# VPC per workload account (deployment-and-operations §2.2): public / app / app-judge / data /
# endpoints tiers per AZ, NAT per var.nat_gateway_count, data subnets with NO route to NAT or
# IGW, VPC endpoints, flow logs, and least-privilege security groups (SG-to-SG references).
# TODO: AWS Network Firewall egress allowlist (§2.3) for staging/prod; DNS Firewall for dev.

locals {
  azs = slice(var.availability_zones, 0, var.az_count)

  # /16 VPC: public /24 (x.0-2), data /24 (x.10-12), app-judge /24 (x.24-26),
  # endpoints /26 (x.20.0-128), app /20 (x.32.0/20 onwards)
  public_cidrs    = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i)]
  data_cidrs      = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 10 + i)]
  endpoint_cidrs  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 10, 80 + i)]
  app_judge_cidrs = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 24 + i)]
  app_cidrs       = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, 2 + i)]

  interface_endpoints = [
    "ecr.api", "ecr.dkr", "logs", "secretsmanager", "kms", "sts", "ssm", "xray", "monitoring", "email-smtp",
  ]
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "td-${var.env}" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "td-${var.env}" }
}

resource "aws_subnet" "public" {
  count = length(local.azs)

  vpc_id            = aws_vpc.this.id
  cidr_block        = local.public_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = { Name = "td-${var.env}-public-${local.azs[count.index]}", Tier = "public" }
}

resource "aws_subnet" "app" {
  count = length(local.azs)

  vpc_id            = aws_vpc.this.id
  cidr_block        = local.app_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = { Name = "td-${var.env}-app-${local.azs[count.index]}", Tier = "app" }
}

# Dedicated subnets for worker-judge so the egress firewall can scope Judge0 to them (§2.3)
resource "aws_subnet" "app_judge" {
  count = length(local.azs)

  vpc_id            = aws_vpc.this.id
  cidr_block        = local.app_judge_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = { Name = "td-${var.env}-app-judge-${local.azs[count.index]}", Tier = "app-judge" }
}

resource "aws_subnet" "data" {
  count = length(local.azs)

  vpc_id            = aws_vpc.this.id
  cidr_block        = local.data_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = { Name = "td-${var.env}-data-${local.azs[count.index]}", Tier = "data" }
}

resource "aws_subnet" "endpoints" {
  count = length(local.azs)

  vpc_id            = aws_vpc.this.id
  cidr_block        = local.endpoint_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = { Name = "td-${var.env}-endpoints-${local.azs[count.index]}", Tier = "endpoints" }
}

resource "aws_eip" "nat" {
  count = var.nat_gateway_count

  domain = "vpc"
  tags   = { Name = "td-${var.env}-nat-${count.index}" }
}

resource "aws_nat_gateway" "this" {
  count = var.nat_gateway_count

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = { Name = "td-${var.env}-nat-${count.index}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = { Name = "td-${var.env}-public" }
}

resource "aws_route_table_association" "public" {
  count = length(local.azs)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "app" {
  count = length(local.azs)

  vpc_id = aws_vpc.this.id

  dynamic "route" {
    for_each = var.nat_gateway_count > 0 ? [1] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.this[min(count.index, var.nat_gateway_count - 1)].id
    }
  }

  tags = { Name = "td-${var.env}-app-${local.azs[count.index]}" }
}

resource "aws_route_table_association" "app" {
  count = length(local.azs)

  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.app[count.index].id
}

resource "aws_route_table_association" "app_judge" {
  count = length(local.azs)

  subnet_id      = aws_subnet.app_judge[count.index].id
  route_table_id = aws_route_table.app[count.index].id
}

# Data tier: local routes only (no NAT, no IGW)
resource "aws_route_table" "data" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "td-${var.env}-data" }
}

resource "aws_route_table_association" "data" {
  count = length(local.azs)

  subnet_id      = aws_subnet.data[count.index].id
  route_table_id = aws_route_table.data.id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = concat(aws_route_table.app[*].id, [aws_route_table.data.id])

  tags = { Name = "td-${var.env}-s3" }
}

resource "aws_security_group" "endpoints" {
  name        = "td-${var.env}-vpce"
  description = "Interface VPC endpoints: 443 from the VPC"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "HTTPS from VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each = toset(local.interface_endpoints)

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.endpoints[*].id
  security_group_ids  = [aws_security_group.endpoints.id]

  tags = { Name = "td-${var.env}-${each.value}" }
}

resource "aws_flow_log" "this" {
  vpc_id               = aws_vpc.this.id
  traffic_type         = "ALL"
  log_destination_type = "s3"
  log_destination      = var.flow_log_bucket_arn
}

# ---------------------------------------------------------------------------
# Security groups (§2.2). Rules reference SG ids, never CIDRs (except the CloudFront prefix list).
# ---------------------------------------------------------------------------
locals {
  sg_names = [
    "alb", "web", "api", "api-webhooks", "workers", "scheduler", "audit-sealer", "migrate",
    "errors-alb", "errors", "rds", "redis-cache", "redis-queue",
  ]

  sg_ingress = flatten([
    [{ to = "web", from = "alb", port = 3000 }],
    [{ to = "api", from = "web", port = 8000 }],
    [{ to = "api-webhooks", from = "alb", port = 8000 }],
    [for s in ["web", "api", "api-webhooks", "workers", "scheduler", "audit-sealer"] : { to = "errors-alb", from = s, port = 443 }],
    [{ to = "errors", from = "errors-alb", port = 8000 }],
    [for s in ["api", "api-webhooks", "workers", "scheduler", "audit-sealer", "migrate", "errors"] : { to = "rds", from = s, port = 5432 }],
    [for s in ["web", "api", "api-webhooks", "workers", "scheduler", "audit-sealer", "errors"] : { to = "redis-cache", from = s, port = 6379 }],
    [for s in ["api", "api-webhooks", "workers", "scheduler", "audit-sealer"] : { to = "redis-queue", from = s, port = 6379 }],
  ])
}

resource "aws_security_group" "this" {
  for_each = toset(local.sg_names)

  name        = "td-${var.env}-${each.value}"
  description = "td ${var.env} ${each.value}"
  vpc_id      = aws_vpc.this.id

  tags = { Name = "sg-${each.value}" }
}

resource "aws_vpc_security_group_egress_rule" "all" {
  for_each = aws_security_group.this

  security_group_id = each.value.id
  description       = "egress (NAT egress is filtered by Network Firewall)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront" {
  security_group_id = aws_security_group.this["alb"].id
  description       = "443 from CloudFront origin-facing prefix list only"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
}

resource "aws_vpc_security_group_ingress_rule" "sg_to_sg" {
  for_each = { for r in local.sg_ingress : "${r.from}->${r.to}:${r.port}" => r }

  security_group_id            = aws_security_group.this[each.value.to].id
  referenced_security_group_id = aws_security_group.this[each.value.from].id
  description                  = "${each.value.port} from sg-${each.value.from}"
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
}
