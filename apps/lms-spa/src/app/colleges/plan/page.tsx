import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Target planner · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/plan — replaces js/views/plan.js render (old route #/plan). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Target planner" />;
}
