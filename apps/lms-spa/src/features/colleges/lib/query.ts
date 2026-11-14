/**
 * URL query helpers (the old components.js getHashQuery / setHashQuery / historyMode, for real query strings).
 * Every list keeps its filters, sort and page in the URL so Back, reload and shared links restore the view.
 *
 *   const [q, setQuery] = useQueryState();
 *   q.status            // "open" | undefined
 *   setQuery({ status: "done", page: null })          // null / "" / false / [] remove a key
 *   setQuery({ q: text }, { history: "auto" })        // typing replaces the entry, discrete changes push one (D8)
 *
 * The district scope parameter `d` is owned by the shell; setQuery never drops it.
 */
import { useCallback, useMemo, useRef } from "react";
import { useLocation, useNavigate } from "react-router";

export type QueryPatch = Record<string, string | number | boolean | null | undefined | readonly (string | number)[]>;
export type HistoryMode = "replace" | "push" | "auto";

/** Free-text keys: changing only these never adds a Back step. */
const TEXT_KEYS = new Set(["q", "search"]);

/** Plain object of a query string (last value wins). */
export function readQuery(search: string): Record<string, string> {
  return Object.fromEntries(new URLSearchParams(search));
}

/** Merge `patch` into `search`; returns the new query string ("" or "?a=1"). Commas stay readable. */
export function mergeQuery(search: string, patch: QueryPatch): string {
  const q = new URLSearchParams(search);
  for (const [k, v] of Object.entries(patch)) {
    if (v === null || v === undefined || v === "" || v === false || (Array.isArray(v) && !v.length)) q.delete(k);
    else q.set(k, Array.isArray(v) ? v.join(",") : String(v));
  }
  const s = q.toString().replace(/%2C/gi, ",");
  return s ? `?${s}` : "";
}

/** D8: push when a key other than a free-text key changed and the user is interacting; else replace. */
export function historyModeFor(prev: Record<string, string>, next: Record<string, string>, userActive = true): "replace" | "push" {
  const keys = new Set([...Object.keys(prev), ...Object.keys(next)]);
  const changed = [...keys].filter((k) => String(prev[k] ?? "") !== String(next[k] ?? ""));
  if (!changed.length || changed.every((k) => TEXT_KEYS.has(k))) return "replace";
  return userActive ? "push" : "replace";
}

/** React: the current query as an object + a setter that merges a patch into the URL (no remount, no scroll). */
export function useQueryState(): [Record<string, string>, (patch: QueryPatch, opts?: { history?: HistoryMode }) => void] {
  const location = useLocation();
  const navigate = useNavigate();
  const values = useMemo(() => readQuery(location.search), [location.search]);
  const loc = useRef(location);
  loc.current = location;
  const mountedAt = useRef(typeof performance !== "undefined" ? performance.now() : 0);

  const set = useCallback(
    (patch: QueryPatch, opts: { history?: HistoryMode } = {}) => {
      const cur = loc.current;
      const search = mergeQuery(cur.search, patch);
      if (search === cur.search || (search === "" && cur.search === "?")) return;
      let mode = opts.history ?? "replace";
      if (mode === "auto") {
        const active = typeof navigator !== "undefined" && "userActivation" in navigator ? (navigator as Navigator & { userActivation: { isActive: boolean } }).userActivation.isActive : true;
        // URL canonicalisation in the first moments after a page opens never adds a Back step
        const settling = typeof performance !== "undefined" && performance.now() - mountedAt.current < 400;
        mode = historyModeFor(readQuery(cur.search), readQuery(search), active && !settling);
      }
      void navigate({ pathname: cur.pathname, search, hash: cur.hash }, { replace: mode === "replace", preventScrollReset: true });
    },
    [navigate],
  );
  return [values, set];
}

/** A comma list from the query (`?ids=a,b` → ['a','b']). */
export function queryList(v: string | undefined | null): string[] {
  return String(v ?? "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

/** A positive integer from the query (page numbers), else `fallback`. */
export function queryInt(v: string | undefined | null, fallback = 1): number {
  const n = Number.parseInt(String(v ?? ""), 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}
