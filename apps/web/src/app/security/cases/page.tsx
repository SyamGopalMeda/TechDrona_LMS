import type { Metadata } from "next";
import { CaseQueue } from "@/features/security-admin/components/CaseQueue";

export const metadata: Metadata = { title: "Cases" };

/** SEC-002 (H1) */
export default function Page() {
  return <CaseQueue />;
}
