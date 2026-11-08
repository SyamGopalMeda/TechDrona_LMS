# ECS Fargate cluster + services (deployment-and-operations §3). One backend image (td-api) with
# the role selected by command/env; one web image (td-web). Graviton (ARM64), non-root,
# read-only root filesystem, ECS Exec disabled (break-glass only). Images are referenced by
# @sha256 digest (var.api_image / var.web_image are set by the deploy workflow).
# Skeleton: CodeDeploy blue/green, autoscaling policies and the migrate one-off task family
# are TODO (marked below).

data "aws_region" "current" {}

resource "aws_ecs_cluster" "this" {
  name = "td-${var.env}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

resource "aws_cloudwatch_log_group" "service" {
  for_each = var.services

  name              = "/td/${var.env}/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.logs_kms_key_arn
}

# --- IAM --------------------------------------------------------------------------
data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "td-${var.env}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Execution role may read only the secrets referenced by task definitions.
data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    # valueFrom may be "<secret-arn>:<json-key>::" — IAM needs the bare secret ARN.
    resources = distinct([
      for a in concat(flatten([for s in values(var.services) : values(s.secrets)]), var.additional_secret_arns) :
      regex("^arn:[^:]+:secretsmanager:[^:]+:[^:]+:secret:[^:]+", a)
    ])
  }

  statement {
    actions   = ["kms:Decrypt"]
    resources = [var.secrets_kms_key_arn]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# One task role per service (least privilege; service-specific policies attached by callers).
resource "aws_iam_role" "task" {
  for_each = var.services

  name               = "td-${var.env}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# --- Public ALB (origin for CloudFront only) -------------------------------------------
resource "aws_lb" "public" {
  name                       = "td-${var.env}"
  load_balancer_type         = "application"
  internal                   = false
  subnets                    = var.public_subnet_ids
  security_groups            = [var.security_group_ids["alb"]]
  drop_invalid_header_fields = true
  enable_deletion_protection = var.env == "prod"

  dynamic "access_logs" {
    for_each = var.alb_log_bucket == null ? [] : [var.alb_log_bucket]
    content {
      bucket  = access_logs.value
      prefix  = "alb/td-${var.env}"
      enabled = true
    }
  }
}

resource "aws_lb_target_group" "http" {
  for_each = { for k, v in var.services : k => v if v.port != null && v.public }

  name                 = "td-${var.env}-${each.key}"
  port                 = each.value.port
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 30

  health_check {
    path                = "/readyz"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.public.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.alb_certificate_arn

  # Requests without the CloudFront origin-verify header are rejected.
  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "forbidden"
      status_code  = "403"
    }
  }
}

# (1) /api/v1/webhooks/* -> api-webhooks directly (never through the BFF)
resource "aws_lb_listener_rule" "webhooks" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.http["api-webhooks"].arn
  }

  condition {
    path_pattern {
      values = ["/api/v1/webhooks/*"]
    }
  }

  condition {
    http_header {
      http_header_name = "X-TD-Origin-Verify"
      values           = [var.origin_verify_header_value]
    }
  }
}

# (2) everything else -> web (BFF)
resource "aws_lb_listener_rule" "web" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.http["web"].arn
  }

  condition {
    path_pattern {
      values = ["/*"]
    }
  }

  condition {
    http_header {
      http_header_name = "X-TD-Origin-Verify"
      values           = [var.origin_verify_header_value]
    }
  }
}

# --- Task definitions and services --------------------------------------------------------
resource "aws_ecs_task_definition" "this" {
  for_each = var.services

  family                   = "td-${var.env}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task[each.key].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  volume {
    name = "tmp"
  }

  container_definitions = jsonencode([
    {
      name                   = each.key
      image                  = each.value.image == "web" ? var.web_image : var.api_image
      essential              = true
      command                = each.value.command
      readonlyRootFilesystem = true
      user                   = "10001:10001"
      stopTimeout            = each.value.stop_timeout
      portMappings           = each.value.port == null ? [] : [{ containerPort = each.value.port, protocol = "tcp" }]
      mountPoints            = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]
      environment = [
        for k, v in merge(var.common_environment, each.value.environment, { TD_SERVICE_NAME = each.key }) :
        { name = k, value = v }
      ]
      secrets = [for k, arn in each.value.secrets : { name = k, valueFrom = arn }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service[each.key].name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = each.key
        }
      }
      linuxParameters = { initProcessEnabled = true }
    },
  ])
}

resource "aws_ecs_service" "this" {
  for_each = { for k, v in var.services : k => v if !v.one_off }

  name                   = each.key
  cluster                = aws_ecs_cluster.this.id
  task_definition        = aws_ecs_task_definition.this[each.key].arn
  desired_count          = each.value.desired_count
  launch_type            = "FARGATE"
  enable_execute_command = false
  propagate_tags         = "SERVICE"

  # TODO(blue/green): deployment_controller { type = "CODE_DEPLOY" } for web/api/api-webhooks
  # with aws_codedeploy_deployment_group (ECSCanary10Percent10Minutes in prod).
  deployment_minimum_healthy_percent = each.value.min_healthy_percent
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = each.value.judge_subnets ? var.app_judge_subnet_ids : var.app_subnet_ids
    security_groups  = [var.security_group_ids[each.value.security_group]]
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = each.value.port != null && each.value.public ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.http[each.key].arn
      container_name   = each.key
      container_port   = each.value.port
    }
  }

  lifecycle {
    # desired_count is driven by autoscaling / scheduled scaling (TODO), not by Terraform
    ignore_changes = [desired_count]
  }
}
