import type { Metadata } from "next";
import { LiveSources } from "@/features/colleges/screens/LiveSources";

export const metadata: Metadata = { title: { absolute: "Official sources · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/live — port of js/views/live.js renderSources (old route #/live). */
export default function Page() {
  return <LiveSources />;
}
