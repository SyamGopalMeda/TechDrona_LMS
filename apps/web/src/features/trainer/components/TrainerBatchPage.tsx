"use client";

import { ErrorState, PageHeader, StatusBadge } from "@/components/ui";
import { AnnounceButton } from "@/features/batches/components/AnnounceButton";
import { BatchDetail } from "@/features/batches/components/Batches";
import { BatchPlan } from "@/features/batches/components/BatchPlan";
import { ClassesAttendance } from "@/features/batches/components/ClassesAttendance";
import type { Batch } from "@/features/batches/lib/types";
import { seg, useApi } from "../shared/use-api";
import { formatDate } from "../shared/ui";

/**
 * TRN-002 batch page: the batch name is the h1, and progress is shown once (BatchDetail's
 * "Batch progress" card + members). The separate `BatchProgress` card used to repeat the same
 * report next to it with different labels.
 * Tabs: Overview, "Classes & attendance" (add classes, mark P / L / A on a phone) and the batch's
 * plan (read-only for trainers; Admin edits it).
 */
export function TrainerBatchPage({ batchId }: { batchId: string }) {
  const batch = useApi<Batch>(`batches/${seg(batchId)}`);
  if (batch.error && !batch.data) {
    // Not this trainer's batch (403) or gone (404): one message, not one per card and tab.
    return (
      <div>
        <PageHeader breadcrumbs={[{ label: "Dashboard", href: "/trainer" }, { label: "Batch" }]} title="Batch" />
        <ErrorState error={batch.error} onRetry={() => void batch.reload()} />
      </div>
    );
  }
  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Dashboard", href: "/trainer" }, { label: batch.data?.name ?? "Batch" }]}
        title={batch.data?.name ?? "Batch"}
        meta={batch.data?.status ? <StatusBadge status={batch.data.status} /> : undefined}
        description={
          batch.data
            ? [
                batch.data.code ? `Batch code ${batch.data.code}` : null,
                batch.data.starts_on || batch.data.ends_on ? `${formatDate(batch.data.starts_on)} – ${formatDate(batch.data.ends_on)}` : null,
              ]
                .filter(Boolean)
                .join(" · ") || undefined
            : undefined
        }
        actions={batch.data && batch.data.status !== "archived" ? <AnnounceButton batchId={batchId} batchName={batch.data.name} /> : undefined}
      />
      <BatchDetail
        batchId={batchId}
        showSummary={false}
        tabs={[
          { id: "classes", label: "Classes & attendance", content: <ClassesAttendance batchId={batchId} canManage={batch.data?.status !== "archived"} /> },
          { id: "plan", label: "Plan", content: <BatchPlan batchId={batchId} /> },
        ]}
      />
    </div>
  );
}
