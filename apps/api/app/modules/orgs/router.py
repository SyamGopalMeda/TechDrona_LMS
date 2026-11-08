"""Batches (cohorts) of the single company (REMOVAL-PLAN §3; api-spec §8 ORG-20..27).

Single-company LMS: organizations are an internal tenancy key (``app.core.company``) and have
no API. ``/orgs/**``, ``/invitations/**`` and ``/me/orgs`` were removed together with college
invitations, roster imports, per-org settings and the coordinator role.

* ``GET /batches`` — Admin (``org.read`` @P) sees every batch; a trainer sees the batches they
  hold a batch grant on.
* ``POST /batches`` — ``batch.create`` @P; the batch belongs to ``COMPANY_ORG_ID``.
* ``GET/PATCH /batches/{id}``, ``/archive``, ``/members`` — unchanged permissions at batch scope.
* ``POST /batches/{id}/members`` accepts any account that is not deactivated or deleted (by
  user id or e-mail). It creates or reactivates the user's membership in the batch's
  organization (``org_memberships``: ``student`` for student members, ``staff`` otherwise;
  ``source='staff'``). When a student's last active batch membership ends, their student
  membership is set to ``left`` (that removes the organization from their ``org_ids``).

Tenant isolation: queries run on ``PrincipalDbSession`` (RLS); account look-ups by e-mail run
as a named system job because staff cannot read accounts that are not yet members.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.core.audit import audit
from app.core.auth import (
    PLATFORM_SCOPE,
    ScopeRef,
    require_active_principal,
    require_permission,
    scope_from_path,
)
from app.core.company import COMPANY_ORG_ID
from app.core.db import PrincipalDbSession, system_context
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339
from app.modules.identity import clock
from app.modules.identity.contacts import normalize_email
from app.modules.identity.models import User, UserProfile
from app.modules.orgs.models import Batch, BatchMember
from app.modules.orgs.service import end_student_membership_if_no_batches, ensure_org_membership

r = authenticated_router(tags=["batches"])

BatchScope = scope_from_path("batch_id", "batch")


def _archived(b: Batch) -> None:
    if b.status == "archived":
        raise ProblemError("invalid_state_transition", current_state="archived", allowed=[])


def _perm(key: str, scope: Any = None) -> Any:
    return Depends(require_permission(key, scope=scope))


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
    }


async def _batch(session: Any, batch_id: uuid.UUID) -> Batch:
    b = await session.get(Batch, batch_id)
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
) -> dict[str, Any]:
    from app.modules.rbac.service import check_permission

    q = select(Batch).order_by(Batch.code)
    if status is not None:
        q = q.where(Batch.status == status)
    if not await check_permission(session, principal, "org.read", PLATFORM_SCOPE):
        mine = [
            g.scope_id
            for g in principal.grants
            if g.scope_type == "batch"
            and g.scope_id is not None
            and await check_permission(session, principal, "org.member.read", ScopeRef("batch", g.scope_id))
        ]
        if not mine:
            raise ProblemError("permission_denied", permission="org.read")
        q = q.where(Batch.id.in_(mine))
    return {"data": [_batch_out(b) for b in (await session.execute(q)).scalars()]}


@r.post("/batches", status_code=201)
async def create_batch(
    body: BatchIn,
    session: PrincipalDbSession,
    principal: Principal = _perm("batch.create", PLATFORM_SCOPE),
) -> dict[str, Any]:
    if body.starts_on and body.ends_on and body.ends_on < body.starts_on:
        raise _vf("ends_on", "before_start", "End date is before start date")
    dup = (
        await session.execute(
            select(Batch.id).where(Batch.organization_id == COMPANY_ORG_ID, Batch.code == body.code)
        )
    ).scalar_one_or_none()
    if dup:
        raise _vf("code", "duplicate", "A batch with this code exists", 409)
    b = Batch(id=uuid7(), organization_id=COMPANY_ORG_ID, created_by=principal.user_id, **body.model_dump())
    try:
        async with session.begin_nested():
            session.add(b)
            await session.flush()
    except IntegrityError as e:  # concurrent create with the same code (uq_batches_org_code)
        raise _vf("code", "duplicate", "A batch with this code exists", 409) from e
    await _audit_batch(session, principal, "batch.created", b, after={"code": b.code})
    return _batch_out(b)


@r.get("/batches/{batch_id}", openapi_extra={"x-td-idle": "neutral"})
async def get_batch(
    batch_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = _perm("org.member.read", BatchScope),
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
    await session.flush()
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
    await session.flush()
    await _audit_batch(
        session, principal, "batch.archived", b, before={"status": before}, after={"status": "archived"}
    )
    return _batch_out(b)


@r.get("/batches/{batch_id}/members", openapi_extra={"x-td-idle": "neutral"})
async def batch_members(
    batch_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = _perm("org.member.read", BatchScope),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(BatchMember, UserProfile.full_name)
            .outerjoin(UserProfile, UserProfile.user_id == BatchMember.user_id)
            .where(BatchMember.batch_id == batch_id, BatchMember.status == "active")
            .order_by(BatchMember.added_at)
        )
    ).all()
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
    async with system_context(session, "orgs.batch_member_lookup"):
        rows = (
            await session.execute(
                select(User.id, User.email).where(
                    or_(User.id.in_(body.user_ids), User.email.in_(emails)),
                    User.status.not_in(("deactivated", "deleted")),
                    User.deleted_at.is_(None),
                )
            )
        ).all()
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
    for uid in user_ids:
        await ensure_org_membership(
            session, b.organization_id, uid, member_type=member_type, added_by=principal.user_id
        )
        if src is not None:
            for old in (
                await session.execute(
                    select(BatchMember).where(
                        BatchMember.batch_id == src.id,
                        BatchMember.user_id == uid,
                        BatchMember.status == "active",
                    )
                )
            ).scalars():
                old.status = "removed"
                old.removed_at = now
        live = (
            await session.execute(
                select(BatchMember.id).where(
                    BatchMember.batch_id == b.id,
                    BatchMember.user_id == uid,
                    BatchMember.member_role == body.member_role,
                    BatchMember.status == "active",
                )
            )
        ).scalar_one_or_none()
        if live is None:
            session.add(
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
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as e:  # concurrent add of the same member (ux_bm_live)
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
    rows = list(
        (
            await session.execute(
                select(BatchMember).where(
                    BatchMember.batch_id == batch_id,
                    BatchMember.user_id == user_id,
                    BatchMember.status == "active",
                )
            )
        ).scalars()
    )
    if not rows:
        raise ProblemError("not_found")
    for m in rows:
        m.status = "removed"
        m.removed_at = clock.now()
    await session.flush()
    await end_student_membership_if_no_batches(session, b.organization_id, user_id)
    await _audit_batch(session, principal, "batch.member.removed", b, subject_user_id=user_id)
    return {"removed": True}


router = APIRouter()
router.include_router(r)
