"""Store-neutral data access of the orgs routes (``router.py``, ``classes.py``) and the website
plan importer (``TD_STORE_ORGS`` = postgres | firestore).

Every function has two branches: the **postgres** branch is the SQL the routes ran before
(moved here unchanged, on the caller's RLS session); the **firestore** branch reads and writes
through ``OrgsRepo`` and never touches ``session`` (it may be ``NO_POSTGRES``). Uniqueness that
Postgres reported as ``IntegrityError`` is reported the same way to the routes: ``Duplicate``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.firestore.backend import uses_firestore
from app.core.firestore.errors import UniqueViolationError
from app.core.ids import uuid7
from app.modules.identity import clock, fs_uow
from app.modules.identity.textsort import text_key
from app.modules.orgs.models import Batch, BatchMember, BatchPlan, ClassAttendance, ClassSession


class Duplicate(Exception):
    """A uniqueness constraint was hit (batch code, class date, live batch member)."""


def fs() -> bool:
    return uses_firestore("orgs")


def _repo() -> Any:
    from app.modules.orgs.repo_firestore import system_repo

    return system_repo()


def _clean(*objs: Any) -> None:
    """Objects just written explicitly: the unit of work must not write them again."""
    uow = fs_uow.current()
    if uow is not None:
        for o in objs:
            uow.clean(o)


async def _names(session: Any, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    from app.modules.identity.public import get_profiles

    profs = await get_profiles(session, user_ids)
    return {u: (profs[u].full_name if u in profs else None) for u in user_ids}


# --------------------------------------------------------------------------- batches


async def get_batch(session: Any, batch_id: uuid.UUID) -> Batch | None:
    if fs():
        return await _repo().get_batch(batch_id)
    return await session.get(Batch, batch_id)


async def list_batches(session: Any, *, status: str | None, ids: list[uuid.UUID] | None) -> list[Batch]:
    """Batches by ``code`` (``GET /batches``)."""
    if fs():
        rows = [
            b
            for b in await _repo().list_batches()
            if (status is None or b.status == status) and (ids is None or b.id in set(ids))
        ]
        return sorted(rows, key=lambda b: text_key(b.code))
    q = select(Batch).order_by(Batch.code)
    if status is not None:
        q = q.where(Batch.status == status)
    if ids is not None:
        q = q.where(Batch.id.in_(ids))
    return list((await session.execute(q)).scalars())


async def code_taken(session: Any, org_id: uuid.UUID, code: str) -> bool:
    if fs():
        return await _repo().batch_by_code(org_id, code) is not None
    return (
        await session.execute(select(Batch.id).where(Batch.organization_id == org_id, Batch.code == code))
    ).scalar_one_or_none() is not None


async def insert_batch(session: Any, b: Batch) -> Batch:
    """Insert; ``Duplicate`` on ``uq_batches_org_code``."""
    if fs():
        try:
            saved = await _repo().insert_batch(b)
        except UniqueViolationError as e:
            raise Duplicate from e
        _clean(saved)
        return saved
    try:
        async with session.begin_nested():
            session.add(b)
            await session.flush()
    except IntegrityError as e:
        raise Duplicate from e
    return b


async def save_batch(session: Any, b: Batch) -> None:
    if fs():
        await _repo().save_batch(b)
        _clean(b)
        return
    await session.flush()


# --------------------------------------------------------------------------- members


async def active_members_named(session: Any, batch_id: uuid.UUID) -> list[tuple[BatchMember, str | None]]:
    """Active members (any role) with their full name, by ``added_at``."""
    if fs():
        rows = sorted(
            (m for m in await _repo().batch_members(batch_id) if m.status == "active"),
            key=lambda m: (m.added_at, str(m.id)),
        )
        names = await _names(session, [m.user_id for m in rows])
        return [(m, names.get(m.user_id)) for m in rows]
    rows2 = list(
        (
            await session.execute(
                select(BatchMember)
                .where(BatchMember.batch_id == batch_id, BatchMember.status == "active")
                .order_by(BatchMember.added_at)
            )
        ).scalars()
    )
    names2 = await names_of(session, [m.user_id for m in rows2])  # identity.public
    return [(m, names2.get(m.user_id)) for m in rows2]


async def students_named(session: Any, batch_id: uuid.UUID) -> list[tuple[uuid.UUID, str | None]]:
    """Active student members ``(user_id, full_name)`` by name (nulls last), then id. The name
    ordering is the identity module's (``identity.public.users_ordered_by_full_name``): in SQL on
    Postgres (database collation, as before), the shared collation key on Firestore."""
    from app.modules.identity.public import users_ordered_by_full_name

    if fs():
        ids = [
            m.user_id
            for m in await _repo().batch_members(batch_id)
            if m.status == "active" and m.member_role == "student"
        ]
    else:
        ids = list(
            (
                await session.execute(
                    select(BatchMember.user_id).where(
                        BatchMember.batch_id == batch_id,
                        BatchMember.status == "active",
                        BatchMember.member_role == "student",
                    )
                )
            ).scalars()
        )
    return await users_ordered_by_full_name(session, ids)


async def lookup_accounts(
    session: Any, user_ids: list[uuid.UUID], emails: list[str]
) -> list[tuple[uuid.UUID, str | None]]:
    """``(id, email)`` of usable accounts (not deactivated/deleted) among the ids / e-mails."""
    from app.modules.identity.pgctx import sys_scope
    from app.modules.identity.public import get_users, users_by_emails

    async with sys_scope(session, "orgs.batch_member_lookup"):
        found = list((await get_users(session, user_ids)).values())
        found += list((await users_by_emails(session, emails)).values())
    seen: set[uuid.UUID] = set()
    out: list[tuple[uuid.UUID, str | None]] = []
    for u in found:
        if u.id in seen or u.status in ("deactivated", "deleted") or u.deleted_at is not None:
            continue
        seen.add(u.id)
        out.append((u.id, u.email))
    return out


async def active_rows(
    session: Any, batch_id: uuid.UUID, user_id: uuid.UUID, member_role: str | None = None
) -> list[BatchMember]:
    """Active member rows of a user in a batch (optionally of one role)."""
    if fs():
        return [
            m
            for m in await _repo().batch_members(batch_id)
            if m.user_id == user_id
            and m.status == "active"
            and (member_role is None or m.member_role == member_role)
        ]
    q = select(BatchMember).where(
        BatchMember.batch_id == batch_id, BatchMember.user_id == user_id, BatchMember.status == "active"
    )
    if member_role is not None:
        q = q.where(BatchMember.member_role == member_role)
    return list((await session.execute(q)).scalars())


async def end_member_rows(session: Any, rows: list[BatchMember], now: Any) -> None:
    """Set rows ``removed`` (Firestore: written now, freeing their ``ux_bm_live`` slot)."""
    for m in rows:
        m.status = "removed"
        m.removed_at = now
    if fs():
        for m in rows:
            await _repo().save_batch_member(m)
            _clean(m)
        return
    await session.flush()


async def add_members(session: Any, members: list[BatchMember]) -> None:
    """Insert active member rows; ``Duplicate`` on ``ux_bm_live`` (a concurrent add)."""
    if fs():
        try:
            for m in members:
                _clean(await _repo().add_batch_member(m))
        except UniqueViolationError as e:
            raise Duplicate from e
        return
    for m in members:
        session.add(m)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as e:
        raise Duplicate from e


# --------------------------------------------------------------------------- plan


async def plan_row(session: Any, batch_id: uuid.UUID) -> BatchPlan | None:
    if fs():
        return await _repo().batch_plan(batch_id)
    return await session.get(BatchPlan, batch_id)


async def save_plan(session: Any, b: Batch, row: BatchPlan, *, new: bool, batch_changed: bool) -> BatchPlan:
    """Persist the plan row (and the batch fields the plan edit changed); returns the stored row."""
    if fs():
        if batch_changed:
            await _repo().save_batch(b)
            _clean(b)
        saved = await _repo().save_plan(row)
        _clean(row, saved)
        return saved
    if new:
        session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def plan_by_source_ref(session: Any, source_ref: str) -> BatchPlan | None:
    if fs():
        return await _repo().plan_by_source_ref(source_ref)
    return (
        await session.execute(select(BatchPlan).where(BatchPlan.source_ref == source_ref))
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- classes


async def get_class(session: Any, class_id: uuid.UUID) -> ClassSession | None:
    if fs():
        return await _repo().get_class(class_id)
    return await session.get(ClassSession, class_id)


async def classes(
    session: Any,
    batch_id: uuid.UUID,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    before: date | None = None,
    limit: int | None = None,
    newest_first: bool = False,
) -> list[ClassSession]:
    """Classes of a batch by date (``date_from``/``date_to`` inclusive, ``before`` exclusive)."""
    if fs():
        rows = [
            c
            for c in await _repo().classes_of(batch_id)
            if (date_from is None or c.session_date >= date_from)
            and (date_to is None or c.session_date <= date_to)
            and (before is None or c.session_date < before)
        ]
        rows.sort(key=lambda c: c.session_date, reverse=newest_first)
        return rows[:limit] if limit is not None else rows
    q = select(ClassSession).where(ClassSession.batch_id == batch_id)
    if date_from:
        q = q.where(ClassSession.session_date >= date_from)
    if date_to:
        q = q.where(ClassSession.session_date <= date_to)
    if before:
        q = q.where(ClassSession.session_date < before)
    q = q.order_by(ClassSession.session_date.desc() if newest_first else ClassSession.session_date)
    if limit is not None:
        q = q.limit(limit)
    return list((await session.execute(q)).scalars())


async def class_dates(session: Any, batch_id: uuid.UUID) -> set[date]:
    if fs():
        return {c.session_date for c in await _repo().classes_of(batch_id)}
    return set(
        (
            await session.execute(select(ClassSession.session_date).where(ClassSession.batch_id == batch_id))
        ).scalars()
    )


async def insert_classes(session: Any, rows: list[ClassSession]) -> None:
    """Insert classes; ``Duplicate`` on ``uq_class_sessions_batch_date``. Firestore inserts one
    by one (rows before a duplicate stay; Postgres rolls the whole set back)."""
    if fs():
        try:
            for c in rows:
                _clean(await _repo().insert_class(c))
        except UniqueViolationError as e:
            raise Duplicate from e
        return
    try:
        async with session.begin_nested():
            for c in rows:
                session.add(c)
            await session.flush()
    except IntegrityError as e:
        raise Duplicate from e


async def save_class(session: Any, c: ClassSession) -> None:
    """``Duplicate`` when a date change hits another class of the batch."""
    if fs():
        try:
            await _repo().save_class(c)
        except UniqueViolationError as e:
            raise Duplicate from e
        _clean(c)
        return
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as e:
        raise Duplicate from e


async def delete_class(session: Any, c: ClassSession) -> None:
    if fs():
        await _repo().delete_class(c.id)
        fs_uow.discard(c)
        return
    await session.delete(c)
    await session.flush()


# --------------------------------------------------------------------------- attendance


async def counts(session: Any, class_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """``{class_id: {status: n}}``."""
    if not class_ids:
        return {}
    if fs():
        out: dict[uuid.UUID, dict[str, int]] = {}
        for cid in dict.fromkeys(class_ids):
            for a in await _repo().attendance_of(session_id=cid):
                d = out.setdefault(cid, {})
                d[a.status] = d.get(a.status, 0) + 1
        return out
    rows = (
        await session.execute(
            select(ClassAttendance.session_id, ClassAttendance.status, func.count())
            .where(ClassAttendance.session_id.in_(class_ids))
            .group_by(ClassAttendance.session_id, ClassAttendance.status)
        )
    ).all()
    out2: dict[uuid.UUID, dict[str, int]] = {}
    for sid, st, n in rows:
        out2.setdefault(sid, {})[st] = int(n)
    return out2


async def marks_of_class(session: Any, class_id: uuid.UUID) -> list[ClassAttendance]:
    if fs():
        return await _repo().attendance_of(session_id=class_id)
    return list(
        (
            await session.execute(select(ClassAttendance).where(ClassAttendance.session_id == class_id))
        ).scalars()
    )


async def names_of(session: Any, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    """Full names of users that have a profile (``user_profiles``), via identity.public."""
    from app.modules.identity.public import get_profiles

    return {u: p.full_name for u, p in (await get_profiles(session, user_ids)).items()}


async def write_marks(
    session: Any,
    c: ClassSession,
    b: Batch,
    *,
    clear: list[uuid.UUID],
    upsert: Sequence[tuple[uuid.UUID, str]],
    marked_by: uuid.UUID,
) -> None:
    """Clear marks and upsert P/L/A marks (``marked_at`` = now on every set)."""
    if fs():
        repo = _repo()
        for u in clear:
            await repo.delete_attendance(c.id, u)
        now = clock.now()
        for u, st in upsert:
            cur = await repo.get_attendance(c.id, u)
            a = ClassAttendance(
                id=cur.id if cur is not None else uuid7(),
                session_id=c.id,
                batch_id=b.id,
                organization_id=b.organization_id,
                user_id=u,
                status=st,
                marked_by=marked_by,
                marked_at=now,
            )
            _clean(await repo.save_attendance(a))
        return
    if clear:
        await session.execute(
            delete(ClassAttendance).where(
                ClassAttendance.session_id == c.id, ClassAttendance.user_id.in_(clear)
            )
        )
    if upsert:
        stmt = pg_insert(ClassAttendance).values(
            [
                {
                    "id": uuid7(),
                    "session_id": c.id,
                    "batch_id": b.id,
                    "organization_id": b.organization_id,
                    "user_id": u,
                    "status": st,
                    "marked_by": marked_by,
                }
                for u, st in upsert
            ]
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_class_attendance_session_user",
            set_={
                "status": stmt.excluded.status,
                "marked_by": stmt.excluded.marked_by,
                "marked_at": func.now(),
            },
        )
        await session.execute(stmt)
    await session.flush()


async def batch_marks(
    session: Any, batch_id: uuid.UUID, user_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, list[str]]:
    """``{user_id: [status, ...]}`` over the batch's non-cancelled classes."""
    if fs():
        repo = _repo()
        live = {c.id for c in await repo.classes_of(batch_id) if not c.cancelled}
        if user_ids is not None and len(user_ids) == 1:
            rows = await repo.attendance_of(batch_id=batch_id, user_id=user_ids[0])
        else:
            rows = await repo.attendance_of(batch_id=batch_id)
        want = set(user_ids) if user_ids is not None else None
        out: dict[uuid.UUID, list[str]] = {}
        for a in rows:
            if a.session_id in live and (want is None or a.user_id in want):
                out.setdefault(a.user_id, []).append(a.status)
        return out
    q = (
        select(ClassAttendance.user_id, ClassAttendance.status)
        .join(ClassSession, ClassSession.id == ClassAttendance.session_id)
        .where(ClassAttendance.batch_id == batch_id, ClassSession.cancelled.is_(False))
    )
    if user_ids is not None:
        q = q.where(ClassAttendance.user_id.in_(user_ids))
    out2: dict[uuid.UUID, list[str]] = {}
    for u, st in (await session.execute(q)).all():
        out2.setdefault(u, []).append(st)
    return out2


async def classes_marked(session: Any, batch_id: uuid.UUID) -> int:
    """Distinct non-cancelled classes of the batch that have at least one mark."""
    if fs():
        repo = _repo()
        live = {c.id for c in await repo.classes_of(batch_id) if not c.cancelled}
        return len(
            {a.session_id for a in await repo.attendance_of(batch_id=batch_id) if a.session_id in live}
        )
    held = (
        await session.execute(
            select(func.count(func.distinct(ClassAttendance.session_id)))
            .join(ClassSession, ClassSession.id == ClassAttendance.session_id)
            .where(ClassAttendance.batch_id == batch_id, ClassSession.cancelled.is_(False))
        )
    ).scalar_one()
    return int(held or 0)


async def classes_with_mark(
    session: Any,
    batch_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    before: date | None = None,
    newest_first: bool = False,
    limit: int | None = None,
) -> list[tuple[ClassSession, str | None]]:
    """Classes of the batch (by date) with the user's own mark (``None`` when unmarked)."""
    if fs():
        cls = await classes(session, batch_id, before=before, newest_first=newest_first, limit=limit)
        marks = {
            a.session_id: a.status for a in await _repo().attendance_of(batch_id=batch_id, user_id=user_id)
        }
        return [(c, marks.get(c.id)) for c in cls]
    q = (
        select(ClassSession, ClassAttendance.status)
        .outerjoin(
            ClassAttendance,
            and_(ClassAttendance.session_id == ClassSession.id, ClassAttendance.user_id == user_id),
        )
        .where(ClassSession.batch_id == batch_id)
    )
    if before is not None:
        q = q.where(ClassSession.session_date < before)
    q = q.order_by(ClassSession.session_date.desc() if newest_first else ClassSession.session_date)
    if limit is not None:
        q = q.limit(limit)
    return [(c, st) for c, st in (await session.execute(q)).all()]


async def my_batches(session: Any, user_id: uuid.UUID) -> list[Batch]:
    """Non-archived batches where the user is an active student, newest start first (nulls
    last), then name."""
    if fs():
        repo = _repo()
        ids = {
            m.batch_id
            for m in await repo.batch_memberships_for(user_id)
            if m.status == "active" and m.member_role == "student"
        }
        rows = [b for b in (await repo.get_batches(list(ids))).values() if b.status != "archived"]
        rows.sort(key=lambda b: text_key(b.name))
        rows.sort(key=lambda b: b.starts_on.toordinal() if b.starts_on else 0, reverse=True)
        return rows
    return list(
        (
            await session.execute(
                select(Batch)
                .join(BatchMember, BatchMember.batch_id == Batch.id)
                .where(
                    BatchMember.user_id == user_id,
                    BatchMember.status == "active",
                    BatchMember.member_role == "student",
                    Batch.status != "archived",
                )
                .distinct()
                .order_by(Batch.starts_on.desc().nulls_last(), Batch.name)
            )
        ).scalars()
    )
