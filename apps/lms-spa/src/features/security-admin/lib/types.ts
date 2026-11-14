/**
 * DTOs for the security console. Every backend route here returns `dict[str, Any]`, so the
 * shapes below were verified by reading the router/service code (cited per interface).
 * Request bodies are the Pydantic models in app/modules/security/api_review.py / api_engine.py.
 */

/** verified: app/modules/security/cases.py case_out (SEC-03 row; list envelope adds `counts`). */
export interface CaseSummary {
  case_id: string;
  case_ref: string;
  user_id: string;
  family: string;
  level: number;
  recommended_level: number | null;
  priority: string;
  status: string;
  opened_reason?: string | null;
  hc_rule: string | null;
  score: number | null;
  age_hours: number;
  sla_first_response_due: string | null;
  sla_decision_due: string | null;
  /** "on_track" | "breaching" (≥ 80 % of the window used) | "breached" | "n/a" */
  sla_state: string;
  assignee_id: string | null;
  is_high_risk: boolean;
  high_risk_reasons: string[];
  repeat_count: number;
  organization_id: string | null;
  unblock_request: { reference: string; state: string } | null;
  version: number;
}

/**
 * Pending `security.case.decision` proposal (SEC-04 `pending_approval`).
 * verified: app/modules/security/cases.py pending_proposal — `status` is "pending" or
 * "expired" (72 h lapse while the case stays escalated); null when none is open.
 */
export interface PendingCaseApproval {
  approval_request_id: string;
  status: "pending" | "expired" | string;
  requested_by: string;
  requested_at: string | null;
  created_at?: string | null;
  expires_at: string;
  /** second_approval_reasons of the proposal */
  reasons?: string[];
  /** caller is a distinct reviewer with the approver permission and no conflict */
  can_decide: boolean;
  is_requester: boolean;
  can_withdraw?: boolean;
  payload?: Partial<DecisionPayload> & { second_approval_reasons?: string[] };
}

/** verified: api_review.py get_case → decisions[] */
export interface CaseDecisionRecord {
  decision_id: string;
  outcome: string;
  decided_by: string;
  approved_by: string | null;
  at: string;
}

/** verified: api_review.py get_case → notes[] */
export interface CaseNote {
  at: string;
  visibility: "internal" | "student" | string;
  body: string;
  author_id: string | null;
}

/** verified: api_review.py get_case (case_out + subject, restriction, notes, decisions). */
export interface CaseDetail extends CaseSummary {
  subject: { user_id: string; name: string | null; is_minor: boolean };
  restriction: Restriction | null;
  notes: CaseNote[];
  decisions: CaseDecisionRecord[];
  /** verified: api_review.py get_case → cs.pending_proposal */
  pending_approval: PendingCaseApproval | null;
}

/** verified: app/modules/security/rules.py score_sharing contributions[] */
export interface ContributingSignal {
  signal_id?: string;
  rule: string;
  rule_version?: string | null;
  category?: string | null;
  occurred_at?: string;
  base_points?: number;
  multipliers?: Record<string, unknown>;
  decayed_points?: number;
  evidence?: Record<string, unknown>;
}

/** verified: api_review.py evaluation_out */
export interface RiskEvaluation {
  id: string;
  family: string;
  mode: string;
  ruleset_version: string;
  evaluated_at: string;
  signals: ContributingSignal[];
  subtotals: Record<string, number>;
  repeat_multiplier: number;
  score: number;
  previous_score: number | null;
  level_before: number;
  level_after: number;
  action: string;
  explanation_keys: string[];
}

/** verified: api_review.py explanation (SEC-07) */
export interface CaseExplanation {
  case_ref: string;
  evaluation: RiskEvaluation | null;
  hc_rule: string | null;
  student_explanation_preview: string[];
}

/** verified: app/modules/security/timeline.py timeline (events carry type-specific keys). */
export interface TimelineEvent {
  at: string;
  type: string;
  [field: string]: unknown;
}

/** verified: api_review.py user_timeline */
export interface Timeline {
  subject: { user_id: string; is_minor: boolean; privacy_tier?: string | null; restriction_level?: number | null };
  events: TimelineEvent[];
  page: { next_cursor: string | null; has_more: boolean; limit?: number };
}

/** verified: api_review.py concurrency — raw engaged 5-minute buckets; overlaps are derived client-side. */
export interface Concurrency {
  available: boolean;
  buckets: { device_id: string; session_id: string; bucket: string }[];
}

/** verified: timeline.py device_graph */
export interface DeviceGraph {
  subject: string;
  nodes: (
    | { type: "device"; id: string; label: string | null; hop: number }
    | { type: "account"; id: string; restricted: boolean; hop: number }
  )[];
  edges: { device: string; account: string }[];
}

/** Request body: api_review.py DecisionIn */
export interface DecisionPayload {
  unblock_request_id?: string | null;
  outcome: string;
  resulting_level?: number | null;
  rationale: string;
  student_summary: string;
  conditions?: { user_exception?: { setting_key: string; value: number | string; expires_at: string } | null; password_reset?: boolean; contact_change?: boolean };
  extension_days?: number;
  false_positive_rule_keys?: string[];
}

/** verified: app/modules/security/unblock.py request_out + api_review.py review_queue extras */
export interface ReviewUnblockRow {
  request_id: string;
  reference: string;
  case_ref: string | null;
  state: string;
  state_label?: string;
  closure_reason?: string | null;
  submitted_at: string | null;
  is_second_level_appeal: boolean;
  version: number;
  level: number;
  sla_state: string;
  requires_second_approval: boolean;
  assignee: string | null;
}

/** verified: api_review.py review_get (UNB-11) */
export interface ReviewUnblockDetail {
  request_id: string;
  reference: string;
  case_ref: string | null;
  state: string;
  state_label?: string;
  submitted_at: string | null;
  is_second_level_appeal: boolean;
  version: number;
  what_happened: string[] | null;
  explanation: string | null;
  recognised_device_ids: string[];
  unrecognised_device_ids: string[];
  lab_location_text: string | null;
  attachments: unknown[] | null;
  preferred_contact: string | null;
  timeline: { at: string; state: string; [k: string]: unknown }[] | null;
  assigned_to: string | null;
}

/** verified: app/modules/security/restrictions.py restriction_out */
export interface Restriction {
  restriction_id: string;
  user_id: string;
  level: number;
  family: string;
  scope: string;
  source: string;
  hc_rule: string | null;
  starts_at: string;
  ends_at: string | null;
  deferred_until: string | null;
  /** "active" | "lift_pending" | "ended" */
  state: string;
  case_id: string | null;
  case_ref: string | null;
  ended_at: string | null;
  end_reason: string | null;
}

/** verified: api_engine.py rules */
export interface RuleRow {
  key: string;
  family: string;
  category: string | null;
  description: string;
  explanation_key: string;
  active_version?: { status: string; semver: string | null; params: unknown };
}

/** verified: app/modules/security/controls.py version_out */
export interface RuleVersion {
  version_id: string;
  rule_key: string | null;
  family: string;
  ruleset_version: string | null;
  semver: string;
  status: string;
  definition: unknown;
  shadow_started_at: string | null;
  eligible_at: string | null;
  proposed_by: string;
  approved_by: string | null;
  status_change_reason: string | null;
}

/** verified: app/modules/admin/approvals.py approval_out */
export interface ApprovalSummary {
  approval_request_id: string;
  action_type: string;
  requested_by: string;
  request_reason: string;
  required_approver_role: string;
  status: string;
  expires_at: string;
  created_at: string | null;
}

/** verified: controls.py engine_state */
export interface EngineState {
  "risk.mode": string;
  "risk.hc.auto_restrict_enabled": boolean;
  rules: { rule_key: string; status: string; semver: string | null; source: string; status_change_reason: string | null; circuit_breaker: "open" | "closed" }[];
  rulesets: Record<string, string>;
  pending_ratifications: ApprovalSummary[];
}

/** verified: api_engine.py report_catalogue */
export interface ReportCatalogueEntry {
  report_key: string;
  id: string;
  title: string;
  per_user: boolean;
  accessible: boolean;
  export_approval: string;
  /** reports.py REPORTS[*].filters (returned via `**v`). */
  filters?: string[];
}

/** verified: app/modules/security/reports.py run_report (+ runner extras such as k_min) */
export interface ReportResult {
  report_key: string;
  report_id: string;
  title: string;
  generated_at: string;
  period: { from: string; to: string; timezone: string };
  rows: Record<string, unknown>[];
  k_min?: number;
  [extra: string]: unknown;
}

/** verified: api_engine.py `_export_out` (GET /security/reports/exports, SEC-47 list). */
export interface SecurityExportJob {
  export_job_id: string;
  report_key: string;
  report_id?: string | null;
  status: string;
  contains_pii: boolean;
  row_count?: number | null;
  approval_request_id: string | null;
  created_at: string | null;
  completed_at: string | null;
  download_expires_at: string | null;
  download_path?: string | null;
}

/** verified: api_engine.py export_report 202 body. */
export interface ExportResponse {
  export_job_id: string;
  status: string;
  approval_request_id: string | null;
  contains_pii: boolean;
}

/** verified: api_engine.py dashboard (SEC-40). `engine` is controls.py engine_state. */
export interface SecurityDashboardData {
  queue: Record<string, number>;
  restrictions: Record<string, number>;
  pending_unblock_requests: number;
  engine?: Record<string, unknown>;
}

/** verified: api_engine.py `_inc_out` (SEC-37..39). */
export interface SecurityIncident {
  incident_id: string;
  incident_ref: string;
  title: string;
  severity: string;
  status: string;
  detected_at: string;
  certin_due_at: string | null;
  certin_reported_at: string | null;
  dpb_report_due_at: string | null;
  version: number;
}

/** verified: api_engine.py bulk_status (SEC-44 status). */
export interface BulkLiftStatus {
  bulk_lift_id: string;
  status: string;
  selector: Record<string, unknown>;
  matched: number;
  progress: Record<string, unknown> | null;
  approval_request_id: string | null;
}
