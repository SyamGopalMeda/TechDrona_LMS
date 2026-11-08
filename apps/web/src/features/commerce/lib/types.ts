/**
 * Commerce DTOs. Request bodies come from the backend's Pydantic models (`Schema<>`); response
 * shapes are hand-written because the routes return `dict[str, Any]` — each one is verified
 * against apps/api/app/modules/commerce (router.py / service.py / pricing.py) and
 * apps/api/app/modules/entitlements. Money is integer paise; datetimes are ISO 8601.
 */
import type { Schema } from "@/lib/api-types";

export type QuoteBody = Schema<"QuoteIn">;
export type OrderBody = Schema<"OrderIn">;
export type ConfirmPayload = Schema<"ConfirmIn">;
export type RefundRequestBody = Schema<"RefundRequestIn">;
export type CancelSubscriptionBody = Schema<"CancelSubIn">;
export type SubscriptionBody = Schema<"SubscriptionIn">;
export type SubscriptionConfirmBody = Schema<"SubscriptionConfirmIn">;

/** Overlap notice / duplicate-purchase block (verified: commerce/pricing.py ownership_checks). */
export interface OwnershipNotice {
  code: "already_owned" | "included_in_subscription" | "overlaps_existing_access" | string;
  source_type: string;
  ends_at: string | null;
}

/** verified: commerce/pricing.py Quote.to_json (POST commerce/checkout/quote). */
export interface QuoteDto {
  price_id: string;
  product: { sku: string; name: string; product_kind: string };
  list_amount_paise: number;
  discount_paise: number;
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  total_paise: number;
  gst_rate: string;
  place_of_supply: string;
  coupon: { code: string | null; status: string; percent_off?: number } | null;
  warnings: OwnershipNotice[];
  blocking: OwnershipNotice[];
  refund_rule: string;
  access_ends_at: string | null;
}

/** verified: commerce/service.py create_order `checkout` (only on the COM-04 response). */
export interface GatewayCheckout {
  key_id: string;
  gateway_order_id: string;
  amount: number;
  currency: string;
  name?: string;
  description?: string;
  prefill?: { name?: string; email?: string; contact?: string };
  notes?: Record<string, string>;
  /** Not returned by the backend today (no simulated payment for the fake gateway). */
  test_payment?: { payment_id: string; signature: string } | null;
}

export type OrderStatus = "created" | "pending_payment" | "paid" | "failed" | "expired" | "cancelled" | "refunded" | "partially_refunded" | string;

/** verified: commerce/service.py order_json items (GET commerce/orders/{id} only). */
export interface OrderItemDto {
  order_item_id: string;
  product_id: string;
  price_id: string;
  unit_amount_paise: number;
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  total_paise: number;
  gst_rate: string;
  sac_code: string;
}

/**
 * verified: commerce/service.py order_json (+ `checkout`/`entitlements` from create_order,
 * `entitlements`/`message` from get_order, `entitlements`/`invoice`/`message` from confirm_order).
 */
export interface OrderDto {
  order_id: string;
  order_number: string;
  status: OrderStatus;
  currency: string;
  subtotal_paise: number;
  discount_paise: number;
  tax_paise: number;
  total_paise: number;
  gateway: string | null;
  expires_at: string;
  paid_at: string | null;
  created_at: string | null;
  items?: OrderItemDto[];
  checkout?: GatewayCheckout | null;
  entitlements?: EntitlementDto[];
  invoice?: { invoice_number: string; pdf_ready: boolean } | null;
  message?: string | null;
  /** COM-04 resumed a matching unpaid order instead of creating a duplicate (FE-27). */
  resumed?: boolean;
}

/** verified: commerce/service.py sub_json (GET me/subscriptions). */
export interface SubscriptionDto {
  subscription_id: string;
  plan_id: string;
  price_id: string;
  status: "created" | "authenticated" | "active" | "pending" | "grace" | "halted" | "cancelled" | "completed" | string;
  gateway_subscription_id: string | null;
  mandate_max_amount_paise: number | null;
  current_period_start: string | null;
  current_period_end: string | null;
  next_charge_at: string | null;
  cancel_at_period_end: boolean;
  grace_until: string | null;
  paid_count: number | null;
  /** Downgrade scheduled for the next renewal (change-plan contract; hand-written). */
  scheduled_price_id?: string | null;
  scheduled_change_at?: string | null;
  /** Prorated upgrade difference added to the next renewal debit. */
  pending_addon_paise?: number;
}

/** POST me/subscriptions/{id}/change-plan body (hand-written; Idempotency-Key required). */
export interface ChangePlanBody {
  price_id: string;
  preview: boolean;
}

/** POST me/subscriptions/{id}/change-plan response (preview and confirm share the shape). */
export interface ChangePlanResultDto {
  subscription_id: string;
  direction: "upgrade" | "downgrade";
  effective: "now" | "renewal";
  effective_at: string | null;
  from_price_id: string;
  to_price_id: string;
  from_amount_paise: number;
  to_amount_paise: number;
  remaining_days: number;
  period_days: number;
  proration_paise: number;
  next_debit_paise: number;
  preview: boolean;
  subscription: SubscriptionDto;
}

/** Every recurring debit is capped by the e-mandate (422 recurring_amount_exceeds_mandate_limit carries max_paise). */
export const MANDATE_MAX_PAISE = 1_500_000;

/** verified: commerce/service.py cancel_subscription (POST me/subscriptions/{id}/cancel). */
export interface CancelSubscriptionResult {
  subscription_id: string;
  status: string;
  cancel_at_period_end: boolean;
  access_until: string | null;
  confirmation_sent: boolean;
}

/** verified: commerce/service.py invoice_json (GET me/invoices). */
export interface InvoiceDto {
  invoice_id: string;
  invoice_number: string;
  invoice_type: "tax_invoice" | "credit_note" | string;
  order_id: string;
  original_invoice_id: string | null;
  issue_date: string;
  seller_gstin: string | null;
  buyer_name: string | null;
  buyer_gstin: string | null;
  place_of_supply: string | null;
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  total_paise: number;
  status: string;
  pdf_ready: boolean;
  description?: string | null;
  due_on?: string | null;
}

/** verified: commerce/router.py refund_eligibility + service.py refund_eligibility. */
export interface RefundEligibilityDto {
  order_id: string;
  refund_rule: string;
  eligible: boolean;
  reasons: string[];
  days_since_purchase: number;
  consumption_pct: number;
  certificate_issued: boolean;
  refundable_paise: number;
  usage_source?: string;
}

/** verified: commerce/service.py refund_json (GET me/refund-requests). */
export interface RefundRequestDto {
  refund_id: string;
  order_id: string;
  amount_paise: number | null;
  reason_code: string;
  status: string;
  consumption_pct: number | null;
  approval_request_id: string | null;
  gateway_refund_id: string | null;
  created_at: string | null;
  processed_at: string | null;
}

/** POST me/refund-requests adds the eligibility snapshot and decision date (commerce/router.py request_refund). */
export interface RefundRequestCreatedDto extends RefundRequestDto {
  eligibility: Omit<RefundEligibilityDto, "order_id" | "refund_rule">;
  decision_due: string;
}

/** verified: entitlements/service.py entitlement_json (+ title/effective_status from entitlements/router.py my_entitlements). */
export interface EntitlementDto {
  entitlement_id: string;
  product_id: string | null;
  course_id: string | null;
  feature_key: string | null;
  /** Single company: the company org or null (historic rows); not shown. */
  organization_id: string | null;
  source_type: string;
  source_ref: string | null;
  status: "active" | "grace" | "expired" | "suspended" | "revoked" | string;
  starts_at: string | null;
  ends_at: string | null;
  grace_ends_at: string | null;
  quotas: Record<string, number | null>;
  revoke_reason: string | null;
  /** Only on GET me/entitlements. */
  title?: string | null;
  /** Only on GET me/entitlements: status evaluated against the clock (e.g. active → expired). */
  effective_status?: string;
}

/** verified: entitlements/router.py my_entitlements (GET me/entitlements). */
export interface EntitlementsResponse {
  data: EntitlementDto[];
  restriction_gate: { active: boolean };
  page: { next_cursor: string | null; has_more: boolean };
}

/** verified: commerce/service.py create_subscription (POST commerce/subscriptions, COM-09). */
export interface SubscriptionCheckoutDto extends SubscriptionDto {
  checkout: { key_id: string; subscription_id: string; name?: string } | null;
}
