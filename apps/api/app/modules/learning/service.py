"""Learning domain logic: lesson access, enrolments, server-side progress from learning
evidence, course completion and certificates.

Learning-evidence rule (brief §1, BR-EVD-01): completion never depends on time alone.

* video   — unique watched seconds >= 90% of the duration. Seconds are credited only from
            playback heartbeats whose position advance is plausible for the *server-measured*
            time between heartbeats (<= 2x speed + 5 s slack), merged into intervals
            (``lesson_progress.watched_intervals``). An analytics coverage feed can replace this
            later (``register_video_coverage_lookup``).
* article — explicit scrolled-to-end marker (LRN-06) **and** the server-observed time since
            the lesson was first opened >= 30% of the estimated reading time.
* assignment — a submission was made (LRN-10).
* quiz / coding — recorded by the owning modules through ``record_completion`` with their
            evidence (attempt / accepted submission ids).
* live_link — no automatic completion (attendance Planned).

Hooks (all optional; absent hooks fail closed):

* ``register_final_test_lookup(fn)`` — assessments: ``await fn(session, user_id, test_id) ->
  (attempt_id, score_pct) | None`` used by certificate rules with ``final_test_id``.
* ``register_video_coverage_lookup(fn)`` — analytics: ``await fn(session, user_id, lesson_key)
  -> watched_seconds | None``.

Outbox events (ids only): ``learning.enrolled``, ``learning.lesson_completed``,
``learning.course_completed``, ``learning.certificate_issued``, ``learning.certificate_revoked``,
``learning.version_migrated``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessDecision, require_access
from app.core.audit import AuditActor, audit
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import ist_date, to_rfc3339, utcnow
from app.modules.catalog import public as catalog_api
from app.modules.catalog.public import Course, CourseVersion, Lesson
from app.modules.learning import fs_store as fss
from app.modules.learning import store_specs as lss
from app.modules.learning.models import Certificate, Enrolment, LessonProgress

VIDEO_COMPLETE_RATIO = 0.9
ARTICLE_MIN_READ_RATIO = 0.3
MAX_PLAYBACK_SPEED = 2.0
CREDIT_SLACK_S = 5
CERT_TEMPLATE = "cert-v1"
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # no I, L, O, U, 0, 1
STUDENT_VISIBLE = ("published", "superseded")

FinalTestLookup = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[tuple[uuid.UUID, float] | None]]
CoverageLookup = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[int | None]]
_final_test_lookup: FinalTestLookup | None = None
_coverage_lookup: CoverageLookup | None = None


def register_final_test_lookup(fn: FinalTestLookup | None) -> None:
    global _final_test_lookup
    _final_test_lookup = fn


def register_video_coverage_lookup(fn: CoverageLookup | None) -> None:
    global _coverage_lookup
    _coverage_lookup = fn


def vf(field: str, code: str, msg: str, status: int = 422) -> ProblemError:
    return ProblemError("validation_failed", status, errors=[{"field": field, "code": code, "message": msg}])


# --------------------------------------------------------------------------- lesson access


async def student_lesson(session: AsyncSession, lesson_id: uuid.UUID) -> tuple[Lesson, CourseVersion, Course]:
    """A lesson of a published (or superseded, for pinned learners) version; drafts are 404."""
    row = await catalog_api.lesson_with_parents(session, lesson_id, version_statuses=STUDENT_VISIBLE)
    if row is None:
        raise ProblemError("not_found")
    return row


async def check_lesson_access(
    session: AsyncSession, principal: Principal, lesson: Lesson, course: Course
) -> AccessDecision:
    """Free-preview lessons: any signed-in user. Everything else: the entitlement checker
    (free courses pass without one; paid content fails closed until entitlements registers).

    Courses the learner could not enrol in (``private`` visibility, unpublished, a company
    course for someone outside the company's batches/staff) are 404 unless the learner already
    holds an active/completed enrolment (pinned learners of an archived course keep access) - BE-05."""
    if not course_enrollable(course, principal):
        enr = await get_enrolment(session, principal.user_id, course.id)
        if enr is None or enr.status not in ("active", "completed"):
            raise ProblemError("not_found")
    if lesson.is_free_preview:
        return AccessDecision(True, "free_preview")
    return await require_access(session, principal, "course", course.id, is_free=course.is_free)


def course_enrollable(course: Course, principal: Principal) -> bool:
    if course.status != "published" or course.current_version_id is None or course.deleted_at:
        return False
    if course.organization_id is not None:
        # Company course (trainer-authored): batch learners and staff of the company only.
        return course.organization_id in principal.org_ids
    return course.visibility in ("public", "unlisted")


async def lock_enrolment(session: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID) -> None:
    """DB-03: serialise check-then-create of one (user, course) enrolment for this transaction,
    so concurrent requests (double click, two tabs) see the winner's row instead of 500ing on
    the unique constraint."""
    if fss.fs():  # Firestore: the enrolment_keys/{user:course} key document enforces it
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"enrol:{user_id}:{course_id}"}
    )


async def get_enrolment(session: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID) -> Enrolment | None:
    if fss.fs():
        eid = await fss.key_target(lss.ENROLMENT_KEYS, lss.enrolment_key(user_id, course_id))
        return await fss.get(session, Enrolment, eid) if eid else None
    return (
        await session.execute(
            select(Enrolment).where(Enrolment.user_id == user_id, Enrolment.course_id == course_id)
        )
    ).scalar_one_or_none()


async def create_enrolment(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    course: Course,
    source: str,
    entitlement_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> Enrolment:
    assert course.current_version_id is not None
    enr = Enrolment(
        id=uuid7(),
        user_id=user_id,
        course_id=course.id,
        course_version_id=course.current_version_id,
        organization_id=organization_id if organization_id is not None else course.organization_id,
        batch_id=batch_id,
        source=source,
        entitlement_id=entitlement_id,
        status="active",
        expires_at=expires_at,
    )
    if fss.fs():
        try:
            fss.add(session, enr)
            await fss.flush(session, raise_unique=True)
        except fss.UniqueConflict as exc:  # a concurrent enrolment holds the (user, course) key
            raise ProblemError(
                "invalid_state_transition", detail="You are already enrolled in this course."
            ) from exc
    else:
        try:
            async with session.begin_nested():
                session.add(enr)
                await session.flush()
        except IntegrityError as exc:  # DB-03: a concurrent enrolment won the unique (user, course)
            raise ProblemError(
                "invalid_state_transition", detail="You are already enrolled in this course."
            ) from exc
    await emit_event(
        session,
        "learning.enrolled",
        {
            "enrolment_id": str(enr.id),
            "user_id": str(user_id),
            "course_id": str(course.id),
            "source": source,
            "batch_id": str(batch_id) if batch_id else None,
        },
        aggregate_type="enrolment",
        aggregate_id=enr.id,
        organization_id=enr.organization_id,
    )
    return enr


def _source_for(course: Course, decision: AccessDecision) -> tuple[str, uuid.UUID | None]:
    if decision.entitlement_ids:
        return "entitlement", decision.entitlement_ids[0]
    if course.is_free or decision.reason == "free":
        return "free", None
    return "manual", None


async def self_enrol(session: AsyncSession, principal: Principal, course: Course) -> tuple[Enrolment, bool]:
    """LRN-03: free course, or a course covered by an entitlement (checked server-side)."""
    if not course_enrollable(course, principal):
        raise ProblemError("not_found")
    await lock_enrolment(session, principal.user_id, course.id)
    existing = await get_enrolment(session, principal.user_id, course.id)
    if existing is not None and existing.status in ("active", "completed"):
        return existing, False
    decision = await require_access(session, principal, "course", course.id, is_free=course.is_free)
    source, ent = _source_for(course, decision)
    if existing is not None:  # withdrawn / expired / suspended -> reactivate on the current version
        existing.status = "active"
        existing.source = source
        existing.entitlement_id = ent
        existing.expires_at = decision.expires_at
        await fss.flush(session)
        return existing, True
    try:
        enr = await create_enrolment(
            session,
            user_id=principal.user_id,
            course=course,
            source=source,
            entitlement_id=ent,
            expires_at=decision.expires_at,
        )
    except ProblemError:
        winner = await _race_winner(session, principal.user_id, course.id)
        if winner is None:
            raise
        return winner, False
    return enr, True


async def _race_winner(session: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID) -> Enrolment | None:
    """Firestore: a concurrent request created the (user, course) enrolment first. Postgres
    serialises the two with ``lock_enrolment`` and the second one returns the winner's row;
    here the loser's insert fails on ``enrolment_keys`` and returns the winner the same way."""
    if not fss.fs():
        return None
    winner = await get_enrolment(session, user_id, course_id)
    return winner if winner is not None and winner.status in ("active", "completed") else None


async def enrolment_for_lesson(
    session: AsyncSession, principal: Principal, lesson: Lesson, course: Course, decision: AccessDecision
) -> Enrolment | None:
    """The learner's enrolment (created on first use when access allows, FR-LRN-001).
    Free-preview access without enrolment returns None (no progress tracked)."""
    enr = await get_enrolment(session, principal.user_id, course.id)
    if enr is not None and enr.status in ("active", "completed"):
        return enr
    if decision.reason == "free_preview" and not course.is_free:
        return None
    if not course_enrollable(course, principal):
        return None
    if enr is None:
        await lock_enrolment(session, principal.user_id, course.id)
        raced = await get_enrolment(session, principal.user_id, course.id)
        if raced is not None:
            return raced if raced.status in ("active", "completed") else None
        source, ent = _source_for(course, decision)
        try:
            return await create_enrolment(
                session,
                user_id=principal.user_id,
                course=course,
                source=source,
                entitlement_id=ent,
                expires_at=decision.expires_at,
            )
        except ProblemError:
            winner = await _race_winner(session, principal.user_id, course.id)
            if winner is None:
                raise
            return winner
    return None


async def pinned_lesson(session: AsyncSession, enrolment: Enrolment, lesson: Lesson) -> Lesson:
    """Map a lesson onto the enrolment's pinned version by ``lesson_key``."""
    if lesson.course_version_id == enrolment.course_version_id:
        return lesson
    found = await catalog_api.find_lessons(
        session, version_id=enrolment.course_version_id, lesson_key=lesson.lesson_key
    )
    other = found[0] if found else None
    if other is None:
        raise ProblemError("not_found", detail="This lesson is not part of your course version.")
    return other


# --------------------------------------------------------------------------- progress


async def get_progress(
    session: AsyncSession, enrolment: Enrolment, lesson_key: uuid.UUID, *, create: bool = True
) -> LessonProgress | None:
    if fss.fs():
        lp = await fss.get(session, LessonProgress, lss.progress_id(enrolment.id, lesson_key))
    else:
        lp = await session.get(LessonProgress, (enrolment.id, lesson_key))
    if lp is None and create:
        lp = LessonProgress(
            enrolment_id=enrolment.id,
            lesson_key=lesson_key,
            user_id=enrolment.user_id,
            organization_id=enrolment.organization_id,
            status="not_started",
            progress_pct=Decimal(0),
            watched_seconds=0,
            watched_intervals=[],
        )
        fss.add(session, lp)
        await fss.flush(session)
    return lp


async def mark_opened(session: AsyncSession, enrolment: Enrolment, lesson: Lesson) -> LessonProgress:
    lp = await get_progress(session, enrolment, lesson.lesson_key)
    assert lp is not None
    now = utcnow()
    if lp.first_opened_at is None:
        lp.first_opened_at = now
    if lp.status == "not_started":
        lp.status = "in_progress"
    enrolment.last_activity_at = now
    await fss.flush(session)
    return lp


def merge_intervals(intervals: list[list[int]], new: tuple[int, int]) -> list[list[int]]:
    items = sorted([*([a, b] for a, b in intervals), [new[0], new[1]]])
    out: list[list[int]] = []
    for a, b in items:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def covered_seconds(intervals: list[list[int]]) -> int:
    return sum(max(0, b - a) for a, b in intervals)


def plausible_advance(prev_pos: int | None, new_pos: int, elapsed_s: float) -> bool:
    if prev_pos is None or new_pos <= prev_pos:
        return False
    return (new_pos - prev_pos) <= elapsed_s * MAX_PLAYBACK_SPEED + CREDIT_SLACK_S


async def record_video_heartbeat(
    session: AsyncSession,
    principal: Principal,
    lesson: Lesson,
    course: Course,
    *,
    prev_pos: int | None,
    new_pos: int,
    elapsed_s: float,
    playing: bool,
    duration_s: int | None,
) -> bool:
    """Credit watched seconds from a playback heartbeat; complete the lesson at >= 90%.
    Returns True when the position advanced plausibly (engagement credited)."""
    enr = await get_enrolment(session, principal.user_id, course.id)
    if enr is None or enr.status not in ("active", "completed"):
        return playing and plausible_advance(prev_pos, new_pos, elapsed_s)
    try:
        target = await pinned_lesson(session, enr, lesson)
    except ProblemError:
        return False
    lp = await get_progress(session, enr, target.lesson_key)
    assert lp is not None
    now = utcnow()
    lp.video_position_s = new_pos
    if lp.first_opened_at is None:
        lp.first_opened_at = now
    if lp.status == "not_started":
        lp.status = "in_progress"
    credited = playing and plausible_advance(prev_pos, new_pos, elapsed_s)
    duration = duration_s or target.duration_seconds
    if credited and prev_pos is not None:
        end = min(new_pos, duration) if duration else new_pos
        if end > prev_pos:
            lp.watched_intervals = merge_intervals(list(lp.watched_intervals or []), (prev_pos, end))
            lp.watched_seconds = covered_seconds(lp.watched_intervals)
    if _coverage_lookup is not None:
        ext = await _coverage_lookup(session, principal.user_id, target.lesson_key)
        if ext is not None:
            # BE-01 (learning side): analytics coverage never exceeds the lesson's duration.
            if duration:
                ext = min(ext, duration)
            lp.watched_seconds = max(lp.watched_seconds, ext)
    if duration:
        lp.progress_pct = Decimal(min(100, round(100 * lp.watched_seconds / duration, 2))).quantize(
            Decimal("0.01")
        )
    enr.last_activity_at = now
    await fss.flush(session)
    if (
        lp.status != "completed"
        and duration
        and lp.watched_seconds >= VIDEO_COMPLETE_RATIO * duration
        and target.lesson_type == "video"
    ):
        await complete_lesson(
            session,
            enr,
            target,
            lp,
            {"kind": "video_coverage", "watched_seconds": lp.watched_seconds, "duration_seconds": duration},
        )
    return credited


async def record_article_completion(
    session: AsyncSession, enrolment: Enrolment, lesson: Lesson, evidence: dict[str, Any]
) -> LessonProgress:
    # LRN-06: article and PDF lessons complete on the scrolled-to-end evidence (FR-CAT-001 pdf).
    if lesson.lesson_type not in ("article", "pdf"):
        raise ProblemError(
            "invalid_state_transition",
            detail={
                "video": "Video lessons complete automatically when you have watched 90% of the video.",
                "quiz": "Quiz lessons complete when the quiz is submitted.",
                "practice_set": "Practice-set lessons complete when the practice set is submitted.",
                "coding": "Coding lessons complete when a solution is accepted.",
                "assignment": "Assignment lessons complete when you submit the assignment.",
            }.get(lesson.lesson_type, "This lesson cannot be completed here."),
        )
    if evidence.get("scrolled_to_end") is not True:
        raise vf("evidence.scrolled_to_end", "required", "Read to the end of the lesson first")
    lp = await get_progress(session, enrolment, lesson.lesson_key)
    assert lp is not None
    if lp.status == "completed":
        return lp
    if lp.first_opened_at is None:
        raise ProblemError("invalid_state_transition", detail="Open the lesson before marking it complete.")
    minutes = lesson.est_reading_minutes or 1
    needed = max(10.0, ARTICLE_MIN_READ_RATIO * minutes * 60)
    elapsed = (utcnow() - lp.first_opened_at).total_seconds()
    if elapsed < needed:
        raise ProblemError(
            "invalid_state_transition",
            detail="Keep reading — this lesson can be completed a little later.",
            retry_after_seconds=int(needed - elapsed) + 1,
        )
    await complete_lesson(
        session,
        enrolment,
        lesson,
        lp,
        {"kind": "article_read", "scrolled_to_end": True, "server_elapsed_s": int(elapsed)},
    )
    return lp


async def record_completion(
    session: AsyncSession, user_id: uuid.UUID, lesson_key: uuid.UUID, evidence: dict[str, Any]
) -> bool:
    """For other modules (assessments, coding, assignments): mark a lesson completed with
    server-verifiable evidence (e.g. ``{"kind": "quiz_submitted", "attempt_id": ...}``).
    Returns False when the user has no active enrolment containing the lesson."""
    if not evidence.get("kind"):
        raise ValueError("evidence.kind is required")
    lessons = await catalog_api.find_lessons(session, lesson_key=lesson_key)
    by_version: dict[uuid.UUID, list[Lesson]] = {}
    for le in lessons:
        by_version.setdefault(le.course_version_id, []).append(le)
    enrols = (
        await _enrolments_on_versions(session, user_id, list(by_version))
        if fss.fs() and by_version
        else list(
            (
                await session.execute(
                    select(Enrolment).where(
                        Enrolment.user_id == user_id,
                        Enrolment.status.in_(("active", "completed")),
                        Enrolment.course_version_id.in_(list(by_version)),
                    )
                )
            ).scalars()
        )
        if by_version
        else []
    )
    rows = [(enr, le) for enr in enrols for le in by_version[enr.course_version_id]]
    done = False
    for enr, lesson in rows:
        lp = await get_progress(session, enr, lesson.lesson_key)
        assert lp is not None
        if lp.status != "completed":
            await complete_lesson(session, enr, lesson, lp, evidence)
        done = True
    return done


async def complete_lesson(
    session: AsyncSession, enrolment: Enrolment, lesson: Lesson, lp: LessonProgress, evidence: dict[str, Any]
) -> None:
    now = utcnow()
    lp.status = "completed"
    lp.completed_at = now
    lp.progress_pct = Decimal(100)
    lp.evidence = evidence
    enrolment.last_activity_at = now
    await fss.flush(session)
    await emit_event(
        session,
        "learning.lesson_completed",
        {
            "enrolment_id": str(enrolment.id),
            "user_id": str(enrolment.user_id),
            "course_id": str(enrolment.course_id),
            "course_version_id": str(enrolment.course_version_id),
            "lesson_key": str(lesson.lesson_key),
            "lesson_type": lesson.lesson_type,
            "evidence_kind": evidence.get("kind"),
        },
        aggregate_type="enrolment",
        aggregate_id=enrolment.id,
        organization_id=enrolment.organization_id,
    )
    await recompute(session, enrolment)


async def required_keys(session: AsyncSession, version_id: uuid.UUID) -> list[uuid.UUID]:
    return [
        le.lesson_key
        for le in await catalog_api.find_lessons(session, version_id=version_id, required_only=True)
    ]


async def progress_map(session: AsyncSession, enrolment_id: uuid.UUID) -> dict[uuid.UUID, LessonProgress]:
    if fss.fs():
        rows = await fss.find(session, LessonProgress, filters=(("enrolment_id", "==", enrolment_id),))
        return {lp.lesson_key: lp for lp in rows}
    return {
        lp.lesson_key: lp
        for lp in (
            await session.execute(select(LessonProgress).where(LessonProgress.enrolment_id == enrolment_id))
        ).scalars()
    }


async def recompute(session: AsyncSession, enrolment: Enrolment) -> None:
    keys = await required_keys(session, enrolment.course_version_id)
    pm = await progress_map(session, enrolment.id)
    done = sum(1 for k in keys if (lp := pm.get(k)) is not None and lp.status == "completed")
    pct = Decimal(100) if not keys else Decimal(round(100 * done / len(keys), 2)).quantize(Decimal("0.01"))
    if fss.fs():
        # the enrolment's progress and completion are written in one transaction on the fresh row
        now = utcnow()

        def step(rows: dict[uuid.UUID, Enrolment]) -> bool:
            e = rows.get(enrolment.id)
            if e is None:
                return False
            e.progress_pct = pct
            if keys and done == len(keys) and e.status == "active":
                e.status, e.completed_at = "completed", now
                return True
            return False

        completed, rows = await fss.locked(session, Enrolment, [enrolment.id], step)
        if enrolment.id in rows:
            fss.copy_into(enrolment, rows[enrolment.id])
    else:
        enrolment.progress_pct = pct
        await fss.flush(session)
        completed = bool(keys and done == len(keys) and enrolment.status == "active")
        if completed:
            enrolment.status = "completed"
            enrolment.completed_at = utcnow()
            await fss.flush(session)
    if completed:
        await emit_event(
            session,
            "learning.course_completed",
            {
                "enrolment_id": str(enrolment.id),
                "user_id": str(enrolment.user_id),
                "course_id": str(enrolment.course_id),
                "course_version_id": str(enrolment.course_version_id),
            },
            aggregate_type="enrolment",
            aggregate_id=enrolment.id,
            organization_id=enrolment.organization_id,
        )
    await maybe_issue_certificate(session, enrolment)


# --------------------------------------------------------------------------- certificates


def new_public_code(n: int = 12) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(n))


async def certificate_eligibility(session: AsyncSession, enrolment: Enrolment) -> dict[str, Any]:
    version = (await catalog_api.get_versions(session, [enrolment.course_version_id])).get(
        enrolment.course_version_id
    )
    rule = version.certificate_rule if version else None
    if not rule:
        return {"eligible": False, "reason": "no_certificate"}
    need = int(rule.get("required_lessons_pct", 100))
    if float(enrolment.progress_pct) < need:
        return {"eligible": False, "reason": "lessons_incomplete", "required_lessons_pct": need}
    test_id = rule.get("final_test_id")
    if test_id:
        if _final_test_lookup is None:
            return {"eligible": False, "reason": "final_test_pending"}
        res = await _final_test_lookup(session, enrolment.user_id, uuid.UUID(str(test_id)))
        min_pct = float(rule.get("final_test_min_pct") or 60)
        if res is None or res[1] < min_pct:
            return {"eligible": False, "reason": "final_test_pending", "final_test_min_pct": min_pct}
        return {"eligible": True, "final_attempt_id": res[0]}
    return {"eligible": True, "final_attempt_id": None}


async def _name_for(session: AsyncSession, user_id: uuid.UUID) -> str:
    from app.modules.identity import public as identity_public

    profile = await identity_public.get_profile(session, user_id)
    name = profile.full_name if profile is not None else None
    return (name or "Learner").strip()[:200]


async def issue_certificate(
    session: AsyncSession,
    enrolment: Enrolment,
    *,
    source: str,
    final_attempt_id: uuid.UUID | None = None,
) -> Certificate:
    if fss.fs():
        existing: Any = await fss.key_target(lss.CERT_BY_ENROLMENT, str(enrolment.id))
    else:
        existing = (
            await session.execute(select(Certificate).where(Certificate.enrolment_id == enrolment.id))
        ).scalar_one_or_none()
    if existing is not None:
        raise ProblemError(
            "invalid_state_transition", detail="A certificate already exists for this enrolment."
        )
    version = (await catalog_api.get_versions(session, [enrolment.course_version_id])).get(
        enrolment.course_version_id
    )
    assert version is not None
    name = await _name_for(session, enrolment.user_id)
    now = utcnow()
    for _ in range(5):
        code = new_public_code()
        if fss.fs():
            clash: Any = await fss.key_target(lss.CERT_CODES, code)
        else:
            clash = (
                await session.execute(select(Certificate.id).where(Certificate.public_code == code))
            ).first()
        if clash is None:
            break
    else:  # pragma: no cover - 30^12 space
        raise ProblemError("internal_error", 500)
    content = {
        "public_code": code,
        "user_id": str(enrolment.user_id),
        "name": name,
        "course_id": str(enrolment.course_id),
        "course_version_id": str(version.id),
        "course_title": version.title,
        "issued_at": to_rfc3339(now),
        "template": CERT_TEMPLATE,
    }
    cert = Certificate(
        id=uuid7(),
        public_code=code,
        user_id=enrolment.user_id,
        organization_id=enrolment.organization_id,
        course_id=enrolment.course_id,
        course_version_id=version.id,
        enrolment_id=enrolment.id,
        name_on_certificate=name,
        identity_verified=False,
        final_attempt_id=final_attempt_id,
        issue_source=source,
        template_version=CERT_TEMPLATE,
        content_hash=hashlib.sha256(json.dumps(content, sort_keys=True).encode()).digest(),
        issued_at=now,
    )
    fss.add(session, cert)
    await fss.flush(session)
    await emit_event(
        session,
        "learning.certificate_issued",
        {
            "certificate_id": str(cert.id),
            "user_id": str(cert.user_id),
            "course_id": str(cert.course_id),
            "enrolment_id": str(enrolment.id),
            "issue_source": source,
        },
        aggregate_type="certificate",
        aggregate_id=cert.id,
        organization_id=cert.organization_id,
    )
    return cert


async def maybe_issue_certificate(session: AsyncSession, enrolment: Enrolment) -> Certificate | None:
    if enrolment.status not in ("active", "completed"):
        return None
    if fss.fs():
        existing: Any = await fss.key_target(lss.CERT_BY_ENROLMENT, str(enrolment.id))
    else:
        existing = (
            await session.execute(select(Certificate.id).where(Certificate.enrolment_id == enrolment.id))
        ).first()
    if existing is not None:
        return None
    el = await certificate_eligibility(session, enrolment)
    if not el["eligible"]:
        return None
    return await issue_certificate(
        session, enrolment, source="rule", final_attempt_id=el.get("final_attempt_id")
    )


def certificate_out(c: Certificate, course_title: str | None = None) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "public_code": c.public_code,
        "course_id": str(c.course_id),
        "course_title": course_title,
        "name_on_certificate": c.name_on_certificate,
        "issued_at": to_rfc3339(c.issued_at),
        "status": "revoked" if c.revoked_at else "valid",
        "revoked_at": to_rfc3339(c.revoked_at) if c.revoked_at else None,
        "verify_url": f"/verify/{c.public_code}",
        "pdf_available": c.pdf_s3_key is not None,
    }


async def revoke_certificate(
    session: AsyncSession, principal: Principal | AuditActor, cert: Certificate, reason: str
) -> Certificate:
    if fss.fs():
        cert = await _revoke_fs(session, cert, reason)
    else:
        if cert.revoked_at is not None:
            raise ProblemError("invalid_state_transition", detail="Certificate already revoked.")
        cert.revoked_at = utcnow()
        cert.revoke_reason = reason
        await fss.flush(session)
    await audit(
        session,
        principal,
        "certificate.revoke",
        "certificate",
        cert.id,
        organization_id=cert.organization_id,
        subject_user_id=cert.user_id,
        reason=reason,
        after={"revoked_at": cert.revoked_at},
    )
    await emit_event(
        session,
        "learning.certificate_revoked",
        {"certificate_id": str(cert.id), "user_id": str(cert.user_id), "course_id": str(cert.course_id)},
        aggregate_type="certificate",
        aggregate_id=cert.id,
        organization_id=cert.organization_id,
    )
    return cert


async def _revoke_fs(session: AsyncSession, cert: Certificate, reason: str) -> Certificate:
    """Firestore: check-and-revoke in one transaction (the Postgres row lock), so two revokers
    cannot both pass the "not revoked yet" check."""
    now = utcnow()

    def step(rows: dict[uuid.UUID, Certificate]) -> None:
        c = rows.get(cert.id)
        if c is None:
            raise ProblemError("not_found")
        if c.revoked_at is not None:
            raise ProblemError("invalid_state_transition", detail="Certificate already revoked.")
        c.revoked_at = now
        c.revoke_reason = reason

    _, rows = await fss.locked(session, Certificate, [cert.id], step)
    fresh = rows[cert.id]
    if fresh is not cert:
        for col in Certificate.__table__.columns:
            setattr(cert, col.key, getattr(fresh, col.key))
    return cert


async def _revoke_all_fs(
    session: AsyncSession, actor: Principal | AuditActor, certs: list[Certificate], reason: str
) -> list[uuid.UUID]:
    """Bulk revoke on Firestore: a certificate revoked concurrently is skipped, as the Postgres
    ``... WHERE revoked_at IS NULL FOR UPDATE`` re-check after the lock wait skips it."""
    out: list[uuid.UUID] = []
    for cert in sorted(certs, key=lambda c: c.id):
        try:
            await revoke_certificate(session, actor, cert, reason)
        except ProblemError as e:
            if e.code == "invalid_state_transition":
                continue
            raise
        out.append(cert.id)
    return out


async def revoke_certificates_for_entitlement(
    session: AsyncSession,
    actor: Principal | AuditActor,
    entitlement_id: uuid.UUID,
    *,
    reason: str = "entitlement_revoked",
) -> list[uuid.UUID]:
    """Public (COM-12 / BR-ENT-10): revoke the live certificates issued on enrolments that were
    granted by ``entitlement_id``. Callable from commerce/entitlements consumers (e.g. an
    ``entitlement.revoked`` with reason ``refund``); idempotent - already revoked certificates
    are skipped. Returns the ids revoked."""
    if fss.fs():
        return await _revoke_all_fs(
            session, actor, await _certificates_for_entitlement(session, entitlement_id), reason
        )
    certs = (
        await session.execute(
            select(Certificate)
            .join(Enrolment, Enrolment.id == Certificate.enrolment_id)
            .where(Enrolment.entitlement_id == entitlement_id, Certificate.revoked_at.is_(None))
            .order_by(Certificate.id)
            .with_for_update(of=Certificate)
        )
    ).scalars()
    out: list[uuid.UUID] = []
    for cert in list(certs):
        await revoke_certificate(session, actor, cert, reason)
        out.append(cert.id)
    return out


async def revoke_certificates_for_courses(
    session: AsyncSession,
    actor: Principal | AuditActor,
    user_id: uuid.UUID,
    course_ids: set[uuid.UUID] | list[uuid.UUID],
    *,
    reason: str = "refund",
) -> list[uuid.UUID]:
    """Public (COM-12 / BR-ENT-10): revoke ``user_id``'s live certificates for ``course_ids``
    (e.g. the courses of a refunded product). Idempotent; returns the ids revoked."""
    ids = list(course_ids)
    if not ids:
        return []
    if fss.fs():
        fs_certs = await fss.find(
            session,
            Certificate,
            filters=(("user_id", "==", user_id),),
            where=lambda c: c.course_id in ids and c.revoked_at is None,
        )
        return await _revoke_all_fs(session, actor, fs_certs, reason)
    certs = (
        await session.execute(
            select(Certificate)
            .where(
                Certificate.user_id == user_id,
                Certificate.course_id.in_(ids),
                Certificate.revoked_at.is_(None),
            )
            .order_by(Certificate.id)
            .with_for_update()
        )
    ).scalars()
    out: list[uuid.UUID] = []
    for cert in list(certs):
        await revoke_certificate(session, actor, cert, reason)
        out.append(cert.id)
    return out


# --------------------------------------------------------------------------- versions


async def migrate_version(session: AsyncSession, enrolment: Enrolment, course: Course) -> bool:
    if course.current_version_id is None or enrolment.course_version_id == course.current_version_id:
        return False
    if fss.fs():
        return await _migrate_version_fs(session, enrolment, course)
    old = enrolment.course_version_id
    enrolment.course_version_id = course.current_version_id
    await fss.flush(session)
    await emit_event(
        session,
        "learning.version_migrated",
        {
            "enrolment_id": str(enrolment.id),
            "user_id": str(enrolment.user_id),
            "course_id": str(course.id),
            "from_version_id": str(old),
            "to_version_id": str(course.current_version_id),
        },
        aggregate_type="enrolment",
        aggregate_id=enrolment.id,
        organization_id=enrolment.organization_id,
    )
    if enrolment.status == "completed":
        # New required lessons re-open the course; existing completions are kept by lesson_key.
        keys = await required_keys(session, enrolment.course_version_id)
        pm = await progress_map(session, enrolment.id)
        if any((lp := pm.get(k)) is None or lp.status != "completed" for k in keys):
            enrolment.status = "active"
            enrolment.completed_at = None
    await recompute(session, enrolment)
    return True


async def _migrate_version_fs(session: AsyncSession, enrolment: Enrolment, course: Course) -> bool:
    """Firestore: the version switch and the completed -> active re-open are one transaction on
    the fresh enrolment (the Postgres ``FOR UPDATE`` on the publish path)."""
    new_v = course.current_version_id
    assert new_v is not None
    keys = await required_keys(session, new_v)
    pm = await progress_map(session, enrolment.id)
    reopen = any((lp := pm.get(k)) is None or lp.status != "completed" for k in keys)

    def step(rows: dict[uuid.UUID, Enrolment]) -> uuid.UUID | None:
        e = rows.get(enrolment.id)
        if e is None or e.course_version_id == new_v:
            return None  # gone, or migrated by a concurrent publisher / learner
        old = e.course_version_id
        e.course_version_id = new_v
        if e.status == "completed" and reopen:
            e.status, e.completed_at = "active", None
        return old

    old, rows = await fss.locked(session, Enrolment, [enrolment.id], step)
    if enrolment.id in rows:
        fss.copy_into(enrolment, rows[enrolment.id])
    if old is None:
        return False
    await emit_event(
        session,
        "learning.version_migrated",
        {
            "enrolment_id": str(enrolment.id),
            "user_id": str(enrolment.user_id),
            "course_id": str(course.id),
            "from_version_id": str(old),
            "to_version_id": str(new_v),
        },
        aggregate_type="enrolment",
        aggregate_id=enrolment.id,
        organization_id=enrolment.organization_id,
    )
    await recompute(session, enrolment)
    return True


async def on_course_published(session: AsyncSession, course: Course, version: CourseVersion) -> None:
    """catalog publish hook: ``minor`` versions auto-migrate active enrolments (FR-CAT-002).
    Runs in the publisher's transaction; platform publishers have ``app.is_platform``, org
    publishers see their org's enrolments (RLS U)."""
    if version.change_type != "minor" or course.current_version_id != version.id:
        return
    # BE-06: migrate each enrolment like LRN-07 does, so progress is recomputed and a course
    # completed on the old version re-opens when the minor version adds required lessons.
    if fss.fs():
        fs_rows = await fss.find(
            session,
            Enrolment,
            filters=(("course_id", "==", course.id),),
            where=lambda e: e.status in ("active", "completed") and e.course_version_id != version.id,
        )
        for enr in sorted(fs_rows, key=lambda e: e.id):
            await migrate_version(session, enr, course)
        return
    enrolments = (
        await session.execute(
            select(Enrolment)
            .where(
                Enrolment.course_id == course.id,
                Enrolment.status.in_(("active", "completed")),
                Enrolment.course_version_id != version.id,
            )
            .order_by(Enrolment.id)
            .with_for_update()
        )
    ).scalars()
    for enr in list(enrolments):
        await migrate_version(session, enr, course)


def iso(dt: datetime | None) -> str | None:
    return to_rfc3339(dt) if dt else None


def window_state(now: datetime, due_at: datetime | None, late_until: datetime | None) -> str:
    if due_at is None or now <= due_at:
        return "on_time"
    if late_until is not None and now <= late_until:
        return "late"
    return "closed"


def ist_day(dt: datetime) -> str:
    """Asia/Kolkata calendar date shown on the public verification page."""
    return ist_date(dt).isoformat()


# --------------------------------------------------------------------------- Firestore helpers


async def _enrolments_on_versions(
    session: AsyncSession, user_id: uuid.UUID, version_ids: list[uuid.UUID]
) -> list[Enrolment]:
    """Firestore: the user's active/completed enrolments pinned to one of ``version_ids``."""
    wanted = set(version_ids)
    return await fss.find(
        session,
        Enrolment,
        filters=(("user_id", "==", user_id),),
        where=lambda e: e.status in ("active", "completed") and e.course_version_id in wanted,
    )


async def _certificates_for_entitlement(
    session: AsyncSession, entitlement_id: uuid.UUID
) -> list[Certificate]:
    """Firestore: live certificates of enrolments granted by ``entitlement_id``, by id."""
    enrolments = await fss.find(session, Enrolment, filters=(("entitlement_id", "==", entitlement_id),))
    ids = [e.id for e in enrolments]
    out: list[Certificate] = []
    for i in range(0, len(ids), 30):
        out += await fss.find(
            session,
            Certificate,
            filters=(("enrolment_id", "in", ids[i : i + 30]),),
            where=lambda c: c.revoked_at is None,
        )
    return sorted(out, key=lambda c: c.id)
