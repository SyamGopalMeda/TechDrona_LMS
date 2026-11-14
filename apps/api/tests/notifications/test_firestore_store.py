"""Notifications on Firestore (P2b, docs/firebase/p2.md): backfill/verify, owner isolation (RLS O),
the dedupe invariant under concurrency, TTL stamping, repository scope lint and index declarations.

HTTP-level parity is covered by the existing notification tests run through the
``notifications_backend`` matrix fixture."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from app.core.db import set_rls_context, system_context
from app.core.firestore.errors import StoreAccessDeniedError
from app.core.firestore.repository import assert_repository_scoped
from app.core.principal import Principal
from app.modules.notifications.service import notifications_for_user, notify
from tests.firestore.matrix import activate_firestore
from tests.identity.factory import make_user


@pytest.fixture
async def fs(request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    restore = await activate_firestore(request, db, monkeypatch, ("notifications",))
    try:
        yield
    finally:
        await restore()


def _principal(user_id: uuid.UUID) -> Principal:
    return Principal(user_id=user_id, session_id=uuid.uuid4(), grants=())


def test_repository_is_principal_or_platform_scoped() -> None:
    from app.modules.notifications.repo_firestore import NotificationRepo

    assert_repository_scoped(NotificationRepo)


async def test_backfill_from_postgres_verifies_clean(
    request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.firestore.backfill import verify

    u = await make_user(db)
    await system_context(db, "test.backfill")
    await notify(db, u.id, "a", category="system", data={"k": [1, 2]})
    await notify(db, u.id, "b", category="learning", dedupe_key="once", channels=("in_app", "email"))
    restore = await activate_firestore(request, db, monkeypatch, ("notifications",))  # backfills
    try:
        reports = {r.collection: r for r in await verify(db, "notifications")}
        assert set(reports) == {"notifications", "notification_dedupe"}
        for r in reports.values():
            assert r.ok, r.as_dict()
        assert reports["notifications"].fs_docs >= 2 and reports["notification_dedupe"].fs_docs >= 1
        # The dedupe guard came across: the same key is still refused after the cutover.
        assert await notify(db, u.id, "b", category="learning", dedupe_key="once") is None
        rows = await notifications_for_user(db, u.id)
        assert [r.template_key for r in rows] == ["a", "b"] and rows[0].data == {"k": [1, 2]}
    finally:
        await restore()


async def test_owner_isolation_and_rls_o_on_writes(db: Any, fs: None) -> None:
    from app.core.firestore.store import ScopedStore
    from app.modules.notifications.repo_firestore import NotificationRepo

    a, b = await make_user(db), await make_user(db)
    await system_context(db, "test")
    nb = await notify(db, b.id, "private", category="system")
    assert nb is not None
    repo_a = NotificationRepo(ScopedStore(_principal(a.id)))
    with pytest.raises(StoreAccessDeniedError):
        await repo_a.inbox(b.id, unread_only=False, cursor=None, limit=10)
    with pytest.raises(StoreAccessDeniedError):
        await repo_a.unread_count(b.id)
    assert await repo_a.mark_read(a.id, nb, _now()) is None  # invisible, not an oracle
    assert await repo_a.mark_all_read(a.id, _now()) == 0
    assert (await NotificationRepo(ScopedStore(_principal(b.id))).unread_count(b.id)) == 1
    # The caller's Postgres context decides, as RLS O: own rows yes, someone else's no.
    await set_rls_context(db, user_id=str(a.id))
    assert await notify(db, a.id, "self", category="system") is not None
    with pytest.raises(StoreAccessDeniedError):
        await notify(db, b.id, "planted", category="system")


async def test_dedupe_is_one_row_under_concurrency_and_ttl_is_stamped(db: Any, fs: None) -> None:
    from app.core.firestore.store import ScopedStore
    from app.modules.notifications.repo_firestore import system_repo
    from app.modules.notifications.store_specs import RETENTION

    u = await make_user(db)
    repo = system_repo("test.notify")

    async def one() -> bool:
        return await repo.create(u.id, {**_doc(), "dedupe_key": "evt-1"})

    results = await asyncio.gather(*(one() for _ in range(4)))
    assert sorted(results) == [False, False, False, True]
    (row,) = await repo.list_for_user(u.id)
    stored = await ScopedStore.system("test.read").get("notifications", str(row.id))
    assert stored is not None and stored["expire_at"] - stored["created_at"] == RETENTION
    assert await repo.erase_user(u.id) == 1
    assert await repo.list_for_user(u.id) == []
    assert await repo.create(u.id, {**_doc(), "dedupe_key": "evt-1"})  # erasure freed the key


def test_composite_indexes_and_ttl_are_declared() -> None:
    spec = json.loads((Path(__file__).resolve().parents[4] / "firestore.indexes.json").read_text())
    declared = {
        (i["collectionGroup"].removeprefix("lms_"), tuple(f["fieldPath"] for f in i["fields"]))
        for i in spec["indexes"]
    }
    assert ("notifications", ("user_id", "channels", "id")) in declared  # inbox
    assert ("notifications", ("user_id", "channels", "read_at", "id")) in declared  # unread inbox
    assert ("notifications", ("user_id", "read_at", "id")) in declared  # read-all
    assert ("notifications", ("template_key", "data.batch_id", "created_at")) in declared  # cap
    ttl = {o["collectionGroup"].removeprefix("lms_") for o in spec["fieldOverrides"] if o.get("ttl")}
    assert {"notifications", "notification_dedupe"} <= ttl


def _now() -> Any:
    from app.core.time import utcnow

    return utcnow()


def _doc() -> dict[str, Any]:
    from app.core.ids import uuid7

    return {
        "id": str(uuid7()),
        "template_key": "x",
        "category": "system",
        "channels": ["in_app"],
        "data": {},
        "priority": "normal",
        "status": "queued",
        "read_at": None,
    }
