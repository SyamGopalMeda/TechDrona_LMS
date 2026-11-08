"use client";

import Link from "next/link";
import { StatTile } from "@/components/ui";
import type { Page } from "@/lib/api/client";
import { useApi } from "@/features/trainer/shared/use-api";
import type { CourseSummary, QuestionReportPage, QuestionSummary } from "../lib/types";
import { courseStatus } from "./Courses";

/** n (or n+ when the page was full): counts come from list endpoints; there is no totals API. */
function countOf(n: number | undefined, full: boolean): string | null {
  if (n === undefined) return null;
  return full ? `${n}+` : String(n);
}

/** CMS-001 content dashboard: review backlog (PLC-04 `{items}` filtered by version status, CAT-08 `{data, page}`). */
export function StudioDashboard() {
  // PLC-04 version_status (audit ADM-54): counts the whole backlog, not just the newest 200 questions.
  const questions = useApi<{ items: QuestionSummary[] }>("studio/questions", { version_status: "awaiting_review", limit: 200 });
  const drafts = useApi<{ items: QuestionSummary[] }>("studio/questions", { status: "draft", limit: 200 });
  const courses = useApi<Page<CourseSummary>>("studio/courses", { limit: 100 });
  // PLC-34: open_count is the queue total; a 403 (no question.edit) shows a dash.
  const reports = useApi<QuestionReportPage>("studio/question-reports", { status: "open", limit: 1 });

  const qItems = questions.error ? undefined : questions.data?.items;
  const qReview = countOf(qItems?.filter((x) => x.latest_version?.status === "in_review" && !x.latest_version.reviewed).length, (qItems?.length ?? 0) >= 200);
  const qDrafts = countOf(drafts.error ? undefined : drafts.data?.items.length, (drafts.data?.items.length ?? 0) >= 200);
  const cData = courses.error ? undefined : courses.data;
  const cReview = countOf(cData?.data.filter((c) => courseStatus(c) === "in_review").length, !!cData?.page.has_more);

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Questions in review" value={qReview} hint={<Link className="text-fg-link underline" href="/studio/review">Open review queue</Link>} />
        <StatTile label="Draft questions" value={qDrafts} hint={<Link className="text-fg-link underline" href="/studio/questions">Question bank</Link>} />
        <StatTile label="Courses in review" value={cReview} hint={<Link className="text-fg-link underline" href="/studio/review">Open review queue</Link>} />
        <StatTile
          label="Open error reports"
          value={reports.error ? "—" : reports.data ? String(reports.data.open_count) : null}
          hint={<Link className="text-fg-link underline" href="/studio/reports/errors">Triage reports</Link>}
        />
      </div>
      <ul className="grid gap-2 text-sm sm:grid-cols-2">
        <li><Link className="text-fg-link underline" href="/studio/courses">Author courses</Link></li>
        <li><Link className="text-fg-link underline" href="/studio/questions/new">Write a question</Link></li>
        <li><Link className="text-fg-link underline" href="/studio/coding">Coding problems</Link></li>
        <li><Link className="text-fg-link underline" href="/studio/tests">Test blueprints</Link></li>
      </ul>
    </div>
  );
}
