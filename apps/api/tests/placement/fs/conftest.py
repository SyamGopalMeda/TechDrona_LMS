"""Firestore-only fixtures for the data-assess repositories (placement, assessments, coding).

These tests run against the Firestore emulator **without Postgres**: ``migrated_database`` (the
root conftest's session-autouse Alembic run) is overridden with a no-op for this directory, and
bank functions get a ``FakeSession`` that answers only the RLS-context query
(``repo_firestore.visibility``). The Postgres side of the matrix is the existing suite
(``tests/placement`` etc.), which needs the docker Postgres.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from tests.firestore.conftest import TEST_PROJECT, clear_emulator, firestore_emulator  # noqa: F401


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """No Postgres for these tests (overrides the root fixture)."""
    yield None


@dataclass
class _Result:
    row: tuple[Any, ...]

    def one(self) -> tuple[Any, ...]:
        return self.row


@dataclass
class FakeSession:
    """Answers the RLS GUC query of ``visibility()``; any other SQL is a test bug."""

    user_id: str = ""
    org_ids: tuple[str, ...] = ()
    is_platform: bool = True
    org_staff: bool = False

    async def execute(self, stmt: Any, *a: Any, **kw: Any) -> _Result:
        sql = str(stmt)
        if "current_setting('app.user_id'" not in sql:
            raise AssertionError(f"unexpected SQL on the Firestore path: {sql[:120]}")
        return _Result(
            (self.user_id, ",".join(self.org_ids), "on" if self.is_platform else "off", self.org_staff)
        )


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession(user_id=str(uuid.uuid4()))


def activate(monkeypatch: pytest.MonkeyPatch, host: str, *modules: str) -> Any:
    from app.core.config import Settings
    from app.core.firestore import client as client_mod
    from app.core.firestore.backend import reset_store_backends

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
    return client


async def deactivate(monkeypatch: pytest.MonkeyPatch, client: Any, *modules: str) -> None:
    from app.core.firestore import client as client_mod
    from app.core.firestore.backend import reset_store_backends

    for m in modules:
        monkeypatch.delenv(f"TD_STORE_{m.upper()}", raising=False)
    reset_store_backends()
    client_mod.set_client(None)
    await client_mod.aclose(client)


@pytest.fixture
async def placement_fs(firestore_emulator: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:  # noqa: F811
    # the owner flips all modules together: placement code paths that read assessments/coding
    # (practice hold-back, coding questions) run on Firestore as well
    client = activate(monkeypatch, firestore_emulator, "placement", "assessments", "coding")
    try:
        yield client
    finally:
        await deactivate(monkeypatch, client, "placement", "assessments", "coding")


# HTTP tests through the FastAPI app (no Postgres: the request session is ``db.NO_POSTGRES``);
# the harness is shared with the data-ops suites.
from tests.audit.fs.http_support import fs_http  # noqa: E402, F401
from tests.audit.fs.support import fs_env  # noqa: E402, F401
