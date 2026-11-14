import type { Metadata } from "next";
import { Targets } from "@/features/colleges/screens/Targets";

export const metadata: Metadata = { title: { absolute: "Targets & performance · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/targets — port of js/views/targets.js render (old route #/targets, ?tab=places). */
export default function Page() {
  return <Targets />;
}
