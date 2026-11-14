import { asyncComponent } from "@/spa/async";
import { buttonClasses } from "@/components/ui/Button";
import { Icon } from "@/components/ui";
import { loadSiteCatalog } from "../lib/server";
import { SiteCourseSections } from "./SiteCourseSections";

/**
 * ADM-016 "Website catalogue" (async server component, passed into the client AdminCoursesPage as
 * a slot): the website's courses with their live state, compact. Read-only here.
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
            The courses learners see on the website and in Explore courses. Course marketing, status and registrations are managed in the Website Admin;
            changes show up here within about five minutes.
          </p>
        </div>
        <a href={catalog.adminUrl} className={buttonClasses({ variant: "secondary", size: "sm", className: "gap-1.5" })}>
          Website Admin <Icon name="external" className="h-4 w-4" />
        </a>
      </div>
      <SiteCourseSections catalog={catalog} variant="compact" headingLevel="h3" />
    </section>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export const SiteCatalogAdminSection = asyncComponent(SiteCatalogAdminSection__server, "features/site-catalog/components/SiteCatalogAdminSection.tsx#SiteCatalogAdminSection");
