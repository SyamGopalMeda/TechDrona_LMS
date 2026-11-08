import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { TestBuilder } from "@/features/studio/components/Tests";

export const metadata: Metadata = { title: "Test builder" };

/** CMS-011 */
export default async function Page({ params }: { params: Promise<{ test_id: string }> }) {
  const { test_id } = await params;
  return (
    <div>
      <PageHeader title="Test builder" eyebrow="CMS-011" />
      <TestBuilder testId={test_id} />
    </div>
  );
}
