"""Store-neutral sessions API for other modules (``TD_STORE_SESSIONS`` = postgres | firestore).

Replaces direct SQL on ``auth_sessions``, ``devices``, ``user_devices``, ``login_attempts`` and
``session_network_observations`` in other modules (security, admin, assessments, media,
support, seeds). Filters are keyword arguments; lists come back in a stable order (documented
per function). Aggregates (group-by reports) are computed by the caller from the lists.
Change data only through the write functions here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.backend import uses_firestore
from app.modules.identity import clock
from app.modules.sessions.models import (
    AuthSession,
    Device,
    LoginAttempt,
    SessionNetworkObservation,
    UserDevice,
)

ENDED = ("expired", "revoked", "blocked")


def _fs() -> bool:
    return uses_firestore("sessions")


def _repo() -> Any:
    from app.modules.sessions.repo_firestore import system_repo

    return system_repo()


def _between(
    v: datetime | None, after: datetime | None, until: datetime | None, *, strict: bool = True
) -> bool:
    if v is None:
        return after is None and until is None
    if after is not None and (v <= after if strict else v < after):
        return False
    return until is None or v <= until


# --------------------------------------------------------------------------- auth sessions


async def get_session(session: AsyncSession, session_id: uuid.UUID) -> AuthSession | None:
    if _fs():
        return await _repo().get_session(session_id)
    return await session.get(AuthSession, session_id)


async def list_sessions(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    status: str | None = None,
    active_at: datetime | None = None,
    created_after: datetime | None = None,
    created_until: datetime | None = None,
    last_seen_after: datetime | None = None,
    last_seen_until: datetime | None = None,
    device_id: uuid.UUID | None = None,
    exclude_device_id: uuid.UUID | None = None,
    session_tier: str | None = None,
    client_type: str | None = None,
    end_reason: str | None = None,
    ended_after: datetime | None = None,
) -> list[AuthSession]:
    """Sessions matching every filter, oldest ``created_at`` first. ``active_at``: status
    ``active`` and ``absolute_expires_at > active_at``. ``created_after`` / ``last_seen_after`` /
    ``ended_after`` are exclusive, the ``*_until`` bounds inclusive."""
    if _fs():
        from app.modules.sessions.store_specs import SESSIONS

        f: list[Any] = []
        if status is not None or active_at is not None:
            f.append(("status", "==", "active" if active_at is not None else status))
        if session_tier:
            f.append(("session_tier", "==", session_tier))
        rows: list[AuthSession] = await _repo()._objs(
            AuthSession, SESSIONS, user_id=user_id, filters=tuple(f)
        )
        rows = [
            s
            for s in rows
            if (active_at is None or s.absolute_expires_at > active_at)
            and (
                (created_after is None and created_until is None)
                or _between(s.created_at, created_after, created_until)
            )
            and (
                (last_seen_after is None and last_seen_until is None)
                or _between(s.last_seen_at, last_seen_after, last_seen_until, strict=False)
            )
            and (device_id is None or s.device_id == device_id)
            and (exclude_device_id is None or s.device_id != exclude_device_id)
            and (client_type is None or s.client_type == client_type)
            and (end_reason is None or s.end_reason == end_reason)
            and (ended_after is None or (s.ended_at is not None and s.ended_at > ended_after))
        ]
        return sorted(rows, key=lambda s: (s.created_at, str(s.id)))
    q = select(AuthSession)
    if user_id is not None:
        q = q.where(AuthSession.user_id == user_id)
    if active_at is not None:
        q = q.where(AuthSession.status == "active", AuthSession.absolute_expires_at > active_at)
    elif status is not None:
        q = q.where(AuthSession.status == status)
    if created_after is not None:
        q = q.where(AuthSession.created_at > created_after)
    if created_until is not None:
        q = q.where(AuthSession.created_at <= created_until)
    if last_seen_after is not None:
        q = q.where(AuthSession.last_seen_at >= last_seen_after)
    if last_seen_until is not None:
        q = q.where(AuthSession.last_seen_at <= last_seen_until)
    if device_id is not None:
        q = q.where(AuthSession.device_id == device_id)
    if exclude_device_id is not None:
        q = q.where(AuthSession.device_id != exclude_device_id)
    if session_tier:
        q = q.where(AuthSession.session_tier == session_tier)
    if client_type:
        q = q.where(AuthSession.client_type == client_type)
    if end_reason:
        q = q.where(AuthSession.end_reason == end_reason)
    if ended_after is not None:
        q = q.where(AuthSession.ended_at > ended_after)
    return list((await session.execute(q.order_by(AuthSession.created_at, AuthSession.id))).scalars().all())


async def update_session(session: AsyncSession, session_id: uuid.UUID, **changes: Any) -> None:
    """Set columns of one session (e.g. ``idle_hold_until``, ``last_step_up_at``)."""
    if _fs():
        s = await _repo().get_session(session_id)
        if s is None:
            return
        for k, v in changes.items():
            setattr(s, k, v)
        await _repo().save_session(s)
        return
    await session.execute(update(AuthSession).where(AuthSession.id == session_id).values(**changes))


async def end_sessions(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: str,
    reason: str,
    ended_by: uuid.UUID | None = None,
    except_ids: Iterable[uuid.UUID] = (),
    only_status: str | None = None,
) -> int:
    """End a user's not-yet-ended sessions (optionally only those in ``only_status``), except
    ``except_ids``. Returns the number ended. Store-neutral ``end_sessions_where``."""
    keep = set(except_ids)
    if _fs():
        return await _repo().end_sessions(
            user_id,
            status=status,
            reason=reason,
            ended_by=ended_by,
            where=lambda s: s.id not in keep and (only_status is None or s.status == only_status),
        )
    from app.modules.sessions.service import end_sessions_where

    conds: list[Any] = [AuthSession.user_id == user_id]
    if keep:
        conds.append(AuthSession.id.not_in(keep))
    if only_status is not None:
        conds.append(AuthSession.status == only_status)
    return await end_sessions_where(session, *conds, status=status, reason=reason, ended_by=ended_by)


async def add_session(session: AsyncSession, s: AuthSession) -> AuthSession:
    """Insert a prepared session row (seeds)."""
    if _fs():
        return await _repo().add_session(s)
    session.add(s)
    await session.flush()
    return s


# --------------------------------------------------------------------------- devices


async def get_device(session: AsyncSession, device_id: uuid.UUID) -> Device | None:
    if _fs():
        return await _repo().get_device(device_id)
    return await session.get(Device, device_id)


async def add_device(session: AsyncSession, d: Device) -> Device:
    if _fs():
        return await _repo().save_device(d)
    session.add(d)
    await session.flush()
    return d


async def list_user_devices(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    device_ids: Iterable[uuid.UUID] | None = None,
    live_only: bool = False,
    not_removed: bool = False,
    created_after: datetime | None = None,
    last_used_after: datetime | None = None,
) -> list[UserDevice]:
    """``user_devices`` rows, oldest first. ``live_only``: ``trust_status <> 'removed'``;
    ``not_removed``: ``removed_at IS NULL``."""
    dids = set(device_ids) if device_ids is not None else None
    if _fs():
        from app.modules.sessions.store_specs import USER_DEVICES

        f: list[Any] = []
        if device_id is not None:
            f.append(("device_id", "==", str(device_id)))
        rows: list[UserDevice] = await _repo()._objs(
            UserDevice, USER_DEVICES, user_id=user_id, filters=tuple(f)
        )
        rows = [
            d
            for d in rows
            if (dids is None or d.device_id in dids)
            and (not live_only or d.trust_status != "removed")
            and (not not_removed or d.removed_at is None)
            and (created_after is None or d.created_at > created_after)
            and (last_used_after is None or (d.last_used_at is not None and d.last_used_at > last_used_after))
        ]
        return sorted(rows, key=lambda d: (d.created_at, str(d.id)))
    q = select(UserDevice)
    if user_id is not None:
        q = q.where(UserDevice.user_id == user_id)
    if device_id is not None:
        q = q.where(UserDevice.device_id == device_id)
    if dids is not None:
        q = q.where(UserDevice.device_id.in_(dids))
    if live_only:
        q = q.where(UserDevice.trust_status != "removed")
    if not_removed:
        q = q.where(UserDevice.removed_at.is_(None))
    if created_after is not None:
        q = q.where(UserDevice.created_at > created_after)
    if last_used_after is not None:
        q = q.where(UserDevice.last_used_at > last_used_after)
    return list((await session.execute(q.order_by(UserDevice.created_at, UserDevice.id))).scalars().all())


async def add_user_device(session: AsyncSession, ud: UserDevice) -> UserDevice:
    if _fs():
        return await _repo().save_user_device(ud)
    session.add(ud)
    await session.flush()
    return ud


async def clear_remember_tokens(session: AsyncSession, user_id: uuid.UUID) -> int:
    if _fs():
        return await _repo().clear_remember(user_id)
    r = await session.execute(
        update(UserDevice)
        .where(UserDevice.user_id == user_id, UserDevice.remember_token_hash.is_not(None))
        .values(remember_token_hash=None, remember_until=None)
    )
    return int(getattr(r, "rowcount", 0) or 0)


# --------------------------------------------------------------------------- login attempts / observations


async def get_login_attempt(session: AsyncSession, attempt_id: uuid.UUID) -> LoginAttempt | None:
    if _fs():
        from app.modules.sessions.store_specs import ATTEMPTS

        return await _repo()._get_obj(LoginAttempt, ATTEMPTS, str(attempt_id))
    return (
        await session.execute(select(LoginAttempt).where(LoginAttempt.id == attempt_id))
    ).scalar_one_or_none()


async def list_login_attempts(
    session: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
    user_id: uuid.UUID | None = None,
    outcomes: Iterable[str] | None = None,
    ip: str | None = None,
) -> list[LoginAttempt]:
    """Attempts with ``since < attempted_at <= until``, oldest first. On Firestore without a
    ``user_id``/``ip`` this scans the window (security reports only)."""
    outs = set(outcomes) if outcomes is not None else None
    if _fs():
        from app.modules.sessions.store_specs import ATTEMPTS

        f: list[Any] = []
        if user_id is not None:
            f.append(("user_id", "==", str(user_id)))
        elif ip is not None:
            f.append(("ip", "==", ip))
        f.append(("attempted_at", ">", since))
        rows: list[LoginAttempt] = await _repo()._objs(
            LoginAttempt, ATTEMPTS, filters=tuple(f), order_by=(("attempted_at", "asc"),)
        )
        return [
            a
            for a in rows
            if (until is None or a.attempted_at <= until)
            and (outs is None or a.outcome in outs)
            and (ip is None or a.ip == ip)
        ]
    q = select(LoginAttempt).where(LoginAttempt.attempted_at > since)
    if until is not None:
        q = q.where(LoginAttempt.attempted_at <= until)
    if user_id is not None:
        q = q.where(LoginAttempt.user_id == user_id)
    if outs is not None:
        q = q.where(LoginAttempt.outcome.in_(outs))
    if ip is not None:
        q = q.where(LoginAttempt.ip == ip)
    return list(
        (await session.execute(q.order_by(LoginAttempt.attempted_at, LoginAttempt.id))).scalars().all()
    )


async def list_observations(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    auth_session_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[SessionNetworkObservation]:
    """Network observations with ``since < first_seen_at <= until``, oldest first."""
    if _fs():
        from app.modules.sessions.store_specs import OBSERVATIONS

        f: list[Any] = []
        if user_id is not None:
            f.append(("user_id", "==", str(user_id)))
        if auth_session_id is not None:
            f.append(("auth_session_id", "==", str(auth_session_id)))
        rows: list[SessionNetworkObservation] = await _repo()._objs(
            SessionNetworkObservation, OBSERVATIONS, filters=tuple(f)
        )
        rows = [
            o
            for o in rows
            if (since is None or o.first_seen_at > since) and (until is None or o.first_seen_at <= until)
        ]
        return sorted(rows, key=lambda o: (o.first_seen_at, str(o.id)))
    q = select(SessionNetworkObservation)
    if user_id is not None:
        q = q.where(SessionNetworkObservation.user_id == user_id)
    if auth_session_id is not None:
        q = q.where(SessionNetworkObservation.auth_session_id == auth_session_id)
    if since is not None:
        q = q.where(SessionNetworkObservation.first_seen_at > since)
    if until is not None:
        q = q.where(SessionNetworkObservation.first_seen_at <= until)
    q = q.order_by(SessionNetworkObservation.first_seen_at, SessionNetworkObservation.id)
    return list((await session.execute(q)).scalars().all())


async def add_observation(session: AsyncSession, o: SessionNetworkObservation) -> None:
    if _fs():
        await _repo().add_observation(o)
        return
    session.add(o)
    await session.flush()


def now() -> datetime:
    return clock.now()


async def remove_user_devices(
    session: AsyncSession, user_id: uuid.UUID, *, reason: str, now: datetime
) -> int:
    """Mark every non-removed device of a user ``removed`` (remember tokens cleared); returns the
    number changed. Used when a password reset / protect-lock signs a user out everywhere."""
    if _fs():
        from app.modules.identity import fs_uow

        n = 0
        for ud in await list_user_devices(session, user_id=user_id, live_only=True):
            ud.trust_status = "removed"
            ud.removed_at = now
            ud.removed_reason = reason
            ud.remember_token_hash = None
            ud.remember_until = None
            await _repo().save_user_device(ud)
            fs_uow.discard(ud)
            n += 1
        return n
    r = await session.execute(
        update(UserDevice)
        .where(UserDevice.user_id == user_id, UserDevice.trust_status != "removed")
        .values(
            trust_status="removed",
            removed_at=now,
            removed_reason=reason,
            remember_token_hash=None,
            remember_until=None,
        )
    )
    return int(getattr(r, "rowcount", 0) or 0)


async def user_device_by_remember(
    session: AsyncSession, token_hash: bytes, *, for_update: bool = False
) -> UserDevice | None:
    """The user device holding this remember-me token hash (Postgres: optionally row-locked)."""
    if _fs():
        return await _repo().user_device_by_remember(token_hash)
    q = select(UserDevice).where(UserDevice.remember_token_hash == token_hash)
    if for_update:
        q = q.with_for_update()
    return (await session.execute(q)).scalar_one_or_none()


def ip_prefix(ip: Any) -> str | None:
    """IPv4 /24 or IPv6 /48 network of an address (``None`` if absent/invalid)."""
    from app.modules.sessions.store_specs import ip_prefix as _prefix

    return _prefix(ip)


async def list_login_attempts_in_prefix(
    session: AsyncSession,
    ip: str,
    *,
    since: datetime,
    until: datetime | None = None,
    outcomes: Iterable[str] | None = None,
) -> list[LoginAttempt]:
    """Attempts from the /24 (IPv4) or /48 (IPv6) network of ``ip`` with
    ``since < attempted_at <= until``, oldest first: the same rows as filtering every attempt of
    the window by network, without scanning them. Postgres: ``ip << network``; Firestore: the
    indexed ``ip_prefix`` field (written on insert and by the backfill)."""
    net = ip_prefix(ip)
    if net is None:
        return []
    outs = set(outcomes) if outcomes is not None else None
    if _fs():
        from app.modules.sessions.store_specs import ATTEMPTS

        rows: list[LoginAttempt] = await _repo()._objs(
            LoginAttempt,
            ATTEMPTS,
            filters=(("ip_prefix", "==", net), ("attempted_at", ">", since)),
            order_by=(("attempted_at", "asc"),),
        )
        return [
            a
            for a in rows
            if (until is None or a.attempted_at <= until) and (outs is None or a.outcome in outs)
        ]
    from sqlalchemy import cast
    from sqlalchemy.dialects.postgresql import CIDR

    q = select(LoginAttempt).where(
        LoginAttempt.attempted_at > since, LoginAttempt.ip.op("<<=")(cast(net, CIDR))
    )
    if until is not None:
        q = q.where(LoginAttempt.attempted_at <= until)
    if outs is not None:
        q = q.where(LoginAttempt.outcome.in_(outs))
    return list(
        (await session.execute(q.order_by(LoginAttempt.attempted_at, LoginAttempt.id))).scalars().all()
    )


async def shared_devices_of_user(
    session: AsyncSession, user_id: uuid.UUID, *, min_accounts: int, since: datetime
) -> list[uuid.UUID]:
    """Security SH-11: ``device_id`` of each ``user_devices`` row of ``user_id`` whose device was
    used (``last_used_at > since``) by at least ``min_accounts`` distinct accounts -- the rows of
    ``SELECT device_id FROM user_devices WHERE user_id = :u AND device_id IN (SELECT device_id
    FROM user_devices WHERE last_used_at > :since GROUP BY device_id HAVING count(DISTINCT
    user_id) >= :n)``. Firestore: one query per device of the user (no collection scan)."""
    if _fs():
        mine = await list_user_devices(session, user_id=user_id)
        qualifying: dict[uuid.UUID, bool] = {}
        for dev in dict.fromkeys(ud.device_id for ud in mine):
            users = {
                ud.user_id for ud in await list_user_devices(session, device_id=dev, last_used_after=since)
            }
            qualifying[dev] = len(users) >= min_accounts
        return [ud.device_id for ud in mine if qualifying.get(ud.device_id)]
    from sqlalchemy import func

    shared = (
        select(UserDevice.device_id)
        .where(UserDevice.last_used_at > since)
        .group_by(UserDevice.device_id)
        .having(func.count(func.distinct(UserDevice.user_id)) >= min_accounts)
    )
    q = select(UserDevice.device_id).where(UserDevice.user_id == user_id, UserDevice.device_id.in_(shared))
    return list((await session.execute(q)).scalars().all())
