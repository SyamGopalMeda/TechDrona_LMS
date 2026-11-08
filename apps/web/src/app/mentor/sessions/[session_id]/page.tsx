import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MentorSessionDetail } from "@/features/mentor/components/Mentor";

export const metadata: Metadata = { title: "Session" };

/** MEN-003 */
export default async function Page({ params }: { params: Promise<{ session_id: string }> }) {
  const { session_id } = await params;
  return (
    <div>
      <PageHeader title="Session" eyebrow="MEN-003" />
      <MentorSessionDetail bookingId={session_id} />
    </div>
  );
}
