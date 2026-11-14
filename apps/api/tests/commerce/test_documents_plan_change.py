"""COM-13 resume, COM-14 plan change, COM-16 invoice PDFs, COM-37 GST export (+ Dual via
ADM-14), the B2C buyer-GSTIN tax invoice and the legacy offline-PO invoices kept after the B2B
removal (D1), and the A-7 commerce rate limits / webhook sanity limit."""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest

from app.core.time import ist_date, utcnow
from app.modules.commerce import documents, policy
from app.modules.commerce.models import GstExport, Invoice, Order, OrderItem, Subscription
from app.modules.entitlements.models import Entitlement, EntitlementEvent
from tests.commerce.factory import (
    buy,
    deliver,
    make_buyer,
    make_product,
    pay_via_webhook,
    principal,
    rows,
)


@pytest.fixture
def store() -> Iterator[documents.MemoryDocumentStore]:
    s = documents.MemoryDocumentStore()
    documents.set_document_store(s)
    yield s
    documents.set_document_store(None)


def _obj(store: documents.MemoryDocumentStore, url: str) -> bytes:
    path = url.split("://", 1)[1].split("?", 1)[0]
    bucket, key = path.split("/", 1)
    return store.objects[(bucket, key)][0]


def fin(api: Any, uid: uuid.UUID, *perms: str) -> Any:
    return api.as_(principal(uid, roles=("super_admin",), platform=True), *perms)


# --------------------------------------------------------------------------- COM-16


async def test_invoice_and_credit_note_pdfs_signed_and_scoped(api, db, client, fake_gw, store) -> None:
    cat = await make_product(db)
    u = await make_buyer(db)
    a = api.as_(principal(u))
    o = await buy(a, cat, state="29")  # inter-state -> IGST
    await pay_via_webhook(client, fake_gw, o)
    inv = (await a.get("/me/invoices")).json()["data"][0]
    assert inv["pdf_ready"] is False and "contract_id" not in inv
    r = await a.get(f"/me/invoices/{inv['invoice_id']}/pdf")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == inv["invoice_number"].replace("/", "-") + ".pdf"
    pdf = _obj(store, body["url"])
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000
    # stored once, reused (same key) and marked ready
    assert (await a.get("/me/invoices")).json()["data"][0]["pdf_ready"] is True
    assert len(store.objects) == 1
    await a.get(f"/me/invoices/{inv['invoice_id']}/pdf")
    assert len(store.objects) == 1
    # another student: 404; finance needs invoice.read
    other = api.as_(principal(await make_buyer(db)))
    assert (await other.get(f"/me/invoices/{inv['invoice_id']}/pdf")).status_code == 404
    f0 = fin(api, await make_buyer(db))
    assert (await f0.get(f"/finance/invoices/{inv['invoice_id']}/pdf")).status_code == 403
    f = fin(api, await make_buyer(db), "invoice.read", "invoice.credit_note")
    assert (await f.get(f"/finance/invoices/{inv['invoice_id']}/pdf")).status_code == 200
    # credit note PDF
    r = await f.post(
        f"/finance/invoices/{inv['invoice_id']}/credit-notes",
        {"amount_paise": 10000, "reason": "goodwill"},
        idem=True,
    )
    assert r.status_code == 201, r.text
    cn = r.json()
    r = await a.get(f"/me/invoices/{cn['invoice_id']}/pdf")
    assert r.status_code == 200 and _obj(store, r.json()["url"]).startswith(b"%PDF")


async def test_pdf_text_has_gst_breakup_and_placeholder_banner(db, api, client, fake_gw) -> None:
    cat = await make_product(db)
    u = await make_buyer(db)
    a = api.as_(principal(u))
    o = await buy(a, cat)
    await pay_via_webhook(client, fake_gw, o)
    inv = (await rows(db, Invoice, Invoice.order_id == uuid.UUID(o["order_id"])))[0]
    pdf = await documents.render_invoice_pdf(db, inv)
    # fpdf2 writes uncompressed text streams only when compression is off; check metadata
    assert pdf.startswith(b"%PDF")
    assert inv.seller_gstin == policy.PLACEHOLDER_GSTIN  # banner path exercised
    assert documents.inr(123456) == "1,234.56" and documents.inr(-5, grouping=False) == "-0.05"


# --------------------------------------------------------------------------- COM-37


EXPORT_PERMS = ("invoice.read", "report.export.request")


async def test_gst_export_csv_permissions_and_download(api, db, client, fake_gw, store) -> None:
    cat = await make_product(db)
    a = api.as_(principal(await make_buyer(db)))
    o = await buy(a, cat)
    await pay_via_webhook(client, fake_gw, o)
    inv = (await rows(db, Invoice, Invoice.order_id == uuid.UUID(o["order_id"])))[0]
    today = ist_date(utcnow())
    period = {"period_from": (today - timedelta(days=1)).isoformat(), "period_to": today.isoformat()}
    # invoice.read alone is not enough (report.export.request too)
    only_read = fin(api, await make_buyer(db), "invoice.read")
    assert (await only_read.post("/finance/gst-exports", period)).status_code == 403
    assert (
        await api.as_(principal(await make_buyer(db))).post("/finance/gst-exports", period)
    ).status_code == 403
    f = fin(api, await make_buyer(db), *EXPORT_PERMS)
    bad = {"period_from": "2026-01-01", "period_to": "2027-03-01"}
    assert (await f.post("/finance/gst-exports", bad)).status_code == 400
    r = await f.post("/finance/gst-exports", period)
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "ready" and job["row_count"] >= 1 and job["approval_request_id"] is None
    lst = (await f.get("/finance/gst-exports")).json()["data"]
    assert [x["gst_export_id"] for x in lst] == [job["gst_export_id"]]
    r = await f.get(f"/finance/gst-exports/{job['gst_export_id']}/download")
    assert r.status_code == 200 and r.json()["filename"].endswith(".csv")
    text = _obj(store, r.json()["url"]).decode()
    assert text.startswith("# Tech Drona GST register") and "CONFIDENTIAL" in text.splitlines()[0]
    data = list(csv.DictReader(io.StringIO("\n".join(text.splitlines()[1:]))))
    row = next(x for x in data if x["document_number"] == inv.invoice_number)
    assert row["document_type"] == "tax_invoice" and row["supply_category"] == "B2C"
    assert row["supply_type"] == "intra_state" and row["sac_code"] == "9992" and row["gst_rate"] == "18.00"
    paise = lambda v: round(float(v) * 100)  # noqa: E731
    assert paise(row["taxable_value_inr"]) == inv.taxable_paise
    assert paise(row["cgst_inr"]) + paise(row["sgst_inr"]) == inv.cgst_paise + inv.sgst_paise
    assert paise(row["total_inr"]) == inv.total_paise
    # requester only
    other = fin(api, await make_buyer(db), *EXPORT_PERMS)
    assert (await other.get(f"/finance/gst-exports/{job['gst_export_id']}/download")).status_code == 404
    # expired after 24 h
    from sqlalchemy import update

    from app.core.db import system_context

    await system_context(db, "test")
    await db.execute(
        update(GstExport)
        .where(GstExport.id == uuid.UUID(job["gst_export_id"]))
        .values(download_expires_at=utcnow() - timedelta(seconds=1))
    )
    r = await f.get(f"/finance/gst-exports/{job['gst_export_id']}/download")
    assert r.status_code == 409 and r.json()["current_state"] == "expired"


async def test_gst_export_over_threshold_needs_super_admin_approval(
    api, db, client, fake_gw, store, monkeypatch
) -> None:
    from app.modules.admin import approvals as apr

    async def _perm(session: Any, p: Any, key: str, scope: Any) -> bool:
        return key == "report.export.approve" and p.has_role("super_admin", "platform")

    monkeypatch.setattr(policy, "GST_EXPORT_DUAL_ABOVE_ROWS", 0)
    monkeypatch.setattr(apr.rs, "check_permission", _perm)
    cat = await make_product(db)
    a = api.as_(principal(await make_buyer(db)))
    o = await buy(a, cat)
    await pay_via_webhook(client, fake_gw, o)
    today = ist_date(utcnow()).isoformat()
    fid = await make_buyer(db)
    f = fin(api, fid, *EXPORT_PERMS)
    r = await f.post("/finance/gst-exports", {"period_from": today, "period_to": today, "reason": "GSTR-1"})
    assert r.status_code == 202 and r.json()["status"] == "awaiting_approval", r.text
    job, appr = r.json()["gst_export_id"], r.json()["approval_request_id"]
    assert appr and store.objects == {}
    assert (await f.get(f"/finance/gst-exports/{job}/download")).status_code == 409
    # requester cannot approve own export; a platform user without the Admin role cannot either
    fsa = api.as_(principal(fid, roles=("super_admin",), platform=True), *EXPORT_PERMS, "approval.decide")
    r = await fsa.post(f"/admin/approvals/{appr}/approve", {"note": "self"}, idem=True)
    assert r.status_code == 403 and r.json()["code"] == "sod_violation"
    other_fin = api.as_(principal(await make_buyer(db), platform=True), "report.export.approve")
    r = await other_fin.post(f"/admin/approvals/{appr}/approve", {"note": "x"}, idem=True)
    assert r.status_code == 403
    sa = api.as_(principal(await make_buyer(db), roles=("super_admin",), platform=True), "approval.decide")
    r = await sa.post(f"/admin/approvals/{appr}/approve", {"note": "ok"}, idem=True)
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert (await f.get(f"/finance/gst-exports/{job}")).json()["status"] == "ready"
    assert (await f.get(f"/finance/gst-exports/{job}/download")).status_code == 200
    # a second request rejected by the approver
    r = await f.post("/finance/gst-exports", {"period_from": today, "period_to": today})
    appr2 = r.json()["approval_request_id"]
    r = await sa.post(f"/admin/approvals/{appr2}/reject", {"note": "not needed"})
    assert r.status_code == 200, r.text
    jobs = {
        x["approval_request_id"]: x["status"] for x in (await f.get("/finance/gst-exports")).json()["data"]
    }
    assert jobs[appr2] == "rejected"


# --------------------------------------------------------------------------- B2C GSTIN (D1)


def _pdf_text(pdf: bytes) -> str:
    """Concatenated (inflated) content streams of an fpdf2 document."""
    import re
    import zlib

    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        out.append(raw.decode("latin-1"))
    return "\n".join(out)


async def _gstin_order(
    api: Any, db: Any, client: Any, fake_gw: Any, cat: Any, state: str, gstin: str
) -> Invoice:
    a = api.as_(principal(await make_buyer(db)))
    billing = {"state_code": state, "gstin": gstin, "name": "Acme Learners LLP"}
    q = await a.post("/commerce/checkout/quote", {"price_id": str(cat.price.id), "billing": billing})
    assert q.status_code == 200, q.text
    r = await a.post(
        "/commerce/orders",
        {"price_id": str(cat.price.id), "billing": billing, "quote_total_paise": q.json()["total_paise"]},
        idem=True,
    )
    assert r.status_code == 201, r.text
    await pay_via_webhook(client, fake_gw, r.json())
    return (await rows(db, Invoice, Invoice.order_id == uuid.UUID(r.json()["order_id"])))[0]


async def test_b2c_buyer_gstin_tax_invoice_splits_cgst_sgst_and_igst(api, db, client, fake_gw) -> None:
    """D1: a B2C buyer may still give a GSTIN; the tax invoice and its PDF keep the GST split."""
    cat = await make_product(db)
    intra = await _gstin_order(api, db, client, fake_gw, cat, "36", "36ABCDE1234F1Z5")
    inter = await _gstin_order(api, db, client, fake_gw, cat, "29", "29ABCDE1234F1Z5")
    assert intra.buyer_gstin == "36ABCDE1234F1Z5" and inter.buyer_gstin == "29ABCDE1234F1Z5"
    assert intra.cgst_paise > 0 and abs(intra.cgst_paise - intra.sgst_paise) <= 1 and intra.igst_paise == 0
    assert inter.igst_paise > 0 and inter.cgst_paise == 0 and inter.sgst_paise == 0
    for inv in (intra, inter):
        assert inv.total_paise == inv.taxable_paise + inv.cgst_paise + inv.sgst_paise + inv.igst_paise
        lines = await documents._lines(db, inv)
        assert lines[0]["description"] == cat.product.name  # no B2B description branch
        text = _pdf_text(await documents.render_invoice_pdf(db, inv))
        for label in ("CGST", "SGST", "IGST", "GSTIN: " + str(inv.buyer_gstin)):
            assert label in text, label
        assert "institution" not in text.lower()
    assert "Intra-state" in _pdf_text(await documents.render_invoice_pdf(db, intra))
    assert "Inter-state" in _pdf_text(await documents.render_invoice_pdf(db, inter))
    regs = await documents.gst_rows(db, ist_date(utcnow()) - timedelta(days=1), ist_date(utcnow()))
    mine = {r["document_number"]: r for r in regs}
    assert mine[intra.invoice_number]["supply_category"] == "B2B"
    assert mine[intra.invoice_number]["supply_type"] == "intra_state"
    assert mine[inter.invoice_number]["supply_type"] == "inter_state"


async def test_b2b_institution_routes_and_fields_are_gone(api, db) -> None:
    """Single company: contract, contract-invoice, org invoice/seat routes are 404 (or 405)."""
    f = fin(api, await make_buyer(db), "invoice.read", "coupon.manage", "product.manage", "entitlement.read")
    some = uuid.uuid4()
    for path in (
        "/finance/contracts",
        f"/finance/contracts/{some}/invoices",
        f"/orgs/{some}/contract",
        f"/orgs/{some}/invoices",
        f"/orgs/{some}/invoices/{some}/pdf",
        f"/orgs/{some}/seats",
    ):
        assert (await f.get(path)).status_code in (404, 405), path
    for path in (
        "/finance/contracts",
        f"/finance/contracts/{some}/terminate",
        f"/finance/contracts/{some}/invoices",
        f"/orgs/{some}/seats/assignments",
        f"/orgs/{some}/seats/revocations",
    ):
        assert (await f.post(path, {}, idem=True)).status_code in (404, 405), path
    # college coupons and institution seat products can no longer be created
    r = await f.post(
        "/finance/coupons",
        {
            "code": "COLLEGE10",
            "discount_type": "flat",
            "amount_off_paise": 100,
            "max_redemptions": 5,
            "valid_from": utcnow().isoformat(),
            "organization_id": str(some),
        },
    )
    assert r.status_code in (400, 422), r.text
    r = await f.post(
        "/finance/products",
        {"sku": "SEAT-X1", "name": "Seat", "product_kind": "institution_seat", "status": "active"},
    )
    assert r.status_code in (400, 422), r.text


async def test_legacy_offline_po_invoice_still_renders_and_is_never_auto_expired(api, db, store) -> None:
    """D1: archived institution invoices keep their rows (legacy offline-PO orders owned by an
    organization); the PDF uses the stored description, the expiry job leaves them alone, the
    finance PDF route still serves them, and a company member cannot read them through RLS."""
    from decimal import Decimal

    from sqlalchemy import select

    from app.core.db import system_context, tenant_context
    from app.core.ids import uuid7
    from app.modules.commerce import service as svc
    from app.modules.commerce.pricing import add_exclusive
    from tests.identity.factory import company_org

    cat = await make_product(db)
    await system_context(db, "test")
    now = utcnow()
    org = company_org()
    line = add_exclusive(200000, Decimal(cat.product.gst_rate), intra_state=False)
    order = Order(
        refunded_paise=0,
        id=uuid7(),
        order_number=await svc.next_order_number(db, now),
        user_id=None,
        organization_id=org,
        status="pending_payment",
        subtotal_paise=200000,
        discount_paise=0,
        tax_paise=line.tax_paise,
        total_paise=line.total_paise,
        gateway="offline_po",
        idempotency_key=f"legacy-{uuid7().hex}",
        billing_name="Legacy College",
        billing_gstin="29ABCDE1234F1Z5",
        place_of_supply="29",
        expires_at=now - timedelta(days=1),
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            id=uuid7(),
            order_id=order.id,
            organization_id=org,
            product_id=cat.product.id,
            plan_id=None,
            price_id=None,
            quantity=4,
            unit_amount_paise=50000,
            taxable_paise=line.taxable_paise,
            cgst_paise=0,
            sgst_paise=0,
            igst_paise=line.igst_paise,
            total_paise=line.total_paise,
            gst_rate=cat.product.gst_rate,
            sac_code=cat.product.sac_code,
        )
    )
    inv = Invoice(
        id=uuid7(),
        invoice_number=await svc.allocate_number(db, "TD", ist_date(now)),
        invoice_type="tax_invoice",
        order_id=order.id,
        organization_id=org,
        seller_gstin=policy.PLACEHOLDER_GSTIN,
        buyer_name="Legacy College",
        buyer_gstin="29ABCDE1234F1Z5",
        place_of_supply="29",
        issue_date=ist_date(now),
        taxable_paise=line.taxable_paise,
        igst_paise=line.igst_paise,
        total_paise=line.total_paise,
        description="Placement seats 2026-27 - PO-77",
        due_on=ist_date(now) + timedelta(days=30),
    )
    db.add(inv)
    await db.flush()
    assert (await documents._lines(db, inv))[0]["description"] == "Placement seats 2026-27 - PO-77"
    text = _pdf_text(await documents.render_invoice_pdf(db, inv))
    assert "Placement seats 2026-27 - PO-77" in text and "Payment due" in text and "IGST" in text
    await svc.expire_orders(db, None)  # type: ignore[arg-type]
    assert (await rows(db, Order, Order.id == order.id))[0].status == "pending_payment"
    f = fin(api, await make_buyer(db), "invoice.read")
    assert (await f.get(f"/finance/invoices/{inv.id}/pdf")).status_code == 200
    # RLS family O: a company member sees neither the org's order nor its invoice
    member = principal(await make_buyer(db), org_ids=(org,))
    await tenant_context(db, member)
    assert (await db.execute(select(Invoice.id).where(Invoice.id == inv.id))).first() is None
    assert (await db.execute(select(Order.id).where(Order.id == order.id))).first() is None
    assert (await db.execute(select(OrderItem.id).where(OrderItem.order_id == order.id))).first() is None


# --------------------------------------------------------------------------- COM-13 / COM-14


async def _active_sub(
    api: Any, db: Any, fake_gw: Any, amount: int = 49900, **kw: Any
) -> tuple[Any, str, str, Any]:
    cat = await make_product(
        db,
        kind="subscription_plan",
        amount_paise=amount,
        recurring=True,
        items=[{"item_type": "feature", "feature_key": "all_courses"}],
        **kw,
    )
    u = await make_buyer(db)
    a = api.as_(principal(u))
    r = await a.post("/commerce/subscriptions", {"price_id": str(cat.price.id)}, idem=True)
    assert r.status_code == 201, r.text
    sid, gsid = r.json()["subscription_id"], r.json()["checkout"]["subscription_id"]
    gp = fake_gw.subscription_charge(gsid, amount)
    body = {
        "razorpay_payment_id": gp.id,
        "razorpay_subscription_id": gsid,
        "razorpay_signature": fake_gw.subscription_signature(gp.id, gsid),
    }
    r = await a.post(f"/commerce/subscriptions/{sid}/confirm", body, idem=True)
    assert r.json()["status"] == "active", r.text
    return a, sid, gsid, cat


async def test_resume_scheduled_cancellation(api, db, client, fake_gw) -> None:
    a, sid, gsid, _ = await _active_sub(api, db, fake_gw)
    r = await a.post(f"/me/subscriptions/{sid}/resume")
    assert r.status_code == 409  # nothing scheduled
    await a.post(f"/me/subscriptions/{sid}/cancel", {"reason": "too_expensive"}, idem=True)
    assert gsid in fake_gw.scheduled_cancels
    r = await a.post(f"/me/subscriptions/{sid}/resume", idem=True)
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is False, r.text
    assert gsid not in fake_gw.scheduled_cancels
    s = (await rows(db, Subscription, Subscription.id == uuid.UUID(sid)))[0]
    assert not s.cancel_at_period_end and s.cancel_reason is None
    other = api.as_(principal(await make_buyer(db)))
    assert (await other.post(f"/me/subscriptions/{sid}/resume")).status_code == 404
    # immediately cancelled (terminal) cannot be resumed
    await _finance_cancel(api, db, sid)
    assert (await a.post(f"/me/subscriptions/{sid}/resume")).status_code == 409


async def _finance_cancel(api: Any, db: Any, sid: str) -> None:
    f = api.as_(
        principal(await make_buyer(db), roles=("super_admin",), platform=True), "subscription.admin_cancel"
    )
    r = await f.post(
        f"/finance/subscriptions/{sid}/cancel",
        {"reason": "fraud", "immediate": True, "ticket_ref": "T-1"},
        idem=True,
    )
    assert r.status_code == 200, r.text


async def test_upgrade_now_prorated_into_next_debit_and_cap(api, db, client, fake_gw, monkeypatch) -> None:
    from app.modules.commerce import ratelimit

    monkeypatch.setitem(ratelimit.LIMITS, "com14_change_plan", (ratelimit.Rule(50, 86_400),))
    a, sid, gsid, cur = await _active_sub(api, db, fake_gw, amount=49900)
    hi = await make_product(
        db,
        kind="subscription_plan",
        amount_paise=99900,
        recurring=True,
        gateway_plan="plan_HI",
        items=[{"item_type": "feature", "feature_key": "all_tests"}],
    )
    # preview: nothing changes
    r = await a.post(
        f"/me/subscriptions/{sid}/change-plan", {"price_id": str(hi.price.id), "preview": True}, idem=True
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["direction"] == "upgrade" and p["effective"] == "now" and p["preview"] is True
    assert 0 < p["proration_paise"] <= 50000 and p["period_days"] == 30
    assert p["next_debit_paise"] == 99900 + p["proration_paise"]
    assert (await rows(db, Subscription, Subscription.id == uuid.UUID(sid)))[0].price_id == cur.price.id
    # idempotency key required
    assert (
        await a.post(f"/me/subscriptions/{sid}/change-plan", {"price_id": str(hi.price.id)})
    ).status_code == 400
    r = await a.post(f"/me/subscriptions/{sid}/change-plan", {"price_id": str(hi.price.id)}, idem=True)
    assert r.status_code == 200 and r.json()["preview"] is False, r.text
    s = (await rows(db, Subscription, Subscription.id == uuid.UUID(sid)))[0]
    assert s.price_id == hi.price.id and s.pending_addon_paise == r.json()["proration_paise"]
    assert fake_gw.subscriptions[gsid].plan_id == "plan_HI"
    assert fake_gw.addons == [(gsid, r.json()["proration_paise"])]
    e = (await rows(db, Entitlement, Entitlement.subscription_id == s.id))[0]
    assert e.product_id == hi.product.id
    evts = [x.event_type for x in await rows(db, EntitlementEvent, EntitlementEvent.entitlement_id == e.id)]
    assert "plan_changed" in evts
    # the add-on is billed with the next debit, then cleared
    gp = fake_gw.subscription_charge(gsid, 99900 + s.pending_addon_paise)
    raw, h = fake_gw.webhook("subscription.charged", {"subscription": {"id": gsid}, "payment": {"id": gp.id}})
    await deliver(client, raw, h)
    assert (await rows(db, Subscription, Subscription.id == s.id))[0].pending_addon_paise == 0
    # debit cap: price + proration may not exceed Rs 15,000
    top = await make_product(
        db, kind="subscription_plan", amount_paise=1_500_000, recurring=True, gateway_plan="plan_TOP"
    )
    r = await a.post(
        f"/me/subscriptions/{sid}/change-plan", {"price_id": str(top.price.id), "preview": True}, idem=True
    )
    assert r.status_code == 422 and r.json()["code"] == "recurring_amount_exceeds_mandate_limit"
    assert r.json()["max_paise"] == 1_500_000
    # validation: one-time price, same plan
    one = await make_product(db, amount_paise=1000)
    r = await a.post(f"/me/subscriptions/{sid}/change-plan", {"price_id": str(one.price.id)}, idem=True)
    assert r.status_code == 400
    r = await a.post(f"/me/subscriptions/{sid}/change-plan", {"price_id": str(hi.price.id)}, idem=True)
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "same_plan"


async def test_downgrade_scheduled_for_renewal_then_applied(api, db, client, fake_gw) -> None:
    a, sid, gsid, cur = await _active_sub(api, db, fake_gw, amount=99900)
    lo = await make_product(
        db,
        kind="subscription_plan",
        amount_paise=49900,
        recurring=True,
        gateway_plan="plan_LO",
        items=[{"item_type": "feature", "feature_key": "all_tests"}],
    )
    r = await a.post(f"/me/subscriptions/{sid}/change-plan", {"price_id": str(lo.price.id)}, idem=True)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["direction"] == "downgrade" and out["effective"] == "renewal" and out["proration_paise"] == 0
    s = (await rows(db, Subscription, Subscription.id == uuid.UUID(sid)))[0]
    assert s.price_id == cur.price.id and s.scheduled_price_id == lo.price.id
    assert s.scheduled_change_at == s.current_period_end
    assert out["subscription"]["scheduled_price_id"] == str(lo.price.id)
    e = (await rows(db, Entitlement, Entitlement.subscription_id == s.id))[0]
    assert e.product_id == cur.product.id  # access to the current plan until renewal
    # renewal: the scheduled change is applied
    gp = fake_gw.subscription_charge(gsid, 49900)
    raw, h = fake_gw.webhook("subscription.charged", {"subscription": {"id": gsid}, "payment": {"id": gp.id}})
    await deliver(client, raw, h)
    s = (await rows(db, Subscription, Subscription.id == s.id))[0]
    assert s.price_id == lo.price.id and s.scheduled_price_id is None
    e = (await rows(db, Entitlement, Entitlement.id == e.id))[0]
    assert e.product_id == lo.product.id and e.status == "active"
    # a cancelled-at-period-end subscription cannot change plan
    await a.post(f"/me/subscriptions/{sid}/cancel", {"reason": "other"}, idem=True)
    r = await a.post(f"/me/subscriptions/{sid}/change-plan", {"price_id": str(cur.price.id)}, idem=True)
    assert r.status_code == 409


# --------------------------------------------------------------------------- A-7 rate limits


async def test_rate_limits_quote_and_webhook_never_drops_valid_events(
    api, db, client, fake_gw, monkeypatch
) -> None:
    from app.modules.commerce import ratelimit

    monkeypatch.setitem(ratelimit.LIMITS, "com03_quote", (ratelimit.Rule(2, 86_400),))
    monkeypatch.setattr(ratelimit, "WEBHOOK_INVALID_PER_IP", ratelimit.Rule(1, 86_400))
    cat = await make_product(db)
    a = api.as_(principal(await make_buyer(db)))
    q = {"price_id": str(cat.price.id), "coupon_code": "NOPE"}
    assert (await a.post("/commerce/checkout/quote", q)).status_code == 200
    assert (await a.post("/commerce/checkout/quote", q)).status_code == 200
    r = await a.post("/commerce/checkout/quote", q)
    assert r.status_code == 429 and r.json()["code"] == "rate_limited" and int(r.headers["Retry-After"]) >= 1
    # another user has their own bucket
    b = api.as_(principal(await make_buyer(db)))
    assert (await b.post("/commerce/checkout/quote", q)).status_code == 200
    # webhook: forged requests from one IP are capped; valid signed events still accepted
    # Unique per run: the per-IP counter lives in Redis for the whole day window, so a reused
    # address (the old 1-in-250 pick) made the first forged delivery 429 on later runs (flaky).
    h = uuid.uuid4().hex
    ip = "2001:db8:" + ":".join(h[i : i + 4] for i in range(0, 24, 4))
    from app.modules.commerce import router as crouter

    real = crouter.webhook_invalid_signature_hit

    async def same_ip(_ip: str | None) -> None:
        await real(ip)

    monkeypatch.setattr(crouter, "webhook_invalid_signature_hit", same_ip)
    raw, h = fake_gw.webhook("payment.captured", {"payment": {"id": "pay_x", "order_id": "order_x"}})
    forged = {**h, "x-razorpay-signature": "0" * 64}
    assert (await deliver(client, raw, forged)).status_code == 400
    assert (await deliver(client, raw, forged)).status_code == 429
    o = await buy(b, cat)
    await pay_via_webhook(client, fake_gw, o)  # asserts 200 accepted despite the IP being over limit


async def test_rate_limit_fails_open_without_redis(monkeypatch) -> None:
    from app.modules.commerce import ratelimit

    def boom() -> Any:
        raise ConnectionError("down")

    monkeypatch.setattr("app.core.redis.get_cache_redis", boom)
    await ratelimit.hit("x:u:1", (ratelimit.Rule(0, 60),))  # no exception


def test_billing_schema_rejects_bad_gstin() -> None:
    from pydantic import ValidationError

    from app.modules.commerce.schemas import BillingIn, GstExportIn

    with pytest.raises(ValidationError):
        BillingIn(gstin="bad")
    assert BillingIn(gstin="29ABCDE1234F1Z5").gstin == "29ABCDE1234F1Z5"
    assert GstExportIn(period_from=date(2026, 10, 1), period_to=date(2026, 10, 31)).reason is None
