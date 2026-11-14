"""Parity: paid test attempt and coding submission over HTTP on the Firebase stack.

VM expectations (``tests/assessments``, ``tests/coding``): question 201 -> review/publish 200,
test 201, sections 200, publish 200; a paid test without entitlement -> ATT-01 403
``entitlement_required``; with one -> 201, autosave 200, submit 200, result 200. Coding: problem
201, test cases 201, validate 200 ``passed``, publish 200; COD submit without entitlement 403,
with one 202 ``queued``; judged -> 200 ``completed``.
"""

from __future__ import annotations

from typing import Any

from tests.coding.conftest import fake_judge, testcase_key  # noqa: F401
from tests.coding.fs.support import seed_languages
from tests.parity.harness import World, grant


async def _question(w: World, author: dict[str, str], reviewer: dict[str, str], body: dict[str, Any]) -> str:
    r = await w.call("POST", "/studio/questions", author, expect=201, idem=True, json=body)
    qid = r.json()["question_id"]
    await w.call("POST", f"/studio/questions/{qid}/submit-review", author)
    await w.call("POST", f"/studio/questions/{qid}/review", reviewer, json={"decision": "approve"})
    await w.call("POST", f"/studio/questions/{qid}/publish", reviewer)
    return qid


async def test_paid_test_attempt_submit_result(web: World) -> None:
    w = web
    _, author = await w.staff("qauthor")
    _, reviewer = await w.staff("qreviewer")
    r = await w.call("POST", "/studio/topics", author, expect=201, json={"slug": "apt", "name": "Aptitude"})
    tid = r.json()["id"]
    mcq = await _question(
        w,
        author,
        reviewer,
        {
            "question_type": "mcq_single",
            "primary_topic_id": tid,
            "stem_html": "<p>2+2?</p>",
            "options": [{"html": "4", "is_correct": True}, {"html": "5"}],
            "explanation_html": "<p>x</p>",
            "difficulty": 2,
        },
    )
    r = await w.call(
        "POST",
        "/studio/tests",
        author,
        expect=201,
        idem=True,
        json={
            "title": "Paid mock",
            "test_kind": "mock",
            "duration_seconds": 1800,
            "attempts_allowed": 2,
            "is_free": False,
        },
    )
    test_id = r.json()["id"]
    await w.call(
        "PUT",
        f"/studio/tests/{test_id}/sections",
        author,
        json={
            "sections": [
                {"title": "A", "rules": [{"rule_type": "fixed", "question_id": mcq, "marks_each": "2"}]}
            ]
        },
    )
    await w.call("POST", f"/studio/tests/{test_id}/publish", author, idem=True)

    student, sh = await w.learner("tester")
    r = await w.call("POST", "/attempts", sh, expect=403, idem=True, json={"test_id": test_id})
    assert r.json()["code"] == "entitlement_required", r.text
    await grant(w, student.user_id, {"feature_key": "all_tests"})
    r = await w.call("POST", "/attempts", sh, expect=201, idem=True, json={"test_id": test_id})
    att = r.json()
    aid = att["attempt_id"]
    q = next(q for sec in att["sections"] for q in sec.get("questions", []))
    await w.call("GET", f"/attempts/{aid}/state", sh)
    await w.call(
        "POST",
        f"/attempts/{aid}/autosave",
        sh,
        json={
            "items": [
                {
                    "question_version_id": q["question_version_id"],
                    "response": {"option_ids": [q["options"][0]["option_id"]]},
                    "client_seq": 1,
                }
            ]
        },
    )
    await w.call("POST", f"/attempts/{aid}/submit", sh, idem=True, json={})
    await w.call("GET", f"/attempts/{aid}/result", sh)
    await w.call("GET", "/me/attempts", sh)
    await w.call("GET", f"/attempts/{aid}/evaluation", author)
    await w.relay()  # outbox consumers, as the Firebase worker runs them


async def test_paid_coding_problem_submit_and_judge(web: World, fake_judge: Any) -> None:  # noqa: F811
    from app.modules.coding import worker

    w = web
    await seed_languages()
    _, author = await w.staff("cauthor")
    _, reviewer = await w.staff("creviewer")
    r = await w.call(
        "POST",
        "/studio/coding/problems",
        author,
        expect=201,
        json={"slug": "sum-parity", "title": "Sum", "statement_md": "Print the sum.", "difficulty": 1},
    )
    pid = r.json()["problem_id"]
    await w.call(
        "POST",
        f"/studio/coding/problems/{pid}/test-cases",
        author,
        expect=201,
        json={"kind": "sample", "input": "3\n1 2 3\n", "expected_output": "6\n"},
    )
    await w.call(
        "POST",
        f"/studio/coding/problems/{pid}/test-cases",
        author,
        expect=201,
        json={"kind": "hidden", "input": "2\n5 5\n", "expected_output": "10\n"},
    )
    await w.call(
        "PUT",
        f"/studio/coding/problems/{pid}/reference-solutions/python3",
        author,
        json={"source_code": "# FAKE_VERDICT: AC\nprint(6)\n"},
    )
    r = await w.call("POST", f"/studio/coding/problems/{pid}/validate", author)
    assert r.json()["status"] == "passed", r.text
    await w.call("POST", f"/studio/coding/problems/{pid}/publish", reviewer)

    student, sh = await w.learner("coder")
    body = {"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\nprint(6)\n"}
    r = await w.call("POST", f"/coding/problems/{pid}/submit", sh, expect=403, idem=True, json=body)
    assert r.json()["code"] == "entitlement_required", r.text
    await grant(w, student.user_id, {"feature_key": "all_coding"})
    r = await w.call("GET", f"/coding/problems/{pid}", sh)
    r = await w.call("POST", f"/coding/problems/{pid}/submit", sh, expect=202, idem=True, json=body)
    sid = r.json()["submission_id"]
    await worker.process_pending(fake_judge)
    r = await w.call("GET", f"/coding/submissions/{sid}", sh)
    assert r.json()["status"] == "completed" and r.json()["verdict"] == "AC", r.text
    await w.call("GET", "/me/coding/submissions", sh)
    await w.relay()  # outbox consumers, as the Firebase worker runs them
