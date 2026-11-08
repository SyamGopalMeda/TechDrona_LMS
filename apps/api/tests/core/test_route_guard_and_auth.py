"""CI route guard (api-specification §1.4) and auth dependency behaviour."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, FastAPI

from app.core.routing import authenticated_router, find_route_guard_violations, public_router
from app.core.time import utcnow
from tests.conftest import SERVICE_TOKEN


def test_all_application_routes_are_guarded(app) -> None:
    """Fails if any authenticated route lacks require_active_principal, a route tag or an
    idle effect. Public routes must be explicitly tagged ``public``."""
    assert find_route_guard_violations(app) == []


def test_guard_detects_untagged_and_unguarded_routes() -> None:
    bad = FastAPI()
    plain = APIRouter()

    @plain.get("/untagged")
    async def untagged() -> None: ...

    @plain.get("/unguarded", openapi_extra={"x-td-route-tag": "default", "x-td-idle": "extends"})
    async def unguarded() -> None: ...

    ok_pub = public_router()

    @ok_pub.get("/pub")
    async def pub() -> None: ...

    ok_auth = authenticated_router()

    @ok_auth.get("/authed")
    async def authed() -> None: ...

    bad.include_router(plain, prefix="/api/v1")
    bad.include_router(ok_pub, prefix="/api/v1")
    bad.include_router(ok_auth, prefix="/api/v1")
    problems = find_route_guard_violations(bad)
    assert any("/api/v1/untagged" in p and "missing x-td-route-tag" in p for p in problems)
    assert any("/api/v1/unguarded" in p and "lacks require_active_principal" in p for p in problems)
    assert not any("/pub" in p or "/authed" in p for p in problems)


def test_router_factory_rejects_unknown_tags() -> None:
    import pytest

    with pytest.raises(ValueError):
        authenticated_router(route_tag="appeal")
    with pytest.raises(ValueError):
        authenticated_router(route_tag="public")
    r = authenticated_router()
    with pytest.raises(ValueError):

        @r.get("/x", openapi_extra={"x-td-idle": "sometimes"})
        async def x() -> None: ...


async def test_no_resolver_registered_is_401(probe_client) -> None:
    from app.core import auth as core_auth

    prev = core_auth.get_session_resolver()
    core_auth.register_session_resolver(None)
    try:
        r = await probe_client.get(
            "/api/v1/_probe/me",
            headers={"Authorization": f"Service {SERVICE_TOKEN}", "X-TD-Session": "x" * 43},
        )
    finally:
        core_auth.register_session_resolver(prev)
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"


async def test_session_header_ignored_without_service_token(probe_client, auth, make_principal) -> None:
    headers = auth.login(make_principal())
    r = await probe_client.get("/api/v1/_probe/me", headers={"X-TD-Session": headers["X-TD-Session"]})
    assert r.status_code == 401
    r = await probe_client.get(
        "/api/v1/_probe/me", headers={**headers, "Authorization": "Service wrong-token"}
    )
    assert r.status_code == 401


async def test_active_principal_ok_and_no_store(probe_client, auth, make_principal) -> None:
    p = make_principal()
    r = await probe_client.get("/api/v1/_probe/me", headers=auth.login(p))
    assert r.status_code == 200
    assert r.json() == {"user_id": str(p.user_id)}
    assert r.headers["cache-control"] == "no-store"


async def test_restricted_scope_gate(probe_client, auth, make_principal) -> None:
    p = make_principal(scope="status_only", restriction_level=4)
    h = auth.login(p)
    r = await probe_client.get("/api/v1/_probe/me", headers=h)
    assert r.status_code == 403 and r.json()["code"] == "account_restricted"
    r = await probe_client.get("/api/v1/_probe/status", headers=h)  # account_status allowed
    assert r.status_code == 200 and r.json() == {"scope": "status_only"}


async def test_permission_denied_by_default(probe_client, auth, make_principal) -> None:
    p = make_principal()
    h = auth.login(p)
    r = await probe_client.get("/api/v1/_probe/perm", headers=h)
    assert r.status_code == 403
    assert r.json()["code"] == "permission_denied" and r.json()["permission"] == "probe.read"
    auth.grant(p, "probe.read")
    assert (await probe_client.get("/api/v1/_probe/perm", headers=h)).status_code == 200


async def test_step_up_required(probe_client, auth, make_principal) -> None:
    stale = make_principal(tier="privileged", last_step_up_at=utcnow() - timedelta(minutes=6))
    r = await probe_client.post("/api/v1/_probe/stepup", headers=auth.login(stale))
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "step_up_required"
    assert body["step_up"]["max_age_seconds"] == 300
    assert body["step_up"]["allowed_methods"] == ["totp"]  # SEC-11: passkeys not offered
    fresh = make_principal(tier="privileged", last_step_up_at=utcnow() - timedelta(minutes=1))
    assert (await probe_client.post("/api/v1/_probe/stepup", headers=auth.login(fresh))).status_code == 200
