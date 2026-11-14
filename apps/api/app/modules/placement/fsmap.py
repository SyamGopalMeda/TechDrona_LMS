"""Generic row <-> Firestore document mapping for one-document-per-row collections.

Used by the placement and assessments store specs; ``app/modules/coding/fsmap.py`` is a copy
because coding may not import placement (module dependency direction). Candidate for
``app/core/firestore`` (request in docs/firebase/agents/data-assess.md).

Value mapping (exact inverse in ``orm_of``):

* UUID -> str; ``uuid[]`` -> list of str; other arrays -> list.
* ``numeric(p, s)`` -> canonical decimal string with the column's scale (Firestore has no
  decimal type and the codec refuses floats for money-like values): ``Decimal("1")`` -> ``"1.00"``.
* ``bytea`` -> base64 string (the backfill checksum hashes canonical JSON, which has no bytes).
* ``inet`` -> str. JSONB, text, ints, bools and timestamps verbatim (UTC).
"""

from __future__ import annotations

import base64
import functools
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, DateTime, LargeBinary, Numeric
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.ids import compose_id


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


def _dt(v: Any) -> datetime | None:
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
        return _dt(v)
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


def orm_of[T](model: type[T], d: dict[str, Any]) -> T:
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
