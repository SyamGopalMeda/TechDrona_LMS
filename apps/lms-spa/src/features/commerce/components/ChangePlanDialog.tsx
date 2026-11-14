"use client";

import { useState, type FormEvent } from "react";
import { Button, Dialog, ErrorState, FormField, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { formatMoney } from "@/features/catalog/lib/format";
import type { PlanDto, ProductDto } from "@/features/catalog/lib/types";
import { MANDATE_MAX_PAISE, type ChangePlanBody, type ChangePlanResultDto, type SubscriptionDto } from "../lib/types";
import { formatDate } from "@/lib/format";

/* ------------------------------------------------------- catalogue helpers */

export interface RecurringPriceOption {
  price_id: string;
  amount_paise: number;
  product_name: string;
  plan: PlanDto;
  label: string;
}

export function intervalLabel(plan: Pick<PlanDto, "interval_unit" | "interval_count">): string {
  const unit = plan.interval_unit ?? "month";
  const n = plan.interval_count ?? 1;
  return n === 1 ? `/${unit}` : `every ${n} ${unit}s`;
}

/** Every active price of a recurring plan in the public catalogue (GET commerce/products). */
export function recurringPrices(products: ProductDto[] | undefined): RecurringPriceOption[] {
  const out: RecurringPriceOption[] = [];
  for (const product of products ?? []) {
    for (const plan of product.plans ?? []) {
      if (plan.billing_type !== "recurring") continue;
      for (const price of plan.prices ?? []) {
        if (price.is_active === false) continue;
        out.push({
          price_id: price.price_id,
          amount_paise: price.amount_paise,
          product_name: product.name,
          plan,
          label: `${product.name} · ${formatMoney(price.amount_paise)} ${intervalLabel(plan)}`,
        });
      }
    }
  }
  return out;
}

/** Human copy for the change-plan problems the api documents (others fall back to the problem title/detail). */
export function changePlanError(err: unknown): { title?: string; detail?: string } {
  if (!(err instanceof ApiError)) return {};
  if (err.code === "recurring_amount_exceeds_mandate_limit") {
    const max = typeof err.problem?.max_paise === "number" ? err.problem.max_paise : MANDATE_MAX_PAISE;
    return {
      title: "This change would exceed the auto-debit limit",
      detail: `A single renewal debit can't be more than ${formatMoney(max)} (your e-mandate limit). Choose a lower plan, or change plan closer to your renewal date when less difference is added.`,
    };
  }
  if (err.code === "invalid_state_transition") {
    return { title: "This subscription can't change plan right now", detail: err.problem?.detail || "Only active subscriptions can change plan." };
  }
  return {};
}

/* ------------------------------------------------------------------ dialog */

export interface ChangePlanDialogProps {
  subscription: SubscriptionDto;
  products: ProductDto[] | undefined;
  catalogueLoading: boolean;
  catalogueError: unknown;
  onClose: () => void;
  onChanged: (result: ChangePlanResultDto) => void;
}

/** STU-018 change plan: preview the proration first, then confirm (a fresh Idempotency-Key for each call). */
export function ChangePlanDialog({ subscription, products, catalogueLoading, catalogueError, onClose, onChanged }: ChangePlanDialogProps) {
  const toast = useToast();
  const all = recurringPrices(products);
  const options = all.filter((o) => o.price_id !== subscription.price_id);
  const current = all.find((o) => o.price_id === subscription.price_id);
  const [priceId, setPriceId] = useState("");
  const [preview, setPreview] = useState<ChangePlanResultDto | null>(null);
  const [busy, setBusy] = useState<"preview" | "confirm" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const path = `me/subscriptions/${encodeURIComponent(subscription.subscription_id)}/change-plan`;
  const selected = options.find((o) => o.price_id === priceId);

  async function call(mode: "preview" | "confirm"): Promise<ChangePlanResultDto | null> {
    setBusy(mode);
    setError(null);
    try {
      const body: ChangePlanBody = { price_id: priceId, preview: mode === "preview" };
      const res = await api.post<ChangePlanResultDto>(path, body, { idempotencyKey: true });
      return res.kind === "ok" ? res.data : null;
    } catch (err) {
      setError(err);
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function submitPreview(e: FormEvent) {
    e.preventDefault();
    if (!priceId) return;
    setPreview(await call("preview"));
  }

  async function confirm() {
    const result = await call("confirm");
    if (!result) return;
    toast.show({
      title:
        result.direction === "upgrade"
          ? `Plan upgraded.${result.proration_paise > 0 ? ` ${formatMoney(result.proration_paise)} will be added to your next renewal.` : ""}`
          : `Your plan changes on ${formatDate(result.effective_at ?? subscription.current_period_end)}.`,
      tone: "success",
    });
    onChanged(result);
  }

  const copy = changePlanError(error);
  const effectiveOn = formatDate(preview?.effective_at ?? subscription.current_period_end);
  return (
    <Dialog open onClose={onClose} title="Change plan" description={current ? `Current plan: ${current.label}` : undefined} dismissible={busy === null}>
      <form onSubmit={submitPreview} className="space-y-4" aria-label="Change plan">
        {catalogueError ? (
          <ErrorState error={catalogueError} />
        ) : catalogueLoading && !products ? (
          <p role="status" className="text-sm text-fg-muted">
            Loading plans…
          </p>
        ) : options.length === 0 ? (
          <p className="text-sm text-fg-muted">There are no other recurring plans to switch to.</p>
        ) : (
          <FormField label="New plan" required>
            {(p) => (
              <Select
                {...p}
                value={priceId}
                onChange={(ev) => {
                  setPriceId(ev.target.value);
                  setPreview(null);
                  setError(null);
                }}
                options={[{ value: "", label: "Choose a plan" }, ...options.map((o) => ({ value: o.price_id, label: o.label }))]}
              />
            )}
          </FormField>
        )}

        <div className="rounded-md border border-line bg-surface-sunken p-3 text-xs text-fg-secondary">
          <p>
            <strong className="text-fg">Upgrades</strong> take effect now. The prorated difference (remaining days × the daily price difference) is added to your next renewal debit.
          </p>
          <p className="mt-1">
            <strong className="text-fg">Downgrades</strong> take effect at your next renewal. There is no refund for the current period.
          </p>
          <p className="mt-1">Every auto-debit is capped at {formatMoney(MANDATE_MAX_PAISE)}.</p>
        </div>

        {preview && selected ? (
          <section aria-label="Change preview" className="rounded-md border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
            <p className="font-medium">
              {preview.direction === "upgrade" ? `Upgrade to ${selected.product_name}: takes effect now` : `Downgrade to ${selected.product_name}: takes effect on ${effectiveOn}`}
            </p>
            <dl className="mt-2 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-xs">
              <dt>Current price</dt>
              <dd className="text-right tabular-nums">{formatMoney(preview.from_amount_paise)}</dd>
              <dt>New price</dt>
              <dd className="text-right tabular-nums">{formatMoney(preview.to_amount_paise)}</dd>
              {preview.direction === "upgrade" ? (
                <>
                  <dt>
                    Prorated difference ({preview.remaining_days} of {preview.period_days} days left)
                  </dt>
                  <dd className="text-right tabular-nums">{formatMoney(preview.proration_paise)}</dd>
                </>
              ) : null}
              <dt className="font-medium">Next renewal debit</dt>
              <dd className="text-right font-medium tabular-nums">{formatMoney(preview.next_debit_paise)}</dd>
            </dl>
            <p className="mt-2 text-xs">
              {preview.direction === "upgrade"
                ? `${formatMoney(preview.proration_paise)} for the rest of this period is added to your next renewal debit. Nothing is charged today.`
                : "You keep your current plan until then. No refund is due for the current period."}
            </p>
          </section>
        ) : null}

        {error ? <ErrorState error={error} title={copy.title} detail={copy.detail} /> : null}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy !== null}>
            Cancel
          </Button>
          {preview ? (
            <Button loading={busy === "confirm"} onClick={() => void confirm()}>
              {preview.direction === "upgrade" ? "Confirm upgrade" : "Confirm downgrade"}
            </Button>
          ) : (
            <Button type="submit" loading={busy === "preview"} disabled={!priceId}>
              Preview change
            </Button>
          )}
        </div>
      </form>
    </Dialog>
  );
}
