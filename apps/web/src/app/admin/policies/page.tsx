import type { Metadata } from "next";
import { PolicySettings } from "@/features/admin/components/PolicySettings";

export const metadata: Metadata = { title: "Policies" };

/** ADM-006 */
export default function Page() {
  return <PolicySettings />;
}
