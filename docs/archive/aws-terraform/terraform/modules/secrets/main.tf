# Secret SHELLS only (deployment-and-operations §7, §10). Values are never in Terraform or
# state: they are set by rotation Lambdas or once via `aws secretsmanager put-secret-value`
# under break-glass. ECS task definitions reference these ARNs (valueFrom).

resource "aws_secretsmanager_secret" "this" {
  for_each = toset(var.secret_names)

  name                    = "td/${var.env}/${each.value}"
  description             = "Tech Drona ${var.env}: ${each.value} (value managed outside Terraform)"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = 30

  tags = { Secret = each.value }
}
