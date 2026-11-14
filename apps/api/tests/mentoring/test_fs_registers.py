"""Register / search parity on Firestore (mentoring): open slots, my bookings, mentor sessions
(views, order, offset pages, counts), the résumé review queue and mentor notes equal the same SQL
run by SQLite over the fixture rows. Emulator only."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from tests.learning.fs_harness import firestore_emulator, fs  # noqa: F401
from tests.learning.test_fs_registers import ids, sqldb
from tests.mentoring.test_fs_repo import _booking, _now, _open_check, _slot


def _offsets(total: int, limit: int) -> list[int]:
    return list(range(0, total + limit, limit))


async def _world(rp: Any) -> dict[str, Any]:
    now = _now()
    m1, m2, student, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    slots = []
    for i in range(12):
        mentor = (m1, m2)[i % 2]
        start = now + timedelta(hours=(i // 2) * 3 - 6)  # some past, some future, equal starts across mentors
        s = _slot(
            mentor, start, session_kind=("mock_interview", "resume_review")[i % 3 == 0], duration_minutes=60
        )
        slots.append(s)
    for m in (m1, m2):
        await rp.create_slots(m, [s for s in slots if s.mentor_id == m], lambda ex: None)
    bookings = []
    for i, s in enumerate(slots[:8]):
        if s.starts_at <= now:  # book past slots directly (booking rules are tested elsewhere)
            pass
        u = (student, other)[i % 2]
        b = _booking(s, u, key=f"k{i}")
        b.created_at = now - timedelta(minutes=i % 3)  # ties on created_at
        check = (lambda _s: None) if s.starts_at <= now else _open_check(u)
        bookings.append(await rp.book(u, b, check))

    # statuses: one cancelled, one completed
    def cancel(bk: Any, sl: Any) -> str:
        bk.status = "cancelled_by_student"
        return "open"

    await rp.finish_booking(bookings[2].user_id, bookings[2].id, cancel)
    return {"now": now, "m1": m1, "m2": m2, "student": student, "slots": slots, "bookings": bookings}


async def test_open_slots_and_my_bookings_match_sql(fs: Any) -> None:  # noqa: F811
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    w = await _world(rp)
    slots = {s.id: s for s in (await rp.get_slots([s.id for s in w["slots"]])).values()}
    bks = [(await rp.get_booking(b.id)).booking for b in w["bookings"]]  # type: ignore[union-attr]
    db = sqldb(
        {
            "s": [{"id": s.id, "mentor_id": s.mentor_id, "status": s.status, "starts_at": s.starts_at,
                   "kind": s.session_kind} for s in slots.values()],
            "b": [{"id": b.id, "user_id": b.user_id, "created_at": b.created_at} for b in bks],
        }
    )  # fmt: skip
    for viewer in (w["student"], w["m1"]):
        for kind in (None, "mock_interview"):
            for limit in (2, 50):
                for off in _offsets(len(slots), limit):
                    sql = "SELECT id FROM s WHERE status = 'open' AND starts_at > ? AND mentor_id != ?"
                    p: list[Any] = [w["now"], viewer]
                    if kind:
                        sql, p = sql + " AND kind = ?", [*p, kind]
                    want = ids(db, sql + " ORDER BY starts_at, id LIMIT ? OFFSET ?", [*p, limit + 1, off])
                    rows, more = await rp.open_slots(
                        start=w["now"], exclude_mentor=viewer, session_kind=kind, offset=off, limit=limit
                    )
                    assert [str(s.id) for s in rows] == want[:limit] and more == (len(want) > limit)
    for limit in (1, 3, 50):
        for off in _offsets(len(bks), limit):
            want = ids(db, "SELECT id FROM b WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                       [w["student"], limit + 1, off])  # fmt: skip
            rows, more = await rp.bookings_of_user(w["student"], off, limit)
            assert [str(b.id) for b in rows] == want[:limit] and more == (len(want) > limit)


async def test_mentor_sessions_views_match_sql(fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.mentoring import service as pg
    from app.modules.mentoring import service_fs
    from app.modules.mentoring.models import InterviewFeedback
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    w = await _world(rp)
    m1 = w["m1"]
    past = [b for b in w["bookings"] if b.status == "booked"]
    # feedback on one held session (it leaves pending_feedback)
    held = None
    for b in past:
        v = await rp.get_booking(b.id)
        if v is not None and v.mentor_id == m1 and v.starts_at is not None and v.starts_at <= w["now"]:
            held = b
            break
    assert held is not None
    fb = InterviewFeedback(id=uuid.uuid4(), mentor_booking_id=held.id, user_id=held.user_id, organization_id=None,
                           mentor_id=m1, scores={"o": 1}, comments=None, released_at=w["now"], created_at=w["now"])  # fmt: skip
    await rp.submit_feedback(m1, held.id, fb, lambda b, s: None)

    async def anywhere(*a: Any, **k: Any) -> list[Any]:
        return []

    async def as_ids(session: Any, principal: Any, bookings: Any, *, mentor_view: bool = False) -> list[str]:
        return [str(b.id) for b in bookings]

    monkeypatch.setattr(pg, "require_anywhere", anywhere)
    monkeypatch.setattr(service_fs, "bookings_json", as_ids)
    views = [v for v in await rp.bookings_of_mentor(m1)]
    with_fb = set(await rp.feedback_for_bookings([v.booking.id for v in views]))
    db = sqldb(
        {"b": [{"id": v.booking.id, "status": v.booking.status, "starts_at": v.starts_at,
                "ends_at": v.starts_at + timedelta(minutes=v.duration), "fb": v.booking.id in with_fb} for v in views]}  # type: ignore[operator]
    )  # fmt: skip
    live = "status IN ('booked','rescheduled')"
    filt = {
        "upcoming": f"{live} AND ends_at > ?",
        "pending_feedback": f"{live} AND starts_at <= ? AND fb = 0",
        "past": f"(starts_at <= ? OR NOT {live})",
        "all": "1=1",
    }
    principal = type("P", (), {"user_id": m1})()
    import app.modules.mentoring.service_fs as sfs

    real_now = w["now"]
    monkeypatch.setattr(sfs, "utcnow", lambda: real_now)
    for view, cond in filt.items():
        order = "starts_at ASC, id" if view in ("upcoming", "pending_feedback") else "starts_at DESC, id"
        p = [] if view == "all" else [real_now]
        for limit in (1, 2, 50):
            for off in _offsets(len(views), limit):
                want = ids(
                    db,
                    f"SELECT id FROM b WHERE {cond} ORDER BY {order} LIMIT ? OFFSET ?",
                    [*p, limit + 1, off],
                )
                cursor = None if off == 0 else _cursor(off)
                out = await sfs.mentor_sessions(None, None, principal, view=view, cursor=cursor, limit=limit)  # type: ignore[arg-type]
                assert out["data"] == want[:limit], (view, limit, off)
                assert out["page"]["has_more"] == (len(want) > limit)
        counts = out["counts"]
    for key in ("upcoming", "pending_feedback"):
        n = db.execute(f"SELECT count(*) FROM b WHERE {filt[key]}", [real_now.isoformat()]).fetchone()[0]
        assert counts[key] == n


def _cursor(off: int) -> str:
    from app.core.pagination import encode_cursor

    return encode_cursor({"o": off})


async def test_review_queue_and_notes_match_sql(fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.mentoring import service as pg
    from app.modules.mentoring import service_fs
    from app.modules.mentoring.models import MentorNote, Resume, ResumeReview
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    now = _now()
    reviewer, me = uuid.uuid4(), uuid.uuid4()
    students = [uuid.uuid4() for _ in range(4)] + [me]
    reviews = []
    for i, u in enumerate(students * 2):
        r = await rp.new_version(u, Resume(id=uuid.uuid4(), user_id=u, template_key="ats_classic", version_no=1,
                                           content={}, checklist_score=0, is_current=True, created_at=now))  # fmt: skip
        status = ("requested", "in_review", "completed")[i % 3]
        rv = ResumeReview(id=uuid.uuid4(), resume_id=r.id, user_id=u, reviewer_id=reviewer if status == "completed" else None,
                          entitlement_id=None, status=status, note=None, comments=[], summary=None,
                          requested_at=now - timedelta(minutes=i), completed_at=now - timedelta(minutes=2 * i) if status == "completed" else None)  # fmt: skip
        await rp.request_review(u, rv)
        reviews.append(rv)
    db = sqldb(
        {"r": [{"id": x.id, "user_id": x.user_id, "status": x.status, "reviewer_id": x.reviewer_id,
                "requested_at": x.requested_at, "completed_at": x.completed_at} for x in reviews]}
    )  # fmt: skip

    async def as_ids(session: Any, principal: Any, rows: Any) -> list[str]:
        return [str(rv.id) for rv, _res in rows]

    monkeypatch.setattr(pg, "_queue_items", as_ids)
    principal = type("P", (), {"user_id": reviewer})()
    for allowed in (None, set(students[:2]) | {me}, set()):

        async def scope(*a: Any, allowed: Any = allowed, **k: Any) -> Any:
            return allowed

        monkeypatch.setattr(pg, "_review_scope", scope)
        for status in ("open", "completed"):
            if allowed is not None and not allowed:
                assert await service_fs.review_queue(None, None, principal, status) == []  # type: ignore[arg-type]
                continue
            if status == "open":
                sql, p = "SELECT id FROM r WHERE status IN ('requested','in_review')", []
                order = " ORDER BY requested_at ASC"
            else:
                sql, p = "SELECT id FROM r WHERE status = 'completed' AND reviewer_id = ?", [reviewer]
                order = " ORDER BY completed_at DESC"
            sql, p = sql + " AND user_id != ?", [*p, reviewer]
            if allowed is not None:
                sql += f" AND user_id IN ({', '.join('?' for _ in allowed)})"
                p += list(allowed)
            want = ids(db, sql + order + " LIMIT 200", p)
            assert await service_fs.review_queue(None, None, principal, status) == want  # type: ignore[arg-type]

    # notes: the student's notes visible to the caller (org NULL, caller's orgs, or own), newest first
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    student = students[0]
    notes = []
    for i in range(9):
        n = MentorNote(id=uuid.uuid4(), student_id=student, author_id=(reviewer, me)[i % 2],
                       organization_id=(None, org_a, org_b)[i % 3], mentor_booking_id=None, body=f"n{i}",
                       created_at=now - timedelta(minutes=i // 2))  # fmt: skip
        notes.append(await rp.add_note(n))
    ndb = sqldb(
        {
            "n": [
                {"id": n.id, "org": n.organization_id, "author": n.author_id, "created_at": n.created_at}
                for n in notes
            ]
        }
    )

    async def quiet(*a: Any, **k: Any) -> None:
        return None

    async def no_names(*a: Any, **k: Any) -> dict[Any, Any]:
        return {}

    monkeypatch.setattr(service_fs, "audit", quiet)
    monkeypatch.setattr(pg, "names", no_names)
    caller = type("P", (), {"user_id": me, "org_ids": frozenset({org_a})})()
    got = await service_fs.read_notes(None, caller, student)  # type: ignore[arg-type]
    want = ids(
        ndb,
        "SELECT id FROM n WHERE org IS NULL OR org IN (?) OR author = ? ORDER BY created_at DESC, id DESC LIMIT 200",
        [org_a, me],
    )
    assert [x["id"] for x in got] == want
