"""``analytics.consumer.consume_outbox`` reads the outbox only through
``app.core.outbox.read_events`` (no SQL on ``outbox_events``), emulator only, no Postgres.

The fixture puts 5 handled events and 1 unhandled event in the Firestore outbox and marks one
handled event consumed beforehand. The expected batch is computed from the fixture: handled, not
yet consumed, ordered ``(occurred_at, id)``, at most ``limit``. ``limit=2`` forces the keyset paging
past the consumed event (the old ``NOT EXISTS ... LIMIT`` semantics).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.firestore.sqlstore import MemoryTx
from app.core.ids import uuid7

FS_MODULES = ("analytics", "core")
pytestmark = pytest.mark.usefixtures("fs_env")


async def test_consume_outbox_pages_read_events_and_skips_consumed(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.firestore.core_store import emit_event_firestore
    from app.core.outbox import read_events
    from app.modules.analytics import consumer, fs_raw

    handled = consumer.HANDLED_TYPES[0]
    ids: list[uuid.UUID] = []
    for i in range(5):
        ids.append(
            await emit_event_firestore(
                handled, {"user_id": str(uuid7()), "n": i}, aggregate_type="x", aggregate_id=uuid7()
            )
        )
    await emit_event_firestore("unrelated.thing_happened", {}, aggregate_type="x", aggregate_id=uuid7())
    await fs_raw.mark_consumed(ids[1], handled)  # already consumed before this run

    seen: list[uuid.UUID] = []

    async def fake_handle(session: Any, *, event_id: uuid.UUID, **kw: Any) -> bool:
        seen.append(event_id)
        return True

    monkeypatch.setattr(consumer, "handle_domain_event", fake_handle)
    s = MemoryTx()  # the no-Postgres request/job transaction (core no_session() counts it)

    # the order read_events gives, minus the consumed one (computed from the fixture)
    from datetime import UTC, datetime

    ordered = [
        r.id for r in await read_events(s, since=datetime(1970, 1, 1, tzinfo=UTC), event_types=[handled])
    ]
    expect = [i for i in ordered if i != ids[1]]
    assert sorted(ordered, key=str) == sorted(ids, key=str)

    first = await consumer.consume_outbox(s, limit=2)
    assert first == {"applied": 2, "skipped": 0, "seen": 2} and seen == expect[:2]
    second = await consumer.consume_outbox(s, limit=2)
    assert second["seen"] == 2 and seen == expect[:4]
    third = await consumer.consume_outbox(s, limit=2)
    assert third["seen"] == 0  # every handled event consumed; the unhandled one is never read
    assert all([await fs_raw.is_consumed(i) for i in ids])
