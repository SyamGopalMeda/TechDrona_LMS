"""The pass-1 statement runner (``security.repo_fs_cases.sx``) on Firestore: SQL semantics of the
statement shapes the case/unblock code uses."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.db import NO_POSTGRES
from app.core.firestore.repository import assert_repository_scoped
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.security.models import UnblockRequest as UR
from app.modules.security.repo_fs_cases import CasesRepo, fs_unit_of_work, sx
from tests.audit.fs.support import sample_row

FS_MODULES = ("security",)
pytestmark = pytest.mark.usefixtures("fs_env")


def test_scope_lint() -> None:
    assert_repository_scoped(CasesRepo)


async def _seed() -> list[UR]:
    now = clock.now()
    case = uuid7()
    out = []
    for i, (state, sub) in enumerate(
        (("submitted", now), ("draft", None), ("closed", now - timedelta(days=1)))
    ):
        r = {
            **sample_row(UR, i),
            "id": uuid7(),
            "case_id": case,
            "state": state,
            "submitted_at": sub,
            "created_at": now + timedelta(seconds=i),
            "reference": f"APL-2026-X{i}",
        }
        row = sx.new(UR, **r)
        sx.add(NO_POSTGRES, row)
        out.append(row)
    await sx.flush(NO_POSTGRES)
    return out


async def test_select_filters_order_limit_count_min_update() -> None:
    rows = await _seed()
    case = rows[0].case_id
    got = await sx.all(
        NO_POSTGRES, select(UR).where(UR.case_id == case, UR.state.in_(("submitted", "draft")))
    )
    assert {r.state for r in got} == {"submitted", "draft"}
    assert await sx.one_or_none(NO_POSTGRES, select(UR).where(UR.reference == "APL-2026-X2")) is rows[2]
    ordered = await sx.all(NO_POSTGRES, select(UR).where(UR.case_id == case).order_by(UR.submitted_at))
    assert [r.state for r in ordered] == ["closed", "submitted", "draft"]  # ASC: NULLS LAST
    desc = await sx.all(
        NO_POSTGRES, select(UR).where(UR.case_id == case).order_by(UR.submitted_at.desc()).limit(2)
    )
    assert [r.state for r in desc] == ["draft", "submitted"]  # DESC: NULLS FIRST
    assert (
        await sx.scalar(NO_POSTGRES, select(func.count()).select_from(UR).where(UR.state.notin_(("closed",))))
        == 2
    )
    assert await sx.scalar(NO_POSTGRES, select(UR.reference).where(UR.state == "draft")) == "APL-2026-X1"
    n = await sx.update(NO_POSTGRES, update(UR).where(UR.state == "draft").values(state="withdrawn"))
    assert n == 1
    assert await sx.one_or_none(NO_POSTGRES, select(UR).where(UR.state == "withdrawn")) is not None


async def test_unit_of_work_writes_changes_on_success() -> None:
    rows = await _seed()
    gen = fs_unit_of_work()
    await gen.__anext__()
    r = await sx.get(NO_POSTGRES, UR, rows[1].id)
    r.state = "submitted"
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    fresh_gen = fs_unit_of_work()
    await fresh_gen.__anext__()
    again = await sx.get(NO_POSTGRES, UR, rows[1].id)
    assert again.state == "submitted"
    with pytest.raises(StopAsyncIteration):
        await fresh_gen.__anext__()
