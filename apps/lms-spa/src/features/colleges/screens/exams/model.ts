/**
 * Exam windows, trust and countdowns (port of the pure helpers of js/views/exams.js). The window parsing mirrors
 * server/rollup.js examWindows() so the timeline matches the server's status counts.
 */
import { daysUntil } from "../../lib/fmt";
import type { ExamState } from "../../lib/types";
import type { Tone } from "../../ui";

export const DAY = 86_400_000;

/** One exam row of GET /api/exams (per college, per semester). */
export interface ExamRecord {
  id?: number;
  college_id?: string;
  semester: "3-1" | "4-1" | string;
  status: string | null;
  exam_body?: string | null;
  endsem_start?: string | null;
  endsem_end?: string | null;
  mid_window?: string | null;
  lab_window?: string | null;
  source_url?: string | null;
  evidence?: string | null;
  confidence?: string | null;
  notice_date?: string | null;
  verified_on?: string | null;
  notes?: string | null;
  updated_at?: string | null;
  updated_by?: string | null;
  /** client marker: no row for this semester yet */
  _missing?: boolean;
  [k: string]: unknown;
}

/** One college of GET /api/exams. */
export interface ExamCollege {
  college_id: string;
  name: string;
  short_name?: string | null;
  district_id: string;
  exam_state: ExamState | null;
  outreach_from?: string | null;
  rows?: ExamRecord[];
  [k: string]: unknown;
}

export type Trust = "confirmed" | "planned" | "conflict";
export interface ExamWindow {
  kind: "endsem" | "mid" | "lab";
  start: string;
  end: string;
  trust: Trust;
  openEnded?: boolean;
  text: string;
}

export const isoOnly = (v: unknown): string | null => (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v.trim()) ? v.trim() : null);
export const addDays = (iso: string, n: number): string => new Date(Date.parse(`${iso}T00:00:00Z`) + n * DAY).toISOString().slice(0, 10);
export const dayIndex = (iso: string, from: string): number => Math.round((Date.parse(`${iso}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY);
export const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

const RANGE_RE = /(\d{4}-\d{2}-\d{2})\s*(?:to|–|—|-|until|till)\s*(\d{4}-\d{2}-\d{2})/gi;

/** Date ranges written in a free-text window ("Mid-II 2026-11-09 to 2026-11-14"). */
export function textWindows(txt: string | null | undefined, row?: Partial<ExamRecord>): { start: string; end: string; openEnded?: boolean }[] {
  const out: { start: string; end: string; openEnded?: boolean }[] = [];
  if (!txt) return out;
  let found = false;
  for (const m of txt.matchAll(RANGE_RE)) {
    found = true;
    const a = m[1]!;
    const b = m[2]!;
    out.push(a <= b ? { start: a, end: b } : { start: b, end: a });
  }
  if (!found) {
    const from = /\bfrom\s+(\d{4}-\d{2}-\d{2})/i.exec(txt)?.[1];
    const ends = /\brunning\b.*?\bends\s+(\d{4}-\d{2}-\d{2})/i.exec(txt)?.[1];
    if (ends) {
      const start =
        [isoOnly(row?.notice_date), isoOnly(row?.verified_on)]
          .filter((d): d is string => !!d && d <= ends)
          .sort()[0] ?? ends;
      out.push({ start, end: ends });
    } else if (from) out.push({ start: from, end: from, openEnded: true });
  }
  return out;
}

/** How trustworthy a row's dates are. */
export function trust(r: ExamRecord, text = ""): Trust {
  const ev = String(r.evidence ?? "");
  if (/conflict/i.test(ev)) return "conflict";
  if (r.status === "Unverified" || /unverified|planned|tentative|inferred/i.test(`${ev} ${text}`)) return "planned";
  return "confirmed";
}

export function windowsOf(r: ExamRecord): ExamWindow[] {
  const out: ExamWindow[] = [];
  const es = isoOnly(r.endsem_start);
  const ee = isoOnly(r.endsem_end);
  if (es || ee) {
    const start = (es || ee)!;
    const end = ee && ee >= start ? ee : start;
    out.push({ kind: "endsem", start, end, trust: trust(r), openEnded: !ee, text: ee ? "End-sem exams" : "End-sem exams start (end date not published)" });
  }
  for (const w of textWindows(r.mid_window, r)) out.push({ kind: "mid", ...w, trust: trust(r, r.mid_window ?? ""), text: `Mid exams — ${r.mid_window}` });
  for (const w of textWindows(r.lab_window, r)) out.push({ kind: "lab", ...w, trust: trust(r, r.lab_window ?? ""), text: `Labs / practicals — ${r.lab_window}` });
  return out;
}

export const isPending = (r: ExamRecord | null | undefined): boolean => !r || !!r._missing || (r.status === "Unverified" && !windowsOf(r).length);

/** 4-1 end-sem exams are over: final-year students are free for outreach. */
export function fourOneDone(c: ExamCollege): boolean {
  const r = (c.rows ?? []).find((x) => x.semester === "4-1");
  if (!r || r.status === "Unverified") return false;
  if (r.status === "Completed") return true;
  const e = isoOnly(r.endsem_end);
  return !!e && (daysUntil(e) ?? 0) < 0;
}

export function countdown(r: ExamRecord | null | undefined): { text: string; tone: Tone } {
  if (!r || r._missing) return { text: "Not tracked yet", tone: "neutral" };
  const s = isoOnly(r.endsem_start);
  const e = isoOnly(r.endsem_end);
  const ds = s ? daysUntil(s) : null;
  const de = e ? daysUntil(e) : null;
  if (ds !== null && ds > 0) return { text: `starts in ${plural(ds, "day")}`, tone: ds <= 14 ? "warn" : "info" };
  if (ds === 0) return { text: "starts today", tone: "bad" };
  if (de !== null && de > 0) return { text: `ends in ${plural(de, "day")}`, tone: "bad" };
  if (de === 0) return { text: "ends today", tone: "bad" };
  if (de !== null && de < 0) return { text: `ended ${plural(-de, "day")} ago`, tone: "good" };
  if (r.status === "Completed") return { text: "completed", tone: "good" };
  if (r.status === "No Current Exams Found") return { text: "no exams announced", tone: "neutral" };
  return { text: "dates not published", tone: "neutral" };
}

/** The row of one semester, or a placeholder marked `_missing`. */
export function semRow(c: ExamCollege, sem: string): ExamRecord {
  return (c.rows ?? []).find((r) => r.semester === sem) ?? { semester: sem, status: "Unverified", _missing: true };
}

export const EXAM_STATE: Record<ExamState, { label: string; short: string; tone: Tone; help: string }> = {
  in_exams: { label: "In exams now", short: "In exams", tone: "bad", help: "An end-sem or mid exam window includes today." },
  exams_soon: { label: "Exams within 14 days", short: "Exams soon", tone: "warn", help: "An exam starts in the next 14 days." },
  clear: { label: "Clear", short: "Clear", tone: "good", help: "No exam today or in the next 14 days." },
  unknown: { label: "Dates unknown", short: "Unknown", tone: "neutral", help: "Neither semester has a confirmed date yet." },
};
export const isExamState = (v: unknown): v is ExamState => typeof v === "string" && v in EXAM_STATE;
