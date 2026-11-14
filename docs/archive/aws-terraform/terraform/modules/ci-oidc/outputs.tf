output "deploy_role_arn" {
  description = "Role ARN to store as a GitHub variable (AWS_<ENV>_DEPLOY_ROLE_ARN)."
  value       = aws_iam_role.deploy.arn
}
