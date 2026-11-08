output "dkim_tokens" {
  description = "Easy DKIM tokens (create CNAMEs in Route 53)."
  value       = aws_sesv2_email_identity.domain.dkim_signing_attributes[0].tokens
}

output "feedback_topic_arn" {
  description = "SNS topic receiving bounces and complaints."
  value       = aws_sns_topic.feedback.arn
}
