// Tech Drona portal — branch detail drawer + shared view helpers (CL: colleges + home)
import * as forms from './forms.js';
import { fmt as F } from '../ui/h.js';
import { openFollowupForm } from './followups.js';

/* ------------------------------------------------------------------ shared helpers */

let metaCache = null;
let metaAt = 0;
/** GET /api/meta, cached for 60 s. Never throws (returns {} on failure). */
export async function getMeta(ctx, force = false) {
  if (!force && metaCache && Date.now() - metaAt < 60000) return metaCache;
  try { metaCache = await ctx.api.get('/meta'); metaAt = Date.now(); } catch { metaCache = metaCache || {}; }
  return metaCache;
}
export function clearMeta() { metaCache = null; }

export const ROLE_LABEL = { college_lead: 'College lead', ambassador_lead: 'Ambassador lead', ambassador: 'Ambassador' };
export const ACT_LABEL = { visit: 'Visit', call: 'Call', session: 'Session', whatsapp: 'WhatsApp', followup: 'Follow-up', other: 'Other' };
export const ISSUE_LABEL = {
  ambassador_gap: 'Ambassador gap', low_outreach: 'Low outreach', low_conversion: 'Low conversion',
  unrealistic_target: 'Unrealistic target', exams: 'Exams', data: 'Data check', other: 'Other',
};
/** Branch groups in plain words. it_core, it_allied and circuit branches count toward the target by default (is_relevant). */
export const CATEGORY_LABEL = { it_core: 'Computer science', it_allied: 'CS-related (AI, data, IoT…)', circuit: 'Electronics / electrical', core: 'Other engineering', other: 'Other' };
/** One name everywhere for is_relevant = 1. */
export const TARGET_BRANCH = 'target branch';
export const TARGET_BRANCH_HELP = 'Computer science, CS-related and electronics branches count toward the enrollment target.';
/** Plain labels for the branch numbers (same words in cards, tables, the drawer and the change history). */
export const BRANCH_FIG = {
  intake: 'Seats / year',
  strength: 'Students, all 4 years (est.)',
  final_year: 'Final-year students',
  eligible: 'Likely prospects (est.)',
};
export const BRANCH_FIG_HELP = {
  intake: 'Seats the branch admits each year (mostly from the AP EAPCET 2026 counselling list).',
  strength: 'Seats per year × 4. An estimate, not a head count.',
  final_year: 'Students now in the final year (joined in 2023). Estimated from the seats unless verified.',
  eligible: 'Final-year students × how relevant the branch is to our courses (computer branches count fully, electronics 60%, others 15%).',
};

/** Value with its basis pill. Unknown -> "—" + Pending pill. */
export function vb(ctx, value, basis, fmtFn) {
  const { ui, h, fmt } = ctx;
  const f = fmtFn || fmt.num;
  if (value === null || value === undefined || Number.isNaN(value)) {
    return h('span', { class: 'vx-vb' }, h('span', { class: 'vx-dash' }, '—'), ui.provenance('pending'));
  }
  const b = basis || 'pending';
  if (ui.valueWithBasis) return ui.valueWithBasis({ value, basis: b }, f);
  return h('span', { class: 'vx-vb' }, f(value), ui.provenance(b));
}
/** {value,basis} object variant */
export const vbo = (ctx, o, fmtFn) => vb(ctx, o ? o.value : null, o ? o.basis : null, fmtFn);

/** Plain text or "—" + pending pill (for unknown non-numeric facts). */
export function txt(ctx, v) {
  if (v === null || v === undefined || v === '' || v === '—') {
    return ctx.h('span', { class: 'vx-vb' }, ctx.h('span', { class: 'vx-dash' }, '—'), ctx.ui.provenance('pending'));
  }
  return String(v);
}

/** Branch ids covered by a person, whatever shape the API returned. */
export function personBranchIds(p, branches) {
  let ids = [];
  if (Array.isArray(p.branch_ids)) ids = p.branch_ids;
  else if (Array.isArray(p.branches)) ids = p.branches.map((b) => (b && typeof b === 'object' ? (b.id ?? b.branch_id) : b));
  ids = ids.filter((x) => x !== null && x !== undefined).map(Number);
  if (!ids.length && Array.isArray(branches)) {
    for (const b of branches) if ((b.people || []).some((q) => Number(q.id) === Number(p.id))) ids.push(Number(b.id));
  }
  return [...new Set(ids)];
}

export function branchLabel(b) {
  if (!b) return '—';
  return b.code ? `${b.code}` : (b.name || `Branch ${b.id}`);
}

/** tel:/mailto: links for a person or college. */
export function contactLinks(ctx, o) {
  const { h, ui } = ctx;
  const out = [];
  if (o.phone) out.push(h('a', { href: `tel:${String(o.phone).replace(/[\s()-]+/g, '')}`, class: 'vx-link' }, ui.icon('phone'), ' ', forms.formatPhone ? forms.formatPhone(o.phone) : o.phone));
  if (o.email) out.push(h('a', { href: `mailto:${o.email}`, class: 'vx-link' }, ui.icon('mail'), ' ', o.email));
  if (o.website) {
    const url = /^https?:/i.test(o.website) ? o.website : `https://${o.website}`;
    out.push(h('a', { href: url, target: '_blank', rel: 'noopener', class: 'vx-link' }, ui.icon('link'), ' ', o.website.replace(/^https?:\/\//, '')));
  }
  if (!out.length) return o.full_name !== undefined ? h('span', { class: 'vx-muted' }, 'Not recorded') : txt(ctx, null);
  return h('span', { class: 'vx-contacts' }, out);
}

/** Small "target / done" progress with numbers. */
export function progressCell(ctx, target, done) {
  const { ui, h, fmt } = ctx;
  if (!target) return h('span', { class: 'vx-muted' }, done ? `${fmt.num(done)} confirmed · no target` : 'No target');
  return h('div', { class: 'vx-prog' }, ui.progress({ target, done: done || 0, size: 'sm' }),
    h('span', { class: 'vx-prog-num' }, `${fmt.num(done || 0)} / ${fmt.num(target)}`));
}

/** Small button. */
export function btn(ctx, label, onClick, opts = {}) {
  const { h, ui } = ctx;
  const handler = (e) => { e.stopPropagation(); onClick(e); };
  let b;
  if (ui.button) {
    b = ui.button({ label, icon: opts.icon, tone: opts.tone || 'secondary', size: opts.small ? 'sm' : undefined, title: opts.title, ariaLabel: opts.aria });
    b.addEventListener('click', handler);
  } else {
    b = h('button', { type: 'button', class: ['td-btn', `td-btn--${opts.tone || 'secondary'}`, opts.small && 'td-btn--sm'], onClick: handler, title: opts.title, 'aria-label': opts.aria },
      opts.icon ? ui.icon(opts.icon) : null, label);
  }
  if (opts.class) b.classList.add(...String(opts.class).split(' '));
  return b;
}

export function callout(ctx, tone, title, body, action) {
  const { h, ui } = ctx;
  return h('div', { class: ['vx-callout', `vx-callout-${tone}`], role: tone === 'bad' || tone === 'warn' ? 'status' : null },
    h('div', { class: 'vx-callout-ic' }, ui.icon(tone === 'good' ? 'check' : tone === 'info' ? 'clock' : 'warn')),
    h('div', { class: 'vx-callout-body' }, h('strong', null, title), body ? h('div', { class: 'vx-callout-text' }, body) : null),
    action || null);
}

/** Make a ui.table element switch to "card mode" on mobile: tags each td with its header label. */
export function cardify(el) {
  if (!el || !el.querySelector) return el;
  el.classList.add('vx-cardable');
  const label = () => {
    const tables = el.tagName === 'TABLE' ? [el] : [...el.querySelectorAll('table')];
    for (const t of tables) {
      const heads = [...t.querySelectorAll('thead th')].map((th) => th.textContent.trim());
      for (const tr of t.querySelectorAll('tbody tr')) {
        [...tr.children].forEach((td, i) => { if (heads[i] && td.dataset.label !== heads[i]) td.dataset.label = heads[i]; });
      }
    }
  };
  label();
  try { new MutationObserver(() => label()).observe(el, { childList: true, subtree: true }); } catch { /* ignore */ }
  return el;
}

/** Set the breadcrumb if the shell supports it. */
export function crumbs(ctx, items) { try { ctx.setBreadcrumb?.(items); } catch { /* ignore */ } }

/** Mark a followup done. */
export async function markFollowupDone(ctx, f) {
  try {
    await ctx.api.patch(`/followups/${f.id}`, { status: 'done' });
    ctx.ui.toast('Follow-up marked done', 'good');
    ctx.refresh?.();
  } catch (e) { ctx.ui.toast(e.message || 'Could not update follow-up', 'bad'); }
}

/** Follow-up list (open first). */
export function followupList(ctx, list, opts = {}) {
  const { h, ui, fmt } = ctx;
  const rows = (list || []).slice().sort((a, b) => (a.status === b.status ? String(a.due_date || '9').localeCompare(String(b.due_date || '9')) : a.status === 'open' ? -1 : 1));
  if (!rows.length) return ui.emptyState({ title: 'No follow-ups', text: opts.emptyText || 'Nothing scheduled yet.' });
  return h('ul', { class: 'vx-list' }, rows.map((f) => {
    const d = f.due_date ? ctx.fmt.days(f.due_date) : null;
    const overdue = f.status === 'open' && f.due_date && f.due_date < todayStr();
    return h('li', { class: ['vx-li', f.status === 'done' && 'is-done', overdue && 'is-overdue'] },
      h('div', { class: 'vx-li-main' },
        h('div', { class: 'vx-li-title' }, f.title || ISSUE_LABEL[f.issue] || 'Follow-up'),
        h('div', { class: 'vx-li-sub vx-row' },
          ui.statusBadge('followup', overdue ? 'overdue' : f.status),
          f.issue && (f.title && f.title !== ISSUE_LABEL[f.issue]) ? ui.badge(ISSUE_LABEL[f.issue] || f.issue, 'neutral') : null,
          h('span', null, [f.status === 'done' && f.done_at ? `Done ${fmt.date(f.done_at)}` : f.due_date ? `Due ${fmt.date(f.due_date)} (${d})` : 'No due date', f.owner_name ? `owner ${f.owner_name}` : null].filter(Boolean).join(' · '))),
        f.notes ? h('div', { class: 'vx-li-sub vx-muted' }, f.notes) : null),
      h('span', { class: 'vx-rowactions' },
        btn(ctx, '', () => openFollowupForm(ctx, { row: f._orig || f }), { small: true, icon: 'edit', aria: `Edit or reschedule follow-up "${f.title || 'Follow-up'}"`, title: 'Edit or reschedule' }),
        f.status === 'open' ? btn(ctx, 'Mark done', () => markFollowupDone(ctx, f), { small: true, icon: 'check' }) : null));
  }));
}

/** Activity list. */
export function activityList(ctx, list, opts = {}) {
  const { h, ui, fmt } = ctx;
  if (!list || !list.length) return ui.emptyState({ title: 'No activity yet', text: opts.emptyText || 'Log visits, calls and sessions here.' });
  return h('ul', { class: 'vx-list' }, list.map((a) => h('li', { class: 'vx-li' },
    h('div', { class: 'vx-li-main' },
      h('div', { class: 'vx-li-title' }, ACT_LABEL[a.type] || a.type || 'Activity',
        a.students_reached ? h('span', { class: 'vx-muted' }, ` · ${fmt.num(a.students_reached)} students reached`) : null),
      h('div', { class: 'vx-li-sub' }, [fmt.date(a.on_date), a.person_name, a.branch_code && a.branch_code !== '—' ? a.branch_code : null, a.created_by ? `logged by ${a.created_by}` : null].filter(Boolean).join(' · '),
        a.notes ? h('div', { class: 'vx-muted' }, a.notes) : null)))));
}

/** Enrollment list. */
export function enrollmentList(ctx, list, lookups = {}, opts = {}) {
  const { h, ui, fmt } = ctx;
  if (!list || !list.length) return ui.emptyState({ title: 'No enrollments yet', text: opts.emptyText || 'Recorded enrollments appear here.' });
  const course = (id) => (lookups.courses || []).find((c) => Number(c.id) === Number(id));
  const person = (id) => (lookups.people || []).find((p) => Number(p.id) === Number(id));
  const branch = (id) => (lookups.branches || []).find((b) => Number(b.id) === Number(id));
  return h('ul', { class: 'vx-list' }, list.map((e) => {
    const br = e.branch_code || (e.branch_id ? branchLabel(branch(e.branch_id)) : null);
    const who = e.person_name || person(e.person_id)?.full_name;
    const meta = [fmt.date(e.enrolled_on), br && br !== '—' ? br : null, who ? `credited to ${who}` : 'not credited to anyone'].filter(Boolean).join(' · ');
    const edit = opts.editable === false ? null : ui.button({ label: 'Update stage', icon: 'edit', tone: 'ghost', size: 'sm', ariaLabel: `Update stage of ${e.student_name || 'this enrollment'}` });
    edit?.addEventListener('click', (ev) => { ev.stopPropagation(); forms.editEnrollment(ctx, e); });
    return h('li', { class: 'vx-li vx-li--enr' },
      h('div', { class: 'vx-li-main' },
        h('div', { class: 'vx-li-title' }, e.student_name || 'Student (name not recorded)', ' ', forms.stageBadge(ctx, e.stage),
          e.is_demo ? h('span', { class: 'td-badge td-badge--bad vx-demo' }, 'DEMO') : null),
        h('div', { class: 'vx-li-sub' }, [e.course_name || course(e.course_id)?.name || 'Course not set', e.amount_inr != null ? fmt.inr(e.amount_inr) : null].filter(Boolean).join(' · ')),
        h('div', { class: 'vx-li-sub vx-muted' }, meta)), edit);
  }));
}

/** fraction -> "4.8%" — the ONE shared rule (fmt.pctOf in ui/h.js). */
export function pctOf(x) { return F.pctOf(x); }

export function todayStr() {
  const d = new Date();
  const o = new URLSearchParams(location.search).get('today');
  if (o && /^\d{4}-\d{2}-\d{2}$/.test(o)) return o;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Seats / students / final-years / prospects block for a branch row object (the drawer shows all four). */
export function branchFigures(ctx, b) {
  const { h } = ctx;
  return h('div', { class: 'vx-figs vx-figs-4' },
    fig(ctx, BRANCH_FIG.intake, vb(ctx, b.intake_per_year, b.intake_basis), BRANCH_FIG_HELP.intake),
    fig(ctx, BRANCH_FIG.final_year, vb(ctx, b.final_year, b.final_year_basis), BRANCH_FIG_HELP.final_year),
    fig(ctx, BRANCH_FIG.eligible, vb(ctx, b.eligible_estimate, b.eligible_basis), BRANCH_FIG_HELP.eligible),
    fig(ctx, BRANCH_FIG.strength, vb(ctx, b.strength_total, b.strength_basis), BRANCH_FIG_HELP.strength));
}
export function fig(ctx, label, node, help) {
  return ctx.h('div', { class: 'vx-fig', title: help || null }, ctx.h('div', { class: 'vx-fig-label' }, label), ctx.h('div', { class: 'vx-fig-value' }, node));
}

/* ------------------------------------------------------------------ branch drawer */

let openDrawer = null;
let openId = null;
let silentClose = false;

/** Id of the branch whose drawer is open (null when none). */
export function openBranchId() { return openDrawer ? openId : null; }

/** Close the branch drawer without firing the caller's onUserClose (used when the URL already changed). */
export function closeBranch() {
  if (!openDrawer) return;
  silentClose = true;
  try { openDrawer.close(); } finally { silentClose = false; }
}

function drawerSkeleton(ctx) {
  const { h, ui } = ctx;
  return h('div', { class: 'v-branch is-drawer', 'aria-busy': 'true' },
    h('div', { class: 'vb-skel' }, h('div', { class: 'td-skel td-skel--title' }), h('div', { class: 'td-skel', style: { width: '40%' } })),
    ui.skeleton ? ui.skeleton(3) : h('div', { class: 'vx-loading' }, 'Loading branch…'),
    ui.skeleton ? ui.skeleton(4) : null);
}

/**
 * Open the branch drawer.
 * opts.onUserClose() — called when the person closes it (X, Esc, backdrop), not when closeBranch() is used.
 * opts.inCollege — the college page is underneath, so the "Open college" link is hidden.
 */
export async function openBranch(branchId, ctx, opts = {}) {
  const { h, ui } = ctx;
  let body = drawerSkeleton(ctx);
  if (openDrawer) closeBranch();
  const dctx = { ...ctx, refresh: () => { reload(); ctx.refresh?.(); } };
  let mine = null;
  mine = ui.drawer({
    title: 'Branch', body, wide: true,
    onClose: () => {
      if (openDrawer === mine) { openDrawer = null; openId = null; }
      if (!silentClose && opts.onUserClose) opts.onUserClose();
    },
  });
  openDrawer = mine;
  openId = String(branchId);
  async function reload() {
    try {
      const node = await renderBranchPage(null, { id: branchId }, dctx, true, opts);
      if (openDrawer !== mine) return;
      const holder = mine.el?.querySelector('.td-drawer__body');
      const keep = holder ? holder.scrollTop : 0;
      body.replaceWith(node);
      body = node;
      if (holder) holder.scrollTop = keep;
      const t = mine.el?.querySelector('.td-drawer__title');
      if (t && node.dataset.title) t.textContent = node.dataset.title;
    } catch (e) {
      if (openDrawer !== mine) return;
      if (e && e.status === 404) {
        // e.g. the branch was just deleted from its own edit form
        mine.close();
        return;
      }
      const err = h('div', { class: 'v-branch is-drawer' }, ui.emptyState({
        title: 'Could not load this branch', text: e.message || String(e), icon: 'warn',
        action: btn(ctx, 'Try again', () => reload(), { tone: 'primary', icon: 'refresh' }),
      }));
      body.replaceWith(err);
      body = err;
    }
  }
  await reload();
  return openDrawer;
}

/** Short, readable label for a source link ("kluniversity.in · PDF"). */
export function sourceLabel(url) {
  if (!url) return '';
  if (!/^https?:\/\//i.test(url)) return String(url);
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./i, '').toLowerCase();
    return /\.pdf($|\?)/i.test(u.pathname) ? `${host} · PDF` : host;
  } catch { return String(url).slice(0, 48); }
}
export function sourceLink(ctx, url, label) {
  if (!url) return null;
  if (!/^https?:\/\//i.test(url)) return ctx.h('span', null, url);
  return ctx.h('a', { href: url, target: '_blank', rel: 'noopener', class: 'vx-link', title: url }, label || sourceLabel(url), ctx.ui.icon('external', { size: 14 }));
}

/** Renders the full branch view. If `el` is given, renders into it; returns the node. */
export async function renderBranchPage(el, params, ctx, inDrawer = false, opts = {}) {
  const { h, ui, fmt, api } = ctx;
  const id = params.id;
  const [d, meta] = await Promise.all([api.get(`/branches/${id}`), getMeta(ctx)]);
  const b = d.branch || {};
  const r = d.rollup || {};
  let collegeRoll = null;
  try { collegeRoll = await api.get('/summary', { scope: `college:${b.college_id}` }); } catch { /* optional */ }
  const people = d.people || [];
  const ambs = people.filter((p) => p.role === 'ambassador');
  const leads = people.filter((p) => p.role !== 'ambassador' && p.status !== 'inactive');
  const activeAmbs = ambs.filter((p) => p.status !== 'inactive');
  const ctxB = { college_id: b.college_id, branch_id: b.id };
  const collegeName = b.college_short_name || b.college_name || d.college_name || '';
  const gap = !!b.is_relevant && !activeAmbs.length;
  const recruit = () => forms.addPerson(ctx, { college_id: b.college_id, role: 'ambassador', branch_ids: [b.id] });

  const wrap = h('div', { class: ['v-branch', inDrawer && 'is-drawer'], dataset: { title: [b.code || b.name || 'Branch', collegeName].filter(Boolean).join(' · ') } });

  // header
  wrap.append(h('header', { class: 'vb-head' },
    h('div', { class: 'vb-title' },
      h('div', { class: 'vb-titlerow' }, h('h2', null, b.name || b.code || 'Branch'), btn(ctx, 'Edit', () => forms.editBranch(ctx, b), { small: true, icon: 'edit', tone: 'ghost', aria: 'Edit branch details or delete branch', title: 'Edit branch details' })),
      h('div', { class: 'vx-row' },
        b.code ? h('span', { class: 'vx-code' }, b.code) : null,
        ui.badge(CATEGORY_LABEL[b.category] || b.category || 'Uncategorised', b.is_relevant ? 'brand' : 'neutral'),
        h('span', { title: TARGET_BRANCH_HELP }, b.is_relevant ? ui.badge('Target branch', 'info') : ui.badge('Not a target branch', 'neutral')),
        gap ? ui.badge('No ambassador', 'bad') : null,
        r.target && r.on_track != null ? ui.statusBadge('on_track', r.on_track) : null,
        r.target && r.on_track === false && r.diagnosis ? ui.statusBadge('diagnosis', r.diagnosis) : null,
        b.is_demo ? ui.badge('DEMO', 'bad') : null),
      !opts.inCollege && b.college_id ? h('a', { href: `#/college/${b.college_id}?tab=branches&branch=${b.id}`, class: 'vx-link vx-small' }, ui.icon('college', { size: 16 }), collegeName ? `Open ${collegeName}` : 'Open college') : null)));

  // actions — ONE row, stable order, one primary (UI-23); sections below have no duplicate add buttons
  wrap.append(h('div', { class: 'vx-actions vb-actions', role: 'toolbar', 'aria-label': 'Branch actions' },
    btn(ctx, 'Record enrollment', () => forms.recordEnrollment(ctx, ctxB), { icon: 'plus', tone: 'primary' }),
    btn(ctx, 'Add ambassador', recruit, { icon: 'ambassador' }),
    btn(ctx, 'Log activity', () => forms.logActivity(ctx, ctxB), { icon: 'clock' }),
    btn(ctx, 'Add follow-up', () => forms.addFollowup(ctx, { scope_type: 'branch', scope_id: String(b.id), college_id: b.college_id }), { icon: 'followup' })));

  // students
  wrap.append(ui.section({
    title: 'Students',
    sub: 'Each number shows whether it is verified, estimated or still pending. Hover a number for how it is worked out.',
    body: h('div', { class: 'vb-students' }, branchFigures(ctx, b),
      b.intake_source || b.intake_year ? h('p', { class: 'vx-small vx-muted vb-source' }, 'Seats from: ',
        b.intake_source ? sourceLink(ctx, b.intake_source) : 'source not recorded', b.intake_year && b.intake_year !== 'unspecified' ? ` (${b.intake_year})` : '') : null),
  }));

  // target
  const ct = collegeRoll?.target;
  const share = r.target && ct ? r.target / ct : null;
  wrap.append(ui.section({
    title: 'Target and progress',
    actions: btn(ctx, r.target ? 'Change target' : 'Set target', () => forms.setTarget('branch', String(b.id), ctx, { college_id: b.college_id, label: [collegeName, b.code || b.name].filter(Boolean).join(' · ') }), { small: true, icon: 'target', tone: r.target ? null : 'primary' }),
    body: h('div', { class: 'vb-target' },
      h('div', { class: 'vx-figs vx-figs-4' },
        fig(ctx, 'Target', r.target ? fmt.num(r.target) : h('span', { class: 'vx-muted' }, 'Not set')),
        fig(ctx, 'Confirmed', fmt.num(r.enrolled ?? 0)),
        fig(ctx, r.target && r.exceeded_by > 0 ? 'Exceeded by' : 'Remaining', r.target ? fmt.num(r.exceeded_by > 0 ? r.exceeded_by : r.remaining) : '—'),
        fig(ctx, 'Students reached', fmt.num(r.reached ?? 0))),
      r.target ? ui.progress({ target: r.target, done: r.enrolled || 0, size: 'md' }) : null,
      h('p', { class: 'vx-small vx-muted' }, r.target
        ? `${r.target_source === 'sum_of_children' ? 'Target is the sum of this branch’s ambassador targets.' : 'Target set for this branch.'}${share != null ? ` It is ${pctOf(share)} of the college target (${fmt.num(r.target)} of ${fmt.num(ct)}).` : ''}${r.deadline ? ` Deadline ${fmt.date(r.deadline)}.` : ''}`
        : ct ? `The college target is ${fmt.num(ct)}. Set a branch target to split it across branches.` : 'Neither this branch nor the college has a target yet.')),
  }));

  // people
  const responsible = leads.length ? leads.map((p) => h('a', { href: `#/person/${p.id}`, class: 'vx-link' }, `${p.full_name} (${ROLE_LABEL[p.role]})`)) : (() => {
    const ids = [...new Set(ambs.map((a) => a.reports_to_name).filter(Boolean))];
    return ids.length ? ids.join(', ') : null;
  })();
  wrap.append(ui.section({
    title: `Ambassadors (${fmt.num(activeAmbs.length)} active)`,
    body: h('div', { class: 'vb-people' },
      h('p', { class: 'vx-small' }, h('span', { class: 'vx-muted' }, 'Responsible lead: '), responsible
        ? (Array.isArray(responsible) ? h('span', { class: 'vx-contacts' }, responsible) : responsible)
        : h('span', { class: 'vx-warn-text' }, 'none appointed yet')),
      ambs.length ? ui.table({
        columns: [
          { key: 'full_name', label: 'Name', render: (p) => h('a', { href: `#/person/${p.id}`, class: p.status === 'inactive' ? 'is-inactive' : null }, p.full_name) },
          { key: 'contact', label: 'Contact', sortable: false, render: (p) => (ui.contactActions ? ui.contactActions(p.phone, p.email, { compact: true, whatsapp: true, name: p.full_name }) : contactLinks(ctx, p)) },
          { key: 'target', label: 'Target', align: 'right', render: (p) => { const t = p.target_summary ? p.target_summary.target : p.target; return t == null ? '—' : fmt.num(t); } },
          { key: 'reached', label: 'Reached', align: 'right', render: (p) => fmt.num(p.reached ?? 0) },
          { key: 'enrolled', label: 'Confirmed', align: 'right', render: (p) => fmt.num(p.actual_own ?? p.enrolled ?? 0) },
          { key: 'status', label: 'Status', render: (p) => ui.statusBadge('person_status', p.status || 'active') },
        ],
        rows: ambs.slice().sort((x, y) => (x.status === 'inactive') - (y.status === 'inactive')),
        // navigating changes the page; the router closes this drawer for us
        onRowClick: (p) => ctx.navigate(`#/person/${p.id}`),
      }) : callout(ctx, b.is_relevant ? 'bad' : 'info', 'No ambassador for this branch',
        b.is_relevant ? 'This branch counts toward the target. Recruit at least one student ambassador to start outreach.' : 'This branch does not count toward the target, so an ambassador is optional.',
        btn(ctx, 'Recruit ambassador', recruit, { tone: b.is_relevant ? 'primary' : null, small: true }))),
  }));

  // outreach
  const fu = d.followups || [];
  const openFu = fu.filter((f) => f.status === 'open').length;
  wrap.append(ui.section({ title: `Follow-ups (${fmt.num(openFu)} open)`,
    body: followupList(ctx, fu, { emptyText: 'Plan the next call or visit for this branch so it does not slip.' }) }));
  wrap.append(ui.section({ title: 'Recent activity',
    body: activityList(ctx, (d.activities || []).slice(0, 15), { emptyText: 'Log a visit, call or session after you reach students in this branch.' }) }));
  wrap.append(ui.section({ title: 'Recent enrollments',
    body: enrollmentList(ctx, (d.enrollments || []).slice(0, 15), { courses: meta.courses, people, branches: [b] }, { emptyText: 'When a student from this branch enrolls, record it here so progress updates.' }) }));

  if (b.notes) wrap.append(ui.section({ title: 'Research notes', body: h('p', { class: 'vb-notes' }, b.notes) }));
  if (el) el.replaceChildren(wrap);
  return wrap;
}

export async function render(el, params, ctx) {
  await renderBranchPage(el, params, ctx);
}
