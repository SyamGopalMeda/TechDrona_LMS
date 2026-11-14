"""Bulk documents over HTTP (``doc_bulk`` + ``/admin/documents/bulk/*``), every module on Firestore,
**no Postgres** (same harness as ``test_learning_http``).

Run: ``TD_TEST_NO_PG=1 TD_TEST_DB_NAME=learning_test .venv/Scripts/python.exe -m pytest -q
tests/learning/fs/test_documents_bulk_http.py``.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

import pytest

from tests.learning.fs import test_learning_http as base
from tests.learning.fs.test_learning_http import API, _idem, _login, _published_course

web = base.web  # fixtures shared with the learning HTTP suite
stores = base.stores

BULK = f"{API}/admin/documents/bulk"
ADMISSION_FIELDS = {
    "program": "Full Stack Web Development",
    "batch_start": "2026-12-01",
    "duration": "16 weeks",
    "mode": "Online",
}


@pytest.fixture(autouse=True)
def bulk_audit(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """``doc_bulk.audit`` -> a recorder (core audit is Postgres; ``web`` stubs the other modules)."""
    from app.modules.learning import doc_bulk

    seen: list[tuple[str, Any]] = []

    async def fake_audit(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> None:
        seen.append((action, kw.get("after")))

    monkeypatch.setattr(doc_bulk, "audit", fake_audit)
    return seen


def _row(n: int, name: str, email: str, **fields: str) -> dict[str, Any]:
    return {"row": n, "name": name, "email": email, "fields": {**ADMISSION_FIELDS, **fields}}


async def _admin(c: Any, auth: Any, make_principal: Any, *, settings: bool = True) -> dict[str, str]:
    _, ah = _login(auth, make_principal, "certificate.issue_manual", is_platform=True)
    if settings:
        r = await c.put(
            f"{API}/admin/documents/settings",
            json={"signatory": "A Signatory", "designation": "Director"},
            headers=ah,
        )
        assert r.status_code == 200, r.text
    return ah


def _issue_body(rows: list[dict[str, Any]], bulk_id: str, **kw: Any) -> dict[str, Any]:
    return {"doc_type": "offer_course", "bulk_id": bulk_id, "label": "december.xlsx", "rows": rows, **kw}


async def test_bulk_permissions(web: Any, make_principal: Any, stores: Any) -> None:
    c, auth, _ = web
    _, lh = _login(auth, make_principal)  # a learner: no certificate.issue_manual
    bid = str(uuid.uuid4())
    rows = [_row(2, "Ananya Reddy", "ananya.bulk@example.test")]
    assert (
        await c.post(f"{BULK}/validate", json={"doc_type": "offer_course", "rows": rows}, headers=lh)
    ).status_code == 403
    r = await c.post(f"{BULK}/issue", json=_issue_body(rows, bid), headers={**lh, **_idem()})
    assert r.status_code == 403
    assert (await c.get(f"{BULK}/{bid}", headers=lh)).status_code == 403
    assert (await c.post(f"{BULK}/pdfs", json={"document_ids": [bid]}, headers=lh)).status_code == 403
    assert (await c.get(f"{BULK}/enrolments", params={"course_id": bid}, headers=lh)).status_code == 403
    r = await c.post(f"{API}/admin/certificates/due/preview", json={"enrolment_id": bid}, headers=lh)
    assert r.status_code == 403


async def test_bulk_validate_reports_every_problem(
    web: Any, make_principal: Any, stores: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.notifications import public as notifications_public

    monkeypatch.setattr(notifications_public, "email_integrated", lambda: False)
    c, auth, _ = web
    ah = await _admin(c, auth, make_principal, settings=False)
    rows = [
        _row(2, "Ananya Reddy", "ananya.v@example.test"),
        _row(3, "Bad Date", "bad.date@example.test", batch_start="01/12/2026", mode="Offline"),
        {"row": 4, "name": "", "email": "not-an-email", "fields": {"program": "X"}},
        _row(5, "Ananya Again", "ANANYA.V@example.test"),
        {**_row(6, "Mobile Typo", "mobile@example.test"), "mobile": "call me"},
        {**_row(7, "Has Mobile", "has.mobile@example.test"), "mobile": "+91 98765 43210"},
    ]
    r = await c.post(f"{BULK}/validate", json={"doc_type": "offer_course", "rows": rows}, headers=ah)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["settings_problem"]  # no signatory yet: reported, rows still checked
    assert out["email_ready"] is False  # email not integrated: the UI offers downloads
    by = {x["row"]: x for x in out["rows"]}
    assert by[2]["ok"] and by[7]["ok"], out
    assert by[2]["fields"]["mode"] == "Online"
    assert len(by[3]["errors"]) == 2  # both bad cells, not only the first
    assert any("YYYY-MM-DD" in e for e in by[3]["errors"]) and any("Online" in e for e in by[3]["errors"])
    assert "Student name" in by[4]["missing"] and "Valid student email" in by[4]["missing"]
    assert "Batch start date" in by[4]["missing"]
    assert any("row 2" in e for e in by[5]["errors"]), by[5]  # duplicate recipient (case-insensitive)
    assert any("Mobile" in e for e in by[6]["errors"])
    assert out["total"] == 6 and out["ok"] == 2 and out["failed"] == 4

    bad = await c.post(f"{BULK}/validate", json={"doc_type": "nope", "rows": rows}, headers=ah)
    assert bad.status_code == 400
    too_many = [_row(i + 2, f"P{i}", f"p{i}@example.test") for i in range(1001)]
    r = await c.post(f"{BULK}/validate", json={"doc_type": "offer_course", "rows": too_many}, headers=ah)
    assert r.status_code == 400


async def test_bulk_issue_partial_failure_links_users_and_lists_the_run(
    web: Any, make_principal: Any, stores: Any, monkeypatch: pytest.MonkeyPatch, bulk_audit: Any
) -> None:
    from app.modules.identity import public as identity_public
    from app.modules.learning import documents as docs

    c, auth, _ = web
    _store, mail = stores
    ah = await _admin(c, auth, make_principal, settings=False)
    bid = str(uuid.uuid4())
    known = uuid.uuid4()

    class _User:
        id = known

    async def users_by_emails(session: Any, emails: Any) -> dict[str, Any]:
        return {e: _User() for e in emails if e == "learner.bulk@example.test"}

    monkeypatch.setattr(identity_public, "users_by_emails", users_by_emails)

    rows = [
        _row(2, "Ananya Reddy", "learner.bulk@example.test"),
        _row(3, "Missing Duration", "missing.bulk@example.test", duration=""),
        _row(4, "Boom Row", "boom.bulk@example.test"),
        _row(5, "Ravi Kumar", "ravi.bulk@example.test"),
    ]
    # settings missing: the whole call is refused (nothing issued)
    r = await c.post(f"{BULK}/issue", json=_issue_body(rows, bid), headers={**ah, **_idem()})
    assert r.status_code == 409 and r.json()["code"] == "invalid_state_transition", r.text
    # an idempotency key is required
    await _admin(c, auth, make_principal)
    r = await c.post(f"{BULK}/issue", json=_issue_body(rows, bid), headers=ah)
    assert r.status_code == 400, r.text

    real = docs.issue_document

    async def flaky(session: Any, actor: Any, **kw: Any) -> Any:
        if kw["recipient"]["name"] == "Boom Row":
            raise RuntimeError("renderer exploded")
        return await real(session, actor, **kw)

    monkeypatch.setattr(docs, "issue_document", flaky)
    key = _idem()
    body = _issue_body(rows, bid, email="outbox")
    r = await c.post(f"{BULK}/issue", json=body, headers={**ah, **key})
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["issued"], out["failed"], out["deferred"]) == (2, 2, 0), out
    by = {x["row"]: x for x in out["results"]}
    assert by[2]["status"] == "issued" and by[2]["ref_no"].startswith("TD-AL-") and by[2]["user_linked"]
    assert by[2]["verify_url"] == f"/verify/{by[2]['ref_no']}" and by[2]["pdf_available"]
    assert by[2]["email_status"] == "awaiting"  # auto-send off: waits in the approval queue
    assert by[5]["status"] == "issued" and not by[5]["user_linked"]
    assert by[3]["status"] == "failed" and "Duration" in (by[3]["missing"] or []), by[3]
    assert by[4]["status"] == "failed" and by[4]["code"] == "internal_error"
    assert mail.sent == []  # queued, not sent
    assert bulk_audit[-1][0] == "documents.bulk_issue" and bulk_audit[-1][1]["issued"] == 2

    # idempotency: the same chunk again replays the first answer, nothing is issued twice
    again = await c.post(f"{BULK}/issue", json=body, headers={**ah, **key})
    assert again.status_code == 200 and again.json() == out

    run = await c.get(f"{BULK}/{bid}", headers=ah)
    assert run.status_code == 200, run.text
    data = run.json()["data"]
    assert [d["bulk_row"] for d in data] == [2, 5] and run.json()["counts"]["valid"] == 2
    assert all(d["bulk_id"] == bid for d in data)
    assert data[0]["user_id"] == str(known) and data[0]["email_status"] == "awaiting"
    reg = (await c.get(f"{API}/admin/documents", params={"q": "ravi.bulk"}, headers=ah)).json()
    assert [x["bulk_id"] for x in reg["data"]] == [bid]

    # the approval queue lists the queued emails
    q = await c.get(
        f"{API}/admin/certificates/outbox", params={"status": "awaiting", "kind": "document"}, headers=ah
    )
    assert q.status_code == 200 and len(q.json()["data"]) == 2, q.text

    # PDFs for the ZIP
    ids = [d["id"] for d in data]
    p = await c.post(f"{BULK}/pdfs", json={"document_ids": [*ids, str(uuid.uuid4())]}, headers=ah)
    assert p.status_code == 200, p.text
    files = p.json()["files"]
    assert [f["id"] for f in files] == ids and p.json()["skipped"][0]["reason"] == "not_found"
    assert base64.b64decode(files[0]["pdf_base64"])[:4] == b"%PDF"
    assert files[0]["filename"] == f"{data[0]['ref_no']} - Ananya Reddy.pdf"
    too_many = await c.post(f"{BULK}/pdfs", json={"document_ids": [str(uuid.uuid4())] * 21}, headers=ah)
    assert too_many.status_code == 400

    # a later upload warns about recipients who already hold this document
    v = await c.post(
        f"{BULK}/validate",
        json={"doc_type": "offer_course", "rows": [_row(2, "Ravi Kumar", "ravi.bulk@example.test")]},
        headers=ah,
    )
    assert v.json()["rows"][0]["ok"] and "Already has" in v.json()["rows"][0]["warnings"][0], v.text


async def test_bulk_issue_limits_and_time_budget(
    web: Any, make_principal: Any, stores: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.learning import doc_bulk

    c, auth, _ = web
    ah = await _admin(c, auth, make_principal)
    bid = str(uuid.uuid4())
    many = [_row(i + 2, f"P {i}", f"p{i}.limit@example.test") for i in range(201)]
    r = await c.post(f"{BULK}/issue", json=_issue_body(many, bid), headers={**ah, **_idem()})
    assert r.status_code == 400, r.text

    monkeypatch.setattr(doc_bulk, "ISSUE_BUDGET_S", -1.0)  # out of time before the first row
    rows = [_row(2, "Late One", "late.one@example.test"), _row(3, "Late Two", "late.two@example.test")]
    r = await c.post(f"{BULK}/issue", json=_issue_body(rows, bid), headers={**ah, **_idem()})
    assert r.status_code == 200, r.text
    assert r.json()["deferred"] == 2 and r.json()["issued"] == 0
    assert {x["status"] for x in r.json()["results"]} == {"deferred"}
    monkeypatch.setattr(doc_bulk, "ISSUE_BUDGET_S", 40.0)
    r = await c.post(f"{BULK}/issue", json=_issue_body(rows, bid), headers={**ah, **_idem()})
    assert r.json()["issued"] == 2, r.text
    assert len((await c.get(f"{BULK}/{bid}", headers=ah)).json()["data"]) == 2


async def test_bulk_students_source_and_due_preview(web: Any, make_principal: Any, stores: Any) -> None:
    c, auth, _ = web
    ah = await _admin(c, auth, make_principal)
    cid, _lessons = await _published_course(c, auth, make_principal, "fs-bulk-docs")
    learner, lh = _login(auth, make_principal)
    r = await c.post(f"{API}/me/enrolments", json={"course_id": cid}, headers=lh)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]

    assert (await c.get(f"{BULK}/enrolments", headers=ah)).status_code == 400  # batch or course
    r = await c.get(f"{BULK}/enrolments", params={"course_id": cid}, headers=ah)
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert [x["enrolment_id"] for x in rows] == [eid] and rows[0]["user_id"] == str(learner.user_id)
    assert rows[0]["course_title"] == "Course fs-bulk-docs"

    # Due tab: preview one certificate before "issue all" (nothing stored)
    r = await c.post(f"{API}/admin/certificates/due/preview", json={"enrolment_id": eid}, headers=ah)
    assert r.status_code == 200, r.text
    assert base64.b64decode(r.json()["pdf_base64"])[:4] == b"%PDF"
    assert r.json()["course_title"] == "Course fs-bulk-docs"
    assert (await c.get(f"{API}/admin/certificates", headers=ah)).json()["data"] == []
    r = await c.post(
        f"{API}/admin/certificates/due/preview", json={"enrolment_id": str(uuid.uuid4())}, headers=ah
    )
    assert r.status_code == 404
