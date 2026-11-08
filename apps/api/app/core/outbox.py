"""Transactional outbox (ADR-0011): ``emit_event`` inserts into ``outbox_events`` in the
caller's business transaction. Payloads carry ids only — never raw PII or secrets."""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.core.models import OutboxEvent
from app.core.time import utcnow

_log = structlog.get_logger("app.outbox")

EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


async def emit_event(
    session: AsyncSession,
    event_type: str,
    payload: dict[str, Any],
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Queue a domain event (e.g. ``entitlement.granted``); returns the event id that
    handlers use for idempotency."""
    if not EVENT_TYPE_RE.match(event_type):
        raise ValueError(f"invalid event type {event_type!r} (use 'module.thing_happened')")
    event_id = uuid7()
    await session.execute(
        insert(OutboxEvent).values(
            id=event_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            organization_id=organization_id,
        )
    )
    return event_id


# --------------------------------------------------------------------------- relay (worker side)


@dataclass(frozen=True)
class OutboxMessage:
    """What an in-process handler receives. ``id`` is the idempotency key for side effects."""

    id: uuid.UUID
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    payload: dict[str, Any]
    organization_id: uuid.UUID | None
    occurred_at: datetime
    attempt: int


OutboxHandler = Callable[[AsyncSession, OutboxMessage], Awaitable[None]]

_handlers: dict[str, list[OutboxHandler]] = {}


def register_handler(event_type: str, fn: OutboxHandler) -> None:
    """Subscribe ``async fn(session, message)`` to ``event_type`` (call at import time of the
    module's ``tasks.py`` or ``router.py``). The handler runs in the relay's transaction under
    ``system_context`` (platform RLS): its DB writes commit atomically with the event being
    marked dispatched, and are rolled back (and the event retried) if any handler for the
    event fails. Non-DB side effects must be idempotent on ``message.id``. Registering the
    same function twice for a type is a no-op."""
    if not EVENT_TYPE_RE.match(event_type):
        raise ValueError(f"invalid event type {event_type!r}")
    lst = _handlers.setdefault(event_type, [])
    if fn not in lst:
        lst.append(fn)


def unregister_handler(event_type: str, fn: OutboxHandler) -> None:
    lst = _handlers.get(event_type, [])
    if fn in lst:
        lst.remove(fn)


def handlers_for(event_type: str) -> tuple[OutboxHandler, ...]:
    return tuple(_handlers.get(event_type, ()))


@dataclass
class RelayResult:
    dispatched: int = 0
    failed: int = 0
    skipped_no_handler: int = 0


async def relay_pending(
    session: AsyncSession, *, batch: int | None = None, max_attempts: int | None = None
) -> RelayResult:
    """Dispatch up to ``batch`` undispatched events (oldest first) inside the caller's
    transaction. Rows are claimed with ``FOR UPDATE SKIP LOCKED`` so concurrent relays never
    double-dispatch; each event runs in its own SAVEPOINT. Events with no handler are marked
    dispatched (nothing to do). Events that reached ``max_attempts`` stay undispatched with
    ``last_error`` set (dead letter, visible to ops)."""
    from app.core.config import get_settings
    from app.core.db import system_context

    s = get_settings()
    batch = batch or s.TD_OUTBOX_RELAY_BATCH
    max_attempts = max_attempts or s.TD_OUTBOX_MAX_ATTEMPTS
    await system_context(session, "outbox_relay")
    rows = (
        (
            await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.dispatched_at.is_(None), OutboxEvent.attempts < max_attempts)
                .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    result = RelayResult()
    for ev in rows:
        handlers = handlers_for(ev.event_type)
        if not handlers:
            ev.dispatched_at = utcnow()
            result.skipped_no_handler += 1
            continue
        msg = OutboxMessage(
            id=ev.id,
            event_type=ev.event_type,
            aggregate_type=ev.aggregate_type,
            aggregate_id=ev.aggregate_id,
            payload=dict(ev.payload or {}),
            organization_id=ev.organization_id,
            occurred_at=ev.occurred_at,
            attempt=ev.attempts + 1,
        )
        try:
            async with session.begin_nested():
                for h in handlers:
                    await h(session, msg)
        except Exception as e:
            ev.attempts = ev.attempts + 1
            ev.last_error = f"{type(e).__name__}: {e}"[:1000]
            result.failed += 1
            _log.warning(
                "outbox_handler_failed",
                event_id=str(ev.id),
                event_type=ev.event_type,
                attempt=ev.attempts,
                error=type(e).__name__,
            )
            continue
        ev.attempts = ev.attempts + 1
        ev.dispatched_at = utcnow()
        ev.last_error = None
        result.dispatched += 1
    await session.flush()
    return result
