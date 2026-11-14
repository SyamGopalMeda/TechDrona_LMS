import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MentorResumeReviews } from "@/features/mentor/components/ResumeReviews";

export const metadata: Metadata = { title: "Resume reviews" };

/** MEN-005 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Résumé reviews" description="Comment on each section and send a summary back to the student." />
      <MentorResumeReviews />
    </div>
  );
}
