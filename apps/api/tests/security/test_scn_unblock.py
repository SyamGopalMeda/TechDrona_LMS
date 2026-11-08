"""SCN-10, SCN-11, SCN-12, SCN-20: unblock requests, reviewer decisions with second-person
approval, re-verification (AUTH-21/22), appeals, auto-expiry and false-positive credit."""

from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import select

from app.core.models import OutboxEvent
from app.modules.admin.models import PolicySetting
from app.modules.identity import clock
from app.modules.rbac.models import ApprovalRequest
from app.modules.security import engine, tasks
from app.modules.security import restrictions as rx
from app.modules.security.models import (
    AccountRestriction,
    CaseDecision,
    SecurityCase,
    SecuritySignal,
    UnblockRequest,
)
from app.modules.sessions.models import AuthSession, UserDevice
from tests.identity.factory import Browser
from tests.security.helpers import adult, device_session, freeze, idem, staff, staff_browser

EXPL = (
    "A family member used my laptop while I was at my office; the phone and laptop are mine. "
    "I have changed my password and signed out the other device now."
)
SUMMARY = "We reviewed your request and found the activity was yours. Finish the verification steps to restore access."


async def restricted_student(
    db, client, *, level: int = 3, started_days_ago: float = 0, high_risk: bool = False, monkeypatch=None
):
    u = await adult(db)
    b = Browser(client)
    r = await b.login(u.email)
    assert r.json()["result"] == "authenticated", r.text
    sess = (await db.execute(select(AuthSession).where(AuthSession.user_id == u.id))).scalar_one()
    laptop_ud = sess.user_device_id
    other = await device_session(db, u.id, ip="183.82.1.9", asn=18209, region="MH")
    await engine.record_signal(
        db,
        rule_key="SH-01",
        user_id=u.id,
        source="heartbeat_batch",
        multipliers={"separation_class": "S3"},
        occurred_at=clock.now() - timedelta(days=started_days_ago, hours=2),
        evidence={"device_a": str(sess.device_id), "device_b": str(other[0])},
    )
    await engine.evaluate_sharing(db, u.id, trigger="manual_review")
    if monkeypatch is not None and started_days_ago:
        freeze(monkeypatch, clock.now() - timedelta(days=started_days_ago))
    case = await engine.open_case(db, user_id=u.id, family="sharing", level=level, opened_reason="engine_L3")
    actor = await adult(db)
    r_, _ = await rx.apply_restriction(
        db,
        user_id=u.id,
        level=level,
        family="sharing",
        source="engine" if level == 3 else "reviewer",
        actor=engine.SYSTEM,
        case_id=case.id,
        applied_by=None if level == 3 else actor.id,
        ends_at=clock.now() + timedelta(hours=24) if level == 3 else None,
        keep_session_id=sess.id,
        rule_keys=["SH-01"],
    )
    if monkeypatch is not None and started_days_ago:
        monkeypatch.undo()
    if high_risk:
        case.is_high_risk = True
        case.high_risk_reasons = ["repeat_incident"]
    await db.flush()
    if level == 4:
        r = await b.login(u.email)
        assert r.json()["result"] == "authenticated"
    return u, b, case, r_, laptop_ud, other


async def submit_request(b: Browser, case_ref: str, laptop_ud, **kw):
    body = {
        "case_ref": case_ref,
        "submit": True,
        "what_happened": ["family_member_used"],
        "explanation": EXPL,
        "recognised_user_device_ids": [str(laptop_ud)],
        "preferred_contact": "sms",
        "declaration": True,
        **kw,
    }
    return await b.post("/security/unblock-requests", body, headers=idem())


async def review_panels(rb: Browser, case: SecurityCase) -> None:
    assert (
        await rb.get(f"/security/cases/{case.id}/explanation", params={"reason_code": "case_review"})
    ).status_code == 200
    r = await rb.get(
        f"/security/users/{case.user_id}/timeline",
        params={"reason_code": "case_review", "case_ref": case.case_ref},
    )
    assert r.status_code == 200


async def etag_of(rb: Browser, case: SecurityCase) -> str:
    r = await rb.get(f"/security/cases/{case.id}", params={"reason_code": "case_review"})
    return r.headers["etag"]


async def decide(rb: Browser, case: SecurityCase, outcome: str, **kw):
    body = {
        "outcome": outcome,
        "rationale": "Both devices belong to the student.",
        "student_summary": SUMMARY,
        **kw,
    }
    return await rb.post(
        f"/security/cases/{case.id}/decisions", body, headers={**idem(), "If-Match": await etag_of(rb, case)}
    )


def otp(sms) -> str:
    return re.search(r"\b(\d{6})\b", sms.sent[-1].text).group(1)


# --------------------------------------------------------------------------- SCN-10


async def test_scn10_unblock_request_validation_limits_and_device_revocation(client, db, sms) -> None:
    _u, b, case, _r, laptop_ud, other = await restricted_student(db, client)
    form = await b.get("/security/unblock-requests/form", params={"case_ref": case.case_ref})
    assert form.status_code == 200 and "sms" in form.json()["preferred_contact_options"]
    key = idem()
    body = {
        "case_ref": case.case_ref,
        "submit": True,
        "what_happened": ["family_member_used"],
        "explanation": EXPL,
        "recognised_user_device_ids": [str(laptop_ud)],
        "preferred_contact": "sms",
        "declaration": True,
    }
    res = await b.post("/security/unblock-requests", body, headers=key)
    assert res.status_code == 201, res.text
    out = res.json()
    assert re.match(r"^APL-\d{4}-[0-9A-HJKMNP-TV-Z]{6}$", out["reference"]) and out["state"] == "submitted"
    assert out["case_ref"] == case.case_ref and out["sla"]["first_response_due"]
    assert [d["user_device_id"] for d in out["devices_revoked"]] != [] and "sms" in out[
        "acknowledgement_sent_via"
    ]
    db.expunge_all()
    removed = (await db.execute(select(UserDevice).where(UserDevice.device_id == other[0]))).scalar_one()
    assert removed.trust_status == "removed" and removed.removed_reason == "security_action"
    assert (await db.get(AuthSession, other[1])).end_reason == "risk_L3"  # already revoked when L3 applied
    replay = await b.post("/security/unblock-requests", body, headers=key)
    assert (
        replay.headers.get("idempotency-replayed") == "true"
        and replay.json()["reference"] == out["reference"]
    )
    dup = await submit_request(b, case.case_ref, laptop_ud)
    assert dup.status_code == 409 and dup.json()["code"] == "unblock_request_open"
    assert (await b.post("/security/unblock-requests", body)).json()["code"] == "idempotency_key_required"
    # by-reference lookup: own → 200; foreign / unknown / malformed → identical 404
    own = await b.get(f"/security/unblock-requests/by-reference/{out['reference']}")
    assert own.status_code == 200 and own.json()["state_label"] == "Submitted"
    _v, vb, vcase, *_rest = await restricted_student(db, client)
    for ref in (out["reference"], "APL-2611-ZZZZZZ", "not-a-ref"):
        miss = await vb.get(f"/security/unblock-requests/by-reference/{ref}")
        assert miss.status_code == 404 and set(miss.json()) >= {"code", "request_id"}
    # someone else's case → 404 without disclosure; DLP rejects OTP-like content
    assert (await submit_request(vb, case.case_ref, laptop_ud)).status_code == 404
    bad = await submit_request(
        vb, vcase.case_ref, _rest[1], explanation="My OTP 482913 was sent to my brother, " * 2
    )
    assert bad.status_code == 422 and bad.json()["code"] == "dlp_rejected"
    short = await submit_request(vb, vcase.case_ref, _rest[1], explanation="too short")
    assert short.status_code == 422


async def test_scn10_rate_limits_three_per_30_days_and_form_loads(client, db, sms) -> None:
    u, b, case, _r, laptop_ud, _ = await restricted_student(db, client)
    refs = [case]
    from app.core.ids import uuid7
    from app.modules.security.refs import make_ref

    for _ in range(3):
        c = SecurityCase(
            id=uuid7(),
            case_ref=make_ref("SEC"),
            user_id=u.id,
            family="sharing",
            level=3,
            opened_reason="manual",
            status="open",
            created_at=clock.now(),
            panel_views={},
            version=1,
        )
        db.add(c)
        refs.append(c)
    await db.flush()
    for c in refs[:3]:
        assert (await submit_request(b, c.case_ref, laptop_ud)).status_code == 201
    r4 = await submit_request(b, refs[3].case_ref, laptop_ud)
    assert r4.status_code == 429 and r4.json()["code"] == "unblock_rate_limited"
    codes = [(await b.get("/security/unblock-requests/form")).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


# --------------------------------------------------------------------------- SCN-11


async def test_scn11_review_lift_reverify_and_fresh_login(client, db, sms) -> None:
    u, b, case, restriction, laptop_ud, _other = await restricted_student(db, client)
    sub = await submit_request(b, case.case_ref, laptop_ud)
    req_id = sub.json()["request_id"]
    r1 = await staff(db)
    rb = await staff_browser(client, r1)
    q = await rb.get("/security/review/unblock-requests")
    assert any(x["reference"] == sub.json()["reference"] for x in q.json()["data"])
    detail = await rb.get(
        f"/security/review/unblock-requests/{req_id}", params={"reason_code": "case_review"}
    )
    assert (await rb.post(f"/security/review/unblock-requests/{req_id}/claim")).status_code == 428
    assert (
        await rb.post(f"/security/review/unblock-requests/{req_id}/claim", headers={"If-Match": '"v999"'})
    ).status_code == 412
    claim = await rb.post(
        f"/security/review/unblock-requests/{req_id}/claim", headers={"If-Match": detail.headers["etag"]}
    )
    assert claim.status_code == 200 and claim.json()["state"] == "under_review"
    early = await decide(rb, case, "lift_false_positive", unblock_request_id=req_id)
    assert early.status_code == 409 and early.json()["code"] == "explanation_not_viewed"
    await review_panels(rb, case)
    res = await decide(rb, case, "lift_false_positive", unblock_request_id=req_id, extension_days=1)
    assert res.status_code == 201, res.text
    assert (
        res.json()["restriction"]["state"] == "lift_pending"
        and res.json()["unblock_request"]["state"] == "approved"
    )
    assert (await b.patch("/me/profile", {"branch": "CSE"})).json()[
        "code"
    ] == "account_restricted"  # still enforced
    # student re-verification (OTP to a contact verified before the restriction) + device review
    s = await b.post("/auth/reverify/start", {"channel": "sms"})
    assert s.status_code == 200, s.text
    bad = await b.post("/auth/reverify/complete", {"otp_code": "000000", "devices": []}, headers=idem())
    assert bad.status_code == 400 and bad.json()["code"] == "otp_invalid"
    done = await b.post(
        "/auth/reverify/complete",
        {"otp_code": otp(sms), "devices": [{"user_device_id": str(laptop_ud), "keep": True}]},
        headers=idem(),
    )
    assert done.status_code == 200, done.text
    assert done.json()["restriction_ended"] and done.json()["sessions_revoked"] >= 1
    db.expunge_all()
    assert {
        x.status for x in (await db.execute(select(AuthSession).where(AuthSession.user_id == u.id))).scalars()
    } <= {"revoked", "blocked"}
    r = await db.get(AccountRestriction, restriction.id)
    assert r.end_reason == "case_decision" and r.decision_id is not None
    ur = await db.get(UnblockRequest, __import__("uuid").UUID(req_id))
    assert ur.state == "closed" and ur.closure_reason == "completed"
    assert (await db.get(SecurityCase, case.id)).status == "closed"
    events = {e.event_type for e in (await db.execute(select(OutboxEvent))).scalars()}
    assert {"restriction.lifted", "security.false_positive_credit"} <= events
    # fresh login: full scope again
    fresh = Browser(client, device=b.device)
    assert (await fresh.login(u.email)).json()["result"] == "authenticated"
    assert (await fresh.patch("/me/profile", {"branch": "CSE"})).status_code == 200


async def test_scn11_high_risk_l4_needs_distinct_second_approver(client, db, sms) -> None:
    _u, _b, case, restriction, _laptop_ud, _ = await restricted_student(db, client, level=4, high_risk=True)
    r1, r2 = await staff(db), await staff(db)
    rb1, rb2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    await review_panels(rb1, case)
    res = await decide(rb1, case, "lift_with_warning")
    assert res.status_code == 202, res.text
    apr_id = res.json()["approval_request_id"]
    assert (await db.execute(select(CaseDecision).where(CaseDecision.case_id == case.id))).first() is None
    dup = await decide(rb1, case, "lift_with_warning")
    assert dup.status_code == 409 and dup.json()["code"] == "second_approval_required"
    own = await rb1.post(
        f"/security/cases/{case.id}/approval-requests/{apr_id}/approve",
        {},
        headers={**idem(), "If-Match": await etag_of(rb1, case)},
    )
    assert own.status_code == 403 and own.json()["code"] == "sod_violation"
    ok = await rb2.post(
        f"/security/cases/{case.id}/approval-requests/{apr_id}/approve",
        {"note": "Agree"},
        headers={**idem(), "If-Match": await etag_of(rb2, case)},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["decided_by"] == str(r1.id) and ok.json()["approved_by"] == str(r2.id)
    d = (await db.execute(select(CaseDecision).where(CaseDecision.case_id == case.id))).scalar_one()
    assert d.requires_second_approval and d.approval_request_id is not None and d.approved_by != d.decided_by
    db.expunge_all()
    assert (await db.get(AccountRestriction, restriction.id)).lift_pending_at is not None


async def test_scn11_send_back_withdraw_and_72h_expiry(client, db, sms, monkeypatch) -> None:
    _u, b, case, _restriction, laptop_ud, _ = await restricted_student(db, client, level=4, high_risk=True)
    sub = await submit_request(b, case.case_ref, laptop_ud)
    r1, r2 = await staff(db), await staff(db)
    rb1, rb2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    req_id = sub.json()["request_id"]
    det = await rb1.get(f"/security/review/unblock-requests/{req_id}", params={"reason_code": "case_review"})
    await rb1.post(
        f"/security/review/unblock-requests/{req_id}/claim", headers={"If-Match": det.headers["etag"]}
    )
    await review_panels(rb1, case)
    apr_id = (await decide(rb1, case, "lift_with_warning", unblock_request_id=req_id)).json()[
        "approval_request_id"
    ]
    assert (await b.get(f"/security/unblock-requests/{req_id}")).json()[
        "state_label"
    ] == "With senior reviewer"
    back = await rb2.post(
        f"/security/cases/{case.id}/approval-requests/{apr_id}/send-back",
        {"note": "Confirm the second location first."},
        headers={"If-Match": await etag_of(rb2, case)},
    )
    assert back.status_code == 200 and back.json()["unblock_request"]["state"] == "under_review"
    apr2 = (await decide(rb1, case, "lift_with_warning", unblock_request_id=req_id)).json()[
        "approval_request_id"
    ]
    nope = await rb2.post(
        f"/security/cases/{case.id}/approval-requests/{apr2}/withdraw",
        headers={"If-Match": await etag_of(rb2, case)},
    )
    assert nope.status_code == 403
    # nobody acts for 72 h → expired, case stays escalated, SLA alert
    freeze(monkeypatch, clock.now() + timedelta(hours=73))
    out = await tasks.sla_breach_alerts(db)
    assert out["approvals_expired"] >= 1
    db.expunge_all()
    assert (await db.get(ApprovalRequest, __import__("uuid").UUID(apr2))).status == "expired"
    assert (await db.get(SecurityCase, case.id)).status == "escalated"


# --------------------------------------------------------------------------- SCN-12


async def test_scn12_reject_appeal_to_different_reviewer_and_final(client, db, sms) -> None:
    _u, b, case, _restriction, laptop_ud, _ = await restricted_student(db, client)
    sub = await submit_request(b, case.case_ref, laptop_ud)
    req_id = sub.json()["request_id"]
    r1, r2 = await staff(db), await staff(db)
    rb1, rb2 = await staff_browser(client, r1), await staff_browser(client, r2, ip="198.18.0.6")
    await review_panels(rb1, case)
    short = await decide(
        rb1, case, "uphold", unblock_request_id=req_id, student_summary="Too short summary of thirty."
    )
    assert short.status_code == 422
    rej = await decide(rb1, case, "uphold", unblock_request_id=req_id)
    assert rej.status_code == 201 and rej.json()["unblock_request"]["state"] == "rejected"
    view = (await b.get(f"/security/unblock-requests/{req_id}")).json()
    assert view["decision"]["outcome"] == "uphold" and view["appeal"]["allowed"] and view["grievance_route"]
    assert "rationale" not in str(view) and "score" not in view
    ap = await b.post(f"/security/unblock-requests/{req_id}/appeal", {"explanation": EXPL}, headers=idem())
    assert (
        ap.status_code == 200
        and ap.json()["state"] == "escalated"
        and ap.json()["state_label"] == "With senior reviewer"
    )
    det = await rb1.get(f"/security/review/unblock-requests/{req_id}", params={"reason_code": "appeal"})
    clash = await rb1.post(
        f"/security/review/unblock-requests/{req_id}/claim", headers={"If-Match": det.headers["etag"]}
    )
    assert clash.status_code == 403 and clash.json()["code"] == "conflict_of_interest"
    det = await rb2.get(f"/security/review/unblock-requests/{req_id}", params={"reason_code": "appeal"})
    assert (
        await rb2.post(
            f"/security/review/unblock-requests/{req_id}/claim", headers={"If-Match": det.headers["etag"]}
        )
    ).status_code == 200
    await review_panels(rb2, case)
    final = await decide(rb2, case, "uphold", unblock_request_id=req_id)
    assert final.status_code == 201
    db.expunge_all()
    ur = await db.get(UnblockRequest, __import__("uuid").UUID(req_id))
    assert ur.state == "closed" and ur.closure_reason == "rejected_final"
    again = await b.post(f"/security/unblock-requests/{req_id}/appeal", {"explanation": EXPL}, headers=idem())
    assert again.json()["code"] in ("appeal_already_used", "invalid_state_transition")


async def test_scn12_rejection_then_auto_expiry_reverify_closes_moot(client, db, sms, monkeypatch) -> None:
    u, b, case, restriction, laptop_ud, _ = await restricted_student(db, client)
    sub = await submit_request(b, case.case_ref, laptop_ud)
    r1 = await staff(db)
    rb1 = await staff_browser(client, r1)
    await review_panels(rb1, case)
    await decide(rb1, case, "uphold", unblock_request_id=sub.json()["request_id"])
    assert (
        await b.post("/auth/reverify/start", {"channel": "sms"})
    ).status_code == 409  # nothing pending yet
    later = clock.now() + timedelta(hours=25)  # past ends_at: auto-expiry, re-verification still required
    freeze(monkeypatch, later)
    b = Browser(client, device=b.device)  # the old session idled out; sign in again (restricted scope)
    assert (await b.login(u.email)).json()["result"] == "authenticated"
    assert (await b.patch("/me/profile", {"branch": "CSE"})).json()["code"] == "account_restricted"
    assert (await b.post("/auth/reverify/start", {"channel": "sms"})).status_code == 200
    done = await b.post(
        "/auth/reverify/complete",
        {"otp_code": otp(sms), "devices": [{"user_device_id": str(laptop_ud), "keep": True}]},
        headers=idem(),
    )
    assert done.status_code == 200, done.text
    db.expunge_all()
    assert (await db.get(AccountRestriction, restriction.id)).end_reason == "expired_reverified"
    ur = await db.get(UnblockRequest, __import__("uuid").UUID(sub.json()["request_id"]))
    assert ur.state == "closed" and ur.closure_reason == "moot"


async def test_scn12_no_appeal_in_14_days_closes_rejected_final(client, db, sms, monkeypatch) -> None:
    _u, b, case, _restriction, laptop_ud, _ = await restricted_student(db, client)
    sub = await submit_request(b, case.case_ref, laptop_ud)
    rb1 = await staff_browser(client, await staff(db))
    await review_panels(rb1, case)
    await decide(rb1, case, "uphold", unblock_request_id=sub.json()["request_id"])
    freeze(monkeypatch, clock.now() + timedelta(days=15))
    assert (await tasks.sla_breach_alerts(db))["rejected_final"] == 1


# --------------------------------------------------------------------------- SCN-20


async def test_scn20_false_positive_exception_suppression_and_credit(client, db, sms, monkeypatch) -> None:
    u, b, case, _restriction, laptop_ud, _ = await restricted_student(
        db, client, started_days_ago=3.5, monkeypatch=monkeypatch
    )
    sub = await submit_request(
        b,
        case.case_ref,
        laptop_ud,
        what_happened=["shared_computer"],
        lab_location_text="Office, 2nd floor",
    )
    rb1 = await staff_browser(client, await staff(db))
    note = await rb1.post(
        f"/security/cases/{case.id}/notes",
        {"visibility": "internal", "body": "Office manager attests shared computer usage on 30 Oct."},
    )
    assert note.status_code == 201
    await review_panels(rb1, case)
    exp = (clock.now() + timedelta(days=60)).isoformat()
    res = await decide(
        rb1,
        case,
        "lift_false_positive",
        unblock_request_id=sub.json()["request_id"],
        false_positive_rule_keys=["SH-01"],
        conditions={
            "user_exception": {"setting_key": "devices.student.max_trusted", "value": 4, "expires_at": exp}
        },
    )
    assert res.status_code == 201, res.text
    exc = (
        await db.execute(
            select(PolicySetting).where(PolicySetting.scope_type == "user", PolicySetting.scope_id == u.id)
        )
    ).scalar_one()
    assert exc.value == 4 and exc.case_decision_id is not None
    from app.modules.admin.policy import get_value

    assert await get_value(db, "devices.student.max_trusted", user_id=u.id) == 4
    sigs = (
        (
            await db.execute(
                select(SecuritySignal).where(
                    SecuritySignal.user_id == u.id, SecuritySignal.rule_key == "SH-01"
                )
            )
        )
        .scalars()
        .all()
    )
    assert sigs and all(s.suppressed_by_decision_id is not None for s in sigs)
    await b.post("/auth/reverify/start", {"channel": "sms"})
    done = await b.post(
        "/auth/reverify/complete",
        {"otp_code": otp(sms), "devices": [{"user_device_id": str(laptop_ud), "keep": True}]},
        headers=idem(),
    )
    assert done.status_code == 200 and done.json()["extension_days_credited"] == 4  # ceil(3.5 days)
    from app.core.db import system_context

    await system_context(db, "test")  # engine runs as a system job (handlers restore scope, DB-06)
    ev = await engine.evaluate_sharing(db, u.id, trigger="manual_review")
    assert ev is not None and float(ev.score) == 0  # recomputed without the suppressed signals
    h8 = await rb1.get("/security/reports/false-positive-rate")
    assert h8.status_code == 200
    assert any(r["key"] == "SH-01" and r["false_positives"] >= 1 for r in h8.json()["rows"])


async def test_scn20_variant_fp_override_of_recommend_l4_needs_second_approval(client, db, sms) -> None:
    u, _b, case, _restriction, _laptop_ud, _ = await restricted_student(db, client)
    case.recommended_level = 4
    st = await rx.get_state(db, u.id)
    st.sharing_score = 92
    await db.flush()
    rb1 = await staff_browser(client, await staff(db))
    await review_panels(rb1, case)
    res = await decide(rb1, case, "lift_false_positive")
    assert res.status_code == 202 and res.json()["requires_second_approval"]
