import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { CaseDetail } from "@/features/security-admin/components/CaseDetail";

export const metadata: Metadata = { title: "Case" };

/** SEC-003 */
async function Page__server({ params }: { params: Promise<{ case_id: string }> }) {
  const { case_id } = await params;
  return <CaseDetail caseId={case_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/security/cases/[case_id]/page.tsx#Page");
