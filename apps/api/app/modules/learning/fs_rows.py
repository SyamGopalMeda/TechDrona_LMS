"""Generic row <-> Firestore document mapping for ORM tables (learning; copied in engage/mentoring).

The P2 mappers were hand-written per table; these modules have ~25 tables whose documents are the
row itself, so one column-type-driven codec is used by the backfill mappers (``doc_mapper``) and by
the repositories (``orm_of``), keeping "what the backfill wrote" == "what the repository reads".

Encoding (Postgres value -> document value):

* UUID -> str; ``ARRAY(uuid)`` -> list[str]
* ``Numeric`` (Decimal) -> str (exact; ``Decimal(str)`` round-trips, e.g. ``"12.50"``)
* ``LargeBinary`` -> hex str (the verify checksum is JSON; Firestore bytes are not JSON)
* ``Date`` -> ISO str; tz-aware ``DateTime`` -> UTC datetime (kept as a Firestore timestamp)
* JSONB -> as is, except that a list directly inside a list (Firestore forbids nested arrays,
  e.g. ``lesson_progress.watched_intervals``) is wrapped as ``{"$l": [...]}``.

Promote to ``app/core/firestore/rows.py`` when the coordinator merges (see the agent report).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, JSON, Date, DateTime, LargeBinary, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.time import ensure_utc

Row = dict[str, Any]
NESTED = "$l"


# --------------------------------------------------------------------------- encode


def _json_in(v: Any, *, in_list: bool = False) -> Any:
    if isinstance(v, Mapping):
        return {str(k): _json_in(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        inner = [_json_in(x, in_list=True) for x in v]
        return {NESTED: inner} if in_list else inner
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return ensure_utc(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def encode(value: Any, col_type: Any = None) -> Any:
    """One column value -> its document form (see the module docstring)."""
    if value is None:
        return None
    if isinstance(col_type, JSON):
        return _json_in(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if isinstance(value, Mapping):
        return _json_in(value)
    return value


def doc_mapper(model: Any, *, extra: Callable[[Row], dict[str, Any]] | None = None) -> Callable[[Row], Row]:
    """Mapper for ``SELECT * FROM <model table>`` rows: every column, encoded by its type."""
    cols = [(c.name, c.key, c.type) for c in model.__table__.columns]

    def to_doc(r: Row) -> Row:
        out = {key: encode(r.get(name), t) for name, key, t in cols}
        if extra is not None:
            out.update(extra(r))
        return out

    return to_doc


def doc_of(obj: Any) -> Row:
    """An ORM instance (persistent or transient) -> its document."""
    return {c.key: encode(getattr(obj, c.key), c.type) for c in type(obj).__table__.columns}


# --------------------------------------------------------------------------- decode


def _json_out(v: Any) -> Any:
    if isinstance(v, Mapping):
        if set(v) == {NESTED}:
            return [_json_out(x) for x in v[NESTED]]
        return {k: _json_out(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_json_out(x) for x in v]
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def as_dt(v: Any) -> datetime | None:
    """Firestore timestamp (DatetimeWithNanoseconds) / ISO string -> plain UTC datetime."""
    if v is None:
        return None
    if isinstance(v, datetime):
        v = v.astimezone(UTC)
        return datetime(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond, tzinfo=UTC)
    return datetime.fromisoformat(str(v)).astimezone(UTC)


def as_uuid(v: Any) -> uuid.UUID | None:
    return v if isinstance(v, uuid.UUID) else (uuid.UUID(str(v)) if v else None)


def decode(value: Any, col_type: Any) -> Any:
    if isinstance(col_type, JSON):
        return _json_out(value) if value is not None else None
    if value is None:
        return [] if isinstance(col_type, ARRAY) else None
    if isinstance(col_type, PG_UUID):
        return as_uuid(value)
    if isinstance(col_type, ARRAY):
        item = col_type.item_type
        return [as_uuid(x) if isinstance(item, PG_UUID) else x for x in value]
    if isinstance(col_type, DateTime):
        return as_dt(value)
    if isinstance(col_type, Date):
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    if isinstance(col_type, Numeric):
        return Decimal(str(value))
    if isinstance(col_type, LargeBinary):
        return bytes.fromhex(value) if isinstance(value, str) else bytes(value)
    return value


def orm_of[T](model: type[T], d: Mapping[str, Any]) -> T:
    """A transient ``model`` instance from a document (column keys only, model Python types)."""
    kw = {c.key: decode(d.get(c.key), c.type) for c in model.__table__.columns}  # type: ignore[attr-defined]
    return model(**kw)
