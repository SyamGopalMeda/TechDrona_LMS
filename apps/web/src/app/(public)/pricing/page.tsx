import type { Metadata } from "next";
import { EmptyState, PageHeader } from "@/components/ui";
import { hasSessionCookie } from "@/lib/api/server";
import { ServerErrorState } from "@/features/catalog/components/CatalogParts";
import { PricingPlans } from "@/features/catalog/components/PricingPlans";
import { serverLoad } from "@/features/catalog/lib/server";
import type { Paged, ProductDto } from "@/features/catalog/lib/types";

export const metadata: Metadata = { title: "Pricing", description: "Plans and prices. Prices include 18% GST." };

/** PUB-008 pricing (COM-01). Prices come from the api only; nothing is hard-coded. */
export default async function Page() {
  const [result, signedIn] = await Promise.all([serverLoad<Paged<ProductDto>>("commerce/products"), hasSessionCookie()]);
  return (
    <div className="space-y-6">
      <PageHeader title="Pricing" description="Prices include 18% GST. The price you see here is the price you pay at checkout." />
      {!result.ok ? (
        <ServerErrorState result={result} retryHref="/pricing" />
      ) : result.data.data.length === 0 ? (
        <EmptyState title="No plans on sale right now" description="Free courses and the free diagnostic are always available." />
      ) : (
        <PricingPlans products={result.data.data} signedIn={signedIn} />
      )}
    </div>
  );
}
