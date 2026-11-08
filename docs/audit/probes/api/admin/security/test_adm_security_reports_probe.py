"""ADM audit probes: Section H report numbers (H8, H9), export dual-control, `from` timezone.

Run from apps/api:
  TD_TEST_DB_NAME=techdrona_audit_admin TD_TEST_RESET_DB=1 \
    .venv/Scripts/python -m pytest tests/_audit_scratch/admin/security -q -s
Each test prints its evidence; assertions encode the behaviour OBSERVED (a pass = finding reproduced).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.security import engine
from app.modules.security import restrictions as rx
from app.modules.security.models import CaseDecision
from app.modules.security.reports import run_report
from tests.security.helpers import adult, idem, staff, staff_browser


async def _l3(db, rv: str = "sharing-audit-1", keys=("SH-01",)):
    u = await adult(db)
    case = await engine.open_case(db, user_id=u.id, family="sharing", level=3, opened_reason="engine_L3")
    r, _ = await rx.apply_restriction(
        db,
        user_id=u.id,
        level=3,
        family="sharing",
        source="engine",
        actor=engine.SYSTEM,
        case_id=case.id,
        ruleset_version=rv,
        rule_keys=list(keys),
    )
    return u, case, r


def _decision(case_id, outcome: str, by, at=None) -> CaseDecision:
    return CaseDecision(
        id=uuid7(),
        case_id=case_id,
        outcome=outcome,
        rationale="audit probe",
        student_summary="Audit probe decision summary for the student, padded to satisfy the fifty character minimum.",
        decided_by=by,
        created_at=at or clock.now(),
    )


async def test_h8_false_positive_rate_collapses_identical_decisions(db) -> None:
    """3 L3 cases on the same ruleset/rule: 2 lifted as false positive, 1 upheld.
    Expected ruleset row: decisions=3, false_positives=2, fp_rate=0.667."""
    reviewer = await adult(db)
    outcomes = ["lift_false_positive", "lift_false_positive", "uphold"]
    for o in outcomes:
        _, case, _ = await _l3(db)
        db.add(_decision(case.id, o, reviewer.id))
    await db.flush()
    data = await run_report(db, "false-positive-rate", {})
    rows = [r for r in data["rows"] if r["key"] == "sharing-audit-1"]
    print("H8_ROWS", rows, "ALERTS", data["alerts"])
    assert rows and rows[0]["decisions"] == 2 and rows[0]["false_positives"] == 1  # observed: collapsed by DISTINCT


async def test_h9_repeat_incidents_counts_decisions_not_incidents(db) -> None:
    """One user, ONE L3 case, two confirmed decisions on it (uphold, later convert_L4).
    Expected: not a repeat-incident user (only 1 incident). Observed below."""
    reviewer = await adult(db)
    u, case, _ = await _l3(db, rv="sharing-audit-2")
    now = clock.now()
    db.add(_decision(case.id, "uphold", reviewer.id, now - timedelta(days=3)))
    db.add(_decision(case.id, "convert_L4", reviewer.id, now - timedelta(days=1)))
    await db.flush()
    data = await run_report(db, "repeat-incidents", {})
    mine = [r for r in data["rows"] if r["user_id"] == str(u.id)]
    print("H9_ROWS", mine)
    assert mine and mine[0]["confirmed_incidents"] == 2  # observed: one case counted as 2 incidents


async def test_h11_learning_activity_not_built(db) -> None:
    data = await run_report(db, "learning-activity", {})
    print("H11", {k: data[k] for k in ("rows", "available", "note")})
    assert data["rows"] == [] and data["available"] is False


async def test_from_filter_ignores_ist_offset(db) -> None:
    data = await run_report(db, "average-review-time", {"from": "2026-10-01T00:00:00+05:30"})
    print("PERIOD", data["period"])
    # 00:00 IST == 2026-09-30T18:30Z; observed: offset replaced by UTC -> 2026-10-01T00:00Z
    assert data["period"]["from"].startswith("2026-10-01T00:00:00")


async def test_aggregate_export_of_per_user_report_bypasses_second_approver(client, db) -> None:
    """H5 is a per-user report. Requesting the export with include_per_user_rows=false completes
    immediately (no second security_reviewer) and the CSV still carries user_id per row."""
    u, _, _ = await _l3(db, rv="sharing-audit-3")
    r1 = await staff(db)
    b1 = await staff_browser(client, r1)
    exp = await b1.post(
        "/security/reports/blocked-accounts/exports",
        {"include_per_user_rows": False, "reason_code": "qa_sample", "reason": "probe"},
        headers=idem(),
    )
    body = exp.json()
    print("EXPORT", exp.status_code, {k: body.get(k) for k in ("status", "approval_request_id", "contains_pii")})
    csv = await b1.get(f"/security/reports/exports/{body['export_job_id']}")
    header = csv.text.splitlines()[1] if csv.status_code == 200 else csv.text
    print("CSV", csv.status_code, "header:", header, "| contains subject user_id:", str(u.id) in csv.text)
    assert body["status"] == "completed" and body["contains_pii"] is False
    assert str(u.id) in csv.text


async def test_h12_report_requires_user_filter_web_never_sends(db) -> None:
    data = await run_report(db, "device-login-history", {"from": "2026-10-01"})
    print("H12", data["rows"], data.get("note"))
    assert data["rows"] == [] and data["note"] == "user_id filter required"


async def test_aggregate_h10_view_is_not_audited(client, db) -> None:
    """Section H: 'All reports must be ... auditable'. Aggregate views write no audit row."""
    from sqlalchemy import text

    r1 = await staff(db)
    b1 = await staff_browser(client, r1, ip="198.18.0.9")
    before = (await db.execute(text("select count(*) from audit_log where action='security.report_viewed'"))).scalar_one()
    res = await b1.get("/security/reports/active-session-counts")
    after = (await db.execute(text("select count(*) from audit_log where action='security.report_viewed'"))).scalar_one()
    print("H10", res.status_code, "audit rows before/after", before, after)
    assert res.status_code == 200 and before == after


_ = datetime  # keep import for readers
