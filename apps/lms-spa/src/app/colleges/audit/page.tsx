import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Audit log · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/audit — replaces js/views/admin.js renderAudit (old route #/audit). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Audit log" />;
}
