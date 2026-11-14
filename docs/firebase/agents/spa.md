# SPA agent report: `apps/lms-spa` (Vite + React Router port of `apps/web`)

Date: 2026-11-12 (round 2 the same day). Scope: `apps/lms-spa/**`, this report and, in round 2 only, the `hosting` → `lms` entry of `firebase.json`. `apps/web` was not modified. Nothing was deployed.

## 1. Approach

The port copies `apps/web/src` unchanged and swaps the Next runtime underneath it, so the UI code stays identical and can be re-synced while the live app keeps changing.

| Piece | How |
|---|---|
| Copy | `scripts/sync-from-web.mjs` copies `apps/web/src` → `src/` (everything except `src/spa/`), `apps/web/public` → `public/`, `apps/web/openapi` → `openapi/`. Left out (server-only, the API function replaces them): `middleware.ts`, `app/api/**`, `app/college-portal/**`, every `route.ts`, `lib/bff/**`, `lib/college-portal/**`. `scripts/sync-report.json` lists what was copied. |
| `next/*` shims | Vite and TS aliases (`vite.config.ts` `nextShimAliases`, `tsconfig.json` `paths`) point at `src/spa/shims/`: `next/link` (React Router `<Link>`, with plain `<a>` for external, hash and download links), `next/navigation` (`useRouter` push/replace/back/forward/refresh, `usePathname`, `useSearchParams`, `useParams` with catch-all → `string[]`, `redirect`/`permanentRedirect`/`notFound` throw marker errors), `next/dynamic` (`React.lazy` + `Suspense` with the `loading` option), `next/headers` (`headers()` rebuilt from `location`, `cookies()` from `document.cookie`), `next` (types only: `Metadata`, `Viewport`, `MetadataRoute`), `server-only` (no-op). |
| Server pages | The sync rewrites every `async function` component in a non-`"use client"` file: `export default async function Page(` becomes `async function Page__server(` plus `export default asyncComponent(Page__server, "<file>#Page")`. Nothing else in the file changes. `src/spa/async.tsx` calls the function (server components use no hooks, so this is safe) and renders its result with React 19 `use()`. While it loads, the page suspends to the segment's `loading.tsx`, like Next streaming. Navigations are React transitions, so the previous page stays on screen until the next one is ready. The promise is cached per component, navigation key, `router.refresh()` counter and props. A new navigation or a refresh reloads the data, as Next re-renders server components on each navigation. |
| Server data | `lib/api/server.ts` is overridden. `serverApiGet(path)` makes the same GET through the browser client (`apiRequest`, same `/api/v1/<path>`) with the client's global auth, restriction, step-up and session-choice redirects turned off. Errors are thrown back to the page, as on the server. `navigation: true` sends `x-td-activity: navigation`. A network failure becomes `ApiError(503)`. `hasSessionCookie()` uses the session probe `GET /api/v1/_bff/session` (section 4). It answers "yes" or "no" from the function's `{session}` reply, and "unknown" for a network error or a reply that is not JSON. A "yes" is cached for 60 s and anything else for 3 s; the cache is dropped when you enter or leave the auth pages. |
| Overrides (`spa-overrides/`, 5 source files + 1 ported test) | `app/layout.tsx`: same markup without `<html>/<body>` (those are static in `index.html`), keeps the `metadata` title template. `app/(public)/layout.tsx`: `signedIn` comes from the probe when the area mounts. `components/shell/PortalShell.tsx`: same markup; the session gate redirects to `/login?next=<path+search>` (same `signInNext`). `features/staff-portal/StaffPortalGate.tsx`: same `/me/grants` decision logic, made once when the portal mounts. `lib/api/server.ts`: described in the row above. |
| Routing | `scripts/gen-routes.mjs` walks `src/app` and writes `src/spa/routes.gen.tsx`. It handles nested layouts, route groups `(x)` (pathless), `[x]` → `:x`, `[...x]` → `*` (param `x: string[]`), and `error.tsx` + `loading.tsx` per segment. All page and segment modules are lazy (one chunk per route). The tree also gets the root `not-found`, `global-error`, a `*` 404 route, and the three `next.config.ts` redirects (`/admin/security[/*]` → `/security[/*]`, `/verify/certificate/:id` → `/verify/:id`). |
| Boundaries | Each segment has the same nesting as Next: `Layout > ErrorBoundary(error.tsx) > Suspense(loading.tsx) > Outlet`. `src/spa/boundary.tsx` handles a thrown `redirect()` as a client navigation (a full load for another origin). `notFound()` goes up to the root and renders `app/not-found.tsx`. Other errors render that segment's `error.tsx` with `{ error, reset }`, or go to the parent segment if it has none. A boundary resets on navigation. Errors in the root layout itself render `global-error.tsx` (minus its `<html>/<body>`). |
| Metadata | `metadata` / `generateMetadata` → `document.title` (root template `%s · Tech Drona`, default `Tech Drona`), `<meta name="description">` and `<meta name="robots">` (`src/spa/metadata.ts`). |
| Env | `scripts/build-env.ts` (shared by `vite.config.ts` and `gen-static.mjs`). **Builds** (`vite build`, Firebase) read `apps/lms-spa/.env.production`, the deploy shell's environment, and from the repo-root `.env` only the public `NEXT_PUBLIC_FIREBASE_*` web config. **`vite dev`** reads the repo-root `.env` (+ `apps/lms-spa/.env*`). The bundle keeps only `NEXT_PUBLIC_*`, `TD_GOOGLE_SIGNIN_ENABLED`, `TD_FIREBASE_ANALYTICS_ENABLED` and `NODE_ENV`, and maps `VITE_X` → `NEXT_PUBLIC_X` (`VITE_` wins). `define` rewrites `process.env` → `globalThis.__TD_ENV__`. `src/spa/env.ts` (the first import) fills it in and sets `TD_API_INTERNAL_URL = location.origin`, so the site catalogue's course-status call goes same-origin to `/api/v1/public/courses/status`. Existing code that reads `process.env.NEXT_PUBLIC_X` or `env["X"]` works unchanged. No secrets reach the bundle. |
| Static files | `scripts/gen-static.mjs` writes three things. `public/manifest.webmanifest` comes from the copied `app/manifest.ts`. `public/robots.txt` is `User-agent: *` / `Disallow: /`, which is what Caddy answered on the LMS host. There is **no** `sitemap.xml`: Caddy answered 404, and Hosting routes `/sitemap.xml` to the function, which answers 404. It also writes `hosting-headers.json` (section 6) and refuses to write it if any origin is `http://`, `localhost` or `sslip.io`. |
| Monaco | `scripts/copy-monaco.mjs` (copied) runs on `predev`/`prebuild` and puts `monaco-editor/min/vs` in `public/vendor/monaco/vs`. It is served same-origin, as before. |
| Styles | The same `tailwind.config.ts` (same preset chain: fallback tokens, then `packages/design-tokens`), `postcss.config.mjs`, `globals.css` (its `../../../../packages/design-tokens/tokens.css` import resolves the same from `apps/lms-spa/src/app`), `site.css` and `fonts.css`. Fonts are self-hosted and preloaded in `index.html`. |

Commands, run inside `apps/lms-spa`:

- `npm run sync`: re-copy from `apps/web`, regenerate the routes and the static files.
- `npm run build`: copy Monaco, generate routes and static files, then `vite build` → `dist/`.
- `npm run dev`: set `TD_DEV_API_PROXY=http://localhost:8000` to proxy `/api` to a local API.
- `npm test` / `npm run typecheck`.

## 2. Route count

The generator found **204 pages, the same as the 204 `page.tsx` files in `apps/web/src/app`.** `scripts/routes-report.json` lists every URL pattern, and `src/spa/spa.test.tsx` asserts `PAGE_COUNT === 204`. The tree also has 11 layouts, 11 `error.tsx`, 2 `loading.tsx`, the root `not-found` and `global-error`, and 3 redirects.

## 3. Server → client conversions

- **99 async pages** became client components through `asyncComponent`. Their source, data paths (`serverApiGet("<same path>")`), `redirect`/`notFound` calls and rendered JSX are unchanged.
- **5 async shared components** were wrapped the same way: `CourseDetail`, `SiteCourseStrip`, `SiteCatalogAdminSection`, `SelfPacedCourses` (in `app/app/courses/page.tsx`) and the root `not-found`.
- **3 async layouts/gates** were hand-ported in `spa-overrides/`: `(public)/layout`, `PortalShell` and `StaffPortalGate`. The root layout was also ported (`headers()` is not needed).
- That is 104 wrapped components in 103 files in total (`scripts/sync-report.json`).

## 4. Middleware → SPA

| `middleware.ts` behaviour | SPA |
|---|---|
| Remember-device refresh (`td_remember`) and `td_csrf` issue/refresh on a page load | **`GET /api/v1/_bff/session` once on app start**, before the router renders (`src/spa/main.tsx` `bootstrapSession`, at most 8 s). It follows the contract in `functions-lms/lms_edge/app.py` `_session_probe`: same-origin, `200 {"session": bool, "refreshed": bool}`. The function re-signs-in a remembered device and sets the cookies on that response. The client's existing `GET /api/v1/_bff/csrf` retry still covers a rejected token. |
| Portal paths, `/modules` and `/continue` without a session → `/login?next=<path+search>` | `PortalShell` (all 9 portals) redirects when the probe says `session: false`, with the same `next`. `/modules` and `/continue` check `hasSessionCookie()` themselves (now the same probe). The probe is called again only when its 60 s / 3 s memo expires. |
| Caddy `/` on the LMS host: no session → `/login`, session → `/modules` | Done by the app on a **document load** of `/`. Signed out (or unknown) → `location.replace("/login")`, a real load so `/login` gets its own headers. Signed in → `/modules`. Client-side links to `/` still show the home page, as behind Caddy. |
| `Cache-Control: no-store` on portal pages | The HTML shell now carries no user data, so it is sent with `no-cache` (section 6). API responses keep their own headers. |
| Per-request CSP nonce | A static CSP without a nonce (section 6). |
| `x-td-request-path` header | Read from `location` (shim). |
| `x-td-activity: navigation` on page loads | Sent by the page-load GETs, i.e. `serverApiGet(..., { navigation: true })`: the catalogue `serverLoad()` pages and `me/modules`, the same calls that set it in Next. **Platform must act:** `lms_edge` does not forward this header from the browser. It only sets it for `sec-fetch-mode: navigate`, which a `fetch()` never is. To keep idle-timer parity, the edge should set `x-td-activity: navigation` upstream when a same-origin GET carries it. |

## 5. Test and build results

All results are from 2026-11-12, run inside `apps/lms-spa` on Node 24.21 / npm 11.19.

| Check | Result |
|---|---|
| `npm ci` | OK. 245 packages, react-router 7.18.5, vite 7.3.8, vitest 3.2.7, React 19.2.9. The first install from the interrupted session had a corrupted `jsdom`, so I reinstalled with `npm ci`. |
| `tsc --noEmit` | **0 errors**. |
| `vitest run --pool=threads --no-file-parallelism` | Round 1: 1000/1000. **Round 2: 106/106 files, 1003/1003 tests passed.** That is 104 ported apps/web test files, 1 test ported with changes, and the new `src/spa/spa.test.tsx` (14 tests: route count, shims, async components, redirect, notFound/error boundary, metadata, Hosting headers, the `_bff/session` contract, the `/` redirect). |
| `npm run build` (copy Monaco, generate routes and static files, `vite build`) | **OK in about 16 s (round 2: OK, 14.5 s, Firebase env).** `dist/` is 20 MB, most of it the Monaco vendor files. There are 381 assets, with lazy chunks per route. The entry chunk is 661 kB (191 kB gzip): React, the router, the firebase SDK used by the shell, and the shared UI. `index.html` has no inline script. |
| `vite preview` smoke test (Playwright Chromium, 14 routes × 3 API modes; round 2 mocks `_bff/session`) | **All pages render with no page errors and no console errors.** Details below. |
| Firebase Hosting emulator (round 2) | Partly verified. It serves `dist/`, the SPA fallback (`/app/courses` → `index.html`) and `robots.txt`. **On this Windows machine the Hosting emulator applies no `headers` and no glob `redirects`, even with a 1-rule test config.** The cause is in firebase-tools 15.34 / superstatic: `glob-slasher` turns `/x` into `\x` on win32, so no source pattern matches. Run the emulator on Linux/macOS/WSL/CI to check headers. The Functions emulator was not started (section 8). |

Test notes:

- 5 apps/web test files are not ported because they test server code the platform agent re-implements: `middleware.test.ts`, `lib/bff/{proxy,remember,public-admissions}.test.ts` and `lib/college-portal/proxy.test.ts`.
- `features/staff-portal/staff-portal.test.tsx` is ported with the same assertions. It drives `decideStaffPortal()` + `GateView` instead of awaiting the old async server component (`spa-overrides/features/staff-portal/staff-portal.test.tsx`).
- Tests that awaited a page's server component directly now call `Page.server(...)`, which is the original function. The sync rewrites this mechanically; one file is affected (`trainer-fixes.test.tsx`).
- One test passes the same way it did in Next: `firebase.test.ts` checks the COOP rules. `apps/lms-spa/next.config.ts` re-exports the Hosting header rules in the `headers()` shape that test expects.
- On this machine, vitest must run with `--no-file-parallelism`. Parallel workers ran out of memory because other agents were using most of the RAM; this is not a code problem.

Smoke test results (`vite preview` on `dist/`). Routes checked: `/`, `/?x=1`, `/login`, `/help`, `/courses`, `/modules`, `/app`, `/app/settings/profile`, `/admin`, `/admin/users`, `/studio`, `/trainer/tests`, `/verify`, `/no-such-page`.

- **No API behind `/api`:**
  - Public pages render with the right titles (for example `Log in · Tech Drona`, `Courses · Tech Drona`).
  - `/` → `/login` (round 2).
  - `/modules` → `/login?next=%2Fmodules`.
  - Portal pages render their shell with the pages' own "Something went wrong" API error states (I checked the screenshots: the same Tailwind look).
  - `/no-such-page` → the branded 404 (`Page not found · Tech Drona`).
- **Signed out (`_bff/session` → `{session:false}`, `/api/v1/*` → 401 `unauthenticated`):** `/` → `/login`; every portal URL redirects to `/login?next=<encoded path>`, the same `next` as the middleware produced.
- **Student (`_bff/session` → `{session:true}`, `me` 200, `me/grants` portals `["/app"]`):**
  - `/` and `/?x=1` → `/modules` (round 2).
  - `/admin`, `/admin/users`, `/studio` and `/trainer/tests` → `/app` (ADM-12 gate).
  - `/login` → `/continue` → `/modules` (already signed in).
  - The public header shows "Dashboard".

## 6. Headers and CSP for Firebase Hosting (platform agent applies them)

`npm run build` (or `node scripts/gen-static.mjs`) writes `apps/lms-spa/hosting-headers.json` in `firebase.json` `hosting.headers` format, computed from the build env. The source of truth is `src/spa/hosting-headers.ts`, which reuses `buildCsp()` from `lib/security/csp.ts`. The rules, in order (later rules override earlier ones for the same key):

1. `/**`:
   - `X-Content-Type-Options: nosniff`
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `X-Frame-Options: DENY`
   - `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(self)`
   - `Cross-Origin-Opener-Policy: same-origin`
   - `Cache-Control: no-cache`
   - `Content-Security-Policy:` the general CSP below.
2. `/assets/**`: `Cache-Control: public, max-age=31536000, immutable` (Vite hashed files).
3. `/login`, `/signup`: `Cross-Origin-Opener-Policy: same-origin-allow-popups`, plus the CSP with the Google sign-in hosts.
4. `/admin/college-data`: the CSP with `frame-src 'self'` added.
5. `/college-portal`, `/college-portal/**`: `X-Frame-Options: SAMEORIGIN`. The portal and its proxy are platform scope; it keeps its own CSP.

General CSP, exact directives (round 2, Firebase build env: `.env.production`):

```
default-src 'self';
script-src 'self' https://checkout.razorpay.com https://player.vdocipher.com https://www.googletagmanager.com;
style-src 'self' 'unsafe-inline';
img-src 'self' data: blob: https://cdn.razorpay.com https://checkout.razorpay.com https://*.google-analytics.com https://www.googletagmanager.com https://techdrona-website.web.app;
font-src 'self' data:;
connect-src 'self' https://api.razorpay.com https://lumberjack.razorpay.com https://storage.googleapis.com https://vdo-ap-southeast.s3-accelerate.amazonaws.com https://*.google-analytics.com https://*.analytics.google.com https://www.googletagmanager.com https://firebase.googleapis.com https://firebaseinstallations.googleapis.com https://firestore.googleapis.com https://techdrona-website.web.app;
frame-src https://player.vdocipher.com https://api.razorpay.com https://checkout.razorpay.com https://www.youtube-nocookie.com https://player.vimeo.com https://docs.google.com https://drive.google.com;
media-src 'self' blob:;
worker-src 'self' blob:;
object-src 'none';
base-uri 'none';
form-action 'self' https://storage.googleapis.com https://vdo-ap-southeast.s3-accelerate.amazonaws.com;
frame-ancestors 'none'
```

How it differs from the Next CSP:

- **`script-src` drops `'nonce-…'` and `'strict-dynamic'`.** A static file cannot carry a per-request nonce, and `'strict-dynamic'` without a nonce blocks every script. The host allow-list that was the CSP2 fallback is now the real policy. All SPA code is same-origin (`'self'`), including the Monaco AMD loader and workers under `/vendor`. There is still no `'unsafe-inline'` or `'unsafe-eval'` for scripts (the Vite build emits no inline scripts).
- **`connect-src` adds `https://firestore.googleapis.com` and the website origin.** The site catalogue (`fetchSiteCatalog`) ran on the server and now runs in the browser. It reads `<website>/catalog.json` and the public Firestore `web_course_public` REST collection.
- On `/login` and `/signup`:
  - `script-src` also has `https://apis.google.com`;
  - `connect-src` also has `https://identitytoolkit.googleapis.com` and `https://securetoken.googleapis.com`;
  - `frame-src` also has `https://<authDomain>` (now `https://billing-f4fe3.firebaseapp.com`) and `https://accounts.google.com`.
- The upload origins come from `S3_ENDPOINT_URL=https://storage.googleapis.com` (in `.env.production`; `TD_CSP_UPLOAD_ORIGINS` overrides it) plus the VdoCipher upload origin, as before. The website origin comes from `NEXT_PUBLIC_SITE_URL=https://techdrona-website.web.app`. No VM origin remains: the generator refuses `sslip.io`, `localhost` and `http://`.

Response headers apply per document, so the SPA keeps the per-path policies by **always opening `/login`, `/signup` and `/admin/college-data` with a full page load, and leaving them with one** (`DOCUMENT_ROUTES` in `src/spa/nav-store.ts`, used by `next/link`, `useRouter` and the API client's navigate hook).

In `firebase.json`, Hosting puts the Caddy transport headers (`Strict-Transport-Security`, `X-Robots-Tag: noindex, nofollow`) on `**` in front of these rules (section 8).

## 7. Known differences (honest list)

1. **First paint is client-rendered.** Next sent finished HTML. Now the browser loads the JS chunk, then the page's API calls, and shows the segment `loading.tsx` skeleton (public area and student area) or a blank area (other portals) meanwhile. The UI after loading is the same.
2. **One `GET /api/v1/_bff/session` on app start** (plus one after the probe memo expires). It answers "is there a session cookie", like the middleware did, and does not call FastAPI unless it refreshes a remembered session. If the API is unreachable, the answer is "unknown": public pages show the signed-out header, a document load of `/` goes to `/login`, and portals render and let their API calls fail as they did before.
3. **No HTTP status codes for pages.** `notFound()` renders the 404 page with HTTP 200, and redirects are client-side (Hosting can do the three static redirects as real redirects). Crawlers see the SPA shell. `robots.txt` is `Disallow: /` and `/sitemap.xml` is a 404, as Caddy served them on the LMS host.
4. **The website catalogue is fetched by the browser.** The website must allow CORS on `/catalog.json` for the LMS origin. Without it, the catalogue falls back as it already did when unreachable (cards from live state only, or a link to the website). Next cached it for 5 minutes on the server; the browser now uses normal HTTP caching.
5. **`x-td-activity: navigation`** used to be set by the BFF only. Now the browser sends it on page-load GETs. **The `lms_edge` function drops it today** (section 4), so it needs a platform change. It only extends the caller's own idle timer.
6. **CSP has no nonce and no `'strict-dynamic'`** (section 6). It is slightly weaker in theory (any script on an allow-listed host could run), but there is still no inline script.
7. `/login`, `/signup` and `/admin/college-data` are always full page loads (to keep their own COOP/CSP).
8. `React.cache()` does not memoise on the client, so `courses/[slug]` loads the course twice (once for `generateMetadata`, once for the page).
9. Not ported (platform scope): the BFF route handlers (`/api/v1/[...path]`, `/api/public/**`, `/college-portal/**`) and their tests (`lib/bff/*.test.ts` ×3, `lib/college-portal/proxy.test.ts`, `middleware.test.ts`). These are the 5 apps/web test files not in the SPA.
10. The LMS origin is the placeholder `https://techdrona-lms-app.web.app` (`NEXT_PUBLIC_BASE_URL` in `.env.production`). Override it with `VITE_BASE_URL=https://<site>` in the build shell once the site exists. The copied `lib/site/website.ts` still contains its old fallback constant (the VM website URL) in the bundle. It is never used, because `NEXT_PUBLIC_SITE_URL` is always set for builds.
11. `npm install` with npm 11 skips dependency install scripts (esbuild, protobufjs, `@firebase/util` postinstall). The build and tests work without them.
12. `/college-portal/**` header rules are still in `hosting-headers.json` (`X-Frame-Options: SAMEORIGIN`), but the portal itself is not on Firebase (platform blocker). Until it is, those paths fall into the SPA fallback and show the 404 page.

## 8. Round 2: Firebase Hosting (+ emulator)

### Build env (exact)

`cd apps/lms-spa && npm ci && npm run build`. The default `vite build` mode is the Firebase build, so nothing else is needed. It reads these values:

| Variable | Value | Source |
|---|---|---|
| `NEXT_PUBLIC_BASE_URL` | `https://techdrona-lms-app.web.app` (placeholder) | `.env.production`; override with `VITE_BASE_URL` |
| `NEXT_PUBLIC_SITE_URL` | `https://techdrona-website.web.app` | `.env.production` |
| `NEXT_PUBLIC_APP_NAME`, `NEXT_PUBLIC_ERRORS_TUNNEL=/api/v1/_errors`, `NEXT_PUBLIC_ANALYTICS_SCHEMA_VERSION=1` | | `.env.production` |
| `S3_ENDPOINT_URL` | `https://storage.googleapis.com` (CSP only, not bundled) | `.env.production` |
| `NEXT_PUBLIC_FIREBASE_*` | web config of `billing-f4fe3` (public) | repo-root `.env` (only these keys) |
| `TD_GOOGLE_SIGNIN_ENABLED`, `TD_FIREBASE_ANALYTICS_ENABLED`, `TD_CSP_UPLOAD_ORIGINS`, any `VITE_*` | optional | deploy shell |

The same `dist/` works on the emulator, because the API is same-origin through the rewrite and the CSP uses `'self'`. No emulator-specific build is needed.

### `firebase.json` → `hosting` → `lms` (edited in round 2)

Only the `lms` entry was changed. I checked this with a JSON diff: the `showcase` target, `functions`, `firestore` and `emulators` are unchanged.

- **`headers`** now holds the platform's Caddy rule on `**` (HSTS, `X-Robots-Tag: noindex, nofollow`) followed by the regenerated `apps/lms-spa/hosting-headers.json`. The block was there, but it had the old VM-origin CSP (`sslip.io`).
- **`rewrites`** now has `/sitemap.xml` → `lmsApi` added, so the function's catch-all answers 404 (Caddy parity), between `/api/**` and the SPA fallback.

The resulting `rewrites`:

```json
"rewrites": [
  { "source": "/api/**", "function": { "functionId": "lmsApi", "region": "asia-south1", "pinTag": false } },
  { "source": "/sitemap.xml", "function": { "functionId": "lmsApi", "region": "asia-south1", "pinTag": false } },
  { "source": "**", "destination": "/index.html" }
]
```

`headers` = `[{ "source": "**", "headers": [Strict-Transport-Security max-age=31536000, X-Robots-Tag noindex, nofollow] }, ...apps/lms-spa/hosting-headers.json]`.

After any rebuild, re-sync with `python functions-lms/tools/sync_hosting.py`. That script does **not** add the `/sitemap.xml` rewrite, so platform should add the line to `lms_hosting()`. Alternatively, paste the file contents after the first rule.

### Running on the emulators

```
cd apps/lms-spa && npm run build
cd ../.. && firebase emulators:start --only hosting:lms,functions:lms --project billing-f4fe3
# Hosting http://127.0.0.1:5000, Functions 5001 (default ports: firebase.json's emulators block has none)
```

- Function env for the emulator (platform scope, `functions-lms/.env.local`):
  - `TD_PUBLIC_BASE_URL=http://127.0.0.1:5000`, which must equal the page origin for the Origin and Fetch Metadata checks;
  - `APP_ENV=local` and no `NODE_ENV=production`, so the edge uses dev-insecure cookie names. `__Host-` and Secure cookies are refused on `http://127.0.0.1`; `http://localhost` works in Chrome;
  - `TD_CSRF_KEY`, plus the API's own env (DB/Firestore emulator).
- **Port conflict:** another emulator suite is already running on this machine with the hub on 14400, UI on 14000, logging on 14500, Auth on 19099 and Firestore on 18080. A second `emulators:start` from the same `firebase.json` collides on the hub/UI/logging ports. Stop it first, or start with a separate `--config` that has other hub/logging ports.
- **What I verified locally (Windows):** with a copy of the `lms` entry (ports 15000/15400), the Hosting emulator served `dist/`, the SPA fallback and `robots.txt`. It did **not** apply headers or glob redirects (the superstatic `glob-slasher` bug on win32 in section 5). The `/api/**` → function rewrite returned 404 with no Functions emulator running.
- **What I did not verify:** I did not start the Python Functions emulator. Platform reports that the full API needs Postgres or flipped Firestore modules and has never run it under the emulator. An end-to-end emulator run needs three things:
  - Linux/macOS/WSL, for Hosting header and redirect parity;
  - the platform's function env;
  - free emulator ports.

