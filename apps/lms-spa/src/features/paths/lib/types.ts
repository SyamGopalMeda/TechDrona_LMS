/**
 * Local types for the guided learning paths module (`apps/api/app/modules/paths`).
 * Hand-written from the module's API contract (the paths routes return untyped dicts in OpenAPI).
 * Single company (ws4.md §3): no `organization_id` inputs; the server stamps the company org.
 */

export type StepType = "reading" | "video" | "article" | "assignment" | "assessment" | "super_step";
export type PathStatus = "draft" | "published" | "archived";
export type Level = "beginner" | "intermediate" | "advanced";
export type Flow = "lenient" | "strict";
export type PaceMode = "every_day" | "weekdays" | "weekends" | "weekdays_weekends" | "custom";
export type DayKey = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export type PerDay = Record<DayKey, number>;
export type StepState = "locked" | "available" | "in_progress" | "completed";
export type Audience = "batches" | "people";

export interface PathSummary {
  id: string;
  organization_id: string;
  title: string;
  description_md: string | null;
  level: Level | null;
  status: PathStatus;
  has_unpublished_changes: boolean;
  version_no: number;
  step_count: number;
  total_credits: number;
  total_hours: number;
  source: "manual" | "ai";
  updated_at: string;
}

export interface Step {
  step_key: string;
  step_type: StepType;
  title: string;
  description_md: string | null;
  est_hours: number;
  credits: number;
  url: string | null;
  /** Server-computed (WS4 D9): true only for allow-listed https embed URLs. */
  embeddable?: boolean;
  lesson_id: string | null;
  assignment_id: string | null;
  test_id: string | null;
  article_id: string | null;
  children: Step[];
}

/** Editor draft step: `step_key` is absent for steps that were never saved. */
export interface StepIn extends Omit<Step, "step_key" | "children" | "embeddable"> {
  step_key?: string;
  children: StepIn[];
}

export interface Pace {
  mode: PaceMode;
  hours_per_day?: number;
  weekend_hours?: number;
  per_day?: PerDay;
}

export interface Allocation {
  id: string;
  path_id: string;
  path_version_id: string;
  version_no: number;
  target_type: "batch" | "users";
  batch_id: string | null;
  batch_name: string | null;
  user_ids: string[];
  flow: Flow;
  sequential: boolean;
  start_date: string | null;
  pace: { mode: PaceMode; per_day: PerDay };
  weekly_hours: number;
  total_hours: number;
  finish_date: string | null;
  status: "active" | "revoked";
  learner_count: number;
  created_at: string;
}

export interface PathDetail extends PathSummary {
  steps: Step[];
  allocations: Allocation[];
}

/** GET paths/context: what the caller may do, and the active batches they may allocate to. */
export interface PathsContext {
  can_author: boolean;
  can_allocate_any_learner: boolean;
  batches: { id: string; name: string; code: string }[];
}

export interface LinkOption {
  id: string;
  title: string;
  meta?: string | null;
}

/** GET paths/batch-members?batch_id=&q= (active students of one batch). */
export interface BatchMember {
  user_id: string;
  full_name: string | null;
  email: string | null;
}

export interface AllocIn {
  target_type: "batch" | "users";
  batch_id?: string;
  user_ids?: string[];
  flow: Flow;
  sequential: boolean;
  start_date?: string;
  pace: Pace;
}

export interface AllocationPreview {
  per_day: PerDay;
  weekly_hours: number;
  total_hours: number;
  finish_date: string | null;
  days: number;
}

export interface LearnerProgress {
  user_id: string;
  full_name: string | null;
  email: string | null;
  completed_steps: number;
  total_steps: number;
  credits_earned: number;
  total_credits: number;
  pct: number;
  last_activity_at: string | null;
  behind: boolean;
}

export interface AllocationProgress {
  allocation: Allocation;
  path: { id: string; title: string };
  steps: { step_key: string; title: string; step_type: StepType; credits: number }[];
  learners: LearnerProgress[];
}

export interface TocEntry {
  id: string;
  text: string;
  level: number;
}

export interface ArticleSummary {
  id: string;
  organization_id: string;
  title: string;
  subtitle: string | null;
  level: Level | null;
  est_minutes: number | null;
  status: "draft" | "published";
  audience: Audience | null;
  batch_ids: string[];
  user_ids: string[];
  updated_at: string;
}

export interface ArticleDetail extends ArticleSummary {
  body_md: string;
  toc: TocEntry[];
}

export interface ReaderArticle {
  id: string;
  title: string;
  subtitle: string | null;
  level: Level | null;
  est_minutes: number | null;
  body_md: string;
  toc: TocEntry[];
  status: "draft" | "published";
  audience: Audience | null;
  can_edit: boolean;
}

export interface MyPath {
  allocation_id: string;
  path_id: string;
  title: string;
  description_md: string | null;
  flow: Flow;
  sequential: boolean;
  step_count: number;
  completed_count: number;
  total_credits: number;
  credits_earned: number;
  pct: number;
  total_hours: number;
  start_date: string | null;
  finish_date: string | null;
  started: boolean;
}

export interface PlayerStep {
  step_key: string;
  parent_key: string | null;
  number: string;
  depth: 0 | 1;
  step_type: StepType;
  title: string;
  description_md: string | null;
  est_hours: number;
  credits: number;
  url: string | null;
  /** Server-computed (WS4 D9): true only for allow-listed https embed URLs. */
  embeddable: boolean;
  lesson_id: string | null;
  assignment_id: string | null;
  test_id: string | null;
  article_id: string | null;
  state: StepState;
  credits_awarded: number;
  due_date: string | null;
  opened_at: string | null;
  completed_at: string | null;
  min_dwell_seconds: number;
}

export interface PlayerPath {
  allocation_id: string;
  path_id: string;
  title: string;
  description_md: string | null;
  flow: Flow;
  sequential: boolean;
  start_date: string | null;
  finish_date: string | null;
  credits_earned: number;
  total_credits: number;
  pct: number;
  steps: PlayerStep[];
}

export interface CompleteResult {
  step: PlayerStep;
  credits_earned: number;
  pct: number;
}
