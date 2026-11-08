# Tech Drona LMS

Tech Drona is a placement-preparation learning platform for Indian engineering and degree students. It is run by a single company, Tech Drona, which sells directly to individual learners and runs its own training batches (single-company mode, see [ADR-0015](docs/architecture-decisions/ADR-0015-single-company.md) and [`docs/single-company/REMOVAL-PLAN.md`](docs/single-company/REMOVAL-PLAN.md)); there is no college portal or B2B contract flow. Businesses can send a corporate enquiry at `/enquiries`. It covers four workloads in one product:

- a structured LMS: courses, batches, DRM video, progress, assignments, certificates;
- a placement-practice engine: aptitude, programming, DSA, CS fundamentals, company paths, interview prep;
- a timed-assessment engine with a sandboxed coding judge;
- an India-compliant commerce stack (Razorpay, UPI AutoPay, GST invoices) with one central entitlement system.

Its main difference from other platforms is **verifiable trust**: published device and session rules, explainable account-sharing controls with human review and appeal, a server-authoritative test timer, and DPDP-compliant privacy from day one.

## Status

| Item | State |
|---|---|
| Overall | **Implementation in progress: Stage 10 (integration)** |
| Stages 1–2 Discovery and product design | Done. Blueprint, ADR-0001..0014 and wave-2 consistency pass complete (`docs/blueprint-brief.md` **v0.3**) |
| Stage 3 Technical foundation | Implemented: monorepo, docker-compose, FastAPI kernel (RLS, outbox, audit hash chain, Celery), Next.js BFF, CI |
| Stages 4–9 Modules | Implemented and tested locally against fakes: identity, sessions, rbac, orgs, catalog, media, learning, placement, assessments, coding, commerce, entitlements, analytics, notifications, security/risk engine, unblock workflow, admin, audit |
| Stage 10 Integration | **In progress.** Backlog: [`docs/stage10-integration-backlog.md`](docs/stage10-integration-backlog.md) |
| Deployed | **Nothing is deployed.** `deploy.yml` is a disabled skeleton; no AWS account, credentials or provider keys exist yet |
| Status vocabulary | Planned → Implemented → Tested → Deployed (roadmap §7) |

The full plan is the 12 stages in [`docs/implementation-roadmap.md`](docs/implementation-roadmap.md). It aims at a pilot from about June 2027 and a production launch around mid-August 2027.

### Fakes awaiting real credentials

Every external integration has a local fake or stub. None of the real adapters has been verified against its provider.

| Integration | Local stand-in | Switch to the real one |
|---|---|---|
| Razorpay (payments, UPI AutoPay, webhooks) | `FakePaymentProvider` (`PAYMENTS_PRIMARY_PROVIDER=fake`) | `razorpay` + `RAZORPAY_KEY_ID/_SECRET/_WEBHOOK_SECRET/_ACCOUNT_ID` |
| Cashfree (fallback) | off (`PAYMENTS_FALLBACK_PROVIDER_ENABLED=false`); webhook verification only | `CASHFREE_APP_ID/_SECRET_KEY` |
| Judge0 (coding judge) | `FakeJudgeAdapter` (`JUDGE_PROVIDER=fake`) | `judge0_cloud` + `JUDGE0_BASE_URL/_API_KEY` |
| VdoCipher (DRM video) | `FakeVideoProvider` (`VDOCIPHER_MODE=stub`) | `VDOCIPHER_API_SECRET` |
| Malware scanning of uploads | `FakeMalwareScanner` | provider to be chosen |
| Email (SES) | SMTP to Mailpit (`EMAIL_PROVIDER=smtp`) | `ses` + verified sender |
| SMS (MSG91, DLT) | console (`SMS_PROVIDER=console`) | `msg91` + `MSG91_*` DLT ids |
| KMS envelope keys | static local keys (`*_KMS_KEY_ID=local`) | AWS KMS aliases |
| S3 / CloudFront signed URLs | SeaweedFS on :9000 | AWS S3 + CloudFront key pair |
| GST invoice seller | placeholder `SELLER_GSTIN` / `SELLER_STATE_CODE` | real GSTIN |
| Error tracking | disabled (`SENTRY_DSN` empty) or local GlitchTip profile | self-hosted GlitchTip in ap-south-1 |

## Document index

### `docs/`

| File | Description |
|---|---|
| [`blueprint-brief.md`](docs/blueprint-brief.md) | Binding shared contracts (**v0.3**): confirmed decisions, module map, roles, canonical table names, API conventions, file ownership. Wins over every other doc when they conflict |
| [`contract-reconciliation.md`](docs/contract-reconciliation.md) | How the 76 wave-1 contract change proposals were resolved, the conflict resolutions, the table inventory delta, the open product-owner decisions (PO-01..13), the required follow-up edits, and (§7) the wave-2 consistency pass: canonical decisions and the issue log for every wave-2 document |
| [`integration-pass-requests.md`](docs/integration-pass-requests.md) | Integration Lead's wave-2 change requests (IPR-*) to the API spec, testing, deployment, roadmap, README, `.env.example`, source excerpt, security and analytics docs |
| [`consistency-pass-requests.md`](docs/consistency-pass-requests.md) | Security review pass change requests (CPR-*, 107 items across 10 files): separation classes, high-confidence rules, kill switch, bulk lift, HMAC key versioning, 395-day log retention, webhook re-fetch |
| [`source-requirements-excerpt.md`](docs/source-requirements-excerpt.md) | Verbatim lists from the product owner: Section H security reports, the 20 Phase-8 account-sharing test scenarios, required session fields, unblock statuses, the Phase-9 deliverables list |
| [`product-requirements.md`](docs/product-requirements.md) | PRD: personas, functional requirements (FR-*) with P0/P1/P2 priority, NFRs, screen inventory, user journeys, dashboards, acceptance criteria, out-of-scope items, open product decisions (OPD-01..13) |
| [`feature-comparison.md`](docs/feature-comparison.md) | Feature-by-feature comparison of Tech Drona's planned scope against the reference platforms, with evidence labels |
| [`role-permission-matrix.md`](docs/role-permission-matrix.md) | The roles (single-company target: Admin, Trainer, Evaluator, Content manager, Student), scoped grants, permission matrix, tenant-isolation rules, separation of duties, data-visibility tiers |
| [`system-architecture.md`](docs/system-architecture.md) | Modular-monolith architecture: containers, module boundaries and dependencies, request lifecycle, auth, placement/assessment/coding/payment designs, jobs, caching, deployment overview, scalability, monorepo layout, open risks |
| [`database-schema.md`](docs/database-schema.md) | PostgreSQL 16 schema for all 121 tables: columns, constraints, indexes, RLS policies, partitioning, retention |
| [`database-erd.md`](docs/database-erd.md) | Entity-relationship diagrams per domain, aligned with the reconciled schema |
| [`account-security-and-risk-engine.md`](docs/account-security-and-risk-engine.md) | Session and device tracking, configurable policies, signal catalogue, rule-based risk scoring v1, graduated restrictions L1–L4, enforcement points, Section H reports, Phase-8 scenario design |
| [`account-unblock-workflow.md`](docs/account-unblock-workflow.md) | Unblock and appeal workflow: states, SLAs, reviewer actions, dual approval, student-facing messaging |
| [`security-threat-model.md`](docs/security-threat-model.md) | STRIDE threat model mapped to the OWASP API Top 10, abuse cases, control targets (ASVS 5.0 L2, L3 for privileged consoles) |
| [`privacy-and-data-retention.md`](docs/privacy-and-data-retention.md) | DPDP Act 2023 + Rules 2025 design: itemised consent, minors, data-subject rights, retention schedule, erasure, breach and CERT-In duties |
| [`analytics-event-schema.md`](docs/analytics-event-schema.md) | Analytics event model, time-on-task measurement (heartbeats, engaged intervals), aggregates, mastery, the security feed, privacy floors |
| [`implementation-roadmap.md`](docs/implementation-roadmap.md) | 12-stage delivery plan: per-stage scope, owners, file ownership, exit criteria, durations, MVP pilot cut, ranked risks, external blockers, product-owner decision log |
| [`api-specification.md`](docs/api-specification.md) | REST API contract (`/api/v1`): conventions, auth and sessions, every endpoint with permission, scope and route tag, problem+json error catalogue, webhooks at `/api/v1/webhooks/{provider}` |
| [`testing-and-acceptance-criteria.md`](docs/testing-and-acceptance-criteria.md) | Test strategy, acceptance tests per FR, the 20 Phase-8 scenarios, tenant-isolation and security suites, load profiles, seed labelling |
| [`deployment-and-operations.md`](docs/deployment-and-operations.md) | AWS ap-south-1 environments, ECS services, Terraform, CI/CD, migrations, secrets (versioned HMAC keys), observability (self-hosted GlitchTip), 395-day log retention, backups/DR, runbooks (incl. kill switch and bulk false-positive lift), costs, launch checklists |

### `docs/architecture-decisions/`

| File | Decision |
|---|---|
| [`ADR-0001-modular-monolith.md`](docs/architecture-decisions/ADR-0001-modular-monolith.md) | FastAPI modular monolith with an isolated code-execution boundary; no microservices in v1 |
| [`ADR-0002-server-side-sessions.md`](docs/architecture-decisions/ADR-0002-server-side-sessions.md) | Opaque server-side sessions in `__Host-` cookies behind a same-origin BFF; no bearer tokens in the browser |
| [`ADR-0003-postgres-rls-tenancy.md`](docs/architecture-decisions/ADR-0003-postgres-rls-tenancy.md) | Tenant isolation by application scoping plus PostgreSQL RLS with FORCE |
| [`ADR-0004-analytics-storage.md`](docs/architecture-decisions/ADR-0004-analytics-storage.md) | Raw analytics in time-partitioned Postgres with short retention; ClickHouse evaluated later |
| [`ADR-0005-code-execution-isolation.md`](docs/architecture-decisions/ADR-0005-code-execution-isolation.md) | `judge-gateway` with Judge0 Cloud in phase 1; a self-hosted hardened judge in phase 2 |
| [`ADR-0006-payments-razorpay.md`](docs/architecture-decisions/ADR-0006-payments-razorpay.md) | Razorpay primary, Cashfree fallback adapter, entitlement-centric access |
| [`ADR-0007-video-vdocipher.md`](docs/architecture-decisions/ADR-0007-video-vdocipher.md) | VdoCipher DRM + dynamic watermark; stream cap enforced at OTP issuance |
| [`ADR-0008-background-jobs.md`](docs/architecture-decisions/ADR-0008-background-jobs.md) | Celery on a dedicated `noeviction` Redis broker with a transactional outbox |
| [`ADR-0009-migrations-ownership.md`](docs/architecture-decisions/ADR-0009-migrations-ownership.md) | One Alembic history at `apps/api/migrations`, one schema owner, expand → migrate → contract |
| [`ADR-0010-nextjs-bff.md`](docs/architecture-decisions/ADR-0010-nextjs-bff.md) | Next.js as the same-origin BFF; FastAPI not exposed to the internet |
| [`ADR-0011-outbox-and-audit-hash-chain.md`](docs/architecture-decisions/ADR-0011-outbox-and-audit-hash-chain.md) | Transactional outbox and an append-only, hash-chained audit log with external anchoring |
| [`ADR-0012-identifiers-time-money.md`](docs/architecture-decisions/ADR-0012-identifiers-time-money.md) | UUIDv7 identifiers, UTC `timestamptz`, money as integer paise |
| [`ADR-0013-assessment-state-and-timer.md`](docs/architecture-decisions/ADR-0013-assessment-state-and-timer.md) | Server-authoritative test timer, frozen layouts, frequent autosave (max interval 10 s per brief v0.3), crash resume |
| [`ADR-0014-error-tracking-data-residency.md`](docs/architecture-decisions/ADR-0014-error-tracking-data-residency.md) | Error tracking on self-hosted GlitchTip in AWS ap-south-1; no Sentry SaaS |
| [`ADR-0015-single-company.md`](docs/architecture-decisions/ADR-0015-single-company.md) | Single-company mode: one company organization, college/B2B features removed, five roles |

### `research/` and related folders

| File | Description |
|---|---|
| [`research/reference-platform-analysis.md`](research/reference-platform-analysis.md) | Canonical research report: platform comparison, account-sharing evidence, student journey friction, admin workflows, recommended and differentiating features, risks, costs, open legal questions, implementation priorities |
| `research_notes/Tech Drona LMS reference platforms/*.md` | Raw research notes used by the report (**not a deliverable**): account-sharing prevention, coding assessment platforms, Coursera-style course platforms, Indian privacy (DPDP), Moodle/Canvas/Open edX architecture, OWASP auth/session security, PrepInsta-style placement platforms |
| `reports/Tech Drona LMS reference platforms.md` | **Byte-identical copy** of `research/reference-platform-analysis.md`. `research/` is canonical; do not edit the copy |

Root files: [`.env.example`](.env.example) is the environment template (placeholders only; DevOps owns it). [`docs/local-development.md`](docs/local-development.md) covers local setup and [`docs/stage10-integration-backlog.md`](docs/stage10-integration-backlog.md) tracks the Stage 10 integration work.

## Changelog

| Date | Change |
|---|---|
| 2026-11-03 | Initial README (Integration Lead) |
| 2026-11-03 | Stage 10: status "implementation in progress"; real repository layout; quick start (compose, migrate, seed, run, URLs, demo accounts); test commands; fakes awaiting credentials (DevOps) |
| 2026-11-03 | Consistency pass: status "blueprint complete, implementation not started"; brief v0.3; index lists every file in `docs/`, `docs/architecture-decisions/` (incl. ADR-0014) and `research/`, including `integration-pass-requests.md`, `consistency-pass-requests.md` and the three wave-2 docs; `reports/`/`research_notes/` status clarified (IPR-README-01, IPR-README-02) |

## Repository layout

```
apps/
  web/            Next.js 15 App Router (TypeScript, Tailwind): UI and same-origin BFF
  api/            FastAPI modular monolith + Celery workers (one image)
    app/core/     kernel: config, db + RLS context, outbox, audit, jobs, authz, crypto
    app/modules/  identity, sessions, security, orgs, rbac, catalog, learning, placement,
                  assessments, coding, commerce, entitlements, analytics, notifications,
                  audit, support, media, admin
    app/seeds/    DEV/DEMO seed scripts (never shipped in the image) + rbac reference data
    app/worker.py Celery app (app.worker.celery_app)
    migrations/   Alembic, one branch per module (ADR-0009)
    tests/
packages/         shared workspace packages (design tokens)
infra/
  docker/         local images/config (Postgres 16 + pg_partman, SeaweedFS S3)
  terraform/      AWS ap-south-1 (ECS Fargate, RDS, ElastiCache, S3, CloudFront): not applied
scripts/          dev-up, run-api, run-web, seed-dev, reset-db, reset-dev-data (.ps1), test-all (.ps1 and .sh)
docs/             blueprint documents, ADRs, local development, Stage 10 backlog
```

## How to run (local)

The full guide is [`docs/local-development.md`](docs/local-development.md). Prerequisites: Docker Desktop, Python 3.12+ and Node.js 22.

```powershell
# 1. Data services: Postgres 16, Redis x2, Mailpit, S3 emulator. Creates .env from .env.example.
./scripts/dev-up.ps1                                 # bash: scripts/dev-up.sh

# 2. API (first run creates apps/api/.venv, installs deps, migrates): http://localhost:8000
./scripts/run-api.ps1 -Install -Migrate              # later runs: ./scripts/run-api.ps1

# 3. Demo data, second terminal (idempotent; refuses when APP_ENV=production)
./scripts/seed-dev.ps1                               # bash: scripts/seed-dev.sh  |  make seed
# Deterministic clean slate (DEV ONLY): drops/recreates the `techdrona` DB, migrates, seeds,
# writes apps/web/.env.e2e.local for Playwright and restarts running app containers.
./scripts/reset-dev-data.ps1 -Force
# Full E2E pass afterwards (compose app profile up):  cd apps/web; npx playwright test --project=chromium --workers=1

# 4. Web, third terminal: http://localhost:3000
./scripts/run-web.ps1

# Alternative to steps 2 and 4: the whole app in containers: api, api-webhooks, Celery worker, worker-maintenance,
#     beat, judge worker, audit sealer, web. API http://localhost:18000, web http://localhost:13000
docker compose --profile app up -d --build --wait
```

| URL | What |
|---|---|
| http://localhost:3000 (host) / http://localhost:13000 (compose) | Web app (Next.js BFF) |
| http://localhost:8000/healthz / http://localhost:18000/healthz | API liveness; `/docs` for OpenAPI (local only) |
| http://localhost:8025 | Mailpit: sign-up, OTP and notification emails |
| http://localhost:9000 | S3 emulator (buckets `local-td-*`) |

**Demo accounts** (created by `dev_users`, synthetic, local only): `student@`, `minor.student@`, `trainer@`, `evaluator@`, `content@`, `admin@` and `admin2@dev.techdrona.local` (the target single-company seed; until the WS1 re-seed lands the older seed may still create `coordinator@`, `support@`, `security@` and `finance@`). The seed prints the shared password and a TOTP secret for each staff account; add the secret to an authenticator app. Other seeds add the demo courses (`demo-dsa-free`, `demo-aptitude-paid`), 12 placement questions and a mock test, 3 coding problems, `DEMO-*` products with coupons `DEMO25` and `DEMOFLAT200`, and one security case for the student.

### Tests

```powershell
./scripts/test-all.ps1        # everything below; bash: make test
cd apps/api
.venv/Scripts/ruff check . ; .venv/Scripts/ruff format --check . ; .venv/Scripts/mypy
$env:TD_TEST_DB_NAME='techdrona_test'; .venv/Scripts/pytest -q      # real Postgres, runs as td_app
cd ../web
npm run lint ; npm run typecheck ; npm test ; npm run build
$env:E2E_BASE_URL='http://localhost:13000'; $env:E2E_INTEGRATION='1'; npx playwright test   # needs seeds + E2E_* logins
```

CI (`.github/workflows/ci.yml`) runs the same commands, plus migration round-trips, image builds with Trivy, and security scans. On main and nightly it also runs an end-to-end job that starts the compose `app` profile, seeds the database and runs Playwright.

## Contribution and agent rules (summary)

1. **Contracts first.** `docs/blueprint-brief.md` (v0.3) and `docs/database-schema.md` win over every other doc until the change requests in `docs/integration-pass-requests.md` and `docs/consistency-pass-requests.md` are applied. Do not edit a contract you do not own. Propose a change under "Contract change proposals" in your own document and follow the process in roadmap §6.
2. **One owner per file.** Each document and code directory has exactly one owning agent or lane (brief §6, roadmap §3.2, enforced by CODEOWNERS). To change someone else's file, raise a change request. Never edit it directly.
3. **One writer per table, one migration author.** Modules write only their own tables and call other modules only through `public.py`. Only the Architect writes Alembic migrations (`apps/api/migrations`). Merges happen in a daily slot.
4. **Security by default.** Every authenticated route uses `require_active_principal` and declares a permission and scope. Student code never runs on app servers. No card data, videos or binaries go in Postgres. Minors never get behavioural risk scoring.
5. **Evidence over time.** No completion, certificate or grade may depend on time thresholds alone.
6. **Honest status.** Use only Planned / Implemented / Tested / Deployed, with the definitions in roadmap §7. Keep research evidence labels ([Verified] / [Reported] / [Rec]) when citing.
7. **Seed data** must be clearly labelled dev/demo only. Secrets go only in AWS Secrets Manager, never in the repository.
