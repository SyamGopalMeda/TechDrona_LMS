import type { Metadata } from "next";
import { AuditLog } from "@/features/admin/components/Governance";

export const metadata: Metadata = { title: "Audit log" };

/** ADM-008 */
export default function Page() {
  return <AuditLog />;
}
