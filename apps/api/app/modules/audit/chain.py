"""Hash chain for ``audit_log`` (ADR-0011).

``row_hash = SHA-256(prev_hash ‖ canonical_json(row))`` where ``row`` holds every business
column plus ``seq``, ``occurred_at`` and ``id`` (not the hashes). Genesis ``prev_hash`` is 32
zero bytes. ``seq`` is gap-free from 1.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.time import to_rfc3339_micro

GENESIS_HASH = bytes(32)

CHAIN_FIELDS: tuple[str, ...] = (
    "seq",
    "occurred_at",
    "id",
    "actor_type",
    "actor_user_id",
    "actor_session_id",
    "actor_roles",
    "action",
    "target_type",
    "target_id",
    "organization_id",
    "subject_user_id",
    "reason_code",
    "reason",
    "before_state",
    "after_state",
    "request_id",
    "ip",
)


def _norm(field: str, v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, datetime):
        return to_rfc3339_micro(v)
    if field == "ip":
        s = str(v)
        try:
            return str(ipaddress.ip_interface(s).ip) if "/" in s else str(ipaddress.ip_address(s))
        except ValueError:
            return s
    if field == "occurred_at" and isinstance(v, str):
        return v
    if field in (
        "actor_user_id",
        "actor_session_id",
        "target_id",
        "organization_id",
        "subject_user_id",
        "id",
    ):
        return str(uuid.UUID(str(v)))
    if isinstance(v, tuple):
        return list(v)
    return v


def canonical_row(row: Mapping[str, Any]) -> bytes:
    data = {f: _norm(f, row.get(f)) for f in CHAIN_FIELDS}
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_row_hash(prev_hash: bytes, row: Mapping[str, Any]) -> bytes:
    if len(prev_hash) != 32:
        raise ValueError("prev_hash must be 32 bytes")
    return hashlib.sha256(prev_hash + canonical_row(row)).digest()


@dataclass(frozen=True, slots=True)
class ChainVerification:
    ok: bool
    checked: int
    last_seq: int | None
    last_hash: bytes | None
    first_bad_seq: int | None = None
    reason: str | None = None


def verify_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_prev_hash: bytes = GENESIS_HASH,
    expected_first_seq: int = 1,
) -> ChainVerification:
    """Recompute the chain over rows ordered by ``seq``."""
    prev = expected_prev_hash
    expected_seq = expected_first_seq
    checked = 0
    last_seq: int | None = None
    for row in rows:
        seq = int(row["seq"])
        if seq != expected_seq:
            return ChainVerification(False, checked, last_seq, prev, seq, f"gap: expected seq {expected_seq}")
        if bytes(row["prev_hash"]) != prev:
            return ChainVerification(False, checked, last_seq, prev, seq, "prev_hash mismatch")
        recomputed = compute_row_hash(prev, row)
        if bytes(row["row_hash"]) != recomputed:
            return ChainVerification(False, checked, last_seq, prev, seq, "row_hash mismatch (row altered)")
        prev = recomputed
        last_seq = seq
        expected_seq += 1
        checked += 1
    return ChainVerification(True, checked, last_seq, prev if checked else None)
