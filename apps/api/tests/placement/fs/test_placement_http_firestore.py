"""Placement HTTP API through the FastAPI app on Firestore, with no Postgres (request session is
``db.NO_POSTGRES``): studio taxonomy and question workflow, companies and paths, practice,
recommendations, question banks and learner reports."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.identity import clock

FS_MODULES = (
    "placement",
    "assessments",
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
)
P = "/api/v1"

pytestmark = pytest.mark.usefixtures("allow_access")

STAFF_PERMS = (
    "taxonomy.manage",
    "question.create",
    "question.edit",
    "question.review",
    "question.publish",
    "question.retire",
    "question.answer_key.read",
    "company_path.manage",
)


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def _staff(make_principal: Any, auth: Any) -> dict[str, str]:
    p = make_principal(
        is_platform=True,
        roles=("content_manager",),
        tier="privileged",
        last_step_up_at=clock.now(),
        is_minor=False,
    )
    for perm in STAFF_PERMS:
        auth.grant(p, perm)
    return auth.login(p)


def _mcq(topic_id: str, stem: str) -> dict[str, Any]:
    return {
        "question_type": "mcq_single",
        "primary_topic_id": topic_id,
        "stem_html": f"<p>{stem}</p>",
        "options": [{"html": "right", "is_correct": True}, {"html": "wrong"}],
        "explanation_html": "<p>because</p>",
        "difficulty": 2,
    }


async def _publish(
    client: Any, author: dict[str, str], reviewer: dict[str, str], topic_id: str, stem: str
) -> str:
    r = await client.post(f"{P}/studio/questions", json=_mcq(topic_id, stem), headers={**author, **_idem()})
    assert r.status_code == 201, r.text
    qid = r.json()["question_id"]
    assert (await client.post(f"{P}/studio/questions/{qid}/submit-review", headers=author)).status_code == 200
    rv = await client.post(
        f"{P}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=reviewer
    )
    assert rv.status_code == 200, rv.text
    pub = await client.post(f"{P}/studio/questions/{qid}/publish", headers=reviewer)
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "active"
    return qid


async def test_studio_taxonomy_questions_companies(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    author, reviewer = _staff(make_principal, auth), _staff(make_principal, auth)

    subj = await client.post(f"{P}/studio/topics", json={"slug": "apt", "name": "Aptitude"}, headers=author)
    assert subj.status_code == 201, subj.text
    top = await client.post(
        f"{P}/studio/topics",
        json={"slug": "num", "name": "Numbers", "parent_id": subj.json()["id"]},
        headers=author,
    )
    assert top.status_code == 201 and top.json()["path"] == "apt/num"
    dup = await client.post(f"{P}/studio/topics", json={"slug": "apt", "name": "Again"}, headers=author)
    assert dup.status_code == 409

    qid = await _publish(client, author, reviewer, top.json()["id"], "2+2?")
    # SoD: the author cannot review their own question
    q2 = await client.post(f"{P}/studio/questions", json=_mcq(top.json()["id"], "3+3?"), headers=author)
    await client.post(f"{P}/studio/questions/{q2.json()['question_id']}/submit-review", headers=author)
    sod = await client.post(
        f"{P}/studio/questions/{q2.json()['question_id']}/review",
        json={"decision": "approve"},
        headers=author,
    )
    assert sod.status_code == 403 and sod.json()["code"] == "sod_violation"

    detail = await client.get(f"{P}/studio/questions/{qid}", headers=reviewer)
    assert detail.status_code == 200 and detail.json()["versions"][0]["status"] == "published"
    assert detail.json()["keys_visible"] is True
    found = await client.get(f"{P}/studio/questions", params={"q": "2+2"}, headers=author)
    assert found.status_code == 200 and [i["question_id"] for i in found.json()["items"]] == [qid]
    tree = await client.get(f"{P}/placement/subjects")
    assert tree.status_code == 200 and tree.json()["items"][0]["question_count"] == 1

    v2 = await client.post(
        f"{P}/studio/questions/{qid}/versions",
        json={
            k: v
            for k, v in _mcq(top.json()["id"], "2+2=?").items()
            if k not in ("question_type", "primary_topic_id")
        },
        headers=author,
    )
    assert v2.status_code == 200 and [v["version_no"] for v in v2.json()["versions"]] == [2, 1]

    co = await client.post(f"{P}/studio/companies", json={"slug": "acme", "name": "Acme"}, headers=author)
    assert co.status_code == 201, co.text
    companies = await client.get(f"{P}/studio/companies", headers=author)
    assert [c["slug"] for c in companies.json()["items"]] == ["acme"]

    retire = await client.post(f"{P}/studio/questions/{qid}/retire", json={"reason": "old"}, headers=reviewer)
    assert retire.status_code == 200 and retire.json()["status"] == "retired"


async def test_practice_and_reports_over_http(
    fs_http: Any, make_principal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _rec, auth = fs_http
    # notifications.assert_owner_or_platform reads the RLS scope from the Postgres session even on
    # the Firebase stack (request to data-money in data-assess.md); the system-scoped resolve
    # notification is allowed on Postgres, so stand that check down here.
    from app.modules.notifications import service as notif

    async def _ok(session: Any, user_id: Any) -> None:
        return None

    monkeypatch.setattr(notif, "assert_owner_or_platform", _ok)
    author, reviewer = _staff(make_principal, auth), _staff(make_principal, auth)
    subj = await client.post(f"{P}/studio/topics", json={"slug": "apt", "name": "Aptitude"}, headers=author)
    tid = subj.json()["id"]
    for i in range(3):
        await _publish(client, author, reviewer, tid, f"Q{i}")

    learner = make_principal(is_minor=False)
    hl = auth.login(learner)
    st = await client.post(
        f"{P}/practice/sessions", json={"topic_id": tid, "count": 3}, headers={**hl, **_idem()}
    )
    assert st.status_code == 201, st.text
    sid = st.json()["session_id"]
    item = st.json()["items"][0]["question"]
    body = {
        "question_version_id": item["question_version_id"],
        "response": {"option_ids": [item["options"][0]["option_id"]]},
        "time_spent_ms": 1000,
    }
    key = _idem()
    a1 = await client.post(f"{P}/practice/sessions/{sid}/answers", json=body, headers={**hl, **key})
    assert a1.status_code == 200, a1.text
    assert a1.json()["is_correct"] is True and a1.json()["correct_option_ids"]
    replay = await client.post(f"{P}/practice/sessions/{sid}/answers", json=body, headers={**hl, **key})
    assert replay.json() == a1.json()  # idempotent replay (Firestore idempotency record)
    other = auth.login(make_principal())
    assert (await client.get(f"{P}/practice/sessions/{sid}", headers=other)).status_code == 404
    state = await client.get(f"{P}/practice/sessions/{sid}", headers=hl)
    assert state.json()["answered_count"] == 1 and state.json()["correct_count"] == 1
    done = await client.post(f"{P}/practice/sessions/{sid}/complete", headers=hl)
    assert done.status_code == 200 and done.json()["answered"] == 1
    assert (await client.get(f"{P}/me/mastery", headers=hl)).status_code == 200
    recs = await client.get(f"{P}/me/recommendations", headers=hl)
    assert recs.status_code == 200, recs.text

    rep = await client.post(
        f"{P}/questions/{item['question_version_id']}/reports",
        json={"category": "typo", "message": "Typo in the stem"},
        headers={**hl, **_idem()},
    )
    assert rep.status_code == 201, rep.text
    again = await client.post(
        f"{P}/questions/{item['question_version_id']}/reports",
        json={"category": "typo", "message": "Again"},
        headers={**hl, **_idem()},
    )
    assert again.status_code == 409
    queue = await client.get(f"{P}/studio/question-reports", headers=author)
    assert queue.status_code == 200 and queue.json()["open_count"] == 1
    res = await client.post(
        f"{P}/studio/question-reports/{rep.json()['report_id']}/resolve",
        json={"resolution": "fixed", "note": "Thanks"},
        headers={**author, **_idem()},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "resolved"


async def test_question_banks_over_http(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    author, reviewer = _staff(make_principal, auth), _staff(make_principal, auth)
    subj = await client.post(f"{P}/studio/topics", json={"slug": "apt", "name": "Aptitude"}, headers=author)
    qid = await _publish(client, author, reviewer, subj.json()["id"], "Prime?")
    b = await client.post(f"{P}/studio/question-banks", json={"name": "Quant"}, headers={**author, **_idem()})
    assert b.status_code == 201, b.text
    bid = b.json()["id"]
    add = await client.post(
        f"{P}/studio/question-banks/{bid}/questions",
        json={"question_ids": [qid]},
        headers={**author, **_idem()},
    )
    assert add.status_code in (200, 201), add.text
    listed = await client.get(f"{P}/studio/question-banks", headers=author)
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["question_count"] == 1
    qs = await client.get(f"{P}/studio/question-banks/{bid}/questions", headers=author)
    assert qs.status_code == 200 and qs.json()["items"][0]["question_id"] == qid
