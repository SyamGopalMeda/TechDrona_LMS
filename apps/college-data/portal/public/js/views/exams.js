// Tech Drona portal — Exams & outreach windows. Route: #/exams  (?state=in_exams&district=guntur&view=list&q=…&done41=1)
// Respects the global district scope (GET /api/exams?districts=…); the District filter narrows inside it. Filters live in the URL.
// Styles: css/views-admin.css (.v-adm-exams) only. Uses shared td-* components only.
import { today, daysUntil } from '../ui/h.js';
import { getScope, scopeRows, SCOPE_EVENT } from '../state.js';
import { getQuery, setQuery, getScoped, scopeLine } from './calls.js';
import { examNoticesCard } from './live.js';

const DAY = 86400000;
const STATUSES = ['Upcoming', 'In Progress', 'Completed', 'No Current Exams Found', 'Unverified'];
const EVIDENCE = ['Officially confirmed', 'Official university timetable (affiliation-based)', 'Unverified (calendar-planned)', 'Conflicting', 'Unverified'];
const CONFIDENCE = ['High', 'Medium', 'Low'];
const STATE = {
  in_exams: { label: 'In exams now', short: 'In exams', tone: 'bad', icon: 'exam', help: 'An end-sem or mid exam window includes today.' },
  exams_soon: { label: 'Exams within 14 days', short: 'Exams soon', tone: 'warn', icon: 'clock', help: 'An exam starts in the next 14 days.' },
  clear: { label: 'Clear', short: 'Clear', tone: 'good', icon: 'check', help: 'No exam today or in the next 14 days.' },
  unknown: { label: 'Dates unknown', short: 'Unknown', tone: 'neutral', icon: 'warn', help: 'Neither semester has a confirmed date yet.' },
};
const STATUS_TONE = { 'In Progress': 'bad', Upcoming: 'warn', Completed: 'good', 'No Current Exams Found': 'neutral', Unverified: 'neutral' };
/** Display words for the stored research values (the stored values themselves never change). */
export const EXAM_STATUS_LABEL = { Upcoming: 'Upcoming', 'In Progress': 'In progress', Completed: 'Finished', 'No Current Exams Found': 'No exams announced', Unverified: 'Not confirmed' };
const EVIDENCE_LABEL = {
  'Officially confirmed': 'Official notice', 'Official university timetable (affiliation-based)': 'University timetable',
  'Unverified (calendar-planned)': 'Academic calendar (planned)', Conflicting: 'Sources disagree', Unverified: 'Not confirmed',
};
export const evidenceLabel = (v) => EVIDENCE_LABEL[v] || v;
const CONF_TONE = { High: 'good', Medium: 'info', Low: 'warn' };
const VIEW_KEY = 'td.exams.view';

const arr = (x) => (Array.isArray(x) ? x : (x && Array.isArray(x.rows) ? x.rows : []));
const isoOnly = (v) => (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v.trim()) ? v.trim() : null);
const addDays = (iso, n) => new Date(Date.parse(iso + 'T00:00:00Z') + n * DAY).toISOString().slice(0, 10);
const dayIndex = (iso, from) => Math.round((Date.parse(iso + 'T00:00:00Z') - Date.parse(from + 'T00:00:00Z')) / DAY);
const readLS = (k) => { try { return localStorage.getItem(k) || ''; } catch { return ''; } };
const writeLS = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

/* ---------- exam windows: mirrors server/rollup.js examWindows() so the timeline matches the status counts ---------- */
const RANGE_RE = /(\d{4}-\d{2}-\d{2})\s*(?:to|–|—|-|until|till)\s*(\d{4}-\d{2}-\d{2})/gi;
function textWindows(txt, row) {
  const out = [];
  if (!txt) return out;
  let m; let found = false;
  RANGE_RE.lastIndex = 0;
  while ((m = RANGE_RE.exec(txt))) {
    found = true;
    const [a, b] = m[1] <= m[2] ? [m[1], m[2]] : [m[2], m[1]];
    out.push({ start: a, end: b });
  }
  if (!found) {
    const from = /\bfrom\s+(\d{4}-\d{2}-\d{2})/i.exec(txt)?.[1];
    const ends = /\brunning\b.*?\bends\s+(\d{4}-\d{2}-\d{2})/i.exec(txt)?.[1];
    if (ends) {
      const start = [isoOnly(row?.notice_date), isoOnly(row?.verified_on)].filter(Boolean).filter((d) => d <= ends).sort()[0] || ends;
      out.push({ start, end: ends });
    } else if (from) out.push({ start: from, end: from, openEnded: true });
  }
  return out;
}
/** How trustworthy a row's dates are. */
function trust(r, text = '') {
  const ev = String(r.evidence || '');
  if (/conflict/i.test(ev)) return 'conflict';
  if (r.status === 'Unverified' || /unverified|planned|tentative|inferred/i.test(`${ev} ${text}`)) return 'planned';
  return 'confirmed';
}
function windowsOf(r) {
  const out = [];
  const es = isoOnly(r.endsem_start); const ee = isoOnly(r.endsem_end);
  if (es || ee) {
    const start = es || ee; const end = ee && ee >= start ? ee : start;
    out.push({ kind: 'endsem', start, end, trust: trust(r), openEnded: !ee, text: ee ? 'End-sem exams' : 'End-sem exams start (end date not published)' });
  }
  for (const w of textWindows(r.mid_window, r)) out.push({ kind: 'mid', ...w, trust: trust(r, r.mid_window), text: `Mid exams — ${r.mid_window}` });
  for (const w of textWindows(r.lab_window, r)) out.push({ kind: 'lab', ...w, trust: trust(r, r.lab_window), text: `Labs / practicals — ${r.lab_window}` });
  return out;
}
const isPending = (r) => !r || r._missing || (r.status === 'Unverified' && !windowsOf(r).length);

function fourOneDone(c) {
  const r = (c.rows || []).find((x) => x.semester === '4-1');
  if (!r || r.status === 'Unverified') return false;
  if (r.status === 'Completed') return true;
  const e = isoOnly(r.endsem_end);
  return !!e && daysUntil(e) < 0;
}

function countdown(r) {
  if (!r || r._missing) return { text: 'Not tracked yet', tone: 'neutral' };
  const s = isoOnly(r.endsem_start), e = isoOnly(r.endsem_end);
  const ds = s ? daysUntil(s) : null, de = e ? daysUntil(e) : null;
  if (ds !== null && ds > 0) return { text: `starts in ${plural(ds, 'day')}`, tone: ds <= 14 ? 'warn' : 'info' };
  if (ds === 0) return { text: 'starts today', tone: 'bad' };
  if (de !== null && de > 0) return { text: `ends in ${plural(de, 'day')}`, tone: 'bad' };
  if (de === 0) return { text: 'ends today', tone: 'bad' };
  if (de !== null && de < 0) return { text: `ended ${plural(-de, 'day')} ago`, tone: 'good' };
  if (r.status === 'Completed') return { text: 'completed', tone: 'good' };
  if (r.status === 'No Current Exams Found') return { text: 'no exams announced', tone: 'neutral' };
  return { text: 'dates not published', tone: 'neutral' };
}

let cur = null;
export const handlesScope = true;

export async function render(el, params = {}, ctx) {
  const p = { ...getQuery(), ...params };
  const narrow = (el.clientWidth || innerWidth) < 760;
  const prevFilt = cur && cur.el === el ? cur.filt : null; // keep filters across ctx.refresh()
  try { cur?.off?.(); } catch { /* ignore */ }
  cur = {
    el, ctx,
    view: p.view === 'list' || p.view === 'timeline' ? p.view : (readLS(VIEW_KEY) || (narrow ? 'list' : 'timeline')),
    filt: prevFilt || { district: p.district || '', state: STATE[p.state] ? p.state : '', q: p.q || '', done41: p.done41 === '1' },
  };
  ctx.setBreadcrumb?.([{ label: 'Exams', href: '#/exams' }]);
  el.className = 'v-adm v-adm-exams';
  el.replaceChildren(ctx.ui.skeleton(2), ctx.ui.skeleton(6));
  const me = cur;
  const onScope = () => { if (cur !== me || !el.isConnected) return; load({ quiet: true }); };
  addEventListener(SCOPE_EVENT, onScope);
  cur.off = () => removeEventListener(SCOPE_EVENT, onScope);
  await load();
}
export function destroy() { try { cur?.off?.(); } catch { /* ignore */ } cur = null; }

function syncUrl() {
  const f = cur.filt;
  setQuery(cur.ctx, { district: f.district, state: f.state, q: f.q.trim(), done41: f.done41 ? '1' : null, view: cur.view });
}

async function load({ quiet = false } = {}) {
  if (!cur) return;
  const me = cur;
  const { el, ctx } = me;
  const { ui, api } = ctx;
  try {
    const [rows, meta] = await Promise.all([getScoped(ctx, '/exams').then(arr), ctx.state?.meta ? Promise.resolve(ctx.state.meta) : api.get('/meta').catch(() => ({}))]);
    if (cur !== me) return;
    me.rows = scopeRows(rows);
    // a district picked earlier that is no longer inside the scope would hide everything: drop it
    if (me.filt.district && !me.rows.some((c) => c.district_id === me.filt.district)) me.filt.district = '';
    me.meta = meta;
    me.dName = new Map((meta.districts || []).map((d) => [d.id, d.name]));
  } catch (e) {
    if (cur !== me) return;
    if (quiet) { ui.toast(e.message, 'bad'); return; }
    el.replaceChildren(ui.errorCard({ title: 'Could not load the exam calendar', error: e, retry: () => { el.replaceChildren(ui.skeleton(4)); load(); } }));
    return;
  }
  draw();
}

function filtered(skipState = false) {
  const { filt } = cur;
  const q = filt.q.trim().toLowerCase();
  return cur.rows.filter((c) => (!filt.district || c.district_id === filt.district)
    && (skipState || !filt.state || c.exam_state === filt.state)
    && (!q || `${c.name} ${c.short_name || ''}`.toLowerCase().includes(q))
    && (!filt.done41 || fourOneDone(c)));
}

function draw() {
  const { el, ctx, filt } = cur;
  const { h, ui, fmt } = ctx;
  const scroller = () => (typeof ui.scroller === 'function' ? ui.scroller() : el.closest('[class*="scroll"], main'));
  const keepY = scroller()?.scrollTop;

  if (!cur.rows.length) {
    el.replaceChildren(head(),
      ui.emptyState({ title: getScope().all ? 'No exam information yet' : 'No colleges in the selected districts', icon: 'exam',
        text: getScope().all ? 'Exam dates come from the research files; ask an admin to re-import them. You can also add dates for one college from its page.'
          : 'Widen the district selection at the top of the page to see more colleges.' }));
    return;
  }

  const base = filtered(true);
  const counts = { in_exams: 0, exams_soon: 0, clear: 0, unknown: 0 };
  for (const c of base) counts[c.exam_state] = (counts[c.exam_state] || 0) + 1;

  const stateCards = h('div', { class: 'adm-states', role: 'group', 'aria-label': 'Filter by exam state' },
    Object.entries(STATE).map(([k, s]) => h('button', {
      type: 'button', class: ['adm-state', `is-${s.tone}`, filt.state === k && 'is-on'], 'aria-pressed': String(filt.state === k), title: s.help,
      onClick: () => { filt.state = filt.state === k ? '' : k; syncUrl(); draw(); },
    }, h('span', { class: 'adm-state__dot', 'aria-hidden': 'true' }), h('span', { class: 'adm-state__label' }, s.label),
    h('strong', { class: 'adm-state__n td-num' }, fmt.num(counts[k] || 0)))));

  // toolbar
  const districts = [...(cur.meta.districts || [])].filter((d) => cur.rows.some((c) => c.district_id === d.id)).sort((a, b) => a.name.localeCompare(b.name));
  const districtSel = h('select', { class: 'td-input td-select', 'aria-label': 'District', onChange: (e) => { filt.district = e.target.value; syncUrl(); draw(); } },
    h('option', { value: '' }, getScope().all ? 'All districts' : 'All selected districts'), districts.map((d) => h('option', { value: d.id }, d.name)));
  districtSel.value = filt.district;
  const search = h('input', { type: 'search', class: 'td-input', placeholder: 'Search college…', value: filt.q, 'aria-label': 'Search college' });
  let t;
  search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { filt.q = search.value; syncUrl(); drawBody(); }, 200); });
  const only41 = h('label', { class: 'adm-toggle' }, h('input', { type: 'checkbox', class: 'td-check', checked: filt.done41, onChange: (e) => { filt.done41 = e.target.checked; syncUrl(); draw(); } }), h('span', null, 'Only colleges that finished 4-1'));
  const viewSeg = h('div', { class: 'adm-seg', role: 'group', 'aria-label': 'Layout' },
    [['timeline', 'Timeline'], ['list', 'List']].map(([id, l]) => h('button', {
      type: 'button', class: ['adm-seg__btn', cur.view === id && 'is-on'], 'aria-pressed': String(cur.view === id),
      onClick: () => { cur.view = id; writeLS(VIEW_KEY, id); syncUrl(); draw(); },
    }, l)));
  const active = !!(filt.district || filt.state || filt.q || filt.done41);
  cur.countEl = h('span', { class: 'adm-count', 'aria-live': 'polite' });
  const clear = active ? ui.button({ label: 'Clear filters', tone: 'ghost', size: 'sm', icon: 'close', onClick: () => { Object.assign(filt, { district: '', state: '', q: '', done41: false }); syncUrl(); draw(); } }) : null;

  cur.bodyEl = h('div', { class: 'ex-body' });
  el.replaceChildren(
    head(),
    stateCards,
    outreachPanel(base),
    examNoticesCard(ctx), // live: latest official exam notices (views/live.js)
    h('div', { class: 'adm-toolbar' }, h('div', { class: 'adm-toolbar__filters' }, search, districtSel, only41),
      h('div', { class: 'adm-toolbar__end' }, cur.countEl, clear, viewSeg)),
    cur.bodyEl);
  drawBody();
  if (keepY) { const sc = scroller(); if (sc) sc.scrollTop = keepY; }
}

function head() {
  const { h, ui, fmt } = cur.ctx;
  const extended = typeof ui.scopePill === 'function';
  const hd = ui.pageHeader({
    title: 'Exams & outreach windows',
    sub: 'Which colleges are writing exams, and when final-year students are free to meet us. Only published notices or academic calendars count; planned dates are marked.',
    actions: [h('p', { class: 'adm-asof' }, 'As of ', h('strong', null, fmt.date(today())))],
    scope: extended || undefined,
  });
  return extended ? hd : h('div', null, hd, scopeLine(cur.ctx));
}

/** "When can we reach final-years?" — open now (4-1 finished) and opening soon (outreach_from in the next 60 days). */
function outreachPanel(rows) {
  const { h, ui, fmt } = cur.ctx;
  const openNow = rows.filter(fourOneDone).sort((a, b) => a.name.localeCompare(b.name));
  const soon = rows.filter((c) => !fourOneDone(c) && c.outreach_from && daysUntil(c.outreach_from) >= 0 && daysUntil(c.outreach_from) <= 60)
    .sort((a, b) => a.outreach_from.localeCompare(b.outreach_from) || a.name.localeCompare(b.name));
  const item = (c, sub) => h('li', null, h('a', { href: `#/college/${c.college_id}` }, c.name),
    h('span', { class: 'adm-muted' }, `${cur.dName.get(c.district_id) || ''}${sub ? ' · ' : ''}`, sub || ''));
  const col = (title, tone, list, fmtSub, emptyText) => {
    const LIMIT = 5;
    const ul = h('ul', { class: 'ex-out__list' });
    const fill = (n) => ul.replaceChildren(...list.slice(0, n).map((c) => item(c, fmtSub(c))),
      ...(list.length > n ? [h('li', null, ui.button({ label: `Show all ${list.length}`, tone: 'ghost', size: 'sm', onClick: () => fill(list.length) }))] : []));
    fill(LIMIT);
    return h('div', { class: ['ex-out__col', `is-${tone}`] },
      h('h3', { class: 'ex-out__title' }, title, h('span', { class: 'adm-pill td-num' }, fmt.num(list.length))),
      list.length ? ul : h('p', { class: 'adm-muted ex-out__empty' }, emptyText));
  };
  return ui.section({
    title: 'When can we reach final-year students?',
    sub: 'Final-year (4-1) students are the main audience. Outreach is easiest once their 4-1 end-sem exams are over.',
    body: h('div', { class: 'ex-out' },
      col('Open now — 4-1 exams finished', 'good', openNow, (c) => (c.outreach_from ? `since ${fmt.date(c.outreach_from)}` : ''), 'No college in this view has finished 4-1 end-sem exams yet.'),
      col('Opening in the next 60 days', 'info', soon, (c) => `from ${fmt.date(c.outreach_from)} (${fmt.days(c.outreach_from)})`, 'No 4-1 end dates are published for the next 60 days in this view.')),
  });
}

function drawBody() {
  const rows = filtered();
  const { ui, fmt } = cur.ctx;
  cur.countEl.textContent = `${fmt.num(rows.length)} of ${fmt.num(cur.rows.length)} colleges`;
  const node = !rows.length
    ? ui.emptyState({ title: 'No colleges match these filters', text: 'Clear a filter or search for another name.', icon: 'filter',
      action: { label: 'Clear filters', icon: 'close', onClick: () => { Object.assign(cur.filt, { district: '', state: '', q: '', done41: false }); syncUrl(); draw(); } } })
    : (cur.view === 'timeline' ? gantt(rows) : list(rows));
  cur.bodyEl.replaceChildren(node);
}

/* ================================================================ Timeline */
function gantt(rows) {
  const { h, fmt } = cur.ctx;
  const BACK = 7, DAYS = 7 + 112;                 // one week back, 16 weeks ahead
  const t0 = addDays(today(), -BACK);
  const narrow = (cur.el.clientWidth || innerWidth) < 760;
  const LABEL_W = narrow ? 140 : 280;
  const avail = (cur.el.clientWidth || 1000) - LABEL_W - 2;
  const DW = Math.max(narrow ? 7 : 8, Math.floor(avail / DAYS));
  const HEAD = 46, ROW = 42, GROUP = 30;
  const W = DAYS * DW;
  const x = (iso) => Math.max(0, Math.min(DAYS, dayIndex(iso, t0))) * DW;
  const todayX = BACK * DW;

  const groups = new Map();
  for (const c of [...rows].sort((a, b) => (cur.dName.get(a.district_id) || '').localeCompare(cur.dName.get(b.district_id) || '') || a.name.localeCompare(b.name))) {
    const k = c.district_id || '';
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(c);
  }
  let totalH = HEAD;
  for (const l of groups.values()) totalH += GROUP + l.length * ROW;

  const S = (tag, attrs, ...kids) => h('svg:' + tag, attrs, ...kids);
  const uid = Math.random().toString(36).slice(2, 7);
  const defs = S('defs', null, ['s31', 's41'].map((cls) => S('pattern', { id: `hatch-${cls}-${uid}`, width: 6, height: 6, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
    S('rect', { width: 6, height: 6, class: `g-hatch-bg ${cls}` }), S('line', { x1: 0, y1: 0, x2: 0, y2: 6, class: `g-hatch ${cls}` }))));
  const svg = S('svg', { class: 'ex-gantt-svg', width: W, height: totalH, viewBox: `0 0 ${W} ${totalH}`, role: 'group', 'aria-label': `Exam timeline from ${fmt.date(t0)} to ${fmt.date(addDays(t0, DAYS))}` }, defs);

  // header: months (row 1), Monday dates (row 2), today pill
  svg.append(S('rect', { x: 0, y: 0, width: W, height: HEAD, class: 'g-head' }));
  const monthStarts = [];
  for (let d = 0; d <= DAYS; d++) { const iso = addDays(t0, d); if (iso.endsWith('-01')) monthStarts.push(d); }
  const labelMonths = [0, ...monthStarts].filter((d, i, a) => i === 0 ? (monthStarts[0] === undefined || monthStarts[0] * DW > 70) : true);
  for (const d of labelMonths) {
    const dt = new Date(addDays(t0, d) + 'T00:00:00Z');
    svg.append(S('text', { x: d * DW + 6, y: 17, class: 'g-month' }, dt.toLocaleDateString('en-IN', { month: 'short', year: 'numeric', timeZone: 'UTC' })));
  }
  for (const d of monthStarts) svg.append(S('line', { x1: d * DW, x2: d * DW, y1: 0, y2: totalH, class: 'g-month-line' }));
  for (let d = 0; d <= DAYS; d++) {
    const dt = new Date(addDays(t0, d) + 'T00:00:00Z');
    if (dt.getUTCDay() !== 1) continue;
    svg.append(S('line', { x1: d * DW, x2: d * DW, y1: HEAD, y2: totalH, class: 'g-week-line' }));
    if (Math.abs(d * DW - todayX) > 22) svg.append(S('text', { x: d * DW + 3, y: 38, class: 'g-week' }, String(dt.getUTCDate())));
  }
  svg.append(S('rect', { x: 0, y: HEAD, width: todayX, height: totalH - HEAD, class: 'g-past' }));

  const labels = h('div', { class: 'ex-gantt-labels', style: { width: LABEL_W + 'px' } },
    h('div', { class: 'ex-gl-head', style: { height: HEAD + 'px' } }, h('span', null, 'College'), h('span', { class: 'ex-gl-lanes' }, 'Year')));
  let y = HEAD;
  for (const [dk, list] of groups) {
    labels.append(h('div', { class: 'ex-gl-group', style: { height: GROUP + 'px' } }, cur.dName.get(dk) || dk || 'District not set', h('span', { class: 'adm-muted' }, ` · ${list.length}`)));
    svg.append(S('rect', { x: 0, y, width: W, height: GROUP, class: 'g-group' }));
    y += GROUP;
    for (const c of list) {
      const done = fourOneDone(c);
      const st = STATE[c.exam_state] || STATE.unknown;
      labels.append(h('div', { class: ['ex-gl-row', done && 'is-done41'], style: { height: ROW + 'px' } },
        h('div', { class: 'ex-gl-main' },
          h('a', { href: `#/college/${c.college_id}`, title: c.name }, c.name),
          h('span', { class: ['ex-gl-sub', `is-${st.tone}`] }, h('i', { 'aria-hidden': 'true' }), done ? '4-1 done · reach out' : st.short)),
        h('span', { class: 'ex-gl-lanes', 'aria-hidden': 'true' }, h('span', null, '3-1'), h('span', null, '4-1'))));
      svg.append(S('line', { x1: 0, x2: W, y1: y + ROW, y2: y + ROW, class: 'g-row-line' }));
      const exRows = c.rows || [];
      const wins = exRows.flatMap((r) => windowsOf(r).map((w) => ({ ...w, sem: r.semester, r })));
      // free-for-outreach gaps: only when every semester is either dated or confirmed exam-free
      // (needs at least one dated semester, so "no exams announced anywhere" stays unknown, as the server counts it)
      const reliable = exRows.length > 0 && exRows.some((r) => isoOnly(r.endsem_start) && isoOnly(r.endsem_end)) && exRows.every((r) => r.status !== 'Unverified'
        && (r.status === 'No Current Exams Found' || r.status === 'Completed' || (isoOnly(r.endsem_start) && isoOnly(r.endsem_end))));
      if (reliable) {
        const busy = wins.map((w) => [Math.max(dayIndex(w.start, t0), BACK), Math.min(dayIndex(w.end, t0) + 1, DAYS)]).filter(([a, b]) => b > a).sort((a, b) => a[0] - b[0]);
        let p = BACK;
        const gaps = [];
        for (const [a, b] of busy) { if (a > p) gaps.push([p, a]); p = Math.max(p, b); }
        if (p < DAYS) gaps.push([p, DAYS]);
        for (const [a, b] of gaps) {
          svg.append(S('rect', { x: a * DW, y: y + ROW - 6, width: (b - a) * DW, height: 4, rx: 2, class: 'g-gap' },
            S('title', null, `${c.name}: no exams ${fmt.date(addDays(t0, a))} – ${fmt.date(addDays(t0, b - 1))}`)));
        }
      }
      if (!wins.some((w) => dayIndex(w.end, t0) >= 0 && dayIndex(w.start, t0) <= DAYS)) {
        const msg = !wins.length ? (exRows.every((r) => r.status === 'No Current Exams Found') ? 'No exams announced' : 'No confirmed dates yet') : 'No exams in this period';
        svg.append(S('text', { x: todayX + 8, y: y + ROW / 2 + 4, class: 'g-pending' }, msg));
      }
      for (const w of wins) {
        if (dayIndex(w.end, t0) < 0 || dayIndex(w.start, t0) > DAYS) continue;
        const cls = w.sem === '4-1' ? 's41' : 's31';
        const ly = y + 7 + (w.sem === '4-1' ? 15 : 0);
        const range = w.start === w.end ? fmt.date(w.start) : `${fmt.date(w.start)} – ${fmt.date(w.end)}`;
        const trustTxt = { confirmed: '', planned: ' · planned, not confirmed', conflict: ' · sources conflict' }[w.trust];
        const label = `${c.name}, ${w.sem}: ${w.text}, ${range}${trustTxt}. Press Enter to edit.`;
        const x1 = x(w.start);
        const x2 = w.openEnded && w.kind !== 'endsem' ? x1 + DW : Math.max(x(addDays(w.end, 1)), x1 + 4);
        const attrs = { x: x1, y: ly, width: x2 - x1, height: 11, rx: 3, tabindex: '0', role: 'button', 'aria-label': label,
          class: ['g-bar', cls, `k-${w.kind}`, `t-${w.trust}`].join(' ') };
        if (w.kind === 'lab') attrs.fill = `url(#hatch-${cls}-${uid})`;
        const bar = S('rect', attrs, S('title', null, `${w.sem} · ${w.text}\n${range}${trustTxt}`));
        bar.addEventListener('click', () => editExam(c, w.r));
        bar.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); editExam(c, w.r); } });
        svg.append(bar);
      }
      y += ROW;
    }
  }
  svg.append(S('line', { x1: todayX, x2: todayX, y1: HEAD - 16, y2: totalH, class: 'g-today' }));
  const td = new Date(today() + 'T00:00:00Z');
  svg.append(S('rect', { x: todayX - 17, y: HEAD - 21, width: 34, height: 16, rx: 8, class: 'g-today-pill' }));
  svg.append(S('text', { x: todayX, y: HEAD - 9.5, 'text-anchor': 'middle', class: 'g-today-label' }, `${td.getUTCDate()} ${td.toLocaleDateString('en-IN', { month: 'short', timeZone: 'UTC' })}`));

  const lg = (cls, text) => h('span', null, h('i', { class: `lg ${cls}`, 'aria-hidden': 'true' }), text);
  return h('div', { class: 'ex-timeline' },
    h('div', { class: 'ex-legend' },
      lg('lg-31', '3-1 (third year)'), lg('lg-41', '4-1 (final year)'), lg('lg-mid', 'Mid exams'), lg('lg-lab', 'Labs / practicals'),
      lg('lg-planned', 'Planned — not confirmed'), lg('lg-gap', 'Free for outreach'), lg('lg-today', 'Today')),
    h('p', { class: 'adm-muted ex-hint' }, matchMedia('(hover: none)').matches
      ? 'Each college has two lanes: top 3-1, bottom 4-1. Tap a bar to see its dates and edit them. Swipe sideways for later weeks.'
      : 'Each college has two lanes: top 3-1, bottom 4-1. Hover a bar for dates; click it (or press Enter) to edit. Scroll sideways for later weeks.'),
    h('div', { class: 'ex-gantt', tabindex: '0', role: 'region', 'aria-label': 'Exam timeline' }, labels, h('div', { class: 'ex-gantt-scroll' }, svg)));
}

/* ================================================================ List (one row per college) */
function list(rows) {
  const { h, ui, fmt } = cur.ctx;
  const ORDER = { in_exams: 0, exams_soon: 1, clear: 2, unknown: 3 };
  const semRow = (c, sem) => (c.rows || []).find((r) => r.semester === sem) || { semester: sem, status: 'Unverified', _missing: true };
  const data = rows.map((c) => ({
    c, name: c.name, state: ORDER[c.exam_state] ?? 9,
    s31: isoOnly(semRow(c, '3-1').endsem_start) || '9999', s41: isoOnly(semRow(c, '4-1').endsem_start) || '9999',
    outreach: fourOneDone(c) ? '0000' : (c.outreach_from || null),
  }));
  const semCell = (c, sem) => {
    const r = semRow(c, sem);
    const edit = ui.button({ label: r._missing ? 'Add dates' : 'Edit', icon: r._missing ? 'plus' : 'edit', tone: 'ghost', size: 'sm',
      ariaLabel: `${r._missing ? 'Add' : 'Edit'} ${sem} exam details for ${c.name}`, onClick: () => editExam(c, r) });
    if (typeof ui.writeOnly === 'function') ui.writeOnly(edit);
    if (r._missing) return h('div', { class: 'ex-sem is-missing' }, h('span', { class: 'adm-muted' }, 'Not tracked yet'), edit);
    const cd = countdown(r);
    const s = r.endsem_start, e = r.endsem_end;
    const show = (v) => (isoOnly(v) ? fmt.date(v) : v ? `“${v}”` : '?');
    const dates = !s && !e ? null : h('span', { class: 'ex-sem__dates' }, s && e ? `${show(s)} – ${show(e)}` : show(s || e));
    const tr = trust(r);
    const pending = isPending(r);
    return h('div', { class: 'ex-sem' },
      h('div', { class: 'ex-sem__top' },
        ui.badge(pending ? 'Dates not confirmed' : EXAM_STATUS_LABEL[r.status] || r.status || '—', pending ? 'neutral' : STATUS_TONE[r.status] || 'neutral'),
        tr !== 'confirmed' && !pending && (s || e || r.mid_window) ? h('span', { class: 'ex-flag' }, tr === 'conflict' ? 'sources conflict' : 'planned') : null),
      dates,
      h('span', { class: ['ex-sem__cd', `is-${cd.tone}`] }, cd.text),
      h('div', { class: 'ex-sem__src' },
        r.confidence ? h('span', { class: ['ex-conf', `is-${CONF_TONE[r.confidence] || 'neutral'}`], title: `${r.evidence ? evidenceLabel(r.evidence) : 'No evidence recorded'} — ${r.confidence} confidence` }, `${r.confidence} confidence`) : null,
        sourceLink(r.source_url),
        r.verified_on ? h('span', { class: 'adm-muted' }, `checked ${fmt.date(r.verified_on)}`) : null),
      edit);
  };
  // dataTable: columns hide / turn into cards by the table's own width (responsive.md §4)
  return ui.dataTable({
    caption: 'Exam dates by college',
    rowKey: (r) => r.c.college_id,
    columns: [
      { key: 'name', label: 'College', primary: true, priority: 1, minWidth: 220, render: ({ c }) => h('div', { class: 'ex-col' },
        h('a', { href: `#/college/${c.college_id}` }, c.name),
        h('span', { class: 'adm-muted' }, cur.dName.get(c.district_id) || '')) },
      { key: 'state', label: 'Right now', priority: 1, minWidth: 140, render: ({ c }) => ui.statusBadge('exam_state', c.exam_state) },
      { key: 's31', label: '3-1 (third year)', priority: 2, minWidth: 220, render: ({ c }) => semCell(c, '3-1') },
      { key: 's41', label: '4-1 (final year)', priority: 1, minWidth: 220, render: ({ c }) => semCell(c, '4-1') },
      { key: 'outreach', label: 'Final-year outreach', priority: 2, minWidth: 160, render: ({ c }) => (fourOneDone(c)
        ? h('span', { class: 'ex-out-ok' }, 'Open now')
        : c.outreach_from ? h('span', null, `from ${fmt.date(c.outreach_from)}`, h('small', { class: 'adm-muted' }, ` ${fmt.days(c.outreach_from)}`))
          : h('span', { class: 'adm-muted' }, '4-1 dates not known')) },
    ],
    rows: data,
    empty: 'No colleges match',
    mobile: 'cards',
  });
}

function sourceLink(src) {
  const { h } = cur.ctx;
  if (!src) return h('span', { class: 'ex-nosrc' }, 'no source');
  const urls = String(src).split(/\s*[;,]\s+|\s+/).filter((u) => /^https?:\/\//.test(u));
  if (!urls.length) return h('span', { class: 'adm-muted', title: src }, 'source noted');
  return h('span', { class: 'ex-links' }, urls.map((u, i) => {
    let host = u; try { host = new URL(u).hostname.replace(/^www\./, ''); } catch { /* keep */ }
    return h('a', { href: u, target: '_blank', rel: 'noopener noreferrer', title: u }, urls.length > 1 ? `${host} (${i + 1})` : host);
  }));
}

/* ================================================================ Edit modal */
function editExam(c, r) {
  const { h, ui, api, fmt } = cur.ctx;
  const isNew = !r.id;
  let n = 0;
  const field = (label, input, help, opts = {}) => {
    const id = `exf-${++n}`;
    if (input.matches?.('input,select,textarea')) input.id = id;
    return h('div', { class: ['td-field', opts.full && 'td-field--full'] },
      h('label', { class: 'td-field__label', for: id }, label, opts.req ? h('span', { class: 'td-field__req', 'aria-hidden': 'true' }, ' *') : null),
      input, help ? h('div', { class: 'td-field__help' }, help) : null);
  };
  const sel = (opts, v, labels = {}) => {
    const all = v && !opts.includes(v) ? [v, ...opts] : opts;
    const s = h('select', { class: 'td-input td-select' }, all.map((o) => h('option', { value: o }, labels[o] || o)));
    s.value = v || all[0];
    return s;
  };
  /** A date that can also be free text ("Dec 2026, no date yet"). Only exact dates drive the timeline/status. */
  const dateOrText = (v) => {
    let mode = v && !isoOnly(v) ? 'text' : 'date';
    const dateIn = h('input', { type: 'date', class: 'td-input td-num', value: isoOnly(v) || '' });
    const textIn = h('input', { type: 'text', class: 'td-input', value: v && !isoOnly(v) ? v : '', placeholder: 'e.g. Dec 2026 (no date yet)' });
    const note = h('div', { class: 'td-field__help' });
    const sw = h('button', { type: 'button', class: 'ex-switch' });
    const box = h('div', { class: 'ex-dt' });
    const paint = () => {
      box.replaceChildren(mode === 'date' ? dateIn : textIn, sw);
      sw.textContent = mode === 'date' ? 'Type text instead' : 'Pick an exact date';
      note.textContent = mode === 'date' ? '' : 'Text is kept as a note. Only exact dates appear on the timeline and count towards the exam status.';
    };
    sw.addEventListener('click', () => { mode = mode === 'date' ? 'text' : 'date'; paint(); (mode === 'date' ? dateIn : textIn).focus(); });
    paint();
    return { node: h('div', null, box, note), get value() { return (mode === 'date' ? dateIn.value : textIn.value).trim(); }, get iso() { return mode === 'date' ? dateIn.value : isoOnly(textIn.value); }, focus: () => (mode === 'date' ? dateIn : textIn).focus() };
  };
  const windowPreview = (input, counts) => {
    const out = h('div', { class: 'td-field__help ex-preview', 'aria-live': 'polite' });
    const upd = () => {
      const v = input.value.trim();
      if (!v) { out.textContent = 'Optional. Write dates like 2026-11-16 to 2026-11-21 so they appear on the timeline.'; out.className = 'td-field__help ex-preview'; return; }
      const ws = textWindows(v, {});
      out.className = `td-field__help ex-preview ${ws.length ? 'is-ok' : 'is-warn'}`;
      out.textContent = ws.length
        ? `On the timeline: ${ws.map((w) => (w.start === w.end ? fmt.date(w.start) : `${fmt.date(w.start)} – ${fmt.date(w.end)}`)).join(', ')}${counts ? '' : ' (shown only; labs do not change the exam status)'}`
        : 'No date range found — this stays a note. Use the form 2026-11-16 to 2026-11-21.';
    };
    input.addEventListener('input', upd);
    upd();
    return out;
  };

  const status = sel(STATUSES, r._missing ? 'Unverified' : r.status, EXAM_STATUS_LABEL);
  const examBody = h('input', { type: 'text', class: 'td-input', value: r.exam_body || '', placeholder: 'e.g. JNTUK, or the college (autonomous)' });
  const s = dateOrText(r.endsem_start), e = dateOrText(r.endsem_end);
  const mid = h('input', { type: 'text', class: 'td-input', value: r.mid_window || '', placeholder: 'e.g. Mid-II 2026-11-09 to 2026-11-14' });
  const lab = h('input', { type: 'text', class: 'td-input', value: r.lab_window || '', placeholder: 'e.g. Practicals 2026-11-23 to 2026-11-28' });
  const src = h('input', { type: 'url', class: 'td-input', value: r.source_url || '', placeholder: 'https://… (exam notice or timetable)' });
  const evidence = sel(EVIDENCE, r.evidence || 'Unverified', EVIDENCE_LABEL);
  const conf = sel(CONFIDENCE, r.confidence || 'Low');
  const notice = dateOrText(r.notice_date);
  const verified = h('input', { type: 'date', class: 'td-input td-num', value: today() });
  const notes = h('textarea', { class: 'td-input', rows: 3 }, r.notes || '');
  const err = h('div', { class: 'td-form__error', role: 'alert', hidden: true });
  const srcErr = h('div', { class: 'td-field__error', 'aria-live': 'polite' });
  const dateErr = h('div', { class: 'td-field__error td-field--full', 'aria-live': 'polite' });
  const checkSrc = () => {
    const v = src.value.trim();
    const need = ['In Progress', 'Upcoming'].includes(status.value) && !v;
    srcErr.textContent = need ? 'Needed when the status is "In progress" or "Upcoming" — paste the notice or timetable link so others can check it.'
      : v && !/^https?:\/\/\S+$/i.test(v) ? 'Start the link with https:// (or leave it empty).' : '';
    src.setAttribute('aria-invalid', String(!!srcErr.textContent));
    return !srcErr.textContent;
  };
  status.addEventListener('change', checkSrc);
  src.addEventListener('input', checkSrc);
  const meta = r.updated_at && !isNew ? h('p', { class: 'adm-muted ex-meta' }, `Last changed ${fmt.date(r.updated_at)} by ${r.updated_by || 'unknown'}${r.verified_on ? ` · last checked ${fmt.date(r.verified_on)}` : ''}`) : null;

  const body = h('div', { class: 'v-adm ex-form' },
    h('p', { class: 'ex-form__who' }, h('strong', null, c.name), ` · semester ${r.semester} (${r.semester === '4-1' ? 'final year' : 'third year'})`), meta, err,
    h('fieldset', { class: 'ex-fs' }, h('legend', null, 'Exam dates'),
      h('div', { class: 'td-form__grid' },
        field('Status', status), field('Exams set by', examBody, 'The university, or the college itself if it is autonomous.'),
        field('End-semester exams start', s.node), field('End-semester exams end', e.node), dateErr,
        field('Mid exams', h('div', null, mid, windowPreview(mid, true)), null, { full: true }),
        field('Labs / practicals', h('div', null, lab, windowPreview(lab, false)), null, { full: true }))),
    h('fieldset', { class: 'ex-fs' }, h('legend', null, 'Where did this come from?'),
      h('div', { class: 'td-form__grid' },
        field('Source link', h('div', null, src, srcErr), null, { full: true }),
        field('Kind of source', evidence), field('How sure are we?', conf),
        field('Notice published on', notice.node), field('Last checked on', verified, 'Defaults to today — the day you looked at the source.'),
        field('Notes', notes, null, { full: true }))));

  const save = async () => {
    err.hidden = true; dateErr.textContent = '';
    if (!checkSrc()) { src.focus(); return false; }
    if (s.iso && e.iso && e.iso < s.iso) { dateErr.textContent = 'The end date is before the start date.'; e.focus(); return false; }
    try { await cur.ctx.ensureUser?.(); } catch { return false; }
    const payload = {
      status: status.value, exam_body: examBody.value.trim() || null,
      endsem_start: s.value || null, endsem_end: e.value || null,
      mid_window: mid.value.trim() || null, lab_window: lab.value.trim() || null,
      source_url: src.value.trim() || null, evidence: evidence.value, confidence: conf.value,
      notice_date: notice.value || null, verified_on: verified.value || today(), notes: notes.value.trim() || null,
    };
    try {
      if (isNew) await api.post('/exams', { college_id: c.college_id, semester: r.semester, ...payload });
      else await api.patch(`/exams/${r.id}`, payload);
    } catch (ex) {
      err.textContent = [ex.message, ...Object.entries(ex.fields || {}).map(([k, v]) => `${k}: ${v}`)].join(' — ');
      err.hidden = false;
      return false;
    }
    ui.toast(`${r.semester} exam details saved for ${c.name}`, 'good');
    load({ quiet: true });
    return true;
  };
  checkSrc();
  ui.modal({ title: isNew ? 'Add exam details' : 'Edit exam details', body, wide: true,
    actions: [{ label: 'Cancel', tone: 'ghost' }, { label: 'Save', tone: 'primary', onClick: save }] });
}
