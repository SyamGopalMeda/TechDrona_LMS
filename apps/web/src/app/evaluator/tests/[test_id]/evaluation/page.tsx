import type { Metadata } from "next";
import { ExamEvaluation } from "@/features/assessment/components/ExamEvaluation";
import { TestPageHeader } from "@/features/trainer/components/TestPageHeader";

export const metadata: Metadata = { title: "Evaluation" };

/** Exam evaluation: integrity badges, AI-assisted grading, finalize, publish (D3). */
export default async function Page({ params }: { params: Promise<{ test_id: string }> }) {
  const { test_id } = await params;
  return (
    <div>
      <TestPageHeader testId={test_id} page="evaluation" description="Grade submissions, review integrity events and publish results." />
      <ExamEvaluation testId={test_id} />
    </div>
  );
}
