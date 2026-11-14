import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { MentorSessionDetail } from "@/features/mentor/components/Mentor";

export const metadata: Metadata = { title: "Session" };

/** MEN-003 */
async function Page__server({ params }: { params: Promise<{ session_id: string }> }) {
  const { session_id } = await params;
  return <MentorSessionDetail bookingId={session_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/mentor/sessions/[session_id]/page.tsx#Page");
