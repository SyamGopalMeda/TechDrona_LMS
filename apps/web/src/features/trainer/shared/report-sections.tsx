"use client";

import { Table } from "@/components/ui";
import { BarList, KFloorNotice, kValue } from "./ui";

/**
 * Batch / org analytics report sections (webstaff R11, w2a R4).
 * verified shapes: apps/api/app/modules/analytics/reports.py `_progress_distribution`,
 * `_lesson_funnel`, `org_report.course_completion_rate`, `_test_participation`.
 * Every count is k-floored on the server: a number, or a string such as "<10".
 */

/** k-floored cell: a number, or "<10" when the group is too small. */
export type KCell = number | string;

export interface ProgressDistribution {
  enrolments: KCell;
  suppressed: boolean;
  buckets: { bucket: string; min_pct: number; max_pct: number; enrolments: KCell }[];
}

export interface LessonFunnelCourse {
  course_id: string;
  course_title: string | null;
  enrolments: KCell;
  suppressed: boolean;
  steps: { lesson_key: string; title: string; is_required: boolean; started: KCell; completed: KCell }[];
}

export interface CourseCompletionRate {
  enrolments: KCell;
  completed: KCell;
  /** share 0–1 */
  rate: KCell;
}

export interface TestParticipation {
  period: { from: string; to: string };
  learners_total: KCell;
  learners_attempted: KCell;
  /** share 0–1 */
  share_attempted: KCell;
  attempts_finished: KCell;
}

const BUCKET_LABEL: Record<string, string> = {
  not_started: "Not started",
  "1-25": "1–25%",
  "26-50": "26–50%",
  "51-75": "51–75%",
  "76-99": "76–99%",
  completed: "Completed",
};

const n = (v: KCell | null | undefined) => (typeof v === "number" ? v.toLocaleString("en-IN") : "Too few to show");
const share = (v: KCell | null | undefined) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "Too few to show");

/** Enrolments per course-progress bucket (6 buckets). */
export function ProgressDistributionView({ data }: { data: ProgressDistribution | null | undefined }) {
  if (!data) return <p className="text-sm text-fg-muted">No course progress yet.</p>;
  if (data.suppressed) return <KFloorNotice compact />;
  return (
    <div className="space-y-2">
      <BarList
        ordinal
        label="Enrolments by course progress"
        items={data.buckets.map((b) => ({ label: BUCKET_LABEL[b.bucket] ?? b.bucket, value: kValue(b.enrolments) }))}
      />
      <p className="text-xs text-fg-muted">{n(data.enrolments)} course enrolments in this batch.</p>
    </div>
  );
}

/** Per course: how many enrolments opened and completed each lesson, in outline order. */
export function LessonFunnelView({ data }: { data: LessonFunnelCourse[] | null | undefined }) {
  if (!data || data.length === 0) return <p className="text-sm text-fg-muted">No lesson activity yet.</p>;
  return (
    <div className="space-y-4">
      {data.map((c) => (
        <div key={c.course_id} className="space-y-2">
          <p className="text-sm font-medium text-fg">
            {c.course_title ?? "Untitled course"} <span className="font-normal text-fg-muted">· {n(c.enrolments)} enrolled</span>
          </p>
          {c.suppressed ? (
            <KFloorNotice compact />
          ) : (
            <Table
              caption={`Lesson funnel: ${c.course_title ?? "course"}`}
              columns={[
                { key: "l", header: "Lesson", cell: (s: LessonFunnelCourse["steps"][number]) => (s.is_required ? s.title : `${s.title} (optional)`) },
                { key: "o", header: "Opened", align: "right", cell: (s) => n(s.started) },
                { key: "c", header: "Completed", align: "right", cell: (s) => n(s.completed) },
              ]}
              rows={c.steps}
              rowKey={(s) => s.lesson_key}
              empty={{ title: "No lessons", description: "This course has no lessons in its current version." }}
            />
          )}
        </div>
      ))}
    </div>
  );
}

export function CourseCompletionView({ data }: { data: CourseCompletionRate | null | undefined }) {
  if (!data) return <p className="text-sm text-fg-muted">No enrolments yet.</p>;
  if (typeof data.rate !== "number") return <KFloorNotice compact />;
  return (
    <p className="text-sm text-fg-secondary">
      <span className="text-2xl font-semibold text-fg tabular-nums">{share(data.rate)}</span> of course enrolments completed ({n(data.completed)} of {n(data.enrolments)}).
    </p>
  );
}

export function TestParticipationView({ data }: { data: TestParticipation | null | undefined }) {
  if (!data) return <p className="text-sm text-fg-muted">No test activity yet.</p>;
  if (typeof data.share_attempted !== "number") return <KFloorNotice compact />;
  return (
    <div className="space-y-1 text-sm text-fg-secondary">
      <p>
        <span className="text-2xl font-semibold text-fg tabular-nums">{share(data.share_attempted)}</span> of students took at least one test ({n(data.learners_attempted)} of {n(data.learners_total)}).
      </p>
      <p>{n(data.attempts_finished)} attempts finished.</p>
      <p className="text-xs text-fg-muted">
        {data.period.from} to {data.period.to} (IST)
      </p>
    </div>
  );
}
