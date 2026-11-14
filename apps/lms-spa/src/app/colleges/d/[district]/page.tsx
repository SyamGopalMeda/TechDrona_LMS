import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "District · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/d/:district — replaces js/views/geo.js renderDistrict (old route #/d/:district). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="District" />;
}
