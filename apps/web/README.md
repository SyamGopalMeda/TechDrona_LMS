# apps/web — Tech Drona web app and BFF

Next.js 15.5 (App Router, React 19, TypeScript strict), Tailwind CSS 3.4, ESLint 9, Vitest 3 + Testing Library, Playwright.
The app is also the **same-origin BFF** (ADR-0010): browsers only ever talk to this origin; the FastAPI `api` is private.

## Commands

```bash
npm install
npm run dev        # http://localhost:3000
npm run lint       # eslint, zero warnings
npm run typecheck  # tsc --noEmit
npm test           # vitest (unit + component)
npm run build      # next build (standalone output for the container image)
npm run e2e        # playwright (first time: npx playwright install chromium)
```

Env vars are the `web` ones from the root `.env.example` (put local values in `apps/web/.env.local`):
`TD_API_INTERNAL_URL`, `TD_CSRF_KEY` (+ `_PREVIOUS`), `TD_SERVICE_TOKEN`, `TD_PUBLIC_BASE_URL`,
`TD_BFF_PROXY_TIMEOUT_MS`, `TD_ORIGIN_VERIFY_HEADER`, `NEXT_PUBLIC_*`. Two web-only additions:

| Var | Default | Meaning |
|---|---|---|
| `TD_TRUSTED_PROXY_HOPS` | `0` | Number of our own proxies appending to `X-Forwarded-For` after the client (CloudFront → ALB → web = `1`). Also enables `CloudFront-Viewer-Address`. `0` means no trusted proxy: the client IP is unknown and the BFF forwards none (forwarding headers are browser-supplied and ignored, SEC-01). |
| `TD_COOKIE_SECURE` | unset | Outside production, `true` switches to the `__Host-` cookie names (needs https, e.g. `next dev --experimental-https`). |

## BFF (`src/app/api/v1/[...path]/route.ts` → `src/lib/bff/proxy.ts`)

Every `/api/v1/*` request from the browser:

1. **Exclusions** — `/api/v1/webhooks/*` → `404` (the ALB routes webhooks straight to `api-webhooks`; they never pass through the BFF and carry no cookies/CSRF). `/api/v1/auth/remember/refresh` (AUTH-28, BFF-internal) → `404`. `_`-prefixed paths are BFF-local (`GET /api/v1/_bff/csrf` re-issues the CSRF cookie; `_errors` tunnel is not implemented yet → 404). Path traversal / encoded separators → `404`.
2. **Unsafe methods** (`POST/PUT/PATCH/DELETE`): Fetch Metadata (`Sec-Fetch-Site` ∈ {`same-origin`,`none`}; if absent, `Origin` must equal `TD_PUBLIC_BASE_URL`, `null` rejected) → JSON-only body (`415`) within 256 KiB (64 KiB for `analytics/*`, `413`) → signed double-submit CSRF (`X-CSRF-Token` == CSRF cookie and HMAC-valid for the presented session) → else `403 csrf_failed`. The beacon route `analytics/events/beacon` takes the token from the body field `csrf`, requires `Sec-Fetch-Site: same-origin`, accepts `text/plain`, and strips `csrf` before forwarding.
3. **Upstream headers** — allow-list only (`accept`, `content-type`, `idempotency-key`, `if-match`, `user-agent`, client hints, …). Browser-sent `Cookie`, `Authorization`, `X-Forwarded-*`, `X-TD-*`, `X-Request-Id`, `traceparent` are dropped. The BFF adds `Authorization: Service <TD_SERVICE_TOKEN>`, `X-TD-Session`, `X-TD-Device` (also as canonical `__Host-` cookies), `X-TD-Client-IP` (+ rebuilt `X-Forwarded-For`), `X-Request-Id` (UUIDv7), `traceparent`, and `X-TD-Activity: navigation` only for real top-level navigations (never prefetch).
4. **Response** — hop-by-hop and encoding headers stripped, body streamed (SSE unbuffered, no timeout), `X-Request-Id` and `Cache-Control: no-store` ensured. `Set-Cookie` from the api is accepted only for `td_session`/`td_device`/`td_remember` and re-issued under this environment's name with `HttpOnly; SameSite=Lax; Path=/` (+`Secure` in prod). Whenever the session cookie is set/rotated/cleared — or the CSRF cookie is missing/stale/signed with the previous key — a new CSRF token is minted.
5. Upstream unreachable/timeout → `503 service_unavailable` problem+json with `request_id`.

**CSRF token** (`src/lib/bff/csrf.ts`): `v1.<nonce>.<HMAC-SHA256(TD_CSRF_KEY, "td-csrf|v1|" + binding + "|" + nonce)>`, binding = `s:` + SHA-256(session cookie) or `anon` before login. `TD_CSRF_KEY_PREVIOUS` verifies during rotation. The key exists only in `web`. Cookie is not HttpOnly (`SameSite=Strict`) so the client can echo it. Middleware issues it on page loads; the client calls `/api/v1/_bff/csrf` if missing and retries once on `csrf_failed`.

**Cookie names — dev vs prod**

| | `NODE_ENV=production` | dev (`next dev`, `TD_COOKIE_SECURE`≠`true`) |
|---|---|---|
| session / device / remember | `__Host-td_session` / `__Host-td_device` / `__Host-td_remember` | `td_session` / `td_device` / `td_remember` |
| CSRF | `__Host-td_csrf` | `td_csrf` |
| `Secure` attribute | yes | no (browsers refuse `Secure`/`__Host-` on http://localhost) |

The api always sees canonical `__Host-` names / `X-TD-*` headers regardless of mode. Production refuses to boot the BFF with a placeholder `TD_CSRF_KEY`. Note: `next start` on plain http locally uses the production names, which browsers will not store; use `next dev` or https.

## Security headers

`src/middleware.ts` sets a per-request nonce CSP (`script-src 'self' 'nonce-…' 'strict-dynamic'`, VdoCipher frames only, `object-src 'none'`, `base-uri 'none'`, `frame-ancestors 'none'`; `'unsafe-eval'`/`ws:` only in dev). The root layout reads request headers, so all pages render dynamically (required for nonces). `next.config.ts` adds nosniff, Referrer-Policy, X-Frame-Options, Permissions-Policy, COOP.

Portal routes (`/app`, `/trainer`, `/evaluator`, `/mentor`, `/studio`, `/desk`, `/finance`, `/security`, `/admin`; in single-company mode the mentor, desk, finance and security sections are part of the Admin portal) require a session cookie to be **present** (middleware + `PortalShell`), else `/login?next=…`; they are `Cache-Control: no-store`. This is UX only: the api authorises everything. Aliases: `/admin/security/*` → `/security/*`, `/verify/certificate/:id` → `/verify/:id` (PRD prefixes are canonical).

## API client (`src/lib/api/client.ts`)

`api.get<T>()` returns data; `api.post/put/patch/delete<T>()` return `{kind:"ok", data, requestId, etag}` or `{kind:"approval_pending", approval}` (202 dual control). Options: `idempotencyKey: true` (UUIDv7, reused on retries), `ifMatch`, `query`, `handle` (opt out of global handling). Errors throw `ApiError` (`status`, `code`, `requestId`, `problem`, user-safe `title`/`detail`). Global handling: `step_up_required` → step-up dialog (TOTP implemented; passkey not yet) then one retry with the same Idempotency-Key; `account_restricted` → `/account/restricted?case_ref&level&until`; `unauthenticated|session_expired|session_revoked` → `/login?next&reason`; `login_incomplete` → `/login/mfa|verify-device|session-choice`; `session_cap_reached` → `onSessionChoiceRequired` hook or `/login/session-choice`; `playback_conflict` → `onPlaybackConflict` hook (then throws). Server components use `serverApiGet()` (`src/lib/api/server.ts`), which calls the api directly with the same BFF headers.

## Activity analytics (`src/lib/analytics`)

Client side of tm-1.0: `EngagementMeter` (ACTIVE/IDLE/HIDDEN on a monotonic clock, `credit = min(gap, T_idle)`), `ActivityTracker` (page.view/hide, visibility/focus/idle events, 15 s engaged heartbeats, 5 min keepalives, flush every 30 s and on every state change, UUIDv7 event ids with monotonic counter, per-page `seq`, batches ≤ 100 events/60 KiB, retry with backoff on network/429/5xx), transport to `POST /api/v1/analytics/events` (CSRF header) and `sendBeacon` to `/api/v1/analytics/events/beacon` on `pagehide` (CSRF in body). Use `useActivityTracker({ route: "/app/learn/[course_slug]/[lesson_id]", surface: "lesson_text", entity })` — `route` must be a template. Not yet: IndexedDB queue (in-memory only), video/coding events, `GET /analytics/config` response shape is assumed (see `config.ts`).

## Design tokens

`tailwind.config.ts` always applies the local fallback preset (`src/styles/fallback-tokens/`, generated once from `packages/design-tokens/tokens.json` v1.0.0) and layers `packages/design-tokens/tailwind-preset.js` on top when present; `globals.css` imports the fallback CSS then `packages/design-tokens/tokens.css`. Both upstream files exist now, so the UX tokens win. To drop the fallback, remove it from `presets` and the first `@import`. Fonts are system fallbacks (no font download at build time).

## E2E against the container stack

`E2E_BASE_URL=http://localhost:13000 E2E_INTEGRATION=1 npx playwright test --project=chromium --workers=1`
(env names: `E2E_STUDENT_*`, `E2E_RESTRICTED_*`, `E2E_EVALUATOR_*`, `E2E_TRAINER_*`, `E2E_REVIEWER_A_*/_B_*` with `_TOTP_SECRET`, `E2E_L4_CASE_ID`, `E2E_TEST_ID`, `E2E_FREE_COURSE_SLUG`). Shared helpers live in `e2e/support/` (`signIn` handles MFA, device OTP via Mailpit, the device-cap chooser and the session chooser; `audit` is the axe WCAG 2.1 A/AA check, failing on serious/critical; `resumeIfAsked` answers TST-004).

- Every browser context is a new *device* (3-device cap), so `signIn` reuses one device cookie per account from `.e2e-devices/` (gitignored; Playwright wipes `test-results/`). Run with `--workers=1`: specs share seeded accounts.
- The seeded `student@` is both the restricted fixture and the learner. Order: restricted specs (`identity` restricted test, `restricted-direct-api` SCN-13, restricted a11y) → `security-console` (lift) → `reverify` (SCN-10) → learner specs (`student-learning`, `multi-tab` SCN-02, `learning-commerce`, student a11y).
- Load smoke: `tests/load/` (k6 via the `grafana/k6` image). QA results: `docs/qa-report-e2e.md`.

## Extending (portal agents)

- Pages: replace the `NotImplemented` placeholder in `src/app/<prefix>/…/page.tsx`; keep the PRD screen id. Add nav entries in `src/lib/nav/portals.ts`.
- UI: import from `@/components/ui` (Button, Input, Select, Checkbox, FormField + `fieldErrors`, Dialog, ToastProvider/useToast, Table, Tabs, Badge, Card, Skeleton, EmptyState, ErrorState, Pagination + cursor-stack helpers, StatTile, PageHeader). Colours only via semantic token classes.
- Data: client → `api.*`; server components → `serverApiGet()`; pass explicit DTO fields to client components only.
- The test runner (`/app/attempts/[attempt_id]`) currently sits inside the student shell; the assessments agent may give it its own layout.
