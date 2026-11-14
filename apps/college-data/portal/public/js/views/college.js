// Tech Drona portal — college page (#/college/:id), full width (CL).
// Tabs: Overview · Team · Contacts & calls · Targets & performance · Branches · Exams · Activity.
// Old tab ids keep working: enrollment → performance, followups / history → activity.
// Team actions use THE person / target dialogs from forms.js (TM). College create/edit lives in college-form.js.
import * as forms from './forms.js';
import {
  openBranch, openBranchId, closeBranch, sourceLink, getMeta, vb, vbo, txt, personBranchIds, branchLabel, contactLinks, progressCell, btn, callout, cardify,
  crumbs, followupList, activityList, enrollmentList, todayStr, ROLE_LABEL, CATEGORY_LABEL, ISSUE_LABEL, pctOf,
} from './branch.js';
import {
  getPerformance, perfRows, perfChip, remainingText, pctText, pctNumText, contactActions, planIndex, pLevelOf, verifiedBadge, itemsOf, unassignedOf, PERF_STATUS,
} from './dashboard.js';
import { editCollege as editCollegeForm, verifyFields, VERIFY_FIELDS, fieldVerification, verificationBadge, tracksVerification } from './college-form.js';
import { collegeLiveCard, researchBadge } from './live.js';

const TABS = ['overview', 'team', 'calls', 'performance', 'branches', 'exams', 'activity'];
const TAB_ALIAS = { enrollment: 'performance', enrollments: 'performance', targets: 'performance', followups: 'activity', history: 'activity', contacts: 'calls' };
let ui_state = { relevantOnly: false, sort: 'relevance', branchView: 'cards', period: 'programme' };
try { Object.assign(ui_state, JSON.parse(localStorage.getItem('td.college.ui2') || '{}')); } catch { /* ignore */ }
const saveUi = () => { try { localStorage.setItem('td.college.ui2', JSON.stringify(ui_state)); } catch { /* ignore */ } };

function hashQuery() {
  const i = location.hash.indexOf('?');
  return new URLSearchParams(i >= 0 ? location.hash.slice(i + 1) : '');
}
function hashWith(id, kv) {
  const q = hashQuery();
  for (const [k, v] of Object.entries(kv)) { if (v == null || v === '') q.delete(k); else q.set(k, v); }
  const s = q.toString();
  return `#/college/${encodeURIComponent(id)}${s ? '?' + s : ''}`;
}
/** Update the URL without a re-render (tab switches). */
/** a tab change is a discrete step: push so Back returns to the previous tab (D8) */
function pushHashQuery(id, kv) {
  const url = hashWith(id, kv);
  if (url === location.hash) return;
  try { history.pushState(null, '', url); } catch { /* ignore */ }
}
function setHashQuery(id, kv) {
  try { history.replaceState(history.state, '', hashWith(id, kv)); } catch { /* ignore */ }
  if (cache && cache.id === id) cache.hash = location.hash;
}
const noBranch = (hash) => String(hash || '').replace(/([?&])branch=[^&]*(&|$)/, (m, a, b) => (b ? a : '')).replace(/[?&]$/, '');

/* ------------------------------------------------------------------ branch drawer <-> URL
   Opening a branch pushes `branch=<id>` into the hash, so the drawer is deep-linkable and Back closes it.
   When only the branch param changed we re-attach the already-built page (no refetch, scroll kept). */
let cache = null; // { id, hash, root, current, crumbs, scroll }
let pushedBranch = false;

/** Bring the active tab into view inside its strip, horizontally only (D6: the page must not scroll past the title). */
function revealActiveTab(root) {
  const tab = root && root.querySelector('.vc-tabs [role="tab"][aria-selected="true"]');
  const strip = tab && tab.parentElement;
  if (!strip || strip.scrollWidth <= strip.clientWidth + 1) return;
  const left = tab.offsetLeft - strip.offsetLeft - (strip.clientWidth - tab.offsetWidth) / 2;
  strip.scrollLeft = Math.max(0, Math.min(left, strip.scrollWidth - strip.clientWidth));
}
function scrollerOf(el) {
  for (let p = el?.parentElement; p; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY;
    if ((o === 'auto' || o === 'scroll') && p.scrollHeight > p.clientHeight) return p;
  }
  return document.scrollingElement;
}
function showBranch(ctx, branchId) {
  const id = current?.id;
  if (!id) { openBranch(branchId, ctx); return; }
  if (String(hashQuery().get('branch') || '') === String(branchId) && openBranchId() === String(branchId)) return;
  if (cache && cache.root) cache.scroll = scrollerOf(cache.root)?.scrollTop || 0;
  pushedBranch = true;
  location.hash = hashWith(id, { branch: branchId });
}
function openBranchFromUrl(ctx, id, branchId) {
  if (openBranchId() === String(branchId)) return;
  openBranch(branchId, ctx, {
    inCollege: true,
    onUserClose: () => {
      if (!location.hash.startsWith(`#/college/${encodeURIComponent(id)}`) || String(hashQuery().get('branch') || '') !== String(branchId)) return;
      if (pushedBranch) { pushedBranch = false; history.back(); return; }
      try { history.replaceState(history.state, '', hashWith(id, { branch: null })); } catch { /* ignore */ }
      if (cache) cache.hash = location.hash;
    },
  });
}

/* ------------------------------------------------------------------ exam helpers */
const ISO_RE = /(\d{4})-(\d{2})-(\d{2})|(\d{1,2})[./-](\d{1,2})[./-](\d{4})/g;
function datesIn(text) {
  if (!text) return [];
  const out = [];
  for (const m of String(text).matchAll(ISO_RE)) {
    if (m[1]) out.push(`${m[1]}-${m[2]}-${m[3]}`);
    else out.push(`${m[6]}-${m[5].padStart(2, '0')}-${m[4].padStart(2, '0')}`);
  }
  return out.sort();
}
function addDay(iso, n = 1) { return new Date(Date.parse(iso + 'T00:00:00Z') + n * 86400000).toISOString().slice(0, 10); }
function examWindows(rows) {
  const out = [];
  for (const r of rows || []) {
    const s = datesIn(r.endsem_start); const e = datesIn(r.endsem_end);
    const approx = /before|after|inferred|approx|tentative|~/i.test(`${r.endsem_start || ''} ${r.endsem_end || ''}`);
    if (s.length || e.length) out.push({ semester: r.semester, kind: 'End-sem exams', start: s[0] || null, end: e[e.length - 1] || s[s.length - 1] || null, approx });
    for (const [k, label] of [['mid_window', 'Mid exams'], ['lab_window', 'Lab exams']]) {
      const ds = datesIn(r[k]);
      if (ds.length) out.push({ semester: r.semester, kind: label, start: ds[0], end: ds[ds.length - 1], approx: /inferred|approx|tentative/i.test(r[k]) });
    }
  }
  return out;
}
function examInfo(d) {
  const r = d.rollup || {};
  const c = d.college || {};
  const today = todayStr();
  const wins = examWindows(d.exams);
  let state = d.exam?.exam_state || d.exam_state || c.exam_state || r.exam_state || null;
  if (!state && r.exams) state = ['in_exams', 'exams_soon', 'clear', 'unknown'].find((k) => r.exams[k] > 0) || null;
  let current = wins.filter((w) => !w.approx && w.start && w.end && w.start <= today && today <= w.end).sort((a, b) => a.end.localeCompare(b.end))[0] || null;
  let next = d.exam?.next_exam || d.next_exam || c.next_exam || r.next_exam || null;
  if (next && next.start && next.start <= today && today <= (next.end || next.start)) { current = current || next; next = null; }
  if (!next) next = wins.filter((w) => !w.approx && w.start && w.start > (current?.end || today)).sort((a, b) => a.start.localeCompare(b.start))[0] || null;
  let outreachFrom = d.exam?.outreach_from || d.outreach_from || c.outreach_from || r.outreach_from || null;
  if (!outreachFrom && !d.exam) {
    const ends = wins.filter((w) => !w.approx && w.semester === '4-1' && w.kind === 'End-sem exams' && w.end).map((w) => w.end).sort();
    if (ends.length) outreachFrom = addDay(ends[ends.length - 1]);
  }
  if (!state) {
    const allUnknown = (d.exams || []).every((x) => /unverified|no current/i.test(`${x.status} ${x.evidence}`));
    state = current ? 'in_exams' : next && (Date.parse(next.start) - Date.parse(today)) / 86400000 <= 14 ? 'exams_soon' : allUnknown ? 'unknown' : 'clear';
  }
  return { state, current, next, outreachFrom, wins };
}
function kindLabel(k) {
  const s = String(k || '').toLowerCase();
  return /end/.test(s) ? 'end-sem exams' : /mid/.test(s) ? 'mid exams' : /lab/.test(s) ? 'lab exams' : 'exams';
}
function examCountdown(ctx, info) {
  const { fmt, h } = ctx;
  const lines = [];
  if (info.current) {
    const n = Math.round((Date.parse(info.current.end) - Date.parse(todayStr())) / 86400000);
    lines.push(`${info.current.semester} ${kindLabel(info.current.kind)} running — ${n <= 0 ? 'ends today' : `ends ${fmt.date(info.current.end)} (in ${fmt.plural(n, 'day')})`}`);
  }
  if (info.next && info.next.start) {
    const n = Math.round((Date.parse(info.next.start) - Date.parse(todayStr())) / 86400000);
    if (n > 0) lines.push(`Next: ${info.next.semester ? info.next.semester + ' ' : ''}${kindLabel(info.next.kind)} start ${fmt.date(info.next.start)} — in ${fmt.plural(n, 'day')}${info.next.approx ? ' (approx.)' : ''}`);
  }
  if (info.outreachFrom) {
    lines.push(info.outreachFrom > todayStr() ? `Good time for outreach from ${fmt.date(info.outreachFrom)} (${fmt.days(info.outreachFrom)})` : `4-1 exams over since ${fmt.date(addDay(info.outreachFrom, -1))} — good time for outreach`);
  }
  if (!lines.length) return h('div', { class: 'vc-countdown' }, h('div', { class: 'vc-cd-sub' }, info.state === 'unknown' ? 'Dates not published yet. Confirm with the college before planning a visit.' : 'No upcoming exams known.'));
  return h('div', { class: 'vc-countdown' }, lines.map((l, i) => h('div', { class: i === 0 ? 'vc-cd-main' : 'vc-cd-sub' }, l)));
}

/* ------------------------------------------------------------------ data shaping */
const isActive = (p) => p && p.status !== 'inactive';
/** Own target / actual of a person row: /api/performance row (v4) → people target_summary (v4) → v3 fields. */
function personPerf(p, perfById) {
  const r = perfById && perfById.get(Number(p.id));
  if (r) return { target: r.target, min: r.min, max: r.max, actual: r.actual ?? r.actual_own, remaining: r.remaining, exceeded_by: r.exceeded_by, pct: r.pct, status: r.status, team: r.team, combined: r.combined, v4: true };
  const ts = p.target_summary;
  if (ts) return { target: ts.target, min: ts.min, max: ts.max, actual: p.actual_own ?? p.enrolled ?? 0, remaining: ts.remaining, exceeded_by: ts.exceeded_by, pct: ts.pct, status: ts.status, v4: true };
  return { target: p.target ?? null, actual: p.enrolled ?? 0, remaining: p.remaining, pct: p.pct != null ? p.pct * 100 : null, status: null };
}

function shape(d, plist) {
  const extra = new Map((plist || []).map((p) => [Number(p.id), p]));
  const people = (d.people || []).map((p) => ({ ...(extra.get(Number(p.id)) || {}), ...p }));
  for (const p of plist || []) if (!people.some((q) => Number(q.id) === Number(p.id))) people.push(p);
  const branches = (d.branches || []).map((b) => ({ ...b, rollup: b.rollup || {} }));
  const byId = new Map(people.map((p) => [Number(p.id), p]));
  for (const p of people) {
    p._branches = personBranchIds(p, branches);
    if (!p.reports_to_name && p.reports_to) p.reports_to_name = (p.lead && p.lead.name) || byId.get(Number(p.reports_to))?.full_name;
  }
  const unassigned = new Set(unassignedOf(people).map((p) => Number(p.id)));
  // ambassador leads are counted too when the server says they have no valid lead
  for (const p of people) if (p.role === 'ambassador_lead' && isActive(p) && p.assignment_status && p.assignment_status !== 'assigned') unassigned.add(Number(p.id));
  const cover = new Map(branches.map((b) => [Number(b.id), []]));
  for (const p of people) for (const bid of p._branches) cover.get(bid)?.push(p);
  for (const b of branches) {
    const list = cover.get(Number(b.id));
    b._people = list;
    b._ambs = list.filter((p) => p.role === 'ambassador');
    b._activeAmbs = b._ambs.filter(isActive);
    b._leads = list.filter((p) => p.role === 'ambassador_lead' && isActive(p));
    b._fu = (d.followups || []).filter((f) => f.scope_type === 'branch' && String(f.scope_id) === String(b.id));
    b._nextFu = b._fu.filter((f) => f.status === 'open' && f.due_date).sort((x, y) => x.due_date.localeCompare(y.due_date))[0] || null;
    b._gap = !!b.is_relevant && b._activeAmbs.length === 0;
  }
  const lead = people.find((p) => p.role === 'college_lead' && p.status === 'active') || people.find((p) => p.role === 'college_lead' && isActive(p)) || null;
  return { people, branches, byId, unassigned, lead };
}

function outreachStatus(ctx, b) {
  const { ui, fmt } = ctx;
  const r = b.rollup || {};
  if (b._gap) return ui.badge('No ambassador', 'bad');
  if (!b.is_relevant && !b._activeAmbs.length) return ui.badge('Not IT', 'neutral');
  if (r.target && r.on_track === false) return ui.statusBadge('diagnosis', r.diagnosis || 'behind_pace');
  if (r.target && r.on_track) return ui.statusBadge('on_track', true);
  if (r.reached) return ui.badge(`${fmt.num(r.reached)} reached`, 'info');
  return ui.badge('Not started', 'warn');
}

/* ------------------------------------------------------------------ render */
let current = null;

export async function render(el, params = {}, ctx) {
  const { h, ui, api } = ctx;
  const id = params.id;
  const q = hashQuery();
  const rawTab = params.tab || q.get('tab');
  const tab0 = TAB_ALIAS[rawTab] || rawTab;
  const tab = TABS.includes(tab0) ? tab0 : 'overview';
  const branchParam = params.branch || q.get('branch');

  // Only the branch param changed (drawer opened/closed, Back/Forward): re-attach the built page.
  if (cache && cache.id === id && cache.root && location.hash !== cache.hash && noBranch(location.hash) === noBranch(cache.hash)) {
    cache.hash = location.hash;
    current = cache.current;
    el.replaceChildren(cache.root);
    crumbs(ctx, cache.crumbs);
    const sc = scrollerOf(cache.root);
    if (sc && cache.scroll) sc.scrollTop = cache.scroll;
    if (branchParam) openBranchFromUrl(ctx, id, branchParam);
    else { pushedBranch = false; closeBranch(); }
    return;
  }

  if (!branchParam) closeBranch();
  el.replaceChildren(h('div', { class: 'v-college', 'aria-busy': 'true' }, loadingSkeleton(ctx)));
  try { ctx.map?.focusCollege?.(id); } catch { /* ignore */ }
  let d, meta, plist, plan;
  try {
    [d, meta, plist, plan] = await Promise.all([
      api.get(`/colleges/${encodeURIComponent(id)}`), getMeta(ctx),
      api.get('/people', { college: id }).then(itemsOf).catch(() => null),
      planIndex(ctx).catch(() => new Map()),
    ]);
  } catch (e) {
    cache = null;
    el.replaceChildren(h('div', { class: 'v-college' }, ui.emptyState({
      title: e.status === 404 ? 'College not found' : 'Could not load this college',
      text: e.status === 404 ? 'This link points to a college that is not in the portal. Pick one from the list instead.' : (e.message || 'Check your connection and try again.'),
      icon: 'warn',
      action: h('div', { class: 'vx-actions' },
        e.status === 404 ? null : btn(ctx, 'Try again', () => render(el, params, ctx), { tone: 'primary', icon: 'refresh' }),
        h('a', { href: '#/colleges', class: ['td-btn', e.status === 404 ? 'td-btn--primary' : 'td-btn--secondary'] }, 'Browse all colleges')),
    })));
    return;
  }
  const c = d.college || {};
  const r = d.rollup || {};
  const s = shape(d, plist);
  const district = (meta.districts || []).find((x) => x.id === c.district_id);
  const city = (meta.cities || []).find((x) => x.id === c.city_id);
  const ex = examInfo(d);
  const research = plan.get(c.id) || null;
  current = { id, d, s, meta, ex, research };

  const crumbItems = [
    { label: 'Colleges', href: '#/colleges' },
    district ? { label: district.name, href: `#/d/${district.id}` } : null,
    city ? { label: city.name, href: `#/d/${c.district_id}/${encodeURIComponent(city.id)}` } : null,
    { label: c.short_name || c.name },
  ].filter(Boolean);
  crumbs(ctx, crumbItems);

  const root = h('div', { class: 'v-college' });
  root.append(header(ctx, c, r, s, district, city, research));
  const openFu = (d.followups || []).filter((f) => f.status === 'open').length;
  const activeN = s.people.filter(isActive).length;
  const tabs = ui.tabs({
    tabs: [
      { id: 'overview', label: 'Overview', render: () => overviewTab(ctx, d, s, ex, research) },
      { id: 'team', label: 'Team', count: activeN || undefined, render: () => teamTab(ctx, d, s, research) },
      { id: 'calls', label: 'Contacts & calls', count: (d.contacts || []).length || undefined, render: () => callsTab(ctx, d) },
      { id: 'performance', label: 'Targets & performance', render: () => performanceTab(ctx, d, s, meta) },
      { id: 'branches', label: 'Branches', count: s.branches.length || undefined, render: () => branchesTab(ctx, d, s) },
      { id: 'exams', label: 'Exams', render: () => examsTab(ctx, d, ex) },
      { id: 'activity', label: 'Activity', count: openFu || undefined, render: () => activityTab(ctx, d, s) },
    ],
    active: tab,
    onChange: (t) => pushHashQuery(id, { tab: t === 'overview' ? null : t, branch: null }),
  });
  tabs.classList?.add('vc-tabs');
  root.append(tabs);
  el.replaceChildren(root);
  if (rawTab && rawTab !== tab && TAB_ALIAS[rawTab]) setHashQuery(id, { tab });
  // keep the active tab visible in the scrollable strip (phones) — horizontally only, never the page (D6)
  requestAnimationFrame(() => revealActiveTab(root));
  cache = { id, hash: location.hash, root, current, crumbs: crumbItems, scroll: 0 };
  if (branchParam) openBranchFromUrl(ctx, id, branchParam);
}

/** current is restored from the cache when only the branch param changes; the cache itself survives destroy(). */
export function destroy() {
  current = null;
  if (cache && !location.hash.startsWith(`#/college/${encodeURIComponent(cache.id)}`)) cache = null;
}

function loadingSkeleton(ctx) {
  const { h, ui } = ctx;
  return [
    h('div', { class: 'vc-head vc-head--skel' },
      h('div', { class: 'vc-head-main' },
        h('div', { class: 'td-skel', style: { width: '30%' } }),
        h('div', { class: 'td-skel td-skel--title', style: { width: '70%', height: '26px' } }),
        h('div', { class: 'td-skel', style: { width: '45%' } }))),
    ui.skeleton(4),
  ];
}

/* ------------------------------------------------------------------ header (compact; sticky on scroll) */
const autonomyText = (v) => (v === null || v === undefined || v === '' ? null : v === 1 || v === true || /^yes$/i.test(String(v)) ? 'Autonomous' : v === 0 || v === false || /^no$/i.test(String(v)) ? 'Not autonomous' : String(v));
const label = (c) => c.short_name || c.name;

function setCollegeTarget(ctx, c) {
  const opts = { scope_type: 'college', scope_id: c.id, label: label(c), college_id: c.id };
  return typeof forms.targetDialog === 'function' ? forms.targetDialog(ctx, opts) : forms.setTarget('college', c.id, ctx, { label: label(c) });
}
function addPerson(ctx, c, s, role, extra = {}) {
  const reports_to = role === 'college_lead' ? undefined : (extra.reports_to ?? (s.lead ? s.lead.id : undefined));
  return forms.addPerson(ctx, { college_id: c.id, role, ...extra, reports_to });
}

function header(ctx, c, r, s, district, city, research) {
  const { h, ui, fmt } = ctx;
  const p = pLevelOf(c, research ? new Map([[c.id, research]]) : null);
  const lead = s.lead;
  const leadLine = lead
    ? h('div', { class: 'vc-leadline' }, ui.icon('lead', { size: 16 }), h('span', { class: 'vx-muted' }, 'College lead'),
      h('a', { href: `#/person/${lead.id}`, class: 'vc-leadname' }, lead.full_name), lead.status === 'onboarding' ? ui.badge('Onboarding', 'warn') : null,
      contactActions(ctx, lead.phone, lead.email))
    : h('div', { class: 'vc-leadline is-missing' }, ui.icon('warn', { size: 16 }), h('span', null, 'No college lead yet'),
      ui.writeOnly ? ui.writeOnly(btn(ctx, 'Appoint', () => addPerson(ctx, c, s, 'college_lead'), { small: true, tone: 'primary' })) : btn(ctx, 'Appoint', () => addPerson(ctx, c, s, 'college_lead'), { small: true, tone: 'primary' }));
  const tgt = r.target > 0
    ? h('button', { type: 'button', class: 'vc-tgt', title: 'Open targets & performance', onClick: () => switchTab('performance') },
      h('span', { class: 'vc-tgt-top' }, h('strong', { class: 'td-num' }, `${fmt.num(r.enrolled ?? 0)} / ${fmt.num(r.target)}`), h('span', { class: 'vx-muted vx-small' }, 'confirmed'),
        h('span', { class: 'vc-tgt-pct td-num' }, pctText(r.pct))),
      ui.progress({ target: r.target, done: r.enrolled ?? 0, size: 'sm' }),
      h('span', { class: 'vc-tgt-sub vx-small' }, remainingText(r) || '', r.pace_status && PERF_STATUS[r.pace_status] ? perfChip(ctx, r.pace_status) : r.on_track != null ? ui.statusBadge('on_track', r.on_track) : null))
    : h('div', { class: 'vc-tgt is-empty' }, h('span', { class: 'vx-small' }, r.target === 0 ? 'Target 0' : 'No college target'),
      h('span', { class: 'vx-muted vx-small' }, `${fmt.num(r.enrolled ?? 0)} confirmed`),
      btn(ctx, 'Set target', () => setCollegeTarget(ctx, c), { small: true, icon: 'target' }));
  const menuItems = [
    { label: 'Add follow-up', icon: 'followup', writeOnly: true, onClick: () => forms.addFollowup(ctx, { scope_type: 'college', scope_id: c.id, college_id: c.id, label: label(c) }) },
    { label: 'Log activity', icon: 'clock', writeOnly: true, onClick: () => forms.logActivity(ctx, { college_id: c.id }) },
    { label: 'Add person to the team', icon: 'people', writeOnly: true, onClick: () => addPerson(ctx, c, s, lead ? 'ambassador' : 'college_lead') },
    { label: r.target > 0 ? 'Change college target' : 'Set college target', icon: 'target', writeOnly: true, onClick: () => setCollegeTarget(ctx, c) },
    { label: 'Edit college details', icon: 'edit', writeOnly: true, onClick: () => editCollegeForm(ctx, c.id) },
    { label: 'Research plan for this college', icon: 'analytics', onClick: () => ctx.navigate(`#/plan?college=${encodeURIComponent(c.id)}`) },
    { label: 'Change history', icon: 'audit', onClick: () => switchTab('activity') },
  ];
  const more = typeof ui.menu === 'function' ? ui.menu({ label: 'More', icon: 'more', items: menuItems, tone: 'secondary', ariaLabel: 'More actions for this college' }) : null;
  const place = [city?.name, district?.name || c.district_id].filter(Boolean);
  return h('header', { class: 'vc-head' },
    h('div', { class: 'vc-head-main' },
      h('div', { class: 'vc-kicker' },
        c.sno ? h('span', { class: 'vx-muted', title: 'Serial number in the master list' }, `#${c.sno}`) : null,
        p ? ui.badge(p, p === 'P1' ? 'brand' : p === 'Hold' ? 'neutral' : 'info') : null,
        c.targeted ? ui.badge('Targeted', 'brand') : ui.badge('Not targeted', 'neutral'),
        ui.statusBadge('op_status', c.op_status || 'pending'),
        c.data_status ? verifiedBadge(ctx, c.data_status === 'partly' ? 'partly' : c.data_status) : null,
        c.is_demo ? ui.badge('DEMO', 'bad') : null),
      h('h1', { class: 'vc-title' }, c.name || c.short_name || c.id),
      h('div', { class: 'vc-loc' }, ui.icon('map', { size: 14 }),
        c.short_name && c.short_name !== c.name ? h('span', { class: 'vc-short' }, c.short_name) : null,
        h('span', null, city ? h('a', { href: `#/d/${c.district_id}/${encodeURIComponent(city.id)}` }, city.name) : null,
          city && district ? ', ' : null,
          district ? h('a', { href: `#/d/${district.id}` }, district.name) : (place.length ? place.join(', ') : '—'))),
      leadLine),
    h('div', { class: 'vc-head-side' }, tgt,
      h('div', { class: 'vc-head-acts', role: 'toolbar', 'aria-label': 'College actions' },
        btn(ctx, 'Log call', () => forms.logCall(ctx, { college_id: c.id, contacts: current?.d?.contacts, college_label: label(c) }), { icon: 'phone', tone: 'primary', class: 'td-write-only' }),
        btn(ctx, 'Record enrollment', () => forms.recordEnrollment(ctx, { college_id: c.id }), { icon: 'plus', class: 'td-write-only vc-act-enrol' }),
        more)));
}

function switchTab(t) {
  const btnEl = document.querySelector(`.v-college .vc-tabs [role="tab"][data-tab="${t}"]`);
  if (btnEl) { btnEl.click(); revealActiveTab(btnEl.closest('.v-college')); return; }
  const id = current?.id;
  if (id) location.hash = `#/college/${id}?tab=${t}`;
}

/* ------------------------------------------------------------------ overview */
function overviewTab(ctx, d, s, ex, research) {
  const { h, ui, fmt } = ctx;
  const c = d.college || {};
  const r = d.rollup || {};
  const wrap = h('div', { class: 'vc-tab vc-overview' });
  const relevant = s.branches.filter((b) => b.is_relevant);
  const gaps = s.branches.filter((b) => b._gap);
  const ambs = s.people.filter((p) => isActive(p) && (p.role === 'ambassador' || p.role === 'ambassador_lead'));
  const cc = (d.call_info && d.call_info.contact_counts) || {};
  const K = (o) => (typeof ui.kpi === 'function' ? ui.kpi(o) : ui.statCard({ ...o, onClick: o.onClick }));
  wrap.append(h('div', { class: 'vc-kpis' },
    K({ label: 'College lead', value: h('span', { class: 'vc-kpi-text', title: s.lead ? s.lead.full_name : null }, s.lead ? s.lead.full_name : 'None'), sub: s.lead ? ROLE_LABEL.college_lead : 'Appoint one', tone: s.lead ? 'good' : 'bad', icon: 'lead', onClick: () => switchTab('team') }),
    K({ label: 'Ambassadors', value: fmt.num(ambs.length), sub: [research && research.ambassadors_research != null ? `${fmt.num(research.ambassadors_research)} suggested` : null, s.unassigned.size ? `${fmt.num(s.unassigned.size)} unassigned` : null].filter(Boolean).join(' · ') || null, tone: s.unassigned.size ? 'warn' : undefined, icon: 'ambassador', onClick: () => switchTab('team') }),
    K({ label: 'Confirmed', value: r.target > 0 ? `${fmt.num(r.enrolled ?? 0)} / ${fmt.num(r.target)}` : fmt.num(r.enrolled ?? 0), sub: r.target > 0 ? `${pctText(r.pct)} · ${remainingText(r) || ''}` : 'No target yet', icon: 'target', onClick: () => switchTab('performance') }),
    K({ label: 'IT branches covered', value: relevant.length ? `${fmt.num(relevant.length - gaps.length)} / ${fmt.num(relevant.length)}` : '—', sub: gaps.length ? `${fmt.plural(gaps.length, 'branch', 'branches')} without ambassador` : relevant.length ? 'all covered' : 'no IT branches recorded', tone: gaps.length ? 'warn' : undefined, icon: 'branch', onClick: () => switchTab('branches') }),
    K({ label: 'Contacts', value: fmt.num(cc.total ?? (d.contacts || []).length), sub: cc.working ? `${fmt.num(cc.working)} working` : 'none confirmed working', icon: 'phone', onClick: () => switchTab('calls') }),
    K({ label: 'Exams', value: h('span', { class: 'vc-kpi-text' }, ui.statusBadge('exam_state', ex.state || 'unknown')), sub: ex.outreachFrom && ex.outreachFrom > todayStr() ? `outreach from ${fmt.date(ex.outreachFrom)}` : null, icon: 'exam', onClick: () => switchTab('exams') })));
  wrap.append(collegeLiveCard(ctx, c.id, c)); // live official-source data (views/live.js)

  // next steps (what is missing), each with its action
  const steps = [];
  const w = (n) => (ui.writeOnly ? ui.writeOnly(n) : n);
  if (!s.lead) steps.push(callout(ctx, 'bad', 'No college lead appointed', 'One student is accountable for the whole college; ambassadors report to them.', w(btn(ctx, 'Appoint college lead', () => addPerson(ctx, c, s, 'college_lead'), { small: true, tone: 'primary' }))));
  if (s.unassigned.size) steps.push(callout(ctx, 'warn', `${fmt.plural(s.unassigned.size, 'person', 'people')} without a valid lead`, 'They need a lead in this college to report to.', btn(ctx, 'Assign in Team', () => switchTab('team'), { small: true })));
  if (gaps.length) steps.push(callout(ctx, 'warn', `${fmt.plural(gaps.length, 'IT branch has', 'IT branches have')} no ambassador`, gaps.map(branchLabel).join(', '), w(btn(ctx, 'Recruit', () => addPerson(ctx, c, s, 'ambassador', { branch_ids: [gaps[0].id] }), { small: true }))));
  if (!(d.contacts || []).length) steps.push(callout(ctx, 'info', 'No contact numbers yet', c.phone ? `The listing has ${c.phone}. Add it so calls can be logged.` : 'Add the TPO, principal or office number.', w(btn(ctx, 'Add contact', () => forms.addContact(ctx, { college_id: c.id }), { small: true }))));
  if (!(r.target > 0) && r.target !== 0) steps.push(callout(ctx, 'info', 'No college target', research && research.research_target ? `Research suggests ${fmt.num(research.research_target.min)}–${fmt.num(research.research_target.max)} (average ${fmt.num(research.research_target.avg)}).` : 'Set one to track pace.', w(btn(ctx, 'Set target', () => setCollegeTarget(ctx, c), { small: true }))));
  if (steps.length) wrap.append(ui.section({ title: 'Next steps', body: h('div', { class: 'vc-steps' }, steps) }));

  wrap.append(ui.section({
    title: 'College information',
    sub: h('span', null, researchBadge(), tracksVerification(c) ? ' Each value shows whether it is verified (with source and date) or unverified.' : null),
    actions: w(btn(ctx, 'Edit details', () => editCollegeForm(ctx, c.id), { small: true, icon: 'edit' })),
    body: collegeInfo(ctx, c),
  }));
  if (research) wrap.append(researchBlock(ctx, research, s));
  return wrap;
}

/** College facts; tracked fields carry their verification state and a "Mark verified" action (R13). */
function collegeInfo(ctx, c) {
  const { h, ui, fmt } = ctx;
  const track = tracksVerification(c);
  const vrow = (field, labelText, value) => {
    const v = track ? fieldVerification(c, field) : null;
    const actions = track && value ? (v.state === 'verified'
      ? h('button', { type: 'button', class: 'vx-linkbtn td-linkbtn vx-small td-write-only', onClick: () => verifyFields(ctx, c, [field], { clear: true }) }, 'Mark unverified')
      : h('button', { type: 'button', class: 'vx-linkbtn td-linkbtn vx-small td-write-only', onClick: () => verifyFields(ctx, c, [field]) }, 'Mark verified')) : null;
    return [labelText, h('div', { class: 'vc-vval' }, h('span', { class: 'vc-vval-v' }, value || (track ? h('span', { class: 'vx-muted' }, '—') : txt(ctx, null))), track ? verificationBadge(ctx, c, field) : null, actions)]; // D7: an empty tracked field shows only "Missing"
  };
  const contactNode = (k, v) => (!v ? null : k === 'phone' ? h('span', { class: 'vc-cphone' }, v, contactActions(ctx, String(v).split(/[\/,;]/)[0].trim(), null))
    : k === 'email' ? h('a', { href: `mailto:${v}` }, v) : /^https?:\/\//i.test(v) ? h('a', { href: v, target: '_blank', rel: 'noopener' }, v.replace(/^https?:\/\//, '').slice(0, 60)) : v);
  const unverifiedN = track ? VERIFY_FIELDS.filter(([f]) => c[f] && fieldVerification(c, f).state !== 'verified').length : 0;
  const yn = (v) => (v === 'yes' ? ui.badge('Yes', 'good') : v === 'no' ? ui.badge('No', 'bad') : h('span', { class: 'vx-muted' }, 'unknown'));
  return h('div', null,
    track && unverifiedN ? h('div', { class: 'vc-vbar' }, h('span', null, `${fmt.plural(unverifiedN, 'value')} not verified yet.`),
      h('button', { type: 'button', class: 'vx-linkbtn td-linkbtn td-write-only', onClick: () => verifyFields(ctx, c, VERIFY_FIELDS.filter(([f]) => c[f] && fieldVerification(c, f).state !== 'verified').map(([f]) => f)) }, 'Verify them with one source')) : null,
    ui.kv([
      vrow('name', 'Official name', c.name),
      ['Also known as', [c.short_name, ...(Array.isArray(c.aliases) ? c.aliases : [])].filter((x, i, a) => x && a.indexOf(x) === i && x !== c.name).join(', ') || '—'],
      vrow('district_id', 'District', c.district_name || c.district_id),
      vrow('city_id', 'City / town', c.city_name || c.city_id),
      vrow('phone', 'Phone', contactNode('phone', c.phone)),
      vrow('email', 'Email', contactNode('email', c.email)),
      vrow('website', 'Website', contactNode('website', c.website)),
      ['Address', c.address || txt(ctx, null)],
      vrow('ownership', 'Ownership', c.ownership),
      vrow('affiliation', 'Affiliation', c.affiliation),
      ['Autonomy', autonomyText(c.autonomous) || txt(ctx, null)],
      ['NAAC / NIRF / tier', [c.naac, c.nirf ? `NIRF ${c.nirf}` : null, c.tier].filter(Boolean).join(' · ') || txt(ctx, null)],
      vrow('op_status', 'Operating status', h('span', { class: 'vx-row' }, ui.statusBadge('op_status', c.op_status || 'pending'), c.op_status_source ? sourceLink(ctx, c.op_status_source, 'evidence') : null)),
      c.op_status_note ? ['Status evidence', h('span', { class: 'vx-small' }, c.op_status_note)] : null,
      ['Admitted students', h('span', { class: 'vx-row' }, h('span', null, '2025-26'), yn(c.op_2025_26), h('span', null, '2026-27'), yn(c.op_2026_27))],
      c.total_intake ? ['Total intake / year', h('span', null, fmt.num(c.total_intake), c.total_intake_source ? h('span', { class: 'vx-small' }, ' · ', sourceLink(ctx, c.total_intake_source)) : null)] : null,
      c.geo_precision ? ['Map location', c.geo_precision === 'exact' ? 'Exact' : c.geo_precision === 'pending' ? 'Not located yet' : `Approximate (${c.geo_precision} level)`] : null,
      c.updated_at ? ['Last updated', `${fmt.date(c.updated_at)}${c.updated_by ? ' by ' + c.updated_by : ''}`] : null,
      c.notes ? ['Notes', c.notes] : null,
    ].filter(Boolean)));
}

function researchBlock(ctx, p, s) {
  const { h, ui, fmt } = ctx;
  const rt = p.research_target || {};
  const est = ui.provenance('estimated');
  return ui.section({
    title: 'Research plan', sub: 'From the research import. Estimates, not live data.',
    actions: h('a', { href: `#/plan?college=${encodeURIComponent(p.college_id)}`, class: 'vx-link vx-small' }, 'Open in planner'),
    body: ui.kv([
      ['Priority', h('span', { class: 'vx-row' }, p.p_level ? ui.badge(p.p_level, p.p_level === 'P1' ? 'brand' : 'info') : '—', p.targeted ? ui.badge('Targeted (research)', 'brand') : ui.badge('Not targeted (research)', 'neutral'), p.hold_reason ? h('span', { class: 'vx-small vx-muted' }, p.hold_reason) : null)],
      rt.avg != null ? ['Enrollment estimate', h('span', null, `${fmt.num(rt.min)}–${fmt.num(rt.max)} (average ${fmt.num(rt.avg)}) `, est)] : null,
      p.ambassadors_research != null ? ['Ambassadors suggested', h('span', null, `${fmt.num(p.ambassadors_research)} `, est, h('span', { class: 'vx-muted vx-small' }, ` · ${fmt.num(s.people.filter((x) => isActive(x) && x.role !== 'college_lead').length)} recruited`))] : null,
      p.college_leads_research != null ? ['College lead', p.college_leads_research === 0.5 ? 'Shared with another college (0.5)' : p.college_leads_research ? 'One for this college' : 'None planned'] : null,
    ].filter(Boolean)),
  });
}

/* ------------------------------------------------------------------ team tab: lead → ambassador leads → ambassadors */
function teamTab(ctx, d, s, research) {
  const { h, ui, fmt, api } = ctx;
  const c = d.college || {};
  const wrap = h('div', { class: 'vc-tab vc-team' });
  const host = h('div');
  const draw = (perfById) => host.replaceChildren(teamBody(ctx, d, s, research, perfById));
  draw(null);
  wrap.append(host);
  // per-person own / team numbers from /api/performance (v4); the tree renders immediately without them
  getPerformance(ctx, { level: 'person', college_id: c.id, period: 'programme', include_inactive: 1 }, { scoped: false })
    .then((res) => { if (res && host.isConnected) draw(new Map(perfRows(res).map((x) => [Number(x.id), x]))); })
    .catch(() => { /* tree already shows the people rows' own figures */ });
  return wrap;
}

function teamBody(ctx, d, s, research, perfById) {
  const { h, ui, fmt } = ctx;
  const c = d.college || {};
  const out = h('div', { class: 'vc-teambody' });
  const active = s.people.filter(isActive);
  const lead = s.lead;
  const AL = active.filter((p) => p.role === 'ambassador_lead' && !s.unassigned.has(Number(p.id)));
  const AM = active.filter((p) => p.role === 'ambassador' && !s.unassigned.has(Number(p.id)));
  const UN = active.filter((p) => s.unassigned.has(Number(p.id)));
  const inactive = s.people.filter((p) => !isActive(p));
  const bmap = new Map(s.branches.map((b) => [Number(b.id), b]));
  const w = (n) => (ui.writeOnly ? ui.writeOnly(n) : n);

  const suggested = research && research.ambassadors_research != null ? research.ambassadors_research : null;
  const ambN = active.filter((p) => p.role !== 'college_lead').length;
  out.append(h('div', { class: 'vc-team-bar' },
    h('div', { class: 'vc-team-sum' },
      ...[[lead ? 1 : 0, 'college lead'], [active.filter((p) => p.role === 'ambassador_lead').length, 'ambassador lead'], [active.filter((p) => p.role === 'ambassador').length, 'ambassador']]
        .map(([n, w]) => h('span', null, h('strong', null, fmt.num(n)), ` ${fmt.word ? fmt.word(n, w) : (n === 1 ? w : `${w}s`)}`)),
      UN.length ? h('span', { class: 'is-warn' }, h('strong', null, fmt.num(UN.length)), ' unassigned') : null,
      suggested != null ? h('span', { class: 'vx-muted' }, `research suggests ${fmt.num(suggested)} ambassadors `, ui.provenance('estimated')) : null),
    h('div', { class: 'vx-actions' },
      w(btn(ctx, 'Add ambassador', () => addPerson(ctx, c, s, 'ambassador'), { small: true, icon: 'ambassador', tone: lead ? 'primary' : null })),
      w(btn(ctx, 'Add ambassador lead', () => addPerson(ctx, c, s, 'ambassador_lead'), { small: true, icon: 'lead' })),
      lead ? w(btn(ctx, 'Replace lead', () => forms.replaceLead(ctx, lead.id), { small: true }))
        : w(btn(ctx, 'Appoint college lead', () => addPerson(ctx, c, s, 'college_lead'), { small: true, tone: 'primary', icon: 'lead' })))));

  if (!active.length && !inactive.length) {
    out.append(ui.emptyState({ title: 'No team yet', icon: 'people', text: 'Start with one college lead who is accountable for the whole college. Then add one student ambassador for each IT branch; they report to the lead.',
      action: w(btn(ctx, 'Appoint college lead', () => addPerson(ctx, c, s, 'college_lead'), { tone: 'primary', icon: 'lead' })) }));
  }

  const card = (p, { compact } = {}) => {
    const pf = personPerf(p, perfById);
    const bs = p._branches.map((i) => bmap.get(i)).filter(Boolean);
    const acts = [
      { label: 'Edit details', icon: 'edit', writeOnly: true, onClick: () => forms.editPerson(ctx, p.id) },
      { label: 'Set target', icon: 'target', writeOnly: true, onClick: () => (forms.targetDialog ? forms.targetDialog(ctx, { scope_type: 'person', scope_id: String(p.id), label: p.full_name }) : forms.setTarget('person', String(p.id), ctx, { label: p.full_name })) },
      p.role === 'college_lead' ? { label: 'Replace as college lead', icon: 'lead', writeOnly: true, onClick: () => forms.replaceLead(ctx, p.id) } : null,
      { label: 'Move to another college', icon: 'college', writeOnly: true, onClick: () => forms.movePerson(ctx, p.id) },
      isActive(p) ? { label: 'Deactivate…', icon: 'close', tone: 'danger', writeOnly: true, onClick: () => deactivate(ctx, p) } : { label: 'Reactivate', icon: 'refresh', writeOnly: true, onClick: () => reactivate(ctx, p) },
    ].filter(Boolean);
    const lname = p.reports_to_name || (p.lead && p.lead.name) || `#${p.reports_to}`;
    const ISSUE = { no_lead: 'No lead assigned', lead_missing: 'Their lead no longer exists', lead_inactive: `Reports to ${lname}, who is inactive`,
      lead_other_college: `Reports to ${lname}, who is at another college`, lead_wrong_role: `Reports to ${lname}, who is not a lead` };
    const issue = s.unassigned.has(Number(p.id)) ? (ISSUE[p.assignment_issue] || (p.reports_to ? `Reports to ${p.reports_to_name || '#' + p.reports_to}, who is not an active lead of this college` : 'No lead assigned')) : null;
    return h('div', { class: ['vc-pcard', `is-${p.role}`, !isActive(p) && 'is-inactive', issue && 'is-unassigned', compact && 'is-compact'] },
      h('div', { class: 'vc-pcard-top' },
        h('span', { class: 'vc-pcard-ic' }, ui.icon(p.role === 'ambassador' ? 'ambassador' : 'lead', { size: 16 })),
        h('div', { class: 'vc-pcard-id' },
          h('a', { href: `#/person/${p.id}`, class: 'vc-pcard-name' }, p.full_name || `Person #${p.id}`),
          h('span', { class: 'vx-small vx-muted' }, ROLE_LABEL[p.role] || p.role, p.designation ? ` · ${p.designation}` : '', bs.length ? ' · ' : '', bs.length ? bs.map(branchLabel).join(', ') : '')),
        p.status !== 'active' ? (ui.statusChip ? ui.statusChip(p.status) : ui.statusBadge('person_status', p.status)) : null,
        typeof ui.menu === 'function' ? ui.menu({ ariaLabel: `Actions for ${p.full_name}`, items: acts }) : btn(ctx, 'Edit', () => forms.editPerson(ctx, p.id), { small: true, tone: 'ghost', icon: 'edit' })),
      issue ? h('div', { class: 'vc-pcard-issue vx-small' }, ui.icon('warn', { size: 14 }), issue) : null,
      h('div', { class: 'vc-pcard-bottom' },
        contactActions(ctx, p.phone, p.email),
        h('div', { class: 'vc-pcard-perf' },
          pf.target != null && pf.target > 0
            ? (ui.progressBar ? ui.progressBar(pf.actual ?? 0, pf.target, { min: pf.min, max: pf.max, size: 'sm', status: pf.status, unit: '', pct: pf.pct }) : progressCell(ctx, pf.target, pf.actual))
            : h('span', { class: 'vx-small vx-muted' }, pf.target === 0 ? `Target 0 · ${fmt.num(pf.actual ?? 0)} confirmed` : `${fmt.num(pf.actual ?? 0)} confirmed · no target`),
          pf.status ? perfChip(ctx, pf.status) : null,
          pf.team && pf.team.size ? h('span', { class: 'vx-small vx-muted' }, `Team (${fmt.num(pf.team.size)}): ${fmt.num(pf.team.actual ?? 0)}${pf.team.target ? ` / ${fmt.num(pf.team.target)}` : ''} confirmed`) : null)));
  };
  const vacant = (title, text, action) => h('div', { class: 'vc-pcard is-vacant' },
    h('div', { class: 'vc-pcard-top' }, h('span', { class: 'vc-pcard-ic' }, ui.icon('plus', { size: 16 })),
      h('div', { class: 'vc-pcard-id' }, h('strong', null, title), h('span', { class: 'vx-small vx-muted' }, text)), action ? w(action) : null));

  if (active.length || inactive.length) {
    const under = (pid) => AM.filter((a) => Number(a.reports_to) === Number(pid));
    const node = (p, kids) => h('li', { class: 'vc-node' }, card(p), kids && kids.length ? h('ul', { class: 'vc-tree-kids' }, kids) : null);
    const gapBranches = s.branches.filter((b) => b._gap);
    const slots = gapBranches.map((b) => h('li', { class: 'vc-node' }, vacant(`${branchLabel(b)} — no ambassador`, `${b.name || 'IT branch'} counts toward the target`,
      btn(ctx, 'Recruit', () => addPerson(ctx, c, s, 'ambassador', { branch_ids: [b.id] }), { small: true }))));
    const top = lead
      ? node(lead, [...AL.filter((a) => Number(a.reports_to) === Number(lead.id)).map((a) => node(a, under(a.id).map((x) => node(x)))), ...under(lead.id).map((x) => node(x)), ...slots])
      : h('li', { class: 'vc-node' }, vacant('College lead — vacant', 'Appoint one student accountable for this college', btn(ctx, 'Appoint', () => addPerson(ctx, c, s, 'college_lead'), { small: true, tone: 'primary' })),
        h('ul', { class: 'vc-tree-kids' }, [...AL.map((a) => node(a, under(a.id).map((x) => node(x)))), ...slots]));
    out.append(h('ul', { class: 'vc-tree', 'aria-label': 'Team structure' }, top));

    if (UN.length) {
      const leads = (typeof forms.validLeads === 'function' ? forms.validLeads(s.people, 'ambassador') : active.filter((p) => ['college_lead', 'ambassador_lead'].includes(p.role)))
        .filter((p) => !s.unassigned.has(Number(p.id)));
      const sel = h('select', { class: 'td-input td-select td-input--sm', 'aria-label': 'Lead to assign to' },
        h('option', { value: '' }, leads.length ? 'Choose a lead…' : 'No active lead in this college'), leads.map((l) => h('option', { value: String(l.id) }, `${l.full_name} (${ROLE_LABEL[l.role]})`)));
      if (lead) sel.value = String(lead.id);
      const picks = new Set(UN.map((p) => Number(p.id)));
      const assign = async () => {
        if (!sel.value) { ui.toast('Choose the lead first', 'warn'); return; }
        const ids = [...picks];
        if (!ids.length) { ui.toast('Tick at least one person', 'warn'); return; }
        // ambassador leads can only report to the college lead
        const leadP = s.byId.get(Number(sel.value));
        const bad = ids.filter((i) => s.byId.get(i)?.role === 'ambassador_lead' && leadP?.role !== 'college_lead');
        if (bad.length) { ui.toast('Ambassador leads can only report to the college lead', 'bad'); return; }
        try {
          let okN = 0; let fail = [];
          try { const r = await ctx.api.post('/people/bulk-assign', { person_ids: ids, reports_to: Number(sel.value) }); okN = (r.updated || []).length + (r.unchanged || []).length || ids.length; } catch (e) {
            if (e.status !== 404 && e.status !== 405) throw e;
            const r = await forms.assignToLead(ctx, ids, Number(sel.value)); okN = r.ok.length; fail = r.failed;
          }
          ui.toast(fail.length ? `${okN} assigned, ${fail.length} failed: ${fail[0].message}` : `${fmt.plural(okN, 'person', 'people')} assigned to ${leadP?.full_name || 'the lead'}`, fail.length ? 'warn' : 'good');
          ctx.refresh?.();
        } catch (e) { ui.toast(e.message, 'bad'); }
      };
      out.append(ui.section({
        title: `Unassigned (${fmt.num(UN.length)})`,
        sub: 'Active people without a valid lead in this college (no lead, an inactive lead, or a lead elsewhere).',
        actions: w(h('div', { class: 'vx-actions' }, sel, btn(ctx, 'Assign ticked', assign, { small: true, tone: 'primary' }))),
        body: h('ul', { class: 'vc-unlist' }, UN.map((p) => h('li', null,
          h('label', { class: 'td-checkhit vc-unpick td-write-only' }, h('input', { type: 'checkbox', class: 'td-check', checked: true, 'aria-label': `Assign ${p.full_name}`, onChange: (e) => { if (e.target.checked) picks.add(Number(p.id)); else picks.delete(Number(p.id)); } })),
          card(p, { compact: true })))),
      }));
    }
    if (inactive.length) {
      out.append(h('details', { class: 'vc-inactive' }, h('summary', null, `Inactive (${fmt.num(inactive.length)}) — history kept`),
        h('div', { class: 'vc-inactive-list' }, inactive.map((p) => card(p, { compact: true })))));
    }
  }
  return out;
}

/** Deactivate / reactivate = THE forms.js flows (R5: lists affected people, offers reassignment). Re-exported for people.js. */
export function deactivate(ctx, p) { return forms.deactivatePerson(ctx, p.id ?? p); }
export function reactivate(ctx, p) { return forms.reactivatePerson(ctx, p); }

/* ------------------------------------------------------------------ contacts & calls tab */
function callsTab(ctx, d) {
  const { h, ui, fmt } = ctx;
  const c = d.college || {};
  const info = d.call_info || {};
  const contacts = d.contacts || [];
  const calls = d.calls || [];
  const wrap = h('div', { class: 'vc-tab vcc' });
  const cc = info.contact_counts || {};
  const w = (n) => (ui.writeOnly ? ui.writeOnly(n) : n);
  wrap.append(h('div', { class: 'vcc-summary' },
    forms.callStatusBadge(ctx, info.call_status || 'not_called'),
    h('span', { class: 'vx-muted vx-small' }, [
      fmt.plural(cc.total || 0, 'contact'), cc.working ? `${fmt.num(cc.working)} working` : null,
      (cc.non_working || 0) + (cc.invalid || 0) ? `${fmt.num((cc.non_working || 0) + (cc.invalid || 0))} not working / invalid` : null,
      fmt.plural(info.calls_total || 0, 'call'),
      c.participation_confirmed_on ? `participation confirmed ${fmt.date(c.participation_confirmed_on)}` : null,
    ].filter(Boolean).join(' · ')),
    h('span', { class: 'vx-grow' }),
    w(btn(ctx, 'Log call', () => forms.logCall(ctx, { college_id: c.id, contacts, college_label: label(c) }), { icon: 'phone', tone: 'primary', small: true })),
    h('a', { href: '#/calls', class: 'vx-link vx-small' }, 'Calling queue')));

  const verifiedTxt = (k) => (k.basis === 'verified' ? `verified${k.verified_on ? ` ${fmt.date(k.verified_on)}` : ''}${k.verified_by ? ` by ${k.verified_by}` : ''}` : null);
  const contactItem = (k) => h('li', { class: 'vcc-item' },
    h('div', { class: 'vcc-main' },
      h('div', { class: 'vcc-title' }, forms.contactLabel(k) || 'Contact', forms.contactStatusBadge(ctx, k.status),
        ui.verifiedBadge ? ui.verifiedBadge({ state: k.basis === 'verified' ? 'verified' : 'unverified', source: k.source_url, date: k.verified_on, by: k.verified_by }) : ui.provenance(k.basis === 'verified' ? 'verified' : 'pending')),
      h('div', { class: 'vcc-num' }, k.phone ? h('span', { class: 'td-num' }, forms.formatPhone ? forms.formatPhone(k.phone) : k.phone) : null, k.email ? h('span', null, k.email) : null, contactActions(ctx, k.phone, k.email)),
      h('div', { class: 'vx-small vx-muted' }, [
        k.last_call ? `Last call ${fmt.date(k.last_call.called_at)}: ${forms.OUTCOMES[k.last_call.outcome]?.label || k.last_call.outcome}` : 'Not called yet',
        k.unanswered_streak >= 2 && k.status !== 'working' ? `${k.unanswered_streak} unanswered in a row` : null,
        k.status_source === 'manual' ? 'status set by hand' : null, verifiedTxt(k),
      ].filter(Boolean).join(' · ')),
      k.source_url ? h('div', { class: 'vx-small' }, sourceLink(ctx, k.source_url, 'source')) : null,
      k.notes ? h('div', { class: 'vx-small vx-muted' }, k.notes) : null),
    h('div', { class: 'vcc-acts' },
      w(btn(ctx, 'Log call', () => forms.logCall(ctx, { college_id: c.id, contacts, contact_id: k.id, college_label: label(c) }), { icon: 'phone', small: true })),
      w(btn(ctx, 'Edit', () => forms.editContact(ctx, k), { icon: 'edit', small: true, tone: 'ghost', aria: `Edit ${forms.contactLabel(k) || 'contact'}` }))));

  // TPO / principal / office first, then the rest; working before untested before broken
  const ROLE_ORDER = ['tpo', 'principal', 'admissions', 'dean', 'hod', 'office', 'other'];
  const ST_ORDER = { working: 0, untested: 1, non_working: 2, invalid: 3 };
  const sorted = contacts.slice().sort((a, b) => (ST_ORDER[a.status] ?? 1) - (ST_ORDER[b.status] ?? 1) || ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role));
  wrap.append(ui.section({
    title: 'Contacts',
    sub: 'Working numbers first. Status comes from logged calls; the same number cannot be added twice.',
    actions: w(btn(ctx, 'Add contact', () => forms.addContact(ctx, { college_id: c.id }), { icon: 'plus', small: true })),
    body: contacts.length ? h('ul', { class: 'vcc-list' }, sorted.map(contactItem))
      : ui.emptyState({ title: 'No contacts yet', icon: 'phone', text: c.phone ? `The college listing has ${c.phone}. Add it (and the TPO's number when you get it) so calls can be logged against it.` : 'Add the TPO, principal or office number so calls can be logged and tracked.', action: w(btn(ctx, 'Add contact', () => forms.addContact(ctx, { college_id: c.id }), { icon: 'plus', tone: 'primary', small: true })) }),
  }));
  wrap.append(ui.section({
    title: `Call history (${calls.length})`,
    body: calls.length ? h('ul', { class: 'vcc-list' }, calls.map((x) => {
      const o = forms.OUTCOMES[x.outcome];
      return h('li', { class: 'vcc-item' },
        h('div', { class: 'vcc-main' },
          h('div', { class: 'vcc-title' }, ui.badge(o?.label || x.outcome, o?.tone || 'neutral'), h('span', null, x.contact_name || (x.contact_role ? forms.CONTACT_ROLE_LABEL[x.contact_role] : x.contact_id ? 'Contact' : 'College number')),
            x.confirms_participation ? ui.badge('Confirmed participation', 'good') : null),
          h('div', { class: 'vx-small vx-muted' }, [`${fmt.date(x.called_at)}${/T\d{2}:\d{2}/.test(x.called_at) ? ', ' + String(x.called_at).slice(11, 16) : ''}`, x.caller ? `by ${x.caller}` : null,
            x.followup_due ? `call-back ${fmt.date(x.followup_due)}${x.followup_status === 'done' ? ' (done)' : ''}` : null].filter(Boolean).join(' · ')),
          x.notes ? h('div', { class: 'vx-small' }, x.notes) : null));
    })) : ui.emptyState({ title: 'No calls logged yet', icon: 'clock', text: 'Use “Log call” after every attempt, even when nobody answers, so the team can see who was tried and when.' }),
  }));
  return wrap;
}

/* ------------------------------------------------------------------ targets & performance tab */
const PERIODS = () => {
  const t = todayStr();
  const dt = new Date(Date.parse(t + 'T00:00:00Z'));
  const mon = new Date(dt); mon.setUTCDate(dt.getUTCDate() - ((dt.getUTCDay() + 6) % 7));
  return [['programme', 'Programme to date'], [`month:${t.slice(0, 7)}`, 'This month'], [`week:${mon.toISOString().slice(0, 10)}`, 'This week']];
};

function performanceTab(ctx, d, s, meta) {
  const { h, ui, fmt } = ctx;
  const c = d.college || {};
  const wrap = h('div', { class: 'vc-tab vc-perf' });
  const w = (n) => (ui.writeOnly ? ui.writeOnly(n) : n);
  const periods = PERIODS();
  if (!periods.some(([k]) => k === ui_state.period)) ui_state.period = 'programme';
  const perfHost = h('div', { class: 'vc-perf-host' });
  const seg = typeof ui.segmented === 'function'
    ? ui.segmented({ options: periods.map(([value, lbl]) => ({ value, label: lbl })), value: ui_state.period, ariaLabel: 'Period', onChange: (v) => { ui_state.period = v; saveUi(); load(); } })
    : h('select', { class: 'td-input td-select td-input--sm', onChange: (e) => { ui_state.period = e.target.value; saveUi(); load(); } }, periods.map(([v, l]) => h('option', { value: v, selected: v === ui_state.period ? true : null }, l)));
  wrap.append(h('div', { class: 'vc-perf-bar' }, seg, h('span', { class: 'vx-grow' }),
    w(btn(ctx, 'Record enrollment', () => forms.recordEnrollment(ctx, { college_id: c.id }), { icon: 'plus', tone: 'primary', small: true })),
    w(btn(ctx, 'Set college target', () => setCollegeTarget(ctx, c), { icon: 'target', small: true }))), perfHost);

  let seq = 0;
  async function load() {
    const my = ++seq;
    perfHost.replaceChildren(ui.skeleton ? ui.skeleton(3, { card: false }) : 'Loading…');
    let col = null; let ppl = null; let err = null;
    try {
      [col, ppl] = await Promise.all([
        getPerformance(ctx, { level: 'college', college_id: c.id, period: ui_state.period }, { scoped: false }),
        getPerformance(ctx, { level: 'person', college_id: c.id, period: ui_state.period, include_inactive: 1 }, { scoped: false }),
      ]);
    } catch (e) { err = e; }
    if (my !== seq) return;
    if (err) { perfHost.replaceChildren(ui.errorCard ? ui.errorCard({ title: 'Could not load performance', error: err, retry: load }) : h('p', null, err.message)); return; }
    if (!col && !ppl) { perfHost.replaceChildren(fallbackPerf(ctx, d, s)); return; }
    const row = perfRows(col).find((x) => String(x.id) === String(c.id)) || perfRows(col)[0] || null;
    perfHost.replaceChildren(collegePerfCard(ctx, c, row, col && col.period), peopleTable(ctx, s, perfRows(ppl), ppl && ppl.period));
  }
  load();

  // enrollment detail (pipeline, course, branch, recent)
  const r = d.rollup || {};
  const fn = d.funnel;
  if (fn && fn.total) wrap.append(ui.section({ title: 'Student pipeline', sub: fn.note, body: h('div', { class: 'vcc-summary' }, fn.stages.map((x) => h('span', { class: 'vx-small' }, forms.stageBadge(ctx, x.stage), ' ', h('strong', { class: 'td-num' }, fmt.num(x.count))))) }));
  const rows = s.branches.filter((b) => b.is_relevant || b.rollup.enrolled || b.rollup.target);
  wrap.append(ui.section({ title: 'By branch', body: rows.length ? cardify(h('div', { class: 'vx-tablewrap' }, ui.table({
    columns: [
      { key: 'code', label: 'Branch', render: (b) => `${b.code || ''} ${b.name ? '— ' + b.name : ''}` },
      { key: 'r_target', label: 'Target', align: 'right', render: (b) => (b.rollup.target != null ? fmt.num(b.rollup.target) : '—') },
      { key: 'r_enrolled', label: 'Confirmed', align: 'right', render: (b) => fmt.num(b.rollup.enrolled || 0) },
      { key: 'r_remaining', label: 'Remaining', align: 'right', render: (b) => (b.rollup.target ? (b.rollup.exceeded_by > 0 ? `+${fmt.num(b.rollup.exceeded_by)}` : fmt.num(b.rollup.remaining)) : '—') },
      { key: 'r_pct', label: 'Progress', sortable: false, render: (b) => progressCell(ctx, b.rollup.target, b.rollup.enrolled) },
      { key: 'set', label: '', sortable: false, render: (b) => w(btn(ctx, 'Set target', () => (forms.targetDialog ? forms.targetDialog(ctx, { scope_type: 'branch', scope_id: String(b.id), label: `${label(c)} · ${b.code || b.name}` }) : forms.setTarget('branch', String(b.id), ctx, { label: `${label(c)} · ${b.code || b.name}` })), { small: true })) },
    ], rows, onRowClick: (b) => showBranch(ctx, b.id),
  }))) : ui.emptyState({ title: 'No IT branches to track', icon: 'branch', text: 'Add this college’s branches to split targets and track branch-wise enrollment.' }) }));
  const byCourse = r.by_course || [];
  if (byCourse.length) {
    wrap.append(ui.section({ title: 'By course', body: cardify(h('div', { class: 'vx-tablewrap' }, ui.table({
      columns: [
        { key: 'name', label: 'Course' },
        { key: 'price_inr', label: 'Price', align: 'right', render: (x) => fmt.inr(x.price_inr) },
        { key: 'target', label: 'Target', align: 'right', render: (x) => (x.target ? fmt.num(x.target) : '—') },
        { key: 'enrolled', label: 'Confirmed', align: 'right', render: (x) => fmt.num(x.enrolled || 0) },
        { key: 'revenue_inr', label: 'Revenue', align: 'right', render: (x) => fmt.inr(x.revenue_inr || 0) },
      ], rows: byCourse,
    }))) }));
  }
  wrap.append(ui.section({ title: 'Recent enrollments', body: enrollmentList(ctx, d.recent_enrollments || [], { courses: meta.courses, people: s.people, branches: s.branches }, { emptyText: 'Use “Record enrollment” when a student from this college signs up. Credit the ambassador so their progress updates.' }) }));
  return wrap;
}

function collegePerfCard(ctx, c, row, period) {
  const { h, ui, fmt } = ctx;
  if (!row) return ui.emptyState({ title: 'No figures for this period', text: 'Nothing recorded yet.' });
  const hasT = row.target != null;
  const stat = (lbl, val, sub) => h('div', { class: 'vc-pstat' }, h('span', { class: 'vx-small vx-muted' }, lbl), h('strong', { class: 'td-num' }, val), sub ? h('span', { class: 'vx-small vx-muted' }, sub) : null);
  return h('section', { class: 'vc-pcol td-card' },
    h('div', { class: 'vc-pcol-head' },
      h('div', null, h('h2', { class: 'vc-card-title' }, 'College'), h('span', { class: 'vx-small vx-muted' }, period ? `${period.label || ''}${period.days_total ? ` · day ${fmt.num(period.days_elapsed)} of ${fmt.num(period.days_total)}` : ''}` : '')),
      perfChip(ctx, row.status)),
    hasT && row.target > 0 ? (ui.progressBar ? ui.progressBar(row.actual ?? 0, row.target, { min: row.min, max: row.max, status: row.status, unit: 'confirmed', pct: row.pct }) : ui.progress({ target: row.target, done: row.actual ?? 0 })) : null,
    h('div', { class: 'vc-pstats' },
      stat('Target', hasT ? fmt.num(row.target) : 'Not set', [row.min != null ? `min ${fmt.num(row.min)}` : null, row.max != null ? `max ${fmt.num(row.max)}` : null, row.target_source === 'sum_of_children' ? 'sum of branch targets' : null].filter(Boolean).join(' · ') || null),
      stat('Confirmed', fmt.num(row.actual ?? 0), row.not_credited ? `${fmt.num(row.not_credited)} not credited to anyone` : null),
      stat(row.exceeded_by > 0 ? 'Exceeded by' : 'Remaining', hasT ? fmt.num(row.exceeded_by > 0 ? row.exceeded_by : row.remaining) : '—'),
      stat('Achieved', pctNumText(row.pct)),
      row.expected != null ? stat('Expected by now', fmt.num(Math.round(row.expected * 10) / 10)) : null),
    row.covers && Number(row.covers.total) > 0 && row.target_source === 'sum_of_children' ? h('p', { class: 'vx-small vx-muted' }, `Target covers ${fmt.num(row.covers.with_target)} of ${fmt.num(row.covers.total)} branches; only their confirmed enrollments are compared with it.`) : null,
    row.below_min ? h('p', { class: 'vx-small vx-warn-text' }, 'Below the minimum.') : null,
    row.above_max ? h('p', { class: 'vx-small' }, 'Above the maximum.') : null);
}

function peopleTable(ctx, s, rows, period) {
  const { h, ui, fmt } = ctx;
  const list = rows.slice().sort((a, b) => ['college_lead', 'ambassador_lead', 'ambassador'].indexOf(a.role) - ['college_lead', 'ambassador_lead', 'ambassador'].indexOf(b.role) || String(a.name).localeCompare(String(b.name)));
  const setT = (p) => (forms.targetDialog ? forms.targetDialog(ctx, { scope_type: 'person', scope_id: String(p.id), label: p.name, period: ui_state.period }) : forms.setTarget('person', String(p.id), ctx, { label: p.name }));
  const cols = [
    { key: 'name', label: 'Person', primary: true, priority: 1, minWidth: 200, render: (p) => h('div', null, h('a', { href: `#/person/${p.id}` }, p.name), h('div', { class: 'vx-small vx-muted' }, ROLE_LABEL[p.role] || p.role, p.person_status === 'inactive' ? ' · inactive' : '')) },
    { key: 'actual', label: 'Own: confirmed vs target', priority: 1, minWidth: 200, render: (p) => (p.target > 0 && ui.progressBar ? ui.progressBar(p.actual ?? 0, p.target, { min: p.min, max: p.max, size: 'sm', status: p.status, pct: p.pct }) : h('span', null, fmt.num(p.actual ?? 0), h('span', { class: 'vx-muted' }, p.target === 0 ? ' · target 0' : ' · no target'))) },
    { key: 'status', label: 'Status', priority: 2, minWidth: 120, cardHidden: true, render: (p) => perfChip(ctx, p.status) },
    { key: 'team', label: 'Team below', sortable: false, priority: 2, minWidth: 180, render: (p) => (p.team && p.team.size ? h('span', { class: 'vx-small' }, `${fmt.num(p.team.actual ?? 0)}${p.team.target != null ? ` / ${fmt.num(p.team.target)}` : ''} · ${fmt.plural(p.team.size, 'person', 'people')}`, p.team.status ? h('span', null, ' ', perfChip(ctx, p.team.status)) : null) : h('span', { class: 'vx-muted' }, '—')) },
    { key: 'combined', label: 'Own + team', sortable: false, priority: 3, minWidth: 120, render: (p) => (p.combined && p.team && p.team.size ? h('span', { class: 'td-num' }, `${fmt.num(p.combined.actual ?? 0)}${p.combined.target != null ? ` / ${fmt.num(p.combined.target)}` : ''}`) : h('span', { class: 'vx-muted' }, '—')) },
  ];
  const body = list.length
    ? (typeof ui.dataTable === 'function'
      ? ui.dataTable({ columns: cols, rows: list, rowActions: (p) => [{ label: 'Set target', icon: 'target', writeOnly: true, onClick: () => setT(p) }], caption: 'People of this college: own and team performance',
        cardTitle: (p) => h('a', { href: `#/person/${p.id}` }, p.name),
        cardSubtitle: (p) => `${ROLE_LABEL[p.role] || p.role}${p.person_status === 'inactive' ? ' · inactive' : ''}`,
        cardMeta: (p) => perfChip(ctx, p.status) })
      : ui.table({ columns: cols, rows: list }))
    : ui.emptyState({ title: 'No team yet', icon: 'people', text: 'Targets per person appear once the college lead and ambassadors are added in the Team tab.' });
  return ui.section({ title: 'People', sub: `Own figures are compared with own targets; the team below a lead is shown separately${period && period.label ? ` · ${period.label}` : ''}.`, body });
}

/** v3 server: no /api/performance — show the programme figures the server already has, and say what is missing. */
function fallbackPerf(ctx, d, s) {
  const { h, ui, fmt } = ctx;
  const r = d.rollup || {};
  return h('div', null,
    h('p', { class: 'vx-small vx-muted vc-note' }, ui.icon('info', { size: 14 }), ' Week and month views appear once the server provides performance by period. Showing programme-to-date figures.'),
    h('section', { class: 'vc-pcol td-card' },
      h('div', { class: 'vc-pcol-head' }, h('h2', { class: 'vc-card-title' }, 'College'), r.target > 0 ? ui.statusBadge('on_track', r.on_track) : ui.badge('No target', 'neutral')),
      r.target > 0 ? ui.progress({ target: r.target, done: r.enrolled ?? 0 }) : null,
      h('div', { class: 'vc-pstats' },
        h('div', { class: 'vc-pstat' }, h('span', { class: 'vx-small vx-muted' }, 'Target'), h('strong', null, r.target != null ? fmt.num(r.target) : 'Not set')),
        h('div', { class: 'vc-pstat' }, h('span', { class: 'vx-small vx-muted' }, 'Confirmed'), h('strong', null, fmt.num(r.enrolled ?? 0))),
        h('div', { class: 'vc-pstat' }, h('span', { class: 'vx-small vx-muted' }, 'Remaining'), h('strong', null, r.target ? fmt.num(r.remaining) : '—')),
        h('div', { class: 'vc-pstat' }, h('span', { class: 'vx-small vx-muted' }, 'Achieved'), h('strong', null, r.target ? pctText(r.pct) : '—')))),
    ui.section({ title: 'People', body: s.people.length ? ui.table({
      columns: [
        { key: 'full_name', label: 'Person', render: (p) => h('a', { href: `#/person/${p.id}` }, p.full_name) },
        { key: 'role', label: 'Role', render: (p) => ROLE_LABEL[p.role] || p.role },
        { key: 'target', label: 'Target', align: 'right', render: (p) => (personPerf(p).target != null ? fmt.num(personPerf(p).target) : '—') },
        { key: 'enrolled', label: 'Confirmed', align: 'right', render: (p) => fmt.num(personPerf(p).actual ?? 0) },
      ], rows: s.people,
    }) : ui.emptyState({ title: 'No team yet', icon: 'people', text: 'Add people in the Team tab.' }) }));
}

/* ------------------------------------------------------------------ branches tab (IT first, with provenance) */
function branchesTab(ctx, d, s) {
  const { h, ui, fmt } = ctx;
  const c = d.college || {};
  const wrap = h('div', { class: 'vc-tab vc-branches' });
  const w = (n) => (ui.writeOnly ? ui.writeOnly(n) : n);
  const gapB = s.branches.filter((b) => b._gap);
  if (gapB.length) {
    wrap.append(callout(ctx, 'bad', `${fmt.plural(gapB.length, 'IT branch has', 'IT branches have')} no ambassador`,
      h('div', null, 'Outreach in these branches has no owner. Tap one to recruit a student ambassador for it.',
        h('div', { class: 'vc-chips vc-gapchips' }, gapB.map((b) => h('button', { type: 'button', class: 'vc-chip is-gap td-write-only', title: `Recruit an ambassador for ${b.name || b.code}`,
          onClick: () => addPerson(ctx, c, s, 'ambassador', { branch_ids: [b.id] }) }, '+ ', branchLabel(b)))))));
  }
  const listEl = h('div', { class: 'vc-branch-list' });
  const countEl = h('span', { class: 'vx-muted vx-small vc-count', 'aria-live': 'polite' });
  let query = '';
  const search = h('input', { type: 'search', class: 'td-input td-input--sm', placeholder: 'Find a branch (code or name)', 'aria-label': 'Find a branch', autocomplete: 'off',
    onInput: (e) => { query = e.target.value.trim().toLowerCase(); draw(); } });
  const relToggle = h('input', { type: 'checkbox', id: 'vc-rel-only', class: 'td-check', checked: ui_state.relevantOnly ? true : null, onChange: (e) => { ui_state.relevantOnly = e.target.checked; saveUi(); draw(); } });
  const sortSel = h('select', { class: 'td-input td-select td-input--sm', 'aria-label': 'Sort branches', onChange: (e) => { ui_state.sort = e.target.value; saveUi(); draw(); } },
    [['relevance', 'IT branches first'], ['gap', 'Needs ambassador first'], ['progress', 'Lowest progress first'], ['remaining', 'Most remaining'], ['eligible', 'Most eligible'], ['strength', 'Most students'], ['name', 'Branch code A–Z']]
      .map(([v, l]) => h('option', { value: v, selected: ui_state.sort === v ? true : null }, l)));
  const viewSel = typeof ui.segmented === 'function'
    ? ui.segmented({ options: [{ value: 'cards', label: 'Cards' }, { value: 'table', label: 'Table' }], value: ui_state.branchView, ariaLabel: 'Show branches as', onChange: (v) => { ui_state.branchView = v; saveUi(); draw(); } })
    : null;
  if (s.branches.length) {
    wrap.append(h('div', { class: 'vc-btools' }, search, sortSel,
      h('label', { class: 'vx-check', for: 'vc-rel-only' }, relToggle, 'IT branches only'), viewSel, countEl, h('span', { class: 'vx-grow' }),
      w(btn(ctx, 'Add branch', () => forms.addBranch(ctx, { college_id: c.id }), { icon: 'plus', small: true }))));
  }
  wrap.append(listEl);
  function sorted() {
    let rows = s.branches.slice();
    if (ui_state.relevantOnly) rows = rows.filter((b) => b.is_relevant);
    if (query) rows = rows.filter((b) => `${b.code || ''} ${b.name || ''}`.toLowerCase().includes(query));
    const key = {
      name: (b) => String(b.code || b.name),
      strength: (b) => -(b.strength_total ?? -1), eligible: (b) => -(b.eligible_estimate ?? -1),
      remaining: (b) => -(b.rollup.remaining ?? -1), progress: (b) => (b.rollup.target ? (b.rollup.pct ?? 0) : 2),
      gap: (b) => (b._gap ? 0 : 1), relevance: (b) => (b.is_relevant ? 0 : 1) * 1e6 - (b.eligible_estimate ?? 0),
    }[ui_state.sort] || (() => 0);
    return rows.sort((a, b) => { const x = key(a); const y = key(b); return typeof x === 'string' ? x.localeCompare(y) : x - y; });
  }
  function draw() {
    const rows = sorted();
    if (!s.branches.length) {
      listEl.replaceChildren(ui.emptyState({ title: 'No branches recorded yet', icon: 'branch', text: 'Branch-wise intake has not been researched for this college. Add each branch you know (for example CSE, ECE) with its yearly intake and source.',
        action: w(btn(ctx, 'Add first branch', () => forms.addBranch(ctx, { college_id: c.id }), { tone: 'primary', icon: 'plus' })) }));
      return;
    }
    const total = s.branches.length;
    countEl.textContent = rows.length === total ? fmt.plural(total, 'branch', 'branches') : `Showing ${fmt.num(rows.length)} of ${fmt.num(total)}`;
    if (!rows.length) {
      const reset = () => { query = ''; search.value = ''; ui_state.relevantOnly = false; relToggle.checked = false; saveUi(); draw(); };
      listEl.replaceChildren(ui.emptyState({ title: query ? `No branch matches “${search.value.trim()}”` : 'No IT branches here', icon: 'search',
        text: query ? 'Try the branch code (e.g. CSE) or part of its name.' : 'This college has branches, but none count toward the IT target.',
        action: btn(ctx, 'Show all branches', reset, { tone: 'primary' }) }));
      return;
    }
    listEl.replaceChildren(ui_state.branchView === 'table' ? branchTable(ctx, d, s, rows) : h('div', { class: 'vc-bcards' }, rows.map((b) => branchCard(ctx, s, b))));
  }
  draw();
  return wrap;
}

function ambNames(ctx, b) {
  const { h } = ctx;
  if (!b._ambs.length) return h('span', { class: 'vx-muted' }, 'None');
  return h('span', null, b._ambs.map((p, i) => [i ? ', ' : '', h('a', { href: `#/person/${p.id}`, onClick: (e) => e.stopPropagation(), class: p.status === 'inactive' ? 'is-inactive' : null }, p.full_name)]));
}
function figc(ctx, lbl, node) {
  return ctx.h('div', { class: 'vx-fig' }, ctx.h('div', { class: 'vx-fig-label' }, lbl), ctx.h('div', { class: 'vx-fig-value' }, node));
}
function branchCard(ctx, s, b) {
  const { h, ui, fmt } = ctx;
  const r = b.rollup;
  return h('article', { class: ['vc-bcard', b._gap && 'is-gap', !b.is_relevant && 'is-irrelevant'], tabindex: '0', role: 'button', 'aria-label': `Open branch ${b.name || b.code}`,
    onClick: () => showBranch(ctx, b.id), onKeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); showBranch(ctx, b.id); } } },
  h('header', { class: 'vc-bcard-head' },
    h('div', null, h('div', { class: 'vc-bcard-title' }, b.code ? h('span', { class: 'vx-code' }, b.code) : null, ' ', b.name || ''),
      h('div', { class: 'vx-row' }, ui.badge(CATEGORY_LABEL[b.category] || 'Other', b.is_relevant ? 'brand' : 'neutral'), outreachStatus(ctx, b))),
    ui.writeOnly ? ui.writeOnly(btn(ctx, '', () => forms.editBranch(ctx, b), { small: true, icon: 'edit', aria: `Edit ${b.code || 'branch'}`, title: 'Edit branch', class: 'vx-iconbtn' })) : null),
  h('div', { class: 'vx-figs vx-figs-4' },
    figc(ctx, 'Intake / yr', vb(ctx, b.intake_per_year, b.intake_basis)),
    figc(ctx, 'Strength', vb(ctx, b.strength_total, b.strength_basis)),
    figc(ctx, '4-1 cohort', vb(ctx, b.final_year, b.final_year_basis)),
    figc(ctx, 'Eligible', vb(ctx, b.eligible_estimate, b.eligible_basis))),
  b.intake_source || b.intake_year ? h('div', { class: 'vx-small vx-muted vc-bsrc' }, 'Intake source: ', b.intake_source ? sourceLink(ctx, b.intake_source) : 'not recorded', b.intake_year ? ` · ${b.intake_year}` : '') : null,
  h('dl', { class: 'vc-bcard-dl' },
    h('dt', null, `Ambassadors (${b._activeAmbs.length})`), h('dd', null, ambNames(ctx, b)),
    h('dt', null, 'Next follow-up'), h('dd', null, b._nextFu ? `${fmt.date(b._nextFu.due_date)} — ${b._nextFu.title || ISSUE_LABEL[b._nextFu.issue] || ''}` : '—')),
  r.target ? h('div', { class: 'vc-bcard-target' }, ui.progress({ target: r.target, done: r.enrolled || 0, size: 'sm' })) : h('div', { class: 'vx-small vx-muted' }, `${fmt.num(r.enrolled || 0)} confirmed · no branch target`));
}
function branchTable(ctx, d, s, rows) {
  const { h, ui, fmt } = ctx;
  return cardify(h('div', { class: 'vx-tablewrap' }, ui.table({
    columns: [
      { key: 'code', label: 'Branch', sortable: true, render: (b) => h('span', null, h('strong', null, b.code || ''), ' ', h('span', { class: 'vx-small' }, b.name || ''), ' ', b.is_relevant ? ui.badge('IT', 'brand') : null) },
      { key: 'intake_per_year', label: 'Intake', align: 'right', sortable: true, render: (b) => vb(ctx, b.intake_per_year, b.intake_basis) },
      { key: 'strength_total', label: 'Strength', align: 'right', sortable: true, render: (b) => vb(ctx, b.strength_total, b.strength_basis) },
      { key: 'eligible_estimate', label: 'Eligible', align: 'right', sortable: true, render: (b) => vb(ctx, b.eligible_estimate, b.eligible_basis) },
      { key: 'source', label: 'Source', sortable: false, render: (b) => (b.intake_source ? sourceLink(ctx, b.intake_source) : h('span', { class: 'vx-muted' }, '—')) },
      { key: 'n_ambs', label: 'Ambassadors', render: (b) => h('span', null, h('strong', null, fmt.num(b._activeAmbs.length)), ' ', ambNames(ctx, b)) },
      { key: 'r_pct', label: 'Progress', sortable: false, render: (b) => progressCell(ctx, b.rollup.target, b.rollup.enrolled) },
      { key: 'status', label: 'Outreach', sortable: false, render: (b) => outreachStatus(ctx, b) },
    ],
    rows, onRowClick: (b) => showBranch(ctx, b.id),
  })));
}

/* ------------------------------------------------------------------ exams tab */
function examsTab(ctx, d, ex) {
  const { h, ui, fmt } = ctx;
  const wrap = h('div', { class: 'vc-tab vc-exams-tab' });
  wrap.append(h('div', { class: 'vc-exam-now td-card' }, ui.statusBadge('exam_state', ex.state || 'unknown'), examCountdown(ctx, ex)));
  const rows = (d.exams || []).slice().sort((a, b) => String(a.semester).localeCompare(String(b.semester)));
  const dt = (v) => (v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? fmt.date(v) : v);
  wrap.append(ui.section({
    title: 'Exam windows', sub: 'Avoid outreach while students write 3-1 / 4-1 exams.', actions: h('a', { href: '#/exams', class: 'vx-link vx-small' }, 'All exams'),
    body: rows.length ? h('div', { class: 'vc-exam-grid' }, rows.map((x) => h('article', { class: 'vc-exam-card' },
      h('h3', { class: 'vc-exam-title' }, `${x.semester} semester`, x.exam_body ? h('span', { class: 'vx-muted vx-small' }, ` · ${x.exam_body}`) : null),
      h('div', { class: 'vx-row' }, ui.badge(x.status || 'Unknown', /no current|unverified/i.test(x.status || '') ? 'neutral' : 'info'),
        x.evidence ? ui.badge(`Evidence: ${x.evidence}`, /unverified/i.test(x.evidence) ? 'warn' : 'good') : null,
        x.confidence ? ui.badge(`Confidence: ${x.confidence}`, /high/i.test(x.confidence) ? 'good' : /low/i.test(x.confidence) ? 'warn' : 'neutral') : null),
      ui.kv([
        ['End-sem', x.endsem_start || x.endsem_end ? `${dt(x.endsem_start) || 'start not known'} → ${dt(x.endsem_end) || 'end not known'}` : txt(ctx, null)],
        ['Mid exams', x.mid_window || '—'], ['Lab exams', x.lab_window || '—'],
        ['Notice date', x.notice_date ? dt(x.notice_date) : '—'], ['Checked on', x.verified_on ? dt(x.verified_on) : '—'],
        ['Source', x.source_url ? sourceLink(ctx, x.source_url) : txt(ctx, null)],
      ]),
      x.notes ? h('p', { class: 'vx-small vx-muted' }, x.notes) : null)))
      : ui.emptyState({ title: 'No exam information yet', icon: 'exam', text: 'Exam dates for this college have not been researched. Add them on the Exams page once the college publishes a notice.', action: h('a', { href: '#/exams', class: 'td-btn td-btn--secondary td-btn--sm' }, 'Open Exams') }),
  }));
  return wrap;
}

/* ------------------------------------------------------------------ activity tab: follow-ups, activity log, history */
function activityTab(ctx, d, s) {
  const { h, ui, fmt } = ctx;
  const c = d.college || {};
  const wrap = h('div', { class: 'vc-tab vc-fu' });
  const w = (n) => (ui.writeOnly ? ui.writeOnly(n) : n);
  const fu = d.followups || [];
  const bmap = new Map(s.branches.map((b) => [String(b.id), b]));
  const pmap = new Map(s.people.map((p) => [String(p.id), p]));
  const labelled = fu.map((f) => ({ ...f, _orig: f, title: `${f.title || ISSUE_LABEL[f.issue] || 'Follow-up'}${f.scope_type === 'branch' && bmap.get(String(f.scope_id)) ? ` · ${branchLabel(bmap.get(String(f.scope_id)))}` : f.scope_type === 'person' && pmap.get(String(f.scope_id)) ? ` · ${pmap.get(String(f.scope_id)).full_name}` : ''}` }));
  wrap.append(h('div', { class: 'vx-actions vc-act-bar' },
    w(btn(ctx, 'Add follow-up', () => forms.addFollowup(ctx, { scope_type: 'college', scope_id: c.id, college_id: c.id, label: label(c) }), { small: true, icon: 'followup', tone: 'primary' })),
    w(btn(ctx, 'Log activity', () => forms.logActivity(ctx, { college_id: c.id }), { small: true, icon: 'clock' }))));
  wrap.append(ui.section({ title: `Open follow-ups (${fu.filter((f) => f.status === 'open').length})`,
    body: followupList(ctx, labelled.filter((f) => f.status === 'open'), { emptyText: 'Nothing planned. Add a follow-up so the next call or visit is not forgotten.' }) }));
  const acts = (d.recent_activities || []).map((a) => ({ ...a, person_name: a.person_name || pmap.get(String(a.person_id))?.full_name, branch_code: a.branch_code || (a.branch_id ? branchLabel(bmap.get(String(a.branch_id))) : null) }));
  wrap.append(ui.section({ title: 'Activity log', sub: acts.length ? `${fmt.plural(acts.length, 'recent activity', 'recent activities')} · ${fmt.num(d.rollup?.reached || 0)} students reached in total` : null, body: activityList(ctx, acts) }));
  const done = labelled.filter((f) => f.status === 'done');
  if (done.length) wrap.append(h('details', { class: 'vc-done' }, h('summary', null, `Completed follow-ups (${done.length})`), followupList(ctx, done)));
  wrap.append(ui.section({ title: 'Change history', actions: h('a', { href: `#/audit?entity=college&entity_id=${c.id}`, class: 'vx-link vx-small' }, 'Full audit log'), body: auditList(ctx, d.audit || []) }));
  return wrap;
}

function parseJ(v) { if (v == null) return null; if (typeof v === 'object') return v; try { return JSON.parse(v); } catch { return { value: v }; } }
const SKIP = new Set(['updated_at', 'updated_by', 'created_at', 'created_by']);
const ENTITY_LABEL = { college: 'College', branch: 'Branch', person: 'Person', target: 'Target', enrollment: 'Enrollment', activity: 'Activity', followup: 'Follow-up', exam: 'Exam', course: 'Course', setting: 'Setting', contact: 'Contact', call: 'Call', colleges: 'College', branches: 'Branch', people: 'Person', targets: 'Target', enrollments: 'Enrollment', activities: 'Activity', followups: 'Follow-up', exams: 'Exam', courses: 'Course', settings: 'Setting' };
const FIELD_LABEL = { op_status: 'operating status', op_status_note: 'status evidence', op_2025_26: 'admitting 2025-26', op_2026_27: 'admitting 2026-27', intake_per_year: 'intake / year', strength_total: 'strength', final_year: 'completing 4-1', eligible_estimate: 'eligible', is_relevant: 'IT branch', reports_to: 'reports to', full_name: 'name', due_date: 'due date', scope_type: 'scope', scope_id: 'scope id', naac: 'NAAC', nirf: 'NIRF', verified_fields: 'verification', district_id: 'district', city_id: 'city' };
function fieldLabel(k) { return FIELD_LABEL[k] || k.replace(/_basis$/, ' basis').replace(/_/g, ' '); }
function short(v) { if (v === null || v === undefined || v === '') return '∅'; const s = typeof v === 'object' ? JSON.stringify(v) : String(v); return s.length > 80 ? s.slice(0, 77) + '…' : s; }

export function auditList(ctx, entries) {
  const { h, ui, fmt } = ctx;
  if (!entries || !entries.length) return ui.emptyState({ title: 'No changes recorded yet', icon: 'audit', text: 'Every edit made in the portal — by whom and when — shows up here.' });
  return h('ol', { class: 'vc-audit' }, entries.map((a) => {
    const before = parseJ(a.before) || {};
    const after = parseJ(a.after) || {};
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter((k) => !SKIP.has(k) && JSON.stringify(before[k]) !== JSON.stringify(after[k]));
    const lbl = after.full_name || before.full_name || after.title || before.title || after.code || before.code || after.name || before.name || '';
    return h('li', { class: 'vc-audit-item' },
      h('div', { class: 'vc-audit-head' },
        ui.badge(a.action, a.action === 'create' ? 'good' : a.action === 'delete' ? 'bad' : 'info'),
        h('span', { class: 'vc-audit-what' }, h('strong', null, ENTITY_LABEL[a.entity] || a.entity), lbl ? ` · ${lbl}` : ''),
        h('span', { class: 'vx-muted vx-small vc-audit-when' }, `${a.actor || 'unknown'} · ${a.at ? fmt.date(a.at) + ', ' + String(a.at).slice(11, 16) : ''}`)),
      a.action === 'update' && keys.length ? h('ul', { class: 'vc-diff' }, keys.slice(0, 12).map((k) => h('li', null,
        h('span', { class: 'vc-diff-key' }, fieldLabel(k)), ' ', h('span', { class: 'vc-diff-old' }, short(before[k])), ' → ', h('span', { class: 'vc-diff-new' }, short(after[k])))))
        : a.action === 'create' && keys.length ? h('div', { class: 'vx-small vx-muted' }, keys.filter((k) => after[k] != null && after[k] !== '' && !/^(id|is_demo|college_id)$/.test(k)).slice(0, 8).map((k) => `${fieldLabel(k)}: ${short(after[k])}`).join(' · ')) : null);
  }));
}
