"""Signed double-submit CSRF token: byte-for-byte the algorithm of apps/web/src/lib/bff/csrf.ts.

    token   = "v1." + nonce + "." + mac          (base64url parts, no padding)
    mac     = HMAC-SHA256(TD_CSRF_KEY, "td-csrf|v1|" + binding + "|" + nonce)
    binding = "s:" + hex(SHA-256(session token))  when a session exists, else "anon"

Tokens minted by the Next.js BFF verify here and vice versa (same key), so a browser keeps its
token across the switch.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Sequence

VERSION = "v1"
NONCE_BYTES = 16
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_SIG_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def session_binding(session_token: str | None) -> str:
    if not session_token:
        return "anon"
    return "s:" + hashlib.sha256(session_token.encode("utf-8")).hexdigest()


def _mac(key: str, binding: str, nonce: str) -> str:
    msg = f"td-csrf|{VERSION}|{binding}|{nonce}".encode()
    return _b64url(hmac.new(key.encode("utf-8"), msg, hashlib.sha256).digest())


def mint(key: str, session_token: str | None) -> str:
    nonce = _b64url(secrets.token_bytes(NONCE_BYTES))
    return f"{VERSION}.{nonce}.{_mac(key, session_binding(session_token), nonce)}"


def verify(keys: Sequence[str], token: str | None, session_token: str | None) -> bool:
    if not token or len(token) > 256:
        return False
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != VERSION:
        return False
    _v, nonce, sig = parts
    if not _NONCE_RE.match(nonce) or not _SIG_RE.match(sig):
        return False
    binding = session_binding(session_token)
    ok = False
    for key in keys:  # evaluate every key (timing)
        if hmac.compare_digest(_mac(key, binding, nonce), sig):
            ok = True
    return ok


def check_double_submit(
    keys: Sequence[str], cookie_token: str | None, header_token: str | None, session_token: str | None
) -> bool:
    if not cookie_token or not header_token:
        return False
    if not hmac.compare_digest(cookie_token.encode(), header_token.encode()):
        return False
    return verify(keys, cookie_token, session_token)
