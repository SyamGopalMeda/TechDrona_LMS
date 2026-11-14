"""engage over HTTP through the real FastAPI app on Firestore, **no Postgres** (data-learning
agent). The request session is the harness ``FirebaseSession`` (falsy like ``NO_POSTGRES``; any
SQL fails the test). Run with ``TD_TEST_NO_PG=1 TD_TEST_DB_NAME=learning_test``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from tests.learning.fs.harness import FirebaseSession, batch_with, client_for, close_app, login, open_app

API = "/api/v1/engage"
STORES = ("engage", "core", "ai", "identity", "orgs", "admin", "notifications", "rbac")
STUBBED = ("app.modules.engage.service", "app.modules.engage.service_fs")
PERM = "engage.activity.manage"


@pytest.fixture
async def web(
    fs_client: Any, monkeypatch: pytest.MonkeyPatch, auth: Any
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, list[tuple[str, Any]]]]:
    app, calls = await open_app(
        fs_client, monkeypatch, stores=STORES, stubbed=STUBBED, session_cls=FirebaseSession
    )
    try:
        async with client_for(app) as c:
            yield c, auth, calls
    finally:
        close_app(app, monkeypatch, STORES)


def _quiz(**kw: Any) -> dict[str, Any]:
    return {
        "activity_type": "quiz",
        "title": "Warm-up",
        "audience": "public",
        "questions": [
            {
                "kind": "single_choice",
                "prompt": "2 + 2?",
                "options": [{"text": "4", "is_correct": True}, {"text": "5"}],
            },
            {
                "kind": "single_choice",
                "prompt": "3 * 3?",
                "options": [{"text": "6"}, {"text": "9", "is_correct": True}],
            },
        ],
        **kw,
    }


async def test_quiz_launch_join_answer_reveal_finalise(web: Any, make_principal: Any) -> None:
    c, auth, calls = web
    _, mh = login(auth, make_principal, PERM, is_platform=True)
    _, ah = login(auth, make_principal)
    _, bh = login(auth, make_principal)

    r = await c.post(f"{API}/activities", json=_quiz(), headers=mh)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert r.json()["question_count"] == 2
    assert (await c.post(f"{API}/activities", json=_quiz(), headers=ah)).status_code == 403
    listed = (await c.get(f"{API}/activities", headers=mh)).json()
    assert [a["id"] for a in listed["data"]] == [aid] and listed["data"][0]["question_count"] == 2
    detail = (await c.get(f"{API}/activities/{aid}", headers=mh)).json()
    qs = detail["questions"]
    assert [q["position"] for q in qs] == [0, 1]

    r = await c.post(f"{API}/activities/{aid}/runs", json={}, headers=mh)
    assert r.status_code == 201, r.text
    run = r.json()
    code, rid = run["join_code"], run["id"]
    assert run["run_no"] == 1 and run["status"] == "scheduled"
    r = await c.post(f"{API}/runs/{rid}/control", json={"action": "start"}, headers=mh)
    assert r.status_code == 200 and r.json()["status"] == "open", r.text

    pre = await c.get(f"{API}/join/{code}", headers=ah)
    assert pre.status_code == 200 and pre.json()["eligible"] is True and pre.json()["joined"] is False, (
        pre.text
    )
    for h in (ah, bh):
        r = await c.post(f"{API}/join/{code}", headers=h)
        assert r.status_code == 200 and r.json()["joined"] is True, r.text
    assert (await c.post(f"{API}/join/{code}", headers=ah)).status_code == 200  # idempotent

    live = await c.get(f"{API}/runs/{rid}/live", headers=ah)
    assert live.status_code == 200, live.text
    lq = live.json()["questions"]
    assert all("correct" not in o for q in lq for o in q["options"])  # no answer key leak
    first, second = lq[0], lq[1]
    right = next(o["id"] for o in qs[0]["options"] if o["is_correct"])
    wrong = next(o["id"] for o in qs[0]["options"] if not o["is_correct"])
    r = await c.post(
        f"{API}/runs/{rid}/responses", json={"question_id": first["id"], "option_ids": [right]}, headers=ah
    )
    assert r.status_code == 201, r.text
    r = await c.post(
        f"{API}/runs/{rid}/responses", json={"question_id": first["id"], "option_ids": [wrong]}, headers=ah
    )
    assert r.status_code == 409 and r.json()["code"] == "already_answered", r.text
    r = await c.post(
        f"{API}/runs/{rid}/responses", json={"question_id": first["id"], "option_ids": [wrong]}, headers=bh
    )
    assert r.status_code == 201, r.text

    pres = await c.get(f"{API}/runs/{rid}/presenter", headers=mh)
    assert pres.status_code == 200, pres.text
    p = pres.json()
    assert (p["joined"], p["voted"], p["total_votes"]) == (2, 2, 2)
    counts = {o["id"]: o["count"] for o in p["questions"][0]["options"]}
    assert counts == {right: 1, wrong: 1}
    assert p["questions"][0]["winner"]["also_correct_count"] == 0
    assert (await c.get(f"{API}/runs/{rid}/presenter", headers=ah)).status_code == 403

    r = await c.post(f"{API}/runs/{rid}/control", json={"action": "reveal", "position": 0}, headers=mh)
    assert r.status_code == 200 and r.json()["revealed_positions"] == [0], r.text
    r = await c.post(
        f"{API}/runs/{rid}/responses", json={"question_id": first["id"], "option_ids": [right]}, headers=bh
    )
    assert r.status_code == 409  # answered already / closed after reveal
    r = await c.post(f"{API}/runs/{rid}/control", json={"action": "publish"}, headers=mh)
    assert r.status_code == 409 and r.json()["code"] == "invalid_state_transition"  # live run
    r = await c.post(f"{API}/runs/{rid}/control", json={"action": "finalise"}, headers=mh)
    assert r.status_code == 200 and r.json()["status"] == "finalised", r.text
    assert ("event", "engage.run_finalised") in calls

    mine = (await c.get(f"{API}/runs/{rid}/live", headers=ah)).json()
    assert mine["leaderboard"] and mine["my_rank"]["rank"] == 1, mine
    assert second["id"] in [q["id"] for q in mine["questions"]]
    runs = (await c.get(f"{API}/me/runs", headers=ah)).json()["data"]
    assert [x["run_id"] for x in runs] == [rid]

    # rerun: new code, run 2; duplicate + delete
    r2 = (await c.post(f"{API}/activities/{aid}/runs", json={}, headers=mh)).json()
    assert r2["run_no"] == 2 and r2["join_code"] != code
    dup = await c.post(f"{API}/activities/{aid}/duplicate", headers=mh)
    assert dup.status_code == 201 and dup.json()["title"].endswith("(copy)"), dup.text
    assert (await c.delete(f"{API}/activities/{aid}", headers=mh)).status_code == 204
    assert (await c.get(f"{API}/activities/{aid}", headers=mh)).status_code == 404
    assert [a["id"] for a in (await c.get(f"{API}/activities", headers=mh)).json()["data"]] == [
        dup.json()["id"]
    ]


async def test_members_only_batch_activity(web: Any, make_principal: Any) -> None:
    c, auth, _ = web
    trainer, th = login(auth, make_principal, PERM)
    member, mh = login(auth, make_principal)
    _, oh = login(auth, make_principal)
    batch = await batch_with([member.user_id], trainer.user_id)

    body = _quiz(audience="members", batch_id=str(batch), activity_type="poll", title="Poll")
    for q in body["questions"]:
        for o in q["options"]:
            o["is_correct"] = False
    r = await c.post(f"{API}/activities", json=body, headers=th)
    assert r.status_code == 201, r.text
    run = (await c.post(f"{API}/activities/{r.json()['id']}/runs", json={}, headers=th)).json()
    await c.post(f"{API}/runs/{run['id']}/control", json={"action": "start"}, headers=th)
    assert (await c.post(f"{API}/join/{run['join_code']}", headers=mh)).status_code == 200
    r = await c.post(f"{API}/join/{run['join_code']}", headers=oh)
    assert r.status_code == 403, r.text  # not a member of the batch
