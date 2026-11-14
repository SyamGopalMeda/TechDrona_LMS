"""Store matrix for module tests (docs/firebase/p2.md §Tests).

A module's ``conftest.py`` builds a parametrized fixture with ``backend_fixture``::

    admin_backend = backend_fixture("admin")

    @pytest.mark.usefixtures("admin_backend")
    async def test_x(client, db): ...      # runs as test_x[postgres] and test_x[firestore]

For ``firestore`` the fixture:

1. needs the emulator (``firestore_emulator``; skips when unavailable), wipes it;
2. installs a per-test client and sets ``TD_STORE_<MODULE>=firestore`` (switch re-read);
3. **backfills the module from the Postgres test database** (the migration-seeded rows, e.g. the
   feature flags) — the same path a cutover uses — so the test starts from equal data;
4. restores the Postgres switch and closes the client afterwards.

Firestore writes are not rolled back with the test's Postgres transaction; each test starts
from a wiped emulator instead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from tests.firestore.conftest import TEST_PROJECT, clear_emulator

BACKENDS = ("postgres", "firestore")


async def activate_firestore(
    request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch, modules: tuple[str, ...]
) -> Callable[[], Any]:
    from app.core.config import Settings
    from app.core.firestore import client as client_mod
    from app.core.firestore.backend import reset_store_backends
    from app.core.firestore.backfill import backfill

    host = request.getfixturevalue("firestore_emulator")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", host)
    clear_emulator(host)
    s = Settings(  # type: ignore[call-arg]
        _env_file=None, APP_ENV="test", FIRESTORE_EMULATOR_HOST=host, FIREBASE_PROJECT_ID=TEST_PROJECT
    )
    client = client_mod.make_client(s)
    client_mod.set_client(client)
    for m in modules:
        monkeypatch.setenv(f"TD_STORE_{m.upper()}", "firestore")
    reset_store_backends()
    for m in modules:
        await backfill(db, m, client=client)

    async def restore() -> None:
        for m in modules:
            monkeypatch.delenv(f"TD_STORE_{m.upper()}", raising=False)
        reset_store_backends()
        client_mod.set_client(None)
        await client_mod.aclose(client)

    return restore


def backend_fixture(*modules: str, on_switch: Callable[[], None] | None = None) -> Any:
    """A parametrized fixture (``postgres`` / ``firestore``) for ``modules``."""

    @pytest.fixture(params=BACKENDS)
    async def _fixture(
        request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> AsyncIterator[str]:
        if on_switch:
            on_switch()
        if request.param == "postgres":
            yield "postgres"
        else:
            restore = await activate_firestore(request, db, monkeypatch, modules)
            try:
                yield "firestore"
            finally:
                await restore()
        if on_switch:
            on_switch()

    return _fixture
