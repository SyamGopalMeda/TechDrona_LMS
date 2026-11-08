"""Alembic environment (async). Supports multiple branch heads: one branch per module
(implementation-conventions §4); apply with ``alembic upgrade heads``.

URL precedence: ``config.attributes["url"]`` (tests) > ``-x url=...`` >
``DATABASE_MIGRATION_URL`` (td_owner) > ``DATABASE_URL``.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.models_registry import import_all_models

config = context.config
if config.config_file_name is not None and not config.attributes.get("skip_logging_config"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = import_all_models().metadata


def _url() -> str:
    url = config.attributes.get("url") or context.get_x_argument(as_dictionary=True).get("url")
    return str(url or get_settings().migration_url)


def _async_url(url: str) -> str:
    """Migrations always use psycopg (async): hand-written DDL sends multi-statement scripts,
    which asyncpg's prepared statements cannot execute."""
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # ADR-0009 online-safety defaults; individual migrations may override with SET LOCAL.
    connection.execute(text("SET lock_timeout = '5s'"))
    connection.execute(text("SET statement_timeout = '300s'"))
    connection.commit()  # session-level SETs; leave no open transaction for Alembic
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_async_url(_url()), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
            await connection.commit()
    finally:
        await engine.dispose()


def _run(coro_factory) -> None:  # type: ignore[no-untyped-def]
    if sys.platform == "win32":
        # psycopg async cannot use the Windows Proactor loop.
        asyncio.run(coro_factory(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(coro_factory())


if context.is_offline_mode():
    run_migrations_offline()
else:
    _run(run_migrations_online)
