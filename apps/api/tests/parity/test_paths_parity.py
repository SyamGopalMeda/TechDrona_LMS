"""Parity: learning paths over HTTP on the Firebase stack (author -> publish -> allocate ->
learner opens/completes steps -> staff progress).

VM expectations (``tests/paths``): create 201, steps 200, publish 200, allocation 201, ``/me/paths``
200, step open 200 ``in_progress``, complete 200 ``completed``, progress 200.
"""

from __future__ import annotations

from typing import Any

from tests.parity.harness import World


async def test_path_author_allocate_learn(web: World, monkeypatch: Any) -> None:
    from app.modules.paths import service as svc

    w = web
    _, sh = await w.staff("pathstaff")
    learner, lh = await w.learner("walker")
    # the learner joins a batch (orgs route store) so she is an active company learner
    r = await w.call("POST", "/batches", sh, expect=201, json={"name": "Parity batch", "code": "PB-1"})
    bid = r.json()["id"]
    await w.call("POST", f"/batches/{bid}/members", sh, json={"user_ids": [str(learner.user_id)]})
    await w.call("GET", f"/batches/{bid}/members", sh)
    r = await w.call("POST", "/paths", sh, expect=201, json={"title": "Core Python", "level": "beginner"})
    pid = r.json()["id"]
    steps = {
        "steps": [
            {
                "step_type": "reading",
                "title": "Intro",
                "url": "https://example.org/a",
                "est_hours": "1",
                "credits": 10,
            },
            {
                "step_type": "video",
                "title": "Loops",
                "url": "https://example.org/v",
                "est_hours": "0.5",
                "credits": 5,
            },
        ]
    }
    await w.call("PUT", f"/paths/{pid}/steps", sh, json=steps)
    await w.call("GET", f"/paths/{pid}", sh)
    for kind in ("assignment", "test", "article", "lesson"):
        await w.call("GET", "/paths/link-options", sh, params={"kind": kind})
    await w.call("POST", f"/paths/{pid}/publish", sh)
    r = await w.call(
        "POST",
        f"/paths/{pid}/allocations",
        sh,
        expect=201,
        json={
            "target_type": "users",
            "user_ids": [str(learner.user_id)],
            "flow": "lenient",
            "sequential": True,
        },
    )
    aid = r.json()["id"]
    r = await w.call("GET", "/me/paths", lh)
    assert [m["allocation_id"] for m in r.json()["data"]] == [aid], r.text
    player = (await w.call("GET", f"/me/paths/{aid}", lh)).json()
    keys = {s["title"]: s["step_key"] for s in player["steps"]}
    r = await w.call("POST", f"/me/paths/{aid}/steps/{keys['Intro']}/open", lh)
    assert r.json()["state"] == "in_progress"
    monkeypatch.setattr(svc, "min_dwell_seconds", lambda step: 0)
    r = await w.call("POST", f"/me/paths/{aid}/steps/{keys['Intro']}/complete", lh)
    assert r.json()["step"]["state"] == "completed"
    await w.call("GET", f"/path-allocations/{aid}/progress", sh)
    # AI draft: whatever the AI setup answers (201 simulated / 403-503 when off), never 500
    await w.call(
        "POST",
        "/paths/ai-generate",
        sh,
        expect=(201, 403, 409, 422, 429, 503),
        json={"topic": "Python basics", "target_hours": 10, "approx_steps": 3},
    )
    await w.relay()  # outbox consumers, as the Firebase worker runs them
