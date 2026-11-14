import type { Metadata } from "next";
import { GradeSubmission } from "@/features/trainer/components/Grading";

export const metadata: Metadata = { title: "Grade submission" };

/** EVL-002 (reuses TRN-009): GradeSubmission renders the header (breadcrumbs + the student's name). */
export default async function Page({
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
