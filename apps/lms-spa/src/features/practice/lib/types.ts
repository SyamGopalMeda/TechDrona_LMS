/**
 * Placement/practice DTOs (api-specification §13 PLC). Request bodies come from the generated
 * OpenAPI schema; response shapes are verified against the dicts built in
 * app/modules/placement/{router,practice,bank}.py (the routes return `dict[str, Any]`).
 */
import type { Schema } from "@/lib/api-types";

export type Difficulty = "easy" | "medium" | "hard";

/** verified: app/modules/placement/practice.py band() */
export type MasteryBand = "insufficient_data" | "beginner" | "developing" | "proficient" | "mastered" | (string & {});

/** PLC-19 request (fields with server defaults are optional when sent). */
export type PracticeStartBody = Partial<Schema<"PracticeStart">>;
/** PLC-21 request. */
export type PracticeAnswerBody = Schema<"PracticeAnswer">;

/** verified: app/modules/placement/bank.py subject_tree / topic_out */
export interface TaxonomyNode {
  id: string;
  parent_id: string | null;
  kind: string;
  slug: string;
  name: string;
  path: string;
  depth: number;
  position: number;
  is_active: boolean;
  question_count: number;
  children: TaxonomyNode[];
}

/** verified: app/modules/placement/router.py plc_01_subjects → {items} */
export interface SubjectsResponse {
  items: TaxonomyNode[];
}

/** verified: app/modules/placement/schemas.py OptionDelivery */
export interface PracticeOption {
  option_id: string;
  label: string;
  html: string;
}

/** verified: app/modules/placement/schemas.py QuestionDelivery (bank.delivery) */
export interface PracticeQuestion {
  question_version_id: string;
  type: "mcq_single" | "mcq_multi" | "numeric" | "fill_blank" | (string & {});
  topic_id: string;
  difficulty: number;
  stem_html: string;
  options: PracticeOption[];
  /** Decimal → JSON string */
  marks?: string | null;
  negative_marks?: string | null;
  expected_seconds?: number | null;
}

/** verified: app/modules/placement/practice.py _feedback (+ bank.key_payload) */
export interface PracticeFeedback {
  question_version_id: string;
  is_correct: boolean | null;
  your_response: Record<string, unknown> | null;
  explanation_html: string | null;
  /** MCQ only */
  correct_option_ids?: string[];
  /** numeric / fill_blank only */
  correct_answer?: string | number | null;
  attempt_no: number;
  solution_viewed: boolean;
  answered_at: string;
  /** always null today (analytics-owned) */
  mastery_delta: { topic_id: string; band_before: MasteryBand; band_after: MasteryBand } | null;
  next_question_version_id: string | null;
}

/** verified: app/modules/placement/practice.py state() items[] */
export interface PracticeItem {
  position: number;
  served_at: string;
  question: PracticeQuestion;
  answered: boolean;
  feedback: PracticeFeedback | null;
}

/** verified: app/modules/placement/practice.py state() (PLC-19 201 body and PLC-20) */
export interface PracticeSession {
  session_id: string;
  mode: "topic_set" | "revision" | (string & {});
  topic_id: string | null;
  status: "active" | "completed" | (string & {});
  target_count: number;
  answered_count: number;
  correct_count: number;
  started_at: string;
  ended_at: string | null;
  next_question_version_id: string | null;
  items: PracticeItem[];
}

/** verified: app/modules/placement/practice.py reveal() */
export type RevealResponse =
  | { kind: "hint"; available: boolean; hint_html: string | null }
  | ({ kind: "solution"; question_version_id: string; explanation_html: string | null; correct_option_ids?: string[]; correct_answer?: string | number | null });

/** verified: app/modules/placement/practice.py complete() */
export interface PracticeSummary {
  session_id: string;
  status: string;
  answered: number;
  correct: number;
  /** 0..1, null when nothing answered */
  accuracy: number | null;
  unanswered: number;
  by_topic: { topic_id: string; answered: number; correct: number }[];
}

/** verified: app/modules/placement/practice.py list_recommendations() items[] */
export interface Recommendation {
  id: string;
  rule_key: string;
  why_recommended: string;
  evidence: Record<string, unknown>;
  target_type: "topic" | (string & {});
  target_id: string;
  priority: number;
  generated_at: string;
  expires_at: string;
}

/** verified: app/modules/placement/practice.py list_recommendations() */
export interface RecommendationsResponse {
  personalised: boolean;
  /** e.g. "consent_required:analytics_personalisation" when not personalised */
  note?: string;
  items: Recommendation[];
}

/** verified: app/modules/placement/practice.py mastery() topics[] */
export interface MasteryTopic {
  topic_id: string;
  name: string | null;
  path: string | null;
  answered: number;
  correct: number;
  /** 0..1 */
  accuracy: number;
  /** 0..1 (EWMA) */
  weighted_accuracy: number;
  band: MasteryBand;
  last_practiced_at: string;
}

/** verified: app/modules/placement/router.py plc_25_mastery → practice.mastery() */
export interface MasteryResponse {
  method: string;
  method_note: string;
  topics: MasteryTopic[];
}

/** verified: app/modules/placement/practice.py review_list() (PLC-24 → {items}) */
export interface ReviewQuestion {
  question_version_id: string;
  topic_id: string;
  last_answered_at: string;
  attempts: number;
}

/* ------------------------------------------------------------ question reports (PLC-33) */

export type QuestionReportCategory = "wrong_answer" | "wrong_explanation" | "typo" | "unclear" | "other";

/** PLC-33 request (hand-written; placement question reports). */
export interface QuestionReportBody {
  category: QuestionReportCategory;
  message: string;
  question_version_id?: string;
}

/** PLC-33 response. */
export interface QuestionReportOut {
  report_id: string;
  question_id: string;
  question_version_id: string | null;
  category: QuestionReportCategory;
  message: string;
  status: "open" | "resolved";
  created_at: string;
}
