"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Card, LoadingBlock, PageHeader, StatusBadge } from "@/components/ui";
import { PLANS_HREF } from "@/lib/site/website";
import { formatMoney, humanize } from "@/features/catalog/lib/format";
import { ContentErrorState } from "@/features/learning/components/States";
import { trackEvent } from "@/lib/firebase/analytics";
import { isTestMode, type PayableOrder } from "../lib/payment-provider";
import type { OrderDto } from "../lib/types";
import { PaymentStep, TestModeBadge } from "./PaymentStep";
import { ServiceNotIntegrated } from "@/components/shell/Integrations";
import { formatDate, formatDateTime } from "@/lib/format";
import { useResource } from "@/lib/api/use-resource";

const POLL_MS = 4000;
const POLL_LIMIT_MS = 15 * 60 * 1000;

export function OrderStatusBadge({ status }: { status: string }) {
  const label = status === "pending_payment" ? "Awaiting payment" : humanize(status);
  return <StatusBadge status={status} label={label} />;
}

/**
 * Polls COM-05 while the payment is being confirmed (up to 15 min). A poll that falls due while
 * the tab is hidden (the learner is in the payment app) waits and runs the moment the tab is
 * visible again; nobody can see the page in between, so this only saves requests.
 */
function usePolledOrder(orderId: string, poll: boolean) {
  const res = useResource<OrderDto>(`commerce/orders/${encodeURIComponent(orderId)}`);
  const started = useRef(Date.now());
  const [gaveUp, setGaveUp] = useState(false);
  const { reload } = res;
  const pending = res.data?.status === "pending_payment" || res.data?.status === "created";
  useEffect(() => {
    if (!poll || !pending || gaveUp) return;
    let due = false;
    const onVisible = () => {
      if (due && document.visibilityState === "visible") {
        due = false;
        void reload();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    const t = setTimeout(() => {
      if (Date.now() - started.current > POLL_LIMIT_MS) setGaveUp(true);
      else if (document.visibilityState === "hidden") due = true;
      else void reload();
    }, POLL_MS);
    return () => {
      clearTimeout(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [poll, pending, gaveUp, reload, res.data]);
  return { ...res, gaveUp };
}

/**
 * STU-017 order status (also used by /app/checkout/[order_id] to resume a pending order).
 * Status is whatever the server reports; a payment is only "done" when COM-05 says `paid`.
 */
export function OrderStatus({ orderId, mode = "status" }: { orderId: string; mode?: "status" | "resume" }) {
  const { data: order, error, loading, reload, gaveUp } = usePolledOrder(orderId, mode === "status");
  const paidOrder = order?.status === "paid" ? order : null;
  useEffect(() => {
    // GA4 purchase (only if analytics consent is on; GA de-duplicates by transaction_id).
    if (!paidOrder?.paid_at || Date.now() - Date.parse(paidOrder.paid_at) > 30 * 60 * 1000) return;
    trackEvent("purchase", { transaction_id: paidOrder.order_id, value: paidOrder.total_paise / 100, currency: paidOrder.currency || "INR", items_count: paidOrder.items?.length });
  }, [paidOrder]);

  if (error) return <ContentErrorState error={error} onRetry={reload} />;
  if (loading && !order) return <LoadingBlock label="Loading order" rows={2} size="card" />;
  if (!order) return null;

  const awaiting = order.status === "pending_payment" || order.status === "created";
  const canPay = mode === "resume" && awaiting && order.checkout;

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={mode === "status" ? [{ label: "Billing", href: "/app/billing" }, { label: `Order ${order.order_number}` }] : undefined}
        title={mode === "resume" ? "Complete your payment" : `Order ${order.order_number}`}
        meta={<OrderStatusBadge status={order.status} />}
      />
      {isTestMode(order) ? <TestModeBadge /> : null}

      <Card title="Summary">
        <dl className="grid gap-2 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="text-fg-muted">Order</dt>
          <dd className="font-mono text-fg">{order.order_number}</dd>
          <dt className="text-fg-muted">Total</dt>
          <dd className="tabular-nums text-fg">{formatMoney(order.total_paise)} incl. GST</dd>
          {order.paid_at ? (
            <>
              <dt className="text-fg-muted">Paid</dt>
              <dd className="text-fg">{formatDateTime(order.paid_at, { year: true })}</dd>
            </>
          ) : null}
        </dl>
      </Card>

      {canPay ? (
        <Card title="Payment">
          <PaymentStep order={order as PayableOrder} onCancelled={() => void reload()} />
        </Card>
      ) : mode === "resume" && awaiting ? (
        <Card title="Payment">
          {order.message ? (
            <p role="status" className="text-sm text-fg-secondary">
              {order.message} You don’t need to pay again —{" "}
              <Link href={`/app/orders/${encodeURIComponent(order.order_id)}`} className="font-medium text-fg-link">
                follow the order status
              </Link>
              .
            </p>
          ) : (
            <p role="status" className="text-sm text-fg-secondary">
              This order can’t be paid from here any more. If you haven’t paid, it expires on its own
              {order.expires_at ? ` at ${formatDateTime(order.expires_at, { year: true })}` : ""} — you can start a new checkout from{" "}
              <a href={PLANS_HREF} className="font-medium text-fg-link">
                plans
              </a>
              . If you already paid, see the{" "}
              <Link href={`/app/orders/${encodeURIComponent(order.order_id)}`} className="font-medium text-fg-link">
                order status
              </Link>
              .
            </p>
          )}
        </Card>
      ) : awaiting ? (
        <Card>
          <ServiceNotIntegrated service="payments" className="mb-3" />
          <div role="status" aria-live="polite">
            {gaveUp ? (
              <p className="text-sm text-fg-secondary">We’re still confirming this payment with the bank. We will email you when it’s confirmed — you don’t need to pay again.</p>
            ) : (
              <p className="text-sm text-fg-secondary">
                {order.message ?? "Awaiting payment. If you’ve just paid, this page updates automatically once the bank confirms it."}
              </p>
            )}
          </div>
          {mode === "status" && order.checkout && !gaveUp ? (
            <p className="mt-2 text-sm">
              Haven’t paid yet?{" "}
              <Link href={`/app/checkout/${encodeURIComponent(order.order_id)}`} className="font-medium text-fg-link">
                Complete payment
              </Link>
            </p>
          ) : null}
        </Card>
      ) : order.status === "paid" ? (
        <Card title="You're all set">
          <p role="status" className="text-sm text-fg-secondary">
            Payment confirmed. Your access is active.
          </p>
          {order.entitlements?.length ? (
            <ul className="mt-3 space-y-1 text-sm text-fg">
              {order.entitlements.map((e) => (
                <li key={e.entitlement_id}>
                  {e.title ?? humanize(e.source_type)}
                  {e.ends_at ? <span className="text-fg-muted"> · until {formatDate(e.ends_at)}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
          {order.invoice ? (
            <p className="mt-3 text-sm text-fg-secondary">
              Invoice {order.invoice.invoice_number}
              {order.invoice.pdf_ready === false ? " (PDF is being prepared)" : ""} — see{" "}
              <Link href="/app/billing" className="text-fg-link">
                Billing
              </Link>
              .
            </p>
          ) : null}
          <div className="mt-4 flex flex-wrap gap-3 text-sm">
            <Link href="/app/learning" className="font-medium text-fg-link">
              Go to my learning
            </Link>
            <Link href="/app/access" className="font-medium text-fg-link">
              My access
            </Link>
          </div>
        </Card>
      ) : (
        <Card>
          <p role="status" className="text-sm text-fg-secondary">
            {order.status === "expired"
              ? "This order expired before payment was completed. If money was deducted, it will be refunded or the order fulfilled automatically — you don't need to do anything."
              : order.status === "failed"
                ? "The payment didn't go through. No access was granted."
                : order.status === "cancelled"
                  ? "This order was cancelled."
                  : `This order is ${humanize(order.status).toLowerCase()}.`}
          </p>
          <p className="mt-3 text-sm">
            <a href={PLANS_HREF} className="font-medium text-fg-link">
              See plans
            </a>
          </p>
        </Card>
      )}
    </div>
  );
}
