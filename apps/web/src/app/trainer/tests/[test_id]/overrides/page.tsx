import type { Metadata } from "next";
import { TestOverrides } from "@/features/trainer/components/TestOps";
import { TestPageHeader } from "@/features/trainer/components/TestPageHeader";

export const metadata: Metadata = { title: "Overrides" };

/** TRN-007 */
export default async function Page({ params }: { params: Promise<{ test_id: string }> }) {
  const { test_id } = await params;
  return (
    <div>
      <TestPageHeader
        testId={test_id}
        page="overrides"
        description="Extra time, extra attempts or a window extension. Every override needs a reason and is audited."
      />
      <TestOverrides testId={test_id} />
    </div>
  );
}
