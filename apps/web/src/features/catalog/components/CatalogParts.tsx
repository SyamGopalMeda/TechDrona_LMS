import Link from "next/link";
import { Badge } from "@/components/ui";
import { formatDuration, humanize, languageName } from "../lib/format";
import type { ServerResult } from "../lib/server";
import type { CourseCardDto } from "../lib/types";

/** X state for server-rendered pages: problem title + reference + a retry link (no JS needed). */
export function ServerErrorState({ result, retryHref }: { result: Extract<ServerResult<unknown>, { ok: false }>; retryHref: string }) {
  return (
    <div role="alert" className="rounded-lg border border-danger-border bg-danger-subtle p-5">
      <p className="font-semibold text-danger-fg">{result.title}</p>
      <p className="mt-1 text-sm text-fg-secondary">{result.detail}</p>
      {result.requestId ? (
        <p className="mt-2 text-xs text-fg-muted">
          Reference: <span className="select-all font-mono">{result.requestId}</span>
        </p>
      ) : null}
      <Link href={retryHref} className="mt-3 inline-block text-sm font-medium text-fg-link hover:text-fg-link-hover">
        Try again
      </Link>
    </div>
  );
}

/** CAT-01 cards carry no price (public_card); paid courses show plans on the detail page. */
export function PriceLabel({ course }: { course: Pick<CourseCardDto, "price_type"> }) {
  if (course.price_type === "free") return <Badge tone="success">Free</Badge>;
  return <Badge tone="neutral">Paid</Badge>;
}

export function CourseCard({ course, headingLevel = 2 }: { course: CourseCardDto; headingLevel?: 2 | 3 }) {
  const H = headingLevel === 2 ? "h2" : "h3";
  const meta = [humanize(course.level), languageName(course.language), course.lesson_count ? `${course.lesson_count} lessons` : null, formatDuration(course.duration_seconds ? course.duration_seconds / 60 : null)].filter(Boolean);
  return (
    <article className="flex h-full flex-col rounded-xl border border-line bg-surface p-5 shadow-xs">
      {course.category ? <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{humanize(course.category)}</p> : null}
      <H className="mt-1 font-display text-base font-semibold text-fg">
        <Link href={`/courses/${encodeURIComponent(course.slug)}`} className="hover:underline focus-visible:shadow-focus focus-visible:outline-none">
          {course.title}
        </Link>
      </H>
      {course.summary ? <p className="mt-2 line-clamp-3 text-sm text-fg-secondary">{course.summary}</p> : null}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-4">
        <p className="text-xs text-fg-muted">{meta.join(" · ")}</p>
        <PriceLabel course={course} />
      </div>
    </article>
  );
}

export function CourseGrid({ courses, headingLevel }: { courses: CourseCardDto[]; headingLevel?: 2 | 3 }) {
  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Courses">
      {courses.map((c) => (
        <li key={c.id}>
          <CourseCard course={c} headingLevel={headingLevel} />
        </li>
      ))}
    </ul>
  );
}
