# Audit — Frontend (learner + public pages): code quality, UX, responsiveness, a11y

Area key: `frontend` · Prefix: `FE-` · Phase A (audit only) · 2026-11-03
Method: static code review (CodeGraph + grep), cross-check of every BFF path against `apps/api` routers / `apps/web/openapi/openapi.json`, unit tests, lint, typecheck, one probe test. No running-stack browsing (E2E agent's area). Staff portals out of scope.

## Tooling results (real)

| Command (in `apps/web`) | Result |
|---|---|
| `npm run lint` (`eslint . --max-warnings=0`) | exit 0, no warnings |
| `npm run typecheck` (`tsc --noEmit`) | exit 0 |
| `npx vitest run` | 36 files / 345 tests: **343 passed, 2 failed — both timeouts** (`auth.test.tsx` "SignupForm applies the under-18 gate" 5075 ms; `security-admin.test.tsx` "Case detail decision panel" 5140 ms). Running the 2 files alone: 4 timeouts. With `--testTimeout=30000`: `auth.test.tsx` 12/12 pass. These are **slow tests under load, not logic failures** (see FE-24). The count includes the audit probe `src/__audit_scratch__/fe-retry-after.probe.test.ts` (passes). |
| Bundle (existing `.next` build, uncompressed JS per route from `app-build-manifest.json`) | heaviest learner route `/app/tests/[test_id]` 423 KB, `/app/learn/...` 415 KB, attempts 408 KB, public `/unblock-request` 402 KB (mostly shared framework). Monaco and recharts are lazy-loaded. No issue raised. |

## Feature / coverage inventory

| Feature/Req ID | Requirement source | Code location | Audit method | Result |
|---|---|---|---|---|
| PUB-001 Home | sitemap §2 | `app/(public)/page.tsx` | code review | Verified OK (live catalog, no invented numbers) |
| PUB-002/003 Catalog, course detail | sitemap §2 | `features/catalog` | code + API path check | Verified OK (empty/error states, notFound, metadata) |
| PUB-004/005 Placement hub/topic | sitemap §2 | `app/(public)/placement/**` | code | Not built (FE-01) |
| PUB-006/007 Companies | sitemap §2 | `app/(public)/companies/**` | code | Not built (FE-01) |
| PUB-008 Pricing | sitemap §2 | `PricingPlans.tsx` | code | Issue (FE-21) |
| PUB-009 Free resources / PUB-010 Colleges | sitemap §2 | `app/(public)/free-resources`, `colleges` | code | Not built (FE-01) |
| PUB-011 Signup | PRD, sitemap | `SignupForm.tsx` | code + tests | Issue (FE-02, FE-10, FE-22) |
| PUB-012 Login + MFA/device/session-choice | PRD | `features/auth` | code + tests + probe | Issue (FE-09, FE-12) |
| PUB-013/014/015 Recovery, verification, guardian | PRD | `features/auth` | code | Verified OK |
| PUB-016 College invite | sitemap §2 | `app/(public)/invite/[token]` | code | Not built (FE-03) |
| PUB-017 Certificate verify | sitemap §2 | `verify/[certificate_id]` | code | Issue (FE-13) |
| PUB-018 Legal pages | sitemap §2 | `app/(public)/legal/*` | code | Not built (FE-01/FE-02) |
| PUB-019 Help / PUB-020 Status | sitemap §2 | `help/**`, `status` | code | Not built (FE-01, FE-14) |
| PUB-021 Account restricted / Unblock request | account-unblock-workflow | `features/unblock` | code | Issue (FE-15) |
| Public footer/header | sitemap §2 footer | `PublicShell.tsx` | code | Issue (FE-11) |
| STU-001 Dashboard | sitemap §3 | `StudentDashboard.tsx` | code | Partial (FE-23) |
| STU-002/003/006/011/015/024/027/028 | sitemap §3 | `app/app/{onboarding,diagnostic,path,analytics,interview-prep,notifications,college,bookmarks}` | code | Not built (FE-05) |
| STU-026 Account status | sitemap §3, unblock workflow | `app/app/account-status/page.tsx` | code | Issue (FE-04) |
| STU-004/005 Learning, course overview | sitemap §3 | `features/learning` | code | Verified OK |
| PLY-001..005 Player, watermark, conflict | PRD, ADR | `features/player` | code + API check | Verified OK (watermark via VdoCipher OTP `annotate`, `media/providers.py:136-150`); Issue FE-08, FE-19 |
| PRC-001..005 Practice | sitemap §3 | `features/practice` | code | Verified OK (tracker gap FE-07) |
| TST-001..005, STU-010 Tests | PRD, blueprint | `features/assessment` | code + tests | Verified OK for saving/timer/keys; Issue FE-06, FE-18, FE-20 |
| Unsaved answers in IndexedDB | blueprint/PRD | `features/assessment/lib/local-store.ts` | code + tests | Verified OK (IDB + localStorage write-ahead, beforeunload, offline banner, idempotent submit); Issue FE-17 |
| No answer keys in client before submit | security-threat-model | `bank.py:720-745` `QuestionDelivery`, review gated `attempts.py:1367-1485` | code | Verified OK |
| Server-clock timer + aria-live | PRD §5.11 | `server-clock.ts`, `RunnerParts.tsx` | code + tests | Verified OK |
| COD-001..003 Coding | sitemap §3 | `features/coding` | code | Verified OK (Monaco lazy, <768px notice) |
| COD-004 Coding inside test | sitemap §3 | `CodingQuestion.tsx` | code | Issue (FE-06) |
| Analytics tracker (heartbeats, visibility, video.*) | analytics-event-schema | `lib/analytics/*` | code vs schema | Issue (FE-07, FE-08, FE-16) |
| STU-012 certificates, STU-018/019 billing/access | sitemap §3 | `features/commerce` | code + API check | Verified OK; Issue FE-26 |
| STU-016/017 Checkout, orders | sitemap §3, COM-* | `Checkout.tsx`, `OrderStatus.tsx` | code + API check | Issue (FE-25 merged into FE-26, FE-27, FE-28) |
| STU-020..023 Settings | sitemap §3 | `features/account` | code + API check | Issue (FE-29, FE-31) |
| STU-025 Support | sitemap §3 | `StudentSupport.tsx` | code | Issue (FE-30) |
| Problem+json handling, step-up MFA | implementation-conventions | `lib/api`, `Providers.tsx:22` | code + tests | Verified OK |
| Dialog focus / toasts aria-live | design-system | `components/ui` (native `<dialog>` showModal; toast `aria-live=polite`) | code | Verified OK |
| Design tokens / no stray hex | design-system | all learner+public tsx | grep `#[0-9a-f]{3,8}` | Verified OK (0 hits); a few arbitrary `h-[48px]`/`max-w-[480px]` only |
| Tables at 360 px | design-system | `components/ui` Table (`overflow-x-auto`) | code | Verified OK |
| Mobile nav | sitemap §3 (bottom tabs) | `PortalShell.tsx:36` | code | Issue (FE-32) |
| RichHtml XSS | threat model | `RichHtml.tsx` + `placement/richtext.py:113` sanitize on write | code | Verified OK (sanitised server-side + nonce CSP) |
| Secrets in client bundle | threat model | `NEXT_PUBLIC_*` = APP_NAME, APP_VERSION, NOTICE_VERSION, BASE_URL only | grep | Verified OK |
| Caching of user data | Next.js | middleware `no-store`, root layout `await headers()` (dynamic) | code | Verified OK |
| 404 / error / loading | Next.js | `app/not-found.tsx`, `app/error.tsx` | code | Issue (FE-33) |
| Lint / typecheck / unit tests | — | `apps/web` | run | lint OK, tsc OK, 2 timeouts (FE-24) |

---

## Findings

### FE-01: 14 public pages are "Not yet implemented" placeholders
- Severity: High
- Status: Confirmed
- Component: `app/(public)/{colleges,companies,companies/[slug],free-resources,help,help/[article],invite/[token],status,placement,placement/[subject]/[topic],legal/terms,legal/privacy,legal/refund-policy,legal/device-policy}/page.tsx`
- Requirement: sitemap §2 PUB-004..010, PUB-016, PUB-018..020
- Repro: `grep -rl NotImplemented "apps/web/src/app/(public)"`
- Expected / Actual: real pages / each renders `<NotImplemented screen="PUB-0xx"/>` (e.g. `legal/terms/page.tsx:7`).
- Evidence: grep lists all 14 files. Backend already serves some: `GET /catalog/free-resources` (catalog router), `GET /invitations/{token}` + `/accept` (orgs/router.py:843, 911), `GET /placement/subjects` (placement/router.py:69).
- Root cause: screens deferred.
- Recommended fix: build legal (static content), invite, help/grievance first; then placement/companies/free-resources on existing APIs.
- Suggested owner paths: `apps/web/src/app/(public)/**`, `apps/web/src/features/catalog`

### FE-02: Signup records consent to Terms/Privacy that link to placeholder pages
- Severity: High
- Status: Confirmed
- Component: `features/auth/components/SignupForm.tsx` (~247-256) → `/legal/terms`, `/legal/privacy`
- Requirement: privacy-and-data-retention (informed consent, notice version), PUB-018
- Expected / Actual: user can read the notice they accept / the pages say "Not yet implemented"; consent is recorded against `NEXT_PUBLIC_NOTICE_VERSION` nobody can read.
- Evidence: links in SignupForm; `legal/*/page.tsx` render NotImplemented.
- Recommended fix: publish legal pages (FE-01) before launch.
- Suggested owner paths: `apps/web/src/app/(public)/legal/*`

### FE-03: College invite flow (PUB-016) cannot be completed
- Severity: High
- Status: Confirmed
- Component: `app/(public)/invite/[token]/page.tsx`
- Requirement: sitemap §2 PUB-016
- Expected / Actual: show invite + data-sharing notice, create/link account / placeholder; `SignupForm` accepts `?invite=` but nothing routes there.
- Evidence: page renders NotImplemented; API `GET /invitations/{token}`, `POST /invitations/{token}/accept` exist (orgs/router.py:843, 911).
- Recommended fix: implement the page on those endpoints.
- Suggested owner paths: `apps/web/src/app/(public)/invite/[token]/page.tsx`, `apps/web/src/features/auth`

### FE-04: Restricted learners are redirected to a placeholder Account Status page
- Severity: High
- Status: Confirmed
- Component: `app/app/account-status/page.tsx:7`; `features/auth/lib/login-flow.ts:22`
- Requirement: sitemap §3 STU-026, account-unblock-workflow
- Expected / Actual: restriction details, case, link to unblock request / `<NotImplemented title="Account status" screen="STU-026"/>`.
- Evidence: `login-flow.ts:22` `if (r && r.level >= 3) return safeNextPath(res.redirect, "/app/account-status")`; also linked from `AccessList.tsx:48`, `learning/components/States.tsx:70`, `lib/nav/portals.ts:57`. `GET /me/security/status`, `GET /me/security/cases/{case_ref}` exist in openapi.json.
- Root cause: screen deferred while redirects were wired.
- Recommended fix: build STU-026 on those endpoints with a link to `/unblock-request`.
- Suggested owner paths: `apps/web/src/app/app/account-status/page.tsx`, `apps/web/src/features/account`

### FE-05: Eight learner screens are placeholders (some linked from nav)
- Severity: Medium
- Status: Confirmed
- Component: `app/app/{onboarding,diagnostic,path,analytics,interview-prep,notifications,college,bookmarks}/page.tsx`
- Requirement: sitemap §3 STU-002/003/006/011/015/024/027/028
- Evidence: each renders `<NotImplemented>`. APIs exist for several: `/me/notifications` (+ read, read-all), `/me/orgs` GET/PATCH, `/me/recommendations`. Analytics is in the nav (`portals.ts:51`) and reuses screen id STU-011 also used by Progress (`portals.ts:49`).
- Recommended fix: build on existing APIs or hide nav entries until built.
- Suggested owner paths: those pages, `apps/web/src/lib/nav/portals.ts`

### FE-06: Coding questions inside timed tests render as an empty radio list (COD-004)
- Severity: High
- Status: Confirmed
- Component: `features/assessment/components/QuestionView.tsx:27-32`; `features/coding/components/CodingQuestion.tsx:6` (unused)
- Requirement: sitemap §3 COD-004
- Expected / Actual: coding editor embedded in the runner / QuestionView only branches on `mcq_multi`, `numeric`, `fill_blank`; everything else falls into the radio fieldset. `CodingQuestion` is imported nowhere.
- Evidence: grep for `CodingQuestion` finds only its definition; API delivers `coding_problem_id` (`apps/api/app/modules/placement/bank.py:736-745`).
- Recommended fix: in QuestionView, when `question.coding_problem_id` is set render `<CodingQuestion attemptId=… />`.
- Suggested owner paths: `apps/web/src/features/assessment/components/QuestionView.tsx`

### FE-07: Activity tracker (heartbeats/visibility) not mounted on practice, test-attempt or coding surfaces
- Severity: High
- Status: Confirmed
- Component: `useActivityTracker` used only in `features/dashboard/components/StudentDashboard.tsx:21` and `features/learning/components/LessonView.tsx:269`
- Requirement: analytics-event-schema §M5 (practice/test/coding are LearningSurfaces); `lib/analytics/time-model.ts:17-21` already types `practice`, `test`
- Expected / Actual: heartbeats from all learning surfaces / none from practice, attempts, coding → learning-time (H-reports) under-counts.
- Evidence: grep `useActivityTracker` → 2 call sites.
- Recommended fix: mount tracker in `PracticeSession`, `AttemptRunner` (with `test_attempt_id`, `question_id`), `CodingWorkspace` (`coding_problem_id`).
- Suggested owner paths: `apps/web/src/features/{practice,assessment,coding}/components/*`

### FE-08: `video.*` events and `played_ranges` never emitted
- Severity: Medium
- Status: Confirmed
- Component: `lib/analytics/use-activity-tracker.ts:45-61` (returns `handle.video`); `features/player/.../VideoPlayer.tsx:57-86`; `LessonView.tsx:269` ignores return value
- Requirement: analytics-event-schema §2.2 (video.play/pause/seek/rate_change/ended/buffering/error), §3.9 unique coverage
- Expected / Actual: player maps provider events to tracker / VideoPlayer reports only playing/not-playing.
- Evidence: no calls to `.video.play`/`seek`/etc. anywhere in `src`. Completion still works (server takes max with MED-05 heartbeat, `learning/service.py:343-346`).
- Recommended fix: pass `tracker.video` into VideoPlayer and map VdoCipher events.
- Suggested owner paths: `apps/web/src/features/player`, `apps/web/src/features/learning/components/LessonView.tsx`

### FE-09: Login/signup throttle countdown ignores `Retry-After` header
- Severity: Medium
- Status: Confirmed (probe)
- Component: `features/auth/lib/errors.ts:31` `retryAfterSeconds`
- Requirement: PUB-012 throttled state
- Repro: `npx vitest run src/__audit_scratch__/fe-retry-after.probe.test.ts`
- Expected / Actual: countdown + disabled submit / helper reads only the body; API sends wait only in header (identity/router.py:476, 488) → returns null, no countdown, Sign in stays enabled.
- Evidence: probe passes asserting `err.retryAfter === 600` and `retryAfterSeconds(err) === null`.
- Recommended fix: fall back to `err.retryAfter`.
- Suggested owner paths: `apps/web/src/features/auth/lib/errors.ts`

### FE-10: `?next=` lost through signup
- Severity: Medium
- Status: Confirmed
- Component: `app/(public)/signup/page.tsx` (reads only `invite`); `CourseAccess` links `/signup?next=…`; post-signup result links to `/app`
- Expected / Actual: return to course/checkout / always lands on `/app`.
- Recommended fix: thread `next` through signup (validated with existing `safeNextPath`).
- Suggested owner paths: `apps/web/src/app/(public)/signup/page.tsx`, `features/auth/components/SignupForm.tsx`

### FE-11: Public footer/header do not match sitemap
- Severity: Medium
- Status: Confirmed
- Component: `components/shell/PublicShell.tsx`
- Requirement: sitemap §2 footer list
- Expected / Actual: Courses · Placement · Companies · Pricing · For colleges · Help · Status · Terms · Privacy · Refund · Device · Grievance officer · Certificate verification / only Terms, Privacy, Refund, Device, Help, Status. Header has no Sign up link and always shows "Log in" even when signed in.
- Recommended fix: add missing links; session-aware header CTA.
- Suggested owner paths: `apps/web/src/components/shell/PublicShell.tsx`

### FE-12: Passkey and Google sign-in not built
- Severity: Medium
- Status: Confirmed
- Component: `features/auth/components/LoginForm.tsx:18`, `MfaForm.tsx:17` (comments: passkey/Google/SMS "not in this build"); `SecuritySettings.tsx:264` passkeys "coming soon"
- Requirement: sitemap §2 PUB-012, STU-021
- Recommended fix: implement or formally descope in PRD.
- Suggested owner paths: `apps/web/src/features/auth`, `features/account`

### FE-13: No `/verify` page to type a certificate code
- Severity: Medium
- Status: Confirmed
- Component: only `app/(public)/verify/[certificate_id]/page.tsx`
- Requirement: sitemap §2 footer "Certificate verification"
- Expected / Actual: employer can enter an id / only reachable by direct link.
- Recommended fix: add `/verify` with a GET form.
- Suggested owner paths: `apps/web/src/app/(public)/verify/page.tsx`

### FE-14: No reachable grievance officer / contact page
- Severity: Medium (compliance)
- Status: Confirmed
- Component: `features/unblock/components/UnblockStatus.tsx:149` falls back to `/help/grievance` (placeholder)
- Requirement: sitemap §2 PUB-019 "contact, grievance officer"
- Recommended fix: static grievance officer page (part of FE-01).
- Suggested owner paths: `apps/web/src/app/(public)/help/**`

### FE-15: Unblock request lacks attachments and draft autosave
- Severity: Medium
- Status: Confirmed
- Component: `features/unblock/components/UnblockRequestForm.tsx` (comment: UNB-02/UNB-03 not in this build); `UnblockStatus.tsx:261` sends `attachment_ids: []`
- Requirement: account-unblock-workflow UNB-02, UNB-03
- Evidence: API has `POST /security/unblock-requests/{id}/attachments`.
- Recommended fix: wire upload + local draft.
- Suggested owner paths: `apps/web/src/features/unblock/components/*`

### FE-16: Required client events not emitted (practice.question_viewed, coding.editor_focus/blur, reading.max_scroll_depth_pct)
- Severity: Medium
- Status: Confirmed
- Component: `lib/analytics/*` (client only emits `page.*` and `video.*` names)
- Requirement: analytics-event-schema (lines ~254, ~280, reading section)
- Evidence: grep for those names in `apps/web/src` → no hits.
- Recommended fix: emit via tracker on the respective surfaces.
- Suggested owner paths: `apps/web/src/lib/analytics`, `features/{practice,coding,learning}`

### FE-17: Unsynced answers and attempt flags persist on device after sign-out
- Severity: Low
- Status: Suspected
- Component: `components/shell/SignOutButton.tsx`; `features/assessment/lib/local-store.ts:48` (14-day retention); `td.attempt.integrity.*` keys never removed
- Expected / Actual: shared-PC hygiene clears local attempt data on logout / not cleared.
- Recommended fix: clear `td-assessment` IDB store and `td.attempt.*` keys on sign-out (after warning if unsynced).
- Suggested owner paths: `apps/web/src/components/shell/SignOutButton.tsx`, `features/assessment/lib/local-store.ts`

### FE-18: Test runner bottom action bar likely overflows at 360 px
- Severity: Low
- Status: Suspected
- Component: `features/assessment/components/AttemptRunner.tsx:606-627`
- Evidence: "Clear response", "← Previous", "Save & next →" (`md` buttons, `px-4`, `text-sm`) in one non-wrapping flex row; estimated ~395 px content.
- Recommended fix: `flex-wrap` or icon-only Prev/Next below `sm`.
- Suggested owner paths: same file

### FE-19: Playback slot not released on tab close
- Severity: Low
- Status: Confirmed
- Component: `features/player/.../use-playback-session.ts:57-61` (stop only on unmount)
- Requirement: single-stream limit / PLY-005
- Expected / Actual: `pagehide` sends stop with `keepalive` / slot held until server stale timeout → spurious conflict on another device.
- Suggested owner paths: `use-playback-session.ts`

### FE-20: "Time's up" overlay is not modal; palette dialog title wrong in free-navigation
- Severity: Low
- Status: Confirmed
- Component: `AttemptRunner.tsx:728-735` (`role="alert"` div; Prev/Next/palette remain focusable and enabled); `AttemptRunner.tsx:635` titles dialog `Questions — {section.title}` while listing all sections. Also `FocusShell` (`:741`) overlays but does not `inert` the portal nav beneath.
- Recommended fix: native `<dialog>.showModal()` or `inert` on content; neutral dialog title.
- Suggested owner paths: `AttemptRunner.tsx`

### FE-21: Pricing shows raw markdown
- Severity: Low
- Status: Confirmed
- Component: `features/catalog/.../PricingPlans.tsx` prints `description_md` as text.
- Suggested owner paths: same

### FE-22: Focus lost after successful signup
- Severity: Low
- Status: Confirmed
- Component: `SignupForm.tsx` `SignupResult` — `headingRef` created but never focused.
- Suggested owner paths: same

### FE-23: Dashboard partial vs PRD
- Severity: Low
- Status: Confirmed
- Component: `StudentDashboard.tsx:79` ("Upcoming tests are not shown here yet"); no recommendations; no first-run redirect to onboarding.
- Suggested owner paths: `features/dashboard`

### FE-24: Two unit tests time out at the 5 s default under load
- Severity: Low
- Status: Confirmed (flaky, not logic)
- Component: `features/auth/components/auth.test.tsx` (SignupForm), `features/security-admin/components/security-admin.test.tsx` (SEC-003, staff area)
- Evidence: full run 343/345 pass, both failures "Test timed out in 5000ms"; isolated run 4 timeouts; `--testTimeout=30000` → auth 12/12 pass in 14.8 s.
- Recommended fix: raise per-test timeout for these long user-event flows or split them.
- Suggested owner paths: those test files / `vitest.config.ts`

### FE-26: Pending orders can never be resumed for payment
- Severity: Medium
- Status: Confirmed
- Component: `features/commerce/components/OrderStatus.tsx:62, 94-95, 108-115`; API `apps/api/app/modules/commerce/router.py:175-198`
- Expected / Actual: `/app/checkout/[order_id]` resumes payment / backend `GET /commerce/orders/{id}` never returns `checkout`, so UI always shows "Resuming payment … is not available yet" and "Complete payment" never appears.
- Recommended fix: return checkout payload for unexpired pending orders (or add re-open endpoint).
- Suggested owner paths: `apps/api/app/modules/commerce/router.py`, `OrderStatus.tsx`

### FE-27: Checkout stays at `/app/checkout/new`; reload creates duplicate order
- Severity: Medium
- Status: Confirmed
- Component: `features/commerce/components/Checkout.tsx:128-131` (`idempotencyKey: true` → fresh uuid7 per call, `lib/api/client.ts:145`)
- Requirement: sitemap line 306 (redirect to `/app/checkout/[order_id]`)
- Recommended fix: `router.replace` to `/app/checkout/{order_id}` after create (depends on FE-26).
- Suggested owner paths: `Checkout.tsx`

### FE-28: Order status shows "Confirming your payment…" for never-paid orders
- Severity: Low
- Status: Confirmed
- Component: `OrderStatus.tsx:103-105` (polls 15 min on `pending_payment` regardless of `message`)
- Recommended fix: "Awaiting payment" when `message` is null. Also `Billing.tsx:275` grace-period copy "update your payment method" has no action.
- Suggested owner paths: `OrderStatus.tsx`, `Billing.tsx`

### FE-29: No self-serve data export / deletion / per-college sharing in privacy settings
- Severity: Medium (DPDP rights)
- Status: Confirmed
- Component: `features/account/components/PrivacySettings.tsx:88-90` ("contact support")
- Requirement: sitemap STU-023 "export, deletion"; privacy-and-data-retention
- Evidence: API has `GET/POST /me/privacy-requests`, `/{id}/export`, `/{id}/withdraw`, `PATCH /me/orgs/{org_id}`.
- Suggested owner paths: `PrivacySettings.tsx`

### FE-30: Support ticket id not URL-encoded in API paths
- Severity: Low
- Status: Confirmed
- Component: `features/support/components/StudentSupport.tsx:227, 241, 252` (`support/tickets/${ticketId}/…` from raw route param)
- Expected / Actual: `encodeURIComponent` like other modules / raw; a crafted `..`-containing id could hit other same-user BFF paths (still the user's own session; low impact).
- Suggested owner paths: same file

### FE-31: Profile cannot change email/mobile; résumé PDF export "coming soon"
- Severity: Low
- Status: Confirmed
- Component: `ProfileSettings.tsx:117`, `features/mentor/student/Resume.tsx:244`
- Suggested owner paths: same

### FE-32: Mobile nav is a `<details>` Menu, not the specified bottom tabs; no portal switcher
- Severity: Low
- Status: Confirmed
- Component: `components/shell/PortalShell.tsx:36-41`; header has only app name, portal badge, SignOutButton (no avatar/portal switcher, FR-RBAC-002). Player and coding run inside the portal chrome rather than the "focus shell" of sitemap §1 (only the test runner uses `FocusShell`). `PortalShell` redirect uses `next=<portal prefix>` and drops the deep link (middleware keeps it, so only the prefetch path is affected).
- Recommended fix: bottom tab bar (Home · Learn · Practice · Tests · More) below `lg`; avatar menu with granted portals.
- Suggested owner paths: `apps/web/src/components/shell/PortalShell.tsx`

### FE-33: 404/error/loading coverage thin; internal screen IDs shown to users
- Severity: Low
- Status: Confirmed
- Component: `app/not-found.tsx` (no shell, unstyled link); no `loading.tsx` or segment `error.tsx` anywhere, no `global-error.tsx`; no `robots.ts`/`sitemap.ts` for public SEO. Screen IDs ("PUB-021 · Account status" at `account/restricted/page.tsx:27`, `eyebrow="STU-013"` at `app/app/mentoring/page.tsx:11`, auth cards) rendered as visible text. `app/app/courses/page.tsx` lacks `metadata`.
- Recommended fix: branded 404 inside PublicShell, `loading.tsx` for `(public)` and `app`, remove screen IDs from UI, add robots/sitemap.
- Suggested owner paths: `apps/web/src/app/**`

### FE-34: Minor code-quality duplication
- Severity: Low
- Status: Confirmed
- Component: three near-identical `use-resource.ts` (`features/{account,learning,assessment}/lib`); learner résumé/mentoring import `@/features/trainer/shared/use-api` (cross-portal coupling); API `recovery_url "/auth/recover"` points to a non-existent page (LoginForm substitutes `/forgot-password`).
- Suggested owner paths: those files; `apps/api/app/modules/identity/router.py`

(FE-25 intentionally unused — merged into FE-26.)

---

## Summary

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 6 (FE-01, 02, 03, 04, 06, 07) |
| Medium | 13 (FE-05, 08, 09, 10, 11, 12, 13, 14, 15, 16, 26, 27, 29) |
| Low | 14 (FE-17..24, 28, 30..34) |

Strong areas: IndexedDB answer persistence, server-clock timer, no answer keys pre-submit, problem+json/step-up handling, native-dialog a11y, design-token discipline (zero stray hex), tables overflow-safe, no secrets in `NEXT_PUBLIC_*`, `no-store` + dynamic rendering for user data, every called BFF path exists in openapi.

Not tested / limits: no browser run of the stack (E2E agent's area), so 360 px findings (FE-18, header wrap) are code-estimated and marked Suspected where applicable; colour contrast not measured (tokens only); bundle measured from an existing `.next` build (built 2026-11-03 16:59), not rebuilt. Probe left in `apps/web/src/__audit_scratch__/fe-retry-after.probe.test.ts`.
