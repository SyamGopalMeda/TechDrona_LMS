import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { TrainerDashboard } from "@/features/trainer/components/TrainerDashboard";

export const metadata: Metadata = { title: "Trainer dashboard" };

/** TRN-001 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Trainer dashboard" eyebrow="TRN-001" />
      <TrainerDashboard />
    </div>
  );
}
