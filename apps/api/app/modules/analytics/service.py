"""Ingest (ANL-01/02): validate, enrich, clamp, dedupe (analytics-event-schema §1, §5).

Order of checks per event (§5.3): known type + supported version, not server-only, purpose
permitted (consent + tier), UUIDv7 time within ±5 min of ``occurred_at``, ``effective_at``
within ``L_late``, payload schema, entitlement of entity refs, then plausibility (engaged
heartbeat cadence >= 10 s per page instance, video coverage clamp).

Identity (``user_id``, ``organization_id``, ``auth_session_id``, ``device_id``,
``privacy_tier``) comes from the principal only.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import ResourceType, check_access
from app.core.errors import ProblemError
from app.core.principal import Principal
from app.core.time import ist_date, to_rfc3339, utcnow
from app.modules.analytics import hooks
from app.modules.analytics.models import ActivityHeartbeat, AnalyticsEvent
from app.modules.analytics.params import (
    EVENT_CATALOGUE,
    MAX_BODY_BYTES,
    MAX_EVENT_BYTES,
    MAX_PAYLOAD_DEPTH,
    MAX_PAYLOAD_PROPS,
    MAX_PAYLOAD_STRING,
    MEASUREMENT_VERSION,
    MIN_ENGAGED_GAP_S,
    RATE_IP_PER_MIN,
    RATE_SESSION_BURST_10S,
    RATE_SESSION_PER_MIN,
    RATE_USER_PER_MIN,
    SUPPORTED_SCHEMA_VERSIONS,
    TM,
)
from app.modules.analytics.schemas import BatchIn, EventIn, HeartbeatPayload, parse_payload
from app.modules.analytics.timemodel import clamp_played_ranges

log = structlog.get_logger("app.analytics")


# --------------------------------------------------------------------------- helpers


def uuid7_time(event_id: str | uuid.UUID) -> datetime:
    """``event_ts``: the 48-bit ms timestamp of a UUIDv7 (CP-1)."""
    h = str(event_id).replace("-", "")
    return datetime.fromtimestamp(int(h[:12], 16) / 1000.0, UTC)


def _depth_ok(v: Any, depth: int = 1) -> bool:
    """Object nesting depth <= 3 (arrays such as ``played_ranges`` pairs add no depth) and
    strings <= 256 chars (§5.2)."""
    if isinstance(v, dict):
        if depth > MAX_PAYLOAD_DEPTH:
            return False
        return all(_depth_ok(x, depth + 1) for x in v.values())
    if isinstance(v, list):
        return len(v) <= 64 and all(_depth_ok(x, depth) for x in v)
    if isinstance(v, str):
        return len(v) <= MAX_PAYLOAD_STRING
    return True


def state_bits(visible: bool, focused: bool, input_recent: bool, media_playing: bool) -> int:
    return (
        (1 if visible else 0)
        | (2 if focused else 0)
        | (4 if input_recent else 0)
        | (8 if media_playing else 0)
    )


def bits_to_state(bits: int) -> tuple[bool, bool, bool, bool]:
    return bool(bits & 1), bool(bits & 2), bool(bits & 4), bool(bits & 8)


async def privacy_tier_of(session: AsyncSession, principal: Principal) -> str:
    if principal.privacy_tier in ("adult", "minor"):
        return principal.privacy_tier
    return "minor" if principal.is_minor else "adult"


async def consent_active(session: AsyncSession, user_id: uuid.UUID, purpose: str) -> bool:
    """Latest account-level consent row for ``purpose`` is ``granted``."""
    from app.modules.identity import public as idp

    acct = [
        c
        for c in await idp.consents_of(session, user_id)
        if c.purpose == purpose and c.context_ref is None and c.organization_id is None
    ]
    return bool(acct and acct[-1].action == "granted")


# --------------------------------------------------------------------------- rate limits


async def enforce_rate_limits(principal: Principal, client_ip: str | None) -> None:
    """Fixed-window counters approximating the §5.2 token buckets, via the shared
    ``app.core.ratelimit`` (keys under ``rl:anl:``). Every counter is incremented before the
    first exceeded one raises ``429``. Redis outages fail open (analytics is not a security
    control; the session gate still applies)."""
    from app.core import ratelimit as core_rl

    checks: list[tuple[str, core_rl.Rule]] = [
        (f"anl:s:{principal.session_id}", core_rl.Rule(RATE_SESSION_PER_MIN, 60)),
        (f"anl:sb:{principal.session_id}", core_rl.Rule(RATE_SESSION_BURST_10S, 10)),
        (f"anl:u:{principal.user_id}", core_rl.Rule(RATE_USER_PER_MIN, 60)),
    ]
    # Same counters and limits; the session's and the user's counters share one lms_kv document
    # per minute (a session always belongs to its user): one billed write instead of three.
    problems = await core_rl.check_colocated(
        checks, group=f"anl:u:{principal.user_id}", span_s=60, scope="user"
    )
    if client_ip:
        problems.append(
            await core_rl.check(f"anl:ip:{client_ip}", (core_rl.Rule(RATE_IP_PER_MIN, 60),), scope="user")
        )
    for problem in problems:
        if problem is not None:
            raise problem


# --------------------------------------------------------------------------- ingest


@dataclass
class _Ctx:
    principal: Principal
    privacy_tier: str
    received: datetime
    skew: timedelta
    product_ok: bool | None = None
    entitled: dict[tuple[str, uuid.UUID], bool] = field(default_factory=dict)
    org_cache: dict[tuple[Any, ...], uuid.UUID | None] = field(default_factory=dict)
    last_engaged: dict[uuid.UUID, datetime | None] = field(default_factory=dict)
    anchors: dict[uuid.UUID, tuple[datetime, int, datetime]] = field(default_factory=dict)
    prev_clock: dict[uuid.UUID, tuple[datetime, int]] = field(default_factory=dict)
    facts: dict[tuple[str, uuid.UUID], Any] = field(default_factory=dict)
    prev_samples: dict[uuid.UUID, list[datetime]] = field(default_factory=dict)
    stored_hbs: dict[uuid.UUID, list[Any]] = field(default_factory=dict)  # Firestore: per page


def _fs() -> bool:
    from app.core.firestore.backend import uses_firestore

    return uses_firestore("analytics")


async def _stored_heartbeats(ctx: _Ctx, page: uuid.UUID) -> list[Any]:
    """Firestore: the page instance's already-stored heartbeats (read once per batch)."""
    if page not in ctx.stored_hbs:
        from app.modules.analytics import fs_raw

        ctx.stored_hbs[page] = await fs_raw.page_heartbeats(ctx.principal.user_id, page)
    return ctx.stored_hbs[page]


class Rejected(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


@dataclass
class IngestResult:
    results: list[dict[str, Any]]
    accepted: int
    duplicate: int
    rejected: int
    credited_s: float


def parse_body(raw: bytes) -> BatchIn:
    if len(raw) > MAX_BODY_BYTES:
        raise ProblemError("payload_too_large", max_bytes=MAX_BODY_BYTES)
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ProblemError("validation_failed", 422, detail="Body is not valid JSON.") from e
    try:
        return BatchIn.model_validate(data)
    except ValidationError as e:
        errors = [
            {
                "field": ".".join(str(p) for p in err["loc"]) or "body",
                "code": err["type"],
                "message": err["msg"],
            }
            for err in e.errors()[:20]
        ]
        raise ProblemError("validation_failed", 422, detail="Batch schema violation.", errors=errors) from e


async def _product_permitted(session: AsyncSession, ctx: _Ctx) -> bool:
    if ctx.product_ok is None:
        ctx.product_ok = ctx.privacy_tier == "adult" and await consent_active(
            session, ctx.principal.user_id, "analytics_product"
        )
    return ctx.product_ok


async def _allowed(session: AsyncSession, ctx: _Ctx, rtype: ResourceType, rid: uuid.UUID) -> bool:
    key = (rtype, rid)
    if key not in ctx.entitled:
        decision = await check_access(session, ctx.principal, rtype, rid)
        ctx.entitled[key] = decision.allowed
    return ctx.entitled[key]


async def _lesson_course(session: AsyncSession, ctx: _Ctx, lesson: uuid.UUID) -> uuid.UUID | None:
    """The course of a lesson visible to the learner (RLS applies); ``None`` = unknown lesson."""
    key = ("lesson_course", lesson)
    if key not in ctx.facts:
        from app.modules.catalog import api as catalog_api

        ids = await catalog_api.course_ids_for_lessons(session, lesson_id=lesson)
        ctx.facts[key] = ids[0] if ids else None
    return ctx.facts[key]


async def _asset_lesson(session: AsyncSession, ctx: _Ctx, asset: uuid.UUID) -> uuid.UUID | None:
    key = ("asset_lesson", asset)
    if key not in ctx.facts:
        from app.modules.catalog import api as catalog_api

        found = (await catalog_api.get_assets(session, [asset])).get(asset)
        ctx.facts[key] = found.lesson_id if found else None
    return ctx.facts[key]


async def _asset_ok(session: AsyncSession, ctx: _Ctx, asset: uuid.UUID, lesson: uuid.UUID | None) -> bool:
    """BE-01/BE-13: a ``lesson_asset_id`` must exist, belong to the event's lesson (when one
    is named) and its lesson must be accessible to the learner."""
    owner = await _asset_lesson(session, ctx, asset)
    if owner is None or (lesson is not None and owner != lesson):
        return False
    return await _allowed(session, ctx, "lesson", owner)


async def _attempt_ok(session: AsyncSession, ctx: _Ctx, attempt: uuid.UUID, effective: datetime) -> bool:
    """BE-12: ``test_attempt_id`` counts only when it is the principal's own attempt and the
    event falls inside that attempt's server-recorded lifetime (started .. submitted or
    deadline); late delivery of genuine in-attempt samples stays valid."""
    key = ("attempt", attempt)
    if key not in ctx.facts:
        from app.modules.assessments import public as assessments

        ctx.facts[key] = await assessments.attempt_lifetime(session, attempt)
    fact = ctx.facts[key]
    if fact is None or fact[0] != ctx.principal.user_id:
        return False
    started, submitted, deadline = fact[1], fact[2], fact[3]
    slack = TM.uuid_time_tolerance
    if effective < started - slack:
        return False
    end = submitted or (deadline + _ATTEMPT_DEADLINE_GRACE if deadline is not None else None)
    return end is None or effective <= end + slack


_ATTEMPT_DEADLINE_GRACE = timedelta(minutes=5)


async def _entitled(session: AsyncSession, ctx: _Ctx, ev: EventIn, effective: datetime) -> bool:
    """§5.3 step 3 / §5.5(5): every content reference must be accessible to the learner and
    consistent with the others (BE-13); unknown or foreign ids reject the event."""
    ent = ev.entity
    if ent is None:
        return True
    course = ent.uuid("course_id")
    lesson = ent.uuid("lesson_id")
    if course is not None and not await _allowed(session, ctx, "course", course):
        return False
    if lesson is not None:
        if not await _allowed(session, ctx, "lesson", lesson):
            return False
        if course is not None and await _lesson_course(session, ctx, lesson) != course:
            return False
    checks: list[tuple[ResourceType, str]] = [
        ("coding_problem", "coding_problem_id"),
        ("test", "test_id"),
        ("company_path", "company_path_id"),
    ]
    for rtype, field_name in checks:
        rid = ent.uuid(field_name)
        if rid is not None and not await _allowed(session, ctx, rtype, rid):
            return False
    asset = ent.uuid("lesson_asset_id")
    if asset is not None and not await _asset_ok(session, ctx, asset, lesson):
        return False
    attempt = ent.uuid("test_attempt_id")
    if attempt is not None and not await _attempt_ok(session, ctx, attempt, effective):
        return False
    return True


async def _org_for(session: AsyncSession, ctx: _Ctx, ev: EventIn) -> uuid.UUID | None:
    ent = ev.entity
    ref = hooks.EntityRef(
        course_id=ent.uuid("course_id") if ent else None,
        lesson_id=ent.uuid("lesson_id") if ent else None,
        batch_id=ent.uuid("batch_id") if ent else None,
        test_attempt_id=ent.uuid("test_attempt_id") if ent else None,
    )
    key = (ref.course_id, ref.lesson_id, ref.batch_id, ref.test_attempt_id)
    if key not in ctx.org_cache:
        ctx.org_cache[key] = await hooks.resolve_org(session, ctx.principal, ref)
    return ctx.org_cache[key]


async def _last_engaged(
    session: AsyncSession, ctx: _Ctx, page: uuid.UUID, event_id: uuid.UUID
) -> datetime | None:
    if page not in ctx.last_engaged and _fs():
        hbs = await _stored_heartbeats(ctx, page)
        ctx.last_engaged[page] = max(
            (h.effective_at for h in hbs if h.kind == "engaged" and h.event_id != event_id), default=None
        )
    if page not in ctx.last_engaged:
        # Excludes the event itself so a retried sample is reported as a duplicate, not capped.
        row = (
            await session.execute(
                text(
                    "SELECT max(effective_at) FROM activity_heartbeats WHERE page_instance_id = :p "
                    "AND user_id = :u AND kind = 'engaged' AND event_id <> :e"
                ),
                {"p": page, "u": ctx.principal.user_id, "e": event_id},
            )
        ).first()
        ctx.last_engaged[page] = row[0] if row else None
    return ctx.last_engaged[page]


def _effective(ctx: _Ctx, ev: EventIn, page: uuid.UUID, flags: list[str]) -> datetime:
    """§1.3: effective_at = min(occurred_at + skew, received_at); clock-jump re-anchoring on
    ``mono_ms`` within a page instance (anchor = first event of the page in this batch)."""
    occurred = ev.occurred_at.astimezone(UTC)
    eff = min(occurred + ctx.skew, ctx.received)
    prev = ctx.prev_clock.get(page)
    if prev is not None:
        d_occ = (occurred - prev[0]).total_seconds() * 1000
        d_mono = ev.mono_ms - prev[1]
        if abs(d_occ - d_mono) > TM.clock_jump_ms:
            flags.append("clock_jump")
    ctx.prev_clock[page] = (occurred, ev.mono_ms)
    anchor = ctx.anchors.get(page)
    if anchor is None:
        ctx.anchors[page] = (eff, ev.mono_ms, occurred)
    elif "clock_jump" in flags:
        eff = min(anchor[0] + timedelta(milliseconds=ev.mono_ms - anchor[1]), ctx.received)
    return eff


async def ingest_batch(
    session: AsyncSession,
    principal: Principal,
    batch: BatchIn,
    *,
    now: datetime | None = None,
) -> IngestResult:
    received = now or utcnow()
    ctx = _Ctx(
        principal=principal,
        privacy_tier=await privacy_tier_of(session, principal),
        received=received,
        skew=received - batch.sent_at.astimezone(UTC),
    )
    large_skew = abs(ctx.skew.total_seconds() * 1000) > TM.large_skew_ms
    results: list[dict[str, Any]] = []
    hb_rows: list[dict[str, Any]] = []
    ev_rows: list[dict[str, Any]] = []
    rejections: dict[tuple[str, str], int] = defaultdict(int)
    dirty: set[date] = set()
    credit_by_id: dict[str, float] = {}
    seen: set[str] = set()

    for raw in batch.events:
        event_id = str(raw.get("event_id", ""))[:64]
        etype = str(raw.get("event_type", "_unknown"))[:48]
        if event_id in seen:  # same event twice in one batch: the second is a duplicate
            results.append({"event_id": event_id, "status": "duplicate"})
            continue
        seen.add(event_id)
        try:
            row, store, credit = await _process_event(session, ctx, raw, large_skew)
            results.append({"event_id": event_id, "status": "pending"})
            if store == "heartbeats":
                hb_rows.append(row)
            else:
                ev_rows.append(row)
            credit_by_id[row["event_id"].hex] = credit
            if "late" in row["ingest_flags"]:
                dirty.add(ist_date(row["effective_at"]))
        except Rejected as r:
            results.append({"event_id": event_id, "status": "rejected", "code": r.code})
            known = etype if etype in EVENT_CATALOGUE else "_unknown"
            rejections[(r.code, known)] += 1

    inserted: set[str] = set()
    if _fs() and (hb_rows or ev_rows):
        from app.modules.analytics import fs_raw

        inserted = await fs_raw.insert_batch(principal.user_id, received, hb_rows, ev_rows)
        hb_rows, ev_rows = [], []
    if hb_rows:
        stmt = (
            pg_insert(ActivityHeartbeat)
            .values(hb_rows)
            .on_conflict_do_nothing(index_elements=["event_id", "event_ts"])
            .returning(ActivityHeartbeat.event_id)
        )
        inserted |= {r[0].hex for r in (await session.execute(stmt)).all()}
    if ev_rows:
        stmt = (
            pg_insert(AnalyticsEvent)
            .values(ev_rows)
            .on_conflict_do_nothing(index_elements=["event_id", "event_ts"])
            .returning(AnalyticsEvent.event_id)
        )
        inserted |= {r[0].hex for r in (await session.execute(stmt)).all()}

    accepted = duplicate = rejected = 0
    credited = 0.0
    for res in results:
        if res["status"] == "rejected":
            rejected += 1
            continue
        if res["status"] == "duplicate":
            duplicate += 1
            continue
        key = uuid.UUID(res["event_id"]).hex
        if key in inserted:
            res["status"] = "accepted"
            accepted += 1
            credited += credit_by_id.get(key, 0.0)
        else:
            res["status"] = "duplicate"
            duplicate += 1

    if rejections and _fs():
        from app.modules.analytics import fs_raw

        await fs_raw.add_rejections(received.replace(minute=0, second=0, microsecond=0), dict(rejections))
        rejections = defaultdict(int)
    if rejections:
        hour = received.replace(minute=0, second=0, microsecond=0)
        for (code, etype), n in rejections.items():
            await session.execute(
                text(
                    "INSERT INTO analytics_ingest_rejections (hour_start, code, event_type, count) "
                    "VALUES (:h, :c, :t, :n) ON CONFLICT (hour_start, code, event_type) "
                    "DO UPDATE SET count = analytics_ingest_rejections.count + EXCLUDED.count"
                ),
                {"h": hour, "c": code, "t": etype, "n": n},
            )
    for d in dirty:
        await mark_dirty(session, principal.user_id, d, "late_event")
    return IngestResult(results, accepted, duplicate, rejected, credited)


async def mark_dirty(session: AsyncSession, user_id: uuid.UUID, d: date, reason: str) -> None:
    if _fs():
        from app.modules.analytics import fs_raw

        await fs_raw.mark_dirty(user_id, d, reason)
        return
    await session.execute(
        text(
            "INSERT INTO analytics_dirty_days (user_id, activity_date, reason) VALUES (:u, :d, :r) "
            "ON CONFLICT (user_id, activity_date) DO UPDATE SET marked_at = now()"
        ),
        {"u": user_id, "d": d, "r": reason},
    )


async def _process_event(
    session: AsyncSession, ctx: _Ctx, raw: dict[str, Any], large_skew: bool
) -> tuple[dict[str, Any], str, float]:
    if not isinstance(raw, dict):
        raise Rejected("invalid_payload")
    if len(json.dumps(raw, separators=(",", ":"), default=str).encode()) > MAX_EVENT_BYTES:
        raise Rejected("payload_too_large")
    payload = raw.get("payload")
    if isinstance(payload, dict) and (len(payload) > MAX_PAYLOAD_PROPS or not _depth_ok(payload)):
        raise Rejected("payload_too_large")
    try:
        ev = EventIn.model_validate(raw)
    except ValidationError as e:
        raise Rejected("invalid_payload") from e

    spec = EVENT_CATALOGUE.get(ev.event_type)
    if spec is None:
        raise Rejected("unknown_event_type")
    if spec.server_only:
        raise Rejected("server_only_event")
    if ev.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise Rejected("unsupported_schema_version")
    if spec.purpose == "product" and not await _product_permitted(session, ctx):
        raise Rejected("purpose_not_permitted")

    event_ts = uuid7_time(ev.event_id)
    occurred = ev.occurred_at.astimezone(UTC)
    if abs(event_ts - occurred) > TM.uuid_time_tolerance:
        raise Rejected("uuid_time_mismatch")
    if event_ts + ctx.skew > ctx.received + TM.uuid_time_tolerance:
        raise Rejected("event_in_future")
    if event_ts < ctx.received - TM.late_window - TM.uuid_time_tolerance:
        # BE-24: the UUIDv7 time is the partition/retention key; it may not be older than any
        # genuinely late event could be, whatever the client's clock and ``sent_at`` claim.
        raise Rejected("event_too_old")
    page = uuid.UUID(ev.page_instance_id)
    flags: list[str] = []
    effective = _effective(ctx, ev, page, flags)
    if effective < ctx.received - TM.late_window:
        raise Rejected("event_too_old")

    model = parse_payload(ev.event_type, ev.schema_version, ev.payload)
    if model is None:
        raise Rejected("invalid_payload")
    if not await _entitled(session, ctx, ev, effective):
        raise Rejected("entity_not_entitled")

    if large_skew:
        flags.append("large_skew")
    if effective < ctx.received - TM.late_flag_after:
        flags.append("late")
    org = await _org_for(session, ctx, ev)
    ent = ev.entity
    common: dict[str, Any] = {
        "event_id": uuid.UUID(ev.event_id),
        "event_ts": event_ts,
        "user_id": ctx.principal.user_id,
        "organization_id": org,
        "auth_session_id": ctx.principal.session_id,
        "device_id": ctx.principal.device_id,
        "tab_id": uuid.UUID(ev.tab_id),
        "page_instance_id": page,
        "seq": ev.seq,
        "effective_at": effective,
        "received_at": ctx.received,
        "course_id": ent.uuid("course_id") if ent else None,
        "lesson_id": ent.uuid("lesson_id") if ent else None,
        "lesson_asset_id": ent.uuid("lesson_asset_id") if ent else None,
        "topic_id": ent.uuid("topic_id") if ent else None,
        "question_id": ent.uuid("question_id") if ent else None,
        "test_attempt_id": ent.uuid("test_attempt_id") if ent else None,
        "coding_problem_id": ent.uuid("coding_problem_id") if ent else None,
        "privacy_tier": ctx.privacy_tier,
    }

    if spec.store == "heartbeats":
        assert isinstance(model, HeartbeatPayload)
        hb = model
        if hb.kind == "engaged":
            last = await _last_engaged(session, ctx, page, common["event_id"])
            if last is not None and abs((effective - last).total_seconds()) < MIN_ENGAGED_GAP_S:
                raise Rejected("rate_capped")
            ctx.last_engaged[page] = effective
        ranges: list[Any] | None = None
        asset = common["lesson_asset_id"]
        rate = None
        position = None
        if hb.media is not None:
            if hb.media.lesson_asset_id:
                media_asset = uuid.UUID(hb.media.lesson_asset_id)
                if media_asset != asset and not await _asset_ok(
                    session, ctx, media_asset, common["lesson_id"]
                ):
                    raise Rejected("entity_not_entitled")
                asset = media_asset
            rate = hb.media.rate
            position = hb.media.position_s
            if hb.media.played_ranges:
                pairs = [(float(a), float(b)) for a, b in hb.media.played_ranges]
                wall = await _credit_wall_s(
                    session, ctx, page, common["event_id"], effective, hb.sample_interval_ms / 1000.0
                )
                pairs, clamped = clamp_played_ranges(pairs, wall, rate)
                if clamped:
                    flags.append("implausible_clamped")
                from sqlalchemy.dialects.postgresql import Range

                ranges = [Range(round(a * 10), round(b * 10), bounds="[)") for a, b in pairs if b > a]
        st = hb.state
        credit = 0.0
        if hb.kind == "engaged" and st.visible and (st.input_recent or st.media_playing):
            credit = min(hb.active_ms / 1000.0, TM.c_max_s)
        row = {
            **common,
            "lesson_asset_id": asset,
            "kind": hb.kind,
            "active_ms": hb.active_ms if hb.kind == "engaged" else 0,
            "sample_interval_ms": hb.sample_interval_ms,
            "state_bits": state_bits(st.visible, st.focused, st.input_recent, st.media_playing),
            "surface": ev.surface or "other",
            "route": ev.route,
            "media_position_s": position,
            "media_rate": rate,
            "played_ranges": ranges,
            "edit_ops": hb.editor.edit_ops if hb.editor else None,
            "editor_focused": hb.editor.focused if hb.editor else None,
            "scroll_depth_pct": hb.reading.max_scroll_depth_pct if hb.reading else None,
            "input_events": hb.input_events,
            "ingest_flags": sorted(set(flags)),
        }
        _remember_sample(ctx, page, effective)
        return row, "heartbeats", credit

    row = {
        **common,
        "event_type": ev.event_type,
        "schema_version": ev.schema_version,
        "source": "client",
        "purpose": spec.purpose,
        "route": ev.route,
        "surface": ev.surface,
        "occurred_at": occurred,
        "skew_ms": int(ctx.skew.total_seconds() * 1000),
        "ingest_flags": sorted(set(flags)),
        "measurement_version": MEASUREMENT_VERSION,
        "payload": _payload_json(model),
    }
    _remember_sample(ctx, page, effective)
    return row, "events", 0.0


def _remember_sample(ctx: _Ctx, page: uuid.UUID, effective: datetime) -> None:
    ctx.prev_samples.setdefault(page, []).append(effective)


async def _credit_wall_s(
    session: AsyncSession,
    ctx: _Ctx,
    page: uuid.UUID,
    event_id: uuid.UUID,
    effective: datetime,
    claimed_s: float,
) -> float:
    """BE-01: ``credit_wall_s`` for the §3.9 clamp is the server-observed time since the
    previous sample of the same page instance (this batch or already stored), capped at
    ``C_max``. The client's ``sample_interval_ms`` is only a further upper bound."""
    prev = max((t for t in ctx.prev_samples.get(page, []) if t < effective), default=None)
    if _fs():
        stored = max(
            (
                h.effective_at
                for h in await _stored_heartbeats(ctx, page)
                if h.event_id != event_id and h.effective_at < effective
            ),
            default=None,
        )
        if stored is not None and (prev is None or stored > prev):
            prev = stored
        wall = claimed_s if prev is None else (effective - prev).total_seconds()
        return max(0.0, min(wall, claimed_s, TM.c_max_s))
    row = (
        await session.execute(
            text(
                "SELECT max(effective_at) FROM activity_heartbeats WHERE page_instance_id = :p "
                "AND user_id = :u AND event_id <> :e AND effective_at < :t"
            ),
            {"p": page, "u": ctx.principal.user_id, "e": event_id, "t": effective},
        )
    ).first()
    if row and row[0] is not None and (prev is None or row[0] > prev):
        prev = row[0]
    wall = claimed_s if prev is None else (effective - prev).total_seconds()
    return max(0.0, min(wall, claimed_s, TM.c_max_s))


def _payload_json(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


def ingest_response(res: IngestResult, now: datetime | None = None) -> dict[str, Any]:
    return {
        "accepted": res.accepted,
        "duplicate": res.duplicate,
        "rejected": res.rejected,
        "results": res.results,
        "server_time": to_rfc3339(now or utcnow()),
        "config_version": MEASUREMENT_VERSION,
    }


async def after_ingest(principal: Principal, res: IngestResult) -> None:
    """``x-td-idle: engaged_only``: slide the idle timer only when engagement was credited."""
    if res.credited_s <= 0:
        return
    try:
        await hooks.touch_engaged(principal.session_id)
    except Exception as e:  # pragma: no cover - sessions module failure must not lose events
        log.warning("analytics_touch_engaged_failed", error=type(e).__name__)


# --------------------------------------------------------------------------- server events


async def insert_server_event(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    event_type: str,
    user_id: uuid.UUID,
    privacy_tier: str,
    occurred_at: datetime,
    payload: dict[str, Any],
    organization_id: uuid.UUID | None = None,
    entity: dict[str, uuid.UUID | None] | None = None,
    auth_session_id: uuid.UUID | None = None,
) -> bool:
    """Write a ``source='server'`` row (outbox consumer, CP-8). Idempotent on event_id."""
    ent = entity or {}
    values: dict[str, Any] = dict(
        event_id=event_id,
        event_ts=uuid7_time(event_id),
        event_type=event_type,
        schema_version=1,
        source="server",
        purpose="learning",
        user_id=user_id,
        organization_id=organization_id,
        auth_session_id=auth_session_id,
        occurred_at=occurred_at,
        received_at=utcnow(),
        effective_at=occurred_at,
        skew_ms=0,
        privacy_tier=privacy_tier,
        ingest_flags=[],
        measurement_version=MEASUREMENT_VERSION,
        payload=payload,
        **{
            k: ent.get(k)
            for k in (
                "course_id",
                "lesson_id",
                "topic_id",
                "question_id",
                "test_attempt_id",
                "coding_problem_id",
            )
        },
    )
    if _fs():
        from app.modules.analytics import fs_raw

        # one batch document per server event, id = the event id (idempotent create)
        return bool(
            await fs_raw.insert_batch(user_id, values["received_at"], [], [values], doc_id=event_id.hex)
        )
    stmt = (
        pg_insert(AnalyticsEvent)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["event_id", "event_ts"])
        .returning(AnalyticsEvent.event_id)
    )
    return (await session.execute(stmt)).first() is not None
