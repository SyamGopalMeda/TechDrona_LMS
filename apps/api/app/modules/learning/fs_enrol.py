"""Firestore queries for learning's enrolment / progress / certificate / legacy-assignment routes
(``service.py``, ``router.py``, ``privacy.py``; ``TD_STORE_LEARNING=firestore``).

Every function is the Firestore equivalent of one Postgres query in those files, with the same
filters and the same ORDER BY applied in memory (RLS family U is replaced by the explicit
``user_id`` filter the route already uses). All rows are tracked by ``fs_store`` in ``session``,
so a later ``fss.flush(session)`` persists mutations.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.learning import fs_store as fss
from app.modules.learning import store_specs as lss
from app.modules.learning.models import (
    Assignment,
    AssignmentAllocation,
    AssignmentSubmission,
    Certificate,
    Enrolment,
    LessonProgress,
)

LIVE_ENROLMENT = ("active", "completed")


def _chunks(ids: list[Any], n: int = 30) -> Iterable[list[Any]]:
    for i in range(0, len(ids), n):
        yield ids[i : i + n]


async def _in(session: Any, model: Any, field: str, values: Iterable[Any], **kw: Any) -> list[Any]:
    vals = list(dict.fromkeys(v for v in values if v is not None))
    out: list[Any] = []
    extra = kw.pop("filters", ())
    for part in _chunks(vals):
        out += await fss.find(session, model, filters=((field, "in", part), *extra), **kw)
    return out


def _desc_nulls_last(dt: datetime | None) -> tuple[int, float]:
    return (1, 0.0) if dt is None else (0, -dt.timestamp())


# --------------------------------------------------------------------------- enrolments


async def my_enrolments(session: AsyncSession, user_id: uuid.UUID) -> list[Enrolment]:
    """``ORDER BY last_activity_at DESC NULLS LAST, id DESC``."""
    rows = await fss.find(session, Enrolment, filters=(("user_id", "==", user_id),))
    rows.sort(key=lambda e: str(e.id), reverse=True)
    rows.sort(key=lambda e: _desc_nulls_last(e.last_activity_at))
    return rows


async def live_enrolments(session: AsyncSession, user_id: uuid.UUID) -> list[Enrolment]:
    return await fss.find(
        session, Enrolment, filters=(("user_id", "==", user_id),), where=lambda e: e.status in LIVE_ENROLMENT
    )


async def enrolments_on_versions(
    session: AsyncSession, user_id: uuid.UUID, version_ids: Iterable[uuid.UUID]
) -> list[Enrolment]:
    wanted = set(version_ids)
    return [e for e in await live_enrolments(session, user_id) if e.course_version_id in wanted]


async def enrolment_page(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID | None,
    course_id: uuid.UUID | None,
    after: uuid.UUID | None,
    limit: int,
) -> list[Enrolment]:
    """Staff list: ``batch_id = :b`` (else ``batch_id IS NOT NULL``), optional course, keyset on id
    (UUID order == lowercase-hex string order), ``limit + 1`` rows."""
    filters: list[Any] = []
    if batch_id is not None:
        filters.append(("batch_id", "==", batch_id))
    if course_id is not None:
        filters.append(("course_id", "==", course_id))
    rows = await fss.find(
        session,
        Enrolment,
        filters=filters,
        where=lambda e: e.batch_id is not None and (after is None or str(e.id) > str(after)),
    )
    rows.sort(key=lambda e: str(e.id))
    return rows[: limit + 1]


async def enrolled_user_ids(
    session: AsyncSession, course_id: uuid.UUID, user_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    users = set(user_ids)
    if not users:
        return set()
    rows = await fss.find(session, Enrolment, filters=(("course_id", "==", course_id),))
    return {e.user_id for e in rows if e.user_id in users}


async def completed_lesson_counts(session: AsyncSession, enrolment_ids: list[uuid.UUID]) -> dict[str, int]:
    done: dict[str, int] = {}
    for lp in await _in(
        session, LessonProgress, "enrolment_id", enrolment_ids, filters=(("status", "==", "completed"),)
    ):
        done[str(lp.enrolment_id)] = done.get(str(lp.enrolment_id), 0) + 1
    return done


# --------------------------------------------------------------------------- certificates


async def my_certificates(session: AsyncSession, user_id: uuid.UUID) -> list[Certificate]:
    """``ORDER BY issued_at DESC, id DESC``."""
    rows = await fss.find(session, Certificate, filters=(("user_id", "==", user_id),))
    rows.sort(key=lambda c: (c.issued_at, str(c.id)), reverse=True)
    return rows


async def certificate_of_enrolment(session: AsyncSession, enrolment_id: uuid.UUID) -> Certificate | None:
    cid = await fss.key_target(lss.CERT_BY_ENROLMENT, str(enrolment_id))
    return await fss.get(session, Certificate, cid) if cid else None


async def certificate_by_code(session: AsyncSession | None, public_code: str) -> Certificate | None:
    cid = await fss.key_target(lss.CERT_CODES, public_code)
    return await fss.get(session, Certificate, cid) if cid else None


# --------------------------------------------------------------------------- assignments (legacy + list)


def _visible_now(al: AssignmentAllocation, now: datetime) -> bool:
    return (
        al.status == "active"
        and (al.visible_from is None or al.visible_from <= now)
        and (al.visible_until is None or al.visible_until >= now)
    )


async def learner_allocated_ids(
    session: AsyncSession, user_id: uuid.UUID, batches: set[uuid.UUID], now: datetime
) -> set[uuid.UUID]:
    """``structured.allocated_to_learner_filter``: allocations targeting the learner (batch or
    explicit user list) that are visible now, or whose assignment the learner handed in."""
    allocs = {a.id: a for a in await _in(session, AssignmentAllocation, "batch_id", batches)}
    for a in await fss.find(
        session, AssignmentAllocation, filters=(("user_ids", "array-contains", user_id),)
    ):
        allocs[a.id] = a
    if not allocs:
        return set()
    handed_in = {
        s.assignment_id
        for s in await fss.find(session, AssignmentSubmission, filters=(("user_id", "==", user_id),))
        if s.status != "draft"
    }
    return {
        al.assignment_id for al in allocs.values() if _visible_now(al, now) or al.assignment_id in handed_in
    }


async def eligible_assignments(
    session: AsyncSession, user_id: uuid.UUID, batches: set[uuid.UUID], courses: set[uuid.UUID], now: datetime
) -> list[Assignment]:
    """``router._eligible_assignment_filter`` (legacy batch/course assignments + structured
    assignments allocated to the learner), any status."""
    picked: dict[uuid.UUID, Assignment] = {}
    for a in await _in(session, Assignment, "batch_id", batches):
        if a.submission_type != "structured":
            picked[a.id] = a
    for a in await _in(session, Assignment, "course_id", courses):
        if a.submission_type != "structured" and a.batch_id is None:
            picked[a.id] = a
    ids = await learner_allocated_ids(session, user_id, batches, now)
    missing = [i for i in ids if i not in picked]
    picked.update(await fss.get_many(session, Assignment, missing))
    return list(picked.values())


def _due_nulls_last(a: Assignment) -> tuple[int, float]:
    return (1, 0.0) if a.due_at is None else (0, a.due_at.timestamp())


def order_due_nulls_last(rows: list[Assignment]) -> list[Assignment]:
    return sorted(rows, key=_due_nulls_last)


async def submissions_of(
    session: AsyncSession,
    assignment_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[AssignmentSubmission]:
    filters: list[Any] = [("assignment_id", "==", assignment_id)]
    if user_id is not None:
        filters.append(("user_id", "==", user_id))
    if status is not None:
        filters.append(("status", "==", status))
    return await fss.find(session, AssignmentSubmission, filters=filters)


async def my_submissions(
    session: AsyncSession, user_id: uuid.UUID, assignment_ids: Iterable[uuid.UUID]
) -> list[AssignmentSubmission]:
    wanted = set(assignment_ids)
    rows = await fss.find(session, AssignmentSubmission, filters=(("user_id", "==", user_id),))
    return sorted((s for s in rows if s.assignment_id in wanted), key=lambda s: s.attempt_no)


async def staff_assignment_candidates(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    platform: bool,
    batches: set[uuid.UUID],
    courses: set[uuid.UUID],
    batch_id: uuid.UUID | None,
    course_id: uuid.UUID | None,
    status: str | None,
) -> list[Assignment]:
    """``list_assignments`` pre-filter, newest (largest id) first."""
    if platform:
        rows = await fss.find(session, Assignment)
    else:
        picked: dict[uuid.UUID, Assignment] = {}
        alloc_ids: set[uuid.UUID] = {
            al.assignment_id
            for al in await fss.find(
                session, AssignmentAllocation, filters=(("evaluator_ids", "array-contains", user_id),)
            )
        }
        for a in await _in(session, Assignment, "batch_id", batches):
            picked[a.id] = a
        for a in await _in(session, Assignment, "course_id", courses):
            picked[a.id] = a
        alloc_ids |= {
            al.assignment_id for al in await _in(session, AssignmentAllocation, "batch_id", batches)
        }
        picked.update(await fss.get_many(session, Assignment, [i for i in alloc_ids if i not in picked]))
        rows = list(picked.values())
    out = [
        a
        for a in rows
        if (batch_id is None or a.batch_id == batch_id)
        and (course_id is None or a.course_id == course_id)
        and (status is None or a.status == status)
    ]
    return sorted(out, key=lambda a: str(a.id), reverse=True)


async def pending_counts(session: AsyncSession, assignment_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    out: dict[uuid.UUID, int] = {}
    for s in await _in(session, AssignmentSubmission, "assignment_id", assignment_ids):
        if s.status in ("submitted", "late"):
            out[s.assignment_id] = out.get(s.assignment_id, 0) + 1
    return out
