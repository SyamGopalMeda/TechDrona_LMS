import { buttonClasses } from "@/components/ui/Button";
import { EmptyState, Icon } from "@/components/ui";
import { cn } from "@/lib/ui/cn";
import { groupMeta, SITE_COURSE_GROUPS } from "../lib/catalog";
import type { SiteAudience, SiteCatalog, SiteCourseGroup } from "../lib/types";
import { RevealGroup } from "./RevealGroup";
import { SiteCourseCard, type SiteCourseCardVariant } from "./SiteCourseCard";
import s from "./site-catalog.module.css";

const SECTION_DOT: Record<SiteCourseGroup, string> = { open: "bg-[#10b981]", running: "bg-[#2563eb]", upcoming: "bg-[#f59e0b]", completed: "bg-[#9ca3af]" };

/** Shown when neither catalog.json nor the live state could be loaded (or nothing is published). */
export function SiteCatalogUnavailable({ catalog, compact = false }: { catalog: Pick<SiteCatalog, "coursesUrl">; compact?: boolean }) {
  return (
    <EmptyState
      variant={compact ? "inline" : "card"}
      icon="book"
      title="Courses are on the Tech Drona website"
      description="We couldn't load the course list just now. Browse every course, its syllabus and registration on the website."
      action={
        <a href={catalog.coursesUrl} className={buttonClasses({ className: "gap-1.5" })}>
          Browse courses on the website <Icon name="external" className="h-4 w-4" />
        </a>
      }
    />
  );
}

/**
 * The website catalogue grouped like the website: Open registrations / Running / Upcoming /
 * Completed. Each group has a kicker, heading, lead and count; empty groups are listed as such
 * in the default variant (so learners see that nothing is running) and dropped in "compact".
 */
export function SiteCourseSections({
  catalog,
  variant = "default",
  headingLevel = "h2",
  audience = "student",
  planActive,
}: {
  catalog: SiteCatalog;
  variant?: SiteCourseCardVariant;
  headingLevel?: "h2" | "h3";
  /** Signed-in students register in the app (default); visitors on /register/<slug>; "admin" manages. */
  audience?: SiteAudience;
  /** Admin only: slug -> has an active fee plan (a course missing from a loaded map has none). */
  planActive?: Record<string, boolean>;
}) {
  if (!catalog.courses.length) return <SiteCatalogUnavailable catalog={catalog} compact={variant === "compact"} />;
  const compact = variant === "compact";
  const H = headingLevel;
  const groups = compact ? catalog.sections.map((x) => groupMeta(x.key)) : SITE_COURSE_GROUPS;
  const grid = compact ? "grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4" : "grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3";
  return (
    <RevealGroup className={compact ? "space-y-6" : "space-y-10"}>
      {!compact ? (
        <nav aria-label="Course groups" className="flex flex-wrap gap-2">
          {SITE_COURSE_GROUPS.map((g) => {
            const n = catalog.sections.find((x) => x.key === g.key)?.courses.length ?? 0;
            return (
              <a
                key={g.key}
                href={`#courses-${g.key}`}
                className={cn(
                  "inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-sm font-semibold text-fg-heading no-underline shadow-xs transition-colors hover:border-brand focus-visible:shadow-focus focus-visible:outline-none",
                  n === 0 && "text-fg-muted",
                )}
              >
                <span aria-hidden="true" className={cn("h-2 w-2 rounded-full", SECTION_DOT[g.key])} />
                {g.title}
                <span className="rounded-full bg-brand-subtle px-1.5 text-xs text-brand-on-subtle">{n}</span>
              </a>
            );
          })}
        </nav>
      ) : null}
      {groups.map((g) => {
        const list = catalog.sections.find((x) => x.key === g.key)?.courses ?? [];
        return (
          <section key={g.key} id={`courses-${g.key}`} aria-labelledby={`courses-${g.key}-${variant}-h`} className="scroll-mt-24">
            <div data-reveal="" className={cn(s.reveal, compact ? "mb-3" : "mb-5")}>
              <p className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-fg-muted">
                <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", SECTION_DOT[g.key])} />
                {g.kicker}
              </p>
              <H id={`courses-${g.key}-${variant}-h`} className={cn("flex items-center font-display font-extrabold tracking-tight text-fg-heading", compact ? "text-base" : "text-xl")}>
                {g.title}
                <span className="ml-2 inline-grid h-6 min-w-6 place-items-center rounded-full bg-brand-subtle px-2 text-[0.8125rem] text-brand-on-subtle">{list.length}</span>
              </H>
              {!compact ? <p className="mt-1 max-w-prose text-[0.9375rem] text-fg-secondary">{g.lead}</p> : null}
            </div>
            {list.length ? (
              <div className={grid}>
                {list.map((c, i) => (
                  <SiteCourseCard key={c.slug} course={c} index={i} variant={variant} audience={audience} planActive={planActive ? (planActive[c.slug] ?? false) : undefined} />
                ))}
              </div>
            ) : (
              <p className="rounded-xl border border-dashed border-line px-4 py-5 text-sm text-fg-secondary">
                {g.key === "open"
                  ? "No registrations are open right now. Check the upcoming courses below."
                  : g.key === "running"
                    ? "No batch is running right now."
                    : g.key === "upcoming"
                      ? "Nothing announced yet. New courses appear here first."
                      : "No completed batches yet."}
              </p>
            )}
          </section>
        );
      })}
      <p className="text-sm text-fg-secondary">
        Full syllabus and course details are on the Tech Drona website.{" "}
        <a href={catalog.coursesUrl} className="font-semibold text-brand">
          All courses on the website
        </a>
      </p>
    </RevealGroup>
  );
}
