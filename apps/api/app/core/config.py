"""Application settings (pydantic-settings).

Variable names follow the root ``.env.example``. Product policy values (timeouts, caps,
thresholds) are NOT settings: they live in ``policy_settings`` (admin module).

Sources, highest priority first: process environment, ``apps/api/.env``, repo-root ``.env``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_API_DIR = Path(__file__).resolve().parents[2]
# Clamped: in the Cloud Functions bundle the code sits at /workspace/app (only 4 parents).
_REPO_ROOT = Path(__file__).resolve().parents[min(4, len(Path(__file__).resolve().parents) - 1)]
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

    # 2. URLs / BFF hop
    TD_PUBLIC_BASE_URL: str = "http://localhost:3000"
    TD_DISABLE_API_DOCS: bool = False
    TD_SERVICE_TOKEN: str = ""
    TD_SERVICE_TOKEN_PREVIOUS: str = ""
    TD_TRUSTED_PROXY_HOPS: int = 0
    TD_COOKIE_SECURE: bool = False
    TD_MAX_BODY_BYTES: int = 256 * 1024
    # DEMO ONLY, owner override: comma-separated e-mails of accounts that sign in with password
    # only (no mandatory MFA enrolment, no new-device code). Ignored when APP_ENV is production.
    TD_MFA_EXEMPT_EMAILS: str = ""
    # Central login (owner decision 2026-11-11): staff may also use "Continue with Google". Google
    # replaces the password step only; staff MFA (or MFA enrolment) still follows. Default off.
    TD_GOOGLE_SIGNIN_STAFF: bool = False
    # TESTING ONLY, owner decision 2026-11-11: switch off the takeover engine (no "We've secured
    # your account" protect-lock, no "Was this you?" step-up; existing protect-locks end at the
    # next sign-in). Ignored when APP_ENV is production.
    TD_ACCOUNT_PROTECTION_OFF: bool = False
    # TESTING ONLY, owner decision 2026-11-12 ("remove the OTP option for now"): email is not
    # integrated, so the new-device code can never arrive. When on, a new device is trusted after
    # the password (and any MFA) without a code. Ignored when APP_ENV is production.
    TD_DEVICE_CODE_OFF: bool = False
    # PERMANENT owner decision 2026-11-12 ("simplify the entire authentication system"): plain
    # email + password sign-in. When on: no MFA prompt or mandatory MFA enrolment, no new-device
    # code, no risk step-up / takeover protect-lock, no "re-confirm it's you" step-up, no
    # concurrent-session prompt (the oldest session ends instead), relaxed password policy, and an
    # Admin's role grants apply at once (no dual-control approval). Password hashing, throttling,
    # CSRF, session cookies and RBAC stay. Unlike the testing switches above this one is honoured
    # in EVERY APP_ENV, production included (owner's choice).
    TD_SIMPLE_AUTH: bool = False

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

    # 6. Keys (versioned HMAC keys and TD_K_<NAME>_ACTIVE_VERSION are read straight from the
    # environment by app.core.security.HmacKeyring / app.core.crypto.AeadKeyring)
    TD_APP_ENVELOPE_KMS_KEY_ID: str = "local"

    # Adapter selectors (checked by the production safety gate)
    JUDGE_PROVIDER: str = "fake"
    SMS_PROVIDER: str = "console"
    EMAIL_PROVIDER: str = "smtp"
    VDOCIPHER_MODE: str = "stub"
    PAYMENTS_PRIMARY_PROVIDER: str = "razorpay"
    S3_KMS_KEY_ID: str = "local"

    # 14. Observability
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

    # Firebase / Firestore (docs/firebase/MIGRATION-PLAN.md, docs/firebase/p0.md). Only used by
    # modules switched to Firestore with TD_STORE_<MODULE>=firestore (app.core.firestore.backend).
    # Dev/tests: FIRESTORE_EMULATOR_HOST (e.g. 127.0.0.1:18080) + a ``demo-*`` project id, so nothing
    # can reach the real project. Other envs: a service-account JSON kept OUTSIDE the repository.
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_SERVICE_ACCOUNT_FILE: str = ""
    FIRESTORE_EMULATOR_HOST: str = ""
    FIRESTORE_DATABASE_ID: str = "(default)"
    # Central login (app.modules.hub): the company website whose Admin Panel the module switcher
    # opens with single sign-on. Its admin lives at <TD_WEBSITE_URL>/admin and reads web_* in the
    # same Firebase project. Empty = the "Company Website Admin" module is hidden.
    TD_WEBSITE_URL: str = "https://techdrona-website.web.app"

    # Runtime host (Firebase migration, docs/firebase/agents/platform.md; read via app.core.runtime).
    # Defaults keep the VM stack exactly as it is: Redis cache/rate limits, Celery + beat.
    # ``firebase`` = the API runs inside the ``lmsApi`` Cloud Function; it then defaults the cache
    # to Firestore and background work to Cloud Tasks + scheduled functions (each overridable).
    TD_RUNTIME: Literal["vm", "firebase"] = "vm"
    TD_CACHE_BACKEND: Literal["", "redis", "firestore"] = ""  # "" = follow TD_RUNTIME
    TD_TASKS_BACKEND: Literal["", "celery", "cloudtasks"] = ""  # "" = follow TD_RUNTIME
    # Cloud Tasks (task-queue functions in functions-lms/main.py): Celery queue -> function name.
    TD_CLOUD_TASKS_LOCATION: str = "asia-south1"
    TD_CLOUD_TASKS_QUEUES: str = "critical=lmsTasksCritical,default=lmsTasks,maintenance=lmsTasksMaintenance"

    @model_validator(mode="after")
    def _firebase_project_from_runtime(self) -> Settings:
        """Cloud Functions reserve every ``FIREBASE_*`` name for user env, so on the Firebase runtime
        the project comes from the platform's ``GOOGLE_CLOUD_PROJECT`` / ``GCLOUD_PROJECT`` (the
        Functions emulator sets them to the ``--project`` id) when ``FIREBASE_PROJECT_ID`` is unset."""
        if self.TD_RUNTIME == "firebase" and not self.FIREBASE_PROJECT_ID.strip():
            import os

            self.FIREBASE_PROJECT_ID = (
                os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT") or ""
            )
        return self

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
    def account_protection_off(self) -> bool:
        """``TD_ACCOUNT_PROTECTION_OFF`` (testing phase; never in production) or simple auth."""
        return (self.TD_ACCOUNT_PROTECTION_OFF and not self.is_production) or self.simple_auth

    @property
    def device_code_off(self) -> bool:
        """``TD_DEVICE_CODE_OFF`` (testing phase, no email; never in production) or simple auth."""
        return (self.TD_DEVICE_CODE_OFF and not self.is_production) or self.simple_auth

    @property
    def simple_auth(self) -> bool:
        """``TD_SIMPLE_AUTH`` (permanent owner decision); honoured in every APP_ENV."""
        return self.TD_SIMPLE_AUTH

    def mfa_exempt(self, email: str | None) -> bool:
        """``TD_MFA_EXEMPT_EMAILS`` (demo owner override); never in production."""
        if self.is_production or not email or not self.TD_MFA_EXEMPT_EMAILS.strip():
            return False
        listed = {e.strip().lower() for e in self.TD_MFA_EXEMPT_EMAILS.split(",") if e.strip()}
        return email.strip().lower() in listed

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
