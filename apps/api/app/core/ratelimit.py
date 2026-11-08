"""Shared per-endpoint rate limits (API §1.11 "Rate limit" column; SEC-02, SEC-03, BE-09).

Fixed windows approximating the spec's token buckets. A rule is ``Rule(limit, window_s)``;
``hit(key, rules)`` counts one request for ``key`` against every rule and raises
``429 rate_limited`` (``Retry-After``, ``RateLimit-Policy``) when one is exceeded.

* Backend: Redis cache cluster (``INCR`` + ``EXPIRE`` in one pipeline). A Redis outage fails
  **open** (logged): limits are abuse brakes; credentials stay protected by the DB-backed
  login back-off and OTP attempt counters.
* Keys never contain raw identifiers: callers pass a client IP, a principal id, or an HMAC
  digest of a contact (``identifier_digest``).
* Tests swap the backend with ``set_backend(MemoryBackend())`` so runs are isolated from the
  shared Redis and from each other.

Modules keep their own limit tables and call ``hit``/``check``: ``commerce.ratelimit``,
``assessments.ratelimit`` and ``analytics.service.enforce_rate_limits`` delegate here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from app.core.errors import ProblemError

log = structlog.get_logger("app.ratelimit")

MIN, HOUR, DAY = 60, 3_600, 86_400


@dataclass(frozen=True, slots=True)
class Rule:
    limit: int
    window_s: int


class Backend(Protocol):
    async def incr(self, keys: list[tuple[str, int]]) -> list[int]:
        """Increment each key (creating it with the given TTL seconds); return new counts."""
        ...

    async def peek(self, keys: list[str]) -> list[int]: ...


class RedisBackend:
    async def incr(self, keys: list[tuple[str, int]]) -> list[int]:
        from app.core.redis import get_cache_redis

        pipe = get_cache_redis().pipeline()
        for k, ttl in keys:
            pipe.incr(k)
            pipe.expire(k, ttl + 1)
        res = await pipe.execute()
        return [int(res[2 * i]) for i in range(len(keys))]

    async def peek(self, keys: list[str]) -> list[int]:
        from app.core.redis import get_cache_redis

        vals = await get_cache_redis().mget(keys)
        return [int(v) if v is not None else 0 for v in vals]


@dataclass
class MemoryBackend:
    """Process-local backend (tests, single-process tools). Windows expire lazily."""

    counts: dict[str, tuple[int, float]] = field(default_factory=dict)

    def _get(self, k: str) -> int:
        n, exp = self.counts.get(k, (0, 0.0))
        return n if exp > time.time() else 0

    async def incr(self, keys: list[tuple[str, int]]) -> list[int]:
        out = []
        now = time.time()
        for k, ttl in keys:
            n = self._get(k) + 1
            self.counts[k] = (n, now + ttl)
            out.append(n)
        return out

    async def peek(self, keys: list[str]) -> list[int]:
        return [self._get(k) for k in keys]


_backend: Backend = RedisBackend()


def set_backend(backend: Backend | None) -> Backend:
    """Install a backend (``None`` restores Redis); returns the previous one."""
    global _backend
    prev = _backend
    _backend = backend if backend is not None else RedisBackend()
    return prev


def get_backend() -> Backend:
    return _backend


def _windows(key: str, rules: tuple[Rule, ...]) -> list[tuple[str, Rule, int]]:
    now = int(time.time())
    return [(f"rl:{key}:{r.window_s}:{now // r.window_s}", r, r.window_s - now % r.window_s) for r in rules]


def _problem(r: Rule, ttl: int, scope: str) -> ProblemError:
    wait = max(1, ttl)
    return ProblemError(
        "rate_limited",
        detail="Too many requests. Please wait and try again.",
        headers={
            "Retry-After": str(wait),
            "RateLimit-Policy": f'"{scope}";q={r.limit};w={r.window_s}',
            "RateLimit": f'"{scope}";r=0;t={wait}',
        },
        retry_after_seconds=wait,
    )


async def check(key: str, rules: tuple[Rule, ...], *, scope: str = "default") -> ProblemError | None:
    """Count one request; return the ``429`` problem when a rule is exceeded (else ``None``).

    Use the returned form where the handler must still commit (e.g. failure counters)."""
    windows = _windows(key, rules)
    try:
        counts = await _backend.incr([(k, ttl) for k, _r, ttl in windows])
    except Exception as e:  # backend outage: fail open
        log.warning("rate_limit_unavailable", key=key.split(":", 1)[0], error=type(e).__name__)
        return None
    for (_k, r, ttl), n in zip(windows, counts, strict=True):
        if n > r.limit:
            return _problem(r, ttl, scope)
    return None


async def hit(key: str, rules: tuple[Rule, ...], *, scope: str = "default") -> None:
    """Count one request for ``key``; raise ``429 rate_limited`` when a rule is exceeded."""
    problem = await check(key, rules, scope=scope)
    if problem is not None:
        raise problem


async def exhausted(key: str, rules: tuple[Rule, ...]) -> bool:
    """True when ``key`` already used up a rule's window (does not count a request)."""
    windows = _windows(key, rules)
    try:
        counts = await _backend.peek([k for k, _r, _ttl in windows])
    except Exception as e:
        log.warning("rate_limit_unavailable", key=key.split(":", 1)[0], error=type(e).__name__)
        return False
    return any(n >= r.limit for (_k, r, _ttl), n in zip(windows, counts, strict=True))
