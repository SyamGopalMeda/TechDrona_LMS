import type { Metadata } from "next";
import { TrainerBatchPage } from "@/features/trainer/components/TrainerBatchPage";

export const metadata: Metadata = { title: "Batch" };

/** TRN-002 */
export default async function Page({
  params,
}: {
  params: Promise<{ batch_id: string }>;
}) {
  const { batch_id } = await params;
  return <TrainerBatchPage batchId={batch_id} />;
}
