"""Entitlements on Firestore (``TD_STORE_ENTITLEMENTS=firestore``), emulator only.

Covers the service functions other modules call (grant / transitions / quotas / expiry /
restriction extension / read API), the row-lock equivalents under concurrency, the CHECK
constraints, the store scope rules, the repository scope lint, the mappers and the indexes.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow

pytestmark = pytest.mark.usefixtures("fs_env")

API = Path(__file__).resolve().parents[3]


def _svc() -> Any:
    from app.modules.entitlements import service

    return service


def _sys() -> Any:
    return _svc().Actor.system("test")


async def _grant(uid: uuid.UUID, source: str = "admin_grant", *, days: int = 30, **kw: Any) -> Any:
    svc = _svc()
    now = utcnow()
    kw.setdefault("feature_key", "all_courses")
    if source == "admin_grant":
        kw.setdefault("granted_by", uid)
    e, created = await svc.grant(
        None,
        _sys(),
        user_id=uid,
        source_type=source,
        starts_at=kw.pop("starts_at", now - timedelta(days=1)),
        ends_at=kw.pop("ends_at", now + timedelta(days=days)),
        **kw,
    )
    return e, created


async def _events(e: Any) -> list[str]:
    return [x.event_type for x in await _svc().entitlement_history(None, e)]


# --------------------------------------------------------------------------- grant


async def test_grant_is_idempotent_per_source(fs_env: list[tuple[str, str]]) -> None:
    uid, item = uuid7(), uuid7()
    e1, c1 = await _grant(uid, "purchase", order_item_id=item)
    e2, c2 = await _grant(uid, "purchase", order_item_id=item)
    assert (c1, c2) == (True, False)
    assert e1.id == e2.id and e1.status == "active" and e1.order_item_id == item
    assert await _events(e1) == ["granted"]
    assert fs_env == [("granted", str(e1.id))]  # side effects only for the real grant
    found = await _svc().for_order_items(None, [item, uuid7()])
    assert list(found) == [item] and found[item].id == e1.id


async def test_concurrent_grants_for_one_subscription_create_exactly_one() -> None:
    uid, sub = uuid7(), uuid7()
    res = await asyncio.gather(*(_grant(uid, "subscription", subscription_id=sub) for _ in range(5)))
    assert sum(created for _, created in res) == 1
    assert len({e.id for e, _ in res}) == 1
    assert len(await _svc().user_entitlements(None, uid)) == 1
    got = await _svc().for_subscription(None, sub)
    assert got is not None and got.id == res[0][0].id


async def test_check_constraints_are_enforced() -> None:
    uid = uuid7()
    with pytest.raises(ValueError, match="ck_ent_source"):
        await _grant(uid, "purchase")  # no order item
    with pytest.raises(ValueError, match="ck_ent_target"):
        await _grant(uid, feature_key=None)
    with pytest.raises(ValueError, match="ck_ent_window"):
        now = utcnow()
        await _grant(uid, starts_at=now, ends_at=now - timedelta(days=1))
    with pytest.raises(ValueError, match="ck_ent_open_end"):
        await _grant(uid, "trial", ends_at=None)
    assert await _svc().user_entitlements(None, uid) == []


# --------------------------------------------------------------------------- transitions


async def test_lifecycle_transitions_and_history(fs_env: list[tuple[str, str]]) -> None:
    svc = _svc()
    uid = uuid7()
    e, _ = await _grant(uid)
    actor = _sys()
    assert await svc.suspend(None, e, actor, reason="payment")
    assert e.status == "suspended"
    assert not await svc.suspend(None, e, actor, reason="again")  # guard
    assert await svc.restore(None, e, actor, reason="paid")
    assert await svc.enter_grace(None, e, utcnow() + timedelta(days=3), actor, reason="dunning")
    assert e.status == "grace" and e.grace_ends_at is not None
    assert await svc.extend_to(None, e, e.ends_at + timedelta(days=10), actor, reason="renewed")
    assert e.status == "active" and e.grace_ends_at is None
    assert await svc.revoke(None, e, actor, reason_code="admin", note="test", source_ref=(ref := uuid7()))
    assert e.status == "revoked" and e.revoked_at is not None and e.revoke_reason == "admin"
    assert not await svc.revoke(None, e, actor, reason_code="admin")
    assert [x.id for x in await svc.revoked_by_source(None, ref)] == [e.id]
    assert await svc.reinstate(None, e, actor, reason="refund failed", source_ref=ref)
    assert e.status == "active" and e.revoked_at is None and e.revoke_reason is None
    assert await svc.revoked_by_source(None, ref) == []
    assert await _events(e) == [
        "granted",
        "suspended",
        "restored",
        "entered_grace",
        "restored",
        "revoked",
        "restored",
    ]
    assert [t for t, _ in fs_env] == await _events(e)
    fresh = await svc.lock(None, e.id)
    assert fresh is not None and fresh.status == "active" and fresh.updated_at >= fresh.created_at


async def test_change_product_keeps_the_larger_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc()
    uid, p1, p2 = uuid7(), uuid7(), uuid7()
    quotas = {p1: {"mentor_sessions_remaining": 4}, p2: {"mentor_sessions_remaining": 2}}

    async def fake_quotas(session: Any, product_id: uuid.UUID) -> dict[str, int]:
        return dict(quotas[product_id])

    monkeypatch.setattr(svc, "quotas_for_product", fake_quotas)
    e, _ = await _grant(uid, "subscription", subscription_id=uuid7(), feature_key=None, product_id=p1)
    assert e.mentor_sessions_remaining == 4
    assert await svc.change_product(None, e, p2, _sys(), reason="downgrade")
    assert e.product_id == p2 and e.mentor_sessions_remaining == 4
    assert not await svc.change_product(None, e, p2, _sys(), reason="same")


async def test_concurrent_revokes_write_one_event() -> None:
    svc = _svc()
    e, _ = await _grant(uuid7())
    copies = [await svc.lock(None, e.id) for _ in range(5)]
    res = await asyncio.gather(*(svc.revoke(None, c, _sys(), reason_code="fraud") for c in copies))
    assert sorted(res) == [False, False, False, False, True]
    assert all(c.status == "revoked" for c in copies)  # every caller sees the committed state
    assert (await _events(e)).count("revoked") == 1


# --------------------------------------------------------------------------- quotas


async def test_consume_quota_soonest_first_and_no_lost_update(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc()
    uid = uuid7()

    async def fake_quotas(session: Any, product_id: uuid.UUID) -> dict[str, int]:
        return {"mentor_sessions_remaining": 2}

    monkeypatch.setattr(svc, "quotas_for_product", fake_quotas)
    late, _ = await _grant(uid, feature_key=None, product_id=uuid7(), days=60)
    soon, _ = await _grant(uid, feature_key=None, product_id=uuid7(), days=10)
    first = await svc.consume_quota(None, uid, "mentor_sessions", _sys())
    assert first is not None and first.id == soon.id and first.mentor_sessions_remaining == 1
    got = await asyncio.gather(*(svc.consume_quota(None, uid, "mentor_sessions", _sys()) for _ in range(5)))
    assert sum(g is not None for g in got) == 3  # 1 + 2 left
    left = {e.id: e.mentor_sessions_remaining for e in await svc.user_entitlements(None, uid)}
    assert left == {late.id: 0, soon.id: 0}
    assert await svc.consume_quota(None, uid, "mentor_sessions", _sys()) is None
    assert (await svc.credit_quota(None, soon.id, "mentor_sessions", _sys(), reason="cancelled")) is not None
    assert {e.id: e.mentor_sessions_remaining for e in await svc.usable_entitlements(None, uid)}[soon.id] == 1
    assert (await _events(soon))[-1] == "quota_credited"


# --------------------------------------------------------------------------- jobs


async def test_expire_due_moves_active_to_grace_or_expired() -> None:
    svc = _svc()
    uid, now = uuid7(), utcnow()
    to_exp, _ = await _grant(uid, starts_at=now - timedelta(days=5), ends_at=now - timedelta(days=1))
    to_grace, _ = await _grant(
        uid,
        starts_at=now - timedelta(days=5),
        ends_at=now - timedelta(days=1),
        grace_ends_at=now + timedelta(days=2),
    )
    keep, _ = await _grant(uid)
    assert await svc.expire_due(None, now) == {"entered_grace": 1, "expired": 1}
    st = {e.id: e.status for e in await svc.user_entitlements(None, uid)}
    assert st == {to_exp.id: "expired", to_grace.id: "grace", keep.id: "active"}
    assert await svc.expire_due(None, now) == {"entered_grace": 0, "expired": 0}
    assert await svc.expire_due(None, now + timedelta(days=3)) == {"entered_grace": 0, "expired": 1}


async def test_restriction_extension_credits_time_bound_entitlements(monkeypatch: pytest.MonkeyPatch) -> None:
    import contextlib

    svc = _svc()

    @contextlib.asynccontextmanager
    async def no_ctx(session: Any, job: str) -> Any:
        yield

    monkeypatch.setattr(svc, "system_context", no_ctx)
    uid = uuid7()
    e, _ = await _grant(uid)
    old_end = e.ends_at
    open_ended, _ = await _grant(uid, ends_at=None)
    out = await svc.extend_entitlements_for_restriction(None, uid, 5, "false positive", case_ref="C-1")
    assert out == {"extended": 1, "entitlement_ids": [str(e.id)], "uncredited_days": {}}
    fresh = await svc.get_entitlement(None, e.id)
    assert fresh.ends_at == old_end + timedelta(days=5)
    assert (await svc.get_entitlement(None, open_ended.id)).ends_at is None
    assert (await _events(e))[-1] == "fp_extension"


# --------------------------------------------------------------------------- access decision


async def test_evaluate_reads_firestore(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc()
    course = uuid7()

    async def scope(session: Any, rtype: str, rid: uuid.UUID) -> Any:
        return set(), {course}, {"all_courses"}

    monkeypatch.setattr(svc, "covering_scope", scope)
    uid = uuid7()
    p = Principal(user_id=uid, session_id=uuid7())
    assert not (await svc.evaluate(None, p, "course", course)).decision.allowed
    e, _ = await _grant(uid, feature_key=None, course_id=course)
    ev = await svc.evaluate(None, p, "course", course)
    assert ev.decision.allowed and ev.winner is not None and ev.winner.id == e.id
    await svc.suspend(None, e, _sys(), reason="x")
    assert (await svc.evaluate(None, p, "course", course)).decision.reason == "suspended_payment"


# --------------------------------------------------------------------------- read API


async def test_read_api_orders_and_counts() -> None:
    svc = _svc()
    uid = uuid7()
    a, _ = await _grant(uid)
    b, _ = await _grant(uid, "trial")
    assert [e.id for e in await svc.user_entitlements(None, uid)] == [b.id, a.id]  # newest first
    await svc.revoke(None, a, _sys(), reason_code="admin")
    assert [e.id for e in await svc.user_entitlements(None, uid, statuses=("active", "grace"))] == [b.id]
    now = utcnow()
    counts = await svc.source_type_counts(
        None, ("admin_grant", "trial", "coupon_grant"), now - timedelta(hours=1), now + timedelta(hours=1)
    )
    assert counts == {"admin_grant": 1, "trial": 1}
    assert await svc.get_entitlement(None, uuid7()) is None


# --------------------------------------------------------------------------- store scope


async def test_store_scope_owner_reads_own_rows_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import auth as core_auth
    from app.core.firestore.errors import StoreAccessDeniedError
    from app.core.firestore.store import ScopedStore
    from app.modules.entitlements.repo_firestore import repo
    from app.modules.entitlements.store_specs import ENTS

    monkeypatch.setattr(core_auth, "_permission_checker", None)
    uid = uuid7()
    e, _ = await _grant(uid)
    me = Principal(user_id=uid, session_id=uuid7())
    other = Principal(user_id=uuid7(), session_id=uuid7())
    assert [x.id for x in await repo(me).for_user(uid)] == [e.id]
    with pytest.raises(StoreAccessDeniedError):
        await repo(other).for_user(uid)
    assert await ScopedStore(other).get(ENTS, str(e.id)) is None  # no existence oracle
    with pytest.raises(StoreAccessDeniedError):  # owners never write their entitlements
        await ScopedStore(me).update(ENTS, str(e.id), {"status": "active"})
    with pytest.raises(StoreAccessDeniedError):
        await repo(me).get(e.id)  # @platform_only


def test_repository_passes_the_scope_lint() -> None:
    from app.core.firestore.repository import assert_repository_scoped
    from app.modules.entitlements.repo_firestore import EntitlementRepo

    assert_repository_scoped(EntitlementRepo)


def test_mappers_round_trip_to_the_orm() -> None:
    from app.modules.entitlements.models import Entitlement
    from app.modules.entitlements.repo_firestore import ent_fields, ent_of
    from app.modules.entitlements.store_specs import ENT_FIELDS, ent_doc, source_key

    now = utcnow()
    row = {k: None for k in ENT_FIELDS} | {
        "id": uuid7(),
        "user_id": uuid7(),
        "source_type": "purchase",
        "order_item_id": uuid7(),
        "product_id": uuid7(),
        "status": "active",
        "starts_at": now,
        "ends_at": now + timedelta(days=1),
        "mocks_remaining": 3,
        "created_at": now,
        "updated_at": now,
    }
    e = ent_of(ent_doc(row))
    assert isinstance(e, Entitlement)
    assert {k: getattr(e, k) for k in ENT_FIELDS} == row
    assert ent_fields(e) == ent_doc(row)
    assert source_key(row) == f"order_item:{row['order_item_id']}"


def test_indexes_for_the_entitlement_queries_are_declared() -> None:
    frag = json.loads((API / "app/modules/entitlements/firestore.indexes.fragment.json").read_text())
    got = {
        (i["collectionGroup"], tuple(f["fieldPath"] for f in i["fields"] if f["fieldPath"] != "__name__"))
        for i in frag["indexes"]
    }
    for need in (
        ("lms_entitlements", ("user_id", "created_at")),
        ("lms_entitlements", ("status", "ends_at")),
        ("lms_entitlements", ("status", "grace_ends_at")),
        ("lms_entitlements", ("source_type", "created_at")),
        ("lms_entitlement_events", ("user_id", "entitlement_id", "occurred_at")),
        ("lms_entitlement_events", ("event_type", "source_ref")),
    ):
        assert need in got
