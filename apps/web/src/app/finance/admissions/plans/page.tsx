import type { Metadata } from "next";
import { FeePlans } from "@/features/admissions/components/Admissions";
import { loadCourseTitles } from "@/features/admissions/lib/course-titles";

export const metadata: Metadata = { title: "Fee plans" };

/** ADM-022 fee plans and the "pay to" settings (`?edit=<slug>` opens that course's plan). */
export default async function Page() {
  return <FeePlans titles={await loadCourseTitles()} />;
}
