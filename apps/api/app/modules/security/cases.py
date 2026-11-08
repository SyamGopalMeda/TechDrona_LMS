"""Cases, reviewer decisions and second-person approval (UNB §4-§6; API SEC-03..12).

``case_decisions`` holds **final** decisions only. A decision that needs a second approver is an
``approval_requests`` row (``security.case.decision``) until a distinct reviewer approves it
(SEC-10), which inserts the decision in the same transaction (UNB §5.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import to_rfc3339
from app.modules.admin import approvals as apr
from app.modules.admin import policy as pol
from app.modules.identity import clock
from app.modules.identity.models import User
from app.modules.rbac import service as rs
from app.modules.rbac.catalogue import ADMIN_ROLE
from app.modules.rbac.models import ApprovalRequest
from app.modules.security import engine
from app.modules.security import restrictions as rx
from app.modules.security.catalogue import RULES_BY_KEY
from app.modules.security.models import (
    AccountRestriction,
    CaseDecision,
    CaseNote,
    SecurityCase,
    SecuritySignal,
    SecurityUserState,
    UnblockRequest,
)
from app.modules.sessions.models import UserDevice

LIFT_OUTCOMES = frozenset({"lift_false_positive", "lift_with_warning", "lift_conditions"})
OUTCOMES = LIFT_OUTCOMES | {"uphold", "convert_L4", "reduce_level"}
OPEN_UR = ("submitted", "under_review", "info_requested", "escalated")
APPEAL_DAYS = 14


def vf(field: str, code: str, message: str) -> ProblemError:
    return ProblemError("validation_failed", 422, errors=[{"field": field, "code": code, "message": message}])


async def get_case(session: AsyncSession, case_id: uuid.UUID, *, lock: bool = False) -> SecurityCase:
    q = select(SecurityCase).where(SecurityCase.id == case_id)
    if lock:
        q = q.with_for_update()
    c = (await session.execute(q)).scalar_one_or_none()
    if c is None:
        raise ProblemError("not_found")
    return c


async def case_restriction(session: AsyncSession, case: SecurityCase) -> AccountRestriction | None:
    return (
        await session.execute(
            select(AccountRestriction)
            .where(AccountRestriction.case_id == case.id, AccountRestriction.ended_at.is_(None))
            .order_by(AccountRestriction.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def open_request_for(session: AsyncSession, case_id: uuid.UUID) -> UnblockRequest | None:
    return (
        await session.execute(
            select(UnblockRequest)
            .where(UnblockRequest.case_id == case_id, UnblockRequest.state.in_((*OPEN_UR, "draft")))
            .with_for_update()
        )
    ).scalar_one_or_none()


def sla_state(c: SecurityCase, now: datetime) -> str:
    if c.status == "closed" or c.sla_decision_due is None:
        return "n/a"
    if now >= c.sla_decision_due:
        return "breached"
    total = (c.sla_decision_due - c.created_at).total_seconds() or 1
    return "breaching" if (now - c.created_at).total_seconds() / total >= 0.8 else "on_track"


async def latest_score(session: AsyncSession, user_id: uuid.UUID) -> float | None:
    st = await session.get(SecurityUserState, user_id)
    return float(st.sharing_score) if st is not None else None


def case_out(
    c: SecurityCase,
    *,
    score: float | None = None,
    ur: UnblockRequest | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or clock.now()
    return {
        "case_id": str(c.id),
        "case_ref": c.case_ref,
        "user_id": str(c.user_id),
        "family": c.family,
        "level": c.level,
        "recommended_level": c.recommended_level,
        "priority": c.priority,
        "status": c.status,
        "opened_reason": c.opened_reason,
        "hc_rule": c.hc_rule,
        "score": score,
        "age_hours": int((now - c.created_at).total_seconds() // 3600) if c.created_at else 0,
        "sla_first_response_due": to_rfc3339(c.sla_first_response_due) if c.sla_first_response_due else None,
        "sla_decision_due": to_rfc3339(c.sla_decision_due) if c.sla_decision_due else None,
        "sla_state": sla_state(c, now),
        "assignee_id": str(c.assignee_id) if c.assignee_id else None,
        "is_high_risk": c.is_high_risk,
        "high_risk_reasons": list(c.high_risk_reasons),
        "repeat_count": c.repeat_count,
        "organization_id": str(c.organization_id) if c.organization_id else None,
        "unblock_request": {"reference": ur.reference, "state": ur.state} if ur else None,
        "version": c.version,
    }


# --------------------------------------------------------------------------- conflicts


async def conflict_reasons(
    session: AsyncSession, reviewer: uuid.UUID, case: SecurityCase, r: AccountRestriction | None
) -> list[str]:
    """UNB §5 / §8: own account, applied the restriction, shared registered device.

    Single company: the former "same org" conflict is gone; every staff member and
    batch student shares the one company organization, so it no longer signals prior contact."""

    out: list[str] = []
    if reviewer == case.user_id:
        out.append("own_account")
    if r is not None and r.applied_by == reviewer:
        out.append("applied_restriction")
    shared = (
        await session.execute(
            select(func.count())
            .select_from(UserDevice)
            .where(
                UserDevice.user_id == reviewer,
                UserDevice.trust_status != "removed",
                UserDevice.device_id.in_(
                    select(UserDevice.device_id).where(UserDevice.user_id == case.user_id)
                ),
            )
        )
    ).scalar_one()
    if shared:
        out.append("shared_device")
    return out


async def require_no_conflict(
    session: AsyncSession,
    reviewer: uuid.UUID,
    case: SecurityCase,
    r: AccountRestriction | None,
    *,
    allow: tuple[str, ...] = (),
) -> None:
    reasons = [x for x in await conflict_reasons(session, reviewer, case, r) if x not in allow]
    if reasons:
        raise ProblemError("conflict_of_interest", reasons=reasons)


def contact_eligible(verified_at: datetime | None, restriction_start: datetime) -> bool:
    """Contacts verified before the restriction and not changed in the 7 days before it (UNB §6.3a)."""
    return verified_at is not None and verified_at < restriction_start - timedelta(days=7)


def has_eligible_contact(user: User | None, restriction_start: datetime) -> bool:
    """True when the student can re-verify by OTP; otherwise a senior reviewer verifies manually."""
    if user is None:
        return False
    return bool(
        (user.email and contact_eligible(user.email_verified_at, restriction_start))
        or (user.phone_e164 and contact_eligible(user.phone_verified_at, restriction_start))
    )


MANUAL_VERIFICATION = "manual_verification_required"


# --------------------------------------------------------------------------- decisions


def _validate_decision(body: dict[str, Any]) -> None:
    outcome = body.get("outcome")
    if outcome not in OUTCOMES:
        raise vf("outcome", "invalid", "Unknown outcome")
    summary = (body.get("student_summary") or "").strip()
    if len(summary) < 50:
        raise vf("student_summary", "too_short", "The student summary must be at least 50 characters")
    if not (body.get("rationale") or "").strip():
        raise vf("rationale", "required", "A rationale is required")
    if body.get("extension_days") and outcome != "lift_false_positive":
        raise vf("extension_days", "lift_only", "Extension days only apply to a false-positive lift")
    if outcome == "reduce_level" and body.get("resulting_level") not in (1, 2):
        raise vf("resulting_level", "invalid", "reduce_level needs resulting_level 1 or 2")
    exc = (body.get("conditions") or {}).get("user_exception")
    if exc:
        k = pol.spec(str(exc.get("setting_key")))
        if k.locked:
            raise vf("conditions.user_exception", "locked_key", "Locked keys cannot have user exceptions")
        pol.validate_value(k, exc.get("value"))
        try:
            exp = datetime.fromisoformat(str(exc.get("expires_at")).replace("Z", "+00:00"))
        except ValueError as e:
            raise vf("conditions.user_exception.expires_at", "invalid", "Invalid expiry") from e
        if exp <= clock.now() or exp > clock.now() + timedelta(days=180):
            raise vf(
                "conditions.user_exception.expires_at", "out_of_bounds", "Exceptions last at most 180 days"
            )


async def second_approval_reasons(
    session: AsyncSession,
    reviewer: uuid.UUID,
    case: SecurityCase,
    r: AccountRestriction | None,
    body: dict[str, Any],
) -> list[str]:
    """Computed, never accepted from the client (UNB §5 rules 1-5; SEC-09)."""
    out: list[str] = []
    outcome = body["outcome"]
    if r is not None and r.level >= 4 and case.is_high_risk and outcome != "uphold":
        out.append("l4_high_risk")
    if outcome == "lift_false_positive" and case.recommended_level == 4:
        score = await latest_score(session, case.user_id)
        if score is not None and score >= 90:
            out.append("overrides_recommend_l4")
    exc = (body.get("conditions") or {}).get("user_exception")
    if exc:
        k = pol.REGISTRY[str(exc["setting_key"])]
        exp = datetime.fromisoformat(str(exc["expires_at"]).replace("Z", "+00:00"))
        loosen = (
            isinstance(k.default, int | float)
            and not isinstance(k.default, bool)
            and float(exc["value"]) > 2 * float(k.default)
        )
        if loosen or exp > clock.now() + timedelta(days=90):
            out.append("exception_beyond_limits")
    if (body.get("conditions") or {}).get("contact_change"):
        out.append("contact_change")
    if outcome == "convert_L4" and "staff_account" in case.high_risk_reasons:
        out.append("l4_on_staff")
    return out


async def propose_decision(
    session: AsyncSession, principal: Principal, case: SecurityCase, body: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    """SEC-09. Returns (status, body): 201 final decision or 202 pending second approval."""
    _validate_decision(body)
    if case.status in ("closed",):
        raise ProblemError("invalid_state_transition", current_state=case.status, allowed=[])
    views = (case.panel_views or {}).get(str(principal.user_id), {})
    if not (views.get("explanation") and views.get("timeline")):
        raise ProblemError("explanation_not_viewed")
    r = await case_restriction(session, case)
    outcome = body["outcome"]
    from app.modules.security.policies import has_perm

    if (
        r is not None
        and r.level >= 3
        and outcome in LIFT_OUTCOMES | {"reduce_level"}
        and not await has_perm(session, principal, "security.restriction.lift_l3l4")
    ):
        raise ProblemError("permission_denied", permission="security.restriction.lift_l3l4")
    if outcome == "convert_L4" and not await has_perm(session, principal, "security.restriction.apply_l3l4"):
        raise ProblemError("permission_denied", permission="security.restriction.apply_l3l4")
    if outcome in LIFT_OUTCOMES | {"reduce_level", "uphold"} and r is None:
        raise ProblemError("invalid_state_transition", current_state="no_active_restriction", allowed=[])
    ur = await _decision_request(session, case, body)
    await require_no_conflict(session, principal.user_id, case, r)
    if ur is not None and ur.is_second_level_appeal and ur.rejected_by == principal.user_id:
        raise ProblemError("conflict_of_interest", reasons=["decided_original_request"])
    pending = (
        await session.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.action_type == "security.case.decision",
                ApprovalRequest.target_id == case.id,
                ApprovalRequest.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if pending is not None:
        raise ProblemError("second_approval_required", approval_request_id=str(pending.id))
    reasons = await second_approval_reasons(session, principal.user_id, case, r, body)
    payload = {
        "case_id": str(case.id),
        "restriction_id": str(r.id) if r else None,
        "unblock_request_id": str(ur.id) if ur else None,
        "outcome": outcome,
        "resulting_level": body.get("resulting_level"),
        "rationale": body["rationale"].strip(),
        "student_summary": body["student_summary"].strip(),
        "conditions": body.get("conditions") or {},
        "extension_days": int(body.get("extension_days") or 0),
        "false_positive_rule_keys": list(body.get("false_positive_rule_keys") or []),
        "second_approval_reasons": reasons,
    }
    if reasons:
        try:
            async with session.begin_nested():
                req = await apr.new_request(
                    session,
                    principal,
                    action_type="security.case.decision",
                    target_type="security_case",
                    target_id=case.id,
                    payload=payload,
                    reason="; ".join(reasons),
                    required_approver_role=ADMIN_ROLE,
                )
        except IntegrityError as e:
            raise ProblemError("second_approval_required") from e
        case.status = "escalated"
        case.escalated_at = clock.now()
        case.version += 1
        if ur is not None:
            await set_ur_state(session, ur, "escalated")
            ur.requires_second_approval = True
            ur.escalated_at = clock.now()
        await audit(
            session,
            principal,
            "case.decision.proposed",
            "security_case",
            case.id,
            subject_user_id=case.user_id,
            reason_code="case_review",
            after={"outcome": outcome, "reasons": reasons},
        )
        return 202, {
            "requires_second_approval": True,
            "approval_request_id": str(req.id),
            "expires_at": to_rfc3339(req.expires_at),
            "unblock_request": {"state": "escalated"} if ur else None,
            "approval": {
                "required_role": ADMIN_ROLE,
                "excludes": ["requested_by", "applied_by"],
            },
        }
    d = await finalize_decision(session, principal, case, payload, decided_by=principal.user_id)
    return 201, d


async def _decision_request(
    session: AsyncSession, case: SecurityCase, body: dict[str, Any]
) -> UnblockRequest | None:
    rid = body.get("unblock_request_id")
    ur = await open_request_for(session, case.id)
    if rid is not None:
        if ur is None or str(ur.id) != str(rid):
            raise ProblemError("not_found")
    return ur


async def set_ur_state(
    session: AsyncSession,
    ur: UnblockRequest,
    state: str,
    *,
    note: dict[str, Any] | None = None,
    closure: str | None = None,
) -> None:
    now = clock.now()
    ur.state = state
    ur.state_changed_at = now
    if state == "closed":
        ur.closure_reason = closure
    entry: dict[str, Any] = {"at": to_rfc3339(now), "state": state}
    if closure:
        entry["closure_reason"] = closure
    if note:
        entry.update(note)
    ur.timeline = [*ur.timeline, entry]
    ur.version += 1
    await session.flush()


async def finalize_decision(
    session: AsyncSession,
    actor: Principal,
    case: SecurityCase,
    payload: dict[str, Any],
    *,
    decided_by: uuid.UUID,
    approved_by: uuid.UUID | None = None,
    approval_request_id: uuid.UUID | None = None,
    skip_reverification: bool = False,
) -> dict[str, Any]:
    now = clock.now()
    outcome = payload["outcome"]
    r = (
        await session.get(AccountRestriction, uuid.UUID(payload["restriction_id"]))
        if payload.get("restriction_id")
        else None
    )
    ur = (
        await session.get(UnblockRequest, uuid.UUID(payload["unblock_request_id"]))
        if payload.get("unblock_request_id")
        else None
    )
    requires = bool(payload.get("second_approval_reasons"))
    d = CaseDecision(
        id=uuid7(),
        created_at=clock.now(),
        case_id=case.id,
        unblock_request_id=ur.id if ur else None,
        outcome=outcome,
        resulting_level=payload.get("resulting_level"),
        rationale=payload["rationale"],
        student_summary=payload["student_summary"],
        conditions=payload.get("conditions") or {},
        extension_days=int(payload.get("extension_days") or 0),
        false_positive_rule_keys=list(payload.get("false_positive_rule_keys") or []),
        decided_by=decided_by,
        requires_second_approval=requires,
        approved_by=approved_by,
        approved_at=now if approved_by else None,
        approval_request_id=approval_request_id,
    )
    session.add(d)
    await session.flush()
    restriction_state = None
    manual = False
    if outcome in LIFT_OUTCOMES:
        if r is not None and r.ended_at is None:
            r.decision_id = d.id
            if skip_reverification:
                await rx.end_restriction(
                    session, r, "case_decision", ended_by=decided_by, decision_id=d.id, actor=actor
                )
                restriction_state = "ended"
            else:
                r.lift_pending_at = now
                restriction_state = "lift_pending"
                subject = await session.get(User, case.user_id)
                if not has_eligible_contact(subject, r.starts_at):
                    # UNB §4.2 / §6.3a: no contact that predates the restriction by 7 days, so OTP
                    # re-verification is impossible; a senior reviewer verifies manually.
                    manual = True
        case.status = "decided"
        if ur is not None and manual:
            await set_ur_state(session, ur, "escalated", note={"escalation_reason": MANUAL_VERIFICATION})
            ur.decided_at = now
            ur.escalated_at = now
        elif ur is not None:
            await set_ur_state(session, ur, "approved")
            ur.decided_at = now
        if outcome == "lift_false_positive":
            await suppress_signals(session, case, r, d)
        await _user_exception(session, case, d, decided_by)
    elif outcome == "uphold":
        case.status = "decided"
        if ur is not None:
            await set_ur_state(
                session,
                ur,
                "rejected",
                note={"appeal_deadline": to_rfc3339(now + timedelta(days=APPEAL_DAYS))},
            )
            ur.decided_at = now
            ur.rejected_by = decided_by
            if ur.is_second_level_appeal:
                await set_ur_state(session, ur, "closed", closure="rejected_final")
        restriction_state = "active"
    elif outcome == "convert_L4":
        nr, _ = await rx.apply_restriction(
            session,
            user_id=case.user_id,
            level=4,
            family=case.family if case.family == "sharing" else "sharing",
            source="reviewer",
            actor=actor,
            case_id=case.id,
            applied_by=decided_by,
            reason=payload["rationale"],
        )
        nr.decision_id = d.id
        case.level = 4
        case.status = "decided"
        if ur is not None:
            await set_ur_state(session, ur, "rejected")
            ur.decided_at = now
            ur.rejected_by = decided_by
        restriction_state = "active"
    elif outcome == "reduce_level":
        lvl = int(payload["resulting_level"])
        nr, _ = await rx.apply_restriction(
            session,
            user_id=case.user_id,
            level=lvl,
            family="sharing",
            source="reviewer",
            actor=actor,
            case_id=case.id,
            applied_by=decided_by,
            reason=payload["rationale"],
        )
        nr.decision_id = d.id
        case.level = lvl
        case.status = "decided"
        if ur is not None:
            await set_ur_state(session, ur, "approved")
            await set_ur_state(session, ur, "closed", closure="completed")
        restriction_state = "reduced"
    case.version += 1
    if case.first_response_at is None:
        case.first_response_at = now
    await session.flush()
    await case_note(session, case.id, None, "student", payload["student_summary"])
    await audit(
        session,
        actor,
        "case.decide",
        "security_case",
        case.id,
        subject_user_id=case.user_id,
        reason_code="case_review",
        reason=payload["rationale"][:500],
        after={
            "decision_id": str(d.id),
            "outcome": outcome,
            "decided_by": str(decided_by),
            "approved_by": str(approved_by) if approved_by else None,
        },
    )
    if outcome in LIFT_OUTCOMES and manual:
        await engine.notify_user(
            session,
            case.user_id,
            "security.review_approved",
            subject="Your review was approved — a senior reviewer will confirm it's you",
            text_body=f"{payload['student_summary']} Case reference: {case.case_ref}. "
            "Your contact details changed recently, so a senior reviewer will contact you to "
            "confirm your identity before access is restored. You don't need to do anything now.",
            data={"case_ref": case.case_ref},
        )
    elif outcome in LIFT_OUTCOMES and not skip_reverification:
        await engine.notify_user(
            session,
            case.user_id,
            "security.review_approved",
            subject="Your review was approved — finish these steps to get back in",
            text_body=f"{payload['student_summary']} Case reference: {case.case_ref}. "
            "Sign in, confirm with a "
            "code and review your devices to restore access.",
            data={"case_ref": case.case_ref},
        )
    elif outcome in ("uphold", "convert_L4"):
        await engine.notify_user(
            session,
            case.user_id,
            "security.review_rejected",
            subject="Decision on your review request",
            text_body=f"{payload['student_summary']} You can appeal once within 14 days. If you are not "
            "satisfied you can also use our grievance route (/help/grievance).",
            data={"case_ref": case.case_ref},
        )
    return {
        "decision_id": str(d.id),
        "case_ref": case.case_ref,
        "outcome": outcome,
        "requires_second_approval": requires,
        "decided_by": str(decided_by),
        "approved_by": str(approved_by) if approved_by else None,
        "approved_at": to_rfc3339(d.approved_at) if d.approved_at else None,
        "restriction": {"restriction_id": str(r.id) if r else None, "state": restriction_state},
        "unblock_request": {"reference": ur.reference, "state": ur.state} if ur else None,
        "next": ("manual_verification" if manual else "student_reverification")
        if restriction_state == "lift_pending"
        else None,
    }


async def suppress_signals(
    session: AsyncSession, case: SecurityCase, r: AccountRestriction | None, d: CaseDecision
) -> int:
    """FP lift: the signals that drove the decision get ``suppressed_by_decision_id`` (UNB §6
    step 9); the score is then recomputed without them and the H8/breaker counters move."""
    keys = list(d.false_positive_rule_keys) or (list(r.rule_keys) if r is not None else [])
    if not keys:
        keys = [k for k, v in RULES_BY_KEY.items() if v.family == "sharing"]
    until = r.starts_at if r is not None else clock.now()
    res = await session.execute(
        update(SecuritySignal)
        .where(
            SecuritySignal.user_id == case.user_id,
            SecuritySignal.family == "sharing",
            SecuritySignal.rule_key.in_(keys),
            SecuritySignal.occurred_at <= until + timedelta(minutes=1),
            SecuritySignal.suppressed_by_decision_id.is_(None),
        )
        .values(suppressed_by_decision_id=d.id)
        .execution_options(synchronize_session=False)
    )
    st = await rx.get_state(session, case.user_id)
    st.l2_issued_at = None
    st.l2_passed_at = None
    st.sharing_score = Decimal(0)
    await session.flush()
    if r is not None and r.hc_rule:
        await engine.check_fp_breaker(session, r.hc_rule)
    return int(getattr(res, "rowcount", 0) or 0)


async def _user_exception(session: AsyncSession, case: SecurityCase, d: CaseDecision, by: uuid.UUID) -> None:
    exc = (d.conditions or {}).get("user_exception")
    if not exc:
        return
    exp = datetime.fromisoformat(str(exc["expires_at"]).replace("Z", "+00:00"))
    await pol.write_setting(
        session,
        key=str(exc["setting_key"]),
        scope_type="user",
        scope_id=case.user_id,
        value=exc["value"],
        changed_by=by,
        change_reason=f"case decision {case.case_ref}",
        expires_at=exp,
        case_decision_id=d.id,
    )
    await audit(
        session,
        AuditActor("user", user_id=by),
        "security.exception.granted",
        "user",
        case.user_id,
        subject_user_id=case.user_id,
        after={"setting_key": exc["setting_key"], "expires_at": exc["expires_at"]},
    )


async def approve_proposal(
    session: AsyncSession, principal: Principal, case: SecurityCase, approval_id: uuid.UUID, note: str | None
) -> dict[str, Any]:
    """SEC-10: the second reviewer approves → the final ``case_decisions`` row."""
    req = await _proposal(session, case, approval_id)
    if req.requested_by == principal.user_id:
        raise ProblemError(
            "sod_violation", rule="SoD-06", detail="The second approver must be a different person."
        )
    r = (
        await session.get(AccountRestriction, uuid.UUID(req.payload["restriction_id"]))
        if req.payload.get("restriction_id")
        else None
    )
    if r is not None and r.applied_by == principal.user_id:
        raise ProblemError("sod_violation", rule="SoD-06", detail="You applied this restriction.")
    await require_no_conflict(session, principal.user_id, case, r)
    from app.modules.security.policies import has_perm

    # D2: the second approver is a different admin (maker != checker, checked above).
    if not (
        principal.has_role(ADMIN_ROLE, "platform")
        and await has_perm(session, principal, "security.restriction.lift_l3l4")
        and await has_perm(session, principal, "approval.decide")
    ):
        raise ProblemError("permission_denied", permission="security.restriction.lift_l3l4")
    if rs.payload_hash(req.payload) != req.payload_hash:
        raise ProblemError("invalid_state_transition", current_state="payload_tampered", allowed=[])
    now = clock.now()
    req.status = "approved"
    req.decided_by = principal.user_id
    req.decided_at = now
    req.decision_note = note
    await session.flush()
    out = await finalize_decision(
        session,
        principal,
        case,
        req.payload,
        decided_by=req.requested_by,
        approved_by=principal.user_id,
        approval_request_id=req.id,
    )
    req.status = "executed"
    req.executed_at = clock.now()
    await session.flush()
    await audit(
        session,
        principal,
        "case.decision.approved",
        "approval_request",
        req.id,
        subject_user_id=case.user_id,
        reason_code="case_review",
        reason=note,
    )
    return {"approval_request_id": str(req.id), **out}


PROPOSAL_FIELDS = (
    "outcome",
    "resulting_level",
    "rationale",
    "student_summary",
    "extension_days",
    "conditions",
    "false_positive_rule_keys",
    "second_approval_reasons",
)


async def pending_proposal(
    session: AsyncSession, principal: Principal, case: SecurityCase
) -> dict[str, Any] | None:
    """SEC-04 ``pending_approval``: the open ``security.case.decision`` proposal (pending, or
    pending past its 72 h expiry → ``expired``) with what the caller may do with it."""
    req = (
        await session.execute(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.action_type == "security.case.decision",
                ApprovalRequest.target_id == case.id,
                ApprovalRequest.status.in_(("pending", "expired")),
            )
            .order_by(ApprovalRequest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if req is None:
        return None
    now = clock.now()
    status = "expired" if req.status == "expired" or req.expires_at <= now else "pending"
    if status == "expired" and case.status != "escalated":
        return None
    is_requester = req.requested_by == principal.user_id
    can_decide = False
    if status == "pending" and not is_requester:
        r = (
            await session.get(AccountRestriction, uuid.UUID(req.payload["restriction_id"]))
            if req.payload.get("restriction_id")
            else None
        )
        from app.modules.security.policies import has_perm

        conflicts = await conflict_reasons(session, principal.user_id, case, r)
        can_decide = (
            not conflicts
            and principal.has_role(ADMIN_ROLE, "platform")
            and await has_perm(session, principal, "security.restriction.lift_l3l4")
            and await has_perm(session, principal, "approval.decide")
        )
    created = to_rfc3339(req.created_at) if req.created_at else None
    return {
        "approval_request_id": str(req.id),
        "status": status,
        "requested_by": str(req.requested_by),
        "requested_at": created,
        "created_at": created,
        "expires_at": to_rfc3339(req.expires_at),
        "reasons": list(req.payload.get("second_approval_reasons") or []),
        "payload": {k: req.payload.get(k) for k in PROPOSAL_FIELDS},
        "is_requester": is_requester,
        "can_decide": can_decide,
        "can_withdraw": is_requester and status == "pending",
    }


async def _proposal(session: AsyncSession, case: SecurityCase, approval_id: uuid.UUID) -> ApprovalRequest:
    req = (
        await session.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()
        )
    ).scalar_one_or_none()
    if req is None or req.action_type != "security.case.decision" or req.target_id != case.id:
        raise ProblemError("not_found")
    if req.status != "pending":
        raise ProblemError("invalid_state_transition", current_state=req.status, allowed=[])
    if req.expires_at <= clock.now():
        raise ProblemError("invalid_state_transition", current_state="expired", allowed=[])
    return req


async def send_back(
    session: AsyncSession, principal: Principal, case: SecurityCase, approval_id: uuid.UUID, note: str
) -> dict[str, Any]:
    req = await _proposal(session, case, approval_id)
    if req.requested_by == principal.user_id:
        raise ProblemError("sod_violation", rule="SoD-06")
    req.status = "rejected"
    req.decided_by = principal.user_id
    req.decided_at = clock.now()
    req.decision_note = note
    case.status = "under_review"
    case.version += 1
    ur = await open_request_for(session, case.id)
    if ur is not None and ur.state == "escalated":
        await set_ur_state(session, ur, "under_review", note={"note": "sent_back"})
    await session.flush()
    await audit(
        session,
        principal,
        "case.decision.sent_back",
        "approval_request",
        req.id,
        subject_user_id=case.user_id,
        reason_code="case_review",
        reason=note,
    )
    return {
        "approval_request_id": str(req.id),
        "status": "rejected",
        "unblock_request": {"state": ur.state} if ur else None,
    }


async def withdraw_proposal(
    session: AsyncSession, principal: Principal, case: SecurityCase, approval_id: uuid.UUID
) -> dict[str, Any]:
    req = await _proposal(session, case, approval_id)
    if req.requested_by != principal.user_id:
        raise ProblemError("permission_denied", permission="security.case.decide")
    req.status = "cancelled"
    await session.flush()
    await audit(
        session,
        principal,
        "case.decision.withdrawn",
        "approval_request",
        req.id,
        subject_user_id=case.user_id,
    )
    return {"approval_request_id": str(req.id), "status": "cancelled"}


async def case_note(
    session: AsyncSession, case_id: uuid.UUID, author: uuid.UUID | None, visibility: str, body: str
) -> CaseNote:
    n = CaseNote(id=uuid7(), case_id=case_id, author_id=author, visibility=visibility, body=body[:4000])
    session.add(n)
    await session.flush()
    return n


async def mark_viewed(session: AsyncSession, case: SecurityCase, reviewer: uuid.UUID, panel: str) -> None:
    views = dict(case.panel_views or {})
    mine = dict(views.get(str(reviewer), {}))
    mine[panel] = to_rfc3339(clock.now())
    views[str(reviewer)] = mine
    case.panel_views = views
    await session.flush()


async def student_projection(session: AsyncSession, case: SecurityCase) -> dict[str, Any]:
    notes = (
        (
            await session.execute(
                select(CaseNote)
                .where(CaseNote.case_id == case.id, CaseNote.visibility == "student")
                .order_by(CaseNote.created_at)
            )
        )
        .scalars()
        .all()
    )
    d = (
        await session.execute(
            select(CaseDecision)
            .where(CaseDecision.case_id == case.id)
            .order_by(CaseDecision.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    r = await case_restriction(session, case)
    return {
        "case_ref": case.case_ref,
        "family": case.family,
        "level": case.level,
        "status": case.status,
        "restriction": {
            "level": r.level,
            "until": to_rfc3339(r.ends_at) if r and r.ends_at else None,
            "state": "lift_pending" if r and r.lift_pending_at else "active",
        }
        if r
        else None,
        "notes": [{"at": to_rfc3339(n.created_at), "body": n.body} for n in notes],
        "decision": {
            "outcome": d.outcome,
            "summary": d.student_summary,
            "decided_at": to_rfc3339(d.created_at),
        }
        if d
        else None,
    }


async def subject_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    u = await session.get(User, user_id)
    if u is None:
        raise ProblemError("not_found")
    return u
