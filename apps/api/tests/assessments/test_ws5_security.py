"""WS5 security regressions for assessments (docs/wiseman-reference/build/security-review.md):

* SEC-10: nobody grades, decides on or invalidates their own attempt (``conflict_of_interest``).
* SEC-13: connectivity events (focus_gained / disconnect / reconnect) have their own cap.
* Single company: the evaluator reads the studio test, its attempts and the evaluation screen of
  their batch without any authoring right.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

import pytest

from app.core.principal import RoleGrant
from app.core.time import utcnow
from app.modules.assessments import exam
from tests.assessments.test_attempts import sql, start
from tests.assessments.test_exam_protocol import autosave, ev, exam_test
from tests.assessments.test_integrity_and_report import flagged_attempt
from tests.placement.world import Persona, World, idem

API = "/api/v1"


def _as_own_evaluator(w: World, who: Persona) -> dict[str, str]:
    """The learner's own user id, now also holding an evaluator grant on their batch."""
    p = replace(
        who.principal,
        tier="staff",
        grants=(RoleGrant("evaluator", "batch", w.batch_a),),  # type: ignore[arg-type]
        last_step_up_at=utcnow(),
    )
    return w.auth.login(p)


async def test_sec10_no_self_grading_or_self_decision(client: Any, world: World, db: Any) -> None:
    _test_id, aid = await flagged_attempt(db, world, client)
    own = _as_own_evaluator(world, world.personas["student"])
    r = await client.post(
        f"{API}/attempts/{aid}/integrity-decision",
        json={"outcome": "no_action", "note": "looks fine"},
        headers={**own, **idem()},
    )
    assert r.status_code == 403 and r.json()["code"] == "conflict_of_interest", r.text
    r = await client.post(
        f"{API}/attempts/{aid}/invalidate", json={"reason": "impersonation"}, headers={**own, **idem()}
    )
    assert r.status_code in (403, 404), r.text
    qv = uuid.uuid4()  # the conflict check runs before the item lookup
    r = await client.post(
        f"{API}/attempts/{aid}/items/{qv}/grade", json={"marks": "1"}, headers={**own, **idem()}
    )
    assert r.status_code == 403 and r.json()["code"] == "conflict_of_interest", r.text
    # a different evaluator of the batch may decide
    r = await client.post(
        f"{API}/attempts/{aid}/integrity-decision",
        json={"outcome": "no_action", "note": "looks fine"},
        headers={**world.personas["evaluator_a"].headers, **idem()},
    )
    assert r.status_code == 201, r.text


async def test_sec13_connectivity_events_are_capped(
    client: Any, world: World, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(exam, "MAX_CONNECTIVITY_EVENTS_PER_ATTEMPT", 3)
    test_id, _ = await exam_test(db, world)
    student = world.personas["student"]
    aid = (await start(client, student, test_id, instructions_agreed=True)).json()["attempt_id"]
    r = await autosave(client, student, aid, [ev("disconnect", i) for i in range(1, 6)])
    assert r.status_code == 200 and r.json()["ignored_events"] == 2, r.text
    r = await autosave(client, student, aid, [ev("reconnect", i) for i in range(10, 13)])
    assert r.json()["ignored_events"] == 3
    n = await sql(
        db,
        "SELECT count(*) FROM attempt_events WHERE attempt_id = :a "
        "AND event_type IN ('focus_gained', 'disconnect', 'reconnect')",
        a=aid,
    )
    assert n[0][0] == 3
    # recordable integrity events keep their own budget
    r = await autosave(client, student, aid, [ev("focus_lost", 20)])
    assert r.json()["ignored_events"] == 0


async def test_evaluator_reads_studio_test_but_cannot_author(client: Any, world: World, db: Any) -> None:
    trainer, evaluator = world.personas["trainer_a"], world.personas["evaluator_a"]
    r = await client.post(
        f"{API}/studio/tests",
        json={"title": "Batch quiz", "test_kind": "course_quiz", "batch_id": str(world.batch_a)},
        headers=trainer.headers,
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = await client.get(f"{API}/studio/tests/{tid}", headers=evaluator.headers)
    assert r.status_code == 200, r.text
    r = await client.get(f"{API}/tests/{tid}/attempts", headers=evaluator.headers)
    assert r.status_code == 200, r.text
    r = await client.patch(f"{API}/studio/tests/{tid}", json={"title": "x"}, headers=evaluator.headers)
    assert r.status_code == 403
    r = await client.post(
        f"{API}/studio/tests",
        json={"title": "Nope", "test_kind": "course_quiz", "batch_id": str(world.batch_a)},
        headers=evaluator.headers,
    )
    assert r.status_code == 403
