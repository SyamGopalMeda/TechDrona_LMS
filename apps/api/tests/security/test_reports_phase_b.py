"""Audit Phase B regressions for Section H reports and exports (ADM-01..06, 08..10, INV-11, INV-17).

H7/H10 seed at least ``analytics.k_min.cohort`` rows so the unsuppressed numbers are checked,
plus a smaller group that must be suppressed.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select, text

from app.core.db import system_context
from app.core.ids import uuid7
from app.modules.admin.policy import get_value
from app.modules.identity import clock
from app.modules.notifications.models import Notification
from app.modules.security import engine
from app.modules.security import restrictions as rx
from app.modules.security.models import CaseDecision, UnblockRequest
from app.modules.security.refs import make_ref
from app.modules.security.reports import run_report
from tests.security.helpers import adult, device_session, idem, staff, staff_browser

NIL = uuid.UUID(int=0)


async def _l3(db, rv: str, keys=("SH-01",), level: int = 3):
    u = await adult(db)
    case = await engine.open_case(db, user_id=u.id, family="sharing", level=level, opened_reason="engine_L3")
    await rx.apply_restriction(
        db,
        user_id=u.id,
        level=level,
        family="sharing",
        source="engine" if level < 4 else "reviewer",
        applied_by=None if level < 4 else u.id,  # ck_ar_l4_human: L4 is reviewer-applied
        actor=engine.SYSTEM,
        case_id=case.id,
        ruleset_version=rv,
        rule_keys=list(keys),
    )
    return u, case


def _decision(case_id, outcome: str, by, at=None) -> CaseDecision:
    return CaseDecision(
        id=uuid7(),
        case_id=case_id,
        outcome=outcome,
        rationale="phase b regression",
        student_summary="Regression decision summary for the student, padded past the fifty character minimum.",
        decided_by=by,
        created_at=at or clock.now(),
    )


def _spy_views(monkeypatch) -> list[str]:
    """td_app cannot read audit_outbox: spy on the report endpoint's audit() calls."""
    from app.modules.security import api_engine

    seen: list[str] = []
    real = api_engine.audit

    async def spy(session, actor, action, target_type, *a, **kw):
        if action == "security.report_viewed":
            seen.append(kw["after"]["report_key"])
        return await real(session, actor, action, target_type, *a, **kw)

    monkeypatch.setattr(api_engine, "audit", spy)
    return seen


# --------------------------------------------------------------------------- numbers


async def test_adm02_h8_counts_every_decision(db) -> None:
    reviewer = await adult(db)
    for o in ("lift_false_positive", "lift_false_positive", "uphold"):
        _, case = await _l3(db, "sharing-phaseb-h8")
        db.add(_decision(case.id, o, reviewer.id))
    await db.flush()
    data = await run_report(db, "false-positive-rate", {})
    row = next(r for r in data["rows"] if r["dimension"] == "ruleset" and r["key"] == "sharing-phaseb-h8")
    assert (row["decisions"], row["false_positives"], row["fp_rate"]) == (3, 2, 0.667)
    rule = next(r for r in data["rows"] if r["dimension"] == "rule" and r["key"] == "SH-01")
    assert rule["decisions"] >= 3
    assert any(
        a["alert"] == "l3_fp_rate_above_10pct" and a["key"] == "sharing-phaseb-h8" for a in data["alerts"]
    )


async def test_adm08_h8_weekly_rule_fp_alert(db) -> None:
    reviewer = await adult(db)
    for _ in range(4):
        _, case = await _l3(db, "sharing-phaseb-h8w", keys=("SH-07",))
        db.add(_decision(case.id, "lift_false_positive", reviewer.id))
    await db.flush()
    data = await run_report(db, "false-positive-rate", {})
    assert any(a["alert"] == "rule_fp_cases_per_week_above_3" and a["key"] == "SH-07" for a in data["alerts"])


async def test_adm03_h9_counts_incidents_not_decisions(db) -> None:
    reviewer = await adult(db)
    now = clock.now()
    single, case = await _l3(db, "sharing-phaseb-h9a")
    db.add(_decision(case.id, "uphold", reviewer.id, now - timedelta(days=3)))
    db.add(_decision(case.id, "convert_L4", reviewer.id, now - timedelta(days=1)))
    repeat, c1 = await _l3(db, "sharing-phaseb-h9b")
    db.add(_decision(c1.id, "uphold", reviewer.id, now - timedelta(days=20)))
    c1.status = "closed"
    c1.closed_at = now - timedelta(days=19)
    await db.flush()
    c2 = await engine.open_case(db, user_id=repeat.id, family="sharing", level=3, opened_reason="engine_L3")
    db.add(_decision(c2.id, "lift_with_warning", reviewer.id, now - timedelta(days=2)))
    await db.flush()
    rows = {r["user_id"]: r for r in (await run_report(db, "repeat-incidents", {}))["rows"]}
    assert str(single.id) not in rows
    r = rows[str(repeat.id)]
    assert r["confirmed_incidents"] == 2 and r["interval_days"] == 18.0
    assert r["latest_outcome"] == "lift_with_warning"


async def test_adm09_from_filter_keeps_offset_and_bare_dates_are_ist(db) -> None:
    a = await run_report(db, "average-review-time", {"from": "2026-10-01T00:00:00+05:30"})
    assert a["period"]["from"].startswith("2026-09-30T18:30:00")
    b = await run_report(db, "average-review-time", {"from": "2026-10-01", "to": "2026-10-02"})
    assert b["period"]["from"].startswith("2026-09-30T18:30:00")
    assert b["period"]["to"].startswith("2026-10-02T18:30:00")  # 'to' date is inclusive (IST)


async def test_adm06_report_filters_are_applied(db) -> None:
    _, case = await _l3(db, "sharing-phaseb-f")
    l4u, _ = await _l3(db, "sharing-phaseb-f4", level=4)
    h5_l4 = await run_report(db, "blocked-accounts", {"level": "4"})
    assert {r["level"] for r in h5_l4["rows"]} == {4} and str(l4u.id) in {r["user_id"] for r in h5_l4["rows"]}
    h1 = await run_report(db, "top-suspicious-accounts", {"level": "4"})
    assert {r["level"] for r in h1["rows"]} <= {4} and case.case_ref not in {
        r["case_ref"] for r in h1["rows"]
    }
    h1r = await run_report(db, "top-suspicious-accounts", {"rule": "SH-01"})
    assert case.case_ref in {r["case_ref"] for r in h1r["rows"]}
    assert (await run_report(db, "top-suspicious-accounts", {"rule": "SH-99"}))["rows"] == []


async def test_adm04_h11_learning_activity_from_analytics(db) -> None:
    """Single company: H11 is platform-wide only (no organization filter or org rollups)."""
    await system_context(db, "test.analytics")
    k = int(await get_value(db, "analytics.k_min.cohort"))
    day = clock.now().date() - timedelta(days=2)
    users = [await adult(db) for _ in range(k)]
    for i, u in enumerate(users):
        await db.execute(
            text(
                "insert into daily_learning_aggregates (user_id, activity_date, entity_kind, entity_id, "
                "organization_id, m2_active_s, m5_learning_s, privacy_tier, measurement_version) "
                "values (:u, :d, '_total', :e, NULL, :m2, :m5, 'adult', 'v1')"
            ),
            {"u": u.id, "d": day, "e": NIL, "m2": 600 + i * 60, "m5": 300},
        )
    data = await run_report(db, "learning-activity", {"from": day.isoformat(), "granularity": "day"})
    assert data["available"] is True and data["scope"] == "platform"
    row = next(r for r in data["rows"] if r["period_start"] == day.isoformat())
    assert row["active_learners"] >= k and row["learning_minutes"] >= 5 * k
    assert "organization_id" not in data["filters_applied"]
    week = await run_report(db, "learning-activity", {"from": day.isoformat(), "granularity": "week"})
    assert week["granularity"] == "week" and week["rows"]


async def test_h7_review_time_with_k_rows_and_suppression(db) -> None:
    k = int(await get_value(db, "analytics.k_min.cohort"))
    reviewer = await adult(db)
    # Same IST week: submitted two days ago, first response +2 h, decision +10 h.
    sub = clock.now() - timedelta(days=2)
    for level, n in ((3, k), (4, max(1, k - 1))):
        for _ in range(n):
            u, case = await _l3(db, f"sharing-phaseb-h7-{level}", level=level)
            case.first_response_at = sub + timedelta(hours=2)
            case.sla_decision_due = sub + timedelta(hours=24)
            db.add(
                UnblockRequest(
                    id=uuid7(),
                    reference=make_ref("APL"),
                    case_id=case.id,
                    user_id=u.id,
                    state="approved",
                    submitted_at=sub,
                    explanation="I share no account; please review.",
                    declaration_at=sub,
                    decided_at=sub + timedelta(hours=10),
                    assigned_to=reviewer.id,
                )
            )
    await db.flush()
    data = await run_report(db, "average-review-time", {})
    l3 = [r for r in data["rows"] if r["level"] == 3]
    l4 = [r for r in data["rows"] if r["level"] == 4]
    assert len(l3) == 1 and l3[0]["requests"] == k
    assert l3[0]["first_response_median_h"] == 2.0 and l3[0]["decision_median_h"] == 10.0
    assert l3[0]["decision_p90_h"] == 10.0 and l3[0]["sla_compliance_pct"] == 100.0
    assert l4 and l4[0]["suppressed"] is True and l4[0]["requests"] is None
    by_reviewer = await run_report(db, "average-review-time", {"reviewer": str(reviewer.id), "level": "3"})
    assert [r["requests"] for r in by_reviewer["rows"]] == [k]
    other = await run_report(db, "average-review-time", {"reviewer": str(uuid7())})
    assert other["rows"] == []


async def test_h10_active_sessions_with_k_rows(db) -> None:
    k = int(await get_value(db, "analytics.k_min.cohort"))
    for i in range(k):
        u = await adult(db)
        await device_session(db, u.id, ip=f"203.0.113.{10 + i}")
    data = await run_report(db, "active-session-counts", {"tier": "student"})
    rows = [r for r in data["rows"] if r["client_type"] == "web"]
    assert len(rows) == 1 and rows[0]["active_sessions"] >= k and "suppressed" not in rows[0]
    assert {r["tier"] for r in data["rows"]} == {"student"}
    assert data["student_sessions_per_user"]["1"] >= k
    staff_only = await run_report(db, "active-session-counts", {"tier": "staff"})
    assert all(r.get("suppressed") or r["active_sessions"] >= k for r in staff_only["rows"])


# --------------------------------------------------------------------------- views, exports


async def test_adm10_every_report_view_is_audited(client, db, monkeypatch) -> None:
    seen = _spy_views(monkeypatch)
    r1 = await staff(db)
    b1 = await staff_browser(client, r1)
    assert (await b1.get("/security/reports/active-session-counts")).status_code == 200
    assert (await b1.get("/security/reports/engine-health")).status_code == 200
    assert (await b1.get("/security/reports/learning-activity")).status_code == 200
    assert seen == ["active-session-counts", "engine-health", "learning-activity"]


async def test_adm01_per_user_export_always_needs_second_reviewer(client, db) -> None:
    u, _ = await _l3(db, "sharing-phaseb-x")
    r1, r2 = await staff(db), await staff(db)
    b1, b2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    exp = await b1.post(
        "/security/reports/blocked-accounts/exports",
        {"include_per_user_rows": False, "reason_code": "qa_sample", "reason": "phase b"},
        headers=idem(),
    )
    body = exp.json()
    assert exp.status_code == 202 and body["status"] == "awaiting_approval" and body["approval_request_id"]
    not_yet = await b1.get(f"/security/reports/exports/{body['export_job_id']}")
    assert not_yet.status_code == 409
    ok = await b2.post(
        f"/admin/approvals/{body['approval_request_id']}/approve", {"note": "ok"}, headers=idem()
    )
    assert ok.json()["status"] == "executed", ok.text
    csv = await b1.get(f"/security/reports/exports/{body['export_job_id']}")
    assert csv.status_code == 200 and str(u.id) in csv.text
    assert "attachment" in csv.headers["content-disposition"]
    # ADM-05: the requester is notified and can list the job with a download path.
    note = (
        await db.execute(
            select(Notification).where(
                Notification.user_id == r1.id, Notification.template_key == "security.export.ready"
            )
        )
    ).scalar_one()
    assert note.data["export_job_id"] == body["export_job_id"]
    mine = (await b1.get("/security/reports/exports")).json()["data"]
    job = next(j for j in mine if j["export_job_id"] == body["export_job_id"])
    assert job["status"] == "completed" and job["contains_pii"] is True
    assert job["download_path"] == f"/security/reports/exports/{body['export_job_id']}"
    # Single principal: the approver neither lists nor downloads the requester's export.
    assert body["export_job_id"] not in [
        j["export_job_id"] for j in (await b2.get("/security/reports/exports")).json()["data"]
    ]
    assert (await b2.get(f"/security/reports/exports/{body['export_job_id']}")).status_code == 404


async def test_adm01_aggregate_export_has_no_identifying_columns(client, db) -> None:
    reviewer = await adult(db)
    _, case = await _l3(db, "sharing-phaseb-agg")
    db.add(_decision(case.id, "uphold", reviewer.id))
    await db.flush()
    r1 = await staff(db)
    b1 = await staff_browser(client, r1)
    for key in (
        "false-positive-rate",
        "average-review-time",
        "engine-health",
        "repeated-network-device-associations",
    ):
        exp = await b1.post(f"/security/reports/{key}/exports", {"reason": "monthly"}, headers=idem())
        body = exp.json()
        assert exp.status_code == 202 and body["status"] == "completed" and body["contains_pii"] is False, key
        csv = (await b1.get(f"/security/reports/exports/{body['export_job_id']}")).text
        header = csv.splitlines()[1] if len(csv.splitlines()) > 1 else ""
        assert "user_id" not in header and "case_ref" not in header, (key, header)
    eng = await b1.post("/security/reports/engine-health/exports", {"reason": "monthly"}, headers=idem())
    eng_csv = (await b1.get(f"/security/reports/exports/{eng.json()['export_job_id']}")).text
    assert "metric,value" in eng_csv and "login_failures_10min" in eng_csv


async def test_inv17_h12_view_and_export(client, db, monkeypatch) -> None:
    seen = _spy_views(monkeypatch)
    u = await adult(db)
    await device_session(db, u.id, ip="203.0.113.77")
    r1, r2, sa = await staff(db), await staff(db), await staff(db, "super_admin")
    b1, b2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    bsa = await staff_browser(client, sa, ip="198.18.0.7")
    missing = await b1.get("/security/reports/device-login-history", params={"reason_code": "case_review"})
    assert missing.status_code == 422 and missing.json()["errors"][0]["field"] == "user_id"
    assert (await b1.get("/security/reports/device-login-history", params={"user_id": str(u.id)})).json()[
        "code"
    ] == "reason_code_required"
    view = await b1.get(
        "/security/reports/device-login-history",
        params={
            "user_id": str(u.id),
            "reason_code": "case_review",
            "from": (date.today() - timedelta(days=60)).isoformat(),
        },
    )
    assert view.status_code == 200 and view.json()["report_id"] == "H12" and view.json()["rows"], view.text
    assert seen == ["device-login-history"]
    # D2: every admin holds security.evidence.read, so a second admin may view H12 too
    assert (
        await bsa.get(
            "/security/reports/device-login-history",
            params={"user_id": str(u.id), "reason_code": "qa_sample"},
        )
    ).status_code == 200
    bad = await b1.post(
        "/security/reports/device-login-history/exports",
        {"reason_code": "case_review", "reason": "no user"},
        headers=idem(),
    )
    assert bad.status_code == 422
    exp = await b1.post(
        "/security/reports/device-login-history/exports",
        {"filters": {"user_id": str(u.id)}, "reason_code": "case_review", "reason": "case export"},
        headers=idem(),
    )
    assert exp.json()["status"] == "awaiting_approval"
    apr = exp.json()["approval_request_id"]
    assert (await b1.post(f"/admin/approvals/{apr}/approve", {}, headers=idem())).json()[
        "code"
    ] == "sod_violation"
    assert (await b2.post(f"/admin/approvals/{apr}/approve", {}, headers=idem())).json()[
        "status"
    ] == "executed"
    csv = await b1.get(f"/security/reports/exports/{exp.json()['export_job_id']}")
    assert csv.status_code == 200 and csv.text.startswith("# Tech Drona security export device-login-history")


async def test_adm05_rejected_export_notifies_requester(client, db) -> None:
    await _l3(db, "sharing-phaseb-rej")
    r1, r2 = await staff(db), await staff(db)
    b1, b2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    exp = await b1.post(
        "/security/reports/repeat-incidents/exports",
        {"reason_code": "qa_sample", "reason": "to reject"},
        headers=idem(),
    )
    apr = exp.json()["approval_request_id"]
    rej = await b2.post(f"/admin/approvals/{apr}/reject", {"note": "not needed"}, headers=idem())
    assert rej.status_code == 200, rej.text
    job = next(
        j
        for j in (await b1.get("/security/reports/exports")).json()["data"]
        if j["export_job_id"] == exp.json()["export_job_id"]
    )
    assert job["status"] == "rejected" and job["download_path"] is None
    n = (
        await db.execute(
            select(Notification).where(
                Notification.user_id == r1.id, Notification.template_key == "security.export.rejected"
            )
        )
    ).scalar_one()
    assert n.data["status"] == "rejected"
