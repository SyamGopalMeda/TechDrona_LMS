"""DEV / DEMO DATA ONLY — demo products, plans, prices and coupons for local development.
Never run against production: refuses outside ``APP_ENV`` local/dev/test. Every
SKU/coupon is prefixed ``DEMO-`` so it is recognisable (and removable) in any database.

Run (after ``alembic upgrade heads`` and ``python -m app.seeds.dev_users``):
``python -m app.seeds.commerce_demo``

Creates (idempotent by SKU / coupon code):

* DEMO-COURSE-DSA-365        course, ₹1,999 incl. GST, 365 days
* DEMO-PP-TCS-NQT-180        placement package, ₹3,499, 180 days, 2 mentor sessions
* DEMO-MOCK-PACK-10          mock pack, ₹799, 10 mocks, 90 days
* DEMO-ALL-ACCESS-M          subscription plan, ₹499/month (gateway plan id must be set
                             from the Razorpay dashboard before subscriptions work)
* coupons DEMO25 (25 %, 100 uses, 1 per user) and DEMOFLAT200 (₹200 off, min ₹1,000)

Prices carry an 18 % GST assumption (flagged in policy.DEFAULT_GST_RATE).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import make_engine, system_context
from app.core.ids import uuid7
from app.core.models_registry import import_all_models
from app.core.time import utcnow
from app.modules.commerce.models import Coupon, Plan, Price, Product, ProductItem
from app.seeds import seeds_allowed
from app.seeds.sync import sync_touched

# Seeds run standalone: register every module's tables so cross-module FKs resolve.
import_all_models()

PRODUCTS: list[dict[str, Any]] = [
    {
        "sku": "DEMO-COURSE-DSA-365",
        "name": "DEMO Data Structures course",
        "kind": "course",
        "amount": 199900,
        "days": 365,
        "items": [{"item_type": "feature", "feature_key": "demo_dsa_course"}],
    },
    {
        "sku": "DEMO-PP-TCS-NQT-180",
        "name": "DEMO TCS NQT Placement Package",
        "kind": "placement_package",
        "amount": 349900,
        "days": 180,
        "items": [
            {"item_type": "feature", "feature_key": "all_company_paths"},
            {
                "item_type": "feature",
                "feature_key": "mentor_sessions",
                "quantity": 2,
                "unit_price_paise": 50000,
            },
            {"item_type": "feature", "feature_key": "resume_reviews", "quantity": 1},
        ],
    },
    {
        "sku": "DEMO-MOCK-PACK-10",
        "name": "DEMO Mock pack (10)",
        "kind": "mock_pack",
        "amount": 79900,
        "days": 90,
        "items": [{"item_type": "feature", "feature_key": "mock_tests", "quantity": 10}],
    },
    {
        "sku": "DEMO-ALL-ACCESS-M",
        "name": "DEMO All-access monthly",
        "kind": "subscription_plan",
        "amount": 49900,
        "recurring": True,
        "items": [
            {"item_type": "feature", "feature_key": "all_courses"},
            {"item_type": "feature", "feature_key": "all_tests"},
        ],
    },
]


class ProductionRefused(RuntimeError):
    pass


def guard() -> None:
    if not seeds_allowed():
        raise ProductionRefused("commerce_demo seed refuses to run outside APP_ENV local/dev/test")


async def seed(session: AsyncSession) -> dict[str, int]:
    from app.modules.identity.models import User

    guard()
    await system_context(session, "seed.commerce_demo")
    # finance@ is an Admin account since D2 (finance desk folded into Admin).
    creator = (
        await session.execute(select(User.id).where(func.lower(User.email) == "finance@dev.techdrona.local"))
    ).scalar_one_or_none() or (await session.execute(select(User.id).limit(1))).scalar_one_or_none()
    if creator is None:
        raise SystemExit("run `python -m app.seeds.dev_users` first (prices need a creator)")
    made = {"products": 0, "coupons": 0}
    now = utcnow()
    for spec in PRODUCTS:
        if (await session.execute(select(Product.id).where(Product.sku == spec["sku"]))).scalar_one_or_none():
            continue
        p = Product(
            id=uuid7(),
            sku=spec["sku"],
            name=spec["name"],
            product_kind=spec["kind"],
            description_md="Demo data (dev only).",
            refund_policy_key="standard_7d_20pct",
            status="active",
            gst_rate=Decimal("18.00"),
        )
        session.add(p)
        await session.flush()
        for it in spec["items"]:
            session.add(ProductItem(id=uuid7(), product_id=p.id, **it))
        if spec["amount"] is None:
            continue
        recurring = bool(spec.get("recurring"))
        plan = Plan(
            id=uuid7(),
            product_id=p.id,
            code=f"{spec['sku']}-PLAN",
            billing_type="recurring" if recurring else "one_time",
            interval_unit="month" if recurring else None,
            interval_count=1 if recurring else None,
            access_duration_days=None if recurring else spec["days"],
            status="active",
        )
        session.add(plan)
        await session.flush()
        session.add(
            Price(
                id=uuid7(),
                plan_id=plan.id,
                amount_paise=spec["amount"],
                is_recurring=recurring,
                valid_from=now - timedelta(minutes=1),
                created_by=creator,
            )
        )
        made["products"] += 1
    for code, kw in (
        ("DEMO25", {"discount_type": "percent", "percent_off": Decimal("25"), "max_redemptions": 100}),
        (
            "DEMOFLAT200",
            {
                "discount_type": "flat",
                "amount_off_paise": 20000,
                "min_order_paise": 100000,
                "max_redemptions": 100,
            },
        ),
    ):
        if (await session.execute(select(Coupon.id).where(Coupon.code == code))).scalar_one_or_none():
            continue
        session.add(
            Coupon(
                id=uuid7(),
                code=code,
                valid_from=now - timedelta(minutes=1),
                valid_until=now + timedelta(days=90),
                created_by=creator,
                **kw,
            )
        )
        made["coupons"] += 1
    await session.flush()
    return made


async def main() -> None:
    s = get_settings()
    guard()
    engine = make_engine(s.DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            print(await seed(session))
            await sync_touched(session, "commerce", "identity")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
