"""Pass-2 requests on pass-3 code (security-pass2.md): the bulk lift releases the evidence of
the users whose cases it closed, **after** the cases are committed; the nightly jobs run in one
``detector_scope``."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.ids import uuid7
from app.core.principal import Principal
from app.modules.security import models as m
from app.modules.security import repo_fs_controls as secx
from tests.commerce.firestore.conftest import FakeSession
from tests.security.fs.test_pass3_controls_reports_http import FS_MODULES, _case, _restriction, _seed  # noqa: F401


async def test_bulk_lift_releases_evidence_after_commit(fs_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.identity.fs_journal import journal
    from app.modules.security import cases as cs
    from app.modules.security import controls, engine
    from app.modules.security import repo_fs_engine as fx

    async def noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(cs, "finalize_decision", noop)  # pass 1 (tested there)
    monkeypatch.setattr(engine, "notify_user", noop)  # pass 2 (tested there)
    seen: list[tuple[list[Any], list[str]]] = []

    async def release(users: Any) -> int:
        s = FakeSession().as_platform()
        statuses = [str((await secx.get(s, m.SecurityCase, c.id)).status) for c in cases]
        seen.append((list(users), statuses))
        return len(list(users))

    monkeypatch.setattr(fx, "release_evidence", release)
    u1, u2 = uuid7(), uuid7()
    cases = [_case(u1, level=3), _case(u2, level=3)]
    rs = [_restriction(u1, 3, case=cases[0]), _restriction(u2, 3, case=cases[1])]
    bl = m.SecurityBulkLift(
        id=uuid7(), selector={}, reason="false positive wave", requested_by=uuid7(), status="approved"
    )
    await _seed(*cases, *rs, bl)
    req = SimpleNamespace(
        payload={"bulk_lift_id": str(bl.id), "restriction_ids": [str(r.id) for r in rs], "reason": "fp"},
        target_type="security_bulk_lift",
        requested_by=bl.requested_by,
        id=uuid7(),
    )
    async with journal():
        await controls._execute_bulk(
            None, Principal(user_id=uuid7(), session_id=uuid7(), is_platform=True), req
        )
    bl_now = await secx.get(FakeSession().as_platform(), m.SecurityBulkLift, bl.id)
    assert len(seen) == 1, bl_now.progress
    users, statuses = seen[0]
    assert sorted(users, key=str) == sorted([u1, u2], key=str)
    assert statuses == ["closed", "closed"]  # called after the cases were committed
    _ = uuid


async def test_nightly_decay_runs_in_one_detector_scope(fs_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import asynccontextmanager

    from app.core import runtime
    from app.modules.security import repo_fs_engine as fx
    from app.modules.security import tasks

    monkeypatch.setattr(runtime, "postgres_enabled", lambda: False)
    scopes: list[str] = []

    @asynccontextmanager
    async def scope() -> Any:
        scopes.append("enter")
        yield
        scopes.append("exit")

    monkeypatch.setattr(fx, "detector_scope", scope)
    await tasks.run_job("security.decay_recompute")
    assert scopes == ["enter", "exit"]
