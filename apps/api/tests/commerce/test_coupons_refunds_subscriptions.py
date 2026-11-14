"""Coupon abuse limits, refund rules (window, consumption, certificate, goodwill Dual),
subscriptions (mandate cap, activation, grace, restore, cancel), disputes, finance access."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import update

from app.core.db import system_context
from app.core.time import utcnow
from app.modules.commerce.models import Coupon, CouponRedemption, Invoice, Order, Refund, Subscription
from app.modules.entitlements import service as ent
from app.modules.entitlements.models import Entitlement, EntitlementEvent
from tests.commerce.factory import (
    buy,
    deliver,
    make_buyer,
    make_coupon,
    make_product,
    pay_via_webhook,
    principal,
    rows,
)

FIN = (
    "order.read",
    "payment.read",
    "refund.decide",
    "refund.goodwill",
    "approval.decide",
    "invoice.read",
    "reconciliation.run",
    "coupon.manage",
    "price.manage",
    "product.manage",
)


def finance(api, uid):
    return api.as_(principal(uid, roles=("super_admin",), platform=True), *FIN)


async def _quote(a, cat, code):
    r = await a.post("/commerce/checkout/quote", {"price_id": str(cat.price.id), "coupon_code": code})
    return r.json()


async def test_coupon_limits_and_abuse(api, db, fake_gw, client) -> None:
    cat = await make_product(db, amount_paise=100000)
    other = await make_product(db, amount_paise=100000)
    u1, u2, u3 = await make_buyer(db), await make_buyer(db), await make_buyer(db)
    await make_coupon(db, u1, code="CAP2", max_redemptions=2, per_user_limit=1)
    await make_coupon(
        db, u1, code="OLD", valid_until=utcnow() - timedelta(hours=1), valid_from=utcnow() - timedelta(days=9)
    )
    await make_coupon(db, u1, code="ONLYX", applicable_product_ids=[other.product.id])
    await make_coupon(db, u1, code="MIN5K", min_order_paise=500000)
    await make_coupon(db, u1, code="NEWBIE", first_time_only=True, per_user_limit=5)
    paused = await make_coupon(db, u1, code="PAUSED")
    await system_context(db, "t")
    await db.execute(update(Coupon).where(Coupon.id == paused.id).values(status="paused"))
    a1, a2, a3 = (api.as_(principal(u)) for u in (u1, u2, u3))
    assert (await _quote(a1, cat, "OLD"))["coupon"]["status"] == "expired"
    assert (await _quote(a1, cat, "ONLYX"))["coupon"]["status"] == "not_applicable"
    assert (await _quote(a1, cat, "MIN5K"))["coupon"]["status"] == "min_order_not_met"
    assert (await _quote(a1, cat, "PAUSED"))["coupon"]["status"] == "invalid"
    assert (await _quote(a1, cat, "NOPE"))["coupon"]["status"] == "invalid"
    r = await a1.post(
        "/commerce/orders",
        {"price_id": str(cat.price.id), "coupon_code": "OLD", "quote_total_paise": 100000},
        idem=True,
    )
    assert r.status_code == 422 and r.json()["code"] == "coupon_expired"
    # per-user limit: a pending reservation already counts
    o1 = await buy(a1, cat, coupon="CAP2")
    assert o1["total_paise"] == 75000
    assert (await _quote(a1, other, "CAP2"))["coupon"]["status"] == "cap_reached"
    # global cap: reservations count; releasing one (cancel) frees the slot
    await buy(a2, cat, coupon="CAP2")
    assert (await _quote(a3, cat, "CAP2"))["coupon"]["status"] == "cap_reached"
    await a1.post(f"/commerce/orders/{o1['order_id']}/cancel")
    assert (await _quote(a3, cat, "CAP2"))["coupon"]["status"] == "applicable"
    o3 = await buy(a3, cat, coupon="CAP2")
    await pay_via_webhook(client, fake_gw, o3)
    c = (await rows(db, Coupon, Coupon.code == "CAP2"))[0]
    assert c.redeemed_count == 1
    red = await rows(db, CouponRedemption, CouponRedemption.coupon_id == c.id)
    assert sorted(x.status for x in red) == ["consumed", "released", "reserved"]
    # new-users-only: u3 has a paid order now
    assert (await _quote(a3, other, "NEWBIE"))["coupon"]["status"] == "new_users_only"
    assert (await _quote(a2, other, "NEWBIE"))["coupon"]["status"] == "applicable"


async def test_free_access_coupon_grants_coupon_entitlement_without_gateway(api, db, fake_gw) -> None:
    cat = await make_product(db, amount_paise=50000)
    u = await make_buyer(db)
    await make_coupon(db, u, code="FREE100", discount_type="free_access", percent_off=None)
    o = await buy(api.as_(principal(u)), cat, coupon="FREE100")
    assert o["status"] == "paid" and o["total_paise"] == 0 and o["checkout"] is None
    assert o["entitlements"][0]["source_type"] == "coupon_grant"
    assert fake_gw.calls == []
    assert await rows(db, Invoice, Invoice.order_id == uuid.UUID(o["order_id"])) == []


class Usage:
    name = "test"

    def __init__(self, pct: str = "0", cert: bool = False) -> None:
        self.pct, self.cert = Decimal(pct), cert

    async def consumption_pct(self, s, u, p):
        return self.pct

    async def certificate_issued(self, s, u, p):
        return self.cert

    async def mocks_started(self, s, u, p):
        return 0


async def test_refund_within_rule_revokes_and_issues_credit_note(api, db, client, fake_gw) -> None:
    cat = await make_product(db)
    u = await make_buyer(db)
    a = api.as_(principal(u))
    o = await buy(a, cat)
    await pay_via_webhook(client, fake_gw, o)
    el = (await a.get(f"/me/orders/{o['order_id']}/refund-eligibility")).json()
    assert el["eligible"] is True and el["refundable_paise"] == 349900
    r = await a.post("/me/refund-requests", {"order_id": o["order_id"], "note": "wrong package"}, idem=True)
    assert r.status_code == 201, r.text
    rid = r.json()["refund_id"]
    assert (await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)).status_code == 409
    f = finance(api, (await make_buyer(db)))
    r = await f.post(f"/finance/refunds/{rid}/decision", {"decision": "approve"}, idem=True)
    assert r.status_code == 200 and r.json()["status"] == "processing", r.text
    e = (await rows(db, Entitlement, Entitlement.user_id == u))[0]
    assert e.status == "revoked" and e.revoke_reason == "refund"
    # COM-03: no GST credit note until the provider confirms the money moved
    cn_filter = (Invoice.order_id == uuid.UUID(o["order_id"]), Invoice.invoice_type == "credit_note")
    assert await rows(db, Invoice, *cn_filter) == []
    gref = next(iter(fake_gw.refunds.values()))
    # refund.processed arrives (before any refund.created): applied from the re-fetch
    fake_gw.refund_settle(gref.id)
    raw, h = fake_gw.webhook("refund.processed", {"refund": {"id": gref.id}})
    assert (await deliver(client, raw, h)).json()["status"] == "accepted"
    raw, h = fake_gw.webhook("refund.created", {"refund": {"id": gref.id}})
    await deliver(client, raw, h)
    rf = (await rows(db, Refund, Refund.id == uuid.UUID(rid)))[0]
    assert rf.status == "processed"
    assert (await rows(db, Order, Order.id == uuid.UUID(o["order_id"])))[0].status == "refunded"
    assert len(await rows(db, Invoice, Invoice.refund_id == rf.id)) == 1
    cn = await rows(db, Invoice, *cn_filter)
    assert len(cn) == 1 and cn[0].invoice_number.startswith("TDCN/") and cn[0].total_paise == 349900
    rep = (
        await f.get(
            "/finance/reports/revenue", params={"range_from": (utcnow() - timedelta(days=1)).isoformat()}
        )
    ).json()
    assert rep["orders_paid"] >= 1 and rep["refunded_paise"] >= 349900


async def test_refund_rules_outside_window_consumption_and_goodwill_dual(api, db, client, fake_gw) -> None:
    cat = await make_product(db)
    u = await make_buyer(db)
    a = api.as_(principal(u))
    o = await buy(a, cat)
    await pay_via_webhook(client, fake_gw, o)
    oid = uuid.UUID(o["order_id"])
    await system_context(db, "t")
    await db.execute(update(Order).where(Order.id == oid).values(paid_at=utcnow() - timedelta(days=8)))
    el = (await a.get(f"/me/orders/{oid}/refund-eligibility")).json()
    assert el["eligible"] is False and el["reasons"] == ["window_passed"]
    ent.register_usage_provider(Usage("25", cert=True))
    el = (await a.get(f"/me/orders/{oid}/refund-eligibility")).json()
    assert set(el["reasons"]) == {"window_passed", "consumption_exceeded", "certificate_issued"}
    r = await a.post("/me/refund-requests", {"order_id": str(oid), "reason_code": "content_issue"}, idem=True)
    assert r.status_code == 201 and r.json()["eligibility"]["eligible"] is False
    rid = r.json()["refund_id"]
    f1_id = await make_buyer(db)
    f1 = finance(api, f1_id)
    r = await f1.post(f"/finance/refunds/{rid}/decision", {"decision": "approve"}, idem=True)
    assert r.status_code == 409 and r.json()["code"] == "refund_not_eligible"
    assert "window_passed" in r.json()["reasons"]
    r = await f1.post(
        f"/finance/refunds/{rid}/decision", {"decision": "approve", "goodwill": True}, idem=True
    )
    assert r.status_code == 202 and r.json()["status"] == "approval_pending"
    appr = r.json()["approval_request_id"]
    # requester cannot approve their own goodwill request (SoD); a second finance admin can
    r = await f1.post(f"/finance/approval-requests/{appr}/approve", {})
    assert r.status_code == 403 and r.json()["code"] == "sod_violation"
    assert (await rows(db, Entitlement, Entitlement.user_id == u))[0].status == "active"
    f2 = finance(api, await make_buyer(db))
    r = await f2.post(f"/finance/approval-requests/{appr}/approve", {"note": "goodwill"})
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    rf = (await rows(db, Refund, Refund.id == uuid.UUID(rid)))[0]
    assert rf.reason_code == "goodwill" and rf.approval_request_id is not None and rf.status == "processing"
    assert (await rows(db, Entitlement, Entitlement.user_id == u))[0].status == "revoked"
    # a student cannot use finance routes
    r = await a.post(f"/finance/refunds/{rid}/decision", {"decision": "reject"}, idem=True)
    assert r.status_code == 403


async def test_subscription_lifecycle_grace_restore_cancel(api, db, client, fake_gw) -> None:
    cat = await make_product(
        db,
        kind="subscription_plan",
        amount_paise=49900,
        recurring=True,
        items=[{"item_type": "feature", "feature_key": "all_courses"}],
    )
    big = await make_product(db, kind="subscription_plan", amount_paise=1_500_100 - 100, recurring=True)
    u = await make_buyer(db)
    a = api.as_(principal(u))
    # mandate cap: CHECK forbids > ₹15,000 recurring prices; at the limit it is accepted
    r = await a.post("/commerce/subscriptions", {"price_id": str(big.price.id)}, idem=True)
    assert r.status_code == 201
    r = await a.post("/commerce/subscriptions", {"price_id": str(cat.price.id)}, idem=True)
    assert r.status_code == 201, r.text
    sid, gsid = r.json()["subscription_id"], r.json()["checkout"]["subscription_id"]
    gp = fake_gw.subscription_charge(gsid, 49900)
    body = {
        "razorpay_payment_id": gp.id,
        "razorpay_subscription_id": gsid,
        "razorpay_signature": fake_gw.subscription_signature(gp.id, gsid),
    }
    r = await a.post(f"/commerce/subscriptions/{sid}/confirm", body, idem=True)
    assert r.status_code == 200 and r.json()["status"] == "active", r.text
    e = (await rows(db, Entitlement, Entitlement.subscription_id == uuid.UUID(sid)))[0]
    assert e.source_type == "subscription" and e.status == "active"
    first_end = e.ends_at
    course = uuid.uuid4()
    chk = await a.post("/entitlements/check", {"resource": {"kind": "course", "id": str(course)}})
    assert chk.json()["allowed"] is True and chk.json()["source_type"] == "subscription"
    # debit fails -> pending -> grace (5 days, access retained)
    fake_gw.subscriptions[gsid].status = "pending"
    raw, h = fake_gw.webhook("subscription.pending", {"subscription": {"id": gsid}})
    await deliver(client, raw, h)
    e = (await rows(db, Entitlement, Entitlement.id == e.id))[0]
    assert e.status == "grace" and e.grace_ends_at - first_end == timedelta(days=5)
    # the grace check at a time after period end but inside grace
    pr = principal(u)
    ev = await ent.evaluate(db, pr, "course", course, at=first_end + timedelta(days=2))
    assert ev.decision.allowed and ev.decision.reason == "in_grace"
    ev = await ent.evaluate(db, pr, "course", course, at=first_end + timedelta(days=6))
    assert not ev.decision.allowed and ev.decision.reason == "expired"
    # retry succeeds: charged -> restored and extended; a replay of an older charge is ignored
    gp2 = fake_gw.subscription_charge(gsid, 49900)
    raw, h = fake_gw.webhook(
        "subscription.charged", {"subscription": {"id": gsid}, "payment": {"id": gp2.id}}
    )
    await deliver(client, raw, h)
    e = (await rows(db, Entitlement, Entitlement.id == e.id))[0]
    assert e.status == "active" and e.ends_at > first_end and e.grace_ends_at is None
    raw, h = fake_gw.webhook("subscription.charged", {"subscription": {"id": gsid}, "payment": {"id": gp.id}})
    await deliver(client, raw, h)
    assert (await rows(db, Entitlement, Entitlement.id == e.id))[0].ends_at == e.ends_at
    evts = [x.event_type for x in await rows(db, EntitlementEvent, EntitlementEvent.entitlement_id == e.id)]
    assert evts[:3] == ["granted", "entered_grace", "restored"]
    subs_orders = await rows(db, Order, Order.subscription_id == uuid.UUID(sid))
    assert len(subs_orders) == 2 and all(o.status == "paid" for o in subs_orders)
    # one-click cancel at period end (allowed from a restricted session)
    ra = api.as_(principal(u, scope="restricted", restriction_level=3))
    r = await ra.post(f"/me/subscriptions/{sid}/cancel", {"reason": "too_expensive"}, idem=True)
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is True
    s = (await rows(db, Subscription, Subscription.id == uuid.UUID(sid)))[0]
    assert s.cancel_at_period_end and s.cancel_reason == "too_expensive"
    assert (await rows(db, Entitlement, Entitlement.id == e.id))[0].status == "active"


async def test_dispute_suspends_then_restores(api, db, client, fake_gw) -> None:
    cat = await make_product(db)
    u = await make_buyer(db)
    a = api.as_(principal(u))
    o = await buy(a, cat)
    pay = await pay_via_webhook(client, fake_gw, o)
    d = fake_gw.open_dispute(pay)
    raw, h = fake_gw.webhook("payment.dispute.created", {"dispute": {"id": d.id}})
    await deliver(client, raw, h)
    chk = await a.post("/entitlements/check", {"resource": {"kind": "product", "id": str(cat.product.id)}})
    assert chk.json()["allowed"] is False and chk.json()["reason_code"] == "SUSPENDED_PAYMENT"
    d.status = "won"
    raw, h = fake_gw.webhook("payment.dispute.won", {"dispute": {"id": d.id}})
    await deliver(client, raw, h)
    chk = await a.post("/entitlements/check", {"resource": {"kind": "product", "id": str(cat.product.id)}})
    assert chk.json()["allowed"] is True


async def test_finance_catalogue_coupon_dual_and_reconciliation(api, db, client, fake_gw) -> None:
    f1 = finance(api, await make_buyer(db))
    r = await f1.post(
        "/finance/products",
        {
            "sku": "PP-TCS-T1",
            "name": "TCS pack",
            "product_kind": "placement_package",
            "status": "active",
            "items": [
                {
                    "item_type": "feature",
                    "feature_key": "mentor_sessions",
                    "quantity": 2,
                    "unit_price_paise": 50000,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    pid = r.json()["product_id"]
    r = await f1.post(
        f"/finance/products/{pid}/plans",
        {"code": "PP-TCS-T1-180", "billing_type": "one_time", "access_duration_days": 180},
    )
    plan = r.json()["plan_id"]
    r = await f1.post(f"/finance/plans/{plan}/prices", {"amount_paise": 349900}, idem=True)
    assert r.status_code == 201 and r.json()["status"] == "created", r.text
    r = await f1.post(f"/finance/plans/{plan}/prices", {"amount_paise": 199900}, idem=True)
    assert r.status_code == 202 and r.json()["status"] == "approval_pending"  # > 20 % decrease
    # recurring plan on a non-subscription product is refused; recurring > ₹15,000 too
    r = await f1.post(
        f"/finance/products/{pid}/plans",
        {"code": "BAD", "billing_type": "recurring", "interval_unit": "month", "interval_count": 1},
    )
    assert r.status_code == 400
    r = await f1.post(
        "/finance/coupons",
        {
            "code": "HALFOFF",
            "discount_type": "percent",
            "percent_off": "60",
            "max_redemptions": 10,
            "valid_from": utcnow().isoformat(),
        },
    )
    assert r.status_code == 202 and r.json()["status"] == "paused"
    appr = r.json()["approval_request_id"]
    f2 = finance(api, await make_buyer(db))
    r = await f2.post(f"/finance/approval-requests/{appr}/approve", {})
    assert r.status_code == 200 and r.json()["result"]["coupon"]["status"] == "active"
    # no step-up -> 401 step_up_required on P5 routes
    nostep = api.as_(
        principal(await make_buyer(db), roles=("super_admin",), platform=True, stepped_up=False), *FIN
    )
    r = await nostep.post(
        "/finance/coupons",
        {
            "code": "X1X",
            "discount_type": "flat",
            "amount_off_paise": 100,
            "max_redemptions": 5,
            "valid_from": utcnow().isoformat(),
        },
    )
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"
    # daily reconciliation recovers a missed capture of a stale pending order
    u = await make_buyer(db)
    cat = await make_product(db)
    o = await buy(api.as_(principal(u)), cat)
    fake_gw.pay(o["checkout"]["gateway_order_id"])
    await system_context(db, "t")
    await db.execute(
        update(Order)
        .where(Order.id == uuid.UUID(o["order_id"]))
        .values(created_at=utcnow() - timedelta(minutes=20))
    )
    r = await f1.post(
        "/finance/reconciliation/runs",
        {
            "range_from": (utcnow() - timedelta(days=1)).isoformat(),
            "range_to": (utcnow() + timedelta(minutes=1)).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["summary"]["recovered"] == 1
    assert (await rows(db, Order, Order.id == uuid.UUID(o["order_id"])))[0].status == "paid"
    assert (await f1.get("/finance/reconciliation")).json()["data"][0]["summary"]["recovered"] == 1
    assert (await f1.get(f"/finance/orders/{o['order_id']}")).json()["payments"][0]["status"] == "captured"


async def test_demo_seed_is_idempotent_and_labelled(api, db, client) -> None:
    from app.seeds.commerce_demo import seed

    await make_buyer(db)
    first = await seed(db)
    assert first == {"products": 4, "coupons": 2}
    assert await seed(db) == {"products": 0, "coupons": 0}
    listed = (await client.get("/api/v1/commerce/products")).json()["data"]
    demo = [p["sku"] for p in listed if p["sku"].startswith("DEMO-")]
    assert "DEMO-COLLEGE-SEAT" not in demo and len(demo) == 4


async def test_revenue_report_refuses_inverted_range_and_reports_gateway(api, db) -> None:
    """Admin audit 2026-11-11: an inverted range was answered with zeros; the gateway state is
    exposed so the finance screens can say "not integrated yet" for the fake adapter."""
    f = finance(api, await make_buyer(db))
    now = utcnow()
    bad = await f.get(
        "/finance/reports/revenue",
        params={"range_from": now.isoformat(), "range_to": (now - timedelta(days=3)).isoformat()},
    )
    assert bad.status_code == 400 and bad.json()["errors"][0]["field"] == "range_to", bad.text
    naive = await f.get("/finance/reports/revenue", params={"range_from": "2026-01-01T00:00:00"})
    assert naive.status_code == 200, naive.text
    ok = await f.get("/finance/reports/revenue")
    assert ok.status_code == 200 and set(ok.json()["gateway"]) == {"provider", "integrated"}
    recon = await f.get("/finance/reconciliation")
    assert recon.status_code == 200 and "gateway" in recon.json()
