"""Public catalog API for other modules (Firebase P2b de-join).

No code outside ``app.modules.catalog`` (seeds excepted) reads or writes the catalog tables
(``courses``, ``course_versions``, ``course_modules``, ``lessons``, ``lesson_assets``,
``lesson_topics``, ``resources``) directly; it calls these functions instead. Each one takes the
caller's session and runs on the caller's RLS context (unless it says it uses a named system
context), so on Postgres the behaviour is the same as the SQL the callers used to run inline.

With ``TD_STORE_CATALOG=firestore`` every function reads/writes Firestore through
``repo_firestore`` (transient ORM instances; the caller's TN visibility is read from the
session's RLS context, system lookups stay system lookups).

Return values are ORM instances or plain values. Callers only read attributes: they never rely
on session identity, lazy loading or a later ``flush`` persisting a change to a catalog object
(writes go through ``create_asset`` / ``update_asset`` / ``update_lesson``).

The ORM classes are re-exported so callers import catalog types from one place.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context, tenant_context
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.principal import Principal
from app.modules.catalog.models import (
    Course,
    CourseModule,
    CourseVersion,
    Lesson,
    LessonAsset,
    Resource,
)

__all__ = [
    "Course",
    "CourseModule",
    "CourseVersion",
    "Lesson",
    "LessonAsset",
    "Resource",
    "asset_lesson_id_system",
    "asset_with_parents",
    "assets_by_s3_key",
    "course_ids_for_lessons",
    "course_org_system",
    "course_status_counts",
    "create_asset",
    "current_outline_lessons",
    "find_lessons",
    "get_assets",
    "get_courses",
    "get_lessons",
    "get_resources",
    "get_versions",
    "lesson_assets",
    "lesson_resources",
    "lesson_with_parents",
    "lock_pending_scan_assets",
    "search_published_lessons",
    "update_asset",
    "update_lesson",
]


async def _system_first(session: AsyncSession, principal: Principal, stmt: Any) -> Any:
    """Same as ``service.system_lookup``: one lookup in the ``catalog.scope_lookup`` system
    context, then the principal's RLS context is restored."""
    await system_context(session, "catalog.scope_lookup")
    try:
        return (await session.execute(stmt)).first()
    finally:
        await tenant_context(session, principal)


async def _reader(session: AsyncSession) -> Any:
    from app.modules.catalog.repo_firestore import reader

    return await reader(session)


async def _writer(session: AsyncSession) -> Any:
    """Media writes run in the caller's (principal or system) context: the TN WITH CHECK
    predicate comes from the session; the store is the ``catalog.write`` job."""
    from app.modules.catalog.repo_firestore import writer

    return await writer(session, None)


# --------------------------------------------------------------------------- batch loaders


async def get_courses(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Course]:
    """Courses by id, soft-deleted ones included (learning, media, analytics, mentoring)."""
    want = list(set(ids))
    if not want:
        return {}
    if uses_firestore("catalog"):
        return await (await _reader(session)).courses(want)
    rows = (await session.execute(select(Course).where(Course.id.in_(want)))).scalars()
    return {c.id: c for c in rows}


async def get_versions(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, CourseVersion]:
    """Course versions by id (learning enrolments and certificates)."""
    want = list(set(ids))
    if not want:
        return {}
    if uses_firestore("catalog"):
        return await (await _reader(session)).versions(want)
    rows = (await session.execute(select(CourseVersion).where(CourseVersion.id.in_(want)))).scalars()
    return {v.id: v for v in rows}


async def get_lessons(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Lesson]:
    """Lessons by id (learning, media, paths link check, analytics lesson meta)."""
    want = list(set(ids))
    if not want:
        return {}
    if uses_firestore("catalog"):
        return await (await _reader(session)).lessons(want)
    rows = (await session.execute(select(Lesson).where(Lesson.id.in_(want)))).scalars()
    return {le.id: le for le in rows}


async def get_assets(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, LessonAsset]:
    """Lesson assets by id (media, analytics durations / asset owner, learning coverage)."""
    want = list(set(ids))
    if not want:
        return {}
    if uses_firestore("catalog"):
        return await (await _reader(session)).assets(want)
    rows = (await session.execute(select(LessonAsset).where(LessonAsset.id.in_(want)))).scalars()
    return {a.id: a for a in rows}


async def get_resources(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Resource]:
    """Resources by id (media downloads, entitlements resource parents)."""
    want = list(set(ids))
    if not want:
        return {}
    if uses_firestore("catalog"):
        return await (await _reader(session)).resources(want)
    rows = (await session.execute(select(Resource).where(Resource.id.in_(want)))).scalars()
    return {r.id: r for r in rows}


# --------------------------------------------------------------------------- lesson queries


async def find_lessons(
    session: AsyncSession,
    *,
    lesson_key: uuid.UUID | None = None,
    version_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None,
    required_only: bool = False,
) -> list[Lesson]:
    """Lessons matching all given filters, unordered (learning completion, pinned lesson,
    required keys, assignment lessons; wiring video coverage)."""
    if lesson_key is None and version_id is None and assignment_id is None and not required_only:
        raise ValueError("find_lessons needs at least one filter")
    if uses_firestore("catalog"):
        return await (await _reader(session)).find_lessons(
            lesson_key=lesson_key,
            version_id=version_id,
            assignment_id=assignment_id,
            required_only=required_only,
        )
    conds: list[Any] = []
    if lesson_key is not None:
        conds.append(Lesson.lesson_key == lesson_key)
    if version_id is not None:
        conds.append(Lesson.course_version_id == version_id)
    if assignment_id is not None:
        conds.append(Lesson.assignment_id == assignment_id)
    if required_only:
        conds.append(Lesson.is_required.is_(True))
    if not conds:
        raise ValueError("find_lessons needs at least one filter")
    return list((await session.execute(select(Lesson).where(*conds))).scalars())


async def lesson_with_parents(
    session: AsyncSession, lesson_id: uuid.UUID, *, version_statuses: Sequence[str]
) -> tuple[Lesson, CourseVersion, Course] | None:
    """A lesson with its version and (not deleted) course when the version status is one of
    ``version_statuses`` (learning ``student_lesson``)."""
    if uses_firestore("catalog"):
        return await (await _reader(session)).lesson_with_parents(lesson_id, version_statuses)
    row = (
        await session.execute(
            select(Lesson, CourseVersion, Course)
            .join(CourseVersion, CourseVersion.id == Lesson.course_version_id)
            .join(Course, Course.id == CourseVersion.course_id)
            .where(
                Lesson.id == lesson_id,
                CourseVersion.status.in_(version_statuses),
                Course.deleted_at.is_(None),
            )
        )
    ).first()
    return None if row is None else (row[0], row[1], row[2])


_LESSON_COURSES = (
    "SELECT DISTINCT cv.course_id FROM lessons l JOIN course_versions cv ON cv.id = l.course_version_id "
)
_COURSES_BY_LESSON_ID = _LESSON_COURSES + "WHERE l.id = :i"
_COURSES_BY_LESSON_ID_OR_KEY = _LESSON_COURSES + "WHERE l.id = :i OR l.lesson_key = :i"
_COURSES_BY_PROBLEM = _LESSON_COURSES + "WHERE l.coding_problem_id = :i"
_COURSES_BY_TEST = _LESSON_COURSES + "WHERE l.test_id = :i"


async def course_ids_for_lessons(
    session: AsyncSession,
    *,
    lesson_id: uuid.UUID | None = None,
    match_lesson_key: bool = False,
    coding_problem_id: uuid.UUID | None = None,
    test_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """DISTINCT course ids of the lessons with that id (or also that ``lesson_key`` when
    ``match_lesson_key``), embedding that coding problem, or embedding that test. Exactly one
    selector (wiring access parents; analytics lesson -> course)."""
    if sum(x is not None for x in (lesson_id, coding_problem_id, test_id)) != 1:
        raise ValueError("course_ids_for_lessons needs exactly one selector")
    if uses_firestore("catalog"):
        return await (await _reader(session)).course_ids_for_lessons(
            lesson_id=lesson_id,
            match_lesson_key=match_lesson_key,
            coding_problem_id=coding_problem_id,
            test_id=test_id,
        )
    param: uuid.UUID | None
    if lesson_id is not None:
        sql = _COURSES_BY_LESSON_ID_OR_KEY if match_lesson_key else _COURSES_BY_LESSON_ID
        param = lesson_id
    elif coding_problem_id is not None:
        sql, param = _COURSES_BY_PROBLEM, coding_problem_id
    else:
        sql, param = _COURSES_BY_TEST, test_id
    rows = await session.execute(text(sql), {"i": param})
    return [r[0] for r in rows.all()]


async def current_outline_lessons(
    session: AsyncSession, course_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, bool]]:
    """``(lesson_key, title, is_required)`` of the course's current version in outline order
    (analytics lesson funnel)."""
    if uses_firestore("catalog"):
        return await (await _reader(session)).current_outline_lessons(course_id)
    rows = (
        await session.execute(
            text(
                "SELECT l.lesson_key, l.title, l.is_required FROM courses c "
                "JOIN lessons l ON l.course_version_id = c.current_version_id "
                "JOIN course_modules m ON m.id = l.course_module_id "
                "WHERE c.id = :c ORDER BY m.position, l.position"
            ),
            {"c": course_id},
        )
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


async def search_published_lessons(
    session: AsyncSession, org_id: uuid.UUID, like: str, *, limit: int = 25
) -> list[tuple[uuid.UUID, str, str, str]]:
    """``(lesson_id, title, lesson_type, course_title)`` of lessons in the current version of
    published platform / ``org_id`` courses whose title matches ``like`` (paths link picker)."""
    if uses_firestore("catalog"):
        return await (await _reader(session)).search_published_lessons(org_id, like, limit)
    rows = await session.execute(
        select(Lesson.id, Lesson.title, Lesson.lesson_type, Course.title)
        .join(CourseVersion, CourseVersion.id == Lesson.course_version_id)
        .join(
            Course,
            and_(Course.id == CourseVersion.course_id, Course.current_version_id == CourseVersion.id),
        )
        .where(
            or_(Course.organization_id == org_id, Course.organization_id.is_(None)),
            Course.status == "published",
            Lesson.title.ilike(like),
        )
        .limit(limit)
    )
    return [(r[0], r[1], r[2], r[3]) for r in rows.all()]


async def lesson_assets(
    session: AsyncSession, lesson_id: uuid.UUID, *, include_retired: bool = False
) -> list[LessonAsset]:
    """A lesson's assets by ``position`` (learning lesson payload: retired ones excluded)."""
    if uses_firestore("catalog"):
        return await (await _reader(session)).lesson_assets(lesson_id, include_retired)
    stmt = select(LessonAsset).where(LessonAsset.lesson_id == lesson_id)
    if not include_retired:
        stmt = stmt.where(LessonAsset.status != "retired")
    return list((await session.execute(stmt.order_by(LessonAsset.position))).scalars())


async def lesson_resources(session: AsyncSession, lesson_id: uuid.UUID) -> list[Resource]:
    """A lesson's resources by id (learning lesson payload)."""
    if uses_firestore("catalog"):
        return await (await _reader(session)).lesson_resources(lesson_id)
    return list(
        (
            await session.execute(
                select(Resource).where(Resource.lesson_id == lesson_id).order_by(Resource.id)
            )
        ).scalars()
    )


# --------------------------------------------------------------------------- asset queries


async def asset_with_parents(
    session: AsyncSession, asset_id: uuid.UUID, *, version_statuses: Sequence[str]
) -> tuple[LessonAsset, Lesson, CourseVersion, Course] | None:
    """An asset with its lesson, version and (not deleted) course when the version status is
    one of ``version_statuses`` (media ``student_asset``)."""
    if uses_firestore("catalog"):
        return await (await _reader(session)).asset_with_parents(asset_id, version_statuses)
    row = (
        await session.execute(
            select(LessonAsset, Lesson, CourseVersion, Course)
            .join(Lesson, Lesson.id == LessonAsset.lesson_id)
            .join(CourseVersion, CourseVersion.id == Lesson.course_version_id)
            .join(Course, Course.id == CourseVersion.course_id)
            .where(
                LessonAsset.id == asset_id,
                CourseVersion.status.in_(version_statuses),
                Course.deleted_at.is_(None),
            )
        )
    ).first()
    return None if row is None else (row[0], row[1], row[2], row[3])


async def lock_pending_scan_assets(session: AsyncSession, *, limit: int) -> list[LessonAsset]:
    """S3 assets still waiting for a malware-scan result, oldest first, locked
    ``FOR UPDATE SKIP LOCKED`` (media scan sweep). Firestore: no row lock (see
    ``CatalogReadRepo.pending_scan_assets``)."""
    if uses_firestore("catalog"):
        return await (await _reader(session)).pending_scan_assets(limit)
    return list(
        (
            await session.execute(
                select(LessonAsset)
                .where(
                    LessonAsset.provider == "s3",
                    LessonAsset.scan_status == "pending",
                    LessonAsset.s3_key.is_not(None),
                )
                .order_by(LessonAsset.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )


async def assets_by_s3_key(session: AsyncSession, s3_key: str) -> list[LessonAsset]:
    """Assets stored under ``s3_key``, unordered (media scan-result consumer)."""
    if uses_firestore("catalog"):
        return await (await _reader(session)).assets_by_s3_key(s3_key)
    return list((await session.execute(select(LessonAsset).where(LessonAsset.s3_key == s3_key))).scalars())


# --------------------------------------------------------------------------- aggregates


async def course_status_counts(session: AsyncSession) -> dict[str, int]:
    """``{status: n}`` of the courses visible in the caller's context, soft-deleted excluded
    (admin dashboard ``learning`` tiles; replaces its inline ``GROUP BY`` on ``courses``)."""
    if uses_firestore("catalog"):
        return dict(await (await _reader(session)).status_counts())
    from sqlalchemy import func

    rows = await session.execute(
        select(Course.status, func.count()).where(Course.deleted_at.is_(None)).group_by(Course.status)
    )
    return {k: int(n) for k, n in rows.all()}


# --------------------------------------------------------------------------- system-context lookups


async def course_org_system(
    session: AsyncSession, principal: Principal, course_id: uuid.UUID
) -> uuid.UUID | None:
    """Owning organization of a course (None = platform course), looked up in the
    ``catalog.scope_lookup`` system context; 404 when there is no such course (learning
    assignment target scope)."""
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import system_reader

        exists, fs_org = await system_reader().course_org(course_id)
        if not exists:
            raise ProblemError("not_found")
        return fs_org
    row = await _system_first(
        session, principal, select(Course.organization_id).where(Course.id == course_id)
    )
    if row is None:
        raise ProblemError("not_found")
    org: uuid.UUID | None = row[0]
    return org


async def asset_lesson_id_system(
    session: AsyncSession, principal: Principal, asset_id: uuid.UUID
) -> uuid.UUID | None:
    """The lesson of an asset, looked up in the ``catalog.scope_lookup`` system context; None
    when there is no such asset (media asset status scope)."""
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import system_reader

        return await system_reader().asset_lesson_id(asset_id)
    row = await _system_first(
        session, principal, select(LessonAsset.lesson_id).where(LessonAsset.id == asset_id)
    )
    return None if row is None else row[0]


# --------------------------------------------------------------------------- writes


async def create_asset(session: AsyncSession, **fields: Any) -> LessonAsset:
    """Insert a lesson asset (a new uuid7 ``id`` unless given) and flush (media uploads)."""
    fields.setdefault("id", uuid7())
    if uses_firestore("catalog"):
        return await (await _writer(session)).create_asset(fields)
    asset = LessonAsset(**fields)
    session.add(asset)
    await session.flush()
    return asset


async def update_asset(session: AsyncSession, asset_id: uuid.UUID, **changes: Any) -> LessonAsset:
    """Set columns of a lesson asset and flush; returns the updated asset (media status,
    duration and scan results)."""
    if uses_firestore("catalog"):
        return await (await _writer(session)).update_asset(asset_id, changes)
    asset = await session.get(LessonAsset, asset_id)
    if asset is None:
        raise ProblemError("not_found")
    for k, v in changes.items():
        setattr(asset, k, v)
    await session.flush()
    return asset


async def update_lesson(session: AsyncSession, lesson_id: uuid.UUID, **changes: Any) -> Lesson:
    """Set columns of a lesson and flush; returns the updated lesson (media video duration).
    Firestore: also refreshes the version outline (and the current course card)."""
    if uses_firestore("catalog"):
        return await (await _writer(session)).update_lesson(lesson_id, changes)
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise ProblemError("not_found")
    for k, v in changes.items():
        setattr(lesson, k, v)
    await session.flush()
    return lesson
