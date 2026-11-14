/**
 * Small helpers shared by the portal dialogs (ports of the plumbing at the top of the old js/views/forms.js).
 */
import { PortalApiError, portalApi } from "../lib/api";
import { today } from "../lib/fmt";

export { today };

/** Number or null (blank / not a number → null). */
export const num = (v: unknown): number | null => (v === "" || v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v));
/** Trimmed string or null when blank. */
export const str = (v: unknown): string | null => (v === undefined || v === null ? null : String(v).trim() || null);
/** Comma list / array → numbers. */
export const arr = (v: unknown): number[] =>
  (Array.isArray(v) ? v : v === "" || v === null || v === undefined ? [] : String(v).split(","))
    .map(Number)
    .filter((x) => !Number.isNaN(x));
/** Whole number ≥ 0, null when blank, NaN when invalid. */
export function wholeOrNull(v: unknown): number | null {
  const n = num(v);
  if (n === null) return null;
  return Number.isInteger(n) && n >= 0 ? n : Number.NaN;
}

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/** A 400-style error with field messages: dialogs show them under the matching inputs (never toasted). */
export function validationError(fields: Record<string, string>): PortalApiError {
  return new PortalApiError(400, Object.values(fields)[0] ?? "Please fix the highlighted fields.", fields);
}

const DAY = 86_400_000;
/** YYYY-MM-DD + n days. */
export function addDays(iso: string, n: number): string {
  const t = Date.parse(`${String(iso).slice(0, 10)}T00:00:00Z`);
  return new Date(t + n * DAY).toISOString().slice(0, 10);
}

/** Rows of a list answer whatever its shape (plain array, {items}, {rows}). */
export function rowsOf<T = Record<string, unknown>>(x: unknown): T[] {
  if (Array.isArray(x)) return x as T[];
  const o = x as { items?: unknown; rows?: unknown } | null;
  if (o && Array.isArray(o.items)) return o.items as T[];
  if (o && Array.isArray(o.rows)) return o.rows as T[];
  return [];
}

/** GET a list; when the server pages it ({items,total}), fetch everything in one go (capped at 5000). */
export async function listAll<T = Record<string, unknown>>(path: string, query: Record<string, string | number | undefined> = {}, scoped = false): Promise<T[]> {
  const r = await portalApi.get<unknown>(path, { query, scoped });
  const o = r as { items?: unknown[]; total?: number } | null;
  if (o && !Array.isArray(o) && Array.isArray(o.items) && Number(o.total) > o.items.length) {
    return rowsOf<T>(await portalApi.get(path, { query: { ...query, page: 1, page_size: Math.min(Number(o.total), 5000) }, scoped }));
  }
  return rowsOf<T>(r);
}

/** 404 / 405: the server has no such endpoint (older server) → callers fall back. */
export const missingEndpoint = (e: unknown): boolean => e instanceof PortalApiError && (e.status === 404 || e.status === 405);

/** Only http(s) links are ever rendered as <a href> (BE-12: a stored "javascript:" URL must never become a link). */
export function safeUrl(u: unknown): string | null {
  if (typeof u !== "string" || !u.trim()) return null;
  try {
    const x = new URL(u.trim());
    return x.protocol === "http:" || x.protocol === "https:" ? x.href : null;
  } catch {
    return null;
  }
}

/** Error message of anything thrown. */
export const errMsg = (e: unknown, fallback = "Something went wrong"): string => (e instanceof Error && e.message ? e.message : fallback);

/** Branch picker options: "CSE — Computer Science", "(not a target branch)" for the others. */
export function branchOpts(branches: readonly { id: number | string; code?: string | null; name?: string | null; is_relevant?: number | boolean | null }[] = []): { value: string; label: string }[] {
  return branches.map((b) => ({ value: String(b.id), label: `${b.code ? `${b.code} — ` : ""}${b.name || ""}${b.is_relevant ? "" : " (not a target branch)"}` }));
}

/** Branches with target branches first, then by code. */
export function sortBranches<T extends { code?: string | null; name?: string | null; is_relevant?: number | boolean | null }>(branches: readonly T[] = []): T[] {
  return branches.slice().sort((a, b) => (b.is_relevant ? 1 : 0) - (a.is_relevant ? 1 : 0) || String(a.code || a.name).localeCompare(String(b.code || b.name)));
}
