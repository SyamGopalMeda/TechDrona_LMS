"""COM-17: notifications consumers for commerce events (invoice email, cancellation email,
renewal reminder, finance alert routing). Handlers are called directly with outbox messages."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.outbox import OutboxMessage, handlers_for
from app.core.time import utcnow
from app.modules.commerce.models import Invoice, Order, Subscription
from app.modules.notifications import consumers
from app.modules.notifications.adapters import MemoryEmailAdapter, get_email_adapter, set_email_adapter
from app.modules.notifications.models import Notification
from tests.commerce.factory import make_buyer, make_product
from tests.identity.factory import grant, make_user


@pytest.fixture
def mail() -> Iterator[MemoryEmailAdapter]:
    prev = get_email_adapter()
    fake = MemoryEmailAdapter()
    set_email_adapter(fake)
    yield fake
    set_email_adapter(prev)


def _msg(event_type: str, payload: dict[str, Any]) -> OutboxMessage:
    return OutboxMessage(
        id=uuid7(),
        event_type=event_type,
        aggregate_type="test",
        aggregate_id=uuid7(),
        payload=payload,
        organization_id=None,
        occurred_at=utcnow(),
        attempt=1,
    )


async def _rows(db: Any, user_id: uuid.UUID) -> list[Notification]:
    return list((await db.execute(select(Notification).where(Notification.user_id == user_id))).scalars())


async def _order(db: Any, user_id: uuid.UUID, **kw: Any) -> Order:
    o = Order(
        id=uuid7(),
        order_number=f"TD-{uuid7().hex[-10:].upper()}",
        user_id=user_id,
        status="paid",
        subtotal_paise=299900,
        tax_paise=0,
        total_paise=299900,
        idempotency_key=uuid7().hex,
        expires_at=utcnow() + timedelta(minutes=30),
        paid_at=utcnow(),
        gateway="razorpay",
        **kw,
    )
    db.add(o)
    await db.flush()
    return o


def test_consumers_registered_for_commerce_events() -> None:
    from app.wiring import _register_notification_consumers

    _register_notification_consumers()
    assert consumers.on_invoice_issued in handlers_for("invoice.issued")
    assert consumers.on_subscription_cancel_requested in handlers_for("subscription.cancel_requested")
    for ev in consumers.FINANCE_ALERT_EVENTS:
        assert consumers.on_finance_alert in handlers_for(ev)


async def test_invoice_issued_emails_buyer_once(db, mail) -> None:
    buyer = await make_buyer(db)
    await system_context(db, "test")
    order = await _order(db, buyer)
    inv = Invoice(
        id=uuid7(),
        invoice_number=f"TD{uuid7().hex[-8:].upper()}",
        invoice_type="tax_invoice",
        order_id=order.id,
        user_id=buyer,
        seller_gstin="36ABCDE1234F1Z5",
        buyer_name="Test User",
        place_of_supply="36",
        issue_date=date.today(),
        taxable_paise=254152,
        cgst_paise=22874,
        sgst_paise=22874,
        total_paise=299900,
    )
    db.add(inv)
    await db.flush()
    msg = _msg("invoice.issued", {"invoice_id": str(inv.id), "order_id": str(order.id)})
    await consumers.on_invoice_issued(db, msg)
    await consumers.on_invoice_issued(db, msg)  # relay retry: deduplicated
    (row,) = await _rows(db, buyer)
    assert row.template_key == "commerce.invoice_issued" and row.category == "transactional"
    assert row.data["invoice_number"] == inv.invoice_number
    (email,) = mail.sent
    assert inv.invoice_number in email.subject and "₹2,999.00" in email.text
    assert f"/app/orders/{order.id}" in email.text


async def test_cancel_requested_sends_email_only_confirmation(db, mail) -> None:
    buyer = await make_buyer(db)
    cat = await make_product(db, kind="subscription_plan", recurring=True)
    await system_context(db, "test")
    end = utcnow() + timedelta(days=20)
    sub = Subscription(
        id=uuid7(),
        user_id=buyer,
        plan_id=cat.plan.id,
        price_id=cat.price.id,
        gateway="razorpay",
        gateway_subscription_id=f"sub_{uuid7().hex[-10:]}",
        status="active",
        mandate_max_amount_paise=100000,
        current_period_end=end,
        cancel_at_period_end=True,
    )
    db.add(sub)
    await db.flush()
    msg = _msg("subscription.cancel_requested", {"subscription_id": str(sub.id), "user_id": str(buyer)})
    await consumers.on_subscription_cancel_requested(db, msg)
    await consumers.on_subscription_cancel_requested(db, msg)
    (row,) = await _rows(db, buyer)
    assert row.channels == ["email"]  # stays out of the in-app inbox (commerce wrote that one)
    (email,) = mail.sent
    assert "cancelled" in email.subject and f"{end:%d %b %Y}" in email.text


async def test_renewal_reminder_only_for_annual_plans_once_per_period(db, mail) -> None:
    buyer = await make_buyer(db)
    annual = await make_product(db, kind="subscription_plan", recurring=True)
    monthly = await make_product(db, kind="subscription_plan", recurring=True)
    await system_context(db, "test")
    annual.plan.interval_unit, annual.plan.interval_count = "year", 1
    now = utcnow()
    for cat in (annual, monthly):
        db.add(
            Subscription(
                id=uuid7(),
                user_id=buyer,
                plan_id=cat.plan.id,
                price_id=cat.price.id,
                gateway="razorpay",
                gateway_subscription_id=f"sub_{uuid7().hex[-10:]}",
                status="active",
                mandate_max_amount_paise=100000,
                current_period_end=now + timedelta(days=6),
            )
        )
    await db.flush()
    assert await consumers.send_renewal_reminders(db, now) == 1
    assert await consumers.send_renewal_reminders(db, now) == 0  # dedupe per period
    (row,) = await _rows(db, buyer)
    assert row.template_key == "subscription.renewal_reminder"
    assert len(mail.sent) == 1 and "renews in 7 days" in mail.sent[0].subject


async def test_finance_alerts_routed_to_active_admins(db) -> None:
    """Single company (D2): finance duties are folded into Admin (``super_admin``)."""
    fin = await make_user(db)
    await grant(db, fin.id, "super_admin")
    other = await make_user(db)
    await system_context(db, "test")
    msg = _msg(
        "commerce.refund_failed",
        {"refund_id": str(uuid7()), "order_id": str(uuid7()), "amount_paise": 5000, "card_last4": "4242"},
    )
    await consumers.on_finance_alert(db, msg)
    await consumers.on_finance_alert(db, msg)
    (row,) = await _rows(db, fin.id)
    assert (
        row.priority == "high" and row.category == "system" and row.template_key == "commerce.refund_failed"
    )
    assert row.data["amount_paise"] == 5000 and "card_last4" not in row.data  # minimised payload
    assert await _rows(db, other.id) == []
