"""Commerce endpoints (api-specification §17 COM, §18 WH).

Implemented: COM-01..12, COM-15, COM-17..36, COM-38..41, COM-43..46, a finance revenue
report, commerce Dual approvals (``/finance/approval-requests``), WH-01 (+ WH-02 signature
verification only, behind the Cashfree flag), COM-13 resume, COM-14 plan change, COM-16
invoice/credit-note PDFs (+ finance variant), COM-37 GST register export (commerce-owned job,
``gst_exports``; Dual via ADM-14 above 10,000 rows). Single company (REMOVAL-PLAN §1.2): the
B2B institution routes (COM-40..42, COM-44 org views) were removed; B2C buyers may still give a
GSTIN for a tax invoice (D1). Per-endpoint rate limits: ``ratelimit.py`` (backlog A-7).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, tuple_

from app.core import auth as core_auth
from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, require_permission, require_step_up
from app.core.config import get_settings
from app.core.db import DbSession, PrincipalDbSession, get_sessionmaker
from app.core.errors import ProblemError, problem_response
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.pagination import decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router, public_router
from app.core.time import utcnow
from app.modules.commerce import admin, billing, billing_approvals, documents, policy, schemas, webhooks
from app.modules.commerce import service as svc
from app.modules.commerce.gateway import get_gateway
from app.modules.commerce.models import (
    Coupon,
    GstExport,
    Invoice,
    Order,
    OrderItem,
    Payment,
    PaymentWebhookEvent,
    Plan,
    Product,
    ReconciliationRun,
    Refund,
    Subscription,
)
from app.modules.commerce.pricing import as_system, build_quote, load_price
from app.modules.commerce.ratelimit import limit, webhook_invalid_signature_hit
from app.modules.entitlements import service as ent
from app.modules.rbac.catalogue import ADMIN_ROLE

pub = public_router(tags=["commerce"])
r = authenticated_router(tags=["commerce"])
acct = authenticated_router(tags=["commerce"], route_tag="account_status", idle="neutral")
fin = authenticated_router(prefix="/finance", tags=["finance"])
webhook_router = public_router(tags=["webhooks"])

P5 = Depends(require_step_up("privileged"))


def _list(rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    return {"data": rows, "page": page_meta(None, limit)}


def _keyset(q: Any, model: Any, cursor: str | None, limit: int, *, desc: bool = True) -> Any:
    """ADM-32: keyset pagination on ``(created_at, id)`` (signed opaque cursor)."""
    if cursor:
        pos = decode_cursor(cursor)
        try:
            t, i = datetime.fromisoformat(str(pos["t"])), uuid.UUID(str(pos["i"]))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
        key = tuple_(model.created_at, model.id)
        q = q.where(key < tuple_(t, i) if desc else key > tuple_(t, i))
    order = (model.created_at.desc(), model.id.desc()) if desc else (model.created_at, model.id)
    return q.order_by(*order).limit(limit + 1)


def _page(rows: list[Any], limit: int) -> tuple[list[Any], dict[str, Any]]:
    more = len(rows) > limit
    rows = rows[:limit]
    nxt = {"t": rows[-1].created_at.isoformat(), "i": str(rows[-1].id)} if more and rows else None
    return rows, page_meta(nxt, limit)


async def has_permission(principal: Principal, permission: str, request: Request) -> bool:
    return await core_auth.check_permission(
        principal, permission, PLATFORM_SCOPE, request, cross_tenant_raises=True
    )


async def _signal(session: Any, principal: Principal | None, action: str, data: dict[str, Any]) -> None:
    await audit(
        session,
        principal if principal else webhooks.GATEWAY_ACTOR,
        action,
        "order",
        None,
        reason_code="AB-checkout",
        after=data,
    )
    await emit_event(session, action, data, aggregate_type="commerce", aggregate_id=uuid7())


# =========================================================================== public catalogue


@pub.get("/commerce/products")
async def list_products(session: DbSession) -> dict[str, Any]:
    """COM-01: active products, plans, current prices with GST breakup, refund rule."""
    data = await admin.catalogue(session, include_drafts=False)
    return _list(data, len(data))


@pub.get("/commerce/products/{sku}")
async def get_product(sku: str, session: DbSession) -> dict[str, Any]:
    data = await admin.catalogue(session, include_drafts=False, sku=sku)
    if not data:
        raise ProblemError("not_found")
    return data[0]


# =========================================================================== checkout


@r.post("/commerce/checkout/quote")
async def quote(
    body: schemas.QuoteIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
    _rl: Principal = Depends(limit("com03_quote")),
) -> dict[str, Any]:
    q = await build_quote(
        session,
        principal,
        price_id=body.price_id,
        coupon_code=body.coupon_code,
        state_code=body.billing.state_code,
    )
    return q.to_json()


@r.post("/commerce/orders", status_code=201)
async def create_order(
    request: Request,
    body: schemas.OrderIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
    _rl: Principal = Depends(limit("com04_order")),
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key") or ""

    async def op() -> IdemResult:
        await svc.buyer_checks(session, principal, paid=True)
        gw = get_gateway()
        async with as_system(session, "commerce.order_resume", principal):
            existing = await svc.find_resumable_order(
                session,
                principal,
                price_id=body.price_id,
                coupon_code=body.coupon_code,
                state_code=body.billing.state_code,
                quote_total_paise=body.quote_total_paise,
            )
        if existing is not None:  # FE-27: a reload resumes the pending order, no duplicate
            out = {
                **svc.order_json(existing),
                "checkout": svc.checkout_payload(get_gateway(existing.gateway or gw.name), existing),
                "entitlements": [],
                "resumed": True,
            }
            return IdemResult(out, 201, existing.id)
        q = await build_quote(
            session,
            principal,
            price_id=body.price_id,
            coupon_code=body.coupon_code,
            state_code=body.billing.state_code,
            lock_coupon=True,
        )
        out = await svc.create_order(
            session,
            principal,
            gw,
            q,
            idempotency_key=key,
            billing_name=body.billing.name,
            billing_gstin=body.billing.gstin,
            quote_total_paise=body.quote_total_paise,
        )
        return IdemResult(out, 201, uuid.UUID(out["order_id"]))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, money=True)


async def _own_order(session: Any, principal: Principal, order_id: uuid.UUID, lock: bool = False) -> Order:
    q = select(Order).where(Order.id == order_id, Order.user_id == principal.user_id)
    o = (await session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if o is None:
        raise ProblemError("not_found")
    return o


@acct.get("/commerce/orders/{order_id}")
async def get_order(
    order_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
    _rl: Principal = Depends(limit("com05_order_status")),
) -> dict[str, Any]:
    o = await _own_order(session, principal, order_id)
    items = list((await session.execute(select(OrderItem).where(OrderItem.order_id == o.id))).scalars())
    out = svc.order_json(o, items)
    out["entitlements"] = await svc.order_entitlements(session, o.id)
    # FE-26: an unexpired pending order carries the checkout payload so payment can resume.
    out["checkout"] = (
        svc.checkout_payload(get_gateway(o.gateway or "razorpay"), o) if svc.is_resumable(o) else None
    )
    if o.status == "pending_payment" and o.expires_at > utcnow():
        out["message"] = (
            "Payment received by bank, confirming…"
            if (
                await session.execute(
                    select(func.count())
                    .select_from(Payment)
                    .where(Payment.order_id == o.id, Payment.status == "authorized")
                )
            ).scalar_one()
            else None
        )
    return out


@r.post("/commerce/orders/{order_id}/confirm")
async def confirm_order(
    order_id: uuid.UUID,
    request: Request,
    body: schemas.ConfirmIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
    _rl: Principal = Depends(limit("com06_confirm")),
) -> JSONResponse:
    """COM-06. Signature failure → 400 + security signal, committed (not rolled back)."""
    if not request.headers.get("Idempotency-Key"):
        raise ProblemError("idempotency_key_required")
    o = await _own_order(session, principal, order_id)
    gw = get_gateway(o.gateway or "razorpay")
    if body.razorpay_order_id != o.gateway_order_id or not gw.verify_checkout_signature(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    ):
        await _signal(session, principal, "abuse.checkout_signature_invalid", {"order_id": str(o.id)})
        return problem_response(ProblemError("payment_signature_invalid"))

    async def op() -> IdemResult:
        order = await _own_order(session, principal, order_id, lock=True)
        return IdemResult(await svc.confirm_order(session, principal, gw, order, body.razorpay_payment_id))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, money=True)


@r.post("/commerce/orders/{order_id}/cancel")
async def cancel_order(
    order_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        o = await _own_order(session, principal, order_id, lock=True)
        return IdemResult(await svc.cancel_order(session, principal, o))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@acct.get("/me/orders")
async def my_orders(
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
) -> dict[str, Any]:
    q = _keyset(select(Order).where(Order.user_id == principal.user_id), Order, cursor, limit)
    rows, page = _page(list((await session.execute(q)).scalars()), limit)
    return {"data": [svc.order_json(o) for o in rows], "page": page}


# =========================================================================== subscriptions


@r.post("/commerce/subscriptions", status_code=201)
async def create_subscription(
    request: Request,
    body: schemas.SubscriptionIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
    _rl: Principal = Depends(limit("com09_subscription")),
) -> JSONResponse:
    async def op() -> IdemResult:
        await svc.buyer_checks(session, principal, paid=True)
        price, plan, product = await load_price(session, body.price_id)
        out = await svc.create_subscription(
            session,
            principal,
            get_gateway(),
            price,
            plan,
            product,
            billing_name=body.billing.name,
            billing_state_code=body.billing.state_code,
            billing_gstin=body.billing.gstin,
        )
        return IdemResult(out, 201, uuid.UUID(out["subscription_id"]))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, money=True)


async def _own_sub(session: Any, principal: Principal, sub_id: uuid.UUID) -> Subscription:
    s = (
        await session.execute(
            select(Subscription)
            .where(Subscription.id == sub_id, Subscription.user_id == principal.user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if s is None:
        raise ProblemError("not_found")
    return s


@r.post("/commerce/subscriptions/{subscription_id}/confirm")
async def confirm_subscription(
    subscription_id: uuid.UUID,
    request: Request,
    body: schemas.SubscriptionConfirmIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
    _rl: Principal = Depends(limit("com10_subscription_confirm")),
) -> JSONResponse:
    if not request.headers.get("Idempotency-Key"):
        raise ProblemError("idempotency_key_required")
    sub = await _own_sub(session, principal, subscription_id)
    gw = get_gateway(sub.gateway)
    if body.razorpay_subscription_id != sub.gateway_subscription_id or not gw.verify_subscription_signature(
        body.razorpay_payment_id, body.razorpay_subscription_id, body.razorpay_signature
    ):
        await _signal(
            session, principal, "abuse.checkout_signature_invalid", {"subscription_id": str(sub.id)}
        )
        return problem_response(ProblemError("payment_signature_invalid"))

    async def op() -> IdemResult:
        from app.modules.commerce.gateway import GatewayUnavailable

        s = await _own_sub(session, principal, subscription_id)
        try:
            gs = await gw.fetch_subscription(s.gateway_subscription_id)
            gp = await gw.fetch_payment(body.razorpay_payment_id)
        except GatewayUnavailable as e:
            raise ProblemError("service_unavailable") from e
        actor = ent.Actor.user(principal)
        async with as_system(session, "commerce.subscription_confirm", principal):
            if gp.subscription_id == s.gateway_subscription_id:
                await svc.record_subscription_charge(session, gw, s, gp, actor)
            await svc.apply_subscription_state(session, s, gs, actor)
        return IdemResult(svc.sub_json(s))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, money=True)


@acct.get("/me/subscriptions")
async def my_subscriptions(
    session: PrincipalDbSession, principal: Principal = Depends(core_auth.require_active_principal)
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Subscription)
            .where(Subscription.user_id == principal.user_id)
            .order_by(Subscription.created_at.desc())
        )
    ).scalars()
    return _list([svc.sub_json(s) for s in rows], 100)


@acct.post("/me/subscriptions/{subscription_id}/cancel")
async def cancel_my_subscription(
    subscription_id: uuid.UUID,
    request: Request,
    body: schemas.CancelSubIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
    _rl: Principal = Depends(limit("com12_cancel")),
) -> JSONResponse:
    """COM-12: one click; allowed from restricted sessions (account_status)."""

    async def op() -> IdemResult:
        s = await _own_sub(session, principal, subscription_id)
        return IdemResult(
            await svc.cancel_subscription(session, principal, get_gateway(s.gateway), s, reason=body.reason)
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op)


# =========================================================================== invoices & refunds (self)


@acct.get("/me/invoices")
async def my_invoices(
    session: PrincipalDbSession, principal: Principal = Depends(core_auth.require_active_principal)
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Invoice).where(Invoice.user_id == principal.user_id).order_by(Invoice.created_at.desc())
        )
    ).scalars()
    return _list([svc.invoice_json(i) for i in rows], 100)


@acct.get("/me/orders/{order_id}/refund-eligibility")
async def refund_eligibility(
    order_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
) -> dict[str, Any]:
    o = await _own_order(session, principal, order_id)
    async with as_system(session, "commerce.refund_eligibility", principal):
        return {
            "order_id": str(o.id),
            "refund_rule": policy.REFUND_RULE_TEXT,
            **await svc.refund_eligibility(session, o),
        }


@acct.post("/me/refund-requests", status_code=201)
async def request_refund(
    request: Request,
    body: schemas.RefundRequestIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
    _rl: Principal = Depends(limit("com18_refund_request")),
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key") or ""

    async def op() -> IdemResult:
        o = await _own_order(session, principal, body.order_id, lock=True)
        async with as_system(session, "commerce.refund_request", principal):
            rf, elig = await svc.create_refund_request(
                session,
                principal,
                o,
                reason_code=body.reason_code,
                note=body.note,
                amount_paise=None,
                idempotency_key=f"{principal.user_id}:{key}",
            )
        due = (utcnow() + timedelta(days=7)).date().isoformat()
        return IdemResult({**svc.refund_json(rf), "eligibility": elig, "decision_due": due}, 201, rf.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, money=True)


@acct.get("/me/refund-requests")
async def my_refunds(
    session: PrincipalDbSession, principal: Principal = Depends(core_auth.require_active_principal)
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Refund).where(Refund.requested_by == principal.user_id).order_by(Refund.created_at.desc())
        )
    ).scalars()
    return _list([svc.refund_json(x) for x in rows], 100)


# =========================================================================== finance: catalogue


@fin.get("/products")
async def fin_products(
    session: PrincipalDbSession, _p: Principal = Depends(require_permission("product.manage"))
) -> dict[str, Any]:
    data = await admin.catalogue(session, include_drafts=True)
    return _list(data, len(data))


@fin.post("/products", status_code=201)
async def fin_create_product(
    body: schemas.ProductIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("product.manage")),
    _s: Principal = P5,
) -> dict[str, Any]:
    p = await admin.create_product(session, principal, body)
    return admin.product_json(p)


async def _product(session: Any, product_id: uuid.UUID) -> Product:
    p = (
        await session.execute(select(Product).where(Product.id == product_id).with_for_update())
    ).scalar_one_or_none()
    if p is None:
        raise ProblemError("not_found")
    return p


@fin.patch("/products/{product_id}")
async def fin_patch_product(
    product_id: uuid.UUID,
    body: schemas.ProductPatchIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("product.manage")),
    _s: Principal = P5,
) -> dict[str, Any]:
    p = await _product(session, product_id)
    before = admin.product_json(p)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    await session.flush()
    await audit(
        session, principal, "product.updated", "product", p.id, before=before, after=admin.product_json(p)
    )
    return admin.product_json(p)


@fin.post("/products/{product_id}/plans", status_code=201)
async def fin_create_plan(
    product_id: uuid.UUID,
    body: schemas.PlanIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("price.manage")),
    _s: Principal = P5,
) -> dict[str, Any]:
    p = await _product(session, product_id)
    pl = await admin.create_plan(session, principal, p, body)
    return admin.plan_json(pl, [])


@fin.post("/plans/{plan_id}/prices", status_code=201)
async def fin_create_price(
    plan_id: uuid.UUID,
    request: Request,
    body: schemas.PriceIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("price.manage")),
    _s: Principal = P5,
) -> JSONResponse:
    """COM-24: no overlapping active windows; Dual for > 20 % decrease or live subscriptions."""

    async def op() -> IdemResult:
        from app.modules.rbac.service import create_approval_request

        plan = (
            await session.execute(select(Plan).where(Plan.id == plan_id).with_for_update())
        ).scalar_one_or_none()
        if plan is None:
            raise ProblemError("not_found")
        if plan.billing_type == "recurring" and body.amount_paise > policy.MANDATE_MAX_PAISE:
            raise ProblemError("recurring_amount_exceeds_mandate_limit", max_paise=policy.MANDATE_MAX_PAISE)
        vf = body.valid_from or utcnow()
        if await admin.price_change_needs_dual(session, plan, body.amount_paise):
            req = await create_approval_request(
                session,
                principal,
                action_type="commerce.price.create",
                target_type="plan",
                target_id=plan.id,
                payload={
                    "plan_id": str(plan.id),
                    "amount_paise": body.amount_paise,
                    "valid_from": vf.isoformat(),
                    "valid_until": body.valid_until.isoformat() if body.valid_until else None,
                },
                reason=body.reason,
                required_approver_role=ADMIN_ROLE,
            )
            return IdemResult({"status": "approval_pending", "approval_request_id": str(req.id)}, 202)
        pr = await admin.apply_price(
            session,
            plan,
            amount_paise=body.amount_paise,
            valid_from=vf,
            valid_until=body.valid_until,
            created_by=principal.user_id,
        )
        await audit(
            session, principal, "price.created", "price", pr.id, after={"amount_paise": pr.amount_paise}
        )
        return IdemResult(
            {"status": "created", "price_id": str(pr.id), "amount_paise": pr.amount_paise}, 201, pr.id
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op, money=True)


# =========================================================================== finance: coupons


@fin.get("/coupons")
async def fin_coupons(
    session: PrincipalDbSession,
    _p: Principal = Depends(require_permission("coupon.manage")),
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = None,
    status: str | None = Query(None, pattern="^(active|paused|expired)$"),
) -> dict[str, Any]:
    """Coupon list (webstaff R6): optional server-side ``status`` filter; each coupon carries the
    id of its pending ``commerce.coupon.activate`` approval (``approval_request_id``) or null."""
    q = select(Coupon)
    if status:
        q = q.where(Coupon.status == status)
    rows, page = _page(list((await session.execute(_keyset(q, Coupon, cursor, limit))).scalars()), limit)
    pending = await admin.pending_coupon_approvals(session, [c.id for c in rows])
    return {"data": [admin.coupon_json(c, pending.get(c.id)) for c in rows], "page": page}


@fin.post("/coupons", status_code=201)
async def fin_create_coupon(
    body: schemas.CouponIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("coupon.manage")),
    _s: Principal = P5,
) -> JSONResponse:
    """COM-26: > 50 % off, free access, or > 1,000 (or unlimited) redemptions needs a second
    finance approval: the coupon is created ``paused`` until approved."""
    from app.modules.admin import approvals as apr
    from app.modules.rbac.service import create_approval_request

    dup = (
        await session.execute(select(Coupon.id).where(func.lower(Coupon.code) == body.code.lower()))
    ).scalar_one_or_none()
    if dup:
        raise ProblemError(
            "validation_failed", errors=[{"field": "code", "code": "duplicate", "message": "Code exists"}]
        )
    dual = admin.coupon_needs_dual(body.discount_type, body.percent_off, body.max_redemptions)
    c = Coupon(
        id=uuid7(),
        code=body.code,
        discount_type=body.discount_type,
        percent_off=body.percent_off,
        amount_off_paise=body.amount_off_paise,
        applicable_product_ids=body.applicable_product_ids,
        min_order_paise=body.min_order_paise,
        max_redemptions=body.max_redemptions,
        per_user_limit=body.per_user_limit,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        first_time_only=body.first_time_only,
        status="paused" if dual else "active",
        created_by=principal.user_id,
    )
    session.add(c)
    await session.flush()
    await audit(session, principal, "coupon.created", "coupon", c.id, after=admin.coupon_json(c))
    out = admin.coupon_json(c)
    if dual:
        req = await create_approval_request(
            session,
            principal,
            action_type="commerce.coupon.activate",
            target_type="coupon",
            target_id=c.id,
            payload={"coupon_id": str(c.id)},
            reason=body.reason,
            required_approver_role=ADMIN_ROLE,
        )
        # Approval envelope (§1.7 ``202 approval_pending``) next to the coupon fields; the coupon's
        # own ``status`` (``paused``) is kept, so the envelope status is ``approval_status``.
        env = apr.pending_response(req)
        return JSONResponse(
            {
                **admin.coupon_json(c, req.id),
                "approval_status": env["status"],
                "action_type": env["action_type"],
                "required_approver_role": env["required_approver_role"],
                "expires_at": env["expires_at"],
            },
            202,
        )
    return JSONResponse(out, 201)


@fin.patch("/coupons/{coupon_id}")
async def fin_patch_coupon(
    coupon_id: uuid.UUID,
    body: schemas.CouponPatchIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("coupon.manage")),
    _s: Principal = P5,
) -> dict[str, Any]:
    c = (
        await session.execute(select(Coupon).where(Coupon.id == coupon_id).with_for_update())
    ).scalar_one_or_none()
    if c is None:
        raise ProblemError("not_found")
    before = admin.coupon_json(c)
    upd = body.model_dump(exclude_unset=True)
    loosening = (upd.get("status") == "active" and c.status == "paused") or (
        # ADM-26: ``None`` means unlimited, so it always loosens a capped coupon.
        "max_redemptions" in upd
        and c.max_redemptions is not None
        and (upd["max_redemptions"] is None or upd["max_redemptions"] > c.max_redemptions)
    )
    if loosening and admin.coupon_needs_dual(
        c.discount_type, c.percent_off, upd.get("max_redemptions", c.max_redemptions)
    ):
        raise ProblemError(
            "second_approval_required", detail="Re-create the coupon to route it through approval."
        )
    for k, v in upd.items():
        setattr(c, k, v)
    await session.flush()
    await audit(
        session, principal, "coupon.updated", "coupon", c.id, before=before, after=admin.coupon_json(c)
    )
    pending = await admin.pending_coupon_approvals(session, [c.id])
    return admin.coupon_json(c, pending.get(c.id))


# ============================================================ finance: orders/refunds/subs/invoices


@fin.get("/orders")
async def fin_orders(
    session: PrincipalDbSession,
    _p: Principal = Depends(require_permission("order.read")),
    status: str | None = None,
    user_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
) -> dict[str, Any]:
    q = select(Order)
    if status:
        q = q.where(Order.status == status)
    if user_id:
        q = q.where(Order.user_id == user_id)
    rows, page = _page(list((await session.execute(_keyset(q, Order, cursor, limit))).scalars()), limit)
    return {"data": [svc.order_json(o) for o in rows], "page": page}


@fin.get("/orders/{order_id}")
async def fin_order(
    order_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("order.read")),
) -> dict[str, Any]:
    o = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if o is None:
        raise ProblemError("not_found")
    items = list((await session.execute(select(OrderItem).where(OrderItem.order_id == o.id))).scalars())
    out = svc.order_json(o, items)
    if await has_permission(principal, "payment.read", request):
        pays = (await session.execute(select(Payment).where(Payment.order_id == o.id))).scalars()
        out["payments"] = [
            {
                "payment_id": str(p.id),
                "gateway_payment_id": p.gateway_payment_id,
                "status": p.status,
                "method": p.method,
                "amount_paise": p.amount_paise,
                "card_last4": p.card_last4,
                "vpa_masked": p.vpa_masked,
                "error_code": p.error_code,
            }
            for p in pays
        ]
    events = (
        await session.execute(
            select(PaymentWebhookEvent)
            .where(PaymentWebhookEvent.order_id == o.id)
            .order_by(PaymentWebhookEvent.received_at)
        )
    ).scalars()
    out["webhook_events"] = [
        {
            "event_type": e.event_type,
            "status": e.status,
            "is_stale": e.is_stale,
            "refetch_status": e.refetch_status,
            "received_at": e.received_at.isoformat(),
        }
        for e in events
    ]
    out["entitlements"] = await svc.order_entitlements(session, o.id)
    out["invoices"] = [
        svc.invoice_json(i)
        for i in (await session.execute(select(Invoice).where(Invoice.order_id == o.id))).scalars()
    ]
    return out


@fin.get("/refunds")
async def fin_refunds(
    session: PrincipalDbSession,
    _p: Principal = Depends(require_permission("refund.decide")),
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
) -> dict[str, Any]:
    q = select(Refund)
    if status:
        q = q.where(Refund.status == status)
    rows, page = _page(
        list((await session.execute(_keyset(q, Refund, cursor, limit, desc=False))).scalars()), limit
    )
    out = []
    for rf in rows:  # eligibility is computed for at most ``limit`` rows (was unbounded)
        o = (await session.execute(select(Order).where(Order.id == rf.order_id))).scalar_one()
        elig = (
            await svc.refund_eligibility(session, o) if o.status in ("paid", "partially_refunded") else None
        )
        out.append({**svc.refund_json(rf), "eligibility": elig})
    return {"data": out, "page": page}


async def _decide_refund(
    session: Any, request: Request, principal: Principal, rf: Refund, body: schemas.RefundDecisionIn
) -> IdemResult:
    from app.modules.rbac.service import create_approval_request

    if rf.status != "requested":
        raise ProblemError("invalid_state_transition", current_state=rf.status, allowed=["requested"])
    if body.decision == "reject":
        rf.status = "rejected"
        await session.flush()
        await audit(session, principal, "refund.rejected", "refund", rf.id, reason=body.note)
        return IdemResult(svc.refund_json(rf))
    o = (await session.execute(select(Order).where(Order.id == rf.order_id).with_for_update())).scalar_one()
    elig = await svc.refund_eligibility(session, o)
    if not elig["eligible"] and not body.goodwill:
        raise ProblemError("refund_not_eligible", reasons=elig["reasons"])
    # COM-11 / ADM-24: never more than is still refundable on the order; a rule-based
    # (non-goodwill) request by the student is also capped by the rule's refundable amount.
    student_rule = not body.goodwill and rf.requested_by == o.user_id
    await svc.check_refund_amount(
        session,
        o,
        body.amount_paise if body.amount_paise is not None else rf.amount_paise,
        rule_limit_paise=elig["refundable_paise"] if student_rule else None,
    )
    if body.amount_paise is not None:
        rf.amount_paise = body.amount_paise
    if body.goodwill and not await has_permission(principal, "refund.goodwill", request):
        raise ProblemError("permission_denied", permission="refund.goodwill")
    if body.goodwill or rf.amount_paise > policy.REFUND_DUAL_ABOVE_PAISE:
        if body.goodwill:
            rf.reason_code = "goodwill"
        req = await create_approval_request(
            session,
            principal,
            action_type="commerce.refund",
            target_type="refund",
            target_id=rf.id,
            payload={
                "refund_id": str(rf.id),
                "amount_paise": rf.amount_paise,
                "order_item_ids": [str(x) for x in body.order_item_ids or []],
            },
            reason=body.note or "refund approval",
            required_approver_role=ADMIN_ROLE,
        )
        rf.approval_request_id = req.id
        await session.flush()
        return IdemResult({**svc.refund_json(rf), "status": "approval_pending"}, 202)
    await svc.execute_refund(session, get_gateway(), rf, principal, order_item_ids=body.order_item_ids)
    return IdemResult(svc.refund_json(rf))


@fin.post("/refunds/{refund_id}/decision")
async def fin_refund_decision(
    refund_id: uuid.UUID,
    request: Request,
    body: schemas.RefundDecisionIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("refund.decide")),
    _s: Principal = P5,
) -> JSONResponse:
    async def op() -> IdemResult:
        rf = (
            await session.execute(select(Refund).where(Refund.id == refund_id).with_for_update())
        ).scalar_one_or_none()
        if rf is None:
            raise ProblemError("not_found")
        return await _decide_refund(session, request, principal, rf, body)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, money=True)


@fin.post("/refunds", status_code=201)
async def fin_create_refund(
    request: Request,
    body: schemas.FinanceRefundIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("refund.decide")),
    _s: Principal = P5,
) -> JSONResponse:
    """COM-32: finance-initiated (duplicate payment, service failure): outside the student
    rule by definition, decided immediately unless goodwill / > ₹25,000 (Dual)."""
    key = request.headers.get("Idempotency-Key") or ""

    async def op() -> IdemResult:
        o = (
            await session.execute(select(Order).where(Order.id == body.order_id).with_for_update())
        ).scalar_one_or_none()
        if o is None:
            raise ProblemError("not_found")
        rf, _ = await svc.create_refund_request(
            session,
            principal,
            o,
            reason_code=body.reason_code,
            note=body.note,
            amount_paise=body.amount_paise,
            idempotency_key=f"{principal.user_id}:{key}",
        )
        decision = schemas.RefundDecisionIn(
            decision="approve",
            goodwill=body.reason_code == "goodwill",
            note=body.note,
            order_item_ids=body.order_item_ids,
        )
        if decision.goodwill or rf.amount_paise > policy.REFUND_DUAL_ABOVE_PAISE:
            res = await _decide_refund(session, request, principal, rf, decision)
        else:
            await svc.execute_refund(
                session, get_gateway(), rf, principal, order_item_ids=body.order_item_ids
            )
            res = IdemResult(svc.refund_json(rf))
        return IdemResult(res.body, 201 if res.status == 200 else res.status, rf.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, money=True)


@fin.get("/subscriptions")
async def fin_subscriptions(
    session: PrincipalDbSession,
    _p: Principal = Depends(require_permission("order.read")),
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = None,
) -> dict[str, Any]:
    q = select(Subscription)
    if status:
        q = q.where(Subscription.status == status)
    rows, page = _page(
        list((await session.execute(_keyset(q, Subscription, cursor, limit))).scalars()), limit
    )
    return {"data": [{**svc.sub_json(s), "user_id": str(s.user_id)} for s in rows], "page": page}


@fin.post("/subscriptions/{subscription_id}/cancel")
async def fin_cancel_subscription(
    subscription_id: uuid.UUID,
    request: Request,
    body: schemas.AdminCancelSubIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("subscription.admin_cancel")),
    _s: Principal = Depends(require_step_up("staff")),
) -> JSONResponse:
    async def op() -> IdemResult:
        s = (
            await session.execute(
                select(Subscription).where(Subscription.id == subscription_id).with_for_update()
            )
        ).scalar_one_or_none()
        if s is None:
            raise ProblemError("not_found")
        return IdemResult(
            await svc.cancel_subscription(
                session,
                principal,
                get_gateway(s.gateway),
                s,
                reason=body.reason,
                immediate=body.immediate,
                ticket_ref=body.ticket_ref,
            )
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op)


@fin.get("/invoices")
async def fin_invoices(
    session: PrincipalDbSession,
    _p: Principal = Depends(require_permission("invoice.read")),
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = None,
    invoice_type: str | None = Query(None, pattern="^(tax_invoice|credit_note)$"),
) -> dict[str, Any]:
    q = select(Invoice)
    if invoice_type:
        q = q.where(Invoice.invoice_type == invoice_type)
    rows, page = _page(list((await session.execute(_keyset(q, Invoice, cursor, limit))).scalars()), limit)
    return {"data": [svc.invoice_json(i) for i in rows], "page": page}


@fin.post("/invoices/{invoice_id}/credit-notes", status_code=201)
async def fin_credit_note(
    invoice_id: uuid.UUID,
    request: Request,
    body: schemas.CreditNoteIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("invoice.credit_note")),
    _s: Principal = P5,
) -> JSONResponse:
    async def op() -> IdemResult:
        inv = (await session.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one_or_none()
        if inv is None or inv.invoice_type != "tax_invoice":
            raise ProblemError("not_found")
        o = (await session.execute(select(Order).where(Order.id == inv.order_id))).scalar_one()
        credited = (
            await session.execute(
                select(func.coalesce(func.sum(Invoice.total_paise), 0)).where(
                    Invoice.original_invoice_id == inv.id
                )
            )
        ).scalar_one()
        if body.amount_paise + int(credited) > inv.total_paise:
            raise ProblemError(
                "validation_failed",
                errors=[
                    {"field": "amount_paise", "code": "exceeds_invoice", "message": "More than the invoice"}
                ],
            )
        cn = await svc.issue_credit_note(session, o, body.amount_paise)
        await audit(session, principal, "invoice.credit_note", "invoice", cn.id, reason=body.reason)
        return IdemResult(svc.invoice_json(cn), 201, cn.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, money=True)


# =========================================================================== reconciliation & reports


@fin.get("/reconciliation")
async def fin_reconciliation(
    session: PrincipalDbSession, _p: Principal = Depends(require_permission("reconciliation.run"))
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(ReconciliationRun).order_by(ReconciliationRun.created_at.desc()).limit(30)
        )
    ).scalars()
    return _list([admin.run_json(x) for x in rows], 30)


@fin.post("/reconciliation/runs", status_code=201)
async def fin_run_reconciliation(
    body: schemas.ReconciliationIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("reconciliation.run")),
    _rl: Principal = Depends(limit("com46_reconciliation")),
) -> dict[str, Any]:
    if body.range_to <= body.range_from or body.range_to - body.range_from > timedelta(days=31):
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "range_to", "code": "invalid_range", "message": "1-31 days"}],
        )
    async with as_system(session, "commerce.reconciliation", principal):
        run = await admin.run_reconciliation(
            session,
            get_gateway(),
            range_from=body.range_from,
            range_to=body.range_to,
            triggered_by=f"user:{principal.user_id}",
        )
        out = admin.run_json(run)
    await audit(session, principal, "reconciliation.run", "reconciliation_run", run.id, after=run.summary)
    return out


@fin.get("/reports/revenue")
async def fin_revenue(
    session: PrincipalDbSession,
    _p: Principal = Depends(require_permission("order.read")),
    range_from: datetime | None = None,
    range_to: datetime | None = None,
) -> dict[str, Any]:
    to = range_to or utcnow()
    frm = range_from or (to - timedelta(days=1))
    return await admin.revenue_report(session, frm, to)


# =========================================================================== commerce Dual approvals


async def _decide_approval(
    session: Any, principal: Principal, approval_id: uuid.UUID, approve: bool, note: str | None
) -> dict[str, Any]:
    from app.modules.rbac.models import ApprovalRequest
    from app.modules.rbac.service import payload_hash

    req = (
        await session.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()
        )
    ).scalar_one_or_none()
    if req is None or req.action_type not in admin.COMMERCE_ACTIONS:
        raise ProblemError("not_found")
    if req.status != "pending":
        raise ProblemError("invalid_state_transition", current_state=req.status, allowed=["pending"])
    if req.expires_at <= utcnow():
        # ADM-23: persist ``expired`` (raising would roll the status change back).
        req.status = "expired"
        await session.flush()
        return {"_expired": True}
    if req.requested_by == principal.user_id:
        raise ProblemError("sod_violation", rule="SoD-dual-control")
    if not principal.has_role(req.required_approver_role, "platform"):
        raise ProblemError("permission_denied", permission="approval.decide")
    if payload_hash(req.payload) != req.payload_hash:
        raise ProblemError("invalid_state_transition", current_state="payload_tampered", allowed=[])
    req.decided_by, req.decided_at, req.decision_note = principal.user_id, utcnow(), note
    if not approve:
        req.status = "rejected"
        if req.action_type == "commerce.refund":
            rf = (
                await session.execute(select(Refund).where(Refund.id == req.target_id))
            ).scalar_one_or_none()
            if rf is not None and rf.status == "requested":
                rf.status = "rejected"
        await audit(session, principal, "approval.rejected", "approval_request", req.id, reason=note)
        return {"approval_request_id": str(req.id), "status": "rejected"}
    req.status = "approved"
    await session.flush()
    async with as_system(session, "commerce.approval_execute", principal):
        result = await admin.execute_approval(
            session, get_gateway(), principal, req.action_type, req.payload, req.requested_by
        )
    req.status = "executed"
    req.executed_at = utcnow()
    await audit(
        session,
        principal,
        "approval.executed",
        "approval_request",
        req.id,
        reason=note,
        after={"action_type": req.action_type},
    )
    return {"approval_request_id": str(req.id), "status": "executed", "result": result}


@fin.post("/approval-requests/{approval_request_id}/approve")
async def fin_approve(
    approval_request_id: uuid.UUID,
    body: schemas.ApprovalDecisionIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("approval.decide")),
    _s: Principal = P5,
) -> Any:
    return _approval_response(
        await _decide_approval(session, principal, approval_request_id, True, body.note)
    )


@fin.post("/approval-requests/{approval_request_id}/reject")
async def fin_reject(
    approval_request_id: uuid.UUID,
    body: schemas.ApprovalDecisionIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("approval.decide")),
    _s: Principal = P5,
) -> Any:
    return _approval_response(
        await _decide_approval(session, principal, approval_request_id, False, body.note)
    )


def _approval_response(out: dict[str, Any]) -> Any:
    if out.pop("_expired", False):
        return problem_response(ProblemError("invalid_state_transition", current_state="expired", allowed=[]))
    return out


# =========================================================================== webhooks (WH-01/02)


async def _cashfree_enabled() -> bool:
    """ADM-17 flag consumer: ``payments.cashfree_enabled`` (admin feature flag, platform-wide)."""
    from app.modules.admin.router import flag_enabled

    async with get_sessionmaker()() as session, session.begin():
        return await flag_enabled(session, "payments.cashfree_enabled")


@webhook_router.post("/webhooks/{provider}")
async def provider_webhook(provider: str, request: Request) -> JSONResponse:
    """Public; HMAC over the raw body; permanent dedupe on the event id; never rejected for
    age; state applied only from a provider re-fetch. Responses carry no internal ids."""
    if provider not in ("razorpay", "cashfree"):
        raise ProblemError("not_found")
    if provider == "cashfree" and not await _cashfree_enabled():
        raise ProblemError("not_found")  # ADM-17: runtime flag on top of the env switch
    gw = get_gateway(provider)
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    ip = getattr(request.state, "client_ip", None)
    queued: uuid.UUID | None = None
    inline = get_settings().TD_COMMERCE_WEBHOOK_MODE == "inline"
    try:
        async with get_sessionmaker()() as session, session.begin():
            if not gw.verify_webhook(raw, headers):
                # Per-IP sanity limit: counts only unverifiable requests, so a valid signed
                # event is never dropped; a flood of forgeries stops costing DB writes.
                await webhook_invalid_signature_hit(ip)
                await webhooks.record_invalid_signature(session, provider, raw, ip)
                return problem_response(ProblemError("webhook_signature_invalid"))
            payload = webhooks.parse_body(raw)
            if payload is None:
                return problem_response(ProblemError("validation_failed", detail="Malformed JSON"))
            status, row_id = await webhooks.ingest(session, gw, raw, headers, payload)
            if row_id is not None and status == "accepted":
                if inline:
                    await webhooks.process_event(session, gw, row_id)
                else:
                    queued = row_id
    except ProblemError:
        raise
    except Exception as e:  # DB unavailable etc.: make the provider retry
        import structlog

        structlog.get_logger("commerce.webhooks").exception("webhook_persist_failed", provider=provider)
        raise ProblemError("service_unavailable") from e
    if queued is not None:  # after commit: the worker must see the row
        from app.modules.commerce.tasks import enqueue_webhook_event

        enqueue_webhook_event(provider, queued)
    return JSONResponse({"status": status})


@webhook_router.get("/webhooks/{provider}/health", include_in_schema=False)
async def webhook_health(provider: str) -> dict[str, str]:
    return {"status": "ok" if provider in ("razorpay", "cashfree") else "unknown"}


# =========================================================================== COM-13 / COM-14


@acct.post("/me/subscriptions/{subscription_id}/resume")
async def resume_my_subscription(
    subscription_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
) -> JSONResponse:
    """COM-13: undo a scheduled (period-end) cancellation before the period ends."""

    async def op() -> IdemResult:
        s = await _own_sub(session, principal, subscription_id)
        return IdemResult(await billing.resume_subscription(session, principal, get_gateway(s.gateway), s))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@r.post("/me/subscriptions/{subscription_id}/change-plan")
async def change_my_plan(
    subscription_id: uuid.UUID,
    request: Request,
    body: schemas.ChangePlanIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
    _rl: Principal = Depends(limit("com14_change_plan")),
) -> JSONResponse:
    """COM-14: upgrade now (proration added to the next debit, debit <= Rs 15,000) or
    downgrade at renewal; ``preview`` computes without changing (rules: ``billing.py``)."""

    async def op() -> IdemResult:
        s = await _own_sub(session, principal, subscription_id)
        async with as_system(session, "commerce.plan_change", principal):
            out = await billing.change_plan(
                session, principal, get_gateway(s.gateway), s, body.price_id, preview=body.preview
            )
        return IdemResult(out)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, money=True)


# =========================================================================== COM-16 invoice PDFs


async def _pdf_link(session: Any, principal: Principal | None, inv: Invoice) -> dict[str, Any]:
    async with as_system(session, "commerce.invoice_pdf", principal):
        key = await documents.ensure_invoice_pdf(session, inv)
    return documents.signed(key, documents.invoice_filename(inv))


@acct.get("/me/invoices/{invoice_id}/pdf")
async def my_invoice_pdf(
    invoice_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(core_auth.require_active_principal),
) -> dict[str, Any]:
    """COM-16: own invoice / credit note PDF; signed URL valid 5 minutes."""
    inv = (
        await session.execute(
            select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == principal.user_id)
        )
    ).scalar_one_or_none()
    if inv is None:
        raise ProblemError("not_found")
    return await _pdf_link(session, principal, inv)


@fin.get("/invoices/{invoice_id}/pdf")
async def fin_invoice_pdf(
    invoice_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("invoice.read")),
) -> dict[str, Any]:
    inv = (await session.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one_or_none()
    if inv is None:
        raise ProblemError("not_found")
    out = await _pdf_link(session, principal, inv)
    await audit(session, principal, "invoice.pdf_downloaded", "invoice", inv.id)
    return out


# =========================================================================== COM-37 GST exports


async def _ensure_export_perm(principal: Principal, request: Request) -> None:
    if not await has_permission(principal, "report.export.request", request):
        raise ProblemError("permission_denied", permission="report.export.request")


@fin.post("/gst-exports", status_code=202)
async def fin_gst_export(
    request: Request,
    body: schemas.GstExportIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("invoice.read")),
    _s: Principal = P5,
    _rl: Principal = Depends(limit("com37_gst_export")),
) -> JSONResponse:
    """COM-37: GST register (invoices + credit notes with tax breakup) for an IST period.
    <= 10,000 rows: rendered now (``ready``). Above: ``awaiting_approval`` until a
    ``super_admin`` holding ``report.export.approve`` (not the requester) approves via ADM-14."""
    await _ensure_export_perm(principal, request)
    if body.period_to < body.period_from:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "period_to", "code": "before_start", "message": "End before start"}],
        )
    if (body.period_to - body.period_from).days + 1 > policy.GST_EXPORT_MAX_DAYS:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "period_to", "code": "too_long", "message": "At most 366 days"}],
        )

    async def op() -> IdemResult:
        from app.modules.admin import approvals as apr

        job = GstExport(
            id=uuid7(),
            requested_by=principal.user_id,
            period_from=body.period_from,
            period_to=body.period_to,
            reason=body.reason,
            status="awaiting_approval",
        )
        session.add(job)
        await session.flush()
        n = await billing.count_gst_rows(session, body.period_from, body.period_to)
        if n > policy.GST_EXPORT_DUAL_ABOVE_ROWS:
            req = await apr.new_request(
                session,
                principal,
                action_type=billing_approvals.GST_EXPORT_ACTION,
                target_type="gst_export",
                target_id=job.id,
                payload={
                    "gst_export_id": str(job.id),
                    "period_from": body.period_from.isoformat(),
                    "period_to": body.period_to.isoformat(),
                    "rows": n,
                },
                reason=body.reason or f"GST register {body.period_from}..{body.period_to}",
                required_approver_role="super_admin",
            )
            job.approval_request_id = req.id
            job.row_count = n
            await session.flush()
        else:
            await billing.render_gst_export(session, job)
        await audit(
            session,
            principal,
            "export.requested",
            "gst_export",
            job.id,
            after={
                "period_from": body.period_from.isoformat(),
                "period_to": body.period_to.isoformat(),
                "rows": n,
                "status": job.status,
            },
        )
        return IdemResult(billing.gst_export_json(job), 202, job.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


async def _own_export(session: Any, principal: Principal, export_id: uuid.UUID) -> GstExport:
    job = (await session.execute(select(GstExport).where(GstExport.id == export_id))).scalar_one_or_none()
    if job is None or job.requested_by != principal.user_id:
        raise ProblemError("not_found")
    return job


@fin.get("/gst-exports")
async def fin_gst_exports(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("invoice.read")),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(GstExport)
            .where(GstExport.requested_by == principal.user_id)
            .order_by(GstExport.created_at.desc())
            .limit(50)
        )
    ).scalars()
    return _list([billing.gst_export_json(x) for x in rows], 50)


@fin.get("/gst-exports/{gst_export_id}")
async def fin_gst_export_status(
    gst_export_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("invoice.read")),
) -> dict[str, Any]:
    return billing.gst_export_json(await _own_export(session, principal, gst_export_id))


@fin.get("/gst-exports/{gst_export_id}/download")
async def fin_gst_export_download(
    gst_export_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("invoice.read")),
) -> dict[str, Any]:
    """Requester only; within 24 h of completion; signed URL valid 5 min; audited."""
    await _ensure_export_perm(principal, request)
    job = await _own_export(session, principal, gst_export_id)
    st = billing.gst_export_json(job)["status"]
    if st != "ready" or job.s3_key is None:
        raise ProblemError("invalid_state_transition", current_state=st, allowed=["ready"])
    await audit(session, principal, "export.download", "gst_export", job.id)
    return documents.signed(job.s3_key, billing.gst_filename(job))


# =========================================================================== mount

billing_approvals.register()

router = APIRouter()
for _r in (pub, r, acct, fin):
    router.include_router(_r)
