"""Batch delivery: plan, computed schedule, live classes and attendance (orgs_0005).

Moved from the website back office (``AdminCourses.jsx`` course plans, ``AdminLearning.jsx``
"Classes & attendance"). Permissions follow the other ``/batches/{id}`` routes (batch scope, so a
trainer holding a grant on batch A can never read or mark batch B):

* read plan / schedule / classes / attendance — ``org.member.read`` @batch (Trainer B, Admin P)
* edit the plan (and the batch's course links + start date) — ``batch.update`` @batch (Admin)
* create / edit / delete classes, mark attendance — ``batch.class.manage`` @batch (Trainer B, Admin P)
* ``/me/classes``, ``/me/attendance`` — the signed-in learner's own batches (active student
  membership in a non-archived batch); nothing else is visible.

Dates are IST calendar dates (``app.core.time.ist_date``). Schedule maths: ``course_plan``.

Storage: every read/write goes through ``app.modules.orgs.route_store`` (the Postgres SQL as
before, or the Firestore repository with ``TD_STORE_ORGS=firestore``, which never uses the
Postgres session).
"""

from __future__ import annotations

import uuid
from datetime import date, time
from typing import Any, Literal

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.audit import audit
from app.core.auth import require_active_principal, require_permission, scope_from_path
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import ist_date, to_rfc3339, utcnow
from app.modules.orgs import route_store as rs
from app.modules.orgs.course_plan import (
    SLUG_RE,
    PlanBody,
    compute_schedule,
    load_plan,
    schedule_out,
    summarize,
)
from app.modules.orgs.models import Batch, BatchPlan, ClassSession

r = authenticated_router(tags=["batches"])

BatchScope = scope_from_path("batch_id", "batch")
_READ = "org.member.read"
_MANAGE = "batch.class.manage"
_HTTPS = r"^https://\S+$"


def _perm(key: str) -> Any:
    return Depends(require_permission(key, scope=BatchScope))


def _vf(field: str, code: str, msg: str, status: int = 422) -> ProblemError:
    return ProblemError("validation_failed", status, errors=[{"field": field, "code": code, "message": msg}])


def _today() -> date:
    return ist_date(utcnow())


async def _batch(session: Any, batch_id: uuid.UUID) -> Batch:
    b = await rs.get_batch(session, batch_id)
    if b is None:
        raise ProblemError("not_found")
    return b


def _writable(b: Batch) -> None:
    if b.status == "archived":
        raise ProblemError("invalid_state_transition", current_state="archived", allowed=[])


def _batch_brief(b: Batch) -> dict[str, Any]:
    return {
        "id": str(b.id),
        "name": b.name,
        "code": b.code,
        "status": b.status,
        "starts_on": b.starts_on.isoformat() if b.starts_on else None,
        "ends_on": b.ends_on.isoformat() if b.ends_on else None,
        "course_id": str(b.course_id) if b.course_id else None,
        "website_course_slug": b.website_course_slug,
    }


async def _plan_row(session: Any, batch_id: uuid.UUID) -> BatchPlan | None:
    return await rs.plan_row(session, batch_id)


# --------------------------------------------------------------------------- schemas


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchPlanPut(Strict):
    plan: PlanBody
    starts_on: date | None = None
    course_id: uuid.UUID | None = None
    website_course_slug: str | None = Field(default=None, max_length=80)
    min_attendance_percent: int | None = Field(default=None, ge=1, le=100)
    # Set the batch's ``ends_on`` to the computed last class (when there is a start date).
    sync_end_date: bool = True

    @field_validator("website_course_slug")
    @classmethod
    def _slug(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        v = v.strip().lower()
        if not SLUG_RE.match(v):
            raise ValueError("a website course slug is lower-case letters, digits and hyphens")
        return v


class BatchPlanPreview(Strict):
    plan: PlanBody
    starts_on: date | None = None


class ClassSessionIn(Strict):
    session_date: date
    starts_at: time | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=720)
    topic: str = Field(default="", max_length=200)
    meet_url: str | None = Field(default=None, max_length=500, pattern=_HTTPS)
    recording_url: str | None = Field(default=None, max_length=500, pattern=_HTTPS)
    notes: str | None = Field(default=None, max_length=4000)
    cancelled: bool = False


class ClassSessionPatch(Strict):
    session_date: date | None = None
    starts_at: time | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=720)
    topic: str | None = Field(default=None, max_length=200)
    meet_url: str | None = Field(default=None, max_length=500, pattern=_HTTPS)
    recording_url: str | None = Field(default=None, max_length=500, pattern=_HTTPS)
    notes: str | None = Field(default=None, max_length=4000)
    cancelled: bool | None = None


class ClassGenerateIn(Strict):
    """Create one class per scheduled date of the plan (existing dates are kept)."""

    from_date: date | None = None


class AttendanceMark(Strict):
    user_id: uuid.UUID
    status: Literal["P", "L", "A"] | None  # None clears the mark


class AttendanceMarksIn(Strict):
    marks: list[AttendanceMark] = Field(min_length=1, max_length=500)


def _empty_to_none(d: dict[str, Any]) -> dict[str, Any]:
    for k in ("meet_url", "recording_url", "notes"):
        if k in d and d[k] == "":
            d[k] = None
    return d


def _session_out(s: ClassSession, counts: dict[str, int] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(s.id),
        "batch_id": str(s.batch_id),
        "session_date": s.session_date.isoformat(),
        "starts_at": s.starts_at.strftime("%H:%M") if s.starts_at else None,
        "duration_minutes": s.duration_minutes,
        "topic": s.topic,
        "meet_url": s.meet_url,
        "recording_url": s.recording_url,
        "notes": s.notes,
        "cancelled": s.cancelled,
    }
    if counts is not None:
        out["attendance"] = {k: counts.get(k, 0) for k in ("P", "L", "A")} | {
            "marked": sum(counts.get(k, 0) for k in ("P", "L", "A"))
        }
    return out


# --------------------------------------------------------------------------- plan + schedule


async def _plan_payload(session: Any, b: Batch) -> dict[str, Any]:
    row = await _plan_row(session, b.id)
    plan = load_plan(row.plan if row else None)
    return {
        "batch": _batch_brief(b),
        "has_plan": row is not None,
        "plan": plan.stored(),
        "min_attendance_percent": row.min_attendance_percent if row else None,
        "source_ref": row.source_ref if row else None,
        "updated_at": to_rfc3339(row.updated_at) if row and row.updated_at else None,
        "schedule": schedule_out(plan, b.starts_on, _today()),
    }


@r.get("/batches/{batch_id}/plan", openapi_extra={"x-td-idle": "neutral"})
async def get_plan(
    batch_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = _perm(_READ)
) -> dict[str, Any]:
    return await _plan_payload(session, await _batch(session, batch_id))


@r.get("/batches/{batch_id}/schedule", openapi_extra={"x-td-idle": "neutral"})
async def get_schedule(
    batch_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = _perm(_READ)
) -> dict[str, Any]:
    b = await _batch(session, batch_id)
    row = await _plan_row(session, b.id)
    return schedule_out(load_plan(row.plan if row else None), b.starts_on, _today())


@r.post("/batches/{batch_id}/plan/preview", openapi_extra={"x-td-idle": "neutral"})
async def preview_plan(
    batch_id: uuid.UUID,
    body: BatchPlanPreview,
    session: PrincipalDbSession,
    principal: Principal = _perm(_READ),
) -> dict[str, Any]:
    """Schedule of an unsaved plan (the editor's live preview). Writes nothing."""
    await _batch(session, batch_id)
    return schedule_out(body.plan, body.starts_on, _today())


@r.put("/batches/{batch_id}/plan")
async def put_plan(
    batch_id: uuid.UUID,
    body: BatchPlanPut,
    session: PrincipalDbSession,
    principal: Principal = _perm("batch.update"),
) -> dict[str, Any]:
    b = await _batch(session, batch_id)
    _writable(b)
    sent = body.model_fields_set
    if "course_id" in sent and body.course_id is not None and body.course_id != b.course_id:
        from app.modules.catalog import api as catalog_api

        found = (await catalog_api.get_courses(session, [body.course_id])).get(body.course_id)
        if found is None or found.deleted_at is not None:
            raise _vf("course_id", "unknown_course", "This LMS course does not exist")
    changed: list[str] = []
    for field in ("starts_on", "course_id", "website_course_slug"):
        if field in sent and getattr(b, field) != getattr(body, field):
            setattr(b, field, getattr(body, field))
            changed.append(field)
    sched = compute_schedule(body.plan, b.starts_on)
    if body.sync_end_date and sched.end_date is not None and b.ends_on != sched.end_date:
        b.ends_on = sched.end_date
        changed.append("ends_on")
    if b.starts_on and b.ends_on and b.ends_on < b.starts_on:
        raise _vf("starts_on", "after_end", "The start date is after the batch's end date")
    row = await _plan_row(session, b.id)
    new = row is None
    if row is None:
        row = BatchPlan(batch_id=b.id, organization_id=b.organization_id, plan={})
    row.plan = body.plan.stored()
    if "min_attendance_percent" in sent:
        row.min_attendance_percent = body.min_attendance_percent
    row.updated_by = principal.user_id
    row = await rs.save_plan(session, b, row, new=new, batch_changed=bool(changed))
    await audit(
        session,
        principal,
        "batch.plan.updated",
        "batch",
        b.id,
        organization_id=b.organization_id,
        after={
            "weeks": len(body.plan.weeks),
            "batch_fields": sorted(changed),
            "min_attendance_percent": row.min_attendance_percent,
        },
    )
    return await _plan_payload(session, b)


# --------------------------------------------------------------------------- classes


async def _session_in_batch(session: Any, batch_id: uuid.UUID, session_id: uuid.UUID) -> ClassSession:
    s = await rs.get_class(session, session_id)
    if s is None or s.batch_id != batch_id:  # never reveal a class of another batch
        raise ProblemError("not_found")
    return s


async def _counts(session: Any, session_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    return await rs.counts(session, session_ids)


async def _students(session: Any, batch_id: uuid.UUID) -> list[tuple[uuid.UUID, str | None]]:
    return await rs.students_named(session, batch_id)


def _dup_date() -> ProblemError:
    return _vf("session_date", "duplicate", "This batch already has a class on that date", 409)


@r.get("/batches/{batch_id}/sessions", openapi_extra={"x-td-idle": "neutral"})
async def list_sessions(
    batch_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = _perm(_READ),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    await _batch(session, batch_id)
    rows = await rs.classes(session, batch_id, date_from=date_from, date_to=date_to)
    counts = await _counts(session, [s.id for s in rows])
    roster = len(await _students(session, batch_id))
    return {
        "today": _today().isoformat(),
        "students": roster,
        "data": [_session_out(s, counts.get(s.id, {})) for s in rows],
    }


@r.post("/batches/{batch_id}/sessions", status_code=201)
async def create_session(
    batch_id: uuid.UUID,
    body: ClassSessionIn,
    session: PrincipalDbSession,
    principal: Principal = _perm(_MANAGE),
) -> dict[str, Any]:
    b = await _batch(session, batch_id)
    _writable(b)
    s = ClassSession(
        id=uuid7(),
        batch_id=b.id,
        organization_id=b.organization_id,
        created_by=principal.user_id,
        **_empty_to_none(body.model_dump()),
    )
    try:
        await rs.insert_classes(session, [s])
    except rs.Duplicate as e:  # uq_class_sessions_batch_date
        raise _dup_date() from e
    await audit(
        session,
        principal,
        "batch.class.created",
        "batch",
        b.id,
        organization_id=b.organization_id,
        after={"session_id": s.id, "date": s.session_date.isoformat()},
    )
    return _session_out(s, {})


@r.post("/batches/{batch_id}/sessions/generate")
async def generate_sessions(
    batch_id: uuid.UUID,
    body: ClassGenerateIn,
    session: PrincipalDbSession,
    principal: Principal = _perm(_MANAGE),
) -> dict[str, Any]:
    """One class per scheduled date of the plan, titled with the week's title. Needs a start
    date and a plan; dates that already have a class are left alone (idempotent)."""
    b = await _batch(session, batch_id)
    _writable(b)
    row = await _plan_row(session, b.id)
    plan = load_plan(row.plan if row else None)
    sched = compute_schedule(plan, b.starts_on)
    if not b.starts_on or not sched.weeks:
        raise ProblemError(
            "invalid_state_transition",
            detail="Set a start date, hours and working days in the plan first.",
            current_state="no_schedule",
            allowed=[],
        )
    existing = await rs.class_dates(session, b.id)
    new_rows: list[ClassSession] = []
    start = time.fromisoformat(plan.class_time) if plan.class_time else None
    minutes = round(plan.daily_hours * 60) or None
    created = 0
    for w in sched.weeks:
        title = plan.weeks[w.n - 1].title if w.n - 1 < len(plan.weeks) else ""
        for d in w.days:
            if d in existing or (body.from_date and d < body.from_date):
                continue
            new_rows.append(
                ClassSession(
                    id=uuid7(),
                    batch_id=b.id,
                    organization_id=b.organization_id,
                    session_date=d,
                    starts_at=start,
                    duration_minutes=minutes if minutes and minutes <= 720 else None,
                    # A week already titled "Week 3 ..." is not prefixed again ("Week 3: Week 3").
                    topic=(
                        title
                        if title.lower().startswith(f"week {w.n}")
                        else (f"Week {w.n}: {title}" if title else f"Week {w.n}")
                    )[:200],
                    meet_url=plan.meet_url,
                    created_by=principal.user_id,
                )
            )
            created += 1
    try:
        await rs.insert_classes(session, new_rows)
    except rs.Duplicate as e:  # a concurrent create of one of the dates
        raise _dup_date() from e
    if created:
        await audit(
            session,
            principal,
            "batch.class.generated",
            "batch",
            b.id,
            organization_id=b.organization_id,
            after={"created": created},
        )
    return {"created": created, "skipped_existing": len(existing)}


@r.patch("/batches/{batch_id}/sessions/{session_id}")
async def patch_session(
    batch_id: uuid.UUID,
    session_id: uuid.UUID,
    body: ClassSessionPatch,
    session: PrincipalDbSession,
    principal: Principal = _perm(_MANAGE),
) -> dict[str, Any]:
    b = await _batch(session, batch_id)
    _writable(b)
    s = await _session_in_batch(session, batch_id, session_id)
    changes = _empty_to_none(body.model_dump(exclude_unset=True))
    if changes.get("session_date", s.session_date) is None or (
        "topic" in changes and changes["topic"] is None
    ):
        raise _vf("session_date", "required", "A class needs a date and a topic (may be empty text)")
    for k, v in changes.items():
        setattr(s, k, v)
    try:
        await rs.save_class(session, s)
    except rs.Duplicate as e:
        raise _dup_date() from e
    await audit(
        session,
        principal,
        "batch.class.updated",
        "batch",
        b.id,
        organization_id=b.organization_id,
        after={"session_id": s.id, "fields": sorted(changes)},
    )
    return _session_out(s, (await _counts(session, [s.id])).get(s.id, {}))


@r.delete("/batches/{batch_id}/sessions/{session_id}")
async def delete_session(
    batch_id: uuid.UUID,
    session_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = _perm(_MANAGE),
) -> dict[str, Any]:
    """Delete a class that has no attendance yet (mark it cancelled otherwise)."""
    b = await _batch(session, batch_id)
    _writable(b)
    s = await _session_in_batch(session, batch_id, session_id)
    if (await _counts(session, [s.id])).get(s.id):
        raise ProblemError(
            "invalid_state_transition",
            detail="Attendance was marked for this class. Mark it cancelled or clear the marks first.",
            current_state="has_attendance",
            allowed=["cancel"],
        )
    await rs.delete_class(session, s)
    await audit(
        session,
        principal,
        "batch.class.deleted",
        "batch",
        b.id,
        organization_id=b.organization_id,
        after={"session_id": session_id},
    )
    return {"deleted": True}


# --------------------------------------------------------------------------- attendance


@r.get("/batches/{batch_id}/sessions/{session_id}/attendance", openapi_extra={"x-td-idle": "neutral"})
async def session_attendance(
    batch_id: uuid.UUID,
    session_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = _perm(_READ),
) -> dict[str, Any]:
    await _batch(session, batch_id)
    s = await _session_in_batch(session, batch_id, session_id)
    marks = {m.user_id: m for m in await rs.marks_of_class(session, s.id)}
    students = await _students(session, batch_id)
    seen = {u for u, _ in students}
    extra = [u for u in marks if u not in seen]  # marked earlier, no longer in the batch
    names: dict[uuid.UUID, str | None] = {}
    if extra:
        names = await rs.names_of(session, extra)
    rows = [(u, n, True) for u, n in students] + [(u, names.get(u), False) for u in extra]
    return {
        "session": _session_out(s, {}),
        "data": [
            {
                "user_id": str(u),
                "full_name": n,
                "in_batch": active,
                "status": marks[u].status if u in marks else None,
                "marked_at": to_rfc3339(marks[u].marked_at) if u in marks else None,
            }
            for u, n, active in rows
        ],
    }


@r.put("/batches/{batch_id}/sessions/{session_id}/attendance")
async def mark_attendance(
    batch_id: uuid.UUID,
    session_id: uuid.UUID,
    body: AttendanceMarksIn,
    session: PrincipalDbSession,
    principal: Principal = _perm(_MANAGE),
) -> dict[str, Any]:
    """Bulk mark (upsert) P / L / A for the batch's active students; ``status: null`` clears."""
    b = await _batch(session, batch_id)
    _writable(b)
    s = await _session_in_batch(session, batch_id, session_id)
    if s.cancelled:
        raise ProblemError(
            "invalid_state_transition",
            detail="This class is cancelled.",
            current_state="cancelled",
            allowed=[],
        )
    if s.session_date > _today():
        raise _vf("session_id", "future_class", "Attendance can be marked on or after the class date")
    allowed = {u for u, _ in await _students(session, batch_id)}
    allowed |= {m.user_id for m in await rs.marks_of_class(session, s.id)}
    marks = {m.user_id: m.status for m in body.marks}  # the last mark for a user wins
    unknown = [u for u in marks if u not in allowed]
    if unknown:
        raise _vf("marks", "not_in_batch", f"{len(unknown)} learner(s) are not students of this batch")
    clear = [u for u, st in marks.items() if st is None]
    upsert = [(u, st) for u, st in marks.items() if st is not None]
    await rs.write_marks(session, s, b, clear=clear, upsert=upsert, marked_by=principal.user_id)
    counts = (await _counts(session, [s.id])).get(s.id, {})
    await audit(
        session,
        principal,
        "batch.attendance.marked",
        "batch",
        b.id,
        organization_id=b.organization_id,
        after={"session_id": s.id, "set": len(upsert), "cleared": len(clear)},
    )
    return {"session": _session_out(s, counts)}


async def _batch_summaries(
    session: Any, batch_id: uuid.UUID, user_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, list[str]]:
    return await rs.batch_marks(session, batch_id, user_ids)


@r.get("/batches/{batch_id}/attendance", openapi_extra={"x-td-idle": "neutral"})
async def batch_attendance(
    batch_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = _perm(_READ)
) -> dict[str, Any]:
    """Attendance per learner (active students) and for the batch as a whole."""
    await _batch(session, batch_id)
    row = await _plan_row(session, batch_id)
    minimum = row.min_attendance_percent if row else None
    students = await _students(session, batch_id)
    by_user = await _batch_summaries(session, batch_id)
    held = await rs.classes_marked(session, batch_id)
    data = []
    for u, n in students:
        sm = summarize(by_user.get(u, []))
        pct = sm.percent
        data.append(
            {
                "user_id": str(u),
                "full_name": n,
                **sm.out(),
                "below_minimum": bool(minimum and pct is not None and pct < minimum),
            }
        )
    total = summarize([st for u, _ in students for st in by_user.get(u, [])])
    return {
        "min_attendance_percent": minimum,
        "classes_marked": int(held or 0),
        "batch": total.out(),
        "data": data,
    }


@r.get("/batches/{batch_id}/attendance/{user_id}", openapi_extra={"x-td-idle": "neutral"})
async def learner_attendance(
    batch_id: uuid.UUID, user_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = _perm(_READ)
) -> dict[str, Any]:
    await _batch(session, batch_id)
    return await _learner_detail(session, batch_id, user_id)


async def _learner_detail(session: Any, batch_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    rows = await rs.classes_with_mark(session, batch_id, user_id)
    sm = summarize([st for s, st in rows if st and not s.cancelled])
    row = await _plan_row(session, batch_id)
    return {
        "user_id": str(user_id),
        "batch_id": str(batch_id),
        "min_attendance_percent": row.min_attendance_percent if row else None,
        "summary": sm.out(),
        "sessions": [
            {
                "session_id": str(s.id),
                "session_date": s.session_date.isoformat(),
                "topic": s.topic,
                "cancelled": s.cancelled,
                "status": st,
            }
            for s, st in rows
        ],
    }


# --------------------------------------------------------------------------- learner (self)


async def _my_batches(session: Any, user_id: uuid.UUID) -> list[Batch]:
    return await rs.my_batches(session, user_id)


@r.get("/me/classes", openapi_extra={"x-td-idle": "neutral"})
async def my_classes(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    upcoming_limit: int = Query(default=10, ge=1, le=50),
    recent_limit: int = Query(default=20, ge=0, le=100),
) -> dict[str, Any]:
    """The learner's batches: next classes (join link), past classes (recordings, own mark),
    week of the plan and own attendance."""
    today = _today()
    out = []
    for b in await _my_batches(session, principal.user_id):
        row = await _plan_row(session, b.id)
        plan = load_plan(row.plan if row else None)
        sched = schedule_out(plan, b.starts_on, today)
        upcoming = await rs.classes(session, b.id, date_from=today, limit=upcoming_limit)
        recent = await rs.classes_with_mark(
            session, b.id, principal.user_id, before=today, newest_first=True, limit=recent_limit
        )
        mine = await _batch_summaries(session, b.id, [principal.user_id])
        sm = summarize(mine.get(principal.user_id, []))

        def _learner(s: ClassSession, default_url: str | None = plan.meet_url) -> dict[str, Any]:
            o = _session_out(s)
            o.pop("notes", None)  # trainer notes stay with staff
            o["meet_url"] = None if s.cancelled else (s.meet_url or default_url)
            return o

        out.append(
            {
                "batch": _batch_brief(b),
                "class_time": plan.class_time,
                "meet_url": plan.meet_url,
                "current_week": sched["current_week"],
                "weeks_count": sched["weeks_count"],
                "end_date": sched["end_date"],
                "current_week_title": (
                    sched["weeks"][sched["current_week"] - 1]["title"] if sched["current_week"] else None
                ),
                "min_attendance_percent": row.min_attendance_percent if row else None,
                "attendance": sm.out(),
                "upcoming": [_learner(s) for s in upcoming],
                "recent": [{**_learner(s), "meet_url": None, "my_status": st} for s, st in recent],
            }
        )
    return {"today": today.isoformat(), "batches": out}


@r.get("/me/attendance", openapi_extra={"x-td-idle": "neutral"})
async def my_attendance(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    out = []
    for b in await _my_batches(session, principal.user_id):
        d = await _learner_detail(session, b.id, principal.user_id)
        out.append(
            {"batch": _batch_brief(b), **{k: d[k] for k in ("min_attendance_percent", "summary", "sessions")}}
        )
    return {"batches": out}
