import type { Metadata } from "next";
import { EvaluationView } from "@/features/learning/assignment-manager/EvaluationView";

export const metadata: Metadata = { title: "Evaluate assignment" };

/** Structured assignment evaluation: AI grading, review, publish (no "Edit assignment" here). */
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EvaluationView assignmentId={decodeURIComponent(id)} />;
}
