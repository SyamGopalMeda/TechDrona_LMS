// Tech Drona portal — live official-source data (frontend). Routes: #/live (Official sources), #/notices (?category=&q=).
// Also exports the shared pieces other screens use: the top-bar status chip (liveChip + startLive, mounted by app.js),
// the college "Official live data" card (collegeLiveCard) and the Exams "Latest official exam notices" card (examNoticesCard).
// API: GET /api/live[?refresh=1], POST /api/live/refresh {source?}, GET /api/live/college/:id, GET /api/live/announcements.
// Rules: a value is only shown as live when it came from these endpoints; every live value carries "checked <time>" and its
// source; a failed source says "Source unreachable — showing last successful copy from <time>". All external text goes
// through h() (text nodes) — never innerHTML. Links are http(s) only and open in a new tab with rel="noopener noreferrer".
// Styles: css/views-live.css (.v-live, .lv-*, .td-livechip).
import { h, fmt } from '../ui/h.js';
import ui from '../ui/components.js';
import { canWrite } from '../state.js';

export const LIVE_EVENT = 'td:live';
const POLL_MS = 5000;
const POLL_MAX_MS = 90000;
const STALE_REFRESH_MS = 15 * 60000; // tab comes back after this long → ask for a background refresh again
export const RESEARCH_LABEL = 'Researched Nov 2026 (not live)';

/* =========================================================================
   Time: IST, relative to the server clock ("12 min ago · 9 Nov, 6:35 pm")
   ========================================================================= */
let skew = 0; // server now − client now
const nowMs = () => Date.now() + skew;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
let istFmt = null;
function istParts(t) {
  try {
    if (!istFmt) istFmt = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
    const p = Object.fromEntries(istFmt.formatToParts(new Date(t)).map((x) => [x.type, x.value]));
    return { y: Number(p.year), m: Number(p.month) - 1, d: Number(p.day), hh: p.hour, mm: p.minute, ap: String(p.dayPeriod || '').toLowerCase() };
  } catch { const d = new Date(t + 330 * 60000); return { y: d.getUTCFullYear(), m: d.getUTCMonth(), d: d.getUTCDate(), hh: String(((d.getUTCHours() + 11) % 12) + 1), mm: String(d.getUTCMinutes()).padStart(2, '0'), ap: d.getUTCHours() < 12 ? 'am' : 'pm' }; }
}
const toMs = (iso) => { if (!iso) return NaN; const t = Date.parse(iso); return t; };
/** "9 Nov, 6:35 pm" (year added when not this year) */
export function absTime(iso) {
  const t = toMs(iso);
  if (Number.isNaN(t)) return '—';
  const p = istParts(t);
  const yNow = istParts(nowMs()).y;
  return `${p.d} ${MONTHS[p.m]}${p.y !== yNow ? ` ${p.y}` : ''}, ${p.hh}:${p.mm} ${p.ap}`;
}
/** "just now" | "12 min ago" | "3 h ago" | "2 days ago" */
export function relTime(iso) {
  const t = toMs(iso);
  if (Number.isNaN(t)) return 'never';
  const s = Math.round((nowMs() - t) / 1000);
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const hr = Math.round(m / 60);
  if (hr < 24) return `${hr} h ago`;
  const d = Math.round(hr / 24);
  return d === 1 ? '1 day ago' : `${d} days ago`;
}
/** <time> "12 min ago · 9 Nov, 6:35 pm" */
export function when(iso, { prefix = '' } = {}) {
  if (!iso || Number.isNaN(toMs(iso))) return h('span', { class: 'lv-muted' }, prefix ? `${prefix}never` : 'never');
  return h('time', { datetime: iso, class: 'lv-time', title: absTime(iso) + ' IST', dataset: prefix ? { prefix } : undefined }, `${prefix}${relTime(iso)} · ${absTime(iso)}`);
}
const dateOnly = (d) => (d && /^\d{4}-\d{2}-\d{2}/.test(String(d)) ? fmt.date(String(d).slice(0, 10)) : (d ? String(d) : '—'));

/* =========================================================================
   Safe links
   ========================================================================= */
export function safeUrl(u) {
  if (typeof u !== 'string' || !u.trim()) return null;
  try { const x = new URL(u.trim(), 'https://x.invalid/'); return (x.protocol === 'http:' || x.protocol === 'https:') && x.hostname !== 'x.invalid' ? x.href : null; } catch { return null; }
}
const hostOf = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return String(u || ''); } };
/** External link (new tab, no opener, no referrer). Non-http(s) values are shown as plain text. */
export function extLink(url, label, { cls } = {}) {
  const href = safeUrl(url);
  if (!href) return url ? h('span', null, String(label || url)) : null;
  return h('a', { href, target: '_blank', rel: 'noopener noreferrer', class: ['lv-ext', cls], title: href },
    h('span', null, String(label || hostOf(href))), ui.icon('external', { size: 13 }));
}

/* =========================================================================
   Shared live status store: boot refresh + polling while sources are being checked
   ========================================================================= */
const store = { api: null, data: null, error: null, unavailable: false, pollStart: 0, timer: null, gaveUp: false, lastFetch: 0, inflight: null };
const emit = (finished = false) => { try { dispatchEvent(new CustomEvent(LIVE_EVENT, { detail: { data: store.data, finished } })); } catch { /* ignore */ } };
export const liveState = () => store;

function accept(d) {
  if (!d || typeof d !== 'object') return;
  const wasRefreshing = !!(store.data && store.data.refreshing);
  if (d.now && !Number.isNaN(Date.parse(d.now))) skew = Date.parse(d.now) - Date.now();
  store.data = d; store.error = null; store.unavailable = false; store.lastFetch = Date.now();
  clearTimeout(store.timer);
  if (d.refreshing) {
    if (!store.pollStart) store.pollStart = Date.now();
    if (Date.now() - store.pollStart > POLL_MAX_MS) { store.gaveUp = true; store.pollStart = 0; emit(true); return; }
    store.gaveUp = false;
    store.timer = setTimeout(() => fetchLive(), POLL_MS);
    emit(false);
  } else {
    store.pollStart = 0; store.gaveUp = false;
    emit(wasRefreshing);
  }
}
async function fetchLive({ refresh = false } = {}) {
  if (!store.api) return null;
  if (store.inflight && !refresh) return store.inflight;
  const p = store.api.get('/live', refresh ? { refresh: 1 } : undefined)
    .then((d) => { accept(d); return d; })
    .catch((e) => {
      store.error = e;
      if (e && (e.status === 404 || e.status === 405)) store.unavailable = true;
      else if (store.pollStart && Date.now() - store.pollStart < POLL_MAX_MS) { clearTimeout(store.timer); store.timer = setTimeout(() => fetchLive(), POLL_MS * 2); }
      emit(false);
      return null;
    })
    .finally(() => { if (store.inflight === p) store.inflight = null; });
  store.inflight = p;
  return p;
}
/** Called once by the shell after sign-in: starts the background refresh and polls while it runs. */
export function startLive(api) {
  if (store.api) return;
  store.api = api;
  fetchLive({ refresh: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && store.api && !store.unavailable && Date.now() - store.lastFetch > STALE_REFRESH_MS) fetchLive({ refresh: true });
  });
}
/** Editor: POST /api/live/refresh — forces a re-check (ignores the TTL) of one source or all. */
export async function forceRefresh(api, source) {
  const d = await api.post('/live/refresh', source ? { source } : {});
  store.pollStart = Date.now();
  accept(d && typeof d === 'object' && d.sources ? d : { ...(store.data || {}), refreshing: true });
  if (!(d && d.sources)) fetchLive();
  return d;
}

/** One summary for the chip and page headers. tone: good | warn | busy | neutral */
export function liveSummary(d = store.data) {
  if (store.unavailable) return null;
  if (!d) return store.error ? { tone: 'neutral', text: 'Official data: could not check', short: 'Not checked' } : { tone: 'busy', text: 'Checking official sources…', short: 'Checking…' };
  const sources = Array.isArray(d.sources) ? d.sources : [];
  if (d.refreshing && !store.gaveUp) return { tone: 'busy', text: 'Checking official sources…', short: 'Checking…' };
  const failing = sources.filter((s) => s.last_status === 'error');
  if (failing.length) {
    const withCopy = failing.filter((s) => s.last_success_at).length;
    const n = failing.length;
    return { tone: 'warn', text: `${n} source${n === 1 ? '' : 's'} unreachable${withCopy ? ' — showing last copy' : ''}`, short: `${n} unreachable` };
  }
  const never = sources.filter((s) => !s.last_success_at);
  if (!sources.length || never.length === sources.length) return { tone: 'neutral', text: 'Official data: not checked yet', short: 'Not checked' };
  const oldest = sources.filter((s) => s.last_success_at).map((s) => s.last_success_at).sort()[0];
  if (never.length) return { tone: 'warn', text: `Official data: ${never.length} source${never.length === 1 ? '' : 's'} not checked yet`, short: `${never.length} not checked`, at: oldest };
  return { tone: 'good', text: `Official data: checked ${relTime(oldest)}`, short: `Checked ${relTime(oldest)}`, at: oldest };
}

/** Top-bar chip → #/live. Re-paints on every store change and every 30 s (relative time). */
export function liveChip() {
  const a = h('a', { href: '#/live', class: 'td-livechip', hidden: true });
  const paint = () => {
    const s = liveSummary();
    if (!s) { a.hidden = true; return; }
    a.hidden = false;
    a.className = `td-livechip td-livechip--${s.tone}`;
    const title = s.at ? `${s.text} (${absTime(s.at)} IST). Open official sources.` : `${s.text}. Open official sources.`;
    a.setAttribute('aria-label', title);
    a.title = title;
    a.replaceChildren(
      s.tone === 'busy' ? h('span', { class: 'td-livechip__spin', 'aria-hidden': 'true' }) : h('span', { class: 'td-livechip__dot', 'aria-hidden': 'true' }),
      h('span', { class: 'td-livechip__long' }, s.text),
      h('span', { class: 'td-livechip__short' }, s.short));
  };
  addEventListener(LIVE_EVENT, paint);
  setInterval(() => { if (a.isConnected) paint(); }, 30000);
  paint();
  return a;
}

/* =========================================================================
   Small shared bits
   ========================================================================= */
function callout(tone, title, body) {
  return h('div', { class: ['lv-callout', `lv-callout--${tone}`], role: tone === 'warn' || tone === 'bad' ? 'status' : null },
    ui.icon(tone === 'good' ? 'check' : tone === 'info' ? 'info' : 'warn', { size: 18 }),
    h('div', null, title ? h('strong', null, title) : null, body ? h('div', { class: 'lv-callout__text' }, body) : null));
}
/** "checked X · source" line for one source object {name,url,last_success_at,using_fallback,last_attempt_at?} */
export function sourceLine(src, { checkedAt } = {}) {
  if (!src) return null;
  const name = src.name || src.source_name || src.id || 'official source';
  if (src.using_fallback) {
    return h('div', { class: 'lv-srcline lv-srcline--warn' }, ui.icon('warn', { size: 14 }),
      h('span', null, 'Source unreachable — showing last successful copy from ', h('strong', null, src.last_success_at ? `${absTime(src.last_success_at)} (${relTime(src.last_success_at)})` : 'an earlier check'), ' · '),
      extLink(src.url, name));
  }
  const at = checkedAt || src.last_success_at;
  return h('div', { class: 'lv-srcline' }, h('span', { class: 'lv-livedot', 'aria-hidden': 'true' }),
    h('span', null, 'Live · checked ', when(at), ' · '), extLink(src.url, name));
}
/** Status pill for a source row. */
function sourcePill(s) {
  if (s.last_status === 'running') return ui.badge('Checking now…', 'info');
  if (s.last_status === 'error') return s.last_success_at ? ui.badge('Unreachable — showing last copy', 'warn') : ui.badge('Unreachable — no copy yet', 'bad');
  if (s.last_status === 'never' || !s.last_success_at) return ui.badge('Not checked yet', 'neutral');
  return s.fresh ? ui.badge('Up to date', 'good') : ui.badge('Due for a re-check', 'neutral');
}
const AUTO = { automatic: ['Automatic', 'good'], partial: ['Partly automatic', 'warn'], manual: ['Manual (research)', 'neutral'] };
function unavailableNote(what) {
  return ui.emptyState({ icon: 'info', title: 'Live official data is not available here', text: `This server does not provide live ${what} yet. Research data elsewhere is labelled “${RESEARCH_LABEL}”.` });
}

/* =========================================================================
   Page: #/live — Official sources
   ========================================================================= */
let page = null; // { off() } for the current live/notices page
export function destroy() { try { page && page.off && page.off(); } catch { /* ignore */ } page = null; }

export async function renderSources(el, params, ctx) {
  destroy();
  ctx.setBreadcrumb && ctx.setBreadcrumb([{ label: 'Official sources' }]);
  el.className = 'v-live v-live-sources';
  if (!store.api) startLive(ctx.api);
  if (!store.data && !store.unavailable) await (store.inflight || fetchLive());
  const me = { off: null };
  page = me;
  const draw = () => {
    if (page !== me || !el.isConnected) return;
    el.replaceChildren(...sourcesPage(ctx));
  };
  const onLive = () => draw();
  addEventListener(LIVE_EVENT, onLive);
  const tick = setInterval(() => { if (page === me && el.isConnected) el.querySelectorAll('time.lv-time').forEach((t) => { const iso = t.getAttribute('datetime'); t.textContent = `${t.dataset.prefix || ''}${relTime(iso)} · ${absTime(iso)}`; }); }, 30000);
  me.off = () => { removeEventListener(LIVE_EVENT, onLive); clearInterval(tick); };
  draw();
}

function sourcesPage(ctx) {
  const d = store.data;
  const s = liveSummary();
  const busy = !!(d && d.refreshing && !store.gaveUp);
  const checkAll = canWrite() ? ui.writeOnly(ui.button({
    label: busy ? 'Checking…' : 'Check sources now', icon: 'refresh', tone: 'primary', disabled: busy,
    onClick: async (e) => {
      const b = e.currentTarget; b.disabled = true;
      try { await forceRefresh(ctx.api); ui.toast('Checking every official source now. This page updates by itself.', 'info'); } catch (err) { b.disabled = false; ui.toast(err.message || 'Could not start the check', 'bad'); }
    },
  })) : null;
  const head = ui.pageHeader({
    title: 'Official sources',
    sub: 'Each time the portal opens it re-checks the official sources the research used (AP EAPCET / ECET counselling, JNTUK, college websites). Values from here are marked live with the time they were checked; everything else is research data, labelled “' + RESEARCH_LABEL + '”.',
    meta: s ? [h('span', { class: ['lv-sumchip', `lv-sumchip--${s.tone}`] }, s.tone === 'busy' ? h('span', { class: 'td-livechip__spin', 'aria-hidden': 'true' }) : h('span', { class: 'td-livechip__dot', 'aria-hidden': 'true' }), s.text)] : null,
    actions: [checkAll, h('a', { href: '#/notices', class: 'td-btn td-btn--secondary' }, ui.icon('list', { size: 18 }), h('span', null, 'Official notices'))],
  });
  if (store.unavailable) return [head, h('div', { class: 'td-card' }, unavailableNote('source checks'))];
  if (!d) {
    return [head, ui.errorCard({ title: 'Could not load the official source status', error: store.error, retry: () => fetchLive({ refresh: true }) })];
  }
  const out = [head];
  if (store.gaveUp && d.refreshing) out.push(callout('warn', 'Still checking after 90 seconds', 'Some sources are slow. The table shows the latest result for each source; reload the page later to see the rest.'));

  const sources = Array.isArray(d.sources) ? d.sources : [];
  const table = ui.dataTable({
    caption: 'Official sources and their status',
    rowKey: (r) => r.id,
    columns: [
      { key: 'name', label: 'Source', primary: true, minWidth: 210, render: (r) => h('div', { class: 'lv-srccell' }, h('strong', null, r.name || r.id), r.url ? h('div', { class: 'lv-small' }, extLink(r.url)) : null) },
      { key: 'last_status', label: 'Status', minWidth: 170, sortValue: (r) => ({ error: 0, never: 1, running: 2, ok: 3 }[r.last_status] ?? 4),
        render: (r) => h('div', { class: 'lv-statcell' }, sourcePill(r), r.last_status === 'error' && r.last_error ? h('div', { class: 'lv-small lv-err' }, String(r.last_error).slice(0, 200)) : null) },
      { key: 'last_attempt_at', label: 'Last checked', minWidth: 150, render: (r) => when(r.last_attempt_at) },
      { key: 'last_success_at', label: 'Last good copy', minWidth: 150, render: (r) => when(r.last_success_at) },
      { key: 'provides', label: 'Provides', priority: 3, minWidth: 200, render: (r) => h('span', { class: 'lv-small' }, r.provides || '—') },
      { key: 'item_count', label: 'Records', priority: 3, align: 'right', minWidth: 70, render: (r) => (r.item_count == null ? '—' : fmt.num(r.item_count)) },
      { key: 'changed_at', label: 'Content last changed', priority: 3, minWidth: 150, render: (r) => (r.changed_at ? when(r.changed_at) : h('span', { class: 'lv-muted' }, '—')) },
    ],
    rows: sources,
    rowActions: canWrite() ? (r) => [{ label: 'Check now', icon: 'refresh', writeOnly: true, onClick: async () => {
      try { await forceRefresh(ctx.api, r.id); ui.toast(`Checking ${r.name || r.id} now.`, 'info'); } catch (err) { ui.toast(err.message || 'Could not start the check', 'bad'); }
    } }] : null,
    empty: { title: 'No official sources configured', text: 'The server has no live sources set up.' },
  });
  out.push(ui.section({ title: 'Sources', sub: 'Each source is re-checked when its copy is older than its refresh interval. “Unreachable” means the last attempt failed; the last good copy is still used and is labelled with its date.', body: table }));

  const cov = d.coverage || null;
  if (cov) {
    const of = (n) => (cov.colleges ? `of ${fmt.num(cov.colleges)} colleges` : null);
    out.push(ui.section({
      title: 'Coverage', sub: 'How many portal colleges could be linked to each official list.',
      body: ui.kpiRow([
        ui.kpi({ label: 'Colleges in the portal', value: cov.colleges ?? null, icon: 'college' }),
        ui.kpi({ label: 'In B.Tech counselling (EAPCET)', value: cov.linked_eapcet ?? null, sub: of(), icon: 'link' }),
        ui.kpi({ label: 'In lateral-entry counselling (ECET)', value: cov.linked_ecet ?? null, sub: of(), icon: 'link' }),
        ui.kpi({ label: 'In JNTUK affiliated list', value: cov.linked_jntuk ?? null, sub: of(), icon: 'link' }),
        ui.kpi({ label: 'Websites checked', value: cov.website_checked ?? null, sub: cov.website_ok != null ? `${fmt.num(cov.website_ok)} answered` : null, icon: 'external' }),
      ]),
    }));
  }

  const auto = Array.isArray(d.automation) ? d.automation : [];
  if (auto.length) {
    out.push(ui.section({
      title: 'What updates automatically',
      sub: 'Automatic = refreshed from an official source with no one involved. Partly = some colleges or fields only. Manual = still from the November 2026 research and edits by the team.',
      body: ui.dataTable({
        caption: 'Automation by topic', rowKey: (r) => r.topic,
        columns: [
          { key: 'topic', label: 'Topic', primary: true, minWidth: 170 },
          { key: 'status', label: 'Updates', minWidth: 150, sortValue: (r) => ({ automatic: 0, partial: 1, manual: 2 }[r.status] ?? 3), render: (r) => { const a = AUTO[r.status] || [r.status || '—', 'neutral']; return ui.badge(a[0], a[1]); } },
          { key: 'source', label: 'Source', minWidth: 150, render: (r) => h('span', { class: 'lv-small' }, r.source || '—') },
          { key: 'how', label: 'How', priority: 3, minWidth: 200, render: (r) => h('span', { class: 'lv-small' }, r.how || '—') },
          { key: 'note', label: 'Note', priority: 3, minWidth: 200, render: (r) => h('span', { class: 'lv-small lv-muted' }, r.note || '—') },
        ],
        rows: auto,
      }),
    }));
  }

  const changes = Array.isArray(d.recent_changes) ? d.recent_changes : [];
  const srcName = new Map(sources.map((x) => [x.id, x.name || x.id]));
  const list = h('ul', { class: 'lv-changes' });
  const fill = (n) => list.replaceChildren(...changes.slice(0, n).map((c) => h('li', { class: 'lv-change' },
    h('div', { class: 'lv-change__meta' }, when(c.at), h('span', { class: 'lv-muted' }, ' · ', srcName.get(c.source) || c.source || 'source')),
    h('div', { class: 'lv-change__text' },
      c.college_id ? h('a', { href: `#/college/${encodeURIComponent(c.college_id)}`, class: 'lv-change__college' }, c.college_name || c.college_id) : null,
      c.college_id ? ': ' : null, c.summary || ''))),
  ...(changes.length > n ? [h('li', null, ui.button({ label: `Show all ${changes.length}`, tone: 'ghost', size: 'sm', onClick: () => fill(changes.length) }))] : []));
  fill(10);
  out.push(ui.section({
    title: 'Recent changes in official data', sub: 'Newest first. A change is recorded when a source’s content differs from the previous check.',
    body: changes.length ? list : ui.emptyState({ icon: 'clock', title: 'No changes seen yet', text: 'Changes appear here once a source differs from its previous check.' }),
  }));
  return out;
}

/* =========================================================================
   Page: #/notices — Official notices (?category=&q=)
   ========================================================================= */
export async function renderNotices(el, params = {}, ctx) {
  destroy();
  ctx.setBreadcrumb && ctx.setBreadcrumb([{ label: 'Official notices' }]);
  el.className = 'v-live v-live-notices';
  if (!store.api) startLive(ctx.api);
  const me = { off: null, category: params.category || '', q: params.q || '', seq: 0 };
  page = me;

  const metaEl = h('div', { class: 'lv-notice-meta', 'aria-live': 'polite' });
  const head = ui.pageHeader({
    title: 'Official notices',
    sub: 'Circulars, exam timetables, results and calendars from the JNTUK notifications page, fetched live. Attachments open on the official site in a new tab.',
    actions: [h('a', { href: '#/live', class: 'td-btn td-btn--secondary' }, ui.icon('data', { size: 18 }), h('span', null, 'Official sources'))],
  });
  const segHost = h('div', { class: 'lv-seghost' });
  const search = h('input', { type: 'search', class: 'td-input lv-search', placeholder: 'Search notices…', 'aria-label': 'Search notices', value: me.q });
  search.value = me.q;
  let t;
  search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { me.q = search.value.trim(); ui.setHashQuery({ q: me.q || null }); load(); }, 250); });
  const countEl = h('span', { class: 'lv-muted lv-small', 'aria-live': 'polite' });
  const listHost = h('div', { class: 'lv-notices' });
  const table = ui.dataTable({
    caption: 'Official notices', rowKey: (r) => r.uid, pageSize: 25, pageLabel: 'notices', loading: true, cardSort: false,
    columns: [
      { key: 'date', label: 'Date', minWidth: 110, cardHidden: true, render: (r) => h('span', { class: 'lv-nowrap' }, dateOnly(r.date)) },
      { key: 'title', label: 'Notice', primary: true, minWidth: 280, render: (r) => noticeMain(r) },
      { key: 'category', label: 'Type', minWidth: 120, cardHidden: true, render: (r) => catBadge(r.category, me.cats) },
      { key: 'dept', label: 'Department', priority: 3, minWidth: 140, cardHidden: true, render: (r) => h('span', { class: 'lv-small' }, r.dept || r.section || '—') },
    ],
    cardTitle: (r) => noticeMain(r),
    cardSubtitle: (r) => h('span', { class: 'lv-small lv-muted' }, [dateOnly(r.date), r.dept || r.section].filter(Boolean).join(' · ')),
    cardMeta: (r) => [catBadge(r.category, me.cats)],
    rows: [],
    empty: { title: 'No notices found', text: 'Try another category or clear the search.' },
  });
  listHost.append(table);
  el.replaceChildren(head, metaEl, h('div', { class: 'lv-toolbar' }, segHost, h('div', { class: 'lv-toolbar__row' }, search, countEl)), listHost);

  async function load() {
    const my = ++me.seq;
    table.update({ loading: true });
    let r;
    try {
      r = await ctx.api.get('/live/announcements', { category: me.category || undefined, q: me.q || undefined, limit: 200 });
    } catch (e) {
      if (page !== me || my !== me.seq) return;
      if (e && (e.status === 404 || e.status === 405)) { listHost.replaceChildren(h('div', { class: 'td-card' }, unavailableNote('notices'))); segHost.replaceChildren(); metaEl.replaceChildren(); return; }
      table.update({ loading: false, error: e });
      return;
    }
    if (page !== me || my !== me.seq) return;
    me.cats = Array.isArray(r.categories) ? r.categories : [];
    const items = Array.isArray(r.items) ? r.items : [];
    const total = me.cats.reduce((n, c) => n + (Number(c.count) || 0), 0);
    const seg = ui.segmented({
      ariaLabel: 'Notice type', value: me.category,
      options: [{ value: '', label: 'All', count: total || undefined }, ...me.cats.map((c) => ({ value: c.id, label: c.label || c.id, count: c.count ?? undefined }))],
      onChange: (v) => { me.category = v; ui.setHashQuery({ category: v || null }, { replace: 'auto' }); load(); },
    });
    segHost.replaceChildren(seg);
    metaEl.replaceChildren(noticeStatus(r));
    countEl.textContent = `${fmt.num(items.length)} ${items.length === 1 ? 'notice' : 'notices'}${me.q ? ` matching “${me.q}”` : ''}`;
    const src = r.source || {};
    const empty = !items.length && !src.last_success_at
      ? { icon: 'clock', title: 'Notices have not been fetched yet', text: 'The JNTUK notifications page has not been read successfully yet. Check the official sources page.' }
      : (me.q || me.category ? { icon: 'filter', title: 'No notices match', text: 'Try another type or clear the search.' } : { title: 'No notices found', text: '' });
    table.update({ rows: items, loading: false, error: null, empty });
  }
  const onLive = (e) => { if (page === me && el.isConnected && e.detail && e.detail.finished) load(); };
  addEventListener(LIVE_EVENT, onLive);
  me.off = () => removeEventListener(LIVE_EVENT, onLive);
  await load();
}

function catBadge(id, cats) {
  const c = (cats || []).find((x) => x.id === id);
  const tone = { exam: 'info', result: 'good', calendar: 'brand', holiday: 'neutral', admission: 'warn' }[id] || 'neutral';
  return ui.badge(c ? c.label : (id ? String(id) : 'Other'), tone);
}
function attachmentLinks(r) {
  const att = Array.isArray(r.attachments) ? r.attachments.filter((a) => a && safeUrl(a.url)) : [];
  if (!att.length) return null;
  const norm = (x) => String(x || '').trim().toLowerCase();
  const label = (a, i) => (!a.name || norm(a.name) === norm(r.title) ? (att.length > 1 ? `Attachment ${i + 1}` : 'Open attachment') : a.name);
  return h('ul', { class: 'lv-att', 'aria-label': 'Attachments' }, att.map((a, i) => h('li', null, extLink(a.url, label(a, i), { cls: 'lv-att__a' }))));
}
/** "New" = first seen in the last 48 h (server) AND dated within the last 14 days — a first-ever fetch marks old notices as seen too. */
function isNew(r) {
  if (!r.is_new) return false;
  const t = r.date ? Date.parse(String(r.date).slice(0, 10) + 'T00:00:00Z') : NaN;
  return Number.isNaN(t) || nowMs() - t <= 14 * 86400000;
}
function noticeMain(r) {
  const href = safeUrl(r.url);
  const title = r.title || '(untitled notice)';
  return h('div', { class: 'lv-notice' },
    h('div', { class: 'lv-notice__title' },
      href ? h('a', { href, target: '_blank', rel: 'noopener noreferrer' }, title) : h('span', null, title),
      isNew(r) ? h('span', { class: 'lv-new' }, ui.badge('New', 'brand')) : null),
    attachmentLinks(r));
}
function noticeStatus(r) {
  const src = r.source || {};
  if (src.using_fallback || (src.last_status === 'error' && src.last_success_at)) return sourceLine({ ...src, using_fallback: true, name: src.name || 'JNTUK notifications' });
  if (src.last_status === 'error') return callout('bad', 'Source unreachable', h('span', null, 'The JNTUK notifications page could not be read and no earlier copy exists. ', extLink(src.url, 'Open the official page')));
  if (!src.last_success_at && !r.checked_at) return h('div', { class: 'lv-srcline' }, 'Not fetched yet.');
  return sourceLine({ ...src, name: src.name || 'JNTUK notifications' }, { checkedAt: src.last_success_at || r.checked_at });
}

/* =========================================================================
   Exams page card: "Latest official exam notices" (top 5, category exam)
   ========================================================================= */
let examCache = null; // {at, data}
export function examNoticesCard(ctx) {
  const body = h('div', { class: 'lv-examcard' }, ui.skeleton(3, { card: false }));
  const sec = ui.section({
    title: 'Latest official exam notices',
    sub: 'Live from the JNTUK notifications page.',
    actions: h('a', { href: '#/notices?category=exam', class: 'lv-more' }, 'All exam notices', ui.icon('chevron', { size: 14 })),
    body,
  });
  sec.classList.add('lv-section', 'v-live');
  const draw = (r) => {
    const items = (Array.isArray(r.items) ? r.items : []).slice(0, 5);
    body.replaceChildren(noticeStatus(r),
      items.length ? h('ul', { class: 'lv-nlist' }, items.map((n) => h('li', { class: 'lv-nlist__item' },
        h('div', { class: 'lv-nlist__date' }, dateOnly(n.date)), noticeMain(n))))
        : h('p', { class: 'lv-muted' }, 'No exam notices in the latest copy of the JNTUK page.'));
  };
  const load = async (force) => {
    if (!force && examCache && Date.now() - examCache.at < 60000) { draw(examCache.data); return; }
    try {
      const r = await ctx.api.get('/live/announcements', { category: 'exam', limit: 5 });
      examCache = { at: Date.now(), data: r };
      if (sec.isConnected || !force) draw(r);
    } catch (e) {
      if (e && (e.status === 404 || e.status === 405)) { sec.remove(); return; }
      body.replaceChildren(ui.errorCard({ title: 'Could not load official exam notices', error: e, retry: () => load(true) }));
    }
  };
  const onLive = (e) => { if (!sec.isConnected) { removeEventListener(LIVE_EVENT, onLive); return; } if (e.detail && e.detail.finished) load(true); };
  addEventListener(LIVE_EVENT, onLive);
  load(false);
  return sec;
}

/* =========================================================================
   College page card: "Official live data"
   ========================================================================= */
const PRESENCE = [
  ['eapcet', 'B.Tech counselling (EAPCET 2026)'],
  ['ecet', 'Lateral-entry counselling (ECET 2026)'],
  ['jntuk_affiliated', 'JNTUK affiliated'],
  ['website', 'Website up'],
];
export function collegeLiveCard(ctx, collegeId, college = {}) {
  const body = h('div', { class: 'lv-college' }, ui.skeleton(3, { card: false }));
  const checkedEl = h('span');
  const sec = ui.section({
    title: h('span', { class: 'lv-title' }, h('span', { class: 'lv-livedot', 'aria-hidden': 'true' }), 'Official live data'),
    sub: checkedEl,
    actions: h('a', { href: '#/live', class: 'lv-more' }, 'Sources', ui.icon('chevron', { size: 14 })),
    body,
  });
  sec.classList.add('lv-section', 'v-live', 'lv-collegecard');
  const load = async () => {
    let d;
    try { d = await ctx.api.get(`/live/college/${encodeURIComponent(collegeId)}`); } catch (e) {
      if (e && (e.status === 404 || e.status === 405)) {
        checkedEl.textContent = '';
        body.replaceChildren(unavailableNote('college checks'));
        return;
      }
      body.replaceChildren(ui.errorCard({ title: 'Could not load the official live data', error: e, retry: load }));
      return;
    }
    checkedEl.replaceChildren(h('span', null, 'Fetched from official sources each time the portal opens · checked '), when(d.checked_at));
    body.replaceChildren(...collegeLiveBody(ctx, d, collegeId, college));
  };
  const onLive = (e) => { if (!sec.isConnected) { removeEventListener(LIVE_EVENT, onLive); return; } if (e.detail && e.detail.finished) load(); };
  addEventListener(LIVE_EVENT, onLive);
  load();
  return sec;
}

function presenceItem(key, label, d) {
  const p = d.presence || {};
  const v = p[key];
  const part = key === 'jntuk_affiliated' ? d.jntuk : key === 'website' ? null : d[key];
  let badge; let sub;
  if (key === 'website') {
    const w = d.website;
    if (!w) { badge = ui.badge('Website: not checked', 'neutral'); sub = h('span', { class: 'lv-muted' }, 'No website on record to check'); }
    else if (v === true || w.ok) { badge = ui.badge('Website up', 'good'); sub = when(w.checked_at, { prefix: 'checked ' }); }
    else {
      badge = ui.badge('Website not answering', 'warn');
      sub = h('span', null, [w.http_status ? `HTTP ${w.http_status}` : null, w.error ? String(w.error).slice(0, 80) : null].filter(Boolean).join(' · ') || 'No answer', ' · ', when(w.checked_at, { prefix: 'checked ' }),
        w.last_ok_at ? h('span', { class: 'lv-muted' }, ` · last up ${relTime(w.last_ok_at)}`) : null);
    }
  } else if (!part) {
    badge = ui.badge(`${label}: not linked`, 'neutral');
    sub = h('span', { class: 'lv-muted' }, 'Not linked to this source');
  } else if (v === null || v === undefined) {
    badge = ui.badge(`${label}: unknown`, 'neutral');
    sub = part.source && part.source.last_success_at ? when(part.source.last_success_at, { prefix: 'checked ' }) : h('span', { class: 'lv-muted' }, 'Source not fetched yet');
  } else {
    const yes = key === 'jntuk_affiliated' ? 'JNTUK affiliated' : `Listed in ${label}`;
    const no = key === 'jntuk_affiliated' ? 'Not matched in the JNTUK list' : `Not matched in the ${label} list`;
    badge = ui.badge(v ? yes : no, v ? 'good' : 'warn');
    sub = part.source && part.source.using_fallback
      ? h('span', { class: 'lv-warntext' }, 'Source unreachable — last copy ', part.source.last_success_at ? absTime(part.source.last_success_at) : '')
      : when(part.source && part.source.last_success_at, { prefix: 'checked ' });
  }
  return h('li', { class: 'lv-presence__item' }, badge, h('div', { class: 'lv-small' }, sub));
}

function linkBasis(link) {
  if (!link) return null;
  if (link.basis === 'research_code') return ui.badge(`Linked by college code${link.code || link.cc ? ` (${link.code || link.cc})` : ''}`, 'good');
  const sc = link.score != null && Number.isFinite(Number(link.score)) ? ` · ${Math.round(Number(link.score) * (Number(link.score) <= 1 ? 100 : 1))}% match` : '';
  return ui.badge(`Linked by name — please check${sc}`, 'warn');
}

function feedBlock(ctx, label, part, { branches = true } = {}) {
  if (!part) return h('div', { class: 'lv-feed' }, h('h3', { class: 'lv-h3' }, label), h('p', { class: 'lv-muted lv-small' }, 'Not linked to this source.'));
  const rec = part.record;
  const head = h('div', { class: 'lv-feed__head' }, h('h3', { class: 'lv-h3' }, label), linkBasis(part.link));
  if (!rec) return h('div', { class: 'lv-feed' }, head, sourceLine(part.source), h('p', { class: 'lv-muted lv-small' }, 'Linked, but this college is not in the latest copy of the source.'));
  const kids = [head, sourceLine(part.source)];
  const web = rec.website ? extLink(/^https?:/i.test(rec.website) ? rec.website : `http://${rec.website}`, rec.website) : null;
  kids.push(ui.kv([
    rec.code ? ['Counselling college code', rec.code] : null,
    rec.cc ? ['JNTUK college code', rec.cc] : null,
    rec.name ? ['Name in this list', rec.name] : null,
    rec.place || rec.district ? ['Place', [rec.place, rec.district].filter(Boolean).join(', ')] : null,
    rec.affiliated_to ? ['Affiliated to', rec.affiliated_to] : null,
    rec.college_type || rec.aid_unaid || rec.co_educ ? ['Type', [rec.college_type, rec.aid_unaid, rec.co_educ, rec.minority].filter(Boolean).join(' · ')] : null,
    rec.year_of_estab ? ['Established', String(rec.year_of_estab)] : null,
    rec.phone ? ['Office phone', rec.phone] : null,
    rec.ao_mobile ? ['Admissions officer (mobile)', rec.ao_mobile] : null,
    rec.email ? ['Office email', rec.email] : null,
    web ? ['Website', web] : null,
    // rec.entry_date (the feed's own bookkeeping date) is not shown: it says nothing about the college
    rec.courses ? ['Courses', Array.isArray(rec.courses) ? rec.courses.join(', ') : String(rec.courses)] : null,
  ].filter(Boolean)));
  const br = Array.isArray(rec.branches) ? rec.branches : [];
  if (branches && br.length) {
    const tt = rec.totals || {};
    kids.push(h('h4', { class: 'lv-h4' }, `Branches in ${label}`,
      tt.seats != null ? h('span', { class: 'lv-muted lv-small' }, ` · ${fmt.num(tt.seats)} seats, ${fmt.num(tt.filled)} filled, ${fmt.num(tt.left_over)} still empty`) : null));
    kids.push(ui.dataTable({
      caption: `${label} branches`, rowKey: (r) => r.code || r.name, dense: true,
      columns: [
        { key: 'name', label: 'Branch', primary: true, minWidth: 180, render: (r) => h('span', null, r.name || r.code || '—', r.code && r.name ? h('span', { class: 'lv-muted lv-small' }, ` (${r.code})`) : null) },
        { key: 'total_seats', label: 'Seats', align: 'right', minWidth: 70, render: (r) => fmt.num(r.total_seats) },
        { key: 'filled', label: 'Filled', align: 'right', minWidth: 70, render: (r) => fmt.num(r.filled) },
        { key: 'left_over_seats', label: 'Still empty', align: 'right', minWidth: 80, render: (r) => fmt.num(r.left_over_seats) },
        { key: 'fee', label: 'Fee / year', align: 'right', minWidth: 90, render: (r) => (r.fee == null || r.fee === '' ? '—' : (Number.isFinite(Number(r.fee)) ? fmt.inr(Number(r.fee)) : String(r.fee))) },
        { key: 'course_type', label: 'Programme', priority: 3, minWidth: 90, render: (r) => r.course_type || '—' },
      ],
      rows: br,
    }));
  }
  return h('div', { class: 'lv-feed' }, kids);
}

function diffList(ctx, d, collegeId) {
  const diffs = Array.isArray(d.diffs) ? d.diffs : [];
  if (!diffs.length) return null;
  const canEdit = canWrite();
  return h('div', { class: 'lv-diffs' },
    h('h3', { class: 'lv-h3' }, ui.icon('warn', { size: 16 }), ` ${diffs.length === 1 ? 'One value differs' : `${diffs.length} values differ`} from the official source`),
    h('ul', { class: 'lv-difflist' }, diffs.map((x) => h('li', { class: 'lv-diff' },
      h('div', { class: 'lv-diff__label' }, x.label || x.field),
      h('div', { class: 'lv-diff__vals' },
        h('div', null, h('span', { class: 'lv-diff__k' }, 'Our record: '), h('span', { class: 'lv-diff__ours' }, x.ours == null || x.ours === '' ? '—' : String(x.ours))),
        h('div', null, h('span', { class: 'lv-diff__k' }, 'Official list: '), h('strong', null, x.live == null || x.live === '' ? '—' : String(x.live)))),
      h('div', { class: 'lv-small lv-muted' }, `${x.source_name || x.source_id || 'source'} · checked `, when(x.checked_at)),
      x.note ? h('div', { class: 'lv-diff__note' }, ui.icon('info', { size: 14 }), h('span', null, String(x.note), x.note_checked_at ? h('span', { class: 'lv-muted' }, ' (checked ', when(x.note_checked_at), ')') : null)) : null,
      canEdit && x.field && x.live != null && x.live !== '' ? ui.writeOnly(ui.button({
        label: 'Use official value', size: 'sm', tone: x.note ? 'secondary' : 'primary', icon: 'check',
        onClick: async (e) => {
          const b = e.currentTarget;
          const ok = await ui.confirm({ title: `Replace ${String(x.label || x.field).toLowerCase()}?`, text: `“${x.ours ?? '—'}” becomes “${x.live}”. The change is recorded as verified from ${x.source_name || 'the official source'}, fetched ${absTime(x.checked_at)}.`, confirmLabel: 'Use official value', tone: 'primary' });
          if (!ok) return;
          b.disabled = true;
          try {
            await ctx.api.patch(`/colleges/${encodeURIComponent(collegeId)}`, { [x.field]: x.live, sources: { [x.field]: `${x.source_name || x.source_id || 'Official source'}, fetched ${fmt.date(String(x.checked_at || '').slice(0, 10))}` } });
            ui.toast(`${x.label || x.field} updated from the official source`, 'good');
            ctx.refresh && ctx.refresh();
          } catch (err) { b.disabled = false; ui.toast(err.message || 'Could not save', 'bad'); }
        },
      })) : null))));
}

function collegeLiveBody(ctx, d, collegeId, college) {
  const out = [];
  const tone = d.signal === 'listed' ? 'good' : d.signal === 'not_found_anywhere' ? 'warn' : 'info';
  if (d.signal_text) out.push(callout(tone, null, d.signal_text));
  out.push(h('ul', { class: 'lv-presence', 'aria-label': 'Presence in official sources' }, PRESENCE.map(([k, l]) => presenceItem(k, l, d))));
  const diffs = diffList(ctx, d, collegeId);
  if (diffs) out.push(diffs);
  out.push(feedBlock(ctx, 'B.Tech counselling list (AP EAPCET 2026)', d.eapcet));
  const ecet = feedBlock(ctx, 'Lateral-entry counselling list (AP ECET 2026)', d.ecet);
  const jntuk = feedBlock(ctx, 'JNTUK affiliation list', d.jntuk, { branches: false });
  out.push(h('details', { class: 'lv-more-details' }, h('summary', null, 'Lateral-entry (ECET) and JNTUK details'), ecet, jntuk));
  const ann = Array.isArray(d.announcements) ? d.announcements : [];
  if (ann.length) {
    out.push(h('div', { class: 'lv-feed' }, h('h3', { class: 'lv-h3' }, 'Official notices mentioning this college'),
      h('ul', { class: 'lv-nlist' }, ann.slice(0, 5).map((n) => h('li', { class: 'lv-nlist__item' }, h('div', { class: 'lv-nlist__date' }, dateOnly(n.date)), noticeMain(n)))),
      ann.length > 5 ? h('a', { href: `#/notices?q=${encodeURIComponent(college.short_name || college.name || '')}`, class: 'lv-more' }, `All ${ann.length} notices`) : null));
  }
  out.push(h('p', { class: 'lv-small lv-muted lv-foot' }, 'Everything else on this page — and the fields under “College information” — is ', ui.badge(RESEARCH_LABEL, 'neutral'), '.'));
  return out;
}

/** Badge other views put next to research-only data. */
export function researchBadge() { return h('span', { class: 'lv-research', title: 'From the November 2026 research import — not refreshed from official sources.' }, ui.badge(RESEARCH_LABEL, 'neutral')); }

export default { renderSources, renderNotices, destroy };
