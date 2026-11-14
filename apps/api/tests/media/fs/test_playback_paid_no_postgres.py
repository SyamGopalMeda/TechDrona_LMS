"""Regression (migration parity): playback of a PAID lesson over HTTP on the all-Firestore stack
with the no-Postgres request session (``install_fake_db``: ``get_principal_db`` yields
``NO_POSTGRES``, exactly what the Firebase stack yields).

Before the fix the media routes handed ``NO_POSTGRES`` to the entitlement check, which reaches
commerce's SQL-on-Firestore engine: MED-04/MED-05 answered 500 for every paid, non-preview lesson,
and the admin playback policies were silently replaced by their defaults (the policy lookup's
``begin_nested`` raised and was swallowed). The VM (Postgres session) does neither.

Real modules on the emulator: media, catalog, learning, entitlements, commerce, admin (policies),
analytics (coverage lookup). Stubbed: audit/outbox recorders and the identity/device lookups of
the watermark and conflict label (``stub_core`` + media adapters).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest

from tests.paths.fs.http_harness import install_fake_db, restore_switch, stub_core, switch_to_firestore

API = "/api/v1"
MODULES = ("media", "catalog", "learning", "entitlements", "commerce", "admin", "analytics")


async def _seed(*, entitled: bool) -> dict[str, Any]:
    from app.core.db import NO_POSTGRES
    from app.core.firestore.store import ScopedStore
    from app.core.ids import uuid7
    from app.core.time import utcnow
    from app.modules.catalog import api as catalog_api
    from app.modules.catalog.store_specs import ASSETS, COURSES, LESSONS, VERSIONS
    from app.modules.entitlements import service as ent
    from app.modules.learning import service as learning

    now = utcnow()
    staff, user = uuid7(), uuid7()
    course_id, version_id, lesson_id, asset_id, module_id = (uuid7() for _ in range(5))
    s = ScopedStore.system("firestore.backfill")
    base = {"organization_id": None, "created_at": now, "updated_at": now}
    docs = {
        COURSES: {
            "id": str(course_id),
            "slug": f"paid-{course_id.hex[:8]}",
            "title": "Paid",
            "course_kind": "course",
            "visibility": "public",
            "status": "published",
            "is_free": False,
            "current_version_id": str(version_id),
            "completeness_pct": "0",
            "created_by": str(staff),
            "deleted_at": None,
        },
        VERSIONS: {
            "id": str(version_id),
            "course_id": str(course_id),
            "version_no": 1,
            "title": "Paid",
            "outcomes": [],
            "language": "en",
            "tags": [],
            "status": "published",
            "created_by": str(staff),
            "published_at": now,
            "outline": [],
            "lesson_count": 1,
            "duration_seconds": 600,
        },
        LESSONS: {
            "id": str(lesson_id),
            "course_module_id": str(module_id),
            "course_version_id": str(version_id),
            "course_id": str(course_id),
            "lesson_key": str(lesson_id),
            "title": "Video",
            "lesson_type": "video",
            "position": 1,
            "is_required": True,
            "is_free_preview": False,
            "duration_seconds": 600,
            "topics": [],
        },
        ASSETS: {
            "id": str(asset_id),
            "lesson_id": str(lesson_id),
            "asset_type": "video",
            "provider": "vdocipher",
            "provider_asset_id": "vdo-paid-1",
            "duration_seconds": 600,
            "status": "available",
            "scan_status": "not_required",
            "position": 1,
        },
    }
    for coll, d in docs.items():
        await s.import_documents(coll, [(str(d["id"]), {**base, **d})])
    if entitled:
        values = {
            "id": uuid7(),
            "user_id": user,
            "organization_id": None,
            "product_id": None,
            "course_id": course_id,
            "feature_key": None,
            "source_type": "admin_grant",
            "order_item_id": None,
            "subscription_id": None,
            "coupon_redemption_id": None,
            "granted_by": staff,
            "grant_reason": "test",
            "status": "active",
            "starts_at": now - timedelta(days=1),
            "ends_at": None,
            "grace_ends_at": None,
        }
        ev = ent._event_fields("granted", ent.Actor("system"), to_status="active", delta={}, reason="test")
        await ent._repo().grant(values, ev)
        course = (await catalog_api.get_courses(NO_POSTGRES, [course_id]))[course_id]
        await learning.create_enrolment(NO_POSTGRES, user_id=user, course=course, source="purchase")
        await learning.fss.flush(NO_POSTGRES)
    return {"user": user, "asset": asset_id, "staff": staff}


async def _set_policy(key: str, value: int, staff: uuid.UUID) -> None:
    from app.core.time import utcnow
    from app.modules.admin.repo_firestore import system_repo

    now = utcnow()
    await system_repo("test.policy").write_version(
        {
            "setting_key": key,
            "scope_type": "platform",
            "scope_id": None,
            "value": value,
            "value_schema": {"type": "integer"},
            "min_value": None,
            "max_value": None,
            "plan_overridable": False,
            "locked": False,
            "effective_from": now - timedelta(minutes=1),
            "expires_at": None,
            "case_decision_id": None,
            "change_reason": "test",
            "changed_by": str(staff),
            "approved_by": None,
            "approval_request_id": None,
            "created_at": now,
        }
    )


@pytest.fixture
async def web(fs_client: Any, monkeypatch: pytest.MonkeyPatch, auth: Any) -> AsyncIterator[Any]:
    from app.main import create_app
    from app.modules.media import adapters

    calls: list[tuple[str, Any]] = []
    stub_core(monkeypatch, calls)

    async def contact(session: Any, user_id: uuid.UUID) -> Any:
        return ("asha@example.test", "+919876543210", "Asha K")

    async def device(session: Any, device_id: uuid.UUID) -> Any:
        return ("Chrome", "Windows")

    monkeypatch.setattr(adapters, "watermark_contact", contact)
    monkeypatch.setattr(adapters, "device_families", device)
    await switch_to_firestore(fs_client, monkeypatch, *MODULES)
    app = create_app()
    install_fake_db(app)  # request sessions are NO_POSTGRES, as on the Firebase stack
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c, auth
    finally:
        restore_switch(monkeypatch, *MODULES)


async def test_paid_lesson_token_heartbeat_stop_and_admin_policy(web: Any, make_principal: Any) -> None:
    c, auth = web
    w = await _seed(entitled=True)
    await _set_policy("playback.heartbeat_seconds", 45, w["staff"])
    h = auth.login(make_principal(user_id=w["user"], device_id=uuid.uuid4(), is_minor=False))

    r = await c.post(f"{API}/media/playback-tokens", json={"lesson_asset_id": str(w["asset"])}, headers=h)
    assert r.status_code == 201, r.text
    tok = r.json()
    # the admin policy is honoured (was silently the default 30 on the no-Postgres session)
    assert tok["heartbeat_interval_seconds"] == 45
    ps = tok["playback_session_id"]
    r = await c.post(
        f"{API}/media/playback-sessions/{ps}/heartbeat", json={"position_seconds": 20}, headers=h
    )
    assert r.status_code == 200 and r.json()["state"] == "active", r.text
    r = await c.post(f"{API}/media/playback-sessions/{ps}/stop", headers=h)
    assert r.status_code == 200 and r.json()["state"] == "ended", r.text


async def test_paid_lesson_without_entitlement_is_403_not_500(web: Any, make_principal: Any) -> None:
    c, auth = web
    w = await _seed(entitled=False)
    h = auth.login(make_principal(user_id=w["user"], device_id=uuid.uuid4(), is_minor=False))
    r = await c.post(f"{API}/media/playback-tokens", json={"lesson_asset_id": str(w["asset"])}, headers=h)
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required", r.text


async def test_entitled_resource_download_on_the_no_postgres_session(web: Any, make_principal: Any) -> None:
    """MED-07 of an ``entitled`` resource of a paid course: the entitlement check (commerce engine)
    works on the request session; the answer is a presigned URL (no 500)."""
    from app.core.firestore.store import ScopedStore
    from app.core.ids import uuid7
    from app.core.time import utcnow
    from app.modules.catalog.store_specs import RESOURCES

    c, auth = web
    w = await _seed(entitled=True)
    course_id = None
    from app.modules.entitlements import service as ent

    for e in await ent._repo().for_user(w["user"]):
        course_id = e.course_id
    assert course_id is not None
    rid, now = uuid7(), utcnow()
    await ScopedStore.system("firestore.backfill").import_documents(
        RESOURCES,
        [
            (
                str(rid),
                {
                    "id": str(rid),
                    "organization_id": None,
                    "course_id": str(course_id),
                    "lesson_id": None,
                    "company_id": None,
                    "title": "Notes",
                    "resource_type": "pdf",
                    "access_level": "entitled",
                    "s3_key": f"content/resource_file/{rid}/notes.pdf",
                    "url": None,
                    "is_public": False,
                    "created_by": str(w["staff"]),
                    "created_at": now,
                    "updated_at": now,
                },
            )
        ],
    )
    h = auth.login(make_principal(user_id=w["user"], device_id=uuid.uuid4(), is_minor=False))
    r = await c.post(f"{API}/media/downloads", json={"resource_id": str(rid)}, headers=h)
    assert r.status_code == 200, r.text
    assert "notes.pdf" in r.json()["url"] and r.json()["expires_at"]
    other = auth.login(make_principal(user_id=uuid7(), device_id=uuid.uuid4(), is_minor=False))
    r = await c.post(f"{API}/media/downloads", json={"resource_id": str(rid)}, headers=other)
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required", r.text
