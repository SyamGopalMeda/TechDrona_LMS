// Tech Drona portal — app shell, router, layout, global search, district scope, session (owned by the UI shell agent)
import { api, apiHooks, ApiError } from './api.js';
import { h, fmt, debounce } from './ui/h.js';
import ui from './ui/components.js';
import {
  state, SCOPE_EVENT, getScope, setDistrictScope, resetDistrictScope, scopeLabel, scopeRows, scopeQueryValue,
  targetGroups, targetDistrictIds, targetGroupOf, setSession, canWrite, SESSION_EVENT,
} from './state.js';

/* =========================================================================
   Navigation + routes
   Primary (desktop sidebar; phone tab bar = first TAB_COUNT + More): Home, Colleges, Team, Targets & performance,
   Calls & follow-ups, Reports. More: Exams, Official notices, Official sources, Data quality, Audit log, Settings. Style guide only with ?dev=1.
   ========================================================================= */
const NAV = [
  { id: 'home', label: 'Home', short: 'Home', icon: 'home', href: '#/' },
  { id: 'colleges', label: 'Colleges', short: 'Colleges', icon: 'college', href: '#/colleges' },
  { id: 'people', label: 'Team', short: 'Team', icon: 'people', href: '#/people', tip: 'Team: college leads and ambassadors' },
  { id: 'targets', label: 'Targets & performance', short: 'Targets', icon: 'target', href: '#/targets', tip: 'Targets & performance: paid enrollments against targets, by person, college or district' },
  { id: 'calls', label: 'Calls & follow-ups', short: 'Calls', icon: 'phone', href: '#/calls' },
  { id: 'analytics', label: 'Reports', short: 'Reports', icon: 'analytics', href: '#/analytics', tip: 'Reports: trend, pace, rankings and courses' },
  { id: 'exams', label: 'Exams', icon: 'exam', href: '#/exams', more: true },
  { id: 'notices', label: 'Official notices', icon: 'list', href: '#/notices', more: true },
  { id: 'live', label: 'Official sources', icon: 'refresh', href: '#/live', more: true, tip: 'Official sources: EAPCET / ECET / JNTUK lists checked automatically' },
  { id: 'data', label: 'Data quality', icon: 'data', href: '#/data', more: true },
  { id: 'audit', label: 'Audit log', icon: 'audit', href: '#/audit', more: true },
  { id: 'settings', label: 'Settings', icon: 'settings', href: '#/settings', more: true },
];
const PRIMARY = NAV.filter((n) => !n.more);
const SECONDARY = NAV.filter((n) => n.more);
const TAB_COUNT = 4;

/** Route-level sub-sections rendered by the shell above the view (one consistent tab strip). */
const SECTIONS = {
  // ONE tab row for the Targets area (responsive.md §7): the view's own "Performance | Targets by place" switch is merged in
  targets: [
    { label: 'Performance', href: '#/targets', is: (p, q) => p === '/targets' && !(q.tab === 'places' || (q.scope && q.tab !== 'perf')) },
    { label: 'Targets by place', href: '#/targets?tab=places', is: (p, q) => p === '/targets' && (q.tab === 'places' || (q.scope && q.tab !== 'perf')) },
    { label: 'Planner', href: '#/plan', is: (p) => p === '/plan' },
  ],
  calls: [{ label: 'Call queue', href: '#/calls' }, { label: 'Follow-ups', href: '#/followups' }],
};

// layout: 'full' (default for every page now) | 'explore' (map beside the panel; a view can opt in with `export const layout`)
const ROUTES = [
  { re: /^\/$/, keys: [], mod: 'dashboard', exp: 'renderState', layout: 'full', nav: 'home', title: 'Home' },
  { re: /^\/d\/([^/]+)$/, keys: ['district'], mod: 'geo', exp: 'renderDistrict', layout: 'full', nav: 'colleges', title: 'District' },
  { re: /^\/d\/([^/]+)\/([^/]+)$/, keys: ['district', 'city'], mod: 'geo', exp: 'renderCity', layout: 'full', nav: 'colleges', title: 'Town' },
  { re: /^\/college\/([^/]+)$/, keys: ['id'], mod: 'college', exp: 'render', layout: 'full', nav: 'colleges', title: 'College' },
  { re: /^\/colleges$/, keys: [], mod: 'dashboard', exp: 'renderCollegeList', layout: 'full', nav: 'colleges', title: 'Colleges' },
  { re: /^\/calls$/, keys: [], mod: 'calls', exp: 'render', layout: 'full', nav: 'calls', section: 'calls', title: 'Calls & follow-ups' },
  { re: /^\/followups$/, keys: [], mod: 'followups', exp: 'render', layout: 'full', nav: 'calls', section: 'calls', title: 'Follow-ups' },
  { re: /^\/analytics$/, keys: [], mod: 'dashboard', exp: 'renderAnalytics', layout: 'full', nav: 'analytics', title: 'Reports' },
  { re: /^\/people$/, keys: [], mod: 'people', exp: 'renderList', layout: 'full', nav: 'people', title: 'Team' },
  { re: /^\/person\/([^/]+)$/, keys: ['id'], mod: 'people', exp: 'renderPerson', layout: 'full', nav: 'people', title: 'Person' },
  { re: /^\/exams$/, keys: [], mod: 'exams', exp: 'render', layout: 'full', nav: 'exams', title: 'Exams' },
  { re: /^\/targets$/, keys: [], mod: 'targets', exp: 'render', layout: 'full', nav: 'targets', section: 'targets', title: 'Targets & performance' },
  { re: /^\/plan$/, keys: [], mod: 'plan', exp: 'render', layout: 'full', nav: 'targets', section: 'targets', title: 'Target planner' },
  { re: /^\/live$/, keys: [], mod: 'live', exp: 'renderSources', layout: 'full', nav: 'live', title: 'Official sources' },
  { re: /^\/notices$/, keys: [], mod: 'live', exp: 'renderNotices', layout: 'full', nav: 'notices', title: 'Official notices' },
  { re: /^\/data$/, keys: [], mod: 'admin', exp: 'renderData', layout: 'full', nav: 'data', title: 'Data quality' },
  { re: /^\/audit$/, keys: [], mod: 'admin', exp: 'renderAudit', layout: 'full', nav: 'audit', title: 'Audit log' },
  { re: /^\/settings$/, keys: [], mod: 'admin', exp: 'renderSettings', layout: 'full', nav: 'settings', title: 'Settings' },
  { re: /^\/styleguide$/, keys: [], builtin: renderStyleguide, layout: 'full', nav: 'styleguide', title: 'Style guide', dev: true },
];
/** Friendly / legacy paths → canonical routes (kept so old links and bookmarks keep working). */
const ALIASES = {
  '/home': '/', '/overview': '/', '/map': '/', '/team': '/people', '/people/list': '/people', '/reports': '/analytics',
  '/planner': '/plan', '/targets/plan': '/plan', '/performance': '/targets', '/calling': '/calls', '/follow-ups': '/followups',
  '/calls/followups': '/followups', '/sources': '/live', '/official': '/live', '/announcements': '/notices', '/quality': '/data', '/data-quality': '/data', '/verification': '/data', '/log': '/audit',
};
/** Developer pages (style guide) need ?dev=1 once per browser session. */
function devMode() {
  let on = false;
  try {
    const q = new URLSearchParams(location.search).get('dev') || new URLSearchParams((location.hash.split('?')[1]) || '').get('dev');
    if (q === '1') sessionStorage.setItem('td.dev', '1');
    if (q === '0') sessionStorage.removeItem('td.dev');
    on = sessionStorage.getItem('td.dev') === '1';
  } catch { on = false; }
  return on;
}

const VIEW_MODULES = {
  dashboard: () => import('./views/dashboard.js'),
  geo: () => import('./views/geo.js'),
  college: () => import('./views/college.js'),
  people: () => import('./views/people.js'),
  followups: () => import('./views/followups.js'),
  calls: () => import('./views/calls.js'),
  exams: () => import('./views/exams.js'),
  targets: () => import('./views/targets.js'),
  plan: () => import('./views/plan.js'),
  admin: () => import('./views/admin.js'),
  live: () => import('./views/live.js'),
};

// Layout chrome follows the form factor set on <html data-form> by ui/components.js (phone | tablet | desktop).
const mqPhone = { get matches() { return ui.formFactor() === 'phone'; } };
const mqDesktop = { get matches() { return ui.formFactor() === 'desktop'; } };
/** phones and narrow tablet bars use the search icon + full-width search instead of the inline box */
function syncCompactBar() {
  if (!$.root) return;
  const compact = ui.formFactor() === 'phone' || innerWidth < 900;
  $.root.classList.toggle('search-compact', compact);
  if (!compact) closeMobileSearch();
}

/* =========================================================================
   API wrapping: online/offline tracking, "who are you" before writes, passcode retry
   ========================================================================= */
const raw = { get: api.get, post: api.post, patch: api.patch, put: api.put, del: api.del };
let online = true;
function setOnline(v) {
  if (online === v) return;
  online = v;
  renderBanners();
  if (v) { loadMeta(); if (lastFailedRoute) { lastFailedRoute = false; route({ keepScroll: true }); } }
}
apiHooks.onNetwork = (ok) => setOnline(ok);
// F8: the server refused the district scope — say so (never show whole-state numbers under a district chip).
let scopeRejected = null;
apiHooks.onScopeRejected = (err) => {
  const msg = (err && err.message) || 'The selected districts could not be used.';
  if (scopeRejected === msg) return;
  scopeRejected = msg;
  renderBanners();
};
let lastFailedRoute = false;
async function tracked(fn, args, { authRetry = true } = {}) {
  try { const r = await fn(...args); setOnline(true); return r; } catch (e) {
    if (e && e.status === 0) setOnline(false);
    // F7: session expired mid-use — sign in on top of whatever is open (dialogs stay mounted, input is kept), then
    // retry this request once. A write keeps its Idempotency-Key (a 401 is never stored by the server).
    if (authRetry && e && e.status === 401 && api.mode === 'session') {
      await showLogin({ reason: 'Your session has ended. Please sign in again — what you were doing is kept.' });
      return tracked(fn, args, { authRetry: false });
    }
    throw e;
  }
}
/** Writes: viewer sessions are refused up front; a legacy 401 asks for the team passcode and retries once with the SAME idempotency key. */
async function writeCall(fn, args) {
  if (!canWrite()) throw new ApiError(403, isSso() ? 'You have view-only access, so this change was not saved. Ask an LMS super admin for edit access.' : 'You have view-only access, so this change was not saved. Ask an admin for an editor passcode.');
  await ensureUser();
  // pin one Idempotency-Key for this logical write so the retry below cannot create a duplicate
  const a = [...args];
  const optIdx = fn === raw.del ? 1 : 2;
  a[optIdx] = { ...(a[optIdx] || {}) };
  if (!a[optIdx].idempotencyKey) a[optIdx].idempotencyKey = api.newKey();
  try { return await tracked(fn, a); } catch (e) {
    if (e && e.status === 401 && api.mode !== 'session') {
      const ok = await askPasscode(e.message);
      if (ok) return tracked(fn, a);
    }
    throw e;
  }
}
api.get = (...a) => tracked(raw.get, a);
api.post = (...a) => writeCall(raw.post, a);
api.patch = (...a) => writeCall(raw.patch, a);
api.put = (...a) => writeCall(raw.put, a);
api.del = (...a) => writeCall(raw.del, a);

/* =========================================================================
   DOM skeleton
   ========================================================================= */
const $ = {};
let breadcrumbItems = null;

function buildShell() {
  const root = document.getElementById('td-app');
  root.textContent = '';

  // top bar
  $.navToggle = ui.button({ icon: 'menu', tone: 'ghost', ariaLabel: 'Toggle navigation', onClick: toggleNav });
  $.navToggle.classList.add('td-topbar__menu');
  const brand = h('a', { href: '#/', class: 'td-brand', 'aria-label': 'Tech Drona outreach portal — home' },
    brandLogo('mark', { class: 'td-brand__mark', width: 36, height: 36 }),
    h('span', { class: 'td-brand__text' },
      brandLogo('wordmark', { class: 'td-brand__word', width: 118, height: 15 }),
      h('span', { class: 'td-brand__sub' }, 'Outreach Portal')));
  $.pageTitle = h('span', { class: 'td-topbar__title', 'aria-hidden': 'true' });
  $.search = buildSearch();
  $.searchBtn = ui.button({ icon: 'search', tone: 'ghost', ariaLabel: 'Search', onClick: openMobileSearch });
  $.searchBtn.classList.add('td-topbar__searchbtn');
  $.themeBtn = ui.button({ icon: 'moon', tone: 'ghost', ariaLabel: 'Switch theme', onClick: toggleTheme });
  $.userBtn = h('button', { type: 'button', class: 'td-user', onClick: () => userMenu(), 'aria-label': 'Who is using this portal' });
  $.scope = buildScopeControl();
  // Owner review 2026-11-14: the "Checked 5 h ago" official-source chip was a background technical detail, so it is no longer
  // shown in the top bar. The background refresh still runs (boot) and the status stays on More › Official sources.
  $.liveSlot = h('span', { class: 'td-liveslot', hidden: true });
  // Module switcher (owner 2026-11-14): the same "Modules" menu as the LMS top bar, shown when the portal runs
  // inside the LMS (SSO). The list comes from the LMS itself (GET /api/v1/me/modules, same origin), so it always
  // matches what this account may open; "All modules" opens the LMS hub.
  $.modItems = [];
  $.modulesBtn = ui.menu({ label: 'Modules', icon: null, tone: 'secondary', size: 'sm', ariaLabel: 'Switch module', items: $.modItems });
  $.modulesBtn.classList.add('td-topbar__modules');
  $.modulesBtn.hidden = true;
  loadModules();
  const topbar = h('header', { class: 'td-topbar' },
    $.navToggle, brand, $.pageTitle, $.scope.root, $.search.root,
    h('div', { class: 'td-topbar__actions' }, $.liveSlot, $.modulesBtn, $.searchBtn, $.themeBtn, $.userBtn));

  $.banners = h('div', { class: 'td-banners' });

  // left nav
  // title + aria-label: the collapsed (icon-only) sidebar still names every link (tooltip and screen readers)
  const navLink = (n) => h('a', { href: n.href, class: 'td-nav__link', dataset: { nav: n.id }, title: n.tip || n.label, 'aria-label': n.label },
    ui.icon(n.icon, { size: 20 }), h('span', { class: 'td-nav__label' }, n.label));
  $.navLinks = NAV.map(navLink);
  $.collapseBtn = h('button', { type: 'button', class: 'td-nav__collapse', onClick: toggleCollapse, 'aria-label': 'Collapse navigation' },
    ui.icon('chevron-left', { size: 18 }), h('span', { class: 'td-nav__label' }, 'Collapse'));
  const dev = devMode();
  $.nav = h('nav', { class: 'td-nav', 'aria-label': 'Main' },
    h('div', { class: 'td-nav__group' }, $.navLinks.slice(0, PRIMARY.length)),
    h('div', { class: 'td-nav__group' }, h('div', { class: 'td-nav__heading' }, 'More'), $.navLinks.slice(PRIMARY.length)),
    h('div', { class: 'td-nav__foot' },
      dev ? h('a', { href: '#/styleguide', class: 'td-nav__link td-nav__link--quiet', dataset: { nav: 'styleguide' }, title: 'Style guide (developer)' }, ui.icon('palette', { size: 18 }), h('span', { class: 'td-nav__label' }, 'Style guide')) : null,
      $.collapseBtn));
  $.navScrim = h('div', { class: 'td-nav-scrim', onClick: () => setNavOpen(false) });

  // stage: (optional) map + panel. The map normally lives in a card a view mounts (ctx.mountMap); explore layout is opt-in.
  $.mapEl = h('div', { id: 'td-map', class: 'td-map', role: 'region', 'aria-label': 'Map of Andhra Pradesh' });
  $.mapToggle = h('button', { type: 'button', class: 'td-maptoggle', onClick: toggleListMap });
  $.unplaced = h('a', { href: '#/data', class: 'td-map-unplaced', hidden: true });
  $.mapWrap = h('div', { class: 'td-mapwrap' }, $.mapEl, $.unplaced);
  $.crumbs = h('nav', { class: 'td-crumbs', 'aria-label': 'Breadcrumb' });
  $.sectionTabs = h('div', { class: 'td-sectiontabs', hidden: true });
  $.handle = h('div', { class: 'td-sheet-handle', 'aria-hidden': 'true' }, h('span'));
  $.view = h('div', { id: 'td-view', class: 'td-view', tabindex: '-1' });
  $.panelHead = h('div', { class: 'td-panel__head' }, h('div', { class: 'td-panel__crumbrow' }, $.crumbs), $.sectionTabs);
  $.panel = h('section', { class: 'td-panel', 'aria-label': 'Page content' }, $.handle, $.panelHead, $.view);
  $.stage = h('div', { class: 'td-stage' }, $.mapWrap, $.panel, $.mapToggle);
  $.main = h('main', { class: 'td-main', id: 'td-main' }, $.stage);

  // bottom tab bar (phones): first TAB_COUNT primary items + More
  $.tabLinks = PRIMARY.slice(0, TAB_COUNT).map((n) => h('a', { href: n.href, class: 'td-tabbar__item', dataset: { nav: n.id }, 'aria-label': n.label },
    ui.icon(n.icon, { size: 22 }), h('span', null, n.short || n.label)));
  $.moreBtn = h('button', { type: 'button', class: 'td-tabbar__item', onClick: openMoreSheet, dataset: { nav: 'more' }, 'aria-haspopup': 'dialog' }, ui.icon('more', { size: 22 }), h('span', null, 'More'));
  $.tabbar = h('nav', { class: 'td-tabbar', 'aria-label': 'Main' }, $.tabLinks, $.moreBtn);

  root.append(topbar, $.banners, h('div', { class: 'td-body' }, $.nav, $.navScrim, $.main), $.tabbar);
  $.root = root;

  initSheet();
  renderUser();
  renderThemeBtn();
  syncThemeColor();
  renderScopeControl();
  if (readLS('td.nav') === 'collapsed') root.classList.add('nav-collapsed');
}

/** Official logo as theme-aware <img> pair (navy on light, white on dark). kind: 'mark' | 'wordmark' | 'wordmark-tagline' */
function brandLogo(kind, { class: cls, width, height, alt = '' } = {}) {
  return h('span', { class: ['td-logo', cls] },
    h('img', { class: 'td-logo-navy', src: `assets/brand/${kind}-navy.svg`, alt, width, height, decoding: 'async' }),
    h('img', { class: 'td-logo-white', src: `assets/brand/${kind}-white.svg`, alt, width, height, decoding: 'async' }));
}

/* =========================================================================
   Theme
   ========================================================================= */
function readLS(k) { try { return localStorage.getItem(k); } catch { return null; } }
function writeLS(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { /* ignore */ } }
function currentTheme() { return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'; }
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  renderThemeBtn();
  syncThemeColor();
}
/** Browser chrome colour follows the chosen theme, not only the OS preference. */
function syncThemeColor() {
  const c = currentTheme() === 'dark' ? '#060C20' : '#032269';
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => { m.setAttribute('content', c); m.removeAttribute('media'); });
}
function toggleTheme() {
  const t = currentTheme() === 'dark' ? 'light' : 'dark';
  writeLS('td.theme', t);
  applyTheme(t);
}
function renderThemeBtn() {
  if (!$.themeBtn) return;
  const dark = currentTheme() === 'dark';
  $.themeBtn.replaceChildren(ui.icon(dark ? 'sun' : 'moon', { size: 18 }));
  $.themeBtn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  $.themeBtn.title = dark ? 'Light theme' : 'Dark theme';
}
// Settings page changes theme/name directly; keep the header in sync.
window.addEventListener('td:theme', () => { renderThemeBtn(); syncThemeColor(); });
window.addEventListener('td:user', () => renderUser());
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
  if (!readLS('td.theme')) applyTheme(e.matches ? 'dark' : 'light');
});

/* =========================================================================
   Current user
   ========================================================================= */
function initials(name) { return (name || '').split(/\s+/).filter(Boolean).slice(0, 2).map((x) => x[0].toUpperCase()).join('') || '?'; }
const ROLE_LABEL = { admin: 'Admin', editor: 'Editor', viewer: 'View only' };
function renderUser() {
  if (!$.userBtn) return;
  const s = state.session;
  const clean = (v) => (typeof v === 'string' && v.trim() && !/^(null|undefined)$/i.test(v.trim()) ? v.trim() : '');
  const name = s.mode === 'session' ? (clean(s.user) || clean(api.user)) : clean(api.user);
  const role = s.mode === 'session' && s.role ? ROLE_LABEL[s.role] || s.role : null;
  $.userBtn.replaceChildren(
    h('span', { class: ['td-user__avatar', !name && 'is-empty'] }, name ? initials(name) : ui.icon('user', { size: 16 })),
    h('span', { class: 'td-user__name' }, name || "Who's using this?"),
    ...(role ? [h('span', { class: ['td-user__role', s.role === 'viewer' && 'is-viewer'] }, role)] : []));
  $.userBtn.title = s.mode === 'session' ? `Signed in as ${name || '—'}${role ? ` (${role})` : ''}${isSso() ? ' through Tech Drona LMS' : ''}` : (name ? `You are ${name} — click to change` : 'Tell us who you are');
  $.userBtn.setAttribute('aria-label', $.userBtn.title);
}

/* Tech Drona LMS single sign-on: the LMS serves the portal under /college-portal/ (framed in its admin dashboard) and
   its proxy asserts who is signed in. There is no passcode screen and no portal sign-out: the LMS session is the sign-in. */
const LMS_LOGIN_URL = '/login?next=%2Fadmin%2Fcollege-data';
function isSso() { return !!state.session.sso || /^\/college-portal(\/|$)/.test(location.pathname); }
/** Navigate the TOP window (the LMS page around the iframe); falls back to this window when the top is not reachable. */
function topNavigate(url) {
  try { if (window.top && window.top !== window) { window.top.location.href = url; return; } } catch { /* cross-origin top: fall back */ }
  location.href = url;
}

/**
 * Leave the portal for an LMS page after closing a menu or dialog. Menus and dialogs add a history entry while open
 * (Back closes them) and remove it with history.back() just after they close; that back() would cancel a page
 * navigation started in the same click, so navigate once it has finished (or after 400 ms if there was none).
 */
function leaveTo(url) {
  let done = false;
  const leave = () => { if (done) return; done = true; removeEventListener('popstate', leave); topNavigate(url); };
  addEventListener('popstate', leave);
  setTimeout(leave, 400);
}

/** Fill the Modules menu from the LMS (SSO mode only). Silent on failure: the button simply stays hidden. */
async function loadModules() {
  if (!isSso()) return;
  let mods = [];
  try {
    const r = await fetch('/api/v1/me/modules', { credentials: 'same-origin', headers: { accept: 'application/json' } });
    if (!r.ok) return;
    mods = (await r.json()).modules || [];
  } catch { return; }
  const hrefFor = (m) => (m.key === 'lms' ? `/continue?area=lms&fallback=${encodeURIComponent(m.href || '/modules')}` : m.href);
  const items = mods.filter((m) => m && m.href).map((m) => (m.key === 'colleges'
    ? { label: `${m.title} (you are here)`, icon: 'check', onClick: () => {} }
    : { label: m.title, icon: m.external ? 'external' : null, onClick: () => leaveTo(hrefFor(m)) }));
  items.push({ label: 'All modules', icon: 'home', onClick: () => leaveTo('/modules') });
  $.modItems.splice(0, $.modItems.length, ...items);
  $.modulesBtn.hidden = false;
}

/** Session mode: account menu (who + sign out). Legacy mode: the "Who's using this?" dialog. SSO: who + back to the LMS. */
function userMenu() {
  if (state.session.mode !== 'session' && !isSso()) { whoModal(); return; }
  const s = state.session;
  if (isSso()) {
    const body = h('div', { class: 'td-acct' },
      h('div', { class: 'td-acct__who' },
        h('span', { class: 'td-user__avatar' }, initials(s.user || api.user)),
        h('div', null, h('strong', null, s.user || api.user || '—'), h('div', { class: 'td-muted' }, ROLE_LABEL[s.role] || 'Signed in'))),
      h('p', { class: 'td-muted' }, 'Signed in through Tech Drona LMS'),
      s.role === 'viewer' ? h('p', { class: 'td-muted' }, 'You can look at everything but cannot make changes. Ask an LMS super admin for edit access.') : null,
      h('div', { class: 'td-acct__actions' }, ui.button({ label: 'Back to LMS admin', icon: 'chevron-left', tone: 'secondary', onClick: () => { m.close(); leaveTo('/admin'); } })));
    const m = ui.modal({ title: 'Your account', body });
    return;
  }
  const body = h('div', { class: 'td-acct' },
    h('div', { class: 'td-acct__who' },
      h('span', { class: 'td-user__avatar' }, initials(s.user || api.user)),
      h('div', null, h('strong', null, s.user || api.user || '—'), h('div', { class: 'td-muted' }, ROLE_LABEL[s.role] || 'Signed in'))),
    s.role === 'viewer' ? h('p', { class: 'td-muted' }, 'You can look at everything but cannot make changes. Sign in with an editor passcode to edit.') : null,
    h('div', { class: 'td-acct__actions' }, ui.button({ label: 'Sign out', icon: 'logout', tone: 'secondary', onClick: () => { m.close(); signOut(); } })));
  const m = ui.modal({ title: 'Your account', body });
}
async function signOut() {
  if (isSso()) { topNavigate('/admin'); return; }
  try { await api.logout(); } catch (e) { if (e && e.status !== 404) console.warn('[shell] logout', e && e.message); }
  setSession({ role: null, user: null });
  showLogin({ reason: 'You have signed out.' });
}

let whoPending = null;
/** Opens the "Who's using this?" modal. Resolves with the name, or null if cancelled. */
function whoModal({ reason } = {}) {
  if (whoPending) return whoPending;
  whoPending = new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (done) return; done = true; whoPending = null; resolve(v); };
    const body = h('div', null,
      h('p', { class: 'td-who__lead' }, reason || 'Your name is shown next to every change you make, so the team knows who updated what. No password or account needed.'));
    const f = ui.form({
      fields: [{ name: 'name', label: 'Your name', type: 'text', required: true, value: api.user || '', help: 'For example "Ravi K." — first name and initial is fine.' }],
      submitLabel: 'Continue',
      onSubmit: async (v) => {
        api.setUser(v.name);
        renderUser();
        ui.toast(`Welcome, ${api.user}`, 'good');
        finish(api.user);
        m.close();
      },
    });
    body.append(f);
    const m = ui.modal({ title: "Who's using this?", body, onClose: () => finish(api.user || null) });
  });
  return whoPending;
}

/** Resolves with the current user's name, prompting once if unknown. Rejects if the user cancels. */
async function ensureUser() {
  if (state.session.mode === 'session' && state.session.user) return state.session.user;
  if (api.user) return api.user;
  const name = await whoModal({ reason: 'Before saving, please tell us who you are. Your name is recorded next to every change.' });
  if (!name) { const e = new Error('Please enter your name before saving.'); e.status = 0; e.fields = {}; e.cancelled = true; throw e; }
  return name;
}

function askPasscode(msg) {
  return new Promise((resolve) => {
    let ok = false;
    const f = ui.form({
      fields: [{ name: 'passcode', label: 'Team passcode', type: 'password', required: true, help: 'Ask your admin for the portal passcode.' }],
      submitLabel: 'Unlock',
      onSubmit: async (v) => { api.setPasscode(v.passcode); ok = true; m.close(); },
    });
    const m = ui.modal({ title: 'Passcode needed', body: h('div', null, h('p', { class: 'td-muted', style: { marginTop: 0 } }, msg || 'Saving changes needs the team passcode.'), f), onClose: () => resolve(ok) });
  });
}

/* =========================================================================
   Session login (only when the server says a login is required: GET /api/session → {required:true, authenticated:false})
   ========================================================================= */
let loginPending = null;
/** Full-screen sign-in. Resolves once signed in (the session cookie is set by the server). */
function showLogin({ reason } = {}) {
  if (loginPending) return loginPending;
  if (isSso()) {
    // The LMS session ended. Leaving the page at once would throw away an open form, so ask first:
    // sign in again in a new tab (cookies are shared) and retry here, or leave for the LMS sign-in.
    const loginUrl = state.session.login_url || LMS_LOGIN_URL;
    loginPending = new Promise((resolve) => {
      const body = h('div', null,
        h('p', { style: { marginTop: 0 } }, reason || 'Your Tech Drona LMS session has ended. What you were doing is still on this page.'),
        h('p', { class: 'td-muted' }, 'Sign in again in a new tab, then come back and press "Retry". Or leave this page to sign in (unsaved changes are lost).'),
        h('div', { class: 'td-acct__actions' },
          ui.button({ label: 'Sign in (new tab)', icon: 'user', tone: 'secondary', onClick: () => { window.open(loginUrl, '_blank', 'noopener'); } }),
          ui.button({ label: 'Retry', onClick: () => { m.close(); } }),
          ui.button({ label: 'Leave and sign in', tone: 'secondary', onClick: () => { topNavigate(loginUrl); } })));
      // Closing (Retry, Esc, ×) retries the pending request once; a still-expired session asks again.
      const m = ui.modal({ title: 'Signed out of the LMS', body, onClose: () => { loginPending = null; resolve(); } });
    });
    return loginPending;
  }
  // F7: do NOT close open dialogs — the sign-in screen is drawn above them so typed input survives a session expiry.
  closeScopePop({ focus: false });
  const returnFocus = document.activeElement;
  loginPending = new Promise((resolve) => {
    const err = h('div', { class: 'td-login__err', role: 'alert', hidden: true });
    const nameIn = h('input', { id: 'td-login-name', class: 'td-input', type: 'text', autocomplete: 'username', required: true, maxlength: '60', value: api.user || '', 'aria-describedby': 'td-login-name-help td-login-name-err' });
    nameIn.value = api.user || '';
    const passIn = h('input', { id: 'td-login-pass', class: 'td-input', type: 'password', autocomplete: 'current-password', required: true, 'aria-describedby': 'td-login-pass-help td-login-pass-err' });
    const submit = ui.button({ label: 'Sign in', tone: 'primary', type: 'submit' });
    submit.classList.add('td-login__submit');
    const showErr = (msg) => { err.textContent = msg; err.hidden = !msg; };
    const nameErr = h('div', { id: 'td-login-name-err', class: 'td-field__error', 'aria-live': 'polite' });
    const passErr = h('div', { id: 'td-login-pass-err', class: 'td-field__error', 'aria-live': 'polite' });
    const fieldErr = (input, box, msg) => {
      box.textContent = msg || '';
      input.setAttribute('aria-invalid', msg ? 'true' : 'false');
      input.closest('.td-field').classList.toggle('has-error', !!msg);
    };
    const f = h('form', { class: 'td-login__form', novalidate: true },
      err,
      h('div', { class: 'td-field' }, h('label', { for: 'td-login-name', class: 'td-field__label' }, 'Your name'), nameIn,
        h('div', { id: 'td-login-name-help', class: 'td-field__help' }, 'Shown next to every change you make.'), nameErr),
      h('div', { class: 'td-field' }, h('label', { for: 'td-login-pass', class: 'td-field__label' }, 'Team passcode'), passIn,
        h('div', { id: 'td-login-pass-help', class: 'td-field__help' }, 'Ask your admin. A view-only passcode lets you look without editing.'), passErr),
      submit);
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = nameIn.value.trim();
      const pass = passIn.value;
      fieldErr(nameIn, nameErr, name ? '' : 'Enter your name.');
      fieldErr(passIn, passErr, pass ? '' : 'Enter the team passcode.');
      if (!name) { showErr('Please enter your name.'); nameIn.focus(); return; }
      if (!pass) { showErr('Please enter the team passcode.'); passIn.focus(); return; }
      showErr('');
      submit.disabled = true; submit.classList.add('is-busy');
      try {
        const r = (await api.login(name, pass)) || {};
        api.setUser(r.user || r.name || name);
        api.mode = 'session';
        setSession({ mode: 'session', required: true, role: r.role || 'editor', user: r.user || r.name || name });
        overlay.remove();
        if (!document.querySelector('.td-overlay')) document.documentElement.classList.remove('td-noscroll');
        loginPending = null;
        if (returnFocus && document.contains(returnFocus) && typeof returnFocus.focus === 'function') { try { returnFocus.focus(); } catch { /* ignore */ } }
        renderUser();
        resolve(true);
      } catch (ex) {
        passIn.value = '';
        if (ex && ex.status === 401) fieldErr(passIn, passErr, 'That passcode is not right.');
        showErr(ex && ex.status === 401 ? 'That passcode is not right. Check it and try again.'
          : ex && ex.status === 0 ? 'Cannot reach the server. Check your connection, then try again.' : (ex && ex.message) || 'Could not sign in.');
        passIn.focus();
      } finally { submit.disabled = false; submit.classList.remove('is-busy'); }
    });
    const overlay = h('div', { class: 'td-login', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'td-login-title' },
      h('div', { class: 'td-login__card' },
        h('span', { class: 'td-logo td-login__mark' },
          h('img', { class: 'td-logo-navy', src: 'assets/brand/mark-navy.svg', alt: '', width: 56, height: 56 }),
          h('img', { class: 'td-logo-white', src: 'assets/brand/mark-white.svg', alt: '', width: 56, height: 56 })),
        h('h1', { id: 'td-login-title', class: 'td-login__title' }, 'Sign in'),
        h('p', { class: 'td-login__sub' }, reason || 'Tech Drona Outreach Portal'),
        f));
    document.querySelector('.td-login')?.remove();
    document.body.append(overlay);
    document.documentElement.classList.add('td-noscroll');
    requestAnimationFrame(() => (nameIn.value ? passIn : nameIn).focus());
  });
  return loginPending;
}

/** Ask the server whether a login is needed; legacy servers (no /api/session) keep the typed-name flow. */
async function initSession() {
  let s = null;
  try { s = await api.session(); } catch (e) {
    console.warn('[shell] /api/session failed', e && e.message);
    if (e && e.status === 0) setOnline(false);
    return;
  }
  if (!s) { api.mode = 'legacy'; setSession({ mode: 'legacy', role: null, user: api.user || null, required: false }); return; }
  const required = !!(s.required ?? s.auth_required ?? s.login_required);
  const authed = !!(s.authenticated ?? (s.role && s.user));
  if (!required && !authed) { api.mode = 'legacy'; setSession({ mode: 'legacy', role: null, user: api.user || null, required: false }); return; }
  api.mode = 'session';
  if (authed) {
    if (s.user) api.setUser(s.user);
    setSession({ mode: 'session', required, role: s.role || 'editor', user: s.user || api.user, sso: !!s.sso, login_url: s.login_url || null });
    return;
  }
  setSession({ mode: 'session', required, role: null, user: null, sso: !!s.sso, login_url: s.login_url || null });
  await showLogin();
}

// Session expired mid-use (cookie gone / server restarted): the api wrappers (tracked/writeCall) show the sign-in screen
// above any open dialog and retry the pending request once (F7), so no global 401 hook is needed.
apiHooks.onUnauthorized = null;
addEventListener(SESSION_EVENT, () => { renderUser(); });

/* =========================================================================
   Banners (demo data / offline)
   ========================================================================= */
function renderBanners() {
  if (!$.banners) return;
  const items = [];
  if (!online) {
    items.push(h('div', { class: 'td-banner td-banner--offline', role: 'alert' },
      ui.icon('offline', { size: 18 }),
      h('span', null,
        h('span', { class: 'td-banner__full' }, h('strong', null, 'Can’t reach the server. '), 'You may be offline or the portal server is not running. What you see may be out of date, and changes won’t save until the connection is back.'),
        h('span', { class: 'td-banner__short' }, h('strong', null, 'Offline'), ' — changes won’t save until you’re back online.')),
      h('button', { type: 'button', class: 'td-banner__btn', onClick: retryConnection }, 'Retry')));
  }
  if (scopeRejected) {
    items.push(h('div', { class: 'td-banner td-banner--warn', role: 'alert' },
      ui.icon('warn', { size: 18 }),
      h('span', null, h('strong', null, 'District filter not applied. '), h('span', { class: 'td-banner__long' }, scopeRejected, ' '), 'Numbers on this page are not shown until the districts are chosen again.'),
      h('button', { type: 'button', class: 'td-banner__btn', onClick: () => { scopeRejected = null; resetDistrictScope(); renderBanners(); } }, 'Reset districts')));
  }
  if (state.session.role === 'viewer') {
    items.push(h('div', { class: 'td-banner td-banner--info', role: 'status' },
      ui.icon('info', { size: 18 }),
      h('span', null, h('strong', null, 'View-only access. '), h('span', { class: 'td-banner__long' }, 'You can browse everything; editing needs an editor passcode.'))));
  }
  if (state.meta && state.meta.demo) {
    items.push(h('div', { class: 'td-banner td-banner--demo', role: 'status' },
      ui.icon('warn', { size: 18 }),
      h('span', null, h('strong', null, 'Demo data present. '), 'Some records are test data, not real. ', h('span', { class: 'td-banner__long' }, 'Ask an admin to remove the demo records before these numbers are used.'))));
  }
  $.banners.replaceChildren(...items);
  $.root && $.root.classList.toggle('has-banner', items.length > 0);
  queueInvalidate();
}

async function retryConnection() {
  try { await raw.get('/meta'); setOnline(true); ui.toast('Connected again', 'good'); await loadMeta(); refresh(); } catch (e) {
    ui.toast(e && e.status === 0 ? 'Still can’t reach the server. Try again in a moment.' : (e && e.message) || 'Retry failed', 'warn');
  }
}
let metaRetry = null;
async function loadMeta() {
  clearTimeout(metaRetry);
  try {
    state.meta = await api.get('/meta');
    mapProxy.setPlaces({ districts: state.meta.districts || [], cities: state.meta.cities || [] });
    renderBanners();
    renderScopeControl();
    renderCrumbs();
  } catch (e) {
    if (e && e.status === 0) metaRetry = setTimeout(loadMeta, 15000);
    renderBanners();
  }
}
addEventListener('offline', () => setOnline(false));
addEventListener('online', () => { loadMeta(); });

/* =========================================================================
   Map (created once, lazily) + proxy for ctx.map
   ========================================================================= */
const MAP_METHODS = ['setColleges', 'setPlaces', 'setScope', 'getUnplacedCount', 'focusState', 'focusDistrict', 'focusCity', 'focusCollege', 'highlight', 'setShowClosed', 'getClosedCount', 'invalidateSize', 'destroy'];
let realMap = null;
let mapLoading = null;
let lastFocus = null;
let mapFailed = false;
const mapProxy = Object.fromEntries(MAP_METHODS.map((m) => [m, (...args) => {
  if (m.startsWith('focus')) lastFocus = [m, args];
  if (m === 'destroy') return undefined; // the shell owns the map's lifetime
  if (realMap && typeof realMap[m] === 'function') { try { return realMap[m](...args); } catch (e) { console.warn('[map]', m, e); } }
  return undefined;
}]));
mapProxy.ready = () => !!realMap;

function ensureMap() {
  if (realMap || mapLoading || mapFailed) return mapLoading;
  mapLoading = (async () => {
    try {
      const mod = await import('./map/map.js');
      if (typeof mod.createMap !== 'function') throw new Error('map.js does not export createMap');
      realMap = mod.createMap($.mapEl, {
        onSelectDistrict: (id) => navigate(`#/d/${encodeURIComponent(id)}`),
        onSelectCity: (districtId, cityId) => navigate(`#/d/${encodeURIComponent(districtId)}/${encodeURIComponent(cityId)}`),
        onSelectCollege: (id) => navigate(`#/college/${encodeURIComponent(id)}`),
        onReset: () => navigate('#/'),
      }) || null;
      if (!realMap) throw new Error('createMap returned nothing');
      $.mapWrap.classList.add('has-map');
      if (state.meta) mapProxy.setPlaces({ districts: state.meta.districts || [], cities: state.meta.cities || [] });
      pushMapScope();
      if (state.colleges) mapProxy.setColleges(state.colleges);
      renderUnplaced();
      if (lastFocus) mapProxy[lastFocus[0]](...lastFocus[1]);
      queueInvalidate();
    } catch (e) {
      mapFailed = true;
      console.warn('[shell] map unavailable:', e);
      $.mapEl.replaceChildren(h('div', { class: 'td-map-fallback' },
        h('div', { class: 'td-map-fallback__icon' }, ui.icon('map', { size: 26 })),
        h('div', { class: 'td-map-fallback__title' }, 'Map unavailable'),
        h('p', null, 'The map could not be loaded. Everything else works — use the list on the right.')));
    } finally { mapLoading = null; }
  })();
  return mapLoading;
}

/* Map as a card inside a page: ctx.mountMap(container) moves the one shared map into the view; the shell takes it back on every route. */
let mapHost = null;
async function mountMap(container) {
  if (!container || !(container instanceof Element)) return mapProxy;
  container.classList.add('td-maphost');
  container.append($.mapEl, $.unplaced);
  mapHost = container;
  await ensureMap();
  pushMapScope();
  if (state.colleges) mapProxy.setColleges(state.colleges);
  queueInvalidate();
  return mapProxy;
}
function reclaimMap() {
  if (!mapHost || !$.mapWrap) return;
  mapHost = null;
  $.mapWrap.prepend($.mapEl);
  $.mapWrap.append($.unplaced);
}

function renderUnplaced() {
  if (!$.unplaced) return;
  const n = Number(mapProxy.getUnplacedCount()) || 0;
  $.unplaced.hidden = !n;
  $.unplaced.replaceChildren(ui.icon('info', { size: 14 }), h('span', null, `${fmt.plural(n, 'college')} not on map (location pending)`));
}

let collegesToken = 0;
async function loadColleges() {
  const my = ++collegesToken;
  try {
    const rows = await api.getScoped('/colleges');
    if (my !== collegesToken) return;
    // scopeRows: client-side fallback when the server ignores `districts=`
    state.colleges = scopeRows(Array.isArray(rows) ? rows : (rows && rows.items) || []);
    mapProxy.setColleges(state.colleges);
    renderUnplaced();
  } catch (e) {
    if (my === collegesToken) console.warn('[shell] /api/colleges failed', e && e.message);
  }
}

let invT = null;
function queueInvalidate() {
  clearTimeout(invT);
  invT = setTimeout(() => mapProxy.invalidateSize(), 60);
  setTimeout(() => mapProxy.invalidateSize(), 360);
}
addEventListener('resize', debounce(() => { applyLayout(); queueInvalidate(); }, 120));

/* =========================================================================
   Layout + mobile bottom sheet
   ========================================================================= */
let routeLayout = 'full';
let sheetState = 'half';
function effectiveLayout() {
  if (routeLayout === 'explore-wide') return mqPhone.matches ? 'full' : 'explore';
  return routeLayout;
}
function applyLayout() {
  if (!$.root) return;
  const lay = effectiveLayout();
  const prev = $.root.dataset.layout;
  $.root.dataset.layout = lay;
  if (lay === 'explore') ensureMap();
  if (mqPhone.matches && lay === 'explore') setSheet(sheetState, false); else { $.panel.style.top = ''; $.panel.style.transition = ''; }
  renderMapToggle();
  if (prev !== lay) queueInvalidate();
}

function sheetPositions() {
  const H = $.stage.clientHeight;
  return { full: 8, half: Math.round(H * 0.48), peek: Math.max(H - 132, 0) };
}
function setSheet(s, animate = true) {
  sheetState = s;
  if (!(mqPhone.matches && effectiveLayout() === 'explore')) return;
  const pos = sheetPositions();
  $.panel.style.transition = animate ? '' : 'none';
  $.panel.style.top = `${pos[s]}px`;
  $.panel.dataset.sheet = s;
  renderMapToggle();
  if (!animate) requestAnimationFrame(() => { $.panel.style.transition = ''; });
}
function renderMapToggle() {
  const full = sheetState === 'full';
  $.mapToggle.replaceChildren(ui.icon(full ? 'map' : 'list', { size: 18 }), h('span', null, full ? 'Map' : 'List'));
  $.mapToggle.setAttribute('aria-label', full ? 'Show map' : 'Show list');
}
function toggleListMap() { setSheet(sheetState === 'full' ? 'peek' : 'full'); }

function initSheet() {
  let startY = 0; let startTop = 0; let dragging = false; let moved = false;
  const onDown = (e) => {
    if (!(mqPhone.matches && effectiveLayout() === 'explore')) return;
    if (e.target.closest('button,a,input,select')) return;
    dragging = true; moved = false;
    startY = e.clientY; startTop = $.panel.offsetTop;
    $.panel.style.transition = 'none';
    $.handle.setPointerCapture && e.pointerId !== undefined && e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onMove = (e) => {
    if (!dragging) return;
    const dy = e.clientY - startY;
    if (Math.abs(dy) > 4) moved = true;
    const pos = sheetPositions();
    $.panel.style.top = `${Math.min(Math.max(startTop + dy, pos.full), pos.peek)}px`;
  };
  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    $.panel.style.transition = '';
    const pos = sheetPositions();
    const top = $.panel.offsetTop;
    if (!moved) { setSheet(sheetState === 'full' ? 'half' : sheetState === 'half' ? 'full' : 'half'); return; }
    const best = Object.entries(pos).sort((a, b) => Math.abs(a[1] - top) - Math.abs(b[1] - top))[0][0];
    setSheet(best);
    queueInvalidate();
  };
  for (const el of [$.handle, $.panelHead]) {
    el.addEventListener('pointerdown', onDown);
    el.addEventListener('pointermove', onMove);
    el.addEventListener('pointerup', onUp);
    el.addEventListener('pointercancel', onUp);
  }
}

/* nav collapse / overlay */
let releaseNavBack = null;
function setNavOpen(on) {
  const was = $.root.classList.contains('nav-open');
  $.root.classList.toggle('nav-open', !!on);
  $.navToggle.setAttribute('aria-expanded', on ? 'true' : 'false');
  if (on && !was) releaseNavBack = ui.backClosable(() => { releaseNavBack = null; setNavOpen(false); });
  if (!on && releaseNavBack) { const r = releaseNavBack; releaseNavBack = null; r(); }
}
function toggleNav() {
  if (mqDesktop.matches) toggleCollapse();
  else setNavOpen(!$.root.classList.contains('nav-open'));
}
function toggleCollapse() {
  if (!mqDesktop.matches) { $.root.classList.remove('nav-open'); return; }
  const c = $.root.classList.toggle('nav-collapsed');
  writeLS('td.nav', c ? 'collapsed' : null);
  $.collapseBtn.setAttribute('aria-label', c ? 'Expand navigation' : 'Collapse navigation');
  queueInvalidate();
}

function openMoreSheet() {
  const item = (n) => h('a', { href: n.href, class: ['td-more__item', state.route && state.route.def && state.route.def.nav === n.id && 'is-active'], onClick: () => d.close() },
    h('span', { class: 'td-more__icon' }, ui.icon(n.icon, { size: 20 })), h('span', null, n.label), ui.icon('chevron', { size: 16 }));
  const sess = state.session;
  const who = sess.mode === 'session' ? `${sess.user || api.user || 'Signed in'}${sess.role ? ` · ${ROLE_LABEL[sess.role] || sess.role}` : ''}` : (api.user ? `You are ${api.user}` : "Who's using this?");
  const list = h('div', { class: 'td-more' },
    PRIMARY.slice(TAB_COUNT).map(item),
    h('div', { class: 'td-more__sep' }),
    SECONDARY.map(item),
    h('div', { class: 'td-more__sep' }),
    h('button', { type: 'button', class: 'td-more__item', onClick: () => { d.close(); userMenu(); } }, h('span', { class: 'td-more__icon' }, ui.icon('user', { size: 20 })), h('span', null, who), ui.icon('chevron', { size: 16 })),
    h('button', { type: 'button', class: 'td-more__item', onClick: () => { toggleTheme(); d.close(); } }, h('span', { class: 'td-more__icon' }, ui.icon(currentTheme() === 'dark' ? 'sun' : 'moon', { size: 20 })), h('span', null, currentTheme() === 'dark' ? 'Light theme' : 'Dark theme'), ui.icon('chevron', { size: 16 })),
    devMode() ? h('a', { href: '#/styleguide', class: 'td-more__item', onClick: () => d.close() }, h('span', { class: 'td-more__icon' }, ui.icon('palette', { size: 20 })), h('span', null, 'Style guide (developer)'), ui.icon('chevron', { size: 16 })) : null);
  const d = ui.drawer({ title: 'More', body: list });
}

/* =========================================================================
   Global search (combobox with grouped results)
   ========================================================================= */
const SEARCH_GROUPS = [
  ['district', 'Districts', 'map'], ['city', 'Cities & towns', 'map'], ['college', 'Colleges', 'college'],
  ['branch', 'Branches', 'branch'], ['person', 'People', 'people'],
];
function buildSearch() {
  const listId = 'td-search-list';
  const input = h('input', {
    type: 'search', class: 'td-search__input', placeholder: 'Search districts, colleges, branches, people…', autocomplete: 'off', spellcheck: 'false',
    role: 'combobox', 'aria-expanded': 'false', 'aria-controls': listId, 'aria-autocomplete': 'list', 'aria-label': 'Search the portal',
  });
  const list = h('div', { id: listId, class: 'td-search__results', role: 'listbox', hidden: true, 'aria-label': 'Search results' });
  const closeBtn = ui.button({ icon: 'close', tone: 'ghost', ariaLabel: 'Close search', onClick: () => closeMobileSearch() });
  closeBtn.classList.add('td-search__close');
  const root = h('div', { class: 'td-search' },
    h('div', { class: 'td-search__box' }, ui.icon('search', { size: 18, class: 'td-search__icon' }), input, h('kbd', { class: 'td-search__kbd', 'aria-hidden': 'true' }, '/'), closeBtn),
    list);
  let options = [];
  let active = -1;
  let token = 0;

  function open(v) { list.hidden = !v; input.setAttribute('aria-expanded', v ? 'true' : 'false'); root.classList.toggle('is-open', v); }
  function setActive(i) {
    active = i;
    options.forEach((o, j) => o.el.setAttribute('aria-selected', j === i ? 'true' : 'false'));
    if (i >= 0 && options[i]) { input.setAttribute('aria-activedescendant', options[i].el.id); options[i].el.scrollIntoView({ block: 'nearest' }); }
    else input.removeAttribute('aria-activedescendant');
  }
  function go(item) {
    let href = item.href || '';
    if (!href) {
      href = item.type === 'district' ? `#/d/${item.id}` : item.type === 'college' ? `#/college/${item.id}` : item.type === 'person' ? `#/person/${item.id}` : '#/';
    }
    open(false);
    input.value = '';
    input.blur();
    closeMobileSearch();
    navigate(href);
  }
  function renderResults(rows, q) {
    list.textContent = '';
    options = [];
    active = -1;
    if (!rows.length) {
      list.append(h('div', { class: 'td-search__empty' }, h('strong', null, `No matches for “${q}”`), h('span', null, 'Try a district, town, college short name (e.g. “KL”), branch code or a person’s name.')));
      open(true);
      return;
    }
    let n = 0;
    for (const [type, label, ic] of SEARCH_GROUPS) {
      const items = rows.filter((r) => r.type === type);
      if (!items.length) continue;
      const gid = `td-sg-${type}`;
      const group = h('div', { role: 'group', 'aria-labelledby': gid, class: 'td-search__group' }, h('div', { id: gid, class: 'td-search__ghead' }, label));
      for (const it of items) {
        const el = h('div', { id: `td-so-${n++}`, role: 'option', class: 'td-search__opt', 'aria-selected': 'false' },
          h('span', { class: 'td-search__oicon' }, ui.icon(ic, { size: 16 })),
          h('span', { class: 'td-search__otext' }, h('span', { class: 'td-search__olabel' }, it.label || it.id), it.sub ? h('span', { class: 'td-search__osub' }, it.sub) : null));
        el.addEventListener('mousedown', (e) => e.preventDefault());
        el.addEventListener('click', () => go(it));
        options.push({ el, item: it });
        group.append(el);
      }
      list.append(group);
    }
    // anything with an unknown type
    const other = rows.filter((r) => !SEARCH_GROUPS.some(([t]) => t === r.type));
    if (other.length) {
      const group = h('div', { role: 'group', class: 'td-search__group' }, h('div', { class: 'td-search__ghead' }, 'Other'));
      other.forEach((it) => {
        const el = h('div', { id: `td-so-${n++}`, role: 'option', class: 'td-search__opt', 'aria-selected': 'false' }, h('span', { class: 'td-search__otext' }, h('span', { class: 'td-search__olabel' }, it.label)));
        el.addEventListener('click', () => go(it));
        options.push({ el, item: it });
        group.append(el);
      });
      list.append(group);
    }
    open(true);
    setActive(0);
  }
  const run = debounce(async () => {
    const q = input.value.trim();
    const my = ++token;
    if (q.length < 2) { open(false); return; }
    list.replaceChildren(h('div', { class: 'td-search__empty td-search__loading' }, ui.icon('search', { size: 16 }), 'Searching…'));
    open(true);
    try {
      const rows = await api.get('/search', { q });
      if (my !== token) return;
      renderResults(Array.isArray(rows) ? rows : [], q);
    } catch (e) {
      if (my !== token) return;
      list.replaceChildren(h('div', { class: 'td-search__empty' }, e && e.status === 0 ? 'Server unreachable — search is unavailable.' : 'Search failed. Please try again.'));
      open(true);
    }
  }, 200);
  input.addEventListener('input', run);
  input.addEventListener('focus', () => { if (input.value.trim().length >= 2 && list.childNodes.length) open(true); });
  input.addEventListener('blur', () => setTimeout(() => open(false), 120));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (list.hidden) run(); else setActive(Math.min(active + 1, options.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(Math.max(active - 1, 0)); }
    else if (e.key === 'Enter') { if (options[active]) { e.preventDefault(); go(options[active].item); } }
    else if (e.key === 'Escape') { if (!list.hidden) { e.preventDefault(); open(false); } else { input.value = ''; input.blur(); closeMobileSearch(); } }
  });
  return { root, input, close: () => { token++; open(false); } };
}
let releaseSearchBack = null;
function openMobileSearch() {
  if (!$.root.classList.contains('search-open')) releaseSearchBack = ui.backClosable(() => { releaseSearchBack = null; closeMobileSearch(); });
  $.root.classList.add('search-open');
  setTimeout(() => $.search.input.focus(), 30);
}
function closeMobileSearch() {
  if (!$.root || !$.root.classList.contains('search-open')) return;
  $.root.classList.remove('search-open');
  if (releaseSearchBack) { const r = releaseSearchBack; releaseSearchBack = null; r(); }
  if ($.searchBtn && document.activeElement === document.body) $.searchBtn.focus();
}

document.addEventListener('keydown', (e) => {
  if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target;
  if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
  if (document.querySelector('.td-overlay')) return;
  e.preventDefault();
  if ($.root.classList.contains('search-compact')) openMobileSearch(); else $.search.input.focus();
});

/* =========================================================================
   District scope (header control + popover / phone bottom sheet)
   ========================================================================= */
async function loadProgram() {
  try {
    state.program = await raw.get('/program');
    state.programAvailable = true;
  } catch (e) {
    // 404 = server without the program endpoint yet: fall back to the built-in target groups (state.js)
    if (e && e.status === 404) state.programAvailable = false;
    else console.warn('[shell] /api/program unavailable', e && e.message);
  }
  renderScopeControl();
  pushMapScope();
}

function pushMapScope() {
  const s = getScope();
  mapProxy.setScope({ all: s.all, ids: s.ids, target: targetDistrictIds(), groups: targetGroups() });
}

/** Per-district rows for the picker: {id, name, colleges, group} (program first, then /api/meta). */
function scopeDistricts() {
  const p = state.program && Array.isArray(state.program.districts) ? state.program.districts : null;
  const m = state.meta && Array.isArray(state.meta.districts) ? state.meta.districts : [];
  const base = p && p.length ? p : m;
  return base.map((d) => {
    const md = m.find((x) => x.id === d.id) || {};
    const colleges = Number.isFinite(d.colleges_total) ? d.colleges_total : Number.isFinite(md.colleges) ? md.colleges : Number.isFinite(d.colleges) ? d.colleges : null;
    return { id: d.id, name: d.name || md.name || d.id, colleges, group: targetGroupOf(d.id) };
  });
}

function buildScopeControl() {
  const btn = h('button', { type: 'button', class: 'td-scope__btn', 'aria-haspopup': 'dialog', 'aria-expanded': 'false', onClick: () => openScopePicker() });
  const root = h('div', { class: 'td-scope' }, btn);
  return { root, btn };
}

function renderScopeControl() {
  if (!$.scope) return;
  const s = getScope();
  const label = scopeLabel({ max: 3 });
  const n = s.all ? null : s.ids.length;
  // short label (tablet / phone top bar): a count, never the bare word "Target" (read as the enrollment target — owner review)
  const short = s.all ? 'All districts' : `${n} district${n === 1 ? '' : 's'}`;
  $.scope.btn.classList.toggle('is-custom', !s.isDefault);
  $.scope.btn.replaceChildren(
    ui.icon('map', { size: 16, class: 'td-scope__icon' }),
    h('span', { class: 'td-scope__k' }, 'Districts:'),
    h('span', { class: 'td-scope__v' }, label),
    h('span', { class: 'td-scope__short' }, short),
    ...(s.isDefault ? [] : [h('span', { class: 'td-scope__chip' }, s.all ? 'All' : 'Custom')]),
    ui.icon('chevron', { size: 14, class: 'td-scope__caret' }));
  $.scope.btn.setAttribute('aria-label', `Districts shown: ${label}${s.isDefault ? ' (default target districts)' : ''}. Change districts`);
  $.scope.btn.title = `Districts shown on every page: ${label}${s.isDefault ? ' (the target districts)' : ''}. Click to change.`;
}

/** Picker body shared by the desktop popover and the phone bottom sheet. close() closes the container. */
function scopePickerBody(close) {
  const cur = getScope();
  const all = scopeDistricts();
  const byId = new Map(all.map((d) => [d.id, d]));
  const groups = Object.entries(targetGroups());
  const targetIds = targetDistrictIds();
  let sel = new Set(cur.all ? all.map((d) => d.id) : cur.ids);
  let allMode = cur.all;
  const boxes = new Map(); // id -> checkbox
  const groupBoxes = []; // [checkbox, ids]
  const summary = h('p', { class: 'td-scope__sum', 'aria-live': 'polite' });
  const applyBtn = ui.button({ label: 'Apply', tone: 'primary', onClick: () => apply() });
  const presetT = h('button', { type: 'button', class: 'td-scope__preset', onClick: () => { allMode = false; sel = new Set(targetIds); sync(); } },
    h('strong', null, 'Target districts (default)'), h('span', null, 'Guntur · Krishna · West Godavari'));
  const presetA = h('button', { type: 'button', class: 'td-scope__preset', onClick: () => { allMode = true; sel = new Set(all.map((d) => d.id)); sync(); } },
    h('strong', null, 'All districts'), h('span', null, 'Every district in Andhra Pradesh'));
  const cnt = (d) => (d && d.colleges !== null && d.colleges !== undefined ? fmt.plural(d.colleges, 'college') : '—');

  const box = (d, { sub = false } = {}) => {
    const id = `td-scope-${d.id}`;
    const input = h('input', { type: 'checkbox', id, value: d.id, onChange: (e) => { allMode = false; if (e.target.checked) sel.add(d.id); else sel.delete(d.id); sync(); } });
    boxes.set(d.id, input);
    return h('li', { class: ['td-scope__item', sub && 'is-sub', d.colleges === 0 && 'is-empty'] },
      h('label', { for: id }, input, h('span', { class: 'td-scope__name' }, d.name), h('span', { class: 'td-scope__cnt td-num' }, cnt(d))));
  };
  const groupBlock = ([gname, ids]) => {
    const id = `td-scope-g-${gname.replace(/\W+/g, '-').toLowerCase()}`;
    const total = ids.reduce((a, x) => a + (byId.get(x)?.colleges || 0), 0);
    const input = h('input', { type: 'checkbox', id, onChange: (e) => { allMode = false; ids.forEach((x) => (e.target.checked ? sel.add(x) : sel.delete(x))); sync(); } });
    groupBoxes.push([input, ids]);
    return h('li', { class: 'td-scope__group' },
      h('label', { for: id, class: 'td-scope__gl' }, input,
        h('span', { class: 'td-scope__name' }, h('strong', null, gname), h('span', { class: 'td-scope__tag' }, 'Target')),
        h('span', { class: 'td-scope__cnt td-num' }, fmt.plural(total, 'college'))),
      h('ul', { class: 'td-scope__sub' }, ids.map((x) => box(byId.get(x) || { id: x, name: x, colleges: null }, { sub: true }))));
  };
  const others = all.filter((d) => !d.group).sort((a, b) => (b.colleges || 0) - (a.colleges || 0) || String(a.name).localeCompare(String(b.name)));
  const withCols = others.filter((d) => d.colleges !== 0);
  const noCols = others.filter((d) => d.colleges === 0);

  function sync() {
    for (const [id, input] of boxes) input.checked = sel.has(id);
    for (const [input, ids] of groupBoxes) {
      const n = ids.filter((x) => sel.has(x)).length;
      input.checked = n === ids.length; input.indeterminate = n > 0 && n < ids.length;
    }
    const isT = !allMode && sel.size === targetIds.length && targetIds.every((x) => sel.has(x));
    presetT.setAttribute('aria-pressed', String(isT)); presetA.setAttribute('aria-pressed', String(allMode));
    const nCol = [...sel].reduce((a, x) => a + (byId.get(x)?.colleges || 0), 0);
    summary.textContent = allMode ? `All districts · ${fmt.plural(all.reduce((a, d) => a + (d.colleges || 0), 0), 'college')}`
      : sel.size ? `${fmt.plural(sel.size, 'district')} · ${fmt.plural(nCol, 'college')}` : 'Select at least one district';
    applyBtn.disabled = !allMode && !sel.size;
  }
  function apply() {
    if (!allMode && !sel.size) return;
    const everything = allMode || all.every((d) => sel.has(d.id));
    close();
    setDistrictScope(everything ? 'all' : [...sel]);
  }
  const body = h('div', { class: 'td-scope__body' },
    h('div', { class: 'td-scope__presets', role: 'group', 'aria-label': 'Quick choices' }, presetT, presetA),
    h('div', { class: 'td-scope__sec' },
      h('h3', { class: 'td-scope__h' }, 'Target districts'),
      h('p', { class: 'td-scope__note' }, 'Grouped by the old undivided districts (includes districts formed in 2022: Palnadu, Bapatla, NTR, Eluru).'),
      h('ul', { class: 'td-scope__list' }, groups.map(groupBlock))),
    withCols.length ? h('div', { class: 'td-scope__sec' }, h('h3', { class: 'td-scope__h' }, 'Other districts'), h('ul', { class: 'td-scope__list' }, withCols.map((d) => box(d)))) : null,
    noCols.length ? h('details', { class: 'td-scope__sec td-scope__more' }, h('summary', null, `${fmt.plural(noCols.length, 'district')} with no colleges listed`), h('ul', { class: 'td-scope__list' }, noCols.map((d) => box(d)))) : null);
  const foot = h('div', { class: 'td-scope__foot' }, summary,
    h('div', { class: 'td-scope__btns' },
      ui.button({ label: 'Reset', tone: 'ghost', onClick: () => { close(); resetDistrictScope(); } }),
      applyBtn));
  sync();
  return { body, foot, first: presetT };
}

let scopePop = null;
function closeScopePop({ focus = true } = {}) {
  if (!scopePop) return;
  const p = scopePop; scopePop = null;
  p.el.remove();
  document.removeEventListener('mousedown', p.outside, true);
  document.removeEventListener('keydown', p.key, true);
  $.scope.btn.setAttribute('aria-expanded', 'false');
  if (focus) $.scope.btn.focus();
}
function openScopePicker() {
  if (scopePop) { closeScopePop(); return; }
  if (!state.meta && !state.program) { ui.toast('The district list is still loading. Try again in a moment.', 'info'); return; }
  if (mqPhone.matches) {
    let d = null;
    const { body, foot } = scopePickerBody(() => d && d.close());
    d = ui.drawer({ title: 'Districts shown', body: h('div', { class: 'td-scope__sheet' }, h('p', { class: 'td-scope__lead' }, 'Every page shows only these districts.'), body, foot) });
    return;
  }
  const { body, foot, first } = scopePickerBody(() => closeScopePop());
  const el = h('div', { class: 'td-scope__pop', role: 'dialog', 'aria-label': 'Choose districts' },
    h('div', { class: 'td-scope__head' }, h('h2', null, 'Districts shown'), h('p', null, 'Every page shows only these districts.')),
    body, foot);
  const outside = (e) => { if (!$.scope.root.contains(e.target)) closeScopePop({ focus: false }); };
  const key = (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeScopePop(); } };
  scopePop = { el, outside, key };
  $.scope.root.append(el);
  $.scope.btn.setAttribute('aria-expanded', 'true');
  document.addEventListener('mousedown', outside, true);
  document.addEventListener('keydown', key, true);
  requestAnimationFrame(() => first.focus());
}

/** `?d=all|target|id,id` in the hash query sets the scope (deep links). Unknown ids are dropped. */
function applyScopeQuery(v) {
  const val = String(v || '').trim();
  if (!val) return;
  let next;
  if (val === 'all' || val === 'target' || val === 'default') next = val;
  else {
    const known = new Set(scopeDistricts().map((d) => d.id));
    next = val.split(',').map((x) => x.trim()).filter((x) => x && (!known.size || known.has(x)));
    if (!next.length) return;
  }
  if (setDistrictScope(next, { silent: true })) onScopeChanged({ rerender: false });
}
/** Keep `?d=` in the address in step when it is present (no re-route). */
function syncScopeQuery() {
  const m = location.hash.match(/^([^?]*)\?(.*)$/);
  if (!m) return;
  const q = new URLSearchParams(m[2]);
  if (!q.has('d')) return;
  q.set('d', scopeQueryValue());
  try { history.replaceState(history.state, '', `${m[1]}?${q.toString().replace(/%2C/g, ',')}`); } catch { /* ignore */ }
}
function onScopeChanged({ rerender = true } = {}) {
  renderScopeControl();
  pushMapScope();
  syncScopeQuery();
  loadColleges();
  if (!rerender) return;
  const r = state.route;
  if (currentMod && currentMod.handlesScope) return; // the view listens to 'td:district-scope' itself
  // The scope applies to EVERY page now (UI-13): re-render whatever is showing.
  if (r && r.def && !r.def.builtin) route({ keepScroll: true });
}
addEventListener('td:open-scope', (e) => openScopePicker(e.detail && e.detail.anchor));
addEventListener(SCOPE_EVENT, () => { if (scopeRejected) { scopeRejected = null; renderBanners(); } onScopeChanged(); announce(`Showing ${scopeLabel()}`); });

/* =========================================================================
   Breadcrumb
   ========================================================================= */
const ROOT_CRUMB = { label: 'Home', href: '#/' };
function districtName(id) { const d = state.meta && (state.meta.districts || []).find((x) => x.id === id); return d ? d.name : prettySlug(id); }
function cityName(id) { const c = state.meta && (state.meta.cities || []).find((x) => x.id === id); return c ? c.name : prettySlug(String(id).split('--').pop()); }
function prettySlug(s) { return String(s || '').replace(/[-_]+/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase()); }

function defaultCrumbs() {
  const r = state.route;
  if (!r) return [ROOT_CRUMB];
  const p = r.params || {};
  if (r.def === ROUTES[0]) return [ROOT_CRUMB];
  if (p.district && !p.city) return [ROOT_CRUMB, { label: districtName(p.district) }];
  if (p.district && p.city) return [ROOT_CRUMB, { label: districtName(p.district), href: `#/d/${p.district}` }, { label: cityName(p.city) }];
  return [ROOT_CRUMB, { label: r.def.title }];
}
function setBreadcrumb(items) {
  let list = Array.isArray(items) ? items.filter(Boolean) : null;
  if (list && list.length) {
    const f = list[0];
    if (!(f.href === '#/' || /andhra|^home$/i.test(f.label || ''))) list = [ROOT_CRUMB, ...list];
  }
  breadcrumbItems = list && list.length ? list : null;
  renderCrumbs();
}
function renderCrumbs() {
  if (!$.crumbs) return;
  const items = breadcrumbItems || defaultCrumbs();
  const ol = h('ol', null, items.map((it, i) => {
    const last = i === items.length - 1;
    return h('li', null,
      i > 0 ? ui.icon('chevron', { size: 14, class: 'td-crumbs__sep' }) : null,
      !last && it.href ? h('a', { href: it.href }, it.label) : h('span', { 'aria-current': last ? 'page' : undefined }, it.label));
  }));
  // phones: one "‹ parent" link instead of the trail — only below the top-level pages (the tab bar covers those)
  const parent = [...items.slice(0, -1)].reverse().find((it) => it && it.href);
  const deep = !!(state.route && state.route.params && (state.route.params.id || state.route.params.district));
  const up = parent && deep ? h('a', { href: parent.href, class: 'td-crumbs__up' }, ui.icon('chevron-left', { size: 18 }), h('span', null, parent.label)) : null;
  $.crumbs.replaceChildren(...[up, ol].filter(Boolean));
  $.crumbs.classList.toggle('is-single', items.length < 2);
  // the shell shows a way back (breadcrumb, or the phone up-link) → views' own "‹ Back" links are hidden (D22)
  $.root && $.root.classList.toggle('has-crumbs', ui.formFactor() === 'phone' ? !!up : items.length >= 2);
  const r = state.route;
  const here = items.length > 1 ? items[items.length - 1].label : (r ? r.def.title : 'Home');
  document.title = `${here} · Tech Drona Outreach Portal`;
  if ($.pageTitle) $.pageTitle.textContent = r && r.def && r.def.title ? (r.def === ROUTES[0] ? 'Home' : here) : '';
  if (pendingAnnounce) { pendingAnnounce = false; announce(`${here} page`); }
}

/* =========================================================================
   Router
   ========================================================================= */
function parseHash() {
  let hs = location.hash.replace(/^#/, '') || '/';
  if (!hs.startsWith('/')) hs = '/' + hs;
  const [path, qstr] = hs.split('?');
  const query = Object.fromEntries(new URLSearchParams(qstr || ''));
  return { path: path.replace(/\/+$/, '') || '/', query };
}
function matchRoute(path) {
  for (const def of ROUTES) {
    const m = path.match(def.re);
    if (m) {
      const params = {};
      def.keys.forEach((k, i) => { params[k] = decodeURIComponent(m[i + 1]); });
      return { def, params };
    }
  }
  return null;
}

export function navigate(href) {
  if (!href) return;
  let target = String(href);
  if (target.startsWith('/')) target = '#' + target;
  if (!target.startsWith('#')) { location.href = target; return; }
  if (location.hash === target) route({ keepScroll: false });
  else location.hash = target;
}

let currentMod = null;
let currentDestroy = null;
let routeToken = 0;

function callDestroy() {
  const fn = currentDestroy;
  currentDestroy = null;
  currentMod = null;
  if (typeof fn === 'function') { try { fn(); } catch (e) { console.warn('[shell] destroy() failed', e); } }
}

function setActiveNav(navId) {
  const all = [...($.navLinks || []), ...($.tabLinks || []), $.nav && $.nav.querySelector('[data-nav="styleguide"]')].filter(Boolean);
  all.forEach((a) => { const on = a.dataset.nav === navId; a.classList.toggle('is-active', on); if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  const onTab = PRIMARY.slice(0, TAB_COUNT).some((n) => n.id === navId);
  const inMore = !!navId && !onTab;
  if ($.moreBtn) { $.moreBtn.classList.toggle('is-active', inMore); if (inMore) $.moreBtn.setAttribute('aria-current', 'page'); else $.moreBtn.removeAttribute('aria-current'); }
}

/** Sub-section tabs (Targets › Performance | Planner, Calls › Call queue | Follow-ups) rendered by the shell. */
function renderSectionTabs(section) {
  if (!$.sectionTabs) return;
  const defs = section && SECTIONS[section];
  $.sectionTabs.hidden = !defs;
  if (!defs) { $.sectionTabs.replaceChildren(); return; }
  const { path, query } = parseHash();
  const items = defs.map((d) => (d.is ? { label: d.label, href: d.href, active: !!d.is(path, query) } : d));
  $.sectionTabs.replaceChildren(ui.linkTabs(items));
}

function defaultMapFocus(def, params) {
  if (params.district && params.city) mapProxy.focusCity(params.district, params.city);
  else if (params.district) mapProxy.focusDistrict(params.district);
  else if (def.mod === 'college' && params.id) { mapProxy.focusCollege(params.id); mapProxy.highlight(params.id); return; }
  else if (def === ROUTES[0]) mapProxy.focusState();
  mapProxy.highlight(null);
}

function viewSkeleton() {
  return h('div', { class: 'td-viewskel', 'aria-hidden': 'true' },
    h('div', { class: 'td-skel td-skel--title', style: { width: '45%', height: '28px' } }),
    h('div', { class: 'td-viewskel__row' }, [0, 1, 2].map(() => h('div', { class: 'td-viewskel__card' }, h('div', { class: 'td-skel', style: { width: '50%' } }), h('div', { class: 'td-skel', style: { width: '70%', height: '22px' } })))),
    ui.skeleton(4));
}

function showViewError(el, { title, text, error, retry }) {
  el.replaceChildren(h('div', { class: 'td-view-error' }, ui.errorCard({ title, text, error, retry })));
}

/* --- scroll memory per history entry (back/forward restores where you were) --- */
const scrollMemo = new Map();
let entrySeq = 0;
function entryKey() {
  const st = history.state;
  if (st && st.tdKey) return st.tdKey;
  const key = `e${Date.now().toString(36)}${++entrySeq}`;
  try { history.replaceState({ ...(st || {}), tdKey: key }, '', location.href); } catch { /* ignore */ }
  return key;
}
let currentKey = null;
function rememberScroll() { const sc = scrollEl(); if (currentKey && sc) scrollMemo.set(currentKey, sc.scrollTop); }

let pendingAnnounce = false;
function announce(msg) {
  const el = document.getElementById('td-announce');
  if (!el) return;
  el.textContent = '';
  setTimeout(() => { el.textContent = msg; }, 50);
}
/** After an in-app navigation, move focus to the new content so keyboard and screen-reader users land there. */
function focusView() {
  const a = document.activeElement;
  const top = document.querySelector('.td-topbar');
  const fromChrome = !a || a === document.body || ($.nav && $.nav.contains(a)) || ($.tabbar && $.tabbar.contains(a)) || ($.crumbs && $.crumbs.contains(a)) || ($.search && $.search.root.contains(a)) || (top && top.contains(a)) || ($.sectionTabs && $.sectionTabs.contains(a));
  if (!fromChrome || document.querySelector('.td-overlay')) return;
  const target = $.view.querySelector('h1') || $.view;
  if (target !== $.view && !target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
  try { target.focus({ preventScroll: true }); } catch { /* ignore */ }
}

let lastRoutePath = null;
let firstRoute = true;
async function route({ keepScroll = false } = {}) {
  const my = ++routeToken;
  let { path, query } = parseHash();
  if (ALIASES[path] !== undefined) {
    const qs = location.hash.includes('?') ? location.hash.slice(location.hash.indexOf('?')) : '';
    try { history.replaceState(history.state, '', `#${ALIASES[path]}${qs}`); } catch { /* ignore */ }
    path = ALIASES[path];
  }
  rememberScroll(); // the previous page is still on screen when hashchange fires
  const key = entryKey();
  const restoreTo = !keepScroll && key !== currentKey && scrollMemo.has(key) ? scrollMemo.get(key) : null;
  currentKey = key;
  pendingAnnounce = !firstRoute && path !== lastRoutePath;
  const hit = matchRoute(path);
  if (query.d) applyScopeQuery(query.d);
  callDestroy();
  reclaimMap();
  closeMobileSearch();
  if ($.search) $.search.close();
  closeScopePop({ focus: false }); // UI-17: the district picker never stays open over the next page
  if (path !== lastRoutePath) ui.closeOverlays(); // e.g. a person link inside the branch drawer
  lastRoutePath = path;
  setNavOpen(false);

  if (!hit) {
    state.route = { path, params: {}, def: { title: 'Page not found', layout: 'full' } };
    routeLayout = 'full';
    applyLayout();
    breadcrumbItems = null;
    renderCrumbs();
    setActiveNav(null);
    renderSectionTabs(null);
    $.root.dataset.route = 'notfound';
    $.view.replaceChildren(h('div', { class: 'td-view-error td-notfound' }, h('div', { class: 'td-card' }, ui.emptyState({
      title: 'Page not found', icon: 'warn',
      text: h('span', null, 'The link ', h('code', null, `#${path}`), ' does not match any page. It may be mistyped or the record may have moved.'),
      action: h('div', { class: 'td-empty__actions' },
        ui.button({ label: 'Go to Home', tone: 'primary', icon: 'home', onClick: () => navigate('#/') }),
        ui.button({ label: 'Browse colleges', icon: 'college', onClick: () => navigate('#/colleges') })),
    }))));
    firstRoute = false;
    focusView();
    return;
  }

  const { def } = hit;
  if (def.dev && !devMode()) {
    state.route = { path, params: {}, def: { title: 'Developer page', layout: 'full' } };
    routeLayout = 'full'; applyLayout(); breadcrumbItems = null; renderCrumbs(); setActiveNav(null); renderSectionTabs(null);
    $.view.replaceChildren(h('div', { class: 'td-view-error td-notfound' }, h('div', { class: 'td-card' }, ui.emptyState({
      title: 'Developer page', icon: 'palette',
      text: h('span', null, 'The style guide is for developers. Open ', h('code', null, '#/styleguide?dev=1'), ' to see it.'),
      action: { label: 'Go to Home', icon: 'home', onClick: () => navigate('#/') },
    }))));
    firstRoute = false;
    return;
  }
  const params = { ...query, ...hit.params };
  state.route = { path, params, def, name: def.exp || 'builtin' };
  routeLayout = def.layout;
  breadcrumbItems = null;
  applyLayout();
  setActiveNav(def.nav === null ? 'styleguide' : def.nav);
  renderCrumbs();
  renderSectionTabs(def.section || null);
  $.root.dataset.route = def.mod || 'styleguide';
  if (effectiveLayout() === 'explore') defaultMapFocus(def, params);

  const scroller = scrollEl();
  const prevScroll = keepScroll && scroller ? scroller.scrollTop : 0;

  // fresh container per render; skeleton sits beside it until the view paints
  const el = h('div', { class: 'td-view-root' });
  const skel = viewSkeleton();
  $.view.replaceChildren(skel, el);
  const dropSkel = () => { if (skel.isConnected) skel.remove(); };
  const mo = new MutationObserver(() => { if (el.childNodes.length) { dropSkel(); mo.disconnect(); } });
  mo.observe(el, { childList: true });
  if (!keepScroll && scroller) scroller.scrollTop = 0;

  try {
    let fn;
    if (def.builtin) fn = def.builtin;
    else {
      let mod;
      try { mod = await VIEW_MODULES[def.mod](); } catch (e) {
        if (my !== routeToken) return;
        mo.disconnect();
        console.warn(`[shell] could not load views/${def.mod}.js`, e);
        showViewError($.view, {
          title: `${def.title} isn't ready yet`,
          text: `This section (views/${def.mod}.js) is still being built or failed to load. The rest of the portal keeps working.`,
          error: e, retry: () => route(),
        });
        return;
      }
      if (my !== routeToken) return;
      fn = mod[def.exp];
      // views may export render() or a default function / object (the planner view)
      if (typeof fn !== 'function' && typeof mod.default === 'function') fn = mod.default;
      if (typeof fn !== 'function' && mod.default && typeof mod.default[def.exp] === 'function') fn = mod.default[def.exp].bind(mod.default);
      currentMod = mod;
      currentDestroy = typeof mod.destroy === 'function' ? mod.destroy.bind(mod) : null;
      // a view may opt into a layout: `export const layout = 'explore'` or `export const layouts = {renderDistrict: 'explore'}`
      const want = (mod.layouts && mod.layouts[def.exp]) || (typeof mod.layout === 'string' ? mod.layout : null);
      if (want && want !== routeLayout && ['full', 'explore', 'explore-wide'].includes(want)) {
        routeLayout = want; applyLayout();
        if (effectiveLayout() === 'explore') defaultMapFocus(def, params);
      }
      if (typeof fn !== 'function') {
        mo.disconnect();
        showViewError($.view, {
          title: `${def.title} isn't ready yet`,
          text: `views/${def.mod}.js does not provide ${def.exp}() yet.`, retry: () => route(),
        });
        return;
      }
    }
    await fn(el, params, ctx);
    if (my !== routeToken) return;
    dropSkel();
    mo.disconnect();
    if (keepScroll && scroller) scroller.scrollTop = prevScroll;
    else if (restoreTo !== null && scroller) requestAnimationFrame(() => { scroller.scrollTop = restoreTo; });
    if (!firstRoute) focusView();
    firstRoute = false;
  } catch (e) {
    if (my !== routeToken) return;
    mo.disconnect();
    if (e && e.status === 0) lastFailedRoute = true;
    console.error(`[shell] ${def.mod || 'view'}.${def.exp || 'render'} failed`, e);
    showViewError($.view, {
      title: e && e.status === 404 ? 'Not found' : `${def.title} could not be shown`,
      text: e && e.status === 404 ? 'This record does not exist or was removed.' : undefined,
      error: e, retry: () => route(),
    });
  }
}
function scrollEl() {
  if (!$.panel) return null;
  return getComputedStyle($.panel).overflowY === 'auto' ? $.panel : ($.stage && getComputedStyle($.stage).overflowY === 'auto' ? $.stage : document.scrollingElement);
}

/** Re-render the current route (keeping scroll) and reload map data. */
async function refresh() {
  loadColleges();
  await route({ keepScroll: true });
}

/* =========================================================================
   ctx — passed to every view
   ========================================================================= */
const ctx = {
  api, ui, h, fmt, state,
  navigate,
  map: mapProxy,
  refresh,
  setBreadcrumb,
  ensureUser,
  get params() { return state.route ? state.route.params : {}; },
  /** mobile helper: ask the shell to open the bottom sheet ('peek'|'half'|'full') */
  setSheet: (s) => setSheet(s),
  /** open the global district picker (header control); views use it for inline "Change" links */
  openDistrictScope: (anchor) => openScopePicker(anchor),
  /** move the shared map into a container in your view (give it a height, e.g. class td-mapcard) → the map proxy */
  mountMap: (container) => mountMap(container),
  /** re-draw the shell's section tabs after a view changed the URL itself (setHashQuery) */
  refreshSectionTabs: () => renderSectionTabs(state.route && state.route.def ? state.route.def.section || null : null),
  /** 'phone' | 'tablet' | 'desktop' — same as <html data-form> */
  get form() { return ui.formFactor(); },
  /** current district scope {all, ids, isDefault} */
  get scope() { return getScope(); },
  /** {mode:'legacy'|'session', role, user, required} */
  get session() { return state.session; },
  /** false for read-only (viewer) sessions — hide write controls (or wrap them with ui.writeOnly) */
  get canWrite() { return canWrite(); },
};
export { ctx };

/* =========================================================================
   Boot
   ========================================================================= */
async function boot() {
  await initSession();
  buildShell();
  renderBanners();
  if (!location.hash) history.replaceState(null, '', '#/');
  addEventListener('hashchange', () => route());
  // remember scroll continuously (hashchange fires after the URL already changed)
  const saveScroll = debounce(rememberScroll, 80);
  $.panel.addEventListener('scroll', saveScroll, { passive: true });
  $.stage.addEventListener('scroll', saveScroll, { passive: true });
  document.addEventListener('scroll', saveScroll, { passive: true });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && $.root.classList.contains('nav-open') && !document.querySelector('.td-overlay')) { setNavOpen(false); $.navToggle.focus(); }
  });
  // form factor changed (rotate / resize across 700 or 1280): re-lay the chrome; views re-fit via CSS / dataTable
  addEventListener(ui.FORMFACTOR_EVENT, () => { setNavOpen(false); applyLayout(); renderCrumbs(); queueInvalidate(); });
  addEventListener('resize', debounce(syncCompactBar, 80));
  syncCompactBar();
  // skip link: move focus to the page content without touching the hash router (D1)
  const skip = document.querySelector('.td-skip');
  if (skip) skip.addEventListener('click', (e) => { e.preventDefault(); try { $.view.focus({ preventScroll: false }); } catch { $.view.focus(); } });
  loadMeta();
  loadProgram();
  loadColleges();
  // live official-source data: one background refresh per visit (after sign-in); no status chip in the top bar
  import('./views/live.js').then((m) => { m.startLive(api); }).catch((e) => console.warn('[shell] live status unavailable', e));
  route();
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();

/* =========================================================================
   Style guide (#/styleguide) — every component, in both themes, for QA.
   Values shown here are visual specimens only; they are not portal data.
   ========================================================================= */
function renderStyleguide(el) {
  ctx.setBreadcrumb([{ label: 'Style guide' }]);
  const intro = h('div', { class: 'td-sg-intro' },
    h('div', null,
      h('h1', null, 'Style guide'),
      h('p', { class: 'td-muted' }, 'Every shared component in light and dark themes. Numbers and names below are visual specimens for QA, not portal data. Signatures: top of js/ui/components.js.')),
    h('div', { class: 'td-sg-intro__actions' },
      ui.button({ label: 'Open modal', icon: 'plus', onClick: () => sgModal() }),
      ui.button({ label: 'Open drawer', icon: 'list', onClick: () => ui.drawer({ title: 'Branch details', body: h('div', null, ui.kv([['Branch', 'CSE'], ['Intake', ui.valueWithBasis({ value: 180, basis: 'verified' })], ['Final year', ui.valueWithBasis({ value: 180, basis: 'estimated' })], ['Eligible', ui.valueWithBasis({ value: null, basis: 'pending' })]])) }) }),
      ui.button({ label: 'Toasts', icon: 'sparkle', onClick: () => { ui.toast('Saved', 'good'); ui.toast('Exams start in 5 days', 'warn'); ui.toast('Could not save — server unreachable', 'bad'); ui.toast('Filters applied', 'info'); } }),
      ui.button({ label: 'Confirm', icon: 'trash', tone: 'danger', onClick: async () => { const ok = await ui.confirm({ title: 'Deactivate this lead?', text: 'Their 3 ambassadors will become unassigned.', body: h('ul', null, h('li', null, 'Specimen A'), h('li', null, 'Specimen B')), confirmLabel: 'Deactivate', danger: true }); ui.toast(ok ? 'Confirmed' : 'Cancelled', ok ? 'good' : 'neutral'); } }),
      ui.button({ label: 'Form dialog', icon: 'target', onClick: () => sgFormDialog() })));
  const panes = h('div', { class: 'td-sg-panes' },
    h('div', { class: 'td-sg-pane', 'data-theme': 'light' }, h('div', { class: 'td-sg-pane__tag' }, 'Light'), sgGallery()),
    h('div', { class: 'td-sg-pane', 'data-theme': 'dark' }, h('div', { class: 'td-sg-pane__tag' }, 'Dark'), sgGallery()));
  el.append(h('div', { class: 'td-sg' }, intro, panes));
}

function sgFilterBar() {
  return ui.filterBar({
    search: { key: 'q', placeholder: 'Search name or phone' },
    filters: [
      { key: 'role', label: 'Role', options: [['college_lead', 'College lead'], ['ambassador_lead', 'Ambassador lead'], ['ambassador', 'Ambassador']] },
      { key: 'status', label: 'Status', options: [['active', 'Active'], ['inactive', 'Inactive']] },
      { key: 'mine', label: 'Only unassigned', type: 'toggle' },
    ],
    onChange: (v, k) => ui.toast(`Filter ${k || 'all'} → ${JSON.stringify(v)}`, 'info'),
    actions: [ui.button({ label: 'Export', icon: 'external', size: 'sm' })],
  });
}
function sgDataTable() {
  const rows = Array.from({ length: 23 }, (_, i) => ({
    id: i + 1, name: `Specimen person ${String.fromCharCode(65 + (i % 26))}${i + 1}`, college: ['Specimen College', 'Sample Institute', 'Example College'][i % 3],
    role: i % 7 === 0 ? 'college_lead' : 'ambassador', assignment: ['assigned', 'unassigned', 'invalid_link'][i % 3 === 0 ? 0 : i % 5 === 0 ? 2 : i % 2],
    actual: (i * 7) % 23, target: i % 4 === 0 ? null : 10 + (i % 5) * 5, phone: i % 6 === 0 ? null : `98765 4${String(1000 + i).slice(1)}`,
  }));
  return ui.dataTable({
    caption: 'Specimen people',
    columns: [
      { key: 'name', label: 'Name', primary: true },
      { key: 'college', label: 'College' },
      { key: 'role', label: 'Role', render: (r) => (r.role === 'college_lead' ? 'College lead' : 'Ambassador') },
      { key: 'assignment', label: 'Lead', render: (r) => ui.statusChip(r.assignment, { size: 'sm' }) },
      { key: 'actual', label: 'Target vs actual', sortValue: (r) => (r.target ? r.actual / r.target : -1), render: (r) => ui.progressBar(r.actual, r.target, { size: 'sm' }) },
      { key: 'phone', label: 'Contact', sortable: false, hideOnPhone: false, render: (r) => ui.contactActions(r.phone, null, { compact: true }) },
    ],
    rows, pageSize: 8, pageLabel: 'people', selectable: true, onSelect: (sel) => ui.toast(`${sel.length} selected`, 'info'),
    rowActions: (r) => [{ label: 'Edit', icon: 'edit', onClick: () => ui.toast(`Edit ${r.name}`, 'info'), writeOnly: true }, { label: 'Move', icon: 'arrow', onClick: () => {} }, { label: 'Deactivate', icon: 'trash', tone: 'danger', onClick: () => {} }],
    onRowClick: (r) => ui.toast(`Open ${r.name}`, 'info'),
  });
}

async function sgFormDialog() {
  const r = await ui.formDialog({
    title: 'Set target', intro: 'Specimen dialog: min and max are optional; the target is required.',
    fields: [
      { name: 'period', label: 'Period', type: 'select', required: true, options: [{ value: 'programme', label: 'Whole programme' }, { value: 'month', label: 'Month' }], value: 'programme' },
      { name: 'target', label: 'Target', type: 'number', required: true, min: 0 },
      { name: 'min', label: 'Minimum', type: 'number', min: 0 },
      { name: 'max', label: 'Maximum', type: 'number', min: 0 },
    ],
    submitLabel: 'Save target',
    onSubmit: async (v, { idempotencyKey }) => {
      await new Promise((res) => setTimeout(res, 500));
      if (v.max !== null && v.max < v.target) { const e = new Error('Please fix the highlighted field'); e.status = 400; e.fields = { max: 'Maximum must be at least the target' }; throw e; }
      return { ...v, idempotencyKey };
    },
  });
  ui.toast(r ? `Saved (specimen, key ${String(r.idempotencyKey).slice(0, 8)}…)` : 'Cancelled', r ? 'good' : 'neutral');
}

function sgModal() {
  const m = ui.modal({
    title: 'Add a person',
    body: ui.form({
      fields: [
        { name: 'full_name', label: 'Full name', type: 'text', required: true },
        { name: 'role', label: 'Role', type: 'select', required: true, options: [{ value: 'college_lead', label: 'College lead' }, { value: 'ambassador_lead', label: 'Ambassador lead' }, { value: 'ambassador', label: 'Ambassador' }] },
        { name: 'phone', label: 'Phone', type: 'tel' },
        { name: 'email', label: 'Email', type: 'email' },
        { name: 'joined_on', label: 'Joined on', type: 'date' },
        { name: 'target', label: 'Target', type: 'number', help: 'Enrolments expected by the deadline.' },
        { name: 'branch_ids', label: 'Branches covered', type: 'multiselect', options: ['CSE', 'CSM', 'CSD', 'AID', 'CAI', 'CSC', 'IT', 'ECE', 'EEE'].map((c, i) => ({ value: i + 1, label: c })) },
        { name: 'notes', label: 'Notes', type: 'textarea' },
      ],
      submitLabel: 'Save person',
      onCancel: () => m.close(),
      onSubmit: async () => {
        await new Promise((r) => setTimeout(r, 700));
        const err = new Error('Please fix the highlighted fields'); err.status = 400; err.fields = { phone: 'Phone must have 10 digits' }; throw err;
      },
    }),
  });
}

function sgGallery() {
  const swatches = ['brand', 'brand-2', 'link', 'brand-solid', 'brand-soft', 'accent', 'accent-ink', 'bg', 'surface', 'surface-2', 'surface-3', 'text', 'text-2', 'muted', 'border', 'border-strong', 'good', 'warn', 'bad', 'info', 'neutral', 'verified', 'estimated', 'pending'];
  const s = (title, ...body) => h('div', { class: 'td-sg-block' }, h('div', { class: 'td-sg-block__title' }, title), ...body);
  const row = (...c) => h('div', { class: 'td-sg-row' }, ...c);
  const specimenRows = [
    { name: 'Specimen College of Engineering', district: 'District A', strength: { value: 2880, basis: 'verified' }, target: 120, enrolled: 84, on_track: true, exam: 'clear' },
    { name: 'Sample Institute of Technology', district: 'District B', strength: { value: 1440, basis: 'estimated' }, target: 60, enrolled: 12, on_track: false, exam: 'in_exams' },
    { name: 'Example Engineering College', district: 'District C', strength: { value: null, basis: 'pending' }, target: null, enrolled: 0, on_track: null, exam: 'unknown' },
  ];
  return h('div', { class: 'td-sg-gallery' },
    s('Brand', h('div', { class: 'td-sg-brand' },
      brandLogo('mark', { class: 'td-sg-brand__mark' }),
      brandLogo('wordmark-tagline', { class: 'td-sg-brand__word' }),
      h('img', { src: 'assets/favicon.svg', alt: 'Favicon', width: 32, height: 32 }))),
    s('Page header (scope pill, meta, link tabs)', ui.pageHeader({ eyebrow: 'Team', title: 'Team', sub: 'College leads and ambassadors, who they report to and how they are doing.', scope: true,
      meta: [ui.statusChip('unassigned'), ui.badge('Specimen', 'neutral')],
      actions: [{ label: 'Add person', icon: 'plus', tone: 'primary', writeOnly: true }],
      tabs: [{ label: 'All', href: '#/styleguide', active: true, count: 12 }, { label: 'College leads', href: '#/styleguide?x=1', active: false, count: 3 }, { label: 'Unassigned', href: '#/styleguide?x=2', active: false, count: 2 }] })),
    s('KPI tiles (ui.kpi / ui.kpiRow)', ui.kpiRow([
      ui.kpi({ label: 'Confirmed', value: 120, sub: 'of 400 target', icon: 'target', tone: 'brand' }),
      ui.kpi({ label: 'Remaining', value: 280, sub: 'by 31 Dec 2026', icon: 'clock', tone: 'warn', help: 'Target minus confirmed (never below 0).' }),
      ui.kpi({ label: 'Colleges with no lead', value: 14, icon: 'college', tone: 'bad', href: '#/styleguide' }),
      ui.kpi({ label: 'Unknown value', value: null, basis: 'pending', icon: 'data' }),
      ui.kpi({ label: 'Loading', loading: true }),
    ])),
    s('Progress bar (ui.progressBar actual, target, {min, max})', h('div', { class: 'td-sg-stack' },
      ui.progressBar(12, 40, { label: 'Specimen A', status: 'behind' }),
      ui.progressBar(30, 40, { min: 20, max: 60, status: 'on_track', unit: 'enrolled' }),
      ui.progressBar(46, 40, { label: 'Specimen C' }),
      ui.progressBar(5, 0, { label: 'Zero target' }),
      ui.progressBar(3, null, { label: 'No target', size: 'sm' }))),
    s('Status chips (ui.statusChip)',
      row(...['no_target', 'zero_target', 'too_early', 'behind', 'on_track', 'met', 'exceeded'].map((v) => ui.statusChip(v))),
      row(...['assigned', 'unassigned', 'invalid_link', 'active', 'onboarding', 'inactive', 'open', 'overdue', 'done'].map((v) => ui.statusChip(v)))),
    s('Verification + contact actions',
      row(ui.verifiedBadge({ state: 'verified', date: '2026-11-03', source: 'https://example.edu.in/contact', by: 'Specimen' }), ui.verifiedBadge({ state: 'unverified' }), ui.verifiedBadge({ state: 'missing' })),
      row(ui.contactActions('98765 43210', 'person@example.com', { whatsapp: true, name: 'Specimen' }), ui.contactActions(null, null, { compact: true }))),
    s('Filter bar + segmented', sgFilterBar(), ui.segmented({ ariaLabel: 'Role', options: [{ value: 'all', label: 'All', count: 12 }, { value: 'lead', label: 'College leads', count: 3 }, { value: 'amb', label: 'Ambassadors', count: 9 }], value: 'all', onChange: (v) => ui.toast(`Segment: ${v}`, 'info') })),
    s('Data table (ui.dataTable: sort, paging, row actions, selection; cards on phones)', sgDataTable()),
    s('Data table states', h('div', { class: 'td-sg-stack', style: { maxWidth: 'none' } },
      ui.dataTable({ columns: [{ key: 'a', label: 'Name' }, { key: 'b', label: 'College' }, { key: 'c', label: 'Status' }], rows: [], loading: true, pageSize: 4 }),
      ui.dataTable({ columns: [{ key: 'a', label: 'Name' }, { key: 'b', label: 'College' }], rows: [], empty: { title: 'No ambassadors yet', text: 'Add the first ambassador for this college.', action: { label: 'Add ambassador', onClick: () => {} } } }),
      ui.dataTable({ columns: [{ key: 'a', label: 'Name' }], rows: [], error: Object.assign(new Error('Cannot reach the server.'), { status: 0 }), onRetry: () => ui.toast('Retry', 'info') }))),
    s('Pagination + overflow menu', row(ui.pagination({ page: 2, pageSize: 50, total: 312, label: 'people', onPage: (n) => ui.toast(`Page ${n}`, 'info') }),
      ui.menu({ items: [{ label: 'Edit', icon: 'edit', onClick: () => ui.toast('Edit', 'info') }, { label: 'Move to college', icon: 'arrow', onClick: () => {} }, { label: 'Deactivate', icon: 'trash', tone: 'danger', onClick: () => {} }] }))),
    s('Page header (simple)', ui.pageHeader({ eyebrow: 'Operations', title: 'Follow-ups', sub: 'Calls and visits you promised, sorted by due date.', actions: [{ label: 'Add follow-up', icon: 'plus', tone: 'primary' }] })),
    s('Chips + spinner', row(ui.chip({ label: 'All', active: true, onClick: () => {} }), ui.chip({ label: 'Overdue', tone: 'bad', onClick: () => {} }), ui.chip({ label: 'District: Guntur', onRemove: () => {} }), ui.spinner({ label: 'Loading colleges…' }))),
    s('Colour tokens', h('div', { class: 'td-sg-swatches' }, swatches.map((n) => h('div', { class: 'td-sg-swatch' }, h('span', { style: { background: `var(--td-${n})` } }), h('code', null, `--td-${n}`))))),
    s('Type', h('div', { class: 'td-sg-type' },
      h('div', { class: 'td-sg-display' }, 'Outreach that hits the mark'),
      h('h2', null, 'Section heading'), h('h3', null, 'Card heading'),
      h('p', null, 'Body text in Inter. Numbers use tabular figures: ', h('span', { class: 'td-num' }, fmt.num(1234567)), ' · ', h('span', { class: 'td-num' }, fmt.inr(45000))),
      h('p', { class: 'td-muted' }, 'Muted helper text for secondary information.'))),
    s('Buttons', row(
      ui.button({ label: 'Primary', tone: 'primary', icon: 'plus' }), ui.button({ label: 'Secondary' }), ui.button({ label: 'Accent', tone: 'accent' }),
      ui.button({ label: 'Ghost', tone: 'ghost' }), ui.button({ label: 'Delete', tone: 'danger', icon: 'trash' }), ui.button({ icon: 'edit', ariaLabel: 'Edit' }),
      ui.button({ label: 'Small', size: 'sm' }), ui.button({ label: 'Disabled', disabled: true }))),
    s('Provenance', row(ui.provenance('verified'), ui.provenance('estimated'), ui.provenance('pending')),
      row(ui.valueWithBasis({ value: 2880, basis: 'verified' }), ui.valueWithBasis({ value: 1440, basis: 'estimated' }), ui.valueWithBasis({ value: null, basis: 'pending' }))),
    s('Badges', row(...['neutral', 'good', 'warn', 'bad', 'info', 'brand'].map((t) => ui.badge(t[0].toUpperCase() + t.slice(1), t)))),
    s('Status badges',
      row(...['in_exams', 'exams_soon', 'clear', 'unknown'].map((v) => ui.statusBadge('exam_state', v))),
      row(...['operational', 'possibly_closed', 'closed', 'pending'].map((v) => ui.statusBadge('op_status', v))),
      row(...['on_track', 'behind', 'no_target'].map((v) => ui.statusBadge('on_track', v)), ...['open', 'overdue', 'done'].map((v) => ui.statusBadge('followup', v))),
      row(...['active', 'onboarding', 'inactive'].map((v) => ui.statusBadge('person_status', v))),
      row(...['ambassador_gap', 'low_outreach', 'low_conversion', 'unrealistic_target', 'behind_pace'].map((v) => ui.statusBadge('diagnosis', v)))),
    s('Progress', h('div', { class: 'td-sg-stack' },
      ui.progress({ target: 120, done: 96, size: 'lg' }), ui.progress({ target: 120, done: 48 }), ui.progress({ target: 120, done: 12, size: 'sm' }), ui.progress({ target: null, done: 3 }))),
    s('Stat cards', h('div', { class: 'td-sg-stats' },
      ui.statCard({ label: 'Colleges', value: fmt.num(170), sub: '142 operational', icon: 'college' }),
      ui.statCard({ label: 'Final-year students', value: fmt.num(41250), basis: 'estimated', icon: 'people', tone: 'brand' }),
      ui.statCard({ label: 'Enrolled', value: fmt.num(312), sub: 'of 1,200 target', icon: 'target', tone: 'good', onClick: () => {} }),
      ui.statCard({ label: 'Overdue follow-ups', value: fmt.num(7), icon: 'followup', tone: 'bad', onClick: () => {} }),
      ui.statCard({ label: 'Eligible students', value: null, basis: 'pending', icon: 'data' }))),
    s('Table (sortable, cards when narrow)', ui.table({
      columns: [
        { key: 'name', label: 'College' },
        { key: 'district', label: 'District' },
        { key: 'strength', label: 'Strength', align: 'right' },
        { key: 'enrolled', label: 'Progress', render: (r) => ui.progress({ target: r.target, done: r.enrolled, size: 'sm' }) },
        { key: 'on_track', label: 'Pace', render: (r) => ui.statusBadge('on_track', r.on_track) },
        { key: 'exam', label: 'Exams', render: (r) => ui.statusBadge('exam_state', r.exam) },
      ],
      rows: specimenRows,
      onRowClick: (r) => ui.toast(`Row: ${r.name}`, 'info'),
    }), h('div', { style: { height: '12px' } }), ui.table({ columns: [{ key: 'a', label: 'Name' }, { key: 'b', label: 'Value' }], rows: [], empty: 'No people added yet' })),
    s('Tabs', ui.tabs({
      tabs: [
        { id: 'overview', label: 'Overview', render: () => h('p', { class: 'td-muted' }, 'Overview tab content.') },
        { id: 'branches', label: 'Branches', count: 9, render: () => h('p', { class: 'td-muted' }, 'Branches tab content.') },
        { id: 'team', label: 'Team', count: 0, render: () => ui.emptyState({ title: 'No team yet', text: 'Add a college lead to get started.', action: { label: 'Add person', onClick: () => {} } }) },
      ],
      active: 'overview',
    })),
    s('Section + key/values', ui.section({
      title: 'College details', sub: 'Last updated 2 days ago',
      actions: [{ label: 'Edit', icon: 'edit' }],
      body: ui.kv([['Website', h('a', { href: '#/styleguide' }, 'example.edu.in')], ['Phone', null], ['Affiliation', 'JNTU Kakinada'], ['Intake', ui.valueWithBasis({ value: 720, basis: 'verified' })]]),
    })),
    s('Empty state', h('div', { class: 'td-card' }, ui.emptyState({ title: 'No follow-ups yet', text: 'Follow-ups you create for colleges, branches or people appear here.', action: { label: 'Add follow-up', onClick: () => {} } }))),
    s('Error card', ui.errorCard({ title: 'Analytics is not ready yet', error: new Error('Failed to fetch dynamically imported module'), retry: () => {} })),
    s('Form', h('div', { class: 'td-card', style: { padding: '20px' } }, ui.form({
      fields: [
        { name: 'name', label: 'Name', type: 'text', required: true },
        { name: 'status', label: 'Status', type: 'select', options: ['active', 'onboarding', 'inactive'], value: 'active' },
        { name: 'due', label: 'Due date', type: 'date' },
        { name: 'count', label: 'Students reached', type: 'number', help: 'Approximate is fine.' },
      ],
      submitLabel: 'Save',
      onSubmit: async () => { await new Promise((r) => setTimeout(r, 600)); ui.toast('Saved (specimen)', 'good'); },
    }))),
    s('Icons', h('div', { class: 'td-sg-icons' }, ui.iconNames.map((n) => h('div', { class: 'td-sg-icon', title: n }, ui.icon(n, { size: 22 }), h('span', null, n))))),
  );
}
