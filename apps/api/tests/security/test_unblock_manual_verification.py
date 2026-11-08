"""E2E-01: a student whose contacts were verified < 7 days before the restriction cannot re-verify
by OTP; an approved lift escalates to a senior reviewer who records a manual verification and the
restriction ends (UNB §4.2, §6.3a). E2E-09: TO-08 evidence carries expected/observed UA and OS."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, update

from app.core.db import system_context
from app.modules.identity import clock
from app.modules.identity.models import User
from app.modules.security.models import AccountRestriction, SecurityCase, SecuritySignal, UnblockRequest
from app.modules.security.signals import on_replay_blocked
from app.modules.sessions.models import AuthSession
from tests.identity.factory import Browser
from tests.security.helpers import adult, device_session, idem, staff, staff_browser
from tests.security.test_scn_unblock import decide, restricted_student, review_panels, submit_request


async def test_recent_contact_lift_goes_to_senior_manual_verification(client, db, sms) -> None:
    u, b, case, restriction, laptop_ud, _ = await restricted_student(db, client)
    # contacts verified an hour ago (not back-dated): not trusted for re-verification
    recent = clock.now() - timedelta(hours=1)
    await db.execute(
        update(User).where(User.id == u.id).values(email_verified_at=recent, phone_verified_at=recent)
    )
    await db.flush()
    sub = await submit_request(b, case.case_ref, laptop_ud)
    assert sub.status_code == 201, sub.text
    req_id = sub.json()["request_id"]
    r1, r2 = await staff(db), await staff(db)
    rb1 = await staff_browser(client, r1)
    rb2 = await staff_browser(client, r2, ip="198.18.0.31")
    detail = await rb1.get(
        f"/security/review/unblock-requests/{req_id}", params={"reason_code": "case_review"}
    )
    claim = await rb1.post(
        f"/security/review/unblock-requests/{req_id}/claim", headers={"If-Match": detail.headers["etag"]}
    )
    assert claim.status_code == 200
    await review_panels(rb1, case)
    res = await decide(rb1, case, "lift_false_positive", unblock_request_id=req_id)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["next"] == "manual_verification" and body["restriction"]["state"] == "lift_pending"
    assert body["unblock_request"]["state"] == "escalated"

    # the student is not told to re-verify, and re-verification is refused
    st = (await b.get("/me/security/status")).json()
    assert (
        "reverify" not in st["available_actions"] and "await_manual_verification" in st["available_actions"]
    )
    assert (await b.post("/auth/reverify/start", {"channel": "email"})).json()[
        "code"
    ] == "invalid_state_transition"
    view = (await b.get(f"/security/unblock-requests/{req_id}")).json()
    assert view["state_label"] == "With senior reviewer"

    q = (await rb2.get("/security/review/unblock-requests")).json()["data"]
    row = next(x for x in q if x["request_id"] == req_id)
    assert row["manual_verification_required"] is True and row["restriction_id"] == str(restriction.id)

    url = f"/security/restrictions/{restriction.id}/manual-verification"
    mv = {"method": "video_call", "note": "Video call, student showed an ID matching the profile."}
    # the deciding reviewer cannot verify their own lift
    own = await rb1.post(url, mv, headers=idem())
    assert own.status_code == 403 and own.json()["code"] == "sod_violation", own.text
    sup = await staff(db, "evaluator")
    bs = await staff_browser(client, sup, ip="198.18.0.32")
    assert (await bs.post(url, mv, headers=idem())).status_code == 403
    ok = await rb2.post(url, mv, headers=idem())
    assert ok.status_code == 200, ok.text
    assert ok.json()["restriction_ended"] is True and ok.json()["sessions_revoked"] >= 1

    db.expunge_all()
    r = await db.get(AccountRestriction, restriction.id)
    assert r.ended_at is not None and r.end_reason == "case_decision" and r.ended_by == r2.id
    ur = await db.get(UnblockRequest, uuid.UUID(req_id))
    assert ur.state == "closed" and ur.closure_reason == "completed"
    assert (await db.get(SecurityCase, case.id)).status == "closed"
    again = await rb2.post(url, mv, headers=idem())
    assert again.status_code == 404
    # fresh login: full scope again
    fresh = Browser(client, device=b.device)
    assert (await fresh.login(u.email)).json()["result"] == "authenticated"
    assert (await fresh.patch("/me/profile", {"branch": "CSE"})).status_code == 200


async def test_manual_verification_refused_when_student_can_reverify(client, db, sms) -> None:
    _u, b, case, restriction, laptop_ud, _ = await restricted_student(db, client)
    sub = await submit_request(b, case.case_ref, laptop_ud)
    req_id = sub.json()["request_id"]
    r1, r2 = await staff(db), await staff(db)
    rb1 = await staff_browser(client, r1)
    rb2 = await staff_browser(client, r2, ip="198.18.0.33")
    detail = await rb1.get(
        f"/security/review/unblock-requests/{req_id}", params={"reason_code": "case_review"}
    )
    await rb1.post(
        f"/security/review/unblock-requests/{req_id}/claim", headers={"If-Match": detail.headers["etag"]}
    )
    await review_panels(rb1, case)
    res = await decide(rb1, case, "lift_false_positive", unblock_request_id=req_id)
    assert res.json()["next"] == "student_reverification"
    assert "reverify" in (await b.get("/me/security/status")).json()["available_actions"]
    mv = await rb2.post(
        f"/security/restrictions/{restriction.id}/manual-verification",
        {"method": "video_call", "note": "Not needed: the student can re-verify by code."},
        headers=idem(),
    )
    assert mv.status_code == 409 and mv.json()["current_state"] == "student_reverification"


async def test_to08_evidence_has_expected_and_observed_ua(db) -> None:
    u = await adult(db)
    _dev, sid = await device_session(db, u.id, ip="49.36.1.2", ua_family="Chrome", os_family="Windows")
    await system_context(db, "test.to08")
    s = await db.get(AuthSession, sid)
    await on_replay_blocked(db, s, "TO-08", {"ua_family": "Firefox", "os_family": "Linux"})
    sig = (
        await db.execute(
            select(SecuritySignal).where(SecuritySignal.user_id == u.id, SecuritySignal.rule_key == "TO-08")
        )
    ).scalar_one()
    assert sig.evidence["expected_ua_family"] == "Chrome" and sig.evidence["expected_os_family"] == "Windows"
    assert sig.evidence["observed_ua_family"] == "Firefox" and sig.evidence["observed_os_family"] == "Linux"
