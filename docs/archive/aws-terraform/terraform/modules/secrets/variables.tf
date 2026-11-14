variable "env" {
  description = "Environment name."
  type        = string
}

variable "kms_key_arn" {
  description = "td-secrets CMK."
  type        = string
}

variable "secret_names" {
  description = "Logical secret names (.env.example [SECRET] variables, deployment-and-operations §10.2)."
  type        = list(string)
  default = [
    "db/td_owner", "db/td_app", "db/td_readonly", "db/td_audit_sealer", "db/td_maintenance", "db/glitchtip",
    "redis/cache", "redis/queue",
    "app/service-token", "app/csrf-key", "app/origin-verify",
    "keys/k_device", "keys/k_login", "keys/k_totp", "keys/k_testcase", "keys/k_analytics",
    "payments/razorpay", # JSON {"key_id","key_secret"}
    "payments/razorpay-webhook", "payments/cashfree",
    "video/vdocipher", "judge/judge0", "sms/msg91", "cdn/cloudfront-signing-key",
    "obs/glitchtip-dsn", "obs/glitchtip-secret-key",
  ]
}
