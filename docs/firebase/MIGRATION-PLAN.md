# Tech Drona LMS: Postgres to Google Firebase migration plan

Status: **PLAN ONLY**. No code has been changed. Author: planning agent, 2026-11-08.
Inputs: `docs/redesign/BRIEF.md`, `docs/single-company/REMOVAL-PLAN.md` §8 (D1–D10), and the
owner decision of 2026-11-08 below. Code facts come from CodeGraph and from read-only greps of
`apps/api` and `apps/web`.

## 0. Owner decision and what it means

Firebase project **`techdrona-lms`** (authDomain `techdrona-lms.firebaseapp.com`, projectId
`techdrona-lms`, storageBucket `techdrona-lms.firebasestorage.app`). Spark (free) now, Blaze later.
The owner chose all four of these:

1. **Firebase Analytics** (GA4) in the web app.
2. **Firebase Auth with Google sign-in.**
3. A **public demo link** on Firebase Hosting.
4. A **full move of LMS data from Postgres to Firestore.** The owner confirmed this after being
   told it is a near-total backend rewrite.

Items 1–3 do not depend on item 4. They can ship in about two weeks, on Spark (Phase 1). Item 4
is the expensive part: an estimated 30–42 engineer-weeks (§6). This plan treats it as a
strangler migration. Each module moves on its own, behind a flag, and Postgres stays the source
of truth for a domain until that domain is cut over.

### Hard platform facts (verify against current Firebase pricing pages before committing)

| Topic | Spark (free) | Blaze (pay as you go) |
|---|---|---|
| Server code: Cloud Functions, Cloud Run, App Hosting | **Not available** | Available, with free monthly quotas |
| Hosting rewrites to Cloud Run or Functions | **Not available** (static files only) | Available |
| Next.js SSR on Hosting (web-frameworks or App Hosting) | **Not available** (needs Functions or Cloud Run) | Available |
| Cloud Storage for a new project (`*.firebasestorage.app`) | **Not available** | Available |
| Firestore | 1 GiB stored, 50k reads, 20k writes, 20k deletes per day, 10 GiB/month egress | Same free tier, then per-operation billing |
| Firestore managed backups, PITR, `gcloud firestore export` | **Not available** (export needs a GCS bucket) | Available |
| BigQuery export extension, Search extensions (Algolia or Typesense) | **Not available** | Available (plus third-party cost) |
| Firebase Auth (Google provider) | Available | Available |
| Firebase Analytics (GA4) | Available (free) | Available |

Firestore Admin SDK calls from FastAPI **bypass security rules**. Every authorization rule that
Postgres RLS enforces today must therefore move into the FastAPI code (§1.4, §3.4).

---

## 1. Current data layer inventory

### 1.1 Shape of the backend

* FastAPI modular monolith, 22 modules under `apps/api/app/modules/*` plus `app/core`.
  About 74k lines of Python in the modules and 3.8k in core.
* **510 HTTP operations** on 451 paths (`apps/api/openapi.json`).
* **163 SQLAlchemy tables** (including `core.outbox_events` and `core.idempotency_keys`).
  Alembic history holds about 214 relations once partitions are counted.
* About **1,870** `session.execute` or `select(` call sites in 100 files, **172** `join` or
  `outerjoin` calls, **22** files with raw `text()` SQL, and about **90** `FOR UPDATE` row
  locks (commerce alone has 31).
* Migrations: about 142 UNIQUE constraints or indexes, about 795 CHECK constraints, about 475
  foreign keys, 1 exclusion constraint (`ex_price_overlap`, gist), 7 triggers, about 25
  `app.*` and `maint.*` SQL functions, and 3 sequences (`commerce_order_number_seq`,
  `support_ticket_number_seq`, `corporate_enquiry_number_seq`). The `invoice_sequences` table
  provides gap-free GST invoice numbers. `audit_log.seq` is an IDENTITY column.
* Tests: 124 test files and about **865 test functions**. Almost all of them run against a
  real Postgres database, and many assert RLS behaviour directly.
* The dev database is tiny: about 28 MB, synthetic data only. Backfill volume is therefore not
  a problem. Correctness is.
* Runtime services (`docker-compose.yml`): postgres, redis (cache and rate limits), redis-queue
  (Celery broker), api, api-webhooks, worker, worker-maintenance, scheduler (beat),
  worker-judge (code sandbox), audit-sealer, web, mailpit and glitchtip. Firestore replaces
  **only postgres**. Redis, Celery, the judge sandbox and S3 (seaweedfs) stay unless replaced
  separately.

### 1.2 Tables per module (163)

| Module (lines of code) | Tables |
|---|---|
| identity (3.2k) | users, user_profiles, user_credentials, mfa_factors, consents, guardian_consents, verification_tokens, password_reset_tokens |
| sessions (2.1k) | auth_sessions, devices, user_devices, login_attempts *(partitioned)*, session_network_observations *(partitioned)* |
| rbac (1.4k) | roles, permissions, role_permissions, role_grants, approval_requests (dual control) |
| orgs (0.7k) | organizations (the single company), org_memberships, batches, batch_members |
| catalog (2.0k) | courses, course_versions, course_modules, lessons, lesson_assets, lesson_topics, resources |
| media (1.7k) | playback_sessions *(partitioned)* |
| learning (5.7k) | enrolments, lesson_progress, certificates, assignments, assignment_sections, assignment_items, assignment_allocations, assignment_submissions, assignment_item_responses, assignment_regrade_requests |
| assessments (6.2k) | tests, test_sections, test_section_rules, test_assignments, test_attempts, attempt_sections, attempt_responses, attempt_events *(partitioned)*, attempt_item_grades, attempt_results, attempt_overrides, attempt_integrity_decisions |
| placement (6.3k) | topics, questions, question_versions *(immutable trigger)*, question_options *(immutable trigger)*, question_media, question_tags, question_reports, question_banks, question_bank_items, practice_sessions, practice_responses, companies, company_paths, company_path_steps, recommendations |
| coding (3.6k) | coding_problems, coding_test_cases, coding_test_case_blobs (encrypted bytea), coding_testcase_content_tokens, coding_reference_solutions, coding_problem_validations, coding_drafts, code_submissions, submission_results, judge_languages |
| paths (2.7k) | learning_paths, learning_path_versions, learning_path_steps, learning_path_version_steps, path_allocations, path_articles, path_step_progress |
| engage (2.1k) | engage_activities, engage_questions, engage_runs, engage_participants, engage_responses |
| mentoring (2.4k) | mentor_slots, mentor_bookings, mentor_notes, interview_feedback, resumes, resume_reviews |
| commerce (7.2k) | products, product_items, plans, prices (exclusion constraint), coupons, coupon_redemptions, orders, order_items, payments, payment_webhook_events, refunds, subscriptions, invoices, invoice_sequences, gst_exports, reconciliation_runs |
| entitlements (1.5k) | entitlements, entitlement_events |
| audit (0.7k) | audit_outbox, audit_log *(partitioned, hash-chained, immutable triggers)* |
| analytics (6.3k) | analytics_events *(partitioned)*, activity_heartbeats *(partitioned)*, engagement_intervals *(partitioned)*, analytics_consumed_events, analytics_dirty_days, analytics_ingest_rejections, analytics_job_state, daily_/weekly_/cohort_learning_aggregates, route_daily_aggregates, topic_mastery, video_watch_coverage, question_item_stats, security_activity_feed_daily, export_jobs |
| security (10.4k) | security_signals *(partitioned)*, risk_evaluations *(partitioned)*, risk_rules, risk_rule_versions, security_counters, security_user_state, account_restrictions, security_cases, case_notes, case_decisions, security_incidents, security_notices, security_bulk_lifts, security_report_exports, unblock_requests |
| support (2.2k) | support_tickets, support_ticket_messages, support_user_notes, corporate_enquiries (D8) |
| notifications (1.0k) | notifications |
| ai (2.2k) | ai_settings, app_settings, ai_tutor_turns, ai_usage (finalize-guard trigger) |
| admin (2.7k) | feature_flags, policy_settings, retention_policies, privacy_requests, erasure_ledger, break_glass_sessions |
| core | outbox_events, idempotency_keys |

**Cross-module model imports** (each one is a coupling that must be cut before a module can
move on its own):

```
admin -> commerce identity rbac security sessions support
analytics -> assessments rbac           assessments -> coding identity orgs placement sessions
commerce -> entitlements identity learning rbac   entitlements -> commerce
learning -> catalog identity orgs placement rbac  media -> catalog identity sessions
mentoring -> entitlements orgs placement          notifications -> commerce identity orgs rbac
paths -> assessments catalog identity learning orgs   placement -> coding orgs
rbac -> identity orgs   security -> admin identity orgs rbac sessions   sessions -> identity orgs
support -> assessments commerce entitlements identity rbac security sessions
(ai, audit, catalog, engage: no cross-module model imports)
```

### 1.3 Transactions that need atomicity (they must stay all-or-nothing)

| Flow | Where | What is atomic today | Postgres mechanisms used |
|---|---|---|---|
| Order fulfilment | `commerce/service.py` `fulfil_order` | lock the order; coupon redemption and cap check; `ent.grant()` per item; `issue_tax_invoice` (next invoice number); audit; `emit_event` (outbox) | `FOR UPDATE`, UNIQUE, `invoice_sequences` upsert, audit_outbox, outbox_events |
| Payment capture or webhook | `commerce/webhooks.py`, `upsert_payment`, `apply_payment`, `confirm_order` | dedupe by gateway event id; payment state machine; fulfil | UNIQUE on event id, `FOR UPDATE` |
| Refund | `create_refund_request`, `execute_refund`, `apply_refund_state` | `refunded_paise <= captured`; revoke entitlements; **revoke certificates (learning)**; credit note number; audit; outbox | `FOR UPDATE` on the order, CHECK constraints, sequence |
| Subscriptions and plan change | `create_subscription`, `apply_subscription_state`, `apply_scheduled_plan_change` | state machine plus entitlement window | `FOR UPDATE` |
| Invoice numbers | `allocate_number` | gap-free per series and fiscal year | `INSERT ... ON CONFLICT DO UPDATE next_value+1` |
| Attempt start | `assessments/attempts.py:374` `start` | one active attempt per user and test; attempt-count limit | `pg_advisory_xact_lock(test:user)` plus a unique index |
| Attempt submit or finalize | `submit_section`, `finalize`, `submit` | freeze responses, score, result row, integrity snapshot | `FOR UPDATE` |
| Grading and publishing | assessments, learning (`structured.py`) | item grades, then a result, then a release (D3: evaluators publish, never their own) | `FOR UPDATE`, SoD checks |
| Entitlements | `entitlements/service.py` `grant` and `revoke` | entitlement row plus `entitlement_events` | `FOR UPDATE` |
| Dual-control approvals | `rbac/service.py` `create_approval_request`, `rbac/router.py` `approve` and `_execute_privileged` | maker ≠ checker (D2: two **different** admins); single execution | `FOR UPDATE`, RLS on approvals |
| Audit chain | `audit/sealer.py` `seal_pending` | single writer; gap-free `seq`; `row_hash = SHA256(prev ‖ canonical(row))`; outbox rows deleted in the same transaction | `pg_try_advisory_xact_lock`, IDENTITY, immutability triggers, a dedicated `td_audit_sealer` DB role |
| AI quota | `ai/store.py:177` `reserve` | per-user message cap (D10: 20) | `pg_advisory_xact_lock` plus a finalize-guard trigger |
| Coding submit | `coding/service.py:536` | one in-flight submission per user | `pg_advisory_xact_lock` |
| Mentor booking | `mentoring/service.py` (10 `FOR UPDATE`) | no double booking of a slot | `FOR UPDATE` |
| Idempotency keys | `core/idempotency.py` | stored replay; 4xx rolled back **to a savepoint** | UNIQUE, savepoints |
| Outbox | `core/outbox.py` `emit_event` and `relay_pending` | event written in the business transaction; relay with row locks | `FOR UPDATE SKIP LOCKED` |

### 1.4 RLS: what it protects and what replaces it

`core/db.py` `tenant_context` sets transaction-local GUCs (`app.user_id`, `app.org_ids`,
`app.is_platform`, `app.actor`, `app.roles`, `app.privacy_tier`). Predicate families come
from `core/migration_helpers.py`:

| Family | Predicate | Example tables | Replacement under the Admin SDK |
|---|---|---|---|
| `O` (owner) | `user_id = app.user_id() OR is_platform` | notifications, resumes, privacy_requests, password_reset_tokens, verification_tokens, playback_sessions, login_attempts, idempotency_keys, analytics_dirty_days | Owner-scoped repository: every query **must** take a `user_id` from the Principal, or require a platform permission |
| `U` / `US` (user plus org staff) | owner, or company staff in the org (`caller_is_org_staff`) | attempt_item_grades, assignment_item_responses, engage_responses, mentor_bookings, question_reports | Repository method takes `(principal, user_id)`. It allows the owner, or staff holding the specific permission (`access.py`) |
| `T` (tenant) | `organization_id ∈ org_ids OR platform` | assignment_allocations, cohort_learning_aggregates, batches | With a single company (D-scope), this reduces to "is company staff with permission X" |
| `TN` (tenant or global) | `organization_id IS NULL OR ∈ org_ids OR platform` | assignments, engage_*, mentor_slots, coupons | Same as `T`; global rows are platform-managed |
| Approval RLS (`rbac_0003`) | approvers see requests | approval_requests | Server check plus the maker ≠ checker test |
| Platform-only reads | audit_log | audit_log | `audit.read` permission check; a separate sealer service account (§3.5) |
| `revoke_app_writes` (append-only) | no UPDATE or DELETE by `td_app` | audit_log, entitlement_events, consents, question_versions | Repository exposes `append()` only; a lint test checks this; the hash chain covers audit_log |

**Honest gap:** RLS is *defence in depth* today. If a service forgets a check, Postgres still
blocks the row. Firestore has nothing equivalent for Admin-SDK traffic, so that second layer
disappears. Planned mitigations:

1. A single `ScopedStore(principal)` façade. A repository cannot be obtained without a
   Principal or a named `system_context(job)`, mirroring `core/db.py`.
2. A static lint test: every repository method on `O`/`U`/`US` collections must either take
   `user_id` or be decorated `@platform_only(permission)`.
3. The existing RLS tests are ported as **authorization tests** at the HTTP level (student A
   cannot read student B's notification, attempt, booking, and so on).
4. `firestore.rules` is deny-all. No browser ever talks to Firestore directly (§3.4).

### 1.5 Partitioned and time-series tables (pg_partman-style maintenance in `core/maintenance.py` / `maint.*`)

audit_log, analytics_events, activity_heartbeats, engagement_intervals, attempt_events,
playback_sessions, login_attempts, session_network_observations, security_signals and
risk_evaluations. They are monthly partitions with a DEFAULT partition; retention is done by
dropping partitions (for example playback 180 days) and `maint.run_retention` /
`purge_expired_rows`.

Firestore replacement: a TTL policy on an `expire_at` field per collection (TTL deletes count
as deletes against the 20k/day quota). High-volume streams are **batched into chunk
documents** (one document per client batch of up to N events) instead of one document per
event, because 20k writes/day on Spark is only about 14 writes a minute.

### 1.6 Search (ILIKE, no full-text indexes in use)

ILIKE is used in `catalog/router.py`, `coding/service.py`, `engage/service.py`,
`paths/service.py`, `placement/bank.py`, `placement/banks.py` and `support/router.py`, plus
admin user search. Firestore has no ILIKE and no full-text search. Options:
(a) small corpora (courses, paths, banks, coding problems, all under about 10k rows): load into a
Redis-cached list and filter in FastAPI; (b) a lowercase `*_lc` field for prefix range queries
(`>= q`, `< q+''`); (c) a `search_terms` array with `array-contains` for single-token
matches; (d) on Blaze, the Typesense or Algolia extension. Recommendation: (a) plus (b). Exact
email lookup uses the uniqueness docs (§3.2).

### 1.7 Aggregates and reports

* Learner, batch, course and platform reports (`analytics/reports.py`: `student_metrics`,
  `batch_report`, `course_report`, `platform_report`, `ingest_health`, the H1–H12 metrics in
  `analytics-event-schema.md`, k-anonymity `k_cell`). These **already read precomputed
  rollups** (daily, weekly and cohort aggregates, topic_mastery, video_watch_coverage,
  question_item_stats, maintained by `analytics/jobs.py` with dirty-day tracking). That
  pattern moves to Firestore unchanged: rollup documents keyed `{user}_{day}` and so on.
* Ad-hoc `GROUP BY` and `func.sum/count` queries are concentrated in `security/reports.py`
  (19), `security/signals.py` (16), `ai/store.py` (14), `commerce/admin.py` (12, revenue and GST),
  `placement/banks.py`, `engage`, `coding`, `admin/accounts.py`, `learning/structured.py`.
  Each one becomes one of: a Firestore `count()`/`sum()`/`avg()` aggregation query (billed at
  1 read per 1,000 index entries), a maintained counter document updated in the same
  transaction, or a nightly rollup job. GST exports and reconciliation (`gst_exports`,
  `reconciliation_runs`) are bounded scans over one month of invoices. That is acceptable.
* On Blaze, the BigQuery streaming export extension can serve heavy finance and security
  reporting.

### 1.8 Uniqueness (about 142 constraints) and sequences

Each one becomes either a **deterministic document ID** (`create()` fails if the document
exists) or a **reservation document** created inside the same transaction. Examples: email and
mobile (`uniq_email/{sha256(normalized)}`), course slug, enrolment
`{userId}_{courseId}`, coupon code, coupon redemption `{couponId}_{userId}`, gateway payment id,
webhook event id, idempotency key `{userId}_{key}`, role grant
`{userId}_{role}_{scope}`, one active attempt per user and test, one response per engage
question per user, and partial unique indexes ("one open X per user") as
`active_x/{userId}` lock documents.

Sequences become counter documents incremented in a transaction (`counters/order_number`,
`counters/support_ticket`, `counters/enquiry`, `invoice_sequences/{series}_{fy}`). They are
gap-free because the counter and the numbered document commit together. Expected throughput is
far below Firestore's roughly 1 sustained write per second per document.

### 1.9 Other Postgres features in use

* **CHECK constraints (about 795)** become Pydantic models in a `schemas_store.py` per module,
  validated on every write. A property-based test feeds the old CHECK cases to the new
  validators.
* **Foreign keys (about 475)**: no referential integrity in Firestore. Parent existence is
  checked inside the write transaction. `ON DELETE CASCADE` becomes explicit delete jobs. A
  nightly `orphan_check` script reports dangling references.
* **Exclusion constraint** `ex_price_overlap`: a transaction reads every price of the plan
  (a small set) and rejects overlapping windows.
* **Triggers**: `trg_set_updated_at` is set in the repository. The immutability triggers on
  `question_versions`/`question_options` become "append-only repository plus content hash".
  `ai_usage_finalize_guard` becomes a transactional state check. The audit immutability
  triggers have **no server-side equivalent** under the Admin SDK; the hash chain plus external
  anchoring takes over (§3.5).
* **Advisory locks** (ai reserve, attempt start, coding submit, audit sealer) become
  transactions on a lock or counter document, or a lease document `locks/{key}`
  `{holder, expire_at}`.
* `FOR UPDATE SKIP LOCKED` job claiming (outbox relay, refund retry, webhook retry) becomes a
  lease field `{status, lease_until, attempts}` claimed in a transaction.
* **Savepoints** (idempotency rolls back business writes on 4xx) do not exist in Firestore.
  Validate first, then write. An idempotency record of a 4xx is written in its own transaction.
* JSONB becomes maps; arrays stay arrays; `inet` and `citext` become normalised strings;
  `bytea` becomes Bytes (under 1 MiB per document). `coding_test_case_blobs` may exceed 1 MiB:
  keep those blobs in S3 (seaweedfs or AWS) or chunk them.
* **Alembic** (73 revision files) is retired module by module. It is replaced by a
  `schema_version` field on documents and idempotent Python "data migrations"
  (`app/store/migrations/NNNN_*.py`) recorded in `_migrations/{id}`.
* **Celery and outbox**: they stay (Redis-backed). Only the outbox *table* moves (§3.6).

---

## 2. Target architecture options

### Option A (recommended): FastAPI plus the same HTTP contract, Firestore repository layer via the Admin SDK

```
Browser ──(same-origin, nonce CSP)──> Next.js BFF (/api/v1/*) ──> FastAPI (unchanged routes/OpenAPI)
                                                                     │
                                         per-module Store flag: pg │ firestore
                                                ┌──────────────────┴──────────────┐
                                           Postgres (shrinking)        Firestore (Admin SDK,
                                                                       google-cloud-firestore async)
Redis + Celery + judge + S3 unchanged.  firestore.rules = deny all.
```

* The web app does not change: all 510 operations, the BFF, cookies, CSRF and the CSP stay as
  they are. The OpenAPI contract is the regression oracle. API tests run unchanged against the
  Firestore emulator.
* Authorization stays in Python (`access.py`, Principal). The RLS families are reimplemented as
  `ScopedStore` (§1.4).
* Cost on **Spark**: Firestore is free. **FastAPI cannot run in Firebase on Spark.** It runs in
  local Docker (as today), on the owner's own server, or on a third-party host. It talks to
  Firestore with a service-account key. Every request counts against the 50k reads/day.
* Cost on **Blaze**: Cloud Run for api and web (scale to zero), Firestore by operation, Hosting
  rewrite to Cloud Run on the same origin. Redis can be Memorystore (about USD 35+/month
  minimum), Upstash, or a small VM. Celery workers run on Cloud Run worker pools or a small
  Compute Engine VM. The judge needs a sandbox: Cloud Run gVisor or a dedicated VM. Estimate
  for demo-scale traffic: about USD 0–15/month without Memorystore. Set a budget alert at
  USD 10.
* Risk: the repository rewrite (about 1,870 query sites) and the loss of RLS defence in depth.

### Option B: client-direct Firestore with security rules plus Cloud Functions

* Rewrite all 510 operations as client SDK reads and writes plus callable or trigger Functions
  for anything privileged (payments, grading, audit, invoices). The FastAPI app, the BFF
  contract and most web data hooks are discarded.
* **Requires Blaze** (Functions). It does not fit the existing session model (`td_session`,
  MFA, device verification, risk engine, break-glass): Firebase Auth sessions would replace the
  LMS's own sessions, contradicting "exchange for the LMS's own session".
* Security rules cannot express dual control, SoD, k-anonymity or exam protocol timing well.
  Exam answer keys and coding test cases must never reach clients, so those still need
  Functions.
* Verdict: highest effort (backend **and** frontend rewrite), highest security risk. Not
  recommended.

### Option C: hybrid

* Option A for everything, plus selected **read-only client listeners** where real-time adds
  value (live engage runs, notifications badge). Rules allow reading only a sanitised
  projection document (for example `engage_live/{runId}`) to users holding a Firebase custom
  token minted by FastAPI from the LMS session.
* Another variant: keep commerce, entitlements and audit (the ledger) in Postgres permanently.
  This is the most data-integrity-safe end state. The owner asked for a FULL move, so this plan
  keeps it only as a **decision gate before Phase 6**.

**Recommendation: Option A**, with an optional C-style real-time projection after Phase 3, and
a go/no-go gate before Phase 6 (commerce and audit).

### Data-integrity risks of any Firestore target, and how Option A handles them

| Risk | Mitigation |
|---|---|
| No joins | Denormalise display fields (name, course title) at write time. Two-step batched `get_all()` lookups (up to 100 IDs per call). Rebuild denormalised copies with a repair job. |
| No cross-collection constraints or FKs | Transactional parent checks; orphan checker; deterministic IDs |
| Transaction limits: request size about 10 MiB, historically **500 writes**, 270 s maximum, reads before writes, **automatic retries** | Keep each transaction under 400 writes. Never call Razorpay, email or other external services inside a transaction callback, because the callback can re-run. Use outbox and saga steps instead (for example `submit_refund` moves after commit, driven by the outbox). Bulk jobs are chunked and resumable. |
| Hot documents (about 1 write/s sustained per doc) | Counters are sharded only where needed (none expected at current scale); the audit head is written by a single sealer |
| Queries need composite indexes; inequality and order rules; `in` holds at most 30 values | `firestore.indexes.json` is generated and reviewed per phase; the emulator flags missing indexes only partly, so a staging smoke test against the real project runs before each cutover |
| Reads cost quota | Redis read-through cache for catalog, roles and settings; precomputed rollups |
| Clock and ordering | Server timestamps (`SERVER_TIMESTAMP`) for ordering; the audit `seq` comes from the head document, not from time |

### Test strategy

* **Emulator**: Firebase CLI 15.34 and Java 21 are installed. Run
  `firebase emulators:start --only firestore,auth --project demo-techdrona-lms`. A `demo-*`
  project ID guarantees nothing ever reaches the real project. It works offline. Reset between
  tests with
  `DELETE http://127.0.0.1:8080/emulator/v1/projects/demo-techdrona-lms/databases/(default)/documents`.
* **Repository contract tests**: one suite per repository, parametrised over `pg` and
  `firestore`, written *before* the Firestore implementation.
* **API tests** (865): add a `TD_STORE_<MODULE>=firestore` test matrix. RLS tests are rewritten
  as HTTP authorization tests (§1.4).
* **Rules tests**: `@firebase/rules-unit-testing` asserts deny-all, and later the C-style
  projections.
* **Migration verification**: per collection, the row count, a per-row canonical-JSON SHA-256
  and a total XOR or sum checksum must match Postgres (§4.2).
* E2E (Playwright) runs against a stack with all flags set to `firestore` before each cutover.

---

## 3. Firestore data model

Conventions:

* Keep existing **UUIDs as document IDs**, so URLs, the API contract, audit `target_id`s and
  backfill stay stable.
* Mostly top-level collections, so cross-entity queries and collection-group queries stay
  simple. Use subcollections only for strictly owned, bounded children.
* Every document carries `schema_version`, `created_at`, `updated_at`, plus `expire_at` where a
  TTL applies.
* Money is integer paise (int64). Timestamps use Firestore Timestamp (microsecond precision).
  The audit `occurred_at` is *also* stored as an RFC 3339 microsecond string so the hash input
  is byte-identical.

### 3.1 Collections by domain

| Domain | Collections (ID pattern) | Notes and denormalisation |
|---|---|---|
| identity | `users/{uid}` (status, roles summary, `grants[]` cache, `email_lc`, `consent_state`), `user_profiles/{uid}`, `user_credentials/{uid}` (password hash, kept separate), `uniq_email/{sha256}`, `uniq_mobile/{sha256}`, **`identity_links/{provider}:{subject}`** (new: Google), `mfa_factors/{id}`, `consents/{id}` (append-only), `guardian_consents/{id}`, `verification_tokens/{sha256(token)}` and `password_reset_tokens/{sha256}` (TTL) | Principal resolution reads one `users` document. The `grants[]` cache is rewritten in the same transaction as `role_grants`. |
| sessions | `auth_sessions/{sid}`, `devices/{id}`, `user_devices/{uid}_{deviceId}`, `login_attempts/{id}` (TTL, chunked per user per hour if volume grows), `session_network_observations/{id}` (TTL) | Session lookup per request is 1 read, so cache in Redis (it already caches). This is the biggest daily-read driver on Spark. |
| rbac | `roles/{key}` (embeds the `permissions[]` array), `permissions/{key}`, `role_grants/{uid}_{role}_{scope}`, `approval_requests/{id}` | Role and permission catalogue cached in memory |
| orgs | `organizations/{companyId}`, `org_memberships/{orgId}_{uid}`, `batches/{id}`, `batch_members/{batchId}_{uid}` | |
| catalog | `courses/{id}`, `courses_by_slug/{slug}`, `course_versions/{id}` (embeds the **outline** of modules and lesson summaries when under 1 MiB; published versions are immutable), `lessons/{id}` (course_version_id), `lesson_assets/{id}`, `resources/{id}` | Public catalog reads come from Redis or a JSON snapshot |
| media | `playback_sessions/{id}` (TTL 180 days) | |
| learning | `enrolments/{uid}_{courseId}`, `lesson_progress/{uid}_{lessonId}`, `certificates/{id}` + `certificate_by_enrolment/{enrolmentId}`, `assignments/{id}` (with `sections/{id}` and `items/{id}` subcollections), `assignment_allocations/{assignmentId}_{target}`, `assignment_submissions/{assignmentId}_{uid}_{n}`, `assignment_item_responses/{submissionId}_{itemId}`, `assignment_regrade_requests/{id}` | Enrolment documents denormalise course title and progress percentage for dashboards |
| assessments | `tests/{id}` (with `sections/` and `section_rules/`), `test_assignments/{id}`, `test_attempts/{id}` (with `sections/`, `responses/{itemId}`, `event_chunks/{n}`, `grades/{itemId}`), `active_attempts/{testId}_{uid}`, `attempt_results/{attemptId}`, `attempt_overrides/{id}`, `attempt_integrity_decisions/{attemptId}` | Answer autosave costs 1 write per answer, so watch the Spark write quota |
| placement | `topics`, `questions/{id}`, `questions/{id}/versions/{v}` (immutable, content hash), `question_options` embedded in the version, `question_banks/{id}` (with `items/`), `question_reports`, `practice_sessions/{id}` (with `responses/`), `companies`, `company_paths/{id}` (with `steps/`), `recommendations/{uid}` | |
| coding | `coding_problems/{id}` (with `test_cases/` metadata), blobs in **S3** (encrypted as today), `coding_reference_solutions`, `coding_drafts/{uid}_{problemId}`, `code_submissions/{id}`, `submission_results/{submissionId}`, `judge_languages/{key}`, `coding_locks/{uid}` | Hidden test cases never leave the server |
| paths | `learning_paths/{id}`, `learning_path_versions/{id}` (embeds the steps array), `path_allocations/{id}`, `path_articles/{id}`, `path_step_progress/{uid}_{stepId}` | |
| engage | `engage_activities/{id}` (embeds the questions), `engage_runs/{id}` (live state), `engage_participants/{runId}_{uid}`, `engage_responses/{runId}_{qId}_{uid}` | One response per question per user comes from the deterministic ID |
| mentoring | `mentor_slots/{id}` (`booked_by`, `booking_id`), `mentor_bookings/{id}`, `mentor_notes`, `interview_feedback`, `resumes/{id}`, `resume_reviews` | A booking transaction flips the slot, so a slot cannot be double-booked |
| commerce | `products/{id}`, `plans/{id}` (embeds the `prices[]` windows, which enforces no overlap), `coupons/{code_lc}` (`redeemed_count`, `cap`), `coupon_redemptions/{couponId}_{uid}`, `orders/{id}` (`refunded_paise`, `captured_paise`, state) with `items/` subcollection, `payments/{gatewayPaymentId}`, `payment_webhook_events/{provider}_{eventId}`, `refunds/{id}`, `subscriptions/{id}`, `invoices/{id}` + `invoice_numbers/{series}_{fy}_{n}`, `invoice_sequences/{series}_{fy}`, `gst_exports/{id}`, `reconciliation_runs/{id}`, `counters/order_number` | |
| entitlements | `entitlements/{id}`, `entitlement_index/{uid}` (map from course or product to the active entitlement id and its window; 1 read per access check), `entitlement_events/{id}` (append-only) | The index is rewritten in the same transaction as each grant or revoke |
| audit | `audit_outbox/{id}`, `audit_log/{seq:012d}`, `audit_meta/head` `{seq, row_hash}`, `audit_anchors/{date}` | §3.5 |
| core | `outbox_events/{id}` (`status`, `available_at`, `lease_until`, `attempts`), `idempotency_keys/{uid}_{key}` (TTL), `locks/{key}`, `counters/{name}`, `_migrations/{id}` | |
| analytics | `analytics_event_batches/{id}` (one document per ingest batch, TTL), `analytics_consumed_events` replaced by a `batch.consumed` flag, `analytics_dirty_days/{uid}_{day}`, `daily_learning_aggregates/{uid}_{day}`, `weekly_learning_aggregates/{uid}_{isoWeek}`, `cohort_learning_aggregates/{batchId}_{day}`, `route_daily_aggregates/{day}_{route}`, `topic_mastery/{uid}_{topicId}`, `video_watch_coverage/{uid}_{lessonId}`, `question_item_stats/{questionVersionId}`, `export_jobs/{id}`, `analytics_job_state/{job}` | Heartbeats and engagement intervals are folded into the batch documents and the daily rollup |
| security | `security_signals/{id}` (TTL, chunked), `risk_evaluations/{id}` (TTL), `risk_rules/{id}` (with immutable `versions/`), `security_counters` **moves to Redis** (rate counters), `security_user_state/{uid}`, `account_restrictions/{uid}_{type}`, `security_cases/{id}` (with `notes/` and `decisions/`), `security_incidents`, `security_notices`, `security_bulk_lifts`, `security_report_exports`, `unblock_requests/{id}` | |
| support | `support_tickets/{id}` (with `messages/`), `support_user_notes/{uid}`, `corporate_enquiries/{id}`, `counters/support_ticket`, `counters/enquiry` | |
| notifications | `notifications/{id}` (`user_id`, `read_at`, TTL) | |
| ai | `ai_settings/{scope}`, `app_settings/platform` (singleton), `ai_tutor_turns/{id}`, `ai_usage/{id}`, `ai_quota/{uid}_{activityId}` (counter) | The quota transaction replaces the advisory lock and the finalize-guard trigger |
| admin | `feature_flags/{key}`, `policy_settings/platform`, `retention_policies/{table}`, `privacy_requests/{id}`, `erasure_ledger/{id}` (append-only), `break_glass_sessions/{id}` | Erasure uses a registry mapping each collection to its user-id field, so a DPDP erasure job can find all data for a user |

### 3.2 Composite indexes (`firestore.indexes.json`, first cut; grows per phase)

```jsonc
{ "indexes": [
  {"collectionGroup":"enrolments","fields":[{"fieldPath":"user_id","order":"ASCENDING"},{"fieldPath":"updated_at","order":"DESCENDING"}]},
  {"collectionGroup":"enrolments","fields":[{"fieldPath":"course_id","order":"ASCENDING"},{"fieldPath":"status","order":"ASCENDING"}]},
  {"collectionGroup":"courses","fields":[{"fieldPath":"status","order":"ASCENDING"},{"fieldPath":"category","order":"ASCENDING"},{"fieldPath":"published_at","order":"DESCENDING"}]},
  {"collectionGroup":"notifications","fields":[{"fieldPath":"user_id","order":"ASCENDING"},{"fieldPath":"created_at","order":"DESCENDING"}]},
  {"collectionGroup":"orders","fields":[{"fieldPath":"user_id","order":"ASCENDING"},{"fieldPath":"created_at","order":"DESCENDING"}]},
  {"collectionGroup":"orders","fields":[{"fieldPath":"status","order":"ASCENDING"},{"fieldPath":"expires_at","order":"ASCENDING"}]},
  {"collectionGroup":"invoices","fields":[{"fieldPath":"issue_date","order":"ASCENDING"},{"fieldPath":"series","order":"ASCENDING"}]},
  {"collectionGroup":"refunds","fields":[{"fieldPath":"status","order":"ASCENDING"},{"fieldPath":"next_attempt_at","order":"ASCENDING"}]},
  {"collectionGroup":"test_attempts","fields":[{"fieldPath":"test_id","order":"ASCENDING"},{"fieldPath":"status","order":"ASCENDING"},{"fieldPath":"submitted_at","order":"DESCENDING"}]},
  {"collectionGroup":"test_attempts","fields":[{"fieldPath":"user_id","order":"ASCENDING"},{"fieldPath":"started_at","order":"DESCENDING"}]},
  {"collectionGroup":"assignment_submissions","fields":[{"fieldPath":"assignment_id","order":"ASCENDING"},{"fieldPath":"grading_status","order":"ASCENDING"}]},
  {"collectionGroup":"approval_requests","fields":[{"fieldPath":"status","order":"ASCENDING"},{"fieldPath":"created_at","order":"DESCENDING"}]},
  {"collectionGroup":"support_tickets","fields":[{"fieldPath":"status","order":"ASCENDING"},{"fieldPath":"category","order":"ASCENDING"},{"fieldPath":"updated_at","order":"DESCENDING"}]},
  {"collectionGroup":"outbox_events","fields":[{"fieldPath":"status","order":"ASCENDING"},{"fieldPath":"available_at","order":"ASCENDING"}]},
  {"collectionGroup":"audit_log","fields":[{"fieldPath":"target_type","order":"ASCENDING"},{"fieldPath":"target_id","order":"ASCENDING"},{"fieldPath":"seq","order":"DESCENDING"}]},
  {"collectionGroup":"audit_log","fields":[{"fieldPath":"actor_user_id","order":"ASCENDING"},{"fieldPath":"seq","order":"DESCENDING"}]},
  {"collectionGroup":"daily_learning_aggregates","fields":[{"fieldPath":"user_id","order":"ASCENDING"},{"fieldPath":"day","order":"ASCENDING"}]}
 ],
 "fieldOverrides": [
  {"collectionGroup":"analytics_event_batches","fieldPath":"events","indexes":[]},
  {"collectionGroup":"audit_log","fieldPath":"before_state","indexes":[]},
  {"collectionGroup":"audit_log","fieldPath":"after_state","indexes":[]},
  {"collectionGroup":"test_attempts","fieldPath":"payload","indexes":[]}
 ]}
```

Turn off single-field indexing on large map and array blobs. This saves storage, write cost and
the 40k-index-entries-per-document limit. Keep the project under the 200 composite-index limit.

### 3.3 Example invariants and how each one is kept

| Invariant | Firestore mechanism |
|---|---|
| Email unique | Transaction: `create(uniq_email/{h})` + `create(users/{uid})`. On email change, delete the old reservation in the same transaction. |
| One active attempt; attempt limit | Transaction reads `active_attempts/{test}_{uid}` and `attempt_counts/{test}_{uid}`, then creates both or fails |
| Refund ≤ captured | Transaction on `orders/{id}`: `refunded_paise + amount ≤ captured_paise`, then create the refund and update the order. The gateway call happens **after** commit through the outbox (`refund.submit`), with `submit_refund` retries as today. |
| Coupon cap and per-user limit | Transaction: increment `coupons/{code}.redeemed_count` (≤ cap) + `create(coupon_redemptions/{coupon}_{uid})` |
| Gap-free invoice numbers | Transaction: read `invoice_sequences/{s}_{fy}`, write `next+1`, create `invoices/{id}` + `invoice_numbers/...` in the same commit |
| Entitlement grant or revoke is atomic with fulfilment | `fulfil_order` becomes one transaction: order, redemption, entitlements, `entitlement_index`, invoice and sequence, `audit_outbox`, `outbox_events`. That is under 50 writes for a normal cart, well under the limit. |
| Maker ≠ checker | Approve transaction reads `approval_requests/{id}`, requires `status=pending`, `approver ≠ maker`, approver ≠ grantee (`_check_not_grantee`), then sets `executed`. Single execution is guaranteed by the status check. |
| Evaluator never grades or publishes their own work (D3) | Server check in the grading transaction (`attempt.user_id ≠ principal.user_id`), as today |
| Question versions immutable | Repository has no update method; `content_sha256` stored; rules deny |
| Webhook dedupe | `create(payment_webhook_events/{provider}_{eventId})`. `AlreadyExists` means a duplicate, which is acknowledged. |
| Idempotency | `create(idempotency_keys/{uid}_{key}, status=in_progress)`, then the operation, then the stored result. A concurrent duplicate sees `in_progress` and gets a 409 (same as today). |

### 3.4 `firestore.rules` outline

```
rules_version = '2';
service cloud.firestore {
  match /databases/{db}/documents {
    // Option A: browsers never access Firestore. All access goes through FastAPI (Admin SDK).
    match /{document=**} { allow read, write: if false; }

    // Option C (later, optional): sanitised live projections only, for holders of a custom
    // token minted by FastAPI from a valid LMS session.
    // match /engage_live/{runId} {
    //   allow read: if request.auth != null
    //               && request.auth.token.lms_uid is string
    //               && runId in request.auth.token.engage_runs;
    // }
    // match /notif_badges/{uid} { allow read: if request.auth.token.lms_uid == uid; }
  }
}
```

Rules guard client-SDK traffic only. **Server-side authorization (`ScopedStore`, `access.py`
permissions, SoD checks) is the real control** for everything that goes through FastAPI.

### 3.5 Audit chain on Firestore

* Business transactions write `audit_outbox/{uuid}` with the same record fields as today, in
  the same transaction as the business write (atomicity kept).
* The sealer is a single writer. A lease document `locks/audit_sealer {holder, expire_at}` is
  claimed in a transaction and replaces `pg_try_advisory_xact_lock`. Per batch (at most 200
  rows), one transaction reads `audit_meta/head`, reads the outbox batch, writes
  `audit_log/{seq:012d}` documents with `prev_hash`/`row_hash` (same `chain.py`, unchanged),
  deletes the outbox documents and updates the head. `seq` stays gap-free because the head and
  the rows commit together.
* **Immutability:** the triggers and the `td_audit_sealer` role cannot be reproduced, because
  Firestore IAM is database-level, not collection-level, and the Admin SDK bypasses rules.
  Mitigations:
  1. Optionally a second named Firestore database `audit`, written only by a sealer service
     account whose key the API never holds. Multiple databases may need Blaze; verify.
  2. A daily anchor: the head hash is written to `audit_anchors`, emailed to the owner's
     mailbox and, on Blaze, written to a GCS bucket with Object Lock. That covers the
     currently "Planned" `last_anchor`.
  3. `verify_chain` runs nightly and alerts on failure.
* **Transition period:** while some modules are still on Postgres, the sealer drains **both**
  outboxes (PG `audit_outbox` and Firestore `audit_outbox`), merges them by
  `(occurred_at, id)` and appends to the one chain, which stays in Postgres until Phase 6. At
  Phase 6 the chain is copied to Firestore, verified end to end, and the head is continued.

### 3.6 Outbox and Celery

`outbox_events` goes to whichever store holds the business transaction. The relay
(`relay_pending`) gets a Firestore implementation (lease claim in a transaction instead of
`SKIP LOCKED`) and drains both stores during the transition. Handlers must be idempotent; they
already are by design. Celery and beat stay on Redis. The Postgres-only maintenance jobs
(`maint.ensure_partitions`, `drop_expired_partitions`) are retired per phase. TTL policies and
a Python retention job replace `run_retention` and `purge_closed_cases`.

---

## 4. Phased plan

### 4.1 Mechanics that apply to every phase

* **Per-module store flag** `TD_STORE_<MODULE> = pg | shadow | firestore`. It is read at
  startup only (no runtime flip, so no split brain).
  * `pg`: today's behaviour.
  * `shadow`: Postgres is primary. After commit, an outbox handler mirrors the changed
    aggregates to Firestore. A nightly verifier diffs the two stores.
  * `firestore`: Firestore is primary. For a rollback window (default 14 days), a reverse
    mirror writes back to Postgres so rollback is a flag flip.
* **Per-module refactor before moving (de-join):** first extract a `repo.py` interface with a
  Postgres implementation, with no behaviour change and tests green. Replace cross-module SQL
  joins and model imports (§1.2) with calls to the owning module's public service. This step is
  a large part of the work and is required for each module.
* **Cross-store atomic flows** during the transition (for example a refund revoking
  certificates in `learning` while `commerce` is still on Postgres) run as outbox sagas with
  idempotent handlers. The plan **groups tightly coupled modules into the same phase** to keep
  the number of sagas small.
* **Backfill** (`app/store/backfill/<module>.py`): stream Postgres in primary-key order and
  transform with the same mapper the repository uses. Write with BulkWriter, resumable by a
  checkpoint in `_migrations`. Run it against the emulator first. On Spark, mind the 20k
  writes/day: the current dev dataset is small, but anything larger needs Blaze or a multi-day
  run.
* **Verification** (`app/store/verify/<module>.py`): per collection, the counts, a per-document
  canonical-JSON SHA-256 compared to the mapped Postgres row, a summed checksum, FK-orphan
  checks, invariant checks (for example `sum(refunds) == order.refunded_paise`, invoice numbers
  contiguous), then an API golden test that records responses on `pg` and replays them on
  `firestore` and compares JSON.
* **Cutover:** short write freeze (maintenance mode banner), final delta backfill, verify, set
  the flag to `firestore`, deploy, smoke test, start the reverse mirror.
* **Rollback:** set the flag back to `pg` (the reverse mirror kept Postgres current). If the
  mirror failed, replay from Firestore with the reverse backfill script.
* **Owner decision F1:** if there is **no production data yet** (only synthetic or demo data),
  skip `shadow` and the reverse mirror. Use **backfill, then verify, then flip, with reseed as
  rollback**. That saves about 25% of the effort.

### 4.2 Phases (low risk first)

| Phase | Scope | Shippable result | Retired at end |
|---|---|---|---|
| **P0: Foundations** | `app/store/` (Firestore async client via `firebase_admin`, `ScopedStore`, transaction helper with a retry-safety guard that **forbids external I/O inside the callback**, lock/counter/unique helpers, lease claims, TTL helper, Pydantic store schemas); emulator fixtures in `tests/conftest.py`; flags; backfill and verify framework; `firebase.json`, `firestore.rules` (deny-all), `firestore.indexes.json`; dual-source outbox relay and audit sealer; repository contract-test harness; secrets handling (`GOOGLE_APPLICATION_CREDENTIALS` path outside the repo, `.gitignore`, startup check refuses a key in the repo) | No behaviour change; CI runs the emulator | none |
| **P1: Firebase Auth (Google), Analytics, Hosting demo** (§5) | Independent of the data move. Can run in parallel with P0. | Google sign-in on `/login` and `/signup`; consent-gated GA4; public demo link | none |
| **P2: Catalog, content and settings** | catalog, media (playback), notifications, support (tickets, enquiries), ai (settings, usage, quota), admin (flags, policies, retention, privacy, erasure, break-glass registry), orgs (single company, batches) | Public catalog, course pages, the studio content editor, the support queue and settings served from Firestore | Partitions and RLS for those tables; Alembic heads for those modules frozen |
| **P3: Engage, paths, mentoring, placement and coding authoring** | engage, paths, mentoring, placement (questions, banks, practice, companies), coding authoring (problems and test-case metadata; blobs stay in S3) | Live engage (optional C-style projection), paths with D9 embeds, mentor booking, question banks | |
| **P4: Learning, assessments, coding submissions and analytics** | learning (enrolments, progress, assignments, certificates), assessments (attempts, grading, publishing, integrity), coding submissions and judge results, analytics (batch ingest, rollups, reports H1–H12, exports) | Learner dashboard, exams, assignments, grading and publishing by evaluators (D3), reports | Partitioned analytics, attempt_events and heartbeat tables; `maint` partition jobs for them |
| **P5: Identity, sessions, RBAC and security** | identity (users, credentials, MFA, consents, guardian), sessions, rbac (roles, grants, approvals), security (signals, risk, cases, restrictions, unblock) | Login, MFA, sessions and the risk engine on Firestore; Redis for counters | `app.*` RLS GUC functions no longer used |
| **Gate G6** | Owner go/no-go: move the ledger, or keep commerce, entitlements and audit on Postgres (Option C)? | | |
| **P6: Commerce, entitlements, audit and core** | commerce (orders, payments, webhooks, refunds, subscriptions, invoices, GST, reconciliation), entitlements, audit chain copy and continuation, outbox_events, idempotency_keys | Payments and invoices on Firestore; audit chain verified after the copy | |
| **P7: Retire Postgres** | Final verify; export a Postgres dump to `backups/`; remove Alembic, `migration_helpers`, RLS lint, `core/db.py` tenant GUCs, the maintenance jobs, the postgres and migrate services in compose; update docs (`database-schema.md`, ADRs) | Firestore-only backend | Postgres, Alembic, RLS, pg_partman / `maint.*` |

The coupled groups that drove the phase choice: commerce ↔ entitlements ↔ learning
(certificates) ↔ audit, which is why P6 needs sagas for certificate revocation after P4.
Assessments ↔ coding ↔ placement are grouped in P3 and P4. Identity is referenced everywhere,
but only through user lookups, so other modules call the identity service and it can move late.

---

## 5. Firebase Auth, Analytics and the Hosting demo

### 5.1 Google sign-in (Firebase Auth), then the LMS's own session

**Flow:**

1. The `/login` or `/signup` page lazily loads the Firebase JS SDK (`firebase/app`,
   `firebase/auth`) from our own nonce-trusted bundle (it is bundled, not loaded from a CDN).
2. `signInWithPopup(GoogleAuthProvider)`.
3. `getIdToken()`.
4. `POST /api/v1/auth/login/google {id_token}` through the BFF, with the anon CSRF binding as
   on the login form.
5. Immediately `signOut(auth)` and clear the Firebase IndexedDB. No parallel Firebase session
   lingers.

**FastAPI** (`identity`, new route; OpenAPI and web types regenerated):
`firebase_admin.auth.verify_id_token(token, check_revoked=True)`. The route requires:

* `aud = techdrona-lms` and the issuer;
* `firebase.sign_in_provider == "google.com"`;
* `email_verified == true`;
* `auth_time` within 5 minutes;
* a one-time use check: SHA-256 of the token stored in Redis with a 1-hour TTL, to stop replay.

The route is rate-limited like `/login`. It then runs the **existing** login pipeline: risk
engine, `login_attempts`, device verification, restrictions, guardian rules, session creation,
the `td_session` cookie and the audit event `identity.login.google`.

**Account linking** (by verified email):

1. If `identity_links/google:{firebase_uid}` exists, use that user.
2. Otherwise, if an LMS user with the same normalised email exists:
   * LMS email **verified**: link, audit `identity.link.google`, and send a notification email.
   * LMS email **unverified**: Google proves ownership. Mark the email verified, **remove the
     unverified password credential and revoke its sessions** (this blocks pre-hijack account
     planting), then link.
3. Otherwise create a new **student** account (never staff). Then show the required
   consents/terms screen and the DOB/guardian flow before the session becomes active.
   Google's `name` and `picture` go to the profile only after consent.

**Staff rules unchanged:** for any non-student role, Google sign-in counts as the first factor
only, and TOTP (`/mfa/verify`) is still required. Step-up and break-glass are unchanged.
Owner decision F3: allow Google sign-in for staff at all, or students only (recommendation:
students plus staff with TOTP).

Unlinking happens in Settings › Security. It requires step-up and at least one other way to
sign in.

**CSP and headers:**

* `script-src`: the SDK is bundled. `apis.google.com` may be injected by the SDK and inherits
  trust via `strict-dynamic`; add it as a CSP2 fallback.
* `connect-src`: `https://identitytoolkit.googleapis.com`, `https://securetoken.googleapis.com`.
* `frame-src`: `https://techdrona-lms.firebaseapp.com`, `https://accounts.google.com`.
* **COOP** is currently `same-origin` (`apps/web/next.config.ts:12`), which breaks
  `signInWithPopup`. Set `same-origin-allow-popups` on `/login` and `/signup` only.
* Alternative: `signInWithRedirect` with `authDomain` set to the LMS's own domain, and the BFF
  reverse-proxying `/__/auth/*` to `techdrona-lms.firebaseapp.com`. This is Firebase's
  documented fix for third-party-storage partitioning, and it keeps COOP strict.

**Firebase console (owner):** enable the Google provider, set the support email, add
**authorized domains** (`localhost` is default; add the demo domain and later `lms.techdrona.in`),
restrict the Web API key by HTTP referrer, and keep email enumeration protection on.

### 5.2 Firebase Analytics (GA4), only after analytics consent

* Load `firebase/analytics` **only** when the stored consent `analytics_product` is granted
  (consent purposes in `identity/schemas.py`). Before that, nothing loads and no cookies are
  set.
* On withdrawal: `setAnalyticsCollectionEnabled(false)`, delete `_ga*` cookies, stop loading.
* Use Consent Mode v2: defaults all denied; only `analytics_storage` is granted on consent;
  `ad_*` stays denied always.
* Disable Google signals and ads personalisation in GA4. Set data retention to 2 months.
* Never send PII (no email, no name). Set no `user_id`, or send an HMAC pseudonym only if
  `analytics_personalisation` is also granted. No analytics on exam or attempt pages,
  guardian-consent pages or the admin, finance and security consoles. No analytics for minors
  without guardian consent covering analytics.
* GA4 is for product and marketing funnels only. The LMS's first-party `analytics_events`
  pipeline stays the source for H1–H12 learning reports.
* CSP: `connect-src https://*.google-analytics.com https://*.analytics.google.com
  https://www.googletagmanager.com https://firebase.googleapis.com
  https://firebaseinstallations.googleapis.com`, and the same for `img-src`. The gtag script is
  inserted by the trusted bundle (`strict-dynamic`), with `https://www.googletagmanager.com` as
  the CSP2 fallback.
* The owner must supply `apiKey`, `appId`, `messagingSenderId` and **`measurementId`**
  (G-XXXX). They are not in the config provided. Enable Google Analytics on the project. These
  are public config values (`NEXT_PUBLIC_FIREBASE_*`), not secrets.

### 5.3 Public demo link (Firebase Hosting)

**On Spark (static only):**

* Next.js `output: "export"` is incompatible with this app as a whole: middleware (nonce CSP),
  BFF route handlers (`src/app/api/v1`), cookies, and dynamic `searchParams` pages such as
  `/courses?q=`.
* Option S1 (recommended for now) is a separate **static showcase build** (`TD_DEMO_STATIC=1`).
  Pages:
  * home;
  * `/courses` (unfiltered list) and `/courses/[slug]`, pre-rendered from a **build-time JSON
    snapshot** of the seeded catalog;
  * `/pricing`, `/help`, `/legal/*`, `/free-resources`, `/companies`, `/placement`.
  Interactive pages show a "Demo: sign-in disabled" call to action. These are excluded:
  `/login`, `/signup`, `/enquiries` (no server to post to; show a mailto instead), `/app`,
  `/admin`, `/trainer`, `/evaluator` and the other portals.
* The static site cannot use per-request nonces. It gets a static CSP in `firebase.json`
  headers. Next's inline bootstrap scripts force `'unsafe-inline'` (or brittle hashes). This is
  acceptable **only** because the site has no sessions, forms or user data. It is a documented
  exception; the real app keeps the nonce CSP.
* Option S2 is the full working app: run the Docker stack on the owner's machine or VM and
  expose it with a tunnel (for example Cloudflare Tunnel) at a demo subdomain. Firebase Hosting
  then only serves a landing page linking to it. It stays up only while the host is on.
* Free container hosts (Render, Koyeb and similar) are a poor fit: the stack needs api, web,
  Redis, a Celery worker, beat and the judge, which goes beyond free-tier memory limits.

**On Blaze:**

* Hosting rewrites `**` to a Cloud Run service running the existing Next.js standalone image
  (same origin, the nonce CSP keeps working).
* The API runs on Cloud Run with private ingress, called by the BFF.
* App Hosting is an alternative for the web app.
* Cloud Storage can replace S3 (later, optional).
* Firestore backups and PITR become available.

---

## 6. Effort, risk, Spark limits, owner inputs and decisions

### 6.1 Effort and risk per phase

Effort is in engineer-weeks for one experienced developer, including tests and verification.
AI-assisted agents can compress the typing but not the verification.

| Phase | Effort | Risk | Main risks |
|---|---|---|---|
| P0 Foundations | 3–4 | Medium | Getting `ScopedStore` and transaction-retry safety right; emulator CI flakiness |
| P1 Auth, Analytics, Hosting demo | 1.5–2.5 | Low–Medium | COOP/CSP regressions; account-linking edge cases; consent correctness |
| P2 Catalog, content, settings | 3–4 | Low | ILIKE search parity; erasure registry |
| P3 Engage, paths, mentoring, placement, coding authoring | 4–6 | Medium | Immutable question versions; booking races; live engage fan-out |
| P4 Learning, assessments, analytics | 6–8 | **High** | Exam integrity and timing; autosave write volume; grading/publish SoD; rollup parity for H1–H12 |
| P5 Identity, sessions, RBAC, security | 5–7 | **High** | Login, MFA and session correctness; loss of RLS; risk-engine aggregates; Spark read quota (session lookups) |
| P6 Commerce, entitlements, audit | 5–7 | **Very high** | Money and GST legal records; the gap-free invoice and audit chain; external calls moved out of transactions; no DB-enforced immutability |
| P7 Retire Postgres | 1–2 | Medium | Leftover joins; docs |
| **Total** | **about 30–42 weeks** (about 22–32 if F1 = no production data) | | |

Plus about 1 week per phase for re-running E2E, accessibility and security checks. The honest
alternative for comparison: P1 alone delivers Analytics, Google sign-in and a demo link in
about 2 weeks while keeping Postgres.

### 6.2 What cannot work on Spark

* Running FastAPI, the BFF (Next.js SSR), Celery or the judge inside Firebase.
* Hosting rewrites to Cloud Run or Functions, so no same-origin full app on `*.web.app`.
* Cloud Storage buckets: S3 or seaweedfs stays.
* Firestore managed backups, PITR and `gcloud firestore export`. On Spark, backups are a custom
  Admin-SDK JSON dump job; plan to run it nightly to `backups/firestore/`.
* BigQuery export and search extensions.
* Sustained real usage: 50k reads/day is about 35 reads a minute averaged. One dashboard load
  can cost 20–100 reads; exam autosave and analytics batches eat the 20k writes. Spark is fine
  for a small demo with Redis caching, not for real learners.
* Phone-number (SMS) auth in Firebase Auth, if ever wanted. Today's SMS goes through the LMS's
  own adapter.

### 6.3 What the owner must provide

1. A **service-account JSON** for `techdrona-lms` (role *Cloud Datastore User*; for the sealer
   database, a separate key if F4 is chosen). Store it outside the repo, for example
   `%USERPROFILE%\.secrets\techdrona-lms-sa.json`, and point to it with
   `GOOGLE_APPLICATION_CREDENTIALS`. **Never commit it.**
2. `firebase login` on the dev machine (CLI 15.34 is installed) and `firebase use techdrona-lms`.
3. In the Firebase console:
   * create the Firestore database (**choose the location once; it is permanent**;
     recommendation `asia-south1`, matching the website project);
   * enable **Auth › Google** provider and set the support email;
   * add the **authorized domains**;
   * enable **Google Analytics** and send the measurement ID;
   * register the Web app and send its full config (`apiKey`, `appId`, `messagingSenderId`,
     `measurementId`).
4. The demo domain choice: `techdrona-lms.web.app` or a custom subdomain such as
   `demo.techdrona.in` (DNS access needed).
5. For Blaze later: a billing account and a budget alert.

### 6.4 Decisions needed from the owner

| # | Decision | Recommendation |
|---|---|---|
| F1 | Is there any production or real learner data in Postgres? | If no: backfill, flip, and reseed as rollback (saves about 25%) |
| F2 | Demo on Spark: S1 static showcase or S2 tunnelled full app (or both) | Both: S1 on `web.app`, S2 when a live walkthrough is needed |
| F3 | Google sign-in for staff? | Allowed, but TOTP is still mandatory; students may use Google only |
| F4 | Audit chain in a separate Firestore database with a separate service account | Yes, once on Blaze; daily anchor email from day one |
| F5 | Gate G6: move commerce, entitlements and audit, or keep the ledger on Postgres (hybrid) | Decide after P5 with real numbers |
| F6 | Firestore location | `asia-south1` |
| F7 | When to move to Blaze | Before P4 (exam and analytics write volume) or before any real users |
| F8 | Search approach for catalog and banks | Redis-cached in-memory filter plus prefix fields; revisit Typesense on Blaze |

---

## Owner decisions (recorded by the coordinator, 2026-11-08)
| # | Decision |
|---|---|
| F1 | Only demo/test data exists — no live backfill/dual-run needed; Postgres demo data may be re-seeded into Firestore. |
| F5 | Move payments, invoices and the audit log too (P6), after its go/no-go review. |
| F2 | Demo link: static showcase on Firebase Hosting now (Spark); full app when upgraded to Blaze (Cloud Run). |
| F6 | Firestore location: **asia-south1 (Mumbai)**. |
| Config | Full web config received (apiKey, appId, messagingSenderId, measurementId G-BXZ1X5KHVC) and stored in the untracked root `.env` as `NEXT_PUBLIC_FIREBASE_*`. Service-account JSON + `firebase login` + Google provider + authorized domains: pending from owner. |
| Open | F3 Google sign-in for staff (default: students only; staff keep password + TOTP), F4 separate audit DB, F7 Blaze timing, F8 search — coordinator defaults per plan recommendations until the owner says otherwise. |
