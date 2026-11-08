"""Commerce background jobs (Celery; Stage 10 backlog A-7).

* ``commerce.process_webhook_event`` (queue ``critical``) — processes one ingested provider
  webhook when ``TD_COMMERCE_WEBHOOK_MODE=queue`` (the HTTP handler only verifies, dedupes,
  persists and answers 200).
* ``commerce.webhook_retry`` (beat, 60 s, ``critical``) — sweep of events still ``received``
  (broker down, failed re-fetch).
* ``commerce.refund_submit_retry`` (beat, 2 min, ``critical``) — approved refunds that never
  reached the provider (outage at approval; COM-02), idempotent on ``notes.refund_id``.
* ``commerce.order_expiry`` (beat, 5 min) — pending orders past ``expires_at``.
* ``commerce.reconciliation`` (beat, hourly) — recovers missed captures for the last 48 h,
  settles refunds still ``processing`` and re-syncs live subscriptions (COM-13).
* ``entitlements.expiry`` (beat, 15 min) — active -> grace -> expired.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import structlog
from celery import shared_task

from app.core.db import get_sessionmaker, system_context
from app.core.jobs import register_periodic, run_async
from app.core.time import utcnow

log = structlog.get_logger("app.commerce.tasks")

PROCESS_WEBHOOK_TASK = "commerce.process_webhook_event"
PROVIDERS = ("razorpay", "cashfree")


def enqueue_webhook_event(provider: str, row_id: uuid.UUID) -> bool:
    """Best effort hand-off to the ``critical`` queue; the retry sweep covers broker outages."""
    try:
        from app.worker import celery_app

        celery_app.send_task(PROCESS_WEBHOOK_TASK, args=[provider, str(row_id)], queue="critical")
        return True
    except Exception as e:  # broker down: ``commerce.webhook_retry`` picks the row up
        log.warning("commerce.webhook_enqueue_failed", error=type(e).__name__)
        return False


async def _process_one(provider: str, row_id: uuid.UUID) -> str:
    from app.modules.commerce import webhooks
    from app.modules.commerce.gateway import get_gateway

    async with get_sessionmaker()() as session, session.begin():
        return await webhooks.process_event(session, get_gateway(provider), row_id)


async def webhook_retry() -> dict[str, int]:
    from app.modules.commerce import webhooks
    from app.modules.commerce.gateway import get_gateway

    out: dict[str, int] = {}
    for provider in PROVIDERS:
        try:
            gw = get_gateway(provider)
        except Exception as e:  # provider not configured in this environment
            log.info("commerce.webhook_retry_skipped", provider=provider, error=type(e).__name__)
            continue
        async with get_sessionmaker()() as session, session.begin():
            out[provider] = await webhooks.process_pending_events(session, gw)
    return out


async def refund_submit_retry() -> dict[str, int]:
    from app.modules.commerce import service as svc
    from app.modules.commerce.gateway import get_gateway

    async with get_sessionmaker()() as session, session.begin():
        await system_context(session, "commerce.refund_submit_retry")
        return await svc.retry_refund_submissions(session, get_gateway())


async def order_expiry() -> dict[str, int]:
    from app.modules.commerce import service as svc
    from app.modules.commerce.gateway import get_gateway

    async with get_sessionmaker()() as session, session.begin():
        await system_context(session, "commerce.order_expiry")
        return await svc.expire_orders(session, get_gateway())


async def reconciliation(hours: int = 48) -> dict[str, Any]:
    from app.modules.commerce import admin
    from app.modules.commerce.gateway import get_gateway

    now = utcnow()
    async with get_sessionmaker()() as session, session.begin():
        await system_context(session, "commerce.reconciliation")
        run = await admin.run_reconciliation(
            session,
            get_gateway(),
            range_from=now - timedelta(hours=hours),
            range_to=now,
            triggered_by="system:beat",
        )
        return admin.run_json(run)


async def entitlement_expiry() -> dict[str, int]:
    from app.modules.entitlements.service import expire_due

    async with get_sessionmaker()() as session, session.begin():
        await system_context(session, "entitlements.expiry")
        return await expire_due(session)


@shared_task(name=PROCESS_WEBHOOK_TASK, ignore_result=True, acks_late=True)
def process_webhook_event(provider: str, row_id: str) -> str:
    return run_async(_process_one(provider, uuid.UUID(row_id)))


@shared_task(name="commerce.webhook_retry", ignore_result=True)
def webhook_retry_task() -> dict[str, int]:
    return run_async(webhook_retry())


@shared_task(name="commerce.refund_submit_retry", ignore_result=True, acks_late=True)
def refund_submit_retry_task() -> dict[str, int]:
    return run_async(refund_submit_retry())


@shared_task(name="commerce.order_expiry", ignore_result=True)
def order_expiry_task() -> dict[str, int]:
    return run_async(order_expiry())


@shared_task(name="commerce.reconciliation", ignore_result=True)
def reconciliation_task() -> dict[str, Any]:
    return run_async(reconciliation())


@shared_task(name="entitlements.expiry", ignore_result=True)
def entitlement_expiry_task() -> dict[str, int]:
    return run_async(entitlement_expiry())


register_periodic(
    "commerce.webhook_retry", "commerce.webhook_retry", 60.0, options={"queue": "critical", "expires": 120}
)
register_periodic(
    "commerce.refund_submit_retry",
    "commerce.refund_submit_retry",
    120.0,
    options={"queue": "critical", "expires": 240},
)
register_periodic("commerce.order_expiry", "commerce.order_expiry", 300.0, options={"expires": 600})
register_periodic("commerce.reconciliation", "commerce.reconciliation", 3600.0, options={"expires": 3600})
register_periodic("entitlements.expiry", "entitlements.expiry", 900.0, options={"expires": 900})
