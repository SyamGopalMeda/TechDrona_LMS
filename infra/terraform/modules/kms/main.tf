# Customer-managed KMS keys (deployment-and-operations §6). Automatic yearly rotation on.
# Key policies are minimal here (account root + CloudWatch Logs); per-principal grants are
# added by the modules that own the consuming roles.

data "aws_caller_identity" "current" {}

locals {
  # alias stem => description
  keys = {
    "td-rds"             = "RDS storage, snapshots, Performance Insights"
    "td-redis"           = "ElastiCache at rest"
    "td-s3-data"         = "uploads, content, certificates, exports buckets"
    "td-judge-testcases" = "Envelope keys for hidden test cases (worker-judge only)"
    "td-app-envelope"    = "App-level envelope encryption (TOTP secrets etc.)"
    "td-audit-anchor"    = "td-audit-anchor bucket (Object Lock)"
    "td-secrets"         = "Secrets Manager secrets"
    "td-logs"            = "CloudWatch log groups and log archive"
    "td-backup"          = "Logical backups and snapshot copies"
    "td-sns"             = "SNS alarm topics"
  }
}

resource "aws_kms_key" "this" {
  for_each = local.keys

  description             = "${each.key} (${var.env}): ${each.value}"
  enable_key_rotation     = true
  rotation_period_in_days = 365
  deletion_window_in_days = 30
  multi_region            = each.key == "td-backup"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountRoot"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.region}.amazonaws.com" }
        Action    = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
      },
    ]
  })

  tags = { Name = "${each.key}-${var.env}" }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_kms_alias" "this" {
  for_each = local.keys

  name          = "alias/${each.key}-${var.env}"
  target_key_id = aws_kms_key.this[each.key].key_id
}
