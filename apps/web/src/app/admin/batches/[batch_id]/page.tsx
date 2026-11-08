import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { AdminBatchDetail } from "@/features/batches/components/Batches";

export const metadata: Metadata = { title: "Batch" };

/** ADM-014 batch detail: members, trainers / evaluators, progress. */
export default async function Page({ params }: { params: Promise<{ batch_id: string }> }) {
  const { batch_id } = await params;
  return (
    <div>
      <PageHeader title="Batch" eyebrow="ADM-014" />
      <p className="mb-4 text-sm">
        <Link href="/admin/batches" className="text-fg-link underline">
          All batches
        </Link>
      </p>
      <AdminBatchDetail batchId={decodeURIComponent(batch_id)} />
    </div>
  );
}
