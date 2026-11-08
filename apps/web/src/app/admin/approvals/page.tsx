import type { Metadata } from "next";
import { ApprovalsQueue } from "@/features/admin/components/ApprovalsQueue";

export const metadata: Metadata = { title: "Approvals" };

/** ADM-010 */
export default function Page() {
  return <ApprovalsQueue />;
}
