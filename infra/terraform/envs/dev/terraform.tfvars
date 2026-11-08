# dev: td-dev account, single AZ, scale-to-zero overnight (deployment-and-operations §3.3)
env               = "dev"
sizing_profile    = "dev"
vpc_cidr          = "10.10.0.0/16"
az_count          = 1
nat_gateway_count = 1

rds_instance_class = "db.t4g.medium"
rds_multi_az       = false
redis_node_type    = "cache.t4g.micro"
redis_replicas     = 0

sizing = {
  web                   = { cpu = 256, memory = 512, count = 1 }
  api                   = { cpu = 512, memory = 1024, count = 1 }
  api_webhooks          = { cpu = 256, memory = 512, count = 1 }
  worker                = { cpu = 256, memory = 512, count = 1 }
  worker_critical_count = 1
}

glitchtip_enabled = false

# PLACEHOLDERS (domain TBD, certs/buckets not created yet)
glitchtip_domain           = "https://errors.dev.internal.techdrona.invalid"
ses_domain                 = "dev.mail.techdrona.invalid"
alb_certificate_arn        = "arn:aws:acm:ap-south-1:000000000000:certificate/PLACEHOLDER"
cloudfront_certificate_arn = "arn:aws:acm:us-east-1:000000000000:certificate/PLACEHOLDER"
errors_certificate_arn     = "arn:aws:acm:ap-south-1:000000000000:certificate/PLACEHOLDER"
log_archive_bucket_arn     = "arn:aws:s3:::td-ops-logs-PLACEHOLDER"

# SEC-10: non-secret app settings (PLACEHOLDERS until domain, SES identity, DLT registration
# and GST registration exist). The API refuses to start in prod while any of these is a
# placeholder; credentials live in Secrets Manager (modules/secrets), never here.
api_app_config = {
  TD_PUBLIC_BASE_URL                = "https://dev.techdrona.invalid"
  TD_ALLOWED_ORIGINS                = "https://dev.techdrona.invalid"
  EMAIL_FROM_ADDRESS                = "no-reply@mail.techdrona.invalid"
  EMAIL_FROM_NAME                   = "Tech Drona"
  MSG91_SENDER_ID                   = "REPLACE_SENDER_ID"
  MSG91_DLT_ENTITY_ID               = "REPLACE_DLT_ENTITY_ID"
  MSG91_TEMPLATE_ID_OTP             = "REPLACE_TEMPLATE_ID"
  MSG91_TEMPLATE_ID_SECURITY_NOTICE = "REPLACE_TEMPLATE_ID"
  MSG91_TEMPLATE_ID_PAYMENT         = "REPLACE_TEMPLATE_ID"
  JUDGE0_BASE_URL                   = "https://judge0.example.invalid"
  SELLER_GSTIN                      = "36AAAAA0000A1Z5"
  SELLER_STATE_CODE                 = "36"
  SELLER_LEGAL_NAME                 = "Tech Drona (PLACEHOLDER)"
  SELLER_ADDRESS                    = "PLACEHOLDER ADDRESS"
}

web_app_config = {
  TD_PUBLIC_BASE_URL  = "https://dev.techdrona.invalid"
  TD_API_INTERNAL_URL = "http://api.td-dev.internal:8000" # PLACEHOLDER: service discovery not built yet
}
