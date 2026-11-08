"""Dev/demo seed and the route-guard CI check with the security/admin routers mounted."""

from __future__ import annotations

from app.core.routing import ROUTE_TAG_KEY, find_route_guard_violations, iter_api_routes


async def test_security_demo_seed_is_idempotent(db) -> None:
    from app.seeds import dev_users, security_demo

    await dev_users.seed(db)
    refs = await security_demo.seed(db)
    assert set(refs) == {f.email for f in security_demo.FIXTURES}
    assert all(ref.startswith("SEC-") for ref in refs.values())
    assert await security_demo.seed(db) == {}


def test_route_guard_green_and_security_routes_tagged(app) -> None:
    assert find_route_guard_violations(app) == []
    tags = {path: (r.openapi_extra or {}).get(ROUTE_TAG_KEY) for r, path in iter_api_routes(app)}
    assert tags["/api/v1/me/security/status"] == "account_status"
    assert tags["/api/v1/security/unblock-requests"] == "account_status"
    assert tags["/api/v1/auth/reverify/complete"] == "account_status"
    assert tags["/api/v1/security/cases"] == "default"
    assert tags["/api/v1/me/privacy-requests"] == "account_status"
