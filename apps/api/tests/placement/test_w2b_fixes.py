"""Regression tests for wave-2 placement fixes (w2b): studio topic list with inactive topics,
``retired_reason`` in question output, and the PLC-04 ``q`` stem search."""

from __future__ import annotations

from typing import Any

from tests.placement.test_audit_fixes import _new_question
from tests.placement.world import World, topic

API = "/api/v1"


def _flatten(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for n in nodes:
        out[n["path"]] = n
        out.update(_flatten(n["children"]))
    return out


async def test_studio_topic_list_includes_inactive_for_staff_only(client, world: World, db) -> None:
    author, student = world.personas["author"], world.personas["student"]
    t = await topic(db, "w2bsub/retiredtopic")
    r = await client.patch(f"{API}/studio/topics/{t}", json={"is_active": False}, headers=author.headers)
    assert r.status_code == 200, r.text

    pub = _flatten((await client.get(f"{API}/placement/subjects")).json()["items"])
    assert "w2bsub/retiredtopic" not in pub

    r = await client.get(f"{API}/studio/topics", headers=author.headers)
    assert r.status_code == 200, r.text
    nodes = _flatten(r.json()["items"])
    assert nodes["w2bsub/retiredtopic"]["is_active"] is False
    assert nodes["w2bsub"]["is_active"] is True

    r = await client.get(f"{API}/studio/topics", headers=student.headers)
    assert r.status_code == 403


async def test_retired_reason_exposed(client, world: World, db) -> None:
    author, reviewer = world.personas["author"], world.personas["reviewer"]
    t = await topic(db, "w2bsub/retire")
    qid = await _new_question(client, author, t)
    await client.post(f"{API}/studio/questions/{qid}/submit-review", headers=author.headers)
    await client.post(
        f"{API}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=reviewer.headers
    )
    await client.post(f"{API}/studio/questions/{qid}/publish", headers=reviewer.headers)
    r = await client.post(
        f"{API}/studio/questions/{qid}/retire", json={"reason": "Ambiguous stem"}, headers=reviewer.headers
    )
    assert r.status_code == 200, r.text
    d = (await client.get(f"{API}/studio/questions/{qid}", headers=author.headers)).json()
    assert d["retired_reason"] == "Ambiguous stem"
    items = (
        await client.get(f"{API}/studio/questions", params={"topic_id": str(t)}, headers=author.headers)
    ).json()["items"]
    assert [i["retired_reason"] for i in items] == ["Ambiguous stem"]


async def test_question_search_by_stem_text(client, world: World, db) -> None:
    author = world.personas["author"]
    t = await topic(db, "w2bsub/search")
    hit = await _new_question(client, author, t, stem_html="<p>A <b>train</b> crosses a platform</p>")
    await _new_question(client, author, t, stem_html="<p>Find the compound interest</p>")

    async def ids(q: str) -> list[str]:
        r = await client.get(
            f"{API}/studio/questions", params={"topic_id": str(t), "q": q}, headers=author.headers
        )
        assert r.status_code == 200, r.text
        return [i["question_id"] for i in r.json()["items"]]

    assert await ids("TRAIN crosses") == [hit]  # case-insensitive, ignores markup
    assert await ids("100%_") == []  # LIKE wildcards are literal
    r = await client.get(f"{API}/studio/questions", params={"q": "x"}, headers=author.headers)
    assert r.status_code == 400
