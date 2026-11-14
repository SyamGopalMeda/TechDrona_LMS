import type { Metadata } from "next";
import { DashboardHero } from "@/components/ui";
import { GradingQueue } from "@/features/trainer/components/Grading";

export const metadata: Metadata = { title: "Grading" };

/** EVL-001 grading queue (reuses TRN-008). */
export default function Page() {
  return (
    <div>
      <DashboardHero title="Grading" description="Assignments with submissions waiting, most work first. Grade, then publish results." />
      <GradingQueue />
    </div>
  );
}
