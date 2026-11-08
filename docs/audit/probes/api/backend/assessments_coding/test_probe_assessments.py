"""Audit probes for assessments (Phase A). Each test asserts the EXPECTED (spec) behaviour, so a
failure = a finding. Prints evidence for the findings file."""

from __future__ import annotations

import uuid
from datetime import timedelta

from app.core.ids import uuid7
from app.modules.assessments.schemas import RuleIn
from tests.assessments.test_attempts import (
    API,
    assign,
    fixed,
    item,
    make_bank,
    make_test,
    sql,
    standard,
    start,
)
from tests.identity.factory import add_member
from tests.placement.world import World, find_keys, idem


async def test_probe_overlapping_rules_publish_ok_but_start_fails(client, world: World, db) -> None:
    """validate() checks each rule's pool independently; build_layout() de-duplicates across rules.
    A fixed rule + a random rule over the same topic needing the whole pool passes publish but
    every start fails."""
    t, qs = await make_bank(db, world)
    test_id = await make_test(
        db,
        world,
        [("S", None, [fixed(qs[0]), RuleIn(rule_type="random", topic_id=t, draw_count=4)])],
        duration_seconds=600,
    )  # make_test publishes (would raise if infeasible)
    await assign(db, world, test_id)
    r = await start(client, world.personas["student"], test_id)
    print("START", r.status_code, r.text[:300])
    assert r.status_code == 201, "publish accepted an infeasible test; start fails for every student"


async def test_probe_answer_keys_leak_while_other_batch_window_open(client, world: World, db) -> None:
    """Same test assigned to batch_a (closed) and batch_a2 (still open). Student A's review shows
    correct answers while a student of batch_a2 can still start the very same fixed questions."""
    _, qs = await make_bank(db, world)
    test_id = await make_test(db, world, [("S", None, [fixed(q) for q in qs])], duration_seconds=1800)
    a1 = await assign(db, world, test_id)  # batch_a
    await assign(db, world, test_id, batch=world.batch_a2)  # batch_a2, open for 2 more hours
    other = await world.persona("student_a2", org_ids=(world.org_a,))
    await add_member(db, world.org_a, other.id, "student", world.batch_a2)
    student = world.personas["student"]
    aid = (await start(client, student, test_id)).json()["attempt_id"]
    r = await client.post(
        f"{API}/attempts/{aid}/submit",
        json={"final_items": [item(qs[0], 1)]},
        headers={**student.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    await sql(
        db,
        "UPDATE test_assignments SET available_until = now() - interval '1 minute', "
        "available_from = now() - interval '3 hours' WHERE id = :a",
        a=a1,
    )
    rev = (await client.get(f"{API}/attempts/{aid}/review", headers=student.headers)).json()
    leaked = find_keys(rev)
    print("REVIEW phase", rev.get("phase"), "keys present:", sorted(leaked))
    r2 = await start(client, other, test_id)
    print("OTHER BATCH START", r2.status_code)
    assert r2.status_code == 201
    assert not leaked, "answer keys visible while the same test is still open for another batch"


async def test_probe_answer_keys_leak_vs_window_extension_override(client, world: World, db) -> None:
    """Student X has window_extension; student Y (no override) gets keys at window close while X
    can still start/take the test."""
    _, qs = await make_bank(db, world)
    test_id = await make_test(db, world, [("S", None, [fixed(q) for q in qs])], duration_seconds=600)
    a1 = await assign(db, world, test_id)
    x = await world.persona("student_x", org_ids=(world.org_a,))
    await add_member(db, world.org_a, x.id, "student", world.batch_a)
    r = await client.post(
        f"{API}/tests/{test_id}/overrides",
        json={
            "user_id": str(x.id),
            "test_assignment_id": str(a1),
            "window_extension_seconds": 86400,
            "reason": "medical leave",
        },
        headers=world.personas["trainer_a"].headers,
    )
    assert r.status_code == 201, r.text
    student = world.personas["student"]
    aid = (await start(client, student, test_id)).json()["attempt_id"]
    await client.post(f"{API}/attempts/{aid}/submit", json={}, headers={**student.headers, **idem()})
    await sql(
        db,
        "UPDATE test_assignments SET available_until = now() - interval '1 minute', "
        "available_from = now() - interval '3 hours' WHERE id = :a",
        a=a1,
    )
    rev = (await client.get(f"{API}/attempts/{aid}/review", headers=student.headers)).json()
    rx = await start(client, x, test_id)
    print("phase", rev["phase"], "keys:", sorted(find_keys(rev)), "| extended student start:", rx.status_code)
    assert rx.status_code == 201
    assert not find_keys(rev), "keys revealed while an extended student can still take the test"


async def test_probe_client_cannot_send_score_fields(client, world: World, db) -> None:
    _, qs, body = await standard(db, world, client)
    aid, student = body["attempt_id"], world.personas["student"]
    bad_item = {**item(qs[0], 1, correct=False), "is_correct": True, "marks_awarded": 100}
    r = await client.post(f"{API}/attempts/{aid}/autosave", json={"items": [bad_item]}, headers=student.headers)
    print("AUTOSAVE extra fields", r.status_code, r.headers.get("content-type"), r.text[:200])
    assert r.status_code == 400 and r.headers["content-type"].startswith("application/problem+json")
    r = await client.post(
        f"{API}/attempts/{aid}/submit",
        json={"final_items": [], "score": 100},
        headers={**student.headers, **idem()},
    )
    print("SUBMIT extra fields", r.status_code, r.text[:200])
    assert r.status_code == 400


async def test_probe_attempt_id_validation_and_404_shapes(client, world: World, db) -> None:
    student = world.personas["student"]
    r = await client.get(f"{API}/attempts/not-a-uuid/state", headers=student.headers)
    print("BAD UUID", r.status_code, r.headers.get("content-type"), r.text[:200])
    assert r.status_code in (400, 404, 422) and "problem+json" in r.headers["content-type"]
    r = await client.get(f"{API}/attempts/{uuid7()}/review", headers=student.headers)
    print("UNKNOWN", r.status_code, r.text[:200])
    assert r.status_code == 404 and r.json()["code"] == "not_found"


async def test_probe_section_timeouts_before_test_deadline(client, world: World, db) -> None:
    """Sequential test whose section durations sum to less than the test duration: after the last
    section times out the attempt stays in_progress (nothing writable) until the test deadline."""
    _, qs = await make_bank(db, world)
    test_id = await make_test(
        db,
        world,
        [("A", 60, [fixed(qs[0])]), ("B", 60, [fixed(qs[1])])],
        duration_seconds=3600,
        navigation_mode="section_locked",
    )
    await assign(db, world, test_id)
    student = world.personas["student"]
    body = (await start(client, student, test_id)).json()
    aid = body["attempt_id"]
    await sql(
        db,
        "UPDATE attempt_sections SET deadline_at = now() - interval '10 minutes', "
        "started_at = now() - interval '11 minutes' WHERE attempt_id = :a AND status = 'active'",
        a=aid,
    )
    await sql(
        db,
        "UPDATE test_attempts SET started_at = now() - interval '11 minutes' WHERE id = :a",
        a=aid,
    )
    r = await client.get(f"{API}/attempts/{aid}/time", headers=student.headers)
    st = await sql(db, "SELECT status FROM attempt_sections WHERE attempt_id = :a ORDER BY position", a=aid)
    att = await sql(db, "SELECT status FROM test_attempts WHERE id = :a", a=aid)
    print("TIME", r.status_code, r.json().get("status"), "sections", [s[0] for s in st], "attempt", att[0][0])
    assert att[0][0] != "in_progress", "all sections timed out but attempt still in_progress"


async def test_probe_my_attempts_has_no_pagination(client, world: World, db) -> None:
    student = world.personas["student"]
    r = await client.get(f"{API}/me/attempts?limit=1", headers=student.headers)
    print("ME/ATTEMPTS keys", sorted(r.json().keys()))
    assert "meta" in r.json() or "next_cursor" in r.json(), "no cursor pagination (hard cap 200)"


async def test_probe_unknown_test_id_on_start(client, world: World, db) -> None:
    r = await start(client, world.personas["student"], uuid.uuid4())
    print("START unknown", r.status_code, r.text[:200])
    assert r.status_code == 404


async def test_probe_start_requires_entitlement_or_assignment_not_bypassed(
    client, world: World, db, no_access
) -> None:
    """Student of college B with a valid assignment id from college A."""
    _, qs = await make_bank(db, world)
    test_id = await make_test(db, world, [("S", None, [fixed(qs[0])])], duration_seconds=600)
    a = await assign(db, world, test_id)
    r = await client.post(
        f"{API}/attempts",
        json={"test_id": str(test_id), "test_assignment_id": str(a)},
        headers={**world.personas["student_b"].headers, **idem()},
    )
    print("FOREIGN ASSIGNMENT", r.status_code, r.text[:150])
    assert r.status_code in (403, 404)
    r = await client.get(f"{API}/tests/{test_id}", headers=world.personas["student_b"].headers)
    print("DETAIL unentitled", r.status_code, r.json().get("code"))
    assert r.status_code == 403
    _ = timedelta
