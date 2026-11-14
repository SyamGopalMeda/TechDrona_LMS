import type { Metadata } from "next";
import { SystemStatus } from "@/features/admin/components/Governance";

export const metadata: Metadata = { title: "System status" };

/** ADM-023 Settings › System status: outside-service status and advanced tools (live audit 2026-11-14). */
export default function Page() {
  return <SystemStatus />;
}
