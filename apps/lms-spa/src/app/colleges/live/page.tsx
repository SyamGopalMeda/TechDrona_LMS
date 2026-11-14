import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Official sources · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/live — replaces js/views/live.js renderSources (old route #/live). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Official sources" />;
}
