"""mentoring on Firestore: data path + repository invariants (emulator only, no Postgres).

Run: ``TD_TEST_DB_NAME=learning_test .venv/Scripts/python -m pytest --noconftest -p no:cacheprovider
tests/mentoring/test_fs_repo.py``. The HTTP flows on Firestore: ``test_mentoring_firestore_matrix.py``."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.learning.fs_harness import backfill_rows, firestore_emulator, fs  # noqa: F401
from tests.learning.test_fs_data_path import synthetic


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _slot(mentor: uuid.UUID, start: datetime, **over: Any) -> Any:
    from app.modules.mentoring.models import MentorSlot

    base = dict(id=uuid.uuid4(), mentor_id=mentor, organization_id=None, starts_at=start, duration_minutes=60,
                session_kind="mock_interview", company_id=None, status="open", created_at=_now())  # fmt: skip
    base.update(over)
    return MentorSlot(**base)


def _booking(slot: Any, user: uuid.UUID, key: str = "k1") -> Any:
    from app.modules.mentoring.models import MentorBooking

    return MentorBooking(
        id=uuid.uuid4(), mentor_slot_id=slot.id, user_id=user, organization_id=None, entitlement_id=uuid.uuid4(),
        meeting_url=None, status="booked", quota_consumed=True, cancelled_at=None, idempotency_key=key, created_at=_now(),
    )  # fmt: skip


def _open_check(user: uuid.UUID) -> Any:
    from app.modules.mentoring import service as pg

    def check(s: Any) -> None:
        if s.status != "open" or s.starts_at <= datetime.now(UTC) or s.mentor_id == user:
            raise pg._unavailable()

    return check


async def _mk_slots(rp: Any, mentor: uuid.UUID, *starts: datetime) -> list[Any]:
    return await rp.create_slots(mentor, [_slot(mentor, s) for s in starts], lambda existing: None)


async def test_backfill_verify(fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.mentoring import models as m
    from app.modules.mentoring import store_specs as ss
    from app.modules.mentoring.repo_firestore import repo

    t = datetime(2026, 12, 1, 10, tzinfo=UTC)
    s1 = synthetic(m.MentorSlot, status="booked", starts_at=t, duration_minutes=60)
    s2 = synthetic(m.MentorSlot, status="cancelled", mentor_id=s1["mentor_id"], starts_at=t)
    b1 = synthetic(m.MentorBooking, mentor_slot_id=s1["id"], status="booked", idempotency_key="idem-1")
    b2 = synthetic(
        m.MentorBooking, mentor_slot_id=s2["id"], status="cancelled_by_mentor", idempotency_key="idem-2"
    )
    fb = synthetic(m.InterviewFeedback, mentor_booking_id=b1["id"], scores={"overall": 4})
    note = synthetic(m.MentorNote)
    res = synthetic(m.Resume, version_no=2, content={"headline": "x", "skills": ["a"]})
    rv_open = synthetic(m.ResumeReview, resume_id=res["id"], status="requested", comments=[])
    rv_done = synthetic(m.ResumeReview, resume_id=res["id"], status="completed", comments=[{"c": "ok"}])
    rows = {
        "mentor_slots": [s1, s2],
        "mentor_bookings": [b1, b2],
        "interview_feedback": [fb],
        "mentor_notes": [note],
        "resumes": [res],
        "resume_reviews": [rv_open, rv_done],
    }
    slot_by = {s1["id"]: s1, s2["id"]: s2}
    joined = [
        {**b, "s_mentor_id": slot_by[b["mentor_slot_id"]]["mentor_id"], "s_starts_at": t, "s_duration": 60}
        for b in (b1, b2)
    ]
    reports = await backfill_rows(monkeypatch, "mentoring", rows, fs, sources={ss._BOOKING_SRC: joined})
    by = {r.collection: r for r in reports}
    assert set(by) == set(ss.COLLECTIONS)
    assert all(r.ok for r in reports), [r.as_dict() for r in reports if not r.ok]
    assert by[ss.SLOT_TIMES].fs_docs == 1  # cancelled slots hold no time key
    assert by[ss.SLOT_LIVE].fs_docs == 1 and by[ss.REVIEW_OPEN].fs_docs == 1
    rp = repo()
    v = await rp.get_booking(b1["id"])
    assert v is not None and v.mentor_id == s1["mentor_id"] and v.starts_at == t and v.duration == 60
    assert v.booking.idempotency_key == "idem-1"
    assert (await rp.feedback_for_bookings([b1["id"]]))[b1["id"]].scores == {"overall": 4}
    assert [x.id for x in await rp.resumes_of(res["user_id"])] == [res["id"]]


async def test_no_double_booking_under_concurrency(fs: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    mentor = uuid.uuid4()
    (slot,) = await _mk_slots(rp, mentor, _now() + timedelta(days=2))
    students = [uuid.uuid4() for _ in range(6)]

    async def one(u: uuid.UUID) -> str:
        try:
            await rp.book(u, _booking(slot, u), _open_check(u))
            return "ok"
        except ProblemError as e:
            return e.code

    out = await asyncio.gather(*(one(u) for u in students))
    assert out.count("ok") == 1 and out.count("slot_unavailable") == 5, out
    got = (await rp.get_slots([slot.id]))[slot.id]
    assert got.status == "booked"
    assert len(await rp.bookings_for_slots([slot.id], ("booked",))) == 1


async def test_idempotency_key_unique_per_user(fs: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    mentor, u = uuid.uuid4(), uuid.uuid4()
    s1, s2 = await _mk_slots(rp, mentor, _now() + timedelta(days=2), _now() + timedelta(days=3))
    await rp.book(u, _booking(s1, u, "same"), _open_check(u))
    with pytest.raises(ProblemError) as e:
        await rp.book(u, _booking(s2, u, "same"), _open_check(u))
    assert e.value.code == "conflict"
    assert (await rp.get_slots([s2.id]))[s2.id].status == "open"  # nothing committed


async def test_reschedule_cancel_and_rebook(fs: Any) -> None:  # noqa: F811
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    mentor, u, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    t1, t2 = _now() + timedelta(days=2), _now() + timedelta(days=3)
    s1, s2 = await _mk_slots(rp, mentor, t1, t2)
    b = await rp.book(u, _booking(s1, u), _open_check(u))

    def move(bk: Any, old: Any, new: Any) -> None:
        _open_check(u)(new)
        bk.mentor_slot_id, bk.status, bk.meeting_url = new.id, "rescheduled", None

    b = await rp.reschedule(u, b.id, s2.id, move)
    slots = await rp.get_slots([s1.id, s2.id])
    assert (slots[s1.id].status, slots[s2.id].status) == ("open", "booked")
    v = await rp.get_booking(b.id)
    assert v is not None and v.starts_at == t2 and v.booking.status == "rescheduled"
    # the old slot is free again: another student can book it
    await rp.book(other, _booking(s1, other), _open_check(other))

    def cancel(bk: Any, s: Any) -> str:
        bk.status, bk.cancelled_at = "cancelled_by_student", _now()
        return "open"

    b, slot = await rp.finish_booking(u, b.id, cancel)
    assert b.status == "cancelled_by_student" and slot.status == "open"
    third = uuid.uuid4()
    await rp.book(third, _booking(s2, third), _open_check(third))  # live key was released


async def test_other_users_booking_is_not_found(fs: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    mentor, u = uuid.uuid4(), uuid.uuid4()
    (s1,) = await _mk_slots(rp, mentor, _now() + timedelta(days=2))
    b = await rp.book(u, _booking(s1, u), _open_check(u))
    with pytest.raises(ProblemError) as e:
        await rp.finish_booking(uuid.uuid4(), b.id, lambda bk, s: None)
    assert e.value.code == "not_found"


async def test_delete_slot_cancels_live_booking(fs: Any) -> None:  # noqa: F811
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    mentor, u = uuid.uuid4(), uuid.uuid4()
    t = _now() + timedelta(days=2)
    (s1,) = await _mk_slots(rp, mentor, t)
    b = await rp.book(u, _booking(s1, u), _open_check(u))
    slot, cancelled = await rp.delete_slot(s1.id, mentor, _now(), lambda s: None)
    assert slot.status == "cancelled" and cancelled is not None and cancelled.id == b.id
    assert cancelled.status == "cancelled_by_mentor"
    # the (mentor, starts_at) time key is free again
    (again,) = await _mk_slots(rp, mentor, t)
    assert again.status == "open"


async def test_slot_time_unique_and_overlap_check(fs: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.mentoring import service as pg
    from app.modules.mentoring.repo_firestore import repo
    from app.modules.mentoring.schemas import SlotsIn

    rp = repo()
    mentor = uuid.uuid4()
    t = _now() + timedelta(days=2)
    await _mk_slots(rp, mentor, t)
    with pytest.raises(ProblemError) as e:  # same start: the unique time key
        await _mk_slots(rp, mentor, t)
    assert e.value.code == "conflict"
    body = SlotsIn.model_validate(
        {
            "slots": [
                {
                    "starts_at": (t + timedelta(minutes=30)).isoformat(),
                    "duration_minutes": 60,
                    "session_kind": "mock_interview",
                }
            ]
        }
    )
    with pytest.raises(ProblemError) as e:
        await rp.create_slots(
            mentor, [_slot(mentor, t + timedelta(minutes=30))], lambda ex: pg._raise_slot_conflicts(body, ex)
        )
    assert e.value.code == "slot_overlap"
    assert (
        len(
            await rp.mentor_slots(
                mentor, t - timedelta(days=1), t + timedelta(days=1), include_cancelled=False
            )
        )
        == 1
    )


async def test_feedback_once_and_no_show_releases_slot(fs: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.mentoring.models import InterviewFeedback
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    mentor, u, u2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    s1, s2 = await _mk_slots(rp, mentor, _now() + timedelta(days=2), _now() + timedelta(days=3))
    b = await rp.book(u, _booking(s1, u), _open_check(u))

    def fb() -> InterviewFeedback:
        return InterviewFeedback(id=uuid.uuid4(), mentor_booking_id=b.id, user_id=u, organization_id=None,
                                 mentor_id=mentor, scores={"overall": 5}, comments="good", released_at=_now(),
                                 created_at=_now())  # fmt: skip

    f, slot = await rp.submit_feedback(mentor, b.id, fb(), lambda bk, s: None)
    assert slot.status == "completed" and f.scores == {"overall": 5}
    with pytest.raises(ProblemError) as e:
        await rp.submit_feedback(mentor, b.id, fb(), lambda bk, s: None)
    assert e.value.detail == "Feedback was already submitted."
    assert [x.id for x in await rp.feedback_of_user(u)] == [f.id]

    b2 = await rp.book(u2, _booking(s2, u2), _open_check(u2))

    def no_show(bk: Any, s: Any) -> str:
        bk.status = "mentor_no_show"
        return "completed"

    b2, s = await rp.finish_booking(mentor, b2.id, no_show, owner_field="slot_mentor_id")
    assert b2.status == "mentor_no_show" and s.status == "completed"
    assert {v.booking.user_id for v in await rp.bookings_of_mentor(mentor)} == {u, u2}


async def test_resume_versions_concurrent_and_current_flag(fs: Any) -> None:  # noqa: F811
    from app.modules.mentoring.models import Resume
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    u = uuid.uuid4()

    def r() -> Resume:
        return Resume(id=uuid.uuid4(), user_id=u, template_key="ats_classic", version_no=1, content={"headline": "h"},
                      checklist_score=10, pdf_s3_key=None, pdf_pending_key=None, pdf_uploaded_at=None,
                      is_current=True, created_at=_now())  # fmt: skip

    made = await asyncio.gather(*(rp.new_version(u, r()) for _ in range(4)))
    assert sorted(x.version_no for x in made) == [1, 2, 3, 4]
    rows = await rp.resumes_of(u)
    assert [x.version_no for x in rows] == [4, 3, 2, 1]
    assert sum(1 for x in rows if x.is_current) == 1 and rows[0].is_current


async def test_resume_review_one_open_then_complete(fs: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.mentoring.models import Resume, ResumeReview
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    u, reviewer = uuid.uuid4(), uuid.uuid4()
    res = await rp.new_version(u, Resume(id=uuid.uuid4(), user_id=u, template_key="ats_classic", version_no=1,
                                         content={}, checklist_score=0, is_current=True, created_at=_now()))  # fmt: skip

    def rv() -> ResumeReview:
        return ResumeReview(id=uuid.uuid4(), resume_id=res.id, user_id=u, reviewer_id=None, entitlement_id=None,
                            status="requested", note=None, comments=[], summary=None, requested_at=_now(),
                            completed_at=None)  # fmt: skip

    first = await rp.request_review(u, rv())
    assert await rp.open_review_exists(u, res.id)
    with pytest.raises(ProblemError):
        await rp.request_review(u, rv())

    def done(x: Any, r: Any) -> None:
        x.status, x.reviewer_id, x.summary, x.completed_at = "completed", reviewer, "ok", _now()
        x.comments = [{"section": "skills", "text": "add more"}]

    got, _ = await rp.complete_review(first.id, done)
    assert got.status == "completed" and got.comments == [{"section": "skills", "text": "add more"}]
    assert not await rp.open_review_exists(u, res.id)
    await rp.request_review(u, rv())  # a new review may be requested now
    assert len((await rp.reviews_by_resume([res.id]))[res.id]) == 2


async def test_erase_user(fs: Any) -> None:  # noqa: F811
    from app.modules.mentoring.models import MentorNote, Resume
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    mentor, u = uuid.uuid4(), uuid.uuid4()
    (s1,) = await _mk_slots(rp, mentor, _now() + timedelta(days=2))
    b = await rp.book(u, _booking(s1, u), _open_check(u))
    await rp.set_booking_fields(b.id, {"meeting_url": "https://meet.example/x"})
    await rp.new_version(u, Resume(id=uuid.uuid4(), user_id=u, template_key="ats_classic", version_no=1, content={},
                                   checklist_score=0, is_current=True, created_at=_now()))  # fmt: skip
    await rp.add_note(MentorNote(id=uuid.uuid4(), student_id=u, author_id=mentor, organization_id=None,
                                 mentor_booking_id=None, body="private", created_at=_now()))  # fmt: skip
    out = await rp.erase_user(u)
    assert out == {"resume_reviews_deleted": 0, "resumes_deleted": 1, "feedback_scrubbed": 0,
                   "mentor_notes_scrubbed": 1, "bookings_scrubbed": 1}  # fmt: skip
    assert [n.body for n in await rp.notes_of_student(u)] == ["[erased]"]
    assert await rp.resumes_of(u) == []
    again = await rp.erase_user(u)
    assert again["mentor_notes_scrubbed"] == 0 and again["bookings_scrubbed"] == 0


def test_session_views_match_sql_filters() -> None:
    from app.modules.mentoring.repo_firestore import BookingView
    from app.modules.mentoring.service_fs import _in_view

    now = _now()

    def v(status: str, start: datetime) -> BookingView:
        from app.core.firestore.store import Doc

        return BookingView(Doc("x", {"id": str(uuid.uuid4()), "mentor_slot_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4()),
                                     "status": status, "slot_mentor_id": str(uuid.uuid4()), "slot_starts_at": start,
                                     "slot_duration": 60, "quota_consumed": True, "idempotency_key": "k"}))  # fmt: skip

    running = v("booked", now - timedelta(minutes=30))  # started, not ended
    assert _in_view("upcoming", running, now, False)  # ends > now
    assert _in_view("pending_feedback", running, now, False)
    assert not _in_view("pending_feedback", running, now, True)
    assert _in_view("past", running, now, False)
    cancelled = v("cancelled_by_student", now + timedelta(days=1))
    assert not _in_view("upcoming", cancelled, now, False) and _in_view("past", cancelled, now, False)


def test_repository_scoped() -> None:
    from app.core.firestore.repository import assert_repository_scoped
    from app.modules.mentoring.repo_firestore import MentoringRepo

    assert_repository_scoped(MentoringRepo)
