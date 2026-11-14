import { asyncComponent } from "@/spa/async";
import { buttonClasses } from "@/components/ui/Button";
import { Icon } from "@/components/ui";
import { useResource } from "@/lib/api/use-resource";
import type { CourseStatusRow } from "@/features/admissions/lib/admissions";
import { loadSiteCatalog } from "../lib/server";
import type { SiteCatalog } from "../lib/types";
import { SiteCourseSections } from "./SiteCourseSections";

/**
 * The cards with admin actions. The fee-plan state comes from the Admissions course list
 * (`GET admin/courses/status`, once for the section); until it loads, or if it fails, the cards
 * just leave out the "No active fee plan" note.
 */
export function SiteCatalogAdminCourses({ catalog }: { catalog: SiteCatalog }) {
  const res = useResource<{ data: CourseStatusRow[] }>(catalog.courses.length ? "admin/courses/status" : null);
  const planActive = res.data ? Object.fromEntries(res.data.data.map((r) => [r.course_slug, r.plan_active])) : undefined;
  return <SiteCourseSections catalog={catalog} variant="compact" headingLevel="h3" audience="admin" planActive={planActive} />;
}

/**
 * ADM-016 "Website catalogue" (async server component, passed into the client AdminCoursesPage as
 * a slot): the website's courses with their live state, compact, with links to manage each one.
 */
async function SiteCatalogAdminSection__server() {
  const catalog = await loadSiteCatalog();
  return (
    <section aria-labelledby="website-catalogue-h" className="rounded-2xl border border-line bg-surface-sunken/60 p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-fg-muted">Tech Drona website</p>
          <h2 id="website-catalogue-h" className="font-display text-lg font-extrabold tracking-tight text-fg-heading">
            Website catalogue
          </h2>
          <p className="mt-0.5 max-w-prose text-[0.9375rem] text-fg-secondary">
            The courses on your website, as learners see them. Set registration status and fee plans in Payments › Admissions; edit course content (text,
            images, syllabus) in the Website Admin.
          </p>
        </div>
        <a href={catalog.adminUrl} className={buttonClasses({ variant: "secondary", size: "sm", className: "gap-1.5" })}>
          Edit content in Website Admin <Icon name="external" className="h-4 w-4" />
        </a>
      </div>
      <SiteCatalogAdminCourses catalog={catalog} />
    </section>
  );
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export const SiteCatalogAdminSection = asyncComponent(SiteCatalogAdminSection__server, "features/site-catalog/components/SiteCatalogAdminSection.tsx#SiteCatalogAdminSection");
