"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, FormField, PageHeader, Pagination, Select, Table, nextCursorStack, previousCursorStack, type Column } from "@/components/ui";
import { useLoader } from "@/features/assessment/lib/use-resource";
import { codingApi, difficultyLabel } from "../lib/api";
import type { ProblemListItem } from "../lib/types";

const STATUS_LABEL: Record<string, string> = { solved: "✓ Solved", attempted: "◐ Attempted", not_started: "Not started" };

/** COD-001 problem list (COD-02). */
export function ProblemList() {
  const [difficulty, setDifficulty] = useState("");
  const [status, setStatus] = useState("");
  const [stack, setStack] = useState<(string | undefined)[]>([undefined]);
  const cursor = stack[stack.length - 1];
  // COD-02 filters by difficulty (1..5) only; the status filter applies to the loaded page.
  const res = useLoader(`${difficulty}|${cursor ?? ""}`, () => codingApi.problems({ difficulty: difficulty ? Number(difficulty) : undefined, cursor }));
  const rows = res.data?.data.filter((p) => !status || p.status === status);

  const columns: Column<ProblemListItem>[] = [
    {
      key: "title",
      header: "Problem",
      cell: (p) => (
        <Link className="font-medium text-fg-link underline" href={`/app/coding/${encodeURIComponent(p.slug)}`}>
          {p.title}
          {!p.entitled ? <span className="ml-1 text-xs text-fg-muted">🔒 Paid</span> : null}
        </Link>
      ),
    },
    { key: "difficulty", header: "Difficulty", cell: (p) => <Badge>{difficultyLabel(p.difficulty)}</Badge> },
    { key: "status", header: "Status", cell: (p) => STATUS_LABEL[p.status] ?? p.status },
  ];

  const resetPaging = () => setStack([undefined]);

  return (
    <div>
      <PageHeader title="Coding" description="Practise problems in your language. Run checks the samples; Submit checks every hidden test." />
      <div className="mb-4 flex flex-wrap gap-4">
        <FormField label="Difficulty">
          {(p) => (
            <Select
              {...p}
              value={difficulty}
              onChange={(e) => {
                setDifficulty(e.target.value);
                resetPaging();
              }}
              options={[
                { value: "", label: "All" },
                ...[1, 2, 3, 4, 5].map((d) => ({ value: String(d), label: `${d} · ${difficultyLabel(d)}` })),
              ]}
            />
          )}
        </FormField>
        <FormField label="Status">
          {(p) => (
            <Select
              {...p}
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
              }}
              options={[
                { value: "", label: "All" },
                { value: "not_started", label: "Not started" },
                { value: "attempted", label: "Attempted" },
                { value: "solved", label: "Solved" },
              ]}
            />
          )}
        </FormField>
      </div>
      <Table
        caption="Coding problems"
        columns={columns}
        rows={rows}
        rowKey={(p) => p.problem_id}
        loading={res.loading}
        error={res.error}
        onRetry={() => void res.reload()}
        empty={{ title: "No problems match these filters", description: "Try a different difficulty or status." }}
        footer={
          <Pagination
            hasMore={!!res.data?.meta.has_more}
            hasPrevious={stack.length > 1}
            loading={res.loading}
            onNext={() => setStack((s) => nextCursorStack(s, res.data?.meta.next_cursor ?? null))}
            onPrevious={() => setStack((s) => previousCursorStack(s))}
          />
        }
      />
    </div>
  );
}
