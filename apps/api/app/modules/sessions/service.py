"""Sessions and devices: device cookies (HMAC, key versions), trust and caps, server-side
sessions (opaque token, SHA-256 stored), timeouts per tier, revocation, login attempts and
per-account back-off.

Postgres is the source of truth (account-security §1.6). The Redis read-through cache
``sess:{hash}`` is Planned; every lookup reads ``auth_sessions`` by its unique token hash.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.security import generate_token, get_keyring, hash_token
from app.modules.identity import clock
from app.modules.identity.policy import get_policy
from app.modules.identity.public import User
from app.modules.sessions.hooks import security_events
from app.modules.sessions.models import AuthSession, Device, LoginAttempt, UserDevice
from app.modules.sessions.ua import UaInfo, net_cluster, parse_ua, valid_ip

TIMEOUTS: dict[str, tuple[timedelta, timedelta]] = {
    "student": (timedelta(minutes=60), timedelta(hours=24)),
    "staff": (timedelta(minutes=30), timedelta(hours=12)),
    "privileged": (timedelta(minutes=15), timedelta(hours=8)),
}
PENDING_STATUSES = frozenset({"pending_mfa", "pending_device_otp", "pending_session_choice"})
ENDED_STATUSES = frozenset({"expired", "revoked", "blocked"})
DEVICE_COOKIE = "__Host-td_device"
SESSION_COOKIE = "__Host-td_session"
REMEMBER_COOKIE = "__Host-td_remember"
DEVICE_COOKIE_MAX_AGE = 34_560_000  # 400 days
DEVICE_TOKEN_BYTES = 16  # 128-bit browser-profile id


def _fs() -> bool:
    """``TD_STORE_SESSIONS=firestore``: sessions tables live in Firestore (repo_firestore)."""
    return uses_firestore("sessions")


def _repo() -> Any:
    from app.modules.sessions.repo_firestore import system_repo

    return system_repo()


def postgres_available() -> bool:
    """False on a stack without Postgres (request sessions are ``NO_POSTGRES``)."""
    from app.core import db as core_db
    from app.core.runtime import postgres_enabled

    return core_db._sessionmaker is not None or postgres_enabled()


@asynccontextmanager
async def system_session(job: str) -> AsyncIterator[Any]:
    """A fresh transaction in the named system context (``get_sessionmaker`` +
    ``system_context``), or ``NO_POSTGRES`` when the stack has no Postgres (the access
    modules then work from Firestore only)."""
    from app.core.db import NO_POSTGRES, get_sessionmaker, system_context

    if not postgres_available():
        yield NO_POSTGRES
        return
    async with get_sessionmaker()() as session, session.begin():
        await system_context(session, job)
        yield session


# --------------------------------------------------------------------------- request info


@dataclass(frozen=True, slots=True)
class ClientInfo:
    ip: str | None
    ua: UaInfo
    device_token: str | None
    client_type: str = "web"


def client_info(request: Request) -> ClientInfo:
    st = request.state
    raw_dev = getattr(st, "device_token", None)
    return ClientInfo(
        ip=valid_ip(getattr(st, "client_ip", None)),
        ua=parse_ua(request.headers.get("user-agent")),
        device_token=raw_dev if raw_dev and 16 <= len(raw_dev) <= 128 else None,
    )


# --------------------------------------------------------------------------- devices


async def resolve_device(session: AsyncSession, info: ClientInfo) -> tuple[Device, str, bool]:
    """Return ``(device, raw_device_token, issued_new_cookie)``. Old key versions are re-hashed
    in place (RE §1.5)."""
    ring = get_keyring("device")
    raw = info.device_token
    now = clock.now()
    if raw:
        digests = ring.all_digests(raw)
        if _fs():
            rows = await _repo().devices_by_hashes([d for _, d in digests])
        else:
            rows = (
                (
                    await session.execute(
                        select(Device).where(Device.device_key_hash.in_([d for _, d in digests]))
                    )
                )
                .scalars()
                .all()
            )
        for dev in rows:
            if ring.verify(raw, dev.device_key_hash, dev.key_version):
                if ring.needs_rehash(dev.key_version):
                    dev.key_version, dev.device_key_hash = ring.sign(raw)
                dev.last_seen_at = now
                if _fs():
                    dev = await _repo().save_device(dev)
                return dev, raw, False
    issued = raw is None
    raw = raw or generate_token(DEVICE_TOKEN_BYTES)
    version, digest = ring.sign(raw)
    dev = Device(
        id=uuid7(),
        device_key_hash=digest,
        key_version=version,
        client_type=info.client_type,
        ua_family=info.ua.family,
        os_family=info.ua.os_family,
        device_class=info.ua.device_class,
        label_hint=info.ua.label,
        first_seen_at=now,
        last_seen_at=now,
    )
    if _fs():
        return await _repo().save_device(dev), raw, issued
    session.add(dev)
    await session.flush()
    return dev, raw, issued


async def device_hash_matches(session: AsyncSession, device_id: uuid.UUID | None, raw: str | None) -> bool:
    if device_id is None:
        return True
    if not raw:
        return False
    dev = await _repo().get_device(device_id) if _fs() else await session.get(Device, device_id)
    return dev is not None and get_keyring("device").verify(raw, dev.device_key_hash, dev.key_version)


async def get_user_device(
    session: AsyncSession, user_id: uuid.UUID, device_id: uuid.UUID
) -> UserDevice | None:
    if _fs():
        return await _repo().live_user_device(user_id, device_id)
    return (
        await session.execute(
            select(UserDevice).where(
                UserDevice.user_id == user_id,
                UserDevice.device_id == device_id,
                UserDevice.trust_status != "removed",
            )
        )
    ).scalar_one_or_none()


async def ensure_user_device(session: AsyncSession, user_id: uuid.UUID, device: Device) -> UserDevice:
    if _fs():
        ud, created = await _repo().ensure_user_device(user_id, device.id)
        if not created and ud.trust_status == "expired":
            ud.trust_status = "pending_otp"
            ud = await _repo().save_user_device(ud)
        return ud
    ud = await get_user_device(session, user_id, device.id)
    if ud is None:
        ud = UserDevice(
            id=uuid7(),
            user_id=user_id,
            device_id=device.id,
            trust_status="pending_otp",
            counts_toward_cap=True,
        )
        session.add(ud)
        await session.flush()
    elif ud.trust_status == "expired":
        ud.trust_status = "pending_otp"
    return ud


async def has_device_history(session: AsyncSession, user_id: uuid.UUID) -> bool:
    if _fs():
        return len(await _repo().user_devices(user_id)) > 1
    return (
        await session.execute(
            select(func.count()).select_from(UserDevice).where(UserDevice.user_id == user_id)
        )
    ).scalar_one() > 1


async def trusted_devices(session: AsyncSession, user_id: uuid.UUID) -> list[UserDevice]:
    if _fs():
        rows = [
            d
            for d in await _repo().user_devices(user_id)
            if d.trust_status == "trusted" and d.counts_toward_cap
        ]
        # ORDER BY last_used_at ASC NULLS FIRST
        return sorted(rows, key=lambda d: (d.last_used_at is not None, d.last_used_at or clock.now()))
    return list(
        (
            await session.execute(
                select(UserDevice)
                .where(
                    UserDevice.user_id == user_id,
                    UserDevice.trust_status == "trusted",
                    UserDevice.counts_toward_cap.is_(True),
                )
                .order_by(UserDevice.last_used_at.asc().nulls_first())
            )
        ).scalars()
    )


async def replacements_used(session: AsyncSession, user_id: uuid.UUID) -> tuple[int, datetime | None]:
    since = clock.now() - timedelta(days=30)
    if _fs():
        found = sorted(
            d.removed_at
            for d in await _repo().user_devices(user_id)
            if d.removed_reason == "self_service_replacement"
            and d.removed_at is not None
            and d.removed_at >= since
        )
        return len(found), (found[0] + timedelta(days=30) if found else None)
    rows = (
        (
            await session.execute(
                select(UserDevice.removed_at)
                .where(
                    UserDevice.user_id == user_id,
                    UserDevice.removed_reason == "self_service_replacement",
                    UserDevice.removed_at >= since,
                )
                .order_by(UserDevice.removed_at.asc())
            )
        )
        .scalars()
        .all()
    )
    nxt = rows[0] + timedelta(days=30) if rows and rows[0] is not None else None
    return len(rows), nxt


async def device_cap_tier(session: AsyncSession, user_id: uuid.UUID) -> str:
    """Which trusted-device limit applies: ``admin`` (super_admin), ``staff`` (trainer, evaluator,
    content manager: "faculty") or ``student``. Devices are recorded for every tier; only the cap
    differs (owner decision 2026-11-11)."""
    from app.modules.rbac.service import active_grants

    roles = {g.role for g in await active_grants(session, user_id)}
    if "super_admin" in roles:
        return "admin"
    if roles - {"student"}:
        return "staff"
    return "student"


async def device_limits(session: AsyncSession, user: User) -> dict[str, object]:
    """``max_trusted`` is ``None`` when the account has no cap (admins, unless
    ``devices.admin.cap_enabled``). Students: ``devices.student.max_trusted``; faculty and capped
    admins: ``devices.staff.max_trusted``. All three keys are edited in Admin > Policies."""
    tier = await device_cap_tier(session, user.id)
    max_trusted: int | None
    if tier == "admin" and not bool(await get_policy(session, "devices.admin.cap_enabled", user_id=user.id)):
        max_trusted = None
    else:
        key = "devices.student.max_trusted" if tier == "student" else "devices.staff.max_trusted"
        max_trusted = int(await get_policy(session, key, user_id=user.id))
    max_repl = int(await get_policy(session, "devices.student.max_replacements_per_30d", user_id=user.id))
    used, nxt = await replacements_used(session, user.id)
    counted = len(await trusted_devices(session, user.id))
    return {
        "max_trusted": max_trusted,
        "cap_tier": tier,
        "trusted_counted": counted,
        "replacements_used_30d": used,
        "replacements_max_30d": max_repl,
        "next_replacement_at": nxt if used >= max_repl else None,
        "inactivity_expiry_days": int(await get_policy(session, "devices.trusted_inactivity_expiry_days")),
    }


async def trust_device(
    session: AsyncSession, ud: UserDevice, method: str | None, *, owner_verified: bool
) -> None:
    now = clock.now()
    ud.trust_status = "trusted"
    ud.trusted_at = now
    ud.verification_method = method
    ud.last_used_at = now
    if owner_verified:
        ud.owner_verified_at = now
    # A recent self-service sign-out followed by a new device within 30 days is a replacement.
    if _fs():
        if ud.counts_toward_cap:
            prev = [
                d
                for d in await _repo().user_devices(ud.user_id)
                if d.id != ud.id
                and d.removed_reason == "self_service_signout"
                and d.removed_at is not None
                and d.removed_at >= now - timedelta(days=30)
            ]
            if prev:
                latest = max(prev, key=lambda d: d.removed_at)
                latest.removed_reason = "self_service_replacement"
                await _repo().save_user_device(latest)
        await _repo().save_user_device(ud)
        sink = security_events()
        if sink is not None:
            await sink.device_trusted(session, ud, method)
        return
    if ud.counts_toward_cap:
        prior = (
            await session.execute(
                select(UserDevice)
                .where(
                    UserDevice.user_id == ud.user_id,
                    UserDevice.id != ud.id,
                    UserDevice.removed_reason == "self_service_signout",
                    UserDevice.removed_at >= now - timedelta(days=30),
                )
                .order_by(UserDevice.removed_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if prior is not None:
            prior.removed_reason = "self_service_replacement"
    await session.flush()
    sink = security_events()
    if sink is not None:
        await sink.device_trusted(session, ud, method)


async def remove_user_device(
    session: AsyncSession, ud: UserDevice, reason: str, *, removed_by: uuid.UUID | None
) -> int:
    now = clock.now()
    ud.trust_status = "removed"
    ud.removed_at = now
    ud.removed_by = removed_by
    ud.removed_reason = reason
    ud.remember_token_hash = None
    ud.remember_until = None
    if _fs():
        await _repo().save_user_device(ud)
        return await _repo().end_sessions(
            ud.user_id,
            status="revoked",
            reason="device_removed",
            ended_by=removed_by,
            where=lambda x: x.user_device_id == ud.id,
        )
    await session.flush()
    return await end_sessions_where(
        session,
        AuthSession.user_device_id == ud.id,
        status="revoked",
        reason="device_removed",
        ended_by=removed_by,
    )


# --------------------------------------------------------------------------- sessions


# Simple auth (owner decision 2026-11-12): Admin sessions effectively never time out; every
# other account gets a flat 5 hours (idle and absolute).
SIMPLE_TIMEOUTS: dict[str, tuple[timedelta, timedelta]] = {
    "privileged": (timedelta(days=3650), timedelta(days=3650)),
    "staff": (timedelta(hours=5), timedelta(hours=5)),
    "student": (timedelta(hours=5), timedelta(hours=5)),
}


def session_timeouts(tier: str) -> tuple[timedelta, timedelta]:
    from app.core.config import get_settings

    if get_settings().simple_auth:
        return SIMPLE_TIMEOUTS[tier]
    return TIMEOUTS[tier]


async def create_session(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    tier: str,
    status: str,
    created_via: str,
    info: ClientInfo,
    device: Device | None,
    user_device: UserDevice | None,
    amr: Iterable[str],
    aal: int = 1,
    restriction_level: int = 0,
    auth_time: datetime | None = None,
    remember: bool = False,
) -> tuple[AuthSession, str]:
    now = clock.now()
    idle, absolute = session_timeouts(tier)
    pending_window = timedelta(minutes=int(await get_policy(session, "auth.pending_login_minutes")))
    abs_at = now + absolute
    idle_at = min(now + (pending_window if status in PENDING_STATUSES else idle), abs_at)
    token = generate_token()
    cluster = net_cluster(info.ip)
    s = AuthSession(
        id=uuid7(),
        token_hash=hash_token(token),
        user_id=user_id,
        device_id=device.id if device else None,
        user_device_id=user_device.id if user_device else None,
        client_type=info.client_type,
        session_tier=tier,
        scope="status_only"
        if restriction_level >= 4
        else ("restricted" if restriction_level == 3 else "full"),
        status=status,
        aal=aal,
        amr=list(dict.fromkeys(amr)),
        created_via=created_via,
        auth_time=auth_time or now,
        remember_device=remember,
        restriction_level_at_issue=restriction_level,
        created_at=now,
        last_seen_at=now,
        idle_expires_at=idle_at,
        absolute_expires_at=abs_at,
        ip_first=info.ip,
        ip_last=info.ip,
        net_cluster_first=cluster,
        net_cluster_last=cluster,
        ua_family=info.ua.family,
        ua_major=info.ua.major,
        os_family=info.ua.os_family,
        device_class=info.ua.device_class,
        ua_hash=info.ua.ua_hash,
    )
    if _fs():
        return await _repo().add_session(s), token
    session.add(s)
    await session.flush()
    return s, token


async def _persist(session: AsyncSession, s: AuthSession) -> None:
    """Postgres: flush the tracked row. Firestore: write the transient object (a session
    ended concurrently stays ended, see ``SessionsRepo.save_session``)."""
    if _fs():
        saved = await _repo().save_session(s)
        if saved.status != s.status:  # lost to a concurrent end: reflect the stored state
            for k in ("status", "end_reason", "ended_at", "ended_by"):
                setattr(s, k, getattr(saved, k))
        return
    await session.flush()


async def save_session(session: AsyncSession, s: AuthSession) -> None:
    """Persist attribute changes a caller made to ``s`` (a no-op flush on Postgres, where the
    row is tracked by the session; required on Firestore, where ``s`` is transient)."""
    await _persist(session, s)


async def activate_session(session: AsyncSession, s: AuthSession) -> None:
    now = clock.now()
    idle, _ = session_timeouts(s.session_tier)
    s.status = "active"
    s.idle_expires_at = min(now + idle, s.absolute_expires_at)
    s.last_seen_at = now
    await _persist(session, s)


async def set_pending(session: AsyncSession, s: AuthSession, status: str, minutes: int | None = None) -> None:
    window = minutes or int(await get_policy(session, "auth.pending_login_minutes"))
    s.status = status
    s.idle_expires_at = min(clock.now() + timedelta(minutes=window), s.absolute_expires_at)
    await _persist(session, s)


async def rotate_token(session: AsyncSession, s: AuthSession) -> str:
    token = generate_token()
    s.token_hash = hash_token(token)
    await _persist(session, s)
    return token


async def end_session(
    session: AsyncSession, s: AuthSession, *, status: str, reason: str, ended_by: uuid.UUID | None = None
) -> None:
    if s.status in ENDED_STATUSES:
        return
    s.status = status
    s.end_reason = reason
    s.ended_at = clock.now()
    s.ended_by = ended_by
    await _persist(session, s)


async def end_sessions_where(
    session: AsyncSession, *conds: object, status: str, reason: str, ended_by: uuid.UUID | None = None
) -> int:
    if _fs():
        # SQL conditions cannot be evaluated against Firestore: callers use
        # ``SessionsRepo.end_sessions(user_id, where=...)`` instead (see data-access.md).
        raise NotImplementedError(
            "end_sessions_where on TD_STORE_SESSIONS=firestore; use SessionsRepo.end_sessions"
        )
    r = await session.execute(
        update(AuthSession)
        .where(AuthSession.status.not_in(ENDED_STATUSES), *conds)  # type: ignore[arg-type]
        .values(status=status, end_reason=reason, ended_at=clock.now(), ended_by=ended_by)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(r, "rowcount", 0) or 0)


async def revoke_all_sessions(
    session: AsyncSession,
    user_id: uuid.UUID,
    reason: str,
    *,
    ended_by: uuid.UUID | None = None,
    except_session_id: uuid.UUID | None = None,
    clear_remember: bool = True,
) -> int:
    """Revoke every (other) session. Without an exception, also moves
    ``users.sessions_valid_after`` so a missed row can never be resurrected (RE §8)."""
    if _fs():
        from app.modules.identity import service as identity_service

        if except_session_id is None:
            if identity_service._fs():
                await identity_service._repo().update_user(user_id, sessions_valid_after=clock.now())
            else:
                await session.execute(
                    update(User).where(User.id == user_id).values(sessions_valid_after=clock.now())
                )
        if clear_remember:
            await _repo().clear_remember(user_id)
        return await _repo().end_sessions(
            user_id,
            status="revoked",
            reason=reason,
            ended_by=ended_by,
            where=lambda x: x.id != except_session_id,
        )
    conds: list[object] = [AuthSession.user_id == user_id]
    if except_session_id is not None:
        conds.append(AuthSession.id != except_session_id)
    else:
        await session.execute(update(User).where(User.id == user_id).values(sessions_valid_after=clock.now()))
    if clear_remember:
        await session.execute(
            update(UserDevice)
            .where(UserDevice.user_id == user_id, UserDevice.remember_token_hash.is_not(None))
            .values(remember_token_hash=None, remember_until=None)
        )
    return await end_sessions_where(session, *conds, status="revoked", reason=reason, ended_by=ended_by)


async def active_sessions(
    session: AsyncSession, user_id: uuid.UUID, *, exclude: uuid.UUID | None = None
) -> list[AuthSession]:
    if _fs():
        return await _repo().active_sessions(user_id, exclude=exclude)
    now = clock.now()
    q = select(AuthSession).where(
        AuthSession.user_id == user_id,
        AuthSession.status == "active",
        AuthSession.absolute_expires_at > now,
        or_(AuthSession.idle_expires_at > now, AuthSession.idle_hold_until > now),
    )
    if exclude is not None:
        q = q.where(AuthSession.id != exclude)
    return list((await session.execute(q.order_by(AuthSession.created_at.asc()))).scalars())


ActiveAttemptLookup = Callable[[AsyncSession, list[uuid.UUID]], Awaitable[set[uuid.UUID]]]
_active_attempt_lookup: ActiveAttemptLookup | None = None


def register_active_attempt_lookup(fn: ActiveAttemptLookup | None) -> None:
    """Assessments hook: which of these session ids hold an in-progress attempt."""
    global _active_attempt_lookup
    _active_attempt_lookup = fn


async def sessions_with_attempts(session: AsyncSession, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if _active_attempt_lookup is None or not ids:
        return set()
    return await _active_attempt_lookup(session, ids)


async def lock_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Serialise cap checks for one user (``pg_advisory_xact_lock``, released at commit).

    Firestore: ``app.core.request_locks.acquire("sess:{user}")`` -- a lease document held by the
    current request (released by the request middleware when the request ends; outside a request
    open ``async with request_locks.scope()``). It waits for a concurrent login of the same user
    and answers 503 + Retry-After when the wait runs out, as a lock wait would."""
    if _fs():
        from app.core import request_locks

        await request_locks.acquire(f"sess:{user_id}")
        return
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('sess:' || :u))"), {"u": str(user_id)})


async def unlock_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Kept for callers: both locks end with the request/transaction (nothing to do)."""
    del session, user_id


# --------------------------------------------------------------------------- login attempts / back-off


async def record_login_attempt(
    session: AsyncSession,
    *,
    identifier: tuple[int, bytes],
    user_id: uuid.UUID | None,
    outcome: str,
    info: ClientInfo,
    method: str = "password",
    mfa_method: str | None = None,
    failure_reason: str | None = None,
    pre_auth_blocked: bool = False,
    device_id: uuid.UUID | None = None,
    auth_session_id: uuid.UUID | None = None,
) -> None:
    version, digest = identifier
    attempt = LoginAttempt(
        id=uuid7(),
        attempted_at=clock.now(),
        user_id=user_id,
        identifier_hash=digest,
        key_version=version,
        method=method,
        mfa_method=mfa_method,
        outcome=outcome,
        failure_reason=failure_reason,
        pre_auth_blocked=pre_auth_blocked,
        ip=info.ip,
        ua_hash=info.ua.ua_hash,
        device_id=device_id,
        auth_session_id=auth_session_id,
    )
    if _fs():
        attempt = await _repo().add_attempt(attempt)
    else:
        session.add(attempt)
        await session.flush()
    sink = security_events()
    if sink is not None:
        await sink.login_attempt(session, attempt)


FAILURE_OUTCOMES = ("bad_credentials", "unknown_identifier")


async def backoff_remaining(session: AsyncSession, digests: list[tuple[int, bytes]]) -> int:
    """Seconds until the next attempt for this identifier is allowed (0 = allowed).

    Consecutive non-pre-auth failures since the last success (24 h window) → delay
    ``base · 2^(n-1)`` capped at ``login.backoff_cap_seconds`` (identical for unknown and known
    identifiers, FR-IDN-005)."""
    now = clock.now()
    hashes = [d for _, d in digests]
    if _fs():
        rows = await _repo().attempts_for_identifiers(hashes, now - timedelta(hours=24))
        succ = [a.attempted_at for a in rows if a.outcome == "success"]
        since_fs = max(max(succ, default=now - timedelta(hours=24)), now - timedelta(hours=24))
        fails = [
            a.attempted_at
            for a in rows
            if a.outcome in FAILURE_OUTCOMES and not a.pre_auth_blocked and a.attempted_at > since_fs
        ]
        n_fs, last_fs = len(fails), max(fails, default=None)
        if n_fs == 0 or last_fs is None:
            return 0
        base = int(await get_policy(session, "login.backoff_base_seconds"))
        cap = int(await get_policy(session, "login.backoff_cap_seconds"))
        delay = min(base * (2 ** min(n_fs - 1, 20)), cap)
        return max(0, int((last_fs + timedelta(seconds=delay) - now).total_seconds() + 0.999))
    last_success = (
        await session.execute(
            select(func.max(LoginAttempt.attempted_at)).where(
                LoginAttempt.identifier_hash.in_(hashes), LoginAttempt.outcome == "success"
            )
        )
    ).scalar_one()
    since = max(last_success or (now - timedelta(hours=24)), now - timedelta(hours=24))
    row = (
        await session.execute(
            select(func.count(), func.max(LoginAttempt.attempted_at)).where(
                LoginAttempt.identifier_hash.in_(hashes),
                LoginAttempt.outcome.in_(FAILURE_OUTCOMES),
                LoginAttempt.pre_auth_blocked.is_(False),
                LoginAttempt.attempted_at > since,
            )
        )
    ).one()
    n, last = int(row[0]), row[1]
    if n == 0 or last is None:
        return 0
    base = int(await get_policy(session, "login.backoff_base_seconds"))
    cap = int(await get_policy(session, "login.backoff_cap_seconds"))
    delay = min(base * (2 ** min(n - 1, 20)), cap)
    remaining = (last + timedelta(seconds=delay) - now).total_seconds()
    return max(0, int(remaining + 0.999))


async def ip_failures_exceeded(session: AsyncSession, ip: str | None) -> bool:
    if not ip:
        return False
    limit = int(await get_policy(session, "login.ip_failed_limit_per_10min"))
    if _fs():
        n_fs = await _repo().count_attempts(
            ip=ip, outcomes=FAILURE_OUTCOMES, since=clock.now() - timedelta(minutes=10)
        )
        return int(n_fs) >= limit
    n = (
        await session.execute(
            select(func.count()).where(
                LoginAttempt.ip == ip,
                LoginAttempt.outcome.in_(FAILURE_OUTCOMES),
                LoginAttempt.attempted_at > clock.now() - timedelta(minutes=10),
            )
        )
    ).scalar_one()
    return int(n) >= limit


def cookie_header(name: str, value: str, max_age: int | None) -> str:
    parts = [f"{name}={value}", "Path=/", "HttpOnly", "SameSite=Lax"]
    if get_settings().TD_COOKIE_SECURE:
        parts.append("Secure")
    if max_age is not None:
        parts.append(f"Max-Age={max(0, int(max_age))}")
    return "; ".join(parts)


def session_cookie(s: AuthSession, token: str) -> str:
    return cookie_header(SESSION_COOKIE, token, int((s.absolute_expires_at - clock.now()).total_seconds()))


def device_cookie(raw: str) -> str:
    return cookie_header(DEVICE_COOKIE, raw, DEVICE_COOKIE_MAX_AGE)


async def get_user_device_by_id(session: AsyncSession, user_device_id: uuid.UUID) -> UserDevice | None:
    """One ``user_devices`` row by id (store-neutral)."""
    if _fs():
        return await _repo().get_user_device_by_id(user_device_id)
    return await session.get(UserDevice, user_device_id)
