import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ExamEvaluation } from "@/features/assessment/components/ExamEvaluation";

export const metadata: Metadata = { title: "Evaluation" };

/** Exam evaluation: integrity badges, AI-assisted grading (suggestions), finalize, publish. */
export default async function Page({ params }: { params: Promise<{ test_id: string }> }) {
  const { test_id } = await params;
  return (
    <div>
      <PageHeader title="Evaluation" description="Grade submissions, review integrity events and publish results." />
      <ExamEvaluation testId={test_id} />
    </div>
  );
}
