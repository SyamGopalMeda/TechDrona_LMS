"""Audit writer facade (ADR-0011): ``audit(...)`` inserts one row into ``audit_outbox`` in
the caller's transaction, so an audit record exists iff the action committed. The audit
module's sealer later moves rows into the hash-chained ``audit_log``.

``td_app`` holds INSERT only on ``audit_outbox``; nothing in the app can update or delete
audit rows.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import column, insert, table
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.request_context import get_request_id

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
    session: AsyncSession,
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


# Alias matching ADR-0011 wording (``core.audit.record()``).
record = audit
