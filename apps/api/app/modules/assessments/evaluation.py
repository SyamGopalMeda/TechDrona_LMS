"""Evaluation of a test's attempts (trainer view): integrity badges, grading progress, AI-assisted
grading of free-text items and per-item finalisation.

* AI output (``app.modules.ai.service.grade_response``) is stored as a *pending suggestion*
  (``attempt_item_grades.ai_status = 'pending'``); only a person finalises marks
  (``POST /attempts/{id}/items/{qv}/grade``), and only finalised marks reach the score.
* Integrity counts are evidence for the evaluator; nothing here changes an attempt because of them.
* Publishing reuses ASM-16 (``POST /tests/{id}/results/release``) per assignment.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from html import unescape
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.errors import ProblemError
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.assessments import attempts as svc
from app.modules.assessments import datastore as adb
from app.modules.assessments import exam, studio
from app.modules.assessments.models import (
    AttemptItemGrade,
    AttemptResponse,
    AttemptResult,
    Test,
    TestAssignment,
    TestAttempt,
)
from app.modules.placement import bank
from app.modules.placement.richtext import html_of

GRADE_PERMISSION = "test.results.release"  # staff who may publish results may also grade them
READ_PERMISSION = "test.results.read"
FINISHED = ("submitted", "auto_submitted", "grading", "awaiting_manual", "graded")
_TAG = re.compile(r"<[^>]+>")


def _text(html: str | None) -> str:
    return unescape(_TAG.sub(" ", html or "")).strip()


async def _scoped(
    request: Request, session: AsyncSession, principal: Principal, t: Test, permission: str
) -> list[TestAttempt]:
    rows = (
        await adb.execute(
            session, select(TestAttempt).where(TestAttempt.test_id == t.id).order_by(TestAttempt.started_at)
        )
    ).scalars()
    out: list[TestAttempt] = []
    cache: dict[tuple[Any, Any], bool] = {}
    for att in rows:
        if att.user_id == principal.user_id:
            continue  # evaluation is a staff view; learners use their own result pages
        key = (att.batch_id, att.organization_id)
        if key not in cache:
            cache[key] = await studio.attempt_scope_allows(
                request, principal, permission, batch_id=att.batch_id, org_id=att.organization_id
            )
        if cache[key]:
            out.append(att)
    return out


async def _allowed_on_test(
    request: Request, session: AsyncSession, principal: Principal, t: Test, permission: str
) -> bool:
    """Staff may open a test's (possibly still empty) evaluation when they hold ``permission`` on
    the test's owning batch / org / platform scope *or* on a batch the test is assigned to. The
    second branch matters for platform / org tests assigned to a batch: batch-scoped trainers and
    evaluators otherwise got 403 before the first attempt existed."""
    if await studio.attempt_scope_allows(
        request, principal, permission, batch_id=t.batch_id, org_id=t.organization_id
    ):
        return True
    batches = (
        await adb.execute(
            session,
            select(TestAssignment.batch_id).where(
                TestAssignment.test_id == t.id, TestAssignment.batch_id.is_not(None)
            ),
        )
    ).scalars()
    for b in set(batches):
        if b is not None and await studio.attempt_scope_allows(
            request, principal, permission, batch_id=b, org_id=None
        ):
            return True
    return False


def _manual_items(att: TestAttempt, types: dict[uuid.UUID, str]) -> list[dict[str, Any]]:
    out = []
    for sec in att.layout["sections"]:
        for it in sec["items"]:
            qv = uuid.UUID(it["qv"])
            if types.get(qv) in svc.MANUAL_TYPES:
                out.append({**it, "section_id": sec["section_id"], "section_title": sec["title"]})
    return out


async def _types(session: AsyncSession, atts: list[TestAttempt]) -> dict[uuid.UUID, str]:
    qvs = {uuid.UUID(it["qv"]) for a in atts for s in a.layout["sections"] for it in s["items"]}
    shapes = await bank.load_answer_shapes(session, list(qvs))
    return {k: v.qtype for k, v in shapes.items()}


async def _grades(
    session: AsyncSession, ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, uuid.UUID], AttemptItemGrade]:
    if not ids:
        return {}
    rows = await adb.execute(session, select(AttemptItemGrade).where(AttemptItemGrade.attempt_id.in_(ids)))
    return {(g.attempt_id, g.question_version_id): g for g in rows.scalars()}


async def _answered(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, set[uuid.UUID]]:
    out: dict[uuid.UUID, set[uuid.UUID]] = {i: set() for i in ids}
    if not ids:
        return out
    rows = await adb.execute(
        session,
        select(
            AttemptResponse.attempt_id, AttemptResponse.question_version_id, AttemptResponse.response
        ).where(AttemptResponse.attempt_id.in_(ids)),
    )
    for aid, qv, resp in rows.all():
        if resp is not None:  # JSONB ``null`` = cleared
            out[aid].add(qv)
    return out


async def _names(session: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    if not user_ids:
        return {}
    from app.modules.identity import public as identity_public

    profiles = await identity_public.get_profiles(session, user_ids)
    return {u: (p.display_name or p.full_name) for u, p in profiles.items()}


# --------------------------------------------------------------------------- list


async def evaluation_list(
    request: Request, session: AsyncSession, principal: Principal, t: Test
) -> dict[str, Any]:
    visible = {r["attempt_id"] for r in await studio.list_attempts(request, session, principal, t)}
    atts = [a for a in await _scoped(request, session, principal, t, READ_PERMISSION) if str(a.id) in visible]
    if not atts and not await _allowed_on_test(request, session, principal, t, READ_PERMISSION):
        raise ProblemError("permission_denied", permission=READ_PERMISSION)
    ids = [a.id for a in atts]
    protocol = exam.protocol_of(t)
    counts = await exam.event_counts(session, ids)
    types = await _types(session, atts)
    grades = await _grades(session, ids)
    answered = await _answered(session, ids)
    names = await _names(session, {a.user_id for a in atts})
    results = (
        {
            r.attempt_id: r
            for r in (
                await adb.execute(session, select(AttemptResult).where(AttemptResult.attempt_id.in_(ids)))
            ).scalars()
        }
        if ids
        else {}
    )
    rows = []
    totals = {"attempts": 0, "finalized": 0, "ai_pending": 0, "manual_pending": 0, "flagged": 0}
    for a in atts:
        n_items = sum(len(s["items"]) for s in a.layout["sections"])
        manual = _manual_items(a, types)
        ai_pending = manual_pending = 0
        for it in manual:
            qv = uuid.UUID(it["qv"])
            g = grades.get((a.id, qv))
            if qv not in answered[a.id] or (g is not None and g.finalized_at is not None):
                continue
            if g is not None and g.ai_status == "pending":
                ai_pending += 1
            else:
                manual_pending += 1
        finished = a.status in FINISHED
        finalized = (n_items - ai_pending - manual_pending) if finished else 0
        integ = exam.summarize(protocol, counts.get(a.id, {}), a.integrity_status)
        res = results.get(a.id)
        rows.append(
            {
                "attempt_id": str(a.id),
                "user_id": str(a.user_id),
                "learner_name": names.get(a.user_id),
                "attempt_no": a.attempt_no,
                "batch_id": str(a.batch_id) if a.batch_id else None,
                "test_assignment_id": str(a.test_assignment_id) if a.test_assignment_id else None,
                "status": a.status,
                "submit_reason": a.submit_reason,
                "submitted_at": svc.iso(a.submitted_at),
                "score": str(res.score) if res else None,
                "max_score": str(res.max_score) if res else None,
                "released": bool(res and res.released_at),
                "grading": {
                    "items": n_items,
                    "finalized": finalized,
                    "ai_pending": ai_pending,
                    "manual_pending": manual_pending,
                    "manual_items": len(manual),
                },
                "integrity": integ,
            }
        )
        totals["attempts"] += 1
        totals["finalized"] += int(finished and not (ai_pending or manual_pending))
        totals["ai_pending"] += ai_pending
        totals["manual_pending"] += manual_pending
        totals["flagged"] += int(integ["flagged"])
    assignments = (
        await adb.execute(session, select(TestAssignment).where(TestAssignment.test_id == t.id))
    ).scalars()
    return {
        "test": {"id": str(t.id), "title": t.title, "status": t.status},
        "protocol": protocol.public(),
        "assignments": [
            studio.assignment_out(x) for x in assignments if any(a.test_assignment_id == x.id for a in atts)
        ],
        "totals": totals,
        "items": rows,
    }


# --------------------------------------------------------------------------- review (one attempt)


async def _attempt_for_staff(
    request: Request, session: AsyncSession, principal: Principal, attempt_id: uuid.UUID, permission: str
) -> tuple[TestAttempt, Test]:
    att = await svc.load_attempt(session, attempt_id)
    if not await studio.attempt_scope_allows(
        request, principal, permission, batch_id=att.batch_id, org_id=att.organization_id
    ):
        raise ProblemError(
            "permission_denied" if att.user_id == principal.user_id else "not_found", permission=permission
        )
    if permission != READ_PERMISSION and att.user_id == principal.user_id:
        # SEC-10: nobody grades their own attempt (evaluators, trainers and admins alike).
        raise ProblemError("conflict_of_interest", detail="You cannot grade your own attempt.")
    t = await adb.get(session, Test, att.test_id)
    if t is None:  # pragma: no cover - FK
        raise ProblemError("not_found")
    return att, t


def _grade_out(g: AttemptItemGrade | None) -> dict[str, Any] | None:
    if g is None:
        return None
    return {
        "ai_status": g.ai_status,
        "ai_marks": str(g.ai_marks) if g.ai_marks is not None else None,
        "ai_feedback": g.ai_feedback,
        "ai_confidence": float(g.ai_confidence) if g.ai_confidence is not None else None,
        "ai_criteria": g.ai_criteria or [],
        "ai_error": g.ai_error,
        "final_marks": str(g.final_marks) if g.final_marks is not None else None,
        "final_feedback": g.final_feedback,
        "finalized_at": svc.iso(g.finalized_at),
        "finalized_by": str(g.finalized_by) if g.finalized_by else None,
    }


async def attempt_review(
    request: Request, session: AsyncSession, principal: Principal, attempt_id: uuid.UUID
) -> dict[str, Any]:
    att, t = await _attempt_for_staff(request, session, principal, attempt_id, READ_PERMISSION)
    qvs = [uuid.UUID(it["qv"]) for s in att.layout["sections"] for it in s["items"]]
    bundles = await bank.load_bundles(session, qvs)
    responses = {
        r.question_version_id: r
        for r in (
            await adb.execute(session, select(AttemptResponse).where(AttemptResponse.attempt_id == att.id))
        ).scalars()
    }
    grades = await _grades(session, [att.id])
    names = await _names(session, {att.user_id})
    sections = []
    for s in att.layout["sections"]:
        items = []
        for it in s["items"]:
            qv = uuid.UUID(it["qv"])
            b = bundles[qv]
            r = responses.get(qv)
            manual = b.qtype in svc.MANUAL_TYPES
            items.append(
                {
                    "question_version_id": str(qv),
                    "type": b.qtype,
                    "stem_html": html_of(b.version.stem) or "",
                    "marks": it["marks"],
                    "negative_marks": it["neg"],
                    "response": r.response if r is not None else None,
                    "is_correct": r.is_correct if r is not None else None,
                    "marks_awarded": str(r.marks_awarded)
                    if r is not None and r.marks_awarded is not None
                    else None,
                    "needs_human": manual,
                    "grade": _grade_out(grades.get((att.id, qv))) if manual else None,
                }
            )
        sections.append({"section_id": s["section_id"], "title": s["title"], "items": items})
    res = await adb.get(session, AttemptResult, att.id)
    return {
        "attempt_id": str(att.id),
        "test_id": str(t.id),
        "learner_name": names.get(att.user_id),
        "user_id": str(att.user_id),
        "status": att.status,
        "submit_reason": att.submit_reason,
        "submitted_at": svc.iso(att.submitted_at),
        "score": str(res.score) if res else None,
        "max_score": str(res.max_score) if res else None,
        "integrity": await exam.attempt_summary(session, att, t),
        "sections": sections,
    }


# --------------------------------------------------------------------------- AI grading


async def _grade_row(
    session: AsyncSession, att: TestAttempt, qv: uuid.UUID, max_marks: Decimal
) -> AttemptItemGrade:
    g = await adb.get(session, AttemptItemGrade, (att.id, qv), with_for_update=True)
    if g is None:
        g = AttemptItemGrade(
            attempt_id=att.id,
            question_version_id=qv,
            test_id=att.test_id,
            user_id=att.user_id,
            organization_id=att.organization_id,
            max_marks=max_marks,
            ai_status="none",
        )
        adb.add(session, g)
    return g


async def run_ai_grading(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    t: Test,
    *,
    attempt_id: uuid.UUID | None,
    redo: bool,
) -> dict[str, Any]:
    from app.modules.ai import public as ai  # grade_response + AIError (store-neutral API)

    atts = [
        a
        for a in await _scoped(request, session, principal, t, GRADE_PERMISSION)
        if a.status in FINISHED and (attempt_id is None or a.id == attempt_id)
    ]
    if attempt_id is not None and not atts:
        raise ProblemError("not_found")
    if not atts and not await _allowed_on_test(request, session, principal, t, GRADE_PERMISSION):
        raise ProblemError("permission_denied", permission=GRADE_PERMISSION)
    ids = [a.id for a in atts]
    types = await _types(session, atts)
    grades = await _grades(session, ids)
    responses = (
        {
            (r.attempt_id, r.question_version_id): r
            for r in (
                await adb.execute(session, select(AttemptResponse).where(AttemptResponse.attempt_id.in_(ids)))
            ).scalars()
            if r.response is not None
        }
        if ids
        else {}
    )
    work: list[tuple[TestAttempt, dict[str, Any]]] = []
    skipped = 0
    for a in atts:
        for it in _manual_items(a, types):
            qv = uuid.UUID(it["qv"])
            g = grades.get((a.id, qv))
            if (a.id, qv) not in responses or (g is not None and g.finalized_at is not None):
                continue
            if g is not None and g.ai_status == "pending" and not redo:
                skipped += 1
                continue
            work.append((a, it))
    bundles = await bank.load_bundles(session, list({uuid.UUID(it["qv"]) for _, it in work}))
    graded = failed = 0
    stopped: str | None = None
    for a, it in work:
        qv = uuid.UUID(it["qv"])
        b = bundles[qv]
        key = b.version.answer_key or {}
        resp = responses[(a.id, qv)].response or {}
        max_marks = Decimal(it["marks"])
        try:
            sug = await ai.grade_response(
                session,
                org_id=a.organization_id or t.organization_id,
                user_id=principal.user_id,
                purpose="assessment",
                question_md=_text(html_of(b.version.stem)),
                response_text=str(resp.get("text") or resp.get("value") or ""),
                max_marks=max_marks,
                rubric=key.get("rubric") if isinstance(key.get("rubric"), list) else None,
                reference_answer_md=key.get("reference_answer_md") or key.get("model_answer") or None,
            )
        except ai.AIError as e:
            if graded == 0 and failed == 0:
                raise  # AIError is a ProblemError (403/429/503 ai_*)
            stopped = e.code
            break
        except Exception:
            g = await _grade_row(session, a, qv, max_marks)
            g.ai_status, g.ai_error = "failed", "AI grading failed for this answer"
            failed += 1
            continue
        g = await _grade_row(session, a, qv, max_marks)
        g.ai_status = "pending"
        g.ai_marks = max(Decimal("0"), min(Decimal(sug.marks), max_marks))
        g.ai_feedback = sug.feedback_md
        g.ai_confidence = Decimal(str(round(max(0.0, min(1.0, float(sug.confidence))), 3)))
        g.ai_criteria = list(sug.criteria or [])
        g.ai_error = None
        g.ai_graded_at = utcnow()
        graded += 1
    await adb.flush(session)
    await audit(
        session,
        principal,
        "test.ai_grading_run",
        "test",
        t.id,
        organization_id=t.organization_id,
        after={
            "graded": graded,
            "failed": failed,
            "skipped": skipped,
            "attempt_id": str(attempt_id) if attempt_id else None,
        },
    )
    return {"graded": graded, "failed": failed, "skipped": skipped, "stopped_reason": stopped}


# --------------------------------------------------------------------------- finalise one item


async def finalize_item(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    attempt_id: uuid.UUID,
    qv: uuid.UUID,
    marks: Decimal,
    feedback: str | None,
) -> dict[str, Any]:
    att, t = await _attempt_for_staff(request, session, principal, attempt_id, GRADE_PERMISSION)
    att = await svc.load_attempt(session, att.id, lock=True)
    if att.status not in FINISHED:
        raise ProblemError(
            "invalid_state_transition",
            detail="Only a submitted attempt can be graded.",
            attempt_status=att.status,
        )
    entry = svc.layout_index(att).get(str(qv))
    shapes = await bank.load_answer_shapes(session, [qv])
    if entry is None or qv not in shapes or shapes[qv].qtype not in svc.MANUAL_TYPES:
        raise ProblemError("not_found")
    max_marks = Decimal(entry[1]["marks"])
    if marks > max_marks:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "marks", "code": "invalid", "message": f"must be at most {max_marks}"}],
        )
    g = await _grade_row(session, att, qv, max_marks)
    before = {"final_marks": str(g.final_marks) if g.final_marks is not None else None}
    now = utcnow()
    g.final_marks = marks
    g.final_feedback = feedback
    g.finalized_by = principal.user_id
    g.finalized_at = now
    await adb.flush(session)
    existing = await adb.get(session, AttemptResult, att.id)
    await svc.score_attempt(
        session, att, t, scoring_version=(existing.scoring_version + 1) if existing else 1
    )
    await audit(
        session,
        principal,
        "attempt.item_graded",
        "test_attempt",
        att.id,
        organization_id=att.organization_id,
        subject_user_id=att.user_id,
        before=before,
        after={
            "question_version_id": str(qv),
            "final_marks": str(marks),
            "ai_marks": str(g.ai_marks) if g.ai_marks is not None else None,
        },
    )
    res = await adb.get(session, AttemptResult, att.id)
    return {
        "attempt_id": str(att.id),
        "question_version_id": str(qv),
        "status": att.status,
        "score": str(res.score) if res else None,
        "max_score": str(res.max_score) if res else None,
        "grade": _grade_out(g),
    }
