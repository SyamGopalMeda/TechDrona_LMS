"""Placement: taxonomy, question bank workflow, practice engine, recommendations, company paths."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import system_context
from app.modules.placement.richtext import sanitize_html
from tests.placement.world import (
    World,
    correct_response,
    find_keys,
    idem,
    question,
    topic,
    wrong_response,
)

API = "/api/v1"


def mcq_body(topic_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
    body = {
        "question_type": "mcq_single",
        "primary_topic_id": str(topic_id),
        "stem_html": "<p>A shop marks an article 25% above cost and gives 10% off. Profit?</p>",
        "options": [
            {"html": "10%"},
            {"html": "12.5%", "is_correct": True},
            {"html": "15%"},
            {"html": "20%"},
        ],
        "explanation_html": "<p>1.25 x 0.9 = 1.125, so 12.5%.</p>",
        "difficulty": 2,
    }
    body.update(kw)
    return body


# --------------------------------------------------------------------------- taxonomy


async def test_subjects_tree_is_public_with_published_counts(client, world: World, db) -> None:
    t = await topic(db, "quant/percentages")
    await question(db, world.personas["author"], world.personas["reviewer"], t)
    await question(db, world.personas["author"], world.personas["reviewer"], t, publish=False)
    r = await client.get(f"{API}/placement/subjects")
    assert r.status_code == 200, r.text
    quant = next(n for n in r.json()["items"] if n["path"] == "quant")
    assert quant["question_count"] == 1  # drafts are not counted
    assert quant["children"][0]["path"] == "quant/percentages"


async def test_topic_create_and_move_recomputes_paths(client, world: World, db) -> None:
    author = world.personas["author"]
    r = await client.post(
        f"{API}/studio/topics", json={"slug": "logical", "name": "Logical"}, headers=author.headers
    )
    assert r.status_code == 201, r.text
    logical = r.json()["id"]
    r = await client.post(
        f"{API}/studio/topics",
        json={"slug": "series", "name": "Series", "parent_id": logical},
        headers=author.headers,
    )
    series = r.json()["id"]
    r = await client.post(
        f"{API}/studio/topics",
        json={"slug": "number", "name": "Number", "parent_id": series},
        headers=author.headers,
    )
    assert r.json()["path"] == "logical/series/number" and r.json()["kind"] == "subtopic"
    r = await client.post(
        f"{API}/studio/topics", json={"slug": "reasoning", "name": "R"}, headers=author.headers
    )
    reasoning = r.json()["id"]
    r = await client.patch(
        f"{API}/studio/topics/{series}", json={"parent_id": reasoning}, headers=author.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["path"] == "reasoning/series"
    await system_context(db, "test")
    paths = {
        row[0]
        for row in (await db.execute(text("SELECT path FROM topics WHERE path LIKE 'reasoning/%'"))).all()
    }
    assert paths == {"reasoning/series", "reasoning/series/number"}
    # students cannot manage the taxonomy
    r = await client.post(
        f"{API}/studio/topics", json={"slug": "x", "name": "X"}, headers=world.personas["student"].headers
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------- question bank


async def test_question_review_workflow_and_key_visibility(client, world: World, db) -> None:
    t = await topic(db, "quant/profit-loss")
    author, reviewer, student = (
        world.personas["author"],
        world.personas["reviewer"],
        world.personas["student"],
    )
    r = await client.post(f"{API}/studio/questions", json=mcq_body(t), headers=author.headers)
    assert r.status_code == 201, r.text
    q = r.json()
    qid = q["question_id"]
    assert q["versions"][0]["status"] == "draft" and q["keys_visible"] is True

    # editing a draft keeps version 1
    r = await client.post(
        f"{API}/studio/questions/{qid}/versions",
        json={k: v for k, v in mcq_body(t).items() if k not in ("question_type", "primary_topic_id")},
        headers=author.headers,
    )
    assert r.status_code == 200 and len(r.json()["versions"]) == 1

    r = await client.post(f"{API}/studio/questions/{qid}/publish", headers=author.headers)
    assert r.status_code == 409  # not reviewed
    r = await client.post(f"{API}/studio/questions/{qid}/submit-review", headers=author.headers)
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{API}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=author.headers
    )
    assert r.status_code == 403 and r.json()["code"] == "sod_violation"  # reviewer != author
    r = await client.post(
        f"{API}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=reviewer.headers
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"{API}/studio/questions/{qid}/publish", headers=reviewer.headers)
    assert r.status_code == 200 and r.json()["status"] == "active"

    # published versions are immutable (DB trigger)
    await system_context(db, "test")
    qv = (
        await db.execute(text("SELECT current_version_id FROM questions WHERE id = :q"), {"q": qid})
    ).scalar_one()
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(text("UPDATE question_versions SET difficulty = 5 WHERE id = :v"), {"v": qv})
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(
                text(
                    "UPDATE question_options SET is_correct = NOT is_correct WHERE question_version_id = :v"
                ),
                {"v": qv},
            )

    # an edit after publish creates version 2 (draft); version 1 stays published
    body = {
        k: v for k, v in mcq_body(t, difficulty=3).items() if k not in ("question_type", "primary_topic_id")
    }
    r = await client.post(f"{API}/studio/questions/{qid}/versions", json=body, headers=author.headers)
    versions = {v["version_no"]: v["status"] for v in r.json()["versions"]}
    assert versions == {1: "published", 2: "draft"}

    # students cannot read the bank (and so never see keys)
    r = await client.get(f"{API}/studio/questions/{qid}", headers=student.headers)
    assert r.status_code == 403
    r = await client.get(f"{API}/studio/questions", headers=student.headers)
    assert r.status_code == 403
    r = await client.get(f"{API}/studio/questions", params={"topic_id": str(t)}, headers=reviewer.headers)
    assert r.status_code == 200 and r.json()["items"][0]["question_id"] == qid

    r = await client.post(f"{API}/studio/questions/{qid}/retire", headers=reviewer.headers)
    assert r.status_code == 200 and r.json()["status"] == "retired"


async def test_question_validation_and_sanitising(client, world: World, db) -> None:
    t = await topic(db, "quant/averages")
    author = world.personas["author"]
    bad = mcq_body(t, options=[{"html": "a", "is_correct": True}, {"html": "b", "is_correct": True}])
    r = await client.post(f"{API}/studio/questions", json=bad, headers=author.headers)
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
    r = await client.post(
        f"{API}/studio/questions",
        json=mcq_body(t, question_type="numeric", options=[], answer_key={"value": "abc"}),
        headers=author.headers,
    )
    assert r.status_code == 400
    r = await client.post(
        f"{API}/studio/questions",
        json=mcq_body(
            t, stem_html='<p onclick="x()">Hi<script>alert(1)</script><a href="javascript:x">l</a></p>'
        ),
        headers=author.headers,
    )
    assert r.status_code == 201
    stem = r.json()["versions"][0]["stem_html"]
    assert "script" not in stem and "onclick" not in stem and "javascript" not in stem and "Hi" in stem
    assert sanitize_html("<img src=x onerror=alert(1) data-s3-key='k'>") == '<img data-s3-key="k">'


async def test_submit_review_requires_explanation(client, world: World, db) -> None:
    t = await topic(db, "quant/ratios")
    author = world.personas["author"]
    r = await client.post(
        f"{API}/studio/questions", json=mcq_body(t, explanation_html=None), headers=author.headers
    )
    qid = r.json()["question_id"]
    r = await client.post(f"{API}/studio/questions/{qid}/submit-review", headers=author.headers)
    assert r.status_code == 400 and r.json()["errors"][0]["field"] == "explanation_html"


# --------------------------------------------------------------------------- practice


async def _practice_bank(db, world: World, n: int = 3) -> tuple[uuid.UUID, list[Any]]:
    t = await topic(db, "quant/percentages")
    qs = [
        await question(db, world.personas["author"], world.personas["reviewer"], t, qtype=qt)
        for qt in ("mcq_single", "mcq_multi", "numeric", "fill_blank")[:n]
    ]
    return t, qs


async def test_practice_requires_entitlement(client, world: World, db, no_access) -> None:
    t, _ = await _practice_bank(db, world)
    r = await client.post(
        f"{API}/practice/sessions",
        json={"topic_id": str(t)},
        headers={**world.personas["student"].headers, **idem()},
    )
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required"


async def test_practice_flow_feedback_only_after_answer(client, world: World, db, allow_access) -> None:
    t, qs = await _practice_bank(db, world, 4)
    student = world.personas["student"]
    r = await client.post(
        f"{API}/practice/sessions", json={"topic_id": str(t), "count": 10}, headers=student.headers
    )
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    r = await client.post(
        f"{API}/practice/sessions",
        json={"topic_id": str(t), "count": 10},
        headers={**student.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    st = r.json()
    sid = st["session_id"]
    assert len(st["items"]) == 4
    assert find_keys(st) == set(), "keys leaked before answering"
    by_qv = {q.qv_id: q for q in qs}

    first = uuid.UUID(st["items"][0]["question"]["question_version_id"])
    q = by_qv[first]
    key = idem()
    body = {"question_version_id": str(first), "response": wrong_response(q), "time_spent_ms": 1200}
    r = await client.post(
        f"{API}/practice/sessions/{sid}/answers", json=body, headers={**student.headers, **key}
    )
    assert r.status_code == 200, r.text
    fb = r.json()
    assert fb["is_correct"] is False and fb["explanation_html"] and fb["attempt_no"] == 1
    # replay with the same key -> same response, no second row
    r2 = await client.post(
        f"{API}/practice/sessions/{sid}/answers", json=body, headers={**student.headers, **key}
    )
    assert r2.json() == fb and r2.headers.get("Idempotency-Replayed") == "true"

    second = uuid.UUID(st["items"][1]["question"]["question_version_id"])
    r = await client.post(
        f"{API}/practice/sessions/{sid}/answers",
        json={
            "question_version_id": str(second),
            "response": correct_response(by_qv[second]),
            "time_spent_ms": 900,
        },
        headers={**student.headers, **idem()},
    )
    assert r.json()["is_correct"] is True

    # state: answered items carry feedback, unanswered ones still carry no keys
    st = (await client.get(f"{API}/practice/sessions/{sid}", headers=student.headers)).json()
    assert st["answered_count"] == 2 and st["correct_count"] == 1
    unanswered = [i for i in st["items"] if not i["answered"]]
    assert unanswered and all(find_keys(i) == set() for i in unanswered)

    # reveal is recorded and the later answer is flagged solution_viewed
    third = unanswered[0]["question"]["question_version_id"]
    r = await client.post(
        f"{API}/practice/sessions/{sid}/questions/{third}/reveal",
        json={"kind": "solution"},
        headers=student.headers,
    )
    assert r.status_code == 200 and r.json()["explanation_html"]
    r = await client.post(
        f"{API}/practice/sessions/{sid}/answers",
        json={
            "question_version_id": third,
            "response": correct_response(by_qv[uuid.UUID(third)]),
            "time_spent_ms": 10,
        },
        headers={**student.headers, **idem()},
    )
    assert r.json()["solution_viewed"] is True

    # other students cannot see this session
    r = await client.get(f"{API}/practice/sessions/{sid}", headers=world.personas["student_b"].headers)
    assert r.status_code == 404

    r = await client.post(f"{API}/practice/sessions/{sid}/complete", headers=student.headers)
    assert r.status_code == 200 and r.json()["status"] == "completed" and r.json()["answered"] == 3
    r = await client.get(f"{API}/me/practice/review", headers=student.headers)
    assert [i["question_version_id"] for i in r.json()["items"]] == [str(first)]

    await system_context(db, "test")
    events = (
        (
            await db.execute(
                text(
                    "SELECT payload FROM outbox_events WHERE event_type = 'practice.answered' AND aggregate_id = :s"
                ),
                {"s": sid},
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 3 and {e["is_correct"] for e in events} == {True, False}
    assert all("response" not in e for e in events)


async def test_restricted_principal_cannot_practise_but_can_read_mastery(
    client, world: World, db, allow_access
) -> None:
    t, _ = await _practice_bank(db, world, 1)
    restricted = await world.persona(
        "restricted", org_ids=(world.org_a,), scope="restricted", restriction_level=3
    )
    r = await client.post(
        f"{API}/practice/sessions", json={"topic_id": str(t)}, headers={**restricted.headers, **idem()}
    )
    assert r.status_code == 403 and r.json()["code"] == "account_restricted"
    r = await client.get(f"{API}/me/mastery", headers=restricted.headers)
    assert r.status_code == 200 and r.json()["method"] == "practice-ewma-v1"


async def _answer_all(client, student, t, qs, *, correct: bool, n_sets: int) -> None:
    by_qv = {q.qv_id: q for q in qs}
    for _ in range(n_sets):
        st = (
            await client.post(
                f"{API}/practice/sessions", json={"topic_id": str(t)}, headers={**student.headers, **idem()}
            )
        ).json()
        for item in st["items"]:
            qv = uuid.UUID(item["question"]["question_version_id"])
            resp = correct_response(by_qv[qv]) if correct else wrong_response(by_qv[qv])
            r = await client.post(
                f"{API}/practice/sessions/{st['session_id']}/answers",
                json={"question_version_id": str(qv), "response": resp, "time_spent_ms": 100},
                headers={**student.headers, **idem()},
            )
            assert r.status_code == 200, r.text
        await client.post(f"{API}/practice/sessions/{st['session_id']}/complete", headers=student.headers)


async def test_weak_topic_recommendation_needs_consent(client, world: World, db, allow_access) -> None:
    t, qs = await _practice_bank(db, world, 4)
    student = world.personas["student"]
    await _answer_all(client, student, t, qs, correct=False, n_sets=3)  # 12 wrong answers
    r = await client.get(f"{API}/me/recommendations", headers=student.headers)
    assert r.json() == {
        "items": [],
        "personalised": False,
        "note": "consent_required:analytics_personalisation",
    }

    from app.modules.identity.models import Consent

    await system_context(db, "test")
    db.add(
        Consent(
            id=uuid.uuid4(),
            user_id=student.id,
            purpose="analytics_personalisation",
            action="granted",
            notice_version="2026-11-01",
            channel="web",
        )
    )
    await db.flush()
    r = await client.get(f"{API}/me/recommendations", headers=student.headers)
    body = r.json()
    assert body["personalised"] is True and len(body["items"]) == 1
    rec = body["items"][0]
    assert rec["rule_key"] == "weak_topic" and rec["target_id"] == str(t) and "0%" in rec["why_recommended"]
    mastery = (await client.get(f"{API}/me/mastery", headers=student.headers)).json()
    assert mastery["topics"][0]["band"] == "beginner" and mastery["topics"][0]["answered"] == 12

    r = await client.post(f"{API}/me/recommendations/{rec['id']}/dismiss", headers=student.headers)
    assert r.status_code == 200
    assert (await client.get(f"{API}/me/recommendations", headers=student.headers)).json()["items"] == []
    r = await client.post(
        f"{API}/me/recommendations/{rec['id']}/dismiss", headers=world.personas["student_b"].headers
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------- companies


async def test_company_paths_and_student_readiness(client, world: World, db, allow_access) -> None:
    t, qs = await _practice_bank(db, world, 2)
    author, student = world.personas["author"], world.personas["student"]
    r = await client.post(
        f"{API}/studio/companies",
        json={"slug": "acme-tech", "name": "Acme Tech (demo)", "hub_status": "published"},
        headers=author.headers,
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    path_id = str(uuid.uuid4())
    body = {
        "company_id": cid,
        "role_name": "Graduate Engineer",
        "status": "published",
        "pattern": [
            {"section": "Quant", "topic_id": str(t), "weight": 1, "minutes": 30, "question_count": 20}
        ],
        "steps": [{"step_type": "practice_set", "title": "Percentages set", "topic_id": str(t)}],
    }
    r = await client.put(f"{API}/studio/company-paths/{path_id}", json=body, headers=author.headers)
    assert r.status_code == 200 and r.json()["version_no"] == 1
    r = await client.put(f"{API}/studio/company-paths/{path_id}", json=body, headers=author.headers)
    assert r.json()["version_no"] == 2 and len(r.json()["steps"]) == 1
    r = await client.put(f"{API}/studio/company-paths/{path_id}", json=body, headers=student.headers)
    assert r.status_code == 403
    assert (await client.get(f"{API}/studio/companies", headers=author.headers)).json()["items"][0]["paths"]

    await _answer_all(client, student, t, qs, correct=True, n_sets=1)
    r = await client.get(f"{API}/me/company-paths/acme-tech", headers=student.headers)
    assert r.status_code == 200, r.text
    assert r.json()["paths"][0]["readiness"]["score_pct"] == 100.0
    # practise a company path step
    step_id = r.json()["paths"][0]["steps"][0]["id"]
    r = await client.post(
        f"{API}/practice/sessions",
        json={"mode": "company_step", "company_path_step_id": step_id},
        headers={**student.headers, **idem()},
    )
    assert r.status_code == 201 and ("company_path", uuid.UUID(path_id)) in allow_access.calls


async def test_admin_reviews_a_content_managers_question(client, world: World, db) -> None:
    """QA 2026-11 (F10): Admin holds question.review and question.publish, so a lone content
    manager's question can be reviewed and published (reviewer != author and publisher != author
    both still hold); Admin still cannot author."""
    t = await topic(db, "quant/admin-review")
    author, admin = world.personas["author"], world.personas["admin"]
    qid = (await client.post(f"{API}/studio/questions", json=mcq_body(t), headers=author.headers)).json()[
        "question_id"
    ]
    assert (
        await client.post(f"{API}/studio/questions/{qid}/submit-review", headers=author.headers)
    ).status_code == 200
    # the Admin review queue lists it and the detail (with keys) opens for review
    q = await client.get(
        f"{API}/studio/questions", params={"version_status": "awaiting_review"}, headers=admin.headers
    )
    assert q.status_code == 200 and qid in {x["question_id"] for x in q.json()["items"]}
    d = await client.get(f"{API}/studio/questions/{qid}", headers=admin.headers)
    assert d.status_code == 200 and d.json()["keys_visible"] is True
    assert (await client.get(f"{API}/studio/questions", headers=admin.headers)).status_code == 403
    r = await client.post(
        f"{API}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=admin.headers
    )
    assert r.status_code == 200, r.text
    # the author may not publish their own question (ADM-48); the Admin can
    r = await client.post(f"{API}/studio/questions/{qid}/publish", headers=author.headers)
    assert r.status_code == 403 and r.json()["code"] == "sod_violation"
    r = await client.post(f"{API}/studio/questions/{qid}/publish", headers=admin.headers)
    assert r.status_code == 200 and r.json()["status"] == "active"
