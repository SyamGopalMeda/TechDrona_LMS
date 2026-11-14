"""Deterministic document ids (MIGRATION-PLAN §1.8): uniqueness = ``create()`` on a fixed id.

``compose_id("u1", "super_admin", "platform")`` -> ``"u1:super_admin:platform"``. Parts are
escaped (``%`` ``/`` ``:``) so two different tuples can never produce the same id.
``hashed_id("email", "a@b.in")`` -> SHA-256 hex, for values that are PII or unbounded (emails,
phone numbers, tokens) — the raw value never becomes a document name.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from enum import Enum

SEPARATOR = ":"
MAX_ID_BYTES = 1500
_RESERVED = re.compile(r"^__.*__$")


def _part(p: object) -> str:
    if isinstance(p, Enum):
        p = p.value
    s = str(p) if isinstance(p, (uuid.UUID, int, str)) and not isinstance(p, bool) else None
    if s is None:
        raise TypeError(f"id parts must be str, int, UUID or Enum, not {type(p).__name__}")
    if not s:
        raise ValueError("id parts must not be empty")
    return s.replace("%", "%25").replace("/", "%2F").replace(SEPARATOR, "%3A")


def validate_id(doc_id: str) -> str:
    if not doc_id or doc_id in {".", ".."} or "/" in doc_id or _RESERVED.match(doc_id):
        raise ValueError(f"invalid Firestore document id {doc_id!r}")
    if len(doc_id.encode()) > MAX_ID_BYTES:
        raise ValueError("Firestore document id longer than 1500 bytes")
    return doc_id


def compose_id(*parts: object) -> str:
    if not parts:
        raise ValueError("compose_id needs at least one part")
    return validate_id(SEPARATOR.join(_part(p) for p in parts))


def hashed_id(namespace: str, value: str, *, normalize: bool = True) -> str:
    """SHA-256 of ``namespace\\0value`` (value lower-cased and stripped unless ``normalize=False``)."""
    v = value.strip().lower() if normalize else value
    return hashlib.sha256(f"{namespace}\0{v}".encode()).hexdigest()
