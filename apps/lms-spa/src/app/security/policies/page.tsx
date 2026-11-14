import type { Metadata } from "next";
import { PolicySettings } from "@/features/admin/components/PolicySettings";

export const metadata: Metadata = { title: "Security policies" };

/** Security policy namespaces (ADM-07/ADM-09) */
export default function Page() {
  return <PolicySettings namespaces={["risk", "sessions", "devices", "playback", "login", "otp", "unblock", "assessment"]} approvalsHref="/security/approvals" />;
}
