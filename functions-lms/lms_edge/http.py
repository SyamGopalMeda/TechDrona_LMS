"""Small ASGI helpers shared by the edge handlers."""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

PROBLEM_CONTENT_TYPE = "application/problem+json"

# Request side is an ALLOW-list (lib/bff/headers.ts FORWARDED_REQUEST_HEADERS).
FORWARDED_REQUEST_HEADERS = (
    "accept",
    "accept-language",
    "content-type",
    "idempotency-key",
    "if-match",
    "if-none-match",
    "if-modified-since",
    "last-event-id",
    "user-agent",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
)
HOP_BY_HOP_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-encoding",
        "content-length",
        "set-cookie",
        "server",
        "x-powered-by",
    }
)
_IP_RE = re.compile(r"^[0-9a-fA-F:.]{2,45}$")


class Headers:
    """Case-insensitive, multi-value header list (ASGI byte pairs in, str out)."""

    def __init__(self, raw: Iterable[tuple[bytes, bytes]] | None = None) -> None:
        self.items: list[tuple[str, str]] = [
            (k.decode("latin-1").lower(), v.decode("latin-1")) for k, v in (raw or [])
        ]

    def get(self, name: str) -> str | None:
        name = name.lower()
        vals = [v for k, v in self.items if k == name]
        if not vals:
            return None
        return "; ".join(vals) if name == "cookie" else ", ".join(vals)

    def get_all(self, name: str) -> list[str]:
        name = name.lower()
        return [v for k, v in self.items if k == name]

    def set(self, name: str, value: str) -> None:
        name = name.lower()
        self.items = [(k, v) for k, v in self.items if k != name]
        self.items.append((name, value))

    def append(self, name: str, value: str) -> None:
        self.items.append((name.lower(), value))

    def delete(self, name: str) -> None:
        name = name.lower()
        self.items = [(k, v) for k, v in self.items if k != name]

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def raw(self) -> list[tuple[bytes, bytes]]:
        return [(k.encode("latin-1"), v.encode("latin-1")) for k, v in self.items]


@dataclass
class Response:
    status: int
    headers: Headers = field(default_factory=Headers)
    body: bytes = b""

    async def send(self, send: Send) -> None:
        h = Headers()
        h.items = list(self.headers.items)
        h.set("content-length", str(len(self.body)))
        await send({"type": "http.response.start", "status": self.status, "headers": h.raw()})
        await send({"type": "http.response.body", "body": self.body, "more_body": False})


def problem(
    status: int,
    code: str,
    title: str,
    detail: str,
    request_id: str,
    extensions: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    """Same body and headers as lib/api/problem.ts ``problemResponse``."""
    body = {
        "type": "https://techdrona.in/problems/" + code.replace("_", "-"),
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "request_id": request_id,
        **(extensions or {}),
    }
    h = Headers()
    h.set("content-type", PROBLEM_CONTENT_TYPE)
    h.set("cache-control", "no-store")
    h.set("x-request-id", request_id)
    for k, v in (headers or {}).items():
        h.set(k, v)
    return Response(status, h, json.dumps(body, separators=(",", ":")).encode())


async def read_body(receive: Receive, limit: int | None = None) -> tuple[bytes, bool]:
    """Read the whole request body; ``(body, too_large)`` (stops reading past ``limit``)."""
    chunks: list[bytes] = []
    size = 0
    while True:
        msg = await receive()
        if msg["type"] == "http.disconnect":
            break
        chunk = msg.get("body", b"") or b""
        size += len(chunk)
        if limit is not None and size > limit:
            return b"", True
        chunks.append(chunk)
        if not msg.get("more_body"):
            break
    return b"".join(chunks), False


async def call_asgi(
    app: ASGIApp,
    *,
    method: str,
    raw_path: str,
    query: bytes,
    headers: Headers,
    body: bytes,
    client: tuple[str, int] | None,
) -> tuple[int, Headers, bytes]:
    """Call ``app`` in-process (the edge -> API hop); buffers the response (no streaming
    endpoints exist in the API)."""
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": unquote(raw_path),
        "raw_path": raw_path.encode("latin-1"),
        "query_string": query,
        "root_path": "",
        "headers": headers.raw(),
        "client": client or ("127.0.0.1", 0),
        "server": ("lms-api.internal", 443),
        "state": {},
    }
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    status = 500
    out_headers = Headers()
    parts: list[bytes] = []

    async def send(message: MutableMapping[str, Any]) -> None:
        nonlocal status, out_headers
        if message["type"] == "http.response.start":
            status = int(message["status"])
            out_headers = Headers(message.get("headers") or [])
        elif message["type"] == "http.response.body":
            parts.append(message.get("body", b"") or b"")

    await app(scope, receive, send)
    return status, out_headers, b"".join(parts)


def resolve_client_ip(headers: Headers, trusted_proxy_hops: int, *, trust_viewer_address: bool) -> str | None:
    """Port of lib/bff/headers.ts ``resolveClientIp``. ``CloudFront-Viewer-Address`` is only
    trusted when an edge overwrites it (Caddy on the VM); Firebase Hosting passes a browser
    supplied value through, so it is ignored there unless ``TD_EDGE_TRUST_VIEWER_ADDRESS``."""
    if trusted_proxy_hops <= 0:
        return None
    viewer = headers.get("cloudfront-viewer-address") if trust_viewer_address else None
    if viewer:
        if "]" in viewer:
            ip = viewer[viewer.index("[") + 1 : viewer.index("]")]
        elif viewer.rfind(":") > viewer.find(":"):
            ip = viewer[: viewer.rfind(":")]
        else:
            ip = viewer.split(":")[0]
        if _IP_RE.match(ip):
            return ip
    xff = headers.get("x-forwarded-for")
    if not xff:
        return None
    chain = [s.strip() for s in xff.split(",") if s.strip()]
    idx = len(chain) - 1 - trusted_proxy_hops
    cand = chain[idx] if idx >= 0 else None
    return cand if cand and _IP_RE.match(cand) else None


def new_traceparent() -> str:
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"


_uuid_lock = threading.Lock()
_last_ms = -1
_counter = 0


def uuid7() -> str:
    """UUIDv7 string (monotonic within a millisecond), like lib/ids/uuid7.ts."""
    global _last_ms, _counter
    with _uuid_lock:
        ms = max(time.time_ns() // 1_000_000, _last_ms)
        if ms == _last_ms:
            _counter += 1
            if _counter > 0xFFF:
                ms += 1
                _counter = int.from_bytes(os.urandom(2), "big") & 0x7FF
        else:
            _counter = int.from_bytes(os.urandom(2), "big") & 0x7FF
        _last_ms = ms
        rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
        value = (ms << 80) | (0x7 << 76) | (_counter << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))
