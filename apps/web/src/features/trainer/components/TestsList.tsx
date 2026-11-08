"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Pagination, Table, nextCursorStack, previousCursorStack } from "@/components/ui";
import { useApi, seg } from "../shared/use-api";
import { StatusBadge } from "../shared/ui";
import type { TestSummary } from "../lib/types";
import { AssignTestDialog } from "./AssignTest";
import { NewTestDialog } from "@/features/studio/components/Tests";

/**
 * Tests in scope (ASM-03) with "Assign" (ASM-10). Trainer (TRN-005) also links to
 * edit / overrides / attempt log / report and can create a test for one of their batches
 * (ASM-04 with `batch_id`, ADM-43). The Evaluator portal (`evaluateOnly`) only links to grading.
 */
export function TestsList({
  batches,
  basePath,
  evaluateOnly = false,
}: {
  batches: { value: string; label: string }[];
  basePath?: "/trainer" | "/evaluator";
  /** Evaluator portal (plan §4.2): grading links only — no create, edit, assign or overrides. */
  evaluateOnly?: boolean;
}) {
  // verified: assessments/router.py asm_03_list_tests →
  // {items: test_out[], page: {next_cursor, has_more}} (BE-21 cursor paging).
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const cursor = cursors[cursors.length - 1];
  const tests = useApi<{
    items: TestSummary[];
    page?: { next_cursor: string | null; has_more: boolean };
  }>(
    "studio/tests",
    { cursor },
  );
  const page = tests.data?.page;
  const [assign, setAssign] = useState<TestSummary | null>(null);
  const [creating, setCreating] = useState(false);
  const router = useRouter();
  const canCreate = !evaluateOnly && !!basePath && batches.length > 0;

  return (
    <>
      {canCreate ? (
        <div className="mb-3 flex justify-end">
          <Button onClick={() => setCreating(true)}>New test</Button>
        </div>
      ) : null}
      <Table
        caption="Tests"
        columns={[
          {
            key: "t",
            header: "Test",
            cell: (t: TestSummary) =>
              basePath && !evaluateOnly ? (
                <Link
                  className="text-fg-link underline"
                  href={`${basePath}/tests/${seg(t.id)}/edit`}
                >
                  {t.title}
                </Link>
              ) : (
                t.title
              ),
          },
          {
            key: "k",
            header: "Kind",
            cell: (t) => t.test_kind.replace(/_/g, " "),
          },
          {
            key: "d",
            header: "Duration",
            cell: (t) =>
              t.duration_seconds
                ? `${Math.round(t.duration_seconds / 60)} min`
                : "—",
          },
          {
            key: "s",
            header: "Status",
            cell: (t) => <StatusBadge status={t.status} />,
          },
          {
            key: "a",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (t) => (
              <span className="flex flex-wrap justify-end gap-2">
                {evaluateOnly ? null : (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={t.status !== "published"}
                    onClick={() => setAssign(t)}
                    aria-label={`Assign ${t.title}`}
                  >
                    Assign
                  </Button>
                )}
                {basePath && evaluateOnly ? (
                  <>
                    <Link
                      className="inline-flex h-8 items-center text-sm text-fg-link underline"
                      href={`${basePath}/tests/${seg(t.id)}/evaluation`}
                      aria-label={`Evaluate ${t.title}`}
                    >
                      Evaluation
                    </Link>
                    <Link
                      className="inline-flex h-8 items-center text-sm text-fg-link underline"
                      href={`${basePath}/tests/${seg(t.id)}/report`}
                      aria-label={`Report for ${t.title}`}
                    >
                      Report
                    </Link>
                  </>
                ) : basePath ? (
                  <>
                    <Link
                      className="inline-flex h-8 items-center text-sm text-fg-link underline"
                      href={`${basePath}/tests/${seg(t.id)}/attempts`}
                    >
                      Attempts
                    </Link>
                    <Link
                      className="inline-flex h-8 items-center text-sm text-fg-link underline"
                      href={`${basePath}/tests/${seg(t.id)}/evaluation`}
                    >
                      Evaluation
                    </Link>
                    <Link
                      className="inline-flex h-8 items-center text-sm text-fg-link underline"
                      href={`${basePath}/tests/${seg(t.id)}/overrides`}
                    >
                      Overrides
                    </Link>
                    <Link
                      className="inline-flex h-8 items-center text-sm text-fg-link underline"
                      href={`${basePath}/tests/${seg(t.id)}/report`}
                    >
                      Report
                    </Link>
                  </>
                ) : null}
              </span>
            ),
          },
        ]}
        rows={tests.data?.items}
        rowKey={(t) => t.id}
        loading={tests.loading}
        error={tests.error}
        onRetry={() => void tests.reload()}
        empty={{
          title: "No tests yet",
          description:
            "Tests you create or that are shared with your batches appear here.",
        }}
      />
      {page?.has_more || cursors.length > 1 ? (
        <Pagination
          label="Tests pages"
          hasMore={!!page?.has_more}
          hasPrevious={cursors.length > 1}
          loading={tests.loading}
          onNext={() => setCursors((c) => nextCursorStack(c, page?.next_cursor ?? null))}
          onPrevious={() => setCursors((c) => previousCursorStack(c))}
        />
      ) : null}
      {creating && basePath ? (
        <NewTestDialog
          open
          batches={batches}
          onClose={() => setCreating(false)}
          onCreated={(t) => router.push(`${basePath}/tests/${seg(t.id)}/edit`)}
        />
      ) : null}
      {assign ? (
        <AssignTestDialog
          open
          testId={assign.id}
          testTitle={assign.title}
          batches={batches}
          onClose={() => setAssign(null)}
        />
      ) : null}
    </>
  );
}
