"""HTTP through the real FastAPI app with **no Postgres** (data-content agent).

Request sessions are ``NO_POSTGRES`` (``install_fake_db``), exactly what the final stack
without Postgres yields: any use raises, so a request that reaches Postgres for a module on
Firestore fails the test. (``FakeSession`` below keeps only the RLS settings in memory, for
service-level tests that need a session-shaped object.) Collaborators that are other
modules' Postgres tables (audit, outbox, ai app gate, orgs/identity adapters) are replaced per
test by recorders or stubs, exactly at the module boundary.

``http_app`` installs the session override on a fresh app and yields ``(client, auth, calls)``:
``auth`` is the root ``FakeAuth`` (login / grant), ``calls`` records audit actions and events.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import Depends

from app.core.principal import Principal


class _Res:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self._row = row

    def one(self) -> tuple[Any, ...]:
        return self._row

    def first(self) -> tuple[Any, ...]:
        return self._row

    def scalar_one(self) -> Any:
        return self._row[0]


class _Tx:
    async def __aenter__(self) -> _Tx:
        return self

    async def __aexit__(self, *a: Any) -> None:
        return None

    is_active = True

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.sync_session = self
        self.guc: dict[str, str] = {
            "app.user_id": "",
            "app.org_ids": "",
            "app.is_platform": "off",
            "app.actor": "anonymous",
            "app.roles": "",
            "app.privacy_tier": "",
        }
        self.added: list[Any] = []

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        sql = str(stmt)
        if "set_config" in sql:
            p = params or {}
            self.guc.update(
                {
                    "app.user_id": p.get("uid", ""),
                    "app.org_ids": p.get("orgs", ""),
                    "app.is_platform": p.get("plat", "off"),
                    "app.actor": p.get("actor", ""),
                    "app.roles": p.get("roles", ""),
                    "app.privacy_tier": p.get("ptier", ""),
                }
            )
            return _Res(())
        if "current_setting" in sql:
            names = re.findall(r"current_setting\('([a-z_.]+)'", sql)
            return _Res(tuple(self.guc[n] for n in names))
        raise AssertionError(f"Postgres statement on the Firestore path: {sql[:300]}")

    def add(self, obj: Any) -> None:
        raise AssertionError(f"ORM add on the Firestore path: {type(obj).__name__}")

    async def flush(self) -> None:
        return None

    def begin(self) -> _Tx:
        return _Tx()

    def begin_nested(self) -> _Tx:
        return _Tx()

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


def install_fake_db(app: Any, *, session: Any = "NO_POSTGRES") -> None:
    """Request sessions are ``NO_POSTGRES`` (what the final Firebase stack yields): falsy, and any
    attribute use raises ``PostgresDisabledError``, so a route of a module on Firestore that still
    touches the Postgres session fails the test. ``session=None`` (also refuses every use) for
    routes that go through ``core_store.idempotent_firestore``, which tests ``session is not None``
    and so calls ``begin_nested`` on ``NO_POSTGRES`` (platform request in the data-content report)."""
    from app.core.auth import require_active_principal
    from app.core.db import NO_POSTGRES, get_db, get_principal_db

    value = NO_POSTGRES if session == "NO_POSTGRES" else session

    async def _db() -> AsyncIterator[Any]:
        yield value

    async def _pdb(principal: Principal = Depends(require_active_principal)) -> AsyncIterator[Any]:
        yield value

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_principal_db] = _pdb


def stub_core(monkeypatch: pytest.MonkeyPatch, calls: list[tuple[str, Any]]) -> None:
    """Audit / outbox / cache bumps (core, Postgres + Redis) -> recorders."""
    import app.core.audit as core_audit
    import app.core.outbox as core_outbox

    async def fake_audit(
        session: Any, actor: Any, action: str, target_type: str, target_id: Any, **kw: Any
    ) -> Any:
        calls.append(("audit", action))
        return None

    async def fake_emit(session: Any, event_type: str, payload: Any, **kw: Any) -> Any:
        calls.append(("event", event_type))
        return None

    monkeypatch.setattr(core_audit, "audit", fake_audit)
    monkeypatch.setattr(core_outbox, "emit_event", fake_emit)
    for mod in (
        "app.modules.paths.service",
        "app.modules.entitlements.service",
        "app.modules.media.service",
        "app.modules.catalog.service",
        "app.modules.catalog.router",
    ):
        m = __import__(mod, fromlist=["x"])
        if hasattr(m, "audit"):
            monkeypatch.setattr(m, "audit", fake_audit)
        if hasattr(m, "emit_event"):
            monkeypatch.setattr(m, "emit_event", fake_emit)
    import app.modules.admin.flags as flags

    async def flag_off(key: str) -> bool:  # maintenance-mode middleware (admin flags + Redis)
        return False

    monkeypatch.setattr(flags, "cached_flag_enabled", flag_off)
    from app.modules.entitlements import cache

    async def no_bump(user_id: Any) -> None:
        return None

    monkeypatch.setattr(cache, "bump", no_bump)
    monkeypatch.setattr(cache, "bump_after_commit", lambda session, user_id: None)
    monkeypatch.setattr(cache, "enabled", lambda: False)


async def switch_to_firestore(fs_client: Any, monkeypatch: pytest.MonkeyPatch, *modules: str) -> None:
    from app.core.firestore import client as client_mod
    from app.core.firestore.backend import reset_store_backends

    client_mod.set_client(fs_client)
    for m in modules:
        monkeypatch.setenv(f"TD_STORE_{m.upper()}", "firestore")
    reset_store_backends()


def restore_switch(monkeypatch: pytest.MonkeyPatch, *modules: str) -> None:
    from app.core.firestore import client as client_mod
    from app.core.firestore.backend import reset_store_backends

    for m in modules:
        monkeypatch.delenv(f"TD_STORE_{m.upper()}", raising=False)
    reset_store_backends()
    client_mod.set_client(None)
