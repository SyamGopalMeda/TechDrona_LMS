"""Catalog and authoring (api-spec §10, CAT-01, 02, 06, 07, 08-22).

Public reads (``/catalog/*``) run with an empty RLS context, so only platform-catalogue rows
(``organization_id IS NULL``) are visible, and the queries additionally require
``status = published`` and the current published version — drafts never leak.

Authoring (``/studio/*``) runs on the principal's RLS context. Permissions per the role
matrix: ``course.create`` @P/@O, ``course.edit`` / ``course.preview`` @C (the course scope
chain includes the owning organization through ``register_course_org_lookup``),
``course.publish`` and ``course.archive`` @P/@O, ``resource.manage`` @C/@P. Cross-tenant ids
answer ``404`` (TI-02).

Not implemented here (other owners): CAT-03/04 company hubs and CAT-05 topic pages
(placement module).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import and_, func, or_, select

from app.core.audit import audit
from app.core.auth import (
    PLATFORM_SCOPE,
    ScopeRef,
    require_active_principal,
    require_permission,
    scope_from_path,
)
from app.core.company import COMPANY_ORG_ID
from app.core.db import DbSession, PrincipalDbSession
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router, public_router
from app.modules.catalog import service as svc
from app.modules.catalog.models import Course, CourseVersion, Lesson, LessonAsset, Resource
from app.modules.catalog.schemas import (
    CourseIn,
    DraftPatch,
    LessonIn,
    LessonPatch,
    OutlineIn,
    PublishIn,
    ResourceIn,
    ResourcePatch,
    TopicsIn,
)

pub = public_router(prefix="/catalog", tags=["catalog"])
studio = authenticated_router(prefix="/studio", tags=["catalog"])

CourseScope = scope_from_path("course_id", "course")
PUBLIC_CACHE = "public, max-age=300"


def _perm(key: str, scope: Any = None) -> Any:
    return Depends(require_permission(key, scope=scope))


# =========================================================================== public catalogue


def _limit(limit: int) -> int:
    """BE-34: out-of-range ``limit`` is a 400 ``validation_failed`` like every other module's
    ``Query(ge=1, le=100)`` (was silently clamped)."""
    if not 1 <= limit <= MAX_LIMIT:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "limit", "code": "out_of_range", "message": f"Use 1 to {MAX_LIMIT}"}],
        )
    return limit


@pub.get("/courses", operation_id="cat_01_list_courses")
async def list_courses(
    response: Response,
    session: DbSession,
    category: str | None = None,
    level: str | None = None,
    price_type: str | None = Query(default=None, pattern="^(free|paid)$"),
    language: str | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return await _public_list(session, cursor, limit, category, level, price_type, language, None)


@pub.get("/search", operation_id="cat_07_search")
async def search(
    response: Response,
    session: DbSession,
    q: str = Query(min_length=2, max_length=100),
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return await _public_list(session, cursor, limit, None, None, None, None, q)


async def _public_list(
    session: Any,
    cursor: str | None,
    limit: int,
    category: str | None,
    level: str | None,
    price_type: str | None,
    language: str | None,
    q: str | None,
) -> dict[str, Any]:
    limit = _limit(limit)
    conds = [*svc.public_course_filter(), Course.visibility == "public"]
    if category:
        conds.append(CourseVersion.category == category)
    if level:
        conds.append(CourseVersion.level == level)
    if language:
        conds.append(CourseVersion.language == language)
    if price_type:
        conds.append(Course.is_free.is_(price_type == "free"))
    if q:
        doc = func.to_tsvector(
            "simple",
            func.concat_ws(
                " ", CourseVersion.title, CourseVersion.summary, func.array_to_string(CourseVersion.tags, " ")
            ),
        )
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conds.append(
            or_(
                doc.op("@@")(func.websearch_to_tsquery("simple", q)),
                CourseVersion.title.ilike(like),
                func.array_to_string(CourseVersion.tags, " ").ilike(like),
            )
        )
    if cursor:
        pos = decode_cursor(cursor)
        try:
            conds.append(Course.id < uuid.UUID(str(pos["id"])))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
    rows = (
        await session.execute(
            select(Course, CourseVersion)
            .join(CourseVersion, CourseVersion.id == Course.current_version_id)
            .where(*conds)
            .order_by(Course.id.desc())
            .limit(limit + 1)
        )
    ).all()
    more = len(rows) > limit
    rows = rows[:limit]
    counts = await svc.published_lesson_counts(session, [v.id for _, v in rows])
    data = [svc.public_card(c, v, counts.get(v.id)) for c, v in rows]
    nxt = {"id": str(rows[-1][0].id)} if more and rows else None
    return {"data": data, "page": page_meta(nxt, limit)}


@pub.get("/courses/{slug}", operation_id="cat_02_course_detail")
async def course_detail(slug: str, response: Response, session: DbSession) -> dict[str, Any]:
    course, version = await svc.public_course_by_slug(session, slug)
    response.headers["Cache-Control"] = PUBLIC_CACHE
    tree = await svc.version_out(session, version, full=False)
    counts = await svc.published_lesson_counts(session, [version.id])
    card = svc.public_card(course, version, counts.get(version.id))
    preview_ids = [le["id"] for m in tree["modules"] for le in m["lessons"] if le["is_free_preview"]]
    rule = version.certificate_rule
    return {
        **card,
        "description_md": version.description_md,
        "outcomes": tree["outcomes"],
        "syllabus": [
            {"title": m["title"], "position": m["position"], "lessons": m["lessons"]} for m in tree["modules"]
        ],
        "free_preview_lesson_ids": preview_ids,
        "certificate": {"available": rule is not None, "rule": rule},
        "access_options": (
            [{"type": "free", "action": "enrol"}]
            if course.is_free
            else [
                {
                    "type": "paid",
                    "action": "view_plans",
                    "products_url": f"/api/v1/products?course_id={course.id}",
                }
            ]
        ),
        "refund_rule_text": None if course.is_free else "See the plan's refund rule at checkout.",
        "version_no": version.version_no,
    }


@pub.get("/free-resources", operation_id="cat_06_free_resources")
async def free_resources(
    response: Response, session: DbSession, limit: int = DEFAULT_LIMIT
) -> dict[str, Any]:
    limit = _limit(limit)
    response.headers["Cache-Control"] = PUBLIC_CACHE
    res = (
        await session.execute(
            select(Resource, Course.slug)
            .outerjoin(Course, Course.id == Resource.course_id)
            .where(
                Resource.access_level == "public",
                Resource.organization_id.is_(None),
                or_(
                    Resource.course_id.is_(None),
                    and_(Course.status == "published", Course.deleted_at.is_(None)),
                ),
            )
            .order_by(Resource.id.desc())
            .limit(limit)
        )
    ).all()
    courses = (
        await session.execute(
            select(Course, CourseVersion)
            .join(CourseVersion, CourseVersion.id == Course.current_version_id)
            .where(*svc.public_course_filter(), Course.visibility == "public", Course.is_free.is_(True))
            .order_by(Course.id.desc())
            .limit(limit)
        )
    ).all()
    counts = await svc.published_lesson_counts(session, [v.id for _, v in courses])
    return {
        "data": {
            "resources": [
                {
                    "id": str(r.id),
                    "title": r.title,
                    "resource_type": r.resource_type,
                    "course_slug": slug,
                    "download_url": "/api/v1/media/downloads",
                    "url": r.url,
                }
                for r, slug in res
            ],
            "free_courses": [svc.public_card(c, v, counts.get(v.id)) for c, v in courses],
        }
    }


# =========================================================================== studio: courses


@studio.get("/courses", operation_id="cat_08_studio_courses", openapi_extra={"x-td-idle": "neutral"})
async def studio_courses(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    status: str | None = Query(default=None, pattern="^(draft|published|archived)$"),
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    from app.modules.rbac.service import ORG_PRIVATE_VIA_BATCH, batch_org, role_permission_map

    perms = await role_permission_map(session)
    keys = {"course.create", "course.edit", "course.preview"}
    platform = False
    orgs: set[uuid.UUID] = set()
    course_ids: set[uuid.UUID] = set()
    batch_staff = False
    for g in principal.grants:
        role_perms = perms.get(g.role, frozenset())
        if not keys & role_perms:
            continue
        if g.scope_type == "platform":
            platform = True
        elif g.scope_type == "course" and g.scope_id:
            course_ids.add(g.scope_id)
        elif g.scope_type == "batch" and g.scope_id:
            batch_staff = True
            # ADM-41 (matrix "O-private"): a batch grant with course.create/edit covers the
            # org-private (organization-owned) courses of the batch's organization, mirroring
            # ``rbac.service.ORG_PRIVATE_VIA_BATCH``. Platform courses are never included.
            if ORG_PRIVATE_VIA_BATCH & role_perms:
                b_org = await batch_org(session, g.scope_id)
                if b_org is not None:
                    orgs.add(b_org)
    if not (platform or orgs or course_ids or batch_staff):
        raise ProblemError("permission_denied", permission="course.create")
    # ADM-41: a batch-scoped trainer is a studio user too; the list holds the courses they can
    # edit (course-scoped grants plus their batch orgs' private courses), so the trainer portal
    # renders instead of 403.
    limit = _limit(limit)
    conds: list[Any] = [Course.deleted_at.is_(None)]
    if not platform:
        conds.append(
            or_(Course.organization_id.in_(orgs or {uuid7()}), Course.id.in_(course_ids or {uuid7()}))
        )
    if status:
        conds.append(Course.status == status)
    if cursor:
        conds.append(Course.id < uuid.UUID(str(decode_cursor(cursor).get("id"))))
    rows = list(
        (
            await session.execute(select(Course).where(*conds).order_by(Course.id.desc()).limit(limit + 1))
        ).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    drafts = {
        v.course_id: v
        for v in (
            await session.execute(
                select(CourseVersion).where(
                    CourseVersion.course_id.in_([c.id for c in rows]), CourseVersion.status.in_(svc.EDITABLE)
                )
            )
        ).scalars()
    }
    data = []
    for c in rows:
        out = svc.course_out(c)
        d = drafts.get(c.id)
        out["draft"] = {"id": str(d.id), "status": d.status, "version_no": d.version_no} if d else None
        data.append(out)
    return {"data": data, "page": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit)}


@studio.post("/courses", status_code=201, operation_id="cat_09_create_course")
async def create_course(
    request: Request,
    body: CourseIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    # Single company: platform authors (content manager, Admin) create platform courses; a
    # batch trainer (ADM-41) creates a company course (organization = the company, internal).
    from app.core import auth as core_auth

    org: uuid.UUID | None = None
    if not await core_auth.check_permission(principal, "course.create", PLATFORM_SCOPE, request):
        org = COMPANY_ORG_ID
        await svc.ensure_permission(
            request, session, principal, "course.create", ScopeRef("organization", org)
        )

    async def op() -> IdemResult:
        course, version = await svc.create_course(
            session,
            principal,
            organization_id=org,
            slug=body.slug,
            title=body.title,
            course_kind=body.course_kind,
            visibility=body.visibility,
            is_free=body.is_free,
            summary=body.summary,
        )
        await audit(
            session,
            principal,
            "course.create",
            "course",
            course.id,
            organization_id=course.organization_id,
            after={"slug": course.slug, "is_free": course.is_free, "visibility": course.visibility},
        )
        out = svc.course_out(course)
        out["draft"] = await svc.version_out(session, version)
        return IdemResult(out, 201, course.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@studio.get(
    "/courses/{course_id}",
    operation_id="cat_10_studio_course",
    dependencies=[_perm("course.edit", CourseScope)],
    openapi_extra={"x-td-idle": "neutral"},
)
async def studio_course(course_id: uuid.UUID, session: PrincipalDbSession) -> dict[str, Any]:
    course = await svc.get_course(session, course_id)
    out = svc.course_out(course)
    draft = await svc.editable_version(session, course.id)
    published = await svc.get_version(session, course.current_version_id)
    out["draft"] = await svc.version_out(session, draft) if draft else None
    out["published"] = await svc.version_out(session, published) if published else None
    return out


@studio.patch(
    "/courses/{course_id}/draft",
    operation_id="cat_11_patch_draft",
    dependencies=[_perm("course.edit", CourseScope)],
)
async def patch_draft(
    course_id: uuid.UUID,
    body: DraftPatch,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    course = await svc.get_course(session, course_id)
    draft = await svc.ensure_draft(session, course, principal)
    data = body.model_dump(exclude_unset=True)
    before: dict[str, Any] = {k: getattr(course, k) for k in ("slug", "visibility", "is_free") if k in data}
    if "slug" in data and data["slug"] != course.slug:
        clash = (
            await session.execute(
                select(Course.id).where(
                    Course.slug == data["slug"],
                    Course.id != course.id,
                    Course.organization_id.is_(None)
                    if course.organization_id is None
                    else Course.organization_id == course.organization_id,
                    Course.deleted_at.is_(None),
                )
            )
        ).first()
        if clash:
            raise ProblemError("validation_failed", 409, errors=[svc._slug_taken()])
    for k in ("slug", "visibility", "is_free", "course_kind"):
        if k in data and data[k] is not None:
            setattr(course, k, data.pop(k))
        else:
            data.pop(k, None)
    for k, v in data.items():
        if k in ("certificate_rule", "completeness_plan"):
            setattr(draft, k, v)  # already dicts (model_dump)
        elif k in ("outcomes", "tags"):
            setattr(draft, k, list(v or []))
        elif v is not None or k in ("summary", "description_md", "level", "category"):
            setattr(draft, k, v)
    svc.touch_draft(draft)
    await session.flush()
    if before:
        await audit(
            session,
            principal,
            "course.settings_change",
            "course",
            course.id,
            organization_id=course.organization_id,
            before=before,
            after={k: getattr(course, k) for k in before},
        )
    return await svc.version_out(session, draft)


@studio.put(
    "/courses/{course_id}/draft/outline",
    operation_id="cat_12_put_outline",
    dependencies=[_perm("course.edit", CourseScope)],
)
async def put_outline(
    course_id: uuid.UUID,
    body: OutlineIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    course = await svc.get_course(session, course_id)
    draft = await svc.ensure_draft(session, course, principal)
    await svc.replace_outline(session, course, draft, [m.model_dump() for m in body.modules])
    await audit(
        session,
        principal,
        "course.outline.replace",
        "course_version",
        draft.id,
        organization_id=course.organization_id,
        after={"course_id": course.id, "modules": len(body.modules)},
    )
    return await svc.version_out(session, draft)


@studio.post(
    "/courses/{course_id}/draft/lessons",
    status_code=201,
    operation_id="cat_13_add_lesson",
    dependencies=[_perm("course.edit", CourseScope)],
)
async def add_lesson(
    request: Request,
    course_id: uuid.UUID,
    body: LessonIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def op() -> IdemResult:
        course = await svc.get_course(session, course_id)
        draft = await svc.ensure_draft(session, course, principal)
        values = body.model_dump(exclude={"module_key", "module_title"}, exclude_none=True)
        lesson = await svc.add_lesson(
            session, course, draft, module_key=body.module_key, module_title=body.module_title, values=values
        )
        await audit(
            session,
            principal,
            "course.lesson.add",
            "lesson",
            lesson.id,
            organization_id=course.organization_id,
            after={"course_id": course.id, "lesson_type": lesson.lesson_type, "title": lesson.title},
        )
        return IdemResult(svc.lesson_out(lesson, topics=[]), 201, lesson.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


async def _lesson_perm(
    request: Request, session: Any, principal: Principal, lesson_id: uuid.UUID, perm: str
) -> uuid.UUID:
    course_id, _org = await svc.lesson_scope(session, principal, lesson_id)
    await svc.ensure_permission(request, session, principal, perm, ScopeRef("course", course_id))
    return course_id


@studio.patch("/lessons/{lesson_id}", operation_id="cat_14_patch_lesson")
async def patch_lesson(
    request: Request,
    lesson_id: uuid.UUID,
    body: LessonPatch,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    course_id = await _lesson_perm(request, session, principal, lesson_id, "course.edit")
    lesson, version = await svc.editable_lesson(session, lesson_id)
    data = body.model_dump(exclude_unset=True)
    merged = {
        k: data.get(k, getattr(lesson, k))
        for k in ("test_id", "coding_problem_id", "assignment_id", "live_url")
    }
    svc.check_lesson_refs(lesson.lesson_type, merged)
    for k, v in data.items():
        if k in ("is_required", "is_free_preview", "title") and v is None:
            continue
        setattr(lesson, k, v)
    svc.touch_draft(version)
    await session.flush()
    await audit(
        session,
        principal,
        "course.lesson.edit",
        "lesson",
        lesson.id,
        organization_id=lesson.organization_id,
        after={"course_id": course_id, "fields": sorted(data)},
    )
    assets = (await session.execute(select(LessonAsset).where(LessonAsset.lesson_id == lesson.id))).scalars()
    topics = (await svc.lesson_topics_map(session, [lesson.id]))[lesson.id]
    return svc.lesson_out(lesson, list(assets), topics=topics)


@studio.put("/lessons/{lesson_id}/topics", operation_id="cat_15_lesson_topics")
async def put_topics(
    request: Request,
    lesson_id: uuid.UUID,
    body: TopicsIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    course_id = await _lesson_perm(request, session, principal, lesson_id, "course.edit")
    lesson, version = await svc.editable_lesson(session, lesson_id)
    await svc.set_lesson_topics(session, lesson, [t.model_dump() for t in body.topics])
    svc.touch_draft(version)
    await audit(
        session,
        principal,
        "course.lesson.topics",
        "lesson",
        lesson.id,
        organization_id=lesson.organization_id,
        after={"course_id": course_id, "topics": [str(t.topic_id) for t in body.topics]},
    )
    return {"lesson_id": str(lesson.id), "topics": [t.model_dump(mode="json") for t in body.topics]}


@studio.post(
    "/courses/{course_id}/submit-review",
    operation_id="cat_16_submit_review",
    dependencies=[_perm("course.edit", CourseScope)],
)
async def submit_review(
    course_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    course = await svc.get_course(session, course_id)
    version = await svc.submit_review(session, course, principal)
    await audit(
        session,
        principal,
        "course.submit_review",
        "course_version",
        version.id,
        organization_id=course.organization_id,
        after={"course_id": course.id, "version_no": version.version_no},
    )
    return svc.version_meta(version)


@studio.post("/courses/{course_id}/publish", operation_id="cat_17_publish")
async def publish(
    request: Request,
    course_id: uuid.UUID,
    body: PublishIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    # course.publish @P, or @O for org-private courses (course scope chain includes the org).
    await svc.ensure_permission(request, session, principal, "course.publish", ScopeRef("course", course_id))

    async def op() -> IdemResult:
        course = await svc.get_course(session, course_id)
        version = await svc.publish(
            session, course, principal, change_type=body.change_type, changelog=body.changelog
        )
        await audit(
            session,
            principal,
            "course.publish",
            "course_version",
            version.id,
            organization_id=course.organization_id,
            after={
                "course_id": course.id,
                "version_no": version.version_no,
                "change_type": version.change_type,
            },
        )
        await emit_event(
            session,
            "course.published",
            {
                "course_id": str(course.id),
                "course_version_id": str(version.id),
                "version_no": version.version_no,
                "change_type": version.change_type,
                "organization_id": str(course.organization_id) if course.organization_id else None,
            },
            aggregate_type="course",
            aggregate_id=course.id,
            organization_id=course.organization_id,
        )
        return IdemResult(
            {"course": svc.course_out(course), "version": svc.version_meta(version)}, 200, version.id
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@studio.post("/courses/{course_id}/archive", operation_id="cat_18_archive")
async def archive(
    request: Request,
    course_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    await svc.ensure_permission(request, session, principal, "course.archive", ScopeRef("course", course_id))
    course = await svc.get_course(session, course_id)
    if course.status == "archived":
        raise ProblemError("invalid_state_transition", detail="Course is already archived.")
    before = course.status
    course.status = "archived"
    await session.flush()
    await audit(
        session,
        principal,
        "course.archive",
        "course",
        course.id,
        organization_id=course.organization_id,
        before={"status": before},
        after={"status": "archived"},
    )
    await emit_event(
        session,
        "course.archived",
        {"course_id": str(course.id)},
        aggregate_type="course",
        aggregate_id=course.id,
        organization_id=course.organization_id,
    )
    return svc.course_out(course)


@studio.get(
    "/courses/{course_id}/versions",
    operation_id="cat_19_versions",
    dependencies=[_perm("course.edit", CourseScope)],
    openapi_extra={"x-td-idle": "neutral"},
)
async def versions(course_id: uuid.UUID, session: PrincipalDbSession) -> dict[str, Any]:
    await svc.get_course(session, course_id)
    rows = (
        await session.execute(
            select(CourseVersion)
            .where(CourseVersion.course_id == course_id)
            .order_by(CourseVersion.version_no.desc())
        )
    ).scalars()
    return {"data": [svc.version_meta(v) for v in rows], "page": page_meta(None, MAX_LIMIT)}


@studio.get(
    "/lessons/{lesson_id}/preview", operation_id="cat_20_preview", openapi_extra={"x-td-idle": "neutral"}
)
async def preview(
    request: Request,
    lesson_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    await _lesson_perm(request, session, principal, lesson_id, "course.preview")
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise ProblemError("not_found")
    assets = (await session.execute(select(LessonAsset).where(LessonAsset.lesson_id == lesson.id))).scalars()
    topics = (await svc.lesson_topics_map(session, [lesson.id]))[lesson.id]
    return {
        "banner": "Preview — not visible to students",
        "lesson": svc.lesson_out(lesson, list(assets), topics=topics),
    }


# =========================================================================== studio: resources


def _resource_out(r: Resource) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "title": r.title,
        "resource_type": r.resource_type,
        "access_level": r.access_level,
        "course_id": str(r.course_id) if r.course_id else None,
        "lesson_id": str(r.lesson_id) if r.lesson_id else None,
        "company_id": str(r.company_id) if r.company_id else None,
        "organization_id": str(r.organization_id) if r.organization_id else None,
        "has_file": r.s3_key is not None,
        "url": r.url,
    }


def _check_resource_key(key: str | None) -> None:
    if key is not None and not key.startswith("content/resource_file/"):
        raise svc.vf(
            "s3_key", "invalid", "Use a key issued by POST /media/uploads/file (purpose resource_file)"
        )


@studio.get("/resources", operation_id="cat_21b_list_resources", openapi_extra={"x-td-idle": "neutral"})
async def list_resources(
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    course_id: uuid.UUID | None = None,
    lesson_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Read side of CAT-21/22 (webstaff request 8): the resources of a course, a lesson or a
    company hub, newest first. Same permission as creating them (``resource.manage`` @C, or
    @P for company resources)."""
    limit = _limit(limit)
    if lesson_id is not None:
        lc, _ = await svc.lesson_scope(session, principal, lesson_id)
        if course_id is not None and course_id != lc:
            raise svc.vf("lesson_id", "mismatch", "Lesson is not part of the course")
        course_id = lc
    if course_id is None and company_id is None:
        raise svc.vf("course_id", "required", "Give a course_id, lesson_id or company_id")
    scope = ScopeRef("course", course_id) if course_id else PLATFORM_SCOPE
    await svc.ensure_permission(request, session, principal, "resource.manage", scope)
    conds: list[Any] = []
    if course_id is not None:
        conds.append(Resource.course_id == course_id)
    if lesson_id is not None:
        conds.append(Resource.lesson_id == lesson_id)
    if company_id is not None:
        conds.append(Resource.company_id == company_id)
    if cursor:
        try:
            conds.append(Resource.id < uuid.UUID(str(decode_cursor(cursor)["id"])))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
    rows = list(
        (
            await session.execute(
                select(Resource).where(*conds).order_by(Resource.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    nxt = {"id": str(rows[-1].id)} if more and rows else None
    return {"data": [_resource_out(r) for r in rows], "page": page_meta(nxt, limit)}


@studio.post("/resources", status_code=201, operation_id="cat_21_create_resource")
async def create_resource(
    request: Request,
    body: ResourceIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    _check_resource_key(body.s3_key)
    if not (body.s3_key or body.url):
        raise svc.vf("s3_key", "required", "A file key or an https URL is required")
    course_id = body.course_id
    if body.lesson_id is not None:
        lc, _ = await svc.lesson_scope(session, principal, body.lesson_id)
        if course_id is not None and course_id != lc:
            raise svc.vf("lesson_id", "mismatch", "Lesson is not part of the course")
        course_id = lc
    if course_id is None and body.company_id is None:
        raise svc.vf("course_id", "required", "Attach the resource to a course, lesson or company")
    scope = ScopeRef("course", course_id) if course_id else PLATFORM_SCOPE
    await svc.ensure_permission(request, session, principal, "resource.manage", scope)
    org = None
    if course_id is not None:
        org = (await svc.get_course(session, course_id)).organization_id

    async def op() -> IdemResult:
        r = Resource(
            id=uuid7(),
            organization_id=org,
            course_id=course_id,
            lesson_id=body.lesson_id,
            company_id=body.company_id,
            title=body.title,
            resource_type=body.resource_type,
            access_level=body.access_level,
            is_public=body.access_level == "public",
            s3_key=body.s3_key,
            url=body.url,
            created_by=principal.user_id,
        )
        session.add(r)
        await session.flush()
        return IdemResult(_resource_out(r), 201, r.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@studio.patch("/resources/{resource_id}", operation_id="cat_22_patch_resource")
async def patch_resource(
    request: Request,
    resource_id: uuid.UUID,
    body: ResourcePatch,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    row = await svc.system_lookup(
        session,
        principal,
        select(Resource.course_id, Resource.organization_id).where(Resource.id == resource_id),
    )
    if row is None:
        raise ProblemError("not_found")
    scope = ScopeRef("course", row[0]) if row[0] else PLATFORM_SCOPE
    await svc.ensure_permission(request, session, principal, "resource.manage", scope)
    r = await session.get(Resource, resource_id)
    if r is None:
        raise ProblemError("not_found")
    data = body.model_dump(exclude_unset=True)
    _check_resource_key(data.get("s3_key"))
    for k, v in data.items():
        if k in ("title", "access_level") and v is None:
            continue
        setattr(r, k, v)
    r.is_public = r.access_level == "public"
    if not (r.s3_key or r.url):
        raise svc.vf("s3_key", "required", "A file key or an https URL is required")
    await session.flush()
    return _resource_out(r)


# The course:{id} scope chain includes the owning organization (role matrix §1.2).
def _register_hooks() -> None:
    from app.modules.rbac.service import register_course_org_lookup

    register_course_org_lookup(svc.course_org_lookup)


_register_hooks()

router = APIRouter()
for _r in (pub, studio):
    router.include_router(_r)
