import type { Metadata } from "next";
import { Reports } from "@/features/colleges/screens/Reports";

export const metadata: Metadata = { title: { absolute: "Reports · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/analytics — port of js/views/dashboard.js renderAnalytics (old route #/analytics). */
export default function Page() {
  return <Reports />;
}
