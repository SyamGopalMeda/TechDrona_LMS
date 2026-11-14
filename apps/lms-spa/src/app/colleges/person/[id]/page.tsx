import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Person · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/person/:id — replaces js/views/people.js renderPerson (old route #/person/:id). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Person" />;
}
