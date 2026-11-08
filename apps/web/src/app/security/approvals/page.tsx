import type { Metadata } from "next";
import { ApprovalsQueue } from "@/features/admin/components/ApprovalsQueue";

export const metadata: Metadata = { title: "Security approvals" };

/** Security dual-control queue (ADM-12 filtered to security action types) */
export default function Page() {
  return <ApprovalsQueue eyebrow="SEC · Dual control" title="Security approvals" actionTypes={["security.export.per_user", "security.restriction.bulk_lift", "risk.kill_switch.ratify"]} />;
}
