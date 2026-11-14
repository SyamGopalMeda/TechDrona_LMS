"""Database access: async engine, sessions, RLS tenant context (ADR-0003).

* ``Base`` — declarative base for every module's ``models.py``.
* ``get_db`` — FastAPI dependency: one transaction per request, RLS context cleared
  (no user, no orgs, not platform) — rows under RLS are invisible unless the route sets
  context. Use ``get_principal_db`` on authenticated routes.
* ``tenant_context(session, principal)`` — transaction-local GUCs via ``set_config(..., true)``:
  ``app.user_id``, ``app.org_ids``, ``app.is_platform``, ``app.actor``, ``app.roles``,
  ``app.privacy_tier``.
* ``system_context(session, job)`` — named system job (``app.is_platform = on``), audited by
  the caller. ``await`` it for whole-transaction system work; ``async with`` it inside
  authenticated handlers so the principal's context is restored afterwards (DB-06).
"""

from __future__ import annotations

import contextvars
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.auth import require_active_principal
from app.core.config import get_settings
from app.core.principal import Principal

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _connect_args(url: str) -> dict[str, Any]:
    s = get_settings()
    if url.startswith("postgresql+asyncpg"):
        return {
            "statement_cache_size": s.DB_STATEMENT_CACHE_SIZE,
            "server_settings": {
                "statement_timeout": str(s.DB_STATEMENT_TIMEOUT_MS),
                "application_name": s.TD_SERVICE_NAME,
                "timezone": "UTC",
            },
        }
    return {}


def make_engine(url: str | None = None, **kwargs: Any) -> AsyncEngine:
    s = get_settings()
    url = url or s.DATABASE_URL
    opts: dict[str, Any] = {
        "pool_size": s.DB_POOL_SIZE,
        "max_overflow": s.DB_MAX_OVERFLOW,
        "pool_timeout": s.DB_POOL_TIMEOUT_SECONDS,
        "pool_pre_ping": s.DB_POOL_PRE_PING,
        "pool_recycle": s.DB_POOL_RECYCLE_SECONDS,
        "connect_args": _connect_args(url),
    }
    opts.update(kwargs)
    if "poolclass" in kwargs:
        for k in ("pool_size", "max_overflow", "pool_timeout", "pool_recycle"):
            opts.pop(k, None)
    return create_async_engine(url, **opts)


class PostgresDisabledError(RuntimeError):
    """Raised when Postgres is used on a stack that has none (``runtime.postgres_enabled()``)."""


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        from app.core.runtime import postgres_enabled

        if not postgres_enabled():
            raise PostgresDisabledError(
                "Postgres is not configured on this stack (TD_RUNTIME=firebase with every module on "
                "Firestore, or no DATABASE_URL): use the module's Firestore repository"
            )
        _engine = make_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


def set_sessionmaker(factory: async_sessionmaker[AsyncSession] | None) -> None:
    """Override the session factory (tests bind it to a rolled-back connection)."""
    global _sessionmaker
    _sessionmaker = factory


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


# --------------------------------------------------------------------------- RLS context
#
# Without Postgres (``NO_POSTGRES`` / ``None`` session: the Firebase stack) there are no GUCs. The
# RLS helpers below are then no-ops, ``system_context`` records the platform scope in a ContextVar
# and ``rls_scope`` answers from it or from the caller's principal (``request_context``).

_platform_job: contextvars.ContextVar[str | None] = contextvars.ContextVar("td_platform_job", default=None)


def current_platform_job() -> str | None:
    """The named system job of the enclosing no-Postgres ``system_context`` block, else None."""
    return _platform_job.get()


def no_sql_session(session: Any) -> bool:
    """``None`` or the ``NO_POSTGRES`` placeholder: nothing at all to run SQL or GUCs on. The
    RLS helpers below no-op on these (but still pass the engine's ``MemoryTx``, which emulates
    ``set_config`` / ``current_setting`` and captures outbox inserts in its unit of work)."""
    return session is None or isinstance(session, _NoPostgresSession)


def is_memory_tx(session: Any) -> bool:
    """The SQL engine's in-memory no-Postgres transaction (``sqlstore.MemoryTx``), duck-typed
    so core does not import the engine."""
    return type(session).__name__ == "MemoryTx" and hasattr(session, "guc")


def no_session(session: Any) -> bool:
    """True for "no Postgres connection behind this session": ``None``, ``NO_POSTGRES`` or a
    ``MemoryTx``. Read helpers that would query Postgres tables (``outbox.read_events``) use this
    so they never try Postgres from a ``MemoryTx`` context."""
    return no_sql_session(session) or is_memory_tx(session)


_GUC_SQL = text(
    "SELECT set_config('app.user_id', :uid, true), set_config('app.org_ids', :orgs, true), "
    "set_config('app.is_platform', :plat, true), set_config('app.actor', :actor, true), "
    "set_config('app.roles', :roles, true), set_config('app.privacy_tier', :ptier, true)"
)


async def apply_db_role(session: AsyncSession) -> None:
    if no_sql_session(session):
        return
    role = get_settings().TD_DB_SET_ROLE
    if role:
        # validated as a plain identifier in Settings
        await session.execute(text(f"SET LOCAL ROLE {role}"))


async def set_rls_context(
    session: AsyncSession,
    *,
    user_id: str | None = None,
    org_ids: Iterable[Any] = (),
    is_platform: bool = False,
    actor: str = "anonymous",
    roles: Iterable[str] = (),
    privacy_tier: str = "",
) -> None:
    if no_sql_session(session):
        return
    await session.execute(
        _GUC_SQL,
        {
            "uid": str(user_id) if user_id else "",
            "orgs": ",".join(str(o) for o in org_ids),
            "plat": "on" if is_platform else "off",
            "actor": actor,
            "roles": ",".join(roles),
            "ptier": privacy_tier or "",
        },
    )


async def tenant_context(session: AsyncSession, principal: Principal | None) -> None:
    """Bind the principal's tenant context to the current transaction."""
    if principal is None:
        await set_rls_context(session)
        return
    await set_rls_context(
        session,
        user_id=str(principal.user_id),
        org_ids=principal.org_ids,
        is_platform=principal.is_platform,
        actor=f"user:{principal.user_id}",
        roles=principal.role_keys,
        privacy_tier=principal.privacy_tier or "",
    )


_READ_GUC_SQL = text(
    "SELECT current_setting('app.user_id', true), current_setting('app.org_ids', true), "
    "current_setting('app.is_platform', true), current_setting('app.actor', true), "
    "current_setting('app.roles', true), current_setting('app.privacy_tier', true)"
)


_SCOPE_GUC_SQL = text("SELECT current_setting('app.user_id', true), current_setting('app.is_platform', true)")


@dataclass(frozen=True, slots=True)
class RlsScope:
    """``app.user_id`` / ``app.is_platform`` of the current transaction (see ``rls_scope``)."""

    user_id: str
    is_platform: bool

    def allows(self, owner_id: Any) -> bool:
        """The RLS ``O`` predicate: ``user_id = app.user_id() OR app.is_platform()``."""
        return self.is_platform or (bool(self.user_id) and str(owner_id) == self.user_id)


async def rls_scope(session: AsyncSession) -> RlsScope:
    """The caller's row-level scope, for stores without RLS (Firestore repositories apply the same
    predicate as the Postgres policy to the same transaction context).

    Without a Postgres session: platform inside ``system_context`` (and in jobs, outside any
    request); otherwise the request principal's scope; an anonymous request gets no rows."""
    if no_sql_session(session):
        if _platform_job.get() is not None:
            return RlsScope("", True)
        from app.core.request_context import _request_state, current_principal

        p = current_principal()
        if p is not None:
            return RlsScope(str(p.user_id), bool(p.is_platform))
        if _request_state.get() is None:  # job / script: no request at all
            return RlsScope("", True)
        return RlsScope("", False)
    uid, plat = (await session.execute(_SCOPE_GUC_SQL)).one()
    return RlsScope(str(uid or ""), (plat or "") == "on")


class SystemContext:
    """Platform RLS scope for a named system job (webhook processor, schedulers, sealer reads).

    Two forms:

    * ``await system_context(session, job)`` switches the **rest of the transaction** to
      platform scope. Only for transactions that are system work end to end (jobs, pre-auth
      public routes that must find a user before any principal exists).
    * ``async with system_context(session, job):`` scopes platform access to the block and
      restores the previous tenant context (user, orgs, roles, ...) on exit, also when the
      block raises (DB-06). Use this inside authenticated request handlers.
    """

    __slots__ = ("_job", "_prev", "_session", "_token")

    def __init__(self, session: AsyncSession, job: str) -> None:
        if not job or not job.replace("_", "").replace(".", "").replace("-", "").isalnum():
            raise ValueError("system job name must be a plain identifier")
        self._session = session
        self._job = job
        self._prev: tuple[str, ...] | None = None
        self._token: contextvars.Token[str | None] | None = None

    async def _enter(self) -> None:
        if no_sql_session(self._session):
            self._token = _platform_job.set(self._job)
            return
        await set_rls_context(self._session, is_platform=True, actor=f"system:{self._job}")

    def __await__(self) -> Any:
        return self._enter().__await__()

    async def __aenter__(self) -> AsyncSession:
        if no_sql_session(self._session):
            await self._enter()
            return self._session
        row = (await self._session.execute(_READ_GUC_SQL)).one()
        self._prev = tuple("" if v is None else str(v) for v in row)
        await self._enter()
        return self._session

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if no_sql_session(self._session):
            if self._token is not None:
                _platform_job.reset(self._token)
            return
        assert self._prev is not None
        uid, orgs, plat, actor, roles, ptier = self._prev
        params = {
            "uid": uid,
            "orgs": orgs,
            "plat": plat or "off",
            "actor": actor or "anonymous",
            "roles": roles,
            "ptier": ptier,
        }
        try:
            await self._session.execute(_GUC_SQL, params)
        except Exception:
            # A failed transaction cannot run statements; it is rolled back as a whole (its
            # GUCs with it). Never mask the block's own exception.
            if exc_type is None:
                raise


def system_context(session: AsyncSession, job: str) -> SystemContext:
    """See :class:`SystemContext` (awaitable, or an async context manager that restores)."""
    return SystemContext(session, job)


def as_system(session: AsyncSession, job: str) -> SystemContext:
    """Alias that reads better at call sites: ``async with as_system(session, "x.y"):``."""
    return SystemContext(session, job)


class _NoPostgresSession:
    """Request "session" on a stack without Postgres: falsy, and any use raises a clear
    ``PostgresDisabledError`` (a route of a module still on Postgres code paths)."""

    def __bool__(self) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        raise PostgresDisabledError(
            f"Postgres session used ({name}) on a stack without Postgres: this route's module "
            "must use its Firestore repository"
        )


NO_POSTGRES: Any = _NoPostgresSession()


def _pg_enabled() -> bool:
    from app.core.runtime import postgres_enabled

    return postgres_enabled()


async def get_db() -> AsyncIterator[AsyncSession]:
    """One transaction per request with an empty RLS context (public routes).

    Use through ``DbSession`` so the commit happens before the response is sent. On a stack
    without Postgres (``runtime.postgres_enabled()`` is False) the dependency yields ``NO_POSTGRES`` (falsy;
    any use raises ``PostgresDisabledError``):
    routes of modules on Firestore never touch it.
    """
    if _sessionmaker is None and not _pg_enabled():
        yield NO_POSTGRES
        return
    async with get_sessionmaker()() as session, session.begin():
        await apply_db_role(session)
        await set_rls_context(session)
        yield session


async def get_principal_db(
    principal: Principal = Depends(require_active_principal),
) -> AsyncIterator[AsyncSession]:
    """One transaction per request with the principal's RLS context (``NO_POSTGRES`` without Postgres)."""
    if _sessionmaker is None and not _pg_enabled():
        yield NO_POSTGRES
        return
    async with get_sessionmaker()() as session, session.begin():
        await apply_db_role(session)
        await tenant_context(session, principal)
        yield session


def savepoint(session: Any) -> Any:
    """``async with savepoint(session):`` = ``session.begin_nested()`` on a SQL session (VM,
    unchanged; also a ``MemoryTx``) and no savepoint on the no-Postgres placeholder
    (``NO_POSTGRES`` / ``None``), where ``begin_nested`` raises. The Firestore writes made inside
    are their own transactions there (the rule of ``core_store.idempotent_firestore`` and
    ``learning.certificates.savepoint``)."""
    import contextlib

    return contextlib.nullcontext() if no_sql_session(session) else session.begin_nested()


@asynccontextmanager
async def job_session(job: str) -> AsyncIterator[Any]:
    """A background job's transaction in the named system context.

    With Postgres (VM): ``get_sessionmaker()`` + ``begin()`` and ``await system_context(...)``
    for the whole transaction, exactly what the jobs did inline. Without Postgres (Firebase
    stack, same test as ``get_db``): the ``NO_POSTGRES`` placeholder the routes get, inside
    ``system_context`` (platform ``rls_scope``); the modules then use their Firestore
    repositories, which commit their own writes."""
    if _sessionmaker is None and not _pg_enabled():
        async with system_context(NO_POSTGRES, job):
            yield NO_POSTGRES
        return
    async with get_sessionmaker()() as session, session.begin():
        await system_context(session, job)
        yield session


# scope="function": commit/rollback runs before the response is sent (FastAPI >= 0.121).
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]
PrincipalDbSession = Annotated[AsyncSession, Depends(get_principal_db, scope="function")]
