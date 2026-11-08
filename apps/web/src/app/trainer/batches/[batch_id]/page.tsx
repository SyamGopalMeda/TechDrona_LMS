import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { BatchDetail } from "@/features/batches/components/Batches";
import { BatchProgress } from "@/features/trainer/components/Insights";

export const metadata: Metadata = { title: "Batch" };

/** TRN-002 */
export default async function Page({
  params,
}: {
  params: Promise<{ batch_id: string }>;
}) {
  const { batch_id } = await params;
  return (
    <div>
      <PageHeader title="Batch" eyebrow="TRN-002" />
      <div className="space-y-6">
        <BatchDetail batchId={batch_id} />
        <BatchProgress batchId={batch_id} />
      </div>
    </div>
  );
}
