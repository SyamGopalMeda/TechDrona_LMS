from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.core.ids import uuid7
from app.modules.commerce import datastore as ds
from app.modules.commerce.models import Order, Plan, Price, Product
from tests.commerce.firestore.factory import catalogue, paid_order


async def test_smoke(fs: Any, session: Any) -> None:
    cat = await catalogue(session)
    row = (
        await ds.execute(
            session,
            select(Price, Plan, Product)
            .join(Plan, Plan.id == Price.plan_id)
            .join(Product, Product.id == Plan.product_id)
            .where(Price.id == cat["price"].id, Price.is_active.is_(True)),
        )
    ).first()
    assert row is not None and row[2].sku == cat["product"].sku
    assert row[2].gst_rate == cat["product"].gst_rate
    uid = uuid7()
    o = await paid_order(session, uid, cat)
    n = (
        await ds.execute(session, select(func.count()).select_from(Order).where(Order.user_id == uid))
    ).scalar_one()
    assert n == 1
    assert o.order_number.endswith("00000001")
