import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Town · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/d/:district/:city — replaces js/views/geo.js renderCity (old route #/d/:district/:city). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Town" />;
}
