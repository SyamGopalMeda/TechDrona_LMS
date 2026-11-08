"""Regression tests for the Phase B audit fixes in assessments (docs/audit/fixes/assess.md):
BE-03, BE-04, BE-09, BE-10, BE-21, BE-23, DB-03/BE-22, ADM-36, ADM-42 (see test_attempts.py),
ADM-44, ADM-49."""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.db import system_context
from app.core.errors import ProblemError
from app.modules.assessments import studio
from app.modules.assessments.schemas import RuleIn, SectionIn, SectionsPut, TestCreate
from app.modules.assessments.tasks import sweep_expired_attempts
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
from tests.coding.conftest import fake_judge, seed_problem  # noqa: F401
from tests.identity.factory import add_member
from tests.placement.world import Q, World, find_keys, idem, topic

# --------------------------------------------------------------------------- BE-03


async def _draft(db, w: World, sections: list[tuple[str, int | None, list[RuleIn]]]) -> Any:
    await system_context(db, "test.factory")
    t = await studio.create_test(
        db, w.personas["author"].principal, TestCreate(title="Draw", test_kind="mock"), None
    )
    await studio.put_sections(
        db,
        t,
        SectionsPut(
            sections=[SectionIn(title=n, duration_seconds=d, rules=rules) for n, d, rules in sections]
        ),
    )
    return t


async def test_be03_overlapping_rules_are_infeasible_at_publish(world: World, db) -> None:
    tp, qs = await make_bank(db, world)
    t = await _draft(
        db, world, [("S", None, [fixed(qs[0]), RuleIn(rule_type="random", topic_id=tp, draw_count=4)])]
    )
    report = await studio.validate(db, t)
    assert report["feasible"] is False
    rnd = report["rules"][1]
    assert rnd["ok"] is False and rnd["reason"] == "overlaps_other_rules" and rnd["available"] == 3
    with pytest.raises(ProblemError) as e:
        await studio.publish(db, t)
    assert e.value.code == "invalid_state_transition"


async def test_be03_overlap_across_sections_and_duplicate_fixed(world: World, db) -> None:
    tp, qs = await make_bank(db, world)
    rnd = RuleIn(rule_type="random", topic_id=tp, draw_count=3)
    t = await _draft(
        db, world, [("A", None, [rnd]), ("B", None, [RuleIn(rule_type="random", topic_id=tp, draw_count=2)])]
    )
    rep = await studio.validate(db, t)
    assert rep["feasible"] is False and rep["rules"][1]["reason"] == "overlaps_other_rules"
    t2 = await _draft(db, world, [("A", None, [fixed(qs[0])]), ("B", None, [fixed(qs[0])])])
    rep2 = await studio.validate(db, t2)
    assert rep2["feasible"] is False and {r["reason"] for r in rep2["rules"]} == {"duplicate_fixed_question"}


async def test_be03_feasible_mix_publishes_and_every_start_succeeds(client, world: World, db) -> None:
    """Random rule listed BEFORE a fixed rule over the same pool: the fixed question is reserved
    first, so no seed can make the start fail."""
    tp, qs = await make_bank(db, world)
    test_id = await make_test(
        db,
        world,
        [("S", None, [RuleIn(rule_type="random", topic_id=tp, draw_count=3), fixed(qs[0])])],
        duration_seconds=600,
    )
    await assign(db, world, test_id)
    r = await start(client, world.personas["student"], test_id)
    assert r.status_code == 201, r.text
    got = {q["question_version_id"] for s in r.json()["sections"] for q in s.get("questions", [])}
    assert got == {str(q.qv_id) for q in qs}


# --------------------------------------------------------------------------- BE-04


async def _close(db, assignment_id: uuid.UUID) -> None:
    await sql(
        db,
        "UPDATE test_assignments SET available_until = now() - interval '1 minute', "
        "available_from = now() - interval '3 hours' WHERE id = :a",
        a=assignment_id,
    )


async def test_be04_no_keys_while_another_batch_window_is_open(client, world: World, db) -> None:
    _, qs = await make_bank(db, world)
    test_id = await make_test(db, world, [("S", None, [fixed(q) for q in qs])], duration_seconds=1800)
    a1 = await assign(db, world, test_id)
    a2 = await assign(db, world, test_id, batch=world.batch_a2)
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
    await _close(db, a1)
    rev = (await client.get(f"{API}/attempts/{aid}/review", headers=student.headers)).json()
    assert rev["phase"] == "after_submit" and not find_keys(rev)
    res = (await client.get(f"{API}/attempts/{aid}/result", headers=student.headers)).json()
    assert res["phase"] == "after_submit"
    # once every window is closed (and nobody is still writing), the after_close policy applies
    await _close(db, a2)
    rev = (await client.get(f"{API}/attempts/{aid}/review", headers=student.headers)).json()
    assert rev["phase"] == "after_close" and find_keys(rev)


async def test_be04_window_extension_and_running_attempt_keep_keys_hidden(client, world: World, db) -> None:
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
    await _close(db, a1)
    rev = (await client.get(f"{API}/attempts/{aid}/review", headers=student.headers)).json()
    assert rev["phase"] == "after_submit" and not find_keys(rev)
    assert (await start(client, x, test_id)).status_code == 201  # x can still take it
    # Without the extension, x's running attempt alone still keeps the keys hidden.
    await sql(db, "UPDATE attempt_overrides SET window_extension_seconds = 0 WHERE test_id = :t", t=test_id)
    rev = (await client.get(f"{API}/attempts/{aid}/review", headers=student.headers)).json()
    assert rev["phase"] == "after_submit" and not find_keys(rev)


def test_be04_release_at_never_precedes_close() -> None:
    from datetime import timedelta

    from app.core.time import utcnow
    from app.modules.assessments.attempts import phase_of
    from app.modules.assessments.models import Test, TestAttempt

    now = utcnow()
    att = TestAttempt(status="graded")
    t = Test(review_policy={"release_at": (now - timedelta(hours=1)).isoformat()})
    assert (
        phase_of(att, t, None, now, test_close=now + timedelta(hours=1), close_known=True) == "after_submit"
    )
    assert (
        phase_of(att, t, None, now, test_close=now - timedelta(minutes=1), close_known=True) == "after_close"
    )
    assert phase_of(att, t, None, now, test_close=None, close_known=True) == "after_close"


# --------------------------------------------------------------------------- BE-10


async def _section_locked_attempt(client, world: World, db) -> tuple[str, Any]:
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
    aid = (await start(client, student, test_id)).json()["attempt_id"]
    await sql(
        db,
        "UPDATE attempt_sections SET deadline_at = now() - interval '10 minutes', "
        "started_at = now() - interval '11 minutes' WHERE attempt_id = :a AND status = 'active'",
        a=aid,
    )
    await sql(db, "UPDATE test_attempts SET started_at = now() - interval '11 minutes' WHERE id = :a", a=aid)
    return aid, student


async def test_be10_last_section_timeout_auto_submits(client, world: World, db) -> None:
    aid, student = await _section_locked_attempt(client, world, db)
    r = await client.get(f"{API}/attempts/{aid}/time", headers=student.headers)
    assert r.status_code == 200, r.text
    row = (
        await sql(
            db,
            "SELECT status, submit_reason, submitted_at < now() - interval '8 minutes' FROM test_attempts WHERE id = :a",
            a=aid,
        )
    )[0]
    assert row[0] in ("auto_submitted", "graded") and row[1] == "deadline" and row[2] is True
    secs = await sql(db, "SELECT status FROM attempt_sections WHERE attempt_id = :a ORDER BY position", a=aid)
    assert [s[0] for s in secs] == ["timed_out", "timed_out"]
    assert (await sql(db, "SELECT count(*) FROM attempt_results WHERE attempt_id = :a", a=aid))[0][0] == 1


async def test_be10_sweeper_closes_timed_out_section_locked_attempt(client, world: World, db) -> None:
    aid, _ = await _section_locked_attempt(client, world, db)
    assert await sweep_expired_attempts(db) >= 1
    row = (await sql(db, "SELECT status, submit_reason FROM test_attempts WHERE id = :a", a=aid))[0]
    assert row[0] in ("auto_submitted", "graded") and row[1] == "deadline"


# --------------------------------------------------------------------------- BE-21


async def test_be21_my_attempts_cursor_pagination(client, world: World, db) -> None:
    student = world.personas["student"]
    for _ in range(2):
        await standard(db, world, client)
    r = await client.get(f"{API}/me/attempts?limit=1", headers=student.headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1 and body["page"]["has_more"] is True and body["page"]["limit"] == 1
    r2 = await client.get(
        f"{API}/me/attempts?limit=1&cursor={body['page']['next_cursor']}", headers=student.headers
    )
    b2 = r2.json()
    assert len(b2["items"]) == 1 and b2["items"][0]["attempt_id"] != body["items"][0]["attempt_id"]
    assert b2["page"]["has_more"] is False
    assert (await client.get(f"{API}/me/attempts?limit=101", headers=student.headers)).status_code == 400
    bad = await client.get(f"{API}/me/attempts?cursor=nope", headers=student.headers)
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_cursor"


# --------------------------------------------------------------------------- BE-09


async def test_be09_attempt_time_rate_limited(client, world: World, db) -> None:
    from app.core.redis import get_cache_redis

    try:
        await get_cache_redis().ping()
    except Exception:
        pytest.skip("redis cache not reachable: the limiter fails open by design")
    _, _, body = await standard(db, world, client)
    student = world.personas["student"]
    codes = [
        (await client.get(f"{API}/attempts/{body['attempt_id']}/time", headers=student.headers)).status_code
        for _ in range(6)
    ]
    assert codes[:4] == [200] * 4 and 429 in codes[4:], codes
    r = await client.get(f"{API}/attempts/{body['attempt_id']}/time", headers=student.headers)
    assert r.json()["code"] == "rate_limited" and int(r.headers["Retry-After"]) >= 1


def test_be09_spec_limits_registered() -> None:
    from app.modules.assessments import ratelimit
    from app.modules.assessments import router as m

    assert {k: (r.limit, r.window_s) for k, r in ratelimit.LIMITS.items()} == {
        "att01_start": (10, 60),
        "att02_state": (30, 60),
        "att03_resume": (10, 60),
        "att05_rebind": (5, 3600),
        "att06_autosave": (30, 60),
        "att07_time": (4, 60),
        "att10_submit": (5, 60),
    }
    names = {
        getattr(d.dependency, "__name__", "")
        for rt in (m.dflt, m.neutral, m.l3r)
        for route in rt.routes
        if route.path.startswith("/attempts")  # type: ignore[attr-defined]
        for d in route.dependencies  # type: ignore[attr-defined]
    }
    assert {f"rate_limit_{k}" for k in ratelimit.LIMITS} <= names


# --------------------------------------------------------------------------- DB-03 / BE-22


@pytest.fixture
async def committed(committed_engine: AsyncEngine) -> Any:
    yield async_sessionmaker(committed_engine, expire_on_commit=False)


async def test_db03_concurrent_starts_get_409_not_500(client, committed, rbac) -> None:
    from tests.placement.world import build_world, question

    # These rows really commit (true concurrency needs separate connections), so they must not
    # land in the shared ``quant/percentages`` topic: published platform questions left there
    # leak into every later test's practice pool and subject counts. Use a private subject and
    # retire everything afterwards.
    subject = f"db03-{uuid.uuid4().hex[:10]}"
    async with committed() as s, s.begin():
        w = await build_world(s, rbac)
        tp = await topic(s, f"{subject}/race")
        qs = [
            await question(s, w.personas["author"], w.personas["reviewer"], tp, qtype=qt, stem=f"Q {qt}")
            for qt in ("mcq_single", "mcq_multi", "numeric", "fill_blank")
        ]
        test_id = await make_test(s, w, [("Quant", None, [fixed(q) for q in qs])], duration_seconds=1800)
        await assign(s, w, test_id)
    try:
        await _db03_race(client, committed, w, test_id)
    finally:
        async with committed() as s, s.begin():
            await system_context(s, "test.cleanup")
            await s.execute(
                text("UPDATE questions SET status = 'retired', deleted_at = now() WHERE id = ANY(:ids)"),
                {"ids": [q.question_id for q in qs]},
            )
            await s.execute(
                text("UPDATE topics SET is_active = false WHERE path LIKE :p"), {"p": f"{subject}%"}
            )
            await s.execute(text("UPDATE tests SET status = 'archived' WHERE id = :t"), {"t": test_id})


async def _db03_race(client: Any, committed: Any, w: World, test_id: uuid.UUID) -> None:
    st = w.personas["student"]

    async def go() -> Any:
        return await client.post(
            f"{API}/attempts",
            json={"test_id": str(test_id)},
            headers={**st.headers, "Idempotency-Key": uuid.uuid4().hex},
        )

    raw = await asyncio.gather(*[go() for _ in range(5)], return_exceptions=True)
    assert not [r for r in raw if isinstance(r, BaseException)], raw
    codes = Counter(r.status_code for r in raw)  # type: ignore[union-attr]
    assert codes[201] == 1 and codes[409] == 4, codes
    assert {r.json()["code"] for r in raw if r.status_code == 409} == {"active_attempt_exists"}  # type: ignore[union-attr]
    async with committed() as s, s.begin():
        await system_context(s, "test")
        n = (
            await s.execute(text("SELECT count(*) FROM test_attempts WHERE test_id = :t"), {"t": test_id})
        ).scalar()
    assert n == 1


# --------------------------------------------------------------------------- ADM-44 / ADM-49 / ADM-36


async def test_adm44_content_manager_cannot_list_learner_attempts(client, world: World, db) -> None:
    test_id, _, _ = await standard(db, world, client)
    r = await client.get(f"{API}/tests/{test_id}/attempts", headers=world.personas["author"].headers)
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"
    rows = (
        await client.get(f"{API}/tests/{test_id}/attempts", headers=world.personas["trainer_a"].headers)
    ).json()
    assert len(rows["items"]) == 1  # the batch trainer still sees their learners


async def test_adm49_batch_trainer_cannot_edit_other_batch_trainers_test(client, world: World, db) -> None:
    other = await world.persona(
        "trainer_a2", grants=(("trainer", "batch", world.batch_a2),), org_ids=(world.org_a,), tier="staff"
    )
    await add_member(db, world.org_a, other.id, "staff", world.batch_a2)
    trainer = world.personas["trainer_a"]
    r = await client.post(
        f"{API}/studio/tests",
        json={"title": "Batch A weekly", "test_kind": "practice_set", "batch_id": str(world.batch_a)},
        headers={**trainer.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert (await client.get(f"{API}/studio/tests/{tid}", headers=trainer.headers)).status_code == 200
    assert (await client.get(f"{API}/studio/tests/{tid}", headers=other.headers)).status_code == 403
    p = await client.patch(f"{API}/studio/tests/{tid}", json={"title": "Renamed"}, headers=other.headers)
    assert p.status_code == 403
    pub = await client.post(f"{API}/studio/tests/{tid}/publish", json={}, headers={**other.headers, **idem()})
    assert pub.status_code == 403
    listed = (await client.get(f"{API}/studio/tests", headers=other.headers)).json()["items"]
    assert tid not in {t["id"] for t in listed}
    assert tid in {
        t["id"] for t in (await client.get(f"{API}/studio/tests", headers=trainer.headers)).json()["items"]
    }
    # Admin (platform scope) manages every company test
    admin = world.personas["admin"]
    assert (await client.get(f"{API}/studio/tests/{tid}", headers=admin.headers)).status_code == 200


async def test_college_assignable_tests_route_is_gone(client, world: World) -> None:
    """COL-007's ``/studio/assignable-tests?organization_id`` was college-only (single company)."""
    r = await client.get(
        f"{API}/studio/assignable-tests?organization_id={world.org_a}",
        headers=world.personas["admin"].headers,
    )
    assert r.status_code in (404, 405)


# --------------------------------------------------------------------------- BE-23


async def test_be23_review_shows_own_coding_submission(client, db, world, allow_access, fake_judge) -> None:  # noqa: F811
    from app.modules.coding.worker import judge_submission
    from app.modules.placement import bank
    from app.modules.placement.schemas import QuestionCreate

    w = world
    author, reviewer, student = w.personas["author"], w.personas["reviewer"], w.personas["student"]
    problem = await seed_problem(db, author.id, weights=[Decimal(1), Decimal(1)])
    tp = await topic(db, "dsa/arrays")
    await system_context(db, "test.factory")
    q, qv = await bank.create_question(
        db,
        author.principal,
        QuestionCreate(
            question_type="coding",
            primary_topic_id=tp,
            stem_html="<p>Solve the linked problem.</p>",
            explanation_html="<p>Sum the numbers.</p>",
            difficulty=2,
            default_marks=Decimal("9"),
            coding_problem_id=problem.id,
        ),
    )
    await bank.submit_review(db, q.id)
    await bank.review(db, reviewer.principal, q.id, "approve")
    await bank.publish(db, q.id)
    test_id = await make_test(
        db, w, [("Coding", None, [fixed(Q(q.id, qv.id, [], [], "coding"))])], duration_seconds=1800
    )
    await assign(db, w, test_id)
    attempt_id = (await start(client, student, test_id)).json()["attempt_id"]
    src = "// FAKE_VERDICT: AC,AC,WA\nint main(){}\n"
    sub = await client.post(
        f"{API}/coding/problems/{problem.id}/submit",
        json={"language_key": "cpp17", "source_code": src, "attempt_id": attempt_id},
        headers={**student.headers, **idem()},
    )
    assert sub.status_code == 202, sub.text
    await system_context(db, "test")
    await judge_submission(db, uuid.UUID(sub.json()["submission_id"]), fake_judge, budget_s=1)
    done = await client.post(
        f"{API}/attempts/{attempt_id}/submit", json={}, headers={**student.headers, **idem()}
    )
    assert done.status_code == 200, done.text
    rev = await client.get(f"{API}/attempts/{attempt_id}/review", headers=student.headers)
    assert rev.status_code == 200, rev.text
    qd = rev.json()["sections"][0]["questions"][0]
    mine = qd["your_submission"]
    assert mine["source_code"] == src and mine["submission_id"] == sub.json()["submission_id"]
    if rev.json()["visible"]["correctness"]:
        assert [c["verdict"] for c in mine["cases"]] == ["AC", "AC", "WA"]
        hidden = [c for c in mine["cases"] if "expected_output" not in c]
        assert hidden and all(
            set(c) <= {"ordinal", "verdict", "time_ms", "memory_kb", "is_hidden"} for c in hidden
        )


# --------------------------------------------------------------------------- DB-01 erasure provider


async def test_db01_assessments_erasure_provider(client, world: World, db) -> None:
    from app.modules.admin.privacy import erasure_providers
    from app.modules.assessments import privacy

    assert erasure_providers()["assessments"] is privacy.erase_user
    _, qs, body = await standard(db, world, client)
    student = world.personas["student"]
    aid = body["attempt_id"]
    await sql(db, "UPDATE test_attempts SET start_ip = '203.0.113.9' WHERE id = :a", a=aid)
    r = await client.post(
        f"{API}/attempts/{aid}/submit",
        json={"final_items": [item(qs[0], 1)]},
        headers={**student.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    out = await privacy.erase_user(db, student.id)
    assert out["test_attempts_anonymised"] == 1 and out["attempt_responses_cleared"] >= 1
    row = (await sql(db, "SELECT start_ip, idempotency_key, status FROM test_attempts WHERE id = :a", a=aid))[
        0
    ]
    assert row[0] is None and row[1].startswith("erased:") and row[2] == "graded"
    left = await sql(
        db, "SELECT count(*) FROM attempt_responses WHERE attempt_id = :a AND response IS NOT NULL", a=aid
    )
    assert left[0][0] == 0
    assert (await sql(db, "SELECT count(*) FROM attempt_results WHERE attempt_id = :a", a=aid))[0][0] == 1
    again = await privacy.erase_user(db, student.id)  # idempotent
    assert again["test_attempts_anonymised"] == 0 and again["attempt_responses_cleared"] == 0
