"""Work hints and event kicks for the Firebase dispatcher (``app.core.scheduler``).

Active only in *event mode* (``TD_TASKS_BACKEND=cloudtasks`` and no Postgres, i.e. the final
Firebase stack; ``scheduler.event_mode``). Everywhere else every function here is a no-op, so the
VM (Celery beat) and the hybrid Firebase+Postgres stack behave exactly as before.

**Hints** (``lms_scheduler_state/hints``, one document). Every Firestore transaction of
``ScopedStore`` that writes a *watched* collection (the union of ``scheduler.GATES[*].watch``) also
sets ``w.<collection> = SERVER_TIMESTAMP`` on the hint document **in the same commit** (so the hint
exists iff the data does). To keep that cheap a process writes the hint for a collection at most
once per ``HINT_REFRESH_S``; the dispatcher therefore treats a collection as written since ``S``
when ``w.<collection> >= S - SKIP_MARGIN`` (``SKIP_MARGIN`` > ``HINT_REFRESH_S`` + clock slack).
Proof sketch: a commit at ``c`` either wrote the hint (``w >= c``) or a hint was committed by the
same process at ``h > c - HINT_REFRESH_S`` (``w >= h``); for any ``S < c``:
``w > c - HINT_REFRESH_S > S - SKIP_MARGIN``. Writes that bypass ``ScopedStore`` (none today for
watched collections) are covered by the weekly full sweep (``scheduler.BACKSTOP_EVERY_DAYS``).

**Kicks.** After a commit that *created* ``outbox_events`` / ``audit_outbox`` documents, a Cloud Task
for ``core.outbox_relay`` / ``core.audit_seal`` is scheduled at the next whole second
(``KICK_COALESCE_S``), strictly after the commit; one task per second per process (in-memory
dedupe), so a burst of writes costs one task. A commit
that writes an in-progress test attempt / active section with a ``deadline_at`` schedules
``assessments.deadline_sweeper`` at ``deadline_at + 1 s`` (the sweep itself then schedules the next
``deadline + grace``). A failed kick is logged; the hint makes the dispatcher's next minute run the
job (backstop), so nothing is ever lost.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger("app.jobhints")

HINTS = "scheduler_state"
HINT_DOC = "hints"
HINT_REFRESH_S = 30.0
SKIP_MARGIN = timedelta(seconds=90)

RELAY_JOB = "core.outbox_relay"
SEAL_JOB = "core.audit_seal"
DEADLINE_JOB = "assessments.deadline_sweeper"
CERT_SEND_JOB = "learning.certificate_outbox_send"
# Certificate emails were picked up by an every-minute sweep; with hourly ticks they are kicked too.
KICK_ON_CREATE = {"outbox_events": RELAY_JOB, "audit_outbox": SEAL_JOB, "certificate_outbox": CERT_SEND_JOB}
DEADLINE_COLLECTIONS = {"test_attempts": "in_progress", "attempt_sections": "active"}

_registered = False
_hint_written: dict[str, float] = {}  # collection -> time.monotonic() of the last committed hint
_scheduled: dict[tuple[str, float], float] = {}  # (job, run-at epoch) -> epoch it was enqueued
_active_cache: tuple[Any, bool] | None = None


def _register() -> None:
    global _registered
    if not _registered:
        from app.core.firestore.collections import CollectionSpec, register_collection

        register_collection(CollectionSpec(HINTS, "system"))
        _registered = True


_register()


def active() -> bool:
    """Event mode (cached per settings object: ``reset_settings_cache`` re-evaluates)."""
    global _active_cache
    from app.core.config import get_settings

    s = get_settings()
    if _active_cache is None or _active_cache[0] is not s:
        from app.core.scheduler import event_mode

        _active_cache = (s, event_mode())
    return _active_cache[1]


def watched() -> frozenset[str]:
    from app.core.scheduler import watched_collections

    return watched_collections()


@dataclass
class TxNotes:
    """What one transaction attempt wrote (filled by ``ScopedTransaction``)."""

    written: set[str] = field(default_factory=set)
    created: set[str] = field(default_factory=set)
    deadlines: set[datetime] = field(default_factory=set)
    hinted: set[str] = field(default_factory=set)


def note(notes: TxNotes, collection: str, data: Any, *, created: bool) -> None:
    notes.written.add(collection)
    if created:
        notes.created.add(collection)
    want = DEADLINE_COLLECTIONS.get(collection)
    if want is not None and isinstance(data, dict) and data.get("status") == want:
        d = data.get("deadline_at")
        if isinstance(d, datetime):
            notes.deadlines.add(d)


def _due_hints(written: Iterable[str]) -> set[str]:
    w = watched()
    now = time.monotonic()
    return {c for c in written if c in w and now - _hint_written.get(c, -1e18) >= HINT_REFRESH_S}


def hint_ref(client: Any) -> Any:
    from app.core.firestore.jobstate import hint_ref as ref

    return ref(client)


def hint_payload(collections: Iterable[str]) -> dict[str, Any]:
    from app.core.firestore.jobstate import hint_payload as payload

    return payload(collections)


def before_commit(stx: Any) -> None:
    """Add the hint write to the transaction (same commit as the data). Sync, no I/O."""
    notes: TxNotes | None = getattr(stx, "notes", None)
    if notes is None or not notes.written:
        return
    due = _due_hints(notes.written)
    notes.hinted = due
    if due:
        stx.raw.set(hint_ref(stx.store.client), hint_payload(due), merge=True)


def _committed(notes: TxNotes) -> None:
    now = time.monotonic()
    for c in notes.hinted:
        _hint_written[c] = now


async def after_commit(stx: Any) -> None:
    notes: TxNotes | None = getattr(stx, "notes", None)
    if notes is None:
        return
    _committed(notes)
    await kick_for(notes)


async def after_direct_write(client: Any, notes: TxNotes) -> None:
    """Non-transactional writes (``ScopedStore.create`` / bulk helpers): separate hint write."""
    if not notes.written or not active():
        return
    due = _due_hints(notes.written)
    if due:
        try:
            await hint_ref(client).set(hint_payload(due), merge=True)
            notes.hinted = due
            _committed(notes)
        except Exception as e:  # the hourly full sweep still covers it
            log.warning("job_hint_write_failed", error=type(e).__name__)
    await kick_for(notes)


async def kick_for(notes: TxNotes) -> None:
    for coll, job in KICK_ON_CREATE.items():
        if coll in notes.created:
            await kick(job)
    for d in sorted(notes.deadlines):
        await kick_at(DEADLINE_JOB, d + timedelta(seconds=1))


# --------------------------------------------------------------------------- kicks


KICK_COALESCE_S = 1.0


def kick_interval(job: str) -> float:
    """Coalescing window of a kick: one task per window per process, scheduled at the window's
    end (strictly after the commit). 1 s, never longer than the job's old loop interval
    (``TD_OUTBOX_RELAY_INTERVAL_SECONDS`` 5 s, ``TD_AUDIT_SEALER_INTERVAL_SECONDS`` 2 s)."""
    from app.core.config import get_settings

    s = get_settings()
    if job == RELAY_JOB:
        return min(KICK_COALESCE_S, float(s.TD_OUTBOX_RELAY_INTERVAL_SECONDS))
    if job == SEAL_JOB:
        return min(KICK_COALESCE_S, float(s.TD_AUDIT_SEALER_INTERVAL_SECONDS))
    return KICK_COALESCE_S


def next_boundary(now: float, interval: float) -> float:
    """The first multiple of ``interval`` strictly after ``now`` (epoch seconds)."""
    return (math.floor(now / interval) + 1) * interval


async def kick(job: str, *, now: float | None = None) -> bool:
    """Schedule ``job`` at the next interval boundary (strictly after now). True if enqueued."""
    if not active():
        return False
    now = time.time() if now is None else now
    return await _enqueue(job, next_boundary(now, kick_interval(job)), now)


async def kick_at(job: str, when: datetime, *, now: float | None = None) -> bool:
    """Schedule ``job`` at ``when`` (or now, when that is already past). True if enqueued."""
    if not active():
        return False
    now = time.time() if now is None else now
    at = max(math.ceil(when.timestamp()), math.ceil(now))
    return await _enqueue(job, float(at), now)


async def _enqueue(job: str, at: float, now: float) -> bool:
    key = (job, round(at, 3))
    if key in _scheduled:
        return False
    for k in list(_scheduled):  # forget runs well in the past
        if k[1] < now - 3600:
            _scheduled.pop(k, None)
    from app.core import cloudtasks
    from app.core.scheduler import entry_for

    eta = datetime.fromtimestamp(at, UTC)
    try:
        e = entry_for(job)
        await asyncio.to_thread(cloudtasks.send_task, e.task, e.args, e.kwargs, eta=eta, queue=e.queue)
    except Exception as ex:  # the hint + the dispatcher's minute backstop cover it
        log.warning("job_kick_failed", job=job, error=type(ex).__name__)
        return False
    _scheduled[key] = now
    return True


def reset_for_tests() -> None:
    global _active_cache
    _hint_written.clear()
    _scheduled.clear()
    _active_cache = None
