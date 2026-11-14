"""orgs over HTTP on Firestore with no Postgres: batches, members, plan, schedule, classes,
attendance, the learner's own views, and the website plan importer (emulator only).

Sessions are minted directly in the sessions store (``_signed_in``), so these tests do not
depend on the login route.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pyotp

import app.modules.orgs.store_specs
import app.modules.rbac.store_specs
import app.modules.sessions.store_specs  # noqa: F401  (register the collections)
from app.core.company import COMPANY_ORG_ID
from app.core.ids import uuid7
from app.core.security import generate_token, hash_token
from app.core.time import ist_date, utcnow
from app.modules.identity import clock
from tests.identity.fs.conftest import fs_user, seed_catalogue


async def _signed_in(http: Any, user: Any, tier: str) -> None:
    """Mint an active session for ``user`` and point the browser at it."""
    from app.modules.sessions.models import AuthSession
    from app.modules.sessions.repo_firestore import system_repo

    now = clock.now()
    token = generate_token()
    await system_repo().add_session(
        AuthSession(
            id=uuid7(),
            token_hash=hash_token(token),
            user_id=user.id,
            client_type="web",
            session_tier=tier,
            scope="full",
            status="active",
            aal=2,
            amr=["pwd", "otp"],
            created_via="password",
            auth_time=now,
            last_step_up_at=now,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(hours=8),
        )
    )
    http.session = token


async def _admin(http: Any) -> Any:
    u = await fs_user(
        f"admin{uuid7().hex[-6:]}@x.in", roles=("super_admin",), totp_secret=pyotp.random_base32()
    )
    await _signed_in(http, u, "privileged")
    return u


async def _batch_grant(user_id: uuid.UUID, role_key: str, batch_id: uuid.UUID) -> None:
    from app.modules.rbac.models import RoleGrant
    from app.modules.rbac.repo_firestore import system_repo as rrepo

    await seed_catalogue()
    role = await rrepo().role_by_key(role_key)
    assert role is not None
    await rrepo().create_grant(
        RoleGrant(
            id=uuid7(),
            user_id=user_id,
            role_id=role.id,
            scope_type="batch",
            scope_id=batch_id,
            organization_id=COMPANY_ORG_ID,
            granted_by=uuid7(),
            granted_at=clock.now(),
        ),
        role_key,
    )


PLAN = {
    "total_hours": 8,
    "daily_hours": 2,
    "working_days": [1, 2, 3, 4, 5],
    "class_time": "10:00",
    "meet_url": "https://meet.example.com/abc",
    "weeks": [{"title": "Basics", "topics": ["intro"]}],
}


async def test_batches_members_and_permissions(http: Any) -> None:
    await _admin(http)
    r = await http.post("/batches", {"name": "Batch A", "code": "A-1"})
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    assert r.json()["status"] == "active"
    dup = await http.post("/batches", {"name": "Batch A again", "code": "A-1"})
    assert dup.status_code == 409, dup.text
    assert (await http.get(f"/batches/{bid}")).json()["code"] == "A-1"
    r = await http.patch(f"/batches/{bid}", {"name": "Batch A (2026)"})
    assert r.status_code == 200 and r.json()["name"] == "Batch A (2026)", r.text
    listing = await http.get("/batches")
    assert listing.status_code == 200 and [b["id"] for b in listing.json()["data"]] == [bid]

    s1 = await fs_user("s1@x.in", full_name="Asha")
    s2 = await fs_user("s2@x.in", full_name="Bala")
    r = await http.post(f"/batches/{bid}/members", {"user_ids": [str(s1.id)], "emails": ["s2@x.in"]})
    assert r.status_code == 200, r.text
    again = await http.post(f"/batches/{bid}/members", {"user_ids": [str(s1.id)]})
    assert again.status_code in (200, 409), again.text  # already a member: no second live row
    members = await http.get(f"/batches/{bid}/members")
    assert members.status_code == 200, members.text
    names = sorted(m.get("full_name") for m in members.json()["data"])
    assert names == ["Asha", "Bala"], members.json()
    from app.modules.orgs.public import batch_members, org_memberships

    assert len(await batch_members(None, batch_ids=[uuid.UUID(bid)], user_ids=[s1.id])) == 1  # type: ignore[arg-type]
    assert [m.member_type for m in await org_memberships(None, user_ids=[s1.id])] == ["student"]  # type: ignore[arg-type]

    r = await http.delete(f"/batches/{bid}/members/{s2.id}")
    assert r.status_code == 200, r.text
    assert await org_memberships(None, user_ids=[s2.id]) == []  # type: ignore[arg-type]  # last batch left
    # re-adding after removal works (the ux_bm_live slot was freed)
    r = await http.post(f"/batches/{bid}/members", {"user_ids": [str(s2.id)]})
    assert r.status_code == 200, r.text

    # a student cannot read staff routes of the batch
    await _signed_in(http, s1, "student")
    denied = await http.get(f"/batches/{bid}/members")
    assert denied.status_code in (403, 404), denied.text
    assert (await http.get("/batches")).status_code == 403

    await _admin(http)
    r = await http.post(f"/batches/{bid}/archive")
    assert r.status_code == 200 and r.json()["status"] == "archived", r.text
    blocked = await http.patch(f"/batches/{bid}", {"name": "x"})
    assert blocked.status_code == 409, blocked.text


async def test_plan_classes_attendance_and_learner_views(http: Any) -> None:
    await _admin(http)
    today = ist_date(utcnow())
    start = today - timedelta(days=14)
    r = await http.post("/batches", {"name": "Batch B", "code": "B-1", "starts_on": start.isoformat()})
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    learner = await fs_user("learner@x.in", full_name="Chitra")
    trainer = await fs_user("trainer@x.in", full_name="Dev", totp_secret=pyotp.random_base32())
    assert (await http.post(f"/batches/{bid}/members", {"user_ids": [str(learner.id)]})).status_code == 200

    # plan: empty, preview, put, schedule
    r = await http.get(f"/batches/{bid}/plan")
    assert r.status_code == 200 and r.json()["has_plan"] is False, r.text
    r = await http.post(f"/batches/{bid}/plan/preview", {"plan": PLAN, "starts_on": start.isoformat()})
    assert r.status_code == 200 and r.json()["weeks_count"] == 1, r.text
    r = await http.request("PUT", f"/batches/{bid}/plan", json={"plan": PLAN, "min_attendance_percent": 75})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_plan"] is True and body["min_attendance_percent"] == 75
    assert body["batch"]["ends_on"] is not None  # sync_end_date moved the batch end date
    assert (await http.get(f"/batches/{bid}/schedule")).status_code == 200
    r = await http.request("PUT", f"/batches/{bid}/plan", json={"plan": {**PLAN, "class_time": "11:00"}})
    assert r.status_code == 200 and r.json()["plan"]["class_time"] == "11:00", r.text

    # classes: generate from the plan (4 working days of 2 h), then manual create/patch/delete
    r = await http.post(f"/batches/{bid}/sessions/generate", {})
    assert r.status_code == 200 and r.json()["created"] == 4, r.text
    r = await http.post(f"/batches/{bid}/sessions/generate", {})
    assert r.status_code == 200 and r.json()["created"] == 0, r.text  # idempotent
    listing = (await http.get(f"/batches/{bid}/sessions")).json()
    assert listing["students"] == 1 and len(listing["data"]) == 4
    first = listing["data"][0]
    dup = await http.post(f"/batches/{bid}/sessions", {"session_date": first["session_date"], "topic": "dup"})
    assert dup.status_code == 409, dup.text
    extra_day = (today - timedelta(days=1)).isoformat()
    existing = {d["session_date"] for d in listing["data"]}
    if extra_day in existing:
        extra_day = (today - timedelta(days=30)).isoformat()
    r = await http.post(f"/batches/{bid}/sessions", {"session_date": extra_day, "topic": "Extra"})
    assert r.status_code == 201, r.text
    extra = r.json()["id"]
    clash = await http.patch(f"/batches/{bid}/sessions/{extra}", {"session_date": first["session_date"]})
    assert clash.status_code == 409, clash.text
    r = await http.patch(f"/batches/{bid}/sessions/{extra}", {"topic": "Extra class"})
    assert r.status_code == 200 and r.json()["topic"] == "Extra class", r.text

    # a trainer granted on this batch marks attendance
    await _batch_grant(trainer.id, "trainer", uuid.UUID(bid))
    await _signed_in(http, trainer, "staff")
    r = await http.request(
        "PUT",
        f"/batches/{bid}/sessions/{extra}/attendance",
        json={"marks": [{"user_id": str(learner.id), "status": "P"}]},
    )
    assert r.status_code == 200 and r.json()["session"]["attendance"]["P"] == 1, r.text
    r = await http.request(
        "PUT",
        f"/batches/{bid}/sessions/{first['id']}/attendance",
        json={"marks": [{"user_id": str(learner.id), "status": "A"}]},
    )
    assert r.status_code == 200, r.text
    stranger = await http.request(
        "PUT",
        f"/batches/{bid}/sessions/{extra}/attendance",
        json={"marks": [{"user_id": str(uuid7()), "status": "P"}]},
    )
    assert stranger.status_code == 422, stranger.text
    sheet = await http.get(f"/batches/{bid}/sessions/{extra}/attendance")
    assert sheet.status_code == 200 and sheet.json()["data"][0]["status"] == "P", sheet.text
    has_marks = await http.delete(f"/batches/{bid}/sessions/{extra}")
    assert has_marks.status_code == 409, has_marks.text
    # clear the mark, then the class can be deleted
    r = await http.request(
        "PUT",
        f"/batches/{bid}/sessions/{extra}/attendance",
        json={"marks": [{"user_id": str(learner.id), "status": None}]},
    )
    assert r.status_code == 200 and r.json()["session"]["attendance"]["marked"] == 0, r.text
    assert (await http.delete(f"/batches/{bid}/sessions/{extra}")).json() == {"deleted": True}

    overview = await http.get(f"/batches/{bid}/attendance")
    assert overview.status_code == 200, overview.text
    ov = overview.json()
    assert ov["classes_marked"] == 1 and ov["min_attendance_percent"] == 75
    assert ov["data"][0]["below_minimum"] is True
    detail = await http.get(f"/batches/{bid}/attendance/{learner.id}")
    assert detail.status_code == 200 and len(detail.json()["sessions"]) == 4, detail.text

    # the trainer of batch B cannot see another batch
    await _admin(http)
    other = (await http.post("/batches", {"name": "Other", "code": "O-1"})).json()["id"]
    await _signed_in(http, trainer, "staff")
    assert (await http.get(f"/batches/{other}/plan")).status_code in (403, 404)
    assert (
        await http.request("PUT", f"/batches/{bid}/plan", json={"plan": PLAN})
    ).status_code == 403  # Admin only

    # the learner's own views
    await _signed_in(http, learner, "student")
    mine = await http.get("/me/classes")
    assert mine.status_code == 200, mine.text
    mb = mine.json()["batches"]
    assert [b["batch"]["id"] for b in mb] == [bid]
    assert all("notes" not in c for c in mb[0]["recent"] + mb[0]["upcoming"])
    att = await http.get("/me/attendance")
    assert att.status_code == 200 and att.json()["batches"][0]["summary"]["absent"] == 1, att.text


def _web_doc(doc_id: str, title: str, slug: str, start: str) -> dict[str, Any]:
    return {
        "name": f"projects/p/databases/(default)/documents/web_courses/{doc_id}",
        "fields": {
            "title": {"stringValue": title},
            "site_slug": {"stringValue": slug},
            "start_date": {"stringValue": start},
            "status": {"stringValue": "running"},
            "hours": {"integerValue": "10"},
            "daily_hours": {"integerValue": "2"},
            "attendance_min": {"integerValue": "80"},
            "created_by": {"stringValue": "importer@x.in"},
            "weeks": {
                "arrayValue": {"values": [{"mapValue": {"fields": {"title": {"stringValue": "Week 1"}}}}]}
            },
        },
    }


async def test_import_website_plans(fs: Any, monkeypatch: Any) -> None:
    from app.core.config import reset_settings_cache
    from app.core.firestore.backend import reset_store_backends
    from app.modules.orgs import import_website_plans as imp
    from app.modules.orgs.public import list_batches
    from app.modules.orgs.repo_firestore import system_repo

    for m in ("audit", "catalog"):
        monkeypatch.setenv(f"TD_STORE_{m.upper()}", "firestore")
    reset_settings_cache()
    reset_store_backends()

    async def _no_course(_s: Any, _slug: str | None) -> None:
        return None

    monkeypatch.setattr(imp, "_course_for_slug", _no_course)  # catalog lookup belongs to catalog
    await fs_user("importer@x.in")
    docs = [
        _web_doc("abcd1234", "Java Full Stack", "java-full-stack", "2026-11-02"),
        _web_doc("efgh5678", "Python", "python", ""),
    ]
    mapped = [imp.map_document(d["name"].rsplit("/", 1)[1], imp.decode_fields(d["fields"])) for d in docs]
    dry = await imp.import_plans(None, mapped, apply=False)
    assert [r["action"] for r in dry] == ["create", "create"]
    assert await list_batches(None) == []  # type: ignore[arg-type]  # dry run wrote nothing
    rep = await imp.import_plans(None, mapped, apply=True)
    assert [r["action"] for r in rep] == ["create", "create"]
    batches = {b.code: b for b in await list_batches(None)}  # type: ignore[arg-type]
    assert set(batches) == {"web-java-full-stack", "web-python"}
    plan = await system_repo().plan_by_source_ref("web_courses/abcd1234")
    assert plan is not None and plan.min_attendance_percent == 80
    assert plan.batch_id == batches["web-java-full-stack"].id
    again = await imp.import_plans(None, mapped, apply=True)
    assert [r["action"] for r in again] == ["unchanged", "unchanged"]
    changed = [imp.map_document("abcd1234", {**imp.decode_fields(docs[0]["fields"]), "title": "Java FS"})]
    upd = await imp.import_plans(None, changed, apply=True)
    assert upd[0]["action"] == "update" and upd[0]["changes"] == ["name"]
    assert (await system_repo().get_batch(batches["web-java-full-stack"].id)).name == "Java FS"  # type: ignore[union-attr]
    # a website code clash gets a suffixed code
    clash = [imp.map_document("zzzz9999", imp.decode_fields(docs[1]["fields"]))]
    assert (await imp.import_plans(None, clash, apply=True))[0]["code"].startswith("web-python-")
