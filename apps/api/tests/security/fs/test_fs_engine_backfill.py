"""Security pass 2: the backfill writes ``expire_at`` on signals, evaluations and counters
(retention TTL), merged into the same documents as the table mappings, and verify checks it.

Postgres is not available here: ``FakePgSession`` answers ``SELECT * FROM <table>`` with fixture
rows and the expiry queries with the rows Postgres would compute (held subject -> NULL; else
time + interval), so the test covers the mapping, merge, write and verify path."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.firestore.backfill import backfill, verify
from app.core.firestore.ids import compose_id
from app.core.firestore.store import ScopedStore
from app.modules.security import models as m
from app.modules.security import repo_fs_engine as fx
from tests.audit.fs.support import sample_row
from tests.identity.fs.conftest import FakePgSession

FS_MODULES = ("security",)
pytestmark = pytest.mark.usefixtures("fs_env")


class _Pg(FakePgSession):
    def __init__(self, tables: dict[str, list[dict[str, Any]]], expiry: dict[str, list[dict[str, Any]]]):
        super().__init__(tables)
        self.expiry = {fx.BACKFILL_EXPIRY_SQL[k]: v for k, v in expiry.items()}

    def _select(self, sql: str) -> list[dict[str, Any]]:
        if sql in self.expiry:
            return list(self.expiry[sql])
        return super()._select(sql)


def test_expiry_sql_is_the_purge_predicate() -> None:
    sig, ev, cnt = (fx.BACKFILL_EXPIRY_SQL[k] for k in (fx.SIGNALS, fx.EVALS, fx.COUNTERS))
    held = "sc.user_id = s.user_id AND (sc.status <> 'closed' OR sc.legal_hold)"
    assert held in sig and held in ev
    assert "c2.id = s.case_id AND (c2.status <> 'closed' OR c2.legal_hold)" in ev
    assert "rp.table_name = 'security_signals' AND rp.is_active" in sig
    assert "rp.table_name = 'risk_evaluations' AND rp.is_active" in ev
    assert "interval '180 days'" in sig and "bucket_start + interval '2 days'" in cnt


async def test_backfill_sets_expire_at_and_verifies() -> None:
    t0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    s_held, s_free = sample_row(m.SecuritySignal, 0), sample_row(m.SecuritySignal, 1)
    e_free = sample_row(m.RiskEvaluation, 0)
    c_row = sample_row(m.SecurityCounter, 0)
    for r, t in ((s_held, t0), (s_free, t0 + timedelta(hours=1)), (e_free, t0)):
        r["occurred_at" if "occurred_at" in r else "evaluated_at"] = t
    c_row["bucket_start"] = t0
    expiry = {
        fx.SIGNALS: [
            {"id": s_held["id"], "occurred_at": s_held["occurred_at"], "expire_at": None},
            {"id": s_free["id"], "occurred_at": s_free["occurred_at"], "expire_at": t0 + timedelta(days=181)},
        ],
        fx.EVALS: [{"id": e_free["id"], "evaluated_at": t0, "expire_at": t0 + timedelta(days=180)}],
        fx.COUNTERS: [
            {"counter_key": c_row["counter_key"], "bucket_start": t0, "expire_at": t0 + timedelta(days=2)}
        ],
    }
    pg = _Pg(
        {"security_signals": [s_held, s_free], "risk_evaluations": [e_free], "security_counters": [c_row]},
        expiry,
    )
    written = await backfill(pg, "security")  # type: ignore[arg-type]
    assert written["security_signals"] == 2 and written["security_counters"] == 1
    st = ScopedStore.system("test.backfill")
    held = await st.get("security_signals", compose_id(str(s_held["id"]), t0.isoformat()))
    free = await st.get("security_signals", compose_id(str(s_free["id"]), s_free["occurred_at"].isoformat()))
    assert held is not None and "expire_at" in held.data and held["expire_at"] is None
    assert free is not None and free["expire_at"] == t0 + timedelta(days=181)
    assert free["rule_key"] == s_free["rule_key"]  # the table mapping's fields are all there
    ev = await st.get("risk_evaluations", compose_id(str(e_free["id"]), t0.isoformat()))
    assert ev is not None and ev["expire_at"] == t0 + timedelta(days=180)
    cn = await st.get("security_counters", compose_id(c_row["counter_key"], t0.isoformat()))
    assert cn is not None and cn["expire_at"] == t0 + timedelta(days=2)
    reports = {r.collection: r for r in await verify(pg, "security")}  # type: ignore[arg-type]
    for coll in ("security_signals", "risk_evaluations", "security_counters"):
        assert reports[coll].ok, reports[coll].as_dict()
