"""Firebase-parity harness (parity-nopg agent): the real FastAPI app over HTTP with EVERY module
on Firestore (emulator) and the request sessions the Firebase stack yields (``NO_POSTGRES``).
No Postgres at all (the root ``migrated_database`` is replaced by a no-op)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.firestore.conftest import firestore_emulator, fs_client  # noqa: F401
from tests.parity.harness import web  # noqa: F401


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    yield None
