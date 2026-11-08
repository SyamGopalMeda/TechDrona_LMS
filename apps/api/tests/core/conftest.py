"""Core test helpers: an app with extra probe routes exercising core dependencies."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict

from app.core.auth import require_active_principal, require_permission, require_step_up
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.routing import authenticated_router, public_router


class EchoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    count: int


def build_probe_routers() -> list[Any]:
    pub = public_router(prefix="/_probe")

    @pub.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @pub.get("/problem")
    async def problem() -> None:
        raise ProblemError("invalid_state_transition", current_state="closed", allowed=["reopen"])

    @pub.post("/echo")
    async def echo(body: EchoIn) -> dict[str, Any]:
        return body.model_dump()

    authed = authenticated_router(prefix="/_probe")

    @authed.get("/me")
    async def me(p: Principal = Depends(require_active_principal)) -> dict[str, str]:
        return {"user_id": str(p.user_id)}

    status = authenticated_router(prefix="/_probe", route_tag="account_status", idle="neutral")

    @status.get("/status")
    async def status_route(p: Principal = Depends(require_active_principal)) -> dict[str, str]:
        return {"scope": p.scope}

    @authed.get("/perm")
    async def perm(p: Principal = Depends(require_permission("probe.read"))) -> dict[str, bool]:
        return {"ok": True}

    @authed.post("/stepup")
    async def stepup(p: Principal = Depends(require_step_up("privileged"))) -> dict[str, bool]:
        return {"ok": True}

    @authed.post("/idem", status_code=201)
    async def idem(
        request: Request,
        body: dict[str, Any],
        session: PrincipalDbSession,
        p: Principal = Depends(require_active_principal),
    ) -> Any:
        async def op() -> IdemResult:
            await emit_event(
                session,
                "probe.thing_created",
                {"n": body.get("n")},
                aggregate_type="probe",
                aggregate_id=uuid7(),
            )
            if body.get("fail"):
                raise ProblemError("invalid_state_transition", current_state="x", allowed=[])
            if body.get("crash"):
                raise ProblemError("service_unavailable")
            return IdemResult(body={"n": body.get("n"), "id": str(uuid7())}, status=201)

        return await idempotent(request, session, user_id=p.user_id, operation=op)

    return [pub, authed, status]


@pytest.fixture
def probe_app(app: Any) -> Any:
    for r in build_probe_routers():
        app.include_router(r, prefix="/api/v1")
    return app


@pytest.fixture
async def probe_client(probe_app: Any) -> Any:
    transport = httpx.ASGITransport(app=probe_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    from app.core.db import dispose_engine
    from app.core.redis import close_redis

    await dispose_engine()
    await close_redis()
