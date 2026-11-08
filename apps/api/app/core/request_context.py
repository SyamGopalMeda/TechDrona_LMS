"""Per-request context (request id) shared by logging, errors and audit."""

from __future__ import annotations

import re
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("td_request_id", default=None)

# Accept an upstream (BFF) id only if it is a short, safe token.
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{8,128}$")


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> object:
    return _request_id.set(value)


def reset_request_id(token: object) -> None:
    _request_id.reset(token)  # type: ignore[arg-type]
