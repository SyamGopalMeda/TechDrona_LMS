import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { TrainerBatchPage } from "@/features/trainer/components/TrainerBatchPage";

export const metadata: Metadata = { title: "Batch" };

/** TRN-002 */
async function Page__server({
  params,
}: {
  params: Promise<{ batch_id: string }>;
}) {
  const { batch_id } = await params;
  return <TrainerBatchPage batchId={batch_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/trainer/batches/[batch_id]/page.tsx#Page");
