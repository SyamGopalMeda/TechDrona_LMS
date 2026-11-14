/**
 * THE status vocabulary (components.js CHIP / STATUS / BASIS): labels, tones and explanations used on every
 * page. Never invent a label or colour for a status in a screen: read it from here.
 */

export type Tone = "neutral" | "good" | "warn" | "bad" | "info" | "brand";
export const TONES: readonly Tone[] = ["neutral", "good", "warn", "bad", "info", "brand"];

export interface StatusMeta {
  label: string;
  tone: Tone;
  tip: string;
}

const PERF_CHIP: Record<string, [string, Tone, string]> = {
  exceeded: ["Exceeded", "good", "Actual is above the target."],
  met: ["Target met", "good", "Actual equals the target."],
  on_track: ["On track", "good", "At least 80% of the enrolments expected by today (straight line from the period start)."],
  behind: ["Behind", "bad", "Less than 80% of the enrolments expected by today."],
  too_early: ["Too early", "info", "Less than 7 days into the period — too early to judge pace."],
  partial_target: ["Partly targeted", "warn", "Only some of the people or places in this group have a target, so it is not judged as a whole."],
  zero_target: ["Target is 0", "neutral", "The target was set to 0 on purpose, so there is no %."],
  no_target: ["No target", "neutral", "No target has been set for this period."],
};

/** Order used for summary cards and filters (cards must add up to the row count). */
export const PERF_STATUS_ORDER = ["behind", "on_track", "too_early", "met", "exceeded", "partial_target", "zero_target", "no_target"] as const;

const CHIP: Record<string, [string, Tone, string?]> = {
  ...PERF_CHIP,
  assigned: ["Has lead", "good", "Reports to an active lead of the same college."],
  unassigned: ["No lead", "warn", "This ambassador does not report to anyone yet."],
  invalid_link: ["Lead invalid", "bad", "Reports to someone who is inactive, in another college or not a lead."],
  active: ["Active", "good"],
  onboarding: ["Onboarding", "info"],
  inactive: ["Inactive", "neutral"],
  verified: ["Verified", "good", "Confirmed from an official or first-hand source."],
  unverified: ["Unverified", "warn", "Entered without a source — not yet checked."],
  missing: ["Missing", "neutral", "No value recorded."],
  open: ["Open", "info"],
  overdue: ["Overdue", "bad"],
  done: ["Done", "good"],
};

/** Status chips that carry an icon instead of a dot. */
export const CHIP_ICON: Record<string, string> = { verified: "check", met: "check", exceeded: "check", behind: "warn", invalid_link: "warn", overdue: "clock", too_early: "clock" };

export const STATUS_META: Readonly<Record<string, StatusMeta>> = Object.freeze(
  Object.fromEntries(Object.entries(CHIP).map(([k, [label, tone, tip]]) => [k, Object.freeze({ label, tone, tip: tip ?? "" })])),
);

const isEmpty = (v: unknown) => v === null || v === undefined || v === "";

/** {label, tone, tip} for any status key (unknown keys get a readable label and a neutral tone). */
export function statusMeta(status: string | null | undefined): StatusMeta {
  if (status && Object.prototype.hasOwnProperty.call(STATUS_META, status)) return STATUS_META[status]!;
  return { label: isEmpty(status) ? "—" : humanize(String(status)), tone: "neutral", tip: "" };
}

export function humanize(s: string): string {
  return s.replace(/_/g, " ").replace(/^\w/, (m) => m.toUpperCase());
}

/** Kind-specific badges (components.js `statusBadge(kind, value)`). */
export const STATUS_KINDS: Record<string, Record<string, [string, Tone]>> = {
  exam_state: {
    in_exams: ["Exams in progress", "bad"],
    exams_soon: ["Exams soon", "warn"],
    clear: ["No exams — good time", "good"],
    unknown: ["Exam dates unknown", "neutral"],
  },
  op_status: {
    operational: ["Operational", "good"],
    possibly_closed: ["Possibly closed", "warn"],
    closed: ["Closed", "bad"],
    pending: ["Status pending", "neutral"],
  },
  on_track: {
    on_track: ["On track", "good"],
    behind: ["Behind", "bad"],
    no_target: ["No target", "neutral"],
  },
  followup: {
    open: ["Open", "info"],
    overdue: ["Overdue", "bad"],
    done: ["Done", "good"],
  },
  person_status: {
    active: ["Active", "good"],
    onboarding: ["Onboarding", "info"],
    inactive: ["Inactive", "neutral"],
  },
  diagnosis: {
    ambassador_gap: ["Need ambassadors", "bad"],
    low_outreach: ["Low outreach", "warn"],
    low_conversion: ["Low conversion", "warn"],
    unrealistic_target: ["Target too high", "warn"],
    behind_pace: ["Behind pace", "warn"],
    exams: ["Exams", "info"],
    data: ["Data gaps", "neutral"],
    other: ["Other", "neutral"],
  },
};
export type StatusKind = keyof typeof STATUS_KINDS;

export const DIAG_TIPS: Record<string, string> = {
  ambassador_gap: "At least one relevant branch has no active ambassador.",
  low_outreach: "Fewer students reached than the pace needs.",
  low_conversion: "Students are being reached but few are enrolling.",
  unrealistic_target: "Target is more than half of the eligible students.",
  behind_pace: "Enrolments are behind the expected pace for the deadline.",
};

/** Provenance labels (components.js BASIS). */
export const BASIS_META: Record<"verified" | "estimated" | "pending", { label: string; icon: string | null; cls: string; tip: string }> = {
  verified: { label: "Verified", icon: "check", cls: "verified", tip: "Verified — confirmed from an official or first-hand source." },
  estimated: {
    label: "≈ Estimated",
    icon: null,
    cls: "estimated",
    tip: "Estimated — calculated from other known numbers (for example intake × 4). Treat it as approximate.",
  },
  pending: { label: "Pending verification", icon: null, cls: "pending", tip: "Pending — not yet known or not yet checked. Do not rely on this value." },
};
