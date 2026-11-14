"""``interval '3 years'`` of ``maint.purge_closed_cases`` on Firestore: calendar years with the
Postgres Feb-29 clamp, ``GREATEST`` ranked on 30-day months, and the purge boundary on a leap day
(a 3 x 365-day approximation would purge a day early)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.ids import uuid7
from app.modules.security import models as m
from app.modules.security.repo_fs_controls import disputed_cutoff, minus_years
from tests.security.fs.test_pass3_controls_reports_http import FS_MODULES, _case, _seed  # noqa: F401


def T(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            T(2028, 2, 29, 12),
            T(2025, 2, 28, 12),
        ),  # leap day -> clamped (SELECT '2028-02-29'::timestamptz - '3 years')
        (T(2028, 3, 1, 0), T(2025, 3, 1, 0)),
        (T(2027, 2, 28, 23, 59, 59), T(2024, 2, 28, 23, 59, 59)),
        (T(2027, 3, 1, 0), T(2024, 3, 1, 0)),
        (T(2024, 2, 29, 6), T(2021, 2, 28, 6)),
    ],
)
def test_minus_years_matches_postgres(now: datetime, expected: datetime) -> None:
    assert minus_years(now, 3) == expected


def test_greatest_ranks_on_30_day_months() -> None:
    from app.modules.admin.public import PgInterval

    now = T(2028, 2, 29, 12)
    assert disputed_cutoff(now, PgInterval(months=12)) == T(2025, 2, 28, 12)  # 3 years wins
    assert disputed_cutoff(now, timedelta(days=365)) == T(2025, 2, 28, 12)  # timedelta accepted
    # a tie (1080 days ranks equal to 36 months): GREATEST keeps its first argument, v_interval
    assert disputed_cutoff(now, PgInterval(days=1080)) == now - timedelta(days=1080)
    assert disputed_cutoff(now, PgInterval(days=1100)) == now - timedelta(days=1100)  # policy wins
    assert disputed_cutoff(now, PgInterval(months=48)) == T(2024, 2, 29, 12)  # 4 years, calendar


async def _purge_with(monkeypatch: pytest.MonkeyPatch, now: datetime, policy: Any) -> None:
    from app.core import runtime
    from app.modules.admin import public as admin_public
    from app.modules.identity import clock

    monkeypatch.setattr(runtime, "postgres_enabled", lambda: False)
    monkeypatch.setattr(clock, "now", lambda: now)

    async def interval(_s: Any, table: str) -> Any:
        assert table == "security_cases"
        return policy

    monkeypatch.setattr(admin_public, "retention_interval", interval)


async def _left() -> set[Any]:
    from sqlalchemy import select

    from app.modules.security import repo_fs_controls as secx
    from tests.commerce.firestore.conftest import FakeSession

    return {c.id for c in (await secx.execute(FakeSession().as_platform(), select(m.SecurityCase))).scalars()}


async def test_one_year_policy_across_a_leap_day(fs_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Policy ``'1 year'`` (12 months) on 2028-02-29 12:00: the cut-off is 2027-02-28 12:00
    (calendar year, clamped), not 2027-03-01 12:00 (365 days)."""
    from app.modules.admin.public import PgInterval
    from app.modules.security import retention

    await _purge_with(monkeypatch, T(2028, 2, 29, 12), PgInterval(months=12))
    before = _case(uuid7(), status="closed")
    before.closed_at = T(2027, 2, 28, 11, 59, 59)
    at = _case(uuid7(), status="closed")
    at.closed_at = T(2027, 2, 28, 12)
    next_day = _case(uuid7(), status="closed")  # purged by a 365-day cut-off, kept by Postgres
    next_day.closed_at = T(2027, 3, 1, 0)
    await _seed(before, at, next_day)
    out = await retention.purge_closed_cases()
    assert out is not None and out["rows_deleted"]["security_cases"] == 1
    assert await _left() == {at.id, next_day.id}


async def test_purge_boundary_on_a_leap_day(fs_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Disputed cases (second-level appeal) closed just before / exactly at the 3-year cut-off
    on 2028-02-29: Postgres purges only the first (``closed_at < now() - interval '3 years'``)."""
    from app.modules.admin.public import PgInterval
    from app.modules.security import retention

    await _purge_with(monkeypatch, T(2028, 2, 29, 12), PgInterval(months=12))
    cut = T(2025, 2, 28, 12)
    before = _case(uuid7(), status="closed")
    before.closed_at = cut - timedelta(seconds=1)
    at = _case(uuid7(), status="closed")
    at.closed_at = cut
    day_after = _case(uuid7(), status="closed")  # 2025-03-01: purged by 3x365 days, not by Postgres
    day_after.closed_at = T(2025, 3, 1, 0)
    appeals = [
        m.UnblockRequest(
            id=uuid7(),
            reference=f"UR-{i}",
            case_id=c.id,
            user_id=c.user_id,
            state="closed",
            is_second_level_appeal=True,
        )
        for i, c in enumerate((before, at, day_after))
    ]
    await _seed(before, at, day_after, *appeals)
    out = await retention.purge_closed_cases()
    assert out is not None and out["rows_deleted"]["security_cases"] == 1
    from sqlalchemy import select

    from app.modules.security import repo_fs_controls as secx
    from tests.commerce.firestore.conftest import FakeSession

    left = {c.id for c in (await secx.execute(FakeSession().as_platform(), select(m.SecurityCase))).scalars()}
    assert left == {at.id, day_after.id}
