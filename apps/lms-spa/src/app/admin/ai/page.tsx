import type { Metadata } from "next";
import { AIAdmin } from "@/features/ai";

export const metadata: Metadata = { title: "Apps" };

/** ADM-003 Apps: platform-wide authorized apps (the AI settings and Usage tabs were removed). */
export default function Page() {
  return <AIAdmin />;
}
