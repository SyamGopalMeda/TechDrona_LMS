"""A-7: 60-second entitlement decision cache — hits, invalidation on entitlement changes
(in-transaction and via the ``entitlement.*`` outbox handler), negative decisions never
cached, TTL bounded by the entitlement end, restriction bypass and Redis-outage fallback."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from app.core.access import check_access
from app.core.db import system_context
from app.core.ids import uuid7
from app.core.outbox import OutboxMessage, handlers_for
from app.core.redis import get_cache_redis
from app.core.time import utcnow
from app.modules.entitlements import cache
from app.modules.entitlements import service as ent
from tests.commerce.factory import make_buyer, make_product, principal

SYS = ent.Actor.system("test")


async def _setup(db: Any, days: float = 30) -> tuple[uuid.UUID, uuid.UUID, Any]:
    uid = await make_buyer(db)
    course = uuid7()
    cat = await make_product(db, items=[{"item_type": "course", "course_id": course}])
    return uid, course, cat


async def _grant(db: Any, uid: uuid.UUID, cat: Any, *, ends_in: timedelta = timedelta(days=30)) -> Any:
    await system_context(db, "test")
    e, _ = await ent.grant(
        db,
        SYS,
        user_id=uid,
        source_type="admin_grant",
        product_id=cat.product.id,
        starts_at=utcnow() - timedelta(days=1),
        ends_at=utcnow() + ends_in,
        granted_by=uid,
    )
    return e


async def test_allow_is_cached_and_invalidated_on_revoke(api, db) -> None:
    uid, course, cat = await _setup(db)
    p = principal(uid)
    # denial: not cached, so a grant is visible at once
    assert not (await check_access(db, p, "course", course)).allowed
    e = await _grant(db, uid, cat)
    d = await check_access(db, p, "course", course)
    assert d.allowed and d.entitlement_ids == (e.id,)
    ver = await cache.version(uid)
    assert ver is not None and ver >= 1
    key = f"ent:dec:{uid}:v{ver}:{cache.principal_fingerprint(p)}:course:{course}"
    r = get_cache_redis()
    assert await r.exists(key) == 1
    assert 0 < await r.ttl(key) <= cache.TTL_SECONDS
    # served from cache even when the DB is not consulted
    hit = await cache.get(p, ver, "course", course)
    assert hit is not None and hit.allowed and hit.entitlement_ids == (e.id,)
    # revoke -> record_event bumps the version -> next check is a miss and denies
    await system_context(db, "test")
    await ent.revoke(db, e, SYS, reason_code="admin")
    assert (await cache.version(uid)) == ver + 1
    assert not (await check_access(db, p, "course", course)).allowed


async def test_ttl_bounded_by_entitlement_end_and_principal_fingerprint(api, db) -> None:
    uid, course, cat = await _setup(db)
    await _grant(db, uid, cat, ends_in=timedelta(seconds=20))
    p = principal(uid)
    assert (await check_access(db, p, "course", course)).allowed
    ver = await cache.version(uid)
    key = f"ent:dec:{uid}:v{ver}:{cache.principal_fingerprint(p)}:course:{course}"
    assert 0 < await get_cache_redis().ttl(key) <= 20
    staff = principal(uid, roles=("trainer",))
    assert cache.principal_fingerprint(staff) != cache.principal_fingerprint(p)


async def test_restricted_and_free_bypass_cache(api, db) -> None:
    uid, course, cat = await _setup(db)
    await _grant(db, uid, cat)
    assert (await check_access(db, principal(uid), "course", course)).allowed
    # an L3 restriction applies immediately even with a cached allow
    restricted = principal(uid, scope="restricted", restriction_level=3)
    d = await check_access(db, restricted, "course", course)
    assert not d.allowed and d.reason == "restricted"
    assert (await check_access(db, restricted, "course", uuid7(), is_free=True)).allowed


async def test_outbox_handler_bumps_version(api, db) -> None:
    uid = uuid7()
    before = await cache.version(uid)
    hs = handlers_for("entitlement.granted")
    assert ent.on_entitlement_event in hs
    msg = OutboxMessage(
        id=uuid7(),
        event_type="entitlement.granted",
        aggregate_type="entitlement",
        aggregate_id=uuid7(),
        payload={"user_id": str(uid)},
        organization_id=None,
        occurred_at=utcnow(),
        attempt=1,
    )
    await ent.on_entitlement_event(db, msg)
    assert (await cache.version(uid)) == (before or 0) + 1
    for et in cache.EVENT_TYPES:
        assert ent.on_entitlement_event in handlers_for(f"entitlement.{et}")


async def test_redis_outage_falls_back_to_database(api, db, monkeypatch) -> None:
    uid, course, cat = await _setup(db)
    await _grant(db, uid, cat)

    def boom() -> Any:
        raise ConnectionError("redis down")

    monkeypatch.setattr(cache, "_redis", boom)
    assert await cache.version(uid) is None
    assert (await check_access(db, principal(uid), "course", course)).allowed
