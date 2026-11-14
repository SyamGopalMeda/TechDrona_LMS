"""Commerce public API for other modules: store-neutral (``TD_STORE_COMMERCE`` postgres/firestore).

Other modules must not query commerce tables (``products``, ``product_items``, ``plans``,
``prices``, ``coupons``, ``orders``, ``invoices``, ``subscriptions``, ...) with their own SQL:
once commerce is on Firestore that SQL would read stale Postgres rows. They call these functions
instead. Every function takes the caller's ``AsyncSession`` (its RLS scope applies exactly as
before) and returns plain values or the commerce ORM rows (transient instances on Firestore).

Current callers and what they should switch to (requests in docs/firebase/agents/data-money.md):

* ``entitlements.service.quotas_for_product`` -> ``product_quotas``
* ``entitlements.service.covering_scope`` -> ``product_ids_covering``
* ``entitlements.router._titles`` -> ``product_names``; ``admin.catalogue`` -> ``catalogue``
* ``wiring._product_items`` -> ``product_item_refs``
* ``admin.accounts.dashboard`` -> ``paid_orders_since``
* ``notifications.consumers`` / ``support.router`` (done) -> ``get_invoice`` / ``get_order`` /
  ``get_subscription`` / ``renewing_subscriptions`` / ``recent_orders``

Non-table helpers other modules already import are re-exported so one import path suffices.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commerce import datastore as ds
from app.modules.commerce.models import Invoice, Order, Plan, Product, ProductItem, Subscription


async def execute(session: AsyncSession, stmt: Any) -> Any:
    """Escape hatch: run any ``select`` over commerce tables on the configured store."""
    return await ds.execute(session, stmt)


# --------------------------------------------------------------------------- catalogue


async def product_quotas(
    session: AsyncSession, product_id: uuid.UUID, feature_keys: Iterable[str]
) -> list[tuple[str, int | None]]:
    """``(feature_key, quantity)`` of the product's items whose feature is one of ``feature_keys``."""
    rows = (
        await ds.execute(
            session,
            select(ProductItem.feature_key, ProductItem.quantity).where(
                ProductItem.product_id == product_id, ProductItem.feature_key.in_(tuple(feature_keys))
            ),
        )
    ).all()
    return [(k, q) for k, q in rows]


async def product_item_refs(
    session: AsyncSession, product_id: uuid.UUID
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """(course ids, test ids) a product grants."""
    rows = (
        await ds.execute(
            session,
            select(ProductItem.course_id, ProductItem.test_id).where(ProductItem.product_id == product_id),
        )
    ).all()
    return {r[0] for r in rows if r[0]}, {r[1] for r in rows if r[1]}


async def product_ids_covering(
    session: AsyncSession,
    *,
    course_ids: Iterable[uuid.UUID] = (),
    test_ids: Iterable[uuid.UUID] = (),
    company_path_ids: Iterable[uuid.UUID] = (),
    topic_ids: Iterable[uuid.UUID] = (),
    feature_keys: Iterable[str] = (),
) -> set[uuid.UUID]:
    """Products with an item on any of the given resources or features."""
    conds = []
    for col, vals in (
        (ProductItem.course_id, list(course_ids)),
        (ProductItem.test_id, list(test_ids)),
        (ProductItem.company_path_id, list(company_path_ids)),
        (ProductItem.topic_id, list(topic_ids)),
        (ProductItem.feature_key, list(feature_keys)),
    ):
        if vals:
            conds.append(col.in_(vals))
    if not conds:
        return set()
    return set((await ds.execute(session, select(ProductItem.product_id).where(or_(*conds)))).scalars())


async def product_names(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = list(ids)
    if not ids:
        return {}
    rows = await ds.execute(session, select(Product.id, Product.name).where(Product.id.in_(ids)))
    return {i: n for i, n in rows.all()}


async def catalogue(
    session: AsyncSession, *, include_drafts: bool, sku: str | None = None
) -> list[dict[str, Any]]:
    from app.modules.commerce.admin import catalogue as _catalogue

    return await _catalogue(session, include_drafts=include_drafts, sku=sku)


# --------------------------------------------------------------------------- orders, invoices, subscriptions


async def get_order(session: AsyncSession, order_id: uuid.UUID) -> Order | None:
    return await ds.get(session, Order, order_id)


async def recent_orders(session: AsyncSession, user_id: uuid.UUID, limit: int = 10) -> list[Order]:
    q = select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(limit)
    return list((await ds.execute(session, q)).scalars())


async def paid_orders_since(session: AsyncSession, since: datetime) -> tuple[int, int]:
    """(count, total paise) of orders in status ``paid`` with ``paid_at > since``."""
    row = (
        await ds.execute(
            session,
            select(func.count(), func.coalesce(func.sum(Order.total_paise), 0)).where(
                Order.status == "paid", Order.paid_at > since
            ),
        )
    ).one()
    return int(row[0]), int(row[1])


async def get_invoice(session: AsyncSession, invoice_id: uuid.UUID) -> Invoice | None:
    return await ds.get(session, Invoice, invoice_id)


async def get_subscription(session: AsyncSession, subscription_id: uuid.UUID) -> Subscription | None:
    return await ds.get(session, Subscription, subscription_id)


async def renewing_subscriptions(
    session: AsyncSession, now: datetime, horizon: datetime
) -> list[tuple[Subscription, Plan]]:
    """Active, not cancelling subscriptions whose period ends in ``(now, horizon]``, with plan."""
    rows = (
        await ds.execute(
            session,
            select(Subscription, Plan)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(
                Subscription.status == "active",
                Subscription.cancel_at_period_end.is_(False),
                Subscription.current_period_end.is_not(None),
                Subscription.current_period_end > now,
                Subscription.current_period_end <= horizon,
            ),
        )
    ).all()
    return [(s, p) for s, p in rows]


# --------------------------------------------------------------------------- non-table helpers


def get_document_store() -> Any:
    from app.modules.commerce.documents import get_document_store as _get

    return _get()


def gateway_status() -> Any:
    from app.modules.commerce.gateway import gateway_status as _status

    return _status()


__all__ = [
    "catalogue",
    "execute",
    "gateway_status",
    "get_document_store",
    "get_invoice",
    "get_order",
    "get_subscription",
    "paid_orders_since",
    "product_ids_covering",
    "product_item_refs",
    "product_names",
    "product_quotas",
    "recent_orders",
    "renewing_subscriptions",
]
