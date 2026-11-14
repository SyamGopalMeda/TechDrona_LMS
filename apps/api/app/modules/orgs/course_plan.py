"""Batch delivery plans: the week-by-week schedule of a batch (no I/O, pure functions).

Ported from the website back office (``tech drona/src/lib/courseplan.js``: ``computeSchedule``,
``activitiesOf``, ``weekOf``, ``attendanceOf``; ``lmsplan.js``: ``attendanceFrom``) so the LMS and
the old website agree on every date:

* ``sessions = ceil(total_hours / daily_hours)``; one session per working day that is not a
  holiday, starting on the batch's ``starts_on``.
* Week ``n`` is the 7 calendar days ``starts_on + 7(n-1) .. starts_on + 7n - 1`` (week 1 starts on
  the start date, whatever weekday that is).
* Without a start date the weeks are counted (``ceil(sessions / working days per week)``) but have
  no dates, and there is no end date.
* ``working_days`` uses the website's numbering: 0 = Sunday .. 6 = Saturday.
* An activity's effective due date is its own ``due``, else the week's last session, else the
  week's last calendar day (a week left without sessions by holidays).
* Attendance: ``P`` present, ``L`` late (counts as attended), ``A`` absent. ``percent`` =
  round((P + L) / marked * 100), half up like JavaScript ``Math.round``.

Where things live (no duplicate "course" concept): lesson content stays in the LMS catalog
(``batches.course_id``), marketing information stays in the website catalogue
(``batches.website_course_slug``), and this plan (schedule + week titles/topics + activities) is the
batch's delivery plan, stored in ``batch_plans.plan`` (JSONB) after validation by ``PlanBody``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ACTIVITY_KINDS = ("project", "assignment", "presentation", "assessment", "test", "mock_interview")
ATTENDANCE_STATUSES = ("P", "L", "A")
MAX_WEEKS = 104
_GUARD_DAYS = 3660
_ID = re.compile(r"^[\w-]{4,40}$")
_HTTPS = re.compile(r"^https://\S+$", re.IGNORECASE)
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def js_weekday(d: date) -> int:
    """0 = Sunday .. 6 = Saturday (JavaScript ``getUTCDay``)."""
    return (d.weekday() + 1) % 7


def round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


# --------------------------------------------------------------------------- plan schema


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanActivity(_Strict):
    id: str = Field(pattern=r"^[\w-]{4,40}$")
    kind: Literal["project", "assignment", "presentation", "assessment", "test", "mock_interview"] = (
        "assignment"
    )
    title: str = Field(min_length=1, max_length=160)
    due: date | None = None
    required: bool = True


class PlanWeek(_Strict):
    title: str = Field(default="", max_length=160)
    topics: list[str] = Field(default_factory=list, max_length=30)
    activities: list[PlanActivity] = Field(default_factory=list, max_length=20)

    @field_validator("topics")
    @classmethod
    def _topics(cls, v: list[str]) -> list[str]:
        out = [t.strip()[:200] for t in v if isinstance(t, str) and t.strip()]
        return out


class PlanBody(_Strict):
    """The stored plan (``batch_plans.plan``) and the body of ``PUT /batches/{id}/plan``'s
    ``plan`` member. Unknown keys are refused (the website's lesson ``items`` are content and
    belong in the LMS catalog course, not here)."""

    total_hours: float = Field(default=0, ge=0, le=2000)
    daily_hours: float = Field(default=0, ge=0, le=12)
    working_days: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5], max_length=7)
    holidays: list[date] = Field(default_factory=list, max_length=120)
    class_time: str | None = Field(default=None, description="HH:MM, IST")
    meet_url: str | None = Field(default=None, max_length=500)
    registrations_open: bool = False
    weeks: list[PlanWeek] = Field(default_factory=list, max_length=MAX_WEEKS)

    @field_validator("working_days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("working days are 0 (Sunday) .. 6 (Saturday)")
        return sorted(set(v))

    @field_validator("holidays")
    @classmethod
    def _holidays(cls, v: list[date]) -> list[date]:
        return sorted(set(v))

    @field_validator("class_time")
    @classmethod
    def _time(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not _HHMM.match(v):
            raise ValueError("use HH:MM (24 hour)")
        return v

    @field_validator("meet_url")
    @classmethod
    def _meet(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        v = v.strip()
        if not _HTTPS.match(v):
            raise ValueError("the class link must start with https://")
        return v

    @field_validator("weeks")
    @classmethod
    def _unique_ids(cls, v: list[PlanWeek]) -> list[PlanWeek]:
        seen: set[str] = set()
        for w in v:
            for a in w.activities:
                if a.id in seen:
                    raise ValueError(f"activity id {a.id!r} is used twice")
                seen.add(a.id)
        return v

    def stored(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def load_plan(raw: dict[str, Any] | None) -> PlanBody:
    """A stored plan (tolerates rows written by older code: unknown keys are dropped)."""
    data = dict(raw or {})
    allowed = set(PlanBody.model_fields)
    return PlanBody.model_validate({k: v for k, v in data.items() if k in allowed})


# --------------------------------------------------------------------------- schedule


@dataclass(frozen=True)
class ScheduleWeek:
    n: int
    start: date | None
    end: date | None
    days: tuple[date, ...]


@dataclass(frozen=True)
class Schedule:
    sessions: int
    weeks: tuple[ScheduleWeek, ...]
    start_date: date | None
    end_date: date | None
    hours_planned: float
    days_per_week: int

    @property
    def weeks_count(self) -> int:
        return len(self.weeks)

    @property
    def class_dates(self) -> list[date]:
        return [d for w in self.weeks for d in w.days]


def compute_schedule(plan: PlanBody, start: date | None) -> Schedule:
    """``courseplan.js computeSchedule`` (see the module docstring)."""
    total, daily = float(plan.total_hours or 0), float(plan.daily_hours or 0)
    days = [d for d in plan.working_days if 0 <= d <= 6]
    sessions = math.ceil(total / daily) if total > 0 and daily > 0 else 0
    hours = sessions * daily
    if not sessions or not days:
        return Schedule(sessions, (), None, None, hours, len(days))
    if start is None:
        count = math.ceil(sessions / len(days))
        weeks = tuple(ScheduleWeek(i + 1, None, None, ()) for i in range(count))
        return Schedule(sessions, weeks, None, None, hours, len(days))
    holidays = set(plan.holidays)
    dates: list[date] = []
    d = start
    for _ in range(_GUARD_DAYS):
        if len(dates) >= sessions:
            break
        if js_weekday(d) in days and d not in holidays:
            dates.append(d)
        d += timedelta(days=1)
    buckets: list[list[date]] = []
    for x in dates:
        n = (x - start).days // 7 + 1
        while len(buckets) < n:
            buckets.append([])
        buckets[n - 1].append(x)
    weeks = tuple(
        ScheduleWeek(i + 1, start + timedelta(days=7 * i), start + timedelta(days=7 * i + 6), tuple(b))
        for i, b in enumerate(buckets)
    )
    return Schedule(sessions, weeks, start, dates[-1] if dates else None, hours, len(days))


def week_of(schedule: Schedule, today: date) -> int:
    """1-based week that contains ``today`` (0 before the start, after the end, or undated)."""
    for w in schedule.weeks:
        if w.start and w.end and w.start <= today <= w.end:
            return w.n
    return 0


def activities_of(plan: PlanBody, schedule: Schedule) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, w in enumerate(plan.weeks):
        sw = schedule.weeks[i] if i < len(schedule.weeks) else None
        fallback = sw.days[-1] if sw and sw.days else (sw.end if sw else None)
        for a in w.activities:
            due = a.due or fallback
            out.append(
                {
                    **a.model_dump(mode="json"),
                    "week": i + 1,
                    "week_title": w.title,
                    "due_effective": due.isoformat() if due else None,
                }
            )
    return out


def schedule_out(plan: PlanBody, start: date | None, today: date) -> dict[str, Any]:
    """API shape of the computed schedule (weeks merged with the plan's week titles/topics)."""
    s = compute_schedule(plan, start)
    acts = activities_of(plan, s)
    n_weeks = max(len(s.weeks), len(plan.weeks))
    weeks = []
    for i in range(n_weeks):
        sw = s.weeks[i] if i < len(s.weeks) else None
        pw = plan.weeks[i] if i < len(plan.weeks) else None
        weeks.append(
            {
                "n": i + 1,
                "from": sw.start.isoformat() if sw and sw.start else None,
                "to": sw.end.isoformat() if sw and sw.end else None,
                "days": [d.isoformat() for d in sw.days] if sw else [],
                "title": pw.title if pw else "",
                "topics": list(pw.topics) if pw else [],
                "activities": [a for a in acts if a["week"] == i + 1],
                "beyond_schedule": sw is None,
            }
        )
    return {
        "sessions": s.sessions,
        "weeks_count": s.weeks_count,
        "hours_planned": s.hours_planned,
        "days_per_week": s.days_per_week,
        "start_date": s.start_date.isoformat() if s.start_date else None,
        "end_date": s.end_date.isoformat() if s.end_date else None,
        "current_week": week_of(s, today),
        "today": today.isoformat(),
        "weeks": weeks,
        "required_activities": sum(1 for a in acts if a["required"]),
    }


# --------------------------------------------------------------------------- attendance


@dataclass(frozen=True)
class AttendanceSummary:
    present: int
    late: int
    absent: int
    marked: int

    @property
    def attended(self) -> int:
        return self.present + self.late

    @property
    def percent(self) -> int | None:
        return round_half_up(self.attended / self.marked * 100) if self.marked else None

    def out(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "late": self.late,
            "absent": self.absent,
            "marked": self.marked,
            "percent": self.percent,
        }


def summarize(statuses: list[str]) -> AttendanceSummary:
    p = sum(1 for s in statuses if s == "P")
    late = sum(1 for s in statuses if s == "L")
    a = sum(1 for s in statuses if s == "A")
    return AttendanceSummary(p, late, a, p + late + a)


def attendance_block_reason(summary: AttendanceSummary, min_percent: int | None) -> str | None:
    """Certificate gate (website ``evaluate``): off when no minimum is set; classes that were
    never marked do not block (``marked == 0``); otherwise ``percent >= min``."""
    if not min_percent or summary.marked == 0:
        return None
    pct = summary.percent or 0
    if pct >= min_percent:
        return None
    return f"Attendance is {pct}% (at least {min_percent}% is needed)"
