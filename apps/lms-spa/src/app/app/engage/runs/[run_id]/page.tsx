import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { LiveRun } from "@/features/engage/components/LiveRun";

export const metadata: Metadata = { title: "Live activity" };

/** STU-032 */
async function Page__server({
  params,
  searchParams,
}: {
  params: Promise<{ run_id: string }>;
  searchParams: Promise<{ code?: string }>;
}) {
  const { run_id } = await params;
  const { code } = await searchParams;
  return <LiveRun runId={run_id} code={typeof code === "string" ? code : undefined} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/engage/runs/[run_id]/page.tsx#Page");
