variable "name" {
  description = "Globally unique bucket name, e.g. td-uploads-prod."
  type        = string
}

variable "kms_key_arn" {
  description = "CMK used for SSE-KMS."
  type        = string
}

variable "data_class" {
  description = "Tag: personal | content | audit | logs | backup | state."
  type        = string
  default     = "personal"
}

variable "object_lock_mode" {
  description = "null (no Object Lock), GOVERNANCE or COMPLIANCE. COMPLIANCE cannot be shortened or removed, even by root."
  type        = string
  default     = null

  validation {
    condition     = var.object_lock_mode == null || contains(["GOVERNANCE", "COMPLIANCE"], coalesce(var.object_lock_mode, "x"))
    error_message = "object_lock_mode must be null, GOVERNANCE or COMPLIANCE."
  }
}

variable "object_lock_years" {
  description = "Default Object Lock retention in years (td-audit-anchor: 8)."
  type        = number
  default     = 8
}

variable "lifecycle_rules" {
  description = "Lifecycle rules."
  type = list(object({
    id              = string
    prefix          = optional(string, "")
    expiration_days = optional(number)
    noncurrent_days = optional(number)
  }))
  default = []
}

variable "access_log_bucket" {
  description = "Target bucket for server access logs (td-log-archive). null disables."
  type        = string
  default     = null
}

variable "extra_policy_json" {
  description = "Additional bucket policy statements (JSON) merged with the TLS-only policy."
  type        = string
  default     = null
}
