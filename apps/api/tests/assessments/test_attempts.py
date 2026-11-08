"""Assessments: attempt lifecycle, timer, autosave, binding/rebind, scoring, review policy,
assignments/overrides scoping (ADR-0013, api-specification §14-15)."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.assessments import studio
from app.modules.assessments.models import TestAssignment
from app.modules.assessments.schemas import RuleIn, SectionIn, SectionsPut, TestCreate
from app.modules.placement.schemas import OptionDelivery, QuestionDelivery
from tests.placement.world import (
    FORBIDDEN_KEYS,
    Q,
    World,
    correct_response,
    find_keys,
    idem,
    question,
    topic,
    wrong_response,
)

API = "/api/v1"


# --------------------------------------------------------------------------- helpers


async def make_bank(db, w: World, *, marks: str = "2", negative: str = "0.5") -> tuple[uuid.UUID, list[Q]]:
    t = await topic(db, "quant/percentages")
    qs = [
        await question(
            db,
            w.personas["author"],
            w.personas["reviewer"],
            t,
            qtype=qt,
            marks=marks,
            negative=negative,
            stem=f"Q {qt}",
        )
        for qt in ("mcq_single", "mcq_multi", "numeric", "fill_blank")
    ]
    return t, qs


async def make_test(
    db,
    w: World,
    sections: list[tuple[str, int | None, list[RuleIn]]],
    *,
    kind: str = "mock",
    org: uuid.UUID | None = None,
    **settings: Any,
) -> uuid.UUID:
    await system_context(db, "test.factory")
    body = TestCreate(title="Demo mock", test_kind=kind, **settings)
    t = await studio.create_test(db, w.personas["author"].principal, body, org)
    await studio.put_sections(
        db,
        t,
        SectionsPut(
            sections=[
                SectionIn(title=title, duration_seconds=dur, rules=rules) for title, dur, rules in sections
            ]
        ),
    )
    await studio.publish(db, t)
    return t.id


def fixed(q: Q, **kw: Any) -> RuleIn:
    return RuleIn(rule_type="fixed", question_id=q.question_id, **kw)


async def assign(
    db,
    w: World,
    test_id: uuid.UUID,
    *,
    batch: uuid.UUID | None = None,
    start: timedelta = timedelta(hours=-1),
    end: timedelta = timedelta(hours=2),
    release_mode: str = "immediate",
    attempts: int | None = None,
) -> uuid.UUID:
    await system_context(db, "test.factory")
    now = utcnow()
    aid = uuid7()
    db.add(
        TestAssignment(
            id=aid,
            test_id=test_id,
            organization_id=w.org_a,
            batch_id=batch or w.batch_a,
            available_from=now + start,
            available_until=now + end,
            attempts_allowed=attempts,
            release_mode=release_mode,
            assigned_by=w.personas["trainer_a"].id,
        )
    )
    await db.flush()
    return aid


async def start(client, who, test_id, **kw: Any) -> Any:
    return await client.post(
        f"{API}/attempts", json={"test_id": str(test_id), **kw}, headers={**who.headers, **idem()}
    )


async def standard(db, w: World, client, **test_kw: Any) -> tuple[uuid.UUID, list[Q], dict[str, Any]]:
    _, qs = await make_bank(db, w)
    test_id = await make_test(
        db, w, [("Quant", None, [fixed(q) for q in qs])], duration_seconds=1800, **test_kw
    )
    await assign(db, w, test_id)
    r = await start(client, w.personas["student"], test_id)
    assert r.status_code == 201, r.text
    return test_id, qs, r.json()


async def sql(db, stmt_: str, **params: Any) -> Any:
    await system_context(db, "test")
    res = await db.execute(text(stmt_), params)
    return res.all() if res.returns_rows else None


def item(q: Q, seq: int, *, correct: bool = True, **kw: Any) -> dict[str, Any]:
    return {
        "question_version_id": str(q.qv_id),
        "response": correct_response(q) if correct else wrong_response(q),
        "client_seq": seq,
        "time_spent_ms": 1000,
        **kw,
    }


# --------------------------------------------------------------------------- key secrecy


def test_delivery_schemas_have_no_key_fields() -> None:
    for model in (QuestionDelivery, OptionDelivery):
        assert not (set(model.model_fields) & (FORBIDDEN_KEYS | {"feedback", "feedback_html"})), model


async def test_start_returns_layout_without_keys_and_binds_session(client, world: World, db) -> None:
    test_id, qs, body = await standard(db, world, client)
    student = world.personas["student"]
    assert body["status"] == "in_progress" and body["binding"]["rebinds_remaining"] == 2
    assert body["autosave"]["max_interval_ms"] == 10000
    assert find_keys(body) == set()
    questions = body["sections"][0]["questions"]
    assert {q["question_version_id"] for q in questions} == {str(q.qv_id) for q in qs}
    assert questions[0]["marks"] == "2.00"
    row = (
        await sql(
            db,
            "SELECT bound_session_id, bound_device_id, layout FROM test_attempts WHERE id = :a",
            a=body["attempt_id"],
        )
    )[0]
    assert row[0] == student.principal.session_id and row[1] == student.principal.device_id
    hold = (
        await sql(
            db, "SELECT idle_hold_until FROM auth_sessions WHERE id = :s", s=student.principal.session_id
        )
    )[0][0]
    assert hold is not None and hold > utcnow() + timedelta(minutes=30)
    locked = (await sql(db, "SELECT settings_locked_at FROM tests WHERE id = :t", t=test_id))[0][0]
    assert locked is not None
    # state endpoint: also key-free
    st = (await client.get(f"{API}/attempts/{body['attempt_id']}/state", headers=student.headers)).json()
    assert find_keys(st) == set() and st["server_now"] and st["deadline_at"] == body["deadline_at"]
    # sessions hook: the bound session holds an in-progress attempt (never auto-evicted)
    from app.modules.sessions.service import sessions_with_attempts

    await system_context(db, "test")
    assert await sessions_with_attempts(db, [student.principal.session_id, uuid7()]) == {
        student.principal.session_id
    }
    ev = await sql(db, "SELECT event_type FROM outbox_events WHERE aggregate_id = :a", a=body["attempt_id"])
    assert [e[0] for e in ev] == ["attempt.started"]


async def test_start_rules(client, world: World, db, no_access) -> None:
    _, qs = await make_bank(db, world)
    student, other = world.personas["student"], world.personas["student_b"]
    test_id = await make_test(
        db, world, [("S", None, [fixed(qs[0])])], duration_seconds=600, attempts_allowed=1
    )
    # no assignment, not free, no entitlement -> 403
    r = await start(client, student, test_id)
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required"
    await assign(db, world, test_id, start=timedelta(hours=1), end=timedelta(hours=3))
    r = await start(client, student, test_id)
    assert r.status_code == 409 and r.json()["code"] == "test_not_open"
    test2 = await make_test(
        db, world, [("S", None, [fixed(qs[0])])], duration_seconds=600, attempts_allowed=1
    )
    await assign(db, world, test2, start=timedelta(hours=-3), end=timedelta(hours=-1))
    r = await start(client, student, test2)
    assert r.status_code == 409 and r.json()["code"] == "test_window_closed"
    test3 = await make_test(
        db, world, [("S", None, [fixed(qs[0])])], duration_seconds=600, attempts_allowed=1
    )
    await assign(db, world, test3)
    r = await start(client, other, test3)  # student of legacy org B is not in the assigned batch
    assert r.status_code == 403
    r = await start(client, student, test3)
    assert r.status_code == 201
    r2 = await start(client, student, test3)
    assert r2.status_code == 409 and r2.json()["code"] == "active_attempt_exists"
    assert r2.json()["attempt_id"] == r.json()["attempt_id"]
    await client.post(
        f"{API}/attempts/{r.json()['attempt_id']}/submit", json={}, headers={**student.headers, **idem()}
    )
    r3 = await start(client, student, test3)
    assert r3.status_code == 409 and r3.json()["code"] == "attempt_limit_reached"
    # settings lock after the first attempt (SoD-08)
    r = await client.patch(
        f"{API}/studio/tests/{test3}",
        json={"duration_seconds": 900},
        headers=world.personas["author"].headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "test_settings_locked"


async def test_session_too_short_for_attempt(client, world: World, db) -> None:
    _, qs = await make_bank(db, world)
    test_id = await make_test(db, world, [("S", None, [fixed(qs[0])])], duration_seconds=3600)
    await assign(db, world, test_id)
    short = await world.new_session(
        world.personas["student"], same_device=True, absolute=timedelta(minutes=30)
    )
    r = await start(client, short, test_id)
    assert r.status_code == 409 and r.json()["code"] == "session_too_short_for_attempt"


async def test_restricted_principal_cannot_start_but_can_list(client, world: World, db) -> None:
    _, qs = await make_bank(db, world)
    test_id = await make_test(db, world, [("S", None, [fixed(qs[0])])], duration_seconds=600)
    await assign(db, world, test_id)
    from dataclasses import replace

    p = replace(world.personas["student"].principal, scope="restricted", restriction_level=3)
    headers = world.auth.login(p)
    r = await client.post(f"{API}/attempts", json={"test_id": str(test_id)}, headers={**headers, **idem()})
    assert r.status_code == 403 and r.json()["code"] == "account_restricted"
    r = await client.get(f"{API}/me/tests", headers=headers)
    assert r.status_code == 200 and r.json()["items"][0]["test_id"] == str(test_id)


# --------------------------------------------------------------------------- autosave


async def test_autosave_batch_same_question_twice_keeps_newest_seq(client, world: World, db) -> None:
    """The batched upsert (one statement per save) equals applying items in client_seq order,
    even when one save carries the same question twice, in either order."""
    _, qs, body = await standard(db, world, client)
    aid, student = body["attempt_id"], world.personas["student"]
    url = f"{API}/attempts/{aid}/autosave"
    payload = {"items": [item(qs[0], 7, correct=False), item(qs[0], 5, correct=True), item(qs[1], 6)]}
    r = await client.post(url, json=payload, headers=student.headers)
    assert r.status_code == 200, r.text
    assert r.json()["acked_seq"] == 7
    rows = await sql(
        db,
        "SELECT question_version_id, client_seq, response FROM attempt_responses WHERE attempt_id = :a",
        a=aid,
    )
    by_qv = {str(q): (seq, resp) for q, seq, resp in rows}
    assert by_qv[str(qs[0].qv_id)] == (7, wrong_response(qs[0]))
    assert by_qv[str(qs[1].qv_id)][0] == 6
    events = await sql(
        db,
        "SELECT question_version_id, client_seq FROM attempt_events "
        "WHERE attempt_id = :a AND event_type = 'answer_saved' ORDER BY client_seq",
        a=aid,
    )
    assert [(str(q), seq) for q, seq in events] == [(str(qs[1].qv_id), 6), (str(qs[0].qv_id), 7)]


async def test_autosave_idempotent_and_order_safe(client, world: World, db) -> None:
    _, qs, body = await standard(db, world, client)
    aid, student = body["attempt_id"], world.personas["student"]
    url = f"{API}/attempts/{aid}/autosave"
    payload = {"items": [item(qs[0], 5, correct=False), item(qs[2], 6)]}
    r = await client.post(url, json=payload, headers=student.headers)
    assert r.status_code == 200, r.text
    assert r.json()["acked_seq"] == 6 and r.json()["status"] == "in_progress" and r.json()["server_now"]
    # exact duplicate (network retry): no change, no new events
    r = await client.post(url, json=payload, headers=student.headers)
    assert r.status_code == 200
    saved = await sql(
        db, "SELECT count(*) FROM attempt_events WHERE attempt_id = :a AND event_type = 'answer_saved'", a=aid
    )
    assert saved[0][0] == 2
    # an older client_seq arriving late never overwrites a newer answer
    r = await client.post(url, json={"items": [item(qs[0], 4, correct=True)]}, headers=student.headers)
    assert r.status_code == 200
    resp = await sql(
        db,
        "SELECT response, client_seq, is_correct, marks_awarded FROM attempt_responses "
        "WHERE attempt_id = :a AND question_version_id = :q",
        a=aid,
        q=qs[0].qv_id,
    )
    assert resp[0][1] == 5 and resp[0][0] == wrong_response(qs[0])
    assert resp[0][2] is None and resp[0][3] is None  # never scored during the attempt
    # newer seq wins; clearing an answer is allowed
    r = await client.post(
        url,
        json={"items": [{"question_version_id": str(qs[0].qv_id), "response": None, "client_seq": 9}]},
        headers=student.headers,
    )
    assert r.status_code == 200
    # invalid option id / foreign question rejected
    bad = {
        "items": [
            {
                "question_version_id": str(qs[0].qv_id),
                "response": {"option_ids": [str(uuid7())]},
                "client_seq": 10,
            }
        ]
    }
    assert (await client.post(url, json=bad, headers=student.headers)).status_code == 400
    foreign = {"items": [{"question_version_id": str(uuid7()), "response": None, "client_seq": 11}]}
    assert (await client.post(url, json=foreign, headers=student.headers)).status_code == 400
    # other users cannot touch the attempt
    r = await client.post(url, json=payload, headers=world.personas["student_b"].headers)
    assert r.status_code == 404
    # timer sync
    r = await client.get(f"{API}/attempts/{aid}/time", headers=student.headers)
    assert r.status_code == 200 and r.json()["deadline_at"] == body["deadline_at"]


async def test_integrity_events_are_advisory_and_consent_gated(client, world: World, db) -> None:
    _, qs = await make_bank(db, world)
    test_id = await make_test(db, world, [("S", None, [fixed(qs[0])])], duration_seconds=600)
    await assign(db, world, test_id, attempts=2)
    student = world.personas["student"]
    events = [{"type": "focus_lost", "client_seq": 1}, {"type": "focus_gained", "client_seq": 2}]
    r = await start(client, student, test_id, integrity_consent=True)
    aid = r.json()["attempt_id"]
    for _ in range(2):
        r = await client.post(
            f"{API}/attempts/{aid}/autosave", json={"events": events}, headers=student.headers
        )
        assert r.status_code == 200 and r.json()["ignored_events"] == 0
    n = await sql(
        db, "SELECT count(*) FROM attempt_events WHERE attempt_id = :a AND event_type LIKE 'focus%'", a=aid
    )
    assert n[0][0] == 2  # duplicates dropped
    await client.post(f"{API}/attempts/{aid}/submit", json={}, headers={**student.headers, **idem()})
    r = await start(client, student, test_id, integrity_consent=False)
    aid2 = r.json()["attempt_id"]
    r = await client.post(f"{API}/attempts/{aid2}/autosave", json={"events": events}, headers=student.headers)
    assert r.json()["ignored_events"] == 2
    res = (await client.get(f"{API}/attempts/{aid}/result", headers=student.headers)).json()
    assert res["integrity_status"] == "none"  # never auto-penalised


# --------------------------------------------------------------------------- timer / expiry


async def test_late_autosave_rejected_and_attempt_auto_submitted(client, world: World, db) -> None:
    _, qs, body = await standard(db, world, client)
    aid, student = body["attempt_id"], world.personas["student"]
    url = f"{API}/attempts/{aid}/autosave"
    assert (
        await client.post(url, json={"items": [item(qs[0], 1)]}, headers=student.headers)
    ).status_code == 200
    # inside the grace window (deadline passed 10 s ago, grace 30 s): still accepted
    await sql(db, "UPDATE test_attempts SET deadline_at = now() - interval '10 seconds' WHERE id = :a", a=aid)
    r = await client.post(url, json={"items": [item(qs[1], 2)]}, headers=student.headers)
    assert r.status_code == 200, r.text
    # past deadline + grace: rejected, and the attempt is closed server-side on the spot
    await sql(db, "UPDATE test_attempts SET deadline_at = now() - interval '45 seconds' WHERE id = :a", a=aid)
    r = await client.post(url, json={"items": [item(qs[2], 3)]}, headers=student.headers)
    assert r.status_code == 409 and r.json()["code"] == "attempt_closed"
    assert r.json()["attempt_status"] == "graded"
    row = (
        await sql(db, "SELECT status, submit_reason, submitted_at FROM test_attempts WHERE id = :a", a=aid)
    )[0]
    assert row[0] == "graded" and row[1] == "deadline" and row[2] is not None
    late = await sql(
        db,
        "SELECT count(*) FROM attempt_responses WHERE attempt_id = :a AND question_version_id = :q",
        a=aid,
        q=qs[2].qv_id,
    )
    assert late[0][0] == 0
    ev = await sql(db, "SELECT event_type FROM outbox_events WHERE aggregate_id = :a ORDER BY id", a=aid)
    assert [e[0] for e in ev] == ["attempt.started", "attempt.submitted", "attempt.scored"]
    res = (await client.get(f"{API}/attempts/{aid}/result", headers=student.headers)).json()
    assert res["score"] == 4.0  # two correct answers saved in time; late one ignored
    # submit after the fact returns the terminal state (no error, no re-scoring)
    r = await client.post(
        f"{API}/attempts/{aid}/submit",
        json={"final_items": [item(qs[3], 9)]},
        headers={**student.headers, **idem()},
    )
    assert r.status_code == 200 and r.json()["submit_reason"] == "deadline"
    assert (
        await sql(
            db,
            "SELECT count(*) FROM outbox_events WHERE aggregate_id = :a AND event_type = 'attempt.scored'",
            a=aid,
        )
    )[0][0] == 1


async def test_sweeper_auto_submits_untouched_attempts(client, world: World, db) -> None:
    _, _qs, body = await standard(db, world, client)
    aid = body["attempt_id"]
    from app.modules.assessments.tasks import sweep_expired_attempts

    await system_context(db, "test")
    assert await sweep_expired_attempts(db) == 0
    await sql(db, "UPDATE test_attempts SET deadline_at = now() - interval '5 minutes' WHERE id = :a", a=aid)
    assert await sweep_expired_attempts(db) == 1
    assert await sweep_expired_attempts(db) == 0  # idempotent
    row = (await sql(db, "SELECT status, submit_reason FROM test_attempts WHERE id = :a", a=aid))[0]
    assert tuple(row) == ("graded", "deadline")
    assert (await sql(db, "SELECT count(*) FROM attempt_results WHERE attempt_id = :a", a=aid))[0][0] == 1


async def test_override_extra_time_extends_running_attempt(client, world: World, db) -> None:
    test_id, _, body = await standard(db, world, client)
    trainer, student = world.personas["trainer_a"], world.personas["student"]
    before = (await sql(db, "SELECT deadline_at FROM test_attempts WHERE id = :a", a=body["attempt_id"]))[0][
        0
    ]
    r = await client.post(
        f"{API}/tests/{test_id}/overrides",
        json={
            "user_id": str(student.id),
            "extra_time_seconds": 900,
            "reason": "power cut during attempt",
            "batch_id": None,
        },
        headers=trainer.headers,
    )
    # ADM-42: a batch trainer's per-student body {user_id} resolves to the assignment of the
    # student's batch (it used to fall back to the org scope and answer 403).
    assert r.status_code == 201, r.text
    aid_assignment = (
        await sql(db, "SELECT test_assignment_id FROM test_attempts WHERE id = :a", a=body["attempt_id"])
    )[0][0]
    assert r.json()["test_assignment_id"] == str(aid_assignment)
    r = await client.post(
        f"{API}/tests/{test_id}/overrides",
        json={
            "user_id": str(student.id),
            "test_assignment_id": str(aid_assignment),
            "extra_time_seconds": 900,
            "reason": "power cut during attempt",
        },
        headers=trainer.headers,
    )
    assert r.status_code == 201, r.text
    after = (
        await sql(
            db,
            "SELECT deadline_at, extra_time_seconds FROM test_attempts WHERE id = :a",
            a=body["attempt_id"],
        )
    )[0]
    assert after[0] - before == timedelta(seconds=1800) and after[1] == 1800
    r = await client.post(
        f"{API}/tests/{test_id}/overrides",
        json={
            "user_id": str(student.id),
            "test_assignment_id": str(aid_assignment),
            "extra_attempts": 1,
            "reason": "accessibility",
        },
        headers=world.personas["trainer_b"].headers,
    )
    assert r.status_code == 403  # trainer of another company batch: no grant here
    assert (
        len((await client.get(f"{API}/tests/{test_id}/overrides", headers=trainer.headers)).json()["items"])
        == 2
    )


# --------------------------------------------------------------------------- scoring & review policy


async def test_scoring_with_negative_marking_and_review_phases(client, world: World, db) -> None:
    _, qs = await make_bank(db, world, marks="2", negative="0.5")
    test_id = await make_test(
        db,
        world,
        [
            ("Quant", None, [fixed(q) for q in qs[:3]]),
            ("Verbal", None, [fixed(qs[3], marks_each=Decimal("4"))]),
        ],
        duration_seconds=1800,
    )
    assignment = await assign(db, world, test_id)
    student = world.personas["student"]
    body = (await start(client, student, test_id)).json()
    aid = body["attempt_id"]
    # mcq_single correct (+2), mcq_multi partially chosen = wrong (-0.5), numeric unanswered (0),
    # fill_blank correct with case/space differences in a 4-mark rule (+4)
    multi = {
        "question_version_id": str(qs[1].qv_id),
        "response": {"option_ids": [str(qs[1].correct[0])]},
        "client_seq": 2,
    }
    fill = {
        "question_version_id": str(qs[3].qv_id),
        "response": {"value": "  PHOTOSYNTHESIS "},
        "client_seq": 3,
    }
    r = await client.post(
        f"{API}/attempts/{aid}/autosave", json={"items": [item(qs[0], 1), multi]}, headers=student.headers
    )
    assert r.status_code == 200
    # review before submit is refused (keys never leave during the attempt)
    r = await client.get(f"{API}/attempts/{aid}/review", headers=student.headers)
    assert r.status_code == 409 and r.json()["code"] == "results_not_released"
    r = await client.post(
        f"{API}/attempts/{aid}/submit", json={"final_items": [fill]}, headers=student.headers
    )
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    key = idem()
    r = await client.post(
        f"{API}/attempts/{aid}/submit", json={"final_items": [fill]}, headers={**student.headers, **key}
    )
    assert r.status_code == 200, r.text
    assert r.json()["submit_reason"] == "user" and r.json()["result_release"]["mode"] == "immediate"
    replay = await client.post(
        f"{API}/attempts/{aid}/submit", json={"final_items": [fill]}, headers={**student.headers, **key}
    )
    assert replay.headers.get("Idempotency-Replayed") == "true"

    # mock default policy, window still open -> after_submit: score yes, correctness/keys no
    res = (await client.get(f"{API}/attempts/{aid}/result", headers=student.headers)).json()
    assert res["phase"] == "after_submit"
    assert res["score"] == 5.5 and res["max_score"] == 10.0 and res["percentage"] == 55.0
    assert "correct_count" not in res and find_keys(res) == set()
    assert [s["score"] for s in res["section_scores"]] == ["1.50", "4.00"]
    rev = (await client.get(f"{API}/attempts/{aid}/review", headers=student.headers)).json()
    assert find_keys(rev) == set()
    answered = {
        q["question_version_id"] for s in rev["sections"] for q in s["questions"] if q["your_response"]
    }
    assert answered == {str(qs[0].qv_id), str(qs[1].qv_id), str(qs[3].qv_id)}

    # after the window closes -> after_close: correctness, keys and explanations
    await sql(
        db,
        "UPDATE test_assignments SET available_until = now() - interval '1 minute', "
        "available_from = now() - interval '3 hours' WHERE id = :a",
        a=assignment,
    )
    res = (await client.get(f"{API}/attempts/{aid}/result", headers=student.headers)).json()
    assert res["phase"] == "after_close"
    assert (res["correct_count"], res["incorrect_count"], res["unanswered_count"]) == (2, 1, 1)
    assert res["percentile"] is None and res["percentile_note"] == "insufficient_cohort"
    rev = (await client.get(f"{API}/attempts/{aid}/review", headers=student.headers)).json()
    by_qv = {q["question_version_id"]: q for s in rev["sections"] for q in s["questions"]}
    assert by_qv[str(qs[0].qv_id)]["is_correct"] is True and by_qv[str(qs[0].qv_id)]["marks_awarded"] == 2.0
    assert by_qv[str(qs[1].qv_id)]["marks_awarded"] == -0.5
    assert by_qv[str(qs[2].qv_id)]["is_correct"] is None
    assert by_qv[str(qs[1].qv_id)]["correct_option_ids"] == sorted(str(i) for i in qs[1].correct)
    assert by_qv[str(qs[2].qv_id)]["correct_answer"] == "12.5" and by_qv[str(qs[2].qv_id)]["explanation_html"]

    # other students cannot read it; the batch trainer can (scope), the other tenant's trainer cannot
    assert (
        await client.get(f"{API}/attempts/{aid}/result", headers=world.personas["student_b"].headers)
    ).status_code == 404
    assert (
        await client.get(f"{API}/attempts/{aid}/result", headers=world.personas["trainer_a"].headers)
    ).status_code == 200
    assert (
        await client.get(f"{API}/attempts/{aid}/result", headers=world.personas["trainer_b"].headers)
    ).status_code == 404
    lst = (
        await client.get(f"{API}/tests/{test_id}/attempts", headers=world.personas["trainer_a"].headers)
    ).json()
    assert [a["attempt_id"] for a in lst["items"]] == [aid]
    lst = (
        await client.get(f"{API}/tests/{test_id}/attempts", headers=world.personas["trainer_b"].headers)
    ).json()
    assert lst["items"] == []


async def test_manual_release(client, world: World, db) -> None:
    _, qs = await make_bank(db, world)
    test_id = await make_test(db, world, [("S", None, [fixed(qs[0])])], duration_seconds=600)
    assignment = await assign(db, world, test_id, release_mode="manual")
    student, trainer = world.personas["student"], world.personas["trainer_a"]
    aid = (await start(client, student, test_id)).json()["attempt_id"]
    r = await client.post(
        f"{API}/attempts/{aid}/submit",
        json={"final_items": [item(qs[0], 1)]},
        headers={**student.headers, **idem()},
    )
    assert r.json()["result_release"]["mode"] == "manual"
    r = await client.get(f"{API}/attempts/{aid}/result", headers=student.headers)
    assert r.status_code == 409 and r.json()["code"] == "results_not_released"
    r = await client.post(
        f"{API}/tests/{test_id}/results/release",
        json={"test_assignment_id": str(assignment)},
        headers=world.personas["trainer_b"].headers,
    )
    assert r.status_code == 403  # trainer of another company batch
    r = await client.post(
        f"{API}/tests/{test_id}/results/release",
        json={"test_assignment_id": str(assignment)},
        headers=trainer.headers,
    )
    assert r.status_code == 200 and r.json()["results_released"] == 1
    r = await client.get(f"{API}/attempts/{aid}/result", headers=student.headers)
    assert r.status_code == 200 and r.json()["score"] == 2.0


# --------------------------------------------------------------------------- navigation


async def test_section_locked_navigation(client, world: World, db) -> None:
    _, qs = await make_bank(db, world)
    test_id = await make_test(
        db,
        world,
        [("A", 600, [fixed(qs[0]), fixed(qs[1])]), ("B", 600, [fixed(qs[2]), fixed(qs[3])])],
        duration_seconds=1800,
        navigation_mode="section_locked",
    )
    await assign(db, world, test_id)
    student = world.personas["student"]
    body = (await start(client, student, test_id)).json()
    aid = body["attempt_id"]
    sa, sb = body["sections"]
    assert (
        sa["status"] == "active"
        and "questions" in sa
        and sb["status"] == "not_started"
        and "questions" not in sb
    )
    url = f"{API}/attempts/{aid}/autosave"
    r = await client.post(url, json={"items": [item(qs[2], 1)]}, headers=student.headers)
    assert r.status_code == 409 and r.json()["code"] == "section_locked"
    r = await client.post(f"{API}/attempts/{aid}/sections/{sa['section_id']}/submit", headers=student.headers)
    assert r.status_code == 200
    secs = r.json()["sections"]
    assert secs[0]["status"] == "submitted" and secs[1]["status"] == "active" and "questions" in secs[1]
    r = await client.post(url, json={"items": [item(qs[0], 2)]}, headers=student.headers)
    assert r.status_code == 409 and r.json()["code"] == "section_locked"
    assert (
        await client.post(url, json={"items": [item(qs[2], 3)]}, headers=student.headers)
    ).status_code == 200
    r = await client.post(f"{API}/attempts/{aid}/sections/{sa['section_id']}/enter", headers=student.headers)
    assert r.status_code == 409  # no return to a submitted section
    # the section timer runs out -> section B (the last) times out and the attempt closes (BE-10)
    await sql(
        db,
        "UPDATE attempt_sections SET deadline_at = now() - interval '2 minutes' "
        "WHERE attempt_id = :a AND status = 'active'",
        a=aid,
    )
    r = await client.post(url, json={"items": [item(qs[3], 4)]}, headers=student.headers)
    assert r.status_code == 409 and r.json()["code"] == "attempt_closed"


# --------------------------------------------------------------------------- binding / rebind


async def test_crash_resume_same_device_reattaches_without_rebind(client, world: World, db) -> None:
    _, qs, body = await standard(db, world, client)
    aid, student = body["attempt_id"], world.personas["student"]
    await client.post(
        f"{API}/attempts/{aid}/autosave", json={"items": [item(qs[0], 1)]}, headers=student.headers
    )
    relogin = await world.new_session(student, same_device=True)
    r = await client.get(f"{API}/attempts/{aid}/state", headers=relogin.headers)
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["reattached"] is True and st["binding"]["rebinds_remaining"] == 2
    assert (
        st["responses"][0]["question_version_id"] == str(qs[0].qv_id)
        and st["responses"][0]["client_seq"] == 1
    )
    row = (await sql(db, "SELECT bound_session_id, rebind_count FROM test_attempts WHERE id = :a", a=aid))[0]
    assert row[0] == relogin.principal.session_id and row[1] == 0
    ev = await sql(db, "SELECT event_type FROM attempt_events WHERE attempt_id = :a", a=aid)
    assert "reattach_same_device" in {e[0] for e in ev} and "rebind" not in {e[0] for e in ev}
    # explicit resume in the bound session logs a resume event
    r = await client.post(f"{API}/attempts/{aid}/resume", headers=relogin.headers)
    assert r.status_code == 200 and "reattached" not in r.json()


async def test_rebind_rules(client, world: World, db, monkeypatch) -> None:
    from app.modules.assessments import ratelimit

    # This scenario makes 6 rebind calls; the ATT-05 5/h limit itself is covered in
    # tests/assessments/test_audit_fixes.py.
    monkeypatch.setitem(ratelimit.LIMITS, "att05_rebind", ratelimit.Rule(50, ratelimit.HOUR))
    _, qs, body = await standard(db, world, client)
    aid, student = body["attempt_id"], world.personas["student"]
    phone = await world.new_session(student, same_device=False)
    r = await client.get(f"{API}/attempts/{aid}/state", headers=phone.headers)
    assert r.status_code == 409 and r.json()["code"] == "attempt_bound_elsewhere"
    p = r.json()
    assert (
        p["bound_device_label"] == "Chrome on Windows"
        and p["rebinds_remaining"] == 2
        and p["otp_required"] is False
    )
    assert p["read_only"]["answered_count"] == 0 and "questions" not in p
    r = await client.post(
        f"{API}/attempts/{aid}/autosave", json={"items": [item(qs[0], 1)]}, headers=phone.headers
    )
    assert r.status_code == 409 and r.json()["code"] == "attempt_bound_elsewhere"
    r = await client.post(f"{API}/attempts/{aid}/rebind", json={"confirm": True}, headers=phone.headers)
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    r = await client.post(
        f"{API}/attempts/{aid}/rebind", json={"confirm": False}, headers={**phone.headers, **idem()}
    )
    assert r.status_code == 400
    r = await client.post(
        f"{API}/attempts/{aid}/rebind", json={"confirm": True}, headers={**phone.headers, **idem()}
    )
    assert r.status_code == 200, r.text
    assert r.json()["binding"]["rebinds_remaining"] == 1 and find_keys(r.json()) == set()
    # the old session is now the "other device"
    r = await client.post(
        f"{API}/attempts/{aid}/autosave", json={"items": [item(qs[0], 2)]}, headers=student.headers
    )
    assert r.status_code == 409 and r.json()["code"] == "attempt_bound_elsewhere"
    r = await client.post(
        f"{API}/attempts/{aid}/rebind", json={"confirm": True}, headers={**student.headers, **idem()}
    )
    assert r.status_code == 200 and r.json()["binding"]["rebinds_remaining"] == 0
    tablet = await world.new_session(student, same_device=False)
    r = await client.post(
        f"{API}/attempts/{aid}/rebind", json={"confirm": True}, headers={**tablet.headers, **idem()}
    )
    assert r.status_code == 409 and r.json()["code"] == "rebind_limit_reached"
    row = (await sql(db, "SELECT rebind_count, bound_session_id FROM test_attempts WHERE id = :a", a=aid))[0]
    assert row[0] == 2 and row[1] == student.principal.session_id
    ev = [
        e[0]
        for e in await sql(
            db, "SELECT event_type FROM attempt_events WHERE attempt_id = :a ORDER BY occurred_at", a=aid
        )
    ]
    assert ev.count("rebind") == 2 and ev.count("rebind_refused") == 1 and ev.count("rebind_requested") == 3
    # a trainer override allows one more device switch
    r = await client.post(
        f"{API}/attempts/{aid}/rebind-override",
        json={"reason": "laptop battery died"},
        headers=world.personas["trainer_b"].headers,
    )
    assert r.status_code == 404
    r = await client.post(
        f"{API}/attempts/{aid}/rebind-override",
        json={"reason": "laptop battery died"},
        headers=world.personas["trainer_a"].headers,
    )
    assert r.status_code == 201
    r = await client.post(
        f"{API}/attempts/{aid}/rebind", json={"confirm": True}, headers={**tablet.headers, **idem()}
    )
    assert r.status_code == 200


async def test_rebind_needs_otp_at_l2(client, world: World, db, mail) -> None:
    _, _qs, body = await standard(db, world, client)
    aid, student = body["attempt_id"], world.personas["student"]
    l2 = await world.new_session(student, same_device=False, restriction_level=2)
    r = await client.post(
        f"{API}/attempts/{aid}/rebind", json={"confirm": True}, headers={**l2.headers, **idem()}
    )
    assert r.status_code == 400 and r.json()["otp_required"] is True
    r = await client.post(f"{API}/attempts/{aid}/rebind/otp", headers=l2.headers)
    assert r.status_code == 200 and r.json()["sent"] is True
    code = re.search(r"\b(\d{6})\b", mail.sent[-1].text).group(1)  # type: ignore[union-attr]
    r = await client.post(
        f"{API}/attempts/{aid}/rebind",
        json={"confirm": True, "otp_code": "000000" if code != "000000" else "111111"},
        headers={**l2.headers, **idem()},
    )
    assert r.status_code == 400 and r.json()["code"] == "otp_invalid"
    r = await client.post(
        f"{API}/attempts/{aid}/rebind",
        json={"confirm": True, "otp_code": code},
        headers={**l2.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    # a same-device re-login at L2 re-attaches without OTP and without consuming a rebind
    relogin = await world.new_session(l2, same_device=True)
    r = await client.get(f"{API}/attempts/{aid}/state", headers=relogin.headers)
    assert (
        r.status_code == 200
        and r.json()["reattached"] is True
        and r.json()["binding"]["rebinds_remaining"] == 1
    )


async def test_proctored_drive_needs_trainer_override(client, world: World, db) -> None:
    _, qs = await make_bank(db, world)
    test_id = await make_test(
        db, world, [("S", None, [fixed(qs[0])])], kind="drive", duration_seconds=600, org=world.org_a
    )
    await assign(db, world, test_id)
    student = world.personas["student"]
    body = (await start(client, student, test_id)).json()
    assert body["test"]["grace_seconds"] == 0 and body["binding"]["rebinds_remaining"] == 0
    other = await world.new_session(student, same_device=False)
    r = await client.post(
        f"{API}/attempts/{body['attempt_id']}/rebind",
        json={"confirm": True},
        headers={**other.headers, **idem()},
    )
    assert r.status_code == 403 and r.json()["trainer_override_required"] is True
    await client.post(
        f"{API}/attempts/{body['attempt_id']}/rebind-override",
        json={"reason": "power cut"},
        headers=world.personas["trainer_a"].headers,
    )
    r = await client.post(
        f"{API}/attempts/{body['attempt_id']}/rebind",
        json={"confirm": True},
        headers={**other.headers, **idem()},
    )
    assert r.status_code == 200


# --------------------------------------------------------------------------- studio scoping


async def test_trainer_scoping_and_cross_tenant_assignment(client, world: World, db) -> None:
    _, qs = await make_bank(db, world)
    ta, tb, coord = world.personas["trainer_a"], world.personas["trainer_b"], world.personas["admin"]
    base = {"title": "Batch quiz", "test_kind": "course_quiz", "duration_seconds": 600}
    # a batch trainer creates tests for their batch's org only
    r = await client.post(
        f"{API}/studio/tests", json={**base, "batch_id": str(world.batch_a)}, headers=ta.headers
    )
    assert r.status_code == 201, r.text
    t_a = r.json()
    assert (
        t_a["organization_id"] == str(world.org_a)
        and t_a["review_policy"]["after_submit"]["answer_key"] is True
    )
    r = await client.post(f"{API}/studio/tests", json=base, headers=ta.headers)  # platform scope
    assert r.status_code == 403
    r = await client.post(
        f"{API}/studio/tests", json={**base, "batch_id": str(world.batch_b)}, headers=ta.headers
    )
    assert r.status_code == 403  # a batch the trainer holds no grant on
    tid = t_a["id"]
    sections = {
        "sections": [{"title": "S", "rules": [{"rule_type": "fixed", "question_id": str(qs[0].question_id)}]}]
    }
    assert (
        await client.put(f"{API}/studio/tests/{tid}/sections", json=sections, headers=ta.headers)
    ).status_code == 200
    v = (await client.post(f"{API}/studio/tests/{tid}/validate", headers=ta.headers)).json()
    assert v["feasible"] is True and v["rules"][0]["pool_size"] == 1
    r = await client.post(f"{API}/studio/tests/{tid}/publish", headers=ta.headers)
    assert r.status_code == 200 and r.json()["status"] == "published"
    # other tenant's trainer cannot even see it
    assert (await client.get(f"{API}/studio/tests/{tid}", headers=tb.headers)).status_code == 404
    assert tid not in {
        t["id"] for t in (await client.get(f"{API}/studio/tests", headers=tb.headers)).json()["items"]
    }
    assert tid in {
        t["id"] for t in (await client.get(f"{API}/studio/tests", headers=ta.headers)).json()["items"]
    }

    now = utcnow()
    window = {
        "available_from": (now - timedelta(minutes=5)).isoformat(),
        "available_until": (now + timedelta(hours=1)).isoformat(),
    }
    r = await client.post(
        f"{API}/tests/{tid}/assignments", json={**window, "batch_id": str(world.batch_a)}, headers=ta.headers
    )
    assert r.status_code == 201, r.text
    # same org, but not the trainer's batch -> 403
    r = await client.post(
        f"{API}/tests/{tid}/assignments", json={**window, "batch_id": str(world.batch_a2)}, headers=ta.headers
    )
    assert r.status_code == 403
    # Admin holds test.assign at platform scope (D3)
    r = await client.post(
        f"{API}/tests/{tid}/assignments",
        json={**window, "batch_id": str(world.batch_a2)},
        headers=coord.headers,
    )
    assert r.status_code == 201
    # cross-tenant: legacy org B's trainer cannot assign college A's test to their batch
    r = await client.post(
        f"{API}/tests/{tid}/assignments", json={**window, "batch_id": str(world.batch_b)}, headers=tb.headers
    )
    assert r.status_code == 404
    # the whole-organization target is gone: a test is assigned to a batch
    r = await client.post(
        f"{API}/tests/{tid}/assignments",
        json={**window, "organization_id": str(world.org_a)},
        headers=coord.headers,
    )
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
    # a platform test assigned by legacy org B is fine for B, invisible for A's listing
    platform_test = await make_test(db, world, [("S", None, [fixed(qs[1])])], duration_seconds=600)
    r = await client.post(
        f"{API}/tests/{platform_test}/assignments",
        json={**window, "batch_id": str(world.batch_b)},
        headers=tb.headers,
    )
    assert r.status_code == 201
    lst = (await client.get(f"{API}/tests/{platform_test}/assignments", headers=ta.headers)).json()["items"]
    assert lst == []
    assert (await client.get(f"{API}/tests/{tid}/assignments", headers=coord.headers)).json()["items"]
    # students see their assigned tests, never other tenants'
    mine = (await client.get(f"{API}/me/tests", headers=world.personas["student"].headers)).json()["items"]
    assert {i["test_id"] for i in mine} == {tid}
    theirs = (await client.get(f"{API}/me/tests", headers=world.personas["student_b"].headers)).json()[
        "items"
    ]
    assert {i["test_id"] for i in theirs} == {str(platform_test)}
    d = await client.get(f"{API}/tests/{tid}", headers=world.personas["student"].headers)
    assert (
        d.status_code == 200
        and d.json()["eligibility"]["via"] == "assignment"
        and find_keys(d.json()) == set()
    )
    assert (
        await client.get(f"{API}/tests/{tid}", headers=world.personas["student_b"].headers)
    ).status_code == 404
    # students cannot author
    r = await client.post(f"{API}/studio/tests", json=base, headers=world.personas["student"].headers)
    assert r.status_code == 403


async def test_publish_refuses_infeasible_draws(client, world: World, db) -> None:
    t, _ = await make_bank(db, world)
    author = world.personas["author"]
    r = await client.post(
        f"{API}/studio/tests", json={"title": "Random", "test_kind": "mock"}, headers=author.headers
    )
    tid = r.json()["id"]
    rules: dict[str, Any] = {
        "sections": [{"title": "S", "rules": [{"rule_type": "random", "topic_id": str(t), "draw_count": 10}]}]
    }
    assert (
        await client.put(f"{API}/studio/tests/{tid}/sections", json=rules, headers=author.headers)
    ).status_code == 200
    v = (await client.post(f"{API}/studio/tests/{tid}/validate", headers=author.headers)).json()
    assert v["feasible"] is False and v["rules"][0]["pool_size"] == 4
    r = await client.post(f"{API}/studio/tests/{tid}/publish", headers=author.headers)
    assert r.status_code == 409
    rules["sections"][0]["rules"][0]["draw_count"] = 3
    await client.put(f"{API}/studio/tests/{tid}/sections", json=rules, headers=author.headers)
    assert (await client.post(f"{API}/studio/tests/{tid}/publish", headers=author.headers)).status_code == 200


async def test_random_draw_is_frozen_per_attempt(client, world: World, db, allow_access) -> None:
    t, qs = await make_bank(db, world)
    test_id = await make_test(
        db,
        world,
        [("S", None, [RuleIn(rule_type="random", topic_id=t, draw_count=3)])],
        duration_seconds=600,
    )
    student = world.personas["student"]
    body = (await start(client, student, test_id)).json()
    drawn = [q["question_version_id"] for q in body["sections"][0]["questions"]]
    assert len(drawn) == 3 == len(set(drawn)) and set(drawn) <= {str(q.qv_id) for q in qs}
    st = (await client.get(f"{API}/attempts/{body['attempt_id']}/state", headers=student.headers)).json()
    assert [q["question_version_id"] for q in st["sections"][0]["questions"]] == drawn
    assert ("test", test_id) in allow_access.calls  # purchased/entitled path (no assignment)
