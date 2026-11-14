import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { QuestionReportQueue } from "@/features/studio/components/QuestionReports";

export const metadata: Metadata = { title: "Reported errors" };

/** CMS-013 reported-error triage queue (PLC-34/35). */
export default function Page() {
  return (
    <div>
      <PageHeader title="Reported errors" eyebrow="CMS-013" description="Errors learners reported in practice questions. Resolving a report notifies the reporter." />
      <QuestionReportQueue />
    </div>
  );
}
