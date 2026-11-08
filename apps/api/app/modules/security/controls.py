"""Engine controls: kill switch (RE §5.7; SEC-42/43), rule versions (RE §5.4; SEC-22..29), bulk
false-positive lift (RE §5.8; SEC-44/45) and the dual-control executors registered with
``admin.approvals`` (``risk.kill_switch.ratify``, ``risk.ruleset.activate``,
``risk.ruleset.rollback``, ``security.restriction.bulk_lift``, ``security.export.per_user``,
``export.bulk_pii``)."""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import to_rfc3339
from app.modules.admin import approvals as apr
from app.modules.admin import policy as pol
from app.modules.identity import clock
from app.modules.rbac.catalogue import ADMIN_ROLE, admin_roles
from app.modules.rbac.models import ApprovalRequest
from app.modules.security import cases as cs
from app.modules.security import engine
from app.modules.security.catalogue import BUILTIN_HC, BUILTIN_RULESETS, RULES_BY_KEY
from app.modules.security.models import (
    AccountRestriction,
    RiskEvaluation,
    RiskRule,
    RiskRuleVersion,
    SecurityBulkLift,
    SecurityCase,
    SecurityReportExport,
    SecuritySignal,
    UnblockRequest,
)
from app.modules.security.policies import sharing_policy
from app.modules.security.rules import SharingContext, score_sharing

SHADOW_DAYS = 14
BULK_MAX = 5000
BULK_SUMMARY = (
    "An error in our account-protection system paused your learning access. We've removed the pause "
    "and credited the restricted days to your access. You don't need to do anything else."
)


# --------------------------------------------------------------------------- kill switch


async def engine_state(session: AsyncSession) -> dict[str, Any]:
    rules = []
    for key in BUILTIN_HC:
        v = await engine.rule_version(session, key)
        status, _, semver = await engine.rule_status(session, key)
        rules.append(
            {
                "rule_key": key,
                "status": status,
                "semver": semver,
                "source": "db" if v is not None else "builtin",
                "status_change_reason": v.status_change_reason if v is not None else None,
                "circuit_breaker": "open"
                if v is not None and v.status_change_reason == "circuit_breaker" and v.status == "shadow"
                else "closed",
            }
        )
    pending = (
        (
            await session.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.action_type == "risk.kill_switch.ratify",
                    ApprovalRequest.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    rulesets = {}
    for fam in BUILTIN_RULESETS:
        _, rv = await engine.ruleset(session, fam)
        rulesets[fam] = rv
    return {
        "risk.mode": await pol.get_value(session, "risk.mode"),
        "risk.hc.auto_restrict_enabled": await pol.get_value(session, "risk.hc.auto_restrict_enabled"),
        "rules": rules,
        "rulesets": rulesets,
        "pending_ratifications": [apr.approval_out(p) for p in pending],
    }


async def kill_switch(
    session: AsyncSession, principal: Principal, target: str, rule_key: str | None, reason: str
) -> dict[str, Any]:
    applied: dict[str, Any] = {"target": target, "effective_within_seconds": 60}
    if target == "risk_mode":
        cur = await pol.get_value(session, "risk.mode")
        if cur != "enforce":
            raise ProblemError("invalid_state_transition", current_state=str(cur), allowed=["enforce"])
        await pol.write_setting(
            session,
            key="risk.mode",
            scope_type="platform",
            scope_id=None,
            value="shadow",
            changed_by=principal.user_id,
            change_reason=f"kill switch: {reason}",
        )
        applied["risk.mode"] = "shadow"
    elif target == "hc_all":
        if not await pol.get_value(session, "risk.hc.auto_restrict_enabled"):
            raise ProblemError("invalid_state_transition", current_state="false", allowed=["true"])
        await pol.write_setting(
            session,
            key="risk.hc.auto_restrict_enabled",
            scope_type="platform",
            scope_id=None,
            value=False,
            changed_by=principal.user_id,
            change_reason=f"kill switch: {reason}",
        )
        applied["risk.hc.auto_restrict_enabled"] = False
    elif target == "rule":
        if not rule_key or rule_key not in RULES_BY_KEY:
            raise cs.vf("rule_key", "required", "rule_key is required for target=rule")
        v = await engine.rule_version(session, rule_key)
        if v is None or v.status != "active":
            raise ProblemError(
                "invalid_state_transition", current_state=v.status if v else "shadow", allowed=["active"]
            )
        v.status = "shadow"
        v.status_changed_at = clock.now()
        v.status_changed_by = principal.user_id
        v.status_change_reason = "kill_switch"
        await session.execute(update(RiskRule).where(RiskRule.key == rule_key).values(active_version_id=None))
        applied["rule_key"] = rule_key
        applied["status"] = "shadow"
    else:
        raise cs.vf("target", "invalid", "target must be risk_mode, hc_all or rule")
    req = await apr.new_request(
        session,
        principal,
        action_type="risk.kill_switch.ratify",
        target_type="risk_engine",
        target_id=None,
        payload={"target": target, "rule_key": rule_key, "reason": reason},
        reason=reason,
        required_approver_role=ADMIN_ROLE,
    )
    await session.flush()
    await audit(session, principal, "risk.kill_switch", "risk_engine", None, reason=reason, after=applied)
    return {
        "applied": applied,
        "ratification": {
            "approval_request_id": str(req.id),
            "action_type": req.action_type,
            "due_at": to_rfc3339(
                req.created_at + timedelta(hours=24) if req.created_at else clock.now() + timedelta(hours=24)
            ),
        },
    }


# --------------------------------------------------------------------------- rule versions


async def rule_id(session: AsyncSession, key: str) -> uuid.UUID:
    rid = (await session.execute(select(RiskRule.id).where(RiskRule.key == key))).scalar_one_or_none()
    if rid is None:
        raise ProblemError("not_found")
    return rid


def version_out(v: RiskRuleVersion, rule_key: str | None = None) -> dict[str, Any]:
    eligible = v.shadow_started_at + timedelta(days=SHADOW_DAYS) if v.shadow_started_at else None
    return {
        "version_id": str(v.id),
        "rule_key": rule_key,
        "family": v.family,
        "ruleset_version": v.ruleset_version,
        "semver": v.semver,
        "status": v.status,
        "definition": v.definition,
        "shadow_started_at": to_rfc3339(v.shadow_started_at) if v.shadow_started_at else None,
        "eligible_at": to_rfc3339(eligible) if eligible else None,
        "proposed_by": str(v.proposed_by),
        "approved_by": str(v.approved_by) if v.approved_by else None,
        "status_change_reason": v.status_change_reason,
    }


async def create_version(
    session: AsyncSession, principal: Principal, body: dict[str, Any]
) -> RiskRuleVersion:
    family = body.get("family")
    rule_key = body.get("rule_key")
    if rule_key:
        rd = RULES_BY_KEY.get(rule_key)
        if rd is None:
            raise cs.vf("rule_key", "unknown", "Unknown rule")
        family = rd.family
    if family not in BUILTIN_RULESETS:
        raise cs.vf("family", "invalid", "Unknown family")
    definition = body.get("definition")
    if not isinstance(definition, dict):
        raise cs.vf("definition", "invalid", "definition must be an object")
    v = RiskRuleVersion(
        id=uuid7(),
        created_at=clock.now(),
        rule_id=await rule_id(session, rule_key) if rule_key else None,
        family=family,
        ruleset_version=f"{family}-{body['semver']}" if not rule_key else f"{rule_key}-{body['semver']}",
        semver=body["semver"],
        definition=definition,
        status="draft",
        proposed_by=principal.user_id,
    )
    session.add(v)
    await session.flush()
    await audit(
        session,
        principal,
        "security.rule.proposed",
        "risk_rule_version",
        v.id,
        after={"rule_key": rule_key, "family": family, "semver": v.semver},
    )
    return v


async def get_version(session: AsyncSession, version_id: uuid.UUID) -> tuple[RiskRuleVersion, str | None]:
    v = await session.get(RiskRuleVersion, version_id)
    if v is None:
        raise ProblemError("not_found")
    key = None
    if v.rule_id:
        key = (await session.execute(select(RiskRule.key).where(RiskRule.id == v.rule_id))).scalar_one()
    return v, key


async def start_shadow(session: AsyncSession, principal: Principal, v: RiskRuleVersion) -> None:
    if v.status != "draft":
        raise ProblemError("invalid_state_transition", current_state=v.status, allowed=["draft"])
    v.status = "shadow"
    v.shadow_started_at = clock.now()
    v.status_changed_at = clock.now()
    v.status_changed_by = principal.user_id
    v.status_change_reason = "shadow_start"
    await session.flush()


async def shadow_report(session: AsyncSession, v: RiskRuleVersion, rule_key: str | None) -> dict[str, Any]:
    """Level distribution of the active ruleset vs this version over the last 30 days of
    sharing signals (adults only; SEC-25/27). Users are counted, ids are masked."""
    if v.family != "sharing" or rule_key:
        report: dict[str, Any] = {
            "family": v.family,
            "rule_key": rule_key,
            "note": "deterministic rule: no score diff",
            "generated_at": to_rfc3339(clock.now()),
        }
        v.shadow_report = report
        return report
    now = clock.now()
    active_def, active_v = await engine.ruleset(session, "sharing")
    cand = {**BUILTIN_RULESETS["sharing"], **v.definition}
    policy = await sharing_policy(session)
    users = (
        (
            await session.execute(
                select(SecuritySignal.user_id)
                .where(
                    SecuritySignal.family == "sharing", SecuritySignal.occurred_at > now - timedelta(days=30)
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    dist_a: dict[int, int] = {}
    dist_b: dict[int, int] = {}
    newly: list[str] = []
    for uid in users:
        if uid is None:
            continue
        rows = await engine.user_signals(session, uid, "sharing", now - timedelta(days=30), now)
        sigs = [engine.to_sig(r) for r in rows]
        ctx = SharingContext()
        a = score_sharing(sigs, now, policy, ctx, {k: float(x) for k, x in active_def["caps"].items()})
        b = score_sharing(sigs, now, policy, ctx, {k: float(x) for k, x in cand["caps"].items()})
        dist_a[a.level_after] = dist_a.get(a.level_after, 0) + 1
        dist_b[b.level_after] = dist_b.get(b.level_after, 0) + 1
        if b.level_after > a.level_after:
            newly.append(str(uid)[:8] + "…")
    report = {
        "active": active_v,
        "candidate": v.ruleset_version,
        "users": len(users),
        "level_distribution": {"active": dist_a, "candidate": dist_b},
        "newly_flagged": newly[:50],
        "newly_flagged_count": len(newly),
        "generated_at": to_rfc3339(now),
    }
    v.shadow_report = report
    await session.flush()
    return report


async def request_activation(
    session: AsyncSession,
    principal: Principal,
    v: RiskRuleVersion,
    rule_key: str | None,
    reason: str,
    *,
    rollback: bool = False,
) -> ApprovalRequest:
    if rollback:
        if v.status != "retired":
            raise ProblemError("invalid_state_transition", current_state=v.status, allowed=["retired"])
    else:
        if v.status != "shadow":
            raise ProblemError("invalid_state_transition", current_state=v.status, allowed=["shadow"])
        assert v.shadow_started_at is not None
        eligible = v.shadow_started_at + timedelta(days=SHADOW_DAYS)
        if clock.now() < eligible:
            raise ProblemError(
                "shadow_period_incomplete",
                shadow_started_at=to_rfc3339(v.shadow_started_at),
                eligible_at=to_rfc3339(eligible),
            )
        if v.shadow_report is None:
            await shadow_report(session, v, rule_key)
    return await apr.new_request(
        session,
        principal,
        action_type="risk.ruleset.rollback" if rollback else "risk.ruleset.activate",
        target_type="risk_rule_version",
        target_id=v.id,
        payload={"version_id": str(v.id), "rule_key": rule_key, "reason": reason},
        reason=reason,
        required_approver_role="super_admin",
    )


async def _activate(session: AsyncSession, principal: Principal, req: ApprovalRequest) -> dict[str, Any]:
    v, key = await get_version(session, uuid.UUID(req.payload["version_id"]))
    rollback = req.action_type == "risk.ruleset.rollback"
    if v.status != ("retired" if rollback else "shadow"):
        raise ProblemError("invalid_state_transition", current_state=v.status, allowed=[])
    now = clock.now()
    q = select(RiskRuleVersion).where(RiskRuleVersion.status == "active", RiskRuleVersion.id != v.id)
    q = (
        q.where(RiskRuleVersion.rule_id == v.rule_id)
        if v.rule_id
        else q.where(RiskRuleVersion.rule_id.is_(None), RiskRuleVersion.family == v.family)
    )
    for old in (await session.execute(q)).scalars():
        old.status = "retired"
        old.status_changed_at = now
        old.status_changed_by = principal.user_id
        old.status_change_reason = "retire"
    await session.flush()
    v.status = "active"
    v.approved_by = principal.user_id
    v.approved_at = now
    v.approval_request_id = req.id
    v.effective_from = now
    v.status_changed_at = now
    v.status_changed_by = principal.user_id
    v.status_change_reason = "rollback" if rollback else "activation"
    await session.flush()
    if v.rule_id:
        await session.execute(update(RiskRule).where(RiskRule.id == v.rule_id).values(active_version_id=v.id))
    await audit(
        session,
        principal,
        "security.rule.activated",
        "risk_rule_version",
        v.id,
        after={"rule_key": key, "semver": v.semver, "rollback": rollback},
    )
    return {"version_id": str(v.id), "status": "active"}


async def _activation_check(session: AsyncSession, principal: Principal, req: ApprovalRequest) -> None:
    v = await session.get(RiskRuleVersion, uuid.UUID(req.payload["version_id"]))
    if v is not None and v.proposed_by == principal.user_id:
        raise ProblemError(
            "sod_violation", rule="SoD-05", detail="The proposer of a rule version cannot approve it."
        )


async def _ratify(session: AsyncSession, principal: Principal, req: ApprovalRequest) -> dict[str, Any]:
    await audit(
        session, principal, "risk.kill_switch.ratified", "approval_request", req.id, after=req.payload
    )
    return {"ratified": True}


# --------------------------------------------------------------------------- bulk lift


def _parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


async def _matches_network(
    session: AsyncSession, r: AccountRestriction, cidr: str | None, asn: int | None
) -> bool:
    if not cidr and asn is None:
        return True
    ev = (
        (
            await session.execute(select(RiskEvaluation.signals).where(RiskEvaluation.id == r.evaluation_id))
        ).scalar_one_or_none()
        if r.evaluation_id
        else None
    )
    nets: list[str] = []
    for c in ev or []:
        e = c.get("evidence", {})
        nets += [n for n in (e.get("net_a"), e.get("net_b")) if n]
    target = ipaddress.ip_network(cidr, strict=False) if cidr else None
    for n in nets:
        a, _, p = n.partition(":")
        if asn is not None and a == f"AS{asn}":
            return True
        if target is not None:
            try:
                if ipaddress.ip_network(p, strict=False).overlaps(target):
                    return True
            except ValueError:
                continue
    return False


async def bulk_select(
    session: AsyncSession, selector: dict[str, Any]
) -> tuple[list[AccountRestriction], dict[str, int], dict[uuid.UUID, SecurityCase]]:
    q = select(AccountRestriction).where(AccountRestriction.ended_at.is_(None))
    if selector.get("ruleset_version"):
        rv = str(selector["ruleset_version"])
        q = q.where(AccountRestriction.ruleset_version.in_((rv, f"sharing-{rv}")))
    frm, to = _parse_ts(selector.get("applied_from")), _parse_ts(selector.get("applied_to"))
    if frm:
        q = q.where(AccountRestriction.starts_at >= frm)
    if to:
        q = q.where(AccountRestriction.starts_at <= to)
    rows = list((await session.execute(q)).scalars())
    excluded = {"l4": 0, "high_risk": 0, "takeover": 0, "human_applied": 0, "pending_decision": 0}
    matched: list[AccountRestriction] = []
    cases: dict[uuid.UUID, SecurityCase] = {}
    rule_key = selector.get("rule_key")
    for r in rows:
        if r.level < 3:
            continue
        if rule_key and rule_key != r.hc_rule and rule_key not in (r.rule_keys or []):
            continue
        case = await session.get(SecurityCase, r.case_id) if r.case_id else None
        if not await _matches_network(session, r, selector.get("network_cidr"), selector.get("asn")):
            continue
        if r.level >= 4:
            excluded["l4"] += 1
            continue
        if r.family == "takeover":
            excluded["takeover"] += 1
            continue
        if r.source != "engine":
            excluded["human_applied"] += 1
            continue
        if case is not None and case.is_high_risk:
            excluded["high_risk"] += 1
            continue
        pending = (
            (
                await session.execute(
                    select(ApprovalRequest.id).where(
                        ApprovalRequest.action_type == "security.case.decision",
                        ApprovalRequest.target_id == r.case_id,
                        ApprovalRequest.status == "pending",
                    )
                )
            ).first()
            if r.case_id
            else None
        )
        if pending is not None:
            excluded["pending_decision"] += 1
            continue
        matched.append(r)
        if case is not None:
            cases[r.id] = case
    return matched, excluded, cases


async def bulk_lift_request(
    session: AsyncSession, principal: Principal, body: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    selector = dict(body.get("selector") or {})
    matched, excluded, cases = await bulk_select(session, selector)
    if len(matched) > BULK_MAX:
        raise cs.vf("selector", "selector_too_broad", f"At most {BULK_MAX} restrictions per request")
    sample = [
        {
            "case_ref": cases[r.id].case_ref if r.id in cases else None,
            "user": str(r.user_id)[:8] + "…",
            "starts_at": to_rfc3339(r.starts_at),
            "hc_rule": r.hc_rule,
        }
        for r in matched[:50]
    ]
    if body.get("dry_run", True):
        return 200, {"matched": len(matched), "excluded_by_reason": excluded, "sample": sample}
    reason = str(body.get("reason") or "").strip()
    if len(reason) < 5:
        raise cs.vf("reason", "required", "A reason is required")
    bl = SecurityBulkLift(
        id=uuid7(),
        selector=selector,
        reason=reason,
        extension_credit=bool(body.get("extension_credit", True)),
        requested_by=principal.user_id,
        matched_restriction_ids=[r.id for r in matched],
        status="awaiting_approval",
        progress={},
    )
    session.add(bl)
    await session.flush()
    req = await apr.new_request(
        session,
        principal,
        action_type="security.restriction.bulk_lift",
        target_type="security_bulk_lift",
        target_id=bl.id,
        payload={
            "bulk_lift_id": str(bl.id),
            "selector": selector,
            "restriction_ids": [str(r.id) for r in matched],
            "extension_credit": bl.extension_credit,
            "reason": reason,
        },
        reason=reason,
        required_approver_role=ADMIN_ROLE,
    )
    bl.approval_request_id = req.id
    await session.flush()
    return 202, {**apr.pending_response(req), "bulk_lift_id": str(bl.id), "matched": len(matched)}


async def _execute_bulk(session: AsyncSession, principal: Principal, req: ApprovalRequest) -> dict[str, Any]:
    from app.modules.security.unblock import false_positive_credit

    bl = await session.get(SecurityBulkLift, uuid.UUID(req.payload["bulk_lift_id"]))
    assert bl is not None
    bl.status = "running"
    done, skipped, failed = 0, 0, 0
    for rid in req.payload["restriction_ids"]:
        try:
            async with session.begin_nested():
                r = await session.get(AccountRestriction, uuid.UUID(rid))
                if r is None or r.ended_at is not None or r.case_id is None:
                    skipped += 1
                    continue
                case = await session.get(SecurityCase, r.case_id)
                assert case is not None
                payload: dict[str, Any] = {
                    "restriction_id": str(r.id),
                    "unblock_request_id": None,
                    "outcome": "lift_false_positive",
                    "resulting_level": 0,
                    "rationale": f"Bulk false-positive lift: {req.payload['reason']}",
                    "student_summary": BULK_SUMMARY,
                    "conditions": {},
                    "extension_days": 0,
                    "false_positive_rule_keys": [],
                    "second_approval_reasons": [],
                }
                await cs.finalize_decision(
                    session,
                    principal,
                    case,
                    payload,
                    decided_by=req.requested_by,
                    approved_by=principal.user_id,
                    approval_request_id=req.id,
                    skip_reverification=True,
                )
                urs = (
                    (
                        await session.execute(
                            select(UnblockRequest).where(
                                UnblockRequest.case_id == case.id,
                                UnblockRequest.state.in_(("draft", *cs.OPEN_UR, "approved")),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for u in urs:
                    await cs.set_ur_state(session, u, "closed", closure="moot")
                if bl.extension_credit:
                    from app.modules.security.models import CaseDecision

                    d = await session.get(CaseDecision, r.decision_id) if r.decision_id else None
                    if d is not None:
                        await false_positive_credit(session, case.user_id, case, d)
                case.status = "closed"
                case.closed_at = clock.now()
                await engine.notify_user(
                    session,
                    case.user_id,
                    "security.bulk_false_positive",
                    subject="We made a mistake — your access is back",
                    text_body=f"Case reference: {case.case_ref}. {BULK_SUMMARY} Sign in again to continue.",
                    data={"case_ref": case.case_ref},
                )
                done += 1
        except Exception:  # one failing restriction never rolls back the others (BL-05)
            failed += 1
    bl.status = "completed"
    bl.completed_at = clock.now()
    bl.progress = {
        "lifted": done,
        "skipped": skipped,
        "failed": failed,
        "reminder": "Move the rule to shadow if it is still active.",
    }
    await session.flush()
    await audit(
        session, principal, "security.bulk_lift.executed", "security_bulk_lift", bl.id, after=bl.progress
    )
    return {"bulk_lift_id": str(bl.id), **bl.progress}


async def _bulk_check(session: AsyncSession, principal: Principal, req: ApprovalRequest) -> None:
    bl = await session.get(SecurityBulkLift, uuid.UUID(req.payload["bulk_lift_id"]))
    if bl is None or [str(x) for x in bl.matched_restriction_ids] != list(req.payload["restriction_ids"]):
        raise ProblemError("invalid_state_transition", current_state="payload_tampered", allowed=[])


async def _bulk_rejected(session: AsyncSession, principal: Principal, req: ApprovalRequest) -> None:
    bl = await session.get(SecurityBulkLift, uuid.UUID(req.payload["bulk_lift_id"]))
    if bl is not None:
        bl.status = "rejected"
        await session.flush()


# --------------------------------------------------------------------------- report exports


async def _execute_export(
    session: AsyncSession, principal: Principal, req: ApprovalRequest
) -> dict[str, Any]:
    from app.modules.security.reports import render_export

    if req.target_type == "export_job":  # generic report exports (analytics ANL-13, export_jobs)
        from app.modules.analytics import exports as ax

        return await ax.execute_approved(session, principal, req)

    job = await session.get(SecurityReportExport, uuid.UUID(req.payload["export_job_id"]))
    assert job is not None
    job.approved_by = principal.user_id
    await render_export(session, job)
    await _notify_export(session, job, ready=True)
    return {"export_job_id": str(job.id), "status": job.status, "row_count": job.row_count}


async def _notify_export(session: AsyncSession, job: SecurityReportExport, *, ready: bool) -> None:
    """ADM-05: tell the requester the approved export is ready (or was not approved)."""
    if ready:
        subject = "Your security report export is ready"
        body = (
            f"The {job.report_key} export you requested was approved. Download it from "
            "Security console > Reports > My exports within 24 hours."
        )
    else:
        subject = "Your security report export was not approved"
        body = f"The {job.report_key} export you requested was not approved."
    await engine.notify_user(
        session,
        job.requested_by,
        "security.export.ready" if ready else "security.export.rejected",
        subject=subject,
        text_body=body,
        data={"export_job_id": str(job.id), "report_key": job.report_key, "status": job.status},
        dedupe_key=f"security.export.{job.id}.{job.status}",
    )


async def _export_rejected(session: AsyncSession, principal: Principal, req: ApprovalRequest) -> None:
    if req.target_type == "export_job":
        from app.modules.analytics import exports as ax

        await ax.on_rejected(session, principal, req)
        return
    job = await session.get(SecurityReportExport, uuid.UUID(req.payload["export_job_id"]))
    if job is not None:
        job.status = "rejected"
        await session.flush()
        if principal.user_id != job.requested_by:  # a self-cancel needs no notice
            await _notify_export(session, job, ready=False)


def register_handlers() -> None:
    apr.register(
        apr.ApprovalHandler(
            "risk.kill_switch.ratify",
            "approval.decide",
            admin_roles(),
            _ratify,
        )
    )
    for at in ("risk.ruleset.activate", "risk.ruleset.rollback"):
        apr.register(
            apr.ApprovalHandler(at, "approval.decide", admin_roles(), _activate, check=_activation_check)
        )
    apr.register(
        apr.ApprovalHandler(
            "security.restriction.bulk_lift",
            "approval.decide",
            admin_roles(),
            _execute_bulk,
            on_reject=_bulk_rejected,
            check=_bulk_check,
        )
    )
    apr.register(
        apr.ApprovalHandler(
            "security.export.per_user",
            "report.export.approve",
            admin_roles(),
            _execute_export,
            on_reject=_export_rejected,
        )
    )
    apr.register(
        apr.ApprovalHandler(
            "export.bulk_pii",
            "report.export.approve",
            admin_roles(),
            _execute_export,
            on_reject=_export_rejected,
        )
    )
