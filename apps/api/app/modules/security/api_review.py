"""Reviewer / support endpoints (route tag ``default``; staff tier): SEC-03..21, UNB-10..18."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.core.audit import audit
from app.core.auth import require_permission
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339
from app.modules.identity import clock
from app.modules.security import cases as cs
from app.modules.security import engine
from app.modules.security import restrictions as rx
from app.modules.security import unblock as unb
from app.modules.security.models import (
    AccountRestriction,
    CaseNote,
    RiskEvaluation,
    SecurityCase,
    UnblockRequest,
)
from app.modules.security.policies import (
    S10,
    check_if_match,
    etag,
    need_perm,
    require_fresh_step_up,
    require_reason_code,
)
from app.modules.security.repo_fs_cases import sec_route
from app.modules.security.timeline import device_graph, timeline

r = authenticated_router(tags=["security"], route_tag="default", idle="extends")
NEUTRAL = {"x-td-idle": "neutral"}


def perm(key: str) -> Any:
    return Depends(require_permission(key))


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visibility: Literal["internal", "student"] = "internal"
    body: str = Field(min_length=1, max_length=4000)


class AssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignee_id: uuid.UUID


class UserException(BaseModel):
    model_config = ConfigDict(extra="forbid")
    setting_key: str
    value: Any
    expires_at: datetime


class Conditions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_exception: UserException | None = None
    password_reset: bool = False
    contact_change: bool = False


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unblock_request_id: uuid.UUID | None = None
    outcome: Literal[
        "lift_false_positive",
        "lift_with_warning",
        "lift_conditions",
        "uphold",
        "convert_L4",
        "reduce_level",
        "close_no_action",
    ]
    resulting_level: int | None = Field(default=None, ge=0, le=4)
    rationale: str = Field(min_length=1, max_length=4000)
    # Required (>= 50 characters) for every outcome except close_no_action, where it is optional.
    student_summary: str = Field(default="", max_length=2000)
    conditions: Conditions = Field(default_factory=Conditions)
    extension_days: int = Field(default=0, ge=0, le=365)
    false_positive_rule_keys: list[str] = Field(default_factory=list, max_length=30)


class ApprovalNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)


class SendBackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=3, max_length=1000)


class ManualCaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    family: Literal["sharing", "takeover"] = "sharing"
    opened_reason: Literal["support_escalation", "manual", "integrity_referral"] = "manual"
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    note: str = Field(min_length=3, max_length=4000)


class RevealIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_ref: str = Field(max_length=60)
    field: Literal["ip"] = "ip"
    reason_code: str
    case_ref: str


class RestrictionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    level: int = Field(ge=1, le=4)
    family: Literal["sharing", "takeover"] = "sharing"
    case_id: uuid.UUID | None = None
    rationale: str = Field(min_length=3, max_length=4000)
    ends_at: datetime | None = None


class LiftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)


class InfoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_key: str
    message: str | None = Field(default=None, max_length=1000)


class EscalateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)


# --------------------------------------------------------------------------- cases


@r.get("/security/cases", openapi_extra=NEUTRAL)
@sec_route
async def list_cases(
    session: PrincipalDbSession,
    status: str | None = None,
    level: str | None = None,
    family: str | None = None,
    high_risk: bool | None = None,
    assignee: str | None = None,
    sla_state: str | None = None,
    rule: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    principal: Principal = perm("security.case.read"),
) -> dict[str, Any]:
    q = select(SecurityCase)
    if status:
        q = q.where(SecurityCase.status.in_(status.split(",")))
    else:
        q = q.where(SecurityCase.status != "closed")
    if level:
        q = q.where(SecurityCase.level.in_([int(x) for x in level.split(",")]))
    if family:
        q = q.where(SecurityCase.family == family)
    if high_risk is not None:
        q = q.where(SecurityCase.is_high_risk.is_(high_risk))
    if assignee == "me":
        q = q.where(SecurityCase.assignee_id == principal.user_id)
    if rule:
        q = q.where(SecurityCase.hc_rule == rule)
    cases = (
        (await session.execute(q.order_by(SecurityCase.sla_decision_due.asc().nulls_last()).limit(limit)))
        .scalars()
        .all()
    )
    now = clock.now()
    out = []
    for c in cases:
        if sla_state and cs.sla_state(c, now) != sla_state:
            continue
        ur = await cs.open_request_for(session, c.id)
        out.append(cs.case_out(c, score=await cs.latest_score(session, c.user_id), ur=ur, now=now))
    counts = dict(
        (
            await session.execute(
                select(SecurityCase.status, func.count())
                .where(SecurityCase.status != "closed")
                .group_by(SecurityCase.status)
            )
        ).all()
    )
    return {
        "data": out,
        "counts": {k: int(v) for k, v in counts.items()},
        "page": {"next_cursor": None, "has_more": False, "limit": limit},
    }


@r.get("/security/cases/{case_id}", openapi_extra=NEUTRAL)
@sec_route
async def get_case(
    case_id: uuid.UUID,
    session: PrincipalDbSession,
    reason_code: str | None = None,
    principal: Principal = perm("security.case.read"),
) -> JSONResponse:
    code = require_reason_code(reason_code)
    c = await cs.get_case(session, case_id)
    rr = await cs.case_restriction(session, c)
    ur = await cs.open_request_for(session, c.id)
    user = await cs.subject_user(session, c.user_id)
    from app.modules.identity import public as identity_public

    prof = await identity_public.get_profile(session, c.user_id)
    notes = (
        await session.execute(select(CaseNote).where(CaseNote.case_id == c.id).order_by(CaseNote.created_at))
    ).scalars()
    from app.modules.security.models import CaseDecision

    decisions = (
        (await session.execute(select(CaseDecision).where(CaseDecision.case_id == c.id))).scalars().all()
    )
    await audit(
        session, principal, "case.viewed", "security_case", c.id, subject_user_id=c.user_id, reason_code=code
    )
    body = {
        **cs.case_out(c, score=await cs.latest_score(session, c.user_id), ur=ur),
        "subject": {
            "user_id": str(user.id),
            "name": prof.full_name if prof else None,
            "is_minor": user.is_minor,
        },
        "restriction": rx.restriction_out(rr, c.case_ref) if rr else None,
        "notes": [
            {
                "at": to_rfc3339(n.created_at),
                "visibility": n.visibility,
                "body": n.body,
                "author_id": str(n.author_id) if n.author_id else None,
            }
            for n in notes
        ],
        "decisions": [
            {
                "decision_id": str(d.id),
                "outcome": d.outcome,
                "decided_by": str(d.decided_by),
                "approved_by": str(d.approved_by) if d.approved_by else None,
                "at": to_rfc3339(d.created_at),
            }
            for d in decisions
        ],
        "pending_approval": await cs.pending_proposal(session, principal, c),
    }
    return JSONResponse(body, headers=etag(c.version))


@r.post("/security/cases/{case_id}/claim")
@sec_route
async def claim_case(
    case_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.case.assign"),
) -> JSONResponse:
    c = await cs.get_case(session, case_id, lock=True)
    check_if_match(request, c.version)
    await cs.require_no_conflict(session, principal.user_id, c, await cs.case_restriction(session, c))
    c.assignee_id = principal.user_id
    if c.status == "open":
        c.status = "under_review"
    if c.first_response_at is None:
        c.first_response_at = clock.now()
    c.version += 1
    await audit(session, principal, "case.claimed", "security_case", c.id, subject_user_id=c.user_id)
    return JSONResponse(cs.case_out(c), headers=etag(c.version))


@r.post("/security/cases/{case_id}/assign")
@sec_route
async def assign_case(
    case_id: uuid.UUID,
    body: AssignIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.case.assign"),
) -> JSONResponse:
    c = await cs.get_case(session, case_id, lock=True)
    check_if_match(request, c.version)
    await cs.require_no_conflict(session, body.assignee_id, c, await cs.case_restriction(session, c))
    c.assignee_id = body.assignee_id
    c.version += 1
    await audit(
        session,
        principal,
        "case.assigned",
        "security_case",
        c.id,
        subject_user_id=c.user_id,
        after={"assignee_id": str(body.assignee_id)},
    )
    return JSONResponse(cs.case_out(c), headers=etag(c.version))


@r.get("/security/cases/{case_id}/explanation", openapi_extra=NEUTRAL)
@sec_route
async def explanation(
    case_id: uuid.UUID,
    session: PrincipalDbSession,
    reason_code: str | None = None,
    principal: Principal = perm("security.evidence.read"),
) -> dict[str, Any]:
    code = require_reason_code(reason_code)
    c = await cs.get_case(session, case_id, lock=True)
    rr = (
        await session.execute(
            select(AccountRestriction)
            .where(AccountRestriction.case_id == c.id)
            .order_by(AccountRestriction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    ev = None
    if rr is not None and rr.evaluation_id:
        ev = (
            await session.execute(select(RiskEvaluation).where(RiskEvaluation.id == rr.evaluation_id))
        ).scalar_one_or_none()
    if ev is None:
        ev = (
            await session.execute(
                select(RiskEvaluation)
                .where(RiskEvaluation.user_id == c.user_id, RiskEvaluation.family == c.family)
                .order_by(RiskEvaluation.evaluated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    await cs.mark_viewed(session, c, principal.user_id, "explanation")
    await audit(
        session,
        principal,
        "case.explanation_viewed",
        "security_case",
        c.id,
        subject_user_id=c.user_id,
        reason_code=code,
    )
    from app.modules.security.api_student import _KEY_TEXT

    return {
        "case_ref": c.case_ref,
        "evaluation": evaluation_out(ev) if ev else None,
        "hc_rule": c.hc_rule,
        "student_explanation_preview": [_KEY_TEXT.get(k, k) for k in (ev.explanation_keys if ev else [])],
    }


def evaluation_out(e: RiskEvaluation) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "user_id": str(e.user_id),
        "family": e.family,
        "mode": e.mode,
        "ruleset_version": e.ruleset_version,
        "trigger": e.trigger,
        "evaluated_at": to_rfc3339(e.evaluated_at),
        "window": e.window,
        "signals": e.signals,
        "subtotals": e.subtotals,
        "repeat_multiplier": float(e.repeat_multiplier),
        "score": float(e.score),
        "previous_score": float(e.previous_score) if e.previous_score is not None else None,
        "level_before": e.level_before,
        "level_after": e.level_after,
        "gates": e.gates,
        "action": e.action,
        "restriction_id": str(e.restriction_id) if e.restriction_id else None,
        "case_id": str(e.case_id) if e.case_id else None,
        "explanation_keys": e.explanation_keys,
    }


@r.post("/security/cases/{case_id}/notes", status_code=201)
@sec_route
async def add_note(
    case_id: uuid.UUID,
    body: NoteIn,
    session: PrincipalDbSession,
    principal: Principal = perm("security.case.note"),
) -> dict[str, Any]:
    c = await cs.get_case(session, case_id)
    n = await cs.case_note(session, c.id, principal.user_id, body.visibility, body.body)
    await audit(
        session,
        principal,
        "case.note_added",
        "security_case",
        c.id,
        subject_user_id=c.user_id,
        after={"visibility": body.visibility},
    )
    return {"note_id": str(n.id), "visibility": n.visibility}


@r.post("/security/cases/{case_id}/decisions")
@sec_route
async def decide(
    case_id: uuid.UUID,
    body: DecisionIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.case.decide"),
) -> JSONResponse:
    require_fresh_step_up(principal)

    async def op() -> IdemResult:
        c = await cs.get_case(session, case_id, lock=True)
        check_if_match(request, c.version)
        status, out = await cs.propose_decision(session, principal, c, body.model_dump(mode="json"))
        return IdemResult(status=status, body=out)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@r.post("/security/cases/{case_id}/approval-requests/{approval_request_id}/approve")
@sec_route
async def approve_decision(
    case_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    body: ApprovalNoteIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("approval.decide"),
) -> JSONResponse:
    require_fresh_step_up(principal)

    async def op() -> IdemResult:
        c = await cs.get_case(session, case_id, lock=True)
        check_if_match(request, c.version)
        return IdemResult(
            body=await cs.approve_proposal(session, principal, c, approval_request_id, body.note)
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@r.post("/security/cases/{case_id}/approval-requests/{approval_request_id}/send-back")
@sec_route
async def send_back_decision(
    case_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    body: SendBackIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.case.decide"),
) -> dict[str, Any]:
    require_fresh_step_up(principal)
    c = await cs.get_case(session, case_id, lock=True)
    check_if_match(request, c.version)
    return await cs.send_back(session, principal, c, approval_request_id, body.note)


@r.post("/security/cases/{case_id}/approval-requests/{approval_request_id}/withdraw")
@sec_route
async def withdraw_decision(
    case_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.case.decide"),
) -> dict[str, Any]:
    c = await cs.get_case(session, case_id, lock=True)
    check_if_match(request, c.version)
    return await cs.withdraw_proposal(session, principal, c, approval_request_id)


@r.post("/security/cases", status_code=201)
@sec_route
async def open_case(
    body: ManualCaseIn, session: PrincipalDbSession, principal: Principal = perm("security.case.note")
) -> dict[str, Any]:
    await cs.subject_user(session, body.user_id)
    active = await rx.active_for(session, body.user_id, body.family)
    c = await engine.open_case(
        session,
        user_id=body.user_id,
        family=body.family,
        level=active.level if active else 0,
        opened_reason=body.opened_reason,
        priority=body.priority,
        actor=principal,
    )
    await cs.case_note(session, c.id, principal.user_id, "internal", body.note)
    return cs.case_out(c)


# --------------------------------------------------------------------------- evidence views


@r.get("/security/users/{user_id}/timeline", openapi_extra=NEUTRAL)
@sec_route
async def user_timeline(
    user_id: uuid.UUID,
    session: PrincipalDbSession,
    reason_code: str | None = None,
    case_ref: str | None = None,
    frm: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    types: str | None = None,
    principal: Principal = perm("security.evidence.read"),
) -> dict[str, Any]:
    code = require_reason_code(reason_code)
    user = await cs.subject_user(session, user_id)
    now = clock.now()
    events = await timeline(
        session, user_id, frm or now - timedelta(days=30), to or now, set(types.split(",")) if types else None
    )
    if case_ref:
        c = (
            await session.execute(select(SecurityCase).where(SecurityCase.case_ref == case_ref))
        ).scalar_one_or_none()
        if c is not None and c.user_id == user_id:
            await cs.mark_viewed(session, c, principal.user_id, "timeline")
    await audit(
        session,
        principal,
        "security.timeline_viewed",
        "user",
        user_id,
        subject_user_id=user_id,
        reason_code=code,
    )
    return {
        "subject": {
            "user_id": str(user.id),
            "is_minor": user.is_minor,
            "privacy_tier": user.privacy_tier,
            "restriction_level": user.restriction_level,
        },
        "events": events[:200],
        "page": {"next_cursor": None, "has_more": len(events) > 200, "limit": 200},
    }


@r.get("/security/users/{user_id}/concurrency", openapi_extra=NEUTRAL)
@sec_route
async def concurrency(
    user_id: uuid.UUID,
    session: PrincipalDbSession,
    reason_code: str | None = None,
    frm: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    principal: Principal = perm("security.evidence.read"),
) -> dict[str, Any]:
    from app.modules.security.signals import engaged_bucket_feed

    code = require_reason_code(reason_code)
    now = clock.now()
    start, end = frm or now - timedelta(days=1), to or now
    if end - start > timedelta(days=14):
        raise cs.vf("from", "range_too_long", "At most 14 days per call")
    feed = engaged_bucket_feed()
    buckets = list(await feed.get_engaged_buckets(session, user_id, start, end)) if feed else []
    await audit(
        session,
        principal,
        "security.concurrency_viewed",
        "user",
        user_id,
        subject_user_id=user_id,
        reason_code=code,
    )
    return {
        "available": feed is not None,
        "buckets": [
            {
                "device_id": str(b.device_id),
                "session_id": str(b.auth_session_id),
                "bucket": to_rfc3339(b.bucket_start),
            }
            for b in buckets
        ],
    }


@r.get("/security/users/{user_id}/device-graph", openapi_extra=NEUTRAL)
@sec_route
async def graph(
    user_id: uuid.UUID,
    session: PrincipalDbSession,
    reason_code: str | None = None,
    days: int = Query(30, ge=1, le=90),
    hops: int = Query(1, ge=1, le=2),
    principal: Principal = perm("security.evidence.read"),
) -> dict[str, Any]:
    code = require_reason_code(reason_code)
    await cs.subject_user(session, user_id)
    await audit(
        session,
        principal,
        "security.device_graph_viewed",
        "user",
        user_id,
        subject_user_id=user_id,
        reason_code=code,
    )
    return await device_graph(session, user_id, days, hops)


@r.post("/security/pii-reveals")
@sec_route
async def pii_reveal(
    body: RevealIn, session: PrincipalDbSession, principal: Principal = perm("security.evidence.read")
) -> dict[str, Any]:
    require_fresh_step_up(principal, S10)
    code = require_reason_code(body.reason_code)
    c = (
        await session.execute(select(SecurityCase).where(SecurityCase.case_ref == body.case_ref))
    ).scalar_one_or_none()
    if c is None:
        raise ProblemError("not_found")
    prefix, _, raw = body.evidence_ref.partition("_")
    try:
        rid = uuid.UUID(raw)
    except ValueError as e:
        raise ProblemError("not_found") from e
    from app.modules.sessions import public as sessions_public

    ip: str | None = None
    subject: uuid.UUID | None = None
    if prefix == "la":
        la = await sessions_public.get_login_attempt(session, rid)
        ip, subject = (str(la.ip) if la and la.ip else None), (la.user_id if la else None)
    elif prefix == "as":
        s = await sessions_public.get_session(session, rid)
        ip, subject = (str(s.ip_first) if s and s.ip_first else None), (s.user_id if s else None)
    if ip is None or subject != c.user_id:
        raise ProblemError("not_found")
    await audit(
        session,
        principal,
        "pii.reveal",
        "security_case",
        c.id,
        subject_user_id=c.user_id,
        reason_code=code,
        after={"evidence_ref": body.evidence_ref, "field": body.field},
    )
    return {"field": "ip", "value": ip, "revealed_at": to_rfc3339(clock.now())}


@r.get("/security/evaluations", openapi_extra=NEUTRAL)
@sec_route
async def evaluations(
    session: PrincipalDbSession,
    user_id: uuid.UUID,
    reason_code: str | None = None,
    family: str | None = None,
    frm: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    principal: Principal = perm("security.evidence.read"),
) -> dict[str, Any]:
    code = require_reason_code(reason_code)
    rows = await engine.evaluations_for(session, user_id, family, frm, to)
    await audit(
        session,
        principal,
        "security.evaluations_viewed",
        "user",
        user_id,
        subject_user_id=user_id,
        reason_code=code,
    )
    return {
        "data": [evaluation_out(e) for e in rows],
        "page": {"next_cursor": None, "has_more": False, "limit": 200},
    }


@r.get("/security/evaluations/{evaluation_id}", openapi_extra=NEUTRAL)
@sec_route
async def evaluation(
    evaluation_id: uuid.UUID,
    session: PrincipalDbSession,
    reason_code: str | None = None,
    principal: Principal = perm("security.evidence.read"),
) -> dict[str, Any]:
    code = require_reason_code(reason_code)
    e = (
        await session.execute(select(RiskEvaluation).where(RiskEvaluation.id == evaluation_id))
    ).scalar_one_or_none()
    if e is None:
        raise ProblemError("not_found")
    await audit(
        session,
        principal,
        "security.evaluation_viewed",
        "risk_evaluation",
        e.id,
        subject_user_id=e.user_id,
        reason_code=code,
    )
    return evaluation_out(e)


# --------------------------------------------------------------------------- restrictions


@r.get("/security/restrictions", openapi_extra=NEUTRAL)
@sec_route
async def list_restrictions(
    session: PrincipalDbSession,
    active: bool = True,
    level: int | None = None,
    principal: Principal = perm("security.status.read"),
) -> dict[str, Any]:
    q = select(AccountRestriction)
    q = q.where(AccountRestriction.ended_at.is_(None)) if active else q
    if level:
        q = q.where(AccountRestriction.level == level)
    rows = (await session.execute(q.order_by(AccountRestriction.starts_at.desc()).limit(200))).scalars().all()
    return {
        "data": [rx.restriction_out(x) for x in rows],
        "page": {"next_cursor": None, "has_more": False, "limit": 200},
    }


@r.post("/security/restrictions", status_code=201)
@sec_route
async def apply_restriction(
    body: RestrictionIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.restriction.apply_l1l2"),
) -> JSONResponse:
    if body.level >= 3:
        await need_perm(session, principal, "security.restriction.apply_l3l4")
        require_fresh_step_up(principal)

    async def op() -> IdemResult:
        user = await cs.subject_user(session, body.user_id)
        if user.id == principal.user_id:
            raise ProblemError("conflict_of_interest", reasons=["own_account"])
        if body.family == "sharing" and user.is_minor:
            raise ProblemError(
                "validation_failed",
                422,
                errors=[
                    {
                        "field": "family",
                        "code": "minor_sharing_not_permitted",
                        "message": "Sharing restrictions are not permitted for minors",
                    }
                ],
            )
        if body.level >= 3 and body.case_id is None:
            raise cs.vf("case_id", "required", "L3/L4 need a case")
        existing = await rx.active_for(session, user.id, body.family)
        if existing is not None and existing.level >= body.level:
            raise ProblemError("invalid_state_transition", current_state=f"L{existing.level}", allowed=[])
        case = await cs.get_case(session, body.case_id) if body.case_id else None
        if case is not None and case.user_id != user.id:
            raise ProblemError("not_found")
        if body.level == 4 and case is not None and "staff_account" in case.high_risk_reasons:
            raise ProblemError(
                "second_approval_required", detail="L4 on a staff account needs two reviewers."
            )
        rr, revoked = await rx.apply_restriction(
            session,
            user_id=user.id,
            level=body.level,
            family=body.family,
            source="reviewer",
            actor=principal,
            ends_at=body.ends_at,
            case_id=case.id if case else None,
            applied_by=principal.user_id,
            reason=body.rationale,
        )
        if case is not None:
            case.level = max(case.level, body.level)
            case.version += 1
        return IdemResult(
            status=201,
            body={
                "restriction_id": str(rr.id),
                "level": rr.level,
                "scope": rr.scope,
                "starts_at": to_rfc3339(rr.starts_at),
                "deferred_until": to_rfc3339(rr.deferred_until) if rr.deferred_until else None,
                "sessions_revoked": revoked,
            },
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@r.post("/security/restrictions/{restriction_id}/lift")
@sec_route
async def lift_restriction(
    restriction_id: uuid.UUID,
    body: LiftIn,
    session: PrincipalDbSession,
    principal: Principal = perm("security.restriction.lift_l1l2"),
) -> dict[str, Any]:
    rr = await session.get(AccountRestriction, restriction_id)
    if rr is None or rr.ended_at is not None:
        raise ProblemError("not_found")
    if rr.level >= 3 or rr.family == "takeover":
        case_ref = None
        if rr.case_id:
            case_ref = (
                await session.execute(select(SecurityCase.case_ref).where(SecurityCase.id == rr.case_id))
            ).scalar()
        raise ProblemError("decision_required", case_ref=case_ref)
    await rx.end_restriction(
        session, rr, "case_decision", ended_by=principal.user_id, actor=principal, reason_text=body.reason
    )
    return rx.restriction_out(rr)


class ManualVerificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["video_call", "callback_known_number", "document_check", "in_person"]
    note: str = Field(min_length=10, max_length=1000)


@r.post("/security/restrictions/{restriction_id}/manual-verification")
@sec_route
async def manual_verification(
    restriction_id: uuid.UUID,
    body: ManualVerificationIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.case.decide"),
) -> JSONResponse:
    """UNB §6.3a: senior manual verification for a lift-pending student whose contacts changed in
    the 7 days before the restriction (no OTP re-verification possible); ends the restriction."""
    require_fresh_step_up(principal)

    async def op() -> IdemResult:
        rr = (
            await session.execute(
                select(AccountRestriction).where(AccountRestriction.id == restriction_id).with_for_update()
            )
        ).scalar_one_or_none()
        if rr is None:
            raise ProblemError("not_found")
        return IdemResult(body=await unb.manual_verification(session, principal, rr, body.method, body.note))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


# --------------------------------------------------------------------------- unblock review (UNB-10..18)


async def _req(session: Any, request_id: uuid.UUID) -> UnblockRequest:
    ur = (
        await session.execute(select(UnblockRequest).where(UnblockRequest.id == request_id).with_for_update())
    ).scalar_one_or_none()
    if ur is None:
        raise ProblemError("not_found")
    return ur


@r.get("/security/review/unblock-requests", openapi_extra=NEUTRAL)
@sec_route
async def review_queue(
    session: PrincipalDbSession,
    state: str | None = None,
    principal: Principal = perm("security.unblock.triage"),
) -> dict[str, Any]:
    q = select(UnblockRequest, SecurityCase).join(SecurityCase, SecurityCase.id == UnblockRequest.case_id)
    q = q.where(UnblockRequest.state.in_(state.split(",") if state else list(cs.OPEN_UR)))
    rows = (await session.execute(q.order_by(UnblockRequest.submitted_at))).all()
    now = clock.now()
    return {
        "data": [
            {
                **unb.request_out(u, case_ref=c.case_ref),
                "level": c.level,
                "sla_state": cs.sla_state(c, now),
                "requires_second_approval": u.requires_second_approval,
                "manual_verification_required": u.state == "escalated"
                and unb.awaiting_manual_verification(u),
                "restriction_id": str(u.restriction_id) if u.restriction_id else None,
                "assignee": str(u.assigned_to) if u.assigned_to else None,
            }
            for u, c in rows
        ],
        "meta": {"info_templates": unb.INFO_TEMPLATES},
        "page": {"next_cursor": None, "has_more": False, "limit": 100},
    }


@r.get("/security/review/unblock-requests/{request_id}", openapi_extra=NEUTRAL)
@sec_route
async def review_get(
    request_id: uuid.UUID,
    session: PrincipalDbSession,
    reason_code: str | None = None,
    principal: Principal = perm("security.unblock.triage"),
) -> JSONResponse:
    code = require_reason_code(reason_code)
    ur = await _req(session, request_id)
    case = await session.get(SecurityCase, ur.case_id)
    await audit(
        session,
        principal,
        "unblock.viewed",
        "unblock_request",
        ur.id,
        subject_user_id=ur.user_id,
        reason_code=code,
    )
    body = {
        **unb.request_out(ur, case_ref=case.case_ref if case else None),
        "what_happened": ur.what_happened,
        "explanation": ur.explanation,
        "recognised_device_ids": [str(x) for x in ur.recognised_device_ids],
        "unrecognised_device_ids": [str(x) for x in ur.unrecognised_device_ids],
        "lab_location_text": ur.lab_location_text,
        "attachments": [unb.attachment_meta(a) for a in ur.attachments],
        "preferred_contact": ur.preferred_contact,
        "timeline": ur.timeline,
        "assigned_to": str(ur.assigned_to) if ur.assigned_to else None,
        "restriction_id": str(ur.restriction_id) if ur.restriction_id else None,
        "manual_verification_required": ur.state == "escalated" and unb.awaiting_manual_verification(ur),
    }
    return JSONResponse(body, headers=etag(ur.version))


@r.post("/security/review/unblock-requests/{request_id}/claim")
@sec_route
async def review_claim(
    request_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.unblock.triage"),
) -> JSONResponse:
    ur = await _req(session, request_id)
    check_if_match(request, ur.version)
    out = await unb.claim(session, principal, ur)
    return JSONResponse(out, headers=etag(ur.version))


@r.post("/security/review/unblock-requests/{request_id}/request-info")
@sec_route
async def review_info(
    request_id: uuid.UUID,
    body: InfoIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.unblock.triage"),
) -> JSONResponse:
    ur = await _req(session, request_id)
    check_if_match(request, ur.version)
    out = await unb.request_info(session, principal, ur, body.template_key, body.message)
    return JSONResponse(out, headers=etag(ur.version))


@r.post("/security/review/unblock-requests/{request_id}/escalate")
@sec_route
async def review_escalate(
    request_id: uuid.UUID,
    body: EscalateIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.unblock.triage"),
) -> JSONResponse:
    ur = await _req(session, request_id)
    check_if_match(request, ur.version)
    out = await unb.escalate(session, principal, ur, body.reason)
    return JSONResponse(out, headers=etag(ur.version))


@r.post("/security/review/unblock-requests/{request_id}/send-back")
@sec_route
async def review_send_back(
    request_id: uuid.UUID,
    body: SendBackIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = perm("security.case.decide"),
) -> JSONResponse:
    require_fresh_step_up(principal)
    ur = await _req(session, request_id)
    check_if_match(request, ur.version)
    out = await unb.send_back_request(session, principal, ur, body.note)
    return JSONResponse(out, headers=etag(ur.version))


@r.get("/security/review/unblock-requests/{request_id}/attachments/{attachment_id}", openapi_extra=NEUTRAL)
@sec_route
async def review_attachment(
    request_id: uuid.UUID,
    attachment_id: str,
    session: PrincipalDbSession,
    reason_code: str | None = None,
    principal: Principal = perm("security.evidence.read"),
) -> dict[str, Any]:
    """UNB-16: a 5-minute presigned viewer URL (inline, no download disposition) for a scanned
    attachment; audited with the reason code."""
    code = require_reason_code(reason_code)
    ur = await _req(session, request_id)
    url, expires_at, att = await unb.attachment_view_url(session, ur, attachment_id)
    await audit(
        session,
        principal,
        "unblock.attachment_viewed",
        "unblock_request",
        ur.id,
        subject_user_id=ur.user_id,
        reason_code=code,
        after={"attachment_id": attachment_id},
    )
    return {
        "attachment_id": att["attachment_id"],
        "filename": att["filename"],
        "content_type": att["content_type"],
        "url": url,
        "expires_at": to_rfc3339(expires_at),
        "download": False,
    }


@r.get("/support/unblock-requests", openapi_extra=NEUTRAL)
@sec_route
async def support_list(
    session: PrincipalDbSession, principal: Principal = perm("security.unblock.triage")
) -> dict[str, Any]:
    """UNB-17: support triage list. Carries the ids support needs to act (forward, and lifting
    L1/L2 via SEC-21); no evidence, explanation or device data."""
    rows = (
        await session.execute(
            select(UnblockRequest, SecurityCase)
            .join(SecurityCase, SecurityCase.id == UnblockRequest.case_id)
            .where(UnblockRequest.state.in_(list(cs.OPEN_UR)))
            .order_by(UnblockRequest.submitted_at, UnblockRequest.id)
        )
    ).all()
    users = {u.user_id for u, _ in rows}
    active: dict[uuid.UUID, list[AccountRestriction]] = {}
    if users:
        for ar in (
            await session.execute(
                select(AccountRestriction)
                .where(AccountRestriction.user_id.in_(users), AccountRestriction.ended_at.is_(None))
                .order_by(AccountRestriction.level.desc())
            )
        ).scalars():
            active.setdefault(ar.user_id, []).append(ar)
    return {
        "data": [
            {
                "request_id": str(u.id),
                "reference": u.reference,
                "case_ref": c.case_ref,
                "state": u.state,
                "level": c.level,
                "route": "support" if c.level <= 2 else "security",
                "submitted_at": to_rfc3339(u.submitted_at) if u.submitted_at else None,
                "restrictions": [
                    {
                        "restriction_id": str(ar.id),
                        "level": ar.level,
                        "family": ar.family,
                        "liftable_by_support": ar.level <= 2 and ar.family != "takeover",
                    }
                    for ar in active.get(u.user_id, [])
                ],
            }
            for u, c in rows
        ]
    }


@r.post("/support/unblock-requests/{request_id}/forward")
@sec_route
async def support_forward(
    request_id: uuid.UUID,
    body: EscalateIn,
    session: PrincipalDbSession,
    principal: Principal = perm("security.unblock.triage"),
) -> dict[str, Any]:
    ur = await _req(session, request_id)
    if ur.state not in cs.OPEN_UR:
        raise ProblemError("invalid_state_transition", current_state=ur.state, allowed=list(cs.OPEN_UR))
    case = await cs.get_case(session, ur.case_id, lock=True)
    await cs.case_note(
        session, case.id, principal.user_id, "internal", f"Forwarded by support: {body.reason}"
    )
    if case.priority in ("low", "medium"):
        case.priority = "high"
    case.version += 1
    await audit(
        session,
        principal,
        "unblock.forwarded",
        "unblock_request",
        ur.id,
        subject_user_id=ur.user_id,
        reason=body.reason,
    )
    return {"reference": ur.reference, "forwarded": True, "priority": case.priority}
