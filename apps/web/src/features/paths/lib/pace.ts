import type { DayKey, Pace, PaceMode, PerDay } from "./types";

/** Study-pace helpers for the Allocate dialog. The api recomputes the plan server-side
 * (`/paths/{id}/allocation-preview`); these give the instant local preview and formatting. */

export const DAY_KEYS: readonly DayKey[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const DAY_LABELS: Record<DayKey, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};
const WEEKEND: ReadonlySet<DayKey> = new Set(["sat", "sun"]);

export const PACE_MODES: { value: PaceMode; label: string }[] = [
  { value: "every_day", label: "Every day" },
  { value: "weekdays", label: "Weekdays" },
  { value: "weekends", label: "Weekends" },
  { value: "weekdays_weekends", label: "Weekdays + weekends" },
  { value: "custom", label: "Custom" },
];

export function isWeekend(d: DayKey): boolean {
  return WEEKEND.has(d);
}

function clampHours(v: number | undefined): number {
  if (typeof v !== "number" || !Number.isFinite(v) || v < 0) return 0;
  return Math.min(24, Math.round(v * 4) / 4);
}

/** Hours studied on each weekday for a pace setting. */
export function perDayFromPace(pace: Pace): PerDay {
  const h = clampHours(pace.hours_per_day);
  const we = clampHours(pace.weekend_hours ?? pace.hours_per_day);
  const out = {} as PerDay;
  for (const d of DAY_KEYS) {
    const weekend = isWeekend(d);
    switch (pace.mode) {
      case "every_day":
        out[d] = h;
        break;
      case "weekdays":
        out[d] = weekend ? 0 : h;
        break;
      case "weekends":
        out[d] = weekend ? h : 0;
        break;
      case "weekdays_weekends":
        out[d] = weekend ? we : h;
        break;
      case "custom":
        out[d] = clampHours(pace.per_day?.[d]);
        break;
    }
  }
  return out;
}

export function weeklyHours(perDay: PerDay): number {
  return Math.round(DAY_KEYS.reduce((s, d) => s + (perDay[d] ?? 0), 0) * 100) / 100;
}

/** Parse YYYY-MM-DD as a UTC date (no local-timezone drift). */
export function parseIsoDate(s: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return null;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return Number.isNaN(d.getTime()) ? null : d;
}

export function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function todayIso(now: Date = new Date()): string {
  const local = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  return toIsoDate(local);
}

/** Day of week key of a UTC date. */
function dayKeyOf(d: Date): DayKey {
  return DAY_KEYS[(d.getUTCDay() + 6) % 7]!;
}

/**
 * Local estimate of the plan: walk the calendar from the start date accumulating each day's
 * hours until the path's total is covered. Same rule as the server; the server value wins.
 */
export function estimateFinish(
  startIso: string,
  totalHours: number,
  perDay: PerDay,
): { finishDate: string; days: number } | null {
  const start = parseIsoDate(startIso);
  if (!start || weeklyHours(perDay) <= 0) return null;
  if (totalHours <= 0) return { finishDate: startIso, days: 0 };
  let acc = 0;
  const d = new Date(start);
  for (let i = 0; i < 3660; i++) {
    acc += perDay[dayKeyOf(d)] ?? 0;
    if (acc + 1e-9 >= totalHours) return { finishDate: toIsoDate(d), days: i + 1 };
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return null;
}

/** "14 Nov 2026" */
export function formatPlanDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = parseIsoDate(iso.slice(0, 10));
  if (!d) return "—";
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(d);
}

export function formatHours(h: number | null | undefined): string {
  if (typeof h !== "number" || !Number.isFinite(h)) return "—";
  const r = Math.round(h * 10) / 10;
  return `${r}h`;
}

/** "14h/week · path is 20h · finishes in ≈ 10 days (14 Nov 2026)" */
export function planSummary(weekly: number, total: number, finishDate: string | null, days: number | null): string {
  const head = `${formatHours(weekly)}/week · path is ${formatHours(total)}`;
  if (!finishDate || days === null) return `${head} · add study hours to see a finish date`;
  return `${head} · finishes in ≈ ${days} ${days === 1 ? "day" : "days"} (${formatPlanDate(finishDate)})`;
}
