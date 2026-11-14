// Tech Drona portal — shared UI state (owned by the UI shell agent; see CONTRACT.md)
//

/* The retired global Filters drawer (UI-16 / F14) and its sessionStorage filter state were removed: every page now has
   its own filter bar with the state in the URL. */
export const state = {
  /** /api/meta payload once loaded ({districts, cities, courses, settings, counts, demo}) */
  meta: null,
  /** last /api/colleges rows loaded by the shell for the map */
  colleges: null,
  /** current route info {path, name, params} */
  route: null,
};
try { sessionStorage.removeItem('td.filters'); } catch { /* ignore */ }

export default state;

/* =========================================================================
   District scope (global): which districts the map, overview and calling queue show.
   Default = the three target districts (old, undivided Guntur / Krishna / West Godavari = 7 present-day ids).
   Persisted in localStorage 'td.districtScope' ('all' or a JSON id list); may also be set by a `?d=` hash query.
   Changes are broadcast as window event 'td:district-scope' ({detail: {ids|null, all, isDefault}}).
   ========================================================================= */
export const SCOPE_EVENT = 'td:district-scope';
const SCOPE_KEY = 'td.districtScope';
/** Built-in fallback until GET /api/program answers (same values the backend seeds into settings). */
export const DEFAULT_TARGET_GROUPS = {
  Guntur: ['guntur', 'palnadu', 'bapatla'],
  Krishna: ['krishna', 'ntr'],
  'West Godavari': ['west-godavari', 'eluru'],
};
/** /api/program payload ({target, deadline, target_district_groups, target_district_ids, districts[]}) or null. */
state.program = null;
/** false when /api/program is not available on this server (older build) — the UI falls back to defaults. */
state.programAvailable = null;

export function targetGroups() {
  const g = state.program && state.program.target_district_groups;
  return g && typeof g === 'object' && Object.keys(g).length ? g : DEFAULT_TARGET_GROUPS;
}
export function targetDistrictIds() {
  const p = state.program && Array.isArray(state.program.target_district_ids) && state.program.target_district_ids.length ? state.program.target_district_ids : null;
  return p ? [...p] : Object.values(targetGroups()).flat();
}
/** group name for a present-day district id, or null */
export function targetGroupOf(id) {
  for (const [name, ids] of Object.entries(targetGroups())) if (ids.includes(id)) return name;
  return null;
}

function loadScope() {
  try {
    const raw = localStorage.getItem(SCOPE_KEY);
    if (!raw) return null; // default
    if (raw === 'all') return 'all';
    const ids = JSON.parse(raw);
    return Array.isArray(ids) && ids.length ? ids.filter((x) => typeof x === 'string') : null;
  } catch { return null; }
}
/** null = default (target districts), 'all', or an explicit id list */
let scopeSel = loadScope();

const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

/** Current selection: {all, ids (null when all), isDefault} */
export function getScope() {
  if (scopeSel === 'all') return { all: true, ids: null, isDefault: false };
  const ids = scopeSel ? [...scopeSel] : targetDistrictIds();
  return { all: false, ids, isDefault: !scopeSel || sameSet(ids, targetDistrictIds()) };
}
/** Value for the `districts=` query param ('' / undefined = no filter, i.e. all districts). */
export function scopeParam() {
  const s = getScope();
  return s.all ? undefined : s.ids.join(',');
}
/** true when the district is inside the current scope (all → always). */
export function inScope(districtId) {
  const s = getScope();
  return s.all || s.ids.includes(districtId);
}
/** Client-side fallback filter (for servers that ignore `districts=`). */
export function scopeRows(rows, key = 'district_id') {
  const s = getScope();
  if (s.all || !Array.isArray(rows)) return rows;
  const set = new Set(s.ids);
  return rows.filter((r) => !r || r[key] === undefined || r[key] === null ? true : set.has(r[key]));
}

function emitScope() {
  const s = getScope();
  try { window.dispatchEvent(new CustomEvent(SCOPE_EVENT, { detail: s })); } catch { /* ignore */ }
}
/** setDistrictScope('all' | 'default' | null | string[]) */
export function setDistrictScope(v, { silent = false } = {}) {
  let next;
  if (v === 'all') next = 'all';
  else if (v === null || v === undefined || v === 'default' || v === 'target') next = null;
  else {
    const ids = [...new Set((Array.isArray(v) ? v : String(v).split(',')).map((x) => String(x).trim()).filter(Boolean))];
    next = !ids.length || sameSet(ids, targetDistrictIds()) ? null : ids;
  }
  const before = JSON.stringify(scopeSel);
  scopeSel = next;
  try {
    if (next === null) localStorage.removeItem(SCOPE_KEY);
    else localStorage.setItem(SCOPE_KEY, next === 'all' ? 'all' : JSON.stringify(next));
  } catch { /* private mode */ }
  if (!silent && before !== JSON.stringify(scopeSel)) emitScope();
  return before !== JSON.stringify(scopeSel);
}
export function resetDistrictScope() { return setDistrictScope(null); }
/** Serialised form for the `?d=` hash query: 'all', 'target' or comma ids. */
export function scopeQueryValue() {
  const s = getScope();
  return s.all ? 'all' : s.isDefault ? 'target' : s.ids.join(',');
}

const districtNameOf = (id) => {
  const d = (state.meta && (state.meta.districts || []).find((x) => x.id === id)) || (state.program && (state.program.districts || []).find((x) => x.id === id));
  return d ? d.name : String(id).replace(/-/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
};
/** Human label: "Guntur · Krishna · West Godavari", "All districts", "Guntur · NTR" … (whole groups use the old name). */
export function scopeLabel({ max = 4 } = {}) {
  const s = getScope();
  if (s.all) return 'All districts';
  const left = new Set(s.ids);
  const parts = [];
  for (const [name, ids] of Object.entries(targetGroups())) {
    if (ids.length && ids.every((x) => left.has(x))) { parts.push(name); ids.forEach((x) => left.delete(x)); }
  }
  for (const id of s.ids) if (left.has(id)) parts.push(districtNameOf(id));
  if (!parts.length) return 'No districts';
  return parts.length > max ? `${parts.slice(0, max - 1).join(' · ')} +${parts.length - (max - 1)} more` : parts.join(' · ');
}

state.getScope = getScope;
state.scopeParam = scopeParam;
state.setDistrictScope = setDistrictScope;

/* =========================================================================
   Session (set by the shell after GET /api/session).
   mode 'legacy' = no login on this server (typed name + optional passcode); 'session' = cookie login.
   role 'viewer' = read-only: write controls are hidden (body.td-readonly) and the server refuses writes (403).
   sso = true when the Tech Drona LMS signs the user in (portal served under /college-portal/ behind the LMS proxy):
   no passcode screen; login_url is where the top window goes when the LMS session has ended.
   ========================================================================= */
state.session = { mode: 'legacy', role: null, user: null, required: false, sso: false, login_url: null };
export const SESSION_EVENT = 'td:session';
/** false only for read-only (viewer) sessions. */
export function canWrite() { return state.session.role !== 'viewer'; }
export function setSession(s) {
  state.session = { ...state.session, ...s };
  try { document.body.classList.toggle('td-readonly', !canWrite()); } catch { /* no DOM */ }
  try { window.dispatchEvent(new CustomEvent(SESSION_EVENT, { detail: state.session })); } catch { /* ignore */ }
}
state.canWrite = canWrite;
