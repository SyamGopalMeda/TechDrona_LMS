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


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    await system_context(session, "assessments.privacy_erase")
    att = await session.execute(
        text(
            "UPDATE test_attempts SET start_ip = NULL, "
            "idempotency_key = 'erased:' || id::text "
            "WHERE user_id = :u AND (start_ip IS NOT NULL OR idempotency_key NOT LIKE 'erased:%')"
        ),
        {"u": user_id},
    )
    resp = await session.execute(
        text("UPDATE attempt_responses SET response = NULL WHERE user_id = :u AND response IS NOT NULL"),
        {"u": user_id},
    )
    grades = await session.execute(
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


def register() -> None:
    from app.modules.admin.privacy import register_erasure_provider

    register_erasure_provider("assessments", erase_user)


register()
