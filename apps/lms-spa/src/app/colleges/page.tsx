import type { Metadata } from "next";
import { Home } from "@/features/colleges/screens/Home";

export const metadata: Metadata = { title: { absolute: "Home · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges — port of js/views/dashboard.js renderState (old route #/). */
export default function Page() {
  return <Home />;
}
