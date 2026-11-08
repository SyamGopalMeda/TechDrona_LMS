import type { Metadata } from "next";
import { ControlRoom } from "@/features/engage/components/ControlRoom";

export const metadata: Metadata = { title: "Control room" };

/** TRN-021 control room */
export default async function Page({ params }: { params: Promise<{ activity_id: string }> }) {
  const { activity_id } = await params;
  return <ControlRoom activityId={activity_id} />;
}
