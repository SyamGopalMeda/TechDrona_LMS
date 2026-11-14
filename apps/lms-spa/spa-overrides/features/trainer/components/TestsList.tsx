"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type ReactNode } from "react";
import { Button, LinkButton, Pagination, Table, nextCursorStack, previousCursorStack } from "@/components/ui";
import { useApi, seg } from "../shared/use-api";
import { StatusBadge } from "../shared/ui";
import type { TestSummary } from "../lib/types";
import { AssignTestDialog } from "./AssignTest";
import { NewTestDialog, testKindLabel } from "@/features/studio/components/Tests";

/**
 * "More ▾" disclosure for the secondary per-test pages, so a row shows at most two actions
 * (design-system §3 Table). Links are real links; the menu closes when one is chosen or on Escape.
 */
function MoreLinks({ title, links }: { title: string; links: { href: string; label: string }[] }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const close = () => ref.current?.removeAttribute("open");
  return (
    <details
      ref={ref}
      className="relative"
      onKeyDown={(e) => {
        if (e.key === "Escape" && ref.current?.open) {
          close();
          ref.current.querySelector("summary")?.focus();
        }
      }}
    >
      <summary
        aria-label={`More for ${title}`}
        className="inline-flex min-h-touch cursor-pointer list-none items-center gap-1 rounded-md px-3 text-sm font-semibold text-fg-secondary hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none md:min-h-8 [&::-webkit-details-marker]:hidden"
      >
        More <span aria-hidden="true">▾</span>
      </summary>
      <ul className="absolute right-0 z-dropdown mt-1 w-44 rounded-lg border border-line bg-surface p-1 text-left shadow-lg">
        {links.map((l) => (
          <li key={l.href}>
            <Link
              href={l.href}
              onClick={close}
              className="flex min-h-touch items-center rounded-md px-3 text-sm text-fg no-underline hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none md:min-h-9"
            >
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}

/**
 * Tests in scope (ASM-03) with "Assign" (ASM-10). Trainer (TRN-005) also links to
 * edit / overrides / attempt log / report and can create a test for one of their batches
 * (ASM-04 with `batch_id`, ADM-43). The Evaluator portal (`evaluateOnly`) only links to grading.
 */
export function TestsList({
  batches,
  basePath,
  evaluateOnly = false,
  header,
}: {
  batches: { value: string; label: string }[];
  basePath?: "/trainer" | "/evaluator";
  /** Evaluator portal (plan §4.2): grading links only — no create, edit, assign or overrides. */
  evaluateOnly?: boolean;
  /**
   * Renders the heading above the list with the "New test" button (null when the user can't
   * create), so the one primary action sits in the page/section header instead of floating
   * over the table. Without it the button is shown on its own row.
   */
  header?: (createButton: ReactNode | null) => ReactNode;
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
  const createButton = canCreate ? <Button onClick={() => setCreating(true)}>New test</Button> : null;

  return (
    <>
      {header ? (
        header(createButton)
      ) : createButton ? (
        <div className="mb-3 flex justify-end">{createButton}</div>
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
            cell: (t) => testKindLabel(t.test_kind),
          },
          {
            key: "d",
            header: "Duration",
            priority: "secondary",
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
              <span className="flex flex-wrap items-center justify-end gap-2">
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
                {basePath ? (
                  <LinkButton
                    size="sm"
                    variant={evaluateOnly ? "secondary" : "ghost"}
                    href={`${basePath}/tests/${seg(t.id)}/evaluation`}
                    aria-label={`Evaluate ${t.title}`}
                  >
                    Evaluate
                  </LinkButton>
                ) : null}
                {basePath && evaluateOnly ? (
                  <LinkButton size="sm" variant="ghost" href={`${basePath}/tests/${seg(t.id)}/report`} aria-label={`Report for ${t.title}`}>
                    Report
                  </LinkButton>
                ) : basePath ? (
                  <MoreLinks
                    title={t.title}
                    links={[
                      { href: `${basePath}/tests/${seg(t.id)}/attempts`, label: "Attempts" },
                      { href: `${basePath}/tests/${seg(t.id)}/overrides`, label: "Overrides" },
                      { href: `${basePath}/tests/${seg(t.id)}/report`, label: "Report" },
                    ]}
                  />
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
          description: evaluateOnly
            ? "Tests assigned to your batches appear here when students submit attempts."
            : "Tests you create or that are shared with your batches appear here.",
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
