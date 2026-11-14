"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Button, Card, EmptyState, ErrorState, FormField, Input, PageHeader, Select, fieldErrors, buttonClasses } from "@/components/ui";
import { PLANS_HREF } from "@/lib/site/website";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { formatDate, formatMoney } from "@/features/catalog/lib/format";
import { NOTICE_VERSION } from "@/features/auth/lib/consents";
import type { Paged, PlanDto, PriceDto, ProductDto } from "@/features/catalog/lib/types";
import { useResource } from "@/features/learning/lib/use-resource";
import type { PayableOrder } from "../lib/payment-provider";
import { GST_STATES, GSTIN_PATTERN } from "../lib/states";
import type { OrderBody, OrderDto, OwnershipNotice, QuoteBody, QuoteDto, SubscriptionBody, SubscriptionCheckoutDto } from "../lib/types";
import { PaymentStep } from "./PaymentStep";
import { SubscriptionPaymentStep } from "./SubscriptionPaymentStep";

const COUPON_COPY: Record<string, string> = {
  applicable: "Coupon applied.",
  invalid: "This coupon code isn't valid.",
  expired: "This coupon has expired.",
  cap_reached: "This coupon has been fully used.",
  not_applicable: "This coupon doesn't apply to this plan.",
  min_order_not_met: "The order doesn't meet this coupon's minimum amount.",
  new_users_only: "This coupon is for new learners only.",
};

const ACTION_LINKS: Record<string, { href: string; label: string }> = {
  contact_not_verified: { href: "/app/settings/profile", label: "Verify your email and mobile" },
  consent_required: { href: "/app/settings/privacy", label: "Review consents" },
  minor_consent_pending: { href: "/app/settings/privacy", label: "Check guardian consent" },
};

const WARNING_COPY: Record<string, string> = {
  included_in_subscription: "Your subscription already includes this.",
  overlaps_existing_access: "You already have access that overlaps with this purchase.",
};

function blockingMessage(b: OwnershipNotice): string {
  if (b.code === "already_owned") return `You already have access to this${b.ends_at ? ` until ${formatDate(b.ends_at)}` : ""}, beyond when the new access would end.`;
  return "This purchase can't be completed right now.";
}

function warningMessage(w: OwnershipNotice): string {
  const base = WARNING_COPY[w.code] ?? "You already have access that overlaps with this purchase.";
  return w.ends_at ? `${base} (until ${formatDate(w.ends_at)})` : base;
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`flex justify-between gap-4 ${strong ? "border-t border-line pt-2 font-semibold text-fg" : "text-fg-secondary"}`}>
      <dt>{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}

function QuoteSummary({ quote }: { quote: QuoteDto }) {
  return (
    <dl className="space-y-1 text-sm">
      <Row label={quote.product.name} value={formatMoney(quote.list_amount_paise)} />
      {quote.discount_paise > 0 ? <Row label={`Discount${quote.coupon?.code ? ` (${quote.coupon.code})` : ""}`} value={`− ${formatMoney(quote.discount_paise)}`} /> : null}
      <Row label="Taxable value" value={formatMoney(quote.taxable_paise)} />
      {quote.igst_paise > 0 ? (
        <Row label="IGST (18%)" value={formatMoney(quote.igst_paise)} />
      ) : (
        <>
          <Row label="CGST (9%)" value={formatMoney(quote.cgst_paise)} />
          <Row label="SGST (9%)" value={formatMoney(quote.sgst_paise)} />
        </>
      )}
      <Row label="Total (incl. GST)" value={formatMoney(quote.total_paise)} strong />
    </dl>
  );
}

export interface CheckoutItem {
  productName: string;
  plan: PlanDto;
  price: PriceDto;
}

/** The product/plan/price behind `price_id` in the public catalogue (COM-01), if it is listed there. */
export function checkoutItem(products: ProductDto[] | undefined, priceId: string | null): CheckoutItem | null {
  if (!products || !priceId) return null;
  for (const product of products) {
    for (const plan of product.plans) {
      const price = plan.prices.find((p) => p.price_id === priceId);
      if (price) return { productName: product.name, plan, price };
    }
  }
  return null;
}

/** "per month", "every 3 months", "for 180 days" or "one-time payment". */
export function cadenceLabel(plan: PlanDto): string {
  if (plan.billing_type === "recurring") {
    const unit = plan.interval_unit === "year" ? "year" : "month";
    return plan.interval_count && plan.interval_count > 1 ? `every ${plan.interval_count} ${unit}s` : `per ${unit}`;
  }
  return plan.access_duration_days ? `one-time payment · ${plan.access_duration_days} days of access` : "one-time payment";
}

/** What is being bought, shown before any billing detail is entered (UI audit: checkout). */
function BuyingSummary({ item }: { item: CheckoutItem }) {
  return (
    <div className="mb-4 rounded-lg bg-brand-subtle p-3">
      <p className="text-[0.8125rem] font-semibold text-fg-secondary">You&apos;re buying</p>
      <p className="font-display text-base font-bold text-fg-heading">{item.productName}</p>
      <p className="mt-1 text-sm text-fg-secondary">
        <span className="font-display text-xl font-extrabold tabular-nums text-fg-heading">{formatMoney(item.price.amount_paise)}</span> {cadenceLabel(item.plan)}
        {item.price.tax_inclusive ? " · includes GST" : ""}
      </p>
    </div>
  );
}

/** Same-document URL change; Next.js syncs `history.replaceState` with its router. */
function replaceUrl(href: string) {
  try {
    window.history.replaceState(window.history.state, "", href);
  } catch {
    /* non-browser test environments: the order is still shown */
  }
}

/** INV-15: COM-03 answers `not_one_time` and COM-04 `recurring_price` for a recurring plan. */
function isRecurringPriceError(err: unknown): boolean {
  return (
    isApiError(err) &&
    err.code === "validation_failed" &&
    Boolean(err.problem?.errors?.some((x) => x.code === "recurring_price" || x.code === "not_one_time"))
  );
}

interface ConsentGrant {
  purpose: string;
  path: string;
}

/** E2E-04: `consent_required` names the consent and the endpoint that grants it. */
function consentGrant(err: unknown): ConsentGrant | null {
  if (!isApiError(err) || err.code !== "consent_required") return null;
  const grant = err.problem?.grant as { method?: string; path?: string; body?: { purpose?: string } } | undefined;
  const purpose = grant?.body?.purpose;
  // Only the consents endpoint is honoured; anything else falls back to the settings link.
  if (!grant || grant.method !== "POST" || grant.path?.replace(/^\//, "") !== "me/consents" || !purpose) return null;
  return { purpose, path: "me/consents" };
}

/** STU-016 checkout: billing → quote (COM-03) → order (COM-04) → payment (provider) → COM-06. */
export function Checkout({ priceId, returnTo }: { priceId: string | null; returnTo?: string | null }) {
  const [name, setName] = useState("");
  const [stateCode, setStateCode] = useState("");
  const [gstin, setGstin] = useState("");
  const [couponInput, setCouponInput] = useState("");
  const [coupon, setCoupon] = useState<string | null>(null);
  const [quote, setQuote] = useState<QuoteDto | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteError, setQuoteError] = useState<unknown>(null);
  const [recurring, setRecurring] = useState(false);
  const [granting, setGranting] = useState(false);
  const [ordering, setOrdering] = useState(false);
  const [orderError, setOrderError] = useState<unknown>(null);
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({});
  const [order, setOrder] = useState<OrderDto | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionCheckoutDto | null>(null);
  // Public catalogue: names the product and price up front. A failure here only hides that block.
  const catalogue = useResource<Paged<ProductDto>>(priceId ? "commerce/products" : null);
  const item = checkoutItem(catalogue.data?.data, priceId);

  const requestQuote = useCallback(async () => {
    if (!priceId || !stateCode) return;
    setQuoting(true);
    setQuoteError(null);
    try {
      const body: QuoteBody = { price_id: priceId, coupon_code: coupon, billing: { state_code: stateCode } };
      const res = await api.post<QuoteDto>("commerce/checkout/quote", body);
      if (res.kind === "ok") {
        setQuote(res.data);
        setRecurring(false);
      }
    } catch (err) {
      setQuote(null);
      if (isRecurringPriceError(err)) setRecurring(true);
      else setQuoteError(err);
    } finally {
      setQuoting(false);
    }
    // GSTIN does not change the quote (build_quote uses state_code only); it is sent with the order.
  }, [priceId, stateCode, coupon]);

  useEffect(() => {
    void requestQuote();
  }, [requestQuote]);

  if (!priceId) {
    return (
      <div>
        <PageHeader title="Checkout" />
        <EmptyState
          icon="card"
          title="Choose a plan first"
          description="Pick a course access option or a plan, then come back to checkout."
          action={<a href={PLANS_HREF} className={buttonClasses()}>See plans</a>}
        />
      </div>
    );
  }

  function validate(): boolean {
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = "Enter the name for the invoice.";
    if (!stateCode) errs.state = "Choose your state for GST.";
    if (gstin && !GSTIN_PATTERN.test(gstin.trim().toUpperCase())) errs.gstin = "Enter a valid 15-character GSTIN or leave it blank.";
    setLocalErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function placeOrder(e?: FormEvent) {
    e?.preventDefault();
    if (!validate() || !priceId) return;
    if (recurring) {
      setOrdering(true);
      setOrderError(null);
      await startSubscription();
      setOrdering(false);
      return;
    }
    if (!quote) return;
    setOrdering(true);
    setOrderError(null);
    try {
      const body: OrderBody = {
        price_id: priceId,
        coupon_code: coupon,
        billing: { name: name.trim(), state_code: stateCode, gstin: gstin.trim().toUpperCase() || null },
        quote_total_paise: quote.total_paise,
      };
      const res = await api.post<OrderDto>("commerce/orders", body, { idempotencyKey: true });
      if (res.kind === "ok") {
        setOrder(res.data);
        // FE-27: the URL becomes the order, so a reload resumes it (COM-05 returns `checkout`
        // for an unexpired pending order) instead of posting a second order. The native
        // history API keeps this component (and the payment step) mounted.
        replaceUrl(`/app/checkout/${encodeURIComponent(res.data.order_id)}`);
      }
    } catch (err) {
      if (isRecurringPriceError(err)) {
        // INV-15: a recurring plan is sold as a UPI AutoPay / e-mandate subscription (COM-09).
        setRecurring(true);
        await startSubscription();
        return;
      }
      if (isApiError(err) && err.code === "validation_failed" && err.problem?.errors?.some((x) => x.code === "quote_mismatch")) {
        await requestQuote();
        setOrderError(new Error("The price changed. Check the updated total and try again."));
      } else {
        setOrderError(err);
      }
    } finally {
      setOrdering(false);
    }
  }

  async function startSubscription() {
    if (!priceId) return;
    try {
      const body: SubscriptionBody = {
        price_id: priceId,
        billing: { name: name.trim(), state_code: stateCode, gstin: gstin.trim().toUpperCase() || null },
      };
      const res = await api.post<SubscriptionCheckoutDto>("commerce/subscriptions", body, { idempotencyKey: true });
      if (res.kind === "ok") setSubscription(res.data);
    } catch (err) {
      setOrderError(err);
    }
  }

  /** E2E-04: grant the named consent, then retry the order with the same billing details. */
  async function grantAndRetry(g: ConsentGrant) {
    setGranting(true);
    try {
      await api.post("me/consents", { purpose: g.purpose, action: "granted", notice_version: NOTICE_VERSION });
    } catch (err) {
      setOrderError(err);
      setGranting(false);
      return;
    }
    setGranting(false);
    await placeOrder();
  }

  const blocking = quote?.blocking ?? [];
  const grant = consentGrant(orderError);
  const serverField = isApiError(orderError) ? fieldErrors(orderError.problem?.errors) : {};
  const action = isApiError(orderError) && !grant ? ACTION_LINKS[orderError.code] : undefined;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Checkout"
        description="The total in the order summary is the final price, including GST."
        back={returnTo ? { href: returnTo, label: "Back" } : undefined}
      />
      {/* The summary comes first in reading order (phones see what they're buying before the form);
          from lg it sits in the right column. */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <aside aria-label="Order summary" className="lg:col-start-2 lg:row-start-1">
          <Card title="Order summary">
            {item ? <BuyingSummary item={item} /> : null}
            {recurring ? (
              <p className="text-sm text-fg-secondary">
                This plan renews automatically. The amount per renewal, including GST, is shown in the payment window, and you can cancel any time from Billing.
              </p>
            ) : !stateCode ? (
              <p className="text-sm text-fg-muted">Choose your state to see the GST breakdown and total.</p>
            ) : quoting && !quote ? (
              <p role="status" className="text-sm text-fg-muted">
                Calculating…
              </p>
            ) : quoteError ? (
              <ErrorState error={quoteError} onRetry={() => void requestQuote()} />
            ) : quote ? (
              <div className="space-y-3" aria-busy={quoting || undefined}>
                <QuoteSummary quote={quote} />
                {quote.access_ends_at ? <p className="text-xs text-fg-muted">Access until {formatDate(quote.access_ends_at)}.</p> : null}
                {quote.warnings.map((w, i) => (
                  <p key={`${w.code}-${i}`} className="rounded-md border border-info-border bg-info-subtle p-2 text-xs text-info-fg">
                    {warningMessage(w)}
                  </p>
                ))}
                {blocking.map((b, i) => (
                  <p key={i} role="alert" className="rounded-md border border-warning-border bg-warning-subtle p-2 text-xs text-warning-fg">
                    {blockingMessage(b)}
                  </p>
                ))}
                {quote.refund_rule ? <p className="text-xs text-fg-muted">{quote.refund_rule}</p> : null}
              </div>
            ) : null}
          </Card>
        </aside>

        <Card title="Billing details" className="lg:col-start-1 lg:row-start-1">
          {subscription ? (
            <SubscriptionPaymentStep subscription={subscription} />
          ) : order && order.checkout ? (
            <div className="space-y-3">
              {order.resumed ? (
                <p role="status" className="text-sm text-fg-secondary">
                  You already had an unpaid order for this plan, so we picked it up instead of creating a new one.
                </p>
              ) : null}
              <PaymentStep order={order as PayableOrder} />
            </div>
          ) : order ? (
            <p className="text-sm text-fg-secondary">
              Order {order.order_number} was created. <Link className="text-fg-link" href={`/app/orders/${encodeURIComponent(order.order_id)}`}>View order status</Link>
            </p>
          ) : (
            <form onSubmit={placeOrder} noValidate className="space-y-4" aria-label="Billing details">
              <FormField label="Name on invoice" required error={localErrors.name ?? serverField["billing.name"]}>
                {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />}
              </FormField>
              <FormField label="State" hint="Used for GST (place of supply)." required error={localErrors.state}>
                {(p) => (
                  <Select
                    {...p}
                    value={stateCode}
                    onChange={(e) => setStateCode(e.target.value)}
                    placeholder="Choose your state"
                    options={GST_STATES.map((s) => ({ value: s.code, label: s.name }))}
                  />
                )}
              </FormField>
              <FormField label="GSTIN (optional)" hint="Only if you need a business invoice." error={localErrors.gstin ?? serverField["billing.gstin"]}>
                {(p) => <Input {...p} value={gstin} onChange={(e) => setGstin(e.target.value)} autoCapitalize="characters" maxLength={15} />}
              </FormField>
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <FormField label="Coupon code (optional)">
                    {(p) => <Input {...p} value={couponInput} onChange={(e) => setCouponInput(e.target.value.toUpperCase())} maxLength={32} />}
                  </FormField>
                </div>
                <Button variant="secondary" onClick={() => setCoupon(couponInput.trim() || null)} disabled={!stateCode}>
                  Apply
                </Button>
              </div>
              {quote?.coupon ? (
                <p role="status" className={`text-sm ${quote.coupon.status === "applicable" ? "text-success-fg" : "text-warning-fg"}`}>
                  {COUPON_COPY[quote.coupon.status] ?? "This coupon can't be used."}
                </p>
              ) : null}
              <Button type="submit" size="lg" className="w-full sm:w-auto" loading={ordering} disabled={recurring ? !stateCode : !quote || quoting || blocking.length > 0}>
                {recurring ? "Continue to autopay set-up" : "Continue to payment"}
              </Button>
              {grant ? (
                <div role="alert" className="space-y-2 rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
                  <p className="font-semibold">{isApiError(orderError) ? orderError.title : null}</p>
                  {isApiError(orderError) && orderError.problem?.detail ? <p>{orderError.problem.detail}</p> : null}
                  <Button size="sm" loading={granting || ordering} onClick={() => void grantAndRetry(grant)}>
                    Turn on and continue
                  </Button>
                </div>
              ) : orderError ? (
                <div className="space-y-2">
                  <ErrorState error={orderError} />
                  {action ? (
                    <Link href={action.href} className="text-sm font-medium text-fg-link">
                      {action.label}
                    </Link>
                  ) : null}
                </div>
              ) : null}
            </form>
          )}
        </Card>
      </div>
    </div>
  );
}
