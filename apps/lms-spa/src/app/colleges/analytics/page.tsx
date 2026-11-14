import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Reports · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/analytics — replaces js/views/dashboard.js renderAnalytics (old route #/analytics). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Reports" />;
}
