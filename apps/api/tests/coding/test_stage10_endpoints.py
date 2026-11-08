"""Stage 10: studio problem list + flat detail fields used by the web studio."""

from __future__ import annotations

import uuid

from app.core.db import system_context
from tests.coding.conftest import HIDDEN_EXPECTED, HIDDEN_INPUT, seed_problem

MANAGE = "coding_problem.manage"


async def test_studio_list_and_detail(client, db, actors) -> None:
    author = await actors(MANAGE, is_platform=True)
    tag = uuid.uuid4().hex[:6]
    p1 = await seed_problem(db, author.id, slug=f"alpha-{tag}", hidden=2, publish=True)
    p2 = await seed_problem(db, author.id, slug=f"beta-{tag}", hidden=1, publish=False)

    r = await client.get("/api/v1/studio/coding/problems", params={"limit": 100}, headers=author.headers)
    assert r.status_code == 200, r.text
    rows = {x["problem_id"]: x for x in r.json()["data"]}
    assert str(p1.id) in rows and str(p2.id) in rows
    a = rows[str(p1.id)]
    assert a["status"] == "published" and a["test_cases"] == {"sample": 1, "hidden": 2}
    assert a["languages"] and a["time_limit_ms"] and a["memory_limit_mb"] == 256
    assert rows[str(p2.id)]["status"] == "draft"

    drafts = await client.get(
        "/api/v1/studio/coding/problems",
        params={"status": "draft", "q": f"beta-{tag}"},
        headers=author.headers,
    )
    assert [x["problem_id"] for x in drafts.json()["data"]] == [str(p2.id)]

    page = await client.get("/api/v1/studio/coding/problems", params={"limit": 1}, headers=author.headers)
    meta = page.json()["meta"]
    assert len(page.json()["data"]) == 1 and meta["has_more"] is True
    nxt = await client.get(
        "/api/v1/studio/coding/problems",
        params={"limit": 1, "cursor": meta["next_cursor"]},
        headers=author.headers,
    )
    assert (
        nxt.status_code == 200 and nxt.json()["data"][0]["problem_id"] != page.json()["data"][0]["problem_id"]
    )

    d = await client.get(f"/api/v1/studio/coding/problems/{p1.id}", headers=author.headers)
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["test_cases"]["hidden"] == 2 and body["checker_type"] and body["limits"]["time_limit_ms"]
    for resp in (r, d):
        assert HIDDEN_INPUT.strip() not in resp.text and HIDDEN_EXPECTED.strip() not in resp.text


async def test_studio_list_requires_manage(client, db, actors) -> None:
    author = await actors(MANAGE, is_platform=True)
    await system_context(db, "test.factory")
    await seed_problem(db, author.id, publish=True)
    student = await actors()
    r = await client.get("/api/v1/studio/coding/problems", headers=student.headers)
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"
