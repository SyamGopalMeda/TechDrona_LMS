"""Certificate automation: PDF renderer (deterministic hash), email attachments (SMTP MIME / SES
raw), the outbox state machine, and the admin certificates API (register, PDF on issue,
approval queue -> email with the PDF attached, due list / batch-end issue, settings).

The DB tests use the shared fixtures (Postgres ``techdrona_test``; ``alembic upgrade heads``
includes ``learning_0005``)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select, update

from app.core.db import system_context
from app.core.errors import ProblemError
from app.core.time import ist_date, utcnow
from app.modules.learning import certificates as certs
from app.modules.learning.cert_models import CertificateOutbox
from app.modules.learning.certpdf import CertificateArt, pdf_sha256, render_certificate_pdf
from app.modules.learning.models import Certificate, Enrolment
from app.modules.notifications.adapters import (
    EmailAttachment,
    MemoryEmailAdapter,
    OutboundEmail,
    SesEmailAdapter,
    build_mime,
    set_email_adapter,
)
from tests.catalog.factory import idem, make_published_course, staff, student
from tests.identity.factory import company_org, make_batch, make_user

ART = CertificateArt(
    name="Ananya Reddy",
    course_title="Data Structures for Placements",
    public_code="ABCDEFGH2345",
    issued_on=date(2026, 11, 11),
    verify_url="https://lms.example.test/verify/ABCDEFGH2345",
)


# --------------------------------------------------------------------------- pure units


def test_certificate_pdf_renders_and_hash_is_stable() -> None:
    a = render_certificate_pdf(ART)
    b = render_certificate_pdf(ART)
    assert a.startswith(b"%PDF-") and len(a) > 5000
    assert a == b and pdf_sha256(a) == hashlib.sha256(b).digest()
    other = render_certificate_pdf(CertificateArt(**{**ART.__dict__, "name": "Rahul Varma"}))
    assert pdf_sha256(other) != pdf_sha256(a)


def test_certificate_pdf_survives_long_and_non_latin_names() -> None:
    art = CertificateArt(
        **{**ART.__dict__, "name": "Şrīnivāsa Rāmānujan Ayyangar " * 3, "course_title": "Python " * 40}
    )
    assert render_certificate_pdf(art).startswith(b"%PDF-")


def test_outbox_state_machine() -> None:
    assert certs.next_status("awaiting", "approve") == "pending"
    assert certs.next_status("failed", "approve") == "pending"
    assert certs.next_status("pending", "sent") == "sent"
    assert certs.next_status("pending", "fail") == "failed"
    for st in ("awaiting", "pending", "failed"):
        assert certs.next_status(st, "cancel") == "cancelled"
    for st, action in (
        ("sent", "cancel"),
        ("sent", "approve"),
        ("cancelled", "approve"),
        ("awaiting", "sent"),
    ):
        with pytest.raises(ProblemError) as e:
            certs.next_status(st, action)
        assert e.value.code == "invalid_state_transition"
    with pytest.raises(ValueError):
        certs.next_status("awaiting", "explode")


def test_email_attachments_smtp_mime_and_ses_raw() -> None:
    pdf = render_certificate_pdf(ART)
    msg = OutboundEmail(
        "learner@example.test",
        "Your certificate",
        "Attached.",
        attachments=(EmailAttachment("ABCDEFGH2345.pdf", "application/pdf", pdf),),
    )
    mime = build_mime(msg, "Tech Drona <no-reply@example.test>", message_id="<x@td>")
    parts = list(mime.iter_attachments())
    assert [p.get_filename() for p in parts] == ["ABCDEFGH2345.pdf"]
    assert parts[0].get_content_type() == "application/pdf" and parts[0].get_content() == pdf
    ses = SesEmailAdapter(client=object())
    raw = ses.request(msg)
    assert "Raw" in raw["Content"] and b"ABCDEFGH2345.pdf" in raw["Content"]["Raw"]["Data"]
    plain = ses.request(OutboundEmail("learner@example.test", "S", "t"))  # unchanged without attachments
    assert plain["Content"]["Simple"]["Body"]["Text"]["Data"] == "t"


def test_email_content_mentions_number_and_verify_link() -> None:
    subject, text = certs.email_content(
        name="Ananya Reddy", course_title="DSA", public_code="ABCDEFGH2345", url=ART.verify_url
    )
    assert "DSA" in subject and text.startswith("Dear Ananya,")
    assert "ABCDEFGH2345" in text and ART.verify_url in text


# --------------------------------------------------------------------------- DB / API


@pytest.fixture
def stores():
    from app.modules.commerce.documents import MemoryDocumentStore, set_document_store

    docs = MemoryDocumentStore()
    mail = MemoryEmailAdapter()
    set_document_store(docs)
    set_email_adapter(mail)
    yield docs, mail
    set_document_store(None)
    set_email_adapter(None)


async def _manual_cert(db, browser, cm):
    author = await make_user(db)
    pc = await make_published_course(db, author.id)
    s = await student(db, browser)
    enr = (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).json()
    r = await cm.post(
        "/certificates", {"enrolment_id": enr["id"], "reason": "Offline exam passed"}, headers=idem()
    )
    assert r.status_code == 201, r.text
    return s, pc, uuid.UUID(r.json()["id"])


@pytest.mark.usefixtures("catalog_backend")
async def test_issue_generates_pdf_queues_email_and_approval_sends_it(browser, db, stores) -> None:
    docs, mail = stores
    cm = browser.fork()
    await staff(db, cm, "content_manager")
    s, pc, cert_id = await _manual_cert(db, browser, cm)

    # the outbox relay consumer (learning.certificate_issued)
    await system_context(db, "t")
    await certs.on_certificate_issued(db, cert_id, "manual")
    await certs.on_certificate_issued(db, cert_id, "manual")  # idempotent
    cert = await db.get(Certificate, cert_id)
    assert cert.pdf_s3_key and cert.template_version == "cert-v2"
    stored, ctype = next(v for (b, k), v in docs.objects.items() if k == cert.pdf_s3_key)
    assert ctype == "application/pdf" and hashlib.sha256(stored).digest() == bytes(cert.content_hash)
    rows = list(
        (
            await db.execute(select(CertificateOutbox).where(CertificateOutbox.certificate_id == cert_id))
        ).scalars()
    )
    assert len(rows) == 1 and rows[0].status == "awaiting" and rows[0].origin == "manual"

    # learners cannot use the admin API
    assert (await browser.get("/admin/certificates")).status_code == 403

    reg = (await cm.get("/admin/certificates", params={"course_id": str(pc.course_id)})).json()
    assert [c["id"] for c in reg["data"]] == [str(cert_id)]
    assert reg["data"][0]["pdf_available"] is True and reg["data"][0]["email_status"] == "awaiting"
    assert (await cm.get("/admin/certificates", params={"q": s.email[:6]})).json()["data"]
    assert (
        await cm.get("/admin/certificates", params={"status": "revoked", "course_id": str(pc.course_id)})
    ).json()["data"] == []
    one = (await cm.get(f"/admin/certificates/{cert_id}")).json()
    assert one["content_sha256"] == bytes(cert.content_hash).hex()
    assert (await cm.get(f"/admin/certificates/{cert_id}/pdf")).json()["url"].startswith("memory://")

    q = (await cm.get("/admin/certificates/outbox", params={"status": "awaiting"})).json()
    ob = next(r for r in q["data"] if r["certificate"]["id"] == str(cert_id))
    assert q["counts"]["awaiting"] >= 1
    r = await cm.post("/admin/certificates/outbox/approve", {"ids": [ob["id"]]}, headers=idem())
    assert r.status_code == 200, r.text
    assert r.json()["approved"] == 1 and r.json()["sent"] == 1
    sent = [m for m in mail.sent if m.template_key == "learning.certificate_issued"]
    assert len(sent) == 1 and sent[0].to == s.email
    assert sent[0].attachments[0].filename == f"{cert.public_code}.pdf"
    assert hashlib.sha256(sent[0].attachments[0].data).digest() == bytes(cert.content_hash)

    # sent rows cannot be approved again or cancelled
    r = await cm.post("/admin/certificates/outbox/cancel", {"ids": [ob["id"]]}, headers=idem())
    assert r.json()["cancelled"] == 0 and r.json()["skipped"][0]["reason"] == "sent"

    # regenerate keeps the same bytes for the same content
    r = await cm.post(f"/admin/certificates/{cert_id}/regenerate", headers=idem())
    assert r.status_code == 200 and r.json()["content_sha256"] == bytes(cert.content_hash).hex()


@pytest.mark.usefixtures("catalog_backend")
async def test_cancel_and_revoked_certificates_are_not_sent(browser, db, stores) -> None:
    _docs, mail = stores
    cm = browser.fork()
    await staff(db, cm, "content_manager")
    _s, _pc, cert_id = await _manual_cert(db, browser, cm)
    await system_context(db, "t")
    await certs.on_certificate_issued(db, cert_id, "manual")
    row = (
        await db.execute(select(CertificateOutbox).where(CertificateOutbox.certificate_id == cert_id))
    ).scalar_one()
    r = await cm.post("/admin/certificates/outbox/cancel", {"ids": [str(row.id)]}, headers=idem())
    assert r.json()["cancelled"] == 1
    await db.refresh(row)
    assert row.status == "cancelled" and row.cancelled_at is not None

    # a pending row of a revoked certificate is cancelled by the sender, never emailed
    await db.execute(
        update(CertificateOutbox)
        .where(CertificateOutbox.id == row.id)
        .values(status="pending", cancelled_at=None)
    )
    await db.execute(
        update(Certificate)
        .where(Certificate.id == cert_id)
        .values(revoked_at=utcnow(), revoke_reason="test revoke")
    )
    await db.flush()
    db.expire_all()
    out = await certs.send_pending(db)
    assert out["cancelled"] >= 1 and not [
        m for m in mail.sent if m.template_key == "learning.certificate_issued"
    ]


@pytest.mark.usefixtures("catalog_backend")
async def test_auto_send_setting_and_batch_end_due_issue(browser, db, stores) -> None:
    _docs, mail = stores
    cm = browser.fork()
    cmu = await staff(db, cm, "content_manager")
    author = await make_user(db)
    pc = await make_published_course(db, author.id)
    await student(db, browser)
    enr = (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).json()
    bid = await make_batch(db, company_org(), cmu.id)
    from app.modules.orgs.models import Batch

    await system_context(db, "t")
    await db.execute(
        update(Batch).where(Batch.id == bid).values(ends_on=ist_date(utcnow()) - timedelta(days=1))
    )
    await db.execute(update(Enrolment).where(Enrolment.id == uuid.UUID(enr["id"])).values(batch_id=bid))
    await db.flush()

    due = (await cm.get("/admin/certificates/due", params={"course_id": str(pc.course_id)})).json()
    row = next(r for r in due["data"] if r["enrolment_id"] == enr["id"])
    assert row["due_because"] == "batch_ended" and row["eligible"] is False
    assert row["reason"] == "lessons_incomplete"
    r = await cm.post("/admin/certificates/due/issue", {"enrolment_ids": [enr["id"]]}, headers=idem())
    assert r.json()["issued"] == 0 and r.json()["skipped"][0]["reason"] == "lessons_incomplete"

    # auto-send on: the queued email is pending (no approval) and the sender delivers it
    assert (await cm.request("PUT", "/admin/certificates/settings", json={"auto_send": True})).json()[
        "auto_send"
    ] is True
    assert (await cm.get("/admin/certificates/settings")).json()["auto_send"] is True
    await system_context(db, "t")
    await db.execute(update(Enrolment).where(Enrolment.id == uuid.UUID(enr["id"])).values(progress_pct=100))
    await db.flush()
    r = await cm.post("/admin/certificates/due/issue", {"course_id": str(pc.course_id)}, headers=idem())
    assert r.status_code == 200 and r.json()["issued"] == 1, r.text
    again = await cm.post("/admin/certificates/due/issue", {"course_id": str(pc.course_id)}, headers=idem())
    assert again.json()["issued"] == 0  # idempotent: one certificate per enrolment
    await system_context(db, "t")
    cert = (
        await db.execute(select(Certificate).where(Certificate.enrolment_id == uuid.UUID(enr["id"])))
    ).scalar_one()
    ob = (
        await db.execute(select(CertificateOutbox).where(CertificateOutbox.certificate_id == cert.id))
    ).scalar_one()
    assert ob.status == "pending" and ob.origin == "manual"
    out = await certs.send_pending(db)
    assert out["sent"] >= 1
    assert any(m.attachments and m.attachments[0].filename == f"{cert.public_code}.pdf" for m in mail.sent)
    summary = (await cm.get("/admin/certificates/summary", params={"course_id": str(pc.course_id)})).json()
    assert summary["issued"] == 1 and summary["auto_send"] is True
    assert (await cm.request("PUT", "/admin/certificates/settings", json={"auto_send": False})).json()[
        "auto_send"
    ] is False
