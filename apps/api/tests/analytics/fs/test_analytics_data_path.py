"""Analytics data path on Firestore (data model + backfill mappers).
Emulator only, no Postgres."""

from __future__ import annotations

import pytest

from app.core.db import Base
from app.core.firestore.collections import get_spec
from app.modules.analytics import models as m
from tests.audit.fs.support import roundtrip_module

pytestmark = pytest.mark.usefixtures("fs_env")

MODELS = [
    c
    for c in vars(m).values()
    if isinstance(c, type) and issubclass(c, Base) and c is not Base and c.__module__ == m.__name__
]


async def test_every_table_maps_and_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.firestore.backfill as bf
    import app.modules.analytics.store_specs  # noqa: F401

    # export_jobs runs on the shared SQL engine (its own codec); checked in test_export_jobs_engine_mapping
    real = bf.mappings
    monkeypatch.setattr(bf, "mappings", lambda mod: [x for x in real(mod) if x.collection != "export_jobs"])

    # 16 tables; the two raw time series are stored inside ``analytics_batches`` (loader mapping,
    # covered by tests/analytics/fs/test_ingest_firestore.py), the other 14 map 1:1.
    assert len(MODELS) == 16
    assert await roundtrip_module("analytics", MODELS) == 13


async def test_export_jobs_engine_mapping() -> None:
    """export_jobs: the engine's document round-trips to an equal ORM row."""
    from app.core.firestore.backfill import mappings
    from app.core.firestore.sqlstore import from_doc
    from tests.audit.fs.support import sample_row

    mp = next(x for x in mappings("analytics") if x.collection == "export_jobs")
    row = sample_row(m.ExportJob, 0)
    back = from_doc(m.ExportJob, mp.transform(row))
    assert {k: getattr(back, k) for k in row} == row


def test_rollup_keys_are_the_primary_keys() -> None:
    import app.modules.analytics.store_specs  # noqa: F401
    from app.core.firestore.backfill import mappings

    mp = next(x for x in mappings("analytics") if x.collection == "daily_learning_aggregates")
    row = {
        "user_id": "u1",
        "activity_date": __import__("datetime").date(2026, 11, 2),
        "entity_kind": "course",
        "entity_id": None,
    }
    assert mp.doc_id(row) == "u1:2026-11-02:course:-"
    assert get_spec("analytics_dirty_days").family == "system"
