"""Provider webhooks (api-specification §18, ADR-0006 v0.4).

Ingest: raw-body HMAC (constant time; current + previous secret) → envelope check →
permanent dedupe ``INSERT … ON CONFLICT (gateway, event_id) DO NOTHING`` → 200.
Processing: row lock, **re-fetch the entity from the provider** and apply the fetched state
through the same state machine as the checkout callback; payload state is never applied.
No event is rejected for age (older than the tolerance ⇒ ``is_stale`` flag only). A failed
re-fetch makes no state change and is retried (``refetch_status = failed``).

Processing: ``TD_COMMERCE_WEBHOOK_MODE=queue`` hands the row to the Celery ``critical`` queue
after commit (``tasks.process_webhook_event``); ``inline`` (local/dev default) processes it in
the request. ``process_pending_events`` (beat ``commerce.webhook_retry``, 60 s, ``critical``)
retries rows still ``received`` with exponential backoff (``next_attempt_at``) for
``WEBHOOK_RETRY_HORIZON`` (72 h) after receipt; only then is a row ``failed``, which emits
``commerce.webhook_failed`` for alerting (COM-13).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.db import system_context
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.time import utcnow
from app.modules.commerce import policy
from app.modules.commerce import service as svc
from app.modules.commerce.gateway import GatewayUnavailable, PaymentGateway
from app.modules.commerce.models import PaymentWebhookEvent, Subscription
from app.modules.entitlements import service as ent

log = structlog.get_logger("commerce.webhooks")

PAYMENT_EVENTS = frozenset({"payment.authorized", "payment.captured", "payment.failed", "order.paid"})
REFUND_EVENTS = frozenset({"refund.created", "refund.processed", "refund.failed"})
SUBSCRIPTION_EVENTS = frozenset(
    {
        "subscription.authenticated",
        "subscription.activated",
        "subscription.charged",
        "subscription.pending",
        "subscription.halted",
        "subscription.paused",
        "subscription.resumed",
        "subscription.cancelled",
        "subscription.completed",
    }
)
DISPUTE_EVENTS = frozenset(
    {"payment.dispute.created", "payment.dispute.won", "payment.dispute.lost", "payment.dispute.closed"}
)
HANDLED = PAYMENT_EVENTS | REFUND_EVENTS | SUBSCRIPTION_EVENTS | DISPUTE_EVENTS
GATEWAY_ACTOR = AuditActor("gateway", system_job="commerce.webhook")


async def record_invalid_signature(session: AsyncSession, provider: str, raw: bytes, ip: str | None) -> None:
    """``400 webhook_signature_invalid`` is logged + audited + emitted for security (AB-12);
    the body is kept only as a hash."""
    digest = hashlib.sha256(raw).hexdigest()
    log.warning("webhook_signature_invalid", provider=provider, body_sha256=digest, ip=ip)
    await system_context(session, "commerce.webhook")
    await audit(
        session,
        GATEWAY_ACTOR,
        "commerce.webhook_signature_invalid",
        "payment_webhook",
        None,
        reason_code="AB-12",
        after={"provider": provider, "body_sha256": digest},
        ip=ip,
    )
    await emit_event(
        session,
        "commerce.webhook_signature_invalid",
        {"provider": provider, "rule_key": "AB-12", "family": "abuse", "body_sha256": digest},
        aggregate_type="payment_webhook",
        aggregate_id=uuid7(),
    )


def _entity_id(payload: dict[str, Any], key: str) -> str | None:
    ent_ = ((payload.get("payload") or {}).get(key) or {}).get("entity") or {}
    v = ent_.get("id")
    return str(v) if v else None


async def ingest(
    session: AsyncSession, gw: PaymentGateway, raw: bytes, headers: dict[str, str], payload: dict[str, Any]
) -> tuple[str, uuid.UUID | None]:
    """Persist (deduped) one verified delivery. Returns ``(status, row_id)``."""
    await system_context(session, "commerce.webhook")
    event_type = str(payload.get("event") or "unknown")
    event_id = (
        headers.get("x-razorpay-event-id") or headers.get("x-webhook-id") or hashlib.sha256(raw).hexdigest()
    )
    created = payload.get("created_at")
    gw_created = datetime.fromtimestamp(int(created), tz=UTC) if isinstance(created, int | float) else None
    s = policy.commerce_settings()
    stale = gw_created is not None and (utcnow() - gw_created).total_seconds() > s.WEBHOOK_TOLERANCE_SECONDS
    status = "received"
    last_error = None
    if event_type not in HANDLED:
        status, last_error = "ignored", "unhandled_event_type"
    elif s.RAZORPAY_ACCOUNT_ID and payload.get("account_id") not in (None, s.RAZORPAY_ACCOUNT_ID):
        status, last_error = "ignored", "account_mismatch"
    row_id = (
        await session.execute(
            pg_insert(PaymentWebhookEvent)
            .values(
                id=uuid7(),
                gateway=gw.name,
                event_id=event_id[:200],
                event_type=event_type[:100],
                signature_valid=True,
                payload=payload,
                payload_sha256=hashlib.sha256(raw).digest(),
                gateway_created_at=gw_created,
                status=status,
                last_error=last_error,
                is_stale=stale,
                processed_at=utcnow() if status == "ignored" else None,
                refetch_status="not_required" if status == "ignored" else None,
            )
            .on_conflict_do_nothing(index_elements=["gateway", "event_id"])
            .returning(PaymentWebhookEvent.id)
        )
    ).scalar_one_or_none()
    if row_id is None:
        return "duplicate", None
    if stale:
        log.info("webhook_stale_event", event_type=event_type)  # monitoring only, never rejected
    return ("ignored" if status == "ignored" else "accepted"), row_id


async def process_event(session: AsyncSession, gw: PaymentGateway, row_id: uuid.UUID) -> str:
    """Worker step. Returns the resulting event status."""
    await system_context(session, "commerce.webhook")
    row = (
        await session.execute(
            select(PaymentWebhookEvent).where(PaymentWebhookEvent.id == row_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.status in ("processed", "ignored"):
        return row.status if row else "missing"
    row.status = "processing"
    row.attempts += 1
    await session.flush()
    actor = ent.Actor.gateway()
    p = row.payload
    et = row.event_type
    nested = await session.begin_nested()
    try:
        await _apply(session, gw, row, et, p, actor)
    except GatewayUnavailable as e:
        await nested.rollback()
        await session.refresh(row)
        row.refetch_status = "failed"
        await _retry_later(session, row, f"refetch_failed: {e}")
        log.warning("webhook_refetch_failed", event_type=et, attempts=row.attempts)
        return row.status
    except Exception as e:
        await nested.rollback()
        await session.refresh(row)
        await _retry_later(session, row, f"{type(e).__name__}: {e}")
        log.exception("webhook_processing_error", event_type=et)
        return row.status
    if nested.is_active:
        await nested.commit()
    row.status = "processed"
    row.processed_at = utcnow()
    row.next_attempt_at = None
    await session.flush()
    return row.status


def backoff(attempts: int) -> timedelta:
    step: timedelta = policy.WEBHOOK_BACKOFF_BASE * (2 ** min(max(attempts - 1, 0), 16))
    return min(step, policy.WEBHOOK_BACKOFF_MAX)


async def _retry_later(session: AsyncSession, row: PaymentWebhookEvent, error: str) -> None:
    """COM-13: keep retrying with exponential backoff until ``WEBHOOK_RETRY_HORIZON`` after
    receipt (a provider outage of hours must not drop refund/subscription/dispute events);
    then mark ``failed`` and alert."""
    now = utcnow()
    row.last_error = error[:500]
    if now - row.received_at >= policy.WEBHOOK_RETRY_HORIZON:
        row.status = "failed"
        row.next_attempt_at = None
        await session.flush()
        log.error("webhook_failed_permanently", event_type=row.event_type, attempts=row.attempts)
        await emit_event(
            session,
            "commerce.webhook_failed",
            {
                "gateway": row.gateway,
                "event_type": row.event_type,
                "webhook_event_id": str(row.id),
                "attempts": row.attempts,
                "last_error": row.last_error,
            },
            aggregate_type="payment_webhook",
            aggregate_id=row.id,
        )
        return
    row.status = "received"
    row.next_attempt_at = now + backoff(row.attempts)
    await session.flush()


async def _apply(
    session: AsyncSession,
    gw: PaymentGateway,
    row: PaymentWebhookEvent,
    et: str,
    p: dict[str, Any],
    actor: ent.Actor,
) -> None:
    now = utcnow()
    if et in PAYMENT_EVENTS:
        pid = _entity_id(p, "payment")
        if not pid:
            row.refetch_status = "not_required"
            return
        gp = await gw.fetch_payment(pid)
        row.refetched_at, row.refetch_status = now, "ok"
        order, pay, _ = await svc.apply_payment(session, gw, gp, actor)
        row.order_id = order.id if order else None
        row.payment_id = pay.id if pay else None
        return
    if et in REFUND_EVENTS:
        rid = _entity_id(p, "refund")
        if not rid:
            row.refetch_status = "not_required"
            return
        gr = await gw.fetch_refund(rid)
        row.refetched_at, row.refetch_status = now, "ok"
        r = await svc.apply_refund_state(session, gr, actor)
        if r is not None:
            row.order_id = r.order_id
        return
    if et in SUBSCRIPTION_EVENTS:
        sid = _entity_id(p, "subscription")
        if not sid:
            row.refetch_status = "not_required"
            return
        gs = await gw.fetch_subscription(sid)
        row.refetched_at, row.refetch_status = now, "ok"
        sub = (
            await session.execute(
                select(Subscription)
                .where(Subscription.gateway == gw.name, Subscription.gateway_subscription_id == sid)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if sub is None:
            row.last_error = "unknown_subscription"
            return
        row.subscription_id = sub.id
        pay_id = _entity_id(p, "payment")
        if pay_id:  # subscription.charged/activated carry the debit
            gp = await gw.fetch_payment(pay_id)
            pay = await svc.record_subscription_charge(session, gw, sub, gp, actor)
            row.payment_id = pay.id
        await svc.apply_subscription_state(session, sub, gs, actor)
        return
    if et in DISPUTE_EVENTS:
        did = _entity_id(p, "dispute")
        if not did:
            row.refetch_status = "not_required"
            return
        d = await gw.fetch_dispute(did)
        row.refetched_at, row.refetch_status = now, "ok"
        await svc.apply_dispute(session, gw, d.payment_id, d.status, actor)
        return
    row.refetch_status = "not_required"


async def process_pending_events(
    session: AsyncSession, gw: PaymentGateway, limit: int = 100, now: datetime | None = None
) -> int:
    """Retry sweep (worker/cron): events still ``received`` (e.g. after a failed re-fetch)
    whose backoff (``next_attempt_at``) has elapsed."""
    await system_context(session, "commerce.webhook")
    now = now or utcnow()
    ids = (
        (
            await session.execute(
                select(PaymentWebhookEvent.id)
                .where(
                    PaymentWebhookEvent.gateway == gw.name,
                    PaymentWebhookEvent.status == "received",
                    or_(
                        PaymentWebhookEvent.next_attempt_at.is_(None),
                        PaymentWebhookEvent.next_attempt_at <= now,
                    ),
                )
                .order_by(PaymentWebhookEvent.received_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    for i in ids:
        await process_event(session, gw, i)
    return len(ids)


def parse_body(raw: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except ValueError:  # includes UnicodeDecodeError
        return None
    return data if isinstance(data, dict) else None
