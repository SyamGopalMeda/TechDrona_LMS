"""Identity service: users, credentials, consents, verification tokens/OTPs, MFA factors."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.security import (
    generate_numeric_otp,
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.modules.identity import clock
from app.modules.identity.contacts import destination_hmac
from app.modules.identity.crypto import decrypt_secret
from app.modules.identity.models import Consent, MfaFactor, User, UserCredential, VerificationToken
from app.modules.identity.policy import get_policy
from app.modules.identity.totp import is_replay, match_step

PURPOSES = (
    "terms",
    "privacy_notice",
    "core_service",
    "security_monitoring",
    "analytics_personalisation",
    "device_fingerprint",
    "marketing_email",
    "marketing_sms",
    "assessment_integrity",
    "analytics_product",
)
REQUIRED_AT_SIGNUP = ("terms", "privacy_notice", "core_service")
# Privacy doc §4: minors may not grant B, C, E, F or H.
MINOR_FORBIDDEN = frozenset(
    {
        "security_monitoring",
        "analytics_personalisation",
        "device_fingerprint",
        "marketing_email",
        "marketing_sms",
        "analytics_product",
    }
)


def age_on(dob: date, on: date) -> int:
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def _fs() -> bool:
    """``TD_STORE_IDENTITY=firestore``: the identity tables live in Firestore (repo_firestore)."""
    return uses_firestore("identity")


def _repo() -> Any:
    from app.modules.identity.repo_firestore import system_repo

    return system_repo()


def eighteenth_birthday(dob: date) -> date:
    try:
        return dob.replace(year=dob.year + 18)
    except ValueError:  # 29 Feb
        return dob.replace(year=dob.year + 18, day=28)


# --------------------------------------------------------------------------- users


async def find_user(session: AsyncSession, kind: str, value: str) -> User | None:
    if _fs():
        return await _repo().find_user(kind, value)
    col = User.email if kind == "email" else User.username if kind == "username" else User.phone_e164
    return (
        await session.execute(select(User).where(col == value, User.deleted_at.is_(None)))
    ).scalar_one_or_none()


async def get_credential(session: AsyncSession, user_id: uuid.UUID) -> UserCredential | None:
    if _fs():
        return await _repo().get_credential(user_id)
    return await session.get(UserCredential, user_id)


async def check_password(cred: UserCredential | None, password: str) -> bool:
    """Argon2id verification in a worker thread (constant work for unknown users)."""
    return await asyncio.to_thread(verify_password, cred.password_hash if cred else None, password)


async def set_password(
    session: AsyncSession, user_id: uuid.UUID, password: str, *, must_change_password: bool = False
) -> None:
    """Set the password. ``users.must_change_password`` follows ``must_change_password``: a
    password the person chose clears it; an Admin-assigned one may set it (first-login change)."""
    pw_hash = await asyncio.to_thread(hash_password, password)
    if _fs():
        await _repo().set_password(user_id, pw_hash, must_change_password=must_change_password)
        return
    cred = await session.get(UserCredential, user_id)
    now = clock.now()
    if cred is None:
        session.add(
            UserCredential(user_id=user_id, password_hash=pw_hash, password_set_at=now, breach_checked_at=now)
        )
    else:
        cred.password_hash = pw_hash
        cred.password_set_at = now
        cred.breach_checked_at = now
        cred.consecutive_failures = 0
        cred.hard_locked_at = None
    user = await session.get(User, user_id)
    if user is not None and user.must_change_password != must_change_password:
        user.must_change_password = must_change_password
    await session.flush()


async def maybe_rehash(cred: UserCredential, password: str) -> None:
    if password_needs_rehash(cred.password_hash):
        cred.password_hash = await asyncio.to_thread(hash_password, password)
        if _fs():  # transient object: persist explicitly
            await _repo().save_credential(cred)


# --------------------------------------------------------------------------- consents


async def current_consents(
    session: AsyncSession, user_id: uuid.UUID, purposes: tuple[str, ...] | None = None
) -> dict[str, dict[str, Any]]:
    """Latest consent state per purpose; ``purposes`` limits the answer to those purposes (same
    values for them as without the filter)."""
    if _fs():
        return await _repo().current_consents(user_id, purposes)
    rows = (
        (
            await session.execute(
                select(Consent)
                .where(
                    Consent.user_id == user_id,
                    Consent.context_ref.is_(None),
                    Consent.organization_id.is_(None),
                    *((Consent.purpose.in_(purposes),) if purposes else ()),
                )
                .order_by(Consent.purpose, Consent.created_at.desc(), Consent.id.desc())
            )
        )
        .scalars()
        .all()
    )
    out: dict[str, dict[str, Any]] = {}
    for c in rows:
        if c.purpose not in out:
            out[c.purpose] = {
                "state": c.action,
                "notice_version": c.notice_version,
                "effective_at": c.created_at,
            }
    return out


async def record_consent(
    session: AsyncSession,
    user_id: uuid.UUID,
    purpose: str,
    action: str,
    notice_version: str,
    *,
    channel: str = "web",
    ip: str | None = None,
    user_agent: str | None = None,
    guardian_consent_id: uuid.UUID | None = None,
    context_ref: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
) -> Consent:
    c = Consent(
        id=uuid7(),
        user_id=user_id,
        purpose=purpose,
        action=action,
        notice_version=notice_version,
        channel=channel,
        ip=ip,
        user_agent=(user_agent or "")[:300] or None,
        guardian_consent_id=guardian_consent_id,
        context_ref=context_ref,
        organization_id=organization_id,
        created_at=clock.now(),
    )
    if _fs():
        return await _repo().add_consent(c)
    session.add(c)
    await session.flush()
    return c


# --------------------------------------------------------------------------- verification tokens / OTP


@dataclass(frozen=True)
class OtpCheck:
    ok: bool
    problem: ProblemError | None = None
    token: VerificationToken | None = None


async def issue_link_token(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    purpose: str,
    channel: str,
    destination: str,
    ttl: timedelta,
    ip: str | None = None,
) -> str:
    raw = generate_token()
    tok = VerificationToken(
        id=uuid7(),
        user_id=user_id,
        purpose=purpose,
        channel=channel,
        destination_hmac=destination_hmac(channel, destination),
        token_hash=hash_token(raw),
        expires_at=clock.now() + ttl,
        created_ip=ip,
        created_at=clock.now(),
    )
    if _fs():
        await _repo().add_token(tok)
        return raw
    session.add(tok)
    await session.flush()
    return raw


async def otp_send_allowed(session: AsyncSession, channel: str, destination: str) -> int:
    """0 if a new OTP may be sent to this destination, else Retry-After seconds.

    SMS: ``otp.sms.max_per_number_per_hour`` / ``per_day`` (SMS-pumping control).
    Email: ``otp.email.max_per_hour`` / ``per_day`` (defaults 10 / 30)."""
    dest = destination_hmac(channel, destination)
    now = clock.now()
    if channel == "sms":
        per_hour = int(await get_policy(session, "otp.sms.max_per_number_per_hour"))
        per_day = int(await get_policy(session, "otp.sms.max_per_number_per_day"))
    else:
        per_hour = int(await get_policy(session, "otp.email.max_per_hour"))
        per_day = int(await get_policy(session, "otp.email.max_per_day"))
    if _fs():
        rows = await _repo().token_times_since(dest, now - timedelta(days=1))
    else:
        rows = (
            (
                await session.execute(
                    select(VerificationToken.created_at).where(
                        VerificationToken.destination_hmac == dest,
                        VerificationToken.created_at > now - timedelta(days=1),
                    )
                )
            )
            .scalars()
            .all()
        )
    hour = sorted(t for t in rows if t > now - timedelta(hours=1))
    if len(hour) >= per_hour:
        return max(1, int((hour[0] + timedelta(hours=1) - now).total_seconds()))
    if len(rows) >= per_day:
        return max(1, int((min(rows) + timedelta(days=1) - now).total_seconds()))
    return 0


def _otp_digest(token_id: uuid.UUID, code: str) -> bytes:
    # Binding the code to its row id keeps token_hash unique even for equal 6-digit codes.
    return hash_token(f"otp:{token_id}:{code}")


async def create_otp(session: AsyncSession, **kw: Any) -> tuple[VerificationToken, str]:
    code = generate_numeric_otp(6)
    now = clock.now()
    ttl = int(await get_policy(session, "otp.ttl_seconds"))
    max_attempts = int(await get_policy(session, "otp.max_verify_attempts"))
    if _fs():
        fid = uuid7()
        new = VerificationToken(
            id=fid,
            user_id=kw.get("user_id"),
            purpose=kw["purpose"],
            channel=kw["channel"],
            destination_hmac=destination_hmac(kw["channel"], kw["destination"]),
            token_hash=_otp_digest(fid, code),
            auth_session_id=kw.get("auth_session_id"),
            device_id=kw.get("device_id"),
            max_attempts=max_attempts,
            expires_at=now + timedelta(seconds=ttl),
            created_ip=kw.get("ip"),
            created_at=now,
        )
        return await _repo().create_otp(new), code
    await session.execute(
        update(VerificationToken)
        .where(
            VerificationToken.purpose == kw["purpose"],
            VerificationToken.user_id.is_not_distinct_from(kw.get("user_id")),
            VerificationToken.auth_session_id.is_not_distinct_from(kw.get("auth_session_id")),
            VerificationToken.consumed_at.is_(None),
            VerificationToken.expires_at > now,
        )
        .values(expires_at=now)
    )
    tid = uuid7()
    tok = VerificationToken(
        id=tid,
        user_id=kw.get("user_id"),
        purpose=kw["purpose"],
        channel=kw["channel"],
        destination_hmac=destination_hmac(kw["channel"], kw["destination"]),
        token_hash=_otp_digest(tid, code),
        auth_session_id=kw.get("auth_session_id"),
        device_id=kw.get("device_id"),
        max_attempts=max_attempts,
        expires_at=now + timedelta(seconds=ttl),
        created_ip=kw.get("ip"),
        created_at=now,
    )
    session.add(tok)
    await session.flush()
    return tok, code


async def check_otp(
    session: AsyncSession,
    *,
    purpose: str,
    code: str,
    user_id: uuid.UUID | None = None,
    auth_session_id: uuid.UUID | None = None,
) -> OtpCheck:
    """Verify the latest OTP for this binding. Attempts are counted (persisted by the caller's
    commit even when the response is an error)."""
    if _fs():
        ok, problem, token = await _repo().check_otp(
            purpose=purpose, code=code, digest=_otp_digest, user_id=user_id, auth_session_id=auth_session_id
        )
        return OtpCheck(ok, problem, token)
    now = clock.now()
    q = select(VerificationToken).where(
        VerificationToken.purpose == purpose, VerificationToken.consumed_at.is_(None)
    )
    if user_id is not None:
        q = q.where(VerificationToken.user_id == user_id)
    if auth_session_id is not None:
        q = q.where(VerificationToken.auth_session_id == auth_session_id)
    tok = (
        await session.execute(q.order_by(VerificationToken.created_at.desc()).limit(1).with_for_update())
    ).scalar_one_or_none()
    if tok is None:
        return OtpCheck(False, ProblemError("otp_expired", attempts_remaining=0))
    if tok.expires_at <= now:
        return OtpCheck(False, ProblemError("otp_expired", attempts_remaining=0), tok)
    if tok.attempts >= tok.max_attempts:
        return OtpCheck(False, ProblemError("otp_attempts_exceeded"), tok)
    if _otp_digest(tok.id, (code or "").strip()) != tok.token_hash:
        tok.attempts += 1
        await session.flush()
        remaining = tok.max_attempts - tok.attempts
        if remaining <= 0:
            return OtpCheck(False, ProblemError("otp_attempts_exceeded"), tok)
        return OtpCheck(False, ProblemError("otp_invalid", attempts_remaining=remaining), tok)
    tok.consumed_at = now
    await session.flush()
    return OtpCheck(True, None, tok)


async def consume_link_token(session: AsyncSession, raw: str, purpose: str) -> VerificationToken | None:
    if _fs():
        # Firestore: a valid, unconsumed token (not claimed). Callers that consume it call
        # ``mark_token_consumed`` (an atomic claim on Firestore; Postgres sets the column under
        # this FOR UPDATE lock).
        return await _repo().link_token(hash_token(raw), purpose)
    tok = (
        await session.execute(
            select(VerificationToken)
            .where(VerificationToken.token_hash == hash_token(raw), VerificationToken.purpose == purpose)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if tok is None or tok.consumed_at is not None or tok.expires_at <= clock.now():
        return None
    return tok


async def mark_token_consumed(session: AsyncSession, tok: VerificationToken) -> bool:
    """Consume a token returned by ``consume_link_token``. Postgres: sets ``consumed_at`` on the
    locked row (committed with the request). Firestore: claims it in a transaction; False when
    another request consumed it first (Postgres serialises that case on the row lock)."""
    now = clock.now()
    if _fs():
        if await _repo().claim_link_token(tok.token_hash, tok.purpose) is None:
            return False
        tok.consumed_at = now
        from app.modules.identity import fs_uow

        uow = fs_uow.current()
        if uow is not None:
            uow.clean(tok)
        return True
    tok.consumed_at = now
    return True


# --------------------------------------------------------------------------- MFA


async def active_factors(session: AsyncSession, user_id: uuid.UUID) -> list[MfaFactor]:
    if _fs():
        return await _repo().active_factors(user_id)
    return list(
        (
            await session.execute(
                select(MfaFactor)
                .where(MfaFactor.user_id == user_id, MfaFactor.revoked_at.is_(None))
                .order_by(MfaFactor.created_at)
            )
        ).scalars()
    )


def is_confirmed_strong(f: MfaFactor) -> bool:
    return (f.factor_type == "totp" and f.totp_confirmed_at is not None) or f.factor_type == "webauthn"


async def has_strong_factor(session: AsyncSession, user_id: uuid.UUID) -> bool:
    return any(is_confirmed_strong(f) for f in await active_factors(session, user_id))


TotpVerdict = Literal["ok", "replayed", "invalid"]


async def check_totp_code(session: AsyncSession, user_id: uuid.UUID, code: str) -> TotpVerdict:
    """Accept a code for any confirmed TOTP factor; single use per 30 s step.

    ``replayed``: the code is genuine but its step was already used (E2E-12). Callers refuse it
    without counting an MFA failure — a replay proves possession of the factor, it is not a guess.
    """
    replayed = False
    for f in await active_factors(session, user_id):
        if f.factor_type != "totp" or f.totp_confirmed_at is None or f.totp_secret_encrypted is None:
            continue
        secret = decrypt_secret(f.totp_secret_encrypted, f.totp_wrapped_key or b"")
        step = match_step(secret, code, last_used_step=f.totp_last_used_step)
        if step is not None and _fs():
            if await _repo().use_totp_step(f.id, step):
                return "ok"
            replayed = True  # the step was used concurrently
            continue
        if step is not None:
            f.totp_last_used_step = step
            f.last_used_at = clock.now()
            await session.flush()
            return "ok"
        replayed = replayed or is_replay(secret, code, last_used_step=f.totp_last_used_step)
    return "replayed" if replayed else "invalid"


async def verify_totp_code(session: AsyncSession, user_id: uuid.UUID, code: str) -> bool:
    return await check_totp_code(session, user_id, code) == "ok"


async def verify_recovery_code(session: AsyncSession, user_id: uuid.UUID, code: str) -> bool:
    digest = hash_token("rc:" + (code or "").strip().replace("-", "").lower())
    if _fs():
        return await _repo().use_recovery_code(user_id, digest)
    for f in await active_factors(session, user_id):
        if f.factor_type == "recovery_codes" and f.recovery_code_hashes and digest in f.recovery_code_hashes:
            f.recovery_code_hashes = [h for h in f.recovery_code_hashes if h != digest]
            f.last_used_at = clock.now()
            await session.flush()
            return True
    return False


def new_recovery_codes(n: int = 10) -> tuple[list[str], list[bytes]]:
    codes = [generate_token(16)[:10].lower().replace("_", "x").replace("-", "y") for _ in range(n)]
    pretty = [f"{c[:5]}-{c[5:]}" for c in codes]
    return pretty, [hash_token("rc:" + c) for c in codes]


async def mfa_failures_recent(session: AsyncSession, user_id: uuid.UUID, minutes: int = 10) -> int:
    """MFA failures of a user in the last ``minutes`` (``login_attempts``, via sessions.public)."""
    from app.modules.sessions import public as sessions_public

    rows = await sessions_public.list_login_attempts(
        session, since=clock.now() - timedelta(minutes=minutes), user_id=user_id, outcomes=["mfa_failed"]
    )
    return len(rows)
