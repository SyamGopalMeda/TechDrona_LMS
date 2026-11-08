variable "env" {
  description = "Environment name."
  type        = string
}

variable "vpc_id" {
  description = "VPC id."
  type        = string
}

variable "app_subnet_ids" {
  description = "Private app subnets (internal ALB + GlitchTip tasks)."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Map from network module (needs errors-alb, errors)."
  type        = map(string)
}

variable "cluster_arn" {
  description = "ECS cluster ARN."
  type        = string
}

variable "execution_role_arn" {
  description = "ECS task execution role ARN (must be allowed to read the GlitchTip secrets)."
  type        = string
}

variable "alb_arn_suffix" {
  description = "Public ALB ARN suffix for alarms."
  type        = string
}

variable "sns_kms_key_arn" {
  description = "td-sns CMK."
  type        = string
}

variable "logs_kms_key_arn" {
  description = "td-logs CMK."
  type        = string
}

variable "glitchtip_enabled" {
  description = "Run GlitchTip (staging/prod true; dev optional)."
  type        = bool
  default     = true
}

variable "glitchtip_image" {
  description = "GlitchTip image pinned by digest, e.g. glitchtip/glitchtip@sha256:... (mirrored to ECR)."
  type        = string
}

variable "glitchtip_domain" {
  description = "Internal URL of GlitchTip (internal ALB / private DNS; never public)."
  type        = string
}

variable "errors_certificate_arn" {
  description = "ACM certificate (private CA or internal domain) for the internal errors ALB."
  type        = string
}

variable "glitchtip_database_url_secret_arn" {
  description = "Secret ARN: postgres URL for database glitchtip with its own role (db/glitchtip)."
  type        = string
}

variable "glitchtip_redis_url_secret_arn" {
  description = "Secret ARN: rediss URL of the cache cluster (own DB index/user)."
  type        = string
}

variable "glitchtip_secret_key_arn" {
  description = "Secret ARN: Django SECRET_KEY for GlitchTip."
  type        = string
}
