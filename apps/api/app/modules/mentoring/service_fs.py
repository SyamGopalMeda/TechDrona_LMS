"""Mentoring service, Firestore path (``TD_STORE_MENTORING=firestore``).

``service.py`` dispatches here (public functions and the data helpers they share). Package gates,
quota consumption and credit-back (entitlements), names (identity), batches (orgs), companies and
topics (placement), audit and outbox stay on Postgres and are the same calls. The JSON shapes come
from ``service.py``'s serializers.

Cross-store order: the Postgres quota is consumed before the Firestore booking transaction; when
that transaction refuses (slot taken meanwhile) the request fails and the Postgres transaction —
including the consumption — rolls back with it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE
from app.core.company import COMPANY_ORG_ID
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.mentoring import service as pg
from app.modules.mentoring.models import (
    InterviewFeedback,
    MentorBooking,
    MentorNote,
    MentorSlot,
    Resume,
    ResumeReview,
)
from app.modules.mentoring.repo_firestore import BookingView, MentoringRepo
from app.modules.mentoring.repo_firestore import repo as _repo
from app.modules.mentoring.schemas import FeedbackIn, ResumeIn, ReviewFeedbackIn, SlotsIn

LIVE = pg.LIVE


def repo() -> MentoringRepo:
    return _repo("mentoring.service")


async def _credit(session: AsyncSession, principal: Principal, b: MentorBooking, *, reason: str) -> bool:
    """``service.credit_back`` (Postgres entitlement) + persist ``quota_consumed = False``."""
    credited = await pg.credit_back(session, principal, b, reason=reason)
    if credited:
        await repo().set_booking_fields(b.id, {"quota_consumed": False})
    return credited


# =========================================================================== shared reads


async def booked_students(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID | None = None
) -> set[uuid.UUID]:
    ids = {v.booking.user_id for v in await repo().bookings_of_mentor(principal.user_id)}
    return {u for u in ids if user_id is None or u == user_id}


async def bookings_json(
    session: AsyncSession,
    principal: Principal,
    bookings: Sequence[MentorBooking],
    *,
    mentor_view: bool = False,
) -> list[dict[str, Any]]:
    if not bookings:
        return []
    rp = repo()
    slots = await rp.get_slots({b.mentor_slot_id for b in bookings})
    fbs = await rp.feedback_for_bookings([b.id for b in bookings])
    return await pg._render_bookings(session, principal, bookings, slots, fbs, mentor_view=mentor_view)


async def mentor_slots_json(
    session: AsyncSession, principal: Principal, slots: Sequence[MentorSlot]
) -> list[dict[str, Any]]:
    if not slots:
        return []
    statuses = (*LIVE, "completed", "student_no_show", "mentor_no_show")
    live = {b.mentor_slot_id: b for b in await repo().bookings_for_slots([s.id for s in slots], statuses)}
    return await pg._render_mentor_slots(session, principal, slots, live)


# =========================================================================== student: slots + bookings


async def list_open_slots(
    session: AsyncSession,
    principal: Principal,
    *,
    session_kind: str | None,
    after: datetime | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    await pg.require_package(session, principal, "mentor_sessions")
    now = utcnow()
    start = max(after or now, now)
    off = pg._offset(cursor)
    rows, more = await repo().open_slots(
        start=start, exclude_mentor=principal.user_id, session_kind=session_kind, offset=off, limit=limit
    )
    nm = await pg.names(session, principal, [s.mentor_id for s in rows])
    return {
        "data": [pg.slot_json(s, nm) for s in rows],
        "page": pg._page(off, limit, more),
        "quota": await pg.quota_summary(session, principal),
    }


def _open_check(principal: Principal, *, exists: bool = True) -> Any:
    def check(slot: MentorSlot) -> None:
        if slot.status != "open" or slot.starts_at <= utcnow() or slot.mentor_id == principal.user_id:
            raise pg._unavailable()

    return check


async def _visible_open_slot(principal: Principal, slot_id: uuid.UUID) -> MentorSlot:
    slot = (await repo().get_slots([slot_id])).get(slot_id)
    if slot is None:
        raise ProblemError("not_found")
    _open_check(principal)(slot)
    return slot


async def _check_student_overlap(
    principal: Principal, slot: MentorSlot, ignore: uuid.UUID | None = None
) -> None:
    ends = pg._ends(slot)
    for v in await repo().live_bookings_of_user(principal.user_id):
        if v.starts_at is None:
            continue
        if not (v.starts_at < ends and v.starts_at > slot.starts_at - timedelta(minutes=60)):
            continue
        if (
            v.booking.mentor_slot_id != ignore
            and v.starts_at + timedelta(minutes=v.duration) > slot.starts_at
        ):
            raise ProblemError(
                "booking_overlap", 409, "Overlapping booking", "You already have a session at this time."
            )


async def book(
    session: AsyncSession, principal: Principal, slot_id: uuid.UUID, idem_key: str
) -> dict[str, Any]:
    await pg.require_package(session, principal, "mentor_sessions")
    slot = await _visible_open_slot(principal, slot_id)
    await _check_student_overlap(principal, slot)
    bid = uuid7()
    ent = await pg.consume(session, principal, "mentor_sessions", bid)
    booking = MentorBooking(
        id=bid,
        mentor_slot_id=slot.id,
        user_id=principal.user_id,
        organization_id=slot.organization_id,
        entitlement_id=ent.id,
        meeting_url=None,
        status="booked",
        quota_consumed=True,
        cancelled_at=None,
        idempotency_key=idem_key,
        created_at=utcnow(),
    )
    booking = await repo().book(principal.user_id, booking, _open_check(principal))
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
    return (await bookings_json(session, principal, [booking]))[0]


def _live_check(b: MentorBooking, slot: MentorSlot) -> None:
    if b.status not in LIVE:
        raise pg._bad_state("This booking can no longer be changed.")
    if slot.starts_at <= utcnow():
        raise pg._bad_state("The session has already started.")


async def _own_live_booking(principal: Principal, booking_id: uuid.UUID) -> tuple[MentorBooking, MentorSlot]:
    v = await repo().get_booking(booking_id)
    if v is None or v.booking.user_id != principal.user_id:
        raise ProblemError("not_found")
    slot = (await repo().get_slots([v.booking.mentor_slot_id]))[v.booking.mentor_slot_id]
    _live_check(v.booking, slot)
    return v.booking, slot


async def reschedule(
    session: AsyncSession, principal: Principal, booking_id: uuid.UUID, new_slot_id: uuid.UUID
) -> dict[str, Any]:
    b, old = await _own_live_booking(principal, booking_id)
    if new_slot_id == old.id:
        raise pg._unavailable("Pick a different slot.")
    new = await _visible_open_slot(principal, new_slot_id)
    await _check_student_overlap(principal, new, ignore=old.id)
    keep = old.starts_at - utcnow() >= pg.FREE_CHANGE
    ent_id = None
    if not keep or not b.quota_consumed:
        await pg.require_package(session, principal, "mentor_sessions")
        ent_id = (await pg.consume(session, principal, "mentor_sessions", b.id)).id
    check_new = _open_check(principal)

    def apply(bk: MentorBooking, old_s: MentorSlot, new_s: MentorSlot) -> None:
        _live_check(bk, old_s)
        check_new(new_s)
        if ent_id is not None:
            bk.entitlement_id, bk.quota_consumed = ent_id, True
        bk.mentor_slot_id = new_s.id
        bk.status = "rescheduled"
        bk.meeting_url = None

    b = await repo().reschedule(principal.user_id, b.id, new.id, apply)
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
    return (await bookings_json(session, principal, [b]))[0]


async def cancel(session: AsyncSession, principal: Principal, booking_id: uuid.UUID) -> dict[str, Any]:
    b, slot = await _own_live_booking(principal, booking_id)
    now = utcnow()

    def apply(bk: MentorBooking, s: MentorSlot) -> str:
        _live_check(bk, s)
        bk.status, bk.cancelled_at = "cancelled_by_student", now
        return "open"

    b, slot = await repo().finish_booking(principal.user_id, b.id, apply)
    credited = False
    if slot.starts_at - now >= pg.FREE_CHANGE:
        credited = await _credit(session, principal, b, reason="student_cancel_12h")
        if credited:
            b.quota_consumed = False
    await emit_event(
        session,
        "mentoring.booking_cancelled",
        {"booking_id": str(b.id), "by": "student", "credited": credited, "user_id": str(principal.user_id)},
        aggregate_type="mentor_booking",
        aggregate_id=b.id,
        organization_id=b.organization_id,
    )
    return (await bookings_json(session, principal, [b]))[0]


async def my_bookings(
    session: AsyncSession, principal: Principal, *, cursor: str | None, limit: int
) -> dict[str, Any]:
    off = pg._offset(cursor)
    rows, more = await repo().bookings_of_user(principal.user_id, off, limit)
    return {
        "data": await bookings_json(session, principal, rows),
        "page": pg._page(off, limit, more),
        "quota": await pg.quota_summary(session, principal),
    }


# =========================================================================== mentor: slots


async def create_slots(
    session: AsyncSession, request: Request | None, principal: Principal, body: SlotsIn
) -> list[dict[str, Any]]:
    scopes = await pg.require_anywhere(request, principal, pg.PERM_SLOTS)
    org: uuid.UUID | None = None if PLATFORM_SCOPE in scopes else COMPANY_ORG_ID
    pg._validate_slot_times(body, utcnow())
    company_ids = {s.company_id for s in body.slots if s.company_id}
    if company_ids:
        async with pg.as_system(session, principal, "mentoring.create_slots"):
            from app.modules.placement import public as placement_public

            found = await placement_public.existing_company_ids(session, company_ids)
        if company_ids - found:
            raise pg._field_error("company_id", "Unknown company")
    lo = min(s.starts_at for s in body.slots) - timedelta(minutes=60)
    hi = max(s.starts_at + timedelta(minutes=s.duration_minutes) for s in body.slots)

    def check(existing: list[MentorSlot]) -> None:
        pg._raise_slot_conflicts(body, [e for e in existing if lo <= e.starts_at < hi])

    now = utcnow()
    rows = [
        MentorSlot(
            id=uuid7(),
            mentor_id=principal.user_id,
            organization_id=org,
            starts_at=s.starts_at,
            duration_minutes=s.duration_minutes,
            session_kind=s.session_kind,
            company_id=s.company_id,
            status="open",
            created_at=now,
        )
        for s in body.slots
    ]
    created = await repo().create_slots(principal.user_id, rows, check)
    return await mentor_slots_json(session, principal, created)


async def list_mentor_slots(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    *,
    after: datetime | None,
    before: datetime | None,
    include_cancelled: bool = False,
) -> list[dict[str, Any]]:
    await pg.require_anywhere(request, principal, pg.PERM_SLOTS)
    now = utcnow()
    lo = after or now - timedelta(days=7)
    hi = before or now + timedelta(days=90)
    rows = await repo().mentor_slots(principal.user_id, lo, hi, include_cancelled=include_cancelled)
    return await mentor_slots_json(session, principal, rows)


async def delete_slot(
    session: AsyncSession, request: Request | None, principal: Principal, slot_id: uuid.UUID
) -> dict[str, Any]:
    await pg.require_anywhere(request, principal, pg.PERM_SLOTS)
    now = utcnow()

    def check(slot: MentorSlot) -> None:
        if slot.status in ("cancelled", "completed") or slot.starts_at <= now:
            raise pg._bad_state("Only future slots can be removed.")

    slot, cancelled_booking = await repo().delete_slot(slot_id, principal.user_id, now, check)
    credited = False
    if cancelled_booking is not None:
        credited = await _credit(session, principal, cancelled_booking, reason="mentor_cancel")
        async with pg.as_system(session, principal, "mentoring.delete_slot_event"):
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
    return {
        "slot": (await mentor_slots_json(session, principal, [slot]))[0],
        "cancelled_booking_id": pg._s(cancelled_booking.id) if cancelled_booking else None,
        "credited": credited,
    }


# =========================================================================== mentor: sessions


def _in_view(view: str, v: BookingView, now: datetime, has_fb: bool) -> bool:
    assert v.starts_at is not None
    ends = v.starts_at + timedelta(minutes=v.duration)
    live = v.booking.status in LIVE
    if view == "upcoming":
        return live and ends > now
    if view == "pending_feedback":
        return live and v.starts_at <= now and not has_fb
    if view == "past":
        return v.starts_at <= now or not live
    return True


async def mentor_sessions(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    *,
    view: Any,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    await pg.require_anywhere(request, principal, pg.PERM_SLOTS)
    now = utcnow()
    off = pg._offset(cursor)
    rp = repo()
    views = await rp.bookings_of_mentor(principal.user_id)
    fb = set(await rp.feedback_for_bookings([v.booking.id for v in views]))

    def pick(key: str) -> list[BookingView]:
        return [v for v in views if _in_view(key, v, now, v.booking.id in fb)]

    rows = pick(view)
    asc = view in ("upcoming", "pending_feedback")
    # (starts_at asc|desc, booking id asc) as the SQL ORDER BY
    rows.sort(key=lambda v: str(v.booking.id))
    rows.sort(key=lambda v: v.starts_at, reverse=not asc)  # type: ignore[arg-type, return-value]
    page = [v.booking for v in rows[off : off + limit + 1]]
    more, page = len(page) > limit, page[:limit]
    counts = {k: len(pick(k)) for k in ("upcoming", "pending_feedback")}
    return {
        "data": await bookings_json(session, principal, page, mentor_view=True),
        "page": pg._page(off, limit, more),
        "counts": counts,
    }


async def mentor_booking(
    session: AsyncSession, principal: Principal, booking_id: uuid.UUID
) -> tuple[MentorBooking, MentorSlot]:
    v = await repo().get_booking(booking_id)
    if v is None or v.mentor_id != principal.user_id:
        raise ProblemError("not_found")
    slot = (await repo().get_slots([v.booking.mentor_slot_id]))[v.booking.mentor_slot_id]
    return v.booking, slot


async def set_meeting_link(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    booking_id: uuid.UUID,
    url: str | None,
) -> dict[str, Any]:
    await pg.require_anywhere(request, principal, pg.PERM_SLOTS)

    def apply(b: MentorBooking, s: MentorSlot) -> None:
        if b.status not in LIVE:
            raise pg._bad_state("The meeting link can only be set on a booked session.")
        b.meeting_url = url

    await repo().finish_booking(principal.user_id, booking_id, apply, owner_field="slot_mentor_id")
    return await pg.session_detail(session, request, principal, booking_id)


async def submit_feedback(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    booking_id: uuid.UUID,
    body: FeedbackIn,
) -> dict[str, Any]:
    await pg.require_anywhere(request, principal, pg.PERM_FEEDBACK)
    b, _slot = await mentor_booking(session, principal, booking_id)
    now = utcnow()

    def check(bk: MentorBooking, s: MentorSlot) -> None:
        if bk.status not in LIVE:
            raise pg._bad_state("Feedback can only be given for a held session.")
        if s.starts_at > now:
            raise pg._bad_state("Feedback opens when the session starts.")

    check(b, _slot)
    fb = InterviewFeedback(
        id=uuid7(),
        mentor_booking_id=b.id,
        user_id=b.user_id,
        organization_id=b.organization_id,
        mentor_id=principal.user_id,
        scores=body.scores.model_dump(),
        comments=(body.comments or "").strip() or None,
        released_at=now,
        created_at=now,
    )
    fb, slot = await repo().submit_feedback(principal.user_id, b.id, fb, check)
    async with pg.as_system(session, principal, "mentoring.feedback"):
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
    return pg.feedback_json(fb, slot)


async def mark_no_show(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    booking_id: uuid.UUID,
    party: Literal["student", "mentor"],
) -> dict[str, Any]:
    await pg.require_anywhere(request, principal, pg.PERM_FEEDBACK)
    await mentor_booking(session, principal, booking_id)
    now = utcnow()

    def apply(b: MentorBooking, s: MentorSlot) -> str:
        if b.status not in LIVE:
            raise pg._bad_state("Only a booked session can be marked as a no-show.")
        if party == "student" and now < s.starts_at + pg.STUDENT_NO_SHOW_AFTER:
            raise pg._bad_state("A student no-show can be marked 10 minutes after the start.")
        if party == "mentor" and now < s.starts_at:
            raise pg._bad_state("The session has not started yet.")
        b.status = f"{party}_no_show"
        return "completed"

    b, _slot = await repo().finish_booking(principal.user_id, booking_id, apply, owner_field="slot_mentor_id")
    credited = False
    if party == "mentor":
        credited = await _credit(session, principal, b, reason="mentor_no_show")
        if credited:
            b.quota_consumed = False
    async with pg.as_system(session, principal, "mentoring.no_show_audit"):
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
    return (await bookings_json(session, principal, [b], mentor_view=True))[0]


# =========================================================================== notes + summaries


async def read_notes(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID
) -> list[dict[str, Any]]:
    orgs = {str(o) for o in principal.org_ids}
    rows = [
        n
        for n in await repo().notes_of_student(student_id)
        if n.organization_id is None or str(n.organization_id) in orgs or n.author_id == principal.user_id
    ]
    rows.sort(key=lambda n: (n.created_at, str(n.id)), reverse=True)
    rows = rows[:200]
    async with pg.as_system(session, principal, "mentoring.notes_read"):
        await audit(
            session,
            principal,
            "mentoring.notes_read",
            "user",
            student_id,
            subject_user_id=student_id,
            after={"count": len(rows)},
        )
    nm = await pg.names(session, principal, [n.author_id for n in rows])
    return [pg.note_json(n, nm) for n in rows]


async def insert_note(session: AsyncSession, principal: Principal, note: MentorNote) -> MentorNote:
    note.created_at = utcnow()
    note = await repo().add_note(note)
    async with pg.as_system(session, principal, "mentoring.note_write"):
        await audit(
            session,
            principal,
            "mentoring.note_created",
            "mentor_note",
            note.id,
            organization_id=note.organization_id,
            subject_user_id=note.student_id,
        )
    return note


async def student_summaries(
    session: AsyncSession, principal: Principal, student_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, datetime | None]:
    if not student_ids:
        return {}
    now = utcnow()
    out: dict[uuid.UUID, datetime | None] = {}
    for v in await repo().bookings_of_students(student_ids):
        if v.booking.status in LIVE and v.starts_at is not None and v.starts_at > now:
            cur = out.get(v.booking.user_id)
            out[v.booking.user_id] = v.starts_at if cur is None or v.starts_at < cur else cur
    return out


async def feedback_history(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID
) -> list[dict[str, Any]]:
    rp = repo()
    fbs = await rp.feedback_of_user(student_id)
    views = {f.mentor_booking_id: await rp.get_booking(f.mentor_booking_id) for f in fbs}
    slots = await rp.get_slots({v.booking.mentor_slot_id for v in views.values() if v})
    rows = []
    for f in fbs:
        v = views.get(f.mentor_booking_id)
        s = slots.get(v.booking.mentor_slot_id) if v else None
        if s is not None:
            rows.append((f, s))
    rows.sort(key=lambda fs: fs[1].starts_at, reverse=True)
    return [pg.feedback_json(f, s) for f, s in rows[:100]]


# =========================================================================== résumés


async def reviews_by_resume(ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[ResumeReview]]:
    return await repo().reviews_by_resume(ids) if ids else {}


async def list_resumes(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    rows = await repo().resumes_of(principal.user_id, 50)
    reviews = await reviews_by_resume([r.id for r in rows])
    return {
        "data": [pg.resume_json(r, reviews.get(r.id, [])) for r in rows],
        "quota": await pg.quota_summary(session, principal),
        "suggested_certifications": await pg._suggested_certifications(session, principal),
    }


async def new_version(principal: Principal, body: ResumeIn, rid: uuid.UUID | None = None) -> Resume:
    content = body.content.model_dump(mode="json")
    score, _ = pg.checklist(content)
    r = Resume(
        id=rid or uuid7(),
        user_id=principal.user_id,
        template_key=body.template_key,
        version_no=1,
        content=content,
        checklist_score=score,
        pdf_s3_key=None,
        pdf_pending_key=None,
        pdf_uploaded_at=None,
        is_current=True,
        created_at=utcnow(),
    )
    return await repo().new_version(principal.user_id, r)


async def own_resume(principal: Principal, rid: uuid.UUID) -> Resume:
    r = await repo().get_resume(rid)
    if r is None or r.user_id != principal.user_id:
        raise ProblemError("not_found")
    return r


async def save_resume(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, body: ResumeIn
) -> tuple[dict[str, Any], bool]:
    r = await repo().get_resume(rid)
    if r is None:
        return pg.resume_json(await new_version(principal, body, rid)), True
    if r.user_id != principal.user_id:
        raise ProblemError("not_found")
    content = body.content.model_dump(mode="json")
    r = await repo().update_resume(
        principal.user_id,
        rid,
        {"content": content, "template_key": body.template_key, "checklist_score": pg.checklist(content)[0]},
    )
    reviews = await reviews_by_resume([r.id])
    return pg.resume_json(r, reviews.get(r.id, [])), False


async def set_pdf_pending(principal: Principal, rid: uuid.UUID, key: str) -> None:
    await repo().update_resume(principal.user_id, rid, {"pdf_pending_key": key})


async def pdf_complete(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, key: str
) -> dict[str, Any]:
    await own_resume(principal, rid)
    r = await repo().complete_pdf(principal.user_id, rid, key, utcnow())
    reviews = await reviews_by_resume([r.id])
    return pg.resume_json(r, reviews.get(r.id, []))


async def request_review(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, note: str | None
) -> dict[str, Any]:
    r = await own_resume(principal, rid)
    if await repo().open_review_exists(principal.user_id, r.id):
        raise pg._bad_state("A review is already pending for this résumé.")
    await pg.require_package(session, principal, "resume_reviews")
    review_id = uuid7()
    ent = await pg.consume(session, principal, "resume_reviews", review_id)
    rv = ResumeReview(
        id=review_id,
        resume_id=r.id,
        user_id=principal.user_id,
        reviewer_id=None,
        entitlement_id=ent.id,
        status="requested",
        note=(note or "").strip() or None,
        comments=[],
        summary=None,
        requested_at=utcnow(),
        completed_at=None,
    )
    rv = await repo().request_review(principal.user_id, rv)
    await emit_event(
        session,
        "mentoring.resume_review_requested",
        {"review_id": str(rv.id), "resume_id": str(r.id), "user_id": str(principal.user_id)},
        aggregate_type="resume_review",
        aggregate_id=rv.id,
    )
    return pg.review_json(rv)


async def review_queue(
    session: AsyncSession, request: Request | None, principal: Principal, status: Literal["open", "completed"]
) -> list[dict[str, Any]]:
    allowed = await pg._review_scope(session, request, principal)
    if allowed is not None and not allowed:
        return []
    rp = repo()
    if status == "open":
        rows = await rp.reviews_with_status(("requested", "in_review"))
        rows.sort(key=lambda x: x.requested_at)
    else:
        rows = [x for x in await rp.reviews_with_status(("completed",)) if x.reviewer_id == principal.user_id]
        rows.sort(key=lambda x: (x.completed_at is None, x.completed_at), reverse=True)
    rows = [x for x in rows if x.user_id != principal.user_id and (allowed is None or x.user_id in allowed)][
        :200
    ]
    resumes = {r.id: r for r in [await rp.get_resume(x.resume_id) for x in rows] if r is not None}
    pairs = [(x, resumes[x.resume_id]) for x in rows if x.resume_id in resumes]
    return await pg._queue_items(session, principal, pairs)


async def review_feedback(
    session: AsyncSession,
    request: Request | None,
    principal: Principal,
    review_id: uuid.UUID,
    body: ReviewFeedbackIn,
) -> dict[str, Any]:
    allowed = await pg._review_scope(session, request, principal)

    def apply(rv: ResumeReview, res: Resume) -> None:
        if (allowed is not None and rv.user_id not in allowed) or rv.user_id == principal.user_id:
            raise ProblemError("not_found")
        if rv.status not in ("requested", "in_review"):
            raise pg._bad_state("This review is already closed.")
        if rv.reviewer_id is not None and rv.reviewer_id != principal.user_id:
            raise pg._bad_state("Another mentor is reviewing this résumé.")
        rv.comments = [c.model_dump() for c in body.comments]
        rv.summary = body.summary.strip()
        rv.reviewer_id = principal.user_id
        rv.status = "completed"
        rv.completed_at = utcnow()

    rv, res = await repo().complete_review(review_id, apply)
    async with pg.as_system(session, principal, "mentoring.review_feedback"):
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
    return (await pg._queue_items(session, principal, [(rv, res)]))[0]


async def erase_user(user_id: uuid.UUID) -> dict[str, Any]:
    return await _repo("mentoring.erasure").erase_user(user_id)
