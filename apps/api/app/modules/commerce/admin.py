"""Finance-side services: catalogue management, coupons, price changes, Dual approvals for
commerce/entitlement actions, reconciliation and reports."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.commerce import policy
from app.modules.commerce import service as svc
from app.modules.commerce.gateway import GatewayUnavailable, PaymentGateway
from app.modules.commerce.models import (
    Coupon,
    Order,
    Payment,
    PaymentWebhookEvent,
    Plan,
    Price,
    Product,
    ProductItem,
    ReconciliationRun,
    Refund,
)
from app.modules.entitlements import service as ent
from app.modules.entitlements.models import Entitlement

COMMERCE_ACTIONS = frozenset(
    {
        "commerce.refund",
        "commerce.coupon.activate",
        "commerce.price.create",
        "entitlements.grant.bulk",
    }
)


# --------------------------------------------------------------------------- serialisers


def product_json(
    p: Product, items: list[ProductItem] | None = None, plans: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "product_id": str(p.id),
        "sku": p.sku,
        "name": p.name,
        "product_kind": p.product_kind,
        "description_md": p.description_md,
        "sac_code": p.sac_code,
        "gst_rate": str(p.gst_rate),
        "refund_policy_key": p.refund_policy_key,
        "refund_rule": policy.REFUND_RULE_TEXT,
        "status": p.status,
    }
    if items is not None:
        out["unlocks"] = [
            {
                "item_type": i.item_type,
                "ref_id": str(i.course_id or i.test_id or i.company_path_id or i.topic_id)
                if (i.course_id or i.test_id or i.company_path_id or i.topic_id)
                else None,
                "feature_key": i.feature_key,
                "quantity": i.quantity,
            }
            for i in items
        ]
    if plans is not None:
        out["plans"] = plans
    return out


def plan_json(pl: Plan, prices: list[Price]) -> dict[str, Any]:
    from app.modules.commerce.pricing import split_inclusive

    def price(pr: Price) -> dict[str, Any]:
        line = split_inclusive(pr.amount_paise, policy.DEFAULT_GST_RATE, intra_state=True)
        return {
            "price_id": str(pr.id),
            "amount_paise": pr.amount_paise,
            "currency": pr.currency,
            "tax_inclusive": pr.tax_inclusive,
            "is_recurring": pr.is_recurring,
            "valid_from": pr.valid_from.isoformat(),
            "valid_until": pr.valid_until.isoformat() if pr.valid_until else None,
            "is_active": pr.is_active,
            "gst_breakup_intra_state": {
                "taxable_paise": line.taxable_paise,
                "cgst_paise": line.cgst_paise,
                "sgst_paise": line.sgst_paise,
            },
        }

    return {
        "plan_id": str(pl.id),
        "code": pl.code,
        "billing_type": pl.billing_type,
        "interval_unit": pl.interval_unit,
        "interval_count": pl.interval_count,
        "access_duration_days": pl.access_duration_days,
        "status": pl.status,
        "prices": [price(p) for p in prices],
    }


async def catalogue(
    session: AsyncSession, *, include_drafts: bool, sku: str | None = None, now: datetime | None = None
) -> list[dict[str, Any]]:
    now = now or utcnow()
    q = select(Product).order_by(Product.created_at)
    if not include_drafts:
        q = q.where(Product.status == "active")
    if sku:
        q = q.where(func.lower(Product.sku) == sku.lower())
    products = (await session.execute(q)).scalars().all()
    out = []
    for p in products:
        items = list(
            (await session.execute(select(ProductItem).where(ProductItem.product_id == p.id))).scalars()
        )
        plans = []
        pq = select(Plan).where(Plan.product_id == p.id)
        if not include_drafts:
            pq = pq.where(Plan.status == "active")
        for pl in (await session.execute(pq.order_by(Plan.created_at))).scalars():
            prq = select(Price).where(Price.plan_id == pl.id)
            if not include_drafts:
                from app.modules.commerce.pricing import current_price_filter

                prq = prq.where(current_price_filter(now))
            plans.append(
                plan_json(pl, list((await session.execute(prq.order_by(Price.valid_from))).scalars()))
            )
        out.append(product_json(p, items, plans))
    return out


# --------------------------------------------------------------------------- products, plans, prices


async def create_product(session: AsyncSession, principal: Principal, body: Any) -> Product:
    exists = (
        await session.execute(select(Product.id).where(func.lower(Product.sku) == body.sku.lower()))
    ).scalar_one_or_none()
    if exists:
        raise ProblemError(
            "validation_failed", errors=[{"field": "sku", "code": "duplicate", "message": "SKU exists"}]
        )
    p = Product(
        id=uuid7(),
        sku=body.sku,
        name=body.name,
        product_kind=body.product_kind,
        description_md=body.description_md,
        sac_code=body.sac_code,
        gst_rate=body.gst_rate,
        refund_policy_key=body.refund_policy_key,
        status=body.status,
    )
    session.add(p)
    await session.flush()
    for it in body.items:
        session.add(
            ProductItem(
                id=uuid7(),
                product_id=p.id,
                item_type=it.item_type,
                course_id=it.ref_id if it.item_type == "course" else None,
                test_id=it.ref_id if it.item_type == "test" else None,
                company_path_id=it.ref_id if it.item_type == "company_path" else None,
                topic_id=it.ref_id if it.item_type == "topic_practice" else None,
                feature_key=it.feature_key if it.item_type == "feature" else None,
                quantity=it.quantity,
                unit_price_paise=it.unit_price_paise,
            )
        )
    await session.flush()
    await audit(
        session, principal, "product.created", "product", p.id, after={"sku": p.sku, "kind": p.product_kind}
    )
    return p


async def create_plan(session: AsyncSession, principal: Principal, product: Product, body: Any) -> Plan:
    if body.billing_type == "recurring" and product.product_kind != "subscription_plan":
        raise ProblemError(
            "validation_failed",
            errors=[
                {
                    "field": "billing_type",
                    "code": "invalid",
                    "message": "Recurring plans need a subscription_plan",
                }
            ],
        )
    pl = Plan(
        id=uuid7(),
        product_id=product.id,
        code=body.code,
        billing_type=body.billing_type,
        interval_unit=body.interval_unit,
        interval_count=body.interval_count,
        access_duration_days=body.access_duration_days,
        gateway_plan_ids=body.gateway_plan_ids or {},
        status="active",
    )
    session.add(pl)
    await session.flush()
    await audit(session, principal, "plan.created", "plan", pl.id, after={"code": pl.code})
    return pl


async def price_change_needs_dual(session: AsyncSession, plan: Plan, amount_paise: int) -> bool:
    current = (
        await session.execute(
            select(Price.amount_paise)
            .where(Price.plan_id == plan.id, Price.is_active.is_(True))
            .order_by(Price.valid_from.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if current and Decimal(current - amount_paise) * 100 / current > policy.PRICE_DUAL_DECREASE_PCT:
        return True
    from app.modules.commerce.models import Subscription

    subs = (
        await session.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.plan_id == plan.id, Subscription.status.in_(("active", "pending", "halted")))
        )
    ).scalar_one()
    return bool(subs)


async def apply_price(
    session: AsyncSession,
    plan: Plan,
    *,
    amount_paise: int,
    valid_from: datetime,
    valid_until: datetime | None,
    created_by: uuid.UUID,
) -> Price:
    """Insert a price, closing an overlapping open-ended active price at ``valid_from``."""
    if plan.billing_type == "recurring" and amount_paise > policy.MANDATE_MAX_PAISE:
        raise ProblemError("recurring_amount_exceeds_mandate_limit", max_paise=policy.MANDATE_MAX_PAISE)
    for old in (
        await session.execute(
            select(Price)
            .where(
                Price.plan_id == plan.id,
                Price.is_active.is_(True),
                or_(Price.valid_until.is_(None), Price.valid_until > valid_from),
            )
            .with_for_update()
        )
    ).scalars():
        if old.valid_from >= valid_from:
            old.is_active = False
        else:
            old.valid_until = valid_from
    await session.flush()
    pr = Price(
        id=uuid7(),
        plan_id=plan.id,
        amount_paise=amount_paise,
        is_recurring=plan.billing_type == "recurring",
        valid_from=valid_from,
        valid_until=valid_until,
        created_by=created_by,
    )
    session.add(pr)
    await session.flush()
    return pr


# --------------------------------------------------------------------------- coupons


async def pending_coupon_approvals(
    session: AsyncSession, coupon_ids: list[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """coupon id -> id of its pending ``commerce.coupon.activate`` approval request."""
    from app.modules.rbac.models import ApprovalRequest

    if not coupon_ids:
        return {}
    rows = await session.execute(
        select(ApprovalRequest.target_id, ApprovalRequest.id).where(
            ApprovalRequest.action_type == "commerce.coupon.activate",
            ApprovalRequest.target_type == "coupon",
            ApprovalRequest.status == "pending",
            ApprovalRequest.target_id.in_(coupon_ids),
        )
    )
    return {t: i for t, i in rows.all() if t is not None}


def coupon_json(c: Coupon, approval_request_id: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "approval_request_id": str(approval_request_id) if approval_request_id else None,
        "coupon_id": str(c.id),
        "code": c.code,
        "discount_type": c.discount_type,
        "percent_off": float(c.percent_off) if c.percent_off is not None else None,
        "amount_off_paise": c.amount_off_paise,
        "applicable_product_ids": [str(x) for x in c.applicable_product_ids],
        "min_order_paise": c.min_order_paise,
        "max_redemptions": c.max_redemptions,
        "per_user_limit": c.per_user_limit,
        "redeemed_count": c.redeemed_count,
        "valid_from": c.valid_from.isoformat(),
        "valid_until": c.valid_until.isoformat() if c.valid_until else None,
        "first_time_only": c.first_time_only,
        "status": c.status,
    }


def coupon_needs_dual(discount_type: str, percent_off: Decimal | None, max_redemptions: int | None) -> bool:
    big = discount_type == "free_access" or (
        percent_off is not None and percent_off > policy.COUPON_DUAL_PERCENT
    )
    many = max_redemptions is None or max_redemptions > policy.COUPON_DUAL_REDEMPTIONS
    return big or many


# --------------------------------------------------------------------------- approvals


async def execute_approval(
    session: AsyncSession,
    gw: PaymentGateway,
    approver: Principal,
    action_type: str,
    payload: dict[str, Any],
    requested_by: uuid.UUID,
) -> dict[str, Any]:
    if action_type == "commerce.refund":
        r = (
            await session.execute(
                select(Refund).where(Refund.id == uuid.UUID(payload["refund_id"])).with_for_update()
            )
        ).scalar_one()
        r = await svc.execute_refund(
            session,
            gw,
            r,
            approver,
            order_item_ids=[uuid.UUID(x) for x in payload.get("order_item_ids") or []] or None,
        )
        return {"refund": svc.refund_json(r)}
    if action_type == "commerce.coupon.activate":
        c = (
            await session.execute(select(Coupon).where(Coupon.id == uuid.UUID(payload["coupon_id"])))
        ).scalar_one()
        c.status = "active"
        await session.flush()
        return {"coupon": coupon_json(c)}
    if action_type == "commerce.price.create":
        plan = (
            await session.execute(select(Plan).where(Plan.id == uuid.UUID(payload["plan_id"])))
        ).scalar_one()
        pr = await apply_price(
            session,
            plan,
            amount_paise=int(payload["amount_paise"]),
            valid_from=datetime.fromisoformat(payload["valid_from"]),
            valid_until=datetime.fromisoformat(payload["valid_until"])
            if payload.get("valid_until")
            else None,
            created_by=requested_by,
        )
        return {"price_id": str(pr.id)}
    if action_type == "entitlements.grant.bulk":
        from app.modules.entitlements.router import do_manual_grant

        return await do_manual_grant(session, approver, payload, granted_by=requested_by)
    raise ProblemError("not_found")


# --------------------------------------------------------------------------- reconciliation & reports


async def run_reconciliation(
    session: AsyncSession, gw: PaymentGateway, *, range_from: datetime, range_to: datetime, triggered_by: str
) -> ReconciliationRun:
    """FR-COM-013 (system context): compares our payments/orders with the provider and
    recovers missed captures (stale pending orders are fulfilled from the fetched state).
    COM-13: also settles refunds still ``processing`` from the provider's refund state,
    re-submits approved refunds that never reached the provider, and re-syncs live
    subscriptions (missed ``subscription.*`` webhooks)."""
    actor = ent.Actor.system("commerce.reconciliation")
    mismatches: list[dict[str, Any]] = []
    summary = {"orders_checked": 0, "payments_checked": 0, "recovered": 0, "provider_errors": 0}
    stale_before = utcnow() - policy.PENDING_ORDER_RECHECK
    pending = (
        (
            await session.execute(
                select(Order).where(
                    Order.status.in_(("created", "pending_payment", "expired")),
                    Order.gateway == gw.name,
                    Order.gateway_order_id.is_not(None),
                    Order.created_at >= range_from,
                    Order.created_at < range_to,
                    Order.created_at <= stale_before,
                )
            )
        )
        .scalars()
        .all()
    )
    for o in pending:
        summary["orders_checked"] += 1
        try:
            assert o.gateway_order_id is not None
            for gp in await gw.fetch_order_payments(o.gateway_order_id):
                _, _, done = await svc.apply_payment(session, gw, gp, actor)
                if done:
                    summary["recovered"] += 1
                    mismatches.append({"type": "missed_capture_recovered", "order_number": o.order_number})
        except GatewayUnavailable:
            summary["provider_errors"] += 1
    pays = (
        (
            await session.execute(
                select(Payment).where(
                    Payment.gateway == gw.name,
                    Payment.status.in_(("captured", "refunded", "partially_refunded")),
                    Payment.created_at >= range_from,
                    Payment.created_at < range_to,
                )
            )
        )
        .scalars()
        .all()
    )
    for p in pays:
        summary["payments_checked"] += 1
        try:
            gp = await gw.fetch_payment(p.gateway_payment_id)
        except (GatewayUnavailable, KeyError):
            summary["provider_errors"] += 1
            continue
        if gp.amount_paise != p.amount_paise:
            mismatches.append(
                {
                    "type": "amount_mismatch",
                    "payment_id": str(p.id),
                    "ours": p.amount_paise,
                    "provider": gp.amount_paise,
                }
            )
        if gp.status not in ("captured", "refunded"):
            mismatches.append(
                {"type": "status_mismatch", "payment_id": str(p.id), "ours": p.status, "provider": gp.status}
            )
    paid_wo_payment = (
        (
            await session.execute(
                select(Order.order_number).where(
                    Order.status == "paid",
                    Order.total_paise > 0,
                    Order.gateway == gw.name,
                    Order.paid_at >= range_from,
                    Order.paid_at < range_to,
                    ~select(Payment.id)
                    .where(Payment.order_id == Order.id, Payment.status == "captured")
                    .exists(),
                )
            )
        )
        .scalars()
        .all()
    )
    mismatches += [{"type": "paid_without_captured_payment", "order_number": n} for n in paid_wo_payment]
    failed_events = (
        await session.execute(
            select(func.count())
            .select_from(PaymentWebhookEvent)
            .where(
                PaymentWebhookEvent.status == "failed",
                PaymentWebhookEvent.received_at >= range_from,
                PaymentWebhookEvent.received_at < range_to,
            )
        )
    ).scalar_one()
    summary["failed_webhook_events"] = int(failed_events)
    await _reconcile_refunds(session, gw, actor, summary, mismatches)
    await _reconcile_subscriptions(session, gw, actor, summary, mismatches)
    summary["mismatches"] = len(mismatches)
    run = ReconciliationRun(
        id=uuid7(),
        gateway=gw.name,
        range_from=range_from,
        range_to=range_to,
        summary=summary,
        mismatches=mismatches,
        triggered_by=triggered_by,
    )
    session.add(run)
    await session.flush()
    return run


async def _reconcile_refunds(
    session: AsyncSession,
    gw: PaymentGateway,
    actor: ent.Actor,
    summary: dict[str, Any],
    mismatches: list[dict[str, Any]],
) -> None:
    summary.update(refunds_checked=0, refunds_settled=0, refunds_resubmitted=0)
    processing = (
        (
            await session.execute(
                select(Refund).where(
                    Refund.status == "processing",
                    Refund.gateway_refund_id.is_not(None),
                    Refund.created_at <= utcnow() - policy.PENDING_ORDER_RECHECK,
                )
            )
        )
        .scalars()
        .all()
    )
    for rf in processing:
        summary["refunds_checked"] += 1
        try:
            assert rf.gateway_refund_id is not None
            gr = await gw.fetch_refund(rf.gateway_refund_id)
        except (GatewayUnavailable, KeyError):
            summary["provider_errors"] += 1
            continue
        if gr.status in ("processed", "failed"):
            await svc.apply_refund_state(session, gr, actor)
            summary["refunds_settled"] += 1
            mismatches.append({"type": f"refund_{gr.status}_recovered", "refund_id": str(rf.id)})
    retried = await svc.retry_refund_submissions(session, gw)
    summary["refunds_resubmitted"] = retried["submitted"]


async def _reconcile_subscriptions(
    session: AsyncSession,
    gw: PaymentGateway,
    actor: ent.Actor,
    summary: dict[str, Any],
    mismatches: list[dict[str, Any]],
) -> None:
    from app.modules.commerce.models import Subscription

    summary.update(subscriptions_checked=0, subscriptions_changed=0)
    subs = (
        (
            await session.execute(
                select(Subscription)
                .where(
                    Subscription.gateway == gw.name,
                    Subscription.status.in_(("authenticated", "active", "pending", "halted", "paused")),
                )
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for sub in subs:
        summary["subscriptions_checked"] += 1
        try:
            gs = await gw.fetch_subscription(sub.gateway_subscription_id)
        except (GatewayUnavailable, KeyError):
            summary["provider_errors"] += 1
            continue
        before = (sub.status, sub.current_period_end)
        await svc.apply_subscription_state(session, sub, gs, actor)
        if (sub.status, sub.current_period_end) != before:
            summary["subscriptions_changed"] += 1
            mismatches.append(
                {"type": "subscription_resynced", "subscription_id": str(sub.id), "status": sub.status}
            )


def run_json(r: ReconciliationRun) -> dict[str, Any]:
    return {
        "run_id": str(r.id),
        "gateway": r.gateway,
        "range_from": r.range_from.isoformat(),
        "range_to": r.range_to.isoformat(),
        "status": r.status,
        "summary": r.summary,
        "mismatches": r.mismatches,
        "triggered_by": r.triggered_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


async def revenue_report(session: AsyncSession, range_from: datetime, range_to: datetime) -> dict[str, Any]:
    """Basic finance report: gross sales, GST, refunds, net, per product kind, manual grants."""
    from app.modules.commerce.models import OrderItem

    sold = (
        await session.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_paise), 0),
                func.coalesce(func.sum(Order.tax_paise), 0),
                func.coalesce(func.sum(Order.discount_paise), 0),
            ).where(
                Order.status.in_(("paid", "refunded", "partially_refunded")),
                Order.paid_at >= range_from,
                Order.paid_at < range_to,
            )
        )
    ).one()
    by_kind = (
        await session.execute(
            select(
                Product.product_kind,
                func.count(OrderItem.id),
                func.coalesce(func.sum(OrderItem.total_paise), 0),
            )
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.status.in_(("paid", "refunded", "partially_refunded")),
                Order.paid_at >= range_from,
                Order.paid_at < range_to,
            )
            .group_by(Product.product_kind)
        )
    ).all()
    refunded = (
        await session.execute(
            select(func.count(Refund.id), func.coalesce(func.sum(Refund.amount_paise), 0)).where(
                Refund.status == "processed",
                Refund.processed_at >= range_from,
                Refund.processed_at < range_to,
            )
        )
    ).one()
    grants = (
        await session.execute(
            select(Entitlement.source_type, func.count())
            .where(
                Entitlement.source_type.in_(("admin_grant", "trial", "coupon_grant")),
                Entitlement.created_at >= range_from,
                Entitlement.created_at < range_to,
            )
            .group_by(Entitlement.source_type)
        )
    ).all()
    gross = int(sold[1])
    return {
        "range_from": range_from.isoformat(),
        "range_to": range_to.isoformat(),
        "orders_paid": int(sold[0]),
        "gross_paise": gross,
        "gst_paise": int(sold[2]),
        "discount_pre_tax_paise": int(sold[3]),
        "refunds_processed": int(refunded[0]),
        "refunded_paise": int(refunded[1]),
        "net_paise": gross - int(refunded[1]),
        "by_product_kind": [
            {"product_kind": k, "items": int(n), "total_paise": int(t)} for k, n, t in by_kind
        ],
        "non_purchase_grants": {k: int(n) for k, n in grants},
        "currency": "INR",
    }
