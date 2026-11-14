"""ASGI middleware (system-architecture §5.1 order):

1. ``RequestContextMiddleware`` — ``X-Request-Id`` (accept a safe upstream id or mint a
   ULID), request log line, ``Cache-Control: no-store`` on authenticated responses.
2. ``ServiceAuthMiddleware`` — BFF hop: only when ``Authorization: Service <token>`` matches
   ``TD_SERVICE_TOKEN`` (or ``TD_SERVICE_TOKEN_PREVIOUS``) are ``X-TD-Session``,
   ``X-TD-Device``, ``X-TD-Client-IP`` and ``X-TD-Activity`` trusted. Otherwise they are ignored.
3. ``MaintenanceMiddleware`` — while the ``platform.maintenance_mode`` flag is on (ADM-17),
   writes answer ``503 maintenance``; reads, admin routes (including break-glass), sign-in and
   step-up, and provider webhooks keep working so staff can operate and switch it off.
4. ``BodyLimitMiddleware`` — 256 KiB default → ``413 payload_too_large``.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import request_commit, request_locks
from app.core.config import get_settings
from app.core.errors import ProblemError, problem_response
from app.core.firestore import request_memo
from app.core.ids import new_request_id
from app.core.request_context import (
    REQUEST_ID_RE,
    bind_request_state,
    reset_request_id,
    reset_request_state,
    set_request_id,
)
from app.core.security import constant_time_equals

log = structlog.get_logger("app.request")


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k == name:
            try:
                return v.decode("latin-1")
            except UnicodeDecodeError:  # pragma: no cover
                return None
    return None


def _state(scope: Scope) -> dict[str, Any]:
    st = scope.setdefault("state", {})
    return st


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = _header(scope, b"x-request-id")
        rid = incoming if incoming and REQUEST_ID_RE.match(incoming) else new_request_id()
        token = set_request_id(rid)
        _state(scope)["request_id"] = rid
        structlog.contextvars.bind_contextvars(request_id=rid)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                # No-Postgres buffers (audit rows, outbox events): the request's commit point.
                try:
                    await request_commit.on_response_start(message["status"])
                except Exception as e:  # never break the response
                    log.error("request_commit_failed", error=type(e).__name__)
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", rid.encode()))
                if _state(scope).get("principal") is not None and not any(
                    k.lower() == b"cache-control" for k, _ in headers
                ):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        lock_token = request_locks.begin_scope()  # Firestore per-request locks (no cost if unused)
        # Firestore read memo for this request only (app.core.firestore.request_memo).
        _state(scope)[request_memo.STATE_KEY] = request_memo.begin()
        state_token = bind_request_state(_state(scope))  # current_principal() / current_rls_context()
        buffers = request_commit.Buffers()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            buffers.close()  # anything not committed by now belongs to a failed request
            _state(scope).pop(request_memo.STATE_KEY, None)  # never outlives the request
            reset_request_state(state_token)
            await request_locks.release_scope(lock_token)
            log.info(
                "request",
                method=scope.get("method"),
                path=scope.get("path"),  # never the query string (may carry tokens)
                status=status_holder["status"],
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            structlog.contextvars.unbind_contextvars("request_id")
            reset_request_id(token)


class ServiceAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        s = get_settings()
        st = _state(scope)
        authz = _header(scope, b"authorization") or ""
        trusted = False
        if authz.startswith("Service "):
            presented = authz[len("Service ") :].strip()
            for expected in (s.TD_SERVICE_TOKEN, s.TD_SERVICE_TOKEN_PREVIOUS):
                if expected and presented and constant_time_equals(presented, expected):
                    trusted = True
        client = scope.get("client")
        st["service_authenticated"] = trusted
        st["client_ip"] = client[0] if client else None
        st["session_token"] = None
        st["device_token"] = None
        st["activity"] = None
        if trusted:
            st["session_token"] = _header(scope, b"x-td-session") or None
            st["device_token"] = _header(scope, b"x-td-device") or None
            # SEC-01: behind the BFF the socket peer is the BFF itself, never the browser. When
            # the BFF cannot attribute an IP (no trusted proxy hop) it sends none and the IP
            # stays unknown — per-IP limits are then skipped instead of pooling every user.
            st["client_ip"] = _header(scope, b"x-td-client-ip") or None
            st["activity"] = _header(scope, b"x-td-activity") or None
        await self.app(scope, receive, send)


MAINTENANCE_FLAG = "platform.maintenance_mode"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Path prefixes (after the API prefix) that stay writable in maintenance mode.
MAINTENANCE_EXEMPT_PREFIXES = ("/admin/", "/auth/", "/webhooks/")


class MaintenanceMiddleware:
    """Blocks writes with ``503 maintenance`` while ``platform.maintenance_mode`` is enabled.

    The flag is read through ``admin.flags.cached_flag_enabled`` (30 s process cache, its own
    short DB session). A flag-read failure fails **open** (logged): maintenance mode is an
    operational switch, not a security control.
    """

    def __init__(self, app: ASGIApp, api_prefix: str = "/api/v1") -> None:
        self.app = app
        self.api_prefix = api_prefix

    def _exempt(self, path: str) -> bool:
        if not path.startswith(self.api_prefix + "/"):
            return True  # /healthz and anything outside the API
        rest = path[len(self.api_prefix) :]
        return rest.startswith(MAINTENANCE_EXEMPT_PREFIXES) or rest == "/admin"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method", "GET") in SAFE_METHODS
            or self._exempt(scope["path"])
        ):
            await self.app(scope, receive, send)
            return
        try:
            from app.modules.admin.flags import cached_flag_enabled

            on = await cached_flag_enabled(MAINTENANCE_FLAG)
        except Exception as e:  # DB hiccup: fail open
            log.warning("maintenance_flag_unavailable", error=type(e).__name__)
            on = False
        if on:
            problem = ProblemError(
                "maintenance",
                detail="Tech Drona is down for maintenance. Changes are paused; please try again shortly.",
                headers={"Retry-After": "300"},
            )
            await problem_response(problem)(scope, receive, send)
            return
        await self.app(scope, receive, send)


# Exact API paths allowed a larger body than TD_MAX_BODY_BYTES (e.g. the public admissions forms,
# which carry base64 payment proofs). Registered by the owning module at import time.
_PATH_BODY_LIMITS: dict[str, int] = {}


def register_body_limit(path: str, max_bytes: int) -> None:
    """Allow ``max_bytes`` (<= 8 MiB) for requests to exactly ``path``."""
    if not path.startswith("/") or not 0 < max_bytes <= 8 * 1024 * 1024:
        raise ValueError("body limit override must be an absolute path and at most 8 MiB")
    _PATH_BODY_LIMITS[path] = max_bytes


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        override = _PATH_BODY_LIMITS.get(scope.get("path", ""))
        limit = self.max_bytes or override or get_settings().TD_MAX_BODY_BYTES
        declared = _header(scope, b"content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            await problem_response(ProblemError("payload_too_large", max_bytes=limit))(scope, receive, send)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise ProblemError("payload_too_large", max_bytes=limit)
            return message

        await self.app(scope, limited_receive, send)
