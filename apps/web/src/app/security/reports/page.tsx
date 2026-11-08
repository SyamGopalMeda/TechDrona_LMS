import type { Metadata } from "next";
import { ReportsIndex } from "@/features/security-admin/components/Reports";

export const metadata: Metadata = { title: "Security reports" };

/** Section H report catalogue (UX-SM-02) */
export default function Page() {
  return <ReportsIndex />;
}
