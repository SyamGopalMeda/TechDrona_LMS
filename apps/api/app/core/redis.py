"""Redis clients: ``cache`` cluster (allkeys-lru) and ``queue`` cluster (noeviction).

``TD_CACHE_BACKEND=firestore`` (default when ``TD_RUNTIME=firebase``, see ``app.core.runtime``)
returns a Redis-compatible facade over Firestore (``app.core.firestore.kv.FirestoreRedis``) from
both getters instead, so every caller works unchanged on Firebase where there is no Redis.
Default (``redis``): exactly the previous behaviour.
"""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

_cache: Any = None
_queue: Any = None


def _firestore_kv() -> Any:
    from app.core.runtime import cache_backend

    if cache_backend() != "firestore":
        return None
    from app.core.firestore.kv import FirestoreRedis

    return FirestoreRedis()


def get_cache_redis() -> Redis:
    global _cache
    if _cache is None:
        _cache = _firestore_kv() or Redis.from_url(
            get_settings().REDIS_CACHE_URL, socket_timeout=2, socket_connect_timeout=2
        )
    return _cache


def get_queue_redis() -> Redis:
    global _queue
    if _queue is None:
        _queue = _firestore_kv() or Redis.from_url(
            get_settings().REDIS_QUEUE_URL, socket_timeout=2, socket_connect_timeout=2
        )
    return _queue


async def close_redis() -> None:
    global _cache, _queue
    for client in (_cache, _queue):
        if client is not None:
            await client.aclose()
    _cache = None
    _queue = None
