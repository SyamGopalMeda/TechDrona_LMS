import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Follow-ups · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/followups — replaces js/views/followups.js render (old route #/followups). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Follow-ups" />;
}
