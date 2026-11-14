import type { Metadata } from "next";
import { ComingInThePort } from "@/features/colleges/shell/Placeholder";

export const metadata: Metadata = { title: { absolute: "Data quality · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/data — replaces js/views/admin.js renderData (old route #/data). Placeholder until ported. */
export default function Page() {
  return <ComingInThePort title="Data quality" />;
}
