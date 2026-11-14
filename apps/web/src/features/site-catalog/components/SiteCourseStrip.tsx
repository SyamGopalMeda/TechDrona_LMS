import Link from "next/link";
import { Card, Icon, ViewAllLink } from "@/components/ui";
import { stripCourses } from "../lib/catalog";
import { loadSiteCatalog } from "../lib/server";
import type { SiteAudience, SiteCatalog } from "../lib/types";
import { RevealGroup } from "./RevealGroup";
import { NotOpenLabel, SiteCourseStatus, siteCourseActions, siteCourseDateNote, siteCourseLink, siteIcon } from "./SiteCourseCard";
import s from "./site-catalog.module.css";
import { cn } from "@/lib/ui/cn";

export interface SiteCourseStripProps {
  /** Max courses (default 3). Open registrations first, then running; upcoming when nothing is live. */
  limit?: number;
  /** "All courses" target (default the in-LMS Explore courses page). */
  allHref?: string;
  title?: string;
  /** Signed-in students register in the app (default); visitors on /register/<slug>. */
  audience?: SiteAudience;
}

/** Presentational strip (no data loading): usable from client components that already hold the catalogue. */
export function SiteCourseStripView({ catalog, limit = 3, allHref = "/app/courses", title = "Courses from Tech Drona", audience = "student" }: SiteCourseStripProps & { catalog: SiteCatalog }) {
  const list = stripCourses(catalog, limit);
  return (
    <Card
      title={title}
      icon="book"
      description={list.some((c) => c.registrationOpen) ? "Registrations are open. Register and pay right here in the LMS." : "Explore upcoming courses and join a waitlist."}
      actions={<ViewAllLink href={allHref}>All courses</ViewAllLink>}
    >
      {list.length ? (
        <RevealGroup className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {list.map((c, i) => {
            const { primary } = siteCourseActions(c, audience);
            const main = siteCourseLink(c, audience);
            const note = siteCourseDateNote(c);
            return (
              <article
                key={c.slug}
                data-reveal=""
                aria-label={c.title}
                style={{ "--sc-acc": c.theme.accent, "--sc-soft": c.theme.accentSoft, "--sc-delay": `${i * 70}ms` } as React.CSSProperties}
                className={cn(s.reveal, s.card, "flex flex-col gap-2 rounded-xl border border-line bg-surface p-3.5")}
              >
                <div className="flex items-start gap-3">
                  <span className={cn(s.iconTile, "grid h-10 w-10 shrink-0 place-items-center rounded-lg")}>
                    <Icon name={siteIcon(c.icon, c.featured ? "award" : "book")} className="h-5 w-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <SiteCourseStatus course={c} className="mb-1" />
                    <h3 className="font-display text-[0.95rem] font-bold leading-snug text-fg-heading">
                      <a href={main.href} {...(main.external ? { target: "_blank", rel: "noopener" } : {})} className="text-inherit no-underline hover:underline focus-visible:shadow-focus focus-visible:outline-none">
                        {c.title}
                      </a>
                    </h3>
                    {note ? <p className="mt-0.5 text-xs text-fg-muted">{note}</p> : null}
                  </div>
                </div>
                {primary.href ? (
                  <a href={primary.href} className="mt-auto inline-flex items-center gap-1 text-sm font-semibold text-brand no-underline hover:underline" aria-label={`${primary.label}: ${c.title}`}>
                    {primary.label} <Icon name="arrowRight" className="h-4 w-4" />
                  </a>
                ) : (
                  <NotOpenLabel label={primary.label} size="inline" />
                )}
              </article>
            );
          })}
        </RevealGroup>
      ) : (
        <p className="text-sm text-fg-secondary">
          See every course on the{" "}
          <Link href={allHref} className="font-semibold text-brand">
            courses page
          </Link>
          .
        </p>
      )}
    </Card>
  );
}

/**
 * Dashboard strip (async server component): top open/running website courses + "All courses".
 * In a client component, pass it in as a prop/children slot from the server page
 * (`<StudentDashboard courses={<SiteCourseStrip />} />`). Renders nothing if the catalogue is down.
 */
export async function SiteCourseStrip(props: SiteCourseStripProps) {
  const catalog = await loadSiteCatalog();
  if (!catalog.courses.length) return null;
  return <SiteCourseStripView catalog={catalog} {...props} />;
}
