"""Structured assignments (WISEMAN-FEATURES "assign"): sections/items from the question bank +
inline prompts, marks validation, batch allocation windows, learner workspace (autosave, submit),
AI tutor limits, rule / AI-suggested grading, finalize with audited overrides, publish, results,
and "Request modification" (regrade) requests."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.core.outbox import relay_pending
from app.core.time import utcnow
from app.modules.ai import public as ai
from app.modules.learning import structured as st
from tests.placement.world import World, build_world, idem, question, topic

API = "/api/v1"


@pytest.fixture
def rbac(auth: Any) -> Iterator[Any]:
    from app.core import auth as core_auth
    from app.modules.rbac.service import RbacPermissionChecker

    prev = core_auth._permission_checker
    core_auth.register_permission_checker(RbacPermissionChecker())
    yield auth
    core_auth.register_permission_checker(prev)


@pytest.fixture
async def world(db: Any, rbac: Any, client: Any) -> World:
    return await build_world(db, rbac)


@pytest.fixture
def spy(monkeypatch: Any) -> list[str]:
    import app.modules.learning.structured_api as sa
    from app.core import audit as core_audit

    actions: list[str] = []
    real = core_audit.audit

    async def fake(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        actions.append(action)
        return await real(session, actor, action, *a, **kw)

    monkeypatch.setattr(sa, "audit", fake)
    return actions


@pytest.fixture
def fake_ai(monkeypatch: Any) -> dict[str, Any]:
    calls: dict[str, Any] = {"grade": 0, "tutor": 0, "enabled": True}

    async def enabled(session: Any, *, org_id: Any = None, app_key: Any = None) -> bool:
        assert app_key == "ai_grading"
        return bool(calls["enabled"])

    async def grade(session: Any, **kw: Any) -> ai.GradeSuggestion:
        calls["grade"] += 1
        return ai.GradeSuggestion(
            marks=Decimal("5"), max_marks=kw["max_marks"], feedback_md="Clear argument.", confidence=0.9
        )

    async def tutor(session: Any, **kw: Any) -> dict[str, Any]:
        calls["tutor"] += 1
        calls["tutor_kw"] = kw
        return {
            "reply_md": "Think about the base case.",
            "used": calls["tutor"],
            "limit": kw["per_learner_limit"],
        }

    monkeypatch.setattr(ai, "ai_enabled", enabled)
    monkeypatch.setattr(ai, "grade_response", grade)
    monkeypatch.setattr(ai, "tutor_reply", tutor)
    return calls


async def _assignment(client: Any, w: World, **kw: Any) -> str:
    tr = w.personas["trainer_a"]
    body = {
        "batch_id": str(w.batch_a),
        "title": "Lists",
        "submission_type": "structured",
        "max_score": 10,
        "ai_help_enabled": True,
        "ai_help_limit": 1,
        **kw,
    }
    r = await client.post(f"{API}/assignments", json=body, headers=tr.headers)
    assert r.status_code == 201, r.text
    assert r.json()["structured"] is True and r.json()["ai_help_limit"] == body["ai_help_limit"]
    return str(r.json()["id"])


async def _mcq(db: Any, w: World) -> Any:
    tid = await topic(db, "dsa/lists")
    return await question(db, w.personas["author"], w.personas["reviewer"], tid, qtype="mcq_single")


def _structure(mcq: Any, essay_marks: float) -> dict[str, Any]:
    return {
        "sections": [
            {
                "title": "Section 1",
                "items": [
                    {"source": "bank", "question_id": str(mcq.question_id), "marks": 4},
                    {
                        "source": "inline",
                        "item_type": "essay",
                        "prompt_md": "Explain list comprehensions.",
                        "marks": essay_marks,
                        "reference_answer_md": "A compact way to build lists.",
                    },
                ],
            }
        ]
    }


@pytest.mark.usefixtures("catalog_backend")
async def test_structured_assignment_end_to_end(client, world: World, db, spy, fake_ai) -> None:
    w = world
    tr, stu = w.personas["trainer_a"], w.personas["student"]
    aid = await _assignment(client, w)
    mcq = await _mcq(db, w)

    # structure: saved as a draft even when marks don't add up; allocation is refused then
    r = await client.put(f"{API}/assignments/{aid}/structure", json=_structure(mcq, 5), headers=tr.headers)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["marks"] == {**s["marks"], "allocated": 9.0, "total": 10.0, "ok": False}
    assert s["sections"][0]["items"][0]["item_type"] == "mcq_single"
    assert s["sections"][0]["items"][0]["key"]["correct_option_ids"] == [str(mcq.correct[0])]
    sec_id = s["sections"][0]["id"]
    now = utcnow()
    alloc = {
        "batch_id": str(w.batch_a),
        "visible_from": (now - timedelta(hours=1)).isoformat(),
        "visible_until": (now + timedelta(days=2)).isoformat(),
        "start_at": (now + timedelta(hours=1)).isoformat(),
        "due_at": (now + timedelta(days=1)).isoformat(),
        "section_engines": {sec_id: "pure_ai"},
        "evaluator_ids": [str(tr.id)],
    }
    r = await client.post(f"{API}/assignments/{aid}/allocations", json=alloc, headers=tr.headers)
    assert r.status_code == 422 and any(e["code"] == "marks_mismatch" for e in r.json()["errors"])
    r = await client.put(f"{API}/assignments/{aid}/structure", json=_structure(mcq, 6), headers=tr.headers)
    assert r.json()["marks"]["ok"] is True
    sec_id = r.json()["sections"][0]["id"]
    essay_id = r.json()["sections"][0]["items"][1]["id"]
    mcq_item = r.json()["sections"][0]["items"][0]["id"]
    alloc["section_engines"] = {sec_id: "pure_ai"}
    bad = {**alloc, "section_engines": {sec_id: "magic"}}
    assert (
        await client.post(f"{API}/assignments/{aid}/allocations", json=bad, headers=tr.headers)
    ).status_code == 400  # request schema errors are 400
    bad = {**alloc, "due_at": (now + timedelta(days=3)).isoformat()}  # after visible_until
    r = await client.post(f"{API}/assignments/{aid}/allocations", json=bad, headers=tr.headers)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "visible_until"
    r = await client.post(f"{API}/assignments/{aid}/allocations", json=alloc, headers=tr.headers)
    assert r.status_code == 201, r.text
    alloc_id = r.json()["id"]
    assert "assignment.allocate" in spy
    # a trainer of another company batch cannot see or allocate it (403: no grant here)
    tb = w.personas["trainer_b"]
    assert (await client.get(f"{API}/assignments/{aid}/structure", headers=tb.headers)).status_code == 403

    # learner: listed, but cannot start before "Can start at"
    mine = (await client.get(f"{API}/me/assignments", headers=stu.headers)).json()["data"]
    row = next(a for a in mine if a["id"] == aid)
    assert row["structured"] is True and row["schedule"]["can_start"] is False
    ws = (await client.get(f"{API}/me/assignments/{aid}/workspace", headers=stu.headers)).json()
    assert ws["submission"] is None and ws["sections"][0]["items"] == []
    r = await client.post(f"{API}/me/assignments/{aid}/workspace/start", headers=stu.headers)
    assert r.status_code == 409
    sb = w.personas["student_b"]
    assert (await client.get(f"{API}/me/assignments/{aid}/workspace", headers=sb.headers)).status_code == 404
    r = await client.patch(
        f"{API}/assignment-allocations/{alloc_id}",
        json={"start_at": (now - timedelta(minutes=5)).isoformat()},
        headers=tr.headers,
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"{API}/me/assignments/{aid}/workspace/start", headers=stu.headers)
    assert r.status_code == 200, r.text
    items = r.json()["sections"][0]["items"]
    assert [i["item_type"] for i in items] == ["mcq_single", "essay"]
    assert "key" not in items[0] and "reference_answer_md" not in items[1]
    assert r.json()["ai_help"] == {"enabled": True, "limit": 1, "used": 0, "remaining": 1}

    # autosave
    url = f"{API}/me/assignments/{aid}/workspace/items"
    r = await client.put(
        f"{url}/{mcq_item}", json={"response": {"option_ids": [str(uuid.uuid4())]}}, headers=stu.headers
    )
    assert r.status_code == 422
    r = await client.put(
        f"{url}/{mcq_item}", json={"response": {"option_ids": [str(mcq.correct[0])]}}, headers=stu.headers
    )
    assert r.status_code == 200 and r.json()["saved_at"], r.text
    r = await client.put(
        f"{url}/{essay_id}", json={"response": {"text": "They build lists."}}, headers=stu.headers
    )
    assert r.status_code == 200

    # AI tutor: limit 1 per learner, never the answer key
    tutor = {"item_id": essay_id, "mode": "guide", "learner_input": "help"}
    r = await client.post(f"{API}/me/assignments/{aid}/tutor", json=tutor, headers=stu.headers)
    assert r.status_code == 200 and r.json()["remaining"] == 0, r.text
    assert fake_ai["tutor_kw"]["context_type"] == "assignment"
    # SEC-17: history stays on the server (item-scoped); client history is never forwarded
    assert fake_ai["tutor_kw"]["item_id"] is not None and "history" not in fake_ai["tutor_kw"]
    assert "compact way" not in fake_ai["tutor_kw"]["question_md"]
    r = await client.post(f"{API}/me/assignments/{aid}/tutor", json=tutor, headers=stu.headers)
    assert r.status_code == 429 and r.json()["code"] == "ai_quota_exceeded"
    r = await client.patch(f"{API}/assignments/{aid}", json={"ai_help_enabled": False}, headers=tr.headers)
    assert r.status_code == 200 and r.json()["ai_help_enabled"] is False
    r = await client.post(f"{API}/me/assignments/{aid}/tutor", json=tutor, headers=stu.headers)
    assert r.status_code == 403 and r.json()["code"] == "ai_disabled"

    # submit (Idempotency-Key required); then the workspace and the structure are frozen
    r = await client.post(f"{API}/me/assignments/{aid}/workspace/submit", headers=stu.headers)
    assert r.status_code == 400
    r = await client.post(f"{API}/me/assignments/{aid}/workspace/submit", headers={**stu.headers, **idem()})
    assert r.status_code == 200 and r.json()["status"] == "submitted", r.text
    sub_id = r.json()["id"]
    r = await client.put(f"{url}/{essay_id}", json={"response": {"text": "late edit"}}, headers=stu.headers)
    assert r.status_code == 409
    r = await client.put(f"{API}/assignments/{aid}/structure", json=_structure(mcq, 6), headers=tr.headers)
    assert r.status_code == 409 and r.json()["code"] == "assignment_locked"
    r = await client.patch(f"{API}/assignments/{aid}", json={"max_score": 20}, headers=tr.headers)
    assert r.status_code == 409

    # evaluation: run AI grading (queued -> outbox -> pending suggestion), rule marks for MCQ
    ev = (await client.get(f"{API}/assignments/{aid}/evaluation", headers=tr.headers)).json()
    assert ev["submission_count"] == 1 and ev["rows"][0]["finalized"] is False
    r = await client.post(f"{API}/assignments/{aid}/ai-grading", json={}, headers=tr.headers)
    assert r.status_code == 202 and r.json()["queued_items"] == 1, r.text
    assert "assignment.ai_grading_run" in spy
    await relay_pending(db)
    assert fake_ai["grade"] == 1
    ev = (await client.get(f"{API}/assignments/{aid}/evaluation", headers=tr.headers)).json()
    assert ev["rows"][0]["ai_pending"] == 1 and ev["rows"][0]["ai_help_used"] == 1
    rv = (await client.get(f"{API}/assignment-submissions/{sub_id}/review", headers=tr.headers)).json()
    m_item, e_item = rv["sections"][0]["items"]
    assert m_item["auto_marks"] == 4.0 and m_item["suggested_marks"] == 4.0
    assert e_item["ai"]["status"] == "pending" and e_item["suggested_marks"] == 5.0
    assert e_item["final_marks"] is None
    # an AI suggestion is never visible to the learner before finalize + publish
    res = (await client.get(f"{API}/me/assignments/{aid}/result", headers=stu.headers)).json()
    assert res["published"] is False and res["submission"]["score"] is None
    assert all(i["final_marks"] is None for i in res["items"])

    # finalize: changing a suggestion needs a reason (audited)
    fin = {"items": [{"item_id": e_item["id"], "marks": 6}]}
    r = await client.post(f"{API}/assignment-submissions/{sub_id}/finalize", json=fin, headers=tr.headers)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "items.0.override_reason"
    fin["items"][0]["override_reason"] = "Covers every point"
    fin["items"][0]["feedback_md"] = "Excellent."
    r = await client.post(f"{API}/assignment-submissions/{sub_id}/finalize", json=fin, headers=tr.headers)
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["final"] == 10.0
    assert [i["source"] for i in r.json()["sections"][0]["items"]] == ["auto", "human"]
    assert {"assignment.item_override", "assignment.finalize"} <= set(spy)
    res = (await client.get(f"{API}/me/assignments/{aid}/result", headers=stu.headers)).json()
    assert res["published"] is False

    # publish (LRN-18) -> learner sees per-item marks + feedback
    r = await client.post(f"{API}/assignments/{aid}/release-grades", headers=tr.headers)
    assert r.status_code == 200 and r.json()["unfinalized_count"] == 0
    res = (await client.get(f"{API}/me/assignments/{aid}/result", headers=stu.headers)).json()
    assert res["published"] is True and res["submission"]["score"] == 10.0
    assert [i["final_marks"] for i in res["items"]] == [4.0, 6.0]
    assert res["items"][1]["feedback_md"] == "Excellent."

    # Request modification: one open request per submission; evaluator resolves and reopens
    rg = f"{API}/me/assignment-submissions/{sub_id}/regrade-requests"
    assert (await client.post(rg, json={"reason": "short"}, headers=stu.headers)).status_code == 400
    r = await client.post(
        rg, json={"reason": "Please recheck question 2", "item_id": essay_id}, headers=stu.headers
    )
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    r = await client.post(rg, json={"reason": "Please recheck question 1"}, headers=stu.headers)
    assert r.status_code == 409
    ev = (await client.get(f"{API}/assignments/{aid}/evaluation", headers=tr.headers)).json()
    assert "regrade_requested" in ev["rows"][0]["flags"]
    q = (await client.get(f"{API}/assignments/{aid}/regrade-requests?status=open", headers=tr.headers)).json()
    assert [x["id"] for x in q["data"]] == [req_id]
    mine_q = (
        await client.get(f"{API}/assignments/{aid}/regrade-requests?mine=true", headers=tr.headers)
    ).json()
    assert len(mine_q["data"]) == 1
    r = await client.post(
        f"{API}/assignment-regrade-requests/{req_id}/resolve",
        json={"action": "resolve", "note": "Re-opened for review", "reopen": True},
        headers=tr.headers,
    )
    assert r.status_code == 200 and r.json()["status"] == "resolved", r.text
    res = (await client.get(f"{API}/me/assignments/{aid}/result", headers=stu.headers)).json()
    assert res["published"] is False and res["regrade"]["status"] == "resolved"
    # learner cannot act on staff endpoints
    assert (await client.get(f"{API}/assignments/{aid}/evaluation", headers=stu.headers)).status_code in (
        403,
        404,
    )


@pytest.mark.usefixtures("catalog_backend")
async def test_pure_objective_and_manual_items_and_ai_disabled(client, world: World, db, fake_ai) -> None:
    w = world
    tr, stu = w.personas["trainer_a"], w.personas["student"]
    aid = await _assignment(client, w, ai_help_enabled=False, ai_help_limit=None)
    mcq = await _mcq(db, w)
    r = await client.put(f"{API}/assignments/{aid}/structure", json=_structure(mcq, 6), headers=tr.headers)
    sec_id = r.json()["sections"][0]["id"]
    now = utcnow()
    alloc = {
        "user_ids": [str(stu.id)],
        "due_at": (now + timedelta(days=1)).isoformat(),
        "section_engines": {sec_id: "pure_objective"},
    }
    r = await client.post(f"{API}/assignments/{aid}/allocations", json=alloc, headers=tr.headers)
    assert r.status_code == 201, r.text
    # a learner outside the list does not see it
    other = await w.persona("other", org_ids=(w.org_a,))
    from tests.identity.factory import add_member

    await add_member(db, w.org_a, other.id, "student", w.batch_a)
    assert (
        await client.get(f"{API}/me/assignments/{aid}/workspace", headers=other.headers)
    ).status_code == 404
    ws = (await client.post(f"{API}/me/assignments/{aid}/workspace/start", headers=stu.headers)).json()
    mcq_item, essay_id = (i["id"] for i in ws["sections"][0]["items"])
    tutor = {"item_id": essay_id, "mode": "explain"}
    r = await client.post(f"{API}/me/assignments/{aid}/tutor", json=tutor, headers=stu.headers)
    assert r.status_code == 403 and r.json()["code"] == "ai_disabled"
    url = f"{API}/me/assignments/{aid}/workspace/items"
    wrong = [str(x) for x in mcq.wrong[:1]]
    await client.put(f"{url}/{mcq_item}", json={"response": {"option_ids": wrong}}, headers=stu.headers)
    await client.put(f"{url}/{essay_id}", json={"response": {"text": "An essay"}}, headers=stu.headers)
    r = await client.post(f"{API}/me/assignments/{aid}/workspace/submit", headers={**stu.headers, **idem()})
    sub_id = r.json()["id"]
    # AI switched off for the org: pure_objective never asks AI, so grading still runs
    fake_ai["enabled"] = False
    r = await client.post(f"{API}/assignments/{aid}/ai-grading", json={}, headers=tr.headers)
    assert r.status_code == 202 and r.json()["queued_items"] == 0, r.text
    assert fake_ai["grade"] == 0
    rv = (await client.get(f"{API}/assignment-submissions/{sub_id}/review", headers=tr.headers)).json()
    m_item, e_item = rv["sections"][0]["items"]
    assert m_item["auto_marks"] == 0.0 and e_item["suggested_marks"] is None
    # written answers need a human mark
    r = await client.post(
        f"{API}/assignment-submissions/{sub_id}/finalize", json={"items": []}, headers=tr.headers
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "required"
    fin = {"items": [{"item_id": e_item["id"], "marks": 7}]}
    r = await client.post(f"{API}/assignment-submissions/{sub_id}/finalize", json=fin, headers=tr.headers)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "too_high"
    fin["items"][0]["marks"] = 3
    r = await client.post(f"{API}/assignment-submissions/{sub_id}/finalize", json=fin, headers=tr.headers)
    assert r.status_code == 200 and r.json()["totals"]["final"] == 3.0, r.text
    # extension for one learner (audited reason)
    alloc_id = (await client.get(f"{API}/assignments/{aid}/allocations", headers=tr.headers)).json()["data"][
        0
    ]["id"]
    r = await client.post(
        f"{API}/assignment-allocations/{alloc_id}/extensions",
        json={
            "user_id": str(stu.id),
            "until": (now + timedelta(days=3)).isoformat(),
            "reason": "Medical leave",
        },
        headers=tr.headers,
    )
    assert r.status_code == 200 and str(stu.id) in r.json()["extensions"]


@pytest.mark.usefixtures("catalog_backend")
async def test_ai_engine_blocked_when_org_ai_off(client, world: World, db, fake_ai) -> None:
    w = world
    tr, stu = w.personas["trainer_a"], w.personas["student"]
    aid = await _assignment(client, w)
    mcq = await _mcq(db, w)
    r = await client.put(f"{API}/assignments/{aid}/structure", json=_structure(mcq, 6), headers=tr.headers)
    sec_id = r.json()["sections"][0]["id"]
    alloc = {
        "batch_id": str(w.batch_a),
        "due_at": (utcnow() + timedelta(days=1)).isoformat(),
        "section_engines": {sec_id: "adaptive"},
    }
    assert (
        await client.post(f"{API}/assignments/{aid}/allocations", json=alloc, headers=tr.headers)
    ).status_code == 201
    await client.post(f"{API}/me/assignments/{aid}/workspace/start", headers=stu.headers)
    await client.post(f"{API}/me/assignments/{aid}/workspace/submit", headers={**stu.headers, **idem()})
    fake_ai["enabled"] = False
    r = await client.post(f"{API}/assignments/{aid}/ai-grading", json={}, headers=tr.headers)
    assert r.status_code == 403 and r.json()["code"] == "ai_disabled"


@pytest.mark.usefixtures("catalog_backend")
async def test_create_validation_and_legacy_submit_rejected(client, world: World) -> None:
    w = world
    tr = w.personas["trainer_a"]
    r = await client.post(
        f"{API}/assignments",
        json={"batch_id": str(w.batch_a), "title": "x", "submission_type": "text", "max_score": 5},
        headers=tr.headers,
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "instructions_md"
    r = await client.post(
        f"{API}/assignments",
        json={
            "batch_id": str(w.batch_a),
            "title": "x",
            "instructions_md": "y",
            "submission_type": "text",
            "max_score": 5,
            "ai_help_enabled": True,
        },
        headers=tr.headers,
    )
    assert r.status_code == 422
    # single company: organization_id is not an input any more
    r = await client.post(
        f"{API}/assignments",
        json={"organization_id": str(w.org_a), "title": "x", "submission_type": "structured", "max_score": 5},
        headers=tr.headers,
    )
    assert r.status_code == 400 and "organization_id" in r.text
    # a company-wide structured assignment needs platform scope; a batch trainer holds
    # assignment.manage only at batch scope
    r = await client.post(
        f"{API}/assignments",
        json={"title": "x", "submission_type": "structured", "max_score": 5},
        headers=tr.headers,
    )
    assert r.status_code == 403
    aid = await _assignment(client, w)
    r = await client.post(f"{API}/assignments/{aid}/clone", headers=tr.headers)
    assert r.status_code == 201 and r.json()["title"] == "Lists (copy)"


def test_judged_marks_scale_by_judge_score() -> None:
    from types import SimpleNamespace

    it = SimpleNamespace(marks=Decimal("10"))
    done = SimpleNamespace(status="completed", score=Decimal("3"), max_score=Decimal("4"))
    assert st.judged_marks(it, done) == Decimal("7.50")  # type: ignore[arg-type]
    assert st.judged_marks(it, SimpleNamespace(status="running", score=None, max_score=None)) is None  # type: ignore[arg-type]
    assert st.judged_marks(it, None) is None  # type: ignore[arg-type]


class _DenyAll:
    async def check(
        self, session: Any, principal: Any, resource_type: Any, resource_id: Any, *, is_free=False
    ):
        from app.core.access import AccessDecision

        return AccessDecision(False, "no_entitlement")


@pytest.mark.usefixtures("catalog_backend")
async def test_coding_problem_access_through_open_assignment(client, world: World, db) -> None:
    """Paid coding problems inside a structured assignment: allowed while the learner works on an
    allocated, started assignment containing it; denied without an allocation, before starting,
    to other learners, and after handing in."""
    from app.core import access
    from app.core.db import system_context
    from app.core.principal import Principal
    from app.modules.coding import service as coding
    from app.modules.coding.schemas import ProblemCreateIn
    from app.modules.learning.structured import coding_access_grant

    coding.register_access_grant(coding_access_grant)  # wired by app.wiring; idempotent
    prev = access.get_access_checker()
    access.register_access_checker(_DenyAll())
    try:
        w = world
        tr, stu, sb = w.personas["trainer_a"], w.personas["student"], w.personas["student_b"]
        await system_context(db, "test.factory")
        p = await coding.create_problem(
            db,
            Principal(user_id=w.personas["author"].id, session_id=uuid.uuid4()),
            ProblemCreateIn(
                slug=f"sum-{uuid.uuid4().hex[:8]}", title="Sum", statement_md="Print the sum.", difficulty=1
            ),
        )
        p.status = "published"
        await db.flush()
        prob = f"{API}/coding/problems/{p.id}"
        aid = await _assignment(client, w)
        body = {
            "sections": [
                {
                    "title": "Code",
                    "items": [
                        {
                            "source": "inline",
                            "item_type": "coding",
                            "prompt_md": "Sum the numbers.",
                            "coding_problem_id": str(p.id),
                            "marks": 10,
                        }
                    ],
                }
            ]
        }
        r = await client.put(f"{API}/assignments/{aid}/structure", json=body, headers=tr.headers)
        assert r.status_code == 200 and r.json()["marks"]["ok"] is True, r.text
        sec_id = r.json()["sections"][0]["id"]
        # no allocation -> the normal entitlement gate applies
        r = await client.get(prob, headers=stu.headers)
        assert r.status_code == 403 and r.json()["code"] == "entitlement_required"
        alloc = {
            "batch_id": str(w.batch_a),
            "due_at": (utcnow() + timedelta(days=1)).isoformat(),
            "section_engines": {sec_id: "pure_objective"},
        }
        assert (
            await client.post(f"{API}/assignments/{aid}/allocations", json=alloc, headers=tr.headers)
        ).status_code == 201
        # allocated but not started -> still denied
        assert (await client.get(prob, headers=stu.headers)).status_code == 403
        r = await client.post(f"{API}/me/assignments/{aid}/workspace/start", headers=stu.headers)
        assert r.status_code == 200, r.text
        assert r.json()["sections"][0]["items"][0]["coding_problem_id"] == str(p.id)
        # started -> allowed; a learner of another org is not
        r = await client.get(prob, headers=stu.headers)
        assert r.status_code == 200, r.text
        assert (await client.get(prob, headers=sb.headers)).status_code == 403
        # handed in -> the assignment no longer grants practice access
        r = await client.post(
            f"{API}/me/assignments/{aid}/workspace/submit", headers={**stu.headers, **idem()}
        )
        assert r.status_code == 200, r.text
        assert (await client.get(prob, headers=stu.headers)).status_code == 403
    finally:
        access.register_access_checker(prev)


@pytest.mark.usefixtures("catalog_backend")
async def test_bank_essay_settings_enforced_and_never_auto_scored(client, world: World, db) -> None:
    """A bank essay's ``settings.max_words`` limits the learner's answer; even under
    ``pure_objective`` an essay is never auto-scored (a human must mark it)."""
    from app.core.db import system_context
    from app.modules.placement import bank
    from app.modules.placement.schemas import QuestionCreate

    w = world
    tr, stu = w.personas["trainer_a"], w.personas["student"]
    author, reviewer = w.personas["author"], w.personas["reviewer"]
    await system_context(db, "test.factory")
    q, _qv = await bank.create_question(
        db,
        author.principal,
        QuestionCreate(
            question_type="essay",
            primary_topic_id=await topic(db, "dsa/essays"),
            stem_html="<p>Why are lists mutable?</p>",
            explanation_html="<p>They change in place.</p>",
            difficulty=2,
            settings={"max_words": 3},
        ),
    )
    await bank.submit_review(db, q.id)
    await bank.review(db, reviewer.principal, q.id, "approve")
    await bank.publish(db, q.id)
    aid = await _assignment(client, w, max_score=5, ai_help_enabled=False, ai_help_limit=None)
    body = {
        "sections": [{"title": "Essay", "items": [{"source": "bank", "question_id": str(q.id), "marks": 5}]}]
    }
    r = await client.put(f"{API}/assignments/{aid}/structure", json=body, headers=tr.headers)
    assert r.status_code == 200 and r.json()["marks"]["ok"] is True, r.text
    sec = r.json()["sections"][0]
    assert sec["items"][0]["item_type"] == "essay" and sec["items"][0]["settings"] == {"max_words": 3}
    alloc = {
        "batch_id": str(w.batch_a),
        "due_at": (utcnow() + timedelta(days=1)).isoformat(),
        "section_engines": {sec["id"]: "pure_objective"},
    }
    assert (
        await client.post(f"{API}/assignments/{aid}/allocations", json=alloc, headers=tr.headers)
    ).status_code == 201
    ws = (await client.post(f"{API}/me/assignments/{aid}/workspace/start", headers=stu.headers)).json()
    item = ws["sections"][0]["items"][0]
    assert item["settings"] == {"max_words": 3}
    url = f"{API}/me/assignments/{aid}/workspace/items/{item['id']}"
    r = await client.put(url, json={"response": {"text": "one two three four"}}, headers=stu.headers)
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert r.json()["errors"][0]["code"] == "too_many_words"
    r = await client.put(url, json={"response": {"text": "they change in place"[:13]}}, headers=stu.headers)
    assert r.status_code == 200, r.text
    r = await client.post(f"{API}/me/assignments/{aid}/workspace/submit", headers={**stu.headers, **idem()})
    sub_id = r.json()["id"]
    r = await client.post(f"{API}/assignments/{aid}/ai-grading", json={}, headers=tr.headers)
    assert r.status_code == 202 and r.json()["queued_items"] == 0
    rv = (await client.get(f"{API}/assignment-submissions/{sub_id}/review", headers=tr.headers)).json()
    e = rv["sections"][0]["items"][0]
    assert e["auto_marks"] is None and e["suggested_marks"] is None
    r = await client.post(
        f"{API}/assignment-submissions/{sub_id}/finalize", json={"items": []}, headers=tr.headers
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "required"
