import type { Metadata } from "next";
import { ReportView } from "@/features/security-admin/components/Reports";

export const metadata: Metadata = { title: "Security report" };

/** Section H report by key (UX-SM-02) */
export default async function Page({ params }: { params: Promise<{ report_key: string }> }) {
  const { report_key } = await params;
  return <ReportView reportKey={report_key} />;
}
