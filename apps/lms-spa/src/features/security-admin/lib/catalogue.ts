/** Static vocabularies from api-specification SEC-31 / RE §10 (report keys, filters, outcomes). */

export interface ReportDef {
  code: string;
  key: string;
  title: string;
  perUser: boolean;
}

/** Section H numbering shared by RE §10, SEC-30/31 and the PRD (resolves I-15). */
export const SECTION_H_REPORTS: ReportDef[] = [
  { code: "H1", key: "top-suspicious-accounts", title: "Top suspicious accounts", perUser: true },
  { code: "H2", key: "account-device-associations", title: "Multiple-account/device associations", perUser: true },
  { code: "H3", key: "concurrent-login-events", title: "Concurrent login events", perUser: true },
  { code: "H4", key: "repeated-network-device-associations", title: "Repeated IP/device associations", perUser: false },
  { code: "H5", key: "blocked-accounts", title: "Blocked accounts", perUser: true },
  { code: "H6", key: "pending-unblock-requests", title: "Pending unblock requests", perUser: true },
  { code: "H7", key: "average-review-time", title: "Average review time", perUser: false },
  { code: "H8", key: "false-positive-rate", title: "False-positive rate", perUser: false },
  { code: "H9", key: "repeat-incidents", title: "Repeat incidents", perUser: true },
  { code: "H10", key: "active-session-counts", title: "Active-session counts", perUser: false },
  { code: "H11", key: "learning-activity", title: "Daily/weekly/monthly learning activity", perUser: false },
  { code: "H12", key: "device-login-history", title: "Device and login history", perUser: true },
  { code: "ENG", key: "engine-health", title: "Policy and engine health", perUser: false },
];

export function reportByKey(key: string): ReportDef | undefined {
  return SECTION_H_REPORTS.find((r) => r.key === key);
}

export const CASE_STATUS_OPTIONS = [
  { value: "open,under_review,escalated", label: "All open" },
  { value: "open", label: "Open" },
  { value: "under_review", label: "Under review" },
  { value: "escalated", label: "Escalated" },
  { value: "decided,closed", label: "Decided / closed" },
];

export const LEVEL_OPTIONS = [
  { value: "", label: "Any level" },
  { value: "2,3,4", label: "Verify and above (L2–L4)" },
  { value: "3,4", label: "Restricted or suspended (L3–L4)" },
  { value: "1", label: "L1 · Notice" },
  { value: "2", label: "L2 · Verify" },
  { value: "3", label: "L3 · Temporary restriction" },
  { value: "4", label: "L4 · Suspended" },
];

/** Restriction sources in words ("hc_rule" is a high-confidence rule that restricts on its own). */
export const SOURCE_OPTIONS = [
  { value: "", label: "Any source" },
  { value: "engine", label: "Risk engine" },
  { value: "hc_rule", label: "High-confidence rule" },
  { value: "reviewer", label: "Reviewer" },
  { value: "support", label: "Support" },
];

export function sourceLabel(source: string | null | undefined): string {
  if (!source) return "—";
  return SOURCE_OPTIONS.find((o) => o.value === source)?.label ?? source.charAt(0).toUpperCase() + source.slice(1).replace(/_/g, " ");
}

export const FAMILY_OPTIONS = [
  { value: "", label: "Any family" },
  { value: "sharing", label: "Sharing" },
  { value: "takeover", label: "Takeover" },
  ];

export const SLA_OPTIONS = [
  { value: "", label: "Any SLA state" },
  { value: "on_track", label: "On track" },
  { value: "breaching", label: "At risk" },
  { value: "breached", label: "Breached" },
];

export const ASSIGNEE_OPTIONS = [
  { value: "", label: "Anyone" },
  { value: "me", label: "Me" },
];

/** SEC-09 outcomes with the level each one results in by default. */
export const DECISION_OUTCOMES = [
  { value: "lift_with_warning", label: "Lift (with warning)", lift: true, defaultLevel: 0 },
  { value: "lift_false_positive", label: "Lift — false positive", lift: true, defaultLevel: 0 },
  { value: "lift_conditions", label: "Lift with conditions", lift: true, defaultLevel: 0 },
  { value: "reduce_level", label: "Reduce to L2 (verify)", lift: false, defaultLevel: 2 },
  { value: "uphold", label: "Uphold", lift: false, defaultLevel: -1 },
  { value: "convert_L4", label: "Convert to L4 (suspend)", lift: false, defaultLevel: 4 },
  // Only for a case with no active restriction (manual / support escalation): nothing on the account changes.
  { value: "close_no_action", label: "Close — no action needed", lift: false, defaultLevel: -1 },
] as const;

/** Outcomes the API accepts for this case: lift / uphold / reduce need an active restriction, close_no_action needs none. */
export function outcomesFor(restricted: boolean) {
  return DECISION_OUTCOMES.filter((o) => (restricted ? o.value !== "close_no_action" : o.value === "close_no_action" || o.value === "convert_L4"));
}

export const UNBLOCK_STATE_OPTIONS = [
  { value: "submitted,under_review,info_requested,escalated", label: "All pending" },
  { value: "submitted", label: "Submitted" },
  { value: "under_review", label: "Under review" },
  { value: "info_requested", label: "Information requested" },
  { value: "escalated", label: "Escalated" },
  { value: "approved,rejected,closed", label: "Decided / closed" },
];

/** Keys verified against app/modules/security/unblock.py INFO_TEMPLATES. */
export const INFO_TEMPLATES_FALLBACK = [
  { key: "confirm_second_location", label: "Confirm the second location" },
  { key: "identify_devices", label: "Identify the devices" },
  { key: "shared_computer_details", label: "Shared computer details" },
  { key: "travel_details", label: "Travel details" },
  { key: "other", label: "Other (free text)" },
];

/* ------------------------------------------------------------- report filters */

/** How a Section H filter is entered. Mirrors app/modules/security/reports.py REPORTS[*].filters. */
export type ReportFilterKind = "date" | "uuid" | "text" | "int" | "select";

export interface ReportFilterDef {
  name: string;
  label: string;
  kind: ReportFilterKind;
  options?: { value: string; label: string }[];
  hint?: string;
}

/** verified: reports.py `_int_filter` takes one level; `_uuid_filter` needs a UUID; `_h11` granularity day|week|month. */
export const REPORT_FILTER_DEFS: Record<string, ReportFilterDef> = {
  from: { name: "from", label: "From", kind: "date", hint: "IST date" },
  to: { name: "to", label: "To", kind: "date", hint: "IST date, inclusive" },
  user_id: { name: "user_id", label: "User id", kind: "uuid", hint: "Copy it from the user's page or case" },
  assignee: { name: "assignee", label: "Assignee (user id)", kind: "uuid" },
  reviewer: { name: "reviewer", label: "Reviewer (user id)", kind: "uuid" },
  rule: { name: "rule", label: "Rule key", kind: "text" },
  level: {
    name: "level",
    label: "Level",
    kind: "select",
    options: LEVEL_OPTIONS.filter((o) => !o.value.includes(",")),
  },
  family: { name: "family", label: "Family", kind: "select", options: FAMILY_OPTIONS },
  sla_state: { name: "sla_state", label: "Response time (SLA)", kind: "select", options: SLA_OPTIONS },
  source: {
    name: "source",
    label: "Source",
    kind: "select",
    options: SOURCE_OPTIONS,
  },
  state: {
    name: "state",
    label: "State",
    kind: "select",
    options: [
      { value: "", label: "All pending" },
      { value: "submitted", label: "Submitted" },
      { value: "under_review", label: "Under review" },
      { value: "info_requested", label: "Information requested" },
      { value: "escalated", label: "Escalated" },
    ],
  },
  min_accounts: { name: "min_accounts", label: "Minimum accounts", kind: "int" },
  days: { name: "days", label: "Days", kind: "int" },
  tier: { name: "tier", label: "Session tier", kind: "text", hint: "e.g. student" },
  client_type: { name: "client_type", label: "Client type", kind: "text", hint: "e.g. web" },
  granularity: {
    name: "granularity",
    label: "Granularity",
    kind: "select",
    options: [
      { value: "day", label: "Day" },
      { value: "week", label: "Week" },
      { value: "month", label: "Month" },
    ],
  },
};

/** Fallback when the catalogue (SEC-30) has not answered: same lists as reports.py REPORTS. */
export const REPORT_FILTERS: Record<string, string[]> = {
  "top-suspicious-accounts": ["level", "family", "rule", "sla_state", "assignee"],
  "account-device-associations": ["min_accounts", "days"],
  "concurrent-login-events": ["from", "to", "user_id", "rule"],
  "repeated-network-device-associations": ["from", "to"],
  "blocked-accounts": ["level", "family", "source"],
  "pending-unblock-requests": ["level", "state"],
  "average-review-time": ["from", "to", "level", "reviewer"],
  "false-positive-rate": ["from", "to"],
  "repeat-incidents": [],
  "active-session-counts": ["tier", "client_type"],
  "learning-activity": ["from", "to", "granularity"],
  "device-login-history": ["from", "to", "user_id"],
  "engine-health": [],
};

/** Filters a report cannot run without (reports.py `validate_filters` / `_h12`). */
export const REQUIRED_REPORT_FILTERS: Record<string, string[]> = { "device-login-history": ["user_id"] };

/** H3 covers at most 14 days (reports.py H3_MAX_DAYS); other dated reports default to 30. */
export function defaultReportDays(reportKey: string): number {
  return reportKey === "concurrent-login-events" ? 14 : 30;
}

/** Envelope keys of SEC-31; everything else a runner returns is secondary data (ADM-07). */
export const REPORT_ENVELOPE_KEYS = new Set(["report_key", "report_id", "title", "generated_at", "period", "filters_applied", "rows"]);
