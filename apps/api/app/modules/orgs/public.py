"""Store-neutral orgs API for other modules (``TD_STORE_ORGS`` = postgres | firestore).

Replaces direct SQL on ``organizations``, ``org_memberships``, ``batches``, ``batch_members``,
``batch_plans``, ``class_sessions`` and ``class_attendance`` in admin, admissions,
assessments, coding, learning, mentoring, notifications, paths, placement, security and the
seeds. Joins become two calls (e.g. ``batch_members`` then ``get_batches``). Change data only
through the write functions here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.backend import uses_firestore
from app.modules.orgs.models import Batch, BatchMember, BatchPlan, Organization, OrgMembership


def _fs() -> bool:
    return uses_firestore("orgs")


def _repo() -> Any:
    from app.modules.orgs.repo_firestore import system_repo

    return system_repo()


# --------------------------------------------------------------------------- organizations


async def get_org(session: AsyncSession, org_id: uuid.UUID) -> Organization | None:
    if _fs():
        return await _repo().get_org(org_id)
    return await session.get(Organization, org_id)


async def add_org(session: AsyncSession, org: Organization) -> Organization:
    if _fs():
        from app.modules.orgs.store_specs import ORGS

        return await _repo()._upsert(ORGS, str(org.id), org)
    session.add(org)
    await session.flush()
    return org


# --------------------------------------------------------------------------- batches


async def get_batch(session: AsyncSession, batch_id: uuid.UUID) -> Batch | None:
    if _fs():
        return await _repo().get_batch(batch_id)
    return await session.get(Batch, batch_id)


async def get_batches(session: AsyncSession, batch_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Batch]:
    ids = list(dict.fromkeys(batch_ids))
    if not ids:
        return {}
    if _fs():
        return await _repo().get_batches(ids)
    return {b.id: b for b in (await session.execute(select(Batch).where(Batch.id.in_(ids)))).scalars().all()}


async def batch_names(session: AsyncSession, batch_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    return {k: b.name for k, b in (await get_batches(session, batch_ids)).items()}


async def list_batches(
    session: AsyncSession,
    *,
    status: str | None = None,
    exclude_status: str | None = None,
    organization_id: uuid.UUID | None = None,
    organization_ids: Iterable[uuid.UUID] | None = None,
    ids: Iterable[uuid.UUID] | None = None,
    code: str | None = None,
    has_course: bool | None = None,
    order: str = "name",
) -> list[Batch]:
    """Batches matching every filter; ``order``: ``name`` / ``created`` / ``id``."""
    oids = set(organization_ids) if organization_ids is not None else None
    bids = set(ids) if ids is not None else None
    if _fs():
        from app.modules.orgs.store_specs import BATCHES

        f: list[Any] = []
        if status is not None:
            f.append(("status", "==", status))
        if code is not None:
            f.append(("code", "==", code))
        rows: list[Batch] = await _repo()._objs(Batch, BATCHES, filters=tuple(f))
        rows = [
            b
            for b in rows
            if (exclude_status is None or b.status != exclude_status)
            and (organization_id is None or b.organization_id == organization_id)
            and (oids is None or b.organization_id in oids)
            and (bids is None or b.id in bids)
            and (has_course is None or (b.course_id is not None) == has_course)
        ]
        from app.modules.identity.textsort import text_key

        fs_key = {
            "name": lambda b: (text_key(b.name), b.id.bytes),
            "created": lambda b: (b.created_at, b.id.bytes),
            "id": lambda b: b.id.bytes,
        }[order]
        return sorted(rows, key=fs_key)
    # Postgres: filters and ORDER BY in SQL (database collation for names, as before)
    q = select(Batch)
    if status is not None:
        q = q.where(Batch.status == status)
    if code is not None:
        q = q.where(Batch.code == code)
    if bids is not None:
        q = q.where(Batch.id.in_(bids))
    if organization_id is not None:
        q = q.where(Batch.organization_id == organization_id)
    if oids is not None:
        q = q.where(Batch.organization_id.in_(oids))
    if exclude_status is not None:
        q = q.where(Batch.status != exclude_status)
    if has_course is not None:
        q = q.where(Batch.course_id.is_not(None) if has_course else Batch.course_id.is_(None))
    order_cols = {
        "name": (Batch.name, Batch.id),
        "created": (Batch.created_at, Batch.id),
        "id": (Batch.id,),
    }[order]
    return list((await session.execute(q.order_by(*order_cols))).scalars().all())


async def batch_status_counts(session: AsyncSession) -> dict[str, int]:
    out: dict[str, int] = {}
    for b in await list_batches(session):
        out[b.status] = out.get(b.status, 0) + 1
    return out


async def add_batch(session: AsyncSession, batch: Batch) -> Batch:
    if _fs():
        from app.modules.orgs.store_specs import BATCHES

        return await _repo()._upsert(BATCHES, str(batch.id), batch)
    session.add(batch)
    await session.flush()
    return batch


async def get_batch_plan(session: AsyncSession, batch_id: uuid.UUID) -> BatchPlan | None:
    if _fs():
        return await _repo().batch_plan(batch_id)
    return await session.get(BatchPlan, batch_id)


# --------------------------------------------------------------------------- batch members


async def batch_members(
    session: AsyncSession,
    *,
    batch_ids: Iterable[uuid.UUID] | None = None,
    user_ids: Iterable[uuid.UUID] | None = None,
    organization_id: uuid.UUID | None = None,
    member_role: str | None = None,
    active_only: bool = True,
) -> list[BatchMember]:
    """Batch members matching every filter. ``active_only``: ``status = 'active' AND
    removed_at IS NULL``."""
    bids = set(batch_ids) if batch_ids is not None else None
    uids = set(user_ids) if user_ids is not None else None
    if _fs():
        repo = _repo()
        if uids is not None and len(uids) <= 30:
            rows: list[BatchMember] = []
            for u in uids:
                rows += await repo.batch_memberships_for(u)
        elif bids is not None and len(bids) <= 30:
            rows = []
            for b in bids:
                rows += await repo.batch_members(b)
        else:
            from app.modules.orgs.store_specs import MEMBERS

            rows = await repo._objs(BatchMember, MEMBERS)
    else:
        q = select(BatchMember)
        if bids is not None:
            q = q.where(BatchMember.batch_id.in_(bids))
        if uids is not None:
            q = q.where(BatchMember.user_id.in_(uids))
        rows = list((await session.execute(q)).scalars().all())
    out = [
        m
        for m in rows
        if (bids is None or m.batch_id in bids)
        and (uids is None or m.user_id in uids)
        and (organization_id is None or m.organization_id == organization_id)
        and (member_role is None or m.member_role == member_role)
        and (not active_only or (m.status == "active" and m.removed_at is None))
    ]
    return sorted(out, key=lambda m: (m.added_at, str(m.id)))


async def is_batch_member(
    session: AsyncSession, batch_id: uuid.UUID, user_id: uuid.UUID, *, member_role: str | None = None
) -> bool:
    return bool(
        await batch_members(session, batch_ids=[batch_id], user_ids=[user_id], member_role=member_role)
    )


async def get_batch_member(session: AsyncSession, member_id: uuid.UUID) -> BatchMember | None:
    if _fs():
        from app.modules.orgs.store_specs import MEMBERS

        return await _repo()._get_obj(BatchMember, MEMBERS, str(member_id))
    return await session.get(BatchMember, member_id)


async def add_batch_member(session: AsyncSession, m: BatchMember) -> BatchMember:
    """Insert an active member (Firestore: ``UniqueViolationError`` if the live row exists)."""
    if _fs():
        return await _repo().add_batch_member(m)
    session.add(m)
    await session.flush()
    return m


async def save_batch_member(session: AsyncSession, m: BatchMember) -> BatchMember:
    if _fs():
        from app.modules.orgs.store_specs import MEMBERS, MEMBERS_LIVE, member_live_key

        repo = _repo()
        saved = await repo._upsert(MEMBERS, str(m.id), m)
        key = member_live_key(m.batch_id, m.user_id, m.member_role)
        ref = await repo.store.get(MEMBERS_LIVE, key)
        if m.status != "active" and ref is not None and ref["member_id"] == str(m.id):
            await repo.store.run_transaction(lambda tx: tx.delete(MEMBERS_LIVE, key))
        elif m.status == "active" and ref is None:
            await repo.store.run_transaction(lambda tx: tx.put(MEMBERS_LIVE, key, {"member_id": str(m.id)}))
        return saved
    await session.flush()
    return m


# --------------------------------------------------------------------------- memberships


async def org_memberships(
    session: AsyncSession,
    *,
    user_ids: Iterable[uuid.UUID] | None = None,
    organization_id: uuid.UUID | None = None,
    member_type: str | None = None,
    active_only: bool = True,
) -> list[OrgMembership]:
    uids = set(user_ids) if user_ids is not None else None
    if _fs():
        repo = _repo()
        if uids is not None and len(uids) <= 30:
            rows: list[OrgMembership] = []
            for u in uids:
                rows += await repo.memberships_for(u)
        else:
            from app.modules.orgs.store_specs import MEMBERSHIPS

            rows = await repo._objs(OrgMembership, MEMBERSHIPS)
    else:
        q = select(OrgMembership)
        if uids is not None:
            q = q.where(OrgMembership.user_id.in_(uids))
        if organization_id is not None:
            q = q.where(OrgMembership.organization_id == organization_id)
        rows = list((await session.execute(q)).scalars().all())
    out = [
        m
        for m in rows
        if (uids is None or m.user_id in uids)
        and (organization_id is None or m.organization_id == organization_id)
        and (member_type is None or m.member_type == member_type)
        and (not active_only or m.status == "active")
    ]
    return sorted(out, key=lambda m: (str(m.organization_id), str(m.user_id)))


async def active_org_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Organizations of the user's active memberships, by id."""
    return sorted({m.organization_id for m in await org_memberships(session, user_ids=[user_id])}, key=str)


async def end_memberships(session: AsyncSession, user_id: uuid.UUID, *, status: str = "left") -> int:
    """End every active org and batch membership of a user (seeds / account deletion)."""
    from app.modules.identity import clock

    now = clock.now()
    n = 0
    for m in await batch_members(session, user_ids=[user_id]):
        m.status, m.removed_at = "removed", now
        await save_batch_member(session, m)
        n += 1
    for om in await org_memberships(session, user_ids=[user_id]):
        if _fs():
            from app.modules.orgs.store_specs import MEMBERSHIPS

            await _repo().store.update(MEMBERSHIPS, str(om.id), {"status": status, "left_at": now})
        else:
            om.status, om.left_at = status, now
        n += 1
    if not _fs():
        await session.flush()
    return n


async def attendance_certificate_block(
    session: AsyncSession, batch_id: uuid.UUID, user_id: uuid.UUID
) -> str | None:
    """Why ``user_id`` may not get a certificate yet because of attendance in ``batch_id``
    (``None`` = no block). Either store (``orgs.service.attendance_certificate_block``)."""
    from app.modules.orgs.service import attendance_certificate_block as _block

    return await _block(session, batch_id, user_id)
