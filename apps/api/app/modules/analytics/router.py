"""Analytics routes (api-specification §20, ANL-01..10, ANL-12).

* Ingest (ANL-01/02) and config (ANL-03): ownership only — no permission key (IPR-AN-01);
  identity from the session. Ingest routes are ``x-td-idle: engaged_only``.
* ANL-02 (beacon): the BFF validates the body ``csrf`` token and ``Sec-Fetch-Site``; this API
  re-checks ``Sec-Fetch-Site`` when the BFF forwards it and answers ``204``.
* ``/me/analytics/*`` (ANL-04/05): the learner's own data (route tag ``l3_readonly``).
* Reports: ``analytics.read`` at batch/course scope (batch reports also accept
  ``progress.read`` at batch scope, which is how evaluators read them);
  ``analytics.read.platform`` @P. Single company: there are no organization reports.
  ANL-11 (commerce) is not implemented here (see README).
* Exports (ANL-13..15, ``exports.py``): ``POST /exports`` (``report.export.request`` +
  ``analytics.read`` at the body's scope), ``GET /exports``, ``GET /exports/{id}``,
  ``GET /exports/{id}/download`` (requester only), ``POST /exports/{id}/approve|reject``
  (``report.export.approve``; approver ≠ requester via ``admin.approvals.decide``).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import (
    ScopeRef,
    check_permission,
    require_active_principal,
    require_permission,
    scope_from_path,
)
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import ist_date, utcnow
from app.modules.analytics import exports, reports
from app.modules.analytics.params import config_payload
from app.modules.analytics.service import (
    after_ingest,
    consent_active,
    enforce_rate_limits,
    ingest_batch,
    ingest_response,
    parse_body,
    privacy_tier_of,
)

ingest = authenticated_router(prefix="/analytics", tags=["analytics"], idle="engaged_only")
me = authenticated_router(prefix="/me/analytics", tags=["analytics"], route_tag="l3_readonly")
rep = authenticated_router(prefix="/analytics", tags=["analytics"], idle="extends")


async def _ingest(request: Request, principal: Principal, session: Any) -> Any:
    raw = await request.body()
    batch = parse_body(raw)
    await enforce_rate_limits(principal, getattr(request.state, "client_ip", None))
    now = utcnow()
    res = await ingest_batch(session, principal, batch, now=now)
    await after_ingest(principal, res)
    return res, now


@ingest.post("/events", openapi_extra={"x-td-idle": "engaged_only"})
async def ingest_events(request: Request, session: PrincipalDbSession) -> dict[str, Any]:
    principal: Principal = request.state.principal
    res, now = await _ingest(request, principal, session)
    return ingest_response(res, now)


@ingest.post("/events/beacon", status_code=204, openapi_extra={"x-td-idle": "engaged_only"})
async def ingest_beacon(request: Request, session: PrincipalDbSession) -> Response:
    site = request.headers.get("sec-fetch-site")
    if site is not None and site != "same-origin":
        raise ProblemError("csrf_failed")
    principal: Principal = request.state.principal
    await _ingest(request, principal, session)
    return Response(status_code=204)


@ingest.get("/config", openapi_extra={"x-td-idle": "neutral"})
async def analytics_config(request: Request, session: PrincipalDbSession) -> dict[str, Any]:
    principal: Principal = request.state.principal
    tier = await privacy_tier_of(session, principal)
    product = tier == "adult" and await consent_active(session, principal.user_id, "analytics_product")
    return config_payload(product, tier)


# --------------------------------------------------------------------------- self


@me.get("/summary")
async def my_summary(request: Request, session: PrincipalDbSession) -> dict[str, Any]:
    principal: Principal = request.state.principal
    tier = await privacy_tier_of(session, principal)
    out = await reports.student_metrics(
        session, principal.user_id, today=ist_date(utcnow()), privacy_tier=tier
    )
    return {"user_id": str(principal.user_id), **out}


@me.get("/learning-time")
async def my_learning_time(
    request: Request,
    session: PrincipalDbSession,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    grain: Literal["day", "week"] = "day",
) -> dict[str, Any]:
    principal: Principal = request.state.principal
    hi = to or ist_date(utcnow())
    lo = from_ or (hi - timedelta(days=27))
    if lo > hi or (hi - lo).days > 366:
        raise ProblemError(
            "validation_failed", 422, detail="Use a range of at most 366 days with from <= to."
        )
    points = await reports.learning_time_series(session, principal.user_id, lo, hi, grain)
    return {
        "grain": grain,
        "measurement_version": reports.MEASUREMENT_VERSION,
        "metric": "M5",
        "points": points,
    }


# --------------------------------------------------------------------------- reports


async def _batch_reader(
    request: Request, principal: Principal = Depends(require_active_principal)
) -> Principal:
    """``analytics.read`` (trainer, Admin) or ``progress.read`` (evaluator) at the batch's scope
    (a platform grant covers every batch)."""
    try:
        ref = ScopeRef("batch", uuid.UUID(str(request.path_params.get("batch_id"))))
    except (TypeError, ValueError) as e:
        raise ProblemError("not_found") from e
    for perm in ("analytics.read", "progress.read"):
        if await check_permission(principal, perm, ref, request, cross_tenant_raises=True):
            return principal
    raise ProblemError("permission_denied", permission="analytics.read")


BatchReader = Annotated[Principal, Depends(_batch_reader)]
CourseReader = Annotated[
    Principal, Depends(require_permission("analytics.read", scope=scope_from_path("course_id", "course")))
]
PlatformReader = Annotated[Principal, Depends(require_permission("analytics.read.platform"))]


@rep.get("/reports/batches/{batch_id}")
async def batch_report(
    batch_id: uuid.UUID, principal: BatchReader, session: PrincipalDbSession
) -> dict[str, Any]:
    out = await reports.batch_report(session, batch_id, today=ist_date(utcnow()))
    if out is None:
        raise ProblemError("not_found")
    return out


@rep.get("/reports/courses/{course_id}")
async def course_report(
    course_id: uuid.UUID, principal: CourseReader, session: PrincipalDbSession
) -> dict[str, Any]:
    return await reports.course_report(session, course_id, today=ist_date(utcnow()))


@rep.get("/reports/platform")
async def platform_report(principal: PlatformReader, session: PrincipalDbSession) -> dict[str, Any]:
    return await reports.platform_report(session, today=ist_date(utcnow()))


@rep.get("/ingest-health")
async def ingest_health(principal: PlatformReader, session: PrincipalDbSession) -> dict[str, Any]:
    return await reports.ingest_health(session, now=utcnow())


# --------------------------------------------------------------------------- exports (ANL-13..15)

exp = authenticated_router(prefix="/exports", tags=["analytics"], idle="extends")
OWN = {"x-td-route-tag": "account_status", "x-td-idle": "neutral"}


class ExportScopeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["platform", "batch", "course"]
    id: uuid.UUID | None = None


class ExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_key: str = Field(min_length=1, max_length=100)
    scope: ExportScopeIn
    filters: dict[str, Any] = Field(default_factory=dict)
    format: Literal["csv"] = "csv"
    contains_pii: bool | None = None  # informative; the catalogue decides
    reason: str | None = Field(default=None, max_length=1000)
    reason_code: str | None = Field(default=None, max_length=64)


class ExportDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)


Approver = Annotated[Principal, Depends(require_permission("report.export.approve"))]


@exp.post("", status_code=202)
async def request_export(body: ExportIn, request: Request, session: PrincipalDbSession) -> JSONResponse:
    principal: Principal = request.state.principal

    async def op() -> IdemResult:
        out = await exports.request_export(session, principal, body.model_dump(mode="json"), request)
        return IdemResult(status=202, body=out)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@exp.get("", openapi_extra=OWN)
async def list_exports(
    request: Request,
    session: PrincipalDbSession,
    scope_type: Literal["platform", "batch", "course"] | None = None,
    scope_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    principal: Principal = request.state.principal
    rows = await exports.list_jobs(session, principal, scope_type=scope_type, scope_id=scope_id, limit=limit)
    return {"data": rows}


@exp.get("/{export_job_id}", openapi_extra=OWN)
async def get_export(
    export_job_id: uuid.UUID, request: Request, session: PrincipalDbSession
) -> dict[str, Any]:
    principal: Principal = request.state.principal
    return exports.job_out(await exports.own_job(session, principal, export_job_id))


@exp.get("/{export_job_id}/download", openapi_extra=OWN, response_model=None)
async def download_export(
    export_job_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    redirect: bool | None = None,
) -> dict[str, Any] | RedirectResponse:
    """302 to the presigned URL; JSON ``{url, expires_at, ...}`` when the client asks for JSON
    (``Accept: application/json`` without ``redirect=true``), e.g. the web app."""
    principal: Principal = request.state.principal
    out = await exports.download(
        session, principal, export_job_id, getattr(request.state, "request_id", None)
    )
    wants_json = "application/json" in request.headers.get("accept", "")
    if redirect or (redirect is None and not wants_json):
        return RedirectResponse(out["url"], status_code=302, headers={"Cache-Control": "no-store"})
    return out


async def _decide(
    request: Request, session: Any, principal: Principal, job_id: uuid.UUID, approve: bool, note: str | None
) -> JSONResponse:
    from app.modules.security.policies import require_fresh_step_up

    require_fresh_step_up(principal)

    async def op() -> IdemResult:
        return IdemResult(body=await exports.decide(session, principal, job_id, approve=approve, note=note))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=approve)


@exp.post("/{export_job_id}/approve")
async def approve_export(
    export_job_id: uuid.UUID,
    body: ExportDecisionIn,
    request: Request,
    principal: Approver,
    session: PrincipalDbSession,
) -> JSONResponse:
    return await _decide(request, session, principal, export_job_id, True, body.note)


@exp.post("/{export_job_id}/reject")
async def reject_export(
    export_job_id: uuid.UUID,
    body: ExportDecisionIn,
    request: Request,
    principal: Approver,
    session: PrincipalDbSession,
) -> JSONResponse:
    return await _decide(request, session, principal, export_job_id, False, body.note)


router = APIRouter()
router.include_router(ingest)
router.include_router(me)
router.include_router(rep)
router.include_router(exp)
