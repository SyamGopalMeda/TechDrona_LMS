/**
 * Assessment DTOs (ASM / ATT). Request bodies come from the generated OpenAPI schema; response
 * shapes are verified against the dicts built in app/modules/assessments/{router,attempts,studio}.py
 * (those routes return `dict[str, Any]`). Unknown fields are tolerated (§1.12).
 */
import type { Schema } from "@/lib/api-types";

export type NavigationMode = "free" | "sequential" | "section_locked" | (string & {});
export type AttemptStatus =
  | "in_progress"
  | "submitted"
  | "auto_submitted"
  | "grading"
  | "awaiting_manual"
  | "graded"
  | "invalidated"
  | (string & {});

/* ------------------------------------------------------------------ ASM-01 / ASM-02 */

/** verified: app/modules/assessments/router.py asm_01_my_tests items[] (not paginated) */
export interface TestListItem {
  test_id: string;
  title: string;
  test_kind: string;
  duration_seconds: number;
  test_assignment_id: string | null;
  available_from: string | null;
  available_until: string | null;
  attempts_used: number;
  attempts_left: number | null;
  status: "available" | "scheduled" | "in_progress" | "completed" | "closed" | (string & {});
  in_progress_attempt_id: string | null;
}

/** verified: router.py asm_01_my_tests */
export interface MyTestsResponse {
  items: TestListItem[];
  server_now: string;
}

/** verified: router.py att_13_my_attempts items[] (latest 200, newest first) */
export interface MyAttempt {
  attempt_id: string;
  test_id: string;
  test_title: string;
  attempt_no: number;
  status: AttemptStatus;
  started_at: string | null;
  deadline_at: string | null;
  submitted_at: string | null;
  submit_reason: string | null;
}

/** A test row plus the student's latest finished attempt (derived client-side from ATT-13). */
export interface TestRowData extends TestListItem {
  last_attempt: MyAttempt | null;
}

/** verified: app/modules/assessments/studio.py sections_out(with_rules=False) */
export interface TestDetailSection {
  section_id: string;
  title: string;
  position: number;
  duration_seconds: number | null;
  instructions_md: string | null;
  question_count: number;
}

/** verified: router.py asm_02_test_detail */
export interface TestDetail {
  id: string;
  title: string;
  test_kind: string;
  version: number;
  duration_seconds: number;
  grace_seconds: number;
  navigation_mode: NavigationMode;
  /** Decimal as string */
  pass_percentage: string | null;
  /** Plain-text marking note */
  marking: string;
  sections: TestDetailSection[];
  /** settings keys used by the server: consent_mandatory, single_device_binding */
  integrity_notice: { settings: Record<string, unknown>; text: string };
  /** Exam protocol (agreement screen, recorded events). Absent on older servers. */
  protocol?: ExamProtocol;
  window: { available_from: string | null; available_until: string | null; window_extension_seconds: number };
  attempts_allowed: number | null;
  attempts_left: number | null;
  eligibility: { eligible: boolean; via: string | null; test_assignment_id: string | null };
  server_now: string;
}

/* ------------------------------------------------------------------ attempt payload */

/** verified: app/modules/placement/schemas.py OptionDelivery */
export interface QuestionOption {
  option_id: string;
  label: string;
  html: string;
}

/** verified: app/modules/placement/schemas.py QuestionDelivery (bank.delivery). Objective types
 * mcq_single / mcq_multi / numeric / fill_blank, plus `coding` (A-4: answer = {submission_id}). */
export interface QuestionDelivery {
  question_version_id: string;
  type: "mcq_single" | "mcq_multi" | "numeric" | "fill_blank" | (string & {});
  topic_id: string;
  difficulty: number;
  stem_html: string;
  options: QuestionOption[];
  /** Decimal → JSON string */
  marks?: string | null;
  negative_marks?: string | null;
  expected_seconds?: number | null;
  /** `coding` items only (bank.delivery): the coding problem solved through COD-07 with attempt_id. */
  coding_problem_id?: string | null;
  /** Optional, if the API starts sending it (avoids the id → slug lookup). */
  coding_problem_slug?: string | null;
}

/** verified: attempts.py state_payload sections[] */
export interface AttemptSection {
  section_id: string;
  title: string;
  position: number;
  status: "active" | "not_started" | "submitted" | (string & {});
  deadline_at: string | null;
  duration_seconds: number | null;
  question_count: number;
  /** present only for visible sections (free navigation, or the active section) */
  questions?: QuestionDelivery[];
}

export type QuestionResponse = { option_ids: string[] } | { value: string } | Record<string, unknown>;

/** verified: attempts.py state_payload responses[] */
export interface SavedResponse {
  question_version_id: string;
  response: QuestionResponse | null;
  client_seq: number;
  flagged: boolean;
  saved_at?: string | null;
}

/** verified: app/modules/assessments/attempts.py state_payload (ATT-01/02/03/05/08/09). For a
 * closed attempt the submitted_payload keys are merged in and sections/responses are empty. */
export interface AttemptPayload {
  attempt_id: string;
  attempt_no: number;
  status: AttemptStatus;
  test: { id: string; version: number; title: string; navigation_mode: NavigationMode; grace_seconds: number };
  server_now: string;
  started_at: string | null;
  deadline_at: string | null;
  current_section_id?: string | null;
  sections: AttemptSection[];
  responses: SavedResponse[];
  binding?: { bound_session_id: string; rebinds_remaining: number };
  autosave?: { debounce_ms: number; max_interval_ms: number; max_items: number };
  reattached?: boolean;
  protocol?: ExamProtocol;
  integrity?: IntegritySummary;
  integrity_flagged?: boolean;
}

/* ------------------------------------------------------------------ exam protocol */

/** Events the exam protocol can record (server: schemas.RECORDABLE_EVENTS). */
export type RecordableEvent = "focus_lost" | "window_blur" | "copy" | "cut" | "paste" | "resize" | "fullscreen_exit" | "right_click";

export const RECORDABLE_EVENTS: readonly RecordableEvent[] = ["focus_lost", "window_blur", "copy", "cut", "paste", "resize", "fullscreen_exit", "right_click"];

/** verified: app/modules/assessments/exam.py Protocol.public */
export interface ExamProtocol {
  exam_mode: boolean;
  require_agreement: boolean;
  conduct_instructions: string | null;
  record_events: RecordableEvent[];
  require_fullscreen: boolean;
  type_thresholds: Partial<Record<RecordableEvent, number>>;
  flag_threshold: number | null;
  auto_submit_after: number | null;
  ai_hints: false;
  labels: Partial<Record<RecordableEvent, string>>;
}

/** verified: exam.py summarize */
export interface IntegritySummary {
  exam_mode: boolean;
  counts: Partial<Record<RecordableEvent, number>>;
  total: number;
  over_threshold: { type: RecordableEvent; label: string; count: number; threshold: number }[];
  flag_threshold: number | null;
  flagged: boolean;
  integrity_status: string;
}

/* ------------------------------------------------------------------ autosave */

export type IntegrityEventType = Schema<"IntegrityEvent">["type"] | RecordableEvent;

/** Client-side item; serialises to Schema<"AutosaveItem">. */
export interface AutosaveItem {
  question_version_id: string;
  response: QuestionResponse | null;
  client_seq: number;
  time_spent_ms: number;
  flagged: boolean;
}

export interface IntegrityEvent {
  type: IntegrityEventType;
  client_at: string;
  client_seq: number;
}

/** Schema<"AutosaveIn"> */
export interface AutosaveRequest {
  items: AutosaveItem[];
  events: IntegrityEvent[];
  current_section_id?: string | null;
}

/** verified: attempts.py autosave */
export interface AutosaveResponse {
  /** null only when the request carried no items/events */
  acked_seq: number | null;
  server_now: string;
  deadline_at: string | null;
  section_deadline_at: string | null;
  status: AttemptStatus;
  /** events dropped because the attempt has no integrity consent */
  ignored_events?: number;
  /** exam protocol only: live counts for the warning banner */
  integrity?: IntegritySummary;
  /** answers the server could not save because they are invalid for their question */
  rejected?: { question_version_id: string; client_seq: number; field?: string | null; message: string }[];
}

/** verified: attempts.py time_payload (ATT-07) */
export interface TimeResponse {
  attempt_id: string;
  status: AttemptStatus;
  server_now: string;
  deadline_at: string | null;
  section_deadline_at: string | null;
  current_section_id: string | null;
}

/** verified: attempts.py submitted_payload (ATT-10) */
export interface SubmitResponse {
  attempt_id: string;
  status: AttemptStatus;
  submitted_at: string | null;
  submit_reason: "user" | "deadline" | (string & {}) | null;
  integrity_status?: string;
  integrity_flagged?: boolean;
  result_release: { mode: "immediate" | "after_window" | "scheduled" | "manual" | (string & {}); release_at: string | null };
  redirect: string;
  server_now: string;
}

/** verified: attempts.py send_rebind_otp (ATT-04) */
export interface RebindOtpResponse {
  otp_required: boolean;
  sent: boolean;
  channel?: "sms" | "email";
}

/* ------------------------------------------------------------------ results */

export type VisibilityKey = "score" | "correctness" | "answer_key" | "explanation" | "section_analytics" | "rank";

/** verified: attempts.py score_attempt section_scores[] (Decimals stored as strings) */
export interface SectionScore {
  section_id: string;
  title: string;
  score: string;
  max: string;
  time_s: number;
}

/** verified: attempts.py score_attempt topic_scores[] */
export interface TopicScore {
  topic_id: string;
  correct: number;
  total: number;
  avg_time_ms: number;
}

/** verified: app/modules/assessments/attempts.py result_payload (ATT-11). Score/correctness/
 * section/rank keys are present only when `visible` allows them. */
export interface AttemptResult {
  attempt_id: string;
  status: AttemptStatus;
  phase: "during" | "after_submit" | "after_close" | (string & {});
  visible: Record<VisibilityKey, boolean>;
  submitted_at: string | null;
  submit_reason: string | null;
  integrity_status: string | null;
  released_at: string | null;
  /** invalidated attempts only */
  appeal_url?: string;
  score?: number;
  max_score?: number;
  percentage?: number;
  time_taken_seconds?: number;
  passed?: boolean | null;
  correct_count?: number;
  incorrect_count?: number;
  unanswered_count?: number;
  section_scores?: SectionScore[];
  topic_scores?: TopicScore[];
  rank?: number | null;
  percentile?: number | null;
  percentile_note?: string;
  rank_provisional?: boolean;
}

/** verified: attempts.py review_payload sections[].questions[] (QuestionDelivery + review keys) */
export interface ReviewItem extends QuestionDelivery {
  your_response: QuestionResponse | null;
  time_spent_ms: number;
  flagged: boolean;
  /** when correctness is visible */
  is_correct?: boolean | null;
  marks_awarded?: number;
  /** when the answer key is visible: MCQ */
  correct_option_ids?: string[];
  /** when the answer key is visible: numeric / fill_blank */
  correct_answer?: string | number | null;
  /** when explanations are visible */
  explanation_html?: string | null;
  /**
   * Coding items (BE-23): the scored submission with the learner's own source. Verdict, score and
   * per-case results are present only when correctness is visible; hidden cases are verdict-only.
   */
  your_submission?: ReviewSubmission | null;
}

/** verified: coding.service.submission_view (include_source) as returned inside ATT-12. */
export interface ReviewSubmission {
  submission_id: string;
  language_key?: string;
  source_code?: string | null;
  verdict?: string | null;
  score?: number | null;
  max_score?: number | null;
  passed_cases?: number | null;
  total_cases?: number | null;
  cases?: { ordinal?: number; is_sample?: boolean; verdict?: string | null }[];
}

/** verified: attempts.py review_payload (ATT-12) */
export interface ReviewResponse {
  attempt_id: string;
  phase: string;
  visible: Partial<Record<VisibilityKey, boolean>>;
  sections: { section_id: string; title: string; questions: ReviewItem[] }[];
}

/** 409 attempt_bound_elsewhere extension members — verified: attempts.py ensure_bound + binding_info. */
export interface BoundElsewhere {
  bound_device_label?: string;
  bound_since?: string;
  rebind_allowed?: boolean;
  rebinds_remaining?: number;
  otp_required?: boolean;
  trainer_override_required?: boolean;
  read_only?: { answered_count?: number; deadline_at?: string | null; server_now?: string };
}
