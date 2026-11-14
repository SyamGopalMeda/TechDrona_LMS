"""Firestore data model of the analytics module (data-ops agent; docs/firebase/agents/data-ops.md).

Raw ``analytics_events`` / ``activity_heartbeats`` rows are stored in ``analytics_batches``
documents (one per ingest batch; ``batch_doc``; data-analytics agent). Every other table maps
1:1 to a collection with
the Postgres primary key as document id (composite keys -> ``compose_id``; dates as ISO text),
so the precomputed rollups that the reports read (MIGRATION-PLAN §1.7) keep their keys:
``daily_learning_aggregates/{user}:{day}:{kind}:{entity|-}``, ``topic_mastery/{user}:{topic}``...

Cost / volume (Spark: 20k writes/day; Blaze: per-op billing):

* ``analytics_events``, ``activity_heartbeats``, ``engagement_intervals`` are high-volume time
  series (partitioned in Postgres). 1:1 documents are kept for the **backfill/verify** of the
  demo data only. The repository phase must write one ``analytics_event_batches/{id}`` document
  per ingest batch (plan §3.1) and fold heartbeats/intervals into it, with a TTL ``expire_at``;
  otherwise every heartbeat costs one write.
* ``analytics_consumed_events`` becomes a ``consumed`` flag on the batch document then.
* Rollups (daily/weekly/cohort/route/topic/video/question stats, security feed) are written by the
  nightly/dirty-day jobs: writes scale with active users per day, not with events.
* ``route_daily_aggregates.unique_users_hll`` (bytea) is stored as hex text.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from app.core.firestore.backfill import TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id
from app.core.time import ist_date
from app.modules.admin.fs_rows import model_row, register_model
from app.modules.analytics import models as m

M = "analytics"
READ = "analytics.read"


def _owned(name: str, *, append_only: bool = False) -> CollectionSpec:
    return CollectionSpec(name, "owned", owner_writes=False, read_permission=READ, append_only=append_only)


def _shared(name: str, read: str = READ) -> CollectionSpec:
    return CollectionSpec(name, "shared", read_permission=read)


def _system(name: str) -> CollectionSpec:
    return CollectionSpec(name, "system")


# Raw time series (data-analytics agent): no 1:1 collections. ``analytics_events`` and
# ``activity_heartbeats`` rows live inside ``analytics_batches`` documents (see ``batch_doc``); the
# row classes encode them exactly like a 1:1 document would.
EventRow = model_row(m.AnalyticsEvent)
HeartbeatRow = model_row(m.ActivityHeartbeat)
BATCHES = "analytics_batches"
BATCH_RETENTION = timedelta(days=90)  # = the analytics_events retention (TTL ``expire_at``)
register_collection(
    CollectionSpec(BATCHES, "owned", owner_writes=False, read_permission=READ, ttl=BATCH_RETENTION)
)
# cost-media (docs/firebase/agents/cost-media.md): per page instance, the stored heartbeats'
# ``effective_at|kind|event_id|received_at`` (``analytics_page_heartbeats/{user}:{page}``), written
# in the same transaction as each batch. Ingest reads this one document instead of every batch of
# the page (which grew with the page's age: O(n^2) reads per viewing). Same TTL as the batches.
PAGE_HEARTBEATS = "analytics_page_heartbeats"
register_collection(
    CollectionSpec(PAGE_HEARTBEATS, "owned", owner_writes=False, read_permission=READ, ttl=BATCH_RETENTION)
)


def _hex(v: Any) -> str:
    return (v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))).hex


def ranges_out(v: Any) -> Any:
    """``int4range[]`` -> list of maps ``{l, u, b}`` (Firestore has no ranges or nested arrays)."""
    if v is None:
        return None
    return [{"l": r.lower, "u": r.upper, "b": r.bounds, "e": bool(r.empty)} for r in v]


def ranges_in(v: Any) -> Any:
    from sqlalchemy.dialects.postgresql import Range

    if v is None:
        return None
    return [Range(x["l"], x["u"], bounds=x["b"], empty=x["e"]) for x in v]


def _hb_doc(r: dict[str, Any]) -> dict[str, Any]:
    d = HeartbeatRow.from_pg(r).doc()
    d["played_ranges"] = ranges_out(r.get("played_ranges"))
    return d


def batch_doc(
    user_id: Any, received_at: datetime, heartbeats: list[dict[str, Any]], events: list[dict[str, Any]]
) -> dict[str, Any]:
    """One ingest batch as stored: the rows plus the index arrays every reader filters on."""
    rows = [*heartbeats, *events]
    return {
        "user_id": str(user_id),
        "received_at": received_at,
        "event_ids": [_hex(r["event_id"]) for r in rows],
        "page_instance_ids": sorted({str(r["page_instance_id"]) for r in rows if r.get("page_instance_id")}),
        "days": sorted({ist_date(r["effective_at"]).isoformat() for r in rows}),
        "session_ids": sorted({str(r["auth_session_id"]) for r in rows if r.get("auth_session_id")}),
        "asset_ids": sorted({str(r["lesson_asset_id"]) for r in rows if r.get("lesson_asset_id")}),
        "event_types": sorted({str(r["event_type"]) for r in events}),
        "heartbeats": [_hb_doc(r) for r in heartbeats],
        "events": [EventRow.from_pg(r).doc() for r in events],
        "expire_at": received_at + BATCH_RETENTION,
    }


async def load_batches(session: Any) -> list[dict[str, Any]]:
    """Backfill: the Postgres raw rows grouped into one batch per user x IST receive day (the
    original client batches are not recorded in Postgres; any grouping serves the readers)."""
    from sqlalchemy import text

    groups: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}
    for table, kind in (("activity_heartbeats", "hb"), ("analytics_events", "ev")):
        res = await session.execute(text(f"SELECT * FROM {table} ORDER BY event_ts, event_id"))  # noqa: S608
        for r in res.mappings().all():
            key = (str(r["user_id"]), ist_date(r["received_at"]).isoformat())
            groups.setdefault(key, {"hb": [], "ev": []})[kind].append(dict(r))
    out = []
    for (uid, day), g in sorted(groups.items()):
        rows = [*g["hb"], *g["ev"]]
        received = max(r["received_at"] for r in rows)
        out.append({"_id": compose_id("bf", uid, day), **batch_doc(uid, received, g["hb"], g["ev"])})
    return out


register_mapping(
    TableMapping(
        M,
        "analytics_events",
        BATCHES,
        lambda r: r["_id"],
        lambda r: {k: v for k, v in r.items() if k != "_id"},
        loader=load_batches,
    )
)
IntervalRow = register_model(M, m.EngagementInterval, _owned("engagement_intervals"))
DailyRow = register_model(M, m.DailyLearningAggregate, _owned("daily_learning_aggregates"))
WeeklyRow = register_model(M, m.WeeklyLearningAggregate, _owned("weekly_learning_aggregates"))
CohortRow = register_model(M, m.CohortLearningAggregate, _shared("cohort_learning_aggregates"))
RouteRow = register_model(
    M, m.RouteDailyAggregate, _shared("route_daily_aggregates", "analytics.read.platform")
)
VideoRow = register_model(M, m.VideoWatchCoverage, _owned("video_watch_coverage"))
TopicRow = register_model(M, m.TopicMastery, _owned("topic_mastery"))
QuestionStatsRow = register_model(M, m.QuestionItemStats, _shared("question_item_stats"))
SecurityFeedRow = register_model(
    M,
    m.SecurityActivityFeedDaily,
    CollectionSpec(
        "security_activity_feed_daily", "owned", owner_writes=False, read_permission="security.evidence.read"
    ),
)
DirtyDayRow = register_model(M, m.AnalyticsDirtyDay, _system("analytics_dirty_days"))
RejectionRow = register_model(M, m.AnalyticsIngestRejection, _system("analytics_ingest_rejections"))
JobStateRow = register_model(M, m.AnalyticsJobState, _system("analytics_job_state"))
ConsumedRow = register_model(M, m.AnalyticsConsumedEvent, _system("analytics_consumed_events"))
# ``export_jobs`` is plain CRUD written with SQLAlchemy Core: it runs on the shared SQL-on-Firestore
# engine (``app/core/firestore/sqlstore.py``) through ``analytics/datastore.py``, so the exports code
# keeps its statements. RLS: requester or platform (``owner`` on ``requested_by``); the Postgres
# policy's "same organization" clause has no engine family (exports are read by the requester or a
# platform approver).
from app.core.firestore.sqlstore import SqlModuleSpec, SqlStore  # noqa: E402

EXPORT_SPEC = SqlModuleSpec(
    module=M,
    models=(m.ExportJob,),
    rls={"export_jobs": "owner"},
    owner_field={"export_jobs": "requested_by"},
    updated_at_trigger=frozenset({"export_jobs"}),
    job="analytics.exports",
)
EXPORT_STORE = SqlStore(EXPORT_SPEC)
EXPORT_STORE.register_backfill()
