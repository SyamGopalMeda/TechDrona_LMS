/**
 * Target period helpers + saveTargetRow (old forms.js "targets" block). The target DIALOG itself belongs to the
 * Targets screen (old views/targets.js openTargetDialog); targetDialog / setTarget are not ported here.
 */
import { portalApi } from "../lib/api";
import { fmt } from "../lib/fmt";
import { missingEndpoint, validationError } from "./util";

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

/** Monday of the ISO week containing YYYY-MM-DD (null when not a date). */
export function mondayOf(iso: string): string | null {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  const dow = (d.getUTCDay() + 6) % 7;
  return isoDay(new Date(d.getTime() - dow * 86400000));
}

export type PeriodKind = "programme" | "month" | "week";

/** Period as the API spells it: 'programme' | 'month:YYYY-MM' | 'week:YYYY-MM-DD'. */
export function periodKey(kind: PeriodKind | string, month?: string | null, week?: string | null): string {
  if (kind === "month") return `month:${month}`;
  if (kind === "week") return `week:${week}`;
  return "programme";
}

/** Parse a stored period ('programme', 'month:2026-11', '2026-11', 'week:2026-11-02', '2026-11-02'). */
export function parsePeriod(p: string | null | undefined): { kind: "programme" } | { kind: "month"; month: string } | { kind: "week"; week: string } {
  const s = String(p || "programme");
  if (s === "programme" || s === "program") return { kind: "programme" };
  const v = s.includes(":") ? (s.split(":")[1] ?? "") : s;
  if (/^\d{4}-\d{2}$/.test(v)) return { kind: "month", month: v };
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return { kind: "week", week: v };
  return { kind: "programme" };
}

/** "November 2026" / "Week of 2 Nov 2026" / "Programme". */
export function periodLabel(p: string | null | undefined): string {
  const x = parsePeriod(p);
  if (x.kind === "month") {
    const d = new Date(`${x.month}-01T00:00:00Z`);
    return d.toLocaleDateString("en-IN", { month: "long", year: "numeric", timeZone: "UTC" });
  }
  if (x.kind === "week") return `Week of ${fmt.date(x.week)}`;
  return "Programme";
}

export interface TargetRowInput {
  scope_type: string;
  scope_id: string | number;
  period?: string;
  min?: number | null;
  target: number | null;
  max?: number | null;
  course_id?: number | null;
  deadline?: string | null;
  notes?: string | null;
  confirm_programme?: boolean;
}

/**
 * Save one target row. v4 servers: PUT /targets {scope_type, scope_id, period, min, target, max, ...}.
 * Older servers (no PUT): POST /targets for a programme target without min/max; anything else is refused with a clear message.
 */
export async function saveTargetRow(
  { scope_type, scope_id, period = "programme", min = null, target, max = null, course_id = null, deadline = null, notes = null, confirm_programme }: TargetRowInput,
  opts: { idempotencyKey?: string } = {},
): Promise<unknown> {
  const body: Record<string, unknown> = { scope_type, scope_id: String(scope_id ?? ""), period, min, target, max, deadline, notes };
  if (course_id !== null && course_id !== undefined) body.course_id = course_id;
  if (confirm_programme) body.confirm_programme = true;
  try {
    return await portalApi.put("targets", body, opts);
  } catch (e) {
    if (!missingEndpoint(e)) throw e;
  }
  if (period !== "programme" || (min !== null && min !== undefined) || (max !== null && max !== undefined)) {
    throw validationError({
      period: "This server cannot store minimum/maximum or monthly/weekly targets yet. Save a programme target without min/max, or ask the admin to update the server.",
    });
  }
  return portalApi.post("targets", { scope_type, scope_id: String(scope_id ?? ""), course_id, target, deadline, notes });
}
