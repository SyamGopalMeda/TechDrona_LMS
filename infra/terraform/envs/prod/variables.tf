variable "env" {
  description = "dev | staging | prod."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be dev, staging or prod."
  }
}

variable "region" {
  description = "Data region. India residency: ap-south-1 only."
  type        = string
  default     = "ap-south-1"

  validation {
    condition     = var.region == "ap-south-1"
    error_message = "All data stores must be in ap-south-1."
  }
}

variable "sizing_profile" {
  description = "dev | staging | pilot | prod (deployment-and-operations §3)."
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR."
  type        = string
}

variable "az_count" {
  description = "AZs used."
  type        = number
}

variable "nat_gateway_count" {
  description = "NAT gateways."
  type        = number
}

variable "rds_instance_class" {
  description = "RDS instance class."
  type        = string
}

variable "rds_multi_az" {
  description = "RDS Multi-AZ."
  type        = bool
}

variable "rds_read_replica" {
  description = "RDS read replica."
  type        = bool
  default     = false
}

variable "redis_node_type" {
  description = "ElastiCache node type (both clusters)."
  type        = string
}

variable "redis_replicas" {
  description = "Replicas per Redis cluster."
  type        = number
}

variable "sizing" {
  description = "ECS task sizing (cpu units, memory MiB, count)."
  type = object({
    web                   = object({ cpu = number, memory = number, count = number })
    api                   = object({ cpu = number, memory = number, count = number })
    api_webhooks          = object({ cpu = number, memory = number, count = number })
    worker                = object({ cpu = number, memory = number, count = number })
    worker_critical_count = number
  })
}

variable "glitchtip_enabled" {
  description = "Run self-hosted GlitchTip (ADR-0014)."
  type        = bool
  default     = true
}

# --- values that do not exist yet: PLACEHOLDERS, supplied at plan time ----------------------
variable "api_image" {
  description = "td-api image by digest (set by deploy workflow)."
  type        = string
  default     = "PLACEHOLDER.dkr.ecr.ap-south-1.amazonaws.com/td-api@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

variable "web_image" {
  description = "td-web image by digest (set by deploy workflow)."
  type        = string
  default     = "PLACEHOLDER.dkr.ecr.ap-south-1.amazonaws.com/td-web@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

variable "glitchtip_image" {
  description = "GlitchTip image by digest (mirrored to ECR)."
  type        = string
  default     = "PLACEHOLDER.dkr.ecr.ap-south-1.amazonaws.com/glitchtip@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

variable "celery_app" {
  description = "Celery app import path inside td-api (Foundation owner)."
  type        = string
  default     = "app.worker"
}

variable "glitchtip_domain" {
  description = "Internal GlitchTip URL."
  type        = string
}

variable "domain_aliases" {
  description = "CloudFront aliases (domain TBD)."
  type        = list(string)
  default     = []
}

variable "ses_domain" {
  description = "SES sending domain (TBD)."
  type        = string
}

variable "alb_certificate_arn" {
  description = "ACM cert (ap-south-1) for the public ALB."
  type        = string
}

variable "cloudfront_certificate_arn" {
  description = "ACM cert (us-east-1) for CloudFront."
  type        = string
}

variable "errors_certificate_arn" {
  description = "ACM cert for the internal GlitchTip ALB."
  type        = string
}

variable "origin_verify_header_value" {
  description = "X-TD-Origin-Verify secret. Pass via TF_VAR_origin_verify_header_value from Secrets Manager in CI; never commit."
  type        = string
  sensitive   = true
}

variable "log_archive_bucket_arn" {
  description = "td-ops-logs bucket ARN in td-log-archive (flow logs)."
  type        = string
}

variable "access_log_bucket_name" {
  description = "S3 server access log bucket (td-log-archive)."
  type        = string
  default     = null
}

variable "github_repository" {
  description = "owner/repo for the OIDC trust policy (PLACEHOLDER)."
  type        = string
  default     = "techdrona/techdrona-lms"
}

variable "api_app_config" {
  description = <<-EOT
    Non-secret per-env settings merged into every API-code service (SEC-10): public URLs,
    sender identities, DLT template ids, seller details. Credentials never go here.
    In prod, placeholder values are refused by the API startup gate (fail closed).
  EOT
  type        = map(string)
  default     = {}
}

variable "web_app_config" {
  description = "Non-secret per-env settings for the web (BFF) service, e.g. TD_API_INTERNAL_URL, TD_PUBLIC_BASE_URL."
  type        = map(string)
  default     = {}
}
