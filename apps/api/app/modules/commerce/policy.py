"""Commerce/entitlement policy defaults and provider settings.

Product policy values belong in ``policy_settings`` (admin module, not shipped yet); until
then these documented defaults apply (PRD BR-ENT-*, FR-COM-*, ADR-0006).

Provider settings are read from the environment with the names of the root ``.env.example``
(§9 Payments). ``SELLER_GSTIN`` / ``SELLER_STATE_CODE`` are requested additions to
``.env.example`` (placeholders below are dev-only and flagged).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import ENV_FILES

ORDER_TTL = timedelta(minutes=30)
PENDING_ORDER_RECHECK = timedelta(minutes=15)
MANDATE_MAX_PAISE = 1_500_000  # RBI e-mandate without AFA per debit (₹15,000)
SUBSCRIPTION_GRACE_DAYS = 5  # commerce.subscription_grace_days (BR-ENT-09; bounds 3-7)
REFUND_WINDOW_DAYS = 7
REFUND_MAX_CONSUMPTION_PCT = Decimal("20")
REFUND_DUAL_ABOVE_PAISE = 2_500_000  # commerce.refund.dual_approval_above_paise
WEBHOOK_TOLERANCE_SECONDS = 300  # monitoring flag only; never an age rejection
WEBHOOK_MAX_ATTEMPTS = 8  # legacy; retries are now bounded by WEBHOOK_RETRY_HORIZON (COM-13)
WEBHOOK_RETRY_HORIZON = timedelta(hours=72)  # keep re-fetching for 3 days before ``failed``
WEBHOOK_BACKOFF_BASE = timedelta(seconds=30)
WEBHOOK_BACKOFF_MAX = timedelta(hours=1)
REFUND_SUBMIT_BACKOFF_BASE = timedelta(minutes=2)  # COM-02 provider re-submit
REFUND_SUBMIT_BACKOFF_MAX = timedelta(hours=2)
REFUND_SUBMIT_ALERT_AFTER = 5  # attempts before ``commerce.refund_submit_stuck``
COUPON_DUAL_PERCENT = Decimal("50")
COUPON_DUAL_REDEMPTIONS = 1000
PRICE_DUAL_DECREASE_PCT = Decimal("20")
MANUAL_GRANT_MAX_DAYS = 365
MANUAL_GRANT_DUAL_DAYS = 90
MANUAL_GRANT_DUAL_USERS = 50
# The placeholder GSTIN shipped in .env.example; PDFs carry a "DEV PLACEHOLDER" banner with it.
PLACEHOLDER_GSTIN = "36AAAAA0000A1Z5"
GST_EXPORT_MAX_DAYS = 366
GST_EXPORT_DUAL_ABOVE_ROWS = 10_000  # role matrix §5: bulk personal-data export > 10,000 rows
GST_EXPORT_DOWNLOAD_HOURS = 24
DOCUMENT_URL_SECONDS = 300  # COM-16 signed URL (5 min)
# GST: 18% on SAC 9992 is an ASSUMPTION pending the CA's confirmation (flagged in the PRD
# open decisions); products carry their own gst_rate so a change needs no code.
DEFAULT_GST_RATE = Decimal("18.00")

REFUND_RULE_TEXT = (
    "Full refund within 7 days of purchase if less than 20% of the content is used and no "
    "certificate is issued (including discounted purchases)."
)


class CommerceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore", case_sensitive=True
    )

    PAYMENTS_PRIMARY_PROVIDER: str = "razorpay"
    PAYMENTS_FALLBACK_PROVIDER_ENABLED: bool = False
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET_PREVIOUS: str = ""
    RAZORPAY_ACCOUNT_ID: str = ""
    RAZORPAY_API_BASE: str = "https://api.razorpay.com/v1"
    CASHFREE_ENV: str = "sandbox"
    CASHFREE_APP_ID: str = ""
    CASHFREE_SECRET_KEY: str = ""
    WEBHOOK_TOLERANCE_SECONDS: int = WEBHOOK_TOLERANCE_SECONDS
    # Requested .env.example additions (dev placeholder values; must be set in prod).
    SELLER_GSTIN: str = "36AAAAA0000A1Z5"
    SELLER_STATE_CODE: str = "36"
    SELLER_LEGAL_NAME: str = "Tech Drona (DEV PLACEHOLDER)"
    # Printed on invoice PDFs. DEV PLACEHOLDER — the registered address must be set in prod.
    SELLER_ADDRESS: str = "DEV PLACEHOLDER ADDRESS, Hyderabad, Telangana"
    # Invoice PDFs and GST exports: private bucket (no public ACL; presigned GET <= 5 min).
    S3_BUCKET_EXPORTS: str = "local-td-exports"
    # ``s3`` (SeaweedFS locally, AWS S3 in prod) or ``memory`` (tests; refused in production).
    COMMERCE_DOCUMENT_STORE: str = "s3"


@lru_cache(maxsize=1)
def commerce_settings() -> CommerceSettings:
    return CommerceSettings()
