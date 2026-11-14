import type { Metadata } from "next";
import { TrainerDashboard } from "@/features/trainer/components/TrainerDashboard";

export const metadata: Metadata = { title: "Trainer dashboard" };

/** TRN-001 */
export default function Page() {
  return (
    <TrainerDashboard />
  );
}
