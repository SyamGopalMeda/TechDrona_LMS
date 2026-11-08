import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ActivityBuilder } from "@/features/engage/components/ActivityBuilder";
import { isActivityType, TYPE_LABEL } from "@/features/engage/lib/labels";

export const metadata: Metadata = { title: "New activity" };

/** TRN-020 builder (new) */
export default async function Page({ searchParams }: { searchParams: Promise<{ type?: string }> }) {
  const { type } = await searchParams;
  const t = isActivityType(type) ? type : "poll";
  return (
    <div>
      <PageHeader title={`New ${TYPE_LABEL[t].toLowerCase()}`} eyebrow="TRN-020" />
      <ActivityBuilder type={t} />
    </div>
  );
}
