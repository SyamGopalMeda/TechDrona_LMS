"""Admissions on the Firestore emulator without Postgres (``TD_STORE_ADMISSIONS=firestore``).

Run on its own (the root conftest migrates Postgres)::

    TD_TEST_DB_NAME=money_test .venv/Scripts/python -m pytest tests/admissions/firestore \
        --confcutdir=tests/admissions/firestore -p no:cacheprovider

Reuses the commerce fake session (RLS GUCs in memory, any other SQL refused).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from tests.commerce.firestore.conftest import FakeSession, firestore_emulator  # noqa: F401
from tests.firestore.conftest import TEST_PROJECT, clear_emulator


@pytest.fixture
async def fs(firestore_emulator: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:  # noqa: F811
    from app.core.config import Settings
    from app.core.firestore import client as client_mod
    from app.core.firestore.backend import reset_store_backends

    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", firestore_emulator)
    clear_emulator(firestore_emulator)
    s = Settings(  # type: ignore[call-arg]
        _env_file=None,
        APP_ENV="test",
        FIRESTORE_EMULATOR_HOST=firestore_emulator,
        FIREBASE_PROJECT_ID=TEST_PROJECT,
    )
    client = client_mod.make_client(s)
    client_mod.set_client(client)
    monkeypatch.setenv("TD_STORE_ADMISSIONS", "firestore")
    reset_store_backends()
    try:
        yield client
    finally:
        monkeypatch.delenv("TD_STORE_ADMISSIONS", raising=False)
        reset_store_backends()
        client_mod.set_client(None)
        await client_mod.aclose(client)


@pytest.fixture
def session() -> FakeSession:
    return FakeSession().as_platform()
