"""Python <-> Firestore value mapping and cursor-position encoding.

* UUID -> str (UUIDs stay document ids / references, MIGRATION-PLAN §3).
* tz-aware datetime -> UTC datetime (naive datetimes are refused, ADR-0012). ``date`` -> ISO string.
* Enum -> value; tuple/set/frozenset -> list. Money is integer paise: ``float``/``Decimal`` amounts
  are not special-cased here, ``Decimal`` is refused (no silent rounding).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from app.core.time import ensure_utc


def to_store(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return to_store(value.value)
    if isinstance(value, Decimal):
        raise TypeError("Decimal is not stored; use integer paise / explicit ints")
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError("Firestore map keys must be strings")
            out[k] = to_store(v)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_store(v) for v in value]
    return value  # sentinels (SERVER_TIMESTAMP, Increment, ...) and refs pass through


def encode_position_value(v: Any) -> Any:
    """JSON-safe form of an order-by value for a signed pagination cursor."""
    if isinstance(v, datetime):
        return {"$dt": ensure_utc(v).isoformat()}
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    raise TypeError(f"cannot paginate on a {type(v).__name__} field")


def decode_position_value(v: Any) -> Any:
    if isinstance(v, dict) and set(v) == {"$dt"}:
        return datetime.fromisoformat(v["$dt"]).astimezone(UTC)
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    raise ValueError("bad cursor value")
