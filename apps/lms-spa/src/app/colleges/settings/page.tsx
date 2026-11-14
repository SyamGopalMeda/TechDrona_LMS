import type { Metadata } from "next";
import { Settings } from "@/features/colleges/screens/Settings";

export const metadata: Metadata = { title: { absolute: "Settings · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/settings — port of js/views/admin.js renderSettings (old route #/settings). */
export default function Page() {
  return <Settings />;
}
