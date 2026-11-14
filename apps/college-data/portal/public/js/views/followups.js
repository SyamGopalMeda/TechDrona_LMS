// Tech Drona portal — "Calls & follow-ups" section, tab 2: follow-ups. Route: #/followups (?tab=&q=&owner=&issue=&sort=&dir=&page=)
// Respects the global district scope (GET /api/followups?districts=…). Also exports openFollowupForm(),
// the one create/edit follow-up form used everywhere in the app.
import { today, daysUntil } from '../ui/h.js';
import { scopeRows, SCOPE_EVENT } from '../state.js';
import { opsHeader, kpiRow, dataTable, statusChip, getQuery, setQuery, getScoped } from './calls.js';

const DAY = 86400000;
export const ISSUES = {
  ambassador_gap: ['Ambassador gap', 'bad'],
  low_outreach: ['Low outreach', 'warn'],
  low_conversion: ['Low conversion', 'warn'],
  unrealistic_target: ['Target too high', 'info'],
  exams: ['Exams', 'info'],
  data: ['Data check', 'neutral'],
  other: ['Other', 'neutral'],
};
const ISSUE_HELP = {
  ambassador_gap: 'A branch or college has no active ambassador.',
  low_outreach: 'Few students reached recently.',
  low_conversion: 'Students reached, but few enrolled.',
  unrealistic_target: 'The target looks too high for the eligible students.',
  exams: 'Plan around end-semester exams.',
  data: 'Something in the records needs checking.',
  other: '',
};
const SCOPE_LABEL = { college: 'College', branch: 'Branch', person: 'Person' };
const TABS = [['overdue', 'Overdue'], ['today', 'Today'], ['fortnight', 'Next 14 days'], ['open', 'All open'], ['done', 'Done']];

export function addDays(iso, n) {
  const t = Date.parse(String(iso).slice(0, 10) + 'T00:00:00Z');
  return new Date(t + n * DAY).toISOString().slice(0, 10);
}

function arr(x) { return Array.isArray(x) ? x : (x && Array.isArray(x.items) ? x.items : x && Array.isArray(x.rows) ? x.rows : []); }

/** GET a list; when the server pages it ({items,total}), fetch everything in one go (capped). */
async function listAll(get, path, params = {}) {
  const r = await get(path, params);
  if (r && !Array.isArray(r) && Array.isArray(r.items) && Number(r.total) > r.items.length) {
    return arr(await get(path, { ...params, page: 1, page_size: Math.min(Number(r.total), 5000) }));
  }
  return arr(r);
}

const PAGE = 25;
let current = null; // {el, ctx, data, tab, q, owner, issue, sort, dir, page, sel:Set}
export const handlesScope = true;

export async function render(el, params = {}, ctx) {
  const q = { ...getQuery(), ...params };
  current = {
    el, ctx, seq: 0,
    tab: TABS.some(([k]) => k === q.tab) ? q.tab : null,
    q: q.q || '', owner: q.owner || '', issue: ISSUES[q.issue] ? q.issue : '',
    sort: q.sort || 'due_date', dir: q.dir === 'desc' ? 'desc' : 'asc',
    page: Math.max(1, Number(q.page) || 1), sel: new Set(),
  };
  ctx.setBreadcrumb?.([{ label: 'Calls & follow-ups', href: '#/calls' }, { label: 'Follow-ups' }]);
  el.className = 'v-ops v-followups';
  el.replaceChildren(ctx.ui.skeleton(2), ctx.ui.skeleton(4));
  const onScope = () => { if (!current || !el.isConnected) return; current.page = 1; current.sel.clear(); load(); };
  addEventListener(SCOPE_EVENT, onScope);
  current.off = () => removeEventListener(SCOPE_EVENT, onScope);
  await load();
}

export function destroy() { try { current?.off?.(); } catch { /* ignore */ } current = null; }

function syncUrl() {
  const c = current;
  setQuery(c.ctx, { tab: c.tab, q: c.q, owner: c.owner, issue: c.issue, sort: c.sort === 'due_date' ? null : c.sort, dir: c.dir === 'asc' ? null : c.dir, page: c.page > 1 ? c.page : null });
}

async function load() {
  if (!current) return;
  const me = current; const my = ++me.seq;
  const { el, ctx } = me;
  const { ui } = ctx;
  const get = (path, p) => getScoped(ctx, path, p);
  let all, colleges, people, meta;
  try {
    [all, colleges, people, meta] = await Promise.all([
      listAll(get, '/followups'),
      listAll(get, '/colleges').catch(() => []),
      listAll((p, x) => ctx.api.get(p, x), '/people', { page_size: 1000 }).catch(() => []),
      ctx.state?.meta ? Promise.resolve(ctx.state.meta) : ctx.api.get('/meta').catch(() => ({})),
    ]);
  } catch (e) {
    if (current !== me || my !== me.seq) return;
    el.replaceChildren(opsHeader(ctx, { active: 'followups' }), ui.errorCard({ title: 'Could not load follow-ups', error: e, retry: load }));
    return;
  }
  if (current !== me || my !== me.seq) return;
  // old servers ignore districts=: filter here (a follow-up without a district — e.g. a deleted record — stays visible)
  all = scopeRows(all);
  colleges = scopeRows(colleges);
  me.data = buildIndex({ all, colleges, people, meta });
  const ids = new Set(me.data.items.map((r) => r.id));
  for (const id of [...me.sel]) if (!ids.has(id)) me.sel.delete(id);
  if (!me.shell || !me.shell.root.isConnected) buildShell();
  drawBody();
}

function buildIndex({ all, colleges, people, meta }) {
  const colMap = new Map(colleges.map((c) => [String(c.id), c]));
  const peopleMap = new Map(people.map((p) => [String(p.id), p]));
  const districtName = new Map((meta.districts || []).map((d) => [d.id, d.name]));
  const items = all.map((r) => ({ ...r, _scope: scopeInfo(r, colMap, peopleMap), _bucket: bucket(r) }));
  return { items, colleges, people, colMap, peopleMap, districtName, meta };
}

function scopeInfo(r, colMap, peopleMap) {
  const id = String(r.scope_id);
  const col = colMap.get(String(r.college_id ?? ''));
  if (r.scope_type === 'college') {
    const c = colMap.get(id) || col;
    return { label: r.scope_label || c?.short_name || c?.name || id, href: r.href || `#/college/${id}`, college: c };
  }
  if (r.scope_type === 'person') {
    const p = peopleMap.get(id);
    const c = col || colMap.get(String(p?.college_id));
    return { label: r.scope_label || p?.full_name || `Person #${id}`, href: r.href || `#/person/${id}`, college: c };
  }
  return {
    label: r.scope_label || r.branch_name || r.branch_code || `Branch #${id}`,
    href: r.href || (r.college_id ? `#/college/${r.college_id}?tab=branches&branch=${id}` : null),
    college: col,
  };
}

function bucket(r) {
  if (r.status === 'done') return 'done';
  const d = daysUntil(r.due_date);
  if (d === null) return 'open';
  if (d < 0) return 'overdue';
  if (d === 0) return 'today';
  if (d <= 14) return 'fortnight';
  return 'open';
}

function ownerName(r) {
  if (r.owner_name) return r.owner_name;
  const p = current?.data?.peopleMap.get(String(r.owner_person_id));
  return p?.full_name || '';
}

function matches(r) {
  const c = r._scope.college;
  if (current.owner && (ownerName(r) || '__none') !== current.owner) return false;
  if (current.issue && (r.issue || 'other') !== current.issue) return false;
  if (current.q) {
    const hay = [r.title, r.notes, r._scope.label, c?.name, c?.short_name, ownerName(r), ISSUES[r.issue]?.[0]].filter(Boolean).join(' ').toLowerCase();
    if (!current.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
  }
  return true;
}

/* ------------------------------------------------------------------ page shell (built once so inputs keep focus) */

function buildShell() {
  const { el, ctx } = current;
  const { h, ui } = ctx;
  const newBtn = ui.button({ label: 'New follow-up', icon: 'plus', tone: 'primary', onClick: () => openFollowupForm(ctx, { data: current.data, onSaved: load }) });
  if (typeof ui.writeOnly === 'function') ui.writeOnly(newBtn);
  const headHost = h('div');
  const kpis = h('div', { class: 'fu-kpis' });
  const tabsHost = h('div', { class: 'fu-tabbar' });
  const filters = h('div', { class: 'fu-filters' });
  const bulk = h('div', { class: 'fu-bulk', role: 'region', 'aria-label': 'Bulk actions', hidden: true });
  const note = h('p', { class: 'fu-note opk-muted', 'aria-live': 'polite' });
  const table = dataTable(ctx, tableOpts([]));
  const unsched = h('div', { class: 'fu-unsched-host' });
  const root = h('div', { class: 'fu-root' }, headHost, kpis, tabsHost, filters, bulk, note, table, unsched);
  el.replaceChildren(root);
  current.shell = { root, headHost, kpis, tabsHost, filters, bulk, note, table, unsched, newBtn };
  buildFilters();
}

function buildFilters() {
  const { ctx, shell } = current;
  const { h, ui } = ctx;
  const ownerOpts = () => {
    const names = [...new Set(current.data.items.filter((r) => r.status !== 'done').map((r) => ownerName(r)).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    if (current.owner && current.owner !== '__none' && !names.includes(current.owner)) names.push(current.owner);
    return [['__none', 'No owner assigned'], ...names.map((n) => [n, n])];
  };
  const issueOpts = Object.entries(ISSUES).map(([k, [l]]) => [k, l]);
  const onChange = (v) => {
    current.q = (v.q || '').trim(); current.owner = v.owner || ''; current.issue = v.issue || '';
    current.page = 1; current.sel.clear(); syncUrl(); drawBody();
  };
  if (typeof ui.filterBar === 'function') {
    const bar = ui.filterBar({
      search: { key: 'q', placeholder: 'Search title, college, person, notes', value: current.q },
      filters: [
        { key: 'owner', label: 'Owner', type: 'select', options: ownerOpts().map(([value, label]) => ({ value, label })), allLabel: 'Everyone' },
        { key: 'issue', label: 'Issue', type: 'select', options: issueOpts.map(([value, label]) => ({ value, label })), allLabel: 'All issues' },
      ],
      values: { q: current.q, owner: current.owner, issue: current.issue },
      onChange,
    });
    shell.filters.replaceChildren(bar);
    return;
  }
  const search = h('input', { type: 'search', class: 'td-input', placeholder: 'Search title, college, person, notes', 'aria-label': 'Search follow-ups', value: current.q });
  const mk = (label, all, opts, val) => { const s = h('select', { class: 'td-input td-select', 'aria-label': label }, h('option', { value: '' }, all), opts.map(([v, l]) => h('option', { value: v }, l))); s.value = val; return s; };
  const owner = mk('Owner', 'Everyone', ownerOpts(), current.owner);
  const issue = mk('Issue', 'All issues', issueOpts, current.issue);
  const fire = () => onChange({ q: search.value, owner: owner.value, issue: issue.value });
  let t; search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(fire, 250); });
  owner.addEventListener('change', fire); issue.addEventListener('change', fire);
  shell.filters.replaceChildren(h('div', { class: 'opk-filterbar' }, h('label', { class: 'opk-grow' }, search), owner, issue));
}

function clearFilters() {
  if (!current) return;
  current.q = ''; current.owner = ''; current.issue = '';
  current.page = 1; current.sel.clear();
  buildFilters(); syncUrl(); drawBody();
}

function lists() {
  const items = current.data.items.filter(matches);
  const open = items.filter((r) => r.status !== 'done');
  return {
    overdue: open.filter((r) => r._bucket === 'overdue'),
    today: open.filter((r) => r._bucket === 'today'),
    fortnight: open.filter((r) => r._bucket === 'today' || r._bucket === 'fortnight'),
    open,
    done: items.filter((r) => r.status === 'done'),
  };
}

function drawBody() {
  if (!current?.shell) return;
  const { ctx, shell } = current;
  const { ui, fmt, h } = ctx;
  const L = lists();
  current.lists = L;
  if (!current.tab) current.tab = L.overdue.length ? 'overdue' : L.today.length ? 'today' : L.fortnight.length ? 'fortnight' : 'open';
  const weekAgo = addDays(today(), -6);
  const doneThisWeek = L.done.filter((r) => r.done_at && String(r.done_at).slice(0, 10) >= weekAgo).length;

  shell.headHost.replaceChildren(opsHeader(ctx, { active: 'followups', counts: { followups: L.overdue.length || null }, actions: [shell.newBtn] }));
  shell.kpis.replaceChildren(kpiRow(ctx, [
    { label: 'Overdue', value: fmt.num(L.overdue.length), tone: L.overdue.length ? 'bad' : 'good', icon: 'warn', sub: L.overdue.length ? 'past their due date' : 'all on schedule', onClick: () => setTab('overdue') },
    { label: 'Due today', value: fmt.num(L.today.length), tone: L.today.length ? 'info' : undefined, icon: 'clock', sub: fmt.date(today()), onClick: () => setTab('today') },
    { label: 'Next 14 days', value: fmt.num(L.fortnight.length), icon: 'followup', sub: `until ${fmt.date(addDays(today(), 14))}`, onClick: () => setTab('fortnight') },
    { label: 'Done this week', value: fmt.num(doneThisWeek), tone: 'good', icon: 'check', sub: 'last 7 days', onClick: () => setTab('done') },
  ]));

  const opts = TABS.map(([id, label]) => ({ value: id, label, count: L[id].length }));
  if (typeof ui.segmented === 'function') {
    shell.tabsHost.replaceChildren(ui.segmented({ options: opts, value: current.tab, onChange: setTab, ariaLabel: 'Which follow-ups' }));
  } else {
    shell.tabsHost.replaceChildren(h('div', { class: 'fu-seg', role: 'group', 'aria-label': 'Which follow-ups' }, opts.map((o) => ui.chip({
      label: `${o.label} (${fmt.num(o.count)})`, active: current.tab === o.value, tone: current.tab === o.value ? (o.value === 'overdue' && o.count ? 'bad' : 'brand') : 'neutral', onClick: () => setTab(o.value),
    }))));
  }
  drawTable();
  drawBulk();
  shell.unsched.replaceChildren(renderUnscheduled());
}

function setTab(id) {
  if (!current) return;
  current.tab = id; current.page = 1; current.sel.clear();
  syncUrl(); drawBody();
}

/* ------------------------------------------------------------------ table */

const SORTERS = {
  due_date: (r) => (current.tab === 'done' ? String(r.done_at || '') : String(r.due_date || '9999')),
  title: (r) => String(r.title || '').toLowerCase(),
  about: (r) => String(r._scope.label || '').toLowerCase(),
  issue: (r) => ISSUES[r.issue]?.[0] || 'Other',
  owner: (r) => (ownerName(r) || '~').toLowerCase(),
  last_contact: (r) => String(r.last_contact || ''),
};

function sortedRows() {
  const rows = [...(current.lists[current.tab] || [])];
  const key = SORTERS[current.sort] ? current.sort : 'due_date';
  const f = SORTERS[key];
  // Done tab: newest first by default
  const dir = (key === 'due_date' && current.tab === 'done' ? -1 : 1) * (current.dir === 'desc' ? -1 : 1);
  return rows.sort((a, b) => (f(a) < f(b) ? -1 : f(a) > f(b) ? 1 : 0) * dir || a.id - b.id);
}

function tableOpts(rows) {
  const { ctx } = current;
  const { h, ui, fmt } = ctx;
  const done = current.tab === 'done';
  const filtered = current.q || current.owner || current.issue;
  const msgs = filtered ? ['No follow-ups match these filters', 'Clear the search, owner or issue filter to see more.'] : {
    overdue: ['Nothing overdue', 'Every open follow-up is on schedule.'],
    today: ['Nothing due today', 'Check “Next 14 days”, or add a new follow-up.'],
    fortnight: ['Nothing due in the next 14 days', 'Schedule check-ins for targeted colleges from the list below.'],
    open: ['No open follow-ups', 'Use “New follow-up”, or log a call with a call-back date.'],
    done: ['Nothing completed yet', 'Items you mark done appear here.'],
  }[current.tab || 'open'];
  return {
    caption: 'Follow-ups',
    columns: [
      { key: 'due_date', label: done ? 'Done on' : 'Due', priority: 1, minWidth: 130, render: dueCell },
      { key: 'title', label: 'What', primary: true, priority: 1, minWidth: 300, render: (r) => h('div', { class: 'fu-what' },
        h('strong', null, r.title || ISSUES[r.issue]?.[0] || 'Follow-up'),
        r.notes ? h('span', { class: 'fu-notes opk-muted', title: r.notes }, r.notes.length > 110 ? r.notes.slice(0, 110) + '…' : r.notes) : null,
        r.is_demo ? ui.badge('DEMO', 'bad') : null) },
      { key: 'about', label: 'About', priority: 2, minWidth: 200, render: (r) => h('div', { class: 'fu-about-cell' },
        r._scope.href ? h('a', { href: r._scope.href }, r._scope.label) : h('span', null, r._scope.label),
        h('span', { class: 'opk-muted vx-small' }, SCOPE_LABEL[r.scope_type] || r.scope_type,
          r.scope_type !== 'college' && r._scope.college ? ` · ${r._scope.college.short_name || r._scope.college.name}` : '',
          r.district_id && current.data.districtName.get(r.district_id) ? ` · ${current.data.districtName.get(r.district_id)}` : '')) },
      { key: 'issue', label: 'Issue', priority: 3, minWidth: 130, render: (r) => { const [l, t] = ISSUES[r.issue] || [r.issue || 'Other', 'neutral']; return ui.badge(l, t); } },
      { key: 'owner', label: 'Owner', priority: 2, minWidth: 140, render: (r) => ownerName(r) || h('em', { class: 'opk-muted' }, 'No owner') },
      { key: 'last_contact', label: 'Last contact', priority: 3, minWidth: 140, hideOnPhone: true, render: (r) => (r.last_contact ? h('span', null, fmt.date(r.last_contact), h('small', { class: 'opk-muted' }, ` ${fmt.days(r.last_contact)}`)) : h('span', { class: 'opk-muted' }, 'Not recorded')) },
    ],
    rows,
    rowKey: (r) => r.id,
    sort: { key: current.sort, dir: current.dir },
    onSort: (key, dir) => { current.sort = key; current.dir = dir === 'desc' ? 'desc' : 'asc'; current.page = 1; syncUrl(); drawTable(); },
    page: current.page, pageSize: PAGE, total: 0,
    onPage: (p) => { current.page = p; syncUrl(); drawTable(); },
    selectable: !done,
    onSelect: (sel) => { current.sel = new Set(sel.map((r) => r.id)); drawBulk(); },
    rowActions: (r) => (r.status === 'done'
      ? [{ label: 'Reopen', icon: 'refresh', writeOnly: true, onClick: () => reopen(r) }, { label: 'Edit', icon: 'edit', writeOnly: true, onClick: () => openFollowupForm(ctx, { data: current.data, row: r, onSaved: load }) }]
      : [{ label: 'Done', icon: 'check', tone: 'primary', writeOnly: true, onClick: () => markDone(r) },
        { label: 'Snooze', icon: 'clock', writeOnly: true, onClick: () => reschedule(r) }]),
    // the whole row opens the edit form (title, due date, owner, notes, delete)
    onRowClick: (r) => openFollowupForm(ctx, { data: current.data, row: r, onSaved: load }),
    empty: { title: msgs[0], text: msgs[1], icon: filtered ? 'filter' : current.tab === 'overdue' ? 'check' : 'followup', action: filtered ? { label: 'Clear filters', icon: 'close', tone: 'secondary', onClick: clearFilters } : undefined },
    mobile: 'cards',
  };
}

function dueCell(r) {
  const { h, fmt } = current.ctx;
  if (r.status === 'done') return h('span', null, fmt.date(r.done_at));
  if (!r.due_date) return h('span', { class: 'opk-muted' }, 'No date');
  const b = r._bucket;
  return h('div', { class: ['fu-due', `is-${b}`] },
    b === 'overdue' ? statusChip(current.ctx, 'overdue', { label: `Overdue ${-daysUntil(r.due_date)}d`, size: 'sm' }) : null,
    h('span', { class: 'fu-due__d' }, fmt.date(r.due_date)),
    b !== 'overdue' ? h('small', { class: b === 'today' ? 'fu-today' : 'opk-muted' }, fmt.days(r.due_date)) : null);
}

function drawTable() {
  const { shell, ctx } = current;
  const rows = sortedRows();
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  if (current.page > pages) current.page = pages;
  const slice = rows.slice((current.page - 1) * PAGE, current.page * PAGE);
  shell.table.update({ ...tableOpts(slice), rows: slice, total: rows.length, page: current.page, loading: false, error: null });
  const label = TABS.find(([k]) => k === current.tab)?.[1] || '';
  shell.note.textContent = rows.length ? `${ctx.fmt.plural(rows.length, 'follow-up')} · ${label.toLowerCase()}` : '';
}

/* ------------------------------------------------------------------ bulk actions */

function drawBulk() {
  if (!current?.shell) return;
  const { ctx, shell } = current;
  const { h, ui, fmt } = ctx;
  const ids = [...current.sel];
  shell.bulk.hidden = !ids.length;
  if (!ids.length) { shell.bulk.replaceChildren(); return; }
  shell.bulk.replaceChildren(
    h('strong', { class: 'fu-bulk-n' }, `${fmt.num(ids.length)} selected`),
    h('div', { class: 'fu-bulk-actions' },
      ui.button({ label: 'Mark done', icon: 'check', tone: 'primary', size: 'sm', onClick: () => bulkDone(ids) }),
      ui.button({ label: 'Snooze…', icon: 'clock', size: 'sm', onClick: () => bulkSnooze(ids) }),
      ui.button({ label: 'Clear selection', tone: 'ghost', size: 'sm', onClick: () => { current.sel.clear(); drawTable(); drawBulk(); } })));
}

async function runBulk(ids, body, verb) {
  const { ctx } = current;
  const res = await Promise.allSettled(ids.map((id) => ctx.api.patch(`/followups/${id}`, typeof body === 'function' ? body(id) : body)));
  const bad = res.filter((x) => x.status === 'rejected');
  const ok = res.length - bad.length;
  if (ok) ctx.ui.toast(`${ctx.fmt.num(ok)} follow-up${ok === 1 ? '' : 's'} ${verb}`, 'good');
  if (bad.length) ctx.ui.toast(`${bad.length} could not be updated: ${bad[0].reason?.message || 'error'}`, 'bad');
  current?.sel.clear();
  await load();
}

async function bulkDone(ids) {
  const { ctx } = current;
  if (typeof ctx.ensureUser === 'function' && !ctx.api.user) { try { await ctx.ensureUser(); } catch { return; } }
  const ok = await ctx.ui.confirm({ title: `Mark ${ids.length} follow-up${ids.length === 1 ? '' : 's'} done?`, text: 'Today is recorded as the last contact date. No next follow-ups are scheduled — use “Done” on a single item to schedule the next step.', confirmLabel: 'Mark done', tone: 'primary' });
  if (!ok) return;
  await runBulk(ids, { status: 'done', last_contact: today() }, 'marked done');
}

function bulkSnooze(ids) {
  const { ctx } = current;
  const { h } = ctx;
  const date = h('input', { type: 'date', class: 'td-input', required: true, min: today(), value: addDays(today(), 7) });
  formModal(ctx, {
    title: `Snooze ${ids.length} follow-up${ids.length === 1 ? '' : 's'}`,
    fields: [fieldEl(h, { label: 'New due date', input: date, name: 'due_date', required: true }), quickDates(h, date)],
    saveLabel: 'Snooze',
    onSave: async () => {
      if (!date.value) throw fieldError({ due_date: 'Pick a date.' });
      if (date.value < today()) throw fieldError({ due_date: 'Pick today or a later date.' });
      await runBulk(ids, { due_date: date.value }, `moved to ${ctx.fmt.date(date.value)}`);
    },
  });
}

/* ------------------------------------------------------------------ targeted colleges (in scope) with nothing scheduled */

function renderUnscheduled() {
  const { ctx, data } = current;
  const { h, ui } = ctx;
  const openFor = new Set(data.items.filter((r) => r.status !== 'done' && r.college_id).map((r) => String(r.college_id)));
  const list = data.colleges.filter((c) => c.targeted && !openFor.has(String(c.id)) && (c.next_followup === null || c.next_followup === undefined))
    .sort((a, b) => (data.districtName.get(a.district_id) || '').localeCompare(data.districtName.get(b.district_id) || '') || String(a.name).localeCompare(b.name));
  const LIMIT = 8;
  const ul = h('ul', { class: 'fu-unsched' });
  const row = (c) => h('li', { class: 'fu-unsched-row' },
    h('div', { class: 'fu-unsched-name' }, h('a', { href: `#/college/${c.id}` }, c.short_name || c.name),
      h('span', { class: 'opk-muted' }, data.districtName.get(c.district_id) || c.district_id || '')),
    ui.button({ label: 'Schedule', icon: 'plus', size: 'sm', onClick: () => openFollowupForm(ctx, { data, preset: { scope_type: 'college', scope_id: c.id }, lockScope: true, scopeLabel: c.short_name || c.name, onSaved: load }) }));
  const fill = (n) => ul.replaceChildren(...list.slice(0, n).map(row));
  fill(LIMIT);
  const more = list.length > LIMIT ? ui.button({ label: `Show all ${list.length}`, tone: 'ghost', size: 'sm', onClick: () => { fill(list.length); more.remove(); } }) : null;
  const body = list.length
    ? h('div', null, ul, more)
    : ui.emptyState({ icon: 'check', title: 'Every targeted college has a follow-up', text: 'Targeted colleges in these districts without an open follow-up will show up here.' });
  return ui.section({ title: `Targeted colleges with nothing scheduled (${list.length})`, sub: 'In the selected districts. Plan the next check-in so no targeted college goes quiet.', body });
}

/* ------------------------------------------------------------------ modal form plumbing (td-form look, inline errors) */

function fieldError(fields) {
  const e = new Error('Please fix the highlighted fields.');
  e.status = 400;
  e.fields = fields;
  return e;
}

let uidN = 0;
function fieldEl(h, { label, input, help, name, required, full }) {
  const id = `fu-f${++uidN}`;
  const ctrl = input;
  if (ctrl.matches?.('input,select,textarea')) { ctrl.id = id; if (name) ctrl.name = name; if (required) ctrl.setAttribute('aria-required', 'true'); }
  const err = h('div', { class: 'td-field__error', id: `${id}-err`, 'aria-live': 'polite' });
  const helpEl = help ? h('div', { class: 'td-field__help', id: `${id}-help` }, help) : null;
  if (ctrl.setAttribute) ctrl.setAttribute('aria-describedby', [helpEl && `${id}-help`, `${id}-err`].filter(Boolean).join(' '));
  const wrap = h('div', { class: ['td-field', full && 'td-field--full'], dataset: { field: name || '' } },
    h('label', { class: 'td-field__label', for: id }, label, required ? h('span', { class: 'td-field__req', 'aria-hidden': 'true' }, ' *') : null),
    ctrl, helpEl, err);
  wrap._err = err;
  wrap._ctrl = ctrl;
  return wrap;
}

/** Back-compat helper (older callers): label + input. */
export function field(h, label, input, help) { return fieldEl(h, { label, input, help }); }

function quickDates(h, input, list = [['Tomorrow', 1], ['+3 days', 3], ['Next week', 7], ['+2 weeks', 14]]) {
  return h('div', { class: 'fu-quick td-field--full', role: 'group', 'aria-label': 'Quick dates' }, list.map(([l, n]) =>
    h('button', { type: 'button', class: 'td-btn td-btn--secondary td-btn--sm', onClick: () => { input.value = addDays(today(), n); input.dispatchEvent(new Event('input')); } }, l)));
}

/**
 * Modal with a td-form. onSave(form) may throw an Error with .fields ({name: message}) — shown under the matching inputs;
 * anything unmatched (and non-field errors) is shown at the top of the form.
 */
function formModal(ctx, { title, intro, fields, saveLabel = 'Save', onSave, extra, wide }) {
  const { h, ui } = ctx;
  const formErr = h('div', { class: 'td-form__error', role: 'alert', hidden: true });
  const save = ui.button({ label: saveLabel, tone: 'primary', type: 'submit' });
  let m;
  const grid = h('div', { class: 'td-form__grid' }, fields);
  // extra (e.g. Delete) goes above the Cancel / Save row: that row is the last child so it can stay sticky at the bottom of the dialog
  const formEl = h('form', { class: 'td-form fu-form', novalidate: true }, intro || null, formErr, grid, extra || null,
    h('div', { class: 'td-form__foot' }, ui.button({ label: 'Cancel', tone: 'ghost', onClick: () => m?.close() }), save));
  const wraps = () => [...grid.querySelectorAll('.td-field')].filter((w) => w._err);
  const setErr = (name, msg) => {
    const w = wraps().find((x) => x.dataset.field === name);
    if (!w) return false;
    w._err.textContent = msg || '';
    w.classList.toggle('has-error', !!msg);
    w._ctrl?.setAttribute?.('aria-invalid', msg ? 'true' : 'false');
    return true;
  };
  formEl.setErrors = (map) => Object.entries(map || {}).forEach(([k, v]) => setErr(k, v));
  formEl.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (save.disabled) return;
    wraps().forEach((w) => setErr(w.dataset.field, ''));
    formErr.hidden = true;
    save.disabled = true;
    save.classList.add('is-busy');
    try {
      await onSave(formEl);
      m?.close();
    } catch (ex) {
      const fe = ex && ex.fields && typeof ex.fields === 'object' ? ex.fields : {};
      let first = null;
      const unmatched = [];
      for (const [k, v] of Object.entries(fe)) { if (setErr(k, String(v))) first = first || k; else unmatched.push(String(v)); }
      if (!first || unmatched.length) { formErr.textContent = first ? unmatched.join(' ') : (ex.message || 'Could not save. Please try again.'); formErr.hidden = false; }
      const target = first ? wraps().find((w) => w.dataset.field === first)?._ctrl : null;
      (target && target.focus ? target : formErr).focus?.();
      if (ex && ex.status !== 400 && !ex.cancelled) ui.toast(ex.message || 'Could not save', 'bad');
    } finally {
      save.disabled = false;
      save.classList.remove('is-busy');
    }
  });
  m = ui.modal({ title, body: formEl, actions: [], wide });
  return m;
}

/* ------------------------------------------------------------------ done / reopen / snooze */

async function markDone(r) {
  const { ctx } = current;
  const { h, api, ui, fmt } = ctx;
  const note = h('textarea', { class: 'td-input', rows: 3, placeholder: 'What happened? (optional)' });
  const next = h('input', { type: 'checkbox', class: 'td-check', checked: true });
  const nextDate = h('input', { type: 'date', class: 'td-input', min: today(), value: addDays(today(), 7) });
  const dateWrap = fieldEl(h, { label: 'Next follow-up on', input: nextDate, name: 'next_date' });
  const quick = quickDates(h, nextDate, [['+3 days', 3], ['+1 week', 7], ['+2 weeks', 14]]);
  next.addEventListener('change', () => { dateWrap.hidden = !next.checked; quick.hidden = !next.checked; });
  formModal(ctx, {
    title: 'Mark follow-up done',
    intro: h('p', { class: 'fu-modal-ctx' }, h('strong', null, r.title || 'Follow-up'), ` — ${r._scope.label}`),
    fields: [
      fieldEl(h, { label: 'Outcome', input: note, name: 'note', full: true, help: 'Added to the notes with today\'s date.' }),
      h('label', { class: 'td-field td-field--full fu-checkrow' }, next, h('span', null, 'Schedule the next follow-up (same owner and issue)')),
      dateWrap, quick,
    ],
    saveLabel: 'Mark done',
    onSave: async () => {
      if (next.checked && !nextDate.value) throw fieldError({ next_date: 'Pick a date, or untick "Schedule the next follow-up".' });
      if (next.checked && nextDate.value < today()) throw fieldError({ next_date: 'The next follow-up cannot be in the past.' });
      const stamp = today();
      const extra = note.value.trim();
      await api.patch(`/followups/${r.id}`, {
        status: 'done', last_contact: stamp,
        notes: extra ? [r.notes, `[${stamp}] ${extra}`].filter(Boolean).join('\n') : r.notes,
      });
      if (next.checked && nextDate.value) {
        await api.post('/followups', {
          scope_type: r.scope_type, scope_id: String(r.scope_id), owner_person_id: r.owner_person_id ?? null, owner_name: r.owner_name ?? null,
          issue: r.issue || 'other', title: r.title || 'Follow-up', due_date: nextDate.value, last_contact: stamp, status: 'open',
          notes: extra ? `Previous: ${extra}` : null,
        });
      }
      ui.toast(next.checked && nextDate.value ? `Done — next follow-up on ${fmt.date(nextDate.value)}` : 'Marked done', 'good');
      current?.sel.delete(r.id);
      load();
    },
  });
}

async function reopen(r) {
  const { ctx } = current;
  try {
    await ctx.api.patch(`/followups/${r.id}`, { status: 'open' });
    ctx.ui.toast('Follow-up reopened', 'good');
    load();
  } catch (e) { ctx.ui.toast(e.message, 'bad'); }
}

function reschedule(r) {
  const { ctx } = current;
  const { h, api, ui, fmt } = ctx;
  const date = h('input', { type: 'date', class: 'td-input', required: true, min: today(), value: r.due_date && daysUntil(r.due_date) >= 0 ? addDays(r.due_date, 1) : addDays(today(), 1) });
  const why = h('input', { type: 'text', class: 'td-input', placeholder: 'e.g. Principal on leave until Monday', maxlength: 300 });
  formModal(ctx, {
    title: 'Snooze follow-up',
    intro: h('p', { class: 'fu-modal-ctx' }, h('strong', null, r.title || 'Follow-up'), ` — ${r._scope.label}`, r.due_date ? ` · currently due ${fmt.date(r.due_date)}` : ''),
    fields: [fieldEl(h, { label: 'New due date', input: date, name: 'due_date', required: true }), quickDates(h, date),
      fieldEl(h, { label: 'Reason', input: why, name: 'reason', full: true, help: 'Optional. Saved in the notes.' })],
    saveLabel: 'Snooze',
    onSave: async () => {
      if (!date.value) throw fieldError({ due_date: 'Pick a date.' });
      if (date.value < today()) throw fieldError({ due_date: 'Pick today or a later date.' });
      const body = { due_date: date.value };
      if (why.value.trim()) body.notes = [r.notes, `[${today()}] Snoozed to ${date.value}: ${why.value.trim()}`].filter(Boolean).join('\n');
      await api.patch(`/followups/${r.id}`, body);
      ui.toast(`Snoozed to ${fmt.date(date.value)}`, 'good');
      load();
    },
  });
}

/* ------------------------------------------------------------------ create / edit form (shared) */

/**
 * Create / edit follow-up modal, used by the Follow-ups page and (via forms.addFollowup) by college, branch and person pages.
 * opts: {data?: {colleges, people}, row?, preset?: {scope_type, scope_id, college_id, issue, title}, lockScope?, scopeLabel?, onSaved?}
 */
export async function openFollowupForm(ctx, opts = {}) {
  const { h, api, ui, fmt } = ctx;
  if (typeof ctx.ensureUser === 'function' && !api.user) { try { await ctx.ensureUser(); } catch { return null; } }
  const row = opts.row || null;
  let colleges = opts.data?.colleges;
  let people = opts.data?.people;
  if (!colleges || !people) {
    [colleges, people] = await Promise.all([
      colleges ? colleges : listAll((p, x) => api.get(p, x), '/colleges').catch(() => []),
      people ? people : listAll((p, x) => api.get(p, x), '/people', { page_size: 1000 }).catch(() => []),
    ]);
  }
  const preset = Object.fromEntries(Object.entries(opts.preset || {}).filter(([, v]) => v !== undefined && v !== null));
  const init = { scope_type: 'college', issue: 'other', due_date: addDays(today(), 3), ...preset, ...(row || {}) };
  const lock = !!opts.lockScope && !row;

  const mkSel = (options, value) => {
    const s = h('select', { class: 'td-input td-select' }, options.map(([v, l]) => h('option', { value: v }, l)));
    s.value = value ?? '';
    return s;
  };
  const scopeType = mkSel([['college', 'A college'], ['branch', 'A branch of a college'], ['person', 'A team member']], init.scope_type);
  const sortedCols = [...colleges].sort((a, b) => (b.targeted ? 1 : 0) - (a.targeted ? 1 : 0) || String(a.short_name || a.name).localeCompare(b.short_name || b.name));
  let initCollege = init.scope_type === 'college' ? init.scope_id : (init.college_id || '');
  if (init.scope_type === 'person' && !initCollege) initCollege = people.find((p) => String(p.id) === String(init.scope_id))?.college_id || '';
  const college = mkSel([['', 'Choose a college…'], ...sortedCols.map((c) => [c.id, `${c.short_name || c.name}${c.targeted ? '' : ' (not targeted)'}`])], initCollege);
  const branch = mkSel([['', 'Choose a college first']], '');
  const peopleSorted = people.slice().sort((a, b) => a.full_name.localeCompare(b.full_name));
  const person = mkSel([['', 'Choose a person…'], ...peopleSorted.map((p) => [p.id, `${p.full_name}${p.college_short_name || p.college_name ? ' — ' + (p.college_short_name || p.college_name) : ''}`])], init.scope_type === 'person' ? String(init.scope_id) : '');
  const scopeWrap = fieldEl(h, { label: 'This follow-up is about', input: scopeType, name: 'scope_type', required: true });
  const collegeWrap = fieldEl(h, { label: 'College', input: college, name: 'college', required: true });
  const branchWrap = fieldEl(h, { label: 'Branch', input: branch, name: 'branch', required: true });
  const personWrap = fieldEl(h, { label: 'Person', input: person, name: 'person', required: true });

  async function loadBranches() {
    branch.replaceChildren(h('option', { value: '' }, college.value ? 'Loading branches…' : 'Choose a college first'));
    if (!college.value) return;
    try {
      const d = await api.get(`/colleges/${college.value}`);
      const bs = (d.branches || []).slice().sort((a, b) => (b.is_relevant ? 1 : 0) - (a.is_relevant ? 1 : 0) || String(a.code).localeCompare(b.code));
      branch.replaceChildren(h('option', { value: '' }, bs.length ? 'Choose a branch…' : 'No branches recorded for this college'),
        ...bs.map((b) => h('option', { value: b.id }, `${b.code ? b.code + ' — ' : ''}${b.name}`)));
      if (init.scope_type === 'branch') branch.value = String(init.scope_id ?? '');
    } catch { branch.replaceChildren(h('option', { value: '' }, 'Could not load branches')); }
  }
  function syncScope() {
    const t = scopeType.value;
    collegeWrap.hidden = t === 'person';
    branchWrap.hidden = t !== 'branch';
    personWrap.hidden = t !== 'person';
    if (t === 'branch') loadBranches();
  }
  scopeType.addEventListener('change', syncScope);
  college.addEventListener('change', () => { if (scopeType.value === 'branch') loadBranches(); });

  const issue = mkSel(Object.entries(ISSUES).map(([k, [l]]) => [k, l]), init.issue || 'other');
  const issueWrap = fieldEl(h, { label: 'Issue', input: issue, name: 'issue', help: ISSUE_HELP[init.issue || 'other'] || ' ' });
  issue.addEventListener('change', () => { const hp = issueWrap.querySelector('.td-field__help'); if (hp) hp.textContent = ISSUE_HELP[issue.value] || ' '; });
  const title = h('input', { type: 'text', class: 'td-input', value: init.title || '', placeholder: 'e.g. Call the principal about a seminar slot', maxlength: 300 });
  const listId = 'fu-owner-list-' + Math.random().toString(36).slice(2, 7);
  const ownerInit = init.owner_name || (people.find((p) => String(p.id) === String(init.owner_person_id))?.full_name) || (row ? '' : (api.user || ''));
  const owner = h('input', { type: 'text', class: 'td-input', list: listId, value: ownerInit, placeholder: 'Type a name', autocomplete: 'off' });
  const scopeCollege = () => (scopeType.value === 'person' ? people.find((p) => String(p.id) === person.value)?.college_id : college.value);
  const ownerList = h('datalist', { id: listId });
  const fillOwnerList = () => {
    const cid = scopeCollege();
    const near = cid ? peopleSorted.filter((p) => p.college_id === cid && p.status !== 'inactive') : [];
    const rest = peopleSorted.filter((p) => !near.includes(p) && p.status !== 'inactive');
    ownerList.replaceChildren(...[...near, ...rest].map((p) => h('option', { value: p.full_name }, `${ROLE_SHORT[p.role] || ''}${p.college_short_name ? ' · ' + p.college_short_name : ''}`)));
  };
  fillOwnerList();
  college.addEventListener('change', fillOwnerList);
  person.addEventListener('change', fillOwnerList);
  const due = h('input', { type: 'date', class: 'td-input', value: init.due_date || '' });
  if (!row) due.min = today();
  const last = h('input', { type: 'date', class: 'td-input', max: today(), value: init.last_contact || '' });
  const notes = h('textarea', { class: 'td-input', rows: 3, placeholder: 'Context the owner needs' }, init.notes || '');

  const lockedLabel = opts.scopeLabel
    || (init.scope_type === 'college' ? (colleges.find((c) => String(c.id) === String(init.scope_id))?.short_name || colleges.find((c) => String(c.id) === String(init.scope_id))?.name)
      : init.scope_type === 'person' ? people.find((p) => String(p.id) === String(init.scope_id))?.full_name : null)
    || `${SCOPE_LABEL[init.scope_type] || init.scope_type} ${init.scope_id}`;
  const aboutFields = lock
    ? [h('div', { class: 'td-field td-field--full fu-about' }, h('span', { class: 'td-field__label' }, 'About'),
      h('div', { class: 'fu-about-val' }, h('span', { class: 'fu-chip' }, SCOPE_LABEL[init.scope_type] || init.scope_type), ' ', h('strong', null, lockedLabel)))]
    : [scopeWrap, collegeWrap, branchWrap, personWrap];

  let m = null;
  let extra = null;
  if (row) {
    extra = h('div', { class: 'vf-danger fu-danger' },
      h('div', null, h('strong', null, 'Delete this follow-up'), h('p', null, 'Use this for mistakes. To finish a follow-up, mark it done instead so the history is kept.')),
      ui.button({ label: 'Delete', icon: 'trash', tone: 'danger', size: 'sm', onClick: async () => {
        const ok = await ui.confirm({ title: 'Delete follow-up?', text: `"${row.title || 'Follow-up'}" will be removed permanently.`, confirmLabel: 'Delete' });
        if (!ok) return;
        try {
          await api.del(`/followups/${row.id}`);
          ui.toast('Follow-up deleted', 'good');
          m?.close();
          if (opts.onSaved) opts.onSaved(); else ctx.refresh?.();
        } catch (e) { ui.toast(e.message, 'bad'); }
      } }));
  }

  m = formModal(ctx, {
    title: row ? 'Edit follow-up' : (lock && opts.scopeLabel ? `New follow-up — ${opts.scopeLabel}` : 'New follow-up'),
    fields: [
      fieldEl(h, { label: 'What needs to happen?', input: title, name: 'title', required: true, full: true }),
      ...aboutFields,
      issueWrap,
      fieldEl(h, { label: 'Due date', input: due, name: 'due_date', required: true }),
      quickDates(h, due),
      fieldEl(h, { label: 'Owner', input: h('div', null, owner, ownerList), name: 'owner_name', help: 'Who will do it. Pick a team member or type any name.' }),
      fieldEl(h, { label: 'Last contacted on', input: last, name: 'last_contact', help: 'When did we last speak to them?' }),
      fieldEl(h, { label: 'Notes', input: notes, name: 'notes', full: true }),
    ],
    extra,
    saveLabel: row ? 'Save changes' : 'Add follow-up',
    onSave: async () => {
      const t = lock ? init.scope_type : scopeType.value;
      const scope_id = lock ? String(init.scope_id) : t === 'college' ? college.value : t === 'branch' ? branch.value : person.value;
      const errs = {};
      if (!title.value.trim()) errs.title = 'Describe what needs to happen.';
      if (!scope_id) errs[t === 'college' ? 'college' : t] = `Choose the ${t === 'person' ? 'person' : t}.`;
      if (t === 'branch' && !college.value) errs.college = 'Choose the college first.';
      if (!due.value) errs.due_date = 'Set a due date.';
      else if (!row && due.value < today()) errs.due_date = 'The due date cannot be in the past.';
      if (last.value && last.value > today()) errs.last_contact = 'Cannot be in the future.';
      if (Object.keys(errs).length) throw fieldError(errs);
      const match = people.find((p) => p.full_name === owner.value.trim());
      const body = {
        scope_type: t, scope_id: String(scope_id),
        issue: issue.value, title: title.value.trim(), owner_name: owner.value.trim() || null,
        owner_person_id: match ? match.id : null, due_date: due.value, last_contact: last.value || null, notes: notes.value.trim() || null,
      };
      try {
        if (row) await api.patch(`/followups/${row.id}`, body);
        else await api.post('/followups', { ...body, status: 'open' });
      } catch (e) {
        // map server field names onto this form's inputs
        if (e && e.fields) {
          const map = { scope_id: t === 'college' ? 'college' : t, owner_person_id: 'owner_name' };
          e.fields = Object.fromEntries(Object.entries(e.fields).map(([k, v]) => [map[k] || k, v]));
        }
        throw e;
      }
      ui.toast(row ? 'Follow-up updated' : `Follow-up added — due ${fmt.date(due.value)}`, 'good');
      if (opts.onSaved) opts.onSaved(); else ctx.refresh?.();
    },
  });
  if (!lock) syncScope();
  return m;
}

const ROLE_SHORT = { college_lead: 'College lead', ambassador_lead: 'Ambassador lead', ambassador: 'Ambassador' };
