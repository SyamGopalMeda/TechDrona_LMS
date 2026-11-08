"""RBAC API (api-specification §9: RBAC-01..06) and PermissionChecker registration.

Dual control for privileged roles (role matrix §5) writes ``approval_requests`` and returns
``202 approval_pending``. Until the admin module ships ADM-14/15, approvals for
``rbac.grant.privileged`` / ``rbac.revoke.privileged`` are decided here
(``/rbac/approval-requests/{id}/approve|reject``; ``approval.decide`` @P, P5, approver ≠
requester, approver must hold the required role). The same two action types are also
registered in the admin approvals registry (ADM-13), so ``/admin/approvals`` lists and decides
them; both paths enforce approver ≠ requester and approver ≠ grantee (ADM-19).

Single-company LMS: only Admin (``rbac.grant.manage`` @P) grants or revokes roles; the
college coordinator's "org staff" grant path and ``organization`` grant scope were removed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.audit import audit
from app.core.auth import (
    PLATFORM_SCOPE,
    register_permission_checker,
    require_active_principal,
    require_permission,
)
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError, problem_response
from app.core.idempotency import IdemResult, idempotent
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339
from app.modules.admin import approvals as apr
from app.modules.identity import clock
from app.modules.rbac import service as rs
from app.modules.rbac.catalogue import PERMISSIONS, ROLES
from app.modules.rbac.models import ApprovalRequest, Role, RoleGrant

register_permission_checker(rs.RbacPermissionChecker())

r = authenticated_router(prefix="/rbac", tags=["rbac"])
me_r = authenticated_router(prefix="/me", tags=["rbac"], route_tag="account_status", idle="neutral")


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    role_key: str = Field(min_length=3, max_length=40)
    scope_type: str = Field(pattern="^(platform|batch|course)$")
    scope_id: uuid.UUID | None = None
    expires_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class RevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=500)


def _grant_out(g: RoleGrant, role_key: str) -> dict[str, Any]:
    return {
        "grant_id": str(g.id),
        "user_id": str(g.user_id),
        "role_key": role_key,
        "scope_type": g.scope_type,
        "scope_id": str(g.scope_id) if g.scope_id else None,
        "organization_id": str(g.organization_id) if g.organization_id else None,
        "granted_by": str(g.granted_by),
        "granted_at": to_rfc3339(g.granted_at),
        "expires_at": to_rfc3339(g.expires_at) if g.expires_at else None,
        "reason": g.reason,
    }


def _p5(principal: Principal) -> None:
    from app.modules.identity.router import step_up_problem

    p = step_up_problem(principal, 300)
    if p:
        raise p


async def _authorize_grant_change(
    session: Any,
    principal: Principal,
    role_key: str,
    scope_type: str,
    scope_id: uuid.UUID | None,
    grantee: uuid.UUID,
) -> None:
    """``rbac.grant.manage`` @P (Admin) is the only way to grant or revoke a role."""
    del role_key, scope_type, scope_id, grantee  # same rule for every role and scope
    if await rs.check_permission(session, principal, "rbac.grant.manage", PLATFORM_SCOPE):
        return
    raise ProblemError("permission_denied", permission="rbac.grant.manage")


@r.get("/roles", openapi_extra={"x-td-idle": "neutral"})
async def list_roles(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    if not await rs.check_permission(session, principal, "rbac.grant.read", PLATFORM_SCOPE):
        raise ProblemError("permission_denied", permission="rbac.grant.read")
    roles = (await session.execute(select(Role).order_by(Role.role_key))).scalars().all()
    return {
        "data": [
            {
                "role_key": x.role_key,
                "name": x.name,
                "session_tier": x.session_tier,
                "mfa_required": x.mfa_required,
                "allowed_scope_types": list(x.allowed_scope_types),
                "dual_control": rs.is_dual_role(x.role_key),
            }
            for x in roles
        ]
    }


@r.get("/permissions", openapi_extra={"x-td-idle": "neutral"})
async def list_permissions(
    principal: Principal = Depends(require_permission("rbac.grant.read")),
) -> dict[str, Any]:
    return {
        "data": [
            {
                "permission_key": p.key,
                "module": p.module,
                "description": p.description,
                "step_up": p.is_sensitive,
                "dual": p.dual,
            }
            for p in PERMISSIONS.values()
        ]
    }


@r.get("/grants", openapi_extra={"x-td-idle": "neutral"})
async def list_grants(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    user_id: uuid.UUID | None = None,
    role: str | None = None,
    scope_type: str | None = None,
    scope_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    if not await rs.check_permission(session, principal, "rbac.grant.read", PLATFORM_SCOPE):
        raise ProblemError("permission_denied", permission="rbac.grant.read")
    rows = await rs.grants_in_scope(
        session, user_id=user_id, role_key=role, scope_type=scope_type, scope_id=scope_id, org_ids=None
    )
    return {"data": [_grant_out(g, rk) for g, rk in rows]}


@r.post("/grants", status_code=201)
async def create_grant(
    body: GrantIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    if body.role_key not in ROLES:
        raise ProblemError(
            "validation_failed",
            422,
            errors=[{"field": "role_key", "code": "unknown_role", "message": "Unknown role"}],
        )
    await _authorize_grant_change(
        session, principal, body.role_key, body.scope_type, body.scope_id, body.user_id
    )
    _p5(principal)

    async def op() -> IdemResult:
        from app.modules.identity.models import User

        if await session.get(User, body.user_id) is None:
            raise ProblemError("not_found")
        if body.user_id == principal.user_id:  # ADM-20: no self-grants at any scope
            raise ProblemError("sod_violation", rule="SoD-05")
        if rs.is_dual_role(body.role_key):
            role = (await session.execute(select(Role).where(Role.role_key == body.role_key))).scalar_one()
            org_id = await rs.resolve_grant_scope(session, role, body.scope_type, body.scope_id)
            await rs.check_sod(session, body.user_id, body.role_key)
            req = await rs.create_approval_request(
                session,
                principal,
                action_type="rbac.grant.privileged",
                target_type="user",
                target_id=body.user_id,
                payload=body.model_dump(mode="json"),
                reason=body.reason,
                required_approver_role="super_admin",
                organization_id=org_id,
            )
            return IdemResult(
                status=202,
                resource_id=req.id,
                body={
                    "status": "approval_pending",
                    "approval_request_id": str(req.id),
                    "action_type": req.action_type,
                    "required_approver_role": "super_admin",
                    "expires_at": to_rfc3339(req.expires_at),
                },
            )
        gid = await rs.create_grant(
            session,
            principal,
            user_id=body.user_id,
            role_key=body.role_key,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            expires_at=body.expires_at,
            reason=body.reason,
            granted_by=principal.user_id,
        )
        return IdemResult(
            status=201,
            resource_id=gid,
            body={"grant_id": str(gid), "session_effect": "grantee_sessions_rotated"},
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op)


@r.post("/grants/{grant_id}/revoke")
async def revoke_grant(
    grant_id: uuid.UUID,
    body: RevokeIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    row = (
        await session.execute(
            select(RoleGrant, Role.role_key)
            .join(Role, Role.id == RoleGrant.role_id)
            .where(RoleGrant.id == grant_id)
        )
    ).one_or_none()
    if row is None:
        raise ProblemError("not_found")
    grant, role_key = row
    await _authorize_grant_change(
        session, principal, role_key, grant.scope_type, grant.scope_id, grant.user_id
    )
    _p5(principal)

    async def op() -> IdemResult:
        if rs.is_dual_role(role_key):
            req = await rs.create_approval_request(
                session,
                principal,
                action_type="rbac.revoke.privileged",
                target_type="role_grant",
                target_id=grant.id,
                payload={"grant_id": str(grant.id), "reason": body.reason},
                reason=body.reason,
                required_approver_role="super_admin",
                organization_id=grant.organization_id,
            )
            return IdemResult(
                status=202,
                resource_id=req.id,
                body={
                    "status": "approval_pending",
                    "approval_request_id": str(req.id),
                    "action_type": req.action_type,
                    "required_approver_role": "super_admin",
                    "expires_at": to_rfc3339(req.expires_at),
                },
            )
        await rs.revoke_grant(session, principal, grant.id, principal.user_id, body.reason)
        return IdemResult(
            status=200,
            body={"grant_id": str(grant.id), "revoked": True, "session_effect": "grantee_sessions_rotated"},
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


PRIVILEGED_ACTIONS = ("rbac.grant.privileged", "rbac.revoke.privileged")


async def _grantee(session: Any, req: ApprovalRequest) -> uuid.UUID | None:
    p = req.payload
    if req.action_type == "rbac.grant.privileged":
        return uuid.UUID(p["user_id"])
    g = await session.get(RoleGrant, uuid.UUID(p["grant_id"]))
    return g.user_id if g is not None else None


async def _check_not_grantee(session: Any, principal: Principal, req: ApprovalRequest) -> None:
    """ADM-19: the person whose roles change can never approve that change (SoD-05)."""
    if await _grantee(session, req) == principal.user_id:
        raise ProblemError(
            "sod_violation", rule="SoD-05", detail="You cannot approve a change to your own roles."
        )


async def _execute_privileged(session: Any, principal: Principal, req: ApprovalRequest) -> dict[str, Any]:
    p = req.payload
    if req.action_type == "rbac.grant.privileged":
        gid = await rs.create_grant(
            session,
            principal,
            user_id=uuid.UUID(p["user_id"]),
            role_key=p["role_key"],
            scope_type=p["scope_type"],
            scope_id=uuid.UUID(p["scope_id"]) if p.get("scope_id") else None,
            expires_at=datetime.fromisoformat(p["expires_at"]) if p.get("expires_at") else None,
            reason=p.get("reason"),
            granted_by=req.requested_by,
        )
        return {"grant_id": str(gid)}
    await rs.revoke_grant(session, principal, uuid.UUID(p["grant_id"]), req.requested_by, p.get("reason"))
    return {"grant_id": p["grant_id"], "revoked": True}


# ADM-13: privileged grant/revoke requests are decided from the one approvals queue
# (/admin/approvals, ADM-12..15) as well as through RBAC-07/08 below; both paths share the
# same SoD checks and executor.
for _action in PRIVILEGED_ACTIONS:
    apr.register(
        apr.ApprovalHandler(
            _action,
            "approval.decide",
            frozenset({"super_admin"}),
            _execute_privileged,
            check=_check_not_grantee,
        )
    )


async def _decide(
    approval_id: uuid.UUID, approve: bool, note: str | None, session: Any, principal: Principal
) -> Any:
    _p5(principal)
    req = (
        await session.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()
        )
    ).scalar_one_or_none()
    if req is None or req.action_type not in PRIVILEGED_ACTIONS:
        raise ProblemError("not_found")
    if await apr.expire_if_due(session, req):
        # ADM-23: return (not raise) so the "expired" status commits.
        return problem_response(ProblemError("invalid_state_transition", current_state="expired", allowed=[]))
    if req.status != "pending":
        raise ProblemError("invalid_state_transition", current_state=req.status, allowed=[])
    if req.requested_by == principal.user_id:
        raise ProblemError("sod_violation", rule="SoD-05")
    if not principal.has_role(req.required_approver_role, "platform"):
        raise ProblemError("permission_denied", permission="approval.decide")
    if approve:
        await _check_not_grantee(session, principal, req)
    if rs.payload_hash(req.payload) != req.payload_hash:
        raise ProblemError("invalid_state_transition", current_state="payload_tampered", allowed=[])
    req.decided_by = principal.user_id
    req.decided_at = clock.now()
    req.decision_note = note
    if not approve:
        req.status = "rejected"
        await audit(session, principal, "approval.rejected", "approval_request", req.id, reason=note)
        return {"approval_request_id": str(req.id), "status": "rejected"}
    req.status = "approved"
    result = await _execute_privileged(session, principal, req)
    req.status = "executed"
    req.executed_at = clock.now()
    await audit(
        session,
        principal,
        "approval.executed",
        "approval_request",
        req.id,
        reason=note,
        after={"action_type": req.action_type, **result},
    )
    return {"approval_request_id": str(req.id), "status": "executed", **result}


@r.post("/approval-requests/{approval_request_id}/approve")
async def approve(
    approval_request_id: uuid.UUID,
    body: DecisionIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("approval.decide")),
) -> Any:
    return await _decide(approval_request_id, True, body.note, session, principal)


@r.post("/approval-requests/{approval_request_id}/reject")
async def reject(
    approval_request_id: uuid.UUID,
    body: DecisionIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("approval.decide")),
) -> Any:
    return await _decide(approval_request_id, False, body.note, session, principal)


@me_r.get("/grants")
async def my_grants(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    rows = await rs.grants_in_scope(
        session, user_id=principal.user_id, role_key=None, scope_type=None, scope_id=None, org_ids=None
    )
    from app.modules.sessions.login import PORTALS

    return {
        "data": [_grant_out(g, rk) for g, rk in rows],
        "portals": sorted({PORTALS[rk] for _, rk in rows if rk in PORTALS}) or ["/app"],
    }


router = APIRouter()
router.include_router(r)
router.include_router(me_r)
