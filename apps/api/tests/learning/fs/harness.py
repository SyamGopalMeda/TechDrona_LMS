"""Shared no-Postgres HTTP harness of the data-learning agent (learning, engage, mentoring).

Builds on ``tests/paths/fs/http_harness.py`` (``FakeSession``: RLS GUCs in memory, **any other
SQL statement or ORM ``add`` fails the test**). Two request-session flavours:

* ``LearningSession`` — truthy, like a real session: ``system_context`` runs (GUCs only);
* ``FirebaseSession`` — **falsy**, like core's ``NO_POSTGRES`` on the final Firebase stack (code
  that branches on ``if session`` takes the no-Postgres path), but with an awaitable
  ``begin_nested`` because core idempotency (``core_store``) calls it on any non-``None`` session.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Any

import httpx
import pytest

from tests.paths.fs.http_harness import FakeSession, restore_switch, stub_core, switch_to_firestore

API = "/api/v1"


class _Nested:
    is_active = True

    async def __aenter__(self) -> _Nested:
        return self

    async def __aexit__(self, *a: Any) -> None:
        return None

    def __await__(self) -> Any:
        async def _self() -> Any:
            return self

        return _self().__await__()

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class LearningSession(FakeSession):
    def begin_nested(self) -> Any:  # type: ignore[override]
        return _Nested()


class FirebaseSession(LearningSession):
    def __bool__(self) -> bool:
        return False


def install_sessions(app: Any, cls: type[FakeSession] = LearningSession) -> None:
    """A fresh session per request, bound to the caller's tenant context (what
    ``get_principal_db`` does with a real session)."""
    from fastapi import Depends

    from app.core.auth import require_active_principal
    from app.core.db import get_db, get_principal_db, tenant_context
    from app.core.principal import Principal

    async def _db() -> AsyncIterator[Any]:
        yield cls()

    async def _pdb(principal: Principal = Depends(require_active_principal)) -> AsyncIterator[Any]:
        s = cls()
        await tenant_context(s, principal)  # type: ignore[arg-type]
        yield s

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_principal_db] = _pdb


def stub_modules(
    monkeypatch: pytest.MonkeyPatch, calls: list[tuple[str, Any]], modules: Iterable[str]
) -> None:
    """``audit`` / ``emit_event`` names imported by these modules -> recorders; app gate on."""

    async def fake_audit(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        calls.append(("audit", action))

    async def fake_emit(session: Any, event_type: str, payload: Any, **kw: Any) -> Any:
        calls.append(("event", event_type))

    async def app_on(session: Any, *, app_key: str) -> None:
        return None

    for name in modules:
        m = __import__(name, fromlist=["x"])
        for attr, fn in (("audit", fake_audit), ("emit_event", fake_emit), ("require_app_enabled", app_on)):
            if hasattr(m, attr):
                monkeypatch.setattr(m, attr, fn)


async def open_app(
    fs_client: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stores: tuple[str, ...],
    stubbed: Iterable[str],
    session_cls: type[FakeSession] = LearningSession,
) -> tuple[Any, list[tuple[str, Any]]]:
    from app.core.ratelimit import MemoryBackend, set_backend
    from app.main import create_app

    calls: list[tuple[str, Any]] = []
    stub_core(monkeypatch, calls)
    stub_modules(monkeypatch, calls, stubbed)
    prev = set_backend(MemoryBackend())
    await switch_to_firestore(fs_client, monkeypatch, *stores)
    app = create_app()
    install_sessions(app, session_cls)
    app.state.td_prev_rl = prev
    return app, calls


def close_app(app: Any, monkeypatch: pytest.MonkeyPatch, stores: tuple[str, ...]) -> None:
    from app.core.ratelimit import set_backend

    set_backend(getattr(app.state, "td_prev_rl", None))
    restore_switch(monkeypatch, *stores)


def client_for(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def login(auth: Any, make_principal: Any, *perms: str, **kw: Any) -> tuple[Any, dict[str, str]]:
    p = make_principal(**kw)
    for perm in perms:
        auth.grant(p, perm)
    return p, auth.login(p)


async def batch_with(students: list[Any], creator: Any) -> Any:
    """A company batch with active student members, through orgs' public API (Firestore)."""
    import uuid

    from app.core.company import COMPANY_ORG_ID
    from app.core.time import utcnow
    from app.modules.orgs import public as orgs_public
    from app.modules.orgs.models import Batch, BatchMember

    bid = uuid.uuid4()
    now = utcnow()
    await orgs_public.add_batch(
        None,  # type: ignore[arg-type]
        Batch(
            id=bid, organization_id=COMPANY_ORG_ID, name="CSE 27", code=f"CSE-{str(bid)[:6]}", status="active",
            created_by=creator, created_at=now, updated_at=now,
        ),
    )  # fmt: skip
    for u in students:
        await orgs_public.add_batch_member(
            None,  # type: ignore[arg-type]
            BatchMember(
                id=uuid.uuid4(), batch_id=bid, organization_id=COMPANY_ORG_ID, user_id=u, member_role="student",
                status="active", added_by=creator, added_at=now, updated_at=now,
            ),
        )  # fmt: skip
    return bid
