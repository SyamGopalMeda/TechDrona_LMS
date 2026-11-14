"""ORM row <-> Firestore document codec for the access modules (identity, sessions, rbac, orgs).

One mapper per table, derived from the SQLAlchemy model, is used by **both** the backfill
(Postgres row dict -> document) and the Firestore repositories (ORM instance <-> document), so a
verified backfill means the repository reads exactly what Postgres had (docs/firebase/p2.md).

Column type -> stored value:

* UUID -> ``str``; ``UUID[]`` -> ``list[str]``
* ``bytea`` -> lower-case hex ``str`` (verify hashes canonical JSON, which has no bytes; the
  TOTP ciphertext and wrapped key stay encrypted exactly as in Postgres — only the transport
  encoding changes); ``bytea[]`` -> ``list[str]``
* ``inet`` -> ``str``; ``date`` / ``time`` -> ISO ``str``; ``timestamptz`` -> UTC ``datetime``
* everything else (text, int, bool, text[], jsonb) unchanged

Repositories hand callers **transient ORM instances** (never attached to a session) carrying the
same attribute names and Python types as rows loaded by SQLAlchemy, so serializers and the
calling code do not change.
"""

from __future__ import annotations

import ipaddress
import uuid
from collections.abc import Mapping
from datetime import date, datetime, time
from functools import cache
from typing import Any, TypeVar, cast

from sqlalchemy import Date, DateTime, LargeBinary, Time
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import ARRAY, INET
from sqlalchemy.types import Uuid

from app.core.time import ensure_utc

M = TypeVar("M")

_TIME = "time"
# kinds
_UUID, _BYTES, _UUIDS, _BYTESS, _INET, _DATE, _DT, _PLAIN = (
    "uuid",
    "bytes",
    "uuid[]",
    "bytes[]",
    "inet",
    "date",
    "dt",
    "plain",
)


def _kind(t: Any) -> str:
    if isinstance(t, ARRAY):
        inner = _kind(t.item_type)
        return {_UUID: _UUIDS, _BYTES: _BYTESS}.get(inner, _PLAIN)
    if isinstance(t, Uuid):
        return _UUID
    if isinstance(t, LargeBinary):
        return _BYTES
    if isinstance(t, INET):
        return _INET
    if isinstance(t, DateTime):
        return _DT
    if isinstance(t, Date):
        return _DATE
    if isinstance(t, Time):
        return _TIME
    return _PLAIN


@cache
def columns(model: Any) -> dict[str, tuple[str, str]]:
    """attribute name -> (column name, kind) for every mapped column of ``model``."""
    out: dict[str, tuple[str, str]] = {}
    attr: Any
    for attr in sa_inspect(model).column_attrs:
        col = attr.columns[0]
        out[attr.key] = (col.name, _kind(col.type))
    return out


def _enc(kind: str, v: Any) -> Any:
    if v is None:
        return None
    if kind == _UUID:
        return str(v)
    if kind == _BYTES:
        return bytes(v).hex()
    if kind == _UUIDS:
        return [str(x) for x in v]
    if kind == _BYTESS:
        return [bytes(x).hex() for x in v]
    if kind == _INET:
        return str(v)
    if kind == _DATE:
        return v.isoformat() if isinstance(v, date) else str(v)
    if kind == _DT:
        return ensure_utc(v) if isinstance(v, datetime) else v
    if kind == _TIME:
        return v.isoformat() if isinstance(v, time) else str(v)
    if isinstance(
        v, (ipaddress.IPv4Address, ipaddress.IPv6Address, ipaddress.IPv4Network, ipaddress.IPv6Network)
    ):
        return str(v)
    if isinstance(v, tuple):
        return list(v)
    return v


def _dec(kind: str, v: Any) -> Any:
    if v is None:
        return None
    if kind == _UUID:
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    if kind == _BYTES:
        return v if isinstance(v, bytes) else bytes.fromhex(v)
    if kind == _UUIDS:
        return [x if isinstance(x, uuid.UUID) else uuid.UUID(str(x)) for x in v]
    if kind == _BYTESS:
        return [x if isinstance(x, bytes) else bytes.fromhex(x) for x in v]
    if kind == _DATE:
        return v if isinstance(v, date) else date.fromisoformat(v)
    if kind == _DT:
        return ensure_utc(v) if isinstance(v, datetime) else v
    if kind == _TIME:
        return v if isinstance(v, time) else time.fromisoformat(v)
    return v


def row_doc(model: type, row: Mapping[str, Any]) -> dict[str, Any]:
    """Postgres row (``SELECT *`` mapping, keyed by column name) -> document."""
    return {attr: _enc(kind, row.get(col)) for attr, (col, kind) in columns(model).items()}


def obj_doc(obj: Any) -> dict[str, Any]:
    """ORM instance -> document (the same shape as ``row_doc``)."""
    return {
        attr: _enc(kind, getattr(obj, attr, None))
        for attr, (_c, kind) in columns(cast(Any, type(obj))).items()
    }


def doc_obj(model: type[M], data: Mapping[str, Any]) -> M:  # noqa: UP047
    """Document -> transient ORM instance (same attribute types as a loaded row)."""
    obj = model()
    for attr, (_c, kind) in columns(cast(Any, model)).items():
        setattr(obj, attr, _dec(kind, data.get(attr)))
    if _load_hook is not None:
        _load_hook(obj)
    return obj


_load_hook: Any = None


def set_load_hook(fn: Any) -> None:
    """``fs_uow`` registers itself here to track loaded objects (unit of work)."""
    global _load_hook
    _load_hook = fn


def enc_value(model: type, attr: str, v: Any) -> Any:
    """Encode one attribute value for a query filter / partial update."""
    return _enc(columns(model)[attr][1], v)


def _default(col: Any, now: datetime) -> Any:
    sd = col.server_default
    if sd is None:
        return None
    arg = getattr(sd, "arg", None)
    if not isinstance(arg, str):
        return now if _kind(col.type) == _DT else None  # func.now()
    if isinstance(col.type, ARRAY):
        return [] if arg.strip() == "{}" else None
    try:
        py = col.type.python_type
    except NotImplementedError:
        return arg
    if py is bool:
        return arg.strip().lower() == "true"
    if py is int:
        return int(arg)
    return arg


def with_defaults(model: type, doc: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Fill ``None`` values with the column's server default (what an INSERT would store)."""
    out = dict(doc)
    attr: Any
    for attr in sa_inspect(model).column_attrs:
        col = attr.columns[0]
        if out.get(attr.key) is None and col.server_default is not None and col.computed is None:
            out[attr.key] = _enc(_kind(col.type), _default(col, now))
    return out
