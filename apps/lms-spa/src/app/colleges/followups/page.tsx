import type { Metadata } from "next";
import { Followups } from "@/features/colleges/screens/Followups";

export const metadata: Metadata = { title: { absolute: "Follow-ups · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/followups — port of js/views/followups.js render (old route #/followups). */
export default function Page() {
  return <Followups />;
}
