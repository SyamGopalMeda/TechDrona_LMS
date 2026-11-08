import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { IntegrityReview } from "@/features/trainer/components/Grading";

export const metadata: Metadata = { title: "Integrity flags" };

/** Integrity review (reuses TRN-010). */
export default function Page() {
  return (
    <div>
      <PageHeader title="Integrity flags" eyebrow="Evaluator" />
      <IntegrityReview />
    </div>
  );
}
