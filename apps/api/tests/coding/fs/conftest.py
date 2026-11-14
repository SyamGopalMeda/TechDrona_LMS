"""Firestore-only tests for coding (no Postgres): reuse the data-assess fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from tests.placement.fs.conftest import (  # noqa: F401
    activate,
    deactivate,
    fake_session,
    firestore_emulator,
    migrated_database,
)


@pytest.fixture
async def coding_fs(firestore_emulator: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:  # noqa: F811
    client = activate(monkeypatch, firestore_emulator, "coding")
    try:
        yield client
    finally:
        await deactivate(monkeypatch, client, "coding")
