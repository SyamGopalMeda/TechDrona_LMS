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


async def video_coverage(
    session: AsyncSession, user_id: uuid.UUID, lesson_asset_id: uuid.UUID
) -> VideoCoverage | None:
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


async def lesson_time_evidence(
    session: AsyncSession, user_id: uuid.UUID, lesson_id: uuid.UUID
) -> LessonTimeEvidence:
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
    row = (
        await session.execute(
            text("SELECT sum(covered_s) FROM video_watch_coverage WHERE user_id = :u AND lesson_id = :l"),
            {"u": user_id, "l": lesson_key},
        )
    ).first()
    return int(row[0]) if row and row[0] is not None else None
