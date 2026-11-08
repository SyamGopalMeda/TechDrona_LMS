"""ai endpoints (single company): /admin/ai-settings, /admin/apps, /admin/ai-usage (platform
scope, step-up, audit, no secrets), /me/enabled-apps and /me/ai/tutor-history; the old
/admin/orgs/* routes are gone (FakeAuth resolver/checker)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import system_context
from app.modules.ai import router as ai_router
from app.modules.ai import service as ai
from app.modules.ai.models import AIUsage, TutorTurn
from app.modules.identity import clock
from tests.identity.factory import make_user

API = "/api/v1"
ADMIN_PERMS = ("feature_flag.manage", "analytics.read.platform")


@pytest.fixture
def audited(monkeypatch: Any) -> list[tuple[str, dict[str, Any] | None]]:
    calls: list[tuple[str, dict[str, Any] | None]] = []
    real = ai_router.audit

    async def spy(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        calls.append((action, kw.get("after")))
        return await real(session, actor, action, *a, **kw)

    monkeypatch.setattr(ai_router, "audit", spy)
    return calls


async def _admin(db: Any, auth: Any, make_principal: Any, *perms: str, fresh: bool = True) -> dict[str, str]:
    u = await make_user(db)
    p = make_principal(
        user_id=u.id,
        tier="privileged",
        is_platform=True,
        roles=("super_admin",),
        last_step_up_at=clock.now() if fresh else None,
    )
    for perm in perms:
        auth.grant(p, perm)
    return auth.login(p)


async def test_old_org_routes_are_gone(db, client, auth, make_principal) -> None:
    h = await _admin(db, auth, make_principal, *ADMIN_PERMS)
    for suffix in ("ai-settings", "apps", "ai-usage"):
        r = await client.get(f"{API}/admin/orgs/{uuid.uuid4()}/{suffix}", headers=h)
        assert r.status_code == 404, (suffix, r.status_code)


async def test_settings_roundtrip_audited_and_secret_free(db, client, auth, make_principal, audited) -> None:
    h = await _admin(db, auth, make_principal, "feature_flag.manage")
    r = await client.get(f"{API}/admin/ai-settings", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai"]["enabled"] is True and body["ai"]["model"] == "claude-sonnet-5-5"
    assert body["ai"]["per_activity_default_cap"] == 20  # D10 default
    assert body["ai"]["monthly_call_cap"] > 0 and body["ai"]["tutor_per_minute"] == 10
    assert body["provider"] == {"name": "fake", "configured": True}
    assert "organization_id" not in body
    assert "api_key" not in r.text.lower() and "secret" not in r.text.lower()

    patch = {
        "enabled": True,
        "model": "claude-haiku-5-5",
        "monthly_call_cap": 100,
        "per_activity_default_cap": 3,
        "tutor_per_day": 50,
    }
    r = await client.patch(f"{API}/admin/ai-settings", json=patch, headers=h)
    assert r.status_code == 200, r.text
    ai_out = r.json()["ai"]
    assert ai_out["model"] == "claude-haiku-5-5" and ai_out["per_activity_default_cap"] == 3
    assert ai_out["tutor_per_day"] == 50
    assert audited[-1][0] == "ai.settings.updated" and audited[-1][1]["monthly_call_cap"] == 100
    r = await client.get(f"{API}/admin/ai-settings", headers=h)
    assert r.json()["ai"]["per_activity_default_cap"] == 3  # persisted

    # caps can no longer be cleared to "unlimited" (SEC-05)
    r = await client.patch(f"{API}/admin/ai-settings", json={"monthly_call_cap": None}, headers=h)
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    r = await client.patch(f"{API}/admin/ai-settings", json={"model": "gpt-x"}, headers=h)
    assert r.status_code == 422
    r = await client.patch(f"{API}/admin/ai-settings", json={"api_key": "sk"}, headers=h)
    assert r.status_code == 400  # keys are never accepted through the API


async def test_permissions_and_step_up(db, client, auth, make_principal) -> None:
    nobody = await _admin(db, auth, make_principal)
    for path in ("/admin/ai-settings", "/admin/apps", "/admin/ai-usage"):
        r = await client.get(f"{API}{path}", headers=nobody)
        assert r.status_code == 403, path
    r = await client.patch(f"{API}/admin/ai-settings", json={"enabled": False}, headers=nobody)
    assert r.status_code == 403
    stale = await _admin(db, auth, make_principal, "feature_flag.manage", fresh=False)
    r = await client.patch(f"{API}/admin/apps", json={"apps": {"engage": False}}, headers=stale)
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"
    r = await client.patch(f"{API}/admin/ai-settings", json={"enabled": False}, headers=stale)
    assert r.status_code == 401


async def test_apps_default_enabled_and_toggle(db, client, auth, make_principal, audited) -> None:
    h = await _admin(db, auth, make_principal, "feature_flag.manage")
    r = await client.get(f"{API}/admin/apps", headers=h)
    assert r.status_code == 200, r.text
    apps = {a["app_key"]: a["enabled"] for a in r.json()["apps"]}
    assert len(apps) == 8 and all(apps.values())
    for _ in range(2):  # insert, then update path
        r = await client.patch(
            f"{API}/admin/apps", json={"apps": {"engage": False, "ai_tutor": False}}, headers=h
        )
        assert r.status_code == 200, r.text
    apps = {a["app_key"]: a["enabled"] for a in r.json()["apps"]}
    assert apps["engage"] is False and apps["ai_tutor"] is False and apps["paths"] is True
    assert audited[0] == ("ai.apps.updated", {"engage": False, "ai_tutor": False})
    r = await client.patch(f"{API}/admin/apps", json={"apps": {"nope": True}}, headers=h)
    assert r.status_code == 422
    assert await ai.ai_enabled(db, app_key="ai_tutor") is False


async def test_usage_summary(db, client, auth, make_principal, fake_ai) -> None:
    u = await make_user(db)
    h = await _admin(db, auth, make_principal, "analytics.read.platform")
    before = (await client.get(f"{API}/admin/ai-usage", headers=h)).json()["totals"]["calls"]
    await ai.generate_questions(db, user_id=u.id, spec=ai.QuestionGenSpec("mcq", 2, "topic", topic="Sorting"))
    await ai.tutor_reply(
        db,
        user_id=u.id,
        context_type="practice",
        context_id=uuid.uuid4(),
        mode="explain",
        question_md="Q",
        learner_input="help",
    )
    r = await client.get(f"{API}/admin/ai-usage", headers=h)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["totals"]["calls"] == before + 2 and b["totals"]["tokens_in"] > 0
    assert {"question_generation", "tutor"} <= {f["feature"] for f in b["by_feature"]}
    assert b["caps"]["monthly_call_cap"] > 0 and b["caps"]["monthly_token_cap"] > 0
    r = await client.get(f"{API}/admin/ai-usage?month=2001-01", headers=h)
    assert r.json()["totals"]["calls"] == 0 and r.json()["period_start"] == "2001-01-01"
    r = await client.get(f"{API}/admin/ai-usage?month=bad", headers=h)
    assert r.status_code == 422


async def test_me_enabled_apps_is_the_platform_set(db, client, auth, make_principal) -> None:
    admin = await _admin(db, auth, make_principal, "feature_flag.manage")
    learner = auth.login(make_principal(user_id=(await make_user(db)).id))
    r = await client.get(f"{API}/me/enabled-apps", headers=learner)
    assert r.status_code == 200, r.text
    assert r.json() == {"apps": dict.fromkeys(r.json()["apps"], True), "ai_enabled": True}
    await client.patch(f"{API}/admin/apps", json={"apps": {"engage": False}}, headers=admin)
    await client.patch(f"{API}/admin/ai-settings", json={"enabled": False}, headers=admin)
    b = (await client.get(f"{API}/me/enabled-apps", headers=learner)).json()
    assert b["ai_enabled"] is False
    assert (
        b["apps"]["engage"] is False and b["apps"]["ai_tutor"] is False and b["apps"]["assignments"] is True
    )


async def test_me_tutor_history_own_rows_only(db, client, auth, make_principal, fake_ai) -> None:
    a, b = await make_user(db), await make_user(db)
    ctx = uuid.uuid4()
    for u in (a, b):
        await ai.tutor_reply(
            db,
            user_id=u.id,
            context_type="assignment",
            context_id=ctx,
            mode="guide",
            question_md="Q",
            learner_input=f"from {u.id}",
        )
    h = auth.login(make_principal(user_id=a.id))
    r = await client.get(
        f"{API}/me/ai/tutor-history", params={"context_type": "assignment", "context_id": str(ctx)}, headers=h
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert [t["role"] for t in data] == ["learner", "tutor"] and data[0]["content"] == f"from {a.id}"
    r = await client.get(
        f"{API}/me/ai/tutor-history", params={"context_type": "nope", "context_id": str(ctx)}, headers=h
    )
    assert r.status_code in (400, 422)


async def test_rls_learner_sees_only_own_usage(db, fake_ai) -> None:
    from app.core.db import set_rls_context

    a, b = await make_user(db), await make_user(db)
    for u in (a, b):
        await ai.tutor_reply(
            db,
            user_id=u.id,
            context_type="practice",
            context_id=uuid.uuid4(),
            mode="guide",
            question_md="Q",
            learner_input="x",
        )
    await set_rls_context(db, user_id=str(a.id))
    rows = (await db.execute(select(AIUsage.user_id))).scalars().all()
    assert rows == [a.id]
    await system_context(db, "test.ai")


async def test_erasure_pseudonymises_usage_and_deletes_history(db, fake_ai) -> None:
    from app.modules.admin.privacy import erasure_providers

    u = await make_user(db)
    await ai.generate_path(db, user_id=u.id, spec=ai.PathGenSpec("Git", "beginner", "mixed", 5, 2))
    await ai.tutor_reply(
        db,
        user_id=u.id,
        context_type="practice",
        context_id=uuid.uuid4(),
        mode="guide",
        question_md="Q",
        learner_input="x",
    )
    await system_context(db, "test.ai")
    ids = [r.id for r in (await db.execute(select(AIUsage).where(AIUsage.user_id == u.id))).scalars()]
    assert erasure_providers()["ai"] is ai_router.erase_user
    out = await ai_router.erase_user(db, u.id)
    assert out == {"ai_usage_pseudonymised": 2, "ai_tutor_turns_deleted": 2}
    rows = (await db.execute(select(AIUsage).where(AIUsage.id.in_(ids)))).scalars().all()
    assert [r.user_id for r in rows] == [None, None] and rows[0].tokens_in > 0
    assert (await db.execute(select(TutorTurn).where(TutorTurn.user_id == u.id))).first() is None
