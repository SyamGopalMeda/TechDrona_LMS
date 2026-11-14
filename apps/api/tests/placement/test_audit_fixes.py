"""Regression tests for audit Phase-B fixes in placement (BE-14/15/27/28, ADM-41/46/48/54/55)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.access import AccessDecision, get_access_checker, register_access_checker
from app.core.ids import uuid7
from app.modules.placement.models import PracticeSession, Question, QuestionVersion
from tests.placement.test_placement import _practice_bank, mcq_body
from tests.placement.world import World, correct_response, idem, topic, wrong_response

API = "/api/v1"


class Toggle:
    def __init__(self) -> None:
        self.allow = True
        self.deny: set[uuid.UUID] = set()

    async def check(
        self, session: Any, principal: Any, resource_type: Any, resource_id: Any, *, is_free: bool = False
    ) -> AccessDecision:
        ok = self.allow and resource_id not in self.deny
        return AccessDecision(ok, "entitlement" if ok else "no_entitlement")


async def _start(client: Any, student: Any, body: dict[str, Any]) -> Any:
    return await client.post(f"{API}/practice/sessions", json=body, headers={**student.headers, **idem()})


# --------------------------------------------------------------------------- practice


async def test_answer_and_reveal_recheck_entitlement(client, world: World, db) -> None:
    """BE-14: keys are not served once the entitlement that admitted the set is gone."""
    prev = get_access_checker()
    tog = Toggle()
    register_access_checker(tog)
    try:
        t, qs = await _practice_bank(db, world, 2)
        st = world.personas["student"]
        r = await _start(client, st, {"topic_id": str(t)})
        assert r.status_code == 201, r.text
        s = r.json()
        by = {str(q.qv_id): q for q in qs}
        qv0 = s["items"][0]["question"]["question_version_id"]
        qv1 = s["items"][1]["question"]["question_version_id"]
        tog.allow = False
        r = await client.post(
            f"{API}/practice/sessions/{s['session_id']}/answers",
            json={"question_version_id": qv0, "response": wrong_response(by[qv0]), "time_spent_ms": 5},
            headers={**st.headers, **idem()},
        )
        assert r.status_code == 403 and r.json()["code"] == "entitlement_required"
        assert "correct_option_ids" not in r.json() and "explanation_html" not in r.json()
        r = await client.post(
            f"{API}/practice/sessions/{s['session_id']}/questions/{qv1}/reveal",
            json={"kind": "solution"},
            headers=st.headers,
        )
        assert r.status_code == 403 and r.json()["code"] == "entitlement_required"
        tog.allow = True
        r = await client.post(
            f"{API}/practice/sessions/{s['session_id']}/answers",
            json={"question_version_id": qv0, "response": wrong_response(by[qv0]), "time_spent_ms": 5},
            headers={**st.headers, **idem()},
        )
        assert r.status_code == 200, r.text
    finally:
        register_access_checker(prev)


async def test_reveal_then_answer_not_counted_correct(client, world: World, db, allow_access) -> None:
    """BE-28: an answer given after viewing the solution is not counted as correct."""
    t, qs = await _practice_bank(db, world, 2)
    st = world.personas["student"]
    s = (await _start(client, st, {"topic_id": str(t)})).json()
    by = {str(q.qv_id): q for q in qs}
    qv0 = s["items"][0]["question"]["question_version_id"]
    qv1 = s["items"][1]["question"]["question_version_id"]
    r = await client.post(
        f"{API}/practice/sessions/{s['session_id']}/questions/{qv0}/reveal",
        json={"kind": "solution"},
        headers=st.headers,
    )
    assert r.status_code == 200
    for qv in (qv0, qv1):
        r = await client.post(
            f"{API}/practice/sessions/{s['session_id']}/answers",
            json={"question_version_id": qv, "response": correct_response(by[qv]), "time_spent_ms": 1},
            headers={**st.headers, **idem()},
        )
        assert r.status_code == 200 and r.json()["is_correct"] is True
    st_ = (await client.get(f"{API}/practice/sessions/{s['session_id']}", headers=st.headers)).json()
    assert st_["answered_count"] == 2 and st_["correct_count"] == 1
    c = (await client.post(f"{API}/practice/sessions/{s['session_id']}/complete", headers=st.headers)).json()
    assert c["answered"] == 2 and c["correct"] == 1 and c["accuracy"] == 0.5 and c["solution_viewed"] == 1
    assert sum(x["correct"] for x in c["by_topic"]) == 1


async def test_duplicate_answer_returns_stored_feedback(client, world: World, db, allow_access) -> None:
    """BE-15: a second answer for the same question (different Idempotency-Key) replays the stored
    feedback and does not double-count; counters are SQL increments under a row lock."""
    t, qs = await _practice_bank(db, world, 1)
    st = world.personas["student"]
    s = (await _start(client, st, {"topic_id": str(t)})).json()
    qv = s["items"][0]["question"]["question_version_id"]
    body = {"question_version_id": qv, "response": correct_response(qs[0]), "time_spent_ms": 1}
    url = f"{API}/practice/sessions/{s['session_id']}/answers"
    r1 = await client.post(url, json=body, headers={**st.headers, **idem()})
    r2 = await client.post(url, json=body, headers={**st.headers, **idem()})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["answered_at"] == r2.json()["answered_at"]
    ps = (
        await db.execute(select(PracticeSession).where(PracticeSession.id == uuid.UUID(s["session_id"])))
    ).scalar_one()
    await db.refresh(ps)
    assert ps.answered_count == 1 and ps.correct_count == 1


# --------------------------------------------------------------------------- question bank SoD


async def _new_question(client: Any, who: Any, t: uuid.UUID, **kw: Any) -> str:
    r = await client.post(f"{API}/studio/questions", json=mcq_body(t, **kw), headers=who.headers)
    assert r.status_code == 201, r.text
    return str(r.json()["question_id"])


async def test_author_cannot_publish_own_question(client, world: World, db) -> None:
    """ADM-48: question.publish = P (!= author)."""
    author, reviewer = world.personas["author"], world.personas["reviewer"]
    t = await topic(db, "sod/publish")
    qid = await _new_question(client, author, t)
    assert (
        await client.post(f"{API}/studio/questions/{qid}/submit-review", headers=author.headers)
    ).status_code == 200
    r = await client.post(
        f"{API}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=reviewer.headers
    )
    assert r.status_code == 200
    r = await client.post(f"{API}/studio/questions/{qid}/publish", headers=author.headers)
    assert r.status_code == 403 and r.json()["code"] == "sod_violation"
    r = await client.post(f"{API}/studio/questions/{qid}/publish", headers=reviewer.headers)
    assert r.status_code == 200 and r.json()["status"] == "active"


async def test_editor_of_draft_cannot_review_it(client, world: World, db) -> None:
    """ADM-46: a reviewer who rewrites the author's draft cannot approve or publish it."""
    author, reviewer = world.personas["author"], world.personas["reviewer"]
    third = await world.persona(
        "reviewer_2", grants=(("content_manager", "platform", None),), is_platform=True, tier="staff"
    )
    t = await topic(db, "sod/edit")
    qid = await _new_question(client, author, t)
    body = {k: v for k, v in mcq_body(t).items() if k not in ("question_type", "primary_topic_id")}
    body["stem_html"] = "<p>Rewritten by the reviewer</p>"
    r = await client.post(f"{API}/studio/questions/{qid}/versions", json=body, headers=reviewer.headers)
    assert r.status_code == 200, r.text
    assert r.json()["versions"][0]["edited_by"] == [str(reviewer.id)]
    assert (
        await client.post(f"{API}/studio/questions/{qid}/submit-review", headers=reviewer.headers)
    ).status_code == 200
    r = await client.post(
        f"{API}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=reviewer.headers
    )
    assert r.status_code == 403 and r.json()["code"] == "sod_violation"
    r = await client.post(
        f"{API}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=author.headers
    )
    assert r.status_code == 403
    r = await client.post(
        f"{API}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=third.headers
    )
    assert r.status_code == 200
    r = await client.post(f"{API}/studio/questions/{qid}/publish", headers=reviewer.headers)
    assert r.status_code == 403
    assert (
        await client.post(f"{API}/studio/questions/{qid}/publish", headers=third.headers)
    ).status_code == 200


async def test_review_comment_and_retire_reason_persisted(client, world: World, db) -> None:
    """ADM-55: request-changes comment and retire reason are stored (and shown to the author)."""
    author, reviewer = world.personas["author"], world.personas["reviewer"]
    t = await topic(db, "sod/notes")
    qid = await _new_question(client, author, t)
    await client.post(f"{API}/studio/questions/{qid}/submit-review", headers=author.headers)
    r = await client.post(
        f"{API}/studio/questions/{qid}/review",
        json={"decision": "request_changes", "comment": "Option C is also correct"},
        headers=reviewer.headers,
    )
    assert r.status_code == 200
    d = (await client.get(f"{API}/studio/questions/{qid}", headers=author.headers)).json()
    assert d["versions"][0]["status"] == "draft"
    assert d["versions"][0]["review_comment"] == "Option C is also correct"
    await client.post(f"{API}/studio/questions/{qid}/submit-review", headers=author.headers)
    await client.post(
        f"{API}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=reviewer.headers
    )
    assert (
        await client.post(f"{API}/studio/questions/{qid}/publish", headers=reviewer.headers)
    ).status_code == 200
    r = await client.post(
        f"{API}/studio/questions/{qid}/retire", json={"reason": "Outdated syllabus"}, headers=reviewer.headers
    )
    assert r.status_code == 200, r.text
    q = (await db.execute(select(Question).where(Question.id == uuid.UUID(qid)))).scalar_one()
    await db.refresh(q)
    assert q.retired_reason == "Outdated syllabus"


async def test_org_private_question_sod_applies(client, world: World, db) -> None:
    """ADM-46: SoD is no longer skipped for org-private questions (checked at the service)."""
    from app.core.errors import ProblemError
    from app.modules.placement import bank

    author = world.personas["author"]
    t = await topic(db, "sod/org")
    qid = uuid.UUID(await _new_question(client, author, t))
    q = (await db.execute(select(Question).where(Question.id == qid))).scalar_one()
    q.organization_id = world.org_a
    qv = (await db.execute(select(QuestionVersion).where(QuestionVersion.question_id == qid))).scalar_one()
    qv.status = "in_review"
    await db.flush()
    try:
        await bank.review(db, author.principal, qid, "approve")
        raise AssertionError("self-review of an org-private question must be refused")
    except ProblemError as e:
        assert e.code == "sod_violation"


async def test_search_filters_on_latest_version_status(client, world: World, db) -> None:
    """ADM-54: PLC-04 can list the review queue (latest version awaiting review / approved)."""
    author, reviewer = world.personas["author"], world.personas["reviewer"]
    t = await topic(db, "sod/queue")
    q_draft = await _new_question(client, author, t)
    q_wait = await _new_question(client, author, t)
    q_ok = await _new_question(client, author, t)
    for q in (q_wait, q_ok):
        await client.post(f"{API}/studio/questions/{q}/submit-review", headers=author.headers)
    await client.post(
        f"{API}/studio/questions/{q_ok}/review", json={"decision": "approve"}, headers=reviewer.headers
    )

    async def ids(vs: str) -> set[str]:
        r = await client.get(
            f"{API}/studio/questions",
            params={"topic_id": str(t), "version_status": vs},
            headers=reviewer.headers,
        )
        assert r.status_code == 200, r.text
        return {i["question_id"] for i in r.json()["items"]}

    assert await ids("draft") == {q_draft}
    assert await ids("in_review") == {q_wait, q_ok}
    assert await ids("awaiting_review") == {q_wait}
    assert await ids("approved") == {q_ok}
    r = await client.get(
        f"{API}/studio/questions", params={"version_status": "bogus"}, headers=reviewer.headers
    )
    assert r.status_code == 400


async def test_batch_trainer_can_list_org_question_bank(client, world: World, db) -> None:
    """ADM-41: a batch-scoped trainer lists their organization's bank (not other orgs')."""
    tr = world.personas["trainer_a"]
    t = await topic(db, "sod/trainer")
    # Single company: without an organization_id a batch trainer authors into the company bank.
    r = await client.post(f"{API}/studio/questions", json=mcq_body(t), headers=tr.headers)
    assert r.status_code == 201, r.text
    assert r.json()["organization_id"] == str(world.org_a)
    mine = r.json()["question_id"]
    # an explicit company id is accepted; any other organization id is unknown
    r = await client.post(
        f"{API}/studio/questions", json=mcq_body(t, organization_id=str(world.org_a)), headers=tr.headers
    )
    assert r.status_code == 201, r.text
    other = await client.post(
        f"{API}/studio/questions",
        json=mcq_body(t, organization_id=str(uuid7())),
        headers=world.personas["trainer_b"].headers,
    )
    assert other.status_code == 404, other.text
    r = await client.get(f"{API}/studio/questions", headers=tr.headers)
    assert r.status_code == 200, r.text
    got = {i["question_id"] for i in r.json()["items"]}
    assert mine in got
    assert all(i["organization_id"] == str(world.org_a) for i in r.json()["items"])
    r = await client.get(f"{API}/studio/questions", headers=world.personas["student"].headers)
    assert r.status_code == 403
