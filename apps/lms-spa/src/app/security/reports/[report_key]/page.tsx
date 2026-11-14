import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { ReportView } from "@/features/security-admin/components/Reports";

export const metadata: Metadata = { title: "Security report" };

/** Section H report by key (UX-SM-02) */
async function Page__server({ params }: { params: Promise<{ report_key: string }> }) {
  const { report_key } = await params;
  return <ReportView reportKey={report_key} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/security/reports/[report_key]/page.tsx#Page");
