import type { Metadata } from "next";
import { AdminDashboard } from "@/features/admin/components/Governance";

export const metadata: Metadata = { title: "Platform admin" };

/** ADM-001 */
export default function Page() {
  return <AdminDashboard />;
}
