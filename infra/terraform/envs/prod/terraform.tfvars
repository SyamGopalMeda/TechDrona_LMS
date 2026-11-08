# prod: td-prod account, 3 AZ, PILOT sizing profile (deployment-and-operations §3.2).
# Switch to the prod profile (§3.1: web 3x(1,2), api 4x(2,4), db.r7g.xlarge + replica,
# cache.r7g.large) at the capacity triggers in §14.4.
env               = "prod"
sizing_profile    = "pilot"
vpc_cidr          = "10.30.0.0/16"
az_count          = 3
nat_gateway_count = 3

rds_instance_class = "db.r7g.large"
rds_multi_az       = true
rds_read_replica   = false
redis_node_type    = "cache.t4g.medium"
redis_replicas     = 1

sizing = {
  web                   = { cpu = 512, memory = 1024, count = 2 }
  api                   = { cpu = 1024, memory = 2048, count = 2 }
  api_webhooks          = { cpu = 256, memory = 512, count = 2 }
  worker                = { cpu = 512, memory = 1024, count = 1 }
  worker_critical_count = 2
}

glitchtip_enabled = true

# PLACEHOLDERS (domain TBD, certs/buckets not created yet)
glitchtip_domain           = "https://errors.internal.techdrona.invalid"
ses_domain                 = "mail.techdrona.invalid"
alb_certificate_arn        = "arn:aws:acm:ap-south-1:000000000000:certificate/PLACEHOLDER"
cloudfront_certificate_arn = "arn:aws:acm:us-east-1:000000000000:certificate/PLACEHOLDER"
errors_certificate_arn     = "arn:aws:acm:ap-south-1:000000000000:certificate/PLACEHOLDER"
log_archive_bucket_arn     = "arn:aws:s3:::td-ops-logs-PLACEHOLDER"

# SEC-10: non-secret app settings (PLACEHOLDERS until domain, SES identity, DLT registration
# and GST registration exist). The API refuses to start in prod while any of these is a
# placeholder; credentials live in Secrets Manager (modules/secrets), never here.
api_app_config = {
  TD_PUBLIC_BASE_URL                = "https://prod.techdrona.invalid"
  TD_ALLOWED_ORIGINS                = "https://prod.techdrona.invalid"
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
  TD_PUBLIC_BASE_URL  = "https://prod.techdrona.invalid"
  TD_API_INTERNAL_URL = "http://api.td-prod.internal:8000" # PLACEHOLDER: service discovery not built yet
}
