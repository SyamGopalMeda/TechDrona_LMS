"""Request bodies (``extra="forbid"``; api-specification §1.1)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GSTIN = r"^[0-9]{2}[A-Z0-9]{13}$"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BillingIn(_In):
    name: str | None = Field(default=None, max_length=200)
    state_code: str | None = Field(default=None, pattern=r"^[0-9]{2}$")
    gstin: str | None = Field(default=None, pattern=GSTIN)


class QuoteIn(_In):
    price_id: uuid.UUID
    coupon_code: str | None = Field(default=None, max_length=32)
    billing: BillingIn = Field(default_factory=BillingIn)


class OrderIn(QuoteIn):
    quote_total_paise: int = Field(ge=0)


class ConfirmIn(_In):
    razorpay_order_id: str = Field(max_length=64)
    razorpay_payment_id: str = Field(max_length=64)
    razorpay_signature: str = Field(max_length=128)


class SubscriptionIn(_In):
    price_id: uuid.UUID
    billing: BillingIn = Field(default_factory=BillingIn)  # COM-10: GST place of supply


class SubscriptionConfirmIn(_In):
    razorpay_payment_id: str = Field(max_length=64)
    razorpay_subscription_id: str = Field(max_length=64)
    razorpay_signature: str = Field(max_length=128)


class CancelSubIn(_In):
    reason: str | None = Field(default=None, max_length=100)
    feedback: str | None = Field(default=None, max_length=1000)


class AdminCancelSubIn(_In):
    reason: str = Field(min_length=3, max_length=200)
    ticket_ref: str | None = Field(default=None, max_length=40)
    immediate: bool = False


class RefundRequestIn(_In):
    order_id: uuid.UUID
    reason_code: Literal["within_policy_window", "content_issue", "other"] = "within_policy_window"
    note: str | None = Field(default=None, max_length=1000)


class RefundDecisionIn(_In):
    decision: Literal["approve", "reject"]
    amount_paise: int | None = Field(default=None, gt=0)
    goodwill: bool = False
    order_item_ids: list[uuid.UUID] | None = None
    note: str | None = Field(default=None, max_length=1000)


class FinanceRefundIn(_In):
    order_id: uuid.UUID
    amount_paise: int | None = Field(default=None, gt=0)
    # ``price_adjustment`` / ``duplicate_payment`` are pure money corrections that keep access
    # (COM-01); every other reason revokes the order's access unless ``order_item_ids`` narrows it.
    reason_code: Literal[
        "duplicate_payment", "service_failure", "content_issue", "goodwill", "price_adjustment", "other"
    ]
    note: str = Field(min_length=3, max_length=1000)
    order_item_ids: list[uuid.UUID] | None = None


class ProductItemIn(_In):
    item_type: Literal["course", "test", "company_path", "topic_practice", "feature"]
    ref_id: uuid.UUID | None = None
    feature_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,62}$")
    quantity: int | None = Field(default=None, gt=0)
    unit_price_paise: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _ref(self) -> ProductItemIn:
        if (self.item_type == "feature") != (self.feature_key is not None) or (
            self.item_type != "feature" and self.ref_id is None
        ):
            raise ValueError("feature items need feature_key; other items need ref_id")
        return self


class ProductIn(_In):
    sku: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{1,63}$")
    name: str = Field(min_length=2, max_length=200)
    product_kind: Literal[
        "free_resource",
        "free_course",
        "course",
        "bundle",
        "subscription_plan",
        "placement_package",
        "mock_pack",
    ]
    description_md: str | None = Field(default=None, max_length=20000)
    sac_code: str = Field(default="9992", pattern=r"^[0-9]{4,8}$")
    gst_rate: Decimal = Field(default=Decimal("18.00"), ge=0, le=28)
    refund_policy_key: str = Field(default="standard_7d_20pct", max_length=64)
    status: Literal["draft", "active"] = "draft"
    items: list[ProductItemIn] = Field(default_factory=list, max_length=500)


class ProductPatchIn(_In):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description_md: str | None = Field(default=None, max_length=20000)
    status: Literal["draft", "active", "retired"] | None = None


class PlanIn(_In):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")
    billing_type: Literal["one_time", "recurring"]
    interval_unit: Literal["month", "year"] | None = None
    interval_count: int | None = Field(default=None, ge=1, le=12)
    access_duration_days: int | None = Field(default=None, gt=0, le=3650)
    gateway_plan_ids: dict[str, str] | None = None

    @model_validator(mode="after")
    def _shape(self) -> PlanIn:
        if self.billing_type == "one_time" and (self.access_duration_days is None or self.interval_unit):
            raise ValueError("one_time plans need access_duration_days and no interval")
        if self.billing_type == "recurring" and (self.interval_unit is None or self.interval_count is None):
            raise ValueError("recurring plans need interval_unit and interval_count")
        return self


class PriceIn(_In):
    amount_paise: int = Field(gt=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    reason: str = Field(default="price change", min_length=3, max_length=500)


class CouponIn(_In):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{3,32}$")
    discount_type: Literal["percent", "flat", "free_access"]
    percent_off: Decimal | None = Field(default=None, gt=0, le=100)
    amount_off_paise: int | None = Field(default=None, gt=0)
    applicable_product_ids: list[uuid.UUID] = Field(default_factory=list)
    min_order_paise: int | None = Field(default=None, ge=0)
    max_redemptions: int | None = Field(default=None, gt=0)
    per_user_limit: int = Field(default=1, ge=1, le=100)
    valid_from: datetime
    valid_until: datetime | None = None
    first_time_only: bool = False
    reason: str = Field(default="campaign", min_length=3, max_length=500)

    @model_validator(mode="after")
    def _shape(self) -> CouponIn:
        if self.discount_type == "percent" and (
            self.percent_off is None or self.amount_off_paise is not None
        ):
            raise ValueError("percent coupons need percent_off only")
        if self.discount_type == "flat" and (self.amount_off_paise is None or self.percent_off is not None):
            raise ValueError("flat coupons need amount_off_paise only")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class CouponPatchIn(_In):
    status: Literal["active", "paused"] | None = None
    valid_until: datetime | None = None
    max_redemptions: int | None = Field(default=None, gt=0)


class ReasonIn(_In):
    reason: str = Field(min_length=3, max_length=1000)


class CreditNoteIn(_In):
    amount_paise: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)


class ReconciliationIn(_In):
    range_from: datetime
    range_to: datetime


class ApprovalDecisionIn(_In):
    note: str | None = Field(default=None, max_length=1000)


class ChangePlanIn(_In):
    """COM-14: ``preview`` computes proration without changing the subscription."""

    price_id: uuid.UUID
    preview: bool = False


class GstExportIn(_In):
    """COM-37: inclusive IST issue-date range, at most 366 days."""

    period_from: date
    period_to: date
    reason: str | None = Field(default=None, max_length=500)
