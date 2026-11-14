/**
 * Formatting helpers: a port of `fmt`, `today`, `daysUntil` and `debounce` from the old portal's
 * js/ui/h.js. Same rules (en-IN digit grouping, fixed month names, THE one percentage rule).
 */

const nfIN = new Intl.NumberFormat("en-IN");
const DAY = 86_400_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

type Num = number | null | undefined;

/** Today's date as YYYY-MM-DD in local time (override with ?today=YYYY-MM-DD for testing, as before). */
export function today(): string {
  try {
    const o = new URLSearchParams(window.location.search).get("today");
    if (o && /^\d{4}-\d{2}-\d{2}$/.test(o)) return o;
  } catch {
    /* no window */
  }
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Whole days from today to `date` (negative = past). null if no date. */
export function daysUntil(date: string | null | undefined): number | null {
  if (!date) return null;
  const a = Date.parse(`${today()}T00:00:00Z`);
  const b = Date.parse(`${String(date).slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(b)) return null;
  return Math.round((b - a) / DAY);
}

const isMissing = (n: unknown): boolean => n === null || n === undefined || (typeof n === "number" && Number.isNaN(n));

export const fmt = {
  /** Indian digit grouping; null → "—" */
  num: (n: Num): string => (isMissing(n) ? "—" : nfIN.format(Math.round(n as number))),
  inr: (n: Num): string => (isMissing(n) ? "—" : `₹${nfIN.format(Math.round(n as number))}`),
  /** x is a fraction (0.42 → "42%") */
  pct: (x: Num, digits = 0): string => (isMissing(x) ? "—" : `${((x as number) * 100).toFixed(digits)}%`),
  /** "9 Nov 2026" (fixed month names: en-IN renders September as "Sept") */
  date: (d: string | null | undefined): string => {
    if (!d) return "—";
    const t = Date.parse(`${String(d).slice(0, 10)}T00:00:00Z`);
    if (Number.isNaN(t)) return String(d);
    const x = new Date(t);
    return `${x.getUTCDate()} ${MONTHS[x.getUTCMonth()]} ${x.getUTCFullYear()}`;
  },
  /** relative days label: "in 5 days", "today", "3 days ago" */
  days: (d: string | null | undefined): string => {
    const n = daysUntil(d);
    if (n === null) return "—";
    if (n === 0) return "today";
    if (n === 1) return "tomorrow";
    if (n === -1) return "yesterday";
    return n > 0 ? `in ${n} days` : `${-n} days ago`;
  },
  plural: (n: Num, one: string, many?: string): string => `${fmt.num(n)} ${Number(n) === 1 ? one : many || `${one}s`}`,
  /** the word only: word(1,'district') → 'district', word(3,'district') → 'districts' */
  word: (n: Num, one: string, many?: string): string => (Number(n) === 1 ? one : many || `${one}s`),
  /**
   * THE one percentage rule for every page (TG-13 / F11): input is a PERCENT number (4.75 → "4.8%").
   * 0 → "0%"; below 10 % one decimal; from 10 % whole numbers; null / NaN / Infinity → "—".
   */
  pctPts: (p: number | string | null | undefined): string => {
    if (p === null || p === undefined || p === "" || !Number.isFinite(Number(p))) return "—";
    const v = Number(p);
    if (v === 0) return "0%";
    return `${Math.abs(v) < 10 ? (Math.round(v * 10) / 10).toFixed(1) : String(Math.round(v))}%`;
  },
  /** same rule for a FRACTION (0.0475 → "4.8%") */
  pctOf: (x: number | string | null | undefined): string =>
    x === null || x === undefined || x === "" || !Number.isFinite(Number(x)) ? "—" : fmt.pctPts(Number(x) * 100),
  /** actual / target as a % — "—" when there is no positive target */
  pctRatio: (a: Num, t: Num): string => (Number(t) > 0 && Number.isFinite(Number(a)) ? fmt.pctPts((Number(a) / Number(t)) * 100) : "—"),
  /** "min 2 · max 4" / "max 4" / "" */
  range: (min: Num | string, max: Num | string): string =>
    [
      min !== null && min !== undefined && min !== "" ? `min ${fmt.num(Number(min))}` : null,
      max !== null && max !== undefined && max !== "" ? `max ${fmt.num(Number(max))}` : null,
    ]
      .filter(Boolean)
      .join(" · "),
};

export function debounce<A extends unknown[]>(fn: (...a: A) => void, ms = 250): ((...a: A) => void) & { cancel: () => void } {
  let t: ReturnType<typeof setTimeout> | undefined;
  const d = (...a: A) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
  d.cancel = () => clearTimeout(t);
  return d;
}

/** "Guntur" from "guntur", "West Godavari" from "west-godavari". */
export function prettySlug(s: string | null | undefined): string {
  return String(s ?? "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

/** Two initials for an avatar ("Ravi Kumar" → "RK"), "?" when empty. */
export function initials(name: string | null | undefined): string {
  return (
    (name ?? "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((x) => x[0]!.toUpperCase())
      .join("") || "?"
  );
}
