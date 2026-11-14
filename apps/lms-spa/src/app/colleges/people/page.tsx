import type { Metadata } from "next";
import { People } from "@/features/colleges/screens/People";

export const metadata: Metadata = { title: { absolute: "Team · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/people — port of js/views/people.js renderList (old route #/people). */
export default function Page() {
  return <People />;
}
