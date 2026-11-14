"""Signed-in student admissions (``/me/admissions``): register for a course and upload payment
proofs inside the LMS, bound to the account (no registration number + email lookup)."""

from __future__ import annotations

import base64
import uuid

from sqlalchemy import select

from app.core.db import system_context
from app.modules.admissions.models import AdmissionRegistration
from tests.admissions.test_admissions import FEE, admin_setup, claim, png, setup_plan
from tests.catalog.factory import make_published_course
from tests.identity.factory import Browser, company_org, make_batch
from tests.security.helpers import adult


def my_body(slug: str, **kw: object) -> dict[str, object]:
    return {
        "course_slug": slug,
        "name": "Ravi Kumar",
        "phone": "98480 12345",
        "college": "VR Siddhartha Engineering College",
        "branch": "ECE",
        "year": "4th year",
        "consent": True,
        "claim": claim(FEE),
        "proof": png(),
        **kw,
    }


async def student_browser(client, db, ip: str):  # type: ignore[no-untyped-def]
    student = await adult(db)
    sb = Browser(client, ip=ip)
    assert (await sb.login(student.email)).json()["result"] == "authenticated"
    return student, sb


async def test_plan_view_without_plan_is_not_an_error(client, db) -> None:
    _, sb = await student_browser(client, db, "203.0.113.160")
    r = await sb.get(f"/me/admissions/plans/nope-{uuid.uuid4().hex[:6]}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"] is None and body["payment"] is None and body["pay_configured"] is False
    assert body["registration"] is None and body["prefill"]["email"]
    assert (await sb.get("/me/admissions/plans/Bad Slug!")).status_code == 404
    assert (await sb.get("/me/admissions")).json() == {"data": []}


async def test_register_in_lms_needs_info_reupload_verify_enrol(client, db, docs) -> None:
    admin_user, admin = await admin_setup(client, db, "198.18.1.40")
    course = await make_published_course(db, admin_user.id, is_free=False, title="Full Stack Java")
    batch_id = await make_batch(db, company_org(), admin_user.id)
    slug = f"java-me-{uuid.uuid4().hex[:6]}"
    await setup_plan(admin, slug, course_id=course.course_id, batch_id=batch_id)
    student, sb = await student_browser(client, db, "203.0.113.161")

    plan = await sb.get(f"/me/admissions/plans/{slug}")
    assert plan.status_code == 200, plan.text
    p = plan.json()
    assert p["plan"]["fee_paise"] == FEE and p["pay_configured"] is True
    assert p["payment"]["upi_id"] == "techdrona.pay@ybl"  # site-wide settings first, like the website
    assert p["plan"]["amount_options"][0] == {"label": "Full fee", "amount_paise": FEE}
    assert p["prefill"]["email"] == student.email.lower() and p["registration"] is None

    # consent + a real proof are required; the account email is used (never typed)
    bad = await sb.post("/me/admissions/registrations", my_body(slug, consent=False))
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "consent"
    txt = {"filename": "x.png", "data_b64": base64.b64encode(b"not an image " * 20).decode()}
    bad = await sb.post("/me/admissions/registrations", my_body(slug, proof=txt))
    assert bad.status_code in (400, 422) and bad.json()["errors"][0]["field"] == "proof", bad.text
    assert (
        await sb.post("/me/admissions/registrations", my_body(slug, email="x@example.com"))
    ).status_code in (400, 422)  # extra fields are refused

    r = await sb.post("/me/admissions/registrations", my_body(slug, reg_no="tdr-me12cd34"))
    assert r.status_code == 201, r.text
    reg = r.json()
    assert reg["reg_no"] == "TDR-ME12CD34" and reg["state"] == "pending" and reg["can_pay"] is False
    assert reg["claims"][0]["status"] == "pending" and reg["balance_paise"] == FEE

    await system_context(db, "t")
    row = (
        await db.execute(select(AdmissionRegistration).where(AdmissionRegistration.reg_no == "TDR-ME12CD34"))
    ).scalar_one()
    assert row.user_id == student.id and row.email == student.email.lower()

    dup = await sb.post("/me/admissions/registrations", my_body(slug))
    assert dup.status_code == 409 and dup.json()["errors"][0]["code"] == "already_registered"

    # staff ask for a better screenshot: the student sees the reason and uploads again
    q = await admin.get("/admin/admissions/claims")
    first = next(c for c in q.json()["data"] if c["registration"]["reg_no"] == "TDR-ME12CD34")
    ni = await admin.post(
        f"/admin/admissions/claims/{first['claim_id']}/needs-info", {"reason": "Screenshot is cut off"}
    )
    assert ni.status_code == 200, ni.text
    mine = (await sb.get("/me/admissions")).json()["data"]
    assert (
        len(mine) == 1 and mine[0]["state"] == "needs_info" and mine[0]["reason"] == "Screenshot is cut off"
    )
    assert mine[0]["can_pay"] is True and mine[0]["pay_options"][-1]["amount_paise"] == FEE

    # another account can't add a claim to this registration
    _, other = await student_browser(client, db, "203.0.113.162")
    stranger = await other.post(
        "/me/admissions/claims",
        {"registration_id": reg["registration_id"], "claim": claim(FEE), "proof": png()},
    )
    assert stranger.status_code == 404

    again = await sb.post(
        "/me/admissions/claims",
        {"registration_id": reg["registration_id"], "claim": claim(FEE), "proof": png()},
    )
    assert again.status_code == 201, again.text
    # the re-upload closes the earlier "needs info" claim (replaced), so one stays open
    assert again.json()["open_claims"] == 1 and len(again.json()["claims"]) == 2
    assert again.json()["state"] == "pending"

    # approval enrols this account; the status page links to the course
    q = await admin.get("/admin/admissions/claims")
    newest = next(
        c
        for c in q.json()["data"]
        if c["registration"]["reg_no"] == "TDR-ME12CD34" and c["claim_id"] != first["claim_id"]
    )
    v = await admin.post(
        f"/admin/admissions/claims/{newest['claim_id']}/verify", {"amount_paise": FEE, "checked": True}
    )
    assert v.status_code == 200, v.text
    assert v.json()["enrolled"] is True, v.json()
    mine = (await sb.get("/me/admissions")).json()["data"][0]
    assert mine["state"] == "enrolled" and mine["enrolled"] is True
    assert mine["course_href"] and mine["course_href"].startswith("/app/courses/")
    assert mine["balance_paise"] == 0 and mine["can_pay"] is False
