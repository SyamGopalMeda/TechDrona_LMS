"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { addApiResponseListener, api, readCsrfToken, type RequestOptions } from "./client";
import { isApiError } from "./errors";
import { serverApiGet } from "./server";
import { onSessionReset } from "@/spa/session";

/**
 * Session-scoped cache for the identity reads every portal page needs: `GET me`, `GET me/grants`
 * and `GET me/modules` (docs/perf/spa-requests.md). Before this, the gate, the portal switcher, the
 * account menu, the module switcher and several pages each asked the API again on every mount.
 *
 * UX caching only: the API still authorises every request, and nothing here grants access.
 *
 * - One request per path at a time: concurrent callers share the in-flight promise.
 * - Results live in memory for the browser session, and in sessionStorage for {@link PERSIST_TTL_MS}
 *   so a full reload reuses them. Both are keyed by the session (a hash of the session-bound
 *   `td_csrf` cookie, re-minted by the API function whenever the session changes) and by the user
 *   id from `GET me`: another session or another user in this tab never sees these values.
 * - Dropped on: sign-in / sign-out / password change (any `auth/*` write, entering an auth page,
 *   the session probe answering "no" or re-issuing the session), any 401/403 answer (except CSRF and
 *   step-up retries), and {@link clearIdentityCache} / {@link refreshIdentity}.
 * - Re-read (and mounted hooks updated) after this user's own profile / MFA / role-grant changes.
 * - Errors are never cached.
 */
export type IdentityPath = "me" | "me/grants" | "me/modules";
export const IDENTITY_PATHS: readonly IdentityPath[] = ["me", "me/grants", "me/modules"];

/** How long a value stored in sessionStorage is reused by a full page reload. */
export const PERSIST_TTL_MS = 5 * 60_000;
const STORAGE_KEY = "td.identity.v1";

type Handle = NonNullable<RequestOptions["handle"]>;

interface Entry {
  data: unknown;
  at: number;
}

const entries = new Map<IdentityPath, Entry>();
const inflight = new Map<IdentityPath, Promise<unknown>>();
const listeners = new Map<IdentityPath, Set<() => void>>();
/** Bumped by every clear: a response that started before it is not stored. */
let generation = 0;
/** Session discriminator the memory entries belong to (null: no readable td_csrf cookie). */
let sessionKey: string | null = null;
let userId: string | null = null;
let hydrated = false;

/* ------------------------------------------------------------------ session key */

/** FNV-1a: the stored key never contains the CSRF token itself. */
function hash(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(36);
}

function currentSessionKey(): string | null {
  const token = readCsrfToken();
  return token ? hash(token) : null;
}

/** The memory entries are for another session (signed out and in again, maybe in another tab). */
function ensureSession(): void {
  const key = currentSessionKey();
  if (!hydrated) {
    hydrated = true;
    sessionKey = key;
    hydrate(key);
    return;
  }
  if (key !== sessionKey) {
    resetMemory();
    sessionKey = key;
  }
}

/* ------------------------------------------------------------------ sessionStorage */

interface Stored {
  sid: string;
  uid: string | null;
  entries: Partial<Record<IdentityPath, Entry>>;
}

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

function hydrate(key: string | null): void {
  const s = storage();
  if (!s) return;
  try {
    const raw = s.getItem(STORAGE_KEY);
    if (!raw) return;
    const stored = JSON.parse(raw) as Stored;
    if (!key || stored.sid !== key) {
      s.removeItem(STORAGE_KEY);
      return;
    }
    const now = Date.now();
    userId = stored.uid ?? null;
    for (const path of IDENTITY_PATHS) {
      const e = stored.entries?.[path];
      if (e && typeof e.at === "number" && now - e.at < PERSIST_TTL_MS && e.at <= now) entries.set(path, e);
    }
  } catch {
    /* unreadable: start empty */
  }
}

function persist(): void {
  const s = storage();
  if (!s) return;
  try {
    if (!sessionKey || entries.size === 0) {
      s.removeItem(STORAGE_KEY);
      return;
    }
    const stored: Stored = { sid: sessionKey, uid: userId, entries: Object.fromEntries(entries) };
    s.setItem(STORAGE_KEY, JSON.stringify(stored));
  } catch {
    /* full / blocked: memory only */
  }
}

/* ------------------------------------------------------------------ store */

function notify(path: IdentityPath): void {
  for (const fn of listeners.get(path) ?? []) fn();
}

function resetMemory(): void {
  generation += 1;
  entries.clear();
  inflight.clear();
  userId = null;
}

/** Forget everything (memory and sessionStorage). Sign-out, another user, tests. */
export function clearIdentityCache(): void {
  resetMemory();
  hydrated = true;
  sessionKey = currentSessionKey();
  const s = storage();
  try {
    s?.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

/** Tests: forget everything, including the session key read at start. */
export function resetIdentityCacheForTests(): void {
  clearIdentityCache();
  hydrated = false;
  sessionKey = null;
  listeners.clear();
}

function store(path: IdentityPath, data: unknown): void {
  if (path === "me") {
    const id = (data as { user?: { id?: unknown } } | null)?.user?.id;
    if (typeof id === "string") {
      // Another user in this tab: nothing cached for the previous one survives.
      if (userId && userId !== id) resetMemory();
      userId = id;
    }
  }
  entries.set(path, { data, at: Date.now() });
  persist();
  notify(path);
}

function fetchInto<T>(path: IdentityPath): Promise<T> {
  const gen = generation;
  const p = serverApiGet<T>(path)
    .then((data) => {
      if (gen === generation) store(path, data);
      return data;
    })
    .finally(() => {
      if (inflight.get(path) === p) inflight.delete(path);
    });
  inflight.set(path, p);
  return p;
}

/** The cached value, synchronously (undefined when not cached). */
export function peekIdentity<T>(path: IdentityPath): T | undefined {
  ensureSession();
  return entries.get(path)?.data as T | undefined;
}

const wantsGlobalHandling = (h: Handle | undefined) => !!h && Object.values(h).some(Boolean);
/** The client's default handling (what `useResource(path)` / `useApi(path)` without options did). */
export const DEFAULT_HANDLE: Handle = { stepUp: true, restriction: true, auth: true, sessionChoice: true };

export interface IdentityOptions {
  /** Skip the cached value and ask the API (the result replaces it). */
  force?: boolean;
  /**
   * The client's global handling this caller relied on (sign-in redirect, restriction page…).
   * The shared request is silent; when it fails with 401/403/409 such a caller repeats it with its
   * own handling, so a failure behaves exactly as before. Omitted = silent (as `serverApiGet`).
   */
  handle?: Handle;
}

/**
 * `GET <path>` through the cache. Errors throw as from `serverApiGet` (ApiError with the API's
 * problem; network failures as 503).
 */
export async function getIdentity<T>(path: IdentityPath, opts: IdentityOptions = {}): Promise<T> {
  ensureSession();
  if (!opts.force) {
    const hit = entries.get(path);
    if (hit) return hit.data as T;
  }
  let p = (opts.force ? undefined : inflight.get(path)) as Promise<T> | undefined;
  p ??= fetchInto<T>(path);
  try {
    return await p;
  } catch (err) {
    if (wantsGlobalHandling(opts.handle) && isApiError(err) && (err.status === 401 || err.status === 403 || err.status === 409)) {
      return api.get<T>(path, { handle: opts.handle });
    }
    throw err;
  }
}

/** Re-read the given paths (default: the ones cached) and update mounted hooks. */
export async function refreshIdentity(paths?: readonly IdentityPath[]): Promise<void> {
  ensureSession();
  const targets = paths ?? IDENTITY_PATHS.filter((p) => entries.has(p));
  await Promise.all(targets.map((p) => getIdentity(p, { force: true }).catch(() => undefined)));
}

/**
 * Start the identity reads early (app start, before the portal layout chunk has loaded), so the
 * gate and the shell find them ready. A read that fails is not kept: the gate asks again.
 */
export function prefetchIdentity(paths: readonly IdentityPath[]): void {
  for (const p of paths) void getIdentity(p).catch(() => undefined);
}

/**
 * Like {@link prefetchIdentity}, started in parallel with the session probe. The probe may
 * re-issue the session cookie (remember-device), so a read that fails is retried once after it,
 * and callers joining meanwhile get the retried answer, never the stale 401.
 */
export function prefetchIdentityWithProbe(paths: readonly IdentityPath[], probe: Promise<unknown>): void {
  ensureSession();
  for (const path of paths) {
    if (entries.has(path) || inflight.has(path)) continue;
    const gen = generation;
    const p: Promise<unknown> = serverApiGet<unknown>(path)
      .catch(async (err: unknown) => {
        if (!isApiError(err) || err.status !== 401) throw err;
        await probe;
        return serverApiGet<unknown>(path);
      })
      .then((data) => {
        if (gen === generation) store(path, data);
        return data;
      })
      .finally(() => {
        if (inflight.get(path) === p) inflight.delete(path);
      });
    inflight.set(path, p);
    void p.catch(() => undefined);
  }
}

/* ------------------------------------------------------------------ invalidation */

/** Writes that change who the caller is or what they may open (cleared: a navigation follows). */
const CLEAR_ON_WRITE = /^auth\//;
/** This user's own changes the header / switchers show: re-read what is cached. */
const REFRESH_ON_WRITE: { re: RegExp; paths: IdentityPath[] }[] = [
  { re: /^me\/(profile|mfa|consents)(\/|$)/, paths: ["me"] },
  { re: /^(rbac\/|admin\/roles(\/|$)|admin\/break-glass(\/|$)|admin\/users\/[^/]+\/(roles|grants)(\/|$))/, paths: ["me/grants", "me/modules"] },
];
/** 401/403 codes that are part of a retry, not a change of identity. */
const NOT_IDENTITY = new Set(["csrf_failed", "step_up_required"]);

let wired = false;
function wire(): void {
  if (wired) return;
  wired = true;
  addApiResponseListener((e) => {
    if (e.status === 401 || e.status === 403) {
      if (!e.code || !NOT_IDENTITY.has(e.code)) clearIdentityCache();
      return;
    }
    if (e.method === "GET" || e.status >= 400) return;
    if (CLEAR_ON_WRITE.test(e.path)) {
      clearIdentityCache();
      return;
    }
    for (const rule of REFRESH_ON_WRITE) {
      if (!rule.re.test(e.path)) continue;
      const cached = rule.paths.filter((p) => entries.has(p));
      for (const p of rule.paths) entries.delete(p);
      persist();
      void refreshIdentity(cached);
    }
  });
  onSessionReset(() => clearIdentityCache());
}
wire();

/* ------------------------------------------------------------------ hooks */

export interface IdentityResource<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  /** Ask the API again (bypasses the cache). */
  reload: () => Promise<void>;
}

/**
 * The cached identity read as a hook (same shape as `useResource` / `useApi`). A cached value is
 * there on the first render (no loading flash); re-reads after this user's own changes update it.
 * `path === null` waits.
 */
export function useIdentity<T>(path: IdentityPath | null, opts: { handle?: Handle } = {}): IdentityResource<T> {
  const [data, setData] = useState<T | undefined>(() => (path ? peekIdentity<T>(path) : undefined));
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(() => path !== null && data === undefined);
  const seq = useRef(0);
  const handleKey = JSON.stringify(opts.handle ?? null);

  const load = useCallback(
    async (force: boolean) => {
      if (path === null) {
        setLoading(false);
        return;
      }
      const id = ++seq.current;
      const cached = force ? undefined : peekIdentity<T>(path);
      if (cached !== undefined) {
        setData(cached);
        setError(null);
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const handle = JSON.parse(handleKey) as Handle | null;
        const res = await getIdentity<T>(path, { force, handle: handle ?? undefined });
        if (id === seq.current) setData(res);
      } catch (err) {
        if (id === seq.current) setError(err);
      } finally {
        if (id === seq.current) setLoading(false);
      }
    },
    [path, handleKey],
  );

  useEffect(() => {
    void load(false);
    if (path === null) return;
    let set = listeners.get(path);
    if (!set) listeners.set(path, (set = new Set()));
    const onChange = () => {
      const v = entries.get(path)?.data as T | undefined;
      if (v !== undefined) setData(v);
    };
    set.add(onChange);
    return () => {
      set.delete(onChange);
    };
  }, [load, path]);

  const reload = useCallback(() => load(true), [load]);
  return { data, error, loading, reload };
}
