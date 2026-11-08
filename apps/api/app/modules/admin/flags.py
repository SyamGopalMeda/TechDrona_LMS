"""Feature-flag evaluation (FR-ADM-003, ADM-17).

* ``evaluate`` — the single rule: the user allowlist first, then ``is_enabled``, then the
  percentage rollout (0 % means off for everyone, anonymous callers are only in a 100 % rollout).
  Single company (admin_0004): there is no organization allowlist; ``org_id`` arguments are
  accepted for old callers and ignored.
* ``flag_enabled(session, key, ...)`` — in-transaction read (``admin.router.flag_enabled``).
* ``cached_flag_enabled(key, ...)`` — for callers without a DB session (core middleware such as
  ``platform.maintenance_mode``): reads ``feature_flags`` (RLS NONE) in its own short
  transaction and keeps the row for ``CACHE_TTL_S`` seconds per process. A PATCH clears this
  process's cache at once; other processes pick the change up within ``CACHE_TTL_S``.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.modules.admin.models import FeatureFlag

CACHE_TTL_S = 30.0


@dataclass(frozen=True)
class FlagSnapshot:
    is_enabled: bool
    rollout_percent: int
    user_allowlist: frozenset[uuid.UUID]

    @classmethod
    def of(cls, f: FeatureFlag) -> FlagSnapshot:
        return cls(
            bool(f.is_enabled),
            int(f.rollout_percent),
            frozenset(f.user_allowlist or ()),
        )


def evaluate(
    f: FlagSnapshot | None, *, user_id: uuid.UUID | None = None, org_id: uuid.UUID | None = None
) -> bool:
    del org_id
    if f is None:
        return False
    if user_id and user_id in f.user_allowlist:
        return True
    if not f.is_enabled:
        return False
    if f.rollout_percent >= 100:
        return True
    if user_id is None:  # a partial rollout never includes anonymous callers (0 % means off)
        return False
    return int(user_id.hex[-4:], 16) % 100 < f.rollout_percent


async def load(session: Any, key: str) -> FlagSnapshot | None:
    f = (await session.execute(select(FeatureFlag).where(FeatureFlag.flag_key == key))).scalar_one_or_none()
    return FlagSnapshot.of(f) if f is not None else None


async def flag_enabled(
    session: Any, key: str, *, user_id: uuid.UUID | None = None, org_id: uuid.UUID | None = None
) -> bool:
    return evaluate(await load(session, key), user_id=user_id, org_id=org_id)


_cache: dict[str, tuple[float, FlagSnapshot | None]] = {}


def invalidate(key: str | None = None) -> None:
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


async def cached_flag_enabled(
    key: str, *, user_id: uuid.UUID | None = None, org_id: uuid.UUID | None = None
) -> bool:
    hit = _cache.get(key)
    if hit is None or time.monotonic() - hit[0] >= CACHE_TTL_S:
        from app.core.db import get_sessionmaker

        async with get_sessionmaker()() as session, session.begin():
            snap = await load(session, key)
        hit = (time.monotonic(), snap)
        _cache[key] = hit
    return evaluate(hit[1], user_id=user_id, org_id=org_id)
