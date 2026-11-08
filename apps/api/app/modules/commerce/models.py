"""Commerce tables (database-schema §11). Money is integer paise (ADR-0012).

Schema additions beyond §11 (reported to the Integration Lead):

* ``product_items.unit_price_paise`` — listed unit price of a consumable (mentor session) for
  the placement-package refund rule (FR-COM-008).
* ``reconciliation_runs`` — persisted daily reconciliation reports (FR-COM-013).

Single company (REMOVAL-PLAN §1.2, ``commerce_0004``): the B2B institution tables and columns
were dropped. ``invoices.description`` / ``due_on`` stay for the legacy offline-PO invoices,
which are kept as GST records (owner decision D1).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_U = UUID(as_uuid=True)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    sku: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    product_kind: Mapped[str] = mapped_column(Text, nullable=False)
    description_md: Mapped[str | None] = mapped_column(Text)
    sac_code: Mapped[str] = mapped_column(Text, nullable=False, server_default="9992")
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="18.00")
    refund_policy_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class ProductItem(Base):
    __tablename__ = "product_items"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("products.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    course_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    test_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    company_path_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    feature_key: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int | None] = mapped_column(Integer)
    unit_price_paise: Mapped[int | None] = mapped_column(BigInteger)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("products.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    billing_type: Mapped[str] = mapped_column(Text, nullable=False)
    interval_unit: Mapped[str | None] = mapped_column(Text)
    interval_count: Mapped[int | None] = mapped_column(SmallInteger)
    access_duration_days: Mapped[int | None] = mapped_column(Integer)
    trial_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    gateway_plan_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("plans.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="INR")
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_inclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    valid_until: Mapped[datetime | None] = mapped_column(_TS)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID] = mapped_column(_U, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    discount_type: Mapped[str] = mapped_column(Text, nullable=False)
    percent_off: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    amount_off_paise: Mapped[int | None] = mapped_column(BigInteger)
    applicable_product_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(_U), nullable=False, server_default="{}"
    )
    min_order_paise: Mapped[int | None] = mapped_column(BigInteger)
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    per_user_limit: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    redeemed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    valid_from: Mapped[datetime] = mapped_column(_TS, nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(_TS)
    first_time_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_by: Mapped[uuid.UUID] = mapped_column(_U, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class CouponRedemption(Base):
    __tablename__ = "coupon_redemptions"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    coupon_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("coupons.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_U, nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("orders.id"), nullable=False)
    discount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="reserved")
    reserved_until: Mapped[datetime] = mapped_column(_TS, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_U, nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("plans.id"), nullable=False)
    price_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("prices.id"), nullable=False)
    gateway: Mapped[str] = mapped_column(Text, nullable=False)
    gateway_subscription_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    mandate_max_amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(_TS)
    current_period_end: Mapped[datetime | None] = mapped_column(_TS)
    next_charge_at: Mapped[datetime | None] = mapped_column(_TS)
    pre_debit_notified_at: Mapped[datetime | None] = mapped_column(_TS)
    total_count: Mapped[int | None] = mapped_column(Integer)
    paid_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    cancelled_at: Mapped[datetime | None] = mapped_column(_TS)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    grace_until: Mapped[datetime | None] = mapped_column(_TS)
    scheduled_plan_id: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("plans.id"))
    scheduled_price_id: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("prices.id"))
    scheduled_change_at: Mapped[datetime | None] = mapped_column(_TS)
    pending_addon_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    billing_name: Mapped[str | None] = mapped_column(Text)
    billing_state_code: Mapped[str | None] = mapped_column(Text)
    billing_gstin: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    order_number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="created")
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="INR")
    subtotal_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    tax_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refunded_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    gateway: Mapped[str | None] = mapped_column(Text)
    gateway_order_id: Mapped[str | None] = mapped_column(Text)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("subscriptions.id"))
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    billing_name: Mapped[str | None] = mapped_column(Text)
    billing_gstin: Mapped[str | None] = mapped_column(Text)
    place_of_supply: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    order_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("orders.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    product_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("products.id"), nullable=False)
    # NULL only on legacy offline-PO invoice lines (commerce_0002 ``ck_oi_catalogue``).
    plan_id: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("plans.id"))
    price_id: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("prices.id"))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    unit_amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    taxable_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cgst_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    sgst_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    igst_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    sac_code: Mapped[str] = mapped_column(Text, nullable=False)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("orders.id"))
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("subscriptions.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    gateway: Mapped[str] = mapped_column(Text, nullable=False)
    gateway_payment_id: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_paise: Mapped[int | None] = mapped_column(BigInteger)
    tax_on_fee_paise: Mapped[int | None] = mapped_column(BigInteger)
    card_last4: Mapped[str | None] = mapped_column(Text)
    card_network: Mapped[str | None] = mapped_column(Text)
    card_issuer: Mapped[str | None] = mapped_column(Text)
    vpa_masked: Mapped[str | None] = mapped_column(Text)
    bank_code: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_description: Mapped[str | None] = mapped_column(Text)
    authorized_at: Mapped[datetime | None] = mapped_column(_TS)
    captured_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    gateway: Mapped[str] = mapped_column(Text, nullable=False)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    gateway_created_at: Mapped[datetime | None] = mapped_column(_TS)
    received_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="received")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(_TS)
    order_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    refetched_at: Mapped[datetime | None] = mapped_column(_TS)
    refetch_status: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(_TS)


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    payment_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("payments.id"), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("orders.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    gateway_refund_id: Mapped[str | None] = mapped_column(Text)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    reason_note: Mapped[str | None] = mapped_column(Text)
    consumption_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="requested")
    requested_by: Mapped[uuid.UUID] = mapped_column(_U, nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(_U)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    processed_at: Mapped[datetime | None] = mapped_column(_TS)
    submit_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    next_submit_at: Mapped[datetime | None] = mapped_column(_TS)
    last_error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class InvoiceSequence(Base):
    __tablename__ = "invoice_sequences"

    series: Mapped[str] = mapped_column(Text, primary_key=True)
    fiscal_year: Mapped[str] = mapped_column(Text, primary_key=True)
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    invoice_number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    invoice_type: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("orders.id"), nullable=False)
    refund_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    original_invoice_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    seller_gstin: Mapped[str] = mapped_column(Text, nullable=False)
    buyer_name: Mapped[str] = mapped_column(Text, nullable=False)
    buyer_gstin: Mapped[str | None] = mapped_column(Text)
    buyer_address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    place_of_supply: Mapped[str] = mapped_column(Text, nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    taxable_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cgst_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    sgst_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    igst_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    irn: Mapped[str | None] = mapped_column(Text)
    pdf_s3_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="issued")
    description: Mapped[str | None] = mapped_column(Text)
    due_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    gateway: Mapped[str] = mapped_column(Text, nullable=False)
    range_from: Mapped[datetime] = mapped_column(_TS, nullable=False)
    range_to: Mapped[datetime] = mapped_column(_TS, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="completed")
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    mismatches: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    triggered_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class GstExport(Base):
    """COM-37 GST register export job (platform only; file in the private exports bucket)."""

    __tablename__ = "gst_exports"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(_U, nullable=False)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(_U)
    s3_key: Mapped[str | None] = mapped_column(Text)
    download_expires_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(_TS)
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
