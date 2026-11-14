"""Typed row <-> Firestore document mapping shared by the data-ops repositories (admin, ai,
security, analytics; docs/firebase/agents/data-ops.md).

A ``FsRow`` subclass declares its columns and their kind once; the same declaration serves

* the backfill transform (``Cls.from_pg(row).doc()``: a Postgres row dict -> document), and
* the repository (``Cls.of(doc)``: document -> object with the **same attribute names and Python
  types as the ORM row**, so the existing serializers and route code are reused unchanged).

Kinds: ``uuid`` (str in Firestore), ``dt`` (Timestamp), ``str``, ``int``, ``bool``, ``float``,
``json`` (JSON text: JSONB may hold nested arrays, which Firestore cannot store, and the
int/float distinction is kept), ``map`` (plain map, for small flat JSON objects), ``list``
(list of scalars), ``uuids`` (list of UUIDs), ``hex`` (bytes as hex text), ``seconds``
(``timedelta`` as integer seconds), ``date`` (ISO date text).

``changes()`` gives the fields changed since ``of()`` (for optimistic-lock updates).
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from app.core.errors import ProblemError
from app.core.firestore.store import Doc, ScopedTransaction


def _enc(kind: str, v: Any) -> Any:
    if v is None:
        return None
    if kind == "uuid":
        return str(v)
    if kind == "uuids":
        return [str(x) for x in v]
    if kind == "json":
        return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if kind == "hex":
        return bytes(v).hex()
    if kind == "seconds":
        return int(v.total_seconds()) if isinstance(v, timedelta) else int(v)
    if kind == "interval":  # Postgres interval: {months, days, microseconds} (admin.intervals)
        from app.modules.admin.intervals import PgInterval

        return PgInterval.coerce(v).doc()  # type: ignore[union-attr]
    if kind == "date":
        return v.isoformat() if isinstance(v, date) else str(v)
    if kind == "decimal":
        return str(v)
    if kind == "int":
        return int(v)
    if kind == "float":
        return float(v)
    if kind == "bool":
        return bool(v)
    if kind == "list":
        return list(v)
    if kind == "str":
        return str(v)
    return v  # dt, map


def _dec(kind: str, v: Any) -> Any:
    if v is None:
        return None
    if kind == "uuid":
        return uuid.UUID(str(v))
    if kind == "uuids":
        return [uuid.UUID(str(x)) for x in v]
    if kind == "json":
        return json.loads(v)
    if kind == "hex":
        return bytes.fromhex(v)
    if kind == "seconds":
        return timedelta(seconds=int(v))
    if kind == "interval":  # also reads legacy plain seconds (the former "seconds" kind)
        from app.modules.admin.intervals import PgInterval

        return PgInterval.coerce(v)
    if kind == "date":
        return date.fromisoformat(v)
    if kind == "decimal":
        return Decimal(v)
    if kind == "list":
        return list(v)
    return v


class FsRow:
    KINDS: ClassVar[dict[str, str]] = {}
    DEFAULTS: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kw: Any) -> None:
        unknown = set(kw) - set(self.KINDS)
        if unknown:
            raise TypeError(f"{type(self).__name__}: unknown fields {sorted(unknown)}")
        for k in self.KINDS:
            v = kw[k] if k in kw else copy.deepcopy(self.DEFAULTS.get(k))
            setattr(self, k, list(v) if isinstance(v, list) else v)
        self._snapshot: dict[str, Any] | None = None
        self._stored_updated_at: Any = None

    if TYPE_CHECKING:  # columns are set dynamically from KINDS

        def __getattr__(self, name: str) -> Any: ...

    @classmethod
    def from_pg(cls, row: dict[str, Any]) -> FsRow:
        """A Postgres row dict (``SELECT *``); extra columns are ignored."""
        return cls(**{k: row[k] for k in cls.KINDS if k in row})

    @classmethod
    def of(cls, d: dict[str, Any] | Doc) -> Any:
        data = d.data if isinstance(d, Doc) else d
        obj = cls(**{k: _dec(kind, data.get(k)) for k, kind in cls.KINDS.items()})
        obj._snapshot = obj.doc()
        obj._stored_updated_at = data.get("updated_at")
        return obj

    def doc(self) -> dict[str, Any]:
        return {k: _enc(kind, getattr(self, k)) for k, kind in self.KINDS.items()}

    def changes(self) -> dict[str, Any]:
        cur = self.doc()
        old = self._snapshot or {}
        return {
            k: v for k, v in cur.items() if k not in ("id", "created_at", "updated_at") and old.get(k) != v
        }

    def mark_saved(self, data: dict[str, Any]) -> None:
        self._snapshot = self.doc()
        self._stored_updated_at = data.get("updated_at")

    @property
    def is_new(self) -> bool:
        return self._snapshot is None

    def __repr__(self) -> str:
        return f"{type(self).__name__}({getattr(self, 'id', '?')})"


async def save_row(
    tx: ScopedTransaction, collection: str, row: FsRow, *, current: Doc | None = None
) -> Doc | None:
    """Optimistic update of ``row`` (409 ``conflict`` when the stored document changed since it
    was read: the Firestore stand-in for ``SELECT ... FOR UPDATE``). ``current``: the document
    already read in this transaction. Returns the saved document, ``None`` when nothing changed."""
    ch = row.changes()
    if not ch:
        return None
    cur = current if current is not None else await tx.get(collection, str(row.id))
    if cur is None:
        raise ProblemError("not_found")
    if cur.get("updated_at") != row._stored_updated_at:
        raise ProblemError("conflict")
    return await tx.update_read(collection, cur, ch)


# --------------------------------------------------------------------------- model-driven rows


def kind_of_column(col: Any) -> str:
    """FsRow kind for a SQLAlchemy column (used to derive a row class from an ORM model)."""
    from sqlalchemy import (
        BigInteger,
        Boolean,
        Date,
        DateTime,
        Float,
        Integer,
        Interval,
        LargeBinary,
        Numeric,
        SmallInteger,
    )
    from sqlalchemy.dialects.postgresql import ARRAY, JSON, JSONB, UUID

    t = col.type
    if isinstance(t, ARRAY):
        return "uuids" if isinstance(t.item_type, UUID) else "list"
    if isinstance(t, UUID):
        return "uuid"
    if isinstance(t, DateTime):
        return "dt"
    if isinstance(t, Date):
        return "date"
    if isinstance(t, Boolean):
        return "bool"
    if isinstance(t, (Integer, BigInteger, SmallInteger)):
        return "int"
    if isinstance(t, Numeric) and not isinstance(t, Float):
        return "decimal"
    if isinstance(t, Float):
        return "float"
    if isinstance(t, (JSON, JSONB)):
        return "json"
    if isinstance(t, LargeBinary):
        return "hex"
    if isinstance(t, Interval):
        return "interval"
    return "str"  # Text, String, INET, CITEXT, enums


def model_row(model: Any) -> type[FsRow]:
    """An ``FsRow`` subclass with one field per column of ``model`` (same names, same kinds)."""
    cols = model.__table__.columns
    kinds = {c.key: kind_of_column(c) for c in cols}
    defaults = {c.key: d for c in cols if (d := _server_default(c, kinds[c.key])) is not _NO_DEFAULT}
    return type(
        f"{model.__name__}Row", (FsRow,), {"KINDS": kinds, "DEFAULTS": defaults, "__module__": __name__}
    )


_NO_DEFAULT = object()


def _server_default(col: Any, kind: str) -> Any:
    """The Python value of a literal server_default (what Postgres fills on INSERT), so new
    Firestore rows carry the same values. Expressions (now()) are left to the store stamps."""
    sd = getattr(col, "server_default", None)
    arg = getattr(sd, "arg", None)
    if not isinstance(arg, str):
        return _NO_DEFAULT
    raw = arg.strip().strip("'")
    try:
        if kind == "bool":
            return raw.lower() == "true"
        if kind == "int":
            return int(raw)
        if kind == "decimal":
            return Decimal(raw)
        if kind == "float":
            return float(raw)
        if kind == "json":
            import json

            return json.loads(raw)
        if kind in ("list", "uuids"):
            return [] if raw == "{}" else _NO_DEFAULT
        if kind == "str":
            return raw
    except (ValueError, ArithmeticError):
        return _NO_DEFAULT
    return _NO_DEFAULT


def pk_columns(model: Any) -> list[str]:
    return [c.key for c in model.__table__.primary_key.columns]


def model_doc_id(model: Any) -> Any:
    """Document id from the primary key: the single column, or ``compose_id`` of all of them
    (``None`` parts become ``-``; dates/datetimes use ISO text)."""
    from app.core.firestore.ids import compose_id

    pks = pk_columns(model)

    def part(v: Any) -> Any:
        if v is None:
            return "-"
        if isinstance(v, (date,)):
            return v.isoformat()
        return v

    if len(pks) == 1:
        return lambda r: str(part(r[pks[0]]))
    return lambda r: compose_id(*(part(r[k]) for k in pks))


def register_model(module: str, model: Any, spec: Any, *, where: str | None = None) -> type[FsRow]:
    """Register ``spec`` (a ``CollectionSpec``) and a 1:1 backfill mapping for ``model``'s table;
    returns the derived row class (repository and backfill share it)."""
    from app.core.firestore.backfill import TableMapping, register_mapping
    from app.core.firestore.collections import register_collection

    register_collection(spec)
    row_cls = model_row(model)
    register_mapping(
        TableMapping(
            module,
            model.__tablename__,
            spec.name,
            model_doc_id(model),
            lambda r: row_cls.from_pg(r).doc(),
            order_by=", ".join(pk_columns(model)),
            where=where,
        )
    )
    return row_cls


# --------------------------------------------------------------------------- no-Postgres helpers


def pg_system(session: Any, job: str) -> Any:
    """``async with pg_system(session, job):`` -- the Postgres platform scope when there is a
    Postgres session, a no-op on the Firebase stack (the request session is ``NO_POSTGRES``,
    falsy): Firestore repositories use named system jobs instead of RLS."""
    import contextlib

    if not session:
        return contextlib.nullcontext(session)
    from app.core.db import system_context

    return system_context(session, job)


async def emit_any(session: Any, event_type: str, payload: dict[str, Any], **kw: Any) -> Any:
    """``core.outbox.emit_event`` in the caller's Postgres transaction, or the Firestore outbox
    (its own transaction) on the Firebase stack."""
    if not session:
        from app.core.firestore.core_store import emit_event_firestore

        return await emit_event_firestore(event_type, payload, **kw)
    from app.core.outbox import emit_event

    return await emit_event(session, event_type, payload, **kw)


def idem_session(session: Any) -> Any:
    """The session to hand to ``core.idempotency.idempotent``: ``None`` on the Firebase stack
    (``NO_POSTGRES`` is falsy; the Firestore idempotency path then opens no savepoint)."""
    return session or None
