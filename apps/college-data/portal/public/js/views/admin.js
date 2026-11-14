// Tech Drona portal — Data quality (verification queue, gaps, exports), audit log, settings.
// Routes: #/data (?tab=verify|gaps|export&kind=colleges|contacts&show=pending|verified&page=), #/audit (?entity=&entity_id=&actor=&action=&from=&to=&page=), #/settings
// Styles: css/views-admin.css (.v-adm). Data views respect the global district scope.
import { today } from '../ui/h.js';
import { csvRow } from '../ui/components.js';
import { scopeRows, SCOPE_EVENT } from '../state.js';
import { getQuery, setQuery, getScoped, dataTable, verifiedBadge, statusChip, contactActions, kpiRow, scopeLine } from './calls.js';
import { CONTACT_ROLE_LABEL } from './forms.js';

const arr = (x) => (Array.isArray(x) ? x : (x && Array.isArray(x.items) ? x.items : x && Array.isArray(x.rows) ? x.rows : []));
/** Only http(s) links are ever rendered as <a href> (BE-12: a stored "javascript:" URL must never become a link). */
export function safeUrl(u) {
  if (typeof u !== 'string' || !u.trim()) return null;
  try { const x = new URL(u.trim()); return x.protocol === 'http:' || x.protocol === 'https:' ? x.href : null; } catch { return null; }
}
function srcLink(h, src, label = 'Open source') {
  const href = safeUrl(src);
  if (href) return h('a', { href, target: '_blank', rel: 'noopener noreferrer', title: href }, label === null ? hostOf(href) : label);
  return src ? h('span', { class: 'adm-muted', title: String(src) }, 'source noted') : null;
}
const hostOf = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return u; } };

const FIELD_LABEL = {
  lat: 'Map location', lng: 'Map location', website: 'Website', phone: 'Phone', email: 'Email', naac: 'NAAC grade', nirf: 'NIRF rank',
  address: 'Address', city_id: 'Town', intake_per_year: 'Seats / year', tier: 'Tier', ownership: 'Ownership', affiliation: 'Affiliation',
  op_status: 'Operating status', branches: 'Branch list', exams: 'Exam dates', name: 'Name', district_id: 'District', short_name: 'Short name',
  full_name: 'Name', reports_to: 'Reports to', college_id: 'College', role: 'Role', status: 'Status', joined_on: 'Joined on', notes: 'Notes',
  op_status_note: 'Status evidence', op_status_source: 'Status source', due_date: 'Due date', owner_name: 'Assigned to', owner_person_id: 'Assigned to (team member)',
  scope_type: 'About (type)', scope_id: 'About', target: 'Target', target_min: 'Minimum', target_max: 'Maximum', period: 'Period', period_start: 'Period starts',
  stage: 'Stage', enrolled_on: 'Enrolled on', confirmed_on: 'Confirmed on', student_name: 'Student', student_contact: 'Student contact',
  basis: 'Verification', source_url: 'Source link', verified_fields: 'Verified fields', verified_by: 'Verified by', verified_on: 'Verified on',
  title: 'Title', issue: 'Reason', last_contact: 'Last spoke to them', done_at: 'Done on', program_target: 'Programme target', program_deadline: 'Programme deadline',
  program_start: 'Programme start', target_district_groups: 'Target districts', deadline: 'Deadline', course_id: 'Course', person_id: 'Person',
  branch_id: 'Branch', price_inr: 'Price (₹)', active: 'Offered', outcome: 'What happened', called_at: 'Called on', caller: 'Called by', next_action_at: 'Call back on',
  contact_id: 'Contact', semester: 'Semester', endsem_start: 'End-sem starts', endsem_end: 'End-sem ends', evidence: 'Evidence', confidence: 'Confidence',
  aliases: 'Other names', targeted: 'Targeted', designation: 'Designation', responsibility: 'Responsibility', relevance_factors: 'Branch relevance',
  min_conversion: 'Low-conversion alert', org_name: 'Organisation name', state_target_deadline: 'Fallback deadline',
  // calling system and other fields that showed up as raw names in the audit log
  followup_id: 'Call-back', confirms_participation: 'College agreed to take part', participation_confirmed_on: 'College agreed on',
  participation_note: 'Agreement note', status_source: 'Number status set by', unreachable_after_attempts: 'Unanswered calls before "Not working"',
  op_2025_26: 'Admitted students 2025-26', op_2026_27: 'Admitted students 2026-27', contact_source: 'Contact details source', is_demo: 'Demo record',
  students_reached: 'Students reached', on_date: 'Date', type: 'Type', amount_inr: 'Amount paid (₹)', interested_on: 'Interested on',
  registered_on: 'Registered on', applied_on: 'Applied on', dropped_on: 'Dropped on', research_id: 'Research reference', sno: 'Serial no.',
  is_relevant: 'Target branch', category: 'Category', intake_basis: 'Seats basis', intake_source: 'Seats source', intake_year: 'Seats year',
  strength_total: 'Total students', final_year: 'Final-year students', program_deadline: 'Programme deadline',
};
const label = (k) => FIELD_LABEL[k] || String(k).replace(/_/g, ' ').replace(/^\w/, (m) => m.toUpperCase());
/** College fields the verification queue tracks (R13 field_status keys). */
const VERIFY_FIELDS = ['name', 'district_id', 'city_id', 'phone', 'email', 'website', 'ownership', 'affiliation', 'op_status'];
const CATEGORY = {
  it_core: ['Computer science', 'CSE, IT and similar'],
  it_allied: ['CS-related (AI, data, IoT…)', 'AI/ML, Data Science, IoT, Cyber Security, CS & Business Systems…'],
  circuit: ['Electronics / electrical', 'ECE, EEE, EIE — strong overlap with software roles'],
  core: ['Other engineering', 'Civil, Mechanical, Chemical…'],
  other: ['Other', 'Anything else'],
};
const ENTITIES = [['college', 'Colleges'], ['branch', 'Branches'], ['person', 'People'], ['target', 'Targets'], ['enrollment', 'Enrollments'],
  ['activity', 'Activities'], ['followup', 'Follow-ups'], ['contact', 'Contacts'], ['call', 'Calls'], ['exam', 'Exams'], ['course', 'Courses'],
  ['setting', 'Settings'], ['district', 'Districts']];
const PLURAL_TO_ENTITY = { colleges: 'college', branches: 'branch', people: 'person', targets: 'target', enrollments: 'enrollment', activities: 'activity', followups: 'followup', exams: 'exam', courses: 'course', settings: 'setting', districts: 'district', contacts: 'contact', calls: 'call' };
const EXPORTS = [
  ['branches', 'Branches'], ['people', 'Team (leads & ambassadors)'], ['targets', 'Targets'], ['enrollments', 'Enrollments'],
  ['activities', 'Outreach activities'], ['followups', 'Follow-ups'], ['contacts', 'College contacts'], ['courses', 'Courses'],
];

const put = (node, ...kids) => node.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
async function pool(items, n, fn) {
  const out = new Array(items.length);
  let i = 0;
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
    while (i < items.length) { const k = i++; try { out[k] = await fn(items[k]); } catch { out[k] = null; } }
  }));
  return out;
}

function shell(el, ctx, cls, crumb) {
  ctx.setBreadcrumb?.([{ label: crumb, href: location.hash.split('?')[0] }]);
  el.className = `v-adm ${cls}`;
  el.replaceChildren(ctx.ui.skeleton(2), ctx.ui.skeleton(4));
}
function pageHead(ctx, title, sub, actions, { scope } = {}) {
  const { ui, h } = ctx;
  const ext = scope && typeof ui.scopePill === 'function';
  const hd = ui.pageHeader({ title, sub, actions: actions ? [].concat(actions) : [], scope: ext || undefined });
  return scope && !ext ? h('div', null, hd, scopeLine(ctx)) : hd;
}
let fid = 0;
function field(h, lbl, input, help, opts = {}) {
  const id = `adf-${++fid}`;
  if (input.matches?.('input,select,textarea')) input.id = id;
  return h('div', { class: ['td-field', opts.full && 'td-field--full'] },
    h('label', { class: 'td-field__label', for: id }, lbl, opts.req ? h('span', { class: 'td-field__req', 'aria-hidden': 'true' }, ' *') : null), input,
    help ? h('div', { class: 'td-field__help' }, help) : null,
    opts.err || null);
}
const errEl = (h) => h('div', { class: 'td-field__error', 'aria-live': 'polite' });
/** Developer extras (raw JSON) only with ?dev=1 — the shell keeps that switch in sessionStorage 'td.dev' (app.js devMode). */
const devMode = () => { try { return sessionStorage.getItem('td.dev') === '1' || /[?&]dev=1\b/.test(location.hash) || /[?&]dev=1\b/.test(location.search); } catch { return false; } };
/** Inside the Tech Drona LMS the LMS signs people in: no portal name, passcode or sign-out (same test as app.js isSso). */
const isSso = (ctx, session) => !!(ctx.session?.sso || session?.sso) || /^\/college-portal(\/|$)/.test(location.pathname);
const writeOk = async (ctx) => { try { await ctx.ensureUser?.(); return true; } catch { return false; } };
const canWrite = (ctx) => (typeof ctx.canWrite === 'boolean' ? ctx.canWrite : (typeof ctx.ui.canWrite === 'function' ? ctx.ui.canWrite() : true));

/* ---------- downloads ---------- */
function csvOf(rows, cols) {
  // ui.csvCell: quotes + spreadsheet formula-injection guard (= + - @ TAB CR get a leading ') — SEC-02
  return '﻿' + [csvRow(cols), ...rows.map((r) => csvRow(cols.map((k) => r[k])))].join('\r\n');
}
function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function collegesCsv(colleges, dName) {
  const rows = colleges.map((c) => ({
    ...c, district: dName.get(c.district_id) || c.district_id,
    strength: c.strength?.value, strength_basis: c.strength?.basis, eligible: c.eligible?.value, eligible_basis: c.eligible?.basis,
    college_lead: c.lead?.name || (c.college_lead && typeof c.college_lead === 'object' ? c.college_lead.full_name || c.college_lead.name : c.college_lead),
    ambassador_leads: Array.isArray(c.ambassador_leads) ? c.ambassador_leads.length : c.ambassador_leads,
    ambassadors: c.ambassador_count ?? (Array.isArray(c.ambassadors) ? c.ambassadors.length : c.ambassadors),
    branches: Array.isArray(c.branches) ? c.branches.length : c.branches,
    next_exam: c.next_exam ? `${c.next_exam.semester} ${c.next_exam.kind} ${c.next_exam.start}–${c.next_exam.end}` : '',
    next_followup: c.next_followup && typeof c.next_followup === 'object' ? c.next_followup.due_date : c.next_followup,
  }));
  const cols = ['id', 'sno', 'name', 'short_name', 'district', 'city_id', 'lat', 'lng', 'geo_precision', 'op_status', 'targeted', 'data_status', 'tier', 'autonomous',
    'branches', 'strength', 'strength_basis', 'eligible', 'eligible_basis', 'college_lead', 'ambassador_leads', 'ambassadors', 'unassigned_count', 'branches_needing_ambassadors',
    'target', 'enrolled', 'remaining', 'pct', 'on_track', 'diagnosis', 'exam_state', 'next_exam', 'followups_open', 'next_followup'];
  return csvOf(rows, cols);
}
const colsOf = (rows) => [...new Set(rows.flatMap((r) => Object.keys(r)))];

// =================================================================== #/data
let dataCur = null;
export const handlesScope = true; // the data page reloads itself on scope change; audit/settings are not scoped

export async function renderData(el, params = {}, ctx) {
  const { h, ui, api, fmt } = ctx;
  const q = { ...getQuery(), ...params };
  shell(el, ctx, 'v-adm-data', 'Data quality');
  try { dataCur?.off?.(); } catch { /* ignore */ }
  const me = { el, ctx, tab: ['verify', 'gaps', 'export'].includes(q.tab) ? q.tab : 'verify', kind: q.kind === 'contacts' ? 'contacts' : 'colleges',
    show: q.show === 'verified' ? 'verified' : 'pending', page: Math.max(1, Number(q.page) || 1) };
  dataCur = me;
  const onScope = () => { if (dataCur !== me || !el.isConnected) return; me.page = 1; renderData(el, { tab: me.tab, kind: me.kind, show: me.show }, ctx); };
  addEventListener(SCOPE_EVENT, onScope);
  me.off = () => removeEventListener(SCOPE_EVENT, onScope);

  let quality, colleges, meta;
  try {
    [quality, colleges, meta] = await Promise.all([
      getScoped(ctx, '/quality'),
      getScoped(ctx, '/colleges').then(arr).then((r) => scopeRows(r)),
      ctx.state?.meta ? Promise.resolve(ctx.state.meta) : api.get('/meta'),
    ]);
  } catch (e) {
    if (dataCur !== me) return;
    el.replaceChildren(pageHead(ctx, 'Data quality', null, null, { scope: true }), ui.errorCard({ title: 'Could not load data quality', error: e, retry: () => renderData(el, params, ctx) }));
    return;
  }
  if (dataCur !== me) return;
  const inScope = new Set(colleges.map((c) => String(c.id)));
  // /quality on older servers ignores districts=: keep only colleges in scope
  quality.missing = (quality.missing || []).map((m) => { const ids = (m.college_ids || []).map(String).filter((id) => inScope.has(id)); return { ...m, college_ids: ids, count: ids.length }; });
  me.colleges = colleges; me.meta = meta;
  me.cMap = new Map(colleges.map((c) => [String(c.id), c]));
  me.dName = new Map((meta.districts || []).map((d) => [d.id, d.name]));
  me.quality = quality;
  me.v4 = colleges.some((c) => 'data_status' in c);

  const sync = () => setQuery(ctx, { tab: me.tab === 'verify' ? null : me.tab, kind: me.tab === 'verify' && me.kind !== 'colleges' ? me.kind : null, show: me.tab === 'verify' && me.show !== 'pending' ? me.show : null, page: me.tab === 'verify' && me.page > 1 ? me.page : null });
  const panels = { verify: () => verifyPanel(me, sync), gaps: () => gapsPanel(me), export: () => exportPanel(me) };
  const unver = colleges.filter((c) => c.data_status && c.data_status !== 'verified').length;
  const tabs = ui.tabs({
    tabs: [
      { id: 'verify', label: 'To verify', count: me.v4 ? unver : undefined, render: panels.verify },
      { id: 'gaps', label: 'Missing or doubtful', count: (quality.missing || []).reduce((s, m) => s + (m.count ? 1 : 0), 0), render: panels.gaps },
      { id: 'export', label: 'Download', render: panels.export },
    ],
    active: me.tab,
    onChange: (id) => { me.tab = id; me.page = 1; sync(); },
  });
  el.replaceChildren(
    pageHead(ctx, 'Data quality', 'Check college details and contact numbers against a source, fill in what is missing, and download the data.', null, { scope: true }),
    kpiRow(ctx, dataKpis(me)),
    tabs);
}

function dataKpis(me) {
  const { fmt } = me.ctx;
  const n = me.colleges.length;
  const by = { verified: 0, partly: 0, unverified: 0 };
  for (const c of me.colleges) if (c.data_status) by[c.data_status] = (by[c.data_status] || 0) + 1;
  const bc = me.quality.basis_counts || {};
  const tot = (bc.verified || 0) + (bc.estimated || 0) + (bc.pending || 0);
  const k = [{ label: 'Colleges in view', value: fmt.num(n), sub: 'in the selected districts', icon: 'college' }];
  if (me.v4) {
    k.push({ label: 'Colleges fully verified', value: fmt.num(by.verified), sub: `${fmt.num(by.partly)} partly · ${fmt.num(by.unverified)} not yet`, tone: by.verified ? 'good' : undefined, icon: 'check' });
  }
  // "numbers" here are branch seat / student figures, not phone numbers
  k.push({ label: 'Verified student figures', value: tot ? fmt.pct((bc.verified || 0) / tot) : '—', sub: `${fmt.num(bc.verified || 0)} of ${fmt.num(tot)} branch figures`, icon: 'data' });
  const op = (me.quality.missing || []).find((m) => m.field === 'op_status');
  k.push({ label: 'Still open? To confirm', value: fmt.num(op?.count || 0), sub: 'possibly closed or not known', tone: op?.count ? 'warn' : 'good', icon: 'warn' });
  return k;
}

/* ---------- verification queue ---------- */
function verifyPanel(me, sync) {
  const { ctx } = me;
  const { h, ui } = ctx;
  const host = h('div', { class: 'ad-verify' });
  const seg = (opts, val, onChange, aria) => (typeof ui.segmented === 'function'
    ? ui.segmented({ options: opts, value: val, onChange, ariaLabel: aria })
    : h('div', { class: 'adm-seg', role: 'group', 'aria-label': aria }, opts.map((o) => h('button', { type: 'button', class: ['adm-seg__btn', val === o.value && 'is-on'], 'aria-pressed': String(val === o.value), onClick: () => onChange(o.value) }, o.label))));
  const body = h('div');
  const draw = () => {
    put(host,
      h('div', { class: 'ad-verify__bar' },
        seg([{ value: 'colleges', label: 'College details' }, { value: 'contacts', label: 'Contact numbers' }], me.kind, (v) => { me.kind = v; me.page = 1; sync(); draw(); }, 'What to verify'),
        seg([{ value: 'pending', label: 'Not verified yet' }, { value: 'verified', label: 'Verified' }], me.show, (v) => { me.show = v; me.page = 1; sync(); draw(); }, 'Which records')),
      h('p', { class: 'adm-muted ad-verify__help' }, me.kind === 'colleges'
        ? 'A college detail counts as verified only when someone checked it against a source (official website, AICTE/university listing, a call to the office). Typing a value without a source leaves it unverified.'
        : 'A contact is verified when its number or email was confirmed from an official page or by the college itself.'),
      body);
    if (me.kind === 'colleges') collegeQueue(me, body, sync); else contactQueue(me, body, sync);
  };
  draw();
  return host;
}

const PAGE_V = 15;
function collegeQueue(me, body, sync) {
  const { ctx } = me;
  const { h, ui, api, fmt } = ctx;
  if (!me.v4) {
    put(body, ui.emptyState({ icon: 'warn', title: 'College details cannot be verified here yet', text: 'This server is out of date. Contact numbers can still be verified: choose “Contact numbers” above.' }));
    return;
  }
  const want = me.show === 'verified' ? (c) => c.data_status === 'verified' || c.data_status === 'partly' : (c) => c.data_status !== 'verified';
  const list = me.colleges.filter(want).sort((a, b) => (b.targeted ? 1 : 0) - (a.targeted ? 1 : 0) || (a.sno ?? 0) - (b.sno ?? 0));
  const details = new Map();
  const columns = [
    { key: 'name', label: 'College', primary: true, sortable: false, priority: 1, minWidth: 220, render: (c) => h('div', { class: 'ad-vq-name' }, h('a', { href: `#/college/${c.id}` }, c.short_name || c.name),
      h('span', { class: 'adm-muted' }, [me.dName.get(c.district_id), c.targeted ? 'targeted' : null].filter(Boolean).join(' · '))) },
    { key: 'data_status', label: 'Status', sortable: false, priority: 1, minWidth: 140, render: (c) => statusChip(ctx, c.data_status === 'partly' ? 'unverified' : c.data_status, { label: { verified: 'Verified', partly: 'Partly verified', unverified: 'Not verified' }[c.data_status] }) },
    { key: 'fields', label: 'Details checked', sortable: false, priority: 2, minWidth: 280, render: (c) => fieldChips(me, details.get(String(c.id))) },
    { key: 'last', label: 'Last verified', sortable: false, priority: 3, minWidth: 160, hideOnPhone: true, render: (c) => lastVerified(me, details.get(String(c.id))) },
  ];
  const tbl = dataTable(ctx, { columns, rows: [], loading: true, rowKey: (c) => c.id });
  put(body, tbl);
  const paint = async () => {
    const pages = Math.max(1, Math.ceil(list.length / PAGE_V));
    if (me.page > pages) me.page = pages;
    const rows = list.slice((me.page - 1) * PAGE_V, me.page * PAGE_V);
    tbl.update({ loading: true });
    const need = rows.filter((c) => !details.has(String(c.id)));
    const got = await pool(need, 6, (c) => api.get(`/colleges/${c.id}`));
    need.forEach((c, i) => details.set(String(c.id), got[i]?.college ? { ...got[i].college, field_status: got[i].college.field_status || got[i].field_status } : null));
    if (!body.isConnected) return;
    tbl.update({
      columns, rows, loading: false, total: list.length, page: me.page, pageSize: PAGE_V, rowKey: (c) => c.id,
      onPage: (p) => { me.page = p; sync(); paint(); },
      rowActions: (c) => [{ label: me.show === 'verified' ? 'Verify more' : 'Mark verified', icon: 'check', tone: 'primary', writeOnly: true, hidden: !canWrite(ctx),
        onClick: () => markCollegeVerified(me, c, details.get(String(c.id)), async () => { details.delete(String(c.id)); const r = await getScoped(ctx, '/colleges').then(arr).catch(() => null); if (r) { const m = new Map(r.map((x) => [String(x.id), x])); for (const x of list) Object.assign(x, m.get(String(x.id)) || {}); } paint(); }) }],
      empty: me.show === 'verified'
        ? { title: 'Nothing verified yet', text: 'Colleges appear here once someone marks at least one detail verified with a source.', icon: 'check' }
        : { title: 'Every college in view is verified', text: 'Nice. Widen the district selection to check more colleges.', icon: 'check' },
    });
  };
  paint();
}

function fieldChips(me, d) {
  const { ctx } = me; const { h } = ctx;
  if (!d) return h('span', { class: 'adm-muted' }, 'Could not load');
  const fs = d.field_status || {};
  const vf = parseVF(d.verified_fields);
  return h('div', { class: 'ad-vq-fields' }, VERIFY_FIELDS.filter((f) => f in fs || vf[f]).map((f) => {
    const st = fs[f] || (vf[f] ? 'verified' : 'unverified');
    return h('span', { class: ['ad-vq-f', `is-${st}`], title: st === 'verified' && vf[f] ? `Verified ${vf[f].verified_on || ''} by ${vf[f].verified_by || 'unknown'}${vf[f].source ? ' · ' + vf[f].source : ''}` : st === 'missing' ? 'No value recorded' : 'Has a value but no source yet' },
      h('span', { class: 'ad-vq-f__k' }, label(f)), h('span', { class: 'ad-vq-f__v' }, st === 'verified' ? '✓' : st === 'missing' ? 'missing' : 'not verified'));
  }));
}
function parseVF(v) { if (!v) return {}; if (typeof v === 'object') return v; try { return JSON.parse(v) || {}; } catch { return {}; } }
function lastVerified(me, d) {
  const { h, fmt } = me.ctx;
  const vf = Object.entries(parseVF(d?.verified_fields));
  if (!vf.length) return h('span', { class: 'adm-muted' }, 'Never');
  const [, last] = vf.sort((a, b) => String(b[1]?.verified_on || '').localeCompare(String(a[1]?.verified_on || '')))[0];
  return h('div', { class: 'ad-vq-last' }, h('span', null, fmt.date(last?.verified_on)), h('small', { class: 'adm-muted' }, `by ${last?.verified_by || 'unknown'}`), last?.source ? srcLink(h, last.source, null) : null);
}

function verifyDialog(ctx, { title, intro, fieldsNode, source = '', onSave }) {
  const { h, ui } = ctx;
  const src = h('input', { type: 'url', class: 'td-input', value: safeUrl(source) || '', placeholder: 'https://… (official page, notice or listing)', required: true });
  const date = h('input', { type: 'date', class: 'td-input td-num', value: today(), max: today() });
  const note = h('input', { type: 'text', class: 'td-input', maxlength: 300, placeholder: 'e.g. Confirmed by phone with the office on 6 Nov' });
  const srcErr = errEl(h); const dateErr = errEl(h); const formErr = h('div', { class: 'td-form__error', role: 'alert', hidden: true });
  const body = h('div', { class: 'v-adm ad-vdlg' }, intro ? h('p', null, intro) : null, fieldsNode || null, formErr,
    h('div', { class: 'td-form__grid' },
      field(h, 'Source link', src, 'Where you checked it. Must start with http:// or https://.', { full: true, req: true, err: srcErr }),
      field(h, 'Checked on', date, 'The day you looked at the source.', { req: true, err: dateErr }),
      field(h, 'Note', note, 'Optional.')));
  ui.modal({ title, body, actions: [{ label: 'Cancel', tone: 'ghost' }, { label: 'Mark verified', tone: 'primary', onClick: async () => {
    srcErr.textContent = ''; dateErr.textContent = ''; formErr.hidden = true;
    const s = src.value.trim();
    let bad = false;
    if (!s) { srcErr.textContent = 'Paste the link where you checked this.'; bad = true; } else if (!safeUrl(s)) { srcErr.textContent = 'Use a full link starting with https://'; bad = true; }
    if (!date.value) { dateErr.textContent = 'Pick the date.'; bad = true; } else if (date.value > today()) { dateErr.textContent = 'Cannot be in the future.'; bad = true; }
    if (bad) { (srcErr.textContent ? src : date).focus(); return false; }
    if (!(await writeOk(ctx))) return false;
    const n = [note.value.trim(), date.value !== today() ? `checked on ${date.value}` : ''].filter(Boolean).join(' · ');
    try { await onSave({ source: s, date: date.value, note: n || undefined }); } catch (e) {
      formErr.textContent = [e.message, ...Object.values(e.fields || {})].filter(Boolean).join(' — '); formErr.hidden = false; return false;
    }
    return true;
  } }] });
}

function markCollegeVerified(me, c, d, done) {
  const { ctx } = me; const { h, ui, api } = ctx;
  const fs = d?.field_status || {};
  const can = VERIFY_FIELDS.filter((f) => fs[f] && fs[f] !== 'missing');
  if (!can.length) { ui.toast('This college has no recorded details to verify yet. Open the college and fill them in first.', 'warn'); return; }
  const boxes = can.map((f) => { const cb = h('input', { type: 'checkbox', class: 'td-check', value: f, checked: fs[f] !== 'verified' }); return { f, cb, node: h('label', { class: 'adm-toggle ad-vdlg__f' }, cb, h('span', null, label(f), ': ', h('strong', null, fieldValue(me, d, f)), fs[f] === 'verified' ? h('small', { class: 'adm-muted' }, ' (already verified)') : null)) }; });
  const fErr = errEl(h);
  verifyDialog(ctx, {
    title: `Verify details — ${c.short_name || c.name}`,
    intro: 'Tick the details you checked against the source. Each ticked detail is stamped with your name, the date and the link.',
    fieldsNode: h('fieldset', { class: 'ad-vdlg__fs' }, h('legend', null, 'Details checked'), boxes.map((b) => b.node), fErr),
    source: d?.website,
    onSave: async ({ source, note }) => {
      const fields = boxes.filter((b) => b.cb.checked).map((b) => b.f);
      if (!fields.length) { fErr.textContent = 'Tick at least one detail.'; throw Object.assign(new Error('Tick at least one detail.'), { fields: {} }); }
      await api.post(`/colleges/${c.id}/verify`, { fields, source, note, verified: true });
      ui.toast(`${fields.length} detail${fields.length === 1 ? '' : 's'} of ${c.short_name || c.name} marked verified`, 'good');
      done();
    },
  });
}
function fieldValue(me, d, f) {
  const v = d?.[f];
  if (f === 'district_id') return me.dName.get(v) || v || '—';
  if (f === 'city_id') return (me.meta.cities || []).find((x) => x.id === v)?.name || v || '—';
  return v == null || v === '' ? '—' : String(v);
}

function contactQueue(me, body, sync) {
  const { ctx } = me;
  const { h, ui, api, fmt } = ctx;
  let list = [];
  const columns = [
    { key: 'name', label: 'Contact', primary: true, sortable: false, priority: 1, minWidth: 200, render: (k) => h('div', { class: 'ad-vq-name' }, h('strong', null, k.name || 'No name recorded'), h('span', { class: 'adm-muted' }, CONTACT_ROLE_LABEL[k.role] || String(k.role || '').replace(/_/g, ' '))) },
    { key: 'college', label: 'College', sortable: false, priority: 2, minWidth: 180, render: (k) => h('div', { class: 'ad-vq-name' }, h('a', { href: `#/college/${k.college_id}?tab=contacts` }, k.college_label || k.college_id), h('span', { class: 'adm-muted' }, me.dName.get(k.district_id) || '')) },
    { key: 'reach', label: 'Phone / email', sortable: false, priority: 1, minWidth: 200, render: (k) => contactActions(ctx, k.phone, k.email, { name: k.name }) },
    { key: 'basis', label: 'Verified?', sortable: false, priority: 2, minWidth: 130, render: (k) => verifiedBadge(ctx, { state: k.basis === 'verified' ? 'verified' : 'unverified', source: k.source_url, date: k.verified_on, by: k.verified_by }) },
    { key: 'src', label: me.show === 'verified' ? 'Verified by' : 'Found at', sortable: false, priority: 3, minWidth: 180, hideOnPhone: true, render: (k) => h('div', { class: 'ad-vq-last' },
      me.show === 'verified' ? h('span', null, k.verified_by ? `${k.verified_by}${k.verified_on ? ', ' + fmt.date(k.verified_on) : ''}` : 'Not recorded') : null,
      srcLink(h, k.source_url, null) || h('span', { class: 'adm-muted' }, 'no link')) },
  ];
  const tbl = dataTable(ctx, { columns, rows: [], loading: true, rowKey: (k) => k.id });
  put(body, tbl);
  const paint = () => {
    const pages = Math.max(1, Math.ceil(list.length / PAGE_V));
    if (me.page > pages) me.page = pages;
    tbl.update({
      columns, rows: list.slice((me.page - 1) * PAGE_V, me.page * PAGE_V), loading: false, total: list.length, page: me.page, pageSize: PAGE_V, rowKey: (k) => k.id,
      onPage: (p) => { me.page = p; sync(); paint(); },
      rowActions: (k) => (k.basis === 'verified' ? [] : [{ label: 'Mark verified', icon: 'check', tone: 'primary', writeOnly: true, hidden: !canWrite(ctx), onClick: () => verifyDialog(ctx, {
        title: `Verify contact — ${k.name || k.college_label}`,
        intro: h('span', null, h('strong', null, [k.name, k.phone, k.email].filter(Boolean).join(' · ')), ` at ${k.college_label}. Confirm the number or email against an official page, or by calling the college.`),
        source: k.source_url,
        onSave: async ({ source, note }) => {
          const notes = note ? [k.notes, `[${today()}] Verified: ${note}`].filter(Boolean).join('\n') : undefined;
          await api.patch(`/contacts/${k.id}`, { basis: 'verified', source_url: source, ...(notes ? { notes } : {}) });
          ui.toast(`${k.name || 'Contact'} marked verified`, 'good');
          load();
        },
      }) }]),
      empty: me.show === 'verified'
        ? { title: 'No verified contacts in view', text: 'Contacts marked verified appear here with who checked them and when.', icon: 'phone' }
        : { title: 'Every contact in view is verified', text: 'Widen the district selection to check more.', icon: 'check' },
    });
  };
  const load = async () => {
    tbl.update({ loading: true });
    try {
      list = scopeRows(arr(await getScoped(ctx, '/contacts', { basis: me.show === 'verified' ? 'verified' : 'pending' })));
      list.sort((a, b) => String(b.verified_on || '').localeCompare(String(a.verified_on || '')) || String(a.college_label).localeCompare(String(b.college_label)));
      if (body.isConnected) paint();
    } catch (e) { tbl.update({ loading: false, error: e, onRetry: load, rows: [] }); }
  };
  load();
}

/* ---------- gaps & checks ---------- */
function gapsPanel(me) {
  const { ctx, colleges, quality, cMap, dName } = me;
  const { h, ui, api, fmt } = ctx;
  const bc = quality.basis_counts || {};
  const total = (bc.verified || 0) + (bc.estimated || 0) + (bc.pending || 0);
  const bars = h('div', { class: 'ad-bars' }, [['verified', 'Verified', 'from an official or first-hand source'], ['estimated', 'Estimated', 'worked out from other numbers, e.g. strength = intake × 4'], ['pending', 'Pending', 'not known yet']].map(([k, l, help]) =>
    h('div', { class: 'ad-bar-row' },
      h('div', { class: 'ad-bar-row__label' }, h('strong', null, l), h('span', { class: 'adm-muted' }, help)),
      h('div', { class: 'ad-bar', role: 'img', 'aria-label': `${l}: ${fmt.num(bc[k] || 0)} values (${total ? fmt.pct((bc[k] || 0) / total) : '0%'})` },
        h('i', { class: `t-${k}`, style: { width: total ? `${(bc[k] || 0) / total * 100}%` : '0' } })),
      h('span', { class: 'ad-bar-row__n td-num' }, fmt.num(bc[k] || 0), h('small', { class: 'adm-muted' }, total ? ` ${fmt.pct((bc[k] || 0) / total)}` : '')))));

  const collegeLinks = (ids, max = 12) => {
    const list = (ids || []).map(String);
    const box = h('div', { class: 'adm-chips' });
    const fill = (n) => put(box, list.slice(0, n).map((id) => h('a', { class: 'adm-chip', href: `#/college/${id}`, title: cMap.get(id)?.name || id }, cMap.get(id)?.short_name || cMap.get(id)?.name || id)),
      list.length > n ? h('button', { type: 'button', class: 'adm-chip adm-chip--more', onClick: () => fill(list.length) }, `+${list.length - n} more`) : null);
    fill(max);
    return box;
  };
  const missing = [...(quality.missing || [])].filter((m) => m.count).sort((a, b) => b.count - a.count);
  const missingTable = missing.length ? ui.table({
    columns: [
      { key: 'label', label: 'What is missing', render: (r) => h('strong', null, r.label) },
      { key: 'count', label: 'Colleges', align: 'right' },
      { key: 'college_ids', label: 'Open a college to fix it', sortable: false, render: (r) => collegeLinks(r.college_ids, 10) },
    ],
    rows: missing.map((m) => ({ ...m, label: m.label || label(m.field) })),
  }) : ui.emptyState({ title: 'Nothing is missing', icon: 'check', text: 'Every tracked field has a value for the colleges in view.' });

  // operating status review
  const review = colleges.filter((c) => c.op_status === 'possibly_closed' || c.op_status === 'pending');
  const reviewBox = h('div', { class: 'ad-review' }, ui.skeleton(2, { card: false }));
  const drawReview = async () => {
    if (!review.length) { reviewBox.replaceChildren(ui.emptyState({ title: 'Nothing to review', icon: 'check', text: 'No college in view is marked “possibly closed” or “pending”.' })); return; }
    const details = await pool(review, 6, (c) => api.get(`/colleges/${c.id}`));
    let shown = 10;
    const paint = () => reviewBox.replaceChildren(h('ul', { class: 'adm-list' }, review.slice(0, shown).map((c, i) => {
      const d = details[i]?.college || {};
      return h('li', { class: 'adm-list__row ad-review-row' },
        h('div', { class: 'ad-review-main' },
          h('div', { class: 'ad-review-title' }, h('a', { href: `#/college/${c.id}` }, c.name), ui.statusBadge('op_status', c.op_status), h('span', { class: 'adm-muted' }, dName.get(c.district_id) || '')),
          h('p', { class: 'ad-evidence' }, d.op_status_note || 'No evidence recorded yet.'),
          h('div', { class: 'ad-review-meta' },
            srcLink(h, d.op_status_source),
            (d.op_2025_26 || d.op_2026_27) ? h('span', { class: 'adm-muted' }, `Admissions 2025-26: ${d.op_2025_26 || 'unknown'} · 2026-27: ${d.op_2026_27 || 'unknown'}`) : null)),
        canWrite(ctx) ? h('div', { class: 'ad-review-actions' },
          ui.button({ label: 'Still operating', icon: 'check', size: 'sm', onClick: () => setOp(c, 'operational') }),
          ui.button({ label: 'Closed', tone: 'danger', size: 'sm', onClick: () => setOp(c, 'closed') })) : null);
    })), review.length > shown ? h('div', { class: 'ad-more' }, ui.button({ label: `Show all ${review.length}`, onClick: () => { shown = review.length; paint(); } })) : null);
    paint();
  };
  const setOp = async (c, status) => {
    const note = h('textarea', { class: 'td-input', rows: 3, placeholder: 'How do you know? e.g. "Called the office on 3 Nov; admissions open for 2026-27"' });
    const src = h('input', { type: 'url', class: 'td-input', placeholder: 'https://… (optional)' });
    const noteErr = errEl(h); const srcErr = errEl(h);
    const body = h('div', { class: 'v-adm' }, h('p', null, 'Mark ', h('strong', null, c.name), ' as ', h('strong', null, status === 'closed' ? 'closed' : 'operational'), '?'),
      status === 'closed' ? h('p', { class: 'ad-warnline' }, 'Closed colleges drop out of the call queue and the planner.') : null,
      h('div', { class: 'td-form__grid' }, field(h, 'Evidence', note, null, { full: true, req: true, err: noteErr }), field(h, 'Source link', src, 'With a link, the status is stamped verified.', { full: true, err: srcErr })));
    ui.modal({ title: 'Update operating status', body, actions: [{ label: 'Cancel', tone: 'ghost' }, { label: status === 'closed' ? 'Mark closed' : 'Save', tone: status === 'closed' ? 'danger' : 'primary', onClick: async () => {
      noteErr.textContent = ''; srcErr.textContent = '';
      if (!note.value.trim()) { noteErr.textContent = 'Add a short note so others can see why this changed.'; note.focus(); return false; }
      const s = src.value.trim();
      if (s && !safeUrl(s)) { srcErr.textContent = 'Use a full link starting with https://, or leave it empty.'; src.focus(); return false; }
      if (!(await writeOk(ctx))) return false;
      await api.patch(`/colleges/${c.id}`, { op_status: status, op_status_note: `${note.value.trim()} [${today()}]`, ...(s ? { op_status_source: s, sources: { op_status: s } } : {}) });
      ui.toast(`${c.name} marked ${status === 'closed' ? 'closed' : 'operational'}`, 'good');
      renderData(me.el, { tab: 'gaps' }, ctx);
    } }] });
  };

  const pendingGeo = colleges.filter((c) => c.geo_precision === 'pending' || c.lat == null || c.lng == null);
  const approxGeo = colleges.filter((c) => c.geo_precision === 'town' || c.geo_precision === 'district');
  const host = h('div', { class: 'ad-gaps' },
    h('div', { class: 'ad-grid' },
      ui.section({ title: 'How reliable are our numbers?', sub: `${fmt.num(total)} branch figures (intake, strength, final year, eligible)`, body: bars }),
      ui.section({ title: 'Map locations', body: h('div', { class: 'ad-geo' },
        h('div', { class: 'ad-geo__n' }, h('strong', { class: 'td-num' }, fmt.num(colleges.length - pendingGeo.length)), h('span', { class: 'adm-muted' }, ` of ${fmt.num(colleges.length)} colleges are on the map`)),
        approxGeo.length ? h('p', { class: 'adm-muted' }, `${fmt.num(approxGeo.length)} are placed at town or district level (approximate pins).`) : null,
        pendingGeo.length ? h('div', null, h('p', { class: 'adm-muted' }, 'Missing a location:'), collegeLinks(pendingGeo.map((c) => c.id), 20)) : h('p', { class: 'ad-ok' }, ui.icon('check', { size: 16 }), 'Every college in view has a map location.')) })),
    ui.section({ title: `Is the college still operating? (${review.length})`, sub: 'Colleges marked “possibly closed” or “pending”. Check the evidence and confirm.', body: reviewBox }),
    ui.section({ title: 'Missing details', sub: 'Sorted by how many colleges are affected. Open a college to fill the gap.', body: missingTable }));
  drawReview();
  return host;
}

/* ---------- export ---------- */
function exportPanel(me) {
  const { ctx, colleges, dName, meta } = me;
  const { h, ui, api } = ctx;
  const exportBtn = (lbl, fn, tone) => {
    const b = ui.button({ label: lbl, icon: 'data', size: 'sm', tone });
    b.addEventListener('click', async () => {
      b.disabled = true; b.classList.add('is-busy');
      try { await fn(); } catch (e) { ui.toast(`Download failed: ${e.message}`, 'bad'); } finally { b.disabled = false; b.classList.remove('is-busy'); }
    });
    return b;
  };
  const getAll = async (res) => {
    const p = res === 'people' ? { page_size: 200 } : { limit: 5000 };
    const first = await api.get(`/${res}`, p);
    if (first && !Array.isArray(first) && Array.isArray(first.items) && first.total > first.items.length) {
      const out = [...first.items];
      for (let pg = 2; out.length < first.total && pg < 200; pg++) out.push(...arr(await api.get(`/${res}`, { page: pg, page_size: 200 })));
      return out;
    }
    return arr(first);
  };
  const backup = async () => {
    const names = ['branches', 'people', 'targets', 'enrollments', 'activities', 'followups', 'exams', 'contacts'];
    const parts = await Promise.all(names.map((n) => (n === 'followups' || n === 'exams' ? api.get(`/${n}`).then(arr) : getAll(n))));
    const audit = arr(await api.get('/audit', { limit: 1000 }));
    const allColleges = arr(await api.get('/colleges'));
    const data = { exported_at: new Date().toISOString(), exported_by: api.user || null, today: meta.today, demo_data_present: !!meta.demo,
      settings: meta.settings, courses: meta.courses, districts: meta.districts, cities: meta.cities, colleges: allColleges,
      ...Object.fromEntries(names.map((n, i) => [n, parts[i]])), audit_latest_1000: audit };
    download(`techdrona-backup-${today()}.json`, JSON.stringify(data, null, 1), 'application/json');
    ui.toast('Backup downloaded', 'good');
  };
  return h('div', { class: 'ad-tools' },
    h('div', { class: 'ad-tool' },
      h('h2', null, 'Spreadsheets (CSV)'),
      h('p', { class: 'adm-muted' }, 'Open in Excel or Google Sheets. Numbers are exactly what the portal shows, with whether each is verified, estimated or not known yet. The colleges file covers the selected districts; the others cover everything.'),
      h('div', { class: 'ad-tool__btns' },
        exportBtn(`Colleges in view (${colleges.length})`, () => download(`techdrona-colleges-${today()}.csv`, collegesCsv(colleges, dName), 'text/csv;charset=utf-8'), 'primary'),
        EXPORTS.map(([res, lbl]) => exportBtn(lbl, async () => {
          const rows = res === 'courses' ? (meta.courses || []) : await getAll(res);
          if (!rows.length) { ui.toast(`No ${lbl.toLowerCase()} recorded yet`, 'info'); return; }
          download(`techdrona-${res}-${today()}.csv`, csvOf(rows, colsOf(rows)), 'text/csv;charset=utf-8');
        })))),
    h('div', { class: 'ad-tool' },
      h('h2', null, 'Full backup (JSON)'),
      h('p', { class: 'adm-muted' }, 'Everything in one file: colleges, team, targets, enrollments, follow-ups, contacts, exams and the latest 1,000 audit entries. Keep it somewhere safe; it contains phone numbers.'),
      h('div', { class: 'ad-tool__btns' }, exportBtn('Download backup', backup))),
    // (the old "Research data" card only said "ask an admin to re-import on the server": no action here, so it is gone)
    h('div', { class: ['ad-tool', meta.demo && 'is-warn'] },
      h('h2', null, 'Demo data'),
      meta.demo
        ? h('p', null, h('strong', null, 'Demo records are present. '), 'They are marked “DEMO” and are not real. Ask an admin to remove them before trusting any totals.')
        : h('p', { class: 'adm-muted' }, 'No demo records. Every number comes from real entries.')));
}

// =================================================================== #/audit
export async function renderAudit(el, params = {}, ctx) {
  const { h, ui, api, fmt } = ctx;
  shell(el, ctx, 'v-adm-audit', 'Audit log');
  const PAGE = 50;
  const q0 = { ...getQuery(), ...params };
  const f = { entity: PLURAL_TO_ENTITY[q0.entity] || q0.entity || '', entity_id: q0.entity_id || '', actor: q0.actor || '', action: q0.action || '', from: q0.from || '', to: q0.to || '' };
  let page = Math.max(1, Number(q0.page) || 1);
  let rows = []; let more = false; let actors = [];
  const parse = (v) => { if (v == null || typeof v === 'object') return v; try { return JSON.parse(v); } catch { return v; } };
  const sync = () => setQuery(ctx, { ...f, page: page > 1 ? page : null });
  const fetchPage = async () => {
    const q = { limit: PAGE + 1, offset: (page - 1) * PAGE };
    for (const k of Object.keys(f)) if (f[k]) q[k] = f[k];
    const got = arr(await api.get('/audit', q)).map((r) => ({ ...r, before: parse(r.before), after: parse(r.after) }));
    more = got.length > PAGE;
    return got.slice(0, PAGE);
  };
  const loadActors = async () => {
    try { const a = await api.get('/audit/actors'); if (Array.isArray(a)) return [...new Set(a.map((x) => (typeof x === 'string' ? x : x.actor)).filter(Boolean))].sort(); } catch { /* older server */ }
    try { return [...new Set(arr(await api.get('/audit', { limit: 1000 })).map((r) => r.actor).filter(Boolean))].sort(); } catch { return []; }
  };
  try { [rows, actors] = await Promise.all([fetchPage(), loadActors()]); } catch (e) {
    if (e.fields && (e.fields.from || e.fields.to)) { f.from = ''; f.to = ''; sync(); return renderAudit(el, {}, ctx); }
    el.replaceChildren(ui.errorCard({ title: 'Could not load the audit log', error: e, retry: () => renderAudit(el, params, ctx) }));
    return;
  }
  const everEmpty = !rows.length && page === 1 && !Object.values(f).some(Boolean);
  const host = h('div', { class: 'ad-audit-host', 'aria-live': 'polite' });
  const dateErr = h('div', { class: 'td-field__error', 'aria-live': 'polite' });
  const reload = async ({ resetPage = true } = {}) => {
    if (resetPage) page = 1;
    dateErr.textContent = '';
    if (f.from && f.to && f.from > f.to) { dateErr.textContent = '“From” is after “To”.'; return; }
    sync();
    host.setAttribute('aria-busy', 'true');
    try { rows = await fetchPage(); draw(); } catch (e) { put(host, ui.errorCard({ title: 'Could not load changes', error: e, retry: reload })); }
    host.removeAttribute('aria-busy');
  };
  const sel = (lbl, opts, key) => {
    const s = h('select', { class: 'td-input td-select', 'aria-label': lbl, onChange: (e) => { f[key] = e.target.value; reload(); } }, opts.map(([v, l]) => h('option', { value: v }, l)));
    s.value = f[key];
    return h('label', { class: 'adm-inline' }, h('span', null, lbl), s);
  };
  const dateIn = (lbl, key) => h('label', { class: 'adm-inline' }, h('span', null, lbl),
    h('input', { type: 'date', class: 'td-input td-num', value: f[key], max: today(), onChange: (e) => { f[key] = e.target.value; reload(); } }));
  let t;
  const idIn = h('label', { class: 'adm-inline' }, h('span', null, 'One record'), h('input', { type: 'search', class: 'td-input', placeholder: 'e.g. c6 or 12', value: f.entity_id, 'aria-label': 'Record reference',
    onInput: (e) => { clearTimeout(t); t = setTimeout(() => { f.entity_id = e.target.value.trim(); reload(); }, 300); } }));
  const entLabel = Object.fromEntries(ENTITIES);
  const SINGULAR = { person: 'Person', followup: 'Follow-up', activity: 'Activity', branch: 'Branch' };
  const entName = (e) => SINGULAR[e] || (entLabel[e] || label(e)).replace(/ies$/, 'y').replace(/s$/, '');
  const changed = (r) => {
    const b = r.before && typeof r.before === 'object' ? r.before : {};
    const a = r.after && typeof r.after === 'object' ? r.after : {};
    return [...new Set([...Object.keys(b), ...Object.keys(a)])].filter((k) => !['updated_at', 'updated_by', 'created_at', 'created_by'].includes(k) && JSON.stringify(b[k]) !== JSON.stringify(a[k]));
  };
  const recordName = (r) => {
    const o = (r.after && typeof r.after === 'object' ? r.after : null) || (r.before && typeof r.before === 'object' ? r.before : {}) || {};
    return o.name || o.full_name || o.title || o.student_name || (r.entity === 'setting' ? label(r.entity_id) : '') || (r.entity === 'target' && o.scope_type ? `${o.scope_type} ${o.scope_id}` : '') || (r.entity === 'exam' && o.semester ? `${o.college_id} · ${o.semester}` : '');
  };
  const recordHref = (r) => {
    const id = r.entity_id;
    if (r.entity === 'college') return `#/college/${id}`;
    if (r.entity === 'person') return `#/person/${id}`;
    const o = r.after || r.before || {};
    if (r.entity === 'branch' && o.college_id) return `#/college/${o.college_id}?tab=branches&branch=${id}`;
    if (o && o.college_id) return `#/college/${o.college_id}`;
    return null;
  };
  const tone = { create: 'good', update: 'info', delete: 'bad' };
  const actLabel = { create: 'Added', update: 'Changed', delete: 'Deleted' };
  const local = (at) => { const d = new Date(at); return Number.isNaN(d.getTime()) ? null : d; };
  const dayOf = (at) => { const d = local(at); return d ? d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : fmt.date(at); };
  const timeOf = (at) => { const d = local(at); return d ? d.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' }) : ''; };
  const when = (at) => h('span', { class: 'ad-when', title: at }, dayOf(at), h('small', { class: 'adm-muted' }, ` ${timeOf(at)}`));
  const BOOL_KEYS = new Set(['targeted', 'active', 'is_relevant', 'autonomous', 'is_demo', 'confirms_participation']);
  /** human-readable value for the diff */
  const show = (k, v) => {
    if (v === undefined) return h('span', { class: 'adm-muted' }, '—');
    if (v === null || v === '') return h('span', { class: 'adm-muted' }, 'empty');
    if (BOOL_KEYS.has(k) || typeof v === 'boolean') return v === true || v === 1 || v === '1' ? 'Yes' : 'No';
    if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) return fmt.date(v);
    if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return `${dayOf(v)} ${timeOf(v)}`;
    if (typeof v === 'number') return Number.isInteger(v) ? fmt.num(v) : String(v);
    if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === 'object' ? JSON.stringify(x) : String(x))).join(', ') : h('span', { class: 'adm-muted' }, 'none');
    if (typeof v === 'object') {
      if (!Object.keys(v).length) return h('span', { class: 'adm-muted' }, 'none');
      return h('ul', { class: 'ad-diff__obj' }, Object.entries(v).map(([kk, vv]) => h('li', null, h('span', { class: 'adm-muted' }, `${label(kk)}: `),
        vv && typeof vv === 'object' && !Array.isArray(vv) ? Object.entries(vv).map(([a, b]) => `${label(a)} ${b ?? '—'}`).join(' · ') : Array.isArray(vv) ? vv.join(', ') : String(vv ?? '—'))));
    }
    const s = String(v);
    if (/^https?:\/\//.test(s)) return srcLink(h, s, s.length > 60 ? s.slice(0, 57) + '…' : s);
    return s.length > 400 ? h('span', { title: s }, s.slice(0, 400) + '…') : s;
  };

  function draw() {
    if (everEmpty) {
      put(host, ui.emptyState({ title: 'No changes recorded yet', icon: 'audit', text: 'Whenever someone adds, edits or deletes anything — a target, an exam date, a team member — it appears here with their name and exactly what changed.' }));
      return;
    }
    put(host,
      rows.length ? ui.dataTable({
        caption: 'Changes, newest first',
        rowKey: (r) => r.id ?? `${r.at}|${r.entity}|${r.entity_id}`,
        // phones / narrow panels: one compact card per change: the record, then "who · when", the action as a badge
        cardSubtitle: (r) => `${r.actor || 'unknown'} · ${dayOf(r.at)} ${timeOf(r.at)}`,
        cardMeta: (r) => ui.badge(actLabel[r.action] || r.action, tone[r.action] || 'neutral'),
        columns: [
          { key: 'at', label: 'When', sortable: false, priority: 1, minWidth: 170, cardHidden: true, render: (r) => when(r.at) },
          { key: 'actor', label: 'Who', sortable: false, priority: 2, minWidth: 140, cardHidden: true, render: (r) => r.actor || '—' },
          { key: 'action', label: 'What', sortable: false, priority: 1, minWidth: 110, cardHidden: true, render: (r) => ui.badge(actLabel[r.action] || r.action, tone[r.action] || 'neutral') },
          { key: 'entity', label: 'Record', primary: true, sortable: false, priority: 1, minWidth: 260, render: (r) => {
            const href = recordHref(r); const nm = recordName(r);
            return h('span', { class: 'ad-rec' }, h('span', { class: 'adm-muted' }, entName(r.entity)),
              href ? h('a', { href }, nm || `#${r.entity_id}`) : h('strong', null, nm || `#${r.entity_id ?? ''}`));
          } },
          { key: 'fields', label: 'Changed', sortable: false, priority: 3, minWidth: 200, render: (r) => {
            const c = changed(r);
            if (r.action !== 'update') return h('span', { class: 'adm-muted' }, r.action === 'create' ? 'new record' : 'record removed');
            return c.length ? h('span', { class: 'ad-fields' }, c.slice(0, 3).map(label).join(', '), c.length > 3 ? h('span', { class: 'adm-muted' }, ` +${c.length - 3} more`) : null) : h('span', { class: 'adm-muted' }, 'no visible change');
          } },
        ],
        rows,
        onRowClick: (r) => showDiff(r),
        mobile: 'cards',
      }) : ui.emptyState({ title: page > 1 ? 'No more changes' : 'No changes match these filters', icon: 'filter', text: 'Clear a filter or pick a wider date range.',
        action: { label: 'Clear filters', icon: 'close', onClick: () => { for (const k of Object.keys(f)) f[k] = ''; page = 1; sync(); renderAudit(el, {}, ctx); } } }),
      (page > 1 || more) ? h('nav', { class: 'opk-pager ad-pager', 'aria-label': 'Pages' },
        h('span', { class: 'adm-muted' }, `Changes ${fmt.num((page - 1) * PAGE + 1)}–${fmt.num((page - 1) * PAGE + rows.length)} (newest first)`),
        ui.button({ label: 'Newer', size: 'sm', disabled: page <= 1, onClick: () => { page -= 1; reload({ resetPage: false }); } }),
        h('span', { class: 'adm-muted' }, `Page ${page}`),
        ui.button({ label: 'Older', size: 'sm', disabled: !more, onClick: () => { page += 1; reload({ resetPage: false }); } })) : null);
  }
  function showDiff(r) {
    const b = r.before && typeof r.before === 'object' ? r.before : {};
    const a = r.after && typeof r.after === 'object' ? r.after : {};
    const keys = [...new Set([...Object.keys(b), ...Object.keys(a)])];
    const ch = new Set(changed(r));
    let onlyChanged = r.action === 'update';
    let raw = false;
    const tbl = h('div');
    const fill = () => {
      if (raw) { tbl.replaceChildren(h('pre', { class: 'ad-raw' }, JSON.stringify({ before: r.before, after: r.after }, null, 2))); return; }
      const ks = keys.filter((k) => !onlyChanged || ch.has(k));
      tbl.replaceChildren(h('div', { class: 'ad-diff' },
        ks.map((k) => h('div', { class: ['ad-diff__row', ch.has(k) && 'is-changed'] },
          h('div', { class: 'ad-diff__key', title: k }, label(k)),
          r.action !== 'create' ? h('div', { class: 'ad-diff__before' }, h('span', { class: 'ad-diff__tag' }, 'Before'), show(k, b[k])) : null,
          r.action !== 'delete' ? h('div', { class: 'ad-diff__after' }, h('span', { class: 'ad-diff__tag' }, 'After'), show(k, a[k])) : null)),
        !ks.length ? h('p', { class: 'adm-muted' }, 'No fields to show.') : null));
    };
    fill();
    const href = recordHref(r);
    const body = h('div', { class: 'v-adm ad-diffwrap' },
      ui.kv([['Who', r.actor || 'unknown'], ['When', `${dayOf(r.at)} at ${timeOf(r.at)}`], ['What', `${actLabel[r.action] || r.action} ${entName(r.entity).toLowerCase()}`],
        ['Record', href ? h('a', { href }, recordName(r) || `#${r.entity_id}`) : (recordName(r) || `#${r.entity_id ?? ''}`)]]),
      h('div', { class: 'ad-diff__opts' },
        r.action === 'update' ? h('label', { class: 'adm-toggle' }, h('input', { type: 'checkbox', class: 'td-check', checked: true, onChange: (e) => { onlyChanged = e.target.checked; fill(); } }), h('span', null, `Only the ${ch.size} changed field${ch.size === 1 ? '' : 's'}`)) : null,
        // the raw JSON is for developers only (?dev=1, same switch as the style guide)
        devMode() ? h('label', { class: 'adm-toggle' }, h('input', { type: 'checkbox', class: 'td-check', onChange: (e) => { raw = e.target.checked; fill(); } }), h('span', null, 'Show raw data')) : null),
      tbl);
    ui.drawer({ title: 'Change details', body });
  }

  const activeFilters = Object.values(f).some(Boolean);
  put(el,
    pageHead(ctx, 'Audit log', 'Every change is recorded with who made it and when. Open any row to see exactly what changed, before and after.'),
    everEmpty ? null : narrowWrap(h('div', { class: 'adm-toolbar ad-audit-filters' }, h('div', { class: 'adm-toolbar__filters' },
      sel('Record type', [['', 'All record types'], ...ENTITIES], 'entity'),
      sel('Action', [['', 'Any action'], ['create', 'Added'], ['update', 'Changed'], ['delete', 'Deleted']], 'action'),
      sel('Changed by', [['', 'Anyone'], ...actors.map((x) => [x, x]), ...(f.actor && !actors.includes(f.actor) ? [[f.actor, f.actor]] : [])], 'actor'),
      // record ids (c6, 12) mean nothing to people: the box only shows when a link opened the log for one record
      f.entity_id ? idIn : null, dateIn('From', 'from'), dateIn('To', 'to'), dateErr),
    activeFilters ? h('div', { class: 'adm-toolbar__end' }, ui.button({ label: 'Clear filters', icon: 'close', tone: 'ghost', size: 'sm', onClick: () => { for (const k of Object.keys(f)) f[k] = ''; page = 1; sync(); renderAudit(el, {}, ctx); } })) : null)),
    host);
  /** On phones the filters would fill the first screen; tuck them behind a disclosure. */
  function narrowWrap(node) {
    if ((el.clientWidth || innerWidth) >= 760) return node;
    return h('details', { class: 'ad-filt', open: activeFilters || undefined }, h('summary', null, ui.icon('filter', { size: 16 }), activeFilters ? 'Filters (on)' : 'Filter changes'), node);
  }
  draw();
}

// =================================================================== #/settings
export async function renderSettings(el, params, ctx) {
  const { h, ui, api, fmt } = ctx;
  shell(el, ctx, 'v-adm-settings', 'Settings');
  let meta; let program = null; let session = null;
  try {
    [meta, program, session] = await Promise.all([
      api.get('/meta'),
      api.get('/program').catch(() => null),
      api.get('/session').catch(() => null),
    ]);
  } catch (e) {
    el.replaceChildren(ui.errorCard({ title: 'Could not load settings', error: e, retry: () => renderSettings(el, params, ctx) }));
    return;
  }
  const s = meta.settings || {};
  const busy = async (btn, fn) => { btn.disabled = true; btn.classList.add('is-busy'); try { await fn(); } finally { btn.disabled = false; btn.classList.remove('is-busy'); } };
  const writable = canWrite(ctx);

  /* --- programme --- */
  const programBody = program ? programSection(ctx, program, () => renderSettings(el, params, ctx)) : h('p', { class: 'adm-muted' }, 'This server does not expose the programme settings yet.');

  /* --- you & access --- */
  const you = accessSection(ctx, meta, session);

  /* --- appearance --- */
  const curTheme = (() => { try { return localStorage.getItem('td.theme') || 'system'; } catch { return 'system'; } })();
  const theme = h('div', { class: 'adm-seg', role: 'radiogroup', 'aria-label': 'Theme' }, [['light', 'Light'], ['dark', 'Dark'], ['system', 'Match device']].map(([v, l]) =>
    h('button', { type: 'button', role: 'radio', 'aria-checked': String(curTheme === v), class: ['adm-seg__btn', curTheme === v && 'is-on'], onClick: (e) => {
      try { v === 'system' ? localStorage.removeItem('td.theme') : localStorage.setItem('td.theme', v); } catch { /* ignore */ }
      const eff = v === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : v;
      document.documentElement.setAttribute('data-theme', eff);
      window.dispatchEvent(new CustomEvent('td:theme', { detail: v }));
      for (const b of theme.children) { b.classList.toggle('is-on', b === e.currentTarget); b.setAttribute('aria-checked', String(b === e.currentTarget)); }
    } }, l)));
  const writeOkLocal = () => writeOk(ctx);

  /* --- courses --- */
  const coursesHost = h('div');
  const reloadCourses = async () => { try { const m = await api.get('/meta'); drawCourses(m.courses || []); } catch (e) { ui.toast(e.message, 'bad'); } };
  const drawCourses = (courses) => {
    const rows = courses.map((c) => {
      const nm = h('input', { type: 'text', class: 'td-input td-input--sm', value: c.name, 'aria-label': `Name of ${c.name}` });
      const pr = h('input', { type: 'number', min: 0, step: 1, inputmode: 'numeric', class: 'td-input td-input--sm td-num ad-price', value: c.price_inr ?? '', 'aria-label': `Price of ${c.name} in rupees` });
      const ac = h('input', { type: 'checkbox', class: 'td-check', checked: !!c.active });
      const err = h('div', { class: 'td-field__error', 'aria-live': 'polite' });
      const saveBtn = ui.button({ label: 'Save', size: 'sm' });
      const dirty = () => nm.value.trim() !== c.name || String(pr.value) !== String(c.price_inr ?? '') || ac.checked !== !!c.active;
      const mark = () => { saveBtn.classList.toggle('td-btn--primary', dirty()); saveBtn.classList.toggle('td-btn--secondary', !dirty()); };
      [nm, pr, ac].forEach((x) => x.addEventListener('input', mark));
      ac.addEventListener('change', mark);
      saveBtn.addEventListener('click', () => busy(saveBtn, async () => {
        err.textContent = '';
        if (!nm.value.trim()) { err.textContent = 'The course needs a name.'; nm.focus(); return; }
        if (pr.value === '' || Number(pr.value) < 0 || !Number.isInteger(Number(pr.value))) { err.textContent = 'Enter the price in whole rupees.'; pr.focus(); return; }
        if (!(await writeOkLocal())) return;
        try {
          await api.patch(`/courses/${c.id}`, { name: nm.value.trim(), price_inr: Number(pr.value), active: ac.checked ? 1 : 0 });
          Object.assign(c, { name: nm.value.trim(), price_inr: Number(pr.value), active: ac.checked ? 1 : 0 }); mark();
          ui.toast(`${c.name} saved`, 'good');
        } catch (e) { err.textContent = e.message; }
      }));
      const delBtn = ui.button({ icon: 'trash', tone: 'ghost', size: 'sm', ariaLabel: `Delete ${c.name}`, onClick: async () => {
        if (!(await ui.confirm({ title: `Delete "${c.name}"?`, text: 'Targets for this course are removed too. If students already enrolled in it, keep it and mark it inactive instead.', confirmLabel: 'Delete course' }))) return;
        if (!(await writeOkLocal())) return;
        try { await api.del(`/courses/${c.id}`); ui.toast('Course deleted', 'good'); reloadCourses(); } catch (e) {
          if (e.status === 409) {
            const off = await ui.confirm({ title: 'This course is in use', text: `${e.message} Inactive courses stay in past records but can no longer be chosen for new enrollments or targets.`, confirmLabel: 'Mark inactive', tone: 'primary' });
            if (off) { try { await api.patch(`/courses/${c.id}`, { active: 0 }); ui.toast(`${c.name} is now inactive`, 'good'); reloadCourses(); } catch (e2) { ui.toast(e2.message, 'bad'); } }
          } else ui.toast(e.message, 'bad');
        }
      } });
      return h('div', { class: ['ad-course', !c.active && 'is-off'] },
        h('div', { class: 'ad-course__name' }, nm),
        h('div', { class: 'ad-course__price' }, h('span', { class: 'ad-rupee', 'aria-hidden': 'true' }, '₹'), pr),
        h('label', { class: 'adm-toggle ad-course__active' }, ac, h('span', null, 'Offered')),
        h('div', { class: 'ad-course__acts' }, saveBtn, delBtn),
        err);
    });
    const nm = h('input', { type: 'text', class: 'td-input td-input--sm', placeholder: 'Course name, e.g. Full-Stack Development', 'aria-label': 'New course name' });
    const pr = h('input', { type: 'number', min: 0, step: 1, inputmode: 'numeric', class: 'td-input td-input--sm td-num ad-price', placeholder: '5000', 'aria-label': 'New course price in rupees' });
    const err = h('div', { class: 'td-field__error', 'aria-live': 'polite' });
    const addBtn = ui.button({ label: 'Add course', icon: 'plus', tone: 'primary', size: 'sm' });
    addBtn.addEventListener('click', () => busy(addBtn, async () => {
      err.textContent = '';
      if (!nm.value.trim()) { err.textContent = 'Give the course a name.'; nm.focus(); return; }
      if (pr.value === '' || Number(pr.value) < 0 || !Number.isInteger(Number(pr.value))) { err.textContent = 'Enter the price in whole rupees, e.g. 5000.'; pr.focus(); return; }
      if (!(await writeOkLocal())) return;
      try { await api.post('/courses', { name: nm.value.trim(), price_inr: Number(pr.value), active: 1 }); ui.toast(`${nm.value.trim()} added`, 'good'); reloadCourses(); } catch (e) { err.textContent = e.message; }
    }));
    put(coursesHost,
      courses.length ? h('div', { class: 'ad-courses' },
        h('div', { class: 'ad-course ad-course--head', 'aria-hidden': 'true' }, h('span', null, 'Course'), h('span', null, 'Price per student'), h('span', null, 'Status'), h('span', null, '')),
        rows) : h('p', { class: 'adm-muted' }, 'No courses yet. Add the courses your team sells, for example a ₹5,000 course and a ₹20,000 course. Targets and revenue use these.'),
      h('div', { class: 'ad-course ad-course--add' },
        h('div', { class: 'ad-course__name' }, nm),
        h('div', { class: 'ad-course__price' }, h('span', { class: 'ad-rupee', 'aria-hidden': 'true' }, '₹'), pr),
        h('span', null),
        h('div', { class: 'ad-course__acts' }, addBtn),
        err));
  };
  drawCourses(meta.courses || []);

  /* --- alerts & defaults --- (org_name is not shown: nothing in the portal displays it; the stored value is kept) */
  const dl = h('input', { type: 'date', class: 'td-input td-num', value: s.state_target_deadline || '' });
  const mc = h('input', { type: 'number', min: 0, max: 100, step: 0.5, inputmode: 'decimal', class: 'td-input td-num', value: s.min_conversion != null ? +(s.min_conversion * 100).toFixed(2) : '' });
  const ua = h('input', { type: 'number', min: 0, max: 50, step: 1, inputmode: 'numeric', class: 'td-input td-num', value: s.unreachable_after_attempts ?? 6 });
  const genErr = h('div', { class: 'td-form__error', role: 'alert', hidden: true });
  const genBtn = ui.button({ label: 'Save', tone: 'primary', size: 'sm' });
  genBtn.addEventListener('click', () => busy(genBtn, async () => {
    genErr.hidden = true;
    const pct = Number(mc.value);
    const tries = Number(ua.value);
    const fail = (m, inp) => { genErr.textContent = m; genErr.hidden = false; inp?.focus(); };
    if (!dl.value) return fail('Choose a fallback deadline.', dl);
    if (mc.value === '' || Number.isNaN(pct) || pct < 0 || pct > 100) return fail('The low-conversion alert must be between 0 and 100 %.', mc);
    if (ua.value === '' || !Number.isInteger(tries) || tries < 0 || tries > 50) return fail('Unanswered calls: use a whole number from 0 to 50.', ua);
    if (!(await writeOkLocal())) return;
    try { await api.patch('/settings', { state_target_deadline: dl.value, min_conversion: pct / 100, unreachable_after_attempts: tries }); ui.toast('Settings saved', 'good'); }
    catch (e) { fail([e.message, ...Object.values(e.fields || {})].join(' — ')); }
  }));
  const general = h('div', { class: 'ad-stack' },
    h('div', { class: 'td-form__grid ad-grid3' },
      field(h, 'Fallback deadline', dl, `Used for a college or person target that has no deadline of its own${s.state_target_deadline ? ` (now ${fmt.date(s.state_target_deadline)})` : ''}.`),
      field(h, 'Low-conversion alert (%)', mc, 'A place is flagged “few reached students enrol” when fewer than this share of the students reached go on to enrol. Default 5 %.'),
      field(h, 'Unanswered calls before a number is "Not working"', ua, 'After this many calls in a row with no answer, busy, switched off or not reachable, the number is marked not working. 0 = never. Default 6.')),
    genErr, h('div', { class: 'ad-row' }, genBtn));

  /* --- relevance factors --- */
  const rf = { it_core: 1, it_allied: 1, circuit: 0.6, core: 0.15, other: 0.15, ...(s.relevance_factors || {}) };
  const rfInputs = {};
  const rfErr = h('div', { class: 'td-form__error', role: 'alert', hidden: true });
  const rfBtn = ui.button({ label: 'Save factors', tone: 'primary', size: 'sm' });
  rfBtn.addEventListener('click', () => busy(rfBtn, async () => {
    rfErr.hidden = true;
    const v = {};
    for (const [k, inp] of Object.entries(rfInputs)) {
      const n = Number(inp.value);
      if (inp.value === '' || Number.isNaN(n) || n < 0 || n > 1) { rfErr.textContent = `${CATEGORY[k][0]}: use a number from 0 to 1.`; rfErr.hidden = false; inp.focus(); return; }
      v[k] = n;
    }
    if (!(await writeOkLocal())) return;
    try { await api.patch('/settings', { relevance_factors: v }); ui.toast('Factors saved — eligible-student estimates were recalculated', 'good'); }
    catch (e) { rfErr.textContent = e.message; rfErr.hidden = false; }
  }));
  const rfBody = h('div', { class: 'ad-stack' },
    h('p', { class: 'adm-muted' }, 'For each type of branch: what share of final-year students could realistically buy a tech course? 1 = everyone, 0.5 = half, 0 = nobody. "Eligible students" = final-year students × this number. It drives the "By eligible students" split in Targets, the call order in the call queue and the "target may be too high" warning.'),
    h('div', { class: 'ad-rf' }, Object.entries(CATEGORY).map(([k, [l, help]]) => {
      rfInputs[k] = h('input', { type: 'number', min: 0, max: 1, step: 0.05, inputmode: 'decimal', class: 'td-input td-num', value: rf[k] ?? '' });
      return field(h, l, rfInputs[k], help);
    })),
    rfErr, h('div', { class: 'ad-row' }, rfBtn));

  const sso = isSso(ctx, session);
  const youLabel = sso ? 'Your account' : 'You & access';
  const sections = [['programme', 'Programme'], ['you', youLabel], ['courses', 'Courses'], ['targets', 'Alerts'], ['relevance', 'Branch relevance'], ['look', 'Appearance']];
  put(el,
    pageHead(ctx, 'Settings', `The programme target, ${sso ? '' : 'who you are, '}the courses you sell, and how alerts are worked out. Every change is recorded in the audit log.`),
    h('nav', { class: 'ad-jump', 'aria-label': 'Settings sections' }, sections.map(([id, l]) =>
      h('a', { href: '#/settings', onClick: (e) => { e.preventDefault(); el.querySelector(`[data-sec="${id}"]`)?.scrollIntoView({ behavior: (typeof ctx.ui.prefersReducedMotion === 'function' ? ctx.ui.prefersReducedMotion() : matchMedia('(prefers-reduced-motion: reduce)').matches) ? 'auto' : 'smooth', block: 'start' }); } }, l)),
    h('a', { href: '#/data?tab=export' }, 'Export & backup'), h('a', { href: '#/audit?entity=setting' }, 'Settings history')),
    !writable ? h('p', { class: 'ad-warnline' }, `You have view-only access. Settings can be viewed but not changed${sso ? '; ask an LMS super admin for edit access' : ''}.`) : null,
    secWrap('programme', ui.section({ title: 'Programme target', sub: 'The headline goal every page measures against.', body: programBody })),
    secWrap('you', ui.section({ title: youLabel, body: you })),
    secWrap('courses', ui.section({ title: 'Courses & prices', sub: 'What your team sells. Revenue = enrollments × price.', body: coursesHost })),
    secWrap('targets', ui.section({ title: 'Alerts & defaults', body: general })),
    secWrap('relevance', ui.section({ title: 'Branch relevance', body: rfBody })),
    secWrap('look', ui.section({ title: 'Appearance', sub: 'Saved on this device.', body: theme })));
  function secWrap(id, node) { node.dataset.sec = id; return node; }
}

/** Programme target / deadline / start / target district groups — PATCH /api/program (R11: the protected path). */
function programSection(ctx, program, rerender) {
  const { h, ui, api, fmt } = ctx;
  const writable = canWrite(ctx);
  const target = h('input', { type: 'number', class: 'td-input td-num', min: 1, max: 1000000, step: 1, inputmode: 'numeric', value: program.target ?? '', disabled: !writable || undefined });
  const deadline = h('input', { type: 'date', class: 'td-input td-num', value: program.deadline || '', disabled: !writable || undefined });
  const hasStart = 'start' in program || 'program_start' in program;
  const start = h('input', { type: 'date', class: 'td-input td-num', value: program.start || program.program_start || '', disabled: !writable || undefined });
  const tErr = errEl(h); const dErr = errEl(h); const sErr = errEl(h); const gErr = errEl(h);
  const formErr = h('div', { class: 'td-form__error', role: 'alert', hidden: true });

  // district groups: one select per district (Not a target / group name)
  const groups = JSON.parse(JSON.stringify(program.target_district_groups || {}));
  const names = () => Object.keys(groups);
  const groupOf = (id) => names().find((n) => (groups[n] || []).includes(id)) || '';
  const districts = [...(program.districts || [])].sort((a, b) => a.name.localeCompare(b.name));
  const gridHost = h('div', { class: 'ad-groups' });
  const newName = h('input', { type: 'text', class: 'td-input', maxlength: 60, placeholder: 'New group name, e.g. Prakasam', 'aria-label': 'New group name', disabled: !writable || undefined });
  const drawGroups = () => {
    put(gridHost,
      h('div', { class: 'ad-groups__chips' }, names().length ? names().map((n) => h('span', { class: 'adm-pill' }, `${n}: ${(groups[n] || []).length} district${(groups[n] || []).length === 1 ? '' : 's'}`)) : h('span', { class: 'adm-muted' }, 'No target districts yet.')),
      h('div', { class: 'ad-groups__grid' }, districts.map((d) => {
        const s = h('select', { class: 'td-input td-select td-input--sm', 'aria-label': `Target group for ${d.name}`, disabled: !writable || undefined },
          h('option', { value: '' }, 'Not a target'), names().map((n) => h('option', { value: n }, n)));
        s.value = groupOf(d.id);
        s.addEventListener('change', () => {
          for (const n of names()) groups[n] = (groups[n] || []).filter((x) => x !== d.id);
          if (s.value) groups[s.value].push(d.id);
          drawGroups();
        });
        return h('label', { class: ['ad-groups__row', groupOf(d.id) && 'is-on'] }, h('span', null, d.name, d.old_district ? h('small', { class: 'adm-muted' }, ` (old ${d.old_district})`) : null), s);
      })));
  };
  drawGroups();
  const addGroup = ui.button({ label: 'Add group', icon: 'plus', size: 'sm', disabled: !writable || undefined, onClick: () => {
    const n = newName.value.trim();
    gErr.textContent = '';
    if (!n) { gErr.textContent = 'Type a group name first.'; newName.focus(); return; }
    if (n.length > 60) { gErr.textContent = 'Use at most 60 characters.'; return; }
    if (names().some((x) => x.toLowerCase() === n.toLowerCase())) { gErr.textContent = 'A group with that name exists.'; return; }
    if (names().length >= 12) { gErr.textContent = 'At most 12 groups.'; return; }
    groups[n] = []; newName.value = ''; drawGroups();
    ui.toast(`Group “${n}” added. Pick its districts below.`, 'info');
  } });

  const save = ui.button({ label: 'Save programme', tone: 'primary', disabled: !writable || undefined });
  save.addEventListener('click', async () => {
    [tErr, dErr, sErr, gErr].forEach((x) => { x.textContent = ''; }); formErr.hidden = true;
    const body = {};
    const n = Number(target.value);
    if (target.value === '' || !Number.isInteger(n) || n < 1 || n > 1000000) { tErr.textContent = 'Enter a whole number from 1 to 10,00,000.'; target.focus(); return; }
    if (!deadline.value) { dErr.textContent = 'Pick the deadline.'; deadline.focus(); return; }
    if (hasStart && start.value && start.value >= deadline.value) { sErr.textContent = 'The start must be before the deadline.'; start.focus(); return; }
    const clean = Object.fromEntries(names().filter((k) => (groups[k] || []).length).map((k) => [k, groups[k]]));
    if (!Object.keys(clean).length) { gErr.textContent = 'Keep at least one district in a target group.'; return; }
    if (n !== program.target) body.target = n;
    if (deadline.value !== program.deadline) body.deadline = deadline.value;
    if (hasStart && start.value && start.value !== (program.start || program.program_start)) body.start = start.value;
    if (JSON.stringify(clean) !== JSON.stringify(program.target_district_groups || {})) body.target_district_groups = clean;
    if (!Object.keys(body).length) { ui.toast('Nothing changed', 'info'); return; }
    const lines = [];
    if (body.target) lines.push(`Target: ${fmt.num(program.target)} → ${fmt.num(body.target)} paid enrollments`);
    if (body.deadline) lines.push(`Deadline: ${fmt.date(program.deadline)} → ${fmt.date(body.deadline)}`);
    if (body.start) lines.push(`Start: ${fmt.date(program.start || program.program_start)} → ${fmt.date(body.start)}`);
    if (body.target_district_groups) lines.push(`Target districts: ${Object.values(program.target_district_groups || {}).flat().length} → ${Object.values(clean).flat().length} (${Object.keys(clean).join(', ')})`);
    const ok = await ui.confirm({ title: 'Change the programme?', text: 'Every page, pace and “remaining” figure is recalculated from this. The change is recorded in the audit log.', body: h('ul', { class: 'ad-confirm-list' }, lines.map((l) => h('li', null, l))), confirmLabel: 'Save changes', tone: 'primary' });
    if (!ok) return;
    if (!(await writeOk(ctx))) return;
    save.disabled = true; save.classList.add('is-busy');
    try {
      const r = await api.patch('/program', body);
      try { ctx.state.program = r && r.target_district_groups ? r : await api.get('/program'); } catch { /* ignore */ }
      window.dispatchEvent(new CustomEvent('td:program', { detail: ctx.state.program }));
      ui.toast('Programme saved', 'good');
      rerender();
    } catch (e) {
      const fe = e.fields || {};
      if (fe.target) tErr.textContent = fe.target;
      if (fe.deadline) dErr.textContent = fe.deadline;
      if (fe.start) sErr.textContent = fe.start;
      if (fe.target_district_groups) gErr.textContent = fe.target_district_groups;
      if (!Object.keys(fe).length || fe._body) { formErr.textContent = e.message; formErr.hidden = false; }
    } finally { save.disabled = !writable; save.classList.remove('is-busy'); }
  });
  return h('div', { class: 'ad-stack ad-program' },
    h('div', { class: 'td-form__grid ad-grid3' },
      field(h, 'Paid enrollments target', target, `Now ${fmt.num(program.target)}.`, { req: true, err: tErr }),
      field(h, 'Deadline', deadline, `Now ${fmt.date(program.deadline)}.`, { req: true, err: dErr }),
      hasStart ? field(h, 'Programme start', start, 'Pace is measured from this date.', { err: sErr }) : null),
    h('div', { class: 'ad-sub' }, h('h3', null, 'Target districts'),
      h('p', { class: 'adm-muted' }, program.note || 'Districts are grouped under the old district names. The default district selection on every page is these districts.'),
      writable ? h('div', { class: 'ad-row ad-groups__add' }, newName, addGroup) : null, gErr, gridHost),
    formErr, writable ? h('div', { class: 'ad-row' }, save) : null);
}

/** Name, sign-in / passcode status, sign out. Inside the LMS: only who is signed in (the LMS owns name, sign-in and sign-out). */
function accessSection(ctx, meta, session) {
  const { h, ui, api, fmt } = ctx;
  const sess = ctx.session || session;
  if (isSso(ctx, session)) {
    const role = sess?.role || session?.role;
    return h('div', { class: 'ad-you' }, h('div', { class: 'ad-you__col' }, h('div', { class: 'ad-access' }, ui.kv([
      ['Signed in as', sess?.user || session?.user || api.user || '—'],
      ['Access', role === 'viewer' ? 'View only' : 'Can edit'],
      ['Sign-in', 'Through Tech Drona LMS. Your LMS name is recorded with every change.'],
    ]))));
  }
  const name = h('input', { type: 'text', class: 'td-input', value: api.user || sess?.user || '', placeholder: 'e.g. Ravi K.', autocomplete: 'name', maxlength: 100 });
  const nameErr = errEl(h);
  const authRequired = !!(session?.auth_required ?? sess?.required ?? meta.passcode_required);
  const status = h('div', { class: 'ad-access' },
    ui.kv([
      ['Sign-in', authRequired ? 'Required on this server (team passcode)' : 'Not required on this server'],
      ['Signed in as', sess?.user || api.user || h('span', { class: 'adm-muted' }, 'nobody yet')],
      ['Access', sess?.role ? (sess.role === 'viewer' ? 'View only' : sess.role === 'admin' ? 'Admin' : 'Can edit') : (authRequired ? 'Unknown' : 'Can edit')],
      session?.expires_at ? ['Session ends', `${fmt.date(session.expires_at)} ${new Date(session.expires_at).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })}`] : null,
    ].filter(Boolean)));
  const signOut = session && session.authenticated ? ui.button({ label: 'Sign out', icon: 'close', size: 'sm', onClick: async () => {
    const ok = await ui.confirm({ title: 'Sign out?', text: 'You will need the team passcode to sign in again on this device.', confirmLabel: 'Sign out', tone: 'danger' });
    if (!ok) return;
    try { await api.del('/session'); ui.toast('Signed out', 'good'); location.reload(); } catch (e) { ui.toast(e.message, 'bad'); }
  } }) : null;
  // legacy passcode (no session endpoint): keep the device passcode controls
  let legacy = null;
  if (!session && meta.passcode_required) {
    const pass = h('input', { type: 'password', class: 'td-input', placeholder: 'Team passcode', autocomplete: 'current-password' });
    let hasPass = false; try { hasPass = !!localStorage.getItem('td.passcode'); } catch { /* ignore */ }
    const st = h('span', { class: 'adm-muted' }, hasPass ? 'A passcode is saved on this device.' : 'No passcode saved on this device.');
    legacy = h('div', { class: 'ad-you__col' }, field(h, 'Team passcode', pass, 'This server asks for a passcode before any change. Ask your team admin for it.'),
      h('div', { class: 'ad-row' }, ui.button({ label: 'Save passcode', size: 'sm', tone: hasPass ? 'secondary' : 'primary', onClick: () => {
        if (!pass.value) { ui.toast('Type the passcode first', 'warn'); pass.focus(); return; }
        api.setPasscode(pass.value); pass.value = ''; st.textContent = 'A passcode is saved on this device.'; ui.toast('Passcode saved on this device', 'good');
      } }), ui.button({ label: 'Forget', size: 'sm', tone: 'ghost', onClick: async () => {
        if (!(await ui.confirm({ title: 'Forget the passcode?', text: 'You will not be able to save changes on this device until you enter it again.', confirmLabel: 'Forget', tone: 'danger' }))) return;
        api.setPasscode(''); st.textContent = 'No passcode saved on this device.'; ui.toast('Passcode removed from this device', 'good');
      } })), st);
  }
  return h('div', { class: 'ad-you' },
    h('div', { class: 'ad-you__col' },
      field(h, 'Your name', name, 'Shown in the audit log next to every change you make. First name and initial is fine.', { err: nameErr }),
      h('div', { class: 'ad-row' }, ui.button({ label: 'Save name', tone: 'primary', size: 'sm', onClick: () => {
        const v = name.value.trim();
        if (!v) { nameErr.textContent = 'Enter your name; changes cannot be saved without one.'; name.focus(); return; }
        if (/^(seed|import|import_research|system|demo)$/i.test(v)) { nameErr.textContent = 'That name is reserved for automatic imports. Use your own name.'; name.focus(); return; }
        nameErr.textContent = '';
        api.setUser(v);
        window.dispatchEvent(new CustomEvent('td:user', { detail: v }));
        ui.toast(`Saved. Changes will be signed “${v}”`, 'good');
      } }))),
    h('div', { class: 'ad-you__col' }, status, signOut ? h('div', { class: 'ad-row' }, signOut) : null),
    legacy);
}
