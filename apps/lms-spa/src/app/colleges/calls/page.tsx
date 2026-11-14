import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Calls & follow-ups · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/calls — replaces js/views/calls.js render (old route #/calls). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Calls & follow-ups" />;
}
