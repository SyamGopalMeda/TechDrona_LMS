"""Stage 10: GET /assignments (staff list used by the trainer grading console)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from app.core.db import system_context
from app.core.ids import uuid7
from app.modules.learning.models import Assignment, AssignmentSubmission
from tests.placement.world import World, build_world


@pytest.fixture
def rbac_auth(auth: Any) -> Iterator[Any]:
    from app.core import auth as core_auth
    from app.modules.rbac.service import RbacPermissionChecker

    prev = core_auth._permission_checker
    core_auth.register_permission_checker(RbacPermissionChecker())
    yield auth
    core_auth.register_permission_checker(prev)


@pytest.fixture
async def world(db: Any, rbac_auth: Any, client: Any) -> World:
    return await build_world(db, rbac_auth)


async def _assignment(db: Any, w: World, org: uuid.UUID, batch: uuid.UUID, title: str) -> uuid.UUID:
    await system_context(db, "test.factory")
    aid = uuid7()
    db.add(
        Assignment(
            id=aid,
            organization_id=org,
            batch_id=batch,
            title=title,
            instructions_md="Do it.",
            submission_type="text",
            max_score=Decimal(10),
            allowed_file_types=["pdf"],
            created_by=w.personas["trainer_a"].id,
        )
    )
    await db.flush()
    return aid


async def test_staff_assignment_list_scoped_to_grading_permission(client, db, world: World) -> None:
    w = world
    a1 = await _assignment(db, w, w.org_a, w.batch_a, "Arrays worksheet")
    a2 = await _assignment(db, w, w.org_a, w.batch_a, "Strings worksheet")
    other_batch = await _assignment(db, w, w.org_a, w.batch_a2, "Other batch")
    other_org = await _assignment(db, w, w.org_b, w.batch_b, "Other org")
    await system_context(db, "test.factory")
    db.add(
        AssignmentSubmission(
            id=uuid7(),
            assignment_id=a1,
            user_id=w.personas["student"].id,
            organization_id=w.org_a,
            body_text="answer",
            status="submitted",
        )
    )
    await db.flush()

    r = await client.get(
        "/api/v1/assignments", params={"scope": "mine"}, headers=w.personas["trainer_a"].headers
    )
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    ids = [x["assignment_id"] for x in rows]
    assert ids == [str(a2), str(a1)]  # newest first; batch_a2 and org B excluded
    assert str(other_batch) not in ids and str(other_org) not in ids
    first = {x["assignment_id"]: x for x in rows}[str(a1)]
    assert first["pending_count"] == 1 and first["batch_name"] == "CSE 2027"
    assert first["max_points"] == 10.0 and first["grades_released"] is False

    # pagination
    p1 = await client.get("/api/v1/assignments", params={"limit": 1}, headers=w.personas["trainer_a"].headers)
    body = p1.json()
    assert [x["assignment_id"] for x in body["data"]] == [str(a2)] and body["page"]["has_more"] is True
    p2 = await client.get(
        "/api/v1/assignments",
        params={"limit": 1, "cursor": body["page"]["next_cursor"]},
        headers=w.personas["trainer_a"].headers,
    )
    assert [x["assignment_id"] for x in p2.json()["data"]] == [str(a1)]

    # trainer of org B sees only its own
    rb = await client.get("/api/v1/assignments", headers=w.personas["trainer_b"].headers)
    assert [x["assignment_id"] for x in rb.json()["data"]] == [str(other_org)]


async def test_staff_assignment_list_denies_students(client, world: World) -> None:
    r = await client.get("/api/v1/assignments", headers=world.personas["student"].headers)
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"


async def _submission(db: Any, w: World, aid: uuid.UUID, user: uuid.UUID, org: uuid.UUID) -> uuid.UUID:
    await system_context(db, "test.factory")
    sid = uuid7()
    db.add(
        AssignmentSubmission(
            id=sid,
            assignment_id=aid,
            user_id=user,
            organization_id=org,
            body_text="my answer",
            status="graded",
            score=Decimal(7),
            feedback_md="Good",
        )
    )
    await db.flush()
    return sid


async def test_get_submission_by_id_owner_staff_and_others(client, db, world: World) -> None:
    """GET /assignment-submissions/{id}: owner (grade hidden until release), trainer with
    assignment.grade on the batch (full view), everyone else 404 (incl. cross-tenant)."""
    w = world
    aid = await _assignment(db, w, w.org_a, w.batch_a, "Arrays worksheet")
    sid = await _submission(db, w, aid, w.personas["student"].id, w.org_a)
    url = f"/api/v1/assignment-submissions/{sid}"

    own = await client.get(url, headers=w.personas["student"].headers)
    assert own.status_code == 200, own.text
    body = own.json()
    assert body["id"] == str(sid) and body["body_text"] == "my answer"
    assert "score" not in body and "feedback_md" not in body  # grades not released yet

    tr = await client.get(url, headers=w.personas["trainer_a"].headers)
    assert tr.status_code == 200, tr.text
    assert tr.json()["score"] == 7.0 and tr.json()["feedback_md"] == "Good"

    # released -> owner sees the grade
    await system_context(db, "test.factory")
    a = await db.get(Assignment, aid)
    assert a is not None
    from app.core.time import utcnow

    a.grades_released_at = utcnow()
    await db.flush()
    own2 = await client.get(url, headers=w.personas["student"].headers)
    assert own2.json()["score"] == 7.0

    # another learner of the same org, the other org's trainer, and an unknown id: 404
    other = await w.persona("student_a2", org_ids=(w.org_a,))
    for headers in (other.headers, w.personas["trainer_b"].headers, w.personas["student_b"].headers):
        r = await client.get(url, headers=headers)
        assert r.status_code == 404 and r.json()["code"] == "not_found", r.text
    r = await client.get(f"/api/v1/assignment-submissions/{uuid7()}", headers=w.personas["trainer_a"].headers)
    assert r.status_code == 404
    # anonymous
    assert (await client.get(url)).status_code == 401
