"""Audit writer facade (ADR-0011): ``audit(...)`` inserts one row into ``audit_outbox`` in
the caller's transaction, so an audit record exists iff the action committed. The audit
module's sealer later moves rows into the hash-chained ``audit_log``.

``td_app`` holds INSERT only on ``audit_outbox``; nothing in the app can update or delete
audit rows.

``TD_STORE_AUDIT=firestore``: pass the caller's Firestore transaction (``ScopedTransaction``) as
``session``; the record goes to ``audit.repo_firestore.enqueue`` in that transaction, so it commits
atomically with the Firestore business write. With a Postgres session (a module not moved yet) or
``None`` the record is written in its own Firestore transaction (``enqueue_now``) -- the audit
store is Firestore then, and nothing would ever seal a Postgres row. Default (``postgres``):
unchanged, a Firestore transaction is refused (it cannot be atomic with ``audit_outbox``).
"""

from __future__ import annotations

import json
import re
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import column, insert, table
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.request_context import get_request_id
from app.core.time import utcnow

ActorType = Literal["user", "system", "gateway", "support_impersonation"]
ACTION_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$")

_audit_outbox = table(
    "audit_outbox",
    column("id", UUID(as_uuid=True)),
    column("record", JSONB),
)


@dataclass(frozen=True, slots=True)
class AuditActor:
    actor_type: ActorType
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    roles: tuple[str, ...] = ()
    system_job: str | None = None

    @classmethod
    def system(cls, job: str) -> AuditActor:
        return cls("system", system_job=job)

    @classmethod
    def from_principal(cls, p: Principal) -> AuditActor:
        return cls("user", user_id=p.user_id, session_id=p.session_id, roles=p.role_keys)


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    return json.loads(json.dumps(v, default=_default, sort_keys=True))


def _default(o: Any) -> Any:
    if isinstance(o, uuid.UUID):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, set | frozenset | tuple):
        return sorted(o) if isinstance(o, set | frozenset) else list(o)
    raise TypeError(f"not JSON serialisable for audit: {type(o).__name__}")


def _s(v: uuid.UUID | None) -> str | None:
    return str(v) if v is not None else None


async def audit(
    session: AsyncSession | Any,
    actor: Principal | AuditActor,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None = None,
    *,
    organization_id: uuid.UUID | None = None,
    subject_user_id: uuid.UUID | None = None,
    reason_code: str | None = None,
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    request_id: str | None = None,
) -> uuid.UUID:
    """Record a privileged action. ``before``/``after`` must be minimised diffs (no
    secrets, no raw tokens, no unnecessary PII)."""
    if not ACTION_RE.match(action):
        raise ValueError(f"invalid audit action {action!r}")
    from app.core.firestore.backend import uses_firestore

    on_firestore = uses_firestore("audit")
    is_fs_tx = _is_firestore_tx(session)
    if on_firestore or is_fs_tx:
        if not on_firestore:
            raise TypeError("audit() got a Firestore transaction but TD_STORE_AUDIT=postgres")
        from app.modules.audit import repo_firestore

        kw: dict[str, Any] = {
            "organization_id": organization_id,
            "subject_user_id": subject_user_id,
            "reason_code": reason_code,
            "reason": reason,
            "before": before,
            "after": after,
            "ip": ip,
            "request_id": request_id,
        }
        if is_fs_tx:
            return await repo_firestore.enqueue(session, actor, action, target_type, target_id, **kw)  # type: ignore[arg-type]
        buf = _pending.get()
        if buf is not None:
            # In a request with no Firestore transaction: buffered, written at the request's commit
            # point (``flush_pending``), dropped when the request fails -- as on Postgres, where the
            # row commits or rolls back with the request transaction.
            fs_record = repo_firestore.build_record(actor, action, target_type, target_id, **kw)
            audit_id = uuid7()
            buf.append(PendingAudit(audit_id, fs_record, utcnow()))
            return audit_id
        return await repo_firestore.enqueue_now(actor, action, target_type, target_id, **kw)
    a = AuditActor.from_principal(actor) if isinstance(actor, Principal) else actor
    record: dict[str, Any] = {
        "actor_type": a.actor_type,
        "actor_user_id": _s(a.user_id),
        "actor_session_id": _s(a.session_id),
        "actor_roles": list(a.roles) or ([f"system:{a.system_job}"] if a.system_job else []),
        "action": action,
        "target_type": target_type,
        "target_id": _s(target_id),
        "organization_id": _s(organization_id),
        "subject_user_id": _s(subject_user_id),
        "reason_code": reason_code,
        "reason": reason,
        "before_state": _jsonable(before),
        "after_state": _jsonable(after),
        "request_id": request_id or get_request_id(),
        "ip": ip,
    }
    audit_id = uuid7()
    await session.execute(insert(_audit_outbox).values(id=audit_id, record=record))
    return audit_id


# --------------------------------------------------------------------------- request buffer (Firestore)
#
# ``RequestContextMiddleware`` opens a buffer per HTTP request (``begin_buffer``). With
# ``TD_STORE_AUDIT=firestore`` and no explicit Firestore transaction, ``audit()`` appends to it.
# Commit points:
#   * a store-layer unit of work may write the buffer inside its own Firestore transaction:
#     ``docs = pending_docs()`` -> ``write_pending(tx, docs)`` in the body -> after success
#     ``mark_written(docs)`` (atomic with the business writes; e.g. ``sqlstore.commit_all``);
#   * the end of a successful request: the middleware calls ``flush_pending()`` when the
#     response starts with status < 500 and no exception reached the error handlers
#     (``mark_failed``); otherwise ``drop_pending()`` -- the Postgres rollback equivalent.


@dataclass(frozen=True, slots=True)
class PendingAudit:
    id: uuid.UUID
    record: dict[str, Any]
    occurred_at: datetime


_pending: ContextVar[list[PendingAudit] | None] = ContextVar("td_audit_pending", default=None)
_failed: ContextVar[list[bool] | None] = ContextVar("td_audit_failed", default=None)
BufferTokens = tuple[Token[list[PendingAudit] | None], Token[list[bool] | None]]


def begin_buffer() -> BufferTokens:
    return _pending.set([]), _failed.set([])


def end_buffer(tokens: BufferTokens) -> None:
    _pending.reset(tokens[0])
    _failed.reset(tokens[1])


def mark_failed() -> None:
    """The request raised (the error handlers call this): buffered audit rows are dropped."""
    f = _failed.get()
    if f is not None:
        f.append(True)


def request_failed() -> bool:
    return bool(_failed.get())


def pending_docs() -> list[PendingAudit]:
    return list(_pending.get() or ())


def write_pending(tx: Any, docs: list[PendingAudit]) -> None:
    """Write buffered rows inside the caller's Firestore transaction (pure: retry-safe)."""
    from app.modules.audit import repo_firestore
    from app.modules.audit.store_specs import OUTBOX

    for d in docs:
        tx.raw_create(OUTBOX, str(d.id), repo_firestore.outbox_doc(d.id, d.record, d.occurred_at))


def mark_written(docs: list[PendingAudit]) -> None:
    buf = _pending.get()
    if buf is not None:
        done = {d.id for d in docs}
        buf[:] = [d for d in buf if d.id not in done]


def drop_pending() -> int:
    buf = _pending.get()
    n = len(buf or ())
    if buf:
        buf.clear()
    return n


async def flush_pending() -> int:
    """Write every buffered row in one Firestore transaction (end of a successful request)."""
    docs = pending_docs()
    if not docs:
        return 0
    from app.core.firestore.store import ScopedStore

    async def fn(tx: Any) -> None:
        write_pending(tx, docs)

    await ScopedStore.system("audit.writer").run_transaction(fn)
    mark_written(docs)
    return len(docs)


def _is_firestore_tx(session: Any) -> bool:
    """Duck-typed so this module never imports the Firestore client (boundary lint)."""
    return type(session).__name__ == "ScopedTransaction" and hasattr(session, "raw_create")


# Alias matching ADR-0011 wording (``core.audit.record()``).
record = audit
