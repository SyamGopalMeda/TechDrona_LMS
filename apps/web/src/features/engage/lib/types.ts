/**
 * Engage (live quizzes, polls, word clouds, surveys) payloads. The generated OpenAPI types do not
 * include the engage module yet, so the shapes are declared here.
 * verified: apps/api/app/modules/engage/schemas.py + service.py (functions named per type)
 */

export type ActivityType = "quiz" | "poll" | "word_cloud" | "survey";
export type QuestionKind = "single_choice" | "multi_choice" | "word" | "text" | "rating";
export type RunMode = "instant" | "scheduled";
export type Audience = "members" | "public";
export type IdentityMode = "named" | "anonymous";
export type ResultsMode = "live" | "on_publish";
export type Pacing = "all_at_once" | "one_by_one";
export type WinnerRule = "fastest_first" | "all_correct";
export type RunStatus = "scheduled" | "open" | "closed" | "finalised";
export type ControlAction = "start" | "close" | "goto" | "reveal" | "hide" | "publish" | "unpublish" | "finalise";

/** verified: schemas.py OptionIn / QuestionIn / ActivityIn */
export interface OptionIn {
  id?: string;
  text: string;
  is_correct: boolean;
}

export interface QuestionIn {
  kind: QuestionKind;
  prompt: string;
  options: OptionIn[];
  max_words?: number | null;
  source_question_id?: string | null;
  source_version_id?: string | null;
}

export interface ActivityIn {
  activity_type: ActivityType;
  title: string;
  description?: string | null;
  /** null/absent = platform activity (Admin / Content manager only). */
  batch_id?: string | null;
  run_mode: RunMode;
  audience: Audience;
  identity_mode: IdentityMode;
  results_mode: ResultsMode;
  pacing: Pacing;
  winner_rule: WinnerRule | null;
  participant_limit: number | null;
  opens_at?: string | null;
  closes_at?: string | null;
  questions: QuestionIn[];
}

/** verified: service.py settings_of */
export interface RunSettings {
  run_mode: RunMode;
  audience: Audience;
  identity_mode: IdentityMode;
  results_mode: ResultsMode;
  pacing: Pacing;
  winner_rule: WinnerRule | null;
  participant_limit: number | null;
}

/** verified: service.py run_summary */
export interface RunSummary {
  id: string;
  activity_id: string;
  run_no: number;
  join_code: string;
  join_path: string;
  status: RunStatus;
  current_position: number;
  revealed_positions: number[];
  results_published: boolean;
  question_count: number;
  settings: RunSettings;
  opens_at: string | null;
  closes_at: string | null;
  opened_at: string | null;
  closed_at: string | null;
  finalised_at: string | null;
  created_at: string | null;
}

/** verified: service.py question_out */
export interface ActivityQuestion {
  id: string;
  position: number;
  kind: QuestionKind;
  prompt: string;
  options: { id: string; text: string; is_correct: boolean }[];
  max_words: number | null;
  source_question_id: string | null;
}

/** verified: service.py activity_out */
export interface ActivityBase extends RunSettings {
  id: string;
  activity_type: ActivityType;
  title: string;
  description: string | null;
  organization_id: string | null;
  batch_id: string | null;
  owner_id: string;
  opens_at: string | null;
  closes_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** verified: service.py list_activities */
export interface ActivitySummary extends ActivityBase {
  question_count: number;
  latest_run: RunSummary | null;
}

export interface ActivityList {
  data: ActivitySummary[];
  counts: { total: number };
}

/** verified: service.py activity_detail (activity_out with questions + runs) */
export interface Activity extends ActivityBase {
  questions: ActivityQuestion[];
  question_count: number;
  runs?: RunSummary[];
}

/** verified: service.py bank_import */
export interface QuestionDraft {
  kind: QuestionKind;
  prompt: string;
  options: { text: string; is_correct: boolean }[];
  max_words: number | null;
  source_question_id: string;
  source_version_id: string;
  key_copied: boolean;
}

export interface BankImportResult {
  data: QuestionDraft[];
  skipped: { question_id: string; reason: string }[];
}

/** verified: service.py _question_result (+ presenter_state extras) */
export interface ResultOption {
  id: string;
  text: string;
  count?: number;
  pct?: number;
  correct?: boolean;
}

export interface WinnerInfo {
  fastest: string;
  also_correct: string[];
  also_correct_count: number;
}

export interface ResultQuestion {
  id: string;
  position: number;
  kind: QuestionKind;
  prompt: string;
  options: ResultOption[];
  max_words: number | null;
  answered: number;
  revealed: boolean;
  words?: { term: string; count: number }[];
  ratings?: Record<string, number>;
  average?: number | null;
}

export interface PresenterQuestion extends ResultQuestion {
  winner?: WinnerInfo | null;
  texts?: { label: string; text: string | null; filtered: boolean }[];
}

export interface LeaderRow {
  rank: number;
  label: string;
  wins: number;
  correct: number;
  time_ms: number;
}

export interface Unchanged {
  unchanged: true;
  version: string;
}

/** verified: service.py presenter_state */
export interface PresenterState {
  version: string;
  run: RunSummary;
  activity: { id: string; title: string; description: string | null; activity_type: ActivityType };
  joined: number;
  voted: number;
  total_votes: number;
  participants: { label: string; seq: number }[];
  questions: PresenterQuestion[];
  leaderboard: LeaderRow[];
}

export interface MyAnswer {
  option_ids?: string[];
  text?: string;
  rating?: number;
}

/** verified: service.py participant_state */
export interface LiveQuestion extends ResultQuestion {
  answerable: boolean;
  my_answer: MyAnswer | null;
  my_correct?: boolean | null;
}

export interface LiveState {
  version: string;
  run: {
    id: string;
    status: RunStatus;
    pacing: Pacing;
    results_mode: ResultsMode;
    identity_mode: IdentityMode;
    current_position: number;
    question_count: number;
    results_published: boolean;
    closes_at: string | null;
  };
  activity: { title: string; description: string | null; activity_type: ActivityType };
  me: { label: string; answered: number };
  joined: number;
  questions: LiveQuestion[];
  leaderboard: LeaderRow[];
  my_rank: LeaderRow | null;
}

/** verified: service.py join_preview */
export interface JoinPreview {
  run_id: string;
  title: string;
  description: string | null;
  activity_type: ActivityType;
  status: RunStatus;
  audience: Audience | null;
  identity_mode: IdentityMode | null;
  eligible: boolean;
  joined: boolean;
}

/** verified: service.py my_runs */
export interface MyRun {
  run_id: string;
  title: string;
  activity_type: ActivityType;
  status: RunStatus;
  results_published: boolean;
  joined_at: string;
}

/** verified: service.py invite */
export interface InviteResult {
  sent: number;
  recipients: number;
  join_path: string;
}

/** verified: service.py answer */
export interface AnswerIn {
  question_id: string;
  option_ids?: string[];
  text?: string;
  rating?: number;
}
