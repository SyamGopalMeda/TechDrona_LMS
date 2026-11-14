import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Exams · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/exams — replaces js/views/exams.js render (old route #/exams). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Exams" />;
}
