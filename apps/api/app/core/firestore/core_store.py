"""Firestore repositories for the ``core`` tables (MIGRATION-PLAN §1.9, §3.6; P0 store layer).

* ``lms_outbox_events``: the transactional outbox for modules whose business writes are in
  Firestore. ``emit_event_tx(tx, ...)`` writes the event in the caller's Firestore transaction
  (atomic with the business change, like ``app.core.outbox.emit_event`` on Postgres).
  ``relay_pending_firestore`` replaces ``FOR UPDATE SKIP LOCKED`` with a lease claimed in a
  transaction (``lease_until``), then runs the handlers registered with
  ``app.core.outbox.register_handler`` and marks the event dispatched. Pending events carry a
  ``pending_at`` field (removed when dispatched or dead-lettered) so "oldest pending first" is a
  single-field ``order_by`` with no composite index.
* ``lms_idempotency_keys``: ``Idempotency-Key`` records (api-specification §1.8) when
  ``TD_STORE_CORE=firestore`` (``app.core.idempotency.idempotent`` dispatches here). Document id =
  SHA-256(user | route | key), so the "unique key" is the document id. Firestore has no
  savepoints: when the caller passes a Postgres ``session`` the business writes still roll back
  to a savepoint on a stored 4xx; Firestore-native operations must validate before writing
  (MIGRATION-PLAN §1.9). A concurrent duplicate answers ``409 idempotency_in_progress`` at once
  (Postgres blocks on the unique index first, then replays or answers the same 409).

Both collections are ``system`` family; their documents are touched only through these helpers.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import structlog
from google.api_core import exceptions as gexc
from google.cloud.firestore import FieldFilter

from app.core.firestore.codec import to_store
from app.core.firestore.collections import CollectionSpec, physical_name, register_collection
from app.core.firestore.store import ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.core.time import utcnow

log = structlog.get_logger("app.outbox.firestore")

OUTBOX = "outbox_events"
IDEMPOTENCY = "idempotency_keys"
RELAY_JOB = "core.outbox_relay"
IDEM_JOB = "core.idempotency"
LEASE = timedelta(seconds=120)

register_collection(CollectionSpec(OUTBOX, "system"))
register_collection(CollectionSpec(IDEMPOTENCY, "system"))


# --------------------------------------------------------------------------- outbox


def emit_event_tx(
    tx: ScopedTransaction,
    event_type: str,
    payload: dict[str, Any],
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Queue a domain event inside a Firestore transaction; returns the event id."""
    from app.core.outbox import EVENT_TYPE_RE

    if not EVENT_TYPE_RE.match(event_type):
        raise ValueError(f"invalid event type {event_type!r} (use 'module.thing_happened')")
    event_id = uuid7()
    tx.raw_create(
        OUTBOX,
        str(event_id),
        event_doc(event_id, event_type, payload, aggregate_type, aggregate_id, organization_id, utcnow()),
    )
    return event_id


def event_doc(
    event_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    occurred_at: Any,
) -> dict[str, Any]:
    """The ``lms_outbox_events`` document (one layout for direct and buffered emits)."""
    return {
        "id": str(event_id),
        "event_type": event_type,
        "aggregate_type": aggregate_type,
        "aggregate_id": str(aggregate_id),
        # JSON text, not a map: the payload round-trips exactly like Postgres JSONB (Firestore maps
        # forbid nested arrays and would change nothing else visible). Readers accept both forms
        # (``outbox_message``; the SQL engine of data-money writes a ``payload`` map).
        "payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "organization_id": str(organization_id) if organization_id else None,
        "occurred_at": occurred_at,
        "pending_at": occurred_at,
        "attempts": 0,
        "dispatched_at": None,
        "last_error": None,
        "lease_until": None,
    }


async def emit_event_firestore(event_type: str, payload: dict[str, Any], **kw: Any) -> uuid.UUID:
    """Stand-alone emit (its own transaction) for callers outside a Firestore transaction."""
    store = ScopedStore.system(RELAY_JOB)
    return await store.run_transaction(lambda tx: _emit(tx, event_type, payload, kw))


async def _emit(
    tx: ScopedTransaction, event_type: str, payload: dict[str, Any], kw: dict[str, Any]
) -> uuid.UUID:
    return emit_event_tx(tx, event_type, payload, **kw)


SessionScope = Callable[[], AbstractAsyncContextManager[Any]]


def _plain_utc(v: Any) -> datetime:
    """Firestore's DatetimeWithNanoseconds -> a plain tz-aware UTC datetime (what asyncpg returns)."""
    v = v.astimezone(UTC)
    return datetime(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond, tzinfo=UTC)


def outbox_message(ev: dict[str, Any]) -> Any:
    """The handler's ``OutboxMessage`` for a stored event, field for field as the Postgres relay
    builds it: UUID ids, ``event_type``/``aggregate_type`` str, ``payload`` a fresh dict (JSON
    round-trip), ``organization_id`` UUID or None, ``occurred_at`` tz-aware UTC datetime,
    ``attempt`` = stored attempts + 1."""
    from app.core.outbox import OutboxMessage

    raw = ev.get("payload_json")
    payload = json.loads(raw) if isinstance(raw, str) else dict(ev.get("payload") or {})
    return OutboxMessage(
        id=uuid.UUID(str(ev["id"])),
        event_type=str(ev["event_type"]),
        aggregate_type=str(ev["aggregate_type"]),
        aggregate_id=uuid.UUID(str(ev["aggregate_id"])),
        payload=payload,
        organization_id=uuid.UUID(str(ev["organization_id"])) if ev.get("organization_id") else None,
        occurred_at=_plain_utc(ev["occurred_at"]),
        attempt=int(ev.get("attempts") or 0) + 1,
    )


async def relay_pending_firestore(
    *,
    batch: int | None = None,
    max_attempts: int | None = None,
    session_scope: SessionScope | None = None,
    holder: str | None = None,
    store: ScopedStore | None = None,
) -> Any:
    """Dispatch up to ``batch`` pending Firestore outbox events (oldest first).

    ``session_scope()`` (optional) yields the handler's ``session`` per event: the worker passes
    a Postgres ``system_context`` transaction while handler modules are still on Postgres; it
    commits only if every handler succeeded (same all-or-nothing rule as the Postgres relay).
    Without it handlers receive ``session=None``."""
    from app.core.config import get_settings
    from app.core.outbox import RelayResult, handlers_for

    s = get_settings()
    batch = batch or s.TD_OUTBOX_RELAY_BATCH
    max_attempts = max_attempts or s.TD_OUTBOX_MAX_ATTEMPTS
    store = store or ScopedStore.system(RELAY_JOB)
    holder = holder or uuid7().hex
    result = RelayResult()
    ids = await _eligible_ids(store, batch, max_attempts)
    for event_id in ids:
        ev = await store.run_transaction(
            partial(_claim, event_id=event_id, holder=holder, max_attempts=max_attempts)
        )
        if ev is None:
            continue
        handlers = handlers_for(ev["event_type"])
        if not handlers:
            await store.run_transaction(
                partial(
                    _finish,
                    event_id=event_id,
                    holder=holder,
                    error=None,
                    max_attempts=max_attempts,
                    counted=False,
                )
            )
            result.skipped_no_handler += 1
            continue
        msg = outbox_message(ev)
        error: str | None = None
        try:
            if session_scope is not None:
                async with session_scope() as session:
                    for h in handlers:
                        await h(session, msg)
            else:
                for h in handlers:
                    await h(None, msg)  # type: ignore[arg-type]
        except Exception as e:
            error = f"{type(e).__name__}: {e}"[:1000]
            log.warning(
                "outbox_handler_failed",
                event_id=ev["id"],
                event_type=ev["event_type"],
                attempt=msg.attempt,
                error=type(e).__name__,
            )
        await store.run_transaction(
            partial(
                _finish,
                event_id=event_id,
                holder=holder,
                error=error,
                max_attempts=max_attempts,
                counted=True,
            )
        )
        if error is None:
            result.dispatched += 1
        else:
            result.failed += 1
    return result


async def _eligible_ids(store: ScopedStore, batch: int, max_attempts: int) -> list[str]:
    """Undispatched events with ``attempts < max_attempts``, oldest first (Postgres:
    ``dispatched_at IS NULL AND attempts < :max ORDER BY occurred_at, id LIMIT :batch``).

    Pending events carry ``pending_at`` (= occurred_at); dead letters carry ``dead_at`` instead.
    Dead letters are re-checked against the CURRENT max, so raising ``TD_OUTBOX_MAX_ATTEMPTS``
    re-picks them exactly as on Postgres (no stored "dead" verdict). Both queries are single-field
    ``order_by`` (no composite index); dead letters are few."""
    coll = store.client.collection(physical_name(OUTBOX))
    cands: list[tuple[Any, str]] = []
    async for snap in coll.order_by("pending_at").limit(batch).stream():
        d = snap.to_dict() or {}
        if int(d.get("attempts") or 0) < max_attempts:
            cands.append((d.get("occurred_at") or d.get("pending_at"), snap.id))
    async for snap in coll.order_by("dead_at").stream():
        d = snap.to_dict() or {}
        if d.get("dispatched_at") is None and int(d.get("attempts") or 0) < max_attempts:
            cands.append((d.get("occurred_at"), snap.id))
    cands.sort(key=lambda c: (c[0], c[1]))
    return [i for _t, i in cands[:batch]]


async def _claim(
    tx: ScopedTransaction, event_id: str, holder: str, max_attempts: int
) -> dict[str, Any] | None:
    cur = await tx.raw_get(OUTBOX, event_id)
    now = utcnow()
    if cur is None or cur.get("dispatched_at") is not None:
        return None
    if cur.get("pending_at") is None and cur.get("dead_at") is None:
        return None
    if int(cur.get("attempts") or 0) >= max_attempts:
        return None
    lease = cur.get("lease_until")
    if lease is not None and lease > now and cur.get("lease_holder") != holder:
        return None  # another relay owns it (SKIP LOCKED)
    tx.raw_set(OUTBOX, event_id, {**cur, "lease_until": now + LEASE, "lease_holder": holder})
    return cur


async def _finish(
    tx: ScopedTransaction, event_id: str, holder: str, error: str | None, max_attempts: int, counted: bool
) -> None:
    cur = await tx.raw_get(OUTBOX, event_id)
    if cur is None or cur.get("lease_holder") != holder:
        return
    now = utcnow()
    attempts = int(cur.get("attempts") or 0) + (1 if counted else 0)
    doc = {**cur, "attempts": attempts, "lease_until": None, "lease_holder": None}
    if error is None:
        doc.update(dispatched_at=now, last_error=None)
        doc.pop("pending_at", None)
        doc.pop("dead_at", None)
    else:
        doc["last_error"] = error
        if attempts >= max_attempts:  # dead letter: stays undispatched, visible to ops
            doc.pop("pending_at", None)
            doc["dead_at"] = now
        else:  # retry later (also a revived dead letter that failed again below the new max)
            doc["pending_at"] = cur.get("pending_at") or cur.get("occurred_at") or now
            doc.pop("dead_at", None)
    tx.raw_set(OUTBOX, event_id, doc)


# --------------------------------------------------------------------------- idempotency


def idem_doc_id(user_id: uuid.UUID | None, route_key: str, key: str) -> str:
    raw = f"{user_id or '-'}\x1f{route_key}\x1f{key}".encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class IdemRecord:
    status: str
    request_hash: bytes
    response_status: int | None
    response_body: Any


async def idempotent_firestore(
    request: Any,
    session: Any,
    *,
    user_id: uuid.UUID | None,
    operation: Callable[[], Awaitable[Any]],
    required: bool = True,
    money: bool = False,
    store: ScopedStore | None = None,
) -> Any:
    """Same contract as ``app.core.idempotency.idempotent`` with the record in Firestore."""
    from fastapi.responses import JSONResponse

    from app.core import idempotency as idem
    from app.core.errors import PROBLEM_CONTENT_TYPE, ProblemError
    from app.core.request_context import get_request_id

    key = request.headers.get(idem.HEADER)
    if not key:
        if required:
            raise ProblemError("idempotency_key_required")
        res = await operation()
        return JSONResponse(res.body, status_code=res.status, headers=res.headers)
    if not idem._valid_key(key):
        raise ProblemError(
            "validation_failed",
            errors=[{"field": idem.HEADER, "code": "invalid", "message": "8-128 printable ASCII characters"}],
        )
    store = store or ScopedStore.system(IDEM_JOB)
    rkey = idem.route_key(request)
    rhash = await idem.request_hash(request)
    ttl = idem.MONEY_TTL if money else idem.DEFAULT_TTL
    doc_id = idem_doc_id(user_id, rkey, key)

    def _record(now: datetime) -> dict[str, Any]:
        return {
            "user_id": str(user_id) if user_id else None,
            "route_key": rkey,
            "idem_key": key,
            "request_hash": rhash,
            "status": "in_progress",
            "response_status": None,
            "response_json": None,
            "resource_id": None,
            "created_at": now,
            "expires_at": now + ttl,
            "expire_at": now + ttl,  # Firestore TTL policy field
        }

    async def _start(tx: ScopedTransaction) -> IdemRecord | None:
        now = utcnow()
        cur = await tx.raw_get(IDEMPOTENCY, doc_id)
        if cur is not None and cur["expires_at"] >= now:
            body = json.loads(cur["response_json"]) if cur.get("response_json") else None
            return IdemRecord(cur["status"], bytes(cur["request_hash"]), cur.get("response_status"), body)
        # absent, or an expired previous use of this key: (re)start it
        tx.raw_set(IDEMPOTENCY, doc_id, _record(now))
        return None

    async def _claim_new() -> bool:
        """The usual case, a key never seen: one ``create`` (fails if the document exists), no
        read. A key that exists (a replay, a concurrent duplicate or an expired previous use)
        takes the transaction ``_start``, exactly as before."""
        try:
            await store.ref(IDEMPOTENCY, doc_id).create(to_store(_record(utcnow())))
        except gexc.AlreadyExists:
            return False
        return True

    existing = None if await _claim_new() else await store.run_transaction(_start)
    if existing is not None:
        if existing.request_hash != rhash:
            raise ProblemError("idempotency_key_reuse")
        if existing.status == "in_progress":
            raise ProblemError("idempotency_in_progress", headers={"Retry-After": "1"})
        is_problem = (
            isinstance(existing.response_body, dict)
            and "code" in existing.response_body
            and "type" in existing.response_body
            and (existing.response_status or 0) >= 400
        )
        return JSONResponse(
            existing.response_body,
            status_code=existing.response_status or 200,
            headers={"Idempotency-Replayed": "true"},
            media_type=PROBLEM_CONTENT_TYPE if is_problem else None,
        )

    async def _set(status: str, code: int, body: Any, resource_id: Any) -> None:
        # A field update with an "exists" precondition (no read): the same document as the old
        # read + overwrite ``{**cur, ...}``, and a record that disappeared stays absent.
        try:
            await store.ref(IDEMPOTENCY, doc_id).update(
                {
                    "status": status,
                    "response_status": code,
                    "response_json": json.dumps(body, ensure_ascii=False),
                    "resource_id": str(resource_id) if resource_id else None,
                }
            )
        except gexc.NotFound:
            return

    async def _drop() -> None:
        async def _fn(tx: ScopedTransaction) -> None:
            cur = await tx.raw_get(IDEMPOTENCY, doc_id)
            if cur is not None and cur.get("status") == "in_progress":
                tx.raw_delete(IDEMPOTENCY, doc_id)

        await store.run_transaction(_fn)

    # None and the no-Postgres placeholder (db.NO_POSTGRES) mean "no savepoint" (R10).
    from app.core.db import no_sql_session

    savepoint = None if no_sql_session(session) else await session.begin_nested()
    try:
        result = await operation()
    except ProblemError as exc:
        if exc.status >= 500 or exc.code in idem._NOT_STORED_CODES:
            await _drop()  # Postgres: the whole transaction (and the row) rolls back
            raise
        if savepoint is not None:
            await savepoint.rollback()
        problem = exc.to_body(get_request_id())
        await _set("failed", exc.status, problem, None)
        return JSONResponse(
            problem, status_code=exc.status, headers=exc.headers, media_type=PROBLEM_CONTENT_TYPE
        )
    except BaseException:
        await _drop()
        raise
    if savepoint is not None and savepoint.is_active:
        await savepoint.commit()
    body = json.loads(idem.canonical_json(result.body)) if result.body is not None else None
    await _set("completed", result.status, body, result.resource_id)
    return JSONResponse(body, status_code=result.status, headers=result.headers)


async def read_outbox_firestore(
    *,
    since: Any,
    event_types: list[str],
    limit: int,
    after: tuple[Any, uuid.UUID] | None = None,
    store: ScopedStore | None = None,
) -> list[Any]:
    """Firestore half of ``app.core.outbox.read_events`` (single-field range on ``occurred_at``;
    the type filter and the keyset are applied in memory, paging until ``limit`` matches)."""
    from app.core.outbox import OutboxRecord

    store = store or ScopedStore.system(RELAY_JOB)
    wanted = set(event_types)
    coll = store.client.collection(physical_name(OUTBOX))
    out: list[Any] = []
    seen: set[str] = set()
    op, start, page = ">", since, max(limit * 4, 200)
    while len(out) < limit:
        q = coll.where(filter=FieldFilter("occurred_at", op, start)).order_by("occurred_at").limit(page)
        snaps = [s async for s in q.stream()]
        fresh = [s for s in snaps if s.id not in seen]
        for snap in fresh:
            seen.add(snap.id)
            d = snap.to_dict() or {}
            if d.get("event_type") not in wanted:
                continue
            msg = outbox_message(d)
            if after is not None and (msg.occurred_at, msg.id) <= after:
                continue
            out.append(
                OutboxRecord(
                    msg.id,
                    msg.event_type,
                    msg.aggregate_type,
                    msg.aggregate_id,
                    msg.payload,
                    msg.organization_id,
                    msg.occurred_at,
                    _plain_utc(d["dispatched_at"]) if d.get("dispatched_at") else None,
                )
            )
        if len(snaps) < page:
            break
        last_ts = (snaps[-1].to_dict() or {}).get("occurred_at")
        if not fresh or last_ts == start:
            page *= 2  # a page full of one timestamp: widen instead of skipping ties
        # ``>=`` so documents sharing the page-edge timestamp are not lost (``seen`` dedupes).
        op, start = ">=", last_ts
    out.sort(key=lambda r: (r.occurred_at, r.id))
    return out[:limit]
