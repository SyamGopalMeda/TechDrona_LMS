"use client";

import type { ActivityTrackerHandle } from "@/lib/analytics/use-activity-tracker";
import { CodingWorkspace } from "./CodingWorkspace";

export interface CodingQuestionProps {
  /** `coding_problem_id` from the test item (QuestionDelivery). */
  problemId: string;
  /** Problem slug when the item carries one; otherwise COD-03 is opened by id. */
  slug?: string | null;
  attemptId: string;
  /** Called with the accepted submission id; the runner saves it as the answer `{submission_id}`. */
  onSubmitted?: (submissionId: string) => void;
  /** The attempt's tracker: editor focus/blur and edit counts are reported on the test page instance. */
  tracker?: ActivityTrackerHandle;
}

/**
 * COD-004: coding question inside a timed test. COD-03 accepts the problem id, and every coding
 * call (COD-03/04/05, run, submit) carries `attempt_id`, so access comes from the in-progress
 * attempt rather than a coding entitlement (w2a weblearn R3).
 */
export function CodingQuestion({ problemId, slug, attemptId, onSubmitted, tracker }: CodingQuestionProps) {
  return <CodingWorkspace slug={slug || problemId} attemptId={attemptId} embedded onSubmitted={onSubmitted} tracker={tracker} />;
}
