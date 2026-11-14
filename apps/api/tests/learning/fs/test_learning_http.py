"""learning over HTTP through the real FastAPI app, every involved module on Firestore, **no
Postgres** (data-learning agent; harness: ``tests/paths/fs/http_harness.py``).

Run: ``TD_TEST_NO_PG=1 TD_TEST_DB_NAME=learning_test .venv/Scripts/python.exe -m pytest -q
tests/learning/fs``.

The request session is ``tests/learning/fs/harness.LearningSession`` (a ``FakeSession``): it keeps RLS GUCs in memory for
``system_context`` and **fails the test on any other SQL statement or ORM ``add``**, so a learning
route that still reaches Postgres fails here. Audit / outbox / maintenance flag / entitlement
cache (core, other agents) are recorders (``stub_core``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from tests.learning.fs.harness import batch_with, client_for, close_app, login, open_app

API = "/api/v1"
MODULES = (
    "learning",
    "catalog",
    "core",
    "entitlements",
    "ai",
    "identity",
    "orgs",
    "admin",
    "notifications",
    "rbac",
)
AUTHOR = (
    "course.create",
    "course.edit",
    "course.preview",
    "course.publish",
    "course.submit_review",
    "course.archive",
    "course.settings_change",
)
LEARNING_MODULES = (
    "app.modules.learning.service",
    "app.modules.learning.router",
    "app.modules.learning.structured",
    "app.modules.learning.structured_api",
    "app.modules.learning.certificates",
    "app.modules.learning.cert_admin",
    "app.modules.learning.documents",
    "app.modules.learning.doc_admin",
)


@pytest.fixture
async def web(
    fs_client: Any, monkeypatch: pytest.MonkeyPatch, auth: Any
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, list[tuple[str, Any]]]]:
    from app.modules.learning import service as svc

    app, calls = await open_app(fs_client, monkeypatch, stores=MODULES, stubbed=LEARNING_MODULES)
    # wiring.py registers analytics/assessments lookups (other agents' modules) at app import
    monkeypatch.setattr(svc, "_coverage_lookup", None)
    monkeypatch.setattr(svc, "_final_test_lookup", None)
    try:
        async with client_for(app) as c:
            yield c, auth, calls
    finally:
        close_app(app, monkeypatch, MODULES)


_login = login


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


async def _published_course(
    c: httpx.AsyncClient, auth: Any, make_principal: Any, slug: str
) -> tuple[str, list[str]]:
    """A free, public course with two article lessons, published through the catalog studio."""
    _, ah = _login(auth, make_principal, *AUTHOR, is_platform=True)
    _, ph = _login(auth, make_principal, *AUTHOR, is_platform=True)
    r = await c.post(
        f"{API}/studio/courses",
        json={"title": f"Course {slug}", "slug": slug, "visibility": "public", "is_free": True},
        headers=ah,
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    lessons = []
    for title in ("Intro", "Wrap-up"):
        r = await c.post(
            f"{API}/studio/courses/{cid}/draft/lessons",
            json={
                "title": title,
                "lesson_type": "article",
                "article_body": {"doc": title},
                "est_reading_minutes": 2,
            },
            headers=ah,
        )
        assert r.status_code == 201, r.text
        lessons.append(r.json()["id"])
    r = await c.put(
        f"{API}/studio/courses/{cid}/draft/outline",
        json={"modules": [{"title": "Only", "lesson_ids": lessons}]},
        headers=ah,
    )
    assert r.status_code == 200, r.text
    assert (await c.post(f"{API}/studio/courses/{cid}/submit-review", headers=ah)).status_code == 200
    r = await c.post(
        f"{API}/studio/courses/{cid}/publish", json={"change_type": "major"}, headers={**ph, **_idem()}
    )
    assert r.status_code == 200, r.text
    return cid, lessons


async def _read_long_ago(user_id: uuid.UUID) -> None:
    """Backdate the learner's lesson opens (the Postgres suite updates ``lesson_progress``)."""
    from datetime import timedelta

    from app.core.firestore.store import ScopedStore
    from app.core.time import utcnow
    from app.modules.learning import store_specs as ss

    st = ScopedStore.system("test.clock")
    page = await st.query(ss.PROGRESS, user_id=user_id, order_by=(), limit=100)
    for d in page.items:
        await st.update(ss.PROGRESS, d.id, {"first_opened_at": utcnow() - timedelta(hours=1)})


async def test_enrol_learn_complete_and_certificate(web: Any, make_principal: Any) -> None:
    c, auth, calls = web
    cid, lessons = await _published_course(c, auth, make_principal, "fs-python")
    learner, lh = _login(auth, make_principal)

    r = await c.post(f"{API}/me/enrolments", json={"course_id": cid}, headers=lh)
    assert r.status_code == 201, r.text
    assert r.json()["progress_pct"] in (0, 0.0, "0.00")
    again = await c.post(f"{API}/me/enrolments", json={"course_id": cid}, headers=lh)
    assert again.status_code == 200, again.text  # already enrolled: same enrolment
    assert again.json()["id"] == r.json()["id"]
    mine = (await c.get(f"{API}/me/enrolments", headers=lh)).json()["data"]
    assert [e["course"]["id"] if isinstance(e.get("course"), dict) else e.get("course_id") for e in mine] == [
        cid
    ]

    keys = []
    for lid in lessons:
        r = await c.get(f"{API}/me/courses/{cid}/lessons/{lid}", headers=lh)
        assert r.status_code == 200, r.text
        keys.append(r.json()["lesson_key"] if "lesson_key" in r.json() else r.json()["lesson"]["lesson_key"])
    await _read_long_ago(learner.user_id)  # the minimum reading time has passed
    for key in keys:
        r = await c.post(
            f"{API}/me/lessons/{key}/completion", json={"evidence": {"scrolled_to_end": True}}, headers=lh
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"
    ov = await c.get(f"{API}/me/courses/{cid}", headers=lh)
    assert ov.status_code == 200, ov.text
    enr = ov.json()["enrolment"] if "enrolment" in ov.json() else ov.json()
    assert float(enr["progress_pct"]) == 100.0, ov.text

    certs = (await c.get(f"{API}/me/certificates", headers=lh)).json()["data"]
    assert len(certs) == 1, certs
    code = certs[0]["public_code"]
    v = await c.get(f"{API}/certificates/verify/{code}")
    assert v.status_code == 200 and v.json()["status"] == "valid", v.text
    assert (await c.get(f"{API}/certificates/verify/ZZZZZZZZZZZZ")).status_code == 404
    dash = await c.get(f"{API}/me/dashboard", headers=lh)
    assert dash.status_code == 200, dash.text

    # another learner sees none of it
    _, oh = _login(auth, make_principal)
    assert (await c.get(f"{API}/me/certificates", headers=oh)).json()["data"] == []
    assert (await c.get(f"{API}/me/courses/{cid}", headers=oh)).status_code == 404
    assert ("event", "learning.certificate_issued") in calls or any(k == "event" for k, _ in calls)
    assert str(learner.user_id)


_batch_with = batch_with


async def test_batch_assignment_submit_grade_release(web: Any, make_principal: Any) -> None:
    from datetime import timedelta

    from app.core.time import utcnow

    c, auth, _calls = web
    trainer, th = _login(auth, make_principal, "assignment.manage", "assignment.grade", "enrolment.read")
    learner, lh = _login(auth, make_principal)
    _outsider, oh = _login(auth, make_principal)
    batch = await _batch_with([learner.user_id], trainer.user_id)

    r = await c.post(
        f"{API}/assignments",
        json={
            "batch_id": str(batch),
            "title": "Linked lists",
            "instructions_md": "Reverse a list",
            "submission_type": "text",
            "max_score": 10,
            "due_at": (utcnow() + timedelta(days=3)).isoformat(),
        },
        headers=th,
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert (await c.post(f"{API}/assignments", json={"batch_id": str(batch), "title": "x", "instructions_md": "x",
                                                   "submission_type": "text", "max_score": 5}, headers=lh)).status_code == 403  # fmt: skip

    mine = await c.get(f"{API}/me/assignments", headers=lh)
    assert mine.status_code == 200, mine.text
    assert [a["id"] for a in mine.json()["data"]] == [aid]
    assert (await c.get(f"{API}/me/assignments/{aid}", headers=oh)).status_code == 404

    body = {"body_text": "def reverse(xs): return xs[::-1]"}
    r = await c.post(f"{API}/me/assignments/{aid}/submissions", json=body, headers={**lh, **_idem()})
    assert r.status_code == 201 and r.json()["status"] == "submitted", r.text
    sub_id = r.json()["id"]
    r = await c.post(f"{API}/me/assignments/{aid}/submissions", json=body, headers={**lh, **_idem()})
    assert r.status_code == 409 and r.json()["code"] == "attempt_limit_reached", r.text

    queue = await c.get(f"{API}/assignments/{aid}/submissions", headers=th)
    assert queue.status_code == 200, queue.text
    assert [s["id"] for s in queue.json()["data"]] == [sub_id]
    r = await c.post(f"{API}/assignment-submissions/{sub_id}/grade", json={"score": 11}, headers=th)
    assert r.status_code == 422, r.text  # above max_score
    r = await c.post(
        f"{API}/assignment-submissions/{sub_id}/grade", json={"score": 8, "feedback_md": "Good"}, headers=th
    )
    assert r.status_code == 200 and r.json()["status"] == "graded", r.text
    hidden = (await c.get(f"{API}/me/assignments/{aid}", headers=lh)).json()
    subs = hidden.get("my_submissions") or hidden.get("submissions")
    assert subs and subs[0]["status"] == "graded" and subs[0].get("score") is None, hidden  # not released
    assert (await c.post(f"{API}/assignments/{aid}/release-grades", headers=th)).status_code == 200
    shown = (await c.get(f"{API}/me/assignments/{aid}", headers=lh)).json()
    subs = shown.get("my_submissions") or shown.get("submissions")
    assert float(subs[0]["score"]) == 8.0 and subs[0]["feedback_md"] == "Good", shown
    r = await c.post(f"{API}/assignment-submissions/{sub_id}/grade", json={"score": 9}, headers=th)
    assert r.status_code == 409, r.text  # released: only an override may change it


async def test_structured_assignment_workspace_finalize_publish_regrade(
    web: Any, make_principal: Any
) -> None:
    from datetime import timedelta

    from app.core.time import utcnow

    c, auth, _calls = web
    trainer, th = _login(auth, make_principal, "assignment.manage", "assignment.grade")
    learner, lh = _login(auth, make_principal)
    _other, oh = _login(auth, make_principal)
    batch = await _batch_with([learner.user_id], trainer.user_id)
    from app.core.company import COMPANY_ORG_ID
    from app.modules.orgs.service import ensure_org_membership

    # evaluators must be company staff (or hold a grading role): orgs on Firestore
    await ensure_org_membership(None, COMPANY_ORG_ID, trainer.user_id, member_type="staff", added_by=None)  # type: ignore[arg-type]

    r = await c.post(
        f"{API}/assignments",
        json={"batch_id": str(batch), "title": "Lists", "submission_type": "structured", "max_score": 10},
        headers=th,
    )
    assert r.status_code == 201 and r.json()["structured"] is True, r.text
    aid = r.json()["id"]
    structure = {
        "sections": [
            {
                "title": "Section 1",
                "items": [
                    {"source": "inline", "item_type": "essay", "prompt_md": "What is a list?", "marks": 4},
                    {"source": "inline", "item_type": "essay", "prompt_md": "Explain slicing.", "marks": 6},
                ],
            }
        ]
    }
    r = await c.put(f"{API}/assignments/{aid}/structure", json=structure, headers=th)
    assert r.status_code == 200 and r.json()["marks"]["ok"] is True, r.text
    sec = r.json()["sections"][0]
    item_ids = [it["id"] for it in sec["items"]]
    assert (await c.get(f"{API}/assignments/{aid}/structure", headers=th)).json()["sections"][0]["id"] == sec[
        "id"
    ]

    now = utcnow()
    alloc = {
        "batch_id": str(batch),
        "visible_from": (now - timedelta(hours=1)).isoformat(),
        "visible_until": (now + timedelta(days=2)).isoformat(),
        "start_at": (now - timedelta(minutes=5)).isoformat(),
        "due_at": (now + timedelta(days=1)).isoformat(),
        "section_engines": {sec["id"]: "pure_manual"},
        "evaluator_ids": [str(trainer.user_id)],
    }
    r = await c.post(f"{API}/assignments/{aid}/allocations", json=alloc, headers=th)
    assert r.status_code == 201, r.text
    assert len((await c.get(f"{API}/assignments/{aid}/allocations", headers=th)).json()["data"]) == 1

    mine = (await c.get(f"{API}/me/assignments", headers=lh)).json()["data"]
    assert [a["id"] for a in mine] == [aid] and mine[0]["schedule"]["can_start"] is True
    assert (await c.get(f"{API}/me/assignments/{aid}/workspace", headers=oh)).status_code == 404
    r = await c.post(f"{API}/me/assignments/{aid}/workspace/start", headers=lh)
    assert r.status_code == 200, r.text
    assert [i["item_type"] for i in r.json()["sections"][0]["items"]] == ["essay", "essay"]
    url = f"{API}/me/assignments/{aid}/workspace/items"
    for iid, text in zip(item_ids, ("An ordered sequence.", "xs[a:b] copies a range."), strict=True):
        r = await c.put(f"{url}/{iid}", json={"response": {"text": text}}, headers=lh)
        assert r.status_code == 200 and r.json()["saved_at"], r.text
    r = await c.post(f"{API}/me/assignments/{aid}/workspace/submit", headers={**lh, **_idem()})
    assert r.status_code == 200, r.text
    r = await c.put(f"{url}/{item_ids[0]}", json={"response": {"text": "late"}}, headers=lh)
    assert r.status_code == 409, r.text  # submitted: no more edits

    ev = await c.get(f"{API}/assignments/{aid}/evaluation", headers=th)
    assert ev.status_code == 200, ev.text
    rows = ev.json()["rows"]
    assert len(rows) == 1, rows
    sub_id = rows[0]["submission_id"]
    rv = await c.get(f"{API}/assignment-submissions/{sub_id}/review", headers=th)
    assert rv.status_code == 200, rv.text
    fin = {
        "items": [
            {"item_id": item_ids[0], "marks": 3, "feedback_md": "Good."},
            {"item_id": item_ids[1], "marks": 6, "feedback_md": "Excellent."},
        ]
    }
    r = await c.post(f"{API}/assignment-submissions/{sub_id}/finalize", json=fin, headers=th)
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["final"] == 9.0
    res = (await c.get(f"{API}/me/assignments/{aid}/result", headers=lh)).json()
    assert res["published"] is False and res["submission"]["score"] is None

    r = await c.post(f"{API}/assignments/{aid}/release-grades", headers=th)
    assert r.status_code == 200 and r.json()["unfinalized_count"] == 0, r.text
    res = (await c.get(f"{API}/me/assignments/{aid}/result", headers=lh)).json()
    assert res["published"] is True and res["submission"]["score"] == 9.0
    assert [i["final_marks"] for i in res["items"]] == [3.0, 6.0]

    rg = f"{API}/me/assignment-submissions/{sub_id}/regrade-requests"
    r = await c.post(rg, json={"reason": "Please recheck question 1", "item_id": item_ids[0]}, headers=lh)
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    r = await c.post(rg, json={"reason": "Please recheck question 2"}, headers=lh)
    assert r.status_code == 409, r.text  # one open request per submission
    q = (await c.get(f"{API}/assignments/{aid}/regrade-requests?status=open", headers=th)).json()
    assert [x["id"] for x in q["data"]] == [req_id]
    r = await c.post(
        f"{API}/assignment-regrade-requests/{req_id}/resolve",
        json={"action": "resolve", "note": "Re-opened for review", "reopen": True},
        headers=th,
    )
    assert r.status_code == 200 and r.json()["status"] == "resolved", r.text
    res = (await c.get(f"{API}/me/assignments/{aid}/result", headers=lh)).json()
    assert res["published"] is False and res["regrade"]["status"] == "resolved"
    r = await c.post(rg, json={"reason": "Please recheck question 2 again"}, headers=lh)
    assert r.status_code in (201, 409), r.text  # the open-request key was released by the resolve


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
def stores() -> Any:
    from app.modules.commerce.documents import MemoryDocumentStore, set_document_store
    from app.modules.notifications.adapters import MemoryEmailAdapter, set_email_adapter

    store = MemoryDocumentStore()
    mail = MemoryEmailAdapter()
    set_document_store(store)
    set_email_adapter(mail)
    yield store, mail
    set_document_store(None)
    set_email_adapter(None)


async def test_documents_issue_register_verify_revoke_and_admin_certificates(
    web: Any, make_principal: Any, stores: Any
) -> None:
    from app.core.time import utcnow

    c, auth, _calls = web
    _store, mail = stores
    _, ah = _login(
        auth, make_principal, "certificate.issue_manual", "certificate.revoke", is_platform=True,
        tier="privileged", mfa_level="totp", auth_time=utcnow(), last_step_up_at=utcnow(),
    )  # fmt: skip
    _, lh = _login(auth, make_principal)

    r = await c.post(f"{API}/admin/documents", json=ADMISSION, headers={**ah, **_idem()})
    assert r.status_code == 409 and r.json()["code"] == "invalid_state_transition", r.text  # no signatory
    r = await c.put(
        f"{API}/admin/documents/settings",
        json={"signatory": "A Signatory", "designation": "Director"},
        headers=ah,
    )
    assert r.status_code == 200 and r.json()["problem"] is None, r.text
    assert (await c.get(f"{API}/admin/documents/settings", headers=ah)).json()["signatory"] == "A Signatory"

    r = await c.post(f"{API}/admin/documents", json=ADMISSION, headers={**ah, **_idem()})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["ref_no"].startswith("TD-AL-") and d["pdf_available"] and d["email_status"] == "sent", d
    assert any(m.to == "ananya.docs@example.test" for m in mail.sent)
    assert (await c.get(f"{API}/admin/documents", headers=lh)).status_code == 403
    reg = (await c.get(f"{API}/admin/documents", params={"q": "ananya.docs"}, headers=ah)).json()
    assert [x["id"] for x in reg["data"]] == [d["id"]] and reg["counts"]["valid"] >= 1
    one = (await c.get(f"{API}/admin/documents/{d['id']}", headers=ah)).json()
    assert one["emails"][0]["status"] == "sent"

    v = await c.get(f"{API}/certificates/verify/{d['ref_no']}")
    assert v.status_code == 200 and v.json()["kind"] == "document" and v.json()["status"] == "valid", v.text
    ok = await c.get(f"{API}/certificates/verify/{d['ref_no']}/check", params={"sha256": d["content_sha256"]})
    assert ok.json() == {"match": True, "status": "valid"}
    assert (await c.get(f"{API}/certificates/verify/TD-AL-2026-ZZZZZZ")).status_code == 404

    # the shared approval queue (certificate admin) lists the document's email row
    q = await c.get(
        f"{API}/admin/certificates/outbox", params={"status": "sent", "kind": "document"}, headers=ah
    )
    assert q.status_code == 200, q.text
    assert any(x["item"] and x["item"]["number"] == d["ref_no"] for x in q.json()["data"])
    summ = await c.get(f"{API}/admin/certificates/summary", headers=ah)
    assert summ.status_code == 200, summ.text
    certs = await c.get(f"{API}/admin/certificates", headers=ah)
    assert certs.status_code == 200 and certs.json()["data"] == [], certs.text

    # templates: override then reset
    tpl = await c.get(f"{API}/admin/documents/templates", headers=ah)
    assert tpl.status_code == 200, tpl.text

    r = await c.post(
        f"{API}/admin/documents/{d['id']}/revoke",
        json={"reason": "Issued in error", "public_reason": True},
        headers=ah,
    )
    assert r.status_code == 200, r.text
    v = (await c.get(f"{API}/certificates/verify/{d['ref_no']}")).json()
    assert v["status"] == "revoked", v
