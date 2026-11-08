# Fixes — agent `core`

Scope: `apps/api/app/core/**`, `main.py`, `wiring.py`, `worker.py`, `seeds/**`, modules identity / sessions / notifications (+ their tests and migrations), web `lib/bff/**`, `middleware.ts`, `features/auth/lib` (safeNextPath / login-flow), infra, compose, Dockerfiles, `.env.example`, CI.

Work was split between the lead `core` agent and four sub-forks: web, infra, DB maintenance, and erasure/consumers. Every change in this file is in the owned paths.

## Fix table

| ID(s) | Severity | Fix summary | Files | Regression test | Result |
|---|---|---|---|---|---|
| SEC-01 | High | **Web:** with `TD_TRUSTED_PROXY_HOPS=0` (or not a number), `resolveClientIp` returns `null`. It never trusts X-Forwarded-For or `CloudFront-Viewer-Address` then, and no client IP is forwarded.<br>**API:** for a request the BFF has authenticated, `client_ip` is `X-TD-Client-IP` or unknown. It never falls back to the BFF's own socket address, which would put every user in one bucket. Per-IP limits are skipped when the IP is unknown.<br>**Infra:** web gets `TD_TRUSTED_PROXY_HOPS=1` (CloudFront → ALB). | `web/src/lib/bff/headers.ts`, `api/app/core/middleware.py`, `infra/terraform/envs/*` | `web/src/lib/bff/proxy.test.ts`; `tests/core/test_phase_b_core.py::test_sec01_*`; `tests/identity/test_phase_b_identity.py::test_sec02_limits_skipped_when_client_ip_unknown` | Fixed+tested (audit web probe now passes) |
| SEC-02, BE-09 (shared limiter) | High | New shared limiter `app/core/ratelimit.py`: fixed windows on the cache Redis, `429 rate_limited` with `Retry-After`, `RateLimit-Policy` and a `retry_after_seconds` body field. It fails open if Redis is down, and `MemoryBackend` is used for tests. Identity applies the spec limits:<br>- AUTH-01: 5/h per IP+device, 3/day per contact<br>- AUTH-02: 20/h per IP<br>- AUTH-16: 5/h per IP, 3/h per identifier<br>- AUTH-17: 10/h per IP<br>- AUTH-18: 5/h per user<br>- AUTH-19: 10/min per user<br>- AUTH-28: 10/min per device<br>The "you already have an account" email is sent at most once per contact per day. | `app/core/ratelimit.py`, `identity/router.py` | `tests/identity/test_phase_b_identity.py::test_sec02_*` (3), `tests/core/test_phase_b_core.py::test_ratelimit_*` (2) | Fixed+tested (probe: 7 signups → `[201×5, 429, 429]`; owner emails 0–1) |
| SEC-03 | Medium | `POST /auth/password/change` is limited to 5/h per user, checked before the password is verified. | `identity/router.py` | `test_sec03_password_change_limited_per_user` | Fixed+tested (probe: 25 wrong guesses → 401×5 then 429) |
| SEC-04 | Medium | `safeNextPath` rejects C0/DEL characters, whitespace, backslashes and a leading `//`, then checks the result resolves to the same origin and returns the normalised path. | `web/src/features/auth/lib/validation.ts` | `validation.test.ts` (+2 cases) | Fixed+tested (`portals.ts` copy: Request) |
| SEC-05 | Medium | When the email already exists, signup now does an Argon2id hash and issues the device cookie, the same as a new signup. Both outcomes are padded to the same minimum response time (1.0 s + up to 0.15 s jitter). The spec defines the body difference itself (`session: null`, `next_steps: ["check_email"]`, AUTH-01 "same 201 shape"), so the body is kept as specified; see Requests (docs). | `identity/router.py` | `test_sec05_duplicate_signup_matches_timing_and_cookies` | Fixed+tested for timing and cookies. Body difference is per the spec: product decision Request |
| SEC-06 | Medium | `HmacKeyring.weak_versions` lists keys that are not ≥ 256-bit hex. The production gate refuses them. Before this, a 42-character non-hex placeholder was accepted. | `core/security.py`, `core/startup_checks.py` | `tests/core/test_logging_and_startup.py::test_sec06_*` | Fixed+tested (probe now lists both keyrings) |
| COM-07, COM-13 (gate) | High | In production the gate now refuses:<br>- empty or placeholder Razorpay key id, secret or webhook secret, and `rzp_test_` keys<br>- the placeholder or a missing `SELLER_GSTIN`, `SELLER_LEGAL_NAME` or `SELLER_ADDRESS`<br>- `EMAIL_PROVIDER=memory`, and any email or SMS provider with no adapter<br>- missing SES sender or region; missing MSG91 auth key, sender or OTP template<br>- `TD_COMMERCE_WEBHOOK_MODE` other than `queue`<br>These values are read through core `Settings` fields that use the same variable names as `CommerceSettings`. | `core/startup_checks.py`, `core/config.py` | `test_com07_*` (2) | Fixed+tested |
| COM-08 | High | `create_celery()`, which builds both the workers and beat, calls `run_startup_checks` after module discovery and wiring. | `app/worker.py` | `test_com08_celery_app_runs_the_production_gate` | Fixed+tested |
| COM-06 | High | Two real adapters behind the existing protocols:<br>- `SesEmailAdapter`: SES v2 `SendEmail` with simple content, tags, configuration set and task-role credentials.<br>- `Msg91SmsAdapter`: Flow API v5 `POST /flow` with `authkey`, DLT template id per `template_key`, `##otp##` / `##message##` variables, and `DLT_TE_ID`.<br>Neither has been run against a live account. Production refuses to start without their configuration. | `notifications/adapters.py`, `core/config.py` | `tests/notifications/test_provider_adapters.py` (4: SES fake client, MSG91 `MockTransport`) | Fixed+tested (unverified against the providers) |
| COM-14 | Medium | Beat leader lock (`app/core/celery_ops.py`):<br>- On `beat_init`, beat takes `SET NX PX` on `td:scheduler:leader` in the queue Redis and blocks as standby until it gets the lock.<br>- It renews every ttl/3 with a compare-and-pexpire Lua script, and exits if it loses the lock.<br>- It releases the lock at exit.<br>Settings: `TD_SCHEDULER_LEADER_LOCK_TTL_SECONDS` and `_ENABLED`. | `core/celery_ops.py`, `worker.py`, `core/config.py`, `.env.example` | `test_com14_beat_leader_lock_single_leader_and_standby` (real Redis), `test_com14_beat_init_signal_is_connected` | Fixed+tested |
| E2E-06 | Medium | A worker bootstep touches `TD_WORKER_HEALTH_FILE` every 15 s from the worker's timer. The compose healthcheck for `worker` and `worker-maintenance` is now a stdlib `mtime < 90 s` check instead of `celery inspect ping`. | `core/celery_ops.py`, `worker.py`, `docker-compose.yml` | `test_e2e06_*` (2) | Fixed+tested (`docker compose config -q` OK; not run in live containers) |
| COM-09, COM-15 | High / Medium | No `judge_*` beat entry remains; coding already removed it. Terraform `worker-judge` now runs the DB poller (infra fork). The maintenance queue now has producers: `td.core.maint_partitions` and `td.core.maint_retention`. | `infra/terraform/envs/*`, `worker.py` | `tests/core/test_stage10_wiring.py::test_celery_beat_has_every_module_job` (every beat queue has a consumer) | Fixed+tested |
| DB-03, BE-22, BE-15 (500 part) | Medium / Low | The core DB error handler maps unique and exclusion violations (SQLSTATE 23505/23P01) to a 409 problem+json, also when they are raised from the dependency commit. Constraint-specific codes are registered with `register_unique_conflict`: `ux_att_one_open` and `test_attempts_…attempt_no_key` → `active_attempt_exists`; enrolment and practice-response duplicates → `conflict`, which is new in the catalogue. Wiring is in `wiring._register_unique_conflicts`. | `core/errors.py`, `wiring.py` | `tests/core/test_phase_b_core.py::test_db03_*` (3) | Fixed+tested (audit probe: `ATTEMPT_RACE {409: 5, 201: 1}`, `UNHANDLED []`) |
| DB-06 | Medium | `system_context(session, job)` still works with `await`, which keeps the whole transaction in platform scope. It can now also be used as `async with` (alias `as_system`): it reads the six GUCs, switches to platform scope and restores the previous tenant context on exit, including on exceptions. The 7 authenticated identity call sites now use the scoped form. | `core/db.py`, `identity/router.py` | `test_db06_*` (2) | Fixed+tested for the core API and identity. Other modules' call sites: Request |
| DB-11 | Low | The seed guard is now an allowlist: `app.seeds.seeds_allowed()` returns true only for `APP_ENV` in {local, dev, test}. All 8 demo seeds use it. | `app/seeds/*.py` | `test_db11_seed_guard_is_an_allowlist` (staging, prod, production) | Fixed+tested (docs §17: Request) |
| SEC-07 | Medium | New `lib/bff/remember.ts`. On a top-level user navigation (`Sec-Fetch-Mode: navigate` and `Sec-Fetch-User: ?1`) with no session but a remember cookie, the middleware calls AUTH-28 with the service token and re-sets the cookies. A 4xx clears the remember cookie. The proxy clears the session cookie on 401 expired or revoked. | `web/src/lib/bff/remember.ts`, `middleware.ts`, `lib/bff/proxy.ts` | `remember.test.ts` (4), `middleware.test.ts` (+3), `proxy.test.ts` (+2) | Fixed+tested (mocked fetch) |
| SEC-08 | Low | `advance()` rotates the session token whenever a session that was pending in an earlier request becomes active (device OTP, session choice). Login, remember-refresh and MFA verify pass `rotate_on_activate=False` because they already have a fresh token. | `sessions/login.py`, `identity/router.py` | `test_sec08_token_rotated_when_pending_login_becomes_active` (the old pending token returns 401) | Fixed+tested |
| SEC-09 | Low | Student step-up methods are TOTP, email OTP and SMS OTP, as in spec §1.6. Password is offered only when the student has no other usable method (no TOTP, no email, no verified mobile). `step_up_problem` no longer advertises `passkey` or `password`. | `identity/router.py` | `test_step_up_student_otp_methods_and_totp_for_staff` (replaces the old password test) | Fixed+tested (web StepUpDialog OTP UI: Request) |
| SEC-11 (identity part) | Low | `step_up_problem` and AUTH-19 no longer list `passkey`, since WebAuthn is not built. | `identity/router.py` | covered by the SEC-09 test | Partly fixed (admin/orgs advertise `passkey`; break-glass is TOTP: Request) |
| SEC-10 | Low | Terraform for dev, staging and prod: one shared env and secrets set for every process running API code. It covers HMAC/AEAD keys, `TD_COOKIE_SECURE`, providers, `TD_COMMERCE_WEBHOOK_MODE=queue`, Razorpay, MSG91 and the service token. Web gets `TD_TRUSTED_PROXY_HOPS=1`. Placeholder tfvars mean prod refuses to start until real values are set. Also fixed: the `worker-judge` command and the `audit-sealer` module path. | `infra/terraform/**` | `terraform fmt -check` and `validate` (3 envs) | Fixed+validated |
| E2E-12 | Low | `check_totp_code` returns `ok`, `replayed` or `invalid`. A genuine code reused within its step is refused (`otp_invalid`, `reason: code_already_used`) and is not recorded as `mfa_failed`, so it adds nothing to TO-03 or lockout. This applies to MFA verify, step-up and device verify. A password reset while a T-protect lock is active must set a different password (RE §T-protect "must_change"). | `identity/totp.py`, `identity/service.py`, `identity/router.py` | `test_e2e12_*` (3) | Fixed+tested |
| E2E-04 (identity side) | Medium | Nothing to fix in identity: per spec AUTH-01, `security_monitoring` is required only before a paid purchase. Commerce fixed the error copy. | — | — | Not in core paths; inline-toggle Request already raised by commerce |
| INV-16 (identity) | Medium | Added tests for AUTH-04/05 mobile OTP: send, wrong code, verify, already verified, and the hourly cap of 3 with `Retry-After`. | — | `test_inv16_*` (2) | Tested (no bug found) |
| INV-10 | Medium | `enrol_url=/app/settings/security/mfa` and `/app/guardian-consent` now both exist as pages; the frontend built them. | — | — | Not reproduced (pages exist). Client handler for `mfa_enrolment_required`: Request |
| FE-34 (API part) | Low | `recovery_url` is already `web_path("forgot_password")` → `/forgot-password`. | — | — | Not reproduced |
| FE-09 (API part) | Medium | `throttled` and `rate_limited` problems now also carry `retry_after_seconds` in the body. | `identity/router.py`, `core/ratelimit.py` | `test_ratelimit_memory_backend_window_and_problem` | Fixed (API side); `errors.ts` fallback: Request |
| BE-33 | Low | API spec §1.13 explicitly defines `400 validation_failed` for schema errors and `422` for semantically invalid input. Core maps `RequestValidationError` to 400 as specified. | — | existing `test_errors_request_id.py` | Not a defect per spec (doc drift at §1.1 line 92: Request) |
| BE-01 (wiring part) | High | `video_coverage_lookup` caps covered seconds per asset at `lesson_assets.duration_seconds`, falling back to the recorded `duration_s`. | `wiring.py` | `test_be01_video_coverage_lookup_capped_at_asset_duration` | Fixed+tested |
| DB-04 | Medium | Migration `core_base_0002`, function `maint.ensure_partitions`:<br>- Creates monthly partitions for the current month plus N ahead, for the 10 registered parents.<br>- Applies the DEFAULT partition's ACLs and policies to each new partition, revokes app-role privileges, and enables and forces RLS.<br>- If DEFAULT already holds rows for that month, it detaches DEFAULT, creates the partition, moves the rows and re-attaches.<br>- `audit_log` is append-only, so a month with rows there is reported, not moved.<br>A daily job runs it on the `maintenance` queue as `td_maintenance`. | `migrations/versions/core_base_0002_maint.py`, `core/maintenance.py`, `worker.py`, `core/config.py` (`DATABASE_MAINTENANCE_URL`) | `tests/core/test_maintenance.py` | Fixed+tested |
| DB-02 | High | `maint.purge_expired_rows`, `maint.drop_expired_partitions` and `maint.run_retention` delete in batches using `retention_policies`. Missing policy rows are added. Risk rows under an open or legal-hold case are kept. All functions are SECURITY DEFINER with `search_path` pinned, and only `td_maintenance` can EXECUTE them. A daily job writes an audit summary. Terraform: a 455-day S3 backstop rule for unblock attachments. | same migration and job, `infra/terraform/envs/*` | `tests/core/test_maintenance.py` (11 tests in total for DB-02 and DB-04) | Fixed+tested (retention conflicts listed below) |
| DB-01 (identity, notifications) | High | Identity erasure provider:<br>- Tombstones the user: contact cleared, status `deleted`.<br>- Scrubs the profile and deletes credentials, MFA factors and tokens.<br>- Keeps consents and guardian consents as legal holds.<br>The notifications provider deletes the user's inbox rows. Both are registered from `wiring`. | `identity/erasure.py`, `notifications/erasure.py`, `wiring.py` | `tests/identity/test_erasure.py`, `tests/notifications/test_erasure.py` | Fixed+tested |
| COM-17 (notifications side) | Medium | Consumers:<br>- `invoice.issued`: in-app notification and email.<br>- `subscription.cancel_requested`: confirmation email.<br>- Daily `notifications.renewal_reminders` job: annual plans, 7 days before renewal, deduplicated per period.<br>- `commerce.refund_failed`, `refund_submit_stuck` and `webhook_failed`: high-priority in-app alerts to `finance_admin` users.<br>Also added the `order` and `billing` web links. | `notifications/consumers.py`, `notifications/tasks.py`, `identity/links.py`, `wiring.py` | `tests/notifications/test_commerce_consumers.py` (5) | Fixed+tested |
| E2E-09 (sessions part) | Low | The resolver passes the observed UA family and OS to `replay_blocked`. The audit row records expected and observed values. | `sessions/resolver.py`, `sessions/hooks.py` | `tests/sessions/test_replay_evidence.py` | Fixed+tested |
| Commerce request 3 (deep link) | Low | The middleware sets the request header `x-td-request-path` to the requested path and query, overwriting any value the browser sends, so `PortalShell` can build `/login?next=` from the real path. | `web/src/middleware.ts` | `middleware.test.ts` ("forwards the requested path…") | Fixed (header). `PortalShell` must use it: Request |
| COM-18 | Medium / Low | `.env.example` gains the missing names (`TD_COMMERCE_WEBHOOK_MODE`, `SELLER_ADDRESS`, `COMMERCE_DOCUMENT_STORE`, web names, worker health and leader-lock settings). Variables no code reads are tagged `[NOT READ YET]`; `MINIO_ROOT_*` is removed. `worker-judge` is described as the DB poller. | `.env.example` | script comparing names read by code with `.env.example` | Fixed |
| COM-23 | Medium | Base images pinned by digest. The API Dockerfile honours `requirements.lock` when present. CI runs `bash scripts/seed-dev.sh`. `s3-init` is a `service_completed_successfully` dependency. | Dockerfiles, `ci.yml`, `docker-compose.yml` | `docker buildx build --check`, actionlint | Fixed (lockfile: Request) |
| COM-24 | Low | `api-webhooks` now has host port `${TD_API_WEBHOOKS_HOST_PORT:-18001}`. The `deploy.yml` `exit 1` skeleton is left as is, intentionally. | `docker-compose.yml` | `docker compose config -q` | Fixed / deploy.yml deferred (intentional skeleton) |
| ADM-17 (flag consumers) | Medium | Not wired. The maintenance-mode gate (§28.4 "not wired yet") needs either a per-request DB read in the ASGI middleware or a cached flag reader with invalidation. `risk.fingerprint_collection` gates fingerprint collection, which is not built (`TD_FP_*` is NOT READ). | — | — | Deferred: needs a cached flag reader (proposal: `admin` publishes flags to Redis on PATCH; core middleware reads them with a 30 s local cache) |
| FR-ORG-002 (w2b request) | Medium | For students, the resolver calls `orgs.service.org_requires_mfa`. When it returns true and the student has no confirmed factor, every non-exempt route returns `403 mfa_enrolment_required` (`enrol_url=/app/settings/security/mfa`); MFA enrolment, login continuation and public routes stay open. Students who already have a factor are asked for it at login (existing `advance`). | `sessions/resolver.py` | `tests/identity/test_phase_b_identity.py::test_org_require_mfa_students_forces_enrolment` | Fixed+tested |
| ADM-12 | Low | No per-request `/me/grants` call was added in the middleware, to avoid an API round trip on every page. | — | — | Request to frontend (`PortalShell`) |

**Retention conflicts found while doing DB-02** (privacy doc wins):
- **Notifications:** privacy D13 is 1 year; the brief said 180 days. 1 year is used.
- **`attempt_events`:** kept at 24 months. Schema R-ASSESS-EVT says 24 months, privacy D15 says the attempt's life + 1 year, and D9 says 3 years. The DPO needs to decide.
- **`purge_cases` / `purge_closed_cases`:** neither is implemented (security).
- **Unblock attachments:** D8 is 90 days after closure, which an S3 lifecycle rule cannot express; the 455-day rule is only a backstop.
- **`devices` / `user_devices`:** `expire_devices` is not implemented.

**Note:** during this work one `ruff check --fix` / `ruff format` run went over the whole `apps/api/app` tree instead of only touched files. That may have applied formatting-only, behaviour-neutral changes to other owners' files. mypy on all of `app` passed afterwards.

## Requests

1. **frontend (web, outside core paths):**
   - `lib/nav/portals.ts:195`: make the second `safeNextPath` delegate to `features/auth/lib/validation.safeNextPath` (SEC-04).
   - `lib/nav/portals.ts`: remove the duplicate `/app/analytics` entry (commerce).
   - `PortalShell.tsx`: redirect with `next=` built from the `x-td-request-path` request header (`headers().get("x-td-request-path")`) instead of the portal prefix (commerce).
   - `PortalShell.tsx`: fetch `/me/grants` on the server and redirect when the portal is not in `portals`; add a portal switcher (ADM-12).
   - `lib/api/client.ts`: handle `mfa_enrolment_required` by navigating to `enrol_url`, falling back to `/app/settings/security` (INV-10).
   - `features/auth/lib/errors.ts` `retryAfterSeconds`: fall back to `err.retryAfter` (the header) or the body's `retry_after_seconds` (FE-09).
   - `components/shell/StepUpDialog.tsx`: students can no longer step up with a password. Implement `email_otp` / `sms_otp`: AUTH-19 `{send_otp_via}`, then AUTH-20 `{method, code}` (SEC-09). Show `reason: code_already_used` as "wait for the next code" (E2E-12).
   - `apps/web/README.md`: hops=0 now means "client IP unknown".
2. **commerce, assessments, analytics:** migrate your own rate limiters to `app.core.ratelimit` (`Rule`, `hit`, `check`, `MemoryBackend` for tests) and delete the copies, for example `commerce/ratelimit.py` becomes a re-export. Call sites were left alone (assess request 2).
3. **all modules with authenticated handlers (DB-06):** replace bare `await system_context(session, ...)` in request handlers with `async with system_context(session, "...")` around only the statements that need platform scope. Remaining sites:
   - `security/api_student.py` (16)
   - `support/router.py` (3), `orgs/router.py` (3), `learning/router.py` (3), `admin/router.py` (3), `placement/mentoring.py` (3)
   - `coding/service.py` (3), `rbac/service.py` (2), `entitlements/service.py` (2), `assessments/integrity.py` (2), `assessments/attempts.py` (1)
   - `notifications/router.py:157` (batch announce; core-owned, left as is because the rest of that handler is system work)
   - `commerce/pricing.as_system` can be replaced by `core.db.as_system`.
   - Jobs and pre-auth routes may keep the `await` form.
4. **admin / orgs (SEC-11, ADM-21):**
   - `admin/accounts.py:59`, `admin/router.py:54` and `orgs/lifecycle.py:50` advertise `"passkey"`, which cannot be used. Advertise `["totp"]` until WebAuthn exists, and document the TOTP exception for break-glass.
   - Admin `REQUIRED_ERASURE_MODULES` still needs providers from learning, assessments, coding, placement and support.
5. **admin (ADM-17):** expose a cached flag reader. Proposal: on flag PATCH, write `ff:<key>` to Redis; core then gates `platform.maintenance_mode` in middleware with `503 maintenance`.
6. **security:**
   - Implement `purge_closed_cases` (case data and attachments at closure + 90 days) and rename the `retention_policies` job.
   - `expire_devices` belongs to sessions/identity (core). Not built this round; tracked here.
7. **identity/media:** erasure clears `user_profiles.avatar_s3_key` but does not delete the S3 object. Add a storage delete or a lifecycle rule.
8. **docs:**
   - `api-specification.md`:
     - AUTH-01: the "same 201 shape" still differs in `session` and `next_steps`. Decide whether new signups should also get no session (log in after verifying) for full non-enumeration (SEC-05).
     - §1.1 line 92: "unknown fields → 422" contradicts §1.13 (400) (BE-33).
     - §1.6: student step-up password fallback only when the account has no other method (SEC-09).
   - `deployment-and-operations.md`:
     - The beat leader lock is now implemented.
     - Worker healthcheck is a liveness file.
     - `worker-judge` is the DB poller.
     - Sealer module is `app.modules.audit.sealer`.
     - CloudFront + ALB = 1 hop.
     - New jobs: `td.core.maint_*`, `notifications.renewal_reminders`.
   - `database-schema.md`:
     - §17: regenerate (DB-11).
     - §1.2 `td_maintenance`: list the real `maint.*` functions.
   - DPO: decide the `attempt_events` retention.
9. **infra follow-ups:**
   - Provision the `td_maintenance` secret as `DATABASE_MAINTENANCE_URL` for ECS `worker-maintenance`.
   - ECS service discovery for the web's `TD_API_INTERNAL_URL`.
   - Generate `apps/api/requirements.lock` with `pip-compile` / `uv`.
   - The repo `.env` points `DATABASE_MAINTENANCE_URL` at the dev DB: a dev `worker-maintenance` running this code purges dev data under the retention rules.
10. **coding (COM-09):** none needed. The `judge_*` beat entry was already removed.

## Test commands and results

All API commands run from `apps/api`; web commands from `apps/web`.

**API, from `apps/api`:**
- **Phase B regressions:** `TD_TEST_DB_NAME=techdrona_fix_core TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/core tests/identity tests/sessions tests/notifications tests/orgs -q`: **228 passed**, 0 failed. This includes `tests/core/test_phase_b_core.py` (17), `tests/identity/test_phase_b_identity.py` (12), `tests/notifications/test_provider_adapters.py` (4), `tests/core/test_maintenance.py` (11), erasure, consumers and replay tests.
- **Full API suite:** `TD_TEST_DB_NAME=techdrona_fix_core_full TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests --ignore=tests/_audit_scratch -q`: **762 passed, 7 failed** (run before the FR-ORG-002 change). None of the 7 is in core code:
  - `tests/admin/test_audit_phase_b_fixes.py::test_db01_erasure_not_completed_until_every_module_erased` expects `identity` to be missing an erasure provider. It is now registered, as secadmin requested, and other modules registered theirs too, so the request completes. **Request (secadmin):** update the test to monkeypatch the provider registry, or to assert on a module that is still missing.
  - Placement (5) and mentoring (1): placement's own answer endpoint returns 400 even on the first answer. `placement/bank.py` was being edited by the placement owner at 22:29, during the run. These belong to the placement or mentoring owner (in progress).
- **Audit probes:** `pytest tests/_audit_scratch/database -k race -s` gives `ATTEMPT_RACE {409: 5, 201: 1}` and `UNHANDLED []`.
- **Security probes:** `pytest tests/_audit_scratch/security/test_sec_probes.py tests/_audit_scratch/commerce/test_probe_ops.py -s` shows the fixed behaviour:
  - Rate limits: `[201×5, 429, 429]` for signups, 429 for forgot, reset and verify.
  - Password change: 401 then 429.
  - Student step-up with a password: 400.
  - Token rotated: True.
  - HMAC placeholders reported; beat queues with no consumer: `[]`.
  - The 4 failures are bug-asserting probes that no longer find their bug: signup enumeration timing, prod-gate gaps, SES/MSG91 not implemented, worker skipping checks. The probe ran before the signup timing floor was added.
- **Lint and types:** `ruff check` on core, worker, wiring, seeds, identity, sessions, notifications and their tests: clean. `ruff format --check` on the same: clean. `mypy app`: no issues in 228 files.
- **Maintenance migration:** `alembic heads` shows `core_base_0002 (core_base) (head)`. Downgrade by one then upgrade heads: OK.

**Web, from `apps/web`:**
- `npx vitest run src/lib/bff src/features/auth/lib src/middleware.test.ts`: 5 files, **48 passed**.
- The audit web probe `vitest run --config ../api/tests/_audit_scratch/security/web/vitest.audit.config.mjs`: 3/3 pass after the fix (2 failed before).
- `npx eslint src/lib/bff src/middleware.ts src/middleware.test.ts src/features/auth/lib --max-warnings=0`: clean.
- `npx tsc --noEmit`: clean.
- The full web suite, run earlier by the web sub-fork, had 8 failures, all in files owned by others (SignupForm timeouts, admin, LessonView, security-admin).

**Infra, from the repo root:**
- `docker compose --profile app config -q`: OK.
- `hashicorp/terraform:1.9.8 fmt -check -recursive` and `validate` (dev, staging, prod): valid.
- `docker buildx build --check` for api, web and postgres: no warnings.
- `rhysd/actionlint:1.7.7`: clean.
