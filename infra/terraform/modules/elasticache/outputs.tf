output "primary_endpoint" {
  description = "Primary endpoint address (use rediss://)."
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}
