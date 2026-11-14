# =============================================================================
# Tech Drona LMS — environment composition (identical in envs/dev, envs/staging, envs/prod;
# per-env differences live ONLY in terraform.tfvars and backend.tf).
# SKELETON — not applied anywhere yet. `terraform validate` passes (1.9.8, init -backend=false).
# Production env/secrets must satisfy apps/api/app/core/startup_checks.py (SEC-10).
# Region lock: ap-south-1 for all data; us-east-1 only for CloudFront/WAF/ACM control plane.
# =============================================================================

locals {
  env = var.env

  common_environment = {
    APP_ENV              = var.env
    AWS_REGION           = var.region
    TZ                   = "UTC"
    LOG_FORMAT           = "json"
    LOG_LEVEL            = "INFO"
    TD_BUSINESS_TIMEZONE = "Asia/Kolkata"
    TD_DISABLE_API_DOCS  = var.env == "prod" ? "true" : "false"
  }

  s = module.secrets.arns

  # SEC-10: configuration shared by EVERY process that boots the API code (uvicorn api,
  # api-webhooks, Celery workers and beat). `run_startup_checks` always requires the HMAC
  # keyrings and, when APP_ENV=prod, refuses fake/dev adapters, placeholder keys, insecure
  # cookies, inline webhook processing and placeholder seller details
  # (apps/api/app/core/startup_checks.py). Values here are selectors/ids only; credentials
  # come from Secrets Manager below. Per-env ids (sender, DLT templates, seller) are in
  # var.api_app_config (terraform.tfvars); placeholders there make prod refuse to start.
  api_runtime_environment = merge({
    TD_COOKIE_SECURE                    = "true"
    TD_K_DEVICE_ACTIVE_VERSION          = "1"
    TD_K_LOGIN_ACTIVE_VERSION           = "1"
    TD_K_TOTP_ACTIVE_VERSION            = "1"
    TD_K_TESTCASE_ACTIVE_VERSION        = "1"
    TD_APP_ENVELOPE_KMS_KEY_ID          = module.kms.key_arns["td-app-envelope"]
    S3_KMS_KEY_ID                       = module.kms.key_arns["td-s3-data"]
    JUDGE_TESTCASE_KMS_KEY_ID           = module.kms.key_arns["td-judge-testcases"]
    S3_BUCKET_UPLOADS                   = "td-uploads-${local.env}"
    S3_BUCKET_CONTENT                   = "td-content-${local.env}"
    S3_BUCKET_CERTIFICATES              = "td-certificates-${local.env}"
    S3_BUCKET_EXPORTS                   = "td-exports-${local.env}"
    EMAIL_PROVIDER                      = "ses"
    SES_CONFIGURATION_SET_TRANSACTIONAL = "td-transactional"
    SMS_PROVIDER                        = "msg91"
    JUDGE_PROVIDER                      = "judge0_cloud"
    VDOCIPHER_MODE                      = "live"
    PAYMENTS_PRIMARY_PROVIDER           = "razorpay"
    TD_COMMERCE_WEBHOOK_MODE            = "queue"
    COMMERCE_DOCUMENT_STORE             = "s3"
    TD_EXPORT_STORE                     = "s3"
  }, var.api_app_config)

  # Secrets every API-code process needs (valueFrom). `<arn>:<json-key>::` selects one key
  # of a JSON secret; the ecs-services module grants GetSecretValue on the base ARN.
  api_runtime_secrets = {
    TD_SERVICE_TOKEN        = local.s["app/service-token"]
    TD_K_DEVICE_KEY_V1      = local.s["keys/k_device"]
    TD_K_LOGIN_KEY_V1       = local.s["keys/k_login"]
    TD_K_TOTP_KEY_V1        = local.s["keys/k_totp"]
    RAZORPAY_KEY_ID         = "${local.s["payments/razorpay"]}:key_id::"
    RAZORPAY_KEY_SECRET     = "${local.s["payments/razorpay"]}:key_secret::"
    RAZORPAY_WEBHOOK_SECRET = local.s["payments/razorpay-webhook"]
    VDOCIPHER_API_SECRET    = local.s["video/vdocipher"]
    MSG91_AUTH_KEY          = local.s["sms/msg91"]
    SENTRY_DSN              = local.s["obs/glitchtip-dsn"]
  }

  # deployment-and-operations §3.1 / §3.2 / §3.3 (cpu units / MiB from var.sizing)
  services = {
    web = {
      image          = "web"
      port           = 3000
      public         = true
      security_group = "web"
      cpu            = var.sizing.web.cpu
      memory         = var.sizing.web.memory
      desired_count  = var.sizing.web.count
      # SEC-01/SEC-10: CloudFront -> ALB -> web. The BFF prefers CloudFront-Viewer-Address
      # (forwarded by Managed-AllViewerExceptHostHeader) and otherwise skips exactly the one
      # XFF entry appended by the ALB. Never 0 behind the edge (0 = no trusted proxy).
      environment = merge({
        TD_TRUSTED_PROXY_HOPS = "1"
        TD_COOKIE_SECURE      = "true"
      }, var.web_app_config)
      secrets = {
        TD_SERVICE_TOKEN        = local.s["app/service-token"]
        TD_CSRF_KEY             = local.s["app/csrf-key"] # web is the ONLY holder (ADR-0010)
        TD_ORIGIN_VERIFY_HEADER = local.s["app/origin-verify"]
        REDIS_CACHE_URL         = local.s["redis/cache"]
        SENTRY_DSN              = local.s["obs/glitchtip-dsn"]
      }
    }
    api = {
      image          = "api"
      port           = 8000
      security_group = "api"
      cpu            = var.sizing.api.cpu
      memory         = var.sizing.api.memory
      desired_count  = var.sizing.api.count
      environment    = merge(local.api_runtime_environment, { TD_ROUTER_SET = "user" })
      secrets = merge(local.api_runtime_secrets, {
        DATABASE_URL         = local.s["db/td_app"]
        REDIS_CACHE_URL      = local.s["redis/cache"]
        REDIS_QUEUE_URL      = local.s["redis/queue"]
        TD_K_TESTCASE_KEY_V1 = local.s["keys/k_testcase"]
      })
    }
    api-webhooks = {
      image          = "api"
      port           = 8000
      public         = true
      security_group = "api-webhooks"
      cpu            = var.sizing.api_webhooks.cpu
      memory         = var.sizing.api_webhooks.memory
      desired_count  = var.sizing.api_webhooks.count
      environment    = merge(local.api_runtime_environment, { TD_ROUTER_SET = "webhooks" })
      secrets = merge(local.api_runtime_secrets, {
        DATABASE_URL    = local.s["db/td_app"]
        REDIS_CACHE_URL = local.s["redis/cache"]
        REDIS_QUEUE_URL = local.s["redis/queue"]
      })
    }
    worker-default = {
      image          = "api"
      security_group = "workers"
      stop_timeout   = 120
      command        = ["sh", "-c", "exec celery -A $TD_CELERY_APP worker -Q default -c 4"]
      cpu            = var.sizing.worker.cpu
      memory         = var.sizing.worker.memory
      desired_count  = var.sizing.worker.count
      environment    = local.api_runtime_environment
      secrets = merge(local.api_runtime_secrets, {
        DATABASE_URL    = local.s["db/td_app"]
        REDIS_CACHE_URL = local.s["redis/cache"]
        REDIS_QUEUE_URL = local.s["redis/queue"]
      })
    }
    worker-critical = {
      image          = "api"
      security_group = "workers"
      stop_timeout   = 120
      command        = ["sh", "-c", "exec celery -A $TD_CELERY_APP worker -Q critical -c 8"]
      cpu            = var.sizing.worker.cpu
      memory         = var.sizing.worker.memory
      desired_count  = var.sizing.worker_critical_count
      environment    = local.api_runtime_environment
      secrets = merge(local.api_runtime_secrets, {
        DATABASE_URL    = local.s["db/td_app"]
        REDIS_CACHE_URL = local.s["redis/cache"]
        REDIS_QUEUE_URL = local.s["redis/queue"]
      })
    }
    worker-maintenance = {
      image          = "api"
      security_group = "workers"
      stop_timeout   = 120
      command        = ["sh", "-c", "exec celery -A $TD_CELERY_APP worker -Q maintenance -c 2"]
      cpu            = 256
      memory         = 512
      environment    = merge(local.api_runtime_environment, { CELERY_QUEUES = "maintenance" })
      secrets = merge(local.api_runtime_secrets, {
        DATABASE_MAINTENANCE_URL = local.s["db/td_maintenance"]
        REDIS_QUEUE_URL          = local.s["redis/queue"]
      })
    }
    worker-judge = {
      image          = "api"
      security_group = "workers"
      judge_subnets  = true
      stop_timeout   = 120
      # COM-09: judging is the DB poller (code_submissions rows, FOR UPDATE SKIP LOCKED), not a
      # Celery consumer: nothing publishes to judge_* queues unless TD_CODING_SEND_TASKS=1
      # (apps/api/app/modules/coding/tasks.py). Same command as docker-compose `worker-judge`.
      command       = ["python", "-m", "app.modules.coding.worker"]
      cpu           = var.sizing.worker.cpu
      memory        = var.sizing.worker.memory
      desired_count = var.sizing.worker.count
      environment   = local.api_runtime_environment
      secrets = merge(local.api_runtime_secrets, {
        DATABASE_URL         = local.s["db/td_app"]
        REDIS_CACHE_URL      = local.s["redis/cache"]
        REDIS_QUEUE_URL      = local.s["redis/queue"]
        JUDGE0_API_KEY       = local.s["judge/judge0"]
        TD_K_TESTCASE_KEY_V1 = local.s["keys/k_testcase"]
      })
    }
    scheduler = {
      image               = "api"
      security_group      = "scheduler"
      min_healthy_percent = 0
      command             = ["sh", "-c", "exec celery -A $TD_CELERY_APP beat --schedule /tmp/celerybeat-schedule"]
      cpu                 = 256
      memory              = 512
      environment         = local.api_runtime_environment
      secrets = merge(local.api_runtime_secrets, {
        DATABASE_URL    = local.s["db/td_app"]
        REDIS_CACHE_URL = local.s["redis/cache"]
        REDIS_QUEUE_URL = local.s["redis/queue"]
      })
    }
    audit-sealer = {
      image               = "api"
      security_group      = "audit-sealer"
      min_healthy_percent = 0
      command             = ["python", "-m", "app.modules.audit.sealer"]
      cpu                 = 256
      memory              = 512
      environment         = { TD_ROLE = "audit_sealer" }
      secrets = {
        DATABASE_AUDIT_SEALER_URL = local.s["db/td_audit_sealer"]
        REDIS_QUEUE_URL           = local.s["redis/queue"]
      }
    }
    migrate = {
      image          = "api"
      security_group = "migrate"
      one_off        = true
      command        = ["alembic", "upgrade", "heads"]
      cpu            = 512
      memory         = 1024
      secrets        = { DATABASE_MIGRATION_URL = local.s["db/td_owner"] }
    }
  }
}

module "kms" {
  source = "../../modules/kms"

  env    = local.env
  region = var.region
}

module "network" {
  source = "../../modules/network"

  env                 = local.env
  region              = var.region
  vpc_cidr            = var.vpc_cidr
  az_count            = var.az_count
  nat_gateway_count   = var.nat_gateway_count
  flow_log_bucket_arn = var.log_archive_bucket_arn
}

module "secrets" {
  source = "../../modules/secrets"

  env         = local.env
  kms_key_arn = module.kms.key_arns["td-secrets"]
}

module "rds" {
  source = "../../modules/rds"

  env                 = local.env
  instance_class      = var.rds_instance_class
  multi_az            = var.rds_multi_az
  read_replica        = var.rds_read_replica
  data_subnet_ids     = module.network.data_subnet_ids
  security_group_id   = module.network.security_group_ids["rds"]
  kms_key_arn         = module.kms.key_arns["td-rds"]
  secrets_kms_key_arn = module.kms.key_arns["td-secrets"]
}

module "redis_cache" {
  source = "../../modules/elasticache"

  env               = local.env
  name              = "cache"
  maxmemory_policy  = "allkeys-lru"
  node_type         = var.redis_node_type
  replicas          = var.redis_replicas
  data_subnet_ids   = module.network.data_subnet_ids
  security_group_id = module.network.security_group_ids["redis-cache"]
  kms_key_arn       = module.kms.key_arns["td-redis"]
}

module "redis_queue" {
  source = "../../modules/elasticache"

  env                     = local.env
  name                    = "queue"
  maxmemory_policy        = "noeviction"
  node_type               = var.redis_node_type
  replicas                = var.redis_replicas
  snapshot_retention_days = 7
  data_subnet_ids         = module.network.data_subnet_ids
  security_group_id       = module.network.security_group_ids["redis-queue"]
  kms_key_arn             = module.kms.key_arns["td-redis"]
}

# --- S3 buckets (deployment-and-operations §4.3) ----------------------------------------
module "bucket" {
  source   = "../../modules/s3-bucket"
  for_each = local.buckets

  name              = "${each.key}-${local.env}"
  kms_key_arn       = module.kms.key_arns[each.value.kms]
  data_class        = each.value.data_class
  object_lock_mode  = each.value.object_lock_mode
  object_lock_years = 8
  lifecycle_rules   = each.value.lifecycle_rules
  access_log_bucket = var.access_log_bucket_name
}

locals {
  # Browser direct uploads (presigned S3 POST from the web origin; audit webstaff 7):
  # td-uploads and td-content need a bucket CORS configuration that allows POST (plus the
  # preflight) from the web origin, e.g. https://app.techdrona.<tld>. The s3-bucket module
  # defines NO aws_s3_bucket_cors_configuration yet, so this is still to be added before
  # browser uploads can work in AWS. The web CSP (apps/web/src/lib/security/csp.ts) derives
  # https://<bucket>.s3.<region>.amazonaws.com from S3_BUCKET_UPLOADS / S3_BUCKET_CONTENT +
  # AWS_REGION; the web task currently gets AWS_REGION (common_environment) but not the
  # bucket names (set them through var.web_app_config or TD_CSP_UPLOAD_ORIGINS).
  # VdoCipher video uploads go to VdoCipher's own uploadLink origin (web env
  # TD_CSP_VDOCIPHER_UPLOAD_ORIGINS, default https://vdo-ap-southeast.s3-accelerate.amazonaws.com):
  # UNVERIFIED, confirm the origin VdoCipher returns for our account region.
  buckets = {
    # Unblock-request attachments (privacy D8: 90 days after case closure). The security
    # purge_closed_cases job deletes them at closure + 90 days; this age-based rule is the
    # backstop for objects the job never reaches (max case life 1 year + 90 days = 455 days).
    td-uploads = { kms = "td-s3-data", data_class = "personal", object_lock_mode = null, lifecycle_rules = [
      { id = "noncurrent-30d", noncurrent_days = 30 },
      { id = "unblock-attachments-455d", prefix = "uploads/unblock_request/", expiration_days = 455, noncurrent_days = 1 },
    ] }
    td-content         = { kms = "td-s3-data", data_class = "content", object_lock_mode = null, lifecycle_rules = [] }
    td-certificates    = { kms = "td-s3-data", data_class = "personal", object_lock_mode = null, lifecycle_rules = [] }
    td-judge-private   = { kms = "td-judge-testcases", data_class = "content", object_lock_mode = null, lifecycle_rules = [{ id = "noncurrent-90d", noncurrent_days = 90 }] }
    td-exports         = { kms = "td-s3-data", data_class = "personal", object_lock_mode = null, lifecycle_rules = [{ id = "expire-7d", expiration_days = 7, noncurrent_days = 1 }] }
    td-backups-logical = { kms = "td-backup", data_class = "backup", object_lock_mode = null, lifecycle_rules = [{ id = "expire-35d", expiration_days = 35, noncurrent_days = 1 }] }
    # Hourly audit chain-head anchors: Object Lock COMPLIANCE, 8 years (R-AUDIT; I-05 resolved).
    # Cannot be shortened or removed by anyone, including root. Hashes only, no personal data.
    td-audit-anchor = { kms = "td-audit-anchor", data_class = "audit", object_lock_mode = "COMPLIANCE", lifecycle_rules = [] }
  }
}

module "ecs" {
  source = "../../modules/ecs-services"

  env                        = local.env
  vpc_id                     = module.network.vpc_id
  public_subnet_ids          = module.network.public_subnet_ids
  app_subnet_ids             = module.network.app_subnet_ids
  app_judge_subnet_ids       = module.network.app_judge_subnet_ids
  security_group_ids         = module.network.security_group_ids
  api_image                  = var.api_image
  web_image                  = var.web_image
  alb_certificate_arn        = var.alb_certificate_arn
  origin_verify_header_value = var.origin_verify_header_value
  logs_kms_key_arn           = module.kms.key_arns["td-logs"]
  secrets_kms_key_arn        = module.kms.key_arns["td-secrets"]
  common_environment         = merge(local.common_environment, { TD_CELERY_APP = var.celery_app })
  services                   = local.services
  additional_secret_arns = [
    module.secrets.arns["db/glitchtip"],
    module.secrets.arns["obs/glitchtip-secret-key"],
  ]
}

module "edge" {
  source = "../../modules/edge"
  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  env                        = local.env
  aliases                    = var.domain_aliases
  alb_dns_name               = module.ecs.alb_dns_name
  origin_verify_header_value = var.origin_verify_header_value
  cloudfront_certificate_arn = var.cloudfront_certificate_arn
  block_docs                 = var.env == "prod"
}

module "ses" {
  source = "../../modules/ses"

  env             = local.env
  domain          = var.ses_domain
  sns_kms_key_arn = module.kms.key_arns["td-sns"]
}

module "observability" {
  source = "../../modules/observability"

  env                               = local.env
  vpc_id                            = module.network.vpc_id
  app_subnet_ids                    = module.network.app_subnet_ids
  security_group_ids                = module.network.security_group_ids
  cluster_arn                       = module.ecs.cluster_arn
  execution_role_arn                = module.ecs.execution_role_arn
  alb_arn_suffix                    = module.ecs.alb_arn_suffix
  sns_kms_key_arn                   = module.kms.key_arns["td-sns"]
  logs_kms_key_arn                  = module.kms.key_arns["td-logs"]
  glitchtip_enabled                 = var.glitchtip_enabled
  glitchtip_image                   = var.glitchtip_image
  glitchtip_domain                  = var.glitchtip_domain
  errors_certificate_arn            = var.errors_certificate_arn
  glitchtip_database_url_secret_arn = module.secrets.arns["db/glitchtip"]
  glitchtip_redis_url_secret_arn    = module.secrets.arns["redis/cache"]
  glitchtip_secret_key_arn          = module.secrets.arns["obs/glitchtip-secret-key"]
}

module "ci_oidc" {
  source = "../../modules/ci-oidc"

  env                = local.env
  github_repository  = var.github_repository
  github_environment = var.env == "prod" ? "production" : var.env
}
