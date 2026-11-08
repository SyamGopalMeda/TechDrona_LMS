"""B1 / B4: transient capacity and client disconnects are not 500s.

* A DB pool checkout timeout (``QueuePool limit ... reached``) or a Postgres "too many
  connections" refusal → ``503 service_unavailable`` problem+json with ``Retry-After``.
* A client that disconnects while its body is read (analytics beacon on navigation) → handled,
  logged at info as ``client_disconnected`` with status 499, never ``unhandled_exception``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import exc as sa_exc
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import make_engine
from app.core.errors import CLIENT_CLOSED_REQUEST, install_error_handlers, is_db_capacity_error
from app.core.middleware import RequestContextMiddleware

PROBLEM = "application/problem+json"


class TooManyConnectionsError(Exception):
    """Stand-in with asyncpg's class name (matched by name)."""


def _app(engine: AsyncEngine | None = None) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/pool-timeout")
    async def pool_timeout() -> None:
        raise sa_exc.TimeoutError("QueuePool limit of size 5 overflow 2 reached, connection timed out")

    @app.get("/too-many")
    async def too_many() -> None:
        raise sa_exc.DBAPIError("connect", None, TooManyConnectionsError("sorry, too many clients"))

    @app.get("/other-db-error")
    async def other_db_error() -> None:
        raise sa_exc.IntegrityError("insert", None, Exception("duplicate key"))

    @app.get("/real-pool")
    async def real_pool() -> dict[str, int]:
        assert engine is not None
        async with engine.connect() as conn:
            return {"one": (await conn.execute(text("SELECT 1"))).scalar_one()}

    @app.post("/ingest")
    async def ingest(request: Request) -> dict[str, int]:
        return {"bytes": len(await request.body())}

    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.get(path)


def _assert_busy(resp: httpx.Response) -> None:
    assert resp.status_code == 503, resp.text
    assert resp.headers["content-type"].startswith(PROBLEM)
    assert resp.headers["retry-after"] == "2"
    body = resp.json()
    assert body["code"] == "service_unavailable"
    assert body["request_id"] == resp.headers["x-request-id"]
    assert "QueuePool" not in resp.text and "too many" not in resp.text


def test_capacity_classifier() -> None:
    assert is_db_capacity_error(sa_exc.TimeoutError("QueuePool limit"))
    assert is_db_capacity_error(sa_exc.DBAPIError("x", None, TooManyConnectionsError()))
    assert not is_db_capacity_error(sa_exc.IntegrityError("x", None, Exception()))
    assert not is_db_capacity_error(RuntimeError("boom"))


async def test_pool_timeout_is_503_with_retry_after() -> None:
    _assert_busy(await _get(_app(), "/pool-timeout"))


async def test_too_many_connections_is_503() -> None:
    _assert_busy(await _get(_app(), "/too-many"))


async def test_other_db_errors_stay_500() -> None:
    resp = await _get(_app(), "/other-db-error")
    assert resp.status_code == 500
    assert resp.json()["code"] == "internal_error"
    assert "duplicate key" not in resp.text


async def test_real_pool_exhaustion_is_503(migrated_database: Any) -> None:
    """A real engine with one connection and a short checkout timeout, the one connection held."""
    engine = make_engine(pool_size=1, max_overflow=0, pool_timeout=0.2)
    app = _app(engine)
    try:
        async with engine.connect() as held:
            await held.execute(text("SELECT 1"))
            _assert_busy(await _get(app, "/real-pool"))
        ok = await _get(app, "/real-pool")  # released → served again
        assert ok.status_code == 200 and ok.json() == {"one": 1}
    finally:
        await engine.dispose()


async def test_client_disconnect_during_body_read_is_not_a_500(caplog: pytest.LogCaptureFixture) -> None:
    app = _app()
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/ingest",
        "raw_path": b"/ingest",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"t"), (b"content-type", b"application/json"), (b"content-length", b"10")],
        "client": ("127.0.0.1", 5000),
        "server": ("t", 80),
    }
    with caplog.at_level(logging.INFO):
        await app(scope, receive, send)  # must not raise
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == CLIENT_CLOSED_REQUEST
    assert "unhandled_exception" not in caplog.text


async def test_pool_settings_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    for k, v in {
        "DB_POOL_SIZE": "7",
        "DB_MAX_OVERFLOW": "3",
        "DB_POOL_TIMEOUT_SECONDS": "4",
        "DB_POOL_PRE_PING": "false",
        "DB_POOL_RECYCLE_SECONDS": "600",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    try:
        engine = make_engine("postgresql+asyncpg://u:p@localhost:1/x")
        pool = engine.sync_engine.pool
        assert (pool.size(), pool._max_overflow, pool._timeout) == (7, 3, 4)  # type: ignore[attr-defined]
        assert pool._pre_ping is False and pool._recycle == 600  # type: ignore[attr-defined]
        await engine.dispose()
    finally:
        get_settings.cache_clear()
