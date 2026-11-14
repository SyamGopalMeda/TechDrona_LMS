"""P1: store-neutral outbox read API (``app.core.outbox.read_events``) on Firestore."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core import db, outbox
from app.core.firestore import core_store
from app.core.firestore.backend import reset_store_backends
from app.core.firestore.store import ScopedStore


async def test_read_events_filters_orders_and_pages(fs_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.firestore import client as client_mod

    monkeypatch.setenv("TD_STORE_CORE", "firestore")
    monkeypatch.setenv("DATABASE_URL", "")
    reset_store_backends()
    prev = client_mod._client
    client_mod.set_client(fs_client)
    try:
        store = ScopedStore.system("core.outbox_relay", client=fs_client)
        t0 = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
        ids = sorted(uuid.UUID(int=(0x0189 << 112) | i) for i in range(1, 7))
        org = uuid.uuid4()

        async def put(tx: Any) -> None:
            for i, eid in enumerate(ids):
                et = "platformtest.wanted" if i != 2 else "platformtest.other"
                ts = t0 + timedelta(seconds=0 if i < 3 else i)  # three share one timestamp
                tx.raw_create(
                    core_store.OUTBOX,
                    str(eid),
                    core_store.event_doc(eid, et, {"i": i, "l": [[i]]}, "t", uuid.uuid4(), org, ts),
                )

        await store.run_transaction(put)
        since = t0 - timedelta(minutes=1)
        recs = await outbox.read_events(
            db.NO_POSTGRES, since=since, event_types=["platformtest.wanted"], limit=3
        )
        assert [r.payload["i"] for r in recs] == [0, 1, 3]  # type filter, (occurred_at, id) order
        assert recs[0].organization_id == org and recs[0].payload["l"] == [[0]]
        assert recs[0].occurred_at.tzinfo is not None and recs[0].dispatched_at is None
        nxt = await outbox.read_events(
            db.NO_POSTGRES,
            since=since,
            event_types=["platformtest.wanted"],
            limit=10,
            after=(recs[-1].occurred_at, recs[-1].id),
        )
        assert [r.payload["i"] for r in nxt] == [4, 5]
        assert (
            await outbox.read_events(
                db.NO_POSTGRES, since=t0 + timedelta(seconds=5), event_types=["platformtest.wanted"]
            )
            == []
        )
    finally:
        client_mod.set_client(prev)
        reset_store_backends()


async def test_memory_tx_counts_as_no_session(fs_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The SQL engine's in-memory transaction has no Postgres behind it: ``read_events`` must not
    query Postgres from it even when a DATABASE_URL is configured (no ``postgres_enabled`` patch)."""
    from app.core.firestore import client as client_mod
    from app.core.firestore.sqlstore import MemoryTx

    assert db.no_session(MemoryTx()) and not db.no_sql_session(MemoryTx())
    assert db.no_session(None) and db.no_session(db.NO_POSTGRES)
    monkeypatch.setenv("TD_STORE_CORE", "firestore")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/x")
    reset_store_backends()
    prev = client_mod._client
    client_mod.set_client(fs_client)
    try:
        store = ScopedStore.system("core.outbox_relay", client=fs_client)
        eid = uuid.uuid4()
        t = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)

        async def put(tx: Any) -> None:
            tx.raw_create(
                core_store.OUTBOX,
                str(eid),
                core_store.event_doc(eid, "platformtest.mem", {}, "t", uuid.uuid4(), None, t),
            )

        await store.run_transaction(put)
        recs = await outbox.read_events(
            MemoryTx(), since=t - timedelta(minutes=1), event_types=["platformtest.mem"]
        )
        assert [r.id for r in recs] == [eid]
    finally:
        client_mod.set_client(prev)
        reset_store_backends()
