"""Postgres -> Firestore backfill and verification (MIGRATION-PLAN §4.1, owner decision F1).

Only demo data exists (F1), so a module moves by **backfill -> verify -> flip the switch**, with
"reseed" as the rollback. No dual-run, no reverse mirror.

Each module declares its tables in ``app/modules/<m>/store_specs.py``::

    register_mapping(TableMapping(
        module="admin", table="feature_flags", collection="feature_flags",
        doc_id=lambda r: r["flag_key"], transform=flag_doc, order_by="flag_key"))

``transform`` is the **same mapper the repository reads** (row dict -> document dict), so a
verified backfill means the repository sees exactly what Postgres had.

* ``backfill(session, module)`` streams each table in primary-key order and writes the mapped
  documents verbatim (timestamps kept) with ``ScopedStore.system("firestore.backfill")``.
  Re-running is idempotent; ``replace=True`` first deletes the collection (reseed).
* ``verify(session, module)`` compares, per collection: the row/document counts, a per-document
  canonical-JSON SHA-256 of the mapped fields, missing/extra ids and a summed checksum.

CLI: ``python -m app.core.firestore.backfill <module>... [--verify-only] [--replace]``
(reads the dev database through ``DATABASE_URL``; writes the Firestore of
``FIRESTORE_EMULATOR_HOST`` or the configured project).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.backend import MODULES
from app.core.time import ensure_utc

Row = dict[str, Any]
JOB = "firestore.backfill"


@dataclass(frozen=True)
class TableMapping:
    module: str
    table: str
    collection: str
    doc_id: Callable[[Row], str]
    transform: Callable[[Row], dict[str, Any]]
    order_by: str = "id"
    where: str | None = None  # optional SQL predicate (e.g. skip soft-deleted rows)
    # Several tables may fold into one collection (embedding); they are verified together.
    group: str | None = None
    # Assembled documents (an embedded outline built from several tables): returns the rows
    # instead of ``SELECT * FROM table``. Runs inside the backfill's system context.
    loader: Callable[[AsyncSession], Awaitable[list[Row]]] | None = None


_mappings: dict[str, list[TableMapping]] = {}


def register_mapping(m: TableMapping) -> TableMapping:
    if m.module not in MODULES:
        raise ValueError(f"unknown module {m.module!r}")
    lst = _mappings.setdefault(m.module, [])
    if not any(x.table == m.table and x.collection == m.collection for x in lst):
        lst.append(m)
    return m


def mappings(module: str) -> list[TableMapping]:
    if module not in MODULES:
        raise ValueError(f"unknown module {module!r}")
    importlib.import_module(f"app.modules.{module}.store_specs")
    return list(_mappings.get(module, []))


# --------------------------------------------------------------------------- canonical form


def canonical(value: Any) -> Any:
    """JSON-stable form used for checksums (Firestore and Postgres values compare equal)."""
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        # A4: bytea (Postgres) and Bytes (Firestore) hash identically, as lowercase hex.
        return bytes(value).hex()
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)  # JSONB 5 vs 5.0 round-trips differ; compare numerically
    return value


def doc_hash(data: dict[str, Any], keys: list[str] | None = None) -> str:
    sel = data if keys is None else {k: data.get(k) for k in keys}
    blob = json.dumps(canonical(sel), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


# --------------------------------------------------------------------------- read Postgres


async def _rows(session: AsyncSession, m: TableMapping) -> list[Row]:
    from app.core.db import as_system

    where = f" WHERE {m.where}" if m.where else ""
    sql = text(f"SELECT * FROM {m.table}{where} ORDER BY {m.order_by}")  # noqa: S608 - static mapping
    async with as_system(session, JOB):
        if m.loader is not None:
            return await m.loader(session)
        res = await session.execute(sql)
        return [dict(r) for r in res.mappings().all()]


async def mapped_documents(session: AsyncSession, m: TableMapping) -> list[tuple[str, dict[str, Any]]]:
    return [(m.doc_id(r), m.transform(r)) for r in await _rows(session, m)]


def _grouped(ms: list[TableMapping]) -> dict[str, list[TableMapping]]:
    out: dict[str, list[TableMapping]] = {}
    for m in ms:
        out.setdefault(m.group or m.collection, []).append(m)
    return out


# --------------------------------------------------------------------------- backfill / verify


@dataclass
class CollectionReport:
    collection: str
    tables: list[str]
    pg_rows: int = 0
    fs_docs: int = 0
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)
    pg_checksum: str = ""
    fs_checksum: str = ""

    @property
    def ok(self) -> bool:
        return (
            not self.missing
            and not self.extra
            and not self.mismatched
            and self.pg_checksum == self.fs_checksum
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "tables": self.tables,
            "pg_rows": self.pg_rows,
            "fs_docs": self.fs_docs,
            "missing": self.missing[:20],
            "extra": self.extra[:20],
            "mismatched": self.mismatched[:20],
            "pg_checksum": self.pg_checksum,
            "fs_checksum": self.fs_checksum,
            "ok": self.ok,
        }


async def _combined(session: AsyncSession, ms: list[TableMapping]) -> dict[str, dict[str, Any]]:
    """Mapped documents of one collection. Rows that map to the same id (several tables folded
    in by ``group``, or many rows embedded in one document) merge; map fields merge one level."""
    out: dict[str, dict[str, Any]] = {}
    for m in ms:
        for doc_id, data in await mapped_documents(session, m):
            cur = out.setdefault(doc_id, {})
            for k, v in data.items():
                cur[k] = {**cur[k], **v} if isinstance(v, dict) and isinstance(cur.get(k), dict) else v
    return out


async def backfill(
    session: AsyncSession, module: str, *, replace: bool = False, client: Any = None
) -> dict[str, int]:
    """Copy a module's tables into Firestore; returns documents written per collection."""
    from app.core.firestore.store import ScopedStore

    store = ScopedStore.system(JOB, client=client)
    written: dict[str, int] = {}
    for coll, ms in _grouped(mappings(module)).items():
        docs = await _combined(session, ms)
        if replace:
            await store.delete_all(coll)
        written[coll] = await store.import_documents(coll, sorted(docs.items()))
    return written


def _checksum(hashes: dict[str, str]) -> str:
    h = hashlib.sha256()
    for k in sorted(hashes):
        h.update(f"{k}={hashes[k]}\n".encode())
    return h.hexdigest()


async def verify(session: AsyncSession, module: str, *, client: Any = None) -> list[CollectionReport]:
    """Counts + per-document SHA-256 of the mapped fields + summed checksum, per collection."""
    from app.core.firestore.store import ScopedStore

    store = ScopedStore.system(JOB, client=client)
    reports: list[CollectionReport] = []
    for coll, ms in _grouped(mappings(module)).items():
        rep = CollectionReport(coll, [m.table for m in ms])
        pg = await _combined(session, ms)
        fs = {d.id: d.data for d in await store.scan(coll)}
        rep.pg_rows, rep.fs_docs = len(pg), len(fs)
        pg_h = {k: doc_hash(v) for k, v in pg.items()}
        fs_h = {k: doc_hash(fs[k], list(pg[k])) for k in fs if k in pg}
        rep.missing = sorted(set(pg) - set(fs))
        rep.extra = sorted(set(fs) - set(pg))
        rep.mismatched = sorted(k for k in fs_h if fs_h[k] != pg_h[k])
        rep.pg_checksum = _checksum(pg_h)
        rep.fs_checksum = _checksum({**fs_h, **{k: "extra" for k in rep.extra}})
        reports.append(rep)
    return reports


async def sync_if_enabled(session: AsyncSession, *modules: str) -> dict[str, dict[str, int]]:
    """Dev seeds: after writing demo rows to Postgres, copy each module whose
    ``TD_STORE_<MODULE>`` is ``firestore`` (owner decision F1: demo data is reseeded)."""
    from app.core.firestore.backend import uses_firestore

    return {m: await backfill(session, m) for m in modules if uses_firestore(m)}
