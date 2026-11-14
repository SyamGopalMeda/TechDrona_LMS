/**
 * Structured assignments (sections + questions, allocations, evaluation, learner workspace).
 * Shapes follow the learning-module contract for `submission_type: "structured"`. The generated
 * API types do not include these endpoints yet; switch to `Schema<...>` once they are regenerated.
 */

import type { AssignmentDto } from "../lib/types";

export type ItemType = "mcq_single" | "mcq_multi" | "numeric" | "fill_blank" | "coding" | "essay" | "short_text" | "file";
export type InlineItemType = "essay" | "short_text" | "file" | "coding";
export type GradingEngine = "pure_ai" | "ai_human" | "pure_objective" | "adaptive" | "pure_manual";

export interface FieldIssue {
  field: string;
  code: string;
  message: string;
}

export interface AssignmentOut extends AssignmentDto {
  organization_id: string | null;
  ai_help_enabled: boolean;
  ai_help_limit: number | null;
  structured: boolean;
  section_count?: number;
  item_count?: number;
}

/** Row of `GET /assignments?scope=mine` (staff list: assignment fields + list extras). */
export interface StaffAssignmentRow extends Partial<AssignmentOut> {
  id?: string;
  assignment_id?: string;
  title: string;
  submission_type: string;
  batch_name?: string | null;
  pending_count?: number;
}

export interface ItemOption {
  option_id: string;
  label: string;
  html: string;
}

export interface RubricCriterion {
  key: string;
  label: string;
  max_points: number;
}

export interface ItemStaff {
  id: string;
  position: number;
  source: "bank" | "inline";
  item_type: ItemType | (string & {});
  question_id: string | null;
  question_version_id: string | null;
  coding_problem_id: string | null;
  prompt_md: string | null;
  stem_html: string | null;
  options: ItemOption[];
  marks: number;
  rubric: { criteria: RubricCriterion[] } | null;
  reference_answer_md: string | null;
}

export interface SectionStaff {
  id: string;
  title: string;
  position: number;
  max_score: number | null;
  marks_total: number;
  items: ItemStaff[];
}

export interface AllocationOut {
  id: string;
  assignment_id: string;
  batch_id: string | null;
  batch_name: string | null;
  user_ids: string[];
  visible_from: string | null;
  visible_until: string | null;
  start_at: string | null;
  due_at: string;
  section_engines: Record<string, GradingEngine>;
  evaluator_ids: string[];
  extensions: Record<string, string>;
  status: "active" | "revoked" | (string & {});
  created_at: string;
}

export interface StructureOut {
  assignment: AssignmentOut;
  locked: boolean;
  sections: SectionStaff[];
  marks: { allocated: number; total: number; ok: boolean; issues: FieldIssue[] };
  allocations: AllocationOut[];
}

export type StructureItemIn =
  | { source: "bank"; question_id: string; question_version_id?: string | null; marks: number }
  | {
      source: "inline";
      item_type: InlineItemType;
      prompt_md: string;
      coding_problem_id?: string | null;
      marks: number;
      rubric?: { criteria: RubricCriterion[] } | null;
      reference_answer_md?: string | null;
    };

export interface StructureIn {
  sections: { title: string; max_score?: number | null; items: StructureItemIn[] }[];
}

export interface AssignmentCreateIn {
  /** Omit both batch_id and course_id for a company-wide assignment (platform staff only). */
  batch_id?: string;
  course_id?: string;
  title: string;
  submission_type: "structured";
  max_score: number;
  instructions_md?: string;
  ai_help_enabled?: boolean;
  ai_help_limit?: number | null;
}

export interface AssignmentPatchIn {
  title?: string;
  instructions_md?: string;
  max_score?: number;
  ai_help_enabled?: boolean;
  ai_help_limit?: number | null;
  status?: string;
}

export interface AllocationIn {
  batch_id?: string;
  user_ids?: string[];
  visible_from?: string | null;
  visible_until?: string | null;
  start_at?: string | null;
  due_at: string;
  section_engines: Record<string, GradingEngine>;
  evaluator_ids: string[];
}

export interface AllocationPatchIn {
  visible_from?: string | null;
  visible_until?: string | null;
  start_at?: string | null;
  due_at?: string;
  section_engines?: Record<string, GradingEngine>;
  evaluator_ids?: string[];
  status?: "revoked";
}

/* ------------------------------------------------------------------ evaluation */

export interface EvaluationRow {
  submission_id: string;
  user_id: string;
  learner_name: string | null;
  learner_email: string | null;
  status: string;
  submitted_at: string | null;
  late: boolean;
  finalized: boolean;
  finalized_marks: number;
  score: number | null;
  max_score: number;
  ai_pending: number;
  ai_queued: number;
  needs_review: number;
  ai_help_used: number;
  regrade_open: boolean;
  flags: string[];
}

export interface EvaluationOut {
  assignment: AssignmentOut;
  submission_count: number;
  max_score: number;
  published: boolean;
  sections: { id: string; title: string; max_marks: number; avg_marks: number | null }[];
  rows: EvaluationRow[];
}

export interface AIGradingQueued {
  queued_items: number;
  auto_scored_items: number;
  submissions: number;
}

export interface JudgeSummary {
  status: string;
  verdict: string | null;
  score: number | null;
  max_score: number | null;
  passed_cases: number | null;
  total_cases: number | null;
}

export interface ItemCode {
  language_key: string;
  source_code: string;
  submission_id: string | null;
  judge: JudgeSummary | null;
}

export interface ItemAI {
  status: "none" | "queued" | "pending" | "failed" | "accepted" | (string & {});
  marks: number | null;
  feedback_md: string | null;
  confidence: number | null;
  error: string | null;
}

/** Note: `source` here is the grading source (auto/ai/human), not the item origin. */
export interface ReviewItem extends Omit<ItemStaff, "source"> {
  response: ItemResponse | null;
  code: ItemCode | null;
  auto_marks: number | null;
  ai: ItemAI | null;
  suggested_marks: number | null;
  final_marks: number | null;
  final_feedback_md: string | null;
  source: "auto" | "ai" | "human" | null;
}

export interface StaffSubmission {
  id: string;
  assignment_id: string;
  user_id?: string;
  status: string;
  submitted_at: string | null;
  file_s3_keys?: string[];
  score?: number | null;
  feedback_md?: string | null;
}

export interface ReviewOut {
  submission: StaffSubmission;
  learner: { user_id: string; name: string | null; email: string | null };
  sections: { id: string; title: string; engine: GradingEngine | null; items: ReviewItem[] }[];
  totals: { final: number | null; suggested: number; max: number };
}

export interface FinalizeIn {
  items: { item_id: string; marks: number; feedback_md?: string; override_reason?: string }[];
  feedback_md?: string;
}

export interface RegradeOut {
  id: string;
  submission_id: string;
  assignment_id: string;
  user_id: string;
  learner_name: string | null;
  item_id: string | null;
  reason: string;
  status: "open" | "resolved" | "rejected" | (string & {});
  resolution_note: string | null;
  resolved_at: string | null;
  created_at: string;
}

/* -------------------------------------------------------------------- learner */

/** Saved answer for one item (shape depends on item_type). */
export type ItemResponse =
  | { option_ids: string[] }
  | { value: string }
  | { text: string }
  | { file_s3_keys: string[] }
  | { language_key: string; source_code: string; submission_id?: string | null }
  | Record<string, unknown>;

export interface WorkspaceItem {
  id: string;
  position: number;
  item_type: ItemType | (string & {});
  marks: number;
  prompt_md: string | null;
  stem_html: string | null;
  options: ItemOption[];
  coding_problem_id: string | null;
  response: ItemResponse | null;
  saved_at: string | null;
}

export interface WorkspaceOut {
  assignment: AssignmentOut;
  schedule: {
    visible_from: string | null;
    visible_until: string | null;
    start_at: string | null;
    due_at: string | null;
    can_start: boolean;
    can_submit: boolean;
    seconds_left: number | null;
  };
  submission: { id: string; status: string; submitted_at: string | null; ai_help_used: number } | null;
  ai_help: { enabled: boolean; limit: number | null; used: number; remaining: number | null };
  sections: { id: string; title: string; items: WorkspaceItem[] }[];
}

export interface TutorIn {
  item_id: string;
  mode: "guide" | "explain";
  learner_input: string;
}

/** `GET /me/assignments/{id}/tutor/history?item_id=` row (server-side history, SEC-17). */
export interface TutorTurn {
  role: "learner" | "tutor" | (string & {});
  content: string;
  created_at: string;
}

export interface TutorOut {
  reply_md: string;
  used: number;
  /** Effective limit (assignment cap or the platform default); never null since WS4. */
  limit: number;
  remaining: number | null;
}

export interface ResultItem {
  id: string;
  section_id: string;
  section_title: string;
  position: number;
  item_type: ItemType | (string & {});
  marks: number;
  prompt_md: string | null;
  stem_html: string | null;
  options: ItemOption[];
  response: ItemResponse | null;
  final_marks: number | null;
  feedback_md: string | null;
}

export interface ResultOut {
  assignment: AssignmentOut;
  published: boolean;
  submission: { id: string; status: string; submitted_at: string | null; score: number | null; max_score: number; feedback_md: string | null } | null;
  items: ResultItem[];
  regrade: RegradeOut | null;
}

export interface LearnerSubmissionOut {
  id: string;
  status: "submitted" | "late" | (string & {});
  submitted_at: string | null;
}
