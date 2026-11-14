"""Admin API: policy settings (ADM-07..09), feature flags (ADM-10/11), dual-control approvals
(ADM-12..16) and DPDP privacy requests (PRV-01..13).

Importing this module registers the admin policy resolver with ``identity.policy`` and the
``policy.change`` approval executor.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, require_active_principal, require_permission
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError, problem_response
from app.core.firestore.backend import uses_firestore
from app.core.idempotency import IdemResult, idempotent
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339, within
from app.modules.admin import accounts
from app.modules.admin import approvals as apr
from app.modules.admin import flags as flags_mod
from app.modules.admin import policy as pol
from app.modules.admin import privacy as prv
from app.modules.admin.fs_rows import idem_session, pg_system
from app.modules.admin.intervals import interval_days
from app.modules.admin.models import FeatureFlag, PrivacyRequest, RetentionPolicy
from app.modules.identity import clock
from app.modules.identity.policy import register_policy_resolver
from app.modules.rbac import service as rs
from app.modules.rbac.catalogue import ADMIN_ROLE, admin_roles
from app.modules.rbac.public import ApprovalRequest

register_policy_resolver(pol.identity_resolver)

r = authenticated_router(tags=["admin"], route_tag="default", idle="extends")
me_r = authenticated_router(prefix="/me", tags=["privacy"], route_tag="account_status", idle="extends")
NEUTRAL = {"x-td-idle": "neutral"}


def perm(key: str, scope: Any = None) -> Any:
    return Depends(require_permission(key, scope=scope))


def p5(principal: Principal, seconds: int = 300) -> None:
    if not within(principal.last_step_up_at, timedelta(seconds=seconds), now=clock.now()):
        raise ProblemError(
            "step_up_required",
            step_up={
                "max_age_seconds": seconds,
                "allowed_methods": ["totp"],  # SEC-11: WebAuthn passkeys are not built yet
                "options_url": "/api/v1/auth/step-up/options",
            },
        )


# --------------------------------------------------------------------------- policy settings


class ChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_type: Literal["platform", "plan", "user"] = "platform"
    scope_id: uuid.UUID | None = None
    value: Any
    effective_from: datetime | None = None
    change_reason: str = Field(min_length=5, max_length=1000)


async def _can_read_policy(session: Any, principal: Principal) -> None:
    for p in ("policy.edit", "policy.propose", "security.rule.read"):
        if await rs.check_permission(session, principal, p, PLATFORM_SCOPE):
            return
    raise ProblemError("permission_denied", permission="policy.edit")


@r.get("/admin/policy-settings", openapi_extra=NEUTRAL)
async def list_settings(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    await _can_read_policy(session, principal)
    from app.modules.rbac import public as rbac_public

    pending = await rbac_public.find_approvals(session, action_type="policy.change", status="pending")
    out = []
    active = await pol.active_platform_rows(session, list(pol.REGISTRY))
    for k in pol.REGISTRY.values():
        row = active.get(k.key)
        out.append(
            {
                **pol.setting_out(k, row),
                "pending_changes": [str(p.id) for p in pending if p.payload.get("setting_key") == k.key],
            }
        )
    return {"data": out}


@r.get("/admin/policy-settings/{setting_key}", openapi_extra=NEUTRAL)
async def get_setting(
    setting_key: str, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> JSONResponse:
    await _can_read_policy(session, principal)
    k = pol.spec(setting_key)
    rows = await pol.history_rows(session, setting_key)
    plat = next((x for x in rows if x.scope_type == "platform" and x.is_active), None)
    body = {
        **pol.setting_out(k, plat),
        "history": [
            {
                "version": x.version,
                "scope_type": x.scope_type,
                "scope_id": str(x.scope_id) if x.scope_id else None,
                "value": x.value,
                "is_active": x.is_active,
                "effective_from": to_rfc3339(x.effective_from),
                "expires_at": to_rfc3339(x.expires_at) if x.expires_at else None,
                "changed_by": str(x.changed_by),
                "approved_by": str(x.approved_by) if x.approved_by else None,
                "change_reason": x.change_reason,
            }
            for x in rows
        ],
    }
    return JSONResponse(body, headers={"ETag": f'"v{plat.version if plat else 0}"'})


async def _check_namespace(session: Any, principal: Principal, key: str) -> None:
    for role, prefixes in pol.PROPOSE_NAMESPACES.items():
        if principal.has_role(role, "platform") and any(key.startswith(p) for p in prefixes):
            return
    raise ProblemError("permission_denied", permission="policy.propose")


@r.post("/admin/policy-settings/{setting_key}/changes", status_code=202)
async def propose_change(
    setting_key: str,
    body: ChangeIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("policy.propose"),
) -> JSONResponse:
    p5(principal)

    async def op() -> IdemResult:
        k = pol.spec(setting_key)
        await _check_namespace(session, principal, setting_key)
        if body.scope_type == "user":
            raise ProblemError(
                "validation_failed",
                422,
                errors=[
                    {
                        "field": "scope_type",
                        "code": "user_scope_requires_case_decision",
                        "message": "User exceptions are created only by case decisions",
                    }
                ],
            )
        value = pol.validate_value(k, body.value)
        pol.check_scope(k, body.scope_type, body.scope_id, value)
        payload = {
            "setting_key": setting_key,
            "scope_type": body.scope_type,
            "scope_id": str(body.scope_id) if body.scope_id else None,
            "value": value,
            "effective_from": body.effective_from.isoformat() if body.effective_from else None,
            "change_reason": body.change_reason,
        }
        req = await apr.new_request(
            session,
            principal,
            action_type="policy.change",
            target_type="policy_setting",
            target_id=None,
            payload=payload,
            reason=body.change_reason,
            required_approver_role=ADMIN_ROLE,
        )
        return IdemResult(status=202, body=apr.pending_response(req))

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=True
    )


async def _execute_policy_change(session: Any, principal: Principal, req: ApprovalRequest) -> dict[str, Any]:
    p = req.payload
    if uses_firestore("admin"):
        # Runs inside the approval's decision journal (rbac.public.decision): the policy head and
        # the active row it replaces are captured so a later failure restores them, and the new
        # version row is removed (all-or-nothing, as the Postgres transaction).
        from app.modules.admin.repo_firestore import system_repo as _policy_repo
        from app.modules.admin.store_specs import POLICY, POLICY_HEADS, head_id
        from app.modules.identity.fs_journal import capture

        hid = head_id(p["setting_key"], p["scope_type"], p.get("scope_id"))
        head = await _policy_repo("admin.policy").store.get(POLICY_HEADS, hid)
        await capture(POLICY_HEADS, hid)
        if head is not None and head.get("active_id"):
            await capture(POLICY, head["active_id"])
    row = await pol.write_setting(
        session,
        key=p["setting_key"],
        scope_type=p["scope_type"],
        scope_id=uuid.UUID(p["scope_id"]) if p.get("scope_id") else None,
        value=p["value"],
        changed_by=req.requested_by,
        change_reason=p["change_reason"],
        approved_by=principal.user_id,
        approval_request_id=req.id,
        effective_from=datetime.fromisoformat(p["effective_from"]) if p.get("effective_from") else None,
    )
    if uses_firestore("admin"):
        from app.modules.identity.fs_journal import current as _journal

        j = _journal()
        if j is not None:
            j.record(POLICY, str(row.id), None)  # created by this action
    await audit(
        session,
        principal,
        "policy.change",
        "policy_setting",
        row.id,
        after={
            "setting_key": row.setting_key,
            "scope_type": row.scope_type,
            "value": row.value,
            "version": row.version,
        },
    )
    return {"setting_key": row.setting_key, "version": row.version, "value": row.value}


apr.register(apr.ApprovalHandler("policy.change", "policy.edit", admin_roles(), _execute_policy_change))


# --------------------------------------------------------------------------- feature flags


class FlagPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_enabled: bool | None = None
    rollout_percent: int | None = Field(default=None, ge=0, le=100)
    user_allowlist: list[uuid.UUID] | None = None


def _flag_out(f: Any) -> dict[str, Any]:
    return {
        "flag_key": f.flag_key,
        "description": f.description,
        "is_enabled": f.is_enabled,
        "rollout_percent": f.rollout_percent,
        "user_allowlist": [str(x) for x in f.user_allowlist],
    }


@r.get("/admin/feature-flags", openapi_extra=NEUTRAL)
async def flags(
    session: PrincipalDbSession, principal: Principal = perm("feature_flag.manage")
) -> dict[str, Any]:
    if uses_firestore("admin"):
        from app.core.firestore.store import ScopedStore
        from app.modules.admin.repo_firestore import AdminSettingsRepo

        return {"data": [_flag_out(f) for f in await AdminSettingsRepo(ScopedStore(principal)).list_flags()]}
    rows = (await session.execute(select(FeatureFlag).order_by(FeatureFlag.flag_key))).scalars()
    return {"data": [_flag_out(f) for f in rows]}


@r.patch("/admin/feature-flags/{flag_key}")
async def patch_flag(
    flag_key: str,
    body: FlagPatch,
    session: PrincipalDbSession,
    principal: Principal = perm("feature_flag.manage"),
) -> dict[str, Any]:
    p5(principal)
    f: Any
    if uses_firestore("admin"):
        from app.core.firestore.store import ScopedStore
        from app.modules.admin.repo_firestore import AdminSettingsRepo

        repo = AdminSettingsRepo(ScopedStore(principal))
        prev, f = await repo.patch_flag(flag_key, body.model_dump(exclude_none=True), principal.user_id)
        before = _flag_out(prev)
    else:
        f = (
            await session.execute(select(FeatureFlag).where(FeatureFlag.flag_key == flag_key))
        ).scalar_one_or_none()
        if f is None:
            raise ProblemError("not_found")
        before = _flag_out(f)
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(f, k, v)
        f.updated_by = principal.user_id
        await session.flush()
    flags_mod.invalidate(flag_key)
    await audit(
        session, principal, "feature_flag.changed", "feature_flag", f.id, before=before, after=_flag_out(f)
    )
    return _flag_out(f)


async def flag_enabled(
    session: Any, key: str, *, user_id: uuid.UUID | None = None, org_id: uuid.UUID | None = None
) -> bool:
    """ADM-17: one evaluation rule (``admin.flags.evaluate``); kept here for existing callers.
    ``org_id`` is ignored (single company)."""
    return await flags_mod.flag_enabled(session, key, user_id=user_id, org_id=org_id)


# --------------------------------------------------------------------------- approvals


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)


@r.get("/admin/approvals", openapi_extra=NEUTRAL)
async def approvals(
    session: PrincipalDbSession,
    # approval_requests.status CHECK (rbac_0001); anything else is a 400, not a silent empty list.
    status: Literal["pending", "approved", "rejected", "expired", "cancelled", "executed"] = "pending",
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    from app.modules.rbac import public as rbac_public

    rows = await rbac_public.find_approvals(session, status=status, order="expires_asc")
    out = []
    # a sole Admin may decide their own requests (rbac.service.is_sole_admin); the UI shows the
    # Approve/Reject buttons on their own rows only when this is true
    sole = await rs.is_sole_admin(session, principal.user_id)
    for q in rows:
        if q.requested_by == principal.user_id or await apr.can_approve(session, principal, q):
            out.append(
                {**apr.approval_out(q), "self_decidable": sole and q.requested_by == principal.user_id}
            )
    return {"data": out}


@r.get("/admin/approvals/{approval_id}", openapi_extra=NEUTRAL)
async def approval(
    approval_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    from app.modules.rbac import public as rbac_public

    q = await rbac_public.get_approval(session, approval_id)
    if q is None or not (q.requested_by == principal.user_id or await apr.can_approve(session, principal, q)):
        raise ProblemError("not_found")
    return apr.approval_out(q, include_payload=True)


async def _decide(
    approval_id: uuid.UUID, body: NoteIn, request: Request, session: Any, principal: Principal, approve: bool
) -> JSONResponse:
    # QA 2026-11-11 (D4): refuse people without approval.decide BEFORE asking for a step-up, so a
    # student/trainer can't trigger MFA/OTP prompts (or OTP e-mails) on an endpoint they can't use.
    from app.core.auth import PLATFORM_SCOPE, get_permission_checker

    checker = get_permission_checker()
    if checker is None or not await checker.has_permission(
        principal, "approval.decide", PLATFORM_SCOPE, request
    ):
        raise ProblemError("permission_denied", permission="approval.decide")
    p5(principal)

    async def op() -> IdemResult:
        out = await apr.decide(session, principal, approval_id, approve=approve, note=body.note)
        if out.pop("_expired", False):
            exc = ProblemError("invalid_state_transition", current_state="expired", allowed=[])
            return IdemResult(status=409, body=exc.to_body(None))
        return IdemResult(body=out)

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=approve
    )


@r.post("/admin/approvals/{approval_id}/approve")
async def approve(
    approval_id: uuid.UUID,
    body: NoteIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    return await _decide(approval_id, body, request, session, principal, True)


@r.post("/admin/approvals/{approval_id}/reject")
async def reject(
    approval_id: uuid.UUID,
    body: NoteIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    return await _decide(approval_id, body, request, session, principal, False)


@r.post("/admin/approvals/{approval_id}/cancel")
async def cancel(
    approval_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    out = await apr.cancel(session, principal, approval_id)
    if out.pop("_expired", False):  # ADM-23: the expired status commits; the caller gets a 409
        return problem_response(ProblemError("invalid_state_transition", current_state="expired", allowed=[]))
    return out


# --------------------------------------------------------------------------- privacy (PRV)


class PrivacyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_type: Literal[
        "access_export", "correction", "erasure", "grievance", "nomination", "consent_withdrawal_help"
    ]
    details: str | None = Field(default=None, max_length=4000)
    confirm: bool = False


class VerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["session", "otp", "guardian_otp", "manual"]


class CompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_summary: str = Field(min_length=3, max_length=2000)


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=2000)


async def _own_prv(session: Any, principal: Principal, request_id: uuid.UUID) -> PrivacyRequest:
    r_ = await prv.load(session, request_id, principal=principal, own=True)
    if r_ is None:
        raise ProblemError("not_found")
    return r_  # type: ignore[no-any-return,unused-ignore]


@me_r.get("/privacy-requests", openapi_extra=NEUTRAL)
async def my_privacy(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    rows = await prv.list_own(session, principal)
    return {"data": [prv.request_out(x) for x in rows]}


@me_r.post("/privacy-requests", status_code=201)
async def create_privacy(
    body: PrivacyIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    if body.request_type == "erasure":
        # Learner-facing: advertise the account's real step-up methods (a student without TOTP
        # confirms with an email/SMS code), not the staff-only ``["totp"]`` of ``p5``.
        from app.modules.identity.router import step_up_problem_for

        problem = await step_up_problem_for(session, principal, 900)
        if problem:
            raise problem
        if not body.confirm:
            raise ProblemError(
                "validation_failed",
                422,
                errors=[{"field": "confirm", "code": "required", "message": "Confirm the erasure request"}],
            )

    async def op() -> IdemResult:
        today = clock.now() - timedelta(days=1)
        n = await prv.count_own_since(session, principal, today)
        if n >= 3:
            raise ProblemError("rate_limited", headers={"Retry-After": "86400"})
        x = await prv.create(
            session,
            principal.user_id,
            body.request_type,
            body.details,
            request.headers.get("idempotency-key"),
            principal=principal,
        )
        await audit(
            session,
            principal,
            "privacy.request.created",
            "privacy_request",
            x.id,
            subject_user_id=principal.user_id,
            after={"type": x.request_type},
        )
        return IdemResult(status=201, body=prv.request_out(x))

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=True
    )


@me_r.get("/privacy-requests/{request_id}", openapi_extra=NEUTRAL)
async def my_privacy_request(
    request_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    return prv.request_out(await _own_prv(session, principal, request_id))


@me_r.post("/privacy-requests/{request_id}/withdraw")
async def withdraw_privacy(
    request_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    x = await _own_prv(session, principal, request_id)
    if x.status not in prv.OPEN_STATES:
        raise ProblemError("invalid_state_transition", current_state=x.status, allowed=list(prv.OPEN_STATES))
    x.status = "withdrawn"
    await prv.save(principal, x, own=True)
    await audit(
        session,
        principal,
        "privacy.request.withdrawn",
        "privacy_request",
        x.id,
        subject_user_id=principal.user_id,
    )
    return prv.request_out(x)


@me_r.get("/privacy-requests/{request_id}/export", openapi_extra=NEUTRAL)
async def my_export(
    request_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    x = await _own_prv(session, principal, request_id)
    if x.request_type != "access_export" or x.status != "completed" or x.export_payload is None:
        raise ProblemError("invalid_state_transition", current_state=x.status, allowed=["completed"])
    await audit(
        session, principal, "export.download", "privacy_request", x.id, subject_user_id=principal.user_id
    )
    return x.export_payload


@r.get("/admin/privacy-requests", openapi_extra=NEUTRAL)
async def privacy_queue(
    session: PrincipalDbSession, principal: Principal = perm("privacy.request.process")
) -> dict[str, Any]:
    rows = await prv.queue(session, principal)
    return {"data": [prv.request_out(x, staff=True) for x in rows]}


async def _prv(session: Any, request_id: uuid.UUID, principal: Principal | None = None) -> PrivacyRequest:
    x = await prv.load(session, request_id, principal=principal, own=False)
    if x is None:
        raise ProblemError("not_found")
    return x  # type: ignore[no-any-return,unused-ignore]


@r.get("/admin/privacy-requests/{request_id}", openapi_extra=NEUTRAL)
async def privacy_detail(
    request_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = perm("privacy.request.process")
) -> dict[str, Any]:
    x = await _prv(session, request_id, principal)
    await audit(
        session, principal, "privacy.request.viewed", "privacy_request", x.id, subject_user_id=x.user_id
    )
    return prv.request_out(x, staff=True)


@r.post("/admin/privacy-requests/{request_id}/verify-identity")
async def privacy_verify(
    request_id: uuid.UUID,
    body: VerifyIn,
    session: PrincipalDbSession,
    principal: Principal = perm("privacy.request.process"),
) -> dict[str, Any]:
    p5(principal)
    x = await _prv(session, request_id, principal)
    x.identity_verification_method = body.method
    x.identity_verified_at = clock.now()
    if x.status in ("received", "identity_verification"):
        x.status = "in_progress"
    await prv.save(principal, x)
    await audit(
        session,
        principal,
        "privacy.identity_verified",
        "privacy_request",
        x.id,
        subject_user_id=x.user_id,
        after={"method": body.method},
    )
    return prv.request_out(x, staff=True)


@r.post("/admin/privacy-requests/{request_id}/complete")
async def privacy_complete(
    request_id: uuid.UUID,
    body: CompleteIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("privacy.request.process"),
) -> JSONResponse:
    p5(principal)

    async def op() -> IdemResult:
        x = await _prv(session, request_id, principal)
        if x.status not in prv.OPEN_STATES:
            raise ProblemError(
                "invalid_state_transition", current_state=x.status, allowed=list(prv.OPEN_STATES)
            )
        if x.identity_verified_at is None:
            raise ProblemError("invalid_state_transition", current_state="identity_unverified", allowed=[])
        if x.request_type == "erasure":
            if x.cooling_off_until and x.cooling_off_until > clock.now():
                raise ProblemError("invalid_state_transition", current_state="cooling_off", allowed=[])
            if x.user_id:
                async with pg_system(session, "admin.privacy_erasure"):
                    res = await prv.execute_erasure(session, x.user_id, x.id)
                    await session.flush()
                if not res.complete:
                    # DB-01: never report an erasure as completed while modules still hold data.
                    x.status = "in_progress"
                    x.response_summary = (
                        "Erasure partly executed (sessions revoked, account deactivated; modules done: "
                        f"{', '.join(sorted(res.ran)) or 'none'}). Pending modules: {', '.join(res.missing)}."
                    )
                    await prv.save(principal, x)
                    await audit(
                        session,
                        principal,
                        "privacy.erasure.partial",
                        "privacy_request",
                        x.id,
                        subject_user_id=x.user_id,
                        after={"modules_done": sorted(res.ran), "modules_pending": res.missing},
                    )
                    return IdemResult(body=prv.request_out(x, staff=True))
        if x.request_type == "access_export" and x.user_id:
            async with pg_system(session, "admin.privacy_export"):
                payload = await prv.build_export(session, x.user_id)
            x.export_payload = payload
        x.status = "completed"
        x.completed_at = clock.now()
        x.response_summary = body.response_summary
        await prv.save(principal, x)
        await audit(
            session,
            principal,
            "privacy.request.completed",
            "privacy_request",
            x.id,
            subject_user_id=x.user_id,
            after={"type": x.request_type},
        )
        return IdemResult(body=prv.request_out(x, staff=True))

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=True
    )


@r.post("/admin/privacy-requests/{request_id}/reject")
async def privacy_reject(
    request_id: uuid.UUID,
    body: RejectIn,
    session: PrincipalDbSession,
    principal: Principal = perm("privacy.request.process"),
) -> dict[str, Any]:
    p5(principal)
    x = await _prv(session, request_id, principal)
    if x.status not in prv.OPEN_STATES:
        raise ProblemError("invalid_state_transition", current_state=x.status, allowed=list(prv.OPEN_STATES))
    x.status = "rejected"
    x.response_summary = body.reason
    x.completed_at = clock.now()
    await prv.save(principal, x)
    await audit(
        session,
        principal,
        "privacy.request.rejected",
        "privacy_request",
        x.id,
        subject_user_id=x.user_id,
        reason=body.reason,
    )
    return prv.request_out(x, staff=True)


@r.get("/admin/retention-policies", openapi_extra=NEUTRAL)
async def retention(session: PrincipalDbSession, principal: Principal = perm("audit.read")) -> dict[str, Any]:
    rows: Any
    if uses_firestore("admin"):
        from app.modules.admin.repo_firestore_privacy import privacy_repo

        rows = await privacy_repo(principal).retention_policies()
    else:
        rows = (await session.execute(select(RetentionPolicy).order_by(RetentionPolicy.table_name))).scalars()
    return {
        "data": [
            {
                "policy_id": str(x.id),
                "data_category": x.data_category,
                "table_name": x.table_name,
                "retention_class": x.retention_class,
                "retention_days": interval_days(x.retention_interval),
                "deletion_method": x.deletion_method,
                "job_name": x.job_name,
                "owner_module": x.owner_module,
            }
            for x in rows
        ]
    }


router = APIRouter()
router.include_router(r)
router.include_router(me_r)
router.include_router(accounts.r)

# ADM-016 courses overview (admin course cards + dashboard certificate tiles).
from app.modules.admin import courses_overview as _courses_overview  # noqa: E402

router.include_router(_courses_overview.r)
