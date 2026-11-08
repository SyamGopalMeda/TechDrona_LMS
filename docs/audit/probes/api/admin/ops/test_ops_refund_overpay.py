"""OPS audit probe: a second refund on a partially refunded order can exceed what was paid."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.db import system_context
from app.modules.commerce.models import Invoice, Refund
from tests.commerce.factory import buy, deliver, make_buyer, make_product, pay_via_webhook, principal, rows
from tests.commerce.test_coupons_refunds_subscriptions import finance


async def test_second_refund_can_exceed_amount_paid(api, db, client, fake_gw) -> None:
    cat = await make_product(db)
    u = await make_buyer(db)
    a = api.as_(principal(u))
    o = await buy(a, cat)
    await pay_via_webhook(client, fake_gw, o)
    total = o["total_paise"]
    oid = o["order_id"]
    f = finance(api, await make_buyer(db))
    # refund 1: partial 100000
    rid1 = (await a.post("/me/refund-requests", {"order_id": oid, "note": "partial"}, idem=True)).json()["refund_id"]
    r = await f.post(f"/finance/refunds/{rid1}/decision", {"decision": "approve", "amount_paise": 100000, "note": "partial ok"}, idem=True)
    assert r.status_code == 200, r.text
    gref = next(iter(fake_gw.refunds.values()))
    fake_gw.refund_settle(gref.id)
    raw, h = fake_gw.webhook("refund.processed", {"refund": {"id": gref.id}})
    await deliver(client, raw, h)
    el = (await a.get(f"/me/orders/{oid}/refund-eligibility")).json()
    print("ELIG after first", el)
    # refund 2: request, then finance approves FULL order total
    r = await a.post("/me/refund-requests", {"order_id": oid, "note": "rest"}, idem=True)
    print("REQ2", r.status_code, r.json().get("amount_paise"))
    rid2 = r.json()["refund_id"]
    r = await f.post(f"/finance/refunds/{rid2}/decision", {"decision": "approve", "amount_paise": total, "note": "all"}, idem=True)
    print("DECIDE2", r.status_code, r.json().get("status"), r.json().get("amount_paise"))
    await system_context(db, "t")
    refunded = (await db.execute(select(func.sum(Refund.amount_paise)).where(Refund.order_id == uuid.UUID(oid), Refund.status.in_(("approved","processing","processed"))))).scalar_one()
    cn = (await db.execute(select(func.sum(Invoice.total_paise)).where(Invoice.order_id == uuid.UUID(oid), Invoice.invoice_type == "credit_note"))).scalar_one()
    print("ORDER_TOTAL", total, "REFUNDED_SUM", refunded, "CREDIT_NOTES_SUM", cn)
    assert refunded <= total, f"over-refund: {refunded} > {total}"
