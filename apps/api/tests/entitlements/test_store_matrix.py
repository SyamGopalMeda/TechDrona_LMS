"""Entitlements behave the same on both stores (``entitlements_backend``: Postgres, then the
Firestore emulator after a backfill from the Postgres test database). Needs Postgres.

The emulator-only suite (``tests/entitlements/fs``) covers the Firestore concurrency guarantees;
this file pins the service results that other modules rely on to be identical per store.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.entitlements import service as ent
from tests.commerce.factory import make_buyer, make_product, principal
from tests.firestore.matrix import backend_fixture

entitlements_backend = backend_fixture("entitlements")
pytestmark = pytest.mark.usefixtures("entitlements_backend")

SYS = ent.Actor.system("test")


async def _grant(db, uid, cat, source="admin_grant", **kw):
    await system_context(db, "test")
    now = utcnow()
    e, created = await ent.grant(
        db,
        SYS,
        user_id=uid,
        source_type=source,
        product_id=cat.product.id,
        starts_at=kw.pop("starts_at", now - timedelta(days=1)),
        ends_at=kw.pop("ends_at", now + timedelta(days=30)),
        granted_by=kw.pop("granted_by", uid if source == "admin_grant" else None),
        **kw,
    )
    return e, created


async def test_grant_lifecycle_and_history_match(api, db) -> None:
    uid = await make_buyer(db)
    cat = await make_product(db)
    e, created = await _grant(db, uid, cat)
    again, created2 = await _grant(db, uid, cat, "trial")
    assert created and created2 and again.id != e.id
    assert await ent.suspend(db, e, SYS, reason="payment")
    assert not await ent.suspend(db, e, SYS, reason="again")
    assert await ent.restore(db, e, SYS, reason="paid")
    assert await ent.revoke(db, e, SYS, reason_code="admin", note="matrix", source_ref=(ref := uuid7()))
    assert [x.id for x in await ent.revoked_by_source(db, ref)] == [e.id]
    hist = [x.event_type for x in await ent.entitlement_history(db, e)]
    assert hist == ["granted", "suspended", "restored", "revoked"]
    mine = await ent.user_entitlements(db, uid)
    assert [x.id for x in mine] == [again.id, e.id]
    assert {x.id: x.status for x in mine} == {again.id: "active", e.id: "revoked"}
    got = await ent.get_entitlement(db, e.id)
    assert got is not None and got.revoke_reason == "admin" and got.revoked_at is not None


async def test_access_decision_matches(api, db) -> None:
    uid = await make_buyer(db)
    course = uuid7()
    cat = await make_product(db, items=[{"item_type": "course", "course_id": course}])
    p = principal(uid)
    assert not (await ent.evaluate(db, p, "course", course)).decision.allowed
    e, _ = await _grant(db, uid, cat)
    ev = await ent.evaluate(db, p, "course", course)
    assert ev.decision.allowed and ev.winner is not None and ev.winner.id == e.id
    await ent.enter_grace(db, e, utcnow() + timedelta(days=2), SYS, reason="dunning")
    assert (await ent.evaluate(db, p, "course", course)).decision.reason == "in_grace"


async def test_expiry_job_matches(api, db) -> None:
    uid = await make_buyer(db)
    cat = await make_product(db)
    now = utcnow()
    e, _ = await _grant(db, uid, cat, starts_at=now - timedelta(days=5), ends_at=now - timedelta(days=1))
    await system_context(db, "test")
    counts = await ent.expire_due(db, now)
    assert counts["expired"] >= 1
    got = await ent.get_entitlement(db, e.id)
    assert got is not None and got.status == "expired"


async def test_source_type_counts_match(api, db) -> None:
    uid = await make_buyer(db)
    cat = await make_product(db)
    counts_before = await ent.source_type_counts(
        db, ("admin_grant",), utcnow() - timedelta(hours=1), utcnow() + timedelta(hours=1)
    )
    await _grant(db, uid, cat)
    counts = await ent.source_type_counts(
        db, ("admin_grant",), utcnow() - timedelta(hours=1), utcnow() + timedelta(hours=1)
    )
    assert counts.get("admin_grant", 0) == counts_before.get("admin_grant", 0) + 1
