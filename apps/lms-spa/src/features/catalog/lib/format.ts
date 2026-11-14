/**
 * Display formatting (design-system §8): money `₹1,499` (Indian grouping, paise → rupees),
 * durations, percentages. Pure functions; safe in server and client components. Dates:
 * `@/lib/format`.
 */

export function formatMoney(paise: number | null | undefined): string {
  if (paise === null || paise === undefined || !Number.isFinite(paise)) return "—";
  const whole = paise % 100 === 0;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 2,
  }).format(paise / 100);
}

export function formatDuration(minutes: number | null | undefined): string | null {
  if (!minutes || minutes <= 0) return null;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (h === 0) return `${m} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${Math.round(Math.max(0, Math.min(100, value)))}%`;
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "";
  const s = value.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** BCP-47 code → English language name ("en" → "English", "hi" → "Hindi"); unknown codes pass through. */
export function languageName(code: string | null | undefined): string | null {
  if (!code) return null;
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}
