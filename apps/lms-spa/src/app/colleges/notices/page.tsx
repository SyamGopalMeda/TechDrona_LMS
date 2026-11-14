import type { Metadata } from "next";
import { Notices } from "@/features/colleges/screens/Notices";

export const metadata: Metadata = { title: { absolute: "Official notices · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/notices — port of js/views/live.js renderNotices (old route #/notices). */
export default function Page() {
  return <Notices />;
}
