// Tech Drona portal — Targets & performance. Route: #/targets (?tab=perf|places, ?scope=college:c6 opens the place tree)
// Sub-sections: Performance (GET /api/performance — server computes actual/remaining/exceeded/%/status; the UI only displays),
// Targets by place (target tree, reconciliation, split wizard — unchanged capability) and the Planner (#/plan, views/plan.js).
// Styles: css/views-targets.css (.v-tgp) + css/views-admin.css (.v-adm tree/wizard). Exports: openTargetDialog, sectionNav, pctText.

import { fmt as F } from '../ui/h.js';
import { STATUS_META, PERF_STATUS_ORDER } from '../ui/components.js';

const STATE_ID = 'ap'; // the server stores the state/programme scope as 'ap'
const CHILD = { state: 'districts', district: 'cities / towns', city: 'colleges', college: 'relevant branches', branch: 'ambassadors' };
const LEVEL = { state: 'The programme (all target districts)', district: 'A district', city: 'A city / town', college: 'A college', branch: 'A branch' };
const TYPE_LABEL = { state: 'Programme', district: 'District', city: 'City / town', college: 'College', branch: 'Branch', person: 'Person' };
const METHOD = {
  eligible: ['By likely prospects', 'More where more final-year students in target branches can enrol. Recommended.'],
  strength: ['By total strength', 'More where the total number of students is higher.'],
  equal: ['Equal split', 'Everyone gets the same number. Handy for ambassadors.'],
};
const DIAG = { ambassador_gap: 'Branches without ambassadors', low_outreach: 'Too few students reached', low_conversion: 'Few reached students enrol', unrealistic_target: 'Target may be too high', behind_pace: 'Behind pace' };
const ROLE = { college_lead: 'College lead', ambassador_lead: 'Ambassador lead', ambassador: 'Ambassador' };
const LEADS = new Set(['college_lead', 'ambassador_lead']);
/** status -> [label, tone, explanation] (R10) — taken from the ONE shared vocabulary in ui/components.js (F12). */
export const STATUS = {
  ...Object.fromEntries(PERF_STATUS_ORDER.map((k) => [k, [STATUS_META[k].label, STATUS_META[k].tone, STATUS_META[k].tip]])),
  open: ['Not met yet', 'warn', 'Pace is not available from this server version.'], // pre-v4 servers only
};
const STATUS_ORDER = [...PERF_STATUS_ORDER, 'open'];
const SORTS = [['behind', 'Furthest behind'], ['pct_asc', '% of target, low to high'], ['pct_desc', '% of target, high to low'], ['actual', 'Most paid enrollments'], ['name', 'Name A–Z']];
const PAGE = 25;
const arr = (x) => (Array.isArray(x) ? x : (x && Array.isArray(x.rows) ? x.rows : (x && Array.isArray(x.items) ? x.items : [])));
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const numOr = (v) => (v === null || v === undefined || v === '' ? null : (Number.isFinite(Number(v)) ? Number(v) : null));

function ensureCss() {
  if (typeof document === 'undefined' || document.querySelector('link[href$="views-targets.css"]')) return;
  document.head.append(Object.assign(document.createElement('link'), { rel: 'stylesheet', href: 'css/views-targets.css' }));
}

/** One rule for % on every page (TG-13 / F11): value is a PERCENT (e.g. 4.75). Delegates to the shared fmt.pctPts. */
export function pctText(p) { return isNum(p) ? F.pctPts(p) : '—'; }

/** Segmented sub-navigation shared by #/targets and #/plan. */
export function sectionNav(ctx, active) {
  ensureCss();
  const { h } = ctx;
  // The shell renders Targets › Performance | Planner tabs (SECTIONS.targets); then only the in-page switch is needed here.
  // ONE tab row (responsive.md §7). When the shell strip already lists "Targets by place" nothing is added here; with the
  // older two-item strip (Performance | Planner) only a renamed in-page switch is added, so no label is repeated (T21/D15/P10).
  const strip = typeof document !== 'undefined' ? document.querySelector('.td-sectiontabs:not([hidden])') : null;
  const shellTabs = !!(strip && strip.querySelector('a, [role="tab"]'));
  if (shellTabs && (active === 'plan' || strip.querySelector('a[href*="tab=places"]'))) return document.createDocumentFragment();
  const items = shellTabs
    ? [['perf', 'Progress', '#/targets'], ['places', 'Targets by place', '#/targets?tab=places']]
    : [['perf', 'Performance', '#/targets'], ['places', 'Targets by place', '#/targets?tab=places'], ['plan', 'Planner', '#/plan']];
  return h('nav', { class: 'tgp-seg', 'aria-label': 'Targets section' },
    items.map(([id, label, href]) => h('a', { class: ['tgp-seg__item', active === id && 'is-active'], href, 'aria-current': active === id ? 'page' : null }, label)));
}

/* ================================================================ dates / periods (server TODAY, never the browser clock) */
const pad = (n) => String(n).padStart(2, '0');
const iso = (d) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
const parseD = (s) => new Date(String(s).slice(0, 10) + 'T00:00:00Z');
function mondayOf(s) { const d = parseD(s); const wd = (d.getUTCDay() + 6) % 7; d.setUTCDate(d.getUTCDate() - wd); return iso(d); }
function addDaysIso(s, n) { const d = parseD(s); d.setUTCDate(d.getUTCDate() + n); return iso(d); }
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
/** 'programme' | 'month:YYYY-MM' | 'week:YYYY-MM-DD' -> human label */
export function periodLabel(p, fmt) {
  if (!p || p === 'programme') return 'Programme to date';
  const [k, v] = String(p).split(':');
  if (k === 'month') { const [y, m] = v.split('-'); return `${MONTHS[Number(m) - 1]} ${y}`; }
  if (k === 'week') return `Week of ${fmt ? fmt.date(v) : v} – ${fmt ? fmt.date(addDaysIso(v, 6)) : addDaysIso(v, 6)}`;
  return p;
}
let healthToday = null;
/** hide write controls for read-only (viewer) sessions — SH's ui.writeOnly when present */
const wo = (ctx, node) => (node && typeof ctx.ui.writeOnly === 'function' ? ctx.ui.writeOnly(node) : node);
/** "55 days left (incl. today)" — same inclusive rule as /api/target-dashboard and the planner, from the server's TODAY (TG-13). */
function daysLeftText(ctx, deadline) {
  const t = serverToday(ctx); if (!t || !deadline) return '';
  const n = Math.round((Date.parse(String(deadline).slice(0, 10) + 'T00:00:00Z') - Date.parse(t + 'T00:00:00Z')) / 86400000) + 1;
  return n > 0 ? `${ctx.fmt.num(n)} days left (incl. today)` : 'deadline passed';
}
/** 'auto' when the user asked for reduced motion (D25), else 'smooth' */
function smooth(ctx) { const u = ctx && ctx.ui; return (u && typeof u.prefersReducedMotion === 'function' ? u.prefersReducedMotion() : (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches)) ? 'auto' : 'smooth'; }
function serverToday(ctx) { return ctx.state?.meta?.today || healthToday || null; }

/* ================================================================ page */
let cur = null;

export async function render(el, params = {}, ctx) {
  ensureCss();
  const tab = params.tab === 'places' || (params.scope && params.tab !== 'perf') ? 'places' : 'perf';
  const keep = cur && cur.root === el ? cur : null;
  cur = { root: el, ctx, params, tab };
  ctx.setBreadcrumb?.([{ label: 'Targets & performance', href: '#/targets' }]);
  el.className = 'v-tgp';
  const { h, ui } = ctx;
  const head = ui.pageHeader({
    title: 'Targets & performance',
    sub: tab === 'perf' ? 'Who is ahead and who is behind: targets against paid enrollments, by person, college or district.'
      : 'Set targets for places, split one number across its parts, and keep every level adding up.',
    actions: tab === 'places' ? [ui.button({ label: 'Split a target', icon: 'target', tone: 'primary', onClick: () => el.querySelector('#tg-wizard')?.scrollIntoView({ behavior: smooth(ctx), block: 'start' }) })] : [],
  });
  const body = h('div', { class: 'tgp-body' });
  el.replaceChildren(head, sectionNav(ctx, tab), body);
  if (!serverToday(ctx)) { try { healthToday = (await ctx.api.get('/health')).today || null; } catch { /* dates fall back to the browser clock */ } }
  if (tab === 'places') return renderPlaces(body, params, ctx, keep);
  return renderPerf(body, params, ctx);
}
export function destroy() { cur = null; }

/* ================================================================ PERFORMANCE */
function hashQuery() { const i = location.hash.indexOf('?'); return new URLSearchParams(i >= 0 ? location.hash.slice(i + 1) : ''); }
function setHashQuery(kv, { push = false } = {}) {
  const q = hashQuery();
  for (const [k, v] of Object.entries(kv)) { if (v == null || v === '' || v === 'all') q.delete(k); else q.set(k, v); }
  const s = q.toString();
  const url = `#/targets${s ? '?' + s : ''}`;
  if (url === location.hash) return;
  try { if (push) history.pushState(null, '', url); else history.replaceState(history.state, '', url); } catch { /* ignore */ }
}

async function renderPerf(host, params, ctx) {
  const { h, ui } = ctx;
  const me = cur;
  const today = serverToday(ctx);
  const f = me.f = {
    level: ['person', 'college', 'district'].includes(params.level) ? params.level : 'person',
    period: /^(programme|month:\d{4}-\d{2}|week:\d{4}-\d{2}-\d{2})$/.test(params.period || '') ? params.period : 'programme',
    status: params.status || '', role: params.role || '', college: params.college || '', q: params.q || '',
    sort: SORTS.some(([k]) => k === params.sort) ? params.sort : 'behind', page: Math.max(1, Number(params.page) || 1), inactive: params.inactive === '1',
  };
  me.today = today;
  me.nodes = { summary: h('div', { class: 'tgp-summary', 'aria-live': 'polite' }), bar: h('div', { class: 'tgp-filters' }), table: h('div', { class: 'tgp-tablehost' }) };
  host.replaceChildren(me.nodes.summary, ui.section({ title: 'Targets vs paid enrollments', sub: h('span', { class: 'tgp-sub' }), body: [me.nodes.bar, me.nodes.table] }));
  me.subEl = host.querySelector('.tgp-sub');
  me.nodes.table.replaceChildren(ui.skeleton(6, { card: false }));
  // colleges for the college filter (scoped)
  ctx.api.getScoped('/colleges').then(arr).then((cs) => { if (cur === me) { me.colleges = cs; drawFilters(); } }).catch(() => { me.colleges = []; });
  drawSummary();
  drawFilters();
  await loadPerf();
}

/** syncUrl() pushes a history entry (filter / segment / page changes — Back undoes them, D8); syncUrl(false) replaces (typing). */
function syncUrl(push = true) {
  const f = cur.f;
  setHashQuery({ tab: null, level: f.level === 'person' ? null : f.level, period: f.period === 'programme' ? null : f.period, status: f.status, role: f.role, college: f.college, inactive: f.inactive ? '1' : null, q: f.q, sort: f.sort === 'behind' ? null : f.sort, page: f.page > 1 ? f.page : null }, { push });
}

/** Programme 400 card + status counts. Programme numbers come from /api/target-dashboard (server TODAY, inclusive days left). */
async function drawSummary() {
  const me = cur; const { h, ui, fmt, api } = me.ctx;
  const host = me.nodes.summary;
  if (!me.dash) {
    host.replaceChildren(ui.skeleton(2, { card: false }));
    try { me.dash = await api.getScoped('/target-dashboard', { scope: 'state' }); } catch (e) { me.dash = { error: e }; }
    if (cur !== me) return;
  }
  const d = me.dash || {};
  // v4.1 (D2): the programme target (400) only applies when the selection includes every programme district. Otherwise
  // program.applies=false / program.target=null, and the top level carries the selected districts' own targets (may be
  // null + target_reason, or partial_target with covers). Older servers always send the programme target.
  const progNA = !!d.program && (d.program.applies === false || (d.program.target === null && !!d.program.target_reason));
  const p = progNA ? d : (d.program || d);
  const target = numOr(p.target !== undefined ? p.target : d.target);
  const confirmed = numOr(p.confirmed ?? d.confirmed);
  const partialT = progNA && d.target_status === 'partial_target';
  const remaining = partialT ? null : numOr(p.remaining ?? d.remaining);
  const pct = target && !partialT ? (isNum(p.pct) ? p.pct * 100 : null) : null;
  const noTargetReason = !d.error && target == null ? (d.target_reason || d.program?.target_reason || p.reason || 'The programme target covers the target districts, not this selection.') : null;
  const pg = d.program || p;
  const nSel = Array.isArray(pg.selected_districts) ? pg.selected_districts.length : 0;
  const selLabel = pg.selected_districts && !pg.all_districts ? ` · ${pg.is_default_selection ? 'target districts' : F.plural(nSel, 'selected district')}` : '';
  const headLabel = progNA ? `Targets · ${F.plural(nSel, 'selected district')}` : `Programme target${selLabel}`;
  const counts = me.counts || null;
  const card = (label, value, sub, tone, onClick) => h(onClick ? 'button' : 'div', { class: ['tgp-card', tone && `is-${tone}`, onClick && 'is-action'], type: onClick ? 'button' : null, onClick },
    h('span', { class: 'tgp-card__label' }, label), h('strong', { class: 'tgp-card__value td-num' }, value), sub ? h('span', { class: 'tgp-card__sub' }, sub) : null);
  const filterTo = (st) => () => { cur.f.status = cur.f.status === st ? '' : st; cur.f.page = 1; syncUrl(); drawFilters(); drawTable(); };
  const prog = d.error
    ? h('div', { class: 'tgp-prog' }, ui.errorCard({ title: 'Could not load the programme target', error: d.error, retry: () => { me.dash = null; drawSummary(); } }))
    : noTargetReason ? h('div', { class: 'tgp-prog' },
      h('div', { class: 'tgp-prog__head' }, h('span', { class: 'tgp-card__label' }, headLabel)),
      h('div', { class: 'tgp-prog__nums' },
        h('strong', { class: 'tgp-prog__big' }, 'No target for this selection'),
        h('span', { class: 'td-num tgp-muted' }, ` · ${F.plural(confirmed ?? 0, 'confirmed enrollment')}`)),
      h('p', { class: 'tgp-muted tgp-small' }, noTargetReason, ' Targets set on the districts, colleges or people in this selection are listed below.'))
    : partialT ? h('div', { class: 'tgp-prog' },
      h('div', { class: 'tgp-prog__head' }, h('span', { class: 'tgp-card__label' }, headLabel), statusChip(me.ctx, 'partial_target')),
      h('div', { class: 'tgp-prog__nums' },
        h('strong', { class: 'td-num tgp-prog__big' }, fmt.num(confirmed)),
        h('span', { class: 'td-num' }, ` paid · target ${fmt.num(target)}`),
        d.covers && isNum(d.covers.total) ? h('span', { class: 'td-num tgp-muted' }, ` · covers ${fmt.num(d.covers.with_target)} of ${fmt.num(d.covers.total)} · not judged`) : null),
      h('p', { class: 'tgp-muted tgp-small' }, STATUS.partial_target[2], ' No %, remaining or pace is shown until every part has a target.'))
    : h('div', { class: 'tgp-prog' },
      h('div', { class: 'tgp-prog__head' },
        h('span', { class: 'tgp-card__label' }, headLabel),
        progNA ? null : wo(me.ctx, h('button', { type: 'button', class: 'tgp-link', onClick: () => openTargetDialog(me.ctx, { scope_type: 'state', scope_id: STATE_ID, label: 'the programme', period: 'programme', onSaved: () => { me.dash = null; drawSummary(); loadPerf(); } }) }, 'Change'))),
      h('div', { class: 'tgp-prog__nums' },
        h('strong', { class: 'td-num tgp-prog__big' }, fmt.num(confirmed)),
        h('span', { class: 'td-num' }, ` of ${fmt.num(target)} paid · `, h('strong', null, pctText(pct))),
        h('span', { class: 'td-num tgp-muted' }, ` · ${fmt.num(remaining)} to go`)),
      perfBar(me.ctx, { actual: confirmed, target, label: progNA ? 'Selected districts' : 'Programme' }, { lg: true }),
      h('p', { class: 'tgp-muted tgp-small' }, d.days_left != null ? `${fmt.num(d.days_left)} days left including today (to ${fmt.date(p.deadline || d.deadline)})` : `Deadline ${fmt.date(p.deadline || d.deadline)}`,
        isNum(d.required_weekly) ? ` · ${d.required_weekly.toLocaleString('en-IN', { maximumFractionDigits: 1 })} confirmed / week needed` : '',
        '. Only confirmed (paid) enrollments dated today or earlier count.'));
  const c = (k) => (counts ? fmt.num(counts[k] || 0) : '…');
  // D6: one card per status that occurs, so the cards always add up to the number of rows. Owner review 2026-11-14:
  // statuses with 0 rows are no longer shown (six "0" cards on day one were noise); the Status filter still lists them all.
  const SUB = {
    exceeded: 'more than their target', met: 'exactly on target', on_track: 'keeping pace with the deadline', behind: 'slower than the pace needed',
    too_early: 'target set under 7 days ago, not judged yet', partial_target: 'only part of the group has a target', zero_target: 'target set to 0',
    no_target: 'no target set yet', open: 'below target (no pace on this server)',
  };
  const order = ['behind', 'on_track', 'too_early', 'met', 'exceeded', 'partial_target', 'zero_target', 'no_target', 'open'];
  const extra = counts ? Object.keys(counts).filter((k) => !order.includes(k)) : [];
  const shown = counts ? [...order, ...extra].filter((k) => counts[k]) : [];
  const toneOf = (k) => { const t = (STATUS[k] || [])[1]; return t === 'neutral' ? null : t; };
  host.replaceChildren(...[prog,
    shown.length ? h('div', { class: 'tgp-cards' },
      shown.map((k) => card((STATUS[k] || [k.replace(/_/g, ' ')])[0], c(k), SUB[k] || '', toneOf(k), filterTo(k)))) : null].filter(Boolean));
}

/* ---------- data */
function normDistrict(ctx, v) {
  if (v && typeof v === 'object') return { id: v.id, name: v.name || v.label || v.id };
  const d = (ctx.state?.meta?.districts || []).find((x) => x.id === v);
  return v ? { id: v, name: d ? d.name : v } : null;
}
function normCollege(r) {
  if (r.college && typeof r.college === 'object') return { id: String(r.college.id), name: r.college.short_name || r.college.name };
  const id = r.college_id ?? (typeof r.college === 'string' ? null : null);
  const name = r.college_short_name || r.college_name || (typeof r.college === 'string' ? r.college : null);
  return id || name ? { id: id ? String(id) : null, name } : null;
}
/** Normalise one /api/performance row (v4). Values are displayed as-is: no recomputation of remaining/%/status. */
function normPerf(ctx, r, level) {
  const role = r.role || null;
  const lead = level === 'person' && LEADS.has(role);
  return {
    id: String(r.id ?? r.scope_id), name: r.name ?? r.label ?? r.full_name ?? String(r.id), level, role, lead,
    personStatus: r.person_status ?? null,
    college: level === 'person' ? normCollege(r) : null, district: normDistrict(ctx, r.district ?? r.district_id),
    min: numOr(r.min ?? r.target_min), target: numOr(r.target), max: numOr(r.max ?? r.target_max),
    target_id: r.target_id ?? null, target_source: r.target_source ?? null,
    own: numOr(r.actual_own), teamActual: numOr(r.actual_team), combinedActual: numOr(r.actual_combined),
    actual: numOr(r.actual ?? r.actual_own), against: numOr(r.actual_against_target),
    remaining: numOr(r.remaining), exceeded_by: numOr(r.exceeded_by), pct: numOr(r.pct), status: r.status || (numOr(r.target) == null ? 'no_target' : 'open'),
    covers: r.covers || null, team: r.team || null, combined: r.combined || null,
    below_min: r.below_min === true, above_max: r.above_max === true, expected: numOr(r.expected), href: r.href || null,
    not_credited: numOr(r.not_credited),
  };
}
/** Fallback for a server without /api/performance: programme period only, from the existing server rollups. */
function legacyRow(ctx, r, level) {
  const t = numOr(r.target); const a = numOr(r.enrolled) ?? 0;
  const status = t == null ? 'no_target' : t === 0 ? 'zero_target' : a > t ? 'exceeded' : a === t ? 'met' : 'open';
  return {
    id: String(r.id), name: r.full_name || r.name || r.label, level, role: r.role || null, lead: false,
    personStatus: level === 'person' ? r.status : null, college: level === 'person' ? normCollege(r) : null,
    district: normDistrict(ctx, r.district_id),
    min: null, target: t, max: null, target_id: null, own: a, team: null, combined: null, actual: a, below_min: false, above_max: false,
    remaining: t == null ? null : Math.max(t - a, 0), exceeded_by: t == null ? null : Math.max(a - t, 0),
    pct: t ? (isNum(r.pct) ? r.pct * 100 : null) : null, status, covers: null, legacy: true, href: r.href || null,
  };
}

async function loadPerf() {
  const me = cur; const { api, ui } = me.ctx; const f = me.f;
  const my = me.seq = (me.seq || 0) + 1;
  me.nodes.table.replaceChildren(ui.skeleton(6, { card: false }));
  try {
    const res = await api.getScoped('/performance', { level: f.level, period: f.period, role: f.level === 'person' ? f.role : '', college_id: f.level === 'person' ? f.college : '', include_inactive: f.level === 'person' && f.inactive ? 1 : '' });
    if (cur !== me || my !== me.seq) return;
    me.v4 = true;
    me.res = res || {};
    me.rows = arr(res).map((r) => normPerf(me.ctx, r, f.level));
  } catch (e) {
    if (cur !== me || my !== me.seq) return;
    if (e && e.status === 404) {
      me.v4 = false;
      try {
        let rows;
        if (f.level === 'person') rows = arr(await api.getScoped('/people', { role: f.role, college: f.college }));
        else if (f.level === 'college') rows = arr(await api.getScoped('/colleges'));
        else rows = arr(await api.getScoped('/leaderboard', { level: 'district', scope: 'state', limit: 500 })).map((r) => ({ ...r, district_id: r.id }));
        if (cur !== me || my !== me.seq) return;
        me.res = {};
        me.rows = rows.map((r) => legacyRow(me.ctx, r, f.level));
        if (f.period !== 'programme') { f.period = 'programme'; syncUrl(false); drawFilters(); }
      } catch (e2) { return showErr(e2); }
    } else return showErr(e);
  }
  const counts = {};
  for (const r of me.rows) counts[r.status] = (counts[r.status] || 0) + 1;
  me.counts = counts;
  drawSummary();
  drawFilters();
  drawTable();
  function showErr(err) {
    me.nodes.table.replaceChildren(ui.errorCard({ title: 'Could not load performance', error: err, retry: loadPerf }));
  }
}

/* ---------- filters */
function drawFilters() {
  const me = cur; if (!me || !me.f) return;
  const { h, ui, fmt } = me.ctx; const f = me.f;
  const today = me.today;
  const seg = (name, opts, value, onPick) => h('div', { class: 'tgp-segctl', role: 'radiogroup', 'aria-label': name },
    opts.map(([v, l]) => h('button', { type: 'button', role: 'radio', 'aria-checked': String(value === v), class: ['tgp-segctl__btn', value === v && 'is-on'], onClick: () => onPick(v) }, l)));
  const pk = String(f.period).split(':')[0];
  const reload = () => { f.page = 1; syncUrl(); loadPerf(); };
  const levelCtl = seg('Show performance by', [['person', 'People'], ['college', 'Colleges'], ['district', 'Districts']], f.level, (v) => { if (v === f.level) return; f.level = v; f.role = ''; f.college = ''; reload(); });
  const v4 = me.v4 !== false;
  const periodCtl = seg('Period', [['programme', 'Programme'], ['month', 'Month'], ['week', 'Week']].map(([v, l]) => [v, l]), pk, (v) => {
    if (!v4 && v !== 'programme') { ui.toast('Month and week periods need the server update (/api/performance).', 'warn'); return; }
    const base = today || new Date().toISOString().slice(0, 10);
    f.period = v === 'programme' ? 'programme' : v === 'month' ? `month:${base.slice(0, 7)}` : `week:${mondayOf(base)}`;
    reload();
  });
  let pick = null;
  if (pk === 'month') {
    pick = h('input', { type: 'month', class: 'td-input tgp-pick', value: f.period.slice(6), 'aria-label': 'Month', onChange: (e) => { if (/^\d{4}-\d{2}$/.test(e.target.value)) { f.period = `month:${e.target.value}`; reload(); } } });
  } else if (pk === 'week') {
    const wk = f.period.slice(5);
    const step = (n) => () => { f.period = `week:${addDaysIso(wk, 7 * n)}`; reload(); };
    pick = h('div', { class: 'tgp-weekpick' },
      ui.button({ icon: 'chevron-left', tone: 'ghost', size: 'sm', ariaLabel: 'Previous week', onClick: step(-1) }),
      h('span', { class: 'td-num' }, periodLabel(f.period, fmt)),
      ui.button({ icon: 'chevron', tone: 'ghost', size: 'sm', ariaLabel: 'Next week', onClick: step(1) }));
  }
  const sel = (label, opts, value, onChange, cls) => h('label', { class: ['tgp-fl', cls] }, h('span', { class: 'tgp-fl__label' }, label),
    (() => { const s = h('select', { class: 'td-input td-select', onChange: (e) => onChange(e.target.value) }, opts.map(([v, l]) => h('option', { value: v }, l))); s.value = value; return s; })());
  const statusOpts = [['', 'All statuses'], ...STATUS_ORDER.filter((k) => k !== 'open' || me.v4 === false).map((k) => [k, STATUS[k][0] + (me.counts ? ` (${me.counts[k] || 0})` : '')])];
  const search = h('input', { type: 'search', class: 'td-input', placeholder: f.level === 'person' ? 'Search name, college…' : 'Search…', value: f.q, 'aria-label': 'Search' });
  let t; search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { f.q = search.value.trim(); f.page = 1; syncUrl(false); drawTable(); }, 200); });
  const colleges = (me.colleges || []).slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const nActive = [f.status, f.role, f.college, f.q].filter(Boolean).length;
  me.nodes.bar.replaceChildren(
    h('div', { class: 'tgp-filters__row' }, levelCtl, h('div', { class: 'tgp-period' }, periodCtl, pick)),
    h('div', { class: 'tgp-filters__row' },
      h('label', { class: 'tgp-fl tgp-fl--search' }, h('span', { class: 'tgp-fl__label' }, 'Search'), search),
      sel('Status', statusOpts, f.status, (v) => { f.status = v; f.page = 1; syncUrl(); drawTable(); drawSummary(); }),
      f.level === 'person' ? sel('Role', [['', 'All roles'], ...Object.entries(ROLE)], f.role, (v) => { f.role = v; reload(); }) : null,
      f.level === 'person' ? sel('College', [['', 'All colleges'], ...colleges.map((c) => [String(c.id), c.short_name || c.name])], f.college, (v) => { f.college = v; reload(); }, 'tgp-fl--college') : null,
      sel('Sort', SORTS, f.sort, (v) => { f.sort = v; f.page = 1; syncUrl(); drawTable(); }),
      f.level === 'person' && me.v4 !== false ? h('label', { class: 'tgp-check' }, h('input', { type: 'checkbox', class: 'td-check', checked: f.inactive, onChange: (e) => { f.inactive = e.target.checked; reload(); } }), h('span', null, 'Include people who left')) : null,
      nActive ? ui.button({ label: 'Clear filters', tone: 'ghost', size: 'sm', onClick: () => { Object.assign(f, { status: '', role: '', college: '', q: '', page: 1 }); reload(); } }) : null));
  if (me.subEl) me.subEl.textContent = `${{ person: 'People', college: 'Colleges', district: 'Districts' }[f.level]} · ${periodLabel(f.period, fmt)}${me.res?.period?.start ? ` · ${fmt.date(me.res.period.start)} – ${fmt.date(me.res.period.end)}${isNum(me.res.period.days_elapsed) ? ` (day ${fmt.num(me.res.period.days_elapsed)} of ${fmt.num(me.res.period.days_total)})` : ''}` : ''}`;
}

/* ---------- table */
function sortRows(rows, sort) {
  const coll = new Intl.Collator('en-IN', { numeric: true, sensitivity: 'base' });
  const nullLast = (a, b, fn) => (a == null && b == null ? 0 : a == null ? 1 : b == null ? -1 : fn(a, b));
  const by = {
    behind: (a, b) => nullLast(a.remaining, b.remaining, (x, y) => y - x) || nullLast(a.pct, b.pct, (x, y) => x - y),
    pct_asc: (a, b) => nullLast(a.pct, b.pct, (x, y) => x - y),
    pct_desc: (a, b) => nullLast(a.pct, b.pct, (x, y) => y - x),
    actual: (a, b) => nullLast(a.actual, b.actual, (x, y) => y - x),
    name: () => 0,
  }[sort] || (() => 0);
  return rows.slice().sort((a, b) => by(a, b) || coll.compare(a.name, b.name));
}

function drawTable() {
  const me = cur; if (!me || !me.rows) return;
  const { h, ui, fmt } = me.ctx; const f = me.f;
  const q = f.q.toLowerCase();
  let rows = me.rows;
  if (f.status) rows = rows.filter((r) => r.status === f.status);
  if (q) rows = rows.filter((r) => [r.name, r.college?.name, r.district?.name, ROLE[r.role]].filter(Boolean).join(' ').toLowerCase().includes(q));
  if (f.level === 'person' && f.role) rows = rows.filter((r) => !r.role || r.role === f.role);
  if (f.level === 'person' && f.college) rows = rows.filter((r) => !r.college?.id || r.college.id === f.college);
  rows = sortRows(rows, f.sort);
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  if (f.page > pages) f.page = pages;
  const pageRows = rows.slice((f.page - 1) * PAGE, f.page * PAGE);
  const notes = [];
  if (me.v4 === false) notes.push(h('div', { class: 'tgp-note is-warn', role: 'status' }, ui.icon('info', { size: 16 }),
    h('span', null, h('strong', null, 'Limited view. '), 'This server does not have the performance service yet, so only programme-to-date figures are shown — no month/week periods, min/max, team totals or pace status. Numbers come from the existing server rollups.')));
  const partial = me.rows.filter((r) => r.covers && isNum(r.covers.total) && isNum(r.covers.with_target) && r.covers.with_target < r.covers.total && r.target != null);
  if (partial.length && f.level !== 'person') notes.push(h('div', { class: 'tgp-note', role: 'note' }, ui.icon('info', { size: 16 }),
    h('span', null, `${fmt.num(partial.length)} ${f.level === 'district' ? 'district' : 'college'}${partial.length === 1 ? '' : 's'} ha${partial.length === 1 ? 's' : 've'} no own target, so the target is the sum of the ${f.level === 'district' ? 'towns' : 'branches'} that have one. Actual, % and remaining then count only those ${f.level === 'district' ? 'towns' : 'branches'}; the full confirmed count is shown underneath ("all").`)));
  if (f.level === 'person' && me.rows.some((r) => r.lead)) notes.push(h('p', { class: 'tgp-muted tgp-small' },
    'For college leads and ambassador leads: ', h('strong', null, 'Own'), ' = enrollments credited to the lead personally (the row\u2019s target, % and status are for these). ',
    h('strong', null, 'Team'), ' = the active ambassadors who report to them. ',
    h('strong', null, 'Total'), ' = own + team. Hover over Team or Total (on touch: press and hold) to see their %.'));
  if (!me.rows.length) {
    me.nodes.table.replaceChildren(...notes, ui.emptyState({ icon: 'target', title: f.level === 'person' ? 'No people yet' : 'Nothing to show', text: f.level === 'person' ? 'Add College Leads and Ambassadors in Team; their targets and confirmed enrollments appear here.' : 'No places in this district selection.' }));
    return;
  }
  const clearAll = () => { Object.assign(f, { status: '', role: '', college: '', q: '', page: 1 }); syncUrl(); drawFilters(); drawSummary(); drawTable(); };
  const emptyF = typeof ui.listEmpty === 'function'
    ? ui.listEmpty({ filtered: true, noun: f.level === 'person' ? 'people' : f.level === 'college' ? 'colleges' : 'districts', onClear: clearAll })
    : ui.emptyState({ icon: 'filter', title: 'No rows match these filters', text: 'Clear a filter or the search to see more.' });
  const editAct = (r) => [{ label: r.target == null ? 'Set target' : 'Edit target', icon: 'target', writeOnly: true,
    onClick: () => openTargetDialog(me.ctx, { scope_type: r.level, scope_id: r.id, label: r.name, period: me.f.period, row: r, v4: me.v4 !== false, onSaved: () => { me.dash = null; drawSummary(); loadPerf(); } }) }];
  const tbl = ui.dataTable({
    caption: `Performance by ${f.level}, ${periodLabel(f.period, fmt)}`,
    columns: [
      { key: 'name', label: f.level === 'person' ? 'Name · role · college' : f.level === 'college' ? 'College · district' : 'District', primary: true, priority: 1, minWidth: 230, sortable: false, render: (r) => nameCell(r) },
      // Owner review 2026-11-14: "Exceeded by" is folded into "Still needed" (+N over) and the "Target vs actual" bar
      // column is gone (the % column says the same). Min / max show under the target only when someone set them.
      { key: 'target', label: 'Target', align: 'right', priority: 2, minWidth: 90, sortable: false, render: (r) => tgtCell(r) },
      { key: 'actual', label: 'Paid enrollments', phoneLabel: f.level === 'person' ? 'Paid enrollments (own · team · total)' : 'Paid enrollments', align: 'right', priority: 1, minWidth: 120, sortable: false, render: (r) => actualCell(r) },
      { key: 'remaining', label: 'Still needed', align: 'right', priority: 2, minWidth: 96, sortable: false, render: (r) => stillCell(r) },
      { key: 'pct', label: '% of target', align: 'right', priority: 2, minWidth: 90, sortable: false, render: (r) => pctCell(r) },
      { key: 'status', label: 'Status', priority: 1, minWidth: 130, sortable: false, cardHidden: true, render: (r) => chipOf(r) },
    ],
    rows: pageRows, rowKey: (r) => `${r.level}:${r.id}`, cardSort: false, empty: emptyF,
    cardTitle: (r) => h('span', null, h('a', { href: hrefOf(r) }, r.name), tagsOf(r)),
    cardSubtitle: (r) => subOf(r),
    cardMeta: (r) => chipOf(r),
    rowActions: (r) => editAct(r),
  });
  tbl.classList.add('tgp-dt');
  const from = total ? (f.page - 1) * PAGE + 1 : 0;
  const pager = h('div', { class: 'tgp-pager' },
    h('span', { class: 'td-num tgp-muted' }, total ? `${fmt.num(from)}–${fmt.num(Math.min(total, f.page * PAGE))} of ${fmt.num(total)}` : '0 rows', total !== me.rows.length ? ` (filtered from ${fmt.num(me.rows.length)})` : ''),
    pages > 1 ? h('div', { class: 'tgp-pager__btns' },
      ui.button({ label: 'Previous', icon: 'chevron-left', size: 'sm', disabled: f.page <= 1, onClick: () => { f.page--; syncUrl(); drawTable(); me.nodes.table.scrollIntoView({ block: 'start', behavior: smooth(me.ctx) }); } }),
      h('span', { class: 'td-num' }, `Page ${f.page} of ${pages}`),
      ui.button({ label: 'Next', size: 'sm', disabled: f.page >= pages, onClick: () => { f.page++; syncUrl(); drawTable(); me.nodes.table.scrollIntoView({ block: 'start', behavior: smooth(me.ctx) }); } })) : null);
  me.nodes.table.replaceChildren(...notes, tbl, pager);

  function teamTitle(tm) {
    const cov = tm.covers && isNum(tm.covers.total) ? ` · ${fmt.num(tm.covers.with_target)} of ${fmt.num(tm.covers.total)} members have a target` : '';
    return `Team of ${fmt.num(tm.size)}: ${fmt.num(tm.actual)}${tm.target != null ? ` of ${fmt.num(tm.target)} (${pctText(tm.pct)})` : ', no team targets'}${tm.status ? ` · ${(STATUS[tm.status] || [tm.status])[0]}` : ''}${cov}`;
  }
  function hrefOf(r) { return r.href || (r.level === 'person' ? `#/person/${r.id}` : r.level === 'college' ? `#/college/${r.id}` : `#/d/${r.id}`); }
  function subOf(r) {
    return r.level === 'person' ? [ROLE[r.role] || r.role, r.college?.name].filter(Boolean).join(' · ') : r.level === 'college' ? (r.district?.name || '—') : null;
  }
  function covOf(r) {
    const cov = r.covers && isNum(r.covers.total) && r.covers.total > 0 && r.target != null ? `target covers ${fmt.num(r.covers.with_target)} of ${fmt.num(r.covers.total)} ${r.level === 'district' ? 'towns' : r.level === 'college' ? 'branches' : 'parts'}` : null;
    return cov ? h('span', { class: ['tgp-cov', r.covers.with_target < r.covers.total && 'is-partial'] }, cov) : null;
  }
  function tagsOf(r) {
    const flag = [];
    if (r.personStatus && r.personStatus !== 'active') flag.push(h('span', { class: 'tgp-tag' }, r.personStatus === 'inactive' ? 'Inactive' : r.personStatus));
    if (r.below_min) flag.push(h('span', { class: 'tgp-tag is-warn' }, 'below min'));
    if (r.above_max) flag.push(h('span', { class: 'tgp-tag is-good' }, 'above max'));
    return flag.length ? h('span', { class: 'tgp-tags' }, flag) : null;
  }
  function nameCell(r) {
    const sub = subOf(r);
    return h('div', { class: 'tgp-namecell' }, h('a', { href: hrefOf(r) }, r.name), tagsOf(r), sub ? h('span', { class: 'tgp-subline' }, sub) : null, covOf(r));
  }
  function stillCell(r) {
    if (r.exceeded_by != null && r.exceeded_by > 0) return h('strong', { class: 'tgp-good', title: 'Paid enrollments above the target' }, `+${fmt.num(r.exceeded_by)} over`);
    return r.remaining == null ? h('span', { class: 'tgp-muted' }, '—') : fmt.num(r.remaining);
  }
  function tgtCell(r) {
    const rng = F.range(r.min, r.max);
    return r.target == null ? h('span', { class: 'tgp-muted' }, 'not set') : h('span', null, h('strong', null, fmt.num(r.target)), rng ? h('small', { class: 'tgp-why' }, rng) : null);
  }
  function pctCell(r) {
    const pctReason = r.pct == null ? (r.target == null ? 'no target' : r.target === 0 ? 'target is 0' : r.status === 'partial_target' ? 'not judged — partly targeted' : '') : '';
    return r.pct == null ? h('span', { class: 'tgp-muted', title: pctReason }, '—', pctReason ? h('small', { class: 'tgp-why' }, pctReason) : null) : pctText(r.pct);
  }
  function chipOf(r) {
    return statusChip(me.ctx, r.status, { title: r.status === 'partial_target' && r.covers && isNum(r.covers.total) ? `${STATUS.partial_target[2]} Target covers ${fmt.num(r.covers.with_target)} of ${fmt.num(r.covers.total)}.` : undefined });
  }
  function actualCell(r) {
    const tm = r.team; const cb = r.combined;
    return r.lead
      ? h('span', { class: 'tgp-act' },
        h('span', null, h('small', null, 'Own '), h('strong', null, fmt.num(r.actual ?? 0))),
        h('span', { title: tm ? teamTitle(tm) : '' }, h('small', null, `Team${tm && isNum(tm.size) ? ` (${tm.size})` : ''} `), fmt.num(tm ? tm.actual : r.teamActual ?? 0), tm && tm.target != null ? h('small', null, ` / ${fmt.num(tm.target)}`) : null,
          tm && tm.covers && isNum(tm.covers.total) && tm.covers.total > 0 && tm.covers.with_target < tm.covers.total ? h('small', { class: 'tgp-why' }, `${fmt.num(tm.covers.with_target)} of ${fmt.num(tm.covers.total)} with a target`) : null),
        h('span', { title: cb ? `Total: ${fmt.num(cb.actual)}${cb.target != null ? ` of ${fmt.num(cb.target)} (${pctText(cb.pct)})${cb.status ? ` · ${(STATUS[cb.status] || [cb.status])[0]}` : ''}` : ', no target'}` : '' }, h('small', null, 'Total '), fmt.num(cb ? cb.actual : r.combinedActual ?? 0), cb && cb.target != null ? h('small', null, ` / ${fmt.num(cb.target)}`) : null))
      : h('span', null, h('strong', null, fmt.num(r.actual ?? 0)),
        r.own != null && r.own !== r.actual && r.level !== 'person' ? h('small', { class: 'tgp-why', title: 'All confirmed enrollments here, including places without a target' }, `${fmt.num(r.own)} all`) : null,
        r.not_credited ? h('small', { class: 'tgp-why', title: 'Confirmed enrollments of this college not credited to any person' }, `${fmt.num(r.not_credited)} not credited`) : null);
  }
}

/** Status chip — the shared ui.statusChip (one vocabulary, one colour map — F12); 'open' only on pre-v4 servers. */
export function statusChip(ctx, status, { title } = {}) {
  if (typeof ctx.ui.statusChip === 'function') {
    return ctx.ui.statusChip(status, { label: status === 'open' ? STATUS.open[0] : undefined, title: title || (status === 'open' ? STATUS.open[2] : undefined), size: 'sm' });
  }
  const [label, tone, tip] = STATUS[status] || [status || '—', 'neutral', ''];
  return ctx.h('span', { class: ['tgp-chip', `is-${tone}`, `st-${status}`], title: title || tip, 'data-status': status }, label);
}

/** Target-vs-actual bar with min / target / max markers. Scale = the largest of actual, target, max. */
export function perfBar(ctx, r, { lg } = {}) {
  const { h, fmt } = ctx;
  const a = Number(r.actual) || 0;
  const t = r.target; const mn = r.min; const mx = r.max;
  if (t == null) return h('span', { class: 'tgp-muted tgp-small' }, `${fmt.num(a)} enrolled · no target`);
  const scale = Math.max(a, t, mx || 0, 1);
  const pos = (v) => `${Math.min(100, (v / scale) * 100).toFixed(2)}%`;
  const tone = t === 0 ? 'neutral' : a >= t ? 'good' : r.status === 'behind' ? 'bad' : r.status === 'on_track' ? 'info' : 'warn';
  const label = `${fmt.num(a)} of ${t === 0 ? 'a target of 0' : fmt.num(t)}${mn != null ? `, minimum ${fmt.num(mn)}` : ''}${mx != null ? `, maximum ${fmt.num(mx)}` : ''}`;
  return h('span', { class: ['tgp-bar', lg && 'tgp-bar--lg'], role: 'img', 'aria-label': label, title: label },
    h('span', { class: 'tgp-bar__track' },
      h('i', { class: `tgp-bar__fill is-${tone}`, style: { width: pos(a) } }),
      mn != null ? h('b', { class: 'tgp-bar__mk is-min', style: { left: pos(mn) } }) : null,
      t > 0 ? h('b', { class: 'tgp-bar__mk is-target', style: { left: pos(t) } }) : null,
      mx != null ? h('b', { class: 'tgp-bar__mk is-max', style: { left: pos(mx) } }) : null));
}

/* ================================================================ ONE "Set target" dialog (person / college / district / programme …) */
/**
 * openTargetDialog(ctx, {scope_type, scope_id, label, period, row?, v4?, onSaved?})
 * min/target/max + period (programme | month | week). Writes PUT /api/targets (v4) — POST /api/targets on older servers (target only).
 * Never derives a target from children (R11): the programme target is only changed by typing a number here, with a warning.
 */
export async function openTargetDialog(ctx, opts = {}) {
  ensureCss();
  const { h, ui, api, fmt } = ctx;
  const st = opts.scope_type; const sid = String(opts.scope_id ?? (st === 'state' ? STATE_ID : ''));
  const today = serverToday(ctx) || new Date().toISOString().slice(0, 10);
  let v4 = opts.v4;
  let period = opts.period || 'programme';
  let existing = [];
  try { existing = arr(await api.get('/targets', { scope: `${st}:${sid}` })).filter((t) => t.course_id == null); } catch { /* new row */ }
  if (v4 === undefined) v4 = existing.some((t) => 'period' in t || 'target_min' in t) || await api.get('/health').then((x) => x && x.version === 'v4', () => false);
  if (!v4) period = 'programme';
  const rowFor = (p) => existing.find((t) => (t.period ? periodKey(t) === p : p === 'programme')) || null;
  const err = h('div', { class: 'td-form__error', role: 'alert', hidden: true });
  const fieldErr = {};
  const num = (name, label, help) => {
    const id = `tgd-${name}`;
    const input = h('input', { type: 'number', min: 0, step: 1, inputmode: 'numeric', class: 'td-input td-num', id, name });
    const e = h('div', { class: 'td-field__error', 'aria-live': 'polite' });
    fieldErr[name] = e;
    return { input, node: h('div', { class: 'td-field' }, h('label', { class: 'td-field__label', for: id }, label), input, help ? h('div', { class: 'td-field__help' }, help) : null, e) };
  };
  const fMin = num('min', 'Minimum (optional)', 'The least that is acceptable.');
  const fT = num('target', 'Target', 'Required. Whole number, 0 or more.');
  const fMax = num('max', 'Stretch / maximum (optional)', 'Must be at least the target.');
  const dl = h('input', { type: 'date', class: 'td-input td-num', id: 'tgd-deadline' });
  const notes = h('textarea', { class: 'td-input', id: 'tgd-notes', rows: 2, maxlength: 500 });
  const kind = h('select', { class: 'td-input td-select', id: 'tgd-period' }, [['programme', 'Whole programme'], ['month', 'A month'], ['week', 'A week (Mon–Sun)']].map(([v, l]) => h('option', { value: v }, l)));
  const month = h('input', { type: 'month', class: 'td-input td-num', 'aria-label': 'Month' });
  const week = h('input', { type: 'date', class: 'td-input td-num', 'aria-label': 'Any day in the week' });
  const weekLbl = h('span', { class: 'td-field__help' });
  const facts = h('div', { class: 'tgd-facts' });
  const pk = () => kind.value;
  const curPeriod = () => (pk() === 'programme' ? 'programme' : pk() === 'month' ? `month:${month.value}` : `week:${week.value ? mondayOf(week.value) : ''}`);
  const fill = () => {
    const p = curPeriod();
    const ex = rowFor(p);
    fMin.input.value = ex?.min ?? ex?.target_min ?? '';
    fT.input.value = ex ? ex.target : '';
    fMax.input.value = ex?.max ?? ex?.target_max ?? '';
    dl.value = ex?.deadline || '';
    notes.value = ex?.notes || '';
    month.hidden = pk() !== 'month'; week.hidden = pk() !== 'week'; weekLbl.hidden = pk() !== 'week';
    weekLbl.textContent = week.value ? periodLabel(`week:${mondayOf(week.value)}`, fmt) : '';
    dlField.hidden = pk() !== 'programme';
    const r = opts.row && opts.row.level === st && (opts.period || 'programme') === p ? opts.row : null;
    facts.replaceChildren(ui.kv([
      ['Period', periodLabel(p, fmt)],
      ['Current target', ex ? `${ex.min ?? ex.target_min ?? '—'} · ${fmt.num(ex.target)} · ${ex.max ?? ex.target_max ?? '—'} (min · target · max)` : 'none for this period'],
      r ? ['Confirmed so far', fmt.num(r.actual ?? 0)] : null,
      ex ? ['Last set', `${fmt.date(ex.updated_at)} by ${ex.updated_by || 'unknown'}`] : null,
    ].filter(Boolean)));
  };
  kind.value = String(period).split(':')[0];
  month.value = period.startsWith('month:') ? period.slice(6) : today.slice(0, 7);
  week.value = period.startsWith('week:') ? period.slice(5) : mondayOf(today);
  [kind, month, week].forEach((x) => x.addEventListener('change', fill));
  const dlField = h('div', { class: 'td-field' }, h('label', { class: 'td-field__label', for: 'tgd-deadline' }, 'Deadline (optional)'), dl,
    h('div', { class: 'td-field__help' }, 'Empty = the deadline of the place above, or the programme deadline.'));
  const isProgramme = st === 'state';
  const body = h('div', { class: 'tgd' },
    isProgramme ? h('div', { class: 'tgp-note is-warn', role: 'note' }, ui.icon('warn', { size: 16 }), h('span', null, h('strong', null, 'This is the programme target. '),
      'It is the goal everyone works towards (400 confirmed enrollments by the programme deadline unless changed here). It is never replaced by the sum of district or college targets.')) : null,
    facts,
    v4 ? h('div', { class: 'td-field' }, h('label', { class: 'td-field__label', for: 'tgd-period' }, 'Period'), h('div', { class: 'tgd-period' }, kind, month, week), weekLbl) : null,
    h('div', { class: ['tgd-grid', !v4 && 'is-single'] }, v4 ? fMin.node : null, fT.node, v4 ? fMax.node : null),
    !v4 ? h('p', { class: 'tgp-muted tgp-small' }, 'Minimum / maximum and month or week targets need the server update; only the programme target can be set on this server.') : null,
    dlField,
    h('div', { class: 'td-field' }, h('label', { class: 'td-field__label', for: 'tgd-notes' }, 'Notes (optional)'), notes),
    st !== 'person' && st !== 'branch' ? h('p', { class: 'tgp-muted tgp-small' }, `This does not change the targets of its ${CHILD[st] || 'parts'}.`) : null,
    err);
  fill();
  const read = (inp) => { const v = inp.value.trim(); return v === '' ? null : Number(v); };
  const save = async () => {
    err.hidden = true; Object.values(fieldErr).forEach((e) => { e.textContent = ''; });
    [fMin, fT, fMax].forEach((x) => x.input.removeAttribute('aria-invalid'));
    const mn = v4 ? read(fMin.input) : null; const t = read(fT.input); const mx = v4 ? read(fMax.input) : null;
    const bad = (f, msg) => { fieldErr[f].textContent = msg; ({ min: fMin, target: fT, max: fMax })[f].input.setAttribute('aria-invalid', 'true'); ({ min: fMin, target: fT, max: fMax })[f].input.focus(); return false; };
    const okInt = (v) => v === null || (Number.isInteger(v) && v >= 0 && v <= 1000000);
    if (t === null) return bad('target', 'Enter the target (0 or more).');
    if (!okInt(t)) return bad('target', 'Enter a whole number, 0 or more.');
    if (!okInt(mn)) return bad('min', 'Enter a whole number, 0 or more, or leave it empty.');
    if (!okInt(mx)) return bad('max', 'Enter a whole number, 0 or more, or leave it empty.');
    if (mn !== null && mn > t) return bad('min', 'The minimum cannot be more than the target.');
    if (mx !== null && mx < t) return bad('max', 'The maximum must be at least the target.');
    const p = curPeriod();
    if (pk() === 'month' && !/^\d{4}-\d{2}$/.test(month.value)) { err.textContent = 'Choose a month.'; err.hidden = false; return false; }
    if (pk() === 'week' && !week.value) { err.textContent = 'Choose a day in the week.'; err.hidden = false; return false; }
    if (isProgramme) {
      const ex = rowFor('programme');
      const okGo = await ui.confirm({ title: 'Change the programme target?', text: `The programme target changes from ${ex ? fmt.num(ex.target) : 'none'} to ${fmt.num(t)}. Every page, pace and planner uses this number.`, confirmLabel: `Set to ${fmt.num(t)}`, tone: 'primary' });
      if (!okGo) return false;
    }
    try { await ctx.ensureUser?.(); } catch { return false; }
    const payload = { scope_type: st, scope_id: sid, course_id: null, target: t, deadline: pk() === 'programme' ? (dl.value || null) : null, notes: notes.value.trim() || null };
    try {
      if (v4) {
        const body2 = { ...payload, period: p, min: mn, max: mx, ...(isProgramme ? { confirm_programme: true } : {}) };
        if (typeof api.put === 'function') await api.put('/targets', body2); else await api.post('/targets', body2);
      } else await api.post('/targets', payload);
    } catch (e) {
      const f = e.fields || {};
      let shown = false;
      for (const [k, m] of Object.entries(f)) { const key = k === 'target_min' ? 'min' : k === 'target_max' ? 'max' : k; if (fieldErr[key]) { fieldErr[key].textContent = m; shown = true; } }
      err.textContent = e.message + (shown ? '' : Object.entries(f).map(([k, m]) => ` — ${k}: ${m}`).join('')); err.hidden = false;
      return false;
    }
    ui.toast(`${opts.label || 'Target'}: ${periodLabel(p, fmt)} target ${fmt.num(t)}`, 'good');
    opts.onSaved?.();
    return true;
  };
  const actions = [{ label: 'Cancel', tone: 'ghost' }];
  const removeAct = { label: 'Remove target', tone: 'danger', align: 'start', onClick: async () => {
    const ex = rowFor(curPeriod());
    if (!ex) { ui.toast('There is no target for this period to remove.', 'warn'); return false; }
    if (isProgramme && curPeriod() === 'programme') { ui.toast('The programme target cannot be removed — change it instead.', 'warn'); return false; }
    try { await ctx.ensureUser?.(); } catch { return false; }
    await api.del(`/targets/${ex.id}`);
    ui.toast(`${opts.label || 'Target'}: ${periodLabel(curPeriod(), fmt)} target removed`, 'good');
    opts.onSaved?.();
    return true;
  } };
  if (existing.length && !(isProgramme && !v4)) actions.unshift(removeAct);
  actions.push({ label: 'Save target', tone: 'primary', onClick: save });
  const m = ui.modal({ title: `Target — ${opts.label || TYPE_LABEL[st] || st}`, body, actions });
  // T17: on touch screens do not pop the keyboard before the user has read the dialog
  if (!(typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches)) setTimeout(() => fT.input.focus(), 50);
  return m;
}
/** a stored target row -> 'programme' | 'month:YYYY-MM' | 'week:YYYY-MM-DD' (accepts the shapes a v4 server may use) */
function periodKey(t) {
  if (t.period_key) return String(t.period_key);
  const p = String(t.period || 'programme');
  if (p === 'programme' || p.includes(':')) return p;
  const start = t.period_start || t.period_key || '';
  if (p === 'month') return `month:${String(start).slice(0, 7)}`;
  if (p === 'week') return `week:${String(start).slice(0, 10)}`;
  return p;
}

/* ================================================================ TARGETS BY PLACE (tree, reconciliation, split wizard) */
let pl = null;
async function renderPlaces(host, params, ctx, keep) {
  const prev = pl && pl.el === host ? pl : (keep && keep.pl) || null;
  pl = {
    el: host, ctx, params,
    open: prev?.open || new Set(['state']), showAll: prev?.showAll || false, kids: new Map(),
    wiz: prev?.wiz || { parent_type: 'state', parent_id: '', district: '', college: '', course_id: '', total: '', method: 'eligible', only_targeted: true, deadline: '', alsoParent: false, preview: null },
  };
  cur.pl = pl;
  host.className = 'tgp-body v-tgpl';
  host.replaceChildren(ctx.ui.skeleton(3), ctx.ui.skeleton(5));
  await load({ first: true });
}

async function load({ first = false } = {}) {
  if (!pl) return;
  const me = pl;
  const { el, ctx } = me;
  const { ui, api } = ctx;
  try {
    const [meta, state, districts, recon, targets, colleges] = await Promise.all([
      api.get('/meta'), api.get('/summary', { scope: 'state' }),
      api.get('/leaderboard', { level: 'district', scope: 'state', limit: 500 }).then(arr),
      api.get('/targets/unreconciled').then(arr).catch(() => []),
      api.get('/targets', { limit: 5000 }).then(arr), api.get('/colleges').then(arr),
    ]);
    if (pl !== me) return;
    Object.assign(me, { meta, state, recon, colleges });
    me.kids = new Map([['state', districts]]);
    me.dMeta = new Map((meta.districts || []).map((d) => [d.id, d]));
    me.cMap = new Map(colleges.map((c) => [c.id, c]));
    const progRows = targets.filter((t) => t.course_id == null && (!t.period || t.period === 'programme'));
    me.explicit = new Map(progRows.map((t) => [`${t.scope_type}:${t.scope_id}`, t]));
    me.unrec = new Map(recon.filter((r) => r.course_id == null).map((r) => [`${r.scope_type}:${r.scope_id}`, r]));
    me.wiz.deadline = me.wiz.deadline || state?.deadline || meta.settings?.state_target_deadline || '';
  } catch (e) {
    if (pl !== me) return;
    el.replaceChildren(ui.errorCard({ title: 'Could not load targets', error: e, retry: () => load({ first }) }));
    return;
  }
  if (first && me.params.scope) await revealScope(me.params.scope);
  draw();
  if (first && me.params.scope) requestAnimationFrame(() => {
    const row = el.querySelector(`[data-key="${CSS.escape(me.focusKey || '')}"]`);
    if (row) { row.scrollIntoView({ block: 'center' }); row.classList.add('is-flash'); }
  });
}

/** Deep link: expand the tree down to `type:id`. */
async function revealScope(scope) {
  const [type, id] = String(scope).split(':');
  const c = type === 'college' ? pl.cMap.get(id) : null;
  if (type === 'district') { pl.open.add('state'); pl.focusKey = `district:${id}`; }
  if (type === 'city') {
    const city = (pl.meta.cities || []).find((x) => x.id === id);
    if (city) { await expand(`district:${city.district_id}`); pl.focusKey = `city:${id}`; }
  }
  if (c) {
    pl.showAll = pl.showAll || !c.targeted;
    await expand(`district:${c.district_id}`);
    if (c.city_id) await expand(`city:${c.city_id}`);
    pl.focusKey = `college:${id}`;
  }
}

async function childrenOf(key) {
  if (pl.kids.has(key)) return pl.kids.get(key);
  const { api } = pl.ctx;
  const [type, id] = key.split(/:(.*)/s);
  let rows = [];
  if (type === 'district') rows = await api.get('/leaderboard', { level: 'city', scope: `district:${id}`, limit: 500 }).then(arr);
  else if (type === 'city') rows = await api.get('/leaderboard', { level: 'college', scope: `city:${id}`, limit: 500 }).then(arr);
  else if (type === 'college') {
    const [lb, rel] = await Promise.all([api.get('/leaderboard', { level: 'branch', scope: `college:${id}`, limit: 500 }).then(arr),
      api.get('/branches', { college: id, relevant: 1 }).then(arr).catch(() => null)]);
    const ok = rel ? new Set(rel.map((b) => String(b.id))) : null;
    rows = lb.filter((b) => !ok || ok.has(String(b.id))).map((b) => ({ ...b, label: String(b.label).split(' · ')[0] }));
  }
  pl.kids.set(key, rows);
  return rows;
}
async function expand(key) { pl.open.add('state'); pl.open.add(key); await childrenOf(key).catch(() => []); }

function draw() {
  const { el } = pl;
  el.replaceChildren(topSection(), reconSection(), treeSection(), wizardSection());
}

/* ---------- programme summary */
function topSection() {
  const { h, ui, fmt } = pl.ctx;
  const s = pl.state || {};
  const courses = pl.meta.courses || [];
  const byCourse = new Map((s.by_course || []).map((c) => [String(c.course_id), c]));
  const srcLabel = { explicit: 'set directly', sum_of_children: 'adds up the district targets', none: 'not set yet' }[s.target_source] || '';
  const hasT = s.target > 0;
  const kpi = (label, value, sub, tone) => h('div', { class: ['tg-kpi', tone && `is-${tone}`] },
    h('span', { class: 'tg-kpi__label' }, label), h('strong', { class: 'tg-kpi__value td-num' }, value), sub ? h('span', { class: 'tg-kpi__sub' }, sub) : null);
  return ui.section({
    title: 'Programme target',
    sub: hasT ? `All courses · ${srcLabel}` : 'No programme target yet',
    actions: [wo(pl.ctx, ui.button({ label: hasT ? 'Change' : 'Set programme target', icon: 'edit', size: 'sm', tone: hasT ? 'secondary' : 'primary',
      onClick: () => openTargetDialog(pl.ctx, { scope_type: 'state', scope_id: STATE_ID, label: 'the programme', period: 'programme', onSaved: () => load() }) }))],
    body: h('div', { class: 'tg-top' },
      h('div', { class: 'tg-kpis' },
        kpi('Target', hasT ? fmt.num(s.target) : 'Not set', hasT ? null : 'Set it here or split one below'),
        kpi('Paid enrollments', fmt.num(s.enrolled ?? 0), s.reached ? `${fmt.num(s.reached)} students reached (logged activities)` : 'students reached: no activity logged'),
        kpi('Still needed', hasT ? fmt.num(s.remaining) : '—'),
        kpi('Deadline', s.deadline ? fmt.date(s.deadline) : 'Not set', s.deadline ? daysLeftText(pl.ctx, s.deadline) : 'set it in Settings')),
      hasT ? perfBar(pl.ctx, { actual: s.enrolled ?? 0, target: s.target }, { lg: true }) : null,
      hasT ? h('p', { class: 'tgp-muted tgp-small td-num' }, `${fmt.num(s.enrolled ?? 0)} of ${fmt.num(s.target)} · ${pctText(isNum(s.pct) ? s.pct * 100 : null)}. Pace and status for people, colleges and districts are on the Performance tab.`) : null,
      courses.length ? h('div', { class: 'tg-courses' },
        h('span', { class: 'tg-courses__title' }, 'By course'),
        courses.map((c) => {
          const r = byCourse.get(String(c.id)) || {};
          return h('div', { class: ['tg-course', !c.active && 'is-off'] },
            h('strong', null, c.name, !c.active ? h('span', { class: 'tgp-muted' }, ' (inactive)') : null),
            h('span', { class: 'tgp-muted' }, `${fmt.inr(c.price_inr)} per student`),
            h('span', { class: 'td-num' }, `${fmt.num(r.enrolled ?? 0)} confirmed`, r.target ? ` of ${fmt.num(r.target)}` : ' · no course target'),
            r.revenue_inr ? h('span', { class: 'tgp-muted td-num' }, `${fmt.inr(r.revenue_inr)} revenue`) : null);
        }))
        : h('p', { class: 'tgp-muted' }, 'No courses yet, so targets count enrollments in any course. ', h('a', { href: '#/settings' }, 'Add courses and prices in Settings'), '.')),
  });
}

/* ---------- reconciliation: warn only. Never offer "use the sum of its parts" for the programme (TG-09, R11). */
function reconSection() {
  const { h, ui, fmt, api } = pl.ctx;
  const rows = (pl.recon || []);
  if (!rows.length) {
    return h('div', { class: 'tg-allgood' }, ui.icon('check', { size: 18 }), h('span', null, h('strong', null, 'Everything adds up. '),
      'Every place with its own target matches the sum of its parts (or its parts have no targets yet).'));
  }
  const courseName = (id) => (pl.meta.courses || []).find((c) => c.id === id)?.name;
  return ui.section({
    title: `Targets that don't match their parts (${rows.length})`,
    sub: 'These places have their own target, but the targets set for their parts add up to a different number. Often that is fine (not every part has a target yet). The programme target is never changed from here.',
    body: h('ul', { class: 'tg-recon' }, rows.map((r) => {
      const diff = (r.children_target_sum ?? 0) - r.target;
      const protectedRow = r.scope_type === 'state';
      return h('li', { class: 'tg-recon__row' },
        h('div', { class: 'tg-recon__main' },
          h('div', null, r.href ? h('a', { href: r.href }, protectedRow ? 'Programme' : r.label) : h('strong', null, protectedRow ? 'Programme' : r.label), ' ',
            h('span', { class: 'tg-pill' }, TYPE_LABEL[r.scope_type] || r.scope_type), r.course_id ? h('span', { class: 'tg-pill' }, courseName(r.course_id) || `course ${r.course_id}`) : null),
          h('div', { class: 'tg-recon__nums td-num' },
            h('span', null, 'Own target ', h('strong', null, fmt.num(r.target))),
            h('span', null, `Targets set for its ${CHILD[r.scope_type] || 'parts'} add up to `, h('strong', null, fmt.num(r.children_target_sum ?? 0))),
            h('span', { class: diff > 0 ? 'is-over' : 'is-under' }, diff > 0 ? `${fmt.num(diff)} more than the target` : `${fmt.num(-diff)} not yet given to any part`)),
          protectedRow ? h('p', { class: 'tgp-muted' }, 'Protected: the programme target stays as it is. Split it below to give every district a share.') : null),
        wo(pl.ctx, h('div', { class: 'tg-recon__actions' },
          !protectedRow ? ui.button({ label: `Use ${fmt.num(r.children_target_sum ?? 0)}`, size: 'sm', title: 'Change this place\'s own target to the sum of its parts', onClick: async () => {
            const ok = await ui.confirm({ title: `Change ${r.label}'s target?`, text: `${r.label}: own target ${fmt.num(r.target)} → ${fmt.num(r.children_target_sum ?? 0)} (the sum of the targets set for its ${CHILD[r.scope_type] || 'parts'}). Parts without a target count as 0.`, confirmLabel: `Set to ${fmt.num(r.children_target_sum ?? 0)}`, tone: 'primary' });
            if (!ok) return;
            try {
              await pl.ctx.ensureUser?.();
              await api.post('/targets', { scope_type: r.scope_type, scope_id: String(r.scope_id), course_id: r.course_id ?? null, target: r.children_target_sum ?? 0, deadline: pl.explicit.get(`${r.scope_type}:${r.scope_id}`)?.deadline || null });
              ui.toast(`${r.label}: target is now ${fmt.num(r.children_target_sum ?? 0)}`, 'good'); load();
            } catch (e) { if (!e.cancelled) ui.toast(e.message, 'bad'); }
          } }) : null,
          r.scope_type !== 'person' ? ui.button({ label: `Re-split ${fmt.num(r.target)}`, size: 'sm', tone: 'primary', title: 'Open the wizard with this target to split it across its parts again', onClick: () => {
            const city = r.scope_type === 'city' ? (pl.meta.cities || []).find((x) => x.id === r.scope_id) : null;
            Object.assign(pl.wiz, { parent_type: r.scope_type, parent_id: r.scope_type === 'state' ? '' : String(r.scope_id), district: city?.district_id || '', college: '', total: String(r.target), course_id: r.course_id ? String(r.course_id) : '', preview: null });
            redrawWizard(true);
          } }) : null)));
    })),
  });
}

/* ---------- tree */
function treeSection() {
  const { h, ui } = pl.ctx;
  const host = h('div', { class: 'tg-tree-host' });
  pl.treeHost = host;
  drawTree();
  return ui.section({
    title: 'Target tree',
    sub: 'Open a place to see its parts. "Own" = a target set directly; "Sum" = no own target, so it adds up its parts. All courses, whole programme. Pace and status are on the Performance tab.',
    actions: [h('label', { class: 'tg-toggle' }, h('input', { type: 'checkbox', class: 'td-check', checked: pl.showAll, onChange: (e) => { pl.showAll = e.target.checked; drawTree(); } }), h('span', null, 'Show places we are not targeting'))],
    body: host,
  });
}

function visibleKids(key) {
  const rows = pl.kids.get(key) || [];
  if (pl.showAll) return rows;
  const [type] = key.split(':');
  if (type === 'state') return rows.filter((d) => d.target || pl.dMeta.get(d.id)?.targeted || pl.explicit.has(`district:${d.id}`));
  if (type === 'district') return rows.filter((c) => c.target || (pl.meta.cities || []).some((x) => x.id === c.id) && pl.colleges.some((k) => k.city_id === c.id && k.targeted));
  if (type === 'city') return rows.filter((c) => c.target || pl.cMap.get(c.id)?.targeted);
  return rows;
}

function drawTree() {
  const { h, fmt, ui } = pl.ctx;
  const out = [];
  const s = pl.state || {};
  const add = (n) => out.push(n);
  const walk = (key, depth) => {
    if (!pl.open.has(key)) return;
    if (!pl.kids.has(key)) { add({ msg: 'Loading…', depth }); childrenOf(key).then(drawTree, () => { pl.kids.set(key, []); drawTree(); }); return; }
    const kids = visibleKids(key).slice().sort((a, b) => (b.target ?? -1) - (a.target ?? -1) || String(a.label).localeCompare(String(b.label)));
    const hidden = (pl.kids.get(key) || []).length - kids.length;
    if (!kids.length) add({ msg: hidden ? `Nothing targeted here (${hidden} hidden — tick "Show places we are not targeting").` : `No ${CHILD[key.split(':')[0]]} recorded.`, depth });
    for (const k of kids) {
      const type = k.type;
      const kk = `${type}:${k.id}`;
      const label = type === 'college' ? (pl.cMap.get(k.id)?.name || k.label) : k.label;
      add({ key: kk, depth, type, id: String(k.id), label, r: k, href: k.href, hasKids: type !== 'branch' });
      if (type !== 'branch') walk(kk, depth + 1);
    }
    if (hidden && kids.length) add({ msg: `${hidden} more not targeted — tick "Show places we are not targeting" to see them.`, depth });
  };
  add({ key: 'state', depth: 0, type: 'state', id: STATE_ID, label: 'Programme', r: s, hasKids: true });
  walk('state', 1);

  const head = h('div', { class: 'tg-tr tg-tr--head', role: 'row' },
    ['Place', 'Target', 'Paid enrollments', 'Progress', 'Deadline', ''].map((t) => h('span', { role: 'columnheader' }, t)));
  const rows = out.map((n) => {
    if (n.msg) return h('div', { class: 'tg-tr tg-tr--msg', role: 'row', style: `--d:${n.depth}` }, h('span', { role: 'gridcell' }, n.msg));
    const r = n.r || {};
    const open = pl.open.has(n.key);
    const ex = pl.explicit.get(`${n.type}:${n.id}`);
    const bad = pl.unrec.get(`${n.type}:${n.id}`);
    const src = r.target_source === 'explicit' ? h('span', { class: 'tg-src is-own', title: 'Target set directly for this place' }, 'Own')
      : r.target_source === 'sum_of_children' ? h('span', { class: 'tg-src', title: 'No own target — this is the sum of its parts' }, 'Sum') : null;
    const toggle = async () => {
      if (open) pl.open.delete(n.key); else pl.open.add(n.key);
      drawTree();
      pl.treeHost.querySelector(`[data-key="${CSS.escape(n.key)}"] .tg-twisty`)?.focus();
    };
    const deadline = ex?.deadline || (n.type === 'state' ? s.deadline : null);
    const hasT = r.target != null && r.target !== 0 ? true : r.target === 0 && r.target_source === 'explicit';
    const pctP = r.target > 0 && isNum(r.pct) ? r.pct * 100 : null;
    return h('div', { class: ['tg-tr', `tg-d${Math.min(n.depth, 4)}`, bad && 'is-unrec', pl.focusKey === n.key && 'is-focus'], role: 'row', 'aria-level': n.depth + 1, 'aria-expanded': n.hasKids ? String(open) : null, 'data-key': n.key, style: `--d:${n.depth}` },
      h('span', { class: 'tg-name', role: 'gridcell' },
        n.hasKids ? h('button', { type: 'button', class: ['tg-twisty', open && 'is-open'], 'aria-label': `${open ? 'Hide' : 'Show'} parts of ${n.label}`, 'aria-expanded': String(open), onClick: toggle }, ui.icon('chevron', { size: 16 })) : h('span', { class: 'tg-twisty-sp' }),
        h('span', { class: 'tg-name__txt' }, n.href ? h('a', { href: n.href }, n.label) : h('strong', null, n.label), h('small', { class: 'tg-type' }, TYPE_LABEL[n.type]))),
      h('span', { class: 'tg-c-target td-num', role: 'gridcell', 'data-label': 'Target' },
        hasT ? fmt.num(r.target) : h('span', { class: 'tgp-muted' }, '—'), src,
        bad ? h('span', { class: 'tg-flag', title: `Its parts add up to ${fmt.num(bad.children_target_sum)}` }, ui.icon('warn', { size: 14 })) : null),
      h('span', { class: 'tg-c-enr td-num', role: 'gridcell', 'data-label': 'Paid enrollments' }, fmt.num(r.enrolled ?? 0)),
      h('span', { class: 'tg-c-prog', role: 'gridcell' }, r.target > 0 ? h('span', { class: 'tg-bar', title: `${fmt.num(r.enrolled ?? 0)} of ${fmt.num(r.target)}` },
        h('span', { class: 'tg-track' }, h('i', { class: r.pct >= 0.6 ? 'is-good' : r.pct >= 0.3 ? 'is-warn' : 'is-bad', style: { width: Math.min(100, (r.pct || 0) * 100) + '%' } })),
        h('span', { class: 'td-num' }, pctText(pctP)))
        : h('span', { class: 'tgp-muted' }, r.target === 0 && r.target_source === 'explicit' ? 'target is 0' : 'no target')),
      h('span', { class: 'tg-c-dl', role: 'gridcell', 'data-label': 'Deadline' }, deadline ? fmt.date(deadline) : h('span', { class: 'tgp-muted', title: 'Uses the deadline of the place above it, or the programme deadline' }, n.depth ? 'inherited' : '—')),
      h('span', { class: 'tg-c-act', role: 'gridcell' }, wo(pl.ctx, ui.button({ icon: 'edit', tone: 'ghost', size: 'sm', ariaLabel: `Set target for ${n.label}`,
        onClick: () => openTargetDialog(pl.ctx, { scope_type: n.type, scope_id: n.id, label: n.type === 'state' ? 'the programme' : n.label, period: 'programme', onSaved: () => load() }) }))));
  });
  pl.treeHost.replaceChildren(h('div', { class: 'tg-tree', role: 'treegrid', 'aria-label': 'Targets by place' }, head, ...rows));
}

/* ---------- allocation wizard */
function wizardSection() {
  const { h, ui } = pl.ctx;
  const host = h('div', { id: 'tg-wizard' });
  pl.wizHost = host;
  host.append(ui.section({
    title: 'Split a target',
    sub: 'Share one number out across the parts of a place. Nothing is saved until you press "Save these targets".',
    body: wizard(),
  }));
  return host;
}
function redrawWizard(scroll) {
  const { ui } = pl.ctx;
  pl.wizHost.replaceChildren(ui.section({ title: 'Split a target', sub: 'Share one number out across the parts of a place. Nothing is saved until you press "Save these targets".', body: wizard() }));
  if (scroll) pl.wizHost.scrollIntoView({ behavior: smooth(pl.ctx), block: 'start' });
}

function wizard() {
  const { h, ui, api, fmt } = pl.ctx;
  const w = pl.wiz;
  let n = 0;
  const field = (label, input, help) => {
    const id = `tgw-${++n}`;
    input.id = id;
    return h('div', { class: 'td-field' }, h('label', { class: 'td-field__label', for: id }, label), input, help ? h('div', { class: 'td-field__help' }, help) : null);
  };
  const sel = (opts, value, onChange) => {
    const s = h('select', { class: 'td-input td-select', onChange: (e) => onChange(e.target.value) }, opts.map(([v, l]) => h('option', { value: v }, l)));
    s.value = value ?? '';
    return s;
  };
  const again = () => redrawWizard(false);
  const reset = () => { w.preview = null; };

  const districts = [...(pl.meta.districts || [])].sort((a, b) => (b.targeted - a.targeted) || a.name.localeCompare(b.name));
  const dOpts = [['', 'Choose a district…'], ...districts.map((d) => [d.id, d.name + (d.targeted ? ' — targeted' : '')])];
  const place = [];
  if (w.parent_type === 'district') place.push(field('District', sel(dOpts, w.parent_id, (v) => { w.parent_id = v; reset(); again(); })));
  if (w.parent_type === 'city') {
    place.push(field('District', sel(dOpts, w.district, (v) => { w.district = v; w.parent_id = ''; reset(); again(); })));
    const cities = (pl.meta.cities || []).filter((c) => c.district_id === w.district).sort((a, b) => a.name.localeCompare(b.name));
    place.push(field('City / town', sel([['', w.district ? 'Choose…' : 'Choose a district first'], ...cities.map((c) => [c.id, `${c.name} (${c.colleges || 0} colleges)`])], w.parent_id, (v) => { w.parent_id = v; reset(); again(); })));
  }
  if (w.parent_type === 'college' || w.parent_type === 'branch') {
    const cs = [...pl.colleges].sort((a, b) => (b.targeted - a.targeted) || a.name.localeCompare(b.name));
    const cv = w.parent_type === 'college' ? w.parent_id : w.college;
    place.push(field('College', sel([['', 'Choose a college…'], ...cs.map((c) => [c.id, c.name + (c.targeted ? ' — targeted' : '')])], cv, (v) => {
      if (w.parent_type === 'college') w.parent_id = v; else { w.college = v; w.parent_id = ''; }
      reset(); again();
    })));
    if (w.parent_type === 'branch') {
      const bsel = sel([['', w.college ? 'Loading branches…' : 'Choose a college first']], '', (v) => { w.parent_id = v; reset(); });
      place.push(field('Branch', bsel));
      if (w.college) api.get('/branches', { college: w.college, relevant: 1 }).then(arr).then((bs) => {
        bsel.replaceChildren(h('option', { value: '' }, bs.length ? 'Choose a branch…' : 'No relevant branches recorded'), ...bs.map((b) => h('option', { value: b.id }, `${b.code || ''} ${b.name}`.trim())));
        bsel.value = String(w.parent_id || '');
      }).catch(() => bsel.replaceChildren(h('option', { value: '' }, 'Could not load branches')));
    }
  }
  const courses = pl.meta.courses || [];
  const total = h('input', { type: 'number', min: 1, step: 1, inputmode: 'numeric', class: 'td-input td-num', value: w.total, placeholder: 'e.g. 500', onInput: (e) => { w.total = e.target.value; } });
  const deadline = h('input', { type: 'date', class: 'td-input td-num', value: w.deadline || '', onChange: (e) => { w.deadline = e.target.value; } });
  const methods = h('div', { class: 'tg-methods', role: 'radiogroup', 'aria-label': 'How to split' }, Object.entries(METHOD).map(([k, [l, help]]) =>
    h('label', { class: ['tg-method', w.method === k && 'is-on'] },
      h('input', { type: 'radio', name: 'tg-method', value: k, checked: w.method === k, onChange: () => { w.method = k; reset(); again(); } }),
      h('span', null, h('strong', null, l), h('small', null, help)))));
  const err = h('div', { class: 'td-form__error', role: 'alert', hidden: true });
  const params = () => ({
    parent_type: w.parent_type, parent_id: w.parent_type === 'state' ? null : w.parent_id,
    course_id: w.course_id ? Number(w.course_id) : null, total: Number(w.total), method: w.method,
    only_targeted: w.only_targeted, deadline: w.deadline || null,
  });
  const fail = (m) => { err.textContent = m; err.hidden = false; };
  const previewBtn = ui.button({ label: 'Preview the split', tone: 'primary', icon: 'chevron' });
  previewBtn.addEventListener('click', async () => {
    err.hidden = true;
    if (w.parent_type !== 'state' && !w.parent_id) return fail('Choose where the target starts first.');
    if (!(Number(w.total) > 0) || !Number.isInteger(Number(w.total))) { total.focus(); return fail('Enter a whole number greater than 0 for the total.'); }
    previewBtn.disabled = true; previewBtn.classList.add('is-busy');
    try {
      const res = await api.post('/targets/allocate', { ...params(), dry_run: true });
      w.preview = { params: params(), rows: (res.rows || []).map((r) => ({ ...r, value: r.proposed })), total: res.total ?? Number(w.total) };
      again();
      requestAnimationFrame(() => pl.wizHost.querySelector('.tg-preview')?.scrollIntoView({ behavior: smooth(pl.ctx), block: 'nearest' }));
    } catch (e) {
      fail([e.message, ...Object.entries(e.fields || {}).map(([k, v]) => `${k}: ${v}`)].join(' — '));
    } finally { previewBtn.disabled = false; previewBtn.classList.remove('is-busy'); }
  });

  const step1 = h('div', { class: 'tg-step' },
    h('h3', { class: 'tg-step__title' }, h('span', { class: 'tg-step__n' }, '1'), 'Where does the number start, and how big is it?'),
    h('div', { class: 'td-form__grid' },
      field('Start from', sel(Object.entries(LEVEL).map(([k, l]) => [k, `${l} → split across its ${CHILD[k]}`]), w.parent_type, (v) => { w.parent_type = v; w.parent_id = ''; w.college = ''; reset(); again(); })),
      ...place,
      field('Total enrollments to share out', total),
      field('Course', sel([['', 'All courses'], ...courses.map((c) => [c.id, `${c.name} (${fmt.inr(c.price_inr)})`])], w.course_id, (v) => { w.course_id = v; reset(); })),
      field('Deadline', deadline, 'Pre-filled with the programme deadline.')),
    h('div', { class: 'td-field' }, h('span', { class: 'td-field__label' }, 'How to share it out'), methods),
    ['state', 'district', 'city'].includes(w.parent_type) ? h('label', { class: 'tg-toggle' },
      h('input', { type: 'checkbox', class: 'td-check', checked: w.only_targeted, onChange: (e) => { w.only_targeted = e.target.checked; reset(); } }), h('span', null, 'Only include colleges we are targeting')) : null,
    err,
    h('div', { class: 'tg-step__foot' }, previewBtn));

  return h('div', { class: 'tg-wizard' }, step1, w.preview ? previewStep() : null,
    h('details', { class: 'tg-explain' }, h('summary', null, 'How is the split worked out?'),
      h('ul', null,
        h('li', null, '"By likely prospects" uses final-year students in each place × the branch relevance factors from Settings. Places whose numbers are still pending get a smaller share, shown as "pending".'),
        h('li', null, 'Numbers are whole people. Remainders go to the places closest to the next whole number, so the parts always add up exactly to your total.'),
        h('li', null, 'You can change any number before saving; the sum is checked as you type.'),
        h('li', null, 'Every saved target is recorded in the audit log with your name.'))));

  function previewStep() {
    const p = w.preview;
    const sumEl = h('strong', { class: 'td-num' });
    const warn = h('div', { class: 'tg-warn', role: 'status' });
    const applyBtn = ui.button({ label: 'Save these targets', tone: 'primary', icon: 'check' });
    const typeKey = (r) => `${r.scope_type}:${r.scope_id}`;
    const replacing = p.params.course_id == null ? p.rows.filter((r) => pl.explicit.has(typeKey(r))).length : 0;
    const basisTotal = p.rows.reduce((s, r) => s + (Number(r.basis_value) || 0), 0);
    const update = () => {
      const sum = p.rows.reduce((s, r) => s + (Number(r.value) || 0), 0);
      sumEl.textContent = `${fmt.num(sum)} of ${fmt.num(p.total)}`;
      sumEl.className = `td-num ${sum === p.total ? 'tg-ok' : 'tg-bad'}`;
      warn.hidden = sum === p.total;
      warn.textContent = sum === p.total ? '' : `The parts add up to ${fmt.num(sum)}, not ${fmt.num(p.total)} (${sum > p.total ? '+' : ''}${fmt.num(sum - p.total)}). You can still save, but this place will be listed under "Targets that don't match their parts".`;
    };
    const tbody = h('tbody', null, p.rows.map((r) => {
      const inp = h('input', { type: 'number', min: 0, step: 1, inputmode: 'numeric', class: 'td-input td-input--sm td-num tg-num', value: r.value, 'aria-label': `Target for ${r.label}`,
        onInput: (e) => { r.value = e.target.value === '' ? 0 : Math.max(0, Math.round(Number(e.target.value))); update(); } });
      const ex = pl.explicit.get(typeKey(r));
      return h('tr', null,
        h('td', { 'data-label': 'Name' }, r.label),
        h('td', { class: 'td-al-right td-num', 'data-label': 'Based on' }, r.basis_value == null ? h('span', { class: 'tgp-muted' }, 'pending') : fmt.num(r.basis_value),
          basisTotal && r.basis_value ? h('small', { class: 'tgp-muted' }, ` · ${pctText((r.basis_value / basisTotal) * 100)}`) : null),
        h('td', { class: 'td-al-right td-num', 'data-label': 'Current' }, ex && p.params.course_id == null ? fmt.num(ex.target) : h('span', { class: 'tgp-muted' }, '—')),
        h('td', { class: 'td-al-right td-num', 'data-label': 'Suggested' }, fmt.num(r.proposed)),
        h('td', { class: 'td-al-right', 'data-label': 'New target' }, inp));
    }));
    const isProg = p.params.parent_type === 'state';
    const alsoParent = h('input', { type: 'checkbox', class: 'td-check', checked: w.alsoParent && !isProg, disabled: isProg, onChange: (e) => { w.alsoParent = e.target.checked; } });
    applyBtn.addEventListener('click', async () => {
      try { await pl.ctx.ensureUser?.(); } catch { return; }
      applyBtn.disabled = true; applyBtn.classList.add('is-busy');
      const edited = p.rows.some((r) => Number(r.value) !== Number(r.proposed));
      try {
        if (!edited) await api.post('/targets/allocate', { ...p.params, dry_run: false });
        else for (const r of p.rows) await api.post('/targets', { scope_type: r.scope_type, scope_id: String(r.scope_id), course_id: p.params.course_id, target: Number(r.value) || 0, deadline: p.params.deadline });
        if (w.alsoParent && !isProg) await api.post('/targets', { scope_type: p.params.parent_type, scope_id: String(p.params.parent_id), course_id: p.params.course_id, target: p.total, deadline: p.params.deadline });
        ui.toast(`Saved ${fmt.num(p.rows.length)} targets`, 'good');
        w.preview = null;
        load();
      } catch (e) {
        ui.toast(e.message, 'bad');
        applyBtn.disabled = false; applyBtn.classList.remove('is-busy');
      }
    });
    const node = h('div', { class: 'tg-step tg-preview' },
      h('h3', { class: 'tg-step__title' }, h('span', { class: 'tg-step__n' }, '2'), `Check the split across ${fmt.num(p.rows.length)} ${CHILD[p.params.parent_type]}`),
      !p.rows.length ? ui.emptyState({ title: 'Nothing to split across', icon: 'target', text: `No ${CHILD[p.params.parent_type]} found here${p.params.only_targeted ? ' among the colleges we are targeting. Untick "Only include colleges we are targeting" to include all.' : '.'}` })
        : h('p', { class: 'tg-sum' }, 'The parts add up to ', sumEl, '.'),
      !p.rows.length ? null : h('div', { class: 'td-table-wrap' }, h('div', { class: 'td-table-scroll' }, h('table', { class: 'td-table tg-ptable' },
          h('thead', null, h('tr', null, h('th', null, 'Name'), h('th', { class: 'td-al-right' }, METHOD[p.params.method][0].replace('By ', 'Based on ')), h('th', { class: 'td-al-right', title: 'Target set directly for this place today, if any' }, 'Own target now'), h('th', { class: 'td-al-right' }, 'Suggested'), h('th', { class: 'td-al-right' }, 'New target'))),
          tbody))),
      warn,
      replacing ? h('p', { class: 'tg-note' }, ui.icon('warn', { size: 16 }), `${fmt.num(replacing)} of these already have their own target; saving replaces them.`) : null,
      p.rows.length ? h('label', { class: 'tg-toggle' }, alsoParent, h('span', null, isProg ? 'The programme target is not changed by a split (change it with "Change" above).' : `Also save ${fmt.num(p.total)} as the target for the starting place`)) : null,
      h('div', { class: 'tg-step__foot' },
        ui.button({ label: 'Discard', tone: 'ghost', onClick: () => { w.preview = null; again(); } }),
        p.rows.length ? wo(pl.ctx, applyBtn) : null));
    update();
    return node;
  }
}
