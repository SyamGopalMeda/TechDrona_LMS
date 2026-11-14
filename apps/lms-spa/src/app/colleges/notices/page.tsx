import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Official notices · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/notices — replaces js/views/live.js renderNotices (old route #/notices). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Official notices" />;
}
