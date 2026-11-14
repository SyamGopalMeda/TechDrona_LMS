"""Runtime switches: defaults keep the VM stack; TD_RUNTIME=firebase flips cache + tasks."""

from __future__ import annotations

import pytest

from app.core import ratelimit, runtime


def test_defaults_are_the_vm_stack(settings_env: pytest.MonkeyPatch) -> None:
    for k in ("TD_RUNTIME", "TD_CACHE_BACKEND", "TD_TASKS_BACKEND"):
        settings_env.delenv(k, raising=False)
    from app.core.config import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert (s.TD_RUNTIME, s.TD_CACHE_BACKEND, s.TD_TASKS_BACKEND) == ("vm", "", "")


def test_vm_runtime_uses_redis_and_celery(settings_env: pytest.MonkeyPatch) -> None:
    settings_env.setenv("TD_RUNTIME", "vm")
    settings_env.setenv("TD_CACHE_BACKEND", "")
    settings_env.setenv("TD_TASKS_BACKEND", "")
    assert runtime.cache_backend() == "redis"
    assert runtime.tasks_backend() == "celery"
    assert not runtime.is_firebase()
    assert isinstance(ratelimit.default_backend(), ratelimit.RedisBackend)


def test_firebase_runtime_defaults(settings_env: pytest.MonkeyPatch) -> None:
    settings_env.setenv("TD_RUNTIME", "firebase")
    settings_env.setenv("TD_CACHE_BACKEND", "")
    settings_env.setenv("TD_TASKS_BACKEND", "")
    assert runtime.cache_backend() == "firestore"
    assert runtime.tasks_backend() == "cloudtasks"
    from app.core.firestore.kv import FirestoreRateLimitBackend

    assert isinstance(ratelimit.default_backend(), FirestoreRateLimitBackend)


def test_explicit_backend_wins(settings_env: pytest.MonkeyPatch) -> None:
    settings_env.setenv("TD_RUNTIME", "firebase")
    settings_env.setenv("TD_CACHE_BACKEND", "redis")
    settings_env.setenv("TD_TASKS_BACKEND", "celery")
    assert runtime.cache_backend() == "redis"
    assert runtime.tasks_backend() == "celery"


def test_cloud_task_queue_map(settings_env: pytest.MonkeyPatch) -> None:
    settings_env.delenv("TD_CLOUD_TASKS_QUEUES", raising=False)
    assert runtime.cloud_task_queues() == {
        "critical": "lmsTasksCritical",
        "default": "lmsTasks",
        "maintenance": "lmsTasksMaintenance",
    }


async def test_redis_getter_returns_firestore_facade_only_when_switched(
    settings_env: pytest.MonkeyPatch,
) -> None:
    from app.core import redis as core_redis
    from app.core.firestore.kv import FirestoreRedis

    await core_redis.close_redis()
    settings_env.setenv("TD_CACHE_BACKEND", "firestore")
    assert isinstance(core_redis.get_cache_redis(), FirestoreRedis)
    await core_redis.close_redis()
    settings_env.setenv("TD_CACHE_BACKEND", "redis")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    from redis.asyncio import Redis

    assert isinstance(core_redis.get_cache_redis(), Redis)
    await core_redis.close_redis()
