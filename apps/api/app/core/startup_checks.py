"""Startup safety gate: refuse fake adapters, local keys and debug settings in production.

Modules with their own adapters register extra checks::

    from app.core.startup_checks import register_fake_adapter
    register_fake_adapter("payments", lambda s: s.PAYMENTS_PRIMARY_PROVIDER == "fake")
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.config import Settings
from app.core.crypto import REQUIRED_AEAD_KEYRINGS, AeadKeyring, CryptoError
from app.core.security import REQUIRED_KEYRINGS, KeyringError, get_keyring

FakeCheck = Callable[[Settings], bool]

# Providers with a real adapter in this build (anything else is refused in production).
IMPLEMENTED_EMAIL_PROVIDERS = frozenset({"ses", "smtp"})
IMPLEMENTED_SMS_PROVIDERS = frozenset({"msg91"})
# The placeholder GSTIN shipped in .env.example (commerce.policy.PLACEHOLDER_GSTIN).
PLACEHOLDER_GSTIN = "36AAAAA0000A1Z5"

_fake_checks: dict[str, FakeCheck] = {
    "judge (JUDGE_PROVIDER=fake)": lambda s: s.JUDGE_PROVIDER.lower() == "fake",
    "sms (SMS_PROVIDER=console)": lambda s: s.SMS_PROVIDER.lower() in {"console", "fake"},
    "email (EMAIL_PROVIDER=fake/console/memory)": lambda s: (
        s.EMAIL_PROVIDER.lower() in {"fake", "console", "memory"}
    ),
    "video (VDOCIPHER_MODE=stub)": lambda s: s.VDOCIPHER_MODE.lower() in {"stub", "fake"},
    "payments (fake provider)": lambda s: s.PAYMENTS_PRIMARY_PROVIDER.lower() == "fake",
    "envelope KMS (local dev key)": lambda s: s.TD_APP_ENVELOPE_KMS_KEY_ID == "local",
    "S3 KMS (local)": lambda s: s.S3_KMS_KEY_ID == "local",
}


class UnsafeConfigurationError(RuntimeError):
    pass


def register_fake_adapter(name: str, is_fake: FakeCheck) -> None:
    _fake_checks[name] = is_fake


def _placeholder(value: str) -> bool:
    v = (value or "").strip()
    return not v or "REPLACE" in v.upper() or "PLACEHOLDER" in v.upper() or v.endswith(".invalid")


def _provider_problems(s: Settings) -> list[str]:
    """COM-06/COM-07: unimplemented providers and missing provider configuration."""
    out: list[str] = []
    email, sms = s.EMAIL_PROVIDER.lower(), s.SMS_PROVIDER.lower()
    if email not in IMPLEMENTED_EMAIL_PROVIDERS | {"fake", "console", "memory"}:
        out.append(f"EMAIL_PROVIDER={email} has no adapter in this build")
    if sms not in IMPLEMENTED_SMS_PROVIDERS | {"fake", "console"}:
        out.append(f"SMS_PROVIDER={sms} has no adapter in this build")
    if email == "ses":
        if _placeholder(s.EMAIL_FROM_ADDRESS) or "@" not in s.EMAIL_FROM_ADDRESS:
            out.append("EMAIL_FROM_ADDRESS must be a real verified SES sender in production")
        if not s.AWS_REGION:
            out.append("AWS_REGION is required for the SES email adapter")
    if sms == "msg91":
        for name in ("MSG91_AUTH_KEY", "MSG91_SENDER_ID", "MSG91_TEMPLATE_ID_OTP"):
            if _placeholder(getattr(s, name)):
                out.append(f"{name} missing or placeholder (MSG91 SMS adapter)")
    return out


def _commerce_problems(s: Settings) -> list[str]:
    """COM-07 / COM-13: live payment credentials, real seller identity, async webhooks."""
    out: list[str] = []
    if s.PAYMENTS_PRIMARY_PROVIDER.lower() == "razorpay":
        for name in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
            if _placeholder(getattr(s, name)):
                out.append(f"{name} missing or placeholder")
        if s.RAZORPAY_KEY_ID.startswith("rzp_test_"):
            out.append("RAZORPAY_KEY_ID is a test-mode key (rzp_test_) in production")
    if not s.SELLER_GSTIN or s.SELLER_GSTIN.strip().upper() == PLACEHOLDER_GSTIN:
        out.append("SELLER_GSTIN missing or the .env.example placeholder")
    for name in ("SELLER_LEGAL_NAME", "SELLER_ADDRESS"):
        if _placeholder(getattr(s, name)):
            out.append(f"{name} missing or placeholder (printed on tax invoices)")
    if s.TD_COMMERCE_WEBHOOK_MODE != "queue":
        out.append("TD_COMMERCE_WEBHOOK_MODE must be 'queue' in production (ADR-0006)")
    return out


def production_problems(s: Settings) -> list[str]:
    problems = [f"fake/local adapter selected: {name}" for name, chk in _fake_checks.items() if chk(s)]
    problems += _provider_problems(s)
    problems += _commerce_problems(s)
    if s.LOG_LEVEL == "DEBUG":
        problems.append("LOG_LEVEL=DEBUG is forbidden in production")
    if not s.TD_DISABLE_API_DOCS:
        problems.append("TD_DISABLE_API_DOCS must be true in production")
    if not s.TD_COOKIE_SECURE:
        problems.append("TD_COOKIE_SECURE must be true in production")
    if not s.TD_SERVICE_TOKEN or "REPLACE" in s.TD_SERVICE_TOKEN or len(s.TD_SERVICE_TOKEN) < 32:
        problems.append("TD_SERVICE_TOKEN missing or placeholder")
    if "sentry.io" in s.SENTRY_DSN:
        problems.append("SENTRY_DSN must not point to sentry.io (ADR-0014)")
    for name in REQUIRED_KEYRINGS:
        try:
            ring = get_keyring(name)
        except KeyringError as e:
            problems.append(str(e))
            continue
        # SEC-06: non-hex placeholders (``local_dev_key_REPLACE...``) are refused even when long.
        if ring.weak_versions or any(len(k) < 32 for k in ring.keys.values()):
            problems.append(
                f"HMAC keyring {name}: TD_K_{name.upper()}_KEY_V{{n}} must be 64+ hex chars in production"
            )
    for name in REQUIRED_AEAD_KEYRINGS:
        try:
            aead = AeadKeyring.from_env(name)  # no dev fallback in production
        except CryptoError as e:
            problems.append(str(e))
            continue
        if aead.weak_versions:
            problems.append(
                f"AEAD keyring {name}: TD_K_{name.upper()}_KEY_V{{n}} must be 64 hex chars in production"
            )
    return problems


def run_startup_checks(s: Settings) -> None:
    """Always: active HMAC key versions must be loaded. Production: no fakes/placeholders.

    ``create_app`` and ``app.worker.create_celery`` (workers and beat, COM-08) call this AFTER
    module discovery (models + routers/tasks imported), so fake adapters registered by modules
    at import time are enforced too."""
    for name in REQUIRED_KEYRINGS:
        try:
            get_keyring(name)
        except KeyringError as e:
            raise UnsafeConfigurationError(str(e)) from e
    if s.is_production:
        problems = production_problems(s)
        if problems:
            raise UnsafeConfigurationError("refusing to start in production: " + "; ".join(problems))
