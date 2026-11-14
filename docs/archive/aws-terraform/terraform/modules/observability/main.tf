# Observability (deployment-and-operations §11): SNS alarm topics, a starter set of alarms
# from the §11.6 catalogue, and self-hosted GlitchTip on ECS Fargate (ADR-0014):
#   errors-web + errors-worker behind an INTERNAL ALB (sg-errors-alb), database `glitchtip`
#   on the shared RDS (own role, secret db/glitchtip), `cache` Redis, 90-day retention.
# No error-tracking egress: no sentry.io anywhere. Tracing stays OTel -> ADOT -> X-Ray.
# TODO: full alarm catalogue, dashboards, Chatbot, log subscriptions/exports to td-log-archive.

data "aws_region" "current" {}

resource "aws_sns_topic" "alarms" {
  for_each = toset(["page", "warn"])

  name              = "td-${var.env}-alarms-${each.value}"
  kms_master_key_id = var.sns_kms_key_arn
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "td-${var.env}-alb-5xx"
  alarm_description   = "Public ALB target 5xx rate (deploy rollback alarm, §8.2)"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = var.alb_arn_suffix }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = 50
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms["page"].arn]
}

# --- GlitchTip (ADR-0014) ---------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "glitchtip" {
  name              = "/td/${var.env}/errors"
  retention_in_days = 30
  kms_key_id        = var.logs_kms_key_arn
}

resource "aws_lb" "errors" {
  name                       = "td-${var.env}-errors"
  load_balancer_type         = "application"
  internal                   = true
  subnets                    = var.app_subnet_ids
  security_groups            = [var.security_group_ids["errors-alb"]]
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "errors" {
  name        = "td-${var.env}-errors"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    path    = "/_health/"
    matcher = "200"
  }
}

resource "aws_lb_listener" "errors" {
  load_balancer_arn = aws_lb.errors.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.errors_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.errors.arn
  }
}

locals {
  glitchtip_roles = {
    errors-web    = { command = null, cpu = 512, memory = 1024, port = 8000 }
    errors-worker = { command = ["./bin/run-celery-with-beat.sh"], cpu = 256, memory = 512, port = null }
  }
}

resource "aws_ecs_task_definition" "glitchtip" {
  for_each = local.glitchtip_roles

  family                   = "td-${var.env}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = var.execution_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name         = each.key
      image        = var.glitchtip_image
      essential    = true
      command      = each.value.command
      portMappings = each.value.port == null ? [] : [{ containerPort = each.value.port, protocol = "tcp" }]
      environment = [
        { name = "GLITCHTIP_DOMAIN", value = var.glitchtip_domain },
        { name = "GLITCHTIP_MAX_EVENT_LIFE_DAYS", value = "90" },
        { name = "ENABLE_USER_REGISTRATION", value = "false" },
        { name = "ENABLE_OBSERVABILITY_API", value = "false" },
      ]
      secrets = [
        { name = "DATABASE_URL", valueFrom = var.glitchtip_database_url_secret_arn },
        { name = "REDIS_URL", valueFrom = var.glitchtip_redis_url_secret_arn },
        { name = "SECRET_KEY", valueFrom = var.glitchtip_secret_key_arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.glitchtip.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = each.key
        }
      }
    },
  ])
}

resource "aws_ecs_service" "glitchtip" {
  for_each = local.glitchtip_roles

  name                   = each.key
  cluster                = var.cluster_arn
  task_definition        = aws_ecs_task_definition.glitchtip[each.key].arn
  desired_count          = var.glitchtip_enabled ? 1 : 0
  launch_type            = "FARGATE"
  enable_execute_command = false

  network_configuration {
    subnets          = var.app_subnet_ids
    security_groups  = [var.security_group_ids["errors"]]
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = each.value.port == null ? [] : [1]
    content {
      target_group_arn = aws_lb_target_group.errors.arn
      container_name   = each.key
      container_port   = each.value.port
    }
  }
}
