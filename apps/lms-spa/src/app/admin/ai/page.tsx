import type { Metadata } from "next";
import { AIAdmin } from "@/features/ai";

export const metadata: Metadata = { title: "AI & apps" };

/** ADM-003 platform AI settings, authorized apps and usage (was per-organization). */
export default function Page() {
  return <AIAdmin />;
}
