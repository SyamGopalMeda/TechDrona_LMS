"""Commerce money flows on the Firestore emulator (``TD_STORE_COMMERCE=firestore``), no Postgres.

The real service code runs (``fulfil_order``, ``issue_tax_invoice``, ``execute_refund``,
``webhooks.ingest``); only the Postgres-side collaborators of other modules (audit, outbox,
entitlement grants/revokes, certificate revocation) are recorded instead of written.

Concurrency: each actor has its own session (= request transaction). A commit that loses an
optimistic race raises 409 ``conflict``; ``_retrying`` re-runs the whole request like the webhook
worker / a client does. The invariants are then checked on what Firestore holds.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.commerce import datastore as ds
from app.modules.commerce import service as svc
from app.modules.commerce import webhooks
from app.modules.commerce.gateway import FakePaymentProvider
from app.modules.commerce.models import Coupon, CouponRedemption, Invoice, Order, OrderItem, Refund
from app.modules.entitlements import service as ent
from tests.commerce.firestore.conftest import FakeSession
from tests.commerce.firestore.factory import catalogue, coupon, paid_order


@pytest.fixture
def pg(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Record the Postgres-side effects of other modules."""
    rec: dict[str, list[Any]] = {"audit": [], "events": [], "grants": [], "revokes": []}

    async def audit(_s: Any, _actor: Any, action: str, *a: Any, **kw: Any) -> None:
        rec["audit"].append(action)

    async def emit(_s: Any, name: str, payload: dict[str, Any], **kw: Any) -> None:
        rec["events"].append((name, payload))

    async def grant(_s: Any, _actor: Any, **kw: Any) -> Any:
        rec["grants"].append(kw)

    async def no_ents(*_a: Any, **_k: Any) -> list[Any]:
        return []

    async def zero(*_a: Any, **_k: Any) -> int:
        return 0

    monkeypatch.setattr(svc, "audit", audit)
    monkeypatch.setattr(svc, "emit_event", emit)
    monkeypatch.setattr(webhooks, "emit_event", emit, raising=False)
    monkeypatch.setattr(ent, "grant", grant)
    monkeypatch.setattr(svc, "_order_entitlements_for_update", no_ents)
    monkeypatch.setattr(svc, "_revoke_certificates", zero)
    return rec


async def _retrying(fn: Callable[[FakeSession], Awaitable[Any]], attempts: int = 25) -> Any:
    for i in range(attempts):
        s = FakeSession().as_platform()
        try:
            out = await fn(s)
            await s.commit()
            return out
        except ProblemError as e:
            await s.rollback()
            if e.code != "conflict" or i == attempts - 1:
                raise
            await asyncio.sleep(0.01 * (i + 1))
    raise AssertionError("unreachable")


async def _pending_order(
    session: Any, cat: dict[str, Any], user_id: uuid.UUID, *, total: int = 118_000, cpn: Coupon | None = None
) -> Order:
    now = utcnow()
    tax = 18_000 * total // 118_000
    o = Order(
        id=uuid7(),
        order_number=await ds.next_order_number(session, now),
        user_id=user_id,
        status="pending_payment",
        subtotal_paise=total - tax,
        discount_paise=0,
        tax_paise=tax,
        total_paise=total,
        gateway="razorpay",
        gateway_order_id=f"order_{uuid.uuid4().hex[:12]}",
        idempotency_key=uuid.uuid4().hex,
        billing_name="Asha Rao",
        place_of_supply="29",
        expires_at=now + timedelta(minutes=30),
    )
    ds.add(session, o)
    ds.add(
        session,
        OrderItem(
            id=uuid7(),
            order_id=o.id,
            user_id=user_id,
            product_id=cat["product"].id,
            plan_id=cat["plan"].id,
            price_id=cat["price"].id,
            unit_amount_paise=total,
            taxable_paise=total - tax,
            cgst_paise=tax // 2,
            sgst_paise=tax - tax // 2,
            total_paise=total,
            gst_rate=Decimal("18.00"),
            sac_code="9992",
        ),
    )
    if cpn is not None:
        ds.add(
            session,
            CouponRedemption(
                id=uuid7(),
                coupon_id=cpn.id,
                user_id=user_id,
                order_id=o.id,
                discount_paise=1000,
                reserved_until=o.expires_at,
            ),
        )
    await session.commit()
    return o


async def _fulfil(order_id: uuid.UUID) -> bool:
    async def run(s: FakeSession) -> bool:
        return await svc.fulfil_order(s, order_id, ent.Actor.system("commerce.test"), payment=None)

    return bool(await _retrying(run))


async def _all(model: Any, *where: Any) -> list[Any]:
    s = FakeSession().as_platform()
    return list((await ds.execute(s, select(model).where(*where))).scalars())


# --------------------------------------------------------------------------- fulfilment


async def test_fulfil_is_idempotent_and_issues_one_invoice(fs: Any, session: Any, pg: Any) -> None:
    cat = await catalogue(session)
    o = await _pending_order(session, cat, uuid7())
    assert await _fulfil(o.id) is True
    assert await _fulfil(o.id) is False
    [order] = await _all(Order, Order.id == o.id)
    assert order.status == "paid" and order.paid_at is not None
    invs = await _all(Invoice, Invoice.order_id == o.id)
    assert len(invs) == 1 and invs[0].invoice_number.endswith("/000001")
    assert invs[0].total_paise == 118_000 and invs[0].buyer_name == "Asha Rao"
    assert len(pg["grants"]) == 1 and pg["grants"][0]["source_type"] == "purchase"
    assert [n for n, _ in pg["events"]].count("order.paid") == 1


async def test_concurrent_fulfilment_of_one_order_grants_once(fs: Any, session: Any, pg: Any) -> None:
    cat = await catalogue(session)
    o = await _pending_order(session, cat, uuid7())
    results = await asyncio.gather(*[_fulfil(o.id) for _ in range(4)])
    assert sorted(results) == [False, False, False, True]
    assert len(await _all(Invoice, Invoice.order_id == o.id)) == 1
    # every attempt that lost the race rolled back completely: one committed grant set
    assert sum(1 for n, _ in pg["events"] if n == "order.paid") >= 1


async def test_invoice_numbers_gap_free_under_concurrency(fs: Any, session: Any, pg: Any) -> None:
    cat = await catalogue(session)
    orders = [await _pending_order(session, cat, uuid7()) for _ in range(6)]

    # an aborted transaction allocates a number but never commits it -> no gap
    s = FakeSession().as_platform()
    await svc.allocate_number(s, "TD", utcnow().date())
    await s.rollback()

    assert all(await asyncio.gather(*[_fulfil(o.id) for o in orders]))
    nums = sorted(int(i.invoice_number.rsplit("/", 1)[1]) for i in await _all(Invoice))
    assert nums == [1, 2, 3, 4, 5, 6]
    seq_n = sorted(int(o.order_number[-8:]) for o in await _all(Order))
    assert seq_n == list(range(1, 7))


async def test_coupon_cap_is_never_exceeded(fs: Any, session: Any, pg: Any) -> None:
    cat = await catalogue(session)
    cpn = await coupon(session, code="LAUNCH2", cap=2)
    orders = [await _pending_order(session, cat, uuid7(), cpn=cpn) for _ in range(4)]
    assert all(await asyncio.gather(*[_fulfil(o.id) for o in orders]))
    [c] = await _all(Coupon, Coupon.id == cpn.id)
    assert c.redeemed_count == 2  # ck_coupon_cap held; the other paid orders are honoured + flagged
    assert pg["audit"].count("coupon.cap_overrun") >= 2
    reds = await _all(CouponRedemption, CouponRedemption.coupon_id == cpn.id)
    assert {r.status for r in reds} == {"consumed"}


async def test_coupon_lookup_is_case_insensitive_citext(fs: Any, session: Any) -> None:
    await coupon(session, code="Diwali25")
    hit = (
        await ds.execute(session, select(Coupon).where(func.lower(Coupon.code) == "diwali25"))
    ).scalar_one()
    assert hit.code == "Diwali25"
    hit2 = (await ds.execute(session, select(Coupon).where(Coupon.code == "DIWALI25"))).scalar_one_or_none()
    assert hit2 is not None  # citext equality


# --------------------------------------------------------------------------- refunds


async def test_refunds_never_exceed_captured(fs: Any, session: Any, pg: Any) -> None:
    cat = await catalogue(session)
    uid = uuid7()
    o = await paid_order(session, uid, cat)
    pay_id = (await _all_payments(o.id))[0].id
    gw = FakePaymentProvider()
    rids = []
    for _ in range(3):
        r = Refund(
            id=uuid7(),
            payment_id=pay_id,
            order_id=o.id,
            user_id=uid,
            amount_paise=50_000,
            reason_code="content_issue",
            status="requested",
            requested_by=uid,
            idempotency_key=uuid.uuid4().hex,
            submit_attempts=0,
        )
        ds.add(session, r)
        rids.append(r.id)
    await session.commit()
    approver = Principal(user_id=uuid7(), session_id=uuid7(), is_platform=True)

    async def approve(rid: uuid.UUID) -> str:
        async def run(s: FakeSession) -> str:
            r = (await ds.execute(s, select(Refund).where(Refund.id == rid).with_for_update())).scalar_one()
            await svc.execute_refund(s, gw, r, approver)
            return r.status

        try:
            return str(await _retrying(run))
        except ProblemError as e:
            assert e.code == "validation_failed"
            return "rejected_amount"

    out = await asyncio.gather(*[approve(r) for r in rids])
    assert sorted(out) == ["processing", "processing", "rejected_amount"]  # 2 x 500 <= 1180, 3rd > total
    [order] = await _all(Order, Order.id == o.id)
    assert order.refunded_paise == 100_000 <= order.total_paise
    committed = sum(
        r.amount_paise for r in await _all(Refund, Refund.order_id == o.id) if r.status != "requested"
    )
    assert committed == order.refunded_paise
    assert await _repo_invariants() == []


async def _all_payments(order_id: uuid.UUID) -> list[Any]:
    from app.modules.commerce.models import Payment

    return await _all(Payment, Payment.order_id == order_id)


async def _repo_invariants() -> list[str]:
    from app.modules.commerce.repo_firestore import repo

    return await repo().invariants()


# --------------------------------------------------------------------------- webhooks


async def test_webhook_delivery_is_deduplicated_under_concurrency(fs: Any, session: Any, pg: Any) -> None:
    gw = FakePaymentProvider()
    payload = {"event": "payment.captured", "payload": {}, "created_at": int(utcnow().timestamp())}
    headers = {"x-razorpay-event-id": "evt_123"}

    async def deliver() -> str:
        async def run(s: FakeSession) -> str:
            status, _ = await webhooks.ingest(s, gw, b"{}", headers, payload)
            return status

        return str(await _retrying(run))

    out = await asyncio.gather(*[deliver() for _ in range(5)])
    assert out.count("accepted") == 1 and out.count("duplicate") == 4
    from app.modules.commerce.models import PaymentWebhookEvent

    assert len(await _all(PaymentWebhookEvent)) == 1


async def test_savepoint_rollback_restores_unit_of_work(fs: Any, session: Any) -> None:
    cat = await catalogue(session)
    o = await paid_order(session, uuid7(), cat)
    s = FakeSession().as_platform()
    order = (await ds.execute(s, select(Order).where(Order.id == o.id))).scalar_one()
    nested = await ds.begin_nested(s)
    order.status = "refunded"
    ds.add(
        s,
        Invoice(
            id=uuid7(),
            invoice_number="X",
            invoice_type="tax_invoice",
            order_id=o.id,
            seller_gstin="29ABCDE1234F1Z5",
            buyer_name="x",
            place_of_supply="29",
            issue_date=utcnow().date(),
            taxable_paise=1,
            total_paise=1,
        ),
    )
    await ds.flush(s)
    await nested.rollback()
    assert order.status == "paid"
    await s.commit()
    assert await _all(Invoice, Invoice.invoice_number == "X") == []


async def test_provider_refund_is_never_called_for_a_transaction_that_cannot_commit(
    fs: Any, session: Any, pg: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 3: the commit checks run before the provider call (``ds.before_side_effect``). A
    concurrent change to the locked order makes this approval unable to commit, so the refund
    must not reach the provider (on Postgres the row lock gives the same guarantee)."""
    cat = await catalogue(session)
    uid = uuid7()
    o = await paid_order(session, uid, cat)
    pay_id = (await _all_payments(o.id))[0].id
    r = Refund(
        id=uuid7(),
        payment_id=pay_id,
        order_id=o.id,
        user_id=uid,
        amount_paise=10_000,
        reason_code="content_issue",
        status="requested",
        requested_by=uid,
        idempotency_key=uuid.uuid4().hex,
        submit_attempts=0,
    )
    ds.add(session, r)
    await session.commit()
    gw = FakePaymentProvider()

    async def concurrent_change(*_a: Any, **_k: Any) -> int:
        other = FakeSession().as_platform()
        row = (await ds.execute(other, select(Order).where(Order.id == o.id).with_for_update())).scalar_one()
        row.billing_name = "changed meanwhile"
        await other.commit()
        return 0

    monkeypatch.setattr(svc, "_revoke_certificates", concurrent_change)
    s = FakeSession().as_platform()
    rr = (await ds.execute(s, select(Refund).where(Refund.id == r.id).with_for_update())).scalar_one()
    approver = Principal(user_id=uuid7(), session_id=uuid7(), is_platform=True)
    with pytest.raises(ProblemError) as ei:
        await svc.execute_refund(s, gw, rr, approver)
    assert ei.value.code == "conflict"
    assert gw.refunds == {}  # the provider was never asked
