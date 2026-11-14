"""Engine, rules, reports, incidents (SEC-22..45).

Single company (D5): org trusted networks and the org security summary were removed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.core.audit import audit
from app.core.auth import require_permission
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.firestore.sqlstore import StorePrincipalDbSession as PrincipalDbSession
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339
from app.modules.admin import approvals as apr
from app.modules.identity import clock
from app.modules.identity.fs_journal import request_journal
from app.modules.rbac.catalogue import ADMIN_ROLE
from app.modules.security import controls as ctl
from app.modules.security import engine
from app.modules.security import repo_fs_controls as secx
from app.modules.security.catalogue import BUILTIN_HC, RULES
from app.modules.security.models import (
    AccountRestriction,
    SecurityBulkLift,
    SecurityCase,
    SecurityIncident,
    SecurityReportExport,
    UnblockRequest,
)
from app.modules.security.policies import S10, has_perm, require_fresh_step_up, require_reason_code
from app.modules.security.refs import make_ref
from app.modules.security.reports import (
    REPORTS,
    SECURITY_EXPORT_KEYS,
    render_export,
    run_report,
    validate_filters,
)

r = authenticated_router(tags=["security"], route_tag="default", idle="extends")
NEUTRAL = {"x-td-idle": "neutral"}
# Direct multi-write routes: one undo scope on Firestore (approval request + engine writes).
JOURNAL = Depends(request_journal, scope="function")


def perm(key: str, scope: Any = None) -> Any:
    return Depends(require_permission(key, scope=scope))


class VersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_key: str | None = None
    family: str | None = None
    semver: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    definition: dict[str, Any]


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=1000)
    effective_from: datetime | None = None


class KillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Literal["risk_mode", "hc_all", "rule"]
    rule_key: str | None = None
    reason: str = Field(min_length=5, max_length=1000)


class BulkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selector: dict[str, Any]
    dry_run: bool = True
    reason: str = Field(default="", max_length=1000)
    extension_credit: bool = True


class ExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: dict[str, Any] = Field(default_factory=dict)
    include_per_user_rows: bool = False
    reason_code: str | None = None
    reason: str | None = Field(default=None, max_length=1000)


class IncidentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=300)
    severity: Literal["low", "medium", "high", "critical"]
    detected_at: datetime
    is_personal_data_breach: bool = False
    certin_reportable: bool = False


class IncidentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["detected", "triaged", "contained", "notified", "remediated", "closed"] | None = None
    certin_reported_at: datetime | None = None
    dpb_intimated_at: datetime | None = None
    dpb_reported_at: datetime | None = None
    principals_notified_at: datetime | None = None
    timeline_entry: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- rules


@r.get("/security/rules", openapi_extra=NEUTRAL)
async def rules(
    session: PrincipalDbSession, principal: Principal = perm("security.rule.read")
) -> dict[str, Any]:
    out = []
    for rd in RULES:
        entry: dict[str, Any] = {
            "key": rd.key,
            "family": rd.family,
            "category": rd.category,
            "description": rd.description,
            "explanation_key": rd.explanation_key,
        }
        if rd.key in BUILTIN_HC:
            status, params, semver = await engine.rule_status(session, rd.key)
            entry["active_version"] = {"status": status, "semver": semver, "params": params}
        out.append(entry)
    return {"data": out}


@r.get("/security/rule-versions", openapi_extra=NEUTRAL)
async def rule_versions(
    session: PrincipalDbSession,
    family: str | None = None,
    status: str | None = None,
    principal: Principal = perm("security.rule.read"),
) -> dict[str, Any]:
    from app.modules.security.models import RiskRule, RiskRuleVersion

    q = select(RiskRuleVersion, RiskRule.key).outerjoin(RiskRule, RiskRule.id == RiskRuleVersion.rule_id)
    if family:
        q = q.where(RiskRuleVersion.family == family)
    if status:
        q = q.where(RiskRuleVersion.status == status)
    rows = (await secx.execute(session, q.order_by(RiskRuleVersion.created_at.desc()))).all()
    return {
        "data": [ctl.version_out(v, k) for v, k in rows],
        "builtin": {fam: d["ruleset_version"] for fam, d in ctl.BUILTIN_RULESETS.items()},
    }


@r.post("/security/rule-versions", status_code=201)
async def create_rule_version(
    body: VersionIn, session: PrincipalDbSession, principal: Principal = perm("security.rule.propose")
) -> dict[str, Any]:
    v = await ctl.create_version(session, principal, body.model_dump())
    return ctl.version_out(v, body.rule_key)


@r.post("/security/rule-versions/{version_id}/simulate")
async def simulate(
    version_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = perm("security.rule.simulate")
) -> dict[str, Any]:
    v, key = await ctl.get_version(session, version_id)
    return await ctl.shadow_report(session, v, key)


@r.post("/security/rule-versions/{version_id}/start-shadow")
async def start_shadow(
    version_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = perm("security.rule.propose")
) -> dict[str, Any]:
    v, key = await ctl.get_version(session, version_id)
    await ctl.start_shadow(session, principal, v)
    return ctl.version_out(v, key)


@r.get("/security/rule-versions/{version_id}/shadow-report", openapi_extra=NEUTRAL)
async def get_shadow_report(
    version_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = perm("security.rule.read")
) -> dict[str, Any]:
    v, key = await ctl.get_version(session, version_id)
    return v.shadow_report or await ctl.shadow_report(session, v, key)


async def _activation(
    version_id: uuid.UUID,
    body: ReasonIn,
    request: Request,
    session: Any,
    principal: Principal,
    rollback: bool,
) -> JSONResponse:
    require_fresh_step_up(principal)

    async def op() -> IdemResult:
        v, key = await ctl.get_version(session, version_id)
        req = await ctl.request_activation(session, principal, v, key, body.reason, rollback=rollback)
        return IdemResult(status=202, body=apr.pending_response(req))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@r.post("/security/rule-versions/{version_id}/activation-requests", status_code=202)
async def activation_request(
    version_id: uuid.UUID,
    body: ReasonIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.rule.publish"),
) -> JSONResponse:
    return await _activation(version_id, body, request, session, principal, False)


@r.post("/security/rule-versions/{version_id}/rollback-requests", status_code=202)
async def rollback_request(
    version_id: uuid.UUID,
    body: ReasonIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.rule.publish"),
) -> JSONResponse:
    return await _activation(version_id, body, request, session, principal, True)


# --------------------------------------------------------------------------- engine controls


@r.post("/security/engine/kill-switch", dependencies=[JOURNAL])
async def kill_switch(
    body: KillIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.engine.kill_switch"),
) -> JSONResponse:
    require_fresh_step_up(principal)

    async def op() -> IdemResult:
        return IdemResult(
            body=await ctl.kill_switch(session, principal, body.target, body.rule_key, body.reason)
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@r.get("/security/engine/state", openapi_extra=NEUTRAL)
async def engine_state(
    session: PrincipalDbSession, principal: Principal = perm("security.rule.read")
) -> dict[str, Any]:
    return await ctl.engine_state(session)


@r.post("/security/restrictions/bulk-lift-requests", dependencies=[JOURNAL])
async def bulk_lift(
    body: BulkIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.restriction.bulk_lift"),
) -> JSONResponse:
    require_fresh_step_up(principal)

    async def op() -> IdemResult:
        status, out = await ctl.bulk_lift_request(session, principal, body.model_dump())
        return IdemResult(status=status, body=out)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@r.get("/security/restrictions/bulk-lift-requests/{bulk_lift_id}", openapi_extra=NEUTRAL)
async def bulk_status(
    bulk_lift_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = perm("security.restriction.bulk_lift"),
) -> dict[str, Any]:
    bl = await secx.get(session, SecurityBulkLift, bulk_lift_id)
    if bl is None:
        raise ProblemError("not_found")
    return {
        "bulk_lift_id": str(bl.id),
        "status": bl.status,
        "selector": bl.selector,
        "matched": len(bl.matched_restriction_ids),
        "progress": bl.progress,
        "approval_request_id": str(bl.approval_request_id) if bl.approval_request_id else None,
    }


# --------------------------------------------------------------------------- reports


@r.get("/security/reports", openapi_extra=NEUTRAL)
async def report_catalogue(
    session: PrincipalDbSession, principal: Principal = perm("security.case.read")
) -> dict[str, Any]:
    evidence = await has_perm(session, principal, "security.evidence.read")
    return {
        "data": [
            {
                "report_key": k,
                **v,
                "accessible": evidence or not v["per_user"],
                "export_approval": "security.export.per_user" if v["per_user"] else "step_up_only",
            }
            for k, v in REPORTS.items()
        ]
    }


async def _report_access(session: Any, principal: Principal, key: str, reason_code: str | None) -> str | None:
    if key not in REPORTS:
        raise ProblemError("not_found")
    if REPORTS[key]["per_user"]:
        if not await has_perm(session, principal, "security.evidence.read"):
            raise ProblemError("permission_denied", permission="security.evidence.read")
        return require_reason_code(reason_code)
    return reason_code


def _export_out(job: SecurityReportExport) -> dict[str, Any]:
    expired = bool(job.download_expires_at and job.download_expires_at < clock.now())
    downloadable = job.status == "completed" and job.content is not None and not expired
    return {
        "export_job_id": str(job.id),
        "report_key": job.report_key,
        "report_id": REPORTS.get(job.report_key, {}).get("id"),
        "status": "expired" if job.status == "completed" and expired else job.status,
        "contains_pii": job.contains_pii,
        "row_count": job.row_count,
        "approval_request_id": str(job.approval_request_id) if job.approval_request_id else None,
        "created_at": to_rfc3339(job.created_at) if job.created_at else None,
        "completed_at": to_rfc3339(job.completed_at) if job.completed_at else None,
        "download_expires_at": to_rfc3339(job.download_expires_at) if job.download_expires_at else None,
        "download_path": f"/security/reports/exports/{job.id}" if downloadable else None,
    }


@r.get("/security/reports/exports", openapi_extra=NEUTRAL)
async def my_exports(
    session: PrincipalDbSession,
    limit: int = 50,
    principal: Principal = perm("report.export.request"),
) -> dict[str, Any]:
    """ADM-05 / INV-11: the caller's own security report exports, newest first (downloads stay
    single-principal: only the requester can list or fetch a job)."""
    rows = (
        (
            await secx.execute(
                session,
                select(SecurityReportExport)
                .where(SecurityReportExport.requested_by == principal.user_id)
                .order_by(SecurityReportExport.created_at.desc(), SecurityReportExport.id.desc())
                .limit(max(1, min(limit, 200))),
            )
        )
        .scalars()
        .all()
    )
    return {"data": [_export_out(j) for j in rows]}


@r.get("/security/reports/{report_key}", openapi_extra=NEUTRAL)
async def report(
    report_key: str,
    request: Request,
    session: PrincipalDbSession,
    reason_code: str | None = None,
    principal: Principal = perm("security.case.read"),
) -> dict[str, Any]:
    code = await _report_access(session, principal, report_key, reason_code)
    filters = {k: v for k, v in request.query_params.items() if k not in ("reason_code",)}
    data = await run_report(session, report_key, filters)
    # Source-req §H: every report view is audited (ADM-10); per-user views carry a reason code.
    await audit(
        session,
        principal,
        "security.report_viewed",
        "security_report",
        None,
        reason_code=code,
        after={
            "report_key": report_key,
            "per_user": bool(REPORTS[report_key]["per_user"]),
            "filters": {k: str(v) for k, v in filters.items()},
        },
    )
    return data


@r.post("/security/reports/{report_key}/exports", status_code=202, dependencies=[JOURNAL])
async def export_report(
    report_key: str,
    body: ExportIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("report.export.request"),
) -> JSONResponse:
    require_fresh_step_up(principal)
    # ADM-01: every export of a per-user report (H1-H3, H5, H6, H9, H12) is approved by a second
    # admin (maker != checker, D2), whatever the client asks for; the flag never bypasses approval.
    per_user = bool(REPORTS.get(report_key, {}).get("per_user", False))

    async def op() -> IdemResult:
        await _report_access(session, principal, report_key, body.reason_code)
        validate_filters(report_key, body.filters)
        if not await has_perm(session, principal, "security.case.read"):
            raise ProblemError("permission_denied", permission="security.case.read")
        job = SecurityReportExport(
            id=uuid7(),
            report_key=report_key,
            requested_by=principal.user_id,
            filters=body.filters,
            include_per_user_rows=bool(per_user),
            contains_pii=bool(per_user),
            reason_code=body.reason_code,
            reason=body.reason,
            status="awaiting_approval" if per_user else "running",
        )
        secx.add(session, job)
        await secx.flush(session)
        approval_id = None
        if per_user:
            action = "security.export.per_user" if report_key in SECURITY_EXPORT_KEYS else "export.bulk_pii"
            req = await apr.new_request(
                session,
                principal,
                action_type=action,
                target_type="security_report_export",
                target_id=job.id,
                payload={"export_job_id": str(job.id), "report_key": report_key, "filters": body.filters},
                reason=body.reason or f"export {report_key}",
                required_approver_role=ADMIN_ROLE,
            )
            job.approval_request_id = req.id
            approval_id = str(req.id)
        else:
            await render_export(session, job)
        await audit(
            session,
            principal,
            "export.requested",
            "security_report_export",
            job.id,
            reason_code=body.reason_code,
            after={"report_key": report_key, "per_user": bool(per_user)},
        )
        return IdemResult(
            status=202,
            body={
                "export_job_id": str(job.id),
                "status": job.status,
                "approval_request_id": approval_id,
                "contains_pii": bool(job.contains_pii),
            },
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@r.get("/security/reports/exports/{export_job_id}", openapi_extra=NEUTRAL)
async def download_export(
    export_job_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = perm("report.export.request"),
) -> PlainTextResponse:
    job = await secx.get(session, SecurityReportExport, export_job_id)
    if job is None or job.requested_by != principal.user_id:
        raise ProblemError("not_found")
    if job.status != "completed" or job.content is None:
        raise ProblemError("invalid_state_transition", current_state=job.status, allowed=["completed"])
    if job.download_expires_at and job.download_expires_at < clock.now():
        raise ProblemError("invalid_state_transition", current_state="expired", allowed=[])
    await audit(session, principal, "export.download", "security_report_export", job.id)
    return PlainTextResponse(
        job.content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{job.report_key}-{job.id}.csv"',
            "Cache-Control": "no-store",
        },
    )


# --------------------------------------------------------------------------- incidents / dashboard


def _inc_out(i: SecurityIncident) -> dict[str, Any]:
    return {
        "incident_id": str(i.id),
        "incident_ref": i.incident_ref,
        "title": i.title,
        "severity": i.severity,
        "status": i.status,
        "detected_at": to_rfc3339(i.detected_at),
        "certin_due_at": to_rfc3339(i.certin_due_at) if i.certin_due_at else None,
        "certin_reported_at": to_rfc3339(i.certin_reported_at) if i.certin_reported_at else None,
        "dpb_report_due_at": to_rfc3339(i.dpb_report_due_at) if i.dpb_report_due_at else None,
        "version": i.version,
    }


@r.get("/security/incidents", openapi_extra=NEUTRAL)
async def incidents(
    session: PrincipalDbSession, principal: Principal = perm("security.incident.read")
) -> dict[str, Any]:
    if uses_firestore("security"):
        from app.modules.security.repo_firestore import incident_repo

        return {"data": [_inc_out(i) for i in await incident_repo(principal).list_incidents()]}
    rows = (
        await secx.execute(session, select(SecurityIncident).order_by(SecurityIncident.detected_at.desc()))
    ).scalars()
    return {"data": [_inc_out(i) for i in rows]}


@r.post("/security/incidents", status_code=201)
async def open_incident(
    body: IncidentIn, session: PrincipalDbSession, principal: Principal = perm("security.incident.manage")
) -> dict[str, Any]:
    require_fresh_step_up(principal, S10)
    # The CERT-In (6 h) and DPB (72 h) deadlines run from detected_at: a future time would push
    # them out silently. A few minutes of clock skew are tolerated.
    detected = body.detected_at if body.detected_at.tzinfo else body.detected_at.replace(tzinfo=UTC)
    if detected > clock.now() + timedelta(minutes=5):
        raise ProblemError(
            "validation_failed",
            422,
            errors=[
                {"field": "detected_at", "code": "in_future", "message": "Detection time is in the future"}
            ],
        )
    inc_cls: Any = SecurityIncident
    if uses_firestore("security"):
        from app.modules.security.store_specs import IncidentRow

        inc_cls = IncidentRow
    i = inc_cls(
        id=uuid7(),
        incident_ref=make_ref("INC"),
        title=body.title,
        severity=body.severity,
        detected_at=body.detected_at,
        is_personal_data_breach=body.is_personal_data_breach,
        certin_reportable=body.certin_reportable,
        certin_due_at=body.detected_at + timedelta(hours=6) if body.certin_reportable else None,
        dpb_report_due_at=body.detected_at + timedelta(hours=72) if body.is_personal_data_breach else None,
        owner_id=principal.user_id,
        timeline=[{"at": to_rfc3339(clock.now()), "entry": "opened"}],
    )
    if uses_firestore("security"):
        from app.modules.security.repo_firestore import incident_repo

        i = await incident_repo(principal).create_incident(i)
    else:
        secx.add(session, i)
        await secx.flush(session)
    await audit(session, principal, "security.incident.opened", "security_incident", i.id)
    return _inc_out(i)


@r.patch("/security/incidents/{incident_id}")
async def update_incident(
    incident_id: uuid.UUID,
    body: IncidentPatch,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.incident.manage"),
) -> dict[str, Any]:
    from app.modules.security.policies import check_if_match

    require_fresh_step_up(principal, S10)
    i: Any
    if uses_firestore("security"):
        from app.modules.security.repo_firestore import incident_repo

        i = await incident_repo(principal).get_incident(incident_id)
    else:
        i = await secx.get(session, SecurityIncident, incident_id)
    if i is None:
        raise ProblemError("not_found")
    check_if_match(request, i.version)
    data = body.model_dump(exclude_none=True)
    entry = data.pop("timeline_entry", None)
    for k, v in data.items():
        setattr(i, k, v)
    if entry:
        i.timeline = [*i.timeline, {"at": to_rfc3339(clock.now()), "entry": entry}]
    if i.status == "closed" and i.closed_at is None:
        i.closed_at = clock.now()
    i.version += 1
    if uses_firestore("security"):
        from app.modules.security.repo_firestore import incident_repo

        await incident_repo(principal).save_incident(i)
    await audit(
        session, principal, "security.incident.updated", "security_incident", i.id, after={"status": i.status}
    )
    return _inc_out(i)


@r.get("/security/dashboard", openapi_extra=NEUTRAL)
async def dashboard(
    session: PrincipalDbSession, principal: Principal = perm("security.case.read")
) -> dict[str, Any]:
    open_cases = dict(
        (
            await secx.execute(
                session,
                select(SecurityCase.status, func.count())
                .where(SecurityCase.status != "closed")
                .group_by(SecurityCase.status),
            )
        ).all()
    )
    restr = dict(
        (
            await secx.execute(
                session,
                select(AccountRestriction.level, func.count())
                .where(AccountRestriction.ended_at.is_(None))
                .group_by(AccountRestriction.level),
            )
        ).all()
    )
    appeals = (
        await secx.execute(
            session,
            select(func.count())
            .select_from(UnblockRequest)
            .where(UnblockRequest.state.in_(("submitted", "under_review", "info_requested", "escalated"))),
        )
    ).scalar_one()
    return {
        "queue": {k: int(v) for k, v in open_cases.items()},
        "restrictions": {f"L{k}": int(v) for k, v in restr.items()},
        "pending_unblock_requests": int(appeals),
        "engine": await ctl.engine_state(session),
    }
