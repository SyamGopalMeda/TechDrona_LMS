"""Public, store-neutral API of ``mentoring`` for other modules (``TD_STORE_MENTORING``).

Callers: ``placement/mentoring.py`` (mentor console). Every function dispatches to Firestore
when the switch is on; none of them exposes ORM rows of the Firestore path to the caller other
than the transient instances the serializers already accept.
"""

from __future__ import annotations

from app.modules.mentoring.service import (
    booked_students,
    feedback_history,
    names,
    read_notes,
    student_summaries,
)

__all__ = ["booked_students", "feedback_history", "names", "read_notes", "student_summaries"]
