variable "env" {
  description = "Environment name."
  type        = string
}

variable "name" {
  description = "cache | queue."
  type        = string

  validation {
    condition     = contains(["cache", "queue"], var.name)
    error_message = "name must be cache or queue."
  }
}

variable "maxmemory_policy" {
  description = "allkeys-lru (cache) or noeviction (queue)."
  type        = string
}

variable "node_type" {
  description = "dev cache.t4g.micro, staging cache.t4g.small, pilot cache.t4g.medium, prod cache.r7g.large."
  type        = string
}

variable "replicas" {
  description = "Replica count (0 = single node, dev only)."
  type        = number
  default     = 1
}

variable "snapshot_retention_days" {
  description = "Daily snapshot retention (queue: 1+)."
  type        = number
  default     = 1
}

variable "data_subnet_ids" {
  description = "Isolated data subnets."
  type        = list(string)
}

variable "security_group_id" {
  description = "sg-redis-cache or sg-redis-queue."
  type        = string
}

variable "kms_key_arn" {
  description = "td-redis CMK."
  type        = string
}
