import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { Presenter } from "@/features/engage/components/Presenter";

export const metadata: Metadata = { title: "Present" };

/** TRN-022 big screen */
async function Page__server({ params }: { params: Promise<{ run_id: string }> }) {
  const { run_id } = await params;
  return <Presenter runId={run_id} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/trainer/engage/runs/[run_id]/present/page.tsx#Page");
