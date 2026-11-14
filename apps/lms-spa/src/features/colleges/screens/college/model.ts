/**
 * College page data shaping (port of the pure helpers of js/views/college.js): people ↔ branch coverage, the
 * exam state / countdown, the per-person performance figures, display wording for research values and the
 * change-history labels. No React here (tested directly).
 */
import { fmt, today } from "../../lib/fmt";
import type { Branch, Contact, CollegeDetail, Exam, Followup, Person } from "../../lib/types";
import { personBranchIds } from "../../forms/team";
import { unassignedOf } from "../shared/dashboard";

/* ------------------------------------------------------------------ shapes */

/** A rollup / summary as the API returns it (programme figures of a college or branch). */
export interface Roll {
  target?: number | null;
  enrolled?: number | null;
  reached?: number | null;
  remaining?: number | null;
  exceeded_by?: number | null;
  pct?: number | null;
  on_track?: boolean | null;
  pace_status?: string | null;
  diagnosis?: string | null;
  target_source?: string | null;
  deadline?: string | null;
  by_course?: { name: string; price_inr?: number | null; target?: number | null; enrolled?: number | null; revenue_inr?: number | null }[];
  [k: string]: unknown;
}

export type PersonX = Person & {
  _branches: number[];
  reports_to_name?: string | null;
  designation?: string | null;
  enrolled?: number | null;
  target?: number | null;
  reached?: number | null;
};

export type BranchX = Branch & {
  rollup: Roll;
  people?: Person[];
  _people: PersonX[];
  _ambs: PersonX[];
  _activeAmbs: PersonX[];
  _leads: PersonX[];
  _fu: Followup[];
  _nextFu: Followup | null;
  _gap: boolean;
};

export type ContactX = Contact & {
  source_url?: string | null;
  notes?: string | null;
  status_source?: string | null;
  unanswered_streak?: number | null;
  last_call?: { called_at: string; outcome: string } | null;
};
export type CallX = {
  id: number;
  called_at: string;
  caller?: string | null;
  outcome: string;
  notes?: string | null;
  contact_id?: number | null;
  contact_name?: string | null;
  contact_role?: string | null;
  confirms_participation?: number | boolean | null;
  followup_due?: string | null;
  followup_status?: string | null;
};
export type ExamX = Exam & {
  evidence?: string | null;
  confidence?: string | null;
  mid_window?: string | null;
  lab_window?: string | null;
  notice_date?: string | null;
  source_url?: string | null;
  verified_on?: string | null;
  notes?: string | null;
};

/** GET /colleges/:id with the extra blocks the v4 server adds. */
export interface CollegeData {
  college: CollegeDetail["college"];
  rollup: Roll;
  branches: CollegeDetail["branches"];
  people: CollegeDetail["people"];
  exams: ExamX[];
  followups: CollegeDetail["followups"];
  recent_activities: CollegeDetail["recent_activities"];
  recent_enrollments: CollegeDetail["recent_enrollments"];
  audit: CollegeDetail["audit"];
  contacts?: ContactX[];
  calls?: CallX[];
  call_info?: { call_status?: string | null; calls_total?: number | null; contact_counts?: { total?: number; working?: number; non_working?: number; invalid?: number } };
  funnel?: { total?: number; note?: string | null; stages: { stage: string; count: number }[] } | null;
  exam?: { exam_state?: string | null; next_exam?: ExamWin | null; outreach_from?: string | null } | null;
  [k: string]: unknown;
}

export const isActive = (p: { status?: string | null } | null | undefined): boolean => !!p && p.status !== "inactive";

export interface Shaped {
  people: PersonX[];
  branches: BranchX[];
  byId: Map<number, PersonX>;
  unassigned: Set<number>;
  lead: PersonX | null;
}

/** People (detail + /people extras) and branches with their coverage (old college.js shape()). */
export function shape(d: CollegeData, plist: Person[] | null | undefined): Shaped {
  const extra = new Map((plist ?? []).map((p) => [Number(p.id), p]));
  const people: PersonX[] = (d.people ?? []).map((p) => ({ ...(extra.get(Number(p.id)) ?? {}), ...p, _branches: [] }));
  for (const p of plist ?? []) if (!people.some((q) => Number(q.id) === Number(p.id))) people.push({ ...p, _branches: [] });
  const raw = d.branches ?? [];
  const byId = new Map(people.map((p) => [Number(p.id), p]));
  for (const p of people) {
    p._branches = personBranchIds(p, raw);
    if (!p.reports_to_name && p.reports_to) p.reports_to_name = p.lead?.name ?? byId.get(Number(p.reports_to))?.full_name ?? null;
  }
  const unassigned = new Set(unassignedOf(people).map((p) => Number(p.id)));
  // ambassador leads are counted too when the server says they have no valid lead
  for (const p of people) if (p.role === "ambassador_lead" && isActive(p) && p.assignment_status && p.assignment_status !== "assigned") unassigned.add(Number(p.id));
  const branches: BranchX[] = raw.map((b) => {
    const list = people.filter((p) => p._branches.includes(Number(b.id)));
    const ambs = list.filter((p) => p.role === "ambassador");
    const activeAmbs = ambs.filter(isActive);
    const fu = (d.followups ?? []).filter((f) => f.scope_type === "branch" && String(f.scope_id) === String(b.id));
    const nextFu =
      fu
        .filter((f) => f.status === "open" && f.due_date)
        .sort((x, y) => String(x.due_date).localeCompare(String(y.due_date)))[0] ?? null;
    return {
      ...b,
      rollup: (b.rollup ?? {}) as Roll,
      _people: list,
      _ambs: ambs,
      _activeAmbs: activeAmbs,
      _leads: list.filter((p) => p.role === "ambassador_lead" && isActive(p)),
      _fu: fu,
      _nextFu: nextFu,
      _gap: !!b.is_relevant && activeAmbs.length === 0,
    };
  });
  const lead = people.find((p) => p.role === "college_lead" && p.status === "active") ?? people.find((p) => p.role === "college_lead" && isActive(p)) ?? null;
  return { people, branches, byId, unassigned, lead };
}

/* ------------------------------------------------------------------ per-person performance */

export interface PerfRow {
  id: number | string;
  name?: string;
  role?: string;
  person_status?: string;
  target?: number | null;
  min?: number | null;
  max?: number | null;
  actual?: number | null;
  actual_own?: number | null;
  remaining?: number | null;
  exceeded_by?: number | null;
  pct?: number | null;
  status?: string | null;
  expected?: number | null;
  not_credited?: number | null;
  target_source?: string | null;
  below_min?: boolean;
  above_max?: boolean;
  covers?: { total?: number; with_target?: number } | null;
  team?: { size?: number; actual?: number | null; target?: number | null; status?: string | null } | null;
  combined?: { actual?: number | null; target?: number | null } | null;
  [k: string]: unknown;
}
export interface PerfPeriod {
  label?: string;
  days_total?: number;
  days_elapsed?: number;
}
export type PerfRes = PerfRow[] | { rows?: PerfRow[]; items?: PerfRow[]; period?: PerfPeriod } | null | undefined;
export const perfRows = (res: PerfRes): PerfRow[] => (!res ? [] : Array.isArray(res) ? res : (res.rows ?? res.items ?? []));
export const perfPeriod = (res: PerfRes): PerfPeriod | null => (res && !Array.isArray(res) ? (res.period ?? null) : null);

export interface PersonPerf {
  target: number | null;
  min?: number | null;
  max?: number | null;
  actual: number | null;
  remaining?: number | null;
  exceeded_by?: number | null;
  pct?: number | null;
  status: string | null;
  team?: PerfRow["team"];
  combined?: PerfRow["combined"];
}

/** Own target / actual of a person: /api/performance row (v4) → people target_summary (v4) → v3 fields. */
export function personPerf(p: PersonX, perfById?: Map<number, PerfRow> | null): PersonPerf {
  const r = perfById?.get(Number(p.id));
  if (r) return { target: r.target ?? null, min: r.min, max: r.max, actual: r.actual ?? r.actual_own ?? null, remaining: r.remaining, exceeded_by: r.exceeded_by, pct: r.pct, status: r.status ?? null, team: r.team, combined: r.combined };
  const ts = p.target_summary;
  if (ts) return { target: ts.target, min: ts.min, max: ts.max, actual: p.actual_own ?? p.enrolled ?? 0, remaining: ts.remaining, exceeded_by: ts.exceeded_by, pct: ts.pct, status: ts.status };
  const pct = typeof p.pct === "number" ? p.pct * 100 : null;
  return { target: p.target ?? null, actual: p.enrolled ?? 0, remaining: typeof p.remaining === "number" ? p.remaining : null, pct, status: null };
}

/* ------------------------------------------------------------------ exams */

export interface ExamWin {
  semester?: string | null;
  kind?: string | null;
  start: string | null;
  end: string | null;
  approx?: boolean;
}

const ISO_RE = /(\d{4})-(\d{2})-(\d{2})|(\d{1,2})[./-](\d{1,2})[./-](\d{4})/g;
export function datesIn(text: string | null | undefined): string[] {
  if (!text) return [];
  const out: string[] = [];
  for (const m of String(text).matchAll(ISO_RE)) {
    if (m[1]) out.push(`${m[1]}-${m[2]}-${m[3]}`);
    else out.push(`${m[6]}-${String(m[5]).padStart(2, "0")}-${String(m[4]).padStart(2, "0")}`);
  }
  return out.sort();
}
export function addDay(iso: string, n = 1): string {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
}
export function examWindows(rows: ExamX[] | null | undefined): ExamWin[] {
  const out: ExamWin[] = [];
  for (const r of rows ?? []) {
    const s = datesIn(r.endsem_start);
    const e = datesIn(r.endsem_end);
    const approx = /before|after|inferred|approx|tentative|~/i.test(`${r.endsem_start ?? ""} ${r.endsem_end ?? ""}`);
    if (s.length || e.length) out.push({ semester: r.semester, kind: "End-sem exams", start: s[0] ?? null, end: e[e.length - 1] ?? s[s.length - 1] ?? null, approx });
    for (const [k, label] of [
      ["mid_window", "Mid exams"],
      ["lab_window", "Lab exams"],
    ] as const) {
      const txt = r[k];
      const ds = datesIn(txt);
      if (ds.length) out.push({ semester: r.semester, kind: label, start: ds[0] ?? null, end: ds[ds.length - 1] ?? null, approx: /inferred|approx|tentative/i.test(String(txt)) });
    }
  }
  return out;
}

export interface ExamInfo {
  state: string | null;
  current: ExamWin | null;
  next: ExamWin | null;
  outreachFrom: string | null;
  wins: ExamWin[];
}

export function examInfo(d: CollegeData): ExamInfo {
  const r = d.rollup ?? {};
  const c = d.college ?? ({} as CollegeData["college"]);
  const t = today();
  const wins = examWindows(d.exams);
  const str = (v: unknown) => (typeof v === "string" && v ? v : null);
  let state = str(d.exam?.exam_state) ?? str(d.exam_state) ?? str(c.exam_state) ?? str(r.exam_state);
  const rExams = r.exams as Record<string, number> | undefined;
  if (!state && rExams) state = ["in_exams", "exams_soon", "clear", "unknown"].find((k) => (rExams[k] ?? 0) > 0) ?? null;
  let current: ExamWin | null =
    wins.filter((w) => !w.approx && w.start && w.end && w.start <= t && t <= w.end).sort((a, b) => String(a.end).localeCompare(String(b.end)))[0] ?? null;
  let next = (d.exam?.next_exam ?? (d.next_exam as ExamWin | undefined) ?? (c.next_exam as ExamWin | null) ?? (r.next_exam as ExamWin | undefined) ?? null) as ExamWin | null;
  if (next && next.start && next.start <= t && t <= (next.end || next.start)) {
    current = current ?? next;
    next = null;
  }
  if (!next) next = wins.filter((w) => !w.approx && w.start && w.start > (current?.end || t)).sort((a, b) => String(a.start).localeCompare(String(b.start)))[0] ?? null;
  let outreachFrom = str(d.exam?.outreach_from) ?? str(d.outreach_from) ?? str(c.outreach_from) ?? str(r.outreach_from);
  if (!outreachFrom && !d.exam) {
    const ends = wins
      .filter((w) => !w.approx && w.semester === "4-1" && w.kind === "End-sem exams" && w.end)
      .map((w) => String(w.end))
      .sort();
    const last = ends[ends.length - 1];
    if (last) outreachFrom = addDay(last);
  }
  if (!state) {
    const allUnknown = (d.exams ?? []).every((x) => /unverified|no current/i.test(`${x.status} ${x.evidence}`));
    state = current ? "in_exams" : next?.start && (Date.parse(next.start) - Date.parse(t)) / 86_400_000 <= 14 ? "exams_soon" : allUnknown ? "unknown" : "clear";
  }
  return { state, current, next, outreachFrom, wins };
}

function kindLabel(k: string | null | undefined): string {
  const s = String(k ?? "").toLowerCase();
  return /end/.test(s) ? "end-sem exams" : /mid/.test(s) ? "mid exams" : /lab/.test(s) ? "lab exams" : "exams";
}

/** Lines of the exam countdown (first = main line). Empty → the caller shows the "nothing known" wording. */
export function examCountdown(info: ExamInfo): string[] {
  const t = today();
  const lines: string[] = [];
  if (info.current?.end) {
    const n = Math.round((Date.parse(info.current.end) - Date.parse(t)) / 86_400_000);
    lines.push(`${info.current.semester} ${kindLabel(info.current.kind)} running — ${n <= 0 ? "ends today" : `ends ${fmt.date(info.current.end)} (in ${fmt.plural(n, "day")})`}`);
  }
  if (info.next?.start) {
    const n = Math.round((Date.parse(info.next.start) - Date.parse(t)) / 86_400_000);
    if (n > 0) lines.push(`Next: ${info.next.semester ? `${info.next.semester} ` : ""}${kindLabel(info.next.kind)} start ${fmt.date(info.next.start)} — in ${fmt.plural(n, "day")}${info.next.approx ? " (approx.)" : ""}`);
  }
  if (info.outreachFrom) {
    lines.push(
      info.outreachFrom > t
        ? `Good time for outreach from ${fmt.date(info.outreachFrom)} (${fmt.days(info.outreachFrom)})`
        : `4-1 exams over since ${fmt.date(addDay(info.outreachFrom, -1))} — good time for outreach`,
    );
  }
  return lines;
}

/* ------------------------------------------------------------------ wording for research values (display only) */

export const autonomyText = (v: unknown): string | null =>
  v === null || v === undefined || v === ""
    ? null
    : v === 1 || v === true || /^yes$/i.test(String(v))
      ? "Autonomous"
      : v === 0 || v === false || /^no$/i.test(String(v))
        ? "Not autonomous"
        : String(v);

const OWNERSHIP_TEXT: Record<string, string> = {
  "pvt autonomous": "Private college (autonomous)",
  "pvt affiliated": "Private college (affiliated)",
  "private self-financing": "Private college (self-financing)",
  "state pvt univ": "Private university",
  "deemed (pvt)": "Deemed university (private)",
  "govt – state univ/constituent": "Government (state university or its college)",
  "govt – national": "Government (national institute)",
};
export function ownershipText(v: string | null | undefined): string | null {
  return v ? (OWNERSHIP_TEXT[String(v).trim().toLowerCase()] ?? String(v)) : null;
}
/** "A+; 3.49; 2nd cycle … (College site)" → "A+". */
export function naacGrade(v: unknown): string | null {
  const s = String(v ?? "").trim();
  if (!s || s === "—") return null;
  const g = (s.split(";")[0] ?? "").replace(/\s*\((aggregator|college site|official)\)\s*$/i, "").trim();
  return g || null;
}
/** "Not in 2025 Engg top 300" → "Not ranked"; "Engg 201-300 (official)" → "Engineering 201-300". */
export function nirfText(v: unknown): string | null {
  const s = String(v ?? "").trim();
  if (!s || s === "—") return null;
  if (/not inherited|\bparent\)/i.test(s)) return "Not ranked (only the parent university is)";
  if (/^not\b/i.test(s)) return "Not ranked";
  return s
    .replace(/\bEngg\b/g, "Engineering")
    .replace(/\bUniv\b/g, "University")
    .replace(/\s*\((official|aggregator)\)/gi, "")
    .trim();
}

/* ------------------------------------------------------------------ change history */

export const ENTITY_LABEL: Record<string, string> = {
  college: "College", branch: "Branch", person: "Person", target: "Target", enrollment: "Enrollment", activity: "Activity", followup: "Follow-up", exam: "Exam",
  course: "Course", setting: "Setting", contact: "Contact", call: "Call", colleges: "College", branches: "Branch", people: "Person", targets: "Target",
  enrollments: "Enrollment", activities: "Activity", followups: "Follow-up", exams: "Exam", courses: "Course", settings: "Setting",
};
const FIELD_LABEL: Record<string, string> = {
  op_status: "operating status", op_status_note: "why this status", op_status_source: "status evidence link", op_2025_26: "admitting 2025-26", op_2026_27: "admitting 2026-27",
  intake_per_year: "seats / year", intake_basis: "seats basis", intake_source: "seats source", intake_year: "seats year", strength_total: "students, all 4 years",
  strength_basis: "students basis", final_year: "final-year students", final_year_basis: "final-year basis", eligible_estimate: "likely prospects",
  eligible_basis: "likely prospects basis", is_relevant: "target branch", category: "branch group", ownership: "type of institution", affiliation: "affiliated university",
  autonomous: "autonomous", tier: "research tier", phone: "office phone", email: "office email", sno: "master list no.", geo_precision: "map pin",
  total_intake: "seats per year (all branches)", notes: "notes", reports_to: "reports to", full_name: "name", due_date: "due date", scope_type: "scope", scope_id: "scope id",
  naac: "NAAC grade", nirf: "NIRF ranking", verified_fields: "verification", district_id: "district", city_id: "city",
};
export const fieldLabel = (k: string): string => FIELD_LABEL[k] ?? k.replace(/_basis$/, " basis").replace(/_/g, " ");
export const SKIP_FIELDS = new Set(["updated_at", "updated_by", "created_at", "created_by"]);
export function parseJ(v: unknown): Record<string, unknown> | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "object") return v as Record<string, unknown>;
  try {
    const o: unknown = JSON.parse(String(v));
    return o && typeof o === "object" ? (o as Record<string, unknown>) : { value: o };
  } catch {
    return { value: v };
  }
}
export function shortVal(v: unknown): string {
  if (v === null || v === undefined || v === "") return "∅";
  const s = typeof v === "object" ? JSON.stringify(v) : String(v);
  return s.length > 80 ? `${s.slice(0, 77)}…` : s;
}

/* ------------------------------------------------------------------ misc */

export const TABS = ["overview", "team", "calls", "performance", "branches", "exams", "activity"] as const;
export type TabId = (typeof TABS)[number];
export const TAB_ALIAS: Record<string, TabId> = {
  enrollment: "performance", enrollments: "performance", targets: "performance", followups: "activity", history: "activity", contacts: "calls",
};
export function resolveTab(raw: string | undefined): TabId {
  const t = raw ? (TAB_ALIAS[raw] ?? raw) : "overview";
  return (TABS as readonly string[]).includes(t) ? (t as TabId) : "overview";
}

/** Programme / this month / this week period keys (performance tab). */
export function periods(): [string, string][] {
  const t = today();
  const dt = new Date(Date.parse(`${t}T00:00:00Z`));
  const mon = new Date(dt);
  mon.setUTCDate(dt.getUTCDate() - ((dt.getUTCDay() + 6) % 7));
  return [
    ["programme", "Programme to date"],
    [`month:${t.slice(0, 7)}`, "This month"],
    [`week:${mon.toISOString().slice(0, 10)}`, "This week"],
  ];
}

/** View preferences kept per browser (old localStorage td.college.ui2). */
export interface CollegeUiPrefs {
  relevantOnly: boolean;
  sort: string;
  branchView: "cards" | "table";
  period: string;
}
const PREFS_KEY = "td.college.ui2";
export function loadPrefs(): CollegeUiPrefs {
  const base: CollegeUiPrefs = { relevantOnly: false, sort: "relevance", branchView: "cards", period: "programme" };
  try {
    return { ...base, ...(JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") as Partial<CollegeUiPrefs>) };
  } catch {
    return base;
  }
}
export function savePrefs(p: CollegeUiPrefs): void {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* ignore */
  }
}

export const collegeLabel = (c: { short_name?: string | null; name?: string | null; id?: string }): string => c.short_name || c.name || c.id || "";
