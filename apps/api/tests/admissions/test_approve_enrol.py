"""Admin approval of a UPI payment (full fee, Rs 5,000): approve -> enrolled at once (entitlement,
enrolment, batch membership), idempotent re-approve, reject needs a reason the student sees, the
receipt streamed through the session, list views carry email / last reference / account state."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text, update

from app.core.db import system_context
from app.core.outbox import relay_pending
from app.modules.admissions.models import AdmissionRegistration
from tests.admissions.test_admissions import admin_setup, claim, png, reg_body
from tests.catalog.factory import make_published_course
from tests.identity.factory import Browser, company_org, make_batch
from tests.security.helpers import adult

FULL = 500000  # Rs 5,000, paid in full


async def full_fee_plan(
    admin: Browser, slug: str, *, course_id: uuid.UUID | None = None, batch_id: uuid.UUID | None = None
) -> None:
    r = await admin.request(
        "PUT",
        "/admin/admissions/pay-settings",
        json={"upi_id": "techdrona@ybl", "payee_name": "Tech Drona", "preferred_app": "PhonePe"},
    )
    assert r.status_code == 200, r.text
    r = await admin.request(
        "PUT",
        "/admin/admissions/plans",
        json={
            "slug": slug,
            "title": "Python Full Stack",
            "course_id": str(course_id) if course_id else None,
            "batch_id": str(batch_id) if batch_id else None,
            "fee_paise": FULL,
            "allow_instalments": False,
            "active": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["policy"] == "full" and r.json()["access_min_paise"] == FULL
    # registration is accepted only while the course is open (admissions_0003)
    o = await admin.request("PUT", f"/admin/courses/{slug}/status", json={"status": "open"})
    assert o.status_code == 200, o.text


async def register(browser: Browser, slug: str, **kw: Any) -> dict[str, Any]:
    body = reg_body(slug, claim=claim(FULL), **kw)
    r = await browser.post("/public/admissions/registrations", body)
    assert r.status_code == 201, r.text
    return {**r.json(), "email": body["email"]}


async def queue_item(admin: Browser, reg_no: str) -> dict[str, Any]:
    q = await admin.get("/admin/admissions/claims")
    assert q.status_code == 200, q.text
    return next(c for c in q.json()["data"] if c["registration"]["reg_no"] == reg_no)


async def test_approve_enrols_at_once_and_is_idempotent(client, db, browser, mail) -> None:
    admin_user, admin = await admin_setup(client, db, "198.18.2.10")
    course = await make_published_course(db, admin_user.id, is_free=False, title="Python Full Stack")
    batch_id = await make_batch(db, company_org(), admin_user.id)
    slug = f"py-{uuid.uuid4().hex[:6]}"
    await full_fee_plan(admin, slug, course_id=course.course_id, batch_id=batch_id)
    reg = await register(browser, slug)

    item = await queue_item(admin, reg["reg_no"])
    # the queue shows who paid, how to reach them and what they claim
    r = item["registration"]
    assert r["email"] == reg["email"] and r["phone"] and r["course_title"] == "Python Full Stack"
    assert item["amount_paise"] == FULL and item["utr"] and item["paid_on"] and item["submitted_at"]
    assert item["has_proof"] is True and r["has_account"] is False

    # the receipt itself, through the staff session
    f = await admin.get(f"/admin/admissions/claims/{item['claim_id']}/proof/file")
    assert f.status_code == 200, f.text
    assert f.headers["content-type"].startswith("image/") and f.content[:3] == b"\xff\xd8\xff"
    assert "no-store" in f.headers["cache-control"]

    v = await admin.post(
        f"/admin/admissions/claims/{item['claim_id']}/verify", {"amount_paise": FULL, "checked": True}
    )
    assert v.status_code == 200, v.text
    out = v.json()
    assert out["enrolled"] is True and out["just_enrolled"] is True and out.get("warning") is None, out
    assert out["new_account"] is True and out["already_verified"] is False
    assert out["claim"]["status"] == "verified"
    assert out["registration"]["status"] == "enrolled" and out["registration"]["balance_paise"] == 0

    await system_context(db, "t")
    row = (
        await db.execute(select(AdmissionRegistration).where(AdmissionRegistration.reg_no == reg["reg_no"]))
    ).scalar_one()
    assert row.status == "enrolled" and row.user_id and row.enrolled_at
    member = (
        await db.execute(
            text("SELECT batch_id, user_id, status, member_role FROM batch_members WHERE id = :i"),
            {"i": row.batch_member_id},
        )
    ).one()
    assert member == (batch_id, row.user_id, "active", "student")
    enr = (
        await db.execute(
            text("SELECT user_id, course_id, status FROM enrolments WHERE id = :i"), {"i": row.enrolment_id}
        )
    ).one()
    assert enr == (row.user_id, course.course_id, "active")

    # approve again (double tap): 200, nothing moves, still one entitlement / enrolment
    again = await admin.post(
        f"/admin/admissions/claims/{item['claim_id']}/verify", {"amount_paise": FULL, "checked": True}
    )
    assert again.status_code == 200, again.text
    assert (
        again.json()["already_verified"] is True
        and again.json()["registration"]["verified_total_paise"] == FULL
    )
    n_ent = (
        await db.execute(
            text("SELECT count(*) FROM entitlements WHERE user_id = :u AND course_id = :c"),
            {"u": row.user_id, "c": course.course_id},
        )
    ).scalar_one()
    assert n_ent == 1
    n_members = (
        await db.execute(
            text("SELECT count(*) FROM batch_members WHERE user_id = :u AND batch_id = :b"),
            {"u": row.user_id, "b": batch_id},
        )
    ).scalar_one()
    assert n_members == 1
    n_verified = (
        await db.execute(
            text(
                "SELECT count(*) FROM admission_events WHERE registration_id = :r AND action = 'payment.verified'"
            ),
            {"r": row.id},
        )
    ).scalar_one()
    assert n_verified == 1

    # the registrations list carries the last payment reference and the enrolled status
    lst = await admin.get("/admin/admissions/registrations", params={"q": reg["email"]})
    assert lst.status_code == 200, lst.text
    entry = lst.json()["data"][0]
    assert entry["status"] == "enrolled" and entry["last_utr"] == item["utr"]
    assert entry["last_claim_status"] == "verified" and entry["balance_paise"] == 0


async def test_approve_links_the_lms_account_of_an_in_app_registration(client, db, browser) -> None:
    admin_user, admin = await admin_setup(client, db, "198.18.2.11")
    course = await make_published_course(db, admin_user.id, is_free=False, title="Python Full Stack")
    slug = f"pyu-{uuid.uuid4().hex[:6]}"
    await full_fee_plan(admin, slug, course_id=course.course_id)
    student = await adult(db)
    reg = await register(browser, slug)
    # registered from inside the LMS: the registration carries the signed-in account
    await system_context(db, "t")
    await db.execute(
        update(AdmissionRegistration)
        .where(AdmissionRegistration.reg_no == reg["reg_no"])
        .values(user_id=student.id)
    )
    item = await queue_item(admin, reg["reg_no"])
    assert item["registration"]["has_account"] is True
    v = await admin.post(
        f"/admin/admissions/claims/{item['claim_id']}/verify", {"amount_paise": FULL, "checked": True}
    )
    assert v.status_code == 200, v.text
    assert v.json()["enrolled"] is True and v.json()["new_account"] is False
    assert v.json()["registration"]["user_id"] == str(student.id)


async def test_reject_and_correction_need_a_reason_the_student_sees(client, db, browser, mail) -> None:
    _, admin = await admin_setup(client, db, "198.18.2.12")
    slug = f"pyr-{uuid.uuid4().hex[:6]}"
    await full_fee_plan(admin, slug)
    reg = await register(browser, slug)
    item = await queue_item(admin, reg["reg_no"])
    cid = item["claim_id"]

    for path in ("reject", "needs-info"):
        assert (await admin.post(f"/admin/admissions/claims/{cid}/{path}", {})).status_code in (400, 422)
        assert (await admin.post(f"/admin/admissions/claims/{cid}/{path}", {"reason": " "})).status_code in (
            400,
            422,
        )
        assert (await admin.post(f"/admin/admissions/claims/{cid}/{path}", {"reason": "no"})).status_code in (
            400,
            422,
        )

    rj = await admin.post(f"/admin/admissions/claims/{cid}/reject", {"reason": "No such payment in PhonePe"})
    assert rj.status_code == 200, rj.text
    assert rj.json()["claim"]["status"] == "rejected"
    assert rj.json()["claim"]["review_note"] == "No such payment in PhonePe"
    # a rejected claim can't be approved afterwards
    late = await admin.post(f"/admin/admissions/claims/{cid}/verify", {"amount_paise": FULL, "checked": True})
    assert late.status_code == 409

    # the student is emailed the reason (outbox, after commit)
    await relay_pending(db)
    sent = [m for m in mail.sent if m.to == reg["email"] and m.template_key == "admissions.claim_rejected"]
    assert sent and "No such payment in PhonePe" in sent[-1].text

    # a new proof for the same registration, then a correction request
    c2 = await browser.post(
        "/public/admissions/claims",
        {"reg_no": reg["reg_no"], "email": reg["email"], "claim": claim(FULL), "proof": png()},
    )
    assert c2.status_code == 201, c2.text
    item2 = await queue_item(admin, reg["reg_no"])
    ni = await admin.post(
        f"/admin/admissions/claims/{item2['claim_id']}/needs-info", {"reason": "Screenshot is cut off"}
    )
    assert ni.status_code == 200 and ni.json()["claim"]["status"] == "needs_info"


async def test_new_upload_replaces_claims_waiting_for_a_correction(client, db, browser) -> None:
    _, admin = await admin_setup(client, db, "198.18.2.13")
    slug = f"pys-{uuid.uuid4().hex[:6]}"
    await full_fee_plan(admin, slug)
    reg = await register(browser, slug)
    first = await queue_item(admin, reg["reg_no"])
    ni = await admin.post(
        f"/admin/admissions/claims/{first['claim_id']}/needs-info", {"reason": "Screenshot is cut off"}
    )
    assert ni.status_code == 200, ni.text

    # the corrected upload may reuse the same UTR (same payment, better screenshot)
    c2 = await browser.post(
        "/public/admissions/claims",
        {
            "reg_no": reg["reg_no"],
            "email": reg["email"],
            "claim": claim(FULL, utr=first["utr"]),
            "proof": png(),
        },
    )
    assert c2.status_code == 201, c2.text

    q = await admin.get("/admin/admissions/claims")
    mine = [c for c in q.json()["data"] if c["registration"]["reg_no"] == reg["reg_no"]]
    assert len(mine) == 1 and mine[0]["claim_id"] != first["claim_id"] and mine[0]["status"] == "pending"
    assert mine[0]["registration"]["open_claims"] == 1

    detail = (await admin.get(f"/admin/admissions/registrations/{first['registration_id']}")).json()
    old = next(c for c in detail["claims"] if c["claim_id"] == first["claim_id"])
    assert old["status"] == "rejected" and old["locks_released"] is True
    assert (
        old["review_note"].startswith("Replaced by a newer upload")
        and "Screenshot is cut off" in old["review_note"]
    )
    assert "payment.superseded" in {e["action"] for e in detail["events"]}
