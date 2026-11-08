import type { Metadata } from "next";
import { FeatureFlags } from "@/features/admin/components/Governance";

export const metadata: Metadata = { title: "Feature flags" };

/** ADM-007 */
export default function Page() {
  return <FeatureFlags />;
}
