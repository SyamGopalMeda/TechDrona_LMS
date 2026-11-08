# Tech Drona LMS — Integration Pass Requests (wave-2 consistency pass)

| Field | Value |
|---|---|
| Owner | Integration Lead |
| Date | 2026-11-03 |
| Status | **Planned** (blueprint stage, documentation only) |
| Basis | `docs/blueprint-brief.md` **v0.3**; decisions and issue log in `docs/contract-reconciliation.md` §7 |

The Integration Lead resolved the wave-2 cross-document issues in brief v0.3, `database-schema.md`/`database-erd.md` v0.3, `role-permission-matrix.md` v0.2, `product-requirements.md` v0.2, `system-architecture.md` v0.3 and ADR-0006/0009/0010/0011/0014. The files below were outside the Integration Lead's edit set for this pass. Their owners apply these changes. Each request is written so it can be applied mechanically. Until they are applied, **brief v0.3 and the schema win**.

Request ids: `IPR-<file>-nn`. "Resolves" points to the issue in the source document and to the `contract-reconciliation.md` §7 log row.

---

## Requests from Integration Lead

### 1. `docs/api-specification.md` (Backend Lead, BE-1)

| # | Location | Change | Resolves |
|---|---|---|---|
| IPR-API-01 | SEC-32 row and detail | Permission `report.export` @P → `report.export.request` @P. Replace "per-user rows need a second `security_reviewer`" with "per-user rows need approval by a `super_admin` holding `report.export.approve` (approver ≠ requester); the job waits in `awaiting_approval`" | API I-03; F-RPM-5 |
| IPR-API-02 | ANL-13 row | `report.export` @scope → `report.export.request` @scope (security_reviewer, finance_admin @P; college_coordinator @O; trainer @B). Remove "(S for own data via PRV)": own-data export is a privacy rights request. The Dual for bulk PII > 10,000 rows is approved through `report.export.approve` (super_admin) | API I-03 |
| IPR-API-03 | AUD-05 row | `audit.read @P + report.export @P` → `audit.read @P + report.export.request @P` | API I-03 |
| IPR-API-04 | ADM-12..ADM-15 (approvals) | Add: approvals whose `action_type` is an export (`report_export`) require `report.export.approve`; approvals whose `action_type` is a policy change require `policy.edit`; other action types keep `approval.decide` per action type | F-RPM-5 |
| IPR-API-05 | SEC-33, SEC-34 rows | Permission `security.case.read` / `security.case.decide` → `security.network.verify` @P (both rows) | API I-03 |
| IPR-API-06 | SEC-37 row | `security.case.read @P (security lead) / audit.read @P (super_admin)` → `security.incident.read` @P (security_reviewer, super_admin) | API I-03 |
| IPR-API-07 | SEC-38, SEC-39 rows | `security.case.decide` @P → `security.incident.manage` @P | API I-03 |
| IPR-API-08 | ADM-09 row | Permission `policy.edit @P (security_reviewer may propose security keys; see §27)` → `policy.propose @P` (namespace-limited: security_reviewer for `risk.*`, `sessions.*`, `devices.*`, `playback.*`, `login.*`, `otp.*`, `unblock.*`, `assessment.*`; finance_admin for `commerce.*`; super_admin any). Execution creates an `approval_requests` row approved by a different `super_admin` with `policy.edit` | API I-02 |
| IPR-API-09 | ANL-01 row (and §5.1 text if any) | Add "max 100 events per request" (larger batches rejected with the spec's existing batch-size error). Permission column: keep `S (self only)`; add footnote "no permission key; authenticated ownership (role matrix §2.7 note)" | API I-03, I-16 |
| IPR-API-10 | Line ~75 "Session states", line ~99 rule 6, §1 tag table row `login_continuation`, AUTH session-cap flow (~line 294, 468) | Add `pending_session_choice` to the `auth_sessions.status` list. The session-cap `409 session_cap_reached` (`prompt_choose`) moves the new session to `pending_session_choice` (≤ 5 min) instead of keeping its last pending status; `login_continuation` routes accept `pending_session_choice`; rule 6 includes it | API I-08 |
| IPR-API-11 | ATT autosave config example (~line 1409) and any text saying 15 s | `"max_interval_ms": 15000` → `10000`; "max 15 s" → "max 10 s" | API I-17 |
| IPR-API-12 | Commerce example (~line 1683) and any `product_kind` list | `"product_kind": "company_pack"` → `"placement_package"`. Allowed values: `free_resource`, `free_course`, `course`, `bundle`, `subscription_plan`, `placement_package`, `mock_pack`, `institution_seat`, `extra_learner_seat` | API I-12 |
| IPR-API-13 | Order status text/enums | Order statuses: `created`, `pending_payment`, `paid`, `failed`, `expired`, `cancelled`, `refunded`, `partially_refunded` (confirm; no change if already so) | API I-13 |
| IPR-API-14 | Refund decision endpoint (finance) | Add: goodwill refunds always create an `approval_requests` row (stored in `refunds.approval_request_id`; DB CHECK `ck_refund_goodwill_dual`); refunds above `commerce.refund.dual_approval_above_paise` (default 2,500,000 paise = ₹25,000) also need it; approver = second `finance_admin` | API I-22 |
| IPR-API-15 | §1.3 CSRF table and line ~71 `td_csrf` row | "`HMAC(server_key, …)`" → "`HMAC(TD_CSRF_KEY, …)` minted and validated by the BFF (`web`); the `api` service does not issue or check `td_csrf` and never holds the key (ADR-0010 v0.3)". The beacon body token is validated by the BFF | DEP I-14 |
| IPR-API-16 | §1 errors table | Add `503 maintenance` (`platform.maintenance_mode` on; writes refused, GETs and health allowed; `Retry-After`; webhooks also 503 so providers retry) | DEP I-16 |
| IPR-API-17 | §1 transport | Add a BFF-only route `POST /api/v1/_errors` (GlitchTip tunnel; not a FastAPI route; no cookies forwarded; 60/min per IP) — ADR-0014 | DEP I-06 |
| IPR-API-18 | §26 FR mapping (~lines 2173, 2176) | `FR-SEC-002` → `FR-SEC-002a` (L1–L2, P0) / `FR-SEC-002b` (L3–L4, P1) as applicable | ROAD I-7 |
| IPR-API-19 | §27 Issues | Mark I-01..I-20, I-22..I-24 **Resolved (contract-reconciliation §7)**; I-21 and I-25 **Routed to Security Specialist** | all |
| IPR-API-20 | Webhooks §18 | No path change (`/api/v1/webhooks/{provider}` is canonical). Add a sentence: "Staleness rule per ADR-0006 v0.3: no age-based rejection for Razorpay; Cashfree payloads older than `WEBHOOK_TOLERANCE_SECONDS` (300) are not trusted; any stale/out-of-order event is applied only from a server-side re-fetch" | API I-14, I-24 |

### 2. `docs/testing-and-acceptance-criteria.md` (QA Lead)

| # | Location | Change | Resolves |
|---|---|---|---|
| IPR-QA-01 | §6 intro and table | Replace "QA's working assumption" with "the canonical 12-stage order in `implementation-roadmap.md` §2 (brief v0.3 §7)". Re-key the table to roadmap stages: 1 Discovery ← QA 1; 2 Product design ← QA 2 + QA 3; 3 Technical foundation ← QA 4 + QA 5; 4 Identity & permissions ← QA 6; 5 Core LMS ← QA 8; 6 Placement prep (incl. timed MCQ assessments) ← QA 9 (MCQ/assessment part: AC-ASM-01..06, SCN-16, P1); 7 Account security & monitoring ← QA 7; 8 Commerce & college management ← QA 10 + college parts of QA 11; 9 Coding assessments ← QA 9 (coding part: AC-COD-01/02, TS-JUDGE, P5); 10 Integration & hardening ← QA 11 remainder + hardening part of QA 12; 11 Pilot ← UAT part of QA 12; 12 Production ← release part of QA 12. Update references to "Stage n" elsewhere (e.g. §13 "Needed by" column) to the roadmap numbering | QA I-01 |
| IPR-QA-02 | §2/TS-AUTHZ "Source of truth" (~line 83) | `permissions.yaml` → `apps/api/app/core/authz/permissions.yaml` generated from role matrix §2/§3/§5 (role matrix v0.2 §10). Add test cases: `report.export.approve` approver ≠ requester; `policy.propose` namespace limits; `security.incident.*`, `security.network.verify` only for security_reviewer (super_admin read-only for incidents) | QA I-04 |
| IPR-QA-03 | §8 seed labelling (~line 787) and I-06 | Use `users.is_synthetic` / `organizations.is_synthetic` (schema v0.3). Production rule: only the synthetic-monitoring provisioning job may set it; add a test that analytics aggregates, risk scoring, invoices and k-counts exclude synthetic rows | QA I-06; DEP I-15 |
| IPR-QA-04 | Any autosave assertion | Max autosave interval 10 s (`max_interval_ms: 10000`), debounce 5 s | API I-17 |
| IPR-QA-05 | Session-cap tests (AC-SES-02 area) | Assert the pending session has `status = 'pending_session_choice'` while the chooser is shown and expires after 5 min | API I-08 |
| IPR-QA-06 | TS-PAY | Add cases: subscription grace = 5 days (`commerce.subscription_grace_days`); goodwill refund cannot reach `approved` without `approval_request_id`; Razorpay event older than 5 min is processed via re-fetch, not rejected | API I-11, I-14, I-22 |
| IPR-QA-07 | Error-code assertions | Stream cap `409 playback_conflict`; step-up `401 step_up_required`; no factor `403 mfa_enrolment_required`; maintenance `503 maintenance` | API I-04, I-10; DEP I-16 |
| IPR-QA-08 | §13 Issues | Mark I-01, I-04, I-06, I-07, I-09, I-10, I-12 **Resolved (contract-reconciliation §7)**; I-02, I-03, I-05, I-08, I-11 remain with the Security Specialist | all |

### 3. `docs/deployment-and-operations.md` (DevOps)

| # | Location | Change | Resolves |
|---|---|---|---|
| IPR-DEP-01 | §4 CloudFront behaviours (~line 223), WAF rule 1 (~231), Razorpay row (~257), RB webhook runbook (~657), any `/webhooks/*` | `/webhooks/*` → `/api/v1/webhooks/*`; Razorpay URL `https://<domain>/api/v1/webhooks/razorpay`. The CloudFront behaviour and ALB listener rule for `/api/v1/webhooks/*` must be ordered **before** the generic `/api/*` → `web` rule and target `api-webhooks` directly | DEP I-13; API I-24 |
| IPR-DEP-02 | Secrets/env tables and §11 | `TD_CSRF_KEY` (+ `_PREVIOUS`) provisioned to `web` only; remove from `api` | DEP I-14 |
| IPR-DEP-03 | Line ~263 Sentry row, `obs/sentry-dsn` (~443), §11.3 item 5 (~490), §11.4 (~497), processor list (~651), cost rows (~747, ~770), risk O-3 (~951) | Replace Sentry SaaS with self-hosted **GlitchTip** in ap-south-1 (ADR-0014): new ECS service `errors` (web 1 × 0.5 vCPU/1 GB, worker 1 × 0.25/0.5), DB `glitchtip` on the existing RDS with its own role, `cache` Redis; internal ALB reachable only from VPC/SSO; secret `obs/glitchtip-dsn`; 90-day event retention; browser events via the BFF tunnel `/api/v1/_errors`. Remove Sentry from the processor breach list; close O-3 | DEP I-06 |
| IPR-DEP-04 | §3 service table (~146) | Confirm `audit-sealer` as above (1 task, `TD_ROLE=audit_sealer`, `td_audit_sealer` creds, only `s3:PutObject` on `td-audit-anchor`). Close I-03 | DEP I-03 |
| IPR-DEP-05 | DB roles (~52, ~426, ~857) and §13 retention jobs (~808–831) | Add DB role `td_maintenance` (secret `db/td_maintenance`, 90-day rotation, used only by the `worker` with `CELERY_QUEUES=maintenance`). Partition premake (`maint.run_partition_maintenance()`) daily 01:00 IST; partition drops (`maint.drop_expired_partitions(parent)`) and purges at the privacy §7 times (03:00/03:30/04:00 IST). Retention jobs run on the `maintenance` queue, not `worker-default`. Remove the note on the scheduling difference (arch §14 now matches) | DEP I-10, I-11 |
| IPR-DEP-06 | §12.3 backups (~569) and DR table (~594) | Enable the AWS Backup daily cross-region snapshot copy to ap-south-2 **from pilot day 1** (pilot RPO for region loss ≤ 24 h); budget +US$30–60/month flagged to the product owner | DEP I-09 |
| IPR-DEP-07 | Backups | Record: all backups containing personal data ≤ 35 days in v1 (no month-end/year-end snapshots of personal data); finance needs are met by GST records in the live DB (R-FIN) | DEP I-07 |
| IPR-DEP-08 | WAF | Approve the `org_trusted_networks` → WAF IP-set sync job (owner `security`, runs on `worker` `default` queue, verified networks only, higher rate limit, never an allowlist that bypasses auth). The Security Specialist may veto | DEP I-08 |
| IPR-DEP-09 | Synthetic monitoring (~372) | Synthetic accounts use `users.is_synthetic = true` (schema v0.3), created only by the synthetic-monitoring provisioning job | DEP I-15 |
| IPR-DEP-10 | Restore cutover §12.4 and RB-04 | Use feature flag `platform.maintenance_mode` (writes `503 maintenance` + `Retry-After`; GETs/health allowed; webhooks 503) | DEP I-16 |
| IPR-DEP-11 | §20 Issues | Mark I-03, I-05, I-06, I-07, I-08, I-09, I-10, I-11, I-13, I-14, I-15, I-16 **Resolved (contract-reconciliation §7)**; I-01, I-02, I-04, I-12 remain with the Security Specialist | all |

### 4. `docs/implementation-roadmap.md` (Integration Lead / TPM — frozen for this pass)

| # | Location | Change | Resolves |
|---|---|---|---|
| IPR-ROAD-01 | Stage work-breakdown rows (~lines 228, 253, 276, 298, 319) | `migrations/**` → `apps/api/migrations/**` | ROAD I-1 |
| IPR-ROAD-02 | Risk R3 (~line 504) | "≤ 15 s autosave" → "≤ 10 s autosave" | API I-17 |
| IPR-ROAD-03 | Lines ~265 and ~453 | `FR-SEC-002` → `FR-SEC-002a` (P0) / `FR-SEC-002b` (P1) | ROAD I-7 |
| IPR-ROAD-04 | §2 Stage 2 "State today" | Wave-2 docs exist (API spec, testing, deployment); wave-2 consistency pass done (brief v0.3); remaining follow-ups = this file + `contract-reconciliation.md` §6.4–§6.8 | ROAD I-2, I-3 |
| IPR-ROAD-05 | §3.2 ownership map | Add `docs/integration-pass-requests.md` to the IL row; add `docs/ux-design-system.md` as UX (brief §6 row now exists); note `apps/api/app/core/authz/permissions.yaml` (SE path, RP approves content); add `infra/**` GlitchTip service under DO | ROAD I-6; QA I-04 |
| IPR-ROAD-06 | §10 external dependencies | Add test infrastructure: Razorpay and Cashfree test accounts, VdoCipher test account, Judge0 test quota, SMS sandbox, perf environment sized like production, isolated DR-restore account, CERT-In-empanelled pen-test vendor (owner DO/TPM, needed by Stage 3) | QA I-10 |
| IPR-ROAD-07 | §12 Issues | Mark I-1, I-2, I-3 (partly: architecture/PRD/role matrix follow-ups applied), I-4, I-5, I-6, I-7 **Resolved**; I-8 routed to README; I-9 confirmed (no change); I-10, I-11 accepted as stated | all |

### 5. `README.md` (Integration Lead — frozen for this pass)

| # | Change | Resolves |
|---|---|---|
| IPR-README-01 | State that `reports/Tech Drona LMS reference platforms.md` is a byte-identical copy of `research/reference-platform-analysis.md`; `research/` is canonical; `research_notes/` holds raw notes and is not a deliverable | ROAD I-8 |
| IPR-README-02 | Document index: brief **v0.3**; add `docs/integration-pass-requests.md` and ADR-0014 | — |

### 6. `.env.example` (DevOps)

| # | Change | Resolves |
|---|---|---|
| IPR-ENV-01 | Section 6 header and `TD_CSRF_KEY` / `TD_CSRF_KEY_PREVIOUS` comments: `[REQUIRED: api, web]` → `[REQUIRED: web]` / `[OPTIONAL: web]`; header "(api; CSRF key also web)" → "(CSRF key: web only, ADR-0010)" | DEP I-14 |
| IPR-ENV-02 | Add `DATABASE_MAINTENANCE_URL=postgresql+psycopg://td_maintenance:local_maint_pw_REPLACE@localhost:5432/techdrona` with comment `[REQUIRED: worker with CELERY_QUEUES=maintenance ONLY] [SECRET] Role td_maintenance: EXECUTE on maint.* only` | DEP I-10 |
| IPR-ENV-03 | `WEBHOOK_TOLERANCE_SECONDS` comment: "applies only to providers that sign a timestamp (Cashfree); Razorpay events are never rejected by age — stale events are re-fetched (ADR-0006)" | API I-14 |
| IPR-ENV-04 | Error tracking: keep the SDK variable name `SENTRY_DSN` (Sentry SDK convention) but comment that it points to the self-hosted GlitchTip in ap-south-1 (ADR-0014); never a sentry.io DSN | DEP I-06 |

### 7. `docs/source-requirements-excerpt.md` (product owner's excerpt; Integration Lead keeps it)

| # | Change | Resolves |
|---|---|---|
| IPR-SRC-01 | Append a non-verbatim note after the Phase 9 list: "Implementation stage order (12 stages): defined in `docs/implementation-roadmap.md` §2 — 1 Discovery, 2 Product design, 3 Technical foundation, 4 Identity & permissions, 5 Core LMS, 6 Placement prep, 7 Account security & monitoring, 8 Commerce & college management, 9 Coding assessments, 10 Integration & hardening, 11 Pilot, 12 Production." | QA I-01 |
| IPR-SRC-02 | Under Section H add: "Report ids H1–H12 follow the order of this list (brief v0.3 §7)." | API I-15 |

### 8. Security Specialist documents (for the concurrent security pass; not edited here)

| # | File / location | Change | Resolves |
|---|---|---|---|
| IPR-SEC-01 | `account-security-and-risk-engine.md` §3.1 | `security.policy.write` → `policy.edit` (super_admin, Dual execute) and `policy.propose` (security_reviewer proposals) | API I-02 |
| IPR-SEC-02 | `account-security-and-risk-engine.md` §10 | Renumber dashboard views to H1–H12 in the verbatim Section H order; add views for H10 Active-session counts and H11 Daily/weekly/monthly learning activity; map H4 Repeated IP/device associations to report key `repeated-network-device-associations` | API I-15 |
| IPR-SEC-03 | `account-security-and-risk-engine.md` §5.5 / §12 | `devices.shared_scope` → `devices.shared_organization_id` (existing F-SEC-3) | API I-25 |
| IPR-SEC-04 | `security-threat-model.md` webhook rows | `POST /webhooks/{provider}` → `POST /api/v1/webhooks/{provider}` | DEP I-13 |
| IPR-SEC-05 | `privacy-and-data-retention.md` §10 processors | Do not add Sentry: error tracking is self-hosted in ap-south-1 (ADR-0014); add GlitchTip error events (90 days, scrubbed) to the retention registry | DEP I-06 |
| IPR-SEC-06 | `account-security-and-risk-engine.md` §7.3 / playback | Paths `POST /api/v1/media/playback-tokens`, `/media/playback-sessions/{id}/heartbeat`; code `409 playback_conflict` (confirm) | API I-04, I-05 |

### 9. `docs/analytics-event-schema.md` (Analytics Engineer)

| # | Change | Resolves |
|---|---|---|
| IPR-AN-01 | §5.1: remove `analytics.event.ingest`; ingest needs an authenticated session and writes only the principal's own events (role matrix v0.2 §2.7 note) | API I-03 |
| IPR-AN-02 | Exclude rows of `users.is_synthetic = true` from all aggregates, k-counts and the security feed | QA I-06; DEP I-15 |

---

**Request count: 62** (API 20, testing 8, deployment 11, roadmap 7, README 2, `.env.example` 4, source excerpt 2, security docs 6, analytics 2).
