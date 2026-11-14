"""``placement.public`` / ``assessments.public`` / ``coding.public`` on Firestore (no Postgres):
data seeded through the real backfill, then read through the store-neutral functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.core.ids import uuid7
from app.modules.assessments import models as am
from app.modules.coding import models as cm
from app.modules.placement import models as pm
from tests.placement.fs.backfill_helper import backfill_and_verify, fake_rows, sample_row
from tests.placement.fs.conftest import activate, deactivate


@pytest.fixture
async def all_fs(firestore_emulator: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    client = activate(monkeypatch, firestore_emulator, "placement", "assessments", "coding")
    try:
        yield client
    finally:
        await deactivate(monkeypatch, client, "placement", "assessments", "coding")


async def test_public_reads_on_firestore(
    all_fs: Any, fake_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.assessments import public as ap
    from app.modules.coding import public as cp
    from app.modules.placement import public as pp

    s = fake_session
    t0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    root = sample_row(
        pm.Topic, parent_id=None, path="apt", slug="apt", name="Aptitude", kind="subject", depth=0
    )
    mid = sample_row(
        pm.Topic, parent_id=root["id"], path="apt/num", slug="num", name="Numbers", kind="topic", depth=1
    )
    leaf = sample_row(
        pm.Topic, parent_id=mid["id"], path="apt/num/pr", slug="pr", name="Primes", kind="subtopic", depth=2
    )
    co = sample_row(pm.Company, slug="acme")
    test = sample_row(
        am.Test,
        organization_id=None,
        status="published",
        title="Aptitude Mock",
        pass_percentage=Decimal("40.00"),
    )
    q = sample_row(pm.Question, organization_id=None, primary_topic_id=leaf["id"])
    qv = sample_row(pm.QuestionVersion, question_id=q["id"], organization_id=None)
    u = uuid7()
    a1 = sample_row(
        am.TestAttempt,
        user_id=u,
        test_id=test["id"],
        organization_id=None,
        status="submitted",
        attempt_no=1,
        started_at=t0,
        submitted_at=t0 + timedelta(minutes=30),
        integrity_status="clean",
    )
    a2 = sample_row(
        am.TestAttempt,
        user_id=u,
        test_id=test["id"],
        organization_id=None,
        status="in_progress",
        attempt_no=2,
        idempotency_key=None,
    )
    r1 = sample_row(
        am.AttemptResult,
        attempt_id=a1["id"],
        user_id=u,
        test_id=test["id"],
        organization_id=None,
        percentage=Decimal("55.00"),
        passed=True,
        graded_at=t0,
    )
    prob = sample_row(
        cm.CodingProblem, organization_id=None, primary_topic_id=mid["id"], slug="two-sum", status="published"
    )
    sub = sample_row(
        cm.CodeSubmission,
        user_id=u,
        organization_id=None,
        coding_problem_id=prob["id"],
        mode="submit",
        status="completed",
        idempotency_key="submit:k1",
    )
    fake_rows(
        monkeypatch,
        {
            "topics": [root, mid, leaf],
            "companies": [co],
            "questions": [q],
            "question_versions": [qv],
            "tests": [test],
            "test_attempts": [a1, a2],
            "attempt_results": [r1],
            "test_attempt_heads": [
                {"test_id": test["id"], "user_id": u, "last_attempt_no": 2, "open_attempt_id": a2["id"]}
            ],
            "coding_problems": [prob],
            "code_submissions": [sub],
        },
    )
    for m in ("placement", "assessments", "coding"):
        assert all(r.ok for r in await backfill_and_verify(m, all_fs)), m

    # placement.public
    assert (await pp.get_question(s, q["id"])).id == q["id"]
    assert (await pp.get_version(s, qv["id"])).question_id == q["id"]
    assert await pp.topic_roots(s, [leaf["id"], mid["id"]]) == {leaf["id"]: root["id"], mid["id"]: root["id"]}
    assert await pp.topic_with_root(s, mid["id"]) == (mid["id"], root["id"])
    # assessments.public
    assert (await ap.attempt_lifetime(s, a1["id"]))[:3] == (u, t0, t0 + timedelta(minutes=30))
    assert await ap.attempt_org_of_user(s, a1["id"], uuid7()) is None
    assert (await ap.get_attempt(s, a2["id"])).status == "in_progress"
    assert await ap.has_attempt_in_progress(s, u) is True
    assert await ap.has_attempt_in_progress(s, uuid7()) is False
    assert await ap.count_attempts(s, u, [test["id"]]) == 2
    assert await ap.count_attempted_tests(s, u, [test["id"], uuid7()]) == 1
    assert await ap.best_result(s, u, test["id"]) == (a1["id"], 55.0)
    assert await ap.test_linkable(s, test["id"], uuid7()) is True
    assert [t[1] for t in await ap.search_tests(s, uuid7(), "mock")] == ["Aptitude Mock"]
    assert await ap.attempt_scored_facts(s, a1["id"]) == (u, test["id"], "clean", True, Decimal("40.00"))
    assert await ap.attempt_scored_facts(s, a2["id"]) is None  # no result yet (inner join)
    # coding.public
    assert await cp.problem_primary_topic(s, prob["id"]) == mid["id"]
    assert (await cp.published_problem(s, prob["id"])).slug == "two-sum"
    assert await cp.verify_submission_owner(s, sub["id"], u, prob["id"]) is True
    assert await cp.verify_submission_owner(s, sub["id"], uuid7()) is False
    j = await cp.get_attempt_judgement(s, sub["id"])
    assert j is not None and j.status == "completed"
