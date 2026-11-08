from __future__ import annotations

import json

import pytest
import structlog

from app.core.config import Settings
from app.core.logging import REDACTED, configure_logging, scrub
from app.core.startup_checks import UnsafeConfigurationError, production_problems, run_startup_checks


def test_scrub_redacts_sensitive_keys_and_values() -> None:
    out = scrub(
        None,
        "info",
        {
            "event": "login",
            "password": "hunter2hunter2",
            "otp": "123456",
            "headers": {"Cookie": "__Host-td_session=abc", "Authorization": "Service xyz", "accept": "json"},
            "note": "client sent Bearer abcdefghijklmnop and __Host-td_session=SECRETVALUE",
            "url": "/reset?token=abc123&x=1",
            "user_id": "0193",
        },
    )
    assert out["password"] == REDACTED and out["otp"] == REDACTED
    assert out["headers"]["Cookie"] == REDACTED and out["headers"]["Authorization"] == REDACTED
    assert out["headers"]["accept"] == "json"
    assert "abcdefghijklmnop" not in out["note"] and "SECRETVALUE" not in out["note"]
    assert "abc123" not in out["url"]
    assert out["user_id"] == "0193"


def test_json_logs_are_scrubbed_end_to_end(capsys) -> None:
    configure_logging("INFO", "json", "api-test")
    structlog.get_logger("t").info("session_created", session_token="tok_raw_value", user_id="u1")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(line)
    assert data["event"] == "session_created"
    assert data["session_token"] == REDACTED
    assert "tok_raw_value" not in line


def _prod(**kw) -> Settings:
    base = dict(
        APP_ENV="prod",
        TD_DISABLE_API_DOCS=True,
        TD_COOKIE_SECURE=True,
        TD_SERVICE_TOKEN="f" * 64,
        JUDGE_PROVIDER="judge0_cloud",
        SMS_PROVIDER="msg91",
        EMAIL_PROVIDER="ses",
        VDOCIPHER_MODE="live",
        TD_APP_ENVELOPE_KMS_KEY_ID="alias/td-app-envelope",
        S3_KMS_KEY_ID="alias/td-s3",
        EMAIL_FROM_ADDRESS="no-reply@techdrona.in",
        AWS_REGION="ap-south-1",
        MSG91_AUTH_KEY="msg91-live-auth-key",
        MSG91_SENDER_ID="TCHDRN",
        MSG91_TEMPLATE_ID_OTP="65f0c0ffee0000000000otp1",
        RAZORPAY_KEY_ID="rzp_live_AbCdEf123456",
        RAZORPAY_KEY_SECRET="live-secret-value",
        RAZORPAY_WEBHOOK_SECRET="live-webhook-secret",
        SELLER_GSTIN="36ABCDE1234F1Z5",
        SELLER_LEGAL_NAME="Tech Drona Private Limited",
        SELLER_ADDRESS="Plot 1, HITEC City, Hyderabad, Telangana 500081",
        TD_COMMERCE_WEBHOOK_MODE="queue",
    )
    base.update(kw)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def test_production_refuses_fake_adapters(monkeypatch) -> None:
    # The ai module reads AI_PROVIDER from the environment (not Settings): AI switched off is a
    # valid production configuration; the default fake provider is not.
    monkeypatch.setenv("AI_PROVIDER", "disabled")
    assert production_problems(_prod()) == []
    monkeypatch.setenv("AI_PROVIDER", "fake")
    assert any("ai provider" in p for p in production_problems(_prod()))
    monkeypatch.setenv("AI_PROVIDER", "disabled")
    with pytest.raises(UnsafeConfigurationError, match="judge"):
        run_startup_checks(_prod(JUDGE_PROVIDER="fake"))
    problems = production_problems(_prod(SMS_PROVIDER="console", VDOCIPHER_MODE="stub", LOG_LEVEL="DEBUG"))
    assert any("sms" in p for p in problems) and any("video" in p for p in problems)
    assert any("DEBUG" in p for p in problems)


def test_non_production_allows_fakes() -> None:
    run_startup_checks(_prod(APP_ENV="local", JUDGE_PROVIDER="fake"))


def test_missing_active_hmac_key_refuses_start(monkeypatch) -> None:
    from app.core.security import reset_keyrings

    monkeypatch.setenv("TD_K_LOGIN_ACTIVE_VERSION", "7")
    reset_keyrings()
    try:
        with pytest.raises(UnsafeConfigurationError, match="active version 7"):
            run_startup_checks(_prod(APP_ENV="local"))
    finally:
        monkeypatch.undo()
        reset_keyrings()


# --------------------------------------------------------------------------- Phase B (core)


def test_sec06_prod_gate_refuses_non_hex_placeholder_hmac_keys(monkeypatch) -> None:
    """SEC-06: a long non-hex placeholder (shaped like .env.example) is no longer accepted."""
    from app.core.security import reset_keyrings

    monkeypatch.setenv("TD_K_DEVICE_KEY_V1", "local_dev_device_key_REPLACE_ME_0123456789")
    monkeypatch.setenv("TD_K_LOGIN_KEY_V1", "x" * 64)
    reset_keyrings()
    try:
        problems = production_problems(_prod())
        assert any("HMAC keyring device" in p for p in problems), problems
        assert any("HMAC keyring login" in p for p in problems), problems
    finally:
        monkeypatch.undo()
        reset_keyrings()
    assert not [p for p in production_problems(_prod()) if "HMAC" in p]


def test_com07_prod_gate_refuses_commerce_and_provider_placeholders() -> None:
    problems = production_problems(
        _prod(
            RAZORPAY_KEY_ID="",
            RAZORPAY_KEY_SECRET="",
            RAZORPAY_WEBHOOK_SECRET="REPLACE_ME",
            SELLER_GSTIN="36AAAAA0000A1Z5",
            SELLER_LEGAL_NAME="Tech Drona (DEV PLACEHOLDER)",
            SELLER_ADDRESS="DEV PLACEHOLDER ADDRESS, Hyderabad, Telangana",
            TD_COMMERCE_WEBHOOK_MODE="inline",
        )
    )
    for needle in (
        "RAZORPAY_KEY_ID",
        "RAZORPAY_KEY_SECRET",
        "RAZORPAY_WEBHOOK_SECRET",
        "SELLER_GSTIN",
        "SELLER_LEGAL_NAME",
        "SELLER_ADDRESS",
        "TD_COMMERCE_WEBHOOK_MODE",
    ):
        assert any(needle in p for p in problems), (needle, problems)
    assert any("rzp_test_" in p for p in production_problems(_prod(RAZORPAY_KEY_ID="rzp_test_abc")))


def test_com07_prod_gate_refuses_memory_email_and_unimplemented_providers() -> None:
    assert any("email" in p for p in production_problems(_prod(EMAIL_PROVIDER="memory")))
    assert any("EMAIL_PROVIDER=sendgrid" in p for p in production_problems(_prod(EMAIL_PROVIDER="sendgrid")))
    assert any("SMS_PROVIDER=twilio" in p for p in production_problems(_prod(SMS_PROVIDER="twilio")))
    p = production_problems(_prod(EMAIL_FROM_ADDRESS="no-reply@example.invalid", AWS_REGION=""))
    assert any("EMAIL_FROM_ADDRESS" in x for x in p) and any("AWS_REGION" in x for x in p)
    p = production_problems(_prod(MSG91_AUTH_KEY="", MSG91_TEMPLATE_ID_OTP="REPLACE"))
    assert any("MSG91_AUTH_KEY" in x for x in p) and any("MSG91_TEMPLATE_ID_OTP" in x for x in p)


def test_com08_celery_app_runs_the_production_gate(monkeypatch) -> None:
    """COM-08: building the Celery app (workers and beat) refuses fakes in production."""
    import app.worker as worker
    from app.core.config import get_settings

    monkeypatch.setattr(worker, "get_settings", lambda: _prod(PAYMENTS_PRIMARY_PROVIDER="fake"))
    try:
        with pytest.raises(UnsafeConfigurationError, match="refusing to start in production"):
            worker.create_celery()
    finally:
        worker.celery_app.set_current()
        get_settings.cache_clear()
