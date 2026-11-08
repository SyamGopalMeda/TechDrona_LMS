"""Per-endpoint rate limits for the attempt routes (api-specification §15.2 "Rate limit" column, BE-09).

Redis fixed windows on the cache cluster via the shared ``app.core.ratelimit``: a breach answers
``429 rate_limited`` with ``Retry-After``. A Redis outage fails **open** (logged): these limits are
abuse brakes; attempt integrity is protected by the server timer, session binding, idempotency
keys and ``client_seq``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Request

from app.core import ratelimit as core_rl
from app.core.auth import require_active_principal
from app.core.principal import Principal

MIN, HOUR = core_rl.MIN, core_rl.HOUR


@dataclass(frozen=True, slots=True)
class Rule:
    limit: int
    window_s: int
    per_attempt: bool = False


# api-specification §15.2. ATT-06 "30/min per attempt (burst 10)" is approximated by a fixed
# 1-minute window of 30 per attempt.
LIMITS: dict[str, Rule] = {
    "att01_start": Rule(10, MIN),
    "att02_state": Rule(30, MIN),
    "att03_resume": Rule(10, MIN),
    "att05_rebind": Rule(5, HOUR),
    "att06_autosave": Rule(30, MIN, per_attempt=True),
    "att07_time": Rule(4, MIN),
    "att10_submit": Rule(5, MIN),
}


async def hit(key: str, rule: Rule) -> None:
    """Count one request for ``key``; raise ``429 rate_limited`` once ``rule`` is exceeded.

    Delegates to the shared limiter ``app.core.ratelimit`` (keys stay under ``rl:asm:``)."""
    await core_rl.hit(f"asm:{key}", (core_rl.Rule(rule.limit, rule.window_s),), scope="user")


def limit(name: str) -> Callable[..., Awaitable[None]]:
    """FastAPI dependency: the §15.2 limit for route ``name`` (per user, or per attempt)."""
    if name not in LIMITS:
        raise KeyError(name)

    async def dep(request: Request, principal: Principal = Depends(require_active_principal)) -> None:
        rule = LIMITS[name]
        scope = f"u:{principal.user_id}"
        if rule.per_attempt:
            scope = f"a:{request.path_params.get('attempt_id')}:{scope}"
        await hit(f"{name}:{scope}", rule)

    dep.__name__ = f"rate_limit_{name}"
    return dep
