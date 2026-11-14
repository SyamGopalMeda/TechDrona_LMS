"""Firestore side of the analytics rollup / coverage / feed / retention / erasure jobs
(``TD_STORE_ANALYTICS=firestore``; data-analytics agent, docs/firebase/agents/data-analytics.md).

Each function is the Firestore equivalent of one SQL statement (or GROUP BY) in ``jobs.py``: the
same rows, the same aggregate semantics (Postgres ``sum`` / ``count FILTER`` / ``bool_or`` /
``max(uuid::text)`` with NULLs ignored), keyed by the same primary keys. The surrounding Python in
``jobs.py`` (percentiles, range merging, coverage, the time model) is shared by both stores.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from app.core.firestore.store import ScopedTransaction, chunks
from app.core.time import utcnow
from app.modules.admin.fs_rows import model_doc_id
from app.modules.analytics import fs_raw
from app.modules.analytics import models as m
from app.modules.analytics.store_specs import (
    CohortRow,
    DailyRow,
    SecurityFeedRow,
    VideoRow,
    WeeklyRow,
)

WEEKLY = "weekly_learning_aggregates"
COHORT = "cohort_learning_aggregates"
VIDEO = "video_watch_coverage"
FEED = "security_activity_feed_daily"

_weekly_id = model_doc_id(m.WeeklyLearningAggregate)
_video_id = model_doc_id(m.VideoWatchCoverage)
_feed_id = model_doc_id(m.SecurityActivityFeedDaily)


# --------------------------------------------------------------------------- shared helpers


async def real_users(session: Any, ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Existing, non-synthetic users among ``ids`` (identity.public)."""
    from app.modules.identity import public as idp

    want = list(dict.fromkeys(ids))
    if not want:
        return set()
    return {u for u, x in (await idp.get_users(session, want)).items() if not x.is_synthetic}


async def daily_between(lo: date, hi: date, *, kind: str | None = None) -> list[Any]:
    """``daily_learning_aggregates`` rows with ``activity_date BETWEEN lo AND hi`` (ISO strings
    order like dates)."""
    f: list[Any] = [("activity_date", ">=", lo.isoformat()), ("activity_date", "<=", hi.isoformat())]
    if kind is not None:
        f.append(("entity_kind", "==", kind))
    docs = await fs_raw.all_docs(fs_raw.DAILY, filters=f, order_by=(("activity_date", "asc"),))
    return [DailyRow.of(d) for d in docs]


def _max_text_uuid(vals: Iterable[Any]) -> uuid.UUID | None:
    """``max(col::text)::uuid`` (NULLs ignored, text comparison)."""
    from app.core.firestore.collation import sort_key

    s = [str(v) for v in vals if v is not None]
    return uuid.UUID(max(s, key=sort_key)) if s else None


async def _replace(coll: str, old_ids: list[str], new: list[tuple[str, dict[str, Any]]]) -> None:
    ops: list[tuple[str, dict[str, Any] | None]] = [(i, None) for i in old_ids] + list(new)
    for i in range(0, len(ops), 300):
        chunk = ops[i : i + 300]

        async def body(tx: ScopedTransaction, chunk: list[Any] = chunk) -> None:
            now = utcnow()
            for did, data in chunk:
                if data is None:
                    tx.raw_delete(coll, did)
                else:
                    tx.raw_set(coll, did, {**data, "updated_at": now})

        await fs_raw.store().run_transaction(body)


# --------------------------------------------------------------------------- weekly rollup


async def rollup_week(session: Any, monday: date, sunday: date, mv: str) -> int:
    """``DELETE`` the week + ``INSERT ... SELECT ... GROUP BY user_id, entity_kind, entity_id``."""
    rows = [
        r
        for r in await daily_between(monday, sunday)
        if r.entity_kind in ("_total", "course", "topic") and r.measurement_version == mv
    ]
    real = await real_users(session, {r.user_id for r in rows})
    groups: dict[tuple[uuid.UUID, str, uuid.UUID], list[Any]] = {}
    for r in rows:
        if r.user_id in real:
            groups.setdefault((r.user_id, r.entity_kind, r.entity_id), []).append(r)
    new: list[tuple[str, dict[str, Any]]] = []
    for (uid, kind, eid), g in groups.items():
        row = {
            "user_id": uid,
            "iso_week_start": monday,
            "entity_kind": kind,
            "entity_id": eid,
            "organization_id": _max_text_uuid(x.organization_id for x in g),
            "m2_active_s": sum(x.m2_active_s or 0 for x in g),
            "m3_video_playback_s": sum(x.m3_video_playback_s or 0 for x in g),
            "m4_assessment_s": sum(x.m4_assessment_s or 0 for x in g),
            "m5_learning_s": sum(x.m5_learning_s or 0 for x in g),
            "active_days": sum(1 for x in g if (x.m5_learning_s or 0) >= 600),
            "privacy_tier": "minor" if any(x.privacy_tier == "minor" for x in g) else "adult",
            "measurement_version": mv,
        }
        new.append((_weekly_id(row), WeeklyRow.from_pg(row).doc()))
    old = await fs_raw.all_docs(WEEKLY, filters=[("iso_week_start", "==", monday.isoformat())])
    await _replace(WEEKLY, [d.id for d in old], new)
    return len(new)


# --------------------------------------------------------------------------- cohorts


async def per_user(
    kind: str, entity: uuid.UUID | None, lo: date, hi: date, users: list[uuid.UUID], mv: str
) -> dict[uuid.UUID, dict[str, Any]]:
    want = set(users)
    out: dict[uuid.UUID, dict[str, Any]] = {u: {"m5": 0, "qa": 0, "qc": 0, "lc": 0} for u in users}
    acc: dict[uuid.UUID, list[Any]] = {}
    for r in await daily_between(lo, hi, kind=kind):
        if r.user_id in want and r.measurement_version == mv and (entity is None or r.entity_id == entity):
            acc.setdefault(r.user_id, []).append(r)
    for u, g in acc.items():
        out[u] = {
            "m5": int(sum(x.m5_learning_s or 0 for x in g)),
            "qa": int(sum(x.questions_attempted or 0 for x in g)),
            "qc": int(sum(x.questions_correct or 0 for x in g)),
            "lc": int(sum(x.lessons_completed or 0 for x in g)),
            "implausible": any(bool(x.implausible_day) for x in g),
        }
    return out


async def upsert_cohort(vals: dict[str, Any]) -> None:
    """``ON CONFLICT (organization_id, batch_id, period_kind, period_start, entity_kind, entity_id)
    DO UPDATE``: the existing cell (found by its natural key, whatever its document id) keeps id."""
    key = (
        str(vals["o"]) if vals["o"] else None,
        str(vals["b"]) if vals["b"] else None,
        vals["pk"],
        vals["ps"].isoformat(),
    )
    docs = await fs_raw.all_docs(
        COHORT, filters=[("period_kind", "==", vals["pk"]), ("period_start", "==", vals["ps"].isoformat())]
    )
    cur = next(
        (
            d
            for d in docs
            if (d.get("organization_id"), d.get("batch_id"), d.get("period_kind"), d.get("period_start"))
            == key
            and d.get("entity_kind") == "_total"
            and d.get("entity_id") is None
        ),
        None,
    )
    row = CohortRow.from_pg(
        {
            "id": uuid.UUID(cur.id) if cur else vals["id"],
            "organization_id": vals["o"],
            "batch_id": vals["b"],
            "period_kind": vals["pk"],
            "period_start": vals["ps"],
            "entity_kind": "_total",
            "entity_id": None,
            "learners_enrolled": vals["en"],
            "learners_active": vals["la"],
            "m5_sum_s": vals["sum"],
            "m5_p50_s": vals["p50"],
            "m5_p90_s": vals["p90"],
            "completions": vals["comp"],
            "accuracy": vals["acc"],
            "suppressed": vals["sup"],
            "measurement_version": vals["mv"],
            "computed_at": utcnow(),
        }
    ).doc()
    await _replace(COHORT, [], [(cur.id if cur else str(vals["id"]), row)])


async def batch_cohorts(session: Any) -> list[tuple[Any, Any, list[uuid.UUID]]]:
    """Every batch as ``(id, organization_id, active non-synthetic student ids)`` (orgs, identity)."""
    from app.modules.orgs import public as orgs

    batches = []
    for b in await orgs.list_batches(session, order="id"):
        members = await orgs.batch_members(session, batch_ids=[b.id], member_role="student")
        ids = list(dict.fromkeys(mm.user_id for mm in members))
        real = await real_users(session, ids)
        batches.append((b.id, b.organization_id, [u for u in ids if u in real]))
    return batches


async def cohort_inputs(
    session: Any, start: date, end: date
) -> tuple[list[tuple[Any, Any, list[uuid.UUID]]], list[uuid.UUID]]:
    """(batches as ``(id, org, active non-synthetic student ids)``, platform users with a
    ``_total`` day in the window, non-synthetic)."""
    batches = await batch_cohorts(session)
    days = await daily_between(start, end, kind="_total")
    ids = list(dict.fromkeys(r.user_id for r in days))
    real = await real_users(session, ids)
    return batches, [u for u in ids if u in real]


# --------------------------------------------------------------------------- video coverage


class CoverageInput:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


async def coverage_inputs(since: datetime) -> list[CoverageInput]:
    """The ``GROUP BY user_id, lesson_asset_id`` over heartbeats with played ranges received after
    ``since``: max org / lesson (as text), all ranges, newest receive time, and the media position
    of the latest-effective heartbeat."""
    hbs, _ = await fs_raw.rows_received_after(since)
    groups: dict[tuple[uuid.UUID, uuid.UUID], list[Any]] = {}
    for h in hbs:
        if h.received_at > since and h.lesson_asset_id is not None and h.played_ranges is not None:
            groups.setdefault((h.user_id, h.lesson_asset_id), []).append(h)
    out = []
    for (u, a), g in groups.items():
        ranges = [r for h in g for r in (h.played_ranges or [])]
        if not ranges:  # unnest() of empty arrays yields no row
            continue
        latest = max(g, key=lambda h: h.effective_at)
        out.append(
            CoverageInput(
                user_id=u,
                lesson_asset_id=a,
                org=_max_text_uuid(h.organization_id for h in g),
                lesson=_max_text_uuid(h.lesson_id for h in g),
                ranges=ranges,
                rec=max(h.received_at for h in g),
                pos=latest.media_position_s,
            )
        )
    return out


async def video_ended_durations(asset_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    """``max((payload->>'duration_s')::numeric)`` of ``video.ended`` events per asset."""
    want = {str(a) for a in asset_ids}
    docs: list[Any] = []
    for chunk in chunks(sorted(want)):
        docs += await fs_raw.all_docs(fs_raw.BATCHES, filters=[("asset_ids", "array-contains-any", chunk)])
    out: dict[uuid.UUID, float] = {}
    for e in fs_raw._rows(docs)[1]:
        if e.event_type == "video.ended" and e.lesson_asset_id is not None and str(e.lesson_asset_id) in want:
            v = (e.payload or {}).get("duration_s")
            if v is not None:
                out[e.lesson_asset_id] = max(out.get(e.lesson_asset_id, float("-inf")), float(v))
    return out


async def coverage_existing(user_id: uuid.UUID, asset_id: uuid.UUID) -> list[Any] | None:
    d = await fs_raw.store().get(VIDEO, _video_id({"user_id": user_id, "lesson_asset_id": asset_id}))
    from app.modules.analytics.store_specs import ranges_in

    return ranges_in(d.get("covered_ranges")) if d else None


async def coverage_upsert(vals: dict[str, Any]) -> None:
    """``ON CONFLICT (user_id, lesson_asset_id) DO UPDATE``: ``duration_s`` keeps the old value
    when the new one is NULL, ``lesson_id`` keeps the old one when set."""
    from app.modules.analytics.store_specs import ranges_in, ranges_out

    did = _video_id({"user_id": vals["u"], "lesson_asset_id": vals["a"]})

    async def body(tx: ScopedTransaction) -> None:
        cur = await tx.raw_get(VIDEO, did)
        old = VideoRow.of(cur) if cur else None
        if old is not None:
            old.covered_ranges = ranges_in(cur.get("covered_ranges")) if cur else None
        now = utcnow()
        row = VideoRow.from_pg(
            {
                "user_id": vals["u"],
                "lesson_asset_id": vals["a"],
                "organization_id": old.organization_id if old else vals["o"],
                "lesson_id": (old.lesson_id if old and old.lesson_id else None) or vals["l"],
                "covered_s": vals["cs"],
                "coverage_pct": vals["pct"],
                "duration_s": vals["dur"] if vals["dur"] is not None else (old.duration_s if old else None),
                "last_position_s": vals["pos"],
                "updated_at": now,
            }
        ).doc()
        row["covered_ranges"] = ranges_out(vals["cr"])
        tx.raw_set(VIDEO, did, row)

    await fs_raw.store().run_transaction(body)


# --------------------------------------------------------------------------- security feed


async def feed_users() -> list[uuid.UUID]:
    return list(dict.fromkeys(SecurityFeedRow.of(d).user_id for d in await fs_raw.all_docs(FEED)))


async def feed_upsert(row: dict[str, Any]) -> None:
    did = _feed_id(row)
    await _replace(FEED, [], [(did, SecurityFeedRow.from_pg({**row, "computed_at": utcnow()}).doc())])


# --------------------------------------------------------------------------- retention / erasure

_TIME_FIELDS = {
    "engagement_intervals": ("started_at", False),
    "daily_learning_aggregates": ("activity_date", True),
    "weekly_learning_aggregates": ("iso_week_start", True),
    "video_watch_coverage": ("updated_at", False),
    "topic_mastery": ("updated_at", False),
    "security_activity_feed_daily": ("activity_date", True),
    "analytics_ingest_rejections": ("hour_start", False),
}


async def purge_older(table: str, cutoff: datetime) -> int:
    """``DELETE FROM table WHERE col < cutoff`` (date columns compare by date)."""
    col, is_date = _TIME_FIELDS[table]
    cut: Any = cutoff.date().isoformat() if is_date else cutoff
    docs = await fs_raw.all_docs(table, filters=[(col, "<", cut)], order_by=((col, "asc"),))
    await _replace(table, [d.id for d in docs], [])
    return len(docs)


async def purge_batches(cutoff_events: datetime, cutoff_heartbeats: datetime) -> tuple[int, int]:
    """Raw rows past retention (``event_ts`` and server ``received_at`` both before the cutoff,
    BE-24): whole batch documents past the event retention go; heartbeats past theirs are cut out of
    newer batches. Returns (heartbeats, events) removed. The TTL on ``expire_at`` is the backstop."""
    st = fs_raw.store()
    docs = await fs_raw.all_docs(
        fs_raw.BATCHES,
        filters=[("received_at", "<", max(cutoff_events, cutoff_heartbeats))],
        order_by=(("received_at", "asc"),),
    )
    from app.modules.analytics.store_specs import EventRow, HeartbeatRow

    n_hb = n_ev = 0
    for d in docs:
        hbs = d.get("heartbeats") or []
        evs = d.get("events") or []
        keep_hb = [x for x in hbs if not _expired(HeartbeatRow.of(x), cutoff_heartbeats)]
        keep_ev = [x for x in evs if not _expired(EventRow.of(x), cutoff_events)]
        n_hb += len(hbs) - len(keep_hb)
        n_ev += len(evs) - len(keep_ev)
        if len(keep_hb) == len(hbs) and len(keep_ev) == len(evs):
            continue
        if not keep_hb and not keep_ev:
            await st.run_transaction(lambda tx, i=d.id: _del(tx, fs_raw.BATCHES, i))  # type: ignore[misc]
        else:
            ids = [HeartbeatRow.of(x).event_id.hex for x in keep_hb] + [
                EventRow.of(x).event_id.hex for x in keep_ev
            ]
            await st.run_transaction(
                lambda tx, d=d, kh=keep_hb, ke=keep_ev, ids=ids: _rewrite(tx, d, kh, ke, ids)  # type: ignore[misc]
            )
    return n_hb, n_ev


def _expired(r: Any, cutoff: datetime) -> bool:
    return r.event_ts < cutoff and (r.received_at is None or r.received_at < cutoff)


async def _del(tx: ScopedTransaction, coll: str, did: str) -> None:
    tx.raw_delete(coll, did)


async def _rewrite(tx: ScopedTransaction, d: Any, hbs: list[Any], evs: list[Any], ids: list[str]) -> None:
    tx.raw_set(fs_raw.BATCHES, d.id, {**d.data, "heartbeats": hbs, "events": evs, "event_ids": ids})


async def purge_dirty_before(day: date) -> int:
    docs = await fs_raw.all_docs(
        fs_raw.DIRTY, filters=[("activity_date", "<", day.isoformat())], order_by=(("activity_date", "asc"),)
    )
    await _replace(fs_raw.DIRTY, [d.id for d in docs], [])
    return len(docs)


async def erase_user(user_id: uuid.UUID) -> dict[str, int]:
    """Every identifiable analytics document of the user (batches included)."""
    out: dict[str, int] = {}
    hb = ev = 0
    for d in await fs_raw.all_docs(fs_raw.BATCHES, user_id=user_id):
        hb += len(d.get("heartbeats") or [])
        ev += len(d.get("events") or [])
    await fs_raw.delete_user_docs(fs_raw.BATCHES, user_id)
    await fs_raw.delete_user_docs(fs_raw.PAGE_HEARTBEATS, user_id)  # ingest's per-page summaries
    out["activity_heartbeats"], out["analytics_events"] = hb, ev
    for table in (
        "engagement_intervals",
        "daily_learning_aggregates",
        "weekly_learning_aggregates",
        "video_watch_coverage",
        "topic_mastery",
        "security_activity_feed_daily",
    ):
        out[table] = await fs_raw.delete_user_docs(table, user_id)
    dirty = [d for d in await fs_raw.all_docs(fs_raw.DIRTY) if d.get("user_id") == str(user_id)]
    await _replace(fs_raw.DIRTY, [d.id for d in dirty], [])
    out["analytics_dirty_days"] = len(dirty)
    return out
