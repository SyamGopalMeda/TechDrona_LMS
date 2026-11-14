"""Firestore-only paths tests (data-content agent): emulator, **no Postgres** (the root
``migrated_database`` is replaced by a no-op). The Postgres suite is ``tests/paths``."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.firestore.conftest import firestore_emulator, fs_client  # noqa: F401


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    yield None
