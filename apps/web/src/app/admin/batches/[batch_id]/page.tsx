import type { Metadata } from "next";
import { AdminBatchDetail } from "@/features/batches/components/Batches";

export const metadata: Metadata = { title: "Batch" };

/** ADM-014 batch detail: members, trainers / evaluators, progress (header with breadcrumbs + the batch name as h1). */
export default async function Page({ params }: { params: Promise<{ batch_id: string }> }) {
  const { batch_id } = await params;
  return <AdminBatchDetail batchId={decodeURIComponent(batch_id)} />;
}
