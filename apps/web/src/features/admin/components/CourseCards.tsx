"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { buttonClasses } from "@/components/ui/Button";
import { Badge, Card, EmptyState, ErrorState, Icon, LoadingBlock, PageHeader, ViewAllLink, type BadgeTone, type IconName } from "@/components/ui";
import { useResource } from "@/features/account/lib/use-resource";
import { cn } from "@/lib/ui/cn";
import { formatDate } from "../lib/console";

/* ------------------------------------------------------------------ API types */

/** verified: apps/api/app/modules/admin/courses_overview.py (GET admin/courses/overview). */
export interface OverviewBatch {
  batch_id: string;
  name: string;
  code: string;
  status: string;
  starts_on: string | null;
  ends_on: string | null;
  enrolled: number;
}

export interface OverviewCourse {
  course_id: string;
  title: string;
  slug: string;
  status: string;
  visibility: string;
  course_kind: string;
  is_free: boolean;
  published_at: string | null;
  updated_at: string | null;
  enrolled: number;
  completed: number;
  certificates_issued: number;
  certificates_ready: number;
  batch_count: number;
  batches: OverviewBatch[];
}

export interface CoursesOverview {
  generated_at: string;
  totals: { courses: number; courses_published: number; courses_draft: number; learners: number; enrolled: number; completed: number };
  certificates: { issued_valid: number; revoked: number; issued_30d: number; ready: number };
  courses: OverviewCourse[];
}

/* ------------------------------------------------------------------ grouping */

export type CourseGroup = "running" | "upcoming" | "draft" | "completed";

export const COURSE_GROUPS: { key: CourseGroup; title: string; description: string; tone: BadgeTone; label: string }[] = [
  { key: "running", title: "Running", description: "Open for learners now, or a batch is in progress.", tone: "success", label: "Running" },
  { key: "upcoming", title: "Coming soon", description: "Published; the next batch has not started yet.", tone: "info", label: "Coming soon" },
  { key: "draft", title: "Draft", description: "Not published yet. Finish them in the content studio.", tone: "warning", label: "Draft" },
  { key: "completed", title: "Completed", description: "Every batch has finished, or the course is archived.", tone: "neutral", label: "Completed" },
];

/** Today's date (YYYY-MM-DD) in India time, the zone batch dates are planned in. */
export function todayIST(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

const ended = (b: OverviewBatch, today: string) => b.status === "completed" || b.status === "archived" || (!!b.ends_on && b.ends_on < today);
const notStarted = (b: OverviewBatch, today: string) => !ended(b, today) && !!b.starts_on && b.starts_on > today;

/**
 * Which group a course card sits in (website AdminCourses: Running / Coming soon / Draft / Completed).
 * Published with no batch = self-paced and open = running. Batches come from the enrolments.
 */
export function courseGroup(c: OverviewCourse, today: string = todayIST()): CourseGroup {
  if (c.status === "draft") return "draft";
  if (c.status !== "published") return "completed";
  if (!c.batches.length) return "running";
  if (c.batches.some((b) => !ended(b, today) && !notStarted(b, today))) return "running";
  if (c.batches.some((b) => notStarted(b, today))) return "upcoming";
  return c.enrolled > 0 ? "running" : "completed";
}

/** The batch whose dates the card shows: the running one, else the next one, else the last one. */
export function featuredBatch(c: OverviewCourse, today: string = todayIST()): OverviewBatch | null {
  return (
    c.batches.find((b) => !ended(b, today) && !notStarted(b, today)) ??
    c.batches.find((b) => notStarted(b, today)) ??
    c.batches[c.batches.length - 1] ??
    null
  );
}

export function groupCourses(courses: OverviewCourse[], today: string = todayIST()): { key: CourseGroup; courses: OverviewCourse[] }[] {
  return COURSE_GROUPS.map((g) => ({ key: g.key, courses: courses.filter((c) => courseGroup(c, today) === g.key) })).filter((g) => g.courses.length > 0);
}

/** Dashboard strip order: running, coming soon, draft, completed; then most enrolled first. */
export function topCourses(courses: OverviewCourse[], n = 6, today: string = todayIST()): OverviewCourse[] {
  const rank = (c: OverviewCourse) => COURSE_GROUPS.findIndex((g) => g.key === courseGroup(c, today));
  return [...courses].sort((a, b) => rank(a) - rank(b) || b.enrolled - a.enrolled || a.title.localeCompare(b.title)).slice(0, n);
}

/* ------------------------------------------------------------------ pieces */

const num = (v: number | null | undefined) => (typeof v === "number" ? new Intl.NumberFormat("en-IN").format(v) : "—");
const plural = (n: number, one: string, many: string) => `${num(n)} ${n === 1 ? one : many}`;
const KIND: Record<string, string> = { self_paced: "Self-paced", cohort: "Cohort", crash_course: "Crash course", company_prep: "Company prep", bootcamp: "Bootcamp" };

export const studioCourseHref = (id: string) => `/studio/courses/${encodeURIComponent(id)}`;
export const certificatesHref = (id: string) => `/admin/certificates?course=${encodeURIComponent(id)}`;

/* Website .adm-kpi: white card, 4px coloured left edge, 52px tinted icon square, big number. */
export type KpiTone = "amber" | "navy" | "green" | "indigo";
const kpiTones: Record<KpiTone, { tile: string }> = {
  amber: { tile: "bg-warning-subtle text-warning-fg" },
  navy: { tile: "bg-brand-subtle text-brand-on-subtle" },
  green: { tile: "bg-success-subtle text-success-fg" },
  indigo: { tile: "bg-info-subtle text-info-fg" },
};

export function KpiCard({ icon, label, value, hint, tone, href }: { icon: IconName; label: string; value: ReactNode; hint?: ReactNode; tone: KpiTone; href?: string }) {
  const t = kpiTones[tone];
  const body = (
    <>
      <span aria-hidden="true" className={cn("row-span-3 grid h-10 w-10 place-items-center rounded-[12px]", t.tile)}>
        <Icon name={icon} className="h-[18px] w-[18px]" />
      </span>
      <span className="font-display text-[1.5rem] font-extrabold leading-none tabular-nums tracking-tight text-fg-heading">{value}</span>
      <span className="text-[0.8125rem] font-semibold text-fg-secondary">{label}</span>
      {hint ? <span className="text-[0.75rem] text-fg-muted">{hint}</span> : <span />}
    </>
  );
  const cls = "relative grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-0.5 overflow-hidden rounded-xl border border-[#e6eaf2] bg-surface p-3.5";
  return href ? (
    <Link href={href} className={cn(cls, "no-underline transition-[border-color,box-shadow] hover:border-[#c7d2ee] hover:shadow-sm focus-visible:shadow-focus focus-visible:outline-none")}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

export function CourseKpis({ data, compact = false }: { data: CoursesOverview; compact?: boolean }) {
  const { totals, certificates } = data;
  return (
    <div className={cn("grid grid-cols-1 gap-3 sm:grid-cols-2", compact ? "2xl:grid-cols-4" : "xl:grid-cols-4")}>
      <KpiCard tone="navy" icon="users" label="Learners" value={num(totals.learners)} hint={`${plural(totals.completed, "course completion", "course completions")}`} href="/admin/users?status=active" />
      <KpiCard tone="green" icon="book" label="Active enrolments" value={num(totals.enrolled)} hint={`Across ${plural(totals.courses_published, "published course", "published courses")}`} href="/admin/courses" />
      <KpiCard tone="indigo" icon="award" label="Certificates issued" value={num(certificates.issued_valid)} hint={`${num(certificates.issued_30d)} in the last 30 days`} href="/admin/certificates" />
      <KpiCard tone="amber" icon="hourglass" label="Ready for certificate" value={num(certificates.ready)} hint={certificates.ready ? "Completed, no certificate yet" : "Nobody is waiting"} href="/admin/certificates" />
    </div>
  );
}

function batchDates(b: OverviewBatch | null): string {
  if (!b) return "No batch yet · self-paced";
  if (!b.starts_on) return `${b.name} · no start date yet`;
  return `${formatDate(b.starts_on)} – ${b.ends_on ? formatDate(b.ends_on) : "open-ended"}`;
}

/** One course card (website `.crs-card`). */
export function CourseCard({ course: c, today = todayIST() }: { course: OverviewCourse; today?: string }) {
  const group = COURSE_GROUPS.find((g) => g.key === courseGroup(c, today))!;
  const fb = featuredBatch(c, today);
  const nums: [number, string][] = [
    [c.enrolled, "Enrolled"],
    [c.completed, "Completed"],
    [c.batch_count, c.batch_count === 1 ? "Batch" : "Batches"],
    [c.certificates_issued, "Certificates issued"],
  ];
  return (
    <article aria-label={c.title} className="flex flex-col gap-2.5 rounded-2xl border border-line bg-surface p-[18px] pb-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <Badge tone={group.tone} dot>
          {group.label}
        </Badge>
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-fg-secondary">
          <span aria-hidden="true" className={cn("h-2 w-2 rounded-full", c.status === "published" && c.visibility === "public" ? "bg-success-border" : "bg-fg-muted")} />
          {c.status !== "published" ? "Not published" : c.visibility === "public" ? "Open for enrolment" : "Not listed publicly"}
        </span>
      </div>
      <h3 className="font-display text-[1.03rem] font-bold leading-snug text-fg-heading">
        <Link href={studioCourseHref(c.course_id)} className="text-inherit no-underline hover:text-brand focus-visible:shadow-focus focus-visible:outline-none">
          {c.title}
        </Link>
      </h3>
      <p className="flex items-center gap-2 text-[0.84rem] text-fg-secondary">
        <Icon name="calendar" className="h-[15px] w-[15px] shrink-0 text-fg-muted" />
        {batchDates(fb)}
      </p>
      <p className="flex items-center gap-2 text-[0.84rem] text-fg-secondary">
        <Icon name="clock" className="h-[15px] w-[15px] shrink-0 text-fg-muted" />
        {KIND[c.course_kind] ?? c.course_kind}
        {c.is_free ? " · Free" : ""}
        {c.published_at ? ` · Published ${formatDate(c.published_at)}` : ""}
      </p>
      <ul className="mt-1 grid grid-cols-4 gap-1.5 border-t border-line pt-2.5">
        {nums.map(([n, label]) => (
          <li key={label}>
            <b className="block font-display text-lg font-extrabold tabular-nums text-brand">{num(n)}</b>
            <small className="block text-[0.72rem] leading-tight text-fg-muted">{label}</small>
          </li>
        ))}
      </ul>
      {c.certificates_ready > 0 ? (
        <p className="flex items-center gap-2 rounded-lg bg-warning-subtle px-2.5 py-2 text-[0.8125rem] font-semibold text-warning-fg">
          <Icon name="award" className="h-[15px] w-[15px] shrink-0" />
          {plural(c.certificates_ready, "learner", "learners")} ready for a certificate
        </p>
      ) : null}
      {group.key === "upcoming" && fb?.starts_on ? (
        <p className="flex items-center gap-2 rounded-lg bg-surface-sunken px-2.5 py-2 text-[0.8125rem] font-semibold text-fg-secondary">
          <Icon name="bolt" className="h-[15px] w-[15px] shrink-0" />
          {fb.name} starts {formatDate(fb.starts_on)} · {plural(fb.enrolled, "learner", "learners")} enrolled
        </p>
      ) : null}
      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        <Link href={studioCourseHref(c.course_id)} className={buttonClasses({ size: "sm", className: "gap-1.5" })}>
          <Icon name="book" className="h-4 w-4" /> Open course
        </Link>
        <Link href="/admin/batches" className={buttonClasses({ variant: "secondary", size: "sm", className: "gap-1.5" })}>
          <Icon name="grid" className="h-4 w-4" /> Batches
        </Link>
        <Link href={certificatesHref(c.course_id)} className={buttonClasses({ variant: "secondary", size: "sm", className: "gap-1.5" })}>
          <Icon name="award" className="h-4 w-4" /> Certificates
        </Link>
      </div>
    </article>
  );
}

const GRID = "grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3";

/** Course cards grouped Running / Coming soon / Draft / Completed (website AdminCourses). */
export function CourseCards({ courses, today = todayIST() }: { courses: OverviewCourse[]; today?: string }) {
  if (!courses.length)
    return (
      <EmptyState
        icon="book"
        title="No courses yet"
        description="Create a course in the content studio. It shows up here with its enrolments and certificates."
        action={<Link href="/studio/courses" className={buttonClasses()}>Open the content studio</Link>}
      />
    );
  return (
    <div className="space-y-8">
      {groupCourses(courses, today).map(({ key, courses: list }) => {
        const g = COURSE_GROUPS.find((x) => x.key === key)!;
        return (
          <section key={key} aria-labelledby={`crs-${key}`}>
            <div className="mb-4">
              <h2 id={`crs-${key}`} className="flex items-center font-display text-lg font-extrabold tracking-tight text-fg-heading">
                {g.title}
                <span className="ml-2 inline-grid h-6 min-w-6 place-items-center rounded-full bg-brand-subtle px-2 text-[0.8125rem] text-brand-on-subtle">{list.length}</span>
              </h2>
              <p className="mt-0.5 text-[0.9375rem] text-fg-secondary">{g.description}</p>
            </div>
            <div className={GRID}>
              {list.map((c) => (
                <CourseCard key={c.course_id} course={c} today={today} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ screens */

/**
 * ADM-016 /admin/courses: every course as a card, grouped by state. `websiteCatalogue` is the
 * server-rendered "Website catalogue" section (features/site-catalog), shown above the LMS cards.
 */
export function AdminCoursesPage({ websiteCatalogue }: { websiteCatalogue?: ReactNode } = {}) {
  const res = useResource<CoursesOverview>("admin/courses/overview");
  const d = res.data;
  return (
    <div>
      <PageHeader
        title="Courses"
        description="Every course with its learners, batches and certificates. Authoring happens in the content studio."
        actions={
          <Link href="/studio/courses" className={buttonClasses({ className: "gap-2" })}>
            <Icon name="pen" className="h-[18px] w-[18px]" /> Content studio
          </Link>
        }
      />
      {websiteCatalogue ? <div className="mb-8">{websiteCatalogue}</div> : null}
      {websiteCatalogue ? (
        <h2 className="mb-4 font-display text-lg font-extrabold tracking-tight text-fg-heading">LMS delivery</h2>
      ) : null}
      {res.error ? (
        <ErrorState error={res.error} title="Could not load the courses" onRetry={() => void res.reload()} />
      ) : !d ? (
        <LoadingBlock label="Loading courses…" size="card" rows={4} />
      ) : (
        <div className="space-y-8">
          <CourseKpis data={d} />
          <CourseCards courses={d.courses} />
        </div>
      )}
    </div>
  );
}

/** Compact course row for the dashboard (2026-11 redesign): status, title, schedule, key numbers. */
export function CourseRow({ course: c, today = todayIST() }: { course: OverviewCourse; today?: string }) {
  const group = COURSE_GROUPS.find((g) => g.key === courseGroup(c, today))!;
  const fb = featuredBatch(c, today);
  const nums: [number, string][] = [
    [c.enrolled, "Enrolled"],
    [c.completed, "Completed"],
    [c.certificates_issued, "Certificates"],
  ];
  return (
    <article aria-label={c.title} className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:gap-4 sm:px-5">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={group.tone} dot>
            {group.label}
          </Badge>
          {c.certificates_ready > 0 ? (
            <Badge tone="warning">
              <Icon name="award" className="mr-1 h-3.5 w-3.5" />
              {plural(c.certificates_ready, "ready for certificate", "ready for certificates")}
            </Badge>
          ) : null}
        </div>
        <h3 className="mt-1.5 truncate font-display text-[0.98rem] font-bold text-fg-heading">
          <Link href={studioCourseHref(c.course_id)} className="text-inherit no-underline hover:text-brand focus-visible:shadow-focus focus-visible:outline-none">
            {c.title}
          </Link>
        </h3>
        <p className="mt-0.5 truncate text-[0.8125rem] text-fg-muted">
          {KIND[c.course_kind] ?? c.course_kind}
          {c.is_free ? " · Free" : ""} · {batchDates(fb)}
        </p>
      </div>
      <ul className="grid shrink-0 grid-cols-3 gap-4 sm:w-[16rem]">
        {nums.map(([n, label]) => (
          <li key={label} className="text-left sm:text-center">
            <b className="block font-display text-lg font-extrabold tabular-nums text-fg-heading">{num(n)}</b>
            <small className="block text-[0.72rem] leading-tight text-fg-muted">{label}</small>
          </li>
        ))}
      </ul>
      <Link href={studioCourseHref(c.course_id)} className={buttonClasses({ variant: "secondary", size: "sm", className: "shrink-0 gap-1.5 self-start sm:self-center" })}>
        Open <Icon name="arrowRight" className="h-4 w-4" />
      </Link>
    </article>
  );
}

/**
 * Admin dashboard section: the learning KPI strip + the top courses as compact rows. Self-contained
 * (its own request); renders nothing until loaded or if the api is older and has no overview route.
 */
export function AdminCoursesSection() {
  const res = useResource<CoursesOverview>("admin/courses/overview");
  const d = res.data;
  if (res.error || !d) return null;
  const top = topCourses(d.courses);
  return (
    <Card title="Courses & learning" icon="book" description="Running and upcoming courses first." padding="none" actions={<ViewAllLink href="/admin/courses">All courses</ViewAllLink>}>
      <div className="border-b border-line bg-surface-subtle/60 p-4 sm:px-5">
        <CourseKpis data={d} compact />
      </div>
      {top.length ? (
        <div className="divide-y divide-line">
          {top.map((c) => (
            <CourseRow key={c.course_id} course={c} />
          ))}
        </div>
      ) : (
        <div className="p-5">
          <EmptyState variant="inline" icon="book" title="No courses yet" description="Courses created in the content studio show up here." />
        </div>
      )}
    </Card>
  );
}
