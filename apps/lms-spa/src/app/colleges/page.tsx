import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Home · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges — replaces js/views/dashboard.js renderState (old route #/). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Home" />;
}
