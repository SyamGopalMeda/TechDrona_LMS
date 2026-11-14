import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { safeNextPath } from "@/features/auth/lib/validation";
import { Checkout } from "@/features/commerce/components/Checkout";

export const metadata: Metadata = { title: "Checkout" };

type Search = Promise<Record<string, string | string[] | undefined>>;

/** STU-016 checkout for a price (before an order exists). */
async function Page__server({ searchParams }: { searchParams: Search }) {
  const sp = await searchParams;
  const priceId = typeof sp.price_id === "string" && /^[A-Za-z0-9-]{1,64}$/.test(sp.price_id) ? sp.price_id : null;
  // SEC-04: the hardened validator (rejects tab-smuggled / control-char paths).
  const returnTo = safeNextPath(typeof sp.return_to === "string" ? sp.return_to : null, "") || null;
  return <Checkout priceId={priceId} returnTo={returnTo} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/app/checkout/new/page.tsx#Page");
