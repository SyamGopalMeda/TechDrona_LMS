import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { GradeSubmission } from "@/features/trainer/components/Grading";

export const metadata: Metadata = { title: "Grade submission" };

/** TRN-009: GradeSubmission renders the header (breadcrumbs + the student's name). */
async function Page__server({
  params,
  searchParams,
}: {
  params: Promise<{ submission_id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { submission_id } = await params;
  const sp = await searchParams;
  const assignment = typeof sp.assignment === "string" ? sp.assignment : null;
  return <GradeSubmission submissionId={submission_id} assignmentId={assignment} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/trainer/grading/[submission_id]/page.tsx#Page");
