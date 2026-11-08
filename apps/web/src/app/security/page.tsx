import type { Metadata } from "next";
import { SecurityDashboard } from "@/features/security-admin/components/SecurityDashboard";

export const metadata: Metadata = { title: "Account security" };

/** SEC-001 */
export default function Page() {
  return <SecurityDashboard />;
}
