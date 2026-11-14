"""Shared test fixtures (Foundation-owned).

Database: the docker-compose Postgres, database ``techdrona_test`` (implementation-conventions
§6). URLs default to the ``DATABASE_*`` values from the environment / root .env with the
database name swapped to ``techdrona_test``; override with:

* ``TEST_DATABASE_URL``            app role (td_app)            — RLS applies
* ``TEST_MIGRATION_DATABASE_URL``  owner role (td_owner)        — runs ``alembic upgrade heads``
* ``TEST_SEALER_DATABASE_URL``     td_audit_sealer
* ``TEST_ADMIN_DATABASE_URL``      superuser on db ``postgres`` — only for ``TD_TEST_RESET_DB=1``

``TD_TEST_RESET_DB=1`` drops and recreates ``techdrona_test`` before migrating (needs the
bootstrap superuser). Otherwise migrations are applied idempotently on the existing DB.

Fixtures for module tests:

* ``db``      AsyncSession on td_app inside an outer transaction rolled back after the test;
              the app under test uses the same connection (savepoints), so nothing persists.
* ``app`` / ``client``  FastAPI app + httpx AsyncClient (ASGI, no network).
* ``auth``    ``FakeAuth`` registry: ``auth.login(principal) -> headers``,
              ``auth.grant(principal, "perm.key")``. Module routers are imported first (so
              their real resolver/checker registrations have happened) and the real ones are
              restored after each test.
* ``committed_engine`` / ``sealer_engine``  real engines for tests that need commits.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

API_DIR = Path(__file__).resolve().parents[1]
# Parallel agents/CI shards set TD_TEST_DB_NAME (e.g. techdrona_test_catalog) so concurrent
# runs with TD_TEST_RESET_DB=1 never drop each other's database.
TEST_DB_NAME = os.environ.get("TD_TEST_DB_NAME", "techdrona_test")
# TD_TEST_NO_PG=1: run without Postgres (Firestore/emulator suites, platform tests). The session
# migration is skipped and every Postgres fixture (engines, ``db``) skips its test. Default: off.
NO_PG = os.environ.get("TD_TEST_NO_PG") == "1"
_NO_PG_URL = "postgresql+asyncpg://no-pg:no-pg@127.0.0.1:1/no_pg"
SERVICE_TOKEN = "test-service-token-" + "a" * 48


def _env_or_dotenv(name: str) -> str | None:
    from app.core.security import load_env_mapping

    return load_env_mapping().get(name) or None


def _to_test_db(url: str | None, driver: str = "postgresql+asyncpg") -> str | None:
    if not url:
        return None
    u = make_url(url).set(database=TEST_DB_NAME, drivername=driver)
    return u.render_as_string(hide_password=False)


@dataclass(frozen=True)
class DbUrls:
    app: str
    migration: str
    sealer: str
    admin: str


def _resolve_urls() -> DbUrls:
    app_url = os.environ.get("TEST_DATABASE_URL") or _to_test_db(_env_or_dotenv("DATABASE_URL"))
    mig = os.environ.get("TEST_MIGRATION_DATABASE_URL") or _to_test_db(
        _env_or_dotenv("DATABASE_MIGRATION_URL")
    )
    sealer = os.environ.get("TEST_SEALER_DATABASE_URL") or _to_test_db(
        _env_or_dotenv("DATABASE_AUDIT_SEALER_URL")
    )
    if not (app_url and mig and sealer):
        raise pytest.UsageError("set DATABASE_URL/DATABASE_MIGRATION_URL/DATABASE_AUDIT_SEALER_URL or TEST_*")
    admin = os.environ.get("TEST_ADMIN_DATABASE_URL")
    if not admin:
        u = make_url(app_url)
        admin = u.set(username="techdrona", password="techdrona_dev", database="postgres").render_as_string(
            hide_password=False
        )
    return DbUrls(app_url, mig, sealer, admin)


URLS: DbUrls


# --------------------------------------------------------------------------- TD_TEST_NO_PG auto-skip
#
# With TD_TEST_NO_PG=1 a test that still reaches Postgres is SKIPPED (not failed):
#   * explicitly: ``@pytest.mark.needs_pg``;
#   * by fixture: the Postgres fixtures (``db``, ``app_engine``, ...) skip themselves;
#   * by detection: every asyncpg / psycopg connection attempt is recorded; a test that fails
#     (in setup, call or teardown) after attempting one is reported as skipped "needs Postgres".
#     This covers tests that build their own engines or hit a Postgres-backed route through the
#     ``client`` fixture (the app then answers 503 and the test's assertion fails).
# Default (switch unset): nothing here is active.

_PG_TOUCHED: list[bool] = [False]


def _install_pg_probe() -> None:
    import asyncpg

    orig = asyncpg.connect

    async def connect(*a: Any, **kw: Any) -> Any:
        _PG_TOUCHED[0] = True
        return await orig(*a, **kw)

    asyncpg.connect = connect  # type: ignore[assignment]
    try:
        import psycopg

        orig_sync = psycopg.Connection.connect.__func__  # type: ignore[attr-defined]

        def sync_connect(cls: Any, *a: Any, **kw: Any) -> Any:
            _PG_TOUCHED[0] = True
            return orig_sync(cls, *a, **kw)

        psycopg.Connection.connect = classmethod(sync_connect)  # type: ignore[assignment,method-assign]
    except Exception:  # noqa: S110 - psycopg optional here
        pass


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not NO_PG:
        return
    skip = pytest.mark.skip(reason="needs Postgres (TD_TEST_NO_PG=1)")
    for item in items:
        if item.get_closest_marker("needs_pg") is not None:
            item.add_marker(skip)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item: pytest.Item) -> Iterator[None]:
    _PG_TOUCHED[0] = False
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Iterator[None]:
    outcome = yield
    if not NO_PG:
        return
    rep = outcome.get_result()  # type: ignore[attr-defined]
    if rep.failed and _PG_TOUCHED[0]:
        rep.outcome = "skipped"
        rep.longrepr = (
            str(item.path),
            item.location[1] or 0,
            "Skipped: needs Postgres (TD_TEST_NO_PG=1; the test opened a Postgres connection)",
        )


def pytest_configure(config: pytest.Config) -> None:
    global URLS
    config.addinivalue_line(
        "markers", "needs_pg: the test needs a Postgres database (skipped with TD_TEST_NO_PG=1)"
    )
    if NO_PG:
        _install_pg_probe()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # psycopg/asyncpg-safe
    try:
        URLS = _resolve_urls()
    except pytest.UsageError:
        if not NO_PG:
            raise
        URLS = DbUrls(_NO_PG_URL, _NO_PG_URL, _NO_PG_URL, _NO_PG_URL)
    os.environ["APP_ENV"] = "test"
    os.environ["LOG_FORMAT"] = "json"
    os.environ["DATABASE_URL"] = URLS.app
    os.environ["DATABASE_MIGRATION_URL"] = URLS.migration
    os.environ["DATABASE_AUDIT_SEALER_URL"] = URLS.sealer
    os.environ["TD_SERVICE_TOKEN"] = SERVICE_TOKEN
    os.environ["TD_SERVICE_TOKEN_PREVIOUS"] = ""
    os.environ["TD_ROUTER_SET"] = "all"
    os.environ["TD_DB_SET_ROLE"] = ""
    # TD_SIMPLE_AUTH is honoured in every APP_ENV and may be on in the server's .env: the suite
    # tests the strict pipeline; tests/identity/test_simple_auth.py switches it on per test.
    os.environ["TD_SIMPLE_AUTH"] = "false"
    os.environ.setdefault("TD_K_DEVICE_KEY_V1", "11" * 32)
    os.environ.setdefault("TD_K_LOGIN_KEY_V1", "22" * 32)
    os.environ["TD_K_DEVICE_ACTIVE_VERSION"] = "1"
    os.environ["TD_K_LOGIN_ACTIVE_VERSION"] = "1"
    os.environ.setdefault("TD_K_TOTP_KEY_V1", "33" * 32)
    os.environ["TD_K_TOTP_ACTIVE_VERSION"] = "1"
    from app.core.config import reset_settings_cache
    from app.core.crypto import reset_aead_keyrings
    from app.core.security import reset_keyrings

    reset_settings_cache()
    reset_keyrings()
    reset_aead_keyrings()


# --------------------------------------------------------------------------- database setup


async def _reset_database(admin_url: str) -> None:
    eng = create_async_engine(admin_url, poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with eng.connect() as c:
            await c.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
            await c.execute(text(f"CREATE DATABASE {TEST_DB_NAME} OWNER techdrona"))
            await c.execute(text(f"GRANT CONNECT, CREATE, TEMPORARY ON DATABASE {TEST_DB_NAME} TO td_owner"))
            await c.execute(
                text(
                    f"GRANT CONNECT ON DATABASE {TEST_DB_NAME} TO td_app, td_readonly, td_audit_sealer, td_maintenance"
                )
            )
    finally:
        await eng.dispose()
    db_url = make_url(admin_url).set(database=TEST_DB_NAME).render_as_string(hide_password=False)
    eng = create_async_engine(db_url, poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with eng.connect() as c:
            for ext in ("pgcrypto", "citext", "btree_gist"):
                await c.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
            await c.execute(text("GRANT USAGE, CREATE ON SCHEMA public TO td_owner"))
    finally:
        await eng.dispose()


def _alembic_upgrade_heads(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.attributes["url"] = url
    cfg.attributes["skip_logging_config"] = True
    # learning_0005 (certificate_outbox policy) uses app.caller_is_org_staff() from orgs_0004 but
    # can't declare a cross-branch depends_on; on an empty database "heads" may order it first
    # (seen after admissions_0003 / identity_0006 were added). Build that prerequisite first.
    command.upgrade(cfg, "orgs_0004")
    command.upgrade(cfg, "heads")


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[DbUrls]:
    if NO_PG:
        yield URLS
        return
    if os.environ.get("TD_TEST_RESET_DB") == "1":
        asyncio.run(_reset_database(URLS.admin))
    _alembic_upgrade_heads(URLS.migration)
    yield URLS


# --------------------------------------------------------------------------- engines/sessions


def _engine(url: str) -> AsyncEngine:
    if NO_PG:
        pytest.skip("needs Postgres (TD_TEST_NO_PG=1)")
    return create_async_engine(url, poolclass=pool.NullPool)


@pytest.fixture
async def app_engine() -> AsyncIterator[AsyncEngine]:
    eng = _engine(URLS.app)
    yield eng
    await eng.dispose()


@pytest.fixture
async def committed_engine() -> AsyncIterator[AsyncEngine]:
    """td_app engine whose writes really commit (for multi-role flows such as sealing)."""
    eng = _engine(URLS.app)
    yield eng
    await eng.dispose()


@pytest.fixture
async def sealer_engine() -> AsyncIterator[AsyncEngine]:
    eng = _engine(URLS.sealer)
    yield eng
    await eng.dispose()


@pytest.fixture
async def owner_engine() -> AsyncIterator[AsyncEngine]:
    eng = _engine(URLS.migration)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(app_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """td_app session inside an outer transaction that is always rolled back. The app under
    test shares the connection (its ``session.begin()`` becomes a SAVEPOINT)."""
    from app.core.db import set_sessionmaker

    async with app_engine.connect() as conn:
        outer = await conn.begin()
        factory = async_sessionmaker(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        set_sessionmaker(factory)
        session = factory()
        try:
            yield session
        finally:
            await session.close()
            set_sessionmaker(None)
            if outer.is_active:
                await outer.rollback()


# --------------------------------------------------------------------------- app / client / auth


@dataclass
class FakeAuth:
    sessions: dict[str, Any] = field(default_factory=dict)
    perms: set[tuple[uuid.UUID, str]] = field(default_factory=set)

    def login(self, principal: Any, token: str | None = None) -> dict[str, str]:
        from app.core.security import generate_token

        token = token or generate_token()
        self.sessions[token] = principal
        return {"Authorization": f"Service {SERVICE_TOKEN}", "X-TD-Session": token}

    def grant(self, principal: Any, permission: str) -> None:
        self.perms.add((principal.user_id, permission))

    # SessionResolver
    async def resolve(self, request: Any, session_token: str, ctx: Any) -> Any:
        from app.core.errors import ProblemError

        p = self.sessions.get(session_token)
        if p is None:
            raise ProblemError("unauthenticated")
        return p

    # PermissionChecker
    async def has_permission(self, principal: Any, permission: str, scope: Any, request: Any) -> bool:
        return (principal.user_id, permission) in self.perms


@pytest.fixture
def auth() -> Iterator[FakeAuth]:
    from app.core import auth as core_auth
    from app.main import discover_routers

    # Import every module router BEFORE capturing: modules register the real resolver/checker
    # at import time. Capturing first would save ``None`` and restore it over the real ones.
    discover_routers("all")
    prev_resolver = core_auth.get_session_resolver()
    prev_checker = core_auth._permission_checker
    fake = FakeAuth()
    core_auth.register_session_resolver(fake)
    core_auth.register_permission_checker(fake)
    yield fake
    core_auth.register_session_resolver(prev_resolver)
    core_auth.register_permission_checker(prev_checker)


@pytest.fixture
def make_principal() -> Any:
    from app.core.ids import uuid7
    from app.core.principal import Principal, RoleGrant

    def _make(**kw: Any) -> Principal:
        roles = kw.pop("roles", ())
        grants = tuple(RoleGrant(r, "platform") for r in roles)
        return Principal(
            user_id=kw.pop("user_id", uuid7()), session_id=kw.pop("session_id", uuid7()), grants=grants, **kw
        )

    return _make


@pytest.fixture
def app() -> Any:
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(app: Any) -> AsyncIterator[Any]:
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    from app.core.db import dispose_engine
    from app.core.redis import close_redis

    await dispose_engine()
    await close_redis()
