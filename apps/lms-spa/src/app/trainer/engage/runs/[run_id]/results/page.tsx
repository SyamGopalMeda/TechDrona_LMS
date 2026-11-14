import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { RunResults } from "@/features/engage/components/RunResults";

export const metadata: Metadata = { title: "Run results" };

/** TRN-023 run results */
async function Page__server({ params }: { params: Promise<{ run_id: string }> }) {
  const { run_id } = await params;
  return <RunResults runId={run_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/trainer/engage/runs/[run_id]/results/page.tsx#Page");
