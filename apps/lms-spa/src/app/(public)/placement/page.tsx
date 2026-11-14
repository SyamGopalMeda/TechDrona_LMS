import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { hasSessionCookie } from "@/lib/api/server";
import { ServerErrorState } from "@/features/catalog/components/CatalogParts";
import { serverLoad } from "@/features/catalog/lib/server";
import { PlacementHub } from "@/features/public/components/PlacementHub";
import type { SubjectsResponse } from "@/features/practice/lib/types";

export const metadata: Metadata = { title: "Placement preparation", description: "Aptitude, reasoning, verbal, programming and DSA topics for campus placement drives." };

/** PUB-004 placement hub (PLC-01). */
async function Page__server() {
  const [result, signedIn] = await Promise.all([serverLoad<SubjectsResponse>("placement/subjects"), hasSessionCookie()]);
  if (!result.ok) return <ServerErrorState result={result} retryHref="/placement" />;
  return <PlacementHub subjects={result.data.items} signedIn={signedIn} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/placement/page.tsx#Page");
