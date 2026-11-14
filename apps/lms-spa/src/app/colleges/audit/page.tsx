import type { Metadata } from "next";
import { AuditLog } from "@/features/colleges/screens/AuditLog";

export const metadata: Metadata = { title: { absolute: "Audit log · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/audit — port of js/views/admin.js renderAudit (old route #/audit). */
export default function Page() {
  return <AuditLog />;
}
