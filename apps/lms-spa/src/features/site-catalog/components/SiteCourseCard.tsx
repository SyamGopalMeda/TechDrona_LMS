import type { CSSProperties } from "react";
import { buttonClasses } from "@/components/ui/Button";
import { Icon, isIconName, type IconName } from "@/components/ui";
import { cn } from "@/lib/ui/cn";
import type { SiteAudience, SiteCourse, SiteCourseGroup } from "../lib/types";
import { CourseScene } from "./CourseScene";
import s from "./site-catalog.module.css";
import { formatDate } from "@/lib/format";

/* Website icon names (tech drona Icon.jsx) -> the LMS kit set. */
const ICONS: Record<string, IconName> = {
  brain: "sparkles",
  spark: "sparkles",
  laptop: "code",
  monitor: "panel",
  cloud: "layers",
  chip: "grid",
  cap: "award",
  rocket: "bolt",
  database: "layers",
};
export const siteIcon = (name: string | undefined, fallback: IconName = "book"): IconName =>
  name && isIconName(name) ? name : (name && ICONS[name]) || fallback;

const LIVE_CLASS: Record<SiteCourseGroup, string> = { open: s.live ?? "", running: s.liveRunning ?? "", upcoming: s.liveSoon ?? "", completed: s.liveDone ?? "" };

/** Status pill with the LED dot (website .cf-live / .pc-live). */
export function SiteCourseStatus({ course: c, className }: { course: Pick<SiteCourse, "group" | "statusLabel">; className?: string }) {
  return (
    <span
      data-group={c.group}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[0.72rem] font-bold tracking-wide",
        LIVE_CLASS[c.group],
        className,
      )}
    >
      <i aria-hidden="true" className="inline-block h-[7px] w-[7px] rounded-full" />
      {c.statusLabel}
    </span>
  );
}

/** One-line date note: "Starts 1 Dec 2026" / "Runs 1 Dec 2026 – 20 Mar 2027" / "Ended …" / edition. */
export function siteCourseDateNote(c: SiteCourse): string | null {
  if (c.group === "completed" && c.endDate) return `Ended ${formatDate(c.endDate)}`;
  if (c.startDate && c.endDate && c.group === "running") return `${formatDate(c.startDate)} – ${formatDate(c.endDate)}`;
  if (c.startDate) return `${c.group === "running" ? "Started" : "Starts"} ${formatDate(c.startDate)}`;
  return c.edition || null;
}

export interface SiteCourseActions {
  /** `href` null: not open for registration (render as a disabled-looking label, no link). */
  primary: { href: string | null; label: string };
  secondary: { href: string; label: string };
  /**
   * The website's waitlist form (`/courses/<slug>#register`), only while registration is
   * "coming soon": the website shows it then, and has no waitlist for closed courses.
   */
  waitlist?: { href: string; label: string };
}

/** Accessible suffix for links that leave the LMS for the company website. */
export const OPENS_WEBSITE = "(opens the Tech Drona website in a new tab)";

/** Register only when the course is open: signed-in students in the app, visitors on /register/<slug>. */
export function siteCourseActions(c: SiteCourse, audience: SiteAudience = "student"): SiteCourseActions {
  return {
    // Full syllabus lives on the company website (opens in a new tab); everything else stays in the LMS.
    secondary: { href: c.courseUrl, label: "Course details" },
    primary: c.registrationOpen
      ? { href: audience === "public" ? c.publicRegisterUrl : c.registerUrl, label: "Register" }
      : { href: null, label: c.regStatus === "coming_soon" ? "Coming soon" : "Closed" },
    ...(!c.registrationOpen && c.regStatus === "coming_soon" ? { waitlist: { href: `${c.courseUrl}#register`, label: "Join the waitlist on our website" } } : {}),
  };
}

/**
 * The "not open" label for the actions row, or null when the status pill already says the same
 * thing (live audit F-4: "Coming soon" was shown twice) or a waitlist link takes its place.
 */
export function notOpenLabel(c: Pick<SiteCourse, "statusLabel">, actions: SiteCourseActions): string | null {
  if (actions.primary.href || actions.waitlist) return null;
  return actions.primary.label.trim().toLowerCase() === c.statusLabel.trim().toLowerCase() ? null : actions.primary.label;
}

/** Shown on a card built without catalog.json (website down, or its CORS header missing). */
export const MINIMAL_TAGLINE = "Syllabus, fees and batch dates are on the Tech Drona website.";

/**
 * Classes for a "stretched" title link: its ::after covers the whole card (the positioned
 * ancestor), so the entire card is one large tap target; other links in the card sit above it.
 */
export const STRETCHED_LINK =
  "text-inherit no-underline after:absolute after:inset-0 after:z-[1] after:content-[''] hover:underline focus-visible:outline-none focus-visible:after:outline focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-brand";

/** The title / banner link: registration when open, else the course details on the website. */
export function siteCourseLink(c: SiteCourse, audience: SiteAudience = "student"): { href: string; external: boolean } {
  const { primary, secondary } = siteCourseActions(c, audience);
  return primary.href ? { href: primary.href, external: false } : { href: secondary.href, external: true };
}

/** "Coming soon" / "Closed" in place of the Register button: looks disabled, is not a link. */
export function NotOpenLabel({ label, size = "sm", className }: { label: string; size?: "sm" | "inline"; className?: string }) {
  if (size === "inline") return <span className={cn("mt-auto inline-flex items-center gap-1 text-sm font-semibold text-fg-muted", className)}>{label}</span>;
  return (
    <span aria-disabled="true" className={cn(buttonClasses({ variant: "secondary", size: "sm" }), "pointer-events-none cursor-not-allowed opacity-60", className)}>
      {label}
    </span>
  );
}

export type SiteCourseCardVariant = "default" | "compact";

/**
 * A website course card (tech drona CatalogCard `.cc` + the featured `.cf` kicker/live pill):
 * accent banner with family + status, kicker, title, tagline, 2-3 facts, tech chips, start date,
 * and links to the course page / registration on the website. The whole card is one link (the
 * stretched title); the action buttons sit above it.
 */
export function SiteCourseCard({
  course: c,
  index = 0,
  variant = "default",
  audience = "student",
  className,
}: {
  course: SiteCourse;
  index?: number;
  variant?: SiteCourseCardVariant;
  audience?: SiteAudience;
  className?: string;
}) {
  const compact = variant === "compact";
  const style = { "--sc-acc": c.theme.accent, "--sc-soft": c.theme.accentSoft, "--sc-delay": `${(index % 3) * 70}ms` } as CSSProperties;
  const facts = c.facts.slice(0, compact ? 2 : 3);
  const tech = c.tech.slice(0, compact ? 4 : 5);
  const dateNote = siteCourseDateNote(c);
  const actions = siteCourseActions(c, audience);
  const { primary, secondary, waitlist } = actions;
  const notOpen = notOpenLabel(c, actions);
  const main = siteCourseLink(c, audience);
  const ext = main.external ? { target: "_blank", rel: "noopener" } : {};
  const titleId = `site-course-${variant}-${c.slug}`;
  const tagline = c.tagline || (c.minimal ? MINIMAL_TAGLINE : "");
  const poster = c.imageSmallUrl ?? c.imageUrl;
  const scene = !poster && c.scene ? c.scene : undefined;
  return (
    <article
      aria-labelledby={titleId}
      data-reveal=""
      data-group={c.group}
      style={style}
      className={cn(s.reveal, s.card, "group relative flex h-full flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-sm", className)}
    >
      <div
        aria-hidden="true"
        className={cn(
          s.banner,
          "relative block overflow-hidden no-underline",
          poster ? (compact ? "h-[150px]" : "h-[230px]") : scene ? (compact ? "h-[130px]" : "h-[190px]") : compact ? "h-[88px]" : "h-[132px]",
        )}
      >
        {poster ? (
          // the website's program poster (portrait); top-aligned so the headline shows, zooms on hover
          // eslint-disable-next-line @next/next/no-img-element -- cross-origin website asset, no image optimiser
          <img src={poster} alt="" loading="lazy" decoding="async" className="absolute inset-0 h-full w-full object-cover object-top transition-transform duration-500 ease-out group-hover:scale-[1.04] motion-reduce:transition-none" />
        ) : scene ? (
          <CourseScene scene={c.scene} accent={c.theme.accent} accentSoft={c.theme.accentSoft} className="absolute inset-x-2 bottom-1 top-9 transition-transform duration-500 ease-out group-hover:-translate-y-0.5 group-hover:scale-[1.025] motion-reduce:transition-none" />
        ) : null}
        {poster ? <span aria-hidden="true" className="absolute inset-x-0 top-0 h-14 bg-gradient-to-b from-black/35 to-transparent" /> : null}
        {!poster && !scene ? <span aria-hidden="true" className={cn(s.glow, "absolute -right-10 -top-12 h-40 w-40 rounded-full opacity-60 blur-2xl")} style={{ background: c.theme.accent }} /> : null}
        <span className="absolute left-3.5 top-3 inline-flex max-w-[calc(100%-11rem)] items-center rounded-full border border-white/70 bg-white/90 px-2.5 py-1 text-xs font-bold uppercase tracking-[0.08em] sm:max-w-[55%]">
          <span className={cn(s.accentText, "truncate")}>{c.family || (c.featured ? "Featured program" : "Course")}</span>
        </span>
        <SiteCourseStatus course={c} className="absolute right-3.5 top-3" />
        <span className={cn(s.bannerArt, "absolute bottom-3 left-3.5 right-3.5 flex items-end gap-2.5", (poster || scene) && "hidden")}>
          <span className={cn(s.iconTile, "grid shrink-0 place-items-center rounded-xl shadow-sm", compact ? "h-9 w-9" : "h-12 w-12")}>
            <Icon name={siteIcon(c.icon, c.featured ? "award" : "book")} className={compact ? "h-5 w-5" : "h-6 w-6"} />
          </span>
          {!compact && c.theme.labels?.length ? (
            <span className="flex min-w-0 flex-wrap gap-1.5 pb-0.5">
              {c.theme.labels.slice(0, 3).map((l) => (
                <span key={l} className="rounded-md bg-white/85 px-2 py-0.5 text-xs font-semibold text-fg-secondary shadow-xs">
                  {l}
                </span>
              ))}
            </span>
          ) : null}
        </span>
      </div>

      <div className={cn("flex flex-1 flex-col", compact ? "gap-2 p-4" : "gap-2.5 p-5")}>
        {c.kicker ? <p className={cn(s.kicker, "text-xs font-bold uppercase tracking-[0.12em]")}>{c.kicker}</p> : null}
        <h3 className={cn("font-display font-bold leading-snug text-fg-heading", compact ? "text-[0.98rem]" : "text-[1.08rem]")}>
          {/* The whole card is this link (stretched); external = the course page on the website. */}
          <a href={main.href} {...ext} className={cn(STRETCHED_LINK, "after:rounded-2xl")}>
            <span id={titleId}>{c.title}</span>
            {main.external ? (
              <>
                <Icon name="external" className="ml-1 inline h-3.5 w-3.5 align-baseline text-fg-muted" />
                <span className="sr-only"> {OPENS_WEBSITE}</span>
              </>
            ) : null}
          </a>
        </h3>
        {tagline ? <p className={cn("text-fg-secondary", compact ? "line-clamp-2 text-[0.84rem]" : "text-[0.9rem]")}>{tagline}</p> : null}

        {facts.length ? (
          <ul className={cn("grid gap-2", compact ? "grid-cols-2" : "grid-cols-3")}>
            {facts.map((f) => (
              <li key={f.label} className="min-w-0 rounded-lg bg-surface-sunken px-2.5 py-2">
                <small className="flex min-w-0 items-center gap-1 text-xs font-semibold uppercase leading-tight tracking-wide text-fg-muted [overflow-wrap:anywhere]">
                  <Icon name={siteIcon(f.icon, "clock")} className="h-3.5 w-3.5 shrink-0" />
                  {f.label}
                </small>
                <strong className="block truncate text-[0.84rem] font-bold text-fg-heading">{f.value}</strong>
              </li>
            ))}
          </ul>
        ) : null}

        {tech.length ? (
          <div className="flex flex-wrap gap-1.5">
            {tech.map((t) => (
              <span key={t} className={cn(s.chip, "rounded-full px-2.5 py-0.5 text-[0.72rem] font-semibold")}>
                {t}
              </span>
            ))}
          </div>
        ) : null}

        {dateNote ? (
          <p className="flex items-center gap-1.5 text-[0.82rem] text-fg-secondary">
            <Icon name="calendar" className="h-4 w-4 shrink-0 text-fg-muted" />
            {dateNote}
          </p>
        ) : null}

        <div className="relative z-[2] mt-auto flex flex-wrap gap-2 pt-2">
          {primary.href ? (
            <a href={primary.href} className={buttonClasses({ size: "sm", className: "gap-1.5" })} aria-label={`${primary.label}: ${c.title}`}>
              {primary.label}
              <Icon name="arrowRight" className="h-4 w-4" />
            </a>
          ) : waitlist ? (
            <a href={waitlist.href} target="_blank" rel="noopener" className={buttonClasses({ size: "sm", className: "gap-1.5" })} aria-label={`${waitlist.label} ${OPENS_WEBSITE}: ${c.title}`}>
              {waitlist.label}
              <Icon name="external" className="h-4 w-4" />
            </a>
          ) : notOpen ? (
            <NotOpenLabel label={notOpen} />
          ) : null}
          <a href={secondary.href} target="_blank" rel="noopener" className={buttonClasses({ variant: "secondary", size: "sm", className: "gap-1.5" })} aria-label={`${secondary.label} on the Tech Drona website (opens in a new tab): ${c.title}`}>
            {secondary.label} on our website
            <Icon name="external" className="h-4 w-4" />
          </a>
        </div>
      </div>
    </article>
  );
}
