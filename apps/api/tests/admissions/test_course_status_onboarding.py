"""Course registration status (open / coming soon / closed) and Verify & Add to Batch: the LMS
account with a ``td`` + 6-digit username and a temporary password, the must-change gate, batch
membership, the login email (sent / not connected) and the password reset on resend."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select, text

from app.core.config import reset_settings_cache
from app.core.db import system_context
from app.modules.admissions.models import AdmissionRegistration
from tests.admissions.test_admissions import admin_setup, claim, reg_body
from tests.admissions.test_approve_enrol import FULL, full_fee_plan, queue_item, register
from tests.identity.factory import Browser, company_org, make_batch
from tests.security.helpers import adult

AMBIGUOUS = set("0O1lI")


@pytest.fixture
def simple_auth(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TD_SIMPLE_AUTH", "true")
    reset_settings_cache()
    yield
    monkeypatch.undo()
    reset_settings_cache()


@pytest.fixture
def email_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend a real email provider is connected (the memory adapter still captures)."""
    monkeypatch.setattr("app.modules.notifications.adapters.email_integrated", lambda: True)


async def _status(admin: Browser, slug: str, status: str) -> Any:
    return await admin.request("PUT", f"/admin/courses/{slug}/status", json={"status": status})


# --------------------------------------------------------------------------- course status


async def test_course_status_crud_public_map_and_registration_gate(client, db, browser) -> None:
    _, admin = await admin_setup(client, db, "198.18.3.10")
    slug = f"cs-{uuid.uuid4().hex[:6]}"

    # opening a course without an active fee plan is refused
    r = await _status(admin, slug, "open")
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "no_fee_plan" and r.json()["detail"].startswith("Set a fee")
    assert (await _status(admin, slug, "bogus")).status_code in (400, 422)

    await full_fee_plan(admin, slug)  # opens the course (helper)
    lst = await admin.get("/admin/courses/status")
    assert lst.status_code == 200, lst.text
    item = next(i for i in lst.json()["data"] if i["course_slug"] == slug)
    assert item["status"] == "open" and item["plan_active"] is True and item["fee_paise"] == FULL
    assert item["updated_at"] and item["batch"] is None

    pub = await browser.get("/public/courses/status")
    assert pub.status_code == 200, pub.text
    assert pub.json()["data"][slug] == "open" and pub.json()["updated_at"]
    assert "max-age=30" in pub.headers["cache-control"]
    plan = await browser.get(f"/public/admissions/plans/{slug}")
    assert plan.json()["course_status"] == "open" and plan.json()["registration_open"] is True

    reg = await register(browser, slug)  # open: accepted

    for st in ("coming_soon", "closed"):
        r = await _status(admin, slug, st)
        assert r.status_code == 200 and r.json()["status"] == st, r.text
        assert (await browser.get("/public/courses/status")).json()["data"][slug] == st
        # the plan view still answers (registered students pay instalments) and says why
        pv = await browser.get(f"/public/admissions/plans/{slug}")
        assert pv.status_code == 200 and pv.json()["course_status"] == st
        assert pv.json()["registration_open"] is False
        res = await browser.post("/public/admissions/registrations", reg_body(slug, claim=claim(FULL)))
        assert res.status_code == 409, res.text
        assert res.json()["code"] == "registration_closed" and res.json()["course_status"] == st

    # a student signed in to the LMS is refused too, and the plan view has no form
    student = await adult(db)
    sb = Browser(client, ip="203.0.113.170")
    assert (await sb.login(student.email)).json()["result"] == "authenticated"
    mp = await sb.get(f"/me/admissions/plans/{slug}")
    assert mp.status_code == 200 and mp.json()["course_status"] == "closed" and mp.json()["plan"] is None

    assert reg["reg_no"]


async def test_switching_the_fee_plan_off_reads_closed(client, db, browser) -> None:
    _, admin = await admin_setup(client, db, "198.18.3.11")
    slug = f"cs2-{uuid.uuid4().hex[:6]}"
    await full_fee_plan(admin, slug)
    r = await admin.request(
        "PUT",
        "/admin/admissions/plans",
        json={"slug": slug, "title": "Python Full Stack", "fee_paise": FULL, "active": False},
    )
    assert r.status_code == 200, r.text
    assert (await browser.get("/public/courses/status")).json()["data"][slug] == "closed"
    res = await browser.post("/public/admissions/registrations", reg_body(slug, claim=claim(FULL)))
    assert res.status_code == 409 and res.json()["code"] == "registration_closed"


# --------------------------------------------------------------------------- verify & add to batch


async def _verify_enrol(admin: Browser, claim_id: str, **body: Any) -> Any:
    return await admin.post(f"/admin/admissions/claims/{claim_id}/verify-and-enrol", body)


async def test_verify_and_enrol_creates_account_and_login_works(
    simple_auth, client, db, browser, mail
) -> None:
    admin_user, admin = await admin_setup(client, db, "198.18.3.20")
    plan_batch = await make_batch(db, company_org(), admin_user.id)
    chosen = await make_batch(db, company_org(), admin_user.id)
    slug = f"ve-{uuid.uuid4().hex[:6]}"
    await full_fee_plan(admin, slug, batch_id=plan_batch)
    reg = await register(browser, slug)
    item = await queue_item(admin, reg["reg_no"])

    r = await _verify_enrol(admin, item["claim_id"], batch_id=str(chosen))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "enrolled" and out["batch"]["batch_id"] == str(chosen)
    acct = out["account"]
    assert acct["created"] is True and acct["must_change_password"] is True
    assert re.fullmatch(r"td\d{6}", acct["username"]) and acct["email"] == reg["email"]
    pw = acct["temporary_password"]
    assert len(pw) == 10 and pw.isalnum() and not (set(pw) & AMBIGUOUS)
    # memory adapter: not a real provider -> said plainly
    assert out["email"] == {"attempted": True, "sent": False, "reason": "email_not_connected"}
    assert out["login_url"].endswith("/login")
    sent = [m for m in mail.sent if m.template_key == "admissions.login_details"]
    assert sent and acct["username"] in sent[-1].text and pw in sent[-1].text
    assert sent[-1].subject == "Your Tech Drona LMS login" and sent[-1].html

    await system_context(db, "t")
    row = (
        await db.execute(select(AdmissionRegistration).where(AdmissionRegistration.reg_no == reg["reg_no"]))
    ).scalar_one()
    assert row.status == "enrolled" and str(row.user_id) == acct["user_id"]
    assert row.enrolled_batch_id == chosen and row.login_email_sent_at is None
    member = (
        await db.execute(
            text("SELECT status, member_role FROM batch_members WHERE batch_id = :b AND user_id = :u"),
            {"b": chosen, "u": row.user_id},
        )
    ).one()
    assert member == ("active", "student")
    # the password never reaches the admissions events trail (audit_outbox isn't readable by
    # the test role; the audit call sites pass no password)
    trail = (
        await db.execute(text("SELECT count(*) FROM admission_events WHERE detail LIKE :p"), {"p": f"%{pw}%"})
    ).scalar_one()
    assert trail == 0

    # list / detail / queue carry the username
    lst = await admin.get("/admin/admissions/registrations", params={"q": reg["email"]})
    entry = lst.json()["data"][0]
    assert entry["account_username"] == acct["username"] and "login_email_sent_at" in entry
    detail = (await admin.get(f"/admin/admissions/registrations/{row.id}")).json()
    assert detail["account_username"] == acct["username"] and detail["batch"]["batch_id"] == str(chosen)
    q = await admin.get(
        "/admin/admissions/claims", params={"status": "verified", "registration_id": str(row.id)}
    )
    assert q.json()["data"][0]["registration"]["account_username"] == acct["username"]

    # the student signs in with the username (any case) + temporary password, must change it
    sb = Browser(client, ip="203.0.113.171")
    li = await sb.login(acct["username"].upper(), pw)
    assert li.status_code == 200, li.text
    assert li.json()["result"] == "authenticated" and li.json()["must_change_password"] is True
    me = (await sb.get("/me")).json()["user"]
    assert me["username"] == acct["username"] and me["must_change_password"] is True
    denied = await sb.get("/me/classes")
    assert denied.status_code == 403 and denied.json()["code"] == "password_change_required"
    ch = await sb.post("/auth/password/change", {"current_password": pw, "new_password": "MyOwnPass9"})
    assert ch.status_code == 200, ch.text
    # a brand-new account accepts the terms once (the web app's "One last step" page)
    nv = (await sb.get("/me/consents")).json()["notice_version"]
    for purpose in ("terms", "privacy_notice", "core_service"):
        ok = await sb.post("/me/consents", {"purpose": purpose, "action": "granted", "notice_version": nv})
        assert ok.status_code in (200, 201), ok.text
    classes = await sb.get("/me/classes")
    assert classes.status_code == 200, classes.text
    assert str(chosen) in {b["batch"]["id"] for b in classes.json()["batches"]}
    mine = (await sb.get("/me/admissions")).json()["data"]
    assert mine[0]["state"] == "enrolled" and mine[0]["batch"]["batch_id"] == str(chosen)
    assert mine[0]["course_href"] == "/app/classes"

    # pressing it again: idempotent, no new account, no password shown
    again = await _verify_enrol(admin, item["claim_id"], batch_id=str(chosen), send_email=False)
    assert again.status_code == 200, again.text
    assert (
        again.json()["account"]["created"] is False and again.json()["account"]["temporary_password"] is None
    )
    assert again.json()["email"]["attempted"] is False


async def test_existing_account_keeps_its_password(simple_auth, client, db, browser) -> None:
    admin_user, admin = await admin_setup(client, db, "198.18.3.21")
    batch = await make_batch(db, company_org(), admin_user.id)
    slug = f"vx-{uuid.uuid4().hex[:6]}"
    await full_fee_plan(admin, slug, batch_id=batch)
    student = await adult(db)
    reg = await register(browser, slug, email=student.email)
    item = await queue_item(admin, reg["reg_no"])
    r = await _verify_enrol(admin, item["claim_id"], send_email=False)  # null batch: the plan's batch
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["account"]["created"] is False and out["account"]["temporary_password"] is None
    assert out["account"]["user_id"] == str(student.id) and out["batch"]["batch_id"] == str(batch)
    assert out["email"] == {"attempted": False, "sent": False, "reason": None}
    sb = Browser(client, ip="203.0.113.172")
    assert (await sb.login(student.email)).json()["result"] == "authenticated"  # old password works


async def test_insufficient_payment_is_refused(client, db, browser) -> None:
    from tests.admissions.test_admissions import setup_plan

    admin_user, admin = await admin_setup(client, db, "198.18.3.22")
    batch = await make_batch(db, company_org(), admin_user.id)
    slug = f"vi-{uuid.uuid4().hex[:6]}"
    await setup_plan(admin, slug, batch_id=batch)  # Rs 3,000 in two instalments, access at Rs 1,500
    body = reg_body(slug, claim=claim(150000))
    assert (await browser.post("/public/admissions/registrations", body)).status_code == 201
    q = await admin.get("/admin/admissions/claims")
    item = next(c for c in q.json()["data"] if c["registration"]["email"] == body["email"])
    r = await _verify_enrol(admin, item["claim_id"], amount_paise=100000)
    assert r.status_code == 409 and r.json()["code"] == "insufficient_payment", r.text
    # nothing moved (one transaction)
    await system_context(db, "t")
    row = (
        await db.execute(select(AdmissionRegistration).where(AdmissionRegistration.email == body["email"]))
    ).scalar_one()
    assert row.verified_total_paise == 0 and row.user_id is None


async def test_login_email_resets_password_and_reports_delivery(
    simple_auth, email_on, client, db, browser, mail
) -> None:
    admin_user, admin = await admin_setup(client, db, "198.18.3.23")
    batch = await make_batch(db, company_org(), admin_user.id)
    slug = f"vl-{uuid.uuid4().hex[:6]}"
    await full_fee_plan(admin, slug, batch_id=batch)
    reg = await register(browser, slug)
    item = await queue_item(admin, reg["reg_no"])
    out = (await _verify_enrol(admin, item["claim_id"], must_change_password=False)).json()
    assert out["email"] == {"attempted": True, "sent": True, "reason": None}
    assert out["account"]["must_change_password"] is False
    username, old_pw = out["account"]["username"], out["account"]["temporary_password"]
    sb = Browser(client, ip="203.0.113.173")
    li = await sb.login(username, old_pw)
    assert li.json()["result"] == "authenticated" and "must_change_password" not in li.json()

    rid = out["registration_id"]
    r = await admin.post(f"/admin/admissions/registrations/{rid}/login-email", {})
    assert r.status_code == 200, r.text
    new_pw = r.json()["account"]["temporary_password"]
    assert new_pw and new_pw != old_pw and r.json()["account"]["must_change_password"] is True
    assert r.json()["email"]["sent"] is True
    # the old password stops working and the old session is gone
    assert (await sb.get("/me")).status_code == 401
    # new password first: a failed attempt starts the per-account back-off (expected behaviour)
    nb = Browser(client, ip="203.0.113.175")
    li = await nb.login(username, new_pw)
    assert li.status_code == 200, li.text
    assert li.json()["result"] == "authenticated" and li.json()["must_change_password"] is True
    assert (await Browser(client, ip="203.0.113.174").login(username, old_pw)).status_code == 401
    assert new_pw in mail.sent[-1].text and "choose your own password" in mail.sent[-1].text

    detail = (await admin.get(f"/admin/admissions/registrations/{rid}")).json()
    assert detail["login_email_sent_at"]

    # resend without a new password
    r = await admin.post(f"/admin/admissions/registrations/{rid}/login-email", {"reset_password": False})
    assert r.status_code == 200 and r.json()["account"]["temporary_password"] is None


async def test_login_email_without_email_says_not_connected(simple_auth, client, db, browser, mail) -> None:
    admin_user, admin = await admin_setup(client, db, "198.18.3.24")
    batch = await make_batch(db, company_org(), admin_user.id)
    slug = f"vn-{uuid.uuid4().hex[:6]}"
    await full_fee_plan(admin, slug, batch_id=batch)
    reg = await register(browser, slug)
    item = await queue_item(admin, reg["reg_no"])

    # not enrolled yet: no login email
    await system_context(db, "t")
    rid = (
        await db.execute(
            select(AdmissionRegistration.id).where(AdmissionRegistration.reg_no == reg["reg_no"])
        )
    ).scalar_one()
    early = await admin.post(f"/admin/admissions/registrations/{rid}/login-email", {})
    assert early.status_code == 409

    out = (await _verify_enrol(admin, item["claim_id"], send_email=False)).json()
    assert out["account"]["temporary_password"]
    r = await admin.post(f"/admin/admissions/registrations/{rid}/login-email", {"reset_password": True})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == {"attempted": True, "sent": False, "reason": "email_not_connected"}
    # the new password is still returned so staff can hand it over
    assert r.json()["account"]["temporary_password"]
    assert (await admin.get(f"/admin/admissions/registrations/{rid}")).json()["login_email_sent_at"] is None
