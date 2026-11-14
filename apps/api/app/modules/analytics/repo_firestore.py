"""Firestore repository of the analytics module (``TD_STORE_ANALYTICS=firestore``) -- slice 1:
the **read interfaces other modules call** (data-ops agent):

* ``topic_mastery`` for placement / mentoring (``mastery.get_topic_mastery``);
* the security feeds (``feeds.get_activity_summary`` / ``get_engaged_buckets``) and the H11
  learning-activity series (``feeds.get_learning_activity``).

They read the rollup collections (``store_specs``: one document per Postgres row, same keys), so
every call is bounded by the window asked for, never by raw event volume -- except
``engaged_buckets``, which reads the heartbeat documents of one user in a <= 35-day window.

Cost note: raw heartbeats/events are high volume. The ingest path (not ported yet) must write
one ``analytics_event_batches`` document per client batch and maintain per-user-day rollups
(``engaged_buckets`` included) in the same write, so these readers never scan raw events.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, ScopedStore

_PAGE = 100
PERM = "analytics.read"


async def _all(store: ScopedStore, coll: str, **kw: Any) -> list[Doc]:
    out: list[Doc] = []
    cursor: str | None = None
    while True:
        page = await store.query(coll, limit=_PAGE, cursor=cursor, **kw)
        out += page.items
        if not page.next_cursor:
            return out
        cursor = page.next_cursor


class AnalyticsReadRepo(FirestoreRepository):
    async def topic_mastery(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        docs = await _all(self.store, "topic_mastery", user_id=user_id, order_by=(("topic_id", "asc"),))
        return [d.data for d in docs]

    async def security_feed_days(
        self, user_id: uuid.UUID, from_date: date, to_date: date
    ) -> list[dict[str, Any]]:
        docs = await _all(
            self.store,
            "security_activity_feed_daily",
            user_id=user_id,
            filters=(
                ("activity_date", ">=", from_date.isoformat()),
                ("activity_date", "<=", to_date.isoformat()),
            ),
            order_by=(("activity_date", "asc"),),
        )
        return [d.data for d in docs]

    @platform_only(PERM)
    async def daily_totals(self, from_date: date, to_date: date) -> list[dict[str, Any]]:
        docs = await _all(
            self.store,
            "daily_learning_aggregates",
            filters=(
                ("entity_kind", "==", "_total"),
                ("activity_date", ">=", from_date.isoformat()),
                ("activity_date", "<=", to_date.isoformat()),
            ),
            order_by=(("activity_date", "asc"),),
        )
        return [d.data for d in docs]


def feed_repo(job: str = "analytics.feed_read") -> AnalyticsReadRepo:
    return AnalyticsReadRepo(ScopedStore.system(job))
