import type { Metadata } from "next";
import { ApprovalsQueue } from "@/features/admin/components/ApprovalsQueue";
import { SECURITY_APPROVAL_TYPES } from "@/features/admin/lib/approval-types";

export const metadata: Metadata = { title: "Security approvals" };

/** Security dual-control queue (ADM-12 filtered to security action types) */
export default function Page() {
  return <ApprovalsQueue title="Security approvals" actionTypes={[...SECURITY_APPROVAL_TYPES]} />;
}
