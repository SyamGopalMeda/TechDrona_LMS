"""Firestore settings slice (P2, docs/firebase/p2.md): backfill/verify, invariants and
store-level authorization for feature flags, policy settings and the AI platform settings.

The HTTP-level parity (same responses on both stores) is covered by the existing admin/ai tests
run through the ``admin_backend`` / ``ai_backend`` matrix fixtures."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest

from app.core.firestore.errors import StoreAccessDeniedError
from app.core.firestore.repository import assert_repository_scoped
from app.core.principal import Principal, RoleGrant
from app.modules.admin import policy as pol
from app.modules.identity import clock
from tests.firestore.matrix import activate_firestore
from tests.security.helpers import set_policy, staff

KEY = "devices.student.max_trusted"


@pytest.fixture
async def fs(request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    from app.modules.admin import flags

    flags.invalidate()
    restore = await activate_firestore(request, db, monkeypatch, ("admin", "ai"))
    try:
        yield
    finally:
        await restore()
        flags.invalidate()


def test_repositories_are_principal_or_platform_scoped() -> None:
    from app.modules.admin.repo_firestore import AdminSettingsRepo
    from app.modules.ai.repo_firestore import AISettingsRepo

    assert_repository_scoped(AdminSettingsRepo)
    assert_repository_scoped(AISettingsRepo)


async def test_backfill_verifies_and_verify_detects_drift(db: Any, fs: None) -> None:
    from app.core.firestore.backfill import verify
    from app.core.firestore.store import ScopedStore

    for module in ("admin", "ai"):
        reports = await verify(db, module)
        assert reports, module
        for r in reports:
            assert r.ok, r.as_dict()
    flags_rep = next(r for r in await verify(db, "admin") if r.collection == "feature_flags")
    assert flags_rep.pg_rows == flags_rep.fs_docs > 0

    sysstore = ScopedStore.system("test.drift")
    await sysstore.update("feature_flags", "platform.maintenance_mode", {"is_enabled": True})
    rep = next(r for r in await verify(db, "admin") if r.collection == "feature_flags")
    assert rep.mismatched == ["platform.maintenance_mode"] and rep.pg_checksum != rep.fs_checksum
    await sysstore.create("feature_flags", {"flag_key": "x.extra"}, doc_id="x.extra")
    rep = next(r for r in await verify(db, "admin") if r.collection == "feature_flags")
    assert rep.extra == ["x.extra"]


async def test_policy_versions_unique_and_one_active_under_concurrency(db: Any, fs: None) -> None:
    actor = (await staff(db)).id

    async def write(v: int) -> Any:
        return await pol.write_setting(
            db, key=KEY, scope_type="platform", scope_id=None, value=v, changed_by=actor, change_reason="race"
        )

    rows = await asyncio.gather(*(write(v) for v in (2, 3, 4, 5)))
    vs = sorted(r.version for r in rows)
    assert vs == list(range(vs[0], vs[0] + 4))  # distinct and gap-free
    hist = await pol.history_rows(db, KEY)
    assert [r.version for r in hist] == sorted((r.version for r in hist), reverse=True)  # newest first
    assert sum(r.is_active for r in hist) == 1
    active = await pol.active_row(db, KEY, "platform", None)
    assert active is not None and active.version == vs[-1]
    assert await pol.get_value(db, KEY) == active.value


async def test_resolution_precedence_and_user_exception_window(db: Any, fs: None) -> None:
    actor = (await staff(db)).id
    uid, plan = uuid.uuid4(), uuid.uuid4()
    await set_policy(db, KEY, 5)
    await set_policy(db, KEY, 2, "plan", plan)
    assert await pol.get_value(db, KEY, user_id=uid) == 5
    assert await pol.get_value(db, KEY, user_id=uid, plan_id=plan) == 2
    now = clock.now()
    await pol.write_setting(
        db,
        key=KEY,
        scope_type="user",
        scope_id=uid,
        value=1,
        changed_by=actor,
        change_reason="case decision",
        effective_from=now - timedelta(days=1),
        expires_at=now - timedelta(minutes=1),
    )
    assert await pol.get_value(db, KEY, user_id=uid, plan_id=plan) == 2  # expired exception ignored
    assert await pol.active_user_exception_count(db, uid, now) == 0
    await pol.write_setting(
        db,
        key=KEY,
        scope_type="user",
        scope_id=uid,
        value=1,
        changed_by=actor,
        change_reason="case decision",
        effective_from=now - timedelta(days=1),
        expires_at=now + timedelta(days=7),
    )
    assert await pol.get_value(db, KEY, user_id=uid, plan_id=plan) == 1  # user > plan > platform
    assert await pol.active_user_exception_count(db, uid, now) == 1
    # Locked keys ignore every override scope.
    assert await pol.get_value(db, "risk.network_points_cap", user_id=uid, plan_id=plan) == 20


async def test_store_layer_refuses_principals_without_the_permission(db: Any, fs: None) -> None:
    from app.core.firestore.store import ScopedStore
    from app.modules.admin.repo_firestore import AdminSettingsRepo
    from app.modules.ai.repo_firestore import AISettingsRepo

    cm, sa = await staff(db, "content_manager"), await staff(db, "super_admin")
    weak = Principal(
        user_id=cm.id, session_id=uuid.uuid4(), grants=(RoleGrant("content_manager", "platform"),)
    )
    strong = Principal(user_id=sa.id, session_id=uuid.uuid4(), grants=(RoleGrant("super_admin", "platform"),))
    with pytest.raises(StoreAccessDeniedError):
        await AdminSettingsRepo(ScopedStore(weak)).list_flags()
    with pytest.raises(StoreAccessDeniedError):
        await AdminSettingsRepo(ScopedStore(weak)).patch_flag(
            "platform.maintenance_mode", {"is_enabled": True}, cm.id
        )
    with pytest.raises(StoreAccessDeniedError):
        await AISettingsRepo(ScopedStore(weak)).write_settings({"enabled": False}, cm.id)
    assert any(
        f.flag_key == "platform.maintenance_mode"
        for f in await AdminSettingsRepo(ScopedStore(strong)).list_flags()
    )
    before, after = await AdminSettingsRepo(ScopedStore(strong)).patch_flag(
        "platform.maintenance_mode", {"rollout_percent": 50}, sa.id
    )
    assert before.rollout_percent == 0 and after.rollout_percent == 50 and after.updated_by == sa.id


async def test_ai_settings_and_apps_singletons(db: Any, fs: None) -> None:
    from app.modules.ai import store

    by = (await staff(db)).id
    assert (await store.system_settings(db)).per_activity_default_cap == 20
    await store.write_settings(db, {"per_activity_default_cap": 4}, by)
    await store.write_apps(db, {"engage": False}, by)
    await store.write_apps(db, {"paths": False}, by)  # merges, does not replace
    assert (await store.system_settings(db)).per_activity_default_cap == 4
    apps = await store.system_apps(db)
    assert apps["engage"] is False and apps["paths"] is False and apps["assignments"] is True
    assert set(apps) == set(store.APPS)


def test_composite_indexes_for_p2_queries_are_declared() -> None:
    """The emulator does not enforce indexes; production does. Keep the P2 queries covered."""
    import json
    from pathlib import Path

    spec = json.loads((Path(__file__).resolve().parents[4] / "firestore.indexes.json").read_text())
    declared = {
        (i["collectionGroup"].removeprefix("lms_"), tuple(f["fieldPath"] for f in i["fields"]))
        for i in spec["indexes"]
    }
    assert ("policy_settings", ("setting_key", "created_at")) in declared  # history, newest first
    assert ("courses", ("status", "visibility", "organization_id", "published_at")) in declared
    assert len(spec["indexes"]) < 200  # project composite-index limit
