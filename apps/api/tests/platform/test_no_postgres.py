"""The final Firebase stack: every TD_STORE_*=firestore, TD_RUNTIME=firebase, no DATABASE_URL.

The app and the Celery registry must boot, the startup gate must pass, health must answer (the
database check pings Firestore) and nothing may build a Postgres engine. Routes of modules whose
code still uses the request session fail with a clear ``PostgresDisabledError`` (module agents'
work), never by trying to connect.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.core import db, runtime
from app.core.firestore.backend import MODULES, reset_store_backends


@pytest.fixture
def no_pg(settings_env: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    for m in MODULES:
        settings_env.setenv(f"TD_STORE_{m.upper()}", "firestore")
    settings_env.setenv("TD_RUNTIME", "firebase")
    settings_env.setenv("DATABASE_URL", "")
    settings_env.setenv("DATABASE_READ_URL", "")
    settings_env.setenv("TD_CACHE_BACKEND", "")
    reset_store_backends()
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    yield settings_env
    reset_store_backends()


def test_switch_defaults_keep_postgres(settings_env: pytest.MonkeyPatch) -> None:
    settings_env.setenv("TD_RUNTIME", "vm")
    settings_env.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    assert runtime.postgres_enabled()
    settings_env.setenv("TD_RUNTIME", "firebase")  # some modules still on Postgres
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    reset_store_backends()
    assert runtime.postgres_enabled()


def test_no_engine_without_postgres(no_pg: pytest.MonkeyPatch) -> None:
    assert runtime.all_modules_on_firestore() and not runtime.postgres_enabled()
    with pytest.raises(db.PostgresDisabledError):
        db.get_engine()
    assert db._engine is None
    assert not db.NO_POSTGRES
    with pytest.raises(db.PostgresDisabledError):
        db.NO_POSTGRES.execute  # noqa: B018


async def test_app_boots_and_health_answers(no_pg: pytest.MonkeyPatch, fs_client: Any) -> None:
    from app.core.firestore import client as client_mod
    from app.core.redis import close_redis
    from app.main import create_app

    prev = client_mod._client
    client_mod.set_client(fs_client)
    await close_redis()
    try:
        app = create_app()  # startup gate included
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/healthz")).status_code == 200
            assert (await c.get("/api/v1/health/live")).json() == {"status": "ok"}
            r = await c.get("/api/v1/health/ready")
            assert r.status_code == 200, r.text
            assert r.json()["checks"] == {"database": "ok", "redis_cache": "ok"}
            assert (await c.get("/api/v1/me")).status_code == 401  # auth path needs no database
        assert db._engine is None
    finally:
        await close_redis()
        client_mod.set_client(prev)


def test_request_session_dependency_yields_sentinel(no_pg: pytest.MonkeyPatch) -> None:
    import asyncio

    async def first() -> Any:
        gen = db.get_db()
        s = await gen.__anext__()
        await gen.aclose()
        return s

    assert asyncio.run(first()) is db.NO_POSTGRES


def test_celery_registry_boots_without_postgres(no_pg: pytest.MonkeyPatch) -> None:
    import app.worker as worker

    capp = worker.create_celery()  # a fresh app under the no-Postgres settings (module app untouched)
    assert "td.core.outbox_relay" in capp.tasks
    assert capp.send_task.__name__ == "_send_task"  # Cloud Tasks transport installed
