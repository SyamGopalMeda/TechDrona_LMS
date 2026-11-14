// Tech Drona portal: dependency-free, accessible charts (owned by the Dashboard agent).
// Every chart: an aria-labelled <figure>, a visually-hidden data table fallback, hover/focus tooltips,
// colours from CSS tokens only (var(--td-...)), and an empty state when there is no data.
// Colour by job: one measure = one hue (--td-brand); a target/benchmark is an outline, never a second hue;
// status hues (good/warn/bad) are reserved for state and always ship with a text label.
import { h, fmt } from './h.js';

let uid = 0;
const nextId = (p) => `tdc-${p}-${++uid}`;
const s = (tag, attrs, ...kids) => h('svg:' + tag, attrs, ...kids);

const TONE = {
  good: 'var(--td-good)', warn: 'var(--td-warn)', bad: 'var(--td-bad)', info: 'var(--td-info)',
  brand: 'var(--td-brand)', brand2: 'var(--td-brand-2)', accent: 'var(--td-accent)',
  neutral: 'var(--td-muted)', muted: 'var(--td-muted)',
};
// Fixed categorical order (never cycled past 4 — extra items fold into "Other" by the caller).
const SERIES = ['var(--td-brand)', 'var(--td-accent)', 'var(--td-info)', 'var(--td-brand-2)'];
const toneColor = (t, i = 0) => TONE[t] || SERIES[i % SERIES.length];
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const defFmt = (v) => fmt.num(v);

/* ---------- shared pieces ---------- */
function figure(kind, label, ...kids) {
  return h('figure', { class: `tdc tdc-${kind}`, role: 'group', 'aria-label': label }, ...kids);
}

/**
 * emptyChart(text, {title?, action?: Node | {label, href}}) — a calm placeholder that says what to do next.
 * The old one-argument form still works.
 */
export function emptyChart(text = 'No data yet', { title, action } = {}) {
  let act = null;
  if (action instanceof Node) act = action;
  else if (action && action.label) act = h('a', { class: 'td-btn td-btn--secondary td-btn--sm tdc-empty-act', href: action.href || '#/' }, action.label);
  return h('div', { class: 'tdc tdc-empty', role: 'note' },
    h('span', { class: 'tdc-empty-mark', 'aria-hidden': 'true', html: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>' }),
    h('div', { class: 'tdc-empty-body' },
      title ? h('strong', { class: 'tdc-empty-title' }, title) : null,
      h('span', null, text),
      act));
}

function srTable(caption, headers, rows) {
  // the 1px clip box is a div: a <table> ignores width:1px and its min-content width leaked page overflow (plan funnel at 360px)
  return h('div', { class: 'tdc-sr' }, h('table', null,
    h('caption', null, caption),
    h('thead', null, h('tr', null, headers.map((x) => h('th', { scope: 'col' }, x)))),
    h('tbody', null, rows.map((r) => h('tr', null, r.map((c, i) => (i === 0 ? h('th', { scope: 'row' }, c) : h('td', null, c))))))));
}

function tooltip(host) {
  const tip = h('div', { class: 'tdc-tip', 'aria-hidden': 'true', hidden: true });
  host.appendChild(tip);
  return {
    show(content, x, y) {
      tip.replaceChildren(...[].concat(content).filter(Boolean));
      tip.hidden = false;
      const W = host.clientWidth || 300;
      const tw = tip.offsetWidth, th = tip.offsetHeight;
      let left = x + 14;
      if (left + tw > W) left = Math.max(0, x - tw - 14);
      tip.style.left = left + 'px';
      tip.style.top = Math.max(0, y - th - 10) + 'px';
    },
    hide() { tip.hidden = true; },
  };
}
function relPos(host, e) {
  const r = host.getBoundingClientRect();
  if (e && 'clientX' in e && e.clientX) return [e.clientX - r.left, e.clientY - r.top];
  const t = (e && e.currentTarget && e.currentTarget.getBoundingClientRect) ? e.currentTarget.getBoundingClientRect() : r;
  return [t.left - r.left + t.width / 2, t.top - r.top];
}
const tipLine = (label, value, color) => h('div', { class: 'tdc-tip-row' },
  color ? h('span', { class: 'tdc-key', style: { background: color } }) : null,
  h('span', { class: 'tdc-tip-label' }, label),
  h('strong', null, value));

/** Redraw an SVG at the host's real pixel width so text stays its true size at every breakpoint. */
function responsive(host, draw) {
  let last = 0, seen = false;
  const run = () => {
    const w = Math.round(host.clientWidth);
    if (!w) return;
    seen = true;
    if (Math.abs(w - last) < 2) return;
    last = w;
    draw(w);
  };
  draw(640);
  if (typeof ResizeObserver !== 'undefined') {
    // Redraw on the next frame so a redraw never re-triggers the observer in the same loop.
    let raf = 0;
    const ro = new ResizeObserver(() => {
      if (seen && !host.isConnected) { ro.disconnect(); return; }
      cancelAnimationFrame(raf); raf = requestAnimationFrame(run);
    });
    ro.observe(host);
  } else {
    requestAnimationFrame(run);
  }
}

/** Axis ticks on a 1-2-5 ladder, so labels are always round, distinct numbers (never 2.5 shown as "3"). */
function niceTicks(maxVal, target = 4) {
  const v = maxVal > 0 ? maxVal : 1;
  const raw = v / target;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / p;
  let step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
  if (step < 1) step = 1; // counts are whole numbers
  const max = Math.ceil(v / step) * step;
  const ticks = [];
  for (let t = 0; t <= max + 1e-9; t += step) ticks.push(t);
  return { max, ticks };
}
const compact = (v) => (v >= 1e7 ? (v / 1e7).toFixed(1).replace(/\.0$/, '') + 'Cr'
  : v >= 1e5 ? (v / 1e5).toFixed(1).replace(/\.0$/, '') + 'L'
  : v >= 1e4 ? (v / 1e3).toFixed(0) + 'K' : fmt.num(v));
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const shortDate = (d) => {
  const t = Date.parse(String(d).slice(0, 10) + 'T00:00:00Z');
  if (Number.isNaN(t)) return String(d);
  const dt = new Date(t);
  return `${dt.getUTCDate()} ${MONTHS[dt.getUTCMonth()]}`;
};

function legend(items) {
  return h('ul', { class: 'tdc-legend' }, items.map((it) =>
    h('li', null, h('span', { class: ['tdc-key', it.hollow && 'tdc-key-hollow'], style: it.hollow ? { borderColor: it.color } : { background: it.color } }), it.label)));
}

/* ---------- barChart ---------- */
/**
 * Horizontal bars. data:[{label, value, secondary?, sub?, href?, tone?}] — `secondary` (e.g. target) is drawn as an
 * outlined track behind the solid `value` bar (e.g. enrolled), and the value cell shows "value / secondary · pct".
 */
export function barChart({ data = [], format = defFmt, onClick, label = 'Bar chart', valueLabel = 'Value',
  secondaryLabel = 'Target', empty = 'No data yet', max: maxIn } = {}) {
  const rows = (data || []).filter((d) => d && (isNum(d.value) || isNum(d.secondary)));
  if (!rows.length) return typeof empty === 'string' ? emptyChart(empty) : empty;
  const hasSec = rows.some((d) => isNum(d.secondary));
  const max = maxIn || Math.max(1, ...rows.map((d) => Math.max(d.value || 0, d.secondary || 0)));
  const host = figure('bar', label);
  const tip = tooltip(host);
  if (hasSec) host.appendChild(legend([{ label: valueLabel, color: SERIES[0] }, { label: secondaryLabel, color: 'var(--td-border-strong, var(--td-muted))', hollow: true }]));
  const list = h('ul', { class: 'tdc-bars', 'aria-hidden': onClick ? null : 'true' });
  rows.forEach((d) => {
    const v = isNum(d.value) ? d.value : 0;
    const pctOf = d.secondary ? v / d.secondary : null;
    const tipContent = () => [h('div', { class: 'tdc-tip-title' }, d.label),
      tipLine(valueLabel, format(d.value), SERIES[0]),
      hasSec ? tipLine(secondaryLabel, isNum(d.secondary) ? format(d.secondary) : 'not set') : null,
      pctOf !== null ? tipLine('Progress', fmt.pct(pctOf)) : null,
      d.sub ? h('div', { class: 'tdc-tip-sub' }, d.sub) : null];
    const valueText = hasSec ? `${format(d.value)} / ${isNum(d.secondary) ? format(d.secondary) : '—'}` : format(d.value);
    const li = h('li', {
      class: ['tdc-bar-row', onClick && 'is-click'],
      tabindex: onClick ? '0' : null, role: onClick ? 'button' : null,
      'aria-label': onClick ? `${d.label}: ${valueText}${pctOf !== null ? ` (${fmt.pct(pctOf)})` : ''}. Open.` : null,
      onClick: onClick ? () => onClick(d) : null,
      onKeydown: onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(d); } } : null,
      onPointermove: (e) => { const [x, y] = relPos(host, e); tip.show(tipContent(), x, y); },
      onPointerleave: () => tip.hide(),
      onFocus: (e) => { const [x, y] = relPos(host, e); tip.show(tipContent(), x, y); },
      onBlur: () => tip.hide(),
    },
    h('span', { class: 'tdc-bar-label', title: d.label }, h('span', { class: 'tdc-bar-name' }, d.label), d.sub ? h('small', null, d.sub) : null),
    h('span', { class: 'tdc-bar-track' },
      isNum(d.secondary) ? h('span', { class: 'tdc-bar-sec', style: { width: Math.min(100, (d.secondary / max) * 100) + '%' } }) : null,
      v > 0 ? h('span', { class: 'tdc-bar-fill', style: { width: Math.max(0.8, Math.min(100, (v / max) * 100)) + '%', background: d.tone ? toneColor(d.tone) : SERIES[0] } }) : null),
    h('span', { class: 'tdc-bar-value' }, valueText, pctOf !== null ? h('small', null, fmt.pct(pctOf)) : null));
    list.appendChild(li);
  });
  host.appendChild(list);
  host.appendChild(srTable(label, hasSec ? ['Name', valueLabel, secondaryLabel] : ['Name', valueLabel],
    rows.map((d) => (hasSec ? [d.label, format(d.value), isNum(d.secondary) ? format(d.secondary) : '—'] : [d.label, format(d.value)]))));
  return host;
}

/* ---------- shared x/y frame for the SVG charts ---------- */
function frame(svg, { W, H, m, xs, yTicks, Y, X, iw }) {
  yTicks.forEach((v) => {
    svg.appendChild(s('line', { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: v === 0 ? 'tdc-base' : 'tdc-grid' }));
    svg.appendChild(s('text', { x: m.l - 8, y: Y(v) + 4, 'text-anchor': 'end', class: 'tdc-axis' }, compact(v)));
  });
  const nTicks = Math.max(2, Math.min(xs.length, Math.floor(iw / 84)));
  const seen = new Set();
  for (let k = 0; k < nTicks; k++) {
    const i = xs.length === 1 ? 0 : Math.round((k / (nTicks - 1)) * (xs.length - 1));
    if (seen.has(i)) continue; seen.add(i);
    const anchor = xs.length === 1 ? 'middle' : i === 0 ? 'start' : i === xs.length - 1 ? 'end' : 'middle';
    svg.appendChild(s('text', { x: X(i), y: H - 8, 'text-anchor': anchor, class: 'tdc-axis' }, shortDate(xs[i])));
  }
}

/* ---------- lineChart ---------- */
/** series:[{name, points:[{x:'YYYY-MM-DD', y}], tone?}] — area for a single series, lines for several. One y-axis. */
export function lineChart({ series = [], format = defFmt, label = 'Trend', height = 220, empty = 'No activity recorded yet' } = {}) {
  const ser = (series || []).filter((x) => x && Array.isArray(x.points) && x.points.length).slice(0, 4);
  const xs = [...new Set(ser.flatMap((x) => x.points.map((p) => String(p.x))))].sort();
  const allY = ser.flatMap((x) => x.points.map((p) => p.y)).filter(isNum);
  if (!xs.length || !allY.length) return emptyChart(empty);
  const host = figure('line', label);
  if (ser.length > 1) host.appendChild(legend(ser.map((x, i) => ({ label: x.name, color: toneColor(x.tone, i) }))));
  const plot = h('div', { class: 'tdc-plot' });
  host.appendChild(plot);
  const tip = tooltip(plot);
  const lookup = ser.map((x) => new Map(x.points.map((p) => [String(p.x), p.y])));
  const { max: yMax, ticks: yTicks } = niceTicks(Math.max(...allY, 0));
  const titleId = nextId('t');

  responsive(plot, (W) => {
    const H = height, m = { l: 44, r: 16, t: 12, b: 28 };
    const iw = Math.max(10, W - m.l - m.r), ih = H - m.t - m.b;
    const X = (i) => m.l + (xs.length === 1 ? iw / 2 : (i / (xs.length - 1)) * iw);
    const Y = (v) => m.t + ih - (v / yMax) * ih;
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H, role: 'img', 'aria-labelledby': titleId, class: 'tdc-svg' },
      s('title', { id: titleId }, `${label}: ${ser.map((x) => x.name).join(', ')}, ${shortDate(xs[0])} to ${shortDate(xs[xs.length - 1])}`));
    frame(svg, { W, H, m, xs, yTicks, Y, X, iw });
    ser.forEach((x, si) => {
      const color = toneColor(x.tone, si);
      const pts = xs.map((d, i) => [i, lookup[si].get(d)]).filter(([, y]) => isNum(y));
      if (!pts.length) return;
      const dLine = pts.map(([i, y], k) => `${k ? 'L' : 'M'}${X(i).toFixed(1)},${Y(y).toFixed(1)}`).join('');
      if (ser.length === 1 && pts.length > 1) {
        const dArea = `${dLine}L${X(pts[pts.length - 1][0]).toFixed(1)},${Y(0)}L${X(pts[0][0]).toFixed(1)},${Y(0)}Z`;
        svg.appendChild(s('path', { d: dArea, class: 'tdc-area', style: { fill: color } }));
      }
      svg.appendChild(s('path', { d: dLine, class: 'tdc-line', style: { stroke: color } }));
      const [li, ly] = pts[pts.length - 1];
      svg.appendChild(s('circle', { cx: X(li), cy: Y(ly), r: 4, class: 'tdc-dot', style: { fill: color } }));
    });
    // Hover layer: crosshair + dots + tooltip; arrow keys when focused.
    const cross = s('line', { y1: m.t, y2: m.t + ih, class: 'tdc-cross', visibility: 'hidden' });
    const hoverDots = ser.map((x, si) => s('circle', { r: 4.5, class: 'tdc-dot', visibility: 'hidden', style: { fill: toneColor(x.tone, si) } }));
    svg.appendChild(cross); hoverDots.forEach((c) => svg.appendChild(c));
    let cur = xs.length - 1;
    const showAt = (i) => {
      cur = Math.max(0, Math.min(xs.length - 1, i));
      const cx = X(cur);
      cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('visibility', 'visible');
      let topY = m.t + ih;
      hoverDots.forEach((c, si) => {
        const y = lookup[si].get(xs[cur]);
        if (isNum(y)) { c.setAttribute('cx', cx); c.setAttribute('cy', Y(y)); c.setAttribute('visibility', 'visible'); topY = Math.min(topY, Y(y)); }
        else c.setAttribute('visibility', 'hidden');
      });
      const scale = (plot.clientWidth || W) / W;
      tip.show([h('div', { class: 'tdc-tip-title' }, fmt.date(xs[cur])),
        ...ser.map((x, si) => tipLine(x.name, format(lookup[si].get(xs[cur]) ?? null), ser.length > 1 ? toneColor(x.tone, si) : null))],
      cx * scale, topY * scale);
    };
    const hide = () => { cross.setAttribute('visibility', 'hidden'); hoverDots.forEach((c) => c.setAttribute('visibility', 'hidden')); tip.hide(); };
    const overlay = s('rect', {
      x: m.l, y: m.t, width: iw, height: ih, class: 'tdc-overlay', tabindex: '0', 'aria-label': `${label}. Use left and right arrow keys to read values.`,
      onPointermove: (e) => {
        const r = svg.getBoundingClientRect();
        const px = ((e.clientX - r.left) / r.width) * W;
        showAt(xs.length === 1 ? 0 : Math.round(((px - m.l) / iw) * (xs.length - 1)));
      },
      onPointerleave: hide, onFocus: () => showAt(cur), onBlur: hide,
      onKeydown: (e) => {
        if (e.key === 'ArrowLeft') { e.preventDefault(); showAt(cur - 1); }
        if (e.key === 'ArrowRight') { e.preventDefault(); showAt(cur + 1); }
      },
    });
    svg.appendChild(overlay);
    const old = plot.querySelector('svg');
    if (old) old.replaceWith(svg); else plot.prepend(svg);
  });
  host.appendChild(srTable(label, ['Date', ...ser.map((x) => x.name)],
    xs.map((d) => [fmt.date(d), ...lookup.map((mp) => format(mp.get(d) ?? null))])));
  return host;
}

/* ---------- columnChart ---------- */
/**
 * Vertical columns for counts per day/week. points:[{x:'YYYY-MM-DD', y}], name = what is counted.
 * xLabel(x) formats the tooltip title (default: the date; pass one for "Week of …").
 */
export function columnChart({ points = [], name = 'Value', format = defFmt, label = 'Columns', height = 220, xLabel, empty = 'No activity recorded yet' } = {}) {
  const pts = (points || []).filter((p) => p && p.x);
  const ys = pts.map((p) => p.y).filter(isNum);
  if (!pts.length || !ys.length) return emptyChart(empty);
  const xs = pts.map((p) => String(p.x));
  const host = figure('column', label);
  const plot = h('div', { class: 'tdc-plot' });
  host.appendChild(plot);
  const tip = tooltip(plot);
  const { max: yMax, ticks: yTicks } = niceTicks(Math.max(...ys, 0));
  const titleId = nextId('t');
  const title = (x) => (xLabel ? xLabel(x) : fmt.date(x));

  responsive(plot, (W) => {
    const H = height, m = { l: 44, r: 16, t: 12, b: 28 };
    const iw = Math.max(10, W - m.l - m.r), ih = H - m.t - m.b;
    const slot = iw / xs.length;
    const gap = Math.min(2, slot * 0.25);
    const bw = Math.max(1, Math.min(28, slot - gap));
    const X = (i) => m.l + slot * i + slot / 2;
    const Y = (v) => m.t + ih - (v / yMax) * ih;
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H, role: 'img', 'aria-labelledby': titleId, class: 'tdc-svg' },
      s('title', { id: titleId }, `${label}, ${shortDate(xs[0])} to ${shortDate(xs[xs.length - 1])}. Total ${format(ys.reduce((a, b) => a + b, 0))}.`));
    frame(svg, { W, H, m, xs, yTicks, Y, X, iw });
    const bars = pts.map((p, i) => {
      const v = isNum(p.y) ? p.y : 0;
      if (!(v > 0)) return null;
      const x0 = X(i) - bw / 2, y0 = Y(v), hgt = Y(0) - y0;
      const r = Math.min(4, bw / 2, hgt);
      // rounded data-end (top), square baseline
      const d = `M${x0},${Y(0)}V${y0 + r}Q${x0},${y0} ${x0 + r},${y0}H${x0 + bw - r}Q${x0 + bw},${y0} ${x0 + bw},${y0 + r}V${Y(0)}Z`;
      const el = s('path', { d, class: 'tdc-col', style: { fill: SERIES[0] } });
      svg.appendChild(el);
      return el;
    });
    let cur = xs.length - 1;
    const showAt = (i) => {
      cur = Math.max(0, Math.min(xs.length - 1, i));
      bars.forEach((b, k) => b && b.classList.toggle('is-dim', k !== cur));
      const v = pts[cur].y;
      const scale = (plot.clientWidth || W) / W;
      tip.show([h('div', { class: 'tdc-tip-title' }, title(xs[cur])), tipLine(name, format(isNum(v) ? v : 0))],
        X(cur) * scale, Y(isNum(v) ? v : 0) * scale);
    };
    const hide = () => { bars.forEach((b) => b && b.classList.remove('is-dim')); tip.hide(); };
    svg.appendChild(s('rect', {
      x: m.l, y: m.t, width: iw, height: ih, class: 'tdc-overlay', tabindex: '0', 'aria-label': `${label}. Use left and right arrow keys to read values.`,
      onPointermove: (e) => {
        const r = svg.getBoundingClientRect();
        const px = ((e.clientX - r.left) / r.width) * W;
        showAt(Math.floor((px - m.l) / slot));
      },
      onPointerleave: hide, onFocus: () => showAt(cur), onBlur: hide,
      onKeydown: (e) => {
        if (e.key === 'ArrowLeft') { e.preventDefault(); showAt(cur - 1); }
        if (e.key === 'ArrowRight') { e.preventDefault(); showAt(cur + 1); }
      },
    }));
    const old = plot.querySelector('svg');
    if (old) old.replaceWith(svg); else plot.prepend(svg);
  });
  host.appendChild(srTable(label, ['Date', name], pts.map((p) => [title(p.x), format(isNum(p.y) ? p.y : 0)])));
  return host;
}

/* ---------- paceMeter ---------- */
/**
 * Enrolled vs target with an "expected by today" tick. All three numbers come from the API (summary.expected_now).
 * tone: 'good' | 'bad' | undefined (brand). Returns a labelled meter; text carries the meaning, colour only supports it.
 */
export function paceMeter({ done, target, expected, tone, format = defFmt, label = 'Progress to target' } = {}) {
  if (!(target > 0)) return null;
  const d = isNum(done) ? done : 0;
  const frac = Math.max(0, Math.min(1, d / target));
  const exp = isNum(expected) && expected > 0 ? Math.max(0, Math.min(1, expected / target)) : null;
  const text = `${format(d)} of ${format(target)} enrolled (${fmt.pct(d / target)})${exp !== null ? `; about ${format(expected)} expected by today` : ''}`;
  return h('div', { class: ['tdc-pace', tone && `tdc-pace--${tone}`], role: 'img', 'aria-label': `${label}: ${text}` },
    h('div', { class: 'tdc-pace-track' },
      frac > 0 ? h('span', { class: 'tdc-pace-fill', style: { width: Math.max(1.2, frac * 100) + '%' } }) : null,
      exp !== null ? h('span', { class: 'tdc-pace-mark', style: { left: exp * 100 + '%' } }) : null),
    h('div', { class: 'tdc-pace-scale', 'aria-hidden': 'true' },
      h('span', null, `${format(d)} enrolled · ${fmt.pct(d / target)}`),
      exp !== null ? h('span', { class: 'tdc-pace-exp' }, `Expected by today ≈ ${format(expected)}`) : null,
      h('span', null, `Target ${format(target)}`)));
}

/* ---------- donut ---------- */
/** data:[{label, value, tone}] — parts of one whole. */
export function donut({ data = [], centerLabel = 'Total', format = defFmt, label = 'Breakdown', empty = 'Nothing to show yet' } = {}) {
  const rows = (data || []).filter((d) => d && isNum(d.value) && d.value > 0);
  const total = rows.reduce((a, d) => a + d.value, 0);
  if (!rows.length || !total) return emptyChart(empty);
  const host = figure('donut', label);
  const tip = tooltip(host);
  const titleId = nextId('t');
  const R = 46, C = 2 * Math.PI * R, GAP = rows.length > 1 ? 2 : 0;
  const svg = s('svg', { viewBox: '0 0 120 120', class: 'tdc-svg tdc-donut-svg', role: 'img', 'aria-labelledby': titleId },
    s('title', { id: titleId }, `${label}: ` + rows.map((d) => `${d.label} ${format(d.value)}`).join(', ')),
    s('circle', { cx: 60, cy: 60, r: R, class: 'tdc-ring-bg' }));
  let acc = 0;
  rows.forEach((d, i) => {
    const len = (d.value / total) * C;
    const color = toneColor(d.tone, i);
    const seg = s('circle', {
      cx: 60, cy: 60, r: R, class: 'tdc-seg', tabindex: '0',
      'stroke-dasharray': `${Math.max(0.5, len - GAP)} ${C - Math.max(0.5, len - GAP)}`,
      'stroke-dashoffset': -acc, transform: 'rotate(-90 60 60)', style: { stroke: color },
      'aria-label': `${d.label}: ${format(d.value)} (${fmt.pct(d.value / total)})`,
    });
    const show = (e) => { const [x, y] = relPos(host, e); tip.show([h('div', { class: 'tdc-tip-title' }, d.label), tipLine(format(d.value), fmt.pct(d.value / total), color)], x, y); };
    seg.addEventListener('pointermove', show); seg.addEventListener('focus', show);
    seg.addEventListener('pointerleave', () => tip.hide()); seg.addEventListener('blur', () => tip.hide());
    svg.appendChild(seg);
    acc += len;
  });
  svg.appendChild(s('text', { x: 60, y: 60, 'text-anchor': 'middle', class: 'tdc-center-val' }, compact(total)));
  svg.appendChild(s('text', { x: 60, y: 76, 'text-anchor': 'middle', class: 'tdc-center-lbl' }, centerLabel));
  host.appendChild(h('div', { class: 'tdc-donut-wrap' }, svg,
    h('ul', { class: 'tdc-donut-legend' }, rows.map((d, i) => h('li', null,
      h('span', { class: 'tdc-key', style: { background: toneColor(d.tone, i) } }),
      h('span', { class: 'tdc-dl-label' }, d.label),
      h('span', { class: 'tdc-dl-val' }, format(d.value), h('small', null, fmt.pct(d.value / total))))))));
  host.appendChild(srTable(label, ['Part', 'Value', 'Share'], rows.map((d) => [d.label, format(d.value), fmt.pct(d.value / total)])));
  return host;
}

/* ---------- funnel ---------- */
/** steps:[{label, value, basis?, hint?}] — e.g. eligible → reached → enrolled. renderBasis(basis) → Node (pass ui.provenance). */
export function funnel({ steps = [], format = defFmt, label = 'Funnel', renderBasis, empty = 'Nothing to show yet' } = {}) {
  const rows = (steps || []).filter(Boolean);
  if (!rows.length) return emptyChart(empty);
  const max = Math.max(1, ...rows.map((d) => (isNum(d.value) ? d.value : 0)));
  const host = figure('funnel', label);
  const tip = tooltip(host);
  const basisNode = (b) => (b ? (renderBasis ? renderBasis(b) : h('span', { class: 'tdc-pill' }, b)) : null);
  const list = h('ol', { class: 'tdc-funnel-list' });
  rows.forEach((d, i) => {
    const known = isNum(d.value);
    const prev = i > 0 ? rows[i - 1].value : null;
    const conv = known && isNum(prev) && prev > 0 && d.value > 0 ? d.value / prev : null;
    const convDigits = conv !== null && conv < 0.1 ? 1 : 0;
    const tipContent = () => [h('div', { class: 'tdc-tip-title' }, d.label), tipLine('Count', known ? format(d.value) : '— (pending)'),
      conv !== null ? tipLine(`Of ${rows[i - 1].label.toLowerCase()}`, fmt.pct(conv, convDigits)) : null];
    list.appendChild(h('li', {
      class: 'tdc-funnel-step', tabindex: '0',
      'aria-label': `${d.label}: ${known ? format(d.value) : 'unknown, pending'}${conv !== null ? `, ${fmt.pct(conv, convDigits)} of previous step` : ''}`,
      onPointermove: (e) => { const [x, y] = relPos(host, e); tip.show(tipContent(), x, y); },
      onPointerleave: () => tip.hide(),
      onFocus: (e) => { const [x, y] = relPos(host, e); tip.show(tipContent(), x, y); }, onBlur: () => tip.hide(),
    },
    h('div', { class: 'tdc-funnel-head' },
      h('span', { class: 'tdc-funnel-label' }, d.label),
      h('span', { class: 'tdc-funnel-val' }, known ? format(d.value) : '—', ' ', known ? basisNode(d.basis) : basisNode('pending'))),
    h('div', { class: 'tdc-funnel-track' },
      known && d.value > 0 ? h('span', { class: 'tdc-funnel-fill', style: { width: Math.max(1, (d.value / max) * 100) + '%' } }) : null),
    conv !== null ? h('span', { class: 'tdc-funnel-conv' }, `${fmt.pct(conv, convDigits)} of ${rows[i - 1].label.toLowerCase()}`)
      : (d.hint ? h('span', { class: 'tdc-funnel-conv' }, d.hint) : null)));
  });
  host.appendChild(list);
  host.appendChild(srTable(label, ['Step', 'Count', 'Basis'], rows.map((d) => [d.label, isNum(d.value) ? format(d.value) : '—', d.basis || (isNum(d.value) ? '' : 'pending')])));
  return host;
}

/* ---------- sparkline ---------- */
/** points: number[] or [{x,y}] */
export function sparkline(points, { label = 'Trend', tone = 'brand' } = {}) {
  const ys = (points || []).map((p) => (isNum(p) ? p : p && p.y)).filter(isNum);
  if (ys.length < 2) return h('span', { class: 'tdc-spark tdc-spark-empty', 'aria-label': `${label}: not enough data` }, '—');
  const max = Math.max(...ys), min = Math.min(0, ...ys), span = max - min || 1;
  const W = 100, H = 28;
  const d = ys.map((y, i) => `${i ? 'L' : 'M'}${((i / (ys.length - 1)) * W).toFixed(2)},${(H - 2 - ((y - min) / span) * (H - 4)).toFixed(2)}`).join('');
  return s('svg', { class: 'tdc-spark', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', role: 'img', 'aria-label': `${label}: from ${fmt.num(ys[0])} to ${fmt.num(ys[ys.length - 1])}` },
    s('title', null, `${label}: ${ys.map((y) => fmt.num(y)).join(', ')}`),
    s('path', { d, class: 'tdc-spark-line', 'vector-effect': 'non-scaling-stroke', style: { stroke: toneColor(tone) } }));
}

/* ---------- progressRing ---------- */
/** pct is a fraction (0.42) or null (unknown → "—"). */
export function progressRing({ pct, label = 'Progress', tone, size } = {}) {
  const known = isNum(pct);
  const R = 50, C = 2 * Math.PI * R;
  const frac = known ? Math.max(0, Math.min(1, pct)) : 0;
  const color = toneColor(tone || (known && pct >= 1 ? 'good' : 'brand'));
  const text = known ? fmt.pct(pct) : '—';
  return h('figure', { class: 'tdc tdc-ring', style: size ? { width: size + 'px' } : null, role: 'img', 'aria-label': `${label}: ${known ? text : 'not set yet'}` },
    s('svg', { viewBox: '0 0 120 120', class: 'tdc-svg', 'aria-hidden': 'true' },
      s('circle', { cx: 60, cy: 60, r: R, class: 'tdc-ring-bg' }),
      frac > 0 ? s('circle', { cx: 60, cy: 60, r: R, class: 'tdc-ring-fg', transform: 'rotate(-90 60 60)', 'stroke-dasharray': `${frac * C} ${C}`, style: { stroke: color } }) : null,
      s('text', { x: 60, y: 62, 'text-anchor': 'middle', 'dominant-baseline': 'middle', class: 'tdc-ring-val' }, text),
      s('text', { x: 60, y: 84, 'text-anchor': 'middle', class: 'tdc-ring-lbl' }, known ? label : 'No target yet')));
}

export default { barChart, lineChart, columnChart, paceMeter, donut, funnel, sparkline, progressRing, emptyChart };
