"""Store-neutral identity API for other modules (``TD_STORE_IDENTITY`` = postgres | firestore).

Other modules must not import ``identity.models`` to run SQL on identity tables: once the
switch is ``firestore`` those tables are empty in Postgres. They call these functions instead.
Every function takes the caller's ``session``. On Postgres it runs the same SQL the callers ran
(their RLS context applies). On Firestore it reads through ``IdentityRepo``, a named system job.
Objects are ORM instances: tracked rows on Postgres, transient copies on Firestore. **Change
data only through the write functions here**, never by mutating a returned object.

Consumers to switch (see docs/firebase/agents/data-access.md §6 for every call site): admin,
admissions, assessments, commerce, hub, learning, media, notifications, paths, security,
support, seeds.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.backend import uses_firestore
from app.modules.identity import clock
from app.modules.identity.models import (
    Consent,
    GuardianConsent,
    MfaFactor,
    PasswordResetToken,
    User,
    UserCredential,
    UserProfile,
    VerificationToken,
)


def _fs() -> bool:
    return uses_firestore("identity")


def _repo() -> Any:
    from app.modules.identity.repo_firestore import system_repo

    return system_repo()


@dataclass(frozen=True, slots=True)
class UserCard:
    """Contact/display fields other modules show (one batched read instead of a join)."""

    id: uuid.UUID
    email: str | None
    phone_e164: str | None
    username: str | None
    status: str
    is_minor: bool
    full_name: str | None
    display_name: str | None


# --------------------------------------------------------------------------- users


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    if _fs():
        return await _repo().get_user(user_id)
    return await session.get(User, user_id)


async def get_users(session: AsyncSession, user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, User]:
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    if _fs():
        return await _repo().get_users(ids)
    rows = (await session.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
    if _fs():
        return await _repo().get_profile(user_id)
    return await session.get(UserProfile, user_id)


async def get_profiles(session: AsyncSession, user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, UserProfile]:
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    if _fs():
        from app.modules.identity.fs_codec import doc_obj
        from app.modules.identity.store_specs import PROFILES

        docs = await _repo().store.get_many(PROFILES, [str(i) for i in ids])
        return {uuid.UUID(k): doc_obj(UserProfile, d.data) for k, d in docs.items()}
    rows = (await session.execute(select(UserProfile).where(UserProfile.user_id.in_(ids)))).scalars().all()
    return {p.user_id: p for p in rows}


async def user_cards(session: AsyncSession, user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, UserCard]:
    """id -> card for existing users (``users LEFT JOIN user_profiles``)."""
    ids = list(dict.fromkeys(user_ids))
    users = await get_users(session, ids)
    profs = await get_profiles(session, users)
    out: dict[uuid.UUID, UserCard] = {}
    for uid, u in users.items():
        p = profs.get(uid)
        out[uid] = UserCard(
            uid,
            u.email,
            u.phone_e164,
            u.username,
            u.status,
            bool(u.is_minor),
            p.full_name if p else None,
            p.display_name if p else None,
        )
    return out


async def find_user(session: AsyncSession, kind: str, value: str) -> User | None:
    """Live user by ``email`` / ``phone`` / ``username`` (``deleted_at IS NULL``)."""
    from app.modules.identity.service import find_user as _find

    return await _find(session, kind, value)


async def users_by_emails(session: AsyncSession, emails: Iterable[str]) -> dict[str, User]:
    """Live users by (lower-case) email."""
    wanted = list(dict.fromkeys(e.strip().lower() for e in emails if e))
    if not wanted:
        return {}
    if _fs():
        out: dict[str, User] = {}
        for e in wanted:
            u = await _repo().find_user("email", e)
            if u is not None:
                out[e] = u
        return out
    rows = (
        (await session.execute(select(User).where(User.email.in_(wanted), User.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    return {u.email: u for u in rows if u.email}


async def username_taken(session: AsyncSession, username: str) -> bool:
    """Any account (live or deleted) holds ``username`` (admissions username generator)."""
    if _fs():
        return bool(await list_users(session, username=username))
    return (await session.execute(select(User.id).where(User.username == username))).first() is not None


async def list_users(
    session: AsyncSession,
    *,
    status: str | None = None,
    exclude_status: str | None = None,
    is_synthetic: bool | None = None,
    is_minor: bool | None = None,
    created_after: datetime | None = None,
    exclude_ids: Iterable[uuid.UUID] = (),
    username: str | None = None,
) -> list[User]:
    """Users matching every given filter (dashboards and counts: ``len(list_users(...))``)."""
    excl = set(exclude_ids)
    if _fs():
        from app.modules.identity.store_specs import USERS

        filters: list[Any] = []
        if status is not None:
            filters.append(("status", "==", status))
        if is_synthetic is not None:
            filters.append(("is_synthetic", "==", is_synthetic))
        if is_minor is not None:
            filters.append(("is_minor", "==", is_minor))
        if username is not None:
            filters.append(("username", "==", username))
        rows: list[User] = await _repo()._objs(User, USERS, filters=tuple(filters))
        return [
            u
            for u in rows
            if (exclude_status is None or u.status != exclude_status)
            and (created_after is None or u.created_at > created_after)
            and u.id not in excl
        ]
    q = select(User)
    if status is not None:
        q = q.where(User.status == status)
    if exclude_status is not None:
        q = q.where(User.status != exclude_status)
    if is_synthetic is not None:
        q = q.where(User.is_synthetic.is_(is_synthetic))
    if is_minor is not None:
        q = q.where(User.is_minor.is_(is_minor))
    if created_after is not None:
        q = q.where(User.created_at > created_after)
    if excl:
        q = q.where(User.id.not_in(excl))
    if username is not None:
        q = q.where(User.username == username)
    return list((await session.execute(q)).scalars().all())


async def status_counts(session: AsyncSession) -> dict[str, int]:
    """``SELECT status, count(*) FROM users GROUP BY status``."""
    if _fs():
        out: dict[str, int] = {}
        for u in await list_users(session):
            out[u.status] = out.get(u.status, 0) + 1
        return out
    return dict((await session.execute(select(User.status, func.count()).group_by(User.status))).all())


async def search_users(
    session: AsyncSession,
    *,
    term: str | None = None,
    status: str | None = None,
    include_deleted: bool = True,
    after: uuid.UUID | None = None,
    limit: int = 50,
) -> list[tuple[User, UserProfile | None]]:
    """Admin / support search: by id, email or full name substring, or phone digits; newest id
    first; keyset ``after`` (an id). Returns up to ``limit + 1`` rows (caller detects more)."""
    t = (term or "").strip().lower()
    digits = "".join(c for c in t if c.isdigit())
    as_id: uuid.UUID | None = None
    try:
        as_id = uuid.UUID(t) if t else None
    except ValueError:
        as_id = None
    if _fs():
        users = await list_users(session, status=status)
        profs = await get_profiles(session, [u.id for u in users])
        rows = []
        for u in users:
            p = profs.get(u.id)
            if not include_deleted and u.status == "deleted":
                continue
            if after is not None and not u.id < after:
                continue
            if as_id is not None:
                if u.id != as_id:
                    continue
            elif t:
                hit = t in (u.email or "").lower() or (p is not None and t in (p.full_name or "").lower())
                if not hit and len(digits) >= 4:
                    hit = digits in (u.phone_e164 or "")
                if not hit:
                    continue
            rows.append((u, p))
        rows.sort(key=lambda r: r[0].id, reverse=True)
        return rows[: limit + 1]
    qry = select(User, UserProfile).outerjoin(UserProfile, UserProfile.user_id == User.id)
    if not include_deleted:
        qry = qry.where(User.status != "deleted")
    if status:
        qry = qry.where(User.status == status)
    if as_id is not None:
        qry = qry.where(User.id == as_id)
    elif t:
        like = f"%{t}%"
        conds = [func.lower(User.email).like(like), func.lower(UserProfile.full_name).like(like)]
        if len(digits) >= 4:
            conds.append(User.phone_e164.like(f"%{digits}%"))
        qry = qry.where(or_(*conds))
    if after is not None:
        qry = qry.where(User.id < after)
    res = (await session.execute(qry.order_by(User.id.desc()).limit(limit + 1))).all()
    return [(u, p) for u, p in res]


async def update_user(session: AsyncSession, user_id: uuid.UUID, **changes: Any) -> None:
    """Set columns of one user (status, must_change_password, restriction_level,
    sessions_valid_after, ...). Contact changes keep uniqueness on both stores."""
    if not changes:
        return
    if _fs():
        await _repo().update_user(user_id, **changes)
        return
    await session.execute(update(User).where(User.id == user_id).values(**changes))


async def create_user(
    session: AsyncSession,
    user: User,
    profile: UserProfile | None = None,
    credential: UserCredential | None = None,
) -> User:
    """Insert a user (+ profile, + credential). Postgres: added to the caller's transaction."""
    if _fs():
        created: User = await _repo().create_user(user, profile)
        if credential is not None:
            await _repo().save_credential(credential)
        return created
    session.add(user)
    await session.flush()
    if profile is not None:
        session.add(profile)
    if credential is not None:
        session.add(credential)
    await session.flush()
    return user


async def save_user(session: AsyncSession, user: User) -> User:
    """Persist every attribute of ``user`` (a row returned by this module)."""
    if _fs():
        return await _repo().save_user(user)
    await session.flush()
    return user


async def save_profile(session: AsyncSession, profile: UserProfile) -> UserProfile:
    if _fs():
        return await _repo().save_profile(profile)
    await session.merge(profile)
    await session.flush()
    return profile


async def save_credential(session: AsyncSession, cred: UserCredential) -> UserCredential:
    if _fs():
        return await _repo().save_credential(cred)
    await session.merge(cred)
    await session.flush()
    return cred


async def get_credential(session: AsyncSession, user_id: uuid.UUID) -> UserCredential | None:
    from app.modules.identity.service import get_credential as _get

    return await _get(session, user_id)


# --------------------------------------------------------------------------- MFA


async def active_factors(session: AsyncSession, user_id: uuid.UUID) -> list[MfaFactor]:
    from app.modules.identity.service import active_factors as _af

    return await _af(session, user_id)


async def add_factor(session: AsyncSession, f: MfaFactor) -> MfaFactor:
    if _fs():
        return await _repo().save_factor(f)
    session.add(f)
    await session.flush()
    return f


async def save_factor(session: AsyncSession, f: MfaFactor) -> MfaFactor:
    if _fs():
        return await _repo().save_factor(f)
    await session.flush()
    return f


async def revoke_factors(session: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None) -> int:
    """Revoke every active factor of a user (MFA reset). Returns the number revoked."""
    now = now or clock.now()
    if _fs():
        n = 0
        for f in await _repo().active_factors(user_id):
            f.revoked_at = now
            await _repo().save_factor(f)
            n += 1
        return n
    r = await session.execute(
        update(MfaFactor)
        .where(MfaFactor.user_id == user_id, MfaFactor.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return int(getattr(r, "rowcount", 0) or 0)


# --------------------------------------------------------------------------- consents / guardian


async def consents_of(session: AsyncSession, user_id: uuid.UUID) -> list[Consent]:
    if _fs():
        rows: list[Consent] = await _repo().consents_for(user_id)
        return sorted(rows, key=lambda c: (c.created_at, str(c.id)))
    q = select(Consent).where(Consent.user_id == user_id).order_by(Consent.created_at, Consent.id)
    return list((await session.execute(q)).scalars().all())


async def latest_consent_action(session: AsyncSession, user_id: uuid.UUID, purpose: str) -> str | None:
    """Newest ``action`` recorded for ``purpose`` (any context), else None."""
    rows = [c for c in await consents_of(session, user_id) if c.purpose == purpose]
    return rows[-1].action if rows else None


async def has_verified_guardian_consent(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """A verified, unrevoked guardian consent exists for the child ``user_id``."""
    if _fs():
        from app.modules.identity.store_specs import GUARDIANS

        rows = await _repo()._objs(GuardianConsent, GUARDIANS, user_id=user_id)
        return any(g.status == "verified" and g.revoked_at is None for g in rows)
    n = (
        await session.execute(
            select(func.count())
            .select_from(GuardianConsent)
            .where(
                GuardianConsent.child_user_id == user_id,
                GuardianConsent.status == "verified",
                GuardianConsent.revoked_at.is_(None),
            )
        )
    ).scalar_one()
    return int(n) > 0


# --------------------------------------------------------------------------- tokens (read-only views)


async def verification_tokens_of(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    purpose: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> list[VerificationToken]:
    """A user's verification tokens / OTPs, oldest first (security timeline, support caps)."""
    if _fs():
        from app.modules.identity.store_specs import VTOKENS

        f: list[Any] = [("user_id", "==", str(user_id))]
        if purpose:
            f.append(("purpose", "==", purpose))
        rows: list[VerificationToken] = await _repo()._objs(VerificationToken, VTOKENS, filters=tuple(f))
    else:
        q = select(VerificationToken).where(VerificationToken.user_id == user_id)
        if purpose:
            q = q.where(VerificationToken.purpose == purpose)
        rows = list((await session.execute(q)).scalars().all())
    rows = [
        t
        for t in rows
        if (created_after is None or t.created_at > created_after)
        and (created_before is None or t.created_at <= created_before)
    ]
    return sorted(rows, key=lambda t: (t.created_at, str(t.id)))


async def reset_tokens_of(
    session: AsyncSession, user_id: uuid.UUID, *, created_after: datetime | None = None
) -> list[PasswordResetToken]:
    if _fs():
        from app.modules.identity.store_specs import RESETS

        rows: list[PasswordResetToken] = await _repo()._objs(
            PasswordResetToken, RESETS, filters=(("user_id", "==", str(user_id)),)
        )
    else:
        rows = list(
            (await session.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user_id)))
            .scalars()
            .all()
        )
    rows = [t for t in rows if created_after is None or t.created_at > created_after]
    return sorted(rows, key=lambda t: (t.created_at, str(t.id)))


# --------------------------------------------------------------------------- web links


def web_base_url() -> str:
    """The web app's public base URL (``identity.links``), for links in emails / documents."""
    from app.modules.identity.links import web_base_url as _base

    return _base()


def web_link(name: str, **params: str) -> str:
    """Absolute link to a named web page (``identity.links.web_link``)."""
    from app.modules.identity.links import web_link as _link

    return _link(name, **params)


# --------------------------------------------------------------------------- one-time codes


async def otp_send_allowed(session: AsyncSession, channel: str, destination: str) -> int:
    """0 if a new OTP may be sent to ``destination`` now, else Retry-After seconds (send caps)."""
    from app.modules.identity.service import otp_send_allowed as _allowed

    return await _allowed(session, channel, destination)


async def create_otp(
    session: AsyncSession,
    *,
    purpose: str,
    channel: str,
    destination: str,
    user_id: uuid.UUID | None = None,
    auth_session_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    ip: str | None = None,
) -> tuple[VerificationToken, str]:
    """Issue a 6-digit OTP for this binding (earlier open OTPs of it expire). Returns
    ``(token, code)``; the caller sends the code."""
    from app.modules.identity.service import create_otp as _create

    return await _create(
        session,
        purpose=purpose,
        channel=channel,
        destination=destination,
        user_id=user_id,
        auth_session_id=auth_session_id,
        device_id=device_id,
        ip=ip,
    )


async def check_otp(
    session: AsyncSession,
    *,
    purpose: str,
    code: str,
    user_id: uuid.UUID | None = None,
    auth_session_id: uuid.UUID | None = None,
) -> Any:
    """Verify the latest OTP of the binding (single use; attempts counted). Returns an
    ``identity.service.OtpCheck`` (``ok``, ``problem``, ``token``)."""
    from app.modules.identity.service import check_otp as _check

    return await _check(session, purpose=purpose, code=code, user_id=user_id, auth_session_id=auth_session_id)


async def users_ordered_by_full_name(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> list[tuple[uuid.UUID, str | None]]:
    """``(user_id, full_name)`` for ``user_ids`` ordered ``full_name NULLS LAST, user_id``
    (users without a profile have ``None``). Postgres: the ORDER BY runs in SQL, so the
    database collation applies exactly as before; Firestore: ``identity.textsort.text_key``."""
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return []
    if _fs():
        from app.modules.identity.textsort import text_key

        profs = await get_profiles(session, ids)
        names = {u: (profs[u].full_name if u in profs else None) for u in ids}
        return sorted(
            ((u, names[u]) for u in ids),
            key=lambda t: (t[1] is None, text_key(t[1]), t[0].bytes),
        )
    from sqlalchemy import column, values
    from sqlalchemy.dialects.postgresql import UUID as PGUUID

    wanted = values(column("id", PGUUID(as_uuid=True)), name="wanted").data([(i,) for i in ids])
    q = (
        select(wanted.c.id, UserProfile.full_name)
        .select_from(wanted)
        .outerjoin(UserProfile, UserProfile.user_id == wanted.c.id)
        .order_by(UserProfile.full_name.nulls_last(), wanted.c.id)
    )
    return [(u, n) for u, n in (await session.execute(q)).all()]
