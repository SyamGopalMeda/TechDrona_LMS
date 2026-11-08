"""Placement preparation API (api-specification §13, PLC-01..11, 16..27, 32, 33..35 in ``reports.py``).

Mentor-facing reads (PLC-46, assigned-students list) are in ``mentoring.py``; mentoring
bookings/slots/feedback (PLC-36..45) and résumés (PLC-47..52) are served by the
``app.modules.mentoring`` module.

Not implemented in this stage (no tables/owner decision yet): question imports (PLC-12..14),
item stats (PLC-15), goals/learning path (PLC-28..31).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, require_active_principal, require_permission
from app.core.db import DbSession, PrincipalDbSession
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.principal import Principal
from app.core.routing import authenticated_router, public_router
from app.modules.placement import bank, practice
from app.modules.placement.mentoring import mentor
from app.modules.placement.policies import (
    batch_org,
    can_in_org,
    has_permission,
    require_in_org,
    resolve_owner,
)
from app.modules.placement.qbank_router import qbank_media, qbank_studio
from app.modules.placement.reports import reports
from app.modules.placement.schemas import (
    CompanyCreate,
    CompanyPathPut,
    PracticeAnswer,
    PracticeStart,
    QuestionContent,
    QuestionCreate,
    RetireIn,
    RevealIn,
    ReviewIn,
    TopicCreate,
    TopicPatch,
)

pub = public_router(tags=["placement"])
studio = authenticated_router(prefix="/studio", tags=["placement-studio"])
dflt = authenticated_router(tags=["placement"])
l3r = authenticated_router(tags=["placement"], route_tag="l3_readonly")

Op = Callable[[], Awaitable[Any]]


async def _idem(
    request: Request,
    session: Any,
    principal: Principal,
    fn: Op,
    *,
    required: bool,
    status: int = 200,
) -> JSONResponse:
    async def op() -> IdemResult:
        return IdemResult(body=await fn(), status=status)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=required)


# --------------------------------------------------------------------------- taxonomy


@pub.get("/placement/subjects")
async def plc_01_subjects(session: DbSession) -> dict[str, Any]:
    return {"items": await bank.subject_tree(session)}


@studio.post("/topics", status_code=201)
async def plc_02_create_topic(
    request: Request,
    body: TopicCreate,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("taxonomy.manage")),
) -> JSONResponse:
    async def fn() -> dict[str, Any]:
        t = await bank.create_topic(session, body)
        await audit(session, principal, "taxonomy.topic_created", "topic", t.id, after={"path": t.path})
        return bank.topic_out(t)

    return await _idem(request, session, principal, fn, required=False, status=201)


@studio.get("/topics", openapi_extra={"x-td-idle": "neutral"})
async def plc_02b_list_topics(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("taxonomy.manage")),
) -> dict[str, Any]:
    """Studio taxonomy tree including deactivated nodes (PLC-01 shows active ones only), so
    taxonomy managers can find and reactivate them through PLC-03."""
    return {"items": await bank.subject_tree(session, include_inactive=True)}


@studio.patch("/topics/{topic_id}")
async def plc_03_patch_topic(
    topic_id: uuid.UUID,
    body: TopicPatch,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("taxonomy.manage")),
) -> dict[str, Any]:
    before = bank.topic_out(await bank.get_topic(session, topic_id))
    t, dependents = await bank.patch_topic(session, topic_id, body)
    after = bank.topic_out(t)
    await audit(session, principal, "taxonomy.topic_changed", "topic", t.id, before=before, after=after)
    return {**after, "dependent_question_count": dependents}


# --------------------------------------------------------------------------- question bank


async def _bank_orgs(
    request: Request, session: Any, principal: Principal, permission: str
) -> list[uuid.UUID | None]:
    """Banks (None = platform) the principal can list. Batch-scoped grants (trainers) count for
    the batch's organization, consistent with ``can_in_org`` (audit ADM-41)."""
    orgs: list[uuid.UUID | None] = []
    if await has_permission(request, principal, permission, PLATFORM_SCOPE):
        orgs.append(None)
    candidates = list(principal.org_ids)
    for g in principal.grants:
        if g.scope_type == "batch" and g.scope_id is not None:
            org = await batch_org(session, g.scope_id)
            if org is not None and org not in candidates:
                candidates.append(org)
    for o in candidates:
        if await can_in_org(request, session, principal, permission, o):
            orgs.append(o)
    if not orgs:
        raise ProblemError("permission_denied", permission=permission)
    return orgs


@studio.get("/questions")
async def plc_04_search_questions(
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    topic_id: uuid.UUID | None = None,
    difficulty: int | None = Query(default=None, ge=1, le=5),
    status: str | None = Query(default=None, pattern="^(draft|active|retired)$"),
    version_status: str | None = Query(
        default=None, pattern="^(draft|in_review|awaiting_review|approved|published|retired)$"
    ),
    company_id: uuid.UUID | None = None,
    tag: str | None = Query(default=None, max_length=120),
    author: uuid.UUID | None = None,
    q: str | None = Query(default=None, min_length=2, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    orgs = await _bank_orgs(request, session, principal, "question.create")
    items = await bank.search_questions(
        session,
        topic_id=topic_id,
        difficulty=difficulty,
        status=status,
        company_id=company_id,
        tag=tag,
        author=author,
        organization_ids=orgs,
        limit=limit,
        offset=offset,
        version_status=version_status,
        text_query=q,
    )
    return {"items": items, "limit": limit, "offset": offset}


@studio.post("/questions", status_code=201)
async def plc_05_create_question(
    request: Request,
    body: QuestionCreate,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    body.organization_id = await resolve_owner(
        request, session, principal, "question.create", body.organization_id
    )
    target = None
    if body.bank_id is not None:
        from app.modules.placement import banks

        target = await banks.get_bank(session, body.bank_id)
        if target.organization_id != body.organization_id:
            raise ProblemError(
                "validation_failed",
                errors=[{"field": "bank_id", "code": "invalid", "message": "bank belongs to another owner"}],
            )

    async def fn() -> dict[str, Any]:
        q, _qv = await bank.create_question(
            session, principal, body, default_topic_id=target.default_topic_id if target else None
        )
        if target is not None:
            from app.modules.placement import banks

            await banks.add_questions(session, principal, target, [q.id])
        await audit(
            session,
            principal,
            "question.created",
            "question",
            q.id,
            organization_id=q.organization_id,
            after={"bank_id": str(target.id)} if target else None,
        )
        return await bank.question_detail(session, q, include_keys=True)

    return await _idem(request, session, principal, fn, required=False, status=201)


async def _keys_visible(request: Request, session: Any, principal: Principal, q: Any) -> bool:
    versions = await bank.versions_of(session, q.id)
    if any(principal.user_id in (v.authored_by, v.reviewed_by) for v in versions):
        return True
    return await can_in_org(request, session, principal, "question.answer_key.read", q.organization_id)


@studio.get("/questions/{question_id}")
async def plc_06_get_question(
    request: Request,
    question_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    q = await bank.get_question(session, question_id)
    await require_in_org(request, session, principal, "question.edit", q.organization_id)
    return await bank.question_detail(
        session, q, include_keys=await _keys_visible(request, session, principal, q)
    )


@studio.post("/questions/{question_id}/versions")
async def plc_07_new_version(
    request: Request,
    question_id: uuid.UUID,
    body: QuestionContent,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    q = await bank.get_question(session, question_id)
    await require_in_org(request, session, principal, "question.edit", q.organization_id)

    async def fn() -> dict[str, Any]:
        qv = await bank.edit_question(session, principal, question_id, body)
        await audit(
            session,
            principal,
            "question.version_saved",
            "question",
            q.id,
            after={"version_no": qv.version_no},
        )
        return await bank.question_detail(session, q, include_keys=True)

    return await _idem(request, session, principal, fn, required=False)


async def _transition(
    request: Request,
    session: Any,
    principal: Principal,
    question_id: uuid.UUID,
    permission: str,
    action: str,
    fn: Callable[[], Awaitable[Any]],
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    q = await bank.get_question(session, question_id)
    await require_in_org(request, session, principal, permission, q.organization_id)

    async def run() -> dict[str, Any]:
        await fn()
        latest = await bank.latest_version(session, question_id)
        await audit(
            session,
            principal,
            action,
            "question",
            q.id,
            organization_id=q.organization_id,
            after={"version_no": latest.version_no, "status": latest.status, **(extra or {})},
        )
        return {
            "question_id": str(q.id),
            "status": q.status,
            "current_version_id": str(q.current_version_id) if q.current_version_id else None,
            "latest_version": {
                "version_no": latest.version_no,
                "status": latest.status,
                "reviewed": latest.reviewed_by is not None,
            },
        }

    return await _idem(request, session, principal, run, required=False)


@studio.post("/questions/{question_id}/submit-review")
async def plc_08_submit_review(
    request: Request,
    question_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    return await _transition(
        request,
        session,
        principal,
        question_id,
        "question.edit",
        "question.submitted_for_review",
        lambda: bank.submit_review(session, question_id),
    )


@studio.post("/questions/{question_id}/review")
async def plc_09_review(
    request: Request,
    question_id: uuid.UUID,
    body: ReviewIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    return await _transition(
        request,
        session,
        principal,
        question_id,
        "question.review",
        "question.review_approved" if body.decision == "approve" else "question.review_changes_requested",
        lambda: bank.review(session, principal, question_id, body.decision, body.comment),
        {"decision": body.decision, "comment": body.comment},
    )


@studio.post("/questions/{question_id}/publish")
async def plc_10_publish(
    request: Request,
    question_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    return await _transition(
        request,
        session,
        principal,
        question_id,
        "question.publish",
        "question.published",
        lambda: bank.publish(session, question_id, principal),
    )


@studio.post("/questions/{question_id}/retire")
async def plc_11_retire(
    request: Request,
    question_id: uuid.UUID,
    session: PrincipalDbSession,
    body: RetireIn | None = None,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    return await _transition(
        request,
        session,
        principal,
        question_id,
        "question.retire",
        "question.retired",
        lambda: bank.retire(session, question_id, body.reason if body else None),
        {"reason": body.reason if body else None},
    )


# --------------------------------------------------------------------------- companies


@studio.get("/companies")
async def plc_16_companies(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("company_path.manage")),
) -> dict[str, Any]:
    return {"items": await bank.list_companies(session)}


@studio.post("/companies", status_code=201)
async def plc_17_create_company(
    request: Request,
    body: CompanyCreate,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("company_path.manage")),
) -> JSONResponse:
    async def fn() -> dict[str, Any]:
        c = await bank.create_company(session, body)
        await audit(session, principal, "company.created", "company", c.id, after={"slug": c.slug})
        return bank.company_out(c)

    return await _idem(request, session, principal, fn, required=False, status=201)


@studio.put("/company-paths/{company_path_id}")
async def plc_18_put_company_path(
    request: Request,
    company_path_id: uuid.UUID,
    body: CompanyPathPut,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    body.organization_id = await resolve_owner(
        request, session, principal, "company_path.manage", body.organization_id
    )
    p = await bank.put_company_path(session, principal, company_path_id, body)
    await audit(
        session,
        principal,
        "company_path.replaced",
        "company_path",
        p.id,
        organization_id=p.organization_id,
        after={"version_no": p.version_no, "status": p.status},
    )
    return bank.path_out(p, await bank.path_steps(session, p.id))


# --------------------------------------------------------------------------- practice


@dflt.post("/practice/sessions", status_code=201)
async def plc_19_start_practice(
    request: Request,
    body: PracticeStart,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def fn() -> dict[str, Any]:
        ps = await practice.start(session, principal, body)
        return await practice.state(session, ps)

    return await _idem(request, session, principal, fn, required=True, status=201)


@dflt.get("/practice/sessions/{session_id}")
async def plc_20_practice_state(
    session_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    ps = await practice.get_owned_session(session, principal, session_id)
    return await practice.state(session, ps)


@dflt.post("/practice/sessions/{session_id}/answers")
async def plc_21_practice_answer(
    request: Request,
    session_id: uuid.UUID,
    body: PracticeAnswer,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def fn() -> dict[str, Any]:
        ps = await practice.get_owned_session(session, principal, session_id, lock=True)
        return await practice.answer(session, principal, ps, body)

    return await _idem(request, session, principal, fn, required=True)


@dflt.post("/practice/sessions/{session_id}/questions/{question_version_id}/reveal")
async def plc_22_reveal(
    request: Request,
    session_id: uuid.UUID,
    question_version_id: uuid.UUID,
    session: PrincipalDbSession,
    body: RevealIn | None = None,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def fn() -> dict[str, Any]:
        ps = await practice.get_owned_session(session, principal, session_id, lock=True)
        return await practice.reveal(session, principal, ps, question_version_id, (body or RevealIn()).kind)

    return await _idem(request, session, principal, fn, required=False)


@dflt.post("/practice/sessions/{session_id}/complete")
async def plc_23_complete(
    request: Request,
    session_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def fn() -> dict[str, Any]:
        ps = await practice.get_owned_session(session, principal, session_id, lock=True)
        return await practice.complete(session, principal, ps)

    return await _idem(request, session, principal, fn, required=False)


@dflt.get("/me/practice/review")
async def plc_24_practice_review(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    return {"items": await practice.review_list(session, principal)}


@l3r.get("/me/mastery")
async def plc_25_mastery(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    return await practice.mastery(session, principal)


@dflt.get("/me/recommendations")
async def plc_26_recommendations(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    await practice.refresh_recommendations(session, principal)
    return await practice.list_recommendations(session, principal)


@dflt.post("/me/recommendations/{recommendation_id}/dismiss")
async def plc_27_dismiss(
    request: Request,
    recommendation_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def fn() -> dict[str, Any]:
        await practice.dismiss_recommendation(session, principal, recommendation_id)
        return {"id": str(recommendation_id), "status": "dismissed"}

    return await _idem(request, session, principal, fn, required=False)


@dflt.get("/me/company-paths/{slug}")
async def plc_32_my_company_path(
    slug: str, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    return await practice.my_company_path(session, principal, slug)


router = APIRouter()
for _r in (pub, studio, dflt, l3r, mentor, reports, qbank_studio, qbank_media):
    router.include_router(_r)


# DB-01: register this module's erasure provider with admin privacy (import-time registration).
from app.modules.placement import privacy as _privacy  # noqa: E402

_privacy.register()
