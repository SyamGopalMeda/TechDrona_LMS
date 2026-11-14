import type { Metadata } from "next";
import { CollegeList } from "@/features/colleges/screens/CollegeList";

export const metadata: Metadata = { title: { absolute: "Colleges · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** /colleges/colleges — the colleges list (old js/views/dashboard.js renderCollegeList, route #/colleges). */
export default function Page() {
  return <CollegeList />;
}
