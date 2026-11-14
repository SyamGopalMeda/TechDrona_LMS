output "arns" {
  description = "Map of logical secret name to ARN."
  value       = { for k, v in aws_secretsmanager_secret.this : k => v.arn }
}
