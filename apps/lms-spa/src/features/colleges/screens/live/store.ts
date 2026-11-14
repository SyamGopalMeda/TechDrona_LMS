/**
 * Live official-source status (port of the store in js/views/live.js): GET /api/live[?refresh=1] starts a background
 * re-check of the official sources; while the answer says `refreshing` we poll every 5 s (give up after 90 s).
 * Screens read it with `useLiveStatus()`; `finished` counts completed refreshes so cards can reload their data.
 *
 * Time helpers keep the old IST wording ("12 min ago · 9 Nov, 6:35 pm"), relative to the server clock.
 */
import { useSyncExternalStore } from "react";
import { isPortalApiError, portalApi } from "../../lib/api";

export const POLL_MS = 5000;
export const POLL_MAX_MS = 90_000;
const STALE_REFRESH_MS = 15 * 60_000;
export const RESEARCH_LABEL = "Researched Nov 2026 (not live)";

export interface LiveSource {
  id: string;
  name?: string | null;
  url?: string | null;
  provides?: string | null;
  last_status?: "ok" | "error" | "never" | "running" | string | null;
  last_error?: string | null;
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  changed_at?: string | null;
  item_count?: number | null;
  fresh?: boolean;
  using_fallback?: boolean;
  [k: string]: unknown;
}

export interface LiveData {
  now?: string;
  refreshing?: boolean;
  sources?: LiveSource[];
  coverage?: Record<string, number | null | undefined> | null;
  automation?: { topic: string; status?: string; source?: string; how?: string; note?: string }[];
  recent_changes?: { at: string; source?: string; college_id?: string | null; college_name?: string | null; summary?: string }[];
  [k: string]: unknown;
}

interface LiveState {
  data: LiveData | null;
  error: unknown;
  unavailable: boolean;
  gaveUp: boolean;
  /** number of refreshes that finished (cards reload when it grows) */
  finished: number;
}

let state: LiveState = { data: null, error: null, unavailable: false, gaveUp: false, finished: 0 };
let skew = 0;
let pollStart = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
let inflight: Promise<LiveData | null> | null = null;
let lastFetch = 0;
let started = false;
const listeners = new Set<() => void>();

function set(patch: Partial<LiveState>): void {
  state = { ...state, ...patch };
  for (const l of listeners) l();
}

export const nowMs = (): number => Date.now() + skew;

function accept(d: LiveData): void {
  if (!d || typeof d !== "object") return;
  const wasRefreshing = !!state.data?.refreshing;
  if (d.now && !Number.isNaN(Date.parse(d.now))) skew = Date.parse(d.now) - Date.now();
  lastFetch = Date.now();
  clearTimeout(timer);
  if (d.refreshing) {
    if (!pollStart) pollStart = Date.now();
    if (Date.now() - pollStart > POLL_MAX_MS) {
      pollStart = 0;
      set({ data: d, error: null, unavailable: false, gaveUp: true, finished: state.finished + 1 });
      return;
    }
    timer = setTimeout(() => void fetchLive(), POLL_MS);
    set({ data: d, error: null, unavailable: false, gaveUp: false });
  } else {
    pollStart = 0;
    set({ data: d, error: null, unavailable: false, gaveUp: false, finished: state.finished + (wasRefreshing ? 1 : 0) });
  }
}

/** GET /api/live (refresh=1 asks the server to re-check stale sources in the background). */
export function fetchLive({ refresh = false }: { refresh?: boolean } = {}): Promise<LiveData | null> {
  if (inflight && !refresh) return inflight;
  const p: Promise<LiveData | null> = portalApi
    .get<LiveData>("live", { query: refresh ? { refresh: 1 } : undefined })
    .then((d) => {
      accept(d);
      return d;
    })
    .catch((e: unknown) => {
      const st = isPortalApiError(e) ? e.status : -1;
      if (st === 404 || st === 405) set({ error: e, unavailable: true });
      else {
        if (pollStart && Date.now() - pollStart < POLL_MAX_MS) {
          clearTimeout(timer);
          timer = setTimeout(() => void fetchLive(), POLL_MS * 2);
        }
        set({ error: e });
      }
      return null;
    })
    .finally(() => {
      if (inflight === p) inflight = null;
    });
  inflight = p;
  return p;
}

function onVisible(): void {
  if (document.visibilityState === "visible" && !state.unavailable && Date.now() - lastFetch > STALE_REFRESH_MS) void fetchLive({ refresh: true });
}

/** Once per visit: start the background re-check (the old shell's startLive). */
export function startLive(): void {
  if (started) return;
  started = true;
  void fetchLive({ refresh: true });
  if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVisible);
}

let lastMountRefresh = 0;
/**
 * The Official sources screen, on mount: GET /api/live?refresh=1 (starts the per-visit re-check on the first call).
 * A second call within 2 s (React StrictMode's double effect) is ignored.
 */
export function refreshOnMount(): void {
  if (Date.now() - lastMountRefresh < 2000) return;
  lastMountRefresh = Date.now();
  if (!started) startLive();
  else void fetchLive({ refresh: true });
}

/** Editor: POST /api/live/refresh — re-check one source or all now (ignores the refresh interval). */
export async function forceRefresh(source?: string): Promise<unknown> {
  const d = await portalApi.post<LiveData>("live/refresh", source ? { source } : {});
  pollStart = Date.now();
  accept(d && typeof d === "object" && d.sources ? d : { ...(state.data ?? {}), refreshing: true });
  if (!(d && typeof d === "object" && d.sources)) void fetchLive();
  return d;
}

const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};
const snapshot = () => state;

export function useLiveStatus(): LiveState {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

export interface LiveSummary {
  tone: "good" | "warn" | "busy" | "neutral";
  text: string;
  short: string;
  at?: string;
}

/** One summary line for page headers (and a future top-bar chip). null = live data not available on this server. */
export function liveSummary(s: LiveState = state): LiveSummary | null {
  if (s.unavailable) return null;
  const d = s.data;
  if (!d) return s.error ? { tone: "neutral", text: "Official data: could not check", short: "Not checked" } : { tone: "busy", text: "Checking official sources…", short: "Checking…" };
  const sources = Array.isArray(d.sources) ? d.sources : [];
  if (d.refreshing && !s.gaveUp) return { tone: "busy", text: "Checking official sources…", short: "Checking…" };
  const failing = sources.filter((x) => x.last_status === "error");
  if (failing.length) {
    const withCopy = failing.filter((x) => x.last_success_at).length;
    const n = failing.length;
    return { tone: "warn", text: `${n} source${n === 1 ? "" : "s"} unreachable${withCopy ? " — showing last copy" : ""}`, short: `${n} unreachable` };
  }
  const never = sources.filter((x) => !x.last_success_at);
  if (!sources.length || never.length === sources.length) return { tone: "neutral", text: "Official data: not checked yet", short: "Not checked" };
  const oldest = sources
    .map((x) => x.last_success_at)
    .filter((x): x is string => !!x)
    .sort()[0];
  if (never.length) return { tone: "warn", text: `Official data: ${never.length} source${never.length === 1 ? "" : "s"} not checked yet`, short: `${never.length} not checked`, at: oldest };
  return { tone: "good", text: `Official data: checked ${relTime(oldest)}`, short: `Checked ${relTime(oldest)}`, at: oldest };
}

/* ------------------------------------------------------------------ time (IST) */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
let istFmt: Intl.DateTimeFormat | null = null;
function istParts(t: number): { y: number; m: number; d: number; hh: string; mm: string; ap: string } {
  try {
    istFmt ??= new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", hour12: true });
    const p = Object.fromEntries(istFmt.formatToParts(new Date(t)).map((x) => [x.type, x.value]));
    return { y: Number(p.year), m: Number(p.month) - 1, d: Number(p.day), hh: String(p.hour), mm: String(p.minute), ap: String(p.dayPeriod ?? "").toLowerCase() };
  } catch {
    const d = new Date(t + 330 * 60_000);
    return {
      y: d.getUTCFullYear(),
      m: d.getUTCMonth(),
      d: d.getUTCDate(),
      hh: String(((d.getUTCHours() + 11) % 12) + 1),
      mm: String(d.getUTCMinutes()).padStart(2, "0"),
      ap: d.getUTCHours() < 12 ? "am" : "pm",
    };
  }
}
const toMs = (iso: string | null | undefined): number => (iso ? Date.parse(iso) : Number.NaN);

/** "9 Nov, 6:35 pm" (year added when not this year), IST. */
export function absTime(iso: string | null | undefined): string {
  const t = toMs(iso);
  if (Number.isNaN(t)) return "—";
  const p = istParts(t);
  const yNow = istParts(nowMs()).y;
  return `${p.d} ${MONTHS[p.m]}${p.y !== yNow ? ` ${p.y}` : ""}, ${p.hh}:${p.mm} ${p.ap}`;
}

/** "just now" | "12 min ago" | "3 h ago" | "2 days ago" */
export function relTime(iso: string | null | undefined): string {
  const t = toMs(iso);
  if (Number.isNaN(t)) return "never";
  const s = Math.round((nowMs() - t) / 1000);
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const hr = Math.round(m / 60);
  if (hr < 24) return `${hr} h ago`;
  const d = Math.round(hr / 24);
  return d === 1 ? "1 day ago" : `${d} days ago`;
}

/** Tests only. */
export function resetLiveStoreForTests(): void {
  clearTimeout(timer);
  state = { data: null, error: null, unavailable: false, gaveUp: false, finished: 0 };
  skew = 0;
  pollStart = 0;
  inflight = null;
  lastFetch = 0;
  lastMountRefresh = 0;
  if (started && typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisible);
  started = false;
}
