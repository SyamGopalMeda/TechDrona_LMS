/**
 * Calling-system and team vocabulary shared by every screen (old js/views/forms.js exports + followups.js ISSUES).
 * Keys are the STORED values (never change them); only the wording shown to people changes
 * (owner-reviewed: docs/qa/college-portal/calls-followups-admin.md).
 */
import type { ReactNode } from "react";
import { Badge } from "../ui/Badges";
import { cx } from "../ui/context";
import { Icon } from "../ui/Icon";
import type { Tone } from "../ui/status";

/* ------------------------------------------------------------------ contacts and calls */

export const CONTACT_ROLE_LABEL: Record<string, string> = {
  tpo: "Placement officer (TPO)",
  principal: "Principal",
  hod: "Head of department",
  office: "College office",
  admissions: "Admissions",
  dean: "Dean",
  other: "Other",
};

/** Number status: set by logged calls (or by hand). [label, tone] */
export const CONTACT_STATUS: Record<string, [string, Tone]> = {
  untested: ["Not tried yet", "neutral"],
  working: ["Working", "good"],
  non_working: ["Not working", "warn"],
  invalid: ["Wrong number", "bad"],
};

export interface OutcomeMeta {
  label: string;
  group: "connected" | "unanswered" | "bad";
  tone: Tone;
  /** suggested call-back in days (null = none) */
  next: number | null;
  /** what to pick it for (button tooltip) */
  hint?: string;
}

/** Call outcomes. hint = what to pick it for (button tooltip). next = suggested call-back in days (null = none). */
export const OUTCOMES: Record<string, OutcomeMeta> = {
  connected_interested: { label: "Interested", group: "connected", tone: "good", next: 3, hint: "They want to go ahead or hear more" },
  connected_callback: { label: "Asked to call back", group: "connected", tone: "info", next: 1, hint: "Busy now, or asked us to call another time" },
  connected_info_only: { label: "Took details only", group: "connected", tone: "info", next: 7, hint: "Listened or asked for details, no decision" },
  connected_not_interested: { label: "Not interested", group: "connected", tone: "neutral", next: null, hint: "Said no" },
  no_answer: { label: "No answer", group: "unanswered", tone: "warn", next: 1, hint: "It rang, nobody picked up" },
  busy: { label: "Line busy", group: "unanswered", tone: "warn", next: 1, hint: "Engaged tone, or the call was cut" },
  switched_off: { label: "Switched off", group: "unanswered", tone: "warn", next: 1, hint: "Phone switched off" },
  not_reachable: { label: "Not reachable", group: "unanswered", tone: "warn", next: 1, hint: "Out of coverage / network message" },
  wrong_number: { label: "Wrong person", group: "bad", tone: "bad", next: null, hint: "Someone answered who is not with this college" },
  invalid_number: { label: "Number does not exist", group: "bad", tone: "bad", next: null, hint: '"This number does not exist" or too few digits' },
  disconnected: { label: "Number out of service", group: "bad", tone: "bad", next: null, hint: '"Temporarily out of service" / permanently disconnected' },
};

/** College calling status (derived by the server from calls, call-backs and enrollments). [label, tone] */
export const CALL_STATUS: Record<string, [string, Tone]> = {
  not_called: ["Not called yet", "neutral"],
  attempted_no_answer: ["No answer yet", "warn"],
  follow_up_due: ["Call-back due", "info"],
  contacted: ["Spoke to them", "brand"],
  interested: ["Interested", "good"],
  participation_confirmed: ["College agreed", "good"],
  enrolled: ["Students enrolled", "good"],
};

/* ------------------------------------------------------------------ enrollments */

export const STAGE_OPTS = [
  { value: "lead", label: "Lead (contact taken)" },
  { value: "interested", label: "Interested" },
  { value: "registered", label: "Registered (form filled)" },
  { value: "applied", label: "Applied (fee pending)" },
  { value: "confirmed", label: "Confirmed (counts)" },
  { value: "dropped", label: "Dropped / refunded" },
];
export const STAGE_LABEL: Record<string, string> = { lead: "Lead", interested: "Interested", registered: "Registered", applied: "Applied", confirmed: "Confirmed", dropped: "Dropped" };
export const STAGE_TONE: Record<string, Tone> = { lead: "neutral", interested: "info", registered: "info", applied: "warn", confirmed: "good", dropped: "bad" };

/* ------------------------------------------------------------------ team, branches, activities */

export const ROLE_OPTS = [
  { value: "ambassador", label: "Ambassador" },
  { value: "ambassador_lead", label: "Ambassador lead" },
  { value: "college_lead", label: "College lead" },
];
export const ROLE_LABEL: Record<string, string> = { college_lead: "College lead", ambassador_lead: "Ambassador lead", ambassador: "Ambassador" };
export const PERSON_STATUS_OPTS = [
  { value: "active", label: "Active" },
  { value: "onboarding", label: "Onboarding" },
  { value: "inactive", label: "Inactive (deactivated)" },
];
export const BASIS_OPTS = [
  { value: "verified", label: "Verified (official source)" },
  { value: "estimated", label: "Estimated" },
  { value: "pending", label: "Pending / unknown" },
];
/** Branch categories: [name, examples] (same text as branch.js CATEGORY_LABEL and Settings → Branch relevance). */
export const CATEGORY: Record<string, [string, string]> = {
  it_core: ["Computer science", "CSE, IT and similar"],
  it_allied: ["CS-related (AI, data, IoT…)", "AI/ML, Data Science, IoT, Cyber Security, CS & Business Systems…"],
  circuit: ["Electronics / electrical", "ECE, EEE, EIE — strong overlap with software roles"],
  core: ["Other engineering", "Civil, Mechanical, Chemical…"],
  other: ["Other", "Anything else"],
};
export const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(Object.entries(CATEGORY).map(([k, [l]]) => [k, l]));
export const CATEGORY_OPTS = Object.entries(CATEGORY).map(([value, [label]]) => ({ value, label }));
export const ACT_OPTS = [
  { value: "visit", label: "Campus visit" },
  { value: "call", label: "Call" },
  { value: "session", label: "Session / workshop" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "followup", label: "Follow-up" },
  { value: "other", label: "Other" },
];
export const OP_OPTS = [
  { value: "operational", label: "Operational" },
  { value: "possibly_closed", label: "Possibly closed" },
  { value: "closed", label: "Closed" },
  { value: "pending", label: "Pending / unknown" },
];

/* ------------------------------------------------------------------ follow-ups */

/** Follow-up reason (stored column `issue`; the keys never change, only the wording). [label, tone] */
export const ISSUES: Record<string, [string, Tone]> = {
  ambassador_gap: ["No ambassador", "bad"],
  low_outreach: ["Few students reached", "warn"],
  low_conversion: ["Few enrolling", "warn"],
  unrealistic_target: ["Target too high", "info"],
  exams: ["Exam timing", "info"],
  data: ["Fix data", "neutral"],
  other: ["General", "neutral"],
};
export const ISSUE_HELP: Record<string, string> = {
  ambassador_gap: "A branch or college has no active ambassador.",
  low_outreach: "Few students reached recently.",
  low_conversion: "Students reached, but few enrolled.",
  unrealistic_target: "The target looks too high for the number of students.",
  exams: "Plan around end-semester exams.",
  data: "Something in the records needs checking.",
  other: "Anything else, e.g. a call-back.",
};
/** What a follow-up is about. */
export const FOLLOWUP_SCOPE_LABEL: Record<string, string> = { college: "College", branch: "Branch", person: "Team member" };

/** A call-back created by "Log call" (stored as issue 'other' with the title "Call back …"): shown as its own reason. */
export function isCallBack(r: { issue?: unknown; title?: unknown }): boolean {
  return ((r.issue as string) || "other") === "other" && /^Call back /.test(String(r.title || ""));
}
/** [label, tone] of a follow-up's reason ("Call-back" for call-backs). */
export function reasonOf(r: { issue?: unknown; title?: unknown }): [string, Tone] {
  if (isCallBack(r)) return ["Call-back", "info"];
  const k = (r.issue as string) || "other";
  return ISSUES[k] ?? [k, "neutral"];
}

/* ------------------------------------------------------------------ phone numbers */

/** "+919876543210" / "98765-43210" → "+91 98765 43210". Anything else is returned unchanged. */
export function formatPhone(v: unknown): string {
  if (v === null || v === undefined) return "";
  const d = String(v).replace(/[\s()-]/g, "");
  const m = d.match(/^(?:\+?91)?([6-9]\d{4})(\d{5})$/) || d.match(/^\+91(\d{5})(\d{5})$/);
  return m ? `+91 ${m[1]} ${m[2]}` : String(v).trim();
}

export const PERSON_PHONE_RULE = "Enter a 10-digit Indian mobile number, e.g. 98765 43210 (+91 optional).";

/** Exact mirror of server/db.js normPhone (v4.1): any Indian number (mobile or STD landline) → "+91XXXXXXXXXX", else null. */
export function normAnyPhone(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  let s = String(v).split(/\b(?:ext|extn)\b|\bx\s*\d|[,;/]/i)[0] ?? "";
  s = s.replace(/[^\d+]/g, "");
  let d = s.replace(/\+/g, "");
  if (s.startsWith("+") && !d.startsWith("91")) return null; // foreign number
  if (d.startsWith("0091")) d = d.slice(4);
  if (d.length === 13 && d.startsWith("910")) d = d.slice(3);
  if (d.length === 12 && d.startsWith("91")) d = d.slice(2);
  else if (d.length === 11 && d.startsWith("0")) d = d.slice(1);
  if (!/^[1-9]\d{9}$/.test(d)) return null;
  return `+91${d}`;
}
/** People: mobile only (server isMobile: ^\+91[6-9]\d{9}$). */
export function normPhone(v: unknown): string | null {
  const n = normAnyPhone(v);
  return n && /^\+91[6-9]\d{9}$/.test(n) ? n : null;
}
/** Trimmed, lower-cased email (null when blank). */
export function normEmail(v: unknown): string | null {
  const s = v === null || v === undefined ? "" : String(v).trim();
  return s ? s.toLowerCase() : null;
}

/* ------------------------------------------------------------------ badges and links */

export function StageBadge({ stage }: { stage: string | null | undefined }) {
  const k = stage || "confirmed";
  return <Badge tone={STAGE_TONE[k] ?? "neutral"}>{STAGE_LABEL[k] ?? k}</Badge>;
}
export function ContactStatusBadge({ status }: { status: string | null | undefined }) {
  const [l, t] = CONTACT_STATUS[status ?? ""] ?? [status ?? "—", "neutral"];
  return <Badge tone={t}>{l}</Badge>;
}
export function CallStatusBadge({ status }: { status: string | null | undefined }) {
  const [l, t] = CALL_STATUS[status ?? ""] ?? [status ?? "—", "neutral"];
  return <Badge tone={t}>{l}</Badge>;
}
export function OutcomeBadge({ outcome }: { outcome: string | null | undefined }) {
  const o = OUTCOMES[outcome ?? ""];
  return <Badge tone={o?.tone ?? "neutral"}>{o?.label ?? outcome ?? "—"}</Badge>;
}
export function ReasonBadge({ row }: { row: { issue?: unknown; title?: unknown } }) {
  const [l, t] = reasonOf(row);
  return <Badge tone={t}>{l}</Badge>;
}

/** "Name · Role" of a contact ("" when none). */
export function contactLabel(k: { name?: string | null; role?: string | null } | null | undefined): string {
  return k ? [k.name, CONTACT_ROLE_LABEL[k.role ?? ""] ?? k.role].filter(Boolean).join(" · ") : "";
}

/** tel: link that dials the stored +91 number (old forms.telLink). Renders nothing without a phone. */
export function TelLink({ phone, label, className }: { phone: string | null | undefined; label?: ReactNode; className?: string }) {
  if (!phone) return null;
  return (
    <a href={`tel:${phone}`} className={cx("vx-tel", className)} aria-label={`Call ${formatPhone(phone)}`}>
      <Icon name="phone" size={16} />
      <span>{label ?? formatPhone(phone)}</span>
    </a>
  );
}
/** Old function name (forms.telLink(ctx, phone, {label, cls})) for ports that call it as a function. */
export function telLink(phone: string | null | undefined, opts: { label?: ReactNode; cls?: string } = {}) {
  return phone ? <TelLink phone={phone} label={opts.label} className={opts.cls} /> : null;
}
