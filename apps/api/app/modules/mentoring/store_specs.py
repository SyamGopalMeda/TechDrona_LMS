# ruff: noqa: E501 - the data-model tables in the docstring are wide
"""Firestore data model of ``mentoring`` (MIGRATION-PLAN §3.1 "mentoring"; docs/firebase/agents/data-learning.md).

Moved together by ``TD_STORE_MENTORING=firestore``; repository ``repo_firestore.py``, service path
``service_fs.py``. Entitlement quotas, users/profiles, batches, audit and outbox stay on Postgres.

=====================================  ==============================================  ==================================
collection (doc id)                    holds                                           replaces
=====================================  ==============================================  ==================================
mentor_slots/{id}                      row                                             RLS TN
mentor_slot_times/{mentor:starts_at}   {slot_id} (slots not cancelled)                 ux_ms_mentor_time
mentor_bookings/{id}                   row + slot_mentor_id / slot_starts_at /         RLS U; the joins on mentor_slots
                                       slot_duration (denormalised, rewritten on
                                       reschedule in the same transaction)
mentor_slot_live/{slot_id}             {booking_id} (booked/rescheduled/completed)     ux_mb_slot_live: **no double booking**
mentor_booking_idem/{user:key}         {booking_id}                                    UNIQUE (user_id, idempotency_key)
interview_feedback/{id}                row                                             RLS U
interview_feedback_by_booking/{b}      {feedback_id}                                   UNIQUE mentor_booking_id
mentor_notes/{id}                      row                                             p_author (system family)
resumes/{id}                           row                                             RLS O
resume_versions/{user:n}               {resume_id}                                     UNIQUE (user_id, version_no)
resume_reviews/{id}                    row                                             RLS O
resume_review_open/{resume_id}         {review_id} (requested/in_review)               "one pending review" (FOR UPDATE)
=====================================  ==============================================  ==================================

Booking = one Firestore transaction: the slot must be ``open`` and ``mentor_slot_live/{slot}``
absent; the booking, the key documents and ``slot.status = booked`` commit together, so two
students can never hold the same slot.
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.backfill import TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id
from app.core.time import ensure_utc
from app.modules.mentoring.fs_rows import doc_mapper, encode
from app.modules.mentoring.models import (
    InterviewFeedback,
    MentorBooking,
    MentorNote,
    MentorSlot,
    Resume,
    ResumeReview,
)

MODULE = "mentoring"
PERM_SLOTS = "mentor.slot.manage"
PERM_FEEDBACK = "mentor.feedback.write"

SLOTS = "mentor_slots"
SLOT_TIMES = "mentor_slot_times"
BOOKINGS = "mentor_bookings"
SLOT_LIVE = "mentor_slot_live"
BOOKING_IDEM = "mentor_booking_idem"
FEEDBACK = "interview_feedback"
FEEDBACK_BY_BOOKING = "interview_feedback_by_booking"
NOTES = "mentor_notes"
RESUMES = "resumes"
RESUME_VERSIONS = "resume_versions"
REVIEWS = "resume_reviews"
REVIEW_OPEN = "resume_review_open"

LIVE_SLOT_BOOKING = ("booked", "rescheduled", "completed")
OPEN_REVIEW = ("requested", "in_review")

register_collection(CollectionSpec(SLOTS, "shared", read_permission=None, write_permission=PERM_SLOTS))
register_collection(
    CollectionSpec(BOOKINGS, "owned", read_permission=PERM_SLOTS, write_permission=PERM_SLOTS)
)
register_collection(
    CollectionSpec(FEEDBACK, "owned", read_permission=PERM_FEEDBACK, write_permission=PERM_FEEDBACK)
)
register_collection(CollectionSpec(RESUMES, "owned", read_permission=PERM_FEEDBACK, write_permission=None))
register_collection(
    CollectionSpec(REVIEWS, "owned", read_permission=PERM_FEEDBACK, write_permission=PERM_FEEDBACK)
)
for _n in (SLOT_TIMES, SLOT_LIVE, BOOKING_IDEM, FEEDBACK_BY_BOOKING, NOTES, RESUME_VERSIONS, REVIEW_OPEN):
    register_collection(CollectionSpec(_n, "system"))


def slot_time_key(mentor_id: Any, starts_at: Any) -> str:
    return compose_id(str(mentor_id), ensure_utc(starts_at).isoformat(timespec="microseconds"))


def idem_key(user_id: Any, key: str) -> str:
    return compose_id(str(user_id), key)


def version_key(user_id: Any, version_no: int) -> str:
    return compose_id(str(user_id), int(version_no))


def slot_fields(slot: Any) -> dict[str, Any]:
    """The denormalised slot fields carried on a booking document."""
    g = slot.get if isinstance(slot, dict) else (lambda k: getattr(slot, k))
    return {
        "slot_mentor_id": encode(g("mentor_id")),
        "slot_starts_at": encode(g("starts_at")),
        "slot_duration": int(g("duration_minutes") or 0),
    }


slot_doc = doc_mapper(MentorSlot)
booking_doc = doc_mapper(
    MentorBooking,
    extra=lambda r: {
        "slot_mentor_id": encode(r["s_mentor_id"]),
        "slot_starts_at": encode(r["s_starts_at"]),
        "slot_duration": int(r["s_duration"]),
    },
)
feedback_doc = doc_mapper(InterviewFeedback)
note_doc = doc_mapper(MentorNote)
resume_doc = doc_mapper(Resume)
review_doc = doc_mapper(ResumeReview)


def _ref(field: str) -> Any:
    return lambda r: {field: str(r["id"])}


def _id(r: dict[str, Any]) -> str:
    return str(r["id"])


_BOOKING_SRC = (
    "(SELECT b.*, s.mentor_id AS s_mentor_id, s.starts_at AS s_starts_at, s.duration_minutes AS s_duration "
    "FROM mentor_bookings b JOIN mentor_slots s ON s.id = b.mentor_slot_id) AS mb"
)

register_mapping(TableMapping(MODULE, "mentor_slots", SLOTS, _id, slot_doc))
register_mapping(
    TableMapping(
        MODULE,
        "mentor_slots",
        SLOT_TIMES,
        lambda r: slot_time_key(r["mentor_id"], r["starts_at"]),
        _ref("slot_id"),
        where="status <> 'cancelled'",
    )
)
register_mapping(TableMapping(MODULE, _BOOKING_SRC, BOOKINGS, _id, booking_doc))
register_mapping(
    TableMapping(
        MODULE,
        "mentor_bookings",
        SLOT_LIVE,
        lambda r: str(r["mentor_slot_id"]),
        _ref("booking_id"),
        where="status IN ('booked', 'rescheduled', 'completed')",
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "mentor_bookings",
        BOOKING_IDEM,
        lambda r: idem_key(r["user_id"], r["idempotency_key"]),
        _ref("booking_id"),
    )
)
register_mapping(TableMapping(MODULE, "interview_feedback", FEEDBACK, _id, feedback_doc))
register_mapping(
    TableMapping(
        MODULE,
        "interview_feedback",
        FEEDBACK_BY_BOOKING,
        lambda r: str(r["mentor_booking_id"]),
        _ref("feedback_id"),
    )
)
register_mapping(TableMapping(MODULE, "mentor_notes", NOTES, _id, note_doc))
register_mapping(TableMapping(MODULE, "resumes", RESUMES, _id, resume_doc))
register_mapping(
    TableMapping(
        MODULE,
        "resumes",
        RESUME_VERSIONS,
        lambda r: version_key(r["user_id"], r["version_no"]),
        _ref("resume_id"),
    )
)
register_mapping(TableMapping(MODULE, "resume_reviews", REVIEWS, _id, review_doc))
register_mapping(
    TableMapping(
        MODULE,
        "resume_reviews",
        REVIEW_OPEN,
        lambda r: str(r["resume_id"]),
        _ref("review_id"),
        where="status IN ('requested', 'in_review')",
    )
)

COLLECTIONS = (
    SLOTS,
    SLOT_TIMES,
    BOOKINGS,
    SLOT_LIVE,
    BOOKING_IDEM,
    FEEDBACK,
    FEEDBACK_BY_BOOKING,
    NOTES,
    RESUMES,
    RESUME_VERSIONS,
    REVIEWS,
    REVIEW_OPEN,
)
