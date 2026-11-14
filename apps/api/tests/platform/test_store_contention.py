"""Store transaction runner: raw ABORTED / "Transaction lock timeout" from a read is retried;
exhaustion is the app's 409 contention problem (data-ops request)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from google.api_core import exceptions as gexc

from app.core.errors import ProblemError, install_error_handlers
from app.core.firestore.errors import TransactionContentionError
from app.core.firestore.store import ScopedStore


async def test_raw_lock_timeout_is_retried(fs_client: Any) -> None:
    store = ScopedStore.system("platformtest.contention", client=fs_client)
    calls = {"n": 0}

    async def fn(tx: Any) -> str:
        calls["n"] += 1
        await tx.raw_get("kv", "x")
        if calls["n"] == 1:
            raise gexc.Aborted("Transaction lock timeout")
        if calls["n"] == 2:
            raise gexc.Unknown("Transaction lock timeout while reading")
        tx.raw_set("kv", "x", {"v": b"1"})
        return "done"

    assert await store.run_transaction(fn) == "done"
    assert calls["n"] == 3


async def test_other_errors_are_not_retried(fs_client: Any) -> None:
    store = ScopedStore.system("platformtest.contention", client=fs_client)
    calls = {"n": 0}

    async def fn(tx: Any) -> None:
        calls["n"] += 1
        raise gexc.PermissionDenied("nope")

    with pytest.raises(gexc.PermissionDenied):
        await store.run_transaction(fn)
    assert calls["n"] == 1


async def test_exhaustion_is_a_409_conflict_problem(fs_client: Any) -> None:
    store = ScopedStore.system("platformtest.contention", client=fs_client)

    async def fn(tx: Any) -> None:
        raise gexc.Aborted("Transaction lock timeout")

    with pytest.raises(TransactionContentionError) as ei:
        await store.run_transaction(fn, max_attempts=3)
    assert isinstance(ei.value, ProblemError) and ei.value.status == 409 and ei.value.code == "conflict"

    app = FastAPI()
    install_error_handlers(app)

    @app.post("/x")
    async def x() -> None:
        await store.run_transaction(fn, max_attempts=2)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/x")
    assert r.status_code == 409 and r.json()["code"] == "conflict" and r.headers["retry-after"] == "1"


async def test_concurrent_read_modify_write_all_succeed(fs_client: Any) -> None:
    """4 concurrent transactions on one document (the data-ops restriction case) all commit."""
    store = ScopedStore.system("platformtest.contention", client=fs_client)

    async def bump(tx: Any) -> int:
        cur = await tx.raw_get("kv", "hot") or {"n": 0}
        await asyncio.sleep(0.05)
        tx.raw_set("kv", "hot", {"n": cur["n"] + 1})
        return int(cur["n"]) + 1

    got = await asyncio.gather(*(store.run_transaction(bump) for _ in range(4)))
    assert sorted(got) == [1, 2, 3, 4]
