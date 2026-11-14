import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { InterviewPrep } from "@/features/dashboard/components/LearnerHubs";

export const metadata: Metadata = { title: "Interview prep" };

/** STU-015 interview prep hub. */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader title="Interview prep" description="Résumé and mock tests." />
      <InterviewPrep />
    </div>
  );
}
