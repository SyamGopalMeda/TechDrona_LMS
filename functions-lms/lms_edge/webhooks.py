"""Front of the ``lmsWebhooks`` function: the ``api-webhooks`` service on Firebase.

On the VM ``api-webhooks`` is the same API image with ``TD_ROUTER_SET=webhooks`` (only the
modules' ``webhook_router``s: today ``POST /api/v1/webhooks/{provider}`` and
``GET /api/v1/webhooks/{provider}/health`` from commerce, plus the health routes). No BFF, no
cookies, no CSRF: providers authenticate with an HMAC over the raw body, which is passed through
byte for byte.

``WebhookEdge`` only does what the network did on the VM:

* the client IP: the API takes the socket peer for unauthenticated requests
  (``ServiceAuthMiddleware``). Behind Google's front end that peer is a proxy, so the address is
  taken from ``X-Forwarded-For`` (right-most minus ``TD_TRUSTED_PROXY_HOPS``) and put in the ASGI
  ``client`` -- the per-IP invalid-signature limit keeps working per provider IP;
* BFF-only headers (``Authorization``, ``X-TD-*``, ``Cookie``) are dropped: a webhook can never be
  "service authenticated" (on the VM nothing but the BFF could reach the API with them);
* anything outside ``/api/v1/webhooks/`` and the health probes answers 404 (the webhooks router set
  has no other routes either).
"""

from __future__ import annotations

from typing import Any

from lms_edge.http import ASGIApp, Headers, Receive, Scope, Send, problem, resolve_client_ip, uuid7

WEBHOOK_PREFIX = "/api/v1/webhooks/"
HEALTH_PATHS = ("/healthz", "/api/v1/health/live", "/api/v1/health/ready")
_DROPPED = ("authorization", "cookie")


class WebhookEdge:
    def __init__(self, api: ASGIApp, *, trusted_proxy_hops: int = 1) -> None:
        self.api = api
        self.hops = trusted_proxy_hops

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.api(scope, receive, send)
            return
        path = scope["path"]
        if not (path.startswith(WEBHOOK_PREFIX) or path in HEALTH_PATHS):
            await problem(
                404, "not_found", "Not found", "The requested resource was not found.", uuid7()
            ).send(send)
            return
        h = Headers(scope.get("headers"))
        ip = resolve_client_ip(h, self.hops, trust_viewer_address=False)
        clean = Headers()
        clean.items = [(k, v) for k, v in h.items if k not in _DROPPED and not k.startswith("x-td-")]
        inner: dict[str, Any] = dict(scope)
        inner["headers"] = clean.raw()
        inner["client"] = (ip, 0) if ip else None
        await self.api(inner, receive, send)
