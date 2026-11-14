"""Shared row <-> Firestore document codecs (promoted from the module copies; NEW, 2026-11-12).

Two codec families exist in the migrated modules and they store values DIFFERENTLY, so both are
kept verbatim (a module must keep the family its backfilled documents were written with):

**Family "json"** -- used by learning, engage and mentoring.
``encode`` / ``decode`` / ``doc_mapper`` / ``doc_of`` / ``orm_of`` / ``as_dt`` / ``as_uuid``:

* UUID -> str; ``ARRAY(uuid)`` -> list[str]; ``Numeric`` -> str (unscaled, ``Decimal(str)``)
* ``LargeBinary`` -> **hex** str; ``Date`` -> ISO str; tz-aware ``DateTime`` -> UTC timestamp
* JSONB as is, except a list directly inside a list is wrapped as ``{"$l": [...]}``.

**Family "scaled"** -- used by placement, assessments and coding.
``to_doc_value`` / ``from_doc_value`` / ``row_doc`` / ``orm_doc`` / ``orm_of_scaled`` / ``pk_id`` /
``register_table`` (backfill ``TableMapping`` registration):

* UUID -> str; ``uuid[]`` -> list[str]; other arrays -> list
* ``numeric(p, s)`` -> decimal string quantized to the column scale (``"1.00"``)
* ``bytea`` -> **base64** str; ``inet`` -> str; JSONB, text, ints, bools, timestamps verbatim.

(``admin/fs_rows.py`` has its own ``FsRow`` class model and is not covered here.)

The per-module copies (``{learning,engage,mentoring}/fs_rows.py``, ``{placement,coding}/fsmap.py``)
were merged here on 2026-11-14; the stored document format is unchanged
(``tests/platform/test_rows.py`` pins it).
"""

from __future__ import annotations

import base64
import functools
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, JSON, Date, DateTime, LargeBinary, Numeric
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.ids import compose_id
from app.core.time import ensure_utc

NESTED = "$l"


# =========================================================================== family "json"


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


# =========================================================================== family "scaled"


def _is_uuid_array(t: Any) -> bool:
    return isinstance(t, ARRAY) and isinstance(t.item_type, PG_UUID)


def _quant(t: Any) -> Decimal:
    return Decimal(1).scaleb(-int(t.scale if t.scale is not None else 2))


def to_doc_value(col: Any, v: Any) -> Any:
    t = col.type
    if v is None:
        return None
    if isinstance(t, PG_UUID):
        return str(v)
    if isinstance(t, Numeric):
        return str(Decimal(str(v)).quantize(_quant(t)))
    if isinstance(t, LargeBinary):
        return base64.b64encode(bytes(v)).decode("ascii")
    if isinstance(t, INET):
        return str(v)
    if _is_uuid_array(t):
        return [str(x) for x in v]
    if isinstance(t, ARRAY):
        return list(v)
    return v


def _dt_scaled(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        v = v.astimezone(UTC)
        return datetime(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond, tzinfo=UTC)
    return datetime.fromisoformat(str(v)).astimezone(UTC)


def from_doc_value(col: Any, v: Any) -> Any:
    t = col.type
    if v is None:
        return None
    if _is_uuid_array(t):
        return [uuid.UUID(str(x)) for x in v]
    if isinstance(t, ARRAY):
        return list(v)
    if isinstance(t, PG_UUID):
        return uuid.UUID(str(v))
    if isinstance(t, DateTime):
        return _dt_scaled(v)
    if isinstance(t, Numeric):
        return Decimal(str(v)).quantize(_quant(t))
    if isinstance(t, LargeBinary):
        return base64.b64decode(v) if isinstance(v, str) else bytes(v)
    return v


def row_doc(model: type[Any], r: Row) -> dict[str, Any]:
    """A table row (dict of column values) -> the stored document."""
    return {c.key: to_doc_value(c, r.get(c.key)) for c in model.__table__.columns}


def orm_doc(obj: Any) -> dict[str, Any]:
    """Document of a (transient) ORM instance."""
    cols = type(obj).__table__.columns
    return row_doc(type(obj), {c.key: getattr(obj, c.key) for c in cols})


def orm_of_scaled[T](model: type[T], d: dict[str, Any]) -> T:
    """Transient ORM instance from a document (never added to a session)."""
    cols = model.__table__.columns  # type: ignore[attr-defined]
    return model(**{c.key: from_doc_value(c, d.get(c.key)) for c in cols})


def pk_id(model: type[Any]) -> Callable[[Row], str]:
    """Document id = the primary key (composite keys joined with ``compose_id``)."""
    keys = [c.key for c in model.__table__.primary_key.columns]
    # attempt_events is partitioned: PK (id, occurred_at), but id alone is unique (uuid7).
    if "id" in keys:
        keys = ["id"]
    if len(keys) == 1:
        k = keys[0]
        return lambda r: str(r[k])
    return lambda r: compose_id(*(str(r[k]) for k in keys))


def register_table(
    module: str,
    model: type[Any],
    collection: str | None = None,
    doc_id: Callable[[Row], str] | None = None,
    **kw: Any,
) -> None:
    table = model.__tablename__
    register_mapping(
        TableMapping(
            module,
            table,
            collection or table,
            doc_id or pk_id(model),
            functools.partial(row_doc, model),
            order_by=kw.pop("order_by", ", ".join(c.key for c in model.__table__.primary_key.columns)),
            **kw,
        )
    )
