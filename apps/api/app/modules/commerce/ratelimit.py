"""Per-endpoint rate limits for commerce and entitlement routes (API §1.11, backlog A-7).

Redis fixed windows on the cache cluster approximating the spec's token buckets: each rule is
``(name, limit, window_s)`` keyed by user (or client IP for the webhook sanity limit). A breach
answers ``429 rate_limited`` with ``Retry-After``. A Redis outage fails **open** (logged): the
limits are abuse brakes, while money paths stay protected by idempotency keys, signatures and
server-side re-fetches. The counting itself lives in ``app.core.ratelimit``; this module keeps the
commerce limit table and the FastAPI dependency.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, Request

from app.core import ratelimit as core_rl
from app.core.auth import require_active_principal
from app.core.principal import Principal
from app.core.ratelimit import DAY, MIN, Rule

__all__ = [
    "DAY",
    "LIMITS",
    "MIN",
    "WEBHOOK_INVALID_PER_IP",
    "Rule",
    "hit",
    "limit",
    "webhook_invalid_signature_hit",
]

# API §17.2 / §19.2 "Rate limit" column.
LIMITS: dict[str, tuple[Rule, ...]] = {
    "com03_quote": (Rule(30, MIN),),  # also the coupon-validation path
    "com04_order": (Rule(10, MIN), Rule(30, DAY)),
    "com05_order_status": (Rule(20, MIN),),
    "com06_confirm": (Rule(10, MIN),),
    "com09_subscription": (Rule(5, DAY),),
    "com10_subscription_confirm": (Rule(10, MIN),),
    "com12_cancel": (Rule(5, DAY),),
    "com14_change_plan": (Rule(5, DAY),),
    "com18_refund_request": (Rule(3, DAY),),
    "com37_gst_export": (Rule(10, DAY),),
    "com46_reconciliation": (Rule(5, DAY),),
    "ent01_check": (Rule(300, MIN),),
    "ent02_check_batch": (Rule(60, MIN),),
    "ent06_grant": (Rule(20, DAY),),
}

# WH-01 per-IP sanity limit. It only applies to requests whose signature does NOT verify:
# a valid signed event is never dropped (Razorpay retries bursts from shared egress IPs).
WEBHOOK_INVALID_PER_IP = Rule(60, MIN)


async def hit(key: str, rules: tuple[Rule, ...]) -> None:
    """Count one request for ``key`` against every rule; raise ``429`` when one is exceeded.

    Delegates to the shared limiter ``app.core.ratelimit`` (same keys, windows and headers)."""
    await core_rl.hit(key, rules, scope="user")


def limit(name: str) -> Callable[..., Awaitable[Principal]]:
    """FastAPI dependency: per-user limit for route ``name`` (returns the principal)."""
    if name not in LIMITS:
        raise KeyError(name)

    async def dep(request: Request, principal: Principal = Depends(require_active_principal)) -> Principal:
        await hit(f"{name}:u:{principal.user_id}", LIMITS[name])
        return principal

    dep.__name__ = f"rate_limit_{name}"
    return dep


async def webhook_invalid_signature_hit(ip: str | None) -> None:
    await hit(f"wh_invalid:ip:{ip or 'unknown'}", (WEBHOOK_INVALID_PER_IP,))
