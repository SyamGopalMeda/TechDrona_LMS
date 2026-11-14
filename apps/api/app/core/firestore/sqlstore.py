"""SQL-on-Firestore engine for modules that move to Firestore without rewriting their SQL
(MIGRATION-PLAN P6; used by commerce and admissions). Edited only by the DATA-MONEY agent.

A module describes its tables once (``SqlModuleSpec``: ORM models, the Postgres RLS family of each
table, unique constraints, CHECKs, ``updated_at`` triggers, citext columns, commit-time read
checks) and gets a ``SqlStore``: ``execute / add / flush / refresh / get / begin_nested /
next_counter``. With ``TD_STORE_<MODULE>=postgres`` every call is passed to the SQLAlchemy session
unchanged. With ``firestore``:

* ``execute(stmt)`` interprets the SQLAlchemy Core subset the modules use (select with joins /
  outer joins, where with AND/OR/NOT and three-valued NULL logic, ``IN``, ``IS [NOT] [DISTINCT
  FROM]``, ``lower()``, citext equality, tuple keyset comparisons, order by with Postgres NULL
  ordering, limit / offset, ``count/sum/min/max/coalesce`` with ``GROUP BY``, correlated
  ``EXISTS``, ``UPDATE ... RETURNING``, ``INSERT ... ON CONFLICT DO NOTHING``, ``DELETE``).
  Equality / ``IN`` predicates and join keys are pushed down; everything is re-evaluated in
  memory. Statements over other modules' tables still go to Postgres; a statement mixing both is
  refused (``UnsupportedStatement``).
* Rows are transient ORM instances in a per-session identity map (**unit of work**): same row,
  same object; uncommitted changes visible to later statements of the transaction; savepoints
  roll the unit of work back too.
* The unit of work commits from SQLAlchemy's ``before_commit`` in **one Firestore transaction**:
  every row read ``FOR UPDATE``, changed or deleted must still be at the version that was read
  (optimistic replacement of the row lock; locked-but-unchanged rows are re-written with ``_lk``
  bumped so two lockers never both commit), uniqueness reservations ``uniq_<module>_*``,
  module commit checks (``commit_reads``) and CHECKs, then all writes and counters together. A
  lost race raises 409 ``conflict`` and the Postgres transaction rolls back with it.
* RLS replacement: each table's Postgres policy family (``read_all`` / ``owner`` / ``platform``)
  is applied to the caller's transaction scope (``app.user_id`` / ``app.org_ids`` /
  ``app.is_platform``); Firestore is reached through the module's named system job.

Known difference: Postgres makes a concurrent locker wait; here the loser gets 409.
"""

from __future__ import annotations

import copy
import json
import operator as pyop
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, cast

from fastapi import Depends
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    event,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql import elements, functions, operators, selectable
from sqlalchemy.sql.dml import Delete, Insert, Update
from sqlalchemy.types import BigInteger

from app.core.auth import require_active_principal
from app.core.db import get_db, get_principal_db
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.firestore.collections import CollectionSpec, get_spec, register_collection
from app.core.firestore.errors import StoreError, TransactionContentionError, UniqueViolationError
from app.core.firestore.ids import compose_id, hashed_id
from app.core.firestore.store import ScopedStore, ScopedTransaction
from app.core.principal import Principal
from app.core.time import utcnow

_IN = 30  # Firestore ``in`` limit
OUTBOX = "outbox_events"  # app.core.firestore.core_store.OUTBOX (same documents as emit_event_tx)
OUTBOX_KEY = "td_sql_outbox"


class UnsupportedStatement(StoreError):
    """A statement shape the engine does not interpret (fails loudly, never guesses)."""


class CheckViolation(StoreError):
    """A Postgres CHECK constraint of the module's schema would reject this commit."""


class _Conflict(Exception):
    pass


# =========================================================================== codec


def plain_dt(v: datetime) -> datetime:
    """Firestore ``DatetimeWithNanoseconds`` -> a plain aware UTC datetime (asyncpg's type)."""
    v = v.astimezone(UTC)
    return datetime(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond, tzinfo=UTC)


def columns(model: type[Any]) -> list[Any]:
    return list(model.__table__.columns)


def to_store_value(coltype: Any, v: Any) -> Any:
    """Column value -> Firestore value. UUID -> str, ``uuid[]`` -> list[str], numeric -> exact
    decimal string, date -> ISO string, JSONB -> canonical JSON string (nested arrays survive)."""
    if v is None:
        return None
    if isinstance(coltype, JSONB):
        return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)
    if isinstance(coltype, ARRAY):
        return [str(x) for x in v]
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return v.astimezone(UTC)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, memoryview):
        return bytes(v)
    return v


def from_store_value(coltype: Any, v: Any) -> Any:
    if v is None:
        return None
    if isinstance(coltype, JSONB):
        return json.loads(v) if isinstance(v, str) else v
    if isinstance(coltype, ARRAY):
        return [uuid.UUID(str(x)) for x in v]
    if isinstance(coltype, UUID):
        return uuid.UUID(str(v))
    if isinstance(coltype, Numeric):
        return Decimal(str(v))
    if isinstance(coltype, DateTime):
        return plain_dt(v) if isinstance(v, datetime) else datetime.fromisoformat(str(v)).astimezone(UTC)
    if isinstance(coltype, Date):
        return v if isinstance(v, date) else date.fromisoformat(str(v))
    if isinstance(coltype, (Integer, SmallInteger, BigInteger)):
        return int(v)
    if isinstance(coltype, Boolean):
        return bool(v)
    if isinstance(coltype, LargeBinary):
        return bytes(v)
    return v


def to_doc(model: type[Any], values: Any) -> dict[str, Any]:
    """A row (ORM instance or ``SELECT *`` mapping) -> the stored document."""
    get = values.get if isinstance(values, dict) else lambda k: getattr(values, k, None)
    return {c.key: to_store_value(c.type, get(c.key)) for c in columns(model)}


def from_doc(model: type[Any], data: dict[str, Any]) -> Any:
    """Stored document -> a transient ORM instance with the Postgres column types."""
    return model(**{c.key: from_store_value(c.type, data.get(c.key)) for c in columns(model)})


def model_doc_id(model: type[Any], values: Any) -> str:
    """Primary key -> document id (``str(pk)``; a composite key -> ``compose_id``)."""
    get = values.get if isinstance(values, dict) else lambda k: getattr(values, k)
    pk = [c.key for c in model.__table__.primary_key.columns]
    if len(pk) == 1:
        return str(get(pk[0]))
    return compose_id(*[get(k) for k in pk])


# =========================================================================== module spec


@dataclass(frozen=True, slots=True)
class Scope:
    user_id: str
    org_ids: frozenset[str]
    is_platform: bool

    @classmethod
    def platform(cls) -> Scope:
        return cls("", frozenset(), True)


UniqueFn = Callable[[Any], "str | None"]
CommitRead = Callable[[ScopedTransaction, list[Any]], Awaitable[None]]


@dataclass(frozen=True)
class SqlModuleSpec:
    module: str
    models: tuple[type[Any], ...]
    rls: Mapping[str, str]  # table -> "read_all" | "owner" | "platform" | "open" (RLS NONE)
    owner_field: Mapping[str, str] = field(default_factory=dict)  # default user_id
    uniques: Mapping[str, Sequence[tuple[str, UniqueFn]]] = field(default_factory=dict)
    updated_at_trigger: frozenset[str] = frozenset()
    citext: frozenset[tuple[str, str]] = frozenset()
    no_delete: frozenset[str] = frozenset()
    append_only: frozenset[str] = frozenset()  # td_app has no UPDATE
    check: Callable[[str, Any], str | None] | None = None  # CHECK name on violation
    commit_reads: tuple[CommitRead, ...] = ()  # read-phase checks in the commit transaction
    job: str = ""
    # Optional codec of a module whose collections already exist with another encoding (security:
    # ``admin.fs_rows``). ``encode(model, row) -> doc``, ``decode(model, doc) -> ORM instance``,
    # ``doc_id_of(model, row) -> str``. ``register_collections=False``: the module's own
    # ``store_specs`` already registered the collections (the engine reads them as a system job).
    encode: Callable[[type[Any], Any], dict[str, Any]] | None = None
    decode: Callable[[type[Any], dict[str, Any]], Any] | None = None
    doc_id_of: Callable[[type[Any], Any], str] | None = None
    register_collections: bool = True

    def __post_init__(self) -> None:
        missing = {m.__tablename__ for m in self.models} ^ set(self.rls)
        if missing:
            raise ValueError(f"{self.module}: RLS family missing/unknown for {sorted(missing)}")

    # attribute names kept from the first (commerce) version of the engine
    @property
    def BY_TABLE(self) -> dict[str, type[Any]]:
        return {m.__tablename__: m for m in self.models}

    @property
    def TABLES(self) -> frozenset[str]:
        return frozenset(self.rls)

    @property
    def RLS(self) -> Mapping[str, str]:
        return self.rls

    @property
    def NO_DELETE(self) -> frozenset[str]:
        return self.no_delete

    @property
    def UPDATED_AT_TRIGGER(self) -> frozenset[str]:
        return self.updated_at_trigger

    @property
    def CITEXT(self) -> frozenset[tuple[str, str]]:
        return self.citext

    @property
    def COUNTERS(self) -> str:
        return f"{self.module}_counters"

    @property
    def JOB(self) -> str:
        return self.job or self.module

    def model(self, table: str) -> type[Any]:
        return self.BY_TABLE[table]

    def doc_id(self, table: str, values: Any) -> str:
        if self.doc_id_of is not None:
            return self.doc_id_of(self.model(table), values)
        return model_doc_id(self.model(table), values)

    def to_doc(self, model: type[Any], values: Any) -> dict[str, Any]:
        return self.encode(model, values) if self.encode is not None else to_doc(model, values)

    def from_doc(self, model: type[Any], data: dict[str, Any]) -> Any:
        return self.decode(model, data) if self.decode is not None else from_doc(model, data)

    def unique_keys(self, table: str, obj: Any) -> set[tuple[str, str]]:
        out: set[tuple[str, str]] = set()
        for ns, fn in self.uniques.get(table, ()):
            v = fn(obj)
            if v is not None:
                out.add((f"{self.module}_{ns}", v))
        return out

    def check_row(self, table: str, obj: Any) -> None:
        bad = self.check(table, obj) if self.check else None
        if bad:
            raise CheckViolation(f"{table}: {bad}")


# =========================================================================== RLS


def visible(spec: SqlModuleSpec, table: str, obj: Any, scope: Scope) -> bool:
    fam = spec.rls[table]
    if scope.is_platform or fam == "open":  # ``open``: RLS NONE (the API checks permissions)
        return True
    if fam == "read_all":
        org = getattr(obj, "organization_id", None)
        return org is None or str(org) in scope.org_ids
    if fam == "owner":
        uid = getattr(obj, spec.owner_field.get(table, "user_id"), None)
        return bool(scope.user_id) and uid is not None and str(uid) == scope.user_id
    return False


def writable(spec: SqlModuleSpec, table: str, obj: Any, scope: Scope) -> bool:
    if scope.is_platform or spec.rls[table] == "open":
        return True
    return spec.rls[table] == "owner" and visible(spec, table, obj, scope)


# =========================================================================== unit of work


@dataclass
class Entry:
    table: str
    obj: Any
    doc_id: str
    loaded: dict[str, Any] | None  # stored document as read (None: inserted in this transaction)
    version: Any  # Firestore update_time as read
    scope: Scope
    keys: set[tuple[str, str]] = field(default_factory=set)  # unique keys as read
    locked: bool = False
    deleted: bool = False

    @property
    def new(self) -> bool:
        return self.loaded is None


def pk_conditions(model: type[Any], ident: Any) -> list[Any]:
    """``session.get`` identity -> one equality per primary-key column, **all** of them: a scalar
    for a single-column key; a tuple (key order) or a ``{column: value}`` mapping for a composite
    key (``(id, occurred_at)``, ``(series, fiscal_year)``, ...)."""
    pks = list(model.__table__.primary_key.columns)
    if len(pks) == 1:
        vals = [ident[pks[0].key] if isinstance(ident, dict) else ident]
    elif isinstance(ident, dict):
        vals = [ident[c.key] for c in pks]
    elif isinstance(ident, (tuple, list)):
        vals = list(ident)
    else:
        raise ValueError(f"{model.__name__}: a composite key needs a tuple or a mapping, not {ident!r}")
    if len(vals) != len(pks):
        raise ValueError(f"{model.__name__}: identity needs {len(pks)} values ({[c.key for c in pks]})")
    return [c == v for c, v in zip(pks, vals, strict=True)]


def _table_of(obj: Any) -> str:
    return str(type(obj).__tablename__)


def _apply_defaults(obj: Any, now: datetime) -> None:
    """Postgres server defaults for columns never set on a new row (the ORM's INSERT omits them)."""
    state = obj.__dict__
    for c in columns(type(obj)):
        if c.key in state or c.server_default is None:
            continue
        arg = c.server_default.arg
        if not isinstance(arg, str):  # func.now()
            val: Any = now
        elif isinstance(c.type, JSONB):
            val = json.loads(arg)
        elif isinstance(c.type, ARRAY):
            val = []
        elif isinstance(c.type, Boolean):
            val = arg.strip().lower() == "true"
        else:
            val = from_store_value(c.type, arg.strip("'"))
        setattr(obj, c.key, val)


class UnitOfWork:
    """Per-session identity map + pending writes (see the module docstring)."""

    def __init__(self, spec: SqlModuleSpec, client: Any = None) -> None:
        self.spec = spec
        self.store = ScopedStore.system(spec.JOB, client=client)
        self.entries: dict[tuple[str, str], Entry] = {}
        self.counters: dict[str, tuple[Any, int, int]] = {}  # name -> (version, base, next)
        # outbox_events captured on a stack without Postgres: committed in the same transaction
        self.outbox: list[dict[str, Any]] = []
        # before-images of the last successful commit: (collection, doc id, document | None)
        self.last_undo: list[tuple[str, str, dict[str, Any] | None]] = []
        # the request's buffered audit rows / outbox events (``app.core.request_commit``) taken by
        # this commit, written in the same transaction as the rows
        self.core_buffered: tuple[list[Any], list[Any]] = ([], [])

    # ------------------------------------------------------------------ loading

    def _query(self, table: str, filters: list[tuple[str, str, Any]]) -> Any:
        return self.store._build_query(get_spec(table), None, filters, ())  # type: ignore[arg-type]

    async def load(self, table: str, filters: list[tuple[str, str, Any]], scope: Scope) -> list[Any]:
        """Rows of ``table`` matching the pushed-down ``filters`` (Firestore) plus every row of the
        table this transaction already holds (they may have changed in memory). RLS applied."""
        seen: dict[str, Any] = {}
        in_filters = [f for f in filters if f[1] == "in"]
        queries: list[list[tuple[str, str, Any]]]
        if in_filters:
            f0 = in_filters[0]
            rest = [f for f in filters if f is not f0]
            vals = list(dict.fromkeys(f0[2]))
            queries = [[*rest, (f0[0], "in", vals[i : i + _IN])] for i in range(0, len(vals), _IN)]
        else:
            queries = [filters]
        for fl in queries:
            async for snap in self._query(table, fl).stream():
                key = (table, snap.id)
                e = self.entries.get(key)
                if e is None:
                    e = self._track(table, snap, scope)
                seen[snap.id] = e.obj
        for (t, did), e in self.entries.items():
            if t == table and did not in seen:
                seen[did] = e.obj
        out = []
        for did, obj in seen.items():
            e = self.entries[(table, did)]
            if e.deleted or not visible(self.spec, table, obj, scope):
                continue
            out.append(obj)
        return out

    def _track(self, table: str, snap: Any, scope: Scope) -> Entry:
        data = snap.to_dict() or {}
        obj = self.spec.from_doc(self.spec.model(table), data)
        e = Entry(table, obj, snap.id, data, snap.update_time, scope, self.spec.unique_keys(table, obj))
        self.entries[(table, snap.id)] = e
        return e

    def entry_of(self, obj: Any) -> Entry | None:
        table = _table_of(obj)
        e = self.entries.get((table, self.spec.doc_id(table, obj)))
        return e if e is not None and e.obj is obj else None

    def lock(self, obj: Any) -> None:
        e = self.entry_of(obj)
        if e is not None:
            e.locked = True

    # ------------------------------------------------------------------ writes

    def add(self, obj: Any, scope: Scope) -> None:
        table = _table_of(obj)
        if table not in self.spec.TABLES:
            raise UnsupportedStatement(f"{table} is not a commerce table")
        _apply_defaults(obj, utcnow())
        if not writable(self.spec, table, obj, scope):
            raise ProblemError("permission_denied", detail="new row violates row-level security policy")
        key = (table, self.spec.doc_id(table, obj))
        cur = self.entries.get(key)
        if cur is not None and cur.obj is obj:
            return
        if cur is not None and not cur.deleted:
            raise ProblemError("conflict", detail=f"{table} {key[1]} already exists")
        self.entries[key] = Entry(table, obj, key[1], None, None, scope)

    def delete(self, obj: Any, scope: Scope) -> None:
        table = _table_of(obj)
        if table in self.spec.NO_DELETE:
            raise ProblemError("permission_denied", detail=f"{table} rows cannot be deleted")
        e = self.entry_of(obj)
        if e is None:
            return
        if not writable(self.spec, table, obj, scope):
            return  # RLS: DELETE ... USING hides the row (0 rows deleted)
        if e.new:
            del self.entries[(e.table, e.doc_id)]
        else:
            e.deleted = True

    async def next_counter(self, name: str) -> int:
        cur = self.counters.get(name)
        if cur is None:
            snap = await self.store.ref(self.spec.COUNTERS, name).get()
            base = int((snap.to_dict() or {}).get("value", 0)) if snap.exists else 0
            cur = (snap.update_time if snap.exists else None, base, base)
        version, base, nxt = cur
        self.counters[name] = (version, base, nxt + 1)
        return nxt + 1

    # ------------------------------------------------------------------ savepoints

    def snapshot(self) -> Any:
        state = {k: (e, copy.copy(e.obj.__dict__), e.locked, e.deleted) for k, e in self.entries.items()}
        return state, dict(self.counters)

    def restore(self, snap: Any) -> None:
        state, counters = snap
        for k in list(self.entries):
            if k not in state:
                del self.entries[k]
        for k, (e, attrs, locked, deleted) in state.items():
            for c in columns(type(e.obj)):
                if c.key in attrs:
                    setattr(e.obj, c.key, attrs[c.key])
            e.locked, e.deleted = locked, deleted
            self.entries[k] = e
        self.counters = counters

    # ------------------------------------------------------------------ commit

    def _final(self, e: Entry) -> dict[str, Any]:
        return self.spec.to_doc(self.spec.model(e.table), e.obj)

    def dirty(self, e: Entry) -> bool:
        if e.new or e.loaded is None:
            return True
        final = self._final(e)
        return any(final.get(k) != _norm(e.loaded.get(k)) for k in final)

    @property
    def pending(self) -> bool:
        return (
            bool(self.counters)
            or bool(self.outbox)
            or any(e.new or e.deleted or e.locked or self.dirty(e) for e in self.entries.values())
        )

    async def commit(self, *, dry_run: bool = False) -> None:
        """Commit the unit of work. ``dry_run``: run every check of the commit (versions of locked /
        changed rows, uniqueness, CHECKs, the module's commit reads such as a deferred ledger
        trigger, counters) in a read-only transaction and write nothing: the Firestore equivalent of
        ``SET CONSTRAINTS ALL IMMEDIATE`` before an external side effect."""
        if not self.pending:
            if not dry_run:
                self.clear()
            return
        now = utcnow()
        work: list[tuple[Entry, Any, bool]] = []  # (entry, final doc | None, changed)
        for e in self.entries.values():
            if e.deleted:
                work.append((e, None, True))
                continue
            changed = self.dirty(e)
            if not (changed or e.locked):
                continue
            if changed and not e.new and e.table in self.spec.append_only:
                raise ProblemError("permission_denied", detail=f"{e.table} is append-only")
            if changed and not e.new and not dry_run and e.table in self.spec.UPDATED_AT_TRIGGER:
                e.obj.updated_at = now
            if changed and not writable(self.spec, e.table, e.obj, e.scope):
                raise ProblemError("permission_denied", detail="row-level security policy")
            final = self._final(e)
            self.spec.check_row(e.table, e.obj)
            work.append((e, final, changed))
        add_keys: dict[tuple[str, str], tuple[str, str]] = {}
        drop_keys: dict[tuple[str, str], tuple[str, str]] = {}
        for e, final, changed in work:
            if not changed:
                continue
            new_keys = set() if final is None else self.spec.unique_keys(e.table, e.obj)
            for k in new_keys - e.keys:
                if k in add_keys and add_keys[k] != (e.table, e.doc_id):
                    raise ProblemError("conflict", detail=f"duplicate {k[0]}")
                add_keys[k] = (e.table, e.doc_id)
            for k in e.keys - new_keys:
                drop_keys[k] = (e.table, e.doc_id)
        for k in set(add_keys) & set(drop_keys):  # moved between rows of this transaction
            drop_keys.pop(k)
        counters = dict(self.counters)
        outbox = list(self.outbox)

        async def body(tx: ScopedTransaction) -> None:
            client = tx.store.client
            # ---- reads (all before any write)
            versioned = [(e, final) for e, final, _ in work if not e.new]
            for i in range(0, len(versioned), 100):
                chunk = versioned[i : i + 100]
                refs = [tx.store.ref(e.table, e.doc_id) for e, _ in chunk]
                snaps = {s.id: s async for s in client.get_all(refs, transaction=tx.raw)}
                for e, _ in chunk:
                    s = snaps.get(e.doc_id)
                    if s is None or not s.exists or s.update_time != e.version:
                        raise _Conflict(f"{e.table}/{e.doc_id} changed since it was read")
            for name, (version, _base, _nxt) in counters.items():
                got = [
                    x
                    async for x in client.get_all(
                        [tx.store.ref(self.spec.COUNTERS, name)], transaction=tx.raw
                    )
                ]
                s = next(iter(got))
                if (s.update_time if s.exists else None) != version:
                    raise _Conflict(f"counter {name} moved")
                counter_before[name] = (s.to_dict() or {}) if s.exists else None
            uniq_reads: dict[tuple[str, str], dict[str, Any] | None] = {}
            for ns, val in list(add_keys) + list(drop_keys):
                uniq_reads[(ns, val)] = await tx.raw_get(f"uniq_{ns}", hashed_id(ns, val, normalize=False))
            for (ns, val), owner in add_keys.items():
                cur = uniq_reads[(ns, val)]
                if cur is not None and (cur.get("collection"), cur.get("doc_id")) != owner:
                    if (ns, val) not in drop_keys:
                        raise UniqueViolationError(f"uniq_{ns}", val)
            for hook in self.spec.commit_reads:
                await hook(tx, work)
            if dry_run:
                for e, final, _ in work:
                    if e.new and final is not None:
                        got = [
                            x
                            async for x in client.get_all(
                                [tx.store.ref(e.table, e.doc_id)], transaction=tx.raw
                            )
                        ]
                        if got and got[0].exists:
                            raise UniqueViolationError(e.table, e.doc_id)
                return
            # ---- writes (and their before-images, for an enclosing undo journal)
            undo.clear()
            for e, final, changed in work:
                undo.append((e.table, e.doc_id, None if e.new else dict(e.loaded or {})))
                if final is None:
                    tx.raw_delete(e.table, e.doc_id)
                elif e.new:
                    tx.raw_create(e.table, e.doc_id, final)
                else:
                    lk = int((e.loaded or {}).get("_lk", 0) or 0)
                    tx.raw_set(e.table, e.doc_id, {**final, "_lk": lk if changed else lk + 1})
            for ns, val in list(drop_keys) + list(add_keys):
                undo.append((f"uniq_{ns}", hashed_id(ns, val, normalize=False), uniq_reads[(ns, val)]))
            for name in counters:
                undo.append((self.spec.COUNTERS, name, counter_before.get(name)))
            for ev in outbox:
                undo.append((OUTBOX, ev["id"], None))
            if core_docs or core_events:
                from app.modules.audit.store_specs import OUTBOX as AUDIT_OUTBOX

                undo.extend((AUDIT_OUTBOX, str(d.id), None) for d in core_docs)
                undo.extend((OUTBOX, str(e.id), None) for e in core_events)
            for (ns, val), owner in drop_keys.items():
                cur = uniq_reads[(ns, val)]
                if cur is not None and (cur.get("collection"), cur.get("doc_id")) == owner:
                    tx.raw_delete(f"uniq_{ns}", hashed_id(ns, val, normalize=False))
            for (ns, val), owner in add_keys.items():
                tx.raw_set(
                    f"uniq_{ns}",
                    hashed_id(ns, val, normalize=False),
                    {"collection": owner[0], "doc_id": owner[1], "created_at": now},
                )
            for name, (_v, _base, nxt) in counters.items():
                tx.raw_set(self.spec.COUNTERS, name, {"value": nxt, "updated_at": now})
            from app.core.firestore.core_store import event_doc

            for ev in outbox:
                tx.raw_create(
                    OUTBOX,
                    ev["id"],
                    event_doc(
                        ev["event_id"],
                        ev["event_type"],
                        ev["payload"],
                        ev["aggregate_type"],
                        ev["aggregate_id"],
                        ev["organization_id"],
                        now,
                    ),
                )
            if core_docs or core_events:  # the request's buffered audit rows / events, same commit
                from app.core import audit as core_audit
                from app.core import outbox as core_outbox

                core_audit.write_pending(tx, core_docs)
                core_outbox.write_pending_events(tx, core_events)

        undo: list[tuple[str, str, dict[str, Any] | None]] = []
        counter_before: dict[str, dict[str, Any] | None] = {}
        core_docs, core_events = ([], []) if dry_run else self.core_buffered
        self.core_buffered = ([], [])
        try:
            await self.store.run_transaction(body)
        except (_Conflict, TransactionContentionError) as e:
            raise ProblemError(
                "conflict", detail="Another request changed this at the same time. Refresh and try again."
            ) from e
        except UniqueViolationError as e:
            raise ProblemError(
                "conflict", detail="Another request changed this at the same time. Refresh and try again."
            ) from e
        if not dry_run:
            if core_docs or core_events:
                from app.core import audit as core_audit
                from app.core import outbox as core_outbox

                core_audit.mark_written(core_docs)
                core_outbox.mark_events_written(core_events)
            self.clear()
            self.last_undo = list(reversed(undo))

    def clear(self) -> None:
        self.entries.clear()
        self.counters.clear()
        self.outbox.clear()

    def undo_callback(self) -> Callable[[], Awaitable[None]] | None:
        """A compensation restoring every document of the last commit to its before-image
        (created documents are deleted), in one transaction. For an enclosing undo journal."""
        log = list(self.last_undo)
        if not log:
            return None
        store = self.store

        async def restore() -> None:
            async def fn(tx: ScopedTransaction) -> None:
                for coll, doc_id, before in log:
                    if before is None:
                        tx.raw_delete(coll, doc_id)
                    else:
                        tx.raw_set(coll, doc_id, before)

            await store.run_transaction(fn)

        return restore


def _norm(v: Any) -> Any:
    if isinstance(v, datetime):
        return plain_dt(v)
    return v


# =========================================================================== results


class Result:
    def __init__(self, rows: list[tuple[Any, ...]], keys: list[str], rowcount: int | None = None) -> None:
        self._rows = rows
        self._keys = keys
        self.rowcount = len(rows) if rowcount is None else rowcount

    def _one(self, rows: list[Any]) -> Any:
        if len(rows) != 1:
            from sqlalchemy.exc import MultipleResultsFound, NoResultFound

            raise (NoResultFound if not rows else MultipleResultsFound)(
                "No row was found when one was required" if not rows else "Multiple rows were found"
            )
        return rows[0]

    def scalars(self) -> Scalars:
        return Scalars([r[0] for r in self._rows])

    def scalar_one(self) -> Any:
        return self._one(self._rows)[0]

    def scalar_one_or_none(self) -> Any:
        if not self._rows:
            return None
        return self._one(self._rows)[0]

    def scalar(self) -> Any:
        return self._rows[0][0] if self._rows else None

    def all(self) -> list[Any]:
        return [_RowT(r, self._keys) for r in self._rows]

    def fetchall(self) -> list[Any]:
        return self.all()

    def one(self) -> Any:
        return _RowT(self._one(self._rows), self._keys)

    def one_or_none(self) -> Any:
        return None if not self._rows else self.one()

    def first(self) -> Any:
        return _RowT(self._rows[0], self._keys) if self._rows else None

    def mappings(self) -> Any:
        return Scalars([dict(zip(self._keys, r, strict=False)) for r in self._rows])

    def __iter__(self) -> Any:
        return iter(self.all())


class Scalars:
    def __init__(self, vals: list[Any]) -> None:
        self._vals = vals

    def all(self) -> list[Any]:
        return list(self._vals)

    def first(self) -> Any:
        return self._vals[0] if self._vals else None

    def one(self) -> Any:
        return Result([(v,) for v in self._vals], ["_"]).scalar_one()

    def one_or_none(self) -> Any:
        return Result([(v,) for v in self._vals], ["_"]).scalar_one_or_none()

    def __iter__(self) -> Any:
        return iter(self._vals)


class _RowT(tuple[Any, ...]):
    """Tuple row with attribute access by column label (like ``sqlalchemy.Row``)."""

    def __new__(cls, values: tuple[Any, ...], keys: list[str]) -> _RowT:
        obj = super().__new__(cls, values)
        obj._keys = keys  # type: ignore[attr-defined]
        return obj

    def __getattr__(self, name: str) -> Any:
        keys = object.__getattribute__(self, "_keys")
        if name in keys:
            return self[keys.index(name)]
        raise AttributeError(name)

    def _asdict(self) -> dict[str, Any]:
        return dict(zip(object.__getattribute__(self, "_keys"), self, strict=False))


# =========================================================================== interpreter

Env = dict[str, Any]  # table name -> ORM instance (or None for an outer-join miss)

_CMP = {
    operators.eq: pyop.eq,
    operators.ne: pyop.ne,
    operators.lt: pyop.lt,
    operators.le: pyop.le,
    operators.gt: pyop.gt,
    operators.ge: pyop.ge,
}
_AGG = {"count", "sum", "min", "max"}


def _clause(x: Any) -> Any:
    return x.__clause_element__() if hasattr(x, "__clause_element__") else x


def _table_name(t: Any) -> str | None:
    name = getattr(t, "name", None)
    return name if isinstance(name, str) else None


def tables_of(stmt: Any) -> set[str]:
    """Every table a statement (and its subqueries) reads or writes."""
    from sqlalchemy.sql.visitors import iterate

    out: set[str] = set()
    for el in iterate(stmt):
        if el.__visit_name__ == "table":
            n = _table_name(el)
            if n:
                out.add(n)
    tbl = getattr(stmt, "table", None)
    if tbl is not None and _table_name(tbl):
        out.add(str(_table_name(tbl)))
    return out


def _ci(v: Any) -> Any:
    return v.lower() if isinstance(v, str) else v


class Interpreter:
    def __init__(self, uow: UnitOfWork, scope: Scope) -> None:
        self.uow = uow
        self.spec = uow.spec
        self.scope = scope
        self._subq: dict[int, list[Any]] = {}  # id(select) -> first-column values (IN subquery)

    async def _prepare_in_subqueries(self, where: Any) -> None:
        """``x IN (SELECT ...)`` with an uncorrelated subquery: run it once, keep its values."""
        from sqlalchemy.sql.visitors import iterate

        if where is None:
            return
        for el in iterate(where):
            if isinstance(el, elements.BinaryExpression) and el.operator in (
                operators.in_op,
                operators.not_in_op,
            ):
                right = el.right.element if isinstance(el.right, elements.Grouping) else el.right
                sub = _subselect(right)
                if sub is not None and id(sub) not in self._subq:
                    rows, _ = await self._select_async(sub, {})
                    self._subq[id(sub)] = [r[0] for r in rows]

    def _is_citext(self, col: Any) -> bool:
        t = getattr(col, "table", None)
        return t is not None and (_table_name(t), col.key) in self.spec.CITEXT

    # ------------------------------------------------------------------ expressions

    def ev(self, e: Any, env: Env) -> Any:
        e = _clause(e)
        if isinstance(e, elements.BindParameter):
            return e.effective_value
        if isinstance(e, elements.Null):
            return None
        if isinstance(e, elements.True_):
            return True
        if isinstance(e, elements.False_):
            return False
        if isinstance(e, (elements.Grouping, elements.Label)):
            return self.ev(e.element, env)
        if isinstance(e, elements.Cast):
            return self.ev(e.clause, env)
        if isinstance(e, elements.ColumnClause) and getattr(e, "table", None) is not None:
            name = _table_name(e.table)
            if name not in env:
                raise UnsupportedStatement(f"column {name}.{e.key} outside the FROM list")
            row = env[name]
            return None if row is None else getattr(row, e.key)
        if isinstance(e, elements.BooleanClauseList):
            vals = [self.ev(c, env) for c in e.clauses]
            if e.operator is operators.and_:
                if any(v is False for v in vals):
                    return False
                return None if any(v is None for v in vals) else True
            if e.operator is operators.or_:
                if any(v is True for v in vals):
                    return True
                return None if any(v is None for v in vals) else False
            raise UnsupportedStatement(f"boolean list {e.operator}")
        if isinstance(e, (elements.Tuple, elements.ClauseList)):
            return tuple(self.ev(c, env) for c in e.clauses)
        if isinstance(e, elements.UnaryExpression):
            if e.operator is operators.inv:
                v = self.ev(e.element, env)
                return None if v is None else not v
            if e.operator is operators.exists:
                return self._exists(e.element, env)
            if e.modifier is not None:
                return self.ev(e.element, env)
            raise UnsupportedStatement(f"unary {e.operator}")
        if isinstance(e, elements.BinaryExpression):
            return self._binary(e, env)
        if isinstance(e, selectable.Exists):
            return self._exists(e.element, env)
        if isinstance(e, selectable.ScalarSelect):
            rows, _ = self._select_sync_guard(e.element)
            return rows
        if isinstance(e, functions.FunctionElement):
            name = e.name.lower()
            args = [self.ev(a, env) for a in e.clauses]
            if name == "lower":
                return None if args[0] is None else str(args[0]).lower()
            if name == "upper":
                return None if args[0] is None else str(args[0]).upper()
            if name == "coalesce":
                return next((a for a in args if a is not None), None)
            if name == "now":
                return utcnow()
            raise UnsupportedStatement(f"function {name} outside an aggregate select")
        raise UnsupportedStatement(f"expression {type(e).__name__}")

    def _select_sync_guard(self, _sel: Any) -> Any:
        raise UnsupportedStatement("scalar subqueries are not supported; use exists() or two steps")

    def _exists(self, sel: Any, env: Env) -> bool:
        sel = _clause(sel)
        if isinstance(sel, (elements.Grouping, selectable.ScalarSelect)):
            sel = sel.element
        rows, _ = self._eval_select_rows(sel, env)
        return bool(rows)

    def _binary(self, e: Any, env: Env) -> Any:
        op = e.operator
        left = self.ev(e.left, env)
        if op in (operators.in_op, operators.not_in_op):
            right = e.right
            if isinstance(right, elements.Grouping):
                right = right.element
            sub = _subselect(right)
            if sub is not None:
                if id(sub) not in self._subq:
                    raise UnsupportedStatement("IN (subquery) was not pre-evaluated")
                vals = self._subq[id(sub)]
            else:
                vals = self.ev(right, env)
            vals = list(vals) if isinstance(vals, (list, tuple, set, frozenset)) else [vals]
            if left is None:
                return None
            ci = self._is_citext(_clause(e.left))
            hit = (_ci(left) if ci else left) in [(_ci(v) if ci else v) for v in vals]
            if not hit and any(v is None for v in vals):
                return None
            return hit if op is operators.in_op else not hit
        right = self.ev(e.right, env)
        if op in (operators.is_, operators.is_not_distinct_from):
            return (
                left == right if left is not None and right is not None else (left is None and right is None)
            )
        if op in (operators.is_not, operators.is_distinct_from):
            return not (
                left == right if left is not None and right is not None else (left is None and right is None)
            )
        if op in _CMP:
            if left is None or right is None:
                return None
            if isinstance(left, tuple):
                if any(v is None for v in left) or any(v is None for v in right):
                    return None
            if self._is_citext(_clause(e.left)) or self._is_citext(_clause(e.right)):
                left, right = _ci(left), _ci(right)
            return _CMP[op](left, right)
        if op in (operators.add, operators.sub, operators.mul):
            if left is None or right is None:
                return None
            return {operators.add: pyop.add, operators.sub: pyop.sub, operators.mul: pyop.mul}[op](
                left, right
            )
        if op in (operators.like_op, operators.ilike_op, operators.not_like_op, operators.not_ilike_op):
            if left is None or right is None:
                return None
            pat = "^" + re.escape(str(right)).replace("%", ".*").replace("_", ".") + "$"
            pat = pat.replace(r"\%", ".*").replace(r"\_", ".")
            flags = (
                re.IGNORECASE | re.DOTALL if op in (operators.ilike_op, operators.not_ilike_op) else re.DOTALL
            )
            hit = re.match(pat, str(left), flags) is not None
            return hit if op in (operators.like_op, operators.ilike_op) else not hit
        raise UnsupportedStatement(f"operator {op}")

    # ------------------------------------------------------------------ pushdown

    def _pushdown(self, where: Any, table: str) -> list[tuple[str, str, Any]]:
        """Top-level AND conjuncts ``table.col == literal`` / ``IN (literals)``."""
        out: list[tuple[str, str, Any]] = []
        model = self.spec.model(table)
        types = {c.key: c.type for c in columns(model)}
        for c in _conjuncts(where):
            if not isinstance(c, elements.BinaryExpression) or c.operator not in (
                operators.eq,
                operators.in_op,
            ):
                continue
            col, val = _clause(c.left), cast(Any, c.right)
            if isinstance(val, elements.Grouping):
                val = val.element
            if not (
                isinstance(col, elements.ColumnClause) and _table_name(getattr(col, "table", None)) == table
            ):
                continue
            if not isinstance(val, elements.BindParameter) or (table, col.key) in self.spec.CITEXT:
                continue
            from sqlalchemy.dialects.postgresql import ARRAY, JSONB

            if isinstance(types[col.key], (JSONB, ARRAY)):
                continue
            v = val.effective_value
            if c.operator is operators.eq:
                if v is None:
                    continue
                out.append((col.key, "==", to_store_value(types[col.key], v)))
            else:
                vs = [to_store_value(types[col.key], x) for x in (v or []) if x is not None]
                if not vs:
                    continue
                out.append((col.key, "in", vs))
        # Firestore allows one ``in`` per query: keep the first, the rest is checked in memory.
        ins = [f for f in out if f[1] == "in"]
        return [f for f in out if f[1] == "=="] + ins[:1]

    # ------------------------------------------------------------------ select

    async def select(self, stmt: Any, outer: Env | None = None) -> Result:
        rows, keys = await self._select_async(stmt, outer or {})
        return Result(rows, keys)

    def _eval_select_rows(self, sel: Any, outer: Env) -> Any:
        """Synchronous evaluation of a correlated subquery over rows already loaded in the
        identity map (``EXISTS`` in WHERE). The outer statement pre-loads its tables."""
        froms = [t for t in self._from_plan(sel) if t[0] not in outer]
        envs: list[Env] = [dict(outer)]
        for table, on, isouter in froms:
            cands = [e.obj for (t, _), e in self.uow.entries.items() if t == table and not e.deleted]
            cands = [o for o in cands if visible(self.spec, table, o, self.scope)]
            envs = self._join(envs, table, cands, on, isouter)
        where = sel.whereclause
        rows = [env for env in envs if where is None or self.ev(where, env) is True]
        return rows, []

    def _from_plan(self, sel: Any) -> list[tuple[str, Any, bool]]:
        plan: list[tuple[str, Any, bool]] = []

        def flat(f: Any) -> None:
            if isinstance(f, selectable.Join):
                flat(f.left)
                name = _table_name(f.right)
                if name not in self.spec.TABLES:
                    raise UnsupportedStatement(f"join with {name}")
                plan.append((str(name), f.onclause, bool(f.isouter)))
                return
            name = _table_name(f)
            if name not in self.spec.TABLES:
                raise UnsupportedStatement(f"from {name!r}")
            if all(p[0] != name for p in plan):
                plan.append((str(name), None, False))

        for f in sel.get_final_froms():
            flat(f)
        return plan

    def _join(self, envs: list[Env], table: str, cands: list[Any], on: Any, isouter: bool) -> list[Env]:
        out: list[Env] = []
        for env in envs:
            matched = False
            for o in cands:
                env2 = {**env, table: o}
                if on is None or self.ev(on, env2) is True:
                    out.append(env2)
                    matched = True
            if isouter and not matched:
                out.append({**env, table: None})
        return out

    async def _load_for(self, sel: Any, outer: Env) -> list[tuple[str, Any, bool]]:
        """Load candidate rows for every FROM table (and EXISTS subqueries) into the identity map."""
        return [t for t in self._from_plan(sel) if t[0] not in outer]

    async def _candidates(self, table: str, where: Any, on: Any, envs: list[Env]) -> list[Any]:
        filters = self._pushdown(where, table) if where is not None else []
        if not filters and on is not None:
            # join pushdown: right.col == known_left.col -> right.col IN (values)
            for c in _conjuncts(on):
                if not (isinstance(c, elements.BinaryExpression) and c.operator is operators.eq):
                    continue
                lcol, rcol = _clause(c.left), _clause(c.right)
                for mine, other in ((lcol, rcol), (rcol, lcol)):
                    if (
                        isinstance(mine, elements.ColumnClause)
                        and _table_name(getattr(mine, "table", None)) == table
                        and isinstance(other, elements.ColumnClause)
                        and _table_name(getattr(other, "table", None)) != table
                    ):
                        vals = {self.ev(other, env) for env in envs}
                        vals.discard(None)
                        if not vals:
                            return [
                                e.obj
                                for (t, _), e in self.uow.entries.items()
                                if t == table
                                and not e.deleted
                                and visible(self.spec, table, e.obj, self.scope)
                            ]
                        ctype = {x.key: x.type for x in columns(self.spec.model(table))}[mine.key]
                        filters = [(mine.key, "in", [to_store_value(ctype, v) for v in vals])]
                        break
                if filters:
                    break
        return await self.uow.load(table, filters, self.scope)

    async def _preload_subqueries(self, sel: Any, outer: Env) -> None:
        from sqlalchemy.sql.visitors import iterate

        if sel.whereclause is None:
            return
        for el in iterate(sel.whereclause):
            if isinstance(el, selectable.Exists) or (
                isinstance(el, elements.UnaryExpression) and el.operator is operators.exists
            ):
                inner: Any = el.element
                while isinstance(inner, (elements.Grouping, selectable.ScalarSelect)):
                    inner = inner.element
                for table, _on, _o in self._from_plan(inner):
                    if table in outer:
                        continue
                    await self.uow.load(table, [], self.scope)

    async def _select_async(self, sel: Any, outer: Env) -> tuple[list[tuple[Any, ...]], list[str]]:
        plan = await self._load_for(sel, outer)
        where = sel.whereclause
        await self._prepare_in_subqueries(where)
        await self._preload_subqueries(sel, outer)
        envs: list[Env] = [dict(outer)]
        for table, on, isouter in plan:
            cands = await self._candidates(table, where, on, envs)
            envs = self._join(envs, table, cands, on, isouter)
        if where is not None:
            envs = [env for env in envs if self.ev(where, env) is True]
        descs = sel.column_descriptions
        cols = [_clause(d["expr"]) if not _is_entity(d["expr"]) else d["expr"] for d in descs]
        keys = [str(d.get("name") or f"c{i}") for i, d in enumerate(descs)]
        group_by = list(sel._group_by_clauses)
        is_agg = bool(group_by) or any(_has_agg(c) for c in cols if not _is_entity(c))
        if is_agg:
            groups: dict[tuple[Any, ...], list[Env]] = {}
            for env in envs:
                groups.setdefault(tuple(self.ev(g, env) for g in group_by), []).append(env)
            if not group_by and not groups:
                groups[()] = []
            rows_env = [(self._agg_row(cols, g), g) for g in groups.values()]
            rows = [r for r, _ in rows_env]
            order = list(sel._order_by_clauses)
            if order:
                rows = [r for r, _ in self._sort(rows_env, order, lambda c, g: self._agg_value(c, g))]
        else:
            order = list(sel._order_by_clauses)
            if order:
                envs = [
                    env
                    for env, _ in self._sort(
                        [(env, env) for env in envs], order, lambda c, env: self.ev(c, env)
                    )
                ]
            rows = [tuple(self._project(c, env) for c in cols) for env in envs]
        if sel._distinct:
            rows = list(dict.fromkeys(rows))
        off = sel._offset or 0
        lim = sel._limit
        rows = rows[off:] if lim is None else rows[off : off + lim]
        fu = sel._for_update_arg
        if fu is not None:
            of_tables = {
                _table_name(_clause(o).table) if hasattr(_clause(o), "table") else _table_name(_clause(o))
                for o in (fu.of or [])
            }
            for env in envs:
                for table, obj in env.items():
                    if obj is None or table in outer:
                        continue
                    if of_tables and table not in of_tables:
                        continue
                    self.uow.lock(obj)
        return rows, keys

    def _project(self, c: Any, env: Env) -> Any:
        if _is_entity(c):
            return env.get(c.__tablename__)
        return self.ev(c, env)

    def _sort(self, items: list[tuple[Any, Any]], order: list[Any], value: Any) -> list[tuple[Any, Any]]:
        # Postgres ORDER BY semantics (platform round 4): text by the cluster collation
        # (en_US.utf8, app.core.firestore.collation; citext columns by lower()), NULLS LAST for
        # ASC / FIRST for DESC unless NULLS FIRST/LAST is given.
        from app.core.firestore.collation import order_key

        out = list(items)
        for o in reversed(order):
            o = _clause(o)
            desc = False
            nulls: Any = None
            inner = o
            if isinstance(inner, elements.UnaryExpression) and inner.modifier in (
                operators.nulls_first_op,
                operators.nulls_last_op,
            ):
                nulls = "first" if inner.modifier is operators.nulls_first_op else "last"
                inner = inner.element
            if isinstance(inner, elements.UnaryExpression) and inner.modifier in (
                operators.desc_op,
                operators.asc_op,
            ):
                desc = inner.modifier is operators.desc_op
                inner = inner.element
            ci = isinstance(inner, elements.ColumnElement) and self._is_citext(inner)

            def key(
                item: tuple[Any, Any], inner: Any = inner, d: bool = desc, n: Any = nulls, ci: bool = ci
            ) -> tuple[Any, ...]:
                return order_key(value(inner, item[1]), desc=d, nulls=n, citext=ci)

            out.sort(key=key, reverse=desc)
        return out

    def _agg_row(self, cols: list[Any], group: list[Env]) -> tuple[Any, ...]:
        return tuple(self._agg_value(c, group) for c in cols)

    def _agg_value(self, c: Any, group: list[Env]) -> Any:
        c = _clause(c)
        if isinstance(c, elements.Label):
            return self._agg_value(c.element, group)
        if isinstance(c, functions.FunctionElement):
            name = c.name.lower()
            if name in _AGG:
                args = list(c.clauses)
                if name == "count":
                    if not args or (
                        isinstance(_clause(args[0]), elements.ColumnClause) and _clause(args[0]).name == "*"
                    ):
                        return len(group)
                    return sum(1 for env in group if self.ev(args[0], env) is not None)
                vals = [v for v in (self.ev(args[0], env) for env in group) if v is not None]
                if not vals:
                    return None
                if name == "sum":
                    return sum(vals)
                return min(vals) if name == "min" else max(vals)
            if name == "coalesce":
                for a in c.clauses:
                    v = self._agg_value(a, group)
                    if v is not None:
                        return v
                return None
        if not group:
            try:
                return self.ev(c, {})  # a literal (``coalesce(sum(x), 0)``) over no rows
            except UnsupportedStatement:
                return None
        return self.ev(c, group[0])

    # ------------------------------------------------------------------ DML

    async def update(self, stmt: Update) -> Result:
        table = _table_name(stmt.table)
        assert table is not None
        where = stmt.whereclause
        await self._prepare_in_subqueries(where)
        cands = await self.uow.load(
            table, self._pushdown(where, table) if where is not None else [], self.scope
        )
        values = _dml_values(stmt)
        hit: list[Any] = []
        for obj in cands:
            env = {table: obj}
            if where is not None and self.ev(where, env) is not True:
                continue
            if not writable(self.spec, table, obj, self.scope):
                continue
            new = {k: self.ev(v, env) for k, v in values.items()}
            for k, v in new.items():
                setattr(obj, k, v)
            self.uow.lock(obj)
            hit.append(obj)
        return self._returning(stmt, table, hit)

    async def delete(self, stmt: Delete) -> Result:
        table = _table_name(stmt.table)
        assert table is not None
        where = stmt.whereclause
        await self._prepare_in_subqueries(where)
        cands = await self.uow.load(
            table, self._pushdown(where, table) if where is not None else [], self.scope
        )
        hit = [o for o in cands if where is None or self.ev(where, {table: o}) is True]
        for o in hit:
            self.uow.delete(o, self.scope)
        return self._returning(stmt, table, hit)

    async def insert(self, stmt: Insert) -> Result:
        table = _table_name(stmt.table)
        assert table is not None
        model = self.spec.model(table)
        values = {k: self.ev(v, {}) for k, v in _dml_values(stmt).items()}
        obj = model(**values)
        _apply_defaults(obj, utcnow())
        post = getattr(stmt, "_post_values_clause", None)
        if post is not None:
            if type(post).__name__ != "OnConflictDoNothing":
                raise UnsupportedStatement("only ON CONFLICT DO NOTHING is supported")
            if await self._conflicts(table, obj):
                return self._returning(stmt, table, [])
        self.uow.add(obj, self.scope)
        return self._returning(stmt, table, [obj])

    async def _conflicts(self, table: str, obj: Any) -> bool:
        keys = self.spec.unique_keys(table, obj)
        for e in self.uow.entries.values():
            if e.table == table and not e.deleted and keys & self.spec.unique_keys(table, e.obj):
                return True
        if (table, self.spec.doc_id(table, obj)) in self.uow.entries:
            return True
        for ns, val in keys:
            snap = await self.uow.store.ref(f"uniq_{ns}", hashed_id(ns, val, normalize=False)).get()
            if snap.exists:
                return True
        snap = await self.uow.store.ref(table, self.spec.doc_id(table, obj)).get()
        return bool(snap.exists)

    def _returning(self, stmt: Any, table: str, objs: list[Any]) -> Result:
        ret = list(getattr(stmt, "_returning", ()) or ())
        if not ret:
            return Result([], [], rowcount=len(objs))
        rows = [tuple(self.ev(_clause(r), {table: o}) for r in ret) for o in objs]
        return Result(
            rows, [getattr(_clause(r), "key", f"c{i}") for i, r in enumerate(ret)], rowcount=len(objs)
        )


def _subselect(x: Any) -> Any:
    """The ``Select`` behind an ``IN`` right-hand side, or None for a literal list."""
    if isinstance(x, selectable.ScalarSelect):
        x = x.element
    return x if isinstance(x, selectable.Select) else None


def _is_entity(x: Any) -> bool:
    return isinstance(x, type) and hasattr(x, "__tablename__")


def _has_agg(c: Any) -> bool:
    from sqlalchemy.sql.visitors import iterate

    return any(
        isinstance(el, functions.FunctionElement) and el.name.lower() in _AGG for el in iterate(_clause(c))
    )


def _conjuncts(where: Any) -> list[Any]:
    if where is None:
        return []
    where = _clause(where)
    if isinstance(where, elements.BooleanClauseList) and where.operator is operators.and_:
        out: list[Any] = []
        for c in where.clauses:
            out += _conjuncts(c)
        return out
    if isinstance(where, elements.Grouping):
        return _conjuncts(where.element)
    return [where]


def _dml_values(stmt: Any) -> dict[str, Any]:
    vals = getattr(stmt, "_values", None)
    if not vals:
        multi = getattr(stmt, "_multi_values", None)
        if multi:
            raise UnsupportedStatement("multi-row INSERT")
        raise UnsupportedStatement("DML without values")
    out: dict[str, Any] = {}
    for k, v in vals.items():
        key = k if isinstance(k, str) else getattr(_clause(k), "key", None)
        out[str(key)] = v
    return out


async def run(uow: UnitOfWork, scope: Scope, stmt: Any) -> Result:
    it = Interpreter(uow, scope)
    if isinstance(stmt, Update):
        return await it.update(stmt)
    if isinstance(stmt, Insert):
        return await it.insert(stmt)
    if isinstance(stmt, Delete):
        return await it.delete(stmt)
    if isinstance(stmt, selectable.Select):
        return await it.select(stmt)
    raise UnsupportedStatement(f"statement {type(stmt).__name__}")


# =========================================================================== per-module store

_SCOPE_SQL = text(
    "SELECT current_setting('app.user_id', true), current_setting('app.org_ids', true), "
    "current_setting('app.is_platform', true)"
)


def _scope_of(row: Any) -> Scope:
    uid, orgs, plat = row
    return Scope(str(uid or ""), frozenset(o for o in str(orgs or "").split(",") if o), (plat or "") == "on")


def _detached_read(session: Any, stmt: Any) -> bool:
    """``stmt`` is a read without row locks and ``session`` is no SQL session at all."""
    from app.core.db import no_sql_session

    return no_sql_session(session) and isinstance(stmt, selectable.Select) and stmt._for_update_arg is None


def _detached_scope() -> Scope:
    """The RLS scope a Postgres transaction of this caller would have, derived exactly like
    ``db.rls_scope`` does for a no-Postgres session (platform inside ``system_context`` and in
    jobs/scripts; else the request principal's ``tenant_context``: user, orgs, platform flag;
    an anonymous request gets the empty context)."""
    from app.core.db import current_platform_job
    from app.core.request_context import _request_state, current_principal

    if current_platform_job() is not None:
        return Scope.platform()
    p = current_principal()
    if p is not None:
        return Scope(str(p.user_id), frozenset(str(o) for o in p.org_ids), bool(p.is_platform))
    if _request_state.get() is None:
        return Scope.platform()
    return Scope("", frozenset(), False)


_stores: dict[str, SqlStore] = {}


class SqlStore:
    """The ``TD_STORE_<MODULE>`` switch for one module's SQL (see the module docstring)."""

    def __init__(self, spec: SqlModuleSpec) -> None:
        self.spec = spec
        self.uow_key = f"td_{spec.module}_uow"
        self.adds_key = f"td_{spec.module}_adds"
        for t in spec.TABLES:
            if spec.register_collections:
                register_collection(CollectionSpec(t, "system"))
        if spec.register_collections:
            register_collection(CollectionSpec(spec.COUNTERS, "system"))
        _stores[spec.module] = self

    def on_firestore(self) -> bool:
        return uses_firestore(self.spec.module)

    def owns(self, obj: Any) -> bool:
        return getattr(type(obj), "__tablename__", None) in self.spec.TABLES

    def uow(self, session: Any) -> UnitOfWork:
        u = session.info.get(self.uow_key)
        if u is None:
            u = session.info[self.uow_key] = UnitOfWork(self.spec)
        return cast(UnitOfWork, u)

    async def scope(self, session: Any) -> Scope:
        return _scope_of((await session.execute(_SCOPE_SQL)).one())

    async def _drain(self, session: Any) -> None:
        adds = session.info.pop(self.adds_key, None)
        if adds:
            u, sc = self.uow(session), await self.scope(session)
            for obj in adds:
                u.add(obj, sc)

    async def execute(self, session: Any, stmt: Any, params: Any = None) -> Any:
        if not self.on_firestore():
            return await (session.execute(stmt) if params is None else session.execute(stmt, params))
        tabs = tables_of(stmt)
        mine = tabs & self.spec.TABLES
        if not mine:
            return await (session.execute(stmt) if params is None else session.execute(stmt, params))
        if tabs - mine:
            raise UnsupportedStatement(f"statement mixes {self.spec.module} and other tables: {sorted(tabs)}")
        if _detached_read(session, stmt):
            # A plain read from a caller with no SQL session (the Firebase stack's request /
            # job placeholder ``NO_POSTGRES``): a throwaway unit of work under the caller's RLS
            # scope. Nothing can be pending (every write on that session raises), so it sees
            # exactly what the Postgres transaction would see. Writes and ``FOR UPDATE`` still
            # raise ``PostgresDisabledError`` below (they need a request/job ``MemoryTx``).
            return await run(UnitOfWork(self.spec), _detached_scope(), stmt)
        await self._drain(session)
        return await run(self.uow(session), await self.scope(session), stmt)

    def add(self, session: Any, obj: Any) -> None:
        if self.on_firestore() and self.owns(obj):
            session.info.setdefault(self.adds_key, []).append(obj)
            return
        session.add(obj)

    async def flush(self, session: Any) -> None:
        if self.on_firestore():
            await self._drain(session)
        await session.flush()

    async def refresh(self, session: Any, obj: Any) -> None:
        """Postgres: reload from the database. Firestore: the identity-map instance is current."""
        if self.on_firestore() and self.owns(obj):
            await self._drain(session)
            return
        await session.refresh(obj)

    async def get(self, session: Any, model: type[Any], ident: Any, *, with_for_update: bool = False) -> Any:
        """``session.get`` (RLS applies, like ``SELECT ... WHERE pk = :id [FOR UPDATE]``)."""
        if not self.on_firestore() or getattr(model, "__tablename__", None) not in self.spec.TABLES:
            if with_for_update:
                return await session.get(model, ident, with_for_update=True)
            return await session.get(model, ident)
        q = select(model).where(*pk_conditions(model, ident))
        if with_for_update:
            q = q.with_for_update()
        return (await self.execute(session, q)).scalar_one_or_none()

    async def delete(self, session: Any, obj: Any) -> None:
        if self.on_firestore() and self.owns(obj):
            await self._drain(session)
            self.uow(session).delete(obj, await self.scope(session))
            return
        await session.delete(obj)

    async def begin_nested(self, session: Any) -> Savepoint:
        """SAVEPOINT that also rolls back the unit of work on Firestore."""
        snap = None
        if self.on_firestore():
            await self._drain(session)
            snap = self.uow(session).snapshot()
        return Savepoint(self, session, await session.begin_nested(), snap)

    async def next_counter(self, session: Any, name: str) -> int:
        """Gap-free counter ``<module>_counters/{name}`` committed with the transaction."""
        return await self.uow(session).next_counter(name)

    async def commit(self, session: Any) -> None:
        """Commit the unit of work (what the ``before_commit`` hook does; tests call it)."""
        if self.uow_key not in session.info and self.adds_key not in session.info:
            return
        await self._drain(session)
        await self.uow(session).commit()

    def register_backfill(self) -> None:
        """One ``TableMapping`` per table (same mapper the engine reads)."""
        from app.core.firestore.backfill import TableMapping, register_mapping

        for m in self.spec.models:
            pk = ", ".join(c.key for c in m.__table__.primary_key.columns)

            def transform(r: dict[str, Any], m: type[Any] = m) -> dict[str, Any]:
                return to_doc(m, r)

            def did(r: dict[str, Any], m: type[Any] = m) -> str:
                return model_doc_id(m, r)

            register_mapping(
                TableMapping(self.spec.module, m.__tablename__, m.__tablename__, did, transform, order_by=pk)
            )


class Savepoint:
    def __init__(self, store: SqlStore, session: Any, nested: Any, snap: Any) -> None:
        self._store, self._session, self._nested, self._snap = store, session, nested, snap

    @property
    def is_active(self) -> bool:
        return bool(self._nested.is_active)

    async def commit(self) -> None:
        await self._nested.commit()

    async def rollback(self) -> None:
        await self._nested.rollback()
        if self._snap is not None:
            self._session.info.pop(self._store.adds_key, None)
            self._store.uow(self._session).restore(self._snap)

    async def __aenter__(self) -> Savepoint:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is not None:
            await self.rollback()
        elif self.is_active:
            await self.commit()


async def precheck_all(session: Any) -> None:
    """Check every pending unit of work of ``session`` as its commit would, writing nothing.
    Call right before an external side effect (email, payment provider, file store), so a
    transaction that cannot commit never triggers one (Postgres: ``SET CONSTRAINTS ALL IMMEDIATE``
    and row locks give the same guarantee)."""
    for st in list(_stores.values()):
        if st.uow_key in session.info or st.adds_key in session.info:
            await st._drain(session)
            await st.uow(session).commit(dry_run=True)


_journal_hooks: tuple[Callable[[], Any], Callable[[Any], None]] | None = None


def register_journal(current: Callable[[], Any], on_rollback: Callable[[Any], None]) -> None:
    """An undo journal (``identity.fs_journal``): every SQL-engine commit made while a journal
    scope is open registers its compensation there, so an approval executor's or a journaled
    route's writes are all-or-nothing with the rest of the scope."""
    global _journal_hooks
    _journal_hooks = (current, on_rollback)


AFTER_COMMIT_KEY = "td_sql_after_commit"


def after_commit(session: Any, cb: Callable[[], Awaitable[Any]]) -> None:
    """Run ``cb`` once after this session's units of work have committed (the Firestore commit
    point: ``commit_all`` / ``MemoryTx.commit``). For follow-ups that must read the committed rows
    (e.g. security evidence holds recomputed from the cases). Dropped when the commit fails."""
    session.info.setdefault(AFTER_COMMIT_KEY, []).append(cb)


async def commit_all(session: Any) -> None:
    """Commit every module's unit of work held by ``session`` (the ``before_commit`` hook's work;
    ``MemoryTx.commit`` and tests call it). Outbox events captured by a ``MemoryTx`` commit in the
    first module transaction (all-or-nothing with that module's rows)."""
    events = session.info.pop(OUTBOX_KEY, None) or []
    pending = [st for st in _stores.values() if st.uow_key in session.info or st.adds_key in session.info]
    if events:
        target = pending[0] if pending else next(iter(_stores.values()), None)
        if target is None:
            raise StoreError("outbox events without a SQL store")
        target.uow(session).outbox.extend(events)
        if target not in pending:
            pending.append(target)
    from app.core import audit as core_audit
    from app.core import outbox as core_outbox
    from app.core import request_commit

    for st in pending:
        await st._drain(session)
    if pending and request_commit.is_open():
        first = pending[0].uow(session)
        if first.pending:
            first.core_buffered = (core_audit.pending_docs(), core_outbox.pending_events())
    for st in pending:
        await st.commit(session)
        if _journal_hooks is not None and _journal_hooks[0]() is not None:
            cb = st.uow(session).undo_callback()
            if cb is not None:
                _journal_hooks[1](cb)
    for follow_up in session.info.pop(AFTER_COMMIT_KEY, None) or []:
        await follow_up()


def _before_commit(sync_session: Session) -> None:
    info = sync_session.info
    pending = [st for st in _stores.values() if st.uow_key in info or st.adds_key in info]
    if not pending:
        return
    from sqlalchemy.util import await_only

    sc: Scope | None = None
    for st in pending:
        adds = info.pop(st.adds_key, None)
        u = st.uow(sync_session)
        if adds:
            if sc is None:  # inside SQLAlchemy's greenlet: a sync execute is fine here
                sc = _scope_of(sync_session.execute(_SCOPE_SQL).one())
            for obj in adds:
                u.add(obj, sc)
        await_only(u.commit())


def _after_end(sync_session: Session, transaction: Any) -> None:
    if transaction.parent is None:
        for st in _stores.values():
            sync_session.info.pop(st.uow_key, None)
            sync_session.info.pop(st.adds_key, None)


event.listen(Session, "before_commit", _before_commit)
event.listen(Session, "after_transaction_end", _after_end)

_ = (Sequence, Mapping)


# =========================================================================== stack without Postgres


class _MemNested:
    """``begin_nested()`` on a ``MemoryTx``: awaitable and an async context manager (the unit of
    work's own savepoint, ``SqlStore.begin_nested``, does the real rollback)."""

    is_active = True

    def __await__(self) -> Any:
        if False:  # pragma: no cover - makes this a generator
            yield
        return self

    async def __aenter__(self) -> _MemNested:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.is_active = False

    async def commit(self) -> None:
        self.is_active = False

    async def rollback(self) -> None:
        self.is_active = False


_GUC_DEFAULTS = {
    "app.user_id": "",
    "app.org_ids": "",
    "app.is_platform": "off",
    "app.actor": "anonymous",
    "app.roles": "",
    "app.privacy_tier": "",
}
_GUC_PARAMS = {
    "uid": "app.user_id",
    "orgs": "app.org_ids",
    "plat": "app.is_platform",
    "actor": "app.actor",
    "roles": "app.roles",
    "ptier": "app.privacy_tier",
}


class _GucResult:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self._row = row

    def one(self) -> tuple[Any, ...]:
        return self._row

    def scalar_one(self) -> Any:
        return self._row[0]


def _store_for_model(model: Any) -> SqlStore | None:
    table = getattr(model, "__tablename__", None)
    for st in _stores.values():
        if table in st.spec.TABLES and st.on_firestore():
            return st
    return None


def _store_for_statement(stmt: Any) -> SqlStore | None:
    """The SQL-engine store owning every table of ``stmt`` (Firestore switch on), else None."""
    try:
        tabs = tables_of(stmt)
    except Exception:
        return None
    if not tabs:
        return None
    for st in _stores.values():
        if tabs <= st.spec.TABLES and st.on_firestore():
            return st
    return None


class MemoryTx:
    """The request / job "session" of a module on Firestore when the stack has no Postgres
    (``runtime.postgres_enabled()`` is False). It keeps the RLS context (``set_config`` /
    ``current_setting`` of ``app.*``) in memory, so ``system_context`` / ``as_system`` /
    ``tenant_context`` and the engine's RLS emulation behave exactly as on Postgres, holds the
    units of work in ``info``, and ``commit()`` commits them. Any other SQL raises
    ``PostgresDisabledError`` (a code path still on Postgres)."""

    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.guc: dict[str, str] = dict(_GUC_DEFAULTS)

    def __bool__(self) -> bool:
        return True

    def _disabled(self, what: str) -> Exception:
        from app.core.db import PostgresDisabledError

        return PostgresDisabledError(f"Postgres used ({what}) on a stack without Postgres")

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        sql = str(stmt)
        if "set_config(" in sql:
            p = params or {}
            for k, guc in _GUC_PARAMS.items():
                if k in p:
                    self.guc[guc] = str(p[k] or "")
            return _GucResult(())
        if "current_setting(" in sql:
            names = re.findall(r"current_setting\('([a-z_.]+)'", sql)
            return _GucResult(tuple(self.guc.get(n, "") for n in names))
        if sql.startswith(("SET LOCAL ROLE", "SET CONSTRAINTS")):
            return _GucResult(())
        if isinstance(stmt, Insert) and _table_name(stmt.table) == OUTBOX:
            v = {
                k: (b.effective_value if isinstance(b, elements.BindParameter) else b)
                for k, b in _dml_values(stmt).items()
            }
            self.info.setdefault(OUTBOX_KEY, []).append(
                {
                    "id": str(v["id"]),
                    "event_id": v["id"],
                    "event_type": v["event_type"],
                    "aggregate_type": v["aggregate_type"],
                    "aggregate_id": v["aggregate_id"],
                    "payload": v.get("payload") or {},
                    "organization_id": v.get("organization_id"),
                }
            )
            return _GucResult(())
        st = _store_for_statement(stmt)
        if st is not None:  # a module on the SQL engine (also code not yet routed through it)
            return await st.execute(self, stmt, params)
        raise self._disabled(sql[:120])

    def add(self, obj: Any) -> None:
        st = _store_for_model(type(obj))
        if st is None:
            raise self._disabled(f"add {type(obj).__name__}")
        st.add(self, obj)

    async def flush(self) -> None:
        for st in list(_stores.values()):
            if st.adds_key in self.info:
                await st._drain(self)

    async def refresh(self, obj: Any) -> None:
        if _store_for_model(type(obj)) is None:
            raise self._disabled(f"refresh {type(obj).__name__}")

    async def get(self, model: Any, ident: Any, **kw: Any) -> Any:
        st = _store_for_model(model)
        if st is None:
            raise self._disabled(f"get {getattr(model, '__name__', model)}")
        return await st.get(self, model, ident, with_for_update=bool(kw.get("with_for_update")))

    def begin_nested(self) -> _MemNested:
        return _MemNested()

    async def commit(self) -> None:
        await commit_all(self)
        self.info.clear()

    async def rollback(self) -> None:
        self.info.clear()

    async def close(self) -> None:
        self.info.clear()


def _postgres_available() -> bool:
    from app.core import db as core_db
    from app.core.runtime import postgres_enabled

    return core_db._sessionmaker is not None or postgres_enabled()


async def _relay(agen: Any) -> Any:
    """Yield the one session of a session-dependency generator, forwarding a request error into
    it (so it rolls back) and finishing it on success (so it commits)."""
    s = await agen.__anext__()
    try:
        yield s
    except BaseException as e:
        try:
            await agen.athrow(e)
        except StopAsyncIteration:
            pass
        raise
    try:
        await agen.__anext__()
    except StopAsyncIteration:
        pass


async def _memory(principal: Any = None) -> Any:
    from app.core.db import set_rls_context, tenant_context

    tx = MemoryTx()
    if principal is None:
        await set_rls_context(tx)  # type: ignore[arg-type]
    else:
        await tenant_context(tx, principal)  # type: ignore[arg-type]
    try:
        yield tx
    except BaseException:
        await tx.rollback()
        raise
    await tx.commit()


async def _memory_relay(principal: Any = None) -> Any:
    inner = _memory(principal)
    tx = await inner.__anext__()
    try:
        yield tx
    except BaseException as e:
        try:
            await inner.athrow(e)
        except StopAsyncIteration:
            pass
        raise
    try:
        await inner.__anext__()
    except StopAsyncIteration:
        pass


async def store_db(pg: Any = Depends(get_db, scope="function")) -> Any:
    """``DbSession`` for modules on the SQL engine. It builds on ``get_db`` (so dependency
    overrides and the Postgres request transaction apply unchanged): when that yields a Postgres
    session it is passed through; when it yields ``NO_POSTGRES`` (a stack without Postgres) a
    ``MemoryTx`` is used instead, committed at the end of a successful request (an exception
    discards it, like a rollback)."""
    if pg:
        yield pg
        return
    async for tx in _memory_relay():
        yield tx


async def store_principal_db(
    principal: Principal = Depends(require_active_principal),
    pg: Any = Depends(get_principal_db, scope="function"),
) -> Any:
    """``PrincipalDbSession`` counterpart of ``store_db`` (the RLS context is the principal's)."""
    if pg:
        yield pg
        return
    async for tx in _memory_relay(principal):
        yield tx


# Drop-in replacements for ``app.core.db.DbSession`` / ``PrincipalDbSession`` (same scope).
StoreDbSession = Annotated[AsyncSession, Depends(store_db, scope="function")]
StorePrincipalDbSession = Annotated[AsyncSession, Depends(store_principal_db, scope="function")]


class store_session:
    """A job/webhook transaction: a Postgres session + ``begin()`` when the stack has Postgres,
    else a ``MemoryTx`` committed on a clean exit."""

    def __init__(self) -> None:
        self._cm: Any = None
        self._tx: MemoryTx | None = None

    async def __aenter__(self) -> Any:
        if _postgres_available():
            from contextlib import AsyncExitStack

            from app.core.db import get_sessionmaker

            self._cm = AsyncExitStack()
            s = await self._cm.enter_async_context(get_sessionmaker()())
            await self._cm.enter_async_context(s.begin())
            return s
        self._tx = MemoryTx()
        return self._tx

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._cm is not None:
            await self._cm.__aexit__(exc_type, exc, tb)
            return
        assert self._tx is not None
        if exc_type is None:
            await self._tx.commit()
        else:
            await self._tx.rollback()


def journaled_executor(store: SqlStore, job: str) -> Any:
    """Decorator for approval executors / reject hooks ``fn(session, principal, req)`` of a module
    on this engine. Postgres: unchanged (the decision's transaction holds every write).
    Firestore: the executor's writes commit **inside** the decision's undo journal
    (``register_journal``), so a later failure in the decision restores them. When the decision
    route has no SQL session (``NO_POSTGRES``), the executor runs on its own ``MemoryTx`` in
    platform scope, like the Postgres system context of the decision."""
    import functools

    def deco(fn: Any) -> Any:
        @functools.wraps(fn)
        async def wrapper(session: Any, principal: Any, req: Any) -> Any:
            if not store.on_firestore():
                return await fn(session, principal, req)
            from app.core.db import set_rls_context

            own = not session
            tx: Any = MemoryTx() if own else session
            if own:
                await set_rls_context(tx, is_platform=True, actor=f"system:{job}")
            try:
                out = await fn(tx, principal, req)
            except BaseException:
                if own:
                    await tx.rollback()
                raise
            await commit_all(tx)
            return out

        return wrapper

    return deco
