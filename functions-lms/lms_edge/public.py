"""Public admissions bridge for the company website: port of lib/bff/public-admissions.ts.

Cross-origin, cookie-less, strict CORS allow-list (``TD_ADMISSIONS_ALLOWED_ORIGINS`` / ``TD_WEBSITE_URL``
/ ``NEXT_PUBLIC_SITE_URL``). Multipart uploads (``data`` JSON + ``proof``/``resume`` files) are
checked (size, magic bytes) and forwarded to the API as JSON with base64 files, the service token
and the attributed client IP. Same paths, statuses, messages and headers as the Next.js handler.
"""

from __future__ import annotations

import base64
import json
import re
from email import policy
from email.parser import BytesParser
from typing import TYPE_CHECKING, Any

from lms_edge.config import ConfigError
from lms_edge.http import Headers, Receive, Response, Scope, call_asgi, read_body, resolve_client_ip, uuid7

if TYPE_CHECKING:
    from lms_edge.app import EdgeApp

PUBLIC_PREFIX = "/api/public/admissions/"
COURSE_STATUS_PATHNAME = "/api/public/courses/status"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_BODY_BYTES = 5 * 1024 * 1024
JSON_MAX = 16 * 1024
_PLAN_RE = re.compile(r"^plans/([a-z0-9][a-z0-9-]{0,79})$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

PROOF_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "application/pdf"})
RESUME_TYPES = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)


def resolve_route(method: str, path: str) -> tuple[str, str, str] | None:
    """``(method, upstream path, kind)`` for the four public endpoints, else ``None``."""
    m = _PLAN_RE.match(path)
    if m and method == "GET":
        return ("GET", f"public/admissions/plans/{m.group(1)}", "plain")
    if method != "POST":
        return None
    if path == "registrations":
        return ("POST", "public/admissions/registrations", "multipart")
    if path == "claims":
        return ("POST", "public/admissions/claims", "multipart")
    if path == "status":
        return ("POST", "public/admissions/status", "json")
    return None


def sniff(b: bytes) -> str:
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:5] == b"%PDF-":
        return "application/pdf"
    if b[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "application/msword"
    if b[:4] == b"PK\x03\x04":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return ""


def _cors(origin: str | None, allowed: frozenset[str]) -> Headers:
    h = Headers()
    h.set("vary", "Origin")
    h.set("cache-control", "no-store")
    h.set("x-content-type-options", "nosniff")
    if origin and origin in allowed:
        h.set("access-control-allow-origin", origin)
        h.set("access-control-allow-methods", "GET, POST, OPTIONS")
        h.set("access-control-allow-headers", "content-type")
        h.set("access-control-max-age", "600")
    return h


def _problem(
    status: int, code: str, detail: str, h: Headers, rid: str, extra: dict[str, Any] | None = None
) -> Response:
    h.set("content-type", "application/problem+json")
    h.set("x-request-id", rid)
    body = {
        "type": f"https://techdrona.in/problems/{code}",
        "title": detail,
        "status": status,
        "detail": detail,
        "code": code,
        "request_id": rid,
        **(extra or {}),
    }
    return Response(status, h, json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode())


def _field_problem(field: str, message: str, h: Headers, rid: str) -> Response:
    return _problem(
        422,
        "validation_failed",
        message,
        h,
        rid,
        {"errors": [{"field": field, "code": "invalid_file", "message": message}]},
    )


class FormPart:
    def __init__(self, data: bytes, filename: str | None) -> None:
        self.data = data
        self.filename = filename

    @property
    def is_file(self) -> bool:
        return self.filename is not None


def parse_multipart(content_type: str, body: bytes) -> dict[str, FormPart]:
    """multipart/form-data -> first part per field name (stdlib ``email`` parser)."""
    msg = BytesParser(policy=policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    if not msg.is_multipart():
        raise ValueError("not multipart")
    out: dict[str, FormPart] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name or name in out:
            continue
        filename = part.get_param("filename", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        out[str(name)] = FormPart(payload, None if filename is None else str(filename))
    return out


def _file_field(form: dict[str, FormPart], name: str, required: bool) -> tuple[bool, Any]:
    f = form.get(name)
    if f is None or (not f.is_file and f.data == b""):
        return (False, "Upload the payment screenshot or receipt.") if required else (True, None)
    if not f.is_file:
        return False, "The file could not be read. Choose it again."
    if len(f.data) > MAX_FILE_BYTES:
        return False, "That file is too large. The limit is 2 MB."
    if len(f.data) < 100:
        return False, "That file is empty or damaged."
    real = sniff(f.data)
    if real not in (PROOF_TYPES if name == "proof" else RESUME_TYPES):
        return False, (
            "Upload your resume as a PDF or Word file."
            if name == "resume"
            else "Upload a JPG, PNG or WebP screenshot, or a PDF receipt."
        )
    value = {"filename": (f.filename or name)[:200], "data_b64": base64.b64encode(f.data).decode("ascii")}
    orig = form.get(f"{name}_sha256")
    if orig is not None and not orig.is_file:
        s = orig.data.decode("utf-8", "replace")
        if _SHA_RE.match(s):
            value["original_sha256"] = s
    return True, value


async def handle_public(edge: EdgeApp, scope: Scope, receive: Receive, raw_path: str) -> Response:
    rid = uuid7()
    h = Headers(scope.get("headers"))
    try:
        config = edge.config()
    except ConfigError:
        config = None
    allowed = config.admissions_origins if config else frozenset()
    origin = h.get("origin")
    headers = _cors(origin, allowed)
    method = scope["method"].upper()
    course_status = raw_path == COURSE_STATUS_PATHNAME
    path = "" if course_status else raw_path[len(PUBLIC_PREFIX) :]

    if method == "OPTIONS":
        if not origin or origin not in allowed:
            return _problem(403, "permission_denied", "Origin not allowed.", headers, rid)
        return Response(204, headers, b"")
    if course_status:
        route = ("GET", "public/courses/status", "plain") if method == "GET" else None
    else:
        route = resolve_route(method, path)
    if route is None:
        return _problem(404, "not_found", "Not found.", headers, rid)
    if origin is not None and origin not in allowed:
        return _problem(403, "permission_denied", "Origin not allowed.", headers, rid)
    if method == "POST" and origin is None:
        return _problem(403, "permission_denied", "Origin required.", headers, rid)
    if config is None:
        return _problem(503, "service_unavailable", "The service is temporarily unavailable.", headers, rid)

    up_method, upstream, kind = route
    body: bytes | None = None
    if kind != "plain":
        limit = JSON_MAX if kind == "json" else MAX_BODY_BYTES
        try:
            declared = int(h.get("content-length") or "")
        except ValueError:
            declared = None
        if declared is not None and declared > limit:
            return _problem(
                413, "payload_too_large", "The request is too large.", headers, rid, {"max_bytes": limit}
            )
        ct = (h.get("content-type") or "").lower()
        if kind == "json":
            if not ct.startswith("application/json"):
                return _problem(415, "unsupported_media_type", "Send JSON.", headers, rid)
            raw, too_large = await read_body(receive, None)
            text = raw.decode("utf-8", "replace")
            if too_large or len(text) > JSON_MAX:
                return _problem(
                    413,
                    "payload_too_large",
                    "The request is too large.",
                    headers,
                    rid,
                    {"max_bytes": JSON_MAX},
                )
            body = raw
        else:
            if not ct.startswith("multipart/form-data"):
                return _problem(
                    415, "unsupported_media_type", "Send the form as multipart/form-data.", headers, rid
                )
            raw, too_large = await read_body(receive, MAX_BODY_BYTES)
            if too_large:
                return _problem(
                    413,
                    "payload_too_large",
                    "The request is too large.",
                    headers,
                    rid,
                    {"max_bytes": MAX_BODY_BYTES},
                )
            try:
                form = parse_multipart(h.get("content-type") or "", raw)
            except Exception:
                return _problem(
                    400, "validation_failed", "The form could not be read.", headers, rid, {"errors": []}
                )
            data_part = form.get("data")
            try:
                if data_part is None or data_part.is_file or len(data_part.data.decode("utf-8")) > JSON_MAX:
                    raise ValueError
                data = json.loads(data_part.data.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError
            except (ValueError, UnicodeDecodeError):
                return _problem(
                    400, "validation_failed", "The form could not be read.", headers, rid, {"errors": []}
                )
            ok, proof = _file_field(form, "proof", True)
            if not ok:
                return _field_problem("proof", proof, headers, rid)
            out: dict[str, Any] = {**data, "proof": proof}
            out.pop("resume", None)
            if upstream.endswith("registrations"):
                ok, resume = _file_field(form, "resume", False)
                if not ok:
                    return _field_problem("resume", resume, headers, rid)
                if resume:
                    out["resume"] = resume
            body = json.dumps(out, ensure_ascii=False).encode()

    up = Headers()
    up.set("accept", "application/json")
    up.set("x-request-id", rid)
    up.set("accept-encoding", "identity")
    if body is not None:
        up.set("content-type", "application/json")
    if config.service_token:
        up.set("authorization", f"Service {config.service_token}")
    ip = resolve_client_ip(h, config.trusted_proxy_hops, trust_viewer_address=config.trust_viewer_address)
    if ip:
        up.set("x-td-client-ip", ip)
    ua = h.get("user-agent")
    if ua:
        up.set("user-agent", ua[:300])
    import asyncio

    try:
        status, uh, ubody = await asyncio.wait_for(
            call_asgi(
                edge.api,
                method=up_method,
                raw_path=f"/api/v1/{upstream}",
                query=b"",
                headers=up,
                body=body or b"",
                client=scope.get("client"),
            ),
            config.proxy_timeout_s,
        )
    except Exception:
        return _problem(
            503, "service_unavailable", "We could not reach the service. Please try again.", headers, rid
        )
    ct_up = uh.get("content-type")
    if ct_up:
        headers.set("content-type", ct_up)
    headers.set("x-request-id", uh.get("x-request-id") or rid)
    retry = uh.get("retry-after")
    if retry:
        headers.set("retry-after", retry)
    return Response(status, headers, b"" if status == 204 else ubody)
