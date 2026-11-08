"""Learning: enrolments, lesson delivery and progress, assignments, grading, certificates
(api-spec §12, LRN-01..24).

Learner routes (``/me/*``) are ownership-scoped (``S``) and run on the principal's RLS
context (family U: own rows). Read-only learner pages are tagged ``l3_readonly`` (brief §5);
everything that changes state is ``default`` (full scope only). Content delivery always calls
``app.core.access.require_access`` server-side; enrolment never grants access by itself.

Staff routes: ``enrolment.read`` / ``enrolment.manage`` / ``progress.read`` @O/@B,
``assignment.manage`` / ``assignment.grade`` @B/@C, ``grade.override_released`` @B/@C (+S10),
``certificate.issue_manual`` @P, ``certificate.revoke`` @P (+S10 staff / P5 privileged).

Not implemented: LRN-25..27 bookmarks (no table in database-schema §7).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select

from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, ScopeRef, require_active_principal, require_permission
from app.core.company import COMPANY_ORG_ID
from app.core.db import DbSession, PrincipalDbSession, system_context
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router, public_router
from app.core.time import to_rfc3339, utcnow
from app.modules.ai.service import require_app_enabled
from app.modules.catalog import service as catalog
from app.modules.catalog.models import Course, CourseVersion, Lesson, LessonAsset, Resource
from app.modules.learning import service as svc
from app.modules.learning import structured
from app.modules.learning.models import (
    Assignment,
    AssignmentSubmission,
    Certificate,
    Enrolment,
    LessonProgress,
)

me = authenticated_router(prefix="/me", tags=["learning"])
me_ro = authenticated_router(prefix="/me", tags=["learning"], route_tag="l3_readonly")
staff = authenticated_router(tags=["learning"])
pub = public_router(tags=["learning"])

PUBLIC_CODE_RE = re.compile(r"^[A-Z0-9]{10,16}$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _limit(limit: int) -> int:
    """BE-34: out-of-range ``limit`` is a 400 ``validation_failed`` like every other module's
    ``Query(ge=1, le=100)`` (was silently clamped)."""
    if not 1 <= limit <= MAX_LIMIT:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "limit", "code": "out_of_range", "message": f"Use 1 to {MAX_LIMIT}"}],
        )
    return limit


def _f(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def enrolment_out(
    e: Enrolment, course: Course | None = None, version: CourseVersion | None = None
) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "course_id": str(e.course_id),
        "course_slug": course.slug if course else None,
        "course_title": version.title if version else (course.title if course else None),
        "course_version_id": str(e.course_version_id),
        "organization_id": str(e.organization_id) if e.organization_id else None,
        "batch_id": str(e.batch_id) if e.batch_id else None,
        "source": e.source,
        "status": e.status,
        "progress_pct": float(e.progress_pct),
        "enrolled_at": to_rfc3339(e.enrolled_at),
        "completed_at": svc.iso(e.completed_at),
        "expires_at": svc.iso(e.expires_at),
        "last_activity_at": svc.iso(e.last_activity_at),
    }


async def _my_enrolments(session: Any, user_id: uuid.UUID) -> list[tuple[Enrolment, Course, CourseVersion]]:
    rows = (
        await session.execute(
            select(Enrolment, Course, CourseVersion)
            .join(Course, Course.id == Enrolment.course_id)
            .join(CourseVersion, CourseVersion.id == Enrolment.course_version_id)
            .where(Enrolment.user_id == user_id)
            .order_by(Enrolment.last_activity_at.desc().nulls_last(), Enrolment.id.desc())
        )
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


# =========================================================================== learner


@me_ro.get("/dashboard", operation_id="lrn_01_dashboard")
async def dashboard(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    enrols = await _my_enrolments(session, principal.user_id)
    cont = [enrolment_out(e, c, v) for e, c, v in enrols if e.status == "active"][:5]
    assignments = await _my_assignments(session, principal)
    now = utcnow()
    due = [
        a for a in assignments if a["my_status"] in ("not_submitted", "returned") and a["window"] != "closed"
    ]
    due.sort(key=lambda a: a["due_at"] or "9999")
    certs = (
        await session.execute(
            select(Certificate)
            .where(Certificate.user_id == principal.user_id)
            .order_by(Certificate.issued_at.desc())
        )
    ).scalars()
    expiring = [
        enrolment_out(e, c, v)
        for e, c, v in enrols
        if e.expires_at is not None and e.status == "active" and (e.expires_at - now).days <= 14
    ]
    return {
        "continue_learning": cont,
        "assigned_work": due[:10],
        "tests": [],
        "expiring": expiring,
        "certificates": [svc.certificate_out(c) for c in certs][:5],
        "banners": [],
    }


def _offset_page(rows: list[Any], cursor: str | None, limit: int) -> tuple[list[Any], dict[str, Any]]:
    """BE-34: signed offset cursor over a small, stably ordered per-learner list."""
    limit = _limit(limit)
    start = 0
    if cursor:
        raw = decode_cursor(cursor).get("o")
        if not isinstance(raw, int) or raw < 0:
            raise ProblemError("invalid_cursor")
        start = raw
    chunk = rows[start : start + limit]
    more = start + limit < len(rows)
    return chunk, page_meta({"o": start + limit} if more else None, limit)


@me_ro.get("/enrolments", operation_id="lrn_02_my_enrolments")
async def my_enrolments(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    cursor: str | None = None,
    limit: int = MAX_LIMIT,
) -> dict[str, Any]:
    rows, page = _offset_page(await _my_enrolments(session, principal.user_id), cursor, limit)
    return {"data": [enrolment_out(e, c, v) for e, c, v in rows], "page": page}


class EnrolIn(Strict):
    course_id: uuid.UUID


@me.post("/enrolments", operation_id="lrn_03_enrol")
async def enrol(
    request: Request,
    body: EnrolIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def op() -> IdemResult:
        course = (
            await session.execute(
                select(Course).where(Course.id == body.course_id, Course.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if course is None:
            raise ProblemError("not_found")
        enr, created = await svc.self_enrol(session, principal, course)
        version = await session.get(CourseVersion, enr.course_version_id)
        return IdemResult(enrolment_out(enr, course, version), 201 if created else 200, enr.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


async def _own_enrolment(
    session: Any, principal: Principal, course_id: uuid.UUID
) -> tuple[Enrolment, Course]:
    enr = await svc.get_enrolment(session, principal.user_id, course_id)
    course = await session.get(Course, course_id)
    if enr is None or course is None:
        raise ProblemError("not_found")
    return enr, course


@me_ro.get("/courses/{course_id}", operation_id="lrn_04_course_overview")
async def course_overview(
    course_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    enr, course = await _own_enrolment(session, principal, course_id)
    version = await session.get(CourseVersion, enr.course_version_id)
    assert version is not None
    modules, by_module, _assets = await catalog.version_tree(session, version.id)
    pm = await svc.progress_map(session, enr.id)
    next_lesson = None
    out_modules = []
    for m in modules:
        lessons = []
        for le in by_module.get(m.id, []):
            lp = pm.get(le.lesson_key)
            st = lp.status if lp else "not_started"
            if next_lesson is None and st != "completed" and le.is_required:
                next_lesson = {"lesson_id": str(le.id), "title": le.title}
            lessons.append(
                {
                    **catalog.lesson_out(le, full=False),
                    "status": st,
                    "progress_pct": float(lp.progress_pct) if lp else 0.0,
                    "video_position_s": lp.video_position_s if lp else None,
                }
            )
        out_modules.append(
            {"id": str(m.id), "module_key": str(m.module_key), "title": m.title, "lessons": lessons}
        )
    cert = (
        await session.execute(select(Certificate).where(Certificate.enrolment_id == enr.id))
    ).scalar_one_or_none()
    if cert is not None:
        cert_status: dict[str, Any] = {
            **svc.certificate_out(cert),
            "status": "revoked" if cert.revoked_at else "issued",
        }
    else:
        el = await svc.certificate_eligibility(session, enr)
        cert_status = {
            "status": "not_eligible" if not el["eligible"] else "pending",
            "reason": el.get("reason"),
        }
    migration = None
    if course.current_version_id and course.current_version_id != enr.course_version_id:
        cur = await session.get(CourseVersion, course.current_version_id)
        if cur is not None:
            migration = {
                "available_version_id": str(cur.id),
                "version_no": cur.version_no,
                "change_type": cur.change_type,
                "changelog": cur.changelog,
            }
    return {
        "enrolment": enrolment_out(enr, course, version),
        "title": version.title,
        "modules": out_modules,
        "next_lesson": next_lesson,
        "certificate": cert_status,
        "version_migration": migration,
    }


@me.get("/courses/{course_id}/lessons/{lesson_id}", operation_id="lrn_05_lesson")
async def lesson_payload(
    course_id: uuid.UUID,
    lesson_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    lesson, version, course = await svc.student_lesson(session, lesson_id)
    if course.id != course_id:
        raise ProblemError("not_found")
    decision = await svc.check_lesson_access(session, principal, lesson, course)
    enr = await svc.enrolment_for_lesson(session, principal, lesson, course, decision)
    progress = None
    if enr is not None:
        lesson = await svc.pinned_lesson(session, enr, lesson)
        lp = await svc.mark_opened(session, enr, lesson)
        progress = {
            "status": lp.status,
            "progress_pct": float(lp.progress_pct),
            "video_position_s": lp.video_position_s,
            "watched_seconds": lp.watched_seconds,
        }
    elif version.status != "published":
        raise ProblemError("not_found")
    assets = list(
        (
            await session.execute(
                select(LessonAsset)
                .where(LessonAsset.lesson_id == lesson.id, LessonAsset.status != "retired")
                .order_by(LessonAsset.position)
            )
        ).scalars()
    )
    resources = (
        await session.execute(select(Resource).where(Resource.lesson_id == lesson.id).order_by(Resource.id))
    ).scalars()
    out = catalog.lesson_out(lesson, assets)
    out["playback"] = (
        {"token_url": "/api/v1/media/playback-tokens"} if lesson.lesson_type == "video" else None
    )
    out["resources"] = [
        {"id": str(r.id), "title": r.title, "resource_type": r.resource_type, "access_level": r.access_level}
        for r in resources
    ]
    out["progress"] = progress
    out["access"] = {"reason": decision.reason}
    return out


class CompletionIn(Strict):
    evidence: dict[str, Any] = Field(default_factory=dict)


@me.post("/lessons/{lesson_key}/completion", operation_id="lrn_06_completion")
async def lesson_completion(
    request: Request,
    lesson_key: uuid.UUID,
    body: CompletionIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def op() -> IdemResult:
        row = (
            await session.execute(
                select(Enrolment, Lesson, Course)
                .join(Lesson, Lesson.course_version_id == Enrolment.course_version_id)
                .join(Course, Course.id == Enrolment.course_id)
                .where(
                    Enrolment.user_id == principal.user_id,
                    Enrolment.status.in_(("active", "completed")),
                    Lesson.lesson_key == lesson_key,
                )
            )
        ).first()
        if row is None:
            raise ProblemError("not_found")
        enr, lesson, course = row
        await svc.check_lesson_access(session, principal, lesson, course)
        lp = await svc.record_article_completion(session, enr, lesson, body.evidence)
        return IdemResult(
            {
                "lesson_key": str(lesson_key),
                "status": lp.status,
                "completed_at": svc.iso(lp.completed_at),
                "enrolment": enrolment_out(enr),
            }
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@me.post("/courses/{course_id}/migrate-version", operation_id="lrn_07_migrate_version")
async def migrate_version(
    request: Request,
    course_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def op() -> IdemResult:
        enr, course = await _own_enrolment(session, principal, course_id)
        migrated = await svc.migrate_version(session, enr, course)
        return IdemResult({"migrated": migrated, "enrolment": enrolment_out(enr, course)})

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


# --------------------------------------------------------------------------- learner: assignments


async def _my_batch_ids(session: Any, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Active batch memberships only (SEC-03)."""
    return await structured.active_batch_ids(session, user_id)


async def _eligible_assignment_filter(session: Any, principal: Principal) -> Any:
    batches = await _my_batch_ids(session, principal.user_id)
    courses = set(
        (
            await session.execute(
                select(Enrolment.course_id).where(
                    Enrolment.user_id == principal.user_id, Enrolment.status.in_(("active", "completed"))
                )
            )
        ).scalars()
    )
    conds: list[Any] = []
    legacy = Assignment.submission_type != "structured"
    if batches:
        conds.append(legacy & Assignment.batch_id.in_(batches))
    if courses:
        conds.append(legacy & Assignment.batch_id.is_(None) & Assignment.course_id.in_(courses))
    # Structured assignments reach learners only through an active, visible allocation.
    conds.append(structured.allocated_to_learner_filter(principal.user_id, batches, utcnow()))
    return or_(*conds)


def _assignment_out(a: Assignment, now: datetime) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "title": a.title,
        "instructions_md": a.instructions_md,
        "submission_type": a.submission_type,
        "max_score": float(a.max_score),
        "rubric": a.rubric,
        "allowed_file_types": list(a.allowed_file_types),
        "course_id": str(a.course_id) if a.course_id else None,
        "batch_id": str(a.batch_id) if a.batch_id else None,
        "available_from": svc.iso(a.available_from),
        "due_at": svc.iso(a.due_at),
        "late_until": svc.iso(a.late_until),
        "late_penalty_pct": float(a.late_penalty_pct),
        "max_attempts": a.max_attempts,
        "status": a.status,
        "grades_released": a.grades_released_at is not None,
        "window": svc.window_state(now, a.due_at, a.late_until),
        "organization_id": str(a.organization_id) if a.organization_id else None,
        "structured": a.submission_type == "structured",
        "ai_help_enabled": a.ai_help_enabled,
        "ai_help_limit": a.ai_help_limit,
    }


def _submission_out(s: AssignmentSubmission, *, show_grade: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(s.id),
        "assignment_id": str(s.assignment_id),
        "user_id": str(s.user_id),
        "attempt_no": s.attempt_no,
        "status": s.status,
        "submitted_at": svc.iso(s.submitted_at),
        "body_text": s.body_text,
        "link_url": s.link_url,
        "file_s3_keys": list(s.file_s3_keys),
        "code_submission_id": str(s.code_submission_id) if s.code_submission_id else None,
        "returned_reason": s.returned_reason,
    }
    if show_grade:
        out.update(
            {
                "score": _f(s.score),
                "raw_score": _f(s.raw_score),
                "late_penalty_pct": _f(s.late_penalty_pct),
                "rubric_scores": s.rubric_scores,
                "feedback_md": s.feedback_md,
                "graded_at": svc.iso(s.graded_at),
            }
        )
    return out


async def _my_assignments(session: Any, principal: Principal) -> list[dict[str, Any]]:
    flt = await _eligible_assignment_filter(session, principal)
    if flt is None:
        return []
    rows = list(
        (
            await session.execute(
                select(Assignment)
                .where(flt, Assignment.status == "active")
                .order_by(Assignment.due_at.nulls_last())
            )
        ).scalars()
    )
    subs: dict[uuid.UUID, AssignmentSubmission] = {}
    if rows:
        for s in (
            await session.execute(
                select(AssignmentSubmission)
                .where(
                    AssignmentSubmission.user_id == principal.user_id,
                    AssignmentSubmission.assignment_id.in_([a.id for a in rows]),
                )
                .order_by(AssignmentSubmission.attempt_no)
            )
        ).scalars():
            subs[s.assignment_id] = s
    now = utcnow()
    out = []
    for a in rows:
        d = _assignment_out(a, now)
        last = subs.get(a.id)
        d["my_status"] = last.status if last else "not_submitted"
        d["my_score"] = _f(last.score) if last and a.grades_released_at else None
        if a.submission_type == "structured":
            d.update(await structured.learner_list_fields(session, principal, a, last, now))
        out.append(d)
    return out


@me_ro.get("/assignments", operation_id="lrn_08_my_assignments")
async def my_assignments(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    return {"data": await _my_assignments(session, principal), "page": page_meta(None, MAX_LIMIT)}


async def _eligible_assignment(session: Any, principal: Principal, assignment_id: uuid.UUID) -> Assignment:
    flt = await _eligible_assignment_filter(session, principal)
    a = None
    if flt is not None:
        a = (
            await session.execute(select(Assignment).where(Assignment.id == assignment_id, flt))
        ).scalar_one_or_none()
    if a is None:
        raise ProblemError("not_found")
    return a


@me_ro.get("/assignments/{assignment_id}", operation_id="lrn_09_my_assignment")
async def my_assignment(
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    a = await _eligible_assignment(session, principal, assignment_id)
    subs = (
        await session.execute(
            select(AssignmentSubmission)
            .where(
                AssignmentSubmission.assignment_id == a.id, AssignmentSubmission.user_id == principal.user_id
            )
            .order_by(AssignmentSubmission.attempt_no)
        )
    ).scalars()
    out = _assignment_out(a, utcnow())
    out["submissions"] = [_submission_out(s, show_grade=a.grades_released_at is not None) for s in subs]
    return out


class SubmissionIn(Strict):
    body_text: str | None = Field(default=None, max_length=50_000)
    link_url: str | None = Field(default=None, pattern=r"^https?://", max_length=2000)
    file_s3_keys: list[str] = Field(default_factory=list, max_length=5)
    code_submission_id: uuid.UUID | None = None


@me.post("/assignments/{assignment_id}/submissions", status_code=201, operation_id="lrn_10_submit")
async def submit_assignment(
    request: Request,
    assignment_id: uuid.UUID,
    body: SubmissionIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def op() -> IdemResult:
        a = await _eligible_assignment(session, principal, assignment_id)
        now = utcnow()
        if a.status != "active" or (a.available_from and now < a.available_from):
            raise ProblemError(
                "invalid_state_transition", detail="This assignment is not open for submissions."
            )
        if a.course_id is not None:
            course = await session.get(Course, a.course_id)
            if course is not None:
                await svc.require_access(session, principal, "course", course.id, is_free=course.is_free)
        window = svc.window_state(now, a.due_at, a.late_until)
        if window == "closed":
            raise ProblemError("invalid_state_transition", detail="The submission window has closed.")
        _validate_payload(a, body, principal.user_id)
        if body.code_submission_id is not None:
            await _require_own_code_submission(session, principal, a, body.code_submission_id)
        prev = list(
            (
                await session.execute(
                    select(AssignmentSubmission)
                    .where(
                        AssignmentSubmission.assignment_id == a.id,
                        AssignmentSubmission.user_id == principal.user_id,
                    )
                    .order_by(AssignmentSubmission.attempt_no)
                    .with_for_update()
                )
            ).scalars()
        )
        if prev and prev[-1].status != "returned" and len(prev) >= a.max_attempts:
            raise ProblemError("attempt_limit_reached")
        sub = AssignmentSubmission(
            id=uuid7(),
            assignment_id=a.id,
            user_id=principal.user_id,
            organization_id=a.organization_id,
            attempt_no=(prev[-1].attempt_no + 1) if prev else 1,
            body_text=body.body_text,
            link_url=body.link_url,
            file_s3_keys=body.file_s3_keys,
            code_submission_id=body.code_submission_id,
            status="late" if window == "late" else "submitted",
            submitted_at=now,
        )
        session.add(sub)
        await session.flush()
        await emit_event(
            session,
            "learning.assignment_submitted",
            {
                "submission_id": str(sub.id),
                "assignment_id": str(a.id),
                "user_id": str(principal.user_id),
                "late": window == "late",
            },
            aggregate_type="assignment",
            aggregate_id=a.id,
            organization_id=a.organization_id,
        )
        # Assignment lessons complete on submission (evidence: the submission id).
        keys = set(
            (await session.execute(select(Lesson.lesson_key).where(Lesson.assignment_id == a.id))).scalars()
        )
        for k in keys:
            await svc.record_completion(
                session, principal.user_id, k, {"kind": "assignment_submitted", "submission_id": str(sub.id)}
            )
        return IdemResult(_submission_out(sub, show_grade=False), 201, sub.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


async def _require_own_code_submission(
    session: Any, principal: Principal, a: Assignment, code_submission_id: uuid.UUID
) -> None:
    """BE-07: the cited code submission must exist, be the learner's own graded ``submit`` and,
    when the assignment's lesson names a coding problem, be for that problem (coding's public
    ``verify_submission_owner``)."""
    from app.modules.coding.service import verify_submission_owner

    problem_id = None
    if a.lesson_id is not None:
        problem_id = (
            await session.execute(select(Lesson.coding_problem_id).where(Lesson.id == a.lesson_id))
        ).scalar_one_or_none()
    if not await verify_submission_owner(session, code_submission_id, principal.user_id, problem_id):
        raise svc.vf("code_submission_id", "not_found", "Submit your code first, then attach that submission")


def _validate_payload(a: Assignment, body: SubmissionIn, user_id: uuid.UUID) -> None:
    t = a.submission_type
    if t == "structured":
        raise ProblemError(
            "invalid_state_transition",
            detail="Answer this assignment in its workspace (/me/assignments/{id}/workspace).",
        )
    if t == "file":
        if not body.file_s3_keys:
            raise svc.vf("file_s3_keys", "required", "Attach at least one file")
        prefix = f"uploads/assignment_submission/{user_id}/"
        allowed = {x.lower().lstrip(".") for x in a.allowed_file_types}
        for i, k in enumerate(body.file_s3_keys):
            if not k.startswith(prefix) or ".." in k:
                raise svc.vf(
                    f"file_s3_keys.{i}", "invalid", "Upload the file with POST /media/uploads/file first"
                )
            ext = k.rsplit(".", 1)[-1].lower() if "." in k.rsplit("/", 1)[-1] else ""
            if allowed and ext not in allowed:
                raise svc.vf(f"file_s3_keys.{i}", "file_type", "This file type is not allowed")
    elif t == "text" and not (body.body_text and body.body_text.strip()):
        raise svc.vf("body_text", "required", "Write your answer")
    elif t == "link" and not body.link_url:
        raise svc.vf("link_url", "required", "Add a link")
    elif t == "code" and body.code_submission_id is None:
        raise svc.vf("code_submission_id", "required", "Submit your code first")


# --------------------------------------------------------------------------- learner: certificates


@me_ro.get("/certificates", operation_id="lrn_11_my_certificates")
async def my_certificates(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    cursor: str | None = None,
    limit: int = MAX_LIMIT,
) -> dict[str, Any]:
    all_rows = (
        await session.execute(
            select(Certificate, CourseVersion.title)
            .join(CourseVersion, CourseVersion.id == Certificate.course_version_id)
            .where(Certificate.user_id == principal.user_id)
            .order_by(Certificate.issued_at.desc(), Certificate.id.desc())
        )
    ).all()
    rows, page = _offset_page(list(all_rows), cursor, limit)
    return {"data": [svc.certificate_out(c, t) for c, t in rows], "page": page}


@me_ro.get("/certificates/{certificate_id}/pdf", operation_id="lrn_12_certificate_pdf")
async def certificate_pdf(
    certificate_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    from app.modules.media.storage import presign_get, storage_settings

    c = await session.get(Certificate, certificate_id)
    if c is None or c.user_id != principal.user_id:
        raise ProblemError("not_found")
    if c.pdf_s3_key is None:
        raise ProblemError("not_found", detail="The certificate PDF is not generated yet.")
    url, exp = presign_get(
        storage_settings().S3_BUCKET_CERTIFICATES, c.pdf_s3_key, filename=f"{c.public_code}.pdf"
    )
    return {"url": url, "expires_at": to_rfc3339(exp)}


@pub.get("/certificates/verify/{public_code}", operation_id="lrn_13_verify_certificate")
async def verify_certificate(public_code: str, session: DbSession) -> dict[str, Any]:
    """Public verification: minimal fields only; no reason for revocation; uniform 404."""
    if not PUBLIC_CODE_RE.match(public_code):
        raise ProblemError("not_found")
    await system_context(session, "learning.certificate_verify")
    row = (
        await session.execute(
            select(
                Certificate.public_code,
                Certificate.name_on_certificate,
                Certificate.identity_verified,
                Certificate.issued_at,
                Certificate.revoked_at,
                CourseVersion.title,
            )
            .join(CourseVersion, CourseVersion.id == Certificate.course_version_id)
            .where(Certificate.public_code == public_code)
        )
    ).first()
    if row is None:
        raise ProblemError("not_found")
    code, name, verified, issued_at, revoked_at, title = row
    if revoked_at is not None:
        return {"public_code": code, "status": "revoked", "revoked_on": svc.ist_day(revoked_at)}
    return {
        "public_code": code,
        "status": "valid",
        "name_on_certificate": name,
        "course_title": title,
        "issued_at": svc.ist_day(issued_at),
        "identity_verified": verified,
        "issuer": "Tech Drona",
    }


# =========================================================================== staff


async def _assignment_scope(session: Any, principal: Principal, a_id: uuid.UUID) -> tuple[ScopeRef, Any]:
    row = await catalog.system_lookup(
        session,
        principal,
        select(Assignment.batch_id, Assignment.course_id, Assignment.organization_id).where(
            Assignment.id == a_id
        ),
    )
    if row is None:
        raise ProblemError("not_found")
    return structured.scope_of(row[0], row[1], row[2]), row


async def _org_of_target(
    session: Any, principal: Principal, batch_id: uuid.UUID | None, course_id: uuid.UUID | None
) -> uuid.UUID | None:
    from app.modules.orgs.models import Batch

    if batch_id is not None:
        row = await catalog.system_lookup(
            session, principal, select(Batch.organization_id).where(Batch.id == batch_id)
        )
        if row is None:
            raise ProblemError("not_found")
        return row[0]
    row = await catalog.system_lookup(
        session, principal, select(Course.organization_id).where(Course.id == course_id)
    )
    if row is None:
        raise ProblemError("not_found")
    return row[0]


class RubricLevel(Strict):
    label: str = Field(min_length=1, max_length=100)
    points: float = Field(ge=0, le=10000)


class RubricCriterion(Strict):
    key: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    label: str = Field(min_length=1, max_length=200)
    max_points: float = Field(gt=0, le=10000)
    description: str | None = Field(default=None, max_length=1000)
    levels: list[RubricLevel] = Field(default_factory=list, max_length=10)


class Rubric(Strict):
    """``assignments.rubric`` (FR-LRN-005 "criteria x levels"; webstaff request 13). The trainer
    grading UI reads ``criteria[].key/label/max_points``; ``rubric_scores`` on LRN-17 is
    ``{criterion key: points}``."""

    criteria: list[RubricCriterion] = Field(min_length=1, max_length=30)


def _check_rubric(rubric: Rubric | None, max_score: Decimal) -> dict[str, Any] | None:
    if rubric is None:
        return None
    seen: set[str] = set()
    for i, c in enumerate(rubric.criteria):
        if c.key in seen:
            raise svc.vf(f"rubric.criteria.{i}.key", "duplicate", "Each criterion needs its own key")
        seen.add(c.key)
        for j, lv in enumerate(c.levels):
            if lv.points > c.max_points:
                raise svc.vf(
                    f"rubric.criteria.{i}.levels.{j}.points", "too_high", "A level cannot exceed max_points"
                )
    if Decimal(str(sum(c.max_points for c in rubric.criteria))) > max_score:
        raise svc.vf("rubric", "exceeds_max_score", "The criteria's points add up to more than max_score")
    return rubric.model_dump(exclude_none=True)


def _rubric_score(rubric: Any, scores: dict[str, float]) -> Decimal | None:
    """Validate LRN-17 ``rubric_scores`` against the assignment's rubric; returns their total.
    Rubrics stored before this schema existed (any other shape) are not checked (None)."""
    try:
        parsed = Rubric.model_validate(rubric)
    except ValueError:
        return None
    crit = {c.key: c for c in parsed.criteria}
    for k in scores:
        if k not in crit:
            raise svc.vf(f"rubric_scores.{k}", "unknown", "Not a criterion of this assignment's rubric")
    for k, c in crit.items():
        if k not in scores:
            raise svc.vf(f"rubric_scores.{k}", "required", f"Score {c.label}")
        if scores[k] > c.max_points:
            raise svc.vf(f"rubric_scores.{k}", "too_high", f"{c.label} is out of {c.max_points:g}")
    return Decimal(str(sum(scores.values()))).quantize(Decimal("0.01"))


class AssignmentIn(Strict):
    batch_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    lesson_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    # Required for file/text/link/code; optional for "structured" (prompts live in the items).
    instructions_md: str | None = Field(default=None, min_length=1, max_length=50_000)
    submission_type: Literal["file", "text", "link", "code", "structured"]
    ai_help_enabled: bool = False
    ai_help_limit: int | None = Field(default=None, ge=0, le=1000)
    max_score: Decimal = Field(gt=0, le=10000)
    rubric: Rubric | None = None
    allowed_file_types: list[str] = Field(
        default_factory=lambda: ["pdf", "zip", "docx", "txt"], max_length=20
    )
    available_from: datetime | None = None
    due_at: datetime | None = None
    late_until: datetime | None = None
    late_penalty_pct: Decimal = Field(default=Decimal(0), ge=0, le=100)
    max_attempts: int = Field(default=1, ge=1, le=20)


class AssignmentPatch(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    instructions_md: str | None = Field(default=None, min_length=1, max_length=50_000)
    rubric: Rubric | None = None
    allowed_file_types: list[str] | None = Field(default=None, max_length=20)
    available_from: datetime | None = None
    due_at: datetime | None = None
    late_until: datetime | None = None
    late_penalty_pct: Decimal | None = Field(default=None, ge=0, le=100)
    max_attempts: int | None = Field(default=None, ge=1, le=20)
    status: Literal["active", "archived"] | None = None
    # structured assignments only
    max_score: Decimal | None = Field(default=None, gt=0, le=10000)
    ai_help_enabled: bool | None = None
    ai_help_limit: int | None = Field(default=None, ge=0, le=1000)


def _check_dates(due: datetime | None, late: datetime | None) -> None:
    if due is not None and late is not None and late < due:
        raise svc.vf("late_until", "before_due", "late_until must be after due_at")


@staff.post("/assignments", status_code=201, operation_id="lrn_14_create_assignment")
async def create_assignment(
    request: Request,
    body: AssignmentIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    is_structured = body.submission_type == "structured"
    if body.batch_id is None and body.course_id is None and not is_structured:
        # Structured assignments may be company-wide (allocated to batches later).
        raise svc.vf("batch_id", "required", "Give a batch_id or a course_id")
    if not is_structured and not body.instructions_md:
        raise svc.vf("instructions_md", "required", "Write the instructions")
    if not is_structured and (body.ai_help_enabled or body.ai_help_limit is not None):
        raise svc.vf("ai_help_enabled", "structured_only", "AI help applies to structured assignments")
    _check_dates(body.due_at, body.late_until)
    rubric = _check_rubric(body.rubric, body.max_score)
    org: uuid.UUID | None = COMPANY_ORG_ID
    if body.batch_id is not None or body.course_id is not None:
        org = await _org_of_target(session, principal, body.batch_id, body.course_id)
    scope = structured.scope_of(body.batch_id, body.course_id, org)
    await catalog.ensure_permission(request, session, principal, "assignment.manage", scope)
    if is_structured:
        await require_app_enabled(session, app_key="assignments")

    async def op() -> IdemResult:
        a = Assignment(
            id=uuid7(),
            organization_id=org,
            course_id=body.course_id,
            batch_id=body.batch_id,
            lesson_id=body.lesson_id,
            title=body.title,
            instructions_md=body.instructions_md or "",
            submission_type=body.submission_type,
            ai_help_enabled=body.ai_help_enabled,
            ai_help_limit=body.ai_help_limit,
            max_score=body.max_score,
            rubric=rubric,
            allowed_file_types=[x.lower().lstrip(".") for x in body.allowed_file_types],
            available_from=body.available_from,
            due_at=body.due_at,
            late_until=body.late_until,
            late_penalty_pct=body.late_penalty_pct,
            max_attempts=body.max_attempts,
            created_by=principal.user_id,
        )
        session.add(a)
        await session.flush()
        return IdemResult(_assignment_out(a, utcnow()), 201, a.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@staff.patch("/assignments/{assignment_id}", operation_id="lrn_15_patch_assignment")
async def patch_assignment(
    request: Request,
    assignment_id: uuid.UUID,
    body: AssignmentPatch,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    scope, _ = await _assignment_scope(session, principal, assignment_id)
    await catalog.ensure_permission(request, session, principal, "assignment.manage", scope)
    a = await session.get(Assignment, assignment_id)
    if a is None:
        raise ProblemError("not_found")
    data = body.model_dump(exclude_unset=True)
    await structured.check_patch(session, a, data)
    _check_dates(data.get("due_at", a.due_at), data.get("late_until", a.late_until))
    if "rubric" in data:
        data["rubric"] = _check_rubric(body.rubric, a.max_score)
    for k, v in data.items():
        if v is None and k in (
            "title",
            "instructions_md",
            "allowed_file_types",
            "late_penalty_pct",
            "max_attempts",
            "status",
            "max_score",
            "ai_help_enabled",
        ):
            continue
        setattr(a, k, v)
    await session.flush()
    return _assignment_out(a, utcnow())


@staff.get(
    "/assignments/{assignment_id}/submissions",
    operation_id="lrn_16_grading_queue",
    openapi_extra={"x-td-idle": "neutral"},
)
async def grading_queue(
    request: Request,
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    status: str | None = None,
) -> dict[str, Any]:
    scope, _ = await _assignment_scope(session, principal, assignment_id)
    await catalog.ensure_permission(request, session, principal, "assignment.grade", scope)
    q = select(AssignmentSubmission).where(AssignmentSubmission.assignment_id == assignment_id)
    if status:
        q = q.where(AssignmentSubmission.status == status)
    rows = (await session.execute(q.order_by(AssignmentSubmission.submitted_at))).scalars()
    return {"data": [_submission_out(s, show_grade=True) for s in rows], "page": page_meta(None, MAX_LIMIT)}


async def _submission_for_staff(
    request: Request, session: Any, principal: Principal, submission_id: uuid.UUID, perm: str
) -> tuple[AssignmentSubmission, Assignment]:
    row = await catalog.system_lookup(
        session,
        principal,
        select(AssignmentSubmission.assignment_id).where(AssignmentSubmission.id == submission_id),
    )
    if row is None:
        raise ProblemError("not_found")
    scope, _ = await _assignment_scope(session, principal, row[0])
    await catalog.ensure_permission(request, session, principal, perm, scope)
    sub = await session.get(AssignmentSubmission, submission_id)
    a = await session.get(Assignment, row[0])
    if sub is None or a is None:
        raise ProblemError("not_found")
    return sub, a


@staff.get(
    "/assignment-submissions/{submission_id}",
    operation_id="lrn_16a_get_submission",
    openapi_extra={"x-td-idle": "neutral", "x-td-route-tag": "l3_readonly"},
)
async def get_submission(
    request: Request,
    submission_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """One assignment submission (Stage 10; trainer grading screen and learner deep link).

    * Owner (``S``): own submission; grade fields only once grades are released (as LRN-09).
    * Staff: ``assignment.grade`` @B/@C on the assignment's scope (as LRN-16); full view.
    * Anyone else: ``404 not_found`` (existence is not disclosed; cross-tenant is 404 too)."""
    row = await catalog.system_lookup(
        session,
        principal,
        select(AssignmentSubmission.assignment_id, AssignmentSubmission.user_id).where(
            AssignmentSubmission.id == submission_id
        ),
    )
    if row is None:
        raise ProblemError("not_found")
    if row[1] == principal.user_id:
        # Owner read runs on the principal's own RLS context (family U: own rows).
        own = await session.get(AssignmentSubmission, submission_id)
        a = await session.get(Assignment, row[0])
        if own is None or a is None:  # pragma: no cover - hidden by RLS / deleted meanwhile
            raise ProblemError("not_found")
        return _submission_out(own, show_grade=a.grades_released_at is not None)
    try:
        sub, _a = await _submission_for_staff(request, session, principal, submission_id, "assignment.grade")
    except ProblemError as e:
        if e.code == "permission_denied":
            raise ProblemError("not_found") from e
        raise
    return _submission_out(sub, show_grade=True)


@staff.get(
    "/assignment-submissions/{submission_id}/files/{file_index}",
    operation_id="lrn_16b_submission_file",
    openapi_extra={"x-td-idle": "neutral", "x-td-route-tag": "l3_readonly"},
)
async def submission_file(
    request: Request,
    submission_id: uuid.UUID,
    file_index: int,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """ADM-47: short-lived (<= 5 min) download URL for one attached file of a submission.
    Same access rule as LRN-16a: the owner, or staff with ``assignment.grade`` on the
    assignment's scope; anyone else 404."""
    from app.modules.media.storage import presign_get, storage_settings

    row = await catalog.system_lookup(
        session,
        principal,
        select(AssignmentSubmission.assignment_id, AssignmentSubmission.user_id).where(
            AssignmentSubmission.id == submission_id
        ),
    )
    if row is None:
        raise ProblemError("not_found")
    if row[1] == principal.user_id:
        sub = await session.get(AssignmentSubmission, submission_id)
        if sub is None:  # pragma: no cover - hidden by RLS
            raise ProblemError("not_found")
    else:
        try:
            sub, _a = await _submission_for_staff(
                request, session, principal, submission_id, "assignment.grade"
            )
        except ProblemError as e:
            if e.code == "permission_denied":
                raise ProblemError("not_found") from e
            raise
    keys = list(sub.file_s3_keys)
    if not 0 <= file_index < len(keys):
        raise ProblemError("not_found")
    key = keys[file_index]
    url, exp = presign_get(storage_settings().S3_BUCKET_UPLOADS, key, filename=key.rsplit("/", 1)[-1])
    return {"url": url, "expires_at": to_rfc3339(exp), "filename": key.rsplit("/", 1)[-1]}


class GradeIn(Strict):
    action: Literal["grade", "return"] = "grade"
    score: Decimal | None = Field(default=None, ge=0)
    rubric_scores: dict[str, Annotated[float, Field(ge=0, le=10000)]] | None = Field(
        default=None, max_length=30
    )
    feedback_md: str | None = Field(default=None, max_length=20_000)
    returned_reason: str | None = Field(default=None, max_length=2000)


@staff.post("/assignment-submissions/{submission_id}/grade", operation_id="lrn_17_grade")
async def grade(
    request: Request,
    submission_id: uuid.UUID,
    body: GradeIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    sub, a = await _submission_for_staff(request, session, principal, submission_id, "assignment.grade")

    async def op() -> IdemResult:
        if sub.user_id == principal.user_id:
            raise ProblemError("conflict_of_interest", detail="You cannot grade your own submission.")
        if a.submission_type == "structured":
            # SEC-11: structured work is graded per item through review/finalize (audited
            # overrides); this legacy endpoint would skip that and could grade a draft.
            raise ProblemError(
                "invalid_state_transition",
                detail="Grade structured assignments from the evaluation screen (finalize).",
            )
        if sub.status == "draft":
            raise ProblemError("invalid_state_transition", detail="The learner has not handed this in yet.")
        if a.grades_released_at is not None and sub.status == "graded":
            raise ProblemError(
                "invalid_state_transition", detail="Grades are released; use grade-override with a reason."
            )
        now = utcnow()
        if body.action == "return":
            if not body.returned_reason:
                raise svc.vf("returned_reason", "required", "Say what to change")
            sub.status = "returned"
            sub.returned_reason = body.returned_reason
        else:
            score = body.score
            if body.rubric_scores is not None:
                total = _rubric_score(a.rubric, body.rubric_scores)
                if total is not None:
                    if score is None:
                        score = total
                    elif abs(score - total) > Decimal("0.01"):
                        raise svc.vf("score", "rubric_mismatch", "The score must equal the rubric total")
            if score is None:
                raise svc.vf("score", "required", "Enter a score")
            if score > a.max_score:
                raise svc.vf("score", "too_high", "Score exceeds the maximum")
            sub.status = "graded"
            sub.raw_score = score
            # BE-08: a submission made after due_at gets the assignment's late penalty.
            late = a.due_at is not None and sub.submitted_at is not None and sub.submitted_at > a.due_at
            pct = Decimal(a.late_penalty_pct or 0) if late else Decimal(0)
            sub.late_penalty_pct = pct if late else None
            sub.score = (score * (Decimal(100) - pct) / Decimal(100)).quantize(Decimal("0.01"))
        sub.rubric_scores = body.rubric_scores
        sub.feedback_md = body.feedback_md
        sub.graded_by = principal.user_id
        sub.graded_at = now
        await session.flush()
        await audit(  # ADM-57
            session,
            principal,
            "assignment.grade",
            "assignment_submission",
            sub.id,
            organization_id=a.organization_id,
            subject_user_id=sub.user_id,
            after={
                "action": body.action,
                "status": sub.status,
                "score": _f(sub.score) if body.action != "return" else None,
                "raw_score": _f(sub.raw_score) if body.action != "return" else None,
                "late_penalty_pct": _f(sub.late_penalty_pct) if body.action != "return" else None,
            },
        )
        await emit_event(
            session,
            "learning.submission_graded",
            {
                "submission_id": str(sub.id),
                "assignment_id": str(a.id),
                "user_id": str(sub.user_id),
                "action": body.action,
            },
            aggregate_type="assignment",
            aggregate_id=a.id,
            organization_id=a.organization_id,
        )
        return IdemResult(_submission_out(sub, show_grade=True))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@staff.post("/assignments/{assignment_id}/release-grades", operation_id="lrn_18_release_grades")
async def release_grades(
    request: Request,
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    scope, _ = await _assignment_scope(session, principal, assignment_id)
    await catalog.ensure_permission(request, session, principal, "assignment.grade", scope)
    a = await session.get(Assignment, assignment_id)
    if a is None:
        raise ProblemError("not_found")
    if a.grades_released_at is None:
        a.grades_released_at = utcnow()
        await session.flush()
        await audit(  # ADM-57
            session,
            principal,
            "assignment.grades_release",
            "assignment",
            a.id,
            organization_id=a.organization_id,
            after={"grades_released_at": a.grades_released_at},
        )
        await emit_event(
            session,
            "learning.grades_released",
            {"assignment_id": str(a.id)},
            aggregate_type="assignment",
            aggregate_id=a.id,
            organization_id=a.organization_id,
        )
    out = _assignment_out(a, utcnow())
    if a.submission_type == "structured":
        # Only finalized (graded) submissions become visible; the rest stay "awaiting results".
        out["unfinalized_count"] = await structured.unfinalized_count(session, a.id)
    return out


class OverrideIn(Strict):
    score: Decimal = Field(ge=0)
    reason: str = Field(min_length=5, max_length=2000)
    feedback_md: str | None = Field(default=None, max_length=20_000)


@staff.post("/assignment-submissions/{submission_id}/grade-override", operation_id="lrn_19_grade_override")
async def grade_override(
    request: Request,
    submission_id: uuid.UUID,
    body: OverrideIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    sub, a = await _submission_for_staff(
        request, session, principal, submission_id, "grade.override_released"
    )
    await _step_up(principal, 600)

    async def op() -> IdemResult:
        if a.grades_released_at is None or sub.status != "graded":
            raise ProblemError("invalid_state_transition", detail="Only released grades are overridden.")
        if body.score > a.max_score:
            raise svc.vf("score", "too_high", "Score exceeds the maximum")
        before = {"score": _f(sub.score)}
        sub.score = body.score
        # An override sets the final score explicitly (no late penalty applied on top).
        sub.raw_score = body.score
        sub.late_penalty_pct = None
        if body.feedback_md is not None:
            sub.feedback_md = body.feedback_md
        sub.graded_by = principal.user_id
        sub.graded_at = utcnow()
        await session.flush()
        await audit(
            session,
            principal,
            "grade.override_released",
            "assignment_submission",
            sub.id,
            organization_id=a.organization_id,
            subject_user_id=sub.user_id,
            reason=body.reason,
            before=before,
            after={"score": _f(sub.score)},
        )
        return IdemResult(_submission_out(sub, show_grade=True))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


async def _step_up(principal: Principal, seconds: int) -> None:
    from app.core.auth import require_step_up

    await require_step_up(seconds)(principal)


class ManualCertIn(Strict):
    enrolment_id: uuid.UUID
    reason: str = Field(min_length=5, max_length=2000)


@staff.post(
    "/certificates",
    status_code=201,
    operation_id="lrn_20_issue_certificate",
    dependencies=[Depends(require_permission("certificate.issue_manual", scope=PLATFORM_SCOPE))],
)
async def issue_certificate_manual(
    request: Request,
    body: ManualCertIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def op() -> IdemResult:
        enr = await session.get(Enrolment, body.enrolment_id)
        if enr is None:
            raise ProblemError("not_found")
        cert = await svc.issue_certificate(session, enr, source="manual")
        await audit(
            session,
            principal,
            "certificate.issue_manual",
            "certificate",
            cert.id,
            organization_id=cert.organization_id,
            subject_user_id=cert.user_id,
            reason=body.reason,
            after={"public_code": cert.public_code, "enrolment_id": enr.id},
        )
        return IdemResult(svc.certificate_out(cert), 201, cert.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


class RevokeIn(Strict):
    reason: str = Field(min_length=5, max_length=2000)


@staff.post(
    "/certificates/{certificate_id}/revoke",
    operation_id="lrn_21_revoke_certificate",
    dependencies=[Depends(require_permission("certificate.revoke", scope=PLATFORM_SCOPE))],
)
async def revoke_certificate(
    request: Request,
    certificate_id: uuid.UUID,
    body: RevokeIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    await _step_up(principal, 300 if principal.tier == "privileged" else 600)

    async def op() -> IdemResult:
        cert = await session.get(Certificate, certificate_id)
        if cert is None:
            raise ProblemError("not_found")
        await svc.revoke_certificate(session, principal, cert, body.reason)
        return IdemResult(svc.certificate_out(cert))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


def _query_scope(request: Request) -> ScopeRef:
    qp = request.query_params
    try:
        if qp.get("batch_id"):
            return ScopeRef("batch", uuid.UUID(qp["batch_id"]))
    except ValueError as e:
        raise ProblemError("not_found") from e
    # Single company: without batch_id the list covers every batch (platform staff only).
    return ScopeRef("platform", None)


def _scope_filter(request: Request) -> Any:
    qp = request.query_params
    if qp.get("batch_id"):
        return Enrolment.batch_id == uuid.UUID(qp["batch_id"])
    return Enrolment.batch_id.is_not(None)


@staff.get(
    "/enrolments",
    operation_id="lrn_22_enrolments",
    dependencies=[Depends(require_permission("enrolment.read", scope=_query_scope))],
    openapi_extra={"x-td-idle": "neutral"},
)
async def list_enrolments(
    request: Request,
    session: PrincipalDbSession,
    course_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    return await _enrolment_page(session, request, course_id, cursor, limit, with_user=False)


async def _enrolment_page(
    session: Any,
    request: Request,
    course_id: uuid.UUID | None,
    cursor: str | None,
    limit: int,
    *,
    with_user: bool,
) -> dict[str, Any]:
    limit = _limit(limit)
    conds = [_scope_filter(request)]
    if course_id:
        conds.append(Enrolment.course_id == course_id)
    if cursor:
        conds.append(Enrolment.id > uuid.UUID(str(decode_cursor(cursor).get("id"))))
    rows = list(
        (
            await session.execute(select(Enrolment).where(*conds).order_by(Enrolment.id).limit(limit + 1))
        ).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    data = []
    for e in rows:
        d = enrolment_out(e)
        d["user_id"] = str(e.user_id)
        data.append(d)
    return {"data": data, "page": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit)}


class BatchEnrolIn(Strict):
    batch_id: uuid.UUID
    course_id: uuid.UUID


@staff.post("/enrolments", operation_id="lrn_23_batch_enrol")
async def batch_enrol(
    request: Request,
    body: BatchEnrolIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    from app.modules.orgs.models import Batch, BatchMember

    await catalog.ensure_permission(
        request, session, principal, "enrolment.manage", ScopeRef("batch", body.batch_id)
    )

    async def op() -> IdemResult:
        batch = await session.get(Batch, body.batch_id)
        course = await session.get(Course, body.course_id)
        if batch is None or course is None or course.deleted_at is not None:
            raise ProblemError("not_found")
        if course.status != "published" or course.current_version_id is None:
            raise ProblemError("invalid_state_transition", detail="Only published courses can be assigned.")
        if course.organization_id is not None and course.organization_id != batch.organization_id:
            raise ProblemError("not_found")
        members = list(
            (
                await session.execute(
                    select(BatchMember.user_id).where(
                        BatchMember.batch_id == batch.id,
                        BatchMember.member_role == "student",
                        BatchMember.status == "active",
                    )
                )
            ).scalars()
        )
        existing = set(
            (
                await session.execute(
                    select(Enrolment.user_id).where(
                        Enrolment.course_id == course.id, Enrolment.user_id.in_(members or [uuid7()])
                    )
                )
            ).scalars()
        )
        created = 0
        for uid in members:
            if uid in existing:
                continue
            await svc.create_enrolment(
                session,
                user_id=uid,
                course=course,
                source="batch_sync",
                organization_id=batch.organization_id,
                batch_id=batch.id,
            )
            created += 1
        await audit(
            session,
            principal,
            "enrolment.batch_assign",
            "batch",
            batch.id,
            organization_id=batch.organization_id,
            after={"course_id": course.id, "created": created, "skipped": len(members) - created},
        )
        return IdemResult(
            {
                "batch_id": str(batch.id),
                "course_id": str(course.id),
                "created": created,
                "already_enrolled": len(members) - created,
            }
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@staff.get(
    "/progress",
    operation_id="lrn_24_progress",
    dependencies=[Depends(require_permission("progress.read", scope=_query_scope))],
    openapi_extra={"x-td-idle": "neutral"},
)
async def progress(
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    course_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    page = await _enrolment_page(session, request, course_id, cursor, limit, with_user=True)
    ids = [uuid.UUID(d["id"]) for d in page["data"]]
    if ids:
        done: dict[str, int] = {}
        for lp in (
            await session.execute(
                select(LessonProgress).where(
                    LessonProgress.enrolment_id.in_(ids), LessonProgress.status == "completed"
                )
            )
        ).scalars():
            done[str(lp.enrolment_id)] = done.get(str(lp.enrolment_id), 0) + 1
        for d in page["data"]:
            d["lessons_completed"] = done.get(d["id"], 0)
    await audit(
        session,
        principal,
        "progress.read",
        "enrolment_scope",
        None,
        organization_id=COMPANY_ORG_ID,
        after={"batch_id": batch_id, "course_id": course_id, "rows": len(page["data"])},
    )
    return page


# --------------------------------------------------------------------------- staff assignment list

_LIST_PERMS = ("assignment.grade", "assignment.manage")


async def _may(request: Request, principal: Principal, perm: str, scope: ScopeRef) -> bool:
    """Non-raising permission probe through the registered checker (cross-tenant 404 -> False)."""
    from app.core import auth as core_auth

    return await core_auth.check_permission(principal, perm, scope, request)


@staff.get(
    "/assignments",
    operation_id="lrn_14a_list_assignments",
    openapi_extra={"x-td-idle": "neutral"},
)
async def list_assignments(
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    scope: Literal["mine"] = "mine",
    batch_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    status: Literal["active", "archived"] | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Staff assignment list (trainer grading console; used by the web app, not in the spec
    table). ``scope=mine``: assignments whose batch/course scope grants the caller
    ``assignment.grade`` or ``assignment.manage``. Newest first, cursor-paginated."""
    from sqlalchemy import func

    from app.modules.orgs.models import Batch

    limit = _limit(limit)
    staff_grants = [g for g in principal.grants if g.role != "student"]
    if not staff_grants:
        raise ProblemError("permission_denied", permission="assignment.grade")
    q = select(Assignment, Batch.name).outerjoin(Batch, Batch.id == Assignment.batch_id)
    if not any(g.scope_type == "platform" for g in staff_grants):
        batches = {g.scope_id for g in staff_grants if g.scope_type == "batch" and g.scope_id}
        courses = {g.scope_id for g in staff_grants if g.scope_type == "course" and g.scope_id}
        # Named evaluator (evaluator_ids) on one of the allocations.
        conds = [structured.evaluator_filter(principal.user_id)]
        if batches:
            conds.append(Assignment.batch_id.in_(batches))
        if courses:
            conds.append(Assignment.course_id.in_(courses))
        if batches:
            conds.append(structured.allocated_to_batches_filter(batches))
        if not conds:
            raise ProblemError("permission_denied", permission="assignment.grade")
        q = q.where(or_(*conds))
    if batch_id is not None:
        q = q.where(Assignment.batch_id == batch_id)
    if course_id is not None:
        q = q.where(Assignment.course_id == course_id)
    if status is not None:
        q = q.where(Assignment.status == status)
    after: uuid.UUID | None = None
    if cursor:
        try:
            after = uuid.UUID(str(decode_cursor(cursor)["id"]))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e

    allowed: dict[tuple[str, uuid.UUID | None], bool] = {}
    picked: list[tuple[Assignment, str | None]] = []
    chunk = (limit + 1) * 2
    for _ in range(20):
        page_q = q if after is None else q.where(Assignment.id < after)
        async with system_context(session, "learning.assignment_list"):
            rows = (await session.execute(page_q.order_by(Assignment.id.desc()).limit(chunk))).all()
        for a, batch_name in rows:
            sref = structured.scope_of(a.batch_id, a.course_id, a.organization_id)
            key = (sref.scope_type, sref.scope_id)
            if key not in allowed:
                ok = False
                for perm in _LIST_PERMS:
                    if await _may(request, principal, perm, sref):
                        ok = True
                        break
                allowed[key] = ok
            visible = allowed[key]
            if not visible and a.submission_type == "structured":
                # Batch staff see org-level structured assignments allocated to their batches.
                async with system_context(session, "learning.assignment_list"):
                    alloc_batches = await structured.allocation_batches(session, a.id)
                for b_id in alloc_batches:
                    if await _may(request, principal, "assignment.grade", ScopeRef("batch", b_id)):
                        visible = True
                        break
                if not visible:
                    async with system_context(session, "learning.assignment_list"):
                        visible = await structured.is_named_evaluator(session, a.id, principal.user_id)
            if visible:
                picked.append((a, batch_name))
                if len(picked) > limit:
                    break
        if len(picked) > limit or len(rows) < chunk:
            break
        after = rows[-1][0].id
    more = len(picked) > limit
    picked = picked[:limit]
    pending: dict[uuid.UUID, int] = {}
    if picked:
        async with system_context(session, "learning.assignment_list"):
            pending = {
                r[0]: int(r[1])
                for r in (
                    await session.execute(
                        select(AssignmentSubmission.assignment_id, func.count())
                        .where(
                            AssignmentSubmission.assignment_id.in_([a.id for a, _ in picked]),
                            AssignmentSubmission.status.in_(("submitted", "late")),
                        )
                        .group_by(AssignmentSubmission.assignment_id)
                    )
                ).all()
            }
    now = utcnow()
    counts: dict[uuid.UUID, tuple[int, int]] = {}
    if picked:
        async with system_context(session, "learning.assignment_list"):
            counts = await structured.structure_counts(session, [a.id for a, _ in picked])
    data = []
    for a, bname in picked:
        out = _assignment_out(a, now)
        if a.submission_type == "structured":
            out["section_count"], out["item_count"] = counts.get(a.id, (0, 0))
        out.update(
            {
                "assignment_id": str(a.id),
                "batch_name": bname,
                "max_points": float(a.max_score),
                "pending_count": pending.get(a.id, 0),
            }
        )
        data.append(out)
    return {"data": data, "page": page_meta({"id": str(picked[-1][0].id)} if more else None, limit)}


# Learning reacts to catalog publishes (minor versions auto-migrate enrolments).
catalog.register_publish_hook(svc.on_course_published)

router = APIRouter()
for _r in (me, me_ro, staff, pub):
    router.include_router(_r)

# Structured assignments (sections/items, allocations, workspace, tutor, evaluation, regrades).
from app.modules.learning import structured_api as _structured_api  # noqa: E402

router.include_router(_structured_api.router)


# DB-01: register this module's erasure provider with admin privacy (import-time registration).
from app.modules.learning import privacy as _privacy  # noqa: E402

_privacy.register()
