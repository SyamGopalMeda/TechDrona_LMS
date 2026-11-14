// Tech Drona portal — Team: directory (#/people) and person page (#/person/:id)   (agent TM)
// Live data only. Assignment status, actuals, targets, remaining/exceeded/% and status all come from the server
// (GET /api/people v4 envelope, GET /api/performance); this view never recomputes them.
import * as forms from './forms.js';
import { fmt as F } from '../ui/h.js';
import { getMeta, crumbs, followupList, activityList, ROLE_LABEL } from './branch.js';

const SEGMENTS = [
  { value: 'all', label: 'All' },
  { value: 'leads', label: 'College leads' },
  { value: 'ambassadors', label: 'Ambassadors' },
  { value: 'unassigned', label: 'Unassigned' },
];
const SEG_PARAMS = {
  all: {},
  leads: { role: 'college_lead' },
  ambassadors: { role: 'ambassador_lead,ambassador' },
  unassigned: { assignment: 'unassigned,invalid_link' },
};
const ISSUE_TEXT = {
  no_lead: 'No lead assigned', lead_missing: 'Lead record no longer exists', lead_inactive: 'Lead is inactive',
  lead_other_college: 'Lead belongs to another college', lead_wrong_role: 'Reports to someone who is not a lead',
};
const PAGE_SIZE = 50;
const opts = (pairs) => pairs.map(([value, label]) => ({ value, label }));
const stop = (e) => e.stopPropagation();
const pctText = (p) => F.pctPts(p); // the ONE shared % rule (percent number from /api/performance)
const tail = (phone) => { const d = String(phone || '').replace(/\D/g, ''); return d.length >= 4 ? `…${d.slice(-4)}` : ''; };
const collegeOf = (p) => p.college || (p.college_id ? { id: p.college_id, name: p.college_name, short_name: p.college_short_name } : null);
const isLeadRole = (r) => r === 'college_lead' || r === 'ambassador_lead';

/* ------------------------------------------------------------------ shared cells */

function roleChip(ctx, p) { return ctx.ui.badge(ROLE_LABEL[p.role] || p.role, p.role === 'ambassador' ? 'neutral' : 'brand'); }

function assignmentCell(ctx, p) {
  const { h, ui } = ctx;
  if (p.role === 'college_lead') return h('span', { class: 'vx-muted vx-small' }, 'Leads the college');
  const st = p.assignment_status || (p.reports_to ? 'assigned' : 'unassigned');
  const lead = p.lead || (p.reports_to ? { id: p.reports_to, name: p.reports_to_name } : null);
  return h('div', { class: 'v-people__lead' },
    lead && lead.id ? h('a', { href: `#/person/${lead.id}`, onClick: stop, class: lead.status === 'inactive' ? 'is-inactive' : null }, lead.name || `#${lead.id}`) : null,
    st === 'assigned' ? null : ui.statusChip(st, { size: 'sm', title: ISSUE_TEXT[p.assignment_issue] || '' }),
    st === 'invalid_link' && p.assignment_issue ? h('span', { class: 'vx-small vx-muted' }, ISSUE_TEXT[p.assignment_issue] || '') : null);
}

/** Target vs actual for the programme period, exactly as the server returned it. */
function perfCell(ctx, p) {
  const { h, ui, fmt } = ctx;
  const ts = p.target_summary;
  const actual = p.actual_own ?? p.enrolled ?? 0;
  if (!ts) return ui.progressBar(actual, p.target ?? null, { size: 'sm', unit: 'enrolled' });
  return h('div', { class: 'v-people__perf' },
    ui.progressBar(actual, ts.target, { min: ts.min, max: ts.max, size: 'sm', unit: 'enrolled', status: ts.status, pct: ts.pct }),
    h('div', { class: 'v-people__perfmeta' }, ui.statusChip(ts.status, { size: 'sm' }),
      isLeadRole(p.role) && p.team_size ? h('span', { class: 'vx-small vx-muted' }, `Team ${fmt.num(p.actual_team ?? 0)} · combined ${fmt.num(p.actual_combined ?? actual)}`) : null));
}

function nameCell(ctx, p) {
  const { h } = ctx;
  const sub = [p.designation, tail(p.phone_norm || p.phone)].filter(Boolean).join(' · ');
  return h('div', { class: 'v-people__name' },
    h('a', { href: `#/person/${p.id}`, onClick: stop }, p.full_name || '(no name)'),
    // shown only when the Role column is hidden for width (.td-dt--hide3), so the role is never lost (D2)
    h('span', { class: 'v-people__rolein' }, roleChip(ctx, p)),
    sub ? h('span', { class: 'vx-small vx-muted' }, sub) : null);
}
function collegeLink(ctx, p) {
  const c = collegeOf(p);
  return c ? ctx.h('a', { href: `#/college/${c.id}`, onClick: stop, title: c.name || '' }, c.short_name || c.name || c.id) : '—';
}

function contactCell(ctx, p) {
  return ctx.ui.contactActions(p.phone_norm || p.phone, p.email, { compact: true, whatsapp: true, name: p.full_name });
}

/* ------------------------------------------------------------------ directory */

export async function renderList(el, params = {}, ctx) {
  const { h, ui, fmt, api } = ctx;
  crumbs(ctx, [{ label: 'Team' }]);
  const q0 = ui.getHashQuery();
  const f = {
    seg: SEG_PARAMS[q0.seg] ? q0.seg : (q0.view === 'amb_no_lead' ? 'unassigned' : 'all'),
    q: q0.q || '', role: q0.role || '', college: q0.college || '', lead: q0.lead || '', assignment: q0.assignment || '', status: q0.status || '',
    sort: q0.sort || 'name', page: Math.max(1, Number(q0.page) || 1),
  };
  const root = h('div', { class: 'v-people v-people--dir' });
  el.replaceChildren(root);

  const addBtn = ui.writeOnly(ui.button({ label: 'Add person', icon: 'plus', tone: 'primary', onClick: () => forms.personDialog(ctx, {}) }));
  const head = ui.pageHeader({
    title: 'Team', scope: true,
    sub: 'College leads, ambassador leads and ambassadors — who belongs where, who manages whom, and how each is doing against target.',
    actions: [addBtn],
  });
  const segWrap = h('div', { class: 'v-people__segs' });
  const fbarWrap = h('div', { class: 'v-people__filters' });
  const bulkBar = h('div', { class: 'v-people__bulk', hidden: true, role: 'region', 'aria-label': 'Bulk actions' });
  const tableWrap = h('div', { class: 'v-people__table' });
  const links = h('p', { class: 'v-people__links vx-small' },
    'Colleges: ', h('a', { href: '#/colleges?team=no_lead' }, 'without a college lead'), ' · ', h('a', { href: '#/colleges?team=no_ambassadors' }, 'without ambassadors'),
    ' · ', h('a', { href: '#/colleges?team=has_unassigned' }, 'with unassigned ambassadors'));
  const leftNote = h('p', { class: 'vx-small vx-muted v-people__left', hidden: true });
  root.append(head, segWrap, fbarWrap, bulkBar, tableWrap, leftNote, links);

  // filter option sources (scoped to the district picker) load next to the first page
  let colleges = [];
  let leads = [];
  const sources = Promise.all([
      api.getScoped('/colleges').catch(() => []),
      api.getScoped('/people', { role: 'college_lead,ambassador_lead', status: 'active,onboarding', page: 1, page_size: 200 }).catch(() => []),
  ]).then(([c, l]) => { colleges = forms.peopleRows(c); leads = forms.peopleRows(l); }).catch(() => { /* filters degrade to empty lists */ });
  const cname = (c) => (c.short_name && !String(c.name).includes(c.short_name) ? `${c.name} (${c.short_name})` : c.name);
  const collegeOpts = () => colleges.slice().sort((a, b) => String(a.name).localeCompare(b.name)).map((c) => ({ value: c.id, label: cname(c) }));
  const leadOpts = () => [{ value: 'none', label: 'No lead (unassigned)' }, ...leads.filter((p) => !f.college || p.college_id === f.college)
    .sort((a, b) => String(a.full_name).localeCompare(b.full_name))
    .map((p) => ({ value: String(p.id), label: `${p.full_name} — ${p.college?.short_name || p.college_short_name || p.college_id}` }))];

  let fbar;
  const buildFilters = () => {
    fbar = ui.filterBar({
      search: { key: 'q', placeholder: 'Search name, phone, email or college', value: f.q, debounce: 300 },
      values: { q: f.q, role: f.role, college: f.college, lead: f.lead, assignment: f.assignment, status: f.status },
      filters: [
        { key: 'role', label: 'Role', options: opts([['college_lead', 'College lead'], ['ambassador_lead', 'Ambassador lead'], ['ambassador', 'Ambassador']]) },
        { key: 'college', label: 'College', options: collegeOpts() },
        { key: 'lead', label: 'Lead', options: leadOpts() },
        { key: 'assignment', label: 'Assignment', options: opts([['assigned', 'Assigned'], ['unassigned', 'No lead'], ['invalid_link', 'Invalid lead link']]) },
        { key: 'status', label: 'Status', options: opts([['active', 'Active'], ['onboarding', 'Onboarding'], ['inactive', 'Inactive']]) },
      ],
      onChange: (v, k) => {
        Object.assign(f, v, { page: 1 });
        if (k === 'college' && f.lead && f.lead !== 'none' && !leads.some((p) => String(p.id) === f.lead && (!f.college || p.college_id === f.college))) f.lead = '';
        if (k === 'college') { const old = fbar; buildFilters(); old.replaceWith(fbar); }
        load({ push: k !== 'q' });
      },
    });
    return fbar;
  };
  fbarWrap.append(buildFilters());
  sources.then(() => { const old = fbar; buildFilters(); old.replaceWith(fbar); if (selected.length) drawBulk(); });

  let selected = [];
  /** D11/T19/P20: "No people yet" only when nothing at all is filtered; "Nobody matches these filters" otherwise. */
  const isFiltered = () => f.seg !== 'all' || [f.q, f.role, f.college, f.lead, f.assignment, f.status].some(Boolean);
  const clearFilters = () => {
    Object.assign(f, { seg: 'all', q: '', role: '', college: '', lead: '', assignment: '', status: '', page: 1 });
    const old = fbar; buildFilters(); old.replaceWith(fbar); load({ push: true });
  };
  function emptyFor() {
    const filtered = isFiltered();
    if (typeof ui.listEmpty === 'function') {
      return ui.listEmpty({ filtered, noun: 'people', addLabel: 'Add College Lead', onAdd: () => forms.personDialog(ctx, { role: 'college_lead' }), onClear: clearFilters,
        text: filtered ? null : 'Add the first College Lead, then their ambassadors. Everyone you add appears here with their targets.' });
    }
    return filtered
      ? { title: 'Nobody matches these filters', text: 'Try another search, or clear the filters to see everyone.' }
      : { title: 'No people yet', text: 'Add the first College Lead, then their ambassadors.' };
  }
  // D2/T04: column priorities (responsive.md §4) — Role and Contact hide first, then the table becomes cards; the row
  // "⋯" actions stay in the sticky right column (table) or the card head (cards), so they are reachable at every width.
  const table = ui.dataTable({
    caption: 'Team members',
    columns: [
      { key: 'name', label: 'Name', primary: true, priority: 1, minWidth: 200, render: (p) => nameCell(ctx, p) },
      { key: 'role', label: 'Role', priority: 3, minWidth: 130, cardHidden: true, render: (p) => roleChip(ctx, p) },
      { key: 'college', label: 'College', priority: 2, minWidth: 100, cardHidden: true, render: (p) => collegeLink(ctx, p) },
      { key: 'assignment', label: 'Lead', priority: 2, minWidth: 140, render: (p) => assignmentCell(ctx, p) },
      { key: 'contact', label: 'Contact', sortable: false, priority: 3, minWidth: 150, render: (p) => contactCell(ctx, p) },
      { key: 'actual', label: 'Target vs actual (programme)', phoneLabel: 'Target vs actual', priority: 2, minWidth: 190, render: (p) => perfCell(ctx, p) },
      { key: 'status', label: 'Status', priority: 1, minWidth: 100, cardHidden: true, render: (p) => ui.statusChip(p.status || 'active', { size: 'sm' }) },
    ],
    cardTitle: (p) => h('a', { href: `#/person/${p.id}`, onClick: stop }, p.full_name || '(no name)'),
    cardSubtitle: (p) => { const c = collegeOf(p); return [ROLE_LABEL[p.role] || p.role, c ? (c.short_name || c.name) : null, p.designation].filter(Boolean).join(' · '); },
    cardMeta: (p) => [p.status && p.status !== 'active' ? ui.statusChip(p.status, { size: 'sm' }) : null],
    rows: [], loading: true, pageSize: PAGE_SIZE, page: f.page, total: 0, pageLabel: 'people',
    sort: { key: f.sort.replace(/^-/, ''), dir: f.sort.startsWith('-') ? 'desc' : 'asc' },
    onSort: (key, dir) => { f.sort = `${dir === 'desc' ? '-' : ''}${key}`; f.page = 1; load({ push: true }); },
    onPage: (n) => { f.page = n; load({ push: true }); },
    rowHref: (p) => `#/person/${p.id}`,
    selectable: ui.canWrite(),
    onSelect: (rows) => { selected = rows; drawBulk(); },
    rowActions: (p) => [
      { label: 'Edit', icon: 'edit', writeOnly: true, onClick: () => forms.personDialog(ctx, { id: p.id }) },
      { label: 'Move to another college', icon: 'college', writeOnly: true, onClick: () => forms.movePerson(ctx, p) },
      p.status === 'inactive'
        ? { label: 'Reactivate', icon: 'check', writeOnly: true, onClick: () => forms.reactivatePerson(ctx, p) }
        : { label: 'Deactivate…', icon: 'close', tone: 'danger', writeOnly: true, onClick: () => forms.deactivatePerson(ctx, p) },
    ],
    empty: emptyFor(),
    onRetry: () => load(),
  });
  tableWrap.append(table);

  function drawBulk() {
    bulkBar.hidden = !selected.length;
    if (!selected.length) { bulkBar.replaceChildren(); return; }
    const cols = [...new Set(selected.map((p) => collegeOf(p)?.id))];
    const n = selected.length;
    const label = h('strong', null, `${fmt.num(n)} selected`);
    const clear = ui.button({ label: 'Clear', tone: 'ghost', size: 'sm', onClick: () => table.clearSelection() });
    if (cols.length > 1) {
      bulkBar.replaceChildren(label, h('span', { class: 'vx-small' }, 'People from different colleges are selected. A lead can only manage people of their own college — pick people of one college.'), clear);
      return;
    }
    const hasAmbLead = selected.some((p) => p.role === 'ambassador_lead');
    const cand = leads.filter((p) => p.college_id === cols[0] && !selected.some((s) => Number(s.id) === Number(p.id)) && (!hasAmbLead || p.role === 'college_lead'));
    const leadsSel = h('select', { class: 'td-input td-select td-input--sm', 'aria-label': 'Assign to lead' },
      h('option', { value: '' }, cand.length ? 'Choose a lead…' : 'No active lead at this college'),
      cand.map((p) => h('option', { value: String(p.id) }, `${p.full_name} (${ROLE_LABEL[p.role]})`)),
      h('option', { value: 'none' }, '— Remove lead (unassign) —'));
    const go = ui.button({ label: 'Assign', tone: 'primary', size: 'sm', onClick: async () => {
      if (!leadsSel.value) { leadsSel.focus(); return; }
      if (selected.some((p) => p.role === 'college_lead')) { ui.toast('College leads do not report to anyone — unselect them first.', 'warn'); return; }
      go.disabled = true;
      const to = leadsSel.value === 'none' ? null : Number(leadsSel.value);
      const r = await forms.assignToLead(ctx, selected.map((p) => p.id), to);
      go.disabled = false;
      if (r.failed.length) ui.toast(`${r.ok.length} updated, ${r.failed.length} not: ${r.failed[0].message}`, 'bad');
      else ui.toast(`${r.ok.length} ${r.ok.length === 1 ? 'person' : 'people'} ${to ? `now report to ${cand.find((c) => c.id === to)?.full_name}` : 'unassigned'}`, 'good');
      table.clearSelection();
      load();
    } });
    bulkBar.replaceChildren(label, h('span', { class: 'vx-small vx-muted' }, `at ${collegeOf(selected[0])?.short_name || collegeOf(selected[0])?.name || ''}`), leadsSel, go, clear);
  }

  const queryParams = () => {
    const seg = SEG_PARAMS[f.seg] || {};
    // F4/D9: without a status filter the directory lists people still on the team (active + onboarding), the same
    // population its segment counts and Home use; people who left are one click away (status=inactive)
    const p = { q: f.q, college_id: f.college, reports_to: f.lead, status: f.status || 'active,onboarding', sort: f.sort };
    // the role filter narrows the segment; it never widens it
    const segRoles = seg.role ? seg.role.split(',') : null;
    p.role = f.role ? (segRoles && !segRoles.includes(f.role) ? '__none__' : f.role) : seg.role;
    p.assignment = f.assignment || seg.assignment;
    if (f.seg === 'unassigned' && f.assignment === 'assigned') p.assignment = '__none__';
    return p;
  };

  let seq = 0;
  let legacy = false;
  /** load({push}) — segment / filter / sort / page changes push a history entry so Back undoes them (D8); typing replaces. */
  async function load({ push = false } = {}) {
    const my = ++seq;
    if (!location.hash.startsWith('#/people')) return; // F16: the user left the page while a request was pending
    ui.setHashQuery({ seg: f.seg === 'all' ? null : f.seg, q: f.q, role: f.role, college: f.college, lead: f.lead, assignment: f.assignment, status: f.status, sort: f.sort === 'name' ? null : f.sort, page: f.page > 1 ? f.page : null, view: null }, { replace: !push });
    table.update({ loading: true, error: null, empty: emptyFor() });
    selected = []; drawBulk();
    const p = queryParams();
    if (p.role === '__none__' || p.assignment === '__none__') { table.update({ rows: [], total: 0, page: 1, loading: false }); drawSegs(null); return; }
    try {
      const base = { q: f.q, college_id: f.college, reports_to: f.lead, status: f.status || 'active,onboarding', page: 1, page_size: 1 };
      const [r, cnt, left] = await Promise.all([
        api.getScoped('/people', { ...p, page: f.page, page_size: PAGE_SIZE }),
        api.getScoped('/people', base).catch(() => null),
        f.status ? Promise.resolve(null) : api.getScoped('/people', { ...base, status: 'inactive' }).catch(() => null),
      ]);
      if (my !== seq || !location.hash.startsWith('#/people')) return;
      if (Array.isArray(r)) { legacy = true; return legacyDraw(r, my); }
      const pages = Math.max(1, Math.ceil((r.total || 0) / PAGE_SIZE));
      if (f.page > pages) { f.page = pages; return load(); }
      table.update({ rows: r.items || [], total: r.total || 0, page: r.page || f.page, loading: false, sort: { key: f.sort.replace(/^-/, ''), dir: f.sort.startsWith('-') ? 'desc' : 'asc' } });
      drawSegs(cnt && !Array.isArray(cnt) ? cnt : null);
      const nLeft = left && !Array.isArray(left) && isFinite(left.total) ? left.total : 0;
      leftNote.replaceChildren(...(nLeft ? [`${fmt.plural(nLeft, 'person', 'people')} who left ${nLeft === 1 ? 'is' : 'are'} not listed. `,
        h('a', { href: '#/people?status=inactive', onClick: (e) => { e.preventDefault(); f.status = 'inactive'; f.page = 1; const old = fbar; buildFilters(); old.replaceWith(fbar); load({ push: true }); } }, 'Show them')] : []));
      leftNote.hidden = !nLeft;
    } catch (e) {
      if (my !== seq) return;
      table.update({ error: e, loading: false });
    }
  }

  /** Servers before v4 return a plain array: filter/sort/page here from the same live rows. */
  function legacyDraw(rows, my) {
    if (my !== seq) return;
    const segRows = (s) => rows.filter((p) => (s === 'leads' ? p.role === 'college_lead' : s === 'ambassadors' ? p.role !== 'college_lead'
      : s === 'unassigned' ? p.role !== 'college_lead' && p.status !== 'inactive' && !p.reports_to : true));
    let list = segRows(f.seg);
    if (f.role) list = list.filter((p) => p.role === f.role);
    if (f.lead) list = list.filter((p) => (f.lead === 'none' ? !p.reports_to : String(p.reports_to) === f.lead));
    if (f.assignment) list = list.filter((p) => (f.assignment === 'assigned' ? !!p.reports_to : f.assignment === 'unassigned' ? !p.reports_to : false));
    const dir = f.sort.startsWith('-') ? -1 : 1;
    const key = f.sort.replace(/^-/, '');
    const val = (p) => ({ name: p.full_name, college: p.college_name, role: p.role, status: p.status, actual: p.enrolled, pct: p.pct, assignment: p.reports_to ? 1 : 0 }[key] ?? p.full_name);
    list.sort((a, b) => { const x = val(a); const y = val(b); return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? ''))) * dir; });
    const total = list.length;
    table.update({ rows: list.slice((f.page - 1) * PAGE_SIZE, f.page * PAGE_SIZE), total, page: f.page, loading: false });
    drawSegs({ total: rows.length, counts: { college_lead: segRows('leads').length, ambassador: segRows('ambassadors').length, unassigned: segRows('unassigned').length } });
  }

  function drawSegs(cnt) {
    const c = cnt?.counts || {};
    const counts = cnt ? {
      all: cnt.total,
      leads: c.college_lead,
      ambassadors: (c.ambassador || 0) + (legacy ? 0 : (c.ambassador_lead || 0)),
      unassigned: (c.unassigned || 0) + (c.invalid_link || 0),
    } : {};
    const seg = ui.segmented({
      ariaLabel: 'Show', value: f.seg,
      options: SEGMENTS.map((s) => ({ ...s, count: counts[s.value] })),
      onChange: (v) => { f.seg = v; f.page = 1; load({ push: true }); },
    });
    if (counts.unassigned) seg.querySelector('[data-value="unassigned"]')?.classList.add('v-people__seg--alert');
    segWrap.replaceChildren(seg);
  }

  load();
  await sources;
}

/* ------------------------------------------------------------------ person page */

function treeOf(people, rootId) {
  const kids = new Map();
  for (const p of people) {
    if (p.reports_to == null) continue;
    const k = Number(p.reports_to);
    if (!kids.has(k)) kids.set(k, []);
    kids.get(k).push(p);
  }
  const seen = new Set([Number(rootId)]);
  const walk = (id) => (kids.get(Number(id)) || []).filter((p) => !seen.has(Number(p.id)) && seen.add(Number(p.id)))
    .sort((a, b) => (a.status === 'inactive') - (b.status === 'inactive') || String(a.full_name).localeCompare(b.full_name))
    .map((p) => ({ p, children: walk(p.id) }));
  return walk(rootId);
}

function treeList(ctx, nodes) {
  const { h, ui, fmt } = ctx;
  if (!nodes.length) return null;
  return h('ul', { class: 'v-person__tree' }, nodes.map(({ p, children }) => h('li', null,
    h('div', { class: ['v-person__node', p.status === 'inactive' && 'is-inactive'] },
      h('a', { href: `#/person/${p.id}` }, p.full_name), roleChip(ctx, p),
      p.status !== 'active' ? ui.statusChip(p.status, { size: 'sm' }) : null,
      h('span', { class: 'vx-small vx-muted td-num' }, `${fmt.num(p.actual_own ?? p.enrolled ?? 0)} confirmed`),
      contactCell(ctx, p)),
    treeList(ctx, children))));
}

/** One "Own / Team / Combined" block from a /api/performance row (values as returned). */
function perfBlock(ctx, title, b, note) {
  const { h, ui, fmt } = ctx;
  if (!b) return null;
  const actual = b.actual ?? 0;
  const fig = (label, val) => h('div', { class: 'vx-fig' }, h('div', { class: 'vx-fig-label' }, label), h('div', { class: 'vx-fig-value td-num' }, val));
  return h('div', { class: 'v-person__perf' },
    h('div', { class: 'v-person__perfhead' }, h('strong', null, title), ui.statusChip(b.status, { size: 'sm' }), note ? h('span', { class: 'vx-small vx-muted' }, note) : null),
    ui.progressBar(actual, b.target, { min: b.min, max: b.max, size: 'md', unit: 'enrolled', status: b.status, pct: b.pct }),
    b.covers && Number(b.covers.total) > 0 && Number(b.covers.with_target) < Number(b.covers.total)
      ? h('p', { class: 'vx-small vx-muted' }, `${fmt.num(b.covers.with_target)} of ${fmt.plural(b.covers.total, 'member')} have a target for this period — the team is judged only when everyone has one.`) : null,
    h('div', { class: 'vx-figs v-person__figs' },
      fig('Target', b.target == null ? '—' : `${fmt.num(b.target)}${F.range(b.min, b.max) ? ` (${F.range(b.min, b.max)})` : ''}`),
      fig('Actual', fmt.num(actual)),
      fig('Remaining', b.remaining == null ? '—' : fmt.num(b.remaining)),
      fig('Exceeded by', b.exceeded_by ? fmt.num(b.exceeded_by) : '—'),
      fig('Achieved', pctText(b.pct))));
}

export async function renderPerson(el, params = {}, ctx) {
  const { h, ui, fmt, api } = ctx;
  const id = params.id;
  el.replaceChildren(h('div', { class: 'v-people v-person' }, ui.skeleton(6)));
  let d;
  let meta;
  try { [d, meta] = await Promise.all([api.get(`/people/${id}`), getMeta(ctx)]); } catch (e) {
    crumbs(ctx, [{ label: 'Team', href: '#/people' }, { label: 'Not found' }]);
    el.replaceChildren(h('div', { class: 'v-people v-person' }, ui.emptyState({
      icon: 'people', title: e.status === 404 ? 'Person not found' : 'Could not load this person',
      text: e.status === 404 ? 'They may have been removed. Go back to the team directory to find someone else.' : e.message,
      action: h('a', { href: '#/people', class: 'td-btn td-btn--secondary' }, 'Back to team'),
    })));
    return;
  }
  const p = d.person || {};
  const c = d.college || collegeOf(p) || {};
  const [colRes, auditRes, tgtRes] = await Promise.all([
    api.get('/people', { college_id: p.college_id, page: 1, page_size: 200 }).catch(() => api.get('/people', { college: p.college_id }).catch(() => [])),
    api.get('/audit', { entity: 'person', entity_id: p.id, limit: 15 }).catch(() => []),
    api.get('/targets', { scope: `person:${p.id}` }).catch(() => []),
  ]);
  const colPeople = forms.peopleRows(colRes);
  const lead = p.lead || (p.reports_to ? colPeople.find((x) => Number(x.id) === Number(p.reports_to)) : null);
  const leadRow = lead ? colPeople.find((x) => Number(x.id) === Number(lead.id)) || lead : null;
  const collegeLead = colPeople.find((x) => x.role === 'college_lead' && x.status !== 'inactive');
  const chain = [];
  { let cur = p; const seen = new Set([Number(p.id)]); while (cur && cur.reports_to && !seen.has(Number(cur.reports_to))) { seen.add(Number(cur.reports_to)); const b = colPeople.find((x) => Number(x.id) === Number(cur.reports_to)); if (!b) break; chain.unshift(b); cur = b; } }
  const tree = treeOf(colPeople, p.id);
  const can = ui.canWrite();
  const isLead = isLeadRole(p.role);

  crumbs(ctx, [{ label: 'Team', href: '#/people' }, c.id ? { label: c.short_name || c.name, href: `#/college/${c.id}?tab=team` } : null, { label: p.full_name }].filter(Boolean));

  const edit = () => forms.personDialog(ctx, { id: p.id });
  const root = h('div', { class: 'v-people v-person' });
  const moreItems = [
    { label: 'Record enrollment', icon: 'plus', writeOnly: true, onClick: () => forms.recordEnrollment(ctx, { college_id: p.college_id, person_id: p.id }) },
    { label: 'Log activity', icon: 'clock', writeOnly: true, onClick: () => forms.logActivity(ctx, { college_id: p.college_id, person_id: p.id }) },
    { label: 'Add follow-up', icon: 'followup', writeOnly: true, onClick: () => forms.addFollowup(ctx, { scope_type: 'person', scope_id: String(p.id), college_id: p.college_id, label: p.full_name }) },
    { label: 'Move to another college…', icon: 'college', writeOnly: true, onClick: () => forms.movePerson(ctx, p) },
    p.role === 'college_lead' && p.status !== 'inactive' ? { label: 'Replace as college lead…', icon: 'lead', writeOnly: true, onClick: () => forms.replaceLead(ctx, p) } : null,
    p.status === 'inactive'
      ? { label: 'Reactivate', icon: 'check', writeOnly: true, onClick: () => forms.reactivatePerson(ctx, p) }
      : { label: 'Deactivate…', icon: 'close', tone: 'danger', writeOnly: true, onClick: () => forms.deactivatePerson(ctx, p) },
  ].filter(Boolean);
  root.append(ui.pageHeader({
    back: { href: '#/people', label: 'Team' },
    eyebrow: h('span', { class: 'v-person__kicker' }, roleChip(ctx, p), ui.statusChip(p.status || 'active', { size: 'sm' }),
      p.role !== 'college_lead' && p.assignment_status && p.assignment_status !== 'assigned' ? ui.statusChip(p.assignment_status, { size: 'sm' }) : null),
    title: p.full_name || '(no name)',
    sub: h('span', null, c.id ? h('a', { href: `#/college/${c.id}` }, c.name || c.short_name) : 'No college', p.designation ? ` · ${p.designation}` : ''),
    actions: [
      ui.writeOnly(ui.button({ label: 'Edit', icon: 'edit', tone: 'primary', onClick: edit })),
      ui.writeOnly(ui.button({ label: 'Set target', icon: 'target', onClick: () => forms.targetDialog(ctx, { scope_type: 'person', scope_id: String(p.id), label: p.full_name, period: perState.period }) })),
      ui.menu({ ariaLabel: 'More actions', items: moreItems }),
    ],
  }));

  if (p.role !== 'college_lead' && p.status !== 'inactive' && p.assignment_status && p.assignment_status !== 'assigned') {
    root.append(h('div', { class: 'vx-callout vx-callout-warn', role: 'status' },
      h('span', { class: 'vx-callout-ic' }, ui.icon('warn')),
      h('div', { class: 'vx-callout-body' }, h('strong', null, ISSUE_TEXT[p.assignment_issue] || 'No lead assigned'),
        h('div', { class: 'vx-callout-text' }, collegeLead ? `Assign ${p.full_name} to a lead of ${c.short_name || c.name}.` : `${c.short_name || c.name || 'This college'} has no active college lead yet — appoint one, then assign ${p.full_name}.`)),
      can ? ui.button({ label: collegeLead ? 'Assign lead' : 'Appoint college lead', size: 'sm', onClick: () => (collegeLead ? edit() : forms.personDialog(ctx, { college_id: p.college_id, role: 'college_lead' })) }) : null));
  }

  // --- where they fit + contact
  const fit = h('div', { class: 'v-person__fit' },
    ui.kv([
      ['College', c.id ? h('a', { href: `#/college/${c.id}` }, c.name || c.short_name) : '—'],
      ['College lead', p.role === 'college_lead' ? 'This person' : collegeLead ? h('a', { href: `#/person/${collegeLead.id}` }, collegeLead.full_name) : h('span', { class: 'vx-warn-text' }, 'None appointed')],
      p.role === 'college_lead' ? ['Reports to', 'Tech Drona'] : ['Managed by', leadRow ? h('span', { class: 'v-person__mgr' },
        h('a', { href: `#/person/${leadRow.id}`, class: leadRow.status === 'inactive' ? 'is-inactive' : null }, leadRow.name || leadRow.full_name),
        leadRow.role ? ` · ${ROLE_LABEL[leadRow.role] || leadRow.role}` : '', leadRow.phone || leadRow.email ? contactCell(ctx, leadRow) : null)
        : h('span', { class: 'vx-warn-text' }, 'Nobody (unassigned)')],
      chain.length > 1 ? ['Reporting line', h('span', null, [...chain.map((x, i) => [i ? ' → ' : '', h('a', { href: `#/person/${x.id}` }, x.full_name)]), ' → ', h('strong', null, p.full_name)])] : null,
      isLead || tree.length ? ['Reports to them', tree.length ? `${fmt.num(p.team_size ?? tree.length)} ${(p.team_size ?? tree.length) === 1 ? 'person' : 'people'} (below)` : 'Nobody yet'] : null,
      ['Branches', (d.branches || []).length ? (d.branches || []).map((b) => b.code || b.name).join(', ') : (p.role === 'college_lead' ? 'Whole college' : '—')],
      ['Joined', p.joined_on ? fmt.date(p.joined_on) : '—'],
      p.notes ? ['Notes', h('span', { class: 'v-person__notes' }, p.notes)] : null,
    ].filter(Boolean)));
  const contact = h('div', { class: 'v-person__contact' },
    h('div', { class: 'v-person__contactlines' },
      h('div', null, ui.icon('phone'), ' ', p.phone_norm || p.phone ? forms.formatPhone(p.phone_norm || p.phone) : h('span', { class: 'vx-muted' }, 'No phone recorded')),
      h('div', null, ui.icon('mail'), ' ', p.email || h('span', { class: 'vx-muted' }, 'No email recorded'))),
    ui.contactActions(p.phone_norm || p.phone, p.email, { whatsapp: true, name: p.full_name }));
  root.append(h('div', { class: 'v-person__grid' },
    ui.section({ title: 'Where they fit', body: fit }),
    ui.section({ title: 'Contact', body: contact })));

  // --- targets & performance (server values only)
  // F13: "this month / this week" come from the server's TODAY (same as the Targets page), never the browser clock
  let td = ctx.state?.meta?.today || null;
  if (!td) { try { td = (await api.get('/health')).today || null; } catch { /* fall back below */ } }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(td || ''))) { const n = new Date(); td = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`; }
  const ym = td.slice(0, 7);
  const periods = [{ value: 'programme', label: 'Programme' }, { value: `month:${ym}`, label: 'This month' }, { value: `week:${forms.mondayOf(td)}`, label: 'This week' }];
  for (const r of (Array.isArray(tgtRes) ? tgtRes : [])) {
    const k = r.period_key || 'programme';
    if (!periods.some((x) => x.value === k)) periods.push({ value: k, label: forms.periodLabel(k, fmt) });
  }
  const perState = { period: ui.getHashQuery().period && periods.some((x) => x.value === ui.getHashQuery().period) ? ui.getHashQuery().period : 'programme' };
  const perfBody = h('div', { class: 'v-person__perfbody' });
  const loadPerf = async () => {
    perfBody.replaceChildren(ui.skeleton(2, { card: false }));
    let row = null; let per = null;
    try {
      const r = await api.get('/performance', { level: 'person', period: perState.period, college_id: p.college_id, include_inactive: 1 });
      per = r.period; row = (r.rows || []).find((x) => Number(x.id) === Number(p.id)) || null;
    } catch (e) {
      if (e.status === 404 || e.status === 400) {
        const rr = d.rollup || {};
        perfBody.replaceChildren(h('p', { class: 'vx-muted' }, perState.period === 'programme'
          ? `Confirmed: ${fmt.num(rr.enrolled ?? 0)}${rr.target != null ? ` of ${fmt.num(rr.target)} target` : ' · no target'}. Monthly and weekly figures need the updated server.`
          : 'Monthly and weekly performance needs the updated server.'));
        return;
      }
      perfBody.replaceChildren(ui.errorCard({ title: 'Could not load performance', error: e, retry: loadPerf }));
      return;
    }
    if (!row) { perfBody.replaceChildren(h('p', { class: 'vx-muted' }, 'No performance row for this period.')); return; }
    const own = { min: row.min, target: row.target, max: row.max, actual: row.actual_own ?? row.actual, remaining: row.remaining, exceeded_by: row.exceeded_by, pct: row.pct, status: row.status };
    perfBody.replaceChildren(...[
      per ? h('p', { class: 'vx-small vx-muted' }, `${per.label || forms.periodLabel(perState.period, fmt)}${per.start && !/\d{4}\s*[–-]/.test(per.label || '') ? ` · ${fmt.date(per.start)} – ${fmt.date(per.end)}` : ''}${per.days_total ? ` · day ${fmt.num(per.days_elapsed)} of ${fmt.num(per.days_total)}` : ''}. Confirmed enrollments only.`) : null,
      h('div', { class: 'v-person__perfgrid' },
        perfBlock(ctx, 'Own', own, 'credited to them'),
        row.team ? perfBlock(ctx, 'Team', row.team, `${fmt.num(row.team.size ?? 0)} ${row.team.size === 1 ? 'person' : 'people'} below them · against the team's targets`) : null,
        row.combined ? perfBlock(ctx, 'Combined', row.combined, 'own + team, against own + team targets') : null),
      row.below_min ? h('p', { class: 'vf-note vf-note--warn' }, 'Below the minimum for this period.') : null,
      row.above_max ? h('p', { class: 'vf-note' }, 'Above the stretch maximum for this period.') : null].filter(Boolean));
  };
  const perSeg = ui.segmented({ ariaLabel: 'Period', value: perState.period, options: periods, onChange: (v) => { perState.period = v; ui.setHashQuery({ period: v === 'programme' ? null : v }, { replace: false }); loadPerf(); } });
  root.append(ui.section({
    title: 'Targets & performance',
    actions: [ui.writeOnly(ui.button({ label: 'Set target', icon: 'target', size: 'sm', onClick: () => forms.targetDialog(ctx, { scope_type: 'person', scope_id: String(p.id), label: p.full_name, period: perState.period }) }))],
    body: h('div', null, perSeg, perfBody),
  }));
  loadPerf();

  // --- team tree
  if (isLead || tree.length) {
    root.append(ui.section({
      title: `Team (${fmt.num(tree.length ? (p.team_size ?? tree.length) : 0)})`,
      sub: 'Everyone who reports to them, directly or through an ambassador lead.',
      actions: [ui.writeOnly(ui.button({ label: 'Add ambassador', icon: 'plus', size: 'sm', onClick: () => forms.personDialog(ctx, { college_id: p.college_id, role: 'ambassador', reports_to: p.id }) }))],
      body: tree.length ? treeList(ctx, tree) : h('p', { class: 'vx-muted' }, 'Nobody reports to them yet.'),
    }));
  }

  // --- enrollments (credited)
  const enr = d.enrollments || [];
  const conf = enr.filter((e) => e.stage === 'confirmed' || !e.stage).length;
  const dropped = enr.filter((e) => e.stage === 'dropped').length;
  const courses = meta?.courses || [];
  const enrList = enr.length ? h('ul', { class: 'vx-list' }, enr.map((e) => h('li', { class: 'vx-li' },
    h('div', { class: 'vx-li-main' },
      h('div', { class: 'vx-li-title' }, e.student_name || 'Student (name not recorded)', ' ', forms.stageBadge(ctx, e.stage)),
      h('div', { class: 'vx-li-sub' }, [e.course_name || courses.find((x) => Number(x.id) === Number(e.course_id))?.name || 'Course not set', e.amount_inr != null ? fmt.inr(e.amount_inr) : null, e.branch_code].filter(Boolean).join(' · ')),
      h('div', { class: 'vx-li-sub vx-muted' }, [`recorded ${fmt.date(e.enrolled_on)}`, e.confirmed_on ? `confirmed ${fmt.date(e.confirmed_on)}` : null].filter(Boolean).join(' · '))),
    ui.writeOnly(ui.button({ label: 'Edit', icon: 'edit', tone: 'ghost', size: 'sm', ariaLabel: `Edit enrollment of ${e.student_name || 'student'}`, onClick: () => forms.editEnrollment(ctx, e) })))))
    : ui.emptyState({ icon: 'target', title: 'No enrollments credited yet', text: 'Enrollments recorded with this person as “Credit to” appear here.' });
  root.append(ui.section({
    title: 'Enrollments credited',
    sub: enr.length ? `${fmt.num(conf)} confirmed · ${fmt.num(enr.length - conf - dropped)} in progress · ${fmt.num(dropped)} dropped` : null,
    actions: [ui.writeOnly(ui.button({ label: 'Record', icon: 'plus', size: 'sm', onClick: () => forms.recordEnrollment(ctx, { college_id: p.college_id, person_id: p.id }) }))],
    body: enrList,
  }));

  // --- activity: follow-ups, logged activities, change history
  const fu = d.followups || [];
  const audit = Array.isArray(auditRes) ? auditRes : auditRes?.items || auditRes?.rows || [];
  const historyList = audit.length ? h('ul', { class: 'vx-list' }, audit.map((a) => h('li', { class: 'vx-li' },
    h('div', { class: 'vx-li-main' },
      h('div', { class: 'vx-li-title' }, a.action === 'create' ? 'Added' : a.action === 'delete' ? 'Deleted' : 'Updated', a.fields ? h('span', { class: 'vx-small vx-muted' }, ` · ${[].concat(a.fields).join(', ')}`) : null),
      h('div', { class: 'vx-li-sub vx-muted' }, `${a.at || a.created_at ? fmt.date(a.at || a.created_at) : ''}${a.actor ? ` · by ${a.actor}` : ''}`)))))
    : h('p', { class: 'vx-muted' }, 'No recorded changes.');
  root.append(h('div', { class: 'v-person__grid' },
    ui.section({
      title: `Follow-ups (${fmt.num(fu.filter((x) => x.status === 'open').length)} open)`,
      actions: [ui.writeOnly(ui.button({ label: 'Add', icon: 'plus', size: 'sm', onClick: () => forms.addFollowup(ctx, { scope_type: 'person', scope_id: String(p.id), college_id: p.college_id, label: p.full_name }) }))],
      body: followupList(ctx, fu, { emptyText: 'Nothing scheduled for this person.' }),
    }),
    ui.section({
      title: 'Activities',
      actions: [ui.writeOnly(ui.button({ label: 'Log', icon: 'plus', size: 'sm', onClick: () => forms.logActivity(ctx, { college_id: p.college_id, person_id: p.id }) }))],
      body: activityList(ctx, (d.activities || []).map((a) => ({ ...a, person_name: null }))),
    })));
  root.append(ui.section({
    title: 'Change history',
    sub: p.updated_at ? `Last updated ${fmt.date(p.updated_at)}${p.updated_by ? ` by ${p.updated_by}` : ''}` : null,
    actions: [h('a', { class: 'vx-link vx-small', href: `#/audit?entity=person&entity_id=${p.id}` }, 'Full history')],
    body: historyList,
  }));
  el.replaceChildren(root);
}

export async function render(el, params, ctx) {
  return params && params.id ? renderPerson(el, params, ctx) : renderList(el, params, ctx);
}
