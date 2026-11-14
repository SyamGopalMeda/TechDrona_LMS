import type { Metadata } from "next";
import { ActivityBuilder } from "@/features/engage/components/ActivityBuilder";
import { isActivityType } from "@/features/engage/lib/labels";

export const metadata: Metadata = { title: "New activity" };

/** TRN-020 builder (new). The builder renders the header ("New activity" + the chosen type). */
export default async function Page({ searchParams }: { searchParams: Promise<{ type?: string }> }) {
  const { type } = await searchParams;
  const t = isActivityType(type) ? type : "poll";
  return <ActivityBuilder type={t} />;
}
