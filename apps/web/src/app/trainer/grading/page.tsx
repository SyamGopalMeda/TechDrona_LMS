import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { GradingQueue } from "@/features/trainer/components/Grading";
import { StructuredEvaluationLinks } from "@/features/learning/assignment-manager/AssignmentManagerList";

export const metadata: Metadata = { title: "Grading" };

/** TRN-008 */
export default function Page() {
  return (
    <div className="space-y-6">
      <PageHeader title="Grading" eyebrow="TRN-008" />
      <StructuredEvaluationLinks />
      <GradingQueue />
    </div>
  );
}
