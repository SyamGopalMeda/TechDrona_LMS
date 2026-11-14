import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AdmissionsOverview } from "@/features/admissions/components/Admissions";
import { loadCourseTitles } from "@/features/admissions/lib/course-titles";

export const metadata: Metadata = { title: "Admissions" };

/** ADM-019 admissions: course registration status (open / coming soon / closed), figures, activity. */
async function Page__server() {
  return <AdmissionsOverview titles={await loadCourseTitles()} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/finance/admissions/page.tsx#Page");
