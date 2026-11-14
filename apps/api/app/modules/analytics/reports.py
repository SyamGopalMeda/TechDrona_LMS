"""Report queries (analytics-event-schema §7; ANL-04..10, ANL-12). "Learning time" is always
M5. Aggregate cells below the k-floor are suppressed (``"<10"``); synthetic users never count.

Rules applied here:

* Trainers, evaluators and Admin see identifiable per-student learning metrics only for the
  active students of a batch in their granted scope — never M1, device data or the security
  feed (§7.3). Single company: there are no organization reports; a batch report covers the
  students' whole Tech Drona activity and is read under a system context after the API has
  checked the caller's batch scope (analytics RLS no longer exposes org rows to students).
* "Needs attention" uses progress and mastery only, never time patterns (§4.6, §7.2), for
  adults and minors alike.
* Minors: the active-days streak is shown as a neutral count, not a streak (§7.1).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context
from app.core.time import ist_date, to_rfc3339
from app.modules.analytics import hooks
from app.modules.analytics.jobs import _pct, week_start
from app.modules.analytics.mastery import get_topic_mastery
from app.modules.analytics.params import (
    K_MIN_COHORT,
    K_MIN_PERCENTILE_REFERENCE,
    MEASUREMENT_VERSION,
    TM,
    config_payload,
)

SUPPRESSED = "<10"


def how_we_measure() -> dict[str, Any]:
    cfg = config_payload(False, "adult")
    return {"measurement_version": MEASUREMENT_VERSION, "params": cfg["params"], "learning_time_metric": "M5"}


def k_cell(n: int, value: Any, k: int = K_MIN_COHORT) -> Any:
    return value if n >= k else SUPPRESSED


def _dist(values: list[int], k: int = K_MIN_COHORT) -> dict[str, Any]:
    n = len(values)
    if n < k:
        return {"n": SUPPRESSED, "median_s": SUPPRESSED, "p90_s": SUPPRESSED, "suppressed": True}
    return {"n": n, "median_s": _pct(values, 0.5), "p90_s": _pct(values, 0.9), "suppressed": False}


# --------------------------------------------------------------------------- student (self)


def _fs() -> bool:
    from app.core.firestore.backend import uses_firestore

    return uses_firestore("analytics")


async def _daily_totals(session: AsyncSession, user_id: uuid.UUID, lo: date, hi: date) -> dict[date, Any]:
    if _fs():
        from app.modules.analytics import fs_reports

        return {r[0]: r for r in await fs_reports.daily_totals(user_id, lo, hi, MEASUREMENT_VERSION)}
    rows = (
        await session.execute(
            text(
                "SELECT activity_date, m2_active_s, m3_video_playback_s, m4_assessment_s, m5_learning_s "
                "FROM daily_learning_aggregates WHERE user_id = :u AND entity_kind = '_total' "
                "AND activity_date BETWEEN :lo AND :hi AND measurement_version = :mv"
            ),
            {"u": user_id, "lo": lo, "hi": hi, "mv": MEASUREMENT_VERSION},
        )
    ).all()
    return {r[0]: r for r in rows}


async def learning_time_series(
    session: AsyncSession, user_id: uuid.UUID, lo: date, hi: date, grain: str
) -> list[dict[str, Any]]:
    days = await _daily_totals(session, user_id, lo, hi)
    buckets: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    d = lo
    while d <= hi:
        key = week_start(d) if grain == "week" else d
        b = buckets[key]
        r = days.get(d)
        if r is not None:
            b["active_s"] += r[1]
            b["video_s"] += r[2]
            b["assessment_s"] += r[3]
            b["learning_s"] += r[4]
            b["active_days"] += 1 if r[4] >= 600 else 0
        else:
            b["learning_s"] += 0
        d += timedelta(days=1)
    out = []
    for k in sorted(buckets):
        b = buckets[k]
        point: dict[str, Any] = {
            "period_start": k.isoformat(),
            "learning_s": b["learning_s"],
            "active_s": b["active_s"],
            "video_s": b["video_s"],
            "assessment_s": b["assessment_s"],
        }
        if grain == "week":
            point["active_days"] = b["active_days"]
        out.append(point)
    return out


async def _streak(session: AsyncSession, user_id: uuid.UUID, today: date) -> int:
    days = await _daily_totals(session, user_id, today - timedelta(days=365), today)
    d = today if (today in days and days[today][4] >= 600) else today - timedelta(days=1)
    n = 0
    while d in days and days[d][4] >= 600:
        n += 1
        d -= timedelta(days=1)
    return n


async def _topic_accuracy(session: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    sql = (
        "SELECT entity_id, sum(questions_attempted), sum(questions_correct), sum(first_attempt_correct), "
        "sum(m5_learning_s) FROM daily_learning_aggregates WHERE user_id = :u AND entity_kind = 'topic'"
    )
    params: dict[str, Any] = {"u": user_id}
    if _fs():
        from app.modules.analytics import fs_reports

        rows: Any = await fs_reports.topic_accuracy(user_id)
    else:
        rows = (await session.execute(text(sql + " GROUP BY entity_id ORDER BY entity_id"), params)).all()
    return [
        {
            "topic_id": str(r[0]),
            "answered": int(r[1]),
            "correct": int(r[2]),
            "accuracy": round(int(r[2]) / int(r[1]), 4) if r[1] else None,
            "learning_s": int(r[4]),
        }
        for r in rows
    ]


async def student_metrics(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    today: date,
    privacy_tier: str,
) -> dict[str, Any]:
    """§7.1 metrics: everything the learner owns."""
    params: dict[str, Any] = {"u": user_id, "k": "_total", "mv": MEASUREMENT_VERSION}
    monday = week_start(today)
    rows: Any
    tests: Any
    if _fs():
        from app.modules.analytics import fs_reports

        rows = await fs_reports.student_rows(user_id, MEASUREMENT_VERSION)
    else:
        rows = None
    if rows is None:
        rows = (
            await session.execute(
                text(
                    "SELECT activity_date, m5_learning_s, m2_active_s, m3_video_playback_s, m4_assessment_s, "
                    "questions_attempted, questions_correct, code_runs, code_submissions, code_accepted, "
                    "lessons_completed "
                    "FROM daily_learning_aggregates WHERE user_id = :u AND entity_kind = :k AND "
                    "measurement_version = :mv"
                ),
                params,
            )
        ).all()
    today_s = sum(r[1] for r in rows if r[0] == today)
    week_s = sum(r[1] for r in rows if monday <= r[0] <= today)
    active_days_30 = len({r[0] for r in rows if r[1] >= 600 and r[0] > today - timedelta(days=30)})
    mastery_rows = await get_topic_mastery(session, user_id)
    if _fs():
        from app.modules.analytics import fs_reports

        tests = await fs_reports.student_tests(user_id)
    else:
        tests = None
    if tests is None:
        tests = (
            await session.execute(
                text(
                    "SELECT entity_id, sum(m4_assessment_s), sum(assessment_active_s), min(activity_date) "
                    "FROM daily_learning_aggregates WHERE user_id = :u AND entity_kind = 'test_attempt'"
                    + " GROUP BY entity_id ORDER BY min(activity_date) DESC LIMIT 50"
                ),
                params,
            )
        ).all()
    out: dict[str, Any] = {
        "learning_time": {"today_s": today_s, "this_week_s": week_s, "metric": "M5"},
        "mastery": [
            {
                "topic_id": str(m.topic_id),
                "band": m.band,
                "mastery": m.mastery,
                "weighted_accuracy": m.weighted_accuracy,
                "n": m.attempts,
                "model_version": m.model_version,
            }
            for m in mastery_rows
        ],
        "accuracy_by_topic": await _topic_accuracy(session, user_id),
        "tests": [
            {"test_attempt_id": str(t[0]), "attempt_time_s": int(t[1]), "time_on_test_page_s": int(t[2])}
            for t in tests
        ],
        "coding": {
            "runs": sum(r[7] for r in rows),
            "submissions": sum(r[8] for r in rows),
            "accepted": sum(r[9] for r in rows),
        },
        "lessons_completed": sum(r[10] for r in rows),
        "how_we_measure": how_we_measure(),
    }
    if privacy_tier == "minor":
        out["active_days_last_30"] = active_days_30  # neutral count, no streak mechanic
    else:
        out["active_days_streak"] = await _streak(session, user_id, today)
        out["active_days_last_30"] = active_days_30
    return out


# ------------------------------------------------------------------ batch (trainer / evaluator / Admin)


async def batch_org(session: AsyncSession, batch_id: uuid.UUID) -> uuid.UUID | None:
    from app.modules.analytics import fs_reports

    return await fs_reports.batch_org(session, batch_id)  # orgs.public (both stores)


async def _batch_students(session: AsyncSession, batch_id: uuid.UUID) -> list[uuid.UUID]:
    from app.modules.analytics import fs_reports

    return await fs_reports.batch_students(session, batch_id)  # orgs + identity public


async def _users_m5(
    session: AsyncSession, users: list[uuid.UUID], lo: date, hi: date
) -> dict[uuid.UUID, tuple[int, bool]]:
    if not users:
        return {}
    if _fs():
        from app.modules.analytics import fs_reports

        return {
            r[0]: (int(r[1]), bool(r[2]))
            for r in await fs_reports.users_m5(users, lo, hi, MEASUREMENT_VERSION)
        }
    rows = (
        await session.execute(
            text(
                "SELECT user_id, sum(m5_learning_s), bool_or(implausible_day) FROM daily_learning_aggregates "
                "WHERE entity_kind = '_total' AND activity_date BETWEEN :lo AND :hi "
                "AND user_id = ANY(:us) AND measurement_version = :mv GROUP BY user_id"
            ),
            {"lo": lo, "hi": hi, "us": users, "mv": MEASUREMENT_VERSION},
        )
    ).all()
    return {r[0]: (int(r[1]), bool(r[2])) for r in rows}


async def _weak_counts(session: AsyncSession, users: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not users:
        return {}
    if _fs():
        from app.modules.analytics import fs_reports

        return {r[0]: int(r[1]) for r in await fs_reports.weak_counts(users)}
    rows = (
        await session.execute(
            text(
                "SELECT user_id, count(*) FROM topic_mastery WHERE user_id = ANY(:us) AND band = 'weak' "
                "GROUP BY user_id"
            ),
            {"us": users},
        )
    ).all()
    return {r[0]: int(r[1]) for r in rows}


_PROGRESS_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("not_started", 0.0, 0.0),
    ("1-25", 0.01, 25.0),
    ("26-50", 25.01, 50.0),
    ("51-75", 50.01, 75.0),
    ("76-99", 75.01, 99.99),
    ("completed", 100.0, 100.0),
)
FUNNEL_MAX_COURSES = 5

_Enr = tuple[uuid.UUID, uuid.UUID, uuid.UUID, float, bool]


async def _enrolments(session: AsyncSession, users: list[uuid.UUID]) -> list[_Enr]:
    """(enrolment_id, user_id, course_id, progress_pct, completed) for the enrolments of
    ``users``; withdrawn ones excluded."""
    if not users:
        return []
    from app.modules.learning import public as learning

    return list(await learning.enrolments_of_users(session, users))


def _bucket_of(pct: float, done: bool) -> str:
    if done or pct >= 100:
        return "completed"
    if pct <= 0:
        return "not_started"
    if pct <= 25:
        return "1-25"
    if pct <= 50:
        return "26-50"
    if pct <= 75:
        return "51-75"
    return "76-99"


def _progress_distribution(enrolments: list[_Enr]) -> dict[str, Any]:
    """Enrolments per course-progress bucket (batch report). Aggregate cells are k-floored on
    the enrolment count like every other cohort cell."""
    n = len(enrolments)
    counts = {label: 0 for label, _lo, _hi in _PROGRESS_BUCKETS}
    for _e, _u, _c, pct, done in enrolments:
        counts[_bucket_of(pct, done)] += 1
    return {
        "enrolments": k_cell(n, n),
        "suppressed": n < K_MIN_COHORT,
        "buckets": [
            {"bucket": label, "min_pct": lo, "max_pct": hi, "enrolments": k_cell(n, counts[label])}
            for label, lo, hi in _PROGRESS_BUCKETS
        ],
    }


async def _lesson_funnel(session: AsyncSession, enrolments: list[_Enr]) -> list[dict[str, Any]]:
    """Per course (most-enrolled first, at most ``FUNNEL_MAX_COURSES``): for each lesson of the
    course's current version in outline order, how many of these enrolments opened it and
    completed it (``lesson_progress`` by ``lesson_key``). Counts are k-floored on the course's
    enrolment count."""
    by_course: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for e, _u, c, _p, _d in enrolments:
        by_course[c].append(e)
    courses = sorted(by_course, key=lambda c: (-len(by_course[c]), str(c)))[:FUNNEL_MAX_COURSES]
    from app.modules.catalog import api as catalog_api

    out: list[dict[str, Any]] = []
    titles = {cid: c.title for cid, c in (await catalog_api.get_courses(session, courses)).items()}
    for course in courses:
        enrolled = by_course[course]
        n = len(enrolled)
        title = titles.get(course)
        lessons = await catalog_api.current_outline_lessons(session, course)
        from app.modules.learning import public as learning

        counts = await learning.lesson_progress_counts(session, enrolled)
        progress: Any = [(k, v[0], v[1]) for k, v in counts.items()]
        stats = {r[0]: (int(r[1]), int(r[2])) for r in progress}
        out.append(
            {
                "course_id": str(course),
                "course_title": title,
                "enrolments": k_cell(n, n),
                "suppressed": n < K_MIN_COHORT,
                "steps": [
                    {
                        "lesson_key": str(key),
                        "title": ltitle,
                        "is_required": bool(req),
                        "started": k_cell(n, stats.get(key, (0, 0))[0]),
                        "completed": k_cell(n, stats.get(key, (0, 0))[1]),
                    }
                    for key, ltitle, req in lessons
                ],
            }
        )
    return out


async def batch_report(session: AsyncSession, batch_id: uuid.UUID, *, today: date) -> dict[str, Any] | None:
    """Batch report (trainer, evaluator, Admin). The caller's batch scope is checked by the API;
    ``batch_org`` runs under the caller's RLS (the batch must be visible), then the aggregates of
    the batch's active students are read under a system context."""
    if await batch_org(session, batch_id) is None:
        return None
    async with system_context(session, "analytics.batch_report"):
        students = await _batch_students(session, batch_id)
        monday = week_start(today)
        week = await _users_m5(session, students, monday, today)
        weak = await _weak_counts(session, students)
        enrolments = await _enrolments(session, students)
        funnel = await _lesson_funnel(session, enrolments)
    learners = []
    for u in students:
        m5, _imp = week.get(u, (0, False))
        reasons = []
        if weak.get(u, 0) >= 2:
            reasons.append("weak_required_topics")
        learners.append(
            {
                "user_id": str(u),
                "weekly_learning_s": m5,
                "weak_topics": weak.get(u, 0),
                "needs_attention": bool(reasons),
                "reasons": reasons,
            }
        )
    values = [m for u, (m, imp) in week.items() if m > 0 and not imp]
    return {
        "batch_id": str(batch_id),
        "week_start": monday.isoformat(),
        "learners_total": len(students),
        "weekly_learning_time": _dist(values),
        "learners": learners,
        "progress_distribution": _progress_distribution(enrolments),
        "lesson_funnel": funnel,
        "measurement_version": MEASUREMENT_VERSION,
    }


async def count_batch_students(session: AsyncSession, batch_id: uuid.UUID) -> int:
    async with system_context(session, "analytics.batch_report"):
        return len(await _batch_students(session, batch_id))


# --------------------------------------------------------------------------- content / platform


async def course_report(session: AsyncSession, course_id: uuid.UUID, *, today: date) -> dict[str, Any]:
    lo = today - timedelta(days=29)
    rows: Any
    if _fs():
        from app.modules.analytics import fs_reports

        rows = await fs_reports.course_rows(session, course_id, lo, today)
    else:
        rows = None
    if rows is None:
        rows = (
            await session.execute(
                text(
                    "SELECT d.user_id, sum(d.m5_learning_s), sum(d.lessons_completed) FROM "
                    "daily_learning_aggregates d "
                    "WHERE NOT (d.user_id = ANY(:syn)) AND "
                    "d.entity_kind = 'course' AND d.entity_id = :c "
                    "AND d.activity_date BETWEEN :lo AND :hi "
                    "AND NOT d.implausible_day GROUP BY d.user_id"
                ),
                {"c": course_id, "lo": lo, "hi": today, "syn": await hooks.synthetic_user_ids(session)},
            )
        ).all()
    learners = len(rows)
    return {
        "course_id": str(course_id),
        "period": {"from": lo.isoformat(), "to": today.isoformat()},
        "learners_active": k_cell(learners, learners),
        "learning_time_per_learner": _dist([int(r[1]) for r in rows if r[1] > 0]),
        "lessons_completed": k_cell(learners, sum(int(r[2]) for r in rows)),
        "video_drop_off": None,  # needs catalog asset -> course mapping (Planned)
        "measurement_version": MEASUREMENT_VERSION,
    }


async def platform_report(session: AsyncSession, *, today: date) -> dict[str, Any]:
    async def active_users(days: int) -> int:
        if _fs():
            from app.modules.analytics import fs_reports

            return await fs_reports.active_users(session, today - timedelta(days=days), today)
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(DISTINCT d.user_id) FROM daily_learning_aggregates d "
                        "WHERE NOT (d.user_id = ANY(:syn)) AND "
                        "d.entity_kind = '_total' AND d.m5_learning_s > 0 AND d.activity_date > :lo "
                        "AND d.activity_date <= :hi"
                    ),
                    {
                        "lo": today - timedelta(days=days),
                        "hi": today,
                        "syn": await hooks.synthetic_user_ids(session),
                    },
                )
            ).scalar()
            or 0
        )

    per_user: Any
    benchmarks: Any
    if _fs():
        from app.modules.analytics import fs_reports

        per_user = await fs_reports.platform_m5(session, today - timedelta(days=30), today)
        benchmarks = await fs_reports.benchmarks()
    else:
        per_user = None
    if per_user is None:
        per_user = (
            await session.execute(
                text(
                    "SELECT sum(d.m5_learning_s) FROM daily_learning_aggregates d "
                    "WHERE NOT (d.user_id = ANY(:syn)) AND "
                    "d.entity_kind = '_total' AND d.activity_date > :lo AND d.activity_date <= :hi "
                    "AND NOT d.implausible_day AND d.m5_learning_s > 0 GROUP BY d.user_id"
                ),
                {
                    "lo": today - timedelta(days=30),
                    "hi": today,
                    "syn": await hooks.synthetic_user_ids(session),
                },
            )
        ).all()
    m5 = [int(r[0]) for r in per_user]
    if not _fs():
        benchmarks = (
            await session.execute(
                text(
                    "SELECT period_start, learners_active, m5_p50_s, m5_p90_s, suppressed FROM "
                    "cohort_learning_aggregates "
                    "WHERE organization_id IS NULL AND batch_id IS NULL AND period_kind = 'week' "
                    "ORDER BY period_start DESC LIMIT 8"
                )
            )
        ).all()
    return {
        "dau": await active_users(1),
        "wau": await active_users(7),
        "mau": await active_users(30),
        "learning_time_30d": {"total_s": sum(m5), **_dist(m5, K_MIN_PERCENTILE_REFERENCE)},
        "cohort_benchmarks": [
            {
                "week_start": b[0].isoformat(),
                "learners_active": b[1],
                "m5_p50_s": b[2],
                "m5_p90_s": b[3],
                "suppressed": b[4],
            }
            for b in benchmarks
        ],
        "measurement_version": MEASUREMENT_VERSION,
    }


async def ingest_health(session: AsyncSession, *, now: datetime) -> dict[str, Any]:
    since = now - timedelta(hours=24)
    rej: Any
    ev: Any
    gaps: Any
    jobs: Any
    if _fs():
        from app.modules.analytics import fs_reports

        rej, ev, gaps, jobs = await fs_reports.ingest_health_rows(since, now - timedelta(hours=1))
    else:
        rej, ev, gaps, jobs = await _ingest_health_pg(session, since, now)
    return _ingest_health_out(rej, ev, gaps, jobs, now)


async def _ingest_health_pg(session: AsyncSession, since: datetime, now: datetime) -> Any:
    rej = (
        await session.execute(
            text(
                "SELECT code, sum(count) FROM analytics_ingest_rejections WHERE hour_start >= :s GROUP "
                "BY code ORDER BY code"
            ),
            {"s": since},
        )
    ).all()
    ev = (
        await session.execute(
            text(
                """
                SELECT count(*),
                       count(*) FILTER (WHERE 'late' = ANY(ingest_flags)),
                       count(*) FILTER (WHERE 'large_skew' = ANY(ingest_flags)),
                       count(*) FILTER (WHERE 'clock_jump' = ANY(ingest_flags)),
                       count(*) FILTER (WHERE received_at >= :h)
                FROM (SELECT ingest_flags, received_at FROM analytics_events WHERE received_at >= :s
                      UNION ALL SELECT ingest_flags, received_at FROM activity_heartbeats
                          WHERE received_at >= :s) x
                """
            ),
            {"s": since, "h": now - timedelta(hours=1)},
        )
    ).one()
    gaps = (
        await session.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE 'seq_gap' = ANY(flags)) FROM engagement_intervals "
                "WHERE started_at >= :s"
            ),
            {"s": since},
        )
    ).one()
    jobs = (
        await session.execute(
            text("SELECT job, watermark, last_run_at, last_result FROM analytics_job_state")
        )
    ).all()
    return rej, ev, gaps, jobs


def _ingest_health_out(rej: Any, ev: Any, gaps: Any, jobs: Any, now: datetime) -> dict[str, Any]:
    total = int(ev[0])
    rejected = sum(int(r[1]) for r in rej)
    builder = next((j for j in jobs if j[0] == "interval_builder"), None)
    return {
        "window_h": 24,
        "events_per_s_last_hour": round(int(ev[4]) / 3600, 3),
        "accepted_24h": total,
        "rejected_24h": rejected,
        "rejection_rate": round(rejected / (total + rejected), 4) if total + rejected else 0.0,
        "rejections_by_code": {r[0]: int(r[1]) for r in rej},
        "late_pct": round(int(ev[1]) / total, 4) if total else 0.0,
        "large_skew_pct": round(int(ev[2]) / total, 4) if total else 0.0,
        "clock_jump_pct": round(int(ev[3]) / total, 4) if total else 0.0,
        "seq_gap_pct": round(int(gaps[1]) / int(gaps[0]), 4) if gaps[0] else 0.0,
        "duplicates": None,  # duplicates are not stored (ON CONFLICT DO NOTHING); counter Planned
        "builder_lag_s": round((now - builder[1]).total_seconds()) if builder and builder[1] else None,
        "jobs": {j[0]: {"last_run_at": to_rfc3339(j[2]) if j[2] else None, "result": j[3]} for j in jobs},
        "measurement_version": MEASUREMENT_VERSION,
        "freeze_after_days": TM.freeze_after_days,
    }


def ist_today(now: datetime) -> date:
    return ist_date(now)
