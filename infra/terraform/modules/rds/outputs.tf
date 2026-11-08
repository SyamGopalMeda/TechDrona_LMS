output "endpoint" {
  description = "Primary endpoint (host:port)."
  value       = aws_db_instance.primary.endpoint
}

output "replica_endpoint" {
  description = "Read replica endpoint, or null."
  value       = try(aws_db_instance.replica[0].endpoint, null)
}

output "master_user_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master password (break-glass only)."
  value       = try(aws_db_instance.primary.master_user_secret[0].secret_arn, null)
}
