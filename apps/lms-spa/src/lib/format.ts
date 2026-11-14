/**
 * Shared date and time-left formatting (design-system §8). Dates are shown in India time
 * (Asia/Kolkata), the product default. Pure functions; no DOM.
 */

const TZ = "Asia/Kolkata";

/** `date` fields are IST calendar days (YYYY-MM-DD): anchor them at IST midnight. */
function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T00:00:00+05:30`) : new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** `3 Nov 2026` (IST); "—" when empty or invalid. */
export function formatDate(iso: string | null | undefined): string {
  const d = parse(iso);
  if (!d) return "—";
  return new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "numeric", month: "short", year: "numeric" }).format(d);
}

/**
 * `3 Nov, 10:15 IST` (consoles, account screens), or with `{ year: true }` `3 Nov 2026, 10:15 IST`
 * (catalog, commerce, learning: a bare `YYYY-MM-DD` is read as IST midnight). "—" when empty or invalid.
 */
export function formatDateTime(iso: string | null | undefined, opts: { year?: boolean } = {}): string {
  if (opts.year) {
    const d = parse(iso);
    if (!d) return "—";
    const time = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false }).format(d);
    return `${formatDate(iso)}, ${time} IST`;
  }
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: TZ }).format(d)} IST`;
}

/** "now", "2 h ago", "3 d ago" (callers add "active" etc.). */
export function formatRelative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const mins = Math.round((now - t) / 60000);
  if (mins < 5) return "now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

/** "in 52 h", "3 h ago", "in 12 days", relative to now (approval expiry, SLA due times). */
export function formatTimeUntil(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const diffH = (t - now) / 3_600_000;
  const abs = Math.abs(diffH);
  const days = Math.round(abs / 24);
  const text = abs < 1 ? `${Math.max(1, Math.round(abs * 60))} min` : abs < 48 ? `${Math.round(abs)} h` : `${days} ${days === 1 ? "day" : "days"}`;
  return diffH >= 0 ? `in ${text}` : `${text} ago`;
}

/**
 * Time left, from seconds:
 * - `"clock"` (default, test timers, design-system §5.11): `HH:MM:SS` when ≥ 1 h, else `MM:SS`;
 *   rounds up so 00:00 means time is over;
 * - `"short"` (retry / resend waits): `M:SS`, rounded down;
 * - `"compact"` (assignment deadlines): "2d 4h", "23h 54m", "5m 12s"; "Time's up" at 0.
 */
export function formatCountdown(seconds: number, style: "clock" | "short" | "compact" = "clock"): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  if (style === "short") {
    const s = Math.max(0, Math.floor(seconds));
    return `${Math.floor(s / 60)}:${pad(s % 60)}`;
  }
  if (style === "compact") {
    if (seconds <= 0) return "Time's up";
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m ${s}s`;
  }
  const total = Math.max(0, Math.ceil(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}
