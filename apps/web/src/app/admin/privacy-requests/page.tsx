import type { Metadata } from "next";
import { PrivacyRequests } from "@/features/admin/components/Governance";

export const metadata: Metadata = { title: "Privacy requests" };

/** ADM-009 */
export default function Page() {
  return <PrivacyRequests />;
}
