"""``EdgeApp``: the Next.js BFF behaviour as ASGI, in front of the FastAPI app (in-process).

Routes (everything Firebase Hosting rewrites to ``lmsApi``):

* ``/api/v1/*`` -> ``handle_bff`` = lib/bff/proxy.ts ``handleBffRequest`` (same checks, same
  problem responses, same upstream headers, same cookie re-issue rules).
* ``/api/v1/_bff/csrf`` -> CSRF bootstrap (unchanged contract: ``204`` + ``td_csrf``).
* ``/api/v1/_bff/session`` -> **new, SPA only**: what the Next.js page middleware did on a page
  load (there is no server-rendered page any more): the remember-device re-issue (AUTH-28) when
  there is no session but a remember cookie, then ``td_csrf`` issue/refresh. Answers
  ``200 {"session": bool, "refreshed": bool}``. Only reachable same-origin.
* ``/api/public/admissions/*`` and ``/api/public/courses/status`` -> ``lms_edge.public``.
* ``/college-portal/*`` -> ``lms_edge.college_portal`` (College Data Portal on Cloud Run behind
  the LMS admin session; port of apps/web/src/lib/college-portal/proxy.ts).
* ``/healthz`` -> the API's liveness probe. Anything else -> ``404``.
"""

from __future__ import annotations

import asyncio
import json

from lms_edge import csrf
from lms_edge.config import ConfigError, EdgeConfig, load_config
from lms_edge.cookies import CookieJar, ParsedSetCookie, cookie_kind_from_name, parse_set_cookie
from lms_edge.http import (
    FORWARDED_REQUEST_HEADERS,
    HOP_BY_HOP_RESPONSE_HEADERS,
    ASGIApp,
    Headers,
    Receive,
    Response,
    Scope,
    Send,
    call_asgi,
    new_traceparent,
    problem,
    read_body,
    resolve_client_ip,
    uuid7,
)

API_PREFIX = "/api/v1/"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ALLOWED_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
DEFAULT_MAX_BODY = 256 * 1024
SMALL_MAX_BODY = 64 * 1024
UPLOAD_MAX_BODY = 4 * 1024 * 1024
UPLOAD_PATHS = frozenset(
    {
        "me/admissions/registrations",
        "me/admissions/claims",
        "public/admissions/registrations",
        "public/admissions/claims",
    }
)
BEACON_PATH = "analytics/events/beacon"
CSRF_BOOTSTRAP_PATH = "_bff/csrf"
SESSION_PROBE_PATH = "_bff/session"
REMEMBER_REFRESH_PATH = "auth/remember/refresh"
ENDED_SESSION_CODES = frozenset({"unauthenticated", "session_expired", "session_revoked"})


def extract_api_path(raw_path: str) -> str | None:
    """Raw (percent-encoded) path after /api/v1/; rejects traversal and encoded separators."""
    from urllib.parse import unquote

    if not raw_path.startswith(API_PREFIX):
        return None
    raw = raw_path[len(API_PREFIX) :]
    if not raw or len(raw) > 1024:
        return None
    for seg in raw.split("/"):
        try:
            decoded = unquote(seg, errors="strict")
        except UnicodeDecodeError:
            return None
        if decoded in ("", ".", "..") or any(c in decoded for c in "/\\\0"):
            return None
    return raw


def max_body_for(path: str) -> int:
    if path in UPLOAD_PATHS:
        return UPLOAD_MAX_BODY
    return SMALL_MAX_BODY if path.startswith("analytics/") else DEFAULT_MAX_BODY


def _is_json_ct(ct: str | None) -> bool:
    if not ct:
        return False
    base = ct.split(";")[0].strip().lower()
    return base == "application/json" or (base.startswith("application/") and base.endswith("+json"))


def _is_prefetch(h: Headers) -> bool:
    purpose = f"{h.get('sec-purpose') or ''} {h.get('purpose') or ''}".lower()
    return "prefetch" in purpose or h.get("next-router-prefetch") == "1"


def _not_found(rid: str) -> Response:
    return problem(404, "not_found", "Not found", "The requested resource was not found.", rid)


def _method_not_allowed(rid: str, allow: str) -> Response:
    return problem(
        405,
        "method_not_allowed",
        "Method not allowed",
        "This method is not supported here.",
        rid,
        headers={"allow": allow},
    )


def _csrf_failed(rid: str) -> Response:
    return problem(
        403,
        "csrf_failed",
        "Request blocked",
        "Your request could not be verified. Refresh the page and try again.",
        rid,
    )


def _too_large(rid: str, limit: int) -> Response:
    return problem(
        413,
        "payload_too_large",
        "Request too large",
        "The request body is too large.",
        rid,
        {"max_bytes": limit},
    )


def _unavailable(rid: str, detail: str, retry: str) -> Response:
    return problem(
        503, "service_unavailable", "Service unavailable", detail, rid, headers={"retry-after": retry}
    )


def _same_origin_ok(h: Headers, config: EdgeConfig) -> bool:
    site = h.get("sec-fetch-site")
    if site is not None:
        return site in ("same-origin", "none")
    origin = h.get("origin")
    return origin is None or origin == config.public_origin


def keep_cookies_through_hosting(resp: Response) -> Response:
    """Firebase Hosting drops ``Set-Cookie`` from a function response unless its
    ``Cache-Control`` contains ``private`` (firebase-tools hosting/proxy.js; the CDN rule). Every
    cookie-carrying answer here is ``no-store`` already, so ``private`` is added in front: same
    caching outcome for the browser, and the cookies survive the Hosting hop."""
    if resp.headers.get_all("set-cookie"):
        cc = resp.headers.get("cache-control") or ""
        if "private" not in cc.lower():
            resp.headers.set("cache-control", f"private, {cc}" if cc else "private, no-store")
    return resp


class EdgeApp:
    def __init__(self, api: ASGIApp, config: EdgeConfig | None = None) -> None:
        self.api = api
        self._config = config

    def config(self) -> EdgeConfig:
        if self._config is None:
            self._config = load_config()
        return self._config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.api(scope, receive, send)
            return
        if scope["type"] != "http":
            return
        raw_path = (scope.get("raw_path") or scope["path"].encode()).decode("latin-1").split("?", 1)[0]
        if raw_path == "/healthz":
            await self.api(scope, receive, send)
            return
        from lms_edge.college_portal import PORTAL_PREFIX, handle_college_portal
        from lms_edge.public import COURSE_STATUS_PATHNAME, PUBLIC_PREFIX, handle_public

        if raw_path == COURSE_STATUS_PATHNAME or raw_path.startswith(PUBLIC_PREFIX):
            resp = await handle_public(self, scope, receive, raw_path)
        elif raw_path == PORTAL_PREFIX or raw_path.startswith(PORTAL_PREFIX + "/"):
            resp = await handle_college_portal(self, scope, receive, raw_path)
        elif raw_path.startswith(API_PREFIX):
            resp = await self.handle_bff(scope, receive, raw_path)
        else:
            resp = _not_found(uuid7())
        await keep_cookies_through_hosting(resp).send(send)

    # ------------------------------------------------------------------ helpers

    def _client_ip(self, h: Headers, config: EdgeConfig) -> str | None:
        return resolve_client_ip(
            h, config.trusted_proxy_hops, trust_viewer_address=config.trust_viewer_address
        )

    def _csrf_set_if_needed(
        self, jar: CookieJar, config: EdgeConfig, session_after: str | None, force: bool
    ) -> None:
        existing = jar.get("csrf")
        if force or not existing or not csrf.verify(config.csrf_keys[:1], existing, session_after):
            jar.set_csrf(csrf.mint(config.csrf_keys[0], session_after))

    # ------------------------------------------------------------------ /api/v1/*

    async def handle_bff(self, scope: Scope, receive: Receive, raw_path: str) -> Response:
        rid = uuid7()
        method = scope["method"].upper()
        h = Headers(scope.get("headers"))
        try:
            config = self.config()
        except ConfigError as e:
            print(f"[edge] configuration error request_id={rid}: {e}")  # noqa: T201 - function log
            return _unavailable(rid, "The service is temporarily unavailable.", "30")

        if config.origin_verify_value:
            import hmac

            if not hmac.compare_digest(
                (h.get("x-origin-verify") or "").encode(), config.origin_verify_value.encode()
            ):
                return problem(
                    403, "permission_denied", "Forbidden", "Request did not arrive through the edge.", rid
                )

        path = extract_api_path(raw_path)
        if path is None:
            return _not_found(rid)
        if path == "webhooks" or path.startswith("webhooks/"):
            return _not_found(rid)
        if path == REMEMBER_REFRESH_PATH:
            return _not_found(rid)
        jar = CookieJar.from_header(config, h.get("cookie"))
        if path == CSRF_BOOTSTRAP_PATH:
            if method != "GET":
                return _method_not_allowed(rid, "GET")
            return self._csrf_bootstrap(jar, config, rid)
        if path == SESSION_PROBE_PATH:
            if method != "GET":
                return _method_not_allowed(rid, "GET")
            return await self._session_probe(scope, h, jar, config, rid)
        if path.startswith("_"):
            return _not_found(rid)
        if method not in ALLOWED_METHODS:
            return _method_not_allowed(rid, ", ".join(ALLOWED_METHODS))

        session = jar.get("session")
        device = jar.get("device")
        csrf_from_cookie = jar.get("csrf")
        body = b""
        upstream_ct = h.get("content-type")

        if method in UNSAFE_METHODS:
            is_beacon = method == "POST" and path == BEACON_PATH
            fetch_site = h.get("sec-fetch-site")
            if is_beacon:
                if fetch_site != "same-origin":
                    return _csrf_failed(rid)
            elif fetch_site is not None:
                if fetch_site not in ("same-origin", "none"):
                    return _csrf_failed(rid)
            else:
                origin = h.get("origin")
                if origin is not None and origin != config.public_origin:
                    return _csrf_failed(rid)

            limit = max_body_for(path)
            try:
                declared = int(h.get("content-length") or "")
            except ValueError:
                declared = None
            if declared is not None and declared > limit:
                return _too_large(rid, limit)
            buf, too_large = await read_body(receive, limit)
            if too_large:
                return _too_large(rid, limit)
            if buf:
                ct = h.get("content-type")
                text_plain = (ct or "").lower().startswith("text/plain")
                if not _is_json_ct(ct) and not (is_beacon and text_plain):
                    return problem(
                        415,
                        "unsupported_media_type",
                        "Unsupported media type",
                        "Send JSON.",
                        rid,
                        {"allowed": ["application/json"]},
                    )
                body = buf

            if is_beacon:
                try:
                    parsed = json.loads(buf.decode("utf-8"))
                    if not isinstance(parsed, dict):
                        raise ValueError
                except (ValueError, UnicodeDecodeError):
                    return problem(
                        400,
                        "validation_failed",
                        "Invalid request",
                        "Body is not valid JSON.",
                        rid,
                        {"errors": []},
                    )
                token = parsed.get("csrf") if isinstance(parsed.get("csrf"), str) else None
                if not csrf.check_double_submit(config.csrf_keys, csrf_from_cookie, token, session):
                    return _csrf_failed(rid)
                parsed.pop("csrf", None)
                body = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False).encode()
                upstream_ct = "application/json"
            elif not csrf.check_double_submit(
                config.csrf_keys, csrf_from_cookie, h.get("x-csrf-token"), session
            ):
                return _csrf_failed(rid)

        up = Headers()
        for name in FORWARDED_REQUEST_HEADERS:
            v = h.get(name)
            if v is not None:
                up.set(name, v)
        if upstream_ct:
            up.set("content-type", upstream_ct)
        up.set("accept-encoding", "identity")
        if config.service_token:
            up.set("authorization", f"Service {config.service_token}")
        cookies_up: list[str] = []
        if session:
            up.set("x-td-session", session)
            cookies_up.append(f"__Host-td_session={session}")
        if device:
            up.set("x-td-device", device)
            cookies_up.append(f"__Host-td_device={device}")
        if cookies_up:
            up.set("cookie", "; ".join(cookies_up))
        ip = self._client_ip(h, config)
        if ip:
            up.set("x-td-client-ip", ip)
            up.set("x-forwarded-for", ip)
        proto, _, host = config.public_origin.partition("://")
        up.set("x-forwarded-proto", proto)
        up.set("x-forwarded-host", host)
        up.set("x-request-id", rid)
        up.set("traceparent", new_traceparent())
        if method == "GET" and not _is_prefetch(h):
            # Next BFF: a top-level page load (Sec-Fetch-Mode: navigate). The SPA loads pages with
            # fetch(), so it marks a page load with `x-td-activity: navigation` itself; accepted
            # only from same-origin requests (the value is advisory: session idle bookkeeping).
            spa_nav = (h.get("x-td-activity") or "").strip().lower() == "navigation" and _same_origin_ok(
                h, config
            )
            if h.get("sec-fetch-mode") == "navigate" or spa_nav:
                up.set("x-td-activity", "navigation")

        is_stream = "text/event-stream" in (h.get("accept") or "")
        try:
            coro = call_asgi(
                self.api,
                method=method,
                raw_path=f"{API_PREFIX}{path}",
                query=scope.get("query_string") or b"",
                headers=up,
                body=b"" if method in ("GET", "HEAD") else body,
                client=scope.get("client"),
            )
            status, uh, ubody = await (coro if is_stream else asyncio.wait_for(coro, config.proxy_timeout_s))
        except Exception as e:
            print(f"[edge] upstream {type(e).__name__} request_id={rid} {method} /api/v1/{path}")  # noqa: T201
            return _unavailable(rid, "We could not reach the service. Please try again.", "5")

        out = Headers()
        for k, v in uh.items:
            if k not in HOP_BY_HOP_RESPONSE_HEADERS:
                out.append(k, v)
        if not out.has("x-request-id"):
            out.set("x-request-id", rid)
        if not out.has("cache-control"):
            out.set("cache-control", "no-store")

        session_after = session
        session_changed = False
        for raw in uh.get_all("set-cookie"):
            parsed = parse_set_cookie(raw)
            if parsed is None:
                continue
            kind = cookie_kind_from_name(parsed.name)
            if kind is None or kind == "csrf":
                continue
            jar.set_from_upstream(kind, parsed)
            if kind == "session":
                session_changed = True
                cleared = parsed.value == "" or (parsed.max_age is not None and parsed.max_age <= 0)
                session_after = None if cleared else parsed.value
        if status == 401 and session and not session_changed:
            try:
                code = json.loads(ubody).get("code")
            except (ValueError, AttributeError, UnicodeDecodeError):
                code = None
            if isinstance(code, str) and code in ENDED_SESSION_CODES:
                jar.set_from_upstream("session", ParsedSetCookie("session", "", max_age=0))
                session_changed = True
                session_after = None
        self._csrf_set_if_needed(jar, config, session_after, force=session_changed)
        for c in jar.set_cookie_headers():
            out.append("set-cookie", c)
        no_body = method == "HEAD" or status in (204, 304)
        return Response(status, out, b"" if no_body else ubody)

    def _csrf_bootstrap(self, jar: CookieJar, config: EdgeConfig, rid: str) -> Response:
        h = Headers()
        h.set("cache-control", "no-store")
        h.set("x-request-id", rid)
        existing = jar.get("csrf")
        if not existing or not csrf.verify(config.csrf_keys[:1], existing, jar.get("session")):
            jar.set_csrf(csrf.mint(config.csrf_keys[0], jar.get("session")))
        elif config.packing == "session":
            # Hosting hides the readable cookie from us: it may be gone (browser restart) while
            # the packed copy is valid. Re-send it with the same value so JS can read it again.
            jar.reissue_visible_csrf()
        for c in jar.set_cookie_headers():
            h.append("set-cookie", c)
        return Response(204, h, b"")

    # ------------------------------------------------------------------ /_bff/session (SPA)

    async def _session_probe(
        self, scope: Scope, h: Headers, jar: CookieJar, config: EdgeConfig, rid: str
    ) -> Response:
        if not _same_origin_ok(h, config):
            return _csrf_failed(rid)
        refreshed = False
        if not jar.get("session") and jar.get("remember"):
            refreshed = await self._remember_refresh(scope, h, jar, config)
        self._csrf_set_if_needed(jar, config, jar.get("session"), force=refreshed)
        out = Headers()
        out.set("content-type", "application/json")
        out.set("cache-control", "no-store")
        out.set("x-request-id", rid)
        for c in jar.set_cookie_headers():
            out.append("set-cookie", c)
        body = json.dumps({"session": jar.get("session") is not None, "refreshed": refreshed}).encode()
        return Response(200, out, body)

    async def _remember_refresh(self, scope: Scope, h: Headers, jar: CookieJar, config: EdgeConfig) -> bool:
        """Port of lib/bff/remember.ts ``refreshRememberedSession``; True when re-authenticated."""
        remember = jar.get("remember") or ""
        clear = ParsedSetCookie("remember", "", max_age=0)
        if not config.service_token:
            return False
        if len(remember) < 16 or len(remember) > 128:
            jar.set_from_upstream("remember", clear)
            return False
        up = Headers()
        up.set("content-type", "application/json")
        up.set("accept", "application/json")
        up.set("accept-encoding", "identity")
        up.set("authorization", f"Service {config.service_token}")
        up.set("x-request-id", uuid7())
        up.set("traceparent", new_traceparent())
        for name in ("user-agent", "accept-language"):
            v = h.get(name)
            if v:
                up.set(name, v)
        cookies_up = [f"__Host-td_remember={remember}"]
        device = jar.get("device")
        if device:
            up.set("x-td-device", device)
            cookies_up.append(f"__Host-td_device={device}")
        up.set("cookie", "; ".join(cookies_up))
        ip = self._client_ip(h, config)
        if ip:
            up.set("x-td-client-ip", ip)
            up.set("x-forwarded-for", ip)
        try:
            status, uh, ubody = await asyncio.wait_for(
                call_asgi(
                    self.api,
                    method="POST",
                    raw_path=API_PREFIX + REMEMBER_REFRESH_PATH,
                    query=b"",
                    headers=up,
                    body=json.dumps({"remember_token": remember}).encode(),
                    client=scope.get("client"),
                ),
                config.proxy_timeout_s,
            )
        except Exception:
            return False
        if status in (400, 401, 403, 422):
            jar.set_from_upstream("remember", clear)
            return False
        if status != 200:
            return False
        try:
            result = json.loads(ubody).get("result")
        except (ValueError, AttributeError, UnicodeDecodeError):
            result = None
        if result != "authenticated":
            return False
        parsed_cookies = [p for p in (parse_set_cookie(c) for c in uh.get_all("set-cookie")) if p is not None]
        new_session = next(
            (
                p.value
                for p in parsed_cookies
                if cookie_kind_from_name(p.name) == "session"
                and p.value
                and (p.max_age is None or p.max_age > 0)
            ),
            None,
        )
        if not new_session:
            return False
        for p in parsed_cookies:
            kind = cookie_kind_from_name(p.name)
            if kind and kind != "csrf":
                jar.set_from_upstream(kind, p)
        return True
