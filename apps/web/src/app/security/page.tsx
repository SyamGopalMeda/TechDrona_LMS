import type { Metadata } from "next";
import { SecurityDashboard } from "@/features/security-admin/components/SecurityDashboard";

export const metadata: Metadata = { title: "Security overview" };

/** Security overview (dashboard). */
export default function Page() {
  return <SecurityDashboard />;
}
