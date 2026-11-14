"""Per-request locks on Firestore: the ``pg_advisory_xact_lock`` replacement (MIGRATION-PLAN §1.9).

``pg_advisory_xact_lock(k)`` blocks until the lock is free and holds it until the request's
transaction ends. Firestore has no such lock, so::

    from app.core import request_locks
    await request_locks.acquire(f"sess:{user_id}")      # e.g. sessions.lock_user on Firestore

claims the lease document ``lms_locks/{key}`` (``ScopedStore.claim_lease``) for this request,
waiting with jittered backoff up to ``wait_s`` (then ``503 service_unavailable`` +
``Retry-After: 1``, like a lock wait hitting ``statement_timeout``). The lease is released when
the request ends: ``RequestContextMiddleware`` opens a scope per HTTP request and calls
``release_scope`` in its ``finally``. Outside a request (jobs, tests) use
``async with request_locks.scope(): ...``. A crashed instance can't leak a lock for longer than
``ttl`` (default 30 s, the lease expiry). Re-acquiring a key already held in the same scope is a
no-op (advisory locks are re-entrant within a session).

Pure Python until a lock is actually taken: a request that takes none costs nothing (the VM
default never imports the Firestore client here).
"""

from __future__ import annotations

import asyncio
import contextvars
import random
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import structlog

log = structlog.get_logger("app.request_locks")

DEFAULT_TTL = timedelta(seconds=30)
DEFAULT_WAIT_S = 10.0
_JOB = "core.request_lock"


@dataclass
class LockScope:
    holder: str = field(default_factory=lambda: f"req:{uuid.uuid4().hex}")
    keys: list[str] = field(default_factory=list)
    store: Any = None


_current: contextvars.ContextVar[LockScope | None] = contextvars.ContextVar("td_request_locks", default=None)


def begin_scope() -> contextvars.Token[LockScope | None]:
    """Open a lock scope for the current request (the holder object is shared by reference, so
    locks taken in copied contexts -- threadpool dependencies -- are still released)."""
    return _current.set(LockScope())


async def release_scope(token: contextvars.Token[LockScope | None]) -> None:
    sc = _current.get()
    _current.reset(token)
    if sc is not None and sc.keys:
        await _release(sc)


async def _release(sc: LockScope) -> None:
    store = sc.store or _store()
    for key in reversed(sc.keys):
        try:
            await store.release_lease(key, sc.holder)
        except Exception as e:  # the lease expires anyway
            log.warning("request_lock_release_failed", key=key.split(":", 1)[0], error=type(e).__name__)
    sc.keys.clear()


@asynccontextmanager
async def scope(store: Any = None) -> AsyncIterator[LockScope]:
    """Explicit scope (jobs/tests); releases every lock taken inside on exit."""
    token = _current.set(LockScope(store=store))
    try:
        sc = _current.get()
        assert sc is not None
        yield sc
    finally:
        await release_scope(token)


def _store() -> Any:
    from app.core.firestore.store import ScopedStore

    return ScopedStore.system(_JOB)


async def acquire(key: str, *, ttl: timedelta = DEFAULT_TTL, wait_s: float = DEFAULT_WAIT_S) -> None:
    """Block until ``key`` is held by the current scope (see module docstring)."""
    from app.core.errors import ProblemError

    sc = _current.get()
    if sc is None:
        raise RuntimeError("request_locks.acquire() outside a request scope; use `async with scope()`")
    if key in sc.keys:
        return
    store = sc.store or _store()
    deadline = time.monotonic() + wait_s
    attempt = 0
    while True:
        if await store.claim_lease(key, sc.holder, ttl):
            sc.keys.append(key)
            return
        attempt += 1
        if time.monotonic() >= deadline:
            log.warning("request_lock_timeout", key=key.split(":", 1)[0])
            raise ProblemError("service_unavailable", headers={"Retry-After": "1"})
        await asyncio.sleep(min(0.5, 0.02 * 2**attempt) * (0.5 + random.random()))  # noqa: S311


def held_keys() -> tuple[str, ...]:
    sc = _current.get()
    return tuple(sc.keys) if sc else ()
