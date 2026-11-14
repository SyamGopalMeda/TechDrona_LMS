import type { Metadata } from "next";
import { TrainerTests } from "@/features/trainer/components/TrainerDashboard";

export const metadata: Metadata = { title: "Tests" };

/** TRN-005: the list renders its own PageHeader so "New test" can sit in the header actions. */
export default function Page() {
  return <TrainerTests />;
}
