"""The commerce Firestore engine: SQL semantics, RLS emulation, uniqueness, the price-window
exclusion, the document mapping and the repository scope lint (emulator, no Postgres)."""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import bindparam, func, or_, select, tuple_, update

from app.core.errors import ProblemError
from app.core.firestore.repository import assert_repository_scoped
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.commerce import datastore as ds
from app.modules.commerce import store_specs as sp
from app.modules.commerce.models import (
    Coupon,
    Invoice,
    Order,
    OrderItem,
    Payment,
    PaymentWebhookEvent,
    Price,
    Product,
)
from app.modules.commerce.repo_firestore import CommerceRepo, UnsupportedStatement
from tests.commerce.firestore.conftest import FakeSession
from tests.commerce.firestore.factory import catalogue, coupon, paid_order


def test_repository_is_platform_scoped() -> None:
    assert_repository_scoped(CommerceRepo)


def test_every_commerce_table_has_a_mapping_family_and_collection() -> None:
    from app.core.firestore.backfill import mappings

    tables = {m.table for m in mappings("commerce")}
    assert sp.TABLES <= tables
    assert set(sp.RLS) == set(sp.TABLES)


def test_document_round_trip_keeps_column_types() -> None:
    now = utcnow()
    o = Order(
        id=uuid7(),
        order_number="TD-O-2026-00000001",
        user_id=uuid7(),
        status="paid",
        subtotal_paise=100,
        discount_paise=0,
        tax_paise=18,
        total_paise=118,
        refunded_paise=0,
        idempotency_key="k",
        expires_at=now,
        paid_at=now,
    )
    back = sp.from_doc(Order, sp.to_doc(Order, o))
    assert {c.key: getattr(back, c.key) for c in sp.columns(Order)} == {
        c.key: getattr(o, c.key) for c in sp.columns(Order)
    }
    c = Coupon(
        id=uuid7(),
        code="X1Y",
        discount_type="percent",
        percent_off=Decimal("12.50"),
        applicable_product_ids=[uuid7()],
        valid_from=now,
        created_by=uuid7(),
    )
    d = sp.to_doc(Coupon, c)
    assert d["percent_off"] == "12.50" and isinstance(d["applicable_product_ids"][0], str)
    back_c = sp.from_doc(Coupon, d)
    assert (
        back_c.percent_off == Decimal("12.50") and back_c.applicable_product_ids == c.applicable_product_ids
    )
    e = PaymentWebhookEvent(
        id=uuid7(),
        gateway="razorpay",
        event_id="e",
        event_type="t",
        signature_valid=True,
        payload={"a": [[1, 2]], "b": {"c": None}},
        payload_sha256=b"\x00" * 32,
    )
    de = sp.to_doc(PaymentWebhookEvent, e)
    assert isinstance(de["payload"], str) and json.loads(de["payload"]) == e.payload  # nested arrays survive
    inv = Invoice(issue_date=date(2026, 4, 1))
    assert sp.to_doc(Invoice, inv)["issue_date"] == "2026-04-01"


async def test_null_logic_ordering_keyset_and_aggregates(fs: Any, session: Any) -> None:
    cat = await catalogue(session)
    uid = uuid7()
    orders = [await paid_order(session, uid, cat, total=t) for t in (118_000, 59_000, 236_000)]
    s = FakeSession().as_platform()
    # NULL never equals anything; IS NULL / IS DISTINCT FROM are two-valued
    n_null = (
        await ds.execute(
            s, select(func.count()).select_from(Order).where(Order.subscription_id == bindparam("n", None))
        )
    ).scalar_one()
    assert n_null == 0
    n_is = (
        await ds.execute(s, select(func.count()).select_from(Order).where(Order.subscription_id.is_(None)))
    ).scalar_one()
    assert n_is == 3
    n_dist = (
        await ds.execute(
            s, select(func.count()).select_from(Order).where(Order.gateway.is_distinct_from("offline_po"))
        )
    ).scalar_one()
    assert n_dist == 3
    # ORDER BY ... DESC puts NULLs first (Postgres); limit/offset
    ids = list(
        (
            await ds.execute(
                s, select(Order.total_paise).order_by(Order.total_paise.desc()).limit(2).offset(1)
            )
        ).scalars()
    )
    assert ids == [118_000, 59_000]
    # keyset on (created_at, id) as the finance lists do
    first = sorted(orders, key=lambda o: (o.created_at, o.id))
    nxt = (
        (
            await ds.execute(
                s,
                select(Order)
                .where(tuple_(Order.created_at, Order.id) > tuple_(first[0].created_at, first[0].id))
                .order_by(Order.created_at, Order.id),
            )
        )
        .scalars()
        .all()
    )
    assert [o.id for o in nxt] == [o.id for o in first[1:]]
    # aggregates, coalesce over no rows, group by over a join
    row = (
        await ds.execute(
            s,
            select(func.count(Order.id), func.coalesce(func.sum(Order.total_paise), 0)).where(
                Order.status == "paid"
            ),
        )
    ).one()
    assert tuple(row) == (3, 413_000)
    none = (
        await ds.execute(
            s, select(func.coalesce(func.sum(Order.total_paise), 0)).where(Order.status == "refunded")
        )
    ).scalar_one()
    assert none == 0
    by_kind = (
        await ds.execute(
            s,
            select(
                Product.product_kind,
                func.count(OrderItem.id),
                func.coalesce(func.sum(OrderItem.total_paise), 0),
            )
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.status.in_(("paid", "refunded")))
            .group_by(Product.product_kind),
        )
    ).all()
    assert [tuple(r) for r in by_kind] == [("course", 3, 413_000)]
    mn = (await ds.execute(s, select(func.min(Order.total_paise)))).scalar_one()
    assert mn == 59_000
    # correlated NOT EXISTS (reconciliation: paid without a captured payment)
    lonely = (
        (
            await ds.execute(
                s,
                select(Order.order_number).where(
                    Order.status == "paid",
                    ~select(Payment.id)
                    .where(Payment.order_id == Order.id, Payment.status == "captured")
                    .exists(),
                ),
            )
        )
        .scalars()
        .all()
    )
    assert lonely == []
    # OR + IN
    hit = (
        await ds.execute(
            s,
            select(func.count())
            .select_from(Order)
            .where(or_(Order.total_paise == 59_000, Order.total_paise.in_([236_000]))),
        )
    ).scalar_one()
    assert hit == 2


async def test_rls_owner_read_all_and_platform_only(fs: Any, session: Any) -> None:
    cat = await catalogue(session)
    a, b = uuid7(), uuid7()
    oa = await paid_order(session, a, cat)
    await paid_order(session, b, cat)
    sa = FakeSession().as_user(a)
    mine = (await ds.execute(sa, select(Order))).scalars().all()
    assert [o.id for o in mine] == [oa.id]  # O: own rows only
    assert (await ds.execute(sa, select(Product))).scalars().all()  # TN: everyone reads the catalogue
    sa2 = FakeSession().as_user(a)
    other = (await ds.execute(sa2, select(Order).where(Order.user_id == b))).scalar_one_or_none()
    assert other is None  # no existence oracle
    platform = FakeSession().as_platform()
    ds.add(
        platform,
        PaymentWebhookEvent(
            id=uuid7(),
            gateway="razorpay",
            event_id="e1",
            event_type="x",
            signature_valid=True,
            payload={},
            payload_sha256=b"\x01" * 32,
        ),
    )
    await platform.commit()
    assert (await ds.execute(FakeSession().as_user(a), select(PaymentWebhookEvent))).scalars().all() == []
    # a user can't write the catalogue (TN WITH CHECK = platform)
    su = FakeSession().as_user(a)
    ds.add(
        su,
        Coupon(
            id=uuid7(),
            code="HACK1",
            discount_type="flat",
            amount_off_paise=1,
            valid_from=utcnow(),
            created_by=a,
        ),
    )
    with pytest.raises(ProblemError) as ei:
        await su.commit()
    assert ei.value.code == "permission_denied"


async def test_uniqueness_and_price_window_exclusion(fs: Any, session: Any) -> None:
    cat = await catalogue(session)
    s = FakeSession().as_platform()
    ds.add(
        s,
        Product(
            id=uuid7(),
            sku=cat["product"].sku.upper(),
            name="Dup",
            product_kind="course",
            refund_policy_key="standard",
        ),
    )
    with pytest.raises(ProblemError) as ei:
        await s.commit()
    assert ei.value.code == "conflict"  # citext UNIQUE (sku)
    s2 = FakeSession().as_platform()
    ds.add(
        s2,
        Price(
            id=uuid7(),
            plan_id=cat["plan"].id,
            amount_paise=99_000,
            is_recurring=False,
            valid_from=utcnow(),
            created_by=uuid7(),
        ),
    )
    with pytest.raises(ProblemError) as ei:
        await s2.commit()
    assert ei.value.code == "conflict"  # ex_price_overlap
    # closing the old window first makes the new price valid (same transaction)
    s3 = FakeSession().as_platform()
    now = utcnow()
    old = (
        await ds.execute(s3, select(Price).where(Price.id == cat["price"].id).with_for_update())
    ).scalar_one()
    old.valid_until = now
    ds.add(
        s3,
        Price(
            id=uuid7(),
            plan_id=cat["plan"].id,
            amount_paise=99_000,
            is_recurring=False,
            valid_from=now,
            created_by=uuid7(),
        ),
    )
    await s3.commit()


async def test_update_returning_and_lost_update_protection(fs: Any, session: Any) -> None:
    c = await coupon(session, code="CAP1", cap=1)
    s1, s2 = FakeSession().as_platform(), FakeSession().as_platform()
    q = (
        update(Coupon)
        .where(
            Coupon.id == c.id,
            (Coupon.max_redemptions.is_(None)) | (Coupon.redeemed_count < Coupon.max_redemptions),
        )
        .values(redeemed_count=Coupon.redeemed_count + 1)
        .returning(Coupon.id)
    )
    assert (await ds.execute(s1, q)).scalar_one_or_none() == c.id
    assert (await ds.execute(s2, q)).scalar_one_or_none() == c.id  # both read 0 ...
    await s1.commit()
    with pytest.raises(ProblemError) as ei:  # ... but only one may commit (no lost update)
        await s2.commit()
    assert ei.value.code == "conflict"
    s3 = FakeSession().as_platform()
    assert (await ds.execute(s3, q)).scalar_one_or_none() is None  # cap reached


async def test_read_your_writes_and_identity_map(fs: Any, session: Any) -> None:
    cat = await catalogue(session)
    o = await paid_order(session, uuid7(), cat)
    s = FakeSession().as_platform()
    a = (await ds.execute(s, select(Order).where(Order.id == o.id))).scalar_one()
    a.status = "refunded"
    b = (await ds.execute(s, select(Order).where(Order.status == "refunded"))).scalar_one()
    assert a is b  # same row, same object, uncommitted change visible in the transaction
    await s.rollback()
    s2 = FakeSession().as_platform()
    assert (await ds.execute(s2, select(Order).where(Order.id == o.id))).scalar_one().status == "paid"


async def test_mixed_statement_is_refused(fs: Any, session: Any) -> None:
    from app.modules.entitlements.models import Entitlement

    with pytest.raises(UnsupportedStatement):
        await ds.execute(
            session, select(Entitlement).join(OrderItem, OrderItem.id == Entitlement.order_item_id)
        )


async def test_postgres_default_is_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the switch every call reaches the session unchanged."""
    from app.core.firestore.backend import reset_store_backends

    monkeypatch.delenv("TD_STORE_COMMERCE", raising=False)
    reset_store_backends()
    seen: list[Any] = []

    class Spy:
        info: dict[str, Any] = {}

        async def execute(self, stmt: Any, params: Any = None) -> Any:
            seen.append(stmt)
            return "pg"

        def add(self, obj: Any) -> None:
            seen.append(obj)

        async def flush(self) -> None:
            seen.append("flush")

    sp_ = Spy()
    stmt = select(Order)
    assert await ds.execute(sp_, stmt) == "pg"
    o = Order(id=uuid.uuid4())
    ds.add(sp_, o)
    await ds.flush(sp_)
    assert seen == [stmt, o, "flush"] and sp_.info == {}


def test_index_fragment_declares_no_composite_index_needed() -> None:
    frag = Path(__file__).resolve().parents[3] / "app/modules/commerce/firestore.indexes.fragment.json"
    data = json.loads(frag.read_text(encoding="utf-8"))
    assert data["indexes"] == []
    overridden = {(f["collectionGroup"], f["fieldPath"]) for f in data["fieldOverrides"]}
    assert ("lms_payment_webhook_events", "payload") in overridden


_ = (timedelta,)


def test_flip_migration_is_written_but_never_applied_by_upgrade_heads() -> None:
    """``migrations/flip/commerce_0005`` drops the FKs into commerce tables; it is outside
    ``version_locations``, so ``alembic upgrade heads`` cannot run it before the flip."""
    import configparser
    import importlib.util

    api = Path(__file__).resolve().parents[3]
    ini = configparser.ConfigParser(interpolation=None)
    ini.read(api / "alembic.ini", encoding="utf-8")
    locations = ini["alembic"]["version_locations"]
    assert "migrations/versions" in locations and "flip" not in locations
    path = api / "migrations/flip/commerce_0005_drop_inbound_fks.py"
    assert not (api / "migrations/versions" / path.name).exists()
    spec = importlib.util.spec_from_file_location("commerce_0005_flip", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (mod.revision, mod.down_revision) == ("commerce_0005", "commerce_0004")
    assert {(t, c) for t, c, _ in mod.FKS} == {
        ("entitlements", "product_id"),
        ("entitlements", "order_item_id"),
        ("entitlements", "subscription_id"),
        ("entitlements", "coupon_redemption_id"),
        ("support_tickets", "related_order_id"),
    }
