"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Badge, Button, Dialog, ErrorState } from "@/components/ui";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { formatDateTime, formatMoney } from "@/features/catalog/lib/format";
import { isTestMode, providerFor, type PayableOrder } from "../lib/payment-provider";

type Choice = "success" | "failure" | "dismiss";

export function TestModeBadge() {
  return <Badge tone="warning">Test mode — no real money is charged</Badge>;
}

/**
 * Pays an order created by COM-04 through the provider abstraction, then confirms it
 * server-side (COM-06). Whatever COM-06 returns, the order page (STU-017) shows the server's
 * status — the browser callback alone never grants access.
 */
export function PaymentStep({ order, onCancelled }: { order: PayableOrder; onCancelled?: () => void }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [testOpen, setTestOpen] = useState(false);
  const resolver = useRef<((c: Choice) => void) | null>(null);
  const testMode = isTestMode(order);
  const orderHref = `/app/orders/${encodeURIComponent(order.order_id)}`;

  function choose(c: Choice) {
    setTestOpen(false);
    resolver.current?.(c);
    resolver.current = null;
  }

  async function pay() {
    setBusy(true);
    setFailure(null);
    setError(null);
    try {
      const provider = providerFor(order);
      const outcome = await provider.pay(order, {
        chooseOutcome: () =>
          new Promise<Choice>((resolve) => {
            resolver.current = resolve;
            setTestOpen(true);
          }),
      });
      if (outcome.kind === "dismissed") {
        setFailure(outcome.failure ?? "Payment wasn't completed. You can try again before the order expires.");
        return;
      }
      await api.post(`commerce/orders/${encodeURIComponent(order.order_id)}/confirm`, outcome.payload, { idempotencyKey: true });
      router.push(orderHref);
    } catch (err) {
      if (isApiError(err) && err.code === "order_expired") {
        router.push(orderHref);
        return;
      }
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`commerce/orders/${encodeURIComponent(order.order_id)}/cancel`, {}, { idempotencyKey: true });
      onCancelled?.();
      router.push(orderHref);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      {testMode ? <TestModeBadge /> : null}
      <p className="text-sm text-fg-secondary">
        Order <span className="font-mono">{order.order_number}</span>
        {order.expires_at ? ` · complete payment by ${formatDateTime(order.expires_at)}` : ""}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="lg" onClick={() => void pay()} loading={busy}>
          Pay {formatMoney(order.total_paise)}
        </Button>
        <Button variant="ghost" onClick={() => void cancel()} disabled={busy}>
          Cancel order
        </Button>
      </div>
      {failure ? (
        <p role="alert" className="rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
          {failure}
        </p>
      ) : null}
      {error ? <ErrorState error={error} /> : null}

      <Dialog
        open={testOpen}
        onClose={() => choose("dismiss")}
        title="Test payment"
        description="This environment uses a test payment gateway. No real money moves and no card or UPI details are collected."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => choose("dismiss")}>
              Close
            </Button>
            <Button variant="secondary" onClick={() => choose("failure")}>
              Simulate a failed payment
            </Button>
            <Button onClick={() => choose("success")} disabled={!order.checkout.test_payment}>
              Simulate a successful payment
            </Button>
          </div>
        }
      >
        <p className="text-sm text-fg-secondary">
          Amount: <span className="font-semibold tabular-nums text-fg">{formatMoney(order.total_paise)}</span>. Access is granted only after the server confirms the payment.
        </p>
        {!order.checkout.test_payment ? <p className="mt-2 text-xs text-fg-muted">Simulating a successful payment is not available yet in this environment.</p> : null}
      </Dialog>
    </div>
  );
}
