import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { TestReportView } from "@/features/trainer/components/TestOps";

export const metadata: Metadata = { title: "Test report" };

/** Test report (reuses TRN-011). */
export default async function Page({ params }: { params: Promise<{ test_id: string }> }) {
  const { test_id } = await params;
  return (
    <div>
      <PageHeader title="Test report" eyebrow="Evaluator" />
      <TestReportView testId={test_id} />
    </div>
  );
}
