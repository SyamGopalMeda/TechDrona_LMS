"""COM audit probes: production gate, Celery beat/queues, outbox handlers, webhook HMAC."""

from __future__ import annotations

import os
import re
from pathlib import Path

from app.modules.commerce.gateway import CashfreeGateway, RazorpayGateway, hmac_hex

REPO = Path(__file__).resolve().parents[5]


def _prod_problems(**env: str) -> list[str]:
    import app.modules.commerce.documents  # noqa: F401
    import app.modules.commerce.gateway  # noqa: F401
    import app.modules.media.providers  # noqa: F401
    import app.modules.notifications.adapters  # noqa: F401
    from app.core.config import Settings
    from app.core.startup_checks import production_problems
    from app.modules.commerce.policy import reset_commerce_settings

    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    reset_commerce_settings()
    try:
        s = Settings(
            APP_ENV="production",
            JUDGE_PROVIDER="judge0_cloud",
            SMS_PROVIDER=env.get("SMS_PROVIDER", "msg91"),
            EMAIL_PROVIDER=env.get("EMAIL_PROVIDER", "ses"),
            VDOCIPHER_MODE="live",
            PAYMENTS_PRIMARY_PROVIDER="razorpay",
            S3_KMS_KEY_ID="arn:aws:kms:ap-south-1:1:key/x",
            TD_APP_ENVELOPE_KMS_KEY_ID="arn:aws:kms:ap-south-1:1:key/y",
            TD_DISABLE_API_DOCS=True,
            TD_COOKIE_SECURE=True,
            TD_SERVICE_TOKEN="x" * 40,
        )
        return production_problems(s)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        reset_commerce_settings()


def test_production_gate_gaps() -> None:
    probs = _prod_problems(
        RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="", RAZORPAY_WEBHOOK_SECRET="", SELLER_GSTIN="36AAAAA0000A1Z5"
    )
    print("ses/msg91 + empty razorpay + placeholder GSTIN ->", probs)
    joined = " ".join(probs).lower()
    assert "razorpay" not in joined and "gstin" not in joined and "seller" not in joined
    assert "sms" not in joined and "email" not in joined
    probs = _prod_problems(EMAIL_PROVIDER="memory")
    print("EMAIL_PROVIDER=memory ->", probs)
    assert not any("email" in p.lower() for p in probs)


def test_ses_and_msg91_adapters_not_implemented() -> None:
    import asyncio

    from app.core.config import Settings
    from app.modules.notifications import adapters

    adapters.set_email_adapter(None)
    adapters.set_sms_adapter(None)
    orig = adapters.get_settings
    adapters.get_settings = lambda: Settings(EMAIL_PROVIDER="ses", SMS_PROVIDER="msg91")  # type: ignore[assignment]
    try:
        e, s = adapters.get_email_adapter(), adapters.get_sms_adapter()
        print("email adapter", type(e).__name__, e.name, "| sms adapter", type(s).__name__, s.name)
        for ad, msg in ((e, adapters.OutboundEmail("a@b.c", "s", "t")), (s, adapters.OutboundSms("+910", "t"))):
            try:
                asyncio.run(ad.send(msg))
                raise AssertionError("sent")
            except RuntimeError as err:
                print("send ->", err)
    finally:
        adapters.get_settings = orig  # type: ignore[assignment]
        adapters.set_email_adapter(None)
        adapters.set_sms_adapter(None)


def test_celery_worker_skips_startup_checks() -> None:
    from app.core.config import reset_settings_cache

    old = {k: os.environ.get(k) for k in ("APP_ENV", "PAYMENTS_PRIMARY_PROVIDER")}
    os.environ["APP_ENV"] = "production"
    os.environ["PAYMENTS_PRIMARY_PROVIDER"] = "fake"
    reset_settings_cache()
    try:
        from app.worker import create_celery

        capp = create_celery()  # no UnsafeConfigurationError
        print("celery app created in APP_ENV=production with fake payments:", capp.main)
        from app.main import create_app

        try:
            create_app()
            raise AssertionError("api started")
        except Exception as e:  # noqa: BLE001
            print("api ->", type(e).__name__, str(e)[:160])
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        reset_settings_cache()


def test_beat_schedule_and_queues() -> None:
    from app.core.outbox import _handlers  # type: ignore[attr-defined]
    from app.worker import celery_app

    sched = celery_app.conf.beat_schedule
    registered = set(celery_app.tasks)
    queues: dict[str, list[str]] = {}
    missing = []
    for name, e in sorted(sched.items()):
        q = (e.get("options") or {}).get("queue", "default")
        queues.setdefault(q, []).append(name)
        if e["task"] not in registered:
            missing.append(e["task"])
        print(f"BEAT {name:45s} task={e['task']:40s} every={e['schedule']} queue={q}")
    print("QUEUES used by beat:", {k: len(v) for k, v in queues.items()})
    print("beat tasks not registered in worker:", missing)
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    consumed = set()
    for m in re.finditer(r"CELERY_QUEUES:\s*([\w,]+)", compose):
        consumed |= set(m.group(1).split(","))
    print("compose CELERY_QUEUES consumed:", sorted(consumed))
    print("beat queues with no consumer:", sorted(set(queues) - consumed))
    print("outbox handler event types:", sorted(_handlers)[:80] if isinstance(_handlers, dict) else _handlers)
    assert not missing


def test_webhook_hmac_rotation_and_empty_secret() -> None:
    raw = b'{"event":"payment.captured"}'
    gw = RazorpayGateway("k", "s", ("new", "old"))
    assert gw.verify_webhook(raw, {"x-razorpay-signature": hmac_hex("old", raw)})
    assert not gw.verify_webhook(raw, {"x-razorpay-signature": hmac_hex("other", raw)})
    empty = RazorpayGateway("k", "", ("", ""))
    assert not empty.verify_webhook(raw, {"x-razorpay-signature": hmac_hex("", raw)})
    assert not empty.verify_checkout_signature("o", "p", hmac_hex("", b"o|p"))
    cf = CashfreeGateway("app", "")
    assert not cf.verify_webhook(raw, {"x-webhook-signature": "x", "x-webhook-timestamp": "1"})
