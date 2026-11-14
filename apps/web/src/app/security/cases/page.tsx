import type { Metadata } from "next";
import { CaseQueue } from "@/features/security-admin/components/CaseQueue";

export const metadata: Metadata = { title: "Cases" };

/** Security case queue. */
export default function Page() {
  return <CaseQueue />;
}
