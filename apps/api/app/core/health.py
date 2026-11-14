"""Health endpoints (public): liveness and readiness (DB + Redis cache).

Without Postgres (``runtime.postgres_enabled()`` False, the Firebase stack) the ``database``
check pings Firestore and ``redis_cache`` pings the Firestore cache facade; same response shape.

``/healthz`` (root, outside ``/api/v1``) is a liveness alias for docker/ECS/ALB healthchecks."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.redis import get_cache_redis
from app.core.routing import public_router

router = public_router(prefix="/health", tags=["health"])
healthz_router = public_router(tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@healthz_router.get("/healthz", include_in_schema=False)
async def healthz() -> JSONResponse:
    """Liveness only (no dependencies) so a DB/Redis blip never kills healthy tasks."""
    return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})


async def _check_db() -> bool:
    from app.core.runtime import postgres_enabled

    if not postgres_enabled():  # Firebase stack: the database is Firestore
        try:
            from app.core.firestore.kv import FirestoreRedis

            return bool(await asyncio.wait_for(FirestoreRedis().ping(), timeout=2))
        except Exception:
            return False
    try:
        async with get_sessionmaker()() as s:
            await asyncio.wait_for(s.execute(text("SELECT 1")), timeout=2)
        return True
    except Exception:
        return False


async def _check_redis() -> bool:
    try:
        return bool(await asyncio.wait_for(get_cache_redis().ping(), timeout=2))
    except Exception:
        return False


@router.get("/ready")
async def ready() -> JSONResponse:
    db_ok, redis_ok = await asyncio.gather(_check_db(), _check_redis())
    ok = db_ok and redis_ok
    body: dict[str, Any] = {
        "status": "ok" if ok else "unavailable",
        "checks": {"database": "ok" if db_ok else "fail", "redis_cache": "ok" if redis_ok else "fail"},
        "release": get_settings().TD_RELEASE,
    }
    return JSONResponse(body, status_code=200 if ok else 503, headers={"Cache-Control": "no-store"})
