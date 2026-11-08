"""Structured logging (structlog, JSON) with secret/PII scrubbing.

Never log tokens, passwords, OTPs, cookies, Authorization headers, CSRF values or keys.
The ``scrub`` processor redacts sensitive keys at any depth and token-looking values in
free-text fields, as a last line of defence; callers must still avoid logging secrets.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

from app.core.request_context import get_request_id

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_RE = re.compile(
    r"(pass(word|wd)?|secret|token|otp|cookie|authorization|auth_header|csrf|api[_-]?key|"
    r"private[_-]?key|hmac|session[_-]?(token|id_raw)|set-cookie|x-td-session|x-td-device|"
    r"recovery[_-]?code|totp|dsn|credential)",
    re.IGNORECASE,
)
# Values that look like secrets even under innocent keys.
_VALUE_PATTERNS = [
    re.compile(r"(?i)(bearer|service)\s+[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"(?i)__Host-td_[a-z]+=[^;\s]+"),
    re.compile(r"\$argon2id?\$[^\s\"']+"),
    re.compile(r"(?i)(password|otp|token|secret)=([^&\s]+)"),
]
_SAFE_KEYS = frozenset({"event", "level", "logger", "timestamp", "request_id", "code", "token_type"})


def _scrub_value(v: Any, depth: int = 0) -> Any:
    if depth > 6:
        return v
    if isinstance(v, Mapping):
        return {
            k: (REDACTED if _is_sensitive_key(k) else _scrub_value(val, depth + 1)) for k, val in v.items()
        }
    if isinstance(v, list | tuple):
        return type(v)(_scrub_value(i, depth + 1) for i in v)
    if isinstance(v, str):
        for pat in _VALUE_PATTERNS:
            v = pat.sub(REDACTED, v)
        return v
    return v


def _is_sensitive_key(k: object) -> bool:
    return isinstance(k, str) and k not in _SAFE_KEYS and bool(_SENSITIVE_KEY_RE.search(k))


def scrub(_logger: Any, _name: str, event_dict: MutableMapping[str, Any]) -> dict[str, Any]:
    return {k: (REDACTED if _is_sensitive_key(k) else _scrub_value(v)) for k, v in event_dict.items()}


def _add_request_id(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    rid = get_request_id()
    if rid and "request_id" not in event_dict:
        event_dict["request_id"] = rid
    return event_dict


_configured = False


def configure_logging(level: str = "INFO", fmt: str = "json", service: str = "api") -> None:
    global _configured
    renderer: Any = (
        structlog.processors.JSONRenderer() if fmt == "json" else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_request_id,
            structlog.processors.format_exc_info,
            scrub,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        # No fixed file: PrintLogger resolves sys.stdout per logger (survives stream swaps).
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    structlog.contextvars.bind_contextvars(service=service)
    if not _configured:
        logging.basicConfig(level=level, stream=sys.stdout, format="%(message)s")
        # uvicorn access logs include raw query strings; keep them off, we log our own line.
        logging.getLogger("uvicorn.access").disabled = True
    _configured = True
