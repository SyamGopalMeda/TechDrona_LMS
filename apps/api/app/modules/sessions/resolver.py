"""``SessionResolver`` for ``app.core.auth.require_active_principal`` (api-spec §1.4 steps 2-11).

Revocations decided here (expiry, device mismatch, revoke-all cut-off) are committed in this
resolver's own transaction before the 401 is raised, so a replayed/stolen cookie stays dead.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.config import get_settings
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal, RoleGrant
from app.core.routing import RouteContext, scope_allows
from app.core.security import hash_token
from app.core.time import to_rfc3339
from app.modules.identity import clock
from app.modules.identity.fs_codec import obj_doc
from app.modules.identity.links import web_link, web_path
from app.modules.identity.public import User
from app.modules.identity.service import active_factors, is_confirmed_strong
from app.modules.sessions import service as ss
from app.modules.sessions.hooks import (
    RestrictionState,
    derive_scope,
    lookup_restriction,
    missing_consents,
    security_events,
)
from app.modules.sessions.models import AuthSession, SessionNetworkObservation
from app.modules.sessions.ua import net_cluster

NEXT_STEP = {
    "pending_mfa": "mfa",
    "pending_device_otp": "device_verification",
    "pending_session_choice": "session_choice",
}
LAST_SEEN_WRITE_INTERVAL = timedelta(seconds=60)
# Tags that never require MFA enrolment / consent / guardian consent first.
_MFA_EXEMPT = frozenset({"mfa_enrolment", "login_continuation", "public"})
_CONSENT_EXEMPT = frozenset({"consent", "account_status", "login_continuation", "mfa_enrolment", "public"})
_MINOR_PENDING_ALLOWED = frozenset({"consent", "account_status", "login_continuation", "mfa_enrolment"})
# ``users.must_change_password`` (set by an Admin, or by a protect-lock): only these work until the
# person chooses a new password. Tags: logout + login steps, public routes, consents, MFA
# enrolment (strict mode: staff may have to enrol before the password change is allowed); plus
# the routes below (paths as declared on the route, without the ``/api/v1`` prefix).
_PW_CHANGE_EXEMPT_TAGS = frozenset({"login_continuation", "public", "consent", "mfa_enrolment"})
_PW_CHANGE_EXEMPT_ROUTES = frozenset(
    {("POST", "/auth/password/change"), ("GET", "/me"), ("GET", "/me/grants")}
)
_API_PREFIX = "/api/v1"


def password_change_exempt(ctx: RouteContext) -> bool:
    path = ctx.path[len(_API_PREFIX) :] if ctx.path.startswith(_API_PREFIX + "/") else ctx.path
    return ctx.route_tag in _PW_CHANGE_EXEMPT_TAGS or (ctx.method.upper(), path) in _PW_CHANGE_EXEMPT_ROUTES


@dataclass(frozen=True, slots=True)
class _Deny:
    exc: ProblemError


async def org_ids_for(
    session: AsyncSession, user_id: uuid.UUID, grant_orgs: set[uuid.UUID]
) -> tuple[uuid.UUID, ...]:
    from app.modules.orgs import public as orgs_public

    rows = await orgs_public.active_org_ids(session, user_id)
    return tuple(sorted(set(rows) | grant_orgs, key=str))


async def build_principal(
    session: AsyncSession, s: AuthSession, user: User, restriction: RestrictionState
) -> Principal:
    from app.modules.rbac.service import active_grants, has_platform_staff_grant

    grants = await active_grants(session, user.id)
    orgs = await org_ids_for(session, user.id, {g.organization_id for g in grants if g.organization_id})
    factors = await active_factors(session, user.id)
    mfa_level = (
        "passkey"
        if any(f.factor_type == "webauthn" for f in factors)
        else ("totp" if any(is_confirmed_strong(f) for f in factors) else "none")
    )
    return Principal(
        user_id=user.id,
        session_id=s.id,
        tier=s.session_tier,  # type: ignore[arg-type]
        scope=derive_scope(restriction.level),  # type: ignore[arg-type]
        device_id=s.device_id,
        org_ids=orgs,
        grants=tuple(RoleGrant(g.role, g.scope_type, g.scope_id) for g in grants),  # type: ignore[arg-type]
        is_platform=has_platform_staff_grant(grants),
        aal=s.aal,
        amr=tuple(s.amr),
        mfa_level=mfa_level,  # type: ignore[arg-type]
        auth_time=s.auth_time,
        # TD_SIMPLE_AUTH: step-up ("confirm it's you") is always treated as fresh.
        last_step_up_at=clock.now() if get_settings().simple_auth else s.last_step_up_at,
        restriction_level=restriction.level,
        restrictions=restriction.restrictions,
        is_minor=user.is_minor,
        privacy_tier=user.privacy_tier,
    )


class SessionsResolver:
    async def resolve(self, request: Request, session_token: str, ctx: RouteContext) -> Principal:
        result: Principal | _Deny
        async with ss.system_session("sessions.resolve") as session:
            result = await self._resolve(session, request, session_token, ctx)
        if isinstance(result, _Deny):
            raise result.exc
        return result

    async def _resolve(
        self, session: AsyncSession, request: Request, token: str, ctx: RouteContext
    ) -> Principal | _Deny:
        now = clock.now()
        if ss._fs():
            s = await ss._repo().session_by_token(hash_token(token))
        else:
            s = (
                await session.execute(
                    select(AuthSession).where(AuthSession.token_hash == hash_token(token)).with_for_update()
                )
            ).scalar_one_or_none()
        if s is None:
            sink = security_events()
            if sink is not None and await sink.unknown_token(session, ss.client_info(request).ip):
                return _Deny(ProblemError("rate_limited", headers={"Retry-After": "900"}))
            return _Deny(ProblemError("unauthenticated"))
        if s.status == "expired":
            return _Deny(ProblemError("session_expired", reason=s.end_reason))
        if s.status in ("revoked", "blocked"):
            safe = _user_safe_reason(s.end_reason)
            return _Deny(ProblemError("session_revoked", detail=_REVOKED_DETAIL.get(safe or ""), reason=safe))

        # 3. expiry (idle not enforced while an attempt holds the session)
        if now >= s.absolute_expires_at:
            await ss.end_session(session, s, status="expired", reason="absolute_timeout")
            return _Deny(ProblemError("session_expired", reason="absolute_timeout"))
        if now >= s.idle_expires_at and not (s.idle_hold_until and now < s.idle_hold_until):
            await ss.end_session(session, s, status="expired", reason="idle_timeout")
            return _Deny(ProblemError("session_expired", reason="idle_timeout"))

        info = ss.client_info(request)
        # 4. stolen-cookie replay: device cookie or UA family/OS drift -> revoke THIS session only
        # Simple auth (owner decision 2026-11-12): a browser/OS label change (e.g. Chrome's
        # "Desktop site" toggle on a phone) no longer signs the user out; the device cookie still
        # has to match.
        drift = not get_settings().simple_auth and (
            (s.ua_family and info.ua.family != s.ua_family)
            or (s.os_family and info.ua.os_family != s.os_family)
        )
        if not await ss.device_hash_matches(session, s.device_id, info.device_token) or drift:
            await ss.end_session(session, s, status="blocked", reason="device_mismatch")
            await audit(
                session,
                AuditActor.system("sessions.resolve"),
                "session.replay_blocked",
                "auth_session",
                s.id,
                subject_user_id=s.user_id,
                ip=info.ip,
                # E2E-09: expected vs observed UA family / OS explain a drift block
                after={
                    "rule": "TO-08" if drift else "TO-04",
                    "expected_ua_family": s.ua_family,
                    "expected_os_family": s.os_family,
                    "observed_ua_family": info.ua.family,
                    "observed_os_family": info.ua.os_family,
                },
            )
            sink = security_events()
            if sink is not None:
                await sink.replay_blocked(
                    session,
                    s,
                    "TO-08" if drift else "TO-04",
                    observed={"ua_family": info.ua.family, "os_family": info.ua.os_family},
                )
            return _Deny(ProblemError("session_revoked", reason="device_mismatch"))

        # 5. revoke-all cut-off and account state
        if ss.uses_firestore("identity"):
            from app.modules.identity.repo_firestore import system_repo as identity_repo

            user = await identity_repo().get_user(s.user_id)
        else:
            user = await session.get(User, s.user_id)
        if user is None or user.status in ("deactivated", "deleted") or user.deleted_at is not None:
            await ss.end_session(session, s, status="revoked", reason="account_deleted")
            return _Deny(ProblemError("session_revoked", reason="account_deleted"))
        if user.sessions_valid_after is not None and user.sessions_valid_after > s.created_at:
            await ss.end_session(session, s, status="revoked", reason="admin_kill")
            return _Deny(ProblemError("session_revoked", reason="signed_out_everywhere"))

        # 6. pending login steps
        if s.status in ss.PENDING_STATUSES and ctx.route_tag != "login_continuation":
            return _Deny(ProblemError("login_incomplete", next_step=NEXT_STEP[s.status]))

        # 7. scope gate from the current restriction state
        restriction = await lookup_restriction(session, user.id, user.restriction_level)
        if restriction.takeover_lock and ctx.route_tag != "login_continuation":
            return _Deny(
                ProblemError(
                    "account_protect_locked",
                    recovery_url=web_path("forgot_password"),
                    recovery_link=web_link("forgot_password"),
                )
            )
        scope = derive_scope(restriction.level)
        if not scope_allows(scope, ctx.route_tag):
            sink = security_events()
            if sink is not None:
                await sink.restricted_denial(session, user.id, ctx.path)
            return _Deny(
                ProblemError(
                    "account_restricted",
                    case_ref=restriction.case_ref,
                    level=restriction.level,
                    until=to_rfc3339(restriction.until) if restriction.until else None,
                    status_url="/app/account-status",
                )
            )

        if s.status == "active":
            # 7b. an Admin-assigned (or protect-lock) password must be replaced first
            if user.must_change_password and not password_change_exempt(ctx):
                return _Deny(ProblemError("password_change_required", change_url="/change-password"))
            # 8. mandatory MFA for staff/privileged tiers, and for students when the platform
            #    policy ``auth.require_mfa_students`` is on (single-company replacement of the
            #    per-org FR-ORG-002 setting). Students who already have a factor are asked for it
            #    at login (``advance``); without one they must enrol.
            if (
                ctx.route_tag not in _MFA_EXEMPT
                and not get_settings().simple_auth  # TD_SIMPLE_AUTH: MFA is optional
                and not get_settings().mfa_exempt(user.email)
                and (s.session_tier != "student" or await students_require_mfa(session, user.id))
            ):
                if not any(is_confirmed_strong(f) for f in await active_factors(session, user.id)):
                    return _Deny(
                        ProblemError("mfa_enrolment_required", enrol_url="/app/settings/security/mfa")
                    )
            # minors without verified guardian consent
            if user.status == "pending_guardian_consent" and ctx.route_tag not in _MINOR_PENDING_ALLOWED:
                return _Deny(ProblemError("minor_consent_pending", guardian_flow_url="/app/guardian-consent"))
            # 9. required consents
            # Changing your own password never waits for the terms step (a new admin-created user
            # must be able to replace the default password first; live check 2026-11-12).
            pw_change = (ctx.method.upper(), ctx.path.removeprefix(_API_PREFIX)) == (
                "POST",
                "/auth/password/change",
            )
            if ctx.route_tag not in _CONSENT_EXEMPT and not pw_change:
                missing = await missing_consents(session, user.id)
                if missing:
                    return _Deny(
                        ProblemError("consent_required", purposes=missing[0], notice_version=missing[1])
                    )

            # 10. idle sliding + last_seen + network observation
            await self._touch(session, s, ctx, request, info.ip)

        principal = await build_principal(session, s, user, restriction)
        request.state.auth_session_id = s.id
        return principal

    async def _touch(
        self, session: AsyncSession, s: AuthSession, ctx: RouteContext, request: Request, ip: str | None
    ) -> None:
        n = clock.now()
        before = obj_doc(s) if ss._fs() else None
        engaged = ctx.idle_effect == "extends" and (
            ctx.method != "GET" or getattr(request.state, "activity", None) == "navigation"
        )
        if engaged:
            idle, _ = ss.session_timeouts(s.session_tier)
            s.idle_expires_at = min(n + idle, s.absolute_expires_at)
        if n - s.last_seen_at >= LAST_SEEN_WRITE_INTERVAL or engaged:
            s.last_seen_at = n
            cluster = net_cluster(ip)
            if ip:
                s.ip_last = ip
            if cluster and cluster != s.net_cluster_last:
                s.net_cluster_last = cluster
                obs = SessionNetworkObservation(
                    id=uuid7(),
                    first_seen_at=n,
                    last_seen_at=n,
                    auth_session_id=s.id,
                    user_id=s.user_id,
                    net_cluster=cluster,
                )
                if ss._fs():
                    await ss._repo().add_observation(obs)
                else:
                    session.add(obs)
        if ss._fs():
            if obj_doc(s) != before:  # Postgres flushes only dirty rows; write only on change
                await ss.save_session(session, s)
            return
        await session.flush()


async def touch_engaged(session_id: uuid.UUID) -> None:
    """``engaged_only`` routes call this when the server credits engagement (RE §1.4)."""
    async with ss.system_session("sessions.touch_engaged") as session:
        s = (
            await ss._repo().get_session(session_id)
            if ss._fs()
            else await session.get(AuthSession, session_id)
        )
        if s is not None and s.status == "active":
            idle, _ = ss.session_timeouts(s.session_tier)
            n = clock.now()
            new_idle = min(n + idle, s.absolute_expires_at)
            if new_idle == s.idle_expires_at and n - s.last_seen_at < LAST_SEEN_WRITE_INTERVAL:
                # Cost (Firestore: one write per credited heartbeat/event batch): the idle expiry
                # cannot move (it is already capped at the absolute expiry) and ``last_seen_at``
                # is fresher than the granularity every other request keeps it at (``_touch``:
                # LAST_SEEN_WRITE_INTERVAL), so writing would change nothing a reader relies on.
                return
            s.idle_expires_at = new_idle
            s.last_seen_at = n
            if ss._fs():
                await ss.save_session(session, s)


_USER_SAFE = {
    "user_logout",
    "user_revoked_other",
    "session_cap_evicted",
    "password_changed",
    "mfa_changed",
    "device_removed",
    "device_mismatch",
    "admin_kill",
    "privilege_change",
    "replaced_same_device",
    "unblock_reset",
    "account_deleted",
}


# ``detail`` of the 401 ``session_revoked`` per (user-safe) reason, so a client that shows the
# problem detail can say WHY (live audit 2026-11-14 #14 / student F-12: a new sign-in past the
# concurrent-session cap silently signed the oldest session out). Other reasons keep the
# catalogue title "You have been signed out".
_REVOKED_DETAIL = {
    "session_cap_evicted": (
        "You were signed out because your account signed in on another device "
        "and only a limited number of devices can stay signed in at once."
    ),
    "replaced_same_device": "You were signed out because your account signed in again on this device.",
    "user_revoked_other": "You were signed out from another device on your account.",
    "password_changed": "You were signed out because your password was changed.",
}


def _user_safe_reason(reason: str | None) -> str | None:
    return reason if reason in _USER_SAFE else "security_action"


async def students_require_mfa(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Platform policy ``auth.require_mfa_students`` (default off; a per-user policy exception
    wins). Staff MFA is decided by the session tier, not by this key."""
    from app.modules.identity.policy import get_policy

    return bool(await get_policy(session, "auth.require_mfa_students", user_id=user_id))
