import type { Metadata } from "next";
import { EvaluationView } from "@/features/learning/assignment-manager/EvaluationView";

export const metadata: Metadata = { title: "Evaluate assignment" };

/** Evaluation of a structured assignment: AI grading, review, publish, modification requests. */
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EvaluationView assignmentId={decodeURIComponent(id)} />;
}
