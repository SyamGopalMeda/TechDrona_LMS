output "cloudfront_domain_name" {
  description = "CloudFront distribution domain."
  value       = module.edge.distribution_domain_name
}

output "deploy_role_arn" {
  description = "GitHub OIDC deploy role for this env (store as a GitHub variable)."
  value       = module.ci_oidc.deploy_role_arn
}

output "rds_endpoint" {
  description = "RDS primary endpoint."
  value       = module.rds.endpoint
}

output "secret_arns" {
  description = "Secret shells to populate out of band."
  value       = module.secrets.arns
}
