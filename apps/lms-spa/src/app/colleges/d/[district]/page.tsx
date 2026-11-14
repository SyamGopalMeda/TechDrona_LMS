import type { Metadata } from "next";
import { District } from "@/features/colleges/screens/District";

export const metadata: Metadata = { title: { absolute: "District · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/d/:district — district page (old js/views/geo.js renderDistrict, route #/d/:district). */
export default function Page() {
  return <District />;
}
