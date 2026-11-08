import type { Metadata } from "next";
import { RuleVersions } from "@/features/security-admin/components/RuleVersions";

export const metadata: Metadata = { title: "Risk rules" };

/** SEC-006 */
export default function Page() {
  return <RuleVersions />;
}
