"""Round 8: in-memory ORDER BY on text follows the VM database's collation (glibc en_US.utf8:
lower case before upper case, accents after the base letter, spaces/punctuation ignored at the
first levels) with Postgres NULL placement (ASC NULLS LAST, DESC NULLS FIRST)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import NO_POSTGRES
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.security.models import UnblockRequest as UR
from app.modules.security.repo_firestore import find_repo
from app.modules.security.repo_fs_cases import _Uow, _uow, sx
from app.modules.security.store_specs import UnblockRow
from tests.audit.fs.support import sample_row

FS_MODULES = ("security",)
pytestmark = pytest.mark.usefixtures("fs_env")
VALUES = ["Zeta", "b", "é", None, "A", "coop", "e", "co-op", "a", "co op"]
ASC = ["a", "A", "b", "co op", "co-op", "coop", "e", "é", "Zeta", None]


async def _seed() -> Any:
    case = uuid7()
    docs = []
    for i, v in enumerate(VALUES):
        r = {
            **sample_row(UR, i),
            "id": uuid7(),
            "case_id": case,
            "lab_location_text": v,
            "reference": f"APL-2026-C{i:02d}",
        }
        docs.append((str(r["id"]), UnblockRow.from_pg(r).doc()))
    await ScopedStore.system("firestore.backfill").import_documents("unblock_requests", docs)
    return case


async def test_runner_order_by_text_collation_and_nulls() -> None:
    case = await _seed()
    token = _uow.set(_Uow())
    try:
        q = select(UR).where(UR.case_id == case)
        asc = [r.lab_location_text for r in await sx.all(NO_POSTGRES, q.order_by(UR.lab_location_text))]
        assert asc == ASC
        desc = [
            r.lab_location_text for r in await sx.all(NO_POSTGRES, q.order_by(UR.lab_location_text.desc()))
        ]
        assert desc == [None, *reversed(ASC[:-1])]  # DESC: NULLS FIRST
        nf = await sx.all(NO_POSTGRES, q.order_by(UR.lab_location_text.asc().nulls_first()))
        assert [r.lab_location_text for r in nf] == [None, *ASC[:-1]]
        top3 = await sx.all(NO_POSTGRES, q.order_by(UR.lab_location_text).limit(3))
        assert [r.lab_location_text for r in top3] == ["a", "A", "b"]
    finally:
        _uow.reset(token)


async def test_find_repo_uses_collation() -> None:
    case = await _seed()
    rows = await find_repo().find(
        "unblock_requests",
        UnblockRow,
        filters=(("case_id", "==", str(case)),),
        order=("lab_location_text", False),
    )
    assert [r.lab_location_text for r in rows] == ASC
    rows = await find_repo().find(
        "unblock_requests",
        UnblockRow,
        filters=(("case_id", "==", str(case)),),
        order=("lab_location_text", True),
    )
    assert [r.lab_location_text for r in rows] == [None, *reversed(ASC[:-1])]
