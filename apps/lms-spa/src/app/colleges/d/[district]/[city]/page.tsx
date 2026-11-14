import type { Metadata } from "next";
import { Town } from "@/features/colleges/screens/Town";

export const metadata: Metadata = { title: { absolute: "Town · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/d/:district/:city — town page (old js/views/geo.js renderCity, route #/d/:district/:city). */
export default function Page() {
  return <Town />;
}
