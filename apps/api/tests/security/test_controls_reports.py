"""Kill switch (KS-*), rule versions (SEC-22..29), bulk false-positive lift (BL-*), Section H
reports and exports (RPT-*), manual restrictions (SEC-20/21), incidents,
org summary and "This wasn't me" (SEC-46)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, update

from app.core.ids import uuid7
from app.modules.admin.policy import get_value
from app.modules.identity import clock
from app.modules.rbac.models import ApprovalRequest
from app.modules.security import engine, tasks
from app.modules.security import restrictions as rx
from app.modules.security.models import (
    AccountRestriction,
    CaseDecision,
    RiskRuleVersion,
    SecurityCase,
    SecurityNotice,
)
from tests.identity.factory import Browser, company_org, staff_login
from tests.security.helpers import activate_rule, adult, enforce, freeze, idem, staff, staff_browser


async def approve(b: Browser, approval_id: str):
    return await b.post(f"/admin/approvals/{approval_id}/approve", {"note": "ok"}, headers=idem())


# --------------------------------------------------------------------------- kill switch


async def test_ks01_02_05_kill_switch_shadow_ratification_and_return_is_dual(client, db, monkeypatch) -> None:
    await enforce(db)
    r1, r2 = await staff(db), await staff(db)
    b1, b2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    res = await b1.post(
        "/security/engine/kill-switch",
        {"target": "risk_mode", "reason": "FP surge after deploy"},
        headers=idem(),
    )
    assert res.status_code == 200, res.text
    assert res.json()["applied"]["risk.mode"] == "shadow"
    assert await get_value(db, "risk.mode") == "shadow"
    apr = res.json()["ratification"]["approval_request_id"]
    again = await b1.post(
        "/security/engine/kill-switch", {"target": "risk_mode", "reason": "again please"}, headers=idem()
    )
    assert again.status_code == 409  # already shadow: the switch only moves toward safety
    assert (await approve(b1, apr)).json()["code"] == "sod_violation"
    ok = await approve(b2, apr)
    assert ok.status_code == 200 and ok.json()["status"] == "executed"
    # KS-03: an unratified switch pages at 24 h and is never reverted
    res2 = await b2.post(
        "/security/engine/kill-switch", {"target": "hc_all", "reason": "precaution"}, headers=idem()
    )
    assert res2.status_code == 409  # hc already off (launch default)
    # KS-05: returning to enforce is a Dual policy change approved by a different super_admin
    prop = await b1.post(
        "/admin/policy-settings/risk.mode/changes",
        {"value": "enforce", "change_reason": "Ratified pilot report"},
        headers=idem(),
    )
    assert prop.status_code == 202 and prop.json()["required_approver_role"] == "super_admin"
    # D2: any different admin is the checker; the maker cannot approve their own change
    assert (await approve(b1, prop.json()["approval_request_id"])).json()["code"] == "sod_violation"
    assert (await approve(b2, prop.json()["approval_request_id"])).json()["status"] == "executed"
    assert await get_value(db, "risk.mode") == "enforce"
    st = await b1.get("/security/engine/state")
    assert st.status_code == 200 and st.json()["risk.mode"] == "enforce"


async def test_ks03_04_06_rule_target_unratified_paging_and_permissions(client, db, monkeypatch) -> None:
    v1 = await activate_rule(db, "HC-01")
    v2 = await activate_rule(db, "HC-02")
    r1 = await staff(db)
    b1 = await staff_browser(client, r1)
    res = await b1.post(
        "/security/engine/kill-switch",
        {"target": "rule", "rule_key": "HC-01", "reason": "FP surge on HC-01"},
        headers=idem(),
    )
    assert res.status_code == 200
    await db.refresh(v1)
    await db.refresh(v2)
    assert v1.status == "shadow" and v1.status_change_reason == "kill_switch" and v2.status == "active"
    freeze(monkeypatch, clock.now() + timedelta(hours=25))
    assert (await tasks.sla_breach_alerts(db))["ratification_pages"] == 1
    monkeypatch.undo()
    sup = await staff(db, "evaluator")
    bs = await staff_browser(client, sup, ip="198.18.0.8")
    denied = await bs.post(
        "/security/engine/kill-switch", {"target": "risk_mode", "reason": "not mine"}, headers=idem()
    )
    assert denied.status_code == 403
    stale = await staff(db)
    bst = Browser(client, ip="198.18.0.9")
    await staff_login(bst, stale)
    freeze(monkeypatch, clock.now() + timedelta(minutes=6))
    r = await bst.post(
        "/security/engine/kill-switch", {"target": "hc_all", "reason": "stale step-up"}, headers=idem()
    )
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"


# --------------------------------------------------------------------------- rule versions


async def test_rule_version_shadow_14_days_then_dual_activation(client, db) -> None:
    r1, r2 = await staff(db), await staff(db)
    b1, b2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    cat = await b1.get("/security/rules")
    assert any(r["key"] == "HC-01" and r["active_version"]["status"] == "shadow" for r in cat.json()["data"])
    created = await b1.post(
        "/security/rule-versions",
        {"family": "sharing", "semver": "1.1.0", "definition": {"points": {"SH-01": 12}}},
    )
    assert created.status_code == 201 and created.json()["status"] == "draft"
    vid = created.json()["version_id"]
    assert (await b1.post(f"/security/rule-versions/{vid}/simulate")).status_code == 200
    assert (await b1.post(f"/security/rule-versions/{vid}/start-shadow")).json()["status"] == "shadow"
    early = await b1.post(
        f"/security/rule-versions/{vid}/activation-requests", {"reason": "Lower SH-01 weight"}, headers=idem()
    )
    assert early.status_code == 409 and early.json()["code"] == "shadow_period_incomplete"
    await db.execute(
        update(RiskRuleVersion)
        .where(RiskRuleVersion.id == uuid.UUID(vid))
        .values(shadow_started_at=clock.now() - timedelta(days=15))
    )
    req = await b1.post(
        f"/security/rule-versions/{vid}/activation-requests", {"reason": "Lower SH-01 weight"}, headers=idem()
    )
    assert req.status_code == 202
    assert (await approve(b1, req.json()["approval_request_id"])).json()["code"] == "sod_violation"
    done = await approve(b2, req.json()["approval_request_id"])
    assert done.status_code == 200 and done.json()["status"] == "executed"
    defn, version = await engine.ruleset(db, "sharing")
    assert version == "sharing-1.1.0" and defn["points"]["SH-01"] == 12
    v = await db.get(RiskRuleVersion, uuid.UUID(vid))
    await db.refresh(v)
    assert v.approved_by == r2.id and v.approved_by != v.proposed_by


# --------------------------------------------------------------------------- bulk lift


async def _engine_l3(db, *, source="engine", level=3, family="sharing", high_risk=False, rv="sharing-1.0.0"):
    u = await adult(db)
    case = await engine.open_case(db, user_id=u.id, family=family, level=level, opened_reason="engine_L3")
    case.is_high_risk = high_risk
    actor = await adult(db)
    r, _ = await rx.apply_restriction(
        db,
        user_id=u.id,
        level=level,
        family=family,
        source=source,
        actor=engine.SYSTEM,
        case_id=case.id,
        applied_by=actor.id if source == "reviewer" else None,
        ruleset_version=rv,
        rule_keys=["SH-01"],
    )
    return u, case, r


async def test_bulk_lift_dry_run_exclusions_dual_and_execution(client, db, sms) -> None:
    good = [await _engine_l3(db) for _ in range(3)]
    await _engine_l3(db, source="reviewer", level=4)
    await _engine_l3(db, source="reviewer")
    await _engine_l3(db, family="takeover")
    await _engine_l3(db, high_risk=True)
    _pend_u, pend_case, _ = await _engine_l3(db)
    other = await adult(db)
    db.add(
        ApprovalRequest(
            id=uuid7(),
            action_type="security.case.decision",
            target_type="security_case",
            target_id=pend_case.id,
            payload={},
            payload_hash=b"0" * 32,
            requested_by=other.id,
            request_reason="x",
            required_approver_role="super_admin",
            status="pending",
            expires_at=clock.now() + timedelta(hours=72),
        )
    )
    await db.flush()
    r1, r2 = await staff(db), await staff(db)
    b1, b2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    sel = {"selector": {"rule_key": "SH-01"}, "dry_run": True}
    dry = await b1.post("/security/restrictions/bulk-lift-requests", sel, headers=idem())
    assert dry.status_code == 200, dry.text
    assert dry.json()["matched"] == 3 and len(dry.json()["sample"]) == 3
    assert dry.json()["excluded_by_reason"] == {
        "l4": 1,
        "high_risk": 1,
        "takeover": 1,
        "human_applied": 1,
        "pending_decision": 1,
    }
    run = await b1.post(
        "/security/restrictions/bulk-lift-requests",
        {**sel, "dry_run": False, "reason": "HC/SH-01 malfunction on 2 Nov"},
        headers=idem(),
    )
    assert run.status_code == 202 and run.json()["action_type"] == "security.restriction.bulk_lift"
    apr = run.json()["approval_request_id"]
    assert (await approve(b1, apr)).json()["code"] == "sod_violation"
    ok = await approve(b2, apr)
    assert ok.status_code == 200 and ok.json()["result"]["lifted"] == 3
    for _u, case, r in good:
        await db.refresh(r)
        assert r.end_reason == "case_decision"
        d = (await db.execute(select(CaseDecision).where(CaseDecision.case_id == case.id))).scalar_one()
        assert d.outcome == "lift_false_positive" and d.decided_by == r1.id and d.approved_by == r2.id
        assert d.approval_request_id == uuid.UUID(apr)
    status = await b1.get(f"/security/restrictions/bulk-lift-requests/{run.json()['bulk_lift_id']}")
    assert status.json()["status"] == "completed"
    sup = await staff(db, "evaluator")
    bs = await staff_browser(client, sup, ip="198.18.0.8")
    assert (
        await bs.post("/security/restrictions/bulk-lift-requests", sel, headers=idem())
    ).status_code == 403


async def test_bulk_lift_tampered_payload_is_refused(client, db) -> None:
    await _engine_l3(db)
    r1, r2 = await staff(db), await staff(db)
    b1, b2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    run = await b1.post(
        "/security/restrictions/bulk-lift-requests",
        {"selector": {"rule_key": "SH-01"}, "dry_run": False, "reason": "rule malfunction"},
        headers=idem(),
    )
    apr = uuid.UUID(run.json()["approval_request_id"])
    req = await db.get(ApprovalRequest, apr)
    await db.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == apr)
        .values(payload={**req.payload, "restriction_ids": []})
    )
    bad = await approve(b2, str(apr))
    assert bad.status_code == 409


# --------------------------------------------------------------------------- reports / exports


async def test_reports_access_reason_codes_and_export_approval_routing(client, db) -> None:
    await _engine_l3(db)
    r1, r2, sa = await staff(db), await staff(db), await staff(db, "super_admin")
    b1, b2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    bsa = await staff_browser(client, sa, ip="198.18.0.7")
    cat = (await b1.get("/security/reports")).json()["data"]
    assert {c["id"] for c in cat} == {f"H{i}" for i in range(1, 13)} | {"ENG"}
    assert (await b1.get("/security/reports/blocked-accounts")).json()["code"] == "reason_code_required"
    h5 = await b1.get("/security/reports/blocked-accounts", params={"reason_code": "qa_sample"})
    assert h5.status_code == 200 and h5.json()["rows"][0]["source"] == "engine"
    for key in (
        "top-suspicious-accounts",
        "account-device-associations",
        "concurrent-login-events",
        "repeated-network-device-associations",
        "pending-unblock-requests",
        "average-review-time",
        "false-positive-rate",
        "repeat-incidents",
        "active-session-counts",
        "learning-activity",
        "engine-health",
    ):
        assert (
            await b1.get(f"/security/reports/{key}", params={"reason_code": "qa_sample"})
        ).status_code == 200, key
    # D2: every admin holds the folded security reviewer permissions (per-user views too)
    assert (await bsa.get("/security/reports/average-review-time")).status_code == 200
    assert (await bsa.get("/security/reports/engine-health")).status_code == 200
    assert (
        await bsa.get("/security/reports/blocked-accounts", params={"reason_code": "qa_sample"})
    ).status_code == 200
    sup = await staff(db, "evaluator")
    bs = await staff_browser(client, sup, ip="198.18.0.8")
    assert (await bs.get("/security/reports/average-review-time")).status_code == 403
    # per-user export: awaiting approval by a second, different admin (maker != checker)
    exp = await b1.post(
        "/security/reports/blocked-accounts/exports",
        {"include_per_user_rows": True, "reason_code": "qa_sample", "reason": "Monthly integrity"},
        headers=idem(),
    )
    assert (
        exp.status_code == 202 and exp.json()["status"] == "awaiting_approval" and exp.json()["contains_pii"]
    )
    apr = exp.json()["approval_request_id"]
    assert (await approve(b1, apr)).json()["code"] == "sod_violation"
    assert (await approve(b2, apr)).json()["status"] == "executed"
    csv = await b1.get(f"/security/reports/exports/{exp.json()['export_job_id']}")
    assert csv.status_code == 200 and csv.text.startswith("# Tech Drona security export blocked-accounts")
    agg = await b1.post(
        "/security/reports/false-positive-rate/exports", {"reason": "monthly"}, headers=idem()
    )
    assert agg.json()["status"] == "completed"


# --------------------------------------------------------------------------- SEC-20/21, networks, incidents


async def test_manual_restrictions_permissions_and_minor_guard(client, db) -> None:
    sup = await staff(db, "evaluator")
    bs = await staff_browser(client, sup)
    target = await adult(db)
    denied = await bs.post(
        "/security/restrictions",
        {"user_id": str(target.id), "level": 1, "rationale": "Notice after support call"},
        headers=idem(),
    )
    assert denied.status_code == 403
    adm = await staff(db)
    ba = await staff_browser(client, adm, ip="198.18.0.7")
    l1 = await ba.post(
        "/security/restrictions",
        {"user_id": str(target.id), "level": 1, "rationale": "Notice after support call"},
        headers=idem(),
    )
    assert l1.status_code == 201, l1.text
    assert (
        await ba.post(f"/security/restrictions/{l1.json()['restriction_id']}/lift", {"reason": "resolved"})
    ).status_code == 200
    r1 = await staff(db)
    b1 = await staff_browser(client, r1, ip="198.18.0.6")
    no_case = await b1.post(
        "/security/restrictions",
        {"user_id": str(target.id), "level": 3, "rationale": "x" * 10},
        headers=idem(),
    )
    assert no_case.status_code == 422
    case = await engine.open_case(db, user_id=target.id, family="sharing", level=0, opened_reason="manual")
    ok = await b1.post(
        "/security/restrictions",
        {"user_id": str(target.id), "level": 4, "case_id": str(case.id), "rationale": "Reseller pattern"},
        headers=idem(),
    )
    assert ok.status_code == 201 and ok.json()["scope"] == "status_only"
    lift = await b1.post(f"/security/restrictions/{ok.json()['restriction_id']}/lift", {"reason": "nope"})
    assert lift.status_code == 409 and lift.json()["code"] == "decision_required"
    kid = await adult(db, minor=True)
    m = await b1.post(
        "/security/restrictions", {"user_id": str(kid.id), "level": 2, "rationale": "x" * 10}, headers=idem()
    )
    assert m.status_code == 422 and m.json()["errors"][0]["code"] == "minor_sharing_not_permitted"
    r = (
        await db.execute(
            select(AccountRestriction).where(
                AccountRestriction.user_id == target.id, AccountRestriction.level == 4
            )
        )
    ).scalar_one()
    assert r.source == "reviewer" and r.applied_by == r1.id


async def test_trusted_networks_and_org_summary_are_gone_incidents_work(client, db) -> None:
    """Single company (D5): the trusted-network and org security-summary routes are removed."""
    r1 = await staff(db)
    b1 = await staff_browser(client, r1, ip="198.18.0.6")
    org = company_org()
    for method, path in (
        ("get", "/security/trusted-networks"),
        ("post", f"/security/trusted-networks/{uuid.uuid4()}/decision"),
        ("get", f"/orgs/{org}/trusted-networks"),
        ("post", f"/orgs/{org}/trusted-networks"),
        ("get", f"/orgs/{org}/security-summary"),
    ):
        r = await (b1.get(path) if method == "get" else b1.post(path, {"cidr": "198.51.100.0/24"}))
        assert r.status_code in (404, 405), (method, path, r.status_code)
    inc = await b1.post(
        "/security/incidents",
        {
            "title": "Credential stuffing wave",
            "severity": "high",
            "detected_at": clock.now().isoformat(),
            "certin_reportable": True,
        },
    )
    assert (
        inc.status_code == 201
        and inc.json()["incident_ref"].startswith("INC-")
        and inc.json()["certin_due_at"]
    )
    upd = await b1.patch(
        f"/security/incidents/{inc.json()['incident_id']}",
        {"status": "triaged"},
        headers={"If-Match": '"v1"'},
    )
    assert upd.status_code == 200 and upd.json()["status"] == "triaged"


async def test_sec46_this_wasnt_me_triggers_hct3(client, browser, db) -> None:
    u = await adult(db)
    r = await browser.login(u.email)
    assert r.json()["result"] == "authenticated"
    n = SecurityNotice(
        id=uuid7(),
        event_ref="ACC-2611-7KQ4MZ",
        user_id=u.id,
        kind="replay",
        rule_key="TO-04",
        created_at=clock.now(),
    )
    db.add(n)
    await db.flush()
    other = await adult(db)
    ob = Browser(client)
    await ob.login(other.email)
    assert (await ob.post("/me/security/events/ACC-2611-7KQ4MZ/disown", {"confirm": True})).status_code == 404
    res = await browser.post("/me/security/events/ACC-2611-7KQ4MZ/disown", {"confirm": True})
    assert res.status_code == 200 and res.json()["result"] == "protected"
    assert (await rx.restriction_state(db, u.id)).takeover_lock
    assert (await browser.get("/me")).status_code == 401


async def test_sla_80pct_alert_and_100pct_auto_escalation(client, db, monkeypatch) -> None:
    from tests.security.test_scn_unblock import restricted_student, submit_request

    _u, b, case, _r, laptop_ud, _ = await restricted_student(db, client)
    sub = await submit_request(b, case.case_ref, laptop_ud)
    # The job runs under its task's system context (handlers restore the caller's scope, DB-06).
    from app.core.db import system_context

    await system_context(db, "test")
    freeze(monkeypatch, case.created_at + timedelta(hours=60))
    assert (await tasks.sla_breach_alerts(db))["alerts_80"] == 1
    freeze(monkeypatch, case.created_at + timedelta(hours=73))
    assert (await tasks.sla_breach_alerts(db))["escalated"] == 1
    db.expunge_all()
    from app.modules.security.models import UnblockRequest

    assert (await db.get(UnblockRequest, uuid.UUID(sub.json()["request_id"]))).state == "escalated"
    assert (await db.get(SecurityCase, case.id)).status == "escalated"


async def test_nightly_decay_deescalates_l1(db, monkeypatch) -> None:
    await enforce(db)
    u = await adult(db)
    base = clock.now()
    for d in (2, 1, 0):
        freeze(monkeypatch, base - timedelta(days=d))
        await engine.record_signal(db, rule_key="SH-06", user_id=u.id, source="nightly")
        await engine.record_signal(db, rule_key="SH-05", user_id=u.id, source="nightly")
    await engine.record_signal(db, rule_key="SH-07", user_id=u.id, source="nightly")
    monkeypatch.undo()
    await engine.evaluate_sharing(db, u.id, trigger="nightly")
    assert (await rx.active_for(db, u.id, "sharing")).level == 1  # ≈ 30 → L1 (device signals only)
    freeze(monkeypatch, clock.now() + timedelta(days=20))
    out = await tasks.decay_recompute(db)
    assert out["evaluations"] >= 1
    assert await rx.active_for(db, u.id, "sharing") is None  # score decayed below 15 → L1 cleared
