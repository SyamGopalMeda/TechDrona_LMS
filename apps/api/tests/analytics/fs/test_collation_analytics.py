"""Analytics Firestore-path text ORDER BY uses Postgres collation (emulator, no Postgres).

``ingest_health`` ``ORDER BY code``: Postgres ``en_US.utf8`` ignores punctuation at the first
level, so ``ab`` sorts before ``a_z`` (byte order would put ``a_z`` first, ``_`` < ``b``), and
case is a tertiary difference (``rate`` before ``Rate`` before ``rated``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

FS_MODULES = ("analytics",)
pytestmark = pytest.mark.usefixtures("fs_env")


async def test_ingest_health_rejection_codes_in_collation_order() -> None:
    from app.modules.analytics import fs_raw, fs_reports

    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    await fs_raw.add_rejections(
        hour, {("a_z", "x"): 1, ("ab", "x"): 2, ("Rate", "x"): 3, ("rated", "x"): 4, ("rate", "x"): 5}
    )
    rej, _ev, _gaps, _jobs = await fs_reports.ingest_health_rows(hour - timedelta(hours=1), hour)
    assert [c for c, _n in rej] == ["ab", "a_z", "rate", "Rate", "rated"]
    assert dict(rej) == {"a_z": 1, "ab": 2, "Rate": 3, "rated": 4, "rate": 5}


def test_max_text_uuid_uses_collation() -> None:
    """``max(col::text)``: uuids have hyphens at fixed positions, so collation and byte order agree;
    the helper goes through the collation key like the SQL."""
    import uuid

    from app.modules.analytics.fs_jobs import _max_text_uuid

    a, b = uuid.UUID(int=1), uuid.UUID(int=(1 << 127) + 5)
    assert _max_text_uuid([a, None, b]) == b
    assert _max_text_uuid([None]) is None
