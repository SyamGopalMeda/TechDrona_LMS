"""Student management: Excel / CSV import, bulk enrolment and the student record (2026-11-14).

* ``GET  /admin/students/import/options`` -- the published courses and open batches an import
  (or Add user) may name, and whether email really reaches people.
* ``POST /admin/students/import?dry_run=true`` -- validates every row (required fields, email /
  mobile format, duplicates inside the file, an existing account (linked, never duplicated),
  unknown course / batch) and answers per row; nothing is written.
* ``POST /admin/students/import`` (Idempotency-Key, <= 500 rows) -- creates the accounts
  (``staff_created``, adult confirmed, username ``td######`` + temporary password,
  ``must_change_password``), stores the student record, adds them to the batch and enrols them in
  the course. Idempotent per email: an account that already exists is linked and enrolled, never
  created twice. A row that fails does not stop the others; every row reports its own result.
* The same endpoint with ``user_ids`` instead of ``rows`` enrols EXISTING accounts (Users list /
  batch page "Enrol in course/batch").
* ``POST /admin/students/send-login`` -- email a NEW temporary password to accounts (only when
  email is integrated; otherwise 409 ``email_not_connected``).

Temporary passwords leave the server only in the response that created them. They are never
logged, audited or stored: the Idempotency-Key replay record keeps ``temporary_password: null``
(``reveal_once``), so a replay says the passwords were already shown.

Permissions: ``user.invite`` (route) + ``enrolment.manage`` at platform scope, and
``batch.member.manage`` when a batch is named. The import is audited with counts only
(``admin.students.imported``); each new account also gets the usual ``admin.user.created``.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

import structlog
from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, require_permission
from app.core.db import PrincipalDbSession, as_system
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.modules.admin.fs_rows import emit_any, idem_session
from app.modules.identity import clock
from app.modules.identity import public as ipub
from app.modules.identity.public import User, UserProfile

log = structlog.get_logger("app.admin.students")

r = authenticated_router(tags=["admin"], route_tag="default", idle="extends")
NEUTRAL = {"x-td-idle": "neutral"}

MAX_ROWS = 500
LOOKUP_CONCURRENCY = 16
STUDENT_TYPES = ("course", "internship")
ENROL_PERMISSION = "enrolment.manage"
BATCH_PERMISSION = "batch.member.manage"
_JOB = "admin.students"
_TYPE_WORDS = {
    "course": "course",
    "course student": "course",
    "student": "course",
    "internship": "internship",
    "internship student": "internship",
    "intern": "internship",
}
_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d")


# --------------------------------------------------------------------------- inputs


class ImportRowIn(BaseModel):
    """One spreadsheet row, as text (the browser parses the .xlsx / .csv). Every field is checked
    per row, so a bad value is reported on its row instead of rejecting the whole file."""

    model_config = ConfigDict(extra="forbid")
    row: int | None = Field(default=None, ge=1, le=1_000_000)  # spreadsheet row number
    full_name: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=320)
    mobile: str | None = Field(default=None, max_length=40)
    student_type: str | None = Field(default=None, max_length=40)
    course: str | None = Field(default=None, max_length=300)
    batch: str | None = Field(default=None, max_length=300)
    college: str | None = Field(default=None, max_length=300)
    branch: str | None = Field(default=None, max_length=200)
    year: str | None = Field(default=None, max_length=40)
    start_date: str | None = Field(default=None, max_length=40)
    end_date: str | None = Field(default=None, max_length=40)


class StudentImportIn(BaseModel):
    """``rows`` (import) or ``user_ids`` (enrol existing accounts), not both.

    ``course`` / ``batch`` (id, slug / code, or title / name) apply to rows that leave theirs
    empty, and are the target in ``user_ids`` mode."""

    model_config = ConfigDict(extra="forbid")
    rows: list[ImportRowIn] = Field(default_factory=list, max_length=MAX_ROWS)
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_ROWS)
    course: str | None = Field(default=None, max_length=300)
    batch: str | None = Field(default=None, max_length=300)
    student_type: Literal["course", "internship"] | None = None
    must_change_password: bool = True
    confirm_adult: bool = False
    send_email: bool = False
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _one_mode(self) -> StudentImportIn:
        if bool(self.rows) == bool(self.user_ids):
            raise ValueError("send either rows or user_ids")
        return self


class SendLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_ROWS)
    must_change_password: bool = True


def _vf(field_name: str, code: str, message: str) -> ProblemError:
    return ProblemError(
        "validation_failed", 422, errors=[{"field": field_name, "code": code, "message": message}]
    )


# --------------------------------------------------------------------------- helpers


def _clean(v: str | None) -> str:
    return re.sub(r"\s+", " ", v or "").strip()


def parse_date(raw: str | None) -> tuple[date | None, bool]:
    """``(date, ok)``; empty -> ``(None, True)``. ISO, ``dd-mm-yyyy``, ``dd/mm/yyyy``, ``dd.mm.yyyy``."""
    s = _clean(raw)
    if not s:
        return None, True
    s = s.split("T", 1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date(), True
        except ValueError:
            continue
    return None, False


def student_type_of(raw: str | None) -> str | None:
    """``course`` / ``internship`` from the words people type ("Intern", "Course student")."""
    return _TYPE_WORDS.get(_clean(raw).lower())


async def reveal_once(
    request: Request,
    session: Any,
    *,
    user_id: uuid.UUID,
    operation: Callable[[], Awaitable[IdemResult]],
    reveal: list[Callable[[Any], None]],
) -> JSONResponse:
    """``core.idempotency.idempotent`` whose STORED body never holds a temporary password.

    ``operation`` returns the body with ``temporary_password: null`` (that is what the replay record
    keeps) and appends to ``reveal`` the callbacks that put the passwords into this one response."""
    resp = await idempotent(
        request, idem_session(session), user_id=user_id, operation=operation, required=True
    )
    if (
        not reveal
        or not (200 <= resp.status_code < 300)
        or resp.headers.get("Idempotency-Replayed") == "true"
    ):
        return resp
    body = json.loads(bytes(resp.body))
    for fn in reveal:
        fn(body)
    if isinstance(body, dict) and "credentials_withheld" in body:
        body["credentials_withheld"] = False
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in {"content-length", "content-type"}}
    return JSONResponse(body, status_code=resp.status_code, headers=headers)


async def free_username(session: Any) -> str:
    from app.modules.admissions.onboarding import USERNAME_ATTEMPTS, new_username

    for _ in range(USERNAME_ATTEMPTS):
        u = new_username()
        if not await ipub.username_taken(session, u):
            return u
    raise ProblemError("conflict", detail="Couldn't pick a free username. Please try again.")


async def require_enrol_permissions(session: Any, principal: Principal, *, batch: bool) -> None:
    from app.modules.rbac import service as rs

    for perm, needed in ((ENROL_PERMISSION, True), (BATCH_PERMISSION, batch)):
        if needed and not await rs.check_permission(session, principal, perm, PLATFORM_SCOPE):
            raise ProblemError("permission_denied", permission=perm)


# --------------------------------------------------------------------------- catalog (courses / batches)


@dataclass
class Catalog:
    courses: list[Any]
    batches: list[Any]

    @classmethod
    async def load(cls, session: Any) -> Catalog:
        from app.modules.admin.courses_overview import _courses
        from app.modules.orgs import public as orgs_public

        courses = [c for c in await _courses(session) if c.deleted_at is None]
        batches = await orgs_public.list_batches(session, order="name")
        return cls(courses, batches)

    def course(self, raw: str | None) -> tuple[Any | None, str | None]:
        """``(course, None)``, ``(None, error)`` or ``(None, None)`` for an empty value."""
        key = _clean(raw)
        if not key:
            return None, None
        low = key.lower()
        hit = [c for c in self.courses if str(c.id) == low or str(c.slug).lower() == low]
        if not hit:
            hit = [c for c in self.courses if _clean(c.title).lower() == low]
        if not hit:
            return None, f'Unknown course "{key}". Use the course slug or its exact title.'
        if len(hit) > 1:
            return None, f'More than one course is called "{key}". Use the course slug instead.'
        c = hit[0]
        if c.status != "published" or c.current_version_id is None:
            return None, f'The course "{c.title}" isn\'t published yet. Publish it first.'
        return c, None

    def batch(self, raw: str | None) -> tuple[Any | None, str | None]:
        key = _clean(raw)
        if not key:
            return None, None
        low = key.lower()
        hit = [b for b in self.batches if str(b.id) == low or str(b.code).lower() == low]
        if not hit:
            hit = [b for b in self.batches if _clean(b.name).lower() == low]
        if not hit:
            return None, f'Unknown batch "{key}". Use the batch name or code shown in Batches.'
        live = [b for b in hit if b.status != "archived"]
        if not live:
            return None, f'The batch "{hit[0].name}" is archived. Choose a current batch.'
        if len(live) > 1:
            return None, f'More than one batch is called "{key}". Use the batch code instead.'
        return live[0], None

    def course_by_id(self, cid: Any) -> Any | None:
        return next((c for c in self.courses if c.id == cid), None)


def course_out(c: Any | None) -> dict[str, Any] | None:
    return None if c is None else {"id": str(c.id), "slug": c.slug, "title": c.title}


def batch_out(b: Any | None) -> dict[str, Any] | None:
    return None if b is None else {"id": str(b.id), "name": b.name, "code": b.code}


def batch_course(cat: Catalog, batch: Any | None) -> Any | None:
    """A batch's own course (``batches.course_id``) when it is published -- used when the row
    names a batch but no course, as admissions does."""
    if batch is None or getattr(batch, "course_id", None) is None:
        return None
    c = cat.course_by_id(batch.course_id)
    if c is None or c.status != "published" or c.current_version_id is None:
        return None
    return c


# --------------------------------------------------------------------------- student record


def _record_fields(
    *,
    student_type: str | None,
    college: str | None = None,
    branch: str | None = None,
    year: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    vals = {
        "student_type": student_type,
        "college": college or None,
        "branch": branch or None,
        "year": year or None,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    }
    return {k: v for k, v in vals.items() if v is not None}


async def save_student_record(
    user_id: uuid.UUID, fields: dict[str, Any], *, source: str, by: uuid.UUID
) -> None:
    """Merge the non-empty ``fields`` into ``student_records/{user_id}`` (Firestore stack only:
    the legacy Postgres stack has no table for it and keeps the account as is)."""
    if not fields or not uses_firestore("admin"):
        return
    from app.core.firestore.store import ScopedStore, ScopedTransaction
    from app.modules.admin.store_specs import STUDENT_RECORDS

    uid = str(user_id)

    async def fn(tx: ScopedTransaction) -> None:
        cur = await tx.get(STUDENT_RECORDS, uid)
        data = (
            dict(cur.data) if cur is not None else {"user_id": uid, "source": source, "created_by": str(by)}
        )
        data.pop("updated_at", None)
        data.pop("schema_version", None)
        data.update(fields)
        data["updated_by"] = str(by)
        await tx.put(STUDENT_RECORDS, uid, data)

    await ScopedStore.system(_JOB).run_transaction(fn)


async def student_record(user_id: uuid.UUID) -> dict[str, Any] | None:
    if not uses_firestore("admin"):
        return None
    from app.core.firestore.store import ScopedStore
    from app.modules.admin.store_specs import STUDENT_RECORDS

    d = await ScopedStore.system(_JOB).get(STUDENT_RECORDS, str(user_id))
    if d is None:
        return None
    keys = ("student_type", "college", "branch", "year", "start_date", "end_date", "source")
    return {k: d.get(k) for k in keys}


async def erase_student_record(_session: Any, user_id: uuid.UUID) -> dict[str, Any]:
    """Privacy erasure provider: the student record (college, dates) is personal data."""
    if not uses_firestore("admin"):
        return {"student_records": 0}
    from app.core.firestore.store import ScopedStore
    from app.modules.admin.store_specs import STUDENT_RECORDS

    store = ScopedStore.system(_JOB)
    if await store.get(STUDENT_RECORDS, str(user_id)) is None:
        return {"student_records": 0}
    await store.delete(STUDENT_RECORDS, str(user_id))
    return {"student_records": 1}


def _register_erasure() -> None:
    from app.modules.admin.privacy import register_erasure_provider

    register_erasure_provider("student_records", erase_student_record)


_register_erasure()


# --------------------------------------------------------------------------- account + enrolment


@dataclass
class NewAccount:
    user: Any
    username: str
    temporary_password: str | None


async def create_account(
    session: Any,
    principal: Principal,
    *,
    email: str,
    phone: str | None,
    full_name: str,
    password: str | None,
    must_change_password: bool,
    college: str | None = None,
    branch: str | None = None,
    reason: str | None,
    source: str,
) -> NewAccount:
    """A ``staff_created`` adult account with a ``td######`` username. ``password=None`` -> a
    temporary password is generated and returned (never recorded)."""
    from app.core.firestore.errors import UniqueViolationError
    from app.modules.admin.accounts import _journal_outbox
    from app.modules.admissions.onboarding import new_temp_password
    from app.modules.identity import service as ids

    now = clock.now()
    user: Any = None
    for attempt in range(3):
        uid = uuid7()
        candidate = User(
            id=uid,
            email=email,
            email_verified_at=now,
            phone_e164=phone,
            username=await free_username(session),
            status="active",
            is_minor=False,
            # the admin confirms the person is 18+ (as Add user / a roster import)
            age_verified_at=now,
            age_verification_method="roster",
            account_origin="staff_created",
        )
        profile = UserProfile(
            user_id=uid,
            full_name=full_name[:200],
            college_name_text=(college or None),
            branch=(branch or None),
        )
        try:
            await ipub.create_user(session, candidate, profile)
        except UniqueViolationError:
            # lost a race on the username (or the email / mobile was just taken)
            if await ids.find_user(session, "email", email) is not None:
                raise ProblemError(
                    "conflict", detail="An account with this email was just created. Run the import again."
                ) from None
            if attempt == 2:
                raise ProblemError(
                    "conflict", detail="Couldn't create the account. Please try again."
                ) from None
            continue
        user = candidate
        break
    if ipub._fs():
        user.status = "active"
    temp = None
    if password is None:
        temp = new_temp_password()
        must_change_password = True
    await ids.set_password(session, user.id, password or temp, must_change_password=must_change_password)
    user.must_change_password = must_change_password
    await audit(
        session,
        principal,
        "admin.user.created",
        "user",
        user.id,
        subject_user_id=user.id,
        reason=reason,
        after={
            "status": "active",
            "account_origin": "staff_created",
            "source": source,
            "has_mobile": phone is not None,
            "temporary_password": temp is not None,  # set, never recorded
            "must_change_password": must_change_password,
        },
    )
    ev = await emit_any(
        session,
        "identity.user_registered",
        {"user_id": str(user.id), "is_minor": False},
        aggregate_type="user",
        aggregate_id=user.id,
    )
    _journal_outbox(session, ev)
    return NewAccount(user, str(user.username), temp)


@dataclass
class EnrolResult:
    added_to_batch: bool = False
    enrolled: bool = False
    already_in_batch: bool = False
    already_enrolled: bool = False


async def enrol(
    session: Any,
    principal: Principal,
    user_id: uuid.UUID,
    *,
    course: Any | None,
    batch: Any | None,
    reason: str,
) -> EnrolResult:
    """Batch membership + course access (entitlement + enrolment), like admissions ``enrol``.
    Re-running it changes nothing (idempotent per user, batch and course)."""
    from app.modules.entitlements import service as ent
    from app.modules.learning import fs_store as fss
    from app.modules.learning import service as learning
    from app.modules.orgs import public as orgs_public
    from app.modules.orgs.public import BatchMember
    from app.modules.orgs.service import ensure_org_membership

    out = EnrolResult()
    now = clock.now()
    async with as_system(session, "admin.students.enrol"):
        if batch is not None:
            await ensure_org_membership(
                session, batch.organization_id, user_id, member_type="student", added_by=principal.user_id
            )
            live = await orgs_public.batch_members(
                session, batch_ids=[batch.id], user_ids=[user_id], member_role="student"
            )
            if live:
                out.already_in_batch = True
            else:
                await orgs_public.add_batch_member(
                    session,
                    BatchMember(
                        id=uuid7(),
                        batch_id=batch.id,
                        organization_id=batch.organization_id,
                        user_id=user_id,
                        member_role="student",
                        added_by=principal.user_id,
                    ),
                )
                out.added_to_batch = True
        if course is not None:
            await learning.lock_enrolment(session, user_id, course.id)
            enr = await learning.get_enrolment(session, user_id, course.id)
            if enr is not None and enr.status in ("active", "completed"):
                out.already_enrolled = True
                return out
            e_row, _ = await ent.grant(
                session,
                ent.Actor.user(principal),
                user_id=user_id,
                source_type="admin_grant",
                course_id=course.id,
                granted_by=principal.user_id,
                starts_at=now,
                ends_at=None,
                reason=reason[:300],
            )
            if enr is None:
                await learning.create_enrolment(
                    session,
                    user_id=user_id,
                    course=course,
                    source="entitlement",
                    entitlement_id=e_row.id,
                    organization_id=batch.organization_id if batch is not None else None,
                    batch_id=batch.id if batch is not None else None,
                )
            else:
                enr.status, enr.source, enr.entitlement_id, enr.expires_at = (
                    "active",
                    "entitlement",
                    e_row.id,
                    None,
                )
                await fss.flush(session)
            out.enrolled = True
    return out


# --------------------------------------------------------------------------- login email


def login_email(
    *,
    name: str,
    username: str | None,
    email: str,
    temporary_password: str,
    must_change_password: bool,
    url: str,
) -> tuple[str, str, str]:
    from html import escape

    subject = "Your Tech Drona LMS login"
    lines = [f"Hello {name},", "", "Here are your Tech Drona LMS sign-in details:", f"Sign in: {url}"]
    if username:
        lines.append(f"Username: {username}")
    lines += [f"Email: {email}", f"Temporary password: {temporary_password}", ""]
    if must_change_password:
        lines.append("You'll be asked to choose your own password when you first sign in.")
    lines.append("Keep these details private.")
    plain = "\n".join(lines) + "\n\nTech Drona\ninfo@techdrona.com"
    rows = [("Sign in", url, False), ("Username", username or "", True), ("Email", email, False)]
    rows.append(("Temporary password", temporary_password, True))
    cells = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;color:#555">{escape(k)}</td>'
        f'<td style="padding:4px 0;{"font-family:monospace;font-size:15px;" if mono else ""}">'
        f"<strong>{escape(v)}</strong></td></tr>"
        for k, v, mono in rows
        if v
    )
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;line-height:1.5">'
        f"<p>Hello {escape(name)},</p><p>Here are your Tech Drona LMS sign-in details:</p>"
        f'<table style="border-collapse:collapse">{cells}</table>'
        + (
            "<p>You'll be asked to choose your own password when you first sign in.</p>"
            if must_change_password
            else ""
        )
        + "<p>Keep these details private.</p><p>Tech Drona<br>info@techdrona.com</p></div>"
    )
    return subject, plain, html


async def send_login_email(
    *, name: str, username: str | None, email: str, temporary_password: str, must_change_password: bool
) -> str:
    """``sent`` / ``not_connected`` / ``failed``."""
    from app.modules.admissions.onboarding import login_url
    from app.modules.notifications.adapters import email_integrated
    from app.modules.notifications.service import send_email

    if not email_integrated():
        return "not_connected"
    subject, plain, html = login_email(
        name=name,
        username=username,
        email=email,
        temporary_password=temporary_password,
        must_change_password=must_change_password,
        url=login_url(),
    )
    ok = await send_email(
        email,
        subject,
        plain,
        template_key="admin.students.login_details",
        category="transactional",
        html=html,
    )
    return "sent" if ok else "failed"


# --------------------------------------------------------------------------- import planning


@dataclass
class RowPlan:
    index: int
    row: int
    full_name: str = ""
    email: str | None = None
    raw_email: str = ""
    phone: str | None = None
    student_type: str | None = None
    course: Any | None = None
    batch: Any | None = None
    college: str = ""
    branch: str = ""
    year: str = ""
    start_date: date | None = None
    end_date: date | None = None
    user: Any | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "error" if self.errors else ("existing" if self.user is not None else "new")


async def plan_rows(session: Any, body: StudentImportIn, cat: Catalog) -> list[RowPlan]:
    from app.modules.identity import service as ids
    from app.modules.identity.contacts import normalize_email, normalize_phone

    default_course, course_err = cat.course(body.course)
    default_batch, batch_err = cat.batch(body.batch)
    if course_err:
        raise _vf("course", "unknown_course", course_err)
    if batch_err:
        raise _vf("batch", "unknown_batch", batch_err)
    plans: list[RowPlan] = []
    seen_email: dict[str, int] = {}
    seen_phone: dict[str, int] = {}
    for i, raw in enumerate(body.rows):
        p = RowPlan(index=i, row=raw.row or i + 2)  # row 1 is the header
        p.full_name = _clean(raw.full_name)
        if len(p.full_name) < 2:
            p.errors.append("Full name is required (2+ characters).")
        elif len(p.full_name) > 120:
            p.errors.append("Full name is too long (120 characters at most).")
        p.raw_email = _clean(raw.email)
        if not p.raw_email:
            p.errors.append("Email is required.")
        else:
            p.email = normalize_email(p.raw_email)
            if p.email is None:
                p.errors.append(f'"{p.raw_email}" isn\'t a valid email address.')
            elif p.email in seen_email:
                p.errors.append(f"Same email as row {seen_email[p.email]}.")
            else:
                seen_email[p.email] = p.row
        mobile = _clean(raw.mobile)
        if mobile:
            p.phone = normalize_phone(mobile)
            if p.phone is None:
                p.errors.append(f'"{mobile}" isn\'t a valid mobile number (10 digits, or +country code).')
            elif p.phone in seen_phone:
                p.errors.append(f"Same mobile number as row {seen_phone[p.phone]}.")
            else:
                seen_phone[p.phone] = p.row
        st_raw = _clean(raw.student_type)
        p.student_type = student_type_of(st_raw) if st_raw else (body.student_type or "course")
        if p.student_type is None:
            p.errors.append(f'Student type "{st_raw}" isn\'t known: use course or internship.')
        if _clean(raw.course):
            p.course, err = cat.course(raw.course)
            if err:
                p.errors.append(err)
        else:
            p.course = default_course
        if _clean(raw.batch):
            p.batch, err = cat.batch(raw.batch)
            if err:
                p.errors.append(err)
        else:
            p.batch = default_batch
        if p.course is None and p.batch is not None:
            p.course = batch_course(cat, p.batch)
        p.college, p.branch, p.year = (
            _clean(raw.college)[:200],
            _clean(raw.branch)[:120],
            _clean(raw.year)[:20],
        )
        for attr, label in (("start_date", "Start date"), ("end_date", "End date")):
            d, ok = parse_date(getattr(raw, attr))
            if not ok:
                p.errors.append(f"{label} isn't a date (use YYYY-MM-DD or DD-MM-YYYY).")
            setattr(p, attr, d)
        if p.start_date and p.end_date and p.end_date < p.start_date:
            p.errors.append("End date is before the start date.")
        if p.course is None and p.batch is None:
            p.warnings.append("No course or batch: the account is created without an enrolment.")
        plans.append(p)

    # existing accounts (linked, never duplicated) and mobile numbers held by someone else. The
    # lookups run concurrently (a 500-row dry run must answer well inside the 60 s request limit).
    gate = asyncio.Semaphore(LOOKUP_CONCURRENCY)

    async def lookup(kind: str, value: str) -> Any:
        async with gate:
            return await ids.find_user(session, kind, value)

    todo = [p for p in plans if p.email is not None]
    users = await asyncio.gather(*(lookup("email", str(p.email)) for p in todo))
    for p, u in zip(todo, users, strict=True):
        p.user = u
        if u is None:
            continue
        if u.status in ("deactivated", "deleted"):
            p.errors.append("An account with this email exists but is deactivated. Reactivate it first.")
        else:
            p.warnings.append(
                "An account with this email already exists: it will be linked, not created again."
            )
    phones = [p for p in todo if p.user is None and p.phone]
    holders = await asyncio.gather(*(lookup("phone", str(p.phone)) for p in phones))
    for p, holder in zip(phones, holders, strict=True):
        if holder is not None:
            p.warnings.append("This mobile number belongs to another account: it won't be saved.")
            p.phone = None
    return plans


async def plan_users(session: Any, body: StudentImportIn, cat: Catalog) -> list[RowPlan]:
    course, course_err = cat.course(body.course)
    batch, batch_err = cat.batch(body.batch)
    if course_err:
        raise _vf("course", "unknown_course", course_err)
    if batch_err:
        raise _vf("batch", "unknown_batch", batch_err)
    if course is None and batch is None:
        raise _vf("course", "target_required", "Choose a course or a batch to enrol them in.")
    if course is None:
        course = batch_course(cat, batch)
    ids = list(dict.fromkeys(body.user_ids))
    users = await ipub.get_users(session, ids)
    profiles = await ipub.get_profiles(session, ids)
    plans: list[RowPlan] = []
    for i, uid in enumerate(ids):
        p = RowPlan(index=i, row=i + 1, course=course, batch=batch, student_type=body.student_type)
        u = users.get(uid)
        if u is None or u.deleted_at is not None:
            p.errors.append("Account not found.")
        else:
            p.user, p.email, p.raw_email = u, u.email, u.email or ""
            prof = profiles.get(uid)
            p.full_name = (prof.full_name if prof else "") or (u.email or "")
            if u.status in ("deactivated", "deleted"):
                p.errors.append("This account is deactivated. Reactivate it first.")
        plans.append(p)
    return plans


def _row_out(p: RowPlan, user_id_key: str | None = None) -> dict[str, Any]:
    u = p.user
    return {
        "row": p.row,
        "full_name": p.full_name,
        "email": p.email or p.raw_email or None,
        "student_type": p.student_type,
        "status": p.status,
        "errors": list(p.errors),
        "warnings": list(p.warnings),
        "user_id": str(u.id) if u is not None else user_id_key,
        "username": getattr(u, "username", None) if u is not None else None,
        "temporary_password": None,
        "course": course_out(p.course),
        "batch": batch_out(p.batch),
        "enrolled": False,
        "added_to_batch": False,
        "email_status": None,
    }


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    def n(st: str) -> int:
        return sum(1 for x in rows if x["status"] == st)

    return {
        "total": len(rows),
        "new": n("new"),
        "created": n("created"),
        "existing": n("existing"),
        "errors": n("error"),
        "enrolled": sum(1 for x in rows if x["enrolled"]),
        "added_to_batch": sum(1 for x in rows if x["added_to_batch"]),
        "emailed": sum(1 for x in rows if x["email_status"] == "sent"),
    }


# --------------------------------------------------------------------------- routes


@r.get("/admin/students/import/options", openapi_extra=NEUTRAL)
async def import_options(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.invite")),
) -> dict[str, Any]:
    """Courses (published) and batches (not archived) an import may name, + email status."""
    from app.modules.notifications.adapters import email_integrated

    cat = await Catalog.load(session)
    return {
        "courses": [
            {**(course_out(c) or {}), "status": c.status}
            for c in sorted(cat.courses, key=lambda c: str(c.title).lower())
            if c.status == "published" and c.current_version_id is not None
        ],
        "batches": [
            {
                **(batch_out(b) or {}),
                "course_id": str(b.course_id) if getattr(b, "course_id", None) else None,
                "starts_on": b.starts_on.isoformat() if b.starts_on else None,
                "ends_on": b.ends_on.isoformat() if b.ends_on else None,
            }
            for b in cat.batches
            if b.status != "archived"
        ],
        "student_types": list(STUDENT_TYPES),
        "max_rows": MAX_ROWS,
        "email_integrated": email_integrated(),
    }


@r.post("/admin/students/import")
async def import_students(
    body: StudentImportIn,
    request: Request,
    session: PrincipalDbSession,
    dry_run: bool = Query(default=False, description="Validate every row and answer; write nothing."),
    principal: Principal = Depends(require_permission("user.invite")),
) -> JSONResponse:
    """Import students from a spreadsheet (``rows``) or enrol existing accounts (``user_ids``).

    ``dry_run=true``: per-row ``status`` new / existing / error, nothing written. Otherwise
    (Idempotency-Key required) per-row ``status`` created / existing / error; a failing row does
    not stop the others. ``temporary_password`` is in this response only."""
    from app.modules.admin.accounts import p5

    users_mode = bool(body.user_ids)
    names_batch = bool(_clean(body.batch)) or any(_clean(x.batch) for x in body.rows)
    await require_enrol_permissions(session, principal, batch=names_batch)
    if not users_mode and not dry_run and not body.confirm_adult:
        raise _vf(
            "confirm_adult",
            "adult_required",
            "Confirm every student is 18 or older (under-18s sign up themselves)",
        )
    if not dry_run and body.reason is not None and len(body.reason.strip()) < 3:
        raise _vf("reason", "too_short", "Give a reason (3+ characters) or leave it empty")
    cat = await Catalog.load(session)
    plans = await (plan_users(session, body, cat) if users_mode else plan_rows(session, body, cat))
    if dry_run:
        rows = [_row_out(p) for p in plans]
        return JSONResponse(
            {
                "dry_run": True,
                "mode": "users" if users_mode else "rows",
                "counts": _counts(rows),
                "rows": rows,
            }
        )
    p5(principal)
    reason = (body.reason or "").strip() or ("Bulk enrolment" if users_mode else "Student import")

    async def op() -> IdemResult:
        reveal.clear()
        out_rows: list[dict[str, Any]] = []
        for p in plans:
            out = _row_out(p)
            out_rows.append(out)
            if p.errors:
                continue
            new: NewAccount | None = None
            try:
                if p.user is None:
                    assert p.email is not None
                    new = await create_account(
                        session,
                        principal,
                        email=p.email,
                        phone=p.phone,
                        full_name=p.full_name,
                        password=None,
                        must_change_password=body.must_change_password,
                        college=p.college,
                        branch=p.branch,
                        reason=reason,
                        source="student_import",
                    )
                    p.user = new.user
                    out.update(status="created", user_id=str(new.user.id), username=new.username)
                    pw, idx = new.temporary_password, len(out_rows) - 1
                    if pw:
                        reveal.append(
                            lambda b, i=idx, v=pw: b["rows"][i].__setitem__("temporary_password", v)
                        )
                fields = _record_fields(
                    student_type=p.student_type if (not users_mode or body.student_type) else None,
                    college=p.college,
                    branch=p.branch,
                    year=p.year,
                    start_date=p.start_date,
                    end_date=p.end_date,
                )
                await save_student_record(
                    p.user.id,
                    fields,
                    source="import" if not users_mode else "bulk_enrol",
                    by=principal.user_id,
                )
            except ProblemError as e:
                out.update(status="error", errors=[str(e.detail or e.code)])
                continue
            except Exception as e:
                log.warning("student_import_row_failed", row=p.row, error=type(e).__name__)
                out.update(status="error", errors=["Couldn't create this account. Try this row again."])
                continue
            if p.course is not None or p.batch is not None:
                try:
                    res = await enrol(
                        session, principal, p.user.id, course=p.course, batch=p.batch, reason=reason
                    )
                    out.update(enrolled=res.enrolled, added_to_batch=res.added_to_batch)
                    if res.already_enrolled:
                        out["warnings"].append("Already enrolled in this course.")
                    if res.already_in_batch:
                        out["warnings"].append("Already in this batch.")
                except Exception as e:
                    detail = e.detail if isinstance(e, ProblemError) and e.detail else type(e).__name__
                    log.warning("student_import_enrol_failed", row=p.row, error=type(e).__name__)
                    msg = f"Enrolment failed ({detail}). Run the import again for this row to retry."
                    if new is None:
                        out.update(status="error", errors=[msg])
                    else:
                        out["warnings"].append(msg)  # the account exists: keep its login details
            if new is not None and new.temporary_password and body.send_email:
                status = await send_login_email(
                    name=p.full_name,
                    username=new.username,
                    email=str(new.user.email),
                    temporary_password=new.temporary_password,
                    must_change_password=True,
                )
                out["email_status"] = status
        counts = _counts(out_rows)
        await audit(
            session,
            principal,
            "admin.students.imported" if not users_mode else "admin.students.enrolled",
            "student_import",
            None,
            reason=reason,
            after={
                k: counts[k]
                for k in ("total", "created", "existing", "errors", "enrolled", "added_to_batch", "emailed")
            },
        )
        return IdemResult(
            {
                "dry_run": False,
                "mode": "users" if users_mode else "rows",
                "counts": counts,
                "rows": out_rows,
                "credentials_withheld": True,  # the replay record; this response gets False
            },
            status=200,
        )

    reveal: list[Callable[[Any], None]] = []
    return await reveal_once(request, session, user_id=principal.user_id, operation=op, reveal=reveal)


@r.post("/admin/students/send-login")
async def send_login(
    body: SendLoginIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.invite")),
) -> JSONResponse:
    """Email each account a NEW temporary password (the old one stops working). Only when email
    is integrated; staff accounts are refused (Admin > Users > Set new password instead)."""
    from app.modules.admin.accounts import p5
    from app.modules.identity import service as ids
    from app.modules.notifications.adapters import email_integrated
    from app.modules.rbac.service import active_grants
    from app.modules.sessions import service as ss

    if not email_integrated():
        raise ProblemError(
            "conflict",
            status=409,
            detail="Email isn't connected yet. Download the login details and share them yourself.",
            reason="email_not_connected",
        )
    p5(principal)
    ids_ = list(dict.fromkeys(body.user_ids))

    async def op() -> IdemResult:
        from app.modules.admissions.onboarding import new_temp_password

        users = await ipub.get_users(session, ids_)
        profiles = await ipub.get_profiles(session, ids_)
        rows: list[dict[str, Any]] = []
        for uid in ids_:
            u = users.get(uid)
            row: dict[str, Any] = {"user_id": str(uid), "status": "error", "message": None}
            rows.append(row)
            if u is None or u.status != "active" or not u.email:
                row["message"] = "Account not found, not active or without an email."
                continue
            if any(g.role != "student" for g in await active_grants(session, uid)):
                row["message"] = "Staff account: set its password in Admin > Users."
                continue
            temp = new_temp_password()
            await ids.set_password(session, uid, temp, must_change_password=body.must_change_password)
            await ss.revoke_all_sessions(session, uid, "admin_kill", ended_by=principal.user_id)
            prof = profiles.get(uid)
            st = await send_login_email(
                name=(prof.full_name if prof else "") or u.email,
                username=u.username,
                email=u.email,
                temporary_password=temp,
                must_change_password=body.must_change_password,
            )
            row["status"] = st
        sent = sum(1 for x in rows if x["status"] == "sent")
        await audit(
            session,
            principal,
            "admin.students.login_sent",
            "student_import",
            None,
            after={"total": len(rows), "sent": sent, "failed": len(rows) - sent},
        )
        return IdemResult({"counts": {"total": len(rows), "sent": sent}, "rows": rows})

    return await idempotent(
        request, idem_session(session), user_id=principal.user_id, operation=op, required=True
    )
