import type { LessonFunnelCourse, ProgressDistribution } from "@/features/trainer/shared/report-sections";

/** Batch (cohort) DTOs. Moved from the removed college portal (single-company plan §3). */

/** verified: app/modules/orgs/router.py `_batch_out` (organization_id = the company org). */
export interface Batch {
  id: string;
  /** Always the company org (still returned by `_batch_out`); not shown in the UI. */
  organization_id: string;
  name: string;
  code: string;
  /** Shown as "Intake" (plan §3). */
  academic_year?: string | null;
  graduation_year?: number | null;
  starts_on?: string | null;
  ends_on?: string | null;
  status: string;
}

/** ORG-25 batch member. verified: app/modules/orgs/router.py batch_members */
export interface BatchMember {
  user_id: string;
  full_name: string | null;
  member_role: string;
  added_at?: string;
}

/** k-floored count: a number, or a string like "<10" when the group is too small. */
export type KCount = number | string;

/** `_dist` cell. verified: app/modules/analytics/reports.py `_dist` ("<10" when suppressed). */
export interface KDist {
  n: KCount;
  median_s: number | string;
  p90_s: number | string;
  suppressed: boolean;
}

/** ANL-06 batch report. verified: app/modules/analytics/reports.py batch_report */
export interface BatchReport {
  batch_id: string;
  week_start: string;
  learners_total: number;
  weekly_learning_time: KDist;
  learners: { user_id: string; weekly_learning_s: number; weak_topics: number; needs_attention: boolean; reasons: string[] }[];
  progress_distribution: ProgressDistribution | null;
  lesson_funnel: LessonFunnelCourse[] | null;
  measurement_version: string | number;
}

/** RBAC grant at batch scope (trainer / evaluator). verified: app/modules/rbac/router.py `_grant_out` */
export interface BatchStaffGrant {
  grant_id: string;
  user_id: string;
  role_key: string;
  scope_type: string;
  scope_id: string | null;
  granted_at: string;
  expires_at: string | null;
}

/** ADM-02 user search row (subset). verified: app/modules/admin user search. */
export interface UserHit {
  user_id: string;
  display_name: string | null;
  email: string | null;
  status: string;
  roles: string[];
}

export interface BatchCreateBody {
  name: string;
  code: string;
  academic_year: string | null;
  graduation_year: number | null;
  starts_on: string | null;
  ends_on: string | null;
  /** Omitted: the api picks "planned" for a future start date (IST), else "active". */
  status?: "planned" | "active";
}
