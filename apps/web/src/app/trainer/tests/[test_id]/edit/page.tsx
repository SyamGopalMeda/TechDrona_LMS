import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { TestBuilder } from "@/features/studio/components/Tests";

export const metadata: Metadata = { title: "Test builder" };

/** TRN-006 */
export default async function Page({
  params,
}: {
  params: Promise<{ test_id: string }>;
}) {
  const { test_id } = await params;
  return (
    <div>
      <PageHeader title="Test builder" eyebrow="TRN-006" />
      <TestBuilder testId={test_id} />
    </div>
  );
}
