import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AttemptRunner } from "@/features/assessment/components/AttemptRunner";

export const metadata: Metadata = { title: "Resume test" };

/** TST-004 Resume after crash/disconnect. */
async function Page__server({ params }: { params: Promise<{ attempt_id: string }> }) {
  const { attempt_id } = await params;
  return <AttemptRunner attemptId={attempt_id} forceResume />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/app/attempts/[attempt_id]/resume/page.tsx#Page");
