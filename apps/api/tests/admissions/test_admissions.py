"""Admissions: public registration + claims, staff verification, ledger, enrolment on access_min.

Public routes are called like the LMS BFF does (``Browser``: service token + client IP); the
website itself reaches them through ``/api/public/admissions/*`` in apps/web.
"""

from __future__ import annotations

import base64
import io
import random
import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text, update

from app.core.db import system_context
from app.core.outbox import relay_pending
from app.core.time import ist_date, utcnow
from app.modules.admissions.models import AdmissionPaymentClaim, AdmissionRegistration
from tests.catalog.factory import make_published_course
from tests.identity.factory import Browser, company_org, make_batch
from tests.security.helpers import adult, staff, staff_browser

FEE = 300000  # Rs 3,000
TODAY = ist_date(utcnow())


def png() -> dict[str, str]:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (40 + random.randint(0, 200), 30), tuple(random.randint(0, 255) for _ in range(3))).save(
        out, "PNG"
    )
    return {"filename": "payment.png", "data_b64": base64.b64encode(out.getvalue()).decode()}


def pdf_resume() -> dict[str, str]:
    return {"filename": "cv.pdf", "data_b64": base64.b64encode(b"%PDF-1.4\n" + b"resume " * 80).decode()}


def utr() -> str:
    return str(random.randint(10**11, 10**12 - 1))


def claim(amount: int = 150000, **kw: Any) -> dict[str, Any]:
    return {"amount_paise": amount, "method": "upi", "utr": utr(), "paid_on": TODAY.isoformat(), **kw}


def reg_body(slug: str, **kw: Any) -> dict[str, Any]:
    return {
        "course_slug": slug,
        "name": "Priya Sharma",
        "email": f"priya.{uuid.uuid4().hex[:6]}@example.com",
        "phone": "98480 12345",
        "college": "VR Siddhartha Engineering College",
        "branch": "CSE",
        "year": "3rd year",
        "current_status": "Student",
        "preferred_mode": "Online",
        "consent": True,
        "claim": claim(),
        "proof": png(),
        "resume": pdf_resume(),
        **kw,
    }


async def setup_plan(
    admin: Browser, slug: str, *, course_id: uuid.UUID | None = None, batch_id: uuid.UUID | None = None
) -> None:
    r = await admin.request(
        "PUT",
        "/admin/admissions/pay-settings",
        json={"phone": "9502524924", "preferred_app": "PhonePe", "upi_id": "techdrona.pay@ybl"},
    )
    assert r.status_code == 200, r.text
    r = await admin.request(
        "PUT",
        "/admin/admissions/plans",
        json={
            "slug": slug,
            "title": "Full Stack Java",
            "course_id": str(course_id) if course_id else None,
            "batch_id": str(batch_id) if batch_id else None,
            "fee_paise": FEE,
            "allow_instalments": True,
            "schedule": [
                {"label": "First instalment", "amount_paise": 150000, "due": ""},
                {"label": "Second instalment", "amount_paise": 150000, "due": ""},
            ],
            "access_min_paise": 150000,
            # regression 2026-11-11: a UPI ID used to hit an invalid DB regex bound ({2,256} -> 2201B)
            "upi_id": "course.fees@okaxis",
            "active": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["policy"] == "instalments" and r.json()["access_min_paise"] == 150000
    # registration is accepted only while the course is open (admissions_0003)
    o = await admin.request("PUT", f"/admin/courses/{slug}/status", json={"status": "open"})
    assert o.status_code == 200, o.text


async def admin_setup(client: Any, db: Any, ip: str) -> tuple[Any, Browser]:
    user = await staff(db, "super_admin")
    return user, await staff_browser(client, user, ip=ip)


async def test_full_flow_register_verify_enrol(client, db, browser, mail, docs) -> None:
    admin_user, admin = await admin_setup(client, db, "198.18.1.10")
    course = await make_published_course(db, admin_user.id, is_free=False, title="Full Stack Java")
    batch_id = await make_batch(db, company_org(), admin_user.id)
    slug = f"java-{uuid.uuid4().hex[:6]}"
    await setup_plan(admin, slug, course_id=course.course_id, batch_id=batch_id)

    plan = await browser.get(f"/public/admissions/plans/{slug}")
    assert plan.status_code == 200, plan.text
    assert plan.json()["pay"]["phone"] == "9502524924" and plan.json()["fee_paise"] == FEE
    assert plan.json()["pay_configured"] is True and "course_id" not in plan.json()

    body = reg_body(slug, reg_no="TDR-AB12CD34")
    r = await browser.post("/public/admissions/registrations", body)
    assert r.status_code == 201, r.text
    assert r.json()["reg_no"] == "TDR-AB12CD34" and r.json()["status"] == "pending_verification"
    email = body["email"]
    assert len(docs.objects) == 2  # proof + resume, private bucket

    # one registration per email per course; a UTR / screenshot can be claimed once
    dup = await browser.post("/public/admissions/registrations", {**body, "reg_no": None, "claim": claim()})
    assert dup.status_code == 409 and dup.json()["errors"][0]["field"] == "email"
    other = reg_body(slug, claim={**claim(), "utr": body["claim"]["utr"]})
    assert (await browser.post("/public/admissions/registrations", other)).status_code == 409
    same_png = reg_body(slug, proof=body["proof"])
    r2 = await browser.post("/public/admissions/registrations", same_png)
    assert r2.status_code == 409 and r2.json()["errors"][0]["field"] == "proof"

    status = await browser.post(
        "/public/admissions/status", {"reg_no": "tdr-ab12cd34", "email": email.upper()}
    )
    assert status.status_code == 200 and status.json()["balance_paise"] == FEE
    assert (
        await browser.post("/public/admissions/status", {"reg_no": "TDR-AB12CD34", "email": "x@example.com"})
    ).status_code == 404

    q = await admin.get("/admin/admissions/claims")
    assert q.status_code == 200, q.text
    item = next(c for c in q.json()["data"] if c["registration"]["reg_no"] == "TDR-AB12CD34")
    proof = await admin.get(f"/admin/admissions/claims/{item['claim_id']}/proof")
    assert proof.status_code == 200 and proof.json()["url"].startswith("memory://")

    # verifying needs the explicit bank check; the amount actually received counts
    assert (
        await admin.post(
            f"/admin/admissions/claims/{item['claim_id']}/verify", {"amount_paise": 150000, "checked": False}
        )
    ).status_code == 422
    v = await admin.post(
        f"/admin/admissions/claims/{item['claim_id']}/verify", {"amount_paise": 150000, "checked": True}
    )
    assert v.status_code == 200, v.text
    out = v.json()
    assert out["enrolled"] is True and out.get("warning") is None, out
    reg = out["registration"]
    assert (
        reg["status"] == "enrolled"
        and reg["verified_total_paise"] == 150000
        and reg["balance_paise"] == 150000
    )
    # approving the same claim again is idempotent (double tap / two reviewers): nothing moves
    again = await admin.post(
        f"/admin/admissions/claims/{item['claim_id']}/verify", {"amount_paise": 150000, "checked": True}
    )
    assert again.status_code == 200 and again.json()["already_verified"] is True
    assert again.json()["registration"]["verified_total_paise"] == 150000
    # ...but a different amount for an already verified claim is refused
    other_amount = await admin.post(
        f"/admin/admissions/claims/{item['claim_id']}/verify", {"amount_paise": 100000, "checked": True}
    )
    assert other_amount.status_code == 409

    await system_context(db, "t")
    row = (
        await db.execute(select(AdmissionRegistration).where(AdmissionRegistration.reg_no == "TDR-AB12CD34"))
    ).scalar_one()
    assert row.user_id and row.entitlement_id and row.enrolment_id and row.batch_member_id
    ent = (
        await db.execute(
            text("SELECT source_type, course_id, status FROM entitlements WHERE id = :i"),
            {"i": row.entitlement_id},
        )
    ).one()
    assert ent == ("admin_grant", course.course_id, "active")
    enr = (
        await db.execute(
            text("SELECT source, status, batch_id FROM enrolments WHERE id = :i"), {"i": row.enrolment_id}
        )
    ).one()
    assert enr == ("entitlement", "active", batch_id)
    # new account: password-set link through the identity reset flow
    assert any(m.to == email and m.template_key == "auth.password_reset" for m in mail.sent)

    # emails to the student go out from the outbox after commit
    await relay_pending(db)
    keys = {m.template_key for m in mail.sent if m.to == email}
    assert {"admissions.registration_received", "admissions.payment_verified", "admissions.enrolled"} <= keys

    # second instalment through the public claim route, then reverse below access_min (owner)
    c2 = await browser.post(
        "/public/admissions/claims",
        {"reg_no": "TDR-AB12CD34", "email": email, "claim": claim(150000), "proof": png()},
    )
    assert c2.status_code == 201, c2.text
    over = await browser.post(
        "/public/admissions/claims",
        {"reg_no": "TDR-AB12CD34", "email": email, "claim": claim(150001), "proof": png()},
    )
    assert over.status_code == 422  # above the balance
    rv = await admin.post(
        f"/admin/admissions/claims/{item['claim_id']}/reverse", {"reason": "Entered by mistake"}
    )
    assert rv.status_code == 200, rv.text
    assert rv.json()["registration"]["verified_total_paise"] == 0 and rv.json()["warning"]
    await db.refresh(row)
    assert row.enrolled_at is None and row.status == "pending_verification"
    ent_status = (
        await db.execute(
            text(
                "SELECT status FROM entitlements WHERE id = (SELECT entitlement_id FROM enrolments WHERE id = :i)"
            ),
            {"i": row.enrolment_id},
        )
    ).scalar_one()
    assert ent_status == "revoked"


async def test_fee_plan_not_linked_keeps_payment_and_warns(client, db, browser) -> None:
    _, admin = await admin_setup(client, db, "198.18.1.11")
    slug = f"plain-{uuid.uuid4().hex[:6]}"
    await setup_plan(admin, slug)
    r = await browser.post("/public/admissions/registrations", reg_body(slug))
    assert r.status_code == 201, r.text
    q = await admin.get("/admin/admissions/claims")
    cid = next(c["claim_id"] for c in q.json()["data"] if c["registration"]["reg_no"] == r.json()["reg_no"])
    v = await admin.post(f"/admin/admissions/claims/{cid}/verify", {"amount_paise": 150000, "checked": True})
    assert v.status_code == 200
    assert v.json()["registration"]["status"] == "payment_verified" and "isn't linked" in v.json()["warning"]


async def test_needs_info_reject_release_and_open_claim_cap(client, db, browser) -> None:
    _, admin = await admin_setup(client, db, "198.18.1.12")
    slug = f"cap-{uuid.uuid4().hex[:6]}"
    await setup_plan(admin, slug)
    body = reg_body(slug)
    r = await browser.post("/public/admissions/registrations", body)
    reg_no = r.json()["reg_no"]
    for _ in range(2):
        ok = await browser.post(
            "/public/admissions/claims",
            {"reg_no": reg_no, "email": body["email"], "claim": claim(), "proof": png()},
        )
        assert ok.status_code == 201, ok.text
    capped = await browser.post(
        "/public/admissions/claims",
        {"reg_no": reg_no, "email": body["email"], "claim": claim(), "proof": png()},
    )
    assert capped.status_code == 409  # at most 3 waiting

    claims = [
        c
        for c in (await admin.get("/admin/admissions/claims")).json()["data"]
        if c["registration"]["reg_no"] == reg_no
    ]
    first = claims[0]
    assert (
        await admin.post(f"/admin/admissions/claims/{first['claim_id']}/needs-info", {"reason": "ok"})
    ).status_code == 422
    ni = await admin.post(
        f"/admin/admissions/claims/{first['claim_id']}/needs-info", {"reason": "Screenshot is cut off"}
    )
    assert ni.status_code == 200 and ni.json()["claim"]["status"] == "needs_info"
    rj = await admin.post(
        f"/admin/admissions/claims/{first['claim_id']}/reject",
        {"reason": "No such payment", "release_locks": True},
    )
    assert rj.status_code == 200 and rj.json()["registration"]["open_claims"] == 2
    # the released UTR can be used again
    again = await browser.post(
        "/public/admissions/claims",
        {"reg_no": reg_no, "email": body["email"], "claim": {**claim(), "utr": first["utr"]}, "proof": png()},
    )
    assert again.status_code == 201, again.text
    # cancelling frees the email for a new registration
    st = await admin.post(
        f"/admin/admissions/registrations/{first['registration_id']}/status",
        {"status": "cancelled", "reason": "Duplicate"},
    )
    assert st.status_code == 200
    assert (
        await browser.post("/public/admissions/registrations", {**reg_body(slug), "email": body["email"]})
    ).status_code == 201


async def test_ledger_trigger_refuses_unbacked_total(client, db, browser) -> None:
    _, admin = await admin_setup(client, db, "198.18.1.13")
    slug = f"ledger-{uuid.uuid4().hex[:6]}"
    await setup_plan(admin, slug)
    r = await browser.post("/public/admissions/registrations", reg_body(slug))
    await system_context(db, "t")
    await db.execute(text("SET CONSTRAINTS trg_areg_ledger, trg_apc_ledger IMMEDIATE"))
    with pytest.raises(Exception, match="ledger"):
        async with db.begin_nested():
            await db.execute(
                update(AdmissionRegistration)
                .where(AdmissionRegistration.reg_no == r.json()["reg_no"])
                .values(verified_total_paise=1000, balance_paise=FEE - 1000)
            )
    with pytest.raises(Exception, match="ck_areg_ledger"):
        async with db.begin_nested():
            await db.execute(
                update(AdmissionRegistration)
                .where(AdmissionRegistration.reg_no == r.json()["reg_no"])
                .values(balance_paise=1)
            )
    n = (
        (
            await db.execute(
                select(AdmissionPaymentClaim)
                .join(AdmissionRegistration)
                .where(AdmissionRegistration.reg_no == r.json()["reg_no"])
            )
        )
        .scalars()
        .all()
    )
    assert len(n) == 1


async def test_public_validation_honeypot_and_bff_only(client, db, browser, mail) -> None:
    _, admin = await admin_setup(client, db, "198.18.1.14")
    slug = f"val-{uuid.uuid4().hex[:6]}"
    await setup_plan(admin, slug)
    secret = "secret.person@example.com"
    cases = [
        reg_body(slug, email=secret, consent=False),
        reg_body(slug, email=secret, phone="12345"),
        reg_body(slug, email=secret, claim=claim(utr="T2511011234567")),
        reg_body(slug, email=secret, claim=claim(amount=100)),  # below the minimum first payment
        reg_body(slug, email=secret, claim=claim(paid_on=(TODAY + timedelta(days=2)).isoformat())),
        reg_body(
            slug,
            email=secret,
            proof={"filename": "x.txt", "data_b64": base64.b64encode(b"plain text " * 30).decode()},
        ),
        {**reg_body(slug, email=secret), "organization_id": "x"},
    ]
    fresh = Browser(browser.client, ip="203.0.113.140")
    for b in cases:
        res = await fresh.post("/public/admissions/registrations", b)
        assert res.status_code in (400, 409, 422), (b.get("claim"), res.text)
        assert secret not in res.text
    hp = await fresh.post("/public/admissions/registrations", reg_body(slug, website="http://spam"))
    assert hp.status_code == 202
    # browsers never reach the API directly: no service token, no write
    direct = await client.post("/api/v1/public/admissions/registrations", json=reg_body(slug))
    assert direct.status_code == 403
    assert (await browser.get("/public/admissions/plans/does-not-exist")).status_code == 404
    await system_context(db, "t")
    assert not (
        await db.execute(select(AdmissionRegistration).where(AdmissionRegistration.email == secret))
    ).first()


async def test_admin_routes_need_permissions(client, db, browser) -> None:
    assert (await browser.get("/admin/admissions/overview")).status_code == 401
    cm = await staff_browser(client, await staff(db, "content_manager"), ip="198.18.1.15")
    assert (await cm.get("/admin/admissions/claims")).status_code == 403
    assert (
        await cm.request("PUT", "/admin/admissions/plans", json={"slug": "x", "title": "x", "fee_paise": 100})
    ).status_code == 403
    student = await adult(db)
    sb = Browser(client, ip="203.0.113.150")
    assert (await sb.login(student.email)).json()["result"] == "authenticated"
    assert (await sb.get("/admin/admissions/registrations")).status_code == 403
    _, admin = await admin_setup(client, db, "198.18.1.16")
    ov = await admin.get("/admin/admissions/overview")
    assert ov.status_code == 200 and "collected_paise" in ov.json()


async def test_record_payment_and_fee_adjust(client, db, browser) -> None:
    _, admin = await admin_setup(client, db, "198.18.1.17")
    slug = f"rec-{uuid.uuid4().hex[:6]}"
    await setup_plan(admin, slug)
    r = await browser.post("/public/admissions/registrations", reg_body(slug))
    reg_id = (await admin.get("/admin/admissions/registrations", params={"q": r.json()["reg_no"]})).json()[
        "data"
    ][0]["registration_id"]
    rec = await admin.post(
        f"/admin/admissions/registrations/{reg_id}/payments",
        {"amount_paise": 50000, "method": "cash", "paid_on": date.today().isoformat(), "checked": True},
    )
    assert rec.status_code == 200, rec.text
    assert rec.json()["registration"]["status"] == "partially_paid"
    low = await admin.post(
        f"/admin/admissions/registrations/{reg_id}/fee", {"fee_paise": 10000, "reason": "Scholarship"}
    )
    assert low.status_code == 422  # below what is verified
    fee = await admin.post(
        f"/admin/admissions/registrations/{reg_id}/fee", {"fee_paise": 200000, "reason": "Scholarship"}
    )
    assert fee.status_code == 200 and fee.json()["registration"]["balance_paise"] == 150000
    detail = await admin.get(f"/admin/admissions/registrations/{reg_id}")
    assert detail.status_code == 200 and len(detail.json()["claims"]) == 2
    assert {e["action"] for e in detail.json()["events"]} >= {
        "registration.created",
        "payment.recorded",
        "registration.fee",
    }


async def test_import_command_is_idempotent(db) -> None:
    from app.modules.admissions import import_cmd

    data = {
        "fee_plans": {
            "imp-course": {
                "title": "Imported",
                "fee": 200000,
                "allow_installments": True,
                "schedule": [{"label": "A", "amount": 100000}, {"label": "B", "amount": 100000}],
                "access_min": 100000,
                "active": True,
            }
        },
        "fee_accounts": {
            "rec1": {
                "reg_no": "TDR-IMPT0001",
                "email": "imp@example.com",
                "name": "Imp Student",
                "phone": "9848012345",
                "college": "X",
                "branch": "CSE",
                "year": "2nd year",
                "course_slug": "imp-course",
                "course_title": "Imported",
                "fee": 200000,
                "access_min": 100000,
                "policy": "installments",
                "allow_installments": True,
                "verified_total": 100000,
                "balance": 100000,
                "status": "enrolled",
                "created_at": {"_seconds": 1762800000},
            }
        },
        "fee_payments": {
            "p1": {
                "account_id": "rec1",
                "provider": "manual_upi",
                "method": "upi",
                "amount": 100000,
                "utr": "111122223333",
                "paid_on": "2026-11-01",
                "status": "verified",
                "verified_amount": 100000,
                "proof": {"file_id": "f1", "name": "s.jpg", "type": "image/jpeg", "sha256": "c" * 64},
            },
            "p2": {
                "account_id": "rec1",
                "provider": "manual_upi",
                "method": "upi",
                "amount": 100000,
                "utr": "111122224444",
                "paid_on": "2026-11-05",
                "status": "pending",
                "proof": {"file_id": "f2", "name": "t.jpg", "type": "image/jpeg", "sha256": "d" * 64},
            },
        },
    }
    first = await import_cmd.run(db, data)
    assert first == {"plans": 1, "registrations": 1, "claims": 2, "skipped": 0}
    again = await import_cmd.run(db, data)
    assert again["registrations"] == 0 and again["claims"] == 0 and again["plans"] == 0
    await db.execute(text("SET CONSTRAINTS trg_areg_ledger, trg_apc_ledger IMMEDIATE"))  # ledger holds
    r = (
        await db.execute(select(AdmissionRegistration).where(AdmissionRegistration.reg_no == "TDR-IMPT0001"))
    ).scalar_one()
    # enrolled on the website, but LMS access is created only by staff: status follows the money
    assert r.status == "payment_verified" and r.open_claims == 1 and r.balance_paise == 100000
