"""Login pipeline after primary authentication (account-security §7.1, api-spec AUTH-06):

    MFA (users with a confirmed TOTP factor)  → pending_mfa
    → new device (untrusted user_device)      → pending_device_otp (email/SMS OTP, or TOTP)
       trusting it checks the trusted-device cap and the replacement quota
    → same-device sessions end (replaced_same_device)
    → concurrent-session cap (pg_advisory_xact_lock) → pending_session_choice (≤ 5 min)
    → active (+ remember-device credential for students on trusted devices)

``advance`` is re-entered by AUTH-11/13/14 until the session is active.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.errors import ProblemError
from app.core.security import generate_token, hash_token
from app.core.time import to_rfc3339
from app.modules.identity import clock
from app.modules.identity.contacts import mask_email, mask_phone
from app.modules.identity.models import User
from app.modules.identity.policy import get_policy
from app.modules.identity.service import has_strong_factor
from app.modules.sessions import service as ss
from app.modules.sessions.hooks import RestrictionState
from app.modules.sessions.models import AuthSession, Device, UserDevice

# Landing portal per role (single-company roles). Evaluators have their own grading portal
# (`/evaluator` in the web app: grading queues, results release; no authoring).
PORTALS = {
    "student": "/app",
    "evaluator": "/evaluator",
    "trainer": "/trainer",
    "content_manager": "/studio",
    "super_admin": "/admin",
}
# Most privileged first: the first role the user holds decides the landing portal.
LANDING_ORDER = ("super_admin", "content_manager", "trainer", "evaluator")


MFA_AMR = frozenset({"totp", "passkey", "recovery_code"})
# Satisfies T-step-up: MFA or SMS OTP (email OTP only when no verified mobile exists).
STEP_UP_AMR = frozenset({"totp", "passkey", "recovery_code", "otp_sms"})


def mfa_done(s: AuthSession) -> bool:
    return bool(set(s.amr) & MFA_AMR)


@dataclass
class LoginOutcome:
    status_code: int
    body: dict[str, Any]
    cookies: list[str] = field(default_factory=list)
    problem: ProblemError | None = None


def session_summary(s: AuthSession) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "status": s.status,
        "tier": s.session_tier,
        "scope": s.scope,
        "aal": s.aal,
        "created_via": s.created_via,
        "auth_time": to_rfc3339(s.auth_time),
        "idle_expires_at": to_rfc3339(s.idle_expires_at),
        "absolute_expires_at": to_rfc3339(s.absolute_expires_at),
    }


def device_channels(user: User) -> list[dict[str, str]]:
    out = []
    if user.phone_e164 and user.phone_verified_at:
        out.append({"channel": "sms", "destination_masked": mask_phone(user.phone_e164) or ""})
    if user.email:
        out.append({"channel": "email", "destination_masked": mask_email(user.email) or ""})
    return out


async def _device_cap_problem(session: AsyncSession, user: User) -> ProblemError | None:
    lim = await ss.device_limits(session, user)
    max_trusted = int(lim["max_trusted"])  # type: ignore[call-overload]
    trusted = await ss.trusted_devices(session, user.id)
    if len(trusted) < max_trusted:
        return None
    devs = []
    for ud in trusted:
        dev = await session.get(Device, ud.device_id)
        devs.append(
            {
                "user_device_id": str(ud.id),
                "label": dev.label_hint if dev else None,
                "user_label": ud.user_label,
                "last_used_at": to_rfc3339(ud.last_used_at) if ud.last_used_at else None,
            }
        )
    nxt = lim["next_replacement_at"]
    return ProblemError(
        "device_cap_reached",
        detail="You've reached your trusted-device limit. Remove a device to continue here.",
        devices=devs,
        max_trusted=max_trusted,
        replacements_used=lim["replacements_used_30d"],
        replacements_max=lim["replacements_max_30d"],
        next_replacement_at=to_rfc3339(nxt) if nxt else None,  # type: ignore[arg-type]
    )


async def free_device_slot(
    session: AsyncSession, user: User, remove_user_device_id: Any, current: UserDevice
) -> ProblemError | None:
    """Remove a trusted device during a pending login (counts as a replacement)."""
    ud = (
        await session.execute(
            select(UserDevice).where(
                UserDevice.id == remove_user_device_id,
                UserDevice.user_id == user.id,
                UserDevice.trust_status == "trusted",
            )
        )
    ).scalar_one_or_none()
    if ud is None or ud.id == current.id:
        return ProblemError("not_found")
    max_repl = int(await get_policy(session, "devices.student.max_replacements_per_30d", user_id=user.id))
    used, nxt = await ss.replacements_used(session, user.id)
    if used >= max_repl:
        return ProblemError(
            "device_replacement_quota_exhausted",
            next_replacement_at=to_rfc3339(nxt) if nxt else None,
            support_url="/app/support",
        )
    await ss.remove_user_device(session, ud, "self_service_replacement", removed_by=user.id)
    return None


async def trust_current_device(
    session: AsyncSession, user: User, ud: UserDevice, method: str | None, *, owner_verified: bool
) -> ProblemError | None:
    if ud.trust_status == "trusted":
        return None
    if ud.counts_toward_cap:
        cap = await _device_cap_problem(session, user)
        if cap is not None:
            return cap
    await ss.trust_device(session, ud, method, owner_verified=owner_verified)
    return None


async def advance(
    session: AsyncSession,
    *,
    s: AuthSession,
    user: User,
    ud: UserDevice | None,
    device: Device | None,
    restriction: RestrictionState,
    remember_requested: bool,
    token: str,
    info: ss.ClientInfo,
    rotate_on_activate: bool = True,
) -> LoginOutcome:
    """Move a (pending) session to the next step. ``token`` is the raw session token so
    the cookie can be (re)issued with every non-error outcome.

    ``rotate_on_activate`` (SEC-08, AUTH-06 "rotate token" step): a session that was pending
    in an earlier request gets a fresh token when it becomes active, so a token observed
    while pending never becomes a full session. Callers that minted the token in this
    request (login, remember refresh) or just rotated it (MFA verify) pass ``False``."""
    cookies = [ss.session_cookie(s, token)]

    # 1. MFA
    if not mfa_done(s) and await has_strong_factor(session, user.id):
        await ss.set_pending(session, s, "pending_mfa")
        methods = ["totp", "recovery_code"]
        return LoginOutcome(200, {"result": "mfa_required", "methods": methods}, cookies)

    # 2. Device trust (+ T-step-up, RE §6.2: MFA or SMS OTP even on a trusted device)
    strong = STEP_UP_AMR if (user.phone_e164 and user.phone_verified_at) else STEP_UP_AMR | {"otp_email"}
    step_up = restriction.step_up_required and not (set(s.amr) & strong)
    if ud is not None and (ud.trust_status != "trusted" or step_up):
        if step_up and (ud.trust_status == "trusted" or await ss.has_device_history(session, user.id)):
            await ss.set_pending(session, s, "pending_device_otp")
            sms_only = [c for c in device_channels(user) if c["channel"] == "sms"]
            return LoginOutcome(
                200,
                {
                    "result": "device_verification_required",
                    "reason": "security_step_up",
                    "channels": sms_only or device_channels(user),
                    "alternatives": ["totp"] if await has_strong_factor(session, user.id) else [],
                },
                cookies,
            )
        if not await ss.has_device_history(session, user.id):
            problem = await trust_current_device(session, user, ud, None, owner_verified=False)
        elif mfa_done(s):
            problem = await trust_current_device(session, user, ud, "totp", owner_verified=True)
        else:
            await ss.set_pending(session, s, "pending_device_otp")
            return LoginOutcome(
                200,
                {
                    "result": "device_verification_required",
                    "channels": device_channels(user),
                    "alternatives": ["totp"] if await has_strong_factor(session, user.id) else [],
                },
                cookies,
            )
        if problem is not None:
            await ss.set_pending(session, s, "pending_device_otp")
            return LoginOutcome(problem.status, {}, cookies, problem)

    # 3. Same-device sessions end, then the concurrent-session cap
    await ss.lock_user(session, user.id)
    if s.device_id is not None:
        await ss.end_sessions_where(
            session,
            AuthSession.user_id == user.id,
            AuthSession.device_id == s.device_id,
            AuthSession.id != s.id,
            AuthSession.status == "active",
            status="revoked",
            reason="replaced_same_device",
        )
    key = (
        "sessions.student.max_concurrent" if s.session_tier == "student" else "sessions.staff.max_concurrent"
    )
    max_concurrent = int(await get_policy(session, key, user_id=user.id))
    others = await ss.active_sessions(session, user.id, exclude=s.id)
    if len(others) >= max_concurrent:
        behavior = str(await get_policy(session, "sessions.student.at_limit_behavior", user_id=user.id))
        with_attempt = await ss.sessions_with_attempts(session, [o.id for o in others])
        evictable = [o for o in others if o.id not in with_attempt]
        if behavior == "evict_oldest" and evictable:
            await ss.end_session(session, evictable[0], status="revoked", reason="session_cap_evicted")
        else:
            minutes = int(await get_policy(session, "auth.session_choice_minutes"))
            await ss.set_pending(session, s, "pending_session_choice", minutes)
            listing = []
            for o in others:
                dev = await session.get(Device, o.device_id) if o.device_id else None
                listing.append(
                    {
                        "session_id": str(o.id),
                        "device_label": (dev.label_hint if dev else None)
                        or f"{o.ua_family} on {o.os_family}",
                        "approx_region": o.geo_region,
                        "last_active_at": to_rfc3339(o.last_seen_at),
                        "has_active_attempt": o.id in with_attempt,
                    }
                )
            problem = ProblemError(
                "session_cap_reached",
                title=f"You're signed in on {len(others)} devices",
                detail="Sign out of one device to continue here.",
                max_concurrent=max_concurrent,
                sessions=listing,
                choice_url="/api/v1/auth/session-choice",
                selectable=behavior != "deny" and bool(evictable),
            )
            return LoginOutcome(409, {}, cookies, problem)

    # 4. Activate (rotate first: the pending token must not become an active session token)
    if rotate_on_activate and s.status != "active":
        token = await ss.rotate_token(session, s)
    await ss.activate_session(session, s)
    user.last_login_at = clock.now()
    if ud is not None:
        ud.last_used_at = clock.now()
    if (
        remember_requested
        and s.session_tier == "student"
        and ud is not None
        and ud.trust_status == "trusted"
        and device is not None
    ):
        days = int(await get_policy(session, "sessions.remember_device.max_days", user_id=user.id))
        if days > 0:
            remember_raw = generate_token()
            ud.remember_token_hash = hash_token(remember_raw)
            ud.remember_until = s.auth_time + timedelta(days=days)
            ud.remember_issued_at = clock.now()
            s.remember_device = True
            cookies.append(
                ss.cookie_header(
                    ss.REMEMBER_COOKIE, remember_raw, int((ud.remember_until - clock.now()).total_seconds())
                )
            )
    await session.flush()
    cookies[0] = ss.session_cookie(s, token)
    await audit(
        session,
        AuditActor("user", user_id=user.id, session_id=s.id),
        "auth.login.succeeded",
        "auth_session",
        s.id,
        subject_user_id=user.id,
        ip=info.ip,
        after={"tier": s.session_tier, "amr": list(s.amr), "created_via": s.created_via, "scope": s.scope},
    )
    body: dict[str, Any] = {"result": "authenticated", "session": session_summary(s)}
    if restriction.level >= 3:
        body["restriction"] = {
            "level": restriction.level,
            "case_ref": restriction.case_ref,
            "until": to_rfc3339(restriction.until) if restriction.until else None,
        }
        body["redirect"] = "/app/account-status"
    else:
        body["redirect"] = await _landing(session, user)
    return LoginOutcome(200, body, cookies)


async def _landing(session: AsyncSession, user: User) -> str:
    from app.modules.rbac.service import active_grants

    grants = await active_grants(session, user.id)
    for role in LANDING_ORDER:
        if any(g.role == role for g in grants):
            return PORTALS[role]
    return "/app"
