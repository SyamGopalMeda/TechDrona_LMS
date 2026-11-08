from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.audit import AuditActor, audit
from app.core.ids import uuid7
from app.modules.audit.sealer import seal_once


@pytest.fixture
def write_and_seal(committed_engine: AsyncEngine, sealer_engine: AsyncEngine) -> Any:
    """Commit ``n`` audit records as td_app, then seal them as td_audit_sealer.
    Returns the unique action marker used (audit rows are append-only and persist)."""

    async def _run(n: int = 3, **kw: Any) -> str:
        marker = f"test.sealed.m{uuid7().hex[:12]}"
        async with committed_engine.connect() as conn, conn.begin():
            s = AsyncSession(bind=conn)
            for i in range(n):
                await audit(
                    s,
                    AuditActor("user", user_id=uuid7(), session_id=uuid7(), roles=("super_admin",)),
                    marker,
                    "probe",
                    uuid7(),
                    after={"i": i, "nested": {"b": 2, "a": 1}},
                    ip="203.0.113.7",
                    request_id=f"req-{i}",
                    **kw,
                )
            await s.close()
        while await seal_once(sealer_engine):
            pass
        return marker

    return _run
