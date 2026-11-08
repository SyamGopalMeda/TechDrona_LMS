# Stage 10 Integration Backlog (from Stage 3–9 agent hand-offs)

Owner: Integration Lead. Status per item: Open / Done (with pointer).

## A. Backend wiring between modules
1. Commerce access checker: catalog (lessons) and coding (problems) must call `entitlements.register_resource_parent_resolver`; product_items FKs to catalog/coding tables later.
2. Learning → commerce `register_usage_provider` (consumption % for refund/seat-release rules).
3. Analytics: switch outbox polling to `app.core.outbox.register_handler` (exists now); register `analytics.evidence.watched_seconds_for_lesson` with learning `register_video_coverage_lookup`; wire jobs to Celery beat via `app.core.jobs.register_periodic` (interval_builder, daily_aggregator, rollups, security_feed, retention_purge, video_coverage).
4. Assessments: Celery beat for deadline sweeper; `touch_engaged` use; coding questions in tests via `coding.judge_for_attempt` / `register_attempt_validator`.
5. Event name: `attempt.scored` (emitted) vs `attempt.graded` (architecture doc) — choose `attempt.scored`, update docs; check analytics consumes it.
6. Placement interim mastery (EWMA) → switch to `analytics.mastery.get_topic_mastery`.
7. Commerce webhook processing inline → Celery `critical` queue worker; rate limits; 60s decision cache.
8. Security ↔ commerce: `extend_entitlements_for_restriction` on false-positive approvals.
9. Media `stream_cap_hit` event → security signals; policy_settings caps instead of constants (catalog/media, sessions).
10. Verification token purpose `attempt_rebind` (currently reuses `step_up_otp`).
11. Public `check_permission` getter in app.core.auth (requested by coding & commerce).
12. Coding: run `run_startup_checks` order (done by core), hidden cases in DB until S3/KMS.

## B. Schema/doc sync (update docs/database-schema.md to match migrations)
Deviations recorded in: coding migration docstrings (`is_free`, `'fake'` provider, `normalized_sha256`, `retry_count`, blob table); catalog/learning/media migration docstrings; analytics README; commerce extra columns (contract grace/reassignment/version, `unit_price_paise`, `reconciliation_runs`, `seat_waitlist`); placement `practice_sessions.served`; identity (`mfa_factors.totp_confirmed_at`, guardian method); `idempotency_keys.user_id` soft ref.

## C. Frontend ↔ API contract reconciliation
- Many response shapes assumed by frontend agents (see each feature `lib/types.ts` "assumed" markers, and reports: AUTH/ME/UNB, CAT/COM/LRN, ANL-04/05, PLC/ASM, SEC-04/14/15, ADM-01/07/12, SUP-11, ORG import `csv_text`).
- Endpoints used by frontend but not in spec: `GET /assignments`, `/studio/coding/problems` (list/detail), `/mentor/sessions/{id}`, `/mentor/students` (+notes).
- Generate OpenAPI from FastAPI and type-check frontend against it (openapi-typescript) — contract tests.

## D. Web platform issues
- CSP: allow Razorpay checkout, S3/SeaweedFS presigned uploads (connect-src/form-action), VdoCipher player frames; Monaco served from /public/vendor (lint ignore for public/vendor).
- Remove stray debug test `src/features/assessment/tmp/dbg.test.ts` (lint error) if still present.
- Analytics tracker: support `video.*` events.
- Unsaved answers: localStorage → IndexedDB (spec).
- `/app/progress` bundle size (recharts 235 kB) — lazy load.
- Concurrent `.next` builds: CI single build; local fine.
- Route prefix differences vs brief (`/security`, `/desk`, `/verify/[certificate_id]`) — update brief/sitemap.

## E. DevOps / config
- `.env.example`: SELLER_GSTIN, SELLER_STATE_CODE, RAZORPAY_ACCOUNT_ID; boto3 dependency (media S3 creds chain).
- Healthcheck path `/healthz` (done) — verify compose app profile & Dockerfiles; web Dockerfile needs `output: "standalone"` + lockfile.
- Celery worker/beat services in compose `app` profile (`app.worker.celery_app`).
- Repo-wide ruff/mypy must be clean; CI run.
- Local test object `uploads/selftest/hello.txt` in local-td-uploads (harmless).
- Stray copy `D:/td-web-buildcheck` outside repo — product owner to delete manually.

## F. Verification
- Whole pytest on fresh DB; web lint/typecheck/test/build.
- Playwright @integration suites against running api+web+mailpit with seeds: identity, learning-commerce, student-learning, security-console, staff-portals.
- Owner scenarios SCN-01..20 status table.
- Authorization matrix tests (every endpoint × role × scope) — generated from role matrix.
- Performance smoke (k6) for attempts autosave; accessibility (axe) on key pages.

## Status updates (documentation sync, 2026-11-03)

Appended by the documentation/integration writer. Items not listed here keep their previous status.

- **B. Schema/doc sync — Done** (pointer: `docs/database-schema.md` v0.5 header, DDL tagged `-- v0.5`, §17 "As-migrated reference" incl. deviation register for every item in B; `docs/database-erd.md` §11). Planned — not yet migrated: `mentor_slots`, `mentor_bookings`, `interview_feedback`, `resumes`, `resume_reviews`, `support_tickets`, `support_ticket_messages`, `export_jobs`, `erasure_ledger`. Remaining code follow-ups (not doc items): ~20 cross-module soft references without FK (A1); partitions have only a DEFAULT partition (no pg_partman yet).
- **A5. Event name — Done (docs)** (pointer: `docs/system-architecture.md` §4.2, §7.4, §8.7, §13, §24.4; `docs/analytics-event-schema.md` §2.4; `docs/api-specification.md` header). `attempt.scored` is emitted by `assessments/attempts.py` and consumed by `analytics/consumer.py`.
- **C. Endpoints used by frontend but not in spec — Partially done (docs)** (pointer: `docs/api-specification.md` §28 lists the frontend gaps). `GET /assignments`, `GET /studio/coding/problems` (list), `/mentor/sessions/{id}`, `/mentor/students` (+notes) are still not implemented in the API.
- **D. Route prefix differences vs brief — Done** (pointer: `docs/blueprint-brief.md` §8.1; `docs/sitemap.md` §13). `/security`, `/desk`, `/verify/[certificate_id]` are canonical; aliases in `apps/web/next.config.ts`. Other D items are code items (not owned by docs) and stay Open.
- **F. Owner scenarios SCN-01..20 status table — Done (docs)** (pointer: `docs/implementation-status.md` §5): 19/20 covered by API tests; SCN-02 partial.
