// Tech Drona portal — UI components (owned by the UI shell agent; signatures fixed by CONTRACT.md)
//
// STABLE SIGNATURES (full docs: redesign/components.md). Original components keep their CONTRACT.md signatures.
// Added in the 2026-11 redesign (all additive, all return HTMLElement unless noted):
//   dataTable({columns:[{key,label,render?,align?,sortable?,width?,primary?,hideOnPhone?,phoneLabel?}], rows, rowKey?,
//              sort?:{key,dir}, onSort?(key,dir), page?, pageSize?, total?, onPage?(page), onRowClick?(row,ev), rowHref?(row),
//              rowActions?(row)->[{label,icon?,tone?,onClick(row),hidden?,writeOnly?}], selectable?, onSelect?(rows),
//              empty?, loading?, error?, onRetry?, mobile?:'cards'|'scroll', cardSort?:false (no phone sort select), caption?, dense?})  -> el with el.update(patch)
//   pagination({page, pageSize, total, onPage(page), pageSizes?, onPageSize?(n), label?})
//   filterBar({search?:{key,placeholder,value,debounce?}, filters:[{key,label,type:'select'|'segmented'|'toggle',options,value?,allLabel?}],
//              values?, onChange(values, changedKey), actions?:[Node], showClear?})  -> el with .values() .set(v,{silent}) .clear()
//   statusChip(status, {label?, title?, size?})
//   progressBar(actual, target, {min?, max?, label?, size?, showNumbers?, unit?, status?})
//   kpi({label, value, sub?, tone?, icon?, href?, onClick?, help?, loading?, basis?}); kpiRow([kpi...])
//   verifiedBadge({state:'verified'|'unverified'|'missing', source?, date?, by?})
//   contactActions(phone, email, {compact?, whatsapp?, name?})
//   emptyState({title, text, action?, actions?, icon?, tone?})          (extended)
//   confirm({title, text?, body?, confirmLabel?, cancelLabel?, danger?, tone?}) -> Promise<boolean>   (extended)
//   formDialog({title, intro?, fields, values?, submitLabel?, cancelLabel?, wide?, danger?, onSubmit(values,{idempotencyKey,close}),
//               onChange?(values, form), footerNote?}) -> Promise<result|null>
//   pageHeader({title, sub?, eyebrow?, actions?, back?, scope?:bool, meta?, tabs?:[{label,href,active?,count?}]})   (extended)
//   linkTabs([{label, href, active?, count?}]); segmented({options:[{value,label,count?}], value, onChange, ariaLabel})
//   scopePill(); menu({label?, icon?, items:[{label,icon?,tone?,onClick,hidden?,writeOnly?}]}); writeOnly(node) -> node
//   getHashQuery() -> {}; setHashQuery(obj, {replace?:true}); canWrite() -> bool
//   Responsive system (2026-11 device pass, see devices/responsive.md): formFactor(), isPhone(), prefersReducedMotion(),
//   scroller(), listEmpty({filtered, noun, addLabel, onAdd, onClear}), hasFilters(values); dataTable column
//   {priority, minWidth, cardHidden, sticky} + options {cardTitle, cardSubtitle, cardMeta, cardBreakpoint};
//   filterBar {collapse}; linkTabs(items, {ariaLabel}); modal actions[i].align:'start'.
import { h, fmt, debounce } from './h.js';
import { getScope, scopeLabel, SCOPE_EVENT, canWrite } from '../state.js';

/* =========================================================================
   Form factor — <html data-form="phone|tablet|desktop" data-pointer="coarse|fine" data-short>
   phone   = width < 700, or a touch device whose short side is a phone's (landscape phones get phone chrome)
   tablet  = 700–1279 (nav rail)       desktop = ≥ 1280 (full sidebar)
   ========================================================================= */
const FF_EVENT = 'td:formfactor';
const mqCoarse = typeof matchMedia === 'function' ? matchMedia('(pointer: coarse)') : null;
let ffCurrent = null;
function computeForm() {
  const w = innerWidth; const ht = innerHeight;
  const coarse = !!(mqCoarse && mqCoarse.matches);
  const shortSide = Math.min(screen.width || w, screen.height || ht);
  const landscapePhone = coarse && (shortSide < 500 || (ht < 500 && w < 950));
  return w < 700 || landscapePhone ? 'phone' : w < 1280 ? 'tablet' : 'desktop';
}
function applyFormFactor() {
  const de = document.documentElement;
  const form = computeForm();
  de.dataset.form = form;
  de.dataset.pointer = mqCoarse && mqCoarse.matches ? 'coarse' : 'fine';
  if (innerHeight < 500) de.dataset.short = '1'; else delete de.dataset.short;
  if (form !== ffCurrent) {
    const prev = ffCurrent;
    ffCurrent = form;
    if (prev) dispatchEvent(new CustomEvent(FF_EVENT, { detail: { form, prev } }));
  }
}
if (typeof document !== 'undefined') {
  applyFormFactor();
  addEventListener('resize', applyFormFactor);
  addEventListener('orientationchange', () => setTimeout(applyFormFactor, 60));
  if (mqCoarse && mqCoarse.addEventListener) mqCoarse.addEventListener('change', applyFormFactor);
}
/** 'phone' | 'tablet' | 'desktop' (same rule as the CSS attribute) */
export function formFactor() { return ffCurrent || computeForm(); }
export const isPhone = () => formFactor() === 'phone';
export const FORMFACTOR_EVENT = FF_EVENT;
export const prefersReducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
/** the element that scrolls the page content (document on phones, the content panel elsewhere) */
export function scroller() {
  const p = document.querySelector('.td-panel');
  if (p && /(auto|scroll)/.test(getComputedStyle(p).overflowY)) return p;
  return document.scrollingElement || document.documentElement;
}

/* =========================================================================
   History-backed overlays: opening pushes a history entry so Android / browser Back closes the top overlay
   instead of leaving the page. Closing by X / Esc / backdrop pops that entry again.
   ========================================================================= */
const hist = { stack: [], pendingBack: 0, deferred: [], seq: 0, releasing: null };
function histDoPush(rec) {
  if (hist.pendingBack) { hist.deferred.push(rec); return; }
  try {
    const r = hist.releasing;
    if (r && history.state && history.state.tdOverlay === r.id && location.href === r.url) {
      // an overlay closed and another opened in the same moment (confirm → dialog): reuse its history entry
      clearTimeout(r.timer); hist.releasing = null;
      history.replaceState({ ...history.state, tdOverlay: rec.id }, '', location.href);
    } else {
      history.pushState({ ...(history.state || {}), tdOverlay: rec.id }, '', location.href);
    }
    rec.pushed = true; rec.url = location.href;
  } catch { rec.pushed = false; }
}
function histPush(onBack) {
  const rec = { id: `ov${++hist.seq}`, onBack, pushed: false, url: null, timer: null };
  hist.stack.push(rec);
  histDoPush(rec);
  return rec;
}
function histFlush(rec) {
  if (hist.releasing === rec) hist.releasing = null;
  if (!history.state || history.state.tdOverlay !== rec.id) return; // another entry is current (navigation / new overlay)
  if (location.href !== rec.url) { // the page changed its own URL while open (filters): keep it, drop the marker
    try { history.replaceState({ ...history.state, tdOverlay: undefined }, '', location.href); } catch { /* ignore */ }
    return;
  }
  hist.pendingBack++;
  history.back();
}
function histRelease(rec) {
  if (!rec) return;
  const i = hist.stack.indexOf(rec);
  if (i < 0) return;
  hist.stack.splice(i, 1);
  const d = hist.deferred.indexOf(rec);
  if (d >= 0) { hist.deferred.splice(d, 1); return; }
  if (!rec.pushed) return;
  // deferred one task: a link inside the overlay navigates synchronously first, then we must not go back
  if (hist.releasing) { clearTimeout(hist.releasing.timer); histFlush(hist.releasing); }
  hist.releasing = rec;
  rec.timer = setTimeout(() => histFlush(rec), 0);
}
if (typeof addEventListener === 'function') {
  addEventListener('popstate', () => {
    if (hist.pendingBack) {
      hist.pendingBack--;
      if (!hist.pendingBack) hist.deferred.splice(0).forEach(histDoPush);
      return;
    }
    const cur = history.state && history.state.tdOverlay;
    for (let i = hist.stack.length - 1; i >= 0; i--) {
      const r = hist.stack[i];
      if (r.id === cur) break;
      if (!r.pushed) continue;
      hist.stack.splice(i, 1);
      r.pushed = false;
      try { r.onBack(); } catch (e) { console.error(e); }
    }
  });
}
/** For shell overlays that are not ui.modal/drawer (phone search, nav drawer): returns release() */
export function backClosable(onBack) { const rec = histPush(onBack); return () => histRelease(rec); }

/* =========================================================================
   Icons — 24px stroke set (currentColor). icon(name) -> <span class="td-icon">
   ========================================================================= */
const P = {
  map: '<path d="M9 4 3.5 6v14L9 18l6 2 5.5-2V4L15 6 9 4Z"/><path d="M9 4v14M15 6v14"/>',
  dashboard: '<rect x="3.5" y="3.5" width="7" height="9" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="5" rx="1.5"/><rect x="13.5" y="11.5" width="7" height="9" rx="1.5"/><rect x="3.5" y="15.5" width="7" height="5" rx="1.5"/>',
  college: '<path d="M3 9.5 12 4l9 5.5"/><path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8"/><path d="M3 20.5h18"/>',
  branch: '<circle cx="6" cy="5.5" r="2.2"/><circle cx="6" cy="18.5" r="2.2"/><circle cx="18" cy="8" r="2.2"/><path d="M6 7.7v8.6M18 10.2c0 4-6 3.3-11 6.6"/>',
  people: '<circle cx="9" cy="8" r="3.5"/><path d="M2.8 20c.6-3.6 3.1-5.5 6.2-5.5s5.6 1.9 6.2 5.5"/><path d="M16 4.8a3.3 3.3 0 0 1 0 6.4M18 14.8c1.9.7 3 2.4 3.3 5.2"/>',
  lead: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c.8-4 3.8-6.2 7.5-6.2s6.7 2.2 7.5 6.2"/><path d="m12 2.2.7 1.3 1.4.2-1 1 .2 1.4-1.3-.7-1.3.7.2-1.4-1-1 1.4-.2Z" fill="currentColor" stroke="none"/>',
  ambassador: '<circle cx="10" cy="8" r="3.6"/><path d="M3.5 20c.7-3.7 3.3-5.8 6.5-5.8 1.4 0 2.6.4 3.6 1.1"/><path d="m17.5 13.5 1.1 2.3 2.4.3-1.8 1.7.5 2.4-2.2-1.2-2.2 1.2.5-2.4-1.8-1.7 2.4-.3Z"/>',
  target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/>',
  followup: '<path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4v4.5h4.5"/><path d="M12 8v4.2l2.8 1.8"/>',
  exam: '<rect x="4.5" y="3.5" width="15" height="17" rx="2"/><path d="M8.5 8h7M8.5 12h7M8.5 16h4"/>',
  data: '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v6.5c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V5.5"/><path d="M4.5 12v6.5c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V12"/>',
  audit: '<path d="M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-10Z"/><path d="M14 3.5v5h5"/><path d="m9 14.5 2 2 4-4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  filter: '<path d="M4 5h16M7 12h10M10 19h4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  edit: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6"/><path d="M5.5 7 6.5 19a2 2 0 0 0 2 1.8h7a2 2 0 0 0 2-1.8L18.5 7M9 7V4.5h6V7"/>',
  phone: '<path d="M5 4h3.5l1.7 4.3-2.2 1.4a11 11 0 0 0 6.3 6.3l1.4-2.2L20 15.5V19a1.5 1.5 0 0 1-1.6 1.5A16 16 0 0 1 3.5 5.6 1.5 1.5 0 0 1 5 4Z"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 6.5 8.5 6 8.5-6"/>',
  link: '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1"/>',
  warn: '<path d="M10.3 4.2 2.8 17.5A2 2 0 0 0 4.5 20.5h15a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z"/><path d="M12 9.5v4M12 17h.01"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  'chevron-left': '<path d="m15 6-6 6 6 6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c.8-4 3.8-6.2 7.5-6.2s6.7 2.2 7.5 6.2"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8h.01"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1" fill="currentColor"/><circle cx="4.5" cy="12" r="1" fill="currentColor"/><circle cx="4.5" cy="18" r="1" fill="currentColor"/>',
  more: '<circle cx="5.5" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="18.5" cy="12" r="1.4" fill="currentColor"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
  refresh: '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v4.5h-4.5"/>',
  offline: '<path d="M3 3l18 18"/><path d="M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 4.2-2.5M19 13a10 10 0 0 0-2-1.6M2 9.5a15 15 0 0 1 4.5-2.8M22 9.5A15 15 0 0 0 11 5.5"/><path d="M12 20h.01"/>',
  sparkle: '<path d="M12 3.5 13.8 9l5.7 1.8-5.7 1.8L12 18.5l-1.8-5.9L4.5 10.8 10.2 9Z"/>',
  home: '<path d="M4 10.5 12 4l8 6.5V19a1.5 1.5 0 0 1-1.5 1.5H15v-6H9v6H5.5A1.5 1.5 0 0 1 4 19Z"/>',
  analytics: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  palette: '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.2 0 1.8-.8 1.8-1.7 0-1.2-1-1.5-1-2.6 0-1 .8-1.7 1.8-1.7h2a3.9 3.9 0 0 0 3.9-3.9c0-4-3.8-7.1-8.5-7.1Z"/><circle cx="7.5" cy="11" r="1.2" fill="currentColor"/><circle cx="10.5" cy="7.2" r="1.2" fill="currentColor"/><circle cx="15" cy="7.5" r="1.2" fill="currentColor"/>',
  logout: '<path d="M15 4h3.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H15"/><path d="M10 16.5 5.5 12 10 7.5M5.5 12H15"/>',
};
const ALIASES = { x: 'close', 'chevron-right': 'chevron', alert: 'warn', calendar: 'exam', team: 'people', overview: 'map' };

export function icon(name, opts = {}) {
  const key = P[name] ? name : (ALIASES[name] || 'info');
  const size = opts.size || 20;
  return h('span', {
    class: ['td-icon', opts.class],
    'aria-hidden': 'true',
    html: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" focusable="false">${P[key]}</svg>`,
  });
}
export const iconNames = Object.keys(P);

/* =========================================================================
   Small helpers
   ========================================================================= */
const toNode = (x) => (x instanceof Node ? x : (x === null || x === undefined ? document.createTextNode('') : document.createTextNode(String(x))));
let uidN = 0;
const uid = (p = 'td') => `${p}-${++uidN}`;

/** button({label, icon, tone:'primary'|'secondary'|'ghost'|'danger'|'accent', size:'sm'|'md', onClick, type, title, disabled}) */
export function button({ label, icon: ic, tone = 'secondary', size, onClick, type = 'button', title, disabled, ariaLabel } = {}) {
  return h('button', {
    type, class: ['td-btn', `td-btn--${tone}`, size && `td-btn--${size}`, !label && 'td-btn--icon'],
    onClick, title: title || (!label ? ariaLabel : undefined), disabled, 'aria-label': ariaLabel || (!label ? title : undefined),
  }, ic ? icon(ic, { size: size === 'sm' ? 16 : 18 }) : null, label ? h('span', null, label) : null);
}

/** Loading placeholder. skeleton(lines=3) */
export function skeleton(lines = 3, { card = true } = {}) {
  const el = h('div', { class: ['td-skeleton', card && 'td-card'], 'aria-busy': 'true', 'aria-label': 'Loading' });
  el.append(h('div', { class: 'td-skel td-skel--title' }));
  for (let i = 0; i < lines; i++) el.append(h('div', { class: 'td-skel', style: { width: `${92 - ((i * 17) % 35)}%` } }));
  return el;
}

/* =========================================================================
   Provenance + values
   ========================================================================= */
const BASIS = {
  verified: { label: 'Verified', icon: 'check', cls: 'verified', tip: 'Verified — confirmed from an official or first-hand source.' },
  estimated: { label: '≈ Estimated', icon: null, cls: 'estimated', tip: 'Estimated — calculated from other known numbers (for example intake × 4). Treat it as approximate.' },
  pending: { label: 'Pending verification', icon: null, cls: 'pending', tip: 'Pending — not yet known or not yet checked. Do not rely on this value.' },
};

export function provenance(basis) {
  const b = BASIS[basis] || BASIS.pending;
  return h('span', { class: ['td-prov', `td-prov--${b.cls}`], title: b.tip, role: 'note', 'aria-label': b.tip },
    b.icon ? icon(b.icon, { size: 12 }) : null, h('span', null, b.label));
}

export function valueWithBasis(vb, fmtFn = fmt.num) {
  const v = vb && typeof vb === 'object' ? vb.value : vb;
  const basis = vb && typeof vb === 'object' ? vb.basis : null;
  const unknown = v === null || v === undefined || Number.isNaN(v);
  return h('span', { class: ['td-vb', unknown && 'td-vb--unknown'] },
    h('span', { class: 'td-vb__value td-num' }, unknown ? '—' : fmtFn(v)),
    provenance(unknown ? 'pending' : (basis || 'pending')));
}

/* =========================================================================
   Badges
   ========================================================================= */
const TONES = ['neutral', 'good', 'warn', 'bad', 'info', 'brand'];
export function badge(text, tone = 'neutral') {
  return h('span', { class: ['td-badge', `td-badge--${TONES.includes(tone) ? tone : 'neutral'}`] }, text);
}

const STATUS = {
  exam_state: {
    in_exams: ['Exams in progress', 'bad'],
    exams_soon: ['Exams soon', 'warn'],
    clear: ['No exams — good time', 'good'],
    unknown: ['Exam dates unknown', 'neutral'],
  },
  op_status: {
    operational: ['Operational', 'good'],
    possibly_closed: ['Possibly closed', 'warn'],
    closed: ['Closed', 'bad'],
    pending: ['Status pending', 'neutral'],
  },
  on_track: {
    on_track: ['On track', 'good'],
    behind: ['Behind', 'bad'],
    no_target: ['No target', 'neutral'],
  },
  followup: {
    open: ['Open', 'info'],
    overdue: ['Overdue', 'bad'],
    done: ['Done', 'good'],
  },
  person_status: {
    active: ['Active', 'good'],
    onboarding: ['Onboarding', 'info'],
    inactive: ['Inactive', 'neutral'],
  },
  diagnosis: {
    ambassador_gap: ['Need ambassadors', 'bad'],
    low_outreach: ['Low outreach', 'warn'],
    low_conversion: ['Low conversion', 'warn'],
    unrealistic_target: ['Target too high', 'warn'],
    behind_pace: ['Behind pace', 'warn'],
    exams: ['Exams', 'info'],
    data: ['Data gaps', 'neutral'],
    other: ['Other', 'neutral'],
  },
};
const DIAG_TIPS = {
  ambassador_gap: 'At least one relevant branch has no active ambassador.',
  low_outreach: 'Fewer students reached than the pace needs.',
  low_conversion: 'Students are being reached but few are enrolling.',
  unrealistic_target: 'Target is more than half of the eligible students.',
  behind_pace: 'Enrolments are behind the expected pace for the deadline.',
};

export function statusBadge(kind, value) {
  let v = value;
  if (kind === 'on_track') {
    if (v === true) v = 'on_track';
    else if (v === false) v = 'behind';
    else if (v === null || v === undefined || v === '') v = 'no_target';
  }
  if (kind === 'op_status' && !v) v = 'pending';
  if (kind === 'exam_state' && !v) v = 'unknown';
  const map = STATUS[kind] || {};
  const hit = map[v];
  if (!hit) {
    if (v === null || v === undefined || v === '') return h('span', { class: 'td-badge td-badge--ghost' }, '—');
    return badge(String(v).replace(/_/g, ' '), 'neutral');
  }
  const el = h('span', { class: ['td-badge', `td-badge--${hit[1]}`, 'td-badge--dot'], dataset: { kind, value: v } }, hit[0]);
  if (kind === 'diagnosis' && DIAG_TIPS[v]) el.title = DIAG_TIPS[v];
  return el;
}

/* =========================================================================
   Progress
   ========================================================================= */
export function progress({ target, done, size = 'md', tone } = {}) {
  const d = Number(done) || 0;
  const hasTarget = target !== null && target !== undefined && Number(target) > 0;
  if (!hasTarget) {
    return h('div', { class: ['td-progress', `td-progress--${size}`, 'td-progress--none'] },
      h('div', { class: 'td-progress__meta' },
        h('span', { class: 'td-progress__nums td-num' }, h('strong', null, fmt.num(d)), ' enrolled'),
        h('span', { class: 'td-progress__pct td-muted' }, 'No target set')),
      h('div', { class: 'td-progress__track' }));
  }
  const t = Number(target);
  const pct = d / t;
  const tn = tone || (pct >= 1 ? 'good' : pct >= 0.6 ? 'good' : pct >= 0.3 ? 'warn' : 'bad');
  const w = Math.max(0, Math.min(1, pct)) * 100;
  return h('div', { class: ['td-progress', `td-progress--${size}`, `td-progress--${tn}`] },
    h('div', { class: 'td-progress__meta' },
      h('span', { class: 'td-progress__nums td-num' }, h('strong', null, fmt.num(d)), h('span', { class: 'td-muted' }, ` / ${fmt.num(t)}`)),
      h('span', { class: 'td-progress__pct td-num' }, fmt.pct(pct))),
    h('div', {
      class: 'td-progress__track', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(t), 'aria-valuenow': String(d),
      'aria-label': `${fmt.num(d)} enrolled of ${fmt.num(t)} target (${fmt.pct(pct)})`,
    }, h('div', { class: 'td-progress__bar', style: { width: `${w}%` } })));
}

/* =========================================================================
   Stat card
   ========================================================================= */
export function statCard({ label, value, sub, basis, tone, icon: ic, onClick } = {}) {
  const tag = onClick ? 'button' : 'div';
  const unknown = value === null || value === undefined;
  return h(tag, { class: ['td-stat', tone && `td-stat--${tone}`, onClick && 'td-stat--action'], type: onClick ? 'button' : undefined, onClick },
    h('div', { class: 'td-stat__head' },
      ic ? h('span', { class: 'td-stat__icon' }, icon(ic, { size: 18 })) : null,
      h('span', { class: 'td-stat__label' }, label),
      onClick ? icon('chevron', { size: 16, class: 'td-stat__go' }) : null),
    h('div', { class: 'td-stat__value td-num' }, unknown ? '—' : toNode(value)),
    (sub || basis) ? h('div', { class: 'td-stat__sub' }, sub ? h('span', null, toNode(sub)) : null, basis ? provenance(unknown ? 'pending' : basis) : null) : null);
}

/* =========================================================================
   Table — client-side sort, sticky header, card mode in narrow containers
   ========================================================================= */
function sortVal(v) {
  if (v && typeof v === 'object' && 'value' in v) v = v.value;
  if (typeof v === 'boolean') return v ? 1 : 0;
  return v;
}

export function table({ columns = [], rows = [], onRowClick, empty } = {}) {
  let sortKey = null;
  let sortDir = 1;
  const wrap = h('div', { class: 'td-table-wrap' });
  const scroller = h('div', { class: 'td-table-scroll', tabindex: '0', role: 'region', 'aria-label': 'Table' });
  const tbl = h('table', { class: ['td-table', onRowClick && 'td-table--click'] });
  const thead = h('thead');
  const tbody = h('tbody');
  tbl.append(thead, tbody);
  scroller.append(tbl);
  wrap.append(scroller);

  const headRow = h('tr');
  columns.forEach((c) => {
    const sortable = c.sortable !== false && !!c.key;
    const th = h('th', { scope: 'col', class: [c.align && `td-al-${c.align}`], 'aria-sort': 'none' });
    if (sortable) {
      const btn = h('button', { type: 'button', class: 'td-th-sort' }, h('span', null, c.label), h('span', { class: 'td-th-sort__ind', 'aria-hidden': 'true' }));
      btn.addEventListener('click', () => {
        if (sortKey === c.key) sortDir = -sortDir; else { sortKey = c.key; sortDir = 1; }
        [...headRow.children].forEach((x) => x.setAttribute('aria-sort', 'none'));
        th.setAttribute('aria-sort', sortDir === 1 ? 'ascending' : 'descending');
        renderBody();
      });
      th.append(btn);
    } else th.append(c.label || '');
    headRow.append(th);
  });
  thead.append(headRow);

  function sorted() {
    if (!sortKey) return rows;
    const coll = new Intl.Collator('en-IN', { numeric: true, sensitivity: 'base' });
    return [...rows].sort((a, b) => {
      const x = sortVal(a[sortKey]);
      const y = sortVal(b[sortKey]);
      const xn = x === null || x === undefined || x === '';
      const yn = y === null || y === undefined || y === '';
      if (xn && yn) return 0;
      if (xn) return 1; // nulls last regardless of direction
      if (yn) return -1;
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * sortDir;
      return coll.compare(String(x), String(y)) * sortDir;
    });
  }

  function renderBody() {
    tbody.textContent = '';
    if (!rows || !rows.length) {
      wrap.classList.add('td-table-wrap--empty');
      const e = empty instanceof Node ? empty : emptyState({ title: typeof empty === 'string' ? empty : 'Nothing here yet', text: '' });
      tbody.append(h('tr', { class: 'td-table-empty' }, h('td', { colspan: String(columns.length || 1) }, e)));
      return;
    }
    wrap.classList.remove('td-table-wrap--empty');
    for (const row of sorted()) {
      const tr = h('tr');
      if (onRowClick) {
        tr.tabIndex = 0;
        tr.addEventListener('click', (ev) => { if (ev.target.closest('a,button,input,select,textarea,label')) return; onRowClick(row, ev); });
        tr.addEventListener('keydown', (ev) => { if ((ev.key === 'Enter' || ev.key === ' ') && ev.target === tr) { ev.preventDefault(); onRowClick(row, ev); } });
      }
      columns.forEach((c, i) => {
        let content;
        if (c.render) content = c.render(row);
        else {
          const v = row[c.key];
          content = v && typeof v === 'object' && 'value' in v ? valueWithBasis(v) : (v === null || v === undefined || v === '' ? '—' : (typeof v === 'number' ? fmt.num(v) : String(v)));
        }
        tr.append(h('td', { class: [c.align && `td-al-${c.align}`, i === 0 && 'td-td-primary', typeof row[c.key] === 'number' && 'td-num'], 'data-label': c.label || '' }, toNode(content)));
      });
      tbody.append(tr);
    }
  }
  renderBody();
  return wrap;
}

/* =========================================================================
   Tabs (ARIA, arrow-key navigation)
   ========================================================================= */
/** Edge-fade + "scroll the active item into view (horizontally only)" for any horizontal strip. */
export function scrollStrip(el, activeSel) {
  const sync = () => {
    const max = el.scrollWidth - el.clientWidth;
    el.classList.toggle('td-strip--l', el.scrollLeft > 2);
    el.classList.toggle('td-strip--r', max > 2 && el.scrollLeft < max - 2);
  };
  const center = () => {
    const a = activeSel && el.querySelector(activeSel);
    if (a && el.scrollWidth > el.clientWidth) {
      const left = a.offsetLeft - (el.clientWidth - a.offsetWidth) / 2;
      el.scrollLeft = Math.max(0, left);
    }
    sync();
  };
  el.classList.add('td-strip');
  el.addEventListener('scroll', sync, { passive: true });
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => sync()).observe(el);
  requestAnimationFrame(center);
  el.centerActive = center;
  return el;
}

export function tabs({ tabs: list = [], active, onChange } = {}) {
  const id = uid('tabs');
  let current = active && list.some((t) => t.id === active) ? active : list[0] && list[0].id;
  const root = h('div', { class: 'td-tabs' });
  const bar = scrollStrip(h('div', { class: 'td-tabs__list', role: 'tablist' }), '.td-tab.is-active');
  const panel = h('div', { class: 'td-tabs__panel', role: 'tabpanel', tabindex: '0' });
  const btns = list.map((t) => {
    const b = h('button', {
      type: 'button', role: 'tab', id: `${id}-${t.id}`, class: 'td-tab', 'aria-controls': `${id}-panel`, dataset: { tab: t.id },
    }, h('span', null, t.label), (t.count !== undefined && t.count !== null) ? h('span', { class: 'td-tab__count td-num' }, fmt.num(t.count)) : null);
    b.addEventListener('click', () => select(t.id, true));
    return b;
  });
  panel.id = `${id}-panel`;
  bar.addEventListener('keydown', (e) => {
    const i = btns.indexOf(document.activeElement);
    if (i < 0) return;
    let n = null;
    if (e.key === 'ArrowRight') n = (i + 1) % btns.length;
    else if (e.key === 'ArrowLeft') n = (i - 1 + btns.length) % btns.length;
    else if (e.key === 'Home') n = 0;
    else if (e.key === 'End') n = btns.length - 1;
    if (n !== null) { e.preventDefault(); btns[n].focus(); select(list[n].id, true); }
  });
  bar.append(...btns);
  root.append(bar, panel);

  let token = 0;
  async function select(tid, user) {
    if (user && tid === current && panel.childNodes.length) return;
    current = tid;
    btns.forEach((b, i) => {
      const on = list[i].id === tid;
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
      b.classList.toggle('is-active', on);
    });
    if (bar.centerActive) requestAnimationFrame(bar.centerActive);
    panel.setAttribute('aria-labelledby', `${id}-${tid}`);
    const t = list.find((x) => x.id === tid);
    const my = ++token;
    panel.textContent = '';
    if (t && t.render) {
      try {
        let out = t.render(panel);
        if (out && typeof out.then === 'function') { panel.append(skeleton(3, { card: false })); out = await out; if (my !== token) return; panel.textContent = ''; }
        if (out instanceof Node) panel.append(out);
      } catch (err) {
        if (my !== token) return;
        panel.textContent = '';
        panel.append(errorCard({ title: 'This tab could not load', error: err }));
      }
    }
    if (user && onChange) onChange(tid);
  }
  select(current, false);
  root.select = (tid) => select(tid, false);
  return root;
}

/* =========================================================================
   Overlays — modal + drawer share a focus-trap stack
   ========================================================================= */
const overlayStack = [];
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

function trapKeydown(e) {
  const top = overlayStack[overlayStack.length - 1];
  if (!top) return;
  if (document.querySelector('.td-login')) return; // the sign-in screen sits above open dialogs (session expiry) and owns the keyboard
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); top.close(); return; }
  if (e.key !== 'Tab') return;
  const f = [...top.panel.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null || x === document.activeElement);
  if (!f.length) { e.preventDefault(); top.panel.focus(); return; }
  const first = f[0];
  const last = f[f.length - 1];
  if (!top.panel.contains(document.activeElement)) { e.preventDefault(); first.focus(); return; }
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

function openOverlay({ kind, title, body, footer, onClose, wide }) {
  const titleId = uid('dlg');
  const returnTo = document.activeElement;
  const closeBtn = button({ icon: 'close', tone: 'ghost', ariaLabel: 'Close' });
  const bodyEl = h('div', { class: `td-${kind}__body` }, body instanceof Node ? body : (body !== undefined && body !== null ? h('p', null, String(body)) : null));
  const panel = h('div', {
    class: [`td-${kind}`, wide && `td-${kind}--wide`], role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId, tabindex: '-1',
  },
  kind === 'drawer' ? h('div', { class: 'td-drawer__grab', 'aria-hidden': 'true' }) : null,
  h('header', { class: `td-${kind}__head` }, h('h2', { id: titleId, class: `td-${kind}__title` }, title || ''), closeBtn),
  bodyEl,
  footer || null);
  const backdrop = h('div', { class: ['td-overlay', `td-overlay--${kind}`] }, panel);
  if (body instanceof Element && (body.matches('form, .td-formdlg') || body.querySelector('form'))) panel.classList.add(`td-${kind}--form`);
  let closed = false;
  let histRec = null;
  const entry = {
    panel,
    close() {
      if (closed) return;
      closed = true;
      histRelease(histRec);
      const i = overlayStack.indexOf(entry);
      if (i >= 0) overlayStack.splice(i, 1);
      if (!overlayStack.length) { document.removeEventListener('keydown', trapKeydown, true); document.documentElement.classList.remove('td-noscroll'); }
      backdrop.classList.add('is-leaving');
      const done = () => backdrop.remove();
      const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (reduce) done(); else setTimeout(done, 180);
      if (returnTo && typeof returnTo.focus === 'function' && document.contains(returnTo)) returnTo.focus();
      if (onClose) { try { onClose(); } catch (e) { console.error(e); } }
    },
  };
  closeBtn.addEventListener('click', () => entry.close());
  backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop) entry.close(); });
  if (!overlayStack.length) document.addEventListener('keydown', trapKeydown, true);
  overlayStack.push(entry);
  histRec = histPush(() => entry.close());
  document.documentElement.classList.add('td-noscroll');
  (document.getElementById('td-overlays') || document.body).append(backdrop);
  sheetSwipe(panel, () => entry.close());
  requestAnimationFrame(() => {
    backdrop.classList.add('is-open');
    // touch devices: do not pop the on-screen keyboard over a dialog the user has not read yet (unless a field asks for it)
    const explicit = bodyEl.querySelector('[autofocus]');
    const coarse = mqCoarse && mqCoarse.matches;
    const auto = explicit || (coarse ? null : bodyEl.querySelector('input:not([type=hidden]):not([type=checkbox]),select,textarea'));
    try { (auto || panel).focus({ preventScroll: !auto }); } catch { (auto || panel).focus(); }
  });
  return entry;
}

/** Phones: drag a sheet down by its grab handle / header to close it (threshold 80px or a quick flick). */
function sheetSwipe(panel, close) {
  const grips = [panel.querySelector('.td-drawer__grab'), panel.querySelector('.td-modal__head, .td-drawer__head')].filter(Boolean);
  let y0 = 0; let t0 = 0; let dy = 0; let active = false; let pid = null;
  const down = (e) => {
    if (formFactor() !== 'phone' || (e.pointerType === 'mouse' && e.button !== 0)) return;
    if (e.target.closest('button, a, input, select, textarea')) return;
    active = true; y0 = e.clientY; t0 = performance.now(); dy = 0; pid = e.pointerId;
    try { e.currentTarget.setPointerCapture(pid); } catch { /* ignore */ }
    panel.style.transition = 'none';
  };
  const move = (e) => {
    if (!active || e.pointerId !== pid) return;
    dy = Math.max(0, e.clientY - y0);
    panel.style.transform = dy ? `translateY(${dy}px)` : '';
  };
  const up = (e) => {
    if (!active || (e && e.pointerId !== pid)) return;
    active = false;
    panel.style.transition = '';
    const fast = dy > 30 && dy / Math.max(1, performance.now() - t0) > 0.6;
    if (dy > 80 || fast) close();
    else panel.style.transform = '';
  };
  grips.forEach((g) => {
    g.addEventListener('pointerdown', down);
    g.addEventListener('pointermove', move);
    g.addEventListener('pointerup', up);
    g.addEventListener('pointercancel', up);
    g.style.touchAction = 'none';
  });
}

/**
 * modal({title, body, actions:[{label, tone, onClick}]}) -> {close}
 * An action closes the modal after onClick unless onClick returns false (or a Promise resolving to false).
 * While a returned Promise is pending the buttons are disabled; a rejection keeps the modal open and shows a toast.
 */
export function modal({ title, body, actions = [], wide, onClose } = {}) {
  let entry;
  const acts = (actions || []).filter(Boolean);
  const footer = acts.length ? h('footer', { class: ['td-modal__foot', acts.length > 2 && 'td-modal__foot--many'] }) : null;
  if (footer) {
    acts.forEach((a) => {
      const tone = a.tone === 'brand' || a.tone === 'primary' ? 'primary' : a.tone === 'bad' || a.tone === 'danger' ? 'danger' : a.tone === 'ghost' ? 'ghost' : (a.tone || 'secondary');
      const b = button({ label: a.label, tone, icon: a.icon });
      if (a.align === 'start') b.classList.add('td-modal__start');
      b.addEventListener('click', async () => {
        if (!a.onClick) { entry.close(); return; }
        let r;
        try {
          r = a.onClick({ close: () => entry.close() });
          if (r && typeof r.then === 'function') {
            footer.querySelectorAll('button').forEach((x) => { x.disabled = true; });
            b.classList.add('is-busy');
            r = await r;
          }
        } catch (err) {
          toast(err && err.message ? err.message : 'Something went wrong', 'bad');
          r = false;
        } finally {
          footer.querySelectorAll('button').forEach((x) => { x.disabled = false; });
          b.classList.remove('is-busy');
        }
        if (r !== false) entry.close();
      });
      footer.append(b);
    });
  }
  entry = openOverlay({ kind: 'modal', title, body, footer, wide, onClose });
  if (acts.length <= 2 && !entry.panel.classList.contains('td-modal--form')) entry.panel.classList.add('td-modal--compact');
  return { close: () => entry.close(), el: entry.panel };
}

/** drawer({title, body, onClose}) -> {close}. Slides in from the right (bottom sheet on phones). */
/** Close every open modal/drawer (the router calls this when the page changes). */
export function closeOverlays() { [...overlayStack].reverse().forEach((o) => o.close()); }

export function drawer({ title, body, onClose, wide } = {}) {
  const entry = openOverlay({ kind: 'drawer', title, body, onClose, wide });
  return { close: () => entry.close(), el: entry.panel };
}

/** confirm({title, text?, body?, confirmLabel?, cancelLabel?, danger?, tone?}) -> Promise<boolean> */
export function confirm({ title = 'Are you sure?', text = '', body, confirmLabel = 'Confirm', cancelLabel = 'Cancel', tone, danger } = {}) {
  const t = tone || (danger === false ? 'primary' : 'danger');
  return new Promise((resolve) => {
    let answered = false;
    const content = h('div', { class: 'td-confirm' }, text ? h('p', { class: 'td-muted' }, toNode(text)) : null, body instanceof Node ? body : null);
    modal({
      title,
      body: content,
      actions: [
        { label: cancelLabel, tone: 'ghost', onClick: () => { answered = true; resolve(false); } },
        { label: confirmLabel, tone: t, onClick: () => { answered = true; resolve(true); } },
      ],
      onClose: () => { if (!answered) { answered = true; resolve(false); } },
    });
  });
}

/* =========================================================================
   Toast
   ========================================================================= */
function toastRegion() {
  let r = document.getElementById('td-toasts');
  if (!r) { r = h('div', { id: 'td-toasts', class: 'td-toasts' }); document.body.append(r); }
  return r;
}
export function toast(msg, tone = 'neutral') {
  const t = ['good', 'bad', 'warn', 'info', 'neutral', 'brand'].includes(tone) ? tone : 'neutral';
  const ic = { good: 'check', bad: 'warn', warn: 'warn', info: 'info', neutral: 'info', brand: 'sparkle' }[t];
  const el = h('div', { class: ['td-toast', `td-toast--${t}`], role: t === 'bad' ? 'alert' : 'status', 'aria-live': t === 'bad' ? 'assertive' : 'polite' },
    icon(ic, { size: 18 }), h('span', { class: 'td-toast__msg' }, String(msg ?? '')));
  const x = button({ icon: 'close', tone: 'ghost', size: 'sm', ariaLabel: 'Dismiss' });
  const kill = () => { el.classList.add('is-leaving'); setTimeout(() => el.remove(), 200); };
  x.addEventListener('click', kill);
  el.append(x);
  const region = toastRegion();
  // identical message already showing? replace it instead of stacking duplicates
  [...region.children].forEach((c) => { if (c.dataset.msg === String(msg ?? '')) c.remove(); });
  el.dataset.msg = String(msg ?? '');
  region.append(el);
  while (region.children.length > 4) region.firstElementChild.remove();
  let timer = setTimeout(kill, t === 'bad' ? 7000 : 4200);
  // pause while hovered / focused so people can read longer messages
  el.addEventListener('mouseenter', () => clearTimeout(timer));
  el.addEventListener('mouseleave', () => { timer = setTimeout(kill, 2500); });
}

/* =========================================================================
   Layout helpers
   ========================================================================= */
export function emptyState({ title = 'Nothing here yet', text = '', action, actions, icon: ic = 'sparkle', tone } = {}) {
  const mk = (x) => (x instanceof Node ? x : x && x.label ? button({ label: x.label, icon: x.icon === undefined ? 'plus' : x.icon, tone: x.tone || 'primary', onClick: x.onClick }) : null);
  const acts = [action, ...(actions || [])].map(mk).filter(Boolean);
  return h('div', { class: ['td-empty', tone && `td-empty--${tone}`] },
    h('div', { class: 'td-empty__icon' }, icon(ic, { size: 22 })),
    h('div', { class: 'td-empty__title' }, title),
    text ? h('p', { class: 'td-empty__text' }, toNode(text)) : null,
    acts.length ? h('div', { class: 'td-empty__action' }, acts) : null);
}

/** true when any filter / search value is set (ignores false, '', null, [] and the listed keys) */
export function hasFilters(values = {}, { ignore = [] } = {}) {
  return Object.entries(values || {}).some(([k, v]) => !ignore.includes(k) && !(v === null || v === undefined || v === '' || v === false || (Array.isArray(v) && !v.length)));
}
/**
 * listEmpty — THE empty-state wording rule.
 *   filtered=false → "No <noun> yet" + "Add the first …" + add action (write-only)
 *   filtered=true  → "Nobody matches these filters" (people) / "No <noun> match these filters" + "Clear filters"
 */
export function listEmpty({ filtered = false, noun = 'records', people, addLabel, onAdd, onClear, text, icon: ic, first } = {}) {
  const isPeople = people !== undefined ? people : /people|person|team|lead|ambassador/i.test(noun);
  if (filtered) {
    return emptyState({
      icon: ic || 'filter',
      title: isPeople ? 'Nobody matches these filters' : `No ${noun} match these filters`,
      text: text || 'Try a different search, or clear the filters to see everything.',
      action: onClear ? { label: 'Clear filters', icon: 'close', tone: 'secondary', onClick: onClear } : null,
    });
  }
  const add = onAdd && addLabel && canWrite() ? writeOnly(button({ label: addLabel, icon: 'plus', tone: 'primary', onClick: onAdd })) : null;
  return emptyState({
    icon: ic || 'sparkle',
    title: `No ${noun} yet`,
    text: text || (first ? `Add the first ${first}.` : addLabel ? `${addLabel.replace(/^Add (an? |the )?/i, 'Add the first ')}.` : ''),
    action: add,
  });
}

export function section({ title, actions, body, sub } = {}) {
  const acts = [].concat(actions || []).filter(Boolean).map((a) => (a instanceof Node ? a : button({ label: a.label, icon: a.icon, tone: a.tone || 'secondary', size: 'sm', onClick: a.onClick })));
  return h('section', { class: 'td-section td-card' },
    (title || acts.length) ? h('header', { class: 'td-section__head' },
      h('div', null, title ? h('h2', { class: 'td-section__title' }, toNode(title)) : null, sub ? h('div', { class: 'td-section__sub' }, toNode(sub)) : null),
      acts.length ? h('div', { class: 'td-section__actions' }, acts) : null) : null,
    h('div', { class: 'td-section__body' }, [].concat(body).filter((x) => x !== null && x !== undefined).map(toNode)));
}

export function kv(pairs = []) {
  return h('dl', { class: 'td-kv' }, pairs.filter(Boolean).map(([k, v]) => [
    h('dt', null, k),
    h('dd', null, v === null || v === undefined || v === '' ? h('span', { class: 'td-muted' }, '—') : toNode(v)),
  ]));
}

/** errorCard({title, text, error, retry}) — friendly failure panel */
export function errorCard({ title = 'Something went wrong', text, error, retry } = {}) {
  const offline = error && error.status === 0;
  return h('div', { class: 'td-error td-card', role: 'alert' },
    h('div', { class: 'td-error__icon' }, icon(offline ? 'offline' : 'warn', { size: 22 })),
    h('div', { class: 'td-error__main' },
      h('div', { class: 'td-error__title' }, offline ? 'Server unreachable' : title),
      h('p', { class: 'td-muted' }, text || (offline ? 'The portal server is not responding. Check that it is running, then try again.' : 'This part of the portal could not be shown right now. Other sections still work.')),
      error && error.message ? h('details', { class: 'td-error__details' }, h('summary', null, 'Technical details'), h('code', null, String(error.message))) : null,
      retry ? h('div', { class: 'td-error__actions' }, button({ label: 'Try again', icon: 'refresh', tone: 'secondary', onClick: retry })) : null));
}

/* =========================================================================
   Form
   ========================================================================= */
function normOptions(options = []) {
  return options.map((o) => {
    if (Array.isArray(o)) return { value: o[0], label: String(o[1] ?? o[0]) }; // [[value, label]] pairs
    return o !== null && typeof o === 'object' ? { value: o.value ?? o.id, label: o.label ?? o.name ?? String(o.value ?? o.id) } : { value: o, label: String(o) };
  });
}

/**
 * form({fields, submitLabel, onSubmit(values) -> Promise, onCancel?, cancelLabel?})
 * Empty inputs become null; numbers become Number; multiselect returns an array of option values.
 * If onSubmit throws an ApiError with .fields, messages are shown under the matching inputs.
 */
export function form({ fields = [], submitLabel = 'Save', onSubmit, onCancel, cancelLabel = 'Cancel' } = {}) {
  const f = h('form', { class: 'td-form', novalidate: true });
  const getters = {};
  const errs = {};
  const inputs = {};
  const grid = h('div', { class: 'td-form__grid' });
  const formErr = h('div', { class: 'td-form__error', role: 'alert', hidden: true });

  fields.forEach((fd) => {
    const id = uid('f');
    const errId = `${id}-err`;
    const helpId = `${id}-help`;
    const full = fd.type === 'textarea' || fd.type === 'multiselect' || fd.full;
    const wrap = h('div', { class: ['td-field', full && 'td-field--full', fd.type === 'checkbox' && 'td-field--check'] });
    const label = h('label', { for: id, class: 'td-field__label' }, fd.label || fd.name, fd.required ? h('span', { class: 'td-field__req', 'aria-hidden': 'true' }, ' *') : null);
    const described = [fd.help ? helpId : null, errId].filter(Boolean).join(' ');
    let control;
    const opts = normOptions(fd.options || []);

    switch (fd.type) {
      case 'textarea':
        control = h('textarea', { id, name: fd.name, class: 'td-input', rows: fd.rows || 3, placeholder: fd.placeholder, 'aria-describedby': described });
        control.value = fd.value ?? '';
        getters[fd.name] = () => (control.value.trim() === '' ? null : control.value);
        break;
      case 'select': {
        control = h('select', { id, name: fd.name, class: 'td-input td-select', 'aria-describedby': described });
        control.append(h('option', { value: '' }, fd.placeholder || (fd.required ? 'Choose…' : '— None —')));
        opts.forEach((o, i) => {
          const op = h('option', { value: String(i) }, o.label);
          if (fd.value !== undefined && fd.value !== null && String(o.value) === String(fd.value)) op.selected = true;
          control.append(op);
        });
        getters[fd.name] = () => (control.value === '' ? null : opts[Number(control.value)].value);
        break;
      }
      case 'multiselect': {
        const selected = new Set((fd.value || []).map(String));
        control = h('div', { class: 'td-multi', id, role: 'group', 'aria-labelledby': `${id}-lbl`, 'aria-describedby': described });
        label.removeAttribute('for');
        label.id = `${id}-lbl`;
        const list = h('div', { class: 'td-multi__list' });
        const countEl = h('span', { class: 'td-multi__count td-num' });
        const boxes = opts.map((o) => {
          const cb = h('input', { type: 'checkbox', value: String(o.value) });
          cb.checked = selected.has(String(o.value));
          cb.addEventListener('change', updCount);
          const row = h('label', { class: 'td-multi__opt', dataset: { text: o.label.toLowerCase() } }, cb, h('span', null, o.label));
          list.append(row);
          return { cb, o, row };
        });
        function updCount() { const n = boxes.filter((b) => b.cb.checked).length; countEl.textContent = n ? `${n} selected` : 'None selected'; }
        updCount();
        const top = h('div', { class: 'td-multi__top' });
        if (opts.length > 6) {
          const s = h('input', { type: 'search', class: 'td-input td-input--sm', placeholder: 'Search…', 'aria-label': `Search ${fd.label || fd.name}` });
          s.addEventListener('input', () => {
            const q = s.value.trim().toLowerCase();
            boxes.forEach((b) => { b.row.hidden = !!q && !b.row.dataset.text.includes(q); });
          });
          s.addEventListener('keydown', (e) => { if (e.key === 'Enter') e.preventDefault(); });
          top.append(s);
        }
        top.append(countEl);
        if (!opts.length) list.append(h('div', { class: 'td-muted td-multi__none' }, 'No options available'));
        control.append(top, list);
        getters[fd.name] = () => boxes.filter((b) => b.cb.checked).map((b) => b.o.value);
        break;
      }
      case 'checkbox': {
        control = h('input', { id, type: 'checkbox', name: fd.name, class: 'td-check', 'aria-describedby': described });
        control.checked = !!fd.value;
        getters[fd.name] = () => control.checked;
        break;
      }
      default: {
        const type = ['text', 'number', 'date', 'tel', 'email', 'password', 'url'].includes(fd.type) ? fd.type : 'text';
        control = h('input', {
          id, name: fd.name, type, class: 'td-input', placeholder: fd.placeholder, 'aria-describedby': described,
          inputmode: type === 'number' ? 'decimal' : undefined, min: fd.min, max: fd.max, step: fd.step ?? (type === 'number' ? 'any' : undefined),
          autocomplete: fd.autocomplete || (type === 'tel' ? 'tel' : type === 'email' ? 'email' : type === 'password' ? 'current-password' : 'off'),
          maxlength: fd.maxlength, required: fd.required ? true : undefined,
        });
        if (fd.value !== undefined && fd.value !== null) control.value = type === 'date' ? String(fd.value).slice(0, 10) : String(fd.value);
        getters[fd.name] = () => {
          const v = control.value.trim();
          if (v === '') return null;
          if (type === 'number') { const n = Number(v); return Number.isNaN(n) ? v : n; }
          return v;
        };
      }
    }
    if (fd.required && control.setAttribute) control.setAttribute('aria-required', 'true');
    if (fd.disabled) control.querySelectorAll ? control.querySelectorAll('input').forEach((x) => { x.disabled = true; }) : null;
    if (fd.disabled && 'disabled' in control) control.disabled = true;
    inputs[fd.name] = control;
    const err = h('div', { id: errId, class: 'td-field__error', 'aria-live': 'polite' });
    errs[fd.name] = err;
    if (fd.type === 'checkbox') wrap.append(h('div', { class: 'td-field__checkrow' }, control, label));
    else wrap.append(label, control);
    if (fd.help) wrap.append(h('div', { id: helpId, class: 'td-field__help' }, fd.help));
    wrap.append(err);
    if (fd.type === 'number' || fd.type === 'date' || fd.type === 'tel') control.classList.add('td-num');
    grid.append(wrap);
  });

  const submit = button({ label: submitLabel, tone: 'primary', type: 'submit' });
  const foot = h('div', { class: 'td-form__foot' });
  if (onCancel) foot.append(button({ label: cancelLabel, tone: 'ghost', onClick: onCancel }));
  foot.append(submit);
  f.append(formErr, grid, foot);

  function setError(name, msg) {
    const e = errs[name];
    const c = inputs[name];
    if (!e) return false;
    e.textContent = msg || '';
    e.parentElement.classList.toggle('has-error', !!msg);
    if (c) c.setAttribute('aria-invalid', msg ? 'true' : 'false');
    return true;
  }
  function clearErrors() { Object.keys(errs).forEach((k) => setError(k, '')); formErr.hidden = true; formErr.textContent = ''; }
  f.values = () => Object.fromEntries(Object.entries(getters).map(([k, g]) => [k, g()]));
  f.setErrors = (map) => Object.entries(map || {}).forEach(([k, v]) => setError(k, v));

  f.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (submit.disabled) return;
    clearErrors();
    const values = f.values();
    let firstBad = null;
    for (const fd of fields) {
      const v = values[fd.name];
      const missing = v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length) || (fd.type === 'checkbox' && false);
      if (fd.required && missing) { setError(fd.name, `${fd.label || fd.name} is required`); firstBad = firstBad || fd.name; continue; }
      if (fd.type === 'number' && v !== null && typeof v !== 'number') { setError(fd.name, 'Enter a number'); firstBad = firstBad || fd.name; continue; }
      if (fd.type === 'email' && v && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) { setError(fd.name, 'Enter a valid email address'); firstBad = firstBad || fd.name; }
    }
    if (firstBad) { focusField(firstBad); return; }
    if (!onSubmit) return;
    const orig = submit.querySelector('span').textContent;
    submit.disabled = true;
    submit.classList.add('is-busy');
    submit.querySelector('span').textContent = 'Saving…';
    f.setAttribute('aria-busy', 'true');
    try {
      await onSubmit(values);
    } catch (err) {
      const fe = err && err.fields && typeof err.fields === 'object' ? err.fields : {};
      let mapped = 0;
      let first = null;
      for (const [k, msg] of Object.entries(fe)) { if (setError(k, String(msg))) { mapped++; first = first || k; } }
      const unmapped = Object.entries(fe).filter(([k]) => !errs[k]).map(([k, v]) => `${k}: ${v}`);
      const msg = (err && err.message) || 'Could not save';
      if (!mapped || unmapped.length) { formErr.textContent = [msg, ...unmapped].join(' — '); formErr.hidden = false; }
      if (first) focusField(first);
      if (err && err.status !== 400) toast(msg, 'bad');
    } finally {
      submit.disabled = false;
      submit.classList.remove('is-busy');
      submit.querySelector('span').textContent = orig;
      f.removeAttribute('aria-busy');
    }
  });
  function focusField(name) {
    const c = inputs[name];
    if (!c) return;
    const t = c.matches && c.matches('input,select,textarea') ? c : c.querySelector('input');
    if (t) t.focus();
  }
  return f;
}


/* =========================================================================
   Additions (backward-compatible): page header, chip, spinner
   ========================================================================= */
/**
 * pageHeader({title, sub, eyebrow, actions:[Node|{label,icon,tone,onClick,writeOnly}], back:{href,label}, scope?:bool, meta?, tabs?})
 * One consistent page title block: h1 + supporting line + primary actions on the right; optional scope pill,
 * meta row (chips/badges) and route-level link tabs underneath.
 */
export function pageHeader({ title, sub, eyebrow, actions, back, scope, meta, tabs: tabList } = {}) {
  const acts = [].concat(actions || []).filter(Boolean).map((a) => {
    if (a instanceof Node) return a;
    const b = button({ label: a.label, icon: a.icon, tone: a.tone || 'secondary', onClick: a.onClick, ariaLabel: a.ariaLabel, disabled: a.disabled });
    return a.writeOnly ? writeOnly(b) : b;
  });
  const metaNodes = [].concat(meta || []).filter(Boolean).map(toNode);
  return h('header', { class: ['td-page-head', tabList && tabList.length && 'td-page-head--tabs'] },
    h('div', { class: 'td-page-head__row' },
      h('div', { class: 'td-page-head__main' },
        back && back.href ? h('a', { class: 'td-page-head__back', href: back.href }, icon('chevron-left', { size: 16 }), h('span', null, back.label || 'Back')) : null,
        eyebrow ? h('div', { class: 'td-page-head__eyebrow' }, toNode(eyebrow)) : null,
        h('h1', { class: 'td-page-head__title' }, toNode(title)),
        sub ? h('p', { class: 'td-page-head__sub' }, toNode(sub)) : null,
        (scope || metaNodes.length) ? h('div', { class: 'td-page-head__meta' }, scope ? scopePill() : null, metaNodes) : null),
      acts.length ? h('div', { class: 'td-page-head__actions' }, acts) : null),
    tabList && tabList.length ? linkTabs(tabList) : null);
}

/** chip({label, tone, active, onClick, onRemove, icon}) — filter/choice pill. Clickable when onClick is given. */
export function chip({ label, tone = 'neutral', active, onClick, onRemove, icon: ic } = {}) {
  const tag = onClick ? 'button' : 'span';
  const el = h(tag, {
    class: ['td-chip2', `td-chip2--${TONES.includes(tone) ? tone : 'neutral'}`, active && 'is-active'],
    type: onClick ? 'button' : undefined, onClick, 'aria-pressed': onClick && active !== undefined ? String(!!active) : undefined,
  }, ic ? icon(ic, { size: 14 }) : null, h('span', null, toNode(label)));
  if (onRemove) {
    const x = h('button', { type: 'button', class: 'td-chip2__x', 'aria-label': `Remove ${typeof label === 'string' ? label : 'filter'}` }, icon('close', { size: 12 }));
    x.addEventListener('click', (e) => { e.stopPropagation(); onRemove(); });
    el.append(x);
  }
  return el;
}

/** spinner({label}) — inline loading indicator with an accessible label. */
export function spinner({ label = 'Loading…', size = 'md' } = {}) {
  return h('span', { class: ['td-spinner', `td-spinner--${size}`], role: 'status' }, h('span', { class: 'td-spinner__ring', 'aria-hidden': 'true' }), h('span', { class: 'td-spinner__label' }, label));
}

/* =========================================================================
   Redesign components (2026-11) — additive; see the signature list at the top of this file
   ========================================================================= */
export { canWrite };
const isEmptyVal = (v) => v === null || v === undefined || v === '';

/** writeOnly(node) -> node. Hidden for read-only (viewer) sessions via body.td-readonly. */
export function writeOnly(node) { if (node && node.classList) node.classList.add('td-write-only'); return node; }

/* ---------- hash query helpers (persist list state in the URL) ---------- */
export function getHashQuery() {
  const i = location.hash.indexOf('?');
  return i < 0 ? {} : Object.fromEntries(new URLSearchParams(location.hash.slice(i + 1)));
}
/* D8 — Back undoes a filter / segment change: discrete changes push a history entry, typing replaces it.
   historyMode(prevQuery, nextQuery) decides for callers that pass {replace: 'auto'}: push when a key other than a free-text
   search key changed, the user is interacting (transient activation) and the page is not still settling after a route
   change (URL canonicalisation on first render must not add a Back step). */
const TEXT_KEYS = new Set(['q', 'search']);
let lastRouteAt = typeof performance !== 'undefined' ? performance.now() : 0;
if (typeof addEventListener === 'function') addEventListener('hashchange', () => { lastRouteAt = performance.now(); });
export function historyMode(prev, next) {
  const keys = new Set([...Object.keys(prev || {}), ...Object.keys(next || {})]);
  const changed = [...keys].filter((k) => String(prev[k] ?? '') !== String(next[k] ?? ''));
  if (!changed.length || changed.every((k) => TEXT_KEYS.has(k))) return 'replace';
  const active = typeof navigator !== 'undefined' && navigator.userActivation ? navigator.userActivation.isActive : true;
  if (!active || performance.now() - lastRouteAt < 400) return 'replace';
  return 'push';
}
/** setHashQuery({k: v|null}, {replace: true|false|'auto'}) — merges into the hash query without re-routing (replace/pushState). */
export function setHashQuery(obj = {}, { replace = true } = {}) {
  const raw = location.hash.replace(/^#/, '') || '/';
  const [path, qs] = raw.split('?');
  const q = new URLSearchParams(qs || '');
  const before = Object.fromEntries(q);
  for (const [k, v] of Object.entries(obj)) {
    if (isEmptyVal(v) || v === false || (Array.isArray(v) && !v.length)) q.delete(k);
    else q.set(k, Array.isArray(v) ? v.join(',') : String(v));
  }
  const str = q.toString().replace(/%2C/gi, ',');
  const url = `#${path}${str ? `?${str}` : ''}`;
  if (url === location.hash) return;
  if (replace === 'auto') replace = historyMode(before, Object.fromEntries(q)) === 'replace';
  try {
    if (replace) history.replaceState(history.state, '', url);
    else history.pushState(history.state ? { ...history.state, tdKey: undefined, tdOverlay: undefined } : null, '', url);
  } catch { location.hash = url; }
}

/* ---------- status chip ---------- */
/**
 * THE status vocabulary + colour map for targets / performance (F12). Every page (Home, Reports, Targets, Team, College,
 * Planner) takes labels, tones and explanations from here: ui.STATUS_META[status] -> {label, tone, tip}.
 */
const PERF_CHIP = {
  exceeded: ['Exceeded', 'good', 'Actual is above the target.'],
  met: ['Target met', 'good', 'Actual equals the target.'],
  on_track: ['On track', 'good', 'At least 80% of the enrolments expected by today (straight line from the period start).'],
  behind: ['Behind', 'bad', 'Less than 80% of the enrolments expected by today.'],
  too_early: ['Too early', 'info', 'Less than 7 days into the period — too early to judge pace.'],
  partial_target: ['Partly targeted', 'warn', 'Only some of the people or places in this group have a target, so it is not judged as a whole.'],
  zero_target: ['Target is 0', 'neutral', 'The target was set to 0 on purpose, so there is no %.'],
  no_target: ['No target', 'neutral', 'No target has been set for this period.'],
};
/** order used for summary cards and filters (cards must add up to the row count) */
export const PERF_STATUS_ORDER = ['behind', 'on_track', 'too_early', 'met', 'exceeded', 'partial_target', 'zero_target', 'no_target'];
const CHIP = {
  ...PERF_CHIP,
  assigned: ['Has lead', 'good', 'Reports to an active lead of the same college.'],
  unassigned: ['No lead', 'warn', 'This ambassador does not report to anyone yet.'],
  invalid_link: ['Lead invalid', 'bad', 'Reports to someone who is inactive, in another college or not a lead.'],
  active: ['Active', 'good'], onboarding: ['Onboarding', 'info'], inactive: ['Inactive', 'neutral'],
  verified: ['Verified', 'good', 'Confirmed from an official or first-hand source.'],
  unverified: ['Unverified', 'warn', 'Entered without a source — not yet checked.'],
  missing: ['Missing', 'neutral', 'No value recorded.'],
  open: ['Open', 'info'], overdue: ['Overdue', 'bad'], done: ['Done', 'good'],
};
const CHIP_ICON = { verified: 'check', met: 'check', exceeded: 'check', behind: 'warn', invalid_link: 'warn', overdue: 'clock', too_early: 'clock' };
export const STATUS_META = Object.freeze(Object.fromEntries(Object.entries(CHIP).map(([k, [label, tone, tip]]) => [k, Object.freeze({ label, tone, tip: tip || '' })])));
const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
/** {label, tone, tip} for any status key (unknown keys get a readable label and a neutral tone) */
export function statusMeta(status) {
  if (status && hasOwn(STATUS_META, status)) return STATUS_META[status];
  return { label: isEmptyVal(status) ? '—' : String(status).replace(/_/g, ' ').replace(/^\w/, (m) => m.toUpperCase()), tone: 'neutral', tip: '' };
}
/** shared % formatter (one rule, see fmt.pctPts): pctText(fraction), pctPoints(percent) */
export const pctText = (x) => fmt.pctOf(x);
export const pctPoints = (p) => fmt.pctPts(p);
export const plural = (n, one, many) => fmt.plural(n, one, many);

/* ---------- CSV (SEC-02): every export goes through these so spreadsheet formulas can never run ---------- */
/** one CSV cell: quoted when needed; a value starting with = + - @ TAB or CR is prefixed with ' (formula injection guard) */
export function csvCell(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') return Number.isFinite(v) ? String(v) : ''; // real numbers (incl. negatives) are not formulas
  let s = typeof v === 'object' ? JSON.stringify(v) : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) || /^\s|\s$/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
export const csvRow = (cells) => cells.map(csvCell).join(',');
/** downloadCsv('name.csv', [headerRow, ...rows]) — UTF-8 with BOM so Excel shows Telugu / ₹ correctly */
export function downloadCsv(filename, rows) {
  const text = '\ufeff' + rows.map(csvRow).join('\r\n');
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  const a = h('a', { href: url, download: filename, style: { display: 'none' } });
  document.body.append(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
}
/** statusChip(status, {label?, title?, size?}) — always text + colour (never colour alone). */
export function statusChip(status, { label, title, size } = {}) {
  const hit = status && hasOwn(CHIP, status) ? CHIP[status] : null;
  if (!hit && isEmptyVal(status)) return h('span', { class: 'td-badge td-badge--ghost' }, '—');
  const [lbl, tone, tip] = hit || [String(status).replace(/_/g, ' ').replace(/^\w/, (m) => m.toUpperCase()), 'neutral', ''];
  const ic = CHIP_ICON[status];
  return h('span', {
    class: ['td-badge', `td-badge--${tone}`, ic ? 'td-badge--icon' : 'td-badge--dot', size === 'sm' && 'td-badge--sm', 'td-status'],
    title: title || tip || undefined, dataset: { status: String(status) },
  }, ic ? icon(ic, { size: 12 }) : null, h('span', null, label || lbl));
}

/* ---------- progress bar: actual vs target (+ optional min / max) ---------- */
/** pct (1 decimal) or null when target is missing / 0 — never divides by zero. */
function pct1(a, t) { return t > 0 ? Math.round((a / t) * 1000) / 10 : null; }
export function progressBar(actual, target, { min, max, label, size = 'md', showNumbers = true, unit = '', status, pct } = {}) {
  const a = Number(actual) || 0;
  const hasT = !isEmptyVal(target) && Number.isFinite(Number(target));
  const t = hasT ? Number(target) : null;
  const cls = ['td-pbar', `td-pbar--${size}`];
  if (!hasT || t === 0) {
    return h('div', { class: [...cls, 'td-pbar--none'] },
      showNumbers ? h('div', { class: 'td-pbar__meta' },
        h('span', { class: 'td-pbar__nums td-num' }, label ? h('span', { class: 'td-pbar__label' }, label) : null, h('strong', null, fmt.num(a)), unit ? ` ${unit}` : ''),
        h('span', { class: 'td-pbar__pct td-muted' }, t === 0 ? 'Target is 0' : 'No target')) : null,
      h('div', { class: 'td-pbar__track', 'aria-hidden': 'true' }));
  }
  // the server's pct (a PERCENT) wins when given, so the bar and the "Achieved" figure next to it always agree (F11)
  if (status === 'partial_target') {
    // v4.1: only part of the group has a target — show the numbers, never a %, remaining or "over target" (not judged)
    return h('div', { class: [...cls, 'td-pbar--none', 'td-pbar--partial'] },
      showNumbers ? h('div', { class: 'td-pbar__meta' },
        h('span', { class: 'td-pbar__nums td-num' }, label ? h('span', { class: 'td-pbar__label' }, label) : null,
          h('strong', null, fmt.num(a)), h('span', { class: 'td-muted' }, ` / ${fmt.num(t)}`), unit ? h('span', { class: 'td-muted' }, ` ${unit}`) : null),
        h('span', { class: 'td-pbar__pct td-muted' }, 'Not judged')) : null,
      h('div', { class: 'td-pbar__track', 'aria-hidden': 'true' }));
  }
  const p = pct !== undefined && pct !== null && Number.isFinite(Number(pct)) ? Number(pct) : pct1(a, t);
  const hi = Number.isFinite(Number(max)) && Number(max) > t ? Number(max) : t;
  const scale = Math.max(hi, 1);
  const fill = Math.max(0, Math.min(1, a / scale)) * 100;
  const over = a > t;
  const remaining = Math.max(t - a, 0);
  const tone = status === 'behind' ? 'bad' : status === 'too_early' ? 'info' : (a >= t ? 'good' : status === 'on_track' ? 'good' : 'brand');
  const ticks = [];
  if (Number.isFinite(Number(min)) && min !== null && Number(min) > 0 && Number(min) < scale) ticks.push(['min', Number(min)]);
  if (hi > t) ticks.push(['target', t]);
  const pTxt = p === null ? '' : fmt.pctPts(p);
  const ariaTxt = `${fmt.num(a)} of ${fmt.num(t)}${unit ? ` ${unit}` : ''} (${pTxt})${over ? `, ${fmt.num(a - t)} over target` : `, ${fmt.num(remaining)} remaining`}`;
  return h('div', { class: [...cls, `td-pbar--${tone}`, over && 'is-over'] },
    showNumbers ? h('div', { class: 'td-pbar__meta' },
      h('span', { class: 'td-pbar__nums td-num' }, label ? h('span', { class: 'td-pbar__label' }, label) : null,
        h('strong', null, fmt.num(a)), h('span', { class: 'td-muted' }, ` / ${fmt.num(t)}`), unit ? h('span', { class: 'td-muted' }, ` ${unit}`) : null),
      h('span', { class: 'td-pbar__pct td-num' }, pTxt)) : null,
    h('div', {
      class: 'td-pbar__track', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(t), 'aria-valuenow': String(Math.min(a, t)), 'aria-label': ariaTxt,
    },
    h('div', { class: 'td-pbar__fill', style: { width: `${fill}%` } }),
    ticks.map(([k, v]) => h('span', { class: `td-pbar__tick td-pbar__tick--${k}`, style: { left: `${(v / scale) * 100}%` }, title: `${k === 'min' ? 'Minimum' : 'Target'}: ${fmt.num(v)}` }))),
    showNumbers ? h('div', { class: 'td-pbar__sub td-muted' },
      over ? h('span', { class: 'td-pbar__over' }, `+${fmt.num(a - t)} over target`) : h('span', null, `${fmt.num(remaining)} to go`),
      (!isEmptyVal(min) || !isEmptyVal(max)) ? h('span', null, fmt.range(min, max)) : null) : null);
}

/* ---------- KPI tile ---------- */
export function kpi({ label, value, sub, tone, icon: ic, href, onClick, help, loading, basis } = {}) {
  const tag = href ? 'a' : onClick ? 'button' : 'div';
  const unknown = value === null || value === undefined || value === '';
  return h(tag, {
    class: ['td-kpi', tone && `td-kpi--${tone}`, (href || onClick) && 'td-kpi--action'], href, type: tag === 'button' ? 'button' : undefined, onClick,
    title: help || undefined, 'aria-busy': loading ? 'true' : undefined,
  },
  h('div', { class: 'td-kpi__head' },
    ic ? h('span', { class: 'td-kpi__icon' }, icon(ic, { size: 16 })) : null,
    h('span', { class: 'td-kpi__label' }, label),
    help ? icon('info', { size: 14, class: 'td-kpi__help' }) : null,
    (href || onClick) ? icon('chevron', { size: 14, class: 'td-kpi__go' }) : null),
  loading ? h('div', { class: 'td-skel', style: { width: '60%', height: '28px', margin: '6px 0' } })
    : h('div', { class: 'td-kpi__value td-num' }, unknown ? '—' : toNode(typeof value === 'number' ? fmt.num(value) : value)),
  (sub || basis) && !loading ? h('div', { class: 'td-kpi__sub' }, sub ? toNode(sub) : null, basis ? provenance(unknown ? 'pending' : basis) : null) : null);
}
export function kpiRow(items = []) { return h('div', { class: 'td-kpi-row' }, items.filter(Boolean)); }

/* ---------- verification ---------- */
export function verifiedBadge({ state = 'missing', source, date, by } = {}) {
  const st = ['verified', 'unverified', 'missing'].includes(state) ? state : 'unverified';
  const parts = [];
  if (date) parts.push(fmt.date(date));
  if (source) parts.push(String(source).replace(/^https?:\/\//, '').slice(0, 60));
  const tip = st === 'verified'
    ? `Verified${date ? ` on ${fmt.date(date)}` : ''}${by ? ` by ${by}` : ''}${source ? ` · source: ${source}` : ''}`
    : st === 'unverified' ? 'Unverified — entered without a confirmed source. Check before relying on it.' : 'Missing — no value recorded yet.';
  return h('span', { class: ['td-verify', `td-verify--${st}`], title: tip, 'aria-label': tip },
    icon(st === 'verified' ? 'check' : st === 'unverified' ? 'warn' : 'info', { size: 12 }),
    h('span', null, st === 'verified' ? 'Verified' : st === 'unverified' ? 'Unverified' : 'Missing'),
    st === 'verified' && parts.length ? h('span', { class: 'td-verify__meta' }, parts.join(' · ')) : null);
}

/* ---------- contact actions ---------- */
function telHref(p) { const d = String(p || '').replace(/[^\d+]/g, ''); return d ? `tel:${d}` : null; }
function waNumber(p) {
  let d = String(p || '').replace(/\D/g, '');
  if (d.length === 10) d = `91${d}`;
  if (d.length === 11 && d.startsWith('0')) d = `91${d.slice(1)}`;
  return d.length >= 11 ? d : null;
}
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); return true; } catch {
    const ta = h('textarea', { style: { position: 'fixed', opacity: '0' } }); ta.value = t; document.body.append(ta); ta.select();
    let ok = false; try { ok = document.execCommand('copy'); } catch { ok = false; } ta.remove(); return ok;
  }
}
export function contactActions(phone, email, { compact = false, whatsapp = false, name } = {}) {
  const who = name ? ` ${name}` : '';
  const link = (href, ic, lbl, aria, extra = {}) => (href
    ? h('a', { class: ['td-btn', 'td-btn--ghost', 'td-btn--sm', compact && 'td-btn--icon'], href, 'aria-label': aria, title: aria, ...extra }, icon(ic, { size: 16 }), compact ? null : h('span', null, lbl))
    : h('span', { class: ['td-btn', 'td-btn--ghost', 'td-btn--sm', 'is-disabled', compact && 'td-btn--icon'], 'aria-disabled': 'true', title: `No ${lbl.toLowerCase()} recorded` }, icon(ic, { size: 16 }), compact ? null : h('span', null, `No ${lbl.toLowerCase()}`)));
  const items = [link(telHref(phone), 'phone', 'Call', `Call${who} ${phone || ''}`.trim())];
  if (whatsapp) {
    const wa = waNumber(phone);
    items.push(link(wa ? `https://wa.me/${wa}` : null, 'external', 'WhatsApp', `WhatsApp${who}`, { target: '_blank', rel: 'noopener noreferrer' }));
  }
  items.push(link(email ? `mailto:${email}` : null, 'mail', 'Email', `Email${who} ${email || ''}`.trim()));
  if (phone || email) {
    const val = [phone, email].filter(Boolean).join(' · ');
    const b = button({ icon: 'link', tone: 'ghost', size: 'sm', ariaLabel: `Copy contact details${who}`, title: 'Copy' });
    b.addEventListener('click', async () => { toast((await copyText(val)) ? `Copied ${val}` : 'Could not copy — select the text instead', 'info'); });
    items.push(b);
  }
  return h('div', { class: ['td-contact', compact && 'td-contact--compact'] }, items);
}

/* ---------- menu (overflow ⋯) ---------- */
let openMenuEl = null;
function closeMenu() { if (openMenuEl) { const m = openMenuEl; openMenuEl = null; m.cleanup(); } }
export function menu({ label, icon: ic = 'more', items = [], ariaLabel = 'More actions', tone = 'ghost', size = 'sm' } = {}) {
  const btn = button({ label, icon: ic, tone, size, ariaLabel });
  btn.setAttribute('aria-haspopup', 'menu');
  btn.setAttribute('aria-expanded', 'false');
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (openMenuEl && openMenuEl.btn === btn) { closeMenu(); return; }
    closeMenu();
    const vis = items.filter((it) => it && !it.hidden && !(it.writeOnly && !canWrite()));
    const pop = h('div', { class: 'td-menu', role: 'menu' });
    const entries = vis.map((it) => {
      const mi = h('button', { type: 'button', role: 'menuitem', class: ['td-menu__item', it.tone === 'danger' && 'is-danger'], tabindex: '-1' },
        it.icon ? icon(it.icon, { size: 16 }) : h('span', { class: 'td-menu__sp' }), h('span', null, it.label));
      mi.addEventListener('click', (ev) => { ev.stopPropagation(); closeMenu(); btn.focus(); if (it.onClick) it.onClick(ev); });
      pop.append(mi);
      return mi;
    });
    if (!entries.length) pop.append(h('div', { class: 'td-menu__none td-muted' }, 'No actions available'));
    (document.getElementById('td-overlays') || document.body).append(pop);
    const r = btn.getBoundingClientRect();
    const pw = pop.offsetWidth; const ph = pop.offsetHeight;
    let left = Math.min(r.right - pw, innerWidth - pw - 8); left = Math.max(8, left);
    let top = r.bottom + 4; if (top + ph > innerHeight - 8) top = Math.max(8, r.top - ph - 4);
    Object.assign(pop.style, { left: `${left}px`, top: `${top}px` });
    const onKey = (ev) => {
      const i = entries.indexOf(document.activeElement);
      if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); closeMenu(); btn.focus(); } else if (ev.key === 'ArrowDown') { ev.preventDefault(); (entries[(i + 1) % entries.length] || btn).focus(); } else if (ev.key === 'ArrowUp') { ev.preventDefault(); (entries[(i - 1 + entries.length) % entries.length] || btn).focus(); } else if (ev.key === 'Tab') closeMenu();
    };
    const onOut = (ev) => { if (!pop.contains(ev.target) && ev.target !== btn && !btn.contains(ev.target)) closeMenu(); };
    const onScroll = () => closeMenu();
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('mousedown', onOut, true);
    addEventListener('resize', onScroll);
    document.addEventListener('scroll', onScroll, true);
    btn.setAttribute('aria-expanded', 'true');
    const releaseBack = backClosable(() => { if (openMenuEl && openMenuEl.pop === pop) closeMenu(); });
    openMenuEl = {
      btn, pop,
      cleanup() {
        releaseBack();
        pop.remove(); btn.setAttribute('aria-expanded', 'false');
        document.removeEventListener('keydown', onKey, true); document.removeEventListener('mousedown', onOut, true);
        removeEventListener('resize', onScroll); document.removeEventListener('scroll', onScroll, true);
      },
    };
    if (entries[0]) requestAnimationFrame(() => entries[0].focus());
  });
  return btn;
}

/* ---------- segmented control + link tabs ---------- */
export function segmented({ options = [], value, onChange, ariaLabel = 'Choose', size } = {}) {
  const opts = normOptions(options).map((o, i) => ({ ...o, count: options[i] && typeof options[i] === 'object' ? options[i].count : undefined }));
  let cur = value === undefined ? (opts[0] && opts[0].value) : value;
  const root = h('div', { class: ['td-seg', size === 'sm' && 'td-seg--sm'], role: 'group', 'aria-label': ariaLabel });
  const btns = opts.map((o) => {
    const b = h('button', { type: 'button', class: 'td-seg__btn', 'aria-pressed': String(String(o.value) === String(cur)), dataset: { value: String(o.value) } },
      h('span', null, o.label), o.count !== undefined && o.count !== null ? h('span', { class: 'td-seg__count td-num' }, fmt.num(o.count)) : null);
    b.addEventListener('click', () => set(o.value, true));
    return b;
  });
  function set(v, user) {
    cur = v;
    btns.forEach((b, i) => b.setAttribute('aria-pressed', String(String(opts[i].value) === String(v))));
    if (user && onChange) onChange(v);
  }
  root.addEventListener('keydown', (e) => {
    const i = btns.indexOf(document.activeElement);
    if (i < 0) return;
    const n = e.key === 'ArrowRight' ? (i + 1) % btns.length : e.key === 'ArrowLeft' ? (i - 1 + btns.length) % btns.length : null;
    if (n !== null) { e.preventDefault(); btns[n].focus(); }
  });
  root.append(...btns);
  root.setValue = (v) => set(v, false);
  root.getValue = () => cur;
  return root;
}

/** Which of several hrefs best matches the current hash: same path, and every query key of the href matches (most specific wins). */
function bestHrefMatch(hrefs) {
  const [curPath, curQs] = location.hash.split('?');
  const cur = new URLSearchParams(curQs || '');
  let best = -1; let score = -1;
  hrefs.forEach((href, i) => {
    if (!href) return;
    const [p, qs] = href.split('?');
    if (p !== curPath) return;
    const q = [...new URLSearchParams(qs || '')];
    if (!q.every(([k, v]) => cur.get(k) === v)) return;
    if (q.length > score) { score = q.length; best = i; }
  });
  return best;
}
export function linkTabs(items = [], { ariaLabel = 'Section' } = {}) {
  const list = items.filter(Boolean);
  const auto = bestHrefMatch(list.map((t) => t.href));
  return scrollStrip(h('nav', { class: 'td-linktabs', 'aria-label': ariaLabel },
    list.map((t, i) => {
      const on = t.active !== undefined ? !!t.active : i === auto;
      return h('a', { href: t.href, class: ['td-linktab', on && 'is-active'], 'aria-current': on ? 'page' : undefined },
        h('span', null, t.label), t.count !== undefined && t.count !== null ? h('span', { class: 'td-linktab__count td-num' }, fmt.num(t.count)) : null);
    })), '.td-linktab.is-active');
}

/* ---------- district scope pill (opens the global picker) ---------- */
export function scopePill() {
  const b = h('button', { type: 'button', class: 'td-scopepill' });
  const paint = () => {
    const s = getScope();
    b.classList.toggle('is-custom', !s.isDefault);
    b.replaceChildren(icon('map', { size: 14 }), h('span', { class: 'td-scopepill__k' }, 'Districts:'), h('span', { class: 'td-scopepill__v' }, scopeLabel({ max: 3 })), icon('chevron-down', { size: 14 }));
    b.setAttribute('aria-label', `Showing ${scopeLabel()}. Change districts`);
  };
  paint();
  const onScope = () => { if (!b.isConnected) { removeEventListener(SCOPE_EVENT, onScope); return; } paint(); };
  addEventListener(SCOPE_EVENT, onScope);
  b.addEventListener('click', () => dispatchEvent(new CustomEvent('td:open-scope', { detail: { anchor: b } })));
  return b;
}

/* ---------- pagination ---------- */
export function pagination({ page = 1, pageSize = 50, total = 0, onPage, pageSizes, onPageSize, label = 'rows' } = {}) {
  const pages = Math.max(1, Math.ceil((Number(total) || 0) / pageSize));
  const p = Math.min(Math.max(1, page), pages);
  const from = total ? (p - 1) * pageSize + 1 : 0;
  const to = Math.min(p * pageSize, total);
  const go = (n) => { if (onPage && n >= 1 && n <= pages && n !== p) onPage(n); };
  const prev = button({ icon: 'chevron-left', tone: 'ghost', size: 'sm', ariaLabel: 'Previous page', disabled: p <= 1, onClick: () => go(p - 1) });
  const next = button({ icon: 'chevron', tone: 'ghost', size: 'sm', ariaLabel: 'Next page', disabled: p >= pages, onClick: () => go(p + 1) });
  let sizeSel = null;
  if (pageSizes && onPageSize) {
    sizeSel = h('select', { class: 'td-input td-select td-input--sm', 'aria-label': 'Rows per page' }, pageSizes.map((n) => h('option', { value: String(n) }, `${n} per page`)));
    sizeSel.value = String(pageSize);
    sizeSel.addEventListener('change', () => onPageSize(Number(sizeSel.value)));
  }
  return h('div', { class: 'td-pager', role: 'navigation', 'aria-label': 'Pagination' },
    h('span', { class: 'td-pager__info td-num', 'aria-live': 'polite' }, total ? `${fmt.num(from)}–${fmt.num(to)} of ${fmt.num(total)} ${label}` : `0 ${label}`),
    h('span', { class: 'td-pager__ctrl' }, sizeSel, pages > 1 ? [prev, h('span', { class: 'td-pager__page td-num' }, `Page ${p} of ${pages}`), next] : null));
}

/* ---------- data table ---------- */
export function dataTable(opts = {}) {
  const o = { mobile: 'cards', ...opts };
  let columns = (o.columns || []).filter(Boolean);
  const st = {
    rows: o.rows || [], total: o.total, page: o.page || 1, sort: o.sort || null, loading: !!o.loading, error: o.error || null,
  };
  const keyOf = o.rowKey || ((r) => r.id);
  const selected = new Set();
  const root = h('div', { class: ['td-dt', o.dense && 'td-dt--dense', o.mobile === 'cards' && 'td-dt--cards'] });
  /* ---- fit: priority 3 columns hide first; below the width of the priority 1+2 columns the table becomes cards ---- */
  let mode = null; // 'table' | 'cards'
  let hide3 = false;
  const prio = (c, i) => (c.priority ? Number(c.priority) : (c.primary || i < 2 ? 1 : 2));
  const minW = (c, i) => Number(c.minWidth) || (i === primaryIdx ? 200 : 110);
  function needWidth(maxPrio) {
    let w = (o.selectable ? 44 : 0) + (o.rowActions ? 96 : 0);
    columns.forEach((c, i) => { if (prio(c, i) <= maxPrio) w += minW(c, i); });
    return w;
  }
  function measureWidth() {
    const w = root.clientWidth || (root.parentElement && root.parentElement.clientWidth) || 0;
    if (w) return w;
    const v = document.querySelector('.td-view');
    return (v && v.clientWidth) || innerWidth;
  }
  function decide() {
    const w = measureWidth();
    const cards = o.mobile === 'cards' && (isPhone() || w < needWidth(2) || (o.cardBreakpoint && w < o.cardBreakpoint));
    return { mode: cards ? 'cards' : 'table', hide3: !cards && w < needWidth(3) };
  }
  const serverSort = typeof o.onSort === 'function';
  const serverPage = typeof o.onPage === 'function';
  let primaryIdx = Math.max(0, columns.findIndex((c) => c.primary));
  const colCls = (c, i) => [prio(c, i) >= 3 && 'td-dt__p3', c.sticky === 'left' && 'td-dt__stick-l', c.sticky === 'right' && 'td-dt__stick-r'];
  const coll = new Intl.Collator('en-IN', { numeric: true, sensitivity: 'base' });

  function sortedRows() {
    const rows = st.rows || [];
    if (serverSort || !st.sort || !st.sort.key) return rows;
    const dir = st.sort.dir === 'desc' ? -1 : 1;
    const col = columns.find((c) => c.key === st.sort.key);
    const get = col && col.sortValue ? col.sortValue : (r) => sortVal(r[st.sort.key]);
    return [...rows].sort((a, b) => {
      const x = get(a); const y = get(b);
      const xn = isEmptyVal(x); const yn = isEmptyVal(y);
      if (xn && yn) return 0; if (xn) return 1; if (yn) return -1;
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
      return coll.compare(String(x), String(y)) * dir;
    });
  }
  function pageRows(rows) {
    if (serverPage || !o.pageSize) return rows;
    const start = (st.page - 1) * o.pageSize;
    return rows.slice(start, start + o.pageSize);
  }
  function totalCount() { return serverPage ? (Number(st.total) || 0) : (st.rows || []).length; }
  function toggleSort(key) {
    const dir = st.sort && st.sort.key === key && st.sort.dir === 'asc' ? 'desc' : 'asc';
    st.sort = { key, dir };
    if (serverSort) o.onSort(key, dir); else { st.page = 1; render(); }
  }
  function cellContent(c, row) {
    if (c.render) return c.render(row);
    const v = row[c.key];
    if (v && typeof v === 'object' && 'value' in v) return valueWithBasis(v);
    return isEmptyVal(v) ? '—' : (typeof v === 'number' ? fmt.num(v) : String(v));
  }
  function actionsFor(row) {
    if (!o.rowActions) return null;
    const list = (o.rowActions(row) || []).filter((a) => a && !a.hidden && !(a.writeOnly && !canWrite()));
    if (!list.length) return null;
    if (list.length <= 2) {
      return h('div', { class: 'td-dt__acts' }, list.map((a) => {
        const b = button({ label: a.label, icon: a.icon, tone: ['danger', 'primary', 'secondary', 'accent'].includes(a.tone) ? a.tone : 'ghost', size: 'sm', onClick: (e) => { e.stopPropagation(); a.onClick && a.onClick(row, e); } });
        return a.writeOnly ? writeOnly(b) : b;
      }));
    }
    return h('div', { class: 'td-dt__acts' }, menu({ ariaLabel: 'Row actions', items: list.map((a) => ({ ...a, onClick: (e) => a.onClick && a.onClick(row, e) })) }));
  }
  function selBox(row) {
    const k = keyOf(row);
    const cb = h('input', { type: 'checkbox', class: 'td-check', 'aria-label': 'Select row' });
    cb.checked = selected.has(k);
    cb.addEventListener('click', (e) => e.stopPropagation());
    cb.addEventListener('change', () => { if (cb.checked) selected.add(k); else selected.delete(k); emitSel(); syncHeadBox(); });
    const hit = h('label', { class: 'td-checkhit' }, cb);
    hit.addEventListener('click', (e) => e.stopPropagation());
    return hit;
  }
  let headBox = null;
  function syncHeadBox() {
    if (!headBox) return;
    const keys = pageRows(sortedRows()).map(keyOf);
    const n = keys.filter((k) => selected.has(k)).length;
    headBox.checked = !!keys.length && n === keys.length; headBox.indeterminate = n > 0 && n < keys.length;
  }
  function emitSel() { if (o.onSelect) o.onSelect((st.rows || []).filter((r) => selected.has(keyOf(r)))); }
  function bindRow(el, row) {
    const href = o.rowHref ? o.rowHref(row) : null;
    if (!o.onRowClick && !href) return;
    el.classList.add('is-click');
    el.tabIndex = 0;
    const act = (ev) => { if (o.onRowClick) o.onRowClick(row, ev); else if (href) location.hash = href.replace(/^#/, ''); };
    el.addEventListener('click', (ev) => { if (ev.target.closest('a,button,input,select,textarea,label')) return; act(ev); });
    el.addEventListener('keydown', (ev) => { if ((ev.key === 'Enter' || ev.key === ' ') && ev.target === el) { ev.preventDefault(); act(ev); } });
  }
  function emptyNode() {
    const e = o.empty;
    if (e instanceof Node) return e;
    if (e && typeof e === 'object') return emptyState({ icon: 'list', ...e });
    return emptyState({ icon: 'list', title: typeof e === 'string' ? e : 'Nothing to show', text: '' });
  }

  function renderTable(rows) {
    const scroller = h('div', { class: 'td-table-scroll', tabindex: '0', role: 'region', 'aria-label': o.caption || 'Table' });
    const tbl = h('table', { class: ['td-table', 'td-dt__table', (o.onRowClick || o.rowHref) && 'td-table--click'] });
    if (o.caption) tbl.append(h('caption', { class: 'td-sr-only' }, o.caption));
    const tr = h('tr');
    if (o.selectable) {
      headBox = h('input', { type: 'checkbox', class: 'td-check', 'aria-label': 'Select all on this page' });
      headBox.addEventListener('change', () => { pageRows(sortedRows()).forEach((r) => (headBox.checked ? selected.add(keyOf(r)) : selected.delete(keyOf(r)))); render(); emitSel(); });
      tr.append(h('th', { class: 'td-dt__sel', scope: 'col' }, h('label', { class: 'td-checkhit' }, headBox)));
    }
    columns.forEach((c) => {
      const sortable = c.sortable !== false && !!c.key && !c.noSort;
      const on = st.sort && st.sort.key === c.key;
      const th = h('th', { scope: 'col', class: [c.align && `td-al-${c.align}`, ...colCls(c, columns.indexOf(c))], style: c.width ? { width: c.width } : undefined, 'aria-sort': on ? (st.sort.dir === 'desc' ? 'descending' : 'ascending') : (sortable ? 'none' : undefined) });
      if (sortable) {
        th.append(h('button', { type: 'button', class: ['td-th-sort', on && 'is-sorted'], onClick: () => toggleSort(c.key) },
          h('span', null, c.label), h('span', { class: 'td-th-sort__ind', 'aria-hidden': 'true' })));
      } else th.append(c.label || '');
      tr.append(th);
    });
    if (o.rowActions) tr.append(h('th', { scope: 'col', class: 'td-al-right td-dt__actcol td-dt__stick-r' }, h('span', { class: 'td-sr-only' }, 'Actions')));
    tbl.append(h('thead', null, tr));
    const tbody = h('tbody');
    const ncol = columns.length + (o.selectable ? 1 : 0) + (o.rowActions ? 1 : 0);
    if (st.loading) {
      const n = Math.min(Math.max(o.pageSize || 6, 4), 8);
      for (let i = 0; i < n; i++) tbody.append(h('tr', { class: 'td-dt__skel', 'aria-hidden': 'true' }, Array.from({ length: ncol }, (_, j) => h('td', null, h('div', { class: 'td-skel', style: { width: `${55 + ((i * 13 + j * 17) % 40)}%` } })))));
    } else if (st.error) {
      tbody.append(h('tr', { class: 'td-table-empty' }, h('td', { colspan: String(ncol) }, errorCard({ title: 'Could not load this list', error: st.error, retry: o.onRetry }))));
    } else if (!rows.length) {
      tbody.append(h('tr', { class: 'td-table-empty' }, h('td', { colspan: String(ncol) }, emptyNode())));
    } else {
      for (const row of rows) {
        const r = h('tr', { class: o.selectable && selected.has(keyOf(row)) ? 'is-selected' : null });
        if (o.selectable) r.append(h('td', { class: 'td-dt__sel' }, selBox(row)));
        columns.forEach((c, i) => r.append(h('td', { class: [c.align && `td-al-${c.align}`, i === primaryIdx && 'td-td-primary', typeof row[c.key] === 'number' && 'td-num', ...colCls(c, i)] }, toNode(cellContent(c, row)))));
        if (o.rowActions) r.append(h('td', { class: 'td-al-right td-dt__actcol td-dt__stick-r' }, actionsFor(row)));
        bindRow(r, row);
        tbody.append(r);
      }
    }
    tbl.append(tbody);
    scroller.append(tbl);
    return scroller;
  }

  function renderCards(rows) {
    const list = h('div', { class: 'td-dt__cards', role: 'list', 'aria-label': o.caption || 'List', 'aria-busy': st.loading ? 'true' : undefined });
    const sortable = columns.filter((c) => c.sortable !== false && c.key && !c.noSort);
    if (o.cardSort !== false && sortable.length && rows.length > 1 && !st.loading) { // cardSort:false when the page has its own sort control
      const sel = h('select', { class: 'td-input td-select td-input--sm', 'aria-label': 'Sort by' },
        h('option', { value: '' }, (() => {
          // name the order the rows arrive in, never a vague "default"
          const d = o.sort && o.sort.key ? columns.find((c) => c.key === o.sort.key) : null;
          return d ? `Sort: ${d.phoneLabel || d.label}${o.sort.dir === 'desc' ? ' ↓' : ' ↑'}` : (o.defaultSortLabel ? `Sort: ${o.defaultSortLabel}` : 'Sort: as listed');
        })()),
        sortable.flatMap((c) => [h('option', { value: `${c.key}:asc` }, `${c.phoneLabel || c.label} ↑`), h('option', { value: `${c.key}:desc` }, `${c.phoneLabel || c.label} ↓`)]));
      sel.value = st.sort ? `${st.sort.key}:${st.sort.dir}` : '';
      sel.addEventListener('change', () => {
        const [k, d] = sel.value.split(':');
        st.sort = k ? { key: k, dir: d } : null;
        if (serverSort && k) o.onSort(k, d); else { st.page = 1; render(); }
      });
      list.append(h('div', { class: 'td-dt__cardsort' }, sel));
    }
    if (st.loading) { for (let i = 0; i < 4; i++) list.append(h('div', { class: 'td-dt-card td-dt-card--skel', 'aria-hidden': 'true' }, h('div', { class: 'td-skel td-skel--title' }), h('div', { class: 'td-skel' }), h('div', { class: 'td-skel', style: { width: '60%' } }))); return list; }
    if (st.error) { list.append(errorCard({ title: 'Could not load this list', error: st.error, retry: o.onRetry })); return list; }
    if (!rows.length) { list.append(h('div', { class: 'td-card' }, emptyNode())); return list; }
    for (const row of rows) {
      const pc = columns[primaryIdx];
      const card = h('div', { class: ['td-dt-card', o.selectable && selected.has(keyOf(row)) && 'is-selected'], role: 'listitem' });
      const sub = o.cardSubtitle ? o.cardSubtitle(row) : null;
      const meta = o.cardMeta ? [].concat(o.cardMeta(row) || []).filter(Boolean) : [];
      card.append(h('div', { class: 'td-dt-card__head' }, o.selectable ? selBox(row) : null,
        h('div', { class: 'td-dt-card__main' },
          h('div', { class: 'td-dt-card__title' }, toNode(o.cardTitle ? o.cardTitle(row) : cellContent(pc, row))),
          !isEmptyVal(sub) ? h('div', { class: 'td-dt-card__sub' }, toNode(sub)) : null,
          meta.length ? h('div', { class: 'td-dt-card__meta' }, meta.map(toNode)) : null),
        actionsFor(row)));
      const dl = h('dl', { class: 'td-dt-card__kv' });
      columns.forEach((c, i) => {
        if (i === primaryIdx || c.hideOnPhone || c.cardHidden) return;
        dl.append(h('div', { class: 'td-dt-card__row' }, h('dt', null, c.phoneLabel || c.label || ''), h('dd', null, toNode(cellContent(c, row)))));
      });
      if (dl.childNodes.length) card.append(dl); else card.classList.add('td-dt-card--bare');
      bindRow(card, row);
      list.append(card);
    }
    return list;
  }

  function render() {
    const all = sortedRows();
    const rows = st.loading || st.error ? [] : pageRows(all);
    const d = decide();
    mode = d.mode; hide3 = d.hide3;
    root.classList.toggle('td-dt--hide3', hide3);
    root.classList.toggle('td-dt--is-cards', mode === 'cards');
    const cards = mode === 'cards';
    const body = cards ? renderCards(rows) : renderTable(rows);
    const kids = [body];
    const total = totalCount();
    if (o.pageSize && !st.loading && !st.error && total > 0) {
      kids.push(pagination({
        page: st.page, pageSize: o.pageSize, total, label: o.pageLabel || 'rows',
        onPage: (n) => { st.page = n; if (serverPage) o.onPage(n); else render(); root.scrollIntoView({ block: 'nearest' }); },
      }));
    }
    root.replaceChildren(...kids);
    syncHeadBox();
  }
  const onFF = () => { if (!root.isConnected && root.dataset.mounted) { removeEventListener(FF_EVENT, onFF); return; } refit(); };
  function refit() {
    const d = decide();
    if (d.mode !== mode) { render(); return; }
    if (d.hide3 !== hide3) { hide3 = d.hide3; root.classList.toggle('td-dt--hide3', hide3); }
  }
  addEventListener(FF_EVENT, onFF);
  if (typeof ResizeObserver === 'function') {
    let lastW = 0;
    const ro = new ResizeObserver((ents) => {
      if (!root.isConnected && root.dataset.mounted) { ro.disconnect(); return; }
      const w = Math.round(ents[0].contentRect.width);
      if (!w || Math.abs(w - lastW) < 2) return;
      lastW = w;
      requestAnimationFrame(refit);
    });
    ro.observe(root);
  }
  requestAnimationFrame(() => { root.dataset.mounted = '1'; });
  render();
  root.update = (patch = {}) => {
    if ('rows' in patch) { st.rows = patch.rows || []; if (!serverPage && !('page' in patch)) st.page = 1; }
    for (const k of ['total', 'page', 'sort', 'loading', 'error']) if (k in patch) st[k] = patch[k];
    if ('columns' in patch) { columns = (patch.columns || []).filter(Boolean); primaryIdx = Math.max(0, columns.findIndex((c) => c.primary)); }
    for (const k of ['empty', 'rowActions', 'onRowClick', 'rowHref', 'caption', 'pageSize']) if (k in patch) o[k] = patch[k];
    if (!('loading' in patch) && 'rows' in patch) st.loading = false;
    render();
  };
  root.selected = () => (st.rows || []).filter((r) => selected.has(keyOf(r)));
  root.clearSelection = () => { selected.clear(); render(); emitSel(); };
  return root;
}

/* ---------- filter bar ---------- */
/**
 * filterBar — on phones (collapse:'auto', the default) only the search box, a "Filters (n)" button and the actions stay
 * in the bar; the filter controls move into a bottom sheet and active filters show as removable chips.
 */
export function filterBar({ search, filters = [], values = {}, onChange, actions, showClear = true, collapse = 'auto' } = {}) {
  const vals = {};
  const ctrls = {};
  const defs = {};
  const root = h('div', { class: ['td-fbar', collapse === 'auto' && 'td-fbar--auto', collapse === 'always' && 'td-fbar--collapsed'], role: 'search' });
  const main = h('div', { class: 'td-fbar__main' });
  const items = h('div', { class: 'td-fbar__items' });
  const clearBtn = button({ label: 'Clear filters', icon: 'close', tone: 'ghost', size: 'sm', onClick: () => root.clear() });
  const moreBtn = button({ label: 'Filters', icon: 'filter', tone: 'secondary', size: 'sm' });
  moreBtn.classList.add('td-fbar__more');
  moreBtn.setAttribute('aria-haspopup', 'dialog');
  const moreCount = h('span', { class: 'td-fbar__count td-num', hidden: true });
  moreBtn.append(moreCount);
  const chips = h('div', { class: 'td-fbar__chips', role: 'group', 'aria-label': 'Active filters' });
  const emit = (k) => { sync(); if (onChange) onChange({ ...vals }, k); };
  const isSet = (v) => !isEmptyVal(v) && v !== false;
  function chipLabel(k) {
    const f = defs[k];
    const v = vals[k];
    if (f.type === 'toggle') return f.label;
    const op = normOptions(f.options || []).find((x) => String(x.value) === String(v));
    return `${f.label}: ${op ? op.label : v}`;
  }
  function sync() {
    clearBtn.hidden = !showClear || !Object.values(vals).some(isSet);
    const active = Object.keys(defs).filter((k) => isSet(vals[k]));
    moreCount.hidden = !active.length;
    moreCount.textContent = active.length ? `(${active.length})` : '';
    moreBtn.setAttribute('aria-label', active.length ? `Filters, ${active.length} active` : 'Filters');
    moreBtn.classList.toggle('is-set', active.length > 0);
    chips.replaceChildren(...active.map((k) => chip({
      label: chipLabel(k), active: true,
      onRemove: () => { vals[k] = typeof vals[k] === 'boolean' ? false : ''; if (ctrls[k]) ctrls[k].set(vals[k]); emit(k); },
    })));
    chips.hidden = !active.length;
  }
  if (search) {
    const k = search.key || 'q';
    vals[k] = values[k] ?? search.value ?? '';
    const inp = h('input', { type: 'search', class: 'td-input td-fbar__q', placeholder: search.placeholder || 'Search…', 'aria-label': search.placeholder || 'Search', value: vals[k], enterkeyhint: 'search' });
    inp.value = vals[k];
    const fire = debounce(() => { vals[k] = inp.value.trim(); emit(k); }, search.debounce ?? 250);
    inp.addEventListener('input', fire);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Escape' && inp.value) { e.stopPropagation(); inp.value = ''; vals[k] = ''; emit(k); } });
    ctrls[k] = { set: (v) => { inp.value = v || ''; } };
    main.append(h('div', { class: 'td-fbar__search' }, icon('search', { size: 16, class: 'td-fbar__qicon' }), inp));
  }
  filters.filter(Boolean).forEach((f) => {
    const k = f.key;
    defs[k] = f;
    vals[k] = values[k] ?? f.value ?? (f.type === 'toggle' ? false : '');
    const opts = normOptions(f.options || []);
    if (f.type === 'segmented') {
      const seg = segmented({ options: [{ value: '', label: f.allLabel || 'All' }, ...(f.options || [])], value: vals[k], ariaLabel: f.label, onChange: (v) => { vals[k] = v; emit(k); }, size: 'sm' });
      ctrls[k] = { set: (v) => seg.setValue(v ?? '') };
      items.append(h('div', { class: 'td-fbar__item td-fbar__item--seg' }, h('span', { class: 'td-fbar__label', 'aria-hidden': 'true' }, f.label), seg));
    } else if (f.type === 'toggle') {
      const id = uid('fb');
      const cb = h('input', { type: 'checkbox', id, class: 'td-check' });
      cb.checked = !!vals[k] && vals[k] !== '0' && vals[k] !== 'false';
      vals[k] = cb.checked;
      cb.addEventListener('change', () => { vals[k] = cb.checked; emit(k); });
      ctrls[k] = { set: (v) => { cb.checked = !!v && v !== '0' && v !== 'false'; } };
      items.append(h('label', { for: id, class: 'td-fbar__item td-fbar__toggle' }, cb, h('span', null, f.label)));
    } else {
      const id = uid('fb');
      const sel = h('select', { id, class: 'td-input td-select td-input--sm', 'aria-label': f.label },
        h('option', { value: '' }, f.allLabel || `${f.label}: all`), opts.map((op, i) => h('option', { value: String(i) }, f.allLabel ? op.label : `${f.label}: ${op.label}`)));
      const toIdx = (v) => { const i = opts.findIndex((op) => String(op.value) === String(v)); return i < 0 ? '' : String(i); };
      sel.value = toIdx(vals[k]);
      sel.addEventListener('change', () => { vals[k] = sel.value === '' ? '' : opts[Number(sel.value)].value; sel.classList.toggle('is-set', sel.value !== ''); emit(k); });
      sel.classList.toggle('is-set', sel.value !== '');
      ctrls[k] = { set: (v) => { sel.value = toIdx(v); sel.classList.toggle('is-set', sel.value !== ''); } };
      items.append(h('div', { class: 'td-fbar__item' }, h('label', { for: id, class: 'td-fbar__label' }, f.label), sel));
    }
  });
  items.append(clearBtn);
  main.append(items);
  if (Object.keys(defs).length) main.append(moreBtn); else root.classList.remove('td-fbar--auto', 'td-fbar--collapsed');
  root.append(main);
  if (actions && [].concat(actions).length) root.append(h('div', { class: 'td-fbar__actions' }, [].concat(actions).filter(Boolean)));
  root.append(chips);

  // phone sheet: the very same controls move into a drawer and back, so their state and handlers stay intact
  moreBtn.addEventListener('click', () => {
    const n = Object.keys(defs).filter((k) => isSet(vals[k])).length;
    const sheetBody = h('div', { class: 'td-fbar-sheet' }, items);
    let d = null;
    const done = button({ label: 'Show results', tone: 'primary', onClick: () => d && d.close() });
    const clearAll = button({ label: 'Clear all', tone: 'ghost', onClick: () => root.clear() });
    sheetBody.append(h('div', { class: 'td-fbar-sheet__foot' }, clearAll, done));
    d = drawer({
      title: n ? `Filters (${n})` : 'Filters', body: sheetBody,
      onClose: () => { main.insertBefore(items, moreBtn); sync(); },
    });
  });
  sync();
  root.values = () => ({ ...vals });
  root.activeCount = () => Object.keys(defs).filter((k) => isSet(vals[k])).length;
  root.hasFilters = () => Object.keys(vals).some((k) => isSet(vals[k]));
  root.set = (v = {}, { silent = false } = {}) => {
    for (const [k, x] of Object.entries(v)) if (k in vals) { vals[k] = x ?? ''; if (ctrls[k]) ctrls[k].set(x); }
    sync();
    if (!silent && onChange) onChange({ ...vals }, null);
  };
  root.clear = () => {
    for (const k of Object.keys(vals)) { vals[k] = typeof vals[k] === 'boolean' ? false : ''; if (ctrls[k]) ctrls[k].set(vals[k]); }
    emit(null);
  };
  return root;
}

/* ---------- form dialog ---------- */
export function formDialog({ title, intro, fields = [], values = {}, submitLabel = 'Save', cancelLabel = 'Cancel', wide, danger, onSubmit, onChange, footerNote } = {}) {
  return new Promise((resolve) => {
    const freshKey = () => { try { return crypto.randomUUID(); } catch { return `k${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`; } };
    // one key per submit attempt (F1): kept only when the attempt failed with no answer from the server (network)
    let idempotencyKey = freshKey();
    let result = null; let done = false; let m = null;
    const fdefs = fields.filter(Boolean).map((fd) => (fd.name in values && fd.value === undefined ? { ...fd, value: values[fd.name] } : fd));
    const f = form({
      fields: fdefs, submitLabel, cancelLabel,
      onCancel: () => m && m.close(),
      onSubmit: async (v) => {
        try { result = onSubmit ? await onSubmit(v, { idempotencyKey, close: () => m && m.close() }) : v; } catch (e) {
          if (!e || e.status !== 0) idempotencyKey = freshKey();
          throw e;
        }
        done = true;
        if (result === undefined) result = true;
        m && m.close();
      },
    });
    if (danger) { const sb = f.querySelector('button[type=submit]'); if (sb) { sb.classList.remove('td-btn--primary'); sb.classList.add('td-btn--danger'); } }
    if (onChange) {
      const fire = debounce(() => onChange(f.values(), f), 200);
      f.addEventListener('input', fire); f.addEventListener('change', fire);
    }
    const body = h('div', { class: 'td-formdlg' },
      intro ? h('div', { class: 'td-formdlg__intro' }, toNode(intro)) : null, f,
      footerNote ? h('div', { class: 'td-formdlg__note td-muted' }, toNode(footerNote)) : null);
    m = modal({ title, body, wide, onClose: () => resolve(done ? result : null) });
  });
}

/* Default export as namespace-like object for ctx.ui */
export default {
  icon, iconNames, button, skeleton, provenance, valueWithBasis, badge, statusBadge, progress, statCard, table, tabs,
  modal, drawer, closeOverlays, confirm, toast, emptyState, section, kv, errorCard, form,
  pageHeader, chip, spinner,
  dataTable, pagination, filterBar, statusChip, progressBar, kpi, kpiRow, verifiedBadge, contactActions, formDialog,
  linkTabs, segmented, scopePill, menu, writeOnly, getHashQuery, setHashQuery, historyMode, canWrite,
  formFactor, isPhone, prefersReducedMotion, scroller, listEmpty, hasFilters, scrollStrip, backClosable, FORMFACTOR_EVENT,
  STATUS_META, PERF_STATUS_ORDER, statusMeta, pctText, pctPoints, plural, csvCell, csvRow, downloadCsv,
};
