# Audit: end-to-end workflows, persistence, performance, mobile (area `e2e`)

Auditor: E2E-workflow agent (Phase A, audit only). Date: 2026-11-03, ~15:20–16:05 UTC.
Stack under test: web http://localhost:13000 (BFF), api :18000, Mailpit :8025 (running containers, not restarted).
Method: (1) the existing Playwright suite, chromium then mobile; (2) new exploratory specs in
`apps/web/e2e/_audit/` (`*.audit.ts`, own config `e2e/_audit/playwright.audit.config.ts`, so the product
suite never picks them up) using **fresh users** (signup + Mailpit); (3) scripted HTTP probes through the
BFF (Node, separate cookie jar per "device") for flows the UI specs could not reach; (4) console / network
capture on every visited page; 360 px screenshots; (5) a light concurrency smoke (≤ 5 parallel GETs).
Probe scripts and raw logs are in the session scratchpad (not committed).

## Side effects on shared dev data (please read)

- Running the **mobile** project (as requested) after the chromium project put the clean fixture
  `student@` into **takeover protect-lock** (see E2E-02). My own repeated staff probes did the same to
  `security@` (TOTP replays, see E2E-12). I restored both **through the normal self-service path**
  (forgot-password → Mailpit link → reset to the *same* documented dev password); `security@` verified
  usable afterwards (`me/security/status` level 0, history `end_reason: takeover_recovered`). All their
  sessions were revoked by the reset.
- Consumed fixtures: the chromium run used up the `security-console` (L4 dual approval) fixture, so the
  mobile copy of that spec fails (expected per qa-report-e2e §0.2); `reverify` was skipped on mobile.
- Created data: ~12 `audit.*@example.com` learners, 3 paid fake-gateway orders (one refunded), one
  manual security case + L3 restriction on `audit.unblock.1793720781727@example.com` (now stuck, E2E-01),
  and an org **"AUDIT Second College"** (`audit-second-college-35529`) with batch `AUD-1` created by `admin@`
  to test cross-college isolation.
- A reset (`scripts/reset-dev-data.ps1`) is advisable before the next full suite run.

## Coverage inventory

| Feature / Req | Requirement source | Code location | Audit method | Result |
|---|---|---|---|---|
| Existing suite, chromium | qa-report-e2e §0 ("33 passed") | `apps/web/e2e/*.spec.ts` | `npx playwright test --project=chromium --workers=1` | **Issue** – 31 passed / 2 failed (E2E-11) |
| Existing suite, mobile (Pixel 7) – never run before | playwright.config.ts `mobile` project | same | `--project=mobile --workers=1` | **Issue** – 25 passed / 7 failed / 1 skipped (E2E-02, E2E-08) |
| Signup → email verify → login | AUTH-01/02/06 | identity/router.py | J1 spec (UI) + `GET me` | Verified OK (`email_verified:true, status:active`) |
| Catalogue browse | PUB-00x, CAT | catalog/router.py | J1 + `GET catalog/courses` | Verified OK (2 courses UI = 2 API) |
| Enrol free course + open lesson | LRN-01/04 | learning/router.py | J1 + `GET me/enrolments` | Verified OK (enrolment `source:free, active`) |
| Lesson completion (article) | LRN-06 | learning/service.py:369 | J1: Mark as complete, reload, API | Verified OK (server min-read gate 409 "Keep reading…", then `progress_pct 0→50`, badge persists after reload) |
| Checkout (fake gateway) | COM-01/06, PO-03 | commerce/service.py:67 | J1 UI + `me/orders`, `me/entitlements`, `me/invoices` | Verified OK after consent; **Issue** E2E-04 (misleading block) |
| Confirm replay | SCN-14-like | commerce/router.py | probe: confirm twice | Verified OK (second confirm 200, same order) |
| Timed test: autosave, reload, submit, server score | TST-003/004/005 | assessments/router.py | J1 + `attempts/{id}/state`, `/result` | Verified OK (4 answers saved server-side; `status: graded, score 2/4, percentage 50`) |
| Progress / analytics update | ANA M5, mastery | analytics/reports.py | `me/analytics/summary` before/after + relogin 30 min later | **Issue** E2E-05 (mastery + lessons update; learning time stays 0) |
| Session cap (2) chooser on 3rd device | FR-SES-006, R-2 | sessions, identity | ID1 spec + node probe | Verified OK (chooser lists 2 sessions; evicted session → `/login?reason=session_revoked`) |
| Device cap (3) on 4th device | FR-SES-004, AC-SES-01, R-3 | DeviceVerificationForm.tsx | ID1 spec + probes | Verified OK ("You have 3 registered devices … 0 of 2 used"); pending session gets 401 `login_incomplete` on private API |
| Revoked / logged-out cookie reuse | SCN-19 | sessions/resolver.py:135 | ID1 + probe | Verified OK (401 `session_revoked` reasons `session_cap_evicted`, `user_logout`, `user_revoked_other`) |
| Logout everywhere | STU-022 | sessions/router.py:159 | probe (UI path blocked by E2E-09) | Verified OK (`revoked:1`, other device 401) |
| Password reset | AUTH-16/17 | identity/router.py:~880 | ID2 spec (UI) | Verified OK (other session 401, link reuse refused "This reset link has expired or was already used", old pw refused, new pw works, change-notice email sent) |
| Staff MFA login | AUTH-07, tiers | identity/router.py | ST1 spec (UI, TOTP) + probes | Verified OK (`aal:2, tier:staff/privileged`) |
| Coordinator sees only own college | SCN-18, RBAC | orgs/router.py, analytics | probe vs a 2nd org + ST1 UI | Verified OK (18 read/write endpoints on other org/batch → 404; UI never shows the 2nd college) |
| Refund flow | FR-COM refund rule, COM-3x | commerce/router.py:745 | probe: eligibility → request → finance approve | **Issue** E2E-03 (lifecycle never completes) |
| Unblock: request → reviewer approves → restored | SCN-10/11, UNB §5–6 | security/unblock.py, cases.py | probe with fresh user, two reviewers | **Issue** E2E-01 (dead end at `lift_pending`) |
| Separation of duties | UNB | cases.py | probe | Verified OK (`403 conflict_of_interest` for the reviewer who applied the restriction; decision needs explanation+timeline viewed) |
| Console errors / failed requests | — | all visited pages | `page.on(console/pageerror/requestfailed/response≥400)` | Verified OK: no page errors, no failed requests; only expected 4xx (409 min-read, 403 consent, 401 after revocation, 403 on foreign portals) |
| 360 px learner pages | design-system, mobile | — | J1 + ST1 at 360×780, scrollWidth check, screenshots | **Issue** E2E-07 (billing); others OK |
| Performance smoke | — | — | 6 endpoints × 40 GETs at concurrency 5 | **Issue** E2E-06 (tail latency / unhealthy worker) |

## Findings

### E2E-01: Unblock approval leaves new-contact students permanently restricted (`lift_pending` dead end)
- Severity: High
- Status: Confirmed
- Component: `apps/api/app/modules/security/unblock.py:622-647` (`contact_eligible`, `reverify_start`), `security/api_review.py:788-799` (manual lift → `decision_required`), `security/api_student.py:~182` (`available_actions`)
- Requirement: account-unblock-workflow.md line 279 ("contacts changed in the 7 days before restriction are not trusted → manual verification via escalated reviewer"), §state table (Escalated "takeover with changed contacts"); Phase 8 scenarios 10/11.
- Repro (fresh adult, email verified minutes before): `security@` opens case + L3 → student re-logs in, `POST security/unblock-requests` (201 `APL-2611-7115AQ`) → `security2@` claims, views explanation + timeline, `POST cases/{id}/decisions {outcome: lift_false_positive}` → student `POST auth/reverify/start {channel:email}`.
- Expected: either OTP re-verification, or the request goes to `escalated` and a senior reviewer can complete manual verification and lift.
- Actual: decision returns `next: "student_reverification"`, request state **approved**, restriction `lift_pending`; student status advertises `available_actions:["reverify",…]`, but reverify is refused and the reviewer cannot lift manually. No endpoint completes the "manual verification". Student stays L3 indefinitely.
- Evidence:
  ```
  S2 decide 201 {"next":"student_reverification","outcome":"lift_false_positive","requires_second_approval":false,"restriction":{"state":"lift_pending"},"unblock_request":{"state":"approved"}}
  U status after 200 {"level":3,…,"lift_pending":true,…,"available_actions":["reverify","request_review","manage_devices","contact_support"]}
  start 409 {"code":"invalid_state_transition","detail":"This contact changed recently, so a senior reviewer will verify you manually."}
  lift 409 {"code":"decision_required","case_ref":"SEC-2611-60B16H"}   (POST security/restrictions/{id}/lift by security2@)
  ```
- Root cause: the decision path does not check `contact_eligible` before choosing `next: student_reverification` / state `approved`; no "manual verification complete" action exists; the lift endpoint ignores a decided case in `lift_pending`. Dev fixtures hide it (dev_users.py:27 back-dates contact verification > 7 days).
- Recommended fix: at decision time, if no eligible contact, set request `escalated` (senior pool) and expose a reviewer action "manual verification complete" that ends the restriction (audited, second reviewer if required); do not advertise `reverify` when `contact_eligible` is false.
- Suggested owner paths: `apps/api/app/modules/security/{cases.py,unblock.py,api_review.py,api_student.py}`, `apps/web/src/features/security/*` (restricted screen copy).

### E2E-02: Mobile project fails and locks the clean `student@` fixture (shared device file + takeover rules)
- Severity: Medium
- Status: Confirmed
- Component: `apps/web/e2e/support/auth.ts:63-92` (`.e2e-devices/<account>.json` shared by all projects); takeover rules TO-08/TO-11 (`security/engine.py:855-913`)
- Requirement: playwright.config.ts defines a `mobile` project; qa-report-e2e claims the suite is green.
- Repro: `npx playwright test --project=chromium --workers=1` then `--project=mobile --workers=1`.
- Expected: mobile project passes (or is excluded) without damaging fixtures.
- Actual: 25 passed / 7 failed / 1 skipped. The mobile context reuses the desktop `td_device` cookie with a Pixel UA → session `blocked device_mismatch`, TO-08 (60) → step-up; ~10 logins/h → AB-01 → TO-11 (20) → score 79.99 ≥ 70 → **protect_lock** of `student@` (all sessions revoked; later logins "We've secured your account"). The remaining student specs then fail at sign-in.
- Evidence:
  ```
  x 19 [mobile] learning-commerce … open a lesson   (Course contents nav not attached — see E2E-08)
  x 20 [mobile] checkout a paid plan …               (page: "You were signed out. Please log in again.")
  x 21/32/33 [mobile] multi-tab / practice / timed test: page.waitForURL timeout at support/auth.ts:103
      page alert: "We've secured your account … signed out all devices"
  x 25 [mobile] security-console … (fixture consumed by chromium run)
  7 failed, 1 skipped, 25 passed (4.6m)
  evaluation 15:29:43 takeover score 79.99 action protect_lock signals [TO-08 60 {device,session}], [TO-11 20 {from: AB-01}]
  timeline: session … status blocked end_reason device_mismatch; AB-01 {logins_1h:10}
  ```
- Root cause: test harness keys device cookies per account, not per project/UA; the full suite performs ≥10 sign-ins of `student@` per hour.
- Recommended fix: key `.e2e-devices` by `${project}-${account}`; give the mobile project its own seeded accounts or a tag filter; consider an env-gated test allow-list for AB-01 in dev only (not prod).
- Suggested owner paths: `apps/web/e2e/support/auth.ts`, `apps/web/playwright.config.ts`, `apps/api/app/seeds/e2e_env.py`.

### E2E-03: Approved refund never completes locally; order stays "paid" while access is revoked
- Severity: Medium
- Status: Confirmed (local fake gateway)
- Component: `apps/api/app/modules/commerce/router.py:745-790` (`_decide_refund` → `execute_refund`), `commerce/webhooks.py:42,152` (refund status only advanced by `refund.processed` webhook)
- Requirement: refund rule (eligibility), order/refund states in api-specification; billing page shows refund status.
- Repro: fresh buyer → `POST me/refund-requests` (201) → finance `POST finance/refunds/{id}/decision {approve}` → wait 15 min.
- Expected: refund `processed`, order `refunded`, consistent states (or a reconciler completing fake refunds).
- Actual: refund stuck `processing` (`processed_at: null`) 15+ min later; order `paid`; entitlement already `revoked`; credit note `TDCN/2627/000001` issued.
- Evidence:
  ```
  decide 200 {"gateway_refund_id":"rfnd_FAKE000000032d33f8","status":"processing",…}
  orders after 200 [[true,"paid"]]   ents after 200 [["revoked","purchase"]]
  (15:54) finance/refunds: 01a1a211-eb7f-… processing created 15:40:45 processed_at null
  ```
- Root cause: completion depends on a gateway webhook the fake gateway never sends; order status not updated when the refund is executed.
- Recommended fix: fake gateway emits/dispatches `refund.processed` (or reconciliation job polls fake refunds); set order `refund_pending`/`partially_refunded` at execution so UI/state are consistent.
- Suggested owner paths: `apps/api/app/modules/commerce/{gateway.py,service.py,webhooks.py,tasks.py}`.

### E2E-04: New adult learner's first checkout is blocked with a misleading "updated terms" message
- Severity: Medium
- Status: Confirmed
- Component: `commerce/service.py:91-103` (`consent_required`, purposes `["security_monitoring"]`); `apps/web/src/features/commerce/components/Checkout.tsx:26`
- Requirement: PO-03 (paid plans need security_monitoring consent); signup offers it unticked (SignupForm, consents.ts:24).
- Repro: sign up via UI (only the required box ticked, the default) → /pricing → Get → Continue to payment.
- Expected: checkout explains that paid plans need "Account protection and single-user licence checks" and offers to turn it on inline.
- Actual: `POST commerce/orders` 403; UI shows "Please review and accept the updated terms" (twice) + "Review consents" link to /app/settings/privacy; the learner has to find and enable the right toggle, then re-enter billing details.
- Evidence: `{"step":"checkout_blocked","alerts":["Please review and accept the updated terms\n\nPlease review and accept the updated terms\n\nReference: 01a1a20a-…"]}`; network `403 POST /api/v1/commerce/orders`.
- Root cause: generic `consent_required` problem title reused; UI does not read `purposes`.
- Recommended fix: map `consent_required` + `purposes:["security_monitoring"]` to a specific message and an inline "Turn on and continue" (POST me/consents) in Checkout; de-duplicate title/detail.
- Suggested owner paths: `apps/web/src/features/commerce/components/Checkout.tsx`, `apps/api/app/core/errors.py` (problem catalogue copy).

### E2E-05: Learning time (M5) stays 0 after real lesson and test activity
- Severity: Medium
- Status: Suspected
- Component: `apps/web/src/lib/analytics/use-activity-tracker.ts`, `analytics/jobs.py` (interval_builder 60 s, daily_aggregator 900 s), `analytics/reports.py:169`
- Requirement: analytics-event-schema M5; Section H "Daily/weekly/monthly learning activity".
- Repro: J1 user read a lesson ~70 s (scrolled, completed), took a timed test (10 s); re-checked ~30 min later after `daily_aggregator` ran at 15:43 and 15:58.
- Expected: `learning_time.today_s > 0`, `active_days_last_30 ≥ 1`.
- Actual: `{"lt":{"today_s":0,"this_week_s":0},"lessons":1,"tests":[{"attempt_time_s":10,"time_on_test_page_s":0}],"streak":0,"last30":0}`; `me/analytics/learning-time` all zeros. Mastery and `lessons_completed` did update.
- Root cause: unknown — either the tracker does not credit time in headless Chromium (focus/engagement), or intervals are not aggregated into `daily_learning_aggregates`. Needs a check of `analytics_events`/intervals for user `01a1a209-c0f6-7738-b719-5f4df8822c9e` (I did not query the dev DB).
- Recommended fix: investigate with an integration test that sends heartbeats and runs interval_builder + daily_aggregator; add an E2E assertion on `learning_time` after a lesson.
- Suggested owner paths: `apps/web/src/lib/analytics/*`, `apps/api/app/modules/analytics/{consumer.py,jobs.py}`.

### E2E-06: Celery workers permanently unhealthy; healthcheck burns ~1 CPU core and inflates tail latency
- Severity: Medium
- Status: Confirmed
- Component: `docker-compose.yml:275-280` (`&celery-healthcheck`: `celery inspect ping … --timeout 10`, Docker timeout 15 s)
- Requirement: deployment-and-operations (health checks).
- Evidence:
  ```
  techdrona-worker-1 Up 4 hours (unhealthy)   techdrona-worker-maintenance-1 Up 4 hours (unhealthy)
  health log: -1 15:57:54→15:58:09, -1 15:58:39→15:58:54, -1 15:59:24→15:59:40
  docker top: 75213 99.8% … celery … inspect ping -d default@fad5a8a289b4 --timeout 10
  docker stats: worker 103–131% CPU while its tasks take 0.1–0.26 s every 5 s
  smoke (≤5 concurrent GETs, other agents also running): p50 272–457 ms, p95 me 2709 ms, me/dashboard 3480 ms, me/tests 9603 ms, catalog/courses 3856 ms (4/40 errors once; 0/40 and max 359 ms on re-run; sequential p50 45 ms)
  ```
- Root cause: the ping never gets a reply within the window (node name / hostname mismatch or broker latency) and each probe spawns a full Celery client for ~15 s every 30 s.
- Recommended fix: use a cheap liveness check (e.g. a heartbeat file written by a worker signal, or `inspect ping` with correct `-d` and `--timeout 3`), and fix whatever makes ping fail.
- Suggested owner paths: `docker-compose.yml`, `infra/` compose/ECS task definitions, `apps/api/app/worker*`.

### E2E-07: /app/billing overflows horizontally at 360 px
- Severity: Low
- Status: Confirmed
- Component: billing orders table (`apps/web/src/components/ui/Table.tsx` + billing feature)
- Evidence: `{"path":"/app/billing","scroll":411,"client":360,"offenders":["table… right=427","span.sr-only right=411",…]}`; screenshot `scratchpad/audit/j1run2/shots/m360-_app_billing.png` (header ends at 360 px, blank band to 411 px). Other pages at 360 px (/app, /app/learning, course, tests, practice, progress, settings/devices, /courses, /pricing, /college, /college/students) have no page-level overflow.
- Root cause: an absolutely positioned `.sr-only` inside the table escapes the scroll wrapper (wrapper not `position:relative`), widening the document.
- Recommended fix: `relative` on the table scroll wrapper (or move the sr-only text out of the cell).
- Suggested owner paths: `apps/web/src/components/ui/Table.tsx`, `apps/web/src/features/commerce/components/*Billing*`.

### E2E-08: Mobile lesson player has no "Course contents" navigation landmark
- Severity: Low
- Status: Confirmed
- Component: `apps/web/src/features/learning/components/LessonView.tsx` (mobile layout)
- Evidence (mobile snapshot): `- complementary: - group: Contents` (desktop: `navigation "Course contents"`); spec `learning-commerce.integration.spec.ts:46` → `expect(locator).toBeAttached() failed`.
- Recommended fix: render the mobile contents as `<nav aria-label="Course contents">` (collapsed) so landmarks match.
- Suggested owner paths: `apps/web/src/features/learning/components/LessonView.tsx`.

### E2E-09: Session blocked as `device_mismatch` (TO-08) seconds after the session-cap chooser in Playwright
- Severity: Low
- Status: Suspected
- Component: `apps/api/app/modules/sessions/resolver.py:147-167`
- Evidence: reproduced twice in `identity.audit.ts` ID1 (3rd device, Chromium context with a Linux/Firefox UA string): timeline `session blocked device_mismatch Chrome on Linux`, signal `TO-08 {device, session}` → step_up (60). Not reproducible with a raw HTTP client using the same UAs (`caps.mjs`: d3 stays 200). Likely a Playwright UA-override artefact, but the signal evidence records neither the expected nor the observed UA/OS, so it cannot be confirmed.
- Recommended fix: include `expected_ua_family/os` and `observed_ua_family/os` in TO-08 evidence and the audit row.
- Suggested owner paths: `sessions/resolver.py`, `security/signals.py`.

### E2E-10: Shared E2E OTP helper can return the previous device's code
- Severity: Low
- Status: Confirmed
- Component: `apps/web/e2e/support/auth.ts:49` (`Date.parse(m.Created) >= after - 5_000`)
- Evidence: two "Verify your new device" mails 4 s apart (15:37:21, 15:37:25); helper returned the first → `POST auth/device-verification/verify` 400 (my first ID1 run).
- Recommended fix: remember consumed message IDs and require `Created >= after - 1000` (as `_audit/support.ts` does).
- Suggested owner paths: `apps/web/e2e/support/auth.ts`.

### E2E-11: Chromium suite not reproducibly green (2 timeouts on "Loading" states)
- Severity: Low
- Status: Confirmed (flaky)
- Evidence:
  ```
  x a11y.integration.spec.ts:47 › a11y: student › student-dashboard   main: status "Loading your dashboard" (5 s expect timeout)
  x learning-commerce.integration.spec.ts:24 › browse → enrol … open a lesson   main: status "Loading lesson"
  2 failed, 31 passed (4.7m)
  ```
  The same pages rendered their h1 in 406 ms in J1. Coincides with the CPU load of E2E-06 and other agents' tests.
- Recommended fix: wait for the loading status to disappear (15–30 s) instead of 5 s; fix E2E-06.
- Suggested owner paths: `apps/web/e2e/a11y.integration.spec.ts`, `learning-commerce.integration.spec.ts`.

### E2E-12: TOTP replay counted as MFA failure; staff locked out by repeated automation; same-password reset accepted
- Severity: Low
- Status: Confirmed (behaviour); design question
- Evidence: `security@` evaluation `TO-03 {mfa_failures_1h:2}` 35 → 54.97 step_up → `TO-03 {mfa_failures_1h:3}` + TO-11 → **89.97 protect_lock** after my probes reused a TOTP code within one 30 s step. Recovery `POST auth/password/reset` with the identical password → 200 `password_reset`, lock ends `takeover_recovered`.
- Recommended fix: count a rejected *replayed valid* code separately from wrong codes (or at lower weight); require the new password to differ from the current one on protect-lock recovery.
- Suggested owner paths: `identity/totp.py`, `identity/router.py` (mfa verify, password reset), `security/engine.py`.

### E2E-13: Unblock form/validation rough edges
- Severity: Low
- Status: Confirmed
- Evidence: `GET security/unblock-requests/form` lists devices that never finished verification (`"last_used_at":null`); submitting without `preferred_contact` (optional in `UnblockIn`) → 422 `preferred_contact not_verified "Choose a verified contact channel"`; `what_happened: []` → 422 (fine, but the API schema default is `[]`).
- Recommended fix: list only trusted devices; default `preferred_contact` to `in_app` when omitted.
- Suggested owner paths: `security/api_student.py`, `security/unblock.py`.

## Playwright excerpts

Chromium (existing suite): `2 failed … 31 passed (4.7m)` (see E2E-11).
Mobile (existing suite, first ever run): `7 failed, 1 skipped, 25 passed (4.6m)` (E2E-02, E2E-08).
Audit specs: `J1 fresh learner journey with persistence checks … ok (1.9m)`; `ID2 password reset … ok (12.8s)`;
`ST1 coordinator: TOTP sign-in, own college only … ok (22.2s)`; `ID1 …` fails at the logout-everywhere step
after E2E-09 (all earlier assertions — session cap, eviction, revoked-cookie reuse, device cap, pending-session
401 — passed; logout-everywhere verified by probe instead).

## Summary

- Counts: Critical 0 · High 1 · Medium 5 · Low 7.
- Strong areas confirmed with real persistence: signup/verify/login, enrolment, lesson completion gate,
  fake-gateway checkout + invoice, timed test autosave/resume/submit/server score, session & device caps,
  revoked-session reuse, logout everywhere, password reset, staff MFA, coordinator tenant isolation
  (18 endpoints against a second college → 404), refund eligibility/duplicate guard, reviewer separation of duties.
- Not tested / limits: video playback & stream cap (fake video provider); SMS channels; real Razorpay;
  k6 not used (light Node smoke only, other agents were loading the stack); learning-time root cause needs
  DB inspection (not done, dev DB off-limits); ID1 logout-everywhere UI path (blocked by E2E-09).
