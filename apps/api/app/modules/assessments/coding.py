"""Coding questions inside tests (Stage 10 backlog A-4).

A ``coding`` question version references a published ``coding_problems`` row
(``question_versions.coding_problem_id``). The learner solves it through the coding module
(COD-07 ``POST /coding/problems/{id}/submit`` with ``attempt_id``); the coding module calls
``validate_coding_attempt`` (registered with ``coding.service.register_attempt_validator``)
before queueing on ``judge_assessment``. Autosave may pin a submission with
``{"submission_id": "<uuid>"}``; otherwise the newest judged submission of the attempt for that
problem counts.

Scoring: ``marks x score / max_score`` of the judged submission (partial credit by weighted
cases, no negative marks); ``is_correct`` is true only for verdict ``AC``. A submission still
queued/running when the attempt is scored counts as unanswered; when its ``submission.judged``
event arrives later, ``on_submission_judged`` re-scores the attempt with a higher
``scoring_version`` (``attempt.scored`` is emitted again).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.outbox import OutboxMessage
from app.core.principal import Principal
from app.modules.assessments import datastore as adb
from app.modules.assessments.models import AttemptResult, Test, TestAttempt
from app.modules.placement import bank, grading


async def coding_problem_items(session: AsyncSession, attempt: TestAttempt) -> dict[uuid.UUID, str]:
    """problem id -> section id for every coding item of the attempt layout."""
    by_qv = {it["qv"]: s["section_id"] for s in attempt.layout["sections"] for it in s["items"]}
    bundles = await bank.load_bundles(session, [uuid.UUID(k) for k in by_qv])
    return {
        b.version.coding_problem_id: by_qv[str(qv)]
        for qv, b in bundles.items()
        if b.qtype == grading.CODING_TYPE and b.version.coding_problem_id is not None
    }


async def validate_coding_attempt(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID, problem_id: uuid.UUID
) -> None:
    """``coding.service.AttemptValidator``: the attempt must be the caller's, in progress, bound
    to this session, and contain ``problem_id`` in a section that is currently open."""
    from app.modules.assessments import attempts as svc

    att, test = await svc.load_owned(session, principal, attempt_id, lock=True)
    if await svc.expire_if_due(session, att, test) or att.status != "in_progress":
        raise ProblemError("attempt_closed", detail="This attempt is not accepting answers any more.")
    await svc.ensure_bound(session, principal, att, test)
    items = await coding_problem_items(session, att)
    section = items.get(problem_id)
    if section is None:
        raise ProblemError("not_found", detail="This coding problem is not part of your attempt.")
    open_sections = {
        str(s.test_section_id) for s in await svc.attempt_sections(session, att.id) if s.status == "active"
    }
    if section not in open_sections:
        raise ProblemError("section_locked", section_id=section)


async def check_pinned_submission(
    session: AsyncSession, attempt: TestAttempt, problem_id: uuid.UUID | None, response: dict[str, Any] | None
) -> None:
    """Autosave guard: a pinned submission must belong to this attempt and problem."""
    if not response or not response.get("submission_id"):
        return
    from app.modules.coding import public as coding_public

    sub = await coding_public.get_submission(session, uuid.UUID(response["submission_id"]))
    if (
        sub is None
        or sub.attempt_id != attempt.id
        or sub.user_id != attempt.user_id
        or sub.coding_problem_id != problem_id
    ):
        raise ProblemError(
            "validation_failed",
            errors=[
                {
                    "field": "response.submission_id",
                    "code": "invalid",
                    "message": "submission does not belong to this attempt and problem",
                }
            ],
        )


async def _scored_submission(
    session: AsyncSession,
    attempt: TestAttempt,
    problem_id: uuid.UUID,
    response: dict[str, Any] | None,
) -> Any:
    """The submission that counts for ``problem_id``: the pinned one, else the newest judged."""
    from app.modules.coding import public as coding_public

    subs = await coding_public.attempt_submissions(
        session, attempt_id=attempt.id, user_id=attempt.user_id, problem_id=problem_id, mode="submit"
    )
    pin = response.get("submission_id") if response else None
    if pin:
        return next((x for x in subs if str(x.id) == str(pin)), None)
    done = [x for x in subs if x.status == "completed"]
    # ORDER BY completed_at DESC, id DESC (completed rows always carry completed_at)
    done.sort(key=lambda x: (x.completed_at is not None, x.completed_at, x.id), reverse=True)
    return done[0] if done else None


async def coding_outcome(
    session: AsyncSession,
    attempt: TestAttempt,
    problem_id: uuid.UUID | None,
    response: dict[str, Any] | None,
) -> tuple[bool | None, Decimal]:
    """(is_correct, fraction of marks). ``(None, 0)`` = unanswered / not judged yet."""
    if problem_id is None:
        return None, Decimal("0")
    sub = await _scored_submission(session, attempt, problem_id, response)
    if sub is None or sub.status != "completed":
        return None, Decimal("0")
    if sub.max_score and sub.max_score > 0 and sub.score is not None:
        frac = max(Decimal("0"), min(Decimal("1"), Decimal(sub.score) / Decimal(sub.max_score)))
    else:
        frac = Decimal("1") if sub.verdict == "AC" else Decimal("0")
    return sub.verdict == "AC", frac


async def coding_review(
    session: AsyncSession,
    attempt: TestAttempt,
    problem_id: uuid.UUID | None,
    response: dict[str, Any] | None,
    *,
    with_verdicts: bool,
) -> dict[str, Any] | None:
    """ATT-12 detail for a coding item (BE-23): the learner's own scored submission with its
    source; per-case verdicts only when correctness is visible. Hidden cases stay verdict-only
    (``coding.service.submission_view``)."""
    if problem_id is None:
        return None
    from app.modules.coding.public import submission_view

    sub = await _scored_submission(session, attempt, problem_id, response)
    if sub is None:
        return None
    view = (await submission_view(session, sub, include_source=True)).model_dump(mode="json")
    if not with_verdicts:
        for k in ("verdict", "score", "max_score", "passed_cases", "total_cases", "cases"):
            view.pop(k, None)
    return view


async def on_submission_judged(session: AsyncSession, msg: OutboxMessage) -> None:
    """Outbox handler: a late verdict for an already-scored attempt re-scores it.

    On the Firestore store the relay passes ``None`` (no Postgres) or a session the engine cannot
    use: the handler then runs in its own engine transaction (``store_session``, system scope),
    committed when it returns -- the Postgres relay's per-event transaction equivalent."""
    from app.modules.placement.rls import memory_gucs

    if adb.on_firestore() and memory_gucs(session) is None:
        from app.core.db import system_context
        from app.core.firestore.sqlstore import store_session

        async with store_session() as fs_session:
            await system_context(fs_session, "assessments.submission_judged")
            await _on_submission_judged(fs_session, msg)
        return
    await _on_submission_judged(session, msg)


async def _on_submission_judged(session: AsyncSession, msg: OutboxMessage) -> None:
    from app.modules.assessments.attempts import score_attempt
    from app.modules.coding import public as coding_public

    if msg.payload.get("mode") != "submit":
        return
    try:
        sub_id = uuid.UUID(str(msg.payload.get("submission_id")))
    except ValueError:
        return
    sub = await coding_public.get_submission(session, sub_id)
    if sub is None or sub.attempt_id is None:
        return
    attempt = await adb.get(session, TestAttempt, sub.attempt_id, with_for_update=True)
    if attempt is None or attempt.status not in ("graded", "awaiting_manual"):
        return  # still in progress: the final scoring will see the verdict
    existing = await adb.get(session, AttemptResult, attempt.id)
    if existing is None or existing.graded_at is None:
        return
    if sub.completed_at is not None and sub.completed_at <= existing.graded_at:
        return  # already reflected
    test = await adb.get(session, Test, attempt.test_id)
    if test is None:  # pragma: no cover - FK
        return
    await score_attempt(session, attempt, test, scoring_version=existing.scoring_version + 1)
