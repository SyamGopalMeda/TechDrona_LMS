"""Stage 10: mentor console reads (GET /mentor/students, /mentor/students/{user_id})."""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import system_context
from tests.identity.factory import add_member
from tests.placement.world import World, topic


async def test_mentor_sees_only_assigned_students(client, db, world: World) -> None:
    w = world
    mentor = await w.persona(
        "mentor_a", grants=(("trainer", "batch", w.batch_a),), org_ids=(w.org_a,), tier="staff"
    )
    other = await w.persona("student_a2", org_ids=(w.org_a,))
    await add_member(db, w.org_a, other.id, "student", w.batch_a2)
    student = w.personas["student"]

    r = await client.get("/api/v1/mentor/students", headers=mentor.headers)
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert [x["user_id"] for x in rows] == [str(student.id)]
    assert rows[0]["batch_id"] == str(w.batch_a) and rows[0]["full_name"]

    # readiness from analytics topic_mastery
    tid = await topic(db, "quant/percentages", "Percentages")
    await system_context(db, "test.factory")
    await db.execute(
        text(
            "INSERT INTO topic_mastery (user_id, topic_id, theta, band, weighted_accuracy, n_eff, attempts, model_version) "
            "VALUES (:u, :t, -2.0, 'weak', 0.2, 8, 10, 'tm-1.0')"
        ),
        {"u": student.id, "t": tid},
    )
    d = await client.get(f"/api/v1/mentor/students/{student.id}", headers=mentor.headers)
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["weak_topics"] == ["Percentages"] and body["feedback"] == [] and body["notes"] == []
    assert body["topics"][0]["band"] == "weak"

    # unassigned student (other batch) and other org's student -> 404 (SoD-11)
    for uid in (other.id, w.personas["student_b"].id):
        nf = await client.get(f"/api/v1/mentor/students/{uid}", headers=mentor.headers)
        assert nf.status_code == 404, nf.text


async def test_mentor_students_denied_without_permission(client, world: World) -> None:
    for who in ("student", "author"):
        r = await client.get("/api/v1/mentor/students", headers=world.personas[who].headers)
        assert r.status_code == 403, (who, r.text)


async def test_admin_can_open_the_mentor_console(client, world: World) -> None:
    """D2: mentor duties belong to Admin (platform scope). Which students the list shows for a
    platform mentor is WS4's mapping (mentoring module); here only access is checked."""
    r = await client.get("/api/v1/mentor/students", headers=world.personas["admin"].headers)
    assert r.status_code == 200, r.text
