import type { Metadata } from "next";
import { CallQueue } from "@/features/colleges/screens/CallQueue";

export const metadata: Metadata = { title: { absolute: "Calls & follow-ups · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/calls — port of js/views/calls.js render (old route #/calls). */
export default function Page() {
  return <CallQueue />;
}
