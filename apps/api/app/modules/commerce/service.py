"""Orders, fulfilment, payments, subscriptions, refunds and GST invoices (ADR-0006).

State is applied only from data fetched from the provider (``PaymentGateway.fetch_*``);
``fulfil_order`` is idempotent and shared by the checkout callback and the webhook worker.
Functions that write shared/platform rows expect system context (``as_system``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.audit import AuditActor, audit
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import ist_date, utcnow
from app.modules.commerce import policy
from app.modules.commerce.gateway import (
    FakePaymentProvider,
    GatewayUnavailable,
    GwPayment,
    GwRefund,
    GwSubscription,
    PaymentGateway,
)
from app.modules.commerce.models import (
    Coupon,
    CouponRedemption,
    Invoice,
    Order,
    OrderItem,
    Payment,
    Plan,
    Price,
    Product,
    Refund,
    Subscription,
)
from app.modules.commerce.pricing import Quote, as_system, split_inclusive
from app.modules.entitlements import service as ent
from app.modules.entitlements.models import Entitlement

log = structlog.get_logger("commerce")

PAYABLE_FROM = ("created", "pending_payment", "expired", "cancelled", "failed")
PAY_RANK = {"created": 0, "failed": 1, "authorized": 1, "captured": 2, "partially_refunded": 3, "refunded": 4}
OPEN_REFUND = ("requested", "approved", "processing")
# Refund amounts that count against what was paid (``orders.refunded_paise``, COM-11).
COMMITTED_REFUND = ("approved", "processing", "processed")
# COM-01: a refund revokes the order's access unless finance marks it as a pure money
# correction (price adjustment, or the refund of a duplicate payment of the same order).
NON_REVOKING_REFUND_REASONS = frozenset({"price_adjustment", "duplicate_payment"})
ACTIVE_SUB = ("created", "authenticated", "active", "pending", "halted", "paused")
TERMINAL_SUB = ("cancelled", "completed", "expired")


def _ts(epoch: int | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, tz=UTC) if epoch else None


# --------------------------------------------------------------------------- buyer checks


async def buyer_checks(session: AsyncSession, principal: Principal, *, paid: bool) -> None:
    """Verified contact; minors need verified guardian consent (BR-ENT-21); adults need the
    ``security_monitoring`` consent for paid plans (PO-03)."""
    from app.modules.identity.models import Consent, GuardianConsent, User

    async with as_system(session, "commerce.buyer_checks", principal):
        user = (await session.execute(select(User).where(User.id == principal.user_id))).scalar_one_or_none()
        if user is None:
            raise ProblemError("not_found")
        if user.email_verified_at is None and user.phone_verified_at is None:
            raise ProblemError("contact_not_verified")
        if user.is_minor:
            ok = (
                await session.execute(
                    select(func.count())
                    .select_from(GuardianConsent)
                    .where(
                        GuardianConsent.child_user_id == user.id,
                        GuardianConsent.status == "verified",
                        GuardianConsent.revoked_at.is_(None),
                    )
                )
            ).scalar_one()
            if not ok:
                raise ProblemError("minor_consent_pending")
        elif paid:
            last = (
                await session.execute(
                    select(Consent.action)
                    .where(Consent.user_id == user.id, Consent.purpose == "security_monitoring")
                    .order_by(Consent.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last != "granted":
                # E2E-04: say exactly which consent paid plans need and how to grant it.
                raise ProblemError(
                    "consent_required",
                    title="Turn on account protection to buy a paid plan",
                    detail=(
                        "Paid plans need 'Account protection and single-user licence checks'. "
                        "Turn it on to continue to payment."
                    ),
                    purposes=["security_monitoring"],
                    reason="paid_plan_requires_security_monitoring",
                    grant={
                        "method": "POST",
                        "path": "/me/consents",
                        "body": {"purpose": "security_monitoring", "action": "granted"},
                        "also_required": ["notice_version"],
                    },
                )


# --------------------------------------------------------------------------- orders


async def next_order_number(session: AsyncSession, now: datetime) -> str:
    n = (await session.execute(text("SELECT nextval('commerce_order_number_seq')"))).scalar_one()
    return f"TD-O-{now.year}-{int(n):08d}"


def order_json(o: Order, items: list[OrderItem] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "order_id": str(o.id),
        "order_number": o.order_number,
        "status": o.status,
        "currency": o.currency,
        "subtotal_paise": o.subtotal_paise,
        "discount_paise": o.discount_paise,
        "tax_paise": o.tax_paise,
        "total_paise": o.total_paise,
        "refunded_paise": o.refunded_paise,
        "gateway": o.gateway,
        "expires_at": o.expires_at.isoformat(),
        "paid_at": o.paid_at.isoformat() if o.paid_at else None,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }
    if items is not None:
        out["items"] = [
            {
                "order_item_id": str(i.id),
                "product_id": str(i.product_id),
                "price_id": str(i.price_id) if i.price_id else None,
                "unit_amount_paise": i.unit_amount_paise,
                "taxable_paise": i.taxable_paise,
                "cgst_paise": i.cgst_paise,
                "sgst_paise": i.sgst_paise,
                "igst_paise": i.igst_paise,
                "total_paise": i.total_paise,
                "gst_rate": str(i.gst_rate),
                "sac_code": i.sac_code,
            }
            for i in items
        ]
    return out


async def create_order(
    session: AsyncSession,
    principal: Principal,
    gw: PaymentGateway,
    q: Quote,
    *,
    idempotency_key: str,
    billing_name: str | None,
    billing_gstin: str | None,
    quote_total_paise: int,
) -> dict[str, Any]:
    """COM-04: order + item + coupon reservation in one transaction, then the provider
    order. A provider outage aborts the whole transaction (no order is created)."""
    if q.blocking:
        b = q.blocking[0]
        raise ProblemError("already_owned", source_type=b["source_type"], ends_at=b["ends_at"])
    if q.coupon is not None and not q.coupon.ok:
        raise ProblemError(policy_coupon_error(q.coupon.status), reason=q.coupon.status)
    if q.total_paise != quote_total_paise:
        raise ProblemError(
            "validation_failed",
            errors=[
                {"field": "quote_total_paise", "code": "quote_mismatch", "message": "Price changed; re-quote"}
            ],
            server_total_paise=q.total_paise,
        )
    now = utcnow()
    order = Order(
        id=uuid7(),
        order_number=await next_order_number(session, now),
        user_id=principal.user_id,
        status="created",
        subtotal_paise=q.subtotal_pre_tax,
        discount_paise=q.discount_pre_tax,
        tax_paise=q.line.tax_paise,
        total_paise=q.total_paise,
        refunded_paise=0,
        gateway=gw.name if q.total_paise > 0 else None,
        idempotency_key=idempotency_key,
        billing_name=billing_name,
        billing_gstin=billing_gstin,
        place_of_supply=q.place_of_supply,
        expires_at=now + policy.ORDER_TTL,
    )
    session.add(order)
    await session.flush()
    item = OrderItem(
        id=uuid7(),
        order_id=order.id,
        user_id=principal.user_id,
        product_id=q.product.id,
        plan_id=q.plan.id,
        price_id=q.price.id,
        quantity=1,
        unit_amount_paise=q.list_paise,
        discount_paise=q.discount_pre_tax,
        taxable_paise=q.line.taxable_paise,
        cgst_paise=q.line.cgst_paise,
        sgst_paise=q.line.sgst_paise,
        igst_paise=q.line.igst_paise,
        total_paise=q.total_paise,
        gst_rate=q.product.gst_rate,
        sac_code=q.product.sac_code,
    )
    session.add(item)
    if q.coupon is not None and q.coupon.coupon is not None:
        session.add(
            CouponRedemption(
                id=uuid7(),
                coupon_id=q.coupon.coupon.id,
                user_id=principal.user_id,
                order_id=order.id,
                discount_paise=q.discount_paise,
                status="reserved",
                reserved_until=order.expires_at,
            )
        )
    await session.flush()
    await audit(
        session, principal, "order.created", "order", order.id, after={"total_paise": order.total_paise}
    )
    checkout: dict[str, Any] | None = None
    entitlements: list[dict[str, Any]] = []
    if order.total_paise == 0:
        # 100 % free-access coupon: no gateway; fulfilled now as a coupon grant.
        async with as_system(session, "commerce.fulfil", principal):
            await fulfil_order(session, order.id, ent.Actor.user(principal), payment=None)
            entitlements = await order_entitlements(session, order.id)
        await session.refresh(order)
    else:
        try:
            gorder = await gw.create_order(
                order.total_paise, order.order_number, {"order_number": order.order_number}
            )
        except GatewayUnavailable as e:
            raise ProblemError(
                "service_unavailable", detail="Payment provider unavailable; try again."
            ) from e
        order.gateway_order_id = gorder.id
        order.status = "pending_payment"
        await session.flush()
        checkout = checkout_payload(gw, order)
    return {**order_json(order), "checkout": checkout, "entitlements": entitlements}


def checkout_payload(gw: PaymentGateway, order: Order) -> dict[str, Any] | None:
    """Razorpay Checkout options for a payable order (COM-04, and COM-05 resume — FE-26)."""
    if order.gateway_order_id is None or order.total_paise <= 0:
        return None
    checkout: dict[str, Any] = {
        "key_id": gw.key_id,
        "gateway_order_id": order.gateway_order_id,
        "amount": order.total_paise,
        "currency": "INR",
        "name": "Tech Drona",
        "notes": {"order_number": order.order_number},
    }
    if isinstance(gw, FakePaymentProvider):
        # Dev/test only (the fake gateway is refused in production): lets the web test-mode
        # dialog "simulate a successful payment" through the real COM-06 verify path.
        checkout["test_payment"] = gw.test_checkout_payment(order.gateway_order_id, order.total_paise)
    return checkout


def is_resumable(order: Order, now: datetime | None = None) -> bool:
    return (
        order.status == "pending_payment"
        and order.gateway_order_id is not None
        and order.expires_at > (now or utcnow())
    )


async def find_resumable_order(
    session: AsyncSession,
    principal: Principal,
    *,
    price_id: uuid.UUID,
    coupon_code: str | None,
    state_code: str | None,
    quote_total_paise: int,
) -> Order | None:
    """FE-27: a reload of the checkout page re-posts COM-04 with a fresh Idempotency-Key. An
    unexpired pending order of the same user for the same price, coupon, place of supply and
    total is returned instead of creating (and reserving a coupon for) a duplicate."""
    from app.modules.commerce.pricing import is_intra_state

    _, pos = is_intra_state(state_code)
    now = utcnow()
    rows = (
        (
            await session.execute(
                select(Order)
                .join(OrderItem, OrderItem.order_id == Order.id)
                .where(
                    Order.user_id == principal.user_id,
                    Order.status == "pending_payment",
                    Order.expires_at > now,
                    Order.gateway_order_id.is_not(None),
                    Order.total_paise == quote_total_paise,
                    Order.place_of_supply == pos,
                    OrderItem.price_id == price_id,
                )
                .order_by(Order.created_at.desc())
                .with_for_update(of=Order)
            )
        )
        .scalars()
        .all()
    )
    for o in rows:
        code = (
            await session.execute(
                select(Coupon.code)
                .join(CouponRedemption, CouponRedemption.coupon_id == Coupon.id)
                .where(CouponRedemption.order_id == o.id, CouponRedemption.status == "reserved")
            )
        ).scalar_one_or_none()
        if (code or "").lower() == (coupon_code or "").lower():
            return o
    return None


def policy_coupon_error(status: str) -> str:
    from app.modules.commerce.pricing import COUPON_ERROR

    return COUPON_ERROR.get(status, "coupon_invalid")


async def order_entitlements(session: AsyncSession, order_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(Entitlement)
                .join(OrderItem, OrderItem.id == Entitlement.order_item_id, isouter=True)
                .join(CouponRedemption, CouponRedemption.id == Entitlement.coupon_redemption_id, isouter=True)
                .where((OrderItem.order_id == order_id) | (CouponRedemption.order_id == order_id))
            )
        )
        .scalars()
        .all()
    )
    return [ent.entitlement_json(e) for e in rows]


async def fulfil_order(
    session: AsyncSession, order_id: uuid.UUID, actor: ent.Actor, *, payment: Payment | None
) -> bool:
    """Idempotent: the first caller moves the order to ``paid`` and grants entitlements;
    later callers are no-ops (row lock + status guard + ``UNIQUE (order_item_id)``)."""
    order = (await session.execute(select(Order).where(Order.id == order_id).with_for_update())).scalar_one()
    if order.status not in PAYABLE_FROM:
        return False
    late = order.status in ("expired", "cancelled", "failed")
    now = utcnow()
    order.status = "paid"
    order.paid_at = now
    await session.flush()
    redemption = (
        await session.execute(
            select(CouponRedemption).where(CouponRedemption.order_id == order.id).with_for_update()
        )
    ).scalar_one_or_none()
    if redemption is not None and redemption.status != "consumed":
        redemption.status = "consumed"
        bumped = (
            await session.execute(
                update(Coupon)
                .where(
                    Coupon.id == redemption.coupon_id,
                    (Coupon.max_redemptions.is_(None)) | (Coupon.redeemed_count < Coupon.max_redemptions),
                )
                .values(redeemed_count=Coupon.redeemed_count + 1)
                .returning(Coupon.id)
            )
        ).scalar_one_or_none()
        if bumped is None:  # money was taken: honour the order, flag the overrun
            await audit(session, actor.audit_actor(), "coupon.cap_overrun", "coupon", redemption.coupon_id)
    items = (await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    for it in items:
        product = (await session.execute(select(Product).where(Product.id == it.product_id))).scalar_one()
        plan = (await session.execute(select(Plan).where(Plan.id == it.plan_id))).scalar_one()
        assert order.user_id is not None
        ends = now + timedelta(days=plan.access_duration_days) if plan.access_duration_days else None
        if order.total_paise == 0 and redemption is not None:
            await ent.grant(
                session,
                actor,
                user_id=order.user_id,
                source_type="coupon_grant",
                product_id=it.product_id,
                coupon_redemption_id=redemption.id,
                starts_at=now,
                ends_at=ends,
                source_ref=order.id,
            )
        else:
            await ent.grant(
                session,
                actor,
                user_id=order.user_id,
                source_type="placement_package"
                if product.product_kind == "placement_package"
                else "purchase",
                product_id=it.product_id,
                order_item_id=it.id,
                starts_at=now,
                ends_at=ends,
                source_ref=order.id,
            )
    if order.total_paise > 0:
        await issue_tax_invoice(session, order)
    await audit(
        session,
        actor.audit_actor(),
        "order.paid",
        "order",
        order.id,
        subject_user_id=order.user_id,
        after={"total_paise": order.total_paise, "payment_id": payment.id if payment else None, "late": late},
    )
    await emit_event(
        session,
        "order.paid",
        {"order_id": str(order.id), "user_id": str(order.user_id), "late_payment": late},
        aggregate_type="order",
        aggregate_id=order.id,
    )
    if late:
        log.warning("order_paid_after_expiry", order_id=str(order.id))
    return True


async def release_coupon(session: AsyncSession, order_id: uuid.UUID) -> None:
    await session.execute(
        update(CouponRedemption)
        .where(CouponRedemption.order_id == order_id, CouponRedemption.status == "reserved")
        .values(status="released")
    )


async def cancel_order(session: AsyncSession, principal: Principal, order: Order) -> dict[str, Any]:
    if order.status not in ("created", "pending_payment"):
        raise ProblemError(
            "invalid_state_transition", current_state=order.status, allowed=["created", "pending_payment"]
        )
    order.status = "cancelled"
    await release_coupon(session, order.id)
    await session.flush()
    await audit(session, principal, "order.cancelled", "order", order.id)
    return order_json(order)


# --------------------------------------------------------------------------- payments


async def upsert_payment(
    session: AsyncSession,
    gw_name: str,
    gp: GwPayment,
    *,
    order: Order | None = None,
    subscription: Subscription | None = None,
) -> Payment:
    """Insert or advance a payment row (forward-only, e.g. ``failed`` after ``captured`` is
    ignored). Card data beyond last4/network/issuer is never stored."""
    status = gp.status
    if status == "refunded" and 0 < gp.amount_refunded_paise < gp.amount_paise:
        status = "partially_refunded"
    if status not in PAY_RANK:
        status = "created"
    now = utcnow()
    await session.execute(
        pg_insert(Payment)
        .values(
            id=uuid7(),
            order_id=order.id if order else None,
            subscription_id=subscription.id if subscription else None,
            user_id=(order.user_id if order else subscription.user_id if subscription else None),
            organization_id=order.organization_id if order else None,
            gateway=gw_name,
            gateway_payment_id=gp.id,
            method=gp.method
            if gp.method in ("upi", "card", "netbanking", "wallet", "emandate", "emi")
            else None,
            status=status,
            amount_paise=gp.amount_paise,
            fee_paise=gp.fee_paise,
            tax_on_fee_paise=gp.tax_paise,
            card_last4=gp.card_last4,
            card_network=gp.card_network,
            card_issuer=gp.card_issuer,
            vpa_masked=gp.vpa_masked,
            bank_code=gp.bank_code,
            error_code=gp.error_code,
            error_description=gp.error_description,
            authorized_at=now if status in ("authorized", "captured") else None,
            captured_at=now if status == "captured" else None,
        )
        .on_conflict_do_nothing()
    )
    p = (
        await session.execute(
            select(Payment)
            .where(Payment.gateway == gw_name, Payment.gateway_payment_id == gp.id)
            .with_for_update()
        )
    ).scalar_one()
    if PAY_RANK[status] > PAY_RANK.get(p.status, 0):
        p.status = status
        if status in ("authorized", "captured") and p.authorized_at is None:
            p.authorized_at = now
        if status == "captured" and p.captured_at is None:
            p.captured_at = now
        if status == "failed":
            p.error_code, p.error_description = gp.error_code, gp.error_description
    if order is not None and p.order_id is None:
        p.order_id = order.id
    await session.flush()
    return p


async def apply_payment(
    session: AsyncSession, gw: PaymentGateway, gp: GwPayment, actor: ent.Actor
) -> tuple[Order | None, Payment | None, bool]:
    """Apply a fetched payment to its order. Returns ``(order, payment, fulfilled_now)``."""
    if gp.subscription_id:
        sub = (
            await session.execute(
                select(Subscription).where(
                    Subscription.gateway == gw.name,
                    Subscription.gateway_subscription_id == gp.subscription_id,
                )
            )
        ).scalar_one_or_none()
        if sub is None:
            return None, None, False
        pay = await record_subscription_charge(session, gw, sub, gp, actor)
        return None, pay, False
    if not gp.order_id:
        return None, None, False
    order = (
        await session.execute(
            select(Order)
            .where(Order.gateway == gw.name, Order.gateway_order_id == gp.order_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        return None, None, False
    pay = await upsert_payment(session, gw.name, gp, order=order)
    fulfilled = False
    if pay.status == "captured":
        if gp.amount_paise != order.total_paise or gp.currency != "INR":
            await audit(
                session,
                actor.audit_actor(),
                "payment.amount_mismatch",
                "order",
                order.id,
                after={"gateway_amount": gp.amount_paise, "order_total": order.total_paise},
            )
            return order, pay, False
        fulfilled = await fulfil_order(session, order.id, actor, payment=pay)
    elif pay.status == "authorized" and order.status == "created":
        order.status = "pending_payment"
    elif pay.status == "failed":
        await emit_event(
            session,
            "payment.failed",
            {"order_id": str(order.id)},
            aggregate_type="order",
            aggregate_id=order.id,
        )
    await session.flush()
    return order, pay, fulfilled


async def confirm_order(
    session: AsyncSession, principal: Principal, gw: PaymentGateway, order: Order, payment_id: str
) -> dict[str, Any]:
    """COM-06 after the signature check: server-side fetch, then the shared fulfilment."""
    if order.status in ("paid", "refunded", "partially_refunded"):
        return {**order_json(order), "entitlements": await order_entitlements(session, order.id)}
    try:
        gp = await gw.fetch_payment(payment_id)
    except GatewayUnavailable as e:
        raise ProblemError(
            "service_unavailable", detail="Could not confirm with the payment provider."
        ) from e
    if gp.order_id != order.gateway_order_id:
        raise ProblemError("payment_signature_invalid")
    async with as_system(session, "commerce.confirm", principal):
        o, _pay, _ = await apply_payment(session, gw, gp, ent.Actor.user(principal))
        assert o is not None
        ents = await order_entitlements(session, o.id)
        invoice = (
            await session.execute(
                select(Invoice).where(Invoice.order_id == o.id, Invoice.invoice_type == "tax_invoice")
            )
        ).scalar_one_or_none()
    out = {**order_json(o), "entitlements": ents}
    if o.status == "paid":
        out["invoice"] = {"invoice_number": invoice.invoice_number, "pdf_ready": False} if invoice else None
        return out
    if gp.status == "authorized":
        out["message"] = "Payment received by bank, confirming…"
        return out
    if o.status == "expired" or o.expires_at <= utcnow():
        raise ProblemError("order_expired")
    return out


async def expire_orders(
    session: AsyncSession, gw: PaymentGateway, now: datetime | None = None
) -> dict[str, int]:
    """Job (system context): pending orders past ``expires_at`` are re-checked with the
    provider first (a captured payment is fulfilled), else expired + coupon released."""
    now = now or utcnow()
    actor = ent.Actor.system("commerce.order_expiry")
    rows = (
        (
            await session.execute(
                select(Order)
                .where(
                    Order.status.in_(("created", "pending_payment")),
                    Order.expires_at <= now,
                    # legacy offline-PO orders (archived B2B invoices): expires_at was a due date
                    Order.gateway.is_distinct_from("offline_po"),
                )
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    out = {"expired": 0, "recovered": 0}
    for o in rows:
        recovered = False
        if o.gateway_order_id:
            try:
                for gp in await gw.fetch_order_payments(o.gateway_order_id):
                    _, _, done = await apply_payment(session, gw, gp, actor)
                    recovered |= done
            except GatewayUnavailable:
                continue  # retry next run, no state change
        if recovered:
            out["recovered"] += 1
            continue
        o.status = "expired"
        await release_coupon(session, o.id)
        out["expired"] += 1
    await session.flush()
    return out


# --------------------------------------------------------------------------- invoices


def fiscal_year(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


async def allocate_number(session: AsyncSession, series: str, issue_date: date) -> str:
    """Gap-free per series and FY: the row lock is held until the transaction commits."""
    fy = fiscal_year(issue_date)
    n = (
        await session.execute(
            text(
                "INSERT INTO invoice_sequences (series, fiscal_year, next_value) VALUES (:s, :fy, 2) "
                "ON CONFLICT (series, fiscal_year) "
                "DO UPDATE SET next_value = invoice_sequences.next_value + 1 "
                "RETURNING next_value - 1"
            ),
            {"s": series, "fy": fy},
        )
    ).scalar_one()
    return f"{series}/{fy[2:4]}{fy[5:7]}/{int(n):06d}"


async def _buyer_name(session: AsyncSession, order: Order) -> str:
    if order.billing_name:
        return order.billing_name
    if order.user_id:
        from app.modules.identity.models import UserProfile

        name = (
            await session.execute(select(UserProfile.full_name).where(UserProfile.user_id == order.user_id))
        ).scalar_one_or_none()
        if name:
            return str(name)
    return "Customer"


async def issue_tax_invoice(session: AsyncSession, order: Order) -> Invoice:
    existing = (
        await session.execute(
            select(Invoice).where(
                Invoice.order_id == order.id,
                Invoice.invoice_type == "tax_invoice",
                Invoice.status == "issued",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    items = (await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    today = ist_date(utcnow())
    s = policy.commerce_settings()
    inv = Invoice(
        id=uuid7(),
        invoice_number=await allocate_number(session, "TD", today),
        invoice_type="tax_invoice",
        order_id=order.id,
        user_id=order.user_id,
        organization_id=order.organization_id,
        seller_gstin=s.SELLER_GSTIN,
        buyer_name=await _buyer_name(session, order),
        buyer_gstin=order.billing_gstin,
        place_of_supply=order.place_of_supply or s.SELLER_STATE_CODE,
        issue_date=today,
        taxable_paise=sum(i.taxable_paise for i in items),
        cgst_paise=sum(i.cgst_paise for i in items),
        sgst_paise=sum(i.sgst_paise for i in items),
        igst_paise=sum(i.igst_paise for i in items),
        total_paise=sum(i.total_paise for i in items),
    )
    session.add(inv)
    await session.flush()
    await emit_event(
        session,
        "invoice.issued",
        {"invoice_id": str(inv.id), "order_id": str(order.id)},
        aggregate_type="invoice",
        aggregate_id=inv.id,
    )
    return inv


async def issue_credit_note(
    session: AsyncSession, order: Order, amount_paise: int, *, refund: Refund | None = None
) -> Invoice:
    original = (
        await session.execute(
            select(Invoice).where(Invoice.order_id == order.id, Invoice.invoice_type == "tax_invoice")
        )
    ).scalar_one_or_none()
    if original is None:
        raise ProblemError("invalid_state_transition", current_state="no_invoice", allowed=[])
    if refund is not None:
        dup = (
            await session.execute(select(Invoice).where(Invoice.refund_id == refund.id))
        ).scalar_one_or_none()
        if dup is not None:
            return dup
    if amount_paise == original.total_paise:
        taxable, c, sg, ig = (
            original.taxable_paise,
            original.cgst_paise,
            original.sgst_paise,
            original.igst_paise,
        )
    else:
        items = (
            (await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
        )
        rate = Decimal(items[0].gst_rate) if items else policy.DEFAULT_GST_RATE
        line = split_inclusive(amount_paise, rate, intra_state=original.igst_paise == 0)
        taxable, c, sg, ig = line.taxable_paise, line.cgst_paise, line.sgst_paise, line.igst_paise
    today = ist_date(utcnow())
    cn = Invoice(
        id=uuid7(),
        invoice_number=await allocate_number(session, "TDCN", today),
        invoice_type="credit_note",
        order_id=order.id,
        refund_id=refund.id if refund else None,
        original_invoice_id=original.id,
        user_id=order.user_id,
        organization_id=order.organization_id,
        seller_gstin=original.seller_gstin,
        buyer_name=original.buyer_name,
        buyer_gstin=original.buyer_gstin,
        place_of_supply=original.place_of_supply,
        issue_date=today,
        taxable_paise=taxable,
        cgst_paise=c,
        sgst_paise=sg,
        igst_paise=ig,
        total_paise=taxable + c + sg + ig,
    )
    session.add(cn)
    await session.flush()
    return cn


def invoice_json(i: Invoice) -> dict[str, Any]:
    return {
        "invoice_id": str(i.id),
        "invoice_number": i.invoice_number,
        "invoice_type": i.invoice_type,
        "order_id": str(i.order_id),
        "original_invoice_id": str(i.original_invoice_id) if i.original_invoice_id else None,
        "issue_date": i.issue_date.isoformat(),
        "seller_gstin": i.seller_gstin,
        "buyer_name": i.buyer_name,
        "buyer_gstin": i.buyer_gstin,
        "place_of_supply": i.place_of_supply,
        "taxable_paise": i.taxable_paise,
        "cgst_paise": i.cgst_paise,
        "sgst_paise": i.sgst_paise,
        "igst_paise": i.igst_paise,
        "total_paise": i.total_paise,
        "status": i.status,
        "pdf_ready": i.pdf_s3_key is not None,
        "description": i.description,
        "due_on": i.due_on.isoformat() if i.due_on else None,
    }


# --------------------------------------------------------------------------- subscriptions


def sub_json(s: Subscription) -> dict[str, Any]:
    return {
        "subscription_id": str(s.id),
        "plan_id": str(s.plan_id),
        "price_id": str(s.price_id),
        "status": s.status,
        "gateway_subscription_id": s.gateway_subscription_id,
        "mandate_max_amount_paise": s.mandate_max_amount_paise,
        "current_period_start": s.current_period_start.isoformat() if s.current_period_start else None,
        "current_period_end": s.current_period_end.isoformat() if s.current_period_end else None,
        "next_charge_at": s.next_charge_at.isoformat() if s.next_charge_at else None,
        "cancel_at_period_end": s.cancel_at_period_end,
        "grace_until": s.grace_until.isoformat() if s.grace_until else None,
        "paid_count": s.paid_count,
        "scheduled_plan_id": str(s.scheduled_plan_id) if s.scheduled_plan_id else None,
        "scheduled_price_id": str(s.scheduled_price_id) if s.scheduled_price_id else None,
        "scheduled_change_at": s.scheduled_change_at.isoformat() if s.scheduled_change_at else None,
        "pending_addon_paise": s.pending_addon_paise,
    }


async def create_subscription(
    session: AsyncSession,
    principal: Principal,
    gw: PaymentGateway,
    price: Price,
    plan: Plan,
    product: Product,
    *,
    billing_name: str | None = None,
    billing_state_code: str | None = None,
    billing_gstin: str | None = None,
) -> dict[str, Any]:
    """COM-09: recurring price ≤ ₹15,000 per debit (RBI e-mandate without AFA). The buyer's
    billing state / GSTIN are kept on the subscription so every debit invoice gets the
    right CGST+SGST vs IGST split and place of supply (COM-10)."""
    if not price.is_recurring or plan.billing_type != "recurring":
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "price_id", "code": "not_recurring", "message": "Not a recurring price"}],
        )
    if price.amount_paise > policy.MANDATE_MAX_PAISE:
        raise ProblemError("recurring_amount_exceeds_mandate_limit", max_paise=policy.MANDATE_MAX_PAISE)
    gplan = (plan.gateway_plan_ids or {}).get(gw.name)
    if not gplan:
        raise ProblemError("service_unavailable", detail="This plan is not yet available for subscription.")
    existing = (
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == principal.user_id,
                Subscription.plan_id == plan.id,
                Subscription.status.in_(("authenticated", "active", "pending", "halted")),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ProblemError(
            "already_owned",
            source_type="subscription",
            ends_at=existing.current_period_end.isoformat() if existing.current_period_end else None,
        )
    total_count = 120 if plan.interval_unit == "month" else 10
    try:
        gs = await gw.create_subscription(str(gplan), total_count, {"user_ref": str(principal.user_id)})
    except GatewayUnavailable as e:
        raise ProblemError("service_unavailable") from e
    sub = Subscription(
        id=uuid7(),
        user_id=principal.user_id,
        plan_id=plan.id,
        price_id=price.id,
        gateway=gw.name,
        gateway_subscription_id=gs.id,
        status="created",
        mandate_max_amount_paise=price.amount_paise,
        total_count=total_count,
        billing_name=billing_name,
        billing_state_code=billing_state_code,
        billing_gstin=billing_gstin,
    )
    session.add(sub)
    await session.flush()
    await audit(
        session,
        principal,
        "subscription.created",
        "subscription",
        sub.id,
        after={"plan_id": plan.id, "amount_paise": price.amount_paise},
    )
    return {
        **sub_json(sub),
        "checkout": {"key_id": gw.key_id, "subscription_id": gs.id, "name": product.name},
    }


async def apply_subscription_state(
    session: AsyncSession, sub: Subscription, gs: GwSubscription, actor: ent.Actor
) -> None:
    """Apply a fetched subscription. Periods only move forward; terminal states stick."""
    end = _ts(gs.current_end)
    renewed = end is not None and sub.current_period_end is not None and end > sub.current_period_end
    if end is not None and (sub.current_period_end is None or end > sub.current_period_end):
        sub.current_period_start = _ts(gs.current_start)
        sub.current_period_end = end
        sub.next_charge_at = _ts(gs.charge_at)
        sub.paid_count = max(sub.paid_count, gs.paid_count)
    old = sub.status
    if old not in TERMINAL_SUB:
        sub.status = gs.status
    if sub.status in ("cancelled",) and sub.cancelled_at is None:
        sub.cancelled_at = utcnow()
    await session.flush()
    e = (
        await session.execute(
            select(Entitlement).where(Entitlement.subscription_id == sub.id).with_for_update()
        )
    ).scalar_one_or_none()
    if (
        renewed
        and sub.scheduled_price_id is not None
        and sub.scheduled_plan_id is not None
        and sub.scheduled_change_at is not None
        and sub.current_period_start is not None
        and sub.scheduled_change_at <= sub.current_period_start + timedelta(minutes=5)
    ):
        await apply_scheduled_plan_change(session, sub, e, actor)
    plan = (await session.execute(select(Plan).where(Plan.id == sub.plan_id))).scalar_one()
    if sub.status == "active" and sub.current_period_end is not None:
        sub.grace_until = None
        if e is None:
            await ent.grant(
                session,
                actor,
                user_id=sub.user_id,
                source_type="subscription",
                product_id=plan.product_id,
                subscription_id=sub.id,
                starts_at=sub.current_period_start or utcnow(),
                ends_at=sub.current_period_end,
                source_ref=sub.id,
            )
        elif e.status == "grace" or (e.ends_at is not None and sub.current_period_end > e.ends_at):
            await ent.extend_to(
                session, e, sub.current_period_end, actor, reason="subscription_charged", source_ref=sub.id
            )
    elif sub.status in ("pending", "halted") and e is not None and e.status == "active":
        base = sub.current_period_end or e.ends_at or utcnow()
        grace_end = base + timedelta(days=policy.SUBSCRIPTION_GRACE_DAYS)
        sub.grace_until = grace_end
        await ent.enter_grace(session, e, grace_end, actor, reason=f"subscription_{sub.status}")
    if old != sub.status:
        await audit(
            session,
            actor.audit_actor(),
            "subscription.status_changed",
            "subscription",
            sub.id,
            subject_user_id=sub.user_id,
            before={"status": old},
            after={"status": sub.status},
        )
        await emit_event(
            session,
            f"subscription.{sub.status}",
            {"subscription_id": str(sub.id)},
            aggregate_type="subscription",
            aggregate_id=sub.id,
        )
    await session.flush()


async def record_subscription_charge(
    session: AsyncSession, gw: PaymentGateway, sub: Subscription, gp: GwPayment, actor: ent.Actor
) -> Payment:
    """Each captured mandate debit becomes a paid order + payment + tax invoice."""
    existing = (
        await session.execute(
            select(Payment).where(Payment.gateway == gw.name, Payment.gateway_payment_id == gp.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return await upsert_payment(session, gw.name, gp, subscription=sub)
    if gp.status != "captured":
        return await upsert_payment(session, gw.name, gp, subscription=sub)
    price = (await session.execute(select(Price).where(Price.id == sub.price_id))).scalar_one()
    plan = (await session.execute(select(Plan).where(Plan.id == sub.plan_id))).scalar_one()
    product = (await session.execute(select(Product).where(Product.id == plan.product_id))).scalar_one()
    from app.modules.commerce.pricing import is_intra_state

    intra, pos = is_intra_state(sub.billing_state_code)
    line = split_inclusive(gp.amount_paise, Decimal(product.gst_rate), intra_state=intra)
    now = utcnow()
    order = Order(
        id=uuid7(),
        order_number=await next_order_number(session, now),
        user_id=sub.user_id,
        status="paid",
        subtotal_paise=line.taxable_paise,
        discount_paise=0,
        tax_paise=line.tax_paise,
        total_paise=gp.amount_paise,
        refunded_paise=0,
        gateway=gw.name,
        gateway_order_id=gp.order_id,
        subscription_id=sub.id,
        idempotency_key=f"sub:{gp.id}",
        billing_name=sub.billing_name,
        billing_gstin=sub.billing_gstin,
        place_of_supply=pos,
        expires_at=now,
        paid_at=now,
    )
    session.add(order)
    await session.flush()
    session.add(
        OrderItem(
            id=uuid7(),
            order_id=order.id,
            user_id=sub.user_id,
            product_id=product.id,
            plan_id=plan.id,
            price_id=price.id,
            unit_amount_paise=gp.amount_paise,
            taxable_paise=line.taxable_paise,
            cgst_paise=line.cgst_paise,
            sgst_paise=line.sgst_paise,
            igst_paise=line.igst_paise,
            total_paise=gp.amount_paise,
            gst_rate=product.gst_rate,
            sac_code=product.sac_code,
        )
    )
    await session.flush()
    pay = await upsert_payment(session, gw.name, gp, order=order, subscription=sub)
    # A prorated upgrade amount (COM-14) is billed as an add-on with this debit.
    sub.pending_addon_paise = 0
    await issue_tax_invoice(session, order)
    await emit_event(
        session,
        "order.paid",
        {"order_id": str(order.id), "subscription_id": str(sub.id)},
        aggregate_type="order",
        aggregate_id=order.id,
    )
    return pay


async def cancel_subscription(
    session: AsyncSession,
    actor_principal: Principal,
    gw: PaymentGateway,
    sub: Subscription,
    *,
    reason: str | None,
    immediate: bool = False,
    ticket_ref: str | None = None,
) -> dict[str, Any]:
    """COM-12/34: cancel at period end (one click). Purchased entitlements and the access
    already paid for are unaffected (BR-ENT-07)."""
    if sub.status in TERMINAL_SUB:
        raise ProblemError("invalid_state_transition", current_state=sub.status, allowed=list(ACTIVE_SUB))
    try:
        gs = await gw.cancel_subscription(sub.gateway_subscription_id, at_cycle_end=not immediate)
    except GatewayUnavailable as e:
        raise ProblemError("service_unavailable") from e
    sub.cancel_at_period_end = not immediate
    sub.cancel_reason = reason
    if immediate or gs.status == "cancelled":
        sub.status = "cancelled"
        sub.cancelled_at = utcnow()
    await session.flush()
    await audit(
        session,
        actor_principal,
        "subscription.cancel",
        "subscription",
        sub.id,
        subject_user_id=sub.user_id,
        reason=ticket_ref or reason,
        after={"cancel_at_period_end": sub.cancel_at_period_end, "status": sub.status},
    )
    await emit_event(
        session,
        "subscription.cancel_requested",
        {
            "subscription_id": str(sub.id),
            "user_id": str(sub.user_id),
            "cancel_at_period_end": sub.cancel_at_period_end,
        },
        aggregate_type="subscription",
        aggregate_id=sub.id,
    )
    access_until = sub.current_period_end.isoformat() if sub.current_period_end else None
    sent = await _cancel_confirmation(session, actor_principal, sub, access_until)
    return {
        "subscription_id": str(sub.id),
        "status": sub.status,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "access_until": access_until,
        "confirmation_sent": sent,
    }


async def _cancel_confirmation(
    session: AsyncSession, principal: Principal, sub: Subscription, access_until: str | None
) -> bool:
    """FR-COM-005 immediate cancel confirmation (COM-17): an in-app notification written in
    this transaction. ``confirmation_sent`` reports whether it was actually created (it was
    hard-coded ``True`` before). Email delivery of the same confirmation is the notifications
    module's consumer of ``subscription.cancel_requested`` (requested in the fixes file)."""
    from app.core.db import system_context, tenant_context
    from app.modules.notifications.service import notify

    nid = None
    try:
        await system_context(session, "commerce.cancel_confirmation")
        async with session.begin_nested():
            nid = await notify(
                session,
                sub.user_id,
                "subscription.cancelled",
                category="transactional",
                data={
                    "subscription_id": str(sub.id),
                    "cancel_at_period_end": sub.cancel_at_period_end,
                    "access_until": access_until,
                },
                channels=("in_app",),
            )
    except Exception as e:  # never fail the cancellation itself
        log.warning("subscription_cancel_confirmation_failed", error=type(e).__name__)
    finally:
        await tenant_context(session, principal)
    return nid is not None


# --------------------------------------------------------------------------- refunds


async def captured_payment(session: AsyncSession, order_id: uuid.UUID) -> Payment | None:
    return (
        await session.execute(
            select(Payment)
            .where(Payment.order_id == order_id, Payment.status.in_(("captured", "partially_refunded")))
            .order_by(Payment.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()


async def refund_eligibility(
    session: AsyncSession, order: Order, now: datetime | None = None
) -> dict[str, Any]:
    """FR-COM-008: 7 days, < 20 % consumed, no certificate (discounted purchases included);
    renewals not refundable; mock packs only if no mock started; placement packages minus
    consumed mentor sessions at their listed unit price."""
    if order.status not in ("paid", "partially_refunded") or order.paid_at is None:
        raise ProblemError("invalid_state_transition", current_state=order.status, allowed=["paid"])
    now = now or utcnow()
    usage = ent.usage_provider()
    reasons: list[str] = []
    days = (now - order.paid_at).total_seconds() / 86400
    if days > policy.REFUND_WINDOW_DAYS:
        reasons.append("window_passed")
    items = (await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars().all()
    pct = Decimal("0")
    cert = False
    deduction = 0
    assert order.user_id is not None or order.organization_id is not None
    uid = order.user_id
    for it in items:
        product = (await session.execute(select(Product).where(Product.id == it.product_id))).scalar_one()
        if uid is not None:
            pct = max(pct, await usage.consumption_pct(session, uid, product.id))
            cert = cert or await usage.certificate_issued(session, uid, product.id)
            if (
                product.product_kind == "mock_pack"
                and await usage.mocks_started(session, uid, product.id) > 0
            ):
                reasons.append("mock_started")
        if product.product_kind == "placement_package":
            from app.modules.commerce.models import ProductItem

            pi = (
                await session.execute(
                    select(ProductItem).where(
                        ProductItem.product_id == product.id, ProductItem.feature_key == "mentor_sessions"
                    )
                )
            ).scalar_one_or_none()
            e = (
                await session.execute(select(Entitlement).where(Entitlement.order_item_id == it.id))
            ).scalar_one_or_none()
            if pi is not None and pi.quantity and e is not None and e.mentor_sessions_remaining is not None:
                used = pi.quantity - e.mentor_sessions_remaining
                deduction += max(used, 0) * int(pi.unit_price_paise or 0)
    if pct >= policy.REFUND_MAX_CONSUMPTION_PCT:
        reasons.append("consumption_exceeded")
    if cert:
        reasons.append("certificate_issued")
    if order.subscription_id is not None:
        first = (
            await session.execute(
                select(func.min(Order.created_at)).where(Order.subscription_id == order.subscription_id)
            )
        ).scalar_one()
        if first is not None and order.created_at > first:
            reasons.append("subscription_renewal")
    already = (
        await session.execute(
            select(func.coalesce(func.sum(Refund.amount_paise), 0)).where(
                Refund.order_id == order.id, Refund.status.in_(("approved", "processing", "processed"))
            )
        )
    ).scalar_one()
    refundable = max(order.total_paise - int(already) - deduction, 0)
    return {
        "eligible": not reasons and refundable > 0,
        "reasons": reasons,
        "days_since_purchase": round(days, 2),
        "consumption_pct": float(pct),
        "certificate_issued": cert,
        "refundable_paise": refundable,
        "usage_source": usage.name,
    }


def refund_json(r: Refund) -> dict[str, Any]:
    return {
        "refund_id": str(r.id),
        "order_id": str(r.order_id),
        "amount_paise": r.amount_paise,
        "reason_code": r.reason_code,
        "status": r.status,
        "consumption_pct": float(r.consumption_pct) if r.consumption_pct is not None else None,
        "approval_request_id": str(r.approval_request_id) if r.approval_request_id else None,
        "gateway_refund_id": r.gateway_refund_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "processed_at": r.processed_at.isoformat() if r.processed_at else None,
    }


async def committed_refunds(session: AsyncSession, order_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.coalesce(func.sum(Refund.amount_paise), 0)).where(
                    Refund.order_id == order_id, Refund.status.in_(COMMITTED_REFUND)
                )
            )
        ).scalar_one()
    )


def _amount_error(code: str, message: str, **ext: Any) -> ProblemError:
    return ProblemError(
        "validation_failed", errors=[{"field": "amount_paise", "code": code, "message": message}], **ext
    )


async def check_refund_amount(
    session: AsyncSession, order: Order, amount_paise: int, *, rule_limit_paise: int | None = None
) -> None:
    """COM-11 / ADM-24: a refund can never take the cumulative refunded amount above what
    was paid (``order.total - refunds approved/processing/processed``). Rule-based refunds
    (not goodwill, not finance-initiated) are further capped by the eligibility rule's
    ``refundable_paise`` (e.g. a placement package minus consumed mentor sessions). The
    order row must be locked by the caller; ``ck_order_refunded`` is the database backstop."""
    remaining = order.total_paise - max(order.refunded_paise, await committed_refunds(session, order.id))
    if amount_paise <= 0:
        raise _amount_error("out_of_range", "Invalid refund amount")
    if amount_paise > remaining:
        raise _amount_error(
            "exceeds_refundable",
            "More than the amount still refundable on this order",
            refundable_paise=max(remaining, 0),
        )
    if rule_limit_paise is not None and amount_paise > rule_limit_paise:
        raise _amount_error(
            "exceeds_refundable",
            "More than the refund rule allows",
            refundable_paise=rule_limit_paise,
        )


async def create_refund_request(
    session: AsyncSession,
    principal: Principal,
    order: Order,
    *,
    reason_code: str,
    note: str | None,
    amount_paise: int | None,
    idempotency_key: str,
) -> tuple[Refund, dict[str, Any]]:
    open_ = (
        await session.execute(
            select(func.count())
            .select_from(Refund)
            .where(Refund.order_id == order.id, Refund.status.in_(OPEN_REFUND))
        )
    ).scalar_one()
    if open_:
        raise ProblemError("invalid_state_transition", current_state="refund_open", allowed=[])
    elig = await refund_eligibility(session, order)
    pay = await captured_payment(session, order.id)
    if pay is None:
        raise ProblemError("invalid_state_transition", current_state="no_captured_payment", allowed=[])
    remaining = order.total_paise - await committed_refunds(session, order.id)
    amount = amount_paise or elig["refundable_paise"] or remaining
    await check_refund_amount(session, order, amount)
    r = Refund(
        id=uuid7(),
        payment_id=pay.id,
        order_id=order.id,
        user_id=order.user_id,
        organization_id=order.organization_id,
        amount_paise=amount,
        reason_code=reason_code,
        reason_note=note,
        consumption_pct=Decimal(str(elig["consumption_pct"])),
        status="requested",
        requested_by=principal.user_id,
        idempotency_key=idempotency_key,
        submit_attempts=0,
    )
    session.add(r)
    await session.flush()
    await audit(
        session,
        principal,
        "refund.requested",
        "refund",
        r.id,
        subject_user_id=order.user_id,
        after={"amount_paise": amount, "eligible": elig["eligible"]},
    )
    await emit_event(
        session, "refund.requested", {"refund_id": str(r.id)}, aggregate_type="refund", aggregate_id=r.id
    )
    return r, elig


async def _order_entitlements_for_update(
    session: AsyncSession, order: Order, order_item_ids: list[uuid.UUID] | None
) -> list[Entitlement]:
    q = (
        select(Entitlement)
        .join(OrderItem, OrderItem.id == Entitlement.order_item_id, isouter=True)
        .join(CouponRedemption, CouponRedemption.id == Entitlement.coupon_redemption_id, isouter=True)
        .where((OrderItem.order_id == order.id) | (CouponRedemption.order_id == order.id))
    )
    if order_item_ids:
        q = q.where(OrderItem.id.in_(order_item_ids))
    ents = list((await session.execute(q.with_for_update(of=Entitlement))).scalars().all())
    if order.subscription_id is not None and not order_item_ids:
        sub_ent = (
            await session.execute(
                select(Entitlement)
                .where(Entitlement.subscription_id == order.subscription_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if sub_ent is not None:
            ents.append(sub_ent)
    return ents


async def _course_still_covered(
    session: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID, excluded: set[uuid.UUID]
) -> bool:
    from app.modules.commerce.models import ProductItem

    q = select(Entitlement).where(Entitlement.user_id == user_id, Entitlement.status.in_(("active", "grace")))
    if excluded:
        q = q.where(Entitlement.id.not_in(excluded))
    for e in (await session.execute(q)).scalars().all():
        if e.course_id == course_id or e.feature_key == "all_courses":
            return True
        if e.product_id is not None:
            hit = (
                await session.execute(
                    select(func.count())
                    .select_from(ProductItem)
                    .where(
                        ProductItem.product_id == e.product_id,
                        (ProductItem.course_id == course_id) | (ProductItem.feature_key == "all_courses"),
                    )
                )
            ).scalar_one()
            if hit:
                return True
    return False


async def _revoke_certificates(
    session: AsyncSession, approver: Principal, order: Order, ents: list[Entitlement], r: Refund
) -> int:
    """BR-ENT-10 (COM-12): certificates issued under a refunded entitlement are revoked —
    certificates of the product's courses and, for ``all_courses`` products, of any course
    certified while the entitlement was held — unless another live entitlement of the user
    still covers that course. Uses the learning module's ``revoke_certificate`` (audited,
    emits ``learning.certificate_revoked``)."""
    from app.modules.commerce.models import ProductItem
    from app.modules.learning.models import Certificate
    from app.modules.learning.service import revoke_certificate

    uid = order.user_id
    if uid is None or not ents:
        return 0
    excluded = {e.id for e in ents}
    certs: dict[uuid.UUID, Certificate] = {}
    for e in ents:
        if e.product_id is None:
            continue
        items = (
            (await session.execute(select(ProductItem).where(ProductItem.product_id == e.product_id)))
            .scalars()
            .all()
        )
        course_ids = {i.course_id for i in items if i.course_id}
        conds: list[ColumnElement[bool]] = []
        if course_ids:
            conds.append(Certificate.course_id.in_(course_ids))
        if any(i.feature_key == "all_courses" for i in items):
            conds.append(Certificate.issued_at >= e.starts_at)
        if not conds:
            continue
        q = select(Certificate).where(
            Certificate.user_id == uid, Certificate.revoked_at.is_(None), or_(*conds)
        )
        for c in (await session.execute(q.with_for_update())).scalars():
            certs[c.id] = c
    n = 0
    for c in certs.values():
        if await _course_still_covered(session, uid, c.course_id, excluded):
            continue
        await revoke_certificate(session, approver, c, f"refund:{r.id}")
        n += 1
    return n


async def execute_refund(
    session: AsyncSession,
    gw: PaymentGateway,
    r: Refund,
    approver: Principal,
    *,
    order_item_ids: list[uuid.UUID] | None = None,
) -> Refund:
    """Approve (system context). Refund state machine (COM-01/02/03; see
    ``docs/audit/fixes/commerce.md``):

    * ``requested`` -> ``approved``: the amount is reserved on the order (``refunded_paise``,
      never above what was paid), access is revoked now (BR-ENT-10) by refund *intent* — every
      refund revokes the order's entitlements and their certificates unless finance marks it a
      ``price_adjustment``/``duplicate_payment`` or names specific ``order_item_ids`` — and the
      provider refund is submitted.
    * provider outage: stays ``approved`` without ``gateway_refund_id``;
      ``commerce.refund_submit_retry`` re-submits it with backoff (idempotent on
      ``notes.refund_id``) and alerts after ``REFUND_SUBMIT_ALERT_AFTER`` attempts.
    * ``processing`` -> ``processed`` (provider-confirmed): order/payment status and the GST
      credit note (only for money that actually moved).
    * ``processing`` -> ``failed`` (provider-confirmed): the reservation is released, the
      entitlements this refund revoked are reinstated and finance is alerted
      (``commerce.refund_failed``)."""
    if r.status != "requested":
        raise ProblemError("invalid_state_transition", current_state=r.status, allowed=["requested"])
    actor = ent.Actor.user(approver)
    order = (
        await session.execute(select(Order).where(Order.id == r.order_id).with_for_update())
    ).scalar_one()
    await check_refund_amount(session, order, r.amount_paise)
    order.refunded_paise = await committed_refunds(session, order.id) + r.amount_paise
    r.status = "approved"
    r.approved_by = approver.user_id if approver.user_id != r.requested_by else None
    await session.flush()
    revoked: list[Entitlement] = []
    if order_item_ids or r.reason_code not in NON_REVOKING_REFUND_REASONS:
        for e in await _order_entitlements_for_update(session, order, order_item_ids):
            if await ent.revoke(session, e, actor, reason_code="refund", source_ref=r.id):
                revoked.append(e)
    certs = await _revoke_certificates(session, approver, order, revoked, r)
    await submit_refund(session, gw, r)
    await audit(
        session,
        approver,
        "refund.approved",
        "refund",
        r.id,
        subject_user_id=r.user_id,
        after={
            "amount_paise": r.amount_paise,
            "status": r.status,
            "entitlements_revoked": len(revoked),
            "certificates_revoked": certs,
        },
    )
    await emit_event(
        session,
        "refund.approved",
        {
            "refund_id": str(r.id),
            "order_id": str(order.id),
            "user_id": str(order.user_id) if order.user_id else None,
            "entitlement_ids": [str(e.id) for e in revoked],
            "certificates_revoked": certs,
        },
        aggregate_type="refund",
        aggregate_id=r.id,
    )
    return r


def _submit_backoff(attempts: int) -> timedelta:
    step: timedelta = policy.REFUND_SUBMIT_BACKOFF_BASE * (2 ** max(attempts - 1, 0))
    return min(step, policy.REFUND_SUBMIT_BACKOFF_MAX)


async def submit_refund(session: AsyncSession, gw: PaymentGateway, r: Refund) -> bool:
    """Submit an ``approved`` refund to the provider. Idempotent: after a failed attempt, a
    refund the provider already holds for this payment with ``notes.refund_id == r.id`` is
    adopted instead of re-created. Returns True when the provider has it (``processing``)."""
    if r.status != "approved" or r.gateway_refund_id is not None:
        return False
    pay = (await session.execute(select(Payment).where(Payment.id == r.payment_id))).scalar_one()
    now = utcnow()
    try:
        gr: GwRefund | None = None
        if r.submit_attempts > 0:  # an earlier attempt may have reached the provider
            for x in await gw.fetch_payment_refunds(pay.gateway_payment_id):
                if str(x.notes.get("refund_id")) == str(r.id):
                    gr = x
                    break
        if gr is None:
            gr = await gw.create_refund(pay.gateway_payment_id, r.amount_paise, {"refund_id": str(r.id)})
    except GatewayUnavailable as e:
        r.submit_attempts += 1
        r.next_submit_at = now + _submit_backoff(r.submit_attempts)
        r.last_error = f"provider_unavailable: {e}"[:500]
        await session.flush()
        log.warning("refund_submit_deferred", refund_id=str(r.id), attempts=r.submit_attempts)
        if r.submit_attempts == policy.REFUND_SUBMIT_ALERT_AFTER:
            await emit_event(
                session,
                "commerce.refund_submit_stuck",
                {"refund_id": str(r.id), "order_id": str(r.order_id), "attempts": r.submit_attempts},
                aggregate_type="refund",
                aggregate_id=r.id,
            )
            await audit(
                session,
                AuditActor.system("commerce.refund_submit_retry"),
                "refund.submit_stuck",
                "refund",
                r.id,
                subject_user_id=r.user_id,
                after={"attempts": r.submit_attempts},
            )
        return False
    r.gateway_refund_id = gr.id
    r.status = "processing"
    r.next_submit_at = None
    r.last_error = None
    await session.flush()
    if gr.status in ("processed", "failed"):  # adopted an already-settled provider refund
        await apply_refund_state(session, gr, ent.Actor.system("commerce.refund_submit"))
    return True


async def retry_refund_submissions(
    session: AsyncSession, gw: PaymentGateway, now: datetime | None = None, limit: int = 50
) -> dict[str, int]:
    """COM-02 job (system context, ``critical`` queue): re-submit approved refunds that never
    reached the provider (outage at approval time)."""
    now = now or utcnow()
    rows = (
        (
            await session.execute(
                select(Refund)
                .where(
                    Refund.status == "approved",
                    Refund.gateway_refund_id.is_(None),
                    or_(Refund.next_submit_at.is_(None), Refund.next_submit_at <= now),
                )
                .order_by(Refund.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    out = {"checked": 0, "submitted": 0, "deferred": 0}
    for r in rows:
        out["checked"] += 1
        if await submit_refund(session, gw, r):
            out["submitted"] += 1
        else:
            out["deferred"] += 1
    return out


async def apply_refund_state(session: AsyncSession, gr: GwRefund, actor: ent.Actor) -> Refund | None:
    """Apply a fetched refund (``refund.processed`` before ``refund.created`` is fine).
    Terminal states (``processed``/``failed``/``rejected``) are never changed again."""
    r = (
        await session.execute(select(Refund).where(Refund.gateway_refund_id == gr.id).with_for_update())
    ).scalar_one_or_none()
    if r is None and gr.notes.get("refund_id"):
        try:
            rid = uuid.UUID(str(gr.notes["refund_id"]))
        except ValueError:
            return None
        r = (
            await session.execute(select(Refund).where(Refund.id == rid).with_for_update())
        ).scalar_one_or_none()
        if r is not None and r.gateway_refund_id is None:
            r.gateway_refund_id = gr.id
    if r is None or r.status in ("processed", "rejected", "failed", "requested"):
        return r
    order = (
        await session.execute(select(Order).where(Order.id == r.order_id).with_for_update())
    ).scalar_one()
    if gr.status == "processed":
        r.status = "processed"
        r.processed_at = utcnow()
        refunded = (
            await session.execute(
                select(func.coalesce(func.sum(Refund.amount_paise), 0)).where(
                    Refund.order_id == order.id, (Refund.status == "processed") | (Refund.id == r.id)
                )
            )
        ).scalar_one()
        full = int(refunded) >= order.total_paise
        order.status = "refunded" if full else "partially_refunded"
        pay = (await session.execute(select(Payment).where(Payment.id == r.payment_id))).scalar_one()
        new_pay = "refunded" if full else "partially_refunded"
        if PAY_RANK[new_pay] > PAY_RANK.get(pay.status, 0):
            pay.status = new_pay
        if full:
            for e in await _order_entitlements_for_update(session, order, None):
                await ent.revoke(session, e, actor, reason_code="refund", source_ref=r.id)
        await issue_credit_note(session, order, r.amount_paise, refund=r)
        await emit_event(
            session, "refund.processed", {"refund_id": str(r.id)}, aggregate_type="refund", aggregate_id=r.id
        )
    elif gr.status == "failed":
        r.status = "failed"
        await session.flush()
        order.refunded_paise = await committed_refunds(session, order.id)
        restored = 0
        for e in await ent.revoked_by_source(session, r.id):
            if await ent.reinstate(session, e, actor, reason="refund_failed", source_ref=r.id):
                restored += 1
        await audit(
            session,
            actor.audit_actor(),
            "refund.failed",
            "refund",
            r.id,
            subject_user_id=r.user_id,
            after={"entitlements_reinstated": restored, "amount_paise": r.amount_paise},
        )
        await emit_event(
            session,
            "commerce.refund_failed",
            {
                "refund_id": str(r.id),
                "order_id": str(order.id),
                "amount_paise": r.amount_paise,
                "entitlements_reinstated": restored,
            },
            aggregate_type="refund",
            aggregate_id=r.id,
        )
    elif r.status == "approved":
        r.status = "processing"
    await session.flush()
    return r


# --------------------------------------------------------------------------- disputes (BR-ENT-11)


async def apply_dispute(
    session: AsyncSession, gw: PaymentGateway, payment_gateway_id: str, status: str, actor: ent.Actor
) -> None:
    """BR-ENT-11 for one-time purchases **and** subscription debits (COM-05): the
    subscription's entitlement is suspended / restored / revoked like an order's."""
    pay = (
        await session.execute(
            select(Payment).where(
                Payment.gateway == gw.name, Payment.gateway_payment_id == payment_gateway_id
            )
        )
    ).scalar_one_or_none()
    if pay is None or (pay.order_id is None and pay.subscription_id is None):
        return
    ents: list[Entitlement] = []
    if pay.order_id is not None:
        ents += list(
            (
                await session.execute(
                    select(Entitlement)
                    .join(OrderItem, OrderItem.id == Entitlement.order_item_id)
                    .where(OrderItem.order_id == pay.order_id)
                    .with_for_update(of=Entitlement)
                )
            )
            .scalars()
            .all()
        )
    sub_id = pay.subscription_id
    if sub_id is None and pay.order_id is not None:
        sub_id = (
            await session.execute(select(Order.subscription_id).where(Order.id == pay.order_id))
        ).scalar_one_or_none()
    if sub_id is not None:
        sub_ent = (
            await session.execute(
                select(Entitlement).where(Entitlement.subscription_id == sub_id).with_for_update()
            )
        ).scalar_one_or_none()
        if sub_ent is not None and sub_ent not in ents:
            ents.append(sub_ent)
    if status in ("open", "under_review"):
        for e in ents:
            await ent.suspend(session, e, actor, reason="payment_dispute")
    elif status == "won":
        for e in ents:
            await ent.restore(session, e, actor, reason="dispute_won")
    elif status == "lost":
        pay.status = "refunded"
        for e in ents:
            await ent.revoke(session, e, actor, reason_code="chargeback")
        if pay.order_id is not None:
            order = (
                await session.execute(select(Order).where(Order.id == pay.order_id).with_for_update())
            ).scalar_one()
            order.status = "refunded"
            order.refunded_paise = order.total_paise
            await emit_event(
                session,
                "commerce.chargeback_lost",
                {"order_id": str(order.id), "subscription_id": str(sub_id) if sub_id else None},
                aggregate_type="order",
                aggregate_id=order.id,
            )
    await audit(session, actor.audit_actor(), "payment.dispute", "payment", pay.id, after={"status": status})
    await session.flush()


async def apply_scheduled_plan_change(
    session: AsyncSession, sub: Subscription, e: Entitlement | None, actor: ent.Actor
) -> None:
    """COM-14 downgrade: switch plan/price at the renewal that crosses ``scheduled_change_at``."""
    if sub.scheduled_plan_id is None or sub.scheduled_price_id is None:
        return
    old_price = sub.price_id
    sub.plan_id, sub.price_id = sub.scheduled_plan_id, sub.scheduled_price_id
    sub.scheduled_plan_id = sub.scheduled_price_id = sub.scheduled_change_at = None
    await session.flush()
    new_plan = (await session.execute(select(Plan).where(Plan.id == sub.plan_id))).scalar_one()
    if e is not None:
        await ent.change_product(
            session, e, new_plan.product_id, actor, reason="subscription_downgrade", source_ref=sub.id
        )
    await audit(
        session,
        actor.audit_actor(),
        "subscription.plan_changed",
        "subscription",
        sub.id,
        subject_user_id=sub.user_id,
        before={"price_id": str(old_price)},
        after={"price_id": str(sub.price_id), "applied": "renewal"},
    )
