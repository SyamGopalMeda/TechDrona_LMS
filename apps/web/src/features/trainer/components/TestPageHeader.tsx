"use client";

import type { ReactNode } from "react";
import { PageHeader, StatusBadge } from "@/components/ui";
import { useGradingBase } from "../shared/portal-base";
import { useApi, seg } from "../shared/use-api";
import type { TestSummary } from "../lib/types";

export type TestPage = "attempts" | "evaluation" | "overrides" | "report";

export const TEST_PAGE_LABEL: Record<TestPage, string> = {
  attempts: "Attempt log",
  evaluation: "Evaluation",
  overrides: "Overrides",
  report: "Test report",
};

/**
 * Header for the per-test pages (attempts, evaluation, overrides, report) in the Trainer and
 * Evaluator portals: breadcrumbs "Tests / {test} / {page}", the test's name as the h1 and its
 * status beside it. The name comes from `GET studio/tests/{id}`; while it loads, or when the
 * viewer can't read the definition, the page name stands in (never an id).
 */
export function TestPageHeader({
  testId,
  page,
  description,
  actions,
}: {
  testId: string;
  page: TestPage;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  const { base } = useGradingBase();
  const test = useApi<Pick<TestSummary, "id" | "title" | "status">>(`studio/tests/${seg(testId)}`);
  const label = TEST_PAGE_LABEL[page];
  const name = test.data?.title;
  return (
    <PageHeader
      breadcrumbs={[{ label: "Tests", href: `${base}/tests` }, ...(name ? [{ label: name }] : []), { label }]}
      eyebrow={name ? label : undefined}
      title={name ?? label}
      meta={test.data?.status ? <StatusBadge status={test.data.status} /> : undefined}
      description={description}
      actions={actions}
    />
  );
}
