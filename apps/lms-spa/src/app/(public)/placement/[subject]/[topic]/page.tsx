import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { hasSessionCookie } from "@/lib/api/server";
import { ServerErrorState } from "@/features/catalog/components/CatalogParts";
import { serverLoad } from "@/features/catalog/lib/server";
import { PlacementTopic, findTopic } from "@/features/public/components/PlacementHub";
import type { SubjectsResponse } from "@/features/practice/lib/types";

type Params = Promise<{ subject: string; topic: string }>;

export const metadata: Metadata = { title: "Placement topic" };

/** PUB-005 topic page, resolved from the PLC-01 taxonomy by slug. Unknown slugs are a 404. */
async function Page__server({ params }: { params: Params }) {
  const { subject, topic } = await params;
  const [result, signedIn] = await Promise.all([serverLoad<SubjectsResponse>("placement/subjects"), hasSessionCookie()]);
  if (!result.ok) return <ServerErrorState result={result} retryHref={`/placement/${encodeURIComponent(subject)}/${encodeURIComponent(topic)}`} />;
  const found = findTopic(result.data.items, subject, topic);
  if (!found) notFound();
  return <PlacementTopic subject={found.subject} topic={found.topic} signedIn={signedIn} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/(public)/placement/[subject]/[topic]/page.tsx#Page");
