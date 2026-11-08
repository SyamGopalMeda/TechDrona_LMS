"""Checkout, GST quotes, checkout callback, Razorpay webhooks (SCN-14 idempotency, invalid
signature, out-of-order / stale events, re-fetch failure), buyer gates, restricted
principals."""

from __future__ import annotations

import time

from sqlalchemy import text

from app.core.db import system_context
from app.modules.commerce import webhooks
from app.modules.commerce.models import Invoice, Order, Payment, PaymentWebhookEvent
from app.modules.entitlements.models import Entitlement
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


async def test_public_catalogue_shows_active_products_with_gst(api, db, client) -> None:
    cat = await make_product(db, amount_paise=118000)
    r = await client.get(f"/api/v1/commerce/products/{cat.product.sku}")
    assert r.status_code == 200, r.text
    body = r.json()
    price = body["plans"][0]["prices"][0]
    assert price["amount_paise"] == 118000
    assert price["gst_breakup_intra_state"] == {
        "taxable_paise": 100000,
        "cgst_paise": 9000,
        "sgst_paise": 9000,
    }
    assert body["unlocks"][0]["item_type"] == "course"
    assert "7 days" in body["refund_rule"]
    assert (await client.get("/api/v1/commerce/products/NOPE-SKU")).status_code == 404


async def test_quote_matches_spec_example_and_igst(api, db) -> None:
    cat = await make_product(db, amount_paise=349900)
    buyer = await make_buyer(db)
    coupon = await make_coupon(db, buyer, code="NQT25X")
    a = api.as_(principal(buyer))
    r = await a.post(
        "/commerce/checkout/quote",
        {"price_id": str(cat.price.id), "coupon_code": "NQT25X", "billing": {"state_code": "36"}},
    )
    q = r.json()
    assert (q["list_amount_paise"], q["discount_paise"], q["taxable_paise"]) == (349900, 87475, 222394)
    assert (q["cgst_paise"], q["sgst_paise"], q["igst_paise"], q["total_paise"]) == (20015, 20016, 0, 262425)
    assert q["coupon"]["status"] == "applicable" and coupon.code == "NQT25X"
    r = await a.post(
        "/commerce/checkout/quote", {"price_id": str(cat.price.id), "billing": {"state_code": "29"}}
    )
    q = r.json()
    assert q["igst_paise"] == 349900 - q["taxable_paise"] and q["cgst_paise"] == 0
    r = await a.post("/commerce/checkout/quote", {"price_id": str(cat.price.id), "unexpected": 1})
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"


async def test_scn14_same_webhook_delivered_repeatedly_is_processed_once(api, db, client, fake_gw) -> None:
    cat = await make_product(db)
    buyer = await make_buyer(db)
    a = api.as_(principal(buyer))
    order = await buy(a, cat)
    assert order["status"] == "pending_payment" and order["checkout"]["key_id"] == fake_gw.KEY_ID
    gp = fake_gw.pay(order["checkout"]["gateway_order_id"])
    raw, h = fake_gw.webhook("payment.captured", {"payment": {"id": gp.id, "order_id": gp.order_id}})
    statuses = [(await deliver(client, raw, h)).json()["status"] for _ in range(3)]
    assert statuses == ["accepted", "duplicate", "duplicate"]
    # a different event for the same payment (order.paid) changes nothing either
    raw2, h2 = fake_gw.webhook("order.paid", {"payment": {"id": gp.id}, "order": {"id": gp.order_id}})
    assert (await deliver(client, raw2, h2)).json()["status"] == "accepted"
    import uuid

    oid = uuid.UUID(order["order_id"])
    assert len(await rows(db, Payment, Payment.order_id == oid)) == 1
    ents = await rows(db, Entitlement, Entitlement.user_id == buyer)
    assert len(ents) == 1 and ents[0].source_type == "purchase" and ents[0].status == "active"
    invoices = await rows(db, Invoice, Invoice.order_id == oid)
    assert len(invoices) == 1 and invoices[0].invoice_number.startswith("TD/")
    assert len(invoices[0].invoice_number) <= 16
    o = (await rows(db, Order, Order.id == oid))[0]
    assert o.status == "paid" and o.paid_at is not None
    r = await a.get(f"/commerce/orders/{oid}")
    assert r.json()["status"] == "paid" and len(r.json()["entitlements"]) == 1


async def test_invalid_signature_is_400_and_logged(api, db, client, fake_gw) -> None:
    raw, h = fake_gw.webhook("payment.captured", {"payment": {"id": "pay_x"}}, secret="wrong-secret")
    r = await deliver(client, raw, h)
    assert r.status_code == 400 and r.json()["code"] == "webhook_signature_invalid"
    await system_context(db, "test.inspect")
    n = (
        await db.execute(
            text("SELECT count(*) FROM outbox_events WHERE event_type = 'commerce.webhook_signature_invalid'")
        )
    ).scalar_one()
    assert n >= 1
    assert await rows(db, PaymentWebhookEvent, PaymentWebhookEvent.event_id == h["X-Razorpay-Event-Id"]) == []
    # missing signature header, malformed JSON with a valid signature
    r = await client.post(
        "/api/v1/webhooks/razorpay", content=raw, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 400
    from app.modules.commerce.gateway import hmac_hex

    bad = b"{not json"
    r = await client.post(
        "/api/v1/webhooks/razorpay",
        content=bad,
        headers={"X-Razorpay-Signature": hmac_hex(fake_gw.WEBHOOK_SECRET, bad)},
    )
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
    assert (await client.post("/api/v1/webhooks/stripe", content=b"{}")).status_code == 404


async def test_out_of_order_and_stale_events_apply_refetched_state(api, db, client, fake_gw) -> None:
    cat = await make_product(db)
    buyer = await make_buyer(db)
    a = api.as_(principal(buyer))
    order = await buy(a, cat)
    pay_id = await pay_via_webhook(client, fake_gw, order)
    # a late, stale "payment.failed" for the captured payment: accepted (no age rejection),
    # flagged stale, and ignored by the forward-only state machine
    raw, h = fake_gw.webhook(
        "payment.failed", {"payment": {"id": pay_id, "status": "failed"}}, created_at=int(time.time()) - 86400
    )
    r = await deliver(client, raw, h)
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    ev = (await rows(db, PaymentWebhookEvent, PaymentWebhookEvent.event_id == h["X-Razorpay-Event-Id"]))[0]
    assert ev.is_stale and ev.status == "processed" and ev.refetch_status == "ok"
    p = (await rows(db, Payment, Payment.gateway_payment_id == pay_id))[0]
    assert p.status == "captured"
    # a payload claiming "captured" for an unpaid order is not trusted: the re-fetch says failed
    order2 = await buy(a, await make_product(db))
    gp2 = fake_gw.pay(order2["checkout"]["gateway_order_id"], status="failed")
    raw, h = fake_gw.webhook("payment.captured", {"payment": {"id": gp2.id, "status": "captured"}})
    assert (await deliver(client, raw, h)).json()["status"] == "accepted"
    import uuid

    o2 = (await rows(db, Order, Order.id == uuid.UUID(order2["order_id"])))[0]
    assert o2.status == "pending_payment"
    assert (await rows(db, Payment, Payment.gateway_payment_id == gp2.id))[0].status == "failed"
    # unknown event types are stored as ignored and acknowledged
    raw, h = fake_gw.webhook("invoice.paid", {"invoice": {"id": "inv_1"}})
    assert (await deliver(client, raw, h)).json()["status"] == "ignored"


async def test_refetch_failure_makes_no_state_change_and_is_retried(api, db, client, fake_gw) -> None:
    import uuid

    cat = await make_product(db)
    buyer = await make_buyer(db)
    order = await buy(api.as_(principal(buyer)), cat)
    gp = fake_gw.pay(order["checkout"]["gateway_order_id"])
    fake_gw.unavailable = True
    raw, h = fake_gw.webhook("payment.captured", {"payment": {"id": gp.id}})
    assert (await deliver(client, raw, h)).json()["status"] == "accepted"
    ev = (await rows(db, PaymentWebhookEvent, PaymentWebhookEvent.event_id == h["X-Razorpay-Event-Id"]))[0]
    assert ev.refetch_status == "failed" and ev.status == "received" and ev.attempts == 1
    # COM-13: exponential backoff, not an immediate re-drive
    assert ev.next_attempt_at is not None and ev.next_attempt_at > ev.received_at
    assert (await rows(db, Order, Order.id == uuid.UUID(order["order_id"])))[0].status == "pending_payment"
    assert await rows(db, Entitlement, Entitlement.user_id == buyer) == []
    fake_gw.unavailable = False
    assert await webhooks.process_pending_events(db, fake_gw, now=ev.received_at) == 0  # not due yet
    await webhooks.process_pending_events(db, fake_gw, now=ev.next_attempt_at)
    assert (await rows(db, Order, Order.id == uuid.UUID(order["order_id"])))[0].status == "paid"
    assert len(await rows(db, Entitlement, Entitlement.user_id == buyer)) == 1


async def test_checkout_callback_signature_and_convergence_with_webhook(api, db, client, fake_gw) -> None:
    cat = await make_product(db)
    buyer = await make_buyer(db)
    a = api.as_(principal(buyer))
    order = await buy(a, cat)
    goid = order["checkout"]["gateway_order_id"]
    gp = fake_gw.pay(goid)
    path = f"/commerce/orders/{order['order_id']}/confirm"
    body = {"razorpay_order_id": goid, "razorpay_payment_id": gp.id, "razorpay_signature": "00" * 32}
    r = await a.post(path, body, idem=True)
    assert r.status_code == 400 and r.json()["code"] == "payment_signature_invalid"
    await system_context(db, "test.inspect")
    n = (
        await db.execute(
            text("SELECT count(*) FROM outbox_events WHERE event_type = 'abuse.checkout_signature_invalid'")
        )
    ).scalar_one()
    assert n == 1
    assert (
        await a.post(path, {**body, "razorpay_signature": fake_gw.checkout_signature(goid, gp.id)})
    ).status_code == 400
    body["razorpay_signature"] = fake_gw.checkout_signature(goid, gp.id)
    r = await a.post(path, body, idem="confirm-key-1")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "paid" and len(out["entitlements"]) == 1 and out["invoice"]["invoice_number"]
    # replay of the same request, then the webhook for the same payment: still one grant
    assert (await a.post(path, body, idem="confirm-key-1")).headers.get("Idempotency-Replayed") == "true"
    raw, h = fake_gw.webhook("payment.captured", {"payment": {"id": gp.id}})
    await deliver(client, raw, h)
    assert len(await rows(db, Entitlement, Entitlement.user_id == buyer)) == 1
    # another user cannot see or confirm this order
    other = api.as_(principal(await make_buyer(db)))
    assert (await other.get(f"/commerce/orders/{order['order_id']}")).status_code == 404


async def test_order_rules_quote_mismatch_already_owned_and_gates(api, db, client, fake_gw) -> None:
    cat = await make_product(db)
    buyer = await make_buyer(db)
    a = api.as_(principal(buyer))
    r = await a.post("/commerce/orders", {"price_id": str(cat.price.id), "quote_total_paise": 1}, idem=True)
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "quote_mismatch"
    r = await a.post("/commerce/orders", {"price_id": str(cat.price.id), "quote_total_paise": 349900})
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    await pay_via_webhook(client, fake_gw, await buy(a, cat))
    q = (await a.post("/commerce/checkout/quote", {"price_id": str(cat.price.id)})).json()
    assert q["blocking"][0]["code"] == "already_owned"
    r = await a.post(
        "/commerce/orders", {"price_id": str(cat.price.id), "quote_total_paise": q["total_paise"]}, idem=True
    )
    assert r.status_code == 409 and r.json()["code"] == "already_owned"
    # adult without security_monitoring consent; minor without guardian consent
    no_consent = api.as_(principal(await make_buyer(db, consent=False)))
    r = await no_consent.post(
        "/commerce/orders", {"price_id": str(cat.price.id), "quote_total_paise": 349900}, idem=True
    )
    assert r.status_code == 403 and r.json()["code"] == "consent_required"
    minor = api.as_(principal(await make_buyer(db, minor=True), is_minor=True))
    r = await minor.post(
        "/commerce/orders", {"price_id": str(cat.price.id), "quote_total_paise": 349900}, idem=True
    )
    assert r.status_code == 403 and r.json()["code"] == "minor_consent_pending"
    # provider down: no order is created
    fake_gw.unavailable = True
    other = await make_buyer(db)
    b = api.as_(principal(other))
    r = await b.post(
        "/commerce/orders", {"price_id": str(cat.price.id), "quote_total_paise": 349900}, idem=True
    )
    assert r.status_code == 503
    assert await rows(db, Order, Order.user_id == other) == []


async def test_restricted_principal_denied_but_billing_allowed(api, db) -> None:
    cat = await make_product(db)
    buyer = await make_buyer(db)
    a = api.as_(principal(buyer, scope="restricted", restriction_level=3))
    r = await a.post(
        "/commerce/orders", {"price_id": str(cat.price.id), "quote_total_paise": 349900}, idem=True
    )
    assert r.status_code == 403 and r.json()["code"] == "account_restricted"
    r = await a.post("/entitlements/check", {"resource": {"kind": "product", "id": str(cat.product.id)}})
    assert r.status_code == 403
    assert (await a.get("/me/subscriptions")).status_code == 200
    assert (await a.get("/me/entitlements")).json()["restriction_gate"]["active"] is True


async def test_cancel_unpaid_order_and_expiry_job(api, db, fake_gw) -> None:
    import uuid
    from datetime import timedelta

    from app.core.time import utcnow
    from app.modules.commerce import service as svc

    cat = await make_product(db)
    buyer = await make_buyer(db)
    a = api.as_(principal(buyer))
    order = await buy(a, cat)
    r = await a.post(f"/commerce/orders/{order['order_id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert (await a.post(f"/commerce/orders/{order['order_id']}/cancel")).status_code == 409
    # expiry: a pending order with a captured payment is recovered, not expired
    o2 = await buy(a, await make_product(db))
    o3 = await buy(a, await make_product(db))
    fake_gw.pay(o2["checkout"]["gateway_order_id"])
    await system_context(db, "test.job")
    out = await svc.expire_orders(db, fake_gw, now=utcnow() + timedelta(hours=1))
    assert out == {"expired": 1, "recovered": 1}
    st = {o.id: o.status for o in await rows(db, Order, Order.user_id == buyer)}
    assert st[uuid.UUID(o2["order_id"])] == "paid" and st[uuid.UUID(o3["order_id"])] == "expired"


def test_fake_payment_provider_refused_in_production() -> None:
    import app.modules.commerce.gateway  # noqa: F401  (registers the check)
    from app.core.config import Settings
    from app.core.startup_checks import production_problems

    s = Settings(APP_ENV="prod", PAYMENTS_PRIMARY_PROVIDER="fake")
    assert any("FakePaymentProvider" in p for p in production_problems(s))


async def test_fake_gateway_test_payment_completes_checkout_on_any_worker(api, db, fake_gw) -> None:
    """B2: the fake gateway's order response carries ``checkout.test_payment`` (the web test-mode
    "Simulate a successful payment"); COM-06 confirm with it fulfils the order even when served
    by another api worker whose in-memory fake never saw the order."""
    from app.modules.commerce.gateway import FakePaymentProvider, set_gateway

    cat = await make_product(db)
    buyer = await make_buyer(db)
    a = api.as_(principal(buyer))
    order = await buy(a, cat)
    c = order["checkout"]
    tp = c["test_payment"]
    assert set(tp) == {"payment_id", "signature"}
    assert fake_gw.verify_checkout_signature(c["gateway_order_id"], tp["payment_id"], tp["signature"])
    # nothing is captured until the learner chooses "success" (reconciliation sees no payment)
    assert await fake_gw.fetch_order_payments(c["gateway_order_id"]) == []

    set_gateway("razorpay", FakePaymentProvider())  # a different worker's (empty) fake
    path = f"/commerce/orders/{order['order_id']}/confirm"
    body = {
        "razorpay_order_id": c["gateway_order_id"],
        "razorpay_payment_id": tp["payment_id"],
        "razorpay_signature": tp["signature"],
    }
    # a tampered amount in the id breaks the signature
    forged = {**body, "razorpay_payment_id": tp["payment_id"].replace("_FAKESIM_", "_FAKESIM_1")}
    assert (await a.post(path, forged, idem=True)).json()["code"] == "payment_signature_invalid"
    r = await a.post(path, body, idem=True)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "paid" and len(out["entitlements"]) == 1
    assert (await rows(db, Payment, Payment.gateway_payment_id == tp["payment_id"]))[0].amount_paise == c[
        "amount"
    ]


def test_real_gateway_never_returns_test_payment() -> None:
    from app.modules.commerce.gateway import RazorpayGateway

    assert not hasattr(RazorpayGateway, "test_checkout_payment")
