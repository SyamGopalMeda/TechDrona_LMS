"""Regression tests for the audit Phase B commerce/entitlements fixes
(docs/audit/fixes/commerce.md). Each test reproduces the audit finding named in its name."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from app.core.db import system_context
from app.core.time import utcnow
from app.modules.commerce import service as svc
from app.modules.commerce.gateway import FakePaymentProvider
from app.modules.commerce.models import Coupon, Invoice, Order, PaymentWebhookEvent, Refund
from app.modules.entitlements import service as ent
from app.modules.entitlements.models import Entitlement
from app.modules.rbac.models import ApprovalRequest
from tests.commerce.factory import (
    buy,
    deliver,
    make_buyer,
    make_product,
    pay_via_webhook,
    principal,
    rows,
)
from tests.commerce.test_coupons_refunds_subscriptions import finance


async def _paid(api, db, client, fake_gw, **kw: Any) -> tuple[Any, uuid.UUID, dict[str, Any]]:
    cat = await make_product(db, **kw)
    u = await make_buyer(db)
    a = api.as_(principal(u))
    o = await buy(a, cat)
    await pay_via_webhook(client, fake_gw, o)
    return a, u, o


async def _settle(client, fake_gw, gref_id: str, status: str = "processed") -> None:
    fake_gw.refund_settle(gref_id, status=status)
    raw, h = fake_gw.webhook(f"refund.{status}", {"refund": {"id": gref_id}})
    assert (await deliver(client, raw, h)).status_code == 200


async def test_com01_placement_refund_with_consumed_sessions_revokes_access(api, db, client, fake_gw) -> None:
    a, u, o = await _paid(
        api,
        db,
        client,
        fake_gw,
        kind="placement_package",
        amount_paise=1_000_000,
        items=[
            {"item_type": "feature", "feature_key": "all_courses"},
            {
                "item_type": "feature",
                "feature_key": "mentor_sessions",
                "quantity": 4,
                "unit_price_paise": 100_000,
            },
        ],
    )
    await system_context(db, "t")
    await ent.consume_quota(db, u, "mentor_sessions", ent.Actor.system("t"))
    rid = (await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)).json()["refund_id"]
    f = finance(api, await make_buyer(db))
    r = await f.post(f"/finance/refunds/{rid}/decision", {"decision": "approve"}, idem=True)
    assert r.status_code == 200 and r.json()["amount_paise"] == 900_000, r.text
    e = (await rows(db, Entitlement, Entitlement.user_id == u))[0]
    assert e.status == "revoked" and e.revoke_reason == "refund"
    gref = next(iter(fake_gw.refunds.values()))
    await _settle(client, fake_gw, gref.id)
    od = (await rows(db, Order, Order.id == uuid.UUID(o["order_id"])))[0]
    assert od.status == "partially_refunded" and od.refunded_paise == 900_000


async def test_com01_price_adjustment_keeps_access(api, db, client, fake_gw) -> None:
    _, u, o = await _paid(api, db, client, fake_gw)
    f = finance(api, await make_buyer(db))
    r = await f.post(
        "/finance/refunds",
        {
            "order_id": o["order_id"],
            "reason_code": "price_adjustment",
            "amount_paise": 50_000,
            "note": "promo",
        },
        idem=True,
    )
    assert r.status_code == 201, r.text
    assert (await rows(db, Entitlement, Entitlement.user_id == u))[0].status == "active"


async def test_com02_refund_submitted_during_outage_is_retried(api, db, client, fake_gw) -> None:
    a, _u, o = await _paid(api, db, client, fake_gw)
    rid = (await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)).json()["refund_id"]
    f = finance(api, await make_buyer(db))
    fake_gw.fail_ops = {"create_refund"}
    r = await f.post(f"/finance/refunds/{rid}/decision", {"decision": "approve"}, idem=True)
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    rf = (await rows(db, Refund, Refund.id == uuid.UUID(rid)))[0]
    assert rf.gateway_refund_id is None and rf.submit_attempts == 1 and rf.next_submit_at is not None
    fake_gw.fail_ops = set()
    await system_context(db, "t")
    assert (await svc.retry_refund_submissions(db, fake_gw, now=utcnow()))["checked"] == 0  # backoff
    out = await svc.retry_refund_submissions(db, fake_gw, now=rf.next_submit_at + timedelta(seconds=1))
    assert out == {"checked": 1, "submitted": 1, "deferred": 0}
    rf = (await rows(db, Refund, Refund.id == uuid.UUID(rid)))[0]
    assert rf.status == "processing" and rf.gateway_refund_id in fake_gw.refunds
    assert len(fake_gw.refunds) == 1


async def test_com02_resubmit_adopts_refund_the_provider_already_has(api, db, client, fake_gw) -> None:
    a, _, o = await _paid(api, db, client, fake_gw)
    rid = (await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)).json()["refund_id"]
    f = finance(api, await make_buyer(db))
    fake_gw.unavailable = True
    await f.post(f"/finance/refunds/{rid}/decision", {"decision": "approve"}, idem=True)
    fake_gw.unavailable = False
    # the provider did create it (response lost): the retry must not create a second one
    pay_id = next(iter(fake_gw.payments))
    await fake_gw.create_refund(pay_id, 349900, {"refund_id": rid})
    await system_context(db, "t")
    await svc.retry_refund_submissions(db, fake_gw, now=utcnow() + timedelta(hours=3))
    assert len(fake_gw.refunds) == 1
    assert (await rows(db, Refund, Refund.id == uuid.UUID(rid)))[0].status == "processing"


async def test_com03_provider_refund_failure_reinstates_access_without_credit_note(
    api, db, client, fake_gw
) -> None:
    a, u, o = await _paid(api, db, client, fake_gw)
    rid = (await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)).json()["refund_id"]
    f = finance(api, await make_buyer(db))
    await f.post(f"/finance/refunds/{rid}/decision", {"decision": "approve"}, idem=True)
    assert (await rows(db, Entitlement, Entitlement.user_id == u))[0].status == "revoked"
    gref = next(iter(fake_gw.refunds.values()))
    await _settle(client, fake_gw, gref.id, status="failed")
    rf = (await rows(db, Refund, Refund.id == uuid.UUID(rid)))[0]
    e = (await rows(db, Entitlement, Entitlement.user_id == u))[0]
    od = (await rows(db, Order, Order.id == uuid.UUID(o["order_id"])))[0]
    cn = await rows(db, Invoice, Invoice.order_id == od.id, Invoice.invoice_type == "credit_note")
    assert rf.status == "failed" and e.status == "active" and e.revoked_at is None
    assert od.status == "paid" and od.refunded_paise == 0 and cn == []
    # finance can raise a new refund afterwards
    r = await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)
    assert r.status_code == 201, r.text


async def test_com11_adm24_cumulative_refunds_cannot_exceed_paid(api, db, client, fake_gw) -> None:
    a, _, o = await _paid(api, db, client, fake_gw)
    f = finance(api, await make_buyer(db))
    r = await f.post(
        "/finance/refunds",
        {
            "order_id": o["order_id"],
            "reason_code": "price_adjustment",
            "amount_paise": 100_000,
            "note": "part",
        },
        idem=True,
    )
    assert r.status_code == 201, r.text
    await _settle(client, fake_gw, next(iter(fake_gw.refunds.values())).id)
    r = await f.post(
        "/finance/refunds",
        {"order_id": o["order_id"], "reason_code": "service_failure", "amount_paise": 349_900, "note": "all"},
        idem=True,
    )
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "exceeds_refundable", r.text
    # student request + finance override above what remains
    rid = (await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)).json()["refund_id"]
    rq = (await rows(db, Refund, Refund.id == uuid.UUID(rid)))[0]
    assert rq.amount_paise == 249_900
    r = await f.post(
        f"/finance/refunds/{rid}/decision", {"decision": "approve", "amount_paise": 349_900}, idem=True
    )
    assert r.status_code == 400, r.text
    # database backstop
    await system_context(db, "t")
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                update(Order).where(Order.id == uuid.UUID(o["order_id"])).values(refunded_paise=349_901)
            )


async def test_db07_money_checks(db) -> None:
    await system_context(db, "t")
    names = set(
        (
            await db.execute(
                text("SELECT conname FROM pg_constraint WHERE convalidated AND conname = ANY(:n)"),
                {
                    "n": [
                        "ck_oi_unit_nonneg",
                        "ck_oi_taxable_nonneg",
                        "ck_oi_discount_nonneg",
                        "ck_oi_total_nonneg",
                        "ck_oi_total",
                        "ck_pay_fee_nonneg",
                        "ck_pay_fee_tax_nonneg",
                        "ck_coupon_min_order_nonneg",
                        "ck_order_refunded",
                    ]
                },
            )
        ).scalars()
    )
    assert len(names) == 9, names


async def test_com05_subscription_dispute_suspends_then_revokes(api, db, client, fake_gw) -> None:
    cat = await make_product(
        db,
        kind="subscription_plan",
        amount_paise=49900,
        recurring=True,
        items=[{"item_type": "feature", "feature_key": "all_courses"}],
    )
    a = api.as_(principal(await make_buyer(db)))
    r = await a.post(
        "/commerce/subscriptions", {"price_id": str(cat.price.id), "billing": {"state_code": "29"}}, idem=True
    )
    assert r.status_code == 201, r.text
    sid, gsid = r.json()["subscription_id"], r.json()["checkout"]["subscription_id"]
    gp = fake_gw.subscription_charge(gsid, 49900)
    body = {
        "razorpay_payment_id": gp.id,
        "razorpay_subscription_id": gsid,
        "razorpay_signature": fake_gw.subscription_signature(gp.id, gsid),
    }
    assert (await a.post(f"/commerce/subscriptions/{sid}/confirm", body, idem=True)).status_code == 200
    so = (await rows(db, Order, Order.subscription_id == uuid.UUID(sid)))[0]
    inv = (await rows(db, Invoice, Invoice.order_id == so.id))[0]
    # COM-10: Karnataka buyer, Telangana seller -> IGST, place of supply 29
    assert inv.place_of_supply == "29" and inv.igst_paise > 0 and inv.cgst_paise == inv.sgst_paise == 0
    d = fake_gw.open_dispute(gp.id)
    raw, h = fake_gw.webhook("payment.dispute.created", {"dispute": {"id": d.id}})
    await deliver(client, raw, h)
    e = (await rows(db, Entitlement, Entitlement.subscription_id == uuid.UUID(sid)))[0]
    assert e.status == "suspended"
    d.status = "lost"
    raw, h = fake_gw.webhook("payment.dispute.lost", {"dispute": {"id": d.id}})
    await deliver(client, raw, h)
    e = (await rows(db, Entitlement, Entitlement.subscription_id == uuid.UUID(sid)))[0]
    assert e.status == "revoked" and e.revoke_reason == "chargeback"


async def test_inv15_recurring_price_cannot_be_bought_as_one_time_order(api, db, fake_gw) -> None:
    cat = await make_product(
        db,
        kind="subscription_plan",
        amount_paise=49900,
        recurring=True,
        items=[{"item_type": "feature", "feature_key": "all_courses"}],
    )
    a = api.as_(principal(await make_buyer(db)))
    r = await a.post(
        "/commerce/orders",
        {"price_id": str(cat.price.id), "billing": {"state_code": "36"}, "quote_total_paise": 49900},
        idem=True,
    )
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "not_one_time", r.text


async def test_fe26_fe27_pending_order_resumes_and_reload_does_not_duplicate(api, db, fake_gw) -> None:
    cat = await make_product(db)
    a = api.as_(principal(await make_buyer(db)))
    o1 = await buy(a, cat)
    o2 = await buy(a, cat)  # reload of /app/checkout/new: new Idempotency-Key, same cart
    assert o2["order_id"] == o1["order_id"] and o2["resumed"] is True
    assert o2["checkout"]["gateway_order_id"] == o1["checkout"]["gateway_order_id"]
    got = (await a.get(f"/commerce/orders/{o1['order_id']}")).json()
    assert got["checkout"]["gateway_order_id"] == o1["checkout"]["gateway_order_id"]
    assert len(fake_gw.orders) == 1


async def test_adm26_coupon_patch_to_unlimited_needs_dual(api, db, fake_gw) -> None:
    f = finance(api, await make_buyer(db))
    r = await f.post(
        "/finance/coupons",
        {
            "code": "SMALL10X",
            "discount_type": "percent",
            "percent_off": "10",
            "max_redemptions": 100,
            "valid_from": utcnow().isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    r = await f.patch(f"/finance/coupons/{r.json()['coupon_id']}", {"max_redemptions": None})
    assert r.status_code == 409 and r.json()["code"] == "second_approval_required", r.text


async def test_adm25_commerce_approval_visible_and_decidable_in_admin_queue(
    api, db, fake_gw, monkeypatch
) -> None:
    from app.modules.admin import approvals as apr

    async def _perm(session: Any, p: Any, key: str, scope: Any) -> bool:
        return key == "approval.decide" and p.has_role("super_admin", "platform")

    monkeypatch.setattr(apr.rs, "check_permission", _perm)
    f1 = finance(api, await make_buyer(db))
    r = await f1.post(
        "/finance/coupons",
        {
            "code": "BIG60X",
            "discount_type": "percent",
            "percent_off": "60",
            "max_redemptions": 10,
            "valid_from": utcnow().isoformat(),
        },
    )
    appr, cid = r.json()["approval_request_id"], r.json()["coupon_id"]
    f2 = finance(api, await make_buyer(db))
    ids = [x["approval_request_id"] for x in (await f2.get("/admin/approvals")).json()["data"]]
    assert appr in ids
    assert (await f1.post(f"/admin/approvals/{appr}/approve", {"note": "self"}, idem=True)).status_code == 403
    r = await f2.post(f"/admin/approvals/{appr}/approve", {"note": "ok"}, idem=True)
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert (await rows(db, Coupon, Coupon.id == uuid.UUID(cid)))[0].status == "active"


async def test_adm23_expired_commerce_approval_is_persisted(api, db, fake_gw) -> None:
    f1 = finance(api, await make_buyer(db))
    r = await f1.post(
        "/finance/coupons",
        {
            "code": "BIG70X",
            "discount_type": "percent",
            "percent_off": "70",
            "max_redemptions": 10,
            "valid_from": utcnow().isoformat(),
        },
    )
    appr = uuid.UUID(r.json()["approval_request_id"])
    await system_context(db, "t")
    await db.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == appr)
        .values(expires_at=utcnow() - timedelta(hours=1))
    )
    f2 = finance(api, await make_buyer(db))
    r = await f2.post(f"/finance/approval-requests/{appr}/approve", {"note": "late"})
    assert r.status_code == 409 and r.json()["current_state"] == "expired"
    assert (await rows(db, ApprovalRequest, ApprovalRequest.id == appr))[0].status == "expired"


async def test_e2e03_dev_fake_gateway_completes_refunds(api, db, client) -> None:
    from app.modules.commerce.gateway import set_gateway

    fake = FakePaymentProvider(auto_settle_refunds=True)
    set_gateway("razorpay", fake)
    try:
        a, _u, o = await _paid(api, db, client, fake)
        rid = (await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)).json()[
            "refund_id"
        ]
        f = finance(api, await make_buyer(db))
        r = await f.post(f"/finance/refunds/{rid}/decision", {"decision": "approve"}, idem=True)
        assert r.status_code == 200, r.text
        rf = (await rows(db, Refund, Refund.id == uuid.UUID(rid)))[0]
        od = (await rows(db, Order, Order.id == uuid.UUID(o["order_id"])))[0]
        assert rf.status == "processed" and od.status == "refunded"
        assert len(await rows(db, Invoice, Invoice.refund_id == rf.id)) == 1
    finally:
        set_gateway("razorpay", None)


async def test_e2e04_missing_monitoring_consent_has_accurate_error(api, db, fake_gw) -> None:
    cat = await make_product(db)
    a = api.as_(principal(await make_buyer(db, consent=False)))
    r = await a.post(
        "/commerce/orders",
        {"price_id": str(cat.price.id), "billing": {"state_code": "36"}, "quote_total_paise": 349900},
        idem=True,
    )
    body = r.json()
    assert r.status_code == 403 and body["code"] == "consent_required"
    assert "updated terms" not in body["title"] and body["purposes"] == ["security_monitoring"]
    assert body["grant"]["path"] == "/me/consents"


async def test_com13_webhook_retry_horizon_then_failed_alert(api, db, client, fake_gw) -> None:
    from app.modules.commerce import webhooks

    cat = await make_product(db)
    o = await buy(api.as_(principal(await make_buyer(db))), cat)
    gp = fake_gw.pay(o["checkout"]["gateway_order_id"])
    fake_gw.unavailable = True
    raw, h = fake_gw.webhook("payment.captured", {"payment": {"id": gp.id}})
    await deliver(client, raw, h)
    ev = (await rows(db, PaymentWebhookEvent, PaymentWebhookEvent.event_id == h["X-Razorpay-Event-Id"]))[0]
    for _ in range(10):  # well past the old 8-attempt limit, still within 72 h
        await webhooks.process_event(db, fake_gw, ev.id)
    ev = (await rows(db, PaymentWebhookEvent, PaymentWebhookEvent.id == ev.id))[0]
    assert ev.status == "received" and ev.attempts == 11
    await db.execute(
        update(PaymentWebhookEvent)
        .where(PaymentWebhookEvent.id == ev.id)
        .values(received_at=utcnow() - timedelta(hours=73))
    )
    assert await webhooks.process_event(db, fake_gw, ev.id) == "failed"
    n = (
        await db.execute(
            text("SELECT count(*) FROM outbox_events WHERE event_type = 'commerce.webhook_failed'")
        )
    ).scalar_one()
    assert n >= 1


async def test_com13_reconciliation_settles_processing_refunds(api, db, client, fake_gw) -> None:
    from app.modules.commerce import admin

    a, _, o = await _paid(api, db, client, fake_gw)
    rid = (await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)).json()["refund_id"]
    f = finance(api, await make_buyer(db))
    await f.post(f"/finance/refunds/{rid}/decision", {"decision": "approve"}, idem=True)
    fake_gw.refund_settle(next(iter(fake_gw.refunds.values())).id)  # webhook never arrives
    await system_context(db, "t")
    await db.execute(
        update(Refund).where(Refund.id == uuid.UUID(rid)).values(created_at=utcnow() - timedelta(hours=1))
    )
    now = utcnow()
    run = await admin.run_reconciliation(
        db, fake_gw, range_from=now - timedelta(days=1), range_to=now, triggered_by="test"
    )
    assert run.summary["refunds_settled"] == 1
    assert (await rows(db, Refund, Refund.id == uuid.UUID(rid)))[0].status == "processed"


async def test_com21_revoke_bumps_cache_version_after_commit(db, monkeypatch) -> None:
    from app.modules.entitlements import cache

    bumped: list[uuid.UUID] = []

    async def fake_bump(uid: uuid.UUID) -> None:
        bumped.append(uid)

    monkeypatch.setattr(cache, "bump", fake_bump)
    uid = uuid.uuid4()

    class FakeSync:
        info: dict[str, Any] = {}

    sync = FakeSync()
    # exercise the hook body directly (the listener is SQLAlchemy's job)
    sync.info[cache._PENDING_KEY] = {uid}
    cache._after_commit(sync)
    await cache.drain_pending_bumps()
    assert bumped == [uid]
