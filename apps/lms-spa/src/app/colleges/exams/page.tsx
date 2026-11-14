import type { Metadata } from "next";
import { Exams } from "@/features/colleges/screens/Exams";

export const metadata: Metadata = { title: { absolute: "Exams · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/exams — port of js/views/exams.js render (old route #/exams). */
export default function Page() {
  return <Exams />;
}
