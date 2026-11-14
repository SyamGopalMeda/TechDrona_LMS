"""HTTP harness for the data-ops Firestore tests: the real FastAPI app, no Postgres.

* The request session is ``app.core.db.NO_POSTGRES`` (what the Firebase stack yields).
  ``RecordingSession`` (kept for unit tests that need a session object) replaces the per-request Postgres session (``get_db`` /
  ``get_principal_db`` dependency overrides). It accepts only what the Firestore code paths still
  send to the caller's session -- ``core.audit.audit()`` and ``core.outbox.emit_event()`` INSERTs
  -- and records them. Any other statement fails the test (a Firestore route touched Postgres).
  ``drain_audit()`` moves the recorded audit rows into the Firestore ``audit_outbox`` (what
  ``core.audit`` will do once it writes Firestore; see data-ops.md "Requests").
* ``fs_http`` fixture: (httpx client, recording session, FakeAuth) with the in-memory rate limiter.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest


class _Result:
    rowcount = 1

    def scalar(self) -> Any:
        return None

    def scalar_one_or_none(self) -> Any:
        return None


class _Savepoint:
    is_active = True

    async def commit(self) -> None:
        self.is_active = False

    async def rollback(self) -> None:
        self.is_active = False


class PostgresTouched(AssertionError):
    pass


class RecordingSession:
    ALLOWED = ("audit_outbox", "outbox_events")

    def __init__(self) -> None:
        self.inserts: list[tuple[str, dict[str, Any]]] = []
        self.info: dict[str, Any] = {}

    async def execute(self, stmt: Any, *args: Any, **kw: Any) -> Any:
        table = getattr(getattr(stmt, "table", None), "name", None)
        if getattr(stmt, "is_insert", False) and table in self.ALLOWED:
            self.inserts.append((table, dict(stmt.compile().params)))
            return _Result()
        raise PostgresTouched(f"Postgres statement on the Firestore path: {stmt}")

    async def get(self, *a: Any, **k: Any) -> Any:
        raise PostgresTouched(f"session.get{a}")

    def add(self, obj: Any) -> None:
        raise PostgresTouched(f"session.add({type(obj).__name__})")

    async def flush(self, *a: Any) -> None:
        return None

    async def begin_nested(self) -> _Savepoint:
        return _Savepoint()

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def in_transaction(self) -> bool:
        return True

    def audit_actions(self) -> list[str]:
        return [p["record"]["action"] for t, p in self.inserts if t == "audit_outbox"]

    async def drain_audit(self) -> int:
        """Write the recorded audit rows into the Firestore outbox (one transaction)."""
        from app.core.firestore.store import ScopedStore, ScopedTransaction
        from app.core.time import utcnow
        from app.modules.audit.repo_firestore import outbox_doc
        from app.modules.audit.store_specs import OUTBOX

        rows = [p for t, p in self.inserts if t == "audit_outbox"]
        self.inserts = [(t, p) for t, p in self.inserts if t != "audit_outbox"]

        async def fn(tx: ScopedTransaction) -> None:
            for p in rows:
                tx.raw_create(OUTBOX, str(p["id"]), outbox_doc(p["id"], p["record"], utcnow()))

        if rows:
            await ScopedStore.system("test.audit_drain").run_transaction(fn)
        return len(rows)


@pytest.fixture
async def fs_http(fs_env: Any, auth: Any) -> AsyncIterator[tuple[Any, RecordingSession, Any]]:
    import httpx

    from app.core.db import NO_POSTGRES, get_db, get_principal_db
    from app.core.ratelimit import MemoryBackend, set_backend
    from app.main import create_app

    rec = RecordingSession()

    async def _session() -> AsyncIterator[Any]:
        # The Firebase stack: no Postgres engine, the request session is NO_POSTGRES (falsy; any
        # use raises PostgresDisabledError). Firestore code paths must never touch it.
        yield NO_POSTGRES

    prev = set_backend(MemoryBackend())
    app = create_app()
    app.dependency_overrides[get_db] = _session
    app.dependency_overrides[get_principal_db] = _session
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c, rec, auth
    finally:
        set_backend(prev)
