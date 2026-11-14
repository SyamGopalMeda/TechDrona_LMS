import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "College · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/college/:id — replaces js/views/college.js render (old route #/college/:id). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="College" />;
}
