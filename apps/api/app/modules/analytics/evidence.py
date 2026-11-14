"""Read-only service interface consumed by the ``learning`` module (analytics-event-schema
§3.9, §5.5 rule 8).

* ``video_coverage(session, user_id, lesson_asset_id) -> VideoCoverage | None`` — unique
  coverage (0-1) for the ``video_coverage`` completion rule (learning owns the threshold,
  proposed >= 0.9). Analytics never marks completion itself.
* ``lesson_time_evidence(session, user_id, lesson_id) -> LessonTimeEvidence`` — lifetime M5
  ("learning time"), M2 and M3 attributed to the lesson plus per-asset coverage. **Time is
  evidence only: no completion, certificate or grade may rest on it alone (CP-12).**

Both run under the caller's RLS context (the learner's own request, or a system context).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.params import MEASUREMENT_VERSION


@dataclass(frozen=True)
class VideoCoverage:
    lesson_asset_id: uuid.UUID
    coverage: float  # 0..1, lifetime unique coverage (seeks excluded)
    covered_s: float
    duration_s: int | None
    last_position_s: int | None
    updated_at: datetime


@dataclass(frozen=True)
class LessonTimeEvidence:
    lesson_id: uuid.UUID
    learning_s: int  # sum M5 attributed to the lesson
    active_s: int  # sum M2
    video_playback_s: int  # sum M3
    active_days: int
    first_activity: date | None
    last_activity: date | None
    coverage: list[VideoCoverage]
    measurement_version: str = MEASUREMENT_VERSION


def _fs() -> bool:
    from app.core.firestore.backend import uses_firestore

    return uses_firestore("analytics")


async def _fs_coverage(user_id: uuid.UUID, **eq: Any) -> list[tuple[Any, ...]]:
    """``video_watch_coverage`` rows of the user as the SQL selects them
    ``(lesson_asset_id, coverage_pct, covered_s, duration_s, last_position_s, updated_at)``."""
    from app.modules.analytics import fs_raw
    from app.modules.analytics.store_specs import VideoRow

    f = [(k, "==", str(v)) for k, v in eq.items()]
    rows = [VideoRow.of(d) for d in await fs_raw.all_docs("video_watch_coverage", user_id=user_id, filters=f)]
    rows.sort(key=lambda r: r.lesson_asset_id)
    return [
        (r.lesson_asset_id, r.coverage_pct, r.covered_s, r.duration_s, r.last_position_s, r.updated_at)
        for r in rows
    ]


async def video_coverage(
    session: AsyncSession, user_id: uuid.UUID, lesson_asset_id: uuid.UUID
) -> VideoCoverage | None:
    if _fs():
        got = await _fs_coverage(user_id, lesson_asset_id=lesson_asset_id)
        if not got:
            return None
        r = got[0]
        return VideoCoverage(r[0], float(r[1]) / 100.0, float(r[2]), r[3], r[4], r[5])
    row = (
        await session.execute(
            text(
                "SELECT lesson_asset_id, coverage_pct, covered_s, duration_s, last_position_s, updated_at "
                "FROM video_watch_coverage WHERE user_id = :u AND lesson_asset_id = :a"
            ),
            {"u": user_id, "a": lesson_asset_id},
        )
    ).first()
    if row is None:
        return None
    return VideoCoverage(row[0], float(row[1]) / 100.0, float(row[2]), row[3], row[4], row[5])


async def _lesson_evidence_pg(session: AsyncSession, user_id: uuid.UUID, lesson_id: uuid.UUID) -> Any:
    agg = (
        await session.execute(
            text(
                """
                SELECT coalesce(sum(m5_learning_s), 0), coalesce(sum(m2_active_s), 0),
                       coalesce(sum(m3_video_playback_s), 0), count(*) FILTER (WHERE m5_learning_s > 0),
                       min(activity_date), max(activity_date)
                FROM daily_learning_aggregates
                WHERE user_id = :u AND entity_kind = 'lesson' AND entity_id = :l AND measurement_version = :mv
                """
            ),
            {"u": user_id, "l": lesson_id, "mv": MEASUREMENT_VERSION},
        )
    ).one()
    cov_rows = (
        await session.execute(
            text(
                "SELECT lesson_asset_id, coverage_pct, covered_s, duration_s, last_position_s, updated_at "
                "FROM video_watch_coverage WHERE user_id = :u AND lesson_id = :l ORDER BY lesson_asset_id"
            ),
            {"u": user_id, "l": lesson_id},
        )
    ).all()
    return agg, cov_rows


async def lesson_time_evidence(
    session: AsyncSession, user_id: uuid.UUID, lesson_id: uuid.UUID
) -> LessonTimeEvidence:
    if _fs():
        from app.modules.analytics import fs_raw
        from app.modules.analytics.store_specs import DailyRow

        days = [
            r
            for r in (
                DailyRow.of(d)
                for d in await fs_raw.all_docs(
                    fs_raw.DAILY,
                    user_id=user_id,
                    filters=[("entity_kind", "==", "lesson"), ("entity_id", "==", str(lesson_id))],
                )
            )
            if r.measurement_version == MEASUREMENT_VERSION
        ]
        dates = [r.activity_date for r in days]
        agg: Any = (
            sum(r.m5_learning_s or 0 for r in days),
            sum(r.m2_active_s or 0 for r in days),
            sum(r.m3_video_playback_s or 0 for r in days),
            sum(1 for r in days if (r.m5_learning_s or 0) > 0),
            min(dates) if dates else None,
            max(dates) if dates else None,
        )
        cov_rows: Any = await _fs_coverage(user_id, lesson_id=lesson_id)
    else:
        agg, cov_rows = await _lesson_evidence_pg(session, user_id, lesson_id)
    return LessonTimeEvidence(
        lesson_id=lesson_id,
        learning_s=int(agg[0]),
        active_s=int(agg[1]),
        video_playback_s=int(agg[2]),
        active_days=int(agg[3]),
        first_activity=agg[4],
        last_activity=agg[5],
        coverage=[VideoCoverage(r[0], float(r[1]) / 100.0, float(r[2]), r[3], r[4], r[5]) for r in cov_rows],
    )


async def watched_seconds_for_lesson(
    session: AsyncSession, user_id: uuid.UUID, lesson_key: uuid.UUID
) -> int | None:
    """Adapter matching ``learning.service.register_video_coverage_lookup`` (``fn(session,
    user_id, lesson_key) -> watched_seconds | None``). Not registered automatically: learning
    decides when to switch its completion rule to the analytics coverage feed."""
    if _fs():
        got = await _fs_coverage(user_id, lesson_id=lesson_key)
        return int(sum(float(r[2]) for r in got)) if got else None
    row = (
        await session.execute(
            text("SELECT sum(covered_s) FROM video_watch_coverage WHERE user_id = :u AND lesson_id = :l"),
            {"u": user_id, "l": lesson_key},
        )
    ).first()
    return int(row[0]) if row and row[0] is not None else None


async def coverage_groups(
    session: AsyncSession, user_id: uuid.UUID, lesson_ids: list[uuid.UUID]
) -> list[tuple[Any, Any, Any]]:
    """``(lesson_asset_id, sum(covered_s), max(duration_s))`` of the user's coverage rows on these
    lessons, grouped by asset (NULLs ignored by the aggregates, as in SQL)."""
    if _fs():
        from app.modules.analytics import fs_raw
        from app.modules.analytics.store_specs import VideoRow

        want = set(lesson_ids)
        g: dict[Any, list[Any]] = {}
        # cost-media: filter by lesson in the query (30 ids per ``in``) instead of reading every
        # coverage document of the user (one per video ever watched) on each MED-05 heartbeat.
        docs: dict[str, Any] = {}
        for chunk in fs_raw._chunks(sorted({str(x) for x in want})):
            for d in await fs_raw.all_docs(
                "video_watch_coverage", user_id=user_id, filters=[("lesson_id", "in", chunk)]
            ):
                docs[d.id] = d
        for _id, d in sorted(docs.items()):  # document-id order, as the full scan returned them
            r = VideoRow.of(d)
            if r.lesson_id in want:
                g.setdefault(r.lesson_asset_id, []).append(r)
        out = []
        for a, rs in g.items():
            cov = [x.covered_s for x in rs if x.covered_s is not None]
            dur = [x.duration_s for x in rs if x.duration_s is not None]
            out.append((a, sum(cov) if cov else None, max(dur) if dur else None))
        return out
    rows = (
        await session.execute(
            text(
                "SELECT c.lesson_asset_id, sum(c.covered_s), max(c.duration_s) "
                "FROM video_watch_coverage c "
                "WHERE c.user_id = :u AND c.lesson_id = ANY(:l) GROUP BY c.lesson_asset_id"
            ),
            {"u": user_id, "l": lesson_ids},
        )
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]
