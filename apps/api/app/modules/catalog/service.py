"""Catalog domain logic: course drafts and immutable published versions, outline editing,
lessons, assets metadata, resources, public catalogue queries.

Versioning (FR-CAT-002): every course has at most one editable version (``draft`` or
``in_review``). Editing a published course lazily clones the current published version into a
new draft (modules keep ``module_key``, lessons keep ``lesson_key``, asset rows are copied, no
binaries). Publishing makes the version immutable, supersedes the previous one and points
``courses.current_version_id`` at it. Progress is keyed by ``lesson_key`` so re-publishing never
resets it.

Hooks for other modules:

* ``register_publish_hook(fn)`` — ``await fn(session, course, version)`` runs inside the publish
  transaction (learning uses it to auto-migrate enrolments on ``minor`` versions). With
  ``TD_STORE_CATALOG=firestore`` it runs on the Postgres session right **after** the Firestore
  publish transaction committed, with transient course/version objects (cross-store ordering:
  if the Postgres transaction then fails, the version stays published in Firestore while the
  enrolment migration, audit and outbox rows roll back).

Persistence: the loaders below dispatch on ``uses_firestore("catalog")`` to ``repo_firestore``
(transient ORM instances, same TN visibility); the Postgres path is unchanged.
* ``course_org_lookup`` is registered with ``rbac.service.register_course_org_lookup`` so the
  ``course:{id}`` scope chain includes the owning organization.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import ScopeRef, require_permission
from app.core.db import system_context, tenant_context
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import to_rfc3339, utcnow
from app.modules.catalog.models import (
    Course,
    CourseModule,
    CourseVersion,
    Lesson,
    LessonAsset,
    LessonTopic,
)

EDITABLE = ("draft", "in_review")
DEFAULT_CERTIFICATE_RULE: dict[str, Any] = {"required_lessons_pct": 100}

PublishHook = Callable[[AsyncSession, Course, CourseVersion], Awaitable[None]]
_publish_hooks: list[PublishHook] = []


def register_publish_hook(fn: PublishHook) -> None:
    if fn not in _publish_hooks:
        _publish_hooks.append(fn)


def vf(field: str, code: str, msg: str, status: int = 422) -> ProblemError:
    return ProblemError("validation_failed", status, errors=[{"field": field, "code": code, "message": msg}])


# --------------------------------------------------------------------------- authorization helpers


async def course_org_lookup(session: AsyncSession, course_id: uuid.UUID) -> uuid.UUID | None:
    """rbac hook: owning organization of a course (None = platform catalogue or unknown).
    Called by the permission checker inside its own system context."""
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import system_reader

        return (await system_reader().course_org(course_id))[1]
    return (
        await session.execute(select(Course.organization_id).where(Course.id == course_id))
    ).scalar_one_or_none()


async def ensure_permission(
    request: Request, session: AsyncSession, principal: Principal, permission: str, scope: ScopeRef
) -> None:
    """In-handler permission check for scopes known only after loading a row. Uses the same
    dependency as route-level checks (404 for cross-tenant targets, 403 otherwise) and restores
    the principal's RLS context afterwards."""
    try:
        await require_permission(permission, scope=scope)(request, principal)
    finally:
        if session:  # falsy NO_POSTGRES session (no Postgres): nothing to restore
            await tenant_context(session, principal)


async def system_lookup(session: AsyncSession, principal: Principal, stmt: Any) -> Any:
    """Run one scope-resolution lookup in a named system context (like the rbac checker),
    then restore the principal's RLS context. Never used to return data to the caller."""
    await system_context(session, "catalog.scope_lookup")
    try:
        return (await session.execute(stmt)).first()
    finally:
        await tenant_context(session, principal)


async def lesson_scope(
    session: AsyncSession, principal: Principal, lesson_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID | None]:
    """(course_id, organization_id) of a lesson, or 404."""
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import system_reader

        found = await system_reader().lesson_scope(lesson_id)
        if found is None:
            raise ProblemError("not_found")
        return found
    row = await system_lookup(
        session,
        principal,
        select(CourseVersion.course_id, Lesson.organization_id)
        .join(CourseVersion, CourseVersion.id == Lesson.course_version_id)
        .where(Lesson.id == lesson_id),
    )
    if row is None:
        raise ProblemError("not_found")
    return row[0], row[1]


# --------------------------------------------------------------------------- loaders


async def get_course(session: AsyncSession, course_id: uuid.UUID) -> Course:
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import reader

        fc = (await (await reader(session)).courses([course_id])).get(course_id)
        if fc is None or fc.deleted_at is not None:
            raise ProblemError("not_found")
        return fc
    course = (
        await session.execute(select(Course).where(Course.id == course_id, Course.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if course is None:
        raise ProblemError("not_found")
    return course


async def editable_version(session: AsyncSession, course_id: uuid.UUID) -> CourseVersion | None:
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import reader

        return await (await reader(session)).editable_version(course_id)
    return (
        await session.execute(
            select(CourseVersion).where(
                CourseVersion.course_id == course_id, CourseVersion.status.in_(EDITABLE)
            )
        )
    ).scalar_one_or_none()


async def get_version(session: AsyncSession, version_id: uuid.UUID | None) -> CourseVersion | None:
    if version_id is None:
        return None
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import reader

        return (await (await reader(session)).versions([version_id])).get(version_id)
    return await session.get(CourseVersion, version_id)


async def version_tree(
    session: AsyncSession, version_id: uuid.UUID
) -> tuple[list[CourseModule], dict[uuid.UUID, list[Lesson]], dict[uuid.UUID, list[LessonAsset]]]:
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import reader

        fm, fl, fa, _topics = await (await reader(session)).version_tree(version_id)
        return fm, fl, fa
    modules = list(
        (
            await session.execute(
                select(CourseModule)
                .where(CourseModule.course_version_id == version_id)
                .order_by(CourseModule.position)
            )
        ).scalars()
    )
    lessons = list(
        (
            await session.execute(
                select(Lesson).where(Lesson.course_version_id == version_id).order_by(Lesson.position)
            )
        ).scalars()
    )
    by_module: dict[uuid.UUID, list[Lesson]] = {m.id: [] for m in modules}
    for le in lessons:
        by_module.setdefault(le.course_module_id, []).append(le)
    assets: dict[uuid.UUID, list[LessonAsset]] = {}
    if lessons:
        rows = (
            await session.execute(
                select(LessonAsset)
                .where(LessonAsset.lesson_id.in_([le.id for le in lessons]))
                .order_by(LessonAsset.position, LessonAsset.id)
            )
        ).scalars()
        for a in rows:
            assets.setdefault(a.lesson_id, []).append(a)
    return modules, by_module, assets


async def version_lessons(session: AsyncSession, version_id: uuid.UUID) -> list[Lesson]:
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import reader

        return await (await reader(session)).version_lessons(version_id)
    return list(
        (await session.execute(select(Lesson).where(Lesson.course_version_id == version_id))).scalars()
    )


# --------------------------------------------------------------------------- serializers


def asset_status(a: LessonAsset) -> str:
    return "ready" if a.status == "available" else a.status


def asset_out(a: LessonAsset) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "asset_type": a.asset_type,
        "provider": a.provider,
        "status": asset_status(a),
        "scan_status": a.scan_status,
        "mime_type": a.mime_type,
        "size_bytes": a.size_bytes,
        "duration_seconds": a.duration_seconds,
        "position": a.position,
    }


async def lesson_topics_map(
    session: AsyncSession, lesson_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """``lesson_topics`` (CAT-15) of the given lessons, primary first."""
    ids = list(lesson_ids)
    out: dict[uuid.UUID, list[dict[str, Any]]] = {i: [] for i in ids}
    if not ids:
        return out
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import _topics, reader

        docs = await (await reader(session)).lesson_docs(ids)
        for i in ids:
            d = docs.get(str(i))
            out[i] = _topics(d.get("topics")) if d is not None else []
        return out
    rows = (
        await session.execute(
            select(LessonTopic)
            .where(LessonTopic.lesson_id.in_(ids))
            .order_by(LessonTopic.lesson_id, LessonTopic.is_primary.desc(), LessonTopic.topic_id)
        )
    ).scalars()
    for t in rows:
        out[t.lesson_id].append({"topic_id": str(t.topic_id), "is_primary": t.is_primary})
    return out


def lesson_out(
    le: Lesson,
    assets: Iterable[LessonAsset] = (),
    *,
    full: bool = True,
    topics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(le.id),
        "lesson_key": str(le.lesson_key),
        "title": le.title,
        "lesson_type": le.lesson_type,
        "position": le.position,
        "is_required": le.is_required,
        "is_free_preview": le.is_free_preview,
        "duration_seconds": le.duration_seconds,
        "est_reading_minutes": le.est_reading_minutes,
    }
    if full:
        out.update(
            {
                "course_module_id": str(le.course_module_id),
                "article_body": le.article_body,
                "test_id": str(le.test_id) if le.test_id else None,
                "coding_problem_id": str(le.coding_problem_id) if le.coding_problem_id else None,
                "assignment_id": str(le.assignment_id) if le.assignment_id else None,
                "live_url": le.live_url,
                "assets": [asset_out(a) for a in assets],
            }
        )
        if topics is not None:  # studio views (webstaff request 8); not loaded for learners
            out["topics"] = topics
    return out


def version_meta(v: CourseVersion) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "version_no": v.version_no,
        "status": v.status,
        "title": v.title,
        "summary": v.summary,
        "description_md": v.description_md,
        "outcomes": list(v.outcomes or []),
        "level": v.level,
        "language": v.language,
        "category": v.category,
        "tags": list(v.tags or []),
        "certificate_rule": v.certificate_rule,
        "completeness_plan": v.completeness_plan,
        "change_type": v.change_type,
        "changelog": v.changelog,
        "created_by": str(v.created_by),
        "submitted_at": to_rfc3339(v.submitted_at) if v.submitted_at else None,
        "published_at": to_rfc3339(v.published_at) if v.published_at else None,
    }


async def version_out(session: AsyncSession, v: CourseVersion, *, full: bool = True) -> dict[str, Any]:
    topics: dict[uuid.UUID, list[dict[str, Any]]] = {}
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import reader

        modules, by_module, assets, fs_topics = await (await reader(session)).version_tree(v.id)
        if full:
            topics = fs_topics
    else:
        modules, by_module, assets = await version_tree(session, v.id)
        if full:
            topics = await lesson_topics_map(session, [le.id for ls in by_module.values() for le in ls])
    out = version_meta(v)
    out["modules"] = [
        {
            "id": str(m.id),
            "module_key": str(m.module_key),
            "title": m.title,
            "position": m.position,
            "lessons": [
                lesson_out(le, assets.get(le.id, ()), full=full, topics=topics.get(le.id) if full else None)
                for le in by_module.get(m.id, [])
            ],
        }
        for m in modules
    ]
    return out


def course_out(c: Course) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "organization_id": str(c.organization_id) if c.organization_id else None,
        "slug": c.slug,
        "title": c.title,
        "course_kind": c.course_kind,
        "visibility": c.visibility,
        "status": c.status,
        "is_free": c.is_free,
        "current_version_id": str(c.current_version_id) if c.current_version_id else None,
        "completeness_pct": float(c.completeness_pct),
        "created_at": to_rfc3339(c.created_at),
        "updated_at": to_rfc3339(c.updated_at),
    }


# --------------------------------------------------------------------------- authoring


async def create_course(
    session: AsyncSession,
    principal: Principal,
    *,
    organization_id: uuid.UUID | None,
    slug: str,
    title: str,
    course_kind: str,
    visibility: str,
    is_free: bool,
    summary: str | None,
) -> tuple[Course, CourseVersion]:
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import CREATE_PERMS, writer

        return await (await writer(session, principal, CREATE_PERMS)).create_course(
            principal.user_id,
            organization_id=organization_id,
            slug=slug,
            title=title,
            course_kind=course_kind,
            visibility=visibility,
            is_free=is_free,
            summary=summary,
            certificate_rule=DEFAULT_CERTIFICATE_RULE,
        )
    clash = (
        await session.execute(
            select(Course.id).where(
                Course.slug == slug,
                Course.organization_id.is_(None)
                if organization_id is None
                else Course.organization_id == organization_id,
                Course.deleted_at.is_(None),
            )
        )
    ).first()
    if clash is not None:
        raise ProblemError("validation_failed", 409, errors=[_slug_taken()])
    course = Course(
        id=uuid7(),
        organization_id=organization_id,
        slug=slug,
        title=title,
        course_kind=course_kind,
        visibility=visibility,
        status="draft",
        is_free=is_free,
        created_by=principal.user_id,
    )
    session.add(course)
    await session.flush()
    version = CourseVersion(
        id=uuid7(),
        course_id=course.id,
        organization_id=organization_id,
        version_no=1,
        title=title,
        summary=summary,
        status="draft",
        certificate_rule=dict(DEFAULT_CERTIFICATE_RULE),
        created_by=principal.user_id,
    )
    session.add(version)
    await session.flush()
    return course, version


def _slug_taken() -> dict[str, str]:
    return {"field": "slug", "code": "taken", "message": "This slug is already used"}


async def ensure_draft(session: AsyncSession, course: Course, principal: Principal) -> CourseVersion:
    """Return the editable version, cloning the published one into a new draft if needed."""
    if course.status == "archived":
        raise ProblemError("invalid_state_transition", detail="Archived courses cannot be edited.")
    existing = await editable_version(session, course.id)
    if existing is not None:
        return existing
    src = await get_version(session, course.current_version_id)
    if src is None:  # pragma: no cover - create_course always makes a draft
        raise ProblemError("invalid_state_transition")
    max_no = (
        await session.execute(
            select(func.max(CourseVersion.version_no)).where(CourseVersion.course_id == course.id)
        )
    ).scalar_one()
    draft = CourseVersion(
        id=uuid7(),
        course_id=course.id,
        organization_id=course.organization_id,
        version_no=int(max_no or 0) + 1,
        title=src.title,
        summary=src.summary,
        description_md=src.description_md,
        outcomes=list(src.outcomes or []),
        level=src.level,
        language=src.language,
        category=src.category,
        tags=list(src.tags or []),
        certificate_rule=src.certificate_rule,
        completeness_plan=src.completeness_plan,
        status="draft",
        created_by=principal.user_id,
    )
    session.add(draft)
    await session.flush()
    modules, by_module, assets = await version_tree(session, src.id)
    for m in modules:
        nm = CourseModule(
            id=uuid7(),
            course_version_id=draft.id,
            organization_id=course.organization_id,
            module_key=m.module_key,
            title=m.title,
            position=m.position,
        )
        session.add(nm)
        await session.flush()
        for le in by_module.get(m.id, []):
            nl = Lesson(
                id=uuid7(),
                course_module_id=nm.id,
                course_version_id=draft.id,
                organization_id=course.organization_id,
                lesson_key=le.lesson_key,
                title=le.title,
                lesson_type=le.lesson_type,
                position=le.position,
                is_required=le.is_required,
                is_free_preview=le.is_free_preview,
                duration_seconds=le.duration_seconds,
                article_body=le.article_body,
                test_id=le.test_id,
                coding_problem_id=le.coding_problem_id,
                assignment_id=le.assignment_id,
                live_url=le.live_url,
                est_reading_minutes=le.est_reading_minutes,
            )
            session.add(nl)
            await session.flush()
            for a in assets.get(le.id, []):
                session.add(
                    LessonAsset(
                        id=uuid7(),
                        lesson_id=nl.id,
                        organization_id=course.organization_id,
                        asset_type=a.asset_type,
                        provider=a.provider,
                        provider_asset_id=a.provider_asset_id,
                        s3_key=a.s3_key,
                        mime_type=a.mime_type,
                        size_bytes=a.size_bytes,
                        duration_seconds=a.duration_seconds,
                        status=a.status,
                        scan_status=a.scan_status,
                        position=a.position,
                    )
                )
            topics = (
                await session.execute(select(LessonTopic).where(LessonTopic.lesson_id == le.id))
            ).scalars()
            for t in topics:
                session.add(
                    LessonTopic(
                        lesson_id=nl.id,
                        topic_id=t.topic_id,
                        organization_id=course.organization_id,
                        is_primary=t.is_primary,
                    )
                )
    await session.flush()
    return draft


def touch_draft(v: CourseVersion) -> None:
    """Any edit of an ``in_review`` version sends it back to ``draft``."""
    if v.status == "in_review":
        v.status = "draft"
        v.submitted_by = None
        v.submitted_at = None


async def editable_lesson(session: AsyncSession, lesson_id: uuid.UUID) -> tuple[Lesson, CourseVersion]:
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import reader

        repo = await reader(session)
        fl = (await repo.lessons([lesson_id])).get(lesson_id)
        if fl is None:
            raise ProblemError("not_found")
        fv = (await repo.versions([fl.course_version_id])).get(fl.course_version_id)
        if fv is None:
            raise ProblemError("not_found")
        if fv.status not in EDITABLE:
            raise ProblemError(
                "invalid_state_transition",
                detail="Published lessons are immutable. Edit the lesson in the course draft.",
            )
        return fl, fv
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise ProblemError("not_found")
    version = await session.get(CourseVersion, lesson.course_version_id)
    assert version is not None
    if version.status not in EDITABLE:
        raise ProblemError(
            "invalid_state_transition",
            detail="Published lessons are immutable. Edit the lesson in the course draft.",
        )
    return lesson, version


def check_lesson_refs(lesson_type: str, values: dict[str, Any]) -> None:
    need = {
        "quiz": "test_id",
        "practice_set": "test_id",
        "coding": "coding_problem_id",
        "assignment": "assignment_id",
        "live_link": "live_url",
    }.get(lesson_type)
    if need and not values.get(need):
        raise vf(need, "required", f"{need} is required for {lesson_type} lessons")


async def add_lesson(
    session: AsyncSession,
    course: Course,
    draft: CourseVersion,
    *,
    module_key: uuid.UUID | None,
    module_title: str | None,
    values: dict[str, Any],
) -> Lesson:
    check_lesson_refs(values["lesson_type"], values)
    modules = list(
        (
            await session.execute(
                select(CourseModule)
                .where(CourseModule.course_version_id == draft.id)
                .order_by(CourseModule.position)
            )
        ).scalars()
    )
    module: CourseModule | None
    if module_key is not None:
        module = next((m for m in modules if m.module_key == module_key), None)
        if module is None:
            raise vf("module_key", "unknown", "No such module in the draft")
    elif module_title or not modules:
        module = CourseModule(
            id=uuid7(),
            course_version_id=draft.id,
            organization_id=course.organization_id,
            module_key=uuid7(),
            title=module_title or "Module 1",
            position=len(modules),
        )
        session.add(module)
        await session.flush()
    else:
        module = modules[-1]
    pos = (
        await session.execute(
            select(func.coalesce(func.max(Lesson.position) + 1, 0)).where(
                Lesson.course_module_id == module.id
            )
        )
    ).scalar_one()
    lesson = Lesson(
        id=uuid7(),
        course_module_id=module.id,
        course_version_id=draft.id,
        organization_id=course.organization_id,
        lesson_key=uuid7(),
        position=int(pos),
        **values,
    )
    session.add(lesson)
    touch_draft(draft)
    await session.flush()
    return lesson


async def replace_outline(
    session: AsyncSession, course: Course, draft: CourseVersion, modules_in: list[dict[str, Any]]
) -> None:
    modules = {
        m.module_key: m
        for m in (
            await session.execute(select(CourseModule).where(CourseModule.course_version_id == draft.id))
        ).scalars()
    }
    lessons = {le.id: le for le in await version_lessons(session, draft.id)}
    seen_lessons: set[uuid.UUID] = set()
    seen_modules: set[uuid.UUID] = set()
    for i, mi in enumerate(modules_in):
        mk = mi.get("module_key")
        if mk is not None and mk not in modules:
            raise vf(f"modules.{i}.module_key", "unknown", "No such module in the draft")
        if mk is not None and mk in seen_modules:
            raise vf(f"modules.{i}.module_key", "duplicate", "Module listed twice")
        for lid in mi["lesson_ids"]:
            if lid not in lessons:
                raise vf(f"modules.{i}.lesson_ids", "unknown", "Lesson is not part of the draft")
            if lid in seen_lessons:
                raise vf(f"modules.{i}.lesson_ids", "duplicate", "Lesson listed twice")
            seen_lessons.add(lid)
        if mk is not None:
            seen_modules.add(mk)
    kept: set[uuid.UUID] = set()
    for i, mi in enumerate(modules_in):
        mk = mi.get("module_key")
        if mk is not None:
            m = modules[mk]
            m.title = mi["title"]
            m.position = i
        else:
            m = CourseModule(
                id=uuid7(),
                course_version_id=draft.id,
                organization_id=course.organization_id,
                module_key=uuid7(),
                title=mi["title"],
                position=i,
            )
            session.add(m)
            await session.flush()
        kept.add(m.id)
        for j, lid in enumerate(mi["lesson_ids"]):
            le = lessons[lid]
            le.course_module_id = m.id
            le.position = j
    await session.flush()
    removed = [lid for lid in lessons if lid not in seen_lessons]
    if removed:
        await session.execute(delete(Lesson).where(Lesson.id.in_(removed)))
    stale_modules = [m.id for m in modules.values() if m.id not in kept]
    if stale_modules:
        await session.execute(delete(CourseModule).where(CourseModule.id.in_(stale_modules)))
    touch_draft(draft)
    await session.flush()


async def set_lesson_topics(session: AsyncSession, lesson: Lesson, topics: list[dict[str, Any]]) -> None:
    if topics and sum(1 for t in topics if t["is_primary"]) != 1:
        raise vf("topics", "one_primary", "Exactly one topic must be primary")
    if len({t["topic_id"] for t in topics}) != len(topics):
        raise vf("topics", "duplicate", "Topic listed twice")
    await session.execute(delete(LessonTopic).where(LessonTopic.lesson_id == lesson.id))
    for t in topics:
        session.add(
            LessonTopic(
                lesson_id=lesson.id,
                topic_id=t["topic_id"],
                organization_id=lesson.organization_id,
                is_primary=t["is_primary"],
            )
        )
    await session.flush()


async def submit_review(session: AsyncSession, course: Course, principal: Principal) -> CourseVersion:
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import writer

        return await (await writer(session, principal)).submit_review(principal.user_id, course.id)
    draft = await editable_version(session, course.id)
    if draft is None or draft.status != "draft":
        raise ProblemError("invalid_state_transition", detail="Only a draft can be submitted for review.")
    if not await version_lessons(session, draft.id):
        raise vf("outline", "empty", "Add at least one lesson before submitting for review")
    draft.status = "in_review"
    draft.submitted_by = principal.user_id
    draft.submitted_at = utcnow()
    await session.flush()
    return draft


async def publish(
    session: AsyncSession,
    course: Course,
    principal: Principal,
    *,
    change_type: str,
    changelog: str | None,
) -> CourseVersion:
    if uses_firestore("catalog"):
        return await _publish_firestore(
            session, course, principal, change_type=change_type, changelog=changelog
        )
    version = await editable_version(session, course.id)
    if version is None or version.status != "in_review":
        raise ProblemError("invalid_state_transition", detail="Only a version in review can be published.")
    # SoD-04: author != publisher for the platform catalogue.
    if course.organization_id is None and principal.user_id in {version.created_by, version.submitted_by}:
        raise ProblemError(
            "sod_violation", detail="A different person must publish a version you authored or submitted."
        )
    lessons = await version_lessons(session, version.id)
    if not lessons:
        raise vf("outline", "empty", "The version has no lessons")
    assets = list(
        (
            await session.execute(
                select(LessonAsset).where(LessonAsset.lesson_id.in_([le.id for le in lessons]))
            )
        ).scalars()
    )
    pending = [a for a in assets if a.status in ("uploading", "processing")]
    if pending:
        raise ProblemError(
            "validation_failed",
            422,
            detail="Some media is still uploading or processing.",
            errors=[
                {"field": f"assets.{a.id}", "code": "media_processing", "message": "Media not ready"}
                for a in pending
            ],
        )
    ready_video = {a.lesson_id for a in assets if a.asset_type == "video" and a.status == "available"}
    missing = [le for le in lessons if le.lesson_type == "video" and le.id not in ready_video]
    if missing:
        raise ProblemError(
            "validation_failed",
            422,
            detail="Every video lesson needs a ready video.",
            errors=[
                {"field": f"lessons.{le.id}", "code": "video_missing", "message": "No ready video"}
                for le in missing
            ],
        )
    now = utcnow()
    if course.current_version_id is not None:
        prev = await session.get(CourseVersion, course.current_version_id)
        if prev is not None and prev.status == "published":
            prev.status = "superseded"
    version.status = "published"
    version.published_at = now
    version.published_by = principal.user_id
    version.change_type = change_type if course.current_version_id is not None else "major"
    version.changelog = changelog
    course.current_version_id = version.id
    course.status = "published"
    course.title = version.title
    course.completeness_pct = completeness(version, len(lessons))
    await session.flush()
    for hook in list(_publish_hooks):
        await hook(session, course, version)
    return version


async def _publish_firestore(
    session: AsyncSession, course: Course, principal: Principal, *, change_type: str, changelog: str | None
) -> CourseVersion:
    """One Firestore transaction (checks, supersede, card, pointers); ``course`` is updated in
    place like the ORM path. The publish hooks run on the Postgres session after the commit."""
    from app.modules.catalog.repo_firestore import writer

    repo = await writer(session, principal)
    new_course, version = await repo.publish(
        principal.user_id, course.id, change_type=change_type, changelog=changelog
    )
    for col in Course.__table__.columns:
        setattr(course, col.key, getattr(new_course, col.key))
    for hook in list(_publish_hooks):
        await hook(session, course, version)
    return version


def completeness(version: CourseVersion, lesson_count: int) -> Decimal:
    plan = version.completeness_plan or {}
    planned = plan.get("planned_lessons")
    if not isinstance(planned, int) or planned <= 0:
        return Decimal(100)
    return Decimal(min(100, round(100 * lesson_count / planned, 2))).quantize(Decimal("0.01"))


# --------------------------------------------------------------------------- public catalogue


def public_course_filter() -> list[Any]:
    return [
        Course.deleted_at.is_(None),
        Course.status == "published",
        Course.organization_id.is_(None),
        Course.current_version_id.is_not(None),
    ]


async def public_course_by_slug(session: AsyncSession, slug: str) -> tuple[Course, CourseVersion]:
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import reader

        found = await (await reader(session)).public_course_by_slug(slug)
        if found is None:
            raise ProblemError("not_found")
        return found
    row = (
        await session.execute(
            select(Course, CourseVersion)
            .join(CourseVersion, CourseVersion.id == Course.current_version_id)
            .where(
                *public_course_filter(), Course.slug == slug, Course.visibility.in_(("public", "unlisted"))
            )
        )
    ).first()
    if row is None:
        raise ProblemError("not_found")
    return row[0], row[1]


async def published_lesson_counts(
    session: AsyncSession, version_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """version_id -> (lesson count, total duration seconds)."""
    if not version_ids:
        return {}
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import reader

        return await (await reader(session)).lesson_counts(version_ids)
    rows = (
        await session.execute(
            select(
                Lesson.course_version_id,
                func.count(Lesson.id),
                func.coalesce(func.sum(Lesson.duration_seconds), 0),
            )
            .where(Lesson.course_version_id.in_(version_ids))
            .group_by(Lesson.course_version_id)
        )
    ).all()
    return {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in rows}


def public_card(c: Course, v: CourseVersion, counts: tuple[int, int] | None) -> dict[str, Any]:
    n, secs = counts or (0, 0)
    return {
        "id": str(c.id),
        "slug": c.slug,
        "title": v.title,
        "summary": v.summary,
        "course_kind": c.course_kind,
        "level": v.level,
        "language": v.language,
        "category": v.category,
        "tags": list(v.tags or []),
        "price_type": "free" if c.is_free else "paid",
        "is_free": c.is_free,
        "lesson_count": n,
        "duration_seconds": secs,
        "completeness_pct": float(c.completeness_pct),
        "published_at": to_rfc3339(v.published_at) if v.published_at else None,
    }
