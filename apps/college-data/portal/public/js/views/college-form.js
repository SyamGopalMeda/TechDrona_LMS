// Tech Drona portal — create / edit a college (CL). One dialog for both, with per-field source + verification (R13)
// and a live duplicate warning. API (CONTRACT v4):
//   POST  /api/colleges {name, district_id, city_id | city_name, …, sources?}  (sno defaults to max+1; 409 duplicate_college)
//   PATCH /api/colleges/:id {changed fields…, sources:{field: source}}    a changed field WITHOUT a source becomes unverified
//   POST  /api/colleges/:id/verify {fields:[…], source, note?, verified?}  stamp (or clear) verification without changing values
// Exports: createCollege(ctx, {district_id?, city_id?}), editCollege(ctx, id), verifyFields(ctx, id, fields)
import { normAnyPhone } from './forms.js';

const OP = [['operational', 'Operational'], ['possibly_closed', 'Possibly closed'], ['closed', 'Closed'], ['pending', 'Not checked yet']];
const YNU = [['unknown', 'Unknown'], ['yes', 'Yes'], ['no', 'No']];
const AUTONOMY = [['', 'Not known'], ['Yes', 'Autonomous'], ['No', 'Not autonomous'], ['Unclear', 'Unclear']];
const TIERS = [['', 'Not known'], ['Tier 1', 'Tier 1'], ['Tier 2', 'Tier 2'], ['Tier 3', 'Tier 3']];
const OWNERSHIP_HINTS = ['Pvt autonomous', 'Pvt affiliated', 'State pvt univ', 'Deemed (pvt)', 'Govt – State univ/constituent', 'Govt – National', 'Private self-financing'];
/** Fields whose provenance is tracked (server field_status keys). */
export const VERIFY_FIELDS = [
  ['name', 'Official name'], ['district_id', 'District'], ['city_id', 'City / town'], ['phone', 'College phone'], ['email', 'College email'],
  ['website', 'Website'], ['ownership', 'Ownership'], ['affiliation', 'Affiliation'], ['op_status', 'Operating status'],
];
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const str = (v) => { const s = v === undefined || v === null ? '' : String(v).trim(); return s || null; };
const norm = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();

/** "0863-2399999 / 98765 43210" -> null when every number is a valid Indian number, else a message. */
function phoneError(v) {
  if (!v) return null;
  const parts = String(v).split(/[\/,;]+/).map((x) => x.trim()).filter(Boolean);
  for (const p of parts) {
    const main = p.split(/\s*(?:ext|x)\.?\s*\d*$/i)[0];
    if (/[a-wyz]/i.test(main.replace(/ext/i, ''))) return 'Use digits only (several numbers can be separated by / or ,).';
    // F6: the same normalisation as the server (forms.normAnyPhone = server/db.js normPhone): mobile or STD landline
    if (!normAnyPhone(main)) return `“${p}” is not a 10-digit Indian number (mobile, or STD code + landline).`;
  }
  return null;
}
/** Source: an http(s) link or a plain note; other schemes (javascript:, data:…) are refused, as on the server. */
function sourceError(v) {
  if (!v) return null;
  if (/^[a-z][a-z0-9+.-]*:/i.test(v) && !/^https?:\/\//i.test(v)) return 'Use an http(s) link or a plain note.';
  return null;
}
function urlError(v) {
  if (!v) return null;
  return /^https?:\/\/[^\s]+\.[^\s]+/i.test(v) ? null : 'Enter a full link starting with http:// or https://';
}

async function loadMeta(ctx) {
  try { return await ctx.api.get('/meta'); } catch { return { districts: [], cities: [] }; }
}

/** A college's verification entry → {state, source, date, by}. */
export function fieldVerification(c, field) {
  const vf = (c && c.verified_fields && typeof c.verified_fields === 'object') ? c.verified_fields : {};
  const fs = c && c.field_status ? c.field_status[field] : null;
  const e = vf[field];
  if (e && (e.verified_on || e.source)) return { state: 'verified', source: e.source || null, date: e.verified_on || null, by: e.verified_by || null };
  if (fs) return { state: fs, source: null, date: null, by: null };
  const v = c ? c[field] : null;
  return { state: v === null || v === undefined || v === '' ? 'missing' : 'unverified', source: null, date: null, by: null };
}
export function verificationBadge(ctx, c, field) {
  const v = fieldVerification(c, field);
  if (typeof ctx.ui.verifiedBadge === 'function') return ctx.ui.verifiedBadge(v);
  return ctx.ui.badge(v.state === 'verified' ? 'Verified' : v.state === 'missing' ? 'Missing' : 'Unverified', v.state === 'verified' ? 'good' : v.state === 'missing' ? 'neutral' : 'warn');
}
/** true when the server tracks per-field verification (v4). */
export const tracksVerification = (c) => !!c && ('verified_fields' in c || 'field_status' in c);

export function createCollege(ctx, preset = {}) { return openCollegeDialog(ctx, null, preset); }
export function editCollege(ctx, id, opts = {}) { return openCollegeDialog(ctx, id, opts); }

async function openCollegeDialog(ctx, id, preset = {}) {
  const { h, ui, api } = ctx;
  const meta = await loadMeta(ctx);
  let c = null;
  if (id) {
    try { c = (await api.get(`/colleges/${encodeURIComponent(id)}`)).college; } catch (e) { ui.toast(e.message, 'bad'); return null; }
  }
  const isNew = !c;
  const track = isNew ? true : tracksVerification(c);
  const districts = [...(meta.districts || [])].sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const inputs = {};
  const errEls = {};
  const field = (name, label, control, { help, full, req } = {}) => {
    const fid = `cf-${name}`;
    control.id = fid;
    if (!control.name) control.name = name;
    inputs[name] = control;
    errEls[name] = h('div', { class: 'td-field__error', id: `${fid}-err`, role: 'alert' });
    control.setAttribute('aria-describedby', `${fid}-err${help ? ` ${fid}-help` : ''}`);
    return h('div', { class: ['td-field', full && 'td-field--full'] },
      h('label', { for: fid, class: 'td-field__label' }, label, req ? h('span', { class: 'td-field__req', 'aria-hidden': 'true' }, ' *') : null),
      control, help ? h('div', { class: 'td-field__help', id: `${fid}-help` }, help) : null, errEls[name]);
  };
  const text = (name, value, attrs = {}) => { const el = h('input', { type: 'text', class: 'td-input', autocomplete: 'off', ...attrs }); el.value = value ?? ''; return el; };
  const select = (name, opts, value) => {
    const el = h('select', { class: 'td-input td-select' }, opts.map(([v, l]) => h('option', { value: v }, l)));
    el.value = value ?? (opts[0] ? opts[0][0] : '');
    return el;
  };
  const area = (value, rows = 2) => { const el = h('textarea', { class: 'td-input', rows }); el.value = value ?? ''; return el; };

  const v0 = c || {};
  const districtSel = select('district_id', [['', 'Choose a district…'], ...districts.map((d) => [d.id, d.name])], v0.district_id || preset.district_id || '');
  const citySel = h('select', { class: 'td-input td-select' });
  const cityNew = text('city_name', '', { placeholder: 'Name of the town' });
  const cityNewWrap = field('city_name', 'New town name', cityNew, { help: 'Only when the town is not in the list.' });
  const fillCities = (keep) => {
    const did = districtSel.value;
    const list = (meta.cities || []).filter((x) => x.district_id === did).sort((a, b) => String(a.name).localeCompare(String(b.name)));
    citySel.replaceChildren(h('option', { value: '' }, did ? 'Choose a city or town…' : 'Choose the district first'),
      ...list.map((x) => h('option', { value: x.id }, x.name)), did ? h('option', { value: '__new' }, '+ Town not in the list…') : null);
    citySel.value = keep && list.some((x) => x.id === keep) ? keep : '';
    cityNewWrap.hidden = citySel.value !== '__new';
  };
  districtSel.addEventListener('change', () => { fillCities(null); });
  citySel.addEventListener('change', () => { cityNewWrap.hidden = citySel.value !== '__new'; });
  fillCities(v0.city_id || preset.city_id || null);

  const ownership = text('ownership', v0.ownership, { list: 'cf-ownership-list' });
  const opSel = select('op_status', OP, v0.op_status || (isNew ? 'operational' : 'pending'));
  const targeted = h('input', { type: 'checkbox', class: 'td-check' });
  targeted.checked = isNew ? true : !!v0.targeted;

  // duplicate warning (live, while typing the name)
  const dupBox = h('div', { class: 'vcf-dup', role: 'status', 'aria-live': 'polite', hidden: true });
  const nameIn = text('name', v0.name, { maxlength: '300' });
  let dupSeq = 0;
  const checkDup = async () => {
    const q = str(nameIn.value);
    const my = ++dupSeq;
    if (!q || q.length < 4 || (!isNew && norm(q) === norm(v0.name))) { dupBox.hidden = true; return; }
    try {
      const res = await api.get('/colleges', { q, districts: 'all' });
      if (my !== dupSeq) return;
      const rows = (Array.isArray(res) ? res : res.items || []).filter((r) => !c || r.id !== c.id);
      const same = rows.filter((r) => norm(r.name) === norm(q) || norm(r.short_name) === norm(q));
      const show = (same.length ? same : rows).slice(0, 4);
      if (!show.length) { dupBox.hidden = true; return; }
      const dName = (did) => (meta.districts || []).find((d) => d.id === did)?.name || did;
      dupBox.hidden = false;
      dupBox.className = ['vcf-dup', same.length ? 'is-bad' : 'is-warn'].join(' ');
      dupBox.replaceChildren(ui.icon('warn', { size: 16 }), h('div', null,
        h('strong', null, same.length ? 'A college with this name is already in the portal' : 'Similar colleges already in the portal'),
        h('ul', null, show.map((r) => h('li', null, h('a', { href: `#/college/${r.id}`, target: '_blank', rel: 'noopener' }, r.name), ` · ${dName(r.district_id)} · #${r.sno}`))),
        h('span', { class: 'vx-muted vx-small' }, 'Open it instead of adding a duplicate. The server refuses the same name in the same district.')));
    } catch { /* duplicate check is advisory */ }
  };
  nameIn.addEventListener('input', (() => { let t; return () => { clearTimeout(t); t = setTimeout(checkDup, 350); }; })());

  // per-field source + verification
  const srcIn = {};
  const verifyRows = VERIFY_FIELDS.map(([f, label]) => {
    srcIn[f] = text(`src_${f}`, '', { placeholder: 'Link (https://…) or note, e.g. “AICTE approval 2025-26”', 'aria-label': `Source for ${label}` });
    errEls[`src_${f}`] = h('div', { class: 'td-field__error', role: 'alert' });
    const cur = isNew ? null : fieldVerification(c, f);
    return h('div', { class: 'vcf-vrow' },
      h('div', { class: 'vcf-vlabel' }, h('strong', null, label), !isNew && track ? verificationBadge(ctx, c, f) : null,
        cur && cur.state === 'verified' && cur.source ? h('span', { class: 'vx-muted vx-small vcf-vsrc', title: cur.source }, cur.source.replace(/^https?:\/\//, '').slice(0, 48)) : null),
      h('div', { class: 'vcf-vin' }, srcIn[f], errEls[`src_${f}`]));
  });

  const grid = (...kids) => h('div', { class: 'td-form__grid' }, ...kids);
  const group = (title, sub, ...kids) => h('fieldset', { class: 'vcf-group' }, h('legend', null, title), sub ? h('p', { class: 'vx-muted vx-small' }, sub) : null, ...kids);
  const body = h('form', { class: 'td-form vcf', novalidate: true, onSubmit: (e) => { e.preventDefault(); } },
    h('datalist', { id: 'cf-ownership-list' }, OWNERSHIP_HINTS.map((o) => h('option', { value: o }))),
    group('Identity', isNew ? 'Add a college that is missing from the master list. Check the duplicate warning before saving.' : (c.sno ? `S.No ${c.sno} (fixed) · id ${c.id}` : null),
      grid(
        field('name', 'Official name', nameIn, { req: true, full: true }),
        h('div', { class: 'td-field td-field--full' }, dupBox),
        field('short_name', 'Short name', text('short_name', v0.short_name, { maxlength: '80' }), { help: 'How people refer to it, e.g. “VVIT”.' }),
        field('aliases', 'Other names', text('aliases', Array.isArray(v0.aliases) ? v0.aliases.join(', ') : '', {}), { help: 'Comma separated. Used by search.' }),
        field('district_id', 'District', districtSel, { req: true }),
        field('city_id', 'City / town', citySel, { req: true }),
        cityNewWrap,
        field('address', 'Address', area(v0.address), { full: true }))),
    group('Contact', 'The college office line, email and website as officially listed.',
      grid(
        field('phone', 'College phone', text('phone', v0.phone, { inputmode: 'tel' }), { help: '10-digit numbers; several allowed, separated by / or ,' }),
        field('email', 'College email', text('email', v0.email, { inputmode: 'email' })),
        field('website', 'Website', text('website', v0.website, { inputmode: 'url', placeholder: 'https://' }), { full: true }))),
    group('Institution', null,
      grid(
        field('ownership', 'Ownership', ownership),
        field('affiliation', 'Affiliation', text('affiliation', v0.affiliation), { help: 'University it is affiliated to, e.g. JNTUK.' }),
        field('autonomous', 'Autonomy', select('autonomous', AUTONOMY, v0.autonomous || '')),
        field('tier', 'Tier', select('tier', TIERS, v0.tier || '')),
        field('naac', 'NAAC grade', text('naac', v0.naac)))),
    group('Status', 'Changing the operating status needs evidence.',
      grid(
        field('op_status', 'Operating status', opSel),
        h('div', { class: 'td-field td-field--check' }, h('div', { class: 'td-field__checkrow' }, targeted, h('label', { class: 'td-field__label', onClick: () => targeted.click() }, 'Targeted by Tech Drona'))),
        field('op_2025_26', 'Admitted students 2025-26?', select('op_2025_26', YNU, v0.op_2025_26 || 'unknown')),
        field('op_2026_27', 'Admitted students 2026-27?', select('op_2026_27', YNU, v0.op_2026_27 || 'unknown')),
        field('op_status_note', 'Evidence for the status', area(v0.op_status_note), { full: true }),
        field('op_status_source', 'Evidence link', text('op_status_source', v0.op_status_source, { placeholder: 'https://' }), { full: true }),
        field('notes', 'Notes', area(v0.notes, 3), { full: true }))),
    track ? group('Sources & verification', isNew
      ? 'Give a source for each value you can back up. Values saved with a source are marked Verified; the rest stay Unverified.'
      : 'Type a source to mark a value Verified (today, by you). Changing a value without a source marks it Unverified.',
    h('div', { class: 'vcf-vlist' }, verifyRows))
      : h('p', { class: 'vcf-note vx-muted vx-small' }, 'This server does not record per-field verification yet; values are saved as typed (unverified).'));
  const formErr = h('div', { class: 'td-form__error', role: 'alert', hidden: true });
  body.append(formErr);

  const read = () => {
    const val = (n) => (inputs[n] ? (inputs[n].type === 'checkbox' ? inputs[n].checked : inputs[n].value) : undefined);
    const o = {
      name: str(val('name')), short_name: str(val('short_name')), aliases: (str(val('aliases')) || '').split(',').map((x) => x.trim()).filter(Boolean),
      district_id: str(districtSel.value), city_id: citySel.value && citySel.value !== '__new' ? citySel.value : null, city_name: citySel.value === '__new' ? str(cityNew.value) : null,
      address: str(val('address')), phone: str(val('phone')), email: str(val('email')) ? str(val('email')).toLowerCase() : null, website: str(val('website')),
      ownership: str(ownership.value), affiliation: str(val('affiliation')), autonomous: str(val('autonomous')), tier: str(val('tier')), naac: str(val('naac')),
      op_status: opSel.value, op_2025_26: val('op_2025_26'), op_2026_27: val('op_2026_27'), op_status_note: str(val('op_status_note')),
      op_status_source: str(val('op_status_source')), targeted: targeted.checked ? 1 : 0, notes: str(val('notes')),
    };
    const sources = {};
    for (const [f] of VERIFY_FIELDS) { const s = str(srcIn[f].value); if (s) sources[f] = s; }
    return { o, sources };
  };
  const clearErrors = () => { Object.values(errEls).forEach((e) => { e.textContent = ''; }); Object.values(inputs).forEach((i) => i.removeAttribute('aria-invalid')); Object.values(srcIn).forEach((i) => i.removeAttribute('aria-invalid')); formErr.hidden = true; };
  const showErrors = (errs, msg) => {
    let first = null;
    for (const [k, m] of Object.entries(errs || {})) {
      const key = k === 'city_name' && !errEls.city_name ? 'city_id' : k;
      const el = errEls[key] || errEls[`src_${key.replace(/^sources\.?/, '')}`];
      if (el) { el.textContent = m; const inp = inputs[key] || srcIn[key.replace(/^sources\.?/, '')]; if (inp) { inp.setAttribute('aria-invalid', 'true'); first = first || inp; } }
    }
    if (msg) { formErr.hidden = false; formErr.replaceChildren(msg); }
    (first || formErr).focus?.();
    first?.scrollIntoView?.({ block: 'center', behavior: 'auto' });
  };
  const validate = ({ o, sources }) => {
    const e = {};
    if (!o.name) e.name = 'Required';
    if (!o.district_id) e.district_id = 'Choose the district';
    if (!o.city_id && !o.city_name) e.city_id = citySel.value === '__new' ? 'Type the town name' : 'Choose the city or town';
    if (citySel.value === '__new' && !o.city_name) e.city_name = 'Type the town name';
    const pe = phoneError(o.phone); if (pe) e.phone = pe;
    if (o.email && !EMAIL_RE.test(o.email)) e.email = 'Enter a valid email address';
    const we = urlError(o.website); if (we) e.website = we;
    const se = sourceError(o.op_status_source) || (o.op_status_source && urlError(o.op_status_source)); if (se) e.op_status_source = se;
    if (!isNew && o.op_status !== (c.op_status || 'pending') && !o.op_status_note) e.op_status_note = 'Add the evidence for the new status';
    for (const [f, s] of Object.entries(sources)) { const m = sourceError(s); if (m) e[`src_${f}`] = m; }
    return e;
  };
  /** changed fields only (edit) — the server stamps/clears verification per changed field. */
  const diff = (o) => {
    if (isNew) return o;
    const out = {};
    const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
    for (const [k, val] of Object.entries(o)) {
      if (k === 'city_name') { if (val) out.city_name = val; continue; }
      if (k === 'aliases') { if (!same(val, Array.isArray(c.aliases) ? c.aliases : [])) out.aliases = val; continue; }
      if (k === 'targeted') { if (Number(val) !== Number(c.targeted ? 1 : 0)) out.targeted = val; continue; }
      if (k === 'op_2025_26' || k === 'op_2026_27') { if ((val || 'unknown') !== (c[k] || 'unknown')) out[k] = val; continue; }
      if (!same(val, c[k] === '' ? null : c[k])) out[k] = val;
    }
    return out;
  };

  let saving = false;
  const save = async () => {
    if (saving) return false;
    clearErrors();
    const r = read();
    const errs = validate(r);
    if (Object.keys(errs).length) { showErrors(errs, `Please fix ${Object.keys(errs).length === 1 ? 'the highlighted field' : `${Object.keys(errs).length} fields`}.`); return false; }
    saving = true;
    try {
      if (isNew) {
        const bodyOut = { ...r.o };
        if (!bodyOut.city_name) delete bodyOut.city_name; else delete bodyOut.city_id;
        if (!bodyOut.aliases.length) delete bodyOut.aliases;
        if (Object.keys(r.sources).length) bodyOut.sources = r.sources;
        const saved = await api.post('/colleges', bodyOut, { idempotencyKey });
        const nid = saved?.id ?? saved?.college?.id;
        ui.toast(`${bodyOut.short_name || bodyOut.name} added`, 'good');
        if (nid) ctx.navigate(`#/college/${encodeURIComponent(nid)}`); else ctx.refresh?.();
        return saved;
      }
      const changes = diff(r.o);
      // sources: changed fields carry their source in the PATCH; unchanged fields with a new source are stamped via /verify
      const patchSources = {}; const verifyOnly = {};
      for (const [f, s] of Object.entries(r.sources)) {
        const changed = f in changes || (f === 'city_id' && 'city_name' in changes);
        (changed ? patchSources : verifyOnly)[f] = s;
      }
      let did = false;
      if (Object.keys(changes).length) {
        if (Object.keys(patchSources).length) changes.sources = patchSources;
        await api.patch(`/colleges/${encodeURIComponent(c.id)}`, changes, { idempotencyKey });
        did = true;
      }
      const bySource = new Map();
      for (const [f, s] of Object.entries(verifyOnly)) bySource.set(s, [...(bySource.get(s) || []), f]);
      for (const [s, fields] of bySource) {
        await api.post(`/colleges/${encodeURIComponent(c.id)}/verify`, { fields, source: s });
        did = true;
      }
      ui.toast(did ? `${c.short_name || c.name} updated` : 'Nothing changed', did ? 'good' : 'info');
      if (did) ctx.refresh?.();
      return true;
    } catch (e) {
      // F1: after any answer from the server the next Save is a NEW request (fresh key); only a network failure keeps it.
      if (!e || e.status !== 0) idempotencyKey = newIdemKey();
      const d = e && e.data ? e.data : {};
      if (e && e.status === 409 && (d.code === 'duplicate_college' || d.existing_id)) {
        showErrors({ name: 'Already in the portal' }, h('span', null, `${e.message || 'This college already exists.'} `,
          d.existing_id ? h('a', { href: `#/college/${encodeURIComponent(d.existing_id)}`, onClick: () => m.close() }, 'Open the existing college') : null));
      } else showErrors(e && e.fields, e && e.message ? e.message : 'Could not save.');
      return false;
    } finally { saving = false; }
  };
  const newIdemKey = () => (typeof api.newKey === 'function' ? api.newKey() : (() => { try { return crypto.randomUUID(); } catch { return `cf${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`; } })());
  let idempotencyKey = newIdemKey();
  const m = ui.modal({
    title: isNew ? 'Add a college' : `Edit college — ${c.short_name || c.name}`,
    body, wide: true,
    actions: [{ label: 'Cancel', tone: 'ghost' }, { label: isNew ? 'Add college' : 'Save changes', tone: 'primary', onClick: save }],
  });
  // T17: on touch screens do not pop the keyboard before the user has read the dialog (responsive.md §9)
  if (!coarse()) setTimeout(() => nameIn.focus(), 50);
  if (isNew && str(nameIn.value)) checkDup();
  return m;
}

/** Mark fields verified (with one source) or clear their verification — used from the college page. */
export async function verifyFields(ctx, c, fields, { clear = false } = {}) {
  const { h, ui, api } = ctx;
  if (clear) {
    const ok = await ui.confirm({ title: 'Mark as unverified?', text: `The ${fields.length === 1 ? 'value stays, but it' : 'values stay, but they'} will show as Unverified until someone confirms ${fields.length === 1 ? 'it' : 'them'} with a source.`, confirmLabel: 'Mark unverified' });
    if (!ok) return null;
    try { await api.post(`/colleges/${encodeURIComponent(c.id)}/verify`, { fields, verified: false, source: 'cleared' }); ui.toast('Marked unverified', 'good'); ctx.refresh?.(); return true; } catch (e) { ui.toast(e.message, 'bad'); return null; }
  }
  const labels = Object.fromEntries(VERIFY_FIELDS);
  const src = h('input', { type: 'text', class: 'td-input', placeholder: 'https://… or a note, e.g. “Called the office on 7 Nov”' });
  const note = h('input', { type: 'text', class: 'td-input', placeholder: 'Optional note' });
  const err = h('div', { class: 'td-field__error', role: 'alert' });
  const body = h('div', { class: 'vcf' },
    h('p', null, `Confirm ${fields.map((f) => labels[f] || f).join(', ')} of ${c.short_name || c.name}. You and today's date are recorded with the source.`),
    h('label', { class: 'td-field' }, h('span', { class: 'td-field__label' }, 'Source', h('span', { class: 'td-field__req' }, ' *')), src),
    h('label', { class: 'td-field' }, h('span', { class: 'td-field__label' }, 'Note'), note), err);
  ui.modal({
    title: 'Mark as verified', body,
    actions: [{ label: 'Cancel', tone: 'ghost' }, { label: 'Mark verified', tone: 'primary', onClick: async () => {
      const s = str(src.value);
      if (!s) { err.textContent = 'Give the source you checked.'; src.focus(); return false; }
      const se = sourceError(s); if (se) { err.textContent = se; return false; }
      try { await api.post(`/colleges/${encodeURIComponent(c.id)}/verify`, { fields, source: s, note: str(note.value) || undefined }); ui.toast('Marked verified', 'good'); ctx.refresh?.(); return true; } catch (e) { err.textContent = e.message; return false; }
    } }],
  });
  if (!coarse()) setTimeout(() => src.focus(), 50);
  return true;
}

/** true on touch-first devices (no autofocus there, so the on-screen keyboard does not cover the dialog). */
function coarse() { return document.documentElement.dataset.pointer === 'coarse' || (typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches); }

export default { createCollege, editCollege, verifyFields };
