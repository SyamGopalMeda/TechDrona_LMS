"""ai test fixtures: the fake adapter pinned for every test (no provider is ever called) and an
in-memory rate-limit backend (SEC-05 limits never touch the shared Redis)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from app.modules.ai.adapters import FakeAIAdapter, set_ai_adapter


@pytest.fixture(autouse=True)
def ai_env(monkeypatch: Any) -> Iterator[None]:
    for k in ("AI_PROVIDER", "ANTHROPIC_API_KEY", "AI_DEFAULT_MODEL", "AI_ALLOWED_MODELS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AI_PROVIDER", "fake")
    yield


@pytest.fixture(autouse=True)
def memory_ratelimit() -> Iterator[None]:
    from app.core.ratelimit import MemoryBackend, set_backend

    prev = set_backend(MemoryBackend())
    yield
    set_backend(prev)


@pytest.fixture
def fake_ai() -> Iterator[FakeAIAdapter]:
    a = FakeAIAdapter()
    set_ai_adapter(a)
    yield a
    set_ai_adapter(None)


@pytest.fixture
async def learner(db: Any) -> uuid.UUID:
    from tests.identity.factory import make_user

    return (await make_user(db)).id


async def set_ai(db: Any, **kw: Any) -> None:
    """Update the platform ``ai_settings`` singleton inside the test transaction."""
    from app.core.db import system_context
    from app.modules.ai import store

    await system_context(db, "test.ai")
    await store.write_settings(db, kw, (await _any_user(db)))


async def disable_app(db: Any, app_key: str) -> None:
    from app.core.db import system_context
    from app.modules.ai import store

    await system_context(db, "test.ai")
    await store.write_apps(db, {app_key: False}, (await _any_user(db)))


async def _any_user(db: Any) -> uuid.UUID:
    from tests.identity.factory import make_user

    return (await make_user(db)).id


# Store matrix (docs/firebase/p2.md): ``@pytest.mark.usefixtures("ai_backend")`` runs a test on
# Postgres and on the Firestore emulator (platform AI settings + app toggles).
from tests.firestore.conftest import firestore_emulator  # noqa: E402, F401
from tests.firestore.matrix import backend_fixture  # noqa: E402

ai_backend = backend_fixture("ai")
