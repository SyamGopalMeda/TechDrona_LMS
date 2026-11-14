"""Scheduled analytics jobs (analytics-event-schema §4.1). Each ``run_*`` function takes an
``AsyncSession`` whose transaction the caller owns, sets a named ``system_context`` and is
idempotent. ``python -m app.modules.analytics.jobs <job> [--once]`` runs one job (Celery beat
wiring is Planned; ``BEAT_SCHEDULE`` documents the intended cadence).

| job                     | cadence                                  |
|-------------------------|------------------------------------------|
| outbox_consumer         | 30 s                                     |
| interval_builder        | 60 s                                     |
| video_coverage          | 60 s (after the builder)                 |
| daily_aggregator        | 15 min (today), 02:30 IST (D-1), dirty days up to D-3 |
| rollups                 | 03:30 IST (weekly + cohort)              |
| security_feed           | 04:30 IST (D-1)                          |
| retention_purge         | daily                                    |
"""

from __future__ import annotations

import asyncio
import json
import sys
import time as _time
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, INT4RANGE
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.time import ist_date, utcnow
from app.modules.analytics import hooks
from app.modules.analytics.params import (
    FEED_VERSION,
    K_MIN_COHORT,
    MEASUREMENT_VERSION,
    RETENTION,
    TM,
)
from app.modules.analytics.service import bits_to_state, consent_active, mark_dirty
from app.modules.analytics.timemodel import (
    ENTITY_FIELDS,
    SERVER_EVIDENCE_SURFACE,
    AttemptRec,
    BuiltInterval,
    DayResult,
    IntervalRec,
    Lifecycle,
    Sample,
    build_intervals,
    compute_day,
    coverage_fraction,
    default_cap,
    ist_day_bounds,
    merge_ranges,
)

log = structlog.get_logger("app.analytics.jobs")

BEAT_SCHEDULE: dict[str, str] = {
    "outbox_consumer": "every 30s",
    "interval_builder": "every 60s",
    "video_coverage": "every 60s",
    "daily_aggregator_today": "every 15min",
    "daily_aggregator_d1": "02:30 Asia/Kolkata",
    "rollups": "03:30 Asia/Kolkata",
    "security_feed": "04:30 Asia/Kolkata",
    "retention_purge": "daily 05:00 Asia/Kolkata",
}


def _ts(t: float) -> datetime:
    return datetime.fromtimestamp(t, UTC)


def _fs() -> bool:
    from app.core.firestore.backend import uses_firestore

    return uses_firestore("analytics")


async def _set_state(
    session: AsyncSession, job: str, watermark: datetime | None, result: dict[str, Any]
) -> None:
    if _fs():
        from app.modules.analytics import fs_raw

        await fs_raw.set_state(job, watermark, json.loads(json.dumps(result, default=str)))
        return
    await session.execute(
        text(
            "INSERT INTO analytics_job_state (job, watermark, last_run_at, last_result) "
            "VALUES (:j, :w, now(), CAST(:r AS jsonb)) ON CONFLICT (job) DO UPDATE SET "
            "watermark = coalesce(EXCLUDED.watermark, analytics_job_state.watermark), "
            "last_run_at = EXCLUDED.last_run_at, last_result = EXCLUDED.last_result"
        ),
        {"j": job, "w": watermark, "r": json.dumps(result, default=str)},
    )


async def _get_watermark(session: AsyncSession, job: str) -> datetime | None:
    if _fs():
        from app.modules.analytics import fs_raw

        return await fs_raw.get_watermark(job)
    row = (
        await session.execute(text("SELECT watermark FROM analytics_job_state WHERE job = :j"), {"j": job})
    ).first()
    return row[0] if row else None


# =========================================================================== interval builder


async def _page_rows_pg(session: AsyncSession, user_id: uuid.UUID, page_id: uuid.UUID) -> tuple[Any, Any]:
    hbs = (
        await session.execute(
            text(
                """
                SELECT seq, effective_at, kind, active_ms, sample_interval_ms, state_bits, surface,
                       course_id, lesson_id, lesson_asset_id, question_id, test_attempt_id, coding_problem_id,
                       ingest_flags, scroll_depth_pct, edit_ops, editor_focused, organization_id,
                           auth_session_id,
                       device_id, tab_id, topic_id, privacy_tier
                FROM activity_heartbeats WHERE page_instance_id = :p AND user_id = :u ORDER BY seq,
                    effective_at
                """
            ),
            {"p": page_id, "u": user_id},
        )
    ).all()
    evs = (
        await session.execute(
            text(
                "SELECT seq, effective_at, event_type, payload, topic_id, surface, tab_id, privacy_tier, "
                "auth_session_id FROM analytics_events "
                "WHERE page_instance_id = :p AND user_id = :u AND event_type LIKE 'page.%' ORDER BY seq"
            ),
            {"p": page_id, "u": user_id},
        )
    ).all()
    return hbs, evs


async def rebuild_page_instance(
    session: AsyncSession, user_id: uuid.UUID, page_id: uuid.UUID, *, now: datetime
) -> list[BuiltInterval]:
    """Rebuild every interval of one page instance from raw rows (§3.4, §3.7)."""
    if _fs():
        from app.modules.analytics import fs_raw

        f_hbs, f_evs = await fs_raw.rows_for_page(user_id, page_id)
        hbs: Any = sorted(f_hbs, key=lambda h: (h.seq, h.effective_at))
        evs: Any = sorted(
            (e for e in f_evs if e.event_type.startswith("page.")), key=lambda e: (e.seq is None, e.seq or 0)
        )
    else:
        hbs, evs = await _page_rows_pg(session, user_id, page_id)
    samples = []
    for h in hbs:
        visible, focused, input_recent, media = bits_to_state(h.state_bits)
        samples.append(
            Sample(
                seq=h.seq,
                t=h.effective_at.timestamp(),
                kind=h.kind,
                active_ms=h.active_ms,
                visible=visible,
                focused=focused,
                input_recent=input_recent,
                media_playing=media,
                sample_interval_ms=h.sample_interval_ms,
                entity=(
                    h.course_id,
                    h.lesson_id,
                    h.lesson_asset_id,
                    h.question_id,
                    h.test_attempt_id,
                    h.coding_problem_id,
                ),
                flags=tuple(h.ingest_flags or ()),
            )
        )
    events = [Lifecycle(e.seq or 0, e.effective_at.timestamp(), e.event_type, e.payload or {}) for e in evs]
    sessions = {h.auth_session_id for h in hbs if h.auth_session_id} | {
        e.auth_session_id for e in evs if e.auth_session_id
    }
    session_end: float | None = None
    if sessions and _fs():
        from app.modules.analytics import fs_raw

        ends = [
            e.effective_at
            for e in await fs_raw.rows_for_sessions(user_id, sessions)
            if e.event_type == "session.ended" and e.auth_session_id in sessions
        ]
        if ends:
            session_end = min(ends).timestamp()
    elif sessions:
        row = (
            await session.execute(
                text(
                    "SELECT min(effective_at) FROM analytics_events WHERE user_id = :u "
                    "AND event_type = 'session.ended' AND auth_session_id = ANY(:s)"
                ),
                {"u": user_id, "s": list(sessions)},
            )
        ).first()
        if row and row[0] is not None:
            session_end = row[0].timestamp()
    built = build_intervals(samples, events, now=now.timestamp(), session_end=session_end)

    if _fs():
        from app.modules.analytics import fs_raw

        old: Any = [
            (o.started_at, o.ended_at if o.ended_at is not None else o.provisional_end)
            for o in await fs_raw.intervals(user_id=user_id, page_id=page_id)
        ]
    else:
        old = (
            await session.execute(
                text(
                    "SELECT started_at, coalesce(ended_at, provisional_end) FROM engagement_intervals "
                    "WHERE page_instance_id = :p AND user_id = :u"
                ),
                {"p": page_id, "u": user_id},
            )
        ).all()
        await session.execute(
            text("DELETE FROM engagement_intervals WHERE page_instance_id = :p AND user_id = :u"),
            {"p": page_id, "u": user_id},
        )
    first = hbs[0] if hbs else None
    topic = next((e.topic_id for e in evs if e.topic_id), None) or next(
        (h.topic_id for h in hbs if h.topic_id), None
    )
    org = next((h.organization_id for h in hbs if h.organization_id), None)
    tier = (first.privacy_tier if first else None) or next((e.privacy_tier for e in evs), "minor")
    surface = next((h.surface for h in hbs if h.surface), None) or next(
        (e.surface for e in evs if e.surface), "other"
    )
    tab = (first.tab_id if first else None) or next((e.tab_id for e in evs if e.tab_id), page_id)
    dates: set[date] = set()
    for s, e in old:
        dates |= {ist_date(s), ist_date(e)}
    fs_rows: list[dict[str, Any]] = []
    for iv in built:
        ent = dict(zip(ENTITY_FIELDS, iv.entity, strict=True))
        if _fs():
            fs_rows.append(
                {
                    "id": uuid7(),
                    "started_at": _ts(iv.started_at),
                    "ended_at": None if iv.is_open else _ts(iv.ended_at),
                    "last_sample_at": _ts(iv.last_sample_at),
                    "provisional_end": _ts(iv.ended_at),
                    "user_id": user_id,
                    "organization_id": org,
                    "auth_session_id": first.auth_session_id if first else None,
                    "device_id": first.device_id if first else None,
                    "tab_id": tab,
                    "page_instance_id": page_id,
                    "surface": surface,
                    "mode": iv.mode,
                    **ent,
                    "topic_id": topic,
                    "active_s": Decimal(str(round(iv.active_s, 3))),
                    "heartbeat_count": iv.heartbeat_count,
                    "close_reason": iv.close_reason,
                    "flags": sorted(iv.flags),
                    "is_open": iv.is_open,
                    "privacy_tier": tier,
                    "measurement_version": MEASUREMENT_VERSION,
                    "created_at": now,
                }
            )
            dates |= {ist_date(_ts(iv.started_at)), ist_date(_ts(iv.ended_at))}
            continue
        await session.execute(
            text(
                """
                INSERT INTO engagement_intervals (id, started_at, ended_at, last_sample_at,
                    provisional_end, user_id,
                    organization_id, auth_session_id, device_id, tab_id, page_instance_id, surface, mode,
                        course_id,
                    lesson_id, lesson_asset_id, topic_id, question_id, test_attempt_id,
                        coding_problem_id, active_s,
                    heartbeat_count, close_reason, flags, is_open, privacy_tier, measurement_version)
                VALUES (:id, :s, :e, :ls, :pe, :u, :o, :sid, :dev, :tab, :p, :surf, :mode, :course_id,
                    :lesson_id,
                    :lesson_asset_id, :topic, :question_id, :test_attempt_id, :coding_problem_id,
                        :active, :hb,
                    :reason, :flags, :open, :tier, :mv)
                """
            ),
            {
                "id": uuid7(),
                "s": _ts(iv.started_at),
                "e": None if iv.is_open else _ts(iv.ended_at),
                "ls": _ts(iv.last_sample_at),
                "pe": _ts(iv.ended_at),
                "u": user_id,
                "o": org,
                "sid": first.auth_session_id if first else None,
                "dev": first.device_id if first else None,
                "tab": tab,
                "p": page_id,
                "surf": surface,
                "mode": iv.mode,
                **ent,
                "topic": topic,
                "active": round(iv.active_s, 3),
                "hb": iv.heartbeat_count,
                "reason": iv.close_reason,
                "flags": sorted(iv.flags),
                "open": iv.is_open,
                "tier": tier,
                "mv": MEASUREMENT_VERSION,
            },
        )
        dates |= {ist_date(_ts(iv.started_at)), ist_date(_ts(iv.ended_at))}
    if _fs():
        from app.modules.analytics import fs_raw

        await fs_raw.replace_page_intervals(user_id, page_id, fs_rows)
    for d in dates:
        await mark_dirty(session, user_id, d, "interval_rebuild")
    return built


async def _discover_pages_pg(session: AsyncSession, since: datetime, limit: int) -> Any:
    rows = (
        await session.execute(
            text(
                """
                SELECT user_id, page_instance_id, max(received_at) AS r FROM (
                    SELECT user_id, page_instance_id, received_at FROM activity_heartbeats
                        WHERE received_at > :since
                    UNION ALL
                    SELECT user_id, page_instance_id, received_at FROM analytics_events
                     WHERE received_at > :since AND page_instance_id IS NOT NULL
                    UNION ALL
                    SELECT e.user_id, i.page_instance_id, e.received_at FROM analytics_events e
                      JOIN engagement_intervals i ON i.auth_session_id = e.auth_session_id AND i.is_open
                     WHERE e.event_type = 'session.ended' AND e.received_at > :since
                    UNION ALL
                    SELECT user_id, page_instance_id, NULL FROM engagement_intervals WHERE is_open
                ) x GROUP BY user_id, page_instance_id LIMIT :n
                """
            ),
            {"since": since, "n": limit},
        )
    ).all()
    return rows


@dataclass(frozen=True)
class _PageKey:
    user_id: uuid.UUID
    page_instance_id: uuid.UUID
    r: datetime | None


async def _discover_pages_fs(since: datetime, limit: int) -> list[_PageKey]:
    """The union of ``_discover_pages_pg``: pages with rows received after ``since``, pages of
    open intervals whose auth session ended after ``since``, and every open interval; ``r`` is
    the newest ``received_at`` (``NULL`` only from open intervals, as ``max`` ignores NULL)."""
    from app.modules.analytics import fs_raw

    newest: dict[tuple[uuid.UUID, uuid.UUID], datetime | None] = {}

    def bump(u: uuid.UUID, p: uuid.UUID, r: datetime | None) -> None:
        cur = newest.get((u, p))
        if cur is None or (r is not None and r > cur):
            newest[(u, p)] = r if r is not None else cur
        elif (u, p) not in newest:
            newest[(u, p)] = r

    hbs, evs = await fs_raw.rows_received_after(since)
    for h in hbs:
        if h.received_at > since:
            bump(h.user_id, h.page_instance_id, h.received_at)
    for e in evs:
        if e.received_at > since and e.page_instance_id is not None:
            bump(e.user_id, e.page_instance_id, e.received_at)
    open_ivs = await fs_raw.intervals(is_open=True)
    for e in evs:
        if e.event_type == "session.ended" and e.received_at > since:
            for i in open_ivs:
                if i.auth_session_id == e.auth_session_id:
                    bump(e.user_id, i.page_instance_id, e.received_at)
    for i in open_ivs:
        bump(i.user_id, i.page_instance_id, None)
    return [_PageKey(u, p, r) for (u, p), r in list(newest.items())[:limit]]


async def run_interval_builder(
    session: AsyncSession, *, now: datetime | None = None, limit: int = 5000
) -> dict[str, Any]:
    now = now or utcnow()
    await system_context(session, "analytics.interval_builder")
    wm = await _get_watermark(session, "interval_builder") or datetime(1970, 1, 1, tzinfo=UTC)
    since = wm - timedelta(minutes=2)  # overlap for in-flight transactions
    if _fs():
        rows: Any = await _discover_pages_fs(since, limit)
    else:
        rows = await _discover_pages_pg(session, since, limit)
    newest = max((r.r for r in rows if r.r is not None), default=None)
    built = 0
    for r in rows:
        built += len(await rebuild_page_instance(session, r.user_id, r.page_instance_id, now=now))
    result = {"page_instances": len(rows), "intervals": built}
    await _set_state(session, "interval_builder", max(newest, wm) if newest else wm, result)
    return result


# =========================================================================== daily aggregates


class _Caps:
    def __init__(self, lessons: dict[uuid.UUID, hooks.LessonMeta], assets: dict[uuid.UUID, hooks.AssetMeta]):
        self.lessons, self.assets = lessons, assets

    def __call__(self, iv: IntervalRec) -> tuple[Any, float | None]:
        key, cap = default_cap(iv)
        if iv.surface == "lesson_text" and iv.lesson_id in self.lessons:
            est = self.lessons[iv.lesson_id].est_reading_minutes
            if est:
                cap = max(TM.cap_lesson_text_factor * est * 60, TM.cap_lesson_text_min_s)
        if iv.surface == "lesson_video" and iv.lesson_asset_id in self.assets:
            dur = self.assets[iv.lesson_asset_id].duration_s
            if dur:
                cap = TM.cap_video_factor * dur
        return key, cap


async def _user_flags(session: AsyncSession, user_id: uuid.UUID) -> tuple[str, bool] | None:

    from app.modules.identity import public as idp

    u = await idp.get_user(session, user_id)
    return (u.privacy_tier, bool(u.is_synthetic)) if u is not None else None


async def _day_intervals_pg(session: AsyncSession, user_id: uuid.UUID, d0: datetime, d1: datetime) -> Any:
    ivs = (
        await session.execute(
            text(
                """
                SELECT page_instance_id, surface, mode, flags, started_at, coalesce(ended_at,
                    provisional_end) AS e,
                       last_sample_at, course_id, lesson_id, lesson_asset_id, topic_id, question_id,
                           test_attempt_id,
                       coding_problem_id, organization_id, device_id
                FROM engagement_intervals
                WHERE user_id = :u AND started_at >= :lo AND started_at < :d1
                  AND coalesce(ended_at, provisional_end) > :d0
                """
            ),
            {"u": user_id, "lo": d0 - timedelta(days=1), "d0": d0, "d1": d1},
        )
    ).all()
    return ivs


async def load_day_inputs(
    session: AsyncSession, user_id: uuid.UUID, day: date, *, now: datetime
) -> tuple[DayResult, dict[str, Any]]:
    """Load intervals/evidence/presence/attempts for one user-day and compute M1..M5."""
    d0f, d1f = ist_day_bounds(day)
    d0, d1 = _ts(d0f), _ts(d1f)
    ivs: Any
    if _fs():
        from app.modules.analytics import fs_raw

        ivs = []
        for r in await fs_raw.intervals(
            user_id=user_id, started_from=d0 - timedelta(days=1), started_before=d1
        ):
            r.e = r.ended_at if r.ended_at is not None else r.provisional_end
            if r.e > d0:
                ivs.append(r)
    else:
        ivs = await _day_intervals_pg(session, user_id, d0, d1)
    intervals = [
        IntervalRec(
            page_instance_id=str(r.page_instance_id),
            surface=r.surface,
            mode=r.mode,
            hidden_playback="hidden_playback" in (r.flags or []),
            start=r.started_at.timestamp(),
            end=r.e.timestamp(),
            last_sample=r.last_sample_at.timestamp(),
            course_id=r.course_id,
            lesson_id=r.lesson_id,
            lesson_asset_id=r.lesson_asset_id,
            topic_id=r.topic_id,
            question_id=r.question_id,
            test_attempt_id=r.test_attempt_id,
            coding_problem_id=r.coding_problem_id,
            organization_id=r.organization_id,
            device_id=r.device_id,
        )
        for r in ivs
    ]
    margin = timedelta(seconds=TM.evidence_window_s + 3600)
    hbs: Any
    evs: Any
    if _fs():
        from app.modules.analytics import fs_raw

        f_hbs = (await fs_raw.rows_for_window(user_id, d0 - timedelta(hours=12), d1 + timedelta(hours=12)))[0]
        hbs = sorted(f_hbs, key=lambda h: (h.page_instance_id, h.seq))
        evs = (await fs_raw.rows_for_window(user_id, d0 - timedelta(days=2), d1 + timedelta(hours=12)))[1]
    else:
        hbs = None
    if hbs is None:
        hbs = (
            await session.execute(
                text(
                    """
                SELECT page_instance_id, effective_at, kind, state_bits, scroll_depth_pct, edit_ops,
                    editor_focused,
                       ingest_flags
                FROM activity_heartbeats WHERE user_id = :u AND effective_at >= :lo AND effective_at < :hi
                ORDER BY page_instance_id, seq
                """
                ),
                {"u": user_id, "lo": d0 - timedelta(hours=12), "hi": d1 + timedelta(hours=12)},
            )
        ).all()
    if not _fs():
        evs = None
    client_evidence: dict[str, list[float]] = defaultdict(list)
    max_scroll: dict[str, int] = {}
    presence: list[float] = []
    flag_counts: dict[str, int] = defaultdict(int)
    for h in hbs:
        t = h.effective_at.timestamp()
        presence.append(t)
        if d0 <= h.effective_at < d1:
            for f in h.ingest_flags or ():
                flag_counts[f] += 1
        if not (d0 - margin <= h.effective_at < d1 + margin) or h.kind != "engaged":
            continue
        pid = str(h.page_instance_id)
        _v, _f, _i, media = bits_to_state(h.state_bits)
        scroll = h.scroll_depth_pct
        evidence = media or (h.edit_ops or 0) > 0 or bool(h.editor_focused)
        if scroll is not None and scroll > max_scroll.get(pid, 0):
            evidence = True
            max_scroll[pid] = scroll
        if evidence:
            client_evidence[pid].append(t)
    if evs is None:
        evs = (
            await session.execute(
                text(
                    """
                SELECT event_type, effective_at, source, payload, topic_id, course_id, lesson_id,
                    test_attempt_id,
                       organization_id, ingest_flags
                FROM analytics_events WHERE user_id = :u AND effective_at >= :lo AND effective_at < :hi
                """
                ),
                {"u": user_id, "lo": d0 - timedelta(days=2), "hi": d1 + timedelta(hours=12)},
            )
        ).all()
    server_evidence: dict[str, list[float]] = defaultdict(list)
    attempts: dict[uuid.UUID, dict[str, Any]] = {}
    counters: dict[tuple[str, uuid.UUID | None], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in evs:
        t = e.effective_at.timestamp()
        in_day = d0 <= e.effective_at < d1
        if e.event_type != "session.ended" and e.effective_at >= d0 - timedelta(hours=12):
            presence.append(t)
        if in_day:
            for f in e.ingest_flags or ():
                flag_counts[f] += 1
        surf = SERVER_EVIDENCE_SURFACE.get(e.event_type)
        if surf and e.source == "server":
            server_evidence[surf].append(t)
        p = e.payload or {}
        if e.event_type.startswith("assessment.") and e.test_attempt_id is not None:
            a = attempts.setdefault(e.test_attempt_id, {"org": e.organization_id})
            if e.event_type == "assessment.attempt_started":
                a["started"] = _parse(p.get("started_at")) or e.effective_at
                a["deadline"] = _parse(p.get("deadline_at"))
            elif e.event_type in ("assessment.attempt_submitted", "assessment.auto_submitted") or (
                e.event_type == "assessment.attempt_scored" and p.get("submitted_at")
            ):
                a["submitted"] = _parse(p.get("submitted_at")) or e.effective_at
                a.setdefault("started", _parse(p.get("started_at")))
                a.setdefault("deadline", _parse(p.get("deadline_at")))
        if not in_day:
            continue
        keys: list[tuple[str, uuid.UUID | None]] = [("_total", None)]
        if e.topic_id:
            keys.append(("topic", e.topic_id))
        if e.course_id:
            keys.append(("course", e.course_id))
        bumps: dict[str, int] = {}
        if e.event_type == "practice.answer_submitted":
            bumps["questions_attempted"] = 1
            if p.get("is_correct"):
                bumps["questions_correct"] = 1
                if int(p.get("attempt_no") or 1) <= 1:
                    bumps["first_attempt_correct"] = 1
        elif e.event_type == "coding.run":
            bumps["code_runs"] = 1
        elif e.event_type == "coding.submit":
            bumps["code_submissions"] = 1
        elif e.event_type == "coding.submission_judged":
            if p.get("mode") == "submit":
                bumps["code_submissions"] = 1
            if p.get("verdict") == "AC":
                bumps["code_accepted"] = 1
        elif e.event_type == "learning.lesson_completed":
            bumps["lessons_completed"] = 1
            if e.lesson_id:
                keys.append(("lesson", e.lesson_id))
        for k in keys:
            for name, n in bumps.items():
                counters[k][name] += n
    attempt_recs = [
        AttemptRec(
            attempt_id=aid,
            started_at=a["started"].timestamp(),
            deadline_at=a["deadline"].timestamp() if a.get("deadline") else None,
            submitted_at=a["submitted"].timestamp() if a.get("submitted") else None,
            organization_id=a.get("org"),
        )
        for aid, a in attempts.items()
        if a.get("started") is not None
    ]
    lookup = hooks.lesson_meta_lookup()
    lessons = await lookup.lessons(session, {iv.lesson_id for iv in intervals if iv.lesson_id})
    assets = await lookup.assets(session, {iv.lesson_asset_id for iv in intervals if iv.lesson_asset_id})
    res = compute_day(
        day=day,
        intervals=intervals,
        client_evidence=dict(client_evidence),
        server_evidence=dict(server_evidence),
        presence=presence,
        attempts=attempt_recs,
        now=now.timestamp(),
        cap_fn=_Caps(lessons, assets),
    )
    return res, {"counters": counters, "flags": dict(flag_counts)}


def _parse(v: Any) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


async def _category_of(session: AsyncSession, topic_ids: set[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """Root ``subject`` of each topic (placement taxonomy) when the table exists."""
    if not topic_ids:
        return {}
    from app.modules.placement import public as placement

    return dict(await placement.topic_roots(session, topic_ids))


def _daily_values(
    params: dict[str, Any],
    kind: str,
    eid: Any,
    user_id: uuid.UUID,
    em: Any,
    c: dict[str, int],
    cats: dict[uuid.UUID, uuid.UUID],
    topic: Any,
    res: Any,
    m2: int,
    m5: int,
    tier: str,
    is_frozen: bool,
) -> dict[str, Any]:
    """The ``daily_learning_aggregates`` row the INSERT below writes, by column name (Firestore)."""
    return {
        "user_id": params["u"],
        "activity_date": params["d"],
        "entity_kind": kind,
        "entity_id": eid if eid is not None else user_id,
        "organization_id": em.organization_id if em else None,
        "course_id": eid if kind == "course" else (em.course_id if em else None),
        "topic_id": topic,
        "category_topic_id": cats.get(topic) if topic else None,
        "m1_session_elapsed_s": round(max(res.m1, res.m2)) if kind == "_total" else None,
        "m2_active_s": m2,
        "m3_video_playback_s": round(em.m3) if em else 0,
        "m4_assessment_s": round(em.m4) if em else 0,
        "m5_learning_s": m5,
        "assessment_active_s": (
            round(res.assessment_active_s.get(eid, 0.0)) if kind == "test_attempt" and eid else 0
        ),
        "questions_attempted": c.get("questions_attempted", 0),
        "questions_correct": c.get("questions_correct", 0),
        "first_attempt_correct": c.get("first_attempt_correct", 0),
        "code_runs": c.get("code_runs", 0),
        "code_submissions": c.get("code_submissions", 0),
        "code_accepted": c.get("code_accepted", 0),
        "lessons_completed": c.get("lessons_completed", 0),
        "implausible_day": res.implausible,
        "privacy_tier": tier,
        "measurement_version": MEASUREMENT_VERSION,
        "is_frozen": is_frozen,
    }


async def compute_user_day(
    session: AsyncSession, user_id: uuid.UUID, day: date, *, now: datetime | None = None, force: bool = False
) -> DayResult | None:
    """Recompute ``daily_learning_aggregates`` for one user x IST day (delete + insert).
    Synthetic users get no rows; frozen days (D+4) are only recomputed with ``force``
    (audited super_admin backfill)."""
    now = now or utcnow()
    flags = await _user_flags(session, user_id)
    params = {"u": user_id, "d": day}
    if _fs():
        from app.modules.analytics import fs_raw
    if (flags is None or flags[1]) and _fs():
        await fs_raw.replace_daily(user_id, day, [])
        return None
    if flags is None or flags[1]:
        await session.execute(
            text("DELETE FROM daily_learning_aggregates WHERE user_id = :u AND activity_date = :d"), params
        )
        await session.execute(
            text("DELETE FROM analytics_dirty_days WHERE user_id = :u AND activity_date = :d"), params
        )
        return None
    tier = flags[0]
    if _fs():
        frozen: Any = any(
            r.is_frozen for r in await fs_raw.daily_rows(user_id, day) if r.entity_kind == "_total"
        )
        if frozen and not force:
            await fs_raw.clear_dirty(user_id, day)
            return None
    frozen = (
        False
        if _fs()
        else (
            await session.execute(
                text(
                    "SELECT is_frozen FROM daily_learning_aggregates "
                    "WHERE user_id = :u AND activity_date = :d AND entity_kind = '_total'"
                ),
                params,
            )
        ).scalar()
    )
    if frozen and not force:
        await session.execute(
            text("DELETE FROM analytics_dirty_days WHERE user_id = :u AND activity_date = :d"), params
        )
        return None
    res, extra = await load_day_inputs(session, user_id, day, now=now)
    counters = extra["counters"]
    if not _fs():
        await session.execute(
            text("DELETE FROM daily_learning_aggregates WHERE user_id = :u AND activity_date = :d"), params
        )
    fs_daily: list[dict[str, Any]] = []
    is_frozen = day <= ist_date(now) - timedelta(days=TM.freeze_after_days)
    keys = set(res.entities) | set(counters)
    has_activity = res.m1 > 0 or res.m2 > 0 or res.m3 > 0 or res.m4 > 0 or bool(counters)
    if has_activity:
        keys.add(("_total", None))
    cats = await _category_of(session, {k[1] for k in keys if k[0] == "topic" and k[1]})
    for kind, eid in keys:
        em = res.entities.get((kind, eid))
        c = counters.get((kind, eid), {})
        m2 = round(em.m2) if em else 0
        m5 = min(round(em.m5), m2) if em else 0
        topic = eid if kind == "topic" else (em.topic_id if em else None)
        vals = _daily_values(params, kind, eid, user_id, em, c, cats, topic, res, m2, m5, tier, is_frozen)
        if _fs():
            fs_daily.append(vals)
            continue
        await session.execute(
            text(
                """
                INSERT INTO daily_learning_aggregates (user_id, activity_date, entity_kind, entity_id,
                    organization_id,
                    course_id, topic_id, category_topic_id, m1_session_elapsed_s, m2_active_s,
                        m3_video_playback_s,
                    m4_assessment_s, m5_learning_s, assessment_active_s, questions_attempted,
                        questions_correct,
                    first_attempt_correct, code_runs, code_submissions, code_accepted, lessons_completed,
                    implausible_day, privacy_tier, measurement_version, is_frozen, computed_at)
                VALUES (:u, :d, :k, :e, :o, :c, :t, :cat, :m1, :m2, :m3, :m4, :m5, :aa, :qa, :qc, :fac,
                    :cr, :cs, :ca,
                    :lc, :imp, :tier, :mv, :fz, now())
                """
            ),
            {
                **params,
                "k": kind,
                "e": eid if eid is not None else user_id,
                "o": em.organization_id if em else None,
                "c": eid if kind == "course" else (em.course_id if em else None),
                "t": topic,
                "cat": cats.get(topic) if topic else None,
                "m1": round(max(res.m1, res.m2)) if kind == "_total" else None,
                "m2": m2,
                "m3": round(em.m3) if em else 0,
                "m4": round(em.m4) if em else 0,
                "m5": m5,
                "aa": round(res.assessment_active_s.get(eid, 0.0)) if kind == "test_attempt" and eid else 0,
                "qa": c.get("questions_attempted", 0),
                "qc": c.get("questions_correct", 0),
                "fac": c.get("first_attempt_correct", 0),
                "cr": c.get("code_runs", 0),
                "cs": c.get("code_submissions", 0),
                "ca": c.get("code_accepted", 0),
                "lc": c.get("lessons_completed", 0),
                "imp": res.implausible,
                "tier": tier,
                "mv": MEASUREMENT_VERSION,
                "fz": is_frozen,
            },
        )
    if _fs():
        await fs_raw.replace_daily(user_id, day, fs_daily)  # also clears the dirty mark
    else:
        await session.execute(
            text("DELETE FROM analytics_dirty_days WHERE user_id = :u AND activity_date = :d"), params
        )
    if res.implausible:
        log.warning("analytics_implausible_day", user_id=str(user_id), day=str(day))
    return res


async def users_active_on(session: AsyncSession, day: date) -> list[uuid.UUID]:
    d0f, d1f = ist_day_bounds(day)
    d0, d1 = _ts(d0f), _ts(d1f)
    if _fs():
        from app.modules.analytics import fs_raw

        users: set[uuid.UUID] = set()
        for i in await fs_raw.intervals(started_from=d0 - timedelta(days=1), started_before=d1):
            if (i.ended_at if i.ended_at is not None else i.provisional_end) > d0:
                users.add(i.user_id)
        hbs, evs = await fs_raw.rows_for_days(fs_raw.ist_days(d0, d1))
        users |= {h.user_id for h in hbs if d0 <= h.effective_at < d1}
        users |= {e.user_id for e in evs if d0 <= e.effective_at < d1}
        return list(users)
    rows = (
        await session.execute(
            text(
                """
                SELECT user_id FROM engagement_intervals WHERE started_at >= :lo AND started_at < :d1
                    AND coalesce(ended_at, provisional_end) > :d0
                UNION SELECT user_id FROM activity_heartbeats WHERE effective_at >= :d0 AND effective_at < :d1
                UNION SELECT user_id FROM analytics_events WHERE effective_at >= :d0 AND effective_at < :d1
                """
            ),
            {"lo": d0 - timedelta(days=1), "d0": d0, "d1": d1},
        )
    ).all()
    return [r[0] for r in rows]


async def run_daily_aggregation(
    session: AsyncSession,
    *,
    days: Sequence[date] | None = None,
    now: datetime | None = None,
    include_dirty: bool = True,
) -> dict[str, Any]:
    """``days`` defaults to today (IST). Dirty days within the late window are recomputed."""
    now = now or utcnow()
    await system_context(session, "analytics.daily_aggregator")
    today = ist_date(now)
    todo: set[tuple[uuid.UUID, date]] = set()
    for d in days or [today]:
        for u in await users_active_on(session, d):
            todo.add((u, d))
    if include_dirty and _fs():
        from app.modules.analytics import fs_raw

        todo |= set(await fs_raw.dirty_days())
    elif include_dirty:
        rows = (await session.execute(text("SELECT user_id, activity_date FROM analytics_dirty_days"))).all()
        todo |= {(r[0], r[1]) for r in rows}
    for u, d in sorted(todo, key=lambda x: (x[1], str(x[0]))):
        await compute_user_day(session, u, d, now=now)
    result = {"user_days": len(todo)}
    await _set_state(session, "daily_aggregator", now, result)
    return result


# =========================================================================== rollups


def week_start(d: date) -> date:
    return d - timedelta(days=d.isoweekday() - 1)


async def rollup_week(session: AsyncSession, monday: date) -> int:
    await system_context(session, "analytics.rollups")
    sunday = monday + timedelta(days=6)
    if _fs():
        from app.modules.analytics import fs_jobs

        return await fs_jobs.rollup_week(session, monday, sunday, MEASUREMENT_VERSION)
    await session.execute(
        text("DELETE FROM weekly_learning_aggregates WHERE iso_week_start = :w"), {"w": monday}
    )
    res = await session.execute(
        text(
            """
            INSERT INTO weekly_learning_aggregates (user_id, iso_week_start, entity_kind, entity_id,
                organization_id,
                m2_active_s, m3_video_playback_s, m4_assessment_s, m5_learning_s, active_days, privacy_tier,
                measurement_version)
            SELECT d.user_id, :w, d.entity_kind, d.entity_id, max(d.organization_id::text)::uuid,
                   sum(d.m2_active_s), sum(d.m3_video_playback_s), sum(d.m4_assessment_s),
                       sum(d.m5_learning_s),
                   count(*) FILTER (WHERE d.m5_learning_s >= 600),
                   CASE WHEN bool_or(d.privacy_tier = 'minor') THEN 'minor' ELSE 'adult' END, :mv
            FROM daily_learning_aggregates d
            WHERE d.activity_date BETWEEN :w AND :s
                AND d.entity_kind IN ('_total','course','topic')
              AND d.measurement_version = :mv AND NOT (d.user_id = ANY(:syn))
            GROUP BY d.user_id, d.entity_kind, d.entity_id
            """
        ),
        {"w": monday, "s": sunday, "mv": MEASUREMENT_VERSION, "syn": await hooks.synthetic_user_ids(session)},
    )
    return int(getattr(res, "rowcount", 0) or 0)


def _pct(values: list[int], q: float) -> int | None:
    if not values:
        return None
    v = sorted(values)
    idx = q * (len(v) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (idx - lo))


async def _upsert_cohort(
    session: AsyncSession,
    *,
    org: uuid.UUID | None,
    batch: uuid.UUID | None,
    period_kind: str,
    start: date,
    enrolled: int,
    per_user: dict[uuid.UUID, dict[str, int]],
    k_min: int = K_MIN_COHORT,
) -> None:
    active = [v["m5"] for v in per_user.values() if v["m5"] > 0 and not v.get("implausible")]
    suppressed = enrolled < k_min or len(active) < k_min
    attempted = sum(v["qa"] for v in per_user.values())
    correct = sum(v["qc"] for v in per_user.values())
    vals: dict[str, Any] = {
        "id": uuid7(),
        "o": org,
        "b": batch,
        "pk": period_kind,
        "ps": start,
        "en": enrolled,
        "la": None if suppressed else len(active),
        "sum": None if suppressed else sum(active),
        "p50": None if suppressed else _pct(active, 0.5),
        "p90": None if suppressed else _pct(active, 0.9),
        "comp": None if suppressed else sum(v["lc"] for v in per_user.values()),
        "acc": None if suppressed or attempted == 0 else round(correct / attempted, 4),
        "sup": suppressed,
        "mv": MEASUREMENT_VERSION,
    }
    if _fs():
        from app.modules.analytics import fs_jobs

        await fs_jobs.upsert_cohort(vals)
        return
    await session.execute(
        text(
            """
            INSERT INTO cohort_learning_aggregates (id, organization_id, batch_id, period_kind, period_start,
                entity_kind, entity_id, learners_enrolled, learners_active, m5_sum_s, m5_p50_s, m5_p90_s,
                    completions,
                accuracy, suppressed, measurement_version, computed_at)
            VALUES (:id, :o, :b, :pk, :ps, '_total', NULL, :en, :la, :sum, :p50, :p90, :comp, :acc, :sup,
                :mv, now())
            ON CONFLICT (organization_id, batch_id, period_kind, period_start, entity_kind,
                entity_id) DO UPDATE SET
                learners_enrolled = EXCLUDED.learners_enrolled, learners_active = EXCLUDED.learners_active,
                m5_sum_s = EXCLUDED.m5_sum_s, m5_p50_s = EXCLUDED.m5_p50_s, m5_p90_s = EXCLUDED.m5_p90_s,
                completions = EXCLUDED.completions, accuracy = EXCLUDED.accuracy,
                    suppressed = EXCLUDED.suppressed,
                measurement_version = EXCLUDED.measurement_version, computed_at = now()
            """
        ),
        vals,
    )


async def _per_user(
    session: AsyncSession, kind: str, entity: uuid.UUID | None, lo: date, hi: date, users: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    if not users:
        return {}
    if _fs():
        from app.modules.analytics import fs_jobs

        return await fs_jobs.per_user(kind, entity, lo, hi, users, MEASUREMENT_VERSION)
    sql = (
        "SELECT user_id, sum(m5_learning_s), sum(questions_attempted), sum(questions_correct), "
        "sum(lessons_completed), bool_or(implausible_day) FROM daily_learning_aggregates "
        "WHERE entity_kind = :k AND activity_date BETWEEN :lo AND :hi AND user_id = ANY(:us) "
        "AND measurement_version = :mv"
    )
    params: dict[str, Any] = {"k": kind, "lo": lo, "hi": hi, "us": users, "mv": MEASUREMENT_VERSION}
    if entity is not None:
        sql += " AND entity_id = :e"
        params["e"] = entity
    rows = (await session.execute(text(sql + " GROUP BY user_id"), params)).all()
    out = {u: {"m5": 0, "qa": 0, "qc": 0, "lc": 0} for u in users}
    for r in rows:
        out[r[0]] = {
            "m5": int(r[1] or 0),
            "qa": int(r[2] or 0),
            "qc": int(r[3] or 0),
            "lc": int(r[4] or 0),
            "implausible": bool(r[5]),
        }
    return out


async def rollup_cohorts(session: AsyncSession, period_kind: str, start: date) -> int:
    """Batch and platform cohort cells with the k-floor (§4.5). Synthetic users never count
    toward k or totals. Single company: there are no organization cohorts; a batch cell sums its
    active student members' whole (``_total``) activity."""
    await system_context(session, "analytics.rollups")
    end = start + timedelta(days=6 if period_kind == "week" else 0)
    n = 0
    # Batches and their active student members come from orgs.public, synthetic flags from
    # identity.public (both stores); the platform users from this module's daily rows.
    from app.modules.analytics import fs_jobs

    if _fs():
        fs_batches, users = await fs_jobs.cohort_inputs(session, start, end)
    else:
        fs_batches = await fs_jobs.batch_cohorts(session)
        syn = set(await hooks.synthetic_user_ids(session))
        users = [
            r[0]
            for r in (
                await session.execute(
                    text(
                        "SELECT DISTINCT d.user_id FROM daily_learning_aggregates d "
                        "WHERE d.entity_kind = '_total' AND d.activity_date BETWEEN :lo AND :hi"
                    ),
                    {"lo": start, "hi": end},
                )
            ).all()
            if r[0] not in syn
        ]
    for batch, org, bm in fs_batches:
        per_b = await _per_user(session, "_total", None, start, end, bm)
        await _upsert_cohort(
            session,
            org=org,
            batch=batch,
            period_kind=period_kind,
            start=start,
            enrolled=len(bm),
            per_user=per_b,
        )
        n += 1
    per_all = await _per_user(session, "_total", None, start, end, users)
    await _upsert_cohort(
        session,
        org=None,
        batch=None,
        period_kind=period_kind,
        start=start,
        enrolled=len(users),
        per_user=per_all,
    )
    return n + 1


async def run_rollups(
    session: AsyncSession, *, now: datetime | None = None, day: date | None = None
) -> dict[str, Any]:
    now = now or utcnow()
    d = day or (ist_date(now) - timedelta(days=1))
    monday = week_start(d)
    weekly = await rollup_week(session, monday)
    cells = await rollup_cohorts(session, "day", d)
    cells += await rollup_cohorts(session, "week", monday)
    result = {"weekly_rows": weekly, "cohort_cells": cells, "day": str(d)}
    await _set_state(session, "rollups", now, result)
    return result


# =========================================================================== video coverage


async def run_video_coverage(session: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    """Merge played ranges into ``video_watch_coverage`` (§3.9). Union is idempotent, so
    re-processing the overlap window is safe."""
    now = now or utcnow()
    await system_context(session, "analytics.video_coverage")
    wm = await _get_watermark(session, "video_coverage") or datetime(1970, 1, 1, tzinfo=UTC)
    if _fs():
        from app.modules.analytics import fs_jobs

        rows: Any = await fs_jobs.coverage_inputs(wm - timedelta(minutes=2))
    else:
        rows = None
    if rows is None:
        rows = (
            await session.execute(
                text(
                    """
                SELECT user_id, lesson_asset_id, max(organization_id::text)::uuid AS org,
                    max(lesson_id::text)::uuid AS lesson,
                       array_agg(r) AS ranges, max(received_at) AS rec,
                       (array_agg(media_position_s ORDER BY effective_at DESC))[1] AS pos
                FROM activity_heartbeats, unnest(played_ranges) AS r
                WHERE received_at > :since AND lesson_asset_id IS NOT NULL AND played_ranges IS NOT NULL
                GROUP BY user_id, lesson_asset_id
                """
                ),
                {"since": wm - timedelta(minutes=2)},
            )
        ).all()
    if not rows:
        await _set_state(session, "video_coverage", wm, {"assets": 0})
        return {"assets": 0}
    assets = await hooks.lesson_meta_lookup().assets(session, {r.lesson_asset_id for r in rows})
    durations: dict[uuid.UUID, float] = {k: v.duration_s for k, v in assets.items() if v.duration_s}
    missing = [r.lesson_asset_id for r in rows if r.lesson_asset_id not in durations]
    if missing:
        # Server-side duration (catalog row) before any client-reported ``video.ended`` value.
        from app.modules.catalog import api as catalog_api

        for aid, a in (await catalog_api.get_assets(session, missing)).items():
            if a.duration_seconds:
                durations[aid] = float(a.duration_seconds)
        missing = [a for a in missing if a not in durations]
    if missing and _fs():
        from app.modules.analytics import fs_jobs

        for aid, fdur in (await fs_jobs.video_ended_durations(missing)).items():
            if fdur:
                durations[aid] = float(fdur)
        missing = []
    if missing:
        for aid, dur in (
            await session.execute(
                text(
                    "SELECT lesson_asset_id, max((payload->>'duration_s')::numeric) FROM analytics_events "
                    "WHERE event_type = 'video.ended' AND lesson_asset_id = ANY(:a) GROUP BY lesson_asset_id"
                ),
                {"a": missing},
            )
        ).all():
            if dur:
                durations[aid] = float(dur)
    newest = wm
    for r in rows:
        if _fs():
            from app.modules.analytics import fs_jobs

            existing: Any = await fs_jobs.coverage_existing(r.user_id, r.lesson_asset_id)
        else:
            existing = None
        if not _fs():
            existing = (
                await session.execute(
                    text(
                        "SELECT covered_ranges FROM video_watch_coverage WHERE user_id = :u AND "
                        "lesson_asset_id = :a"
                    ),
                    {"u": r.user_id, "a": r.lesson_asset_id},
                )
            ).scalar()
        pairs = [(x.lower / 10.0, x.upper / 10.0) for x in (existing or []) if x.lower is not None]
        pairs += [(x.lower / 10.0, x.upper / 10.0) for x in r.ranges if x is not None and x.lower is not None]
        dur = durations.get(r.lesson_asset_id)
        if dur:
            # BE-01: coverage can never exceed the asset (ranges past the end are not media).
            pairs = [(max(0.0, a), min(dur, b)) for a, b in pairs]
        merged = merge_ranges([(a, b) for a, b in pairs if b > a])
        covered = sum(b - a for a, b in merged)
        pct = round(coverage_fraction(merged, dur) * 100, 2) if dur else 0.0
        from sqlalchemy.dialects.postgresql import Range

        cov_vals = {
            "u": r.user_id,
            "a": r.lesson_asset_id,
            "o": r.org,
            "l": r.lesson,
            "cr": [Range(round(a * 10), round(b * 10), bounds="[)") for a, b in merged],
            "cs": round(covered, 1),
            "pct": min(100.0, pct),
            "dur": round(dur) if dur else None,
            "pos": int(r.pos) if r.pos is not None else None,
        }
        if _fs():
            from app.modules.analytics import fs_jobs

            await fs_jobs.coverage_upsert(cov_vals)
            newest = max(newest, r.rec)
            continue
        await session.execute(
            text(
                """
                INSERT INTO video_watch_coverage (user_id, lesson_asset_id, organization_id, lesson_id,
                    covered_ranges,
                    covered_s, coverage_pct, duration_s, last_position_s, updated_at)
                VALUES (:u, :a, :o, :l, :cr, :cs, :pct, :dur, :pos, now())
                ON CONFLICT (user_id, lesson_asset_id) DO UPDATE SET covered_ranges = EXCLUDED.covered_ranges,
                    covered_s = EXCLUDED.covered_s, coverage_pct = EXCLUDED.coverage_pct,
                    duration_s = coalesce(EXCLUDED.duration_s, video_watch_coverage.duration_s),
                    lesson_id = coalesce(video_watch_coverage.lesson_id, EXCLUDED.lesson_id),
                    last_position_s = EXCLUDED.last_position_s, updated_at = now()
                """
            ).bindparams(bindparam("cr", type_=ARRAY(INT4RANGE))),
            {
                "u": r.user_id,
                "a": r.lesson_asset_id,
                "o": r.org,
                "l": r.lesson,
                "cr": [Range(round(a * 10), round(b * 10), bounds="[)") for a, b in merged],
                "cs": round(covered, 1),
                "pct": min(100.0, pct),
                "dur": round(dur) if dur else None,
                "pos": int(r.pos) if r.pos is not None else None,
            },
        )
        newest = max(newest, r.rec)
    result = {"assets": len(rows)}
    await _set_state(session, "video_coverage", newest, result)
    return result


# =========================================================================== security feed


async def security_feed_eligible(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Adults with an active ``security_monitoring`` consent; never synthetic, never minors."""
    flags = await _user_flags(session, user_id)
    if flags is None or flags[1] or flags[0] != "adult":
        return False
    return await consent_active(session, user_id, "security_monitoring")


async def run_security_feed(
    session: AsyncSession, *, day: date | None = None, now: datetime | None = None
) -> dict[str, Any]:
    now = now or utcnow()
    d = day or (ist_date(now) - timedelta(days=1))
    await system_context(session, "analytics.security_feed")
    # Withdrawn consent / minors / synthetic: delete any rows (<= 24 h after withdrawal).
    if _fs():
        from app.modules.analytics import fs_jobs

        existing: Any = [(u,) for u in await fs_jobs.feed_users()]
    else:
        existing = (
            await session.execute(text("SELECT DISTINCT user_id FROM security_activity_feed_daily"))
        ).all()
    removed = 0
    for (u,) in existing:
        if not await security_feed_eligible(session, u):
            if _fs():
                from app.modules.analytics import fs_raw

                await fs_raw.delete_user_docs(fs_raw.SECURITY_FEED, u)
            else:
                await session.execute(
                    text("DELETE FROM security_activity_feed_daily WHERE user_id = :u"), {"u": u}
                )
            removed += 1
    built = 0
    for u in await users_active_on(session, d):
        if not await security_feed_eligible(session, u):
            continue
        res, extra = await load_day_inputs(session, u, d, now=now)
        flags = extra["flags"]
        if _fs():
            from app.modules.analytics import fs_jobs

            await fs_jobs.feed_upsert(
                {
                    "user_id": u,
                    "activity_date": d,
                    "privacy_tier": "adult",
                    "active_devices": min(res.active_devices, 32767),
                    "multi_device_overlap_s": round(res.multi_device_overlap_s),
                    "max_concurrent_active_page_instances": min(res.max_concurrent_page_instances, 32767),
                    "active_hours_bitmap": res.active_hours_bitmap,
                    "implausible_day": res.implausible,
                    "plausibility_violations": {"implausible_day": 1} if res.implausible else {},
                    "clock_jump_count": flags.get("clock_jump", 0),
                    "large_skew_count": flags.get("large_skew", 0),
                    "feed_version": FEED_VERSION,
                }
            )
            built += 1
            continue
        await session.execute(
            text(
                """
                INSERT INTO security_activity_feed_daily (user_id, activity_date, privacy_tier,
                    active_devices,
                    multi_device_overlap_s, max_concurrent_active_page_instances, active_hours_bitmap,
                        implausible_day,
                    plausibility_violations, clock_jump_count, large_skew_count, feed_version, computed_at)
                VALUES (:u, :d, 'adult', :ad, :mdo, :mc, :hb, :imp, CAST(:pv AS jsonb), :cj, :ls, :fv, now())
                ON CONFLICT (user_id, activity_date) DO UPDATE SET active_devices = EXCLUDED.active_devices,
                    multi_device_overlap_s = EXCLUDED.multi_device_overlap_s,
                    max_concurrent_active_page_instances = EXCLUDED.max_concurrent_active_page_instances,
                    active_hours_bitmap = EXCLUDED.active_hours_bitmap,
                        implausible_day = EXCLUDED.implausible_day,
                    plausibility_violations = EXCLUDED.plausibility_violations,
                    clock_jump_count = EXCLUDED.clock_jump_count,
                        large_skew_count = EXCLUDED.large_skew_count,
                    feed_version = EXCLUDED.feed_version, computed_at = now()
                """
            ),
            {
                "u": u,
                "d": d,
                "ad": min(res.active_devices, 32767),
                "mdo": round(res.multi_device_overlap_s),
                "mc": min(res.max_concurrent_page_instances, 32767),
                "hb": res.active_hours_bitmap,
                "imp": res.implausible,
                "pv": json.dumps({"implausible_day": 1} if res.implausible else {}),
                "cj": flags.get("clock_jump", 0),
                "ls": flags.get("large_skew", 0),
                "fv": FEED_VERSION,
            },
        )
        built += 1
    result = {"built": built, "removed_users": removed, "day": str(d)}
    await _set_state(session, "security_feed", now, result)
    return result


# =========================================================================== retention


_PURGE: list[tuple[str, str, str, str]] = [
    # table, time column, key columns, retention key
    ("activity_heartbeats", "event_ts", "event_id, event_ts", "activity_heartbeats"),
    ("analytics_events", "event_ts", "event_id, event_ts", "analytics_events"),
    ("engagement_intervals", "started_at", "id, started_at", "engagement_intervals"),
    (
        "daily_learning_aggregates",
        "activity_date",
        "user_id, activity_date, entity_kind, entity_id",
        "aggregates",
    ),
    (
        "weekly_learning_aggregates",
        "iso_week_start",
        "user_id, iso_week_start, entity_kind, entity_id",
        "aggregates",
    ),
    ("video_watch_coverage", "updated_at", "user_id, lesson_asset_id", "aggregates"),
    ("topic_mastery", "updated_at", "user_id, topic_id", "aggregates"),
    (
        "security_activity_feed_daily",
        "activity_date",
        "user_id, activity_date",
        "security_activity_feed_daily",
    ),
    (
        "analytics_ingest_rejections",
        "hour_start",
        "hour_start, code, event_type",
        "analytics_ingest_rejections",
    ),
]


# BE-24: ``event_ts`` is client-derived (UUIDv7 time); a row is only purged once it is also old
# by server time, so a skewed device clock cannot get fresh rows deleted early.
_PURGE_SERVER_TIME: dict[str, str] = {
    "activity_heartbeats": " AND received_at < :cut",
    "analytics_events": " AND received_at < :cut",
}


async def run_retention_purge(
    session: AsyncSession, *, now: datetime | None = None, batch_size: int = 5000, max_batches: int = 200
) -> dict[str, int]:
    """§4.4 retention. Uses ``maint.drop_expired_partitions(parent)`` when that SECURITY
    DEFINER function exists and this role may execute it (partition drop); otherwise — the
    current state, since only DEFAULT partitions exist — batched ``DELETE`` by key."""
    now = now or utcnow()
    await system_context(session, "analytics.retention_purge")
    if _fs():
        return await _retention_purge_fs(session, now)
    can_drop = False
    # to_regprocedure() itself fails without USAGE on schema maint, so check that first.
    if (await session.execute(text("SELECT has_schema_privilege('maint', 'USAGE')"))).scalar():
        can_drop = bool(
            (
                await session.execute(
                    text(
                        "SELECT coalesce(has_function_privilege("
                        "to_regprocedure('maint.drop_expired_partitions(regclass)'), 'EXECUTE'), false)"
                    )
                )
            ).scalar()
        )
    out: dict[str, int] = {}
    for table, col, keys, rkey in _PURGE:
        cutoff = now - RETENTION[rkey]
        if can_drop and table in ("activity_heartbeats", "analytics_events", "engagement_intervals"):
            await session.execute(
                text("SELECT maint.drop_expired_partitions(CAST(:t AS regclass))"), {"t": table}
            )
        total = 0
        stmt = text(
            f"DELETE FROM {table} WHERE ({keys}) IN "  # noqa: S608 - identifiers are module constants
            f"(SELECT {keys} FROM {table} WHERE {col} < :cut{_PURGE_SERVER_TIME.get(table, '')} LIMIT :n)"
        )
        cut: Any = cutoff.date() if col in ("activity_date", "iso_week_start") else cutoff
        for _ in range(max_batches):
            res = await session.execute(stmt, {"cut": cut, "n": batch_size})
            n = int(getattr(res, "rowcount", 0) or 0)
            total += n
            if n < batch_size:
                break
        out[table] = total
    # Dirty marks for frozen days can never be processed.
    frozen_before = ist_date(now) - timedelta(days=TM.freeze_after_days)
    res = await session.execute(
        text("DELETE FROM analytics_dirty_days WHERE activity_date < :d"), {"d": frozen_before}
    )
    out["analytics_dirty_days"] = int(getattr(res, "rowcount", 0) or 0)
    await _set_state(session, "retention_purge", now, out)
    return out


async def _retention_purge_fs(session: AsyncSession, now: datetime) -> dict[str, int]:
    """``run_retention_purge`` on Firestore: same tables, cut-offs and result keys (raw rows live in
    batch documents; the batch TTL is the backstop)."""
    from app.modules.analytics import fs_jobs

    out: dict[str, int] = {}
    hb, ev = await fs_jobs.purge_batches(
        now - RETENTION["analytics_events"], now - RETENTION["activity_heartbeats"]
    )
    out["activity_heartbeats"], out["analytics_events"] = hb, ev
    for table, _col, _keys, rkey in _PURGE:
        if table in ("activity_heartbeats", "analytics_events"):
            continue
        out[table] = await fs_jobs.purge_older(table, now - RETENTION[rkey])
    out["analytics_dirty_days"] = await fs_jobs.purge_dirty_before(
        ist_date(now) - timedelta(days=TM.freeze_after_days)
    )
    await _set_state(session, "retention_purge", now, out)
    return out


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """Privacy provider (DM-12, s.8(7)): delete the user's rows from every identifiable
    analytics table (cohort rows are already non-identifying)."""
    await system_context(session, "analytics.privacy_erase")
    if _fs():
        from app.modules.analytics import fs_jobs

        return await fs_jobs.erase_user(user_id)
    out: dict[str, int] = {}
    for table in (
        "activity_heartbeats",
        "analytics_events",
        "engagement_intervals",
        "daily_learning_aggregates",
        "weekly_learning_aggregates",
        "video_watch_coverage",
        "topic_mastery",
        "security_activity_feed_daily",
        "analytics_dirty_days",
    ):
        res = await session.execute(
            text(f"DELETE FROM {table} WHERE user_id = :u"),  # noqa: S608 - constant identifiers
            {"u": user_id},
        )
        out[table] = int(getattr(res, "rowcount", 0) or 0)
    return out


# =========================================================================== CLI

_JOBS = {
    "outbox_consumer": None,
    "interval_builder": run_interval_builder,
    "video_coverage": run_video_coverage,
    "daily_aggregator": run_daily_aggregation,
    "rollups": run_rollups,
    "security_feed": run_security_feed,
    "retention_purge": run_retention_purge,
}


async def run_job(name: str) -> dict[str, Any]:
    from app.core.firestore.sqlstore import store_session

    started = _time.monotonic()
    # A Postgres transaction when the stack has Postgres; otherwise an in-memory transaction
    # (RLS settings only) committed on success: Firestore modules never touch Postgres.
    async with store_session() as session:
        if name == "outbox_consumer":
            from app.modules.analytics.consumer import consume_outbox

            await system_context(session, "analytics.outbox_consumer")
            result: dict[str, Any] = dict(await consume_outbox(session))
        else:
            fn = _JOBS[name]
            assert fn is not None
            result = await fn(session)
    log.info("analytics_job_done", job=name, ms=round((_time.monotonic() - started) * 1000), result=result)
    return result


def main(argv: list[str]) -> int:  # pragma: no cover - CLI
    if not argv or argv[0] not in _JOBS:
        print(f"usage: python -m app.modules.analytics.jobs <{'|'.join(_JOBS)}>", file=sys.stderr)
        return 2
    asyncio.run(run_job(argv[0]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
