"use client";

import { Card, DashboardHero, QuickActions, StatGrid, StatTile, type QuickAction } from "@/components/ui";
import type { Page } from "@/lib/api/client";
import { useApi } from "@/features/trainer/shared/use-api";
import type { CourseSummary, QuestionReportPage, QuestionSummary } from "../lib/types";
import { courseStatus } from "./Courses";

/** n (or n+ when the page was full): counts come from list endpoints; there is no totals API. */
function countOf(n: number | undefined, full: boolean): string | null {
  if (n === undefined) return null;
  return full ? `${n}+` : String(n);
}

const QUICK_ACTIONS: QuickAction[] = [
  { href: "/studio/courses", label: "Author courses", hint: "Lessons, modules and publishing", icon: "book" },
  { href: "/studio/questions/new", label: "Write a question", hint: "Goes to review before use", icon: "pen" },
  { href: "/studio/coding", label: "Coding problems", hint: "Statements and test cases", icon: "code" },
  { href: "/studio/tests", label: "Template mocks", hint: "Reusable practice tests", icon: "clock" },
  { href: "/studio/media", label: "Media", hint: "Videos and files", icon: "play" },
  { href: "/studio/taxonomy", label: "Taxonomy", hint: "Topics and skills", icon: "grid" },
];

/** CMS-001 content dashboard: review backlog (PLC-04 `{items}` filtered by version status, CAT-08 `{data, page}`). */
export function StudioDashboard() {
  // PLC-04 version_status (audit ADM-54): counts the whole backlog, not just the newest 200 questions.
  const questions = useApi<{ items: QuestionSummary[] }>("studio/questions", { version_status: "awaiting_review", limit: 200 });
  const drafts = useApi<{ items: QuestionSummary[] }>("studio/questions", { status: "draft", limit: 200 });
  const courses = useApi<Page<CourseSummary>>("studio/courses", { limit: 100 });
  // PLC-34: open_count is the queue total; a 403 (no question.edit) shows a dash.
  const reports = useApi<QuestionReportPage>("studio/question-reports", { status: "open", limit: 1 });

  const qItems = questions.error ? undefined : questions.data?.items;
  const qReviewN = qItems?.filter((x) => x.latest_version?.status === "in_review" && !x.latest_version.reviewed).length;
  const qReview = countOf(qReviewN, (qItems?.length ?? 0) >= 200);
  const qDrafts = countOf(drafts.error ? undefined : drafts.data?.items.length, (drafts.data?.items.length ?? 0) >= 200);
  const cData = courses.error ? undefined : courses.data;
  const cReviewN = cData?.data.filter((c) => courseStatus(c) === "in_review").length;
  const cReview = countOf(cReviewN, !!cData?.page.has_more);
  const openReports = reports.error ? undefined : reports.data?.open_count;

  return (
    <div className="space-y-6">
      <DashboardHero title="Content dashboard" description="What is waiting for review, and shortcuts to the content you author.">
      <StatGrid>
        <StatTile icon="hourglass" label="Questions in review" value={qReview} hint="Open review queue" href="/studio/review" tone={qReviewN ? "warning" : "neutral"} />
        <StatTile icon="pen" label="Draft questions" value={qDrafts} hint="All questions" href="/studio/questions" tone="neutral" />
        <StatTile icon="book" label="Courses in review" value={cReview} hint="Open review queue" href="/studio/review" tone={cReviewN ? "warning" : "neutral"} />
        <StatTile
          icon="alert"
          label="Open error reports"
          value={reports.error ? "—" : openReports !== undefined ? String(openReports) : null}
          hint="Triage reports"
          href="/studio/reports/errors"
          tone={openReports ? "highlight" : "neutral"}
        />
      </StatGrid>
      </DashboardHero>
      <Card title="Quick actions" icon="bolt">
        <QuickActions items={QUICK_ACTIONS} columns={3} />
      </Card>
    </div>
  );
}
