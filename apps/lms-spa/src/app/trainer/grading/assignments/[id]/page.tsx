import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { EvaluationView } from "@/features/learning/assignment-manager/EvaluationView";

export const metadata: Metadata = { title: "Evaluate assignment" };

/** Evaluation of a structured assignment: AI grading, review, publish, modification requests. */
async function Page__server({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EvaluationView assignmentId={decodeURIComponent(id)} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/trainer/grading/assignments/[id]/page.tsx#Page");
