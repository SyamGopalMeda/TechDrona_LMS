import type { Metadata } from "next";
import { CollegePage } from "@/features/colleges/screens/College";

export const metadata: Metadata = { title: { absolute: "College · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/college/:id — port of js/views/college.js render (old route #/college/:id). */
export default function Page() {
  return <CollegePage />;
}
