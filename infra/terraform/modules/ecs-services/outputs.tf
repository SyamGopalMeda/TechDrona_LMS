output "cluster_arn" {
  description = "ECS cluster ARN."
  value       = aws_ecs_cluster.this.arn
}

output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "alb_dns_name" {
  description = "Public ALB DNS name (CloudFront origin)."
  value       = aws_lb.public.dns_name
}

output "task_role_arns" {
  description = "Map of service name to task role ARN (attach service-specific policies)."
  value       = { for k, v in aws_iam_role.task : k => v.arn }
}

output "execution_role_arn" {
  description = "Shared task execution role ARN."
  value       = aws_iam_role.execution.arn
}

output "alb_arn_suffix" {
  description = "Public ALB ARN suffix (CloudWatch alarm dimension)."
  value       = aws_lb.public.arn_suffix
}
