"""Firestore-only tests for assessments (no Postgres): reuse the data-assess fixtures and the
shared HTTP harness (request session = ``MemoryTx`` through ``StorePrincipalDbSession``)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from tests.audit.fs.http_support import fs_http  # noqa: F401
from tests.audit.fs.support import fs_env  # noqa: F401
from tests.placement.conftest import allow_access  # noqa: F401
from tests.placement.fs.conftest import (  # noqa: F401
    activate,
    deactivate,
    fake_session,
    firestore_emulator,
    migrated_database,
)


@pytest.fixture
async def assessments_fs(firestore_emulator: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:  # noqa: F811
    client = activate(monkeypatch, firestore_emulator, "assessments", "placement", "coding")
    try:
        yield client
    finally:
        await deactivate(monkeypatch, client, "assessments", "placement", "coding")


@pytest.fixture(autouse=True)
def _no_postgres_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Jobs (``store_session``) see the Firebase runtime: no Postgres, so a ``MemoryTx``."""
    from app.core.firestore import sqlstore

    monkeypatch.setattr(sqlstore, "_postgres_available", lambda: False)
