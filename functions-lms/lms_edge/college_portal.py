"""``/college-portal/*``: the College Data Portal behind the LMS session (port of the Next.js
route handler apps/web/src/lib/college-portal/proxy.ts).

browser -> Hosting ``/college-portal/**`` -> ``lmsApi`` (this module) -> Cloud Run ``college-portal``

* Every request (HTML, assets, API) is authenticated against the LMS session (``__session`` cookie,
  unpacked by ``CookieJar``) with in-process calls to ``GET /api/v1/me/grants`` + ``/api/v1/me``,
  and limited to Admin-portal users (``/admin`` in ``portals`` or a live ``super_admin`` grant).
  Failures FAIL CLOSED. Positive results are cached 60 s per instance, keyed on session + device +
  user agent; page loads and writes always re-check and count as LMS activity.
* The LMS session never reaches the portal: request headers are an allow-list; the user is
  identified with ``x-td-proxy-user`` + the shared ``x-td-proxy-secret`` (``x-td-proxy-role`` is
  always ``editor``: everyone admitted holds the Admin portal).
* Cloud Run additionally requires IAM (``roles/run.invoker`` for the function's service account):
  the request carries a Google ID token for the service URL (metadata server), unless
  ``TD_COLLEGE_PORTAL_ID_TOKEN=false`` (local runs against a plain HTTP portal).

Configuration: ``TD_COLLEGE_PORTAL_URL`` (env, the Cloud Run URL) and ``TD_COLLEGE_PORTAL_SECRET``
(Secret Manager, >= 32 characters, same value as the service's ``PORTAL_PROXY_SECRET``). Without
either, ``/college-portal/*`` answers 503. Response security headers (the portal's CSP,
``X-Frame-Options: SAMEORIGIN``, ``Cache-Control``) are also set by firebase.json, which wins.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import os
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote, urljoin, urlsplit

from lms_edge.config import ConfigError
from lms_edge.cookies import CookieJar
from lms_edge.http import (
    HOP_BY_HOP_RESPONSE_HEADERS,
    Headers,
    Receive,
    Response,
    Scope,
    call_asgi,
    new_traceparent,
    read_body,
    uuid7,
)

if TYPE_CHECKING:
    from lms_edge.app import EdgeApp

PORTAL_PREFIX = "/college-portal"
PORTAL_ENTRY = f"{PORTAL_PREFIX}/index.html"
ADMIN_PAGE = "/admin/college-data"
LOGIN_URL = f"/login?next={quote(ADMIN_PAGE, safe='')}"
MAX_BODY_BYTES = 1024 * 1024
UPSTREAM_TIMEOUT_S = 15.0
AUTH_CACHE_TTL_S = 60.0
AUTH_CACHE_MAX = 500
ALLOWED_METHODS = ("GET", "HEAD", "POST", "PATCH", "PUT", "DELETE")
UNSAFE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})
#: Browser headers that may reach the portal. Cookie, Authorization, X-CSRF-Token, X-TD-* never do.
FORWARDED_PORTAL_HEADERS = (
    "accept",
    "content-type",
    "idempotency-key",
    "if-modified-since",
    "if-none-match",
    "user-agent",
)
DROPPED_RESPONSE_HEADERS = HOP_BY_HOP_RESPONSE_HEADERS | {
    "set-cookie",
    "content-encoding",
    "content-length",
    "server",
    "alt-svc",
    "via",
    "x-cloud-trace-context",
}
ADMIN_PREFIX = "/admin"
ADMIN_ROLES = frozenset({"super_admin"})
METADATA_IDENTITY = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"

# ------------------------------------------------------------------ auth cache (per instance)

_auth_cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
_id_token: dict[str, tuple[str, float]] = {}
_clients: dict[int, Any] = {}


def reset_state() -> None:
    """Test helper."""
    _auth_cache.clear()
    _id_token.clear()
    _clients.clear()


def _cache_get(key: str, now: float) -> str | None:
    hit = _auth_cache.get(key)
    if hit is None:
        return None
    if hit[1] <= now:
        _auth_cache.pop(key, None)
        return None
    return hit[0]


def _cache_set(key: str, name: str, now: float) -> None:
    _auth_cache.pop(key, None)
    while len(_auth_cache) >= AUTH_CACHE_MAX:
        _auth_cache.popitem(last=False)
    _auth_cache[key] = (name, now + AUTH_CACHE_TTL_S)


def _auth_key(session: str, device: str, user_agent: str) -> str:
    return hashlib.sha256(f"{session}\0{device}\0{user_agent}".encode()).hexdigest()


# ------------------------------------------------------------------ config


def portal_target(env: Any = None) -> tuple[str, str] | None:
    """(base URL without trailing slash, secret) or None when not configured (fail closed)."""
    env = os.environ if env is None else env
    raw = (env.get("TD_COLLEGE_PORTAL_URL") or "").strip()
    secret = (env.get("TD_COLLEGE_PORTAL_SECRET") or "").strip()
    if not raw or len(secret) < 32:
        return None
    u = urlsplit(raw)
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    return f"{u.scheme}://{u.netloc}{u.path}".rstrip("/"), secret


def _id_token_enabled(base: str, env: Any = None) -> bool:
    env = os.environ if env is None else env
    flag = (env.get("TD_COLLEGE_PORTAL_ID_TOKEN") or "").strip().lower()
    if flag in ("false", "0", "off"):
        return False
    if flag in ("true", "1", "on"):
        return True
    return (urlsplit(base).hostname or "").endswith(".run.app")


# ------------------------------------------------------------------ helpers


def display_name_of(me: Any) -> str:
    """Audit-log actor "Name (email)", at most 100 characters (the portal's limit)."""

    def pick(v: Any) -> str | None:
        return " ".join(v.split()) if isinstance(v, str) and v.strip() else None

    me = me if isinstance(me, dict) else {}
    profile = me.get("profile") if isinstance(me.get("profile"), dict) else {}
    user = me.get("user") if isinstance(me.get("user"), dict) else {}
    name = pick(profile.get("display_name")) or pick(profile.get("full_name"))
    email = pick(user.get("email"))
    if name and email and name.lower() != email.lower():
        suffix = f" ({email})"
        return (
            f"{name[: 100 - len(suffix)].strip()}{suffix}"
            if len(suffix) < 60
            else name[:100]
        )
    return (name or email or "LMS admin")[:100]


def extract_portal_path(raw_path: str) -> tuple[str, str]:
    """("entry"|"ok"|"bad"|"not_found", rest) for the percent-encoded path."""
    if raw_path in (PORTAL_PREFIX, f"{PORTAL_PREFIX}/"):
        return "entry", ""
    if not raw_path.startswith(f"{PORTAL_PREFIX}/"):
        return "not_found", ""
    rest = raw_path[len(PORTAL_PREFIX) :]
    if len(rest) > 2048 or "\\" in rest or "\0" in rest:
        return "bad", ""
    segments = rest[1:].split("/")
    for i, seg in enumerate(segments):
        try:
            decoded = unquote(seg, errors="strict")
        except UnicodeDecodeError:
            return "bad", ""
        if decoded == "" and i < len(segments) - 1:
            return "bad", ""
        if decoded in (".", "..") or any(c in decoded for c in "/\\\0"):
            return "bad", ""
    return "ok", rest


def _is_navigation(method: str, h: Headers) -> bool:
    if method not in ("GET", "HEAD"):
        return False
    dest = h.get("sec-fetch-dest")
    if dest:
        return dest in ("document", "iframe")
    return "text/html" in (h.get("accept") or "")


def _json(
    status: int, body: dict[str, Any], extra: dict[str, str] | None = None
) -> Response:
    h = Headers()
    h.set("content-type", "application/json")
    h.set("cache-control", "private, no-store")
    h.set("x-content-type-options", "nosniff")
    for k, v in (extra or {}).items():
        h.set(k, v)
    return Response(status, h, json.dumps(body, separators=(",", ":")).encode())


def _html_page(
    status: int,
    title: str,
    message: str,
    href: str = "/admin",
    label: str = "Back to the LMS",
) -> Response:
    e = html.escape
    body = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{e(title)}</title><style>body{{font-family:system-ui,sans-serif;margin:0;padding:2rem;"
        "color:#1f2937}h1{font-size:1.25rem}a{color:#1d4ed8}</style></head><body>"
        f'<h1>{e(title)}</h1><p>{e(message)}</p><p><a href="{e(href)}" target="_top">{e(label)}</a></p>'
        "</body></html>"
    )
    h = Headers()
    h.set("content-type", "text/html; charset=utf-8")
    h.set("cache-control", "private, no-store")
    h.set("x-content-type-options", "nosniff")
    h.set("x-frame-options", "SAMEORIGIN")
    h.set(
        "content-security-policy",
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
    )
    return Response(status, h, body.encode())


def _redirect(status: int, location: str) -> Response:
    h = Headers()
    h.set("location", location)
    h.set("cache-control", "private, no-store")
    return Response(status, h, b"")


def _unauthenticated(method: str, h: Headers) -> Response:
    # Inside the admin page's frame a redirect would load /login (frame-ancestors 'none') into the
    # frame: answer in the frame with a link that leaves it.
    if h.get("sec-fetch-dest") == "iframe":
        return _html_page(
            401,
            "Signed out",
            "Your LMS session has ended. Sign in again to open the College Data Portal.",
            LOGIN_URL,
            "Sign in",
        )
    if _is_navigation(method, h):
        return _redirect(303, LOGIN_URL)
    return _json(
        401, {"error": "Please sign in to the LMS again", "code": "auth_required"}
    )


def _forbidden(method: str, h: Headers) -> Response:
    if _is_navigation(method, h):
        return _html_page(
            403,
            "Admins only",
            "The College Data Portal is available to LMS admins only.",
        )
    return _json(403, {"error": "Admins only", "code": "forbidden"})


def _unavailable(method: str, h: Headers) -> Response:
    if _is_navigation(method, h):
        return _html_page(
            503,
            "College Data Portal",
            "We could not verify your access right now. Please try again shortly.",
        )
    return _json(
        503,
        {
            "error": "Could not verify your access. Please try again.",
            "code": "auth_unavailable",
        },
        {"retry-after": "5"},
    )


def rewrite_location(location: str, base: str) -> str | None:
    """Map an upstream redirect back under /college-portal (never to another origin)."""
    base_url = f"{base}/"
    try:
        target = urlsplit(urljoin(base_url, location))
    except ValueError:
        return None
    b = urlsplit(base_url)
    if (target.scheme, target.netloc) != (b.scheme, b.netloc):
        return None
    base_path = b.path.rstrip("/")
    path = target.path
    if base_path and path.startswith(f"{base_path}/"):
        path = path[len(base_path) :]
    if not path.startswith(f"{PORTAL_PREFIX}/"):
        path = f"{PORTAL_PREFIX}{path}"
    return (
        path
        + (f"?{target.query}" if target.query else "")
        + (f"#{target.fragment}" if target.fragment else "")
    )


def _client() -> Any:
    """One httpx client per event loop (a2wsgi runs one loop per instance)."""
    import httpx

    loop = asyncio.get_running_loop()
    c = _clients.get(id(loop))
    if c is None or c.is_closed:
        c = httpx.AsyncClient(
            timeout=UPSTREAM_TIMEOUT_S, follow_redirects=False, http2=False
        )
        _clients.clear()
        _clients[id(loop)] = c
    return c


async def _fetch_id_token(audience: str) -> str:
    hit = _id_token.get(audience)
    now = time.time()
    if hit and hit[1] > now:
        return hit[0]
    r = await _client().get(
        METADATA_IDENTITY,
        params={"audience": audience, "format": "full"},
        headers={"Metadata-Flavor": "Google"},
        timeout=5.0,
    )
    r.raise_for_status()
    token = r.text.strip()
    _id_token[audience] = (token, now + 45 * 60)  # Google ID tokens live 60 min
    return token


# ------------------------------------------------------------------ authorisation


async def _api_get(
    edge: EdgeApp,
    scope: Scope,
    h: Headers,
    path: str,
    session: str,
    device: str | None,
    activity: bool,
) -> tuple[int, Any]:
    config = edge.config()
    up = Headers()
    up.set("accept", "application/json")
    up.set("accept-encoding", "identity")
    for name in ("user-agent", "accept-language"):
        v = h.get(name)
        if v:
            up.set(name, v)
    if config.service_token:
        up.set("authorization", f"Service {config.service_token}")
    up.set("x-td-session", session)
    cookies = [f"__Host-td_session={session}"]
    if device:
        up.set("x-td-device", device)
        cookies.append(f"__Host-td_device={device}")
    up.set("cookie", "; ".join(cookies))
    ip = edge._client_ip(h, config)
    if ip:
        up.set("x-td-client-ip", ip)
        up.set("x-forwarded-for", ip)
    proto, _, host = config.public_origin.partition("://")
    up.set("x-forwarded-proto", proto)
    up.set("x-forwarded-host", host)
    up.set("x-request-id", uuid7())
    up.set("traceparent", new_traceparent())
    if activity:
        up.set("x-td-activity", "navigation")
    status, _uh, body = await asyncio.wait_for(
        call_asgi(
            edge.api,
            method="GET",
            raw_path=f"/api/v1/{path}",
            query=b"",
            headers=up,
            body=b"",
            client=scope.get("client"),
        ),
        config.proxy_timeout_s,
    )
    try:
        data = json.loads(body) if body else None
    except (ValueError, UnicodeDecodeError):
        data = None
    return status, data


def is_admin(grants: Any) -> bool:
    if not isinstance(grants, dict):
        return False
    portals = grants.get("portals")
    if isinstance(portals, list) and ADMIN_PREFIX in portals:
        return True
    rows = grants.get("data")
    if isinstance(rows, list):
        return any(
            isinstance(g, dict) and g.get("role_key") in ADMIN_ROLES for g in rows
        )
    return False


async def _check_access(
    edge: EdgeApp,
    scope: Scope,
    h: Headers,
    session: str,
    device: str | None,
    activity: bool,
) -> tuple[str, str]:
    """("ok", name) | ("unauthenticated"|"forbidden"|"unavailable", "")."""
    try:
        (gs, grants), (ms, me) = await asyncio.gather(
            _api_get(edge, scope, h, "me/grants", session, device, activity),
            _api_get(edge, scope, h, "me", session, device, False),
        )
    except Exception as e:  # noqa: BLE001 - fail closed
        print(f"[college-portal] access check {type(e).__name__}")  # noqa: T201
        return "unavailable", ""
    if gs == 401:
        return "unauthenticated", ""
    if gs != 200:
        return ("forbidden", "") if gs == 403 else ("unavailable", "")
    if not is_admin(grants):
        return "forbidden", ""
    if ms == 401:
        return "unauthenticated", ""
    if ms != 200:
        return "unavailable", ""
    return "ok", display_name_of(me)


# ------------------------------------------------------------------ handler


async def handle_college_portal(
    edge: EdgeApp, scope: Scope, receive: Receive, raw_path: str
) -> Response:
    method = scope["method"].upper()
    h = Headers(scope.get("headers"))
    if method not in ALLOWED_METHODS:
        return _json(
            405, {"error": "Method not allowed"}, {"allow": ", ".join(ALLOWED_METHODS)}
        )

    kind, rest = extract_portal_path(raw_path)
    if kind == "not_found":
        return _json(404, {"error": "Not found"})
    if kind == "bad":
        return _json(400, {"error": "Invalid path", "code": "bad_path"})
    if kind == "entry":
        return _redirect(308, PORTAL_ENTRY)

    target = portal_target()
    try:
        config = edge.config()
    except ConfigError as e:
        print(f"[college-portal] LMS configuration error: {e}")  # noqa: T201
        target = None
    if target is None:
        return _json(503, {"error": "College Data Portal is not configured"})
    base, secret = target

    if config.origin_verify_value and not hmac.compare_digest(
        (h.get("x-origin-verify") or "").encode(), config.origin_verify_value.encode()
    ):
        return _json(403, {"error": "Forbidden", "code": "forbidden"})

    # Cross-site request forgery: unsafe methods only from our own pages (same rule as the BFF).
    if method in UNSAFE_METHODS:
        site = h.get("sec-fetch-site")
        origin = h.get("origin")
        if (site is not None and site not in ("same-origin", "none")) or (
            origin is not None and origin != config.public_origin
        ):
            return _json(403, {"error": "Request blocked", "code": "cross_origin"})

    # AuthN / AuthZ on every request.
    jar = CookieJar.from_header(config, h.get("cookie"))
    session = jar.get("session")
    if not session:
        return _unauthenticated(method, h)
    device = jar.get("device")
    activity = method in UNSAFE_METHODS or _is_navigation(method, h)
    key = _auth_key(session, device or "", h.get("user-agent") or "")
    now = time.time()
    name = None if activity else _cache_get(key, now)
    if name is None:
        result, name = await _check_access(edge, scope, h, session, device, activity)
        if result == "unauthenticated":
            return _unauthenticated(method, h)
        if result == "forbidden":
            return _forbidden(method, h)
        if result != "ok":
            return _unavailable(method, h)
        _cache_set(key, name, now)

    body = b""
    if method not in ("GET", "HEAD"):
        try:
            declared = int(h.get("content-length") or "")
        except ValueError:
            declared = None
        if declared is not None and declared > MAX_BODY_BYTES:
            return _json(
                413, {"error": "Request too large", "code": "payload_too_large"}
            )
        body, too_large = await read_body(receive, MAX_BODY_BYTES)
        if too_large:
            return _json(
                413, {"error": "Request too large", "code": "payload_too_large"}
            )

    up: dict[str, str] = {}
    for hname in FORWARDED_PORTAL_HEADERS:
        v = h.get(hname)
        if v is not None:
            up[hname] = v
    up["accept-encoding"] = "identity"
    up["x-td-proxy-secret"] = secret
    up["x-td-proxy-user"] = quote(name, safe="-_.!~*'()")  # encodeURIComponent
    up["x-td-proxy-role"] = "editor"
    ip = edge._client_ip(h, config)
    if ip:
        up["x-forwarded-for"] = ip
    proto, _, host = config.public_origin.partition("://")
    up["x-forwarded-proto"] = proto
    up["x-forwarded-host"] = host

    query = (scope.get("query_string") or b"").decode("latin-1")
    url = f"{base}{rest}" + (f"?{query}" if query else "")
    try:
        if _id_token_enabled(base):
            up["authorization"] = f"Bearer {await _fetch_id_token(base)}"
        r = await _client().request(
            method, url, headers=up, content=body if body else None
        )
    except Exception as e:  # noqa: BLE001
        print(
            f"[college-portal] upstream {type(e).__name__} {method} {PORTAL_PREFIX}{rest}"
        )  # noqa: T201
        return _json(
            502, {"error": "College Data Portal is unavailable"}, {"retry-after": "5"}
        )

    # The portal answers 401 only for a wrong shared secret (proxy_required), Cloud Run 401/403 for
    # a missing invoker grant: server misconfiguration, never an LMS sign-out.
    upstream_json = "json" in (r.headers.get("content-type") or "").lower()
    if r.status_code == 401 or (r.status_code == 403 and not upstream_json):
        print(
            f"[college-portal] upstream refused the request ({r.status_code}): check the secret / run.invoker"
        )  # noqa: T201
        return _json(
            502,
            {
                "error": "College Data Portal is misconfigured",
                "code": "portal_misconfigured",
            },
        )

    out = Headers()
    for k, v in r.headers.multi_items():
        if k.lower() not in DROPPED_RESPONSE_HEADERS:
            out.append(k.lower(), v)
    loc = r.headers.get("location")
    if loc is not None:
        out.delete("location")
        rewritten = rewrite_location(loc, base)
        if rewritten:
            out.set("location", rewritten)
    ctype = (r.headers.get("content-type") or "").lower()
    ucache = (r.headers.get("cache-control") or "").lower()
    sensitive = (
        rest.startswith("/api/")
        or rest == "/api"
        or ctype.startswith("text/html")
        or rest.lower().endswith((".html", ".htm"))
    )
    out.set(
        "cache-control",
        "private, no-store"
        if sensitive or "no-store" in ucache
        else "private, no-cache",
    )
    out.set("x-content-type-options", "nosniff")
    if not out.has("x-frame-options"):
        out.set("x-frame-options", "SAMEORIGIN")
    no_body = method == "HEAD" or r.status_code in (204, 304)
    return Response(r.status_code, out, b"" if no_body else r.content)
