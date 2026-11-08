"""Application settings (pydantic-settings).

Variable names follow the root ``.env.example``. Product policy values (timeouts, caps,
thresholds) are NOT settings: they live in ``policy_settings`` (admin module).

Sources, highest priority first: process environment, ``apps/api/.env``, repo-root ``.env``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_API_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[4]
ENV_FILES: tuple[Path, ...] = (_REPO_ROOT / ".env", _API_DIR / ".env")

PRODUCTION_ENVS = frozenset({"prod", "production"})

LOCAL_DB_URL = "postgresql+asyncpg://td_app:local_app_pw_REPLACE@localhost:5432/techdrona"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # 1. Runtime
    APP_ENV: Literal["local", "test", "dev", "staging", "prod", "production"] = "local"
    TD_SERVICE_NAME: str = "api"
    TD_ROUTER_SET: Literal["user", "webhooks", "all"] = "user"
    TD_RELEASE: str = "local-dev"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"
    TD_BUSINESS_TIMEZONE: str = "Asia/Kolkata"

    # 2. URLs / BFF hop
    TD_PUBLIC_BASE_URL: str = "http://localhost:3000"
    TD_ALLOWED_ORIGINS: str = "http://localhost:3000"
    TD_DISABLE_API_DOCS: bool = False
    TD_SERVICE_TOKEN: str = ""
    TD_SERVICE_TOKEN_PREVIOUS: str = ""
    TD_TRUSTED_PROXY_HOPS: int = 0
    TD_COOKIE_SECURE: bool = False
    TD_MAX_BODY_BYTES: int = 256 * 1024

    # 3. PostgreSQL
    DATABASE_URL: str = LOCAL_DB_URL
    DATABASE_READ_URL: str = ""
    DATABASE_MIGRATION_URL: str = ""
    DATABASE_AUDIT_SEALER_URL: str = ""
    # td_maintenance login: runs only the maint.* SECURITY DEFINER functions (DB-02/DB-04). The
    # maintenance jobs skip (with a warning) when unset; they never fall back to DATABASE_URL.
    DATABASE_MAINTENANCE_URL: str = ""
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 2
    DB_POOL_TIMEOUT_SECONDS: int = 5
    # Liveness check on every pool checkout. With asyncpg it costs BEGIN + ";" + ROLLBACK (3 round
    # trips per checkout); keep it on where the DB can fail over (RDS), turn it off on a stable
    # local stack and rely on DB_POOL_RECYCLE_SECONDS instead.
    DB_POOL_PRE_PING: bool = True
    # Replace pooled connections older than this (-1 = never).
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_STATEMENT_TIMEOUT_MS: int = 15000
    DB_STATEMENT_CACHE_SIZE: int = 100
    # Optional: role assumed with SET LOCAL ROLE at the start of every app transaction.
    # Leave empty when DATABASE_URL already logs in as td_app (default, docker-compose and AWS).
    # Set to "td_app" only if you deliberately connect as a superuser/owner locally.
    TD_DB_SET_ROLE: str = ""

    # 4. Redis
    REDIS_CACHE_URL: str = "redis://localhost:6379/0"
    REDIS_QUEUE_URL: str = "redis://localhost:6380/0"

    # 6. Keys (versioned HMAC keys are read dynamically by app.core.security.HmacKeyring)
    TD_K_DEVICE_ACTIVE_VERSION: int = 1
    TD_K_LOGIN_ACTIVE_VERSION: int = 1
    TD_APP_ENVELOPE_KMS_KEY_ID: str = "local"

    # Adapter selectors (checked by the production safety gate)
    JUDGE_PROVIDER: str = "fake"
    SMS_PROVIDER: str = "console"
    EMAIL_PROVIDER: str = "smtp"
    VDOCIPHER_MODE: str = "stub"
    PAYMENTS_PRIMARY_PROVIDER: str = "razorpay"
    S3_KMS_KEY_ID: str = "local"

    # 14. Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    SENTRY_DSN: str = ""

    # Audit sealer
    TD_AUDIT_SEALER_INTERVAL_SECONDS: float = Field(default=2.0, gt=0)
    TD_AUDIT_SEALER_BATCH: int = Field(default=500, gt=0)
    # Celery beat also schedules the sealer (needs DATABASE_AUDIT_SEALER_URL on the worker);
    # set false where the dedicated audit-sealer service runs instead.
    TD_AUDIT_SEALER_BEAT_ENABLED: bool = True

    # Outbox relay (Celery beat -> app.worker.outbox_relay)
    TD_OUTBOX_RELAY_INTERVAL_SECONDS: float = Field(default=5.0, gt=0)
    TD_OUTBOX_RELAY_BATCH: int = Field(default=200, gt=0)
    TD_OUTBOX_MAX_ATTEMPTS: int = Field(default=10, gt=0)
    # Payment webhooks: "inline" processes right after ingest (local/dev/tests); "queue" hands
    # the row to the Celery ``critical`` queue (``commerce.process_webhook_event``) and relies on
    # the ``commerce.webhook_retry`` beat sweep if the broker is down.
    TD_COMMERCE_WEBHOOK_MODE: Literal["inline", "queue"] = "inline"

    # TOTP secret encryption (AES-256-GCM keyring; keys TD_K_TOTP_KEY_V{n} read by app.core.crypto)
    TD_K_TOTP_ACTIVE_VERSION: int = 1

    # Email (SES in production; SMTP/Mailpit locally) — read by notifications.adapters too.
    EMAIL_FROM_ADDRESS: str = ""
    EMAIL_FROM_NAME: str = "Tech Drona"
    AWS_REGION: str = ""
    SES_CONFIGURATION_SET_TRANSACTIONAL: str = ""
    # SMS (MSG91 Flow API with DLT-registered templates)
    MSG91_AUTH_KEY: str = ""
    MSG91_SENDER_ID: str = ""
    MSG91_DLT_ENTITY_ID: str = ""
    MSG91_TEMPLATE_ID_OTP: str = ""
    MSG91_TEMPLATE_ID_SECURITY_NOTICE: str = ""
    MSG91_TEMPLATE_ID_PAYMENT: str = ""
    MSG91_BASE_URL: str = "https://control.msg91.com/api/v5"

    # Commerce values the production gate must see (the commerce module reads the same
    # variables through ``CommerceSettings``; empty here means "not configured").
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    SELLER_GSTIN: str = ""
    SELLER_LEGAL_NAME: str = ""
    SELLER_ADDRESS: str = ""

    # Celery beat leader lock (ADR-0008: single scheduler; a second replica waits as standby)
    TD_SCHEDULER_LEADER_LOCK_ENABLED: bool = True
    TD_SCHEDULER_LEADER_LOCK_TTL_SECONDS: int = Field(default=30, ge=5)
    # Worker liveness file touched from the worker's event loop (container healthcheck, E2E-06)
    TD_WORKER_HEALTH_FILE: str = ""
    TD_WORKER_HEALTH_INTERVAL_SECONDS: float = Field(default=15.0, gt=0)

    @field_validator("TD_DB_SET_ROLE")
    @classmethod
    def _role_ident(cls, v: str) -> str:
        if v and not v.replace("_", "").isalnum():
            raise ValueError("TD_DB_SET_ROLE must be a plain identifier")
        return v

    @property
    def is_production(self) -> bool:
        return self.APP_ENV in PRODUCTION_ENVS

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.TD_ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def migration_url(self) -> str:
        return self.DATABASE_MIGRATION_URL or self.DATABASE_URL

    @property
    def sealer_url(self) -> str:
        return self.DATABASE_AUDIT_SEALER_URL or self.DATABASE_URL


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """For tests: re-read the environment on next ``get_settings()``."""
    get_settings.cache_clear()
