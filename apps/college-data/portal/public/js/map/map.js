// Tech Drona portal — map component (map agent; see CONTRACT.md).
//
// createMap(el, {onSelectDistrict(id), onSelectCity(districtId, cityId), onSelectCollege(id), onReset()}) ->
//   {setColleges(rows), focusState(), focusDistrict(id), focusCity(districtId, cityId), focusCollege(id),
//    highlight(id|null)   // a college id, city id or district id
//    invalidateSize(), destroy(),
//    getUnplacedCount(),            // colleges with null lat/lng (not drawn)
//    setPlaces({districts, cities}), // optional: /api/meta lists, used only for nicer display names
//    setShowClosed(bool), getClosedCount(),
//    setScope({all, ids, target, groups})}   // global district scope: target districts are outlined, districts
//                                            // outside the selection dimmed; the state view frames the selection
//
// Levels of detail (one marker system at a time, never two overlapping ones):
//   state view, zoomed out  -> one bubble per district (ring = share on track / behind / no target)
//   district view or zoom 9.5+ -> one bubble per city (a city with a single college is drawn as its pin)
//   zoom 12+ / city / college -> water-drop pins; pins that share a spot are fanned out ("spiderfied")
//
// Possibly-closed and closed colleges are hidden by default (a map control and the geo panels toggle them).
// The choice is stored in localStorage 'td.map.showClosed' and broadcast as the window event
// 'td:closed-visibility' ({detail:{show}}), so the map and the panels stay in sync without the shell.
//
// Gestures (no dependency, "gestureHandling"-like): with a mouse the scroll wheel scrolls the page until the map
// is clicked / focused (or Ctrl/⌘ is held — a hint says so); on touch (pointer:coarse) one finger scrolls the
// page and two fingers pan/zoom the map. Touch taps show the info as a popup first; a second tap (or the
// popup's button) opens the place. Pins and bubbles get ≥44px hit areas on touch.
//
// Basemap: OpenStreetMap standard tiles (keyless) by default. An optional keyed provider can be configured —
// handlers.tileProvider / window.TD_CONFIG.tileProvider = {url, darkUrl?, key?, attribution, maxZoom?} (url may use
// {key} and {r}), or <meta name="td-tiles-url|td-tiles-url-dark|td-tiles-key|td-tiles-attribution">, or the CARTO
// shorthand (handlers.cartoKey / TD_CONFIG.cartoKey / <meta name="td-carto-key">). If the keyed provider fails
// (≥50% tile errors or nothing loads in 8 s) the map falls back to OSM automatically; if OSM fails too a
// "Street map unavailable · Retry" message is shown (also retried on the window 'online' event). No key is
// committed. Integer zoom levels keep 256px tiles crisp (no fractional upscaling); {r} gives @2x tiles for keyed
// providers on high-DPR screens. Tile requests send referrerPolicy strict-origin-when-cross-origin (OSM policy).
//
// Leaflet 1.9.4 is vendored in /vendor/leaflet. index.html loads it as a classic script; if window.L is
// missing (e.g. demo page or dynamic import order) this module loads it itself before exporting.

const VENDOR = new URL('../../vendor/leaflet/', import.meta.url);
const GEOJSON_URL = new URL('../../data/ap_districts.geojson', import.meta.url);

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src; s.onload = resolve; s.onerror = () => reject(new Error('Failed to load ' + src));
    document.head.appendChild(s);
  });
}
if (!document.querySelector('link[href*="leaflet.css"]')) {
  const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = new URL('leaflet.css', VENDOR).href;
  document.head.appendChild(l);
}
if (!window.L) {
  // index.html may still be executing a deferred <script src=leaflet.js>; wait briefly before loading our own copy.
  const existing = document.querySelector('script[src*="leaflet.js"]');
  if (existing) await new Promise((r) => { existing.addEventListener('load', r, { once: true }); setTimeout(r, 4000); });
  if (!window.L) await loadScript(new URL('leaflet.js', VENDOR).href);
}
const L = window.L;

let geojsonPromise = null;
function loadDistricts() {
  if (!geojsonPromise) {
    geojsonPromise = fetch(GEOJSON_URL).then((r) => {
      if (!r.ok) throw new Error('District boundaries HTTP ' + r.status);
      return r.json();
    }).catch((e) => { geojsonPromise = null; throw e; });
  }
  return geojsonPromise;
}

// ---------- closed-college visibility (shared with the geo panels) ----------
export const CLOSED_EVENT = 'td:closed-visibility';
const CLOSED_KEY = 'td.map.showClosed';
export const isClosed = (r) => r && (r.op_status === 'possibly_closed' || r.op_status === 'closed');
export function getShowClosed() {
  try { return localStorage.getItem(CLOSED_KEY) === '1'; } catch { return false; }
}
export function setShowClosedPref(show) {
  try { localStorage.setItem(CLOSED_KEY, show ? '1' : '0'); } catch { /* private mode */ }
  window.dispatchEvent(new CustomEvent(CLOSED_EVENT, { detail: { show: !!show } }));
}

// ---------- small helpers ----------
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf = new Intl.NumberFormat('en-IN');
const num = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : nf.format(v));
const plural = (n, one, many) => `${num(n)} ${n === 1 ? one : (many || one + 's')}`;
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const placed = (r) => isNum(r.lat) && isNum(r.lng);
const titleCase = (s) => s.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

const mq = (q) => !!window.matchMedia?.(q).matches;
const coarse = () => mq('(pointer: coarse)');
const IS_MAC = /Mac|iPhone|iPad|iPod/i.test((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || navigator.userAgent || '');
const TOUCH_HIT = 44;

// Pace bucket from the server's pace_status (too_early / partial_target are never "behind"); on_track is the
// legacy boolean (null while too early / no usable target) and is only used when pace_status is missing.
function progressOf(r) {
  if (!r.target) return 'none';
  switch (r.pace_status) {
    case 'behind': return 'bad';
    case 'on_track': case 'met': case 'exceeded': return 'good';
    case 'too_early': case 'partial_target': return 'early';
    case 'no_target': case 'zero_target': return 'none';
    default: return r.on_track === true ? 'good' : r.on_track === false ? 'bad' : 'early';
  }
}
const PROGRESS_LABEL = { good: 'On track', bad: 'Behind', early: 'Too early to tell', none: 'No target yet' };

// Interior label point: best point on a coarse grid maximising distance to the outline (a cheap "polylabel").
function ringsOf(geom) { return geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates; }
function inRing(x, y, r) {
  let c = false;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
    const [xi, yi] = r[i], [xj, yj] = r[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}
function segDist(x, y, a, b) {
  let dx = b[0] - a[0], dy = b[1] - a[1], t = 0;
  if (dx || dy) t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)));
  const px = a[0] + t * dx - x, py = a[1] + t * dy - y;
  return Math.sqrt(px * px + py * py);
}
function labelPoint(geom) {
  let best = null, bestArea = -1;
  for (const poly of ringsOf(geom)) { // largest outer ring
    const r = poly[0]; let a = 0;
    for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += (r[j][0] + r[i][0]) * (r[j][1] - r[i][1]);
    if (Math.abs(a) > bestArea) { bestArea = Math.abs(a); best = poly; }
  }
  const outer = best[0];
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of outer) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y); }
  let bx = (minX + maxX) / 2, by = (minY + maxY) / 2, bd = -1;
  const N = 18;
  for (let i = 1; i < N; i++) for (let j = 1; j < N; j++) {
    const x = minX + ((maxX - minX) * i) / N, y = minY + ((maxY - minY) * j) / N;
    if (!inRing(x, y, outer) || best.slice(1).some((h) => inRing(x, y, h))) continue;
    let d = Infinity;
    for (let k = 0, m = outer.length - 1; k < outer.length; m = k++) d = Math.min(d, segDist(x, y, outer[m], outer[k]));
    if (d > bd) { bd = d; bx = x; by = y; }
  }
  return L.latLng(by, bx);
}

// ---------- icons ----------
const DROP = 'M12 0C5.37 0 0 5.3 0 11.86c0 8.62 10.36 20.6 11.2 21.57a1.06 1.06 0 0 0 1.6 0C13.64 32.46 24 20.48 24 11.86 24 5.3 18.63 0 12 0z';
const CROSS = 'M9 8.8l6 6M15 8.8l-6 6';
function pinIcon(r, { selected = false, highlighted = false, faded = false } = {}) {
  const closed = isClosed(r);
  const prog = closed ? 'closed' : progressOf(r);
  const approx = r.geo_precision === 'town' || r.geo_precision === 'district';
  const exams = !closed && r.exam_state === 'in_exams';
  const w = selected ? 36 : 26, h = Math.round(w * 34 / 24);
  // touch: an invisible ≥44px hit box with the drop drawn at its bottom centre (the tip stays on the spot)
  const touch = coarse();
  const W = touch ? Math.max(w, TOUCH_HIT) : w, H = touch ? Math.max(h, TOUCH_HIT) : h;
  const cls = ['td-pin', `td-pin--${prog}`, approx && 'td-pin--approx', exams && 'td-pin--exams',
    selected && 'td-pin--selected', highlighted && 'is-hl', faded && 'td-pin--faded', touch && 'td-pin--touch'].filter(Boolean).join(' ');
  const html =
    `<span class="td-pin__in" style="width:${w}px;height:${h}px">` +
    (exams ? '<span class="td-pin__pulse" aria-hidden="true"></span>' : '') +
    `<svg class="td-pin__svg" viewBox="-1.5 -1.5 27 37" width="${w}" height="${h}" aria-hidden="true" focusable="false">` +
    `<path class="td-pin__body" d="${DROP}"/>` +
    (closed ? `<path class="td-pin__cross" d="${CROSS}"/>`
      : '<path class="td-pin__gloss" d="M5 7.5C6.6 4.2 9.6 2.6 12.6 2.6" fill="none"/><circle class="td-pin__dot" cx="12" cy="11.8" r="4.4"/>') +
    '</svg></span>';
  return L.divIcon({ className: cls, html, iconSize: [W, H], iconAnchor: [W / 2, H - 1], tooltipAnchor: [0, -h + 4], tdVisual: [w, h] });
}

function bubbleSize(n) { return Math.round(Math.min(52, 30 + Math.sqrt(n) * 3.4)); }
function bubbleIcon(group, { label = null, highlighted = false, kind = 'city' } = {}) {
  const n = group.rows.length;
  const size = bubbleSize(n);
  const hit = coarse() ? Math.max(size, TOUCH_HIT) : size;
  const pad = (hit - size) / 2;
  let good = 0, bad = 0, early = 0, exams = 0;
  for (const r of group.rows) {
    const p = isClosed(r) ? 'closed' : progressOf(r);
    if (p === 'good') good++; else if (p === 'bad') bad++; else if (p === 'early') early++;
    if (r.exam_state === 'in_exams' && !isClosed(r)) exams++;
  }
  const g = (good / n) * 100, b = g + (bad / n) * 100, e = b + (early / n) * 100;
  const html =
    `<span class="td-cluster__in" style="inset:${pad}px">` +
    (exams ? '<span class="td-cluster__exam" aria-hidden="true"></span>' : '') +
    `<span class="td-cluster__ring" style="--g:${g.toFixed(1)}%;--b:${b.toFixed(1)}%;--e:${e.toFixed(1)}%"></span>` +
    `<span class="td-cluster__core">${num(n)}</span>` +
    (label ? `<span class="td-cluster__label">${esc(label)}</span>` : '') +
    '</span>';
  return L.divIcon({
    className: ['td-cluster', `td-cluster--${kind}`, exams && 'td-cluster--exams', highlighted && 'is-hl'].filter(Boolean).join(' '),
    html, iconSize: [hit, hit], iconAnchor: [hit / 2, hit / 2], tooltipAnchor: [0, -size / 2], tdVisual: [size, size],
  });
}

const EYE = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';
const EYE_OFF = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path d="M3 3l18 18M10.6 5.1A10.6 10.6 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4M6.6 6.6C3.7 8.4 2 12 2 12s3.6 7 10 7a9.9 9.9 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

// ---------- the map ----------
export function createMap(el, handlers = {}) {
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const animate = () => !(reduceMotion && reduceMotion.matches);
  el.classList.add('td-map');

  // Integer zoom (zoomSnap 1): 256px raster tiles are drawn 1:1 instead of being upscaled at fractional zooms.
  // Wheel zoom and one-finger dragging start disabled; the gesture block below turns them on when appropriate.
  const map = L.map(el, {
    zoomControl: false, attributionControl: true, zoomSnap: 1, zoomDelta: 1, minZoom: 5, maxZoom: 18,
    worldCopyJump: false, preferCanvas: false, wheelPxPerZoomLevel: 90,
    scrollWheelZoom: false, dragging: !coarse(), touchZoom: true, closePopupOnClick: true,
    zoomAnimation: animate(), fadeAnimation: animate(), markerZoomAnimation: animate(),
  }).setView([16.4, 81.0], 7);
  const PREFIX = '<a href="https://leafletjs.com" title="A JavaScript library for interactive maps">Leaflet</a>';
  map.attributionControl.setPrefix(PREFIX);
  L.control.zoom({ position: 'topright', zoomInTitle: 'Zoom in', zoomOutTitle: 'Zoom out' }).addTo(map);

  for (const [name, z] of [['tdMask', 402], ['tdDistricts', 410]]) {
    map.createPane(name).style.zIndex = z;
  }

  // --- overlay UI owned by the map (hint bubble, tile-error message) ---
  const hintEl = L.DomUtil.create('div', 'td-map-hint', el);
  hintEl.setAttribute('aria-hidden', 'true');
  let hintT = null;
  function showHint(text) {
    if (hintEl.textContent !== text) hintEl.textContent = text;
    hintEl.classList.add('is-on');
    clearTimeout(hintT);
    hintT = setTimeout(() => hintEl.classList.remove('is-on'), 1600);
  }
  const tileMsg = L.DomUtil.create('div', 'td-map-tilemsg', el);
  tileMsg.setAttribute('role', 'status');
  tileMsg.hidden = true;
  L.DomEvent.disableClickPropagation(tileMsg);
  L.DomEvent.disableScrollPropagation(tileMsg);

  // --- base tiles, light/dark following the shell theme ---
  const isDark = () => {
    const t = document.documentElement.getAttribute('data-theme');
    if (t === 'dark') return true;
    if (t === 'light') return false;
    return mq('(prefers-color-scheme: dark)');
  };
  const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors<span class="td-attr-long"> (ODbL)</span>';
  const metaVal = (n) => (document.querySelector(`meta[name="${n}"]`)?.content || '').trim();
  function keyedProvider() {
    const cfg = handlers.tileProvider || window.TD_CONFIG?.tileProvider || null;
    if (cfg && cfg.url) return { kind: 'custom', url: cfg.url, darkUrl: cfg.darkUrl || null, key: cfg.key || '', attribution: cfg.attribution || OSM_ATTR, maxZoom: cfg.maxZoom || 19, subdomains: cfg.subdomains || 'abc' };
    if (metaVal('td-tiles-url')) return { kind: 'custom', url: metaVal('td-tiles-url'), darkUrl: metaVal('td-tiles-url-dark') || null, key: metaVal('td-tiles-key'), attribution: metaVal('td-tiles-attribution') || OSM_ATTR, maxZoom: 19, subdomains: 'abc' };
    // CARTO basemaps need a (free) key; without one CARTO serves "API key required" watermark tiles.
    const cartoKey = handlers.cartoKey || window.TD_CONFIG?.cartoKey || metaVal('td-carto-key');
    if (cartoKey) return { kind: 'carto', key: cartoKey };
    return null;
  }
  const provider = keyedProvider();
  let useOsm = !provider; // true after the keyed provider failed (automatic fallback)
  let tiles = null;
  let tilesArmed = false; // tiles are added after the first fit, so no throw-away zoom level is fetched
  const health = { ok: 0, err: 0, timer: null, failed: false };
  function makeTiles(dark) {
    const common = { maxZoom: 19, crossOrigin: true, referrerPolicy: 'strict-origin-when-cross-origin', detectRetina: false };
    if (provider && !useOsm) {
      if (provider.kind === 'carto') {
        const style = dark ? 'dark_all' : 'light_all';
        return L.tileLayer('https://basemaps.cartocdn.com/rastertiles/' + style + '/{z}/{x}/{y}{r}.png?key={key}', {
          ...common, key: provider.key, tdStyle: 'carto:' + style, className: 'td-tiles td-tiles--carto',
          attribution: `${OSM_ATTR} &copy; <a href="https://carto.com/attributions">CARTO</a>`,
        });
      }
      const url = dark && provider.darkUrl ? provider.darkUrl : provider.url;
      return L.tileLayer(url, {
        ...common, key: provider.key, subdomains: provider.subdomains, maxZoom: provider.maxZoom,
        tdStyle: 'custom:' + (dark ? (provider.darkUrl ? 'dark' : 'inv') : 'light'),
        className: 'td-tiles td-tiles--keyed' + (dark && !provider.darkUrl ? ' td-tiles--invert' : ''), attribution: provider.attribution,
      });
    }
    return L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      ...common, tdStyle: dark ? 'osm-dark' : 'osm', className: 'td-tiles td-tiles--osm', attribution: OSM_ATTR,
    });
  }
  function resetHealth() { health.ok = 0; health.err = 0; clearTimeout(health.timer); health.timer = null; }
  function setTileFailed(on) {
    health.failed = on;
    el.classList.toggle('td-map--offline', on);
    tileMsg.hidden = !on;
    if (!on) return;
    const offline = navigator.onLine === false;
    tileMsg.innerHTML = `<span>${offline ? 'You are offline — street map unavailable.' : 'Street map could not load.'} Districts and colleges are still shown.</span>`;
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'td-map-tilemsg__retry'; b.textContent = 'Retry';
    b.addEventListener('click', retryTiles);
    tileMsg.append(b);
  }
  function tilesFailed() {
    resetHealth();
    if (provider && !useOsm) { // keyed provider broken (bad key, quota, blocked): fall back to OSM automatically
      console.warn('[map] keyed tile provider failed; falling back to OpenStreetMap tiles');
      useOsm = true; setTiles(true); return;
    }
    setTileFailed(true);
  }
  function retryTiles() {
    setTileFailed(false); resetHealth();
    if (provider && useOsm) { useOsm = false; setTiles(true); } else tiles?.redraw();
  }
  function onOnline() { if (health.failed) retryTiles(); }
  window.addEventListener('online', onOnline);
  function setTiles(force = false) {
    const dark = isDark();
    el.classList.toggle('td-map--dark', dark);
    if (!tilesArmed) return;
    const next = makeTiles(dark);
    if (!force && tiles && tiles.options.tdStyle === next.options.tdStyle) return;
    if (tiles) map.removeLayer(tiles);
    resetHealth();
    tiles = next;
    tiles.on('loading', () => { if (!health.failed) { health.ok = 0; health.err = 0; } });
    tiles.on('tileloadstart', () => {
      if (health.timer || health.ok) return;
      health.timer = setTimeout(() => { health.timer = null; if (!destroyed && !health.ok && tiles === next) tilesFailed(); }, 8000);
    });
    tiles.on('tileload', () => {
      health.ok++; clearTimeout(health.timer); health.timer = null;
      if (health.failed) setTileFailed(false);
    });
    tiles.on('tileerror', () => {
      health.err++;
      if (health.err >= 2 && health.err / (health.ok + health.err) >= 0.5) tilesFailed();
    });
    tiles.addTo(map);
  }
  function armTiles() { if (tilesArmed || destroyed) return; tilesArmed = true; setTiles(true); }
  setTiles();
  const armT = setTimeout(() => { if (hasSize()) armTiles(); }, 2500); // safety net if the first fit never happens
  const themeObs = new MutationObserver(() => setTiles());
  themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  const schemeMq = window.matchMedia?.('(prefers-color-scheme: dark)');
  const onScheme = () => setTiles();
  schemeMq?.addEventListener?.('change', onScheme);

  // --- gestures: wheel only after click/focus (or with Ctrl/⌘); on touch one finger scrolls the page ---
  let wheelOn = false;
  function setWheel(on) {
    if (on === wheelOn || destroyed) return;
    wheelOn = on;
    if (on) map.scrollWheelZoom.enable(); else map.scrollWheelZoom.disable();
    el.classList.toggle('td-map--active', on);
  }
  const onPointerDown = (e) => { if (e.pointerType === 'mouse' || e.pointerType === 'pen') setWheel(true); };
  const onLeave = () => setWheel(false);
  const onFocusIn = () => { if (!coarse()) setWheel(true); };
  const onFocusOut = (e) => { if (!e.relatedTarget || !el.contains(e.relatedTarget)) setWheel(false); };
  let wheelAcc = 0, wheelAt = 0;
  const onWheel = (e) => {
    if (wheelOn || destroyed) return;
    if (e.target && e.target.closest && e.target.closest('.leaflet-control')) return; // e.g. scrolling the legend
    if (e.ctrlKey || e.metaKey) { // Ctrl/⌘ + wheel (and trackpad pinch) zooms the map instead of the page
      e.preventDefault();
      wheelAcc += e.deltaY * (e.deltaMode === 1 ? 30 : e.deltaMode === 2 ? 300 : 1);
      if (Math.abs(wheelAcc) < 40) return;
      const now = performance.now();
      const dz = wheelAcc < 0 ? 1 : -1;
      wheelAcc = 0;
      if (now - wheelAt < 160) return;
      wheelAt = now;
      map.setZoomAround(map.mouseEventToContainerPoint(e), map.getZoom() + dz, { animate: animate() });
      return;
    }
    showHint(IS_MAC ? 'Use ⌘ + scroll to zoom, or click the map first' : 'Use Ctrl + scroll to zoom, or click the map first');
  };
  let touch0 = null;
  const onTouchStart = (e) => { touch0 = e.touches && e.touches.length === 1 ? { x: e.touches[0].clientX, y: e.touches[0].clientY } : null; };
  const onTouchMove = (e) => {
    if (!touch0 || map.dragging.enabled() || !e.touches || e.touches.length !== 1) return;
    const t = e.touches[0];
    if (Math.abs(t.clientY - touch0.y) > 14 || Math.abs(t.clientX - touch0.x) > 14) { touch0 = null; showHint('Use two fingers to move the map'); }
  };
  el.addEventListener('pointerdown', onPointerDown);
  el.addEventListener('mouseleave', onLeave);
  el.addEventListener('focusin', onFocusIn);
  el.addEventListener('focusout', onFocusOut);
  el.addEventListener('wheel', onWheel, { passive: false, capture: true });
  el.addEventListener('touchstart', onTouchStart, { passive: true });
  el.addEventListener('touchmove', onTouchMove, { passive: true });
  const coarseMq = window.matchMedia?.('(pointer: coarse)');
  function applyPointer() {
    const c = coarse();
    el.classList.toggle('td-map--coarse', c);
    if (c) map.dragging.disable(); else map.dragging.enable();
  }
  const onCoarse = () => { applyPointer(); if (!destroyed) render(); };
  applyPointer();
  coarseMq?.addEventListener?.('change', onCoarse);

  // --- touch: first tap shows the info as a popup with an explicit action; second tap opens ---
  let pop = null; // { key, popup }
  function closePop() { if (pop) { const p = pop.popup; pop = null; map.closePopup(p); } }
  /** returns true when the tap was consumed to show info (touch only) */
  function touchInfo(key, latlng, html, actLabel, act, offsetY) {
    if (!coarse()) return false;
    if (pop && pop.key === key) { closePop(); return false; } // second tap on the same thing: open it
    closePop();
    const node = document.createElement('div');
    node.className = 'td-map-pop__body';
    node.innerHTML = html;
    node.querySelectorAll('.td-map-tip__hint').forEach((x) => x.remove());
    if (actLabel) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'td-map-pop__go'; b.textContent = actLabel + ' ›';
      b.addEventListener('click', (e) => { e.stopPropagation(); closePop(); act(); });
      node.append(b);
    }
    // auto-pan keeps the popup clear of the corner controls (closed chip on top, zoom bar on the right)
    const ce = controlExtents(), W = el.clientWidth;
    const popup = L.popup({
      className: 'td-map-pop', maxWidth: Math.max(160, Math.min(260, W - ce.right - 56)), minWidth: Math.max(140, Math.min(180, W - ce.right - 56)), closeButton: true, autoPan: true,
      autoPanPaddingTopLeft: L.point(10, ce.top + 6), autoPanPaddingBottomRight: L.point(Math.max(10, Math.min(ce.right + 6, W - 200)), 10),
      offset: L.point(0, offsetY || 0),
    }).setLatLng(latlng).setContent(node);
    pop = { key, popup };
    popup.on('remove', () => { if (pop && pop.popup === popup) pop = null; });
    popup.openOn(map);
    return true;
  }

  // --- tooltips never clipped by the card edge: flip below near the top, shift sideways near the sides ---
  function placeTip(layer) {
    const t = layer.getTooltip && layer.getTooltip();
    const c = t && t._container;
    if (!t || !c || !t._latlng || !map.hasLayer(t)) return;
    const W = el.clientWidth, Hh = el.clientHeight, M = 6;
    const p = map.latLngToContainerPoint(t._latlng);
    const io = layer.options.icon && layer.options.icon.options;
    const anchor = io ? L.point(io.tooltipAnchor || [0, 0]) : L.point(0, 0);
    const iconBottom = io ? (io.tdVisual ? io.iconSize[1] - io.iconAnchor[1] : 0) : 0;
    const baseOff = io ? 0 : -8; // sticky polygon tooltips sit 8px above the pointer
    const tw = c.offsetWidth, th = c.offsetHeight;
    let dir = 'top', oy = baseOff;
    const topEdge = p.y + anchor.y + baseOff - th;
    if (topEdge < M && p.y + (io ? iconBottom : 16) + th + M < Hh) { dir = 'bottom'; oy = (io ? iconBottom - anchor.y : 16) + 6; }
    let ox = 0;
    const left = p.x + anchor.x - tw / 2;
    if (left < M) ox = M - left;
    else if (left + tw > W - M) ox = (W - M) - (left + tw);
    if (tw > W - 2 * M) ox = M - left; // wider than the map: pin to the left edge
    t.options.direction = dir;
    t.options.offset = L.point(ox, oy);
    if (typeof t._updatePosition === 'function') t._updatePosition(); else t.update();
  }

  // --- state ---
  let rows = [];
  let byId = new Map();
  let places = { districts: new Map(), cities: new Map() };
  let districtLayer = null, maskLayer = null;
  const districtFeatures = new Map(); // id -> {layer, name, bounds, labelAt}
  let apBounds = L.latLngBounds([12.6, 76.7], [19.95, 84.8]);
  const pinLayer = L.layerGroup().addTo(map);
  let markerIndex = new Map(); // college / city / district id -> marker (pin or the bubble containing it)
  let view = { level: 'state', districtId: null, cityId: null, collegeId: null };
  let highlighted = null;
  let pendingFocus = null;
  let destroyed = false;
  let boundariesFailed = false;
  let showClosed = getShowClosed();
  let stateFitHadRows = false;
  let refitOnRows = false;
  // global district scope (from the shell): ids = selected district ids (null when all), target = program target ids
  let scope = { all: true, ids: null, target: [], groups: {} };
  const inSel = (id) => scope.all || !scope.ids || scope.ids.includes(id);
  const isGoal = (id) => scope.target.includes(id);
  const goalGroup = (id) => Object.entries(scope.groups || {}).find(([, ids]) => ids.includes(id))?.[0] || null;

  const districtName = (id) => places.districts.get(id) || districtFeatures.get(id)?.name || titleCase(id || '');
  const cityName = (cid) => {
    if (!cid) return '';
    if (cid.startsWith('~')) return districtName(cid.slice(1)) + ' (district)';
    if (places.cities.get(cid)) return places.cities.get(cid);
    const parts = cid.split('--');
    return titleCase(parts[parts.length - 1]);
  };
  const shortDistrict = (n) => n.replace(/^Dr\. B\.R\. Ambedkar /, '').replace(/^Sri Potti Sriramulu /, '').replace(/^YSR /, '');

  // Closed colleges are hidden unless the user asked for them, or unless the current data contains
  // nothing else (e.g. the shell filter is "College status: Possibly closed") — an empty map would mislead.
  function hidingClosed() {
    if (showClosed) return false;
    return rows.some((r) => !isClosed(r));
  }
  const shown = (r) => !hidingClosed() || !isClosed(r) || r.id === view.collegeId;

  // --- controls: reset, closed toggle, legend ---
  const ResetControl = L.Control.extend({
    options: { position: 'topright' },
    onAdd() {
      const wrap = L.DomUtil.create('div', 'leaflet-bar td-map-reset');
      const btn = L.DomUtil.create('button', 'td-map-reset__btn', wrap);
      btn.type = 'button';
      btn.title = 'Show all of Andhra Pradesh';
      btn.setAttribute('aria-label', 'Reset map to Andhra Pradesh');
      btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path d="M3 11.5 12 4l9 7.5M5.5 9.5V20h5v-5.5h3V20h5V9.5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg><span class="td-map-reset__txt">Andhra Pradesh</span>';
      L.DomEvent.disableClickPropagation(wrap);
      L.DomEvent.on(btn, 'click', (e) => {
        L.DomEvent.preventDefault(e);
        if (handlers.onReset) handlers.onReset(); else api.focusState();
      });
      return wrap;
    },
  });
  new ResetControl().addTo(map);

  let closedBtn = null;
  const ClosedControl = L.Control.extend({
    options: { position: 'topleft' },
    onAdd() {
      const wrap = L.DomUtil.create('div', 'td-map-closed');
      closedBtn = L.DomUtil.create('button', 'td-map-closed__btn', wrap);
      closedBtn.type = 'button';
      L.DomEvent.disableClickPropagation(wrap);
      L.DomEvent.on(closedBtn, 'click', (e) => { L.DomEvent.preventDefault(e); setShowClosedPref(!showClosed); });
      return wrap;
    },
  });
  new ClosedControl().addTo(map);
  function scopeRows() {
    if (view.level === 'state' || !view.districtId) return rows;
    return rows.filter((r) => r.district_id === view.districtId);
  }
  function renderClosedControl() {
    if (!closedBtn) return;
    const n = scopeRows().filter(isClosed).length;
    const relevant = n > 0 && rows.some((r) => !isClosed(r));
    closedBtn.parentElement.hidden = !relevant;
    if (!relevant) return;
    closedBtn.setAttribute('aria-pressed', String(showClosed));
    closedBtn.title = showClosed ? 'Hide colleges marked possibly closed or closed'
      : 'These colleges may have stopped running. Show them on the map';
    const full = showClosed ? `Showing ${plural(n, 'possibly closed college')}` : `${num(n)} possibly closed hidden`;
    closedBtn.setAttribute('aria-label', `${full}. ${showClosed ? 'Hide them' : 'Show them'}`);
    closedBtn.innerHTML = (showClosed ? EYE : EYE_OFF) +
      `<span class="td-map-closed__long">${full}</span>` +
      `<span class="td-map-closed__short" aria-hidden="true">${num(n)} closed</span>` +
      `<span class="td-map-closed__act">${showClosed ? 'Hide' : 'Show'}</span>`;
  }

  // Legend: a toggle, collapsed by default on touch devices and on maps narrower than 900px; the user's
  // choice is remembered ('td.map.legend').
  const LEGEND_KEY = 'td.map.legend';
  const legendPref = () => { try { const v = localStorage.getItem(LEGEND_KEY); return v === null ? null : v === '1'; } catch { return null; } };
  let legendEl = null, legendDefaulted = false, legendProg = false;
  function defaultLegend() {
    if (!legendEl || legendDefaulted || !hasSize()) return;
    legendDefaulted = true;
    const pref = legendPref();
    const want = pref !== null ? pref : (!coarse() && el.clientWidth >= 900);
    if (legendEl.open !== want) { legendProg = true; legendEl.open = want; }
  }
  let legendClosedRow = null;
  const LegendControl = L.Control.extend({
    options: { position: 'bottomleft' },
    onAdd() {
      const d = L.DomUtil.create('details', 'td-map-legend');
      legendEl = d;
      const drop = (cls, inner = '<circle class="td-pin__dot" cx="12" cy="11.8" r="4.4"/>') => `<svg viewBox="-1.5 -1.5 27 37" width="13" height="18" class="td-pin ${cls}" aria-hidden="true" focusable="false"><path class="td-pin__body" d="${DROP}"/>${inner}</svg>`;
      d.innerHTML =
        '<summary>Legend</summary><ul>' +
        `<li><span class="td-map-legend__sw">${drop('td-pin--good')}</span>On track</li>` +
        `<li><span class="td-map-legend__sw">${drop('td-pin--bad')}</span>Behind target</li>` +
        `<li><span class="td-map-legend__sw">${drop('td-pin--early')}</span>Too early to tell</li>` +
        `<li><span class="td-map-legend__sw">${drop('td-pin--none')}</span>No target yet</li>` +
        '<li><span class="td-map-legend__sw"><span class="td-map-legend__bubble"></span></span>Group · ring = progress mix</li>' +
        '<li><span class="td-map-legend__sw"><span class="td-map-legend__ring"></span></span>In exams now</li>' +
        `<li><span class="td-map-legend__sw">${drop('td-pin--none td-pin--approx')}</span>Approx. location</li>` +
        `<li class="td-map-legend__closed"><span class="td-map-legend__sw">${drop('td-pin--closed', `<path class="td-pin__cross" d="${CROSS}"/>`)}</span>Possibly closed</li>` +
        '<li><span class="td-map-legend__sw"><span class="td-map-legend__area td-map-legend__area--goal"></span></span><span><strong>Target</strong> district</span></li>' +
        '<li><span class="td-map-legend__sw"><span class="td-map-legend__area"></span></span>Other selected district</li>' +
        '<li><span class="td-map-legend__sw"><span class="td-map-legend__area td-map-legend__area--muted"></span></span>Not selected (dimmed)</li>' +
        '</ul>';
      legendClosedRow = d.querySelector('.td-map-legend__closed');
      d.addEventListener('toggle', () => {
        if (legendProg) { legendProg = false; return; }
        try { localStorage.setItem(LEGEND_KEY, d.open ? '1' : '0'); } catch { /* private mode */ }
      });
      L.DomEvent.disableClickPropagation(d);
      L.DomEvent.disableScrollPropagation(d);
      return d;
    },
  });
  new LegendControl().addTo(map);

  // --- district polygons ---
  function districtStats() {
    const s = new Map();
    for (const r of rows) {
      if (!r.district_id || !shown(r)) continue;
      const o = s.get(r.district_id) || { total: 0, targeted: 0, placed: 0, target: 0, enrolled: 0, hasT: false };
      o.total++; if (r.targeted) o.targeted++; if (placed(r)) o.placed++;
      if (r.target) { o.hasT = true; o.target += r.target; } o.enrolled += r.enrolled || 0;
      s.set(r.district_id, o);
    }
    return s;
  }
  // targeted shading uses all rows (a district stays "targeted" whether or not closed colleges are shown)
  function targetedDistricts() {
    const t = new Set();
    for (const r of rows) if (r.targeted && r.district_id) t.add(r.district_id);
    return t;
  }

  function buildDistricts(fc) {
    // Inverted mask: dims everything outside Andhra Pradesh.
    const holes = [];
    for (const f of fc.features) for (const poly of ringsOf(f.geometry)) holes.push(poly[0].map(([x, y]) => [y, x]));
    maskLayer = L.polygon([[[-85, -180], [-85, 180], [85, 180], [85, -180]], ...holes], {
      pane: 'tdMask', renderer: L.svg({ pane: 'tdMask', padding: 0.5 }), className: 'td-ap-mask', interactive: false, stroke: false, fill: true, fillOpacity: 1,
    }).addTo(map);

    districtLayer = L.geoJSON(fc, {
      pane: 'tdDistricts', renderer: L.svg({ pane: 'tdDistricts', padding: 0.5 }),
      style: () => ({ className: 'td-dist', weight: 1.2, fill: true, fillOpacity: 1, opacity: 1 }),
      onEachFeature: (f, layer) => {
        const id = f.properties.id;
        districtFeatures.set(id, { layer, name: f.properties.name, bounds: layer.getBounds(), labelAt: labelPoint(f.geometry) });
        layer.bindTooltip(() => districtTooltip(id), { sticky: true, direction: 'top', className: 'td-map-tip', offset: [0, -8] });
        layer.on('tooltipopen mousemove', () => placeTip(layer));
        layer.on('click', (e) => {
          if (view.level !== 'state' && view.districtId === id) { if (coarse()) layer.closeTooltip(); return; } // tapping the open district's own area does nothing
          const go = () => { if (handlers.onSelectDistrict) handlers.onSelectDistrict(id); else api.focusDistrict(id); };
          if (coarse()) { layer.closeTooltip(); if (touchInfo('d:' + id, e.latlng, districtTooltip(id), 'Open district', go, -4)) return; }
          go();
        });
        layer.on('mouseover', () => layer.getElement()?.classList.add('is-hover'));
        layer.on('mouseout', () => layer.getElement()?.classList.remove('is-hover'));
      },
    }).addTo(map);
    apBounds = districtLayer.getBounds();
    map.setMaxBounds(apBounds.pad(0.6));
  }

  function districtTooltip(id) {
    const s = districtStats().get(id);
    const tg = targetedDistricts().has(id);
    const lines = !s ? `<span class="td-map-tip__muted">No colleges listed${tg ? '' : ' · not targeted'}</span>`
      : `${plural(s.total, 'college')}` +
        (s.targeted ? ` · <strong>${num(s.targeted)} targeted</strong>` : ' · <span class="td-map-tip__muted">not targeted</span>');
    const act = view.level !== 'state' && view.districtId === id ? '' : `<div class="td-map-tip__hint">${s ? 'Click to open district' : 'Click to open'}</div>`;
    const g = isGoal(id) ? goalGroup(id) : null;
    const tag = isGoal(id) ? `<div class="td-map-tip__goal">Target district${g && g !== districtName(id) ? ` · ${esc(g)} group` : ''}</div>` : '';
    const out = inSel(id) ? '' : '<div class="td-map-tip__muted">Outside the selected districts</div>';
    return `<div class="td-map-tip__title">${esc(districtName(id))}</div>${tag}${out}<div>${inSel(id) ? lines : ''}</div>${act}`;
  }

  function styleDistricts() {
    if (!districtLayer) return;
    const tg = targetedDistricts();
    for (const [id, d] of districtFeatures) {
      const e = d.layer.getElement(); if (!e) continue;
      const focused = view.level !== 'state' && view.districtId === id;
      const sel = inSel(id);
      e.classList.toggle('td-dist--goal', isGoal(id));
      e.classList.toggle('td-dist--out', !sel);
      e.classList.toggle('td-dist--targeted', sel && !isGoal(id) && tg.has(id));
      e.classList.toggle('td-dist--muted', sel && !isGoal(id) && !tg.has(id));
      e.classList.toggle('td-dist--active', focused);
      e.classList.toggle('td-dist--dim', view.level !== 'state' && !focused);
      e.classList.toggle('is-hl', highlighted === id);
    }
    // keep the focused / highlighted outline on top
    const top = (view.level !== 'state' && districtFeatures.get(view.districtId)) || districtFeatures.get(highlighted);
    top?.layer.bringToFront();
  }

  // --- markers ---
  function collegeTooltip(r) {
    const closed = isClosed(r);
    const prog = closed ? 'closed' : progressOf(r);
    const approx = r.geo_precision === 'town' || r.geo_precision === 'district';
    const where = [cityName(r.city_id), districtName(r.district_id)].filter(Boolean).join(', ');
    const tgt = r.target ? `<strong>${num(r.enrolled ?? 0)}</strong> of ${num(r.target)} enrolled · ${PROGRESS_LABEL[progressOf(r)].toLowerCase()}`
      : `${num(r.enrolled ?? 0)} enrolled · no target yet`;
    return `<div class="td-map-tip__title">${esc(r.short_name || r.name)}</div>` +
      (r.short_name && r.short_name !== r.name ? `<div class="td-map-tip__sub">${esc(r.name)}</div>` : '') +
      `<div class="td-map-tip__muted">${esc(where)}</div>` +
      (closed ? `<div class="td-map-tip__row td-map-tip__closed"><span class="td-map-tip__dot td-map-tip__dot--closed"></span>${r.op_status === 'closed' ? 'Closed' : 'Possibly closed — status needs checking'}</div>`
        : `<div class="td-map-tip__row"><span class="td-map-tip__dot td-map-tip__dot--${prog}"></span>${tgt}</div>`) +
      (!closed && r.exam_state === 'in_exams' ? '<div class="td-map-tip__row td-map-tip__exam">In exams now</div>' : '') +
      (approx ? `<div class="td-map-tip__row td-map-tip__approx">Approx. location (${r.geo_precision === 'town' ? 'town centre' : 'district HQ'})</div>` : '');
  }

  function addPin(r, at = null, { faded = false } = {}) {
    const selected = view.collegeId === r.id;
    const m = L.marker(at || [r.lat, r.lng], {
      icon: pinIcon(r, { selected, highlighted: highlighted === r.id, faded }), keyboard: true, riseOnHover: true,
      zIndexOffset: selected ? 1000 : faded ? -500 : 0,
    });
    m.bindTooltip(() => collegeTooltip(r), { direction: 'top', className: 'td-map-tip', opacity: 1 });
    m.on('tooltipopen', () => placeTip(m));
    m.on('click', () => {
      const go = () => { if (handlers.onSelectCollege) handlers.onSelectCollege(r.id); else api.focusCollege(r.id); };
      if (coarse()) {
        m.closeTooltip();
        const vh = (m.options.icon.options.tdVisual || [26, 37])[1];
        if (touchInfo('c:' + r.id, m.getLatLng(), collegeTooltip(r), 'Open college', go, -vh + 6)) return;
      }
      go();
    });
    m.on('add', () => {
      const e = m.getElement(); if (!e) return;
      e.setAttribute('role', 'button');
      e.setAttribute('aria-label', `${r.name}, ${cityName(r.city_id)}. ${isClosed(r) ? 'Possibly closed' : PROGRESS_LABEL[progressOf(r)]}${r.exam_state === 'in_exams' ? ', in exams' : ''}. Open college.`);
      // keyboard users get the same tooltip as hover
      e.addEventListener('focus', () => m.openTooltip());
      e.addEventListener('blur', () => { if (view.collegeId !== r.id) m.closeTooltip(); });
    });
    m.tdRow = r; m.tdFaded = faded;
    m.addTo(pinLayer);
    markerIndex.set(r.id, m);
    return m;
  }

  function groupTip(group, kind) {
    let target = 0, enrolled = 0, hasT = false, targeted = 0;
    for (const r of group.rows) { if (r.target) { hasT = true; target += r.target; } enrolled += r.enrolled || 0; if (r.targeted) targeted++; }
    const names = kind === 'district' ? [districtName(group.districtId)] : group.cityIds.map(cityName);
    const nm = names.length <= 3 ? names.join(', ') : `${names.slice(0, 3).join(', ')} +${names.length - 3} more`;
    const hint = kind === 'district' ? 'Click to open district' : group.cityIds.length === 1 ? 'Click to open this city' : 'Click to zoom in';
    return `<div class="td-map-tip__title">${esc(nm)}</div>` +
      `<div>${plural(group.rows.length, 'college')}${targeted ? ` · ${num(targeted)} targeted` : ''}</div>` +
      `<div class="td-map-tip__muted">${hasT ? `${num(enrolled)} of ${num(target)} enrolled` : `${num(enrolled)} enrolled · no target yet`}</div>` +
      `<div class="td-map-tip__hint">${hint}</div>`;
  }

  function addBubble(group, kind) {
    const ids = new Set(group.rows.map((r) => r.id));
    const label = kind === 'district' ? shortDistrict(districtName(group.districtId))
      : group.cityIds.length === 1 ? cityName(group.cityIds[0]) : null;
    const keys = [...ids, ...group.cityIds, ...(kind === 'district' ? [group.districtId] : [])];
    const m = L.marker(group.center, {
      icon: bubbleIcon(group, { label, kind, highlighted: highlighted && keys.includes(highlighted) }), keyboard: true, riseOnHover: true,
      zIndexOffset: 500 + group.rows.length,
    });
    m.tdIds = ids; m.tdGroup = group; m.tdKind = kind; m.tdLabel = label;
    m.bindTooltip(() => groupTip(group, kind), { direction: 'top', className: 'td-map-tip', opacity: 1 });
    m.on('tooltipopen', () => placeTip(m));
    m.on('click', () => {
      let go, actLabel;
      if (kind === 'district') {
        actLabel = 'Open district';
        go = () => { if (handlers.onSelectDistrict) handlers.onSelectDistrict(group.districtId); else api.focusDistrict(group.districtId); };
      } else if (group.cityIds.length === 1 && !group.cityIds[0].startsWith('~')) {
        const did = group.rows[0].district_id, cid = group.cityIds[0];
        actLabel = 'Open city';
        go = () => { if (handlers.onSelectCity) handlers.onSelectCity(did, cid); else api.focusCity(did, cid); };
      } else {
        // zooming in is harmless and exactly what the user wants: no confirm tap needed
        fit(L.latLngBounds(group.rows.map((r) => [r.lat, r.lng])).pad(0.2), { maxZoom: 13 });
        return;
      }
      if (coarse()) {
        m.closeTooltip();
        const vs = (m.options.icon.options.tdVisual || [30, 30])[1];
        if (touchInfo('g:' + kind + ':' + keys.join(','), m.getLatLng(), groupTip(group, kind), actLabel, go, -vs / 2 + 4)) return;
      }
      go();
    });
    m.on('add', () => {
      const e = m.getElement(); if (!e) return;
      e.setAttribute('role', 'button');
      const nm = kind === 'district' ? `${districtName(group.districtId)} district` : group.cityIds.map(cityName).join(', ');
      e.setAttribute('aria-label', `${nm}: ${plural(group.rows.length, 'college')}. ${kind === 'district' ? 'Open district' : group.cityIds.length === 1 ? 'Open city' : 'Zoom in'}.`);
      e.addEventListener('focus', () => m.openTooltip());
      e.addEventListener('blur', () => m.closeTooltip());
    });
    m.addTo(pinLayer);
    for (const k of keys) markerIndex.set(k, m);
    return m;
  }

  // Group by city, then merge city groups that would overlap on screen (greedy distance clustering in pixels).
  function cityGroups(list) {
    const by = new Map();
    for (const r of list) {
      const k = r.city_id || `~${r.district_id}`;
      if (!by.has(k)) by.set(k, { cityIds: [k], rows: [] });
      by.get(k).rows.push(r);
    }
    for (const g of by.values()) {
      let la = 0, ln = 0; for (const r of g.rows) { la += r.lat; ln += r.lng; }
      g.center = L.latLng(la / g.rows.length, ln / g.rows.length);
    }
    return [...by.values()];
  }
  function mergeClose(groups, radiusPx) {
    const z = map.getZoom();
    const pts = groups.map((g) => ({ g, p: map.project(g.center, z) })).sort((a, b) => b.g.rows.length - a.g.rows.length);
    const out = [];
    for (const it of pts) {
      const hit = out.find((o) => o.p.distanceTo(it.p) < radiusPx);
      if (!hit) { out.push({ p: it.p, g: { ...it.g, cityIds: [...it.g.cityIds], rows: [...it.g.rows] } }); continue; }
      const n1 = hit.g.rows.length, n2 = it.g.rows.length;
      hit.p = L.point((hit.p.x * n1 + it.p.x * n2) / (n1 + n2), (hit.p.y * n1 + it.p.y * n2) / (n1 + n2));
      hit.g.rows.push(...it.g.rows); hit.g.cityIds.push(...it.g.cityIds);
    }
    for (const o of out) o.g.center = map.unproject(o.p, z);
    return out.map((o) => o.g);
  }

  // One bubble per district, placed at the polygon's interior point (or the colleges' centroid when the
  // district has no polygon), then nudged apart so neighbouring bubbles never overlap.
  function districtGroups(list) {
    const by = new Map();
    for (const r of list) {
      const k = r.district_id || '~';
      if (!by.has(k)) by.set(k, { districtId: k, cityIds: [], rows: [] });
      const g = by.get(k); g.rows.push(r);
      const c = r.city_id || `~${k}`; if (!g.cityIds.includes(c)) g.cityIds.push(c);
    }
    const z = map.getZoom();
    const items = [...by.values()].map((g) => {
      let at = districtFeatures.get(g.districtId)?.labelAt;
      if (!at) { let la = 0, ln = 0; for (const r of g.rows) { la += r.lat; ln += r.lng; } at = L.latLng(la / g.rows.length, ln / g.rows.length); }
      return { g, p: map.project(at, z), r: bubbleSize(g.rows.length) / 2 };
    });
    for (let iter = 0; iter < 40; iter++) {
      let moved = false;
      for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
        const a = items[i], b = items[j];
        const min = a.r + b.r + 20; // leaves room for the name label under each bubble
        let dx = b.p.x - a.p.x, dy = b.p.y - a.p.y, d = Math.hypot(dx, dy);
        if (d >= min) continue;
        if (d < 0.01) { dx = 1; dy = 0; d = 1; }
        const push = (min - d) / 2;
        a.p = L.point(a.p.x - (dx / d) * push, a.p.y - (dy / d) * push);
        b.p = L.point(b.p.x + (dx / d) * push, b.p.y + (dy / d) * push);
        moved = true;
      }
      if (!moved) break;
    }
    for (const it of items) it.g.center = map.unproject(it.p, z);
    return items.map((it) => it.g);
  }

  // Pins that would sit on top of each other (same town centroid, same campus…) are fanned out in rings
  // around their true spot, with a thin leader line back to it.
  function drawPinsSpread(list, fadedFn) {
    const z = map.getZoom();
    const groups = [];
    for (const r of list) {
      const p = map.project([r.lat, r.lng], z);
      const g = groups.find((x) => x.p.distanceTo(p) < 16);
      if (g) g.items.push(r); else groups.push({ p, items: [r] });
    }
    for (const g of groups) {
      if (g.items.length === 1) { addPin(g.items[0], null, { faded: fadedFn(g.items[0]) }); continue; }
      g.items.sort((a, b) => String(a.short_name || a.name).localeCompare(String(b.short_name || b.name)));
      const hub = map.unproject(g.p, z);
      L.circleMarker(hub, { radius: 3, className: 'td-spider-hub', interactive: false }).addTo(pinLayer);
      let i = 0, ring = 1;
      const touch = coarse(); // 44px hit boxes need wider rings so neighbours do not overlap
      while (i < g.items.length) {
        const cap = 6 * ring, R = touch ? 44 + (ring - 1) * 46 : 24 + (ring - 1) * 26;
        const n = Math.min(cap, g.items.length - i);
        for (let k = 0; k < n; k++, i++) {
          const a = -Math.PI / 2 + (2 * Math.PI * k) / n + (ring % 2 ? 0 : Math.PI / n);
          const ll = map.unproject(g.p.add(L.point(Math.cos(a) * R, Math.sin(a) * R + 10)), z);
          L.polyline([hub, ll], { className: 'td-spider-leg', interactive: false, weight: 1.2 }).addTo(pinLayer);
          addPin(g.items[i], ll, { faded: fadedFn(g.items[i]) });
        }
        ring++;
      }
    }
  }

  function visibleRows() {
    const p = rows.filter((r) => placed(r) && shown(r) && (view.level !== 'state' || inSel(r.district_id)));
    if (view.level === 'state' || !view.districtId) return p;
    return p.filter((r) => r.district_id === view.districtId);
  }

  // Hide bubble labels that would collide with another label or bubble (bigger groups win).
  function declutterLabels() {
    const boxes = [];
    const bubbles = [];
    pinLayer.eachLayer((m) => {
      if (!m.tdGroup) return;
      const p = map.latLngToContainerPoint(m.getLatLng());
      const io = m.options.icon.options;
      const s = (io.tdVisual || io.iconSize)[0];
      bubbles.push({ m, p, s, n: m.tdGroup.rows.length });
    });
    bubbles.sort((a, b) => b.n - a.n);
    const circles = bubbles.map((b) => ({ x1: b.p.x - b.s / 2 + 5, y1: b.p.y - b.s / 2 + 5, x2: b.p.x + b.s / 2 - 5, y2: b.p.y + b.s / 2 - 5 }));
    const hit = (a, b) => a.x1 < b.x2 && a.x2 > b.x1 && a.y1 < b.y2 && a.y2 > b.y1;
    for (const b of bubbles) {
      const e = b.m.getElement(); if (!e || !b.m.tdLabel) continue;
      const w = b.m.tdLabel.length * 6.2 + 14;
      const box = { x1: b.p.x - w / 2, x2: b.p.x + w / 2, y1: b.p.y + b.s / 2 + 2, y2: b.p.y + b.s / 2 + 22 };
      const ok = !boxes.some((x) => hit(x, box)) && !circles.some((c) => hit(c, box));
      e.classList.toggle('td-cluster--nolabel', !ok);
      if (ok) boxes.push(box);
    }
  }

  function drawPins() {
    pinLayer.clearLayers();
    markerIndex = new Map();
    const list = visibleRows();
    const z = map.getZoom();
    let mode;
    if (view.level === 'state') mode = z < 9.5 ? 'district' : z < 12 ? 'city' : 'pins';
    else if (view.level === 'district') mode = z < 12 ? 'city' : 'pins';
    else mode = 'pins';

    if (mode === 'pins') {
      const faded = view.level === 'city' && view.cityId ? (r) => r.city_id !== view.cityId : () => false;
      drawPinsSpread(list, faded);
    } else if (mode === 'district') {
      for (const g of districtGroups(list)) addBubble(g, 'district');
    } else {
      for (const g of mergeClose(cityGroups(list), 40)) {
        if (g.rows.length === 1) addPin(g.rows[0]);
        else addBubble(g, 'city');
      }
    }
    declutterLabels();
  }

  function render() {
    if (destroyed) return;
    styleDistricts();
    drawPins();
    renderClosedControl();
    if (legendClosedRow) legendClosedRow.hidden = !rows.some(isClosed) || hidingClosed();
  }

  // --- navigation ---
  // On phones the shell's bottom sheet covers the lower part of the map. Detect that overlap so fits and
  // fly-tos centre the content in the part of the map the user can actually see.
  function obscuredBottom() {
    const panel = handlers.sheetEl || document.querySelector('.td-panel');
    if (!panel) return 0;
    const r = el.getBoundingClientRect(), p = panel.getBoundingClientRect();
    if (!p.width || p.left > r.left + 4 || p.right < r.right - 4 || p.top <= r.top || p.top >= r.bottom) return 0;
    return Math.min(r.bottom - p.top, r.height * 0.6);
  }
  // Keep framed content clear of the map's own controls: the top-left controls (closed chip) are wide and
  // short, so content stays below them; the top-right ones (zoom + home) are tall and narrow, so content stays
  // left of them; the bottom-left legend toggle keeps content above it.
  function controlExtents() {
    const r = el.getBoundingClientRect();
    const out = { top: 0, right: 0, bottom: 0 };
    for (const c of el.querySelectorAll('.leaflet-control-container .leaflet-control')) {
      if (c.classList.contains('leaflet-control-attribution')) continue;
      const b = c.getBoundingClientRect();
      if (!b.width || !b.height) continue;
      const corner = c.parentElement;
      if (corner.classList.contains('leaflet-top') && corner.classList.contains('leaflet-left')) out.top = Math.max(out.top, b.bottom - r.top);
      else if (corner.classList.contains('leaflet-top') && corner.classList.contains('leaflet-right')) out.right = Math.max(out.right, r.right - b.left);
      // an opened legend only matters on wide maps (≥900px) where it covers a corner, not the frame: count its toggle row
      else if (corner.classList.contains('leaflet-bottom')) out.bottom = Math.max(out.bottom, Math.min(r.bottom - b.top, 58));
    }
    return out;
  }
  function padding() {
    const W = el.clientWidth, H = el.clientHeight;
    const pad = W < 520 ? 12 : 28;
    const c = controlExtents();
    let top = pad + c.top, bottom = pad + c.bottom + obscuredBottom(), right = pad + c.right;
    // never squeeze the content below ~45% of the map
    const vScale = top + bottom > H * 0.55 ? (H * 0.55) / (top + bottom) : 1;
    const hScale = pad + right > W * 0.45 ? (W * 0.45) / (pad + right) : 1;
    top *= vScale; bottom *= vScale; right *= hScale;
    return { paddingTopLeft: L.point(pad * hScale, top), paddingBottomRight: L.point(right, bottom) };
  }
  function sameCentre(ll) { return map.latLngToContainerPoint(ll).distanceTo(map.latLngToContainerPoint(map.getCenter())) < 1; }
  function fit(bounds, opts = {}) {
    if (!bounds || !bounds.isValid()) return;
    const o = { ...padding(), maxZoom: opts.maxZoom ?? 14 };
    // Leaflet's flyTo divides by the pixel distance travelled, so flying to the current centre gives NaN.
    if (animate() && !sameCentre(bounds.getCenter())) map.flyToBounds(bounds, { ...o, duration: 0.6 });
    else map.fitBounds(bounds, { ...o, animate: false });
  }
  // Polygon bounds; for a district with no polygon (e.g. a newly formed one missing from the GeoJSON),
  // fall back to the bounds of its placed colleges, then to the whole state.
  function districtBounds(id) {
    const d = districtFeatures.get(id);
    if (d) return d.bounds;
    const pts = rows.filter((r) => r.district_id === id && placed(r)).map((r) => [r.lat, r.lng]);
    if (pts.length) return L.latLngBounds(pts).pad(pts.length > 1 ? 0.2 : 0.5);
    return apBounds;
  }
  // State view frames the districts that actually have colleges (the outreach area); the rest of the state
  // stays visible around it. With no colleges yet, the whole state is shown.
  function stateBounds() {
    const ids = new Set(rows.filter((r) => placed(r) && shown(r) && inSel(r.district_id)).map((r) => r.district_id));
    // a district selection frames the selected polygons, whether or not their colleges have loaded yet
    if (!scope.all && scope.ids && scope.ids.length) scope.ids.forEach((id) => { if (districtFeatures.has(id)) ids.add(id); });
    let b = null;
    for (const id of ids) { const db = districtBounds(id); if (db && db !== apBounds) b = b ? b.extend(db) : L.latLngBounds(db.getSouthWest(), db.getNorthEast()); }
    return b && b.isValid() ? b : apBounds;
  }
  function ready() { return !!districtLayer || boundariesFailed; }
  // Leaflet computes NaN centres when the container has no size (e.g. the map is hidden on the mobile
  // full-page college layout), so focusing waits until the container is visible again.
  const hasSize = () => el.clientWidth > 0 && el.clientHeight > 0;
  let sizeFocus = null;
  function whenReady(fn) {
    if (!ready()) { pendingFocus = fn; return; }
    if (!hasSize()) { sizeFocus = fn; return; }
    sizeFocus = null;
    // Leaflet caches the container size; refresh it if the map was just shown (stale 0×0 size also gives NaN).
    const sz = map.getSize();
    if (sz.x !== el.clientWidth || sz.y !== el.clientHeight) map.invalidateSize({ pan: false });
    fn();
  }
  function fitState() {
    stateFitHadRows = rows.some(placed);
    fit(stateBounds(), { maxZoom: 9 });
  }

  const api = {
    setColleges(list) {
      rows = Array.isArray(list) ? list.slice() : [];
      byId = new Map(rows.map((r) => [r.id, r]));
      render();
      // the state view was framed before any colleges arrived: frame the outreach area now
      if (view.level === 'state' && (!stateFitHadRows || refitOnRows) && rows.some(placed)) { refitOnRows = false; whenReady(() => fitState()); }
    },
    setPlaces({ districts = [], cities = [] } = {}) {
      places = { districts: new Map(districts.map((d) => [d.id, d.name])), cities: new Map(cities.map((c) => [c.id, c.name])) };
      render();
    },
    getUnplacedCount() { return rows.filter((r) => !placed(r)).length; },
    setScope({ all = true, ids = null, target = [], groups = {} } = {}) {
      const next = { all: !!all || !Array.isArray(ids), ids: Array.isArray(ids) ? [...ids] : null, target: Array.isArray(target) ? [...target] : [], groups: groups || {} };
      const changed = JSON.stringify(next.all ? null : next.ids) !== JSON.stringify(scope.all ? null : scope.ids);
      scope = next;
      render();
      // re-frame now (selected polygons) and again when the shell delivers the new scope's colleges
      if (changed && view.level === 'state') { refitOnRows = true; whenReady(() => fitState()); }
    },
    getClosedCount() { return rows.filter(isClosed).length; },
    setShowClosed(show) { setShowClosedPref(!!show); },
    focusState() {
      view = { level: 'state', districtId: null, cityId: null, collegeId: null };
      whenReady(() => { render(); fitState(); });
    },
    focusDistrict(id) {
      view = { level: 'district', districtId: id, cityId: null, collegeId: null };
      whenReady(() => {
        render();
        fit(districtBounds(id), { maxZoom: 11 });
      });
    },
    focusCity(districtId, cityId) {
      view = { level: 'city', districtId, cityId, collegeId: null };
      whenReady(() => {
        render();
        const inCity = rows.filter((r) => r.city_id === cityId && placed(r) && shown(r));
        if (inCity.length) fit(L.latLngBounds(inCity.map((r) => [r.lat, r.lng])).pad(0.3), { maxZoom: 13.5 });
        else fit(districtBounds(districtId), { maxZoom: 11 });
      });
    },
    focusCollege(id) {
      const r = byId.get(id);
      view = { level: 'college', districtId: r?.district_id || view.districtId, cityId: r?.city_id || null, collegeId: id };
      whenReady(() => {
        render();
        if (!r || !placed(r)) { fit(districtBounds(view.districtId), { maxZoom: 11 }); return; }
        const zoom = Math.max(map.getZoom(), r.geo_precision === 'exact' ? 14 : 13);
        // centre the pin in the visible part of the map (above a phone's bottom sheet)
        const pt = map.project([r.lat, r.lng], zoom).add(L.point(0, obscuredBottom() / 2));
        const target = map.unproject(pt, zoom);
        const open = () => { const m = markerIndex.get(id); if (m && m.tdRow) m.openTooltip(); };
        if (animate() && !sameCentre(target)) {
          map.once('moveend', () => setTimeout(open, 30));
          map.flyTo(target, zoom, { duration: 0.7 });
        } else { map.setView(target, zoom, { animate: false }); drawPins(); open(); }
      });
    },
    highlight(id) {
      const prev = highlighted;
      highlighted = id || null;
      if (prev === highlighted) return;
      styleDistricts();
      for (const k of [prev, highlighted]) {
        if (!k) continue;
        const m = markerIndex.get(k);
        if (!m) continue;
        const on = highlighted === k || (m.tdGroup && highlighted && markerIndex.get(highlighted) === m);
        if (m.tdRow) m.setIcon(pinIcon(m.tdRow, { selected: view.collegeId === m.tdRow.id, highlighted: on, faded: m.tdFaded }));
        else m.getElement()?.classList.toggle('is-hl', !!on);
        m.setZIndexOffset(on ? 2000 : m.tdGroup ? 500 + m.tdGroup.rows.length : (m.tdRow && view.collegeId === m.tdRow.id ? 1000 : 0));
      }
    },
    invalidateSize() { if (hasSize()) map.invalidateSize({ pan: false, debounceMoveend: true }); },
    destroy() {
      destroyed = true;
      themeObs.disconnect();
      schemeMq?.removeEventListener?.('change', onScheme);
      coarseMq?.removeEventListener?.('change', onCoarse);
      window.removeEventListener(CLOSED_EVENT, onClosedPref);
      window.removeEventListener('online', onOnline);
      el.removeEventListener('pointerdown', onPointerDown);
      el.removeEventListener('mouseleave', onLeave);
      el.removeEventListener('focusin', onFocusIn);
      el.removeEventListener('focusout', onFocusOut);
      el.removeEventListener('wheel', onWheel, { capture: true });
      el.removeEventListener('touchstart', onTouchStart);
      el.removeEventListener('touchmove', onTouchMove);
      clearTimeout(armT); clearTimeout(hintT); resetHealth();
      ro?.disconnect();
      map.remove();
      hintEl.remove(); tileMsg.remove();
      el.classList.remove('td-map', 'td-map--offline', 'td-map--dark', 'td-map--coarse', 'td-map--active', 'td-map--compact', 'td-map--zoomed');
    },
    /** escape hatch for debugging / tests */
    get leaflet() { return map; },
  };

  function onClosedPref(e) {
    const v = !!(e && e.detail && e.detail.show);
    if (v === showClosed) return;
    showClosed = v;
    render();
  }
  window.addEventListener(CLOSED_EVENT, onClosedPref);

  // the visible marker system depends on zoom; redraw (cheap: ≤ a few hundred markers) when it settles
  // goal/targeted district fills fade once streets matter (zoom ≥ 11), keeping only the outlines
  const syncZoomClass = () => el.classList.toggle('td-map--zoomed', map.getZoom() >= 11);
  map.on('zoomend', () => { if (!destroyed) { syncZoomClass(); drawPins(); } });

  // compact maps (phones, narrow or short cards e.g. landscape phones): shorter chip text, icon-only home,
  // no Leaflet prefix in the attribution
  let compact = null;
  function syncCompact() {
    const c = el.clientWidth < 560 || el.clientHeight < 320;
    el.style.setProperty('--td-map-h', el.clientHeight + 'px');
    if (c === compact) return;
    compact = c;
    el.classList.toggle('td-map--compact', c);
    map.attributionControl.setPrefix(c ? false : PREFIX);
  }
  const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => {
    if (!hasSize()) return;
    syncCompact();
    defaultLegend();
    map.invalidateSize({ pan: false, debounceMoveend: true });
    if (sizeFocus) { const f = sizeFocus; sizeFocus = null; f(); }
    if (ready()) armTiles();
  }) : null;
  ro?.observe(el);
  if (hasSize()) { syncCompact(); defaultLegend(); }

  loadDistricts().then((fc) => {
    if (destroyed) return;
    buildDistricts(fc);
    if (pendingFocus) { const f = pendingFocus; pendingFocus = null; render(); whenReady(() => { f(); armTiles(); }); }
    else { render(); whenReady(() => { stateFitHadRows = rows.some(placed); map.fitBounds(stateBounds(), { ...padding(), maxZoom: 9, animate: false }); armTiles(); }); }
  }).catch((err) => {
    console.error('[map] could not load district boundaries', err);
    el.classList.add('td-map--noboundaries');
    boundariesFailed = true;
    armTiles();
    if (pendingFocus) { const f = pendingFocus; pendingFocus = null; render(); whenReady(f); } else render();
  });

  return api;
}

export default createMap;
