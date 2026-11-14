"""The process Firestore client across event loops (found on the first Firebase deploy, 2026-11-13).

The scheduler runs every job through ``app.core.jobs.run_async``: a fresh event loop per job,
whose ``finally`` closes the loop-bound gRPC client. A long-lived ``ScopedStore`` (module-level
system stores, cached repositories) used to keep the first client it saw, so every later job
failed with ``UsageError: Channel is closed``.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.firestore.conftest import TEST_PROJECT, clear_emulator


@pytest.fixture
def process_client_env(firestore_emulator: str, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from app.core.config import reset_settings_cache
    from app.core.firestore import client as client_mod

    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", firestore_emulator)
    monkeypatch.setenv("FIREBASE_PROJECT_ID", TEST_PROJECT)
    reset_settings_cache()
    clear_emulator(firestore_emulator)
    client_mod.set_client(None)
    yield
    client_mod.set_client(None)
    monkeypatch.undo()
    reset_settings_cache()


def test_long_lived_store_survives_run_async_per_job(process_client_env: None) -> None:
    from app.core.firestore.collections import physical_name
    from app.core.firestore.store import ScopedStore
    from app.core.jobs import run_async

    store = ScopedStore.system("test.loops")  # created once, like a module-level system store

    async def job(i: int) -> int:
        ref = store.client.collection(physical_name("kv")).document(f"loop-test-{i}")
        await ref.set({"i": i})
        return int((await ref.get()).to_dict()["i"])

    assert [run_async(job(i)) for i in range(3)] == [0, 1, 2]


def test_process_client_is_replaced_on_another_loop(process_client_env: None) -> None:
    from app.core.firestore import client as client_mod

    async def grab() -> object:
        return client_mod.get_client()

    a = asyncio.run(grab())
    b = asyncio.run(grab())  # first loop is gone: never hand its client out again
    assert a is not b

    async def same() -> bool:
        return client_mod.get_client() is client_mod.get_client()

    assert asyncio.run(same())


def test_admin_client_is_new_each_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real project path: ``firebase_admin.firestore_async.client()`` caches ONE client per app,
    so the closed client came back after every job. ``_admin_client`` must build a new one."""
    from google.auth.credentials import AnonymousCredentials

    from app.core.config import Settings
    from app.core.firestore import client as client_mod

    class FakeCred:
        def get_credential(self) -> AnonymousCredentials:
            return AnonymousCredentials()

    class FakeApp:
        project_id = "demo-admin-client"
        credential = FakeCred()

    monkeypatch.setattr(client_mod, "admin_app", lambda s=None: FakeApp())
    s = Settings(_env_file=None, APP_ENV="test")  # type: ignore[call-arg]
    a = client_mod._admin_client(s, "(default)")
    b = client_mod._admin_client(s, "(default)")
    assert a is not b
    assert a.project == "demo-admin-client"
