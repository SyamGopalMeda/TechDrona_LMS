"""Domain-event consumer (CP-7, CP-8).

Primary path: ``on_outbox_event`` is registered with ``app.core.outbox.register_handler`` for
every type in ``HANDLED_TYPES`` (``register_outbox_handlers``), so the core relay delivers
events within seconds, in the relay's transaction (exactly-once with ``dispatched_at``).

Fallback (kept on purpose, beat every 10 min): ``consume_outbox`` reads ``outbox_events`` with
its own cursor + look-back and skips ids already in ``analytics_consumed_events``. It catches
events the relay will never deliver to analytics: events marked dispatched by a process that
had no analytics handler registered (relay treats "no handler" as done), and dead-lettered
events (``attempts >= TD_OUTBOX_MAX_ATTEMPTS``) once the cause is fixed. Both paths record the
event id in ``analytics_consumed_events`` and ``insert_server_event`` is idempotent per event
id, so running both never double-counts mastery or time.

Payload contracts (ids only, never PII; producers: placement, assessments, coding, learning,
sessions, identity):

* ``practice.answered`` / ``practice.answer_submitted``: ``user_id``, ``question_id``,
  ``question_version_id?``, ``topic_ids`` (primary first) or ``topic_id``, ``is_correct``
  (null = skipped), ``attempt_no``, ``difficulty`` (easy|medium|hard), ``after_solution``,
  ``after_hint``, ``answered_at?``, ``practice_response_id?``, ``organization_id?``
  (placement emits ``topic_id`` + ``solution_viewed``; both shapes are accepted)
* ``attempt.started`` (assessments): ``user_id``, ``attempt_id``, ``started_at``, ``deadline_at``
* ``attempt.submitted``: ``user_id``, ``attempt_id``, ``submitted_at``, ``auto`` (true ->
  ``assessment.auto_submitted``) — with ``attempt.started`` this gives M4
* ``attempt.scored``: ``user_id``, ``attempt_id``, ``topic_scores`` ``[{topic_id, correct,
  total}]`` (or per-question ``responses`` ``[{topic_ids, is_correct, difficulty?,
  question_version_id?}]``) -> mastery updates with test weight 1.0
* ``submission.judged`` (coding): ``user_id``, ``problem_id``, ``mode`` (run|submit), ``verdict``
* ``coding.run`` / ``coding.submit`` / ``coding.submission_judged``, ``learning.*``,
  ``practice.hint_viewed`` / ``practice.solution_viewed``: ``user_id`` + the §2 payload +
  entity ids (``course_id``, ``lesson_id``, ``topic_id``, ``question_id``, ``coding_problem_id``)
* ``session.ended``: ``user_id``, ``session_id`` (auth_sessions.id), ``ended_at``
* ``consent.changed``: ``user_id``, ``purpose``, ``action`` — withdrawal of
  ``security_monitoring`` deletes the user's feed rows immediately (<= 24 h rule).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import ist_date, utcnow
from app.modules.analytics import mastery
from app.modules.analytics.service import insert_server_event, mark_dirty

log = structlog.get_logger("app.analytics.consumer")

PRACTICE_TYPES = ("practice.answered", "practice.answer_submitted")
ATTEMPT_DONE_TYPES = ("attempt.scored", "assessment.attempt_submitted", "assessment.auto_submitted")
# Producer event names (assessments/coding modules) -> stored analytics event types.
ALIASES = {
    "attempt.started": "assessment.attempt_started",
    "attempt.submitted": "assessment.attempt_submitted",
    "submission.judged": "coding.submission_judged",
}
PASSTHROUGH_TYPES = (
    "assessment.attempt_started",
    "assessment.attempt_resumed",
    "assessment.section_entered",
    "assessment.answer_saved",
    "practice.hint_viewed",
    "practice.solution_viewed",
    "coding.run",
    "coding.submit",
    "coding.submission_judged",
    "learning.lesson_started",
    "learning.lesson_completed",
    "learning.course_completed",
    "learning.certificate_issued",
    "learning.resource_downloaded",
    "learning.assignment_submitted",
)
HANDLED_TYPES = (
    *PRACTICE_TYPES,
    *ATTEMPT_DONE_TYPES,
    *PASSTHROUGH_TYPES,
    *ALIASES,
    "session.ended",
    "consent.changed",
)


def normalize(event_type: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Map producer payload shapes onto the analytics catalogue (§2) without losing ids."""
    p = dict(p)
    if p.get("attempt_id") and not p.get("test_attempt_id"):
        p["test_attempt_id"] = p["attempt_id"]
    if p.get("problem_id") and not p.get("coding_problem_id"):
        p["coding_problem_id"] = p["problem_id"]
    if p.get("lesson_key") and not p.get("lesson_id"):
        p["lesson_id"] = p["lesson_key"]
    if "solution_viewed" in p and "after_solution" not in p:
        p["after_solution"] = p["solution_viewed"]
    if "hint_used" in p and "after_hint" not in p:
        p["after_hint"] = p["hint_used"]
    if event_type == "attempt.submitted" and p.get("auto"):
        return "assessment.auto_submitted", p
    if event_type == "submission.judged":
        mode = p.get("mode")
        return ("coding.run" if mode == "run" else "coding.submission_judged"), p
    return ALIASES.get(event_type, event_type), p


_ENTITY_KEYS = ("course_id", "lesson_id", "topic_id", "question_id", "test_attempt_id", "coding_problem_id")


def _uuid(v: Any) -> uuid.UUID | None:
    if v is None or v == "":
        return None
    try:
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    except ValueError:
        return None


def _ts(v: Any, default: datetime) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    if isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=UTC)
        except ValueError:
            return default
    return default


def _topics(p: dict[str, Any]) -> tuple[uuid.UUID, ...]:
    raw = p.get("topic_ids") or ([p["topic_id"]] if p.get("topic_id") else [])
    return tuple(t for t in (_uuid(x) for x in raw) if t is not None)


def _fs() -> bool:
    from app.core.firestore.backend import uses_firestore

    return uses_firestore("analytics")


async def _user(session: AsyncSession, user_id: uuid.UUID) -> tuple[str, bool] | None:
    from app.modules.identity import public as idp

    u = await idp.get_user(session, user_id)
    return (u.privacy_tier, bool(u.is_synthetic)) if u is not None else None


def _safe_payload(p: dict[str, Any]) -> dict[str, Any]:
    """Keep ids, numbers, booleans and short codes only (no free text) — <= 24 props."""
    out: dict[str, Any] = {}
    for k, v in p.items():
        if k in ("user_id", "responses") or k in _ENTITY_KEYS:
            continue
        if isinstance(v, bool | int | float) or v is None:
            out[k] = v
        elif isinstance(v, str) and len(v) <= 64:
            out[k] = v
        elif isinstance(v, dict) and k == "section_scores":
            out[k] = {str(a)[:64]: b for a, b in list(v.items())[:16] if isinstance(b, int | float)}
        if len(out) >= 24:
            break
    return out


async def handle_domain_event(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: datetime,
    organization_id: uuid.UUID | None = None,
) -> bool:
    """Process one domain event (idempotent per ``event_id``). Returns True if applied."""
    event_type, p = normalize(event_type, payload or {})
    if event_type == "consent.changed":
        uid = _uuid(p.get("user_id"))
        if uid and p.get("purpose") == "security_monitoring" and p.get("action") == "withdrawn" and _fs():
            from app.modules.analytics import fs_raw

            await fs_raw.delete_user_docs(fs_raw.SECURITY_FEED, uid)
        elif uid and p.get("purpose") == "security_monitoring" and p.get("action") == "withdrawn":
            await session.execute(
                text("DELETE FROM security_activity_feed_daily WHERE user_id = :u"), {"u": uid}
            )
        return True
    uid = _uuid(p.get("user_id"))
    if uid is None:
        log.warning("analytics_event_without_user", event_type=event_type)
        return False
    user = await _user(session, uid)
    if user is None:
        return False
    tier, _synthetic = user
    org = _uuid(p.get("organization_id")) or organization_id
    entity = {k: _uuid(p.get(k)) for k in _ENTITY_KEYS}

    if event_type == "session.ended":
        sid = _uuid(p.get("session_id") or p.get("auth_session_id"))
        ended = _ts(p.get("ended_at"), occurred_at)
        await insert_server_event(
            session,
            event_id=event_id,
            event_type="session.ended",
            user_id=uid,
            privacy_tier=tier,
            occurred_at=ended,
            payload={"reason": str(p.get("reason", ""))[:32]},
            auth_session_id=sid,
        )
        return True

    if event_type in PRACTICE_TYPES:
        topics = _topics(p)
        entity["topic_id"] = entity["topic_id"] or (topics[0] if topics else None)
        at = _ts(p.get("answered_at"), occurred_at)
        fresh = await insert_server_event(
            session,
            event_id=event_id,
            event_type="practice.answer_submitted",
            user_id=uid,
            privacy_tier=tier,
            occurred_at=at,
            payload=_safe_payload(p),
            organization_id=org,
            entity=entity,
        )
        if fresh:
            await mastery.apply_response(
                session,
                mastery.ScoredResponse(
                    user_id=uid,
                    topic_ids=topics,
                    correct=None if p.get("is_correct") is None else bool(p.get("is_correct")),
                    difficulty=p.get("difficulty"),
                    source="practice",
                    attempt_no=int(p.get("attempt_no") or 1),
                    after_solution=bool(p.get("after_solution")),
                    after_hint=bool(p.get("after_hint")),
                    at=at,
                    question_version_id=_uuid(p.get("question_version_id")),
                    organization_id=org,
                ),
            )
            await mark_dirty(session, uid, ist_date(at), "server_event")
        return fresh

    if event_type in ATTEMPT_DONE_TYPES:
        at = _ts(p.get("submitted_at"), occurred_at)
        stored_type = "assessment.attempt_scored" if event_type == "attempt.scored" else event_type
        fresh = await insert_server_event(
            session,
            event_id=event_id,
            event_type=stored_type,
            user_id=uid,
            privacy_tier=tier,
            occurred_at=at,
            payload=_safe_payload(p),
            organization_id=org,
            entity=entity,
        )
        if fresh:
            for resp in p.get("responses") or []:
                if not isinstance(resp, dict):
                    continue
                await mastery.apply_response(
                    session,
                    mastery.ScoredResponse(
                        user_id=uid,
                        topic_ids=_topics(resp),
                        correct=None if resp.get("is_correct") is None else bool(resp.get("is_correct")),
                        difficulty=resp.get("difficulty"),
                        source="test",
                        at=at,
                        question_version_id=_uuid(resp.get("question_version_id")),
                        organization_id=org,
                    ),
                )
            # assessments emits per-topic aggregates: {topic_id, correct, total}
            for ts in [] if p.get("responses") else (p.get("topic_scores") or []):
                topic = _uuid(ts.get("topic_id")) if isinstance(ts, dict) else None
                if topic is None:
                    continue
                total, correct = int(ts.get("total") or 0), int(ts.get("correct") or 0)
                for i in range(min(total, 200)):
                    await mastery.apply_response(
                        session,
                        mastery.ScoredResponse(
                            user_id=uid,
                            topic_ids=(topic,),
                            correct=i < correct,
                            difficulty=None,
                            source="test",
                            at=at,
                            organization_id=org,
                        ),
                    )
            started = _ts(p.get("started_at"), at)
            d = ist_date(started)
            while d <= ist_date(at):
                await mark_dirty(session, uid, d, "server_event")
                d += timedelta(days=1)
        return fresh

    if event_type in PASSTHROUGH_TYPES:
        at = _ts(
            p.get("started_at") if event_type == "assessment.attempt_started" else p.get("occurred_at"),
            occurred_at,
        )
        fresh = await insert_server_event(
            session,
            event_id=event_id,
            event_type=event_type,
            user_id=uid,
            privacy_tier=tier,
            occurred_at=at,
            payload=_safe_payload(p),
            organization_id=org,
            entity=entity,
        )
        if fresh:
            await mark_dirty(session, uid, ist_date(at), "server_event")
        return fresh
    return False


async def _already_consumed(session: AsyncSession, event_id: uuid.UUID) -> bool:
    if _fs():
        from app.modules.analytics import fs_raw

        return await fs_raw.is_consumed(event_id)
    row = (
        await session.execute(
            text("SELECT 1 FROM analytics_consumed_events WHERE outbox_event_id = :i"), {"i": event_id}
        )
    ).first()
    return row is not None


async def on_outbox_event(session: AsyncSession, msg: Any) -> None:
    """``app.core.outbox`` handler (``msg``: ``OutboxMessage``); runs in the relay transaction."""
    if await _already_consumed(session, msg.id):
        return
    await handle_domain_event(
        session,
        event_id=msg.id,
        event_type=msg.event_type,
        payload=msg.payload or {},
        occurred_at=msg.occurred_at,
        organization_id=msg.organization_id,
    )
    if _fs():
        from app.modules.analytics import fs_raw

        await fs_raw.mark_consumed(msg.id, msg.event_type)
        return
    await session.execute(
        text(
            "INSERT INTO analytics_consumed_events (outbox_event_id, event_type) VALUES (:i, :t) "
            "ON CONFLICT DO NOTHING"
        ),
        {"i": msg.id, "t": msg.event_type},
    )


async def _consumed_ids(session: AsyncSession, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of ``ids`` this module already consumed (``analytics_consumed_events``)."""
    if not ids:
        return set()
    if _fs():
        from app.modules.analytics import fs_raw

        return {i for i in ids if await fs_raw.is_consumed(i)}
    rows = await session.execute(
        text("SELECT outbox_event_id FROM analytics_consumed_events WHERE outbox_event_id = ANY(:ids)"),
        {"ids": ids},
    )
    return {r[0] for r in rows.all()}


async def unconsumed_events(session: AsyncSession, *, since: datetime, limit: int) -> list[Any]:
    """Outbox events of ``HANDLED_TYPES`` after ``since`` that this module has not consumed yet,
    ordered ``(occurred_at, id)``, at most ``limit``: the old ``... AND NOT EXISTS (consumed)
    ORDER BY occurred_at, id LIMIT :n``. Read through ``app.core.outbox.read_events`` (either
    store), paged by keyset until ``limit`` unconsumed events are found or the outbox ends."""
    from app.core.outbox import read_events

    out: list[Any] = []
    after: tuple[datetime, uuid.UUID] | None = None
    while len(out) < limit:
        page = await read_events(session, since=since, event_types=HANDLED_TYPES, limit=limit, after=after)
        if not page:
            break
        done = await _consumed_ids(session, [r.id for r in page])
        out += [r for r in page if r.id not in done]
        if len(page) < limit:
            break
        after = (page[-1].occurred_at, page[-1].id)
    return out[:limit]


async def _consume_outbox_fs(session: AsyncSession, *, limit: int, lookback: timedelta) -> dict[str, int]:
    """``consume_outbox`` on Firestore: the core outbox documents (``TD_STORE_CORE=firestore``),
    the consumed marks and the job watermark live in Firestore; same order, limit and result."""
    from app.modules.analytics import fs_raw

    wm = await fs_raw.get_watermark("outbox_consumer")
    since = (wm or datetime(1970, 1, 1, tzinfo=UTC)) - lookback
    rows = await unconsumed_events(session, since=since, limit=limit)
    applied = skipped = 0
    newest: datetime | None = None
    for r in rows:
        ok = await handle_domain_event(
            session,
            event_id=r.id,
            event_type=r.event_type,
            payload=r.payload or {},
            occurred_at=r.occurred_at,
            organization_id=r.organization_id,
        )
        await fs_raw.mark_consumed(r.id, r.event_type)  # as Postgres: applied or skipped
        applied += 1 if ok else 0
        skipped += 0 if ok else 1
        newest = r.occurred_at if newest is None or r.occurred_at > newest else newest
    await fs_raw.set_state("outbox_consumer", newest, {})
    return {"applied": applied, "skipped": skipped, "seen": len(rows)}


def register_outbox_handlers() -> None:
    from app.core.outbox import register_handler

    for t in HANDLED_TYPES:
        register_handler(t, on_outbox_event)


async def consume_outbox(
    session: AsyncSession, *, limit: int = 500, lookback: timedelta = timedelta(minutes=10)
) -> dict[str, int]:
    """Process unconsumed outbox events of ``HANDLED_TYPES``. Caller sets system context."""
    if _fs():
        return await _consume_outbox_fs(session, limit=limit, lookback=lookback)
    state = (
        await session.execute(text("SELECT watermark FROM analytics_job_state WHERE job = 'outbox_consumer'"))
    ).first()
    since = (state[0] if state and state[0] else datetime(1970, 1, 1, tzinfo=UTC)) - lookback
    rows = [
        (r.id, r.event_type, r.payload, r.organization_id, r.occurred_at)
        for r in await unconsumed_events(session, since=since, limit=limit)
    ]
    applied = skipped = 0
    newest = state[0] if state and state[0] else None
    for r in rows:
        async with session.begin_nested():
            ok = await handle_domain_event(
                session,
                event_id=r[0],
                event_type=r[1],
                payload=r[2] or {},
                occurred_at=r[4],
                organization_id=r[3],
            )
            await session.execute(
                text(
                    "INSERT INTO analytics_consumed_events (outbox_event_id, event_type) VALUES (:i, :t) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"i": r[0], "t": r[1]},
            )
        applied += 1 if ok else 0
        skipped += 0 if ok else 1
        newest = r[4] if newest is None or r[4] > newest else newest
    await session.execute(
        text(
            "INSERT INTO analytics_job_state (job, watermark, last_run_at) VALUES ('outbox_consumer', "
            ":w, :n) "
            "ON CONFLICT (job) DO UPDATE SET watermark = EXCLUDED.watermark, last_run_at = "
            "EXCLUDED.last_run_at"
        ),
        {"w": newest, "n": utcnow()},
    )
    return {"applied": applied, "skipped": skipped, "seen": len(rows)}
