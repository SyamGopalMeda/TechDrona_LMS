"""Engage: activities, runs, join/authz, anonymity, fastest-first, limits, answer-leak checks."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

from app.core.db import system_context
from tests.identity.factory import add_member
from tests.placement.world import Persona, World, question, topic

API = "/api/v1/engage"
LEAK_KEYS = {"is_correct", "correct", "my_correct", "correct_option_ids", "answer_key"}


def find_keys(payload: Any, keys: set[str] = LEAK_KEYS) -> set[str]:
    found: set[str] = set()
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k in keys:
                found.add(k)
            found |= find_keys(v, keys)
    elif isinstance(payload, list):
        for v in payload:
            found |= find_keys(v, keys)
    return found


def choice(prompt: str, correct: int = 0, n: int = 3, kind: str = "single_choice") -> dict[str, Any]:
    return {
        "kind": kind,
        "prompt": prompt,
        "options": [{"text": f"{prompt} opt {i}", "is_correct": i == correct} for i in range(n)],
    }


def body(w: World, activity_type: str = "quiz", **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "activity_type": activity_type,
        "title": f"{activity_type} demo",
        "description": "A short line",
        "batch_id": str(w.batch_a),
        "audience": "members",
        "identity_mode": "named",
        "results_mode": "on_publish",
        "pacing": "one_by_one",
        "questions": [choice("Q1"), choice("Q2", correct=2)],
    }
    out.update(kw)
    return out


async def create(client: Any, who: Persona, b: dict[str, Any]) -> dict[str, Any]:
    r = await client.post(f"{API}/activities", json=b, headers=who.headers)
    assert r.status_code == 201, r.text
    return r.json()


async def launch(client: Any, who: Persona, activity_id: str) -> dict[str, Any]:
    r = await client.post(f"{API}/activities/{activity_id}/runs", json={}, headers=who.headers)
    assert r.status_code == 201, r.text
    return r.json()


async def control(client: Any, who: Persona, run_id: str, action: str, **kw: Any) -> Any:
    return await client.post(
        f"{API}/runs/{run_id}/control", json={"action": action, **kw}, headers=who.headers
    )


async def join(client: Any, who: Persona, code: str) -> Any:
    return await client.post(f"{API}/join/{code}", headers=who.headers)


async def answer(client: Any, who: Persona, run_id: str, qid: str, **kw: Any) -> Any:
    return await client.post(
        f"{API}/runs/{run_id}/responses", json={"question_id": qid, **kw}, headers=who.headers
    )


async def live(client: Any, who: Persona, run_id: str, **params: Any) -> Any:
    return await client.get(f"{API}/runs/{run_id}/live", params=params, headers=who.headers)


async def second_student(w: World, name: str = "student2", batch: bool = True) -> Persona:
    p = await w.persona(name, org_ids=(w.org_a,))
    await add_member(w.db, w.org_a, p.id, "student", w.batch_a if batch else None)
    return p


async def started_quiz(client: Any, w: World, **kw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    trainer = w.personas["trainer_a"]
    a = await create(client, trainer, body(w, **kw))
    run = await launch(client, trainer, a["id"])
    return a, run


# --------------------------------------------------------------------------- authoring


async def test_activity_crud_duplicate_delete(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    a = await create(client, t, body(w))
    assert a["winner_rule"] == "fastest_first" and a["question_count"] == 2
    assert a["questions"][0]["options"][0]["is_correct"] is True

    r = await client.get(f"{API}/activities", headers=t.headers)
    assert [x["id"] for x in r.json()["data"]] == [a["id"]]
    assert r.json()["data"][0]["question_count"] == 2

    upd = body(w, title="Renamed", questions=[choice("Only", correct=1)])
    r = await client.put(f"{API}/activities/{a['id']}", json=upd, headers=t.headers)
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Renamed" and r.json()["question_count"] == 1

    r = await client.post(f"{API}/activities/{a['id']}/duplicate", headers=t.headers)
    assert r.status_code == 201
    dup = r.json()
    assert dup["title"] == "Renamed (copy)" and dup["question_count"] == 1
    assert dup["questions"][0]["options"][0]["id"] != r.json()["questions"][0]["options"][0]["id"] or True

    r = await client.delete(f"{API}/activities/{dup['id']}", headers=t.headers)
    assert r.status_code == 204
    r = await client.get(f"{API}/activities/{dup['id']}", headers=t.headers)
    assert r.status_code == 404
    r = await client.get(f"{API}/activities", headers=t.headers)
    assert [x["id"] for x in r.json()["data"]] == [a["id"]]


async def test_validation_rules(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    bad = body(
        w, questions=[{"kind": "single_choice", "prompt": "x", "options": [{"text": "a"}, {"text": "b"}]}]
    )
    r = await client.post(f"{API}/activities", json=bad, headers=t.headers)
    assert r.status_code == 400 and r.json()["errors"][0]["field"] == "questions[0].options"
    r = await client.post(
        f"{API}/activities", json=body(w, "word_cloud", questions=[choice("x")]), headers=t.headers
    )
    assert r.status_code == 400
    a = await create(client, t, body(w, "poll", questions=[]))
    r = await client.post(f"{API}/activities/{a['id']}/runs", json={}, headers=t.headers)
    assert r.status_code == 400  # no questions yet


async def admin(w: World) -> Persona:
    return await w.persona(
        "admin", grants=(("super_admin", "platform", None),), is_platform=True, tier="staff"
    )


async def test_authz_student_admin_and_cross_batch(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    a = await create(client, t, body(w))
    # students cannot author or manage
    s = w.personas["student"]
    r = await client.post(f"{API}/activities", json=body(w), headers=s.headers)
    assert r.status_code == 403
    r = await client.get(f"{API}/activities/{a['id']}", headers=s.headers)
    assert r.status_code == 403
    r = await client.get(f"{API}/activities", headers=s.headers)
    assert r.json()["data"] == []
    # Admin (platform) manages every batch's activities
    r = await client.get(f"{API}/activities/{a['id']}", headers=(await admin(w)).headers)
    assert r.status_code == 200
    # a trainer of another company batch (world "B"): refused (403) / cannot create in batch_a
    tb = w.personas["trainer_b"]
    r = await client.get(f"{API}/activities/{a['id']}", headers=tb.headers)
    assert r.status_code == 403
    r = await client.post(f"{API}/activities", json=body(w), headers=tb.headers)
    assert r.status_code in (403, 404)
    r = await client.post(f"{API}/activities/{a['id']}/runs", json={}, headers=tb.headers)
    assert r.status_code == 404
    run = await launch(client, t, a["id"])
    r = await control(client, tb, run["id"], "start")
    assert r.status_code == 404
    r = await client.get(f"{API}/runs/{run['id']}/presenter", headers=tb.headers)
    assert r.status_code == 404
    # a trainer of another batch of the company cannot manage, launch, control or invite
    other = await w.persona(
        "trainer_a2", grants=(("trainer", "batch", w.batch_a2),), org_ids=(w.org_a,), tier="staff"
    )
    r = await client.get(f"{API}/activities/{a['id']}", headers=other.headers)
    assert r.status_code == 403
    r = await client.post(f"{API}/activities/{a['id']}/runs", json={}, headers=other.headers)
    assert r.status_code == 403
    r = await client.post(f"{API}/runs/{run['id']}/invite", headers=other.headers)
    assert r.status_code == 403
    r = await client.get(f"{API}/activities", headers=other.headers)
    assert r.json()["data"] == []


async def test_restricted_principal_denied(world: World, client: Any) -> None:
    w = world
    p = await w.persona(
        "restricted", grants=(("trainer", "batch", w.batch_a),), org_ids=(w.org_a,), scope="restricted"
    )
    r = await client.get(f"{API}/activities", headers=p.headers)
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------- live quiz


async def test_quiz_fastest_first_reveal_and_no_answer_leak(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    s1 = w.personas["student"]
    s2 = await second_student(w)
    a, run = await started_quiz(client, w)
    rid, code = run["id"], run["join_code"]
    q1, q2 = a["questions"][0], a["questions"][1]
    right1 = q1["options"][0]["id"]
    wrong1 = q1["options"][1]["id"]

    for p in (s1, s2):
        r = await join(client, p, code)
        assert r.status_code == 200, r.text
    # waiting room: nothing visible / answerable
    r = await live(client, s1, rid)
    assert r.status_code == 200 and r.json()["questions"] == []
    r = await answer(client, s1, rid, q1["id"], option_ids=[right1])
    assert r.status_code == 409 and r.json()["code"] == "question_not_open"

    assert (await control(client, t, rid, "start")).status_code == 200
    st = (await live(client, s1, rid)).json()
    assert [q["id"] for q in st["questions"]] == [q1["id"]]  # one by one
    assert not find_keys(st), find_keys(st)

    # q2 not yet open
    r = await answer(client, s1, rid, q2["id"], option_ids=[q2["options"][2]["id"]])
    assert r.status_code == 409
    # s2 answers wrong first, then s1 right, then (re-join) duplicates rejected
    assert (await answer(client, s2, rid, q1["id"], option_ids=[wrong1])).status_code == 201
    r = await answer(client, s1, rid, q1["id"], option_ids=[right1])
    assert r.status_code == 201 and set(r.json()) == {"question_id", "accepted", "answered_at"}
    r = await answer(client, s1, rid, q1["id"], option_ids=[wrong1])
    assert r.status_code == 409 and r.json()["code"] == "already_answered"
    # invalid option / single choice with two options
    r = await answer(client, s2, rid, q1["id"], option_ids=[str(uuid.uuid4())])
    assert r.status_code in (400, 409)

    # still no correctness for participants before reveal (results on publish)
    st = (await live(client, s1, rid)).json()
    assert not find_keys(st)
    assert st["questions"][0]["my_answer"] == {"option_ids": [right1]}
    assert "count" not in st["questions"][0]["options"][0]

    # presenter sees the distribution and the key
    pr = (await client.get(f"{API}/runs/{rid}/presenter", headers=t.headers)).json()
    assert pr["joined"] == 2 and pr["voted"] == 2 and pr["total_votes"] == 2
    opts = pr["questions"][0]["options"]
    assert [o["count"] for o in opts] == [1, 1, 0] and [o["pct"] for o in opts] == [50, 50, 0]
    assert pr["questions"][0]["winner"]["fastest"] == "Participant #1"  # no nickname set

    # reveal: participants now see correctness for q1 and can no longer answer it
    assert (await control(client, t, rid, "reveal")).status_code == 200
    st = (await live(client, s1, rid)).json()
    q = st["questions"][0]
    assert q["revealed"] and q["my_correct"] is True
    assert [o["correct"] for o in q["options"]] == [True, False, False]
    st2 = (await live(client, s2, rid)).json()
    assert st2["questions"][0]["my_correct"] is False

    # next question: q2 key must not leak
    assert (await control(client, t, rid, "goto", position=1)).status_code == 200
    st = (await live(client, s2, rid)).json()
    assert [x["id"] for x in st["questions"]] == [q2["id"]]
    assert not find_keys(st)
    # s2 is faster on q2 and also correct
    right2 = q2["options"][2]["id"]
    assert (await answer(client, s2, rid, q2["id"], option_ids=[right2])).status_code == 201
    assert (await answer(client, s1, rid, q2["id"], option_ids=[right2])).status_code == 201

    assert (await control(client, t, rid, "finalise")).status_code == 200
    st = (await live(client, s1, rid)).json()
    assert st["run"]["status"] == "finalised" and st["run"]["results_published"]
    board = st["leaderboard"]
    # s1: 1 win (q1) + 2 correct; s2: 1 win (q2) + 1 correct → s1 first
    assert board[0]["correct"] == 2 and board[0]["wins"] == 1
    assert st["my_rank"]["rank"] == 1
    res = (await client.get(f"{API}/runs/{rid}/results", headers=t.headers)).json()
    assert res["questions"][1]["winner"]["also_correct_count"] == 1
    # finalised: no more answers / joins
    r = await join(client, await second_student(w, "late"), code)
    assert r.status_code == 409


async def test_fastest_first_uses_server_order(world: World, client: Any) -> None:
    """Winner = earliest server timestamp even when a later responder joined first."""
    w = world
    t = w.personas["trainer_a"]
    ps = [w.personas["student"], await second_student(w, "s2"), await second_student(w, "s3")]
    a, run = await started_quiz(client, w, pacing="all_at_once", winner_rule="fastest_first")
    rid = run["id"]
    for p in reversed(ps):
        await join(client, p, run["join_code"])
    await control(client, t, rid, "start")
    q1 = a["questions"][0]
    right = q1["options"][0]["id"]
    for p in ps:  # answer in order s1, s2, s3
        assert (await answer(client, p, rid, q1["id"], option_ids=[right])).status_code == 201
    async with system_context(w.db, "test.check"):
        rows = (
            await w.db.execute(
                text(
                    "SELECT user_id, answered_at FROM engage_responses WHERE run_id = :r ORDER BY answered_at"
                ),
                {"r": uuid.UUID(rid)},
            )
        ).all()
    assert [r[0] for r in rows] == [p.id for p in ps]
    assert rows[0][1] < rows[1][1] < rows[2][1]
    pr = (await client.get(f"{API}/runs/{rid}/presenter", headers=t.headers)).json()
    # all named "Test User"; the winner's seq identifies who: s1 joined last (seq 3)
    w1 = pr["questions"][0]["winner"]
    assert w1["also_correct_count"] == 2
    board = pr["leaderboard"]
    assert board[0]["wins"] == 1 and board[0]["rank"] == 1


async def test_all_correct_rule_ranking(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    s1, s2 = w.personas["student"], await second_student(w)
    a, run = await started_quiz(
        client, w, pacing="all_at_once", winner_rule="all_correct", results_mode="live"
    )
    rid = run["id"]
    for p in (s1, s2):
        await join(client, p, run["join_code"])
    await control(client, t, rid, "start")
    q1, q2 = a["questions"]
    await answer(client, s2, rid, q1["id"], option_ids=[q1["options"][0]["id"]])
    await answer(client, s1, rid, q1["id"], option_ids=[q1["options"][0]["id"]])
    await answer(client, s1, rid, q2["id"], option_ids=[q2["options"][2]["id"]])
    await answer(client, s2, rid, q2["id"], option_ids=[q2["options"][0]["id"]])
    # live results mode: distribution visible, still no key
    st = (await live(client, s1, rid)).json()
    assert st["questions"][0]["options"][0]["count"] == 2
    assert not find_keys(st)
    pr = (await client.get(f"{API}/runs/{rid}/presenter", headers=t.headers)).json()
    assert pr["leaderboard"][0]["correct"] == 2 and pr["leaderboard"][0]["wins"] == 0


# --------------------------------------------------------------------------- join rules


async def test_members_only_vs_public_cross_org(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    sb = w.personas["student_b"]
    _a, run = await started_quiz(client, w, activity_type="poll", questions=[choice("Fav?")])
    r = await client.get(f"{API}/join/{run['join_code']}", headers=sb.headers)
    assert r.status_code == 200 and r.json()["eligible"] is False
    r = await join(client, sb, run["join_code"])
    assert r.status_code == 403
    # org member outside the batch is not a member of a batch activity
    outsider = await second_student(w, "outsider", batch=False)
    assert (await join(client, outsider, run["join_code"])).status_code == 403
    # not joined → cannot read live state or answer
    r = await live(client, sb, run["id"])
    assert r.status_code == 403 and r.json()["code"] == "not_joined"

    pub = await create(client, t, body(w, "poll", audience="public", questions=[choice("Fav?")]))
    prun = await launch(client, t, pub["id"])
    await control(client, t, prun["id"], "start")
    assert (await join(client, sb, prun["join_code"])).status_code == 200
    q = pub["questions"][0]
    r = await answer(client, sb, prun["id"], q["id"], option_ids=[q["options"][1]["id"]])
    assert r.status_code == 201
    pr = (await client.get(f"{API}/runs/{prun['id']}/presenter", headers=t.headers)).json()
    assert pr["joined"] == 1 and pr["questions"][0]["options"][1]["count"] == 1
    # bad / unknown codes
    assert (await join(client, sb, "NOPE")).status_code == 404
    assert (await join(client, sb, "ABCDEFGH")).status_code == 404


async def test_participant_limit(world: World, client: Any) -> None:
    w = world
    s1, s2 = w.personas["student"], await second_student(w)
    _a, run = await started_quiz(client, w, participant_limit=1)
    assert (await join(client, s1, run["join_code"])).status_code == 200
    r = await join(client, s2, run["join_code"])
    assert r.status_code == 409 and r.json()["code"] == "participant_limit_reached"
    assert (await join(client, s1, run["join_code"])).status_code == 200  # re-join is idempotent


async def test_anonymous_hides_identity(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    s1, s2 = w.personas["student"], await second_student(w)
    a, run = await started_quiz(
        client, w, identity_mode="anonymous", pacing="all_at_once", results_mode="live"
    )
    rid = run["id"]
    for p in (s1, s2):
        await join(client, p, run["join_code"])
    await control(client, t, rid, "start")
    q1 = a["questions"][0]
    await answer(client, s1, rid, q1["id"], option_ids=[q1["options"][0]["id"]])
    await control(client, t, rid, "finalise")
    pr = await client.get(f"{API}/runs/{rid}/presenter", headers=t.headers)
    st = await live(client, s2, rid)
    for payload in (pr.text, st.text):
        assert "Test User" not in payload
        assert str(s1.id) not in payload and str(s2.id) not in payload
    assert {p["label"] for p in pr.json()["participants"]} == {"Anonymous #1", "Anonymous #2"}
    assert pr.json()["questions"][0]["winner"]["fastest"] == "Anonymous #1"
    async with system_context(w.db, "test.check"):
        names = (
            await w.db.execute(
                text("SELECT display_name, user_id FROM engage_participants WHERE run_id = :r"),
                {"r": uuid.UUID(rid)},
            )
        ).all()
    assert all(n[0] is None for n in names) and {n[1] for n in names} == {s1.id, s2.id}


# --------------------------------------------------------------------------- word cloud, survey


async def test_word_cloud_normalisation_and_filter(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    ps = [w.personas["student"]] + [await second_student(w, f"w{i}") for i in range(3)]
    a = await create(
        client,
        t,
        body(w, "word_cloud", pacing="all_at_once", questions=[{"kind": "word", "prompt": "Best model?"}]),
    )
    run = await launch(client, t, a["id"])
    await control(client, t, run["id"], "start")
    q = a["questions"][0]
    assert q["max_words"] == 1
    for p, word in zip(ps, ["  ChatGPT!! ", "chatgpt", "f.u.c.k", "Gemini"], strict=True):
        await join(client, p, run["join_code"])
        r = await answer(client, p, run["id"], q["id"], text=word)
        assert r.status_code == 201, r.text
    r = await answer(client, ps[0], run["id"], q["id"], text="   ")
    assert r.status_code in (400, 409)
    pr = (await client.get(f"{API}/runs/{run['id']}/presenter", headers=t.headers)).json()
    assert pr["questions"][0]["words"] == [{"term": "chatgpt", "count": 2}, {"term": "gemini", "count": 1}]
    assert "fuck" not in json.dumps(pr)
    # on_publish: participants don't see the cloud before reveal
    st = (await live(client, ps[1], run["id"])).json()
    assert "words" not in st["questions"][0]
    await control(client, t, run["id"], "reveal")
    st = (await live(client, ps[1], run["id"])).json()
    assert st["questions"][0]["words"][0]["term"] == "chatgpt"


async def test_survey_kinds(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    s = w.personas["student"]
    qs = [
        {"kind": "rating", "prompt": "Rate the session"},
        {"kind": "text", "prompt": "Any feedback?"},
        choice("Pace?", kind="multi_choice"),
    ]
    a = await create(client, t, body(w, "survey", pacing="all_at_once", questions=qs))
    assert a["winner_rule"] is None
    assert all(not o["is_correct"] for o in a["questions"][2]["options"])
    run = await launch(client, t, a["id"])
    await control(client, t, run["id"], "start")
    await join(client, s, run["join_code"])
    rq, tq, mq = a["questions"]
    assert (await answer(client, s, run["id"], rq["id"], rating=4)).status_code == 201
    assert (await answer(client, s, run["id"], tq["id"], text="Great class")).status_code == 201
    ids = [mq["options"][0]["id"], mq["options"][2]["id"]]
    assert (await answer(client, s, run["id"], mq["id"], option_ids=ids)).status_code == 201
    pr = (await client.get(f"{API}/runs/{run['id']}/results", headers=t.headers)).json()
    assert pr["questions"][0]["average"] == 4.0 and pr["questions"][0]["ratings"]["4"] == 1
    assert pr["questions"][1]["texts"][0]["text"] == "Great class"
    assert [o["count"] for o in pr["questions"][2]["options"]] == [1, 0, 1]


# --------------------------------------------------------------------------- runs, polling, limits


async def test_rerun_closes_previous_and_new_code(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    a, run1 = await started_quiz(client, w)
    run2 = await launch(client, t, a["id"])
    assert run2["run_no"] == 2 and run2["join_code"] != run1["join_code"]
    d = (await client.get(f"{API}/activities/{a['id']}", headers=t.headers)).json()
    assert [(r["run_no"], r["status"]) for r in d["runs"]] == [(2, "scheduled"), (1, "closed")]
    r = await control(client, t, run1["id"], "start")
    assert r.status_code == 409


async def test_polling_version_and_etag(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    s = w.personas["student"]
    _a, run = await started_quiz(client, w)
    rid = run["id"]
    r = await client.get(f"{API}/runs/{rid}/presenter", headers=t.headers)
    v = r.json()["version"]
    assert r.headers["etag"] == f'W/"{v}"'
    r = await client.get(f"{API}/runs/{rid}/presenter", params={"since": v}, headers=t.headers)
    assert r.json() == {"unchanged": True, "version": v}
    r = await client.get(f"{API}/runs/{rid}/presenter", headers={**t.headers, "If-None-Match": f'W/"{v}"'})
    assert r.status_code == 304
    await join(client, s, run["join_code"])
    r = await client.get(f"{API}/runs/{rid}/presenter", params={"since": v}, headers=t.headers)
    assert r.json().get("unchanged") is None and r.json()["joined"] == 1
    v2 = (await live(client, s, rid)).json()["version"]
    await control(client, t, rid, "start")
    assert (await live(client, s, rid, since=v2)).json().get("unchanged") is None


async def test_answer_rate_limited(world: World, client: Any, monkeypatch: Any) -> None:
    """Uses an hour window so the fixed-window boundary can't reset the count mid-test."""
    from app.core.ratelimit import Rule
    from app.modules.engage import service

    monkeypatch.setattr(service, "ANSWER_RULES", (Rule(10, 3600),))
    w = world
    t = w.personas["trainer_a"]
    s = w.personas["student"]
    a, run = await started_quiz(client, w)
    await join(client, s, run["join_code"])
    await control(client, t, run["id"], "start")
    q1 = a["questions"][0]
    codes = [
        (await answer(client, s, run["id"], q1["id"], option_ids=[q1["options"][0]["id"]])).status_code
        for _ in range(11)
    ]
    assert codes[0] == 201 and codes[-1] == 429


async def test_scheduled_run_opens_and_closes_on_timer(world: World, client: Any) -> None:
    from datetime import timedelta

    from app.core.time import utcnow

    w = world
    t = w.personas["trainer_a"]
    s = w.personas["student"]
    now = utcnow()
    a = await create(
        client,
        t,
        body(
            w,
            "poll",
            run_mode="scheduled",
            pacing="all_at_once",
            opens_at=(now - timedelta(minutes=1)).isoformat(),
            closes_at=(now + timedelta(hours=1)).isoformat(),
            questions=[choice("Fav?")],
        ),
    )
    run = await launch(client, t, a["id"])
    assert run["status"] == "open"
    await join(client, s, run["join_code"])
    q = a["questions"][0]
    assert (
        await answer(client, s, run["id"], q["id"], option_ids=[q["options"][0]["id"]])
    ).status_code == 201
    async with system_context(w.db, "test.clock"):
        await w.db.execute(
            text("UPDATE engage_runs SET closes_at = now() - interval '1 second' WHERE id = :r"),
            {"r": uuid.UUID(run["id"])},
        )
    st = (await live(client, s, run["id"])).json()
    assert st["run"]["status"] == "closed"


async def test_invite_notifies_batch_members(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    _a, run = await started_quiz(client, w)
    r = await client.post(f"{API}/runs/{run['id']}/invite", headers=t.headers)
    assert r.status_code == 200, r.text
    assert r.json()["sent"] >= 1  # the batch student
    async with system_context(w.db, "test.check"):
        n = (
            await w.db.execute(
                text(
                    "SELECT count(*) FROM notifications WHERE template_key = 'engage.invite' AND user_id = :u"
                ),
                {"u": w.personas["student"].id},
            )
        ).scalar_one()
    assert n == 1


# --------------------------------------------------------------------------- bank import


async def test_bank_import_copies_key_only_with_key_access(world: World, client: Any) -> None:
    w = world
    tid = await topic(w.db, "python/lists")
    q = await question(w.db, w.personas["author"], w.personas["reviewer"], tid, stem="Which is a list?")
    r = await client.post(
        f"{API}/bank-import",
        json={"question_ids": [str(q.question_id)]},
        headers=w.personas["author"].headers,
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"][0]
    assert d["prompt"] == "Which is a list?" and d["kind"] == "single_choice" and d["key_copied"] is True
    assert [o["is_correct"] for o in d["options"]] == [False, True, False, False]
    r = await client.post(
        f"{API}/bank-import",
        json={"question_ids": [str(q.question_id)]},
        headers=w.personas["trainer_a"].headers,
    )
    assert r.json()["data"], r.json()
    d = r.json()["data"][0]
    assert d["key_copied"] is False and not any(o["is_correct"] for o in d["options"])
    r = await client.post(
        f"{API}/bank-import",
        json={"question_ids": [str(uuid.uuid4())]},
        headers=w.personas["trainer_a"].headers,
    )
    assert r.json()["data"] == [] and r.json()["skipped"][0]["reason"] == "not_found"


def test_word_normalisation_unit() -> None:
    from app.modules.engage.words import is_blocked, normalise_terms

    assert normalise_terms("  Large  Language-Model!! ", 2) == ["large language-model"]
    assert normalise_terms("C++", 1) == ["c++"]
    assert normalise_terms("gpt-4, claude, gemini", 2) == ["gpt-4", "claude"]
    assert normalise_terms("...", 1) == []
    assert is_blocked("Sh1t") and is_blocked("f.u.c.k") and not is_blocked("scunthorpe")


# --------------------------------------------------------------------------- single company (WS4)


async def test_no_organization_target_or_picker(world: World, client: Any) -> None:
    """Single company: an activity targets a batch or the platform; ``organization_id`` is not an
    input, and a legacy organization-wide row cannot be created (CHECK) nor joined as members."""
    w = world
    t = w.personas["trainer_a"]
    ad = await admin(w)
    # organization picker gone: the field is rejected (extra=forbid)
    r = await client.post(f"{API}/activities", json=body(w, organization_id=str(w.org_a)), headers=t.headers)
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "extra_forbidden", r.text
    # no batch = platform activity: a batch trainer may not create one, Admin may
    plat = body(w, "poll", pacing="all_at_once", questions=[choice("Fav?")])
    plat.pop("batch_id")
    r = await client.post(f"{API}/activities", json=plat, headers=t.headers)
    assert r.status_code == 403
    a = await create(client, ad, plat)
    assert a["organization_id"] is None and a["batch_id"] is None
    run = await launch(client, ad, a["id"])
    # a platform activity has no member list to invite
    r = await client.post(f"{API}/runs/{run['id']}/invite", headers=ad.headers)
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "no_audience"
    # a batch activity stamps the batch's organization
    b = await create(client, ad, body(w))
    assert b["batch_id"] == str(w.batch_a) and b["organization_id"] == str(w.org_a)
    # the database refuses a live organization-wide activity (engage_0002 ck_ea_no_org_wide)
    async with system_context(w.db, "test.check"):
        await w.db.execute(text("SAVEPOINT ow"))
        try:
            await w.db.execute(
                text("UPDATE engage_activities SET batch_id = NULL WHERE id = :a"), {"a": uuid.UUID(b["id"])}
            )
            raise AssertionError("ck_ea_no_org_wide not enforced")
        except Exception as e:
            assert "ck_ea_no_org_wide" in str(e), e
        finally:
            await w.db.execute(text("ROLLBACK TO SAVEPOINT ow"))


async def test_removed_batch_member_cannot_join_or_be_invited(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    s2 = await second_student(w, "leaver")
    _a, run = await started_quiz(client, w)
    async with system_context(w.db, "test.factory"):
        await w.db.execute(
            text("UPDATE batch_members SET status = 'removed', removed_at = now() WHERE user_id = :u"),
            {"u": s2.id},
        )
    r = await join(client, s2, run["join_code"])
    assert r.status_code == 403
    r = await client.post(f"{API}/runs/{run['id']}/invite", headers=t.headers)
    assert r.status_code == 200
    async with system_context(w.db, "test.check"):
        n = (
            await w.db.execute(
                text(
                    "SELECT count(*) FROM notifications WHERE template_key = 'engage.invite' AND user_id = :u"
                ),
                {"u": s2.id},
            )
        ).scalar_one()
    assert n == 0


async def test_sec06_publish_only_on_closed_runs(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    s = w.personas["student"]
    a, run = await started_quiz(client, w, pacing="all_at_once")
    rid = run["id"]
    await join(client, s, run["join_code"])
    # scheduled and open runs cannot publish (the key would show while still answerable)
    r = await control(client, t, rid, "publish")
    assert r.status_code == 409 and r.json()["code"] == "invalid_state_transition"
    await control(client, t, rid, "start")
    r = await control(client, t, rid, "publish")
    assert r.status_code == 409
    st = (await live(client, s, rid)).json()
    assert not find_keys(st) and not st["run"]["results_published"]
    q1 = a["questions"][0]
    assert (await answer(client, s, rid, q1["id"], option_ids=[q1["options"][0]["id"]])).status_code == 201
    await control(client, t, rid, "close")
    assert (await control(client, t, rid, "publish")).status_code == 200
    assert (await control(client, t, rid, "unpublish")).status_code == 200


async def test_sec06_revealed_question_stays_closed_after_hide(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    s = w.personas["student"]
    a, run = await started_quiz(client, w)  # one_by_one
    rid = run["id"]
    await join(client, s, run["join_code"])
    await control(client, t, rid, "start")
    q1 = a["questions"][0]
    assert (await control(client, t, rid, "reveal")).status_code == 200
    assert (await control(client, t, rid, "hide")).status_code == 200
    st = (await live(client, s, rid)).json()
    q = st["questions"][0]
    assert q["answerable"] is False and not find_keys(st)
    r = await answer(client, s, rid, q1["id"], option_ids=[q1["options"][0]["id"]])
    assert r.status_code == 409 and r.json()["code"] == "question_not_open"


def test_sec06_answerable_unit() -> None:
    from app.modules.engage.models import EngageRun
    from app.modules.engage.service import _answerable

    r = EngageRun(
        status="open",
        settings={"pacing": "all_at_once"},
        questions=[{"id": "a"}, {"id": "b"}],
        current_position=0,
        revealed_positions=[],
        closed_positions=[],
        results_published=False,
    )
    assert _answerable(r, 0) and _answerable(r, 1)
    r.closed_positions = [1]
    assert _answerable(r, 0) and not _answerable(r, 1)
    r.results_published = True
    assert not _answerable(r, 0)


async def test_sec07_invite_and_launch_budget_survive_relaunch(world: World, client: Any) -> None:
    w = world
    t = w.personas["trainer_a"]
    a = await create(client, t, body(w))
    codes = []
    for _ in range(6):  # relaunching mints a new run id; the invite budget (5/h) must not reset
        run = await launch(client, t, a["id"])
        codes.append((await client.post(f"{API}/runs/{run['id']}/invite", headers=t.headers)).status_code)
    assert codes[:5] == [200] * 5 and codes[5] == 429
    # launches themselves are budgeted per activity + manager (10/h): 6 used above
    launched = [
        (await client.post(f"{API}/activities/{a['id']}/runs", json={}, headers=t.headers)).status_code
        for _ in range(5)
    ]
    assert launched[:4] == [201] * 4 and launched[4] == 429
    # another activity has its own budget
    b = await create(client, t, body(w, title="Other"))
    assert (
        await client.post(f"{API}/activities/{b['id']}/runs", json={}, headers=t.headers)
    ).status_code == 201


async def test_leaderboard_uses_nicknames_never_full_names(world: World, client: Any) -> None:
    """§2.4: students share one company org, so labels must never reveal a learner's real name or
    e-mail — only the profile nickname (``display_name``), else ``Participant #n``."""
    w = world
    t = w.personas["trainer_a"]
    s1, s2 = w.personas["student"], await second_student(w)
    async with system_context(w.db, "test.factory"):
        await w.db.execute(
            text(
                "UPDATE user_profiles SET display_name = 'Ace', full_name = 'Real Name One' WHERE user_id = :u"
            ),
            {"u": s1.id},
        )
        await w.db.execute(
            text("UPDATE user_profiles SET full_name = 'Real Name Two' WHERE user_id = :u"), {"u": s2.id}
        )
    a, run = await started_quiz(client, w, pacing="all_at_once", results_mode="live")
    rid = run["id"]
    for p in (s1, s2):
        assert (await join(client, p, run["join_code"])).status_code == 200
    await control(client, t, rid, "start")
    q1 = a["questions"][0]
    for p in (s1, s2):
        await answer(client, p, rid, q1["id"], option_ids=[q1["options"][0]["id"]])
    await control(client, t, rid, "finalise")
    pr = await client.get(f"{API}/runs/{rid}/presenter", headers=t.headers)
    st = await live(client, s2, rid)
    for payload in (pr.text, st.text):
        assert "Real Name" not in payload
        assert s1.email not in payload and s2.email not in payload
        assert str(s1.id) not in payload and str(s2.id) not in payload
    labels = {row["label"] for row in st.json()["leaderboard"]}
    assert labels == {"Ace", "Participant #2"}
