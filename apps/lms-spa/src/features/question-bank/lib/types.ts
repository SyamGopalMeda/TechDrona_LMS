/**
 * Question banks (qbank) — local types for the `studio/question-banks*`, extended
 * `studio/questions*` and `studio/question-media*` endpoints. These endpoints are not in the
 * generated `@/lib/api-types` yet (they are regenerated later), so they are declared
 * here by hand from the qbank API contract.
 */

/** Server `question_type` values. */
export type QuestionType =
  | "mcq_single"
  | "mcq_multi"
  | "coding"
  | "essay"
  | "poll"
  | "survey"
  | "word_cloud"
  | "numeric"
  | "fill_blank";

/** Import / AI "kind" values (the type tiles). */
export type ImportKind = "mcq" | "code" | "essay" | "poll" | "survey" | "word_cloud";

export interface Bank {
  id: string;
  organization_id: string | null;
  name: string;
  subject: string | null;
  description: string | null;
  question_count: number;
  type_counts: Record<string, number>;
  /** Top tags (up to 8). */
  tags: string[];
  created_at: string;
  updated_at: string;
  last_added_at: string | null;
  created_by: string;
}

export interface BankListResponse {
  items: Bank[];
  total: number;
  counters: { banks: number; questions: number; subjects: number };
  subjects: { subject: string | null; count: number }[];
  limit: number;
  offset: number;
}

export type VersionStatus = "draft" | "in_review" | "published" | "retired";

export interface BankQuestion {
  question_id: string;
  question_type: QuestionType | string;
  status: "draft" | "active" | "retired" | string;
  organization_id: string | null;
  primary_topic_id: string | null;
  tags: string[];
  added_at: string;
  published_version_id: string | null;
  latest_version: {
    question_version_id: string;
    version_no: number;
    status: VersionStatus | string;
    reviewed: boolean;
    difficulty: number;
    stem_html: string;
    option_count: number;
    correct_count: number | null;
    has_images: boolean;
  } | null;
}

export interface BankQuestionsResponse {
  bank: Bank;
  items: BankQuestion[];
  total: number;
  type_counts: Record<string, number>;
  tags: string[];
  limit: number;
  offset: number;
}

export interface MediaRef {
  media_id: string;
  url: string | null;
}

export interface VersionOption {
  option_id: string;
  label: string;
  html: string;
  image: MediaRef | null;
  is_correct?: boolean;
  feedback_html?: string | null;
}

export interface QuestionVersionDetail {
  question_version_id: string;
  version_no: number;
  status: VersionStatus | string;
  difficulty: number;
  stem_html: string;
  stem_images: { media_id: string; url: string }[];
  settings: Record<string, unknown> | null;
  default_marks?: string | number | null;
  default_negative?: string | number | null;
  expected_seconds?: number | null;
  coding_problem_id: string | null;
  options: VersionOption[];
  answer_key?: unknown;
  explanation_html?: string | null;
  correct_option_ids?: string[];
  reviewed_by?: string | null;
  review_comment?: string | null;
}

export interface ResolvedQuestion {
  question_id: string;
  question_type: QuestionType | string;
  tags: string[];
  keys_visible: boolean;
  version: QuestionVersionDetail | null;
}

/** `GET studio/questions/{id}` (extended). */
export interface QuestionFull {
  question_id: string;
  organization_id: string | null;
  question_type: QuestionType | string;
  primary_topic_id: string | null;
  status: string;
  tags: { tag_type: string; topic_id: string | null; company_id: string | null; value: string | null }[];
  keys_visible: boolean;
  banks?: { id: string; name: string }[];
  versions: QuestionVersionDetail[];
}

export interface ImportProblem {
  index: number | null;
  field: string;
  message: string;
}

export interface ImportPreview {
  index: number;
  type: ImportKind | string;
  text: string;
  options: { text: string; correct: boolean }[];
  tags: string[];
  sample_cases: number;
  hidden_cases: number;
}

export interface ValidateResult {
  ok: boolean;
  count: number;
  problem_count: number;
  problems: ImportProblem[];
  fix_prompt: string | null;
  items: ImportPreview[];
}

export interface ImportResult {
  bank: Bank;
  question_ids: string[];
  count: number;
}

export type GenerateMode = "topic" | "company" | "subject" | "test";
export type GenerateDifficulty = "easy" | "medium" | "hard" | "mixed";

export interface GenerateResult {
  drafts: Record<string, unknown>[];
  previews: ImportPreview[];
  problems: ImportProblem[];
}

export interface MediaTicket {
  media_id: string;
  upload: { url: string; fields: Record<string, unknown> };
  expires_at: string;
  max_bytes: number;
}

export interface MediaStatus {
  media_id: string;
  status: "uploading" | "ready" | "failed" | string;
  scan_status: "pending" | "clean" | "infected" | string;
  url: string | null;
}

/**
 * A question picked in the bank picker, ready to embed in an assignment, test or live activity.
 * `question_version_id` is null only when `requirePublished` was false and the question has no
 * version the caller may see.
 */
export interface PickedQuestion {
  question_id: string;
  question_version_id: string | null;
  question_type: string;
  stem_html: string;
  stem_images: { media_id: string; url: string }[];
  options: { option_id: string; label: string; html: string; image_url: string | null; is_correct?: boolean }[];
  settings: Record<string, unknown>;
  tags: string[];
  difficulty: number;
  bank_id: string;
  keys_visible: boolean;
}
