"""Cursor pagination (api-specification §1.10): opaque, HMAC-signed, 24 h expiry.

The signing key is derived from ``TD_SERVICE_TOKEN`` (HMAC(service_token, "td-cursor-v1"));
cursors therefore become invalid when the service token rotates (acceptable: 24 h TTL).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.core.config import get_settings
from app.core.errors import ProblemError

CURSOR_TTL_SECONDS = 24 * 3600
MAX_LIMIT = 100
DEFAULT_LIMIT = 25


def _key() -> bytes:
    secret = get_settings().TD_SERVICE_TOKEN or "td-local-cursor-key"
    return hmac.new(secret.encode(), b"td-cursor-v1", hashlib.sha256).digest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def encode_cursor(position: dict[str, Any]) -> str:
    payload = json.dumps({"k": position, "t": int(time.time())}, separators=(",", ":"), default=str).encode()
    sig = hmac.new(_key(), payload, hashlib.sha256).digest()[:16]
    return _b64(payload) + "." + _b64(sig)


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        p, s = cursor.split(".", 1)
        payload, sig = _unb64(p), _unb64(s)
        expected = hmac.new(_key(), payload, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        data = json.loads(payload)
        if int(time.time()) - int(data["t"]) > CURSOR_TTL_SECONDS:
            raise ValueError("expired")
        pos = data["k"]
        if not isinstance(pos, dict):
            raise ValueError("bad position")
        return pos
    except (ValueError, KeyError, TypeError) as e:
        raise ProblemError("invalid_cursor") from e


def page_meta(next_position: dict[str, Any] | None, limit: int) -> dict[str, Any]:
    return {
        "next_cursor": encode_cursor(next_position) if next_position else None,
        "has_more": next_position is not None,
        "limit": limit,
    }
