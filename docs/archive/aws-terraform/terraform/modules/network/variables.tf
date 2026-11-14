variable "env" {
  description = "Environment name."
  type        = string
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "ap-south-1"
}

variable "vpc_cidr" {
  description = "VPC CIDR (dev 10.10.0.0/16, staging 10.20.0.0/16, prod 10.30.0.0/16)."
  type        = string
}

variable "availability_zones" {
  description = "Candidate AZs."
  type        = list(string)
  default     = ["ap-south-1a", "ap-south-1b", "ap-south-1c"]
}

variable "az_count" {
  description = "Number of AZs actually used (dev 1, staging/prod 3)."
  type        = number
  default     = 3
}

variable "nat_gateway_count" {
  description = "NAT gateways (dev 1, staging 1, prod 3)."
  type        = number
  default     = 1
}

variable "flow_log_bucket_arn" {
  description = "S3 bucket ARN (td-log-archive account) for VPC flow logs."
  type        = string
}
