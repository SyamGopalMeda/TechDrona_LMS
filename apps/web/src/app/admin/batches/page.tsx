import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { BatchList } from "@/features/batches/components/Batches";

export const metadata: Metadata = { title: "Batches" };

/** ADM-013 batches (cohorts), managed by Admin (single-company plan §3). */
export default function Page() {
  return (
    <div>
      <PageHeader title="Batches" eyebrow="ADM-013" description="Create cohorts, add students and assign trainers and evaluators." />
      <BatchList />
    </div>
  );
}
