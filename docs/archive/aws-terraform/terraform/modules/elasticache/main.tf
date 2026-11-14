# ElastiCache Redis 7 (deployment-and-operations §4.2). Instantiated twice per env:
#   cache: allkeys-lru, disposable (sessions read-through copy, rate limits, locks, GlitchTip)
#   queue: noeviction (Celery broker, Streams, deadline ZSET) — never used for sessions
# In-transit TLS, at-rest KMS, AUTH token from Secrets Manager (value set outside Terraform).

resource "aws_elasticache_subnet_group" "this" {
  name       = "td-${var.env}-${var.name}"
  subnet_ids = var.data_subnet_ids
}

resource "aws_elasticache_parameter_group" "this" {
  name   = "td-${var.env}-${var.name}-redis7"
  family = "redis7"

  parameter {
    name  = "maxmemory-policy"
    value = var.maxmemory_policy
  }
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "td-${var.env}-${var.name}"
  description          = "td ${var.env} ${var.name} (${var.maxmemory_policy})"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.node_type
  port                 = 6379

  num_cache_clusters         = var.replicas + 1
  automatic_failover_enabled = var.replicas > 0
  multi_az_enabled           = var.replicas > 0

  subnet_group_name    = aws_elasticache_subnet_group.this.name
  security_group_ids   = [var.security_group_id]
  parameter_group_name = aws_elasticache_parameter_group.this.name

  at_rest_encryption_enabled = true
  kms_key_id                 = var.kms_key_arn
  transit_encryption_enabled = true
  transit_encryption_mode    = "required"
  # AUTH token / RBAC users: managed out of band (Secrets Manager rotation), never in state.

  snapshot_retention_limit = var.snapshot_retention_days
  snapshot_window          = "19:00-20:00"
  maintenance_window       = "sat:22:00-sat:23:00"
  apply_immediately        = false
}
