import type { Metadata } from "next";
import { DataQuality } from "@/features/colleges/screens/DataQuality";

export const metadata: Metadata = { title: { absolute: "Data quality · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/data — port of js/views/admin.js renderData (old route #/data). */
export default function Page() {
  return <DataQuality />;
}
