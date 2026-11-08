"""Study plan arithmetic for allocations (pure functions; recomputed server-side, never trusted
from the client).

``per_day`` maps ``mon``…``sun`` to study hours. The plan walks calendar days from the start date
(inclusive), adding that weekday's hours until the path's total hours are covered; the day the
total is reached is the finish date. Per-step due dates use the same walk with the cumulative
hours of the leaf steps in order.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.core.errors import ProblemError

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_PLAN_DAYS = 3650
PACE_MODES = ("every_day", "weekdays", "weekends", "weekdays_weekends", "custom")


def _vf(field: str, code: str, message: str) -> ProblemError:
    return ProblemError("validation_failed", errors=[{"field": field, "code": code, "message": message}])


def _hours(v: Any, field: str) -> Decimal:
    try:
        d = Decimal(str(v))
    except Exception as e:
        raise _vf(field, "invalid", "Enter a number of hours") from e
    if d < 0 or d > 24:
        raise _vf(field, "out_of_range", "Hours per day must be between 0 and 24")
    return d.quantize(Decimal("0.01"))


def per_day_from_pace(pace: dict[str, Any]) -> dict[str, Decimal]:
    mode = pace.get("mode", "every_day")
    if mode not in PACE_MODES:
        raise _vf("pace.mode", "invalid", "Unknown study pace")
    if mode == "custom":
        raw = pace.get("per_day") or {}
        out = {d: _hours(raw.get(d, 0), f"pace.per_day.{d}") for d in DAYS}
    else:
        h = _hours(pace.get("hours_per_day", 2), "pace.hours_per_day")
        wk_end = _hours(pace.get("weekend_hours", h), "pace.weekend_hours")
        zero = Decimal("0")
        out = {}
        for i, d in enumerate(DAYS):
            weekend = i >= 5
            if mode == "every_day":
                out[d] = h
            elif mode == "weekdays":
                out[d] = zero if weekend else h
            elif mode == "weekends":
                out[d] = h if weekend else zero
            else:  # weekdays_weekends: own hours for Sat/Sun
                out[d] = wk_end if weekend else h
    if sum(out.values()) <= 0:
        raise _vf("pace", "no_study_time", "Choose at least one study day with hours")
    return out


def finish_date(start: date, total_hours: Decimal, per_day: dict[str, Decimal]) -> tuple[date, int]:
    """(finish date, number of calendar days in the plan)."""
    return due_dates(start, [total_hours], per_day)[0], _days(start, total_hours, per_day)


def _days(start: date, total: Decimal, per_day: dict[str, Decimal]) -> int:
    return (due_dates(start, [total], per_day)[0] - start).days + 1


def due_dates(start: date, cumulative: list[Decimal], per_day: dict[str, Decimal]) -> list[date]:
    """Day on which each cumulative hour mark is reached (marks must be non-decreasing)."""
    out: list[date] = []
    acc = Decimal("0")
    day = start
    i = 0
    for _ in range(MAX_PLAN_DAYS):
        acc += per_day[DAYS[day.weekday()]]
        while i < len(cumulative) and cumulative[i] <= acc:
            out.append(day)
            i += 1
        if i >= len(cumulative):
            return out
        day += timedelta(days=1)
    raise _vf("pace", "plan_too_long", "This pace would take more than ten years; add study time")


def plan(start: date, total_hours: Decimal, pace: dict[str, Any]) -> dict[str, Any]:
    per_day = per_day_from_pace(pace)
    fin, days = finish_date(start, total_hours, per_day)
    return {
        "per_day": per_day,
        "weekly_hours": sum(per_day.values()),
        "total_hours": total_hours,
        "finish_date": fin,
        "days": days,
    }
