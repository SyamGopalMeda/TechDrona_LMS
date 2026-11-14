"""Store-neutral API of coding for other modules (Firestore migration, round 2).

The coding service functions that other modules already call (``learning``, ``assessments``,
``wiring``) dispatch on ``TD_STORE_CODING`` inside ``service.py``; they are re-exported here so
callers have one stable import. New here: ``problem_primary_topic`` (replaces the
``coding_problems`` join in ``wiring.coding_problem_parents``, together with
``placement.public.topic_with_root``).

| Function | Used by |
|---|---|
| ``published_problem``, ``get_problem`` | learning/structured.py, placement/bank.py |
| ``verify_submission_owner`` | learning/router.py, learning/structured.py |
| ``get_attempt_judgement``, ``judge_for_attempt`` | assessments/coding.py, learning/structured.py |
| ``problem_primary_topic`` | wiring.coding_problem_parents |
| ``get_submission``, ``attempt_submissions``, ``submission_view`` | assessments/coding.py |
| ``attempt_code_signals`` | assessments/integrity.py (flags: the ``cs`` CTE of ``FLAGS_SQL``) |

Reads apply the caller's RLS on both stores: the Postgres session's policies, or on Firestore
``repo_firestore.visibility(session)`` (``MemoryTx`` GUCs, the request principal for
``NO_POSTGRES``, the system view for ``None``).
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.backend import uses_firestore
from app.modules.coding.models import CodeSubmission, CodingProblem
from app.modules.coding.service import (
    AttemptJudgement,
    AttemptSubmissionHandle,
    get_attempt_judgement,
    get_problem,
    judge_for_attempt,
    published_problem,
    submission_view,
    verify_submission_owner,
)


async def problem_primary_topic(session: AsyncSession, problem_id: uuid.UUID) -> uuid.UUID | None:
    if uses_firestore("coding"):
        from app.modules.coding import repo_firestore

        p = await (await repo_firestore.repo(session)).get_problem(problem_id)
        return p.primary_topic_id if p else None
    return (
        await session.execute(select(CodingProblem.primary_topic_id).where(CodingProblem.id == problem_id))
    ).scalar_one_or_none()


async def get_submission(session: AsyncSession | None, submission_id: uuid.UUID) -> CodeSubmission | None:
    """``session.get(CodeSubmission, id)`` (``None`` when missing or not visible)."""
    if uses_firestore("coding"):
        from app.modules.coding import repo_firestore

        return await (await repo_firestore.repo(session)).get_submission(submission_id)
    assert session is not None
    return await session.get(CodeSubmission, submission_id)


async def attempt_submissions(
    session: AsyncSession | None,
    *,
    attempt_id: uuid.UUID,
    user_id: uuid.UUID,
    problem_id: uuid.UUID,
    mode: str = "submit",
) -> list[CodeSubmission]:
    """The user's submissions for ``problem_id`` inside ``attempt_id`` (any status), oldest first."""
    if uses_firestore("coding"):
        from app.modules.coding import repo_firestore

        subs = await (await repo_firestore.repo(session)).submissions_of(
            user_id,
            (
                ("attempt_id", "==", str(attempt_id)),
                ("coding_problem_id", "==", str(problem_id)),
                ("mode", "==", mode),
            ),
        )
        return sorted(subs, key=lambda x: (x.queued_at, x.id))
    assert session is not None
    q = (
        select(CodeSubmission)
        .where(
            CodeSubmission.attempt_id == attempt_id,
            CodeSubmission.user_id == user_id,
            CodeSubmission.coding_problem_id == problem_id,
            CodeSubmission.mode == mode,
        )
        .order_by(CodeSubmission.queued_at, CodeSubmission.id)
    )
    return list((await session.execute(q)).scalars())


async def attempt_code_signals(
    session: AsyncSession | None, attempt_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """Integrity signals per attempt from its ``submit`` submissions: (max submissions on one
    problem within one clock hour of ``queued_at``, similarity-flagged submissions). Attempts
    without submissions are absent (``FLAGS_SQL`` ``cs`` CTE: ``coalesce(..., 0)`` by the caller)."""
    ids = list(dict.fromkeys(attempt_ids))
    if not ids:
        return {}
    rows: list[tuple[Any, Any, Any, int, int]] = []
    if uses_firestore("coding"):
        from app.modules.coding import repo_firestore

        r = await repo_firestore.repo(session)
        for i in range(0, len(ids), 30):  # Firestore ``in``: at most 30 values
            subs = await r.all_submissions(
                (("attempt_id", "in", [str(a) for a in ids[i : i + 30]]), ("mode", "==", "submit"))
            )
            per: Counter[tuple[Any, Any, Any]] = Counter()
            sim: Counter[tuple[Any, Any, Any]] = Counter()
            for x in subs:
                k = (
                    x.attempt_id,
                    x.coding_problem_id,
                    x.queued_at.replace(minute=0, second=0, microsecond=0),
                )
                per[k] += 1
                sim[k] += int(bool(x.similarity_flag))
            rows += [(*k, n, sim[k]) for k, n in per.items()]
    else:
        assert session is not None
        h = func.date_trunc("hour", CodeSubmission.queued_at)
        q = (
            select(
                CodeSubmission.attempt_id,
                CodeSubmission.coding_problem_id,
                h,
                func.count(),
                func.count().filter(CodeSubmission.similarity_flag.is_(True)),
            )
            .where(CodeSubmission.attempt_id.in_(ids), CodeSubmission.mode == "submit")
            .group_by(CodeSubmission.attempt_id, CodeSubmission.coding_problem_id, h)
        )
        rows = [tuple(r) for r in (await session.execute(q)).all()]
    out: dict[uuid.UUID, tuple[int, int]] = {}
    for att, _pid, _h, n, s in rows:
        burst, flags = out.get(att, (0, 0))
        out[att] = (max(burst, int(n)), flags + int(s))
    return out


__all__ = [
    "AttemptJudgement",
    "AttemptSubmissionHandle",
    "attempt_code_signals",
    "attempt_submissions",
    "get_attempt_judgement",
    "get_problem",
    "get_submission",
    "judge_for_attempt",
    "problem_primary_topic",
    "published_problem",
    "submission_view",
    "verify_submission_owner",
]
