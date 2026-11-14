variable "env" {
  description = "Environment name."
  type        = string
}

variable "engine_version" {
  description = "PostgreSQL 16 minor version (parameter group pinned)."
  type        = string
  default     = "16.6"
}

variable "instance_class" {
  description = "dev db.t4g.medium, staging/pilot db.r7g.large, prod db.r7g.xlarge."
  type        = string
}

variable "multi_az" {
  description = "Multi-AZ deployment (staging/prod true)."
  type        = bool
  default     = true
}

variable "read_replica" {
  description = "Create one async read replica (prod profile)."
  type        = bool
  default     = false
}

variable "allocated_storage_gb" {
  description = "gp3 storage (GB)."
  type        = number
  default     = 100
}

variable "max_allocated_storage_gb" {
  description = "Storage autoscaling ceiling (GB)."
  type        = number
  default     = 2000
}

variable "backup_retention_days" {
  description = "PITR window (35 = maximum)."
  type        = number
  default     = 35
}

variable "data_subnet_ids" {
  description = "Isolated data subnets."
  type        = list(string)
}

variable "security_group_id" {
  description = "sg-rds."
  type        = string
}

variable "kms_key_arn" {
  description = "td-rds CMK."
  type        = string
}

variable "secrets_kms_key_arn" {
  description = "td-secrets CMK (managed master password)."
  type        = string
}

variable "enhanced_monitoring_role_arn" {
  description = "IAM role for Enhanced Monitoring (15 s). null disables."
  type        = string
  default     = null
}
