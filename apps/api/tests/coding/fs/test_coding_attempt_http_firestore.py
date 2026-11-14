"""A test attempt with a coding question, end to end over HTTP on Firestore with no Postgres:
coding problem authored and published -> coding question -> test published -> learner starts an
attempt -> problem opened and solved through the attempt (no standalone entitlement) -> judge
worker (fake judge) -> attempt submitted -> scored from the judged submission -> result and review.

Assessments routes get the SQL engine's ``MemoryTx`` request session; coding routes get
``NO_POSTGRES``; coding is reached from assessments with either (``repo_firestore.visibility``)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from tests.audit.fs.http_support import fs_http  # noqa: F401
from tests.audit.fs.support import fs_env  # noqa: F401
from tests.coding.fs.support import seed_languages
from tests.coding.fs.test_coding_http_firestore import _author_problem
from tests.coding.fs.test_coding_http_firestore import _staff as _coding_staff

FS_MODULES = (
    "assessments",
    "placement",
    "coding",
    "core",
    "audit",
    "identity",
    "sessions",
    "rbac",
    "notifications",
    "orgs",
    "entitlements",
    "ai",
    "analytics",
    "security",
    "learning",
    "paths",
    "admin",
)
P = "/api/v1"
ASSESS_PERMS = (
    "taxonomy.manage",
    "question.create",
    "question.edit",
    "question.review",
    "question.publish",
    "question.answer_key.read",
    "test.create",
    "test.edit",
    "test.assign",
    "test.results.read",
    "test.results.release",
)


@pytest.fixture(autouse=True)
def _no_postgres_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Jobs (``store_session``) see the Firebase runtime: no Postgres, so a ``MemoryTx``."""
    from app.core.firestore import sqlstore

    monkeypatch.setattr(sqlstore, "_postgres_available", lambda: False)


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def _staff(make_principal: Any, auth: Any) -> dict[str, str]:
    p, h = _coding_staff(make_principal, auth)
    for perm in ASSESS_PERMS:
        auth.grant(p, perm)
    return h


async def _published_question(
    client: Any, author: dict[str, str], reviewer: dict[str, str], body: Any
) -> str:
    r = await client.post(f"{P}/studio/questions", json=body, headers={**author, **_idem()})
    assert r.status_code == 201, r.text
    qid = r.json()["question_id"]
    assert (await client.post(f"{P}/studio/questions/{qid}/submit-review", headers=author)).status_code == 200
    rv = await client.post(
        f"{P}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=reviewer
    )
    assert rv.status_code == 200, rv.text
    pub = await client.post(f"{P}/studio/questions/{qid}/publish", headers=reviewer)
    assert pub.status_code == 200, pub.text
    return str(qid)


async def test_attempt_with_coding_question_end_to_end(
    fs_http: Any,  # noqa: F811
    make_principal: Any,
    fake_judge: Any,
    access: Any,
) -> None:
    from app.modules.coding import worker

    client, _rec, auth = fs_http
    await seed_languages()
    author, reviewer = _staff(make_principal, auth), _staff(make_principal, auth)
    pid = await _author_problem(client, author, reviewer, "attempt-sum")

    topic = await client.post(f"{P}/studio/topics", json={"slug": "dsa", "name": "DSA"}, headers=author)
    assert topic.status_code == 201, topic.text
    cq = await _published_question(
        client,
        author,
        reviewer,
        {
            "question_type": "coding",
            "primary_topic_id": topic.json()["id"],
            "stem_html": "<p>Sum the numbers.</p>",
            "explanation_html": "<p>Add them.</p>",
            "difficulty": 2,
            "coding_problem_id": pid,
        },
    )
    t = await client.post(
        f"{P}/studio/tests",
        json={"title": "Coding round", "test_kind": "mock", "duration_seconds": 1800, "attempts_allowed": 1},
        headers={**author, **_idem()},
    )
    assert t.status_code == 201, t.text
    test_id = t.json()["id"]
    secs = await client.put(
        f"{P}/studio/tests/{test_id}/sections",
        json={
            "sections": [
                {"title": "Code", "rules": [{"rule_type": "fixed", "question_id": cq, "marks_each": "9"}]}
            ]
        },
        headers=author,
    )
    assert secs.status_code == 200, secs.text
    pub = await client.post(f"{P}/studio/tests/{test_id}/publish", headers={**author, **_idem()})
    assert pub.status_code == 200, pub.text

    # learner without a standalone entitlement: access comes only through the attempt
    from app.core.access import AccessDecision

    async def _check(session: Any, principal: Any, rtype: Any, rid: Any, *, is_free: bool = False) -> Any:
        ok = rtype != "coding_problem" or is_free
        return AccessDecision(ok, "entitlement" if ok else "no_entitlement")

    access.check = _check
    learner = make_principal(is_minor=False)
    hl = auth.login(learner)
    assert (await client.get(f"{P}/coding/problems/{pid}", headers=hl)).status_code in (402, 403)
    st = await client.post(f"{P}/attempts", json={"test_id": test_id}, headers={**hl, **_idem()})
    assert st.status_code == 201, st.text
    aid = st.json()["attempt_id"]
    (q,) = [q for sec in st.json()["sections"] for q in sec.get("questions", [])]
    assert q["type"] == "coding"

    prob = await client.get(f"{P}/coding/problems/{pid}", params={"attempt_id": aid}, headers=hl)
    assert prob.status_code == 200, prob.text
    draft = await client.put(
        f"{P}/coding/problems/{pid}/drafts/python3",
        params={"attempt_id": aid},
        json={"source_code": "print(1)"},
        headers=hl,
    )
    assert draft.status_code == 200, draft.text
    sub = await client.post(
        f"{P}/coding/problems/{pid}/submit",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC,AC,WA", "attempt_id": aid},
        headers={**hl, **_idem()},
    )
    assert sub.status_code == 202, sub.text
    assert sub.json()["queue"] == "judge_assessment"
    sid = sub.json()["submission_id"]
    # someone else's attempt id does not open the problem
    other = auth.login(make_principal(is_minor=False))
    denied = await client.post(
        f"{P}/coding/problems/{pid}/submit",
        json={"language_key": "python3", "source_code": "x", "attempt_id": aid},
        headers={**other, **_idem()},
    )
    assert denied.status_code in (403, 404, 409), denied.text

    done = await worker.process_pending(fake_judge)
    assert done == {uuid.UUID(sid): "PARTIAL"}
    view = await client.get(f"{P}/coding/submissions/{sid}", headers=hl)
    assert view.status_code == 200 and view.json()["score"] == 2.0 and view.json()["max_score"] == 3.0

    save = await client.post(
        f"{P}/attempts/{aid}/autosave",
        json={
            "items": [
                {
                    "question_version_id": q["question_version_id"],
                    "response": {"submission_id": sid},
                    "client_seq": 1,
                }
            ]
        },
        headers=hl,
    )
    assert save.status_code == 200, save.text
    end = await client.post(f"{P}/attempts/{aid}/submit", json={}, headers={**hl, **_idem()})
    assert end.status_code == 200, end.text

    res = await client.get(f"{P}/attempts/{aid}/result", headers=hl)
    assert res.status_code == 200, res.text
    body = res.json()
    score = body.get("score", body.get("total_score"))
    assert score is not None and Decimal(str(score)) == Decimal("6"), body  # 9 x 2/3 of the cases
