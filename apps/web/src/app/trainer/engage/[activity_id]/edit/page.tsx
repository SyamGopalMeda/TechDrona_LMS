import type { Metadata } from "next";
import { ActivityBuilder } from "@/features/engage/components/ActivityBuilder";

export const metadata: Metadata = { title: "Edit activity" };

/** TRN-020 builder (edit). The builder renders the header with the activity's name. */
export default async function Page({ params }: { params: Promise<{ activity_id: string }> }) {
  const { activity_id } = await params;
  return <ActivityBuilder activityId={activity_id} />;
}
