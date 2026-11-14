import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { GradingQueue } from "@/features/trainer/components/Grading";

export const metadata: Metadata = { title: "Grading" };

/** TRN-008: every assignment with its waiting submissions, most work first. */
export default function Page() {
  return (
    <div>
      <PageHeader title="Grading" eyebrow="TRN-008" description="Assignments with submissions waiting, most work first. Grade, then release results." />
      <GradingQueue />
    </div>
  );
}
