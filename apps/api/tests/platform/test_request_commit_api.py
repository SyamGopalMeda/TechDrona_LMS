"""Public buffer API (security pass 2, request 8): checkpoint / rollback_to / buffer_open."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from app.core import db, outbox, request_commit
from app.core.audit import AuditActor, audit
from app.core.firestore.backend import reset_store_backends
from app.core.firestore.collections import physical_name

NOPG = db.NO_POSTGRES


@pytest.fixture
def fs(fs_client: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    from app.core.firestore import client as client_mod

    monkeypatch.setenv("TD_STORE_AUDIT", "firestore")
    reset_store_backends()
    prev = client_mod._client
    client_mod.set_client(fs_client)
    yield fs_client
    client_mod.set_client(prev)
    reset_store_backends()


async def _emit(tag: str) -> uuid.UUID:
    return await outbox.emit_event(
        NOPG, "platformtest.thing_done", {"t": tag}, aggregate_type="t", aggregate_id=uuid.uuid4()
    )


async def _count(fs_client: Any, coll: str) -> int:
    return len([s async for s in fs_client.collection(physical_name(coll)).stream()])


async def test_buffer_open_commits_on_success(fs: Any) -> None:
    assert not request_commit.is_open()
    async with request_commit.buffer_open():
        assert request_commit.is_open()
        await audit(NOPG, AuditActor.system("platformtest"), "platform.thing.done", "thing")
        await _emit("a")
        assert await _count(fs, "outbox_events") == 0  # not before the commit point
    assert not request_commit.is_open()
    assert await _count(fs, "outbox_events") == 1 and await _count(fs, "audit_outbox") == 1


async def test_buffer_open_drops_on_error(fs: Any) -> None:
    with pytest.raises(RuntimeError):
        async with request_commit.buffer_open():
            await audit(NOPG, AuditActor.system("platformtest"), "platform.thing.done", "thing")
            await _emit("a")
            raise RuntimeError("job failed")
    assert await _count(fs, "outbox_events") == 0 and await _count(fs, "audit_outbox") == 0


async def test_checkpoint_rollback_and_nested_scope(fs: Any) -> None:
    async with request_commit.buffer_open():
        await _emit("keep")
        cp = request_commit.checkpoint()
        await _emit("drop")
        await audit(NOPG, AuditActor.system("platformtest"), "platform.thing.done", "thing")
        assert request_commit.rollback_to(cp) == 2
        with pytest.raises(ValueError):
            async with request_commit.buffer_open():  # nested = savepoint
                await _emit("inner-drop")
                raise ValueError
        async with request_commit.buffer_open():
            await _emit("inner-keep")
        assert [e.payload["t"] for e in outbox.pending_events()] == ["keep", "inner-keep"]
    assert await _count(fs, "outbox_events") == 2 and await _count(fs, "audit_outbox") == 0
