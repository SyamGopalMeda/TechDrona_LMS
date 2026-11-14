import type { Metadata } from "next";
import { AdmissionsOverview } from "@/features/admissions/components/Admissions";
import { loadCourseTitles } from "@/features/admissions/lib/course-titles";

export const metadata: Metadata = { title: "Admissions" };

/** ADM-019 admissions: course registration status (open / coming soon / closed), figures, activity. */
export default async function Page() {
  return <AdmissionsOverview titles={await loadCourseTitles()} />;
}
