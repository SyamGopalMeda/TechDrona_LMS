variable "env" {
  description = "Environment name."
  type        = string
}

variable "aliases" {
  description = "Alternate domain names, e.g. [\"app.techdrona.<tld>\"] (TBD)."
  type        = list(string)
  default     = []
}

variable "alb_dns_name" {
  description = "Public ALB DNS name."
  type        = string
}

variable "origin_verify_header_value" {
  description = "Secret X-TD-Origin-Verify value (from Secrets Manager at plan time)."
  type        = string
  sensitive   = true
}

variable "cloudfront_certificate_arn" {
  description = "ACM certificate in us-east-1 for the CloudFront aliases."
  type        = string
}

variable "block_docs" {
  description = "Block /docs, /openapi.json, /redoc, /metrics, /healthz/deep at the edge (prod)."
  type        = bool
  default     = true
}

variable "log_bucket_domain_name" {
  description = "CloudFront standard log bucket domain (td-log-archive). null disables."
  type        = string
  default     = null
}
