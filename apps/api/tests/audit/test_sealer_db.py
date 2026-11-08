"""Sealer + database guarantees: chaining, append-only, privileges, RLS."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_rls_context
from app.modules.audit.chain import verify_rows
from app.modules.audit.models import AuditLog
from app.modules.audit.sealer import iter_chain, verify_chain


async def test_seal_chain_and_verify(write_and_seal, sealer_engine) -> None:
    marker = await write_and_seal(4)
    async with sealer_engine.connect() as conn, conn.begin():
        s = AsyncSession(bind=conn)
        mine = (
            (await s.execute(select(AuditLog).where(AuditLog.action == marker).order_by(AuditLog.seq)))
            .scalars()
            .all()
        )
        assert len(mine) == 4
        seqs = [r.seq for r in mine]
        assert seqs == list(range(seqs[0], seqs[0] + 4))  # gap-free
        assert mine[0].after_state == {"i": 0, "nested": {"a": 1, "b": 2}}
        assert str(mine[0].ip) == "203.0.113.7"
        result = await verify_chain(s)
        assert result.ok, result
        assert result.last_seq is not None and result.last_seq >= seqs[-1]
        # outbox drained
        left = (await s.execute(text("SELECT count(*) FROM audit_outbox"))).scalar()
        assert left == 0
        await s.close()


async def test_tamper_detection_on_real_rows(write_and_seal, sealer_engine) -> None:
    marker = await write_and_seal(3)
    async with sealer_engine.connect() as conn, conn.begin():
        s = AsyncSession(bind=conn)
        rows = [r async for r in iter_chain(s)]
        await s.close()
    assert verify_rows(rows).ok
    idx = next(i for i, r in enumerate(rows) if r["action"] == marker)
    rows[idx] = {**rows[idx], "target_type": "something_else"}
    res = verify_rows(rows)
    assert not res.ok and res.first_bad_seq == rows[idx]["seq"]


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE audit_log SET reason = 'x' WHERE seq = 1",
        "DELETE FROM audit_log WHERE seq = 1",
        "TRUNCATE audit_log",
        "INSERT INTO audit_log (seq, occurred_at, id, actor_type, action, target_type, prev_hash, row_hash) "
        "VALUES (999999999, now(), gen_random_uuid(), 'system', 'x.y', 't', '\\x00', '\\x00')",
        "SELECT count(*) FROM audit_outbox",
        "UPDATE audit_outbox SET record = '{}'",
        "SELECT * FROM audit_log_default",
    ],
)
async def test_app_role_cannot_modify_audit(write_and_seal, app_engine, stmt) -> None:
    await write_and_seal(1)
    async with app_engine.connect() as conn, conn.begin():
        await conn.execute(text("SELECT set_config('app.is_platform', 'on', true)"))
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(stmt))


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE audit_log SET reason = 'x' WHERE seq = 1",
        "DELETE FROM audit_log WHERE seq = 1",
        "TRUNCATE audit_log",
    ],
)
async def test_sealer_role_cannot_rewrite_history(write_and_seal, sealer_engine, stmt) -> None:
    await write_and_seal(1)
    async with sealer_engine.connect() as conn, conn.begin():
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(stmt))


async def test_audit_log_read_is_platform_only(write_and_seal, db) -> None:
    marker = await write_and_seal(2)
    await set_rls_context(db)  # ordinary context: not platform
    n = (await db.execute(select(AuditLog).where(AuditLog.action == marker))).scalars().all()
    assert n == []
    await set_rls_context(db, is_platform=True, actor="user:test")
    n = (await db.execute(select(AuditLog).where(AuditLog.action == marker))).scalars().all()
    assert len(n) == 2


async def test_trigger_blocks_truncate_even_for_owner(write_and_seal, owner_engine) -> None:
    await write_and_seal(1)
    async with owner_engine.connect() as conn, conn.begin():
        with pytest.raises(DBAPIError, match="append-only"):
            await conn.execute(text("TRUNCATE audit_log"))
