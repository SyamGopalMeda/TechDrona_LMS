"""SEC-04 ``pending_approval``: the open ``security.case.decision`` proposal (SEC-09 202) is
exposed on the case with what the caller may do; SEC-10/11/11a act on that id."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import update

from app.core.db import system_context
from app.modules.identity import clock
from app.modules.rbac.models import ApprovalRequest
from tests.security.helpers import idem, staff, staff_browser
from tests.security.test_scn_unblock import decide, etag_of, restricted_student, review_panels


async def _case(rb, case) -> dict:
    r = await rb.get(f"/security/cases/{case.id}", params={"reason_code": "case_review"})
    assert r.status_code == 200, r.text
    return r.json()


async def test_pending_proposal_exposed_and_actionable(client, db, sms) -> None:
    _u, _b, case, _r, _ud, _ = await restricted_student(db, client, level=4, high_risk=True)
    r1, r2 = await staff(db), await staff(db)
    sup = await staff(db, "evaluator")
    rb1, rb2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    assert (await _case(rb1, case))["pending_approval"] is None
    await review_panels(rb1, case)
    res = await decide(rb1, case, "lift_false_positive", extension_days=2)
    assert res.status_code == 202, res.text
    apr_id = res.json()["approval_request_id"]

    mine = (await _case(rb1, case))["pending_approval"]
    assert mine["approval_request_id"] == apr_id and mine["status"] == "pending"
    assert mine["requested_by"] == str(r1.id) and mine["requested_at"] and mine["expires_at"]
    assert mine["is_requester"] is True and mine["can_decide"] is False and mine["can_withdraw"] is True
    p = mine["payload"]
    assert p["outcome"] == "lift_false_positive" and p["extension_days"] == 2
    assert p["rationale"] == "Both devices belong to the student." and p["student_summary"].startswith(
        "We reviewed"
    )
    assert "resulting_level" in p and mine["reasons"]

    other = (await _case(rb2, case))["pending_approval"]
    assert other["is_requester"] is False and other["can_decide"] is True and other["can_withdraw"] is False

    # a non-admin staff member (evaluator) cannot read cases at all
    bs = await staff_browser(client, sup, ip="198.18.0.8")
    assert (
        await bs.get(f"/security/cases/{case.id}", params={"reason_code": "case_review"})
    ).status_code == 403

    # the second reviewer approves through SEC-10 with the id from the case
    ok = await rb2.post(
        f"/security/cases/{case.id}/approval-requests/{other['approval_request_id']}/approve",
        {"note": "Agree"},
        headers={**idem(), "If-Match": await etag_of(rb2, case)},
    )
    assert ok.status_code == 200, ok.text
    after = await _case(rb2, case)
    assert after["pending_approval"] is None and after["decisions"][-1]["approved_by"] == str(r2.id)


async def test_withdrawn_and_expired_proposals(client, db, sms) -> None:
    _u, _b, case, _r, _ud, _ = await restricted_student(db, client, level=4, high_risk=True)
    r1, r2 = await staff(db), await staff(db)
    rb1, rb2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    await review_panels(rb1, case)
    apr_id = (await decide(rb1, case, "lift_with_warning")).json()["approval_request_id"]
    wd = await rb1.post(
        f"/security/cases/{case.id}/approval-requests/{apr_id}/withdraw",
        headers={"If-Match": await etag_of(rb1, case)},
    )
    assert wd.status_code == 200 and wd.json()["status"] == "cancelled"
    c = await _case(rb1, case)
    assert c["pending_approval"] is None and c["status"] == "escalated"

    # re-propose, then nobody acts for 72 h: shown as expired, nobody can act on it
    apr2 = (await decide(rb1, case, "lift_with_warning")).json()["approval_request_id"]
    await system_context(db, "test.expire")
    await db.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == uuid.UUID(apr2))
        .values(expires_at=clock.now() - timedelta(minutes=1))
    )
    exp = (await _case(rb2, case))["pending_approval"]
    assert exp["approval_request_id"] == apr2 and exp["status"] == "expired"
    assert exp["can_decide"] is False and exp["can_withdraw"] is False
