/**
 * TypeScript shapes of the College Data Portal API (apps/college-data/portal/CONTRACT.md, server/schema.sql,
 * server/server.js). The server is unchanged by the React port, so these follow it exactly.
 *
 * Rows carry more fields than listed for some endpoints (the server adds rollup fields over time): every row
 * type has an index signature so a screen can read an extra field without a cast, but the listed fields are
 * the ones the contract promises. Dates are 'YYYY-MM-DD' strings, timestamps ISO strings.
 */

/** Provenance of a number: verified (official / first-hand), estimated (derived), pending (unknown). */
export type Basis = "verified" | "estimated" | "pending" | "unavailable";
/** A number with its provenance (`{value: 180, basis: 'verified'}`). */
export interface ValueBasis {
  value: number | null;
  basis: Basis | null;
}

export type OpStatus = "operational" | "possibly_closed" | "closed" | "pending";
export type ExamState = "in_exams" | "exams_soon" | "clear" | "unknown";
export type Diagnosis = "ambassador_gap" | "low_outreach" | "low_conversion" | "unrealistic_target" | "behind_pace" | "exams" | "data" | "other";
/** Performance / pace status (THE vocabulary: ui/status.ts STATUS_META). */
export type PerfStatus = "behind" | "on_track" | "too_early" | "met" | "exceeded" | "partial_target" | "zero_target" | "no_target";
export type PersonRole = "college_lead" | "ambassador_lead" | "ambassador";
export type PersonStatus = "active" | "onboarding" | "inactive";
export type AssignmentStatus = "assigned" | "unassigned" | "invalid_link";
export type DataStatus = "verified" | "partly" | "unverified";
export type FieldStatus = "verified" | "unverified" | "missing";
export type ScopeType = "state" | "district" | "city" | "college" | "branch" | "person";
/** `scope=` query value: 'state' | 'district:<id>' | 'city:<id>' | 'college:<id>' | 'branch:<id>' | 'person:<id>' */
export type ScopeKey = "state" | `${Exclude<ScopeType, "state">}:${string}`;

/** Paginated envelope (`page` / `page_size` given on /people, /colleges): otherwise those return a plain array. */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  counts?: Record<string, number>;
}

/* ------------------------------------------------------------------ session, meta, program */

/** GET /api/session (proxy mode: always authenticated, sso true, role 'editor' for every LMS admin). */
export interface PortalSession {
  required: boolean;
  auth_required?: boolean;
  authenticated: boolean;
  role: "editor" | "viewer" | "admin" | null;
  user: string | null;
  sso?: boolean;
  sso_provider?: string;
  login_url?: string | null;
  expires_at: string | null;
  viewer_enabled?: boolean;
}

export interface District {
  id: string;
  name: string;
  old_district?: string | null;
  hq_lat?: number | null;
  hq_lng?: number | null;
  targeted?: number;
  /** /api/meta adds per-district counts */
  colleges?: number;
  [k: string]: unknown;
}

export interface City {
  id: string;
  district_id: string;
  name: string;
  lat?: number | null;
  lng?: number | null;
  [k: string]: unknown;
}

export interface Course {
  id: number;
  name: string;
  price_inr: number | null;
  active: number;
  notes?: string | null;
}

/** GET /api/meta */
export interface PortalMeta {
  districts: District[];
  cities: City[];
  courses: Course[];
  settings: Record<string, unknown>;
  counts: Record<string, number>;
  demo: boolean;
  auth?: PortalSession;
  [k: string]: unknown;
}

/** GET /api/program (v3): the programme target and the target district groups. */
export interface Program {
  target: number | null;
  deadline: string | null;
  target_district_groups: Record<string, string[]>;
  target_district_ids: string[];
  districts: { id: string; name: string; colleges_total?: number; colleges?: number; [k: string]: unknown }[];
  [k: string]: unknown;
}

/** GET /api/search?q= */
export interface SearchHit {
  type: "district" | "city" | "college" | "branch" | "person" | (string & {});
  id: string;
  label: string;
  sub?: string | null;
  /** old portal hash link ('#/college/c9'); map it with routes.ts `fromLegacyHref` */
  href?: string | null;
}

/* ------------------------------------------------------------------ colleges, branches, people */

export interface NextExam {
  semester: string;
  kind: string;
  start: string | null;
  end: string | null;
}

/** Row of GET /api/colleges */
export interface CollegeRow {
  id: string;
  sno: number;
  name: string;
  short_name: string | null;
  district_id: string;
  city_id: string | null;
  lat: number | null;
  lng: number | null;
  geo_precision: "exact" | "town" | "district" | "pending" | null;
  op_status: OpStatus | null;
  targeted: number;
  tier?: string | null;
  autonomous?: number | string | null;
  branches?: number;
  strength?: ValueBasis;
  eligible?: ValueBasis;
  college_lead?: unknown;
  ambassador_leads?: number;
  ambassadors?: number;
  branches_needing_ambassadors?: number;
  target: number | null;
  enrolled: number;
  remaining: number | null;
  pct: number | null;
  on_track: boolean | null;
  pace_status?: PerfStatus | null;
  diagnosis: Diagnosis | null;
  exam_state: ExamState | null;
  next_exam: NextExam | null;
  followups_open?: number;
  next_followup?: unknown;
  lead?: { id: number; name: string; phone: string | null } | null;
  ambassador_count?: number;
  unassigned_count?: number;
  data_status?: DataStatus;
  [k: string]: unknown;
}

/** `college` block of GET /api/colleges/:id */
export interface College extends CollegeRow {
  aliases?: string[] | null;
  address?: string | null;
  website?: string | null;
  phone?: string | null;
  email?: string | null;
  ownership?: string | null;
  affiliation?: string | null;
  naac?: string | null;
  nirf?: string | null;
  op_status_note?: string | null;
  notes?: string | null;
  is_demo?: number;
  verified_fields?: Record<string, { source?: string; on?: string; by?: string } | unknown>;
  field_status?: Partial<Record<string, FieldStatus>>;
  updated_at?: string | null;
  updated_by?: string | null;
}

export interface Branch {
  id: number;
  college_id: string;
  code: string;
  name: string;
  category: "it_core" | "it_allied" | "circuit" | "core" | "other";
  is_relevant: number;
  intake_per_year: number | null;
  intake_basis: Basis | null;
  strength_total: number | null;
  strength_basis: Basis | null;
  final_year: number | null;
  final_year_basis: Basis | null;
  eligible_estimate: number | null;
  eligible_basis: Basis | null;
  notes?: string | null;
  [k: string]: unknown;
}

export interface TargetSummary {
  min: number | null;
  target: number | null;
  max: number | null;
  remaining: number | null;
  exceeded_by: number | null;
  pct: number | null;
  status: PerfStatus;
}

/** Row of GET /api/people (v4 fields included) */
export interface Person {
  id: number;
  college_id: string;
  role: PersonRole;
  full_name: string;
  phone: string | null;
  email: string | null;
  reports_to: number | null;
  status: PersonStatus;
  joined_on: string | null;
  notes?: string | null;
  college?: { id: string; name: string; short_name: string | null; district_id: string } | null;
  college_name?: string;
  lead?: { id: number; name: string; role: PersonRole; status: PersonStatus } | null;
  assignment_status?: AssignmentStatus;
  assignment_issue?: string | null;
  links?: { tel: string | null; whatsapp: string | null; mailto: string | null };
  team_size?: number;
  actual_own?: number;
  actual_team?: number;
  actual_combined?: number;
  target_summary?: TargetSummary;
  branches?: unknown[];
  [k: string]: unknown;
}

/** GET /api/summary?scope= (also the `rollup` of detail endpoints) */
export interface Summary {
  scope: string;
  label: string;
  target: number | null;
  target_source: "explicit" | "sum_of_children" | "none";
  reconciled: boolean;
  children_target_sum: number | null;
  enrolled: number;
  reached: number;
  remaining: number | null;
  pct: number | null;
  deadline: string | null;
  on_track: boolean | null;
  pace_status?: PerfStatus;
  diagnosis: Diagnosis | null;
  [k: string]: unknown;
}

/** GET /api/colleges/:id */
export interface CollegeDetail {
  college: College;
  rollup: Summary;
  branches: (Branch & { rollup?: Summary; people?: Person[] })[];
  people: Person[];
  exams: Exam[];
  followups: Followup[];
  recent_activities: Activity[];
  recent_enrollments: Enrollment[];
  audit: AuditEntry[];
  [k: string]: unknown;
}

/* ------------------------------------------------------------------ outreach records */

export interface Followup {
  id: number;
  scope_type: "college" | "branch" | "person";
  scope_id: string;
  owner_person_id: number | null;
  owner_name: string | null;
  due_date: string | null;
  status: "open" | "done";
  issue: Diagnosis | null;
  title: string | null;
  notes: string | null;
  last_contact: string | null;
  created_at: string;
  created_by: string;
  done_at: string | null;
  [k: string]: unknown;
}

export interface Exam {
  id: number;
  college_id: string;
  semester: "3-1" | "4-1";
  exam_body: string | null;
  status: string | null;
  endsem_start: string | null;
  endsem_end: string | null;
  [k: string]: unknown;
}

export interface Activity {
  id: number;
  college_id: string;
  branch_id: number | null;
  person_id: number | null;
  on_date: string;
  type: "visit" | "call" | "session" | "whatsapp" | "followup" | "other";
  students_reached: number;
  notes: string | null;
  [k: string]: unknown;
}

export type EnrollmentStage = "lead" | "interested" | "registered" | "applied" | "confirmed" | "dropped";
export interface Enrollment {
  id: number;
  college_id: string;
  branch_id: number | null;
  course_id: number | null;
  person_id: number | null;
  student_name: string | null;
  enrolled_on: string;
  amount_inr: number | null;
  stage: EnrollmentStage;
  [k: string]: unknown;
}

export type ContactRole = "tpo" | "principal" | "hod" | "office" | "admissions" | "dean" | "other";
export interface Contact {
  id: number;
  college_id: string;
  branch_id: number | null;
  name: string | null;
  role: ContactRole;
  phone: string | null;
  email: string | null;
  basis: "verified" | "pending";
  status: "untested" | "working" | "non_working" | "invalid";
  verified_by?: string | null;
  verified_on?: string | null;
  [k: string]: unknown;
}

export type CallOutcome =
  | "connected_interested"
  | "connected_callback"
  | "connected_not_interested"
  | "connected_info_only"
  | "no_answer"
  | "busy"
  | "switched_off"
  | "not_reachable"
  | "wrong_number"
  | "invalid_number"
  | "disconnected";
export interface Call {
  id: number;
  contact_id: number | null;
  college_id: string;
  branch_id: number | null;
  called_at: string;
  caller: string;
  outcome: CallOutcome;
  notes: string | null;
  next_action_at: string | null;
  [k: string]: unknown;
}

export interface Target {
  id: number;
  scope_type: ScopeType;
  scope_id: string;
  course_id: number | null;
  target: number;
  min?: number | null;
  max?: number | null;
  period?: string;
  period_start?: string | null;
  period_key?: string;
  deadline: string | null;
  notes: string | null;
  [k: string]: unknown;
}

/** Row of GET /api/performance */
export interface PerformanceRow {
  id: string | number;
  name: string;
  href: string | null;
  level: "person" | "college" | "district" | "state";
  min: number | null;
  target: number | null;
  max: number | null;
  actual: number;
  remaining: number | null;
  exceeded_by: number | null;
  pct: number | null;
  status: PerfStatus;
  [k: string]: unknown;
}

export interface AuditEntry {
  id: number;
  at: string;
  actor: string;
  action: "create" | "update" | "delete";
  entity: string;
  entity_id: string;
  before: unknown;
  after: unknown;
  [k: string]: unknown;
}

/** GET /api/attention */
export interface AttentionItem {
  type: string;
  id: string;
  label: string;
  href: string | null;
  reasons: string[];
  diagnosis: Diagnosis | null;
  severity: "high" | "medium" | "low" | (string & {});
  count?: number;
  [k: string]: unknown;
}

/** GET /api/timeseries */
export interface TimePoint {
  date: string;
  enrolled: number;
  reached: number;
}
