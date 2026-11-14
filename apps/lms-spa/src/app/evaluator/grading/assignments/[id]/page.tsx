import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { EvaluationView } from "@/features/learning/assignment-manager/EvaluationView";

export const metadata: Metadata = { title: "Evaluate assignment" };

/** Structured assignment evaluation: AI grading, review, publish (no "Edit assignment" here). */
async function Page__server({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EvaluationView assignmentId={decodeURIComponent(id)} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/evaluator/grading/assignments/[id]/page.tsx#Page");
