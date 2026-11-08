"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, ErrorState } from "@/components/ui";
import { api } from "@/lib/api/client";
import { formatMoney } from "@/features/catalog/lib/format";
import { isFakeSubscription, payRazorpaySubscription } from "../lib/payment-provider";
import type { SubscriptionCheckoutDto, SubscriptionConfirmBody } from "../lib/types";
import { TestModeBadge } from "./PaymentStep";

/**
 * INV-15: a recurring plan starts a subscription (COM-09) and the learner authorises the
 * UPI AutoPay / e-mandate in the gateway window; the server confirms it (COM-10). The browser
 * callback alone never grants access — Billing shows whatever the server reports.
 */
export function SubscriptionPaymentStep({ subscription }: { subscription: SubscriptionCheckoutDto }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const checkout = subscription.checkout;
  const fake = checkout ? isFakeSubscription(checkout) : false;

  async function authorise() {
    if (!checkout) return;
    setBusy(true);
    setFailure(null);
    setError(null);
    try {
      const outcome = await payRazorpaySubscription(checkout);
      if (outcome.kind === "dismissed") {
        setFailure(outcome.failure ?? "The mandate wasn't authorised. You can try again.");
        return;
      }
      const body: SubscriptionConfirmBody = outcome.payload;
      await api.post(`commerce/subscriptions/${encodeURIComponent(subscription.subscription_id)}/confirm`, body, { idempotencyKey: true });
      router.push("/app/billing");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-fg-secondary">
        This plan renews automatically. You authorise a UPI AutoPay or card mandate
        {subscription.mandate_max_amount_paise ? ` of up to ${formatMoney(subscription.mandate_max_amount_paise)} per debit` : ""}. You can cancel any time from{" "}
        <Link href="/app/billing" className="font-medium text-fg-link">
          Billing
        </Link>
        .
      </p>
      {fake ? (
        <>
          <TestModeBadge />
          <p role="status" className="text-sm text-fg-muted">
            Authorising a mandate is not available with the test gateway in this environment. No money was involved.
          </p>
        </>
      ) : checkout ? (
        <Button size="lg" onClick={() => void authorise()} loading={busy}>
          Set up autopay
        </Button>
      ) : (
        <p role="status" className="text-sm text-fg-muted">
          The payment window is not available for this subscription. See Billing for its status.
        </p>
      )}
      {failure ? (
        <p role="alert" className="rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
          {failure}
        </p>
      ) : null}
      {error ? <ErrorState error={error} /> : null}
    </div>
  );
}
