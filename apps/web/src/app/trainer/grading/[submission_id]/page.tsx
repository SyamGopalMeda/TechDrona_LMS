import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { GradeSubmission } from "@/features/trainer/components/Grading";

export const metadata: Metadata = { title: "Grade submission" };

/** TRN-009 */
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
  return (
    <div>
      <PageHeader title="Grade submission" eyebrow="TRN-009" />
      <GradeSubmission submissionId={submission_id} assignmentId={assignment} />
    </div>
  );
}
