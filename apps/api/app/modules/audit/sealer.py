"""Audit sealer (ADR-0011): moves ``audit_outbox`` rows into the hash-chained ``audit_log``.

Runs as the dedicated ``audit-sealer`` service with ``DATABASE_AUDIT_SEALER_URL``
(role ``td_audit_sealer``: SELECT/DELETE on ``audit_outbox``, SELECT/INSERT on ``audit_log``).
A transaction-scoped advisory lock guarantees a single writer, so ``seq`` is gap-free.

    python -m app.modules.audit.sealer            # loop every TD_AUDIT_SEALER_INTERVAL_SECONDS
    python -m app.modules.audit.sealer --once     # one batch
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import get_settings
from app.core.db import make_engine
from app.modules.audit.chain import GENESIS_HASH, ChainVerification, compute_row_hash, verify_rows
from app.modules.audit.models import AuditLog, AuditOutbox

log = structlog.get_logger("app.audit.sealer")

SEALER_LOCK_KEY = 0x7D_A0D1_7000_0001  # constant advisory-lock key for the single sealer

_RECORD_FIELDS = (
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


_UUID_FIELDS = ("actor_user_id", "actor_session_id", "target_id", "organization_id", "subject_user_id")


async def chain_head(session: AsyncSession) -> tuple[int, bytes]:
    row = (
        await session.execute(select(AuditLog.seq, AuditLog.row_hash).order_by(AuditLog.seq.desc()).limit(1))
    ).first()
    if row is None:
        return 0, GENESIS_HASH
    return int(row.seq), bytes(row.row_hash)


async def seal_pending(session: AsyncSession, batch: int | None = None) -> int:
    """Seal up to ``batch`` outbox rows inside the caller's transaction. Returns count."""
    batch = batch or get_settings().TD_AUDIT_SEALER_BATCH
    got = (
        await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": SEALER_LOCK_KEY})
    ).scalar()
    if not got:
        return 0
    pending = (
        await session.execute(
            select(AuditOutbox.id, AuditOutbox.occurred_at, AuditOutbox.record)
            .order_by(AuditOutbox.occurred_at, AuditOutbox.id)
            .limit(batch)
        )
    ).all()
    if not pending:
        return 0
    seq, prev = await chain_head(session)
    rows: list[dict[str, Any]] = []
    for item in pending:
        seq += 1
        rec: dict[str, Any] = dict(item.record or {})
        row: dict[str, Any] = {f: rec.get(f) for f in _RECORD_FIELDS}
        row["actor_roles"] = list(row["actor_roles"] or [])
        for f in _UUID_FIELDS:
            if row[f] is not None:
                row[f] = uuid.UUID(str(row[f]))
        row.update(seq=seq, occurred_at=item.occurred_at, id=item.id)
        row_hash = compute_row_hash(prev, row)
        row.update(prev_hash=prev, row_hash=row_hash)
        rows.append(row)
        prev = row_hash
    await session.execute(insert(AuditLog), rows)
    await session.execute(delete(AuditOutbox).where(AuditOutbox.id.in_([p.id for p in pending])))
    return len(rows)


async def iter_chain(
    session: AsyncSession, from_seq: int = 1, page: int = 1000
) -> AsyncIterator[dict[str, Any]]:
    cursor = from_seq
    while True:
        result = await session.execute(
            select(AuditLog).where(AuditLog.seq >= cursor).order_by(AuditLog.seq).limit(page)
        )
        chunk = result.scalars().all()
        if not chunk:
            return
        for r in chunk:
            yield {c.key: getattr(r, c.key) for c in AuditLog.__table__.columns}
        cursor = chunk[-1].seq + 1


async def verify_chain(session: AsyncSession, from_seq: int = 1) -> ChainVerification:
    """Recompute the whole chain from ``from_seq`` (needs SELECT on audit_log: platform
    context for td_app, or the sealer role)."""
    expected_prev = GENESIS_HASH
    if from_seq > 1:
        prev_row = (
            await session.execute(select(AuditLog.row_hash).where(AuditLog.seq == from_seq - 1))
        ).scalar_one_or_none()
        if prev_row is None:
            return ChainVerification(False, 0, None, None, from_seq - 1, "anchor row missing")
        expected_prev = bytes(prev_row)
    rows = [r async for r in iter_chain(session, from_seq)]
    return verify_rows(rows, expected_prev_hash=expected_prev, expected_first_seq=from_seq)


async def seal_once(engine: AsyncEngine, batch: int | None = None) -> int:
    """One sealing round. Default (every ``TD_STORE_*`` on Postgres): exactly the Postgres
    sealer. During the Firestore transition (MIGRATION-PLAN §3.5) the sealer drains **both**
    outboxes into the one chain selected by ``TD_STORE_AUDIT``:

    * chain on Postgres + some module on Firestore: the Firestore ``audit_outbox`` is appended
      to the Postgres chain first, then the Postgres outbox as before;
    * chain on Firestore (``TD_STORE_AUDIT=firestore``): the Firestore outbox, then the Postgres
      outbox (``app.core.audit.audit()`` still writes there) are appended to the Firestore chain.
    """
    from app.core.firestore.backend import firestore_modules, uses_firestore

    if uses_firestore("audit"):
        return await _seal_into_firestore(engine, batch)
    n = 0
    if firestore_modules():
        n += await _seal_firestore_outbox_into_pg(engine, batch)
    async with engine.connect() as conn, conn.begin():
        session = AsyncSession(bind=conn)
        try:
            return n + await seal_pending(session, batch)
        finally:
            await session.close()


async def _pg_lock(session: AsyncSession) -> bool:
    got = (
        await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": SEALER_LOCK_KEY})
    ).scalar()
    return bool(got)


async def _seal_firestore_outbox_into_pg(engine: AsyncEngine, batch: int | None) -> int:
    """Firestore outbox -> Postgres chain. Postgres commits first, then the Firestore documents
    are deleted; a batch whose delete failed is recognised by id among the newest chain rows on
    the next round and only deleted (never sealed twice)."""
    from app.modules.audit.repo_firestore import MAX_SEAL_BATCH, sealer_repo

    repo = sealer_repo()
    size = min(batch or get_settings().TD_AUDIT_SEALER_BATCH, MAX_SEAL_BATCH)
    pending = await repo.pending_outbox(size)
    if not pending:
        return 0
    async with engine.connect() as conn, conn.begin():
        session = AsyncSession(bind=conn)
        try:
            if not await _pg_lock(session):
                return 0
            recent = {
                str(i)
                for i in (
                    await session.execute(select(AuditLog.id).order_by(AuditLog.seq.desc()).limit(2 * size))
                ).scalars()
            }
            seq, prev = await chain_head(session)
            rows: list[dict[str, Any]] = []
            for audit_id, occurred_at, record in pending:
                if audit_id in recent:
                    continue
                seq += 1
                row = _row(seq, prev, uuid.UUID(audit_id), occurred_at, record)
                rows.append(row)
                prev = row["row_hash"]
            if rows:
                await session.execute(insert(AuditLog), rows)
        finally:
            await session.close()
    await repo.delete_outbox([p[0] for p in pending])
    return len(rows)


async def _seal_into_firestore(engine: AsyncEngine, batch: int | None) -> int:
    """``TD_STORE_AUDIT=firestore``: Firestore outbox, then one Postgres outbox batch, into the
    Firestore chain. The Postgres rows are deleted after the Firestore commit; the head keeps the
    batch's ids so a failed delete is retried without sealing the rows again."""
    from app.modules.audit.repo_firestore import MAX_SEAL_BATCH, sealer_repo

    repo = sealer_repo()
    size = min(batch or get_settings().TD_AUDIT_SEALER_BATCH, MAX_SEAL_BATCH)
    n = await repo.seal_pending(size)
    async with engine.connect() as conn, conn.begin():
        session = AsyncSession(bind=conn)
        try:
            if not await _pg_lock(session):
                return n
            pending = (
                await session.execute(
                    select(AuditOutbox.id, AuditOutbox.occurred_at, AuditOutbox.record)
                    .order_by(AuditOutbox.occurred_at, AuditOutbox.id)
                    .limit(min(size, 2 * MAX_SEAL_BATCH))
                )
            ).all()
            if not pending:
                return n
            n += await repo.append(
                [(p.id, p.occurred_at, dict(p.record or {})) for p in pending],
                pg_batch_ids=[str(p.id) for p in pending],
            )
            await session.execute(delete(AuditOutbox).where(AuditOutbox.id.in_([p.id for p in pending])))
        finally:
            await session.close()
    return n


def _row(
    seq: int, prev: bytes, audit_id: uuid.UUID, occurred_at: Any, record: dict[str, Any]
) -> dict[str, Any]:
    row: dict[str, Any] = {f: record.get(f) for f in _RECORD_FIELDS}
    row["actor_roles"] = list(row["actor_roles"] or [])
    for f in _UUID_FIELDS:
        if row[f] is not None:
            row[f] = uuid.UUID(str(row[f]))
    row.update(seq=seq, occurred_at=occurred_at, id=audit_id)
    row_hash = compute_row_hash(prev, row)
    row.update(prev_hash=prev, row_hash=row_hash)
    return row


async def run_forever(interval: float | None = None) -> None:  # pragma: no cover - service loop
    s = get_settings()
    engine = make_engine(s.sealer_url)
    interval = interval or s.TD_AUDIT_SEALER_INTERVAL_SECONDS
    log.info("audit_sealer_started", interval_s=interval)
    try:
        while True:
            try:
                n = await seal_once(engine)
                if n:
                    log.info("audit_sealed", rows=n)
                    continue  # drain backlog without sleeping
            except Exception:
                log.exception("audit_sealer_error")
            await asyncio.sleep(interval)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    from app.core.logging import configure_logging

    p = argparse.ArgumentParser(description="Tech Drona audit sealer")
    p.add_argument("--once", action="store_true")
    args = p.parse_args(argv)
    s = get_settings()
    configure_logging(s.LOG_LEVEL, s.LOG_FORMAT, "audit-sealer")

    async def _once() -> None:
        engine = make_engine(s.sealer_url)
        try:
            print(await seal_once(engine))
        finally:
            await engine.dispose()

    asyncio.run(_once() if args.once else run_forever())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
