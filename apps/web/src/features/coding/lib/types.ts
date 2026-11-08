/**
 * Coding DTOs (COD). Request bodies come from the generated OpenAPI schema; response shapes are
 * verified against app/modules/coding/{router,service,schemas}.py.
 */
import type { Body } from "@/lib/api-types";

export type Verdict = "AC" | "WA" | "TLE" | "MLE" | "RE" | "CE" | "PARTIAL" | (string & {});

/** `{data, meta}` cursor envelope — verified: app/core/pagination.py page_meta */
export interface CursorPage<T> {
  data: T[];
  meta: { next_cursor: string | null; has_more: boolean; limit: number };
}

/** verified: app/modules/coding/router.py list_languages data[] */
export interface Language {
  language_key: string;
  display_name: string;
  version?: string | null;
  starter_template?: string | null;
}

/** verified: router.py list_problems data[] */
export interface ProblemListItem {
  problem_id: string;
  slug: string;
  title: string;
  /** 1..5 */
  difficulty: number;
  is_free: boolean;
  /** false → paid problem the student isn't entitled to */
  entitled: boolean;
  status: "solved" | "attempted" | "not_started" | (string & {});
}

/** verified: router.py get_problem samples[] */
export interface SampleCase {
  ordinal: number;
  input: string | null;
  expected_output: string | null;
}

/** verified: router.py get_problem (service.problem_out + samples + languages). Text is Markdown. */
export interface ProblemDetail {
  problem_id: string;
  slug: string;
  title: string;
  version_no: number;
  statement_md: string;
  input_format_md: string | null;
  output_format_md: string | null;
  constraints_md: string | null;
  /** 1..5 */
  difficulty: number;
  limits: { time_limit_ms: number; wall_limit_ms: number; memory_limit_kb: number };
  allowed_languages: string[];
  scoring_mode: string;
  is_free: boolean;
  samples: SampleCase[];
  /** allowed + enabled languages with their starter code */
  languages: { language_key: string; display_name: string; starter_template: string | null }[];
}

/** verified: schemas.py SampleCaseResultOut | HiddenCaseResultOut */
export interface CaseResult {
  ordinal: number;
  is_sample: boolean;
  verdict: Verdict;
  time_ms: number | null;
  memory_kb: number | null;
  /** sample / custom cases only */
  is_custom?: boolean;
  stdout_excerpt?: string | null;
  expected_output?: string | null;
  input?: string | null;
}

export type SubmissionStatus = "queued" | "running" | "completed" | "rejected" | (string & {});

/** verified: schemas.py SubmissionOut (COD-08). Optional fields are absent in the local placeholder
 * created right after 202 Accepted and in history rows (service.history_item). */
export interface Submission {
  submission_id: string;
  problem_id?: string;
  problem_version?: number;
  language_key?: string;
  mode: "run" | "submit" | (string & {});
  status: SubmissionStatus;
  notice?: "judge_degraded" | (string & {}) | null;
  verdict?: Verdict | null;
  score?: number | null;
  max_score?: number | null;
  passed_cases?: number | null;
  total_cases?: number | null;
  max_time_ms?: number | null;
  max_memory_kb?: number | null;
  compile_output?: string | null;
  cases?: CaseResult[];
  queued_at?: string;
  completed_at?: string | null;
  attempt_id?: string | null;
  /** ATT-12 review only (BE-23): the learner's own code. */
  source_code?: string | null;
  /** from the 202 body only */
  queue_position?: number | null;
}

/** verified: service.py accepted_body (202 for run/submit) */
export interface SubmissionAccepted {
  submission_id: string;
  status: SubmissionStatus;
  mode: "run" | "submit";
  queue: string;
  queue_position: number | null;
  problem_version: number;
  poll_url: string;
}

export type RunBody = Body<"coding/problems/{problem_id}/run", "post">;
export type SubmitBody = Body<"coding/problems/{problem_id}/submit", "post">;

/** verified: app/modules/coding/authoring.py draft_out (COD-04/05) */
export interface CodingDraft {
  problem_id: string;
  language_key: string;
  source_code: string;
  size_bytes: number;
  updated_at: string;
}
