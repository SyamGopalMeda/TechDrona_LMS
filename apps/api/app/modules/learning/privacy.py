"""DB-01: learning erasure provider (privacy D9). Registered with
``admin.privacy.register_erasure_provider`` when the learning router is imported.

* ``lesson_progress`` rows: deleted (no legal hold).
* ``assignment_submissions``: free-text answer, link and file keys cleared (the graded score
  stays for the org's aggregate reports, attached to a user id identity tombstones).
* ``certificates``: revoked (reason ``erasure``) and the printed name replaced; the row cannot be
  deleted (public-verification ledger, td_app has no DELETE) so verification reports "revoked".
* ``enrolments``: set ``withdrawn`` (no personal content; kept for referential integrity).

Idempotent: a second run changes nothing and returns zero counts. Caller supplies a system
context (``admin.privacy_erasure``)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.modules.learning.models import AssignmentSubmission, Certificate, Enrolment, LessonProgress

ERASED_NAME = "Erased learner"


def _n(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    progress = await session.execute(delete(LessonProgress).where(LessonProgress.user_id == user_id))
    subs = await session.execute(
        update(AssignmentSubmission)
        .where(
            AssignmentSubmission.user_id == user_id,
            (AssignmentSubmission.body_text.is_not(None))
            | (AssignmentSubmission.link_url.is_not(None))
            | (AssignmentSubmission.file_s3_keys != [])
            | (AssignmentSubmission.feedback_md.is_not(None)),
        )
        .values(body_text=None, link_url=None, file_s3_keys=[], feedback_md=None)
        .execution_options(synchronize_session=False)
    )
    certs = await session.execute(
        update(Certificate)
        .where(Certificate.user_id == user_id, Certificate.name_on_certificate != ERASED_NAME)
        .values(
            name_on_certificate=ERASED_NAME,
            revoked_at=func.coalesce(Certificate.revoked_at, utcnow()),
            revoke_reason=func.coalesce(Certificate.revoke_reason, "erasure"),
            pdf_s3_key=None,
        )
        .execution_options(synchronize_session=False)
    )
    enrols = await session.execute(
        update(Enrolment)
        .where(Enrolment.user_id == user_id, Enrolment.status != "withdrawn")
        .values(status="withdrawn")
        .execution_options(synchronize_session=False)
    )
    await session.flush()
    return {
        "lesson_progress_deleted": _n(progress),
        "submissions_scrubbed": _n(subs),
        "certificates_revoked": _n(certs),
        "enrolments_withdrawn": _n(enrols),
    }


def register() -> None:
    from app.modules.admin.privacy import register_erasure_provider

    register_erasure_provider("learning", erase_user)
