"""Firestore side of ``reports.py`` (``TD_STORE_ANALYTICS=firestore``; data-analytics agent).

Each function returns the **rows of one SQL statement in ``reports.py``, as tuples in the same
column order and row order**, computed from the rollup documents with the SQL aggregate semantics
(``sum`` over integers, ``count(DISTINCT)``, ``bool_or``, ``min``, ``GROUP BY`` + ``ORDER BY``).
The report logic in ``reports.py`` (k-anonymity cells, distributions, buckets) is shared by both
stores. Other modules: orgs (batches), identity (synthetic users), learning (enrolments, lesson
progress) through their ``public.py``.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from app.core.firestore.collation import sort_key
from app.modules.analytics import fs_raw
from app.modules.analytics.fs_jobs import daily_between, real_users
from app.modules.analytics.store_specs import (
    CohortRow,
    DailyRow,
    IntervalRow,
    JobStateRow,
    RejectionRow,
    TopicRow,
)


async def user_daily(user_id: uuid.UUID, *, kind: str) -> list[Any]:
    docs = await fs_raw.all_docs(fs_raw.DAILY, user_id=user_id, filters=[("entity_kind", "==", kind)])
    return [DailyRow.of(d) for d in docs]


async def daily_totals(user_id: uuid.UUID, lo: date, hi: date, mv: str) -> list[tuple[Any, ...]]:
    rows = [
        r
        for r in await user_daily(user_id, kind="_total")
        if lo <= r.activity_date <= hi and r.measurement_version == mv
    ]
    return [
        (r.activity_date, r.m2_active_s, r.m3_video_playback_s, r.m4_assessment_s, r.m5_learning_s)
        for r in rows
    ]


def _s(vals: Any) -> int:
    return int(sum(v or 0 for v in vals))


async def topic_accuracy(user_id: uuid.UUID) -> list[tuple[Any, ...]]:
    g: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for r in await user_daily(user_id, kind="topic"):
        g[r.entity_id].append(r)
    return [
        (
            e,
            _s(x.questions_attempted for x in rs),
            _s(x.questions_correct for x in rs),
            _s(x.first_attempt_correct for x in rs),
            _s(x.m5_learning_s for x in rs),
        )
        for e, rs in sorted(g.items(), key=lambda kv: kv[0])
    ]


async def student_rows(user_id: uuid.UUID, mv: str) -> list[tuple[Any, ...]]:
    return [
        (
            r.activity_date,
            r.m5_learning_s,
            r.m2_active_s,
            r.m3_video_playback_s,
            r.m4_assessment_s,
            r.questions_attempted,
            r.questions_correct,
            r.code_runs,
            r.code_submissions,
            r.code_accepted,
            r.lessons_completed,
        )
        for r in await user_daily(user_id, kind="_total")
        if r.measurement_version == mv
    ]


async def student_tests(user_id: uuid.UUID) -> list[tuple[Any, ...]]:
    g: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for r in await user_daily(user_id, kind="test_attempt"):
        g[r.entity_id].append(r)
    rows = [
        (
            e,
            _s(x.m4_assessment_s for x in rs),
            _s(x.assessment_active_s for x in rs),
            min(x.activity_date for x in rs),
        )
        for e, rs in g.items()
    ]
    rows.sort(key=lambda t: t[3], reverse=True)
    return rows[:50]


async def batch_org(session: Any, batch_id: uuid.UUID) -> uuid.UUID | None:
    from app.modules.orgs import public as orgs

    b = await orgs.get_batch(session, batch_id)
    return b.organization_id if b is not None else None


async def batch_students(session: Any, batch_id: uuid.UUID) -> list[uuid.UUID]:
    from app.modules.orgs import public as orgs

    ids = list(
        dict.fromkeys(
            m.user_id for m in await orgs.batch_members(session, batch_ids=[batch_id], member_role="student")
        )
    )
    real = await real_users(session, ids)
    return [u for u in ids if u in real]


async def users_m5(users: list[uuid.UUID], lo: date, hi: date, mv: str) -> list[tuple[Any, ...]]:
    want = set(users)
    g: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for r in await daily_between(lo, hi, kind="_total"):
        if r.user_id in want and r.measurement_version == mv:
            g[r.user_id].append(r)
    return [
        (u, _s(x.m5_learning_s for x in rs), any(bool(x.implausible_day) for x in rs)) for u, rs in g.items()
    ]


async def weak_counts(users: list[uuid.UUID]) -> list[tuple[Any, ...]]:
    out = []
    for u in users:
        docs = await fs_raw.all_docs(fs_raw.TOPIC_MASTERY, user_id=u, filters=[("band", "==", "weak")])
        if docs:
            out.append((u, len([TopicRow.of(d) for d in docs])))
    return out


async def course_rows(session: Any, course_id: uuid.UUID, lo: date, hi: date) -> list[tuple[Any, ...]]:
    g: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for r in await daily_between(lo, hi, kind="course"):
        if r.entity_id == course_id and not r.implausible_day:
            g[r.user_id].append(r)
    real = await real_users(session, g)
    return [
        (u, _s(x.m5_learning_s for x in rs), _s(x.lessons_completed for x in rs))
        for u, rs in g.items()
        if u in real
    ]


async def active_users(session: Any, lo: date, hi: date) -> int:
    """``count(DISTINCT user_id)`` of ``_total`` rows with ``m5 > 0`` and ``lo < date <= hi``."""
    users = {
        r.user_id
        for r in await daily_between(lo, hi, kind="_total")
        if r.activity_date > lo and (r.m5_learning_s or 0) > 0
    }
    return len(await real_users(session, users))


async def platform_m5(session: Any, lo: date, hi: date) -> list[tuple[Any, ...]]:
    g: dict[uuid.UUID, int] = defaultdict(int)
    for r in await daily_between(lo, hi, kind="_total"):
        if r.activity_date > lo and not r.implausible_day and (r.m5_learning_s or 0) > 0:
            g[r.user_id] += int(r.m5_learning_s)
    real = await real_users(session, g)
    return [(v,) for u, v in g.items() if u in real]


async def benchmarks() -> list[tuple[Any, ...]]:
    docs = await fs_raw.all_docs("cohort_learning_aggregates", filters=[("period_kind", "==", "week")])
    rows = [CohortRow.of(d) for d in docs]
    rows = [r for r in rows if r.organization_id is None and r.batch_id is None]
    rows.sort(key=lambda r: r.period_start, reverse=True)
    return [(r.period_start, r.learners_active, r.m5_p50_s, r.m5_p90_s, r.suppressed) for r in rows[:8]]


async def ingest_health_rows(
    since: datetime, hour: datetime
) -> tuple[list[tuple[Any, ...]], tuple[int, ...], tuple[int, int], list[tuple[Any, ...]]]:
    """(rejections by code, event counters, interval gap counters, job states) of the window."""
    rej: dict[str, int] = defaultdict(int)
    for d in await fs_raw.all_docs(
        fs_raw.REJECTIONS, filters=[("hour_start", ">=", since)], order_by=(("hour_start", "asc"),)
    ):
        r = RejectionRow.of(d)
        rej[r.code] += int(r.count)
    hbs, evs = await fs_raw.rows_received_after(since - __import__("datetime").timedelta(microseconds=1))
    rows = [x for x in [*evs, *hbs] if x.received_at is not None and x.received_at >= since]

    def has(x: Any, f: str) -> bool:
        return f in (x.ingest_flags or [])

    ev = (
        len(rows),
        sum(1 for x in rows if has(x, "late")),
        sum(1 for x in rows if has(x, "large_skew")),
        sum(1 for x in rows if has(x, "clock_jump")),
        sum(1 for x in rows if x.received_at >= hour),
    )
    ivs = [
        IntervalRow.of(d)
        for d in await fs_raw.all_docs(
            fs_raw.INTERVALS, filters=[("started_at", ">=", since)], order_by=(("started_at", "asc"),)
        )
    ]
    gaps = (len(ivs), sum(1 for i in ivs if "seq_gap" in (i.flags or [])))
    jobs = [JobStateRow.of(d) for d in await fs_raw.all_docs(fs_raw.JOB_STATE)]
    return (
        sorted(rej.items(), key=lambda kv: sort_key(kv[0])),  # ORDER BY code (collation)
        ev,
        gaps,
        [(j.job, j.watermark, j.last_run_at, j.last_result) for j in jobs],
    )
