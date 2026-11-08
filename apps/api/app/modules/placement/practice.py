"""Practice engine (PLC-19..24), interim mastery view (PLC-25), recommendations v1 (PLC-26/27)
and the student company-path view (PLC-32).

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

from app.core.access import check_access, require_access
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import to_rfc3339, utcnow
from app.modules.placement import bank, grading
from app.modules.placement.models import (
    Company,
    CompanyPath,
    CompanyPathStep,
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


async def _root_topic_id(session: AsyncSession, topic: Topic) -> uuid.UUID:
    root_slug = topic.path.split("/", 1)[0]
    rid = (await session.execute(select(Topic.id).where(Topic.path == root_slug))).scalar_one_or_none()
    return rid or topic.id


async def get_owned_session(
    session: AsyncSession, principal: Principal, ps_id: uuid.UUID, *, lock: bool = False
) -> PracticeSession:
    """``lock=True`` takes ``SELECT ... FOR UPDATE`` on the session row so concurrent answers /
    reveals / completion of one set serialise (audit BE-15: no lost counter updates)."""
    stmt = select(PracticeSession).where(PracticeSession.id == ps_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    ps = (await session.execute(stmt)).scalar_one_or_none()
    if ps is None or ps.user_id != principal.user_id:
        raise ProblemError("not_found")
    return ps


async def _published_step(session: AsyncSession, step_id: uuid.UUID) -> CompanyPathStep:
    """A practice step of a PUBLISHED company path (audit BE-27: draft/archived paths -> 404)."""
    row = (
        await session.execute(
            select(CompanyPathStep)
            .join(CompanyPath, CompanyPath.id == CompanyPathStep.company_path_id)
            .where(CompanyPathStep.id == step_id, CompanyPath.status == "published")
        )
    ).scalar_one_or_none()
    if row is None or row.step_type != "practice_set" or row.topic_id is None:
        raise ProblemError("not_found")
    return row


async def require_session_access(session: AsyncSession, principal: Principal, ps: PracticeSession) -> None:
    """Re-check the entitlement that admitted the set (PLC-21/22 "S + entitlement", audit BE-14):
    a set started while entitled must not keep serving keys after the entitlement ends."""
    if ps.company_path_step_id is not None:
        step = await _published_step(session, ps.company_path_step_id)
        await require_access(session, principal, "company_path", step.company_path_id)
        return
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
    step: CompanyPathStep | None = None
    if body.mode == "company_step":
        if body.company_path_step_id is None:
            raise ProblemError(
                "validation_failed",
                errors=[{"field": "company_path_step_id", "code": "required", "message": "required"}],
            )
        step = await _published_step(session, body.company_path_step_id)
        assert step.topic_id is not None
        await require_access(session, principal, "company_path", step.company_path_id)
        topic = await bank.get_topic(session, step.topic_id)
    else:
        if body.topic_id is None:
            raise ProblemError(
                "validation_failed", errors=[{"field": "topic_id", "code": "required", "message": "required"}]
            )
        topic = await bank.get_topic(session, body.topic_id)
        await require_access(session, principal, "question_set", await _root_topic_id(session, topic))

    pool = await bank.published_pool(
        session, topic_id=topic.id, difficulty_min=body.difficulty_min, difficulty_max=body.difficulty_max
    )
    history = await session.execute(
        select(
            PracticeResponse.question_version_id, PracticeResponse.is_correct, PracticeResponse.answered_at
        )
        .where(PracticeResponse.user_id == principal.user_id)
        .order_by(PracticeResponse.answered_at.desc())
    )
    now = utcnow()
    recent_correct: set[uuid.UUID] = set()
    latest_wrong: set[uuid.UUID] = set()
    seen_latest: set[uuid.UUID] = set()
    for qv_id, correct, at in history.all():
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
        company_path_step_id=step.id if step else None,
        status="active",
        target_count=len(chosen),
        served=[
            {"qv": str(q), "served_at": _iso(now), "pos": i + 1, "solution_viewed": False, "hint_used": False}
            for i, q in enumerate(chosen)
        ],
        started_at=now,
    )
    session.add(ps)
    await session.flush()
    return ps


def _served_index(ps: PracticeSession, qv_id: uuid.UUID) -> int:
    for i, s in enumerate(ps.served):
        if s["qv"] == str(qv_id):
            return i
    raise ProblemError("not_found")


async def _responses(session: AsyncSession, ps: PracticeSession) -> dict[uuid.UUID, PracticeResponse]:
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


async def reveal(
    session: AsyncSession, principal: Principal, ps: PracticeSession, qv_id: uuid.UUID, kind: str
) -> dict[str, Any]:
    if ps.status != "active":
        raise ProblemError("invalid_state_transition", detail="This practice set is already finished.")
    await require_session_access(session, principal, ps)
    idx = _served_index(ps, qv_id)
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
    if ps.status == "active":
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
    rows = await session.execute(
        select(PracticeResponse)
        .where(PracticeResponse.user_id == principal.user_id)
        .order_by(PracticeResponse.answered_at.desc())
        .limit(2000)
    )
    seen: set[uuid.UUID] = set()
    out: list[dict[str, Any]] = []
    for r in rows.scalars():
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
    rows = await session.execute(
        select(PracticeResponse.topic_id, PracticeResponse.is_correct, PracticeResponse.answered_at)
        .where(
            PracticeResponse.user_id == user_id,
            PracticeResponse.solution_viewed.is_(False),
            PracticeResponse.is_correct.is_not(None),
        )
        .order_by(PracticeResponse.answered_at)
    )
    seqs: dict[uuid.UUID, list[bool]] = defaultdict(list)
    last: dict[uuid.UUID, datetime] = {}
    for topic_id, ok, at in rows.all():
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
        from app.modules.analytics.mastery import get_topic_mastery

        async with session.begin_nested():
            views = await get_topic_mastery(session, user_id)
    except Exception:  # pragma: no cover - analytics module/table missing
        return {}
    return {v.topic_id: v for v in views if v.band not in ("not_started",)}


async def mastery(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    stats = await topic_stats(session, principal.user_id)
    views = await analytics_mastery(session, principal.user_id)
    ids = set(stats) | set(views)
    topics = (
        {t.id: t for t in (await session.execute(select(Topic).where(Topic.id.in_(list(ids))))).scalars()}
        if ids
        else {}
    )
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


async def list_recommendations(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    allowed = await personalisation_allowed(session, principal.user_id)
    if not allowed:
        return {"items": [], "personalised": False, "note": "consent_required:analytics_personalisation"}
    now = utcnow()
    rows = await session.execute(
        select(Recommendation)
        .where(
            Recommendation.user_id == principal.user_id,
            Recommendation.status == "active",
            Recommendation.expires_at > now,
        )
        .order_by(Recommendation.priority.desc(), Recommendation.generated_at.desc())
        .limit(5)
    )
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
            for r in rows.scalars()
        ],
    }


async def dismiss_recommendation(session: AsyncSession, principal: Principal, rec_id: uuid.UUID) -> None:
    r = await session.get(Recommendation, rec_id)
    if r is None or r.user_id != principal.user_id:
        raise ProblemError("not_found")
    if r.status == "active":
        r.status = "dismissed"
        await session.flush()


# --------------------------------------------------------------------------- company path (student)


async def my_company_path(session: AsyncSession, principal: Principal, slug: str) -> dict[str, Any]:
    company = (await session.execute(select(Company).where(Company.slug == slug))).scalar_one_or_none()
    if company is None or company.hub_status != "published":
        raise ProblemError("not_found")
    paths = list(
        (
            await session.execute(
                select(CompanyPath)
                .where(CompanyPath.company_id == company.id, CompanyPath.status == "published")
                .order_by(CompanyPath.role_name, CompanyPath.version_no.desc())
            )
        ).scalars()
    )
    if not paths:
        raise ProblemError("not_found")
    stats = await topic_stats(session, principal.user_id)
    all_topics = list((await session.execute(select(Topic))).scalars())
    # Only paths the learner is entitled to are listed (audit BE-15 note: one unentitled path
    # must not 403 the whole page); with none entitled the first denial is raised as before.
    entitled: list[CompanyPath] = []
    for p in paths:
        if (await check_access(session, principal, "company_path", p.id)).allowed:
            entitled.append(p)
    if not entitled:
        await require_access(session, principal, "company_path", paths[0].id)
    out_paths = []
    for p in entitled:
        out_paths.append(
            {
                **bank.path_out(p, await bank.path_steps(session, p.id)),
                "readiness": path_readiness(p, stats, all_topics),
            }
        )
    return {"company": bank.company_out(company), "paths": out_paths}


READINESS_FORMULA = "sum(weight x practice accuracy in section topic) / sum(weight)"


def path_readiness(
    p: CompanyPath, stats: dict[uuid.UUID, dict[str, Any]], all_topics: list[Topic]
) -> dict[str, Any]:
    """Company-path readiness from the learner's practice accuracy per pattern section."""
    weights = 0.0
    acc = 0.0
    for sec in p.pattern:
        w = float(sec.get("weight", 0))
        root = next((t for t in all_topics if str(t.id) == str(sec.get("topic_id"))), None)
        if root is None or w <= 0:
            continue
        sub = [t.id for t in all_topics if t.id == root.id or t.path.startswith(root.path + "/")]
        ans = sum(stats[t]["answered"] for t in sub if t in stats)
        cor = sum(stats[t]["correct"] for t in sub if t in stats)
        weights += w
        acc += w * (cor / ans if ans else 0.0)
    return {
        "score_pct": round(100 * acc / weights, 1) if weights else None,
        "formula": READINESS_FORMULA,
        "method": MASTERY_METHOD,
    }


async def practised_company_readiness(session: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """Readiness for every published company path the learner has practised (company-step
    practice sets). Used by the mentor console (MEN-004 / PLC-46) until the goals model
    (PLC-28..31, target companies) exists. Caller sets the DB context (RLS U on sessions)."""
    rows = (
        await session.execute(
            select(CompanyPath, Company)
            .join(CompanyPathStep, CompanyPathStep.company_path_id == CompanyPath.id)
            .join(PracticeSession, PracticeSession.company_path_step_id == CompanyPathStep.id)
            .join(Company, Company.id == CompanyPath.company_id)
            .where(PracticeSession.user_id == user_id, CompanyPath.status == "published")
            .distinct()
        )
    ).all()
    if not rows:
        return []
    stats = await topic_stats(session, user_id)
    all_topics = list((await session.execute(select(Topic))).scalars())
    out = [
        {
            "company_id": str(c.id),
            "company_slug": c.slug,
            "company_name": c.name,
            "company_path_id": str(p.id),
            "role_name": p.role_name,
            **path_readiness(p, stats, all_topics),
        }
        for p, c in rows
    ]
    return sorted(out, key=lambda r: (r["company_name"], r["role_name"]))
