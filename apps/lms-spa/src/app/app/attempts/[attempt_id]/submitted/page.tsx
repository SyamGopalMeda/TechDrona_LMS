import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { SubmittedView } from "@/features/assessment/components/SubmittedView";

export const metadata: Metadata = { title: "Test submitted" };

/** TST-005 Submitted. `?reason=deadline|deadline_offline` is set by the runner on auto-submit. */
async function Page__server({
  params,
  searchParams,
}: {
  params: Promise<{ attempt_id: string }>;
  searchParams: Promise<{ reason?: string }>;
}) {
  const { attempt_id } = await params;
  const { reason } = await searchParams;
  return <SubmittedView attemptId={attempt_id} reason={reason ?? null} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/app/attempts/[attempt_id]/submitted/page.tsx#Page");
