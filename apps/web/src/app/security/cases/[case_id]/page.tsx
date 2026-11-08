import type { Metadata } from "next";
import { CaseDetail } from "@/features/security-admin/components/CaseDetail";

export const metadata: Metadata = { title: "Case" };

/** SEC-003 */
export default async function Page({ params }: { params: Promise<{ case_id: string }> }) {
  const { case_id } = await params;
  return <CaseDetail caseId={case_id} />;
}
