import type { CSSProperties } from "react";
import { buttonClasses } from "@/components/ui/Button";
import { Icon, isIconName, type IconName } from "@/components/ui";
import { formatDate } from "@/features/catalog/lib/format";
import { cn } from "@/lib/ui/cn";
import type { SiteAudience, SiteCourse, SiteCourseGroup } from "../lib/types";
import { CourseScene } from "./CourseScene";
import s from "./site-catalog.module.css";

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
}

/** Register only when the course is open: signed-in students in the app, visitors on /register/<slug>. */
export function siteCourseActions(c: SiteCourse, audience: SiteAudience = "student"): SiteCourseActions {
  return {
    // Full syllabus lives on the company website (opens in a new tab); everything else stays in the LMS.
    secondary: { href: c.courseUrl, label: "Course details" },
    primary: c.registrationOpen
      ? { href: audience === "public" ? c.publicRegisterUrl : c.registerUrl, label: "Register" }
      : { href: null, label: c.regStatus === "coming_soon" ? "Coming soon" : "Closed" },
  };
}

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
 * and links to the course page / registration on the website.
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
  const { primary, secondary } = siteCourseActions(c, audience);
  const main = siteCourseLink(c, audience);
  const ext = main.external ? { target: "_blank", rel: "noopener" } : {};
  const titleId = `site-course-${variant}-${c.slug}`;
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
      <a
        href={main.href}
        {...ext}
        tabIndex={-1}
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
        <span className="absolute left-3.5 top-3 z-[1] inline-flex max-w-[calc(100%-11rem)] items-center rounded-full border border-white/70 bg-white/90 px-2.5 py-1 text-[0.68rem] font-bold uppercase tracking-[0.08em] sm:max-w-[55%]">
          <span className={cn(s.accentText, "truncate")}>{c.family || (c.featured ? "Featured program" : "Course")}</span>
        </span>
        <SiteCourseStatus course={c} className="absolute right-3.5 top-3 z-[1]" />
        <span className={cn(s.bannerArt, "absolute bottom-3 left-3.5 right-3.5 flex items-end gap-2.5", (poster || scene) && "hidden")}>
          <span className={cn(s.iconTile, "grid shrink-0 place-items-center rounded-xl shadow-sm", compact ? "h-9 w-9" : "h-12 w-12")}>
            <Icon name={siteIcon(c.icon, c.featured ? "award" : "book")} className={compact ? "h-5 w-5" : "h-6 w-6"} />
          </span>
          {!compact && c.theme.labels?.length ? (
            <span className="flex min-w-0 flex-wrap gap-1.5 pb-0.5">
              {c.theme.labels.slice(0, 3).map((l) => (
                <span key={l} className="rounded-md bg-white/85 px-2 py-0.5 text-[0.68rem] font-semibold text-fg-secondary shadow-xs">
                  {l}
                </span>
              ))}
            </span>
          ) : null}
        </span>
      </a>

      <div className={cn("flex flex-1 flex-col", compact ? "gap-2 p-4" : "gap-2.5 p-5")}>
        {c.kicker ? <p className={cn(s.kicker, "text-[0.7rem] font-bold uppercase tracking-[0.12em]")}>{c.kicker}</p> : null}
        <h3 id={titleId} className={cn("font-display font-bold leading-snug text-fg-heading", compact ? "text-[0.98rem]" : "text-[1.08rem]")}>
          <a href={main.href} {...ext} className="text-inherit no-underline hover:underline focus-visible:shadow-focus focus-visible:outline-none">
            {c.title}
          </a>
        </h3>
        {c.tagline ? <p className={cn("text-fg-secondary", compact ? "line-clamp-2 text-[0.84rem]" : "text-[0.9rem]")}>{c.tagline}</p> : null}

        {facts.length ? (
          <ul className={cn("grid gap-2", compact ? "grid-cols-2" : "grid-cols-3")}>
            {facts.map((f) => (
              <li key={f.label} className="min-w-0 rounded-lg bg-surface-sunken px-2.5 py-2">
                <small className="flex items-center gap-1 truncate text-[0.68rem] font-semibold uppercase tracking-wide text-fg-muted">
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

        <div className="mt-auto flex flex-wrap gap-2 pt-2">
          {primary.href ? (
            <a href={primary.href} className={buttonClasses({ size: "sm", className: "gap-1.5" })} aria-label={`${primary.label}: ${c.title}`}>
              {primary.label}
              <Icon name="arrowRight" className="h-4 w-4" />
            </a>
          ) : (
            <NotOpenLabel label={primary.label} />
          )}
          <a href={secondary.href} target="_blank" rel="noopener" className={buttonClasses({ variant: "secondary", size: "sm" })} aria-label={`${secondary.label} on the Tech Drona website (opens in a new tab): ${c.title}`}>
            {secondary.label} ↗
          </a>
        </div>
      </div>
    </article>
  );
}
