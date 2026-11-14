import type { Metadata } from "next";
import { Person } from "@/features/colleges/screens/Person";

export const metadata: Metadata = { title: { absolute: "Person · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/person/:id — port of js/views/people.js renderPerson (old route #/person/:id). */
export default function Page() {
  return <Person />;
}
