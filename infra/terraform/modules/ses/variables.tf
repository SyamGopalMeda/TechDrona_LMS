variable "env" {
  description = "Environment name."
  type        = string
}

variable "domain" {
  description = "Sending domain (TBD; per env, e.g. staging.mail.techdrona.<tld>)."
  type        = string
}

variable "sns_kms_key_arn" {
  description = "td-sns CMK."
  type        = string
}
