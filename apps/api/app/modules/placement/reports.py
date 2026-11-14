"""Question error reports (api-specification §13.1 PLC-33..35; CMS-013 triage queue).

* PLC-33 ``POST /questions/{question_id}/reports`` — any active learner who can see the
  question (RLS) reports an error; one open report per user per question. The path id may be a
  question id or the ``question_version_id`` a learner sees in a practice session.
* PLC-34 ``GET /studio/question-reports`` — triage queue for holders of ``question.edit`` in
  the question's organization (platform bank: platform scope). Rows are filtered per scope.
* PLC-35 ``POST /studio/question-reports/{report_id}/resolve`` — resolution + note; the
  reporter gets an in-app notification (notifications module public service).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, ScopeRef, require_active_principal
from app.core.db import PrincipalDbSession, system_context, tenant_context
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339, utcnow
from app.modules.placement.models import Question, QuestionReport
from app.modules.placement.policies import can_in_org, has_permission
from app.modules.placement.rls import bind_principal, no_postgres

reports = authenticated_router(tags=["placement"], dependencies=[Depends(bind_principal)])

Category = Literal["wrong_answer", "wrong_explanation", "typo", "unclear", "other"]
Resolution = Literal["fixed", "no_change", "duplicate", "invalid"]


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    message: str = Field(min_length=1, max_length=1000)
    question_version_id: uuid.UUID | None = None


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: Resolution
    note: str | None = Field(default=None, max_length=1000)


def _nopg(session: Any) -> Any:
    """The request session, or ``None`` without Postgres (``db.NO_POSTGRES`` is falsy): core
    ``idempotent`` then keeps no Postgres savepoint (it checks ``session is not None``)."""
    return session or None


def report_out(r: QuestionReport) -> dict[str, Any]:
    return {
        "report_id": str(r.id),
        "question_id": str(r.question_id),
        "question_version_id": str(r.question_version_id) if r.question_version_id else None,
        "organization_id": str(r.organization_id) if r.organization_id else None,
        "category": r.category,
        "message": r.message,
        "status": r.status,
        "resolution": r.resolution,
        "resolution_note": r.resolution_note,
        "reporter_user_id": str(r.user_id),
        "created_at": to_rfc3339(r.created_at),
        "resolved_at": to_rfc3339(r.resolved_at) if r.resolved_at else None,
        "resolved_by": str(r.resolved_by) if r.resolved_by else None,
    }


def _fs() -> bool:
    from app.modules.placement.bank import _fs as bank_fs

    return bank_fs()


async def _repo(session: AsyncSession) -> Any:
    from app.modules.placement.bank import _repo as bank_repo

    return await bank_repo(session)


async def _fs_queue(
    session: AsyncSession,
    allowed: Callable[[uuid.UUID | None], Awaitable[bool]],
    status: str | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    """``plc_34_report_queue`` on Firestore: same filters, id-descending keyset, same cursor."""
    rows = await (await _repo(session)).visible_reports()
    ok_orgs = [o for o in dict.fromkeys(r.organization_id for r in rows) if await allowed(o)]
    if not ok_orgs:
        return {"data": [], "meta": page_meta(None, limit), "open_count": 0}
    scoped = [r for r in rows if r.organization_id in ok_orgs]
    picked = [r for r in scoped if status is None or r.status == status]
    if cursor:
        try:
            after = uuid.UUID(str(decode_cursor(cursor)["id"]))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
        picked = [r for r in picked if r.id < after]
    picked.sort(key=lambda r: r.id, reverse=True)
    more = len(picked) > limit
    picked = picked[:limit]
    return {
        "data": [report_out(r) for r in picked],
        "meta": page_meta({"id": str(picked[-1].id)} if more and picked else None, limit),
        "open_count": sum(1 for r in scoped if r.status == "open"),
    }


async def _resolve_target(
    session: AsyncSession, path_id: uuid.UUID, version_id: uuid.UUID | None
) -> tuple[Question, uuid.UUID | None]:
    """Question visible to the caller (RLS) that has been published at least once."""
    from app.modules.placement import public

    q = await public.get_question(session, path_id)
    if q is None:
        qv = await public.get_version(session, path_id)
        if qv is not None:
            q = await public.get_question(session, qv.question_id)
            version_id = version_id or qv.id
    if q is None or q.deleted_at is not None or q.current_version_id is None:
        raise ProblemError("not_found")
    if version_id is not None:
        qv = await public.get_version(session, version_id)
        if qv is None or qv.question_id != q.id:
            raise ProblemError("not_found")
    return q, version_id


@reports.post("/questions/{question_id}/reports", status_code=201)
async def plc_33_report_question(
    request: Request,
    question_id: uuid.UUID,
    body: ReportIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    q, version_id = await _resolve_target(session, question_id, body.question_version_id)
    message = body.message.strip()
    if not message:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "message", "code": "required", "message": "Describe the problem."}],
        )

    async def op() -> IdemResult:
        if _fs():
            now = utcnow()
            fr = QuestionReport(
                id=uuid7(),
                question_id=q.id,
                question_version_id=version_id,
                organization_id=q.organization_id,
                user_id=principal.user_id,
                category=body.category,
                message=message,
                status="open",
                resolution=None,
                resolution_note=None,
                resolved_by=None,
                resolved_at=None,
                created_at=now,
                updated_at=now,
            )
            await (await _repo(session)).create_report(principal.user_id, fr)
            return IdemResult(body=report_out(fr), status=201, resource_id=fr.id)
        open_dup = (
            await session.execute(
                select(QuestionReport.id).where(
                    QuestionReport.user_id == principal.user_id,
                    QuestionReport.question_id == q.id,
                    QuestionReport.status == "open",
                )
            )
        ).first()
        if open_dup is not None:
            raise ProblemError(
                "invalid_state_transition",
                detail="You already reported this question; we're looking into it.",
                reason="report_already_open",
                report_id=str(open_dup[0]),
            )
        r = QuestionReport(
            id=uuid7(),
            question_id=q.id,
            question_version_id=version_id,
            organization_id=q.organization_id,
            user_id=principal.user_id,
            category=body.category,
            message=message,
            status="open",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(r)
        await session.flush()
        return IdemResult(body=report_out(r), status=201, resource_id=r.id)

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


async def _edits_anything(request: Request, principal: Principal) -> bool:
    scopes = [PLATFORM_SCOPE, *(ScopeRef("organization", o) for o in principal.org_ids)]
    scopes += [
        ScopeRef("batch", g.scope_id) for g in principal.grants if g.scope_type == "batch" and g.scope_id
    ]
    for s in scopes:
        if await has_permission(request, principal, "question.edit", s):
            return True
    return False


def _allowed_cache(
    request: Request, session: AsyncSession, principal: Principal
) -> Callable[[uuid.UUID | None], Awaitable[bool]]:
    cache: dict[uuid.UUID | None, bool] = {}

    async def allowed(org: uuid.UUID | None) -> bool:
        if org not in cache:
            cache[org] = await can_in_org(request, session, principal, "question.edit", org)
        return cache[org]

    return allowed


@reports.get("/studio/question-reports", openapi_extra={"x-td-idle": "neutral"})
async def plc_34_report_queue(
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    status: Annotated[Literal["open", "resolved"] | None, Query()] = "open",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    if not await _edits_anything(request, principal):
        raise ProblemError("permission_denied", permission="question.edit")
    allowed = _allowed_cache(request, session, principal)
    if _fs():
        return await _fs_queue(session, allowed, status, cursor, limit)
    # RLS U already limits rows to the caller's organizations (+ everything for platform staff)
    # and their own reports; keep only scopes where the caller holds question.edit.
    orgs = list((await session.execute(select(QuestionReport.organization_id).distinct())).scalars())
    ok_orgs = [o for o in orgs if await allowed(o)]
    if not ok_orgs:
        return {"data": [], "meta": page_meta(None, limit), "open_count": 0}
    org_filter: ColumnElement[bool] = QuestionReport.organization_id.in_(
        [o for o in ok_orgs if o is not None]
    )
    if None in ok_orgs:
        org_filter = org_filter | QuestionReport.organization_id.is_(None)
    q = select(QuestionReport).where(org_filter)
    if status is not None:
        q = q.where(QuestionReport.status == status)
    if cursor:
        try:
            q = q.where(QuestionReport.id < uuid.UUID(str(decode_cursor(cursor)["id"])))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
    rows = list((await session.execute(q.order_by(QuestionReport.id.desc()).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    open_count = (
        await session.execute(
            select(func.count())
            .select_from(QuestionReport)
            .where(org_filter, QuestionReport.status == "open")
        )
    ).scalar_one()
    return {
        "data": [report_out(r) for r in rows],
        "meta": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit),
        "open_count": int(open_count),
    }


@reports.post("/studio/question-reports/{report_id}/resolve")
async def plc_35_resolve_report(
    request: Request,
    report_id: uuid.UUID,
    body: ResolveIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    r = (
        await (await _repo(session)).get_report(report_id)
        if _fs()
        else await session.get(QuestionReport, report_id)
    )
    if r is None:
        raise ProblemError("not_found")
    if not await can_in_org(request, session, principal, "question.edit", r.organization_id):
        # The reporter can see their own row under RLS; never reveal it to non-editors.
        if r.user_id == principal.user_id:
            raise ProblemError("permission_denied", permission="question.edit")
        raise ProblemError("not_found")

    async def op() -> IdemResult:
        now = utcnow()
        if _fs():
            row = await (await _repo(session)).resolve_report(
                report_id,
                {
                    "status": "resolved",
                    "resolution": body.resolution,
                    "resolution_note": (body.note or "").strip() or None,
                    "resolved_by": principal.user_id,
                    "resolved_at": now,
                },
            )
        else:
            row = (
                await session.execute(
                    select(QuestionReport).where(QuestionReport.id == report_id).with_for_update()
                )
            ).scalar_one()
            if row.status != "open":
                raise ProblemError("invalid_state_transition", detail="This report is already resolved.")
            row.status = "resolved"
            row.resolution = body.resolution
            row.resolution_note = (body.note or "").strip() or None
            row.resolved_by = principal.user_id
            row.resolved_at = now
            row.updated_at = now
            await session.flush()
        await audit(
            session,
            principal,
            "question.report_resolved",
            "question_report",
            row.id,
            organization_id=row.organization_id,
            after={"question_id": str(row.question_id), "resolution": row.resolution},
        )
        await _notify_reporter(session, principal, row)
        return IdemResult(body=report_out(row), status=200, resource_id=row.id)

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


async def _notify_reporter(session: AsyncSession, principal: Principal, r: QuestionReport) -> None:
    from app.modules.notifications.service import notify

    if no_postgres(session):  # no Postgres: notifications writes through its own Firestore repository
        await notify(
            session,
            r.user_id,
            "placement.question_report_resolved",
            category="learning",
            data={
                "report_id": str(r.id),
                "question_id": str(r.question_id),
                "resolution": r.resolution,
                "note": r.resolution_note,
            },
            channels=("in_app",),
            organization_id=r.organization_id,
            dedupe_key=f"question_report_resolved:{r.id}",
        )
        return
    await system_context(session, "placement.question_report_resolved")  # write another user's inbox
    try:
        await notify(
            session,
            r.user_id,
            "placement.question_report_resolved",
            category="learning",
            data={
                "report_id": str(r.id),
                "question_id": str(r.question_id),
                "resolution": r.resolution,
                "note": r.resolution_note,
            },
            channels=("in_app",),
            organization_id=r.organization_id,
            dedupe_key=f"question_report_resolved:{r.id}",
        )
    finally:
        await tenant_context(session, principal)
