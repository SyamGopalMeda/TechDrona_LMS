variable "env" {
  description = "Environment name."
  type        = string
}

variable "github_repository" {
  description = "owner/repo allowed to assume the role (PLACEHOLDER until the GitHub repo exists)."
  type        = string
}

variable "github_environment" {
  description = "GitHub Environment name whose jobs may assume the role (staging | production)."
  type        = string
}

variable "create_provider" {
  description = "Create the account-level GitHub OIDC provider (once per account)."
  type        = bool
  default     = true
}
