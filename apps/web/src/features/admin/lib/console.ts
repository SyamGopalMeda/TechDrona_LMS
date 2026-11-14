"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest, type ApiResult, type ApprovalPending, type RequestOptions } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

/**
 * Shared data helpers for the staff consoles (security, admin, support, finance).
 * Everything here goes through the BFF API client; the api authorises every call, so
 * these hooks only render what the api returns (monitoring visibility tiers are the
 * api's job: a field that is absent is shown as absent, never guessed).
 */

export type Query = NonNullable<RequestOptions["query"]>;

export interface PageInfo {
  next_cursor: string | null;
  has_more: boolean;
  limit?: number;
}

export interface ListEnvelope<T> {
  data: T[];
  page?: PageInfo;
  counts?: Record<string, number>;
  [extra: string]: unknown;
}

export interface CursorList<T> {
  rows: T[] | undefined;
  envelope: ListEnvelope<T> | undefined;
  loading: boolean;
  error: unknown;
  hasMore: boolean;
  hasPrevious: boolean;
  next: () => void;
  previous: () => void;
  reload: () => Promise<void>;
}

function stableKey(q: Query | undefined): string {
  if (!q) return "";
  return Object.keys(q)
    .sort()
    .map((k) => `${k}=${String(q[k] ?? "")}`)
    .join("&");
}

/** Strip empty filter values so the query string only carries what the user chose. */
export function cleanQuery(q: Record<string, string | number | boolean | null | undefined>): Query {
  const out: Query = {};
  for (const [k, v] of Object.entries(q)) if (v !== "" && v !== undefined && v !== null && v !== false) out[k] = v;
  return out;
}

/** Cursor-paginated GET (api-specification §1.10) with a client-side cursor stack for "Previous". */
export function useCursorList<T>(path: string | null, query?: Query, options?: Omit<RequestOptions, "method" | "body" | "query">): CursorList<T> {
  const key = stableKey(query);
  const [stack, setStack] = useState<(string | undefined)[]>([undefined]);
  const [envelope, setEnvelope] = useState<ListEnvelope<T>>();
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);
  const q = useRef(query);
  q.current = query;
  const opts = useRef(options);
  const cursor = stack[stack.length - 1];

  // A new filter set starts from the first page.
  useEffect(() => setStack([undefined]), [key, path]);

  const reload = useCallback(async () => {
    if (path === null) return;
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await apiRequest<ListEnvelope<T>>(path, { ...opts.current, method: "GET", query: { ...q.current, cursor } });
      if (id !== seq.current) return;
      if (res.kind === "ok") setEnvelope(res.data);
    } catch (err) {
      if (id === seq.current) setError(err);
    } finally {
      if (id === seq.current) setLoading(false);
    }
    // key captures the query contents
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, key, cursor]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const nextCursor = envelope?.page?.next_cursor ?? null;
  return {
    rows: envelope?.data,
    envelope,
    loading,
    error,
    hasMore: !!envelope?.page?.has_more && !!nextCursor,
    hasPrevious: stack.length > 1,
    next: () => {
      if (nextCursor) setStack((s) => [...s, nextCursor]);
    },
    previous: () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s)),
    reload,
  };
}

export interface Versioned<T> {
  data: T | undefined;
  etag: string | null;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
}

/**
 * GET that also keeps the ETag (needed as If-Match for case / unblock transitions,
 * api-specification §1.9). Pass `path = null` to wait (e.g. until a reason code is chosen).
 */
export function useVersioned<T>(path: string | null, query?: Query, options?: Omit<RequestOptions, "method" | "body" | "query">): Versioned<T> {
  const key = stableKey(query);
  const [data, setData] = useState<T>();
  const [etag, setEtag] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);
  const q = useRef(query);
  q.current = query;
  const opts = useRef(options);

  const reload = useCallback(async () => {
    if (path === null) return;
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await apiRequest<T>(path, { ...opts.current, method: "GET", query: q.current });
      if (id !== seq.current) return;
      if (res.kind === "ok") {
        setData(res.data);
        setEtag(res.etag);
      }
    } catch (err) {
      if (id === seq.current) setError(err);
    } finally {
      if (id === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, key]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, etag, error, loading, reload };
}

/** ETag from the response, else the resource's `version` field (`"v<version>"`). */
export function ifMatchFor(etag: string | null, version?: number | null): string | undefined {
  if (etag) return etag;
  return typeof version === "number" ? `"v${version}"` : undefined;
}

/* --------------------------------------------------------------- mutations */

export type MutationOutcome<T> =
  | { kind: "ok"; data: T; status: number; requestId: string | null }
  | { kind: "approval_pending"; approval: ApprovalPending; requestId: string | null };

export function toOutcome<T>(res: ApiResult<T>): MutationOutcome<T> {
  if (res.kind === "approval_pending") return { kind: "approval_pending", approval: res.approval, requestId: res.requestId };
  return { kind: "ok", data: res.data, status: res.status, requestId: res.requestId };
}

/** Field errors keyed by field name from a 422 validation problem. */
export function problemFieldErrors(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError)) return {};
  const out: Record<string, string> = {};
  for (const e of err.problem?.errors ?? []) if (!(e.field in out)) out[e.field] = e.message;
  return out;
}

/* --------------------------------------------------------------- formatting */

const TZ = "Asia/Kolkata";

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: TZ }).format(d)} IST`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: TZ }).format(d);
}

/** "in 52 h", "3 h ago", "in 12 days", relative to now. */
export function formatCountdown(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const diffH = (t - now) / 3_600_000;
  const abs = Math.abs(diffH);
  const days = Math.round(abs / 24);
  const text = abs < 1 ? `${Math.max(1, Math.round(abs * 60))} min` : abs < 48 ? `${Math.round(abs)} h` : `${days} ${days === 1 ? "day" : "days"}`;
  return diffH >= 0 ? `in ${text}` : `${text} ago`;
}

/** INR from paise with Indian digit grouping (₹18,42,300.00). */
export function formatINR(paise: number | null | undefined): string {
  if (typeof paise !== "number" || Number.isNaN(paise)) return "—";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2 }).format(paise / 100);
}

export function humanize(key: string | null | undefined): string {
  if (!key) return "—";
  const s = key.replace(/[_.-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Render an unknown cell value safely (reports return heterogeneous rows). */
export function cellText(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(v);
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.map(cellText).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/* ---------------------------------------------------------------- identity */

/**
 * Readable short reference for a record that has no human number (audit 1.11): the last 8
 * characters of its id, uppercased, e.g. `#9F3C21AB`. Staff can read it out on a call; the full
 * id stays available for copy (select-all) where needed.
 */
export function shortRef(id: string | null | undefined, prefix = "#"): string {
  if (!id) return "—";
  const clean = id.replace(/[^a-zA-Z0-9]/g, "");
  return `${prefix}${(clean.length > 8 ? clean.slice(-8) : clean).toUpperCase()}`;
}

/** Best readable name for a person: name, then email, then a short reference ("User #9F3C21AB"). */
export function personLabel(p: { name?: string | null; full_name?: string | null; display_name?: string | null; email?: string | null; id?: string | null } | null | undefined): string {
  if (!p) return "—";
  const name = p.full_name ?? p.display_name ?? p.name;
  if (name && name.trim()) return name.trim();
  if (p.email && p.email.trim()) return p.email.trim();
  return p.id ? `User ${shortRef(p.id)}` : "—";
}
