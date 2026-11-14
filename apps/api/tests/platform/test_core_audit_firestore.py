"""core audit() on Firestore: atomic with the caller's Firestore transaction (TD_STORE_AUDIT)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app.core.audit import AuditActor, audit
from app.core.firestore.backend import reset_store_backends
from app.core.firestore.collections import physical_name
from app.core.firestore.store import ScopedStore
from app.modules.audit.store_specs import OUTBOX


@pytest.fixture
def audit_on_firestore(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("TD_STORE_AUDIT", "firestore")
    reset_store_backends()
    yield
    monkeypatch.delenv("TD_STORE_AUDIT")
    reset_store_backends()


async def _outbox(fs_client: Any) -> list[dict[str, Any]]:
    return [s.to_dict() async for s in fs_client.collection(physical_name(OUTBOX)).stream()]


async def test_audit_in_firestore_transaction_commits_with_it(
    fs_client: Any, audit_on_firestore: Any
) -> None:
    store = ScopedStore.system("platformtest.audit", client=fs_client)
    target = uuid.uuid4()

    async def ok(tx: Any) -> uuid.UUID:
        return await audit(
            tx, AuditActor.system("platformtest"), "platform.thing.done", "thing", target, reason="r"
        )

    aid = await store.run_transaction(ok)
    docs = await _outbox(fs_client)
    assert len(docs) == 1 and docs[0]["id"] == str(aid)
    rec = json.loads(docs[0]["record_json"])
    assert rec["action"] == "platform.thing.done" and rec["target_id"] == str(target)
    assert rec["actor_roles"] == ["system:platformtest"]

    async def rolled_back(tx: Any) -> None:
        await audit(tx, AuditActor.system("platformtest"), "platform.thing.failed", "thing", target)
        raise RuntimeError("business write failed")

    with pytest.raises(RuntimeError):
        await store.run_transaction(rolled_back)
    assert len(await _outbox(fs_client)) == 1  # nothing recorded for the rolled-back action


async def test_firestore_transaction_refused_while_audit_on_postgres(fs_client: Any) -> None:
    reset_store_backends()
    store = ScopedStore.system("platformtest.audit", client=fs_client)

    async def fn(tx: Any) -> None:
        await audit(tx, AuditActor.system("platformtest"), "platform.thing.done", "thing")

    with pytest.raises(TypeError):
        await store.run_transaction(fn)
    with pytest.raises(ValueError):
        await audit(None, AuditActor.system("x"), "Bad Action", "thing")
