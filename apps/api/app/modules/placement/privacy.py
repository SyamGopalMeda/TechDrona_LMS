"""DB-01: placement erasure provider (privacy D9/D10: practice history, recommendations,
question reports). Registered when the placement router is imported.

* ``practice_responses`` and ``practice_sessions``: deleted (no legal hold).
* ``recommendations``: deleted.
* ``question_reports``: the learner's free-text message is replaced (td_app has no DELETE on
  this table; the report itself stays for the content-quality trail).

Idempotent. Caller supplies a system context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.placement.models import PracticeResponse, PracticeSession, QuestionReport, Recommendation

ERASED_TEXT = "[erased]"


def _n(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    from app.core.firestore.backend import uses_firestore

    if uses_firestore("placement"):
        from app.modules.placement.repo_firestore import system_repo

        c = await system_repo().erase_user(user_id)
        return {
            "practice_responses_deleted": c["responses"],
            "practice_sessions_deleted": c["sessions"],
            "recommendations_deleted": c["recs"],
            "question_reports_scrubbed": c["reports"],
        }
    responses = await session.execute(delete(PracticeResponse).where(PracticeResponse.user_id == user_id))
    sessions = await session.execute(delete(PracticeSession).where(PracticeSession.user_id == user_id))
    recs = await session.execute(delete(Recommendation).where(Recommendation.user_id == user_id))
    reports = await session.execute(
        update(QuestionReport)
        .where(QuestionReport.user_id == user_id, QuestionReport.message != ERASED_TEXT)
        .values(message=ERASED_TEXT)
        .execution_options(synchronize_session=False)
    )
    await session.flush()
    return {
        "practice_responses_deleted": _n(responses),
        "practice_sessions_deleted": _n(sessions),
        "recommendations_deleted": _n(recs),
        "question_reports_scrubbed": _n(reports),
    }


def register() -> None:
    from app.modules.admin.privacy import register_erasure_provider

    register_erasure_provider("placement", erase_user)
