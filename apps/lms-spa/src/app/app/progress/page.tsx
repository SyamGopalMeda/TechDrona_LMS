import type { Metadata } from "next";
import { ProgressDashboard } from "@/features/progress/components/ProgressDashboard";

export const metadata: Metadata = { title: "Progress" };

/** Student progress: skill analytics and time spent (ANL-04/05, PLC-25). */
export default function Page() {
  return <ProgressDashboard />;
}
