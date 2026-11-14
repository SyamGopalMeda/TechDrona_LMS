"""Batches (cohorts) of the single company (REMOVAL-PLAN §3; api-spec §8 ORG-20..27).

Single-company LMS: organizations are an internal tenancy key (``app.core.company``) and have
no API. ``/orgs/**``, ``/invitations/**`` and ``/me/orgs`` were removed together with college
invitations, roster imports, per-org settings and the coordinator role.

* ``GET /batches`` — Admin (``org.read`` @P) sees every batch; a trainer or evaluator sees the
  batches they hold a batch grant on. ``?mine=true`` limits anyone (Admin included) to their own
  batch grants.
* ``POST /batches`` — ``batch.create`` @P; the batch belongs to ``COMPANY_ORG_ID``.
* ``GET /batches/{id}`` and ``GET /batches/{id}/members`` — batch read (``BATCH_READ_PERMISSIONS``
  at that batch: Trainer and Evaluator of the batch, Admin). ``PATCH``, ``/archive`` and member
  changes keep their own permissions at batch scope.
* ``/batches/{id}/plan``, ``/schedule``, ``/sessions``, ``/attendance`` and ``/me/classes``,
  ``/me/attendance``: ``app.modules.orgs.classes`` (delivery moved from the website back office).
* ``POST /batches/{id}/members`` accepts any account that is not deactivated or deleted (by
  user id or e-mail). It creates or reactivates the user's membership in the batch's
  organization (``org_memberships``: ``student`` for student members, ``staff`` otherwise;
  ``source='staff'``). When a student's last active batch membership ends, their student
  membership is set to ``left`` (that removes the organization from their ``org_ids``).

Tenant isolation: queries run on ``PrincipalDbSession`` (RLS); account look-ups by e-mail run
as a named system job because staff cannot read accounts that are not yet members.

Storage: every read/write goes through ``app.modules.orgs.route_store`` (Postgres SQL as before,
or the Firestore repository with ``TD_STORE_ORGS=firestore``; no Postgres session is used then).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.audit import audit
from app.core.auth import (
    PLATFORM_SCOPE,
    ScopeRef,
    check_permission,
    require_active_principal,
    require_permission,
    scope_from_path,
)
from app.core.company import COMPANY_ORG_ID
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import ist_date, to_rfc3339
from app.modules.identity import clock
from app.modules.identity.contacts import normalize_email
from app.modules.identity.fs_uow import unit_of_work
from app.modules.orgs import route_store as rs
from app.modules.orgs.models import Batch, BatchMember
from app.modules.orgs.service import end_student_membership_if_no_batches, ensure_org_membership

r = authenticated_router(tags=["batches"])
# Firestore: changes to loaded rows are written at the end of a successful request (fs_uow).
_UOW = [Depends(unit_of_work, scope="function")]

BatchScope = scope_from_path("batch_id", "batch")


def _archived(b: Batch) -> None:
    if b.status == "archived":
        raise ProblemError("invalid_state_transition", current_state="archived", allowed=[])


def _perm(key: str, scope: Any = None) -> Any:
    return Depends(require_permission(key, scope=scope))


# Batch read: the batch's name/dates and its roster (live audit 2026-11-14, F1). The matrix gives
# ``org.member.read`` to the Trainer (B) and Admin (P) only, so an Evaluator of the batch got 403
# on ``GET /batches/{id}`` and ``/members`` and an empty ``?mine=true``: the grading and integrity
# screens fell back to "Student" and an empty batch filter. The Evaluator holds ``progress.read``
# at its batch, and reading learners' progress in a batch already discloses who they are, so
# either permission AT THAT BATCH allows these two reads. Nothing else changes: classes,
# attendance and the plan (``orgs.classes``) and every write keep their own permissions, and a
# grant on batch A never covers batch B. Done in code, not in the catalogue, so it needs no change
# to the deployed ``role_permissions`` collection.
BATCH_READ_PERMISSIONS = ("org.member.read", "progress.read")


async def can_read_batch(principal: Principal, scope: ScopeRef, request: Request | None = None) -> bool:
    """Batch read (``BATCH_READ_PERMISSIONS``) at ``scope``; an unknown batch raises 404 (TI-02)."""
    for key in BATCH_READ_PERMISSIONS:
        if await check_permission(principal, key, scope, request, cross_tenant_raises=True):
            return True
    return False


async def _require_batch_read(
    request: Request, principal: Principal = Depends(require_active_principal)
) -> Principal:
    if not await can_read_batch(principal, BatchScope(request), request):
        raise ProblemError("permission_denied", permission=BATCH_READ_PERMISSIONS[0])
    used = getattr(request.state, "permissions_used", None)
    if used is None:
        request.state.permissions_used = used = []
    used.append(BATCH_READ_PERMISSIONS[0])
    return principal


_require_batch_read.td_permission = BATCH_READ_PERMISSIONS[0]  # type: ignore[attr-defined]  # route guard listings


def _vf(field: str, code: str, msg: str, status: int = 422) -> ProblemError:
    return ProblemError("validation_failed", status, errors=[{"field": field, "code": code, "message": msg}])


# --------------------------------------------------------------------------- schemas


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchIn(Strict):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    academic_year: str | None = Field(default=None, max_length=9)
    graduation_year: int | None = Field(default=None, ge=1990, le=2100)
    starts_on: date | None = None
    ends_on: date | None = None
    # Omitted: "planned" when the batch starts after today (IST), else "active".
    status: Literal["planned", "active"] | None = None


class BatchPatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    academic_year: str | None = Field(default=None, max_length=9)
    graduation_year: int | None = Field(default=None, ge=1990, le=2100)
    starts_on: date | None = None
    ends_on: date | None = None
    status: Literal["planned", "active", "completed"] | None = None


class BatchMembersIn(Strict):
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    emails: list[str] = Field(default_factory=list, max_length=500)
    member_role: Literal["student", "trainer", "mentor"] = "student"
    move_from_batch_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _some(self) -> BatchMembersIn:
        if not self.user_ids and not self.emails:
            raise ValueError("give user_ids or emails")
        if len(self.user_ids) + len(self.emails) > 500:
            raise ValueError("at most 500 members per request")
        return self


def _batch_out(b: Batch) -> dict[str, Any]:
    return {
        "id": str(b.id),
        "organization_id": str(b.organization_id),
        "name": b.name,
        "code": b.code,
        "academic_year": b.academic_year,
        "graduation_year": b.graduation_year,
        "starts_on": b.starts_on.isoformat() if b.starts_on else None,
        "ends_on": b.ends_on.isoformat() if b.ends_on else None,
        "status": b.status,
        # orgs_0005: course links (edited with the batch plan, ``PUT /batches/{id}/plan``)
        "course_id": str(b.course_id) if b.course_id else None,
        "website_course_slug": b.website_course_slug,
    }


async def _batch(session: Any, batch_id: uuid.UUID) -> Batch:
    b = await rs.get_batch(session, batch_id)
    if b is None:
        raise ProblemError("not_found")
    return b


async def _audit_batch(session: Any, principal: Principal, action: str, b: Batch, **kw: Any) -> None:
    await audit(session, principal, action, "batch", b.id, organization_id=b.organization_id, **kw)


# --------------------------------------------------------------------------- ORG-20..27 batches


@r.get("/batches", openapi_extra={"x-td-idle": "neutral"})
async def list_batches(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    status: Literal["planned", "active", "completed", "archived"] | None = None,
    mine: bool = False,
) -> dict[str, Any]:
    """``mine=true``: only the batches the caller holds a batch grant on (trainer/evaluator),
    even for an Admin. The Teacher portal uses it so an Admin who made themselves the trainer of
    a batch sees the batches they teach there, not every batch (that is the Admin portal).
    A batch grant counts when it gives batch read there (``BATCH_READ_PERMISSIONS``)."""
    from app.modules.rbac.service import check_permission as rbac_check

    async def _reads(batch_id: uuid.UUID) -> bool:
        ref = ScopeRef("batch", batch_id)
        for key in BATCH_READ_PERMISSIONS:
            try:
                if await rbac_check(session, principal, key, ref):
                    return True
            except ProblemError:  # a grant on a batch that no longer exists
                return False
        return False

    ids: list[uuid.UUID] | None = None
    if mine or not await rbac_check(session, principal, "org.read", PLATFORM_SCOPE):
        own = [
            g.scope_id
            for g in principal.grants
            if g.scope_type == "batch" and g.scope_id is not None and await _reads(g.scope_id)
        ]
        if not own:
            if mine:
                return {"data": []}
            raise ProblemError("permission_denied", permission="org.read")
        ids = own
    return {"data": [_batch_out(b) for b in await rs.list_batches(session, status=status, ids=ids)]}


@r.post("/batches", status_code=201)
async def create_batch(
    body: BatchIn,
    session: PrincipalDbSession,
    principal: Principal = _perm("batch.create", PLATFORM_SCOPE),
) -> dict[str, Any]:
    if body.starts_on and body.ends_on and body.ends_on < body.starts_on:
        raise _vf("ends_on", "before_start", "End date is before start date")
    if await rs.code_taken(session, COMPANY_ORG_ID, body.code):
        raise _vf("code", "duplicate", "A batch with this code exists", 409)
    status = body.status or (
        "planned" if body.starts_on is not None and body.starts_on > ist_date(clock.now()) else "active"
    )
    b = Batch(
        id=uuid7(),
        organization_id=COMPANY_ORG_ID,
        created_by=principal.user_id,
        status=status,
        **body.model_dump(exclude={"status"}),
    )
    try:
        b = await rs.insert_batch(session, b)
    except rs.Duplicate as e:  # concurrent create with the same code (uq_batches_org_code)
        raise _vf("code", "duplicate", "A batch with this code exists", 409) from e
    await _audit_batch(session, principal, "batch.created", b, after={"code": b.code})
    return _batch_out(b)


@r.get("/batches/{batch_id}", openapi_extra={"x-td-idle": "neutral"})
async def get_batch(
    batch_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(_require_batch_read),
) -> dict[str, Any]:
    return _batch_out(await _batch(session, batch_id))


@r.patch("/batches/{batch_id}")
async def patch_batch(
    batch_id: uuid.UUID,
    body: BatchPatch,
    session: PrincipalDbSession,
    principal: Principal = _perm("batch.update", BatchScope),
) -> dict[str, Any]:
    b = await _batch(session, batch_id)
    _archived(b)  # archived batches are read-only; un-archiving is not a PATCH (BE-18)
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if getattr(b, k) != v}
    starts = changes.get("starts_on", b.starts_on)
    ends = changes.get("ends_on", b.ends_on)
    if starts and ends and ends < starts:
        raise _vf("ends_on", "before_start", "End date is before start date")
    if not changes:
        return _batch_out(b)
    before = {k: str(getattr(b, k)) if getattr(b, k) is not None else None for k in changes}
    for k, v in changes.items():
        setattr(b, k, v)
    await rs.save_batch(session, b)
    await _audit_batch(
        session,
        principal,
        "batch.updated",
        b,
        before=before,
        after={"fields": sorted(changes), **({"status": b.status} if "status" in changes else {})},
    )
    return _batch_out(b)


@r.post("/batches/{batch_id}/archive")
async def archive_batch(
    batch_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = _perm("batch.archive", BatchScope),
) -> dict[str, Any]:
    b = await _batch(session, batch_id)
    _archived(b)  # re-archiving is a 409, and only a real transition is audited (BE-18)
    before = b.status
    b.status = "archived"
    await rs.save_batch(session, b)
    await _audit_batch(
        session, principal, "batch.archived", b, before={"status": before}, after={"status": "archived"}
    )
    return _batch_out(b)


@r.get("/batches/{batch_id}/members", openapi_extra={"x-td-idle": "neutral"})
async def batch_members(
    batch_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(_require_batch_read),
) -> dict[str, Any]:
    rows = await rs.active_members_named(session, batch_id)
    return {
        "data": [
            {
                "user_id": str(m.user_id),
                "full_name": n,
                "member_role": m.member_role,
                "added_at": to_rfc3339(m.added_at),
            }
            for m, n in rows
        ]
    }


async def _resolve_accounts(session: Any, body: BatchMembersIn) -> list[uuid.UUID]:
    """Ids of the requested accounts (not deactivated/deleted). Unknown or unusable accounts
    are a 422 listing how many were refused; e-mails are never echoed back (TI-05)."""
    emails: list[str] = []
    bad = 0
    for raw in body.emails:
        e = normalize_email(raw)
        if e is None:
            raise _vf("emails", "invalid_email", "One or more e-mail addresses are not valid")
        emails.append(e)
    rows = await rs.lookup_accounts(session, body.user_ids, emails)
    by_id = {uid for uid, _ in rows}
    by_email = {str(em).lower(): uid for uid, em in rows if em}
    out: list[uuid.UUID] = []
    for uid in body.user_ids:
        if uid in by_id:
            out.append(uid)
        else:
            bad += 1
    for e in emails:
        if e in by_email:
            out.append(by_email[e])
        else:
            bad += 1
    if bad:
        raise _vf("user_ids", "unknown_account", f"{bad} account(s) were not found or are not active")
    return list(dict.fromkeys(out))


@r.post("/batches/{batch_id}/members")
async def add_batch_members(
    batch_id: uuid.UUID,
    body: BatchMembersIn,
    session: PrincipalDbSession,
    principal: Principal = _perm("batch.member.manage", BatchScope),
) -> dict[str, Any]:
    from app.modules.rbac.service import check_permission

    b = await _batch(session, batch_id)
    _archived(b)
    src: Batch | None = None
    if body.move_from_batch_id:
        if body.move_from_batch_id == b.id:
            raise _vf("move_from_batch_id", "same_batch", "Choose a different source batch")
        src = await _batch(session, body.move_from_batch_id)
        if src.organization_id != b.organization_id or not await check_permission(
            session, principal, "batch.member.manage", ScopeRef("batch", src.id)
        ):
            raise ProblemError("not_found")
        _archived(src)
    user_ids = await _resolve_accounts(session, body)
    member_type = "student" if body.member_role == "student" else "staff"
    added = 0
    now = clock.now()
    new_rows: list[BatchMember] = []
    for uid in user_ids:
        await ensure_org_membership(
            session, b.organization_id, uid, member_type=member_type, added_by=principal.user_id
        )
        if src is not None:
            await rs.end_member_rows(session, await rs.active_rows(session, src.id, uid), now)
        if not await rs.active_rows(session, b.id, uid, body.member_role):
            new_rows.append(
                BatchMember(
                    id=uuid7(),
                    batch_id=b.id,
                    organization_id=b.organization_id,
                    user_id=uid,
                    member_role=body.member_role,
                    added_by=principal.user_id,
                )
            )
            added += 1
    try:
        await rs.add_members(session, new_rows)
    except rs.Duplicate as e:  # concurrent add of the same member (ux_bm_live)
        raise ProblemError(
            "invalid_state_transition",
            detail="These members were just added by someone else. Refresh and try again.",
            current_state="already_member",
            allowed=[],
        ) from e
    if added == 0 and src is None:
        return {"added": 0}
    await _audit_batch(
        session,
        principal,
        "batch.members.added",
        b,
        after={"added": added, "moved_from": src.id if src else None},
    )
    return {"added": added}


@r.delete("/batches/{batch_id}/members/{user_id}")
async def remove_batch_member(
    batch_id: uuid.UUID,
    user_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = _perm("batch.member.manage", BatchScope),
) -> dict[str, Any]:
    b = await _batch(session, batch_id)
    _archived(b)
    rows = await rs.active_rows(session, batch_id, user_id)
    if not rows:
        raise ProblemError("not_found")
    await rs.end_member_rows(session, rows, clock.now())
    await end_student_membership_if_no_batches(session, b.organization_id, user_id)
    await _audit_batch(session, principal, "batch.member.removed", b, subject_user_id=user_id)
    return {"removed": True}


router = APIRouter()
router.include_router(r, dependencies=_UOW)

# Plan, schedule, classes and attendance of a batch + the learner's own classes (orgs_0005).
from app.modules.orgs.classes import r as _classes_router  # noqa: E402

router.include_router(_classes_router, dependencies=_UOW)
