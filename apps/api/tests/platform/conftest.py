"""Platform (Firebase runtime) tests: no Postgres needed.

* ``migrated_database`` (the root conftest's session-wide, autouse Postgres migration) is
  overridden with a no-op here: nothing in this folder touches Postgres.
* Firestore tests reuse the P0 emulator fixtures (``tests/firestore/conftest.py``); run with
  ``TD_TEST_DB_NAME=platform_test`` so the demo project is ``demo-platform-test``.
* ``functions-lms`` (the edge package and main.py) is put on ``sys.path``.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.firestore.conftest import TEST_PROJECT, clear_emulator, firestore_emulator, fs_client  # noqa: F401

FUNCTIONS_DIR = Path(__file__).resolve().parents[4] / "functions-lms"
if str(FUNCTIONS_DIR) not in sys.path:
    sys.path.insert(0, str(FUNCTIONS_DIR))


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    yield None


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Change env-backed settings inside a test; the settings cache is reset before and after."""
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    yield monkeypatch
    monkeypatch.undo()
    reset_settings_cache()
