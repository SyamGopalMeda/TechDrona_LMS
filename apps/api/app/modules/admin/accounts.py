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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from app.core.firestore.backend import uses_firestore
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339, within
from app.modules.admin import approvals as apr
from app.modules.admin.fs_rows import emit_any, idem_session
from app.modules.admin.models import BreakGlassSession, PrivacyRequest
from app.modules.identity import clock
from app.modules.identity import public as ipub
from app.modules.identity.contacts import mask_phone
from app.modules.identity.fs_journal import capture, request_journal
from app.modules.identity.public import User, UserProfile
from app.modules.rbac.catalogue import ADMIN_ROLE, admin_roles
from app.modules.rbac.public import ApprovalRequest, Role, RoleGrant

r = authenticated_router(tags=["admin"], route_tag="default", idle="extends")
NEUTRAL = {"x-td-idle": "neutral"}
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
# Synthetic, deactivated grantor of historic break-glass grants (admin_0002; ck_rg_self).
BREAK_GLASS_SYSTEM_USER_ID = uuid.UUID("00000000-0000-7000-8000-0000000bb6a5")
ALERT_ROLES = tuple(sorted(admin_roles()))


def p5(principal: Principal, seconds: int = 300) -> None:
    from app.core.config import get_settings

    if get_settings().simple_auth:  # TD_SIMPLE_AUTH: no re-confirm prompts
        return
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


async def _count_pg(session: Any, *where: Any, model: Any) -> int:
    return int((await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one())


_ACTIONABLE_CHECK_CAP = 500


@asynccontextmanager
async def _read_session(session: Any, job: str) -> AsyncIterator[Any]:
    """The request session, or on a stack without Postgres a read-only in-memory transaction of
    the SQL-engine modules (commerce) in platform scope (discarded afterwards)."""
    if session:
        yield session
        return
    from app.core.db import set_rls_context
    from app.core.firestore.sqlstore import MemoryTx

    tx = MemoryTx()
    await set_rls_context(tx, is_platform=True, actor=f"system:{job}")  # type: ignore[arg-type]  # MemoryTx emulates the RLS GUCs
    try:
        yield tx
    finally:
        await tx.rollback()


async def _actionable_approvals(session: Any, principal: Principal, now: datetime) -> int:
    """ADM-22: count only pending requests this viewer could decide (not their own, and only
    action types whose approver role/permission they hold). Store-neutral (rbac.public)."""
    from app.modules.rbac import public as rbac_public

    pending = [
        r
        for r in await rbac_public.find_approvals(session, status="pending", expires_after=now)
        if r.requested_by != principal.user_id
    ]
    by_type: dict[str, list[ApprovalRequest]] = {}
    for req in pending:
        by_type.setdefault(req.action_type, []).append(req)
    total = 0
    for action_type, reqs in by_type.items():
        if action_type in apr.NOT_VIA_ADMIN or not await apr.can_approve(session, principal, action_type):
            continue
        h = apr.handler_for(action_type)
        if h is None or h.check is None:
            total += len(reqs)
            continue
        # Per-request SoD checks (own role change, own MFA reset, own rule version...): the
        # checks are read-only, so run each one and count only the requests it lets through.
        for req in reqs[:_ACTIONABLE_CHECK_CAP]:
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
    from app.modules.catalog import public as catalog_public
    from app.modules.commerce import public as commerce_public
    from app.modules.orgs import public as orgs_public
    from app.modules.rbac import public as rbac_public
    from app.modules.security import public as security_public
    from app.modules.sessions import public as sessions_public
    from app.modules.support.service import dashboard_counts as support_dashboard_counts

    # Store-neutral: every count comes from the owning module's public API (each runs the same
    # query on Postgres, or its Firestore repository).
    now = clock.now()
    users = await ipub.status_counts(session)
    minors = len(await ipub.list_users(session, is_minor=True, exclude_status="deleted", is_synthetic=False))
    # erased (status "deleted") and synthetic accounts are not "new registrations"
    new7 = len(
        await ipub.list_users(
            session, created_after=now - timedelta(days=7), exclude_status="deleted", is_synthetic=False
        )
    )
    new30 = len(
        await ipub.list_users(
            session, created_after=now - timedelta(days=30), exclude_status="deleted", is_synthetic=False
        )
    )
    support = await support_dashboard_counts(session, now)
    levels = await security_public.restricted_users_by_level(session)
    async with _read_session(session, "admin.dashboard") as rs_:
        paid = await commerce_public.paid_orders_since(rs_, now - timedelta(days=30))
    from app.modules.admin.privacy import OPEN_STATES as PRV_OPEN

    courses = await catalog_public.course_status_counts(session)
    batches = await orgs_public.batch_status_counts(session)
    staff_ids = await rbac_public.staff_user_ids(session)
    learners = len(await ipub.list_users(session, status="active", is_synthetic=False, exclude_ids=staff_ids))
    # "Signed in now": like the other headline counts, synthetic accounts (QA / demo, live audit
    # 2026-11-14 #9) are left out.
    synthetic = {u.id for u in await ipub.list_users(session, is_synthetic=True)}
    active_sessions = sum(
        1 for s in await sessions_public.list_sessions(session, active_at=now) if s.user_id not in synthetic
    )

    return {
        "generated_at": to_rfc3339(now),
        # ADM-01 learning tiles: active learner accounts (no staff role), courses and batches by state.
        "learning": {
            "learners": learners,
            "courses_published": int(courses.get("published", 0)),
            "courses_draft": int(courses.get("draft", 0)),
            "batches_active": int(batches.get("active", 0)),
            "batches_planned": int(batches.get("planned", 0)),
        },
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
        "sessions": {"active": active_sessions},
        "support": support,
        "security": {
            "restricted_by_level": {str(k): int(v) for k, v in sorted(levels.items())},
            "open_cases": await security_public.open_case_count(session),
        },
        "approvals": {"pending": await _actionable_approvals(session, principal, now)},
        "privacy": dict(zip(("open", "overdue"), await _privacy_counts(session, PRV_OPEN, now), strict=True)),
        "break_glass": {"active": await _bg_active_count(session)},
        "commerce": {"paid_orders_30d": int(paid[0]), "revenue_paise_30d": int(paid[1])},
    }


# --------------------------------------------------------------------------- ADM-02 / ADM-03


async def _roles_for(session: Any, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    if not user_ids:
        return {}
    from app.modules.rbac import public as rbac_public

    out: dict[uuid.UUID, set[str]] = {}
    for g, role in await rbac_public.live_grants(session, user_ids=user_ids, now=clock.now()):
        out.setdefault(g.user_id, set()).add(role)
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
    status: Literal[
        "pending_verification", "pending_guardian_consent", "active", "deactivated", "deleted", "current"
    ]
    | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    term = (q or "").strip()
    after: uuid.UUID | None = None
    if cursor:
        try:
            after = uuid.UUID(str(decode_cursor(cursor)["id"]))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
    # "current": everyone except erased accounts (the admin list's default view)
    rows = await ipub.search_users(
        session,
        term=term,
        status=None if status == "current" else status,
        include_deleted=status != "current",
        after=after,
        limit=limit,
    )
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
    u = await ipub.get_user(session, user_id)
    if u is None:
        raise ProblemError("not_found")
    return u


async def _set_user(session: Any, u: User, **changes: Any) -> None:
    """Change columns of ``u`` on either store (Postgres: the tracked row is flushed)."""
    for k, v in changes.items():
        setattr(u, k, v)
    if ipub._fs():
        await ipub.update_user(session, u.id, **changes)
    else:
        await session.flush()


def _journal_outbox(session: Any, event_id: Any) -> None:
    """A Firestore outbox row written by ``emit_any`` (its own transaction) is removed again if
    the request fails (request journal); Postgres rows roll back with the transaction."""
    if not session and event_id is not None:
        from app.modules.identity.fs_journal import current as _journal

        if (j := _journal()) is not None:
            j.record("outbox_events", str(event_id), None)


# Firestore: every Firestore write of these routes is one undo scope (identity.fs_journal), so a
# failure after some writes (sessions ended, audit, ...) leaves none behind -- the single Postgres
# transaction's all-or-nothing. Audit rows are buffered to the request commit point (core.audit).
_JOURNAL = [Depends(request_journal, scope="function")]


@r.get("/admin/users/{user_id}", openapi_extra=NEUTRAL)
async def user_detail(
    user_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.read")),
) -> dict[str, Any]:
    from app.modules.rbac import public as rbac_public
    from app.modules.sessions import public as sessions_public

    u = await _user(session, user_id)
    prof = await ipub.get_profile(session, u.id)
    now = clock.now()
    grants = await rbac_public.live_grants(session, user_ids=[u.id], now=now)
    factors = await ipub.active_factors(session, u.id)
    pending = await rbac_public.find_approvals(session, target_id=u.id, status="pending", expires_after=now)
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
            "active": len(await sessions_public.list_sessions(session, user_id=u.id, active_at=now))
        },
        "pending_approvals": [apr.approval_out(a) for a in pending],
        "break_glass_active": bg is not None,
    }


# --------------------------------------------------------------------------- ADM-04 deactivate


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=1000)


class CreateUserIn(BaseModel):
    """ADM-06 staff-created account. The admin sets a starting password and tells the person;
    an optional role is granted in the same step (Admin roles go to dual control as usual)."""

    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    mobile: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=1, max_length=128)  # policy: password_problems below
    role_key: str | None = Field(default=None, max_length=40)
    scope_type: str = Field(default="platform", pattern="^(platform|batch|course)$")
    scope_id: uuid.UUID | None = None
    reason: str = Field(min_length=5, max_length=500)
    confirm_adult: bool = False
    # "Must change password on first login": the person signs in with the assigned password and
    # must choose a new one before anything else works (403 password_change_required).
    must_change_password: bool = False


def _field_problem(field: str, code: str, message: str) -> ProblemError:
    return ProblemError("validation_failed", 422, errors=[{"field": field, "code": code, "message": message}])


@r.post("/admin/users", status_code=201, dependencies=_JOURNAL)
async def create_user(
    body: CreateUserIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.invite")),
) -> JSONResponse:
    from app.core.auth import PLATFORM_SCOPE
    from app.core.config import get_settings
    from app.modules.identity import service as ids
    from app.modules.identity.contacts import normalize_email, normalize_phone
    from app.modules.identity.passwords import password_problems
    from app.modules.rbac import service as rs
    from app.modules.rbac.catalogue import ROLES

    p5(principal)
    if not body.confirm_adult:
        raise _field_problem(
            "confirm_adult",
            "adult_required",
            "Confirm the person is 18 or older (under-18s sign up themselves)",
        )
    email = normalize_email(body.email)
    if not email:
        raise _field_problem("email", "invalid_email", "Enter a valid email address")
    phone = None
    if body.mobile and body.mobile.strip():
        phone = normalize_phone(body.mobile)
        if not phone:
            raise _field_problem("mobile", "invalid_mobile", "Enter a valid mobile number")
    probs = password_problems(body.password, context=(email.split("@")[0],))
    if probs:
        raise _field_problem("password", probs[0], "Choose a longer or less common password")
    role_key = (body.role_key or "").strip() or None
    if role_key is not None:
        if role_key not in ROLES:
            raise _field_problem("role_key", "unknown_role", "Unknown role")
        if not await rs.check_permission(session, principal, "rbac.grant.manage", PLATFORM_SCOPE):
            raise ProblemError("permission_denied", permission="rbac.grant.manage")
        if body.scope_type != "platform" and body.scope_id is None:
            raise _field_problem("scope_id", "scope_required", "Choose where this role applies")

    async def op() -> IdemResult:
        if await ids.find_user(session, "email", email) is not None:
            raise _field_problem("email", "already_registered", "An account with this email already exists")
        if phone and await ids.find_user(session, "phone", phone) is not None:
            raise _field_problem(
                "mobile", "already_registered", "An account with this mobile number already exists"
            )
        now = clock.now()
        uid = uuid7()
        user = User(
            id=uid,
            email=email,
            email_verified_at=now,
            phone_e164=phone,
            status="active",
            is_minor=False,
            # The admin confirms the person is 18+ (form checkbox); recorded like a roster import.
            age_verified_at=now,
            age_verification_method="roster",
            account_origin="staff_created",
        )
        await ipub.create_user(session, user, UserProfile(user_id=uid, full_name=body.full_name.strip()))
        if ipub._fs():
            user.status = "active"
        await ids.set_password(session, uid, body.password, must_change_password=body.must_change_password)
        await audit(
            session,
            principal,
            "admin.user.created",
            "user",
            uid,
            subject_user_id=uid,
            reason=body.reason,
            after={
                "status": "active",
                "account_origin": "staff_created",
                "has_mobile": phone is not None,
                "must_change_password": body.must_change_password,
            },
        )
        ev = await emit_any(
            session,
            "identity.user_registered",
            {"user_id": str(uid), "is_minor": False},
            aggregate_type="user",
            aggregate_id=uid,
        )
        _journal_outbox(session, ev)
        role_out: dict[str, Any] | None = None
        if role_key is not None:
            scope_id = None if body.scope_type == "platform" else body.scope_id
            from app.modules.rbac import public as rbac_public

            role = await rbac_public.role_by_key(session, role_key)
            assert role is not None  # role_key was checked against the catalogue
            org_id = await rs.resolve_grant_scope(session, role, body.scope_type, scope_id)
            # TD_SIMPLE_AUTH: an Admin's grant of any role applies at once (no dual control).
            if rs.is_dual_role(role_key) and not get_settings().simple_auth:
                req = await rs.create_approval_request(
                    session,
                    principal,
                    action_type="rbac.grant.privileged",
                    target_type="user",
                    target_id=uid,
                    payload={
                        "user_id": str(uid),
                        "role_key": role_key,
                        "scope_type": body.scope_type,
                        "scope_id": str(scope_id) if scope_id else None,
                        "expires_at": None,
                        "reason": body.reason,
                    },
                    reason=body.reason,
                    required_approver_role="super_admin",
                    organization_id=org_id,
                )
                role_out = {
                    "role_key": role_key,
                    "status": "approval_pending",
                    "approval_request_id": str(req.id),
                }
            else:
                gid = await rs.create_grant(
                    session,
                    principal,
                    user_id=uid,
                    role_key=role_key,
                    scope_type=body.scope_type,
                    scope_id=scope_id,
                    expires_at=None,
                    reason=body.reason,
                    granted_by=principal.user_id,
                )
                role_out = {"role_key": role_key, "status": "granted", "grant_id": str(gid)}
        return IdemResult(
            status=201,
            resource_id=uid,
            body={
                "user_id": str(uid),
                "status": user.status,
                "role": role_out,
                "must_change_password": body.must_change_password,
            },
        )

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=True
    )


@r.post("/admin/users/{user_id}/deactivate", dependencies=_JOURNAL)
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
        await _set_user(session, u, status="deactivated")
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
        ev = await emit_any(
            session,
            "identity.user_deactivated",
            {"user_id": str(u.id)},
            aggregate_type="user",
            aggregate_id=u.id,
        )
        _journal_outbox(session, ev)
        return IdemResult(body={"user_id": str(u.id), "status": u.status, "sessions_revoked": n})

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=True
    )


class SetPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=5, max_length=1000)
    # The person must choose a new password right after signing in with this one.
    must_change_password: bool = False


@r.post("/admin/users/{user_id}/password", dependencies=_JOURNAL)
async def set_user_password(
    user_id: uuid.UUID,
    body: SetPasswordIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.invite")),
) -> JSONResponse:
    """Admin sets a new password for someone (owner request 2026-11-12: while email is not
    integrated a reset link can never arrive, so this is the only way back in). Step-up, reason
    and audit required; the person's sessions end so the new password is needed everywhere."""
    p5(principal)

    async def op() -> IdemResult:
        from app.modules.identity import service as ids
        from app.modules.identity.passwords import password_problems
        from app.modules.sessions import service as ss

        if user_id == principal.user_id:
            raise ProblemError(
                "sod_violation",
                rule="self_action",
                detail="Change your own password in your security settings.",
            )
        u = await _user(session, user_id)
        if u.status in ("deactivated", "deleted"):
            raise ProblemError("invalid_state_transition", current_state=u.status, allowed=["active"])
        # Security audit 2026-11-12: one Admin (or a stolen Admin session) must not be able to take
        # over another Admin by setting their password. Admins change their own password; a locked-out
        # Admin is recovered through the dual-control MFA reset.
        from app.modules.rbac.catalogue import ADMIN_ROLE
        from app.modules.rbac.service import active_grants

        if any(g.role == ADMIN_ROLE for g in await active_grants(session, u.id)):
            raise ProblemError(
                "permission_denied",
                detail="Another Admin's password can't be set here. "
                "They change it in their own security settings.",
            )
        probs = password_problems(body.password, context=((u.email or "").split("@")[0],))
        if probs:
            raise _field_problem("password", probs[0], "Choose a longer or less common password")
        await ids.set_password(session, u.id, body.password, must_change_password=body.must_change_password)
        n = await ss.revoke_all_sessions(session, u.id, "admin_kill", ended_by=principal.user_id)
        await audit(
            session,
            principal,
            "admin.user.password_set",
            "user",
            u.id,
            subject_user_id=u.id,
            reason=body.reason,
            after={"sessions_revoked": n, "must_change_password": body.must_change_password},
        )
        return IdemResult(
            body={
                "user_id": str(u.id),
                "password_set": True,
                "sessions_revoked": n,
                "must_change_password": body.must_change_password,
            }
        )

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=True
    )


@r.post("/admin/users/{user_id}/reactivate", dependencies=_JOURNAL)
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
        await _set_user(
            session,
            u,
            status="active" if (u.email_verified_at or u.phone_verified_at) else "pending_verification",
        )
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

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=True
    )


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
        from app.modules.rbac import public as rbac_public

        if not await ipub.active_factors(session, u.id):
            raise ProblemError("invalid_state_transition", current_state="no_factors", allowed=[])
        dup = await rbac_public.find_approvals(
            session, action_type="user.mfa.reset", target_id=u.id, status="pending", expires_after=clock.now()
        )
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

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=True
    )


async def _check_mfa_reset(session: Any, principal: Principal, req: ApprovalRequest) -> None:
    if str(principal.user_id) == req.payload.get("user_id"):
        raise ProblemError("sod_violation", rule="SoD-05", detail="You cannot approve your own MFA reset.")


async def _execute_mfa_reset(session: Any, principal: Principal, req: ApprovalRequest) -> dict[str, Any]:
    from app.modules.notifications.service import send_email
    from app.modules.sessions import service as ss

    uid = uuid.UUID(req.payload["user_id"])
    u = await _user(session, uid)
    # Runs inside the approval's decision scope (rbac.public.decision): on Firestore the factor and
    # session writes are journaled and undone if anything after them fails.
    removed = await ipub.revoke_factors(session, uid)
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


async def _privacy_counts(session: Any, open_states: Any, now: datetime) -> tuple[int, int]:
    if uses_firestore("admin"):
        from app.modules.admin.privacy import open_counts

        return await open_counts(session, now)
    return (
        await _count_pg(session, PrivacyRequest.status.in_(open_states), model=PrivacyRequest),
        await _count_pg(
            session,
            PrivacyRequest.status.in_(open_states),
            PrivacyRequest.due_at <= now,
            model=PrivacyRequest,
        ),
    )


async def _bg_active_count(session: Any) -> int:
    if uses_firestore("admin"):
        return await _bg_repo().count_active()
    return await _count_pg(session, BreakGlassSession.status == "active", model=BreakGlassSession)


def _bg_repo() -> Any:
    """Firestore break-glass store. A named job: every caller already passed the route's
    permission check (``breakglass.activate``, or the user-detail permission for the badge)."""
    from app.modules.admin.repo_firestore_privacy import break_glass_repo

    return break_glass_repo(None)


async def _bg_save(b: Any, session: Any) -> None:
    if uses_firestore("admin"):
        from app.modules.admin.store_specs import BREAK_GLASS

        await capture(BREAK_GLASS, str(b.id))  # restored by the request journal on failure
        await _bg_repo().save(b)
    if session:
        await session.flush()  # Postgres row, or the caller's own Postgres writes (grants)


async def _active_bg(session: Any, user_id: uuid.UUID) -> BreakGlassSession | None:
    if uses_firestore("admin"):
        return await _bg_repo().active_for(user_id)  # type: ignore[no-any-return,unused-ignore]
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
    recipients: Any
    if uses_firestore("rbac"):
        from app.modules.rbac import public as rbac_public

        recipients = sorted(await rbac_public.user_ids_with_role(session, ALERT_ROLES, scope_type="platform"))
    else:
        recipients = await _alert_recipients_pg(session, now)
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
    await emit_any(
        session,
        f"admin.break_glass_{event}",
        {"break_glass_id": str(b.id), "user_id": str(b.user_id), "recipients": sent},
        aggregate_type="break_glass_session",
        aggregate_id=b.id,
    )
    return sent


async def _alert_recipients_pg(session: Any, now: datetime) -> Any:
    return (
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


async def _revoke_grant(session: Any, b: BreakGlassSession, by: uuid.UUID | None) -> None:
    if b.role_grant_id is None:
        return
    if uses_firestore("rbac"):
        # rbac on Firestore: through its public API (data-access). The service revoke also audits
        # and rotates the grantee's sessions; the expiry job revokes in the holder's name.
        from app.modules.rbac import public as rbac_public

        g_fs = await rbac_public.get_grant(session, b.role_grant_id)
        if g_fs is not None and g_fs.revoked_at is None:
            await rbac_public.revoke_grant(
                session,
                AuditActor.system("admin.break_glass") if by is None else AuditActor("user", user_id=by),
                b.role_grant_id,
                by or b.user_id,
                "break_glass_ended",
            )
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
    rows: Any
    if uses_firestore("admin"):
        rows = await _bg_repo().list_sessions(status, 200)
    else:
        q = select(BreakGlassSession)
        if status:
            q = q.where(BreakGlassSession.status == status)
        rows = (
            (await session.execute(q.order_by(BreakGlassSession.started_at.desc()).limit(200)))
            .scalars()
            .all()
        )
    mine = await _active_bg(session, principal.user_id)
    return {"data": [bg_out(b) for b in rows], "active": bg_out(mine) if mine else None}


async def _bg(session: Any, bid: uuid.UUID) -> BreakGlassSession:
    if uses_firestore("admin"):
        fb = await _bg_repo().get(bid)
        if fb is None:
            raise ProblemError("not_found")
        return fb  # type: ignore[no-any-return,unused-ignore]
    b = (
        await session.execute(select(BreakGlassSession).where(BreakGlassSession.id == bid).with_for_update())
    ).scalar_one_or_none()
    if b is None:
        raise ProblemError("not_found")
    return b


@r.post("/admin/break-glass/{session_id}/end", dependencies=_JOURNAL)
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
        await _bg_save(b, session)
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

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=False
    )


@r.post("/admin/break-glass/{session_id}/review", dependencies=_JOURNAL)
async def break_glass_review(
    session_id: uuid.UUID,
    body: ReviewIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("breakglass.activate")),
) -> JSONResponse:
    async def op() -> IdemResult:
        b = await _bg(session, session_id)
        from app.modules.rbac.service import is_sole_admin

        if b.user_id == principal.user_id and not await is_sole_admin(session, principal.user_id):
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
        await _bg_save(b, session)
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

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=False
    )


async def expire_break_glass(session: Any) -> int:
    """System job: end every elevation past ``expires_at`` and revoke its grant."""
    rows: Any
    if uses_firestore("admin"):
        from app.modules.admin.repo_firestore_privacy import break_glass_repo

        rows = await break_glass_repo(None, "admin.break_glass_expiry").due_for_expiry(clock.now())
    else:
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
        if uses_firestore("admin"):
            # One elevation = one unit, as the Postgres job's transaction: its grant revoke,
            # session rotation, row update and audit row are undone together if any step fails.
            await _expire_one_fs(session, b)
            continue
        await _expire_one(session, b)
    return len(rows)


async def _expire_one(session: Any, b: Any) -> None:
    b.status = "expired"
    b.ended_at = b.expires_at
    b.end_reason = "expired"
    await _revoke_grant(session, b, None)
    await _bg_save(b, session)
    await audit(
        session,
        AuditActor.system("admin.break_glass_expiry"),
        "admin.break_glass.expired",
        "break_glass_session",
        b.id,
        subject_user_id=b.user_id,
    )
    await _alert(session, b, "expired", exclude=None)


async def _expire_one_fs(session: Any, b: Any) -> None:
    from app.core import audit as core_audit
    from app.modules.identity.fs_journal import journal

    tokens = core_audit.begin_buffer()
    try:
        async with journal():
            await _expire_one(session, b)
        await core_audit.flush_pending()
    except Exception:
        core_audit.drop_pending()
        raise
    finally:
        core_audit.end_buffer(tokens)
