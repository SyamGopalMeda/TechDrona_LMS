variable "env" {
  description = "Environment name."
  type        = string
}

variable "vpc_id" {
  description = "VPC id."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for the ALB."
  type        = list(string)
}

variable "app_subnet_ids" {
  description = "Private app subnets for tasks."
  type        = list(string)
}

variable "app_judge_subnet_ids" {
  description = "Private subnets reserved for worker-judge."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Map from network module (alb, web, api, ...)."
  type        = map(string)
}

variable "api_image" {
  description = "td-api image by digest: <registry>/td-api@sha256:..."
  type        = string
}

variable "web_image" {
  description = "td-web image by digest: <registry>/td-web@sha256:..."
  type        = string
}

variable "alb_certificate_arn" {
  description = "ACM certificate (ap-south-1) for the ALB HTTPS listener."
  type        = string
}

variable "origin_verify_header_value" {
  description = "X-TD-Origin-Verify value expected from CloudFront. Supplied at plan time from Secrets Manager (data source in env), never committed."
  type        = string
  sensitive   = true
}

variable "alb_log_bucket" {
  description = "ALB access log bucket (td-log-archive). null disables."
  type        = string
  default     = null
}

variable "log_retention_days" {
  description = "CloudWatch log retention; exported to S3 for 395 days (privacy §7.1)."
  type        = number
  default     = 30
}

variable "logs_kms_key_arn" {
  description = "td-logs CMK."
  type        = string
}

variable "secrets_kms_key_arn" {
  description = "td-secrets CMK."
  type        = string
}

variable "common_environment" {
  description = "Non-secret env shared by all containers (APP_ENV, AWS_REGION, LOG_FORMAT=json, ...)."
  type        = map(string)
  default     = {}
}

variable "services" {
  description = "Service catalogue (deployment-and-operations §3.1). Key = service name."
  type = map(object({
    image               = string # "api" | "web"
    command             = optional(list(string))
    cpu                 = number
    memory              = number
    desired_count       = optional(number, 1)
    port                = optional(number)
    public              = optional(bool, false) # attached to the public ALB
    security_group      = string
    judge_subnets       = optional(bool, false)
    one_off             = optional(bool, false) # e.g. migrate: task definition only
    stop_timeout        = optional(number, 30)
    min_healthy_percent = optional(number, 100)
    environment         = optional(map(string), {})
    secrets             = optional(map(string), {}) # ENV_NAME => secret ARN
  }))
}

variable "additional_secret_arns" {
  description = "Extra secrets the shared execution role may read (e.g. GlitchTip task secrets)."
  type        = list(string)
  default     = []
}
