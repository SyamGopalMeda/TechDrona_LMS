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

from collections.abc import AsyncIterator, Iterable
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


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
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

_GUC_SQL = text(
    "SELECT set_config('app.user_id', :uid, true), set_config('app.org_ids', :orgs, true), "
    "set_config('app.is_platform', :plat, true), set_config('app.actor', :actor, true), "
    "set_config('app.roles', :roles, true), set_config('app.privacy_tier', :ptier, true)"
)


async def apply_db_role(session: AsyncSession) -> None:
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

    __slots__ = ("_job", "_prev", "_session")

    def __init__(self, session: AsyncSession, job: str) -> None:
        if not job or not job.replace("_", "").replace(".", "").replace("-", "").isalnum():
            raise ValueError("system job name must be a plain identifier")
        self._session = session
        self._job = job
        self._prev: tuple[str, ...] | None = None

    async def _enter(self) -> None:
        await set_rls_context(self._session, is_platform=True, actor=f"system:{self._job}")

    def __await__(self) -> Any:
        return self._enter().__await__()

    async def __aenter__(self) -> AsyncSession:
        row = (await self._session.execute(_READ_GUC_SQL)).one()
        self._prev = tuple("" if v is None else str(v) for v in row)
        await self._enter()
        return self._session

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
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


async def get_db() -> AsyncIterator[AsyncSession]:
    """One transaction per request with an empty RLS context (public routes).

    Use through ``DbSession`` so the commit happens before the response is sent.
    """
    async with get_sessionmaker()() as session, session.begin():
        await apply_db_role(session)
        await set_rls_context(session)
        yield session


async def get_principal_db(
    principal: Principal = Depends(require_active_principal),
) -> AsyncIterator[AsyncSession]:
    """One transaction per request with the principal's RLS context."""
    async with get_sessionmaker()() as session, session.begin():
        await apply_db_role(session)
        await tenant_context(session, principal)
        yield session


# scope="function": commit/rollback runs before the response is sent (FastAPI >= 0.121).
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]
PrincipalDbSession = Annotated[AsyncSession, Depends(get_principal_db, scope="function")]
