/** Content-studio DTOs, verified against apps/api (see per-type comments). Request bodies use `Body<>`/`Schema<>`. */
import type { Schema } from "@/lib/api-types";
import type { TestSummary } from "@/features/trainer/lib/types";

/* ------------------------------------------------------------------ courses */

/** CAT-08 row / `course_out`. verified: app/modules/catalog/service.py course_out (+ `draft` summary in studio_courses) */
export interface CourseSummary {
  id: string;
  organization_id: string | null;
  slug: string;
  title: string;
  course_kind: string;
  visibility: "public" | "unlisted" | "private" | "org_only" | string;
  /** draft | published | archived */
  status: string;
  is_free: boolean;
  current_version_id: string | null;
  completeness_pct: number;
  created_at: string;
  updated_at: string;
  /** editable version (draft or in_review), if any */
  draft: { id: string; status: "draft" | "in_review" | string; version_no: number } | null;
}

/** verified: app/modules/catalog/service.py lesson_out */
export interface Lesson {
  id: string;
  lesson_key: string;
  title: string;
  lesson_type: "video" | "article" | "pdf" | "practice_set" | "quiz" | "coding" | "assignment" | "live_link" | string;
  position: number;
  is_required: boolean;
  is_free_preview: boolean;
  duration_seconds: number | null;
  est_reading_minutes: number | null;
  /** Full lesson_out (studio detail, CAT-14 PATCH, CAT-20 preview). */
  course_module_id?: string;
  article_body?: Record<string, unknown> | null;
  test_id?: string | null;
  coding_problem_id?: string | null;
  assignment_id?: string | null;
  live_url?: string | null;
  assets?: LessonAssetOut[];
  /** CAT-15 lesson topics, primary first (studio views only; catalog lesson_out topics). */
  topics?: { topic_id: string; is_primary: boolean }[];
}

/** verified: app/modules/catalog/service.py asset_out ("available" is reported as "ready"). */
export interface LessonAssetOut {
  id: string;
  asset_type: string;
  provider?: string;
  status: string;
  scan_status?: string | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  duration_seconds?: number | null;
  position?: number;
}

/** CAT-21/22 `_resource_out`. verified: app/modules/catalog/router.py */
export interface ResourceOut {
  id: string;
  title: string;
  resource_type: "file" | "link" | "cheatsheet" | "interview_experience" | string;
  access_level: "public" | "signed_in" | "entitled" | string;
  course_id: string | null;
  lesson_id: string | null;
  company_id: string | null;
  organization_id: string | null;
  has_file: boolean;
  url: string | null;
}

/** verified: app/modules/catalog/service.py version_meta */
export interface CourseVersion {
  id: string;
  version_no: number;
  status: string;
  title: string;
  summary: string | null;
  description_md: string | null;
  outcomes: string[];
  level: "beginner" | "intermediate" | "advanced" | null;
  language: string | null;
  category: string | null;
  tags: string[];
  change_type: "minor" | "major" | null;
  changelog: string | null;
  created_by: string;
  submitted_at: string | null;
  published_at: string | null;
}

/** verified: app/modules/catalog/service.py version_out */
export interface CourseVersionTree extends CourseVersion {
  modules: { id: string; module_key: string; title: string; position: number; lessons: Lesson[] }[];
}

/** CAT-10. verified: app/modules/catalog/router.py studio_course */
export interface CourseDetail extends Omit<CourseSummary, "draft"> {
  draft: CourseVersionTree | null;
  published: CourseVersionTree | null;
}

/* ---------------------------------------------------------------- questions */

/** PLC-04 row. verified: app/modules/placement/bank.py search_questions → `{items, limit, offset}` */
export interface QuestionSummary {
  question_id: string;
  organization_id: string | null;
  question_type: QuestionType;
  primary_topic_id: string;
  /** draft | active | retired */
  status: string;
  /** PLC-11 reason, when retired. */
  retired_reason?: string | null;
  latest_version: { question_version_id: string; version_no: number; status: string; reviewed?: boolean; difficulty: number; stem_html: string } | null;
}

export type QuestionType = Schema<"QuestionCreate">["question_type"];

/** verified: app/modules/placement/bank.py version_out (key fields only when `keys_visible`) */
export interface QuestionVersion {
  question_version_id: string;
  version_no: number;
  /** draft | in_review | published | retired */
  status: string;
  difficulty: number;
  stem_html: string;
  default_marks: string;
  default_negative: string;
  expected_seconds: number | null;
  authored_by: string;
  reviewed_by: string | null;
  /** Users who edited this version (reviewers among them can't approve it, audit ADM-46). */
  edited_by?: string[];
  /** Reviewer's comment from PLC-09 (audit ADM-55). */
  review_comment?: string | null;
  published_at: string | null;
  options: { option_id: string; label: string | null; html: string; is_correct?: boolean; feedback_html?: string | null }[];
  answer_key?: Record<string, unknown> | null;
  explanation_html?: string | null;
  correct_option_ids?: string[];
}

/** PLC-05/06/07. verified: app/modules/placement/bank.py question_detail (versions newest first) */
export interface QuestionDetail {
  question_id: string;
  organization_id: string | null;
  question_type: QuestionType;
  primary_topic_id: string;
  status: string;
  retired_reason?: string | null;
  current_version_id: string | null;
  created_by: string;
  keys_visible: boolean;
  tags: { tag_type: string; topic_id: string | null; company_id: string | null; value: string | null }[];
  versions: QuestionVersion[];
}

/* ------------------------------------------------------------------- coding */

/** verified: app/modules/coding/service.py studio_summary_out (list rows) */
export interface CodingProblemSummary {
  problem_id: string;
  slug: string;
  title: string;
  status: "draft" | "in_review" | "published" | "retired" | string;
  difficulty: number;
  version_no: number;
  is_free: boolean;
  scoring_mode: "weighted_cases" | "all_or_nothing";
  organization_id: string | null;
  time_limit_ms: number;
  memory_limit_mb: number;
  languages: string[];
  test_cases: { sample: number; hidden: number };
  updated_at: string;
  published_at: string | null;
}

/** COD-24 picker row. verified: app/modules/coding/router.py studio_published_problems (metadata only). */
export interface PublishedCodingProblem {
  problem_id: string;
  slug: string;
  title: string;
  difficulty: number;
  version_no: number;
  organization_id: string | null;
}

/** verified: app/modules/coding/router.py studio_get_problem = problem_out(staff) + studio_compat_fields */
export interface CodingProblem extends CodingProblemSummary {
  statement_md: string;
  input_format_md: string | null;
  output_format_md: string | null;
  constraints_md: string | null;
  limits: { time_limit_ms: number; wall_limit_ms: number | null; memory_limit_kb: number };
  allowed_languages: string[];
  checker_type: string;
  created_by: string;
}

/** COD-16 list row. verified: app/modules/coding/service.py case_meta_out (Sample/HiddenCaseMetaOut) */
export type TestCase =
  | { test_case_id: string; ordinal: number; is_sample: true; weight: number; input: string; expected_output: string }
  | { test_case_id: string; ordinal: number; is_sample: false; weight: number; size_bytes: number | null; input_sha256: string | null; expected_sha256: string | null };

/* -------------------------------------------------------------------- tests */

/** verified: app/modules/assessments/studio.py sections_out(with_rules=True) */
export interface TestRuleOut {
  rule_id: string;
  position: number;
  rule_type: "fixed" | "random";
  question_id: string | null;
  question_version_id: string | null;
  topic_id: string | null;
  company_id: string | null;
  question_types: string[] | null;
  difficulty_min: number | null;
  difficulty_max: number | null;
  draw_count: number;
  marks_each: string | null;
  negative_marks_each: string | null;
}

export interface TestSectionOut {
  section_id: string;
  title: string;
  position: number;
  duration_seconds: number | null;
  instructions_md: string | null;
  question_count: number;
  rules: TestRuleOut[];
}

/** ASM-05. verified: app/modules/assessments/router.py asm_05_get_test = test_out + sections */
export type TestDefinition = TestSummary & { sections: TestSectionOut[] };

/** ASM-08. verified: app/modules/assessments/studio.py validate */
export interface ValidationResult {
  test_id: string;
  feasible: boolean;
  has_sections: boolean;
  rules: { section_id: string; rule_id: string; rule_type: string; pool_size: number; required: number; ok: boolean; recommended_ok: boolean }[];
}

/* ----------------------------------------------- coding validation / hidden content (hand-written) */

/** COD-18 reference solutions (studio only). */
export interface ReferenceSolution {
  language_key: string;
  source_code: string;
  size_bytes: number;
  updated_at: string;
}

/** COD-18 per-case verdict: ordinal/verdict/time/memory only — never case content. */
export interface ValidationCase {
  ordinal: number;
  is_sample: boolean;
  verdict: string;
  time_ms: number | null;
  memory_kb: number | null;
}

export interface ValidationSolution {
  language_key: string;
  verdict: string;
  passed_cases: number;
  total_cases: number;
  cases: ValidationCase[];
}

/** COD-18 POST validate / GET validation. */
export interface ProblemValidation {
  validation_id: string;
  problem_id: string;
  problem_version: number;
  status: "passed" | "failed" | "error";
  is_current: boolean;
  validated_at: string;
  requested_by: string;
  detail: string | null;
  solutions: ValidationSolution[];
}

/** COD-17: short-lived, single-use same-origin download links (never cached). */
export interface HiddenCaseContentLinks {
  test_case_id: string;
  ordinal: number;
  input_url: string;
  expected_url: string;
  expires_at: string;
  sha256: { input: string | null; expected: string | null };
}

/* ------------------------------------------------------- question reports (PLC-34/35) */

export type QuestionReportResolution = "fixed" | "no_change" | "duplicate" | "invalid";

export interface QuestionReport {
  report_id: string;
  question_id: string;
  question_version_id: string | null;
  organization_id: string | null;
  category: "wrong_answer" | "wrong_explanation" | "typo" | "unclear" | "other" | string;
  message: string;
  status: "open" | "resolved";
  resolution: QuestionReportResolution | null;
  resolution_note: string | null;
  reporter_user_id: string;
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
}

export interface QuestionReportPage {
  data: QuestionReport[];
  meta: { next_cursor: string | null; has_more: boolean; limit: number };
  open_count: number;
}
