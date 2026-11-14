"""Firestore repository of ``mentoring`` (``TD_STORE_MENTORING=firestore``; model in ``store_specs.py``).

Rows come back as transient ORM instances so ``service.py``'s serializers are shared. The service
performs the same authorization as on Postgres (permission at some scope, slot ownership, SoD-11
assignment) before calling in; the repository runs as named system jobs (Postgres used
``as_system`` for these reads/writes too). Every public method takes the ``user_id`` it acts for
or is ``@platform_only``.

``FOR UPDATE`` sections become transactions: ``book`` / ``reschedule`` / ``cancel`` /
``delete_slot`` / ``submit_feedback`` / ``mark_no_show`` / ``review_feedback`` re-read and
re-check their documents inside the transaction (a check callback raises the same
``ProblemError`` as Postgres) and commit every document of the step together.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from app.core.errors import ProblemError
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.core.time import utcnow
from app.modules.mentoring import store_specs as ss
from app.modules.mentoring.fs_rows import as_dt, as_uuid, doc_of, orm_of
from app.modules.mentoring.models import (
    InterviewFeedback,
    MentorBooking,
    MentorNote,
    MentorSlot,
    Resume,
    ResumeReview,
)

PERM = ss.PERM_SLOTS
LIVE = ("booked", "rescheduled")
_MANAGED = ("created_at", "updated_at", "schema_version")


def conflict() -> ProblemError:
    return ProblemError(
        "conflict", detail="Another request changed this at the same time. Refresh and try again."
    )


def _new(obj: Any, now: datetime, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    d = doc_of(obj)
    if not d.get("created_at"):
        d["created_at"] = now
    d.pop("updated_at", None)
    d.update(extra or {})
    return d


def _diff(cur: Doc, obj: Any, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    new = {k: v for k, v in doc_of(obj).items() if k not in _MANAGED}
    new.update(extra or {})
    return {k: v for k, v in new.items() if cur.data.get(k) != v}


def slot_of(d: Doc) -> MentorSlot:
    return orm_of(MentorSlot, d.data)


def booking_of(d: Doc) -> MentorBooking:
    return orm_of(MentorBooking, d.data)


class BookingView:
    """A booking plus its denormalised slot fields (mentor, start, duration)."""

    __slots__ = ("booking", "duration", "mentor_id", "starts_at")

    def __init__(self, d: Doc) -> None:
        self.booking = booking_of(d)
        self.mentor_id = as_uuid(d.get("slot_mentor_id"))
        self.starts_at = as_dt(d.get("slot_starts_at"))
        self.duration = int(d.get("slot_duration") or 0)


def _chunks(ids: list[str], n: int = 30) -> Iterable[list[str]]:
    for i in range(0, len(ids), n):
        yield ids[i : i + n]


class MentoringRepo(FirestoreRepository):
    async def _all(
        self, coll: str, *, filters: Any = (), order_by: Any = (), user_id: Any = None
    ) -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                coll, user_id=user_id, filters=filters, order_by=order_by, limit=500, cursor=cursor
            )
            out += page.items
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    async def _in(self, coll: str, field: str, values: Iterable[Any], *extra: Any) -> list[Doc]:
        ids = sorted({str(v) for v in values if v is not None})
        out: list[Doc] = []
        for part in _chunks(ids):
            out += await self._all(coll, filters=((field, "in", part), *extra))
        return out

    # ================================================================== slots

    @platform_only(PERM)
    async def get_slots(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, MentorSlot]:
        docs = await self.store.get_many(ss.SLOTS, [str(i) for i in ids])
        return {uuid.UUID(k): slot_of(d) for k, d in docs.items()}

    @platform_only(PERM)
    async def open_slots(
        self, *, start: datetime, exclude_mentor: uuid.UUID, session_kind: str | None, offset: int, limit: int
    ) -> tuple[list[MentorSlot], bool]:
        """status open, starts_at > start, not the caller's; ordered (starts_at, id); offset paging."""
        want = offset + limit + 1
        out: list[MentorSlot] = []
        cursor: str | None = None
        while len(out) < want:
            page = await self.store.query(
                ss.SLOTS,
                filters=(("status", "==", "open"), ("starts_at", ">", start)),
                order_by=(("starts_at", "asc"),),
                limit=200,
                cursor=cursor,
            )
            for d in page.items:
                if d["mentor_id"] == str(exclude_mentor):
                    continue
                if session_kind and d["session_kind"] != session_kind:
                    continue
                out.append(slot_of(d))
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        rows = out[offset : offset + limit + 1]
        return rows[:limit], len(rows) > limit

    @platform_only(PERM)
    async def mentor_slots(
        self, mentor_id: uuid.UUID, lo: datetime, hi: datetime, *, include_cancelled: bool, limit: int = 500
    ) -> list[MentorSlot]:
        docs = await self._all(
            ss.SLOTS,
            filters=(("mentor_id", "==", str(mentor_id)), ("starts_at", ">=", lo), ("starts_at", "<", hi)),
            order_by=(("starts_at", "asc"),),
        )
        rows = [slot_of(d) for d in docs if include_cancelled or d["status"] != "cancelled"]
        return rows[:limit]

    @platform_only(PERM)
    async def create_slots(
        self,
        mentor_id: uuid.UUID,
        rows: list[MentorSlot],
        check: Callable[[list[MentorSlot]], None],
    ) -> list[MentorSlot]:
        """Insert ``rows`` after ``check(existing non-cancelled slots of the mentor)`` passes,
        atomically (the mentor's slot set is the transaction's read set)."""
        now = utcnow()

        async def fn(tx: ScopedTransaction) -> list[MentorSlot]:
            existing = await tx.query(ss.SLOTS, filters=(("mentor_id", "==", str(mentor_id)),))
            check([slot_of(d) for d in existing if d["status"] != "cancelled"])
            keys = [ss.slot_time_key(s.mentor_id, s.starts_at) for s in rows]
            if len(set(keys)) != len(keys):  # two new slots at the same start (ux_ms_mentor_time)
                raise conflict()
            for key in keys:  # every read before the first write
                if await tx.raw_get(ss.SLOT_TIMES, key) is not None:
                    raise conflict()
            out = []
            for s, key in zip(rows, keys, strict=True):
                tx.raw_create(ss.SLOT_TIMES, key, {"slot_id": str(s.id), "created_at": now})
                out.append(slot_of(await tx.create(ss.SLOTS, _new(s, now), doc_id=str(s.id))))
            return out

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def delete_slot(
        self, slot_id: uuid.UUID, mentor_id: uuid.UUID, now: datetime, check: Callable[[MentorSlot], None]
    ) -> tuple[MentorSlot, MentorBooking | None]:
        """Cancel the mentor's slot and its live booking (``cancelled_by_mentor``) atomically."""

        async def fn(tx: ScopedTransaction) -> tuple[MentorSlot, MentorBooking | None]:
            sd = await tx.get(ss.SLOTS, str(slot_id))
            if sd is None or sd["mentor_id"] != str(mentor_id):
                raise ProblemError("not_found")
            slot = slot_of(sd)
            check(slot)
            live = await tx.raw_get(ss.SLOT_LIVE, str(slot_id))
            bd = await tx.get(ss.BOOKINGS, live["booking_id"]) if live else None
            booking = booking_of(bd) if bd is not None and bd["status"] in LIVE else None
            sd2 = await tx.update_read(ss.SLOTS, sd, {"status": "cancelled"})
            tx.raw_delete(ss.SLOT_TIMES, ss.slot_time_key(slot.mentor_id, slot.starts_at))
            if booking is not None and bd is not None:
                booking.status, booking.cancelled_at = "cancelled_by_mentor", now
                bd2 = await tx.update_read(ss.BOOKINGS, bd, _diff(bd, booking))
                booking = booking_of(bd2)
                tx.raw_delete(ss.SLOT_LIVE, str(slot_id))
            return slot_of(sd2), booking

        return await self.store.run_transaction(fn)

    # ================================================================== bookings

    @platform_only(PERM)
    async def get_booking(self, booking_id: uuid.UUID) -> BookingView | None:
        d = await self.store.get(ss.BOOKINGS, str(booking_id))
        return BookingView(d) if d else None

    async def bookings_of_user(
        self, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[MentorBooking], bool]:
        page = await self.store.query(
            ss.BOOKINGS,
            user_id=user_id,
            order_by=(("created_at", "desc"),),
            limit=min(offset + limit + 1, 100),
        )
        docs = list(page.items)
        cursor = page.next_cursor
        while cursor and len(docs) < offset + limit + 1:
            page = await self.store.query(
                ss.BOOKINGS, user_id=user_id, order_by=(("created_at", "desc"),), limit=100, cursor=cursor
            )
            docs += page.items
            cursor = page.next_cursor
        rows = [booking_of(d) for d in docs][offset : offset + limit + 1]
        return rows[:limit], len(rows) > limit

    async def live_bookings_of_user(self, user_id: uuid.UUID) -> list[BookingView]:
        docs = await self._all(ss.BOOKINGS, user_id=user_id, filters=(("status", "in", list(LIVE)),))
        return [BookingView(d) for d in docs]

    @platform_only(PERM)
    async def bookings_of_mentor(self, mentor_id: uuid.UUID) -> list[BookingView]:
        return [
            BookingView(d)
            for d in await self._all(ss.BOOKINGS, filters=(("slot_mentor_id", "==", str(mentor_id)),))
        ]

    @platform_only(PERM)
    async def bookings_of_students(self, student_ids: Iterable[uuid.UUID]) -> list[BookingView]:
        return [BookingView(d) for d in await self._in(ss.BOOKINGS, "user_id", student_ids)]

    @platform_only(PERM)
    async def bookings_for_slots(
        self, slot_ids: Iterable[uuid.UUID], statuses: tuple[str, ...]
    ) -> list[MentorBooking]:
        return [
            booking_of(d)
            for d in await self._in(ss.BOOKINGS, "mentor_slot_id", slot_ids)
            if d["status"] in statuses
        ]

    async def book(
        self, user_id: uuid.UUID, booking: MentorBooking, check: Callable[[MentorSlot], None]
    ) -> MentorBooking:
        """No double booking: the slot must pass ``check`` (open, future, not own) and have no
        live booking; booking + keys + ``slot.status = booked`` commit together."""
        now = utcnow()

        async def fn(tx: ScopedTransaction) -> MentorBooking:
            sd = await tx.get(ss.SLOTS, str(booking.mentor_slot_id))
            if sd is None:
                raise ProblemError("not_found")
            check(slot_of(sd))
            if await tx.raw_get(ss.SLOT_LIVE, sd.id) is not None:
                check(orm_of(MentorSlot, {**sd.data, "status": "booked"}))
            ik = ss.idem_key(user_id, booking.idempotency_key)
            if await tx.raw_get(ss.BOOKING_IDEM, ik) is not None:
                raise conflict()
            d = await tx.create(
                ss.BOOKINGS, _new(booking, now, ss.slot_fields(sd.data)), doc_id=str(booking.id)
            )
            tx.raw_create(ss.BOOKING_IDEM, ik, {"booking_id": str(booking.id), "created_at": now})
            tx.raw_create(ss.SLOT_LIVE, sd.id, {"booking_id": str(booking.id), "created_at": now})
            await tx.update_read(ss.SLOTS, sd, {"status": "booked"})
            return booking_of(d)

        return await self.store.run_transaction(fn)

    async def reschedule(
        self,
        user_id: uuid.UUID,
        booking_id: uuid.UUID,
        new_slot_id: uuid.UUID,
        apply: Callable[[MentorBooking, MentorSlot, MentorSlot], None],
    ) -> MentorBooking:
        """Move a live booking to an open slot: old slot reopened, new slot booked, atomically.
        ``apply(booking, old, new)`` re-checks both slots and mutates the booking."""

        async def fn(tx: ScopedTransaction) -> MentorBooking:
            bd = await tx.get(ss.BOOKINGS, str(booking_id))
            if bd is None or bd["user_id"] != str(user_id):
                raise ProblemError("not_found")
            b = booking_of(bd)
            old = await tx.get(ss.SLOTS, str(b.mentor_slot_id))
            new = await tx.get(ss.SLOTS, str(new_slot_id))
            if old is None or new is None:
                raise ProblemError("not_found")
            taken = await tx.raw_get(ss.SLOT_LIVE, new.id)
            new_slot = slot_of(new)
            if taken is not None:
                new_slot.status = "booked"
            apply(b, slot_of(old), new_slot)
            bd2 = await tx.update_read(ss.BOOKINGS, bd, _diff(bd, b, ss.slot_fields(new.data)))
            await tx.update_read(ss.SLOTS, old, {"status": "open"})
            await tx.update_read(ss.SLOTS, new, {"status": "booked"})
            tx.raw_delete(ss.SLOT_LIVE, old.id)
            tx.raw_create(ss.SLOT_LIVE, new.id, {"booking_id": str(b.id), "created_at": utcnow()})
            return booking_of(bd2)

        return await self.store.run_transaction(fn)

    async def finish_booking(
        self,
        user_id: uuid.UUID,
        booking_id: uuid.UUID,
        apply: Callable[[MentorBooking, MentorSlot], str | None],
        *,
        owner_field: str = "user_id",
    ) -> tuple[MentorBooking, MentorSlot]:
        """Generic locked update of a booking and its slot: ``apply`` checks and mutates the
        booking and returns the slot's new status (or ``None``). ``owner_field``: ``user_id``
        (student routes) or ``slot_mentor_id`` (mentor routes) must equal ``user_id``.
        The slot's live key is released when the booking leaves booked/rescheduled/completed."""

        async def fn(tx: ScopedTransaction) -> tuple[MentorBooking, MentorSlot]:
            bd = await tx.get(ss.BOOKINGS, str(booking_id))
            if bd is None or bd.get(owner_field) != str(user_id):
                raise ProblemError("not_found")
            sd = await tx.get(ss.SLOTS, bd["mentor_slot_id"])
            if sd is None:
                raise ProblemError("not_found")
            b, slot = booking_of(bd), slot_of(sd)
            slot_status = apply(b, slot)
            bd2 = await tx.update_read(ss.BOOKINGS, bd, _diff(bd, b))
            if slot_status is not None and slot_status != sd["status"]:
                sd = await tx.update_read(ss.SLOTS, sd, {"status": slot_status})
            if bd["status"] in ss.LIVE_SLOT_BOOKING and b.status not in ss.LIVE_SLOT_BOOKING:
                # this booking held the slot's live key (ux_mb_slot_live); release it
                tx.raw_delete(ss.SLOT_LIVE, sd.id)
            return booking_of(bd2), slot_of(sd)

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def set_booking_fields(self, booking_id: uuid.UUID, changes: dict[str, Any]) -> MentorBooking:
        return booking_of(await self.store.update(ss.BOOKINGS, str(booking_id), changes))

    # ================================================================== feedback

    @platform_only(PERM)
    async def feedback_for_bookings(
        self, booking_ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, InterviewFeedback]:
        keys = await self.store.get_many(ss.FEEDBACK_BY_BOOKING, [str(b) for b in booking_ids])
        docs = await self.store.get_many(ss.FEEDBACK, [k["feedback_id"] for k in keys.values()])
        out = [orm_of(InterviewFeedback, d.data) for d in docs.values()]
        return {f.mentor_booking_id: f for f in out}

    @platform_only(PERM)
    async def feedback_of_user(self, student_id: uuid.UUID) -> list[InterviewFeedback]:
        return [orm_of(InterviewFeedback, d.data) for d in await self._all(ss.FEEDBACK, user_id=student_id)]

    @platform_only(PERM)
    async def submit_feedback(
        self,
        mentor_id: uuid.UUID,
        booking_id: uuid.UUID,
        fb: InterviewFeedback,
        check: Callable[[MentorBooking, MentorSlot], None],
    ) -> tuple[InterviewFeedback, MentorSlot]:
        now = utcnow()

        async def fn(tx: ScopedTransaction) -> tuple[InterviewFeedback, MentorSlot]:
            bd = await tx.get(ss.BOOKINGS, str(booking_id))
            if bd is None or bd.get("slot_mentor_id") != str(mentor_id):
                raise ProblemError("not_found")
            sd = await tx.get(ss.SLOTS, bd["mentor_slot_id"])
            if sd is None:
                raise ProblemError("not_found")
            check(booking_of(bd), slot_of(sd))
            if await tx.raw_get(ss.FEEDBACK_BY_BOOKING, bd.id) is not None:
                raise ProblemError("invalid_state_transition", detail="Feedback was already submitted.")
            d = await tx.create(ss.FEEDBACK, _new(fb, now), doc_id=str(fb.id))
            tx.raw_create(ss.FEEDBACK_BY_BOOKING, bd.id, {"feedback_id": str(fb.id), "created_at": now})
            await tx.update_read(ss.BOOKINGS, bd, {"status": "completed"})
            sd2 = await tx.update_read(ss.SLOTS, sd, {"status": "completed"})
            return orm_of(InterviewFeedback, d.data), slot_of(sd2)

        return await self.store.run_transaction(fn)

    # ================================================================== notes

    @platform_only(PERM)
    async def notes_of_student(self, student_id: uuid.UUID) -> list[MentorNote]:
        docs = await self._all(ss.NOTES, filters=(("student_id", "==", str(student_id)),))
        return [orm_of(MentorNote, d.data) for d in docs]

    @platform_only(PERM)
    async def add_note(self, note: MentorNote) -> MentorNote:
        d = await self.store.create(ss.NOTES, _new(note, utcnow()), doc_id=str(note.id))
        return orm_of(MentorNote, d.data)

    # ================================================================== résumés

    async def resumes_of(self, user_id: uuid.UUID, limit: int = 50) -> list[Resume]:
        page = await self.store.query(
            ss.RESUMES, user_id=user_id, order_by=(("version_no", "desc"),), limit=limit
        )
        return [orm_of(Resume, d.data) for d in page.items]

    @platform_only(PERM)
    async def get_resume(self, resume_id: uuid.UUID) -> Resume | None:
        d = await self.store.get(ss.RESUMES, str(resume_id))
        return orm_of(Resume, d.data) if d else None

    async def new_version(self, user_id: uuid.UUID, r: Resume) -> Resume:
        """Insert ``r`` as version ``max+1`` and clear the previous ``is_current``, atomically
        (``resume_versions/{user:n}`` makes a concurrent duplicate number fail and retry)."""
        now = utcnow()
        for _ in range(5):
            mine = await self._all(ss.RESUMES, user_id=user_id)
            last = max((int(d["version_no"]) for d in mine), default=0)
            current = [d.id for d in mine if d.get("is_current")]

            async def fn(tx: ScopedTransaction, last: int = last, current: list[str] = current) -> Resume:
                if await tx.raw_get(ss.RESUME_VERSIONS, ss.version_key(user_id, last + 1)) is not None:
                    raise UniqueViolationError(ss.RESUME_VERSIONS, "")
                if str(r.id) not in current and await tx.raw_get(ss.RESUMES, str(r.id)) is not None:
                    raise UniqueViolationError(ss.RESUMES, str(r.id))
                cur_docs = await tx.get_many(ss.RESUMES, current)
                r.version_no = last + 1
                for d in cur_docs.values():
                    if d.get("is_current"):
                        await tx.update_read(ss.RESUMES, d, {"is_current": False})
                tx.raw_create(
                    ss.RESUME_VERSIONS,
                    ss.version_key(user_id, r.version_no),
                    {"resume_id": str(r.id), "created_at": now},
                )
                d = await tx.create(ss.RESUMES, _new(r, now), doc_id=str(r.id))
                return orm_of(Resume, d.data)

            try:
                return await self.store.run_transaction(fn)
            except UniqueViolationError as e:
                if e.collection in (ss.RESUMES, "lms_" + ss.RESUMES):
                    raise
                continue
        raise conflict()

    async def complete_pdf(self, user_id: uuid.UUID, resume_id: uuid.UUID, key: str, now: datetime) -> Resume:
        """Check the pending upload key and promote it, in one transaction (the Postgres
        ``FOR UPDATE`` on the résumé): a concurrent complete or a new upload cannot interleave."""

        async def fn(tx: ScopedTransaction) -> Resume:
            cur = await tx.get(ss.RESUMES, str(resume_id))
            if cur is None or cur.get("user_id") != str(user_id):
                raise ProblemError("not_found")
            if not cur.get("pdf_pending_key") or key != cur.get("pdf_pending_key"):
                msg = "This upload was not started for this résumé."
                raise ProblemError(
                    "validation_failed", errors=[{"field": "key", "code": "invalid", "message": msg}]
                )
            d = await tx.update_read(
                ss.RESUMES, cur, {"pdf_s3_key": key, "pdf_pending_key": None, "pdf_uploaded_at": now}
            )
            return orm_of(Resume, d.data)

        return await self.store.run_transaction(fn)

    async def update_resume(
        self, user_id: uuid.UUID, resume_id: uuid.UUID, changes: dict[str, Any]
    ) -> Resume:
        return orm_of(Resume, (await self.store.update(ss.RESUMES, str(resume_id), changes)).data)

    @platform_only(PERM)
    async def reviews_by_resume(self, resume_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[ResumeReview]]:
        ids = list(resume_ids)
        out: dict[uuid.UUID, list[ResumeReview]] = {i: [] for i in ids}
        rows = [orm_of(ResumeReview, d.data) for d in await self._in(ss.REVIEWS, "resume_id", ids)]
        for rv in sorted(rows, key=lambda x: x.requested_at, reverse=True):
            out.setdefault(rv.resume_id, []).append(rv)
        return out

    async def open_review_exists(self, user_id: uuid.UUID, resume_id: uuid.UUID) -> bool:
        return (await self.store.get(ss.REVIEW_OPEN, str(resume_id))) is not None

    async def request_review(self, user_id: uuid.UUID, rv: ResumeReview) -> ResumeReview:
        now = utcnow()

        async def fn(tx: ScopedTransaction) -> ResumeReview:
            if await tx.raw_get(ss.REVIEW_OPEN, str(rv.resume_id)) is not None:
                raise ProblemError(
                    "invalid_state_transition", detail="A review is already pending for this résumé."
                )
            tx.raw_create(ss.REVIEW_OPEN, str(rv.resume_id), {"review_id": str(rv.id), "created_at": now})
            d = await tx.create(
                ss.REVIEWS, _new(rv, now, {"requested_at": rv.requested_at or now}), doc_id=str(rv.id)
            )
            return orm_of(ResumeReview, d.data)

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def reviews_with_status(self, statuses: tuple[str, ...]) -> list[ResumeReview]:
        docs = await self._all(ss.REVIEWS, filters=(("status", "in", list(statuses)),))
        return [orm_of(ResumeReview, d.data) for d in docs]

    @platform_only(PERM)
    async def complete_review(
        self, review_id: uuid.UUID, apply: Callable[[ResumeReview, Resume], None]
    ) -> tuple[ResumeReview, Resume]:
        async def fn(tx: ScopedTransaction) -> tuple[ResumeReview, Resume]:
            rd = await tx.get(ss.REVIEWS, str(review_id))
            if rd is None:
                raise ProblemError("not_found")
            res = await tx.get(ss.RESUMES, rd["resume_id"])
            if res is None:
                raise ProblemError("not_found")
            rv = orm_of(ResumeReview, rd.data)
            apply(rv, orm_of(Resume, res.data))
            open_key = await tx.raw_get(ss.REVIEW_OPEN, rd["resume_id"])
            rd2 = await tx.update_read(ss.REVIEWS, rd, _diff(rd, rv))
            if (
                open_key is not None
                and open_key.get("review_id") == rd.id
                and rv.status not in ss.OPEN_REVIEW
            ):
                tx.raw_delete(ss.REVIEW_OPEN, rd["resume_id"])
            return orm_of(ResumeReview, rd2.data), orm_of(Resume, res.data)

        return await self.store.run_transaction(fn)

    # ================================================================== erasure (DB-01)

    async def erase_user(self, user_id: uuid.UUID) -> dict[str, int]:
        st = self.store
        reviews = await self._all(ss.REVIEWS, user_id=user_id)
        resumes = await self._all(ss.RESUMES, user_id=user_id)
        for d in reviews:
            await st.delete(ss.REVIEWS, d.id)
            k = await st.get(ss.REVIEW_OPEN, d["resume_id"])
            if k is not None and k.get("review_id") == d.id:
                await st.delete(ss.REVIEW_OPEN, d["resume_id"])
        for d in resumes:
            await st.delete(ss.RESUMES, d.id)
            k = await st.get(ss.RESUME_VERSIONS, ss.version_key(user_id, d["version_no"]))
            if k is not None:
                await st.delete(ss.RESUME_VERSIONS, k.id)
        fb = 0
        for d in await self._all(ss.FEEDBACK, user_id=user_id):
            if d.get("comments") is not None:
                await st.update(ss.FEEDBACK, d.id, {"comments": None})
                fb += 1
        notes = 0
        for d in await self._all(ss.NOTES, filters=(("student_id", "==", str(user_id)),)):
            if d.get("body") != "[erased]":
                await st.update(ss.NOTES, d.id, {"body": "[erased]"})
                notes += 1
        bk = 0
        for d in await self._all(ss.BOOKINGS, user_id=user_id):
            if d.get("meeting_url") is not None:
                await st.update(ss.BOOKINGS, d.id, {"meeting_url": None})
                bk += 1
        return {
            "resume_reviews_deleted": len(reviews),
            "resumes_deleted": len(resumes),
            "feedback_scrubbed": fb,
            "mentor_notes_scrubbed": notes,
            "bookings_scrubbed": bk,
        }


def repo(job: str = "mentoring.service") -> MentoringRepo:
    return MentoringRepo(ScopedStore.system(job))
