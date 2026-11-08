"""COM audit probes: refunds, disputes, subscription invoices, seats, contract termination.

Each test asserts the CURRENT (observed) behaviour and prints evidence; a passing test here
documents a finding, it does not endorse the behaviour."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.core.db import system_context, tenant_context
from app.core.time import utcnow
from app.modules.commerce.models import Invoice, Order, Refund
from app.modules.commerce.pricing import split_inclusive
from app.modules.commerce.service import fiscal_year
from app.modules.entitlements import service as ent
from app.modules.entitlements.models import Entitlement
from app.modules.orgs.models import OrgMembership
from tests.commerce.factory import (
    add_member,
    buy,
    deliver,
    make_buyer,
    make_contract,
    make_org,
    make_product,
    pay_via_webhook,
    principal,
    rows,
)
from tests.commerce.test_coupons_refunds_subscriptions import finance
from tests.entitlements.test_access_and_seats import _coordinator


def test_gst_split_cgst_sgst_unequal_and_fy() -> None:
    line = split_inclusive(262425, Decimal("18"), intra_state=True)
    print("split 262425 ->", line)
    assert line.cgst_paise != line.sgst_paise  # 20015 vs 20016
    assert line.total_paise == 262425
    assert fiscal_year(date(2027, 3, 31)) == "2026-27" and fiscal_year(date(2027, 4, 1)) == "2027-28"


async def test_placement_package_partial_refund_keeps_entitlement(api, db, client, fake_gw) -> None:
    cat = await make_product(
        db,
        kind="placement_package",
        amount_paise=1_000_000,
        items=[
            {"item_type": "feature", "feature_key": "all_courses"},
            {"item_type": "feature", "feature_key": "mentor_sessions", "quantity": 4, "unit_price_paise": 100_000},
        ],
    )
    u = await make_buyer(db)
    a = api.as_(principal(u))
    o = await buy(a, cat)
    await pay_via_webhook(client, fake_gw, o)
    await system_context(db, "t")
    await ent.consume_quota(db, u, "mentor_sessions", ent.Actor.system("t"))
    el = (await a.get(f"/me/orders/{o['order_id']}/refund-eligibility")).json()
    print("eligibility", el)
    r = await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)
    assert r.status_code == 201, r.text
    rid = r.json()["refund_id"]
    f = finance(api, await make_buyer(db))
    r = await f.post(f"/finance/refunds/{rid}/decision", {"decision": "approve"}, idem=True)
    print("decision", r.status_code, r.json().get("status"), r.json().get("amount_paise"))
    gref = next(iter(fake_gw.refunds.values()))
    fake_gw.refund_settle(gref.id)
    raw, h = fake_gw.webhook("refund.processed", {"refund": {"id": gref.id}})
    await deliver(client, raw, h)
    e = (await rows(db, Entitlement, Entitlement.user_id == u))[0]
    od = (await rows(db, Order, Order.id == uuid.UUID(o["order_id"])))[0]
    print("after refund: order", od.status, "entitlement", e.status, "mentor_left", e.mentor_sessions_remaining)
    assert gref.amount_paise == 900_000
    assert od.status == "partially_refunded"
    assert e.status == "active"  # FINDING: 90 % refunded yet access + 3 mentor sessions retained


async def test_gateway_refund_failure_leaves_access_revoked(api, db, client, fake_gw) -> None:
    cat = await make_product(db)
    u = await make_buyer(db)
    a = api.as_(principal(u))
    o = await buy(a, cat)
    await pay_via_webhook(client, fake_gw, o)
    rid = (await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)).json()["refund_id"]
    f = finance(api, await make_buyer(db))
    await f.post(f"/finance/refunds/{rid}/decision", {"decision": "approve"}, idem=True)
    gref = next(iter(fake_gw.refunds.values()))
    fake_gw.refund_settle(gref.id, status="failed")
    raw, h = fake_gw.webhook("refund.failed", {"refund": {"id": gref.id}})
    await deliver(client, raw, h)
    rf = (await rows(db, Refund, Refund.id == uuid.UUID(rid)))[0]
    e = (await rows(db, Entitlement, Entitlement.user_id == u))[0]
    od = (await rows(db, Order, Order.id == uuid.UUID(o["order_id"])))[0]
    cn = await rows(db, Invoice, Invoice.order_id == od.id, Invoice.invoice_type == "credit_note")
    print("refund", rf.status, "entitlement", e.status, "order", od.status, "credit_notes", len(cn))
    assert rf.status == "failed" and e.status == "revoked" and od.status == "paid" and len(cn) == 1


async def test_second_refund_can_exceed_order_total(api, db, client, fake_gw) -> None:
    cat = await make_product(db, amount_paise=100_000)
    u = await make_buyer(db)
    o = await buy(api.as_(principal(u)), cat)
    await pay_via_webhook(client, fake_gw, o)
    f = finance(api, await make_buyer(db))
    r1 = await f.post(
        "/finance/refunds",
        {"order_id": o["order_id"], "reason_code": "service_failure", "amount_paise": 60_000, "note": "audit probe"},
        idem=True,
    )
    print("r1", r1.status_code, r1.text[:200])
    g1 = next(iter(fake_gw.refunds.values()))
    fake_gw.refund_settle(g1.id)
    raw, h = fake_gw.webhook("refund.processed", {"refund": {"id": g1.id}})
    await deliver(client, raw, h)
    r2 = await f.post(
        "/finance/refunds",
        {"order_id": o["order_id"], "reason_code": "service_failure", "amount_paise": 100_000, "note": "audit probe"},
        idem=True,
    )
    print("r2", r2.status_code, r2.text[:300])
    total = sum(x.amount_paise for x in await rows(db, Refund, Refund.order_id == uuid.UUID(o["order_id"])))
    print("refund rows total", total)
    assert r2.status_code == 201 and total == 160_000


async def test_subscription_charge_dispute_and_interstate_invoice(api, db, client, fake_gw) -> None:
    cat = await make_product(
        db,
        kind="subscription_plan",
        amount_paise=49900,
        recurring=True,
        items=[{"item_type": "feature", "feature_key": "all_courses"}],
    )
    u = await make_buyer(db)
    a = api.as_(principal(u))
    r = await a.post("/commerce/subscriptions", {"price_id": str(cat.price.id)}, idem=True)
    sid, gsid = r.json()["subscription_id"], r.json()["checkout"]["subscription_id"]
    gp = fake_gw.subscription_charge(gsid, 49900)
    body = {
        "razorpay_payment_id": gp.id,
        "razorpay_subscription_id": gsid,
        "razorpay_signature": fake_gw.subscription_signature(gp.id, gsid),
    }
    r = await a.post(f"/commerce/subscriptions/{sid}/confirm", body, idem=True)
    assert r.status_code == 200, r.text
    so = (await rows(db, Order, Order.subscription_id == uuid.UUID(sid)))[0]
    inv = (await rows(db, Invoice, Invoice.order_id == so.id))[0]
    print("sub invoice", inv.place_of_supply, inv.cgst_paise, inv.sgst_paise, inv.igst_paise)
    assert inv.igst_paise == 0  # always intra-state; no billing state captured for subscriptions
    d = fake_gw.open_dispute(gp.id)
    raw, h = fake_gw.webhook("payment.dispute.created", {"dispute": {"id": d.id}})
    print("dispute webhook", (await deliver(client, raw, h)).json())
    e = (await rows(db, Entitlement, Entitlement.subscription_id == uuid.UUID(sid)))[0]
    print("subscription entitlement after dispute open:", e.status)
    assert e.status == "active"  # FINDING: dispute on a mandate debit never suspends access
    d.status = "lost"
    raw, h = fake_gw.webhook("payment.dispute.lost", {"dispute": {"id": d.id}})
    await deliver(client, raw, h)
    e = (await rows(db, Entitlement, Entitlement.subscription_id == uuid.UUID(sid)))[0]
    print("subscription entitlement after chargeback lost:", e.status)
    assert e.status == "active"


async def test_member_removal_keeps_seat_and_blocks_waitlist(api, db) -> None:
    org = await make_org(db)
    coord, cid = await _coordinator(api, db, org)
    s1, s2 = await make_buyer(db), await make_buyer(db)
    for s in (s1, s2):
        await add_member(db, org, s)
    cat = await make_product(
        db, kind="institution_seat", items=[{"item_type": "feature", "feature_key": "all_courses"}]
    )
    c = await make_contract(db, org, cat.product, cid, seats=1, allowance=1)
    r = await coord.post(
        f"/orgs/{org}/seats/assignments",
        {"contract_id": str(c.id), "user_ids": [str(s1), str(s2)], "waitlist_when_full": True},
        idem=True,
    )
    assert r.json()["assigned"] == 1 and r.json()["waitlisted"] == 1
    # remove s1 from the org exactly as DELETE /orgs/{org}/members/{user} does (status=removed)
    from sqlalchemy import update

    await system_context(db, "t")
    await db.execute(
        update(OrgMembership)
        .where(OrgMembership.organization_id == org, OrgMembership.user_id == s1)
        .values(status="removed", left_at=utcnow())
    )
    seats = (await coord.get(f"/orgs/{org}/seats")).json()["data"][0]
    e1 = (await rows(db, Entitlement, Entitlement.user_id == s1))[0]
    print("pool after removal", seats["pool"], "removed student's seat entitlement:", e1.status)
    assert seats["pool"]["used"] == 1 and seats["pool"]["waitlisted"] == 1 and e1.status == "active"


async def test_contract_termination_can_extend_access(api, db) -> None:
    org = await make_org(db)
    s1 = await make_buyer(db)
    await add_member(db, org, s1)
    cat = await make_product(
        db, kind="institution_seat", items=[{"item_type": "feature", "feature_key": "all_courses"}]
    )
    c = await make_contract(db, org, cat.product, s1, seats=2, ends_on=date.today() + timedelta(days=2))
    await system_context(db, "t")
    actor = ent.Actor.system("t")
    await ent.assign_seats(
        db, actor, org_id=org, contract_id=c.id, user_ids=[s1], waitlist_when_full=False
    )
    e = (await rows(db, Entitlement, Entitlement.user_id == s1))[0]
    before = e.ends_at
    await system_context(db, "t")
    await ent.terminate_contract_entitlements(db, c, actor, at=utcnow())
    e = (await rows(db, Entitlement, Entitlement.user_id == s1))[0]
    print("ends_at before termination", before, "after", e.ends_at)
    assert e.ends_at > before  # FINDING: termination pushed the end date later


async def test_late_payment_on_cancelled_order_is_fulfilled(api, db, client, fake_gw) -> None:
    cat = await make_product(db)
    u = await make_buyer(db)
    a = api.as_(principal(u))
    o = await buy(a, cat)
    await a.post(f"/commerce/orders/{o['order_id']}/cancel")
    await pay_via_webhook(client, fake_gw, o)
    od = (await rows(db, Order, Order.id == uuid.UUID(o["order_id"])))[0]
    print("cancelled order after late capture:", od.status)
    assert od.status == "paid"
    await tenant_context(db, principal(u))


async def test_refund_submit_outage_is_never_retried(api, db, client, fake_gw) -> None:
    from app.modules.commerce import tasks as ctasks

    cat = await make_product(db)
    u = await make_buyer(db)
    a = api.as_(principal(u))
    o = await buy(a, cat)
    await pay_via_webhook(client, fake_gw, o)
    rid = (await a.post("/me/refund-requests", {"order_id": o["order_id"]}, idem=True)).json()["refund_id"]
    f = finance(api, await make_buyer(db))
    fake_gw.unavailable = True
    r = await f.post(f"/finance/refunds/{rid}/decision", {"decision": "approve"}, idem=True)
    fake_gw.unavailable = False
    rf = (await rows(db, Refund, Refund.id == uuid.UUID(rid)))[0]
    e = (await rows(db, Entitlement, Entitlement.user_id == u))[0]
    print("approve during outage:", r.status_code, "refund", rf.status, "gw id", rf.gateway_refund_id, "ent", e.status)
    beat = [n for n in dir(ctasks) if "refund" in n.lower()]
    print("commerce task symbols mentioning refund:", beat)
    assert rf.status == "approved" and rf.gateway_refund_id is None and e.status == "revoked" and not beat
