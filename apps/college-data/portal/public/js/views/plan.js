// Tech Drona portal — Target planner (planner agent). Route: #/plan  (?college=<id> opens and scrolls to that row)
// Data: GET /api/plan?districts=… (research v2 rows + actual team/funnel counts). All planning numbers are recomputed
// in the browser by ../plan/model.js from user-adjustable ASSUMPTIONS (no server round trip). Styles: css/views-plan.css.
import { computePlan, normalizeAssumptions, perRecruited, TARGET_GROUPS } from '../plan/model.js';
import * as S from '../state.js';
import * as charts from '../ui/charts.js';
import { today as todayStr } from '../ui/h.js';
import { sectionNav, pctText } from './targets.js';

/** TODAY from the server (TZ-safe, same date as every API rollup); the browser clock is only a fallback (TG-13/16). */
const serverToday = (me) => me.ctx.state?.meta?.today || me.today || todayStr();

const LS_KEY = 'td.plan.assumptions';
const LS_UI = 'td.plan.ui';
const SC = ['min', 'avg', 'max'];
const SC_LABEL = { min: 'Minimum', avg: 'Average', max: 'Maximum' };
/** T20: rows rendered synchronously; the rest of the college table is appended in idle chunks */
const FIRST_ROWS = 24;
const CHUNK_ROWS = 30;
const idle = (fn) => (typeof requestIdleCallback === 'function' ? requestIdleCallback(fn, { timeout: 120 }) : setTimeout(fn, 16));
const smooth = (ctx) => ((ctx?.ui?.prefersReducedMotion ? ctx.ui.prefersReducedMotion() : (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches)) ? 'auto' : 'smooth');
const STAGES = [['lead', 'Lead'], ['interested', 'Interested'], ['registered', 'Registered'], ['applied', 'Applied'], ['confirmed', 'Confirmed']];
const RAG = { GREEN: ['Reachable', 'good'], AMBER: ['Only with MoU', 'warn'], RED: ['Not reachable', 'bad'] };
const BASIS_TXT = {
  verified: ['✓', 'Verified', 'Verified — from an official document (AICTE EoA, NIRF, mandatory disclosure, annual report).'],
  estimated: ['≈', 'Estimated', 'Estimated — calculated from other numbers (for example current intake × fill). Treat as approximate.'],
  unavailable: ['?', 'Unavailable', 'Unavailable — no figure found. Counted as 0; never guessed.'],
};

let cur = null;

/* ------------------------------------------------------------------ helpers */
const n1 = (v) => (v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: 1 }));
const signed = (ctx, v) => (v > 0 ? `+${ctx.fmt.num(v)}` : v < 0 ? `−${ctx.fmt.num(-v)}` : '0');
const val = (o) => (o && typeof o === 'object' ? o.value : o);
const lsGet = (k) => { try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch { return null; } };
const lsSet = (k, v) => { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } };
const offerCode = (t) => { const m = /^\((\w)\)/.exec(t || ''); return m ? m[1] : null; };
/** first dialable number of a research phone field ("08645-350200 Extn 1409; 0863-…" -> "08645350200") */
const telOf = (p) => { const d = String(p || '').split(/[;,/]|\bext|\bx\b/i)[0].replace(/[^\d+]/g, ''); return d.replace(/\D/g, '').length >= 8 ? d : null; };
const safeUrl = (u) => (/^https?:\/\//i.test(String(u || '').trim()) ? String(u).trim() : null);

function scopeNow() {
  try { if (typeof S.getScope === 'function') return { ...S.getScope(), param: S.scopeParam(), label: S.scopeLabel() }; } catch { /* fall through */ }
  let raw = null;
  try { raw = localStorage.getItem('td.districtScope'); } catch { /* ignore */ }
  if (raw === 'all') return { all: true, ids: null, param: undefined, label: 'All districts' };
  let ids = null;
  try { ids = JSON.parse(raw); } catch { ids = null; }
  if (!Array.isArray(ids) || !ids.length) ids = Object.values(TARGET_GROUPS).flat();
  return { all: false, ids, param: ids.join(','), label: ids.join(' · ') };
}
const groupsNow = () => { try { return typeof S.targetGroups === 'function' ? S.targetGroups() : TARGET_GROUPS; } catch { return TARGET_GROUPS; } };

function districtName(ctx, id) {
  const st = ctx.state || {};
  const d = (st.meta?.districts || []).find((x) => x.id === id) || (st.program?.districts || []).find((x) => x.id === id);
  return d ? d.name : String(id || '—').replace(/-/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
}

/** compact provenance mark: ✓ verified (green) · ≈ estimated (amber) · ? unavailable (grey, dashed) */
function mark(ctx, basis) {
  const b = BASIS_TXT[basis] ? basis : 'unavailable';
  const [sym, label, tip] = BASIS_TXT[b];
  return ctx.h('span', { class: ['td-prov', `td-prov--${b === 'unavailable' ? 'pending' : b}`, 'vp-mark'], title: tip, role: 'img', 'aria-label': label }, sym);
}
function numB(ctx, obj, { strong } = {}) {
  const v = val(obj);
  const b = v === null || v === undefined ? 'unavailable' : (obj?.basis || 'unavailable');
  return ctx.h('span', { class: ['vp-nb', strong && 'vp-nb--strong'] }, ctx.h('span', { class: 'td-num' }, v === null || v === undefined ? '—' : ctx.fmt.num(v)), mark(ctx, b));
}
function basisLegend(ctx) {
  const { h } = ctx;
  return h('p', { class: 'vp-legend' }, h('span', { class: 'vp-legend__k' }, 'Source of each figure:'),
    ...['verified', 'estimated', 'unavailable'].map((b) => h('span', { class: 'vp-legend__i' }, mark(ctx, b), BASIS_TXT[b][1])));
}
function srcLink(ctx, url, label = 'source') {
  const u = safeUrl(url);
  return u ? ctx.h('a', { href: u, target: '_blank', rel: 'noopener noreferrer', class: 'vp-src' }, label, ctx.ui.icon('external', { size: 12 })) : null;
}

/* ------------------------------------------------------------------ entry */
export async function render(el, params = {}, ctx) {
  destroy();
  const ui0 = lsGet(LS_UI) || {};
  cur = {
    el, ctx, params, data: null, plan: null, A: null, people: new Map(),
    ui: { q: '', p: '', show: 'targeted', sortKey: 'rank', sortDir: 1, distMode: ui0.distMode || 'groups', expanded: new Set() },
    nodes: {},
  };
  const me = cur;
  ctx.setBreadcrumb?.([{ label: 'Targets & performance', href: '#/targets' }, { label: 'Planner', href: '#/plan' }]);
  el.className = 'v-plan';
  el.replaceChildren(ctx.ui.skeleton(2), ctx.ui.skeleton(6));
  me.onScope = () => { if (cur === me) load(me); };
  window.addEventListener(S.SCOPE_EVENT || 'td:district-scope', me.onScope);
  await load(me);
}
export function destroy() {
  if (cur?.onScope) window.removeEventListener(S.SCOPE_EVENT || 'td:district-scope', cur.onScope);
  cur = null;
}
export default render;
/** The planner reloads itself on 'td:district-scope' (me.onScope), so the shell skips its own re-render (no double load). */
export const handlesScope = true;

async function load(me) {
  const { el, ctx } = me;
  const scope = scopeNow();
  me.scope = scope;
  if (!ctx.state?.meta?.today && !me.today) { try { me.today = (await ctx.api.get('/health')).today || null; } catch { /* browser date fallback */ } }
  try {
    const data = await ctx.api.get('/plan', scope.param ? { districts: scope.param } : {});
    if (cur !== me) return;
    me.data = data || { colleges: [] };
  } catch (e) {
    if (cur !== me) return;
    el.replaceChildren(ctx.ui.pageHeader({ title: 'Target planner', sub: 'Plan colleges, College Leads and ambassadors for the 400-enrollment goal.' }), sectionNav(ctx, 'plan'),
      ctx.ui.errorCard({ title: e?.status === 404 ? 'The planner data is not available on this server yet' : 'Could not load the plan', error: e, retry: () => load(me) }));
    return;
  }
  if (me.data.imported === false || !(me.data.colleges || []).length) {
    el.replaceChildren(ctx.ui.pageHeader({ eyebrow: `Scope: ${scope.label}`, title: 'Target planner' }), sectionNav(ctx, 'plan'),
      ctx.ui.emptyState({ icon: 'data', title: me.data.imported === false ? 'Research data has not been imported yet' : 'No researched colleges in this district selection',
        text: me.data.imported === false ? (me.data.message && !/node\s+server\//i.test(me.data.message) ? me.data.message : 'The research plan has not been loaded yet. Ask an admin to import the research data once.') : 'Choose other districts with the district selector at the top of the page.' }));
    return;
  }
  me.A = normalizeAssumptions({ ...baseDefaults(me), ...(lsGet(LS_KEY) || {}) });
  me.people.clear();
  if (me.params.college) {
    const id = String(me.params.college);
    me.ui.expanded.add(id);
    const row = (me.data.colleges || []).find((c) => c.college_id === id);
    if (row && !row.targeted) me.ui.show = 'all';
    me.focus = id;
  }
  drawAll(me); // drawHeavy() scrolls to me.focus once the college table exists
}
function focusRow(me) {
  if (!me.focus) return;
  const id = me.focus; me.focus = null;
  requestAnimationFrame(() => {
    const tr = me.el.querySelector(`tr[data-id="${CSS.escape(id)}"]`);
    if (tr) { tr.scrollIntoView({ block: 'start', behavior: smooth(me.ctx) }); tr.classList.add('is-flash'); tr.querySelector('.vp-exp')?.focus({ preventScroll: true }); loadPeople(me, id); }
  });
}

/** research defaults, with the programme goal/deadline taken from the server when it has them */
function baseDefaults(me) {
  const prog = me.data?.program || me.ctx.state?.program || {};
  const d = {};
  const t = Number(prog.target);
  if (Number.isFinite(t) && t > 0) d.program_target = t;
  const dl = prog.deadline;
  if (typeof dl === 'string' && /^\d{4}-\d{2}-\d{2}/.test(dl)) d.deadline = dl.slice(0, 10);
  return d;
}

function recompute(me) {
  me.plan = computePlan(me.data.colleges || [], me.A, { groups: groupsNow(), today: serverToday(me) });
}

function drawAll(me) {
  const { el, ctx } = me;
  const { h, ui } = ctx;
  recompute(me);
  const n = me.nodes;
  n.strip = h('div', { class: 'vp-strip', 'aria-live': 'polite' });
  n.reach = h('div');
  n.dist = h('div');
  n.colleges = h('div');
  n.analytics = h('div');
  const d = me.data;
  el.replaceChildren(
    ui.pageHeader({
      eyebrow: `Scope: ${me.scope.label}`,
      title: 'Target planner',
      sub: 'What-if model: how many colleges, College Leads and ambassadors it takes to reach the goal, recomputed as you change the assumptions. It never sets anyone’s target — real targets are set on Performance.',
    }),
    sectionNav(ctx, 'plan'),
    n.strip,
    assumptionsPanel(me),
    n.reach, n.dist, n.colleges, n.analytics,
    sourcesNote(me, d),
  );
  // T20: paint the summary first; the big tables follow on the next frames instead of blocking the first paint
  n.strip.replaceChildren(...strip(me));
  n.reach.replaceChildren(reachSection(me));
  [n.dist, n.colleges, n.analytics].forEach((x) => x.replaceChildren(ui.skeleton(4)));
  updateChanged(me);
  const gen = me.gen = (me.gen || 0) + 1;
  requestAnimationFrame(() => setTimeout(() => { if (cur === me && me.gen === gen) drawHeavy(me); }, 0));
}

function updateChanged(me) {
  if (me.nodes.changed) me.nodes.changed.hidden = JSON.stringify(me.A) === JSON.stringify(normalizeAssumptions(baseDefaults(me)));
}
/** the cheap part (header strip + "what it takes") follows every keystroke; the tables are debounced */
function drawLight(me) {
  recompute(me);
  me.nodes.strip.replaceChildren(...strip(me));
  me.nodes.reach.replaceChildren(reachSection(me));
  updateChanged(me);
}
function drawHeavy(me) {
  const n = me.nodes;
  n.dist.replaceChildren(districtSection(me));
  n.colleges.replaceChildren(collegeSection(me));
  n.analytics.replaceChildren(analyticsSection(me));
  focusRow(me);
}
function drawResults(me, { now = false } = {}) {
  drawLight(me);
  clearTimeout(me.heavyT);
  const gen = me.gen = (me.gen || 0) + 1;
  if (now) { drawHeavy(me); return; }
  me.heavyT = setTimeout(() => { if (cur === me && me.gen === gen) drawHeavy(me); }, 260);
}

/* ------------------------------------------------------------------ a. header strip */
function strip(me) {
  const { ctx, plan } = me;
  const { h, fmt } = ctx;
  const T = plan.totals, P = plan.progress, A = plan.A;
  const pctTone = (p) => (p >= 1 ? 'good' : p >= 0.8 ? 'warn' : 'bad');
  const tile = (label, value, sub, tone) => h('div', { class: ['vp-tile', tone && `vp-tile--${tone}`] },
    h('div', { class: 'vp-tile__label' }, label), h('div', { class: 'vp-tile__value td-num' }, value), sub ? h('div', { class: 'vp-tile__sub' }, sub) : null);
  return [
    tile('Goal', `${fmt.num(A.program_target)} paid`, `by ${fmt.date(A.deadline)}`, 'brand'),
    ...SC.map((s) => tile(`Planned ${SC_LABEL[s].toLowerCase()}`, fmt.num(T[s]),
      h('span', null, h('strong', null, fmt.pct(T.pctOfTarget[s])), ' of goal · ', T.gap[s] >= 0 ? `${fmt.num(T.gap[s])} above` : `${fmt.num(-T.gap[s])} short`),
      pctTone(T.pctOfTarget[s]))),
    tile('Confirmed so far', fmt.num(P.confirmed), `${pctText(P.pct == null ? null : P.pct * 100)} of goal · ${fmt.num(P.remaining)} to go`, P.confirmed ? 'good' : null),
    tile('Days left', P.days_left === null ? '—' : fmt.num(P.days_left), P.required_weekly !== null ? `incl. today · ${n1(P.required_weekly)} confirmed / week needed` : 'deadline passed'),
  ];
}

/* ------------------------------------------------------------------ b. assumptions */
function assumptionsPanel(me) {
  const { ctx } = me;
  const { h, ui } = ctx;
  const phone = typeof ui.isPhone === 'function' ? ui.isPhone() : matchMedia('(max-width: 699px)').matches;
  const saved = lsGet(LS_UI) || {};
  const det = h('details', { class: 'vp-assume td-card', open: saved.assumeOpen ?? !phone });
  det.addEventListener('toggle', () => lsSet(LS_UI, { ...(lsGet(LS_UI) || {}), assumeOpen: det.open }));
  const body = h('div', { class: 'vp-assume__body' });
  const changed = h('span', { class: 'td-badge td-badge--info', hidden: true }, 'Changed from research defaults');
  me.nodes.changed = changed;
  det.append(
    h('summary', { class: 'vp-assume__sum' },
      h('span', { class: 'vp-assume__title' }, ui.icon('settings', { size: 18 }), 'Assumptions'),
      h('span', { class: 'td-badge td-badge--warn' }, 'Assumptions — not measured yet'), changed,
      h('span', { class: 'vp-assume__chev', 'aria-hidden': 'true' }, ui.icon('chevron', { size: 16 }))),
    body);
  const update = (fn) => { fn(me.A); me.A = normalizeAssumptions(me.A); lsSet(LS_KEY, me.A); drawResults(me); syncInputs(); };
  const inputs = [];
  const syncInputs = () => inputs.forEach((f) => f());

  const numIn = ({ label, get, set, min, max, step, suffix, help, id }) => {
    const inp = h('input', { class: 'td-input vp-num', type: 'number', inputmode: 'decimal', min, max, step, id });
    const sync = () => { if (document.activeElement !== inp) inp.value = String(+get().toFixed(4)); };
    inp.addEventListener('input', () => { const v = parseFloat(inp.value); if (Number.isFinite(v) && v >= min && v <= max) update((A) => set(A, v)); });
    inp.addEventListener('change', sync);
    inputs.push(sync); sync();
    return h('label', { class: 'vp-field' }, h('span', { class: 'vp-field__label' }, label),
      h('span', { class: 'vp-field__ctl' }, inp, suffix ? h('span', { class: 'vp-field__suf' }, suffix) : null),
      help ? h('span', { class: 'vp-field__help' }, help) : null);
  };
  const slider = ({ label, get, set, min, max, step, show, help }) => {
    const out = h('output', { class: 'vp-out td-num' });
    const rng = h('input', { type: 'range', class: 'vp-range', min, max, step, 'aria-label': label });
    const sync = () => { rng.value = String(get()); out.textContent = show(get()); rng.setAttribute('aria-valuetext', show(get())); };
    rng.addEventListener('input', () => update((A) => set(A, parseFloat(rng.value))));
    inputs.push(sync); sync();
    return h('label', { class: 'vp-field vp-field--range' }, h('span', { class: 'vp-field__label' }, label, out), rng, help ? h('span', { class: 'vp-field__help' }, help) : null);
  };
  const derived = h('p', { class: 'vp-derived' });
  inputs.push(() => { derived.textContent = `= ${n1(perRecruited(me.A))} paid enrollments per recruited ambassador (research: 2.5)`; });

  const years = h('fieldset', { class: 'vp-fs' }, h('legend', null, 'Year groups in scope'),
    ...[['final', 'Final year (2027 batch)'], ['third', '3rd year (half weight)'], ['second', '2nd year (half weight)']].map(([k, l]) => {
      const cb = h('input', { type: 'checkbox' });
      inputs.push(() => { cb.checked = !!me.A.years[k]; });
      cb.addEventListener('change', () => update((A) => { A.years[k] = cb.checked; }));
      return h('label', { class: 'vp-check' }, cb, h('span', null, l));
    }));

  const rateGrid = h('fieldset', { class: 'vp-fs vp-fs--rates' }, h('legend', null, 'Conversion to paid (% of IT students)'),
    h('div', { class: 'vp-rates', role: 'group' },
      h('span'), ...SC.map((s) => h('span', { class: 'vp-rates__hd' }, SC_LABEL[s])),
      ...[['final', 'Final year'], ['third', '3rd year'], ['second', '2nd year']].flatMap(([k, l]) => [
        h('span', { class: 'vp-rates__row' }, l),
        ...SC.map((s, i) => {
          const inp = h('input', { class: 'td-input vp-num', type: 'number', inputmode: 'decimal', min: 0, max: 100, step: 0.05, 'aria-label': `${l} ${SC_LABEL[s]} conversion, percent` });
          const sync = () => { if (document.activeElement !== inp) inp.value = String(+(me.A.rates[k][i] * 100).toFixed(3)); };
          inp.addEventListener('input', () => { const v = parseFloat(inp.value); if (Number.isFinite(v) && v >= 0 && v <= 100) update((A) => { A.rates[k][i] = v / 100; }); });
          inp.addEventListener('change', sync);
          inputs.push(sync); sync();
          return inp;
        }),
      ])),
    h('p', { class: 'vp-field__help' }, 'Multiplied by the college-type factor and the contact factor (1.0 verified placement line · 0.8 office line · 0.6 none). Research anchor: ~1% lead-to-enrollment industry index.'));

  const team = h('fieldset', { class: 'vp-fs' }, h('legend', null, 'Ambassador productivity'),
    slider({ label: 'Paid enrollments per active ambassador', min: 1, max: 20, step: 0.5, get: () => me.A.paid_per_active, set: (A, v) => { A.paid_per_active = v; }, show: n1 }),
    slider({ label: 'Share of ambassadors who stay active', min: 0.1, max: 1, step: 0.05, get: () => me.A.active_share, set: (A, v) => { A.active_share = v; }, show: (v) => `${Math.round(v * 100)}%` }),
    derived,
    slider({ label: 'Buffer on the minimum', min: 1, max: 2, step: 0.05, get: () => me.A.buffer, set: (A, v) => { A.buffer = v; }, show: (v) => `× ${n1(v)}`, help: 'Recruit against buffer × minimum to absorb drop-outs.' }));

  const struct = h('fieldset', { class: 'vp-fs' }, h('legend', null, 'Team structure'),
    h('div', { class: 'vp-grid2' },
      numIn({ label: 'Min. ambassadors per college', min: 1, max: 50, step: 1, get: () => me.A.min_ambassadors, set: (A, v) => { A.min_ambassadors = v; } }),
      numIn({ label: 'Standby: 1 per', min: 1, max: 50, step: 1, suffix: 'ambassadors', get: () => me.A.standby_per, set: (A, v) => { A.standby_per = v; } }),
      numIn({ label: 'Own College Lead from', min: 1, max: 50, step: 1, suffix: 'ambassadors', get: () => me.A.own_lead_from, set: (A, v) => { A.own_lead_from = v; }, help: 'Smaller colleges share a Lead with one college in the same town.' }),
      numIn({ label: 'Lead capacity (span)', min: 2, max: 50, step: 1, suffix: 'ambassadors', get: () => me.A.lead_span, set: (A, v) => { A.lead_span = v; }, help: 'Above this, ambassador leads are added (research: 7).' }),
      numIn({ label: 'College Leads per District Lead', min: 1, max: 50, step: 1, get: () => me.A.district_lead_span, set: (A, v) => { A.district_lead_span = v; } })));

  const targets = h('fieldset', { class: 'vp-fs' }, h('legend', null, 'Personal targets per ambassador'),
    h('div', { class: 'vp-grid3' },
      ...[['min', 'Minimum'], ['standard', 'Standard'], ['stretch', 'Stretch']].map(([k, l]) => numIn({ label: l, min: 0, max: 1000, step: 1, get: () => me.A.amb_targets[k], set: (A, v) => { A.amb_targets[k] = v; } }))),
    numIn({ label: 'Programme goal (paid enrollments)', min: 1, max: 100000, step: 1, get: () => me.A.program_target, set: (A, v) => { A.program_target = v; } }));

  const reset = ui.button({ label: 'Reset to research defaults', icon: 'refresh', onClick: () => {
    lsSet(LS_KEY, null); me.A = normalizeAssumptions(baseDefaults(me)); drawResults(me, { now: true }); syncInputs(); ui.toast('Assumptions reset to the research defaults', 'info');
  } });
  body.append(
    h('p', { class: 'vp-assume__note' }, 'These are planning assumptions from the research (v2, 7 Nov 2026), not measured results. Replace them with Tech Drona’s own conversion and ambassador numbers after two weeks of selling. Changes are saved in this browser only.'),
    h('div', { class: 'vp-assume__grid' }, years, rateGrid, team, struct, targets),
    h('div', { class: 'vp-assume__foot' }, reset));
  syncInputs();
  return det;
}

/* ------------------------------------------------------------------ c. what it takes */
function reachSection(me) {
  const { ctx, plan } = me;
  const { h, ui, fmt } = ctx;
  const A = plan.A, T = plan.totals;
  const card = (s) => {
    const r = plan.reach[s];
    const head = r.reached
      ? h('p', { class: 'vp-reach__lead' }, `The top `, h('strong', null, fmt.plural(r.colleges, 'college')), ` by priority reach ${fmt.num(r.total)} on the ${SC_LABEL[s].toLowerCase()} scenario.`)
      : h('p', { class: 'vp-reach__lead vp-reach__lead--bad' }, `Even all ${fmt.plural(r.colleges, 'targeted college')} reach only ${fmt.num(r.total)} on the ${SC_LABEL[s].toLowerCase()} scenario — `, h('strong', null, `${fmt.num(r.shortfall)} short`), '.');
    const cell = (label, v, sub) => h('div', { class: 'vp-kpi' }, h('div', { class: 'vp-kpi__v td-num' }, v), h('div', { class: 'vp-kpi__l' }, label), sub ? h('div', { class: 'vp-kpi__s' }, sub) : null);
    return h('article', { class: ['vp-reach', r.reached ? 'is-ok' : 'is-short'] },
      h('h3', { class: 'vp-reach__title' }, `${SC_LABEL[s]} scenario`, ui.badge(r.reached ? 'Goal reached' : 'Goal not reached', r.reached ? 'good' : 'bad')),
      head,
      h('div', { class: 'vp-kpis' },
        cell('Colleges', fmt.num(r.colleges)),
        cell('College Leads', fmt.num(r.college_leads), 'shared Leads count once'),
        cell('Ambassador leads', fmt.num(r.ambassador_leads)),
        cell('Ambassadors', fmt.num(r.ambassadors), `+ ${fmt.num(r.standby)} standby`)),
      h('table', { class: 'vp-mini' },
        h('caption', { class: 'td-sr-only' }, `Expected output per person, ${SC_LABEL[s]} scenario`),
        h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Expected paid'), ...SC.map((x) => h('th', { scope: 'col', class: 'td-al-right' }, SC_LABEL[x])))),
        h('tbody', null,
          h('tr', null, h('th', { scope: 'row' }, 'Per ambassador'), ...SC.map((x) => h('td', { class: 'td-al-right td-num' }, n1(r.perAmbassador[x])))),
          h('tr', null, h('th', { scope: 'row' }, 'Per College Lead (team)'), ...SC.map((x) => h('td', { class: 'td-al-right td-num' }, n1(r.perLead[x])))))));
  };
  const all = h('table', { class: 'vp-mini vp-mini--wide' },
    h('caption', null, `Whole selection (${fmt.plural(T.targeted, 'targeted college')})`),
    h('thead', null, h('tr', null, h('th', { scope: 'col' }, ''), ...SC.map((x) => h('th', { scope: 'col', class: 'td-al-right' }, SC_LABEL[x])))),
    h('tbody', null,
      h('tr', null, h('th', { scope: 'row' }, 'Paid enrollments'), ...SC.map((x) => h('td', { class: 'td-al-right td-num' }, fmt.num(T[x])))),
      h('tr', null, h('th', { scope: 'row' }, 'Per ambassador'), ...SC.map((x) => h('td', { class: 'td-al-right td-num' }, n1(plan.perAmbassador[x])))),
      h('tr', null, h('th', { scope: 'row' }, 'Per College Lead (team incl. own sales)'), ...SC.map((x) => h('td', { class: 'td-al-right td-num' }, n1(plan.perLead[x]))))));
  const team = h('ul', { class: 'vp-team' },
    h('li', null, h('strong', { class: 'td-num' }, fmt.num(T.college_leads)), ' College Leads'),
    h('li', null, h('strong', { class: 'td-num' }, fmt.num(T.ambassador_leads)), ' ambassador leads'),
    h('li', null, h('strong', { class: 'td-num' }, fmt.num(T.ambassadors)), ' ambassadors + ', h('strong', { class: 'td-num' }, fmt.num(T.standby)), ' standby'),
    h('li', null, h('strong', { class: 'td-num' }, fmt.num(T.district_leads)), ' District/City Leads'),
    h('li', null, 'Personal targets: ', h('strong', null, `${A.amb_targets.min} / ${A.amb_targets.standard} / ${A.amb_targets.stretch}`), ' paid (min / standard / stretch)'));
  return ui.section({
    title: `What it takes to reach ${fmt.num(A.program_target)}`,
    sub: 'Colleges are added in priority order until the scenario total reaches the goal. Minimum is the planning number; recruit against the buffered minimum.',
    body: [h('div', { class: 'vp-reach-grid' }, card('min'), card('avg')), h('div', { class: 'vp-reach-all' }, all, h('div', null, h('h3', { class: 'vp-h4' }, 'Full team for the selection'), team))],
  });
}

/* ------------------------------------------------------------------ d. districts */
function districtSection(me) {
  const { ctx, plan } = me;
  const { h, ui, fmt } = ctx;
  const mode = me.ui.distMode;
  const rows = (mode === 'groups' ? plan.groups : plan.districts).filter((g) => g.colleges > 0);
  const label = (g) => (mode === 'groups' ? g.key : districtName(ctx, g.key));
  const groups = groupsNow();
  const sub = (g) => (mode === 'groups' ? (groups[g.key] || []).map((id) => districtName(ctx, id)).join(', ') : (plan.colleges.find((r) => r.district_id === g.key)?.group || 'not a target district'));
  const toggle = h('div', { class: 'vp-seg', role: 'group', 'aria-label': 'Group districts by' },
    ...[['groups', 'Target groups'], ['districts', 'Present-day districts']].map(([k, l]) => h('button', {
      type: 'button', class: ['vp-seg__b', mode === k && 'is-on'], 'aria-pressed': String(mode === k),
      onClick: () => { me.ui.distMode = k; lsSet(LS_UI, { ...(lsGet(LS_UI) || {}), distMode: k }); me.nodes.dist.replaceChildren(districtSection(me)); },
    }, l)));
  const max = Math.max(1, ...rows.map((g) => g.max));
  const target = plan.A.program_target;
  const chart = h('figure', { class: 'vp-range-chart', role: 'group', 'aria-label': 'Planned paid enrollments by district: minimum to maximum, average marked' },
    h('div', { class: 'vp-rc-legend', 'aria-hidden': 'true' },
      h('span', null, h('i', { class: 'vp-rc-key vp-rc-key--range' }), 'Min – max'), h('span', null, h('i', { class: 'vp-rc-key vp-rc-key--avg' }), 'Average'),
      h('span', null, `% = average as a share of the ${fmt.num(target)} goal`)),
    h('ul', { class: 'vp-rc', 'aria-hidden': 'true' }, ...rows.map((g) => h('li', { class: 'vp-rc__row' },
      h('span', { class: 'vp-rc__label' }, label(g)),
      h('span', { class: 'vp-rc__track' },
        h('span', { class: 'vp-rc__range', style: { left: `${(g.min / max) * 100}%`, width: `${Math.max(0.6, ((g.max - g.min) / max) * 100)}%` } }),
        h('span', { class: 'vp-rc__avg', style: { left: `${(g.avg / max) * 100}%` } })),
      h('span', { class: 'vp-rc__val td-num' }, `${fmt.num(g.min)}–${fmt.num(g.avg)}–${fmt.num(g.max)}`, h('small', null, fmt.pct(g.shareOfTarget.avg)))))),
    h('figcaption', { class: 'td-sr-only' }, rows.map((g) => `${label(g)}: ${g.min} to ${g.max}, average ${g.avg}`).join('; ')));
  const tbl = h('div', { class: 'vp-scroll', tabindex: '0', role: 'region', 'aria-label': 'District breakdown table' },
    h('table', { class: 'vp-table' },
      h('thead', null, h('tr', null,
        ...[mode === 'groups' ? 'Target group' : 'District', 'Active colleges', 'Targeted', 'IT students (selected years)', 'Min', 'Avg', 'Max', `Share of ${fmt.num(target)} (min / avg / max)`, 'College Leads', 'Amb. leads', 'Ambassadors', 'Standby', mode === 'groups' ? 'District Leads' : null, 'Recruited', 'Confirmed']
          .filter((x) => x !== null).map((x, i) => h('th', { scope: 'col', class: i ? 'td-al-right' : null }, x)))),
      h('tbody', null, ...rows.map((g) => h('tr', null,
        h('th', { scope: 'row' }, h('span', { class: 'vp-strong' }, label(g)), h('small', { class: 'vp-sub' }, sub(g))),
        ...[g.colleges, g.targeted, g.pool, g.min, g.avg, g.max].map((v) => h('td', { class: 'td-al-right td-num' }, fmt.num(v))),
        h('td', { class: 'td-al-right td-num' }, SC.map((s) => fmt.pct(g.shareOfTarget[s])).join(' / ')),
        h('td', { class: 'td-al-right td-num' }, n1(g.college_leads)),
        ...[g.ambassador_leads, g.ambassadors, g.standby].map((v) => h('td', { class: 'td-al-right td-num' }, fmt.num(v))),
        mode === 'groups' ? h('td', { class: 'td-al-right td-num' }, fmt.num(g.district_leads)) : null,
        h('td', { class: 'td-al-right td-num' }, fmt.num(g.recruited)),
        h('td', { class: 'td-al-right td-num' }, fmt.num(g.confirmed))))),
      h('tfoot', null, h('tr', null, h('th', { scope: 'row' }, 'Selection'),
        ...[plan.totals.colleges, plan.totals.targeted, plan.totals.pool, plan.totals.min, plan.totals.avg, plan.totals.max].map((v) => h('td', { class: 'td-al-right td-num' }, fmt.num(v))),
        h('td', { class: 'td-al-right td-num' }, SC.map((s) => fmt.pct(plan.totals.pctOfTarget[s])).join(' / ')),
        h('td', { class: 'td-al-right td-num' }, n1(plan.totals.college_leads)),
        ...[plan.totals.ambassador_leads, plan.totals.ambassadors, plan.totals.standby].map((v) => h('td', { class: 'td-al-right td-num' }, fmt.num(v))),
        mode === 'groups' ? h('td', { class: 'td-al-right td-num' }, fmt.num(plan.totals.district_leads)) : null,
        h('td', { class: 'td-al-right td-num' }, fmt.num(plan.totals.recruited)),
        h('td', { class: 'td-al-right td-num' }, fmt.num(plan.totals.confirmed))))));
  return ui.section({
    title: 'District breakdown',
    sub: 'Target groups are the old undivided districts (they include districts formed in 2022: Palnadu, Bapatla, NTR, Eluru). A college shared by two Leads counts 0.5.',
    actions: [toggle],
    body: rows.length ? [chart, tbl] : ui.emptyState({ title: 'No colleges in this district selection', text: 'Choose districts with the district selector at the top of the page.' }),
  });
}

/* ------------------------------------------------------------------ e. colleges */
const COLS = [
  { key: 'rank', label: '#', num: true },
  { key: 'p', label: 'Priority' },
  { key: 'name', label: 'College' },
  { key: 'it_branch_count', label: 'IT branches', num: true },
  { key: 'it_fy', label: 'IT final yr', num: true },
  { key: 'it_3rd', label: '3rd yr', num: true },
  { key: 'it_2nd', label: '2nd yr', num: true },
  { key: 'reachable', label: 'Reachable', num: true, tip: 'IT students in the selected year groups × contact factor' },
  { key: 'min', label: 'Min', num: true },
  { key: 'avg', label: 'Avg', num: true },
  { key: 'max', label: 'Max', num: true },
  { key: 'amb', label: 'Ambassadors (have / need)', num: true },
  { key: 'lead', label: 'College Lead' },
  { key: 'confirmed', label: 'Confirmed', num: true },
  { key: 'rag', label: '400 here?' },
  { key: 'offer', label: 'Lead offer' },
  { key: 'act', label: 'Actions', nosort: true },
];
const P_ORDER = { P1: 1, P2: 2, P3: 3, Hold: 4 };
function sortValue(r, k) {
  const c = r.college;
  switch (k) {
    case 'p': return P_ORDER[c.p_level] ?? 9;
    case 'name': return (c.short_name || c.name || '').toLowerCase();
    case 'it_branch_count': return c.it_branch_count;
    case 'it_fy': case 'it_3rd': case 'it_2nd': return val(c[k]);
    case 'amb': return r.ambassadors;
    case 'lead': return r.college_leads;
    case 'rag': return { GREEN: 1, AMBER: 2, RED: 3 }[r.rag];
    case 'offer': return offerCode(c.lead_offer);
    default: return r[k];
  }
}

function collegeSection(me) {
  const { ctx } = me;
  const { h, ui } = ctx;
  const host = h('div');
  const search = h('input', { class: 'td-input vp-search', type: 'search', placeholder: 'Search college, town or district', 'aria-label': 'Search colleges', value: me.ui.q });
  const tableHost = h('div');
  const sel = (label, key, opts) => {
    const s = h('select', { class: 'td-input td-select vp-sel', 'aria-label': label }, ...opts.map(([v, l]) => h('option', { value: v, selected: me.ui[key] === v }, l)));
    s.addEventListener('change', () => { me.ui[key] = s.value; tableHost.replaceChildren(collegeTable(me)); });
    return s;
  };
  let t = null;
  search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { me.ui.q = search.value; tableHost.replaceChildren(collegeTable(me)); }, 120); });
  tableHost.append(collegeTable(me));
  host.append(ui.section({
    title: 'Colleges',
    sub: 'Only IT branches count (CSE, IT, AI/ML, DS, Cyber Security, CSBS, IoT, AI&DS …). Expand a row for its branches and its College Lead → ambassador team.',
    body: [
      h('div', { class: 'vp-toolbar' }, search,
        sel('Show', 'show', [['targeted', 'Targeted'], ['hold', 'On hold'], ['all', 'All active']]),
        sel('Priority', 'p', [['', 'All priorities'], ['P1', 'P1'], ['P2', 'P2'], ['P3', 'P3'], ['Hold', 'Hold']])),
      basisLegend(ctx),
      tableHost,
    ],
  }));
  return host;
}

function filteredRows(me) {
  const { plan, ctx } = me;
  const q = me.ui.q.trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9 ]/g, ' ');
  const words = q.split(/\s+/).filter(Boolean);
  let rows = plan.colleges.filter((r) => r.college.status_final === 'active' || r.targeted);
  if (me.ui.show === 'targeted') rows = rows.filter((r) => r.targeted);
  if (me.ui.show === 'hold') rows = rows.filter((r) => !r.targeted);
  if (me.ui.p) rows = rows.filter((r) => (r.college.p_level || 'Hold') === me.ui.p);
  if (words.length) {
    rows = rows.filter((r) => {
      const c = r.college;
      const hay = [c.name, c.short_name, c.city, districtName(ctx, c.district_id), r.group, c.college_id].filter(Boolean).join(' ').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9 ]/g, ' ');
      return words.every((w) => hay.includes(w));
    });
  }
  const k = me.ui.sortKey, dir = me.ui.sortDir;
  const coll = new Intl.Collator('en-IN', { numeric: true, sensitivity: 'base' });
  return rows.sort((a, b) => {
    const x = sortValue(a, k), y = sortValue(b, k);
    const xn = x === null || x === undefined || x === '', yn = y === null || y === undefined || y === '';
    if (xn && yn) return (a.rank ?? 999) - (b.rank ?? 999);
    if (xn) return 1; if (yn) return -1;
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : coll.compare(String(x), String(y));
    return c * dir || (a.rank ?? 999) - (b.rank ?? 999);
  });
}

function collegeTable(me) {
  const { ctx } = me;
  const { h, ui, fmt } = ctx;
  const rows = filteredRows(me);
  const wrap = h('div');
  const count = h('p', { class: 'vp-count', role: 'status' }, `${fmt.plural(rows.length, 'college')} shown`);
  if (!rows.length) {
    wrap.append(count, ui.emptyState({ title: 'No colleges match', text: 'Clear the search or change the filters above.' }));
    return wrap;
  }
  const head = h('tr', null, ...COLS.map((c) => {
    const th = h('th', { scope: 'col', class: [c.num && 'td-al-right', `vp-c-${c.key}`], 'aria-sort': me.ui.sortKey === c.key ? (me.ui.sortDir === 1 ? 'ascending' : 'descending') : 'none', title: c.tip });
    if (c.nosort) th.append(h('span', { class: 'td-sr-only' }, c.label));
    else th.append(h('button', { type: 'button', class: 'td-th-sort', onClick: () => {
      if (me.ui.sortKey === c.key) me.ui.sortDir = -me.ui.sortDir; else { me.ui.sortKey = c.key; me.ui.sortDir = c.num && c.key !== 'rank' ? -1 : 1; }
      wrap.replaceWith(collegeTable(me));
    } }, h('span', null, c.label), h('span', { class: 'td-th-sort__ind', 'aria-hidden': 'true' })));
    return th;
  }));
  const tbody = h('tbody');
  const addRows = (from, to) => {
    const frag = document.createDocumentFragment();
    for (const r of rows.slice(from, to)) {
      const open = me.ui.expanded.has(r.id);
      frag.append(collegeRow(me, r, open));
      if (open) frag.append(detailRow(me, r));
    }
    tbody.append(frag);
  };
  // T20: the first rows (and every expanded row) now, the rest in idle chunks; a newer table cancels the old job
  let first = FIRST_ROWS;
  rows.forEach((r, i) => { if (me.ui.expanded.has(r.id)) first = Math.max(first, i + 1); });
  addRows(0, first);
  const job = me.tableJob = (me.tableJob || 0) + 1;
  const more = (from) => {
    if (from >= rows.length || cur !== me || me.tableJob !== job || !wrap.isConnected) return;
    addRows(from, from + CHUNK_ROWS);
    idle(() => more(from + CHUNK_ROWS));
  };
  if (first < rows.length) idle(() => more(first));
  const scroller = h('div', { class: 'vp-scroll vp-scroll--tall', tabindex: '0', role: 'region', 'aria-label': 'College plan table' },
    h('table', { class: 'vp-table vp-table--colleges' }, h('thead', null, head), tbody));
  wrap.classList.add('vp-ctable');
  wrap.append(count, scroller);
  return wrap;
}

function collegeRow(me, r, open) {
  const { ctx } = me;
  const { h, ui, fmt } = ctx;
  const c = r.college;
  const tdn = (v, cls) => h('td', { class: ['td-al-right td-num', cls] }, v);
  const toggle = h('button', {
    type: 'button', class: 'vp-exp', 'aria-expanded': String(open), 'aria-controls': `vp-d-${r.id}`,
    'aria-label': `${open ? 'Hide' : 'Show'} branches and team for ${c.name}`,
    onClick: () => {
      if (me.ui.expanded.has(r.id)) me.ui.expanded.delete(r.id); else { me.ui.expanded.add(r.id); loadPeople(me, r.id); }
      const tr = toggle.closest('tr');
      const next = tr.nextElementSibling;
      if (next && next.classList.contains('vp-detail')) next.remove();
      const nowOpen = me.ui.expanded.has(r.id);
      toggle.setAttribute('aria-expanded', String(nowOpen));
      toggle.setAttribute('aria-label', `${nowOpen ? 'Hide' : 'Show'} branches and team for ${c.name}`);
      tr.classList.toggle('is-open', nowOpen);
      if (nowOpen) tr.after(detailRow(me, r));
    },
  }, ui.icon('chevron', { size: 16 }));
  const pTone = { P1: 'brand', P2: 'info', P3: 'neutral', Hold: 'warn' }[c.p_level] || 'neutral';
  const ragB = RAG[r.rag] || ['—', 'neutral'];
  const leadTxt = !r.targeted ? '—' : r.college_leads === 1 ? (r.ambassador_leads ? `Own + ${r.ambassador_leads} amb. leads` : 'Own') : 'Shared (½)';
  const actualLead = (c.actual?.college_leads || 0) > 0;
  const tel = c.contact?.verified ? telOf(c.contact.phone) : null;
  const call = tel
    ? h('a', { class: 'td-btn td-btn--secondary td-btn--sm vp-call', href: `tel:${tel}`, 'aria-label': `Call ${c.name}${c.contact.role ? ` (${c.contact.role})` : ''}`, title: `${c.contact.phone}${c.contact.role ? ' · ' + c.contact.role : ''}` }, ui.icon('phone', { size: 16 }), h('span', null, 'Call'))
    : h('span', { class: 'vp-nocall', title: 'No verified phone number yet' }, 'No verified no.');
  const amb = h('span', { class: 'vp-amb' }, h('span', { class: ['td-num', r.recruited >= r.ambassadors && r.ambassadors ? 'vp-ok' : null] }, fmt.num(r.recruited)), h('span', { class: 'vp-muted' }, ` / ${fmt.num(r.ambassadors)}`), r.standby ? h('small', { class: 'vp-sub' }, `+${r.standby} standby`) : null);
  const tr = h('tr', { 'data-id': r.id, class: [open && 'is-open', !r.targeted && 'is-hold'] },
    h('td', { class: 'vp-c-rank' }, h('span', { class: 'vp-rankcell' }, toggle, h('span', { class: 'td-num' }, c.rank ?? '—'))),
    h('td', null, ui.badge(c.p_level || 'Hold', pTone)),
    h('td', { class: 'vp-c-name' },
      h('a', { href: `#/college/${encodeURIComponent(r.id)}`, class: 'vp-strong vp-name', title: c.name }, c.short_name || c.name),
      h('small', { class: 'vp-sub' }, [c.city, districtName(ctx, c.district_id)].filter(Boolean).join(' · '),
        c.verify_flag ? h('span', { class: 'vp-flag', title: c.verify_flag }, ' · ', ui.icon('warn', { size: 12 }), ' check') : null)),
    tdn(c.it_branch_count ?? '—'),
    h('td', { class: 'td-al-right' }, numB(ctx, c.it_fy, { strong: true })),
    h('td', { class: ['td-al-right', !me.A.years.third && 'vp-off'] }, numB(ctx, c.it_3rd)),
    h('td', { class: ['td-al-right', !me.A.years.second && 'vp-off'] }, numB(ctx, c.it_2nd)),
    tdn(r.reachable === null ? '—' : fmt.num(r.reachable)),
    tdn(fmt.num(r.min), 'vp-strong'), tdn(fmt.num(r.avg)), tdn(fmt.num(r.max)),
    h('td', { class: 'td-al-right' }, amb),
    h('td', null, h('span', { class: 'vp-lead' }, leadTxt, actualLead ? ui.badge('appointed', 'good') : (r.targeted ? h('small', { class: 'vp-sub' }, 'not appointed') : null))),
    tdn(fmt.num(r.confirmed)),
    h('td', null, r.college.status_final === 'active' ? h('span', { class: ['td-badge', `td-badge--${ragB[1]}`, 'td-badge--dot'], title: rgTip(r.rag) }, ragB[0]) : '—'),
    h('td', null, offerCode(c.lead_offer) ? h('span', { class: 'vp-offer', title: c.lead_offer }, `(${offerCode(c.lead_offer)})`) : '—'),
    h('td', { class: 'vp-c-act' }, h('span', { class: 'vp-actions' }, call,
      h('a', { class: 'td-btn td-btn--ghost td-btn--sm td-btn--icon', href: `#/college/${encodeURIComponent(r.id)}`, 'aria-label': `Open ${c.name}`, title: 'Open college page' }, ui.icon('arrow', { size: 16 })))));
  // column class + label on every cell: the phone layout (views-plan.css, ≤599px) turns each row into a labelled card
  [...tr.children].forEach((td, i) => { const col = COLS[i]; if (!col) return; td.classList.add(`vp-c-${col.key}`); td.dataset.label = col.label; });
  return tr;
}
const rgTip = (k) => ({ GREEN: 'Average ≥ 400 from individual sign-ups', AMBER: '400 only via an institutional MoU covering ~half the IT students, from Jan 2027', RED: 'Not reachable by any modelled route' }[k] || '');

function detailRow(me, r) {
  const { ctx } = me;
  const { h, ui, fmt } = ctx;
  const c = r.college;
  const it = (c.branches || []).filter((b) => b.is_it);
  const hidden = (c.branches || []).length - it.length;
  const branches = it.length
    ? h('div', { class: 'vp-xscroll' }, h('table', { class: 'vp-mini vp-mini--branches' },
      h('caption', null, `IT branches (${it.length})`, hidden ? h('small', { class: 'vp-sub' }, ` · ${hidden} non-IT branches hidden`) : null),
      h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Branch'), h('th', { scope: 'col', class: 'td-al-right', title: 'Intake of the 2023-24 entry batch = this year’s final years' }, 'Final yr (2023-24)'), h('th', { scope: 'col', class: 'td-al-right' }, 'Latest intake'), h('th', { scope: 'col' }, 'Source'))),
      h('tbody', null, ...it.map((b) => h('tr', null,
        h('th', { scope: 'row' }, b.name),
        h('td', { class: 'td-al-right' }, numB(ctx, { value: b.intake_2023_24, basis: b.basis })),
        h('td', { class: 'td-al-right td-num' }, b.intake_latest == null ? '—' : fmt.num(b.intake_latest)),
        h('td', null, srcLink(ctx, b.source) || h('span', { class: 'vp-muted' }, '—')))))))
    : h('p', { class: 'vp-muted' }, 'No IT branch list in the research for this college.');
  const planNums = ui.kv([
    ['IT branches', c.it_branch_count == null ? '—' : fmt.num(c.it_branch_count)],
    ['IT students (final · 3rd · 2nd yr)', h('span', null, numB(ctx, c.it_fy), ' · ', numB(ctx, c.it_3rd), ' · ', numB(ctx, c.it_2nd))],
    ['Reachable', r.reachable === null ? '—' : fmt.num(r.reachable)],
    ['Planned paid (min · avg · max)', `${fmt.num(r.min)} · ${fmt.num(r.avg)} · ${fmt.num(r.max)}`],
    ['Confirmed so far', fmt.num(r.confirmed)],
    ['400 here?', r.college.status_final === 'active' ? `${(RAG[r.rag] || ['—'])[0]} — ${rgTip(r.rag)}` : '—'],
  ]);
  const facts = ui.kv([
    ['IT final-year pool', h('span', null, numB(ctx, c.it_fy), ' ', srcLink(ctx, c.it_fy?.source))],
    ['All-branch final year', h('span', null, numB(ctx, c.fy_pool), ' ', srcLink(ctx, c.fy_pool?.source))],
    ['Total students', h('span', null, numB(ctx, c.total_students), c.total_students?.year ? h('small', { class: 'vp-sub' }, ` ${c.total_students.year}`) : null, ' ', srcLink(ctx, c.total_students?.source))],
    ['Type · contact factor', `${c.type ? c.type.toUpperCase() : '—'} · × ${c.access_x ?? '—'}`],
    ['Research target (min/avg/max)', c.research_target ? `${fmt.num(c.research_target.min)} / ${fmt.num(c.research_target.avg)} / ${fmt.num(c.research_target.max)}` : '—'],
    ['MoU pipeline from Jan 2027', c.mou ? `${fmt.num(c.mou.min)} / ${fmt.num(c.mou.avg)} / ${fmt.num(c.mou.max)} seats` : '—'],
    ['4-1 exams end', c.exam_4_1_end ? fmt.date(c.exam_4_1_end) : (c.exam_4_1_note || '—')],
    ['Placement', c.placement_tier || '—'],
    ['Lead offer', c.lead_offer || '—'],
    c.hold_reason ? ['Why on hold', c.hold_reason] : null,
    c.verify_flag ? ['To verify', c.verify_flag] : null,
    ['Contact', c.contact ? h('span', null, [c.contact.name, c.contact.role].filter(Boolean).join(' · ') || 'College office', ' ',
      c.contact.phone ? (c.contact.verified && telOf(c.contact.phone) ? h('a', { href: `tel:${telOf(c.contact.phone)}` }, c.contact.phone) : h('span', null, c.contact.phone, ' ', ui.provenance('pending'))) : null,
      c.contact.verified ? ' ' : null, c.contact.verified ? ui.provenance('verified') : null, ' ', srcLink(ctx, c.contact.source)) : 'No contact in the research'],
  ]);
  const teamHost = h('div', { class: 'vp-tree-host' });
  drawTeam(me, r, teamHost);
  return h('tr', { class: 'vp-detail', id: `vp-d-${r.id}` }, h('td', { colspan: String(COLS.length) },
    h('div', { class: 'vp-detail__grid' },
      h('div', { class: 'vp-detail__col' }, h('h3', { class: 'vp-h4' }, 'Team for this college'), teamHost),
      h('div', { class: 'vp-detail__col' }, h('h3', { class: 'vp-h4' }, 'IT strength'), branches),
      h('div', { class: 'vp-detail__col' }, h('h3', { class: 'vp-h4' }, 'Plan for this college'), planNums, h('h3', { class: 'vp-h4 vp-h4--gap' }, 'Research facts'), facts))));
}

async function loadPeople(me, id) {
  if (me.people.has(id)) return;
  const inline = me.plan?.byId.get(id)?.college.actual?.people;
  if (Array.isArray(inline)) { me.people.set(id, inline); return; }
  me.people.set(id, 'loading');
  try {
    const rows = await me.ctx.api.get('/people', { college: id });
    if (cur !== me) return;
    me.people.set(id, Array.isArray(rows) ? rows : (rows?.rows || []));
  } catch (e) {
    if (cur !== me) return;
    me.people.set(id, { error: e });
  }
  const host = me.el.querySelector(`#vp-d-${CSS.escape(id)} .vp-tree-host`);
  const r = me.plan.byId.get(id);
  if (host && r) drawTeam(me, r, host);
}

function drawTeam(me, r, host) {
  const { ctx } = me;
  const { h, ui, fmt } = ctx;
  let st = me.people.get(r.id);
  if (st === undefined && Array.isArray(r.college.actual?.people)) { st = r.college.actual.people; me.people.set(r.id, st); }
  if (st === undefined) { loadPeople(me, r.id); host.replaceChildren(ui.spinner({ label: 'Loading team…', size: 'sm' })); return; }
  if (st === 'loading') { host.replaceChildren(ui.spinner({ label: 'Loading team…', size: 'sm' })); return; }
  if (st && st.error) { host.replaceChildren(h('p', { class: 'vp-muted' }, `Could not load the team: ${st.error.message || st.error}`)); return; }
  const people = (st || []).filter((p) => p.status !== 'inactive');
  const leads = people.filter((p) => p.role === 'college_lead');
  const aLeads = people.filter((p) => p.role === 'ambassador_lead');
  const ambs = people.filter((p) => p.role === 'ambassador');
  const add = (role, reports_to) => async () => {
    try { const f = await import('./forms.js'); const saved = await f.addPerson(ctx, { college_id: r.id, role, reports_to }); if (saved) { me.focus = r.id; me.params = { ...me.params, college: r.id }; load(me); } } catch (e) { ui.toast(e.message || 'Could not open the form', 'bad'); }
  };
  const person = (p, roleLabel) => h('li', { class: 'vp-node vp-node__row' },
    h('span', { class: 'vp-node__dot is-filled', 'aria-hidden': 'true' }),
    h('a', { href: `#/person/${encodeURIComponent(p.id)}`, class: 'vp-strong' }, p.full_name || `Person ${p.id}`),
    h('small', { class: 'vp-sub' }, ` ${roleLabel}${p.status && p.status !== 'active' ? ` · ${p.status}` : ''}${p.enrolled != null ? ` · ${fmt.num(p.enrolled)} confirmed` : ''}`));
  const addBtn = (label, role, reports_to) => h('button', { type: 'button', class: 'td-btn td-btn--ghost td-btn--sm vp-add', onClick: add(role, reports_to), 'aria-label': `Add ${label.toLowerCase()} at ${r.college.name}` }, ui.icon('plus', { size: 14 }), h('span', null, 'Add person'));
  /** n vacant slots as compact dashed chips plus one "Add person" button */
  const vacancies = (n, label, role, reports_to) => (n > 0 ? h('li', { class: 'vp-node vp-node--vacant' },
    h('span', { class: 'vp-slots', role: 'img', 'aria-label': `${n} vacant ${label.toLowerCase()} ${n === 1 ? 'slot' : 'slots'}` },
      ...Array.from({ length: Math.min(n, 24) }, () => h('span', { class: 'vp-slot', 'aria-hidden': 'true' })), n > 24 ? h('small', null, `+${n - 24}`) : null),
    h('span', { class: 'vp-muted vp-slots__t' }, `${n} vacant ${n === 1 ? label.toLowerCase() : label.toLowerCase() + 's'}`),
    addBtn(label, role, reports_to)) : null);
  if (!r.targeted && !people.length) { host.replaceChildren(h('p', { class: 'vp-muted' }, 'Not targeted under the current assumptions, so no team is planned.')); return; }
  const lead = leads[0];
  const needAL = r.ambassador_leads;
  const needAmb = r.ambassadors;
  const vacantAmb = Math.max(0, needAmb - ambs.length);
  let subTree;
  if (needAL || aLeads.length) {
    // split ambassadors (people first, then vacancies) evenly across ambassador leads
    const nAL = Math.max(needAL, aLeads.length);
    // hierarchy by reports_to: ambassadors under their ambassador lead; anyone else reports to the College Lead directly
    const alIds = new Set(aLeads.map((p) => p.id));
    const direct = ambs.filter((p) => !alIds.has(p.reports_to));
    const per = Array.from({ length: nAL }, (_, i) => ({ people: aLeads[i] ? ambs.filter((p) => p.reports_to === aLeads[i].id) : [], vacant: Math.floor(vacantAmb / nAL) + (i < vacantAmb % nAL ? 1 : 0) }));
    subTree = h('ul', { class: 'vp-tree' }, ...direct.map((p) => person(p, 'Ambassador (reports to the College Lead)')), ...per.map((g, i) => h('li', { class: 'vp-node vp-node--branch' },
      aLeads[i] ? h('span', { class: 'vp-node__row' }, h('span', { class: 'vp-node__dot is-filled', 'aria-hidden': 'true' }), h('a', { href: `#/person/${encodeURIComponent(aLeads[i].id)}`, class: 'vp-strong' }, aLeads[i].full_name), h('small', { class: 'vp-sub' }, ' Ambassador lead'))
        : h('span', { class: 'vp-node__row' }, h('span', { class: 'vp-node__dot', 'aria-hidden': 'true' }), h('span', { class: 'vp-muted' }, `Vacant — Ambassador lead ${i + 1}`), addBtn('Ambassador lead', 'ambassador_lead', lead?.id)),
      h('ul', { class: 'vp-tree' }, ...g.people.map((p) => person(p, 'Ambassador')), vacancies(g.vacant, 'Ambassador', 'ambassador', aLeads[i]?.id || lead?.id)))));
  } else subTree = h('ul', { class: 'vp-tree' }, ...ambs.map((p) => person(p, 'Ambassador')), vacancies(vacantAmb, 'Ambassador', 'ambassador', lead?.id));
  const leadNode = h('li', { class: 'vp-node vp-node--root' },
    lead ? h('span', { class: 'vp-node__row' }, h('span', { class: 'vp-node__dot is-filled', 'aria-hidden': 'true' }), h('a', { href: `#/person/${encodeURIComponent(lead.id)}`, class: 'vp-strong' }, lead.full_name), h('small', { class: 'vp-sub' }, ' College Lead'))
      : h('span', { class: 'vp-node__row' }, h('span', { class: 'vp-node__dot', 'aria-hidden': 'true' }), h('span', { class: 'vp-muted' }, 'Vacant — College Lead'), addBtn('College Lead', 'college_lead')),
    subTree);
  const sum = h('p', { class: 'vp-team-sum' },
    `Needs 1 College Lead${r.college_leads < 1 ? ' (shared with a nearby college)' : ''}`, needAL ? `, ${needAL} ambassador leads` : '',
    `, ${fmt.num(needAmb)} ambassadors + ${fmt.num(r.standby)} standby. Recruited: ${fmt.plural(ambs.length, 'ambassador')}.`,
    r.lead_note ? h('small', { class: 'vp-sub' }, ` (${r.lead_note})`) : null);
  const perAmb = r.ambassadors ? h('p', { class: 'vp-sub' }, `Expected per ambassador: ${SC.map((s) => n1(r.perAmb[s])).join(' / ')} (min / avg / max)`) : null;
  host.replaceChildren(sum, h('ul', { class: 'vp-tree vp-tree--root', 'aria-label': `Team hierarchy for ${r.college.name}` }, leadNode), perAmb);
}

/* ------------------------------------------------------------------ f. progress & analytics */
function analyticsSection(me) {
  const { ctx, plan } = me;
  const { h, ui, fmt } = ctx;
  const stage = Object.fromEntries(STAGES.map(([k]) => [k, 0]));
  let dropped = 0, calls = 0;
  for (const r of plan.colleges) {
    const a = r.college.actual || {};
    for (const [k] of STAGES) stage[k] += a.leads_by_stage?.[k] || 0;
    dropped += a.leads_by_stage?.dropped || 0;
    calls += a.calls || 0;
  }
  const any = STAGES.some(([k]) => stage[k] > 0);
  const funnelBox = any
    ? charts.funnel({ steps: STAGES.map(([k, l], i) => ({ label: l, value: STAGES.slice(i).reduce((a, [kk]) => a + stage[kk], 0) })), label: 'Student funnel for this selection (students who reached at least each stage)' })
    : ui.emptyState({ icon: 'list', title: 'No students recorded yet', text: 'Lead → interested → registered → applied → confirmed counts appear here as the team records students on each college page.' });
  const P = plan.progress, T = plan.totals;
  const weeks = P.days_left ? P.days_left / 7 : null;
  const paceRows = [
    ['Goal', plan.A.program_target],
    ['Planned minimum', T.min],
    ['Buffered minimum (recruit against this)', T.buffered],
  ].map(([l, tgt]) => h('tr', null, h('th', { scope: 'row' }, l), h('td', { class: 'td-al-right td-num' }, fmt.num(tgt)),
    h('td', { class: 'td-al-right td-num' }, fmt.num(Math.max(0, tgt - P.confirmed))),
    h('td', { class: 'td-al-right td-num' }, weeks ? n1(Math.max(0, tgt - P.confirmed) / weeks) : '—')));
  const pace = h('div', null,
    charts.paceMeter({ done: P.confirmed, target: plan.A.program_target, label: 'Confirmed paid enrollments vs goal' }) || null,
    h('table', { class: 'vp-mini' }, h('caption', { class: 'td-sr-only' }, 'Required pace'),
      h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Aim'), h('th', { scope: 'col', class: 'td-al-right' }, 'Target'), h('th', { scope: 'col', class: 'td-al-right' }, 'Still needed'), h('th', { scope: 'col', class: 'td-al-right' }, 'Per week'))),
      h('tbody', null, ...paceRows)),
    h('p', { class: 'vp-sub' }, `${P.days_left ?? '—'} days left including today (to ${fmt.date(plan.A.deadline)}). Only confirmed (verified payment) enrollments count. Calls logged in this selection: ${fmt.num(calls)}.`));
  const withPeople = plan.colleges.filter((r) => (r.college.actual?.ambassadors || 0) > 0 || (r.college.actual?.college_leads || 0) > 0);
  const perf = withPeople.length
    ? h('div', { class: 'vp-scroll', tabindex: '0', role: 'region', 'aria-label': 'Ambassador performance' }, h('table', { class: 'vp-table' },
      h('thead', null, h('tr', null, ...['College', 'Ambassadors (active / recruited / needed)', 'Confirmed', 'Per recruited ambassador', 'Plan per ambassador (min)', 'Status'].map((x, i) => h('th', { scope: 'col', class: i ? 'td-al-right' : null }, x)))),
      h('tbody', null, ...withPeople.sort((a, b) => b.confirmed - a.confirmed).map((r) => {
        const a = r.college.actual || {};
        const per = a.ambassadors ? r.confirmed / a.ambassadors : null;
        const planPer = r.perAmb.min;
        const tone = per === null ? 'neutral' : per >= (planPer || 0) ? 'good' : 'warn';
        return h('tr', null, h('th', { scope: 'row' }, h('a', { href: `#/plan?college=${encodeURIComponent(r.id)}`, onClick: (e) => { e.preventDefault(); openRow(me, r.id); } }, r.college.short_name || r.college.name)),
          h('td', { class: 'td-al-right td-num' }, `${fmt.num(a.active_ambassadors || 0)} / ${fmt.num(a.ambassadors || 0)} / ${fmt.num(r.ambassadors)}`),
          h('td', { class: 'td-al-right td-num' }, fmt.num(r.confirmed)),
          h('td', { class: 'td-al-right td-num' }, n1(per)),
          h('td', { class: 'td-al-right td-num' }, n1(planPer)),
          h('td', { class: 'td-al-right' }, ui.badge(per === null ? 'No ambassadors' : tone === 'good' ? 'On plan' : 'Below plan', tone)));
      }))))
    : ui.emptyState({ icon: 'people', title: 'No College Leads or ambassadors recruited yet', text: `The plan needs ${fmt.num(T.college_leads)} College Leads and ${fmt.num(T.ambassadors)} ambassadors in this selection. Open a college row above and use “Add person” to start filling the vacancies.` });
  return ui.section({
    title: 'Progress & analytics',
    sub: 'Actual numbers recorded in the portal for this district selection (not estimates).',
    body: h('div', { class: 'vp-an-grid' },
      h('div', null, h('h3', { class: 'vp-h4' }, 'Student funnel'), funnelBox, any ? h('p', { class: 'vp-sub' }, 'Each step counts students who reached at least that stage.') : null, dropped ? h('p', { class: 'vp-sub' }, `${fmt.num(dropped)} dropped / refunded (not counted).`) : null),
      h('div', null, h('h3', { class: 'vp-h4' }, 'Confirmed vs required pace'), pace),
      h('div', { class: 'vp-an-wide' }, h('h3', { class: 'vp-h4' }, 'Ambassador performance'), perf)),
  });
}

function openRow(me, id) {
  me.ui.expanded.add(id);
  const r = me.plan.byId.get(id);
  if (r && !r.targeted) me.ui.show = 'all';
  me.nodes.colleges.replaceChildren(collegeSection(me));
  const tr = me.el.querySelector(`tr[data-id="${CSS.escape(id)}"]`);
  if (tr) { tr.scrollIntoView({ block: 'start', behavior: smooth(me.ctx) }); tr.classList.add('is-flash'); tr.querySelector('.vp-exp')?.focus({ preventScroll: true }); }
}

/* ------------------------------------------------------------------ sources */
function sourcesNote(me, d) {
  const { ctx } = me;
  const { h, fmt } = ctx;
  const T = d.totals_research;
  return h('footer', { class: 'vp-sources' },
    h('h3', { class: 'vp-h4' }, 'Where these numbers come from'),
    h('ul', null,
      h('li', null, `Research ${d.research_version || 'v2'}${d.source_report ? ` — report “${String(d.source_report).split(/[\\/]/).pop()}”` : ''}${d.generated_at ? `, loaded ${fmt.date(d.generated_at)}` : ''}.`),
      T ? h('li', null, `Research totals for the ${fmt.num(T.targeted ?? 0)} targeted colleges in this district selection: ${fmt.num(T.min)} / ${fmt.num(T.avg)} / ${fmt.num(T.max)} paid (min / avg / max), ${fmt.num(T.ambassadors)} ambassadors, ${fmt.num(T.college_leads)} College Leads. With the default assumptions this page reproduces them exactly (all districts: 377 / 655 / 1,143, 299 ambassadors, 64 College Leads).`) : null,
      h('li', null, 'Student strength: AICTE EoA, NIRF, mandatory disclosures and annual reports (verified); intake × fill or regional IT share (estimated). Each figure links its source in the expanded row.'),
      h('li', null, 'Conversion rates are planning assumptions anchored on an industry lead-to-enrollment index of about 1%; replace them with measured rates. Nothing on this page is a promise of enrollments.')));
}
