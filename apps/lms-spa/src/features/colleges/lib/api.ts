/**
 * Typed client for the College Data Portal API, called from the browser at `/college-portal/api/*`.
 *
 *   browser ──fetch──▶ Hosting `/college-portal/**` ──▶ lmsApi (functions-lms/lms_edge/college_portal.py)
 *          ──▶ Cloud Run `college-portal` (apps/college-data/portal/server/server.js, unchanged)
 *
 * The proxy signs the LMS admin in server-side (LMS session cookie → `x-td-proxy-user` + shared secret), so this
 * client sends NO credentials of its own: same-origin cookies only. Constraints the proxy imposes (see the
 * PORTING-GUIDE "API and proxy constraints"):
 *  - methods GET, HEAD, POST, PATCH, PUT, DELETE; request bodies ≤ 1 MiB; 15 s upstream timeout;
 *  - only these request headers reach the server: accept, content-type, idempotency-key, if-modified-since,
 *    if-none-match, user-agent (so no X-User / X-Passcode: the actor is the LMS user);
 *  - unsafe methods must be same-origin (Origin / Sec-Fetch-Site checked) — a same-origin fetch is;
 *  - 401 {code:'auth_required'} = the LMS session ended → LMS sign-in; 403 {code:'forbidden'} = not an LMS admin;
 *    503 {code:'auth_unavailable'} = the LMS could not check access (retry).
 *
 * Writes carry an `Idempotency-Key` (port of the old js/api.js rule F1): a key that got any HTTP answer other than
 * 2xx is spent; only a network failure keeps it, so the retry of the same body is de-duplicated by the server.
 */
import { getScope, scopeParam } from "./scope";

export const PORTAL_API_BASE = "/college-portal/api";

/** Where the LMS sends a signed-out user (back to the page they were on). */
export function lmsLoginUrl(here: string = currentPath()): string {
  const next = here.startsWith("/") && !here.startsWith("//") ? here : "/colleges";
  return `/login?next=${encodeURIComponent(next)}`;
}

function currentPath(): string {
  if (typeof window === "undefined") return "/colleges";
  return `${window.location.pathname}${window.location.search}`;
}

export type QueryValue = string | number | boolean | null | undefined | readonly (string | number)[];
export type Query = Record<string, QueryValue>;

/** Error of a portal request. `status` 0 = network failure (no answer). */
export class PortalApiError extends Error {
  readonly status: number;
  /** Field → message map from a 400 (shown under the matching form inputs). */
  readonly fields: Record<string, string>;
  /** The full JSON body (e.g. a 409 `{existing_id, existing_name}`). */
  readonly data: Record<string, unknown> | null;
  /** Machine code: the server's `code`, or 'scope_rejected' (districts filter refused), 'network'. */
  readonly code: string | undefined;

  constructor(status: number, message: string, fields: Record<string, string> = {}, data: Record<string, unknown> | null = null, code?: string) {
    super(message);
    this.name = "PortalApiError";
    this.status = status;
    this.fields = fields;
    this.data = data;
    this.code = code ?? (typeof data?.code === "string" ? data.code : undefined);
  }

  /** The LMS session ended (proxy 401). */
  get isSignedOut(): boolean {
    return this.status === 401;
  }
  /** Not an LMS admin (proxy 403 `forbidden`) — not the portal's own 403 `read_only`. */
  get isAdminsOnly(): boolean {
    return this.status === 403 && (this.code === "forbidden" || this.code === undefined);
  }
}

export function isPortalApiError(e: unknown): e is PortalApiError {
  return e instanceof PortalApiError;
}

/** Human message for an HTTP failure; the server's own message wins when it is specific (old api.js `friendly`). */
export function friendlyMessage(status: number, data: Record<string, unknown> | null, retryAfter?: string | null): string {
  const raw = data && (data.error ?? data.message);
  const srv = typeof raw === "string" && raw.trim() ? raw : null;
  const code = typeof data?.code === "string" ? data.code : undefined;
  if (status === 0) return "Cannot reach the server. Check your connection, then try again.";
  if (status === 401) return "Your Tech Drona LMS session has ended. Please sign in again.";
  if (status === 403) {
    if (code === "forbidden") return "The College Data Portal is available to LMS admins only.";
    if (code === "cross_origin") return "This request was blocked because it did not come from the portal page. Reload the page and try again.";
    return srv && !/^forbidden$/i.test(srv) ? srv : "You have view-only access, so this change was not saved.";
  }
  if (status === 409) return srv || "This already exists or was changed by someone else. Reload and try again.";
  if (status === 429) {
    const ra = Number(retryAfter);
    const wait = Number.isFinite(ra) && ra > 0 ? (ra >= 60 ? `${Math.ceil(ra / 60)} minute${ra >= 120 ? "s" : ""}` : `${ra} seconds`) : "a few minutes";
    return srv && !/too many/i.test(srv) ? srv : `Too many attempts. Please wait ${wait} and try again.`;
  }
  if (status === 503 && code === "auth_unavailable") return "We could not check your access right now. Please try again in a moment.";
  if (status === 404) return srv || "Not found — it may have been removed.";
  if (status >= 500) return "The server had a problem saving or loading this. Try again; if it keeps happening, tell an admin.";
  return srv || `Request failed (${status})`;
}

/* ------------------------------------------------------------------ hooks (tests, shell) */

export interface PortalApiHooks {
  fetchImpl?: typeof fetch;
  /** 401: default = full page load to the LMS sign-in with ?next=<current path>. */
  onSignedOut?: (err: PortalApiError) => void;
  /** Network state changes (true = an answer arrived, false = no answer). The shell shows the offline banner. */
  onNetwork?: (online: boolean) => void;
  /** The server refused the district scope (400 on `districts=`). The shell shows the "Reset districts" banner. */
  onScopeRejected?: (err: PortalApiError) => void;
}

let hooks: PortalApiHooks = {};

/** Install hooks; returns a function restoring the previous ones. */
export function configurePortalApi(next: PortalApiHooks): () => void {
  const prev = hooks;
  hooks = { ...hooks, ...next };
  return () => {
    hooks = prev;
  };
}

function signedOut(err: PortalApiError): void {
  if (hooks.onSignedOut) hooks.onSignedOut(err);
  else if (typeof window !== "undefined") window.location.assign(lmsLoginUrl());
}

/* ------------------------------------------------------------------ requests */

/** RFC 4122 v4 id (crypto.randomUUID needs a secure context; fall back to getRandomValues). */
export function newIdempotencyKey(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  } catch {
    /* insecure context */
  }
  const b = new Uint8Array(16);
  if (typeof crypto !== "undefined" && crypto.getRandomValues) crypto.getRandomValues(b);
  else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  b[6] = (b[6]! & 0x0f) | 0x40;
  b[8] = (b[8]! & 0x3f) | 0x80;
  const x = [...b].map((n) => n.toString(16).padStart(2, "0")).join("");
  return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
}

/** `/college-portal/api/<path>?<query>`; arrays join with commas; null / undefined / '' are dropped. */
export function portalUrl(path: string, query?: Query): string {
  const clean = path.replace(/^\/+/, "").replace(/^api\//, "");
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v === undefined || v === null || v === "") continue;
    qs.set(k, Array.isArray(v) ? v.join(",") : String(v));
  }
  const s = qs.toString().replace(/%2C/gi, ",");
  return `${PORTAL_API_BASE}/${clean}${s ? `?${s}` : ""}`;
}

export interface WriteOptions {
  /** Reuse one key for every retry of ONE logical submission (FormDialog does). Default: a fresh key. */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export interface GetOptions {
  query?: Query;
  /** Add the global district scope as `districts=` (omitted for "All districts"); an explicit query value wins. */
  scoped?: boolean;
  signal?: AbortSignal;
}

/** Keys that already got a non-2xx answer (F1): never sent again. */
const spentKeys = new Set<string>();
const isKeyReuse = (status: number, data: Record<string, unknown> | null) =>
  status === 422 && !!data && (data.code === "idempotency_key_reused" || /idempotency/i.test(String(data.error ?? data.message ?? "")));

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

async function request<T>(method: Method, url: string, body: unknown, opts: WriteOptions & { keyRetried?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  let key: string | null = null;
  if (method !== "GET") {
    key = opts.idempotencyKey && !spentKeys.has(opts.idempotencyKey) ? opts.idempotencyKey : newIdempotencyKey();
    headers["idempotency-key"] = key;
  }
  let res: Response;
  try {
    res = await (hooks.fetchImpl ?? globalThis.fetch)(url, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as { name?: string })?.name === "AbortError") throw e;
    hooks.onNetwork?.(false);
    throw new PortalApiError(0, friendlyMessage(0, null), {}, null, "network");
  }
  hooks.onNetwork?.(true);
  let data: Record<string, unknown> | null = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text) as Record<string, unknown>;
    } catch {
      data = { error: text.slice(0, 300) };
    }
  }
  if (!res.ok) {
    if (key) spentKeys.add(key);
    if (key && isKeyReuse(res.status, data) && !opts.keyRetried) {
      return request<T>(method, url, body, { ...opts, idempotencyKey: newIdempotencyKey(), keyRetried: true });
    }
    const fields = data && typeof data.fields === "object" && data.fields ? (data.fields as Record<string, string>) : {};
    const err = new PortalApiError(res.status, friendlyMessage(res.status, data, res.headers.get("retry-after")), fields, data);
    if (res.status === 401) signedOut(err);
    throw err;
  }
  return data as T;
}

async function getJson<T>(path: string, opts: GetOptions = {}): Promise<T> {
  const query: Query = opts.scoped ? { districts: scopeParam(), ...opts.query } : { ...opts.query };
  try {
    return await request<T>("GET", portalUrl(path, query), undefined, { signal: opts.signal });
  } catch (e) {
    // F8: never silently show whole-state numbers under a district chip when the server refuses the scope.
    const d = query.districts;
    if (opts.scoped && d && isPortalApiError(e) && e.status === 400 && (e.fields.districts || /district/i.test(e.message))) {
      const err = new PortalApiError(
        400,
        `The selected districts could not be used (${e.message}). Choose the districts again or reset the scope.`,
        e.fields,
        e.data,
        "scope_rejected",
      );
      hooks.onScopeRejected?.(err);
      throw err;
    }
    throw e;
  }
}

/** Writes change rollups everywhere: every successful write clears the read cache (lib/cache.ts listens). */
const writeListeners = new Set<() => void>();
export function onPortalWrite(fn: () => void): () => void {
  writeListeners.add(fn);
  return () => writeListeners.delete(fn);
}

async function write<T>(method: Exclude<Method, "GET">, path: string, body: unknown, opts?: WriteOptions): Promise<T> {
  const out = await request<T>(method, portalUrl(path), body, opts);
  for (const l of writeListeners) l();
  return out;
}

/**
 * The portal API. Paths are relative to `/college-portal/api/` ("colleges", "colleges/c9", "/people").
 * Reads in components should go through `usePortalQuery` (lib/cache.ts): de-duplicated and cached.
 */
export const portalApi = {
  get: <T>(path: string, opts?: GetOptions) => getJson<T>(path, opts),
  post: <T>(path: string, body: unknown = {}, opts?: WriteOptions) => write<T>("POST", path, body, opts),
  patch: <T>(path: string, body: unknown = {}, opts?: WriteOptions) => write<T>("PATCH", path, body, opts),
  put: <T>(path: string, body: unknown = {}, opts?: WriteOptions) => write<T>("PUT", path, body, opts),
  del: <T>(path: string, opts?: WriteOptions) => write<T>("DELETE", path, undefined, opts),
  newKey: newIdempotencyKey,
  /** current `districts=` value (undefined = all) — for links and CSV file names */
  scopeParam,
  getScope,
};

/** Tests only. */
export function resetPortalApiForTests(): void {
  spentKeys.clear();
  hooks = {};
}
