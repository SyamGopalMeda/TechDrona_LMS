import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { ActivityBuilder } from "@/features/engage/components/ActivityBuilder";

export const metadata: Metadata = { title: "Edit activity" };

/** TRN-020 builder (edit). The builder renders the header with the activity's name. */
async function Page__server({ params }: { params: Promise<{ activity_id: string }> }) {
  const { activity_id } = await params;
  return <ActivityBuilder activityId={activity_id} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/trainer/engage/[activity_id]/edit/page.tsx#Page");
