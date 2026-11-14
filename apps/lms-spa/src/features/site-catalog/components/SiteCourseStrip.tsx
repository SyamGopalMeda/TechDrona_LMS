import { asyncComponent } from "@/spa/async";
import Link from "next/link";
import { Card, Icon, ViewAllLink } from "@/components/ui";
import { stripCourses } from "../lib/catalog";
import { loadSiteCatalog } from "../lib/server";
import type { SiteCatalog, SiteLearnerAudience } from "../lib/types";
import { RevealGroup } from "./RevealGroup";
import { NotOpenLabel, notOpenLabel, OPENS_WEBSITE, SiteCourseStatus, STRETCHED_LINK, siteCourseActions, siteCourseDateNote, siteCourseLink, siteIcon } from "./SiteCourseCard";
import s from "./site-catalog.module.css";
import { cn } from "@/lib/ui/cn";

export interface SiteCourseStripProps {
  /** Max courses (default 3). Open registrations first, then running; upcoming when nothing is live. */
  limit?: number;
  /** "All courses" target (default the in-LMS Explore courses page). */
  allHref?: string;
  title?: string;
  /** Signed-in students register in the app (default); visitors on /register/<slug>. */
  audience?: SiteLearnerAudience;
}

/**
 * The strip's one-line description. Only mentions a waitlist when one exists: the website has a
 * waitlist form for courses whose registration is "coming soon" (live audit F-4).
 */
export function stripDescription(list: SiteCatalog["courses"]): string {
  if (list.some((c) => c.registrationOpen)) return "Registrations are open. Register and pay right here in the LMS.";
  if (list.some((c) => c.regStatus === "coming_soon")) return "Registrations open soon. Join the waitlist on our website to hear first.";
  return "See what's running now and what's coming next.";
}

/** Presentational strip (no data loading): usable from client components that already hold the catalogue. */
export function SiteCourseStripView({ catalog, limit = 3, allHref = "/app/courses", title = "Courses from Tech Drona", audience = "student" }: SiteCourseStripProps & { catalog: SiteCatalog }) {
  const list = stripCourses(catalog, limit);
  return (
    <Card
      title={title}
      icon="book"
      description={stripDescription(list)}
      actions={<ViewAllLink href={allHref}>All courses</ViewAllLink>}
    >
      {list.length ? (
        <RevealGroup className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {list.map((c, i) => {
            const actions = siteCourseActions(c, audience);
            const { primary, waitlist } = actions;
            const notOpen = notOpenLabel(c, actions);
            const main = siteCourseLink(c, audience);
            const note = siteCourseDateNote(c);
            return (
              <article
                key={c.slug}
                data-reveal=""
                aria-label={c.title}
                style={{ "--sc-acc": c.theme.accent, "--sc-soft": c.theme.accentSoft, "--sc-delay": `${i * 70}ms` } as React.CSSProperties}
                className={cn(s.reveal, s.card, "relative flex min-h-[7.5rem] flex-col gap-2 rounded-xl border border-line bg-surface p-3.5")}
              >
                <div className="flex items-start gap-3">
                  <span className={cn(s.iconTile, "grid h-10 w-10 shrink-0 place-items-center rounded-lg")}>
                    <Icon name={siteIcon(c.icon, c.featured ? "award" : "book")} className="h-5 w-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <SiteCourseStatus course={c} className="mb-1" />
                    <h3 className="font-display text-[0.95rem] font-bold leading-snug text-fg-heading">
                      {/* The whole card is this link (stretched): a large tap target on phones. */}
                      <a href={main.href} {...(main.external ? { target: "_blank", rel: "noopener" } : {})} className={cn(STRETCHED_LINK, "after:rounded-xl")}>
                        {c.title}
                        {main.external ? (
                          <>
                            <Icon name="external" className="ml-1 inline h-3.5 w-3.5 align-baseline text-fg-muted" />
                            <span className="sr-only"> {OPENS_WEBSITE}</span>
                          </>
                        ) : null}
                      </a>
                    </h3>
                    {note ? <p className="mt-0.5 text-xs text-fg-muted">{note}</p> : null}
                  </div>
                </div>
                {primary.href ? (
                  <a href={primary.href} className="relative z-[2] mt-auto inline-flex min-h-[44px] items-center gap-1 self-start text-sm font-semibold text-brand no-underline hover:underline" aria-label={`${primary.label}: ${c.title}`}>
                    {primary.label} <Icon name="arrowRight" className="h-4 w-4" />
                  </a>
                ) : waitlist ? (
                  <a
                    href={waitlist.href}
                    target="_blank"
                    rel="noopener"
                    className="relative z-[2] mt-auto inline-flex min-h-[44px] items-center gap-1 self-start text-sm font-semibold text-brand no-underline hover:underline"
                    aria-label={`${waitlist.label} ${OPENS_WEBSITE}: ${c.title}`}
                  >
                    {waitlist.label} <Icon name="external" className="h-4 w-4" />
                  </a>
                ) : notOpen ? (
                  <NotOpenLabel label={notOpen} size="inline" />
                ) : main.external ? (
                  <span aria-hidden="true" className="mt-auto inline-flex items-center gap-1 text-sm font-semibold text-brand">
                    Course page on our website <Icon name="external" className="h-4 w-4" />
                  </span>
                ) : null}
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
async function SiteCourseStrip__server(props: SiteCourseStripProps) {
  const catalog = await loadSiteCatalog();
  if (!catalog.courses.length) return null;
  return <SiteCourseStripView catalog={catalog} {...props} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export const SiteCourseStrip = asyncComponent(SiteCourseStrip__server, "features/site-catalog/components/SiteCourseStrip.tsx#SiteCourseStrip");
