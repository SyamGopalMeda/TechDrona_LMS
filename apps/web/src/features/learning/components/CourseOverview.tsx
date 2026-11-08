"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, ErrorState, PageHeader, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { formatDate, formatDuration, humanize } from "@/features/catalog/lib/format";
import { LinkButton, ProgressBar } from "@/features/catalog/components/LinkButton";
import { lessonHref, useEnrolledCourse } from "../lib/use-course";
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
        title={c.title}
        description={c.enrolment.expires_at ? `Access until ${formatDate(c.enrolment.expires_at)}` : undefined}
        actions={next ? <LinkButton href={lessonHref(slug, next)}>{started ? "Resume" : "Start course"}</LinkButton> : null}
      />
      <Card>
        <ProgressBar value={c.enrolment.progress_pct} label="Course progress" />
        <p className="mt-2 text-xs text-fg-muted">Progress counts lessons you’ve completed: videos watched to 90% and readings finished, as recorded by the server.</p>
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
              <Badge tone="success">Issued</Badge> Download it from{" "}
              <Link href="/app/certificates" className="font-medium text-fg-link">
                Certificates
              </Link>
              .
            </p>
          ) : cert.status === "revoked" ? (
            <p className="text-sm text-fg-secondary">
              <Badge tone="danger">Revoked</Badge> This certificate is no longer valid.
            </p>
          ) : (
            <p className="text-sm text-fg-secondary">{("reason" in cert && cert.reason) || (cert.status === "pending" ? "You've met the requirements; your certificate is being issued." : "Complete the course requirements to earn a certificate.")}</p>
          )}
        </Card>
      ) : null}

      <section aria-labelledby="contents-h">
        <h2 id="contents-h" className="mb-3 font-display text-lg font-semibold text-fg">
          Contents
        </h2>
        <ol className="space-y-4">
          {c.modules.map((m) => (
            <li key={m.id} className="rounded-xl border border-line bg-surface">
              <h3 className="border-b border-line px-4 py-3 font-medium text-fg">{m.title}</h3>
              <ul className="divide-y divide-line">
                {m.lessons.map((l) => (
                  <li key={l.id} className="flex items-center gap-3 px-4 py-2 text-sm">
                    <LessonStatusIcon lesson={l} />
                    <Link href={lessonHref(slug, l.id)} className="flex-1 text-fg hover:underline focus-visible:shadow-focus focus-visible:outline-none">
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
