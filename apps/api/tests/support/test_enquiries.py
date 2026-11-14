"""D8: public corporate enquiry form (``POST /public/enquiries``) and the Admin enquiry queue."""

from __future__ import annotations

import uuid

import pytest

from app.core.db import system_context
from app.modules.notifications.service import notifications_for_user
from tests.identity.factory import Browser
from tests.security.helpers import adult, staff, staff_browser
from tests.support import helpers as h

pytestmark = pytest.mark.usefixtures("support_backend")

SECRET_EMAIL = "priya.secret@acme-example.com"
SECRET_PHONE = "9876501234"


def form(**kw):
    return {
        "name": "Priya Raman",
        "company": "Acme Example Pvt Ltd",
        "email": SECRET_EMAIL,
        "phone": SECRET_PHONE,
        "message": "We would like training for 40 engineers on cloud and DevOps next quarter.",
        "consent": True,
        **kw,
    }


async def _count(db) -> int:
    await system_context(db, "t")
    return await h.enquiry_count(db)


async def test_public_enquiry_stored_notified_and_admin_queue(client, db, browser, mail) -> None:
    admin = await staff(db, "super_admin")
    before = await _count(db)

    r = await browser.post("/public/enquiries", form())
    assert r.status_code == 202, r.text
    assert r.json() == {"status": "received"}
    assert await _count(db) == before + 1
    row = await h.latest_enquiry(db)
    assert row.email == SECRET_EMAIL and row.phone == "+919876501234" and row.status == "new"
    assert row.reference.startswith("TD-E-") and row.consent_at is not None

    # Every Admin is notified (in-app + email); the message carries only the reference.
    notes = await notifications_for_user(db, admin.id)
    assert any(n.template_key == "support.corporate_enquiry_received" for n in notes)
    sent = [m for m in mail.sent if row.reference in m.subject]
    assert sent and all(SECRET_EMAIL not in m.text and "Priya" not in m.text for m in sent)

    ab = await staff_browser(client, admin, ip="198.18.0.81")
    q = await ab.get("/support/enquiries")
    assert q.status_code == 200, q.text
    item = next(x for x in q.json()["data"] if x["enquiry_id"] == str(row.id))
    assert item["company"] == "Acme Example Pvt Ltd" and "message" not in item
    assert q.json()["counts"]["new"] >= 1
    detail = await ab.get(f"/support/enquiries/{row.id}")
    assert detail.status_code == 200 and detail.json()["message"].startswith("We would like")
    upd = await ab.patch(
        f"/support/enquiries/{row.id}",
        {"status": "in_progress", "assign_to_me": True, "staff_note": "Called"},
    )
    assert upd.status_code == 200 and upd.json()["assigned_to"] == str(admin.id)
    assert (await ab.patch(f"/support/enquiries/{row.id}", {"status": "closed"})).json()["closed_at"]
    assert (await ab.get(f"/support/enquiries/{uuid.uuid4()}")).status_code == 404


async def test_enquiry_queue_is_admin_only(client, db, browser) -> None:
    assert (await browser.get("/support/enquiries")).status_code == 401
    cm = await staff_browser(client, await staff(db, "content_manager"), ip="198.18.0.82")
    assert (await cm.get("/support/enquiries")).status_code == 403
    student = await adult(db)
    sb = Browser(client, ip="203.0.113.83")
    assert (await sb.login(student.email)).json()["result"] == "authenticated"
    assert (await sb.get("/support/enquiries")).status_code == 403


async def test_validation_consent_and_no_pii_in_errors(db, browser) -> None:
    before = await _count(db)
    cases = [
        form(consent=False),
        form(email="not-an-email"),
        form(phone="12"),
        form(phone="abcdefghij"),
        form(name="x"),
        form(company="C" * 151),
        form(message="short"),
        form(message="m" * 4001),
        form(name="Priya\x07Raman"),
        {**form(), "organization_id": str(uuid.uuid4())},  # extra=forbid
        {k: v for k, v in form().items() if k != "consent"},
    ]
    for body in cases:
        r = await browser.post("/public/enquiries", body)
        assert r.status_code in (400, 422), (body, r.text)
        assert SECRET_EMAIL not in r.text and SECRET_PHONE not in r.text and "Priya" not in r.text
    r = await browser.post("/public/enquiries", form(consent=False))
    assert r.json()["errors"][0]["field"] == "consent"
    assert await _count(db) == before
    # phone is optional (another IP: the rejects above used up this IP's hourly quota)
    fresh_ip = Browser(browser.client, ip="203.0.113.98")
    assert (
        await fresh_ip.post("/public/enquiries", form(phone=None, email="ops@acme-example.com"))
    ).status_code == 202


async def test_honeypot_accepted_silently(db, browser, mail) -> None:
    before = await _count(db)
    r = await browser.post("/public/enquiries", form(website="http://spam.example"))
    assert r.status_code == 202 and r.json() == {"status": "received"}
    assert await _count(db) == before
    assert not [m for m in mail.sent if "corporate enquiry" in m.subject]


async def test_rate_limited_per_ip_and_per_email(client, db, browser) -> None:
    # 3 per email per day
    for i in range(3):
        assert (await browser.post("/public/enquiries", form())).status_code == 202, i
    limited = await browser.post("/public/enquiries", form())
    assert limited.status_code == 429 and SECRET_EMAIL not in limited.text
    # 5 per IP per hour (the 4 above already counted); other emails from the same IP
    assert (await browser.post("/public/enquiries", form(email="a@acme-example.com"))).status_code == 202
    assert (await browser.post("/public/enquiries", form(email="c@acme-example.com"))).status_code == 429
    other_ip = Browser(client, ip="203.0.113.99")
    assert (await other_ip.post("/public/enquiries", form(email="b@acme-example.com"))).status_code == 202
