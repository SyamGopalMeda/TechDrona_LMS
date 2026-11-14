"""lms_edge.college_portal: /college-portal/* behind the LMS admin session (proxy.ts parity)."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest
from lms_edge import EdgeApp, college_portal, load_config
from lms_edge.cookies import pack

ORIGIN = "https://lms.example"
SECRET = "p" * 40
PORTAL = "http://portal.internal"


def _cfg() -> Any:
    return load_config(
        {
            "TD_CSRF_KEY": "k" * 40,
            "TD_SERVICE_TOKEN": "s" * 48,
            "TD_PUBLIC_BASE_URL": ORIGIN,
            "TD_COOKIE_SECURE": "true",
            "APP_ENV": "test",
        }
    )


class FakeApi:
    def __init__(self, grants: tuple[int, Any], me: tuple[int, Any] = (200, {})) -> None:
        self.answers = {"/api/v1/me/grants": grants, "/api/v1/me": me}
        self.calls: list[dict[str, str]] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await receive()
        self.calls.append({k.decode(): v.decode() for k, v in scope["headers"]} | {":path": scope["path"]})
        status, body = self.answers.get(scope["path"], (404, {}))
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": json.dumps(body).encode()})


class FakePortal:
    def __init__(
        self, status: int = 200, headers: dict[str, str] | None = None, body: bytes = b"<html>ok</html>"
    ) -> None:
        self.requests: list[httpx.Request] = []
        self.status, self.headers, self.body = status, headers or {"content-type": "text/html"}, body

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, headers=self.headers, content=self.body)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    college_portal.reset_state()
    monkeypatch.setenv("TD_COLLEGE_PORTAL_URL", PORTAL)
    monkeypatch.setenv("TD_COLLEGE_PORTAL_SECRET", SECRET)
    monkeypatch.setenv("TD_COLLEGE_PORTAL_ID_TOKEN", "false")


def _wire(monkeypatch: pytest.MonkeyPatch, portal: FakePortal) -> None:
    monkeypatch.setattr(
        college_portal, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(portal))
    )


def _client(api: FakeApi) -> httpx.AsyncClient:
    app = EdgeApp(api, _cfg())  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)


def _session_cookie() -> dict[str, str]:
    exp = time.time() + 3600
    return {"cookie": "__session=" + pack({"session": ("SESS", exp), "device": ("DEV", exp)})}


ADMIN = (200, {"portals": ["/admin"], "data": [{"role_key": "super_admin"}]})
ME = (200, {"profile": {"display_name": "Asha Admin"}, "user": {"email": "asha@example.com"}})


async def test_entry_redirects_to_index() -> None:
    async with _client(FakeApi(ADMIN)) as c:
        r = await c.get("/college-portal/")
    assert r.status_code == 308 and r.headers["location"] == "/college-portal/index.html"


async def test_no_session_navigation_redirects_to_login(monkeypatch: pytest.MonkeyPatch) -> None:
    portal = FakePortal()
    _wire(monkeypatch, portal)
    async with _client(FakeApi(ADMIN)) as c:
        r = await c.get("/college-portal/index.html", headers={"sec-fetch-dest": "document"})
        r2 = await c.get("/college-portal/api/colleges", headers={"accept": "application/json"})
        r3 = await c.get("/college-portal/index.html", headers={"sec-fetch-dest": "iframe"})
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2Fadmin%2Fcollege-data"
    assert r2.status_code == 401 and r2.json()["code"] == "auth_required"
    assert r3.status_code == 401 and "Signed out" in r3.text
    assert portal.requests == []


async def test_non_admin_is_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    portal = FakePortal()
    _wire(monkeypatch, portal)
    async with _client(FakeApi((200, {"portals": ["/app"], "data": [{"role_key": "student"}]}), ME)) as c:
        r = await c.get("/college-portal/api/colleges", headers=_session_cookie())
    assert r.status_code == 403 and portal.requests == []


async def test_expired_session_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, FakePortal())
    async with _client(FakeApi((401, {"code": "session_expired"}))) as c:
        r = await c.get("/college-portal/api/colleges", headers=_session_cookie())
    assert r.status_code == 401


async def test_admin_is_forwarded_with_secret_and_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    portal = FakePortal(headers={"content-type": "text/html", "set-cookie": "x=1", "server": "node"})
    _wire(monkeypatch, portal)
    api = FakeApi(ADMIN, ME)
    async with _client(api) as c:
        r = await c.get(
            "/college-portal/index.html?x=1",
            headers={
                **_session_cookie(),
                "sec-fetch-dest": "document",
                "x-td-proxy-role": "viewer",
                "authorization": "x",
            },
        )
    assert r.status_code == 200 and r.text == "<html>ok</html>"
    assert "set-cookie" not in r.headers and "server" not in r.headers
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    (req,) = portal.requests
    assert str(req.url) == f"{PORTAL}/index.html?x=1"
    assert req.headers["x-td-proxy-secret"] == SECRET
    assert req.headers["x-td-proxy-role"] == "editor"
    assert req.headers["x-td-proxy-user"] == "Asha%20Admin%20(asha%40example.com)"
    assert "cookie" not in req.headers and "authorization" not in req.headers
    grants_call = next(x for x in api.calls if x[":path"] == "/api/v1/me/grants")
    assert grants_call["x-td-session"] == "SESS" and grants_call["x-td-device"] == "DEV"
    assert grants_call["x-td-activity"] == "navigation"


async def test_auth_cache_for_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, FakePortal(headers={"content-type": "text/css"}, body=b"a{}"))
    api = FakeApi(ADMIN, ME)
    async with _client(api) as c:
        for _ in range(3):
            r = await c.get("/college-portal/css/app.css", headers=_session_cookie())
            assert r.status_code == 200 and r.headers["cache-control"] == "private, no-cache"
    assert sum(1 for x in api.calls if x[":path"] == "/api/v1/me/grants") == 1


async def test_cross_origin_write_blocked_and_wrong_secret_is_502(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, FakePortal(status=401, headers={"content-type": "application/json"}, body=b"{}"))
    async with _client(FakeApi(ADMIN, ME)) as c:
        r = await c.post(
            "/college-portal/api/calls",
            headers={**_session_cookie(), "sec-fetch-site": "cross-site"},
            json={},
        )
        r2 = await c.post(
            "/college-portal/api/calls", headers={**_session_cookie(), "origin": ORIGIN}, json={}
        )
    assert r.status_code == 403 and r.json()["code"] == "cross_origin"
    assert r2.status_code == 502 and r2.json()["code"] == "portal_misconfigured"


async def test_bad_paths_and_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _client(FakeApi(ADMIN, ME)) as c:
        assert (await c.get("/college-portal/a/%2e%2e/b")).status_code == 400
        monkeypatch.delenv("TD_COLLEGE_PORTAL_SECRET")
        assert (await c.get("/college-portal/index.html", headers=_session_cookie())).status_code == 503


def test_rewrite_location() -> None:
    assert college_portal.rewrite_location("/index.html", PORTAL) == "/college-portal/index.html"
    assert college_portal.rewrite_location("https://evil.example/x", PORTAL) is None
