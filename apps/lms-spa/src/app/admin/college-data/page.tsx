import type { Metadata } from "next";
import { CollegeDataPortal } from "@/features/college-data/CollegeDataPortal";

export const metadata: Metadata = { title: "College Data Portal" };

/** ADM-015 College Data Portal (embedded same-origin app; see src/lib/college-portal/proxy.ts). */
export default function Page() {
  return <CollegeDataPortal />;
}
