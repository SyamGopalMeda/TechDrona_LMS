output "key_arns" {
  description = "Map of key alias stem (without env suffix) to key ARN."
  value       = { for k, v in aws_kms_key.this : k => v.arn }
}
