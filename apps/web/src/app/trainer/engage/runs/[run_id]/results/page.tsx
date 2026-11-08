import type { Metadata } from "next";
import { RunResults } from "@/features/engage/components/RunResults";

export const metadata: Metadata = { title: "Run results" };

/** TRN-023 run results */
export default async function Page({ params }: { params: Promise<{ run_id: string }> }) {
  const { run_id } = await params;
  return <RunResults runId={run_id} />;
}
