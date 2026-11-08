# RDS PostgreSQL 16 (deployment-and-operations §4.1). Direct connections (no RDS Proxy in v1).
# Master password managed by RDS in Secrets Manager; application role passwords (td_owner,
# td_app, td_readonly, td_audit_sealer, td_maintenance, glitchtip) live in secret shells
# created by the `secrets` module and are rotated there. Never put values in Terraform.

resource "aws_db_subnet_group" "this" {
  name       = "td-${var.env}"
  subnet_ids = var.data_subnet_ids
}

resource "aws_db_parameter_group" "this" {
  name   = "td-${var.env}-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }

  parameter {
    name  = "log_lock_waits"
    value = "1"
  }

  parameter {
    name  = "idle_in_transaction_session_timeout"
    value = "60000"
  }

  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements,pg_partman_bgw"
    apply_method = "pending-reboot"
  }

  parameter {
    name  = "rds.log_retention_period"
    value = "4320"
  }
}

resource "aws_db_instance" "primary" {
  identifier     = "td-${var.env}"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  db_name                       = "techdrona"
  username                      = "td_master"
  manage_master_user_password   = true
  master_user_secret_kms_key_id = var.secrets_kms_key_arn

  allocated_storage     = var.allocated_storage_gb
  max_allocated_storage = var.max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = var.kms_key_arn

  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  publicly_accessible    = false
  parameter_group_name   = aws_db_parameter_group.this.name

  backup_retention_period   = var.backup_retention_days
  backup_window             = "18:00-19:00"         # 23:30-00:30 IST
  maintenance_window        = "sat:21:00-sat:22:00" # Sun 02:30-03:30 IST
  copy_tags_to_snapshot     = true
  delete_automated_backups  = false
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "td-${var.env}-final"

  performance_insights_enabled          = true
  performance_insights_kms_key_id       = var.kms_key_arn
  performance_insights_retention_period = 7
  monitoring_interval                   = var.enhanced_monitoring_role_arn == null ? 0 : 15
  monitoring_role_arn                   = var.enhanced_monitoring_role_arn

  enabled_cloudwatch_logs_exports     = ["postgresql"]
  auto_minor_version_upgrade          = true
  iam_database_authentication_enabled = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_db_instance" "replica" {
  count = var.read_replica ? 1 : 0

  identifier             = "td-${var.env}-replica"
  replicate_source_db    = aws_db_instance.primary.identifier
  instance_class         = var.instance_class
  storage_encrypted      = true
  kms_key_id             = var.kms_key_arn
  vpc_security_group_ids = [var.security_group_id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false
  skip_final_snapshot    = true

  performance_insights_enabled    = true
  performance_insights_kms_key_id = var.kms_key_arn
}
