"""Mentoring + résumé review business logic (api-spec PLC-36..52, FR-PLC-010/015, SoD-11).

RLS model:

* student paths run in the principal's tenant context (``mentor_slots`` TN visibility,
  ``mentor_bookings`` / ``interview_feedback`` U, ``resumes`` / ``resume_reviews`` O);
* mentor/staff paths authorise in the application first (permission held at some scope +
  slot ownership or SoD-11 assignment) and then read/write under a named system context
  (``as_system``) — the documented "mentor visibility via API";
* ``mentor_notes`` is only readable by its author or a system context; there is no student
  route to it.

Quotas: ``entitlements.service.consume_quota`` draws from the usable entitlement ending
soonest; credit back uses the entitlements module's public ``lock`` + ``record_event``
(``quota_credited``) — no edits to that module.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import auth as core_auth
from app.core.access import check_access
from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, ScopeRef
from app.core.company import COMPANY_ORG_ID
from app.core.db import system_context, tenant_context
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.entitlements import public as ent_svc
from app.modules.entitlements.public import Entitlement
from app.modules.mentoring.models import (
    InterviewFeedback,
    MentorBooking,
    MentorNote,
    MentorSlot,
    Resume,
    ResumeReview,
)
from app.modules.mentoring.schemas import FeedbackIn, ResumeIn, ReviewFeedbackIn, SlotsIn

PERM_SLOTS = "mentor.slot.manage"
PERM_FEEDBACK = "mentor.feedback.write"
PERM_NOTES = "mentor.notes.read"

LIVE = ("booked", "rescheduled")
FREE_CHANGE = timedelta(hours=12)
STUDENT_NO_SHOW_AFTER = timedelta(minutes=10)
FEEDBACK_DUE = timedelta(hours=48)
MAX_AHEAD = timedelta(days=180)
PDF_MAX_BYTES = 5 * 1024 * 1024
RESTRICTION_LOCKS = frozenset({"premium_locked", "learning_locked", "content_locked"})
QuotaKey = Literal["mentor_sessions", "resume_reviews"]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _s(v: uuid.UUID | None) -> str | None:
    return str(v) if v else None


def _ends(slot: MentorSlot) -> datetime:
    return slot.starts_at + timedelta(minutes=slot.duration_minutes)


@asynccontextmanager
async def as_system(session: AsyncSession, principal: Principal, job: str) -> AsyncIterator[None]:
    """Run a block under a named system context, flush, then restore the principal's. Without a
    Postgres session (Firebase stack) there is no RLS context to switch: the block just runs."""
    if not session:
        yield
        return
    await system_context(session, job)
    try:
        yield
        await session.flush()
    finally:
        await tenant_context(session, principal)


def _unavailable(detail: str = "This slot is no longer available.") -> ProblemError:
    return ProblemError("slot_unavailable", 409, "Slot unavailable", detail)


def _bad_state(detail: str) -> ProblemError:
    return ProblemError("invalid_state_transition", detail=detail)


def _field_error(field: str, message: str, code: str = "invalid") -> ProblemError:
    return ProblemError("validation_failed", errors=[{"field": field, "code": code, "message": message}])


# --------------------------------------------------------------------------- permissions / SoD-11


def _grant_scopes(principal: Principal) -> list[ScopeRef]:
    out: list[ScopeRef] = [PLATFORM_SCOPE]
    for g in principal.grants:
        if g.scope_type != "platform" and g.scope_id is not None:
            ref = ScopeRef(g.scope_type, g.scope_id)
            if ref not in out:
                out.append(ref)
    return out


async def scopes_holding(request: Request | None, principal: Principal, perm: str) -> list[ScopeRef]:
    """Every scope (platform + each grant's own scope) at which ``perm`` is held."""
    return [
        s for s in _grant_scopes(principal) if await core_auth.check_permission(principal, perm, s, request)
    ]


async def require_anywhere(request: Request | None, principal: Principal, perm: str) -> list[ScopeRef]:
    scopes = await scopes_holding(request, principal, perm)
    if not scopes:
        raise ProblemError("permission_denied", permission=perm)
    return scopes


async def assigned_batches(
    session: AsyncSession, request: Request | None, principal: Principal, perm: str = PERM_NOTES
) -> dict[uuid.UUID, tuple[str, uuid.UUID]]:
    """batch_id -> (name, organization_id) for every active batch where the caller holds
    ``perm`` through a batch grant (single company: no organization grants exist)."""
    from app.modules.orgs import public as orgs_public

    batch_ids = {g.scope_id for g in principal.grants if g.scope_type == "batch" and g.scope_id}
    if not batch_ids:
        return {}
    async with as_system(session, principal, "mentoring.scope"):
        found = await orgs_public.get_batches(session, batch_ids)
    rows = sorted(
        ((b.id, b.name, b.organization_id) for b in found.values() if b.status == "active"),
        key=lambda r: r[0],
    )
    out: dict[uuid.UUID, tuple[str, uuid.UUID]] = {}
    for bid, name, org in rows:
        if await core_auth.check_permission(principal, perm, ScopeRef("batch", bid), request):
            out[bid] = (name, org)
    return out


async def batch_students(
    session: AsyncSession,
    principal: Principal,
    batches: dict[uuid.UUID, tuple[str, uuid.UUID]],
    user_id: uuid.UUID | None = None,
) -> list[tuple[uuid.UUID, str | None, uuid.UUID]]:
    """(student_id, name, batch_id) rows for active student members of ``batches``."""
    if not batches:
        return []
    from app.modules.identity import public as identity_public
    from app.modules.orgs import public as orgs_public

    async with as_system(session, principal, "mentoring.students"):
        members = [
            m
            for m in await orgs_public.batch_members(
                session,
                batch_ids=list(batches),
                user_ids=[user_id] if user_id is not None else None,
                member_role="student",
                active_only=False,
            )
            if m.status == "active"
        ]
        users = await identity_public.get_users(session, {m.user_id for m in members})
        profs = await identity_public.get_profiles(session, users)
    rows = []
    for m in members:
        u = users.get(m.user_id)
        if u is None or u.deleted_at is not None:
            continue
        p = profs.get(m.user_id)
        rows.append((m.user_id, (p.display_name or p.full_name) if p else None, m.batch_id))
    return sorted(set(rows), key=lambda r: (str(r[0]), str(r[2])))


async def booked_students(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID | None = None
) -> set[uuid.UUID]:
    """Students who booked a session with the caller (booking-based assignment, SoD-11)."""
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.booked_students(session, principal, user_id)
    q = (
        select(MentorBooking.user_id)
        .join(MentorSlot, MentorSlot.id == MentorBooking.mentor_slot_id)
        .where(MentorSlot.mentor_id == principal.user_id)
        .distinct()
    )
    if user_id is not None:
        q = q.where(MentorBooking.user_id == user_id)
    async with as_system(session, principal, "mentoring.booked_students"):
        return set((await session.execute(q)).scalars())


async def is_assigned(
    session: AsyncSession, request: Request | None, principal: Principal, student_id: uuid.UUID, perm: str
) -> bool:
    if student_id == principal.user_id:
        return False
    if await booked_students(session, principal, student_id):
        return True
    batches = await assigned_batches(session, request, principal, perm)
    return bool(await batch_students(session, principal, batches, student_id))


async def names(
    session: AsyncSession, principal: Principal, ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, str | None]:
    wanted = list({i for i in ids if i})
    if not wanted:
        return {}
    from app.modules.identity import public as identity_public

    async with as_system(session, principal, "mentoring.names"):
        cards = await identity_public.user_cards(session, wanted)
    return {uid: c.display_name or c.full_name for uid, c in cards.items()}


# --------------------------------------------------------------------------- entitlements


def _usable(now: datetime) -> list[Any]:
    return [
        Entitlement.status.in_(("active", "grace")),
        Entitlement.starts_at <= now,
        or_(Entitlement.ends_at.is_(None), Entitlement.ends_at > now, Entitlement.grace_ends_at > now),
    ]


async def quota_summary(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    ents = await ent_svc.usable_entitlements(session, principal.user_id, utcnow())
    pkg = [
        e for e in ents if e.mentor_sessions_remaining is not None or e.resume_reviews_remaining is not None
    ]
    return {
        "has_package": bool(pkg),
        "mentor_sessions_remaining": sum(e.mentor_sessions_remaining or 0 for e in pkg),
        "resume_reviews_remaining": sum(e.resume_reviews_remaining or 0 for e in pkg),
    }


def _entitlement_required(reason: str) -> ProblemError:
    return ProblemError(
        "entitlement_required",
        detail="Mentoring and résumé reviews need the premium placement package.",
        resource_type="placement_package",
        reason=reason,
    )


async def require_package(session: AsyncSession, principal: Principal, quota: QuotaKey) -> None:
    """Premium placement package gate (PLC-36/37/50). Restricted accounts are denied
    (BR-ENT-04); product-backed entitlements are confirmed through ``app.core.access``."""
    if principal.restriction_level >= 3 or RESTRICTION_LOCKS & set(principal.restrictions):
        raise _entitlement_required("restricted")
    field_name = ent_svc.QUOTA_FEATURES[quota]
    ents = [
        e
        for e in await ent_svc.usable_entitlements(session, principal.user_id, utcnow())
        if getattr(e, field_name) is not None
    ]
    if not ents:
        raise _entitlement_required("no_entitlement")
    reason = "no_entitlement"
    for e in ents:
        if e.product_id is None:
            return
        decision = await check_access(session, principal, "product", e.product_id)
        if decision.allowed:
            return
        reason = decision.reason
    raise _entitlement_required(reason)


async def consume(
    session: AsyncSession, principal: Principal, quota: QuotaKey, source_ref: uuid.UUID
) -> Entitlement:
    ent = await ent_svc.consume_quota(
        session, principal.user_id, quota, ent_svc.Actor.user(principal), source_ref=source_ref
    )
    if ent is None:
        raise _entitlement_required("quota_exhausted")
    return ent


async def credit_back(
    session: AsyncSession, principal: Principal, booking: MentorBooking, *, reason: str
) -> bool:
    """Return the booking's session credit to its source entitlement (FR-PLC-010)."""
    if not booking.quota_consumed:
        return False
    async with as_system(session, principal, "mentoring.credit_back"):
        if booking.entitlement_id is not None:
            await ent_svc.credit_quota(
                session,
                booking.entitlement_id,
                "mentor_sessions",
                ent_svc.Actor.user(principal),
                reason=reason,
                source_ref=booking.id,
            )
        booking.quota_consumed = False
    return True


# --------------------------------------------------------------------------- JSON shapes


def slot_json(s: MentorSlot, nm: dict[uuid.UUID, str | None]) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "mentor_id": str(s.mentor_id),
        "mentor_name": nm.get(s.mentor_id),
        "organization_id": _s(s.organization_id),
        "starts_at": _iso(s.starts_at),
        "ends_at": _iso(_ends(s)),
        "duration_minutes": s.duration_minutes,
        "session_kind": s.session_kind,
        "company_id": _s(s.company_id),
        "status": s.status,
    }


def feedback_json(f: InterviewFeedback, slot: MentorSlot | None) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "booking_id": str(f.mentor_booking_id),
        "mentor_id": str(f.mentor_id),
        "scores": f.scores,
        "comments": f.comments,
        "released_at": _iso(f.released_at),
        "created_at": _iso(f.created_at),
        "starts_at": _iso(slot.starts_at) if slot else None,
        "session_kind": slot.session_kind if slot else None,
    }


def note_json(n: MentorNote, nm: dict[uuid.UUID, str | None]) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "student_id": str(n.student_id),
        "author_id": str(n.author_id),
        "author_name": nm.get(n.author_id),
        "booking_id": _s(n.mentor_booking_id),
        "body": n.body,
        "created_at": _iso(n.created_at),
    }


async def bookings_json(
    session: AsyncSession,
    principal: Principal,
    bookings: Sequence[MentorBooking],
    *,
    mentor_view: bool = False,
) -> list[dict[str, Any]]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.bookings_json(session, principal, bookings, mentor_view=mentor_view)
    if not bookings:
        return []
    ids = [b.id for b in bookings]
    async with as_system(session, principal, "mentoring.bookings_read"):
        slots = {
            s.id: s
            for s in (
                await session.execute(
                    select(MentorSlot).where(MentorSlot.id.in_({b.mentor_slot_id for b in bookings}))
                )
            ).scalars()
        }
        fbs = {
            f.mentor_booking_id: f
            for f in (
                await session.execute(
                    select(InterviewFeedback).where(InterviewFeedback.mentor_booking_id.in_(ids))
                )
            ).scalars()
        }
    return await _render_bookings(session, principal, bookings, slots, fbs, mentor_view=mentor_view)


async def _render_bookings(
    session: AsyncSession,
    principal: Principal,
    bookings: Sequence[MentorBooking],
    slots: dict[uuid.UUID, MentorSlot],
    fbs: dict[uuid.UUID, InterviewFeedback],
    *,
    mentor_view: bool,
) -> list[dict[str, Any]]:
    """Booking JSON from already-loaded slots and feedback (shared by both stores)."""
    now = utcnow()
    nm = await names(
        session, principal, [s.mentor_id for s in slots.values()] + [b.user_id for b in bookings]
    )
    out = []
    for b in bookings:
        s = slots[b.mentor_slot_id]
        f = fbs.get(b.id)
        visible = f is not None and (mentor_view or (f.released_at is not None and f.released_at <= now))
        row: dict[str, Any] = {
            "id": str(b.id),
            "slot_id": str(s.id),
            "status": b.status,
            "starts_at": _iso(s.starts_at),
            "ends_at": _iso(_ends(s)),
            "duration_minutes": s.duration_minutes,
            "session_kind": s.session_kind,
            "company_id": _s(s.company_id),
            "mentor_id": str(s.mentor_id),
            "mentor_name": nm.get(s.mentor_id),
            "meeting_url": b.meeting_url,
            "quota_consumed": b.quota_consumed,
            "credit_restored": not b.quota_consumed,
            "cancelled_at": _iso(b.cancelled_at),
            "created_at": _iso(b.created_at),
            "free_change_until": _iso(s.starts_at - FREE_CHANGE),
            "feedback": feedback_json(f, s) if visible and f is not None else None,
        }
        if mentor_view:
            due = _ends(s) + FEEDBACK_DUE
            row.update(
                {
                    "student_id": str(b.user_id),
                    "student_name": nm.get(b.user_id),
                    "feedback_due_at": _iso(due),
                    "feedback_overdue": f is None and b.status in LIVE and now > due,
                }
            )
        out.append(row)
    return out


# --------------------------------------------------------------------------- pagination (offset cursor)


def _offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    from app.core.pagination import decode_cursor

    try:
        return max(0, int(decode_cursor(cursor)["o"]))
    except (KeyError, ValueError, TypeError) as e:
        raise ProblemError("invalid_cursor") from e


def _page(offset: int, limit: int, more: bool) -> dict[str, Any]:
    from app.core.pagination import page_meta

    return page_meta({"o": offset + limit} if more else None, limit)


# --------------------------------------------------------------------------- student: slots + bookings


async def list_open_slots(
    session: AsyncSession,
    principal: Principal,
    *,
    session_kind: str | None,
    after: datetime | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.list_open_slots(
            session, principal, session_kind=session_kind, after=after, cursor=cursor, limit=limit
        )
    await require_package(session, principal, "mentor_sessions")
    now = utcnow()
    start = max(after or now, now)
    off = _offset(cursor)
    q = select(MentorSlot).where(
        MentorSlot.status == "open", MentorSlot.starts_at > start, MentorSlot.mentor_id != principal.user_id
    )
    if session_kind:
        q = q.where(MentorSlot.session_kind == session_kind)
    rows = list(
        (
            await session.execute(
                q.order_by(MentorSlot.starts_at, MentorSlot.id).offset(off).limit(limit + 1)
            )
        ).scalars()
    )
    more, rows = len(rows) > limit, rows[:limit]
    nm = await names(session, principal, [s.mentor_id for s in rows])
    return {
        "data": [slot_json(s, nm) for s in rows],
        "page": _page(off, limit, more),
        "quota": await quota_summary(session, principal),
    }


async def _visible_open_slot(session: AsyncSession, principal: Principal, slot_id: uuid.UUID) -> MentorSlot:
    """Lock a slot visible to the student under RLS (TN); 404 across tenants."""
    slot = (
        await session.execute(select(MentorSlot).where(MentorSlot.id == slot_id).with_for_update())
    ).scalar_one_or_none()
    if slot is None:
        raise ProblemError("not_found")
    if slot.status != "open" or slot.starts_at <= utcnow() or slot.mentor_id == principal.user_id:
        raise _unavailable()
    return slot


async def _check_student_overlap(
    session: AsyncSession, principal: Principal, slot: MentorSlot, ignore: uuid.UUID | None = None
) -> None:
    async with as_system(session, principal, "mentoring.overlap"):
        rows = (
            await session.execute(
                select(MentorSlot)
                .join(MentorBooking, MentorBooking.mentor_slot_id == MentorSlot.id)
                .where(
                    MentorBooking.user_id == principal.user_id,
                    MentorBooking.status.in_(LIVE),
                    MentorSlot.starts_at < _ends(slot),
                    MentorSlot.starts_at > slot.starts_at - timedelta(minutes=60),
                )
            )
        ).scalars()
        for other in rows:
            if other.id != ignore and _ends(other) > slot.starts_at:
                raise ProblemError(
                    "booking_overlap", 409, "Overlapping booking", "You already have a session at this time."
                )


async def book(
    session: AsyncSession, principal: Principal, slot_id: uuid.UUID, idem_key: str
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.book(session, principal, slot_id, idem_key)
    await require_package(session, principal, "mentor_sessions")
    slot = await _visible_open_slot(session, principal, slot_id)
    await _check_student_overlap(session, principal, slot)
    bid = uuid7()
    ent = await consume(session, principal, "mentor_sessions", bid)
    booking = MentorBooking(
        id=bid,
        mentor_slot_id=slot.id,
        user_id=principal.user_id,
        organization_id=slot.organization_id,
        entitlement_id=ent.id,
        status="booked",
        quota_consumed=True,
        idempotency_key=idem_key,
    )
    session.add(booking)
    await session.flush()
    async with as_system(session, principal, "mentoring.book"):
        slot.status = "booked"
    await emit_event(
        session,
        "mentoring.booking_created",
        {
            "booking_id": str(bid),
            "slot_id": str(slot.id),
            "user_id": str(principal.user_id),
            "mentor_id": str(slot.mentor_id),
        },
        aggregate_type="mentor_booking",
        aggregate_id=bid,
        organization_id=slot.organization_id,
    )
    await session.refresh(booking)
    return (await bookings_json(session, principal, [booking]))[0]


async def _own_live_booking(
    session: AsyncSession, principal: Principal, booking_id: uuid.UUID
) -> tuple[MentorBooking, MentorSlot]:
    b = (
        await session.execute(
            select(MentorBooking)
            .where(MentorBooking.id == booking_id, MentorBooking.user_id == principal.user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if b is None:
        raise ProblemError("not_found")
    async with as_system(session, principal, "mentoring.slot_read"):
        slot = (
            await session.execute(
                select(MentorSlot).where(MentorSlot.id == b.mentor_slot_id).with_for_update()
            )
        ).scalar_one()
    if b.status not in LIVE:
        raise _bad_state("This booking can no longer be changed.")
    if slot.starts_at <= utcnow():
        raise _bad_state("The session has already started.")
    return b, slot


async def reschedule(
    session: AsyncSession, principal: Principal, booking_id: uuid.UUID, new_slot_id: uuid.UUID
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.reschedule(session, principal, booking_id, new_slot_id)
    b, old = await _own_live_booking(session, principal, booking_id)
    if new_slot_id == old.id:
        raise _unavailable("Pick a different slot.")
    new = await _visible_open_slot(session, principal, new_slot_id)
    await _check_student_overlap(session, principal, new, ignore=old.id)
    keep = old.starts_at - utcnow() >= FREE_CHANGE
    if not keep or not b.quota_consumed:
        # < 12 h before the session: the original credit is spent; a new one is drawn.
        await require_package(session, principal, "mentor_sessions")
        ent = await consume(session, principal, "mentor_sessions", b.id)
        b.entitlement_id = ent.id
        b.quota_consumed = True
    b.mentor_slot_id = new.id
    b.status = "rescheduled"
    b.meeting_url = None
    await session.flush()
    async with as_system(session, principal, "mentoring.reschedule"):
        old.status = "open"
        new.status = "booked"
    await emit_event(
        session,
        "mentoring.booking_rescheduled",
        {
            "booking_id": str(b.id),
            "from_slot_id": str(old.id),
            "to_slot_id": str(new.id),
            "credit_kept": keep,
            "user_id": str(principal.user_id),
        },
        aggregate_type="mentor_booking",
        aggregate_id=b.id,
        organization_id=b.organization_id,
    )
    await session.refresh(b)
    return (await bookings_json(session, principal, [b]))[0]


async def cancel(session: AsyncSession, principal: Principal, booking_id: uuid.UUID) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.cancel(session, principal, booking_id)
    b, slot = await _own_live_booking(session, principal, booking_id)
    now = utcnow()
    b.status = "cancelled_by_student"
    b.cancelled_at = now
    await session.flush()
    credited = False
    if slot.starts_at - now >= FREE_CHANGE:
        credited = await credit_back(session, principal, b, reason="student_cancel_12h")
    async with as_system(session, principal, "mentoring.cancel"):
        slot.status = "open"
    await emit_event(
        session,
        "mentoring.booking_cancelled",
        {"booking_id": str(b.id), "by": "student", "credited": credited, "user_id": str(principal.user_id)},
        aggregate_type="mentor_booking",
        aggregate_id=b.id,
        organization_id=b.organization_id,
    )
    await session.refresh(b)
    return (await bookings_json(session, principal, [b]))[0]


async def my_bookings(
    session: AsyncSession, principal: Principal, *, cursor: str | None, limit: int
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.my_bookings(session, principal, cursor=cursor, limit=limit)
    off = _offset(cursor)
    rows = list(
        (
            await session.execute(
                select(MentorBooking)
                .where(MentorBooking.user_id == principal.user_id)
                .order_by(MentorBooking.created_at.desc(), MentorBooking.id.desc())
                .offset(off)
                .limit(limit + 1)
            )
        ).scalars()
    )
    more, rows = len(rows) > limit, rows[:limit]
    return {
        "data": await bookings_json(session, principal, rows),
        "page": _page(off, limit, more),
        "quota": await quota_summary(session, principal),
    }


# --------------------------------------------------------------------------- mentor: slots


def _overlaps(a_start: datetime, a_min: int, b_start: datetime, b_min: int) -> bool:
    return a_start < b_start + timedelta(minutes=b_min) and b_start < a_start + timedelta(minutes=a_min)


async def mentor_slots_json(
    session: AsyncSession, principal: Principal, slots: Sequence[MentorSlot]
) -> list[dict[str, Any]]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.mentor_slots_json(session, principal, slots)
    if not slots:
        return []
    async with as_system(session, principal, "mentoring.mentor_slots"):
        live = {
            b.mentor_slot_id: b
            for b in (
                await session.execute(
                    select(MentorBooking).where(
                        MentorBooking.mentor_slot_id.in_([s.id for s in slots]),
                        MentorBooking.status.in_((*LIVE, "completed", "student_no_show", "mentor_no_show")),
                    )
                )
            ).scalars()
        }
    return await _render_mentor_slots(session, principal, slots, live)


async def _render_mentor_slots(
    session: AsyncSession,
    principal: Principal,
    slots: Sequence[MentorSlot],
    live: dict[uuid.UUID, MentorBooking],
) -> list[dict[str, Any]]:
    nm = await names(session, principal, [s.mentor_id for s in slots] + [b.user_id for b in live.values()])
    out = []
    for s in slots:
        b = live.get(s.id)
        out.append(
            {
                **slot_json(s, nm),
                "booking_id": _s(b.id) if b else None,
                "student_id": _s(b.user_id) if b else None,
                "student_name": nm.get(b.user_id) if b else None,
            }
        )
    return out


async def create_slots(
    session: AsyncSession, request: Request | None, principal: Principal, body: SlotsIn
) -> list[dict[str, Any]]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.create_slots(session, request, principal, body)
    scopes = await require_anywhere(request, principal, PERM_SLOTS)
    # Single company: an Admin (platform grant) publishes platform slots open to every learner;
    # a batch-scoped mentor's slots belong to the company (its batch learners).
    org: uuid.UUID | None = None if PLATFORM_SCOPE in scopes else COMPANY_ORG_ID
    _validate_slot_times(body, utcnow())
    company_ids = {s.company_id for s in body.slots if s.company_id}
    async with as_system(session, principal, "mentoring.create_slots"):
        if company_ids:
            from app.modules.placement import public as placement_public

            found = await placement_public.existing_company_ids(session, company_ids)
            missing = company_ids - found
            if missing:
                raise _field_error("company_id", "Unknown company")
        lo = min(s.starts_at for s in body.slots) - timedelta(minutes=60)
        hi = max(s.starts_at + timedelta(minutes=s.duration_minutes) for s in body.slots)
        existing = list(
            (
                await session.execute(
                    select(MentorSlot)
                    .where(
                        MentorSlot.mentor_id == principal.user_id,
                        MentorSlot.status != "cancelled",
                        MentorSlot.starts_at >= lo,
                        MentorSlot.starts_at < hi,
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        _raise_slot_conflicts(body, existing)
        created = []
        for s in body.slots:
            row = MentorSlot(
                id=uuid7(),
                mentor_id=principal.user_id,
                organization_id=org,
                starts_at=s.starts_at,
                duration_minutes=s.duration_minutes,
                session_kind=s.session_kind,
                company_id=s.company_id,
                status="open",
            )
            session.add(row)
            created.append(row)
        await session.flush()
        for row in created:
            await session.refresh(row)
    return await mentor_slots_json(session, principal, created)


def _validate_slot_times(body: SlotsIn, now: datetime) -> None:
    errors = []
    for i, s in enumerate(body.slots):
        if s.starts_at <= now:
            errors.append(
                {
                    "field": f"slots.{i}.starts_at",
                    "code": "in_past",
                    "message": "Slot must start in the future",
                }
            )
        elif s.starts_at - now > MAX_AHEAD:
            errors.append(
                {"field": f"slots.{i}.starts_at", "code": "too_far", "message": "At most 180 days ahead"}
            )
    if errors:
        raise ProblemError("validation_failed", errors=errors)


def _raise_slot_conflicts(body: SlotsIn, existing: Sequence[MentorSlot]) -> None:
    conflicts = []
    for i, s in enumerate(body.slots):
        clash = any(
            _overlaps(s.starts_at, s.duration_minutes, e.starts_at, e.duration_minutes) for e in existing
        )
        clash = clash or any(
            _overlaps(s.starts_at, s.duration_minutes, o.starts_at, o.duration_minutes)
            for j, o in enumerate(body.slots)
            if j != i
        )
        if clash:
            conflicts.append(
                {
                    "index": i,
                    "starts_at": s.starts_at.isoformat(),
                    "ends_at": (s.starts_at + timedelta(minutes=s.duration_minutes)).isoformat(),
                }
            )
    if conflicts:
        raise ProblemError(
            "slot_overlap",
            409,
            "Slots overlap",
            "One or more slots overlap your existing availability.",
            conflicts=conflicts,
        )


async def list_mentor_slots(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    *,
    after: datetime | None,
    before: datetime | None,
    include_cancelled: bool = False,
) -> list[dict[str, Any]]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.list_mentor_slots(
            session, request, principal, after=after, before=before, include_cancelled=include_cancelled
        )
    await require_anywhere(request, principal, PERM_SLOTS)
    now = utcnow()
    lo = after or now - timedelta(days=7)
    hi = before or now + timedelta(days=90)
    q = select(MentorSlot).where(
        MentorSlot.mentor_id == principal.user_id, MentorSlot.starts_at >= lo, MentorSlot.starts_at < hi
    )
    if not include_cancelled:
        q = q.where(MentorSlot.status != "cancelled")
    async with as_system(session, principal, "mentoring.list_slots"):
        rows = list((await session.execute(q.order_by(MentorSlot.starts_at).limit(500))).scalars())
    return await mentor_slots_json(session, principal, rows)


async def delete_slot(
    session: AsyncSession, request: Request | None, principal: Principal, slot_id: uuid.UUID
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.delete_slot(session, request, principal, slot_id)
    await require_anywhere(request, principal, PERM_SLOTS)
    now = utcnow()
    cancelled_booking: MentorBooking | None = None
    credited = False
    async with as_system(session, principal, "mentoring.delete_slot"):
        slot = (
            await session.execute(
                select(MentorSlot)
                .where(MentorSlot.id == slot_id, MentorSlot.mentor_id == principal.user_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if slot is None:
            raise ProblemError("not_found")
        if slot.status in ("cancelled", "completed") or slot.starts_at <= now:
            raise _bad_state("Only future slots can be removed.")
        cancelled_booking = (
            await session.execute(
                select(MentorBooking)
                .where(MentorBooking.mentor_slot_id == slot.id, MentorBooking.status.in_(LIVE))
                .with_for_update()
            )
        ).scalar_one_or_none()
        slot.status = "cancelled"
        if cancelled_booking is not None:
            cancelled_booking.status = "cancelled_by_mentor"
            cancelled_booking.cancelled_at = now
    if cancelled_booking is not None:
        credited = await credit_back(session, principal, cancelled_booking, reason="mentor_cancel")
        async with as_system(session, principal, "mentoring.delete_slot_event"):
            await emit_event(
                session,
                "mentoring.booking_cancelled",
                {
                    "booking_id": str(cancelled_booking.id),
                    "by": "mentor",
                    "credited": credited,
                    "user_id": str(cancelled_booking.user_id),
                },
                aggregate_type="mentor_booking",
                aggregate_id=cancelled_booking.id,
                organization_id=cancelled_booking.organization_id,
            )
    async with as_system(session, principal, "mentoring.delete_slot_read"):
        await session.refresh(slot)
    return {
        "slot": (await mentor_slots_json(session, principal, [slot]))[0],
        "cancelled_booking_id": _s(cancelled_booking.id) if cancelled_booking else None,
        "credited": credited,
    }


# --------------------------------------------------------------------------- mentor: sessions

SessionView = Literal["upcoming", "pending_feedback", "past", "all"]


def _session_filter(view: SessionView, now: datetime) -> list[Any]:
    ends = MentorSlot.starts_at + func.make_interval(0, 0, 0, 0, 0, MentorSlot.duration_minutes)
    if view == "upcoming":
        return [MentorBooking.status.in_(LIVE), ends > now]
    if view == "pending_feedback":
        no_fb = (
            ~select(InterviewFeedback.id)
            .where(InterviewFeedback.mentor_booking_id == MentorBooking.id)
            .exists()
        )
        return [MentorBooking.status.in_(LIVE), MentorSlot.starts_at <= now, no_fb]
    if view == "past":
        return [or_(MentorSlot.starts_at <= now, ~MentorBooking.status.in_(LIVE))]
    return []


async def mentor_sessions(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    *,
    view: SessionView,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.mentor_sessions(
            session, request, principal, view=view, cursor=cursor, limit=limit
        )
    await require_anywhere(request, principal, PERM_SLOTS)
    now = utcnow()
    off = _offset(cursor)
    base = (
        select(MentorBooking)
        .join(MentorSlot, MentorSlot.id == MentorBooking.mentor_slot_id)
        .where(MentorSlot.mentor_id == principal.user_id)
    )
    order = (
        (MentorSlot.starts_at.asc(), MentorBooking.id)
        if view in ("upcoming", "pending_feedback")
        else (MentorSlot.starts_at.desc(), MentorBooking.id)
    )
    async with as_system(session, principal, "mentoring.sessions"):
        rows = list(
            (
                await session.execute(
                    base.where(*_session_filter(view, now)).order_by(*order).offset(off).limit(limit + 1)
                )
            ).scalars()
        )
        counts: dict[str, int] = {}
        keys: tuple[SessionView, ...] = ("upcoming", "pending_feedback")
        for key in keys:
            counts[key] = (
                await session.execute(
                    select(func.count())
                    .select_from(MentorBooking)
                    .join(MentorSlot, MentorSlot.id == MentorBooking.mentor_slot_id)
                    .where(MentorSlot.mentor_id == principal.user_id, *_session_filter(key, now))
                )
            ).scalar_one()
    more, rows = len(rows) > limit, rows[:limit]
    return {
        "data": await bookings_json(session, principal, rows, mentor_view=True),
        "page": _page(off, limit, more),
        "counts": counts,
    }


async def _mentor_booking(
    session: AsyncSession, principal: Principal, booking_id: uuid.UUID
) -> tuple[MentorBooking, MentorSlot]:
    """The caller's own booking (slot owner) under a system context, locked; else 404."""
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.mentor_booking(session, principal, booking_id)
    async with as_system(session, principal, "mentoring.mentor_booking"):
        row = (
            await session.execute(
                select(MentorBooking, MentorSlot)
                .join(MentorSlot, MentorSlot.id == MentorBooking.mentor_slot_id)
                .where(MentorBooking.id == booking_id, MentorSlot.mentor_id == principal.user_id)
                .with_for_update()
            )
        ).one_or_none()
    if row is None:
        raise ProblemError("not_found")
    return row[0], row[1]


async def weak_topics(session: AsyncSession, principal: Principal, student_id: uuid.UUID) -> list[str]:
    from app.modules.analytics.public import get_topic_mastery
    from app.modules.placement import public as placement_public

    async with as_system(session, principal, "mentoring.readiness"):
        views = [v for v in await get_topic_mastery(session, student_id) if v.band == "weak"]
        nm = await placement_public.topic_names(session, [v.topic_id for v in views])
    return [nm.get(v.topic_id) or str(v.topic_id) for v in views]


async def session_detail(
    session: AsyncSession, request: Request | None, principal: Principal, booking_id: uuid.UUID
) -> dict[str, Any]:
    await require_anywhere(request, principal, PERM_SLOTS)
    b, _ = await _mentor_booking(session, principal, booking_id)
    row = (await bookings_json(session, principal, [b], mentor_view=True))[0]
    notes: list[dict[str, Any]] = []
    if await scopes_holding(request, principal, PERM_NOTES):
        notes = await read_notes(session, principal, b.user_id)
    row["notes"] = notes
    row["weak_topics"] = await weak_topics(session, principal, b.user_id)
    return row


async def set_meeting_link(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    booking_id: uuid.UUID,
    url: str | None,
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.set_meeting_link(session, request, principal, booking_id, url)
    await require_anywhere(request, principal, PERM_SLOTS)
    b, _slot = await _mentor_booking(session, principal, booking_id)
    if b.status not in LIVE:
        raise _bad_state("The meeting link can only be set on a booked session.")
    async with as_system(session, principal, "mentoring.meeting_link"):
        b.meeting_url = url
    return await session_detail(session, request, principal, booking_id)


async def submit_feedback(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    booking_id: uuid.UUID,
    body: FeedbackIn,
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.submit_feedback(session, request, principal, booking_id, body)
    await require_anywhere(request, principal, PERM_FEEDBACK)
    b, slot = await _mentor_booking(session, principal, booking_id)
    now = utcnow()
    if b.status not in LIVE:
        raise _bad_state("Feedback can only be given for a held session.")
    if slot.starts_at > now:
        raise _bad_state("Feedback opens when the session starts.")
    async with as_system(session, principal, "mentoring.feedback"):
        exists = (
            await session.execute(
                select(InterviewFeedback.id).where(InterviewFeedback.mentor_booking_id == b.id)
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise _bad_state("Feedback was already submitted.")
        fb = InterviewFeedback(
            id=uuid7(),
            mentor_booking_id=b.id,
            user_id=b.user_id,
            organization_id=b.organization_id,
            mentor_id=principal.user_id,
            scores=body.scores.model_dump(),
            comments=(body.comments or "").strip() or None,
            released_at=now,
        )
        session.add(fb)
        b.status = "completed"
        slot.status = "completed"
        await session.flush()
        await session.refresh(fb)
        await audit(
            session,
            principal,
            "mentoring.feedback_submitted",
            "mentor_booking",
            b.id,
            organization_id=b.organization_id,
            subject_user_id=b.user_id,
            after={"scores": fb.scores},
        )
        await emit_event(
            session,
            "mentoring.feedback_released",
            {"booking_id": str(b.id), "user_id": str(b.user_id), "mentor_id": str(principal.user_id)},
            aggregate_type="mentor_booking",
            aggregate_id=b.id,
            organization_id=b.organization_id,
        )
    return feedback_json(fb, slot)


async def mark_no_show(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    booking_id: uuid.UUID,
    party: Literal["student", "mentor"],
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.mark_no_show(session, request, principal, booking_id, party)
    await require_anywhere(request, principal, PERM_FEEDBACK)
    b, slot = await _mentor_booking(session, principal, booking_id)
    now = utcnow()
    if b.status not in LIVE:
        raise _bad_state("Only a booked session can be marked as a no-show.")
    if party == "student" and now < slot.starts_at + STUDENT_NO_SHOW_AFTER:
        raise _bad_state("A student no-show can be marked 10 minutes after the start.")
    if party == "mentor" and now < slot.starts_at:
        raise _bad_state("The session has not started yet.")
    async with as_system(session, principal, "mentoring.no_show"):
        b.status = f"{party}_no_show"
        slot.status = "completed"
    credited = False
    if party == "mentor":
        credited = await credit_back(session, principal, b, reason="mentor_no_show")
    async with as_system(session, principal, "mentoring.no_show_audit"):
        await audit(
            session,
            principal,
            "mentoring.no_show_marked",
            "mentor_booking",
            b.id,
            organization_id=b.organization_id,
            subject_user_id=b.user_id,
            after={"party": party, "credited": credited},
        )
        await emit_event(
            session,
            "mentoring.no_show_marked",
            {"booking_id": str(b.id), "party": party, "credited": credited, "user_id": str(b.user_id)},
            aggregate_type="mentor_booking",
            aggregate_id=b.id,
            organization_id=b.organization_id,
        )
        await session.refresh(b)
    return (await bookings_json(session, principal, [b], mentor_view=True))[0]


# --------------------------------------------------------------------------- notes + student summary


async def read_notes(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Notes on an (already authorised) student, limited to the caller's tenants."""
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.read_notes(session, principal, student_id)
    async with as_system(session, principal, "mentoring.notes_read"):
        rows = list(
            (
                await session.execute(
                    select(MentorNote)
                    .where(
                        MentorNote.student_id == student_id,
                        or_(
                            MentorNote.organization_id.is_(None),
                            MentorNote.organization_id.in_(list(principal.org_ids)),
                            MentorNote.author_id == principal.user_id,
                        ),
                    )
                    .order_by(MentorNote.created_at.desc(), MentorNote.id.desc())
                    .limit(200)
                )
            ).scalars()
        )
        await audit(
            session,
            principal,
            "mentoring.notes_read",
            "user",
            student_id,
            subject_user_id=student_id,
            after={"count": len(rows)},
        )
    nm = await names(session, principal, [n.author_id for n in rows])
    return [note_json(n, nm) for n in rows]


async def list_notes(
    session: AsyncSession, request: Request | None, principal: Principal, student_id: uuid.UUID
) -> list[dict[str, Any]]:
    await require_anywhere(request, principal, PERM_NOTES)
    if not await is_assigned(session, request, principal, student_id, PERM_NOTES):
        raise ProblemError("not_found")
    return await read_notes(session, principal, student_id)


async def add_note(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    student_id: uuid.UUID,
    body: str,
    booking_id: uuid.UUID | None,
) -> dict[str, Any]:
    await require_anywhere(request, principal, PERM_FEEDBACK)
    org: uuid.UUID | None = None
    if booking_id is not None:
        b, _ = await _mentor_booking(session, principal, booking_id)
        if b.user_id != student_id:
            raise ProblemError("not_found")
        org = b.organization_id
    elif not await booked_students(session, principal, student_id):
        batches = await assigned_batches(session, request, principal, PERM_NOTES)
        rows = await batch_students(session, principal, batches, student_id)
        if not rows:
            raise ProblemError("not_found")
        org = batches[rows[0][2]][1]
    note = MentorNote(
        id=uuid7(),
        student_id=student_id,
        author_id=principal.user_id,
        organization_id=org,
        mentor_booking_id=booking_id,
        body=body,
    )
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        note = await service_fs.insert_note(session, principal, note)
        nm = await names(session, principal, [principal.user_id])
        return note_json(note, nm)
    async with as_system(session, principal, "mentoring.note_write"):
        session.add(note)
        await session.flush()
        await session.refresh(note)
        await audit(
            session,
            principal,
            "mentoring.note_created",
            "mentor_note",
            note.id,
            organization_id=org,
            subject_user_id=student_id,
        )
    nm = await names(session, principal, [principal.user_id])
    return note_json(note, nm)


async def student_summaries(
    session: AsyncSession, principal: Principal, student_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, datetime | None]:
    """next upcoming live session start per student (any mentor)."""
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.student_summaries(session, principal, student_ids)
    if not student_ids:
        return {}
    now = utcnow()
    async with as_system(session, principal, "mentoring.next_session"):
        rows = (
            await session.execute(
                select(MentorBooking.user_id, func.min(MentorSlot.starts_at))
                .join(MentorSlot, MentorSlot.id == MentorBooking.mentor_slot_id)
                .where(
                    MentorBooking.user_id.in_(list(student_ids)),
                    MentorBooking.status.in_(LIVE),
                    MentorSlot.starts_at > now,
                )
                .group_by(MentorBooking.user_id)
            )
        ).all()
    return {r[0]: r[1] for r in rows}


async def feedback_history(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID
) -> list[dict[str, Any]]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.feedback_history(session, principal, student_id)
    async with as_system(session, principal, "mentoring.feedback_history"):
        rows = (
            await session.execute(
                select(InterviewFeedback, MentorSlot)
                .join(MentorBooking, MentorBooking.id == InterviewFeedback.mentor_booking_id)
                .join(MentorSlot, MentorSlot.id == MentorBooking.mentor_slot_id)
                .where(InterviewFeedback.user_id == student_id)
                .order_by(MentorSlot.starts_at.desc())
                .limit(100)
            )
        ).all()
    return [feedback_json(f, s) for f, s in rows]


# --------------------------------------------------------------------------- résumés

CHECKLIST = (
    ("headline", "Add a one-line headline"),
    ("summary", "Write a summary of at least 50 characters"),
    ("education", "Add your education"),
    ("skills", "List at least 5 skills"),
    ("projects", "Describe at least one project"),
    ("internships", "Add an internship or work experience"),
    ("achievements", "Add an achievement"),
    ("certifications", "Add a certification"),
)


def checklist(content: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    done = {
        "headline": bool((content.get("headline") or "").strip()),
        "summary": len((content.get("summary") or "").strip()) >= 50,
        "education": bool(content.get("education")),
        "skills": len(content.get("skills") or []) >= 5,
        "projects": any((p.get("description") or "").strip() for p in content.get("projects") or []),
        "internships": bool(content.get("internships")),
        "achievements": bool(content.get("achievements")),
        "certifications": bool(content.get("certifications")),
    }
    items = [{"key": k, "label": label, "done": done[k]} for k, label in CHECKLIST]
    score = round(100 * sum(1 for i in items if i["done"]) / len(items))
    return score, items


def review_json(r: ResumeReview) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "resume_id": str(r.resume_id),
        "status": r.status,
        "note": r.note,
        "requested_at": _iso(r.requested_at),
        "completed_at": _iso(r.completed_at),
        "comments": r.comments if r.status == "completed" else [],
        "summary": r.summary if r.status == "completed" else None,
    }


def resume_json(r: Resume, reviews: Sequence[ResumeReview] = ()) -> dict[str, Any]:
    score, items = checklist(r.content)
    return {
        "id": str(r.id),
        "template_key": r.template_key,
        "version_no": r.version_no,
        "content": r.content,
        "checklist_score": r.checklist_score if r.checklist_score is not None else score,
        "checklist": items,
        "is_current": r.is_current,
        "has_pdf": r.pdf_s3_key is not None,
        "pdf_uploaded_at": _iso(r.pdf_uploaded_at),
        "created_at": _iso(r.created_at),
        "updated_at": _iso(r.updated_at),
        "reviews": [review_json(x) for x in reviews],
    }


async def _reviews_by_resume(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[ResumeReview]]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.reviews_by_resume(ids)
    out: dict[uuid.UUID, list[ResumeReview]] = {i: [] for i in ids}
    if ids:
        for rv in (
            await session.execute(
                select(ResumeReview)
                .where(ResumeReview.resume_id.in_(ids))
                .order_by(ResumeReview.requested_at.desc())
            )
        ).scalars():
            out[rv.resume_id].append(rv)
    return out


async def _suggested_certifications(session: AsyncSession, principal: Principal) -> list[dict[str, Any]]:
    """Tech Drona certificates of the caller (FR-PLC-015 auto-fill)."""
    from app.modules.catalog import public as catalog_api
    from app.modules.learning import public as learning_public

    async with as_system(session, principal, "mentoring.certificates"):
        certs = [
            (c.course_id, c.issued_at, c.public_code)
            for c in await learning_public.certificates_of_user(session, principal.user_id)
        ]
        courses = await catalog_api.get_courses(session, {r[0] for r in certs})
    # inner join on courses, then the old LIMIT 30
    rows = [(courses[cid].title, issued, code) for cid, issued, code in certs if cid in courses][:30]
    return [
        {"title": t, "issuer": "Tech Drona", "issued_on": issued.date().isoformat(), "credential_id": code}
        for t, issued, code in rows
    ]


async def list_resumes(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.list_resumes(session, principal)
    rows = list(
        (
            await session.execute(
                select(Resume)
                .where(Resume.user_id == principal.user_id)
                .order_by(Resume.version_no.desc())
                .limit(50)
            )
        ).scalars()
    )
    reviews = await _reviews_by_resume(session, [r.id for r in rows])
    return {
        "data": [resume_json(r, reviews[r.id]) for r in rows],
        "quota": await quota_summary(session, principal),
        "suggested_certifications": await _suggested_certifications(session, principal),
    }


async def _new_version(
    session: AsyncSession, principal: Principal, body: ResumeIn, rid: uuid.UUID | None = None
) -> Resume:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.new_version(principal, body, rid)
    content = body.content.model_dump(mode="json")
    score, _ = checklist(content)
    last = (
        await session.execute(select(func.max(Resume.version_no)).where(Resume.user_id == principal.user_id))
    ).scalar_one()
    await session.execute(
        update(Resume).where(Resume.user_id == principal.user_id, Resume.is_current).values(is_current=False)
    )
    r = Resume(
        id=rid or uuid7(),
        user_id=principal.user_id,
        template_key=body.template_key,
        version_no=(last or 0) + 1,
        content=content,
        checklist_score=score,
        is_current=True,
    )
    session.add(r)
    await session.flush()
    await session.refresh(r)
    return r


async def create_resume(session: AsyncSession, principal: Principal, body: ResumeIn) -> dict[str, Any]:
    return resume_json(await _new_version(session, principal, body))


async def _own_resume(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, *, lock: bool = False
) -> Resume:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.own_resume(principal, rid)
    q = select(Resume).where(Resume.id == rid, Resume.user_id == principal.user_id)
    r = (await session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if r is None:
        raise ProblemError("not_found")
    return r


async def save_resume(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, body: ResumeIn
) -> tuple[dict[str, Any], bool]:
    """PLC-48 PUT: update an own résumé in place, or create it with the client-chosen id."""
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.save_resume(session, principal, rid, body)
    r = (
        await session.execute(
            select(Resume).where(Resume.id == rid, Resume.user_id == principal.user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if r is None:
        async with as_system(session, principal, "mentoring.resume_id_check"):
            taken = (await session.execute(select(Resume.id).where(Resume.id == rid))).scalar_one_or_none()
        if taken is not None:
            raise ProblemError("not_found")
        return resume_json(await _new_version(session, principal, body, rid)), True
    content = body.content.model_dump(mode="json")
    r.content = content
    r.template_key = body.template_key
    r.checklist_score = checklist(content)[0]
    await session.flush()
    await session.refresh(r)
    reviews = await _reviews_by_resume(session, [r.id])
    return resume_json(r, reviews[r.id]), False


async def pdf_upload(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, filename: str, size_bytes: int
) -> dict[str, Any]:
    from app.modules.media.public import presign_post, safe_filename, storage_settings

    r = await _own_resume(session, principal, rid, lock=True)
    base = safe_filename(filename)
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    key = f"resumes/{principal.user_id}/{r.id}/{uuid7()}-{base}"
    post = presign_post(
        storage_settings().S3_BUCKET_UPLOADS, key, content_type="application/pdf", max_bytes=PDF_MAX_BYTES
    )
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        await service_fs.set_pdf_pending(principal, r.id, key)
    else:
        r.pdf_pending_key = key
        await session.flush()
    return {
        "url": post.url,
        "fields": post.fields,
        "key": key,
        "expires_at": _iso(post.expires_at),
        "max_bytes": PDF_MAX_BYTES,
    }


async def pdf_complete(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, key: str
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.pdf_complete(session, principal, rid, key)
    r = await _own_resume(session, principal, rid, lock=True)
    if not r.pdf_pending_key or key != r.pdf_pending_key:
        raise _field_error("key", "This upload was not started for this résumé.")
    r.pdf_s3_key = key
    r.pdf_pending_key = None
    r.pdf_uploaded_at = utcnow()
    await session.flush()
    await session.refresh(r)
    reviews = await _reviews_by_resume(session, [r.id])
    return resume_json(r, reviews[r.id])


async def pdf_download(session: AsyncSession, principal: Principal, rid: uuid.UUID) -> dict[str, Any]:
    from app.modules.media.public import presign_get, storage_settings

    r = await _own_resume(session, principal, rid)
    if not r.pdf_s3_key:
        raise ProblemError("not_found")
    url, exp = presign_get(
        storage_settings().S3_BUCKET_UPLOADS, r.pdf_s3_key, filename=f"resume-v{r.version_no}.pdf"
    )
    return {"url": url, "expires_at": _iso(exp)}


async def request_review(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, note: str | None
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.request_review(session, principal, rid, note)
    r = await _own_resume(session, principal, rid, lock=True)
    open_ = (
        await session.execute(
            select(ResumeReview.id).where(
                ResumeReview.resume_id == r.id, ResumeReview.status.in_(("requested", "in_review"))
            )
        )
    ).scalar_one_or_none()
    if open_ is not None:
        raise _bad_state("A review is already pending for this résumé.")
    await require_package(session, principal, "resume_reviews")
    review_id = uuid7()
    ent = await consume(session, principal, "resume_reviews", review_id)
    rv = ResumeReview(
        id=review_id,
        resume_id=r.id,
        user_id=principal.user_id,
        entitlement_id=ent.id,
        status="requested",
        note=(note or "").strip() or None,
        comments=[],
    )
    session.add(rv)
    await session.flush()
    await session.refresh(rv)
    await emit_event(
        session,
        "mentoring.resume_review_requested",
        {"review_id": str(rv.id), "resume_id": str(r.id), "user_id": str(principal.user_id)},
        aggregate_type="resume_review",
        aggregate_id=rv.id,
    )
    return review_json(rv)


# --------------------------------------------------------------------------- mentor: résumé reviews


async def _review_scope(
    session: AsyncSession, request: Request | None, principal: Principal
) -> set[uuid.UUID] | None:
    """``None`` = every student (platform reviewer); else the assigned student ids."""
    scopes = await require_anywhere(request, principal, PERM_FEEDBACK)
    if PLATFORM_SCOPE in scopes:
        return None
    batches = await assigned_batches(session, request, principal, PERM_FEEDBACK)
    ids = {r[0] for r in await batch_students(session, principal, batches)}
    return ids | await booked_students(session, principal)


async def _queue_items(
    session: AsyncSession, principal: Principal, rows: Sequence[tuple[ResumeReview, Resume]]
) -> list[dict[str, Any]]:
    nm = await names(session, principal, [rv.user_id for rv, _ in rows])
    out = []
    for rv, res in rows:
        score, _ = checklist(res.content)
        out.append(
            {
                **review_json(rv),
                "comments": rv.comments,
                "summary": rv.summary,
                "student_id": str(rv.user_id),
                "student_name": nm.get(rv.user_id),
                "reviewer_id": _s(rv.reviewer_id),
                "resume": {
                    "id": str(res.id),
                    "template_key": res.template_key,
                    "version_no": res.version_no,
                    "content": res.content,
                    "checklist_score": res.checklist_score if res.checklist_score is not None else score,
                },
            }
        )
    return out


async def review_queue(
    session: AsyncSession, request: Request | None, principal: Principal, status: Literal["open", "completed"]
) -> list[dict[str, Any]]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.review_queue(session, request, principal, status)
    allowed = await _review_scope(session, request, principal)
    q = select(ResumeReview, Resume).join(Resume, Resume.id == ResumeReview.resume_id)
    if status == "open":
        q = q.where(ResumeReview.status.in_(("requested", "in_review"))).order_by(
            ResumeReview.requested_at.asc()
        )
    else:
        q = q.where(
            ResumeReview.status == "completed", ResumeReview.reviewer_id == principal.user_id
        ).order_by(ResumeReview.completed_at.desc())
    q = q.where(ResumeReview.user_id != principal.user_id)
    if allowed is not None:
        if not allowed:
            return []
        q = q.where(ResumeReview.user_id.in_(allowed))
    async with as_system(session, principal, "mentoring.review_queue"):
        rows = [(a, b) for a, b in (await session.execute(q.limit(200))).all()]
    return await _queue_items(session, principal, rows)


async def review_feedback(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    review_id: uuid.UUID,
    body: ReviewFeedbackIn,
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.review_feedback(session, request, principal, review_id, body)
    allowed = await _review_scope(session, request, principal)
    async with as_system(session, principal, "mentoring.review_feedback"):
        row = (
            await session.execute(
                select(ResumeReview, Resume)
                .join(Resume, Resume.id == ResumeReview.resume_id)
                .where(ResumeReview.id == review_id)
                .with_for_update()
            )
        ).one_or_none()
        if (
            row is None
            or (allowed is not None and row[0].user_id not in allowed)
            or row[0].user_id == principal.user_id
        ):
            raise ProblemError("not_found")
        rv: ResumeReview = row[0]
        if rv.status not in ("requested", "in_review"):
            raise _bad_state("This review is already closed.")
        if rv.reviewer_id is not None and rv.reviewer_id != principal.user_id:
            raise _bad_state("Another mentor is reviewing this résumé.")
        rv.comments = [c.model_dump() for c in body.comments]
        rv.summary = body.summary.strip()
        rv.reviewer_id = principal.user_id
        rv.status = "completed"
        rv.completed_at = utcnow()
        await session.flush()
        await session.refresh(rv)
        await audit(
            session,
            principal,
            "mentoring.resume_review_completed",
            "resume_review",
            rv.id,
            subject_user_id=rv.user_id,
            after={"comments": len(rv.comments)},
        )
        await emit_event(
            session,
            "mentoring.resume_review_completed",
            {"review_id": str(rv.id), "user_id": str(rv.user_id), "reviewer_id": str(principal.user_id)},
            aggregate_type="resume_review",
            aggregate_id=rv.id,
        )
    return (await _queue_items(session, principal, [(rv, row[1])]))[0]
