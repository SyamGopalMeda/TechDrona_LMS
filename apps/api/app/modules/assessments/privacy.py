"""Erasure provider for assessments (privacy s.8(7), DB-01): registered with
``admin.privacy.register_erasure_provider`` at import (``router.py`` imports this module).

What is erased for the user: the start IP and client idempotency keys of every attempt, and the
learner's raw answers (``attempt_responses.response``). Kept in minimal form: attempt rows,
correctness/marks and results keyed by the (tombstoned) user id, so cohort statistics, ranks of
other learners and integrity decisions stay consistent. ``attempt_events`` is append-only
(``revoke_app_writes``); it ages out with retention class R-ASSESS-EVT (24 months), which is
reported in the summary. Idempotent.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context
from app.modules.assessments import datastore as adb


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    await system_context(session, "assessments.privacy_erase")
    if adb.on_firestore():
        return await _erase_store(session, user_id)
    att = await adb.execute(
        session,
        text(
            "UPDATE test_attempts SET start_ip = NULL, "
            "idempotency_key = 'erased:' || id::text "
            "WHERE user_id = :u AND (start_ip IS NOT NULL OR idempotency_key NOT LIKE 'erased:%')"
        ),
        {"u": user_id},
    )
    resp = await adb.execute(
        session,
        text("UPDATE attempt_responses SET response = NULL WHERE user_id = :u AND response IS NOT NULL"),
        {"u": user_id},
    )
    grades = await adb.execute(
        session,
        text(
            "UPDATE attempt_item_grades SET ai_feedback = NULL, ai_criteria = NULL "
            "WHERE user_id = :u AND (ai_feedback IS NOT NULL OR ai_criteria IS NOT NULL)"
        ),
        {"u": user_id},
    )
    return {
        "test_attempts_anonymised": int(getattr(att, "rowcount", 0) or 0),
        "attempt_responses_cleared": int(getattr(resp, "rowcount", 0) or 0),
        "attempt_item_grades_ai_cleared": int(getattr(grades, "rowcount", 0) or 0),
        "retained": {"attempt_events": "append-only; purged by retention R-ASSESS-EVT (24 months)"},
    }


async def _erase_store(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """The three UPDATEs above on the Firestore store (same predicates, same counts)."""
    from sqlalchemy import select

    from app.modules.assessments.models import AttemptItemGrade, AttemptResponse, TestAttempt

    n_att = n_resp = n_grade = 0
    for a in (
        await adb.execute(session, select(TestAttempt).where(TestAttempt.user_id == user_id))
    ).scalars():
        if a.start_ip is not None or not (a.idempotency_key or "").startswith("erased:"):
            a.start_ip = None
            a.idempotency_key = f"erased:{a.id}"
            n_att += 1
    for r in (
        await adb.execute(session, select(AttemptResponse).where(AttemptResponse.user_id == user_id))
    ).scalars():
        if r.response is not None:
            r.response = None
            n_resp += 1
    for g in (
        await adb.execute(session, select(AttemptItemGrade).where(AttemptItemGrade.user_id == user_id))
    ).scalars():
        if g.ai_feedback is not None or g.ai_criteria is not None:
            g.ai_feedback = None
            g.ai_criteria = None
            n_grade += 1
    await adb.flush(session)
    return {
        "test_attempts_anonymised": n_att,
        "attempt_responses_cleared": n_resp,
        "attempt_item_grades_ai_cleared": n_grade,
        "retained": {"attempt_events": "append-only; purged by retention R-ASSESS-EVT (24 months)"},
    }


def register() -> None:
    from app.modules.admin.privacy import register_erasure_provider

    register_erasure_provider("assessments", erase_user)


register()
