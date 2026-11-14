// Tech Drona portal — "Calls & follow-ups" section, tab 1: the call queue. Route: #/calls (?filter=&sort=&dir=&q=&page=)
// A prioritised list of colleges to call: best number, last outcome, next call date and a fast "Log call".
// Priority is internal (it only orders this list); every number comes from GET /api/calls/queue (scoped by district).
// Also exports the small "ops kit" shared by followups.js, exams.js and admin.js: section header + feature-detected
// wrappers around the shared components (dataTable, kpi, contactActions …) so the views keep working on older shells.
import * as forms from './forms.js';
import { getScope, scopeLabel, scopeRows, SCOPE_EVENT } from '../state.js';

/* =====================================================================================================
   Ops kit (shared by the OP views). Uses ctx.ui.* when the shell provides it, a compact fallback otherwise.
   ===================================================================================================== */

/** Current `#/path?query` as an object. */
export function getQuery() {
  const raw = location.hash.split('?')[1] || '';
  return Object.fromEntries(new URLSearchParams(raw));
}
/** Merge {k: v|null} into the hash query without re-routing (empty / null values are removed). */
export function setQuery(ctx, kv) {
  if (typeof ctx.ui.setHashQuery === 'function') {
    const clean = Object.fromEntries(Object.entries(kv).map(([k, v]) => [k, v === '' || v === undefined || v === false ? null : v]));
    try { ctx.ui.setHashQuery(clean, { replace: 'auto' }); return; } catch { /* fall through */ }
  }
  const [base, raw] = location.hash.split('?');
  const q = new URLSearchParams(raw || '');
  for (const [k, v] of Object.entries(kv)) { if (v === null || v === undefined || v === '' || v === false) q.delete(k); else q.set(k, String(v)); }
  const s = q.toString().replace(/%2C/g, ',');
  try { history.replaceState(history.state, '', `${base || '#/'}${s ? '?' + s : ''}`); } catch { /* ignore */ }
}

/** Scoped GET (adds districts= from the global scope); falls back to plain GET + client-side filtering on old shells. */
export async function getScoped(ctx, path, params = {}) {
  if (typeof ctx.api.getScoped === 'function') return ctx.api.getScoped(path, params);
  return ctx.api.get(path, params);
}

/** Section header shared by #/calls and #/followups: one title, the scope pill and the two tabs. */
export function opsHeader(ctx, { active, actions = [], counts = {} }) {
  const { h, ui } = ctx;
  const tabs = [
    { label: 'Call queue', href: '#/calls', active: active === 'calls', count: counts.calls },
    { label: 'Follow-ups', href: '#/followups', active: active === 'followups', count: counts.followups },
  ];
  const sub = active === 'calls'
    ? 'Call the colleges most likely to bring students first, log every call, and set a call-back date.'
    : 'Call-backs and to-dos for colleges, branches and team members. Overdue items are highlighted.';
  // new shell: it draws the "Call queue | Follow-ups" section tabs itself (components.md) — only add the scope pill here
  const extended = typeof ui.linkTabs === 'function';
  const head = ui.pageHeader(extended
    ? { title: active === 'calls' ? 'Call queue' : 'Follow-ups', eyebrow: 'Calls & follow-ups', sub, actions, scope: true }
    : { title: 'Calls & follow-ups', sub, actions });
  if (extended) return head;
  // older shell: render the scope line + tabs ourselves
  const nav = h('nav', { class: 'opk-tabs', 'aria-label': 'Calls & follow-ups' }, tabs.map((t) => h('a', {
    href: t.href, class: ['opk-tab', t.active && 'is-active'], 'aria-current': t.active ? 'page' : null,
  }, t.label, t.count ? h('span', { class: 'opk-tab__n td-num' }, String(t.count)) : null)));
  return h('div', { class: 'opk-head' }, head, scopeLine(ctx), nav);
}

/** "Showing: Guntur · Krishna · West Godavari  [Change]" (only used when the shell has no scope pill). */
export function scopeLine(ctx, prefix = 'Districts') {
  const { h, ui } = ctx;
  if (typeof ui.scopePill === 'function') return ui.scopePill();
  const sc = getScope();
  return h('div', { class: 'opk-scope' }, ui.icon('map', { size: 16 }),
    h('span', null, `${prefix}: `, h('strong', null, sc.all ? 'All districts' : scopeLabel({ max: 6 })), sc.isDefault ? ' (target districts)' : ''),
    typeof ctx.openDistrictScope === 'function' ? ui.button({ label: 'Change', size: 'sm', tone: 'ghost', onClick: () => ctx.openDistrictScope() }) : null);
}

export function kpiRow(ctx, items) {
  const { h, ui } = ctx;
  if (typeof ui.kpi === 'function' && typeof ui.kpiRow === 'function') return ui.kpiRow(items.map((k) => ui.kpi(k)));
  return h('div', { class: 'opk-kpis' }, items.map((k) => ui.statCard({ label: k.label, value: k.value, sub: k.sub, tone: k.tone === 'brand' ? 'info' : k.tone, icon: k.icon, onClick: k.onClick || (k.href ? () => { location.hash = k.href; } : undefined) })));
}

export function statusChip(ctx, status, opts = {}) {
  if (typeof ctx.ui.statusChip === 'function') return ctx.ui.statusChip(status, opts);
  const T = { overdue: ['Overdue', 'bad'], open: ['Open', 'info'], done: ['Done', 'good'], verified: ['Verified', 'good'], unverified: ['Unverified', 'warn'], missing: ['Missing', 'neutral'] };
  const [l, t] = T[status] || [String(status).replace(/_/g, ' '), 'neutral'];
  return ctx.ui.badge(opts.label || l, t);
}

export function verifiedBadge(ctx, o) {
  if (typeof ctx.ui.verifiedBadge === 'function') return ctx.ui.verifiedBadge(o);
  const { h, ui, fmt } = ctx;
  if (o.state === 'verified') return h('span', { class: 'opk-vb', title: [o.source, o.by].filter(Boolean).join(' · ') || null }, ui.badge('Verified ✓', 'good'), o.date ? h('small', { class: 'opk-muted' }, ` ${fmt.date(o.date)}`) : null);
  return ui.badge(o.state === 'missing' ? 'Missing' : 'Unverified', o.state === 'missing' ? 'neutral' : 'warn');
}

export function contactActions(ctx, phone, email, opts = {}) {
  const { h, ui } = ctx;
  if (typeof ui.contactActions === 'function') return ui.contactActions(phone, email, { compact: true, ...opts });
  return h('span', { class: 'opk-contact' }, phone ? forms.telLink(ctx, phone) : null,
    email ? h('a', { href: `mailto:${email}`, class: 'vx-tel', 'aria-label': `Email ${email}` }, ui.icon('mail', { size: 16 }), h('span', null, phone ? 'Email' : email)) : null,
    !phone && !email ? h('span', { class: 'opk-muted' }, 'No phone') : null);
}

export function confirmDialog(ctx, o) {
  return ctx.ui.confirm({ ...o, tone: o.danger ? 'danger' : (o.tone || 'primary') });
}

/**
 * dataTable — ui.dataTable when available; otherwise ui.table + a pager (+ optional checkbox column).
 * Callers always pass rows for the current page and total + onPage (paging is done by the caller).
 */
export function dataTable(ctx, o) {
  const { h, ui, fmt } = ctx;
  if (typeof ui.dataTable === 'function') {
    // ui.dataTable's update() only takes rows/total/page/sort/loading/error: rebuild it when anything else changes
    // (columns, empty text, row actions, selectable per tab …) so callers can always pass full options.
    const SIMPLE = new Set(['rows', 'total', 'page', 'sort', 'loading', 'error']);
    const host = h('div', { class: 'opk-dtwrap' });
    let opts = { ...o };
    let inner = ui.dataTable(opts);
    host.append(inner);
    host.update = (p = {}) => {
      opts = { ...opts, ...p };
      if (Object.keys(p).some((k) => !SIMPLE.has(k))) { const n = ui.dataTable(opts); inner.replaceWith(n); inner = n; } else inner.update(p);
    };
    return host;
  }
  const st = { ...o };
  const sel = new Set();
  const key = (r) => (st.rowKey ? st.rowKey(r) : r.id);
  const wrap = h('div', { class: 'opk-dt' });
  const draw = () => {
    if (st.loading) { wrap.replaceChildren(ui.skeleton(4)); return; }
    if (st.error) { wrap.replaceChildren(ui.errorCard({ error: st.error, retry: st.onRetry })); return; }
    const rows = st.rows || [];
    const cols = st.columns.map((c) => ({ ...c, sortable: false }));
    if (st.selectable) {
      cols.unshift({ key: '_sel', label: '', sortable: false, render: (r) => {
        const cb = h('input', { type: 'checkbox', class: 'td-check', 'aria-label': 'Select row', checked: sel.has(key(r)) });
        cb.addEventListener('change', () => { if (cb.checked) sel.add(key(r)); else sel.delete(key(r)); st.onSelect?.(rows.filter((x) => sel.has(key(x)))); });
        return cb;
      } });
    }
    if (st.rowActions) {
      cols.push({ key: '_act', label: '', sortable: false, render: (r) => h('div', { class: 'opk-acts' }, st.rowActions(r).filter((a) => a && !a.hidden).map((a) => ui.button({
        label: a.label, icon: a.icon, size: 'sm', tone: a.tone === 'danger' ? 'danger' : (a.tone || 'secondary'), onClick: () => a.onClick(r),
      }))) });
    }
    const empty = st.empty && typeof st.empty === 'object' && !(st.empty instanceof Node) ? ui.emptyState(st.empty) : st.empty;
    wrap.replaceChildren(ui.table({ columns: cols, rows, empty, onRowClick: st.onRowClick }), pager(ctx, st));
  };
  wrap.update = (p) => { if (p && 'rows' in p) sel.clear(); Object.assign(st, p); draw(); };
  draw();
  return wrap;
}

export function pager(ctx, { page = 1, pageSize = 25, total = 0, onPage, label = 'rows' }) {
  const { h, ui, fmt } = ctx;
  if (typeof ui.pagination === 'function') return ui.pagination({ page, pageSize, total, onPage, label });
  if (!onPage || total <= pageSize) return h('span', { hidden: true });
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = (page - 1) * pageSize + 1; const to = Math.min(total, page * pageSize);
  return h('nav', { class: 'opk-pager', 'aria-label': 'Pages' },
    h('span', { class: 'opk-muted' }, `${fmt.num(from)}–${fmt.num(to)} of ${fmt.num(total)} ${label}`),
    ui.button({ label: 'Prev', size: 'sm', disabled: page <= 1, onClick: () => onPage(page - 1) }),
    h('span', { class: 'opk-muted' }, `Page ${page} of ${pages}`),
    ui.button({ label: 'Next', size: 'sm', disabled: page >= pages, onClick: () => onPage(page + 1) }));
}

/** count of overdue open follow-ups in scope (for the section tabs); null when unknown */
export async function overdueCount(ctx) {
  try {
    const r = await getScoped(ctx, '/followups', { status: 'open', due: 'overdue' });
    const rows = Array.isArray(r) ? r : (r?.items || r?.rows || []);
    return scopeRows(rows).length;
  } catch { return null; }
}

/* =====================================================================================================
   Call queue
   ===================================================================================================== */
// [server filter key, chip label]. Keys are the API's (GET /api/calls/queue?filter=); only the wording is ours.
const FILTERS = [
  ['all', 'All colleges'],
  ['pending', 'To call'],
  ['high', 'High priority'],
  ['working', 'Has a working number'],
  ['interested', 'Spoke to them'],
  ['confirmed', 'College agreed'],
  ['invalid', 'Has a bad number'],
];
const EMPTY = {
  all: ['No colleges match', 'Clear the search, or widen the district scope at the top of the page.'],
  working: ['No working numbers yet', 'A number becomes “working” after a logged call where someone answered. Start with “All colleges” and log each call.'],
  high: ['No high-priority colleges here', 'High priority needs many eligible students, a number to call and no exams soon. Add contacts to move colleges up the list.'],
  pending: ['Nothing to call', 'Every college in view has been reached and has no call-back due.'],
  invalid: ['No bad numbers', 'Colleges with a wrong, out-of-service or unreachable number appear here so someone can find a new one.'],
  interested: ['No conversations yet', 'Colleges move here after a call where someone answered.'],
  confirmed: ['No college has agreed yet', 'Tick “The college agreed to take part” when logging a call, or record confirmed enrollments.'],
};
// column key -> server sort and its natural direction
const SORTS = { priority: ['priority', 'desc'], next_action: ['next_action', 'asc'], last_call: ['last_call', 'desc'], name: ['name', 'asc'] };
const PAGE = 25;

let cur = null;
export const handlesScope = true;

export async function render(el, params = {}, ctx) {
  const { h, ui } = ctx;
  const q = { ...getQuery(), ...params };
  cur = {
    el, ctx, seq: 0,
    filter: FILTERS.some(([k]) => k === q.filter) ? q.filter : 'all',
    sort: SORTS[q.sort] ? q.sort : 'priority',
    dir: q.dir === 'asc' || q.dir === 'desc' ? q.dir : null,
    q: q.q || '',
    page: Math.max(1, Number(q.page) || 1),
  };
  ctx.setBreadcrumb?.([{ label: 'Calls & follow-ups', href: '#/calls' }, { label: 'Call queue' }]);
  el.className = 'v-ops v-calls';

  const headHost = h('div');
  const kpis = h('div', { class: 'vcq-kpis', 'aria-live': 'polite' });
  const search = h('input', { type: 'search', class: 'td-input vcq-search', placeholder: 'Search college, town or district', 'aria-label': 'Search colleges', enterkeyhint: 'search', value: cur.q });
  let t;
  search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { cur.q = search.value.trim(); cur.page = 1; sync(); load(); }, 250); });
  const chips = h('div', { class: 'vcq-chips', role: 'toolbar', 'aria-label': 'Show' });
  const note = h('p', { class: 'vcq-note opk-muted', 'aria-live': 'polite' });
  const table = dataTable(ctx, tableOpts([]));
  cur.dom = { headHost, kpis, chips, note, table, search };
  drawHead(null);
  el.replaceChildren(headHost, kpis, h('div', { class: 'vcq-toolbar' }, h('label', { class: 'vcq-searchwrap' }, ui.icon('search', { size: 16 }), search), chips), note, table);
  table.update({ loading: true });

  const onScope = () => { if (!cur || !el.isConnected) return; cur.page = 1; sync(); load(); drawHeadAsync(); };
  addEventListener(SCOPE_EVENT, onScope);
  cur.off = () => removeEventListener(SCOPE_EVENT, onScope);
  drawHeadAsync();
  await load();
}

export function destroy() { try { cur?.off?.(); } catch { /* ignore */ } cur = null; }

function sync() { setQuery(cur.ctx, { filter: cur.filter === 'all' ? null : cur.filter, sort: cur.sort === 'priority' ? null : cur.sort, dir: cur.dir, q: cur.q, page: cur.page > 1 ? cur.page : null }); }

function drawHead(overdue) {
  const { ctx, dom } = cur;
  dom.headHost.replaceChildren(opsHeader(ctx, {
    active: 'calls', counts: { followups: overdue || null },
    // the new shell draws the Call queue | Follow-ups tabs; only older shells need a link here
    actions: typeof ctx.ui.linkTabs === 'function' ? [] : [ctx.ui.button({ label: 'Follow-ups', icon: 'followup', onClick: () => { location.hash = '#/followups'; } })],
  }));
}
async function drawHeadAsync() { const me = cur; const n = await overdueCount(me.ctx); if (cur === me) drawHead(n); }

function tableOpts(rows) {
  const { ctx } = cur;
  const { h, ui, fmt } = ctx;
  return {
    caption: 'Colleges to call',
    columns: [
      { key: 'name', label: 'College', primary: true, priority: 1, minWidth: 340, render: (r) => h('div', { class: 'vcq-name' },
        h('a', { href: r.href || `#/college/${r.college_id}` }, r.short_name || r.name),
        h('span', { class: 'opk-muted vx-small' }, [r.short_name && r.short_name !== r.name ? r.name : null, [r.city_name, r.district_name].filter(Boolean).join(', ')].filter(Boolean).join(' · ')),
        h('span', { class: 'vcq-badges' }, forms.callStatusBadge(ctx, r.call_status), r.op_status !== 'operational' ? ui.statusBadge('op_status', r.op_status) : null,
          r.exam_state === 'in_exams' || r.exam_state === 'exams_soon' ? ui.statusBadge('exam_state', r.exam_state) : null)) },
      { key: 'contact', label: 'Number to call', sortable: false, priority: 1, minWidth: 230, render: (r) => contactCell(r) },
      { key: 'last_call', label: 'Last call', priority: 2, minWidth: 160, render: (r) => (r.last_call ? outcomeText(r.last_call, r.calls_total) : h('span', { class: 'opk-muted' }, 'Not called yet')) },
      { key: 'next_action', label: 'Call back on', priority: 2, minWidth: 150, render: (r) => nextCell(r.next_action) },
      { key: 'priority', label: 'Priority', priority: 3, minWidth: 150, render: (r) => whyPopover(r) },
    ],
    rows,
    rowKey: (r) => r.college_id,
    sort: { key: cur.sort, dir: cur.dir || SORTS[cur.sort][1] },
    onSort: (key, dir) => {
      if (!SORTS[key]) return;
      cur.sort = key; cur.dir = dir && dir !== SORTS[key][1] ? dir : null; cur.page = 1; sync(); load();
    },
    page: cur.page, pageSize: PAGE, total: 0,
    onPage: (p) => { cur.page = p; sync(); drawTable(); cur.el.scrollIntoView?.({ block: 'start' }); },
    rowActions: (r) => [
      { label: 'Log call', icon: 'phone', tone: 'primary', writeOnly: true, onClick: () => forms.logCall(ctx, { college_id: r.college_id, college_label: r.short_name || r.name, onSaved: afterSave }) },
      { label: 'Add contact', icon: 'plus', writeOnly: true, onClick: () => forms.addContact(ctx, { college_id: r.college_id, onSaved: afterSave }) },
    ],
    empty: { title: EMPTY[cur.filter][0], text: EMPTY[cur.filter][1], icon: 'phone' },
    mobile: 'cards',
  };
}

function afterSave() { load({ keep: true }); drawHeadAsync(); }

async function load({ keep } = {}) {
  if (!cur) return;
  const me = cur; const my = ++me.seq;
  const { ctx } = me;
  if (!keep) me.dom.table.update({ loading: true, error: null });
  let q; let td;
  try {
    [q, td] = await Promise.all([
      getScoped(ctx, '/calls/queue', { filter: me.filter, sort: SORTS[me.sort][0], q: me.q || undefined, limit: 1000 }),
      getScoped(ctx, '/target-dashboard', { scope: 'state' }).catch(() => null),
    ]);
  } catch (e) {
    if (cur === me && my === me.seq) me.dom.table.update({ loading: false, error: e, onRetry: () => load(), rows: [] });
    return;
  }
  if (cur !== me || my !== me.seq) return;
  // servers that ignore `districts=`: filter rows here (counts would then cover every district, so they are hidden)
  const before = (q.rows || []).length;
  q.rows = scopeRows(q.rows || []);
  me.exactCounts = q.rows.length === before || Array.isArray(q.districts_filter);
  if (me.dir && me.dir !== SORTS[me.sort][1]) q.rows.reverse();
  me.data = q;
  drawKpis(td);
  drawChips(q.counts);
  drawTable();
}

function drawTable() {
  const { data, dom, ctx } = cur;
  const rows = data?.rows || [];
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  if (cur.page > pages) cur.page = pages;
  const slice = rows.slice((cur.page - 1) * PAGE, cur.page * PAGE);
  dom.table.update({ ...tableOpts(slice), rows: slice, total: rows.length, page: cur.page, loading: false, error: null });
  const sortLabel = { priority: 'highest priority first', next_action: 'by call-back date', last_call: 'by last call', name: 'by name' }[cur.sort];
  dom.note.textContent = rows.length ? `${ctx.fmt.plural(rows.length, 'college')} · ${sortLabel}${cur.q ? ` · matching “${cur.q}”` : ''}` : '';
}

function drawKpis(td) {
  const { ctx, dom } = cur; const { fmt } = ctx;
  if (!td || !td.calls) { dom.kpis.replaceChildren(); return; }
  const c = td.calls; const k = td.contacts || {}; const p = td.pending_calls || {};
  dom.kpis.replaceChildren(kpiRow(ctx, [
    { label: 'Calls today', value: fmt.num(c.today), sub: `${fmt.num(c.last_7d)} in the last 7 days`, icon: 'phone' },
    { label: 'Call-backs due', value: fmt.num(p.callbacks_due), sub: `${fmt.num(p.callbacks_scheduled)} scheduled later`, tone: p.callbacks_due ? 'warn' : undefined, icon: 'clock', href: '#/followups?tab=overdue' },
    { label: 'Colleges not called yet', value: fmt.num(p.never_called), sub: 'operating colleges only', icon: 'college', onClick: () => setFilter('pending') },
    { label: 'Working numbers', value: fmt.num(k.working), sub: `${fmt.num(k.untested)} not tried yet · ${fmt.num((k.non_working || 0) + (k.invalid || 0))} not working`, icon: 'check', tone: k.working ? 'good' : undefined },
  ]));
}

function setFilter(k) { if (cur.filter === k) return; cur.filter = k; cur.page = 1; sync(); load(); }

function drawChips(counts) {
  const { ctx, dom } = cur;
  dom.chips.replaceChildren(...FILTERS.map(([k, l]) => ctx.ui.chip({
    label: cur.exactCounts ? `${l} (${ctx.fmt.num(counts?.[k] ?? 0)})` : l,
    active: cur.filter === k, tone: cur.filter === k ? 'brand' : 'neutral',
    onClick: () => setFilter(k),
  })));
}

function outcomeText(lc, total) {
  const { h, ui, fmt } = cur.ctx;
  const o = forms.OUTCOMES[lc.outcome];
  return h('div', { class: 'vcq-last' }, ui.badge(o?.label || lc.outcome, o?.tone || 'neutral'),
    h('span', { class: 'opk-muted vx-small' }, `${fmt.date(lc.called_at)}${lc.caller ? ` · ${lc.caller}` : ''}${total > 1 ? ` · ${fmt.plural(total, 'call')}` : ''}`));
}

function nextCell(next) {
  const { h, ui, fmt } = cur.ctx;
  if (!next?.due_date) return h('span', { class: 'opk-muted' }, 'No call-back set');
  return h('span', { class: ['vcq-next', next.overdue && 'is-overdue', next.due && !next.overdue && 'is-due'] }, ui.icon('clock', { size: 14 }),
    h('span', null, next.overdue ? 'Overdue · ' : next.due ? 'Today · ' : '', fmt.date(next.due_date)));
}

function contactCell(r) {
  const { ctx } = cur; const { h, fmt, ui } = ctx;
  const k = r.best_contact; const cc = r.contact_counts || {};
  if (!k) return h('span', { class: 'opk-muted vx-small' }, cc.total ? `No working number (${fmt.plural((cc.non_working || 0) + (cc.invalid || 0), 'bad number')})` : 'No contact yet');
  return h('div', { class: 'vcq-contact' },
    h('div', { class: 'vcq-reach' }, k.phone ? forms.telLink(ctx, k.phone) : null,
      k.email ? h('a', { href: `mailto:${k.email}`, class: 'vx-tel', title: k.email, 'aria-label': `Email ${k.email}` }, ui.icon('mail', { size: 16 }), k.phone ? null : h('span', null, k.email)) : null),
    h('span', { class: 'vx-small' }, forms.contactLabel(k), ' ', forms.contactStatusBadge(ctx, k.status), k.basis === 'verified' ? ' ' : null, k.basis === 'verified' ? ui.provenance('verified') : null));
}

function whyPopover(r) {
  const { h, ui } = cur.ctx;
  const p = r.priority;
  if (!p) return h('span', { class: 'opk-muted' }, '—');
  const tone = p.tier === 'high' ? 'brand' : p.tier === 'medium' ? 'info' : 'neutral';
  return h('details', { class: 'vcq-why' },
    h('summary', { 'aria-label': `Priority ${p.score} of 100, ${p.tier}. Show why` }, ui.badge(`${p.tier === 'high' ? 'High' : p.tier === 'medium' ? 'Medium' : 'Low'} · ${p.score}`, tone), h('span', { class: 'vcq-why-q' }, 'Why?')),
    h('div', { class: 'vcq-why-pop', role: 'note' },
      h('strong', null, `Priority ${p.score} / 100`),
      h('ul', null, (p.parts || []).map((x) => h('li', null,
        h('span', { class: 'vcq-why-k' }, x.label),
        h('span', { class: 'vcq-why-pts td-num' }, `${x.points}/${x.max}`),
        h('span', { class: 'vcq-why-d' }, x.detail, x.estimated ? ' ' : null, x.estimated ? ui.provenance('estimated') : null, x.basis === 'pending' ? ' ' : null, x.basis === 'pending' ? ui.provenance('pending') : null)))),
      h('p', { class: 'opk-muted vx-small' }, 'High is 60 or more, medium 40–59. It only decides the order of this list.')));
}
