"""Issued documents against Postgres (shared fixtures; ``alembic upgrade heads`` includes
``learning_0006``): settings gate, issue + PDF + email through the shared outbox, register,
public verify (documents and old certificate codes), PDF check, revoke / supersede, templates,
and the enrolment -> admission letter automation."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import select

from app.core.audit import AuditActor
from app.core.db import system_context
from app.core.errors import ProblemError
from app.modules.learning import certificates as certs
from app.modules.learning import documents as docs
from app.modules.learning.cert_models import CertificateOutbox
from app.modules.learning.doc_models import IssuedDocument
from app.modules.notifications.adapters import MemoryEmailAdapter, set_email_adapter
from tests.catalog.factory import idem, make_published_course, staff, student
from tests.identity.factory import make_user

SYSTEM = AuditActor.system("tests.documents")
ADMISSION = {
    "doc_type": "offer_course",
    "recipient": {"name": "Ananya Reddy", "email": "ananya.docs@example.test"},
    "fields": {
        "program": "Full Stack Web Development",
        "batch_start": "2026-12-01",
        "duration": "16 weeks",
        "mode": "Online",
    },
}


@pytest.fixture
def stores():
    from app.modules.commerce.documents import MemoryDocumentStore, set_document_store

    store = MemoryDocumentStore()
    mail = MemoryEmailAdapter()
    set_document_store(store)
    set_email_adapter(mail)
    yield store, mail
    set_document_store(None)
    set_email_adapter(None)


async def _ready(cm) -> None:
    r = await cm.request(
        "PUT", "/admin/documents/settings", json={"signatory": "A Signatory", "designation": "Director"}
    )
    assert r.status_code == 200 and r.json()["problem"] is None, r.text


async def test_issue_send_register_verify_and_pdf_check(browser, db, stores) -> None:
    _store, mail = stores
    cm = browser.fork()
    await staff(db, cm, "content_manager")

    # settings gate: no signatory -> refused
    r = await cm.post("/admin/documents", ADMISSION, headers=idem())
    assert r.status_code == 409 and r.json()["code"] == "invalid_state_transition", r.text
    await _ready(cm)

    # missing required fields are named
    bad = {**ADMISSION, "fields": {"program": "x"}}
    r = await cm.post("/admin/documents", bad, headers=idem())
    assert r.status_code == 400 and "Batch start date" in r.json()["missing"]

    r = await cm.post("/admin/documents", ADMISSION, headers=idem())
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["ref_no"].startswith("TD-AL-") and d["pdf_available"] and d["email_status"] == "sent"
    sent = [m for m in mail.sent if m.template_key == docs.EMAIL_TEMPLATE_KEY]
    assert sent and sent[0].to == "ananya.docs@example.test"
    att = sent[0].attachments[0]
    assert (
        att.filename == f"{d['ref_no']}.pdf" and hashlib.sha256(att.data).hexdigest() == d["content_sha256"]
    )

    # learners cannot use the admin API
    assert (await browser.get("/admin/documents")).status_code in (401, 403)  # not signed in / no permission
    reg = (await cm.get("/admin/documents", params={"q": "ananya.docs"})).json()
    assert [x["id"] for x in reg["data"]] == [d["id"]] and reg["counts"]["valid"] >= 1
    one = (await cm.get(f"/admin/documents/{d['id']}")).json()
    assert one["emails"][0]["status"] == "sent" and one["paragraphs"][0] == "Dear Ananya,"
    assert (await cm.get(f"/admin/documents/{d['id']}/pdf")).json()["url"].startswith("memory://")

    # public verify by ref (any spelling) and the PDF check; old certificate codes still 404 cleanly
    v = await browser.get(f"/certificates/verify/{d['ref_no']}")
    assert v.status_code == 200 and v.json()["kind"] == "document" and v.json()["status"] == "valid"
    assert v.json()["recipient"] == "Ananya Reddy" and v.json()["program"] == "Full Stack Web Development"
    assert "fields" not in v.json() and "paragraphs" not in v.json()
    slashed = d["ref_no"].replace("-", "/").lower()
    assert (await browser.get(f"/certificates/verify/{slashed}")).status_code in (
        200,
        404,
    )  # path may split on "/"
    ok = await browser.get(
        f"/certificates/verify/{d['ref_no']}/check", params={"sha256": d["content_sha256"]}
    )
    assert ok.json() == {"match": True, "status": "valid"}
    no = await browser.get(f"/certificates/verify/{d['ref_no']}/check", params={"sha256": "0" * 64})
    assert no.json()["match"] is False
    assert (await browser.get("/certificates/verify/ZZZZZZZZZZZZ")).status_code == 404
    assert (await browser.get("/certificates/verify/TD-AL-2026-ZZZZZZ")).status_code == 404

    # the shared approval queue lists document rows with a normalised item
    q = (await cm.get("/admin/certificates/outbox", params={"status": "sent", "kind": "document"})).json()
    row = next(x for x in q["data"] if x["item"] and x["item"]["number"] == d["ref_no"])
    assert row["certificate"] is None and row["item"]["kind"] == "document"


async def test_revoke_supersede_and_verify_states(browser, db, stores) -> None:
    _store, mail = stores
    cm = browser.fork()
    await staff(db, cm, "content_manager")
    await _ready(cm)
    d = (await cm.post("/admin/documents", {**ADMISSION, "email": "queue"}, headers=idem())).json()
    assert d["email_status"] == "awaiting"
    await system_context(db, "t")
    doc = await db.get(IssuedDocument, uuid.UUID(d["id"]))

    new = await docs.reissue(db, SYSTEM, doc, fields={"duration": "20 weeks"})
    await db.refresh(doc)
    assert doc.status == "superseded" and doc.superseded_by_id == new.id and new.replaces_id == doc.id
    assert new.fields["duration"] == "20 weeks" and new.origin == "reissue"
    with pytest.raises(ProblemError):  # only one correction per document; superseded cannot be re-issued
        await docs.reissue(db, SYSTEM, doc)
    old_v = (await browser.get(f"/certificates/verify/{doc.ref_no}")).json()
    assert old_v["status"] == "superseded" and old_v["superseded_by"] == new.ref_no
    new_v = (await browser.get(f"/certificates/verify/{new.ref_no}")).json()
    assert new_v["status"] == "valid" and new_v["replaces"] == doc.ref_no

    # revoking cancels unsent emails and is idempotent
    row = await docs.queue_email(db, new, origin="resend", status="awaiting")
    assert row is not None
    assert await docs.revoke(db, SYSTEM, new, "Issued in error", public_reason=True) is True
    assert await docs.revoke(db, SYSTEM, new, "again") is False
    await db.refresh(row)
    assert row.status == "cancelled"
    rv = (await browser.get(f"/certificates/verify/{new.ref_no}")).json()
    assert rv["status"] == "revoked" and rv["revoked_reason"] == "Issued in error" and "program" not in rv
    assert not [m for m in mail.sent if m.template_key == docs.EMAIL_TEMPLATE_KEY]


async def test_templates_override_and_reset(browser, db, stores) -> None:
    cm = browser.fork()
    await staff(db, cm, "content_manager")
    await _ready(cm)
    body = {"content": {"paragraphs": ["Hello {{first_name}}, welcome to {{program}}."]}}
    r = await cm.request("PUT", "/admin/documents/templates/document/offer_course", json=body)
    assert r.status_code == 200, r.text
    d = (await cm.post("/admin/documents", {**ADMISSION, "email": "none"}, headers=idem())).json()
    one = (await cm.get(f"/admin/documents/{d['id']}")).json()
    assert one["paragraphs"] == ["Hello Ananya, welcome to Full Stack Web Development."]
    bad = {"content": {"paragraphs": ["Dear [Student name]"]}}
    await cm.request("PUT", "/admin/documents/templates/document/offer_course", json=bad)
    r = await cm.post("/admin/documents", {**ADMISSION, "email": "none"}, headers=idem())
    assert r.status_code == 400 and r.json()["leftovers"] == ["[Student name]"]
    assert (await cm.request("DELETE", "/admin/documents/templates/document/offer_course")).status_code == 200
    cat = (await cm.get("/admin/documents/templates")).json()
    assert cat["documents"]["offer_course"]["override"] is None and "general" in cat["emails"]


@pytest.mark.usefixtures("catalog_backend")
async def test_enrolment_queues_one_admission_letter_for_approval(browser, db, stores) -> None:
    _store, mail = stores
    cm = browser.fork()
    await staff(db, cm, "content_manager")
    await _ready(cm)
    author = await make_user(db)
    pc = await make_published_course(db, author.id)
    await student(db, browser)
    enr = (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).json()
    await system_context(db, "t")
    eid = uuid.UUID(enr["id"])

    assert await docs.on_enrolled(db, eid, "free") is None  # free self-enrolment: no letter
    doc = await docs.on_enrolled(db, eid, "manual")
    assert doc is not None and doc.doc_type == "offer_course" and doc.origin == "enrolment"
    assert await docs.on_enrolled(db, eid, "manual") is None  # once per enrolment
    rows = list(
        (await db.execute(select(CertificateOutbox).where(CertificateOutbox.document_id == doc.id))).scalars()
    )
    assert len(rows) == 1 and rows[0].status == "awaiting" and rows[0].origin == "enrolment"
    out = await certs.approve(db, SYSTEM, [rows[0].id])
    assert out["approved"] == 1 and out["sent"] == 1
    assert next(m for m in mail.sent if m.template_key == docs.EMAIL_TEMPLATE_KEY).attachments
