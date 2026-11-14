// Tech Drona portal: Home (#/), Colleges list (#/colleges) and Reports (#/analytics) — owned by CL (colleges + home).
// Every number comes from the API; the UI never recomputes rollups. Unknown values render as "—" + Pending.
// The global district scope applies everywhere (api.getScoped adds `districts=`; scopeRows is the client fallback).
// New v4 endpoints (/api/performance, colleges `team=`, people `assignment=`) are feature-detected: when the server
// does not provide them yet the page says so instead of inventing numbers.
import { h, fmt, daysUntil, debounce, today } from '../ui/h.js';
import { barChart, lineChart, columnChart, paceMeter, funnel, progressRing, emptyChart } from '../ui/charts.js';
import { getScope, scopeLabel, scopeRows, inScope, targetDistrictIds, targetGroups } from '../state.js';
import { telLink, logCall, callStatusBadge, contactLabel } from './forms.js';
import { downloadCsv, STATUS_META, statusMeta, historyMode } from '../ui/components.js';

/** GET with the global district scope (`districts=`); falls back to a plain GET on older api.js builds. */
export const getScoped = (ctx, path, params) => (typeof ctx.api.getScoped === 'function' ? ctx.api.getScoped(path, params) : ctx.api.get(path, params));
/** Inline "Change districts" button that opens the header picker. */
export function scopeChangeBtn(ctx, label = 'Change districts') {
  if (typeof ctx.openDistrictScope !== 'function') return null;
  return h('button', { type: 'button', class: 'vd-linkbtn vd-scope-change', onClick: (e) => ctx.openDistrictScope(e.currentTarget) }, label);
}
/** Scope pill shown in page headers: "Districts: Guntur · Krishna · West Godavari  Change". */
export function scopePill(ctx) {
  const sc = getScope();
  return h('span', { class: 'vd-scopepill td-hide-phone' }, ctx.ui.icon('map', { size: 14 }),
    h('span', null, sc.all ? 'All districts' : scopeLabel({ max: 3 })), scopeChangeBtn(ctx, 'Change'));
}

/** 'phone' | 'tablet' | 'desktop' from the shell (responsive.md §1); falls back to the <html data-form> attribute / width. */
export function formFactor(ctx) {
  try { if (ctx && ctx.ui && typeof ctx.ui.formFactor === 'function') return ctx.ui.formFactor(); } catch { /* fall back */ }
  const f = document.documentElement.dataset.form;
  if (f) return f;
  return innerWidth < 700 ? 'phone' : innerWidth < 1280 ? 'tablet' : 'desktop';
}
export const isPhone = (ctx) => formFactor(ctx) === 'phone';
export function scrollBehavior(ctx) {
  const reduce = ctx && ctx.ui && typeof ctx.ui.prefersReducedMotion === 'function' ? ctx.ui.prefersReducedMotion()
    : typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  return reduce ? 'auto' : 'smooth';
}
/** Run fn on every form-factor change while `node` is in the document (removes itself afterwards). */
export function onFormFactor(node, fn) {
  const handler = (e) => { if (!node.isConnected) { removeEventListener('td:formfactor', handler); return; } fn(e && e.detail); };
  addEventListener('td:formfactor', handler);
}

/* =====================================================================================
 * Shared helpers (also used by geo.js and college.js)
 * ===================================================================================== */
const VIEW_CLASSES = ['v-dashboard', 'v-geo', 'v-analytics', 'v-colleges'];
let cleanups = [];

export function mount(el, cls, ...kids) {
  runCleanups();
  VIEW_CLASSES.forEach((c) => el.classList.remove(c));
  el.classList.add(cls);
  el.replaceChildren(...kids.flat().filter(Boolean));
}
/** replaceChildren that skips null/false (replaceChildren would print "null"). */
export const put = (host, ...kids) => host.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
export function onCleanup(fn) { if (typeof fn === 'function') cleanups.push(fn); }
function runCleanups() { const c = cleanups; cleanups = []; c.forEach((fn) => { try { fn(); } catch { /* ignore */ } }); }
export function destroy() { runCleanups(); }

export const loading = (text = 'Loading…') => h('div', { class: 'vd-loading', role: 'status' }, h('span', { class: 'vd-spinner', 'aria-hidden': 'true' }), text);

export async function fetchAll(map) {
  const keys = Object.keys(map);
  const res = await Promise.allSettled(keys.map((k) => map[k]));
  const data = {}, errors = {};
  res.forEach((r, i) => { if (r.status === 'fulfilled') data[keys[i]] = r.value; else errors[keys[i]] = r.reason; });
  return { data, errors };
}
export const errorNote = (err, what = 'this section') => h('div', { class: 'vd-error', role: 'alert' },
  `Could not load ${what}. `, h('span', { class: 'vd-muted' }, (err && err.message) || ''));

export function setCrumbs(ctx, crumbs) { if (typeof ctx.setBreadcrumb === 'function') ctx.setBreadcrumb(crumbs); }

export const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
export const rowId = (r) => r.id ?? r.scope_id ?? r.key;
export const rowLabel = (r) => r.label ?? r.name ?? r.full_name ?? String(rowId(r));
/** Rows from a list endpoint that may return either an array (v3) or {items,total} (v4 paged). */
export const itemsOf = (res) => (Array.isArray(res) ? res : res && Array.isArray(res.items) ? res.items : []);

/* ---------- one formatting rule for every page (TG-13) ---------- */
/** fraction (0.0475) -> "4.8%" — the ONE shared rule (fmt.pctOf / fmt.pctPts in ui/h.js). */
export function pctText(x) { return fmt.pctOf(x); }
/** percent number from /api/performance (4.8) -> "4.8%". */
export const pctNumText = (p) => fmt.pctPts(p);
/**
 * D2 (v4.1): the programme target covers only the programme's target districts. When the district selection does not
 * include them the server sends target null + a reason; older servers always send the target. Returns the reason or null.
 */
export function noTargetReason(...objs) {
  for (const o of objs) {
    if (!o || typeof o !== 'object') continue;
    // top level: the selection's own (rolled-up) target is null and the server says why
    if (o.target === null && o.target_reason) return String(o.target_reason);
    const p = o.program && typeof o.program === 'object' ? o.program : null;
    if (p && p.target === null && p.target_reason && (o.target === null || o.target === undefined)) return String(p.target_reason);
  }
  return null;
}
/** true when /api/target-dashboard says the programme target does not apply to this district selection (v4.1). */
export const programmeNA = (T) => !!(T && T.program && (T.program.applies === false || (T.program.target === null && T.program.target_reason)));
/** rates (per week / per day): 1 decimal below 10, whole above. */
export const rateText = (x) => (x === null || x === undefined || !Number.isFinite(Number(x)) ? '—' : x >= 10 ? fmt.num(x) : (Math.round(x * 10) / 10).toLocaleString('en-IN'));
/** days left always comes from the API (inclusive of today). */
export function daysLeftText(daysLeft, deadline) {
  if (isNum(daysLeft)) {
    if (daysLeft <= 0) return `Deadline passed${deadline ? ` (${fmt.date(deadline)})` : ''}`;
    return `${fmt.plural(daysLeft, 'day')} left incl. today${deadline ? ` · deadline ${fmt.date(deadline)}` : ''}`;
  }
  return deadline ? `Deadline ${fmt.date(deadline)}` : 'No deadline set';
}
/** Deadline line when the API gives no days_left: only the date (never a browser-computed count). */
export function deadlineText(deadline, daysLeft) { return daysLeftText(daysLeft, deadline); }

/** {value, basis} → node with provenance; missing → "—" + Pending. */
export function withBasis(ctx, obj, f = fmt.num) {
  const o = obj && typeof obj === 'object' ? obj : { value: isNum(obj) ? obj : null, basis: isNum(obj) ? null : 'pending' };
  if (o.value === null || o.value === undefined) return ctx.ui.valueWithBasis({ value: null, basis: 'pending' }, f);
  return ctx.ui.valueWithBasis(o, f);
}

/** Stat card that never shows 0 for an unknown: null → "—" with a Pending basis. */
export function kpi(ctx, { label, value, basis, sub, tone, icon, href, onClick, format = fmt.num, notSet }) {
  const unknown = value === null || value === undefined || (typeof value === 'number' && Number.isNaN(value));
  return ctx.ui.statCard({
    label, icon, tone,
    sub: unknown && notSet ? notSet : sub,
    value: unknown ? '—' : format(value),
    basis: unknown ? (notSet ? undefined : 'pending') : (basis || undefined),
    onClick: onClick || (href ? () => ctx.navigate(href) : undefined),
  });
}
export const kpiB = (ctx, label, obj, extra = {}) => kpi(ctx, { label, value: obj ? obj.value : null, basis: obj ? obj.basis : 'pending', ...extra });

/* ---------- performance status (R10) ---------- */
// labels + tones from the ONE shared vocabulary (ui/components.js STATUS_META — F12)
export const PERF_STATUS = Object.fromEntries(['no_target', 'zero_target', 'too_early', 'partial_target', 'behind', 'on_track', 'met', 'exceeded']
  .map((k) => [k, [STATUS_META[k].label, STATUS_META[k].tone]]));
export function perfChip(ctx, status) {
  if (!status) return null;
  if (typeof ctx.ui.statusChip === 'function') { try { const n = ctx.ui.statusChip(status); if (n) return n; } catch { /* fall back */ } }
  const m = statusMeta(status);
  return ctx.ui.badge(m.label, m.tone);
}
/** "12 to go" / "Exceeded by 2" / "Target met" from server remaining + exceeded_by (or remaining only on v3 rows). */
export function remainingText(r) {
  if (!r || r.target === null || r.target === undefined) return null;
  if (isNum(r.exceeded_by) && r.exceeded_by > 0) return `Exceeded by ${fmt.num(r.exceeded_by)}`;
  if (isNum(r.remaining)) return r.remaining > 0 ? `${fmt.num(r.remaining)} to go` : 'Target met';
  return null;
}

/* ---------- /api/performance (v4) — feature-detected once per session ---------- */
let perfSupported = null; // null = unknown, true/false after the first call
export async function getPerformance(ctx, params = {}, { scoped = true } = {}) {
  if (perfSupported === false) return null;
  try {
    const res = scoped ? await getScoped(ctx, '/performance', params) : await ctx.api.get('/performance', params);
    perfSupported = true;
    return res;
  } catch (e) {
    if (e && (e.status === 404 || e.status === 405 || e.status === 501)) { perfSupported = false; return null; }
    throw e;
  }
}
export const perfRows = (res) => (res ? (Array.isArray(res) ? res : res.rows || res.items || []) : []);

/** Target / enrolled progress for any row/summary with {target, enrolled|actual, remaining}. */
export function progressNode(ctx, r, { size = 'sm' } = {}) {
  const actual = r ? (r.actual ?? r.actual_combined ?? r.enrolled) : null;
  if (!r || !(r.target > 0)) {
    return h('span', { class: 'vd-noprog' }, h('span', { class: 'vd-muted' }, r && r.target === 0 ? STATUS_META.zero_target.label : STATUS_META.no_target.label),
      isNum(actual) && actual > 0 ? h('span', null, ` · ${fmt.num(actual)} confirmed`) : null);
  }
  const rt = remainingText(r);
  return h('div', { class: 'vd-prog' },
    ctx.ui.progress({ target: r.target, done: actual ?? 0, size }),
    rt ? h('span', { class: 'vd-muted vd-small' }, rt) : null);
}

/** status chip (v4 status, else on-track + diagnosis), or "No target". */
export function statusNode(ctx, r) {
  const st = r && (r.status || r.pace_status);
  if (st && PERF_STATUS[st]) return perfChip(ctx, st);
  if (!r || !(r.target > 0)) return ctx.ui.badge(r && r.target === 0 ? STATUS_META.zero_target.label : STATUS_META.no_target.label, 'neutral');
  return h('span', { class: 'vd-status' }, ctx.ui.statusBadge('on_track', r.on_track),
    r.on_track === false && r.diagnosis ? ctx.ui.statusBadge('diagnosis', r.diagnosis) : null);
}

/** Lead name of a /api/colleges row: v4 `lead{id,name,phone}` or v3 `college_lead` (name string). */
export function leadOf(r) {
  if (r && r.lead && typeof r.lead === 'object') return { id: r.lead.id, name: r.lead.name || r.lead.full_name, phone: r.lead.phone || null };
  const l = r && r.college_lead;
  if (!l) return null;
  if (typeof l === 'object') return { id: l.id, name: l.full_name || l.name, phone: l.phone || null };
  return { id: r.college_lead_id ?? null, name: String(l), phone: null };
}
export const ambCount = (r) => (isNum(r.ambassador_count) ? r.ambassador_count : (r.ambassadors ?? 0));

export function leadsNode(ctx, r) {
  const lead = leadOf(r);
  return h('div', { class: 'vd-leads' },
    lead ? h('span', { class: 'vd-lead-name' }, lead.name) : ctx.ui.badge('No lead', 'warn'),
    h('span', { class: 'vd-muted' }, `${fmt.plural(r.ambassador_leads ?? 0, 'amb. lead')} · ${fmt.plural(ambCount(r), 'ambassador')}`),
    r.branches_needing_ambassadors > 0 ? ctx.ui.badge(`${fmt.plural(r.branches_needing_ambassadors, 'branch', 'branches')} need${r.branches_needing_ambassadors === 1 ? 's' : ''} ambassadors`, 'warn') : null);
}

export function nextFollowupNode(r) {
  const f = r.next_followup;
  if (!f) return h('span', { class: 'vd-muted' }, r.followups_open ? `${fmt.num(r.followups_open)} open` : '—');
  const date = typeof f === 'object' ? f.due_date : f;
  const overdue = typeof f === 'object' && f.overdue !== undefined ? !!f.overdue : (daysUntil(date) ?? 0) < 0;
  return h('span', { class: ['vd-fu', overdue && 'is-overdue'], title: typeof f === 'object' && f.title ? f.title : null },
    fmt.date(date), overdue ? h('span', { class: 'vd-small' }, ' · overdue') : null);
}

export function examNode(ctx, r) {
  const ne = r.next_exam;
  return h('div', { class: 'vd-exam' }, ctx.ui.statusBadge('exam_state', r.exam_state || 'unknown'),
    ne && ne.start ? h('div', { class: 'vd-muted vd-small' }, `${ne.semester || ''} ${ne.kind || ''} ${ne.start <= today() && ne.end ? `ends ${fmt.date(ne.end)}` : fmt.date(ne.start)}`.trim()) : null);
}

/** URL segment for a city: the full city id (matches the server's hrefs, e.g. #/d/guntur/guntur--tenali). */
export function citySlug(districtId, cityId) { return String(cityId); }
const cityShort = (districtId, cityId) => { const p = `${districtId}--`; return String(cityId).startsWith(p) ? String(cityId).slice(p.length) : String(cityId); };
export { cityShort };
export function cityIdFrom(districtId, param) {
  const s = decodeURIComponent(String(param || ''));
  return s.includes('--') ? s : `${districtId}--${s}`;
}

export function hrefFor(level, r) {
  if (r.href) return r.href;
  const id = rowId(r);
  switch (level) {
    case 'district': return `#/d/${id}`;
    case 'city': { const did = r.district_id || String(id).split('--')[0]; return `#/d/${did}/${citySlug(did, id)}`; }
    case 'college': return `#/college/${id}`;
    case 'branch': return r.college_id ? `#/college/${r.college_id}?tab=branches&branch=${id}` : null;
    case 'person': return `#/person/${id}`;
    default: return null;
  }
}

const sectionEl = (ctx, title, body, actions, sub) => ctx.ui.section({ title, actions, body, sub });

/** Server reason strings carry ISO dates ("Exams start 2026-11-09"); show them as "9 Nov 2026". */
export const prettyReason = (t) => String(t ?? '').replace(/\b(\d{4}-\d{2}-\d{2})\b/g, (m) => fmt.date(m));

/** Plain-language meaning + next action for each diagnosis code (rollup.js order). */
export const DIAG_INFO = {
  ambassador_gap: { title: 'Ambassadors missing', text: 'Some relevant branches have no active ambassador, so nobody is reaching those students.', cta: 'Show these colleges', filter: ['diagnosis', 'ambassador_gap'] },
  low_outreach: { title: 'Too little outreach', text: 'Fewer students have been reached than this point in the campaign needs.', cta: 'Show these colleges', filter: ['diagnosis', 'low_outreach'] },
  low_conversion: { title: 'Low conversion', text: 'Students are being reached, but too few of them are enrolling.', cta: 'Show these colleges', filter: ['diagnosis', 'low_conversion'] },
  unrealistic_target: { title: 'Target looks too high', text: 'The target is more than half of the eligible students, so it is unlikely to be met.', cta: 'Review targets', href: '#/targets' },
  behind_pace: { title: 'Behind pace', text: 'Enrollments are behind the pace needed to reach the target by the deadline.', cta: 'Show these colleges', filter: ['diagnosis', 'behind_pace'] },
};
const DIAG_ORDER = ['ambassador_gap', 'low_outreach', 'low_conversion', 'unrealistic_target', 'behind_pace'];

/** Open the colleges list with exactly one filter applied (filters live in the URL). */
const GO_KEY = { exam_state: 'exam', op_status: 'op' };
export function goColleges(ctx, key, value) {
  const k = GO_KEY[key] || key;
  ctx.navigate(key ? `#/colleges?${encodeURIComponent(k)}=${encodeURIComponent(value)}` : '#/colleges');
}

/** A list that shows `limit` items and a "Show all N" toggle for the rest. */
function expandable(items, limit, { cls, noun = 'more' } = {}) {
  const list = h('ul', { class: cls });
  const extra = items.length - limit;
  let open = false;
  const draw = () => list.replaceChildren(...(open ? items : items.slice(0, limit)));
  draw();
  if (extra <= 0) return list;
  const btn = h('button', { type: 'button', class: 'td-btn td-btn--ghost td-btn--sm vd-more', 'aria-expanded': 'false' });
  const label = () => { btn.textContent = open ? 'Show fewer' : `Show ${fmt.num(extra)} ${noun}`; btn.setAttribute('aria-expanded', open ? 'true' : 'false'); };
  btn.addEventListener('click', () => { open = !open; draw(); label(); });
  label();
  return h('div', { class: 'vd-expandable' }, list, btn);
}

/* Attention list (/api/attention rows) */
const SEV_TEXT = { high: 'Urgent', 3: 'Urgent', critical: 'Urgent', medium: 'Soon', 2: 'Soon', low: 'Watch', 1: 'Watch' };
export function attentionList(ctx, rows, limit = 8) {
  const all = [...(rows || []).filter((r) => r.type === 'group'), ...(rows || []).filter((r) => r.type !== 'group')];
  if (!all.length) return ctx.ui.emptyState({ icon: 'check', title: 'Nothing urgent', text: 'No colleges are behind pace, missing leads or overdue right now.' });
  const items = all.slice(0, 60).map((r) => {
    const sev = String(r.severity ?? '');
    return h('li', { class: ['vd-attn-item', r.type === 'group' && 'is-group'], dataset: { sev } },
      h('a', { href: r.href || hrefFor(r.type, r) || '#/', class: 'vd-attn-link',
        onMouseenter: () => r.type === 'college' && ctx.map?.highlight?.(r.id), onMouseleave: () => ctx.map?.highlight?.(null) },
      h('div', { class: 'vd-attn-head' },
        h('strong', null, r.label || rowLabel(r)),
        SEV_TEXT[sev] ? h('span', { class: 'td-sr-only' }, ` (${SEV_TEXT[sev]})`) : null,
        r.type === 'group' && isNum(r.count) ? h('span', { class: 'vd-count' }, fmt.plural(r.count, 'college'))
          : (r.diagnosis ? ctx.ui.statusBadge('diagnosis', r.diagnosis) : null)),
      (r.reasons || []).length ? h('ul', { class: 'vd-attn-reasons' }, r.reasons.map((x) => h('li', null, prettyReason(x)))) : null));
  });
  const more = all.length > 60 ? h('p', { class: 'vd-muted vd-small' }, `Showing the first 60 of ${fmt.num(all.length)}. Use the Colleges list filters to see the rest.`) : null;
  return h('div', null, expandable(items, limit, { cls: 'vd-attn', noun: 'more' }), more);
}

/* ---------- hash query helpers (list state lives in the URL, UI-18) ---------- */
export function hashQuery() {
  const i = location.hash.indexOf('?');
  return new URLSearchParams(i >= 0 ? location.hash.slice(i + 1) : '');
}
/** Write the list state to the hash query without re-routing. A discrete filter / sort / page change pushes a history
 *  entry so Back undoes it; typing in the search box replaces (D8 — ui.historyMode). */
export function replaceHashQuery(base, obj) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(obj)) if (v !== undefined && v !== null && v !== '' && v !== false) q.set(k, String(v));
  const s = q.toString();
  const url = `${base}${s ? '?' + s : ''}`;
  if (url === location.hash) return;
  const prev = location.hash.startsWith(base) ? Object.fromEntries(hashQuery()) : null;
  const push = prev && typeof historyMode === 'function' && historyMode(prev, Object.fromEntries(q)) === 'push';
  try { if (push) history.pushState(null, '', url); else history.replaceState(history.state, '', url); } catch { /* ignore */ }
}

/* ---------- research plan (P-level, leads / ambassadors needed) — cached per session ---------- */
let planCache = null;
export async function planIndex(ctx) {
  if (!planCache) {
    planCache = ctx.api.get('/plan', { districts: 'all' }).catch(() => ctx.api.get('/plan')).then((p) => {
      const m = new Map();
      for (const c of (p && p.colleges) || []) m.set(c.college_id, c);
      return m;
    }).catch(() => { planCache = null; return new Map(); });
  }
  return planCache;
}
export const P_LEVELS = ['P1', 'P2', 'P3', 'Hold'];
export function pLevelOf(r, plan) {
  if (r && r.p_level) return r.p_level;
  const p = plan && plan.get(r.id || r.college_id);
  return p ? (p.p_level || null) : null;
}

/** Verification state of a college row: v4 `data_status` / `verified_fields`; null when the server has no such data. */
export function verifiedStateOf(r) {
  if (!r) return null;
  if (r.data_status) return r.data_status === 'partly_verified' ? 'partly' : r.data_status; // verified | partly | unverified
  const vf = r.verified_fields;
  if (vf && typeof vf === 'object') return Object.keys(vf).length ? 'partly' : 'unverified';
  return null;
}
export const VERIFIED_LABEL = { verified: ['Verified', 'good'], partly: ['Partly verified', 'info'], unverified: ['Unverified', 'warn'] };
export function verifiedBadge(ctx, state, extra = {}) {
  if (!state) return null;
  if (typeof ctx.ui.verifiedBadge === 'function' && (state === 'verified' || state === 'unverified' || state === 'missing')) {
    try { const n = ctx.ui.verifiedBadge({ state, ...extra }); if (n) return n; } catch { /* fall back */ }
  }
  const [l, t] = VERIFIED_LABEL[state] || [state, 'neutral'];
  return ctx.ui.badge(l, t);
}

/** Phone / WhatsApp / email actions for a person or contact (ui.contactActions when the shell provides it). */
export function contactActions(ctx, phone, email, { compact = true } = {}) {
  if (!phone && !email) return null;
  if (typeof ctx.ui.contactActions === 'function') { try { const n = ctx.ui.contactActions(phone, email); if (n) return n; } catch { /* fall back */ } }
  const digits = phone ? String(phone).replace(/[^\d]/g, '') : '';
  const wa = digits.length >= 10 ? `https://wa.me/${digits.length === 10 ? '91' + digits : digits}` : null;
  const a = (href, icon, label, extra = {}) => h('a', { href, class: 'td-btn td-btn--ghost td-btn--sm td-btn--icon vd-cact', title: label, 'aria-label': label, onClick: (e) => e.stopPropagation(), ...extra },
    icon ? ctx.ui.icon(icon, { size: 16 }) : h('span', { class: 'vd-wa', 'aria-hidden': 'true' }, 'WA'));
  return h('span', { class: 'vd-cacts' },
    phone ? a(`tel:${String(phone).replace(/[^\d+]/g, '')}`, 'phone', `Call ${phone}`) : null,
    wa ? a(wa, null, `WhatsApp ${phone}`, { target: '_blank', rel: 'noopener' }) : null,
    email ? a(`mailto:${email}`, 'mail', `Email ${email}`) : null,
    compact ? null : h('span', { class: 'vd-small vd-muted' }, phone || email));
}

/** Simple pager: "1–25 of 171"  ‹ Prev  Page 1 of 7  Next ›  */
export function pager(ctx, { page, pageSize, total, onPage }) {
  if (typeof ctx.ui.pagination === 'function') { try { const n = ctx.ui.pagination({ page, pageSize, total, onPage }); if (n) return n; } catch { /* fall back */ } }
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return total ? h('div', { class: 'vd-pager' }, h('span', { class: 'vd-muted vd-small' }, `${fmt.plural(total, 'result')}`)) : null;
  const from = (page - 1) * pageSize + 1, to = Math.min(total, page * pageSize);
  const b = (label, p, dis, aria) => h('button', { type: 'button', class: 'td-btn td-btn--secondary td-btn--sm', disabled: dis ? true : null, 'aria-label': aria, onClick: () => onPage(p) }, label);
  return h('nav', { class: 'vd-pager', 'aria-label': 'Pages' },
    h('span', { class: 'vd-muted vd-small', 'aria-live': 'polite' }, `${fmt.num(from)}–${fmt.num(to)} of ${fmt.num(total)}`),
    h('span', { class: 'vd-pager-btns' },
      b('‹ Prev', page - 1, page <= 1, 'Previous page'),
      h('span', { class: 'vd-small' }, `Page ${fmt.num(page)} of ${fmt.num(pages)}`),
      b('Next ›', page + 1, page >= pages, 'Next page')));
}

/** Unassigned ambassadors from /api/people rows. v4 rows carry assignment_status; on v3 rows apply rule R3 to the same rows. */
export function unassignedOf(people) {
  const rows = people || [];
  if (rows.some((p) => p.assignment_status)) return rows.filter((p) => p.role === 'ambassador' && p.status !== 'inactive' && p.assignment_status && p.assignment_status !== 'assigned');
  const byId = new Map(rows.map((p) => [Number(p.id), p]));
  return rows.filter((p) => {
    if (p.role !== 'ambassador' || p.status === 'inactive') return false;
    if (!p.reports_to) return true;
    const m = byId.get(Number(p.reports_to));
    return !m || m.status === 'inactive' || m.college_id !== p.college_id || !['college_lead', 'ambassador_lead'].includes(m.role);
  });
}

/* =====================================================================================
 * #/  — Home
 * ===================================================================================== */
function homeSkeleton(ctx) {
  if (typeof ctx.ui.skeleton !== 'function') return loading();
  return h('div', { class: 'vd-skel', role: 'status', 'aria-label': 'Loading home' }, ctx.ui.skeleton(2), ctx.ui.skeleton(4), ctx.ui.skeleton(4));
}

export async function renderState(el, params, ctx) {
  ctx.map?.focusState?.();
  setCrumbs(ctx, [{ label: 'Home', href: '#/' }]);
  mount(el, 'v-dashboard', homeSkeleton(ctx));
  const sc = getScope();
  const { data, errors } = await fetchAll({
    summary: getScoped(ctx, '/summary', { scope: 'state' }),
    road: getScoped(ctx, '/target-dashboard', { scope: 'state' }),
    plan: getScoped(ctx, '/plan'),
    colleges: getScoped(ctx, '/colleges'),
    attention: getScoped(ctx, '/attention', { scope: 'state' }),
    followups: getScoped(ctx, '/followups', { status: 'open' }),
    exams: getScoped(ctx, '/exams'),
    queue: getScoped(ctx, '/calls/queue', { filter: 'all', sort: 'priority', limit: 300 }),
    people: getScoped(ctx, '/people', { assignment: 'unassigned,invalid_link', page: 1, page_size: 1 }).catch(() => getScoped(ctx, '/people')),
    perf: getPerformance(ctx, { level: 'person', period: 'programme' }),
    meta: ctx.api.get('/meta'),
  });
  if (!el.isConnected && el.parentNode === null) return;
  const collegesAll = scopeRows(itemsOf(data.colleges));
  const collegeIds = new Set(collegesAll.map((c) => c.id));
  const collegeOk = (id) => sc.all || !id || collegeIds.has(id);
  const S = data.summary;
  if (!S) {
    mount(el, 'v-dashboard', typeof ctx.ui.errorCard === 'function'
      ? ctx.ui.errorCard({ title: 'Could not load the programme summary', error: errors.summary, retry: () => renderState(el, params, ctx) })
      : errorNote(errors.summary, 'the programme summary'));
    return;
  }
  if (data.exams) data.exams = scopeRows(data.exams).filter((e) => collegeOk(e.college_id));
  if (data.followups) data.followups = itemsOf(data.followups).filter((f) => collegeOk(f.college_id || (f.scope_type === 'college' ? f.scope_id : null)));
  if (data.queue && data.queue.rows) data.queue.rows = scopeRows(data.queue.rows).filter((r) => collegeOk(r.college_id));
  if (data.attention) data.attention = data.attention.filter((r) => r.type === 'group' || (r.type === 'college' ? collegeOk(r.id) : r.type === 'district' ? inScope(r.id) : true));
  // v4: {total} of the unassigned query; v3: the full people array (rule R3 applied to its rows)
  const unassignedTotal = data.people && !Array.isArray(data.people) && isNum(data.people.total) ? data.people.total
    : data.people ? unassignedOf(itemsOf(data.people).filter((p) => collegeOk(p.college_id))).length : null;

  const shellMap = el.closest('[data-layout]')?.dataset.layout === 'explore' && typeof ctx.mountMap !== 'function';
  const head = typeof ctx.ui.pageHeader === 'function'
    ? ctx.ui.pageHeader({ eyebrow: 'Outreach programme', title: 'Home', sub: scopePill(ctx) })
    : h('header', { class: 'vd-pagehead' }, h('h1', null, 'Home'), scopePill(ctx));

  mount(el, 'v-dashboard',
    h('div', { class: ['vd-home', shellMap && 'is-narrow'] },
      head,
      kpiStrip(ctx, S, data.road, data.plan, errors),
      needsAttention(ctx, { S, colleges: collegesAll, unassignedTotal, perf: data.perf, errors, attention: data.attention }),
      shellMap ? null : mapPanel(ctx, collegesAll, data.meta),
      h('div', { class: 'vd-duo' },
        topCalls(ctx, data.queue, errors.queue),
        sectionEl(ctx, 'Next 14 days', upcoming(ctx, data.followups, data.exams, S, errors),
          h('a', { href: '#/exams', class: 'vd-link' }, 'Exam calendar'), 'Follow-ups due and exam windows')),
      h('p', { class: 'vd-muted vd-small vd-home-foot' }, 'Charts, rankings, districts and courses are in ', h('a', { href: '#/analytics' }, 'Reports'), '.')));
}

/** Compact KPI strip: target, confirmed, remaining/exceeded, % achieved, pace + days left, team recruited vs needed. */
function kpiStrip(ctx, S, T, plan, errors) {
  const prog = T && T.program ? T.program : null;
  const why = noTargetReason(T, S);
  const progNA = programmeNA(T);
  // D2: the programme target applies only to a selection with every programme district; otherwise the selected
  // districts' own targets (T.target, may be partial_target) are shown
  const target = why ? null : (progNA ? T.target : prog && prog.target !== undefined ? prog.target : T ? T.target : S.target);
  const partialT = !!T && T.target_status === 'partial_target';
  const hasTarget = target > 0;
  const confirmed = T ? T.confirmed : S.enrolled;
  const remaining = T ? T.remaining : S.remaining;
  const exceeded = partialT ? 0 : T && isNum(T.exceeded_by) ? T.exceeded_by : hasTarget && confirmed > target ? confirmed - target : 0;
  const pct = T ? T.pct : S.pct;
  // F18: colour the pace tile from the server's pace status (too_early = grace period, never red)
  const paceSt = (T && (T.pace_status || (prog && prog.pace_status))) || S.pace_status || null;
  const behind = hasTarget && T && T.required_weekly != null && (T.current_weekly ?? 0) < T.required_weekly && paceSt !== 'too_early';
  const tile = (label, value, sub, tone, href) => h(href ? 'a' : 'div', { class: ['vd-kt', tone && `is-${tone}`], href: href || null },
    h('span', { class: 'vd-kt-l' }, label), h('span', { class: 'vd-kt-v td-num' }, value), sub ? h('span', { class: 'vd-kt-s' }, sub) : null);
  const tr = plan && plan.totals_research; const ta = plan && plan.totals_actual;
  const leadsHave = ta ? ta.college_leads : S.college_leads; const ambHave = ta ? (ta.ambassadors ?? 0) + (ta.ambassador_leads ?? 0) : (S.ambassadors ?? 0) + (S.ambassador_leads ?? 0);
  const need = (have, n) => (isNum(n) ? `${fmt.num(have ?? 0)} of ${fmt.num(n)}` : fmt.num(have ?? 0));
  // D1 (v4.1): totals_actual counts every active person in scope; outside_plan = those at colleges not in the research plan
  const outside = (k) => { const o = ta && ta.outside_plan; if (!o || typeof o !== 'object') return 0; return k === 'amb' ? (o.ambassadors ?? 0) + (o.ambassador_leads ?? 0) : (o[k] ?? 0); };
  const recSub = (k, base) => (outside(k) > 0 ? `${base} · ${fmt.num(outside(k))} outside the plan` : base);
  return h('section', { class: 'vd-kstrip', 'aria-label': 'Programme at a glance' },
    why ? h('div', { class: 'vd-kt', title: why }, h('span', { class: 'vd-kt-l' }, 'Target'), h('span', { class: 'vd-kt-v vd-kt-v--text' }, 'No target'), h('span', { class: 'vd-kt-s' }, 'for this selection'))
      : tile('Target', hasTarget ? fmt.num(target) : 'Not set', hasTarget ? (partialT && T.covers ? `covers ${fmt.num(T.covers.with_target)} of ${fmt.num(T.covers.total)} · not judged` : progNA ? `selected districts' targets` : prog ? (prog.is_default_selection ? 'target districts' : `${fmt.plural((prog.selected_districts || []).length || 0, 'district')} selected`) : (T && T.deadline ? `by ${fmt.date(T.deadline)}` : null)) : 'Set it in Targets', partialT ? 'warn' : null, hasTarget ? null : '#/targets'),
    tile('Confirmed', fmt.num(confirmed ?? 0), 'paid enrollments'),
    tile(exceeded ? 'Exceeded by' : 'Remaining', hasTarget && !partialT ? fmt.num(exceeded || remaining) : '—', hasTarget && !partialT ? (exceeded ? 'above target' : 'still needed') : null, exceeded ? 'good' : null),
    tile('Achieved', hasTarget && !partialT ? pctText(pct) : '—', hasTarget && !partialT ? 'of target' : null),
    tile('Needed per week', hasTarget && T ? (T.deadline_passed ? 'Passed' : rateText(T.required_weekly)) : '—',
      T && hasTarget ? h('span', null, paceSt === 'too_early' ? 'too early to judge · ' : `now ${rateText(T.current_weekly)}/wk · `, daysLeftText(T.days_left, null)) : (errors.road ? 'Pace unavailable' : null),
      behind ? 'bad' : paceSt === 'too_early' ? 'info' : hasTarget && T ? 'good' : null, '#/analytics'),
    tile('College leads', need(leadsHave, tr && tr.college_leads), recSub('college_leads', tr ? 'recruited of needed' : 'recruited'), isNum(tr?.college_leads) && (leadsHave ?? 0) < tr.college_leads ? 'warn' : null, '#/people?seg=leads'),
    tile('Ambassadors', need(ambHave, tr && tr.ambassadors), recSub('amb', tr ? 'recruited of needed' : 'incl. ambassador leads'), isNum(tr?.ambassadors) && ambHave < tr.ambassadors ? 'warn' : null, '#/people?seg=ambassadors'));
}

/** "Needs attention": four counts that each open a filtered list. */
function needsAttention(ctx, { S, colleges, unassignedTotal, perf, errors, attention }) {
  const targetedOps = colleges.filter((c) => c.targeted && (c.op_status || 'pending') === 'operational');
  const noLead = targetedOps.filter((c) => !leadOf(c));
  const pRows = perfRows(perf);
  const behind = perf ? pRows.filter((r) => r.status === 'behind') : null;
  const card = ({ n, title, text, href, tone, icon, na }) => h('a', { href, class: ['vd-need', `is-${n > 0 ? tone : 'ok'}`, na && 'is-na'] },
    h('span', { class: 'vd-need-icon' }, ctx.ui.icon(n > 0 ? icon : 'check', { size: 20 })),
    h('span', { class: 'vd-need-body' },
      h('span', { class: 'vd-need-n td-num' }, n === null ? '—' : fmt.num(n)),
      h('strong', null, title), h('span', { class: 'vd-muted vd-small' }, text)),
    ctx.ui.icon('chevron', { size: 16, class: 'vd-need-go' }));
  const others = (attention || []).filter((r) => r.type !== 'group');
  return h('section', { class: 'vd-needs', 'aria-labelledby': 'vd-needs-t' },
    h('div', { class: 'vd-needs-head' }, h('h2', { id: 'vd-needs-t', class: 'vd-h2' }, 'Needs attention'),
      h('span', { class: 'vd-muted vd-small' }, 'Each opens the matching list')),
    h('div', { class: 'vd-needs-grid' },
      card({ n: noLead.length, title: 'Targeted colleges with no lead', text: `of ${fmt.num(targetedOps.length)} targeted operational colleges`, href: '#/colleges?team=no_lead&targeted=1', tone: 'bad', icon: 'lead' }),
      card({ n: unassignedTotal, title: 'Unassigned team members', text: unassignedTotal !== null ? 'active, without a valid lead to report to' : (errors.people ? 'Could not load the team' : ''), href: '#/people?seg=unassigned', tone: 'warn', icon: 'ambassador' }),
      card({ n: behind ? behind.length : null, title: 'People behind target', text: behind ? `of ${fmt.plural(pRows.filter((r) => r.target > 0).length, 'person', 'people')} with a target` : 'Shown once performance tracking is live on the server', href: '#/targets?level=person&status=behind', tone: 'bad', icon: 'target', na: !behind }),
      card({ n: isNum(S.followups_overdue) ? S.followups_overdue : null, title: 'Overdue follow-ups', text: isNum(S.followups_open) ? `${fmt.num(S.followups_open)} open in total` : '', href: '#/followups?tab=overdue', tone: 'bad', icon: 'followup' })),
    others.length || (attention || []).length ? h('details', { class: 'vd-needs-more' },
      h('summary', null, `All alerts (${fmt.num((attention || []).length)})`),
      attentionList(ctx, attention, 8)) : (errors.attention ? errorNote(errors.attention, 'alerts') : null));
}

/** Map as a secondary panel (Home on layouts without the shell's map): collapsed by default, remembered per browser. */
function mapPanel(ctx, rows, meta) {
  const KEY = 'td.home.map';
  let open = !isPhone(ctx); // visible by default on tablet / desktop; one tap away on phones
  try { const v = localStorage.getItem(KEY); if (v === '1' || v === '0') open = v === '1'; } catch { /* ignore */ }
  const host = h('div', { class: 'vd-mapbox td-mapcard', hidden: open ? null : true });
  let m = null;
  const build = async () => {
    if (m) { m.invalidateSize?.(); return; }
    host.replaceChildren(loading('Loading map…'));
    try {
      host.replaceChildren();
      if (typeof ctx.mountMap === 'function') { // the shell owns the map and feeds it the scoped pins
        m = await ctx.mountMap(host);
        if (m) { m.focusState?.(); return; }
      }
      const mod = await import('../map/map.js');
      const sc = getScope();
      m = mod.createMap(host, {
        onSelectDistrict: (id) => ctx.navigate(`#/d/${encodeURIComponent(id)}`),
        onSelectCity: (d, c) => ctx.navigate(`#/d/${encodeURIComponent(d)}/${encodeURIComponent(c)}`),
        onSelectCollege: (id) => ctx.navigate(`#/college/${encodeURIComponent(id)}`),
        onReset: () => m && m.focusState(),
      });
      if (meta) m.setPlaces?.({ districts: meta.districts || [], cities: meta.cities || [] });
      m.setScope?.({ all: sc.all, ids: sc.ids, target: targetDistrictIds(), groups: targetGroups() });
      m.setColleges(rows);
      onCleanup(() => { try { m.destroy(); } catch { /* ignore */ } m = null; });
    } catch (e) {
      host.replaceChildren(h('p', { class: 'vd-muted vd-pad' }, 'The map could not be loaded. Everything else works without it.'));
    }
  };
  const btn = h('button', { type: 'button', class: 'td-btn td-btn--secondary td-btn--sm', 'aria-expanded': open ? 'true' : 'false' });
  const label = () => btn.replaceChildren(ctx.ui.icon('map', { size: 16 }), h('span', null, open ? 'Hide map' : 'Show map'));
  btn.addEventListener('click', () => {
    open = !open; host.hidden = !open; btn.setAttribute('aria-expanded', open ? 'true' : 'false'); label();
    try { localStorage.setItem(KEY, open ? '1' : '0'); } catch { /* ignore */ }
    if (open) build();
  });
  label();
  if (open) setTimeout(build, 0);
  return h('section', { class: 'vd-mapsec td-card', 'aria-labelledby': 'vd-map-t' },
    h('div', { class: 'vd-mapsec-head' },
      h('div', null, h('h2', { class: 'vd-h2', id: 'vd-map-t' }, 'Map'), h('span', { class: 'vd-muted vd-small' }, `${fmt.plural(rows.length, 'college')} in the selected districts`)),
      btn),
    host);
}

/* Top colleges to call: the internal priority queue for the selected districts. */
function topCalls(ctx, q, err) {
  const head = h('div', { class: 'vdq-head' }, h('h2', { class: 'vd-h2' }, 'Top colleges to call'), h('a', { href: '#/calls', class: 'vd-link' }, 'Open calling'));
  if (!q) return h('section', { class: 'vdc vd-lite td-card' }, head, errorNote(err, 'the calling queue'));
  const rows = (q.rows || []).slice(0, 5);
  const refresh = () => ctx.refresh?.();
  const item = (r) => {
    const k = r.best_contact;
    const verified = !!(k && k.phone && k.basis === 'verified' && k.status !== 'invalid' && k.status !== 'non_working');
    return h('li', { class: 'vdc-item' },
      h('div', { class: 'vdc-main' },
        h('a', { href: `#/college/${r.college_id}`, class: 'vdc-name' }, r.short_name || r.name),
        h('span', { class: 'vd-muted vd-small' }, [r.city_name, r.district_name].filter(Boolean).join(', '), r.priority ? ` · priority ${r.priority.score}` : ''),
        h('span', { class: 'vdc-badges' }, callStatusBadge(ctx, r.call_status),
          h('span', { class: 'vd-small vd-muted' }, verified ? contactLabel(k) || 'Verified number' : k && k.phone ? 'Number not verified' : 'No number yet'),
          verified ? ctx.ui.provenance('verified') : null)),
      h('div', { class: 'vdc-act' },
        verified ? telLink(ctx, k.phone, { label: 'Call', cls: 'td-btn td-btn--primary td-btn--sm vdc-call' }) : null,
        h('button', { type: 'button', class: 'td-btn td-btn--secondary td-btn--sm', onClick: () => logCall(ctx, { college_id: r.college_id, college_label: r.short_name || r.name, onSaved: refresh }) },
          ctx.ui.icon('phone', { size: 14 }), h('span', null, 'Log call'))));
  };
  return h('section', { class: 'vdc vd-lite td-card', 'aria-label': 'Top colleges to call' }, head,
    h('p', { class: 'vd-muted vd-small vdq-sub' }, `Highest priority first, of ${fmt.plural((q.rows || []).length, 'college')} in the queue. “Call” dials verified numbers only.`),
    rows.length ? h('ol', { class: 'vdc-list' }, rows.map(item)) : h('p', { class: 'vd-muted vd-small' }, 'No operational colleges in the selected districts.'));
}

const examRange = (ne) => {
  if (!ne || !ne.start) return '';
  const what = [ne.semester, ne.kind].filter(Boolean).join(' ');
  return `${what ? what + ': ' : ''}${fmt.date(ne.start)}${ne.end && ne.end !== ne.start ? ' – ' + fmt.date(ne.end) : ''}`;
};

function upcoming(ctx, followups, exams, S, errors) {
  const fuItems = [];
  for (const f of followups || []) {
    const fd = daysUntil(f.due_date);
    if (fd === null || fd < 0 || fd > 14) continue; // overdue ones are counted in "Needs attention"
    const href = f.href || (f.scope_type === 'college' ? `#/college/${f.scope_id}` : f.scope_type === 'person' ? `#/person/${f.scope_id}` : f.college_id ? `#/college/${f.college_id}` : '#/followups');
    fuItems.push({ date: f.due_date, node: h('li', null, h('a', { href, class: 'vd-up' },
      h('span', { class: 'vd-up-date' }, h('strong', null, fmt.date(f.due_date).replace(/ \d{4}$/, '')), h('small', null, fmt.days(f.due_date))),
      h('span', { class: 'vd-up-main' },
        h('strong', null, f.title || 'Follow-up'),
        h('span', { class: 'vd-muted vd-small' }, [f.scope_label || f.college_name || f.label, f.owner_name ? `owner ${f.owner_name}` : null].filter(Boolean).join(' · '))))) });
  }
  fuItems.sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const exItems = [];
  for (const e of exams || []) {
    const ne = e.next_exam;
    const inNow = e.exam_state === 'in_exams';
    const d = ne && ne.start ? daysUntil(ne.start) : null;
    if (!inNow && !(d !== null && d >= 0 && d <= 14)) continue;
    exItems.push({ key: inNow ? `0-${ne && ne.end ? ne.end : ''}` : `1-${ne.start}`, node: h('li', null, h('a', { href: `#/college/${e.college_id}?tab=exams`, class: 'vd-up' },
      h('span', { class: 'vd-up-date' }, inNow ? h('strong', null, 'Now') : h('strong', null, fmt.date(ne.start).replace(/ \d{4}$/, '')),
        h('small', null, inNow ? (ne && ne.end ? `ends ${fmt.days(ne.end)}` : 'running') : fmt.days(ne.start))),
      h('span', { class: 'vd-up-main' }, h('strong', null, e.name || e.college_id), h('span', { class: 'vd-muted vd-small' }, examRange(ne))),
      ctx.ui.statusBadge('exam_state', e.exam_state))) });
  }
  exItems.sort((a, b) => a.key.localeCompare(b.key));
  const fuBlock = h('div', { class: 'vd-up-block' },
    h('h3', { class: 'vd-h3' }, ctx.ui.icon('followup', { size: 16 }), 'Follow-ups due', h('span', { class: 'vd-count' }, fmt.num(fuItems.length))),
    errors.followups ? errorNote(errors.followups, 'follow-ups') : null,
    fuItems.length ? expandable(fuItems.map((x) => x.node), 3, { cls: 'vd-uplist' })
      : h('p', { class: 'vd-muted vd-small vd-up-empty' }, S.followups_open > 0 ? 'No open follow-up is due in the next 14 days.' : 'No follow-ups yet. Add one from a college page when you plan a call or visit.'));
  const exBlock = h('div', { class: 'vd-up-block' },
    h('h3', { class: 'vd-h3' }, ctx.ui.icon('exam', { size: 16 }), 'Exams', h('span', { class: 'vd-count' }, fmt.num(exItems.length))),
    errors.exams ? errorNote(errors.exams, 'exams') : null,
    exItems.length ? expandable(exItems.map((x) => x.node), 3, { cls: 'vd-uplist' })
      : h('p', { class: 'vd-muted vd-small vd-up-empty' }, 'No exams running or starting in the next 14 days.'));
  return h('div', { class: 'vd-up-grid' }, fuBlock, exBlock);
}

/* =====================================================================================
 * #/colleges — colleges list (also embedded by the district / city pages in geo.js)
 * ===================================================================================== */
const CALL_STATUS_OPTS = [['not_called', 'Not called'], ['attempted_no_answer', 'Tried, no answer'], ['follow_up_due', 'Call-back due'], ['contacted', 'Contacted'],
  ['interested', 'Interested'], ['participation_confirmed', 'Participation confirmed'], ['enrolled', 'Students enrolled']];
const CONTACT_OPTS = [['working', 'Has a working number'], ['untested', 'Has an untested number'], ['non_working', 'Has a non-working / invalid number'], ['none', 'No contact yet']];
const TEAM_OPTS = [['no_lead', 'No college lead'], ['has_lead', 'Has a college lead'], ['no_ambassadors', 'No ambassadors'], ['has_team', 'Lead and ambassadors'], ['has_unassigned', 'Has unassigned people']];
const OP_OPTS = [['operational', 'Operational'], ['all', 'Any status'], ['possibly_closed', 'Possibly closed'], ['closed', 'Closed'], ['pending', 'Status pending']];
const VERIFIED_OPTS = [['verified', 'Verified'], ['partly', 'Partly verified'], ['unverified', 'Unverified']];
const AMB_OPTS = [['gap', 'Some IT branch has no ambassador'], ['ok', 'Every IT branch covered']];
const PROGRESS_OPTS = [['behind', 'Behind'], ['on_track', 'On track'], ['no_target', 'No target']];
const EXAM_OPTS = [['in_exams', 'In exams now'], ['exams_soon', 'Exams within 14 days'], ['clear', 'Clear'], ['unknown', 'Dates unknown']];
const FU_OPTS = [['overdue', 'Overdue follow-up'], ['open', 'Has open follow-ups'], ['none', 'No follow-ups']];
const SORTS = [
  ['priority', 'Priority (P-level, then name)'], ['name', 'Name'], ['sno', 'List number'], ['district', 'District'], ['lead', 'Lead missing first'],
  ['ambassadors', 'Ambassadors'], ['unassigned', 'Unassigned ambassadors'], ['target', 'Target'], ['actual', 'Confirmed'], ['pct', 'Progress %'],
  ['remaining', 'Remaining'], ['eligible', 'Eligible students'], ['next_followup', 'Next follow-up'],
];
const PAGE_SIZE = 25;
/** URL keys of the list state */
const LIST_KEYS = ['q', 'team', 'p', 'op', 'verified', 'targeted', 'diagnosis', 'call_status', 'contact', 'amb', 'progress', 'exam', 'followup', 'sort', 'dir', 'page'];
const LABELS = {
  team: ['Team', TEAM_OPTS], p: ['P-level', [...P_LEVELS.map((x) => [x, x]), ['none', 'Not in research plan']]], op: ['Status', OP_OPTS], verified: ['Verification', VERIFIED_OPTS],
  diagnosis: ['Main reason', DIAG_ORDER.map((k) => [k, DIAG_INFO[k].title])], call_status: ['Calling', CALL_STATUS_OPTS], contact: ['Contacts', CONTACT_OPTS],
  amb: ['Ambassadors', AMB_OPTS], progress: ['Progress', PROGRESS_OPTS], exam: ['Exams', EXAM_OPTS], followup: ['Follow-ups', FU_OPTS], targeted: ['Targeted', [['1', 'Targeted only']]],
};

export async function renderCollegeList(el, params, ctx) {
  setCrumbs(ctx, [{ label: 'Home', href: '#/' }, { label: 'Colleges', href: '#/colleges' }]);
  mount(el, 'v-colleges', loading('Loading colleges…'));
  const meta = await ctx.api.get('/meta').catch(() => ({ districts: [], cities: [] }));
  const list = collegeList(ctx, { meta, params: params || {}, base: '#/colleges' });
  const addBtn = ctx.ui.button({ label: 'Add college', icon: 'plus', tone: 'primary', onClick: () => openCollegeForm(ctx, null) });
  const head = typeof ctx.ui.pageHeader === 'function'
    ? ctx.ui.pageHeader({ title: 'Colleges', sub: scopePill(ctx), actions: [list.exportBtn, addBtn] })
    : h('header', { class: 'vd-pagehead' }, h('div', null, h('h1', null, 'Colleges'), scopePill(ctx)), h('div', { class: 'vd-pagehead-actions' }, list.exportBtn, addBtn));
  mount(el, 'v-colleges', head, list.el);
  await list.load();
}

export async function openCollegeForm(ctx, collegeId, opts = {}) {
  const mod = await import('./college-form.js');
  return collegeId ? mod.editCollege(ctx, collegeId, opts) : mod.createCollege(ctx, opts);
}

/**
 * Colleges list component. opts: {meta, params, base ('#/colleges' keeps state in the URL; null = in-memory),
 * fixed: {district?, city?} (district / city pages), compact}
 * returns {el, load, exportBtn}
 */
export function collegeList(ctx, { meta, params = {}, base = null, fixed = null, compact = false } = {}) {
  const dName = new Map((meta.districts || []).map((d) => [d.id, d.name]));
  const cName = new Map((meta.cities || []).map((c) => [c.id, c.name]));
  const v = { sort: 'priority', dir: 1, page: 1, op: 'operational' };
  for (const k of LIST_KEYS) if (params[k] !== undefined && params[k] !== '') v[k] = String(params[k]);
  if (params.exam_state && !v.exam) v.exam = String(params.exam_state);
  if (params.op_status && !params.op) v.op = String(params.op_status);
  v.dir = Number(v.dir) === -1 ? -1 : 1; v.page = Math.max(1, Number(v.page) || 1);
  let rows = [], plan = new Map(), people = null, peopleTried = false;
  const caps = { team: false, verified: false, unassigned: false };

  const save = () => { if (base) replaceHashQuery(base, { ...Object.fromEntries(LIST_KEYS.map((k) => [k, v[k]])), sort: v.sort === 'priority' ? null : v.sort, dir: v.dir === -1 ? -1 : null, page: v.page > 1 ? v.page : null, op: v.op === 'operational' ? null : v.op }); };

  const unassignedN = (r) => (isNum(r.unassigned_count) ? r.unassigned_count : people ? people.get(r.id) ?? 0 : null);
  const sortVal = (r, k) => {
    switch (k) {
      case 'priority': { const p = pLevelOf(r, plan); const i = P_LEVELS.indexOf(p); return `${i < 0 ? 9 : i}-${String(r.short_name || r.name).toLowerCase()}`; }
      case 'name': return String(r.short_name || r.name || '').toLowerCase();
      case 'district': return `${dName.get(r.district_id) || r.district_id || ''}-${r.short_name || r.name}`;
      case 'lead': return leadOf(r) ? 1 : 0;
      case 'ambassadors': return ambCount(r);
      case 'unassigned': return unassignedN(r);
      case 'actual': return r.actual ?? r.enrolled ?? null;
      case 'eligible': return r.eligible ? r.eligible.value : null;
      case 'next_followup': return r.next_followup ? (typeof r.next_followup === 'object' ? r.next_followup.due_date : r.next_followup) : null;
      case 'target': return r.target > 0 ? r.target : null;
      case 'pct': return isNum(r.pct) && r.target > 0 ? r.pct : null;
      case 'remaining': return r.target > 0 ? r.remaining : null;
      default: return r[k] ?? null;
    }
  };
  const matches = (r) => {
    if (v.team && !caps.team) {
      const lead = !!leadOf(r); const amb = ambCount(r) + (r.ambassador_leads || 0);
      if (v.team === 'no_lead' && lead) return false;
      if (v.team === 'has_lead' && !lead) return false;
      if (v.team === 'no_ambassadors' && amb > 0) return false;
      if (v.team === 'has_team' && !(lead && amb > 0)) return false;
    }
    if (v.team === 'has_unassigned' && !caps.team && !((unassignedN(r) ?? 0) > 0)) return false;
    if (v.p) { const p = pLevelOf(r, plan); if (v.p === 'none' ? !!p : p !== v.p) return false; }
    if (v.verified && caps.verified && verifiedStateOf(r) !== v.verified) return false;
    if (v.targeted === '1' && !r.targeted) return false;
    if (v.followup) {
      const d = r.next_followup ? (typeof r.next_followup === 'object' ? r.next_followup.due_date : r.next_followup) : null;
      if (v.followup === 'overdue' && !(d && d < today())) return false;
      if (v.followup === 'none' && r.followups_open) return false;
      if (v.followup === 'open' && !(r.followups_open > 0)) return false;
    }
    return true;
  };
  const visible = () => rows.filter(matches).sort((a, b) => {
    const x = sortVal(a, v.sort), y = sortVal(b, v.sort);
    if ((x === null || x === undefined) && (y === null || y === undefined)) return 0;
    if (x === null || x === undefined) return 1; if (y === null || y === undefined) return -1;
    return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'en-IN', { numeric: true })) * v.dir;
  });

  /* ---------- rendering ---------- */
  const countEl = h('span', { class: 'vd-muted vd-small', 'aria-live': 'polite' });
  const host = h('div', { class: 'vd-ctable-host' });
  const pagerHost = h('div');
  const chipsHost = h('div', { class: 'vd-chips' });
  const filtersHost = h('div', { class: 'vd-filterbar' });
  const moreHost = h('div', { class: 'vd-filters-more' });

  const placeOf = (r) => [cName.get(r.city_id) || (r.city_id ? cityShort(r.district_id, r.city_id) : null), fixed?.district ? null : (dName.get(r.district_id) || r.district_id)].filter(Boolean).join(', ');
  // cell renderers (shared by ui.dataTable and the plain-table fallback)
  const C = {
    name: (r) => {
      const p = pLevelOf(r, plan); const vs = verifiedStateOf(r);
      return h('div', { class: 'vd-cc-name' },
        h('a', { href: `#/college/${r.id}`, class: 'vd-cname' }, r.short_name || r.name),
        h('span', { class: 'vd-muted vd-small vd-cplace' }, `#${r.sno ?? '—'}${placeOf(r) ? ' · ' + placeOf(r) : ''}`),
        h('span', { class: 'vd-badges' },
          p ? ctx.ui.badge(p, p === 'P1' ? 'brand' : p === 'Hold' ? 'neutral' : 'info') : null,
          r.op_status && r.op_status !== 'operational' ? ctx.ui.statusBadge('op_status', r.op_status) : null,
          r.targeted ? null : ctx.ui.badge('Not targeted', 'neutral'),
          vs ? verifiedBadge(ctx, vs) : null,
          r.exam_state === 'in_exams' || r.exam_state === 'exams_soon' ? ctx.ui.statusBadge('exam_state', r.exam_state) : null));
    },
    lead: (r) => {
      const lead = leadOf(r);
      return lead
        ? h('span', { class: 'vd-cc-lead' }, lead.id ? h('a', { href: `#/person/${lead.id}` }, lead.name) : h('span', null, lead.name), lead.phone ? contactActions(ctx, lead.phone, null) : null)
        : ctx.ui.badge('No lead', 'warn');
    },
    ambassadors: (r) => {
      const un = unassignedN(r);
      return h('span', { class: 'vd-cc-amb' },
        h('strong', { class: 'td-num' }, fmt.num(ambCount(r))),
        !caps.team && r.ambassador_leads ? h('span', { class: 'vd-muted vd-small' }, ` + ${fmt.num(r.ambassador_leads)} lead${r.ambassador_leads === 1 ? '' : 's'}`) : null,
        un > 0 ? h('span', { class: 'vd-cc-un' }, ctx.ui.badge(`${fmt.num(un)} unassigned`, 'warn')) : null,
        r.branches_needing_ambassadors > 0 ? h('span', { class: 'vd-muted vd-small vd-block' }, `${fmt.plural(r.branches_needing_ambassadors, 'IT branch', 'IT branches')} uncovered`) : null);
    },
    pct: (r) => h('div', { class: 'vd-tp' }, progressNode(ctx, r), r.target > 0 || r.status ? statusNode(ctx, r) : null),
    next_followup: (r) => h('div', { class: 'vd-cc-call' }, r.call_status ? callStatusBadge(ctx, r.call_status) : null, h('span', { class: 'vd-small' }, nextFollowupNode(r))),
  };
  const COLS = [['name', 'College'], ['lead', 'College lead'], ['ambassadors', 'Ambassadors'], ['pct', 'Target vs actual'], compact ? null : ['next_followup', 'Calling · next follow-up']].filter(Boolean);
  // responsive.md §4: what stays visible as the table narrows (1 = always), and the width each column needs
  const COL_FIT = { name: { priority: 1, minWidth: 230 }, pct: { priority: 1, minWidth: 180 }, lead: { priority: 2, minWidth: 170 },
    ambassadors: { priority: 3, minWidth: 130 }, next_followup: { priority: 3, minWidth: 170 } };
  // card mode: the college name is the title, number · place the subtitle, status badges the meta row
  const cardBadges = (r) => {
    const p = pLevelOf(r, plan); const vs = verifiedStateOf(r);
    const kids = [p ? ctx.ui.badge(p, p === 'P1' ? 'brand' : p === 'Hold' ? 'neutral' : 'info') : null,
      r.op_status && r.op_status !== 'operational' ? ctx.ui.statusBadge('op_status', r.op_status) : null,
      r.targeted ? null : ctx.ui.badge('Not targeted', 'neutral'), vs ? verifiedBadge(ctx, vs) : null,
      r.exam_state === 'in_exams' || r.exam_state === 'exams_soon' ? ctx.ui.statusBadge('exam_state', r.exam_state) : null].filter(Boolean);
    return kids.length ? h('span', { class: 'vd-badges' }, kids) : null;
  };
  const filtersActive = () => LIST_KEYS.some((k) => !['sort', 'dir', 'page', 'op'].includes(k) && v[k]) || (v.op && v.op !== 'operational');
  const DESC_FIRST = ['ambassadors', 'unassigned', 'actual', 'pct', 'eligible', 'target', 'remaining'];
  const setSort = (key, dir) => { v.sort = key; v.dir = dir ? (dir === 'desc' ? -1 : 1) : (DESC_FIRST.includes(key) ? -1 : 1); v.page = 1; save(); drawFilters(); draw(); };
  const onPage = (p) => { v.page = p; save(); draw(); host.scrollIntoView?.({ block: 'start', behavior: scrollBehavior(ctx) }); };
  const plainTable = (page) => {
    const th = (lbl, key) => {
      const on = v.sort === key;
      return h('th', { scope: 'col', 'aria-sort': on ? (v.dir > 0 ? 'ascending' : 'descending') : 'none' },
        h('button', { type: 'button', class: 'vd-th', onClick: () => (v.sort === key ? setSort(key, v.dir > 0 ? 'desc' : 'asc') : setSort(key)) },
          lbl, h('span', { class: 'vd-th-ind', 'aria-hidden': 'true' }, on ? (v.dir > 0 ? '▲' : '▼') : '')));
    };
    return h('div', { class: 'vd-ctable-wrap' }, h('table', { class: ['vd-ctable', compact && 'is-compact'] },
      h('thead', null, h('tr', null, COLS.map(([k, l]) => th(l, k)))),
      h('tbody', null, page.map((r) => h('tr', { tabindex: '0', class: 'vd-crow', onClick: (e) => { if (!e.target.closest('a,button')) ctx.navigate(`#/college/${r.id}`); }, onKeydown: (e) => { if (e.key === 'Enter' && e.target === e.currentTarget) ctx.navigate(`#/college/${r.id}`); } },
        COLS.map(([k, l]) => h('td', { 'data-label': l }, C[k](r))))))));
  };
  const draw = () => {
    const all = visible();
    const total = all.length;
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (v.page > pages) v.page = pages;
    const page = all.slice((v.page - 1) * PAGE_SIZE, v.page * PAGE_SIZE);
    countEl.textContent = `${fmt.plural(total, 'college')}${v.op === 'operational' ? ' · operational' : v.op && v.op !== 'all' ? '' : ' · any status'}`;
    if (!total) {
      // responsive.md §5: "match" wording only when a filter or search is actually set
      const filtered = filtersActive();
      const addFirst = !fixed && !filtered ? () => openCollegeForm(ctx, null) : null;
      const text = filtered ? 'Clear a filter or the search to see more.'
        : (fixed ? 'No colleges from the master list are in this place yet.' : 'No colleges in the selected districts yet. Add the first one, or pick other districts in the header.');
      let empty = null;
      if (typeof ctx.ui.listEmpty === 'function') {
        try { empty = ctx.ui.listEmpty({ filtered, noun: 'colleges', addLabel: addFirst ? 'Add college' : undefined, onAdd: addFirst || undefined, onClear: clearAll, icon: filtered ? 'search' : 'college', text }); } catch { empty = null; }
      }
      host.replaceChildren(empty || ctx.ui.emptyState({ icon: filtered ? 'search' : 'college', title: filtered ? 'No colleges match these filters' : 'No colleges yet', text,
        action: filtered ? ctx.ui.button({ label: 'Clear filters', tone: 'primary', onClick: clearAll })
          : addFirst ? ctx.ui.writeOnly(ctx.ui.button({ label: 'Add college', icon: 'plus', tone: 'primary', onClick: addFirst })) : null }));
      pagerHost.replaceChildren();
      return;
    }
    if (typeof ctx.ui.dataTable === 'function') {
      host.replaceChildren(ctx.ui.dataTable({
        columns: COLS.map(([k, l]) => ({ key: k, label: l, render: C[k], primary: k === 'name', ...COL_FIT[k] })),
        rows: page, sort: COLS.some(([k]) => k === v.sort) ? { key: v.sort, dir: v.dir > 0 ? 'asc' : 'desc' } : null, onSort: (k, d) => setSort(k, d),
        page: v.page, pageSize: PAGE_SIZE, total, onPage, pageLabel: 'colleges',
        rowHref: (r) => `#/college/${r.id}`, caption: 'Colleges', mobile: 'cards', cardSort: false, // the filter bar has its own Sort
        cardTitle: (r) => h('a', { href: `#/college/${r.id}`, class: 'vd-cname' }, r.short_name || r.name),
        cardSubtitle: (r) => `#${r.sno ?? '—'}${placeOf(r) ? ' · ' + placeOf(r) : ''}`,
        cardMeta: cardBadges,
      }));
      pagerHost.replaceChildren();
      return;
    }
    host.replaceChildren(plainTable(page));
    put(pagerHost, pager(ctx, { page: v.page, pageSize: PAGE_SIZE, total, onPage }));
  };

  const selectEl = (key, label, opts, { any = 'Any', disabled, title } = {}) => h('label', { class: 'vd-field', title: title || null }, h('span', null, label),
    h('select', { class: 'td-input td-select td-input--sm', disabled: disabled ? true : null, onChange: (e) => setV(key, e.target.value) },
      any !== null ? h('option', { value: '' }, any) : null,
      opts.map(([val, t]) => h('option', { value: val, selected: String(v[key] || '') === String(val) ? true : null }, t))));
  function setV(key, val) {
    v[key] = val || undefined;
    if (key === 'op' && !val) v.op = 'operational';
    v.page = 1; save(); drawFilters();
    if (['op', 'diagnosis', 'call_status', 'contact', 'amb', 'progress', 'exam', 'q', 'team'].includes(key)) load(); else draw();
  }
  function clearAll() {
    for (const k of LIST_KEYS) if (!['sort', 'dir'].includes(k)) delete v[k];
    v.op = 'operational'; v.page = 1; search.value = ''; save(); drawFilters(true); load();
  }
  const search = h('input', { type: 'search', class: 'td-input vd-search', placeholder: 'Search name, short name, town…', 'aria-label': 'Search colleges', value: v.q || '',
    onInput: debounce((e) => setV('q', e.target.value.trim()), 300) });
  // primary filters: the shared ui.filterBar (built once per capability set, so typing keeps focus)
  let fbar = null; let fbarCaps = null;
  // phones: every filter goes into the filter bar (it collapses into the "Filters (n)" sheet) and "More filters" is hidden
  const MORE_KEYS = ['targeted', 'diagnosis', 'call_status', 'contact', 'amb', 'progress', 'exam', 'followup'];
  let barKeys = new Set(['team', 'p', 'op', 'verified']);
  const barValues = () => ({ q: v.q || '', team: v.team || '', p: v.p || '', op: v.op === 'operational' ? '' : (v.op || ''), verified: v.verified || '', sort: v.sort === 'priority' ? '' : v.sort,
    ...(barKeys.has('targeted') ? Object.fromEntries(MORE_KEYS.map((k) => [k, v[k] || ''])) : {}) });
  const primaryBar = (force) => {
    if (typeof ctx.ui.filterBar !== 'function') return null;
    const phone = isPhone(ctx);
    const key = `${caps.verified}|${phone}`;
    if (fbar && fbarCaps === key && !force) { fbar.set(barValues(), { silent: true }); return fbar; }
    fbarCaps = key;
    barKeys = new Set(['team', 'p', 'op', 'verified', ...(phone ? MORE_KEYS : [])]);
    fbar = ctx.ui.filterBar({
      search: { key: 'q', placeholder: 'Search name, short name, town…', value: v.q || '', debounce: 300 },
      filters: [
        { key: 'team', label: 'Team', options: TEAM_OPTS },
        { key: 'p', label: 'P-level', options: LABELS.p[1] },
        { key: 'op', label: 'Status', allLabel: 'Status: operational', options: [['all', 'Any status'], ...OP_OPTS.filter(([k]) => k !== 'operational' && k !== 'all')] },
        caps.verified ? { key: 'verified', label: 'Verification', options: VERIFIED_OPTS } : null,
        { key: 'sort', label: 'Sort', allLabel: 'Sort: priority', options: SORTS.filter(([k]) => k !== 'priority') },
        ...(phone ? [
          { key: 'targeted', label: 'Targeted', allLabel: 'All colleges', options: [['1', 'Targeted only']] },
          { key: 'diagnosis', label: 'Main reason', options: LABELS.diagnosis[1] },
          { key: 'call_status', label: 'Calling', options: CALL_STATUS_OPTS },
          { key: 'contact', label: 'Contacts', options: CONTACT_OPTS },
          { key: 'amb', label: 'Coverage', options: AMB_OPTS },
          { key: 'progress', label: 'Progress', options: PROGRESS_OPTS },
          { key: 'exam', label: 'Exams', options: EXAM_OPTS },
          { key: 'followup', label: 'Follow-ups', options: FU_OPTS },
        ] : []),
      ],
      values: barValues(),
      onChange: (vals, k) => {
        if (k === null) { clearAll(); return; }
        if (k === 'sort') { setSort(vals.sort || 'priority'); return; }
        setV(k, vals[k]);
      },
    });
    return fbar;
  };
  const drawFilters = (force) => {
    const bar = primaryBar(force);
    if (bar) { if (bar.parentNode !== filtersHost) put(filtersHost, bar); }
    else put(filtersHost,
      h('div', { class: 'vd-filterbar-search' }, search),
      selectEl('team', 'Team', TEAM_OPTS),
      selectEl('p', 'P-level', LABELS.p[1]),
      selectEl('op', 'Status', OP_OPTS.filter(([k]) => k !== 'all'), { any: 'Any status' }),
      caps.verified ? selectEl('verified', 'Verification', VERIFIED_OPTS) : null,
      selectEl('sort', 'Sort', SORTS, { any: null }));
    const moreN = ['diagnosis', 'call_status', 'contact', 'amb', 'progress', 'exam', 'followup', 'targeted'].filter((k) => v[k]).length;
    put(moreHost, h('details', { class: 'vd-more-filters', open: moreN ? true : null },
      h('summary', null, moreN ? `More filters (${moreN})` : 'More filters'),
      h('div', { class: 'vd-filterbar' },
        selectEl('targeted', 'Targeted', [['1', 'Targeted only']], { any: 'All' }),
        selectEl('diagnosis', 'Main reason behind', LABELS.diagnosis[1]),
        selectEl('call_status', 'Calling status', CALL_STATUS_OPTS),
        selectEl('contact', 'Contact numbers', CONTACT_OPTS),
        selectEl('amb', 'Branch coverage', AMB_OPTS),
        selectEl('progress', 'Progress', PROGRESS_OPTS),
        selectEl('exam', 'Exams', EXAM_OPTS),
        selectEl('followup', 'Follow-ups', FU_OPTS))));
    const chips = [];
    for (const [k, [label, opts]] of Object.entries(LABELS)) {
      if (!v[k] || (k === 'op' && v.op === 'operational')) continue;
      if (fbar && barKeys.has(k)) continue;
      if (k === 'op' && v.op === 'all') { chips.push(chip(`Status: any`, () => setV('op', 'operational'))); continue; }
      const o = opts.find(([x]) => String(x) === String(v[k]));
      chips.push(chip(`${label}: ${o ? o[1] : v[k]}`, () => setV(k, '')));
    }
    if (v.q && !fbar) chips.push(chip(`Search: “${v.q}”`, () => { search.value = ''; setV('q', ''); }));
    put(chipsHost, chips.length ? [...chips, h('button', { type: 'button', class: 'vd-linkbtn', onClick: clearAll }, 'Clear all')] : null);
  };
  const chip = (label, onRemove) => (typeof ctx.ui.chip === 'function' ? ctx.ui.chip({ label, tone: 'brand', onRemove })
    : h('button', { type: 'button', class: 'vd-chip', onClick: onRemove, 'aria-label': `Remove filter ${label}` }, label, ' ×'));

  /* ---------- data ---------- */
  let seq = 0;
  const load = async () => {
    const my = ++seq;
    const p = { q: v.q || undefined, diagnosis: v.diagnosis || undefined, call_status: v.call_status || undefined, contact: v.contact || undefined,
      amb: v.amb || undefined, progress: v.progress || undefined, exam_state: v.exam || undefined };
    if (v.op && v.op !== 'all') p.op_status = v.op;
    if (fixed?.district) p.district = fixed.district;
    if (fixed?.city) p.city = fixed.city;
    if (v.team) p.team = v.team; // v4 servers filter (caps.team then skips the client filter); older ones ignore it and matches() filters
    host.replaceChildren(ctx.ui.skeleton ? ctx.ui.skeleton(6, { card: false }) : loading('Loading colleges…'));
    try {
      const [res, pl] = await Promise.all([
        fixed ? ctx.api.get('/colleges', p) : getScoped(ctx, '/colleges', p),
        planIndex(ctx),
      ]);
      if (my !== seq) return;
      let list = itemsOf(res);
      if (res && !Array.isArray(res) && isNum(res.total) && res.total > list.length) {
        list = itemsOf(await (fixed ? ctx.api.get('/colleges', { ...p, page: 1, page_size: res.total }) : getScoped(ctx, '/colleges', { ...p, page: 1, page_size: res.total })));
        if (my !== seq) return;
      }
      rows = fixed ? list : scopeRows(list);
      plan = pl;
      caps.team = rows.some((r) => 'ambassador_count' in r || ('lead' in r && !('college_lead' in r)));
      caps.verified = rows.some((r) => 'data_status' in r || 'verified_fields' in r);
      caps.unassigned = rows.some((r) => 'unassigned_count' in r);
      // v3 servers have no unassigned_count per college: count from /api/people rows with the same rule (R3), once.
      if (!caps.unassigned && !peopleTried) {
        peopleTried = true;
        try {
          const pr = itemsOf(await (fixed ? ctx.api.get('/people', fixed.district ? { district: fixed.district } : {}) : getScoped(ctx, '/people')));
          const m = new Map();
          for (const x of unassignedOf(pr)) m.set(x.college_id, (m.get(x.college_id) || 0) + 1);
          people = m;
        } catch { people = null; }
        if (my !== seq) return;
      }
      drawFilters();
      draw();
    } catch (err) {
      if (my === seq) host.replaceChildren(errorNote(err, 'colleges'));
    }
  };

  const exportCsv = () => {
    const out = visible();
    const head = ['S.No', 'College', 'Short name', 'District', 'City', 'P-level', 'Status', 'Targeted', 'Verification', 'College lead', 'Ambassador leads', 'Ambassadors',
      'Unassigned ambassadors', 'IT branches without ambassador', 'Target', 'Confirmed', 'Remaining', 'Progress %', 'Status vs target', 'Eligible', 'Eligible basis',
      'Exam state', 'Calling status', 'Open follow-ups', 'Next follow-up'];
    const val = (x) => (x === null || x === undefined ? '' : x);
    const lines = [head, ...out.map((r) => [r.sno, r.name, r.short_name, dName.get(r.district_id) || r.district_id, cName.get(r.city_id) || r.city_id, pLevelOf(r, plan) || '',
      r.op_status, r.targeted ? 'yes' : 'no', verifiedStateOf(r) || '', leadOf(r)?.name || '', val(r.ambassador_leads), ambCount(r), val(unassignedN(r)), val(r.branches_needing_ambassadors),
      r.target > 0 ? r.target : '', val(r.actual ?? r.enrolled), r.target > 0 ? val(r.remaining) : '', isNum(r.pct) && r.target > 0 ? Math.round(r.pct * 1000) / 10 : '',
      r.status || (r.target > 0 ? (r.on_track ? 'on track' : 'behind') : 'no target'), val(r.eligible?.value), r.eligible?.basis || 'pending', val(r.exam_state), val(r.call_status), val(r.followups_open),
      r.next_followup ? (typeof r.next_followup === 'object' ? r.next_followup.due_date : r.next_followup) : ''])];
    // SEC-02: ui.downloadCsv quotes every cell and neutralises spreadsheet formulas (= + - @ TAB CR → leading ')
    downloadCsv(`techdrona-colleges-${today()}.csv`, lines);
    ctx.ui.toast?.(`Exported ${fmt.plural(out.length, 'college')}`, 'good');
  };
  const exportBtn = ctx.ui.button({ label: 'Export CSV', icon: 'data', tone: 'secondary', onClick: exportCsv });

  drawFilters();
  const el = h('div', { class: 'vd-clist' }, filtersHost, moreHost, h('div', { class: 'vd-clist-bar' }, countEl, chipsHost), host, pagerHost);
  onFormFactor(el, () => drawFilters()); // phone <-> tablet: rebuild the bar with / without the extra filters
  return { el, load, exportBtn };
}

/* =====================================================================================
 * #/analytics — Reports (respects the global district scope)
 * ===================================================================================== */
const CHILD = { state: 'district', district: 'city', city: 'college', college: 'branch' };
const LEVEL_TITLE = { district: 'District performance', city: 'City performance', college: 'College performance', branch: 'Branch performance' };
const analytics = { level: 'state', district: '', city: '', college: '', trend: 'cumulative', metric: 'enrolled' };

function scopeString(a) {
  if (a.level === 'district' && a.district) return `district:${a.district}`;
  if (a.level === 'city' && a.city) return `city:${a.city}`;
  if (a.level === 'college' && a.college) return `college:${a.college}`;
  return 'state';
}

export async function renderAnalytics(el, params, ctx) {
  setCrumbs(ctx, [{ label: 'Home', href: '#/' }, { label: 'Reports', href: '#/analytics' }]);
  mount(el, 'v-analytics', loading());
  const meta = await ctx.api.get('/meta').catch(() => ({ districts: [], cities: [] }));
  // "Look at" persists in the URL (UI-18); districts outside the scope are not offered.
  const q = params || {};
  if (q.level) Object.assign(analytics, { level: String(q.level), district: String(q.district || ''), city: String(q.city || ''), college: String(q.college || '') });
  if (analytics.district && !inScope(analytics.district)) Object.assign(analytics, { level: 'state', district: '', city: '', college: '' });
  const scopeBar = h('div', { class: 'vd-scopebar', role: 'group', 'aria-label': 'Choose what to report on' });
  const body = h('div', { class: 'va-body' });
  let collegeOpts = [];
  const persist = () => replaceHashQuery('#/analytics', analytics.level === 'state' ? {} : { level: analytics.level, district: analytics.district, city: analytics.city, college: analytics.college });

  const sel = (label, options, value, onChange, disabled) => h('label', { class: 'vd-field' }, h('span', null, label),
    h('select', { class: 'td-input td-select td-input--sm', disabled: disabled ? true : null, onChange: (e) => onChange(e.target.value) },
      options.map(([v, t]) => h('option', { value: v, selected: String(value || '') === String(v) ? true : null }, t))));
  const inScopeDistricts = () => (meta.districts || []).filter((d) => inScope(d.id)).sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const drawScopeBar = () => {
    const a = analytics;
    const cities = (meta.cities || []).filter((c) => c.district_id === a.district).sort((x, y) => String(x.name).localeCompare(String(y.name)));
    const sc = getScope();
    put(scopeBar,
      sel('Report on', [['state', sc.all ? 'All districts' : 'Selected districts'], ['district', 'One district'], ['city', 'One city or town'], ['college', 'One college']], a.level, (v) => { a.level = v; persist(); drawScopeBar(); refresh(); }),
      a.level !== 'state' ? sel('District', [['', 'Choose a district'], ...inScopeDistricts().map((d) => [d.id, d.name])], a.district, async (v) => {
        a.district = v; a.city = ''; a.college = '';
        if (a.level === 'college' && v) collegeOpts = itemsOf(await ctx.api.get('/colleges', { district: v }).catch(() => []));
        persist(); drawScopeBar(); refresh();
      }) : null,
      a.level === 'city' ? sel('City', [['', 'Choose a city'], ...cities.map((c) => [c.id, c.name])], a.city, (v) => { a.city = v; persist(); refresh(); }, !a.district) : null,
      a.level === 'college' ? sel('College', [['', 'Choose a college'], ...collegeOpts.map((c) => [c.id, c.short_name || c.name])], a.college, (v) => { a.college = v; persist(); refresh(); }, !a.district) : null,
      h('span', { class: 'vd-grow' }), scopePill(ctx));
  };

  let seq = 0;
  const refresh = async () => {
    const my = ++seq;
    const scope = scopeString(analytics);
    const level = scope.split(':')[0];
    body.replaceChildren(typeof ctx.ui.skeleton === 'function' ? h('div', { class: 'vd-skel', role: 'status', 'aria-label': 'Loading reports' }, ctx.ui.skeleton(2), h('div', { class: 'va-grid' }, ctx.ui.skeleton(5), ctx.ui.skeleton(5))) : loading('Loading reports…'));
    const child = CHILD[level];
    // state level = the selected districts (districts=); a district/city/college is already inside the selection.
    const G = (path, p) => (level === 'state' ? getScoped(ctx, path, p) : ctx.api.get(path, p));
    const collegeParams = level === 'district' ? { district: scope.slice(9) } : level === 'city' ? { city: scope.slice(5) } : {};
    const { data, errors } = await fetchAll({
      summary: G('/summary', { scope }),
      road: G('/target-dashboard', { scope }),
      geo: G('/leaderboard', { level: child, scope, limit: 200 }),
      cities: level === 'state' || level === 'district' ? G('/leaderboard', { level: 'city', scope, limit: 200 }) : Promise.resolve(null),
      colleges: level !== 'college' ? G('/leaderboard', { level: 'college', scope, limit: 500 }) : Promise.resolve(null),
      branches: G('/leaderboard', { level: 'branch', scope, limit: 500 }),
      persons: G('/leaderboard', { level: 'person', scope, limit: 500 }),
      ts: G('/timeseries', { scope, days: 60 }),
      collegeRows: level !== 'college' ? G('/colleges', collegeParams) : Promise.resolve(null),
      plan: level === 'state' ? getScoped(ctx, '/plan') : Promise.resolve(null),
      perf: level === 'state' ? getPerformance(ctx, { level: 'college', period: 'programme' }) : Promise.resolve(null),
    });
    if (my !== seq) return;
    const S = data.summary;
    if (!S) { body.replaceChildren(errorNote(errors.summary, 'reports for this selection')); return; }
    if (level === 'state' && data.geo) data.geo = data.geo.filter((r) => inScope(rowId(r)));
    const collegeRows = level === 'college' ? [S] : scopeRows(itemsOf(data.collegeRows));
    const nothingYet = !(S.target > 0) && !(S.enrolled > 0) && !(S.reached > 0) && !(data.persons || []).length;
    const T = data.road;
    const funnelSec = sectionEl(ctx, 'Eligible → reached → confirmed', funnel({
      label: 'Conversion funnel', renderBasis: (b) => ctx.ui.provenance(b),
      steps: [
        { label: 'Eligible students', value: S.eligible ? S.eligible.value : null, basis: S.eligible ? S.eligible.basis : 'pending', hint: 'Final-year students in relevant branches' },
        { label: 'Students reached', value: S.reached ?? null, basis: 'verified', hint: S.reached > 0 ? null : 'Log visits and sessions from a college page to count students reached' },
        { label: 'Confirmed', value: S.enrolled ?? null, basis: 'verified', hint: S.enrolled > 0 ? null : 'Record enrollments from a college page' },
      ],
    }), null, 'How many eligible students the team has reached and enrolled');
    const grid = nothingYet
      ? h('div', { class: 'va-grid' },
        sectionEl(ctx, 'Nothing to report yet', h('div', { class: 'va-start' },
          h('p', null, `No targets, outreach or enrollments are recorded for ${S.label || 'this selection'} yet. Charts and rankings appear as soon as the team adds real records.`),
          h('ol', { class: 'va-start-steps' },
            h('li', null, h('a', { href: '#/targets' }, 'Set a target'), ' to compare progress across districts, cities and colleges.'),
            h('li', null, h('a', { href: '#/colleges?team=no_lead&targeted=1' }, 'Appoint leads and ambassadors'), ' from a college page to rank the team.'),
            h('li', null, h('a', { href: '#/colleges' }, 'Log outreach and enrollments'), ' to see the trend and conversion.')))),
        funnelSec)
      : h('div', { class: 'va-grid' },
        sectionEl(ctx, LEVEL_TITLE[child] || 'Performance', geoChart(ctx, child, data.geo, errors.geo), null, 'Confirmed against target; click a bar to open it'),
        sectionEl(ctx, 'Trend (last 60 days)', trendBlock(ctx, data.ts, errors.ts, S)),
        funnelSec,
        sectionEl(ctx, 'Why colleges are behind', diagnosisBlock(ctx, collegeRows, errors.collegeRows), null, 'Main reason for each college that is behind pace'),
        data.cities ? sectionEl(ctx, 'City leaderboard', leaderTable(ctx, 'city', level === 'state' ? data.cities.filter((r) => inScope(r.district_id || String(rowId(r)).split('--')[0])) : data.cities, { limit: 10 })) : null,
        data.colleges ? sectionEl(ctx, 'College leaderboard', topBottom(ctx, level === 'state' ? data.colleges.filter((r) => !r.district_id || inScope(r.district_id)) : data.colleges)) : null,
        sectionEl(ctx, 'Branch leaderboard', data.branches ? leaderTable(ctx, 'branch', data.branches, { limit: 10 }) : errorNote(errors.branches, 'branches')),
        sectionEl(ctx, 'Team leaderboards', peopleBoards(ctx, data.persons, errors.persons)));
    body.replaceChildren(
      h('div', { class: 'va-headline td-card' },
        h('h2', null, level === 'state' ? (getScope().all ? 'All districts' : scopeLabel({ max: 5 })) : (S.label || 'Selection')),
        h('div', { class: 'vd-kpis vd-kpis-tight' },
          kpi(ctx, { label: 'Target', value: S.target > 0 ? S.target : null, notSet: noTargetReason(T, S) ? 'No target for this selection' : 'Not set yet', icon: 'target', sub: S.target > 0 ? targetSourceText(S) : null, href: S.target > 0 ? undefined : '#/targets' }),
          kpi(ctx, { label: 'Confirmed', value: S.enrolled, icon: 'check' }),
          kpi(ctx, { label: S.target > 0 && S.enrolled > S.target ? 'Exceeded by' : 'Remaining', value: S.target > 0 ? (S.enrolled > S.target ? S.enrolled - S.target : S.remaining) : null, notSet: 'Needs a target', icon: 'clock' }),
          kpi(ctx, { label: 'Achieved', value: S.target > 0 ? S.pct : null, notSet: 'Needs a target', format: pctText, tone: S.target > 0 ? (S.on_track === true ? 'good' : S.on_track === false ? 'warn' : undefined) : undefined, sub: S.target > 0 ? daysLeftText(T && T.days_left, S.deadline) : null }),
          kpi(ctx, { label: 'Students reached', value: S.reached, icon: 'people' }),
          kpiB(ctx, 'Eligible students', S.eligible, { icon: 'people' })),
        coverageNote(ctx, S, data.geo, collegeRows, data.perf, child),
        S.target > 0 ? h('div', { class: 'va-pace' },
          paceMeter({ done: S.enrolled ?? 0, target: S.target, expected: S.expected_now, label: `${S.label || 'Selection'} progress to target` }),
          h('div', { class: 'va-pace-meta' }, statusNode(ctx, S),
            S.on_track === false && S.diagnosis ? ctx.ui.statusBadge('diagnosis', S.diagnosis) : null,
            S.on_track === false && S.diagnosis && DIAG_INFO[S.diagnosis] ? h('span', { class: 'vd-muted vd-small' }, DIAG_INFO[S.diagnosis].text) : null)) : null),
      T ? roadBlock(ctx, T) : null,
      grid,
      level === 'state' ? h('div', { class: 'va-grid' },
        recruitCard(ctx, data.plan, S, errors.plan),
        sectionEl(ctx, 'Districts', districtList(ctx, { ...meta, districts: (meta.districts || []).filter((d) => inScope(d.id)) }, collegeRows, data.geo || []), scopeChangeBtn(ctx), 'Selected districts; open one for its summary and colleges')) : null,
      keyFacts(ctx, S),
      sectionEl(ctx, 'Courses', courseBreakdown(ctx, S.by_course)));
  };

  const head = typeof ctx.ui.pageHeader === 'function'
    ? ctx.ui.pageHeader({ title: 'Reports', sub: 'Progress, pace, trend, conversion and rankings for the selected districts. Numbers come from the server; nothing is estimated here.' })
    : h('header', { class: 'vd-pagehead' }, h('h1', null, 'Reports'));
  mount(el, 'v-analytics', head, scopeBar, body);
  if (analytics.level === 'college' && analytics.district) collegeOpts = itemsOf(await ctx.api.get('/colleges', { district: analytics.district }).catch(() => []));
  drawScopeBar();
  await refresh();
}

function targetSourceText(S) {
  if (S.target_source === 'sum_of_children') return 'sum of lower-level targets';
  if (S.target_source === 'explicit' || S.target_source === 'program') return 'set directly';
  return null;
}

/** TG-01: a rolled-up target only covers places that have a target; say how many, and how much came from the rest. */
function coverageNote(ctx, S, geo, collegeRows, perf, child) {
  if (!(S.target > 0) || S.target_source !== 'sum_of_children') return null;
  const totals = perf && perf.totals && perf.totals.covers ? perf.totals.covers : null;
  let withT, total, label;
  if (totals) { withT = totals.with_target; total = totals.total; label = 'colleges'; }
  else if (Array.isArray(geo) && geo.length) { withT = geo.filter((r) => r.target > 0).length; total = geo.length; label = child === 'city' ? 'cities' : child === 'college' ? 'colleges' : child === 'branch' ? 'branches' : 'districts'; }
  else { withT = collegeRows.filter((r) => r.target > 0).length; total = collegeRows.length; label = 'colleges'; }
  const outside = Array.isArray(geo) ? geo.filter((r) => !(r.target > 0)).reduce((a, r) => a + (r.enrolled || 0), 0) : 0;
  return h('p', { class: 'va-cover', role: 'note' }, ctx.ui.icon('info', { size: 16 }),
    h('span', null, `This target is the sum of lower-level targets and covers ${fmt.num(withT)} of ${fmt.num(total)} ${label}.`,
      outside > 0 ? ` ${fmt.plural(outside, 'confirmed enrollment')} came from ${label} without a target, so the % may overstate progress.` : ''));
}

/* "Road to {target}": confirmed vs target, required vs current pace, projection, funnel, calling and people (GET /api/target-dashboard). */
const ROLE_SHORT = { college_lead: 'College lead', ambassador_lead: 'Amb. lead', ambassador: 'Ambassador' };
export function roadBlock(ctx, T) {
  const hasTarget = T.target > 0;
  const num = (label, value, note) => h('div', { class: 'vdr-num' }, h('dt', null, label), h('dd', null, value), note ? h('small', null, note) : null);
  const P = T.projection || {};
  const projTone = P.status === 'after_deadline' ? 'is-bad' : P.status === 'on_or_before_deadline' || P.status === 'achieved' ? 'is-good' : null;
  const behind = hasTarget && T.required_weekly != null && T.current_weekly < T.required_weekly;
  const f = T.funnel || { stages: [] };
  const max = Math.max(1, ...f.stages.filter((s) => s.stage !== 'dropped').map((s) => s.count));
  const bars = h('ol', { class: 'vdr-bars', 'aria-label': 'Students by current stage' }, f.stages.filter((s) => s.stage !== 'dropped').map((s) => h('li', { class: ['vdr-bar', s.counts_toward_target && 'is-target'] },
    h('span', { class: 'vdr-bar-l' }, s.label, s.counts_toward_target ? h('small', null, ' · counts toward target') : null),
    h('span', { class: 'vdr-bar-v td-num' }, fmt.num(s.count)),
    h('span', { class: 'vdr-bar-t', 'aria-hidden': 'true' }, s.count > 0 ? h('span', { style: { width: Math.max(2, (s.count / max) * 100) + '%' } }) : null))));
  const dropped = f.stages.find((s) => s.stage === 'dropped')?.count || 0;
  const k = T.contacts || {}; const c = T.calls || {}; const p = T.pending_calls || {};
  const factsList = (items) => h('ul', { class: 'vdr-facts' }, items.map(([v, l, href]) => h('li', null, href ? h('a', { href, class: 'vd-link' }, h('b', null, fmt.num(v))) : h('b', null, fmt.num(v)), h('span', null, l))));
  const exceeded = hasTarget && T.confirmed > T.target ? T.confirmed - T.target : 0;
  return h('section', { class: 'vdr td-card', 'aria-labelledby': 'vdr-title' },
    h('div', { class: 'vdr-head' },
      h('div', null,
        h('h2', { id: 'vdr-title', class: 'vdr-title' }, hasTarget ? `Road to ${fmt.num(T.target)}` : 'Road to the target'),
        h('p', { class: 'vdr-sub' }, 'Only confirmed enrollments count toward the target. Leads, interested, registered and applied students are shown separately.')),
      h('a', { href: '#/calls', class: 'td-btn td-btn--secondary td-btn--sm' }, ctx.ui.icon('phone', { size: 16 }), h('span', null, 'Open calling'))),
    h('dl', { class: 'vdr-nums' },
      num('Target', hasTarget ? fmt.num(T.target) : 'Not set', hasTarget && T.deadline ? `deadline ${fmt.date(T.deadline)}` : null),
      num('Confirmed', fmt.num(T.confirmed)),
      num(exceeded ? 'Exceeded by' : 'Remaining', hasTarget ? fmt.num(exceeded || T.remaining) : '—'),
      num('Achieved', hasTarget ? pctText(T.pct) : '—')),
    hasTarget ? h('div', { class: 'vdr-pace' },
      h('div', { class: behind ? 'is-bad' : null }, h('span', null, 'Needed from today'), h('strong', null, T.deadline_passed ? 'Deadline passed' : `${rateText(T.required_weekly)} / week`),
        h('span', null, T.deadline_passed ? daysLeftText(T.days_left, T.deadline) : `${rateText(T.required_daily)} a day · ${daysLeftText(T.days_left, null)}`)),
      h('div', { class: behind ? 'is-bad' : T.current_weekly > 0 ? 'is-good' : null }, h('span', null, 'Current pace (last 14 days)'), h('strong', null, `${rateText(T.current_weekly)} / week`),
        h('span', null, `${fmt.plural(T.confirmed_last_14d, 'confirmed enrollment')} in 14 days`)),
      h('div', { class: projTone }, h('span', null, 'Projected completion'), h('strong', null, P.date ? fmt.date(P.date) : P.status === 'achieved' ? 'Reached' : 'Not enough data'),
        h('span', null, P.explanation || ''))) : noTargetReason(T) ? h('p', { class: 'vdr-empty' }, `No target for this selection. ${noTargetReason(T)}`)
      : h('p', { class: 'vdr-empty' }, 'No target is set yet, so pace and projection cannot be shown. ', h('a', { href: '#/targets' }, 'Set the programme target'), '.'),
    h('div', { class: 'vdr-grid' },
      h('div', null, h('h3', { class: 'vdr-h3' }, 'Student pipeline'),
        f.total ? bars : h('p', { class: 'vdr-empty' }, 'No student records yet. Open a college and use “Record enrollment”: save a lead as soon as a student shows interest, then move the same record forward.'),
        f.total ? h('p', { class: 'vdr-note' }, `Each student is counted once, at their current stage.${dropped ? ` ${fmt.plural(dropped, 'student')} dropped or refunded (not counted).` : ''}`) : null),
      h('div', null, h('h3', { class: 'vdr-h3' }, 'Calling'),
        k.total ? factsList([[k.working, 'working numbers', '#/calls?filter=working'], [(k.non_working || 0) + (k.invalid || 0), 'not working / invalid', '#/calls?filter=invalid'], [k.untested, 'not called yet'], [k.colleges_without_contact, 'colleges with no contact']])
          : h('p', { class: 'vdr-empty' }, 'No contacts recorded yet. Add numbers on a college page (Contacts & calls).'),
        factsList([[c.today, 'calls today'], [c.last_7d, 'calls in 7 days'], [p.callbacks_due, 'call-backs due', '#/calls?filter=pending'], [T.followups_due, 'follow-ups due', '#/followups']]))),
    h('div', null, h('h3', { class: 'vdr-h3' }, 'Leads & ambassadors by confirmed enrollments'),
      (T.people || []).length ? h('ol', { class: 'vdr-people' }, T.people.slice(0, 5).map((x) => h('li', null,
        h('span', null, h('a', { href: x.href || `#/person/${x.id}` }, x.full_name), h('span', { class: 'vd-muted' }, ` · ${ROLE_SHORT[x.role] || x.role}${x.college_label ? `, ${x.college_label}` : ''}`)),
        h('span', { class: 'td-num' }, h('b', null, fmt.num(x.confirmed)), x.target != null ? ` / ${fmt.num(x.target)}` : '', x.in_pipeline ? h('span', { class: 'vd-muted' }, ` · ${fmt.num(x.in_pipeline)} in pipeline`) : null))))
        : h('p', { class: 'vdr-empty' }, 'No college leads or ambassadors yet. ', h('a', { href: '#/colleges?team=no_lead&targeted=1' }, 'Open a college'), ' to appoint them; credit each enrollment to the person who brought it.')));
}

/* Recruitment structure: College Leads / Ambassadors required (research model, GET /api/plan) vs recruited (people records). */
function recruitCard(ctx, plan, S, err) {
  const T = plan && plan.totals_research;
  const A = plan && plan.totals_actual;
  const leadsHave = A ? A.college_leads : (S.college_leads ?? null);
  const ambHave = A ? (A.ambassadors ?? 0) + (A.ambassador_leads ?? 0) : (S.ambassadors ?? 0) + (S.ambassador_leads ?? 0);
  const row = (label, need, have, hint) => h('div', { class: 'vdq-row' },
    h('div', { class: 'vdq-row-head' }, h('strong', null, label),
      h('span', { class: 'vdq-nums td-num' }, h('b', null, have === null ? '—' : fmt.num(have)), ' recruited', isNum(need) ? ` of ${fmt.num(need)} needed` : '')),
    isNum(need) && need > 0 ? h('span', { class: 'vdq-bar', role: 'progressbar', 'aria-label': `${label} recruited`, 'aria-valuemin': '0', 'aria-valuemax': String(need), 'aria-valuenow': String(have || 0) },
      h('span', { style: { width: `${Math.min(100, ((have || 0) / need) * 100)}%` } })) : null,
    h('span', { class: 'vd-muted vd-small vdq-hint' }, hint, isNum(need) ? ctx.ui.provenance('estimated') : null));
  const est = T && isNum(T.avg) ? h('p', { class: 'vdq-est' },
    'Research estimate for these colleges: ', h('b', { class: 'td-num' }, `${fmt.num(T.min)}–${fmt.num(T.max)}`), ' paid enrollments (average ',
    h('b', { class: 'td-num' }, fmt.num(T.avg)), ') ', ctx.ui.provenance('estimated')) : null;
  const note = !T ? h('p', { class: 'vd-muted vd-small' }, err ? `Could not load the planner numbers (${err.message || 'error'}).` : 'No planner numbers for these districts yet.') : null;
  return ctx.ui.section({ title: 'Recruitment structure', actions: h('a', { href: '#/plan', class: 'vd-link' }, 'Target planner'),
    sub: 'Each college has one student College Lead, with Student Ambassadors reporting to the lead.',
    body: h('div', { class: 'vdq' }, note,
      row('College Leads', T ? T.college_leads : null, leadsHave, T ? 'Needed (research model) ' : 'Recruited so far'),
      row('Student Ambassadors', T ? T.ambassadors : null, ambHave, T ? 'Needed (research model, incl. ambassador leads) ' : 'Including ambassador leads'),
      est) });
}

/** Compact stat list: label, value, sub/provenance. Links when there is somewhere useful to go. */
function fact(ctx, { label, value, sub, basis, tone, href, format = fmt.num }) {
  const unknown = value === null || value === undefined || (typeof value === 'number' && Number.isNaN(value));
  const tag = href ? 'a' : 'div';
  return h('li', null, h(tag, { class: ['vd-fact', tone && `is-${tone}`, href && 'is-link'], href: href || null },
    h('span', { class: 'vd-fact-label' }, label),
    h('span', { class: 'vd-fact-value' }, unknown ? '—' : format(value), href ? ctx.ui.icon('chevron', { size: 14, class: 'vd-fact-go' }) : null),
    (sub || basis || unknown) ? h('span', { class: 'vd-fact-sub' }, sub ? h('span', null, sub) : null, (basis || unknown) ? ctx.ui.provenance(unknown ? 'pending' : basis) : null) : null));
}

function keyFacts(ctx, S) {
  const ex = S.exams || {};
  const of = (n, what) => (isNum(n) ? `of ${fmt.num(n)} ${what}` : null);
  const group = (title, items) => h('section', { class: 'vd-factgroup td-card', 'aria-label': title },
    h('h2', { class: 'vd-h2' }, title), h('ul', { class: 'vd-facts' }, items));
  return h('div', { class: 'vd-factgrid' },
    group('Colleges & students', [
      fact(ctx, { label: 'Operational colleges', value: S.operational_colleges, sub: of(S.colleges, 'listed'), href: '#/colleges' }),
      fact(ctx, { label: 'Targeted colleges', value: S.targeted_colleges, sub: 'chosen for outreach', href: '#/colleges?targeted=1' }),
      fact(ctx, { label: 'Relevant branches', value: S.branches_relevant, sub: of(S.branches, 'branches') }),
      fact(ctx, { label: 'Relevant students', value: S.relevant_students?.value ?? null, basis: S.relevant_students?.basis, sub: 'IT, allied & circuit branches' }),
      fact(ctx, { label: 'Eligible students', value: S.eligible?.value ?? null, basis: S.eligible?.basis, sub: 'final-year, likely to enrol' }),
    ]),
    group('Team', [
      fact(ctx, { label: 'Colleges with a lead', value: S.colleges_with_lead, sub: of(S.targeted_colleges, 'targeted'), href: '#/colleges?team=has_lead' }),
      fact(ctx, { label: 'Ambassador leads', value: S.ambassador_leads, href: '#/people?role=ambassador_lead' }),
      fact(ctx, { label: 'Ambassadors', value: S.ambassadors, href: '#/people?role=ambassador' }),
      fact(ctx, { label: 'Branches covered', value: S.branches_with_ambassadors, sub: of(S.branches_relevant, 'relevant') }),
      fact(ctx, { label: 'Branches needing ambassadors', value: S.branches_needing_ambassadors, tone: S.branches_needing_ambassadors > 0 ? 'warn' : undefined,
        sub: S.branches_needing_ambassadors > 0 ? 'Show colleges with gaps' : 'All covered', href: '#/colleges?amb=gap' }),
    ]),
    group('Follow-ups & exams', [
      fact(ctx, { label: 'Open follow-ups', value: S.followups_open, href: '#/followups' }),
      fact(ctx, { label: 'Overdue follow-ups', value: S.followups_overdue, tone: S.followups_overdue > 0 ? 'bad' : undefined, href: '#/followups?tab=overdue' }),
      fact(ctx, { label: 'Colleges in exams now', value: ex.in_exams ?? null, sub: 'avoid visits', href: '#/colleges?exam=in_exams' }),
      fact(ctx, { label: 'Exams within 14 days', value: ex.exams_soon ?? null, href: '#/colleges?exam=exams_soon' }),
      fact(ctx, { label: 'Exam dates unknown', value: ex.unknown ?? null, sub: 'need checking', href: '#/exams' }),
    ]));
}

function districtList(ctx, meta, colleges, lb) {
  const counts = new Map();
  for (const c of colleges) {
    const k = c.district_id; if (!k) continue;
    const o = counts.get(k) || { total: 0, targeted: 0 };
    o.total++; if (c.targeted) o.targeted++;
    counts.set(k, o);
  }
  const lbMap = new Map((lb || []).map((r) => [rowId(r), r]));
  const rows = (meta.districts || []).map((d) => ({ ...d, ...(counts.get(d.id) || { total: 0, targeted: 0 }), lb: lbMap.get(d.id) || null }))
    .sort((a, b) => {
      const at = a.lb && a.lb.target > 0, bt = b.lb && b.lb.target > 0;
      if (at !== bt) return at ? -1 : 1;
      if (at) return (b.lb.pct ?? 0) - (a.lb.pct ?? 0);
      return (b.targeted - a.targeted) || String(a.name).localeCompare(String(b.name));
    });
  if (!rows.length) return ctx.ui.emptyState({ title: 'No districts selected', text: 'Pick districts in the header to see them here.' });
  return h('ul', { class: 'vd-dlist' }, rows.map((d) => h('li', null,
    h('a', { href: `#/d/${d.id}`, class: ['vd-drow', !d.targeted && 'is-dim'] },
      h('div', { class: 'vd-drow-name' }, h('strong', null, d.name),
        h('span', { class: 'vd-muted vd-small' }, d.targeted ? `${fmt.plural(d.targeted, 'targeted college')}` : (d.total ? `${fmt.plural(d.total, 'college')}, none targeted` : 'No operational colleges listed'))),
      h('div', { class: 'vd-drow-prog' }, d.lb && d.lb.target > 0 ? progressNode(ctx, d.lb)
        : h('span', { class: 'vd-muted vd-small' }, d.lb && d.lb.enrolled > 0 ? `${fmt.num(d.lb.enrolled)} confirmed · no target` : 'No target yet')),
      h('div', { class: 'vd-drow-status' }, d.lb && d.lb.target > 0 ? statusNode(ctx, d.lb) : null)))));
}

function courseBreakdown(ctx, byCourse) {
  const rows = byCourse || [];
  if (!rows.length) {
    return ctx.ui.emptyState({ icon: 'target', title: 'No courses yet', text: 'Add your courses and prices in Settings to see enrollments and revenue by course.',
      action: h('a', { href: '#/settings', class: 'td-btn td-btn--secondary' }, 'Add courses') });
  }
  const total = rows.reduce((a, r) => a + (r.revenue_inr || 0), 0);
  return h('div', { class: 'vd-course' },
    ctx.ui.table({
      columns: [
        { key: 'name', label: 'Course' },
        { key: 'price_inr', label: 'Price', align: 'right', render: (r) => fmt.inr(r.price_inr) },
        { key: 'target', label: 'Target', align: 'right', render: (r) => (r.target > 0 ? fmt.num(r.target) : '—') },
        { key: 'enrolled', label: 'Confirmed', align: 'right', render: (r) => fmt.num(r.enrolled ?? 0) },
        { key: 'revenue_inr', label: 'Revenue', align: 'right', render: (r) => fmt.inr(r.revenue_inr) },
      ],
      rows, empty: 'No courses yet',
    }),
    h('p', { class: 'vd-total' }, 'Total revenue recorded: ', h('strong', null, fmt.inr(total))));
}

function sortLb(rows) {
  return [...(rows || [])].sort((a, b) => {
    const at = a.target > 0, bt = b.target > 0;
    if (at !== bt) return at ? -1 : 1;
    if (at) return (b.pct ?? 0) - (a.pct ?? 0) || (b.enrolled ?? 0) - (a.enrolled ?? 0);
    return (b.enrolled ?? 0) - (a.enrolled ?? 0);
  });
}

function geoChart(ctx, level, rows, err) {
  if (err) return errorNote(err, 'performance');
  const list = sortLb(rows).filter((r) => r.target > 0 || r.enrolled > 0).slice(0, 30);
  const chart = barChart({
    label: LEVEL_TITLE[level] || 'Performance', valueLabel: 'Confirmed', secondaryLabel: 'Target',
    data: list.map((r) => ({ label: rowLabel(r), value: r.enrolled ?? 0, secondary: r.target > 0 ? r.target : null, href: hrefFor(level, r) })),
    onClick: (d) => d.href && ctx.navigate(d.href),
    empty: 'No targets or enrollments here yet. Set targets to compare performance.',
  });
  return list.length && list.length < (rows || []).length ? h('div', null, chart, h('p', { class: 'vd-muted vd-small' }, `Showing ${list.length} with a target or enrollments, of ${(rows || []).length}.`)) : chart;
}

function trendBlock(ctx, ts, err, S) {
  if (err) return errorNote(err, 'the trend');
  const host = h('div', { class: 'va-chart', 'aria-live': 'polite' });
  const rows = ts || [];
  const hasCum = rows.some((r) => 'cum_enrolled' in r);
  if (!hasCum && analytics.trend === 'cumulative') analytics.trend = 'weekly';
  // TG-06: the trend stops at today; the headline counts every confirmed record. Say so when they differ.
  const lastCum = hasCum && rows.length ? rows[rows.length - 1].cum_enrolled : null;
  const gap = isNum(lastCum) && isNum(S && S.enrolled) && lastCum !== S.enrolled ? S.enrolled - lastCum : 0;
  const draw = () => {
    const m = analytics.metric;
    const name = m === 'enrolled' ? 'Confirmed enrollments' : 'Students reached';
    if (!rows.some((r) => (r[m] ?? 0) > 0)) {
      host.replaceChildren(emptyChart(`No ${m === 'enrolled' ? 'enrollments' : 'outreach'} recorded in the last 60 days.`, { action: { label: m === 'enrolled' ? 'Record an enrollment' : 'Log outreach', href: '#/colleges' } }));
      return;
    }
    if (analytics.trend === 'cumulative') {
      const key = m === 'enrolled' ? 'cum_enrolled' : 'cum_reached';
      host.replaceChildren(lineChart({ label: `${name}, running total`, series: [{ name: `${name} so far`, points: rows.map((r) => ({ x: r.date, y: r[key] ?? null })) }] }));
      return;
    }
    let points = rows.map((r) => ({ x: r.date, y: r[m] ?? 0 }));
    if (analytics.trend === 'weekly') {
      const wk = new Map();
      for (const p of points) {
        const d = new Date(String(p.x).slice(0, 10) + 'T00:00:00Z');
        if (Number.isNaN(d.getTime())) continue;
        d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); // Monday
        const k = d.toISOString().slice(0, 10);
        wk.set(k, (wk.get(k) || 0) + (p.y || 0));
      }
      points = [...wk.entries()].sort().map(([x, y]) => ({ x, y }));
    }
    host.replaceChildren(columnChart({ label: `${name} per ${analytics.trend === 'weekly' ? 'week' : 'day'}`, name, points,
      xLabel: analytics.trend === 'weekly' ? (x) => `Week of ${fmt.date(x)}` : undefined }));
  };
  // in-page filter → the shared segmented control (responsive.md §7); local fallback for older shells
  const seg = (key, label, opts) => (typeof ctx.ui.segmented === 'function'
    ? ctx.ui.segmented({ options: opts.map(([value, t]) => ({ value, label: t })), value: analytics[key], ariaLabel: label, size: 'sm', onChange: (v) => { analytics[key] = v; draw(); } })
    : segFallback(key, label, opts));
  const segFallback = (key, label, opts) => h('div', { class: 'vd-seg', role: 'group', 'aria-label': label }, opts.map(([v, t]) => h('button', {
    type: 'button', class: ['vd-seg-btn', analytics[key] === v && 'is-on'], 'aria-pressed': analytics[key] === v ? 'true' : 'false',
    onClick: (e) => { analytics[key] = v; e.currentTarget.parentNode.querySelectorAll('button').forEach((b) => { const on = b === e.currentTarget; b.classList.toggle('is-on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false'); }); draw(); },
  }, t)));
  draw();
  return h('div', null, h('div', { class: 'va-toggles' },
    seg('metric', 'Measure', [['enrolled', 'Confirmed'], ['reached', 'Reached']]),
    seg('trend', 'View', [...(hasCum ? [['cumulative', 'Total']] : []), ['weekly', 'Per week'], ['daily', 'Per day']])), host,
  gap ? h('p', { class: 'vd-muted vd-small va-cover' }, ctx.ui.icon('info', { size: 14 }),
    ` The running total ends at ${fmt.num(lastCum)} while the headline shows ${fmt.num(S.enrolled)}: the trend counts records dated up to today, the headline counts every confirmed record${gap > 0 ? ' (including any dated after today)' : ''}.`) : null);
}

function diagnosisBlock(ctx, rows, err) {
  if (err) return errorNote(err, 'diagnosis');
  const withTarget = (rows || []).filter((r) => r.target > 0);
  const behind = withTarget.filter((r) => r.on_track === false);
  const counts = new Map();
  behind.forEach((r) => { const k = DIAG_INFO[r.diagnosis] ? r.diagnosis : 'behind_pace'; counts.set(k, (counts.get(k) || 0) + 1); });
  if (!withTarget.length) return emptyChart('No colleges have targets yet, so there is nothing to diagnose.', { action: { label: 'Set targets', href: '#/targets' } });
  if (!behind.length) return h('div', { class: 'vd-allgood' }, ctx.ui.badge('All on track', 'good'), h('p', { class: 'vd-muted' }, `All ${fmt.plural(withTarget.length, 'college')} with targets are on pace.`));
  const data = DIAG_ORDER.filter((k) => counts.get(k)).map((k) => ({ key: k, label: DIAG_INFO[k].title, value: counts.get(k), sub: DIAG_INFO[k].text }))
    .sort((a, b) => b.value - a.value);
  return h('div', null,
    barChart({ label: 'Why colleges are behind', valueLabel: 'Colleges', data, max: Math.max(...data.map((d) => d.value)),
      onClick: (d) => goColleges(ctx, 'diagnosis', d.key) }),
    h('p', { class: 'vd-muted vd-small' }, `${fmt.num(behind.length)} of ${fmt.plural(withTarget.length, 'college')} with targets are behind pace. `,
      h('a', { class: 'vd-link', href: '#/colleges?progress=behind' }, 'Show them')));
}

function leaderTable(ctx, level, rows, { limit = 10, reverse = false } = {}) {
  if (!(rows || []).some((r) => r.target > 0 || r.enrolled > 0)) return emptyChart('Nothing to rank yet. Rankings appear once targets or enrollments exist here.', { action: { label: 'Set targets', href: '#/targets' } });
  let list = sortLb(rows);
  if (reverse) list = list.filter((r) => r.target > 0).reverse();
  list = list.slice(0, limit);
  return h('ol', { class: 'va-rank' }, list.map((r, i) => {
    const href = hrefFor(level, r);
    const sub = r.sub || r.college_name || null;
    return h('li', null, h(href ? 'a' : 'div', { class: 'va-rank-row', href: href || null },
      h('span', { class: 'va-rank-n', 'aria-label': 'Rank ' + (i + 1) }, String(i + 1)),
      h('span', { class: 'va-rank-name' }, h('strong', null, rowLabel(r)), sub ? h('span', { class: 'vd-muted vd-small' }, sub) : null),
      h('span', { class: 'va-rank-prog' }, progressNode(ctx, r))));
  }));
}

function topBottom(ctx, rows) {
  const ranked = (rows || []).filter((r) => r.target > 0);
  if (!ranked.length) return emptyChart('No colleges have targets yet.', { action: { label: 'Set targets', href: '#/targets' } });
  return h('div', { class: 'va-pair' },
    h('div', null, h('h3', { class: 'vd-h3' }, 'Top 10'), leaderTable(ctx, 'college', rows, { limit: 10 })),
    ranked.length > 10 ? h('div', null, h('h3', { class: 'vd-h3' }, 'Bottom 10'), leaderTable(ctx, 'college', rows, { limit: 10, reverse: true })) : null);
}

function peopleBoards(ctx, rows, err) {
  if (err) return errorNote(err, 'the team leaderboard');
  const list = rows || [];
  if (!list.length) return ctx.ui.emptyState({ title: 'No team yet', text: 'Appoint college leads and ambassadors from a college page to rank them here.' });
  if (!list.some((r) => r.role)) return leaderTable(ctx, 'person', list, { limit: 15 });
  const leads = list.filter((r) => r.role === 'college_lead' || r.role === 'ambassador_lead');
  const ambs = list.filter((r) => r.role === 'ambassador');
  return h('div', { class: 'va-pair' },
    h('div', null, h('h3', { class: 'vd-h3' }, 'Leads'), leads.length ? leaderTable(ctx, 'person', leads, { limit: 10 }) : emptyChart('No leads yet')),
    h('div', null, h('h3', { class: 'vd-h3' }, 'Ambassadors'), ambs.length ? leaderTable(ctx, 'person', ambs, { limit: 10 }) : emptyChart('No ambassadors yet')));
}

export default { renderState, renderCollegeList, renderAnalytics, destroy };
