"""Postgres ``interval`` values with their three components (months, days, microseconds).

Postgres keeps an interval as ``(months, days, microseconds)`` and applies them to a timestamp in
that order: months first (the day of month clamped to the target month's last day), then days,
then the time part. ``'1 year'`` is 12 months, so ``ts - '1 year'`` is the same calendar date a
year earlier (29 Feb -> 28 Feb), not ``ts - 365 days``. asyncpg decodes intervals to a
``timedelta`` (months counted as 30 days, years as 365), which loses that; Firestore had stored
plain seconds. ``PgInterval`` keeps the components:

* stored on Firestore as ``{"months", "days", "microseconds"}``; a legacy plain number (seconds,
  the earlier ``"seconds"`` kind) or a ``timedelta`` is still readable (as days + time);
* ``ts + iv`` / ``ts - iv`` (and ``add_interval`` / ``subtract_interval``) use Postgres
  semantics in UTC (the API's database session time zone);
* ordering and ``min()`` follow Postgres ``interval_cmp`` (a month counts as 30 days);
* ``.days`` / ``total_seconds()`` give the asyncpg ``timedelta`` view for display code.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_USEC_PER_DAY = 86_400_000_000


@dataclass(frozen=True, slots=True)
class PgInterval:
    months: int = 0
    days: int = 0
    microseconds: int = 0

    # ------------------------------------------------------------------ construction

    @classmethod
    def from_timedelta(cls, td: timedelta) -> PgInterval:
        return cls(0, td.days, td.seconds * 1_000_000 + td.microseconds)

    @classmethod
    def coerce(cls, v: Any) -> PgInterval | None:
        """From a stored document value, a ``timedelta`` or a legacy number of seconds."""
        if v is None or isinstance(v, PgInterval):
            return v
        if isinstance(v, timedelta):
            return cls.from_timedelta(v)
        if isinstance(v, dict):
            return cls(int(v.get("months") or 0), int(v.get("days") or 0), int(v.get("microseconds") or 0))
        if isinstance(v, (int, float)):  # legacy: seconds
            return cls.from_timedelta(timedelta(seconds=float(v)))
        raise TypeError(f"not an interval: {v!r}")

    def doc(self) -> dict[str, int]:
        return {"months": self.months, "days": self.days, "microseconds": self.microseconds}

    # ------------------------------------------------------------------ views

    def as_timedelta(self) -> timedelta:
        """asyncpg's lossy view (years 365 days, remaining months 30 days)."""
        years, months = (
            divmod(self.months, 12) if self.months >= 0 else (-(-self.months // 12), -(-self.months % 12))
        )
        return timedelta(days=self.days + months * 30 + years * 365, microseconds=self.microseconds)

    def total_seconds(self) -> float:
        return self.as_timedelta().total_seconds()

    def _cmp_key(self) -> int:  # Postgres interval_cmp: 1 month = 30 days
        return (self.months * 30 + self.days) * _USEC_PER_DAY + self.microseconds

    def __lt__(self, other: Any) -> bool:
        return self._cmp_key() < PgInterval.coerce(other)._cmp_key()  # type: ignore[union-attr]

    def __le__(self, other: Any) -> bool:
        return self._cmp_key() <= PgInterval.coerce(other)._cmp_key()  # type: ignore[union-attr]

    def __gt__(self, other: Any) -> bool:
        return self._cmp_key() > PgInterval.coerce(other)._cmp_key()  # type: ignore[union-attr]

    def __ge__(self, other: Any) -> bool:
        return self._cmp_key() >= PgInterval.coerce(other)._cmp_key()  # type: ignore[union-attr]

    # ------------------------------------------------------------------ timestamp arithmetic

    def __radd__(self, ts: Any) -> Any:
        if isinstance(ts, datetime):
            return add_interval(ts, self)
        return NotImplemented

    def __rsub__(self, ts: Any) -> Any:
        if isinstance(ts, datetime):
            return subtract_interval(ts, self)
        return NotImplemented

    def __neg__(self) -> PgInterval:
        return PgInterval(-self.months, -self.days, -self.microseconds)


def _add_months(ts: datetime, months: int) -> datetime:
    if not months:
        return ts
    total = ts.year * 12 + (ts.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(ts.day, calendar.monthrange(year, month)[1])  # clamp to the month end
    return ts.replace(year=year, month=month, day=day)


def add_interval(ts: datetime, iv: Any) -> datetime:
    """``ts + iv`` with Postgres semantics (months, clamped; then days; then time), in UTC."""
    i = PgInterval.coerce(iv)
    if i is None:
        return ts
    tz = ts.tzinfo
    u = ts.astimezone(UTC) if tz is not None else ts
    u = _add_months(u, i.months)
    u = u + timedelta(days=i.days) + timedelta(microseconds=i.microseconds)
    return u.astimezone(tz) if tz is not None else u


def subtract_interval(ts: datetime, iv: Any) -> datetime:
    """``ts - iv`` with Postgres semantics (``ts + (-iv)``)."""
    i = PgInterval.coerce(iv)
    return ts if i is None else add_interval(ts, -i)


def interval_days(iv: Any) -> int | None:
    """Whole days as asyncpg reports them (``timedelta.days``), for display fields."""
    i = PgInterval.coerce(iv)
    return None if i is None else i.as_timedelta().days


# SQL that reads an interval column without asyncpg's lossy conversion (backfill, Postgres reads).
def components_sql(col: str, prefix: str = "iv") -> str:
    return (
        f"(date_part('year', {col}) * 12 + date_part('month', {col}))::int AS {prefix}_months, "
        f"date_part('day', {col})::int AS {prefix}_days, "
        f"((date_part('hour', {col}) * 3600 + date_part('minute', {col}) * 60) * 1000000"
        f" + date_part('microseconds', {col}))::bigint AS {prefix}_usec"
    )


def from_components(row: Any, prefix: str = "iv") -> PgInterval | None:
    m = row.get(f"{prefix}_months") if isinstance(row, dict) else getattr(row, f"{prefix}_months")
    if m is None:
        return None
    get = row.get if isinstance(row, dict) else lambda k: getattr(row, k)
    return PgInterval(int(m), int(get(f"{prefix}_days") or 0), int(get(f"{prefix}_usec") or 0))
