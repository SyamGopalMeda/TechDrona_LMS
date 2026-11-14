import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { PracticeSession } from "@/features/practice/components/PracticeSession";

export const metadata: Metadata = { title: "Practice session" };

/** PRC-003 Practice session (PLC-20..23). */
async function Page__server({ params }: { params: Promise<{ session_id: string }> }) {
  const { session_id } = await params;
  return <PracticeSession sessionId={session_id} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/practice/sessions/[session_id]/page.tsx#Page");
