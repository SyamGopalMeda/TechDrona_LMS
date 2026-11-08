import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { TestOverrides } from "@/features/trainer/components/TestOps";

export const metadata: Metadata = { title: "Overrides" };

/** TRN-007 */
export default async function Page({
  params,
}: {
  params: Promise<{ test_id: string }>;
}) {
  const { test_id } = await params;
  return (
    <div>
      <PageHeader
        title="Overrides"
        eyebrow="TRN-007"
        description="Extra time, extra attempts or a window extension. Every override needs a reason and is audited."
      />
      <TestOverrides testId={test_id} />
    </div>
  );
}
