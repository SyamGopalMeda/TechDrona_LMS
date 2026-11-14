"""DB-01: mentoring erasure provider (résumés, interview feedback, mentor notes, bookings).
Not in admin's ``REQUIRED_ERASURE_MODULES`` list, but it holds personal data (résumé content
and PDFs), so it registers too. Registered when the mentoring router is imported.

* ``resume_reviews`` and ``resumes``: deleted (content and PDF keys; the S3 objects are left to
  the uploads-bucket lifecycle rule).
* ``interview_feedback``: free-text comments cleared (scores stay for the mentor's history).
* ``mentor_notes`` about the student: body replaced.
* ``mentor_bookings``: meeting URL cleared.

Idempotent. Caller supplies a system context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mentoring.models import InterviewFeedback, MentorBooking, MentorNote, Resume, ResumeReview

ERASED = "[erased]"


def _n(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    from app.core.firestore.backend import uses_firestore

    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.erase_user(user_id)
    reviews = await session.execute(delete(ResumeReview).where(ResumeReview.user_id == user_id))
    resumes = await session.execute(delete(Resume).where(Resume.user_id == user_id))
    feedback = await session.execute(
        update(InterviewFeedback)
        .where(InterviewFeedback.user_id == user_id, InterviewFeedback.comments.is_not(None))
        .values(comments=None)
        .execution_options(synchronize_session=False)
    )
    notes = await session.execute(
        update(MentorNote)
        .where(MentorNote.student_id == user_id, MentorNote.body != ERASED)
        .values(body=ERASED)
        .execution_options(synchronize_session=False)
    )
    bookings = await session.execute(
        update(MentorBooking)
        .where(MentorBooking.user_id == user_id, MentorBooking.meeting_url.is_not(None))
        .values(meeting_url=None)
        .execution_options(synchronize_session=False)
    )
    await session.flush()
    return {
        "resume_reviews_deleted": _n(reviews),
        "resumes_deleted": _n(resumes),
        "feedback_scrubbed": _n(feedback),
        "mentor_notes_scrubbed": _n(notes),
        "bookings_scrubbed": _n(bookings),
    }


def register() -> None:
    from app.modules.admin.public import register_erasure_provider

    register_erasure_provider("mentoring", erase_user)
