import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { TestReportView } from "@/features/trainer/components/TestOps";
import { TestPageHeader } from "@/features/trainer/components/TestPageHeader";

export const metadata: Metadata = { title: "Test report" };

/** Test report (TRN-011): score distribution, item analysis and result release. */
async function Page__server({ params }: { params: Promise<{ test_id: string }> }) {
  const { test_id } = await params;
  return (
    <div>
      <TestPageHeader testId={test_id} page="report" description="How the batch scored, and releasing results to students." />
      <TestReportView testId={test_id} />
    </div>
  );
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/trainer/tests/[test_id]/report/page.tsx#Page");
