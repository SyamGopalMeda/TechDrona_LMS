"""lmsWebhooks front (functions-lms/lms_edge/webhooks.py): the api-webhooks service on Firebase."""

from __future__ import annotations

from typing import Any

import httpx
from lms_edge.webhooks import WebhookEdge


class Echo:
    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        body = b""
        while True:
            m = await receive()
            body += m.get("body", b"")
            if not m.get("more_body"):
                break
        self.seen.append(
            {
                "path": scope["path"],
                "client": scope["client"],
                "headers": dict(scope["headers"]),
                "body": body,
            }
        )
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"status":"accepted"}'})


async def test_raw_body_ip_and_header_hygiene() -> None:
    api = Echo()
    edge = WebhookEdge(api, trusted_proxy_hops=1)  # type: ignore[arg-type]
    raw = b'{"event":"payment.captured","payload":{}}  '
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=edge), base_url="https://fn") as c:
        r = await c.post(
            "/api/v1/webhooks/razorpay",
            content=raw,
            headers={
                "x-razorpay-signature": "abc",
                "x-forwarded-for": "6.6.6.6, 3.7.0.1, 10.0.0.9",
                "authorization": "Service forged",
                "x-td-session": "forged",
                "cookie": "__session=x",
            },
        )
        assert r.status_code == 200
        assert (await c.get("/api/v1/me")).status_code == 404
        assert (await c.get("/api/v1/_bff/csrf")).status_code == 404
    seen = api.seen[0]
    assert seen["body"] == raw  # byte for byte (HMAC)
    assert seen["client"] == ("3.7.0.1", 0)
    h = seen["headers"]
    assert h[b"x-razorpay-signature"] == b"abc"
    assert b"authorization" not in h and b"x-td-session" not in h and b"cookie" not in h
    assert len(api.seen) == 1


async def test_real_api_webhook_router_set() -> None:
    """The real app with TD_ROUTER_SET=webhooks behind the front: only webhook + health routes."""
    from app.core.config import get_settings
    from app.main import create_app

    s = get_settings().model_copy(update={"TD_ROUTER_SET": "webhooks"})
    edge = WebhookEdge(create_app(s))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=edge), base_url="https://fn") as c:
        assert (await c.get("/api/v1/webhooks/razorpay/health")).json() == {"status": "ok"}
        assert (await c.get("/api/v1/webhooks/nope/health")).json() == {"status": "unknown"}
        assert (await c.get("/api/v1/health/live")).status_code == 200
        r = await c.post("/api/v1/webhooks/unknown", content=b"{}")
        assert r.status_code == 404
