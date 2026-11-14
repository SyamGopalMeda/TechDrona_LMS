# Outreach Portal in React — porting guide

The College Data ("Outreach") Portal is being rewritten as React routes inside the LMS SPA
(`apps/lms-spa`). The **foundation** is done (shell, data layer, state, shared UI, map, charts, a placeholder
per route). Screen agents now port the old views (`apps/college-data/portal/public/js/views/*.js`) one route
at a time onto it. Nothing is wired to production yet: the LMS Modules menu, the hub and `/admin/college-data`
still open the old portal (`/college-portal/index.html`). The cut-over is a later step.

## Architecture

```
browser ── /colleges/**  (Firebase Hosting, SPA index.html, hashed + CDN-cached JS/CSS chunks)
   │         src/app/colleges/**  → layout (gate + shell) → one lazy chunk per screen
   └── fetch /college-portal/api/*  ── Hosting rewrite ──▶ lmsApi (functions-lms/lms_edge/college_portal.py:
                                         LMS session → admin check → x-td-proxy-* headers)
                                         ──▶ Cloud Run college-portal (apps/college-data/portal/server/server.js, unchanged)
```

- UI: `apps/lms-spa/src/app/colleges/**` (routes, generated into `src/spa/routes.gen.tsx` by
  `node scripts/gen-routes.mjs`) and `apps/lms-spa/src/features/colleges/**` (everything else).
- Data: the portal server's REST API exactly as before (`apps/college-data/portal/CONTRACT.md`).
- Admin only: `CollegesGate` = LMS session + Admin portal grant (same rule as the proxy and the hub's
  `can_open_colleges`). The proxy re-checks every API call and fails closed.

## Folder structure

```
src/app/colleges/
  layout.tsx            Suspense(PortalBoot) > CollegesGate > PortalLayout
  loading.tsx           ViewSkeleton inside the shell (screen chunk loading / suspending)
  error.tsx             ErrorCard inside the shell (a screen threw; 404 / admins-only wording)
  page.tsx              Home                       …one folder per route (see route map)
  [...rest]/page.tsx    old alias paths → redirect; anything else → "Page not found"
src/features/colleges/
  lib/   api.ts (client) · cache.ts (usePortalQuery) · types.ts · scope.ts · session.ts · query.ts
         routes.ts (paths, NAV, SECTIONS, route map, legacy links) · prefs.ts (theme, device) · fmt.ts
  shell/ PortalLayout.tsx · Chrome.tsx (brand, sidebar, tab bar, More sheet, crumbs, banners, account)
         ScopePicker.tsx · GlobalSearch.tsx · modules.ts · page-context.tsx (usePortalPage)
         CollegesGate.tsx · PortalBoot.tsx · Placeholder.tsx · brand/*.svg
  ui/    index.ts (import from here) + one file per component family
  map/   CollegeMap.tsx (React wrapper) · engine.ts (map.js port) · ap_districts.geojson
  charts/Charts.tsx · index.ts
  styles/tokens.css base.css components.css shell.css map.css charts.css + views/*.css
docs/colleges-react/scope-css.mjs   regenerates styles/*.css from the old portal CSS
```

## Styling (keep the old look)

- The old CSS is reused **unchanged in meaning**: `styles/*.css` are generated from
  `apps/college-data/portal/public/css/*.css` with every selector scoped under `.tdp` (the portal root).
  `:root/html/body` became `.tdp`; `[data-theme]` became `[data-tdp-theme]`; `:root[data-form="phone"]`
  became `.tdp[data-form="phone"]`. The LMS styles are unaffected and the LMS `<html data-theme>` is never touched.
- So **write the old class names** (`td-card`, `td-btn td-btn--primary`, `td-kpi-row`, `td-section`, …) — do
  not use the LMS Tailwind classes or LMS `components/ui` inside the portal (their tokens collide on purpose
  with nothing, but they will not look like the portal).
- Shell CSS (tokens, base, components, shell) loads with the layout. **Each screen imports its own view CSS**:
  `import "@/features/colleges/styles/views/dashboard.css";` (admin, calls, college, dashboard, live, ops, plan,
  targets). It is code-split with the screen. Chart CSS (`charts.css`) comes with `charts/`, map CSS with the map.
- Device attributes on `.tdp`: `data-form="phone|tablet|desktop"` (phone < 700 px or landscape phone, desktop ≥
  1280), `data-pointer`, `data-short`; theme `data-tdp-theme`. In JS use `usePortalUi().form` / `useDevice()`.
- Regenerate after changing an old CSS file: `node docs/colleges-react/scope-css.mjs <in.css> <out.css>`.
  (components.css has one hand fix: `.tdp.td-noscroll{overflow:hidden}`.) New styles: add them to the
  matching `styles/views/*.css`, scoped with `.tdp ` yourself.

## Route map (old hash route → new path)

Rule: `#/<x>` → `/colleges/<x>`; query strings unchanged. Build links with `portalPath` from `lib/routes.ts`,
and pass API hrefs (`'#/college/c9'`, search hits, attention items) through `toPortalHref()`.

| Old route | New path | Old view (js/views) | Nav | Title |
|---|---|---|---|---|
| `#/` | `/colleges` | `dashboard.js renderState` | home | Home |
| `#/colleges` | `/colleges/colleges` | `dashboard.js renderCollegeList` | colleges | Colleges |
| `#/college/:id` | `/colleges/college/:id` | `college.js render` (+ `college-form.js`, `branch.js`, `forms.js`) | colleges | College |
| `#/d/:district` | `/colleges/d/:district` | `geo.js renderDistrict` | colleges | District |
| `#/d/:district/:city` | `/colleges/d/:district/:city` | `geo.js renderCity` | colleges | Town |
| `#/people` | `/colleges/people` | `people.js renderList` | people | Team |
| `#/person/:id` | `/colleges/person/:id` | `people.js renderPerson` | people | Person |
| `#/targets` (`?tab=places`) | `/colleges/targets` | `targets.js render` | targets | Targets & performance |
| `#/plan` | `/colleges/plan` | `plan.js render` (+ `plan/model.js`) | targets | Target planner |
| `#/calls` | `/colleges/calls` | `calls.js render` | calls | Calls & follow-ups |
| `#/followups` | `/colleges/followups` | `followups.js render` | calls | Follow-ups |
| `#/analytics` | `/colleges/analytics` | `dashboard.js renderAnalytics` | analytics | Reports |
| `#/exams` | `/colleges/exams` | `exams.js render` | exams | Exams |
| `#/notices` | `/colleges/notices` | `live.js renderNotices` | notices | Official notices |
| `#/live` | `/colleges/live` | `live.js renderSources` | live | Official sources |
| `#/data` | `/colleges/data` | `admin.js renderData` | data | Data quality |
| `#/audit` | `/colleges/audit` | `admin.js renderAudit` | audit | Audit log |
| `#/settings` | `/colleges/settings` | `admin.js renderSettings` | settings | Settings |

Aliases (`/colleges/team`, `/reports`, `/planner`, `/performance`, `/calling`, `/follow-ups`, `/sources`,
`/official`, `/announcements`, `/quality`, `/data-quality`, `/verification`, `/log`, `/home`, `/overview`,
`/map`…) redirect via `[...rest]`. `/colleges#/college/c9` (old-style link) is converted by the shell.
The style guide (`#/styleguide`) was not ported. Section tabs (Targets › Performance | Targets by place |
Planner; Calls › Call queue | Follow-ups) are drawn by the shell from `SECTIONS` — screens must not repeat them.

Suggested split for the three screen agents (by shared code): **A** Home, Colleges list, Reports, District,
Town (dashboard.js + geo.js, map + charts heavy); **B** College, Team, Person (college.js, college-form.js,
branch.js, people.js, forms.js); **C** Targets, Planner, Calls, Follow-ups, Exams, Notices, Sources, Data
quality, Audit, Settings (targets.js, plan.js, calls.js, followups.js, exams.js, live.js, admin.js).
`forms.js` dialogs (addContact, editContact, logCall, editEnrollment…) are shared: whoever ports them first
puts them in `src/features/colleges/forms/` and the others reuse them.

## How to port a screen

```tsx
// src/app/colleges/colleges/page.tsx
import type { Metadata } from "next";
import { CollegeList } from "@/features/colleges/screens/CollegeList";
export const metadata: Metadata = { title: { absolute: "Colleges · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };
export default function Page() { return <CollegeList />; }
```

Put the screen in `src/features/colleges/screens/<Name>.tsx` (plus `screens/<name>/…` helpers). Keep the page
file thin. Keep the `metadata` block (the shell also sets `document.title` from the breadcrumb).

```tsx
import "@/features/colleges/styles/views/dashboard.css";
import { usePortalQuery } from "@/features/colleges/lib/cache";
import { useQueryState } from "@/features/colleges/lib/query";
import { portalPath } from "@/features/colleges/lib/routes";
import { usePortalPage } from "@/features/colleges/shell/page-context";
import { DataTable, FilterBar, ListEmpty, PageHeader, StatusChip, hasFilters } from "@/features/colleges/ui";
import type { CollegeRow } from "@/features/colleges/lib/types";

export function CollegeList() {
  const [q, setQuery] = useQueryState();
  const { data, error, loading, reload } = usePortalQuery<CollegeRow[]>("colleges", { scoped: true, query: { q: q.q, op_status: q.op_status }, keepPrevious: true });
  usePortalPage({ crumbs: [{ label: "Colleges" }] });
  return (
    <>
      <PageHeader title="Colleges" scope />
      <FilterBar values={q} onChange={(v) => setQuery({ ...v, page: null }, { history: "auto" })} search={{ placeholder: "Search colleges" }} filters={[…]} />
      <DataTable rows={data} loading={loading} error={error} onRetry={reload} columns={[…]} rowHref={(r) => portalPath.college(r.id)}
        empty={<ListEmpty noun="colleges" filtered={hasFilters(q, ["d"])} onClear={() => setQuery({ q: null, op_status: null })} />} />
    </>
  );
}
```

Old `render(el, params, ctx)` → React mapping:

| Old (`ctx` / `ui`) | New |
|---|---|
| `ctx.api.get(path, params)` | `usePortalQuery<T>(path, { query })` in components; `portalApi.get` / `fetchCached` outside render |
| `ctx.api.getScoped(path, params)` | `usePortalQuery(path, { scoped: true, query })` (re-runs when the scope changes) |
| `ctx.api.post/patch/put/del` | `portalApi.post/patch/put/del(path, body, { idempotencyKey })` — clears the cache; mounted queries refetch |
| `ctx.refresh()` | `reload()` from `usePortalQuery`, or `invalidatePortalCache()` |
| `ctx.navigate('#/x')` / `href: '#/x'` | `useNavigate()` + `portalPath.*`; `<Link to={portalPath.x}>`; `toPortalHref(apiHref)` |
| `ctx.params` (hash params + query) | `useParams()` (route params) + `useQueryState()` (query) |
| `ui.getHashQuery()` / `setHashQuery(o, {replace})` | `const [q, setQuery] = useQueryState(); setQuery(patch, { history: "replace" \| "push" \| "auto" })` |
| `ctx.setBreadcrumb([...])` | `usePortalPage({ title, crumbs: [{ label, to }] })` ("Home" is prepended) |
| `ctx.scope`, `'td:district-scope'` event | `useDistrictScope()`, `useScopeLabel()`; `scopeRows(rows)` for client fallback |
| `ctx.openDistrictScope()` | `<ScopePill />` (or `window.dispatchEvent(new CustomEvent("td:open-scope"))`) |
| `ctx.canWrite`, `ui.writeOnly(node)` | `usePortalUi().canWrite`, `<WriteOnly>…</WriteOnly>`, `writeOnly: true` on row actions / menu items |
| `ctx.session` | `usePortalSession()` → `{ user, role, canWrite }` |
| `ctx.form` / `ui.isPhone()` | `usePortalUi().form === "phone"` |
| `ctx.mountMap(container)` | `<CollegeMap … style={{ height }} />` |
| `ctx.state.meta` | `usePortalQuery<PortalMeta>("meta", { ttl: 300_000 })` (already loaded by the shell → instant) |
| `ui.toast(msg, tone)` / `ui.confirm({...})` | `toast(msg, tone)` / `await confirm({...})` (plain functions) |
| `ui.modal` / `ui.drawer` | `<Modal open title onClose footer>` / `<Drawer open title onClose>` |
| `ui.formDialog({...})` → Promise | `<FormDialog open fields onSubmit onDone />` (same field specs) |
| `ui.form({...})` | `<PortalForm fields onSubmit />` |
| `export function destroy()` | effect cleanups |

## Fetching and caching (lib/cache.ts, lib/api.ts)

- `usePortalQuery<T>(path | null, { query?, scoped?, ttl? = 30 s, keepPrevious? })` →
  `{ data, error, loading, refreshing, reload }`. `null` path waits (dependent requests). Same URL = one request
  (de-duplicated); answers younger than `ttl` are served without a request; older ones show at once and refresh
  in the background — moving between screens is instant. Use `keepPrevious` for filter / page changes.
- `scoped: true` adds `districts=` from the global scope (none for "All districts") and keys the cache on it.
  The server returns 400 on an unknown district; the client turns that into `code: 'scope_rejected'` and the
  shell shows "District filter not applied · Reset districts" (never show whole-state numbers silently).
- Writes: `portalApi.post/patch/put/del`. A successful write clears the whole read cache (rollups change
  everywhere) and every mounted query refetches. Pass the same `idempotencyKey` for retries of ONE submission
  (FormDialog does this for you: the key survives only a network failure).
- Errors are `PortalApiError { status, message (friendly), fields, data, code }`. `status 0` = network
  (offline banner), 401 = LMS session ended (the client sends the browser to `/login?next=<here>`),
  403 `forbidden` = not an admin (`err.isAdminsOnly`), 403 `read_only` = viewer, 409 duplicates
  (`data.existing_id`…), 400 field errors (`fields` → shown under inputs by PortalForm).
- `prefetchPortal(path, req)` warms a likely next screen (e.g. on row hover).
- Types for the main entities: `lib/types.ts` (rows have index signatures for extra rollup fields).

## State

- **District scope** (`lib/scope.ts`): default = target districts (old Guntur / Krishna / West Godavari = 7 ids,
  from `GET /api/program`); stored in localStorage `td.districtScope` (same key and origin as the old portal);
  `?d=all|target|id,id` in the URL sets it (deep links) and is kept in step while present.
  `useDistrictScope()`, `useScopeLabel(max)`, `setDistrictScope()`, `resetDistrictScope()`, `targetGroups()`,
  `districtName(id)`, `inScope(id)`, `scopeRows(rows)`.
- **Session** (`lib/session.ts`): `usePortalSession()` from `GET /api/session` (proxy mode: `sso: true`,
  role `editor` for every LMS admin; `viewer` still honoured).
- **URL query** (`lib/query.ts`): `useQueryState()`, `mergeQuery`, `queryList`, `queryInt`. Free-text keys
  (`q`, `search`) replace the history entry; other changes push one with `history: "auto"`. `d` is never dropped.
- **Preferences** (`lib/prefs.ts`): theme (`td.theme`), sidebar collapsed (`td.nav`), `useDevice()`.

## Shared UI (`@/features/colleges/ui`)

| Component | Old | Notes |
|---|---|---|
| `Icon name size` | `ui.icon` | same 24 px set (`ICON_NAMES`) |
| `Button tone size icon ariaLabel busy` / `LinkButton to reload` | `ui.button` | icon-only needs `ariaLabel` |
| `PageHeader title sub eyebrow actions back scope meta tabs` | `ui.pageHeader` | `scope` shows the ScopePill |
| `Section title sub actions` · `Kv pairs` | `ui.section` · `ui.kv` | |
| `Kpi label value sub tone icon to onClick help loading basis` · `KpiRow` · `StatCard` | `ui.kpi/kpiRow/statCard` | numbers are formatted en-IN |
| `ProgressBar actual target min max status pct size` | `ui.progressBar` | server `pct` wins; `partial_target` = "Not judged" |
| `StatusChip status size` · `StatusBadge kind value` · `Badge tone` · `Chip` | `ui.statusChip/statusBadge/badge/chip` | vocabulary in `ui/status.ts` (`STATUS_META`, `PERF_STATUS_ORDER`) |
| `Provenance basis` · `ValueWithBasis value` · `VerifiedBadge state source date by` | `ui.provenance/valueWithBasis/verifiedBadge` | |
| `DataTable columns rows rowKey sort onSort page pageSize total onPage rowHref onRowClick rowActions selectable onSelect loading error onRetry empty mobile cardTitle cardSubtitle cardMeta cardSort` · `Pagination` | `ui.dataTable/pagination` | phone / narrow → cards; `priority: 3` columns hide first; ≤ 2 row actions are buttons, more go in a menu |
| `FilterBar values onChange search filters actions` | `ui.filterBar` | controlled; phone → "Filters (n)" sheet + chips |
| `Tabs tabs active onChange` · `LinkTabs items` · `Segmented options value onChange` | `ui.tabs/linkTabs/segmented` | |
| `Modal open title onClose footer wide form compact` · `Drawer` | `ui.modal/drawer` | focus trap, Esc, backdrop; drawer = bottom sheet on phones |
| `confirm({title,text,body,confirmLabel,danger})` · `toast(msg, tone)` | `ui.confirm/toast` | need `<OverlayHost/>` (the shell has it) |
| `Menu label icon items ariaLabel` | `ui.menu` | items `{label, icon, onClick, href, tone:'danger', writeOnly, hidden}` |
| `Field` · `PortalForm fields onSubmit onCancel` · `FormDialog open title intro fields values onSubmit onDone` | `ui.form/formDialog` | specs: text, number, date, tel, email, password, url, textarea, select, multiselect, checkbox |
| `EmptyState` · `ListEmpty filtered noun addLabel onAdd onClear` · `ErrorCard error retry` · `Skeleton` · `ViewSkeleton` · `Spinner` | `ui.emptyState/listEmpty/errorCard/skeleton/spinner` | use ListEmpty wording for every list |
| `ContactActions phone email whatsapp compact name` · `telHref` · `whatsappHref` | `ui.contactActions` | WhatsApp adds 91 to 10-digit numbers |
| `WriteOnly` · `usePortalUi()` | `ui.writeOnly`, `canWrite()` | |

Not ported (do it locally if a screen needs it): `ui.table` (old simple table — use DataTable),
`ui.progress` (use ProgressBar), `ui.scrollStrip` (`useScrollStrip`), `downloadCsv/csvCell` (copy from
components.js into `lib/csv.ts` when the first export screen is ported — keep the formula-injection guard),
history-backed overlays (Back closing a sheet), the old login / passcode screens (SSO only now).

## Map (`map/CollegeMap.tsx`)

`<CollegeMap colleges places focus highlight style={{ height: 420 }} />` — lazy-loads Leaflet (npm
`leaflet@1.9.4`, pinned, same as the vendored copy), the map CSS and the district GeoJSON (a hashed asset).
`engine.ts` is the old `map.js` verbatim (`@ts-nocheck`): district bubbles → town bubbles → pins as you zoom,
target districts outlined, out-of-scope dimmed (follows the scope automatically), hide-closed toggle
(`useShowClosed()` shares it with lists), zoom to district / town / college, reset (home) → `/colleges`,
light/dark tiles, touch gestures, OSM fallback. Clicks navigate to the district / town / college pages unless
you pass `onSelect*`. `onReady(api)` exposes the engine API (`getUnplacedCount`, `getClosedCount`, …).
`react-leaflet` was **not** added: the engine is imperative and tested; wrapping it once is smaller and safer
than re-implementing it in react-leaflet components.

## Charts (`@/features/colleges/charts`)

`BarChart`, `LineChart`, `ColumnChart`, `PaceMeter`, `Donut`, `Funnel`, `Sparkline`, `ProgressRing`,
`EmptyChart` — same props as charts.js (`data`, `series`, `points`, `steps`, `format`, `label`…). Accessible
(figure label, hidden data table, keyboard tooltips), token colours only.

## API and proxy constraints (college_portal.py, server.js)

- Base `/college-portal/api/`; methods GET, HEAD, POST, PATCH, PUT, DELETE; body ≤ 1 MiB; 15 s upstream timeout.
- Only these request headers reach the server: `accept`, `content-type`, `idempotency-key`,
  `if-modified-since`, `if-none-match`, `user-agent`. No `X-User` / `X-Passcode`: the actor is the LMS user
  (`x-td-proxy-user` = "Name (email)"), role always `editor`.
- Unsafe methods are CSRF-checked by `Origin` / `Sec-Fetch-Site` (must be same-origin) — a same-origin `fetch`
  passes; no CSRF token is needed (the LMS BFF token is not used here).
- Auth answers: 401 `{code:'auth_required'}`, 403 `{code:'forbidden'}` (not admin), 403 `{code:'cross_origin'}`,
  503 `{code:'auth_unavailable'}` (retry-after 5). Access is cached 60 s per instance for GETs; writes and
  page loads re-check.
- `POST /api/session` answers 409 `{code:'sso'}` behind the proxy (there is no portal sign-in).
- Idempotency (server): only 2xx results are remembered for 10 min; same key + different request → 422
  `idempotency_key_reused` (the client retries once with a fresh key).
- Every list/rollup endpoint accepts `districts=`; an unknown id → 400 (see scope_rejected above).
- `/api/live?refresh=1` starts a background refresh of the official sources (the old shell did this once per
  visit: the Official sources screen should call it once on mount).

## CSP and hosting

- `/colleges` and `/colleges/**` get the LMS CSP plus the OSM / CARTO tile hosts in `img-src`
  (`src/spa/hosting-headers.ts collegesCsp`). Headers apply per document, so `needsDocumentLoad`
  (`src/spa/nav-store.ts isCollegesPath`) makes crossing into or out of `/colleges` a full page load; inside
  the portal navigation stays client-side. **Not deployed yet**: regenerate `hosting-headers.json`
  (`node scripts/gen-static.mjs` with the Firebase env) and run `functions-lms/tools/sync_hosting.py` at cut-over.
- No external fonts: the LMS self-hosts Inter and Plus Jakarta Sans (the old portal used Google Fonts).
- The old portal's own HTML/CSS/JS keep being served at `/college-portal/**` until the cut-over.

## Conventions

- One screen per route folder; screen code in `features/colleges/screens/`; screen-specific CSS in the matching
  `styles/views/*.css`, imported by the screen.
- Never call `fetch` directly; never build `/colleges/...` strings by hand (`portalPath`); never compute
  rollups on the client (CONTRACT.md "Rollup semantics": the UI shows what the API returns).
- Same wording as the old views (owner-reviewed). Same status vocabulary (`ui/status.ts`). Indian number
  format via `fmt` (`lib/fmt.ts`), the one percentage rule `fmt.pctPts` / `fmt.pctOf`.
- Every list: loading skeleton, `ErrorCard` with retry, `ListEmpty` (filtered vs not), filters in the URL.
- Write controls behind `canWrite` / `WriteOnly` / `writeOnly: true`.
- Tests: vitest next to the code (`*.test.tsx`), run with
  `NODE_OPTIONS=--max-old-space-size=3072 npx vitest run --pool=threads --no-file-parallelism <paths>`;
  `npx tsc --noEmit` must stay at 0 errors. Do not run `npm run build`, browsers or servers locally.
- After adding / removing a page: `node scripts/gen-routes.mjs` and update `PAGE_COUNT` in `src/spa/spa.test.tsx`
  (199 with the 19 portal placeholders).
- Replace the placeholder (`ComingInThePort`) in the route's `page.tsx`; delete nothing in the old portal.

## Cut-over checklist (later, not part of porting)

1. All screens ported and checked on the live site. 2. Regenerate hosting headers + sync firebase.json.
3. Point the LMS `ModuleSwitcher` / hub `colleges` module / `FULL_SCREEN_COLLEGES` / `/admin/college-data`
to `/colleges`; add `/colleges` to `features/hub/last-page.ts` `COLLEGES_PREFIXES`. 4. Keep the API proxy;
retire only the static portal files (`/college-portal/{index.html,css,js,vendor,assets}`).
