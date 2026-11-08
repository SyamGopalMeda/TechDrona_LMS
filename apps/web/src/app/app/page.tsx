import type { Metadata } from "next";
import { StudentDashboard } from "@/features/dashboard/components/StudentDashboard";

export const metadata: Metadata = { title: "Dashboard" };

/** STU-001 */
export default function Page() {
  return <StudentDashboard />;
}
