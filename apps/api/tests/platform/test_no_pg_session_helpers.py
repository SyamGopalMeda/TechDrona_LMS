"""No-Postgres session helpers: rls_scope / system_context / RLS setters are no-ops on the
placeholder, and audit rows + outbox events are buffered to the request's commit point
(written on success, dropped on failure) -- the Postgres transaction semantics, over HTTP."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core import db, outbox
from app.core.audit import AuditActor, audit
from app.core.errors import ProblemError, install_error_handlers
from app.core.firestore.backend import reset_store_backends
from app.core.firestore.collections import physical_name
from app.core.middleware import RequestContextMiddleware

NOPG = db.NO_POSTGRES


async def test_rls_helpers_are_noops_and_scope_follows_context() -> None:
    await db.set_rls_context(NOPG, user_id="u", is_platform=True)  # no SQL, no error
    await db.apply_db_role(NOPG)
    await db.tenant_context(NOPG, None)
    assert db.no_session(None) and db.no_session(NOPG)
    scope = await db.rls_scope(NOPG)
    assert scope.is_platform  # job / script: no request at all
    from app.core.request_context import bind_request_state, reset_request_state

    tok = bind_request_state({})  # an anonymous request
    try:
        assert (await db.rls_scope(NOPG)) == db.RlsScope("", False)
        async with db.system_context(NOPG, "platformtest.job") as s:
            assert s is NOPG and (await db.rls_scope(NOPG)).is_platform
        assert not (await db.rls_scope(NOPG)).is_platform  # restored on exit
    finally:
        reset_request_state(tok)


async def test_rls_scope_uses_the_request_principal() -> None:
    from app.core.ids import uuid7
    from app.core.principal import Principal
    from app.core.request_context import bind_request_state, reset_request_state

    p = Principal(user_id=uuid7(), session_id=uuid7(), grants=())
    tok = bind_request_state({"principal": p})
    try:
        sc = await db.rls_scope(NOPG)
        assert sc.user_id == str(p.user_id) and sc.allows(p.user_id) and not sc.allows(uuid.uuid4())
    finally:
        reset_request_state(tok)


@pytest.fixture
def fs_app(fs_client: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    from app.core.firestore import client as client_mod

    monkeypatch.setenv("TD_STORE_AUDIT", "firestore")
    reset_store_backends()
    prev = client_mod._client
    client_mod.set_client(fs_client)
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    async def work(fail: str | None) -> dict[str, Any]:
        aid = await audit(
            NOPG, AuditActor.system("platformtest"), "platform.thing.done", "thing", uuid.uuid4()
        )
        eid = await outbox.emit_event(
            NOPG, "platformtest.thing_done", {"n": 1}, aggregate_type="thing", aggregate_id=uuid.uuid4()
        )
        if fail == "problem":
            raise ProblemError("conflict")
        if fail == "crash":
            raise RuntimeError("boom")
        return {"audit": str(aid), "event": str(eid)}

    @app.post("/ok")
    async def ok() -> dict[str, Any]:
        return await work(None)

    @app.post("/problem")
    async def problem() -> dict[str, Any]:
        return await work("problem")

    @app.post("/crash")
    async def crash() -> dict[str, Any]:
        return await work("crash")

    yield app
    client_mod.set_client(prev)
    reset_store_backends()


async def _docs(fs_client: Any, coll: str) -> list[dict[str, Any]]:
    return [s.to_dict() async for s in fs_client.collection(physical_name(coll)).stream()]


async def test_success_commits_audit_and_event(fs_app: FastAPI, fs_client: Any) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fs_app), base_url="http://t") as c:
        r = await c.post("/ok")
    assert r.status_code == 200
    audits = await _docs(fs_client, "audit_outbox")
    events = await _docs(fs_client, "outbox_events")
    assert [a["id"] for a in audits] == [r.json()["audit"]]
    assert json.loads(audits[0]["record_json"])["action"] == "platform.thing.done"
    assert [e["id"] for e in events] == [r.json()["event"]] and events[0]["pending_at"] is not None


@pytest.mark.parametrize("path", ["/problem", "/crash"])
async def test_failure_drops_audit_and_event(fs_app: FastAPI, fs_client: Any, path: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fs_app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        r = await c.post(path)
    assert r.status_code in (409, 500)
    assert await _docs(fs_client, "audit_outbox") == []
    assert await _docs(fs_client, "outbox_events") == []


async def test_outside_a_request_emit_writes_at_once(fs_client: Any) -> None:
    from app.core.firestore import client as client_mod

    prev = client_mod._client
    client_mod.set_client(fs_client)
    try:
        eid = await outbox.emit_event(
            NOPG, "platformtest.job_done", {}, aggregate_type="job", aggregate_id=uuid.uuid4()
        )
    finally:
        client_mod.set_client(prev)
    assert [e["id"] for e in await _docs(fs_client, "outbox_events")] == [str(eid)]
