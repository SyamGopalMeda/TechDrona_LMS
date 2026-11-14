"""Identity & authentication API (api-specification §4: AUTH-*, ME-*).

Pre-authentication routes run under the named system context ``identity.*`` (RLS
``app.is_platform``) because they must find a user before any principal exists; every
query in them is keyed by a token hash or a normalised identifier. Errors that must persist
state (failed-login counters, OTP attempt counters) are *returned* as problem responses so
the request transaction still commits.
"""

from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit as rl
from app.core.audit import AuditActor, audit
from app.core.auth import STEP_UP_WINDOWS, require_active_principal
from app.core.config import get_settings
from app.core.db import DbSession, PrincipalDbSession
from app.core.errors import ProblemError, problem_response
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.request_context import get_request_id
from app.core.routing import authenticated_router, public_router
from app.core.security import hash_password, hash_token
from app.core.time import ist_date, to_rfc3339, within
from app.modules.identity import clock, fs_uow, google
from app.modules.identity import public as ipub
from app.modules.identity import service as ids
from app.modules.identity.contacts import (
    classify_identifier,
    classify_login_identifier,
    identifier_digest,
    identifier_digests,
    mask_email,
    mask_phone,
    normalize_email,
    normalize_phone,
)
from app.modules.identity.crypto import encrypt_secret
from app.modules.identity.links import web_link, web_path
from app.modules.identity.models import (
    GuardianConsent,
    MfaFactor,
    PasswordResetToken,
    User,
    UserProfile,
    VerificationToken,
)
from app.modules.identity.passwords import password_problems
from app.modules.identity.pgctx import sys_ctx, sys_scope
from app.modules.identity.policy import get_policy
from app.modules.identity.schemas import (
    ChangePasswordIn,
    ConsentChangeIn,
    DeviceSendIn,
    DeviceVerifyIn,
    ForgotIn,
    GoogleLoginIn,
    GoogleSignupIn,
    GuardianDecisionIn,
    LoginIn,
    MfaVerifyIn,
    ProfilePatchIn,
    RememberIn,
    ResetIn,
    SessionChoiceIn,
    SignupIn,
    StepUpIn,
    StepUpOptionsIn,
    TokenIn,
    TotpBeginIn,
    TotpConfirmIn,
)
from app.modules.identity.totp import provisioning_uri, random_base32
from app.modules.notifications.service import notify, send_email, send_sms
from app.modules.sessions import public as spub
from app.modules.sessions import service as ss
from app.modules.sessions.hooks import lookup_restriction
from app.modules.sessions.login import (
    LoginOutcome,
    advance,
    free_device_slot,
    session_summary,
    trust_current_device,
)
from app.modules.sessions.public import AuthSession, Device, UserDevice

pub = public_router(prefix="/auth", tags=["auth"])
lc = authenticated_router(prefix="/auth", tags=["auth"], route_tag="login_continuation", idle="extends")
acct = authenticated_router(tags=["auth"], route_tag="account_status", idle="extends")
dflt = authenticated_router(tags=["auth"], route_tag="default", idle="extends")
consent_r = authenticated_router(prefix="/me", tags=["me"], route_tag="consent", idle="extends")
mfa_r = authenticated_router(prefix="/me/mfa", tags=["me"], route_tag="mfa_enrolment", idle="extends")

NOTICE_VERSION_DEFAULT = "2026-11-01"

# API §4 identity "Rate limit" column (SEC-02/SEC-03). Per-IP rules are skipped when the
# client IP is unknown (the BFF sends none without a trusted proxy hop; see SEC-01).
AUTH_LIMITS: dict[str, tuple[rl.Rule, ...]] = {
    "auth01_signup_ip_device": (rl.Rule(5, rl.HOUR),),
    "auth01_signup_contact": (rl.Rule(3, rl.DAY),),
    "auth02_verify_email_ip": (rl.Rule(20, rl.HOUR),),
    "auth16_forgot_ip": (rl.Rule(5, rl.HOUR),),
    "auth16_forgot_identifier": (rl.Rule(3, rl.HOUR),),
    "auth17_reset_ip": (rl.Rule(10, rl.HOUR),),
    "auth18_change_user": (rl.Rule(5, rl.HOUR),),
    "auth19_options_user": (rl.Rule(10, rl.MIN),),
    "auth28_remember_device": (rl.Rule(10, rl.MIN),),
    # Out-of-band "you already have an account" mail: at most one per contact per day.
    "auth01_already_registered_mail": (rl.Rule(1, rl.DAY),),
}


async def _limit(name: str, subject: str | None) -> None:
    """Count one request for rule ``name`` keyed by ``subject`` (skipped when unknown)."""
    if subject:
        await rl.hit(f"{name}:{subject}", AUTH_LIMITS[name], scope=name.split("_", 1)[0])


def _contact_key(kind: str, value: str) -> str:
    return identifier_digest(kind, value)[1].hex()


# SEC-05: both signup outcomes (new account / already registered) answer no sooner than this,
# plus jitter, so response time does not reveal whether the contact exists.
SIGNUP_MIN_SECONDS = 1.0
SIGNUP_JITTER_SECONDS = 0.15


async def _pad_signup(started: float) -> None:
    target = SIGNUP_MIN_SECONDS + secrets.randbelow(1000) / 1000 * SIGNUP_JITTER_SECONDS
    remaining = target - (time.monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)


# --------------------------------------------------------------------------- helpers


def _vf(field: str, code: str, message: str, status: int = 400) -> ProblemError:
    return ProblemError(
        "validation_failed", status, errors=[{"field": field, "code": code, "message": message}]
    )


def _respond(outcome: LoginOutcome, extra_cookies: list[str] | None = None) -> JSONResponse:
    resp = (
        problem_response(outcome.problem)
        if outcome.problem
        else JSONResponse(outcome.body, outcome.status_code)
    )
    for c in [*outcome.cookies, *(extra_cookies or [])]:
        resp.headers.append("set-cookie", c)
    return resp


def step_up_problem(
    principal: Principal, seconds: int, methods: list[str] | None = None
) -> ProblemError | None:
    if get_settings().simple_auth:  # TD_SIMPLE_AUTH: no re-confirm prompts
        return None
    if within(principal.last_step_up_at, timedelta(seconds=seconds), now=clock.now()):
        return None
    # Passkeys are not built yet (SEC-11), so they are not advertised. Without ``methods`` this
    # is the tier's generic list; ``step_up_problem_for`` passes the account's real methods
    # (AUTH-19), so the hint matches what /auth/step-up/options will offer.
    if methods is None:
        methods = ["totp"]
        if principal.tier == "student":
            methods += ["sms_otp", "email_otp"]
    return ProblemError(
        "step_up_required",
        detail="This action needs a fresh confirmation.",
        step_up={
            "max_age_seconds": seconds,
            "allowed_methods": methods,
            "options_url": "/api/v1/auth/step-up/options",
        },
    )


async def step_up_problem_for(
    session: AsyncSession, principal: Principal, seconds: int
) -> ProblemError | None:
    """``step_up_problem`` advertising only the methods this account can actually use."""
    if within(principal.last_step_up_at, timedelta(seconds=seconds), now=clock.now()):
        return None
    user = await _user(session, principal.user_id)
    return step_up_problem(principal, seconds, await _step_up_methods(session, principal, user))


def totp_replay_problem() -> ProblemError:
    """E2E-12: a valid TOTP code reused within its 30 s step (single use per step, AUTH-20)."""
    return ProblemError(
        "otp_invalid",
        detail="This code was already used. Wait for the next code in your authenticator app.",
        reason="code_already_used",
        attempts_remaining=None,
    )


def tier_window(principal: Principal) -> int:
    return {"student": STEP_UP_WINDOWS["student"], "staff": STEP_UP_WINDOWS["staff"]}.get(
        principal.tier, STEP_UP_WINDOWS["privileged"]
    )


async def _insert(session: AsyncSession, obj: Any) -> None:
    """``session.add(obj); await session.flush()`` on either store (Firestore: inserted now,
    later changes to ``obj`` are written at the end of the request by ``fs_uow``)."""
    if fs_uow.on_firestore(obj) and fs_uow.current() is None:
        async with fs_uow.open_uow():
            fs_uow.add(session, obj)
        return
    fs_uow.add(session, obj)
    await fs_uow.flush(session, obj)


async def _emit(session: AsyncSession, event_type: str, payload: dict[str, Any], **kw: Any) -> None:
    """Outbox event: Postgres outbox, or the Firestore outbox when identity is on Firestore
    (the event must commit with the identity change it describes)."""
    if ids._fs():
        from app.core.firestore.core_store import emit_event_firestore

        await emit_event_firestore(event_type, payload, **kw)
        return
    await emit_event(session, event_type, payload, **kw)


async def _current_session(session: AsyncSession, request: Request) -> AuthSession:
    sid = getattr(request.state, "auth_session_id", None)
    s = await spub.get_session(session, sid) if sid else None
    if s is None:
        raise ProblemError("unauthenticated")
    return s


async def _user(session: AsyncSession, user_id: uuid.UUID) -> User:
    u = await ipub.get_user(session, user_id)
    if u is None:
        raise ProblemError("unauthenticated")
    return u


async def _create_user(session: AsyncSession, user: User, profile: UserProfile) -> None:
    """Insert a user and profile (Firestore: with the email/phone/username reservations)."""
    if ids._fs():
        created = await ipub.create_user(session, user, profile)
        fs_uow.discard(created)
        from app.modules.identity.fs_codec import columns, obj_doc

        for attr in columns(User):  # server defaults, as Postgres eager_defaults fills them
            setattr(user, attr, getattr(created, attr))
        uow = fs_uow.current()
        if uow is not None:  # later changes to ``user`` (e.g. last_login_at) are written at the end
            uow.tracked[id(user)] = (user, obj_doc(user))
        return
    session.add(user)
    await session.flush()
    session.add(profile)


async def _login_identifier(user: User) -> tuple[int, bytes]:
    if user.email:
        return identifier_digest("email", user.email)
    return identifier_digest("phone", user.phone_e164 or str(user.id))


async def _send_verification_email(session: AsyncSession, user: User, ip: str | None) -> None:
    if not user.email:
        return
    ttl = timedelta(hours=int(await get_policy(session, "auth.email_verify_ttl_hours")))
    raw = await ids.issue_link_token(
        session,
        user_id=user.id,
        purpose="email_verify",
        channel="email",
        destination=user.email,
        ttl=ttl,
        ip=ip,
    )
    await send_email(
        user.email,
        "Verify your email for Tech Drona",
        f"Confirm your email address: {web_link('verify_email', token=raw)}\n\n"
        "This link expires in 24 hours.",
        template_key="auth.verify_email",
    )


# =========================================================================== AUTH-01 signup


async def _record_signup_consents(
    session: AsyncSession,
    uid: uuid.UUID,
    consents: list[Any],
    is_minor: bool,
    *,
    ip: str | None,
    user_agent: str | None,
) -> None:
    for c in consents:
        if not c.granted or (is_minor and c.purpose in ids.MINOR_FORBIDDEN):
            continue  # optional items are simply not granted; minors cannot grant B, C, E, F, H
        await ids.record_consent(
            session, uid, c.purpose, "granted", c.notice_version, ip=ip, user_agent=user_agent
        )


async def _start_guardian_consent(
    session: AsyncSession,
    uid: uuid.UUID,
    full_name: str,
    guardian: Any,
    g_email: str | None,
    g_phone: str | None,
    *,
    ip: str | None,
) -> None:
    gc = GuardianConsent(
        id=uuid7(),
        child_user_id=uid,
        guardian_name=guardian.name,
        guardian_email=g_email,
        guardian_phone_e164=g_phone,
        relationship=guardian.relationship,
        verification_method="guardian_otp_declaration",
        status="pending",
        expires_at=None,
    )
    await _insert(session, gc)
    if g_email:
        raw = await ids.issue_link_token(
            session,
            user_id=uid,
            purpose="guardian_verify",
            channel="email",
            destination=g_email,
            ttl=timedelta(days=7),
            ip=ip,
        )
        await send_email(
            g_email,
            "Consent needed for your child's Tech Drona account",
            f"{full_name} has asked to join Tech Drona. Review and decide: "
            f"{web_link('guardian_consent', token=raw)}\n\nThis link expires in 7 days.",
            template_key="auth.guardian_consent_request",
        )


@pub.post("/signup", status_code=201)
async def signup(body: SignupIn, request: Request, session: DbSession) -> JSONResponse:
    started = time.monotonic()
    await sys_ctx(session, "identity.signup")
    info = ss.client_info(request)
    if info.ip:
        await _limit("auth01_signup_ip_device", f"{info.ip}|{info.device_token or '-'}")
    email = normalize_email(body.email) if body.email else None
    if body.email and not email:
        raise _vf("email", "invalid_email", "Enter a valid email address")
    phone = normalize_phone(body.mobile) if body.mobile else None
    if body.mobile and not phone:
        raise _vf("mobile", "invalid_mobile", "Enter a valid mobile number")
    if not email and not phone:
        raise _vf("email", "contact_required", "Email or mobile is required")
    if email:
        await _limit("auth01_signup_contact", _contact_key("email", email))
    if phone:
        await _limit("auth01_signup_contact", _contact_key("phone", phone))
    today = ist_date(clock.now())
    age = ids.age_on(body.date_of_birth, today)
    if body.date_of_birth > today or age > 120:
        raise _vf("date_of_birth", "invalid_date_of_birth", "Enter a valid date of birth")
    is_minor = age < 18
    probs = password_problems(body.password, context=tuple(x for x in ((email or "").split("@")[0],) if x))
    if probs:
        raise _vf("password", probs[0], "Choose a longer or less common password")
    granted = {c.purpose: c for c in body.consents if c.granted}
    missing = [p for p in ids.REQUIRED_AT_SIGNUP if p not in granted]
    if missing:
        raise ProblemError("consent_required", purposes=missing, notice_version=NOTICE_VERSION_DEFAULT)
    if is_minor and body.guardian is None:
        raise _vf("guardian", "guardian_required", "A parent or guardian is needed for under-18 accounts")
    g_email = normalize_email(body.guardian.email) if body.guardian and body.guardian.email else None
    g_phone = normalize_phone(body.guardian.phone) if body.guardian and body.guardian.phone else None
    if is_minor and not (g_email or g_phone):
        raise _vf("guardian.email", "guardian_contact_required", "Guardian email or mobile is required")

    existing = None
    if email:
        existing = await ids.find_user(session, "email", email)
    if existing is None and phone:
        existing = await ids.find_user(session, "phone", phone)
    if existing is not None:
        # No enumeration (AUTH-01): same 201 shape; the real owner is told out of band.
        # SEC-05: spend the same Argon2id work as a real signup and issue the device cookie
        # like the new-account branch, so timing and cookies do not tell the two apart.
        await asyncio.to_thread(hash_password, body.password)
        _device, raw_dev, _issued = await ss.resolve_device(session, info)
        if existing.email:
            # SEC-02: at most one "already registered" mail per contact per day.
            quota = await rl.check(
                f"auth01_already_registered_mail:{_contact_key('email', existing.email)}",
                AUTH_LIMITS["auth01_already_registered_mail"],
            )
            if quota is None:
                await send_email(
                    existing.email,
                    "You already have a Tech Drona account",
                    "Someone tried to sign up with this address. Sign in or reset your password: "
                    f"{web_link('forgot_password')}",
                    template_key="auth.already_registered",
                )
        dup = JSONResponse(
            {
                "user_id": str(uuid7()),
                "status": "pending_verification",
                "is_minor": is_minor,
                "next_steps": ["check_email"],
                "session": None,
            },
            status_code=201,
        )
        dup.headers.append("set-cookie", ss.device_cookie(raw_dev))
        await _pad_signup(started)
        return dup

    now = clock.now()
    uid = uuid7()
    user = User(
        id=uid,
        email=email,
        phone_e164=phone,
        status="pending_guardian_consent" if is_minor else "pending_verification",
        is_minor=is_minor,
        age_verified_at=now,
        age_verification_method="self_declared",
        account_origin="self_signup",
    )
    await _create_user(
        session,
        user,
        UserProfile(user_id=uid, full_name=body.full_name.strip(), date_of_birth=body.date_of_birth),
    )
    await ids.set_password(session, uid, body.password)
    await _record_signup_consents(
        session, uid, body.consents, is_minor, ip=info.ip, user_agent=request.headers.get("user-agent")
    )
    next_steps = []
    if email:
        next_steps.append("verify_email")
    if phone:
        next_steps.append("verify_mobile")
    if is_minor and body.guardian:
        await _start_guardian_consent(
            session, uid, body.full_name, body.guardian, g_email, g_phone, ip=info.ip
        )
        next_steps.insert(0, "guardian_consent")

    device, raw_dev, _issued = await ss.resolve_device(session, info)
    ud = await ss.ensure_user_device(session, uid, device)
    await ss.trust_device(session, ud, None, owner_verified=False)
    s, token = await ss.create_session(
        session,
        user_id=uid,
        tier="student",
        status="active",
        created_via="password",
        info=info,
        device=device,
        user_device=ud,
        amr=["pwd"],
    )
    user.last_login_at = now
    await _send_verification_email(session, user, info.ip)
    actor = AuditActor("user", user_id=uid, session_id=s.id)
    await audit(
        session,
        actor,
        "identity.user.signed_up",
        "user",
        uid,
        subject_user_id=uid,
        ip=info.ip,
        after={"is_minor": is_minor, "status": user.status},
    )
    await _emit(
        session,
        "identity.user_registered",
        {"user_id": str(uid), "is_minor": is_minor},
        aggregate_type="user",
        aggregate_id=uid,
    )
    resp = JSONResponse(
        {
            "user_id": str(uid),
            "status": user.status,
            "is_minor": is_minor,
            "next_steps": next_steps,
            "session": {
                "status": s.status,
                "scope": s.scope,
                "tier": s.session_tier,
                "idle_expires_at": to_rfc3339(s.idle_expires_at),
            },
        },
        status_code=201,
    )
    resp.headers.append("set-cookie", ss.session_cookie(s, token))
    resp.headers.append("set-cookie", ss.device_cookie(raw_dev))
    await _pad_signup(started)
    return resp


# =========================================================================== AUTH-02/03 email verification


@pub.post("/verify/email")
async def verify_email(body: TokenIn, request: Request, session: DbSession) -> dict[str, Any]:
    await _limit("auth02_verify_email_ip", ss.client_info(request).ip)
    await sys_ctx(session, "identity.verify_email")
    tok = await ids.consume_link_token(session, body.token, "email_verify")
    if tok is None or tok.user_id is None:
        raise _vf("token", "invalid_or_expired", "This link is invalid or has expired")
    user = await _user(session, tok.user_id)
    if not await ids.mark_token_consumed(session, tok):
        raise _vf("token", "invalid_or_expired", "This link is invalid or has expired")
    user.email_verified_at = clock.now()
    if user.status == "pending_verification":
        user.status = "active"
    await audit(
        session,
        AuditActor("user", user_id=user.id),
        "identity.email.verified",
        "user",
        user.id,
        subject_user_id=user.id,
    )
    return {"result": "verified", "status": user.status}


@acct.post("/auth/verify/email/resend", status_code=202)
async def resend_verification(
    request: Request, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    user = await _user(session, principal.user_id)
    if not user.email or user.email_verified_at:
        raise ProblemError("invalid_state_transition", current_state="verified", allowed=[])
    async with sys_scope(session, "identity.verify_email"):
        recent = len(
            await ipub.verification_tokens_of(
                session, user.id, purpose="email_verify", created_after=clock.now() - timedelta(hours=1)
            )
        )
        if recent >= 3:
            raise ProblemError("rate_limited", headers={"Retry-After": "3600"})
        await _send_verification_email(session, user, ss.client_info(request).ip)
    return {"status": "sent", "sent_to": mask_email(user.email)}


@acct.post("/auth/verify/mobile/send-otp")
async def mobile_send_otp(
    request: Request, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> JSONResponse:
    user = await _user(session, principal.user_id)
    if not user.phone_e164 or user.phone_verified_at:
        raise ProblemError("invalid_state_transition", current_state="verified", allowed=[])
    async with sys_scope(session, "identity.verify_mobile"):
        wait = await ids.otp_send_allowed(session, "sms", user.phone_e164)
        if wait:
            return problem_response(ProblemError("otp_send_limited", headers={"Retry-After": str(wait)}))
        _, code = await ids.create_otp(
            session,
            user_id=user.id,
            purpose="phone_verify",
            channel="sms",
            destination=user.phone_e164,
            ip=ss.client_info(request).ip,
        )
    await send_sms(user.phone_e164, f"{code} is your Tech Drona verification code.", template_key="otp")
    return JSONResponse(
        {
            "sent_to": mask_phone(user.phone_e164),
            "expires_in_seconds": int(await get_policy(session, "otp.ttl_seconds")),
        }
    )


@acct.post("/auth/verify/mobile")
async def mobile_verify(
    body: TotpConfirmIn, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> JSONResponse:
    user = await _user(session, principal.user_id)
    async with sys_scope(session, "identity.verify_mobile"):
        chk = await ids.check_otp(session, purpose="phone_verify", code=body.code, user_id=user.id)
    if not chk.ok:
        assert chk.problem is not None
        return problem_response(chk.problem)
    user.phone_verified_at = clock.now()
    if user.status == "pending_verification":
        user.status = "active"
    await audit(session, principal, "identity.mobile.verified", "user", user.id, subject_user_id=user.id)
    return JSONResponse({"result": "verified"})


# =========================================================================== AUTH-06 login


@pub.post("/login")
async def login(body: LoginIn, request: Request, session: DbSession) -> JSONResponse:
    await sys_ctx(session, "identity.login")
    info = ss.client_info(request)
    # email, mobile number or username (identity_0006), case-insensitive
    ident = classify_login_identifier(body.identifier)
    kind, value = ident or ("email", body.identifier.strip().lower())
    digests = identifier_digests(kind, value)
    record_id = identifier_digest(kind, value)

    # Pre-auth gates (never count toward the account's failure counter).
    if await ss.ip_failures_exceeded(session, info.ip):
        await ss.record_login_attempt(
            session,
            identifier=record_id,
            user_id=None,
            outcome="throttled",
            info=info,
            pre_auth_blocked=True,
            failure_reason="ip_window",
        )
        return problem_response(
            ProblemError("throttled", headers={"Retry-After": "600"}, retry_after_seconds=600)
        )
    wait = await ss.backoff_remaining(session, digests)
    if wait:
        await ss.record_login_attempt(
            session,
            identifier=record_id,
            user_id=None,
            outcome="throttled",
            info=info,
            pre_auth_blocked=True,
            failure_reason="account_backoff",
        )
        return problem_response(
            ProblemError("throttled", headers={"Retry-After": str(wait)}, retry_after_seconds=wait)
        )

    user = await ids.find_user(session, kind, value) if ident else None
    cred = await ids.get_credential(session, user.id) if user else None
    ok = await ids.check_password(cred, body.password)
    # TD_SIMPLE_AUTH: no "sign-in paused, reset your password" hard lock (the reset email may not
    # be connected); the IP / per-account back-off throttling above still applies.
    simple = get_settings().simple_auth
    blocked = user is not None and (
        user.status in ("deactivated", "deleted") or (cred is not None and cred.hard_locked_at and not simple)
    )
    if not ok or user is None or cred is None or blocked:
        fail_outcome = "unknown_identifier" if user is None else ("locked" if blocked else "bad_credentials")
        if user is not None and cred is not None and not ok and not blocked:
            cred.consecutive_failures += 1
            limit = int(await get_policy(session, "login.hard_disable_after_failures"))
            if cred.consecutive_failures >= limit and cred.hard_locked_at is None and not simple:
                cred.hard_locked_at = clock.now()
                await audit(
                    session,
                    AuditActor.system("identity.login"),
                    "auth.account.hard_disabled",
                    "user",
                    user.id,
                    subject_user_id=user.id,
                    ip=info.ip,
                    after={"consecutive_failures": cred.consecutive_failures},
                )
                if user.email:
                    await send_email(
                        user.email,
                        "Sign-in paused on your Tech Drona account",
                        "We paused password sign-in after many failed attempts. "
                        "Reset your password to continue: "
                        f"{web_link('forgot_password')}",
                        template_key="auth.hard_disabled",
                    )
        await ss.record_login_attempt(
            session, identifier=record_id, user_id=user.id if user else None, outcome=fail_outcome, info=info
        )
        return problem_response(ProblemError("invalid_credentials"))

    cred.consecutive_failures = 0
    await ids.maybe_rehash(cred, body.password)
    from app.modules.rbac.service import active_grants, tier_for

    tier = tier_for(await active_grants(session, user.id))
    restriction = await lookup_restriction(session, user.id, user.restriction_level)
    if restriction.takeover_lock:
        await ss.record_login_attempt(
            session, identifier=record_id, user_id=user.id, outcome="restricted", info=info
        )
        return problem_response(
            ProblemError("account_protect_locked", recovery_url=web_path("forgot_password"))
        )
    device, raw_dev, _issued = await ss.resolve_device(session, info)
    ud = await ss.ensure_user_device(session, user.id, device)
    s, token = await ss.create_session(
        session,
        user_id=user.id,
        tier=tier,
        status="pending_mfa",
        created_via="password",
        info=info,
        device=device,
        user_device=ud,
        amr=["pwd"],
        restriction_level=restriction.level,
    )
    outcome = await advance(
        session,
        s=s,
        user=user,
        ud=ud,
        device=device,
        restriction=restriction,
        remember_requested=body.remember_device,
        token=token,
        info=info,
        rotate_on_activate=False,
    )
    result = outcome.body.get("result")
    la_outcome = {"authenticated": "success", "mfa_required": "mfa_required"}.get(
        str(result), "device_otp_required" if s.status == "pending_device_otp" else "success"
    )
    await ss.record_login_attempt(
        session,
        identifier=record_id,
        user_id=user.id,
        outcome=la_outcome,
        info=info,
        device_id=device.id,
        auth_session_id=s.id,
    )
    request.state.login_session_id = s.id
    return _respond(outcome, [ss.device_cookie(raw_dev)])


# =========================================================================== Google sign-in (Firebase Auth)

# docs/firebase/MIGRATION-PLAN.md §5.1. Students only (owner default for F3): staff keep
# password + TOTP. Login needs a fresh Google sign-in (auth_time); completing a new account
# allows time to fill in the details form.
GOOGLE_LOGIN_MAX_AUTH_AGE = timedelta(minutes=5)
GOOGLE_SIGNUP_MAX_AUTH_AGE = timedelta(minutes=30)
AUTH_LIMITS["auth29_google_ip"] = (rl.Rule(30, rl.HOUR),)


def _google_problem(code: str, status: int, title: str, detail: str, **ext: Any) -> JSONResponse:
    return problem_response(ProblemError(code, status, title, detail, **ext))


def _google_token_invalid() -> JSONResponse:
    return _google_problem(
        "google_token_invalid",
        401,
        "Google sign-in could not be verified",
        "Please try signing in with Google again.",
    )


async def _claim_unverified_account(session: AsyncSession, user: User, info: ss.ClientInfo) -> None:
    """An LMS account with this email exists but its email was never verified. Google proves
    the person controls the address, so the pending account becomes theirs: the email is
    marked verified, and the password, sessions and devices set up before verification are
    removed (stops pre-hijacking: someone who registered the address first cannot keep a way
    in)."""
    now = clock.now()
    cred = await ids.get_credential(session, user.id)
    had_password = cred is not None
    if cred is not None:
        if ids._fs():
            await ids._repo().delete_credential(user.id)
            fs_uow.discard(cred)
        else:
            await session.delete(cred)
    revoked = await ss.revoke_all_sessions(session, user.id, "password_changed")
    await spub.remove_user_devices(session, user.id, reason="security_action", now=now)
    user.email_verified_at = now
    if user.status == "pending_verification":
        user.status = "active"
    await fs_uow.flush(session)
    await audit(
        session,
        AuditActor.system("identity.login_google"),
        "identity.link.google",
        "user",
        user.id,
        subject_user_id=user.id,
        ip=info.ip,
        after={"claimed_unverified": True, "password_removed": had_password, "sessions_revoked": revoked},
    )


async def _google_signup(
    session: AsyncSession, request: Request, info: ss.ClientInfo, email: str, body: GoogleSignupIn
) -> User:
    """AUTH-01 rules for a new student account created from Google (email already verified)."""
    await _limit("auth01_signup_contact", _contact_key("email", email))
    today = ist_date(clock.now())
    age = ids.age_on(body.date_of_birth, today)
    if body.date_of_birth > today or age > 120:
        raise _vf("signup.date_of_birth", "invalid_date_of_birth", "Enter a valid date of birth")
    is_minor = age < 18
    granted = {c.purpose for c in body.consents if c.granted}
    missing = [p for p in ids.REQUIRED_AT_SIGNUP if p not in granted]
    if missing:
        raise ProblemError("consent_required", purposes=missing, notice_version=NOTICE_VERSION_DEFAULT)
    if is_minor and body.guardian is None:
        raise _vf(
            "signup.guardian", "guardian_required", "A parent or guardian is needed for under-18 accounts"
        )
    g_email = normalize_email(body.guardian.email) if body.guardian and body.guardian.email else None
    g_phone = normalize_phone(body.guardian.phone) if body.guardian and body.guardian.phone else None
    if is_minor and not (g_email or g_phone):
        raise _vf(
            "signup.guardian.email", "guardian_contact_required", "Guardian email or mobile is required"
        )
    now = clock.now()
    uid = uuid7()
    user = User(
        id=uid,
        email=email,
        email_verified_at=now,
        status="pending_guardian_consent" if is_minor else "active",
        is_minor=is_minor,
        age_verified_at=now,
        age_verification_method="self_declared",
        account_origin="sso",
    )
    await _create_user(
        session,
        user,
        UserProfile(user_id=uid, full_name=body.full_name.strip(), date_of_birth=body.date_of_birth),
    )
    await _record_signup_consents(
        session, uid, body.consents, is_minor, ip=info.ip, user_agent=request.headers.get("user-agent")
    )
    if is_minor and body.guardian:
        await _start_guardian_consent(
            session, uid, body.full_name, body.guardian, g_email, g_phone, ip=info.ip
        )
    await audit(
        session,
        AuditActor("user", user_id=uid),
        "identity.user.signed_up",
        "user",
        uid,
        subject_user_id=uid,
        ip=info.ip,
        after={"is_minor": is_minor, "status": user.status, "method": "google"},
    )
    await _emit(
        session,
        "identity.user_registered",
        {"user_id": str(uid), "is_minor": is_minor},
        aggregate_type="user",
        aggregate_id=uid,
    )
    return user


@pub.post("/login/google")
async def login_google(body: GoogleLoginIn, request: Request, session: DbSession) -> JSONResponse:
    """Sign in (or finish creating a student account) with a Firebase Auth Google ID token.

    Same response shape and pipeline as AUTH-06 ``/auth/login`` (risk gates, login_attempts,
    device verification, restrictions, session cap, ``td_session`` cookie, audit). Errors:
    ``google_token_invalid`` 401, ``google_signin_not_allowed`` 403 (staff),
    ``google_signup_required`` 409 (no account yet: resend with ``signup`` details and a fresh
    token), ``google_signin_unavailable`` 503 (not configured / switched off)."""
    await sys_ctx(session, "identity.login")
    info = ss.client_info(request)
    if info.ip:
        await _limit("auth29_google_ip", info.ip)
    configured = google.get_verifier()
    if configured is None:
        return _google_problem(
            "google_signin_unavailable",
            503,
            "Google sign-in is not available",
            "Sign in with your email and password instead.",
        )
    verifier, project_id = configured
    try:
        claims = await verifier.verify(body.id_token)
        ident = google.identity_from_claims(
            claims,
            project_id=project_id,
            now=clock.now(),
            max_auth_age=GOOGLE_SIGNUP_MAX_AUTH_AGE if body.signup else GOOGLE_LOGIN_MAX_AUTH_AGE,
        )
    except google.TokenRejected as e:
        google.log.info("google_token_rejected", reason=e.reason)
        return _google_token_invalid()
    if not await google.claim_token_once(body.id_token):
        google.log.info("google_token_rejected", reason="replayed")
        return _google_token_invalid()
    email = normalize_email(ident.email)
    if not email:
        return _google_token_invalid()
    digests = identifier_digests("email", email)
    record_id = identifier_digest("email", email)

    if await ss.ip_failures_exceeded(session, info.ip):
        await ss.record_login_attempt(
            session,
            identifier=record_id,
            user_id=None,
            outcome="throttled",
            info=info,
            method="sso",
            pre_auth_blocked=True,
            failure_reason="ip_window",
        )
        return problem_response(
            ProblemError("throttled", headers={"Retry-After": "600"}, retry_after_seconds=600)
        )
    wait = await ss.backoff_remaining(session, digests)
    if wait:
        await ss.record_login_attempt(
            session,
            identifier=record_id,
            user_id=None,
            outcome="throttled",
            info=info,
            method="sso",
            pre_auth_blocked=True,
            failure_reason="account_backoff",
        )
        return problem_response(
            ProblemError("throttled", headers={"Retry-After": str(wait)}, retry_after_seconds=wait)
        )

    from app.modules.rbac.service import active_grants, tier_for

    user = await ids.find_user(session, "email", email)
    new_account = False
    if user is None:
        if body.signup is None:
            return _google_problem(
                "google_signup_required",
                409,
                "Finish creating your account",
                "Tell us a few details to create your Tech Drona account.",
                suggested_name=ident.name,
                required_consents=list(ids.REQUIRED_AT_SIGNUP),
                notice_version=NOTICE_VERSION_DEFAULT,
            )
        user = await _google_signup(session, request, info, email, body.signup)
        new_account = True
    else:
        if user.status in ("deactivated", "deleted"):
            await ss.record_login_attempt(
                session, identifier=record_id, user_id=user.id, outcome="locked", info=info, method="sso"
            )
            return problem_response(ProblemError("invalid_credentials"))
        # Staff may use Google instead of their password only when the owner turned on
        # TD_GOOGLE_SIGNIN_STAFF (central login). Google replaces the password step only: advance()
        # below still demands the staff MFA factor (or MFA enrolment), exactly as after a password.
        if (
            tier_for(await active_grants(session, user.id)) != "student"
            and not get_settings().TD_GOOGLE_SIGNIN_STAFF
        ):
            await ss.record_login_attempt(
                session,
                identifier=record_id,
                user_id=user.id,
                outcome="restricted",
                info=info,
                method="sso",
                failure_reason="google_staff",
            )
            return _google_problem(
                "google_signin_not_allowed",
                403,
                "Use your password to sign in",
                "Staff accounts sign in with email, password and an authenticator code.",
            )
        if user.email_verified_at is None:
            await _claim_unverified_account(session, user, info)

    tier = tier_for(await active_grants(session, user.id))
    restriction = await lookup_restriction(session, user.id, user.restriction_level)
    if restriction.takeover_lock:
        await ss.record_login_attempt(
            session, identifier=record_id, user_id=user.id, outcome="restricted", info=info, method="sso"
        )
        return problem_response(
            ProblemError("account_protect_locked", recovery_url=web_path("forgot_password"))
        )
    device, raw_dev, _issued = await ss.resolve_device(session, info)
    ud = await ss.ensure_user_device(session, user.id, device)
    s, token = await ss.create_session(
        session,
        user_id=user.id,
        tier=tier,
        status="pending_mfa",
        created_via="sso",
        info=info,
        device=device,
        user_device=ud,
        amr=["google"],
        auth_time=ident.auth_time,
        restriction_level=restriction.level,
    )
    outcome = await advance(
        session,
        s=s,
        user=user,
        ud=ud,
        device=device,
        restriction=restriction,
        remember_requested=body.remember_device,
        token=token,
        info=info,
        rotate_on_activate=False,
    )
    result = outcome.body.get("result")
    la_outcome = {"authenticated": "success", "mfa_required": "mfa_required"}.get(
        str(result), "device_otp_required" if s.status == "pending_device_otp" else "success"
    )
    await ss.record_login_attempt(
        session,
        identifier=record_id,
        user_id=user.id,
        outcome=la_outcome,
        info=info,
        method="sso",
        device_id=device.id,
        auth_session_id=s.id,
    )
    await audit(
        session,
        AuditActor("user", user_id=user.id, session_id=s.id),
        "identity.login.google",
        "auth_session",
        s.id,
        subject_user_id=user.id,
        ip=info.ip,
        after={"result": str(result), "new_account": new_account},
    )
    if outcome.problem is None:
        outcome.body["new_account"] = new_account
    request.state.login_session_id = s.id
    return _respond(outcome, [ss.device_cookie(raw_dev)])


# =========================================================================== login continuation


async def _pending_context(
    session: AsyncSession, request: Request
) -> tuple[AuthSession, User, UserDevice | None, Device | None]:
    s = await _current_session(session, request)
    user = await _user(session, s.user_id)
    ud = await ss.get_user_device_by_id(session, s.user_device_id) if s.user_device_id else None
    device = await spub.get_device(session, s.device_id) if s.device_id else None
    return s, user, ud, device


@lc.post("/mfa/verify")
async def mfa_verify(body: MfaVerifyIn, request: Request, session: PrincipalDbSession) -> JSONResponse:
    s, user, ud, device = await _pending_context(session, request)
    if s.status != "pending_mfa":
        raise ProblemError("invalid_state_transition", current_state=s.status, allowed=[])
    info = ss.client_info(request)
    if await ids.mfa_failures_recent(session, user.id) >= 5:
        return problem_response(ProblemError("otp_attempts_exceeded"))
    if body.method == "totp":
        verdict = await ids.check_totp_code(session, user.id, body.code)
        if verdict == "replayed":  # E2E-12: refused, but not an MFA failure (no TO-03/lockout)
            return problem_response(totp_replay_problem())
        ok = verdict == "ok"
    else:
        ok = await ids.verify_recovery_code(session, user.id, body.code)
    ident = await _login_identifier(user)
    mfa_method = "totp" if body.method == "totp" else "recovery_code"
    if not ok:
        await ss.record_login_attempt(
            session,
            identifier=ident,
            user_id=user.id,
            outcome="mfa_failed",
            info=info,
            mfa_method=mfa_method,
            auth_session_id=s.id,
        )
        return problem_response(ProblemError("otp_invalid", attempts_remaining=None))
    s.amr = [*s.amr, mfa_method]
    s.aal = 2
    s.last_step_up_at = clock.now()
    if user.email:  # successful MFA login clears a hard-disable counter (FR-IDN-009)
        cred = await ids.get_credential(session, user.id)
        if cred:
            cred.consecutive_failures = 0
    token = await ss.rotate_token(session, s)
    restriction = await lookup_restriction(session, user.id, user.restriction_level)
    outcome = await advance(
        session,
        s=s,
        user=user,
        ud=ud,
        device=device,
        restriction=restriction,
        remember_requested=False,
        token=token,
        info=info,
        rotate_on_activate=False,
    )
    if outcome.body.get("result") == "authenticated":
        await ss.record_login_attempt(
            session,
            identifier=ident,
            user_id=user.id,
            outcome="success",
            info=info,
            mfa_method=mfa_method,
            auth_session_id=s.id,
        )
    return _respond(outcome)


@lc.post("/device-verification/send")
async def device_verification_send(
    body: DeviceSendIn, request: Request, session: PrincipalDbSession
) -> JSONResponse:
    s, user, _ud, _device = await _pending_context(session, request)
    if s.status != "pending_device_otp":
        raise ProblemError("invalid_state_transition", current_state=s.status, allowed=[])
    if body.channel == "sms":
        if not (user.phone_e164 and user.phone_verified_at):
            raise _vf("channel", "channel_unavailable", "No verified mobile number")
        dest = user.phone_e164
    else:
        if not user.email:
            raise _vf("channel", "channel_unavailable", "No email address")
        dest = user.email
    async with sys_scope(session, "identity.device_otp"):
        wait = await ids.otp_send_allowed(session, body.channel, dest)
        if wait:
            return problem_response(ProblemError("otp_send_limited", headers={"Retry-After": str(wait)}))
        _, code = await ids.create_otp(
            session,
            user_id=user.id,
            purpose="new_device_otp",
            channel=body.channel,
            destination=dest,
            auth_session_id=s.id,
            device_id=s.device_id,
            ip=ss.client_info(request).ip,
        )
    text = f"{code} is your Tech Drona code to verify a new device. It expires in 5 minutes. Never share it."
    if body.channel == "sms":
        await send_sms(dest, text, template_key="otp")
        masked = mask_phone(dest)
    else:
        await send_email(dest, "Verify your new device", text, template_key="auth.new_device_otp")
        masked = mask_email(dest)
    return JSONResponse(
        {"sent_to": masked, "expires_in_seconds": int(await get_policy(session, "otp.ttl_seconds"))}
    )


@lc.post("/device-verification/verify")
async def device_verification_verify(
    body: DeviceVerifyIn, request: Request, session: PrincipalDbSession
) -> JSONResponse:
    s, user, ud, device = await _pending_context(session, request)
    if s.status != "pending_device_otp" or ud is None:
        raise ProblemError("invalid_state_transition", current_state=s.status, allowed=[])
    info = ss.client_info(request)
    token = request.state.session_token
    method = ud.verification_method if ud.verification_method and ud.trust_status == "pending_otp" else None
    if method is None:
        if not body.code:
            raise _vf("code", "required", "Enter the code")
        if body.method == "totp":
            verdict = await ids.check_totp_code(session, user.id, body.code)
            if verdict == "replayed":
                return problem_response(totp_replay_problem())
            if verdict != "ok":
                return problem_response(ProblemError("otp_invalid", attempts_remaining=None))
            method = "totp"
        else:
            async with sys_scope(session, "identity.device_otp"):
                chk = await ids.check_otp(
                    session, purpose="new_device_otp", code=body.code, auth_session_id=s.id
                )
            if not chk.ok:
                assert chk.problem is not None
                return problem_response(chk.problem)
            assert chk.token is not None
            method = "sms_otp" if chk.token.channel == "sms" else "email_otp"
        ud.verification_method = method  # this pending login passed verification
        await fs_uow.flush(session)
    if body.remove_user_device_id is not None:
        problem = await free_device_slot(session, user, body.remove_user_device_id, ud)
        if problem is not None:
            return problem_response(problem)
    problem = await trust_current_device(
        session, user, ud, method, owner_verified=method in ("sms_otp", "totp")
    )
    if problem is not None:
        return _respond(LoginOutcome(problem.status, {}, [ss.session_cookie(s, token)], problem))
    await audit(
        session,
        AuditActor("user", user_id=user.id, session_id=s.id),
        "session.device.trusted",
        "user_device",
        ud.id,
        subject_user_id=user.id,
        ip=info.ip,
        after={"method": method},
    )
    if method == "totp":
        s.amr = [*s.amr, "totp"]
    else:
        s.amr = [*s.amr, "otp_sms" if method == "sms_otp" else "otp_email"]
    restriction = await lookup_restriction(session, user.id, user.restriction_level)
    outcome = await advance(
        session,
        s=s,
        user=user,
        ud=ud,
        device=device,
        restriction=restriction,
        remember_requested=False,
        token=token,
        info=info,
    )
    return _respond(outcome)


@lc.post("/session-choice")
async def session_choice(
    body: SessionChoiceIn, request: Request, session: PrincipalDbSession
) -> JSONResponse:
    s, user, ud, device = await _pending_context(session, request)
    if s.status != "pending_session_choice":
        raise ProblemError("invalid_state_transition", current_state=s.status, allowed=[])
    info = ss.client_info(request)
    if body.cancel:
        await ss.end_session(session, s, status="revoked", reason="user_logout", ended_by=user.id)
        return JSONResponse({"result": "cancelled"})
    if body.end_session_id is None:
        raise _vf("end_session_id", "required", "Choose a session to end")
    target = await spub.get_session(session, body.end_session_id)
    if target is not None and (target.user_id != user.id or target.status != "active" or target.id == s.id):
        target = None
    if target is None:
        raise ProblemError("not_found")
    if (
        target.id in await ss.sessions_with_attempts(session, [target.id])
        and not body.confirm_attempt_session
    ):
        raise ProblemError(
            "invalid_state_transition",
            current_state="has_active_attempt",
            allowed=["confirm_attempt_session"],
        )
    await ss.end_session(session, target, status="revoked", reason="session_cap_evicted", ended_by=user.id)
    await notify(
        session,
        user.id,
        "session.revoked",
        category="security",
        data={"end_reason": "session_cap_evicted", "session_id": str(target.id)},
    )
    await audit(
        session,
        AuditActor("user", user_id=user.id, session_id=s.id),
        "session.evicted_by_choice",
        "auth_session",
        target.id,
        subject_user_id=user.id,
        ip=info.ip,
    )
    restriction = await lookup_restriction(session, user.id, user.restriction_level)
    outcome = await advance(
        session,
        s=s,
        user=user,
        ud=ud,
        device=device,
        restriction=restriction,
        remember_requested=False,
        token=request.state.session_token,
        info=info,
    )
    return _respond(outcome)


@lc.post("/logout", openapi_extra={"x-td-idle": "neutral"})
async def logout(
    request: Request, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> JSONResponse:
    s = await _current_session(session, request)
    await ss.end_session(session, s, status="revoked", reason="user_logout", ended_by=principal.user_id)
    await audit(session, principal, "auth.logout", "auth_session", s.id, subject_user_id=principal.user_id)
    resp = JSONResponse({"result": "logged_out"})
    resp.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    resp.headers.append("set-cookie", ss.cookie_header(ss.SESSION_COOKIE, "", 0))
    raw_dev = getattr(request.state, "device_token", None)
    if raw_dev:
        resp.headers.append("set-cookie", ss.device_cookie(raw_dev))
    return resp


# =========================================================================== AUTH-16/17/18 passwords


async def issue_password_reset(
    session: AsyncSession, user: User, *, ip: str | None, actor: Principal | AuditActor | None = None
) -> bool:
    """Send a password-reset link (≤ 3 per hour per user). Never sets a password. Used by
    AUTH-16 and by support (SUP-13). Returns False when rate-limited or no email."""
    if not user.email or user.status == "deleted":
        return False
    if ids._fs():
        recent = len(
            await ipub.reset_tokens_of(session, user.id, created_after=clock.now() - timedelta(hours=1))
        )
    else:
        recent = (
            await session.execute(
                select(func.count()).where(
                    PasswordResetToken.user_id == user.id,
                    PasswordResetToken.created_at > clock.now() - timedelta(hours=1),
                )
            )
        ).scalar_one()
    if recent >= 3:
        return False
    raw = ss.generate_token()
    ttl = int(await get_policy(session, "auth.password_reset_ttl_minutes"))
    await _insert(
        session,
        PasswordResetToken(
            id=uuid7(),
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=clock.now() + timedelta(minutes=ttl),
            requested_ip=ip,
            created_at=clock.now(),
        ),
    )
    await send_email(
        user.email,
        "Reset your Tech Drona password",
        f"Reset your password: {web_link('reset_password', token=raw)}\n\n"
        f"This link expires in {ttl} minutes "
        "and can be used once. If you didn't ask for this, ignore this email.",
        template_key="auth.password_reset",
    )
    await audit(
        session,
        actor or AuditActor.system("identity.password_reset"),
        "auth.password.reset_requested",
        "user",
        user.id,
        subject_user_id=user.id,
        ip=ip,
    )
    return True


async def send_verification_email(session: AsyncSession, user: User, ip: str | None) -> None:
    """Public wrapper for support (SUP-12)."""
    await _send_verification_email(session, user, ip)


@pub.post("/password/forgot", status_code=202)
async def password_forgot(body: ForgotIn, request: Request, session: DbSession) -> dict[str, str]:
    await sys_ctx(session, "identity.password_reset")
    info = ss.client_info(request)
    await _limit("auth16_forgot_ip", info.ip)
    ident = classify_identifier(body.identifier)
    kind, value = ident or ("email", body.identifier.strip().lower())
    await _limit("auth16_forgot_identifier", _contact_key(kind, value))
    user = await ids.find_user(session, *ident) if ident else None
    if user is not None:
        await issue_password_reset(session, user, ip=info.ip)
    return {"status": "accepted", "detail": "If an account exists, we've sent instructions."}


@pub.post("/password/reset")
async def password_reset(body: ResetIn, request: Request, session: DbSession) -> dict[str, str]:
    await _limit("auth17_reset_ip", ss.client_info(request).ip)
    await sys_ctx(session, "identity.password_reset")
    if ids._fs():
        tok = await ids._repo().reset_token_by_hash(hash_token(body.token))
    else:
        tok = (
            await session.execute(
                select(PasswordResetToken)
                .where(PasswordResetToken.token_hash == hash_token(body.token))
                .with_for_update()
            )
        ).scalar_one_or_none()
    if tok is None or tok.consumed_at is not None or tok.expires_at <= clock.now():
        raise _vf("token", "invalid_or_expired", "This reset link is invalid, used or expired")
    user = await _user(session, tok.user_id)
    has_mfa = await ids.has_strong_factor(session, user.id)
    probs = password_problems(
        body.new_password, has_mfa=has_mfa, context=tuple(x for x in ((user.email or "").split("@")[0],) if x)
    )
    if probs:
        raise _vf("new_password", probs[0], "Choose a longer or less common password")
    # A reset must set a different password (owner rule; E2E-12 / RE §T-protect: after a
    # protective lock the old one is presumed known to an attacker). The token is not consumed,
    # so the learner can pick another password with the same link.
    if await ids.check_password(await ids.get_credential(session, user.id), body.new_password):
        raise _vf(
            "new_password",
            "password_reuse_not_allowed",
            "Choose a new password that is different from your current one",
        )
    if ids._fs():
        # single use under concurrency (Postgres: the FOR UPDATE row lock above)
        if not await ids._repo().claim_reset_token(tok.id):
            raise _vf("token", "invalid_or_expired", "This reset link is invalid, used or expired")
        fs_uow.discard(tok)
    else:
        tok.consumed_at = clock.now()
    await ids.set_password(session, user.id, body.new_password)
    revoked = await ss.revoke_all_sessions(session, user.id, "password_changed")
    info = ss.client_info(request)
    await audit(
        session,
        AuditActor("user", user_id=user.id),
        "auth.password.reset",
        "user",
        user.id,
        subject_user_id=user.id,
        ip=info.ip,
        after={"sessions_revoked": revoked},
    )
    await notify(
        session,
        user.id,
        "security.password_changed",
        category="security",
        channels=("in_app", "email"),
        email_to=user.email,
        email_subject="Your Tech Drona password was changed",
        email_text="Your password was reset and you were signed out everywhere. "
        "If this wasn't you, contact support immediately.",
    )
    return {"result": "password_reset", "next": "login"}


@dflt.post("/auth/password/change")
async def password_change(
    body: ChangePasswordIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    # SEC-03 / AUTH-18 "5/h per user": bounds current-password guessing by a session holder.
    await _limit("auth18_change_user", str(principal.user_id))
    user = await _user(session, principal.user_id)
    cred = await ids.get_credential(session, user.id)
    if not await ids.check_password(cred, body.current_password):
        return problem_response(ProblemError("invalid_credentials"))
    probs = password_problems(
        body.new_password,
        has_mfa=principal.mfa_level != "none",
        context=tuple(x for x in ((user.email or "").split("@")[0], body.current_password) if x),
    )
    if probs:
        raise _vf("new_password", probs[0], "Choose a longer or less common password")
    await ids.set_password(session, user.id, body.new_password)
    s = await _current_session(session, request)
    revoked = 0
    if body.revoke_other_sessions:
        revoked = await ss.revoke_all_sessions(
            session, user.id, "password_changed", ended_by=user.id, except_session_id=s.id
        )
    token = await ss.rotate_token(session, s)
    await audit(
        session,
        principal,
        "auth.password.changed",
        "user",
        user.id,
        subject_user_id=user.id,
        after={"other_sessions_revoked": revoked},
    )
    resp = JSONResponse({"result": "password_changed", "other_sessions_revoked": revoked})
    resp.headers.append("set-cookie", ss.session_cookie(s, token))
    return resp


# =========================================================================== AUTH-19/20 step-up


async def _step_up_methods(session: AsyncSession, principal: Principal, user: User) -> list[str]:
    """Spec §1.6 / AUTH-19: passkey (not built), TOTP; students also SMS and email OTP.

    SEC-09: ``password`` is not a step-up method. It remains only as the documented fallback
    for a student account that has no other usable method (no TOTP, no email and no verified
    mobile — e.g. a mobile-only signup before the number is verified)."""
    methods = []
    if await ids.has_strong_factor(session, user.id):
        methods.append("totp")
    if principal.tier == "student":
        if user.email:
            methods.append("email_otp")
        if user.phone_e164 and user.phone_verified_at:
            methods.append("sms_otp")
        if not methods:
            methods.append("password")
    if not methods:
        # TD_MFA_EXEMPT_EMAILS (demo owner override, never in production) signs in with a password
        # only and has no TOTP; without this it could never confirm a step-up (approvals, revokes).
        from app.core.config import get_settings as _settings

        if _settings().mfa_exempt(user.email):
            methods.append("password")
    return methods


@acct.post("/auth/step-up/options", openapi_extra={"x-td-idle": "neutral"})
async def step_up_options(
    body: StepUpOptionsIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    await _limit("auth19_options_user", str(principal.user_id))
    user = await _user(session, principal.user_id)
    methods = await _step_up_methods(session, principal, user)
    out: dict[str, Any] = {"allowed_methods": methods, "purpose": body.purpose}
    if body.send_otp_via:
        want = f"{body.send_otp_via}_otp"
        if want not in methods:
            raise _vf("send_otp_via", "method_not_allowed_for_tier", "This method is not available")
        dest = user.email if body.send_otp_via == "email" else user.phone_e164
        assert dest is not None
        s = await _current_session(session, request)
        async with sys_scope(session, "identity.step_up"):
            wait = await ids.otp_send_allowed(session, body.send_otp_via, dest)
            if wait:
                return problem_response(ProblemError("otp_send_limited", headers={"Retry-After": str(wait)}))
            _, code = await ids.create_otp(
                session,
                user_id=user.id,
                purpose="step_up_otp",
                channel=body.send_otp_via,
                destination=dest,
                auth_session_id=s.id,
            )
        text = f"{code} is your Tech Drona confirmation code. Never share it."
        if body.send_otp_via == "sms":
            await send_sms(dest, text, template_key="otp")
        else:
            await send_email(dest, "Confirm it's you", text, template_key="auth.step_up_otp")
        out["sent_to"] = mask_phone(dest) if body.send_otp_via == "sms" else mask_email(dest)
    return JSONResponse(out)


@acct.post("/auth/step-up")
async def step_up(
    body: StepUpIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    user = await _user(session, principal.user_id)
    s = await _current_session(session, request)
    info = ss.client_info(request)
    if body.method not in await _step_up_methods(session, principal, user):
        raise _vf("method", "method_not_allowed_for_tier", "This method is not allowed for your account")
    if await ids.mfa_failures_recent(session, user.id) >= 5:
        return problem_response(ProblemError("otp_attempts_exceeded"))
    ok = False
    if body.method == "totp":
        verdict = await ids.check_totp_code(session, user.id, body.code or "")
        if verdict == "replayed":  # E2E-12: a reused valid code is refused, not counted as a failure
            return problem_response(totp_replay_problem())
        ok = verdict == "ok"
    elif body.method == "password":
        ok = await ids.check_password(await ids.get_credential(session, user.id), body.password or "")
    else:
        async with sys_scope(session, "identity.step_up"):
            chk = await ids.check_otp(
                session, purpose="step_up_otp", code=body.code or "", auth_session_id=s.id
            )
        if not chk.ok:
            await ss.record_login_attempt(
                session,
                identifier=await _login_identifier(user),
                user_id=user.id,
                outcome="mfa_failed",
                info=info,
                mfa_method=body.method,
                auth_session_id=s.id,
            )
            assert chk.problem is not None
            return problem_response(chk.problem)
        ok = True
    if not ok:
        mfa_method = body.method if body.method in ("totp", "email_otp", "sms_otp") else None
        await ss.record_login_attempt(
            session,
            identifier=await _login_identifier(user),
            user_id=user.id,
            outcome="mfa_failed",
            info=info,
            mfa_method=mfa_method,
            auth_session_id=s.id,
        )
        return problem_response(ProblemError("otp_invalid", attempts_remaining=None))
    s.last_step_up_at = clock.now()
    amr_tag = {"totp": "totp", "password": "pwd", "email_otp": "otp_email", "sms_otp": "otp_sms"}[body.method]
    if amr_tag not in s.amr:
        s.amr = [*s.amr, amr_tag]
    await audit(
        session,
        principal,
        "auth.step_up.succeeded",
        "auth_session",
        s.id,
        subject_user_id=user.id,
        after={"method": body.method},
    )
    return JSONResponse(
        {
            "last_step_up_at": to_rfc3339(s.last_step_up_at),
            "valid_for_seconds": {"privileged_action": 300, "staff_action": 600, "student_action": 900},
        }
    )


# =========================================================================== AUTH-25/26/27 guardian consent


async def _guardian_link(
    session: AsyncSession, token: str
) -> tuple[VerificationToken, GuardianConsent, User]:
    tok = await ids.consume_link_token(session, token, "guardian_verify")
    if tok is None or tok.user_id is None:
        raise ProblemError("not_found")
    if ids._fs():
        gc = await ids._repo().latest_guardian_consent(tok.user_id)
    else:
        gc = (
            await session.execute(
                select(GuardianConsent)
                .where(GuardianConsent.child_user_id == tok.user_id)
                .order_by(GuardianConsent.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    child = await ipub.get_user(session, tok.user_id)
    if gc is None or child is None:
        raise ProblemError("not_found")
    return tok, gc, child


@pub.get("/guardian-consent/{token}")
async def guardian_view(token: str, session: DbSession) -> dict[str, Any]:
    await sys_ctx(session, "identity.guardian")
    _tok, gc, child = await _guardian_link(session, token)
    prof = await ipub.get_profile(session, child.id)
    first = prof.full_name.split()[0] if prof and prof.full_name else "Your child"
    return {
        "child_first_name": first,
        "status": gc.status,
        "relationship": gc.relationship,
        "notice_version": NOTICE_VERSION_DEFAULT,
        "items": [
            {"purpose": "core_service", "item": "A", "required": True},
            {"purpose": "assessment_integrity", "item": "G", "required": False},
        ],
        "unavailable_for_minors": sorted(ids.MINOR_FORBIDDEN),
        "contact_masked": mask_email(gc.guardian_email)
        if gc.guardian_email
        else mask_phone(gc.guardian_phone_e164),
    }


@pub.post("/guardian-consent/{token}/verify-contact")
async def guardian_verify_contact(token: str, request: Request, session: DbSession) -> JSONResponse:
    await sys_ctx(session, "identity.guardian")
    _tok, gc, child = await _guardian_link(session, token)
    if gc.status != "pending":
        raise ProblemError("invalid_state_transition", current_state=gc.status, allowed=[])
    channel, dest = ("email", gc.guardian_email) if gc.guardian_email else ("sms", gc.guardian_phone_e164)
    assert dest is not None
    wait = await ids.otp_send_allowed(session, channel, dest)
    if wait:
        return problem_response(ProblemError("otp_send_limited", headers={"Retry-After": str(wait)}))
    _, code = await ids.create_otp(
        session,
        user_id=child.id,
        purpose="guardian_verify",
        channel=channel,
        destination=dest,
        auth_session_id=gc.id,  # binding id: keeps the link token valid (see create_otp invalidation)
        ip=ss.client_info(request).ip,
    )
    text = f"{code} is your Tech Drona guardian verification code."
    if channel == "sms":
        await send_sms(dest, text, template_key="otp")
    else:
        await send_email(dest, "Your guardian verification code", text, template_key="auth.guardian_otp")
    return JSONResponse({"sent_to": mask_email(dest) if channel == "email" else mask_phone(dest)})


@pub.post("/guardian-consent/{token}/decision")
async def guardian_decision(
    token: str, body: GuardianDecisionIn, request: Request, session: DbSession
) -> JSONResponse:
    async def op() -> IdemResult:
        await sys_ctx(session, "identity.guardian")
        _tok, gc, child = await _guardian_link(session, token)
        if gc.status != "pending":
            raise ProblemError("invalid_state_transition", current_state=gc.status, allowed=[])
        chk = await ids.check_otp(
            session, purpose="guardian_verify", code=body.otp_code, user_id=child.id, auth_session_id=gc.id
        )
        if not chk.ok:
            # Returned (not raised) so the attempt counter is committed with the stored result.
            assert chk.problem is not None
            return IdemResult(body=chk.problem.to_body(get_request_id()), status=chk.problem.status)
        if body.decision == "consent" and not body.declaration:
            raise _vf("declaration", "required", "Please confirm you are the parent or legal guardian")
        now = clock.now()
        info = ss.client_info(request)
        if not await ids.mark_token_consumed(session, _tok):
            raise ProblemError("not_found")
        if body.decision == "consent":
            prof = await ipub.get_profile(session, child.id)
            gc.status = "verified"
            gc.verified_at = now
            gc.verification_ref = f"otp:{chk.token.id}" if chk.token else None
            gc.evidence_hash = hash_token(f"{gc.id}:{chk.token.id if chk.token else ''}:{now.isoformat()}")
            if prof and prof.date_of_birth:
                from datetime import UTC, datetime, time

                gc.expires_at = datetime.combine(ids.eighteenth_birthday(prof.date_of_birth), time(0), UTC)
            for purpose in ("terms", "privacy_notice", "core_service"):
                await ids.record_consent(
                    session,
                    child.id,
                    purpose,
                    "granted",
                    NOTICE_VERSION_DEFAULT,
                    ip=info.ip,
                    guardian_consent_id=gc.id,
                )
            if child.status == "pending_guardian_consent":
                child.status = (
                    "active"
                    if (child.email_verified_at or child.phone_verified_at)
                    else "pending_verification"
                )
        else:
            gc.status = "rejected"
        await audit(
            session,
            AuditActor("system", system_job="identity.guardian"),
            f"identity.guardian_consent.{gc.status}",
            "guardian_consent",
            gc.id,
            subject_user_id=child.id,
            ip=info.ip,
        )
        await _emit(
            session,
            "consent.changed",
            {"user_id": str(child.id), "guardian_consent": gc.status},
            aggregate_type="user",
            aggregate_id=child.id,
        )
        return IdemResult(body={"status": gc.status, "child_status": child.status})

    await sys_ctx(session, "identity.guardian")  # idempotency row has no user (RLS: platform)
    # NO_POSTGRES is falsy: the Firestore idempotency store then takes no Postgres savepoint
    return await idempotent(request, session or None, user_id=None, operation=op)  # type: ignore[arg-type]


# =========================================================================== AUTH-28 remember-device


@pub.post("/remember/refresh")
async def remember_refresh(body: RememberIn, request: Request, session: DbSession) -> JSONResponse:
    if not getattr(request.state, "service_authenticated", False):
        raise ProblemError("remember_invalid")
    await sys_ctx(session, "identity.remember")
    info = ss.client_info(request)
    await _limit("auth28_remember_device", hash_token(info.device_token).hex() if info.device_token else None)
    ud = await spub.user_device_by_remember(session, hash_token(body.remember_token), for_update=True)
    now = clock.now()
    if ud is None or ud.trust_status != "trusted" or ud.remember_until is None or now >= ud.remember_until:
        raise ProblemError("remember_invalid")
    if not await ss.device_hash_matches(session, ud.device_id, info.device_token):
        raise ProblemError("remember_invalid")
    user = await _user(session, ud.user_id)
    from app.modules.rbac.service import active_grants, tier_for

    restriction = await lookup_restriction(session, user.id, user.restriction_level)
    if (
        tier_for(await active_grants(session, user.id)) != "student"
        or restriction.level >= 3
        or restriction.takeover_lock
        or user.status in ("deactivated", "deleted")
        or (
            user.sessions_valid_after
            and ud.remember_issued_at
            and ud.remember_issued_at <= user.sessions_valid_after
        )
    ):
        raise ProblemError("remember_invalid")
    device = await spub.get_device(session, ud.device_id)
    days = int(await get_policy(session, "sessions.remember_device.max_days", user_id=user.id))
    original_auth = ud.remember_until - timedelta(days=days)
    s, token = await ss.create_session(
        session,
        user_id=user.id,
        tier="student",
        status="pending_mfa",
        created_via="remember_device",
        info=info,
        device=device,
        user_device=ud,
        amr=["remember"],
        aal=1,
        auth_time=original_auth,
        restriction_level=restriction.level,
    )
    s.amr = ["remember", "totp"] if await ids.has_strong_factor(session, user.id) else ["remember"]
    outcome = await advance(
        session,
        s=s,
        user=user,
        ud=ud,
        device=device,
        restriction=restriction,
        remember_requested=False,
        token=token,
        info=info,
        rotate_on_activate=False,
    )
    s.amr = ["remember"]
    s.aal = 1
    if outcome.body.get("result") == "authenticated":
        raw = ss.generate_token()  # rotate on every use; remember_until never slides
        ud.remember_token_hash = hash_token(raw)
        ud.remember_issued_at = now
        s.remember_device = True
        outcome.cookies.append(
            ss.cookie_header(ss.REMEMBER_COOKIE, raw, int((ud.remember_until - now).total_seconds()))
        )
        outcome.body["session"] = session_summary(s)
    await audit(
        session,
        AuditActor("user", user_id=user.id, session_id=s.id),
        "auth.remember.reissued",
        "auth_session",
        s.id,
        subject_user_id=user.id,
        ip=info.ip,
    )
    return _respond(outcome)


# =========================================================================== ME-01/02


@acct.get("/me", openapi_extra={"x-td-idle": "extends"})
async def me(
    request: Request, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    user = await _user(session, principal.user_id)
    prof = await ipub.get_profile(session, user.id)
    s = await _current_session(session, request)
    portals = sorted({g.role for g in principal.grants}) or ["student"]
    restriction: dict[str, Any] = {"level": principal.restriction_level}
    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "email_verified": user.email_verified_at is not None,
            "mobile_masked": mask_phone(user.phone_e164),
            "mobile_verified": user.phone_verified_at is not None,
            "status": user.status,
            "is_minor": user.is_minor,
            "privacy_tier": user.privacy_tier,
            "locale": user.locale,
            # true: every route but this one, password change and logout answers 403
            # password_change_required until the person chooses a new password.
            "must_change_password": user.must_change_password,
        },
        "profile": {
            "full_name": prof.full_name if prof else None,
            "display_name": prof.display_name if prof else None,
            "graduation_year": prof.graduation_year if prof else None,
            "branch": prof.branch if prof else None,
            "legal_name_locked": False,
        },
        "session": {
            **session_summary(s),
            "remember_device": s.remember_device,
            "last_step_up_at": to_rfc3339(s.last_step_up_at) if s.last_step_up_at else None,
        },
        "restriction": restriction,
        "mfa": {"level": principal.mfa_level},
        "portals": portals,
    }


@dflt.patch("/me/profile")
async def patch_profile(
    body: ProfilePatchIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    prof = await ipub.get_profile(session, principal.user_id)
    if prof is None:
        raise ProblemError("not_found")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if k == "full_name" and v is None:
            continue
        setattr(prof, k, v)
    await fs_uow.flush(session)
    await audit(
        session,
        principal,
        "identity.profile.updated",
        "user",
        principal.user_id,
        subject_user_id=principal.user_id,
        after={"fields": sorted(changes)},
    )
    return {"result": "updated", "fields": sorted(changes)}


# =========================================================================== ME-05/06 consents


@consent_r.get("/consents", openapi_extra={"x-td-idle": "neutral"})
async def get_consents(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    state = await ids.current_consents(session, principal.user_id)
    return {
        "data": [
            {
                "purpose": p,
                "state": state.get(p, {}).get("state", "not_granted"),
                "notice_version": state.get(p, {}).get("notice_version"),
                "effective_at": to_rfc3339(state[p]["effective_at"]) if p in state else None,
                "available": not (principal.is_minor and p in ids.MINOR_FORBIDDEN),
            }
            for p in ids.PURPOSES
        ],
        "notice_version": NOTICE_VERSION_DEFAULT,
    }


@consent_r.post("/consents", status_code=201)
async def change_consent(
    body: ConsentChangeIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    if body.action == "granted" and principal.is_minor and body.purpose in ids.MINOR_FORBIDDEN:
        raise ProblemError(
            "permission_denied", detail="Not available for under-18 accounts.", permission="consent.grant"
        )
    if body.action == "withdrawn" and body.purpose in ids.REQUIRED_AT_SIGNUP:
        raise ProblemError(
            "invalid_state_transition",
            current_state="required",
            allowed=["privacy_request_account_closure"],
            detail="Withdrawing this item closes your account; use the privacy centre.",
        )
    info = ss.client_info(request)
    c = await ids.record_consent(
        session,
        principal.user_id,
        body.purpose,
        body.action,
        body.notice_version,
        ip=info.ip,
        user_agent=request.headers.get("user-agent"),
        context_ref=body.context_ref,
    )
    await audit(
        session,
        principal,
        f"consent.{body.action}",
        "consent",
        c.id,
        subject_user_id=principal.user_id,
        after={"purpose": body.purpose, "notice_version": body.notice_version},
    )
    await _emit(
        session,
        "consent.changed",
        {"user_id": str(principal.user_id), "purpose": body.purpose, "action": body.action},
        aggregate_type="user",
        aggregate_id=principal.user_id,
    )
    return {"purpose": body.purpose, "state": body.action, "effective_at": to_rfc3339(c.created_at)}


# =========================================================================== ME-07..13 MFA


def _factor_out(f: MfaFactor) -> dict[str, Any]:
    return {
        "factor_id": str(f.id),
        "type": f.factor_type,
        "label": f.label,
        "confirmed": f.factor_type != "totp" or f.totp_confirmed_at is not None,
        "created_at": to_rfc3339(f.created_at),
        "last_used_at": to_rfc3339(f.last_used_at) if f.last_used_at else None,
        "remaining_codes": len(f.recovery_code_hashes or []) if f.factor_type == "recovery_codes" else None,
    }


@mfa_r.get("/factors", openapi_extra={"x-td-idle": "neutral"})
async def list_factors(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    return {"data": [_factor_out(f) for f in await ids.active_factors(session, principal.user_id)]}


async def _mfa_change_step_up(session: AsyncSession, principal: Principal) -> None:
    """ME-08: U15 for students; none for a staff member's first factor; S10/P5 otherwise."""
    has_factor = await ids.has_strong_factor(session, principal.user_id)
    if principal.tier != "student" and not has_factor:
        return
    p = await step_up_problem_for(session, principal, tier_window(principal))
    if p:
        raise p


@mfa_r.post("/totp", status_code=201)
async def totp_begin(
    body: TotpBeginIn, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    await _mfa_change_step_up(session, principal)
    user = await _user(session, principal.user_id)
    # discard earlier unconfirmed enrolments
    for f in await ids.active_factors(session, user.id):
        if f.factor_type == "totp" and f.totp_confirmed_at is None:
            f.revoked_at = clock.now()
    secret = random_base32()
    ct, wrapped = encrypt_secret(secret)
    f = MfaFactor(
        id=uuid7(),
        user_id=user.id,
        factor_type="totp",
        label=body.label or "Authenticator app",
        totp_secret_encrypted=ct,
        totp_wrapped_key=wrapped,
    )
    await _insert(session, f)
    await audit(
        session, principal, "identity.mfa.totp_enrolment_started", "mfa_factor", f.id, subject_user_id=user.id
    )
    return {
        "factor_id": str(f.id),
        "otpauth_uri": provisioning_uri(secret, user.email or user.phone_e164 or str(user.id)),
        "secret": secret,
    }


@mfa_r.post("/totp/{factor_id}/confirm")
async def totp_confirm(
    factor_id: uuid.UUID,
    body: TotpConfirmIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    if ids._fs():
        f = await ids._repo().get_factor(factor_id)
        if f is not None and (
            f.user_id != principal.user_id or f.factor_type != "totp" or f.revoked_at is not None
        ):
            f = None
    else:
        f = (
            await session.execute(
                select(MfaFactor).where(
                    MfaFactor.id == factor_id,
                    MfaFactor.user_id == principal.user_id,
                    MfaFactor.factor_type == "totp",
                    MfaFactor.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
    if f is None:
        raise ProblemError("not_found")
    if f.totp_confirmed_at is not None:
        raise ProblemError("invalid_state_transition", current_state="confirmed", allowed=[])
    from app.modules.identity.crypto import decrypt_secret
    from app.modules.identity.totp import match_step

    step = match_step(decrypt_secret(f.totp_secret_encrypted or b"", f.totp_wrapped_key or b""), body.code)
    if step is None:
        return problem_response(ProblemError("otp_invalid", attempts_remaining=None))
    f.totp_confirmed_at = clock.now()
    f.totp_last_used_step = step
    f.is_primary = not any(
        x.is_primary for x in await ids.active_factors(session, principal.user_id) if x.id != f.id
    )
    s = await _current_session(session, request)
    s.last_step_up_at = clock.now()
    s.amr = [*s.amr, "totp"] if "totp" not in s.amr else s.amr
    revoked = await ss.revoke_all_sessions(
        session,
        principal.user_id,
        "mfa_changed",
        ended_by=principal.user_id,
        except_session_id=s.id,
        clear_remember=False,
    )
    await audit(
        session,
        principal,
        "identity.mfa.totp_enrolled",
        "mfa_factor",
        f.id,
        subject_user_id=principal.user_id,
        after={"other_sessions_revoked": revoked},
    )
    user = await _user(session, principal.user_id)
    await notify(
        session,
        principal.user_id,
        "security.mfa_added",
        category="security",
        channels=("in_app", "email"),
        email_to=user.email,
        email_subject="Two-step verification added",
        email_text="An authenticator app was added to your Tech Drona account.",
    )
    return JSONResponse({"factor_id": str(f.id), "confirmed": True})


@dflt.delete("/me/mfa/factors/{factor_id}")
async def delete_factor(
    factor_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    p = await step_up_problem_for(session, principal, tier_window(principal))
    if p:
        raise p
    factors = await ids.active_factors(session, principal.user_id)
    f = next((x for x in factors if x.id == factor_id), None)
    if f is None:
        raise ProblemError("not_found")
    strong_left = [x for x in factors if ids.is_confirmed_strong(x) and x.id != f.id]
    if principal.tier != "student" and ids.is_confirmed_strong(f) and not strong_left:
        raise ProblemError(
            "invalid_state_transition",
            current_state="last_factor",
            allowed=[],
            detail="Staff accounts must keep at least one two-step verification method.",
        )
    f.revoked_at = clock.now()
    s = await _current_session(session, request)
    await ss.revoke_all_sessions(
        session,
        principal.user_id,
        "mfa_changed",
        ended_by=principal.user_id,
        except_session_id=s.id,
        clear_remember=False,
    )
    await audit(
        session,
        principal,
        "identity.mfa.factor_removed",
        "mfa_factor",
        f.id,
        subject_user_id=principal.user_id,
        after={"type": f.factor_type},
    )
    return {"result": "removed"}


@mfa_r.post("/recovery-codes", status_code=201)
async def recovery_codes(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    if not await ids.has_strong_factor(session, principal.user_id):
        raise ProblemError("invalid_state_transition", current_state="no_mfa", allowed=["enrol_totp"])
    p = await step_up_problem_for(session, principal, tier_window(principal))
    if p:
        raise p
    for f in await ids.active_factors(session, principal.user_id):
        if f.factor_type == "recovery_codes":
            f.revoked_at = clock.now()
    codes, hashes = ids.new_recovery_codes()
    f = MfaFactor(
        id=uuid7(), user_id=principal.user_id, factor_type="recovery_codes", recovery_code_hashes=hashes
    )
    await fs_uow.flush(session)  # earlier recovery-code factors are revoked first
    await _insert(session, f)
    await audit(
        session,
        principal,
        "identity.mfa.recovery_codes_generated",
        "mfa_factor",
        f.id,
        subject_user_id=principal.user_id,
    )
    return {"codes": codes, "factor_id": str(f.id)}


# Firestore: changes made to loaded rows are written at the end of a successful request (fs_uow).
_UOW = [Depends(fs_uow.unit_of_work, scope="function")]
router = APIRouter()
for _r in (pub, lc, acct, dflt, consent_r, mfa_r):
    router.include_router(_r, dependencies=_UOW)
