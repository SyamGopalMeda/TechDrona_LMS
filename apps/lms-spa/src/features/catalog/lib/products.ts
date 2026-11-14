import type { AccessOptionDto, PlanDto, PriceDto, ProductDto } from "./types";

/** COM-01 returns only current prices; prefer the active one. Amounts are GST-inclusive paise. */
export function currentPrice(plan: PlanDto): PriceDto | null {
  return plan.prices.find((p) => p.is_active) ?? plan.prices[0] ?? null;
}

/** Products whose `unlocks` include this course (product_json item_type "course", ref_id = course id). */
export function accessOptionsForCourse(products: ProductDto[], courseId: string): AccessOptionDto[] {
  const out: AccessOptionDto[] = [];
  for (const product of products) {
    if (!product.unlocks?.some((u) => u.item_type === "course" && u.ref_id === courseId)) continue;
    for (const plan of product.plans) {
      const price = currentPrice(plan);
      if (!price) continue;
      out.push({
        sku: product.sku,
        price_id: price.price_id,
        name: product.name,
        product_kind: product.product_kind,
        total_paise: price.amount_paise,
        access_days: plan.access_duration_days,
        interval: plan.billing_type === "recurring" ? plan.interval_unit : null,
      });
    }
  }
  return out;
}
