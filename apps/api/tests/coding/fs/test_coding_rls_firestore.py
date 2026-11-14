"""``repo_firestore.visibility`` with every session kind it meets (no Postgres): the SQL engine's
``MemoryTx`` (its ``current_setting`` answer has 3 values, no ``app.caller_is_org_staff()``),
``NO_POSTGRES`` and ``None``."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.core.principal import Principal


async def test_visibility_on_memory_tx_no_postgres_and_none(coding_fs: Any) -> None:
    from app.core.db import NO_POSTGRES, system_context, tenant_context
    from app.core.firestore.sqlstore import MemoryTx
    from app.modules.coding import rls
    from app.modules.coding.repo_firestore import SYSTEM_VIEW, visibility

    org = uuid.uuid4()
    p = Principal(user_id=uuid.uuid4(), session_id=uuid.uuid4(), org_ids=(org,))
    tx = MemoryTx()
    await tenant_context(tx, p)  # type: ignore[arg-type]
    v = await visibility(tx)
    assert v.user_id == str(p.user_id) and v.org_ids == frozenset({str(org)}) and not v.is_platform
    assert v.sees(None) and v.sees(org) and not v.sees(uuid.uuid4())
    assert v.sees_owned(p.user_id, None) and not v.sees_owned(uuid.uuid4(), org)  # not org staff

    sys_tx = MemoryTx()
    await system_context(sys_tx, "test.job")  # type: ignore[arg-type]
    assert (await visibility(sys_tx)).is_platform

    token = rls.set_principal(p)
    try:
        nv = await visibility(NO_POSTGRES)
    finally:
        rls._principal.reset(token)
    assert nv.user_id == str(p.user_id) and nv.org_ids == frozenset({str(org)})
    assert await visibility(None) == SYSTEM_VIEW
    assert rls.no_postgres(tx) and rls.no_postgres(NO_POSTGRES) and rls.no_postgres(None)


def test_rls_copies_are_identical() -> None:
    root = Path(__file__).resolve().parents[3] / "app/modules"
    assert (root / "placement/rls.py").read_bytes() == (root / "coding/rls.py").read_bytes()
