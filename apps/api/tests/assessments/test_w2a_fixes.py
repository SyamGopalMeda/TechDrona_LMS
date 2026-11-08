"""Wave-2 fixes (agent w2a): ADM-49 owning batch on tests, coding items in draw rules
(webstaff request 10)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.core.db import system_context
from app.core.errors import ProblemError
from app.modules.assessments import studio
from app.modules.assessments.schemas import RuleIn, SectionIn, SectionsPut, TestCreate
from tests.assessments.test_attempts import API, assign, make_bank, make_test, start
from tests.coding.conftest import seed_problem
from tests.identity.factory import add_member
from tests.placement.world import World, idem, topic

# --------------------------------------------------------------------------- ADM-49


async def test_adm49_owning_batch_scopes_every_trainer_of_that_batch(client, world: World, db) -> None:
    trainer = world.personas["trainer_a"]
    co = await world.persona(
        "co_trainer_a", grants=(("trainer", "batch", world.batch_a),), org_ids=(world.org_a,), tier="staff"
    )
    await add_member(db, world.org_a, co.id, "staff", world.batch_a)
    other = await world.persona(
        "trainer_a2", grants=(("trainer", "batch", world.batch_a2),), org_ids=(world.org_a,), tier="staff"
    )
    await add_member(db, world.org_a, other.id, "staff", world.batch_a2)
    r = await client.post(
        f"{API}/studio/tests",
        json={"title": "Batch A weekly", "test_kind": "practice_set", "batch_id": str(world.batch_a)},
        headers={**trainer.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    assert r.json()["batch_id"] == str(world.batch_a)
    tid = r.json()["id"]
    await system_context(db, "test")
    stored = (await db.execute(text("SELECT batch_id FROM tests WHERE id = :t"), {"t": tid})).scalar()
    assert stored == world.batch_a
    # a co-trainer of the owning batch edits it (matrix test.edit trainer = B) ...
    p = await client.patch(f"{API}/studio/tests/{tid}", json={"title": "Renamed"}, headers=co.headers)
    assert p.status_code == 200, p.text
    listed = (await client.get(f"{API}/studio/tests", headers=co.headers)).json()["items"]
    assert tid in {t["id"] for t in listed}
    # ... a trainer of another batch of the same org does not
    assert (await client.get(f"{API}/studio/tests/{tid}", headers=other.headers)).status_code == 403
    p2 = await client.patch(f"{API}/studio/tests/{tid}", json={"title": "Hijack"}, headers=other.headers)
    assert p2.status_code == 403
    assert tid not in {
        t["id"] for t in (await client.get(f"{API}/studio/tests", headers=other.headers)).json()["items"]
    }


# --------------------------------------------------------------------------- coding sections


async def _coding_question(db, w: World, *, topic_path: str = "dsa/arrays") -> tuple[Any, Any, Any, Any]:
    from app.modules.placement import bank
    from app.modules.placement.schemas import QuestionCreate

    author, reviewer = w.personas["author"], w.personas["reviewer"]
    problem = await seed_problem(db, author.id, weights=[Decimal(1), Decimal(1)])
    tp = await topic(db, topic_path)
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
            default_marks=Decimal("10"),
            coding_problem_id=problem.id,
        ),
    )
    await bank.submit_review(db, q.id)
    await bank.review(db, reviewer.principal, q.id, "approve")
    await bank.publish(db, q.id)
    return problem, q, qv, tp


def test_rule_schema_accepts_coding() -> None:
    pid = uuid.uuid4()
    assert RuleIn(rule_type="fixed", coding_problem_id=pid).coding_problem_id == pid
    assert RuleIn(rule_type="random", topic_id=pid, question_types=["coding"]).question_types == ["coding"]
    with pytest.raises(ValidationError):
        RuleIn(rule_type="fixed", coding_problem_id=pid, question_id=pid)
    with pytest.raises(ValidationError):
        RuleIn(rule_type="random", topic_id=pid, coding_problem_id=pid)


async def test_fixed_rule_by_coding_problem_id_and_random_coding_draw(client, world: World, db) -> None:
    problem, q, qv, tp = await _coding_question(db, world)
    _otp, objective = await make_bank(db, world)
    test_id = await make_test(
        db,
        world,
        [
            ("Aptitude", None, [RuleIn(rule_type="fixed", question_id=objective[0].question_id)]),
            ("Coding", None, [RuleIn(rule_type="fixed", coding_problem_id=problem.id)]),
        ],
        duration_seconds=1800,
    )
    await system_context(db, "test")
    rules = (
        await db.execute(
            text(
                "SELECT r.question_id FROM test_section_rules r JOIN test_sections s ON s.id = r.test_section_id "
                "WHERE s.test_id = :t ORDER BY s.position"
            ),
            {"t": test_id},
        )
    ).scalars()
    assert list(rules)[1] == q.id  # resolved to the wrapping bank question
    await assign(db, world, test_id)
    r = await start(client, world.personas["student"], test_id)
    assert r.status_code == 201, r.text
    delivered = {x["question_version_id"] for s in r.json()["sections"] for x in s.get("questions", [])}
    assert str(qv.id) in delivered

    # a random coding section draws from the coding questions of the topic subtree
    await system_context(db, "test.factory")
    t = await studio.create_test(
        db, world.personas["author"].principal, TestCreate(title="Coding draw", test_kind="mock"), None
    )
    await studio.put_sections(
        db,
        t,
        SectionsPut(
            sections=[
                SectionIn(
                    title="Coding",
                    rules=[RuleIn(rule_type="random", topic_id=tp, question_types=["coding"], draw_count=1)],
                )
            ]
        ),
    )
    report = await studio.validate(db, t)
    assert report["feasible"] is True and report["rules"][0]["pool_size"] == 1
    # without "coding" the objective pool never contains coding questions
    t2 = await studio.create_test(
        db, world.personas["author"].principal, TestCreate(title="Objective draw", test_kind="mock"), None
    )
    await studio.put_sections(
        db,
        t2,
        SectionsPut(sections=[SectionIn(title="S", rules=[RuleIn(rule_type="random", topic_id=tp)])]),
    )
    assert (await studio.validate(db, t2))["rules"][0]["pool_size"] == 0


async def test_unknown_coding_problem_in_rule_is_422(world: World, db) -> None:
    await system_context(db, "test.factory")
    t = await studio.create_test(
        db, world.personas["author"].principal, TestCreate(title="Bad", test_kind="mock"), None
    )
    with pytest.raises(ProblemError) as e:
        await studio.put_sections(
            db,
            t,
            SectionsPut(
                sections=[
                    SectionIn(title="C", rules=[RuleIn(rule_type="fixed", coding_problem_id=uuid.uuid4())])
                ]
            ),
        )
    assert e.value.code == "validation_failed"
    assert e.value.ext["errors"][0]["field"] == "sections.0.rules.0.coding_problem_id"
