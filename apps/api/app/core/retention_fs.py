"""``maint.run_retention`` on Firestore (privacy §7; migration ``core_base_0002``).

The VM's daily ``td.core.maint_retention`` calls ``maint.run_retention(5000, 200)``: for each of 12
tables with an **active** ``retention_policies`` row it deletes the rows matching the table's
predicate of ``maint.purge_expired_rows`` with ``cutoff = now() - min(active retention_interval)``
and writes one ``audit_outbox`` summary ``maint.retention.purged``. This module is the same job for
the collections of modules on Firestore (``TD_STORE_<MODULE>=firestore``), run by the same task on
the ``lmsScheduler`` dispatcher (daily 22:30 UTC, ``maintenance`` queue). Nothing here runs on the
VM: ``firestore_targets()`` is empty when no module is on Firestore.

Per table (same order, same predicates as the SQL):

========================  ==============================================  ================================
table                     deleted when (``cutoff = now - interval``)       kept / Firestore notes
========================  ==============================================  ================================
login_attempts            ``attempted_at < cutoff``
session_network_obs.      ``coalesce(last_seen_at, first_seen_at) < c``
auth_sessions             ``coalesce(ended_at, absolute_expires_at) < c``  referenced by a test attempt
                                                                           (``bound_session_id`` FK)
security_signals          ``occurred_at < c``                              user has an open/held case
risk_evaluations          ``evaluated_at < c``                             user or own case open/held
playback_sessions         ``started_at < c``
attempt_events            ``occurred_at < c``
verification_tokens       ``coalesce(consumed_at, expires_at) < c``
password_reset_tokens     ``coalesce(consumed_at, expires_at) < c``
outbox_events             ``dispatched_at < c`` or (undispatched,
                          ``attempts >= 10`` and ``occurred_at < c``)
idempotency_keys          ``expires_at < c``
notifications             ``created_at < c``                               + its dedupe marker
========================  ==============================================  ================================

* **Intervals**: read from ``retention_policies`` on every run (``admin.public``), so an admin
  edit applies from the next run, as on Postgres. Months / days follow Postgres interval
  arithmetic (``'1 year'`` is a calendar year). A table without an active row is skipped and left
  out of the summary; an active row without an interval fails the run before anything is deleted
  (the SQL raises inside its single transaction).
* **Rows**: candidates come from single-field range queries on the predicate's time fields
  (``limit`` pages, so an empty table costs one read); each page is re-read and re-checked in the
  deleting transaction. ``batch * max_batches`` caps the deletions per table and run, like the SQL.
* **TTL guard**: 10 of these collections also carry a Firestore TTL ``expire_at`` stamped by their
  writers (fixed defaults, e.g. ``attempted_at + 395 days``). A TTL must never delete what the VM
  keeps -- after an admin lengthens an interval, for held evidence, for a deactivated policy, or
  where calendar months differ from the writer's days (``notifications``: 365 days vs '1 year').
  When that can happen the job reads the documents whose ``expire_at`` falls before
  ``now + GUARD_HORIZON`` (2 days: the next run plus one missed run) and moves ``expire_at`` to the
  first instant the SQL predicate is true (``None`` while kept). A stamp is only moved later, and
  only if it is still what the query saw (``hold_evidence`` may have just cleared it). TTL deletes
  that happen anyway delete only rows the predicate already selects; they are not counted in the
  summary (Firestore does not report them).
* **Audit**: one ``maint.retention.purged`` record per run, actor ``system:maint.retention``,
  target ``retention_policy``, ``after_state = {table: {partitions_dropped: 0, rows_deleted: n}}``
  (Firestore has no partitions).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

import structlog
from google.api_core import exceptions as gexc

from app.modules.admin.intervals import PgInterval, add_interval, subtract_interval

log = structlog.get_logger("app.retention.firestore")

JOB = "maint.retention"
PAGE = 100  # ScopedStore.query maximum page
GUARD_HORIZON = timedelta(days=2)
DEAD_ATTEMPTS = 10  # ``s.attempts >= 10`` is fixed in maint.purge_expired_rows

Basis = Callable[[dict[str, Any]], "datetime | None"]
Keep = Callable[[Any, list[Any]], Awaitable[set[str]]]


def _ts(v: Any) -> datetime | None:
    """A stored timestamp as a plain aware UTC ``datetime`` (Firestore returns
    ``DatetimeWithNanoseconds``); anything else is ``None``."""
    if not isinstance(v, datetime):
        return None
    v = v.astimezone(UTC) if v.tzinfo else v.replace(tzinfo=UTC)
    return datetime(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond, tzinfo=UTC)


def _coalesce(*fields: str) -> Basis:
    def basis(d: dict[str, Any]) -> datetime | None:
        for f in fields:
            t = _ts(d.get(f))
            if t is not None:
                return t
        return None

    return basis


def _outbox_basis(d: dict[str, Any]) -> datetime | None:
    dispatched = _ts(d.get("dispatched_at"))
    if dispatched is not None:
        return dispatched
    if int(d.get("attempts") or 0) >= DEAD_ATTEMPTS:
        return _ts(d.get("occurred_at"))
    return None


@dataclass(frozen=True)
class Target:
    table: str
    collection: str
    module: str | None  # TD_STORE_<module>; None: whenever any module is on Firestore
    scans: tuple[str, ...]  # range-query fields that find every row with basis < cutoff
    basis: Basis  # the time the SQL predicate compares with the cutoff (None: never due)
    keep: Keep | None = None  # rows the SQL keeps although due (NOT EXISTS / FK)
    ttl: bool = False  # writers stamp a TTL ``expire_at``
    # what the writers add to the basis for ``expire_at``; None: variable or inexact (always guard)
    writer_interval: PgInterval | None = None
    dedupe: bool = False  # notifications: the dedupe marker goes with its notification

    def due(self, d: dict[str, Any], cutoff: datetime) -> bool:
        b = self.basis(d)
        return b is not None and b < cutoff


# --------------------------------------------------------------------------- keep rules


async def _keep_signals(session: Any, docs: list[Any]) -> set[str]:
    from app.modules.security import public as sp

    users, _ = await sp.evidence_holds(session, [d.get("user_id") for d in docs])
    held = {str(u) for u in users}
    return {d.id for d in docs if d.get("user_id") is not None and str(d.get("user_id")) in held}


async def _keep_evaluations(session: Any, docs: list[Any]) -> set[str]:
    from app.modules.security import public as sp

    users, cases = await sp.evidence_holds(
        session, [d.get("user_id") for d in docs], [d.get("case_id") for d in docs]
    )
    hu, hc = {str(u) for u in users}, {str(c) for c in cases}
    return {d.id for d in docs if str(d.get("user_id")) in hu or str(d.get("case_id")) in hc}


async def _keep_bound_sessions(session: Any, docs: list[Any]) -> set[str]:
    """``test_attempts.bound_session_id REFERENCES auth_sessions(id)`` (no ON DELETE): Postgres
    cannot delete a session an attempt references, so neither does Firestore."""
    from app.modules.assessments import public as ap

    bound = await ap.attempt_bound_session_ids(session, [uuid.UUID(d.id) for d in docs])
    return {str(b) for b in bound}


@cache
def all_targets() -> tuple[Target, ...]:
    """The 12 tables of ``maint.run_retention``, in its order."""
    from app.core.firestore.core_store import IDEMPOTENCY, OUTBOX
    from app.modules.identity.store_specs import RESETS, TOKEN_RETENTION, VTOKENS
    from app.modules.media.store_specs import PLAYBACK
    from app.modules.media.store_specs import RETENTION as PLAY_RETENTION
    from app.modules.notifications.store_specs import NOTIFICATIONS
    from app.modules.security.repo_fs_engine import EVALS, SIGNALS
    from app.modules.sessions.store_specs import ATTEMPTS, AUTH_LOG_RETENTION, OBSERVATIONS, SESSIONS

    def fixed(td: timedelta) -> PgInterval:
        return PgInterval.from_timedelta(td)

    import app.modules.assessments.store_specs  # noqa: F401  (registers attempt_events)

    return (
        Target(
            "login_attempts",
            ATTEMPTS,
            "sessions",
            ("attempted_at",),
            _coalesce("attempted_at"),
            ttl=True,
            writer_interval=fixed(AUTH_LOG_RETENTION),
        ),
        Target(
            # last_seen_at is NOT NULL, so coalesce(last_seen_at, first_seen_at) = last_seen_at
            "session_network_observations",
            OBSERVATIONS,
            "sessions",
            ("last_seen_at",),
            _coalesce("last_seen_at", "first_seen_at"),
            # writers stamp first_seen_at + 395 d; observations are insert-only with last = first
            ttl=True,
            writer_interval=fixed(AUTH_LOG_RETENTION),
        ),
        Target(
            "auth_sessions",
            SESSIONS,
            "sessions",
            ("ended_at", "absolute_expires_at"),
            _coalesce("ended_at", "absolute_expires_at"),
            keep=_keep_bound_sessions,
        ),
        Target(
            "security_signals",
            SIGNALS,
            "security",
            ("occurred_at",),
            _coalesce("occurred_at"),
            keep=_keep_signals,
            ttl=True,
        ),
        Target(
            "risk_evaluations",
            EVALS,
            "security",
            ("evaluated_at",),
            _coalesce("evaluated_at"),
            keep=_keep_evaluations,
            ttl=True,
        ),
        Target(
            "playback_sessions",
            PLAYBACK,
            "media",
            ("started_at",),
            _coalesce("started_at"),
            ttl=True,
            writer_interval=fixed(PLAY_RETENTION),
        ),
        # The TTL policy exists but no writer stamps ``expire_at``: deleted by this job only.
        Target("attempt_events", "attempt_events", "assessments", ("occurred_at",), _coalesce("occurred_at")),
        Target(
            "verification_tokens",
            VTOKENS,
            "identity",
            ("consumed_at", "expires_at"),
            _coalesce("consumed_at", "expires_at"),
            # stamp = expires_at + 7 d >= coalesce(consumed_at, expires_at) + 7 d
            ttl=True,
            writer_interval=fixed(TOKEN_RETENTION),
        ),
        Target(
            "password_reset_tokens",
            RESETS,
            "identity",
            ("consumed_at", "expires_at"),
            _coalesce("consumed_at", "expires_at"),
            ttl=True,
            writer_interval=fixed(TOKEN_RETENTION),
        ),
        # Firestore modules emit into lms_outbox_events whatever TD_STORE_CORE says.
        Target("outbox_events", OUTBOX, None, ("dispatched_at", "occurred_at"), _outbox_basis),
        Target(
            "idempotency_keys",
            IDEMPOTENCY,
            "core",
            ("expires_at",),
            _coalesce("expires_at"),
            ttl=True,
            writer_interval=PgInterval(),
        ),
        Target(
            "notifications",
            NOTIFICATIONS,
            "notifications",
            ("created_at",),
            _coalesce("created_at"),
            ttl=True,
            dedupe=True,  # stamped created_at + 365 days; the policy is 1 calendar year
        ),
    )


def firestore_targets() -> list[Target]:
    """The tables whose rows live in Firestore on this stack (empty on the VM)."""
    from app.core.firestore.backend import firestore_modules, uses_firestore

    if not firestore_modules():
        return []
    return [t for t in all_targets() if t.module is None or uses_firestore(t.module)]


def eligible_from(basis: datetime, iv: PgInterval) -> datetime:
    """The instant ``t`` from which the SQL predicate ``basis < now - iv`` selects the row (it is
    true for every ``now > t``): ``basis + iv``, moved on by whole days where calendar months
    clamp at a month end (``'1 year'`` after 29 Feb). Never earlier than the predicate."""
    t = add_interval(basis, iv)
    for _ in range(4):
        if subtract_interval(t, iv) >= basis:
            return t
        t += timedelta(days=1)
    return t


def needs_guard(t: Target, iv: PgInterval | None) -> bool:
    """Can a writer's TTL stamp fire before the SQL predicate selects the row?"""
    if not t.ttl:
        return False
    if iv is None or t.writer_interval is None or iv.months:
        return True  # no active policy (keep all), variable stamps, or calendar months
    return iv > t.writer_interval


# --------------------------------------------------------------------------- the run


async def run_retention(
    batch: int = 5000, max_batches: int = 200, *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """``maint.run_retention(batch, max_batches)`` for the Firestore tables. Returns the SQL's
    rows ``(table_name, partitions_dropped, rows_deleted)``; ``[]`` when nothing is on Firestore."""
    targets = firestore_targets()
    if not targets:
        return []
    if batch < 1 or max_batches < 1:
        raise ValueError("maint.purge_expired_rows: batch sizes must be positive")
    from app.core.audit import AuditActor, audit
    from app.core.db import system_context
    from app.core.firestore.sqlstore import store_session
    from app.core.firestore.store import ScopedStore
    from app.core.time import utcnow
    from app.modules.admin import public as admin_public

    now = _ts(now or utcnow()) or utcnow()
    store = ScopedStore.system(JOB)
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    restamped: dict[str, int] = {}
    async with store_session() as session:
        await system_context(session, JOB)
        await admin_public.ensure_retention_defaults(session)
        intervals = await admin_public.active_retention_intervals(session)
        for t in targets:  # the SQL raises inside its one transaction: nothing deleted
            if t.table in intervals and intervals[t.table] is None:
                raise ValueError(f"maint.purge_expired_rows: {t.table} has no active retention policy")
        for t in targets:
            iv = intervals.get(t.table)
            deleted = 0
            if iv is not None:
                deleted = await _purge(session, store, t, subtract_interval(now, iv), batch * max_batches)
            if needs_guard(t, iv):
                try:
                    restamped[t.table] = await _guard(session, store, t, iv, now)
                except gexc.FailedPrecondition:
                    # firestore.indexes.json not deployed yet (expire_at ascending index): the
                    # rows are still purged and audited; the TTL may fire early until it is.
                    log.error("retention_ttl_guard_index_missing", table=t.table, collection=t.collection)
            if t.table in intervals:
                rows.append({"table_name": t.table, "partitions_dropped": 0, "rows_deleted": deleted})
                summary[t.table] = {"partitions_dropped": 0, "rows_deleted": deleted}
        await audit(
            session,
            AuditActor.system(JOB),
            "maint.retention.purged",
            "retention_policy",
            None,
            after=summary,
        )
    log.info(
        "retention_purged_firestore",
        rows=sum(int(r["rows_deleted"]) for r in rows),
        tables=len(rows),
        ttl_restamped=sum(restamped.values()),
    )
    return rows


async def _purge(session: Any, store: Any, t: Target, cutoff: datetime, cap: int) -> int:
    total = 0
    for field in t.scans:
        cursor: str | None = None
        while total < cap:
            page = await store.query(
                t.collection,
                filters=((field, "<", cutoff),),
                order_by=((field, "asc"),),
                limit=PAGE,
                cursor=cursor,
            )
            due = [d for d in page.items if t.due(d.data, cutoff)]
            if due:
                kept = await t.keep(session, due) if t.keep else set()
                ids = [d.id for d in due if d.id not in kept][: cap - total]
                if ids:
                    total += await _delete(store, t, ids, cutoff)
            if not page.next_cursor:
                break
            cursor = page.next_cursor
    return total


def _dedupe_refs(docs: dict[str, Any]) -> dict[str, str]:
    """notification id -> its dedupe marker's document id (notifications with a dedupe key)."""
    from app.modules.notifications.store_specs import dedupe_id

    return {i: dedupe_id(d.get("user_id"), d["dedupe_key"]) for i, d in docs.items() if d.get("dedupe_key")}


def _dedupe_collection() -> str:
    from app.modules.notifications.store_specs import DEDUPE

    return DEDUPE


async def _delete(store: Any, t: Target, ids: list[str], cutoff: datetime) -> int:
    """Delete ``ids`` that are still due (re-read in the transaction); a notification's dedupe
    marker goes with it when the marker still points at it."""

    async def fn(tx: Any) -> int:
        cur = await tx.get_many(t.collection, ids)
        markers: dict[str, str] = {}
        found: dict[str, Any] = {}
        if t.dedupe:
            markers = _dedupe_refs({i: d.data for i, d in cur.items()})
            if markers:
                found = await tx.get_many(_dedupe_collection(), list(markers.values()))
        n = 0
        for i, d in cur.items():
            if not t.due(d.data, cutoff):
                continue
            tx.raw_delete(t.collection, i)
            n += 1
            m = found.get(markers.get(i, ""))
            if m is not None and str(m.data.get("notification_id")) == i:
                tx.raw_delete(_dedupe_collection(), m.id)
        return n

    return int(await store.run_transaction(fn))


async def _guard(session: Any, store: Any, t: Target, iv: PgInterval | None, now: datetime) -> int:
    """Move TTL stamps that would fire before the SQL predicate selects the row (see module doc).
    Returns the number of documents re-stamped."""
    horizon = now + GUARD_HORIZON
    cursor: str | None = None
    changed = 0
    while True:
        page = await store.query(
            t.collection,
            filters=(("expire_at", "<", horizon),),
            order_by=(("expire_at", "asc"),),
            limit=PAGE,
            cursor=cursor,
        )
        if page.items:
            kept = await t.keep(session, page.items) if t.keep else set()
            fixes: dict[str, tuple[Any, datetime | None]] = {}
            for d in page.items:
                b = t.basis(d.data)
                want = None if (iv is None or b is None or d.id in kept) else eligible_from(b, iv)
                seen = _ts(d.get("expire_at"))
                if want is None or seen is None or seen < want:
                    fixes[d.id] = (d.get("expire_at"), want)
            if fixes:
                changed += await _restamp(store, t, fixes)
        if not page.next_cursor:
            return changed
        cursor = page.next_cursor


async def _restamp(store: Any, t: Target, fixes: dict[str, tuple[Any, datetime | None]]) -> int:
    async def fn(tx: Any) -> int:
        cur = {i: d.data for i, d in (await tx.get_many(t.collection, list(fixes))).items()}
        markers: dict[str, str] = {}
        found: dict[str, Any] = {}
        if t.dedupe:
            markers = _dedupe_refs(cur)
            if markers:
                found = await tx.get_many(_dedupe_collection(), list(markers.values()))
        n = 0
        for i, data in cur.items():
            seen, want = fixes[i]
            # unchanged since the query (``hold_evidence`` may have just set None)
            if _ts(data.get("expire_at")) != _ts(seen):
                continue
            tx.raw_set(t.collection, i, {**data, "expire_at": want})
            n += 1
            m = found.get(markers.get(i, ""))
            if m is not None and str(m.data.get("notification_id")) == i:
                tx.raw_set(_dedupe_collection(), m.id, {**m.data, "expire_at": want})
        return n

    return int(await store.run_transaction(fn))
