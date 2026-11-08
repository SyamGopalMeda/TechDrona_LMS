"""Platform administration of accounts (ADM-01..05 + reactivation) and break-glass (ADM-17..19).

* ADM-01 dashboard: platform aggregates only (no per-user rows).
* ADM-02/03 user search and account view (no security evidence).
* ADM-04 deactivate / reactivate: mandatory reason, step-up P5, Idempotency-Key, every
  session revoked on deactivation, audited.
* ADM-05 MFA reset: dual control — the request is stored as ``approval_requests``
  (``user.mfa.reset``) and executed by a *different* Admin (ADM-14; owner decision D2: the
  security reviewer role was folded into Admin, dual control = two different admins).
* ADM-17..19 break-glass: **activation is retired** (single company, D2). It elevated to the
  removed ``security_reviewer`` role, and Admin already holds every permission that was
  break-glass only. The list / end / review routes and the expiry job stay so historic
  sessions can still be closed and reviewed by another Admin. Alerts go to every Admin.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from app.core.audit import AuditActor, audit
from app.core.auth import require_permission
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.outbox import emit_event
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339, within
from app.modules.admin import approvals as apr
from app.modules.admin.models import BreakGlassSession, PrivacyRequest
from app.modules.identity import clock
from app.modules.identity.contacts import mask_phone
from app.modules.identity.models import MfaFactor, User, UserProfile
from app.modules.rbac.catalogue import ADMIN_ROLE, admin_roles
from app.modules.rbac.models import ApprovalRequest, Role, RoleGrant

r = authenticated_router(tags=["admin"], route_tag="default", idle="extends")
NEUTRAL = {"x-td-idle": "neutral"}
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
# Synthetic, deactivated grantor of historic break-glass grants (admin_0002; ck_rg_self).
BREAK_GLASS_SYSTEM_USER_ID = uuid.UUID("00000000-0000-7000-8000-0000000bb6a5")
ALERT_ROLES = tuple(sorted(admin_roles()))


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


def _ts(v: datetime | None) -> str | None:
    return to_rfc3339(v) if v else None


def _vf(field: str, code: str, message: str) -> ProblemError:
    return ProblemError("validation_failed", 422, errors=[{"field": field, "code": code, "message": message}])


# --------------------------------------------------------------------------- ADM-01 dashboard


async def _count(session: Any, *where: Any, model: Any) -> int:
    return int((await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one())


_ACTIONABLE_CHECK_CAP = 500


async def _actionable_approvals(session: Any, principal: Principal, now: datetime) -> int:
    """ADM-22: count only pending requests this viewer could decide (not their own, and only
    action types whose approver role/permission they hold)."""
    by_type = (
        await session.execute(
            select(ApprovalRequest.action_type, func.count())
            .where(
                ApprovalRequest.status == "pending",
                ApprovalRequest.expires_at > now,
                ApprovalRequest.requested_by != principal.user_id,
            )
            .group_by(ApprovalRequest.action_type)
        )
    ).all()
    total = 0
    for action_type, n in by_type:
        if action_type in apr.NOT_VIA_ADMIN or not await apr.can_approve(session, principal, action_type):
            continue
        h = apr.handler_for(action_type)
        if h is None or h.check is None:
            total += int(n)
            continue
        # Per-request SoD checks (own role change, own MFA reset, own rule version...): the
        # checks are read-only, so run each one and count only the requests it lets through.
        reqs = (
            await session.execute(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.action_type == action_type,
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.expires_at > now,
                    ApprovalRequest.requested_by != principal.user_id,
                )
                .limit(_ACTIONABLE_CHECK_CAP)
            )
        ).scalars()
        for req in reqs:
            try:
                await h.check(session, principal, req)
            except ProblemError:
                continue
            total += 1
    return total


@r.get("/admin/dashboard", openapi_extra=NEUTRAL)
async def dashboard(
    session: PrincipalDbSession, principal: Principal = Depends(require_permission("analytics.read.platform"))
) -> dict[str, Any]:
    from app.modules.commerce.models import Order
    from app.modules.security.models import AccountRestriction, SecurityCase
    from app.modules.sessions.models import AuthSession
    from app.modules.support.models import SupportTicket
    from app.modules.support.service import OPEN_STATUSES

    now = clock.now()
    users = dict((await session.execute(select(User.status, func.count()).group_by(User.status))).all())
    minors = await _count(
        session, User.is_minor.is_(True), User.status != "deleted", User.is_synthetic.is_(False), model=User
    )
    new7 = await _count(session, User.created_at > now - timedelta(days=7), model=User)
    new30 = await _count(session, User.created_at > now - timedelta(days=30), model=User)
    open_t = await _count(session, SupportTicket.status.in_(OPEN_STATUSES), model=SupportTicket)
    breached = await _count(
        session,
        SupportTicket.status.in_(OPEN_STATUSES),
        or_(
            SupportTicket.resolution_due_at < now,
            (SupportTicket.first_responded_at.is_(None)) & (SupportTicket.first_response_due_at < now),
        ),
        model=SupportTicket,
    )
    unassigned = await _count(
        session,
        SupportTicket.status.in_(OPEN_STATUSES),
        SupportTicket.assigned_to.is_(None),
        model=SupportTicket,
    )
    levels = dict(
        (
            await session.execute(
                select(AccountRestriction.level, func.count(func.distinct(AccountRestriction.user_id)))
                .where(AccountRestriction.ended_at.is_(None))
                .group_by(AccountRestriction.level)
            )
        ).all()
    )
    paid = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Order.total_paise), 0)).where(
                Order.status == "paid", Order.paid_at > now - timedelta(days=30)
            )
        )
    ).one()
    from app.modules.admin.privacy import OPEN_STATES as PRV_OPEN

    return {
        "generated_at": to_rfc3339(now),
        "users": {
            "total": sum(v for k, v in users.items() if k != "deleted"),
            "active": users.get("active", 0),
            "pending_verification": users.get("pending_verification", 0)
            + users.get("pending_guardian_consent", 0),
            "deactivated": users.get("deactivated", 0),
            "minors": minors,
            "new_7d": new7,
            "new_30d": new30,
        },
        "sessions": {
            "active": await _count(
                session,
                AuthSession.status == "active",
                AuthSession.absolute_expires_at > now,
                model=AuthSession,
            )
        },
        "support": {"open": open_t, "breached": breached, "unassigned": unassigned},
        "security": {
            "restricted_by_level": {str(k): int(v) for k, v in sorted(levels.items())},
            "open_cases": await _count(
                session, SecurityCase.status.not_in(("decided", "closed")), model=SecurityCase
            ),
        },
        "approvals": {"pending": await _actionable_approvals(session, principal, now)},
        "privacy": {
            "open": await _count(session, PrivacyRequest.status.in_(PRV_OPEN), model=PrivacyRequest),
            "overdue": await _count(
                session,
                PrivacyRequest.status.in_(PRV_OPEN),
                PrivacyRequest.due_at <= now,
                model=PrivacyRequest,
            ),
        },
        "break_glass": {
            "active": await _count(session, BreakGlassSession.status == "active", model=BreakGlassSession)
        },
        "commerce": {"paid_orders_30d": int(paid[0]), "revenue_paise_30d": int(paid[1])},
    }


# --------------------------------------------------------------------------- ADM-02 / ADM-03


async def _roles_for(session: Any, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    if not user_ids:
        return {}
    now = clock.now()
    rows = (
        await session.execute(
            select(RoleGrant.user_id, Role.role_key)
            .join(Role, Role.id == RoleGrant.role_id)
            .where(
                RoleGrant.user_id.in_(user_ids),
                RoleGrant.revoked_at.is_(None),
                or_(RoleGrant.expires_at.is_(None), RoleGrant.expires_at > now),
            )
        )
    ).all()
    out: dict[uuid.UUID, set[str]] = {}
    for uid, role in rows:
        out.setdefault(uid, set()).add(role)
    return {k: sorted(v) for k, v in out.items()}


def _name(u: User, prof: UserProfile | None) -> str | None:
    if prof is None:
        return None
    return prof.display_name or prof.full_name


@r.get("/admin/users", openapi_extra=NEUTRAL)
async def search_users(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.read")),
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Literal["pending_verification", "pending_guardian_consent", "active", "deactivated", "deleted"]
    | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    qry = select(User, UserProfile).outerjoin(UserProfile, UserProfile.user_id == User.id)
    if status:
        qry = qry.where(User.status == status)
    term = (q or "").strip()
    if term:
        try:
            qry = qry.where(User.id == uuid.UUID(term))
        except ValueError:
            like = f"%{term.lower()}%"
            digits = "".join(c for c in term if c.isdigit())
            conds = [func.lower(User.email).like(like), func.lower(UserProfile.full_name).like(like)]
            if len(digits) >= 4:
                conds.append(User.phone_e164.like(f"%{digits}%"))
            qry = qry.where(or_(*conds))
    if cursor:
        try:
            after = uuid.UUID(str(decode_cursor(cursor)["id"]))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
        qry = qry.where(User.id < after)
    rows = (await session.execute(qry.order_by(User.id.desc()).limit(limit + 1))).all()
    more = len(rows) > limit
    rows = rows[:limit]
    roles = await _roles_for(session, [u.id for u, _ in rows])
    await audit(session, principal, "admin.user.searched", "user", None, after={"q_len": len(term)})
    return {
        "data": [
            {
                "user_id": str(u.id),
                "display_name": _name(u, p),
                "email": u.email,
                "phone_masked": mask_phone(u.phone_e164),
                "status": u.status,
                "is_minor": u.is_minor,
                "restriction_level": u.restriction_level,
                "roles": roles.get(u.id, []),
                "created_at": _ts(u.created_at),
                "last_login_at": _ts(u.last_login_at),
            }
            for u, p in rows
        ],
        "page": page_meta({"id": str(rows[-1][0].id)} if more and rows else None, limit),
    }


async def _user(session: Any, user_id: uuid.UUID) -> User:
    u = await session.get(User, user_id)
    if u is None:
        raise ProblemError("not_found")
    return u


@r.get("/admin/users/{user_id}", openapi_extra=NEUTRAL)
async def user_detail(
    user_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.read")),
) -> dict[str, Any]:
    from app.modules.sessions.models import AuthSession

    u = await _user(session, user_id)
    prof = await session.get(UserProfile, u.id)
    now = clock.now()
    grants = (
        await session.execute(
            select(RoleGrant, Role.role_key)
            .join(Role, Role.id == RoleGrant.role_id)
            .where(
                RoleGrant.user_id == u.id,
                RoleGrant.revoked_at.is_(None),
                or_(RoleGrant.expires_at.is_(None), RoleGrant.expires_at > now),
            )
        )
    ).all()
    factors = (
        (
            await session.execute(
                select(MfaFactor).where(MfaFactor.user_id == u.id, MfaFactor.revoked_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    pending = (
        (
            await session.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.target_id == u.id,
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.expires_at > now,
                )
            )
        )
        .scalars()
        .all()
    )
    bg = await _active_bg(session, u.id)
    await audit(session, principal, "admin.user.viewed", "user", u.id, subject_user_id=u.id)
    return {
        "user_id": str(u.id),
        "display_name": _name(u, prof),
        "email": u.email,
        "phone_masked": mask_phone(u.phone_e164),
        "status": u.status,
        "privacy_tier": u.privacy_tier,
        "is_minor": u.is_minor,
        "email_verified_at": _ts(u.email_verified_at),
        "phone_verified_at": _ts(u.phone_verified_at),
        "restriction_level": u.restriction_level,
        "account_origin": u.account_origin,
        "created_at": _ts(u.created_at),
        "last_login_at": _ts(u.last_login_at),
        "grants": [
            {
                "grant_id": str(g.id),
                "role": role,
                "scope_type": g.scope_type,
                "scope_id": str(g.scope_id) if g.scope_id else None,
                "expires_at": _ts(g.expires_at),
            }
            for g, role in grants
        ],
        "mfa": {
            "enrolled": any(f.factor_type != "recovery_codes" for f in factors),
            "factors": [
                {
                    "factor_type": f.factor_type,
                    "created_at": _ts(f.created_at),
                    "last_used_at": _ts(f.last_used_at),
                }
                for f in factors
            ],
        },
        "sessions": {
            "active": await _count(
                session,
                AuthSession.user_id == u.id,
                AuthSession.status == "active",
                AuthSession.absolute_expires_at > now,
                model=AuthSession,
            )
        },
        "pending_approvals": [apr.approval_out(a) for a in pending],
        "break_glass_active": bg is not None,
    }


# --------------------------------------------------------------------------- ADM-04 deactivate


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=1000)


@r.post("/admin/users/{user_id}/deactivate")
async def deactivate(
    user_id: uuid.UUID,
    body: ReasonIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.deactivate")),
) -> JSONResponse:
    p5(principal)

    async def op() -> IdemResult:
        from app.modules.sessions import service as ss

        if user_id == principal.user_id:
            raise ProblemError(
                "sod_violation", rule="self_action", detail="You cannot deactivate your own account."
            )
        u = await _user(session, user_id)
        if u.status in ("deactivated", "deleted"):
            raise ProblemError("invalid_state_transition", current_state=u.status, allowed=["active"])
        before = u.status
        u.status = "deactivated"
        await session.flush()
        n = await ss.revoke_all_sessions(session, u.id, "admin_kill", ended_by=principal.user_id)
        await audit(
            session,
            principal,
            "admin.user.deactivated",
            "user",
            u.id,
            subject_user_id=u.id,
            reason=body.reason,
            before={"status": before},
            after={"status": "deactivated", "sessions_revoked": n},
        )
        await emit_event(
            session,
            "identity.user_deactivated",
            {"user_id": str(u.id)},
            aggregate_type="user",
            aggregate_id=u.id,
        )
        return IdemResult(body={"user_id": str(u.id), "status": u.status, "sessions_revoked": n})

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@r.post("/admin/users/{user_id}/reactivate")
async def reactivate(
    user_id: uuid.UUID,
    body: ReasonIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.deactivate")),
) -> JSONResponse:
    p5(principal)

    async def op() -> IdemResult:
        u = await _user(session, user_id)
        if u.status != "deactivated" or u.deleted_at is not None:
            raise ProblemError("invalid_state_transition", current_state=u.status, allowed=["deactivated"])
        u.status = "active" if (u.email_verified_at or u.phone_verified_at) else "pending_verification"
        await session.flush()
        await audit(
            session,
            principal,
            "admin.user.reactivated",
            "user",
            u.id,
            subject_user_id=u.id,
            reason=body.reason,
            before={"status": "deactivated"},
            after={"status": u.status},
        )
        return IdemResult(body={"user_id": str(u.id), "status": u.status})

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


# --------------------------------------------------------------------------- ADM-05 MFA reset


class MfaResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=10, max_length=1000)
    verification_method: Literal["video_call", "document", "known_contact"]


@r.post("/admin/users/{user_id}/mfa-reset", status_code=202)
async def mfa_reset(
    user_id: uuid.UUID,
    body: MfaResetIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.mfa.reset")),
) -> JSONResponse:
    p5(principal)

    async def op() -> IdemResult:
        if user_id == principal.user_id:
            raise ProblemError("sod_violation", rule="self_action", detail="You cannot reset your own MFA.")
        u = await _user(session, user_id)
        active = await _count(
            session, MfaFactor.user_id == u.id, MfaFactor.revoked_at.is_(None), model=MfaFactor
        )
        if not active:
            raise ProblemError("invalid_state_transition", current_state="no_factors", allowed=[])
        dup = (
            await session.execute(
                select(ApprovalRequest.id).where(
                    ApprovalRequest.action_type == "user.mfa.reset",
                    ApprovalRequest.target_id == u.id,
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.expires_at > clock.now(),
                )
            )
        ).first()
        if dup:
            raise ProblemError("invalid_state_transition", current_state="approval_pending", allowed=[])
        req = await apr.new_request(
            session,
            principal,
            action_type="user.mfa.reset",
            target_type="user",
            target_id=u.id,
            payload={
                "user_id": str(u.id),
                "verification_method": body.verification_method,
                "reason": body.reason,
            },
            reason=body.reason,
            required_approver_role=ADMIN_ROLE,
        )
        return IdemResult(status=202, body=apr.pending_response(req))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


async def _check_mfa_reset(session: Any, principal: Principal, req: ApprovalRequest) -> None:
    if str(principal.user_id) == req.payload.get("user_id"):
        raise ProblemError("sod_violation", rule="SoD-05", detail="You cannot approve your own MFA reset.")


async def _execute_mfa_reset(session: Any, principal: Principal, req: ApprovalRequest) -> dict[str, Any]:
    from sqlalchemy import update

    from app.modules.notifications.service import send_email
    from app.modules.sessions import service as ss

    uid = uuid.UUID(req.payload["user_id"])
    u = await _user(session, uid)
    res = await session.execute(
        update(MfaFactor)
        .where(MfaFactor.user_id == uid, MfaFactor.revoked_at.is_(None))
        .values(revoked_at=clock.now())
        .execution_options(synchronize_session=False)
    )
    removed = int(getattr(res, "rowcount", 0) or 0)
    n = await ss.revoke_all_sessions(session, uid, "mfa_changed", ended_by=principal.user_id)
    await audit(
        session,
        principal,
        "admin.user.mfa_reset",
        "user",
        uid,
        subject_user_id=uid,
        reason=req.request_reason,
        after={
            "factors_removed": removed,
            "sessions_revoked": n,
            "verification_method": req.payload.get("verification_method"),
            "requested_by": str(req.requested_by),
        },
    )
    if u.email:
        await send_email(
            u.email,
            "Your Tech Drona sign-in factors were reset",
            "Your authenticator app and recovery codes were removed after an identity check by our team. "
            "Sign in and set up two-step verification again. If you didn't ask for this, contact support.",
            template_key="admin.mfa_reset",
        )
    return {"user_id": str(uid), "factors_removed": removed, "sessions_revoked": n}


apr.register(
    apr.ApprovalHandler(
        "user.mfa.reset",
        "user.mfa.reset",
        admin_roles(),
        _execute_mfa_reset,
        check=_check_mfa_reset,
    )
)


# --------------------------------------------------------------------------- ADM-17..19 break-glass


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=2000)


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=5, max_length=2000)


def add_business_days(start: datetime, days: int) -> datetime:
    d = start
    left = days
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def bg_out(b: BreakGlassSession) -> dict[str, Any]:
    now = clock.now()
    if b.status == "active":
        review = "not_due"
    elif b.reviewed_at is not None:
        review = "reviewed"
    elif b.review_due_at is not None and now > b.review_due_at:
        review = "overdue"
    else:
        review = "pending"
    return {
        "break_glass_id": str(b.id),
        "user_id": str(b.user_id),
        "reason": b.reason,
        "elevated_role": b.elevated_role,
        "status": b.status,
        "started_at": _ts(b.started_at),
        "expires_at": _ts(b.expires_at),
        "ended_at": _ts(b.ended_at),
        "end_reason": b.end_reason,
        "ended_by": str(b.ended_by) if b.ended_by else None,
        "review_status": review,
        "review_due_at": _ts(b.review_due_at),
        "reviewed_by": str(b.reviewed_by) if b.reviewed_by else None,
        "reviewed_at": _ts(b.reviewed_at),
        "review_note": b.review_note,
    }


async def _active_bg(session: Any, user_id: uuid.UUID) -> BreakGlassSession | None:
    return (
        await session.execute(
            select(BreakGlassSession).where(
                BreakGlassSession.user_id == user_id, BreakGlassSession.status == "active"
            )
        )
    ).scalar_one_or_none()


async def _alert(session: Any, b: BreakGlassSession, event: str, *, exclude: uuid.UUID | None) -> int:
    """In-app + security alert to every active Admin."""
    from app.modules.notifications.service import notify

    now = clock.now()
    recipients = (
        (
            await session.execute(
                select(RoleGrant.user_id)
                .join(Role, Role.id == RoleGrant.role_id)
                .where(
                    Role.role_key.in_(ALERT_ROLES),
                    RoleGrant.scope_type == "platform",
                    RoleGrant.revoked_at.is_(None),
                    or_(RoleGrant.expires_at.is_(None), RoleGrant.expires_at > now),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    sent = 0
    for uid in recipients:
        if uid == exclude:
            continue
        nid = await notify(
            session,
            uid,
            f"admin.break_glass_{event}",
            category="security",
            priority="critical" if event == "activated" else "high",
            data={"break_glass_id": str(b.id), "user_id": str(b.user_id), "expires_at": _ts(b.expires_at)},
            dedupe_key=f"bg:{b.id}:{event}",
        )
        sent += nid is not None
    await emit_event(
        session,
        f"admin.break_glass_{event}",
        {"break_glass_id": str(b.id), "user_id": str(b.user_id), "recipients": sent},
        aggregate_type="break_glass_session",
        aggregate_id=b.id,
    )
    return sent


async def _revoke_grant(session: Any, b: BreakGlassSession, by: uuid.UUID | None) -> None:
    if b.role_grant_id is None:
        return
    g = await session.get(RoleGrant, b.role_grant_id)
    if g is not None and g.revoked_at is None:
        g.revoked_at = clock.now()
        g.revoked_by = by


@r.get("/admin/break-glass", openapi_extra=NEUTRAL)
async def break_glass_list(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("breakglass.activate")),
    status: Literal["active", "ended", "expired"] | None = None,
) -> dict[str, Any]:
    q = select(BreakGlassSession)
    if status:
        q = q.where(BreakGlassSession.status == status)
    rows = (await session.execute(q.order_by(BreakGlassSession.started_at.desc()).limit(200))).scalars().all()
    mine = await _active_bg(session, principal.user_id)
    return {"data": [bg_out(b) for b in rows], "active": bg_out(mine) if mine else None}


async def _bg(session: Any, bid: uuid.UUID) -> BreakGlassSession:
    b = (
        await session.execute(select(BreakGlassSession).where(BreakGlassSession.id == bid).with_for_update())
    ).scalar_one_or_none()
    if b is None:
        raise ProblemError("not_found")
    return b


@r.post("/admin/break-glass/{session_id}/end")
async def break_glass_end(
    session_id: uuid.UUID,
    body: NoteIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("breakglass.activate")),
) -> JSONResponse:
    async def op() -> IdemResult:
        b = await _bg(session, session_id)
        if b.status != "active":
            raise ProblemError("invalid_state_transition", current_state=b.status, allowed=["active"])
        b.status = "ended"
        b.ended_at = clock.now()
        b.end_reason = "ended_early"
        b.ended_by = principal.user_id
        await _revoke_grant(session, b, principal.user_id)
        await session.flush()
        await audit(
            session,
            principal,
            "admin.break_glass.ended",
            "break_glass_session",
            b.id,
            subject_user_id=b.user_id,
            reason=body.note,
        )
        await _alert(session, b, "ended", exclude=principal.user_id)
        return IdemResult(body=bg_out(b))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@r.post("/admin/break-glass/{session_id}/review")
async def break_glass_review(
    session_id: uuid.UUID,
    body: ReviewIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("breakglass.activate")),
) -> JSONResponse:
    async def op() -> IdemResult:
        b = await _bg(session, session_id)
        if b.user_id == principal.user_id:
            raise ProblemError("sod_violation", rule="SoD-05", detail="Another super admin must review this.")
        if b.status == "active" or b.reviewed_at is not None:
            raise ProblemError(
                "invalid_state_transition",
                current_state="active" if b.status == "active" else "reviewed",
                allowed=["ended", "expired"],
            )
        b.reviewed_by = principal.user_id
        b.reviewed_at = clock.now()
        b.review_note = body.note
        await session.flush()
        await audit(
            session,
            principal,
            "admin.break_glass.reviewed",
            "break_glass_session",
            b.id,
            subject_user_id=b.user_id,
            reason=body.note,
        )
        return IdemResult(body=bg_out(b))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


async def expire_break_glass(session: Any) -> int:
    """System job: end every elevation past ``expires_at`` and revoke its grant."""
    rows = (
        (
            await session.execute(
                select(BreakGlassSession)
                .where(BreakGlassSession.status == "active", BreakGlassSession.expires_at <= clock.now())
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for b in rows:
        b.status = "expired"
        b.ended_at = b.expires_at
        b.end_reason = "expired"
        await _revoke_grant(session, b, None)
        await session.flush()
        await audit(
            session,
            AuditActor.system("admin.break_glass_expiry"),
            "admin.break_glass.expired",
            "break_glass_session",
            b.id,
            subject_user_id=b.user_id,
        )
        await _alert(session, b, "expired", exclude=None)
    return len(rows)
