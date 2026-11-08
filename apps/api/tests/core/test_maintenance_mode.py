"""ADM-17: ``platform.maintenance_mode`` blocks writes in core middleware (w3be).

The middleware is exercised on a minimal ASGI app with the flag reader stubbed, so the test
never flips the shared ``feature_flags`` row.
"""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.middleware import MaintenanceMiddleware


async def _ok(_request):  # type: ignore[no-untyped-def]
    return JSONResponse({"ok": True})


def _client(monkeypatch: pytest.MonkeyPatch, *, on: bool | Exception) -> httpx.AsyncClient:
    calls: list[str] = []

    async def fake(key: str, **_kw: object) -> bool:
        calls.append(key)
        if isinstance(on, Exception):
            raise on
        return on

    monkeypatch.setattr("app.modules.admin.flags.cached_flag_enabled", fake)
    paths = ["/api/v1/orders", "/api/v1/admin/break-glass", "/api/v1/auth/login", "/api/v1/webhooks/razorpay"]
    app = Starlette(routes=[Route(p, _ok, methods=["GET", "POST"]) for p in [*paths, "/healthz"]])
    wrapped = MaintenanceMiddleware(app, api_prefix="/api/v1")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://t")


async def test_writes_blocked_with_503_when_flag_on(monkeypatch) -> None:
    async with _client(monkeypatch, on=True) as c:
        r = await c.post("/api/v1/orders", json={})
        assert r.status_code == 503
        assert r.json()["code"] == "maintenance" and r.headers["Retry-After"] == "300"
        # reads keep working
        assert (await c.get("/api/v1/orders")).status_code == 200


async def test_admin_break_glass_auth_and_webhooks_still_work(monkeypatch) -> None:
    async with _client(monkeypatch, on=True) as c:
        for p in ("/api/v1/admin/break-glass", "/api/v1/auth/login", "/api/v1/webhooks/razorpay", "/healthz"):
            assert (await c.post(p, json={})).status_code == 200, p


async def test_writes_allowed_when_flag_off_or_unreadable(monkeypatch) -> None:
    async with _client(monkeypatch, on=False) as c:
        assert (await c.post("/api/v1/orders", json={})).status_code == 200
    async with _client(monkeypatch, on=ConnectionError("db down")) as c:
        assert (await c.post("/api/v1/orders", json={})).status_code == 200
