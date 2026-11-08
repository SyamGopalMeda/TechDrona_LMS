"""Regression (audit ADM-35): the mentor console's company readiness is computed from real
practice data instead of always being ``[]``."""

from __future__ import annotations

import uuid

from tests.mentoring.test_mentoring import book, grant_package, mentor, publish
from tests.placement.conftest import allow_access  # noqa: F401
from tests.placement.test_placement import _practice_bank
from tests.placement.world import World, correct_response, idem

API = "/api/v1"


async def test_mentor_detail_readiness_from_practised_company_paths(
    client,
    db,
    world: World,
    allow_access,  # noqa: F811
) -> None:
    m = await mentor(world)
    student, author = world.personas["student"], world.personas["author"]
    t, qs = await _practice_bank(db, world, 2)
    # Admin-as-mentor (D2) is assigned to learners who booked them
    (slot,) = await publish(client, m, 30)
    await grant_package(db, student)
    assert (await book(client, student, slot["id"])).status_code == 201

    d = await client.get(f"{API}/mentor/students/{student.id}", headers=m.headers)
    assert d.status_code == 200, d.text
    assert d.json()["readiness"] == []

    cid = (
        await client.post(
            f"{API}/studio/companies",
            json={"slug": "readyco", "name": "ReadyCo", "hub_status": "published"},
            headers=author.headers,
        )
    ).json()["id"]
    pid = str(uuid.uuid4())
    body = {
        "company_id": cid,
        "role_name": "SDE",
        "status": "published",
        "pattern": [{"section": "Q", "topic_id": str(t), "weight": 1, "minutes": 10, "question_count": 5}],
        "steps": [{"step_type": "practice_set", "title": "S", "topic_id": str(t)}],
    }
    r = await client.put(f"{API}/studio/company-paths/{pid}", json=body, headers=author.headers)
    assert r.status_code == 200, r.text
    step_id = r.json()["steps"][0]["id"]
    s = await client.post(
        f"{API}/practice/sessions",
        json={"mode": "company_step", "company_path_step_id": step_id},
        headers={**student.headers, **idem()},
    )
    assert s.status_code == 201, s.text
    by = {str(q.qv_id): q for q in qs}
    for item in s.json()["items"]:
        qv = item["question"]["question_version_id"]
        r = await client.post(
            f"{API}/practice/sessions/{s.json()['session_id']}/answers",
            json={"question_version_id": qv, "response": correct_response(by[qv]), "time_spent_ms": 1},
            headers={**student.headers, **idem()},
        )
        assert r.status_code == 200, r.text

    d = await client.get(f"{API}/mentor/students/{student.id}", headers=m.headers)
    assert d.status_code == 200, d.text
    (row,) = d.json()["readiness"]
    assert row["company_slug"] == "readyco" and row["company_path_id"] == pid
    assert row["role_name"] == "SDE" and row["score_pct"] == 100.0
