import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { ContentDocView } from "@/features/public/components/ContentDoc";
import { REFUND_POLICY } from "@/features/public/content/legal";
import { serverLoad } from "@/features/catalog/lib/server";
import type { Paged, ProductDto } from "@/features/catalog/lib/types";

export const metadata: Metadata = { title: REFUND_POLICY.title, description: REFUND_POLICY.summary };

/**
 * PUB-018 refund policy. Also shows the refund rule exactly as the api returns it for products
 * on sale (COM-01 `refund_rule`), which is the text checkout shows (FR-COM-008 "same text").
 */
async function Page__server() {
  const products = await serverLoad<Paged<ProductDto>>("commerce/products");
  const rules = products.ok ? [...new Set(products.data.data.map((p) => p.refund_rule).filter((r): r is string => Boolean(r)))] : [];
  return (
    <ContentDocView doc={REFUND_POLICY} kind="policy">
      {rules.length ? (
        <section aria-labelledby="sec-checkout-rule" className="space-y-2 rounded-lg border border-line bg-surface p-4">
          <h2 id="sec-checkout-rule" className="font-display text-lg font-semibold text-fg">
            The rule as shown at checkout
          </h2>
          {rules.map((r) => (
            <p key={r} className="text-sm text-fg-secondary">
              {r}
            </p>
          ))}
        </section>
      ) : null}
    </ContentDocView>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/legal/refund-policy/page.tsx#Page");
