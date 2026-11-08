"""Time helpers (ADR-0012): storage and processing in UTC; IST only for presentation/rollups."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def utcnow() -> datetime:
    """Timezone-aware current UTC time. Never use naive datetimes."""
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime not allowed; attach a timezone")
    return dt.astimezone(UTC)


def to_rfc3339(dt: datetime) -> str:
    """API wire format: RFC 3339 UTC with millisecond precision and ``Z``."""
    dt = ensure_utc(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def to_rfc3339_micro(dt: datetime) -> str:
    """Lossless UTC rendering (microseconds) used for hashing/canonical forms."""
    return ensure_utc(dt).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ist_date(dt: datetime) -> date:
    """Asia/Kolkata calendar day used for daily rollups."""
    return ensure_utc(dt).astimezone(IST).date()


def seconds_since(dt: datetime | None, now: datetime | None = None) -> float | None:
    if dt is None:
        return None
    return ((now or utcnow()) - ensure_utc(dt)).total_seconds()


def within(dt: datetime | None, window: timedelta, now: datetime | None = None) -> bool:
    s = seconds_since(dt, now)
    return s is not None and 0 <= s <= window.total_seconds()
