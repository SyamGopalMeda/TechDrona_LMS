"""Round 8: the usage report's ``by_feature`` (SQL ``ORDER BY feature``) uses the VM collation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.firestore.store import ScopedStore
from app.modules.ai import store
from app.modules.ai.store_specs_usage import USAGE_MONTHS, empty_month, month_key

FS_MODULES = ("ai",)
pytestmark = pytest.mark.usefixtures("fs_env")


async def test_by_feature_sorted_in_collation() -> None:
    now = datetime.now(UTC)
    m = empty_month()
    for f in ("Zeta", "grading", "éval", "eval", "Grading", "path_generation"):
        m["by_feature"][f] = {"calls": 1, "tokens_in": 1, "tokens_out": 1, "cost_micros": 0}
        m["calls"] += 1
    await ScopedStore.system("firestore.backfill").import_documents(USAGE_MONTHS, [(month_key(now), m)])
    out = await store.usage_summary(None, now.date())  # type: ignore[arg-type]
    assert [f["feature"] for f in out["by_feature"]] == [
        "eval",
        "éval",
        "grading",
        "Grading",
        "path_generation",
        "Zeta",
    ]
