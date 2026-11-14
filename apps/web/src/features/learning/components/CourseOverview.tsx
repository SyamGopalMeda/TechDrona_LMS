"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, Card, ErrorState, PageHeader, SectionHeader, StatusBadge, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { CourseAccess } from "@/features/catalog/components/CourseAccess";
import { accessOptionsForCourse } from "@/features/catalog/lib/products";
import type { CourseDetailDto, Paged, ProductDto } from "@/features/catalog/lib/types";
import { formatDate, formatDuration, humanize } from "@/features/catalog/lib/format";
import { LinkButton, ProgressBar } from "@/features/catalog/components/LinkButton";
import { lessonHref, useEnrolledCourse } from "../lib/use-course";
import { useResource } from "../lib/use-resource";
import type { CourseLessonRef } from "../lib/types";
import { ContentErrorState, LoadingBlock } from "./States";

export function LessonStatusIcon({ lesson }: { lesson: Pick<CourseLessonRef, "status"> }) {
  if (lesson.status === "completed") return <span aria-label="Completed" className="text-success-fg">✓</span>;
  if (lesson.status === "in_progress") return <span aria-label="In progress" className="text-brand">◐</span>;
  return <span aria-label="Not started" className="text-fg-muted">○</span>;
}

/** STU-005 enrolled course overview (CAT-02 slug → LRN-04). */
export function CourseOverview({ slug }: { slug: string }) {
  const { catalog, course } = useEnrolledCourse(slug);
  const toast = useToast();
  const [migrating, setMigrating] = useState(false);
  const [migrateError, setMigrateError] = useState<unknown>(null);

  if (catalog.error) return <ContentErrorState error={catalog.error} onRetry={catalog.reload} />;
  // LRN-04 answers 404 until the learner is enrolled: show the course and how to get access
  // (the "Explore courses" catalogue links here) instead of "We couldn't find this".
  if (course.error && catalog.data && isApiError(course.error) && course.error.status === 404)
    return <NotEnrolledCourse course={catalog.data} onEnrolled={() => void course.reload()} />;
  if (course.error) return <ContentErrorState error={course.error} onRetry={course.reload} />;
  const c = course.data;
  if (!c) return <LoadingBlock label="Loading course" rows={4} />;

  const first = c.modules.flatMap((m) => m.lessons)[0];
  const next = c.next_lesson?.lesson_id ?? first?.id ?? null;
  const started = c.enrolment.progress_pct > 0;
  const cert = c.certificate;

  async function migrate() {
    setMigrating(true);
    setMigrateError(null);
    try {
      await api.post(`me/courses/${encodeURIComponent(c!.enrolment.course_id)}/migrate-version`, {}, { idempotencyKey: true });
      toast.show({ title: "Switched to the new version of this course.", tone: "success" });
      await course.reload();
    } catch (err) {
      setMigrateError(err);
    } finally {
      setMigrating(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "My learning", href: "/app/learning" }, { label: c.title }]}
        title={c.title}
        description={c.enrolment.expires_at ? `Access until ${formatDate(c.enrolment.expires_at)}` : undefined}
        actions={next ? <LinkButton href={lessonHref(slug, next)}>{started ? "Resume" : "Start course"}</LinkButton> : null}
      />
      <Card>
        <ProgressBar value={c.enrolment.progress_pct} label="Course progress" />
        <p className="mt-2 text-xs text-fg-muted">Progress counts lessons you’ve completed: videos watched to 90% and readings finished.</p>
      </Card>

      {c.version_migration ? (
        <Card title="A new version of this course is available">
          <p className="text-sm text-fg-secondary">{c.version_migration.changelog ?? "Your progress on matching lessons carries over."}</p>
          <Button className="mt-3" variant="secondary" size="sm" onClick={migrate} loading={migrating}>
            Switch to the new version
          </Button>
          {migrateError ? <div className="mt-3"><ErrorState error={migrateError} /></div> : null}
        </Card>
      ) : null}

      {cert ? (
        <Card title="Certificate">
          {cert.status === "issued" ? (
            <p className="text-sm text-fg-secondary">
              <StatusBadge status="verified" label="Issued" /> Download it from{" "}
              <Link href="/app/certificates" className="font-medium text-fg-link">
                Certificates
              </Link>
              .
            </p>
          ) : cert.status === "revoked" ? (
            <p className="text-sm text-fg-secondary">
              <StatusBadge status="revoked" /> This certificate is no longer valid.
            </p>
          ) : (
            <p className="text-sm text-fg-secondary">{("reason" in cert && cert.reason) || (cert.status === "pending" ? "You've met the requirements; your certificate is being issued." : "Complete the course requirements to earn a certificate.")}</p>
          )}
        </Card>
      ) : null}

      <section aria-labelledby="contents-h">
        <SectionHeader id="contents-h" title="Contents" />
        <ol className="space-y-4">
          {c.modules.map((m) => (
            <li key={m.id} className="rounded-xl border border-line bg-surface">
              <h3 className="border-b border-line px-4 py-3 font-display font-bold text-fg-heading">{m.title}</h3>
              <ul className="divide-y divide-line">
                {m.lessons.map((l) => (
                  <li key={l.id} className="flex items-center gap-3 px-4 py-1 text-sm">
                    <LessonStatusIcon lesson={l} />
                    <Link href={lessonHref(slug, l.id)} className="flex min-h-touch flex-1 items-center text-fg hover:text-brand hover:underline focus-visible:shadow-focus focus-visible:outline-none">
                      {l.title}
                    </Link>
                    <span className="text-xs text-fg-muted">{[humanize(l.lesson_type), formatDuration(l.duration_seconds ? l.duration_seconds / 60 : l.est_reading_minutes)].filter(Boolean).join(" · ")}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

/** STU-005 before enrolment: CAT-02 course info, free-preview lessons and the access options. */
export function NotEnrolledCourse({ course, onEnrolled }: { course: CourseDetailDto; onEnrolled: () => void }) {
  const paid = course.price_type !== "free";
  const products = useResource<Paged<ProductDto>>(paid ? "commerce/products" : null);
  const options = paid && products.data ? accessOptionsForCourse(products.data.data, course.id) : [];
  const refundRule = products.data?.data.find((p) => p.refund_rule)?.refund_rule ?? course.refund_rule_text ?? null;
  const preview = new Set(course.free_preview_lesson_ids ?? []);
  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Explore courses", href: "/app/courses" }, { label: course.title }]}
        title={course.title}
        description={course.summary ?? undefined}
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section aria-labelledby="syllabus-h">
          <SectionHeader id="syllabus-h" title="What's inside" />
          <ol className="space-y-4">
            {(course.syllabus ?? []).map((m) => (
              <li key={`${m.position}-${m.title}`} className="rounded-xl border border-line bg-surface">
                <h3 className="border-b border-line px-4 py-3 font-display font-bold text-fg-heading">{m.title}</h3>
                <ul className="divide-y divide-line">
                  {m.lessons.map((l) => (
                    <li key={l.id} className="flex min-h-touch items-center gap-3 px-4 py-1 text-sm">
                      {l.is_free_preview || preview.has(l.id) ? (
                        <Link href={lessonHref(course.slug, l.id)} className="flex-1 text-fg hover:text-brand hover:underline focus-visible:shadow-focus focus-visible:outline-none">
                          {l.title} <span className="text-xs font-medium text-success-fg">· Free preview</span>
                        </Link>
                      ) : (
                        <span className="flex-1 text-fg">{l.title}</span>
                      )}
                      <span className="text-xs text-fg-muted">{[humanize(l.lesson_type), formatDuration(l.duration_seconds ? l.duration_seconds / 60 : l.est_reading_minutes)].filter(Boolean).join(" · ")}</span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </section>
        <Card title={paid ? "Get access" : "Free course"}>
          <p className="mb-3 text-sm text-fg-secondary">
            {paid ? "You're not enrolled in this course yet. Choose an option below, or start it if your plan or batch already includes it." : "You're not enrolled yet. Enrol for free to start learning and track your progress."}
          </p>
          {paid && products.loading && !products.data ? (
            <LoadingBlock label="Loading prices" rows={1} />
          ) : (
            <CourseAccess course={{ ...course, refund_rule: refundRule, access_options: options }} signedIn onEnrolled={onEnrolled} />
          )}
        </Card>
      </div>
    </div>
  );
}
