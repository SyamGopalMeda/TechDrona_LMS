"""lms_edge (functions-lms): Next.js BFF parity in front of the API, cookies packed in __session."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest
from lms_edge import EdgeApp, csrf, load_config
from lms_edge.cookies import CookieJar, pack, parse_cookie_header, unpack

KEY = "k" * 40
TOKEN = "s" * 48
ORIGIN = "https://lms.example"


def _cfg(**over: str) -> Any:
    env = {
        "TD_CSRF_KEY": KEY,
        "TD_SERVICE_TOKEN": TOKEN,
        "TD_PUBLIC_BASE_URL": ORIGIN,
        "TD_COOKIE_SECURE": "true",
        "TD_TRUSTED_PROXY_HOPS": "1",
        "TD_ADMISSIONS_ALLOWED_ORIGINS": "https://site.example",
        "APP_ENV": "test",
    }
    env.update(over)
    return load_config(env)


class FakeApi:
    """Records what the edge sends upstream; answers per path."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: dict[str, tuple[int, list[tuple[str, str]], bytes]] = {}

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        body = b""
        while True:
            m = await receive()
            body += m.get("body", b"")
            if not m.get("more_body"):
                break
        headers = {k.decode(): v.decode() for k, v in scope["headers"]}
        self.requests.append(
            {
                "path": scope["path"],
                "method": scope["method"],
                "headers": headers,
                "body": body,
                "query": scope["query_string"],
            }
        )
        status, hdrs, out = self.responses.get(
            scope["path"], (200, [("content-type", "application/json")], b'{"ok":true}')
        )
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(k.encode(), v.encode()) for k, v in hdrs],
            }
        )
        await send({"type": "http.response.body", "body": out})


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


def client(api: FakeApi, **cfg: str) -> httpx.AsyncClient:
    app = EdgeApp(api, _cfg(**cfg))  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)


def set_cookies(r: httpx.Response) -> dict[str, str]:
    out = {}
    for c in r.headers.get_list("set-cookie"):
        name = c.split("=", 1)[0]
        out[name] = c
    return out


def cookie_value(sc: str) -> str:
    return sc.split(";", 1)[0].split("=", 1)[1]


# --------------------------------------------------------------------------- CSRF algorithm


def test_csrf_token_matches_the_typescript_algorithm() -> None:
    tok = csrf.mint(KEY, "SESSION")
    v, nonce, sig = tok.split(".")
    expected = (
        base64.urlsafe_b64encode(
            hmac.new(
                KEY.encode(),
                f"td-csrf|v1|s:{hashlib.sha256(b'SESSION').hexdigest()}|{nonce}".encode(),
                hashlib.sha256,
            ).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    assert v == "v1" and sig == expected
    assert csrf.verify([KEY], tok, "SESSION")
    assert not csrf.verify([KEY], tok, "OTHER")
    assert not csrf.verify(["x" * 40], tok, "SESSION")
    assert csrf.verify(["x" * 40, KEY], tok, "SESSION")  # previous-key rotation
    anon = csrf.mint(KEY, None)
    assert csrf.check_double_submit([KEY], anon, anon, None)
    assert not csrf.check_double_submit([KEY], anon, anon + "x", None)


# --------------------------------------------------------------------------- __session packing


def test_pack_roundtrip_and_expiry() -> None:
    packed = pack({"session": ("S", 2000.0), "device": ("D", 9000.0), "csrf": ("C", None)})
    assert unpack(packed, 1000.0) == {"session": ("S", 2000.0), "device": ("D", 9000.0), "csrf": ("C", None)}
    assert unpack(packed, 3000.0) == {"device": ("D", 9000.0), "csrf": ("C", None)}
    assert unpack("garbage", 0) == {} and unpack("v1.!!!", 0) == {}


def test_jar_max_age_is_longest_part() -> None:
    from lms_edge.cookies import ParsedSetCookie

    jar = CookieJar.from_header(_cfg(), None, now=1000.0)
    jar.set_from_upstream("session", ParsedSetCookie("__Host-td_session", "S", max_age=3600))
    jar.set_from_upstream("device", ParsedSetCookie("__Host-td_device", "D", max_age=34_560_000))
    hdrs = jar.set_cookie_headers()
    assert len(hdrs) == 1 and hdrs[0].startswith("__session=v1.")
    assert (
        "Max-Age=34560000" in hdrs[0]
        and "HttpOnly" in hdrs[0]
        and "Secure" in hdrs[0]
        and "SameSite=Lax" in hdrs[0]
    )


# --------------------------------------------------------------------------- bootstrap + proxy


async def test_csrf_bootstrap_and_reissue(api: FakeApi) -> None:
    async with client(api) as c:
        r = await c.get("/api/v1/_bff/csrf")
        assert (
            r.status_code == 204
            and r.headers["cache-control"] == "private, no-store"
            and "x-request-id" in r.headers
        )
        sc = set_cookies(r)
        visible = sc["__Host-td_csrf"]
        assert "HttpOnly" not in visible and "SameSite=Strict" in visible and "Max-Age" not in visible
        assert "__session" in sc
        token = cookie_value(visible)
        assert csrf.verify([KEY], token, None)
        # Hosting forwards only __session: the edge re-sends the same readable token
        r2 = await c.get(
            "/api/v1/_bff/csrf", headers={"cookie": f"__session={cookie_value(sc['__session'])}"}
        )
        assert cookie_value(set_cookies(r2)["__Host-td_csrf"]) == token
        assert (await c.post("/api/v1/_bff/csrf")).status_code == 405
    assert api.requests == []


async def _bootstrap(c: httpx.AsyncClient) -> tuple[str, str]:
    sc = set_cookies(await c.get("/api/v1/_bff/csrf"))
    return cookie_value(sc["__session"]), cookie_value(sc["__Host-td_csrf"])


async def test_unsafe_request_needs_double_submit_and_fetch_metadata(api: FakeApi) -> None:
    async with client(api) as c:
        sess, tok = await _bootstrap(c)
        ck = {"cookie": f"__session={sess}"}
        body = {"email": "a@b.c"}
        r = await c.post("/api/v1/auth/login", json=body, headers={**ck, "sec-fetch-site": "same-origin"})
        assert r.status_code == 403 and r.json()["code"] == "csrf_failed"
        r = await c.post(
            "/api/v1/auth/login",
            json=body,
            headers={**ck, "x-csrf-token": tok, "sec-fetch-site": "cross-site"},
        )
        assert r.status_code == 403
        r = await c.post(
            "/api/v1/auth/login",
            json=body,
            headers={**ck, "x-csrf-token": tok, "origin": "https://evil.example"},
        )
        assert r.status_code == 403
        r = await c.post(
            "/api/v1/auth/login",
            content=b"a=1",
            headers={**ck, "x-csrf-token": tok, "content-type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 415 and r.json()["allowed"] == ["application/json"]
        r = await c.post(
            "/api/v1/analytics/x",
            content=b"{" + b" " * 70_000 + b"}",
            headers={**ck, "x-csrf-token": tok, "content-type": "application/json"},
        )
        assert r.status_code == 413 and r.json()["max_bytes"] == 65536
        assert api.requests == []
        r = await c.post(
            "/api/v1/auth/login",
            json=body,
            headers={**ck, "x-csrf-token": tok, "sec-fetch-site": "same-origin"},
        )
        assert r.status_code == 200 and r.json() == {"ok": True}
    up = api.requests[-1]
    assert up["path"] == "/api/v1/auth/login" and json.loads(up["body"]) == body


async def test_upstream_headers_are_rebuilt(api: FakeApi) -> None:
    async with client(api) as c:
        jar = pack({"session": ("SESS", None), "device": ("DEV", None), "csrf": ("C", None)})
        await c.get(
            "/api/v1/me?x=1",
            headers={
                "cookie": f"__session={jar}; other=1",
                "x-td-session": "forged",
                "authorization": "Bearer forged",
                "x-forwarded-for": "6.6.6.6, 1.2.3.4, 10.0.0.1",
                "cloudfront-viewer-address": "9.9.9.9:443",
                "traceparent": "00-forged",
                "sec-fetch-mode": "navigate",
                "accept": "application/json",
                "x-custom": "dropped",
            },
        )
    h = api.requests[-1]["headers"]
    assert h["authorization"] == f"Service {TOKEN}"
    assert h["x-td-session"] == "SESS" and h["x-td-device"] == "DEV"
    assert h["cookie"] == "__Host-td_session=SESS; __Host-td_device=DEV"
    assert h["x-td-client-ip"] == "1.2.3.4" and h["x-forwarded-for"] == "1.2.3.4"  # viewer header ignored
    assert h["x-forwarded-proto"] == "https" and h["x-forwarded-host"] == "lms.example"
    assert h["traceparent"] != "00-forged" and h["x-td-activity"] == "navigation"
    assert "x-custom" not in h and h["accept-encoding"] == "identity"
    assert api.requests[-1]["query"] == b"x=1"


async def test_session_cookie_from_api_is_packed_and_csrf_rebound(api: FakeApi) -> None:
    api.responses["/api/v1/auth/login"] = (
        200,
        [
            ("content-type", "application/json"),
            ("set-cookie", "__Host-td_session=NEWSESS; Path=/; Max-Age=3600; Secure; HttpOnly; SameSite=Lax"),
            ("set-cookie", "__Host-td_device=DEV2; Path=/; Max-Age=34560000; Secure; HttpOnly; SameSite=Lax"),
            ("set-cookie", "__Host-td_csrf=evil; Path=/"),
            ("set-cookie", "tracker=1; Path=/"),
            ("server", "uvicorn"),
        ],
        b'{"result":"authenticated"}',
    )
    async with client(api) as c:
        sess, tok = await _bootstrap(c)
        r = await c.post(
            "/api/v1/auth/login",
            json={},
            headers={"cookie": f"__session={sess}", "x-csrf-token": tok, "sec-fetch-site": "same-origin"},
        )
    sc = set_cookies(r)
    assert set(sc) == {"__session", "__Host-td_csrf"} and "server" not in r.headers
    parts = unpack(cookie_value(sc["__session"]), 0)
    assert parts["session"][0] == "NEWSESS" and parts["device"][0] == "DEV2"
    new_tok = cookie_value(sc["__Host-td_csrf"])
    assert parts["csrf"][0] == new_tok and csrf.verify([KEY], new_tok, "NEWSESS")
    assert "Max-Age=345600" in sc["__session"]


async def test_ended_session_is_cleared(api: FakeApi) -> None:
    api.responses["/api/v1/me"] = (
        401,
        [("content-type", "application/problem+json")],
        b'{"code":"session_expired"}',
    )
    async with client(api) as c:
        jar = pack({"session": ("OLD", 9e9), "csrf": (csrf.mint(KEY, "OLD"), None)})
        r = await c.get("/api/v1/me", headers={"cookie": f"__session={jar}"})
    assert r.status_code == 401 and r.json() == {"code": "session_expired"}
    parts = unpack(cookie_value(set_cookies(r)["__session"]), 0)
    assert "session" not in parts and csrf.verify([KEY], parts["csrf"][0], None)


async def test_reserved_and_blocked_paths(api: FakeApi) -> None:
    async with client(api) as c:
        for path in (
            "/api/v1/webhooks/razorpay",
            "/api/v1/auth/remember/refresh",
            "/api/v1/_errors",
            "/api/v1/a/%2E%2E/b",
            "/api/v1/a%2Fb",
            "/elsewhere",
        ):
            r = await c.get(path)
            assert r.status_code == 404, path
            assert r.json()["type"] == "https://techdrona.in/problems/not-found"
        r = await c.options("/api/v1/me")
        assert r.status_code == 405 and r.headers["allow"] == "GET, HEAD, POST, PUT, PATCH, DELETE"
    assert api.requests == []


async def test_beacon_csrf_in_body_is_stripped(api: FakeApi) -> None:
    async with client(api) as c:
        sess, tok = await _bootstrap(c)
        ck = {"cookie": f"__session={sess}"}
        r = await c.post(
            "/api/v1/analytics/events/beacon",
            content=json.dumps({"csrf": tok, "events": [1]}),
            headers={**ck, "content-type": "text/plain", "sec-fetch-site": "same-origin"},
        )
        assert r.status_code == 200
        r2 = await c.post(
            "/api/v1/analytics/events/beacon",
            content=json.dumps({"csrf": tok}),
            headers={**ck, "content-type": "text/plain"},
        )
        assert r2.status_code == 403  # beacons need Sec-Fetch-Site: same-origin
    up = api.requests[-1]
    assert json.loads(up["body"]) == {"events": [1]} and up["headers"]["content-type"] == "application/json"


async def test_split_mode_is_byte_compatible_with_nextjs(api: FakeApi) -> None:
    api.responses["/api/v1/auth/login"] = (
        200,
        [("set-cookie", "__Host-td_session=S2; Path=/; Max-Age=60")],
        b"{}",
    )
    async with client(api, TD_EDGE_COOKIE_PACKING="split") as c:
        tok = cookie_value(set_cookies(await c.get("/api/v1/_bff/csrf"))["__Host-td_csrf"])
        r = await c.post(
            "/api/v1/auth/login",
            json={},
            headers={"cookie": f"__Host-td_csrf={tok}", "x-csrf-token": tok, "sec-fetch-site": "same-origin"},
        )
    sc = set_cookies(r)
    assert (
        sc["__Host-td_session"] == "__Host-td_session=S2; Path=/; Max-Age=60; Secure; HttpOnly; SameSite=Lax"
    )
    assert "__session" not in sc and "__Host-td_csrf" in sc


async def test_session_probe_remember_refresh(api: FakeApi) -> None:
    api.responses["/api/v1/auth/remember/refresh"] = (
        200,
        [
            ("content-type", "application/json"),
            ("set-cookie", "__Host-td_session=FRESH; Path=/; Max-Age=600"),
        ],
        b'{"result":"authenticated"}',
    )
    async with client(api) as c:
        jar = pack({"remember": ("R" * 32, 9e9), "device": ("DEV", 9e9)})
        r = await c.get(
            "/api/v1/_bff/session", headers={"cookie": f"__session={jar}", "sec-fetch-site": "same-origin"}
        )
        assert r.status_code == 200 and r.json() == {"session": True, "refreshed": True}
        parts = unpack(cookie_value(set_cookies(r)["__session"]), 0)
        assert parts["session"][0] == "FRESH" and csrf.verify([KEY], parts["csrf"][0], "FRESH")
        up = api.requests[-1]
        assert up["headers"]["authorization"] == f"Service {TOKEN}" and up["headers"]["x-td-device"] == "DEV"
        assert json.loads(up["body"]) == {"remember_token": "R" * 32}
        # invalid remember token -> cleared
        api.responses["/api/v1/auth/remember/refresh"] = (401, [], b"{}")
        r = await c.get("/api/v1/_bff/session", headers={"cookie": f"__session={jar}"})
        assert r.json() == {"session": False, "refreshed": False}
        assert "remember" not in unpack(cookie_value(set_cookies(r)["__session"]), 0)
        r = await c.get("/api/v1/_bff/session", headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403


# --------------------------------------------------------------------------- public admissions bridge


async def test_public_admissions_cors_and_multipart(api: FakeApi) -> None:
    pdf = b"%PDF-1.4 " + b"x" * 200
    async with client(api) as c:
        r = await c.options(
            "/api/public/admissions/registrations", headers={"origin": "https://site.example"}
        )
        assert r.status_code == 204 and r.headers["access-control-allow-origin"] == "https://site.example"
        r = await c.options(
            "/api/public/admissions/registrations", headers={"origin": "https://evil.example"}
        )
        assert r.status_code == 403
        r = await c.post("/api/public/admissions/status", json={}, headers={})
        assert r.status_code == 403 and r.json()["detail"] == "Origin required."
        r = await c.post(
            "/api/public/admissions/registrations",
            data={"data": json.dumps({"name": "A", "resume": "x"})},
            files={"proof": ("receipt.pdf", pdf, "application/pdf")},
            headers={"origin": "https://site.example", "x-forwarded-for": "5.6.7.8, 10.0.0.1"},
        )
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "https://site.example"
        r = await c.post(
            "/api/public/admissions/claims",
            data={"data": "{}"},
            files={"proof": ("x.txt", b"hello" * 50, "text/plain")},
            headers={"origin": "https://site.example"},
        )
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "proof"
        r = await c.get("/api/public/admissions/plans/Bad_Slug", headers={"origin": "https://site.example"})
        assert r.status_code == 404
    up = api.requests[0]
    assert up["path"] == "/api/v1/public/admissions/registrations"
    sent = json.loads(up["body"])
    assert sent["name"] == "A" and "resume" not in sent
    assert base64.b64decode(sent["proof"]["data_b64"]) == pdf and sent["proof"]["filename"] == "receipt.pdf"
    assert (
        up["headers"]["authorization"] == f"Service {TOKEN}" and up["headers"]["x-td-client-ip"] == "5.6.7.8"
    )
    assert "cookie" not in up["headers"]


def test_cookie_header_parsing_first_wins() -> None:
    assert parse_cookie_header("a=1; b=2; a=3") == {"a": "1", "b": "2"}


async def test_edge_in_front_of_the_real_api_app() -> None:
    """The unchanged FastAPI app behind the edge (public liveness route; no database)."""
    from app.main import create_app

    edge = EdgeApp(create_app(), _cfg())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=edge), base_url=ORIGIN) as c:
        r = await c.get("/api/v1/health/live")
        assert r.status_code == 200 and r.json() == {"status": "ok"}
        assert "x-request-id" in r.headers
        r = await c.get("/api/v1/no/such/route")
        assert r.status_code == 404 and r.headers["content-type"].startswith("application/problem+json")
        assert (await c.get("/healthz")).json() == {"status": "ok"}


async def test_spa_navigation_marker_is_forwarded_like_nextjs(api: FakeApi) -> None:
    """The SPA marks page loads with x-td-activity: navigation (fetch() never has mode=navigate)."""
    cases = [
        (
            {"x-td-activity": "navigation", "sec-fetch-site": "same-origin", "sec-fetch-mode": "cors"},
            "navigation",
        ),
        ({"x-td-activity": "navigation"}, "navigation"),  # no fetch metadata, no Origin
        ({"sec-fetch-mode": "navigate"}, "navigation"),  # Next rule unchanged
        ({"x-td-activity": "navigation", "sec-fetch-site": "cross-site"}, None),
        ({"x-td-activity": "navigation", "origin": "https://evil.example"}, None),
        ({"x-td-activity": "navigation", "sec-fetch-site": "same-origin", "sec-purpose": "prefetch"}, None),
        ({"x-td-activity": "navigation", "next-router-prefetch": "1"}, None),
        ({"x-td-activity": "heartbeat", "sec-fetch-site": "same-origin"}, None),
        ({"sec-fetch-mode": "navigate", "purpose": "prefetch"}, None),
    ]
    async with client(api) as c:
        for headers, expected in cases:
            await c.get("/api/v1/me", headers=headers)
            assert api.requests[-1]["headers"].get("x-td-activity") == expected, headers
        await c.delete("/api/v1/me", headers={"x-td-activity": "navigation"})  # 403 csrf: never forwarded


async def test_cookie_responses_are_private_for_hosting(api: FakeApi) -> None:
    """Firebase Hosting strips Set-Cookie unless Cache-Control has `private` (seen on the emulator)."""
    async with client(api) as c:
        r = await c.get("/api/v1/me")  # API answer + a freshly minted csrf cookie
        assert r.headers.get_list("set-cookie") and r.headers["cache-control"] == "private, no-store"
    async with client(api) as c:
        sess, _tok = await _bootstrap(c)
        r = await c.get("/api/v1/me", headers={"cookie": f"__session={sess}"})
        assert not r.headers.get_list("set-cookie") and r.headers["cache-control"] == "no-store"
