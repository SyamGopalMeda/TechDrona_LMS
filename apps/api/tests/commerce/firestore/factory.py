"""Catalogue / order rows for the Firestore-only commerce tests (written through the engine)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.commerce import datastore as ds
from app.modules.commerce.models import Coupon, Order, OrderItem, Payment, Plan, Price, Product, ProductItem


async def catalogue(session: Any, *, amount: int = 118_000, kind: str = "course") -> dict[str, Any]:
    now = utcnow()
    p = Product(
        id=uuid7(),
        sku=f"SKU-{uuid.uuid4().hex[:8]}",
        name="Python Course",
        product_kind=kind,
        refund_policy_key="standard",
        status="active",
    )
    ds.add(session, p)
    ds.add(session, ProductItem(id=uuid7(), product_id=p.id, item_type="course", course_id=uuid7()))
    plan = Plan(
        id=uuid7(),
        product_id=p.id,
        code=f"PLAN-{uuid.uuid4().hex[:8]}",
        billing_type="one_time",
        access_duration_days=365,
    )
    ds.add(session, plan)
    price = Price(
        id=uuid7(),
        plan_id=plan.id,
        amount_paise=amount,
        is_recurring=False,
        valid_from=now - timedelta(days=1),
        created_by=uuid7(),
    )
    ds.add(session, price)
    await session.commit()
    return {"product": p, "plan": plan, "price": price}


async def coupon(session: Any, *, code: str = "SAVE10", cap: int | None = None, per_user: int = 1) -> Coupon:
    c = Coupon(
        id=uuid7(),
        code=code,
        discount_type="percent",
        percent_off=Decimal("10.00"),
        max_redemptions=cap,
        per_user_limit=per_user,
        valid_from=utcnow() - timedelta(days=1),
        created_by=uuid7(),
    )
    ds.add(session, c)
    await session.commit()
    return c


async def paid_order(session: Any, user_id: uuid.UUID, cat: dict[str, Any], *, total: int = 118_000) -> Order:
    """A paid order + item + captured payment (what fulfilment leaves behind)."""
    now = utcnow()
    tax = total - round(total / Decimal("1.18"))
    o = Order(
        id=uuid7(),
        order_number=await ds.next_order_number(session, now),
        user_id=user_id,
        status="paid",
        subtotal_paise=total - tax,
        discount_paise=0,
        tax_paise=tax,
        total_paise=total,
        gateway="razorpay",
        gateway_order_id=f"order_{uuid.uuid4().hex[:10]}",
        idempotency_key=uuid.uuid4().hex,
        place_of_supply="29",
        expires_at=now + timedelta(minutes=30),
        paid_at=now,
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
    ds.add(
        session,
        Payment(
            id=uuid7(),
            order_id=o.id,
            user_id=user_id,
            gateway="razorpay",
            gateway_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
            status="captured",
            amount_paise=total,
            method="upi",
            captured_at=now,
            authorized_at=now,
        ),
    )
    await session.commit()
    return o
