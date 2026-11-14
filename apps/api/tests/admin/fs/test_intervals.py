"""Postgres interval parity (``admin.intervals``): months / days / microseconds are kept, and
timestamp arithmetic follows Postgres (months clamped to the month end, then days, then time)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.admin.intervals import (
    PgInterval,
    add_interval,
    components_sql,
    from_components,
    interval_days,
    subtract_interval,
)

YEAR = PgInterval(months=12)
MONTHS_18 = PgInterval(months=18)
DAYS_90 = PgInterval(days=90)
FS_MODULES = ("admin", "audit")  # for the fs_env fixture


def dt(y: int, m: int, d: int, h: int = 0) -> datetime:
    return datetime(y, m, d, h, tzinfo=UTC)


@pytest.mark.parametrize(
    ("ts", "iv", "expected"),
    [
        (dt(2025, 3, 1), YEAR, dt(2024, 3, 1)),  # a calendar year, not 365 days (2024 is a leap year)
        (dt(2024, 2, 29), YEAR, dt(2023, 2, 28)),  # leap day clamps to 28 Feb
        (dt(2025, 2, 28), YEAR, dt(2024, 2, 28)),
        (dt(2025, 8, 31), MONTHS_18, dt(2024, 2, 29)),  # 31 Aug - 18 months -> end of Feb 2024
        (dt(2026, 8, 31), MONTHS_18, dt(2025, 2, 28)),
        (dt(2024, 3, 1), DAYS_90, dt(2023, 12, 2)),  # 90 days across a leap February
        (dt(2025, 3, 1), DAYS_90, dt(2024, 12, 1)),
        (dt(2024, 3, 31, 5), PgInterval(1, 1, 3_600_000_000), dt(2024, 2, 28, 4)),  # months, days, time
    ],
)
def test_subtract_interval_matches_postgres(ts: datetime, iv: PgInterval, expected: datetime) -> None:
    assert subtract_interval(ts, iv) == expected
    assert ts - iv == expected  # datetime - PgInterval uses the same rule


def test_add_interval_and_reverse_operator() -> None:
    assert add_interval(dt(2024, 2, 29), YEAR) == dt(2025, 2, 28)
    assert dt(2024, 1, 31) + PgInterval(months=1) == dt(2024, 2, 29)
    assert dt(2023, 1, 31) + PgInterval(months=1) == dt(2023, 2, 28)
    assert add_interval(dt(2024, 1, 1), None) == dt(2024, 1, 1)


def test_ordering_views_and_legacy_values() -> None:
    # Postgres interval_cmp: a month counts as 30 days
    assert min(YEAR, PgInterval(days=400)) == YEAR
    assert DAYS_90 < YEAR < MONTHS_18
    assert interval_days(YEAR) == 365 and interval_days(MONTHS_18) == 545  # asyncpg's timedelta view
    assert interval_days(DAYS_90) == 90 and interval_days(None) is None
    # legacy Firestore rows (plain seconds, the former "seconds" kind) and timedeltas stay readable
    assert PgInterval.coerce(395 * 86400) == PgInterval(days=395)
    assert PgInterval.coerce(timedelta(days=2, hours=1)) == PgInterval(0, 2, 3_600_000_000)
    assert PgInterval.coerce({"months": 12, "days": 0, "microseconds": 0}) == YEAR
    assert PgInterval.coerce(YEAR.doc()) == YEAR


def test_backfill_reads_components() -> None:
    sql = components_sql("r.retention_interval")
    assert "date_part('year', r.retention_interval) * 12" in sql
    assert from_components({"iv_months": 18, "iv_days": 2, "iv_usec": 5}) == PgInterval(18, 2, 5)
    assert from_components({"iv_months": None, "iv_days": None, "iv_usec": None}) is None


async def test_retention_interval_on_firestore(fs_env: Any) -> None:
    """Retention rows keep the components on Firestore; the public helper returns the shortest
    active interval; a legacy row stored as plain seconds is still read."""
    from app.core.firestore.backfill import mappings
    from app.core.firestore.store import ScopedStore
    from app.modules.admin import public as admin_public
    from app.modules.admin.store_specs import RETENTION

    m = next(x for x in mappings("admin") if x.collection == RETENTION)
    base = {
        "data_category": "auth logs",
        "retention_class": "R-SEC",
        "basis": "law",
        "deletion_method": "purge",
        "legal_hold_aware": True,
        "job_name": "purge",
        "owner_module": "security",
        "is_active": True,
        "updated_by": None,
        "created_at": dt(2026, 1, 1),
        "updated_at": dt(2026, 1, 1),
        "retention_interval": timedelta(days=365),  # what asyncpg returns for '1 year' (lossy)
    }
    a = {
        **base,
        "id": uuid.uuid4(),
        "table_name": "risk_evaluations",
        "iv_months": 12,
        "iv_days": 0,
        "iv_usec": 0,
    }
    b = {
        **base,
        "id": uuid.uuid4(),
        "table_name": "risk_evaluations",
        "iv_months": 18,
        "iv_days": 0,
        "iv_usec": 0,
    }
    doc_a = m.transform(a)
    assert doc_a["retention_interval"] == {"months": 12, "days": 0, "microseconds": 0}
    st = ScopedStore.system("test.seed")
    legacy = {**m.transform(b), "table_name": "login_attempts", "retention_interval": 395 * 86400}
    await st.import_documents(RETENTION, [(str(a["id"]), doc_a), (str(b["id"]), m.transform(b))])
    await st.import_documents(RETENTION, [(str(uuid.uuid4()), legacy)])
    assert await admin_public.retention_interval(None, "risk_evaluations") == YEAR  # min(12, 18 months)
    assert await admin_public.retention_interval(None, "login_attempts") == PgInterval(days=395)
    assert await admin_public.retention_interval(None, "nothing") is None
    assert dt(2025, 3, 1) - await admin_public.retention_interval(None, "risk_evaluations") == dt(2024, 3, 1)  # type: ignore[operator]


async def test_policy_rows_by_case_decision(fs_env: Any) -> None:
    from app.core.ids import uuid7
    from app.modules.admin import public as admin_public

    d1, d2 = uuid7(), uuid7()
    await admin_public.write_setting(
        None, key="sessions.student.max_concurrent", scope_type="user", scope_id=uuid7(), value=3,
        changed_by=uuid7(), change_reason="case", case_decision_id=d1,
        expires_at=dt(2099, 1, 1),
    )  # fmt: skip
    rows = await admin_public.policy_settings_for_case_decisions(None, [d1, d2])
    assert [r.case_decision_id for r in rows] == [d1]
    assert await admin_public.policy_case_decision_ids(None, [d1, d2, uuid7()]) == {d1}
    assert await admin_public.policy_case_decision_ids(None, []) == set()
