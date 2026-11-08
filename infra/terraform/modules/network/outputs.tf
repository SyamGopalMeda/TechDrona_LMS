output "vpc_id" {
  description = "VPC id."
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "Public subnet ids (ALB, NAT)."
  value       = aws_subnet.public[*].id
}

output "app_subnet_ids" {
  description = "Private app subnet ids (ECS tasks)."
  value       = aws_subnet.app[*].id
}

output "app_judge_subnet_ids" {
  description = "Private subnets for worker-judge only."
  value       = aws_subnet.app_judge[*].id
}

output "data_subnet_ids" {
  description = "Isolated data subnet ids (RDS, ElastiCache)."
  value       = aws_subnet.data[*].id
}

output "security_group_ids" {
  description = "Map of logical SG name to id."
  value       = { for k, v in aws_security_group.this : k => v.id }
}
