"""Prices, GST split, coupons and checkout quotes (COM-03, FR-COM-002/007).

Prices are GST-inclusive for D2C: the inclusive amount after discount is split into taxable
value and CGST+SGST (intra-state, place of supply = seller state) or IGST. One coupon per
order (no stacking); coupons apply to one-time purchases only (never to mandates).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_system as core_as_system
from app.core.money import percent_of, round_half_up
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.commerce import datastore as ds
from app.modules.commerce import policy
from app.modules.commerce.models import Coupon, CouponRedemption, Order, Plan, Price, Product, ProductItem
from app.modules.entitlements import public as ent_pub
from app.modules.entitlements import service as ent_svc

COUPON_ERROR = {
    "invalid": "coupon_invalid",
    "expired": "coupon_expired",
    "cap_reached": "coupon_cap_reached",
    "not_applicable": "coupon_not_applicable",
    "min_order_not_met": "coupon_not_applicable",
    "new_users_only": "coupon_not_applicable",
}
SELLABLE_KINDS = frozenset({"course", "bundle", "placement_package", "mock_pack", "subscription_plan"})


@asynccontextmanager
async def as_system(
    session: AsyncSession, job: str, principal: Principal | None = None
) -> AsyncGenerator[None]:
    """Run a block in system context, flush its writes, then restore the previous RLS context
    (``app.core.db.as_system``; also on error, DB-06). Used where shared rows must be written
    (coupon counters, fulfilment) after app-level checks. ``principal`` is kept for call-site
    compatibility; the restored context is whatever was active before the block."""
    async with core_as_system(session, job):
        yield
        await ds.flush(session)


@dataclass(frozen=True, slots=True)
class GstLine:
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int

    @property
    def tax_paise(self) -> int:
        return self.cgst_paise + self.sgst_paise + self.igst_paise

    @property
    def total_paise(self) -> int:
        return self.taxable_paise + self.tax_paise


def split_inclusive(amount_paise: int, rate: Decimal, *, intra_state: bool) -> GstLine:
    """Split a GST-inclusive amount; tax = amount - taxable so the total is exact."""
    taxable = round_half_up(Decimal(amount_paise) * 100 / (100 + rate))
    tax = amount_paise - taxable
    if intra_state:
        c = tax // 2
        return GstLine(taxable, c, tax - c, 0)
    return GstLine(taxable, 0, 0, tax)


def add_exclusive(taxable_paise: int, rate: Decimal, *, intra_state: bool) -> GstLine:
    if intra_state:
        half = percent_of(taxable_paise, rate / 2)
        return GstLine(taxable_paise, half, half, 0)
    return GstLine(taxable_paise, 0, 0, percent_of(taxable_paise, rate))


def is_intra_state(state_code: str | None) -> tuple[bool, str]:
    seller = policy.commerce_settings().SELLER_STATE_CODE
    pos = state_code or seller
    return pos == seller, pos


async def load_price(
    session: AsyncSession, price_id: uuid.UUID, now: datetime | None = None
) -> tuple[Price, Plan, Product]:
    from app.core.errors import ProblemError

    now = now or utcnow()
    row = (
        await ds.execute(
            session,
            select(Price, Plan, Product)
            .join(Plan, Plan.id == Price.plan_id)
            .join(Product, Product.id == Plan.product_id)
            .where(
                Price.id == price_id,
                Price.is_active.is_(True),
                Price.valid_from <= now,
                or_(Price.valid_until.is_(None), Price.valid_until > now),
                Plan.status == "active",
                Product.status == "active",
            ),
        )
    ).first()
    if row is None:
        raise ProblemError("not_found")
    return row[0], row[1], row[2]


def current_price_filter(now: datetime) -> Any:
    return (
        Price.is_active.is_(True)
        & (Price.valid_from <= now)
        & or_(Price.valid_until.is_(None), Price.valid_until > now)
    )


@dataclass(slots=True)
class CouponCheck:
    status: str
    coupon: Coupon | None = None
    discount_paise: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "applicable"


async def check_coupon(
    session: AsyncSession,
    code: str,
    *,
    user_id: uuid.UUID,
    product: Product,
    list_paise: int,
    now: datetime,
    for_update: bool = False,
) -> CouponCheck:
    """Coupon rules (FR-COM-007). Must run in system context: global caps count every
    user's redemptions. ``for_update`` locks the coupon row (order creation)."""
    q = select(Coupon).where(func.lower(Coupon.code) == code.strip().lower())
    if for_update:
        q = q.with_for_update()
    c = (await ds.execute(session, q)).scalar_one_or_none()
    if c is None or c.status == "paused":
        return CouponCheck("invalid")
    if c.status == "expired" or c.valid_from > now or (c.valid_until is not None and c.valid_until <= now):
        return CouponCheck("expired", c)
    if c.applicable_product_ids and product.id not in c.applicable_product_ids:
        return CouponCheck("not_applicable", c)
    if c.min_order_paise is not None and list_paise < c.min_order_paise:
        return CouponCheck("min_order_not_met", c)
    live = (CouponRedemption.status == "consumed") | (
        (CouponRedemption.status == "reserved") & (CouponRedemption.reserved_until > now)
    )
    if c.max_redemptions is not None:
        used = (
            await ds.execute(
                session,
                select(func.count())
                .select_from(CouponRedemption)
                .where(CouponRedemption.coupon_id == c.id, live),
            )
        ).scalar_one()
        if used >= c.max_redemptions:
            return CouponCheck("cap_reached", c)
    mine = (
        await ds.execute(
            session,
            select(func.count())
            .select_from(CouponRedemption)
            .where(CouponRedemption.coupon_id == c.id, CouponRedemption.user_id == user_id, live),
        )
    ).scalar_one()
    if mine >= c.per_user_limit:
        return CouponCheck("cap_reached", c)
    if c.first_time_only:
        prior = (
            await ds.execute(
                session,
                select(func.count())
                .select_from(Order)
                .where(
                    Order.user_id == user_id, Order.status.in_(("paid", "refunded", "partially_refunded"))
                ),
            )
        ).scalar_one()
        if prior:
            return CouponCheck("new_users_only", c)
    if c.discount_type == "percent":
        assert c.percent_off is not None
        discount = percent_of(list_paise, c.percent_off)
    elif c.discount_type == "flat":
        assert c.amount_off_paise is not None
        discount = min(c.amount_off_paise, list_paise)
    else:
        discount = list_paise
    return CouponCheck("applicable", c, min(discount, list_paise))


@dataclass(slots=True)
class Quote:
    price: Price
    plan: Plan
    product: Product
    list_paise: int
    discount_paise: int  # GST-inclusive discount shown to the buyer
    line: GstLine
    subtotal_pre_tax: int
    discount_pre_tax: int
    intra_state: bool
    place_of_supply: str
    coupon: CouponCheck | None
    access_ends_at: datetime | None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    blocking: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_paise(self) -> int:
        return self.line.total_paise

    def to_json(self) -> dict[str, Any]:
        c = self.coupon
        coupon: dict[str, Any] | None = None
        if c is not None:
            coupon = {"code": c.coupon.code if c.coupon else None, "status": c.status}
            if c.coupon is not None and c.coupon.percent_off is not None and c.ok:
                coupon["percent_off"] = float(c.coupon.percent_off)
        return {
            "price_id": str(self.price.id),
            "product": {
                "sku": self.product.sku,
                "name": self.product.name,
                "product_kind": self.product.product_kind,
            },
            "list_amount_paise": self.list_paise,
            "discount_paise": self.discount_paise,
            "taxable_paise": self.line.taxable_paise,
            "cgst_paise": self.line.cgst_paise,
            "sgst_paise": self.line.sgst_paise,
            "igst_paise": self.line.igst_paise,
            "total_paise": self.total_paise,
            "gst_rate": str(self.product.gst_rate),
            "place_of_supply": self.place_of_supply,
            "coupon": coupon,
            "warnings": self.warnings,
            "blocking": self.blocking,
            "refund_rule": policy.REFUND_RULE_TEXT,
            "access_ends_at": self.access_ends_at.isoformat() if self.access_ends_at else None,
        }


async def _item_refs(session: AsyncSession, product_id: uuid.UUID) -> set[tuple[str, str]]:
    rows = (
        await ds.execute(session, select(ProductItem).where(ProductItem.product_id == product_id))
    ).scalars()
    refs: set[tuple[str, str]] = set()
    for i in rows:
        ref = i.course_id or i.test_id or i.company_path_id or i.topic_id
        if ref is not None:
            refs.add((i.item_type, str(ref)))
        elif i.feature_key and i.feature_key.startswith("all_"):
            refs.add(("feature", i.feature_key))
    return refs


_FEATURE_COVERS = {
    "all_courses": "course",
    "all_tests": "test",
    "all_company_paths": "company_path",
    "all_practice": "topic_practice",
}


def _covers(holder: set[tuple[str, str]], target: set[tuple[str, str]]) -> bool:
    if holder & target:
        return True
    covered_kinds = {
        _FEATURE_COVERS[ref] for kind, ref in holder if kind == "feature" and ref in _FEATURE_COVERS
    }
    return any(kind in covered_kinds for kind, _ in target)


async def ownership_checks(
    session: AsyncSession, user_id: uuid.UUID, product: Product, new_ends_at: datetime | None, now: datetime
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """BR-ENT-05 (block duplicate) and BR-ENT-06/07 (warn on overlap)."""
    warnings: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    ents = [
        e
        for e in await ent_pub.user_entitlements(session, user_id, statuses=("active", "grace"))
        if e.product_id is not None
    ]
    target = await _item_refs(session, product.id)
    for e in ents:
        if ent_svc.effective_state(e, now) not in ("active", "grace"):
            continue
        assert e.product_id is not None
        if e.product_id == product.id:
            if e.ends_at is None or (
                new_ends_at is not None and e.ends_at + timedelta(days=1) >= new_ends_at
            ):
                blocking.append(
                    {
                        "code": "already_owned",
                        "source_type": e.source_type,
                        "ends_at": e.ends_at.isoformat() if e.ends_at else None,
                    }
                )
                continue
        elif not _covers(await _item_refs(session, e.product_id), target):
            continue
        code = "included_in_subscription" if e.source_type == "subscription" else "overlaps_existing_access"
        warnings.append(
            {
                "code": code,
                "source_type": e.source_type,
                "ends_at": e.ends_at.isoformat() if e.ends_at else None,
            }
        )
    return warnings, blocking


async def build_quote(
    session: AsyncSession,
    principal: Principal,
    *,
    price_id: uuid.UUID,
    coupon_code: str | None,
    state_code: str | None,
    lock_coupon: bool = False,
    now: datetime | None = None,
) -> Quote:
    """Server-side price computation; client amounts are never trusted."""
    from app.core.errors import ProblemError

    now = now or utcnow()
    price, plan, product = await load_price(session, price_id, now)
    if product.product_kind not in SELLABLE_KINDS or plan.billing_type != "one_time":
        raise ProblemError(
            "validation_failed",
            errors=[
                {
                    "field": "price_id",
                    "code": "not_one_time",
                    "message": "Use subscriptions for recurring plans",
                }
            ],
        )
    intra, pos = is_intra_state(state_code)
    list_paise = price.amount_paise
    coupon: CouponCheck | None = None
    discount = 0
    if coupon_code:
        async with as_system(session, "commerce.coupon_check", principal):
            coupon = await check_coupon(
                session,
                coupon_code,
                user_id=principal.user_id,
                product=product,
                list_paise=list_paise,
                now=now,
                for_update=lock_coupon,
            )
        if coupon.ok:
            discount = coupon.discount_paise
    rate = Decimal(product.gst_rate)
    if price.tax_inclusive:
        line = split_inclusive(list_paise - discount, rate, intra_state=intra)
        subtotal = split_inclusive(list_paise, rate, intra_state=intra).taxable_paise
    else:
        line = add_exclusive(list_paise - discount, rate, intra_state=intra)
        subtotal = list_paise
    ends = now + timedelta(days=plan.access_duration_days) if plan.access_duration_days else None
    warnings, blocking = await ownership_checks(session, principal.user_id, product, ends, now)
    return Quote(
        price=price,
        plan=plan,
        product=product,
        list_paise=list_paise,
        discount_paise=discount,
        line=line,
        subtotal_pre_tax=subtotal,
        discount_pre_tax=subtotal - line.taxable_paise,
        intra_state=intra,
        place_of_supply=pos,
        coupon=coupon,
        access_ends_at=ends,
        warnings=warnings,
        blocking=blocking,
    )
