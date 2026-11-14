"""Parity: placement practice (paid topic practice) over HTTP on the Firebase stack.

VM expectations (``tests/placement``): practice without entitlement 403 ``entitlement_required``;
with ``all_practice`` 201; answer 200 (idempotent replay identical); state 200; complete 200;
mastery / recommendations 200; question report 201 then resolve 200 (notifies the reporter).
"""

from __future__ import annotations

from tests.parity.harness import World, grant


async def _publish_mcq(
    w: World, author: dict[str, str], reviewer: dict[str, str], tid: str, stem: str
) -> None:
    r = await w.call(
        "POST",
        "/studio/questions",
        author,
        expect=201,
        idem=True,
        json={
            "question_type": "mcq_single",
            "primary_topic_id": tid,
            "stem_html": f"<p>{stem}</p>",
            "options": [{"html": "right", "is_correct": True}, {"html": "wrong"}],
            "explanation_html": "<p>because</p>",
            "difficulty": 2,
        },
    )
    qid = r.json()["question_id"]
    await w.call("POST", f"/studio/questions/{qid}/submit-review", author)
    await w.call("POST", f"/studio/questions/{qid}/review", reviewer, json={"decision": "approve"})
    await w.call("POST", f"/studio/questions/{qid}/publish", reviewer)


async def test_practice_session_report_resolve(web: World) -> None:
    w = web
    _, author = await w.staff("pauthor")
    _, reviewer = await w.staff("previewer")
    tid = (
        await w.call("POST", "/studio/topics", author, expect=201, json={"slug": "apt", "name": "Aptitude"})
    ).json()["id"]
    for i in range(3):
        await _publish_mcq(w, author, reviewer, tid, f"Q{i}")

    learner, hl = await w.learner("practiser")
    r = await w.call(
        "POST", "/practice/sessions", hl, expect=403, idem=True, json={"topic_id": tid, "count": 3}
    )
    assert r.json()["code"] == "entitlement_required", r.text
    await grant(w, learner.user_id, {"feature_key": "all_practice"})
    st = await w.call(
        "POST", "/practice/sessions", hl, expect=201, idem=True, json={"topic_id": tid, "count": 3}
    )
    sid = st.json()["session_id"]
    item = st.json()["items"][0]["question"]
    body = {
        "question_version_id": item["question_version_id"],
        "response": {"option_ids": [item["options"][0]["option_id"]]},
        "time_spent_ms": 1000,
    }
    key = {"Idempotency-Key": "parity-answer-1"}
    a1 = await w.call("POST", f"/practice/sessions/{sid}/answers", {**hl, **key}, json=body)
    replay = await w.call("POST", f"/practice/sessions/{sid}/answers", {**hl, **key}, json=body)
    assert replay.json() == a1.json()
    await w.call("GET", f"/practice/sessions/{sid}", hl)
    await w.call("POST", f"/practice/sessions/{sid}/complete", hl)
    # analytics mastery (the single writer, CP-11) exists for the topic -> /me/mastery uses it
    # (on the NO_POSTGRES session the lookup's begin_nested raised and the EWMA was used instead)
    import uuid

    from app.core.db import NO_POSTGRES
    from app.modules.analytics import mastery as am

    await am.apply_response(
        NO_POSTGRES,
        am.ScoredResponse(
            user_id=learner.user_id,
            topic_ids=(uuid.UUID(tid),),
            correct=True,
            difficulty="medium",
            source="practice",
        ),
    )
    r = await w.call("GET", "/me/mastery", hl)
    assert r.json()["method"] == "analytics-topic-mastery", r.text
    await w.call("GET", "/me/recommendations", hl)
    await w.call("GET", "/me/practice/review", hl)
    rep = await w.call(
        "POST",
        f"/questions/{item['question_version_id']}/reports",
        hl,
        expect=201,
        idem=True,
        json={"category": "typo", "message": "Typo in the stem"},
    )
    await w.call("GET", "/studio/question-reports", author)
    r = await w.call(
        "POST",
        f"/studio/question-reports/{rep.json()['report_id']}/resolve",
        author,
        idem=True,
        json={"resolution": "fixed", "note": "Thanks"},
    )
    assert r.json()["status"] == "resolved"
    r = await w.call("GET", "/me/notifications", hl)
    await w.relay()  # outbox consumers, as the Firebase worker runs them
