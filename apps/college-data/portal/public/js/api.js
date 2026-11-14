// Tech Drona portal — API client (owned by the UI shell agent; see CONTRACT.md)
//
//   api.get(path, params)                    -> JSON (throws ApiError)
//   api.post/patch/put(path, body, {idempotencyKey?}), api.del(path, {idempotencyKey?})
//     Writes always carry an `Idempotency-Key` header (a fresh UUID unless the caller passes one — a dialog passes the
//     same key for every retry of one submission, so a double click or a network retry never creates two records).
//     Key rules (F1): a key that got ANY HTTP answer other than 2xx is spent — reusing it sends a fresh key, so fixing a
//     field after a 409/400 and saving again is a new request. Only a network failure (no answer) keeps the key, so the
//     retry of that same body is de-duplicated by the server. A 422 "Idempotency-Key reused with a different request"
//     (v4.1 servers) is retried once with a fresh key.
//   ApiError {status, message, fields, data, code}  — data = full JSON body (e.g. 409 {existing_id, existing_name, college}).
//   Session (when the server supports it): api.session(), api.login(name, passcode), api.logout().
import { scopeParam } from './state.js';

export class ApiError extends Error {
  constructor(status, message, fields = {}, data = null) {
    super(message);
    this.status = status;
    this.fields = fields || {};
    this.data = data;
    this.code = data && data.code ? data.code : undefined;
  }
}

const USER_KEY = 'td.user';
const PASS_KEY = 'td.passcode';

function readLS(k) { try { return localStorage.getItem(k) || ''; } catch { return ''; } }
function writeLS(k, v) { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch { /* ignore */ } }

/** RFC 4122 v4 id (crypto.randomUUID needs a secure context; fall back to getRandomValues on plain http LAN hosts). */
export function newKey() {
  try { if (crypto.randomUUID) return crypto.randomUUID(); } catch { /* insecure context */ }
  const b = new Uint8Array(16);
  (crypto && crypto.getRandomValues ? crypto.getRandomValues(b) : b.forEach((_, i) => { b[i] = Math.floor(Math.random() * 256); }));
  b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
  const x = [...b].map((n) => n.toString(16).padStart(2, '0')).join('');
  return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
}

/**
 * Absolute URL of an API path, relative to the page: "/api/..." when the portal is served at "/" (standalone) and
 * "/college-portal/api/..." when the Tech Drona LMS serves it under /college-portal/ (document.baseURI = the page's directory).
 */
export function apiUrl(path) {
  return new URL('api' + (path.startsWith('/') ? path : '/' + path), document.baseURI);
}

function buildUrl(path, params) {
  const url = apiUrl(path);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, Array.isArray(v) ? v.join(',') : v);
    }
  }
  return url;
}

/** Human message for an HTTP failure; the server's own message wins when it is specific. */
function friendly(status, data, res) {
  const srv = data && (data.error || data.message);
  if (status === 401) return srv && !/^unauthori[sz]ed$/i.test(srv) ? srv : 'Please sign in again — your session has ended.';
  if (status === 403) return srv && !/^forbidden$/i.test(srv) ? srv : 'You have view-only access, so this change was not saved.';
  if (status === 409) return srv || 'This already exists or was changed by someone else. Reload and try again.';
  if (status === 429) {
    const ra = Number(res && res.headers && res.headers.get('Retry-After'));
    const wait = Number.isFinite(ra) && ra > 0 ? (ra >= 60 ? `${Math.ceil(ra / 60)} minute${ra >= 120 ? 's' : ''}` : `${ra} seconds`) : 'a few minutes';
    return srv && !/too many/i.test(srv) ? srv : `Too many attempts. Please wait ${wait} and try again.`;
  }
  if (status === 404) return srv || 'Not found — it may have been removed.';
  if (status >= 500) return 'The server had a problem saving or loading this. Try again; if it keeps happening, tell an admin.';
  return srv || (res && res.statusText) || `Request failed (${status})`;
}

/** Hooks the shell installs (session expiry, network state, rejected district scope). */
export const apiHooks = { onUnauthorized: null, onNetwork: null, onScopeRejected: null };

/** Keys that already got a non-2xx answer (F1): never send them again. */
const spentKeys = new Set();
const isKeyReuse = (status, data) => status === 422 && !!data && (data.code === 'idempotency_key_reused' || /idempotency/i.test(String(data.error || data.message || '')));

async function request(method, path, body, params, opts = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (api.user) headers['X-User'] = encodeURIComponent(api.user);
  const pass = readLS(PASS_KEY);
  if (pass && api.mode !== 'session') headers['X-Passcode'] = pass;
  let key = null;
  if (method !== 'GET') {
    key = opts.idempotencyKey && !spentKeys.has(opts.idempotencyKey) ? opts.idempotencyKey : newKey();
    headers['Idempotency-Key'] = key;
  }
  let res;
  try {
    res = await fetch(buildUrl(path, params), {
      method, headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    if (apiHooks.onNetwork) apiHooks.onNetwork(false);
    throw new ApiError(0, 'Cannot reach the server. Check your connection, then try again.');
  }
  if (apiHooks.onNetwork) apiHooks.onNetwork(true);
  let data = null;
  const text = await res.text();
  if (text) { try { data = JSON.parse(text); } catch { data = { error: text.slice(0, 300) }; } }
  if (!res.ok) {
    if (key) spentKeys.add(key);
    if (key && isKeyReuse(res.status, data) && !opts.keyRetried) {
      return request(method, path, body, params, { ...opts, idempotencyKey: newKey(), keyRetried: true });
    }
    const err = new ApiError(res.status, friendly(res.status, data, res), (data && data.fields) || {}, data);
    if (res.status === 401 && apiHooks.onUnauthorized && !opts.noAuthHook) apiHooks.onUnauthorized(err, { method, path });
    throw err;
  }
  return data;
}

export const api = {
  user: readLS(USER_KEY),
  /** 'legacy' (typed name + optional X-Passcode) or 'session' (cookie login). Set by the shell after GET /api/session. */
  mode: 'legacy',
  setUser(name) { this.user = (name || '').trim(); writeLS(USER_KEY, this.user); },
  setPasscode(p) { writeLS(PASS_KEY, p || ''); },
  hasPasscode() { return !!readLS(PASS_KEY); },
  get: (path, params) => request('GET', path, undefined, params),
  post: (path, body, opts) => request('POST', path, body ?? {}, undefined, opts),
  patch: (path, body, opts) => request('PATCH', path, body ?? {}, undefined, opts),
  put: (path, body, opts) => request('PUT', path, body ?? {}, undefined, opts),
  del: (path, opts) => request('DELETE', path, undefined, undefined, opts),
  newKey,
  /** GET /api/session → {required, authenticated, role, user} | null when the server has no session support (404). */
  async session() {
    try { return await request('GET', '/session', undefined, undefined, { noAuthHook: true }); } catch (e) {
      if (e && (e.status === 404 || e.status === 405)) return null;
      if (e && e.status === 401) return { required: true, authenticated: false, role: null, user: null, ...(e.data || {}) };
      throw e;
    }
  },
  login: (name, passcode) => request('POST', '/session', { name, passcode }, undefined, { noAuthHook: true }),
  logout: () => request('DELETE', '/session', undefined, undefined, { noAuthHook: true }),
  /** GET with the global district scope appended as `districts=` (omitted when "All districts"); explicit params win.
   *  If the server rejects the scope (400 on districts=), the page must NOT silently show whole-state numbers under a
   *  district chip (F8): the error is rethrown with code 'scope_rejected' and the shell shows a banner to reset the scope. */
  async getScoped(path, params = {}) {
    const d = scopeParam();
    try { return await api.get(path, { districts: d, ...params }); } catch (e) {
      if (d && e && e.status === 400 && ((e.fields && e.fields.districts) || /district/i.test(e.message || ''))) {
        const err = new ApiError(400, `The selected districts could not be used (${e.message}). Choose the districts again or reset the scope.`, e.fields, { ...(e.data || {}), code: 'scope_rejected' });
        if (apiHooks.onScopeRejected) { try { apiHooks.onScopeRejected(err, { path, districts: d }); } catch { /* ignore */ } }
        throw err;
      }
      throw e;
    }
  },
};

export default api;
