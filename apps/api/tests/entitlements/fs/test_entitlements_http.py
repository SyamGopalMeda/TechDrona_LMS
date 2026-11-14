"""Entitlement endpoints over HTTP on Firestore (``TD_STORE_ENTITLEMENTS=firestore``), no Postgres.

ENT-01/02 access checks, ENT-03 own list, ENT-04 staff view, ENT-05 history, through the real
FastAPI app. Request sessions are ``NO_POSTGRES``: any Postgres use fails the test.
Commerce's product tables (``covering_scope``) and its Redis rate limiter are stubbed at the
module boundary.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest

from app.core.time import utcnow
from tests.paths.fs.http_harness import install_fake_db, stub_core

API = "/api/v1"


@pytest.fixture
async def web(
    fs_env: Any, monkeypatch: pytest.MonkeyPatch, auth: Any
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    from app.main import create_app
    from app.modules.commerce import ratelimit
    from app.modules.entitlements import service as svc

    stub_core(monkeypatch, [])

    async def no_limit(key: str, rules: Any) -> None:
        return None

    monkeypatch.setattr(ratelimit, "hit", no_limit)
    course = uuid.UUID(int=7)

    async def scope(session: Any, rtype: str, rid: uuid.UUID) -> Any:
        return set(), {course}, set()

    monkeypatch.setattr(svc, "covering_scope", scope)
    app = create_app()
    install_fake_db(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, auth


async def test_entitlement_endpoints(web: Any, make_principal: Any) -> None:
    from app.modules.entitlements import service as svc

    c, auth = web
    course = uuid.UUID(int=7)
    learner = make_principal()
    lh = auth.login(learner)
    check = {"resource": {"kind": "course", "id": str(course)}}
    r = await c.post(f"{API}/entitlements/check", json=check, headers=lh)
    assert r.status_code == 200, r.text
    assert (r.json()["allowed"], r.json()["reason_code"]) == (False, "NO_ENTITLEMENT")

    now = utcnow()
    e, _ = await svc.grant(
        None,
        svc.Actor.system("test"),
        user_id=learner.user_id,
        source_type="admin_grant",
        course_id=course,
        granted_by=learner.user_id,
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=30),
        reason="matrix grant",
    )
    r = await c.post(f"{API}/entitlements/check", json=check, headers=lh)
    body = r.json()
    assert (body["allowed"], body["reason_code"], body["entitlement_id"], body["status"]) == (
        True,
        "ENTITLED",
        str(e.id),
        "active",
    )
    r = await c.post(
        f"{API}/entitlements/check-batch",
        json={"resources": [check["resource"], {"kind": "course", "id": str(uuid.uuid4()), "is_free": True}]},
        headers=lh,
    )
    assert [x["allowed"] for x in r.json()["results"]] == [True, True]

    mine = (await c.get(f"{API}/me/entitlements", headers=lh)).json()
    assert [x["entitlement_id"] for x in mine["data"]] == [str(e.id)]
    assert mine["data"][0]["effective_status"] == "active" and mine["data"][0]["title"] == "Course access"
    other = make_principal()
    oh = auth.login(other)
    assert (await c.get(f"{API}/me/entitlements", headers=oh)).json()["data"] == []

    await svc.suspend(None, e, svc.Actor.system("test"), reason="payment")
    hist = (await c.get(f"{API}/entitlements/{e.id}/events", headers=lh)).json()["data"]
    assert [h["event_type"] for h in hist] == ["granted", "suspended"]
    assert (await c.get(f"{API}/entitlements/{e.id}/events", headers=oh)).status_code == 404  # no oracle
    r = await c.post(f"{API}/entitlements/check", json=check, headers=lh)
    assert r.json()["reason_code"] == "SUSPENDED_PAYMENT"

    staff = make_principal(is_platform=True)
    sh = auth.login(staff)
    assert (await c.get(f"{API}/users/{learner.user_id}/entitlements", headers=sh)).status_code == 403
    auth.grant(staff, "entitlement.read")
    r = await c.get(f"{API}/users/{learner.user_id}/entitlements", headers=sh)
    assert r.status_code == 200 and [x["status"] for x in r.json()["data"]] == ["suspended"]
    assert (await c.get(f"{API}/entitlements/{e.id}/events", headers=sh)).status_code == 200


@pytest.fixture
async def web_core(
    fs_env: Any, monkeypatch: pytest.MonkeyPatch, auth: Any
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    """Privileged writes: idempotency on Firestore (``TD_STORE_CORE``), request session ``None``
    (``core_store`` treats only ``None`` as "no Postgres", see http_harness.install_fake_db)."""
    from app.core.firestore.backend import reset_store_backends
    from app.main import create_app
    from app.modules.commerce import ratelimit

    stub_core(monkeypatch, [])

    async def no_limit(key: str, rules: Any) -> None:
        return None

    monkeypatch.setattr(ratelimit, "hit", no_limit)
    monkeypatch.setenv("TD_STORE_CORE", "firestore")
    reset_store_backends()
    app = create_app()
    install_fake_db(app, session=None)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c, auth
    finally:
        monkeypatch.delenv("TD_STORE_CORE", raising=False)
        reset_store_backends()


async def test_manual_grant_and_revoke(web_core: Any, make_principal: Any) -> None:
    c, auth = web_core
    learner = make_principal()
    admin = make_principal(is_platform=True, last_step_up_at=utcnow())
    auth.grant(admin, "entitlement.grant_manual")
    auth.grant(admin, "entitlement.revoke")
    ah = auth.login(admin)
    body = {
        "user_ids": [str(learner.user_id)],
        "target": {"feature_key": "all_courses"},
        "source_type": "admin_grant",
        "ends_at": (utcnow() + timedelta(days=30)).isoformat(),
        "reason": "Scholarship for the Nov batch",
    }
    key = {"Idempotency-Key": str(uuid.uuid4())}
    r = await c.post(f"{API}/entitlements/grants", json=body, headers={**ah, **key})
    assert r.status_code == 201, r.text
    assert r.json()["granted"] == 1
    eid = r.json()["entitlement_ids"][0]
    replay = await c.post(f"{API}/entitlements/grants", json=body, headers={**ah, **key})
    assert replay.status_code == 201 and replay.json()["entitlement_ids"] == [eid]  # stored replay

    big = {**body, "ends_at": (utcnow() + timedelta(days=200)).isoformat()}  # > 90 days: dual control
    stale = make_principal(is_platform=True)  # no fresh step-up
    auth.grant(stale, "entitlement.grant_manual")
    r = await c.post(
        f"{API}/entitlements/grants",
        json=big,
        headers={**auth.login(stale), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 401 or r.json()["code"] == "step_up_required"

    rk = {"Idempotency-Key": str(uuid.uuid4())}
    r = await c.post(
        f"{API}/entitlements/{eid}/revoke",
        json={"reason_code": "admin", "note": "test"},
        headers={**ah, **rk},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "revoked" and r.json()["revoke_reason"] == "admin"
    rk = {"Idempotency-Key": str(uuid.uuid4())}
    r = await c.post(
        f"{API}/entitlements/{eid}/revoke",
        json={"reason_code": "admin", "note": "again"},
        headers={**ah, **rk},
    )
    assert r.status_code == 409 and r.json()["code"] == "invalid_state_transition"
    mine = (await c.get(f"{API}/me/entitlements", headers=auth.login(learner))).json()["data"]
    assert [(x["entitlement_id"], x["status"]) for x in mine] == [(eid, "revoked")]
