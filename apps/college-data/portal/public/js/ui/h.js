// Tech Drona portal — DOM + formatting helpers (owned by orchestrator; see CONTRACT.md)

/**
 * h('div', {class:'x', onClick: fn, dataset:{id:1}, style:{...}}, child, [children], 'text')
 * - attrs starting with "on" become event listeners
 * - null/undefined/false children are skipped; arrays are flattened; strings/numbers become text nodes
 */
export function h(tag, attrs, ...children) {
  const el = tag === 'frag' ? document.createDocumentFragment()
    : (tag.startsWith('svg:') ? document.createElementNS('http://www.w3.org/2000/svg', tag.slice(4)) : document.createElement(tag));
  if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs);
    attrs = null;
  }
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === 'class' || k === 'className') el.setAttribute('class', Array.isArray(v) ? v.filter(Boolean).join(' ') : v);
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k === 'html') el.innerHTML = v; // only for trusted, static markup (icons)
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false || c === true) continue;
    if (Array.isArray(c)) append(el, c);
    else if (c instanceof Node) el.appendChild(c);
    else el.appendChild(document.createTextNode(String(c)));
  }
}

export const qs = (sel, root = document) => root.querySelector(sel);
export const qsa = (sel, root = document) => [...root.querySelectorAll(sel)];

export function debounce(fn, ms = 250) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

const nfIN = new Intl.NumberFormat('en-IN');
const DAY = 86400000;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Today's date as YYYY-MM-DD in local time (override with ?today=YYYY-MM-DD for testing). */
export function today() {
  const o = new URLSearchParams(location.search).get('today');
  if (o && /^\d{4}-\d{2}-\d{2}$/.test(o)) return o;
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Whole days from today to `date` (negative = past). null if no date. */
export function daysUntil(date) {
  if (!date) return null;
  const a = Date.parse(today() + 'T00:00:00Z');
  const b = Date.parse(String(date).slice(0, 10) + 'T00:00:00Z');
  if (Number.isNaN(b)) return null;
  return Math.round((b - a) / DAY);
}

export const fmt = {
  /** Indian digit grouping; null -> '—' */
  num: (n) => (n === null || n === undefined || Number.isNaN(n) ? '—' : nfIN.format(Math.round(n))),
  inr: (n) => (n === null || n === undefined ? '—' : '₹' + nfIN.format(Math.round(n))),
  /** x is a fraction (0.42 -> "42%") */
  pct: (x, digits = 0) => (x === null || x === undefined || Number.isNaN(x) ? '—' : (x * 100).toFixed(digits) + '%'),
  date: (d) => {
    if (!d) return '—';
    const t = Date.parse(String(d).slice(0, 10) + 'T00:00:00Z');
    if (Number.isNaN(t)) return String(d);
    const x = new Date(t); // fixed month names: en-IN renders September as "Sept"
    return `${x.getUTCDate()} ${MONTHS[x.getUTCMonth()]} ${x.getUTCFullYear()}`;
  },
  /** relative days label: "in 5 days", "today", "3 days ago" */
  days: (d) => {
    const n = daysUntil(d);
    if (n === null) return '—';
    if (n === 0) return 'today';
    if (n === 1) return 'tomorrow';
    if (n === -1) return 'yesterday';
    return n > 0 ? `in ${n} days` : `${-n} days ago`;
  },
  plural: (n, one, many) => `${fmt.num(n)} ${Number(n) === 1 ? one : (many || one + 's')}`,
  /** the word only: fmt.word(1,'district') -> 'district', fmt.word(3,'district') -> 'districts' */
  word: (n, one, many) => (Number(n) === 1 ? one : (many || one + 's')),
  /**
   * THE one percentage rule for every page (TG-13 / F11): input is a PERCENT number (4.75 -> "4.8%").
   * 0 -> "0%"; below 10 % one decimal; from 10 % whole numbers; null / NaN / Infinity -> "—" (never divides by zero).
   */
  pctPts: (p) => {
    if (p === null || p === undefined || p === '' || !Number.isFinite(Number(p))) return '—';
    const v = Number(p);
    if (v === 0) return '0%';
    return (Math.abs(v) < 10 ? (Math.round(v * 10) / 10).toFixed(1) : String(Math.round(v))) + '%';
  },
  /** same rule for a FRACTION (0.0475 -> "4.8%") */
  pctOf: (x) => (x === null || x === undefined || x === '' || !Number.isFinite(Number(x)) ? '—' : fmt.pctPts(Number(x) * 100)),
  /** actual / target as a % — "—" when there is no positive target (no divide-by-zero, no misleading %) */
  pctRatio: (a, t) => (Number(t) > 0 && Number.isFinite(Number(a)) ? fmt.pctPts((Number(a) / Number(t)) * 100) : '—'),
  /** "min 2 · max 4" / "max 4" / "" — never renders a dash pair for a missing end */
  range: (min, max) => [min !== null && min !== undefined && min !== '' ? `min ${fmt.num(Number(min))}` : null,
    max !== null && max !== undefined && max !== '' ? `max ${fmt.num(Number(max))}` : null].filter(Boolean).join(' · '),
};

export default h;
