import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { ActivityBuilder } from "@/features/engage/components/ActivityBuilder";
import { isActivityType } from "@/features/engage/lib/labels";

export const metadata: Metadata = { title: "New activity" };

/** TRN-020 builder (new). The builder renders the header ("New activity" + the chosen type). */
async function Page__server({ searchParams }: { searchParams: Promise<{ type?: string }> }) {
  const { type } = await searchParams;
  const t = isActivityType(type) ? type : "poll";
  return <ActivityBuilder type={t} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/trainer/engage/new/page.tsx#Page");
