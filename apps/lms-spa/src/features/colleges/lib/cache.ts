/**
 * Read cache for the portal API: request de-duplication + a small in-memory cache, so moving between screens is
 * instant (stale-while-revalidate) and two components asking for the same list share one request.
 *
 * - Key = the full request URL (path + query + the `districts=` scope when `scoped`).
 * - A cached answer younger than `ttl` (default 30 s) is used without a request; an older one is shown at once
 *   while a background request refreshes it (`refreshing: true`).
 * - Any successful write (portalApi.post/patch/put/del) clears the whole cache and every mounted query refetches
 *   (rollups change everywhere, so partial invalidation is not worth the risk). `invalidatePortalCache(prefix)`
 *   clears part of it by hand.
 * - At most MAX_ENTRIES answers are kept (oldest dropped first). Nothing is persisted.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { onPortalWrite, portalApi, portalUrl, type Query } from "./api";
import { scopeParam, useDistrictScope } from "./scope";

export const DEFAULT_TTL_MS = 30_000;
const MAX_ENTRIES = 200;

interface Entry {
  data?: unknown;
  at: number;
  promise?: Promise<unknown>;
}

const cache = new Map<string, Entry>();
let generation = 0;
const genListeners = new Set<() => void>();

export interface CacheRequest {
  query?: Query;
  /** add the global district scope (`districts=`) — the key follows the scope */
  scoped?: boolean;
}

function effectiveQuery(req: CacheRequest): Query {
  return req.scoped ? { districts: scopeParam(), ...req.query } : { ...req.query };
}

/** Cache key of a GET (the request URL). */
export function cacheKey(path: string, req: CacheRequest = {}): string {
  return portalUrl(path, effectiveQuery(req));
}

function remember(key: string, e: Entry): void {
  cache.delete(key);
  cache.set(key, e);
  while (cache.size > MAX_ENTRIES) {
    const first = cache.keys().next().value;
    if (first === undefined) break;
    cache.delete(first);
  }
}

/**
 * GET through the cache. Fresh (age < ttl) answers resolve without a request; concurrent calls for the same key
 * share one request; `force` always asks the server (still de-duplicated).
 */
export function fetchCached<T>(path: string, req: CacheRequest & { ttl?: number; force?: boolean } = {}): Promise<T> {
  const key = cacheKey(path, req);
  const hit = cache.get(key);
  const ttl = req.ttl ?? DEFAULT_TTL_MS;
  if (hit?.promise) return hit.promise as Promise<T>;
  if (!req.force && hit && hit.data !== undefined && Date.now() - hit.at < ttl) return Promise.resolve(hit.data as T);
  const gen = generation;
  const p = portalApi.get<T>(path, { query: req.query, scoped: req.scoped }).then(
    (data) => {
      // an invalidation while this was in flight: hand the answer to the caller, but do not cache it
      if (gen === generation) remember(key, { data, at: Date.now() });
      else if (cache.get(key)?.promise === p) cache.delete(key);
      return data;
    },
    (err: unknown) => {
      const cur = cache.get(key);
      if (cur?.promise === p) {
        if (cur.data !== undefined) remember(key, { data: cur.data, at: cur.at });
        else cache.delete(key);
      }
      throw err;
    },
  );
  remember(key, { data: hit?.data, at: hit?.at ?? 0, promise: p });
  return p;
}

/** The cached answer for a GET (any age), without a request. */
export function peekCached<T>(path: string, req: CacheRequest = {}): { data: T; at: number } | undefined {
  const hit = cache.get(cacheKey(path, req));
  return hit && hit.data !== undefined ? { data: hit.data as T, at: hit.at } : undefined;
}

/** Drop cached answers (all, or those whose path starts with `prefix`, e.g. "colleges") and refetch mounted queries. */
export function invalidatePortalCache(prefix?: string): void {
  const base = prefix ? portalUrl(prefix).split("?")[0]! : null;
  for (const k of [...cache.keys()]) if (!base || k.startsWith(base)) cache.delete(k);
  generation += 1;
  for (const l of genListeners) l();
}

onPortalWrite(() => invalidatePortalCache());

const subscribeGen = (fn: () => void) => {
  genListeners.add(fn);
  return () => genListeners.delete(fn);
};
const getGen = () => generation;

export interface PortalQuery<T> {
  /** last answer for this request (from the cache at once when there is one) */
  data: T | undefined;
  error: unknown;
  /** true while there is no data yet for this request */
  loading: boolean;
  /** true while a background request refreshes data that is already shown */
  refreshing: boolean;
  /** ask the server again (keeps showing the current data) */
  reload: () => Promise<void>;
}

export interface PortalQueryOptions extends CacheRequest {
  /** freshness window in ms (default 30 s) */
  ttl?: number;
  /** keep showing the previous request's data while a new key loads (filters, paging) */
  keepPrevious?: boolean;
}

/**
 * React: GET a portal endpoint through the cache. `path === null` waits (dependent requests).
 *
 *   const { data, error, loading, reload } = usePortalQuery<CollegeRow[]>("colleges", { scoped: true, query: { q } });
 *
 * A change of path / query / scope (when `scoped`) loads the new request; stale answers are dropped.
 */
export function usePortalQuery<T>(path: string | null, opts: PortalQueryOptions = {}): PortalQuery<T> {
  const scope = useDistrictScope();
  const gen = useSyncExternalStore(subscribeGen, getGen, getGen);
  const queryKey = JSON.stringify(opts.query ?? {});
  const scopeKey = opts.scoped ? JSON.stringify(scope) : "";
  const key = path === null ? null : cacheKey(path, { query: opts.query, scoped: opts.scoped });
  const initial = path === null ? undefined : peekCached<T>(path, { query: opts.query, scoped: opts.scoped });

  const [state, setState] = useState<{ key: string | null; data: T | undefined; error: unknown; loading: boolean; refreshing: boolean }>(() => ({
    key,
    data: initial?.data,
    error: null,
    loading: path !== null && !initial,
    refreshing: false,
  }));
  const seq = useRef(0);
  const ttl = opts.ttl ?? DEFAULT_TTL_MS;
  const keepPrevious = !!opts.keepPrevious;
  const scoped = !!opts.scoped;

  const run = useCallback(
    async (force: boolean) => {
      if (path === null) return;
      const id = ++seq.current;
      const query = JSON.parse(queryKey) as Query;
      const k = cacheKey(path, { query, scoped });
      const cached = peekCached<T>(path, { query, scoped });
      const fresh = !!cached && Date.now() - cached.at < ttl;
      setState((s) => {
        const sameKey = s.key === k;
        const data = cached ? cached.data : sameKey || keepPrevious ? s.data : undefined;
        return { key: k, data, error: null, loading: data === undefined, refreshing: data !== undefined && (force || !fresh) };
      });
      if (fresh && !force) {
        setState((s) => (id === seq.current ? { ...s, loading: false, refreshing: false } : s));
        return;
      }
      try {
        const data = await fetchCached<T>(path, { query, scoped, ttl, force });
        if (id === seq.current) setState({ key: k, data, error: null, loading: false, refreshing: false });
      } catch (error) {
        if (id === seq.current) setState((s) => ({ ...s, error, loading: false, refreshing: false }));
      }
    },
    [path, queryKey, scoped, ttl, keepPrevious],
  );

  useEffect(() => {
    void run(false);
    // scopeKey / gen: a scope change or an invalidation re-runs the request
  }, [run, scopeKey, gen]);

  const reload = useCallback(() => run(true), [run]);

  if (path === null) return { data: undefined, error: null, loading: false, refreshing: false, reload };
  // The first render after a key change still holds the previous key's state: never show another request's data.
  if (state.key !== key && !keepPrevious) {
    const c = peekCached<T>(path, { query: opts.query, scoped: opts.scoped });
    return { data: c?.data, error: null, loading: !c, refreshing: !!c, reload };
  }
  return { data: state.data, error: state.error, loading: state.loading, refreshing: state.refreshing, reload };
}

/** Warm the cache for a screen the user is likely to open next (e.g. on link hover). Errors are ignored. */
export function prefetchPortal(path: string, req: CacheRequest = {}): void {
  fetchCached(path, req).catch(() => undefined);
}

/** Tests only. */
export function clearPortalCacheForTests(): void {
  cache.clear();
  generation = 0;
}
