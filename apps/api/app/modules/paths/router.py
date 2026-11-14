"""Guided learning paths API (docs/wiseman-reference/build/paths.md).

Single company (REMOVAL-PLAN §6 WS4): no organization is ever taken from the request; every
path and article belongs to the company org. ``extra="forbid"`` bodies reject ``organization_id``.

Staff (``path.manage`` / ``path.allocate``, checked in-handler):
  GET  /paths/context                         can_author, can_allocate_any_learner, batches
  GET  /paths | POST /paths                   list / create (Idempotency-Key optional)
  GET|PATCH|DELETE /paths/{id}                detail / edit / archive
  PUT  /paths/{id}/steps                      replace the draft step tree (add, delete, reorder)
  POST /paths/{id}/publish                    new immutable version
  POST /paths/ai-generate                     AI draft (ai.generate_path) -> editable draft path
  GET  /paths/link-options | /paths/batch-members?batch_id=   editor / allocate pickers
  POST /paths/{id}/allocation-preview         study plan preview (server-computed)
  POST /paths/{id}/allocations                allocate (path.allocate)
  GET  /path-allocations/{id}/progress | DELETE /path-allocations/{id}
  GET|POST /path-articles, GET|PATCH|DELETE /path-articles/{id}, POST .../publish | .../unpublish
Learner / reader:
  GET  /me/paths, GET /me/paths/{allocation_id}
  POST /me/paths/{allocation_id}/steps/{step_key}/open | /complete
  GET  /read/{article_id}
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import require_active_principal
from app.core.db import PrincipalDbSession
from app.core.idempotency import IdemResult, idempotent
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.modules.paths import service as svc

CurrentPrincipal = Annotated[Principal, Depends(require_active_principal)]
Level = Literal["beginner", "intermediate", "advanced"]
StepType = Literal["reading", "video", "article", "assignment", "assessment", "super_step"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathIn(Strict):
    title: str = Field(min_length=1, max_length=200)
    description_md: str = Field(default="", max_length=5000)
    level: Level = "beginner"


class PathPatch(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description_md: str | None = Field(default=None, max_length=5000)
    level: Level | None = None


class StepIn(Strict):
    step_key: uuid.UUID | None = None
    step_type: StepType
    title: str = Field(min_length=1, max_length=300)
    description_md: str = Field(default="", max_length=5000)
    est_hours: Decimal = Field(default=Decimal("0"), ge=0, le=1000)
    credits: int = Field(default=0, ge=0, le=10000)
    url: str | None = Field(default=None, max_length=2048)
    lesson_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    test_id: uuid.UUID | None = None
    article_id: uuid.UUID | None = None
    children: list[StepIn] = Field(default_factory=list, max_length=100)


class StepsIn(Strict):
    steps: list[StepIn] = Field(max_length=200)


class AiPathIn(Strict):
    topic: str = Field(min_length=2, max_length=200)
    style: Literal["mixed", "textbook"] = "mixed"
    level: Level = "beginner"
    target_hours: int = Field(ge=1, le=500)
    approx_steps: int = Field(ge=1, le=60)
    guidelines: str | None = Field(default=None, max_length=4000)


class PerDay(Strict):
    mon: float = Field(default=0, ge=0, le=24)
    tue: float = Field(default=0, ge=0, le=24)
    wed: float = Field(default=0, ge=0, le=24)
    thu: float = Field(default=0, ge=0, le=24)
    fri: float = Field(default=0, ge=0, le=24)
    sat: float = Field(default=0, ge=0, le=24)
    sun: float = Field(default=0, ge=0, le=24)


class PaceIn(Strict):
    mode: Literal["every_day", "weekdays", "weekends", "weekdays_weekends", "custom"] = "every_day"
    hours_per_day: float | None = Field(default=None, ge=0, le=24)
    weekend_hours: float | None = Field(default=None, ge=0, le=24)
    per_day: PerDay | None = None


class AllocIn(Strict):
    target_type: Literal["batch", "users"] = "batch"
    batch_id: uuid.UUID | None = None
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    flow: Literal["lenient", "strict"] = "lenient"
    sequential: bool = False
    start_date: date | None = None
    pace: PaceIn = Field(default_factory=PaceIn)


class ArticleIn(Strict):
    title: str = Field(min_length=1, max_length=200)
    subtitle: str = Field(default="", max_length=500)
    level: Level = "beginner"
    est_minutes: int = Field(default=0, ge=0, le=6000)
    body_md: str = Field(default="", max_length=200_000)


class ArticlePatch(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, max_length=500)
    level: Level | None = None
    est_minutes: int | None = Field(default=None, ge=0, le=6000)
    body_md: str | None = Field(default=None, max_length=200_000)


class PublishIn(Strict):
    audience: Literal["batches", "people"]
    batch_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


def _pace(p: PaceIn) -> dict[str, Any]:
    out: dict[str, Any] = {"mode": p.mode}
    if p.hours_per_day is not None:
        out["hours_per_day"] = p.hours_per_day
    if p.weekend_hours is not None:
        out["weekend_hours"] = p.weekend_hours
    if p.per_day is not None:
        out["per_day"] = p.per_day.model_dump()
    return out


def _alloc_body(b: AllocIn) -> dict[str, Any]:
    d = b.model_dump(exclude={"pace"})
    d["pace"] = _pace(b.pace)
    return d


staff = authenticated_router(tags=["paths"])
learner = authenticated_router(tags=["paths-learner"])


# --------------------------------------------------------------------------- staff: paths


@staff.get("/paths/context")
async def paths_context(
    request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.staff_context(request, session, principal)


@staff.get("/paths")
async def list_paths(
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Literal["draft", "published", "archived"] | None = None,
) -> dict[str, Any]:
    return await svc.list_paths(request, session, principal, q=q, status=status)


@staff.post("/paths", status_code=201)
async def create_path(
    body: PathIn, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> JSONResponse:
    async def op() -> IdemResult:
        p = await svc.create_path(
            request,
            session,
            principal,
            title=body.title,
            description_md=body.description_md,
            level=body.level,
        )
        return IdemResult(await svc.path_detail(session, p), 201, p.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@staff.post("/paths/ai-generate", status_code=201)
async def ai_generate(
    body: AiPathIn, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> JSONResponse:
    async def op() -> IdemResult:
        p = await svc.ai_generate(request, session, principal, body.model_dump())
        return IdemResult(await svc.path_detail(session, p), 201, p.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@staff.get("/paths/link-options")
async def link_options(
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    kind: Literal["assignment", "test", "article", "lesson"],
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    return await svc.link_options(request, session, principal, kind, q)


@staff.get("/paths/batch-members")
async def batch_members(
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    batch_id: uuid.UUID,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    return await svc.batch_members(request, session, principal, batch_id, q)


@staff.get("/paths/{path_id}")
async def get_path(
    path_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    p = await svc.managed_path(request, session, principal, path_id)
    return await svc.path_detail(session, p)


@staff.patch("/paths/{path_id}")
async def patch_path(
    path_id: uuid.UUID,
    body: PathPatch,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    p = await svc.managed_path(request, session, principal, path_id)
    await svc.update_path(session, principal, p, body.model_dump())
    return await svc.path_detail(session, p)


@staff.delete("/paths/{path_id}", status_code=204)
async def archive_path(
    path_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> Response:
    p = await svc.managed_path(request, session, principal, path_id)
    await svc.archive_path(session, principal, p, request)
    return Response(status_code=204)


@staff.put("/paths/{path_id}/steps")
async def put_steps(
    path_id: uuid.UUID,
    body: StepsIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    p = await svc.managed_path(request, session, principal, path_id)
    await svc.replace_steps(session, principal, p, [s.model_dump() for s in body.steps])
    return await svc.path_detail(session, p)


@staff.post("/paths/{path_id}/publish")
async def publish_path(
    path_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    p = await svc.managed_path(request, session, principal, path_id)
    await svc.publish_path(session, principal, p)
    return await svc.path_detail(session, p)


@staff.post("/paths/{path_id}/allocation-preview")
async def allocation_preview(
    path_id: uuid.UUID,
    body: AllocIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    p = await svc.get_path(session, path_id)
    await svc.require_author(request, principal, "path.allocate")
    return await svc.allocation_preview(session, p, _alloc_body(body))


@staff.post("/paths/{path_id}/allocations", status_code=201)
async def allocate(
    path_id: uuid.UUID,
    body: AllocIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> JSONResponse:
    async def op() -> IdemResult:
        p = await svc.get_path(session, path_id)
        a = await svc.create_allocation(request, session, principal, p, _alloc_body(body))
        return IdemResult(await svc.allocation_out(session, a), 201, a.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@staff.get("/path-allocations/{allocation_id}/progress")
async def allocation_progress(
    allocation_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    a = await svc.managed_allocation(request, session, principal, allocation_id)
    return await svc.allocation_progress(session, a, show_email=svc.shows_learner_email(principal))


@staff.delete("/path-allocations/{allocation_id}", status_code=204)
async def revoke_allocation(
    allocation_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> Response:
    a = await svc.managed_allocation(request, session, principal, allocation_id)
    await svc.revoke_allocation(session, principal, a)
    return Response(status_code=204)


# --------------------------------------------------------------------------- staff: articles


@staff.get("/path-articles")
async def list_articles(
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    return await svc.list_articles(request, session, principal, q)


@staff.post("/path-articles", status_code=201)
async def create_article(
    body: ArticleIn, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> JSONResponse:
    async def op() -> IdemResult:
        a = await svc.create_article(request, session, principal, body.model_dump())
        return IdemResult(svc.article_out(a, body=True), 201, a.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@staff.get("/path-articles/{article_id}")
async def get_article(
    article_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    a = await svc.managed_article(request, session, principal, article_id)
    return svc.article_out(a, body=True)


@staff.patch("/path-articles/{article_id}")
async def patch_article(
    article_id: uuid.UUID,
    body: ArticlePatch,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    a = await svc.managed_article(request, session, principal, article_id, change=True)
    await svc.update_article(session, principal, a, body.model_dump())
    return svc.article_out(a, body=True)


@staff.delete("/path-articles/{article_id}", status_code=204)
async def delete_article(
    article_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> Response:
    a = await svc.managed_article(request, session, principal, article_id, change=True)
    await svc.delete_article(session, principal, a)
    return Response(status_code=204)


@staff.post("/path-articles/{article_id}/publish")
async def publish_article(
    article_id: uuid.UUID,
    body: PublishIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    a = await svc.managed_article(request, session, principal, article_id, change=True)
    await svc.publish_article(request, session, principal, a, body.model_dump())
    return svc.article_out(a, body=True)


@staff.post("/path-articles/{article_id}/unpublish")
async def unpublish_article(
    article_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    a = await svc.managed_article(request, session, principal, article_id, change=True)
    await svc.unpublish_article(session, principal, a)
    return svc.article_out(a, body=True)


# --------------------------------------------------------------------------- learner / reader


@learner.get("/read/{article_id}")
async def read_article(
    article_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.read_article(request, session, principal, article_id)


@learner.get("/me/paths")
async def my_paths(session: PrincipalDbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    return await svc.my_paths(session, principal)


@learner.get("/me/paths/{allocation_id}")
async def my_path(
    allocation_id: uuid.UUID, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.player_view(session, principal, allocation_id)


@learner.post("/me/paths/{allocation_id}/steps/{step_key}/open")
async def open_step(
    allocation_id: uuid.UUID, step_key: uuid.UUID, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.open_step(session, principal, allocation_id, step_key)


@learner.post("/me/paths/{allocation_id}/steps/{step_key}/complete")
async def complete_step(
    allocation_id: uuid.UUID, step_key: uuid.UUID, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.complete_step(session, principal, allocation_id, step_key)


router = APIRouter()
for _r in (staff, learner):
    router.include_router(_r)
