import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Team · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/people — replaces js/views/people.js renderList (old route #/people). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Team" />;
}
