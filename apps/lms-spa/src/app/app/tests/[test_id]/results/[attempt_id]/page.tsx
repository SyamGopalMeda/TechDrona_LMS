import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { ResultsView } from "@/features/assessment/components/ResultsView";

export const metadata: Metadata = { title: "Results" };

/** STU-010 Results & review (ATT-11, ATT-12). */
async function Page__server({ params }: { params: Promise<{ attempt_id: string }> }) {
  const { attempt_id } = await params;
  return <ResultsView attemptId={attempt_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/app/tests/[test_id]/results/[attempt_id]/page.tsx#Page");
