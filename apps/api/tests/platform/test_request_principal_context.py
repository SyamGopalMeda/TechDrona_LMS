"""R12: the caller's principal / RLS view is readable without a request or a Postgres session."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.core import auth as core_auth
from app.core.errors import install_error_handlers
from app.core.ids import uuid7
from app.core.middleware import RequestContextMiddleware, ServiceAuthMiddleware
from app.core.principal import Principal, RoleGrant
from app.core.request_context import ANONYMOUS, current_principal, current_rls_context

TOKEN = "t" * 48


class Resolver:
    def __init__(self, p: Principal) -> None:
        self.p = p

    async def resolve(self, request: Any, session_token: str, ctx: Any) -> Principal:
        return self.p


def helper_without_request() -> dict[str, Any]:
    """What a module calling catalog on Firestore sees (no request, no session passed)."""
    ctx = current_rls_context()
    return {"user": ctx.user_id, "roles": list(ctx.roles), "anon": ctx.anonymous}


@pytest.fixture
def app(settings_env: pytest.MonkeyPatch) -> Any:
    settings_env.setenv("TD_SERVICE_TOKEN", TOKEN)
    p = Principal(user_id=uuid7(), session_id=uuid7(), grants=(RoleGrant("admin", "platform"),))
    prev = core_auth.get_session_resolver()
    core_auth.register_session_resolver(Resolver(p))  # type: ignore[arg-type]
    a = FastAPI()
    install_error_handlers(a)
    a.add_middleware(ServiceAuthMiddleware)
    a.add_middleware(RequestContextMiddleware)

    @a.get("/me")
    async def me(principal: Principal = Depends(core_auth.require_active_principal)) -> dict[str, Any]:
        assert current_principal() is principal
        return helper_without_request()

    @a.get("/public")
    async def public() -> dict[str, Any]:
        return helper_without_request()

    @a.get("/sync")
    def sync_route(principal: Principal = Depends(core_auth.require_active_principal)) -> dict[str, Any]:
        return helper_without_request()  # threadpool: copied context, shared state dict

    a.state.p = p
    yield a
    core_auth.register_session_resolver(prev)  # type: ignore[arg-type]


async def test_principal_context_per_request(app: Any) -> None:
    h = {"Authorization": f"Service {TOKEN}", "X-TD-Session": "s1"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        me = (await c.get("/me", headers=h)).json()
        assert me == {"user": str(app.state.p.user_id), "roles": ["admin"], "anon": False}
        assert (await c.get("/sync", headers=h)).json()["user"] == str(app.state.p.user_id)
        assert (await c.get("/public", headers=h)).json() == {"user": None, "roles": [], "anon": True}
    assert current_principal() is None and current_rls_context() == ANONYMOUS  # nothing leaks out
