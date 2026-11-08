from __future__ import annotations

from redis.asyncio import Redis


async def test_live(client) -> None:
    r = await client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_ready_checks_db_and_redis(client) -> None:
    r = await client.get("/api/v1/health/ready")
    body = r.json()
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis_cache"] == "ok", "is the docker-compose redis cache running?"
    assert r.status_code == 200


async def test_ready_503_when_redis_down(client, monkeypatch) -> None:
    import app.core.health as health

    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2, socket_timeout=0.2)
    monkeypatch.setattr(health, "get_cache_redis", lambda: dead)
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["redis_cache"] == "fail"
    await dead.aclose()
