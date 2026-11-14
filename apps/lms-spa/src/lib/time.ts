/**
 * Calendar-day and `<input type="datetime-local">` helpers. India time (Asia/Kolkata, no DST) is
 * the zone batch, course and payment dates are planned in.
 */

/** The India-time calendar date (YYYY-MM-DD) of `now` (default: today). */
export function todayIST(now: Date | number = Date.now()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

/** Start of an IST calendar day (YYYY-MM-DD) as an ISO timestamp, for APIs that take datetimes. */
export const istDayStart = (d: string) => `${d}T00:00:00+05:30`;

/** End of an IST calendar day (YYYY-MM-DD), for "valid until" dates chosen by day. */
export const istDayEnd = (d: string) => `${d}T23:59:59+05:30`;

/** A `datetime-local` value typed as India time ("2026-11-12T09:30") → ISO, whatever the browser's zone. */
export function istLocalToIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(`${local.length === 16 ? `${local}:00` : local}+05:30`);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** RFC 3339 → `<input type="datetime-local">` value in the browser's local time. */
export function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** `<input type="datetime-local">` value (browser local time) → RFC 3339 UTC, or null when empty/invalid. */
export function localInputToIso(v: string): string | null {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
