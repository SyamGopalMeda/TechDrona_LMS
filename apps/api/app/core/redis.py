"""Redis clients: ``cache`` cluster (allkeys-lru) and ``queue`` cluster (noeviction)."""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import get_settings

_cache: Redis | None = None
_queue: Redis | None = None


def get_cache_redis() -> Redis:
    global _cache
    if _cache is None:
        _cache = Redis.from_url(get_settings().REDIS_CACHE_URL, socket_timeout=2, socket_connect_timeout=2)
    return _cache


def get_queue_redis() -> Redis:
    global _queue
    if _queue is None:
        _queue = Redis.from_url(get_settings().REDIS_QUEUE_URL, socket_timeout=2, socket_connect_timeout=2)
    return _queue


async def close_redis() -> None:
    global _cache, _queue
    for client in (_cache, _queue):
        if client is not None:
            await client.aclose()
    _cache = None
    _queue = None
