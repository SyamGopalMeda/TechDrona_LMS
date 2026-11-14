import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AdminBatchDetail } from "@/features/batches/components/Batches";

export const metadata: Metadata = { title: "Batch" };

/** ADM-014 batch detail: members, trainers / evaluators, progress (header with breadcrumbs + the batch name as h1). */
async function Page__server({ params }: { params: Promise<{ batch_id: string }> }) {
  const { batch_id } = await params;
  return <AdminBatchDetail batchId={decodeURIComponent(batch_id)} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/admin/batches/[batch_id]/page.tsx#Page");
