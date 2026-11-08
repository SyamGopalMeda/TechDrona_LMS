import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { CodingProblemEditor } from "@/features/studio/components/Coding";

export const metadata: Metadata = { title: "Coding problem" };

/** CMS-010 */
export default async function Page({ params }: { params: Promise<{ problem_id: string }> }) {
  const { problem_id } = await params;
  return (
    <div>
      <PageHeader title="Coding problem" eyebrow="CMS-010" />
      <CodingProblemEditor problemId={problem_id} />
    </div>
  );
}
