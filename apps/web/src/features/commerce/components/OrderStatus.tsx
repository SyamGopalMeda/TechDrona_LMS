"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Badge, Card, PageHeader, type BadgeTone } from "@/components/ui";
import { formatDate, formatDateTime, formatMoney, humanize } from "@/features/catalog/lib/format";
import { ContentErrorState, LoadingBlock } from "@/features/learning/components/States";
import { useResource } from "@/features/learning/lib/use-resource";
import { isTestMode, type PayableOrder } from "../lib/payment-provider";
import type { OrderDto } from "../lib/types";
import { PaymentStep, TestModeBadge } from "./PaymentStep";

const POLL_MS = 4000;
const POLL_LIMIT_MS = 15 * 60 * 1000;

const TONE: Record<string, BadgeTone> = {
  paid: "success",
  pending_payment: "info",
  created: "info",
  failed: "danger",
  expired: "warning",
  cancelled: "neutral",
  refunded: "neutral",
  partially_refunded: "neutral",
};

export function OrderStatusBadge({ status }: { status: string }) {
  const label = status === "pending_payment" ? "Awaiting payment" : humanize(status);
  return <Badge tone={TONE[status] ?? "neutral"}>{label}</Badge>;
}

/** Polls COM-05 while the payment is being confirmed (up to 15 min). */
function usePolledOrder(orderId: string, poll: boolean) {
  const res = useResource<OrderDto>(`commerce/orders/${encodeURIComponent(orderId)}`);
  const started = useRef(Date.now());
  const [gaveUp, setGaveUp] = useState(false);
  const { reload } = res;
  const pending = res.data?.status === "pending_payment" || res.data?.status === "created";
  useEffect(() => {
    if (!poll || !pending || gaveUp) return;
    const t = setTimeout(() => {
      if (Date.now() - started.current > POLL_LIMIT_MS) setGaveUp(true);
      else void reload();
    }, POLL_MS);
    return () => clearTimeout(t);
  }, [poll, pending, gaveUp, reload, res.data]);
  return { ...res, gaveUp };
}

/**
 * STU-017 order status (also used by /app/checkout/[order_id] to resume a pending order).
 * Status is whatever the server reports; a payment is only "done" when COM-05 says `paid`.
 */
export function OrderStatus({ orderId, mode = "status" }: { orderId: string; mode?: "status" | "resume" }) {
  const { data: order, error, loading, reload, gaveUp } = usePolledOrder(orderId, mode === "status");

  if (error) return <ContentErrorState error={error} onRetry={reload} />;
  if (loading && !order) return <LoadingBlock label="Loading order" rows={2} />;
  if (!order) return null;

  const awaiting = order.status === "pending_payment" || order.status === "created";
  const canPay = mode === "resume" && awaiting && order.checkout;

  return (
    <div className="space-y-6">
      <PageHeader
        title={mode === "resume" ? "Complete your payment" : `Order ${order.order_number}`}
        actions={<OrderStatusBadge status={order.status} />}
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
              <dd className="text-fg">{formatDateTime(order.paid_at)}</dd>
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
              {order.expires_at ? ` at ${formatDateTime(order.expires_at)}` : ""} — you can start a new checkout from{" "}
              <Link href="/pricing" className="font-medium text-fg-link">
                plans
              </Link>
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
              What I have access to
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
            <Link href="/pricing" className="font-medium text-fg-link">
              See plans
            </Link>
          </p>
        </Card>
      )}
    </div>
  );
}
