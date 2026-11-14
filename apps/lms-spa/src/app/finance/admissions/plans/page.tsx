import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { FeePlans } from "@/features/admissions/components/Admissions";
import { loadCourseTitles } from "@/features/admissions/lib/course-titles";

export const metadata: Metadata = { title: "Fee plans" };

/** ADM-022 fee plans and the "pay to" settings (`?edit=<slug>` opens that course's plan). */
async function Page__server() {
  return <FeePlans titles={await loadCourseTitles()} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/finance/admissions/plans/page.tsx#Page");
