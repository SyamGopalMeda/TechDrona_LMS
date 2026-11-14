// Tech Drona portal — shared forms (Team agent owns: person, target and enrollment dialogs)
// Each export opens a ui.modal containing a ui.form, saves through the API, toasts, then calls ctx.refresh().
// Call style is flexible: ctx may be passed first or last, e.g. addPerson(ctx, {college_id}) or setTarget('college', 'c9', ctx).

import { apiUrl } from '../api.js';
const ROLE_OPTS = [
  { value: 'ambassador', label: 'Ambassador' },
  { value: 'ambassador_lead', label: 'Ambassador lead' },
  { value: 'college_lead', label: 'College lead' },
];
const ROLE_LABEL = { college_lead: 'College lead', ambassador_lead: 'Ambassador lead', ambassador: 'Ambassador' };
const STATUS_OPTS = [
  { value: 'active', label: 'Active' }, { value: 'onboarding', label: 'Onboarding' }, { value: 'inactive', label: 'Inactive (deactivated)' },
];
const BASIS_OPTS = [
  { value: 'verified', label: 'Verified (official source)' }, { value: 'estimated', label: 'Estimated' }, { value: 'pending', label: 'Pending / unknown' },
];
// Same names as branch.js CATEGORY_LABEL (mirrored, not imported: branch.js imports this module, and this list is built at load time)
const CATEGORY_OPTS = [
  { value: 'it_core', label: 'Computer science' }, { value: 'it_allied', label: 'CS-related (AI, data, IoT…)' },
  { value: 'circuit', label: 'Electronics / electrical' }, { value: 'core', label: 'Other engineering' }, { value: 'other', label: 'Other' },
];
// (follow-up reasons live in followups.js ISSUES: one list for every follow-up form)
const ACT_OPTS = [
  { value: 'visit', label: 'Campus visit' }, { value: 'call', label: 'Call' }, { value: 'session', label: 'Session / workshop' },
  { value: 'whatsapp', label: 'WhatsApp' }, { value: 'followup', label: 'Follow-up' }, { value: 'other', label: 'Other' },
];
const OP_OPTS = [
  { value: 'operational', label: 'Operational' }, { value: 'possibly_closed', label: 'Possibly closed' },
  { value: 'closed', label: 'Closed' }, { value: 'pending', label: 'Pending / unknown' },
];
const YNU = [{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }, { value: 'unknown', label: 'Unknown' }];
const YN = [{ value: '1', label: 'Yes' }, { value: '0', label: 'No' }];
const NONE = (label = '— None —') => ({ value: '', label });

/* ------------------------------------------------------------------ plumbing */

const isCtx = (a) => a && typeof a === 'object' && a.api && a.ui && a.h;
let fallbackCtx = null;
async function getFallbackCtx() {
  if (fallbackCtx) return fallbackCtx;
  const [{ api }, ui, hm] = await Promise.all([import('../api.js'), import('../ui/components.js'), import('../ui/h.js')]);
  fallbackCtx = {
    api, ui: ui.default || ui, h: hm.h, fmt: hm.fmt,
    navigate: (href) => { location.hash = href; },
    refresh: () => window.dispatchEvent(new HashChangeEvent('hashchange')),
  };
  return fallbackCtx;
}
async function split(args) {
  const ctx = args.find(isCtx) || await getFallbackCtx();
  return [ctx, args.filter((a) => !isCtx(a))];
}

function todayStr() {
  const o = new URLSearchParams(location.search).get('today');
  if (o && /^\d{4}-\d{2}-\d{2}$/.test(o)) return o;
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
const num = (v) => (v === '' || v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v));
const str = (v) => (v === undefined || v === null ? null : (String(v).trim() || null));
const arr = (v) => (Array.isArray(v) ? v : v === '' || v == null ? [] : String(v).split(',')).map(Number).filter((x) => !Number.isNaN(x));

const PHONE_RE = /^(\+?91)?[6-9]\d{9}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
function validationError(fields) {
  const e = new Error(Object.values(fields)[0]);
  e.fields = fields;
  e.status = 400;
  return e;
}

/** "+919876543210" / "98765-43210" -> "+91 98765 43210". Anything else is returned unchanged. */
export function formatPhone(v) {
  if (v === null || v === undefined) return '';
  const d = String(v).replace(/[\s()-]/g, '');
  const m = d.match(/^(?:\+?91)?([6-9]\d{4})(\d{5})$/) || d.match(/^\+91(\d{5})(\d{5})$/);
  return m ? `+91 ${m[1]} ${m[2]}` : String(v).trim();
}

/** Whole number >= 0, or null when blank. Throws-friendly message otherwise. */
function wholeOrNull(v) {
  const n = num(v);
  if (n === null) return null;
  return Number.isInteger(n) && n >= 0 ? n : NaN;
}

/**
 * Inline validation: run each rule when its input loses focus (and again on input once it has shown an error).
 * rules: {name: (value, formEl) => message|''}
 */
function liveValidate(formEl, rules) {
  for (const [name, rule] of Object.entries(rules)) {
    const el = field(formEl, name);
    if (!el) continue;
    let shown = false;
    const check = () => {
      const msg = rule(el.value.trim(), formEl) || '';
      if (msg || shown) formEl.setErrors?.({ [name]: msg });
      shown = !!msg;
    };
    el.addEventListener('blur', check);
    el.addEventListener('input', () => { if (shown) check(); });
  }
}

/** Show/hide a whole ui.form field (wrapper included). */
function showField(formEl, name, on) {
  const el = field(formEl, name) || formEl.querySelector(`[data-field="${name}"]`);
  const wrap = el?.closest('.td-field');
  if (wrap) wrap.hidden = !on;
}
function setHelp(formEl, name, text) {
  const el = field(formEl, name);
  const wrap = el?.closest('.td-field');
  const help = wrap?.querySelector('.td-field__help');
  if (help) help.textContent = text;
}

/** Make sure we know who is making changes (X-User header). */
async function ensureUser(ctx) {
  if (ctx.api.user) return true;
  // Prefer the shell's own prompt (ctx.ensureUser rejects when the user cancels).
  const shellPrompt = [ctx.ensureUser, ctx.promptUser, ctx.askUser].find((fn) => typeof fn === 'function');
  if (shellPrompt) {
    try { await shellPrompt(); } catch { return false; }
    return !!ctx.api.user;
  }
  const { ui, h } = ctx;
  return new Promise((resolve) => {
    let m;
    let done = false;
    const f = ui.form({
      fields: [{ name: 'name', label: 'Your name', type: 'text', required: true, help: 'Saved on this device and recorded with every change you make.' }],
      submitLabel: 'Continue',
      onSubmit: async (v) => {
        const n = str(v.name);
        if (!n) throw validationError({ name: 'Please enter your name.' });
        ctx.api.setUser(n);
        done = true;
        m.close();
        resolve(true);
      },
    });
    m = ui.modal({
      title: 'Who is making this change?',
      body: h('div', { class: 'vx-form' }, h('p', { class: 'vx-muted' }, 'Changes are logged with your name in the audit history.'), f),
      actions: [{ label: 'Cancel', tone: 'neutral', onClick: () => { m.close(); if (!done) resolve(false); } }],
    });
  });
}

/**
 * Open a modal containing a ui.form.
 * onSubmit(values) does the API work; on success the modal closes, a toast shows and ctx.refresh() runs.
 */
async function openForm(ctx, { title, intro, fields, submitLabel = 'Save', onSubmit, success = 'Saved', after, extra }) {
  if (!(await ensureUser(ctx))) return null;
  const { ui, h } = ctx;
  let m;
  // ui.form adds its own empty option: turn a leading {value:''} option into the placeholder.
  const byName = {};
  for (const fd of fields) {
    byName[fd.name] = fd;
    if (fd.type === 'select' && fd.options && fd.options[0] && fd.options[0].value === '') {
      fd.placeholder = fd.options[0].label;
      fd.options = fd.options.slice(1);
    }
  }
  const form = ui.form({
    fields, submitLabel,
    onCancel: () => m?.close(),
    onSubmit: async (vals) => {
      // errors propagate: ui.form shows them inline and toasts non-validation errors
      const res = await onSubmit(vals);
      if (res && res._keepOpen) return res;
      ui.toast(typeof success === 'function' ? success(res, vals) : success, 'good');
      m?.close();
      ctx.refresh?.();
      return res;
    },
  });
  const body = h('div', { class: 'vx-form' }, intro ? h('div', { class: 'vx-form-intro' }, intro) : null, form, extra || null);
  m = ui.modal({ title, body, actions: [] });
  try { after?.(form, byName); } catch (e) { console.warn('form wiring', e); }
  return m;
}

/**
 * Show only the options of a rendered ui.form <select> for which pred(option) is true.
 * ui.form uses the option index as the DOM value, so options are hidden/disabled rather than replaced.
 */
function filterSelect(formEl, fd, pred) {
  const sel = formEl.querySelector(`select[name="${fd.name}"]`);
  if (!sel) return;
  for (const op of sel.options) {
    if (op.value === '') continue;
    const o = fd.options[Number(op.value)];
    const ok = !!o && pred(o);
    op.hidden = !ok;
    op.disabled = !ok;
  }
  if (sel.selectedOptions[0] && sel.selectedOptions[0].disabled) sel.value = '';
}
const field = (formEl, name) => formEl.querySelector(`[name="${name}"]`);
/** fn receives the real option value (not the DOM index) of a select. */
function onChange(formEl, fd, fn) {
  const el = field(formEl, fd.name);
  if (el) el.addEventListener('change', () => fn(el.value === '' ? '' : (fd.options[Number(el.value)]?.value ?? '')));
}

let metaCache = null;
async function meta(ctx) {
  if (!metaCache) { try { metaCache = await ctx.api.get('/meta'); } catch { metaCache = {}; } setTimeout(() => { metaCache = null; }, 60000); }
  return metaCache;
}
async function collegeDetail(ctx, id) { return id ? ctx.api.get(`/colleges/${id}`) : null; }
const personBranchIds = (p, branches) => {
  let ids = Array.isArray(p.branch_ids) ? p.branch_ids : Array.isArray(p.branches) ? p.branches.map((b) => (b && typeof b === 'object' ? (b.id ?? b.branch_id) : b)) : [];
  ids = ids.map(Number).filter((x) => !Number.isNaN(x));
  if (!ids.length && branches) for (const b of branches) if ((b.people || []).some((q) => Number(q.id) === Number(p.id))) ids.push(Number(b.id));
  return ids;
};
const branchOpts = (branches) => (branches || []).map((b) => ({ value: String(b.id), label: `${b.code ? b.code + ' — ' : ''}${b.name || ''}${b.is_relevant ? '' : ' (not a target branch)'}` }));
const personOpt = (p) => ({ value: String(p.id), label: `${p.full_name} (${ROLE_LABEL[p.role] || p.role}${p.status === 'inactive' ? ', inactive' : ''})`, role: p.role, branches: p._b || [] });

const ALLOWED_BOSS = { ambassador: ['ambassador_lead', 'college_lead'], ambassador_lead: ['college_lead'], college_lead: [] };
const BRANCH_HELP = {
  college_lead: 'Optional. A college lead covers the whole college — leave empty unless they also look after specific branches.',
  ambassador_lead: 'Branches this lead looks after (can be several).',
  ambassador: 'Branches where this ambassador talks to students. Enrollments can only be credited to people covering that branch.',
};
const BOSS_HELP = {
  ambassador: 'An ambassador reports to an ambassador lead or the college lead.',
  ambassador_lead: 'An ambassador lead reports to the college lead.',
};

/** Pick a college first (for forms opened outside a college page): type-to-filter list, Enter picks. */
async function pickCollege(ctx, title) {
  const { ui, h } = ctx;
  let list = [];
  let m0 = {};
  try { [list, m0] = await Promise.all([ctx.api.get('/colleges'), meta(ctx)]); } catch (e) { ui.toast(e.message, 'bad'); return null; }
  const dn = new Map((m0.districts || []).map((d) => [d.id, d.name]));
  const all = list.map((c) => ({
    id: c.id, label: c.short_name || c.name,
    sub: [c.short_name && c.short_name !== c.name ? c.name : null, dn.get(c.district_id) || c.district_id].filter(Boolean).join(' · '),
    hay: `${c.name} ${c.short_name || ''} ${dn.get(c.district_id) || ''}`.toLowerCase(), targeted: c.targeted ? 1 : 0,
  })).sort((a, b) => (b.targeted - a.targeted) || a.label.localeCompare(b.label));
  return new Promise((resolve) => {
    let done = false;
    let m = null;
    const finish = (v) => { if (done) return; done = true; resolve(v); m?.close(); };
    const search = h('input', { type: 'search', class: 'td-input', placeholder: 'Type a college or district name…', 'aria-label': 'Search colleges', autofocus: true, autocomplete: 'off' });
    const box = h('div', { class: 'vf-pick', role: 'listbox', 'aria-label': 'Colleges' });
    const note = h('p', { class: 'vf-pick-note', 'aria-live': 'polite' });
    let shown = [];
    let idx = 0;
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      shown = all.filter((c) => !q || q.split(/\s+/).every((w) => c.hay.includes(w))).slice(0, 60);
      idx = Math.min(idx, Math.max(shown.length - 1, 0));
      box.replaceChildren(...shown.map((c, i) => h('button', {
        type: 'button', role: 'option', class: ['vf-pick-opt', i === idx && 'is-active'], 'aria-selected': String(i === idx), onClick: () => finish(c.id),
      }, h('span', { class: 'vf-pick-name' }, c.label, c.targeted ? h('span', { class: 'vf-pick-tag' }, 'Targeted') : null), h('span', { class: 'vf-pick-sub' }, c.sub))));
      note.textContent = shown.length
        ? (all.length > shown.length ? `Showing ${shown.length} of ${all.length}. Keep typing to narrow down.` : '')
        : 'No college matches. Check the spelling or try the district name.';
    };
    search.addEventListener('input', () => { idx = 0; draw(); });
    search.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        idx = Math.max(0, Math.min(shown.length - 1, idx + (e.key === 'ArrowDown' ? 1 : -1)));
        draw();
        box.querySelector('.is-active')?.scrollIntoView({ block: 'nearest' });
      }
      if (e.key === 'Enter') { e.preventDefault(); if (shown[idx]) finish(shown[idx].id); }
    });
    draw();
    m = ui.modal({
      title,
      body: h('div', { class: 'vf-form' }, h('p', { class: 'vf-intro' }, 'Choose the college first. Type to search, use the arrow keys and Enter, or click.'), search, note, box),
      actions: [{ label: 'Cancel', tone: 'ghost', onClick: () => { finish(null); } }],
    });
    const obs = new MutationObserver(() => { if (!document.contains(m.el)) { obs.disconnect(); if (!done) { done = true; resolve(null); } } });
    obs.observe(document.body, { childList: true, subtree: true });
  });
}


/* ------------------------------------------------------------------ people */
// ONE person dialog (add + edit) plus the Move college, Replace lead and Deactivate flows (PLAN R1–R6).
// The server enforces the rules; the dialog explains them before saving and shows what the server changed.

const LEAD_ROLES = ['college_lead', 'ambassador_lead'];
const isActive = (p) => p && p.status !== 'inactive';

/**
 * F6 — ONE phone rule, mirrored from the server (CONTRACT v4.1): PEOPLE = Indian mobile only (+91 then 6-9 and 9 digits);
 * college CONTACTS = mobile or STD landline (college-form.js phoneError). A person whose stored number is an older landline
 * can still be re-saved: an unchanged phone is never re-validated or re-sent (see personDialog).
 * "+91 98765 43210" / "098765-43210" / "9876543210" -> "+919876543210"; null when it is not a 10-digit Indian mobile.
 */
export const PERSON_PHONE_RULE = 'Enter a 10-digit Indian mobile number, e.g. 98765 43210 (+91 optional).';
const phoneDigits = (v) => String(v ?? '').replace(/\D/g, '');
/** Exact mirror of server/db.js normPhone (v4.1): any Indian number (mobile or STD landline) -> "+91XXXXXXXXXX", else null. */
export function normAnyPhone(v) {
  if (v == null) return null;
  let s = String(v).split(/\b(?:ext|extn)\b|\bx\s*\d|[,;/]/i)[0];
  s = s.replace(/[^\d+]/g, '');
  let d = s.replace(/\+/g, '');
  if (s.startsWith('+') && !d.startsWith('91')) return null; // foreign number
  if (d.startsWith('0091')) d = d.slice(4);
  if (d.length === 13 && d.startsWith('910')) d = d.slice(3);
  if (d.length === 12 && d.startsWith('91')) d = d.slice(2);
  else if (d.length === 11 && d.startsWith('0')) d = d.slice(1);
  if (!/^[1-9]\d{9}$/.test(d)) return null;
  return `+91${d}`;
}
/** People: mobile only (server isMobile: ^\+91[6-9]\d{9}$). */
export function normPhone(v) {
  const n = normAnyPhone(v);
  return n && /^\+91[6-9]\d{9}$/.test(n) ? n : null;
}
let v4Promise = null;
/** true on v4+ servers (GET /api/health → version), cached for the session; false when unknown. */
export function serverIsV4(ctx) {
  if (!v4Promise) v4Promise = ctx.api.get('/health').then((x) => !!x && /^v(\d+)/.test(String(x.version || '')) && Number(String(x.version).match(/^v(\d+)/)[1]) >= 4, () => { v4Promise = null; return false; });
  return v4Promise;
}
/** Trimmed, lower-cased email (null when blank). */
export function normEmail(v) { const s = str(v); return s ? s.toLowerCase() : null; }

/** Error helpers: the 409 body's existing_id may sit on the error (api.js v4) or only in the message. */
const errExisting = (e) => e?.existing_id ?? e?.data?.existing_id ?? e?.body?.existing_id ?? e?.extra?.existing_id ?? null;
const missingEndpoint = (e) => e && (e.status === 404 || e.status === 405);
/** Rows from GET /people whatever its shape (v4 {items} or the older plain array). */
export const peopleRows = (r) => (Array.isArray(r) ? r : Array.isArray(r?.items) ? r.items : []);

/** Active/onboarding people anywhere with the same normalised phone or email (excluding selfId). Uses live search. */
export async function findDuplicatePeople(ctx, { phone, email } = {}, selfId = null) {
  const np = normPhone(phone);
  const ne = normEmail(email);
  const jobs = [];
  if (np) jobs.push(['phone', np.slice(3)]);
  if (ne && EMAIL_RE.test(ne)) jobs.push(['email', ne]);
  const out = new Map();
  await Promise.all(jobs.map(async ([kind, q]) => {
    let rows = [];
    try { rows = peopleRows(await ctx.api.get('/people', { q, page_size: 50 })); } catch { return; }
    for (const p of rows) {
      if (Number(p.id) === Number(selfId) || !isActive(p)) continue;
      const hit = kind === 'phone' ? normPhone(p.phone) === np : String(p.email || '').trim().toLowerCase() === ne;
      if (hit) out.set(Number(p.id), { ...p, _field: kind });
    }
  }));
  return [...out.values()];
}

function dupNotice(ctx, list, { onOpen } = {}) {
  const { h } = ctx;
  if (!list.length) return null;
  return h('div', { class: 'vf-note vf-note--warn v-person-dup', role: 'alert' },
    h('strong', null, list.length === 1 ? 'Already in the team' : `${list.length} people already use these details`),
    h('ul', null, list.map((p) => h('li', null,
      `${p.full_name || 'Unnamed'} — ${ROLE_LABEL[p.role] || p.role}, ${p.college_short_name || p.college?.name || p.college_name || p.college_id || 'college unknown'}`,
      ` (same ${p._field === 'email' ? 'email' : 'mobile number'}) `,
      h('a', { href: `#/person/${p.id}`, class: 'v-person-dup__open', onClick: () => onOpen?.() }, 'Open existing')))),
    h('p', { class: 'vx-small' }, 'Edit the existing record instead of adding the same person twice.'));
}

const personOptV = (p, extra = {}) => ({ value: String(p.id), label: `${p.full_name} (${ROLE_LABEL[p.role] || p.role}${p.status === 'onboarding' ? ', onboarding' : ''})`, role: p.role, ...extra });
/** Valid managers for a role inside one college (R2): active college lead / ambassador lead, never yourself. */
export function validLeads(people, role, selfId = null) {
  const allowed = ALLOWED_BOSS[role] || [];
  return (people || []).filter((p) => allowed.includes(p.role) && isActive(p) && Number(p.id) !== Number(selfId));
}

/** Asks what happens to the current college lead (R5). Resolves 'ambassador_lead' | 'inactive' | null (cancel). */
function askOldLeadFate(ctx, oldLead, newName) {
  const { h, ui } = ctx;
  return new Promise((resolve) => {
    let answered = false;
    const pick = { v: 'ambassador_lead' };
    const radio = (value, title, text) => h('label', { class: 'v-person-choice' },
      h('input', { type: 'radio', name: 'td-oldlead', value, checked: value === pick.v ? true : null, onChange: () => { pick.v = value; } }),
      h('span', null, h('strong', null, title), h('span', { class: 'vx-small vx-muted' }, text)));
    const m = ui.modal({
      title: 'Replace the college lead?',
      body: h('div', { class: 'v-person-dlg' },
        h('p', null, `${oldLead.full_name} is the college lead here. A college can have only one active college lead, so ${newName || 'the new person'} replaces them.`),
        h('fieldset', { class: 'v-person-choices' }, h('legend', null, `What should happen to ${oldLead.full_name}?`),
          radio('ambassador_lead', 'Keep them as an ambassador lead', 'They stay in the team, reporting to the new college lead. Their direct reports move to the new college lead.'),
          radio('inactive', 'Set them inactive', 'History and credited enrollments are kept. Their direct reports move to the new college lead.'))),
      actions: [
        { label: 'Cancel', tone: 'ghost', onClick: () => { answered = true; resolve(null); } },
        { label: 'Replace lead', tone: 'primary', onClick: () => { answered = true; resolve(pick.v); } },
      ],
    });
    const obs = new MutationObserver(() => { if (!document.contains(m.el)) { obs.disconnect(); if (!answered) resolve(null); } });
    obs.observe(document.body, { childList: true, subtree: true });
  });
}

/** POST /people/:old/replace-lead (R5). Falls back to the same steps one by one on servers without the endpoint. */
export async function replaceLeadRequest(ctx, oldId, newId, fate) {
  try {
    return await ctx.api.post(`/people/${oldId}/replace-lead`, { new_lead_id: Number(newId), old_lead_becomes: fate });
  } catch (e) { if (!missingEndpoint(e)) throw e; }
  // same steps one by one (old lead first, so there is never a second active college lead)
  const od = await ctx.api.get(`/people/${oldId}`);
  const reports = (od.reports || []).filter((r) => Number(r.id) !== Number(newId) && isActive(r));
  await ctx.api.patch(`/people/${oldId}`, fate === 'inactive' ? { status: 'inactive' } : { role: 'ambassador_lead', reports_to: null });
  await ctx.api.patch(`/people/${newId}`, { role: 'college_lead', reports_to: null, status: 'active' });
  if (fate !== 'inactive') await ctx.api.patch(`/people/${oldId}`, { reports_to: Number(newId) });
  const moved = [];
  for (const r of reports) {
    try { await ctx.api.patch(`/people/${r.id}`, { reports_to: Number(newId) }); moved.push(r.id); } catch { /* left unassigned; shown in Team */ }
  }
  return { moved };
}

/** Plain-language summary of PATCH/POST side effects returned by the v4 server. */
function sideEffectText(res) {
  const se = res?.side_effects || {};
  const parts = [];
  if (se.unassigned?.length) parts.push(`${se.unassigned.length} ${se.unassigned.length === 1 ? 'person is' : 'people are'} now unassigned`);
  if (se.removed_branches?.length) parts.push(`${se.removed_branches.length} branch link${se.removed_branches.length === 1 ? '' : 's'} removed`);
  if (se.reassigned?.length) parts.push(`${se.reassigned.length} moved to the new lead`);
  return parts.join(' · ');
}

const DESIGNATION_HELP = 'What they do in the team, e.g. "CSE 3rd-year coordinator" or "Hostel outreach".';

/**
 * THE person dialog. opts: {id} to edit, or {college_id, role, reports_to, branch_ids} to add.
 * Add without college_id asks for the college first.
 */
export async function personDialog(...args) {
  const [ctx, [o0 = {}]] = await split(args);
  const opts = typeof o0 === 'object' && o0 ? o0 : { id: o0 };
  const { h, ui } = ctx;
  const editing = opts.id != null && opts.id !== '';
  let p = {};
  let pd = null;
  if (editing) {
    try { pd = await ctx.api.get(`/people/${opts.id}`); p = pd.person || pd; } catch (e) { ui.toast(e.message, 'bad'); return null; }
  }
  let collegeId = editing ? p.college_id : opts.college_id;
  if (!collegeId) { collegeId = await pickCollege(ctx, 'Add a person — choose their college'); if (!collegeId) return null; }
  let d;
  try { d = await collegeDetail(ctx, collegeId); } catch (e) { ui.toast(e.message, 'bad'); return null; }
  const branches = d.branches || [];
  const people = d.people || [];
  const cname = d.college?.short_name || d.college?.name || collegeId;
  const currentLead = people.find((x) => x.role === 'college_lead' && isActive(x) && Number(x.id) !== Number(p.id));
  const role0 = editing ? p.role : (opts.role || (currentLead ? 'ambassador' : 'college_lead'));
  // D4: v4 servers always store a designation — offer it for the first person of a college too (no rows to infer from)
  const supportsDesignation = 'designation' in p || people.some((x) => 'designation' in x) || await serverIsV4(ctx);
  // F6: the stored phone (perhaps an older landline) passes unchanged; only a NEW number must be a mobile
  const storedPhone = editing && p.phone ? String(p.phone) : '';
  const phoneUnchanged = (val) => !!storedPhone && phoneDigits(val) !== '' && (phoneDigits(val) === phoneDigits(storedPhone) || phoneDigits(val) === phoneDigits(formatPhone(storedPhone)));
  const phoneErr = (val) => (str(val) && !normPhone(val) && !phoneUnchanged(val) ? PERSON_PHONE_RULE : '');

  // Reports-to options: every valid lead of THIS college; an invalid current link stays visible (never silently cleared).
  const leadOpts = people.filter((x) => LEAD_ROLES.includes(x.role) && isActive(x) && Number(x.id) !== Number(p.id)).map((x) => personOptV(x));
  const cur = editing && p.reports_to ? people.find((x) => Number(x.id) === Number(p.reports_to)) : null;
  const curValid = cur && leadOpts.some((x) => Number(x.value) === Number(cur.id));
  if (editing && p.reports_to && !curValid) {
    const why = !cur ? 'not in this college' : !isActive(cur) ? 'inactive' : 'not a lead';
    leadOpts.push({ value: String(p.reports_to), label: `${cur?.full_name || p.reports_to_name || `#${p.reports_to}`} (${why} — choose a valid lead)`, role: '__current' });
  }
  const current = editing ? personBranchIds({ ...p, branches: p.branches }, branches) : (opts.branch_ids || []).map(Number);
  const brs = branches.slice().sort((a, b) => (b.is_relevant ? 1 : 0) - (a.is_relevant ? 1 : 0) || String(a.code || a.name).localeCompare(b.code || b.name));
  const fields = [
    { name: 'full_name', label: 'Full name', type: 'text', required: true, value: p.full_name || '', placeholder: 'e.g. Sai Kiran Reddy', maxlength: 200 },
    { name: 'role', label: 'Role', type: 'select', options: ROLE_OPTS, value: role0, required: true },
    { name: 'reports_to', label: 'Reports to', type: 'select', options: [NONE('— No lead yet (unassigned) —'), ...leadOpts], value: editing ? (p.reports_to ? String(p.reports_to) : '') : (opts.reports_to ? String(opts.reports_to) : ''), help: BOSS_HELP[role0] || '' },
    { name: 'phone', label: 'Mobile number', type: 'tel', value: p.phone ? formatPhone(p.phone) : '', placeholder: '98765 43210', help: '10-digit Indian mobile. Saved as +91 XXXXX XXXXX.' },
    { name: 'email', label: 'Email', type: 'text', autocomplete: 'email', value: p.email || '', placeholder: 'name@college.edu.in', help: 'Saved in lower case.', maxlength: 200 },
    supportsDesignation ? { name: 'designation', label: 'Designation / responsibility', type: 'text', value: p.designation || '', placeholder: 'Optional', help: DESIGNATION_HELP, maxlength: 120 } : null,
    { name: 'branch_ids', label: 'Branches covered', type: 'multiselect', options: branchOpts(brs), value: current.map(String), help: BRANCH_HELP[role0] || BRANCH_HELP.ambassador },
    { name: 'status', label: 'Status', type: 'select', options: STATUS_OPTS.filter((s) => editing || s.value !== 'inactive'), value: p.status || 'active', required: true, help: editing ? 'To deactivate, use “Deactivate” on their page — it also handles the people who report to them.' : 'Use Onboarding until they have been briefed.' },
    { name: 'joined_on', label: 'Joined on', type: 'date', value: p.joined_on || (editing ? '' : todayStr()), max: todayStr() },
    editing ? null : { name: 'target', label: 'Programme target (optional)', type: 'number', min: 0, step: 1, value: '', placeholder: 'e.g. 5', help: 'Confirmed enrollments expected by the programme deadline. Monthly or weekly targets: use “Set target” on their page.' },
    { name: 'notes', label: 'Notes', type: 'textarea', value: p.notes || '' },
  ].filter(Boolean);
  // an inactive person's status select must still show "Inactive"
  if (editing && p.status === 'inactive') fields.find((f) => f.name === 'status').options = STATUS_OPTS;

  const leadNote = h('p', { class: 'vf-note vf-note--warn', role: 'status', hidden: true });
  const linkNote = editing && p.reports_to && !curValid
    ? h('p', { class: 'vf-note vf-note--warn', role: 'status' }, `${p.full_name} currently reports to someone who is ${!cur ? 'not in this college' : !isActive(cur) ? 'inactive' : 'not a lead'}. Choose a valid lead below, or leave it to keep the record as it is.`) : null;
  const noLeadNote = h('p', { class: 'vf-note', role: 'status', hidden: true });
  const dupBox = h('div', { class: 'v-person-dupbox', 'aria-live': 'polite' });
  let mm = null;
  const intro = h('div', { class: 'v-person-dlg' },
    h('div', { class: 'v-person-dlg__college' }, ui.icon('college'), h('span', null, 'College: ', h('strong', null, d.college?.name || cname)),
      editing ? h('button', { type: 'button', class: 'vx-linkbtn td-linkbtn v-person-dlg__move', onClick: () => { mm?.close(); movePerson(ctx, p); } }, 'Move to another college…') : null),
    linkNote, leadNote, noLeadNote, dupBox);

  let dupSeq = 0;
  let formRef = null;
  let allowSameName = false;
  const checkDupes = async (formEl) => {
    const my = ++dupSeq;
    const phone = field(formEl, 'phone')?.value || '';
    const email = field(formEl, 'email')?.value || '';
    const list = (normPhone(phone) || (normEmail(email) && EMAIL_RE.test(normEmail(email)))) ? await findDuplicatePeople(ctx, { phone, email }, p.id) : [];
    if (my !== dupSeq) return;
    dupBox.replaceChildren(dupNotice(ctx, list, { onOpen: () => mm?.close() }) || '');
  };

  const roleOf = (formEl, byName) => { const el = field(formEl, 'role'); return el && el.value !== '' ? byName.role.options[Number(el.value)]?.value : null; };
  const wire = (formEl, byName) => {
    formRef = formEl;
    formEl.classList.add('v-person-form');
    const apply = (role) => {
      filterSelect(formEl, byName.reports_to, (o) => (ALLOWED_BOSS[role] || []).includes(o.role) || o.role === '__current');
      showField(formEl, 'reports_to', role && role !== 'college_lead');
      setHelp(formEl, 'reports_to', BOSS_HELP[role] || '');
      const bh = formEl.querySelector('.td-multi')?.closest('.td-field')?.querySelector('.td-field__help');
      if (bh) bh.textContent = BRANCH_HELP[role] || BRANCH_HELP.ambassador;
      const rs = field(formEl, 'reports_to');
      const valid = validLeads(people, role, p.id);
      // pre-pick the only possible lead so new people are not left unassigned by accident
      if (!editing && rs && rs.value === '' && role && role !== 'college_lead' && valid.length === 1) {
        const idx = byName.reports_to.options.findIndex((x) => Number(x.value) === Number(valid[0].id));
        if (idx >= 0) rs.value = String(idx);
      }
      leadNote.hidden = !(role === 'college_lead' && currentLead && !(editing && p.role === 'college_lead'));
      leadNote.textContent = currentLead ? `${currentLead.full_name} is the college lead of ${cname}. Saving will ask whether they become an ambassador lead or inactive — a college has one active college lead.` : '';
      noLeadNote.hidden = !(role && role !== 'college_lead' && !valid.length);
      noLeadNote.textContent = role === 'ambassador_lead'
        ? `${cname} has no active college lead yet. An ambassador lead reports to the college lead — appoint one first, or save now and assign later (they will show as unassigned).`
        : `${cname} has no active lead yet. The ambassador will show as unassigned until you appoint a college lead and assign them.`;
    };
    apply(roleOf(formEl, byName));
    onChange(formEl, byName.role, apply);
    liveValidate(formEl, {
      full_name: (v) => (v ? '' : 'Name is required.'),
      phone: (v) => phoneErr(v),
      email: (v) => (v && !EMAIL_RE.test(v) ? 'Enter a valid email address, e.g. name@college.edu.in.' : ''),
      target: (v) => (v && Number.isNaN(wholeOrNull(v)) ? 'Enter a whole number (0 or more).' : ''),
    });
    // normalisation preview + live duplicate warning
    const ph = field(formEl, 'phone');
    const showNorm = () => { const n = normPhone(ph.value); setHelp(formEl, 'phone', ph.value.trim() ? (n ? `Will be saved as ${formatPhone(n)}.` : phoneUnchanged(ph.value) ? 'Stored number (not a mobile) — kept as it is. A new number must be a 10-digit mobile.' : '10-digit Indian mobile, e.g. 98765 43210.') : '10-digit Indian mobile. Saved as +91 XXXXX XXXXX.'); };
    const later = (() => { let t; return () => { clearTimeout(t); t = setTimeout(() => checkDupes(formEl), 450); }; })();
    ph?.addEventListener('input', () => { showNorm(); later(); });
    ph?.addEventListener('blur', () => checkDupes(formEl));
    const em = field(formEl, 'email');
    em?.addEventListener('input', later);
    em?.addEventListener('blur', () => checkDupes(formEl));
    // put the duplicate warning right under the contact fields
    const after = (em || ph)?.closest('.td-field');
    if (after) { const holder = h('div', { class: 'td-field td-field--full v-person-dupwrap' }, dupBox); after.after(holder); }
    if (editing && (p.phone || p.email)) checkDupes(formEl);
  };

  const errorsOf = (v) => {
    const errs = {};
    if (!str(v.full_name)) errs.full_name = 'Name is required.';
    if (phoneErr(v.phone)) errs.phone = phoneErr(v.phone);
    if (str(v.email) && !EMAIL_RE.test(String(v.email).trim())) errs.email = 'Enter a valid email address, e.g. name@college.edu.in.';
    if (Number.isNaN(wholeOrNull(v.target))) errs.target = 'Enter a whole number (0 or more).';
    if (v.joined_on && !/^\d{4}-\d{2}-\d{2}$/.test(v.joined_on)) errs.joined_on = 'Use a date like 2026-11-07.';
    else if (v.joined_on && v.joined_on > todayStr()) errs.joined_on = 'Joining date cannot be in the future.';
    return errs;
  };
  /** 409 from the server: show who already has these details, then let ui.form show the field message. */
  const on409 = async (e, v) => {
    const id = errExisting(e);
    if (e.code === 'possible_duplicate_name') {
      dupBox.replaceChildren(h('div', { class: 'vf-note vf-note--warn v-person-dup', role: 'alert' },
        h('strong', null, `${e.data?.existing_name || 'Someone'} with the same name is already at ${cname}.`), ' ',
        id ? h('a', { href: `#/person/${id}`, class: 'v-person-dup__open', onClick: () => mm?.close() }, 'Open existing') : null,
        h('div', { class: 'vx-row' }, h('button', { type: 'button', class: 'td-btn td-btn--secondary td-btn--sm', onClick: () => { allowSameName = true; formRef?.requestSubmit(); } }, 'It is a different person — save anyway'))));
      return;
    }
    if (e.code === 'lead_exists') {
      dupBox.replaceChildren(h('p', { class: 'vf-note vf-note--warn', role: 'alert' }, `${e.data?.existing_name || 'Someone'} is already the college lead here. Choose another role, or use “Replace lead” on their page.`));
      return;
    }
    let list = [];
    if (id) { try { const x = await ctx.api.get(`/people/${id}`); list = [{ ...(x.person || x), _field: e.fields?.email && !e.fields?.phone ? 'email' : 'phone' }]; } catch { /* ignore */ } }
    if (!list.length) list = await findDuplicatePeople(ctx, v, p.id);
    if (list.length) dupBox.replaceChildren(dupNotice(ctx, list, { onOpen: () => mm?.close() }));
  };

  mm = await openForm(ctx, {
    title: editing ? `Edit ${p.full_name}` : `Add a person — ${cname}`,
    intro, fields, extra: editing && !(pd?.enrollments || []).length && !(pd?.activities || []).length
      ? h('div', { class: 'vf-danger v-person-dlg__danger' }, h('span', { class: 'vx-small vx-muted' }, 'Added by mistake?'),
        h('button', { type: 'button', class: 'td-btn td-btn--ghost td-btn--sm', onClick: () => deletePerson(ctx, p, () => mm?.close()) }, 'Delete this record'))
      : null,
    submitLabel: editing ? 'Save changes' : 'Add person',
    success: (res, v) => {
      if (res && res._noop) return 'No changes to save';
      const se = sideEffectText(res?._res || res);
      return `${str(v.full_name)} ${editing ? 'updated' : `added as ${(ROLE_LABEL[res?._role || v.role] || v.role).toLowerCase()} at ${cname}`}${se ? ` · ${se}` : ''}`;
    },
    after: wire,
    onSubmit: async (v) => {
      const errs = errorsOf(v);
      if (Object.keys(errs).length) throw validationError(errs);
      const role = v.role;
      const wantsLead = role === 'college_lead' && currentLead && !(editing && p.role === 'college_lead');
      let fate = null;
      if (wantsLead) { fate = await askOldLeadFate(ctx, currentLead, str(v.full_name)); if (!fate) return { _keepOpen: true }; }
      const next = {
        role, full_name: str(v.full_name), phone: str(v.phone) ? (normPhone(v.phone) || (phoneUnchanged(v.phone) ? (normPhone(storedPhone) || storedPhone) : null)) : null, email: normEmail(v.email),
        reports_to: role === 'college_lead' ? null : num(v.reports_to), status: v.status || 'active', joined_on: str(v.joined_on), notes: str(v.notes),
      };
      if (supportsDesignation) next.designation = str(v.designation);
      const sameName = allowSameName ? { allow_same_name: true } : {};
      try {
        if (!editing) {
          const body = { college_id: collegeId, ...next, branch_ids: arr(v.branch_ids), ...sameName };
          // replacing a lead: add as ambassador lead under the current lead, then swap roles in one server call
          if (wantsLead) { body.role = 'ambassador_lead'; body.reports_to = Number(currentLead.id); }
          const saved = await ctx.api.post('/people', body);
          const sp = saved?.person || saved;
          const pid = sp?.id;
          if (wantsLead && pid != null) {
            try { await replaceLeadRequest(ctx, currentLead.id, pid, fate); } catch (e) { ui.toast(`Added ${next.full_name} as ambassador lead, but replacing the college lead failed: ${e.message}`, 'warn'); return { ...sp, _role: 'ambassador_lead' }; }
          }
          const t = wholeOrNull(v.target);
          if (pid != null && t != null) {
            try { await saveTargetRow(ctx, { scope_type: 'person', scope_id: pid, period: 'programme', target: t }); } catch (e) { ui.toast(`Person added, but the target could not be saved: ${e.message}`, 'warn'); }
          }
          return { ...sp, _res: saved };
        }
        // edit: send only what changed (never clears an untouched invalid link)
        const before = { ...p, phone: p.phone ? normPhone(p.phone) || p.phone : null, email: p.email ? String(p.email).toLowerCase() : null };
        const body = {};
        for (const [k, val] of Object.entries(next)) if ((val ?? null) !== (before[k] ?? null)) body[k] = val;
        const nb = arr(v.branch_ids).sort((a, b) => a - b);
        if (nb.join(',') !== current.slice().sort((a, b) => a - b).join(',')) body.branch_ids = nb;
        if (wantsLead) { delete body.role; delete body.reports_to; }
        if (!Object.keys(body).length && !wantsLead) return { _noop: true };
        let saved = p;
        if (Object.keys(body).length) saved = await ctx.api.patch(`/people/${p.id}`, { ...body, ...(body.full_name ? sameName : {}) });
        if (wantsLead) await replaceLeadRequest(ctx, currentLead.id, p.id, fate);
        return { ...(saved?.person || saved), _res: saved };
      } catch (e) {
        if (e && e.status === 409) await on409(e, v);
        throw e;
      }
    },
  });
  return mm;
}

/** Back-compatible entry points (college, branch, plan and people views call these). */
export async function addPerson(...args) {
  const [ctx, [opts = {}]] = await split(args);
  return personDialog(ctx, { ...opts, id: undefined });
}
export async function editPerson(...args) {
  const [ctx, [p0]] = await split(args);
  const id = typeof p0 === 'object' && p0 ? p0.id : p0;
  return personDialog(ctx, { id });
}

/** Move a person to another college (R4): their lead and branch links are cleared; people reporting to them become unassigned. */
export async function movePerson(...args) {
  const [ctx, [p0]] = await split(args);
  if (!(await ensureUser(ctx))) return null;
  const { h, ui } = ctx;
  const id = typeof p0 === 'object' && p0 ? p0.id : p0;
  let pd;
  try { pd = await ctx.api.get(`/people/${id}`); } catch (e) { ui.toast(e.message, 'bad'); return null; }
  const p = pd.person || pd;
  const target = await pickCollege(ctx, `Move ${p.full_name} to another college`);
  if (!target) return null;
  if (target === p.college_id) { ui.toast(`${p.full_name} is already at this college`, 'info'); return null; }
  let nd = null;
  try { nd = await collegeDetail(ctx, target); } catch (e) { ui.toast(e.message, 'bad'); return null; }
  const oldName = pd.college?.short_name || pd.college?.name || p.college_short_name || p.college_id;
  const newName = nd.college?.short_name || nd.college?.name || target;
  const reports = (pd.reports || []).filter(isActive);
  const brs = pd.branches || p.branches || [];
  const newLead = (nd.people || []).find((x) => x.role === 'college_lead' && isActive(x));
  const items = [
    p.reports_to ? `Their lead (${p.reports_to_name || `#${p.reports_to}`}) is cleared — choose a lead at ${newName} next.` : null,
    brs.length ? `Branch links at ${oldName} are removed (${brs.map((b) => b.code || b.name).join(', ')}).` : null,
    reports.length ? `${reports.length} ${reports.length === 1 ? 'person reports' : 'people report'} to them and will become unassigned: ${reports.map((r) => r.full_name).join(', ')}.` : null,
    p.role === 'college_lead' && newLead ? `${newName} already has a college lead (${newLead.full_name}); the move will be refused. Change their role first, or use “Replace lead” there.` : null,
    'Enrollments already credited stay on record.',
  ].filter(Boolean);
  const ok = await new Promise((resolve) => {
    let answered = false;
    const m = ui.modal({
      title: `Move ${p.full_name} to ${newName}?`,
      body: h('div', { class: 'v-person-dlg' }, h('p', null, `From ${oldName} to ${newName}. What changes:`), h('ul', { class: 'v-person-list' }, items.map((t) => h('li', null, t)))),
      actions: [{ label: 'Cancel', tone: 'ghost', onClick: () => { answered = true; resolve(false); } }, { label: 'Move', tone: 'primary', onClick: () => { answered = true; resolve(true); } }],
    });
    const obs = new MutationObserver(() => { if (!document.contains(m.el)) { obs.disconnect(); if (!answered) resolve(false); } });
    obs.observe(document.body, { childList: true, subtree: true });
  });
  if (!ok) return null;
  let res;
  try {
    try { res = await ctx.api.post(`/people/${p.id}/move`, { college_id: target }); } catch (e) {
      if (!missingEndpoint(e)) throw e;
      for (const r of reports) await ctx.api.patch(`/people/${r.id}`, { reports_to: null });
      res = await ctx.api.patch(`/people/${p.id}`, { college_id: target, reports_to: null, branch_ids: [] });
    }
  } catch (e) { ui.toast(e.message, 'bad'); return null; }
  const se = sideEffectText(res);
  ui.toast(`${p.full_name} moved to ${newName}${se ? ` · ${se}` : ''}`, 'good');
  ctx.refresh?.();
  // assign a lead at the new college straight away (not for college leads)
  if (p.role !== 'college_lead') setTimeout(() => personDialog(ctx, { id: p.id }), 250);
  return res;
}

/** Deactivate (R5): lists the people who report to this person and optionally reassigns them first. */
export async function deactivatePerson(...args) {
  const [ctx, [p0]] = await split(args);
  if (!(await ensureUser(ctx))) return null;
  const { h, ui } = ctx;
  const id = typeof p0 === 'object' && p0 ? p0.id : p0;
  let pd; let d;
  try { pd = await ctx.api.get(`/people/${id}`); d = await collegeDetail(ctx, (pd.person || pd).college_id); } catch (e) { ui.toast(e.message, 'bad'); return null; }
  const p = pd.person || pd;
  const reports = (pd.reports || []).filter(isActive);
  const needsCollegeLead = reports.some((r) => r.role === 'ambassador_lead');
  const cands = (d?.people || []).filter((x) => isActive(x) && Number(x.id) !== Number(p.id) && (needsCollegeLead ? x.role === 'college_lead' : LEAD_ROLES.includes(x.role))
    && !reports.some((r) => Number(r.id) === Number(x.id) && x.role !== 'ambassador_lead'));
  const sel = h('select', { class: 'td-input td-select', 'aria-label': 'Reassign their team to' },
    h('option', { value: '' }, '— Leave them unassigned —'), cands.map((c) => h('option', { value: String(c.id) }, `${c.full_name} (${ROLE_LABEL[c.role]})`)));
  const body = h('div', { class: 'v-person-dlg' },
    h('p', null, `${p.full_name} will be set inactive. Their history, branches and credited enrollments are kept, and you can reactivate them any time.`),
    reports.length ? [
      h('p', null, h('strong', null, `${reports.length} ${reports.length === 1 ? 'person reports' : 'people report'} to ${p.full_name}:`)),
      h('ul', { class: 'v-person-list' }, reports.map((r) => h('li', null, `${r.full_name} — ${ROLE_LABEL[r.role] || r.role}`))),
      h('label', { class: 'v-person-field' }, h('span', null, 'Move them to'), sel),
      h('p', { class: 'vx-small vx-muted' }, cands.length ? 'Leave unassigned to sort it out later — they will show under “Unassigned” in Team.' : 'No other active lead at this college, so they will become unassigned.'),
    ] : h('p', { class: 'vx-muted' }, 'Nobody reports to them.'));
  return new Promise((resolve) => {
    let done = false;
    const m = ui.modal({
      title: `Deactivate ${p.full_name}?`, body,
      actions: [
        { label: 'Cancel', tone: 'ghost', onClick: () => { done = true; resolve(null); } },
        { label: 'Deactivate', tone: 'danger', onClick: async () => {
          const to = sel.value ? Number(sel.value) : null;
          try {
            for (const r of reports) {
              if (to && Number(r.id) === to) continue;
              await ctx.api.patch(`/people/${r.id}`, { reports_to: to });
            }
            const res = await ctx.api.patch(`/people/${p.id}`, { status: 'inactive' });
            const moved = to ? reports.filter((r) => Number(r.id) !== to).length : 0;
            ui.toast(`${p.full_name} set inactive — history kept${moved ? ` · ${moved} moved to ${cands.find((c) => Number(c.id) === to)?.full_name}` : reports.length ? ` · ${reports.length} now unassigned` : ''}`, 'good');
            done = true; resolve(res); ctx.refresh?.();
            return true;
          } catch (e) { ui.toast(e.message, 'bad'); return false; }
        } },
      ],
    });
    const obs = new MutationObserver(() => { if (!document.contains(m.el)) { obs.disconnect(); if (!done) resolve(null); } });
    obs.observe(document.body, { childList: true, subtree: true });
  });
}

/** Reactivate; a second active college lead is refused by the server (409) and explained here. */
export async function reactivatePerson(...args) {
  const [ctx, [p0]] = await split(args);
  if (!(await ensureUser(ctx))) return null;
  const p = typeof p0 === 'object' && p0 ? p0 : { id: p0, full_name: `#${p0}` };
  try {
    const r = await ctx.api.patch(`/people/${p.id}`, { status: 'active' });
    ctx.ui.toast(`${p.full_name} reactivated${p.role !== 'college_lead' && !p.reports_to ? ' — assign them a lead' : ''}`, 'good');
    ctx.refresh?.();
    return r;
  } catch (e) {
    ctx.ui.toast(e.status === 409 && p.role === 'college_lead' ? `${e.message} Use “Replace lead” on the current college lead instead.` : e.message, 'bad');
    return null;
  }
}

/** Replace a college lead from their page: pick an existing person of the college (or add a new one) and decide the old lead's fate. */
export async function replaceLead(...args) {
  const [ctx, [p0]] = await split(args);
  if (!(await ensureUser(ctx))) return null;
  const { h, ui } = ctx;
  const id = typeof p0 === 'object' && p0 ? p0.id : p0;
  let pd; let d;
  try { pd = await ctx.api.get(`/people/${id}`); d = await collegeDetail(ctx, (pd.person || pd).college_id); } catch (e) { ui.toast(e.message, 'bad'); return null; }
  const old = pd.person || pd;
  const cands = (d.people || []).filter((x) => isActive(x) && Number(x.id) !== Number(old.id));
  const sel = h('select', { class: 'td-input td-select', 'aria-label': 'New college lead' },
    h('option', { value: '' }, cands.length ? 'Choose a person…' : 'Nobody else at this college yet'),
    cands.map((c) => h('option', { value: String(c.id) }, `${c.full_name} (${ROLE_LABEL[c.role]})`)));
  const fate = { v: 'ambassador_lead' };
  const radio = (value, title) => h('label', { class: 'v-person-choice' }, h('input', { type: 'radio', name: 'td-fate', value, checked: value === fate.v ? true : null, onChange: () => { fate.v = value; } }), h('span', null, title));
  const err = h('p', { class: 'td-field__error', role: 'alert' });
  const body = h('div', { class: 'v-person-dlg' },
    h('p', null, `Choose who becomes the college lead of ${d.college?.short_name || d.college?.name} instead of ${old.full_name}.`),
    h('label', { class: 'v-person-field' }, h('span', null, 'New college lead'), sel),
    h('button', { type: 'button', class: 'vx-linkbtn td-linkbtn', onClick: () => { m.close(); personDialog(ctx, { college_id: old.college_id, role: 'college_lead' }); } }, 'Or add a new person as college lead…'),
    h('fieldset', { class: 'v-person-choices' }, h('legend', null, `${old.full_name} then`),
      radio('ambassador_lead', 'stays as an ambassador lead under the new lead'), radio('inactive', 'is set inactive (history kept)'),
      h('p', { class: 'vx-small vx-muted' }, 'Either way, the people who reported to them move to the new college lead.')),
    err);
  const m = ui.modal({
    title: `Replace ${old.full_name} as college lead`, body,
    actions: [
      { label: 'Cancel', tone: 'ghost' },
      { label: 'Replace lead', tone: 'primary', onClick: async () => {
        if (!sel.value) { err.textContent = 'Choose the new college lead.'; return false; }
        try {
          const r = await replaceLeadRequest(ctx, old.id, Number(sel.value), fate.v);
          ui.toast(`${cands.find((c) => String(c.id) === sel.value)?.full_name} is now the college lead${sideEffectText(r) ? ` · ${sideEffectText(r)}` : ''}`, 'good');
          ctx.refresh?.();
          return true;
        } catch (e) { err.textContent = e.message; return false; }
      } },
    ],
  });
  return m;
}

/** Bulk "assign to lead": PATCH reports_to for each id; returns {ok:[ids], failed:[{id, message}]}. */
export async function assignToLead(ctx, ids, leadId) {
  try {
    const r = await ctx.api.post('/people/bulk-assign', { person_ids: ids.map(Number), reports_to: leadId == null ? null : Number(leadId) });
    return { ok: [...(r.updated || []), ...(r.unchanged || [])], failed: [] };
  } catch (e) {
    if (!missingEndpoint(e)) return { ok: [], failed: ids.map((id) => ({ id, message: e.message })), error: e };
  }
  const ok = []; const failed = [];
  for (const id of ids) {
    try { await ctx.api.patch(`/people/${id}`, { reports_to: leadId == null ? null : Number(leadId) }); ok.push(id); } catch (e) { failed.push({ id, message: e.message }); }
  }
  return { ok, failed };
}

/** Delete a person added by mistake (server refuses with 409 when they have history; then offer Deactivate). */
export async function deletePerson(ctx, p, close) {
  const ok = await ctx.ui.confirm({
    title: `Delete ${p.full_name}?`,
    text: 'Only for a record added by mistake. This permanently removes the person and their branch links; anyone reporting to them becomes unassigned. This cannot be undone.',
    confirmLabel: 'Delete permanently',
  });
  if (!ok) return;
  try {
    await ctx.api.del(`/people/${p.id}`);
    ctx.ui.toast(`${p.full_name} deleted`, 'good');
    close?.();
    if (location.hash.startsWith(`#/person/${p.id}`)) ctx.navigate('#/people'); else ctx.refresh?.();
  } catch (e) {
    if (e.status === 409) {
      const again = await ctx.ui.confirm({ title: 'This person cannot be deleted', text: `${e.message} Deactivate ${p.full_name} instead? Their history is kept.`, confirmLabel: 'Deactivate…', tone: 'primary' });
      if (again) { close?.(); await deactivatePerson(ctx, p); }
    } else ctx.ui.toast(e.message, 'bad');
  }
}

/* ------------------------------------------------------------------ enrollment / activity / follow-up */

/** D10: crediting an enrollment to someone who is no longer active needs a deliberate yes. true = go ahead. */
async function confirmInactiveCredit(ctx, person) {
  if (!person || person.status !== 'inactive') return true;
  return ctx.ui.confirm({
    title: `${person.full_name} is inactive`,
    text: `${person.full_name} has left the team. Credit this enrollment to them anyway? It will count toward their (and their lead's) figures. Choose "No one credited" or an active person instead if they did not bring this student.`,
    confirmLabel: 'Credit anyway', cancelLabel: 'Go back', danger: false,
  });
}

export async function recordEnrollment(...args) {
  const [ctx, [opts = {}]] = await split(args);
  let collegeId = opts.college_id;
  if (!collegeId) { collegeId = await pickCollege(ctx, 'Record an enrollment'); if (!collegeId) return null; }
  let d; let m;
  try { [d, m] = await Promise.all([collegeDetail(ctx, collegeId), meta(ctx)]); } catch (e) { ctx.ui.toast(e.message, 'bad'); return null; }
  const branches = (d.branches || []).slice().sort((a, b) => (b.is_relevant ? 1 : 0) - (a.is_relevant ? 1 : 0) || String(a.code || a.name).localeCompare(b.code || b.name));
  const people = (d.people || []).filter((p) => p.status !== 'inactive' || (opts.person_id != null && Number(p.id) === Number(opts.person_id)));
  const courses = (m.courses || []).filter((c) => c.active !== 0);
  for (const p of people) p._b = personBranchIds(p, branches);
  const roleRank = { ambassador: 0, ambassador_lead: 1, college_lead: 2 };
  const creditOpts = [NONE('— No one credited —'), ...people.slice().sort((a, b) => (roleRank[a.role] - roleRank[b.role]) || a.full_name.localeCompare(b.full_name)).map(personOpt)];
  const creditFilter = (branchId) => (o) => !branchId || o.role === 'college_lead' || o.branches.includes(Number(branchId));
  const priceOf = (cid) => courses.find((c) => String(c.id) === String(cid))?.price_inr ?? '';
  const firstCourse = opts.course_id || (courses.length === 1 ? courses[0].id : '');
  const credited = opts.person_id ? people.find((p) => Number(p.id) === Number(opts.person_id)) : null;
  const branchId = opts.branch_id || (credited && credited._b.length === 1 ? credited._b[0] : '');
  const { h, fmt } = ctx;
  const fields = [
    { name: 'stage', label: 'Stage', type: 'select', required: true, options: STAGE_OPTS, value: opts.stage || 'confirmed', help: 'Only a confirmed enrollment counts toward targets. Record a lead early and move the same record forward later.' },
    { name: 'enrolled_on', label: 'Date', type: 'date', value: todayStr(), required: true, max: todayStr(), help: 'The day this stage was reached (for a confirmed enrollment: the day the student confirmed).' },
    { name: 'course_id', label: 'Course', type: 'select', required: courses.length > 0,
      options: [NONE(courses.length ? 'Choose a course…' : 'No courses yet'), ...courses.map((c) => ({ value: String(c.id), label: `${c.name}${c.price_inr != null ? ' — ' + fmt.inr(c.price_inr) : ''}` }))],
      value: firstCourse ? String(firstCourse) : '', help: courses.length ? null : 'Add courses and prices in Settings.' },
    { name: 'amount_inr', label: 'Amount paid (₹)', type: 'number', min: 0, step: 1, value: firstCourse ? priceOf(firstCourse) : '', help: 'Filled in from the course price. Change it if a discount applied.' },
    { name: 'branch_id', label: "Student's branch", type: 'select', options: [NONE('— Branch not known —'), ...branchOpts(branches)], value: branchId ? String(branchId) : '' },
    { name: 'person_id', label: 'Credit to', type: 'select', options: creditOpts, value: opts.person_id ? String(opts.person_id) : '', help: 'Only people covering the chosen branch are listed (college leads always are).' },
    { name: 'student_name', label: 'Student name', type: 'text', placeholder: 'Optional' },
    { name: 'student_contact', label: 'Student phone or email', type: 'text', placeholder: 'Optional' },
    { name: 'notes', label: 'Notes', type: 'textarea' },
  ];
  const amountRule = (v) => (v !== '' && v !== null && v !== undefined && Number.isNaN(wholeOrNull(v)) ? 'Enter the amount in whole rupees (0 or more).' : '');
  const dateRule = (v) => (!v ? 'Date is required.' : v > todayStr() ? 'Date cannot be in the future.' : '');
  return openForm(ctx, {
    title: `Record enrollment — ${d.college?.short_name || d.college?.name || collegeId}`,
    intro: h('p', { class: 'vf-note' }, ctx.ui.icon('info'), ' Store only what is needed. Student name and contact are optional — leave them blank unless the team needs them for follow-up.'),
    fields, submitLabel: 'Save record',
    success: (res, v) => {
      const who = people.find((p) => String(p.id) === String(v.person_id));
      return `${v.stage && v.stage !== 'confirmed' ? STAGE_LABEL[v.stage] + ' recorded' : 'Enrollment recorded'}${who ? ` and credited to ${who.full_name}` : ''}`;
    },
    after: (formEl, f) => {
      filterSelect(formEl, f.person_id, creditFilter(branchId));
      onChange(formEl, f.branch_id, (b) => filterSelect(formEl, f.person_id, creditFilter(b)));
      onChange(formEl, f.course_id, (c) => { const a = field(formEl, 'amount_inr'); if (a) a.value = priceOf(c); });
      liveValidate(formEl, { amount_inr: amountRule, enrolled_on: dateRule });
    },
    onSubmit: async (v) => {
      const errs = {};
      const dm = dateRule(v.enrolled_on);
      if (dm) errs.enrolled_on = dm;
      if (Number.isNaN(wholeOrNull(v.amount_inr))) errs.amount_inr = 'Enter the amount in whole rupees (0 or more).';
      if (Object.keys(errs).length) throw validationError(errs);
      if (!(await confirmInactiveCredit(ctx, people.find((p) => String(p.id) === String(v.person_id))))) return { _keepOpen: true };
      return ctx.api.post('/enrollments', {
        college_id: collegeId, branch_id: num(v.branch_id), course_id: num(v.course_id), person_id: num(v.person_id), stage: v.stage || 'confirmed',
        enrolled_on: v.enrolled_on, amount_inr: wholeOrNull(v.amount_inr), student_name: str(v.student_name),
        student_contact: str(v.student_contact), notes: str(v.notes),
      });
    },
  });
}

export async function logActivity(...args) {
  const [ctx, [opts = {}]] = await split(args);
  let collegeId = opts.college_id;
  if (!collegeId) { collegeId = await pickCollege(ctx, 'Log an activity'); if (!collegeId) return null; }
  let d;
  try { d = await collegeDetail(ctx, collegeId); } catch (e) { ctx.ui.toast(e.message, 'bad'); return null; }
  const branches = d.branches || [];
  const people = (d.people || []).filter((p) => p.status !== 'inactive');
  const fields = [
    { name: 'type', label: 'What happened?', type: 'select', options: ACT_OPTS, value: opts.type || 'visit', required: true },
    { name: 'on_date', label: 'Date', type: 'date', value: todayStr(), required: true, max: todayStr() },
    { name: 'branch_id', label: 'Branch', type: 'select', options: [NONE('— Whole college —'), ...branchOpts(branches)], value: opts.branch_id ? String(opts.branch_id) : '' },
    { name: 'person_id', label: 'Done by', type: 'select', options: [NONE('— Tech Drona staff / not listed —'), ...people.map(personOpt)], value: opts.person_id ? String(opts.person_id) : '' },
    { name: 'students_reached', label: 'Students reached', type: 'number', min: 0, step: 1, value: '', placeholder: '0', help: 'How many students heard about the courses. Leave blank if none.' },
    { name: 'notes', label: 'Notes', type: 'textarea', placeholder: 'What was discussed? What happens next?' },
  ];
  const reachRule = (v) => (v !== '' && v !== null && v !== undefined && Number.isNaN(wholeOrNull(v)) ? 'Enter a whole number (0 or more).' : '');
  const dateRule = (v) => (!v ? 'Date is required.' : v > todayStr() ? 'Date cannot be in the future.' : '');
  return openForm(ctx, {
    title: `Log activity — ${d.college?.short_name || d.college?.name || collegeId}`, fields, submitLabel: 'Log activity',
    success: (res, v) => `Activity logged${wholeOrNull(v.students_reached) ? ` — ${ctx.fmt.num(wholeOrNull(v.students_reached))} students reached` : ''}`,
    after: (formEl) => liveValidate(formEl, { students_reached: reachRule, on_date: dateRule }),
    onSubmit: async (v) => {
      const errs = {};
      if (reachRule(v.students_reached)) errs.students_reached = reachRule(v.students_reached);
      if (dateRule(v.on_date)) errs.on_date = dateRule(v.on_date);
      if (Object.keys(errs).length) throw validationError(errs);
      return ctx.api.post('/activities', {
        college_id: collegeId, branch_id: num(v.branch_id), person_id: num(v.person_id), on_date: v.on_date,
        type: v.type, students_reached: wholeOrNull(v.students_reached) ?? 0, notes: str(v.notes),
      });
    },
  });
}

/**
 * Add a follow-up. Uses the same form as the Follow-ups page so the experience is identical everywhere.
 * opts: {scope_type, scope_id, college_id, label, title, issue}
 */
export async function addFollowup(...args) {
  const [ctx, [opts = {}]] = await split(args);
  if (!(await ensureUser(ctx))) return null;
  const scope_type = opts.scope_type || 'college';
  const sid = opts.scope_id ?? opts.college_id;
  const { openFollowupForm } = await import('./followups.js');
  return openFollowupForm(ctx, {
    preset: { scope_type, scope_id: sid == null ? '' : String(sid), college_id: opts.college_id, title: opts.title, issue: opts.issue },
    lockScope: sid != null && sid !== '',
    scopeLabel: opts.label,
    onSaved: () => ctx.refresh?.(),
  });
}

/* ------------------------------------------------------------------ targets */
// Period helpers + saveTargetRow (used when adding a person with a programme target). The dialog itself is TP's
// openTargetDialog (views/targets.js); targetDialog / setTarget delegate to it.

const isoDay = (d) => d.toISOString().slice(0, 10);
/** Monday of the ISO week containing YYYY-MM-DD. */
export function mondayOf(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  const dow = (d.getUTCDay() + 6) % 7;
  return isoDay(new Date(d.getTime() - dow * 86400000));
}
/** Period as the API spells it: 'programme' | 'month:YYYY-MM' | 'week:YYYY-MM-DD'. */
export function periodKey(kind, month, week) {
  if (kind === 'month') return `month:${month}`;
  if (kind === 'week') return `week:${week}`;
  return 'programme';
}
/** Parse a stored period ('programme', 'month:2026-11', '2026-11', 'week:2026-11-02', '2026-11-02'). */
export function parsePeriod(p) {
  const s = String(p || 'programme');
  if (s === 'programme' || s === 'program') return { kind: 'programme' };
  const v = s.includes(':') ? s.split(':')[1] : s;
  if (/^\d{4}-\d{2}$/.test(v)) return { kind: 'month', month: v };
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return { kind: 'week', week: v };
  return { kind: 'programme' };
}
export function periodLabel(p, fmt) {
  const x = parsePeriod(p);
  if (x.kind === 'month') { const d = new Date(`${x.month}-01T00:00:00Z`); return d.toLocaleDateString('en-IN', { month: 'long', year: 'numeric', timeZone: 'UTC' }); }
  if (x.kind === 'week') return `Week of ${fmt ? fmt.date(x.week) : x.week}`;
  return 'Programme';
}

/** PUT with the shared client when it has one; otherwise the same headers api.js sends. */
async function apiPut(ctx, path, body) {
  if (typeof ctx.api.put === 'function') return ctx.api.put(path, body);
  const headers = { Accept: 'application/json', 'Content-Type': 'application/json' };
  if (ctx.api.user) headers['X-User'] = encodeURIComponent(ctx.api.user);
  try { const pass = localStorage.getItem('td.passcode'); if (pass) headers['X-Passcode'] = pass; } catch { /* ignore */ }
  try { headers['Idempotency-Key'] = crypto.randomUUID(); } catch { /* ignore */ }
  let res;
  try { res = await fetch(apiUrl(path), { method: 'PUT', headers, body: JSON.stringify(body), credentials: 'same-origin' }); } catch {
    const e = new Error('Cannot reach the server. Is it running?'); e.status = 0; throw e;
  }
  const text = await res.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch { data = { error: text }; } }
  if (!res.ok) { const e = new Error((data && data.error) || res.statusText); e.status = res.status; e.fields = (data && data.fields) || {}; e.data = data; throw e; }
  return data;
}

/**
 * Save one target row. v4 servers: PUT /targets {scope_type, scope_id, period, min, target, max, ...}.
 * Older servers (no PUT): POST /targets for a programme target without min/max; anything else is refused with a clear message.
 */
export async function saveTargetRow(ctx, { scope_type, scope_id, period = 'programme', min = null, target, max = null, course_id = null, deadline = null, notes = null, confirm_programme }) {
  const body = { scope_type, scope_id: String(scope_id ?? ''), period, min, target, max, deadline, notes };
  if (course_id != null) body.course_id = course_id;
  if (confirm_programme) body.confirm_programme = true;
  try { return await apiPut(ctx, '/targets', body); } catch (e) {
    if (!missingEndpoint(e)) throw e;
  }
  if (period !== 'programme' || min != null || max != null) {
    throw validationError({ period: 'This server cannot store minimum/maximum or monthly/weekly targets yet. Save a programme target without min/max, or ask the admin to update the server.' });
  }
  return ctx.api.post('/targets', { scope_type, scope_id: String(scope_id ?? ''), course_id, target, deadline, notes });
}

/**
 * targetDialog(ctx, {scope_type, scope_id, label, period?})
 * There is ONE target dialog: openTargetDialog in views/targets.js (agent TP). This wrapper keeps the forms.* entry points.
 */
export async function targetDialog(...args) {
  const [ctx, [o = {}]] = await split(args);
  if (!(await ensureUser(ctx))) return null;
  let mod;
  try { mod = await import('./targets.js'); } catch (e) { ctx.ui.toast(`The target dialog could not load: ${e.message}`, 'bad'); return null; }
  return mod.openTargetDialog(ctx, {
    scope_type: o.scope_type, scope_id: o.scope_type === 'state' ? 'ap' : o.scope_id, label: o.label, period: o.period,
    onSaved: () => { o.onSaved?.(); ctx.refresh?.(); },
  });
}

/** Back-compatible: setTarget(scope_type, scope_id, opts) or setTarget(ctx, scope_type, scope_id, opts). */
export async function setTarget(...args) {
  const [ctx, rest] = await split(args);
  const [scope_type, scope_id, opts = {}] = rest;
  return targetDialog(ctx, { ...opts, scope_type, scope_id });
}

/* ------------------------------------------------------------------ college / branch */

export async function editCollege(...args) {
  const [ctx, [c0]] = await split(args);
  const id = typeof c0 === 'object' && c0 ? c0.id : c0;
  let c;
  try { c = (await ctx.api.get(`/colleges/${id}`)).college; } catch (e) { ctx.ui.toast(e.message, 'bad'); return null; }
  const fields = [
    { name: 'phone', label: 'Phone', type: 'tel', value: c.phone || '' },
    { name: 'email', label: 'Email', type: 'email', value: c.email || '' },
    { name: 'website', label: 'Website', type: 'text', value: c.website || '' },
    { name: 'contact_source', label: 'Contact source', type: 'text', value: c.contact_source || '', help: 'Where the contact details came from (URL or note).' },
    { name: 'address', label: 'Address', type: 'textarea', value: c.address || '' },
    { name: 'op_status', label: 'Operating status', type: 'select', options: OP_OPTS, value: c.op_status || 'pending' },
    { name: 'op_2025_26', label: 'Admitted students 2025-26?', type: 'select', options: YNU, value: c.op_2025_26 || 'unknown' },
    { name: 'op_2026_27', label: 'Admitted students 2026-27?', type: 'select', options: YNU, value: c.op_2026_27 || 'unknown' },
    { name: 'op_status_note', label: 'Evidence for status', type: 'textarea', value: c.op_status_note || '', help: 'Required when changing the status.' },
    { name: 'op_status_source', label: 'Evidence source (URL)', type: 'text', value: c.op_status_source || '' },
    { name: 'targeted', label: 'Targeted by Tech Drona (include in plans and targets)', type: 'checkbox', value: !!c.targeted },
    { name: 'notes', label: 'Notes', type: 'textarea', value: c.notes || '' },
  ];
  return openForm(ctx, {
    title: `Edit college — ${c.short_name || c.name}`, fields, submitLabel: 'Save college', success: 'College updated',
    onSubmit: async (v) => {
      const errs = {};
      if (v.phone && !/^[+\d][\d\s-]{6,}$/.test(String(v.phone).trim())) errs.phone = 'Enter a valid phone number.';
      if (v.email && !EMAIL_RE.test(String(v.email).trim())) errs.email = 'Enter a valid email address.';
      if (v.op_status !== (c.op_status || 'pending') && !str(v.op_status_note)) errs.op_status_note = 'Add the evidence for the new status.';
      if (Object.keys(errs).length) throw validationError(errs);
      return ctx.api.patch(`/colleges/${c.id}`, {
        phone: str(v.phone), email: str(v.email), website: str(v.website), contact_source: str(v.contact_source), address: str(v.address),
        op_status: v.op_status, op_2025_26: v.op_2025_26, op_2026_27: v.op_2026_27,
        op_status_note: str(v.op_status_note), op_status_source: str(v.op_status_source), targeted: v.targeted === true || Number(v.targeted) === 1 ? 1 : 0, notes: str(v.notes),
      });
    },
  });
}

function branchFields(b = {}) {
  return [
    { name: 'code', label: 'Branch code', type: 'text', value: b.code || '', required: true, help: 'e.g. CSE, CSM, ECE' },
    { name: 'name', label: 'Branch name', type: 'text', value: b.name || '', required: true },
    { name: 'category', label: 'Category', type: 'select', required: true, placeholder: 'Choose a category…', options: CATEGORY_OPTS, value: b.category || 'other', help: 'Decides whether it is a target branch by default.' },
    { name: 'is_relevant', label: 'Target branch?', type: 'select', options: [{ value: '', label: 'Default for category' }, ...YN], value: b.is_relevant == null ? '' : String(b.is_relevant ? 1 : 0) },
    { name: 'intake_per_year', label: 'Seats / year', type: 'number', value: b.intake_per_year ?? '' },
    { name: 'intake_basis', label: 'Seats basis', type: 'select', options: BASIS_OPTS, value: b.intake_basis || (b.intake_per_year != null ? 'estimated' : 'pending') },
    { name: 'intake_source', label: 'Seats source (URL or document)', type: 'text', value: b.intake_source || '' },
    { name: 'intake_year', label: 'Seats year', type: 'text', value: b.intake_year || '', help: 'Academic year of the seats figure, e.g. 2023-24' },
    { name: 'strength_total', label: 'Total strength, all years (if known)', type: 'number', value: b.strength_basis === 'verified' ? (b.strength_total ?? '') : '', help: 'Leave blank to estimate as intake × 4.' },
    { name: 'final_year', label: 'Students completing 4-1 (if known)', type: 'number', value: b.final_year_basis === 'verified' ? (b.final_year ?? '') : '', help: 'Leave blank to estimate from intake.' },
    { name: 'notes', label: 'Notes', type: 'textarea', value: b.notes || '' },
  ];
}
function branchBody(v) {
  const body = {
    code: str(v.code)?.toUpperCase() ?? null, name: str(v.name), category: v.category,
    intake_per_year: num(v.intake_per_year), intake_basis: num(v.intake_per_year) == null ? 'pending' : v.intake_basis,
    intake_source: str(v.intake_source), intake_year: str(v.intake_year), notes: str(v.notes),
  };
  if (v.is_relevant != null && v.is_relevant !== '') body.is_relevant = Number(v.is_relevant) ? 1 : 0;
  else body.is_relevant = ['it_core', 'it_allied', 'circuit'].includes(v.category) ? 1 : 0;
  if (num(v.strength_total) != null) { body.strength_total = num(v.strength_total); body.strength_basis = 'verified'; }
  if (num(v.final_year) != null) { body.final_year = num(v.final_year); body.final_year_basis = 'verified'; }
  return body;
}
function checkBranch(v) {
  const errs = {};
  if (!str(v.code)) errs.code = 'Code is required.';
  if (!str(v.name)) errs.name = 'Name is required.';
  if (!CATEGORY_OPTS.some((o) => o.value === v.category)) errs.category = 'Choose a category.';
  for (const k of ['intake_per_year', 'strength_total', 'final_year']) if (num(v[k]) != null && num(v[k]) < 0) errs[k] = 'Cannot be negative.';
  if (num(v.intake_per_year) != null && v.intake_basis === 'verified' && !str(v.intake_source)) errs.intake_source = 'Verified figures need a source.';
  if (Object.keys(errs).length) throw validationError(errs);
}

export async function editBranch(...args) {
  const [ctx, [b0]] = await split(args);
  let b = typeof b0 === 'object' && b0 ? b0 : null;
  if (!b || b.code === undefined) {
    try { b = (await ctx.api.get(`/branches/${b ? b.id : b0}`)).branch; } catch (e) { ctx.ui.toast(e.message, 'bad'); return null; }
  }
  let mm = null;
  const extra = ctx.h('div', { class: 'vx-form-danger' },
    ctx.h('button', { type: 'button', class: 'td-btn td-btn--danger td-btn--sm', onClick: async () => {
      const msg = `Delete branch ${b.code || b.name}? People keep their records, but the branch link is removed.`;
      const ok = ctx.ui.confirm ? await ctx.ui.confirm({ title: 'Delete branch?', text: msg, confirmLabel: 'Delete' }) : window.confirm(msg);
      if (!ok) return;
      try { await ctx.api.del(`/branches/${b.id}`); ctx.ui.toast('Branch deleted', 'good'); mm?.close(); ctx.refresh?.(); } catch (e) { ctx.ui.toast(e.message, 'bad'); }
    } }, 'Delete branch'));
  mm = await openForm(ctx, {
    title: `Edit branch — ${b.code || b.name}`, fields: branchFields(b), submitLabel: 'Save branch', success: 'Branch updated', extra,
    onSubmit: async (v) => { checkBranch(v); return ctx.api.patch(`/branches/${b.id}`, branchBody(v)); },
  });
  return mm;
}

export async function addBranch(...args) {
  const [ctx, [opts = {}]] = await split(args);
  const collegeId = typeof opts === 'object' ? opts.college_id : opts;
  if (!collegeId) { ctx.ui.toast('Open a college first', 'warn'); return null; }
  return openForm(ctx, {
    title: 'Add branch', fields: branchFields({}), submitLabel: 'Add branch', success: (r, v) => `Branch ${String(v.code).toUpperCase()} added`,
    onSubmit: async (v) => { checkBranch(v); return ctx.api.post('/branches', { college_id: collegeId, ...branchBody(v) }); },
  });
}

/* ------------------------------------------------------------------ calling system: contacts, calls, enrollment stages */

// Labels for the calling system. Keys are the stored values (never change them); only the wording shown to people changes.
export const CONTACT_ROLE_LABEL = { tpo: 'Placement officer (TPO)', principal: 'Principal', hod: 'Head of department', office: 'College office', admissions: 'Admissions', dean: 'Dean', other: 'Other' };
/** Number status: set by logged calls (or by hand). [label, tone] */
export const CONTACT_STATUS = {
  untested: ['Not tried yet', 'neutral'], working: ['Working', 'good'], non_working: ['Not working', 'warn'], invalid: ['Wrong number', 'bad'],
};
/** Call outcomes. hint = what to pick it for (button tooltip). next = suggested call-back in days (null = none). */
export const OUTCOMES = {
  connected_interested: { label: 'Interested', group: 'connected', tone: 'good', next: 3, hint: 'They want to go ahead or hear more' },
  connected_callback: { label: 'Asked to call back', group: 'connected', tone: 'info', next: 1, hint: 'Busy now, or asked us to call another time' },
  connected_info_only: { label: 'Took details only', group: 'connected', tone: 'info', next: 7, hint: 'Listened or asked for details, no decision' },
  connected_not_interested: { label: 'Not interested', group: 'connected', tone: 'neutral', next: null, hint: 'Said no' },
  no_answer: { label: 'No answer', group: 'unanswered', tone: 'warn', next: 1, hint: 'It rang, nobody picked up' },
  busy: { label: 'Line busy', group: 'unanswered', tone: 'warn', next: 1, hint: 'Engaged tone, or the call was cut' },
  switched_off: { label: 'Switched off', group: 'unanswered', tone: 'warn', next: 1, hint: 'Phone switched off' },
  not_reachable: { label: 'Not reachable', group: 'unanswered', tone: 'warn', next: 1, hint: 'Out of coverage / network message' },
  wrong_number: { label: 'Wrong person', group: 'bad', tone: 'bad', next: null, hint: 'Someone answered who is not with this college' },
  invalid_number: { label: 'Number does not exist', group: 'bad', tone: 'bad', next: null, hint: '"This number does not exist" or too few digits' },
  disconnected: { label: 'Number out of service', group: 'bad', tone: 'bad', next: null, hint: '"Temporarily out of service" / permanently disconnected' },
};
/** College calling status (derived by the server from calls, call-backs and enrollments). [label, tone] */
export const CALL_STATUS = {
  not_called: ['Not called yet', 'neutral'], attempted_no_answer: ['No answer yet', 'warn'], follow_up_due: ['Call-back due', 'info'],
  contacted: ['Spoke to them', 'brand'], interested: ['Interested', 'good'], participation_confirmed: ['College agreed', 'good'], enrolled: ['Students enrolled', 'good'],
};
export const STAGE_OPTS = [
  { value: 'lead', label: 'Lead (contact taken)' }, { value: 'interested', label: 'Interested' },
  { value: 'registered', label: 'Registered (form filled)' }, { value: 'applied', label: 'Applied (fee pending)' },
  { value: 'confirmed', label: 'Confirmed (counts)' }, { value: 'dropped', label: 'Dropped / refunded' },
];
export const STAGE_LABEL = { lead: 'Lead', interested: 'Interested', registered: 'Registered', applied: 'Applied', confirmed: 'Confirmed', dropped: 'Dropped' };
const STAGE_TONE = { lead: 'neutral', interested: 'info', registered: 'info', applied: 'warn', confirmed: 'good', dropped: 'bad' };
export function stageBadge(ctx, stage) { return ctx.ui.badge(STAGE_LABEL[stage || 'confirmed'] || stage, STAGE_TONE[stage || 'confirmed'] || 'neutral'); }
export function contactStatusBadge(ctx, s) { const [l, t] = CONTACT_STATUS[s] || [s, 'neutral']; return ctx.ui.badge(l, t); }
export function callStatusBadge(ctx, s) { const [l, t] = CALL_STATUS[s] || [s, 'neutral']; return ctx.ui.badge(l, t); }
export function contactLabel(k) { return k ? [k.name, CONTACT_ROLE_LABEL[k.role] || k.role].filter(Boolean).join(' · ') : ''; }
/** tel: link that dials the stored +91 number. */
export function telLink(ctx, phone, { label, cls } = {}) {
  if (!phone) return null;
  return ctx.h('a', { href: `tel:${phone}`, class: ['vx-tel', cls], 'aria-label': `Call ${formatPhone(phone)}` }, ctx.ui.icon('phone', { size: 16 }), ctx.h('span', null, label || formatPhone(phone)));
}

function contactFields(k = {}, branches = [], { edit } = {}) {
  return [
    { name: 'role', label: 'Role', type: 'select', required: true, options: Object.entries(CONTACT_ROLE_LABEL).map(([value, label]) => ({ value, label })), value: k.role || 'tpo' },
    { name: 'name', label: 'Name', type: 'text', value: k.name, placeholder: 'Optional, e.g. Dr. K. Rao' },
    { name: 'phone', label: 'Phone', type: 'tel', value: k.phone ? formatPhone(k.phone) : '', placeholder: '98765 43210 or 0863 2344700', help: 'Saved as +91 and a 10-digit number. The same number cannot be added twice for one college.' },
    { name: 'email', label: 'Email', type: 'email', value: k.email },
    { name: 'basis', label: 'Is it verified?', type: 'select', required: true, options: [{ value: 'verified', label: 'Verified — official site or confirmed by the college' }, { value: 'pending', label: 'Not verified yet (listing, aggregator, word of mouth)' }], value: k.basis || 'pending' },
    { name: 'source_url', label: 'Where it was found (link)', type: 'url', value: k.source_url, placeholder: 'https://…', help: 'Optional. The page that lists this number or email.' },
    branches.length ? { name: 'branch_id', label: 'Branch (for a head of department)', type: 'select', options: [NONE('— Whole college —'), ...branchOpts(branches)], value: k.branch_id ? String(k.branch_id) : '' } : null,
    edit ? { name: 'status', label: 'Number status', type: 'select', required: true, options: Object.entries(CONTACT_STATUS).map(([value, [label]]) => ({ value, label })), value: k.status || 'untested', help: 'Set automatically from logged calls. Change it only if you know better; your choice then stays until you change it again.' } : null,
    { name: 'notes', label: 'Notes', type: 'textarea', value: k.notes },
  ].filter(Boolean);
}
function contactBody(v, collegeId) {
  const b = { role: v.role, name: str(v.name), phone: str(v.phone), email: str(v.email), basis: v.basis, source_url: str(v.source_url), notes: str(v.notes) };
  if (collegeId) b.college_id = collegeId;
  if (v.branch_id !== undefined) b.branch_id = num(v.branch_id);
  if (v.status) b.status = v.status;
  return b;
}
function checkContactVals(v) {
  const f = {};
  if (!str(v.phone) && !str(v.email)) { f.phone = 'Add a phone number or an email.'; }
  if (v.email && !EMAIL_RE.test(String(v.email).trim())) f.email = 'Enter a valid email address.';
  if (Object.keys(f).length) throw validationError(f);
}

export async function addContact(...args) {
  const [ctx, [opts = {}]] = await split(args);
  const collegeId = opts.college_id;
  let d; try { d = await collegeDetail(ctx, collegeId); } catch (e) { ctx.ui.toast(e.message, 'bad'); return null; }
  return openForm(ctx, {
    title: `Add contact — ${d.college?.short_name || d.college?.name || collegeId}`,
    fields: contactFields({}, d.branches || []), submitLabel: 'Add contact', success: 'Contact added',
    onSubmit: async (v) => { checkContactVals(v); const r = await ctx.api.post('/contacts', contactBody(v, collegeId)); opts.onSaved?.(r); return r; },
  });
}
export async function editContact(...args) {
  const [ctx, [k, opts = {}]] = await split(args);
  let d; try { d = await collegeDetail(ctx, k.college_id); } catch (e) { ctx.ui.toast(e.message, 'bad'); return null; }
  const { h } = ctx;
  let m = null;
  const del = ctx.ui.button({ label: 'Delete contact', tone: 'ghost', icon: 'trash', size: 'sm' });
  del.addEventListener('click', async () => {
    if (!(await ctx.ui.confirm({ title: 'Delete this contact?', text: 'Only for a contact added by mistake. A contact with logged calls cannot be deleted. Set its number status to “Wrong number” or “Not working” instead.', confirmLabel: 'Delete' }))) return;
    try { await ctx.api.del(`/contacts/${k.id}`); ctx.ui.toast('Contact deleted', 'good'); m?.close(); ctx.refresh?.(); } catch (e) { ctx.ui.toast(e.message, 'bad'); }
  });
  m = await openForm(ctx, {
    title: `Edit contact — ${contactLabel(k) || formatPhone(k.phone)}`,
    fields: contactFields(k, d.branches || [], { edit: true }), submitLabel: 'Save contact', success: 'Contact saved',
    extra: h('div', { class: 'vx-danger-zone' }, del),
    onSubmit: async (v) => { checkContactVals(v); const r = await ctx.api.patch(`/contacts/${k.id}`, contactBody(v)); opts.onSaved?.(r); return r; },
  });
  return m;
}

const addDaysIso = (iso, n) => new Date(Date.parse(iso + 'T00:00:00Z') + n * 86400000).toISOString().slice(0, 10);

/**
 * Fast "Log call" modal. opts: {college_id, contact_id?, contacts?, college_label?, onSaved?}
 * Outcome buttons, notes, next-action quick dates and "participation confirmed"; one tap per choice on a phone.
 */
export async function logCall(...args) {
  const [ctx, [opts = {}]] = await split(args);
  if (!(await ensureUser(ctx))) return null;
  const { h, ui } = ctx;
  let contacts = opts.contacts; let label = opts.college_label;
  if (!contacts) {
    try { const d = await collegeDetail(ctx, opts.college_id); contacts = d.contacts || []; label = label || d.college?.short_name || d.college?.name; } catch (e) { ui.toast(e.message, 'bad'); return null; }
  }
  const t0 = todayStr();
  const pick = opts.contact_id ?? (contacts.find((k) => k.status === 'working') || contacts.find((k) => k.status === 'untested') || contacts[0])?.id ?? null;
  const st = { contact: pick, outcome: null, next: null, nextTouched: false, confirm: false };
  const err = h('div', { class: 'vcl-err', role: 'alert', hidden: true });

  const contactBox = h('div', { class: 'vcl-contacts', role: 'radiogroup', 'aria-label': 'Who did you call?' });
  const contactBtn = (id, title, sub, badge) => {
    const on = st.contact === id;
    return h('button', { type: 'button', role: 'radio', 'aria-checked': String(on), tabindex: on ? '0' : '-1', autofocus: on ? true : null, class: ['vcl-contact', on && 'is-on'], onClick: () => { st.contact = id; drawContacts(); contactBox.querySelector('.is-on')?.focus(); } },
      h('span', { class: 'vcl-contact-main' }, h('strong', null, title), h('span', { class: 'vx-muted vx-small' }, sub)), badge || null);
  };
  const drawContacts = () => contactBox.replaceChildren(
    ...contacts.map((k) => contactBtn(k.id, contactLabel(k) || 'Contact', k.phone ? formatPhone(k.phone) : k.email || '', contactStatusBadge(ctx, k.status))),
    contactBtn(null, contacts.length ? 'A number not listed here' : 'College number (not in contacts)', 'Logged for the college only'));
  drawContacts();

  const groups = [['connected', 'Spoke to someone'], ['unanswered', 'Did not connect'], ['bad', 'Number problem']];
  const outBox = h('div', { class: 'vcl-outcomes', role: 'radiogroup', 'aria-label': 'What happened?', 'aria-required': 'true' });
  const confirmInput = h('input', { type: 'checkbox', onChange: (e) => { st.confirm = e.target.checked; } });
  const confirmRow = h('label', { class: 'vcl-confirm' }, confirmInput, h('span', null, 'The college agreed to take part (only after speaking to someone)'));
  const drawOutcomes = () => {
    outBox.replaceChildren(...groups.map(([g, title]) => h('fieldset', { class: 'vcl-group' }, h('legend', null, title),
      h('div', { class: 'vcl-grid' }, Object.entries(OUTCOMES).filter(([, o]) => o.group === g).map(([k, o]) =>
        h('button', { type: 'button', role: 'radio', class: ['vcl-out', `vcl-out--${o.tone}`, st.outcome === k && 'is-on'], 'aria-checked': String(st.outcome === k), 'data-k': k, title: o.hint || null, onClick: () => { pickOutcome(k); outBox.querySelector(`[data-k="${k}"]`)?.focus(); } }, o.label))))));
    const connected = !!st.outcome && OUTCOMES[st.outcome].group === 'connected';
    confirmInput.disabled = !connected;
    if (!connected) { confirmInput.checked = false; st.confirm = false; }
    confirmRow.classList.toggle('is-disabled', !connected);
  };

  const nextBox = h('div', { class: 'vcl-next', role: 'group', 'aria-label': 'Call back on' });
  const dateIn = h('input', { type: 'date', class: 'td-input td-num vcl-date', min: t0, 'aria-label': 'Pick a call-back date', onChange: (e) => { st.next = e.target.value || null; st.nextTouched = true; drawNext(); } });
  const quick = [['No call-back', null], ['Today', 0], ['Tomorrow', 1], ['In 3 days', 3], ['Next week', 7]];
  const drawNext = () => {
    nextBox.replaceChildren(...quick.map(([l, n]) => {
      const v = n == null ? null : addDaysIso(t0, n);
      return ui.chip({ label: l, active: st.next === v, onClick: () => { st.next = v; st.nextTouched = true; drawNext(); } });
    }), dateIn);
    dateIn.value = st.next || '';
  };
  const pickOutcome = (k) => {
    st.outcome = k; err.hidden = true; outBox.removeAttribute('aria-invalid');
    if (!st.nextTouched) { const n = OUTCOMES[k].next; st.next = n == null ? null : addDaysIso(t0, n); drawNext(); }
    drawOutcomes();
  };
  drawNext();
  drawOutcomes();
  const notes = h('textarea', { class: 'td-input vcl-notes', rows: 2, placeholder: 'What was said? Who to ask for next time?', 'aria-label': 'Notes' });

  const body = h('div', { class: 'vcl' },
    h('section', null, h('h3', { class: 'vcl-h' }, 'Who did you call?'), contactBox),
    h('section', null, h('h3', { class: 'vcl-h' }, 'What happened?'), outBox),
    h('section', null, h('h3', { class: 'vcl-h' }, 'Call back on'), nextBox, h('p', { class: 'vx-muted vx-small vcl-help' }, 'A date adds a call-back to Follow-ups, assigned to you. It is suggested from what happened; change it if needed.')),
    h('section', null, h('h3', { class: 'vcl-h' }, 'Notes'), notes, confirmRow),
    err);
  ui.modal({
    title: `Log call — ${label || opts.college_id}`, body,
    actions: [
      { label: 'Cancel', tone: 'ghost' },
      { label: 'Save call', tone: 'primary', onClick: async () => {
        if (!st.outcome) { err.textContent = 'Choose what happened on the call.'; err.hidden = false; outBox.setAttribute('aria-invalid', 'true'); outBox.querySelector('.vcl-out')?.focus(); return false; }
        const payload = { college_id: opts.college_id, contact_id: st.contact, outcome: st.outcome, notes: str(notes.value), next_action_at: st.next, confirms_participation: st.confirm || undefined };
        try {
          const r = await ctx.api.post('/calls', payload);
          const k = r.contact;
          ui.toast(`Call logged${k && k.status !== 'untested' ? ` · number: ${(CONTACT_STATUS[k.status]?.[0] || k.status).toLowerCase()}` : ''}${r.followup ? ` · call-back ${ctx.fmt.date(r.followup.due_date)}` : ''}`, 'good');
          if (opts.onSaved) opts.onSaved(r); else ctx.refresh?.();
          return true;
        } catch (e) { err.textContent = e.message || 'Could not save the call'; err.hidden = false; return false; }
      } },
    ],
  });
  return true;
}

/**
 * Edit an enrollment record (all fields) or delete one recorded by mistake.
 * The credited person is limited to people of the enrollment's college (R8); the record is never copied.
 */
export async function editEnrollment(...args) {
  const [ctx, [e0]] = await split(args);
  const { h, ui, fmt } = ctx;
  let e = e0 && typeof e0 === 'object' ? e0 : { id: e0 };
  if (!e.college_id || e.stage === undefined) { try { e = { ...e, ...(await ctx.api.get(`/enrollments/${e.id}`)) }; } catch (err) { ui.toast(err.message, 'bad'); return null; } }
  let d = {}; let m = {};
  try { [d, m] = await Promise.all([collegeDetail(ctx, e.college_id), meta(ctx)]); } catch (err) { ui.toast(err.message, 'bad'); return null; }
  const branches = (d.branches || []).slice().sort((a, b) => (b.is_relevant ? 1 : 0) - (a.is_relevant ? 1 : 0) || String(a.code || a.name).localeCompare(b.code || b.name));
  // same-college people only; the currently credited person stays listed even when inactive
  const people = (d.people || []).filter((p) => p.status !== 'inactive' || Number(p.id) === Number(e.person_id));
  const courses = (m.courses || []).filter((c) => c.active !== 0 || Number(c.id) === Number(e.course_id));
  const today = todayStr();
  const fields = [
    { name: 'stage', label: 'Stage', type: 'select', required: true, options: STAGE_OPTS, value: e.stage || 'confirmed', help: 'Moving the stage updates this record. Only “Confirmed” counts toward targets.' },
    { name: 'confirmed_on', label: 'Confirmed on', type: 'date', value: e.confirmed_on || '', max: today, help: 'The day the student confirmed. Counts toward targets from this date.' },
    { name: 'enrolled_on', label: 'First recorded on', type: 'date', required: true, value: e.enrolled_on || '', max: today },
    { name: 'course_id', label: 'Course', type: 'select', options: [NONE('— Course not set —'), ...courses.map((c) => ({ value: String(c.id), label: `${c.name}${c.price_inr != null ? ' — ' + fmt.inr(c.price_inr) : ''}` }))], value: e.course_id ? String(e.course_id) : '' },
    { name: 'amount_inr', label: 'Amount paid (₹)', type: 'number', min: 0, step: 1, value: e.amount_inr ?? '' },
    { name: 'branch_id', label: "Student's branch", type: 'select', options: [NONE('— Branch not known —'), ...branchOpts(branches)], value: e.branch_id ? String(e.branch_id) : '' },
    { name: 'person_id', label: 'Credit to', type: 'select', options: [NONE('— No one credited —'), ...people.map((p) => personOpt(p))], value: e.person_id ? String(e.person_id) : '', help: `Only people of ${d.college?.short_name || d.college?.name || 'this college'} can be credited.` },
    { name: 'student_name', label: 'Student name', type: 'text', value: e.student_name || '' },
    { name: 'student_contact', label: 'Student phone or email', type: 'text', value: e.student_contact || '' },
    { name: 'notes', label: 'Notes', type: 'textarea', value: e.notes || '' },
  ];
  let mm = null;
  const del = h('div', { class: 'vf-danger v-person-dlg__danger' }, h('span', { class: 'vx-small vx-muted' }, 'Recorded by mistake?'),
    h('button', { type: 'button', class: 'td-btn td-btn--ghost td-btn--sm', onClick: async () => {
      const ok = await ui.confirm({ title: 'Delete this enrollment?', text: `${e.student_name || `Enrollment #${e.id}`} (${STAGE_LABEL[e.stage] || e.stage}) is removed for good and stops counting toward targets. The change is kept in the audit history. To record a refund, set the stage to “Dropped / refunded” instead.`, confirmLabel: 'Delete enrollment' });
      if (!ok) return;
      try { await ctx.api.del(`/enrollments/${e.id}`); ui.toast('Enrollment deleted', 'good'); mm?.close(); ctx.refresh?.(); } catch (err) { ui.toast(err.message, 'bad'); }
    } }, ui.icon('trash'), ' Delete'));
  const dateRule = (v) => (!v ? '' : !/^\d{4}-\d{2}-\d{2}$/.test(v) ? 'Use a date like 2026-11-07.' : v > today ? 'Date cannot be in the future.' : '');
  mm = await openForm(ctx, {
    title: `Edit enrollment — ${e.student_name || `#${e.id}`}`, fields, submitLabel: 'Save', extra: del,
    success: (r) => (r && r._noop ? 'No changes to save' : `Saved · stage ${STAGE_LABEL[r?.stage] || r?.stage || ''}`),
    after: (formEl, byName) => {
      const sel = field(formEl, 'stage');
      const sync = () => {
        const st = byName.stage.options[Number(sel.value)]?.value;
        showField(formEl, 'confirmed_on', st === 'confirmed');
        const c = field(formEl, 'confirmed_on');
        if (st === 'confirmed' && c && !c.value) c.value = today;
      };
      sel?.addEventListener('change', sync); sync();
      onChange(formEl, byName.course_id, (cid) => { const a = field(formEl, 'amount_inr'); const pr = courses.find((c) => String(c.id) === String(cid))?.price_inr; if (a && !a.value && pr != null) a.value = pr; });
      liveValidate(formEl, { enrolled_on: (v) => (!v ? 'Date is required.' : dateRule(v)), confirmed_on: dateRule, amount_inr: (v) => (v && Number.isNaN(wholeOrNull(v)) ? 'Enter whole rupees (0 or more).' : '') });
    },
    onSubmit: async (v) => {
      const errs = {};
      if (!v.enrolled_on) errs.enrolled_on = 'Date is required.'; else if (dateRule(v.enrolled_on)) errs.enrolled_on = dateRule(v.enrolled_on);
      if (v.stage === 'confirmed' && v.confirmed_on && dateRule(v.confirmed_on)) errs.confirmed_on = dateRule(v.confirmed_on);
      if (v.stage === 'confirmed' && v.confirmed_on && v.enrolled_on && v.confirmed_on < v.enrolled_on) errs.confirmed_on = 'Cannot be before the first recorded date.';
      if (Number.isNaN(wholeOrNull(v.amount_inr))) errs.amount_inr = 'Enter whole rupees (0 or more).';
      if (Object.keys(errs).length) throw validationError(errs);
      const next = {
        stage: v.stage, enrolled_on: v.enrolled_on, course_id: num(v.course_id), amount_inr: wholeOrNull(v.amount_inr), branch_id: num(v.branch_id),
        person_id: num(v.person_id), student_name: str(v.student_name), student_contact: str(v.student_contact), notes: str(v.notes),
      };
      if (v.stage === 'confirmed' && v.confirmed_on) next.confirmed_on = v.confirmed_on;
      const body = {};
      for (const [k, val] of Object.entries(next)) if ((val ?? null) !== (e[k] ?? null)) body[k] = val;
      if (!Object.keys(body).length) return { _noop: true };
      if ('person_id' in body && !(await confirmInactiveCredit(ctx, people.find((p) => String(p.id) === String(v.person_id))))) return { _keepOpen: true };
      return ctx.api.patch(`/enrollments/${e.id}`, body);
    },
  });
  return mm;
}
