"""Firestore collections of the commerce module (MIGRATION-PLAN P6; ``TD_STORE_COMMERCE``).

One collection per Postgres table, same logical name (physical ``lms_<table>``), one document per
row, document id = the primary key (``invoice_sequences``: ``{series}:{fiscal_year}``). Every
column is stored under its own name (codec: ``app/core/firestore/sqlstore.py``): UUID -> str,
``uuid[]`` -> list[str], timestamptz -> timestamp, ``date`` -> ISO string, ``numeric`` -> exact
decimal string (money stays integer paise), ``bytea`` -> bytes, JSONB -> canonical JSON string.
``_lk`` (not a column) is bumped when a row is committed under ``FOR UPDATE`` without a change.

Authorization: all collections are ``system`` family; the engine applies each table's Postgres
RLS family (``RLS``) to the caller's transaction scope. Uniqueness -> ``uniq_commerce_*``
documents written in the commit transaction (``UNIQUES``). Sequences:
``commerce_counters/order_number`` (seeded from ``commerce_order_number_seq``) and the
``invoice_sequences`` rows (gap-free per series and fiscal year).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.errors import ProblemError
from app.core.firestore.backfill import TableMapping, register_mapping
from app.core.firestore.sqlstore import (
    SqlModuleSpec,
    SqlStore,
    columns,
    from_doc,
    from_store_value,
    model_doc_id,
    plain_dt,
    to_doc,
    to_store_value,
)
from app.core.firestore.store import ScopedTransaction
from app.modules.commerce.models import (
    Coupon,
    CouponRedemption,
    GstExport,
    Invoice,
    InvoiceSequence,
    Order,
    OrderItem,
    Payment,
    PaymentWebhookEvent,
    Plan,
    Price,
    Product,
    ProductItem,
    ReconciliationRun,
    Refund,
    Subscription,
)

MODELS: tuple[type[Any], ...] = (
    Product,
    ProductItem,
    Plan,
    Price,
    Coupon,
    CouponRedemption,
    Subscription,
    Order,
    OrderItem,
    Payment,
    PaymentWebhookEvent,
    Refund,
    InvoiceSequence,
    Invoice,
    ReconciliationRun,
    GstExport,
)
BY_TABLE: dict[str, type[Any]] = {m.__tablename__: m for m in MODELS}
TABLES = frozenset(BY_TABLE)
COUNTERS = "commerce_counters"
ORDER_SEQ = "order_number"

# Postgres RLS family per table (commerce_0001 / commerce_0004).
#   read_all : TN without organizations after commerce_0004 -> every caller reads, platform writes
#   owner    : O  -> ``user_id = app.user_id() OR app.is_platform()``
#   platform : ``app.is_platform()`` only
RLS: dict[str, str] = {
    "products": "read_all",
    "product_items": "read_all",
    "plans": "read_all",
    "prices": "read_all",
    "coupons": "read_all",
    "orders": "owner",
    "order_items": "owner",
    "payments": "owner",
    "refunds": "owner",
    "invoices": "owner",
    "coupon_redemptions": "owner",
    "subscriptions": "owner",
    "payment_webhook_events": "platform",
    "invoice_sequences": "platform",
    "reconciliation_runs": "platform",
    "gst_exports": "platform",
}
UPDATED_AT_TRIGGER = frozenset(
    {
        "products",
        "plans",
        "coupons",
        "coupon_redemptions",
        "subscriptions",
        "orders",
        "payments",
        "refunds",
        "gst_exports",
    }
)
CITEXT = frozenset({("products", "sku"), ("plans", "code"), ("coupons", "code")})
NO_DELETE = frozenset({"invoices", "payment_webhook_events"})


def _ci(v: Any) -> str:
    return str(v).lower()


def _k(*parts: Any) -> str:
    return "|".join("" if p is None else str(p) for p in parts)


def _pi_key(r: Any) -> str | None:
    ref = r.course_id or r.test_id or r.company_path_id or r.topic_id or r.feature_key
    return _k(r.product_id, r.item_type, ref)


def _opt(v: Any) -> str | None:
    return None if v is None else str(v)


UNIQUES: dict[str, list[tuple[str, Any]]] = {
    "products": [("products_sku", lambda r: _ci(r.sku))],
    "product_items": [("ux_pi", _pi_key)],
    "plans": [("plans_code", lambda r: _ci(r.code))],
    "coupons": [("coupons_code", lambda r: _ci(r.code))],
    "coupon_redemptions": [("cr_coupon_order", lambda r: _k(r.coupon_id, r.order_id))],
    "subscriptions": [("sub_gateway", lambda r: _k(r.gateway, r.gateway_subscription_id))],
    "orders": [
        ("orders_number", lambda r: r.order_number),
        ("orders_gateway", lambda r: _k(r.gateway, r.gateway_order_id) if r.gateway_order_id else None),
        ("orders_idem", lambda r: _k(r.user_id or r.organization_id, r.idempotency_key)),
    ],
    "payments": [("pay_gateway", lambda r: _k(r.gateway, r.gateway_payment_id))],
    "payment_webhook_events": [("pwe_event", lambda r: _k(r.gateway, r.event_id))],
    "refunds": [
        ("refund_idem", lambda r: r.idempotency_key),
        ("refund_gateway", lambda r: r.gateway_refund_id),
    ],
    "invoices": [
        ("inv_number", lambda r: r.invoice_number),
        (
            "inv_tax_order",
            lambda r: str(r.order_id) if r.invoice_type == "tax_invoice" and r.status == "issued" else None,
        ),
        ("inv_cn_refund", lambda r: _opt(r.refund_id)),
    ],
}


def check(table: str, r: Any) -> str | None:
    """The money CHECK constraints of the commerce schema (Postgres backstops)."""
    if table == "orders":
        if r.total_paise != r.subtotal_paise - r.discount_paise + r.tax_paise:
            return "ck_order_total"
        if not (0 <= (r.refunded_paise or 0) <= r.total_paise):
            return "ck_order_refunded"
        if r.status in ("paid", "refunded", "partially_refunded") and r.paid_at is None:
            return "ck_order_paid"
        if r.user_id is None and r.organization_id is None:
            return "ck_order_owner"
    elif table == "coupons":
        if r.max_redemptions is not None and r.redeemed_count > r.max_redemptions:
            return "ck_coupon_cap"
    elif table == "invoices":
        if r.total_paise != r.taxable_paise + r.cgst_paise + r.sgst_paise + r.igst_paise:
            return "ck_inv_total"
        if (r.invoice_type == "credit_note") != (r.original_invoice_id is not None):
            return "ck_inv_cn"
    elif table == "order_items":
        if not (r.igst_paise == 0 or (r.cgst_paise == 0 and r.sgst_paise == 0)):
            return "ck_oi_gst"
    elif table in ("refunds", "payments"):
        if r.amount_paise <= 0:
            return f"{table}_amount_paise_check"
    elif table == "prices":
        if r.amount_paise <= 0:
            return "prices_amount_paise_check"
        if r.is_recurring and r.amount_paise > 1_500_000:
            return "ck_price_mandate"
        if r.valid_until is not None and r.valid_until <= r.valid_from:
            return "ck_price_window"
    return None


async def price_overlap(tx: ScopedTransaction, work: list[Any]) -> None:
    """``ex_price_overlap``: active prices of one plan have disjoint [valid_from, valid_until)."""
    plans = {str(e.obj.plan_id) for e, final, changed in work if e.table == "prices" and changed and final}
    inf = datetime.max.replace(tzinfo=UTC)
    for plan_id in plans:
        stored = await tx.query("prices", filters=[("plan_id", "==", plan_id)])
        rows: dict[str, Any] = {d.id: from_doc(Price, d.data) for d in stored}
        for e, final, _ in work:
            if e.table != "prices":
                continue
            if final is not None and str(e.obj.plan_id) == plan_id:
                rows[e.doc_id] = e.obj
            else:
                rows.pop(e.doc_id, None)
        active = [p for p in rows.values() if p.is_active]
        for i, a in enumerate(active):
            for b in active[i + 1 :]:
                if a.valid_from < (b.valid_until or inf) and b.valid_from < (a.valid_until or inf):
                    raise ProblemError("conflict", detail="price windows overlap (ex_price_overlap)")


SPEC = SqlModuleSpec(
    module="commerce",
    models=MODELS,
    rls=RLS,
    uniques=UNIQUES,
    updated_at_trigger=UPDATED_AT_TRIGGER,
    citext=CITEXT,
    no_delete=NO_DELETE,
    check=check,
    commit_reads=(price_overlap,),
)
STORE = SqlStore(SPEC)


def unique_keys(table: str, obj: Any) -> set[tuple[str, str]]:
    return SPEC.unique_keys(table, obj)


def doc_id(table: str, values: Any) -> str:
    return model_doc_id(BY_TABLE[table], values)


_plain_dt = plain_dt

# --------------------------------------------------------------------------- backfill / verify

STORE.register_backfill()
register_mapping(
    TableMapping(
        "commerce",
        "(SELECT 'order_number' AS name, CASE WHEN is_called THEN last_value ELSE 0 END AS value "
        "FROM commerce_order_number_seq) AS c",
        COUNTERS,
        lambda r: r["name"],
        lambda r: {"value": int(r["value"])},
        order_by="name",
    )
)

__all__ = [
    "SPEC",
    "STORE",
    "columns",
    "doc_id",
    "from_doc",
    "from_store_value",
    "to_doc",
    "to_store_value",
    "unique_keys",
]
