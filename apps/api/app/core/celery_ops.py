"""Celery process operations: beat leader lock (COM-14) and worker liveness file (E2E-06).

Beat leader lock (ADR-0008, deployment-and-operations "single scheduler replica with a Redis
leader lock"): on ``beat_init`` the scheduler takes ``td:scheduler:leader`` on the queue Redis
with ``SET NX PX``. A second scheduler (rolling deploy, accidental scale-out) waits in standby
until the key is free, so periodic jobs never fire twice. The leader renews the key every
``ttl/3``; if a renewal finds the key gone or owned by someone else the process exits, and the
orchestrator restarts it into standby. The key is released on clean shutdown.

Worker liveness: a bootstep touches ``TD_WORKER_HEALTH_FILE`` from the worker's own timer
(the consumer's event loop), so the container healthcheck is a cheap ``mtime`` test instead of
spawning a ``celery inspect ping`` client every 30 s.
"""

from __future__ import annotations

import atexit
import os
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

import structlog

log = structlog.get_logger("app.celery_ops")

LEADER_KEY = "td:scheduler:leader"

# Renew / release only when we still own the key (compare-and-act in one round trip).
_RENEW_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"
)
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
)


class _SyncRedis(Protocol):
    def set(self, name: str, value: str, *, nx: bool = ..., px: int | None = ...) -> Any: ...
    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...


def leader_token() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def try_acquire(client: _SyncRedis, token: str, ttl_ms: int, key: str = LEADER_KEY) -> bool:
    return bool(client.set(key, token, nx=True, px=ttl_ms))


def renew(client: _SyncRedis, token: str, ttl_ms: int, key: str = LEADER_KEY) -> bool:
    return bool(client.eval(_RENEW_LUA, 1, key, token, ttl_ms))


def release(client: _SyncRedis, token: str, key: str = LEADER_KEY) -> bool:
    return bool(client.eval(_RELEASE_LUA, 1, key, token))


class BeatLeaderLock:
    """Blocking acquire + background renewal for one beat process."""

    def __init__(
        self,
        client: _SyncRedis,
        ttl_seconds: int,
        *,
        key: str = LEADER_KEY,
        on_lost: Any = None,
        poll_seconds: float | None = None,
    ) -> None:
        self.client = client
        self.key = key
        self.ttl_ms = int(ttl_seconds * 1000)
        self.token = leader_token()
        self.poll = poll_seconds if poll_seconds is not None else max(1.0, ttl_seconds / 3)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_lost = on_lost or (lambda: os._exit(3))

    def acquire_blocking(self, max_wait: float | None = None) -> bool:
        start = time.monotonic()
        waiting_logged = False
        while not self._stop.is_set():
            try:
                if try_acquire(self.client, self.token, self.ttl_ms, self.key):
                    log.info("scheduler_leader_acquired", key=self.key)
                    return True
            except Exception as e:  # broker down: keep waiting, never run unlocked
                log.warning("scheduler_leader_lock_error", error=type(e).__name__)
            if not waiting_logged:
                log.info("scheduler_standby", key=self.key)
                waiting_logged = True
            if max_wait is not None and time.monotonic() - start >= max_wait:
                return False
            self._stop.wait(self.poll)
        return False

    def _renew_loop(self) -> None:
        while not self._stop.wait(self.poll):
            try:
                ok = renew(self.client, self.token, self.ttl_ms, self.key)
            except Exception as e:
                log.warning("scheduler_leader_renew_error", error=type(e).__name__)
                continue  # transient: the TTL covers ~3 missed renewals
            if not ok:
                log.error("scheduler_leader_lost", key=self.key)
                self._on_lost()
                return

    def start_renewal(self) -> None:
        self._thread = threading.Thread(target=self._renew_loop, name="beat-leader-renew", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            release(self.client, self.token, self.key)
        except Exception as e:
            log.warning("scheduler_leader_release_error", error=type(e).__name__)


def install_beat_leader_lock() -> None:
    """Connect ``beat_init``: block until this beat holds the leader lock (if enabled)."""
    from celery.signals import beat_init

    from app.core.config import get_settings

    @beat_init.connect(weak=False)
    def _take_leadership(sender: Any = None, **_kw: Any) -> None:
        s = get_settings()
        if not s.TD_SCHEDULER_LEADER_LOCK_ENABLED:
            log.warning("scheduler_leader_lock_disabled")
            return
        import redis

        client = redis.Redis.from_url(s.REDIS_QUEUE_URL, socket_timeout=5, socket_connect_timeout=5)
        lock = BeatLeaderLock(client, s.TD_SCHEDULER_LEADER_LOCK_TTL_SECONDS)
        lock.acquire_blocking()
        lock.start_renewal()
        atexit.register(lock.stop)


# --------------------------------------------------------------------------- worker liveness


def health_file_path(configured: str = "") -> Path:
    return Path(configured or os.path.join(tempfile.gettempdir(), "td-celery-worker.alive"))


def touch(path: Path) -> None:
    try:
        path.touch()
    except OSError as e:  # never let liveness bookkeeping break the worker
        log.warning("worker_health_touch_failed", error=type(e).__name__)


def is_fresh(path: Path, max_age_seconds: float) -> bool:
    try:
        return time.time() - path.stat().st_mtime < max_age_seconds
    except OSError:
        return False


def install_worker_health(capp: Any) -> None:
    """Add a bootstep that touches the liveness file from the worker's timer."""
    from celery import bootsteps

    from app.core.config import get_settings

    s = get_settings()
    path = health_file_path(s.TD_WORKER_HEALTH_FILE)
    interval = s.TD_WORKER_HEALTH_INTERVAL_SECONDS

    class WorkerHealthFile(bootsteps.StartStopStep):
        requires = {"celery.worker.components:Timer"}

        def __init__(self, worker: Any, **kw: Any) -> None:
            self.tref: Any = None

        def start(self, worker: Any) -> None:
            touch(path)
            self.tref = worker.timer.call_repeatedly(interval, touch, (path,), priority=10)

        def stop(self, worker: Any) -> None:
            if self.tref is not None:
                self.tref.cancel()
            try:
                path.unlink()
            except OSError:
                pass

    capp.steps["worker"].add(WorkerHealthFile)
