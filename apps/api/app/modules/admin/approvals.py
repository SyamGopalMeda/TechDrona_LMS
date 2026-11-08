"""Dual-control queue (API §1.7, ADM-12..16): an executor registry keyed by ``action_type``.

Modules register ``ApprovalHandler``s at import time. ADM-14 re-verifies the payload hash,
enforces approver ≠ requester (``sod_violation``), the approver permission and approver role
for that action type, and runs ``execute`` in the same transaction (status ``executed``).
``security.case.decision`` is decided through SEC-10/11 instead (never ADM-14).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE
from app.core.errors import ProblemError
from app.core.principal import Principal
from app.core.time import to_rfc3339
from app.modules.identity import clock
from app.modules.rbac import service as rs
from app.modules.rbac.models import ApprovalRequest

Executor = Callable[[AsyncSession, Principal, ApprovalRequest], Awaitable[dict[str, Any]]]
Hook = Callable[[AsyncSession, Principal, ApprovalRequest], Awaitable[None]]


@dataclass(frozen=True)
class ApprovalHandler:
    action_type: str
    approver_permission: str
    approver_roles: frozenset[str]
    execute: Executor
    on_reject: Hook | None = None
    check: Hook | None = None  # extra SoD / conflict checks before execution


_HANDLERS: dict[str, ApprovalHandler] = {}
APPROVAL_TTL = timedelta(hours=72)
NOT_VIA_ADMIN = frozenset({"security.case.decision"})


async def new_request(session: AsyncSession, principal: Principal, **kw: Any) -> ApprovalRequest:
    """``rbac.service.create_approval_request`` with ``expires_at`` on the module clock (72 h)."""
    req = await rs.create_approval_request(session, principal, **kw)
    req.created_at = clock.now()
    req.expires_at = clock.now() + APPROVAL_TTL
    await session.flush()
    return req


def register(handler: ApprovalHandler) -> None:
    _HANDLERS[handler.action_type] = handler


def handler_for(action_type: str) -> ApprovalHandler | None:
    return _HANDLERS.get(action_type)


def approval_out(req: ApprovalRequest, *, include_payload: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "approval_request_id": str(req.id),
        "action_type": req.action_type,
        "target_type": req.target_type,
        "target_id": str(req.target_id) if req.target_id else None,
        "requested_by": str(req.requested_by),
        "request_reason": req.request_reason,
        "required_approver_role": req.required_approver_role,
        "status": req.status,
        "decided_by": str(req.decided_by) if req.decided_by else None,
        "decided_at": to_rfc3339(req.decided_at) if req.decided_at else None,
        "decision_note": req.decision_note,
        "expires_at": to_rfc3339(req.expires_at),
        "created_at": to_rfc3339(req.created_at) if req.created_at else None,
    }
    if include_payload:
        out["payload"] = req.payload
        out["payload_hash"] = req.payload_hash.hex()
    return out


def pending_response(req: ApprovalRequest) -> dict[str, Any]:
    return {
        "status": "approval_pending",
        "approval_request_id": str(req.id),
        "action_type": req.action_type,
        "required_approver_role": req.required_approver_role,
        "expires_at": to_rfc3339(req.expires_at),
    }


async def can_approve(
    session: AsyncSession, principal: Principal, req_or_type: ApprovalRequest | str
) -> bool:
    action_type = req_or_type if isinstance(req_or_type, str) else req_or_type.action_type
    h = _HANDLERS.get(action_type)
    if h is None:
        return False
    if not any(principal.has_role(r, "platform") for r in h.approver_roles):
        return False
    return await rs.check_permission(session, principal, h.approver_permission, PLATFORM_SCOPE)


async def load_for_update(session: AsyncSession, approval_id: uuid.UUID) -> ApprovalRequest:
    req = (
        await session.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()
        )
    ).scalar_one_or_none()
    if req is None:
        raise ProblemError("not_found")
    return req


def ensure_pending(req: ApprovalRequest) -> None:
    """Raise unless ``req`` is pending and unexpired. Callers must persist ``expired`` first
    (see ``expire_if_due``): a raise rolls the transaction back, so setting the status here
    would be lost (ADM-23)."""
    if req.status != "pending":
        raise ProblemError("invalid_state_transition", current_state=req.status, allowed=[])
    if req.expires_at <= clock.now():
        raise ProblemError("invalid_state_transition", current_state="expired", allowed=[])


async def expire_if_due(session: AsyncSession, req: ApprovalRequest) -> bool:
    """Mark a pending, past-due request ``expired`` and flush. The caller then returns a 409
    without raising so the status change commits (ADM-23)."""
    if req.status == "pending" and req.expires_at <= clock.now():
        req.status = "expired"
        await session.flush()
        return True
    return False


def expired_body(req: ApprovalRequest) -> dict[str, Any]:
    return {"approval_request_id": str(req.id), "status": "expired", "_expired": True}


async def decide(
    session: AsyncSession, principal: Principal, approval_id: uuid.UUID, *, approve: bool, note: str | None
) -> dict[str, Any]:
    req = await load_for_update(session, approval_id)
    h = _HANDLERS.get(req.action_type)
    if h is None or req.action_type in NOT_VIA_ADMIN:
        raise ProblemError("not_found")
    if await expire_if_due(session, req):
        return expired_body(req)
    ensure_pending(req)
    if req.requested_by == principal.user_id:
        raise ProblemError("sod_violation", rule="SoD-05", detail="You cannot decide your own request.")
    if not await can_approve(session, principal, req):
        raise ProblemError("permission_denied", permission=h.approver_permission)
    if h.check is not None:
        await h.check(session, principal, req)
    if rs.payload_hash(req.payload) != req.payload_hash:
        raise ProblemError("invalid_state_transition", current_state="payload_tampered", allowed=[])
    now = clock.now()
    req.decided_by = principal.user_id
    req.decided_at = now
    req.decision_note = note
    if not approve:
        req.status = "rejected"
        await session.flush()
        if h.on_reject is not None:
            await h.on_reject(session, principal, req)
        await audit(
            session,
            principal,
            "approval.rejected",
            "approval_request",
            req.id,
            reason=note,
            after={"action_type": req.action_type},
        )
        return {"approval_request_id": str(req.id), "status": "rejected"}
    req.status = "approved"
    await session.flush()
    result = await h.execute(session, principal, req)
    req.status = "executed"
    req.executed_at = clock.now()
    await session.flush()
    await audit(
        session,
        principal,
        "approval.executed",
        "approval_request",
        req.id,
        reason=note,
        after={"action_type": req.action_type, **{k: v for k, v in result.items() if k != "rows"}},
    )
    return {"approval_request_id": str(req.id), "status": "executed", "result": result}


async def cancel(session: AsyncSession, principal: Principal, approval_id: uuid.UUID) -> dict[str, Any]:
    req = await load_for_update(session, approval_id)
    if req.requested_by != principal.user_id:
        raise ProblemError("permission_denied", permission="approval.cancel")
    if await expire_if_due(session, req):
        return expired_body(req)
    ensure_pending(req)
    req.status = "cancelled"
    await session.flush()
    h = _HANDLERS.get(req.action_type)
    if h is not None and h.on_reject is not None:
        await h.on_reject(session, principal, req)
    await audit(
        session,
        principal,
        "approval.cancelled",
        "approval_request",
        req.id,
        after={"action_type": req.action_type},
    )
    return {"approval_request_id": str(req.id), "status": "cancelled"}
