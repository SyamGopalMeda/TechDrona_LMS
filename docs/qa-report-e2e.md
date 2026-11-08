# QA report: end-to-end, accessibility and load smoke (Stage 10)

Owner: QA (E2E). Date: 2026-11-03. Scope: `apps/web` (UI + BFF) against the full local container stack. Backend (`apps/api`) defects are recorded for the backend owner, not fixed here.

## Final audit verification (2026-11-04/06), supersedes the numbers in §0

Full report: `docs/audit/FINAL-AUDIT-REPORT.md` §9. Stack: `docker compose --profile app`, with images rebuilt from the current tree. Each project ran after a fresh `scripts/reset-dev-data.ps1 -Force`.

| Gate | Result |
|---|---|
| Playwright `chromium`, `--workers=1` | **48 passed, 0 failed, 0 skipped**: 3 green passes, one after the host reboot. The first pass of the run had 42 passed / 3 failed / 3 skipped |
| Playwright `mobile` (Pixel 7), `--workers=1` | {MOBILE}. The first pass of the run had 43 passed / 5 failed |
| Audit journeys `npx playwright test -c e2e/_audit/playwright.audit.config.ts --project=chromium --workers=1` | **4 passed, 0 failed** (ID1 caps, ID2 password reset, J1 learner journey, ST1 coordinator). The first pass had 2 failed |
| API `pytest`, fresh DB | **813 passed** |
| Web `lint` / `typecheck` / `vitest` / `build` | clean / clean / 630/630 (`--maxWorkers=4` on the rebooted host; 628/628 with default workers before the reboot) / OK |

Root causes and fixes from this run:

**App bug: mobile tab bar over the Focus screens.** On phones the learner bottom tab bar (`z-topbar`) was drawn on top of the practice and timed-test action bars (`z-sticky`, also `bottom-0`), so "Check answer" and "Save →" could not be tapped. `MobileTabBar` now renders nothing on the design-system §4 Focus routes. Covered by `components/shell/shell.test.tsx` and by the mobile `student-learning` specs.

**Harness: TO-08 from unload beacons.** Chromium sends unload-time `sendBeacon` / keepalive requests (`/analytics/events/beacon`) from the browser process with the host's real UA, not the emulated one. The api treats a UA/OS change on a session as a stolen-cookie replay (TO-08), and two of them protect-lock the account (HC-T3). This locked `student@` in the mobile project, and it blocked "device 3" in audit ID1.
- The mobile project now launches Chromium with `--user-agent=<Pixel 7>`.
- ID1 launches one Chromium process per simulated device.

**Harness: TOTP replay.** `freshTotp()` in `e2e/support/auth.ts` never reuses a 30 s step for the same secret. When it has to wait, it adds the wait to the test timeout.

**Specs: selector drift.**
- "Save and go to the next question".
- Scoped "Trusted networks" link.
- Exact taxonomy cell.
- Mobile palette dialog.
- J1 follows the E2E-04 in-place consent grant and checks it persisted via `GET /me/consents`.

**Fixtures.** `.env.e2e.local` now has the finance, content and admin staff accounts, and `e2e_demo` seeds one pending `policy.change` approval. The 3 previously skipped staff specs now run and pass.

## 0. Final integration pass (2026-11-03, after this report)

Backend issues B1–B5 below are **fixed**. The seed gaps are closed. The whole Playwright suite now passes **from one fresh seed in one pass**.

| Gate | Result |
|---|---|
| Playwright, full chromium suite, `--workers=1`, one pass after `scripts/reset-dev-data.ps1 -Force` | **33 passed, 0 failed, 0 skipped** (23 `@integration` + 10 smoke/auth-page tests). Final run: 1.3 min, after a fresh reset, and the second consecutive green full pass from a fresh seed. One intermediate pass found T3/T4 below. The practice spec was repeated 4× green afterwards |
| API `pytest`, fresh DB (`TD_TEST_DB_NAME=techdrona_test_final`, `TD_TEST_RESET_DB=1`) | **559 passed, 0 failed, 0 skipped** (9 min 34 s). Baseline 540 + the B1/B4, B2, autosave-batch, pool-env and seed-fixture tests |
| `ruff check` / `ruff format --check` / `mypy app` | clean / clean / no issues |
| Web `lint` / `typecheck` / `test` / `build` | lint 0 warnings, typecheck clean, `npm test` **36 files / 345 tests passed**, `npm run build` OK. Under full parallel load a few UI tests have hit the 5 s per-test timeout. Each passes alone, and the last full run was 345/345. `ProgressDashboard` (recharts, 1.3–4 s alone) now has a 15 s timeout |

### 0.1 Fixes

| ID | Fix | Tests |
|---|---|---|
| B1 | A pool checkout timeout (`sqlalchemy.exc.TimeoutError`), or Postgres refusing a connection (`TooManyConnectionsError`, `CannotConnectNowError`), now returns **`503 service_unavailable`** problem+json with `Retry-After: 2`. It is logged at warning as `db_capacity_exhausted`, with no traceback. Other DB errors are still `500 internal_error` (`app/core/errors.py`). The pool is configurable through env: `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, and the new `DB_POOL_PRE_PING` and `DB_POOL_RECYCLE_SECONDS`. Compose `api` defaults: 4 uvicorn workers × pool 20 + overflow 5, pre-ping off. Postgres `max_connections` is 200 (all `TD_API_*` / `TD_PG_MAX_CONNECTIONS` overridable). | `tests/core/test_capacity_and_disconnect.py`: synthetic and **real** pool exhaustion, too-many-connections, other DB errors stay 500, env → engine settings |
| B2 | With `PAYMENTS_PRIMARY_PROVIDER=fake`, COM-01 returns `checkout.test_payment = {payment_id, signature}`. The signature is the Razorpay `order_id|payment_id` HMAC with the fake secret. The payment id encodes the gateway order and the amount, so COM-06 confirm works on **any api worker** (the fake is in-memory per process). Nothing is captured until the learner confirms. The real Razorpay gateway never adds it | `tests/commerce/test_checkout_webhooks.py::test_fake_gateway_test_payment_completes_checkout_on_any_worker` (also checks that a tampered id fails the signature); E2E checkout now asserts instead of skipping |
| B3a–f | Separate DEV-only fixtures, idempotent, refused in production (see §0.2) | `tests/seeds/test_dev_fixtures.py` (seed chain run twice, every invariant, the trainer sees the test through the real route) |
| B4 | A `ClientDisconnect` while a request body is read is answered `499` and logged at info as `client_disconnected`. It is never logged as `unhandled_exception` or 500 | `test_client_disconnect_during_body_read_is_not_a_500` |
| B5 | The local root `.env` now has `PAYMENTS_PRIMARY_PROVIDER=fake`, the same as `.env.example`. **This is a local dev file change**; no secrets were touched. `.env.example` now documents `test_payment` and that `razorpay` with placeholder keys gives 503 | — |

Found and fixed during the full run:

| ID | Problem | Fix |
|---|---|---|
| W10 | a11y `scrollable-region-focusable` (serious) on the security case detail. It appears now that the case has a linked evaluation, so the signals table renders | `components/ui/Table.tsx`: the scroll wrapper is a named `region` with `tabIndex=0` and the standard focus ring |
| B6 | The clean learner had no `security_monitoring` consent, so COM-01 returned `403 consent_required`. The old seed got it only as the restricted fixture | `e2e_demo` seeds the consent; the seed test asserts it |
| T1 | a11y course-player spec assumed an existing enrolment | It enrols in the free course first |
| T2 | Practice spec locator matched both the verdict and the "✓ Correct answer" badge | It anchors on the verdict line |
| T3 | Practice spec assumed question 1 is multiple-choice; question order is random, so it can be numeric | It types an answer when there are no options |
| T4 | The identity request-a-review spec ticked only the first device. Unticked devices are signed out on submit, and with the new fixture devices the browser's own device was sometimes unticked, so the session ended | It ticks every listed device |

### 0.2 Fixtures (`scripts/reset-dev-data.ps1 -Force`)

The script drops and recreates **only** the `techdrona` database. It migrates, runs all seeds (`seed-dev.ps1 -Migrate`), writes `apps/web/.env.e2e.local` (gitignored; loaded by `playwright.config.ts`), clears `.e2e-devices` and restarts the running app containers. It refuses `APP_ENV=prod` and any `DATABASE_URL` that does not point at `techdrona`. Staff TOTP secrets are fixed dev-only constants.

| Account | State after reset | Used by |
|---|---|---|
| `student@` | clean learner, no case, `all_practice` grant, `security_monitoring` consent | learner, practice, timed test, checkout, multi-tab, a11y |
| `restricted.student@` | L3, case linked to the engine evaluation and 9 signals, verified ≥ 30 days before the restriction, no request | restricted-direct-api, identity request-a-review, a11y |
| `reverify.student@` | L3, lift pending (decided by `security@`) | reverify (SCN-10) |
| `suspended.student@` | L4 high-risk case, submitted APL request, escalated by `admin@` | security-console dual approval (`E2E_L4_CASE_ID`) |
| `security@`, `security2@` | reviewers A and B | security-console |
| `trainer@` | `demo-college-weekly-test` published in the college scope | staff-portals assign |
| `e2e-timed-test` | free, 4 fixed questions, 100 attempts | `E2E_TEST_ID` |

Spec order no longer matters. security-console and reverify use up their fixtures, so run the reset again before the next full pass.

### 0.3 Load smoke after the fixes (200 VUs × 2 min, through the BFF)

Profiling (`pg_stat_statements` and in-process cProfile):

- Autosave **DB execution is about 1.5 ms per request** across about 20 statements.
- The api container was **CPU-bound**: 2 workers at about 193 %, Postgres at 40–60 %.
- `pool_pre_ping` added `BEGIN; ; ROLLBACK` on every checkout. That is 3 extra round trips × 2 transactions per request. Turning it off makes a sequential autosave **about 17 % faster** (91–94 → 75–78 ms, host to Docker).
- Overflow connections are closed on return. Every new backend paid asyncpg type introspection and statement re-prepare (0.5–1.8 s under load). That caused the pool stalls.
- The autosave path itself had no read N+1. RLS `set_config` is one statement per transaction at about 0.02 ms. Existing indexes cover every hot query (all sub-ms).

Changes:

- The per-item `INSERT … ON CONFLICT` loop is now **one multi-row upsert**. The newest `client_seq` per question wins, which is equivalent to applying the items in order.
- `load_bundles` (full stems, bodies and keys) is replaced on the autosave path by **one lean query**: type, option ids and coding problem.
- Compose sizing as in B1.

| Run | Code / api config | Autosave ok | Client p50 / p95 / p99 | Server p50 / p95 / p99 |
|---|---|---|---|---|
| QA run 2 | before, 2 × (5+2) | 74.0 % (500s) | 5.16 s / 9.73 s / 10.81 s | n/a |
| QA run 3 | before, 2 × (20+10) | 100 % | 178 ms / 1.27 s / 2.33 s | 161 ms / 1.20 s / — |
| A | before, 2 × (20+10) | 100 % | 126 ms / 558 ms / 1.74 s | 114 / 520 / 1,663 ms |
| B | after, 4 × (10+10) | 99.56 % (26 × **503**, 0 × 500) | 247 ms / 2.42 s / 10.65 s | 175 / 1,813 / 8,052 ms |
| C | after, 4 × (20+5) | 100 % | 140 ms / 1.58 s / 2.71 s | 115 / 1,293 / 2,267 ms |
| D | after, 2 × (20+10) | 97.2 % (100 × **503**) | 352 ms / 6.37 s / 10.39 s | — |
| E | after, 4 × (20+5) | 100 % | **87 ms / 334 ms / 481 ms** | **71 / 261 / 400 ms** |
| F | after, 4 × (20+5) | 100 % | 107 ms / 648 ms / 939 ms | — |
| G | after, 4 × (20+5), pre-ping off | 100 % | 94 ms / 486 ms / 1.02 s | 75 / 384 / 779 ms |
| H (final compose defaults) | after, 4 × (20+5), pre-ping off | 100 % | 444 ms / 1.75 s / 2.56 s | 241 / 1,019 / 1,739 ms |

Honest reading:

- **No run since the fixes produced a 500.** Saturation now gives a clean `503` with `Retry-After`.
- On this laptop the same configuration varies **up to 5×** from run to run (E vs C/H: 0.33 s vs 1.6–1.75 s client p95). The variance is larger than any configuration or code effect, so a before/after p95 claim cannot be made from these numbers.
- The best run (E) is about at the 300 ms target (**server p95 261 ms, client 334 ms**). The median of the after runs is about 0.65–1.6 s.
- **Local does not reliably meet the 300 ms p95 target.** The api, web BFF, Postgres and k6 all share one 12-CPU laptop VM, and the api is CPU-bound.
- The NFR applies to production infrastructure. Rerun on staging-sized hardware with the app tier scaled horizontally.
- Remaining per-request cost:
  - 2 transactions: the session resolver commits separately, with `SELECT … FOR UPDATE` on `auth_sessions`.
  - About 9 resolver lookups.
  - An `auth_sessions` sliding-idle update on every engaged POST.

  These are candidates for a cached principal, which was not changed here for security reasons.

## 1. Environment

| Item | Value |
|---|---|
| Stack | `docker compose --profile app up -d --build --wait` (api :18000, web :13000, Mailpit :8025). Images rebuilt from the current tree, including the backend QA changes (LRN-16a). `migrate` exited 0 |
| Seeds | `scripts/seed-dev.ps1` on the dev DB `techdrona`. Staff TOTP secrets had been printed on an earlier run only, so they were recovered from `mfa_factors` with the local KMS key (dev only) |
| Config override | (Resolved by B5, §0: `.env` is now `fake`.) At the time, local `.env` had `PAYMENTS_PRIMARY_PROVIDER=razorpay` (`.env.example`: `fake`), so checkout called the real `api.razorpay.com` with a placeholder key → `503`. The api services were recreated with `PAYMENTS_PRIMARY_PROVIDER=fake` through a compose override file (env only, no code change). **The running stack still carries that override.** A plain `docker compose up` reverts to `.env` |
| Browser | Playwright 1.64 Chromium (`--project=chromium`, `--workers=1`). The `mobile` project was not run |
| Host | One laptop: 12 CPUs and 7.6 GiB for the Docker VM. k6 ran on the same machine |

## 2. Specs run

The integration specs share seeded accounts and are **stateful**. `student@` is both the restricted fixture (security_demo L3) and the learner. Valid order: restricted-state specs → `security-console` (lift) → `reverify` (SCN-10) → learner specs.

| Spec | Tests | Result | Notes |
|---|---|---|---|
| `smoke.spec.ts` | 4 | 4 pass | |
| `auth-pages.spec.ts` | 3 | 3 pass | |
| `identity.integration` signup → verify email → login → sessions | 1 | pass | Test bug fixed: it read the verification mail instead of the device-OTP mail |
| `identity.integration` restricted → request a review | 1 | pass (restricted phase) | Seed already holds a submitted APL request; the spec now asserts the request status card when one exists |
| `restricted-direct-api.integration` **(new, SCN-13)** | 2 | 2 pass (restricted phase) | Through the BFF with a real session and CSRF: `POST attempts`, `media/playback-tokens`, `coding/problems/{id}/run` and `/submit`, `GET coding/problems`, `POST practice/sessions` and `/answers` → `403 application/problem+json`, `code=account_restricted`, `case_ref`, `level`, `until`, no `data`. `GET me` and `me/sessions` → 200. A missing CSRF token → `403 csrf_failed`. A content page redirects to the restricted screen |
| `security-console.integration` | 1 | pass | The seed has only an L3, non-high-risk case, so the single-reviewer branch ran. **The L4 dual-approval branch was not exercised** (no seeded L4 case) |
| `reverify.integration` **(new, SCN-10 recovery)** | 1 | pass | Needed the new web re-verification panel (W3) and a fixture backdate (B3b) |
| `learning-commerce` browse → enrol free → lesson | 1 | pass | |
| `learning-commerce` checkout paid plan | 1 | **skipped: blocked by B2** | Fake gateway gives no `test_payment` |
| `student-learning` practice | 1 | **skipped: blocked by B3f** | Student has no practice entitlement; no local path grants one |
| `student-learning` timed test (start, autosave, refresh-resume, offline, submit) | 1 | pass | Test fixes: resumes an already-open attempt, picks an unchecked option, strict-mode locator |
| `multi-tab.integration` **(new, SCN-02)** | 1 | pass | One context, 3 tabs (lesson, practice, dashboard); the same attempt is open in two tabs, both autosave, both show "already open in another tab", the notice clears when one tab closes, the session count is unchanged, no logout or cap prompt. Also runs axe on the test runner. Video takeover is not covered (fake video provider) |
| `staff-portals` coordinator CSV roster | 1 | pass | |
| `staff-portals` trainer assigns a test | 1 | **skipped: blocked by B3d** | `GET /studio/tests` returns no items in the trainer's scope |
| `a11y.integration` **(new)** | 15 + runner | all pass after fixes | See §4 |

**Final full-suite run** (one pass in the final, post-recovery state): 23 passed, 7 failed, 3 skipped.

- 5 of the failures were the restricted-state specs. They fail by design once the student is unrestricted.
- 2 were coordinator sign-ins that hit the device cap on the MFA page (W4). They pass after the fix.
- The practice skip check raced the error. It was fixed and now skips correctly.

Every spec passed or was skipped as blocked in its valid phase. **Not achieved:** one green run of the whole suite from a single seed, because of B3e.

Note: `student@` has now used all 3 attempts of `E2E_TEST_ID` (`demo-aptitude-mock`), so the timed-test and SCN-02 specs need fresh attempts before the next run.

## 3. Bugs

### 3.1 Web: fixed

| ID | Bug | Fix |
|---|---|---|
| W1 | Coding editor kept drafts in memory only (COD-04/05 were not called) | `codingApi.getDraft/saveDraft`. The workspace restores the server draft per language (local edits win), autosaves 5 s after the last keystroke (≤ 12/min; server limit 20/min), flushes on language switch and unmount, and shows the save state in a polite live region. Unit test added |
| W2 | SCN-02: no "already open in another tab" notice on the attempt runner | BroadcastChannel `td-attempt-<id>` hello/here/bye protocol, plus a status banner |
| W3 | **After a reviewer lift (`lift_pending`) the student had no UI for AUTH-21/22**, so access could never be restored | `ReverifyPanel` on the L3/L4 restricted screen when SEC-01 offers `reverify`: email or SMS code → `auth/reverify/complete` (Idempotency-Key) → `/login?reason=reverified`. Unit and E2E tests |
| W4 | MFA page dead end: `409 device_cap_reached` after TOTP showed "Remove a device to continue here" with no way to do so | Hands off to `/login/verify-device`, which already has the device-cap chooser. Unit test |
| W5 | a11y serious: color-contrast on the landing "See pricing" ghost button on the brand hero | On-brand underlined link |
| W6 | a11y serious: link-in-text-block on the student dashboard (2 links) | Underlined |
| W7 | Trainer grading (TRN-009) searched LRN-16 lists because no single-submission GET existed | Uses the new LRN-16a `GET /assignment-submissions/{id}`; `?assignment=` is now optional; 404 → "Submission not found". `npm run gen:api` re-run. Tests updated |
| — | Studio nav entry for `/studio/reports/errors` | Already present (`portals.ts`), no change |

Test-infrastructure fixes:

- New shared `e2e/support/auth.ts`: MFA, Mailpit OTP filtered by send time, device-cap chooser, session chooser, and one reused device per account in `apps/web/.e2e-devices/` (gitignored). Each fresh context had been registering a new device and burned the 3-device cap and the 2 replacements per 30 days.
- `support/a11y.ts` and `support/attempt.ts`.
- `security-console` handles L3 or L4 and empty evidence.
- `staff-portals`, `student-learning`, `learning-commerce` and `identity` now use the shared sign-in.

### 3.2 Web: open

| ID | Gap |
|---|---|
| W8 | FIN-003 Coupons is a `NotImplemented` placeholder. There is no finance UI for ENT-06 manual grants either, so there is no UI path to a free-access entitlement for test or comp users |
| W9 | W4 hand-off labels the channel "your email" because the `device_cap_reached` problem carries no masked destinations. Better: the api includes `channels` in that problem |

### 3.3 Backend: fixed in the final integration pass (see §0; originally open for the backend owner)

| ID | Endpoint / area | Request → actual | Expected |
|---|---|---|---|
| B1 | All routes under load (seen on `POST /api/v1/auth/login`, `POST /api/v1/attempts`, `POST /api/v1/attempts/{id}/autosave`) | 200 VUs through the BFF. `sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 2 reached` (1,318 in one run) → **bare `500`** | `503 service_unavailable` problem+json with `Retry-After`. Size the pool for 2 uvicorn workers (5+2 each is the bottleneck; see §5) |
| B2 | `POST /api/v1/commerce/orders` with `PAYMENTS_PRIMARY_PROVIDER=fake` | `checkout = {key_id: "rzp_test_FAKE", gateway_order_id, amount, currency, name, notes}` | The web contract (`features/commerce/lib/payment-provider.ts`) expects `checkout.test_payment = {payment_id, signature}`, signed with the fake secret, so "Simulate a successful payment" can call verify. Without it no paid flow can be tested end to end locally |
| B3a | `security_demo` seed | Case `SEC-…` has no linked risk evaluation; SEC case detail says "No risk evaluation is linked" and shows no contributing signals | The case should link the engine evaluation that produced L3 |
| B3b | `security_demo` + AUTH-21 `POST /api/v1/auth/reverify/start {"channel":"email"}` | `409 invalid_state_transition` (`contact_not_eligible`): the seed restricts `student@` 1 minute after `email_verified_at` | Seed backdates `email_verified_at` ≥ 8 days (QA backdated it by 30 days in the dev DB). Product note: anyone restricted within 7 days of signup can never self-reverify. Confirm this is intended |
| B3c | Seeds | Only an L3, non-high-risk case | Add an L4 / high-risk case with a submitted request for the dual-control E2E (SEC-09/10) |
| B3d | `GET /api/v1/studio/tests` as `trainer@` | `{"items": []}` | Seed a published test scoped to the demo org or batch |
| B3e | Seeds | `student@` is both the restricted fixture and the learner, so no single seed can run the whole suite green | Add a second seeded student for the restricted scenario |
| B3f | `POST /api/v1/practice/sessions` as `student@` | `403 entitlement_required` | Seed a practice entitlement (or a free practice subject) for the demo student |
| B4 | `POST /api/v1/analytics/events` when the page navigates away | `unhandled_exception exc_type=ClientDisconnect` logged with a traceback, status 500 | Treat client disconnect as non-error (log at info) |
| B5 | Local `.env` (DevOps) | `PAYMENTS_PRIMARY_PROVIDER=razorpay` with placeholder keys | Match `.env.example` (`fake`) |

## 4. Accessibility (axe-core 4.10, WCAG 2.1 A/AA)

Pages: landing, login, signup, student dashboard, course player, practice, timed test (instructions **and** the TST-002 runner), coding workspace, restricted (L3), unblock request, security unblock queue, security case detail (purpose gate, then the opened case), college dashboard.

| Result | Detail |
|---|---|
| Before fixes | 2 serious: `color-contrast` on landing (W5), `link-in-text-block` on student dashboard (W6) |
| After fixes | **0 violations of any impact on all 16 audited views** |
| Exclusions | `.monaco-editor` (vendor widget tree) |
| Artefacts | `apps/web/test-results/a11y/<page>.json` per run (Playwright wipes `test-results/` on the next run). Failures attach the axe summary to the report |

No screenshots were kept; failure snapshots are in `apps/web/test-results/*/error-context.md` for the last run only.

## 5. Load smoke (k6 0.54 in Docker, `tests/load/attempt-autosave.k6.js`)

Flow per VU: `GET /login` and `GET /api/v1/_bff/csrf` → `POST /api/v1/auth/login` (fresh synthetic user, first device auto-trusted) → `POST /api/v1/attempts` → `POST /api/v1/attempts/{id}/autosave` every 3 s. All traffic goes through the BFF on :13000.

- Script handling: k6 carries cookies itself, because `__Host-`/Secure cookies are not sent over http by its jar.
- Synthetic users: `tests/load/seed_load_users.py` (`load001..600@load.techdrona.local`).
- Shape: 200 VUs for 2 minutes.

**These are laptop numbers, not production capacity.**

| Run | API DB pool | Login ok | Attempt start ok | Autosave ok | Autosave p50 / p95 / p99 (client) | Server autosave p50 / p95 | HTTP failed | Throughput |
|---|---|---|---|---|---|---|---|---|
| 2 (baseline) | default 5+2 per worker × 2 workers | 81.9 % (245/299) | 80.4 % (197/245) | **74.0 %** (1,748/2,362) | 5.16 s / 9.73 s / 10.81 s | n/a (pool timeouts) | 20.5 % | 27 req/s |
| 3 | 20+10 per worker (env override, then reverted) | 100 % (200/200) | 100 % (200/200) | **100 %** (6,504/6,504) | 178 ms / 1.27 s / 2.33 s | 161 ms / 1.20 s | 0 % | 59 req/s |

- Run 1 (not in the table) used an early script that reused stale cookies on retry. It produced a `csrf_failed` cascade and is discarded. Its root failures were the same pool timeouts.
- **Errors at default settings come entirely from DB pool exhaustion → 500 (B1).** With a larger pool the error rate is 0, but the NFR target `autosave p95 < 300 ms` is still missed on this laptop (1.27 s client, 1.20 s server).
- The k6 thresholds (`p95<300ms`, `<1 %` failures) are reported, not gating locally.
- Rerun on staging-sized infrastructure before drawing capacity conclusions. Profile autosave DB time (row locks per attempt, audit/outbox writes per save).

## 6. Dev-database changes made during QA (local only)

- `student@dev.techdrona.local`:
  - Device rows marked `support_reset`: E2E contexts had exhausted the 3-device cap and both replacements.
  - `email_verified_at` backdated by 30 days (B3b).
  - Its L3 case decided `lift_false_positive` and re-verified, so the account is now level 0.
  - Attempts 3/3 used on `demo-aptitude-mock`.
- 600 synthetic users `load###@load.techdrona.local`, about 600 open attempts, and roster invitations from the coordinator CSV spec.

## 7. Files

- Specs:
  - New: `apps/web/e2e/restricted-direct-api.integration.spec.ts`, `multi-tab.integration.spec.ts`, `reverify.integration.spec.ts`, `a11y.integration.spec.ts`, `e2e/support/{auth,a11y,attempt}.ts`.
  - Updated: identity, security-console, staff-portals, student-learning, learning-commerce.
- Web code:
  - `features/coding/{lib/api.ts,lib/types.ts,components/CodingWorkspace.tsx}`
  - `features/assessment/components/AttemptRunner.tsx`
  - `features/unblock/components/{ReverifyPanel.tsx,RestrictedStatus.tsx}`
  - `features/auth/components/MfaForm.tsx`
  - `features/trainer/components/Grading.tsx`
  - `features/dashboard/components/StudentDashboard.tsx`
  - `app/(public)/page.tsx`
  - `lib/api-types/schema.d.ts` + `openapi/openapi.json` (regenerated)
  - Tests: `mfa.test.tsx`, coding, unblock and trainer tests.
- Load: `tests/load/attempt-autosave.k6.js`, `tests/load/seed_load_users.py`.
- Gates (final): `npm run lint` 0 warnings, `typecheck` clean, `npm test` 36 files / 345 tests passed, `npm run build` OK.
