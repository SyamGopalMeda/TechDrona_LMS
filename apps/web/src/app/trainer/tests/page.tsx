import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { TrainerTests } from "@/features/trainer/components/TrainerDashboard";

export const metadata: Metadata = { title: "Tests" };

/** TRN-005 */
export default function Page() {
  return (
    <div>
      <PageHeader
        title="Tests"
        eyebrow="TRN-005"
        description="Assign tests to your batches, grant overrides and follow attempts."
      />
      <TrainerTests />
    </div>
  );
}
