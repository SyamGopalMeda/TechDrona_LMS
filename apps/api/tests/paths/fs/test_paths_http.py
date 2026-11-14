"""Paths over HTTP on Firestore (``TD_STORE_PATHS=firestore``), no Postgres.

The full author -> publish -> allocate -> learner -> progress -> article -> archive flow through
the real FastAPI app. The fake request session refuses every SQL statement except the RLS
settings, so any leftover Postgres access on the paths tables fails the test. Other modules'
tables are reached only through ``paths.adapters`` (stubbed here, at that boundary).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from tests.paths.fs.http_harness import install_fake_db, restore_switch, stub_core, switch_to_firestore

API = "/api/v1"
STAFF_PERMS = (
    "path.manage",
    "path.allocate",
    "path.publish",
    "path.update",
    "path.archive",
    "path.create",
    "path.steps_save",
    "path.allocation_revoke",
    "path_article.create",
    "path_article.update",
    "path_article.publish",
    "path_article.unpublish",
    "path_article.delete",
)


@pytest.fixture
async def web(
    fs_client: Any, monkeypatch: pytest.MonkeyPatch, auth: Any
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, list[tuple[str, Any]]]]:
    from app.main import create_app
    from app.modules.paths import adapters
    from app.modules.paths import service as svc

    calls: list[tuple[str, Any]] = []
    stub_core(monkeypatch, calls)

    async def app_on(session: Any, *, app_key: str) -> None:
        return None

    monkeypatch.setattr(svc, "require_app_enabled", app_on)

    async def members(session: Any, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        return set(user_ids)

    async def no_batches(session: Any, user_id: uuid.UUID) -> set[uuid.UUID]:
        return set()

    async def names(session: Any, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
        return {u: (f"Learner {str(u)[:4]}", "x@example.test") for u in user_ids}

    async def yes(*a: Any) -> bool:
        return True

    monkeypatch.setattr(adapters, "active_company_members", members)
    monkeypatch.setattr(adapters, "student_batch_ids", no_batches)
    monkeypatch.setattr(adapters, "user_names", names)
    monkeypatch.setattr(adapters, "test_in_org", yes)
    await switch_to_firestore(fs_client, monkeypatch, "paths")
    app = create_app()
    install_fake_db(app)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c, auth, calls
    finally:
        restore_switch(monkeypatch, "paths")


async def test_author_publish_allocate_learn_and_archive(
    web: Any, make_principal: Any, monkeypatch: Any
) -> None:
    from app.modules.paths import adapters
    from app.modules.paths import service as svc

    c, auth, calls = web
    staff = make_principal(is_platform=True)
    for p in STAFF_PERMS:
        auth.grant(staff, p)
    sh = auth.login(staff)
    learner = make_principal()
    lh = auth.login(learner)

    r = await c.post(f"{API}/paths", json={"title": "  Core Python ", "level": "beginner"}, headers=sh)
    assert r.status_code == 201, r.text
    path = r.json()
    pid = path["id"]
    assert path["title"] == "Core Python" and path["status"] == "draft" and path["steps"] == []

    test_id = str(uuid.uuid4())
    steps = {
        "steps": [
            {
                "step_type": "reading",
                "title": "Intro",
                "url": "https://www.youtube-nocookie.com/embed/abc",
                "est_hours": "1.5",
                "credits": 10,
            },
            {
                "step_type": "super_step",
                "title": "Practice",
                "children": [
                    {
                        "step_type": "video",
                        "title": "Loops",
                        "url": "https://example.org/v",
                        "est_hours": "0.5",
                        "credits": 5,
                    },
                    {"step_type": "assessment", "title": "Quiz", "test_id": test_id, "credits": 20},
                ],
            },
        ]
    }
    r = await c.put(f"{API}/paths/{pid}/steps", json=steps, headers=sh)
    assert r.status_code == 200, r.text
    r = await c.get(f"{API}/paths/{pid}", headers=sh)
    detail = r.json()
    assert detail["step_count"] == 3 and detail["total_credits"] == 35 and detail["total_hours"] == 2.0
    assert [s["title"] for s in detail["steps"]] == ["Intro", "Practice"]
    assert detail["steps"][0]["embeddable"] is True
    assert [s["title"] for s in detail["steps"][1]["children"]] == ["Loops", "Quiz"]

    r = await c.get(f"{API}/paths", params={"q": "python"}, headers=sh)
    assert [p["id"] for p in r.json()["data"]] == [pid]

    r = await c.post(f"{API}/paths/{pid}/publish", headers=sh)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published" and r.json()["version_no"] == 1

    body = {"target_type": "users", "user_ids": [str(learner.user_id)], "flow": "lenient", "sequential": True}
    r = await c.post(f"{API}/paths/{pid}/allocations", json=body, headers=sh)
    assert r.status_code == 201, r.text
    alloc = r.json()
    aid = alloc["id"]
    assert alloc["version_no"] == 1 and alloc["learner_count"] == 1 and alloc["status"] == "active"

    r = await c.get(f"{API}/me/paths", headers=lh)
    mine = r.json()["data"]
    assert (
        [m["allocation_id"] for m in mine] == [aid] and mine[0]["step_count"] == 3 and not mine[0]["started"]
    )
    other = auth.login(make_principal())
    assert (await c.get(f"{API}/me/paths", headers=other)).json()["data"] == []
    assert (await c.get(f"{API}/me/paths/{aid}", headers=other)).status_code == 404

    player = (await c.get(f"{API}/me/paths/{aid}", headers=lh)).json()
    keys = {s["title"]: s["step_key"] for s in player["steps"]}
    assert {s["title"]: s["state"] for s in player["steps"]}["Loops"] == "locked"  # sequential

    r = await c.post(f"{API}/me/paths/{aid}/steps/{keys['Intro']}/open", headers=lh)
    assert r.status_code == 200 and r.json()["state"] == "in_progress"
    again = await c.post(
        f"{API}/me/paths/{aid}/steps/{keys['Intro']}/open", headers=lh
    )  # ON CONFLICT DO NOTHING
    assert again.json()["opened_at"] == r.json()["opened_at"]
    r = await c.post(f"{API}/me/paths/{aid}/steps/{keys['Intro']}/complete", headers=lh)
    assert r.status_code == 409 and r.json()["code"] == "too_early"
    monkeypatch.setattr(svc, "min_dwell_seconds", lambda step: 0)
    r = await c.post(f"{API}/me/paths/{aid}/steps/{keys['Intro']}/complete", headers=lh)
    assert r.status_code == 200, r.text
    assert r.json()["credits_earned"] == 10 and r.json()["step"]["state"] == "completed"
    r = await c.post(f"{API}/me/paths/{aid}/steps/{keys['Quiz']}/complete", headers=lh)
    assert r.status_code == 409 and r.json()["code"] == "completion_by_evaluation"

    # assessments ``attempt.scored`` -> the quiz step completes from evidence (outbox handler)
    async def outcome(session: Any, attempt_id: uuid.UUID) -> tuple[Any, ...]:
        return (learner.user_id, uuid.UUID(test_id), "clean", True, None)

    monkeypatch.setattr(adapters, "attempt_outcome", outcome)

    class Msg:
        payload = {"attempt_id": str(uuid.uuid4())}

    await svc.on_attempt_scored(None, Msg())  # type: ignore[arg-type]
    await svc.on_attempt_scored(None, Msg())  # idempotent
    player = (await c.get(f"{API}/me/paths/{aid}", headers=lh)).json()
    st = {s["title"]: (s["state"], s["credits_awarded"]) for s in player["steps"]}
    assert st["Quiz"] == ("completed", 20) and st["Intro"] == ("completed", 10)
    assert player["credits_earned"] == 30

    prog = (await c.get(f"{API}/path-allocations/{aid}/progress", headers=sh)).json()
    row = prog["learners"][0]
    assert (row["user_id"], row["completed_steps"], row["total_steps"], row["credits_earned"]) == (
        str(learner.user_id),
        2,
        3,
        30,
    )

    # articles
    r = await c.post(
        f"{API}/path-articles", json={"title": "Guide", "body_md": "## Part one\n\nworld"}, headers=sh
    )
    assert r.status_code == 201, r.text
    art = r.json()["id"]
    assert r.json()["toc"]
    assert [a["id"] for a in (await c.get(f"{API}/path-articles", headers=sh)).json()["data"]] == [art]
    assert (await c.get(f"{API}/read/{art}", headers=lh)).status_code == 404  # not in audience yet
    r = await c.post(
        f"{API}/path-articles/{art}/publish",
        json={"audience": "people", "user_ids": [str(learner.user_id)]},
        headers=sh,
    )
    assert r.status_code == 200, r.text
    read = (await c.get(f"{API}/read/{art}", headers=lh)).json()
    assert read["title"] == "Guide" and read["status"] == "published" and read["can_edit"] is False
    assert (await c.delete(f"{API}/path-articles/{art}", headers=sh)).status_code == 204
    assert (await c.get(f"{API}/path-articles/{art}", headers=sh)).status_code == 404

    # archive revokes the active allocation
    assert (await c.delete(f"{API}/paths/{pid}", headers=sh)).status_code == 204
    assert (await c.get(f"{API}/me/paths", headers=lh)).json()["data"] == []
    actions = [a for k, a in calls if k == "audit"]
    for needed in ("path.create", "path.steps_save", "path.publish", "path.allocate", "path.archive"):
        assert needed in actions


async def test_learner_cannot_author(web: Any, make_principal: Any) -> None:
    c, auth, _ = web
    lh = auth.login(make_principal())
    assert (await c.post(f"{API}/paths", json={"title": "x"}, headers=lh)).status_code == 403
    assert (await c.get(f"{API}/paths", headers=lh)).json() == {"data": []}
