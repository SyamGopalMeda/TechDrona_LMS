"""Engage: live quizzes, polls, word clouds and surveys.

Manager (``engage.activity.manage``, scoped to the activity's batch, or the platform):
  GET    /engage/activities                        list (``q``, ``type``) with question count + latest run
  POST   /engage/activities                        create (Idempotency-Key optional)
  GET    /engage/activities/{id}                   detail incl. questions (with correct flags) + runs
  PUT    /engage/activities/{id}                   replace settings + questions
  DELETE /engage/activities/{id}                   soft delete (closes live runs)
  POST   /engage/activities/{id}/duplicate         copy "<title> (copy)"
  POST   /engage/activities/{id}/runs              new run + join code; 10/h per activity+user
  POST   /engage/bank-import                       placement questions → question drafts (not saved)
  GET    /engage/runs/{run_id}/presenter           live state (counts, distribution, winners, leaderboard)
  GET    /engage/runs/{run_id}/results             same payload (summary page)
  POST   /engage/runs/{run_id}/control             start|close|goto|reveal|hide|publish|unpublish|finalise
  POST   /engage/runs/{run_id}/invite              notify active batch members; 5/h per activity+user
Participant (any authenticated user; members-only runs check active batch membership):
  GET    /engage/join/{code}                       preview (eligibility, status)
  POST   /engage/join/{code}                       join (participant limit enforced)
  GET    /engage/runs/{run_id}/live                participant state (no correct answers before reveal)
  POST   /engage/runs/{run_id}/responses           answer one question (rate limited; one per question)
  GET    /engage/me/runs                           runs I joined

Live endpoints are polled: each returns ``version`` and an ``ETag``; ``?since=<version>`` answers
``{"unchanged": true}`` and ``If-None-Match`` answers ``304`` when nothing changed.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from app.core.auth import require_active_principal
from app.core.db import PrincipalDbSession
from app.core.idempotency import IdemResult, idempotent
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.modules.engage import service as svc
from app.modules.engage.schemas import ActivityIn, AnswerIn, BankImportIn, ControlIn, LaunchIn

router = authenticated_router(prefix="/engage", tags=["engage"])

CurrentPrincipal = Annotated[Principal, Depends(require_active_principal)]
NEUTRAL = {"x-td-idle": "neutral"}
Since = Annotated[str | None, Query(max_length=64)]


def _live(request: Request, body: dict[str, Any], version: str) -> Response:
    etag = f'W/"{version}"'
    headers = {"ETag": etag, "Cache-Control": "no-store"}
    if request.headers.get("if-none-match") in (etag, f'"{version}"'):
        return Response(status_code=304, headers=headers)
    return JSONResponse(body, headers=headers)


# --------------------------------------------------------------------------- activities


@router.get("/activities", openapi_extra=NEUTRAL)
async def list_activities(
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    type: Literal["quiz", "poll", "word_cloud", "survey"] | None = None,
) -> dict[str, Any]:
    return await svc.list_activities(request, session, principal, q=q, activity_type=type)


@router.post("/activities", status_code=201)
async def create_activity(
    body: ActivityIn, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> JSONResponse:
    async def op() -> IdemResult:
        out = await svc.create_activity(request, session, principal, body)
        return IdemResult(out, 201, uuid.UUID(out["id"]))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@router.get("/activities/{activity_id}", openapi_extra=NEUTRAL)
async def get_activity(
    activity_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.activity_detail(request, session, principal, activity_id)


@router.put("/activities/{activity_id}")
async def put_activity(
    activity_id: uuid.UUID,
    body: ActivityIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    return await svc.update_activity(request, session, principal, activity_id, body)


@router.delete("/activities/{activity_id}", status_code=204)
async def delete_activity(
    activity_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> Response:
    await svc.delete_activity(request, session, principal, activity_id)
    return Response(status_code=204)


@router.post("/activities/{activity_id}/duplicate", status_code=201)
async def duplicate_activity(
    activity_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> JSONResponse:
    async def op() -> IdemResult:
        out = await svc.duplicate_activity(request, session, principal, activity_id)
        return IdemResult(out, 201, uuid.UUID(out["id"]))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@router.post("/activities/{activity_id}/runs", status_code=201)
async def launch_run(
    activity_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    body: LaunchIn | None = None,
) -> JSONResponse:
    async def op() -> IdemResult:
        out = await svc.launch_run(request, session, principal, activity_id, body or LaunchIn())
        return IdemResult(out, 201, uuid.UUID(out["id"]))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@router.post("/bank-import")
async def bank_import(
    body: BankImportIn, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.bank_import(request, session, principal, body.question_ids)


# --------------------------------------------------------------------------- presenter / control room


@router.get("/runs/{run_id}/presenter", openapi_extra=NEUTRAL)
async def presenter(
    run_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    since: Since = None,
) -> Response:
    body, version = await svc.presenter_state(request, session, principal, run_id, since)
    return _live(request, body, version)


@router.get("/runs/{run_id}/results", openapi_extra=NEUTRAL)
async def results(
    run_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    body, _v = await svc.presenter_state(request, session, principal, run_id, None)
    return body


@router.post("/runs/{run_id}/control")
async def control(
    run_id: uuid.UUID,
    body: ControlIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    return await svc.control_run(request, session, principal, run_id, body)


@router.post("/runs/{run_id}/invite")
async def invite(
    run_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.invite(request, session, principal, run_id)


# --------------------------------------------------------------------------- participants


@router.get("/join/{code}", openapi_extra=NEUTRAL)
async def join_preview(
    code: str,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    return await svc.join_preview(request, session, principal, code[:16])


@router.post("/join/{code}")
async def join(
    code: str, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.join(request, session, principal, code[:16])


@router.get("/runs/{run_id}/live", openapi_extra=NEUTRAL)
async def live(
    run_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    since: Since = None,
) -> Response:
    body, version = await svc.participant_state(request, session, principal, run_id, since)
    return _live(request, body, version)


@router.post("/runs/{run_id}/responses", status_code=201)
async def respond(
    run_id: uuid.UUID,
    body: AnswerIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    return await svc.answer(request, session, principal, run_id, body)


@router.get("/me/runs", openapi_extra=NEUTRAL)
async def my_runs(session: PrincipalDbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    return await svc.my_runs(session, principal)


# DB-01: erasure provider (participant names, free-text answers).
from app.modules.engage import privacy as _privacy  # noqa: E402

_privacy.register()
