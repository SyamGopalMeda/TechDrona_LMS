"""Firestore-only entitlements tests (data-content agent): run against the emulator **without
Postgres**. The root ``migrated_database`` (session, autouse) needs Postgres, so it is replaced
here by a no-op. Audit/outbox/cache side effects (Postgres + Redis) are captured instead of
written; the both-stores behaviour is covered by ``tests/entitlements/test_store_matrix.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

from tests.firestore.conftest import firestore_emulator, fs_client  # noqa: F401


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    yield None


@pytest.fixture
async def fs_env(
    fs_client: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[list[tuple[str, str]]]:
    """``TD_STORE_ENTITLEMENTS=firestore`` on the per-test emulator client; yields the captured
    ``(event_type, entitlement_id)`` side effects (audit + outbox + cache in production)."""
    from app.core.firestore import client as client_mod
    from app.core.firestore.backend import reset_store_backends
    from app.modules.entitlements import service as svc

    client_mod.set_client(fs_client)  # type: ignore[arg-type]
    monkeypatch.setenv("TD_STORE_ENTITLEMENTS", "firestore")
    reset_store_backends()
    seen: list[tuple[str, str]] = []

    async def capture(session: Any, ent: Any, ev: dict[str, Any], actor: Any) -> None:
        seen.append((ev["event_type"], str(ent.id)))

    monkeypatch.setattr(svc, "_after_event", capture)
    try:
        yield seen
    finally:
        monkeypatch.delenv("TD_STORE_ENTITLEMENTS", raising=False)
        reset_store_backends()
        client_mod.set_client(None)
