/** Trainer / assessment DTOs, verified against apps/api (see per-type comments). */

/** ASM-03/05/06/09 test. verified: app/modules/assessments/studio.py `test_out` */
export interface TestSummary {
  id: string;
  organization_id: string | null;
  test_kind:
    | "practice_set"
    | "mock"
    | "company_mock"
    | "diagnostic"
    | "course_quiz"
    | "drive"
    | string;
  title: string;
  slug: string | null;
  company_id: string | null;
  company_path_id: string | null;
  status: "draft" | "published" | "closed" | "archived" | string;
  version: number;
  duration_seconds: number | null;
  grace_seconds: number | null;
  navigation_mode: string;
  attempts_allowed: number | null;
  grading_method: string;
  shuffle_questions: boolean;
  shuffle_options: boolean;
  review_policy: Record<string, unknown> | null;
  integrity_settings: Record<string, boolean> | null;
  /** Decimal serialised as a string */
  pass_percentage: string | null;
  is_free: boolean;
  available_from: string | null;
  available_until: string | null;
  settings_locked_at: string | null;
  published_at: string | null;
  /** ADM-49 owning batch (set when created with `batch_id`); null for legacy/studio tests. */
  batch_id?: string | null;
}

export type ReleaseMode = "immediate" | "after_window" | "scheduled" | "manual";

/** ASM-10/11 test assignment. verified: app/modules/assessments/studio.py `assignment_out` */
export interface TestAssignment {
  id: string;
  test_id: string;
  organization_id: string | null;
  batch_id: string | null;
  available_from: string;
  available_until: string;
  attempts_allowed: number | null;
  release_mode: ReleaseMode;
  results_release_at: string | null;
}

/** ASM-13/14 override. verified: app/modules/assessments/studio.py `override_out` */
export interface Override {
  id: string;
  test_id: string;
  test_assignment_id: string | null;
  user_id: string | null;
  batch_id: string | null;
  extra_time_seconds: number;
  extra_attempts: number;
  window_extension_seconds: number;
  reason: string;
  granted_by: string;
  created_at: string | null;
}

/**
 * ASM-15 attempt row. verified: app/modules/assessments/studio.py list_attempts.
 * Decimals arrive as strings. No student name or event log is returned.
 */
export interface AttemptRow {
  attempt_id: string;
  user_id: string;
  attempt_no: number;
  status: string;
  submit_reason: string | null;
  started_at: string | null;
  submitted_at: string | null;
  rebind_count: number;
  integrity_status: string;
  score: string | null;
  max_score: string | null;
  percentage: string | null;
}

/** ASM-16 release response. verified: app/modules/assessments/studio.py release_results */
export interface ReleaseResult {
  test_assignment_id: string;
  released_at: string;
  results_released: number;
}

/** LRN-14/15 assignment. verified: app/modules/learning/router.py `_assignment_out` */
export interface Assignment {
  id: string;
  title: string;
  instructions_md: string;
  submission_type: "file" | "text" | "link" | "code";
  max_score: number;
  rubric: Record<string, unknown> | null;
  allowed_file_types: string[];
  course_id: string | null;
  batch_id: string | null;
  available_from: string | null;
  due_at: string | null;
  late_until: string | null;
  late_penalty_pct: number;
  max_attempts: number;
  status: "active" | "archived" | string;
  grades_released: boolean;
  window: string;
}

/** `GET /assignments?scope=mine` row. verified: app/modules/learning/router.py list_assignments */
export interface AssignmentSummary extends Assignment {
  assignment_id: string;
  batch_name: string | null;
  max_points: number;
  pending_count: number;
}

/** LRN-16 submission (staff view). verified: app/modules/learning/router.py `_submission_out(show_grade=True)` */
export interface Submission {
  id: string;
  assignment_id: string;
  user_id: string;
  attempt_no: number;
  status: "submitted" | "late" | "graded" | "returned" | string;
  submitted_at: string | null;
  body_text: string | null;
  link_url: string | null;
  file_s3_keys: string[];
  code_submission_id: string | null;
  returned_reason: string | null;
  /** Final score after any late penalty. */
  score: number | null;
  /** The grader's score before the late penalty (BE-08). */
  raw_score?: number | null;
  /** Late penalty applied, when the submission was late (BE-08). */
  late_penalty_pct?: number | null;
  rubric_scores: Record<string, unknown> | null;
  feedback_md: string | null;
  graded_at: string | null;
}

/* ------------------------------------------------------------ integrity (ASM-19/20) */

export type IntegrityOutcome = "no_action" | "refer_security" | "invalidate";

/** Advisory signal counts for one attempt (never IPs). */
export interface IntegritySignals {
  focus_lost: number;
  fullscreen_exit: number;
  paste: number;
  disconnect: number;
  rebind: number;
  rebind_refused: number;
  reattach_same_device: number;
  session_revoked_security: number;
  code_submit_burst: number;
  similarity_flags: number;
}

export interface IntegrityDecision {
  decision_id: string;
  outcome: IntegrityOutcome;
  note: string;
  decided_at: string;
  decided_by: string;
  security_case_ref: string | null;
}

/** ASM-19 `GET /integrity/flags` row (advisory, "review recommended"). */
export interface IntegrityFlag {
  attempt_id: string;
  test_id: string;
  test_title: string;
  user_id: string;
  student_name: string | null;
  organization_id: string | null;
  batch_id: string | null;
  attempt_status: string;
  attempt_no: number;
  started_at: string;
  submitted_at: string | null;
  integrity_status:
    "none" | "review_recommended" | "cleared" | "invalidated" | string;
  signals: IntegritySignals;
  reasons: { code: string; label: string; count: number; threshold: number }[];
  recommendation: "review_recommended";
  status: "open" | "decided";
  decision: IntegrityDecision | null;
}

export interface IntegrityFlagPage {
  data: IntegrityFlag[];
  page: { next_cursor: string | null; has_more: boolean; limit: number };
  thresholds: Record<string, number>;
}

/** ASM-20 response. */
export interface IntegrityDecisionResult {
  decision_id: string;
  attempt_id: string;
  outcome: IntegrityOutcome;
  note: string;
  decided_at: string;
  decided_by: string;
  attempt_status: string;
  integrity_status: string;
  security_case_ref: string | null;
}

/* ------------------------------------------------------------------ report (ASM-22) */

export interface ItemStat {
  question_version_id: string;
  question_id: string | null;
  section_title: string | null;
  position: number;
  n: number;
  difficulty_p: number | null;
  discrimination: number | null;
  suppressed: boolean;
}

/** `GET /tests/{test_id}/report`. distribution/submissions/sections are null for item-stats-only viewers. */
export interface TestReport {
  test_id: string;
  title: string;
  scope: "full" | "item_stats_only";
  k_min: number;
  attempts_count: number;
  distribution: {
    buckets: { label: string; from: number; to: number; count: number }[];
    mean: number | null;
    median: number | null;
  } | null;
  submissions: {
    submitted: number;
    auto_submitted: number;
    admin_force: number;
    total: number;
  } | null;
  sections:
    | {
        section_id: string;
        title: string;
        position: number;
        avg_time_seconds: number | null;
        attempts: number;
      }[]
    | null;
  items: { suppressed: boolean; reason: string | null; data: ItemStat[] };
}
