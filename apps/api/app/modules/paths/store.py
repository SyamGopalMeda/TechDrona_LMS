"""Persistence of the paths tables, per ``TD_STORE_PATHS``.

Every read and write ``service.py`` does on ``learning_paths``, ``learning_path_steps``,
``learning_path_versions``, ``learning_path_version_steps``, ``path_allocations``,
``path_articles`` and ``path_step_progress`` is one function here: the Postgres branch is the
SQL the service ran inline (unchanged, on the caller's session and RLS context), the Firestore
branch calls ``repo_firestore``. Objects are ORM instances on both stores; a changed object is
written back with ``save_*`` (Postgres: ``flush`` of the tracked row, as before).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.backend import uses_firestore
from app.core.time import utcnow
from app.modules.paths import adapters
from app.modules.paths.models import (
    LearningPath,
    LearningPathStep,
    LearningPathVersion,
    LearningPathVersionStep,
    PathAllocation,
    PathArticle,
    PathStepProgress,
)


def fs() -> bool:
    return uses_firestore("paths")


def _r() -> Any:
    from app.modules.paths.repo_firestore import repo

    return repo()


# --------------------------------------------------------------------------- paths


async def get_path(session: AsyncSession, path_id: uuid.UUID) -> LearningPath | None:
    if fs():
        return await _r().get_path(path_id)
    return (
        await session.execute(select(LearningPath).where(LearningPath.id == path_id))
    ).scalar_one_or_none()


async def list_paths(session: AsyncSession, status: str | None, q: str | None) -> list[LearningPath]:
    if fs():
        return list(await _r().list_paths(status, q, 200))
    stmt = select(LearningPath)
    stmt = (
        stmt.where(LearningPath.status == status) if status else stmt.where(LearningPath.status != "archived")
    )
    if q:
        stmt = stmt.where(LearningPath.title.ilike(adapters.like_pattern(q)))
    return list((await session.execute(stmt.order_by(LearningPath.updated_at.desc()).limit(200))).scalars())


async def insert_path(session: AsyncSession, p: LearningPath) -> None:
    if fs():
        await _r().insert_path(p)
        return
    session.add(p)
    await session.flush()


async def save_path(session: AsyncSession, p: LearningPath) -> None:
    if fs():
        await _r().save_path(p)
        return
    await session.flush()


async def draft_rows(session: AsyncSession, path_id: uuid.UUID) -> list[LearningPathStep]:
    if fs():
        return list(await _r().draft_rows(path_id))
    return list(
        (await session.execute(select(LearningPathStep).where(LearningPathStep.path_id == path_id))).scalars()
    )


async def replace_draft(session: AsyncSession, p: LearningPath, rows: list[LearningPathStep]) -> None:
    """Replace the draft step tree with ``rows`` and save ``p`` (one document on Firestore)."""
    if fs():
        await _r().save_path(p, rows)
        return
    await session.execute(delete(LearningPathStep).where(LearningPathStep.path_id == p.id))
    for r in rows:
        session.add(r)
    await session.flush()


async def draft_steps_using_article(session: AsyncSession, article_id: uuid.UUID) -> int:
    if fs():
        return int(await _r().draft_steps_using_article(article_id))
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(LearningPathStep)
                .where(LearningPathStep.article_id == article_id)
            )
        ).scalar_one()
    )


async def publish(
    session: AsyncSession, p: LearningPath, v: LearningPathVersion, rows: list[LearningPathVersionStep]
) -> None:
    """Insert the version and its steps and save the path pointers (``p`` already updated)."""
    if fs():
        await _r().publish(p, v, rows)
        return
    session.add(v)
    await session.flush()
    for r in rows:
        session.add(r)
    await session.flush()


# --------------------------------------------------------------------------- versions


async def get_version(session: AsyncSession, version_id: uuid.UUID) -> LearningPathVersion | None:
    if fs():
        return await _r().get_version(version_id)
    return (
        await session.execute(select(LearningPathVersion).where(LearningPathVersion.id == version_id))
    ).scalar_one_or_none()


async def version_rows(session: AsyncSession, version_id: uuid.UUID) -> list[LearningPathVersionStep]:
    if fs():
        return list(await _r().version_rows(version_id))
    return list(
        (
            await session.execute(
                select(LearningPathVersionStep).where(LearningPathVersionStep.path_version_id == version_id)
            )
        ).scalars()
    )


# --------------------------------------------------------------------------- allocations


async def allocations_for_path(session: AsyncSession, path_id: uuid.UUID) -> list[PathAllocation]:
    if fs():
        return list(await _r().allocations_for_path(path_id))
    return list(
        (
            await session.execute(
                select(PathAllocation)
                .where(PathAllocation.path_id == path_id)
                .order_by(PathAllocation.created_at.desc())
            )
        ).scalars()
    )


async def get_allocation(session: AsyncSession, allocation_id: uuid.UUID) -> PathAllocation | None:
    if fs():
        return await _r().get_allocation(allocation_id)
    return (
        await session.execute(select(PathAllocation).where(PathAllocation.id == allocation_id))
    ).scalar_one_or_none()


async def insert_allocation(session: AsyncSession, a: PathAllocation) -> None:
    if fs():
        await _r().insert_allocation(a)
        return
    session.add(a)
    await session.flush()


async def save_allocation(session: AsyncSession, a: PathAllocation) -> None:
    if fs():
        await _r().save_allocation(a)
        return
    await session.flush()


async def revoke_active_for_path(session: AsyncSession, path_id: uuid.UUID) -> None:
    if fs():
        await _r().revoke_active_for_path(path_id, utcnow())
        return
    await session.execute(
        update(PathAllocation)
        .where(PathAllocation.path_id == path_id, PathAllocation.status == "active")
        .values(status="revoked", revoked_at=utcnow())
    )


async def user_allocations(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    allocation_id: uuid.UUID | None = None,
    linking: tuple[str, uuid.UUID] | None = None,
    limit: int | None = None,
) -> list[PathAllocation]:
    """Active allocations targeting ``user_id`` (chosen learner, or active student of the batch),
    newest first. ``allocation_id``: that one only. ``linking=(field, id)``: only allocations whose
    pinned version has a step with ``field`` = ``id`` (assignment_id / test_id / article_id)."""
    if fs():
        r = _r()
        versions = await r.versions_linking(*linking) if linking else None
        batches = await adapters.student_batch_ids(session, user_id)
        got = await r.allocations_for_user(
            user_id, batches, allocation_id=allocation_id, version_ids=versions
        )
        return got[:limit] if limit else got
    my_batches = await adapters.student_batch_ids(session, user_id)
    stmt = select(PathAllocation).where(
        PathAllocation.status == "active",
        or_(PathAllocation.user_ids.contains([user_id]), PathAllocation.batch_id.in_(my_batches)),
    )
    if allocation_id is not None:
        stmt = stmt.where(PathAllocation.id == allocation_id)
    if linking is not None:
        col = getattr(LearningPathVersionStep, linking[0])
        stmt = stmt.where(
            PathAllocation.path_version_id.in_(
                select(LearningPathVersionStep.path_version_id).where(col == linking[1])
            )
        )
    else:
        stmt = stmt.order_by(PathAllocation.created_at.desc())
    if limit:
        stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars())


# --------------------------------------------------------------------------- progress


async def allocation_progress_rows(session: AsyncSession, allocation_id: uuid.UUID) -> list[PathStepProgress]:
    """Every learner's progress on one allocation (system context ``paths.progress``)."""
    if fs():
        return list(await _r().progress_for_allocation(allocation_id))
    from app.core.db import system_context

    async with system_context(session, "paths.progress"):
        return list(
            (
                await session.execute(
                    select(PathStepProgress).where(PathStepProgress.allocation_id == allocation_id)
                )
            ).scalars()
        )


async def user_progress(
    session: AsyncSession, allocation_id: uuid.UUID, user_id: uuid.UUID
) -> list[PathStepProgress]:
    if fs():
        return list(await _r().progress(user_id, allocation_id))
    return list(
        (
            await session.execute(
                select(PathStepProgress).where(
                    PathStepProgress.allocation_id == allocation_id, PathStepProgress.user_id == user_id
                )
            )
        ).scalars()
    )


async def open_progress(session: AsyncSession, values: dict[str, Any]) -> None:
    """Insert a progress row unless one exists (``ON CONFLICT DO NOTHING``)."""
    if fs():
        await _r().insert_progress(values["user_id"], PathStepProgress(**values), if_absent=True)
        return
    await session.execute(
        pg_insert(PathStepProgress)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["allocation_id", "user_id", "step_key"])
    )


async def add_progress(session: AsyncSession, pr: PathStepProgress) -> None:
    """Insert a new progress row (flushed by the caller's ``flush_progress`` on Postgres)."""
    if fs():
        await _r().insert_progress(pr.user_id, pr, if_absent=False)
        return
    session.add(pr)


async def save_progress(session: AsyncSession, pr: PathStepProgress) -> None:
    if fs():
        await _r().save_progress(pr.user_id, pr)


async def flush(session: AsyncSession) -> None:
    """Postgres: flush tracked changes; Firestore: writes already happened per object."""
    if not fs():
        await session.flush()


# --------------------------------------------------------------------------- articles


async def get_article(session: AsyncSession, article_id: uuid.UUID) -> PathArticle | None:
    if fs():
        return await _r().get_article(article_id)
    return (
        await session.execute(
            select(PathArticle).where(PathArticle.id == article_id, PathArticle.deleted_at.is_(None))
        )
    ).scalar_one_or_none()


async def article_in_org(session: AsyncSession, article_id: uuid.UUID, org_id: uuid.UUID) -> bool:
    if fs():
        a = await _r().get_article(article_id)
        return a is not None and a.organization_id == org_id
    return (
        await session.execute(
            select(PathArticle.id).where(
                PathArticle.id == article_id,
                PathArticle.organization_id == org_id,
                PathArticle.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none() is not None


async def list_articles(session: AsyncSession, q: str | None) -> list[PathArticle]:
    if fs():
        return list(await _r().list_articles(q, 200))
    stmt = select(PathArticle).where(PathArticle.deleted_at.is_(None))
    if q:
        stmt = stmt.where(PathArticle.title.ilike(adapters.like_pattern(q)))
    return list((await session.execute(stmt.order_by(PathArticle.updated_at.desc()).limit(200))).scalars())


async def article_options(session: AsyncSession, org_id: uuid.UUID, q: str | None) -> list[tuple[Any, ...]]:
    if fs():
        return [(a.id, a.title, a.status) for a in await _r().list_articles(q, 25, org_id)]
    rows = await session.execute(
        select(PathArticle.id, PathArticle.title, PathArticle.status)
        .where(
            PathArticle.organization_id == org_id,
            PathArticle.deleted_at.is_(None),
            PathArticle.title.ilike(adapters.like_pattern(q)),
        )
        .order_by(PathArticle.updated_at.desc())
        .limit(25)
    )
    return [tuple(r) for r in rows.all()]


async def insert_article(session: AsyncSession, a: PathArticle) -> None:
    if fs():
        await _r().insert_article(a)
        return
    session.add(a)
    await session.flush()


async def save_article(session: AsyncSession, a: PathArticle) -> None:
    if fs():
        await _r().save_article(a)
        return
    await session.flush()


def now() -> datetime:
    return utcnow()
