"""Sessions & devices API (api-specification §5: SES-01..12) and SessionResolver registration.

Lab-device enrolment (SES-13..16) is Planned (needs the org settings UI + enrolment links).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select

from app.core.audit import audit
from app.core.auth import register_session_resolver, require_active_principal, require_permission
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339
from app.modules.identity import clock
from app.modules.identity.models import User
from app.modules.identity.policy import get_policy
from app.modules.sessions import service as ss
from app.modules.sessions.models import AuthSession, Device, LoginAttempt, UserDevice
from app.modules.sessions.resolver import SessionsResolver
from app.modules.sessions.ua import mask_ip

register_session_resolver(SessionsResolver())

me_r = authenticated_router(prefix="/me", tags=["sessions"], route_tag="account_status", idle="extends")
admin_r = authenticated_router(prefix="/users", tags=["sessions"], route_tag="default", idle="extends")

REASON_CODES = ("ticket", "unblock_request", "case", "incident", "user_request", "legal")


class RenameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_label: str = Field(min_length=1, max_length=60)


class AdminRevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: uuid.UUID | None = None
    all: bool = False
    reason_code: str
    reason: str = Field(min_length=3, max_length=500)


class DeviceResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: str
    reason: str = Field(min_length=3, max_length=500)
    ticket_id: uuid.UUID | None = None


def _session_out(
    s: AuthSession, current: uuid.UUID | None, label: str | None, *, full_ip: bool
) -> dict[str, Any]:
    ended = s.ended_at
    return {
        "session_id": str(s.id),
        "is_current": s.id == current,
        "status": s.status,
        "device_label": label or f"{s.ua_family} on {s.os_family}",
        "device_class": s.device_class,
        "approx_region": s.geo_region,
        "ip": (s.ip_last if full_ip else mask_ip(s.ip_last)) if s.ip_last else None,
        "auth_method": "+".join(s.amr),
        "tier": s.session_tier,
        "login_at": to_rfc3339(s.created_at),
        "last_active_at": to_rfc3339(s.last_seen_at),
        "logout_at": to_rfc3339(ended) if ended else None,
        "duration_seconds": int((ended - s.created_at).total_seconds()) if ended else None,
        "end_reason": s.end_reason,
    }


async def _labels(session: Any, device_ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str | None]:
    ids_ = [d for d in device_ids if d]
    if not ids_:
        return {}
    rows = (await session.execute(select(Device.id, Device.label_hint).where(Device.id.in_(ids_)))).all()
    return {r[0]: r[1] for r in rows}


async def _list_sessions(
    session: Any, user_id: uuid.UUID, current: uuid.UUID | None, *, owner: bool
) -> list[dict[str, Any]]:
    since = clock.now() - timedelta(days=90)
    rows = list(
        (
            await session.execute(
                select(AuthSession)
                .where(
                    AuthSession.user_id == user_id,
                    or_(
                        AuthSession.status.in_(("active", *ss.PENDING_STATUSES)),
                        AuthSession.ended_at >= since,
                    ),
                )
                .order_by(AuthSession.created_at.desc())
                .limit(100)
            )
        ).scalars()
    )
    labels = await _labels(session, {s.device_id for s in rows})
    recent = clock.now() - timedelta(days=7)
    return [
        _session_out(
            s,
            current,
            labels.get(s.device_id) if s.device_id else None,
            full_ip=owner and (s.id == current or s.created_at >= recent),
        )
        for s in rows
    ]


# --------------------------------------------------------------------------- SES-01..08 (self)


@me_r.get("/sessions", openapi_extra={"x-td-idle": "neutral"})
async def my_sessions(
    request: Request, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    data = await _list_sessions(session, principal.user_id, principal.session_id, owner=True)
    return {"data": data, "page": {"next_cursor": None, "has_more": False, "limit": len(data)}}


@me_r.delete("/sessions/{session_id}")
async def revoke_my_session(
    session_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    s = (
        await session.execute(
            select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == principal.user_id)
        )
    ).scalar_one_or_none()
    if s is None:
        raise ProblemError("not_found")
    reason = "user_logout" if s.id == principal.session_id else "user_revoked_other"
    await ss.end_session(session, s, status="revoked", reason=reason, ended_by=principal.user_id)
    await audit(
        session,
        principal,
        "session.revoked_by_owner",
        "auth_session",
        s.id,
        subject_user_id=principal.user_id,
    )
    return {"revoked": True, "session_id": str(s.id)}


@me_r.post("/sessions/revoke-others")
async def revoke_other_sessions(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    n = await ss.revoke_all_sessions(
        session,
        principal.user_id,
        "user_revoked_other",
        ended_by=principal.user_id,
        except_session_id=principal.session_id,
    )
    await audit(
        session,
        principal,
        "session.revoked_others",
        "user",
        principal.user_id,
        subject_user_id=principal.user_id,
        after={"revoked": n},
    )
    return {"revoked": n}


async def _devices_payload(session: Any, user: User, current_device: uuid.UUID | None) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                select(UserDevice, Device)
                .join(Device, Device.id == UserDevice.device_id)
                .where(UserDevice.user_id == user.id, UserDevice.trust_status.in_(("trusted", "pending_otp")))
                .order_by(UserDevice.created_at)
            )
        ).all()
    )
    groups: dict[tuple[str | None, str | None], str] = {}
    data = []
    for ud, dev in rows:
        key = (dev.os_family, dev.device_class)
        if key not in groups:
            groups[key] = f"g{len(groups) + 1}"
        data.append(
            {
                "user_device_id": str(ud.id),
                "label": dev.label_hint,
                "user_label": ud.user_label,
                "client_type": dev.client_type,
                "device_class": dev.device_class,
                "trust_status": ud.trust_status,
                "counts_toward_cap": ud.counts_toward_cap,
                "first_seen_at": to_rfc3339(dev.first_seen_at),
                "last_used_at": to_rfc3339(ud.last_used_at) if ud.last_used_at else None,
                "approx_region": None,
                "is_current": dev.id == current_device,
                "group_hint": f"probably_this_computer:{groups[key]}",
            }
        )
    limits = await ss.device_limits(session, user)
    nxt = limits.get("next_replacement_at")
    limits["next_replacement_at"] = to_rfc3339(nxt) if nxt else None  # type: ignore[arg-type]
    return {
        "data": data,
        "limits": limits,
        "page": {"next_cursor": None, "has_more": False, "limit": len(data)},
    }


@me_r.get("/devices", openapi_extra={"x-td-idle": "neutral"})
async def my_devices(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    user = await session.get(User, principal.user_id)
    assert user is not None
    return await _devices_payload(session, user, principal.device_id)


async def _own_device(session: Any, principal: Principal, user_device_id: uuid.UUID) -> UserDevice:
    ud = (
        await session.execute(
            select(UserDevice).where(
                UserDevice.id == user_device_id,
                UserDevice.user_id == principal.user_id,
                UserDevice.trust_status != "removed",
            )
        )
    ).scalar_one_or_none()
    if ud is None:
        raise ProblemError("not_found")
    return ud


@me_r.patch("/devices/{user_device_id}")
async def rename_device(
    user_device_id: uuid.UUID,
    body: RenameIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    ud = await _own_device(session, principal, user_device_id)
    ud.user_label = body.user_label.strip()
    return {"user_device_id": str(ud.id), "user_label": ud.user_label}


@me_r.delete("/devices/{user_device_id}")
async def remove_my_device(
    user_device_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    # Re-auth when this is a remember-device session whose full authentication is > 24 h old.
    if "remember" in principal.amr and (
        principal.auth_time is None or clock.now() - principal.auth_time > timedelta(hours=24)
    ):
        raise ProblemError(
            "step_up_required",
            step_up={
                "max_age_seconds": 900,
                "allowed_methods": ["password", "totp"],
                "options_url": "/api/v1/auth/step-up/options",
            },
        )
    ud = await _own_device(session, principal, user_device_id)
    n = await ss.remove_user_device(session, ud, "self_service_signout", removed_by=principal.user_id)
    await audit(
        session,
        principal,
        "session.device.removed",
        "user_device",
        ud.id,
        subject_user_id=principal.user_id,
        after={"sessions_revoked": n},
    )
    return {"removed": True, "sessions_revoked": n}


@me_r.get("/device-policy", openapi_extra={"x-td-idle": "neutral"})
async def device_policy(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    uid = principal.user_id
    return {
        "devices": {
            "max_trusted": await get_policy(session, "devices.student.max_trusted", user_id=uid),
            "max_replacements_per_30d": await get_policy(
                session, "devices.student.max_replacements_per_30d", user_id=uid
            ),
            "trusted_inactivity_expiry_days": await get_policy(
                session, "devices.trusted_inactivity_expiry_days"
            ),
        },
        "sessions": {
            "max_concurrent": await get_policy(
                session,
                "sessions.student.max_concurrent"
                if principal.tier == "student"
                else "sessions.staff.max_concurrent",
                user_id=uid,
            ),
            "at_limit_behavior": await get_policy(session, "sessions.student.at_limit_behavior", user_id=uid),
            "idle_minutes": int(ss.TIMEOUTS[principal.tier][0].total_seconds() // 60),
            "absolute_hours": int(ss.TIMEOUTS[principal.tier][1].total_seconds() // 3600),
            "remember_device_max_days": await get_policy(
                session, "sessions.remember_device.max_days", user_id=uid
            ),
        },
        "streams": {"max_concurrent": 1},
        "attempts": {"max_rebinds_per_attempt": 2},
    }


@me_r.get("/login-history", openapi_extra={"x-td-idle": "neutral"})
async def login_history(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    since = clock.now() - timedelta(days=90)
    rows = list(
        (
            await session.execute(
                select(LoginAttempt)
                .where(LoginAttempt.user_id == principal.user_id, LoginAttempt.attempted_at >= since)
                .order_by(LoginAttempt.attempted_at.desc())
                .limit(200)
            )
        ).scalars()
    )
    attempts = [
        {
            "at": to_rfc3339(a.attempted_at),
            "method": a.method,
            "mfa_method": a.mfa_method,
            "result": a.outcome,
            "ip": a.ip,
        }
        for a in rows
    ]
    ended = [
        s
        for s in await _list_sessions(session, principal.user_id, principal.session_id, owner=True)
        if s["logout_at"]
    ]
    return {"attempts": attempts, "ended_sessions": ended}


# --------------------------------------------------------------------------- SES-09..12 (staff)


def _require_reason(code: str | None) -> str:
    if not code or code not in REASON_CODES:
        raise ProblemError("reason_code_required", allowed_reason_codes=list(REASON_CODES))
    return code


async def _target_user(session: Any, user_id: uuid.UUID) -> User:
    u = await session.get(User, user_id)
    if u is None:
        raise ProblemError("not_found")
    return u


def _staff_step_up(principal: Principal) -> None:
    from app.modules.identity.router import step_up_problem

    p = step_up_problem(principal, 300 if principal.tier == "privileged" else 600)
    if p:
        raise p


@admin_r.get("/{user_id}/sessions")
async def user_sessions(
    user_id: uuid.UUID,
    session: PrincipalDbSession,
    reason_code: Annotated[str | None, Query()] = None,
    principal: Principal = Depends(require_permission("session.read")),
) -> dict[str, Any]:
    code = _require_reason(reason_code)
    await _target_user(session, user_id)
    data = await _list_sessions(session, user_id, None, owner=False)
    await audit(
        session, principal, "session.list_viewed", "user", user_id, subject_user_id=user_id, reason_code=code
    )
    return {"data": data, "page": {"next_cursor": None, "has_more": False, "limit": len(data)}}


@admin_r.post("/{user_id}/sessions/revoke")
async def admin_revoke_sessions(
    user_id: uuid.UUID,
    body: AdminRevokeIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("session.revoke")),
) -> dict[str, Any]:
    code = _require_reason(body.reason_code)
    _staff_step_up(principal)
    await _target_user(session, user_id)
    if body.all:
        n = await ss.revoke_all_sessions(session, user_id, "admin_kill", ended_by=principal.user_id)
    elif body.session_id:
        n = await ss.end_sessions_where(
            session,
            AuthSession.id == body.session_id,
            AuthSession.user_id == user_id,
            status="revoked",
            reason="admin_kill",
            ended_by=principal.user_id,
        )
        if n == 0:
            raise ProblemError("not_found")
    else:
        raise ProblemError(
            "validation_failed",
            422,
            errors=[{"field": "session_id", "code": "required", "message": "session_id or all"}],
        )
    await audit(
        session,
        principal,
        "session.admin_kill",
        "user",
        user_id,
        subject_user_id=user_id,
        reason_code=code,
        reason=body.reason,
        after={"revoked": n, "all": body.all},
    )
    return {"revoked": n}


@admin_r.get("/{user_id}/devices")
async def user_devices(
    user_id: uuid.UUID,
    session: PrincipalDbSession,
    reason_code: Annotated[str | None, Query()] = None,
    principal: Principal = Depends(require_permission("session.read")),
) -> dict[str, Any]:
    code = _require_reason(reason_code)
    user = await _target_user(session, user_id)
    payload = await _devices_payload(session, user, None)
    support_used = await _support_resets_used(session, user_id)
    payload["limits"]["support_resets_used_30d"] = support_used
    await audit(
        session,
        principal,
        "session.devices_viewed",
        "user",
        user_id,
        subject_user_id=user_id,
        reason_code=code,
    )
    return payload


async def _support_resets_used(session: Any, user_id: uuid.UUID) -> int:
    rows = (
        await session.execute(
            select(UserDevice.id).where(
                UserDevice.user_id == user_id,
                UserDevice.removed_reason == "support_reset",
                UserDevice.removed_at >= clock.now() - timedelta(days=30),
            )
        )
    ).all()
    return len(rows)


@admin_r.post("/{user_id}/devices/{user_device_id}/reset")
async def admin_device_reset(
    user_id: uuid.UUID,
    user_device_id: uuid.UUID,
    body: DeviceResetIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("device.reset")),
) -> dict[str, Any]:
    code = _require_reason(body.reason_code)
    _staff_step_up(principal)
    ud = (
        await session.execute(
            select(UserDevice).where(
                UserDevice.id == user_device_id,
                UserDevice.user_id == user_id,
                UserDevice.trust_status != "removed",
            )
        )
    ).scalar_one_or_none()
    if ud is None:
        raise ProblemError("not_found")
    used = await _support_resets_used(session, user_id)
    beyond = used >= 1
    if beyond:
        from app.core.auth import PLATFORM_SCOPE
        from app.modules.rbac.service import check_permission

        if not await check_permission(session, principal, "device.reset.beyond_quota", PLATFORM_SCOPE):
            raise ProblemError(
                "device_replacement_quota_exhausted",
                detail="Support quota used; an admin must perform this reset.",
            )
    n = await ss.remove_user_device(session, ud, "support_reset", removed_by=principal.user_id)
    await audit(
        session,
        principal,
        "session.device.support_reset",
        "user_device",
        ud.id,
        subject_user_id=user_id,
        reason_code=code,
        reason=body.reason,
        after={"sessions_revoked": n, "beyond_quota": beyond},
    )
    return {"removed": True, "support_resets_used_30d": used + 1, "support_resets_max_30d": 1}


router = APIRouter()
router.include_router(me_r)
router.include_router(admin_r)
