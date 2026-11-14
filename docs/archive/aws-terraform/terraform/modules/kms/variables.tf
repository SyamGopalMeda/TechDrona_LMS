variable "env" {
  description = "Environment name (dev | staging | prod)."
  type        = string
}

variable "region" {
  description = "AWS region (ap-south-1)."
  type        = string
  default     = "ap-south-1"
}
