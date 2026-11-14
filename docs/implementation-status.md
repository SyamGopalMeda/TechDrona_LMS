# Implementation Status

> **Removed 2026-11-14** ([cleanup/feature-removal-plan.md](cleanup/feature-removal-plan.md)): mentoring (slots, bookings, sessions, feedback, mentor notes, résumé reviews, the `/mentor` console; the Résumé builder stays), company paths (the `companies` entity stays), corporate enquiries, `GET /catalog/search`, the public SPA pages Hosting redirects to the website, and the `/app/diagnostic`, `/admin/question-review`, `/admin/notifications`, `/app/bookmarks`, `/app/analytics` and `/security/policies` pages. Mentions below of those features are historical.

> **Single-company note (2026-11-06).** Tech Drona now runs as a single company ([ADR-0015](architecture-decisions/ADR-0015-single-company.md)); the college/B2B features described in this document (college portal and coordinators, institution contracts and seats, invitations and roster import, per-organization settings, trusted networks and lab devices, the "For colleges" page) are removed. Roles are Admin (`super_admin`), Trainer, Evaluator, Content manager and Student; finance, support, security and mentor duties belong to Admin. Batches are Tech Drona cohorts managed by Admin at `/admin/batches`; businesses use the corporate enquiry form at `/enquiries`. Rows for `/college/**`, invitations, contracts, seats and `/admin/organizations/**` describe removed features. Where this document conflicts, ADR-0015 and [`single-company/REMOVAL-PLAN.md`](single-company/REMOVAL-PLAN.md) §8 win.

| Field | Value |
|---|---|
| Stage | 10 — Integration & hardening |
| As of | 2026-11-06 |
| Owner | Integration Lead (docs) |
| Scope | `apps/api` (FastAPI, 17 modules, 24 Alembic revisions) and `apps/web` (Next.js portals) |
| Related | `stage10-integration-backlog.md`, `api-specification.md`, `database-schema.md`, `testing-and-acceptance-criteria.md` §4 (SCN-01..20), `product-requirements.md` §4 |

## 0. How to read this document

Each row is scored on four independent columns:

| Column | Meaning |
|---|---|
| **Planned** | Specified in the product/architecture docs (always "Yes" for listed rows). |
| **Implemented** | `Yes` = code and migration exist and are wired into the app; `Partial` = core paths implemented, listed items still Planned; `No` = nothing in code yet (UI may exist against an assumed API). |
| **Tested** | `Yes` = automated tests exist that exercise the behaviour (file pointers given); `Partial` = only some paths covered; `No` = no automated test. "Tested" means the test exists in the repo; the full suite has **not** been re-run for this document (backlog §F). |
| **Deployed** | `No` for every row: there is no staging/production deployment evidence yet (no CI run artefacts, no environment). Local Docker Compose only. |

Evidence snapshot (collected 2026-11-03):

- API: `pytest --collect-only` → **424 tests collected** in `apps/api/tests/**` (44 test files).
- Web: ~265 `it(...)`/`test(...)` cases across 29 Vitest files in `apps/web/src/**` and 7 Playwright specs in `apps/web/e2e/` (5 tagged `@integration`, which need a running api + web + Mailpit with seeds).
- Endpoint counts below are route decorators per module (`@<router>.<verb>(...)`), plus `/healthz`, `/live`, `/ready` in `app/core/health.py`.

## 1. Backend modules (`apps/api/app/modules/*`)

| Module | Migration(s) | Routes | Implemented | Not yet implemented (Planned) | Tests (evidence) | Tested | Deployed |
|---|---|---|---|---|---|---|---|
| core (kernel) | `core_base_0001_kernel` (`outbox_events`, `idempotency_keys`) | 3 health | Yes — request id, problem+json errors, idempotency, RLS context, route guard, outbox relay + worker, jobs registry, AEAD keyrings, startup checks / fake-adapter gate | KMS wrapping of envelope keys (`TD_APP_ENVELOPE_KMS_KEY_ID`) | `tests/core/` — `test_errors_request_id.py` (9), `test_health.py` (3), `test_idempotency.py` (5), `test_ids_time_money.py` (5), `test_logging_and_startup.py` (5), `test_outbox_relay_and_worker.py` (8), `test_rls.py` (5), `test_route_guard_and_auth.py` (9), `test_security_primitives.py` (8), `test_startup_order_and_healthz.py` (3) | Yes | No |
| identity | `identity_0001..0003` (8 tables + org visibility + token RLS) | 29 | Yes — signup (email/mobile), email link + mobile OTP verification, login, MFA (TOTP + recovery codes), step-up, device verification, session choice, password forgot/reset/change, guardian consent, consents, profile, remember-device refresh | Passkey/WebAuthn enrolment & login endpoints (model fields only), Google OIDC (P1), contact change flow (FR-IDN-008), breached-password API (TO-02; a local common-password list is used) | `tests/identity/` — `test_login_and_passwords.py` (12), `test_signup_and_verification.py` (8), `test_totp_crypto.py` (10), `test_seeds_and_audit.py` (4); e2e `identity.integration.spec.ts` | Yes | No |
| sessions | `sessions_0001`, `sessions_0002_partition_rls` (devices, user_devices, auth_sessions, network observations, login_attempts) | 12 | Yes — opaque sessions, device trust + OTP, device/session caps, replacement quota, idle/absolute timeouts, remember-device, stolen-cookie/UA-drift handling, support kill/reset with step-up | Lab-device enrolment (SES-13..16); Redis session cache `sess:{hash}` | `tests/sessions/test_sessions_and_devices.py` (16), `test_restrictions_and_hooks.py` (4) | Yes | No |
| security | `security_0001_security` (18 tables) | 70 | Yes — signals, risk engine (rules/versions/evaluations, shadow/enforce), HC-01/HC-02 + HC-T1..T3, restrictions L1–L4, cases, unblock requests + appeals, dual approval, FP exceptions + entitlement credit, trusted networks, incidents, reports, circuit breaker | Case attachments + student uploads (need S3 presign adapter); breached-password signal (TO-02) | `tests/security/` — `test_scn_sessions.py` (12), `test_scn_sharing.py` (15), `test_scn_unblock.py` (10), `test_rules_unit.py` (11), `test_controls_reports.py` (11), `test_seed_and_guard.py` (2); e2e `security-console.integration.spec.ts` | Yes | No |
| rbac | `rbac_0001..0003` (roles, permissions, role_permissions, role_grants, approval_requests + seed + RLS) | 8 | Yes — allow-only grants with scopes/expiry, permission checker, dual control for privileged grants (`202 approval_pending`) | Break-glass elevation (catalogue marks `BG` only) | `tests/rbac/test_rbac.py` (9) | Yes | No |
| orgs | `orgs_0001_orgs` (6 tables) | 28 | Yes — organizations, batches, memberships, invitations (TI-05), roster CSV import (`csv_text` inline), staff grants at batch scope | XLSX upload via MED-02 presign; shortlists, placement drives (FR-ORG-016/019) | `tests/orgs/test_orgs.py` (9); e2e `staff-portals.integration.spec.ts` (roster import) | Yes | No |
| catalog | `catalog_0001_catalog` (7 tables) | 19 | Yes — public catalogue (published only), authoring with draft/published versions, modules, lessons, assets, resources, review/publish workflow | Org-private trainer courses (P1) not separately verified | `tests/catalog/test_catalog.py` (4), `test_seed.py` (2); e2e `learning-commerce.integration.spec.ts` | Partial (thin coverage) | No |
| media | `media_0001_playback` (`playback_sessions` partitioned) | 7 | Yes — upload credentials (VdoCipher + S3 presigned POST), asset status, playback token with stream cap/takeover, heartbeats, stop, short-lived downloads | GuardDuty scan-result consumer; L2 owner verification hook before playback; real VdoCipher not verified | `tests/media/test_media.py` (7) | Yes | No |
| learning | `learning_0001_learning` (5 tables) | 24 | Yes — enrolments, lesson delivery via `app.core.access`, completion, version migration, assignments + submissions + grading + release + override, certificates + PDF + public verify | Attendance for live links; LinkedIn add (P1); bookmarks/notes (P1) | `tests/learning/test_learning.py` (7) | Partial | No |
| placement | `placement_0001`, `placement_0002_path_step_test_fk` (11 tables) | 23 | Yes — topics, question bank with versions + review lifecycle, companies + company paths, practice sessions (untimed, reveal), review, recommendations | Question import (PLC-12..14), item stats (PLC-15), goals / learning path (PLC-28..31), question reports (PLC-33..35), mentoring (PLC-36..46), résumés (PLC-47..52); mastery still interim EWMA (backlog A6) | `tests/placement/test_placement.py` (10), `test_seed.py` (2); e2e `student-learning.integration.spec.ts` (practice) | Partial | No |
| assessments | `assessments_0001_assessments` (11 tables) | 26 | Yes — test authoring/validate/publish, sections + rules, assignments, overrides, server-authoritative attempts, autosave, sections, submit, resume, rebind (OTP) + override, results release | ASM-17 regrade, ASM-18 invalidate, ASM-19/20 integrity review queue, ASM-22 report, ASM-23 leaderboard, per-endpoint rate limits; coding questions in tests (backlog A4); deadline sweeper on Celery beat | `tests/assessments/test_attempts.py` (20); e2e `student-learning.integration.spec.ts` (timed test) | Yes | No |
| coding | `coding_0001_coding` (6 tables) | 13 | Yes — COD-01..03, 06..08, 10, 13..16, 19 + studio problem detail; run/submit queued, judge worker, envelope-encrypted hidden cases (DB blob store) | COD-04/05 drafts, COD-09 SSE, COD-11 diff, COD-12 editorial, COD-17, COD-18, COD-20..22 review/similarity; S3 `td-judge-private` blob store | `tests/coding/test_flow.py` (12), `test_judge.py` (12), `test_studio.py` (3) | Yes | No |
| commerce | `commerce_0001_commerce` (16 tables) | 46 | Yes — COM-01..12, 15, 17..36, 38..41, 43..46; checkout, Razorpay webhooks (WH-01) with re-fetch, coupons, refunds, subscriptions, invoices + credit notes, contracts, reconciliation runs, disputes, finance revenue report, `/finance/approval-requests` | COM-13, COM-14 (P1), COM-16 invoice PDF, COM-37 GST export, COM-42 B2B invoice; Cashfree API calls; webhook processing on Celery `critical` queue (backlog A7) | `tests/commerce/test_checkout_webhooks.py` (11), `test_coupons_refunds_subscriptions.py` (8); e2e `learning-commerce.integration.spec.ts` (checkout, test mode) | Yes | No |
| entitlements | `entitlements_0001_entitlements` (`entitlements`, `entitlement_events`, `seat_waitlist`) | 10 | Yes — ENT-01..10, `app.core.access` checker registration, seats + waitlist | Resource-parent resolvers from catalog/coding (backlog A1); learning usage provider (A2) | `tests/entitlements/test_access_and_seats.py` (8) | Yes | No |
| analytics | `analytics_0001_analytics` (19 tables incl. partitions) | 11 | Yes — ANL-01..10, 12: ingest + beacon, config, `/me/analytics/*`, reports; time model (union of intervals), mastery, aggregates | ANL-11 commerce, ANL-13..15 exports; several report fields return `null` pending interfaces; Celery beat wiring (backlog A3) | `tests/analytics/test_ingest.py` (13), `test_pipeline.py` (13), `test_timemodel.py` (14) | Yes | No |
| notifications | `notifications_0001_notifications` | 4 | Partial — NTF-01..03 inbox, NTF-06 batch announcement; email via SMTP | NTF-04/05 preferences, NTF-07..09 templates, NTF-10 SSE; SES and MSG91 adapters | `tests/notifications/test_notifications.py` (5) | Yes | No |
| admin | `admin_0001_admin` (policy_settings, feature_flags, privacy_requests, retention_policies) | 22 | Yes — ADM-07..16 (policies, flags, dual-control approvals), PRV-01..13 privacy requests | Erasure ledger / retention purge execution; break-glass | `tests/admin/test_admin.py` (4) | Partial (thin coverage) | No |
| audit | `audit_0001_audit_log` (`audit_outbox`, `audit_log` partitioned) | 3 | Yes — hash-chained append-only log, sealer, AUD-01..03 read API (queries audited) | S3 Object Lock anchoring | `tests/audit/test_audit_api.py` (5), `test_chain.py` (5), `test_sealer_db.py` (6) | Yes | No |
| support (tickets) | — (no tables) | 0 | **No** — only `/support/unblock-requests` (security module) and support session/device actions (sessions module) exist | Tickets, macros, CSAT, SLA (FR-SUP-001..004, 008) | — | No | No |

## 2. Web portals and feature areas (`apps/web`)

All portals exist as Next.js routes under `apps/web/src/app/` with feature code in `apps/web/src/features/`. Several features compile against response shapes marked "assumed" in `lib/types.ts` (backlog §C); those are scored `Partial` until contract tests against the generated OpenAPI exist.

| Area (route prefix) | Feature dir(s) | Implemented | Backend available? | Tests (evidence) | Tested | Deployed |
|---|---|---|---|---|---|---|
| Public site, auth, guardian consent, invite, verify (`/(public)/*`, `/login/*`, `/verify/[certificate_id]`) | `auth`, `catalog`, `unblock` | Yes | Yes | `src/features/auth/components/auth.test.tsx`, `src/features/auth/lib/validation.test.ts`, `src/features/unblock/components/unblock.test.tsx`; e2e `auth-pages.spec.ts`, `smoke.spec.ts`, `identity.integration.spec.ts` | Yes | No |
| Student dashboard, account, devices, privacy (`/app`, `/app/settings/*`, `/app/account-status`, `/app/access`) | `dashboard`, `account` | Yes | Yes | `src/features/account/components/account.test.tsx`; e2e `identity.integration.spec.ts` | Yes | No |
| Catalogue, player, learning, certificates (`/app/courses`, `/app/learn/*`, `/app/learning`, `/app/certificates`) | `catalog`, `player`, `learning` | Yes | Yes | `catalog.test.tsx`, `player.test.tsx`, `learning.test.tsx`; e2e `learning-commerce.integration.spec.ts` | Yes | No |
| Checkout, orders, billing (`/app/checkout/*`, `/app/orders/*`, `/app/billing`) | `commerce` | Yes | Yes (Razorpay fake in dev) | `commerce.test.tsx`; e2e `learning-commerce.integration.spec.ts` | Yes | No |
| Practice (`/app/practice/*`; company paths removed 2026-11-14) | `practice` | Yes | Yes | `src/features/practice/practice.test.tsx`; e2e `student-learning.integration.spec.ts` | Yes | No |
| Timed tests / attempts (`/app/tests/*`, `/app/attempts/*`) | `assessment` | Yes (unsaved answers in localStorage; IndexedDB Planned — backlog D) | Yes | `assessment.test.tsx`, `autosave-queue.test.ts`, `resume.test.ts`, `server-clock.test.ts`; e2e `student-learning.integration.spec.ts` | Yes | No |
| Coding workspace (`/app/coding/*`) | `coding` | Yes (Monaco from `/public/vendor`) | Yes (fake judge in dev) | `src/features/coding/coding.test.tsx` | Yes | No |
| Progress (`/app/progress`; `/app/analytics` removed 2026-11-14) | `progress` | Yes (recharts bundle not lazy-loaded yet) | Yes | `src/features/progress/progress.test.tsx`, `src/lib/analytics/analytics.test.ts` | Yes | No |
| Onboarding, path, interview prep, résumé (`/app/onboarding`, `/app/path`, `/app/interview-prep`, `/app/resume`; diagnostic, mentoring and bookmarks pages removed 2026-11-14) | various | Partial (screens) | **No** for goals/path, mentoring, résumé, bookmarks (placement/learning Planned) | — | No | No |
| Student support tickets (`/app/support/*`) | `support` | Partial (screens) | **No** (no ticket API) | `support.test.tsx` (UI only) | Partial | No |
| Trainer portal (`/trainer/*`) | `trainer` | Yes | Mostly (integrity review, regrade, report Planned in API) | `trainer.test.tsx`; e2e `staff-portals.integration.spec.ts` (assign test) | Yes | No |
| College coordinator portal (`/college/*`) | `college` | Yes | Mostly (shortlists Planned) | `college.test.tsx`, `src/features/college/lib/roster.test.ts`; e2e `staff-portals.integration.spec.ts` (roster import) | Yes | No |
| Placement mentor portal (`/mentor/*`): **removed 2026-11-14** | — | — | — | `mentor.test.tsx` (UI only) | Partial | No |
| Content studio (`/studio/*`) | `studio` | Yes, except CMS-006 question import (`/studio/questions/import`): **Planned** (placeholder screen only) | Yes (question import, error reports Planned) | `studio.test.tsx` | Yes | No |
| Support desk (`/desk/*`) | `support` | Partial | Unblock forwarding + session/device actions only; tickets **No** | `support.test.tsx` | Partial | No |
| Finance console (`/finance/*`) | `finance` | Yes | Yes | `finance.test.tsx` | Yes | No |
| Security console (`/security/*`) | `security-admin` | Yes | Yes | `security-admin.test.tsx`; e2e `security-console.integration.spec.ts` | Yes | No |
| Super admin (`/admin/*`) | `admin` | Yes | Yes (break-glass **No**) | `admin.test.tsx` | Yes | No |
| Platform: BFF proxy, CSRF, middleware, API client | `src/lib/*`, `src/middleware.ts` | Yes | — | `src/lib/bff/proxy.test.ts`, `src/lib/api/client.test.ts`, `src/lib/api/errors.test.ts`, `src/middleware.test.ts`, `src/components/ui/ui.test.tsx` | Yes | No |

## 3. Functional requirement areas (`product-requirements.md` §4)

| FR area | Implemented | Notable gaps | Evidence |
|---|---|---|---|
| FR-IDN (001–013) | Partial | Passkey/WebAuthn flows (001/005/006), Google OIDC (011, P1), contact-change re-auth (008), certificate identity confirmation (013) | `tests/identity/*`; e2e `identity.integration.spec.ts` |
| FR-SES (001–012) | Yes | Lab devices (SES-13..16); Redis session cache | `tests/sessions/*`, `tests/media/test_media.py` (stream cap), `tests/security/test_scn_sessions.py` |
| FR-SEC (001–010) | Yes | Breached-password signal; attachment uploads | `tests/security/*` (all 20 SCN rows except SCN-02 explicit) |
| FR-ORG (001–019) | Partial | 016 shortlists, 019 placement drives; XLSX import; seat assignment on acceptance via entitlements (Planned per orgs router) | `tests/orgs/test_orgs.py`; e2e `staff-portals.integration.spec.ts` |
| FR-RBAC (001–004) | Yes | — | `tests/rbac/test_rbac.py`, `tests/core/test_route_guard_and_auth.py` |
| FR-CAT (001–009), FR-MED (001–002) | Yes (core) | FR-CAT-009 org-private courses unverified; DRM only through real VdoCipher (not verified) | `tests/catalog/*`, `tests/media/test_media.py` |
| FR-LRN (001–009) | Partial | 008 LinkedIn (P1), 009 bookmarks/notes (P1) | `tests/learning/test_learning.py` |
| FR-PLC (001–018) | Partial | 008–010 interview prep / mentoring, 013 diagnostic flow, 014 goals, 015 résumé, 016 learning path, 017 question reports, 018 import; 006 mastery on interim EWMA | `tests/placement/*` |
| FR-ASM (001–015) | Partial | 011 regrade, 012 invalidation, 013 accommodations, 015 leaderboard; coding questions in tests (FR-COD-007) | `tests/assessments/test_attempts.py` |
| FR-COD (001–010) | Partial | 007 in tests, 008 similarity, 009 snapshot replay; outage queue behaviour depends on real Judge0 | `tests/coding/*` |
| FR-COM (001–014) | Yes (core) | 006 plan change (P1); invoice PDF; GST export | `tests/commerce/*` |
| FR-ENT (001–005) | Yes | p95 ≤ 20 ms not load-tested; cache/decision cache (backlog A7) | `tests/entitlements/test_access_and_seats.py` |
| FR-ANL (001–005) | Yes (core) | Commerce reports, exports; Celery beat wiring | `tests/analytics/*` |
| FR-NTF (001–005) | Partial | SES/SMS real adapters, preferences (003), templates/delivery status (005) | `tests/notifications/test_notifications.py` |
| FR-SUP (001–008) | Partial | Ticketing (001–004, 008) not implemented; 005–007 (lookup, session/device actions, lift L1/L2) implemented in sessions/security | `tests/sessions/test_sessions_and_devices.py` (support kill/reset), `tests/security/test_scn_unblock.py` |
| FR-PRV (001–006) | Partial | Erasure ledger / retention purge execution | `tests/admin/test_admin.py`, `tests/identity/test_signup_and_verification.py` (guardian consent) |
| FR-ADM (001–007) | Partial | 005 break-glass | `tests/audit/*`, `tests/admin/test_admin.py` |

Non-functional: see §7. Authorization matrix (6,405 requests/run), axe on 16 views, and a local k6 autosave smoke now exist; production-scale load evidence does not.

## 4. Fakes and adapters awaiting credentials

Every fake registers with `app.core.startup_checks.register_fake_adapter`, so the API **refuses to start when `APP_ENV` is production** with a fake selected. Real adapters are implemented against vendor docs but **not verified against the providers** (no credentials in this environment).

| Integration | Dev/test fake | Real adapter | Switch to real | Status |
|---|---|---|---|---|
| Payments — Razorpay | `FakePaymentProvider` (`apps/api/app/modules/commerce/gateway.py`) — selected by `PAYMENTS_PRIMARY_PROVIDER=fake` or installed by tests via `set_gateway` | `RazorpayGateway` (same file) | `PAYMENTS_PRIMARY_PROVIDER=razorpay` + `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` (`_PREVIOUS` for rotation), `RAZORPAY_API_BASE`; GST/seller: `SELLER_GSTIN`, `SELLER_STATE_CODE`, `RAZORPAY_ACCOUNT_ID` (backlog E) | Awaiting credentials |
| Payments — Cashfree (fallback, P1) | — | `CashfreeGateway` (webhook signature only; API calls raise) | `PAYMENTS_FALLBACK_PROVIDER_ENABLED=true`, `CASHFREE_APP_ID`, `CASHFREE_SECRET_KEY` | Partial |
| Video — VdoCipher | `FakeVideoProvider` (`apps/api/app/modules/media/providers.py`) — `VDOCIPHER_MODE=stub|fake` (default `stub`) | `VdoCipherProvider` | `VDOCIPHER_MODE` set to any value other than `stub`/`fake` (e.g. `live`), `VDOCIPHER_API_SECRET`, `VDOCIPHER_API_BASE_URL` | Awaiting credentials |
| Code judge — Judge0 | `FakeJudgeAdapter` (`apps/api/app/modules/coding/judge_gateway/fake.py`) — `JUDGE_PROVIDER=fake` (default) | `judge_gateway/judge0.py` (worker-judge only) | `JUDGE_PROVIDER=judge0_cloud` (or `judge0`; `judge0_selfhosted` for phase 2), `JUDGE0_BASE_URL` (alias `JUDGE0_URL`), `JUDGE0_API_KEY`, `JUDGE0_AUTH_HEADER` | Awaiting credentials |
| Email — SES | `MemoryEmailAdapter` (`EMAIL_PROVIDER=fake|console|memory`); local SMTP to Mailpit (`SmtpEmailAdapter`, `SMTP_HOST=localhost|mailpit`) is flagged as a dev adapter (`apps/api/app/modules/notifications/adapters.py`) | `SmtpEmailAdapter` against a real relay works today; `ses` → `UnavailableAdapter` (Planned, raises at send) | `EMAIL_PROVIDER=smtp` + `SMTP_HOST`, `SMTP_PORT`, `EMAIL_FROM_ADDRESS`, `EMAIL_FROM_NAME` (SES SMTP endpoint), or implement `ses` | SES adapter Planned |
| SMS — MSG91 (DLT) | `ConsoleSmsAdapter` (`SMS_PROVIDER=console|fake`, default `console`) | none (`msg91` → `UnavailableAdapter`, Planned) | Implement adapter, then `SMS_PROVIDER=msg91` | Adapter Planned |
| Object storage — S3 | SeaweedFS/MinIO via `S3_ENDPOINT_URL=http://localhost:9000` (`apps/api/app/modules/media/storage.py`, stdlib SigV4) | Same code against AWS (virtual-hosted, no endpoint override) | `AWS_REGION`, `S3_BUCKET_UPLOADS`, `S3_BUCKET_CONTENT`, `S3_BUCKET_CERTIFICATES`; static `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` today — ECS task-role credentials need `boto3`/`botocore` (backlog E) | Partial |
| Malware scan — GuardDuty | `FakeMalwareScanner` (marks uploads clean) when `S3_KMS_KEY_ID=local` | `GuardDutyScanner` (awaits result consumer `media.service.apply_scan_result`; EventBridge consumer Planned) | `S3_KMS_KEY_ID=<kms key>` + GuardDuty Malware Protection | Consumer Planned |
| KMS — app envelope keys | Local keyring fallback `TD_LOCAL_ENVELOPE_KEY` / `local` outside production (`apps/api/app/core/crypto.py`) | Versioned keys from env (Secrets Manager) | `TD_K_*_V{n}` + `TD_K_*_ACTIVE_VERSION`; KMS wrapping via `TD_APP_ENVELOPE_KMS_KEY_ID` is Planned | KMS wrapping Planned |
| KMS — hidden test cases | DB blob store `coding_test_case_blobs` (`apps/api/app/modules/coding/blobstore.py`) with KEK from env (`apps/api/app/modules/coding/crypto.py`) | S3 `td-judge-private` + KMS `GenerateDataKey` | `TD_K_TESTCASE_KEY_V{n}`, `TD_K_TESTCASE_ACTIVE_VERSION` (worker-judge only) | S3/KMS Planned |
| Audit anchoring | — | S3 Object Lock anchor | — | Planned |
| Observability | disabled when empty | OTLP / Sentry | `OTEL_EXPORTER_OTLP_ENDPOINT`, `SENTRY_DSN` | Config only |

## 5. Owner scenarios SCN-01..SCN-20

Definitions: `testing-and-acceptance-criteria.md` §4.2–§4.21. Coverage found by searching test names/markers (`scn01`…`scn20`, `SCN-nn`) in `apps/api/tests` and `apps/web`. All API scenario tests live in `apps/api/tests/`; none of the Playwright specs reference an SCN id.

| SCN | Scenario | Covering tests | Status |
|---|---|---|---|
| SCN-01 | Laptop, then phone | `security/test_scn_sharing.py::test_scn01_laptop_then_phone_daily_overlap_scores_l0` | Covered |
| SCN-02 | Several tabs on the same laptop | No SCN-tagged test. Related building blocks: `analytics/test_timemodel.py::test_example1_overlapping_windows_union_not_sum`, `::test_union_invariant_random_multi_tab`, `::test_hidden_tab_and_keepalive_earn_no_active_credit`; `media/test_media.py::test_stream_cap_conflict_takeover_and_heartbeats`. No test for the same attempt in two tabs / 5–7 tab boundary / "no security signal" | **Partial (uncovered end-to-end)** |
| SCN-03 | Two students on the same college Wi-Fi | `security/test_scn_sessions.py::test_scn03_campus_wifi_many_students_no_lockout_no_signals` | Covered |
| SCN-04 | Wi-Fi to mobile data | `security/test_scn_sessions.py::test_scn04_network_change_keeps_session_and_ua_family_change_is_to08`; `sessions/test_sessions_and_devices.py::test_network_observation_on_cluster_change` | Covered |
| SCN-05 | Concurrent use from two unrelated devices | `security/test_scn_sharing.py::test_scn05a_relayed_otp_sharer_l1_l2_then_l3`, `::test_scn05a2_two_days_l2_only_and_5c_mobile_sharer_under_detected` | Covered (5a, 5a-2, 5c; 5d via SCN-09e) |
| SCN-06 | Several accounts on the same browser/device | `security/test_scn_sharing.py::test_scn06_shared_pc_lab_pc_minor_and_restricted_device_reuse` | Covered |
| SCN-07 | Geographically inconsistent locations | `security/test_scn_sharing.py::test_scn07_geo_inconsistent_broadband_sh10_only_and_mobile_excluded`, `::test_scn07_first_login_outside_india_is_to09_notice_only` | Covered |
| SCN-08 | Legitimate student on a VPN | `security/test_scn_sharing.py::test_scn08_vpn_student_capped_and_tor_adds_takeover_only`; `security/test_rules_unit.py` (SCN-08 marker) | Covered |
| SCN-09 | Automatic restriction by a high-confidence rule | `security/test_scn_sharing.py::test_scn09e_*`, `test_scn09f_*`, `test_scn09d_*`, `test_scn09h_*`, `test_scn09i_*`, `test_scn09c_deferral_keeps_attempt_session`, `test_cb03_*`, `test_cb06_*` (circuit breaker, 9g); `security/test_scn_sessions.py::test_scn09c_stuffing_source_then_failed_otp_is_hct2_protect_lock` | Covered |
| SCN-10 | Unblock request with a legitimate explanation | `security/test_scn_unblock.py::test_scn10_unblock_request_validation_limits_and_device_revocation`, `::test_scn10_rate_limits_three_per_30_days_and_form_loads`; e2e `identity.integration.spec.ts` ("restricted account → request a review") | Covered |
| SCN-11 | Administrator approves and revokes suspicious sessions | `security/test_scn_unblock.py::test_scn11_review_lift_reverify_and_fresh_login`, `::test_scn11_high_risk_l4_needs_distinct_second_approver`, `::test_scn11_send_back_withdraw_and_72h_expiry`; e2e `security-console.integration.spec.ts` | Covered |
| SCN-12 | Administrator rejects with a reason | `security/test_scn_unblock.py::test_scn12_reject_appeal_to_different_reviewer_and_final`, `::test_scn12_rejection_then_auto_expiry_reverify_closes_moot`, `::test_scn12_no_appeal_in_14_days_closes_rejected_final` | Covered |
| SCN-13 | Blocked user calls private content APIs directly | `security/test_scn_sessions.py::test_scn13_l3_and_l4_principals_get_403_on_every_non_allowed_route`, `::test_scn13_l3_entitlement_locks_and_cache_column`; `media/test_media.py::test_restricted_principal_cannot_play` | Covered |
| SCN-14 | Same payment webhook delivered repeatedly | `commerce/test_checkout_webhooks.py::test_scn14_same_webhook_delivered_repeatedly_is_processed_once` | Covered |
| SCN-15 | Inactive tab stays open for hours | `security/test_scn_sessions.py::test_scn15_idle_session_expires_and_background_poll_does_not_extend`; `analytics/test_timemodel.py::test_example2_tab_left_open_for_hours_no_credit_beyond_idle`; `sessions/test_sessions_and_devices.py::test_idle_timeout_and_engaged_activity` | Covered |
| SCN-16 | Browser crash during a timed assessment | `security/test_scn_sessions.py::test_scn16b_relogin_same_device_replaces_old_session`; `assessments/test_attempts.py::test_crash_resume_same_device_reattaches_without_rebind`; `analytics/test_pipeline.py::test_crash_closes_interval_with_grace_in_db`; e2e `student-learning.integration.spec.ts` (refresh-resume) | Covered |
| SCN-17 | Multiple tabs used to manipulate time tracking | `security/test_scn_sessions.py::test_scn17_time_manipulation_is_integrity_only`; `analytics/test_ingest.py` (plausibility / rejections) | Covered |
| SCN-18 | Administrator accesses another institution's records | `security/test_scn_sessions.py::test_scn18_cross_org_access_404_and_ab09_alert`; `core/test_rls.py`; `orgs/test_orgs.py` | Covered (full ID-swap matrix Planned, backlog §F) |
| SCN-19 | Changing a session identifier or reusing a revoked session | `security/test_scn_sessions.py::test_scn19_altered_revoked_and_replayed_tokens`, `::test_scn19_drift_and_minor_replay_is_deterministic`, `::test_scn19_unknown_token_flood_ab07_throttles_source`; `sessions/test_sessions_and_devices.py::test_stolen_cookie_replay_revokes_only_that_session` | Covered |
| SCN-20 | Student disputes a false-positive sharing decision | `security/test_scn_unblock.py::test_scn20_false_positive_exception_suppression_and_credit`, `::test_scn20_variant_fp_override_of_recommend_l4_needs_second_approval` | Covered |

**Summary: 19 of 20 scenarios have dedicated API tests; SCN-02 is only partially covered by component tests.** No scenario is verified in a deployed environment, and the Playwright suites that touch SCN-10/11/16 require the `@integration` stack.

## 6. Top gaps (feed for Stage 10/11 planning)

1. **No support-ticket and mentoring backend** while `/app/support`, `/desk/tickets`, `/mentor/*` screens exist (backlog §C).
2. **SCN-02** needs a dedicated multi-tab test (same attempt in two tabs, 5/7-tab boundary, no security signal).
3. **Third-party adapters unverified**: Razorpay, VdoCipher, Judge0; **SES and MSG91 adapters not written**; S3 task-role credentials need `boto3`; KMS wrapping Planned.
4. **Celery beat wiring** for analytics jobs, assessment deadline sweeper, webhook `critical` queue (backlog A3, A4, A7).
5. **Assessment integrity tooling**: regrade, invalidation, integrity queue, leaderboard; coding questions inside tests.
6. **No deployment or staging-scale load evidence.** Accessibility, authorization matrix and local load smoke now exist (§7).

## 7. Stage 10 final integration verification (2026-11-03)

Details: `qa-report-e2e.md` §0 (fixes, fixtures, load table) and `qa-report-backend.md`.

| Gate | Result |
|---|---|
| API `pytest`, fresh DB `techdrona_test_final` | **559 passed, 0 failed, 0 skipped** (9 min 34 s). Baseline 540 + the B1/B4, B2, autosave-batch, pool-env and seed-fixture tests |
| `ruff check`, `ruff format --check`, `mypy app` | clean |
| Web `lint` / `typecheck` / `test` / `build` | lint 0 warnings, typecheck clean, `npm test` **36 files / 345 tests passed**, `npm run build` OK. Under full parallel load a few UI tests have hit the 5 s per-test timeout. Each passes alone, and the last full run was 345/345. `ProgressDashboard` (recharts, 1.3–4 s alone) now has a 15 s timeout |
| Playwright, chromium, `--workers=1`, one pass from one `scripts/reset-dev-data.ps1` seed | **33 passed / 0 failed / 0 skipped** (23 `@integration`) |
| k6 autosave smoke, 200 VUs × 2 min, local laptop | 0 × 500 in every run after the fixes; client p95 ranged 334 ms – 1.75 s across identical runs (best run: server p95 261 ms). **The 300 ms p95 target is not reliably met locally**; it needs staging-sized infrastructure |

Closed in this pass:

- **B1.** DB pool exhaustion returns `503` + `Retry-After`. Pool and pre-ping are configured through env. Compose sizing: 4 workers × (20+5), `max_connections=200`.
- **B2.** The fake gateway's `checkout.test_payment` works end to end. Paid checkout E2E is green.
- **B3.** Separate DEV fixtures, plus the `reset-dev-data.ps1` script and the E2E env file.
- **B4.** Client disconnect returns 499 and is logged at info.
- **B5.** Local `.env` uses the `fake` provider.
- **W10.** Table scroll region is keyboard-focusable.
- **Autosave.** One multi-row upsert and a lean answer-shape query.

Still open:

- Load at the NFR target on real infrastructure.
- Principal caching to drop the separate resolver transaction.
- The `mobile` Playwright project was not run.
- W8 and W9 (web) from the E2E report.

## 8. Final audit verification (2026-11-04/06)

Full report: `docs/audit/FINAL-AUDIT-REPORT.md`. It covers the feature-by-feature checklist, the counts per severity, the deferred items and the owner decisions.

Audit Phase A found **205 issues: 4 Critical, 48 High, 87 Medium and 66 Low.** Final state after fix waves 1–3 and this verification:
- **177 fixed and retested**, including all 4 Critical and 47 of the 48 High.
- **16 partly fixed:** the remainder is a spec-Planned feature or waits on a decision.
- **7 deferred:** DB-08/09/10 schema hygiene, notification templates and preferences, passkey and Google sign-in, contact change.
- **2 not reproduced.**
- **3 need an owner decision.**

| Gate | Result |
|---|---|
| API `pytest`, fresh DB `techdrona_final_verify` | **813 passed, 0 failed, 0 skipped** (12 min 20 s) |
| `ruff check` / `ruff format --check` / `mypy` | clean / 442 files formatted / no issues in 232 files |
| Web `lint` / `typecheck` / `build` | 0 warnings / clean / OK |
| Web `vitest` | Before the host reboot: 628/628 (default workers). After it: 630/630 with `--maxWorkers=4`. The default parallelism hit 5 s/15 s per-test timeouts on the loaded host, with no assertion failures |
| Playwright `chromium`, `--workers=1`, fresh reset | **48 passed / 0 failed / 0 skipped** (three green passes, one after the reboot) |
| Playwright `mobile` (Pixel 7), `--workers=1`, fresh reset | {MOBILE} |
| Playwright audit journeys (`e2e/_audit`, chromium) | **4 passed / 0 failed** (ID1, ID2, J1, ST1) |

Fixed during the verification:
- **Mobile app bug:** the learner tab bar covered the practice and timed-test action bars on phones; it is now hidden on the Focus routes.
- **Test-builder coding picker:** it uses COD-24, so batch trainers can pick problems.
- **E2E harness:**
  - Pixel 7 UA at the browser level (unload beacons had tripped TO-08).
  - TOTP replay-safe sign-in.
  - Selector drift.
  - The finance, content and admin accounts and a pending approval are added to the e2e fixtures, so no spec is skipped any more.

Still open: see the report §6–§8. The real provider adapters (SES, MSG91, Razorpay live, VdoCipher, Judge0, GuardDuty) are unverified without credentials. There is still no staging or production deployment evidence.

## Changelog

| Date | Change |
|---|---|
| 2026-11-03 | v0.1 — created for Stage 10 from code inspection (routers, migrations, adapters) and test inventory. |
| 2026-11-03 | v0.2 — §7 final integration pass: B1–B5 fixed, dev fixtures and reset script, full-suite numbers, load results. |
| 2026-11-03 | v0.3 — audit fix wave 3: CMS-006 question import marked Planned (webstaff request 18). |
| 2026-11-06 | v0.4 — §8 final audit verification: issue counts, final gate numbers, link to `audit/FINAL-AUDIT-REPORT.md`. Mobile Playwright now run (closes the §7 open item). |
