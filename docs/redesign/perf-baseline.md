# Performance baseline (pre-redesign) — Tech Drona LMS

Agent: Performance (baseline phase), 2026-11-07. Read-only on application code. Scripts and raw data are in
`docs/redesign/perf/` (all re-runnable, see §7). Every number below was measured in this session unless it is
labelled *code-reviewed*. Nothing here was tuned or changed.

## 0. Measurement conditions (read this before comparing numbers)

| Item | Value |
|---|---|
| Host | Intel i5-12450H (8 cores / 12 threads), 15.7 GB RAM, Windows 11 |
| Host load during runs | **Heavily contended.** ~0.02 GB physical RAM free, CPU 64–76 % busy (measured 13:3x UTC) — several other agents were running Playwright/pytest against the same stack at the same time. A `docker compose exec` crashed once with `pageAlloc: out of memory`. uvicorn worker children were observed dying and being respawned (`Child process [...] died` in `docker compose logs api`). |
| Docker | Engine 29.2.0, 12 vCPU / 7.6 GB VM. Stack: `techdrona-*` containers healthy, unchanged during the runs (not restarted). |
| Web under test | `techdrona/td-web:local` image created 2026-11-07T12:37Z, **production** standalone (`NODE_ENV=production`), http://localhost:13000 |
| API | `td-api:local`, uvicorn 2 workers, `DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=2` (`apps/api/app/core/config.py:62-63`) |
| Bundle numbers | local `apps/web/.next` (BUILD_ID `5FGhmYJj…`, built 17:44 IST, before any redesign edit; `find src -newer .next/BUILD_ID` was empty at 18:20). Chunk hashes differ from the image, so per-route sizes are representative, not byte-exact for the image. `npm run build` was **not** re-run: redesign agents were editing `src/` concurrently and a rebuild would no longer be a baseline. |
| Browser | Playwright 1.64.1, headless Chromium 156.0.8078.4, desktop viewport, no CPU/network throttling, localhost (no network latency) |
| Runs | 3 runs per page. **Cold** = fresh browser context (empty HTTP cache, cookies from the saved sign-in). **Warm** = second navigation in the same context. Table values are medians. |
| Accounts | student pages as `asha.student@`; all staff pages as `admin2@` (super_admin can open every staff portal). `student@`, `admin@`, `trainer@`, `evaluator@`, `content@` were all at the 3-device cap with devices created minutes earlier by other agents; I did **not** replace devices (2 replacements / 30 days would have locked other agents out). Admin sees platform scope, so the trainer/evaluator pages show *all* batches (≥ a real trainer's data). |

Because of the contention, absolute timings are pessimistic and noisy (e.g. the evaluator warm run LCP is 3 s while
cold is 1.4 s). Relative findings (request counts, duplicates, waterfalls, bytes, bundle sizes, caching headers) are
stable and are what the optimisation list is based on. **Re-run §7 on a quiet machine before the "after" comparison.**

## 1. Web bundles (First Load JS)

Method: `docs/redesign/perf/bundle-stats.mjs` sums the gzip(-9) size of every JS chunk a route loads (page entry
+ all ancestor layouts, from `app-build-manifest.json`). No source maps are emitted, so `source-map-explorer`
cannot be used; `@next/bundle-analyzer` is not installed (not added). Raw: `perf/bundle-stats.json`.

- 185 page routes. First Load JS (gzip): **min 110 KB, median 134 KB, max 173.5 KB**; 15 routes > 150 KB.
- Shared by every route: 100.2 KB gz (react-dom 53 KB, Next runtime `1255-*` 45.2 KB, webpack 1.8 KB). Root layout
  + Providers add ~15 KB. CSS: 12.4 KB gz for every route (2 files).
- `framework-*`, `main-*`, `polyfills-*` (132 KB gz) belong to the pages-router fallback only (used by 0 app routes;
  polyfills are `nomodule`).
- Heavy deps are already split: **recharts** lives in a lazy chunk `8939-*` (112 KB gz, 0 static users; loaded by
  `features/progress/components/LearningTimeChart.tsx:12` via `next/dynamic`). **Monaco** is self-hosted under
  `public/vendor/monaco` (14 MB on disk) and loaded on demand by `@monaco-editor/react`
  (`features/coding/components/MonacoEditor.tsx:11`). No lodash/moment/date-fns/icon packs in the bundle.

| Route (page measured in §2) | First Load JS gz (KB) | raw (KB) |
|---|---|---|
| `/` , `/courses` | 115.5 | 384 |
| `/login` | 120.8 | 398 |
| `/app` | 139.1 | 453 |
| `/app/learn/[course]/[lesson]` (course player) | 143.2 | 465 |
| `/app/tests/[test_id]` (test landing) | 159.8 | 515 |
| `/app/attempts/[attempt_id]` (test runner) | 156.6 | 506 |
| `/app/assignments` | 146.4 | 479 |
| `/app/path/my/[allocationId]` | 150.1 | 482 |
| `/app/progress` (target of `/app/analytics`) | 133.6 | 436 |
| `/admin` / `/admin/users` / `/admin/batches` | 136.5 / 133.0 / 138.9 | 448 / 434 / 454 |
| `/trainer` | 155.2 | 503 |
| `/evaluator` | 142.7 | 462 |
| `/studio/question-banks` / `[bank_id]` | 151.0 / 161.4 | 484 / 515 |
| `/evaluator/tests/[id]/report` | 133.7 | 437 |
| Largest: `/trainer/assignments/[id]` | 173.5 | — |

Largest non-framework chunks: `6721-*` 14.5 KB (test-runner UI; also pulled into the *landing* page
`/app/tests/[test_id]`), `5047-*` 14.4 KB (assignment submission), `/trainer/assignments/[id]` page 12.3 KB,
`9424-*` 10.8 KB (grading). Verdict: **bundles are not the bottleneck** (automated-tested via build artefacts).

## 2. Page timing (Playwright, median of 3)

Script `perf/page-timing.mjs`; raw `perf/page-timing.json` (incl. per-request API list per page). TTFB = navigation
`responseStart − requestStart`; LCP/CLS/long tasks via buffered `PerformanceObserver`; bytes = CDP
`encodedDataLength` of every request; "API" = `/api/*` (BFF) calls in the last cold run.

| Page | Path | As | TTFB | FCP | LCP | load | CLS | req | KB xfer | JS KB | long tasks n/max ms | warm TTFB | warm LCP | warm KB | API calls | duplicate API calls |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| public home | `/` | anon | 549 | 1440 | 1788 | 1693 | **0.179** | 30 | 153.8 | 123 | 2/89 | 23 | 992 | 17.8 | 0 | — |
| course catalog | `/courses` | anon | 177 | 1116 | 1356 | 1182 | 0.029 | 31 | 159.0 | 123 | 1/105 | 72 | 1384 | 22.9 | 0 | — |
| login | `/login` | anon | 63 | 1240 | 1240 | 1311 | 0 | 32 | 165.7 | 132 | 1/66 | 15 | 524 | 17.2 | 0 | — |
| student dashboard | `/app` | student | 108 | 1320 | 2004 | 1365 | 0 | 49 | 191.6 | 153 | 1/55 | 15 | 976 | 22.4 | 7 | — |
| course player | — | — | not measured: no demo learner is enrolled in any course (only an audit-created account is), and `/app/courses/demo-dsa-free` returns "We couldn't find this" for asha. Enrolling would have changed a shared fixture. |
| test landing | `/app/tests/:id` | student | 79 | 944 | **3044** | 994 | 0 | 44 | 208.1 | 173 | 1/51 | 18 | 2932 | 26.2 | 4 | — |
| assignments | `/app/assignments` | student | 99 | 1248 | 1680 | 1326 | 0 | 41 | 192.8 | 158 | 1/69 | 25 | 1208 | 21.0 | 4 | — |
| paths player | `/app/path/my/:id` | student | 98 | 1424 | 2212 | 1482 | 0.008 | 48 | 210.2 | 170 | 1/51 | 25 | 1544 | 24.5 | 5 | — |
| analytics | `/app/analytics` → `/app/progress` | student | 167 | 356 | 1040 | 397 | 0.015 | **70** | **316.5** | 258 | 1/82 | 32 | 744 | 41.0 | 10 | me/grants ×2, me/notifications ×2, me/enabled-apps ×2 |
| admin dashboard | `/admin` | admin | 109 | 988 | 988 | 1022 | 0 | 41 | 185.9 | 147 | 1/52 | 58 | 480 | 24.8 | 3 | — |
| admin users | `/admin/users` | admin | 76 | 548 | 844 | 596 | **0.378**¹ | 48 | 186.0 | 144 | 0/0 | 65 | 1008 | 31.5 | 2 | — |
| admin batches | `/admin/batches` | admin | 222 | 1436 | 1436 | 1471 | 0.005 | 44 | 188.0 | 151 | 1/58 | 65 | 952 | 24.4 | 2 | — |
| trainer dashboard | `/trainer` | admin | 119 | 1832 | 1832 | 1875 | 0.002 | 60 | 223.9 | 169 | 1/59 | 60 | 1372 | 39.2 | **12** | me/grants ×2, studio/tests ×2 (+4× tests/:id/assignments, N+1) |
| evaluator queue | `/evaluator` | admin | 127 | 1444 | 1444 | 1484 | 0 | 25 | 180.2 | 155 | 1/58 | 202 | 3044 | 10.9 | 3 | assignments?scope=mine ×2 |
| studio question banks² | `/studio/question-banks` | admin | 78 | 860 | 860 | 928 | 0 | 34 | 193.7 | 164 | 1/59 | 52 | 524 | 19.1 | 3 | — |
| test report (analytics) | `/evaluator/tests/:id/report` | admin | 148 | 1592 | 1592 | 1637 | **0.193**¹ | 26 | 173.7 | 145 | 1/72 | 97 | 1048 | 14.7 | 5 | me/grants ×2 |

¹ Intermittent: a single diagnostic re-run (`perf/cls-sources.mjs`) recorded 0 shifts on these two pages; the home-page
shift reproduced every time (source: `<footer>` moved by the streamed page replacing the shorter `(public)/loading.tsx`
skeleton). ² admin2 gets **403** on `GET studio/question-banks` — the page measured is its error state, not a populated
bank list (a content-manager sign-in was blocked by the device cap).

Observations (automated-tested):
- **Main thread is not a problem**: 0–2 long tasks per load, max 152 ms (home, run max). JS execution is fine.
- **Caching works for static assets**: warm loads transfer 11–41 KB instead of 154–317 KB.
- **LCP is data-bound, not byte-bound**: on student dashboard, paths player and test landing LCP lands 0.7–2.1 s after
  FCP because the main content is fetched client-side after hydration (`useResource`/`useApi` in `useEffect`).
- Every portal page fires 8–14 RSC prefetch requests for visible `<Link>`s (≈1 KB, 25–75 ms each, `perf/prefetch-cost.mjs`).
  Cheap today; it scales with table rows (admin users prefetched one `/admin/users/:id` per row).
- Shell calls on every student page: `me/grants`, `me/notifications?unread_only=true&limit=1`, `me/enabled-apps`.
  Staff layouts fetch `me/grants` server-side (`features/staff-portal/StaffPortalGate.tsx:20`) **and** again client-side
  (`components/shell/PortalSwitcher.tsx:28`), and trainer pages a third time (`features/trainer/shared/grants.ts:21`).

## 3. API

### 3a. Sequential replay (no concurrency) — server time from the api's own `duration_ms` log, joined by request id

Script `perf/api-timing.mjs` (1 warm-up + 7 calls each, through the BFF with the browser's cookies/UA). Raw `perf/api-timing.json`.
BFF overhead (client − server) median **25 ms** (14–136).

| Endpoint (GET) | server p50 ms | client p50 ms |
|---|---|---|
| `me/paths/:allocation_id` | **410** | 546 |
| `assignments?scope=mine&limit=100` (staff) | 235 | 252 |
| `me/dashboard` | 202 | 257 |
| `read/:id` (path article) | 154 | 276 |
| `me/notifications?unread_only=true&limit=1` | 148 | 221 |
| `tests/:id` | 135 | 149 |
| `admin/users` | 98 | 148 |
| `me/enabled-apps` | 96 | 119 |
| `me/tests` | 95 | 117 |
| `studio/tests` | 90 | 111 |
| all others captured (24 more) | 30–87 | 46–119 |

Only `me/paths/:id` exceeds 300 ms when called alone.

### 3b. Same endpoints inside real page loads (parallel calls from one page)

In-page TTFBs were 2–9× the sequential numbers: `me/assignments` 778 ms (87 alone), `me/notifications` 640 ms
(148), `assignments?scope=mine` 742 ms (235), `studio/tests` 664 ms (90), `me/dashboard` 445 ms (202),
`placement/subjects` 737 ms. Log aggregate for 13:12–13:22 UTC (`perf/api-server-times.json`, includes other
agents' traffic): `analytics/reports/batches/:id` p50 1017 ms, `tests/:id/report` p50 739 ms (p95 1642),
`assignments` p95 6.7 s, `admin/dashboard` max 8.4 s, `audit/chain-status` max 22 s.

Likely cause (code-reviewed + pg_stat_statements): every authenticated request first runs the session resolver in its
**own transaction** that starts with `SELECT … FROM auth_sessions WHERE token_hash = $1 FOR UPDATE`
(`apps/api/app/modules/sessions/resolver.py:113-128`), then ~6–9 more statements (user, device hash, restriction,
MFA factors, consents, grants, optional `UPDATE last_seen_at`) before the endpoint's own transaction. Parallel requests
from one tab therefore **queue on the same row lock**. pg_stat_statements since 12:11 UTC: that SELECT ran 1 611 times,
mean **58 ms**, max **3 047 ms**, although EXPLAIN shows it costs 0.13 ms (57 rows; unique index `ux_as_token`).
The `UPDATE auth_sessions SET last_seen_at…` statements show mean 54–79 ms, max 589–674 ms — same signature (lock wait).

### 3c. N+1 patterns

| Where | Pattern | Evidence |
|---|---|---|
| `apps/web/src/features/trainer/components/Insights.tsx:91` (`LiveTests`) | one `GET tests/:id/assignments` per published test, up to `LIVE_SCAN = 25` | automated-tested: 4 calls on `/trainer` with 4 tests |
| `apps/web/src/features/trainer/lib/batches.ts:27` | one `GET batches/:id` per batch grant (batch staff) | code-reviewed (admin takes the single-call branch) |
| `apps/web/src/features/trainer/lib/batches.ts:57-62` (`useMemberNames`) | one `GET batches/:id/members` per batch | code-reviewed |
| `apps/api/app/modules/paths/service.py:1361-1362` (`my_paths`) | `_player()` = 3 queries **per allocation** | code-reviewed |

### 3d. Postgres

- `log_min_duration_statement = 500ms`; `pg_stat_statements` installed (stats reset 12:11 UTC).
- Slow-log (all DBs, last 24 h): almost entirely test-harness `CREATE/DROP DATABASE` (0.5–4.2 s), plus
  `maint.run_partition_maintenance` 1.66 s and one **`UPDATE code_submissions SET status='queued' … WHERE status='running'
  AND started_at < …` that took 37 762 600 ms (10.5 h)** ending 03:35 UTC — the stale-judge sweep in
  `apps/api/app/modules/coding/worker.py:351-355`. Either a lock wait or the host slept; the sweep has no
  `lock_timeout`/`statement_timeout` guard (code-reviewed). No application read query appears in the slow log.
- EXPLAIN (ANALYZE, read-only) of the hottest/most variable reads — batch roster join (mean 110 ms, max 750 ms in
  pg_stat_statements), `auth_sessions` token lookup, path-allocation targeting (`paths/service.py:1202`) — all
  execute in **0.1–0.5 ms** with index scans. The dev data set is tiny (e.g. 57 sessions, 6 notifications), so today's
  latency is per-request overhead + contention, not query plans. Re-check plans with realistic volumes before launch.

## 4. Fonts, images, caching, compression, CSP

| Item | Finding (manually tested with curl unless noted) |
|---|---|
| `/_next/static/*` | `Cache-Control: public, max-age=31536000, immutable`, gzip — correct |
| HTML documents | `private, no-cache, no-store` on all pages; portal pages `no-store` (middleware) — correct for authed pages, but public marketing pages are uncacheable too |
| `/vendor/monaco/**` (14 MB, ~100 files) | `Cache-Control: public, max-age=0` → every coding-page visit revalidates each Monaco file |
| `/favicon.ico` | **404**, rendered as a full dynamic HTML page (`no-store`) on every first visit |
| Compression | gzip only from the Next standalone server; no brotli |
| BFF public catalog (`/api/v1/catalog/courses`) | `public, max-age=300` — good |
| Fonts | **No web fonts are loaded.** Tokens ask for `Plus Jakarta Sans` / `Inter` / `JetBrains Mono` (`packages/design-tokens/tokens.css:8-10`) but nothing ships them, so users get system fonts. Adding the brand font is a redesign requirement and a CLS risk (see P6). |
| Images | No `next/image` anywhere; the only `<img>` is question media (`features/question-bank/components/parts.tsx:176`). No raster images on measured pages (logo is inline SVG). |
| CSP impact | `app/layout.tsx:23` calls `await headers()` so Next can nonce its scripts → **every route is dynamically rendered**, including legal/marketing pages. Sequential TTFB (7 curls): `/` 98–244 ms, `/courses` 127–279 ms, `/login` 111–858 ms, `/legal/terms` 109–510 ms. A static page would be served in single-digit ms and could be CDN-cached. Middleware also runs on every page navigation (nonce + CSRF cookie). |

## 5. Prioritised optimisations

Expected gains are estimates derived from the measurements above, not measured after a change.

| # | Change | Where | Expected gain | Risk |
|---|---|---|---|---|
| P1 | Stop serialising requests on the session row: resolve with a plain `SELECT` (no `FOR UPDATE`), do the idle-slide/`last_seen_at` write as a conditional `UPDATE … WHERE last_seen_at < now() - interval` only when due, and cache the resolved principal briefly (e.g. Redis, keyed by token hash, invalidated by `sessions_valid_after`/revocation) | `apps/api/app/modules/sessions/resolver.py:113-128, 243, 249-276` | In-page API latency back toward the sequential numbers (e.g. `me/assignments` 778 → ~100 ms, `studio/tests` 664 → ~100 ms); fewer DB round-trips per request; LCP −300–700 ms on data-bound pages | **High** — security-critical path (revocation, replay detection, idle timeout). Needs security sign-off + the existing sessions tests. |
| P2 | Remove `/app/analytics` server `redirect()` page; use a `redirects()` entry in `next.config.ts` (already used for `/admin/security`) | `apps/web/src/app/app/analytics/page.tsx:8`, `apps/web/next.config.ts:24-30` | 70 → ~45 requests, 316 → ~190 KB, 3 duplicate shell API calls gone, no double render | Low |
| P3 | Trainer dashboard: replace the per-test N+1 with one call (backend "live assignments for my batches" list, or include assignments in `studio/tests`), and share the `studio/tests` result between `LiveTests` and `TestsList` | `features/trainer/components/Insights.tsx:77-101`, `features/trainer/components/TestsList.tsx:32-38` | `/trainer` 12 → ~6 API calls; scales O(1) instead of O(tests≤25) | Low–Med (backend endpoint) |
| P4 | Request de-duplication / short-lived cache in the client data hooks (in-flight promise map keyed by path+query, e.g. 30 s for `me/grants`, `me/enabled-apps`); pass the server-fetched grants from `StaffPortalGate` to the client instead of refetching | `features/trainer/shared/use-api.ts:24-55`, `features/learning/lib/use-resource.ts:17`, `features/account/lib/use-resource.ts:14`, `components/shell/PortalSwitcher.tsx:28`, `features/trainer/shared/grants.ts:21`, `features/staff-portal/StaffPortalGate.tsx:20`, `features/learning/assignment-manager/AssignmentManagerList.tsx:211` + `features/trainer/components/Grading.tsx:46` (evaluator `assignments?scope=mine` ×2) | Removes all duplicate calls seen in §2 (1–2 per staff page) and the shell refetches | Low (keep `reload()` bypassing the cache) |
| P5 | Fix home CLS 0.179: make the `(public)/loading.tsx` skeleton match the page height or drop it for `/`, and let the anonymous catalog fetch use `revalidate` (it is `cache: "no-store"` today) | `apps/web/src/app/(public)/loading.tsx:2-13`, `apps/web/src/app/(public)/page.tsx:14`, `apps/web/src/lib/api/server.ts:45-47` | CLS 0.179 → ~0 (passes "good" < 0.1); home TTFB −100–400 ms | Low |
| P6 | Ship brand fonts self-hosted with `next/font/local` (Plus Jakarta Sans for display, subset latin, `display: swap`, `adjustFontFallback`) — not via Google Fonts CDN (CSP `font-src` is self) | `apps/web/src/app/layout.tsx`, `packages/design-tokens/tokens.css:8-10` | Brand-correct type with ~0 CLS and ~20–40 KB woff2 per weight instead of an uncontrolled swap | Low |
| P7 | Render primary page data on the server (RSC + existing `serverApiGet`) for the dashboard, paths player, assignments and test landing instead of client `useEffect` fetches | e.g. `features/learning/lib/use-resource.ts` consumers on `/app`, `/app/path/my/[id]`, `/app/assignments`, `/app/tests/[id]` | LCP closer to FCP (today +0.4–2.1 s); fewer client round-trips | Med (larger refactor; overlaps the redesign) |
| P8 | Let public pages be static/CDN-cacheable despite CSP: evaluate Next's `experimental.sri` (hash-based `script-src` + `'strict-dynamic'`) for the `(public)` group, or move the nonce read out of the root layout into portal layouts only | `apps/web/src/app/layout.tsx:20-23`, `apps/web/src/middleware.ts:72-82`, `apps/web/src/lib/security/csp.ts` | Public TTFB 100–500 ms → <20 ms locally, cacheable at the edge; less web-container CPU | Med–High (CSP is a security control; verify with the security agent) |
| P9 | `me/paths/:id` (410 ms alone): profile; the four queries in `player_view` each run < 1 ms on EXPLAIN, so time is spent in resolver/RLS setup or Python tree building; also make `my_paths` load all allocations' versions/rows/progress in 3 batched queries | `apps/api/app/modules/paths/service.py:1315-1330, 1350-1383, 1405-1409` | `me/paths/:id` < 150 ms; `/app/path/my` O(1) queries | Low |
| P10 | Long-cache Monaco: copy it to a versioned path (e.g. `/vendor/monaco-0.52.2/`) in `scripts/copy-monaco.mjs` and add `Cache-Control: public, max-age=31536000, immutable` for `/vendor/:path*` in `headers()` | `apps/web/next.config.ts:20-23`, `apps/web/scripts/copy-monaco.mjs`, `features/coding/components/MonacoEditor.tsx:11` | No revalidation of ~100 files on each coding page visit | Low |
| P11 | Add brand favicons/icons (from `D:\company website\tech drona\dist`) as `app/icon.*` / `favicon.ico` | `apps/web/src/app/` | Removes a dynamic 404 render per visit | Low |
| P12 | Guard the stale-judge sweep with `SET LOCAL lock_timeout` / `statement_timeout` (and investigate the 10.5 h statement) | `apps/api/app/modules/coding/worker.py:351-355` | Prevents a sweep from blocking for hours | Low |
| P13 | Investigate `audit/chain-status` (max 22 s) and `admin/dashboard` (max 8.4 s) outliers — they run on admin-dashboard load | api `audit` / `admin` modules | Admin dashboard tail latency | Unknown (not profiled) |
| P14 | Split the test-runner chunk (`6721-*`, 14.5 KB gz) out of the test *landing* page with `next/dynamic` | `apps/web/src/app/app/tests/[test_id]/page.tsx` | −14 KB gz on `/app/tests/:id` | Low |
| P15 | Brotli at the edge (CloudFront/ALB) for JS/CSS/HTML | infra | ~15–20 % fewer bytes vs gzip (typical; not measured) | Low |
| P16 | Environment: uvicorn workers were being respawned under load and the host had no free RAM; size API memory/workers (2 workers × pool 5+2) before load testing | `docker-compose.yml` api service, `apps/api/app/core/config.py:62-63` | Stable latency for the "after" run | Low |

Not recommended: bundle-size work beyond P14 (routes are already 110–174 KB gz, heavy libraries already lazy).

## 6. What was not measured / limitations

- Course player (no enrolled demo learner; see §2). Real trainer/evaluator/content accounts (device cap; measured as admin).
- Studio question bank with data (admin gets 403).
- Test runner during an attempt (starting an attempt changes shared fixture state; landing page measured instead).
- No mobile/throttled profile; no load test. Numbers are from a contended host — treat absolute ms as upper bounds.

## 7. Reproduce

```
# from repo root; PERF_STATE_DIR keeps sign-in state outside the repo (contains cookies — never commit)
node docs/redesign/perf/bundle-stats.mjs apps/web/.next > docs/redesign/perf/bundle-stats.json
PERF_STATE_DIR=<tmp> node docs/redesign/perf/page-timing.mjs --runs 3            # -> perf/page-timing.json
PERF_STATE_DIR=<tmp> node docs/redesign/perf/api-timing.mjs --n 7 > docs/redesign/perf/api-timing.json
docker compose logs api --since <start-ISO> --no-log-prefix > <tmp>/api.log
node docs/redesign/perf/api-timing.mjs --join docs/redesign/perf/api-timing.json --logs <tmp>/api.log
docker compose logs api --since <ISO> --until <ISO> --no-log-prefix | node docs/redesign/perf/api-log-stats.mjs 3
PERF_STATE_DIR=<tmp> node docs/redesign/perf/cls-sources.mjs anon /             # layout-shift sources
PERF_STATE_DIR=<tmp> node docs/redesign/perf/prefetch-cost.mjs admin /admin/users
```
In Git Bash set `MSYS_NO_PATHCONV=1` so `/paths` are not rewritten. Staff accounts at the device cap: the script
signs in as `admin2@` and `asha.student@` by default (`PERF_STUDENT_AS`, `PERF_ADMIN_AS`, `PERF_STAFF_OWN_ROLE=1`
override) and refuses to replace a device.

Verification labels: bundle sizes, page timings, duplicate/N+1 calls, caching headers, EXPLAIN plans —
**automated-tested / manually-tested (API, curl, psql)**; lock-contention cause and N+1s marked "code-reviewed" —
**code-reviewed**; all gains in §5 — **estimates, not verified**.
