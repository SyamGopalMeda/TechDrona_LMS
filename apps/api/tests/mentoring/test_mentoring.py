"""Mentoring (PLC-36..46) — slots, bookings, credit rules, feedback, no-show, notes."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import text

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.time import utcnow
from tests.identity.factory import add_member
from tests.placement.world import Persona, World

API = "/api/v1"


def _at(hours: float) -> str:
    return (utcnow() + timedelta(hours=hours)).replace(microsecond=0).isoformat()


async def grant_package(
    db: Any, who: Persona, *, sessions: int = 2, reviews: int = 1, days: int = 30
) -> uuid.UUID:
    await system_context(db, "test.factory")
    eid = uuid7()
    await db.execute(
        text(
            "INSERT INTO entitlements (id, user_id, feature_key, source_type, granted_by, status, starts_at, "
            "ends_at, mentor_sessions_remaining, resume_reviews_remaining) VALUES (:id, :u, 'placement_package', "
            "'admin_grant', :u, 'active', now() - interval '1 day', now() + make_interval(days => :d), :s, :r)"
        ),
        {"id": eid, "u": who.id, "d": days, "s": sessions, "r": reviews},
    )
    return eid


async def remaining(db: Any, eid: uuid.UUID) -> int:
    await system_context(db, "test.factory")
    return int(
        (
            await db.execute(
                text("SELECT mentor_sessions_remaining FROM entitlements WHERE id = :i"), {"i": eid}
            )
        ).scalar_one()
    )


async def shift_slot(db: Any, booking_or_slot: str, hours: float, *, by_booking: bool = True) -> None:
    """Move a slot's start relative to now (simulates time passing)."""
    await system_context(db, "test.factory")
    where = "id = (SELECT mentor_slot_id FROM mentor_bookings WHERE id = :i)" if by_booking else "id = :i"
    await db.execute(
        text(f"UPDATE mentor_slots SET starts_at = now() + make_interval(mins => :m) WHERE {where}"),
        {"i": uuid.UUID(booking_or_slot), "m": int(hours * 60)},
    )


async def mentor(
    w: World, name: str = "mentor_a", batch: uuid.UUID | None = None, org: uuid.UUID | None = None
) -> Persona:
    if name in w.personas:
        return w.personas[name]
    """Single company (D2): mentor duties are performed by Admin (``super_admin`` @ platform);
    the Placement mentor role is gone. ``batch``/``org`` only set the staff membership."""
    b = batch or w.batch_a
    o = org or w.org_a
    m = await w.persona(
        name, grants=(("super_admin", "platform", None),), org_ids=(o,), is_platform=True, tier="staff"
    )
    await add_member(w.db, o, m.id, "staff", b)
    return m


async def publish(client: Any, m: Persona, *starts: float, minutes: int = 60) -> list[dict[str, Any]]:
    r = await client.post(
        f"{API}/mentor/slots",
        json={"slots": [{"starts_at": _at(h), "duration_minutes": minutes} for h in starts]},
        headers=m.headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def book(client: Any, who: Persona, slot_id: str, key: str | None = None) -> Any:
    return await client.post(
        f"{API}/mentoring/bookings",
        json={"slot_id": slot_id},
        headers={**who.headers, "Idempotency-Key": key or f"book-{uuid.uuid4().hex}"},
    )


# --------------------------------------------------------------------------- slots


async def test_publish_slots_validation_and_overlap(client, world: World) -> None:
    m = await mentor(world)
    slots = await publish(client, m, 24, 26, minutes=45)
    # Admin (platform) publishes platform slots: no organization
    assert [s["organization_id"] for s in slots] == [None, None]
    assert slots[0]["status"] == "open" and slots[0]["duration_minutes"] == 45

    clash = await client.post(
        f"{API}/mentor/slots",
        json={"slots": [{"starts_at": _at(24.5), "duration_minutes": 30}]},
        headers=m.headers,
    )
    assert clash.status_code == 409 and clash.json()["code"] == "slot_overlap", clash.text
    assert clash.json()["conflicts"][0]["index"] == 0

    within = await client.post(
        f"{API}/mentor/slots",
        json={
            "slots": [
                {"starts_at": _at(40), "duration_minutes": 60},
                {"starts_at": _at(40.5), "duration_minutes": 30},
            ]
        },
        headers=m.headers,
    )
    assert within.status_code == 409, within.text

    for bad in (
        {"starts_at": _at(-1), "duration_minutes": 30},
        {"starts_at": _at(50), "duration_minutes": 40},
        {"starts_at": _at(50), "duration_minutes": 30, "session_kind": "chat"},
    ):
        r = await client.post(f"{API}/mentor/slots", json={"slots": [bad]}, headers=m.headers)
        assert r.status_code == 400 and r.json()["code"] == "validation_failed", r.text

    listed = await client.get(f"{API}/mentor/slots", headers=m.headers)
    assert listed.status_code == 200 and len(listed.json()["data"]) == 2

    # the org picker is gone (400); students / trainers lack mentor.slot.manage
    r = await client.post(
        f"{API}/mentor/slots",
        json={"slots": [{"starts_at": _at(70), "duration_minutes": 30}], "organization_id": str(world.org_a)},
        headers=m.headers,
    )
    assert r.status_code == 400, r.text
    for who in ("student", "trainer_a"):
        r = await client.post(
            f"{API}/mentor/slots",
            json={"slots": [{"starts_at": _at(70), "duration_minutes": 30}]},
            headers=world.personas[who].headers,
        )
        assert r.status_code == 403, (who, r.text)


async def test_restricted_principal_denied(client, world: World) -> None:
    s = await world.persona("restricted_student", org_ids=(world.org_a,), scope="restricted")
    for path in ("/mentoring/slots", "/me/mentoring/bookings", "/me/resumes"):
        r = await client.get(f"{API}{path}", headers=s.headers)
        assert r.status_code == 403, (path, r.text)


# --------------------------------------------------------------------------- booking + entitlement


async def test_booking_requires_package_and_idempotency(client, db, world: World) -> None:
    m = await mentor(world)
    (slot,) = await publish(client, m, 30)
    student = world.personas["student"]

    r = await client.get(f"{API}/mentoring/slots", headers=student.headers)
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required", r.text
    r = await book(client, student, slot["id"])
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required", r.text

    eid = await grant_package(db, student, sessions=1)
    r = await client.get(f"{API}/mentoring/slots", headers=student.headers)
    assert r.status_code == 200, r.text
    assert [s["id"] for s in r.json()["data"]] == [slot["id"]]
    assert r.json()["quota"] == {
        "has_package": True,
        "mentor_sessions_remaining": 1,
        "resume_reviews_remaining": 1,
    }

    nokey = await client.post(
        f"{API}/mentoring/bookings", json={"slot_id": slot["id"]}, headers=student.headers
    )
    assert nokey.status_code == 400 and nokey.json()["code"] == "idempotency_key_required"

    first = await book(client, student, slot["id"], key="book-key-0001")
    assert first.status_code == 201, first.text
    replay = await book(client, student, slot["id"], key="book-key-0001")
    assert replay.status_code == 201 and replay.json()["id"] == first.json()["id"]
    assert replay.headers.get("Idempotency-Replayed") == "true"
    b = first.json()
    assert b["status"] == "booked" and b["quota_consumed"] and b["mentor_id"] == str(m.id)
    assert await remaining(db, eid) == 0

    mine = await client.get(f"{API}/me/mentoring/bookings", headers=student.headers)
    assert [x["id"] for x in mine.json()["data"]] == [b["id"]]
    assert mine.json()["quota"]["mentor_sessions_remaining"] == 0

    # quota exhausted on another slot; slot no longer open for others
    (slot2,) = await publish(client, m, 50)
    r = await book(client, student, slot2["id"])
    assert r.status_code == 403 and r.json()["reason"] == "quota_exhausted", r.text
    other = await world.persona("student_a3", org_ids=(world.org_a,))
    await grant_package(db, other)
    r = await book(client, other, slot["id"])
    assert r.status_code == 409 and r.json()["code"] == "slot_unavailable", r.text


async def test_unknown_slot_is_404_and_platform_slots_open_to_all(client, db, world: World) -> None:
    sb = world.personas["student_b"]
    await grant_package(db, sb)
    r = await book(client, sb, str(uuid7()))
    assert r.status_code == 404, r.text

    # Admin (platform) slots have no organization and are open to every learner, including
    # public learners outside the company's batches
    pm = await world.persona(
        "platform_mentor", grants=(("super_admin", "platform", None),), is_platform=True, tier="staff"
    )
    (gslot,) = await publish(client, pm, 30)
    assert gslot["organization_id"] is None
    r = await book(client, sb, gslot["id"])
    assert r.status_code == 201, r.text


async def test_cancel_and_reschedule_credit_rules(client, db, world: World) -> None:
    m = await mentor(world)
    far1, far2, soon1, soon2 = await publish(client, m, 48, 50, 3, 5)
    student = world.personas["student"]
    eid = await grant_package(db, student, sessions=3)

    # >= 12 h: cancel credits back
    b = (await book(client, student, far1["id"])).json()
    assert await remaining(db, eid) == 2
    c = await client.post(f"{API}/mentoring/bookings/{b['id']}/cancel", json={}, headers=student.headers)
    assert c.status_code == 200, c.text
    assert c.json()["status"] == "cancelled_by_student" and c.json()["credit_restored"] is True
    assert await remaining(db, eid) == 3
    again = await client.post(f"{API}/mentoring/bookings/{b['id']}/cancel", json={}, headers=student.headers)
    assert again.status_code == 409

    # >= 12 h reschedule keeps the credit
    b = (await book(client, student, far1["id"])).json()
    assert await remaining(db, eid) == 2
    r = await client.post(
        f"{API}/mentoring/bookings/{b['id']}/reschedule",
        json={"slot_id": far2["id"]},
        headers=student.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rescheduled" and r.json()["slot_id"] == far2["id"]
    assert await remaining(db, eid) == 2

    # < 12 h: reschedule draws a new credit; cancel keeps it consumed
    r = await client.post(
        f"{API}/mentoring/bookings/{b['id']}/reschedule",
        json={"slot_id": far1["id"]},
        headers=student.headers,
    )
    assert r.status_code == 200 and await remaining(db, eid) == 2
    await shift_slot(db, b["id"], 2)
    r = await client.post(
        f"{API}/mentoring/bookings/{b['id']}/reschedule",
        json={"slot_id": soon1["id"]},
        headers=student.headers,
    )
    assert r.status_code == 200, r.text
    assert await remaining(db, eid) == 1
    s2 = (await book(client, student, soon2["id"])).json()
    assert await remaining(db, eid) == 0
    c = await client.post(f"{API}/mentoring/bookings/{s2['id']}/cancel", json={}, headers=student.headers)
    assert c.status_code == 200 and c.json()["credit_restored"] is False
    assert await remaining(db, eid) == 0

    # another student's booking is invisible
    r = await client.post(
        f"{API}/mentoring/bookings/{b['id']}/cancel", json={}, headers=world.personas["student_b"].headers
    )
    assert r.status_code == 404


async def test_mentor_delete_slot_credits_student(client, db, world: World) -> None:
    m = await mentor(world)
    open_slot, booked_slot = await publish(client, m, 20, 22)
    student = world.personas["student"]
    eid = await grant_package(db, student, sessions=1)
    b = (await book(client, student, booked_slot["id"])).json()
    assert await remaining(db, eid) == 0

    r = await client.delete(f"{API}/mentor/slots/{open_slot['id']}", headers=m.headers)
    assert r.status_code == 200 and r.json()["cancelled_booking_id"] is None
    r = await client.delete(f"{API}/mentor/slots/{booked_slot['id']}", headers=m.headers)
    assert r.status_code == 200, r.text
    assert r.json()["cancelled_booking_id"] == b["id"] and r.json()["credited"] is True
    assert await remaining(db, eid) == 1
    mine = (await client.get(f"{API}/me/mentoring/bookings", headers=student.headers)).json()["data"]
    assert mine[0]["status"] == "cancelled_by_mentor" and mine[0]["credit_restored"] is True

    other = await mentor(world, "mentor_a2")
    r = await client.delete(f"{API}/mentor/slots/{booked_slot['id']}", headers=other.headers)
    assert r.status_code == 404


# --------------------------------------------------------------------------- sessions, feedback, no-show


async def test_sessions_feedback_and_no_show(client, db, world: World, audits) -> None:
    m = await mentor(world)
    s1, s2, s3 = await publish(client, m, 30, 32, 34)
    student = world.personas["student"]
    eid = await grant_package(db, student, sessions=3)
    b1 = (await book(client, student, s1["id"])).json()
    b2 = (await book(client, student, s2["id"])).json()
    b3 = (await book(client, student, s3["id"])).json()

    up = await client.get(f"{API}/mentor/sessions", params={"view": "upcoming"}, headers=m.headers)
    assert up.status_code == 200, up.text
    assert [x["id"] for x in up.json()["data"]] == [b1["id"], b2["id"], b3["id"]]
    assert up.json()["counts"] == {"upcoming": 3, "pending_feedback": 0}
    assert up.json()["data"][0]["student_id"] == str(student.id)

    # meeting link: https only
    bad = await client.patch(
        f"{API}/mentor/sessions/{b1['id']}",
        json={"meeting_url": "http://meet.example.com/x"},
        headers=m.headers,
    )
    assert bad.status_code == 400, bad.text
    ok = await client.patch(
        f"{API}/mentor/sessions/{b1['id']}",
        json={"meeting_url": "https://meet.example.com/abc"},
        headers=m.headers,
    )
    assert ok.status_code == 200 and ok.json()["meeting_url"] == "https://meet.example.com/abc", ok.text
    detail = await client.get(f"{API}/mentor/sessions/{b1['id']}", headers=m.headers)
    assert detail.status_code == 200 and detail.json()["notes"] == [] and detail.json()["weak_topics"] == []
    mine = (await client.get(f"{API}/me/mentoring/bookings", headers=student.headers)).json()["data"]
    assert {x["id"]: x["meeting_url"] for x in mine}[b1["id"]] == "https://meet.example.com/abc"

    other = await mentor(world, "mentor_a2")
    assert (await client.get(f"{API}/mentor/sessions/{b1['id']}", headers=other.headers)).status_code == 404
    assert (await client.get(f"{API}/mentor/sessions", headers=student.headers)).status_code == 403

    scores = {"communication": 4, "problem_solving": 3, "technical_depth": 5, "confidence": 4, "overall": 4}
    early = await client.post(
        f"{API}/mentor/bookings/{b1['id']}/feedback", json={"scores": scores}, headers=m.headers
    )
    assert early.status_code == 409, early.text

    await shift_slot(db, b1["id"], -1)
    pend = await client.get(f"{API}/mentor/sessions", params={"view": "pending_feedback"}, headers=m.headers)
    assert [x["id"] for x in pend.json()["data"]] == [b1["id"]]

    missing = await client.post(
        f"{API}/mentor/bookings/{b1['id']}/feedback",
        json={"scores": {k: v for k, v in scores.items() if k != "overall"}},
        headers=m.headers,
    )
    assert missing.status_code == 400
    out_of_range = await client.post(
        f"{API}/mentor/bookings/{b1['id']}/feedback",
        json={"scores": {**scores, "overall": 6}},
        headers=m.headers,
    )
    assert out_of_range.status_code == 400
    assert (
        await client.post(
            f"{API}/mentor/bookings/{b1['id']}/feedback", json={"scores": scores}, headers=other.headers
        )
    ).status_code == 404
    fb = await client.post(
        f"{API}/mentor/bookings/{b1['id']}/feedback",
        json={"scores": scores, "comments": "Structured answers."},
        headers=m.headers,
    )
    assert fb.status_code == 201, fb.text
    assert fb.json()["scores"] == scores
    dup = await client.post(
        f"{API}/mentor/bookings/{b1['id']}/feedback", json={"scores": scores}, headers=m.headers
    )
    assert dup.status_code == 409

    hist = (await client.get(f"{API}/me/mentoring/bookings", headers=student.headers)).json()["data"]
    done = next(x for x in hist if x["id"] == b1["id"])
    assert done["status"] == "completed" and done["feedback"]["comments"] == "Structured answers."

    # student no-show only after 10 minutes; consumes the credit
    await shift_slot(db, b2["id"], -0.05)
    r = await client.post(
        f"{API}/mentor/bookings/{b2['id']}/no-show", json={"party": "student"}, headers=m.headers
    )
    assert r.status_code == 409, r.text
    await shift_slot(db, b2["id"], -0.5)
    r = await client.post(
        f"{API}/mentor/bookings/{b2['id']}/no-show", json={"party": "student"}, headers=m.headers
    )
    assert r.status_code == 200 and r.json()["status"] == "student_no_show", r.text
    assert await remaining(db, eid) == 0

    # mentor no-show credits back automatically
    await shift_slot(db, b3["id"], -0.7)
    r = await client.post(
        f"{API}/mentor/bookings/{b3['id']}/no-show", json={"party": "mentor"}, headers=m.headers
    )
    assert r.status_code == 200 and r.json()["status"] == "mentor_no_show" and r.json()["credit_restored"], (
        r.text
    )
    assert await remaining(db, eid) == 1
    r = await client.post(
        f"{API}/mentor/bookings/{b3['id']}/no-show", json={"party": "student"}, headers=m.headers
    )
    assert r.status_code == 409

    await system_context(db, "test.factory")
    actions = {a for a, subject in audits if subject == student.id}
    assert {"mentoring.feedback_submitted", "mentoring.no_show_marked"} <= actions
    events = set(
        (
            await db.execute(
                text("SELECT event_type FROM outbox_events WHERE payload->>'user_id' = :u"),
                {"u": str(student.id)},
            )
        ).scalars()
    )
    assert {"mentoring.booking_created", "mentoring.feedback_released", "mentoring.no_show_marked"} <= events


# --------------------------------------------------------------------------- notes + mentor console


async def test_private_notes_and_student_console(client, db, world: World, audits) -> None:
    m = await mentor(world)
    student = world.personas["student"]
    sb = world.personas["student_b"]
    unassigned = await world.persona("student_a2", org_ids=(world.org_a,))
    await add_member(db, world.org_a, unassigned.id, "student", world.batch_a2)

    # Admin-as-mentor is assigned to the learners who booked them (D2 mapping)
    (slot,) = await publish(client, m, 30)
    await grant_package(db, student)
    assert (await book(client, student, slot["id"])).status_code == 201
    n = await client.post(
        f"{API}/mentor/students/{student.id}/notes",
        json={"body": "  Needs DSA practice  "},
        headers=m.headers,
    )
    assert n.status_code == 201, n.text
    assert n.json()["body"] == "Needs DSA practice" and n.json()["author_id"] == str(m.id)
    blank = await client.post(
        f"{API}/mentor/students/{student.id}/notes", json={"body": "   "}, headers=m.headers
    )
    assert blank.status_code == 400

    for uid in (sb.id, unassigned.id):
        assert (await client.get(f"{API}/mentor/students/{uid}/notes", headers=m.headers)).status_code == 404
        r = await client.post(f"{API}/mentor/students/{uid}/notes", json={"body": "x"}, headers=m.headers)
        assert r.status_code == 404

    listed = await client.get(f"{API}/mentor/students/{student.id}/notes", headers=m.headers)
    assert [x["body"] for x in listed.json()["data"]] == ["Needs DSA practice"]
    # the batch trainer reads (mentor.notes.read @B) but cannot write notes
    coord = world.personas["trainer_a"]
    r = await client.get(f"{API}/mentor/students/{student.id}/notes", headers=coord.headers)
    assert r.status_code == 200 and len(r.json()["data"]) == 1
    r = await client.post(
        f"{API}/mentor/students/{student.id}/notes", json={"body": "x"}, headers=coord.headers
    )
    assert r.status_code == 403
    # the student never sees notes (no role permission); another tenant's trainer holds
    # mentor.notes.read only on batch_b -> the student is not disclosed
    r = await client.get(f"{API}/mentor/students/{student.id}/notes", headers=student.headers)
    assert r.status_code == 403, r.text
    r = await client.get(
        f"{API}/mentor/students/{student.id}/notes", headers=world.personas["trainer_b"].headers
    )
    assert r.status_code == 404, r.text

    # RLS: the student's own context cannot read the table
    from app.core.db import tenant_context

    await tenant_context(db, student.principal)
    assert (await db.execute(text("SELECT count(*) FROM mentor_notes"))).scalar_one() == 0

    # console detail now carries notes, feedback history and the next session
    d = await client.get(f"{API}/mentor/students/{student.id}", headers=m.headers)
    assert d.status_code == 200, d.text
    assert [x["body"] for x in d.json()["notes"]] == ["Needs DSA practice"]
    assert d.json()["feedback"] == [] and d.json()["next_session_at"] is not None
    lst = await client.get(f"{API}/mentor/students", headers=m.headers)
    assert lst.json()["data"][0]["next_session_at"] is not None
    assert ("mentoring.note_created", student.id) in audits
    assert sum(1 for a, _ in audits if a == "mentoring.notes_read") >= 3


async def test_platform_mentor_sees_booked_students_only(client, db, world: World) -> None:
    pm = await world.persona(
        "platform_mentor", grants=(("super_admin", "platform", None),), is_platform=True, tier="staff"
    )
    sb = world.personas["student_b"]
    assert (await client.get(f"{API}/mentor/students/{sb.id}", headers=pm.headers)).status_code == 404
    (slot,) = await publish(client, pm, 30)
    await grant_package(db, sb)
    assert (await book(client, sb, slot["id"])).status_code == 201
    r = await client.get(f"{API}/mentor/students", headers=pm.headers)
    assert [x["user_id"] for x in r.json()["data"]] == [str(sb.id)]
    d = await client.get(f"{API}/mentor/students/{sb.id}", headers=pm.headers)
    assert d.status_code == 200 and d.json()["batch_id"] is None
    n = await client.post(
        f"{API}/mentor/students/{sb.id}/notes", json={"body": "Booked student"}, headers=pm.headers
    )
    assert n.status_code == 201, n.text
