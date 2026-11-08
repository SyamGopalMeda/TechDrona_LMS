"""FastAPI application factory.

Routers are auto-discovered: every ``app.modules.<name>.router`` module exposing
``router: APIRouter`` is included under ``/api/v1`` (``TD_ROUTER_SET=user``); a module may
also expose ``webhook_router`` (included for ``TD_ROUTER_SET=webhooks``). ``all`` mounts both
(local dev/tests). Modules never edit this file.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.core.config import Settings, get_settings
from app.core.db import dispose_engine
from app.core.errors import install_error_handlers
from app.core.health import healthz_router
from app.core.health import router as health_router
from app.core.logging import configure_logging
from app.core.middleware import (
    BodyLimitMiddleware,
    MaintenanceMiddleware,
    RequestContextMiddleware,
    ServiceAuthMiddleware,
)
from app.core.models_registry import _optional_import, import_all_models, module_names
from app.core.redis import close_redis
from app.core.startup_checks import run_startup_checks

API_PREFIX = "/api/v1"


def discover_routers(router_set: str) -> list[tuple[str, APIRouter]]:
    found: list[tuple[str, APIRouter]] = []
    for name in module_names():
        mod = _optional_import(f"app.modules.{name}.router")
        if mod is None:
            continue
        attrs = []
        if router_set in ("user", "all"):
            attrs.append("router")
        if router_set in ("webhooks", "all"):
            attrs.append("webhook_router")
        for attr in attrs:
            r = getattr(mod, attr, None)
            if isinstance(r, APIRouter):
                found.append((f"{name}.{attr}", r))
    return found


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    configure_logging(s.LOG_LEVEL, s.LOG_FORMAT, s.TD_SERVICE_NAME)
    # Module discovery first: modules register fake adapters / extension points at import
    # time, and the production safety gate must see them.
    import_all_models()
    routers = discover_routers(s.TD_ROUTER_SET)
    from app.wiring import wire_all

    wire_all()  # cross-module hooks + outbox handlers (same set as the Celery worker)
    run_startup_checks(s)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await dispose_engine()
        await close_redis()

    docs_off = s.TD_DISABLE_API_DOCS or s.is_production
    app = FastAPI(
        title="Tech Drona LMS API",
        version="1",
        lifespan=lifespan,
        docs_url=None if docs_off else f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=None if docs_off else f"{API_PREFIX}/openapi.json",
    )
    install_error_handlers(app)
    # Same-origin BFF model: no CORS middleware on purpose (browsers never call the API directly).
    # Starlette runs the last-added middleware first:
    # RequestContext -> ServiceAuth -> Maintenance -> BodyLimit.
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(MaintenanceMiddleware, api_prefix=API_PREFIX)
    app.add_middleware(ServiceAuthMiddleware)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(healthz_router)
    app.include_router(health_router, prefix=API_PREFIX)
    for _name, r in routers:
        app.include_router(r, prefix=API_PREFIX)
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> object:
    # ``uvicorn app.main:app`` — built lazily so importing this module has no side effects.
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
