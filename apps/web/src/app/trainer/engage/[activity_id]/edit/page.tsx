import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ActivityBuilder } from "@/features/engage/components/ActivityBuilder";

export const metadata: Metadata = { title: "Edit activity" };

/** TRN-020 builder (edit) */
export default async function Page({ params }: { params: Promise<{ activity_id: string }> }) {
  const { activity_id } = await params;
  return (
    <div>
      <PageHeader title="Edit activity" eyebrow="TRN-020" />
      <ActivityBuilder activityId={activity_id} />
    </div>
  );
}
