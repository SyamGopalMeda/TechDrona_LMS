"""mentoring over HTTP through the real FastAPI app on Firestore, **no Postgres** (data-learning
agent). Session: the harness ``FirebaseSession`` (falsy like ``NO_POSTGRES``; any SQL fails the
test). Entitlements are on Firestore too (the package quota is consumed and credited there).
Run with ``TD_TEST_NO_PG=1 TD_TEST_DB_NAME=learning_test``."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest

from tests.learning.fs.harness import FirebaseSession, client_for, close_app, login, open_app

API = "/api/v1"
STORES = (
    "mentoring",
    "entitlements",
    "core",
    "ai",
    "identity",
    "orgs",
    "admin",
    "notifications",
    "rbac",
    "placement",
    "learning",
    "catalog",
)
STUBBED = (
    "app.modules.mentoring.service",
    "app.modules.mentoring.service_fs",
    "app.modules.entitlements.service",
)


@pytest.fixture
async def web(
    fs_client: Any, monkeypatch: pytest.MonkeyPatch, auth: Any
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, list[tuple[str, Any]]]]:
    app, calls = await open_app(
        fs_client, monkeypatch, stores=STORES, stubbed=STUBBED, session_cls=FirebaseSession
    )
    try:
        async with client_for(app) as c:
            yield c, auth, calls
    finally:
        close_app(app, monkeypatch, STORES)


async def _package(
    monkeypatch: pytest.MonkeyPatch, fs_client: Any, user_id: uuid.UUID, *, sessions: int, reviews: int
) -> uuid.UUID:
    """A placement-package entitlement written through the entitlements backfill mapper."""
    from app.core.firestore import backfill as bf
    from app.core.time import utcnow
    from app.modules.entitlements.models import Entitlement
    from tests.learning.test_fs_data_path import synthetic

    eid = uuid.uuid4()
    now = utcnow()
    given = {
        "id": eid,
        "user_id": user_id,
        "feature_key": "placement_package",
        "source_type": "admin_grant",
        "granted_by": user_id,
        "status": "active",
        "starts_at": now - timedelta(days=1),
        "ends_at": now + timedelta(days=30),
        "mentor_sessions_remaining": sessions,
        "resume_reviews_remaining": reviews,
    }
    row = synthetic(Entitlement, **given)
    for col in Entitlement.__table__.columns:  # optional columns stay empty
        if col.nullable and col.name not in given:
            row[col.name] = None
    from app.core.firestore.store import ScopedStore

    m = next(
        x for x in bf.mappings("entitlements") if x.collection == "entitlements" and x.table == "entitlements"
    )
    await ScopedStore.system("test.factory", client=fs_client).import_documents(
        m.collection, [(m.doc_id(row), m.transform(row))]
    )
    return eid


async def _remaining(eid: uuid.UUID) -> int:
    from app.modules.entitlements import service as ent

    e = await ent.get_entitlement(None, eid)  # type: ignore[arg-type]
    assert e is not None
    return int(e.mentor_sessions_remaining or 0)


async def test_slots_book_reschedule_cancel_feedback(
    web: Any, make_principal: Any, monkeypatch: pytest.MonkeyPatch, fs_client: Any
) -> None:
    from app.core.time import utcnow

    c, auth, _calls = web
    _mentor, mh = login(
        auth,
        make_principal,
        "mentor.slot.manage",
        "mentor.feedback.write",
        "mentor.notes.read",
        is_platform=True,
    )
    stu, sh = login(auth, make_principal)
    other, oh = login(auth, make_principal)
    eid = await _package(monkeypatch, fs_client, stu.user_id, sessions=2, reviews=1)
    await _package(monkeypatch, fs_client, other.user_id, sessions=1, reviews=0)

    now = utcnow()
    starts = [now + timedelta(hours=h) for h in (48, 72, 96)]
    r = await c.post(
        f"{API}/mentor/slots",
        json={"slots": [{"starts_at": s.isoformat(), "duration_minutes": 60} for s in starts]},
        headers={**mh, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201, r.text
    slot_ids = [s["id"] for s in r.json()["data"]]
    dup = await c.post(
        f"{API}/mentor/slots",
        json={
            "slots": [{"starts_at": (starts[0] + timedelta(minutes=30)).isoformat(), "duration_minutes": 60}]
        },
        headers={**mh, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert dup.status_code == 409 and dup.json()["code"] == "slot_overlap", dup.text

    open_ = await c.get(f"{API}/mentoring/slots", headers=sh)
    assert open_.status_code == 200, open_.text
    assert [s["id"] for s in open_.json()["data"]] == slot_ids
    assert open_.json()["quota"]["mentor_sessions_remaining"] == 2

    r = await c.post(
        f"{API}/mentoring/bookings",
        json={"slot_id": slot_ids[0]},
        headers={**sh, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code in (200, 201), r.text
    bid = r.json()["id"]
    assert await _remaining(eid) == 1
    taken = await c.post(
        f"{API}/mentoring/bookings",
        json={"slot_id": slot_ids[0]},
        headers={**oh, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert taken.status_code == 409 and taken.json()["code"] == "slot_unavailable", (
        taken.text
    )  # no double booking

    r = await c.post(f"{API}/mentoring/bookings/{bid}/reschedule", json={"slot_id": slot_ids[1]}, headers=sh)
    assert r.status_code == 200 and r.json()["status"] == "rescheduled", r.text
    assert await _remaining(eid) == 1  # > 12 h ahead: the credit is kept
    r = await c.post(
        f"{API}/mentoring/bookings",
        json={"slot_id": slot_ids[0]},
        headers={**oh, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code in (200, 201), r.text  # the old slot is open again

    mine = (await c.get(f"{API}/me/mentoring/bookings", headers=sh)).json()["data"]
    assert [b["id"] for b in mine] == [bid] and mine[0]["slot_id"] == slot_ids[1]
    sessions = await c.get(f"{API}/mentor/sessions", params={"view": "upcoming"}, headers=mh)
    assert sessions.status_code == 200 and sessions.json()["counts"]["upcoming"] == 2, sessions.text

    r = await c.post(f"{API}/mentoring/bookings/{bid}/cancel", headers=sh)
    assert r.status_code == 200 and r.json()["status"] == "cancelled_by_student", r.text
    assert r.json()["credit_restored"] is True and await _remaining(eid) == 2

    mslots = (await c.get(f"{API}/mentor/slots", headers=mh)).json()["data"]
    assert {s["id"]: s["status"] for s in mslots}[slot_ids[1]] == "open"
    r = await c.delete(f"{API}/mentor/slots/{slot_ids[2]}", headers=mh)
    assert r.status_code == 200 and r.json()["slot"]["status"] == "cancelled", r.text


async def test_resumes_and_review(
    web: Any, make_principal: Any, monkeypatch: pytest.MonkeyPatch, fs_client: Any
) -> None:
    c, auth, _calls = web
    stu, sh = login(auth, make_principal)
    _, rh = login(auth, make_principal, "mentor.feedback.write", is_platform=True)
    await _package(monkeypatch, fs_client, stu.user_id, sessions=0, reviews=1)
    body = {"template_key": "ats_classic", "content": {"headline": "Backend developer", "skills": ["python"]}}
    r = await c.post(f"{API}/me/resumes", json=body, headers=sh)
    assert r.status_code in (200, 201), r.text
    rid = r.json()["id"]
    assert r.json()["version_no"] == 1
    r2 = await c.post(f"{API}/me/resumes", json=body, headers=sh)
    assert r2.json()["version_no"] == 2
    listed = (await c.get(f"{API}/me/resumes", headers=sh)).json()["data"]
    assert [x["version_no"] for x in listed] == [2, 1] and [x["is_current"] for x in listed] == [True, False]

    r = await c.post(
        f"{API}/me/resumes/{rid}/review-requests",
        json={"note": "please"},
        headers={**sh, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code in (200, 201), r.text
    rev_id = r.json()["id"]
    again = await c.post(
        f"{API}/me/resumes/{rid}/review-requests",
        json={},
        headers={**sh, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert again.status_code == 409, again.text
    queue = (await c.get(f"{API}/mentor/resume-reviews", headers=rh)).json()["data"]
    assert [q["id"] for q in queue] == [rev_id]
    r = await c.post(
        f"{API}/mentor/resume-reviews/{rev_id}/feedback",
        json={"summary": "Solid start", "comments": [{"section": "skills", "comment": "Add projects"}]},
        headers=rh,
    )
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    mine = (await c.get(f"{API}/me/resumes", headers=sh)).json()["data"]
    assert mine[1]["reviews"][0]["summary"] == "Solid start"
