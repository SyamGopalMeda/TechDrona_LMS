output "alarm_topic_arns" {
  description = "SNS alarm topics (page, warn)."
  value       = { for k, v in aws_sns_topic.alarms : k => v.arn }
}

output "errors_alb_dns_name" {
  description = "Internal GlitchTip ALB DNS name (DSN host; VPC-only)."
  value       = aws_lb.errors.dns_name
}
