"use client";

import { useId, useState } from "react";
import { formatMoney, humanize } from "../lib/format";
import { currentPrice } from "../lib/products";
import type { PlanDto, ProductDto, ProductUnlockDto } from "../lib/types";
import { LinkButton } from "./LinkButton";
import { SafeMarkdown } from "./SafeMarkdown";

type Interval = "month" | "year";

const FREE_KINDS = new Set(["free_resource", "free_course"]);

function pickPlan(product: ProductDto, interval: Interval): PlanDto | null {
  const priced = product.plans.filter((p) => currentPrice(p));
  const recurring = priced.filter((p) => p.billing_type === "recurring");
  if (recurring.length) return recurring.find((p) => p.interval_unit === interval) ?? recurring[0] ?? null;
  return priced[0] ?? null;
}

function cadence(plan: PlanDto): string {
  if (plan.billing_type === "recurring") {
    const n = plan.interval_count && plan.interval_count > 1 ? `${plan.interval_count} ` : "";
    return `/${n}${plan.interval_unit === "year" ? "year" : "month"}${n ? "s" : ""}`;
  }
  if (plan.access_duration_days) return ` for ${plan.access_duration_days} days`;
  return "";
}

/** product_json `unlocks[]` as readable lines: features by key, other items counted by type. */
function unlockLines(unlocks: ProductUnlockDto[] | undefined): string[] {
  const counts = new Map<string, number>();
  const lines: string[] = [];
  for (const u of unlocks ?? []) {
    if (u.item_type === "feature" && u.feature_key) lines.push(humanize(u.feature_key));
    else counts.set(u.item_type, (counts.get(u.item_type) ?? 0) + 1);
  }
  for (const [type, n] of counts) lines.push(`${n} ${humanize(type).toLowerCase()}${n > 1 ? "s" : ""}`);
  return lines;
}

/** PUB-008 plan cards. All prices from COM-01 (GST-inclusive current prices; no sale/list price is returned). */
export function PricingPlans({ products, signedIn }: { products: ProductDto[]; signedIn: boolean }) {
  const hasToggle = products.some((p) => {
    const ints = new Set(p.plans.filter((pl) => pl.billing_type === "recurring" && currentPrice(pl)).map((pl) => pl.interval_unit));
    return ints.has("month") && ints.has("year");
  });
  const [interval, setInterval] = useState<Interval>("year");
  const groupId = useId();
  const refundRule = products.find((p) => p.refund_rule)?.refund_rule;

  return (
    <div className="space-y-6">
      {hasToggle ? (
        <fieldset className="flex flex-wrap items-center gap-4">
          <legend className="sr-only">Billing period</legend>
          <span className="text-sm font-medium text-fg" aria-hidden="true">
            Billing:
          </span>
          {(["month", "year"] as const).map((v) => (
            <label key={v} className="inline-flex items-center gap-2 text-sm text-fg">
              <input type="radio" name={groupId} value={v} checked={interval === v} onChange={() => setInterval(v)} className="h-4 w-4 accent-brand" />
              {v === "month" ? "Monthly" : "Annual"}
            </label>
          ))}
        </fieldset>
      ) : null}

      <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-4" aria-label="Plans">
        {products.map((product) => {
          const plan = pickPlan(product, interval);
          const free = FREE_KINDS.has(product.product_kind);
          const price = plan ? currentPrice(plan) : null;
          const checkout = price ? `/app/checkout/new?price_id=${encodeURIComponent(price.price_id)}&return_to=%2Fpricing` : null;
          const unlocks = unlockLines(product.unlocks);
          return (
            <li key={product.sku}>
              <article className="flex h-full flex-col rounded-xl border border-line bg-surface p-5 shadow-xs">
                <div className="flex items-start justify-between gap-2">
                  <h2 className="font-display text-lg font-semibold text-fg">{product.name}</h2>
                </div>
                <p className="mt-2 font-display text-2xl font-bold tabular-nums text-fg">
                  {free ? formatMoney(0) : price ? formatMoney(price.amount_paise) : "—"}
                  {plan && !free ? <span className="text-sm font-normal text-fg-muted">{cadence(plan)}</span> : null}
                </p>
                {!free && price ? <p className="text-xs text-fg-muted">incl. GST</p> : null}
                {product.description_md ? <SafeMarkdown source={product.description_md} className="mt-3 space-y-2 text-sm text-fg-secondary" /> : null}
                {unlocks.length ? (
                  <ul className="mt-3 space-y-1 text-sm text-fg-secondary">
                    {unlocks.map((u) => (
                      <li key={u}>
                        <span aria-hidden="true">✓ </span>
                        {u}
                      </li>
                    ))}
                  </ul>
                ) : null}
                <div className="mt-auto pt-5">
                  {free ? (
                    <LinkButton href={signedIn ? "/courses?price_type=free" : "/signup"} variant="secondary" className="w-full">
                      Start free
                    </LinkButton>
                  ) : checkout ? (
                    <LinkButton href={signedIn ? checkout : `/login?next=${encodeURIComponent(checkout)}`} className="w-full">
                      Get {product.name}
                    </LinkButton>
                  ) : (
                    <p className="text-sm text-fg-muted">Not on sale right now.</p>
                  )}
                  {plan?.billing_type === "recurring" && !free ? (
                    <p className="mt-2 text-xs text-fg-muted">Renews automatically. Cancel any time in one click.</p>
                  ) : null}
                </div>
              </article>
            </li>
          );
        })}
      </ul>
      {refundRule ? (
        <p className="rounded-lg border border-line bg-surface p-4 text-sm text-fg-secondary">
          <strong className="text-fg">Refund rule:</strong> {refundRule}
        </p>
      ) : null}
    </div>
  );
}
