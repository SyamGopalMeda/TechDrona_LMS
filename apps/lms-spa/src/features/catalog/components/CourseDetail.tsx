import { asyncComponent } from "@/spa/async";
import { Badge, Card } from "@/components/ui";
import { formatDuration, humanize } from "../lib/format";
import { accessOptionsForCourse } from "../lib/products";
import { serverLoad } from "../lib/server";
import type { AccessOptionDto, CourseDetailDto, Paged, ProductDto } from "../lib/types";
import { CourseAccess } from "./CourseAccess";

const minutes = (secs: number | null | undefined) => (secs ? secs / 60 : null);

/**
 * PUB-003 course detail (server-rendered; CAT-02 public read). CAT-02 carries no prices, so a
 * paid course's options come from COM-01 products that unlock this course.
 */
async function CourseDetail__server({ course, signedIn }: { course: CourseDetailDto; signedIn: boolean }) {
  const modules = course.syllabus ?? [];
  const lessonCount = modules.reduce((n, m) => n + m.lessons.length, 0);
  const meta = [humanize(course.level), course.language, lessonCount ? `${lessonCount} lessons` : null, formatDuration(minutes(course.duration_seconds))].filter(Boolean);
  let accessOptions: AccessOptionDto[] = [];
  let refundRule = course.refund_rule_text ?? null;
  if (course.price_type === "paid") {
    const products = await serverLoad<Paged<ProductDto>>("commerce/products");
    if (products.ok) {
      accessOptions = accessOptionsForCourse(products.data.data, course.id);
      refundRule = products.data.data.find((p) => p.refund_rule)?.refund_rule ?? refundRule;
    }
  }
  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_20rem]">
      <div className="min-w-0 space-y-8">
        <header>
          {course.category ? <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{humanize(course.category)}</p> : null}
          <h1 className="mt-1 font-display text-3xl font-bold text-fg">{course.title}</h1>
          {course.summary ? <p className="mt-2 max-w-prose text-fg-secondary">{course.summary}</p> : null}
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-fg-muted">
            {meta.length ? <span>{meta.join(" · ")}</span> : null}
            {typeof course.completeness_pct === "number" && course.completeness_pct < 100 ? (
              <Badge tone="info">{`Content ${Math.round(course.completeness_pct)}% complete`}</Badge>
            ) : null}
          </div>
        </header>

        {course.outcomes && course.outcomes.length > 0 ? (
          <section aria-labelledby="outcomes-h">
            <h2 id="outcomes-h" className="font-display text-lg font-semibold text-fg">
              What you’ll be able to do
            </h2>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-fg-secondary">
              {course.outcomes.map((o) => (
                <li key={o}>{o}</li>
              ))}
            </ul>
          </section>
        ) : null}

        <section aria-labelledby="syllabus-h">
          <h2 id="syllabus-h" className="font-display text-lg font-semibold text-fg">
            Syllabus
          </h2>
          {modules.length === 0 ? (
            <p className="mt-2 text-sm text-fg-muted">The syllabus for this course hasn’t been published yet.</p>
          ) : (
            <ol className="mt-3 space-y-3">
              {modules.map((m, i) => (
                <li key={`${m.position}-${m.title}`} className="rounded-lg border border-line bg-surface">
                  <details open={i === 0}>
                    <summary className="cursor-pointer px-4 py-3 font-medium text-fg focus-visible:shadow-focus focus-visible:outline-none">
                      {m.title} <span className="text-sm font-normal text-fg-muted">· {m.lessons.length} lessons</span>
                    </summary>
                    <ul className="divide-y divide-line border-t border-line">
                      {m.lessons.map((l) => (
                        <li key={l.id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
                          <span className="text-fg-secondary">
                            {l.title}
                            {l.lesson_type ? <span className="text-fg-muted"> · {humanize(l.lesson_type)}</span> : null}
                          </span>
                          <span className="flex shrink-0 items-center gap-2 text-xs text-fg-muted">
                            {l.is_free_preview ? <Badge tone="brand">Free preview</Badge> : null}
                            {formatDuration(minutes(l.duration_seconds) ?? l.est_reading_minutes)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </details>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      <aside aria-label="Access" className="lg:sticky lg:top-6 lg:self-start">
        <Card title="Get access">
          <CourseAccess course={{ ...course, refund_rule: refundRule, access_options: accessOptions }} signedIn={signedIn} />
        </Card>
      </aside>
    </div>
  );
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export const CourseDetail = asyncComponent(CourseDetail__server, "features/catalog/components/CourseDetail.tsx#CourseDetail");
