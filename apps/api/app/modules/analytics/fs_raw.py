"""Firestore data access of the analytics ingest path and its jobs (``TD_STORE_ANALYTICS=firestore``;
data-analytics agent, docs/firebase/agents/data-analytics.md).

**Raw events are batch documents** (cost-safe): one ``analytics_batches/{id}`` document per ingest
batch (client batch, or one server event) holds its heartbeat and event rows (``rows`` encoded
exactly like the 1:1 backfill documents, ``store_specs.HeartbeatRow`` / ``EventRow``) plus index
arrays so every reader is bounded: ``event_ids`` (dedupe), ``page_instance_ids``, ``days`` (IST
dates touched), ``session_ids``, ``asset_ids``; ``received_at`` (interval-builder watermark) and a
TTL ``expire_at`` (received + 90 days = the ``analytics_events`` retention; heartbeats older than
35 days are dropped by the readers, as the Postgres retention purge drops them).

Postgres dedupes on ``(event_id, event_ts)`` (``event_ts`` is derived from the uuid7 id, so the id
alone decides): here ``insert_batch`` reads the user's batches that already hold any of the ids
(``array-contains-any``, 30 per query) and stores only new rows.

Readers return ``FsRow`` objects with the **same attribute names as the SQL rows** the jobs read,
so ``timemodel`` / aggregation code runs unchanged on either store. Derived/rollup tables keep
the 1:1 documents of ``store_specs`` (intervals, daily aggregates, dirty days, rejections, job
state).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.firestore.ids import compose_id
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.core.time import ist_date, utcnow
from app.modules.admin.fs_rows import model_doc_id
from app.modules.analytics import models as m
from app.modules.analytics.store_specs import (
    BATCH_RETENTION,
    BATCHES,
    PAGE_HEARTBEATS,
    DailyRow,
    DirtyDayRow,
    EventRow,
    HeartbeatRow,
    IntervalRow,
    JobStateRow,
    RejectionRow,
    batch_doc,
    ranges_in,
)

HEARTBEAT_RETENTION = timedelta(days=35)
JOB = "analytics.fs"
_PAGE = 300
_IN = 30


INTERVALS = "engagement_intervals"
DAILY = "daily_learning_aggregates"
DIRTY = "analytics_dirty_days"
REJECTIONS = "analytics_ingest_rejections"
JOB_STATE = "analytics_job_state"

_interval_id = model_doc_id(m.EngagementInterval)
_daily_id = model_doc_id(m.DailyLearningAggregate)
_dirty_id = model_doc_id(m.AnalyticsDirtyDay)
_rejection_id = model_doc_id(m.AnalyticsIngestRejection)


def store() -> ScopedStore:
    return ScopedStore.system(JOB)


async def all_docs(coll: str, **kw: Any) -> list[Doc]:
    st = store()
    out: list[Doc] = []
    cursor: str | None = None
    kw.setdefault("order_by", ())
    while True:
        page = await st.query(coll, limit=_PAGE, cursor=cursor, **kw)
        out += page.items
        if not page.next_cursor:
            return out
        cursor = page.next_cursor


def _chunks(vals: Sequence[Any], n: int = _IN) -> Iterable[list[Any]]:
    for i in range(0, len(vals), n):
        yield list(vals[i : i + n])


def ist_days(lo: datetime, hi: datetime) -> list[str]:
    """IST dates (ISO) of every instant in ``[lo, hi)``."""
    d, last = ist_date(lo), ist_date(hi - timedelta(microseconds=1))
    out = []
    while d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# =========================================================================== raw batches


def _hex(v: Any) -> str:
    return (v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))).hex


async def existing_event_ids(user_id: uuid.UUID, ids: Iterable[Any]) -> set[str]:
    want = sorted({_hex(i) for i in ids})
    found: set[str] = set()
    for chunk in _chunks(want):
        for d in await all_docs(
            BATCHES, user_id=user_id, filters=[("event_ids", "array-contains-any", chunk)]
        ):
            found |= set(d.get("event_ids") or ()) & set(chunk)
    return found


async def insert_batch(
    user_id: uuid.UUID,
    received_at: datetime,
    heartbeats: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    doc_id: str | None = None,
) -> set[str]:
    """Store the rows whose event id is new (``ON CONFLICT DO NOTHING``); returns their hex ids."""
    known = await existing_event_ids(user_id, [r["event_id"] for r in [*heartbeats, *events]])
    hb = [r for r in heartbeats if _hex(r["event_id"]) not in known]
    ev = [r for r in events if _hex(r["event_id"]) not in known]
    if not hb and not ev:
        return set()
    doc = batch_doc(user_id, received_at, hb, ev)
    ids = doc["event_ids"]
    bid = doc_id or str(uuid7())
    by_page: dict[str, list[str]] = {}
    for r in hb:
        if r.get("page_instance_id"):
            by_page.setdefault(str(r["page_instance_id"]), []).append(_page_hb_entry(r))
    if not by_page:
        await store().create(BATCHES, doc, doc_id=bid)
        return set(ids)

    async def body(tx: ScopedTransaction) -> None:
        # The page summaries change with the batch (one commit): a reader sees both or neither.
        current = {p: await tx.raw_get(PAGE_HEARTBEATS, page_hb_id(user_id, p)) for p in by_page}
        await tx.create(BATCHES, doc, doc_id=bid)
        for p, entries in by_page.items():
            _stage_page_summary(tx, user_id, p, current[p], entries, received_at)

    await store().run_transaction(body)
    return set(ids)


# =========================================================================== page heartbeat summaries
#
# Ingest needs, per page instance, the already-stored heartbeats' ``effective_at`` / ``kind`` /
# ``event_id`` (rate cap of engaged samples, BE-01 ``credit_wall_s``). Reading every batch of the
# page made each ingest cost one read per earlier batch (~120 batches in a viewing hour: ~7,000
# reads per hour of video). ``analytics_page_heartbeats/{user}:{page}`` keeps exactly those fields
# for the page (plus ``received_at`` for the 35-day reader cut). A page without a summary (stored
# before summaries existed) or whose summary would pass ``PAGE_HB_CAP`` entries (document size) is
# read from the batches as before.

PAGE_HB_CAP = 6000


@dataclass(frozen=True, slots=True)
class StoredHeartbeat:
    """The fields of a stored heartbeat that ingest reads (same names as ``HeartbeatRow``)."""

    event_id: uuid.UUID
    kind: str
    effective_at: datetime
    received_at: datetime | None


def page_hb_id(user_id: Any, page_id: Any) -> str:
    return compose_id(str(user_id), str(page_id))


def _iso(v: datetime) -> str:
    return v.astimezone(UTC).isoformat()


def _page_hb_entry(r: dict[str, Any]) -> str:
    rec = r.get("received_at")
    return "|".join((_iso(r["effective_at"]), str(r["kind"]), _hex(r["event_id"]), _iso(rec) if rec else ""))


def _page_hb_of(entry: str) -> StoredHeartbeat:
    eff, kind, eid, rec = entry.split("|")
    return StoredHeartbeat(
        uuid.UUID(eid), kind, datetime.fromisoformat(eff), datetime.fromisoformat(rec) if rec else None
    )


def _stage_page_summary(
    tx: ScopedTransaction,
    user_id: Any,
    page_id: str,
    current: dict[str, Any] | None,
    entries: list[str],
    received_at: datetime,
) -> None:
    if current is not None and current.get("overflow"):
        return
    have = list((current or {}).get("hbs") or [])
    seen = set(have)
    merged = have + [e for e in entries if e not in seen]
    now = utcnow()
    base = {
        "user_id": str(user_id),
        "page_instance_id": page_id,
        "created_at": (current or {}).get("created_at") or now,
        "updated_at": now,
        "expire_at": max(received_at + BATCH_RETENTION, (current or {}).get("expire_at") or now),
    }
    if len(merged) > PAGE_HB_CAP:  # too big for one document: readers scan the batches again
        tx.raw_set(PAGE_HEARTBEATS, page_hb_id(user_id, page_id), {**base, "overflow": True, "hbs": []})
        return
    tx.raw_set(PAGE_HEARTBEATS, page_hb_id(user_id, page_id), {**base, "overflow": False, "hbs": merged})


async def page_heartbeats(user_id: uuid.UUID, page_id: uuid.UUID) -> list[Any]:
    """The page instance's stored heartbeats (``rows_for_page(...)[0]`` for the fields ingest
    reads): from its summary document when it has a usable one, else from the batches."""
    d = await store().get(PAGE_HEARTBEATS, page_hb_id(user_id, page_id))
    if d is not None and not d.get("overflow"):
        cut = utcnow() - HEARTBEAT_RETENTION
        rows = [_page_hb_of(x) for x in d.get("hbs") or ()]
        return [h for h in rows if h.received_at is None or h.received_at >= cut]
    hbs = (await rows_for_page(user_id, page_id))[0]
    if d is None and hbs:
        # A page stored before the summaries existed: seed its summary once, so the next batch of
        # the page reads one document (union with whatever a concurrent ingest wrote meanwhile).
        entries = [
            _page_hb_entry(
                {
                    "effective_at": h.effective_at,
                    "kind": h.kind,
                    "event_id": h.event_id,
                    "received_at": h.received_at,
                }
            )
            for h in hbs
        ]
        newest = max((h.received_at for h in hbs if h.received_at is not None), default=utcnow())

        async def body(tx: ScopedTransaction) -> None:
            cur = await tx.raw_get(PAGE_HEARTBEATS, page_hb_id(user_id, page_id))
            _stage_page_summary(tx, user_id, str(page_id), cur, entries, newest)

        await store().run_transaction(body)
    return hbs


def _rows(docs: Iterable[Doc], *, now: datetime | None = None) -> tuple[list[Any], list[Any]]:
    """Heartbeat / event rows of batch documents (heartbeats past their 35-day retention dropped)."""
    hb_cut = (now or utcnow()) - HEARTBEAT_RETENTION
    hbs: list[Any] = []
    evs: list[Any] = []
    seen: set[str] = set()
    for d in docs:
        if d.id in seen:
            continue
        seen.add(d.id)
        for x in d.get("heartbeats") or ():
            h = HeartbeatRow.of(x)
            h.played_ranges = ranges_in(x.get("played_ranges"))
            if h.received_at is None or h.received_at >= hb_cut:
                hbs.append(h)
        evs += [EventRow.of(x) for x in d.get("events") or ()]
    return hbs, evs


async def batches_for_page(user_id: uuid.UUID, page_id: uuid.UUID) -> list[Doc]:
    return await all_docs(
        BATCHES, user_id=user_id, filters=[("page_instance_ids", "array-contains", str(page_id))]
    )


async def rows_for_page(user_id: uuid.UUID, page_id: uuid.UUID) -> tuple[list[Any], list[Any]]:
    hbs, evs = _rows(await batches_for_page(user_id, page_id))
    pid = page_id
    return [h for h in hbs if h.page_instance_id == pid], [e for e in evs if e.page_instance_id == pid]


async def rows_for_window(user_id: uuid.UUID, lo: datetime, hi: datetime) -> tuple[list[Any], list[Any]]:
    """Rows of ``user_id`` with ``effective_at`` in ``[lo, hi)``."""
    docs: list[Doc] = []
    for chunk in _chunks(ist_days(lo, hi)):
        docs += await all_docs(BATCHES, user_id=user_id, filters=[("days", "array-contains-any", chunk)])
    hbs, evs = _rows(docs)
    return (
        [h for h in hbs if lo <= h.effective_at < hi],
        [e for e in evs if lo <= e.effective_at < hi],
    )


async def rows_for_sessions(user_id: uuid.UUID, session_ids: Iterable[uuid.UUID]) -> list[Any]:
    """Event rows of ``user_id`` on any of these auth sessions."""
    want = sorted({str(s) for s in session_ids})
    docs: list[Doc] = []
    for chunk in _chunks(want):
        docs += await all_docs(
            BATCHES, user_id=user_id, filters=[("session_ids", "array-contains-any", chunk)]
        )
    return _rows(docs)[1]


async def rows_received_after(since: datetime) -> tuple[list[Any], list[Any]]:
    """Every user's rows of batches received after ``since`` (interval-builder discovery)."""
    return _rows(
        await all_docs(BATCHES, filters=[("received_at", ">", since)], order_by=(("received_at", "asc"),))
    )


async def rows_for_days(day_isos: Sequence[str]) -> tuple[list[Any], list[Any]]:
    """Every user's rows of batches touching these IST days."""
    docs: list[Doc] = []
    for chunk in _chunks(list(day_isos)):
        docs += await all_docs(BATCHES, filters=[("days", "array-contains-any", chunk)])
    return _rows(docs)


# =========================================================================== intervals


async def intervals(
    *,
    user_id: uuid.UUID | None = None,
    page_id: uuid.UUID | None = None,
    is_open: bool | None = None,
    started_from: datetime | None = None,
    started_before: datetime | None = None,
) -> list[Any]:
    f: list[Any] = []
    if page_id is not None:
        f.append(("page_instance_id", "==", str(page_id)))
    if is_open is not None:
        f.append(("is_open", "==", is_open))
    if started_from is not None:
        f.append(("started_at", ">=", started_from))
    if started_before is not None:
        f.append(("started_at", "<", started_before))
    order = (("started_at", "asc"),) if started_from is not None or started_before is not None else ()
    docs = await all_docs(INTERVALS, user_id=user_id, filters=f, order_by=order)
    return [IntervalRow.of(d) for d in docs]


async def replace_page_intervals(user_id: uuid.UUID, page_id: uuid.UUID, rows: list[dict[str, Any]]) -> None:
    """``DELETE ... WHERE page_instance_id AND user_id`` + ``INSERT`` of ``rows``, in chunked
    transactions (a page instance has a handful of intervals)."""
    old = await intervals(user_id=user_id, page_id=page_id)
    st = store()
    new_docs = [(_interval_id(r), IntervalRow.from_pg(r).doc()) for r in rows]
    ops: list[tuple[str, str, dict[str, Any] | None]] = [
        ("del", _interval_id(o.__dict__), None) for o in old
    ] + [("put", i, d) for i, d in new_docs]
    for chunk in _chunks(ops, 300):

        async def body(tx: ScopedTransaction, chunk: list[Any] = chunk) -> None:
            for op, did, data in chunk:
                if op == "del":
                    tx.raw_delete(INTERVALS, did)
                else:
                    tx.raw_set(INTERVALS, did, {**(data or {}), "updated_at": utcnow()})

        await st.run_transaction(body)


# =========================================================================== daily aggregates / dirty days


async def daily_rows(user_id: uuid.UUID, day: date) -> list[Any]:
    docs = await all_docs(DAILY, user_id=user_id, filters=[("activity_date", "==", day.isoformat())])
    return [DailyRow.of(d) for d in docs]


async def replace_daily(user_id: uuid.UUID, day: date, rows: list[dict[str, Any]]) -> None:
    """``DELETE`` the user-day's aggregates, ``INSERT`` ``rows`` and clear the dirty mark, in one
    transaction (a user-day has one row per entity touched: well under the 400-write cap)."""
    old = await daily_rows(user_id, day)
    st = store()
    now = utcnow()

    async def body(tx: ScopedTransaction) -> None:
        for o in old:
            tx.raw_delete(DAILY, _daily_id(o.__dict__))
        for r in rows:
            tx.raw_set(
                DAILY, _daily_id(r), {**DailyRow.from_pg({**r, "computed_at": now}).doc(), "updated_at": now}
            )
        tx.raw_delete(DIRTY, _dirty_id({"user_id": user_id, "activity_date": day}))

    await st.run_transaction(body)


async def clear_dirty(user_id: uuid.UUID, day: date) -> None:
    did = _dirty_id({"user_id": user_id, "activity_date": day})
    await store().run_transaction(lambda tx: _raw_delete(tx, DIRTY, did))


async def _raw_delete(tx: ScopedTransaction, coll: str, did: str) -> None:
    tx.raw_delete(coll, did)


async def mark_dirty(user_id: uuid.UUID, day: date, reason: str) -> None:
    """``INSERT ... ON CONFLICT (user_id, activity_date) DO UPDATE SET marked_at = now()``: the
    first reason is kept, ``marked_at`` moves."""
    did = _dirty_id({"user_id": user_id, "activity_date": day})

    async def body(tx: ScopedTransaction) -> None:
        cur = await tx.raw_get(DIRTY, did)
        now = utcnow()
        if cur is None:
            row = DirtyDayRow(user_id=user_id, activity_date=day, reason=reason, marked_at=now).doc()
            tx.raw_set(DIRTY, did, {**row, "created_at": now, "updated_at": now})
        else:
            tx.raw_set(DIRTY, did, {**cur, "marked_at": now, "updated_at": now})

    await store().run_transaction(body)


async def dirty_days() -> list[tuple[uuid.UUID, date]]:
    return [(r.user_id, r.activity_date) for r in (DirtyDayRow.of(d) for d in await all_docs(DIRTY))]


async def add_rejections(hour: datetime, counts: dict[tuple[str, str], int]) -> None:
    """``INSERT ... ON CONFLICT (hour_start, code, event_type) DO UPDATE SET count = count + n``."""

    async def body(tx: ScopedTransaction) -> None:
        cur = {}
        for code, et in counts:
            did = _rejection_id({"hour_start": hour, "code": code, "event_type": et})
            cur[did] = await tx.raw_get(REJECTIONS, did)
        now = utcnow()
        for (code, et), n in counts.items():
            did = _rejection_id({"hour_start": hour, "code": code, "event_type": et})
            prev = cur[did]
            total = int((prev or {}).get("count") or 0) + n
            row = RejectionRow(hour_start=hour, code=code, event_type=et, count=total).doc()
            tx.raw_set(REJECTIONS, did, {**row, "updated_at": now})

    await store().run_transaction(body)


# =========================================================================== job state


async def get_watermark(job: str) -> datetime | None:
    d = await store().get(JOB_STATE, job)
    return JobStateRow.of(d).watermark if d else None


async def set_state(job: str, watermark: datetime | None, result: dict[str, Any]) -> None:
    """``ON CONFLICT (job) DO UPDATE``: the watermark is kept when the new one is ``NULL``."""

    async def body(tx: ScopedTransaction) -> None:
        cur = await tx.raw_get(JOB_STATE, job)
        prev = JobStateRow.of(cur).watermark if cur else None
        now = utcnow()
        row = JobStateRow(job=job, watermark=watermark or prev, last_run_at=now, last_result=result).doc()
        tx.raw_set(JOB_STATE, job, {**row, "updated_at": now})

    await store().run_transaction(body)


async def record_idle_run(job: str, result: dict[str, Any]) -> None:
    """What ``set_state(job, None, result)`` leaves behind after an idle run (watermark kept,
    ``last_run_at``/``last_result`` refreshed), as one blind update: no read. Used by the Firebase
    dispatcher when it skips a provably idle run (app.core.scheduler). Raises when the state
    document does not exist yet (the dispatcher then runs the job for real)."""
    from app.core.firestore.codec import to_store
    from app.core.firestore.collections import physical_name

    now = utcnow()
    row = JobStateRow(job=job, watermark=None, last_run_at=now, last_result=result).doc()
    changes = {k: row[k] for k in ("last_run_at", "last_result", "last_duration_ms") if k in row}
    doc = store().client.collection(physical_name(JOB_STATE)).document(job)
    await doc.update(to_store({**changes, "updated_at": now}))


def interval_doc_id(row: dict[str, Any]) -> str:
    return _interval_id(row)


def daily_doc_id(row: dict[str, Any]) -> str:
    return _daily_id(row)


__all__ = ["compose_id"]


# =========================================================================== consumer / mastery

CONSUMED = "analytics_consumed_events"
TOPIC_MASTERY = "topic_mastery"
QUESTION_STATS = "question_item_stats"
SECURITY_FEED = "security_activity_feed_daily"


async def is_consumed(event_id: uuid.UUID) -> bool:
    return await store().get(CONSUMED, str(event_id)) is not None


async def mark_consumed(event_id: uuid.UUID, event_type: str) -> None:
    """``INSERT INTO analytics_consumed_events ... ON CONFLICT DO NOTHING``."""
    from app.modules.analytics.store_specs import ConsumedRow

    did = str(event_id)

    async def body(tx: ScopedTransaction) -> None:
        if await tx.raw_get(CONSUMED, did) is None:
            now = utcnow()
            row = ConsumedRow(outbox_event_id=event_id, event_type=event_type, consumed_at=now).doc()
            tx.raw_set(CONSUMED, did, {**row, "created_at": now, "updated_at": now})

    await store().run_transaction(body)


async def item_difficulty(question_version_id: uuid.UUID) -> float | None:
    from app.modules.analytics.store_specs import QuestionStatsRow

    d = await store().get(QUESTION_STATS, str(question_version_id))
    v = QuestionStatsRow.of(d).difficulty_b if d else None
    return float(v) if v is not None else None


async def upsert_mastery(
    user_id: uuid.UUID, topic_id: uuid.UUID, organization_id: uuid.UUID | None, update: Any
) -> None:
    """``SELECT ... FOR UPDATE`` + ``INSERT ... ON CONFLICT DO UPDATE`` of one ``topic_mastery``
    row in one transaction: ``update(current_row_or_None) -> new column values``."""
    from app.modules.analytics.store_specs import TopicRow

    did = compose_id(str(user_id), str(topic_id))

    async def body(tx: ScopedTransaction) -> None:
        cur = await tx.raw_get(TOPIC_MASTERY, did)
        row = TopicRow.of(cur) if cur else None
        vals = update(row)
        now = utcnow()
        org = (row.organization_id if row and row.organization_id else None) or organization_id
        merged = {
            **(row.doc() if row else {}),
            **TopicRow.from_pg(
                {**vals, "user_id": user_id, "topic_id": topic_id, "organization_id": org, "updated_at": now}
            ).doc(),
        }
        tx.raw_set(TOPIC_MASTERY, did, merged)

    await store().run_transaction(body)


async def delete_user_docs(coll: str, user_id: uuid.UUID) -> int:
    """Delete every document of ``coll`` owned by ``user_id`` (chunked transactions)."""
    docs = await all_docs(coll, user_id=user_id)
    for chunk in _chunks([d.id for d in docs], 300):

        async def body(tx: ScopedTransaction, chunk: list[str] = chunk) -> None:
            for did in chunk:
                tx.raw_delete(coll, did)

        await store().run_transaction(body)
    return len(docs)
