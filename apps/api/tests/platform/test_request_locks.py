"""Per-request Firestore locks (pg_advisory_xact_lock replacement), on the emulator."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core import request_locks
from app.core.errors import ProblemError, install_error_handlers
from app.core.firestore.store import ScopedStore
from app.core.middleware import RequestContextMiddleware


async def test_lock_serialises_and_is_released_at_scope_end(fs_client: Any) -> None:
    store = ScopedStore.system("core.request_lock", client=fs_client)
    order: list[str] = []

    async def worker(name: str, hold: float) -> None:
        async with request_locks.scope(store=store):
            await request_locks.acquire("sess:u1", wait_s=5)
            await request_locks.acquire("sess:u1")  # re-entrant
            order.append(f"{name}+")
            await asyncio.sleep(hold)
            order.append(f"{name}-")

    await asyncio.gather(worker("a", 0.3), worker("b", 0.0))
    assert order in (["a+", "a-", "b+", "b-"], ["b+", "b-", "a+", "a-"])
    async with request_locks.scope(store=store):  # free again
        await request_locks.acquire("sess:u1", wait_s=0.5)


async def test_wait_timeout_is_503(fs_client: Any) -> None:
    store = ScopedStore.system("core.request_lock", client=fs_client)
    async with request_locks.scope(store=store):
        await request_locks.acquire("sess:u2")
        async with request_locks.scope(store=store):
            with pytest.raises(ProblemError) as ei:
                await request_locks.acquire("sess:u2", wait_s=0.3)
    assert ei.value.code == "service_unavailable" and ei.value.headers["Retry-After"] == "1"


async def test_acquire_needs_a_scope() -> None:
    with pytest.raises(RuntimeError):
        await request_locks.acquire("x")


async def test_middleware_releases_after_the_request(fs_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ScopedStore.system("core.request_lock", client=fs_client)
    monkeypatch.setattr(request_locks, "_store", lambda: store)
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    @app.post("/lock")
    async def lock() -> dict[str, Any]:
        await request_locks.acquire("sess:u3")
        return {"held": list(request_locks.held_keys())}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.post("/lock")
        r2 = await c.post("/lock")  # would time out (10 s) if the first lease leaked
    assert r1.json() == r2.json() == {"held": ["sess:u3"]}
    snap = await fs_client.collection("lms_locks").document("sess:u3").get()
    assert not snap.exists
