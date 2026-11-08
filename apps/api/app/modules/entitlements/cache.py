"""60-second entitlement decision cache (API §19.1, backlog A-7).

Keys live on the Redis cache cluster:

* ``ent:ver:{user_id}`` — the user's entitlement-set version, ``INCR``-ed on every entitlement
  change: inside the changing transaction (``record_event``), again **immediately after that
  transaction commits** (``bump_after_commit``, a SQLAlchemy ``after_commit`` hook — COM-21),
  and once more by the outbox handler for every ``entitlement.*`` event. A reader that raced
  the uncommitted change (new version + old rows) caches under a version that the post-commit
  bump retires at once, so a revoke is never served from cache after it has committed, even
  when the outbox relay is down.
* ``ent:dec:{user_id}:v{n}:{principal_fp}:{type}:{id}`` — a cached **allow** decision, TTL
  ``min(60 s, until the winning entitlement ends)``.

Only positive decisions are cached: a denial is re-evaluated every time, so a purchase,
manual grant is visible immediately even before the post-commit invalidation.
Restriction (L3+/locks) and free-content checks run before the cache (principal-only, no
DB) and are never cached. A Redis outage falls back to the database (fail open to the
uncached, authoritative evaluation).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import uuid
from datetime import datetime
from typing import Any

import structlog

from app.core.access import AccessDecision
from app.core.principal import Principal
from app.core.time import utcnow

log = structlog.get_logger("entitlements.cache")

TTL_SECONDS = 60
EVENT_TYPES = (
    "granted",
    "extended",
    "entered_grace",
    "restored",
    "suspended",
    "expired",
    "revoked",
    "quota_consumed",
    "quota_credited",
    "fp_extension",
    "plan_changed",
)

_enabled = True


def set_enabled(on: bool) -> None:
    """Kill switch (tests / incident response)."""
    global _enabled
    _enabled = on


def _redis() -> Any:
    from app.core.redis import get_cache_redis

    return get_cache_redis()


def _ver_key(user_id: uuid.UUID) -> str:
    return f"ent:ver:{user_id}"


def principal_fingerprint(p: Principal) -> str:
    """Grants and org memberships influence the staff-preview decision."""
    raw = json.dumps(
        {
            "g": sorted(f"{g.role}|{g.scope_type}|{g.scope_id}" for g in p.grants),
            "o": sorted(str(o) for o in p.org_ids),
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def version(user_id: uuid.UUID) -> int | None:
    try:
        v = await _redis().get(_ver_key(user_id))
    except Exception as e:
        log.warning("entitlement_cache_unavailable", error=type(e).__name__)
        return None
    return int(v) if v is not None else 0


async def bump(user_id: uuid.UUID) -> None:
    try:
        r = _redis()
        pipe = r.pipeline()
        pipe.incr(_ver_key(user_id))
        pipe.expire(_ver_key(user_id), 7 * 86_400)
        await pipe.execute()
    except Exception as e:
        log.warning("entitlement_cache_bump_failed", error=type(e).__name__)


_PENDING_KEY = "entitlements.cache.bump_user_ids"
_tasks: set[asyncio.Task[None]] = set()


def _after_commit(sync_session: Any) -> None:
    ids: set[uuid.UUID] = sync_session.info.pop(_PENDING_KEY, set())
    if not ids:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no loop (sync use): the outbox handler still bumps
        return
    for uid in ids:
        t = loop.create_task(bump(uid))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)


def _after_rollback(sync_session: Any) -> None:
    sync_session.info.pop(_PENDING_KEY, None)


def bump_after_commit(session: Any, user_id: uuid.UUID) -> None:
    """Schedule a version bump for ``user_id`` right after ``session`` commits (COM-21)."""
    from sqlalchemy import event

    sync = getattr(session, "sync_session", session)
    pending: set[uuid.UUID] | None = sync.info.get(_PENDING_KEY)
    if pending is None:
        pending = sync.info[_PENDING_KEY] = set()
        if not event.contains(sync, "after_commit", _after_commit):
            event.listen(sync, "after_commit", _after_commit)
            event.listen(sync, "after_soft_rollback", _after_soft_rollback)
    pending.add(user_id)


def _after_soft_rollback(sync_session: Any, previous_transaction: Any) -> None:
    if previous_transaction.parent is None:  # outermost rollback: nothing was committed
        _after_rollback(sync_session)


async def drain_pending_bumps() -> None:
    """Await scheduled post-commit bumps (tests / graceful shutdown)."""
    if _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


def _key(p: Principal, ver: int, rtype: str, rid: uuid.UUID) -> str:
    return f"ent:dec:{p.user_id}:v{ver}:{principal_fingerprint(p)}:{rtype}:{rid}"


async def get(p: Principal, ver: int, rtype: str, rid: uuid.UUID) -> AccessDecision | None:
    try:
        raw = await _redis().get(_key(p, ver, rtype, rid))
    except Exception:
        return None
    if raw is None:
        return None
    d = json.loads(raw)
    exp = datetime.fromisoformat(d["expires_at"]) if d.get("expires_at") else None
    if exp is not None and exp <= utcnow():
        return None
    return AccessDecision(bool(d["allowed"]), str(d["reason"]), tuple(uuid.UUID(x) for x in d["ids"]), exp)


async def put(p: Principal, ver: int, rtype: str, rid: uuid.UUID, dec: AccessDecision) -> None:
    if not dec.allowed:
        return
    ttl = TTL_SECONDS
    if dec.expires_at is not None:
        ttl = min(ttl, math.floor((dec.expires_at - utcnow()).total_seconds()))
    if ttl < 1:
        return
    body = json.dumps(
        {
            "allowed": dec.allowed,
            "reason": dec.reason,
            "ids": [str(x) for x in dec.entitlement_ids],
            "expires_at": dec.expires_at.isoformat() if dec.expires_at else None,
        }
    )
    try:
        await _redis().set(_key(p, ver, rtype, rid), body, ex=ttl)
    except Exception as e:
        log.warning("entitlement_cache_put_failed", error=type(e).__name__)


def enabled() -> bool:
    return _enabled
