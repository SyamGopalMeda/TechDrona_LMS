"""Security background jobs on the Firebase stack (no Postgres): ``run_job`` opens a
``store_session`` (``MemoryTx``) instead of a Postgres session and commits on success."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.identity import clock
from app.modules.security import models as m
from app.modules.security import repo_fs_controls as secx
from tests.commerce.firestore.conftest import FakeSession
from tests.security.fs.test_pass3_controls_reports_http import FS_MODULES, _seed  # noqa: F401


async def test_purge_counters_job(fs_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import runtime
    from app.modules.security import tasks

    monkeypatch.setattr(runtime, "postgres_enabled", lambda: False)
    now = clock.now()
    keep = m.SecurityCounter(counter_key="k:new", bucket_start=now - timedelta(hours=1), count=3)
    old = [
        m.SecurityCounter(counter_key=f"k:old{i}", bucket_start=now - timedelta(days=3), count=1)
        for i in range(2)
    ]
    await _seed(keep, *old)
    await tasks.run_job("security.purge_counters")
    left = (await secx.execute(FakeSession().as_platform(), select(m.SecurityCounter))).scalars().all()
    assert [c.counter_key for c in left] == ["k:new"]


async def test_sla_breach_alerts_job_runs_without_postgres(
    fs_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import runtime
    from app.modules.security import tasks

    monkeypatch.setattr(runtime, "postgres_enabled", lambda: False)
    out = await tasks.run_job("security.sla_breach_alerts")
    assert isinstance(out, dict)
