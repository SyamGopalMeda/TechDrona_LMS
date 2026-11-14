"""AI routes and the tutor service on Firestore with no Postgres (request session NO_POSTGRES)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.db import NO_POSTGRES
from app.core.ids import uuid7
from app.modules.ai import public as ai_public
from app.modules.ai import store
from app.modules.ai.adapters import FakeAIAdapter, set_ai_adapter
from app.modules.identity import clock

FS_MODULES = ("ai", "audit", "core", "admin")
P = "/api/v1"


@pytest.fixture
def fake_ai() -> Iterator[FakeAIAdapter]:
    a = FakeAIAdapter()
    set_ai_adapter(a)
    yield a
    set_ai_adapter(None)


def _admin(make_principal: Any, auth: Any) -> dict[str, str]:
    p = make_principal(
        is_platform=True, roles=("super_admin",), tier="privileged", last_step_up_at=clock.now()
    )
    for perm in ("feature_flag.manage", "analytics.read.platform"):
        auth.grant(p, perm)
    return auth.login(p)


async def test_tutor_flow_usage_and_history(
    fs_http: Any, make_principal: Any, fake_ai: FakeAIAdapter
) -> None:
    client, _rec, auth = fs_http
    learner = make_principal()
    ctx = uuid7()
    for i in range(2):
        out = await ai_public.tutor_reply(
            NO_POSTGRES,
            user_id=learner.user_id,
            context_type="assignment",
            context_id=ctx,
            mode="explain",
            question_md="What is 2+2?",
            learner_input=f"try {i}",
            per_learner_limit=2,
        )
        assert out["used"] == i + 1 and out["limit"] == 2
    with pytest.raises(ai_public.AIQuotaExceeded):
        await ai_public.tutor_reply(
            NO_POSTGRES,
            user_id=learner.user_id,
            context_type="assignment",
            context_id=ctx,
            mode="explain",
            question_md="q",
            learner_input="again",
            per_learner_limit=2,
        )
    hist = await client.get(
        f"{P}/me/ai/tutor-history",
        params={"context_type": "assignment", "context_id": str(ctx)},
        headers=auth.login(learner),
    )
    assert hist.status_code == 200, hist.text
    turns = hist.json()["data"]
    assert [t["role"] for t in turns] == ["learner", "tutor", "learner", "tutor"]
    assert turns[0]["content"] == "try 0" and turns[0]["created_at"].endswith("Z")
    other = await client.get(
        f"{P}/me/ai/tutor-history",
        params={"context_type": "assignment", "context_id": str(ctx)},
        headers=auth.login(make_principal()),
    )
    assert other.json()["data"] == []

    h = _admin(make_principal, auth)
    usage = (await client.get(f"{P}/admin/ai-usage", headers=h)).json()
    assert usage["totals"]["calls"] == 2 and usage["by_feature"][0]["feature"] == "tutor"
    assert usage["by_day"][0]["date"] == datetime.now(UTC).date().isoformat()
    assert usage["caps"]["monthly_call_cap"] == store.PlatformAI().monthly_call_cap
    assert (await client.get(f"{P}/admin/ai-usage", params={"month": "2020-01"}, headers=h)).json()["totals"][
        "calls"
    ] == 0


async def test_settings_and_apps_routes(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    h = _admin(make_principal, auth)
    r = await client.patch(f"{P}/admin/ai-settings", json={"per_activity_default_cap": 5}, headers=h)
    assert r.status_code == 200, r.text
    got = (await client.get(f"{P}/admin/ai-settings", headers=h)).json()
    assert got["ai"]["per_activity_default_cap"] == 5
    a = await client.patch(f"{P}/admin/apps", json={"apps": {"engage": False}}, headers=h)
    assert a.status_code == 200, a.text
    mine = (await client.get(f"{P}/me/enabled-apps", headers=auth.login(make_principal()))).json()
    assert mine["apps"]["engage"] is False and mine["apps"]["paths"] is True
    assert (await client.get(f"{P}/admin/ai-usage", headers=auth.login(make_principal()))).status_code == 403
