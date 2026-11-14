"""Practice engine (PLC-19..24), interim mastery view (PLC-25) and recommendations v1 (PLC-26/27).
The student company-path view (PLC-32) and company-step practice were removed
(docs/cleanup/feature-removal-plan.md §3.2).

* Keys/explanations are returned only for questions the student has answered (or explicitly
  revealed, which is recorded and excludes the answer from mastery inputs).
* ``topic_mastery`` belongs to analytics (AN CP-11): PLC-25 and the ``weak_topic`` rule read
  ``analytics.mastery.get_topic_mastery``; topics analytics has not scored yet fall back to an
  EWMA of practice accuracy from ``practice_responses`` (method ``practice-ewma-v1``; the method
  used is disclosed per topic).
"""

from __future__ import annotations

import secrets
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_access
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import to_rfc3339, utcnow
from app.modules.placement import bank, grading
from app.modules.placement.models import (
    PracticeResponse,
    PracticeSession,
    Recommendation,
    Topic,
)
from app.modules.placement.schemas import PracticeAnswer, PracticeStart

EWMA_ALPHA = 0.3
WEAK_MIN_ANSWERS = 10
WEAK_THRESHOLD = 0.5
RECENT_CORRECT_EXCLUSION = timedelta(days=30)
REC_TTL = timedelta(days=7)
MASTERY_METHOD = "practice-ewma-v1"
_rng = secrets.SystemRandom()


def _iso(dt: datetime) -> str:
    return to_rfc3339(dt)


def _fs() -> bool:
    return bank._fs()


async def _repo(session: AsyncSession) -> Any:
    return await bank._repo(session)


async def _root_topic_id(session: AsyncSession, topic: Topic) -> uuid.UUID:
    root_slug = topic.path.split("/", 1)[0]
    if _fs():
        return (await (await _repo(session)).topic_id_by_path(root_slug)) or topic.id
    rid = (await session.execute(select(Topic.id).where(Topic.path == root_slug))).scalar_one_or_none()
    return rid or topic.id


async def get_owned_session(
    session: AsyncSession, principal: Principal, ps_id: uuid.UUID, *, lock: bool = False
) -> PracticeSession:
    """``lock=True`` takes ``SELECT ... FOR UPDATE`` on the session row so concurrent answers /
    reveals / completion of one set serialise (audit BE-15: no lost counter updates)."""
    if _fs():
        # No row lock on Firestore: every write that must not lose updates (answer counters,
        # reveal flags, completion) is its own transaction in the repository.
        fps = await (await _repo(session)).get_session(principal.user_id, ps_id)
        if fps is None:
            raise ProblemError("not_found")
        return fps
    stmt = select(PracticeSession).where(PracticeSession.id == ps_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    ps = (await session.execute(stmt)).scalar_one_or_none()
    if ps is None or ps.user_id != principal.user_id:
        raise ProblemError("not_found")
    return ps


async def require_session_access(session: AsyncSession, principal: Principal, ps: PracticeSession) -> None:
    """Re-check the entitlement that admitted the set (PLC-21/22 "S + entitlement", audit BE-14):
    a set started while entitled must not keep serving keys after the entitlement ends."""
    if ps.topic_id is None:
        raise ProblemError("not_found")
    topic = await bank.get_topic(session, ps.topic_id)
    await require_access(session, principal, "question_set", await _root_topic_id(session, topic))


async def start(session: AsyncSession, principal: Principal, body: PracticeStart) -> PracticeSession:
    if body.difficulty_min > body.difficulty_max:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "difficulty_min", "code": "invalid", "message": "must be <= difficulty_max"}],
        )
    if body.topic_id is None:
        raise ProblemError(
            "validation_failed", errors=[{"field": "topic_id", "code": "required", "message": "required"}]
        )
    topic = await bank.get_topic(session, body.topic_id)
    await require_access(session, principal, "question_set", await _root_topic_id(session, topic))

    pool = await bank.published_pool(
        session, topic_id=topic.id, difficulty_min=body.difficulty_min, difficulty_max=body.difficulty_max
    )
    held_back = await _in_graded_tests(session, pool)
    pool = [q for q in pool if q not in held_back]
    if _fs():
        hist_rows: Any = [
            (h.question_version_id, h.is_correct, h.answered_at)
            for h in await (await _repo(session)).history(principal.user_id)
        ]
    else:
        hist_rows = (
            await session.execute(
                select(
                    PracticeResponse.question_version_id,
                    PracticeResponse.is_correct,
                    PracticeResponse.answered_at,
                )
                .where(PracticeResponse.user_id == principal.user_id)
                .order_by(PracticeResponse.answered_at.desc())
            )
        ).all()
    now = utcnow()
    recent_correct: set[uuid.UUID] = set()
    latest_wrong: set[uuid.UUID] = set()
    seen_latest: set[uuid.UUID] = set()
    for qv_id, correct, at in hist_rows:
        if correct and at > now - RECENT_CORRECT_EXCLUSION:
            recent_correct.add(qv_id)
        if qv_id not in seen_latest:
            seen_latest.add(qv_id)
            if correct is False:
                latest_wrong.add(qv_id)
    if body.mode == "revision":
        chosen = [q for q in pool if q in latest_wrong]
        _rng.shuffle(chosen)
        chosen = chosen[: body.count]
    else:
        fresh = [q for q in pool if q not in recent_correct]
        rest = [q for q in pool if q in recent_correct]
        _rng.shuffle(fresh)
        _rng.shuffle(rest)
        chosen = (fresh + rest)[: body.count]
    if not chosen:
        raise ProblemError(
            "invalid_state_transition",
            detail="No published questions match this selection yet. Try another topic or difficulty.",
        )
    ps = PracticeSession(
        id=uuid7(),
        user_id=principal.user_id,
        organization_id=None,
        mode=body.mode,
        topic_id=topic.id,
        company_path_step_id=None,
        status="active",
        target_count=len(chosen),
        served=[
            {"qv": str(q), "served_at": _iso(now), "pos": i + 1, "solution_viewed": False, "hint_used": False}
            for i, q in enumerate(chosen)
        ],
        started_at=now,
    )
    if _fs():
        ps.answered_count, ps.correct_count, ps.ended_at, ps.updated_at = 0, 0, None, now
        return await (await _repo(session)).create_session(principal.user_id, ps)
    session.add(ps)
    await session.flush()
    return ps


async def _in_graded_tests(session: AsyncSession, pool: list[uuid.UUID]) -> set[uuid.UUID]:
    """Question versions a published graded test (any kind but ``practice_set``) uses as a fixed
    question. Practice reveals keys and explanations, so those stay out of practice sets while
    the test is live (QA 2026-11: the Demo Aptitude Mock's questions were answerable from
    practice). Questions a test only draws at random from a topic are not held back."""
    if not pool:
        return set()
    from app.modules.assessments import public as assessments_public

    qmap = {k: b.question.id for k, b in (await bank.load_bundles(session, pool)).items()}
    return await assessments_public.fixed_versions_in_live_tests(session, pool, qmap)


def _served_index(ps: PracticeSession, qv_id: uuid.UUID) -> int:
    for i, s in enumerate(ps.served):
        if s["qv"] == str(qv_id):
            return i
    raise ProblemError("not_found")


async def _responses(session: AsyncSession, ps: PracticeSession) -> dict[uuid.UUID, PracticeResponse]:
    if _fs():
        return {r.question_version_id: r for r in await (await _repo(session)).responses(ps.user_id, ps.id)}
    rows = await session.execute(
        select(PracticeResponse).where(PracticeResponse.practice_session_id == ps.id)
    )
    return {r.question_version_id: r for r in rows.scalars()}


def _feedback(b: bank.Bundle, r: PracticeResponse, next_qv: str | None) -> dict[str, Any]:
    return {
        "question_version_id": str(r.question_version_id),
        "is_correct": r.is_correct,
        "your_response": r.response,
        **bank.key_payload(b),
        "attempt_no": r.attempt_no,
        "solution_viewed": r.solution_viewed,
        "answered_at": _iso(r.answered_at),
        "mastery_delta": None,  # analytics-owned (topic_mastery) — not computed here
        "next_question_version_id": next_qv,
    }


def _next_unanswered(ps: PracticeSession, answered: set[str]) -> str | None:
    for s in ps.served:
        if s["qv"] not in answered:
            return str(s["qv"])
    return None


async def state(session: AsyncSession, ps: PracticeSession) -> dict[str, Any]:
    ids = [uuid.UUID(s["qv"]) for s in ps.served]
    bundles = await bank.load_bundles(session, ids)
    resp = await _responses(session, ps)
    answered = {str(k) for k in resp}
    nxt = _next_unanswered(ps, answered)
    items = []
    for s in ps.served:
        qv = uuid.UUID(s["qv"])
        b = bundles.get(qv)
        if b is None:
            continue
        r = resp.get(qv)
        items.append(
            {
                "position": s["pos"],
                "served_at": s["served_at"],
                "question": bank.delivery(b),
                "answered": r is not None,
                "feedback": _feedback(b, r, nxt) if r is not None else None,
            }
        )
    return {
        "session_id": str(ps.id),
        "mode": ps.mode,
        "topic_id": str(ps.topic_id) if ps.topic_id else None,
        "status": ps.status,
        "target_count": ps.target_count,
        "answered_count": ps.answered_count,
        "correct_count": ps.correct_count,
        "started_at": _iso(ps.started_at),
        "ended_at": _iso(ps.ended_at) if ps.ended_at else None,
        "next_question_version_id": nxt,
        "items": items,
    }


async def answer(
    session: AsyncSession, principal: Principal, ps: PracticeSession, body: PracticeAnswer
) -> dict[str, Any]:
    if ps.status != "active":
        raise ProblemError("invalid_state_transition", detail="This practice set is already finished.")
    await require_session_access(session, principal, ps)
    idx = _served_index(ps, body.question_version_id)
    served = ps.served[idx]
    bundles = await bank.load_bundles(session, [body.question_version_id])
    b = bundles.get(body.question_version_id)
    if b is None:
        raise ProblemError("not_found")
    resp = await _responses(session, ps)
    existing = resp.get(body.question_version_id)
    if existing is not None:  # already answered in this set: same feedback, nothing re-scored
        answered = {str(k) for k in resp}
        return _feedback(b, existing, _next_unanswered(ps, answered))
    normalised = grading.normalise_response(b.qtype, body.response, b.option_ids)
    if normalised is None:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "response", "code": "required", "message": "answer is empty"}],
        )
    correct = grading.is_correct(b.qtype, normalised, b.correct_option_ids, b.version.answer_key)
    if _fs():
        return await _fs_answer(session, principal, ps, b, body, served, normalised, correct, resp)
    prior = (
        await session.execute(
            select(func.count()).where(
                PracticeResponse.user_id == principal.user_id,
                PracticeResponse.question_version_id == b.version.id,
            )
        )
    ).scalar_one()
    now = utcnow()
    served_at = datetime.fromisoformat(served["served_at"].replace("Z", "+00:00"))
    r = PracticeResponse(
        id=uuid7(),
        practice_session_id=ps.id,
        user_id=principal.user_id,
        organization_id=ps.organization_id,
        question_version_id=b.version.id,
        topic_id=b.question.primary_topic_id,
        response=normalised,
        is_correct=correct,
        attempt_no=int(prior) + 1,
        served_at=served_at,
        time_spent_ms=body.time_spent_ms,
        hint_used=bool(served.get("hint_used")),
        solution_viewed=bool(served.get("solution_viewed")),
        answered_at=max(now, served_at),
    )
    # Answers given after viewing the solution are recorded but do not count as correct in the
    # set summary (PLC-22 "lowers mastery weight"; audit BE-28).
    counts_correct = bool(correct) and not r.solution_viewed
    try:
        async with session.begin_nested():
            session.add(r)
            await session.flush()
    except IntegrityError:
        # UNIQUE(practice_session_id, question_version_id): a concurrent duplicate answer won the
        # race -> return the stored feedback (idempotent), never a 500 (audit BE-15).
        resp = await _responses(session, ps)
        existing = resp.get(body.question_version_id)
        if existing is None:
            raise
        return _feedback(b, existing, _next_unanswered(ps, {str(k) for k in resp}))
    # SQL-side increments: no lost updates even without the row lock.
    await session.execute(
        update(PracticeSession)
        .where(PracticeSession.id == ps.id)
        .values(
            answered_count=PracticeSession.answered_count + 1,
            correct_count=PracticeSession.correct_count + (1 if counts_correct else 0),
        )
        .execution_options(synchronize_session=False)
    )
    await session.refresh(ps, ["answered_count", "correct_count"])
    await emit_event(
        session,
        "practice.answered",
        {
            "practice_response_id": str(r.id),
            "practice_session_id": str(ps.id),
            "user_id": str(principal.user_id),
            "question_version_id": str(b.version.id),
            "topic_id": str(r.topic_id),
            "is_correct": correct,
            "attempt_no": r.attempt_no,
            "difficulty": b.version.difficulty,
            "solution_viewed": r.solution_viewed,
            "server_time_on_question_ms": int((r.answered_at - served_at).total_seconds() * 1000),
        },
        aggregate_type="practice_session",
        aggregate_id=ps.id,
        organization_id=ps.organization_id,
    )
    answered = {str(k) for k in resp} | {str(b.version.id)}
    return _feedback(b, r, _next_unanswered(ps, answered))


async def _fs_answer(
    session: AsyncSession,
    principal: Principal,
    ps: PracticeSession,
    b: bank.Bundle,
    body: PracticeAnswer,
    served: dict[str, Any],
    normalised: Any,
    correct: bool | None,
    resp: dict[uuid.UUID, PracticeResponse],
) -> dict[str, Any]:
    """``answer`` on Firestore: response + counters in one transaction (``record_answer``)."""
    now = utcnow()
    served_at = datetime.fromisoformat(served["served_at"].replace("Z", "+00:00"))
    r = PracticeResponse(
        id=uuid7(),
        practice_session_id=ps.id,
        user_id=principal.user_id,
        organization_id=ps.organization_id,
        question_version_id=b.version.id,
        topic_id=b.question.primary_topic_id,
        response=normalised,
        is_correct=correct,
        attempt_no=1,  # prior answers + 1, counted by the repository
        served_at=served_at,
        time_spent_ms=body.time_spent_ms,
        hint_used=bool(served.get("hint_used")),
        solution_viewed=bool(served.get("solution_viewed")),
        rating_before=None,
        rating_after=None,
        answered_at=max(now, served_at),
    )
    counts_correct = bool(correct) and not r.solution_viewed

    def emit(tx: Any, row: PracticeResponse) -> None:
        from app.core.firestore.core_store import emit_event_tx

        emit_event_tx(
            tx,
            "practice.answered",
            {
                "practice_response_id": str(row.id),
                "practice_session_id": str(ps.id),
                "user_id": str(principal.user_id),
                "question_version_id": str(b.version.id),
                "topic_id": str(row.topic_id),
                "is_correct": correct,
                "attempt_no": row.attempt_no,
                "difficulty": b.version.difficulty,
                "solution_viewed": row.solution_viewed,
                "server_time_on_question_ms": int((row.answered_at - served_at).total_seconds() * 1000),
            },
            aggregate_type="practice_session",
            aggregate_id=ps.id,
            organization_id=ps.organization_id,
        )

    stored, created, after = await (await _repo(session)).record_answer(
        principal.user_id, r, counts_correct=counts_correct, on_created=emit
    )
    ps.answered_count, ps.correct_count = after.answered_count, after.correct_count
    if not created:  # a concurrent duplicate answer won: same feedback (audit BE-15)
        resp = await _responses(session, ps)
        return _feedback(b, stored, _next_unanswered(ps, {str(k) for k in resp}))
    answered = {str(k) for k in resp} | {str(b.version.id)}
    return _feedback(b, stored, _next_unanswered(ps, answered))


async def reveal(
    session: AsyncSession, principal: Principal, ps: PracticeSession, qv_id: uuid.UUID, kind: str
) -> dict[str, Any]:
    if ps.status != "active":
        raise ProblemError("invalid_state_transition", detail="This practice set is already finished.")
    await require_session_access(session, principal, ps)
    idx = _served_index(ps, qv_id)
    if _fs():
        fps = await (await _repo(session)).mark_served(
            principal.user_id, ps.id, str(qv_id), "hint_used" if kind == "hint" else "solution_viewed"
        )
        ps.served = fps.served
        if kind == "hint":
            return {"kind": "hint", "available": False, "hint_html": None}
        fb = (await bank.load_bundles(session, [qv_id])).get(qv_id)
        if fb is None:
            raise ProblemError("not_found")
        return {"kind": "solution", "question_version_id": str(qv_id), **bank.key_payload(fb)}
    served = [dict(s) for s in ps.served]
    if kind == "hint":
        served[idx]["hint_used"] = True
        ps.served = served
        await session.flush()
        return {"kind": "hint", "available": False, "hint_html": None}
    served[idx]["solution_viewed"] = True
    ps.served = served
    await session.flush()
    b = (await bank.load_bundles(session, [qv_id])).get(qv_id)
    if b is None:
        raise ProblemError("not_found")
    return {"kind": "solution", "question_version_id": str(qv_id), **bank.key_payload(b)}


async def complete(session: AsyncSession, principal: Principal, ps: PracticeSession) -> dict[str, Any]:
    if _fs():
        fps, changed = await (await _repo(session)).complete_session(principal.user_id, ps.id)
        ps.status, ps.ended_at = fps.status, fps.ended_at
        if changed:
            await refresh_recommendations(session, principal)
    elif ps.status == "active":
        ps.status = "completed"
        ps.ended_at = utcnow()
        await session.flush()
        await refresh_recommendations(session, principal)
    resp = await _responses(session, ps)
    by_topic: dict[uuid.UUID, list[bool]] = defaultdict(list)
    for r in resp.values():
        # answers after viewing the solution never count as correct (audit BE-28)
        by_topic[r.topic_id].append(bool(r.is_correct) and not r.solution_viewed)
    answered = len(resp)
    correct = sum(1 for r in resp.values() if r.is_correct and not r.solution_viewed)
    return {
        "session_id": str(ps.id),
        "status": ps.status,
        "answered": answered,
        "correct": correct,
        "solution_viewed": sum(1 for r in resp.values() if r.solution_viewed),
        "accuracy": round(correct / answered, 4) if answered else None,
        "unanswered": max(0, (ps.target_count or 0) - answered),
        "by_topic": [
            {"topic_id": str(t), "answered": len(v), "correct": sum(v)} for t, v in sorted(by_topic.items())
        ],
    }


async def review_list(session: AsyncSession, principal: Principal, limit: int = 50) -> list[dict[str, Any]]:
    """PLC-24: questions whose latest practice answer was incorrect."""
    if _fs():
        latest: Any = (await (await _repo(session)).history(principal.user_id))[:2000]
    else:
        latest = (
            await session.execute(
                select(PracticeResponse)
                .where(PracticeResponse.user_id == principal.user_id)
                .order_by(PracticeResponse.answered_at.desc())
                .limit(2000)
            )
        ).scalars()
    seen: set[uuid.UUID] = set()
    out: list[dict[str, Any]] = []
    for r in latest:
        if r.question_version_id in seen:
            continue
        seen.add(r.question_version_id)
        if r.is_correct is False:
            out.append(
                {
                    "question_version_id": str(r.question_version_id),
                    "topic_id": str(r.topic_id),
                    "last_answered_at": _iso(r.answered_at),
                    "attempts": r.attempt_no,
                }
            )
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- mastery (interim)


def _ewma(seq: list[bool]) -> float:
    m: float | None = None
    for ok in seq:
        x = 1.0 if ok else 0.0
        m = x if m is None else EWMA_ALPHA * x + (1 - EWMA_ALPHA) * m
    return m if m is not None else 0.0


def band(n: int, ewma: float) -> str:
    if n < 5:
        return "insufficient_data"
    if ewma < 0.4:
        return "beginner"
    if ewma < 0.6:
        return "developing"
    if ewma < 0.8:
        return "proficient"
    return "mastered"


async def topic_stats(session: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, dict[str, Any]]:
    if _fs():
        hist = await (await _repo(session)).history(user_id)
        stat_rows: Any = [
            (h.topic_id, h.is_correct, h.answered_at)
            for h in sorted(hist, key=lambda h: h.answered_at)
            if not h.solution_viewed and h.is_correct is not None
        ]
    else:
        stat_rows = (
            await session.execute(
                select(PracticeResponse.topic_id, PracticeResponse.is_correct, PracticeResponse.answered_at)
                .where(
                    PracticeResponse.user_id == user_id,
                    PracticeResponse.solution_viewed.is_(False),
                    PracticeResponse.is_correct.is_not(None),
                )
                .order_by(PracticeResponse.answered_at)
            )
        ).all()
    seqs: dict[uuid.UUID, list[bool]] = defaultdict(list)
    last: dict[uuid.UUID, datetime] = {}
    for topic_id, ok, at in stat_rows:
        seqs[topic_id].append(bool(ok))
        last[topic_id] = at
    return {
        t: {
            "answered": len(s),
            "correct": sum(s),
            "accuracy": sum(s) / len(s),
            "ewma": _ewma(s),
            "last_practiced_at": last[t],
        }
        for t, s in seqs.items()
    }


ANALYTICS_METHOD = "analytics-topic-mastery"
# analytics bands (tm-1.0) -> the PLC-25 band vocabulary the UI already renders
_ANALYTICS_BAND = {"weak": "beginner", "developing": "developing", "strong": "mastered"}


async def analytics_mastery(session: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, Any]:
    """``analytics.mastery.get_topic_mastery`` (single writer of ``topic_mastery``, CP-11) by
    topic. Empty when analytics has not consumed the user's events yet (or is unavailable),
    in which case callers fall back to the interim practice EWMA."""
    try:
        from app.core.db import savepoint
        from app.modules.analytics.mastery import get_topic_mastery

        # no savepoint on the Firebase stack's NO_POSTGRES session (begin_nested raised there and
        # the analytics mastery was silently replaced by the interim EWMA)
        async with savepoint(session):
            views = await get_topic_mastery(session, user_id)
    except Exception:  # pragma: no cover - analytics module/table missing
        return {}
    return {v.topic_id: v for v in views if v.band not in ("not_started",)}


async def mastery(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    stats = await topic_stats(session, principal.user_id)
    views = await analytics_mastery(session, principal.user_id)
    ids = set(stats) | set(views)
    topics = {t.id: t for t in await _topics(session, ids)} if ids else {}
    items = []
    for tid in sorted(ids, key=lambda k: topics[k].path if k in topics else ""):
        t = topics.get(tid)
        s = stats.get(tid)
        v = views.get(tid)
        item: dict[str, Any] = {
            "topic_id": str(tid),
            "name": t.name if t else None,
            "path": t.path if t else None,
            "answered": s["answered"] if s else (v.attempts if v else 0),
            "correct": s["correct"] if s else None,
            "accuracy": round(s["accuracy"], 4) if s else None,
            "last_practiced_at": (
                _iso(s["last_practiced_at"])
                if s
                else (_iso(v.last_practiced_at) if v and v.last_practiced_at else None)
            ),
        }
        if v is not None:
            item.update(
                weighted_accuracy=round(v.weighted_accuracy, 4),
                mastery=v.mastery,
                band=_ANALYTICS_BAND.get(v.band, v.band),
                method=ANALYTICS_METHOD,
            )
        else:
            assert s is not None
            item.update(
                weighted_accuracy=round(s["ewma"], 4),
                band=band(s["answered"], s["ewma"]),
                method=MASTERY_METHOD,
            )
        items.append(item)
    return {
        "method": ANALYTICS_METHOD if views else MASTERY_METHOD,
        "method_note": "Topic mastery from analytics (tests and practice, Elo-style, recency-weighted); "
        "topics analytics has not scored yet fall back to an EWMA (alpha 0.3) of practice correctness. "
        "Answers after viewing the solution are excluded.",
        "topics": items,
    }


async def _topics(session: AsyncSession, ids: set[uuid.UUID]) -> list[Topic]:
    if _fs():
        return await (await _repo(session)).get_topics(ids)
    return list((await session.execute(select(Topic).where(Topic.id.in_(list(ids))))).scalars())


async def _all_topics(session: AsyncSession) -> list[Topic]:
    if _fs():
        return await (await _repo(session)).all_topics()
    return list((await session.execute(select(Topic))).scalars())


# --------------------------------------------------------------------------- recommendations v1


async def personalisation_allowed(session: AsyncSession, user_id: uuid.UUID) -> bool:
    from app.modules.identity.service import current_consents

    state_ = await current_consents(session, user_id)
    return state_.get("analytics_personalisation", {}).get("state") == "granted"


async def refresh_recommendations(session: AsyncSession, principal: Principal) -> int:
    """Rule ``weak_topic`` (system-architecture §7.4): >= 10 answers in a topic and EWMA accuracy
    < 0.5 -> practise that topic. Needs ``analytics_personalisation`` consent (PO-04)."""
    uid = principal.user_id
    now = utcnow()
    if _fs():
        return await _fs_refresh_recommendations(session, principal, now)
    await session.execute(
        update(Recommendation)
        .where(
            Recommendation.user_id == uid, Recommendation.status == "active", Recommendation.expires_at <= now
        )
        .values(status="expired")
        .execution_options(synchronize_session=False)
    )
    if not await personalisation_allowed(session, uid):
        return 0
    stats = await topic_stats(session, uid)
    views = await analytics_mastery(session, uid)
    weak = {
        t: s
        for t, s in stats.items()
        if t not in views and s["answered"] >= WEAK_MIN_ANSWERS and s["ewma"] < WEAK_THRESHOLD
    }
    for t, v in views.items():  # analytics mastery wins where it exists
        if v.band == "weak" and v.attempts >= WEAK_MIN_ANSWERS:
            s = stats.get(t) or {"answered": v.attempts, "correct": 0}
            weak[t] = {**s, "answered": v.attempts, "ewma": v.mastery, "method": ANALYTICS_METHOD}
    names = (
        {
            t.id: t.name
            for t in (await session.execute(select(Topic).where(Topic.id.in_(list(weak))))).scalars()
        }
        if weak
        else {}
    )
    active = {
        r.target_id: r
        for r in (
            await session.execute(
                select(Recommendation).where(
                    Recommendation.user_id == uid,
                    Recommendation.rule_key == "weak_topic",
                    Recommendation.status == "active",
                )
            )
        ).scalars()
    }
    recently_dismissed = set(
        (
            await session.execute(
                select(Recommendation.target_id).where(
                    Recommendation.user_id == uid,
                    Recommendation.rule_key == "weak_topic",
                    Recommendation.status == "dismissed",
                    Recommendation.generated_at > now - REC_TTL,
                )
            )
        ).scalars()
    )
    n = 0
    for tid, s in weak.items():
        pct = round(s["ewma"] * 100)
        reason = (
            f"Your recent accuracy in {names.get(tid, 'this topic')} is {pct}% over {s['answered']} answers "
            f"(below {int(WEAK_THRESHOLD * 100)}%). A short practice set will help."
        )
        evidence = {
            "answered": s["answered"],
            "correct": s["correct"],
            "weighted_accuracy": round(s["ewma"], 4),
            "threshold": WEAK_THRESHOLD,
            "method": s.get("method", MASTERY_METHOD),
        }
        priority = max(1, min(100, 100 - pct))
        rec = active.get(tid)
        if rec is not None:
            rec.reason, rec.evidence, rec.priority = reason, evidence, priority
            rec.expires_at = now + REC_TTL
        elif tid not in recently_dismissed:
            session.add(
                Recommendation(
                    id=uuid7(),
                    user_id=uid,
                    organization_id=None,
                    rule_key="weak_topic",
                    reason=reason,
                    evidence=evidence,
                    target_type="topic",
                    target_id=tid,
                    priority=priority,
                    generated_at=now,
                    expires_at=now + REC_TTL,
                )
            )
        n += 1
    for tid, rec in active.items():
        if tid not in weak:
            rec.status = "completed"
    await session.flush()
    return n


def _weak_topics(stats: dict[uuid.UUID, Any], views: dict[uuid.UUID, Any]) -> dict[uuid.UUID, Any]:
    weak = {
        t: s
        for t, s in stats.items()
        if t not in views and s["answered"] >= WEAK_MIN_ANSWERS and s["ewma"] < WEAK_THRESHOLD
    }
    for t, v in views.items():  # analytics mastery wins where it exists
        if v.band == "weak" and v.attempts >= WEAK_MIN_ANSWERS:
            s = stats.get(t) or {"answered": v.attempts, "correct": 0}
            weak[t] = {**s, "answered": v.attempts, "ewma": v.mastery, "method": ANALYTICS_METHOD}
    return weak


def _rec_text(name: str, s: dict[str, Any]) -> tuple[str, dict[str, Any], int]:
    pct = round(s["ewma"] * 100)
    reason = (
        f"Your recent accuracy in {name} is {pct}% over {s['answered']} answers "
        f"(below {int(WEAK_THRESHOLD * 100)}%). A short practice set will help."
    )
    evidence = {
        "answered": s["answered"],
        "correct": s["correct"],
        "weighted_accuracy": round(s["ewma"], 4),
        "threshold": WEAK_THRESHOLD,
        "method": s.get("method", MASTERY_METHOD),
    }
    return reason, evidence, max(1, min(100, 100 - pct))


async def _fs_refresh_recommendations(session: AsyncSession, principal: Principal, now: datetime) -> int:
    """``refresh_recommendations`` on Firestore: the same rule, rows written in transactions that
    keep ``ux_rec_dedupe`` (``recommendations_active``)."""
    uid = principal.user_id
    r = await _repo(session)
    recs = await r.recommendations(uid)
    changed: dict[uuid.UUID, Recommendation] = {}
    for rec in recs:
        if rec.status == "active" and rec.expires_at <= now:
            rec.status = "expired"
            changed[rec.id] = rec
    if not await personalisation_allowed(session, uid):
        await r.save_recommendations(uid, list(changed.values()), new_ids=set())
        return 0
    weak = _weak_topics(await topic_stats(session, uid), await analytics_mastery(session, uid))
    names = {t.id: t.name for t in await _topics(session, set(weak))} if weak else {}
    active = {x.target_id: x for x in recs if x.rule_key == "weak_topic" and x.status == "active"}
    recently_dismissed = {
        x.target_id
        for x in recs
        if x.rule_key == "weak_topic" and x.status == "dismissed" and x.generated_at > now - REC_TTL
    }
    new: list[Recommendation] = []
    n = 0
    for tid, s in weak.items():
        reason, evidence, priority = _rec_text(names.get(tid, "this topic"), s)
        rec = active.get(tid)
        if rec is not None:
            rec.reason, rec.evidence, rec.priority = reason, evidence, priority
            rec.expires_at = now + REC_TTL
            changed[rec.id] = rec
        elif tid not in recently_dismissed:
            new.append(
                Recommendation(
                    id=uuid7(),
                    user_id=uid,
                    organization_id=None,
                    rule_key="weak_topic",
                    rule_version=1,
                    reason=reason,
                    evidence=evidence,
                    target_type="topic",
                    target_id=tid,
                    priority=priority,
                    status="active",
                    generated_at=now,
                    expires_at=now + REC_TTL,
                )
            )
        n += 1
    for tid, rec in active.items():
        if tid not in weak:
            rec.status = "completed"
            changed[rec.id] = rec
    await r.save_recommendations(uid, [*changed.values(), *new], new_ids={x.id for x in new})
    return n


async def list_recommendations(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    allowed = await personalisation_allowed(session, principal.user_id)
    if not allowed:
        return {"items": [], "personalised": False, "note": "consent_required:analytics_personalisation"}
    now = utcnow()
    if _fs():
        live = [
            x
            for x in await (await _repo(session)).recommendations(principal.user_id)
            if x.status == "active" and x.expires_at > now
        ]
        live.sort(key=lambda x: (x.priority, x.generated_at), reverse=True)
        rec_rows: Any = live[:5]
    else:
        rec_rows = (
            await session.execute(
                select(Recommendation)
                .where(
                    Recommendation.user_id == principal.user_id,
                    Recommendation.status == "active",
                    Recommendation.expires_at > now,
                )
                .order_by(Recommendation.priority.desc(), Recommendation.generated_at.desc())
                .limit(5)
            )
        ).scalars()
    return {
        "personalised": True,
        "items": [
            {
                "id": str(r.id),
                "rule_key": r.rule_key,
                "why_recommended": r.reason,
                "evidence": r.evidence,
                "target_type": r.target_type,
                "target_id": str(r.target_id),
                "priority": r.priority,
                "generated_at": _iso(r.generated_at),
                "expires_at": _iso(r.expires_at),
            }
            for r in rec_rows
        ],
    }


async def dismiss_recommendation(session: AsyncSession, principal: Principal, rec_id: uuid.UUID) -> None:
    if _fs():
        repo = await _repo(session)
        fr = await repo.get_recommendation(principal.user_id, rec_id)
        if fr is None:
            raise ProblemError("not_found")
        if fr.status == "active":
            fr.status = "dismissed"
            await repo.save_recommendations(principal.user_id, [fr], new_ids=set())
        return
    r = await session.get(Recommendation, rec_id)
    if r is None or r.user_id != principal.user_id:
        raise ProblemError("not_found")
    if r.status == "active":
        r.status = "dismissed"
        await session.flush()
