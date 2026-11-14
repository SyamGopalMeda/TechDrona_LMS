import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Targets & performance · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/targets — replaces js/views/targets.js render (old route #/targets). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Targets & performance" />;
}
