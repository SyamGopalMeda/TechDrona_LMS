"""The request's commit point for writes buffered without Postgres (Firebase stack).

On Postgres, an audit row (``core.audit``) and an outbox event (``core.outbox.emit_event``)
commit or roll back with the request transaction. Without a Postgres session they are buffered
per request (``audit.begin_buffer`` / ``outbox.begin_event_buffer``, opened by
``RequestContextMiddleware``) and:

* written together in ONE Firestore transaction when the response starts with status < 500 and
  no error reached the error handlers (``audit.mark_failed``), or
* dropped otherwise (the rollback equivalent).

A store-layer unit of work (e.g. ``sqlstore.commit_all``) may write them earlier inside its own
transaction with ``audit.write_pending`` / ``outbox.write_pending_events`` and then
``mark_written`` / ``mark_events_written`` (fully atomic with the business writes).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from app.core import audit, outbox


class Buffers:
    __slots__ = ("audit_tokens", "event_token")

    def __init__(self) -> None:
        self.audit_tokens = audit.begin_buffer()
        self.event_token = outbox.begin_event_buffer()

    def close(self) -> None:
        drop()
        outbox.end_event_buffer(self.event_token)
        audit.end_buffer(self.audit_tokens)


def has_pending() -> bool:
    return bool(audit.pending_docs() or outbox.pending_events())


def drop() -> None:
    audit.drop_pending()
    outbox.drop_pending_events()


async def commit() -> int:
    docs, events = audit.pending_docs(), outbox.pending_events()
    if not docs and not events:
        return 0
    from app.core.firestore.store import ScopedStore

    async def fn(tx: Any) -> None:
        audit.write_pending(tx, docs)
        outbox.write_pending_events(tx, events)

    await ScopedStore.system("core.request_commit").run_transaction(fn)
    audit.mark_written(docs)
    outbox.mark_events_written(events)
    return len(docs) + len(events)


async def on_response_start(status: int) -> None:
    if not has_pending():
        return
    if status < 500 and not audit.request_failed():
        await commit()
    else:
        drop()


# --------------------------------------------------------------------------- public buffer API
# (security pass 2, request 8). Code that used ``audit._pending`` / ``outbox._pending_events``
# directly should switch to these; the private names keep working.


@dataclass(frozen=True, slots=True)
class Checkpoint:
    audit_ids: frozenset[Any]
    event_ids: frozenset[Any]


def is_open() -> bool:
    """True inside a request (or ``buffer_open``) buffer scope."""
    return audit._pending.get() is not None


def checkpoint() -> Checkpoint:
    """Remember the buffered audit rows / outbox events (a SAVEPOINT for the buffers)."""
    return Checkpoint(
        frozenset(d.id for d in audit.pending_docs()), frozenset(e.id for e in outbox.pending_events())
    )


def rollback_to(token: Checkpoint) -> int:
    """Drop everything buffered after ``token`` (ROLLBACK TO SAVEPOINT); returns how many."""
    n = 0
    buf = audit._pending.get()
    if buf is not None:
        keep = [d for d in buf if d.id in token.audit_ids]
        n += len(buf) - len(keep)
        buf[:] = keep
    ebuf = outbox._pending_events.get()
    if ebuf is not None:
        ekeep = [e for e in ebuf if e.id in token.event_ids]
        n += len(ebuf) - len(ekeep)
        ebuf[:] = ekeep
    return n


@asynccontextmanager
async def buffer_open() -> AsyncIterator[None]:
    """Buffer scope for code outside a request (jobs, scripts, tests): audit rows and outbox
    events written inside are committed together when the block exits normally and dropped when
    it raises. Nested inside an open scope (a request) it acts as a savepoint: on error only its
    own rows are dropped, on success they stay for the outer commit point."""
    if is_open():
        cp = checkpoint()
        try:
            yield None
        except BaseException:
            rollback_to(cp)
            raise
        return
    buffers = Buffers()
    try:
        yield None
        await commit()
    finally:
        buffers.close()  # drops anything not committed (the error path)
