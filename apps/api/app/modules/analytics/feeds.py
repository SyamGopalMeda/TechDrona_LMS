"""Read-only service interface consumed by the ``security`` module (analytics-event-schema
§6.5; reconciliation §3.10). **Security never queries raw analytics tables.**

Eligibility for both functions: ``privacy_tier = adult``, not synthetic, and an active
``security_monitoring`` consent. Everyone else (minors always) gets ``[]``.

* ``get_activity_summary(session, user_id, from_date, to_date) -> list[ActivityFeedDay]``
  — daily rows from ``security_activity_feed_daily`` (built 04:30 IST for D-1; 180 d).
* ``get_engaged_buckets(session, user_id, from_ts, to_ts) -> list[EngagedBucket]``
  — 5-minute buckets of engaged heartbeats ``(device_id, auth_session_id, bucket_5min,
  activity_kind)``; no content identities; window limited by heartbeat retention (35 d).
* ``get_learning_activity(session, from_date, to_date, granularity=)``
  — H11 (ADM-04): active learners and engaged/learning minutes per day/week/month from the
  daily aggregates, platform-wide or per org with k-floor suppression. Not per-user.

The caller passes its own session; these functions switch it to a named system context
for the read (the caller is a trusted in-process module, not a user request).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context
from app.modules.analytics.jobs import security_feed_eligible


@dataclass(frozen=True)
class ActivityFeedDay:
    activity_date: date
    active_devices: int
    multi_device_overlap_s: int
    max_concurrent_active_page_instances: int
    active_hours_bitmap: int  # 24-bit IST hour presence; hour-level only
    implausible_day: bool
    plausibility_violations: dict[str, Any]
    clock_jump_count: int
    large_skew_count: int
    feed_version: str


@dataclass(frozen=True)
class EngagedBucket:
    device_id: uuid.UUID | None
    auth_session_id: uuid.UUID | None
    bucket_5min: datetime
    activity_kind: str  # interactive | media | hidden_playback


async def get_activity_summary(
    session: AsyncSession, user_id: uuid.UUID, from_date: date, to_date: date
) -> list[ActivityFeedDay]:
    await system_context(session, "analytics.feed_read")
    if not await security_feed_eligible(session, user_id):
        return []
    rows = (
        await session.execute(
            text(
                """
                SELECT activity_date, active_devices, multi_device_overlap_s,
                    max_concurrent_active_page_instances,
                       active_hours_bitmap, implausible_day, plausibility_violations, clock_jump_count,
                       large_skew_count, feed_version
                FROM security_activity_feed_daily
                WHERE user_id = :u AND activity_date BETWEEN :a AND :b ORDER BY activity_date
                """
            ),
            {"u": user_id, "a": from_date, "b": to_date},
        )
    ).all()
    return [ActivityFeedDay(*r) for r in rows]


async def get_engaged_buckets(
    session: AsyncSession, user_id: uuid.UUID, from_ts: datetime, to_ts: datetime
) -> list[EngagedBucket]:
    await system_context(session, "analytics.feed_read")
    if not await security_feed_eligible(session, user_id):
        return []
    rows = (
        await session.execute(
            text(
                """
                SELECT device_id, auth_session_id,
                       to_timestamp(floor(extract(epoch FROM effective_at) / 300) * 300) AS bucket,
                       CASE WHEN state_bits & 1 = 0 THEN 'hidden_playback'
                            WHEN state_bits & 6 = 6 THEN 'interactive'
                            WHEN state_bits & 8 = 8 THEN 'media'
                            ELSE 'interactive' END AS kind
                FROM activity_heartbeats
                WHERE user_id = :u AND kind = 'engaged' AND effective_at >= :a AND effective_at < :b
                  AND privacy_tier = 'adult'
                GROUP BY 1, 2, 3, 4 ORDER BY 3, 1
                """
            ),
            {"u": user_id, "a": from_ts.astimezone(UTC), "b": to_ts.astimezone(UTC)},
        )
    ).all()
    return [EngagedBucket(r[0], r[1], r[2], r[3]) for r in rows]


# --------------------------------------------------------------------------- H11 learning activity


@dataclass(frozen=True)
class LearningActivityBucket:
    """One day/week/month of learning activity (ADM-04, H11). ``suppressed`` buckets hide
    every count (kept for compatibility; platform-wide buckets are never suppressed)."""

    period_start: date
    active_learners: int | None
    engaged_minutes: int | None
    learning_minutes: int | None
    suppressed: bool


_GRANULARITY = {"day": "day", "week": "week", "month": "month"}


async def get_learning_activity(
    session: AsyncSession,
    from_date: date,
    to_date: date,
    *,
    granularity: str = "day",
    k_min: int | None = None,
) -> list[LearningActivityBucket]:
    """DAU/WAU/MAU-style active learners plus engaged (M2) and learning (M5) minutes per
    IST day / ISO week / month, platform-wide (single company: there are no per-organization
    views). Synthetic users are excluded. An active learner had M2 > 0 in the bucket.
    ``k_min`` is accepted for callers; platform-wide buckets are not suppressed."""
    del k_min
    trunc = _GRANULARITY.get(granularity)
    if trunc is None:
        raise ValueError(f"granularity must be one of {sorted(_GRANULARITY)}")
    await system_context(session, "analytics.feed_read")
    rows = (
        await session.execute(
            text(
                f"""
                SELECT date_trunc('{trunc}', d.activity_date)::date AS p,
                       count(DISTINCT d.user_id) FILTER (WHERE d.m2_active_s > 0) AS learners,
                       coalesce(sum(d.m2_active_s), 0) AS m2, coalesce(sum(d.m5_learning_s), 0) AS m5
                FROM daily_learning_aggregates d JOIN users u ON u.id = d.user_id AND NOT u.is_synthetic
                WHERE d.entity_kind = '_total' AND d.activity_date BETWEEN :a AND :b
                GROUP BY 1 ORDER BY 1
                """  # noqa: S608 - trunc is a module constant
            ),
            {"a": from_date, "b": to_date},
        )
    ).all()
    out: list[LearningActivityBucket] = []
    for p, learners, m2, m5 in rows:
        out.append(
            LearningActivityBucket(
                period_start=p,
                active_learners=int(learners),
                engaged_minutes=int(m2) // 60,
                learning_minutes=int(m5) // 60,
                suppressed=False,
            )
        )
    return out
