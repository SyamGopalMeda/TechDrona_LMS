"""Public orgs functions for other modules (no HTTP).

Single-company LMS: the only organization is ``app.core.company.COMPANY_ORG_ID`` (after
``orgs_0003`` re-homes every row); the functions below keep their signatures so callers in
other modules keep working, and they naturally return the company organization.

``get_learner_org_context`` answers "which organization / batch does this learner's activity
belong to" from orgs-owned tables only (audit BE-02: analytics attribution of client activity).
Public (B2C) learners who are in no batch have no organization membership and get ``None``:
their activity stays private to them (RLS family U/O), it is never stamped with the company org.
It runs on the caller's session; under a learner's own RLS context the learner can read their
own ``org_memberships`` / ``batch_members`` rows, and system/platform contexts see everything.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.orgs.models import Batch, BatchMember, Organization, OrgMembership


def _fs() -> bool:
    """``TD_STORE_ORGS=firestore``: orgs tables live in Firestore (repo_firestore)."""
    return uses_firestore("orgs")


def _repo() -> Any:
    from app.modules.orgs.repo_firestore import system_repo

    return system_repo()


async def _fs_learner_org_context(user_id: uuid.UUID, batch_id: uuid.UUID | None) -> LearnerOrgContext | None:
    repo = _repo()
    active_orgs = set(await repo.active_student_org_ids(user_id))
    members = [
        m
        for m in await repo.batch_memberships_for(user_id)
        if m.status == "active" and m.member_role == "student"
    ]
    batches = await repo.get_batches(list({m.batch_id for m in members}))
    live = [m for m in members if m.batch_id in batches and batches[m.batch_id].status != "archived"]
    if batch_id is not None:
        for m in live:
            if m.batch_id == batch_id and m.organization_id in active_orgs:
                return LearnerOrgContext(organization_id=m.organization_id, batch_id=batch_id)
    if len(active_orgs) != 1:
        return None
    org_id = next(iter(active_orgs))
    ids = {m.batch_id for m in live if m.organization_id == org_id}
    return LearnerOrgContext(organization_id=org_id, batch_id=next(iter(ids)) if len(ids) == 1 else None)


@dataclass(frozen=True)
class LearnerOrgContext:
    organization_id: uuid.UUID
    batch_id: uuid.UUID | None


async def get_learner_org_context(
    session: AsyncSession, user_id: uuid.UUID, *, batch_id: uuid.UUID | None = None
) -> LearnerOrgContext | None:
    """The learner's organization (and batch) for attribution. Deterministic rule:

    1. ``batch_id`` (a server-verified hint, e.g. ``enrolments.batch_id`` or a client hint the
       caller wants checked): used only if the user is an *active* student member of that
       batch, the batch is not archived, and the user's membership in the batch's organization
       is active -> (batch's organization, batch).
    2. Otherwise exactly one active student membership in a live (not deleted, not suspended)
       organization -> that organization; its batch is the user's single active, non-archived
       student batch in that organization, else ``None`` (0 or several batches = ambiguous).
    3. Otherwise (no membership, or several organizations) -> ``None``: never guess.

    Course-specific attribution belongs to the enrolment (``enrolments.organization_id`` /
    ``batch_id``, learning module); callers that know the enrolment should pass its
    ``batch_id`` or use the enrolment's organization first.
    """
    if _fs():
        return await _fs_learner_org_context(user_id, batch_id)
    live_orgs = select(Organization.id).where(
        Organization.deleted_at.is_(None), Organization.status == "active"
    )
    active_orgs = (
        select(OrgMembership.organization_id)
        .where(
            OrgMembership.user_id == user_id,
            OrgMembership.status == "active",
            OrgMembership.member_type == "student",
            OrgMembership.organization_id.in_(live_orgs),
        )
        .distinct()
    )
    if batch_id is not None:
        row = (
            await session.execute(
                select(BatchMember.organization_id)
                .join(Batch, Batch.id == BatchMember.batch_id)
                .where(
                    BatchMember.batch_id == batch_id,
                    BatchMember.user_id == user_id,
                    BatchMember.status == "active",
                    BatchMember.member_role == "student",
                    Batch.status != "archived",
                    BatchMember.organization_id.in_(active_orgs),
                )
                .limit(1)
            )
        ).first()
        if row is not None:
            return LearnerOrgContext(organization_id=row[0], batch_id=batch_id)
    orgs = list((await session.execute(active_orgs.limit(2))).scalars())
    if len(orgs) != 1:
        return None
    org_id = orgs[0]
    batches = list(
        (
            await session.execute(
                select(BatchMember.batch_id)
                .join(Batch, Batch.id == BatchMember.batch_id)
                .where(
                    BatchMember.user_id == user_id,
                    BatchMember.organization_id == org_id,
                    BatchMember.status == "active",
                    BatchMember.member_role == "student",
                    Batch.status != "archived",
                )
                .distinct()
                .limit(2)
            )
        ).scalars()
    )
    return LearnerOrgContext(organization_id=org_id, batch_id=batches[0] if len(batches) == 1 else None)


async def active_student_org_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Public: the live (active, not deleted) organizations where ``user_id`` has an active
    student membership, ordered by id (analytics BE-02 attribution; requested by ``assess``)."""
    if _fs():
        return await _repo().active_student_org_ids(user_id)
    rows = await session.execute(
        select(OrgMembership.organization_id)
        .join(Organization, Organization.id == OrgMembership.organization_id)
        .where(
            OrgMembership.user_id == user_id,
            OrgMembership.status == "active",
            OrgMembership.member_type == "student",
            Organization.deleted_at.is_(None),
            Organization.status == "active",
        )
        .distinct()
        .order_by(OrgMembership.organization_id)
    )
    return list(rows.scalars())


async def batch_org_for_member(
    session: AsyncSession, batch_id: uuid.UUID, user_id: uuid.UUID
) -> uuid.UUID | None:
    """Public: the organization of ``batch_id`` when ``user_id`` is an active student member of
    that (non-archived) batch and still an active member of its live organization, else None.
    Lets callers verify a client ``batch_id`` hint (BE-02)."""
    ctx = await get_learner_org_context(session, user_id, batch_id=batch_id)
    return ctx.organization_id if ctx is not None and ctx.batch_id == batch_id else None


# --------------------------------------------------------------------------- memberships


async def ensure_org_membership(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    member_type: str,
    added_by: uuid.UUID | None,
) -> OrgMembership:
    """Create or reactivate ``user_id``'s membership in ``org_id`` (the company org) when they
    join a batch. ``staff`` is never downgraded to ``student``. Runs on the caller's session
    (RLS family T: the caller must hold the organization in ``app.org_ids`` or be platform)."""
    if _fs():
        return await _repo().ensure_membership(org_id, user_id, member_type=member_type, added_by=added_by)
    m = (
        await session.execute(
            select(OrgMembership).where(
                OrgMembership.organization_id == org_id, OrgMembership.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    now = clock.now()
    if m is None:
        m = OrgMembership(
            id=uuid7(),
            organization_id=org_id,
            user_id=user_id,
            member_type=member_type,
            status="active",
            joined_at=now,
            invited_by=added_by,
            source="staff",
        )
        session.add(m)
        await session.flush()
        return m
    if m.status != "active":
        m.status = "active"
        m.left_at = None
        m.joined_at = m.joined_at or now
    if member_type == "staff" and m.member_type != "staff":
        m.member_type = "staff"
    await session.flush()
    return m


async def end_student_membership_if_no_batches(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """REMOVAL-PLAN §3: when a student's last active batch membership in ``org_id`` ends,
    their *student* org membership becomes ``left`` (staff memberships are untouched).
    Returns True when the membership was ended."""
    if _fs():
        return await _repo().end_student_membership_if_no_batches(org_id, user_id)
    still = (
        await session.execute(
            select(BatchMember.id)
            .where(
                BatchMember.organization_id == org_id,
                BatchMember.user_id == user_id,
                BatchMember.status == "active",
            )
            .limit(1)
        )
    ).first()
    if still is not None:
        return False
    m = (
        await session.execute(
            select(OrgMembership).where(
                OrgMembership.organization_id == org_id,
                OrgMembership.user_id == user_id,
                OrgMembership.member_type == "student",
                OrgMembership.status == "active",
            )
        )
    ).scalar_one_or_none()
    if m is None:
        return False
    m.status = "left"
    m.left_at = clock.now()
    await session.flush()
    return True


# --------------------------------------------------------------------------- attendance gate


async def attendance_certificate_block(
    session: AsyncSession, batch_id: uuid.UUID, user_id: uuid.UUID
) -> str | None:
    """Public (learning certificates, ``due_enrolments``): why ``user_id`` may not get a
    certificate yet because of attendance in ``batch_id``, else ``None``.

    Off unless the batch plan sets ``min_attendance_percent`` (orgs_0005; NULL = off, the
    default). Classes never marked for the learner do not block (website ``evaluate`` rule);
    late counts as attended; cancelled classes are ignored. Runs on the caller's session.
    """
    from app.modules.orgs.course_plan import attendance_block_reason, summarize
    from app.modules.orgs.models import BatchPlan, ClassAttendance, ClassSession

    if _fs():
        plan = await _repo().batch_plan(batch_id)
        if plan is None or not plan.min_attendance_percent:
            return None
        marks = await _repo().attendance_statuses(batch_id, user_id)
        return attendance_block_reason(summarize(marks), plan.min_attendance_percent)
    minimum = (
        await session.execute(select(BatchPlan.min_attendance_percent).where(BatchPlan.batch_id == batch_id))
    ).scalar_one_or_none()
    if not minimum:
        return None
    statuses = list(
        (
            await session.execute(
                select(ClassAttendance.status)
                .join(ClassSession, ClassSession.id == ClassAttendance.session_id)
                .where(
                    ClassAttendance.batch_id == batch_id,
                    ClassAttendance.user_id == user_id,
                    ClassSession.cancelled.is_(False),
                )
            )
        ).scalars()
    )
    return attendance_block_reason(summarize(statuses), minimum)
