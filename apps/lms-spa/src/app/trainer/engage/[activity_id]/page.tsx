import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { ControlRoom } from "@/features/engage/components/ControlRoom";

export const metadata: Metadata = { title: "Control room" };

/** TRN-021 control room */
async function Page__server({ params }: { params: Promise<{ activity_id: string }> }) {
  const { activity_id } = await params;
  return <ControlRoom activityId={activity_id} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/trainer/engage/[activity_id]/page.tsx#Page");
