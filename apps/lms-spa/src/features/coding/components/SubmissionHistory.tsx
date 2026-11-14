"use client";

import { useState } from "react";
import { PageHeader, Pagination, Table, nextCursorStack, previousCursorStack, type Column } from "@/components/ui";
import { formatIstDateTime } from "@/features/assessment/lib/format";
import { useLoader } from "@/features/assessment/lib/use-resource";
import { codingApi } from "../lib/api";
import type { Submission } from "../lib/types";
import { VerdictChip } from "./VerdictPanel";

/** COD-003 submission history (COD-10). */
export function SubmissionHistory({ slug }: { slug: string }) {
  const problem = useLoader(slug, () => codingApi.problem(slug));
  const [stack, setStack] = useState<(string | undefined)[]>([undefined]);
  const cursor = stack[stack.length - 1];
  const pid = problem.data?.problem_id ?? null;
  const res = useLoader(pid ? `${pid}|${cursor ?? ""}` : null, () => codingApi.history(pid!, cursor));

  const columns: Column<Submission>[] = [
    { key: "when", header: "Submitted", cell: (s) => formatIstDateTime(s.queued_at) },
    { key: "lang", header: "Language", cell: (s) => s.language_key ?? "—" },
    { key: "verdict", header: "Verdict", cell: (s) => (s.status === "completed" ? <VerdictChip verdict={s.verdict} /> : s.status) },
    { key: "passed", header: "Tests passed", align: "right", cell: (s) => (s.total_cases ? `${s.passed_cases ?? 0}/${s.total_cases}` : "—") },
    { key: "score", header: "Score", align: "right", cell: (s) => (s.score ?? "—") },
  ];

  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: "Coding", href: "/app/coding" },
          { label: problem.data?.title ?? "Problem", href: `/app/coding/${encodeURIComponent(slug)}` },
          { label: "Submissions" },
        ]}
        title="Submissions"
        description={problem.data?.title ? `Your submissions for ${problem.data.title}.` : undefined}
      />
      <Table
        caption="My submissions"
        columns={columns}
        rows={res.data?.data}
        rowKey={(s) => s.submission_id}
        loading={problem.loading || res.loading}
        error={problem.error ?? res.error}
        onRetry={() => void (problem.error ? problem.reload() : res.reload())}
        empty={{ title: "No submissions yet", description: "Submit your code from the problem page to see it here." }}
        footer={
          <Pagination
            hasMore={!!res.data?.meta.has_more}
            hasPrevious={stack.length > 1}
            onNext={() => setStack((s) => nextCursorStack(s, res.data?.meta.next_cursor ?? null))}
            onPrevious={() => setStack((s) => previousCursorStack(s))}
          />
        }
      />
    </div>
  );
}
