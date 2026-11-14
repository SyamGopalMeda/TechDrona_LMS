# Tech Drona LMS — PostgreSQL Database Schema

> **Superseded (2026-11-14):** the LMS runs on Firebase (Vite React SPA + Cloud Functions + Firestore, project `billing-f4fe3`) — see `docs/firebase-migration-plan.md` and `docs/firebase/`. This PostgreSQL schema describes the legacy VM database, not the Firestore data model.

> **Single-company note (2026-11-06).** Tech Drona now runs as a single company ([ADR-0015](architecture-decisions/ADR-0015-single-company.md)); the college/B2B features described in this document (college portal and coordinators, institution contracts and seats, invitations and roster import, per-organization settings, trusted networks and lab devices, the "For colleges" page) are removed. Roles are Admin (`super_admin`), Trainer, Evaluator, Content manager and Student; finance, support, security and mentor duties belong to Admin. Batches are Tech Drona cohorts managed by Admin at `/admin/batches`; businesses use the corporate enquiry form at `/enquiries`. One `organizations` row (`org_type='internal'`, `COMPANY_ORG_ID`) remains as an internal tenancy key; college-only tables (contracts, seats, invitations, roster imports, trusted networks, lab devices, per-org settings) are dropped by the single-company migrations. Where this document conflicts, ADR-0015 and [`single-company/REMOVAL-PLAN.md`](single-company/REMOVAL-PLAN.md) §8 win.

| Field | Value |
|---|---|
| Owner | System Architect |
| Contract basis | `docs/blueprint-brief.md` **v0.4** §4 canonical entity names (all present below; 122 tables) + 10 implementation tables (§17.2) |
| Engine | PostgreSQL 16+ on AWS RDS (ap-south-1) |
| Status | **Partially implemented (v0.5, 2026-11-03)** — 113 of the 122 documented tables are created by Alembic revisions in `apps/api/migrations/versions/`, plus 10 tables added during implementation (123 migrated tables). The 9 tables marked Planned at v0.5 are all migrated as of v0.6 (2026-11-03, audit fix wave 3; §17.1, §17.8). Column-, constraint- and index-level edits made to match the migrations are tagged `-- v0.5` in the DDL; §17 is the as-migrated reference. **The migrations are the source of truth**; where this document and a migration disagree, the migration wins and this document is a bug. |
| Migration owner | Single Alembic history in `apps/api/migrations` (ADR-0009) |
| Companions | `docs/database-erd.md` (diagrams), `docs/system-architecture.md` (flows), `docs/contract-reconciliation.md` (decisions behind v0.2 changes) |
| Revision | v0.2 (2026-11-03): reconciliation edits by the Integration Lead — security tables per `account-security-and-risk-engine.md` §12, analytics tables per `analytics-event-schema.md` §4 and §10, 26 tables added from accepted proposals, §15 pending items resolved. v0.3 (2026-11-03): wave-2 consistency pass by the Integration Lead (`contract-reconciliation.md` §7) — `td_maintenance` role (§1.2), `auth_sessions.status` `pending_session_choice`, relaxed `permissions.permission_key` format, `users`/`organizations` `is_synthetic`, `products.product_kind` aligned with the PRD vocabulary, `refunds.approval_request_id`; no tables added (still 121). v0.4 (2026-11-03): security review pass applied by the Integration Lead (`consistency-pass-requests.md` CPR-SCH-01..15, log in `contract-reconciliation.md` §9) — versioned HMAC keys, remember-device token, idle hold, `session_network_observations` (122 tables), pending case decisions in `approval_requests`, HC/circuit-breaker columns, no minor evaluations, webhook re-fetch columns, 395-day R-SEC; see §16.1 v0.5 (2026-11-03, **Stage 10 schema sync**, documentation/integration writer): DDL in §2–§13 aligned with the Alembic migrations (≈150 column/constraint edits, 47 indexes added or corrected, all tagged `-- v0.5`); 9 tables marked Planned — not yet migrated; RLS deviations recorded (§14, §17.5); 10 implementation tables documented (§17.2); backlog §B closed (`docs/stage10-integration-backlog.md`). v0.6 (2026-11-03, audit fix wave 3): §1.2 `td_maintenance` lists the real `maint.*` functions; §1.3/§17.6 partitions created by `maint.ensure_partitions` (DB-04), not `pg_partman`; §17.1 regenerated from the 45 migration headers; `-- v0.6` DDL edits for `lessons` (catalog_0002), `tests.batch_id` (assessments_0003), `assignment_submissions.raw_score`/`late_penalty_pct` (learning_0002), `questions`/`question_versions` (placement_0004), commerce_0003 columns, support categories (support_0002), `export_jobs` and `erasure_ledger` as migrated; Planned tables of v0.5 are all migrated (§17.8). |

All tables below are in Brief v0.2 §4. Tags such as **(CCP-3)**, **(PRD CCP-04)**, **(SEC CCP-S1)**, **(AN CP-2)** record which accepted proposal introduced or reshaped a table (`docs/contract-reconciliation.md` §2). Security- and analytics-table columns are now **confirmed** by their domain owners' requirements (§15 lists the resolutions).

---

## 1. Conventions

### 1.1 Types and naming

* Tables snake_case plural (Brief §4); columns snake_case; FK columns `<entity>_id`.
* `id uuid PRIMARY KEY` — UUIDv7 generated by the application (`uuid_utils.uuid7()`, ADR-0012). No DB default is relied upon; `gen_random_uuid()` is permitted only in data backfills.
* Time: `timestamptz`, stored UTC. `created_at timestamptz NOT NULL DEFAULT now()`, `updated_at timestamptz NOT NULL DEFAULT now()` maintained by trigger `trg_set_updated_at` (BEFORE UPDATE) on every table that has `updated_at`.
* Money: `bigint` **paise** (`amount_paise`), currency `char(3)` default `'INR'`. Percentages `numeric(5,2)`.
* Enumerations: `text` + `CHECK (col IN (...))` (cheaper to evolve than PG enum types under Alembic).
* Case-insensitive identifiers: `citext` (email, coupon code, slugs where user-facing).
* Secrets: hashes as `bytea` (SHA-256 = 32 bytes, `CHECK (octet_length(x) = 32)`); encrypted values as `bytea` ciphertext with KMS-wrapped data keys (`*_encrypted`, `*_wrapped_key`).
* Soft delete (`deleted_at`) only where justified (users, courses, questions, organizations); everything else is hard state + status columns.
* `organization_id` is present on tenant-scoped tables (denormalised from parents where needed so RLS predicates are single-column).
* Extensions: `pgcrypto`, `citext`, `pg_partman`, `pg_stat_statements`, `btree_gist`.

### 1.2 Database roles

| Role | Purpose | Privileges |
|---|---|---|
| `td_owner` | Owns all objects; used only by Alembic migration task | DDL. Never used by the running app. |
| `td_app` | API + workers | DML on module tables (no UPDATE/DELETE on append-only tables); subject to RLS (FORCE). |
| `td_readonly` | Read replica dashboards/exports | SELECT; RLS still applies (sets same GUCs). |
| `td_audit_sealer` | Audit sealer (dedicated 1-task ECS service `audit-sealer`, v0.3) | INSERT on `audit_log`, SELECT/DELETE on `audit_outbox`. |
| `td_maintenance` | Partition maintenance and retention purge (Celery `maintenance` queue, ECS/compose `worker-maintenance`), v0.3; implemented v0.6 (`core_base_0002`, `support_0003`) | LOGIN via `DATABASE_MAINTENANCE_URL` (the jobs skip with a warning when it is unset; they never fall back to `td_app`). No table privileges and no DDL of its own: only `USAGE` on schema `maint` and `EXECUTE` on these `SECURITY DEFINER` functions owned by `td_owner` (`search_path = pg_catalog, maint, pg_temp`, revoked from `PUBLIC`; `td_app` has no `EXECUTE` on `maint.*`). They raise the transaction-local GUC `app.maint = on`, which admits `td_owner` through `p_maint` policies on the FORCE-RLS tables they touch. **`core_base_0002`:** `maint.ensure_partitions(parent regclass, months_ahead int = 3)` (premake monthly children for one of the 10 registered parents, §1.3); `maint.drop_expired_partitions(parent regclass)` (detach + drop children whose upper bound is older than the parent's `retention_policies` interval); `maint.purge_expired_rows(table text, batch int = 5000, max_batches int = 200)` (batched row deletes past the `retention_policies` interval; `security_signals` / `risk_evaluations` rows of a user with an open or legal-hold case are kept); entry points `maint.run_partition_maintenance(months_ahead int = 3)` and `maint.run_retention(batch, max_batches)`, each writing one `audit_outbox` summary. **`support_0003`** (security-owned, see §17.1): `maint.closed_case_attachments(limit int = 500)`, `maint.clear_closed_case_attachments(source text, ids uuid[])`, `maint.purge_closed_cases(batch int = 500)` (privacy D8; `app.modules.security.retention`). Jobs: `td.core.maint_partitions` (daily 21:30 UTC), `td.core.maint_retention` (daily 22:30 UTC), `td.security.purge_closed_cases` (Sundays 23:00 UTC). |

### 1.3 Partitioned tables (RANGE, monthly; v0.6: managed by `maint.ensure_partitions`, not `pg_partman`)

| Table | Partition key | Premake | Retention (drop partitions) |
|---|---|---|---|
| `login_attempts` | `attempted_at` | 3 | 395 days (R-SEC; partition dropped when its newest row is > 395 days old) |
| `session_network_observations` (v0.4) | `first_seen_at` | 3 | 395 days (R-SEC) |
| `security_signals` | `occurred_at` | 3 | 180 days (R-RISK) |
| `risk_evaluations` | `evaluated_at` | 3 | 180 days (R-RISK; rows referenced by an open/held case are copied into the case evidence before partition drop) |
| `attempt_events` | `occurred_at` | 3 | 24 months (R-ASSESS-EVT) |
| `analytics_events` | `event_ts` (from UUIDv7 `event_id`, AN CP-1) | 3 | 90 days (R-AN-RAW) |
| `activity_heartbeats` | `event_ts` (from UUIDv7 `event_id`, AN CP-1) | 3 | 35 days (R-AN-HB) |
| `engagement_intervals` | `started_at` | 3 | 13 months (R-AN-INT) |
| `playback_sessions` | `started_at` | 3 | 180 days (R-PLAY, privacy D11) |
| `audit_log` | `occurred_at` | 3 | 8 years (R-AUDIT) |

v0.6 (DB-04, `core_base_0002`): `pg_partman` is not used. Each parent was created with a `DEFAULT` partition only; the daily job `td.core.maint_partitions` calls `maint.run_partition_maintenance(3)`, which runs `maint.ensure_partitions(parent, 3)` for the 10 parents above and creates `<parent>_YYYYMM` children for the current month plus 3 ahead. Each new child gets the DEFAULT partition's ACL (privileges granted by default privileges to `td_app`/`td_readonly` are revoked first), ENABLE + FORCE RLS and copies of the DEFAULT partition's policies. If the DEFAULT partition already holds rows for that month they are moved under an ACCESS EXCLUSIVE lock (detach DEFAULT → create child → copy → delete from DEFAULT → re-attach); `audit_log` is immutable, so such a month is skipped and reported (`skipped_default_rows`). Expired children are dropped by `td.core.maint_retention` (`maint.drop_expired_partitions`).

Partitioned tables have composite PKs that include the partition key; other tables reference them by **soft reference** (uuid column without FK) because FKs into partitioned tables would need the partition key too.

### 1.4 Retention classes (Security Specialist's `privacy-and-data-retention.md` is authoritative; these are the architecture defaults)

| Class | Rule | Basis |
|---|---|---|
| R-ACCT | Life of account + 30 days grace, then erase/anonymise (DOB reduced to age-band flag) | privacy doc D1 (authoritative) |
| R-SEC | 1 year minimum (180 days hot); purge at **395 days** (`auth_sessions` ended rows, `login_attempts`, `session_network_observations`, operational logs) | DPDP Rules 6(e), 8(3); CERT-In 180 days [Verified]; privacy doc D5 |
| R-RISK | Risk inputs (signals, evaluations) 180 days unless referenced by an open or held case; cases, decisions, appeals 1 year after closure (3 years if disputed / legal hold); attachments 90 days after closure | privacy doc D7, D8 |
| R-DEV | `devices` 180 days after last use (unless referenced by an open case); `user_devices` trust expires after 90 days inactivity; removed rows 13 months (replacement quota + disputes) | privacy doc D6 |
| R-PLAY | 180 days | privacy doc D11 |
| R-PRIV | Rights requests and security incidents: 3 years after closure; `erasure_ledger`: 35 days beyond the oldest retained backup | privacy doc D16, D18, §7 |
| R-TOKEN | Delete 7 days after expiry/consumption | minimisation [Rec] |
| R-FIN | 8 years (covers 72 months from GST annual-return due date) | CGST s.36 [Verified] |
| R-AUDIT | Security-administration and access actions 3 years; financial actions 8 years (aligns with R-FIN); Object-Lock hash anchors 8 years | privacy doc D5, D17, §7.1 |
| R-CONSENT | Life of account + 3 years (limitation) | research §8 open Q12 [Rec] |
| R-LEARN | Life of account (learning record), anonymised on erasure | [Rec] |
| R-ASSESS-EVT | 24 months then drop | [Rec] |
| R-AN-RAW | `analytics_events` 90 days (partition drop) | Brief v0.2 §1; privacy doc D10 (reconciliation §3.1) |
| R-AN-HB | `activity_heartbeats` 35 days (72 h late window + 30-day recompute) | analytics doc §4.4 |
| R-AN-INT | `engagement_intervals` 13 months | analytics doc §4.4 |
| R-AN-AGG | Identifiable per-user aggregates 24 months after activity date or account deletion + 30 days, whichever first; then deleted (cohort rows remain) | analytics doc §4.4; privacy doc §7 |
| R-AN-COHORT | Non-identifying (k-rule) aggregates: life of platform / contract; B2B returned or deleted at contract end | analytics doc §4.4 |
| R-AN-FEED | `security_activity_feed_daily` 180 days; deleted within 24 h of `security_monitoring` withdrawal | analytics doc §6.5 |
| R-CONTENT | Indefinite (non-personal content/config) | — |
| R-ORG | Contract term + DPA return/delete window | research §8 [Rec] |

### 1.5 PII classification

| Class | Meaning | Examples |
|---|---|---|
| P0 | No personal data | content, config |
| P1 | Pseudonymous identifiers | `user_id`, `device_id`, session ids |
| P2 | Direct personal data | name, email, phone, college roll no. |
| P3 | Sensitive / high-impact | DOB, minor status, guardian data, IP/ASN, user-agent, risk signals, payment instrument metadata, GSTIN of individuals, free-text appeals |
| P4 | Secrets | password hashes, TOTP secrets, token hashes, webhook payload signatures |

---

## 2. Kernel: RLS functions, policy families, core tables

### 2.1 Context functions

```sql
CREATE SCHEMA IF NOT EXISTS app;

CREATE FUNCTION app.user_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;

CREATE FUNCTION app.org_ids() RETURNS uuid[] LANGUAGE sql STABLE AS
$$ SELECT coalesce(string_to_array(nullif(current_setting('app.org_ids', true), ''), ',')::uuid[], '{}') $$;

CREATE FUNCTION app.is_platform() RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT coalesce(current_setting('app.is_platform', true), 'off') = 'on' $$;

CREATE FUNCTION app.set_updated_at() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN NEW.updated_at := now(); RETURN NEW; END $$;
```

Set per transaction by `core.db` (system-architecture §6.5): `SELECT set_config('app.user_id', :uid, true), set_config('app.org_ids', :orgs, true), set_config('app.is_platform', :p, true), set_config('app.actor', :actor, true);`

### 2.2 Policy families

Every table with a family other than `NONE` has `ENABLE ROW LEVEL SECURITY` **and** `FORCE ROW LEVEL SECURITY`.

| Family | USING / WITH CHECK predicate | Used for |
|---|---|---|
| `T` (tenant) | `organization_id = ANY (app.org_ids()) OR app.is_platform()` | strictly org-owned rows (batches, contracts) |
| `TN` (tenant or global) | USING: `organization_id IS NULL OR organization_id = ANY (app.org_ids()) OR app.is_platform()`; WITH CHECK: `(organization_id IS NULL AND app.is_platform()) OR organization_id = ANY (app.org_ids()) OR app.is_platform()` | content that may be platform-owned (NULL org) or org-private |
| `U` (user + tenant) | `user_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) OR app.is_platform()` | learner records (attempts, enrolments, progress) |
| `O` (owner or platform) | `user_id = app.user_id() OR app.is_platform()` | personal/security/finance records with no college visibility |
| `NONE` | no RLS; access governed by permissions only | global reference data (roles, permissions, topics, companies), kernel tables |

Example (generated by a migration helper for each table):

```sql
ALTER TABLE test_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE test_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY p_u ON test_attempts FOR ALL TO td_app, td_readonly
  USING (user_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) OR app.is_platform())
  WITH CHECK (user_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) OR app.is_platform());
```

RLS is the tenant **boundary**; object-level authorization stays in the application (system-architecture §6.4). PK/unique/FK checks bypass RLS (research §8 [Verified]) — tenant-visible uniqueness is always scoped by `organization_id`.

### 2.3 Core tables (CCP-1, AN CP-8)

`outbox_events` carries every server-emitted domain event (e.g. `session.ended`, `account.restricted`, `consent.changed`, `age_tier.changed`, `attempt.submitted`); the relay dispatches to Celery consumers, including the analytics consumer that writes `analytics_events` rows with `source='server'` (AN CP-7). It is distinct from `audit_outbox` (§13), which feeds only the audit sealer.

```sql
-- Owner: core | RLS: NONE | Retention: dispatched rows deleted after 7 days | PII: P1 (payload may reference ids only; no raw PII by rule)
CREATE TABLE outbox_events (
  id              uuid PRIMARY KEY,
  event_type      text        NOT NULL,                       -- e.g. 'entitlement.granted'
  aggregate_type  text        NOT NULL,
  aggregate_id    uuid        NOT NULL,
  payload         jsonb       NOT NULL,
  organization_id uuid        NULL,
  occurred_at     timestamptz NOT NULL DEFAULT now(),
  dispatched_at   timestamptz NULL,
  attempts        int         NOT NULL DEFAULT 0,
  last_error      text        NULL
);
CREATE INDEX ix_outbox_pending ON outbox_events (occurred_at) WHERE dispatched_at IS NULL;

-- Owner: core | RLS: O | Retention: 24 h default, 7 days for money routes | PII: P1 (stored response bodies must not contain secrets; short TTL)
CREATE TABLE idempotency_keys (
  id              uuid PRIMARY KEY,
  user_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch); NULL for system callers
  route_key       text        NOT NULL,                       -- 'POST /api/v1/commerce/orders'
  idem_key text NOT NULL,  -- v0.5 as migrated
  request_hash bytea NOT NULL,  -- v0.5 as migrated
  status text NOT NULL,  -- v0.5 as migrated
  response_status int         NULL,
  response_body   jsonb       NULL,
  resource_id     uuid        NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  expires_at      timestamptz NOT NULL,
  -- v0.5: not in migration (replaced/removed): UNIQUE (user_id, route_key, idem_key)
  CONSTRAINT ck_idempotency_keys_idem_key_len CHECK (char_length(idem_key) BETWEEN 8 AND 128),  -- v0.5 added in migration
  CONSTRAINT ck_idempotency_keys_request_hash_len CHECK (octet_length(request_hash) = 32),  -- v0.5 added in migration
  CONSTRAINT ck_idempotency_keys_status CHECK (status IN ('in_progress','completed','failed')),  -- v0.5 added in migration
  CONSTRAINT uq_idempotency_keys_user_route_key UNIQUE NULLS NOT DISTINCT (user_id, route_key, idem_key)  -- v0.5 added in migration
);
CREATE INDEX ix_idem_expires ON idempotency_keys (expires_at);
```

---

## 3. Identity (`identity` module)

```sql
-- RLS: O (user_id = id) — implemented as policy on id | Retention: R-ACCT | PII: P2/P3
CREATE TABLE users (
  id                 uuid PRIMARY KEY,
  email              citext      NULL,
  email_verified_at  timestamptz NULL,
  phone_e164         text        NULL CHECK (phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
  phone_verified_at  timestamptz NULL,
  status             text        NOT NULL DEFAULT 'pending_verification'
                     CHECK (status IN ('pending_verification','pending_guardian_consent','active','deactivated','deleted')),
  -- Minor handling (PRD CCP-12, SEC CCP-S6): unverified age ⇒ minor. is_minor stays true until an age
  -- determination is recorded; the birthday job flips it on the 18th birthday (DOB in user_profiles).
  is_minor           boolean     NOT NULL DEFAULT true,
  age_verified_at    timestamptz NULL,                        -- when an age determination was recorded
  age_verification_method text   NULL CHECK (age_verification_method IN ('self_declared','roster','digilocker','guardian_attested')),
  privacy_tier       text        GENERATED ALWAYS AS (CASE WHEN is_minor THEN 'minor' ELSE 'adult' END) STORED,  -- AN DM-9; cached for ingest
  -- Security-maintained columns (SEC-DM-01). Only the security module writes restriction_level.
  restriction_level  smallint    NOT NULL DEFAULT 0 CHECK (restriction_level BETWEEN 0 AND 4),  -- cache of active account_restrictions
  sessions_valid_after timestamptz NULL,                      -- "revoke all": sessions created before this are invalid
  must_change_password boolean   NOT NULL DEFAULT false,      -- T-protect / breached password (TO-02)
  -- v0.3: synthetic-monitoring / test accounts. Excluded from analytics aggregates, risk scoring, invoices and k-counts.
  -- In production only the synthetic-monitoring provisioning job may set it; seed/demo data never reaches production.
  -- v0.4 (CPR-SCH-14, endorsed by the Security Specialist): the risk engine excludes synthetic accounts from SH and HC rules
  -- and security dashboards (RE §4.4).
  is_synthetic       boolean     NOT NULL DEFAULT false,
  account_origin     text        NOT NULL DEFAULT 'self_signup'
                     CHECK (account_origin IN ('self_signup','roster_import','staff_created','sso')),
  locale             text        NOT NULL DEFAULT 'en-IN',
  last_login_at      timestamptz NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  deleted_at         timestamptz NULL,
  CONSTRAINT ck_users_contact CHECK (email IS NOT NULL OR phone_e164 IS NOT NULL OR status = 'deleted'),
  CONSTRAINT ck_users_adult_verified CHECK (is_minor OR age_verified_at IS NOT NULL),
  CONSTRAINT ck_users_age_method CHECK ((age_verified_at IS NULL) = (age_verification_method IS NULL))
);
CREATE UNIQUE INDEX ux_users_email ON users (email) WHERE email IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX ux_users_phone ON users (phone_e164) WHERE phone_e164 IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_users_status ON users (status);
-- RLS policy on users: USING (id = app.user_id() OR app.is_platform() OR EXISTS org membership visibility via SECURITY DEFINER fn app.user_visible_in_orgs(id))

-- RLS: O (user_id) + org visibility fn | Retention: R-ACCT | PII: P2/P3 (DOB)
CREATE TABLE user_profiles (
  user_id             uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  full_name           text        NOT NULL CHECK (char_length(full_name) BETWEEN 1 AND 200),
  display_name        text        NULL,
  date_of_birth       date        NULL,                       -- required at self signup (age gate)
  college_name_text   text        NULL,                       -- free text for D2C users
  degree              text        NULL,
  branch              text        NULL,
  graduation_year     smallint    NULL CHECK (graduation_year BETWEEN 1990 AND 2100),
  city                text        NULL,
  state_code          char(2)     NULL,                       -- GST state code use for place of supply
  target_role         text        NULL,
  target_company_ids  uuid[]      NOT NULL DEFAULT '{}',
  target_date         date        NULL,
  avatar_s3_key       text        NULL,
  timezone            text        NOT NULL DEFAULT 'Asia/Kolkata',
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- RLS: O | Retention: R-ACCT | PII: P4
CREATE TABLE user_credentials (
  user_id              uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  password_hash        text        NOT NULL,                  -- PHC string, Argon2id m=19456,t=2,p=1
  hash_params_version  smallint    NOT NULL DEFAULT 1,        -- rehash on login if outdated
  password_set_at      timestamptz NOT NULL DEFAULT now(),
  breach_checked_at    timestamptz NULL,
  consecutive_failures int         NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
  hard_locked_at       timestamptz NULL,                      -- ≤100 consecutive failures (NIST)
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

-- RLS: O | Retention: R-ACCT (revoked factors 1 year) | PII: P4/P2 (sms phone)
CREATE TABLE mfa_factors (
  id                     uuid PRIMARY KEY,
  user_id                uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  factor_type            text        NOT NULL CHECK (factor_type IN ('webauthn','totp','sms','recovery_codes')),
  label                  text        NULL,
  totp_secret_encrypted  bytea       NULL,                    -- AES-GCM, KMS-wrapped key
  totp_wrapped_key       bytea       NULL,
  totp_last_used_step    bigint      NULL,                    -- replay guard (single use per 30 s step)
  webauthn_credential_id bytea       NULL,
  webauthn_public_key    bytea       NULL,
  webauthn_sign_count    bigint      NULL,
  webauthn_aaguid        uuid        NULL,
  webauthn_transports    text[]      NULL,
  webauthn_uv_required   boolean     NOT NULL DEFAULT true,
  sms_phone_e164         text        NULL,
  recovery_code_hashes   bytea[]     NULL,                    -- SHA-256 each, single-use (removed on use)
  is_primary             boolean     NOT NULL DEFAULT false,
  last_used_at           timestamptz NULL,
  created_at             timestamptz NOT NULL DEFAULT now(),
  revoked_at             timestamptz NULL,
  totp_confirmed_at timestamptz NULL,  -- v0.5 added in migration
  CONSTRAINT ck_mfa_payload CHECK (
    (factor_type = 'totp'     AND totp_secret_encrypted IS NOT NULL) OR
    (factor_type = 'webauthn' AND webauthn_credential_id IS NOT NULL AND webauthn_public_key IS NOT NULL) OR
    (factor_type = 'sms'      AND sms_phone_e164 IS NOT NULL) OR
    (factor_type = 'recovery_codes' AND recovery_code_hashes IS NOT NULL))
);
CREATE INDEX ix_mfa_user ON mfa_factors (user_id) WHERE revoked_at IS NULL;
CREATE UNIQUE INDEX ux_mfa_webauthn_cred ON mfa_factors (webauthn_credential_id) WHERE webauthn_credential_id IS NOT NULL;

-- RLS: NONE (pre-auth flows; accessed by hash only) | Retention: R-TOKEN | PII: P4/P3
-- RLS (as migrated, identity_0003): O (user_id = app.user_id() OR platform); pre-auth flows run in a named system context
CREATE TABLE verification_tokens (
  id                uuid PRIMARY KEY,
  user_id           uuid        NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose           text        NOT NULL CHECK (purpose IN ('email_verify','phone_verify','login_otp','new_device_otp',
                                                            'step_up_otp','contact_change','guardian_verify')),
  channel           text        NOT NULL CHECK (channel IN ('email','sms')),
  destination_hmac  bytea       NOT NULL CHECK (octet_length(destination_hmac) = 32),  -- HMAC(normalised email/phone)
  token_hash        bytea       NOT NULL CHECK (octet_length(token_hash) = 32),
  auth_session_id   uuid        NULL,                          -- binds step-up/new-device OTP to the pending session
  device_id         uuid        NULL,
  attempts          smallint    NOT NULL DEFAULT 0,
  max_attempts      smallint    NOT NULL DEFAULT 5,
  expires_at        timestamptz NOT NULL,                      -- OTP 10 min, email link 24 h
  consumed_at       timestamptz NULL,
  created_ip        inet        NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_vt_attempts CHECK (attempts <= max_attempts)
);
CREATE UNIQUE INDEX ux_vt_token_hash ON verification_tokens (token_hash);
CREATE INDEX ix_vt_user_purpose ON verification_tokens (user_id, purpose, created_at DESC);
CREATE INDEX ix_vt_dest_recent ON verification_tokens (destination_hmac, created_at DESC);  -- OTP quotas
CREATE INDEX ix_vt_expires ON verification_tokens (expires_at);

-- RLS: NONE (accessed by hash) | Retention: R-TOKEN | PII: P4
-- RLS (as migrated, identity_0003): O; pre-auth flows run in a named system context
CREATE TABLE password_reset_tokens (
  id             uuid PRIMARY KEY,
  user_id        uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash     bytea       NOT NULL CHECK (octet_length(token_hash) = 32),
  expires_at     timestamptz NOT NULL,                          -- 30 min
  consumed_at    timestamptz NULL,
  requested_ip   inet        NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_prt_hash ON password_reset_tokens (token_hash);
CREATE INDEX ix_prt_user ON password_reset_tokens (user_id, created_at DESC);

-- Append-only ledger (one row per grant/withdraw). RLS: O | Retention: R-CONSENT | PII: P3
CREATE TABLE consents (
  id                  uuid PRIMARY KEY,
  user_id             uuid        NOT NULL REFERENCES users(id),
  -- Canonical purposes (Brief v0.2 §1 Privacy; privacy doc §3.2 items A–H; AN CP-10)
  purpose             text        NOT NULL CHECK (purpose IN ('terms','privacy_notice',
                                     'core_service',               -- A (incl. basic learning-progress analytics)
                                     'security_monitoring',        -- B account-sharing detection (adults)
                                     'analytics_personalisation',  -- C recommendations / readiness scores
                                     'college_data_sharing',       -- D
                                     'device_fingerprint',         -- E (Phase 2, adults)
                                     'marketing_email','marketing_sms',  -- F
                                     'assessment_integrity',       -- G (per test; test_id in context)
                                     'analytics_product')),        -- H product/route analytics (adults, opt-in)
  action              text        NOT NULL CHECK (action IN ('granted','withdrawn')),
  context_ref         uuid        NULL,                         -- e.g. test_id for assessment_integrity
  notice_version      text        NOT NULL,                     -- itemised notice version shown
  notice_locale       text        NOT NULL DEFAULT 'en-IN',
  channel             text        NOT NULL CHECK (channel IN ('web','android','ios','roster_import','support')),
  guardian_consent_id uuid        NULL REFERENCES guardian_consents(id),
  organization_id     uuid        NULL REFERENCES organizations(id),   -- for college_data_sharing
  ip                  inet        NULL,
  user_agent          text        NULL,
  created_at          timestamptz NOT NULL DEFAULT now()
);  -- Minors may not grant B, C, E, F or H (privacy doc §4): enforced by the identity service (needs users.is_minor), not a CHECK
CREATE INDEX ix_consents_user_purpose ON consents (user_id, purpose, created_at DESC);
-- Current state view: consents_current = DISTINCT ON (user_id, purpose, organization_id) ORDER BY created_at DESC

-- RLS: O (child_user_id) | Retention: R-CONSENT (life of child account + limitation) | PII: P3
CREATE TABLE guardian_consents (
  id                   uuid PRIMARY KEY,
  child_user_id        uuid        NOT NULL REFERENCES users(id),
  guardian_user_id     uuid        NULL REFERENCES users(id),      -- if guardian holds an adult account (Rule 10)
  guardian_name        text        NOT NULL,
  guardian_email       citext      NULL,
  guardian_phone_e164  text        NULL,
  relationship         text        NOT NULL CHECK (relationship IN ('parent','legal_guardian')),
  verification_method text NOT NULL CHECK (verification_method IN ('existing_adult_account','digilocker_token', 'institution_attested','guardian_otp_declaration')),  -- v0.5 as migrated
  verification_ref     text        NULL,                            -- token reference, never ID documents
  evidence_hash        bytea       NULL,
  status               text        NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','verified','rejected','revoked','expired')),
  verified_at          timestamptz NULL,
  revoked_at           timestamptz NULL,
  expires_at           timestamptz NULL,                            -- child's 18th birthday
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_gc_contact CHECK (guardian_email IS NOT NULL OR guardian_phone_e164 IS NOT NULL OR guardian_user_id IS NOT NULL)
);
CREATE INDEX ix_gc_child ON guardian_consents (child_user_id, status);
```

---

## 4. Sessions and devices (`sessions` module)

Column set confirmed by the Security Specialist (`account-security-and-risk-engine.md` §1.2, §12; reconciliation SEC-DM-02..06). The session row covers every Section A field of the source requirements: user, session reference (hash only), login time (`created_at`), last active (`last_seen_at`), logout time (`ended_at`), session duration (derived: `coalesce(ended_at, last_seen_at) − created_at`), source IP (`ip_first`/`ip_last`), browser + version (`ua_family`, `ua_major`), OS + device category (`os_family`, `device_class`), privacy-conscious device identifier (`device_id` → HMAC'd cookie), approximate region (`geo_country`, `geo_region`; no city), auth method + verification status (`amr`, `aal`, `created_via`), status (`active`/`expired`/`revoked`/`blocked`), termination reason (`end_reason`).

```sql
-- RLS: NONE (device rows are not personal on their own; linked via user_devices) | Retention: R-DEV | PII: P1/P3
CREATE TABLE devices (
  id                   uuid PRIMARY KEY,
  device_key_hash      bytea       NOT NULL CHECK (octet_length(device_key_hash) = 32),  -- HMAC-SHA256(k_device_v{key_version}, raw id); re-hashed in place on lookup with an old version
  key_version          smallint    NOT NULL DEFAULT 1 CHECK (key_version >= 1),          -- v0.4 (CPR-SCH-01): HMAC key version (security.keys.k_device.current_version)
  client_type          text        NOT NULL CHECK (client_type IN ('web','android','ios')),
  ua_family            text        NULL,                         -- 'Chrome'
  os_family            text        NULL,                         -- 'Windows'
  device_class         text        NULL CHECK (device_class IN ('desktop','mobile','tablet','unknown')),
  fp_hash              bytea       NULL CHECK (fp_hash IS NULL OR octet_length(fp_hash) = 32),  -- Phase 2, adults, opt-in (consent E)
  fp_epoch             int         NULL,                         -- HMAC key epoch; rotated every 90 days
  shared_organization_id uuid      NULL REFERENCES organizations(id),   -- registered college lab device (security §5.5)
  shared_registered_by uuid        NULL REFERENCES users(id),
  shared_registered_at timestamptz NULL,
  label_hint           text        NULL,                         -- 'Chrome on Windows'
  first_seen_at        timestamptz NOT NULL DEFAULT now(),
  last_seen_at         timestamptz NOT NULL DEFAULT now(),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_dev_fp CHECK ((fp_hash IS NULL) = (fp_epoch IS NULL)),
  CONSTRAINT ck_dev_shared CHECK ((shared_organization_id IS NULL) = (shared_registered_by IS NULL))
);
CREATE UNIQUE INDEX ux_devices_key ON devices (device_key_hash);
CREATE INDEX ix_devices_fp ON devices (fp_hash, fp_epoch) WHERE fp_hash IS NOT NULL;
CREATE INDEX ix_devices_last_seen ON devices (last_seen_at);

-- RLS: O | Retention: R-DEV | PII: P1/P2 (label)
CREATE TABLE user_devices (
  id                 uuid PRIMARY KEY,
  user_id            uuid        NOT NULL REFERENCES users(id),
  device_id          uuid        NOT NULL REFERENCES devices(id),
  trust_status       text        NOT NULL DEFAULT 'pending_otp'
                     CHECK (trust_status IN ('pending_otp','trusted','removed','expired')),
  trusted_at         timestamptz NULL,
  owner_verified_at  timestamptz NULL,                           -- set only by sms_otp (registered mobile), passkey, totp or support; email_otp sets trusted_at only
  verification_method text       NULL CHECK (verification_method IN ('email_otp','sms_otp','passkey','totp','support')),
  counts_toward_cap  boolean     NOT NULL DEFAULT true,          -- false for registered lab devices of the user's org
  remember_until     timestamptz NULL,                           -- fixed at last full authentication; never slides (≤ 30 days, students, trusted only)
  remember_token_hash bytea      NULL CHECK (remember_token_hash IS NULL OR octet_length(remember_token_hash) = 32),  -- v0.4 (CPR-SCH-02): SHA-256 of __Host-td_remember; rotated on each re-issue
  remember_issued_at timestamptz NULL,                           -- v0.4: last remember-token issue/rotation
  user_label text NULL CHECK (user_label IS NULL OR char_length(user_label) <= 60),  -- v0.5 as migrated; user-provided name
  last_used_at       timestamptz NULL,
  removed_at         timestamptz NULL,
  removed_by         uuid        NULL REFERENCES users(id),
  removed_reason     text        NULL CHECK (removed_reason IN ('self_service_replacement','self_service_signout',
                                         'support_reset','security_action','unblock_reset','inactivity_expiry')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_ud_removed CHECK ((trust_status = 'removed') = (removed_at IS NOT NULL)),
  CONSTRAINT ck_ud_trusted CHECK (trust_status <> 'trusted' OR trusted_at IS NOT NULL),
  CONSTRAINT ck_ud_remember CHECK ((remember_token_hash IS NULL) = (remember_until IS NULL))
);
CREATE UNIQUE INDEX ux_ud_user_device ON user_devices (user_id, device_id) WHERE trust_status <> 'removed';
CREATE UNIQUE INDEX ux_ud_remember ON user_devices (remember_token_hash) WHERE remember_token_hash IS NOT NULL;   -- v0.4 (CPR-SCH-02)
CREATE INDEX ix_ud_trusted ON user_devices (user_id) WHERE trust_status = 'trusted' AND counts_toward_cap;   -- cap ≤ 3
CREATE INDEX ix_ud_replacements ON user_devices (user_id, removed_at)
  WHERE removed_reason = 'self_service_replacement';                                            -- ≤ 2 per 30 days
CREATE INDEX ix_ud_device ON user_devices (device_id);                                           -- device–account graph (SH-11, H4)
CREATE INDEX ix_ud_replacements ON user_devices (user_id, removed_at) WHERE removed_reason = 'self_service_replacement';  -- v0.5 added in migration

-- RLS: O | Retention: R-SEC | PII: P4 (hash) / P3 (ip, network, geo)
CREATE TABLE auth_sessions (
  id                   uuid PRIMARY KEY,                         -- internal id; never the token
  token_hash           bytea       NOT NULL CHECK (octet_length(token_hash) = 32),  -- SHA-256(raw token); raw never stored
  user_id              uuid        NOT NULL REFERENCES users(id),
  organization_id      uuid        NULL REFERENCES organizations(id),   -- active tenant context
  device_id            uuid        NULL REFERENCES devices(id),
  user_device_id       uuid        NULL REFERENCES user_devices(id),
  client_type          text        NOT NULL CHECK (client_type IN ('web','android','ios')),
  session_tier         text        NOT NULL CHECK (session_tier IN ('student','staff','privileged')),   -- timeouts per Brief §1
  scope                text        NOT NULL DEFAULT 'full' CHECK (scope IN ('full','restricted','status_only')),  -- UNB CCP-U3; record only; enforcement derives scope per request from restr:{uid}
  status               text        NOT NULL DEFAULT 'active'
                       CHECK (status IN ('pending_mfa','pending_device_otp','pending_session_choice','active','expired','revoked','blocked')),
                       -- v0.3: pending_session_choice = at the concurrent-session cap, waiting (≤ 5 min) for the user to pick a session to end
  aal                  smallint    NOT NULL DEFAULT 1 CHECK (aal BETWEEN 1 AND 3),
  amr                  text[]      NOT NULL DEFAULT '{}',        -- {'pwd','otp_sms'}, {'passkey'}
  created_via          text        NOT NULL CHECK (created_via IN ('password','otp_login','passkey','sso','recovery','unblock_reauth',
                          'remember_device')),          -- v0.4: remember_device = silent AAL1 re-issue on a top-level navigation
  auth_time            timestamptz NOT NULL DEFAULT now(),       -- last primary authentication
  last_step_up_at      timestamptz NULL,                         -- step-up windows 5/10/15 min (Brief §1)
  remember_device      boolean     NOT NULL DEFAULT false,
  restriction_level_at_issue smallint NOT NULL DEFAULT 0 CHECK (restriction_level_at_issue BETWEEN 0 AND 4),
  created_at           timestamptz NOT NULL DEFAULT now(),       -- login time
  last_seen_at         timestamptz NOT NULL DEFAULT now(),       -- written at most once per 60 s
  idle_expires_at      timestamptz NOT NULL,
  absolute_expires_at  timestamptz NOT NULL,
  idle_hold_until      timestamptz NULL,                         -- v0.4 (CPR-SCH-03): deadline_at + grace + 5 min while bound to an in-progress attempt
  ip_first             inet        NULL,                         -- full IP (security log, 1 year); UI shows /24 or /48
  ip_last              inet        NULL,
  net_cluster_first    text        NULL,                         -- 'AS55836:49.36.0.0/16'
  net_cluster_last     text        NULL,
  asn                  integer     NULL,
  network_type         text        NULL CHECK (network_type IN ('mobile','broadband','hosting','vpn_proxy','tor','education','unknown')),
  geo_country          char(2)     NULL,
  geo_region           text        NULL,                         -- state; never city
  ua_family            text        NULL,
  ua_major             text        NULL,
  os_family            text        NULL,
  device_class         text        NULL CHECK (device_class IN ('desktop','mobile','tablet','unknown')),
  ua_hash              bytea       NULL CHECK (ua_hash IS NULL OR octet_length(ua_hash) = 32),   -- raw UA never stored
  app_version          text        NULL,                         -- mobile apps only
  risk_evaluation_id   uuid        NULL,                         -- soft ref (partitioned table)
  ended_at             timestamptz NULL,                         -- logout / expiry / revocation time
  end_reason           text        NULL CHECK (end_reason IN ('user_logout','user_revoked_other','session_cap_evicted',
                          'idle_timeout','absolute_timeout','password_changed','mfa_changed','device_removed',
                          'device_mismatch','risk_L2_overflow','risk_L3','admin_L4','takeover_protect','admin_kill',
                          'unblock_reset','privilege_change','account_deleted','replaced_same_device')),
                          -- v0.4: replaced_same_device = re-login on the same device_id ends the old session before the cap check
  ended_by             uuid        NULL REFERENCES users(id),     -- NULL = user/system
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_as_expiry CHECK (idle_expires_at <= absolute_expires_at),
  CONSTRAINT ck_as_ended CHECK ((status IN ('expired','revoked','blocked')) = (ended_at IS NOT NULL AND end_reason IS NOT NULL)),
  CONSTRAINT ck_as_blocked CHECK (status <> 'blocked' OR end_reason IN ('risk_L3','admin_L4','takeover_protect','device_mismatch'))
);
CREATE UNIQUE INDEX ux_as_token ON auth_sessions (token_hash);
CREATE INDEX ix_as_user_active ON auth_sessions (user_id, created_at) WHERE status = 'active';   -- concurrency cap, oldest-first
CREATE INDEX ix_as_user_ended ON auth_sessions (user_id, ended_at DESC);                         -- device & login history (H2)
CREATE INDEX ix_as_expiry ON auth_sessions (absolute_expires_at) WHERE status = 'active';
CREATE INDEX ix_as_device ON auth_sessions (device_id, created_at DESC);

-- v0.4 (CPR-SCH-04). Owner sessions. Written on network-cluster change, ≤ 1 per 60 s per session.
-- Partitioned monthly on first_seen_at. RLS: O | Retention: R-SEC | PII: P3
CREATE TABLE session_network_observations (
  id                uuid        NOT NULL,
  first_seen_at     timestamptz NOT NULL DEFAULT now(),
  last_seen_at      timestamptz NOT NULL DEFAULT now(),
  auth_session_id   uuid        NOT NULL,                     -- soft ref to auth_sessions (partitioned table)
  user_id           uuid        NOT NULL,                     -- soft ref
  net_cluster       text        NOT NULL,                     -- 'AS55836:49.36.0.0/16'
  asn               integer     NULL,
  network_type      text        NULL CHECK (network_type IN ('mobile','broadband','hosting','vpn_proxy','tor','education','unknown')),
  geo_region        text        NULL,                         -- state; never city
  PRIMARY KEY (id, first_seen_at)
) PARTITION BY RANGE (first_seen_at);
CREATE INDEX ix_sno_session ON session_network_observations (auth_session_id, first_seen_at);
CREATE INDEX ix_sno_user_time ON session_network_observations (user_id, first_seen_at DESC);   -- separation class S0–S3 (RE §4.2.1)

-- Partitioned monthly on attempted_at. RLS: O (user_id NULL rows visible to platform only) | Retention: R-SEC | PII: P3
CREATE TABLE login_attempts (
  id                  uuid        NOT NULL,
  attempted_at        timestamptz NOT NULL DEFAULT now(),
  user_id             uuid        NULL,                        -- soft ref; NULL when identifier unknown
  identifier_hash     bytea       NOT NULL CHECK (octet_length(identifier_hash) = 32),   -- HMAC(k_login_v{key_version}, normalised email/phone); never re-hashed
  key_version         smallint    NOT NULL DEFAULT 1 CHECK (key_version >= 1),         -- v0.4 (CPR-SCH-01); lookups search across live versions
  method              text        NOT NULL CHECK (method IN ('password','otp','passkey','sso','recovery')),
  mfa_method          text        NULL CHECK (mfa_method IN ('totp','passkey','sms_otp','email_otp','recovery_code')),
  outcome             text        NOT NULL CHECK (outcome IN ('success','bad_credentials','unknown_identifier','throttled',
                          'mfa_required','mfa_failed','device_otp_required','restricted','locked','error')),
  failure_reason      text        NULL,
  pre_auth_blocked    boolean     NOT NULL DEFAULT false,      -- blocked before credential check; never counts toward lockout
  ip                  inet        NULL,
  asn                 integer     NULL,
  network_type        text        NULL CHECK (network_type IN ('mobile','broadband','hosting','vpn_proxy','tor','education','unknown')),
  geo_country         char(2)     NULL,
  geo_region          text        NULL,
  ua_hash             bytea       NULL CHECK (ua_hash IS NULL OR octet_length(ua_hash) = 32),
  device_id           uuid        NULL,
  auth_session_id     uuid        NULL,
  risk_evaluation_id  uuid        NULL,
  PRIMARY KEY (id, attempted_at)
) PARTITION BY RANGE (attempted_at);
CREATE INDEX ix_la_user_time ON login_attempts (user_id, attempted_at DESC);
CREATE INDEX ix_la_ident_time ON login_attempts (identifier_hash, attempted_at DESC);
CREATE INDEX ix_la_ip_time ON login_attempts (ip, attempted_at DESC);
CREATE INDEX ix_la_asn_time ON login_attempts (asn, attempted_at DESC) WHERE outcome <> 'success';   -- TO-05 stuffing source
CREATE INDEX brin_la_time ON login_attempts USING brin (attempted_at);

-- Partitioned monthly on started_at. RLS: O | Retention: R-PLAY | PII: P1/P3
CREATE TABLE playback_sessions (
  id                 uuid        NOT NULL,
  started_at         timestamptz NOT NULL DEFAULT now(),
  user_id            uuid        NOT NULL,                    -- soft refs (partitioned)
  auth_session_id    uuid        NOT NULL,
  device_id          uuid        NULL,
  lesson_asset_id    uuid        NOT NULL,
  provider           text        NOT NULL DEFAULT 'vdocipher',
  provider_otp_ref_hash bytea    NULL CHECK (provider_otp_ref_hash IS NULL OR octet_length(provider_otp_ref_hash) = 32),
  status             text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','ended')),
  otp_expires_at     timestamptz NOT NULL,                    -- 300 s default (playback.otp_ttl_seconds)
  last_heartbeat_at  timestamptz NOT NULL DEFAULT now(),
  last_position_s    integer     NULL,
  ended_at           timestamptz NULL,
  end_reason         text        NULL CHECK (end_reason IN ('stopped','stale','taken_over','revoked')),
  tab_id uuid NULL,  -- v0.5 added in migration
  PRIMARY KEY (id, started_at),
  CONSTRAINT ck_ps_end CHECK ((status = 'ended') = (ended_at IS NOT NULL AND end_reason IS NOT NULL))
) PARTITION BY RANGE (started_at);
CREATE INDEX ix_ps_user_active ON playback_sessions (user_id, last_heartbeat_at) WHERE status = 'active';
CREATE INDEX ix_ps_asset ON playback_sessions (lesson_asset_id, started_at);
CREATE INDEX ix_ps_user_started ON playback_sessions (user_id, started_at DESC);  -- v0.5 added in migration
CREATE INDEX ix_ps_id ON playback_sessions (id);  -- v0.5 added in migration
```

Stream cap is enforced transactionally with `pg_advisory_xact_lock(hashtext('play:'||user_id))` + count on `ix_ps_user_active` (system-architecture §12); a partial unique index is deliberately not used so the cap stays configurable. Watched time and coverage are analytics data (`video_watch_coverage`, §12), not stored here.

---

## 5. Security (`security` module)

Confirmed by the Security Specialist (`account-security-and-risk-engine.md` §4–§9, §12; `account-unblock-workflow.md` §2–§5). All security tables are **platform-scoped** for RLS (family `O`: the subject user may read their own rows through API projections; reviewers via `app.is_platform()` with a `security_reviewer` grant). Coordinators see only aggregate views. No sharing-family data exists for minors (CHECKs below + service rules).

```sql
-- Partitioned monthly on occurred_at. Append-only. RLS: O | Retention: R-RISK | PII: P3
CREATE TABLE security_signals (
  id               uuid        NOT NULL,
  occurred_at      timestamptz NOT NULL DEFAULT now(),
  user_id          uuid        NULL,                          -- soft ref (NULL for source-level abuse signals, e.g. TO-05 by ASN)
  family           text        NOT NULL CHECK (family IN ('sharing','takeover','cap','abuse','integrity')),
  rule_key         text        NOT NULL,                      -- 'SH-01', 'TO-04', 'cap.stream', 'AB-12'; families SH-*, TO-*, HC-*, AB-*, IN-*, cap.* (RE §4)
  rule_version     text        NULL,                          -- semver of the rule version that produced it
  category         text        NULL CHECK (category IN ('C','D','N')),   -- concurrency / device / network (sharing only)
  base_points      numeric(5,2) NOT NULL DEFAULT 0,
  multipliers      jsonb       NOT NULL DEFAULT '{}',          -- {"separation_class":"S3","separation":1.0,"trusted_network":1.0,"counted":true}
  evidence         jsonb       NOT NULL DEFAULT '{}',          -- ids, /16–/24 prefixes, state codes, counts only; never raw IPs
  source           text        NOT NULL CHECK (source IN ('login','heartbeat_batch','playback','attempt','nightly','system')),
  auth_session_id  uuid        NULL,
  device_id        uuid        NULL,
  is_minor_at_time boolean     NOT NULL,
  suppressed_by_decision_id uuid NULL,  -- v0.5 added in migration
  PRIMARY KEY (id, occurred_at),
  CONSTRAINT ck_sig_minor CHECK (family <> 'sharing' OR NOT is_minor_at_time),
  CONSTRAINT ck_sig_cat CHECK ((family = 'sharing') = (category IS NOT NULL) OR rule_key IN ('SH-M1','HC-01','HC-02'))  -- v0.5 as migrated
) PARTITION BY RANGE (occurred_at);
CREATE INDEX ix_sig_user_time ON security_signals (user_id, occurred_at DESC);
CREATE INDEX ix_sig_rule_time ON security_signals (rule_key, occurred_at DESC);

-- RLS: NONE (platform config) | Retention: R-CONTENT | PII: P0
CREATE TABLE risk_rules (
  id                 uuid PRIMARY KEY,
  key                text        NOT NULL UNIQUE,              -- 'SH-01'
  family             text        NOT NULL CHECK (family IN ('sharing','takeover','cap','abuse','integrity')),
  category           text        NULL CHECK (category IN ('C','D','N')),
  description        text        NOT NULL,                     -- reviewer-facing
  explanation_key    text        NOT NULL,                     -- student-facing copy key, e.g. 'sh01.overlap_two_devices'
  active_version_id  uuid        NULL,                          -- FK added after risk_rule_versions
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

-- Immutable once active. rule_id NULL = a ruleset version (one active per family). RLS: NONE | Retention: R-CONTENT | PII: P0
CREATE TABLE risk_rule_versions (
  id               uuid PRIMARY KEY,
  rule_id          uuid        NULL REFERENCES risk_rules(id),
  family           text        NOT NULL CHECK (family IN ('sharing','takeover','cap','abuse','integrity')),
  ruleset_version  text        NOT NULL,                       -- 'sharing-1.0.0'
  semver           text        NOT NULL CHECK (semver ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
  definition       jsonb       NOT NULL,                       -- {params, points, caps, multipliers, thresholds}
  status           text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','shadow','active','retired')),
  effective_from   timestamptz NULL,
  shadow_started_at timestamptz NULL,                          -- ≥ 14 days shadow before activation (service rule)
  shadow_report    jsonb       NULL,                           -- level-distribution diff, newly flagged users, FP history
  proposed_by      uuid        NOT NULL REFERENCES users(id),
  approved_by      uuid        NULL REFERENCES users(id),
  approved_at      timestamptz NULL,
  approval_request_id uuid     NULL REFERENCES approval_requests(id),
  status_changed_at timestamptz NULL,                          -- v0.4 (CPR-SCH-10)
  status_changed_by uuid       NULL REFERENCES users(id),      -- NULL = system
  status_change_reason text NULL CHECK (status_change_reason IN ('activation','rollback','retire','circuit_breaker','kill_switch','shadow_start')),  -- v0.5 as migrated
  created_at       timestamptz NOT NULL DEFAULT now(),
  -- v0.5: not in migration (replaced/removed): UNIQUE (rule_id, semver)
  CONSTRAINT ck_rrv_approval CHECK (status IN ('draft','shadow') OR status = 'retired' OR (approved_by IS NOT NULL AND approved_by <> proposed_by))  -- v0.5 as migrated
);
CREATE UNIQUE INDEX ux_rrv_active_ruleset ON risk_rule_versions (family) WHERE rule_id IS NULL AND status = 'active';
CREATE UNIQUE INDEX ux_rrv_rule_semver ON risk_rule_versions (coalesce(rule_id, '00000000-0000-0000-0000-000000000000'::uuid), family, semver);  -- v0.5 added in migration
CREATE UNIQUE INDEX ux_rrv_active_rule ON risk_rule_versions (rule_id) WHERE rule_id IS NOT NULL AND status = 'active';  -- v0.5 added in migration
ALTER TABLE risk_rules ADD CONSTRAINT fk_rr_active FOREIGN KEY (active_version_id) REFERENCES risk_rule_versions(id);
-- v0.4 (CPR-SCH-10) allowed status transitions: draft → shadow → active (Dual) → retired; active → shadow only with
-- status_change_reason 'circuit_breaker' (system, status_changed_by NULL) or 'kill_switch' (SEC-42, ratified within 24 h);
-- shadow → active again needs a new dual approval (RE §5.7).

-- Partitioned monthly on evaluated_at. Append-only. RLS: O | Retention: R-RISK | PII: P3
-- Written when the score changes by ≥ 5, the level changes, or at a synchronous decision point (security §9).
CREATE TABLE risk_evaluations (
  id                uuid        NOT NULL,
  evaluated_at      timestamptz NOT NULL DEFAULT now(),
  user_id           uuid        NOT NULL,                      -- soft ref
  organization_id   uuid        NULL,
  family            text        NOT NULL CHECK (family IN ('sharing','takeover')),
  mode              text        NOT NULL CHECK (mode IN ('enforce','shadow')),
  ruleset_version   text        NOT NULL,
  feed_version      text        NULL,                          -- analytics feed consumed, e.g. 'feed-1.0' (AN §6.5)
  trigger           text        NOT NULL CHECK (trigger IN ('login','playback','attempt','rebind','heartbeat_batch',
                                    'nightly','policy_shadow','manual_review','verification')),
  "window" jsonb NOT NULL,  -- v0.5 as migrated; {from, to, half_life_days}
  signals           jsonb       NOT NULL,                      -- [{signal_id, rule, rule_version, category, occurred_at, base_points, multipliers, decayed_points, evidence}]
  subtotals         jsonb       NOT NULL,                      -- {C, D, N, network_capped}
  repeat_multiplier numeric(3,2) NOT NULL DEFAULT 1.00,
  score             numeric(5,2) NOT NULL CHECK (score BETWEEN 0 AND 100),
  previous_score    numeric(5,2) NULL,
  level_before      smallint    NOT NULL CHECK (level_before BETWEEN 0 AND 4),
  level_after       smallint    NOT NULL CHECK (level_after BETWEEN 0 AND 4),
  gates             jsonb       NOT NULL DEFAULT '{}',          -- incl. hc_rule, separated_days, l2_reached
  action            text        NOT NULL CHECK (action IN ('none','notice_L1','require_otp_L2','restrict_L3','recommend_L4',
                                    'step_up','protect_lock','deescalate')),
  restriction_id    uuid        NULL,                          -- soft ref to account_restrictions
  case_id           uuid        NULL,                          -- soft ref to security_cases
  explanation_keys  text[]      NOT NULL DEFAULT '{}',
  auth_session_id   uuid        NULL,
  latency_ms        integer     NULL,
  is_minor_at_time  boolean     NOT NULL DEFAULT false,         -- v0.4 (CPR-SCH-08)
  PRIMARY KEY (id, evaluated_at),
  CONSTRAINT ck_re_no_auto_l4 CHECK (level_after <= 3 OR level_before = 4),  -- engine never moves a user into L4 (recommend_L4 only)
  CONSTRAINT ck_re_no_minor CHECK (NOT is_minor_at_time)        -- no risk_evaluations rows of any family for minors (RE §4.4)
) PARTITION BY RANGE (evaluated_at);
CREATE INDEX ix_re_user_time ON risk_evaluations (user_id, family, evaluated_at DESC);
CREATE INDEX ix_re_level ON risk_evaluations (evaluated_at, level_after) WHERE level_after >= 2;

-- RLS: O | Retention: R-RISK | PII: P3
CREATE TABLE account_restrictions (
  id                  uuid PRIMARY KEY,
  user_id             uuid        NOT NULL REFERENCES users(id),
  level               smallint    NOT NULL CHECK (level BETWEEN 1 AND 4),
  family              text        NOT NULL CHECK (family IN ('sharing','takeover')),
  scope               text        NOT NULL CHECK (scope IN ('learning_access','status_only','protect_lock')),
  source              text        NOT NULL CHECK (source IN ('engine','reviewer')),
  starts_at           timestamptz NOT NULL DEFAULT now(),
  ends_at             timestamptz NULL,                          -- NULL = until a case decision (L4)
  deferred_until      timestamptz NULL,                          -- L3 deferred until an in-progress attempt ends (max 3 h)
  evaluation_id       uuid        NULL,                          -- soft ref to risk_evaluations
  case_id             uuid        NULL REFERENCES security_cases(id),
  applied_by          uuid        NULL REFERENCES users(id),     -- NULL = engine
  ended_at            timestamptz NULL,
  ended_by            uuid        NULL REFERENCES users(id),
  end_reason text NULL CHECK (end_reason IN ('expired_reverified','case_decision','superseded','takeover_recovered','deescalated')),  -- v0.5 as migrated
  decision_id         uuid        NULL REFERENCES case_decisions(id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  hc_rule text NULL,  -- v0.5 added in migration
  ruleset_version text NULL,  -- v0.5 added in migration
  rule_keys text[] NOT NULL DEFAULT '{}',  -- v0.5 added in migration
  reverify_device_ids uuid[] NOT NULL DEFAULT '{}',  -- v0.5 added in migration
  lift_pending_at timestamptz NULL,  -- v0.5 added in migration
  CONSTRAINT ck_ar_l4_human CHECK (level < 4 OR (source = 'reviewer' AND applied_by IS NOT NULL)),      -- SEC CCP-S5
  CONSTRAINT ck_ar_ended CHECK ((ended_at IS NULL) = (end_reason IS NULL)),
  CONSTRAINT ck_ar_l4_lift CHECK (level < 4 OR ended_at IS NULL OR end_reason IN ('case_decision','superseded'))
);
CREATE UNIQUE INDEX ux_ar_active_family ON account_restrictions (user_id, family) WHERE ended_at IS NULL;   -- one active per family
CREATE INDEX ix_ar_ends ON account_restrictions (ends_at) WHERE ended_at IS NULL AND ends_at IS NOT NULL;
CREATE INDEX ix_ar_level_active ON account_restrictions (level, starts_at) WHERE ended_at IS NULL;          -- H5

-- RLS: O (subject reads own case summary through API projection) | Retention: R-RISK | PII: P3
CREATE TABLE security_cases (
  id                     uuid PRIMARY KEY,
  case_ref               text        NOT NULL UNIQUE CHECK (case_ref ~ '^SEC-[0-9]{4}-[0-9A-HJKMNP-TV-Z]{6}$'),  -- Crockford Base32, CSPRNG
  user_id                uuid        NOT NULL REFERENCES users(id),
  organization_id        uuid        NULL REFERENCES organizations(id),   -- context only; not tenant-visible
  family                 text        NOT NULL CHECK (family IN ('sharing','takeover')),
  level                  smallint    NOT NULL CHECK (level BETWEEN 0 AND 4),
  recommended_level      smallint    NULL CHECK (recommended_level BETWEEN 0 AND 4),
  priority               text        NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high','urgent')),
  status                 text        NOT NULL DEFAULT 'open' CHECK (status IN ('open','under_review','awaiting_user','escalated',
                                         'decided','closed')),
  opened_reason          text        NOT NULL CHECK (opened_reason IN ('engine_L3','engine_recommend_L4','takeover_recovery_failed',
                                         'unblock_request','support_escalation','manual','integrity_referral',
                                         'engine_hc_L3')),             -- v0.4: engine_hc_L3 = L3 applied by HC-01/HC-02 (RE §5.6)
  assignee_id            uuid        NULL REFERENCES users(id),
  is_high_risk           boolean     NOT NULL DEFAULT false,      -- unblock doc §5 rule 1 → second-person approval
  repeat_count           smallint    NOT NULL DEFAULT 0,
  sla_first_response_due timestamptz NULL,
  sla_decision_due       timestamptz NULL,
  first_response_at      timestamptz NULL,
  legal_hold             boolean     NOT NULL DEFAULT false,
  closed_at              timestamptz NULL,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  high_risk_reasons text[] NOT NULL DEFAULT '{}',  -- v0.5 added in migration
  hc_rule text NULL,  -- v0.5 added in migration
  sla_alerted_at timestamptz NULL,  -- v0.5 added in migration
  escalated_at timestamptz NULL,  -- v0.5 added in migration
  panel_views jsonb NOT NULL DEFAULT '{}',  -- v0.5 added in migration
  version integer NOT NULL DEFAULT 1,  -- v0.5 added in migration
  CONSTRAINT ck_sc_closed CHECK ((status = 'closed') = (closed_at IS NOT NULL))
);
CREATE INDEX ix_sc_queue ON security_cases (status, priority, sla_decision_due) WHERE status <> 'closed';   -- H1
CREATE INDEX ix_sc_user ON security_cases (user_id, created_at DESC);

-- RLS: O | Retention: R-RISK | PII: P3 (free text, attachments)
CREATE TABLE unblock_requests (
  id                      uuid PRIMARY KEY,
  reference               text        NOT NULL UNIQUE CHECK (reference ~ '^APL-[0-9]{4}-[0-9A-HJKMNP-TV-Z]{6}$'),
  case_id                 uuid        NOT NULL REFERENCES security_cases(id),
  user_id                 uuid        NOT NULL REFERENCES users(id),
  restriction_id          uuid        NULL REFERENCES account_restrictions(id),
  state                   text        NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','submitted','under_review',
                                          'info_requested','escalated','approved','rejected','closed')),   -- Brief v0.2 §1
  closure_reason          text        NULL CHECK (closure_reason IN ('completed','rejected_final','withdrawn','no_response','moot')),
  state_changed_at        timestamptz NOT NULL DEFAULT now(),
  what_happened           text[]      NOT NULL DEFAULT '{}',       -- multi-select codes (unblock doc §3)
  explanation             text        NULL CHECK (explanation IS NULL OR char_length(explanation) BETWEEN 30 AND 2000),  -- DLP-masked
  recognised_device_ids   uuid[]      NOT NULL DEFAULT '{}',
  unrecognised_device_ids uuid[]      NOT NULL DEFAULT '{}',       -- revoked on submit
  lab_location_text       text        NULL CHECK (lab_location_text IS NULL OR char_length(lab_location_text) <= 200),
  attachments             jsonb       NOT NULL DEFAULT '[]',       -- ≤ 2 S3 keys, ≤ 5 MB each, AV-scanned; never ID documents
  preferred_contact       text        NULL CHECK (preferred_contact IN ('in_app','email','sms')),
  declaration_at          timestamptz NULL,
  guardian_assisted       boolean     NOT NULL DEFAULT false,
  is_second_level_appeal  boolean     NOT NULL DEFAULT false,      -- the one appeal after rejection
  submitted_at            timestamptz NULL,
  assigned_to             uuid        NULL REFERENCES users(id),
  info_requested_due      timestamptz NULL,                       -- 7 days; SLA clock paused while info_requested
  escalated_at            timestamptz NULL,
  requires_second_approval boolean    NOT NULL DEFAULT false,
  decided_at              timestamptz NULL,
  idempotency_key         text        NULL,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  appeal_used boolean NOT NULL DEFAULT false,  -- v0.5 added in migration
  info_requested_at timestamptz NULL,  -- v0.5 added in migration
  rejected_by uuid NULL REFERENCES users(id),  -- v0.5 added in migration
  timeline jsonb NOT NULL DEFAULT '[]',  -- v0.5 added in migration
  version integer NOT NULL DEFAULT 1,  -- v0.5 added in migration
  CONSTRAINT ck_ur_submitted CHECK (state = 'draft' OR (submitted_at IS NOT NULL AND explanation IS NOT NULL AND declaration_at IS NOT NULL)),
  CONSTRAINT ck_ur_closed CHECK ((state = 'closed') = (closure_reason IS NOT NULL)),
  UNIQUE (user_id, idempotency_key)
);
CREATE UNIQUE INDEX ux_ur_open_per_case ON unblock_requests (case_id)
  WHERE state IN ('draft','submitted','under_review','info_requested','escalated');      -- 1 open request per case 🔒
CREATE INDEX ix_ur_user ON unblock_requests (user_id, submitted_at DESC);                 -- 3 per 30 days
CREATE INDEX ix_ur_queue ON unblock_requests (state, submitted_at) WHERE state IN ('submitted','under_review','info_requested','escalated');  -- H6, H7
CREATE UNIQUE INDEX ux_ur_open_per_case ON unblock_requests (case_id) WHERE state IN ('draft','submitted','under_review','info_requested','escalated');  -- v0.5 added in migration

-- Append-only. RLS: NONE on table; API restricts to security_reviewer + 'student' projection | Retention: R-RISK | PII: P3
CREATE TABLE case_notes (
  id                uuid PRIMARY KEY,
  case_id           uuid        NOT NULL REFERENCES security_cases(id),
  author_id         uuid        NULL REFERENCES users(id),     -- NULL = system note
  visibility        text        NOT NULL DEFAULT 'internal' CHECK (visibility IN ('internal','student')),
  body              text        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 4000),
  attachments       jsonb       NOT NULL DEFAULT '[]',         -- S3 keys
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_cn_case ON case_notes (case_id, created_at);

-- Append-only. RLS: O via case.user_id projection | Retention: R-RISK | PII: P3
-- Final decisions only; a decision awaiting a second approver lives in approval_requests (action_type security.case.decision)
-- and is inserted here on approval (UNB §5.1; v0.4 CPR-SCH-05).
CREATE TABLE case_decisions (
  id                     uuid PRIMARY KEY,
  case_id                uuid        NOT NULL REFERENCES security_cases(id),
  unblock_request_id     uuid        NULL REFERENCES unblock_requests(id),
  outcome                text        NOT NULL CHECK (outcome IN ('lift_false_positive','lift_with_warning','lift_conditions',
                                         'uphold','convert_L4','reduce_level')),
  resulting_level        smallint    NULL CHECK (resulting_level BETWEEN 0 AND 4),
  rationale              text        NOT NULL,
  student_summary        text        NULL CHECK (student_summary IS NULL OR char_length(student_summary) >= 50),
  conditions             jsonb       NOT NULL DEFAULT '{}',      -- e.g. per-user exception → policy_settings row (scope 'user')
  extension_days         smallint    NOT NULL DEFAULT 0 CHECK (extension_days >= 0),   -- false-positive subscription extension
  decided_by             uuid        NOT NULL REFERENCES users(id),
  requires_second_approval boolean   NOT NULL DEFAULT false,
  approved_by            uuid        NULL REFERENCES users(id),
  approved_at            timestamptz NULL,
  approval_request_id    uuid        NULL REFERENCES approval_requests(id),   -- v0.4: the approved security.case.decision request
  created_at             timestamptz NOT NULL DEFAULT now(),
  false_positive_rule_keys text[] NOT NULL DEFAULT '{}',  -- v0.5 added in migration
  CONSTRAINT ck_cd_approval_link CHECK (NOT requires_second_approval OR approval_request_id IS NOT NULL),
  CONSTRAINT ck_cd_second CHECK (approved_by IS NULL OR approved_by <> decided_by),                    -- UNB CCP-U2
  CONSTRAINT ck_cd_needs CHECK (NOT requires_second_approval OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)),
  CONSTRAINT ck_cd_reject_summary CHECK (outcome <> 'uphold' OR student_summary IS NOT NULL)
);
CREATE INDEX ix_cd_case ON case_decisions (case_id, created_at);
CREATE INDEX ix_cd_outcome ON case_decisions (outcome, created_at);                       -- H8 false-positive rate, H9 repeats

-- (SEC CCP-S1) Coordinator proposes, security_reviewer verifies. RLS: T (org sees its own rows) | Retention: R-ORG | PII: P0/P1
CREATE TABLE org_trusted_networks (
  id               uuid PRIMARY KEY,
  organization_id  uuid        NOT NULL REFERENCES organizations(id),
  cidr             cidr        NULL CHECK (cidr IS NULL OR (family(cidr) = 4 AND masklen(cidr) >= 16) OR family(cidr) = 6),
  asn              integer     NULL,
  status           text        NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','verified','rejected','expired')),
  proposed_by      uuid        NOT NULL REFERENCES users(id),
  verified_by      uuid        NULL REFERENCES users(id),
  verified_at      timestamptz NULL,
  evidence_ref     text        NULL,                            -- WHOIS / college IT letter (S3 key)
  expires_at       timestamptz NULL,                            -- reviewed every 12 months
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  decision_note text NULL,  -- v0.5 added in migration
  CONSTRAINT ck_otn_target CHECK (num_nonnulls(cidr, asn) = 1),
  CONSTRAINT ck_otn_verify CHECK (status <> 'verified' OR (verified_by IS NOT NULL AND verified_by <> proposed_by))
);
CREATE INDEX ix_otn_org ON org_trusted_networks (organization_id) WHERE status = 'verified';
CREATE INDEX gist_otn_cidr ON org_trusted_networks USING gist (cidr inet_ops) WHERE status = 'verified';

-- (SEC CCP-S2) Breach register with dual clocks (CERT-In 6 h; DPB). RLS: NONE (security lead / DPO / super_admin only via API) | Retention: R-PRIV | PII: P2/P3
CREATE TABLE security_incidents (
  id                   uuid PRIMARY KEY,
  incident_ref text NOT NULL UNIQUE CHECK (incident_ref ~ '^INC-[0-9]{4}-[0-9A-HJKMNP-TV-Z]{6}$'),  -- v0.5 as migrated; 'INC-YYMM-XXXXXX'
  title                text        NOT NULL,
  severity             text        NOT NULL CHECK (severity IN ('low','medium','high','critical')),
  status               text        NOT NULL DEFAULT 'detected' CHECK (status IN ('detected','triaged','contained','notified',
                                       'remediated','closed')),
  detected_at          timestamptz NOT NULL,
  is_personal_data_breach boolean  NOT NULL DEFAULT false,
  certin_reportable    boolean     NOT NULL DEFAULT false,
  certin_due_at        timestamptz NULL,                          -- detected_at + 6 h
  certin_reported_at   timestamptz NULL,
  dpb_intimation_due_at timestamptz NULL,
  dpb_intimated_at     timestamptz NULL,
  dpb_report_due_at    timestamptz NULL,                          -- detailed report (72 h, Rule 7)
  dpb_reported_at      timestamptz NULL,
  principals_notified_at timestamptz NULL,
  affected_data        jsonb       NOT NULL DEFAULT '{}',          -- categories (D1–D18), counts, orgs
  timeline             jsonb       NOT NULL DEFAULT '[]',
  owner_id             uuid        NOT NULL REFERENCES users(id),
  legal_hold           boolean     NOT NULL DEFAULT true,
  closed_at            timestamptz NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1,  -- v0.5 added in migration
  CONSTRAINT ck_si_certin CHECK (NOT certin_reportable OR certin_due_at IS NOT NULL)
);
CREATE INDEX ix_si_open ON security_incidents (status, certin_due_at) WHERE status <> 'closed';
```

Per-user security exceptions (security §5.5) are **not** a table: they are `policy_settings` rows with `scope_type = 'user'`, `expires_at` ≤ 180 days and a required `case_decision_id` (SEC-DM-19, §13). `policy_settings` itself is owned by `admin` (CCP-7).

---

## 6. Organizations and RBAC (`orgs`, `rbac` modules)

```sql
-- RLS: T on id (org members see their org; platform sees all) | Retention: R-ORG | PII: P2 (contact person) / P0
CREATE TABLE organizations (
  id                 uuid PRIMARY KEY,
  name text NOT NULL CHECK (char_length(name) BETWEEN 2 AND 200),  -- v0.5 as migrated
  slug citext NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),  -- v0.5 as migrated
  org_type           text        NOT NULL CHECK (org_type IN ('college','university','company','training_partner','internal')),
  status             text        NOT NULL DEFAULT 'active' CHECK (status IN ('prospect','active','suspended','archived')),
  data_role          text        NOT NULL DEFAULT 'tech_drona_processor'
                     CHECK (data_role IN ('tech_drona_processor','independent_fiduciaries')),   -- DPA posture
  gstin              text        NULL CHECK (gstin ~ '^[0-9]{2}[A-Z0-9]{13}$'),
  billing_name       text        NULL,
  billing_address    jsonb       NULL,
  state_code         char(2)     NULL,
  contact_name       text        NULL,
  contact_email      citext      NULL,
  contact_phone_e164 text        NULL,
  settings           jsonb       NOT NULL DEFAULT '{}',        -- e.g. require_mfa_students
  is_synthetic       boolean     NOT NULL DEFAULT false,       -- v0.3: synthetic-monitoring org (see users.is_synthetic)
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  deleted_at         timestamptz NULL
);
-- policy: USING (id = ANY (app.org_ids()) OR app.is_platform())

-- RLS: T | Retention: R-ORG | PII: P2 (roll number)
CREATE TABLE org_memberships (
  id               uuid PRIMARY KEY,
  organization_id  uuid        NOT NULL REFERENCES organizations(id),
  user_id          uuid        NOT NULL REFERENCES users(id),
  member_type      text        NOT NULL CHECK (member_type IN ('student','staff')),
  external_ref     text        NULL,                           -- roll / registration number
  status           text        NOT NULL DEFAULT 'active' CHECK (status IN ('invited','active','graduated','left','removed')),
  joined_at        timestamptz NULL,
  left_at          timestamptz NULL,
  invited_by       uuid        NULL REFERENCES users(id),
  source           text        NOT NULL DEFAULT 'roster_import' CHECK (source IN ('roster_import','invite','self_join_code','staff')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  -- v0.5: not in migration (replaced/removed): UNIQUE (organization_id, user_id)
  CONSTRAINT uq_org_memberships_org_user UNIQUE (organization_id, user_id)  -- v0.5 added in migration
);
CREATE UNIQUE INDEX ux_om_external_ref ON org_memberships (organization_id, external_ref) WHERE external_ref IS NOT NULL;
CREATE INDEX ix_om_user ON org_memberships (user_id) WHERE status = 'active';

-- RLS: T | Retention: R-ORG | PII: P0
CREATE TABLE batches (
  id                 uuid PRIMARY KEY,
  organization_id    uuid        NOT NULL REFERENCES organizations(id),
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),  -- v0.5 as migrated
  code text NOT NULL CHECK (char_length(code) BETWEEN 1 AND 64),  -- v0.5 as migrated
  academic_year      text        NULL,                         -- '2026-27'
  graduation_year    smallint    NULL,
  starts_on          date        NULL,
  ends_on            date        NULL,
  status             text        NOT NULL DEFAULT 'active' CHECK (status IN ('planned','active','completed','archived')),
  created_by         uuid        NOT NULL REFERENCES users(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  -- v0.5: not in migration (replaced/removed): UNIQUE (organization_id, code)
  CONSTRAINT ck_batch_dates CHECK (ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on),
  CONSTRAINT uq_batches_org_code UNIQUE (organization_id, code)  -- v0.5 added in migration
);
CREATE INDEX ix_batches_org ON batches (organization_id);  -- v0.5 added in migration

-- RLS: T | Retention: R-ORG | PII: P1
CREATE TABLE batch_members (
  id               uuid PRIMARY KEY,
  batch_id         uuid        NOT NULL REFERENCES batches(id),
  organization_id  uuid        NOT NULL REFERENCES organizations(id),   -- denormalised for RLS
  user_id          uuid        NOT NULL REFERENCES users(id),
  member_role      text        NOT NULL CHECK (member_role IN ('student','trainer','mentor')),
  status           text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','removed','completed')),
  added_by         uuid        NULL REFERENCES users(id),
  added_at         timestamptz NOT NULL DEFAULT now(),
  removed_at       timestamptz NULL,
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_bm_live ON batch_members (batch_id, user_id, member_role) WHERE status = 'active';
CREATE INDEX ix_bm_user ON batch_members (user_id) WHERE status = 'active';

-- (PRD CCP-04) Idempotent roster upload (FR-ORG-010): re-uploading the same file (same file_sha256) returns the same job.
-- RLS: T | Retention: R-ORG (row results purged 90 days after commit) | PII: P2 (row_results may echo names/emails)
CREATE TABLE bulk_import_jobs (
  id                uuid PRIMARY KEY,
  organization_id   uuid        NOT NULL REFERENCES organizations(id),
  batch_id          uuid        NULL REFERENCES batches(id),
  uploaded_by       uuid        NOT NULL REFERENCES users(id),
  file_s3_key       text        NOT NULL,
  file_sha256       bytea       NOT NULL CHECK (octet_length(file_sha256) = 32),
  status            text        NOT NULL DEFAULT 'validating' CHECK (status IN ('validating','preview_ready','committing',
                                    'committed','failed','cancelled')),
  total_rows        int         NULL CHECK (total_rows BETWEEN 0 AND 5000),
  valid_rows        int         NULL,
  error_rows        int         NULL,
  row_results       jsonb       NOT NULL DEFAULT '[]',            -- [{row, status, error_code, user_id}]
  committed_at      timestamptz NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  -- v0.5: not in migration (replaced/removed): UNIQUE (organization_id, file_sha256)
  CONSTRAINT uq_bulk_import_jobs_org_sha UNIQUE (organization_id, file_sha256)  -- v0.5 added in migration
);

-- (PRD CCP-04) Single-use invite links (FR-ORG-011): valid 14 days, ≤ 3 resends. Token stored as SHA-256 only.
-- RLS: T | Retention: R-ORG (accepted/expired rows purged after 1 year) | PII: P2
CREATE TABLE org_invitations (
  id                 uuid PRIMARY KEY,
  organization_id    uuid        NOT NULL REFERENCES organizations(id),
  batch_id           uuid        NULL REFERENCES batches(id),
  bulk_import_job_id uuid        NULL REFERENCES bulk_import_jobs(id),
  email              citext      NULL,
  phone_e164         text        NULL CHECK (phone_e164 IS NULL OR phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
  full_name          text        NULL,
  external_ref       text        NULL,                            -- roll number
  member_type        text        NOT NULL DEFAULT 'student' CHECK (member_type IN ('student','staff')),
  token_hash         bytea       NOT NULL CHECK (octet_length(token_hash) = 32),
  status             text        NOT NULL DEFAULT 'sent' CHECK (status IN ('pending','sent','opened','accepted','expired','bounced','revoked')),
  resend_count       smallint    NOT NULL DEFAULT 0 CHECK (resend_count BETWEEN 0 AND 3),
  expires_at         timestamptz NOT NULL,
  accepted_at        timestamptz NULL,
  accepted_user_id   uuid        NULL REFERENCES users(id),
  invited_by         uuid        NOT NULL REFERENCES users(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_oi_contact CHECK (email IS NOT NULL OR phone_e164 IS NOT NULL)
);
CREATE UNIQUE INDEX ux_oi_token ON org_invitations (token_hash);
CREATE INDEX ix_oi_org_status ON org_invitations (organization_id, status);

-- RLS: NONE | Retention: R-CONTENT | PII: P0
CREATE TABLE roles (
  id            uuid PRIMARY KEY,
  role_key      text        NOT NULL UNIQUE CHECK (role_key IN ('student','college_coordinator','trainer','content_manager',
                   'placement_mentor','support_agent','security_reviewer','finance_admin','super_admin')),
  name          text        NOT NULL,
  session_tier  text        NOT NULL CHECK (session_tier IN ('student','staff','privileged')),
  mfa_required  boolean     NOT NULL,
  allowed_scope_types text[] NOT NULL,                         -- e.g. {'organization','batch'}
  is_system     boolean     NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- RLS: NONE | Retention: R-CONTENT | PII: P0
CREATE TABLE permissions (
  id              uuid PRIMARY KEY,
  permission_key  text        NOT NULL UNIQUE CHECK (permission_key ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$'),  -- v0.3: 2–3 segments (resource.action or resource.sub.action); keys = role-permission-matrix.md §2
  module          text        NOT NULL,                         -- owning backend module (brief §2); not derived from the key prefix
  description     text        NOT NULL,
  is_sensitive    boolean     NOT NULL DEFAULT false,           -- requires step-up MFA freshness
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- RLS: NONE | Retention: R-CONTENT | PII: P0
CREATE TABLE role_permissions (
  role_id        uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_id  uuid NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (role_id, permission_id)
);

-- RLS: custom — USING (user_id = app.user_id() OR organization_id = ANY (app.org_ids()) OR app.is_platform())
-- Retention: R-AUDIT for revoked grants (kept for accountability) | PII: P1
CREATE TABLE role_grants (
  id               uuid PRIMARY KEY,
  user_id          uuid        NOT NULL REFERENCES users(id),
  role_id          uuid        NOT NULL REFERENCES roles(id),
  scope_type       text        NOT NULL CHECK (scope_type IN ('platform','organization','batch','course')),
  scope_id         uuid        NULL,                            -- org/batch/course id; NULL for platform
  organization_id  uuid        NULL REFERENCES organizations(id),   -- resolved owning org (NULL for platform/global course)
  granted_by       uuid        NOT NULL REFERENCES users(id),
  granted_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NULL,
  revoked_at       timestamptz NULL,
  revoked_by       uuid        NULL REFERENCES users(id),
  reason           text        NULL,
  CONSTRAINT ck_rg_scope CHECK ((scope_type = 'platform') = (scope_id IS NULL)),
  CONSTRAINT ck_rg_self CHECK (granted_by <> user_id OR scope_type <> 'platform')
);
CREATE UNIQUE INDEX ux_rg_live ON role_grants (user_id, role_id, scope_type, coalesce(scope_id, '00000000-0000-0000-0000-000000000000'::uuid))
  WHERE revoked_at IS NULL;
CREATE INDEX ix_rg_user ON role_grants (user_id) WHERE revoked_at IS NULL;
CREATE INDEX ix_rg_scope ON role_grants (scope_type, scope_id) WHERE revoked_at IS NULL;
CREATE UNIQUE INDEX ux_rg_live ON role_grants (user_id, role_id, scope_type, coalesce(scope_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE revoked_at IS NULL;  -- v0.5 added in migration
```

---

## 7. Catalog and learning (`catalog`, `learning` modules)

```sql
-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE courses (
  id                  uuid PRIMARY KEY,
  organization_id     uuid        NULL REFERENCES organizations(id),   -- NULL = platform catalogue
  slug citext NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,118}$'),  -- v0.5 as migrated
  title               text        NOT NULL,
  course_kind text NOT NULL DEFAULT 'self_paced' CHECK (course_kind IN ('self_paced','cohort','crash_course','company_prep','bootcamp')),  -- v0.5 as migrated
  visibility          text        NOT NULL DEFAULT 'private' CHECK (visibility IN ('public','unlisted','private','org_only')),
  status              text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
  current_version_id  uuid        NULL,                                 -- FK added below
  primary_topic_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  completeness_pct numeric(5,2) NOT NULL DEFAULT 0 CHECK (completeness_pct BETWEEN 0 AND 100),  -- v0.5 as migrated; public content-completeness indicator
  created_by          uuid        NOT NULL REFERENCES users(id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  deleted_at          timestamptz NULL,
  is_free boolean NOT NULL DEFAULT false  -- v0.5 added in migration
);
CREATE UNIQUE INDEX ux_courses_slug ON courses (coalesce(organization_id, '00000000-0000-0000-0000-000000000000'::uuid), slug)
  WHERE deleted_at IS NULL;
CREATE INDEX ix_courses_public ON courses (status, visibility) WHERE deleted_at IS NULL;  -- v0.5 added in migration
CREATE INDEX ix_courses_org ON courses (organization_id) WHERE organization_id IS NOT NULL;  -- v0.5 added in migration

-- Immutable once published. RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE course_versions (
  id               uuid PRIMARY KEY,
  course_id        uuid        NOT NULL REFERENCES courses(id),
  organization_id  uuid        NULL REFERENCES organizations(id),
  version_no       int         NOT NULL CHECK (version_no >= 1),
  title            text        NOT NULL,
  summary          text        NULL,
  description_md   text        NULL,
  outcomes         text[]      NOT NULL DEFAULT '{}',
  status           text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','in_review','published','superseded')),
  published_at     timestamptz NULL,
  published_by     uuid        NULL REFERENCES users(id),
  changelog        text        NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  level text NULL CHECK (level IN ('beginner','intermediate','advanced')),  -- v0.5 added in migration
  language text NOT NULL DEFAULT 'en',  -- v0.5 added in migration
  category text NULL CHECK (category IN ('aptitude','programming','dsa','cs_fundamentals','company','interview','other')),  -- v0.5 added in migration
  tags text[] NOT NULL DEFAULT '{}',  -- v0.5 added in migration
  certificate_rule jsonb NULL,  -- v0.5 added in migration
  completeness_plan jsonb NULL,  -- v0.5 added in migration
  change_type text NULL CHECK (change_type IN ('minor','major')),  -- v0.5 added in migration
  created_by uuid NOT NULL REFERENCES users(id),  -- v0.5 added in migration
  submitted_by uuid NULL REFERENCES users(id),  -- v0.5 added in migration
  submitted_at timestamptz NULL,  -- v0.5 added in migration
  UNIQUE (course_id, version_no),
  CONSTRAINT ck_cv_published CHECK (status NOT IN ('published','superseded') OR (published_at IS NOT NULL AND published_by IS NOT NULL))  -- v0.5 added in migration
);
CREATE UNIQUE INDEX ux_cv_one_draft ON course_versions (course_id) WHERE status IN ('draft','in_review');  -- v0.5 added in migration
ALTER TABLE courses ADD CONSTRAINT fk_courses_current_version FOREIGN KEY (current_version_id) REFERENCES course_versions(id);

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE course_modules (
  id                 uuid PRIMARY KEY,
  course_version_id  uuid        NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  organization_id    uuid        NULL REFERENCES organizations(id),
  module_key         uuid        NOT NULL,                          -- stable across versions
  title              text        NOT NULL,
  position           int         NOT NULL CHECK (position >= 0),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  -- v0.5: not in migration (replaced/removed): UNIQUE (course_version_id, position)
  -- v0.5: not in migration (replaced/removed): UNIQUE (course_version_id, module_key)
  CONSTRAINT uq_cm_position UNIQUE (course_version_id, position) DEFERRABLE INITIALLY DEFERRED,  -- v0.5 added in migration
  CONSTRAINT uq_cm_key UNIQUE (course_version_id, module_key)  -- v0.5 added in migration
);

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE lessons (
  id                 uuid PRIMARY KEY,
  course_module_id   uuid        NOT NULL REFERENCES course_modules(id) ON DELETE CASCADE,
  course_version_id  uuid        NOT NULL REFERENCES course_versions(id),   -- denormalised
  organization_id    uuid        NULL REFERENCES organizations(id),
  lesson_key         uuid        NOT NULL,                          -- stable across versions (CCP-11)
  title              text        NOT NULL,
  lesson_type        text        NOT NULL CHECK (lesson_type IN ('video','article','pdf','practice_set','quiz','coding','assignment','live_link')),  -- v0.6 catalog_0002: + pdf, practice_set (FR-CAT-001)
  position           int         NOT NULL CHECK (position >= 0),
  is_required        boolean     NOT NULL DEFAULT true,
  is_free_preview    boolean     NOT NULL DEFAULT false,
  duration_seconds   int         NULL CHECK (duration_seconds >= 0),
  article_body       jsonb       NULL,                             -- rich-text doc (lesson_type='article')
  test_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  coding_problem_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  assignment_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  live_url text NULL CHECK (live_url IS NULL OR live_url ~ '^https://'),  -- v0.5 as migrated
  est_reading_minutes smallint   NULL CHECK (est_reading_minutes >= 0),  -- article MLAT cap (AN DM-4)
  -- topic mapping moved to lesson_topics (AN DM-4); the former topic_ids uuid[] column is removed
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  -- v0.5: not in migration (replaced/removed): UNIQUE (course_module_id, position)
  -- v0.5: not in migration (replaced/removed): UNIQUE (course_version_id, lesson_key)
  CONSTRAINT ck_lesson_ref CHECK (                                -- v0.6 catalog_0002
    (lesson_type IN ('quiz','practice_set') AND test_id IS NOT NULL) OR   -- practice_set embeds a practice_set test
    (lesson_type = 'coding'     AND coding_problem_id IS NOT NULL) OR
    (lesson_type = 'assignment' AND assignment_id IS NOT NULL) OR
    (lesson_type = 'live_link'  AND live_url IS NOT NULL) OR
    (lesson_type IN ('video','article','pdf'))),                   -- pdf: file is a lesson_assets row (asset_type 'pdf'), no reference
  CONSTRAINT uq_lessons_position UNIQUE (course_module_id, position) DEFERRABLE INITIALLY DEFERRED,  -- v0.5 added in migration
  CONSTRAINT uq_lessons_key UNIQUE (course_version_id, lesson_key)  -- v0.5 added in migration
);
CREATE INDEX ix_lessons_key ON lessons (lesson_key);
CREATE INDEX ix_lessons_version ON lessons (course_version_id);  -- v0.5 added in migration
CREATE INDEX ix_lessons_assignment ON lessons (assignment_id) WHERE assignment_id IS NOT NULL;  -- v0.5 added in migration

-- (AN DM-4) Lesson → topic attribution for analytics and weak-topic recommendations. One primary topic per lesson.
-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE lesson_topics (
  lesson_id        uuid        NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  topic_id uuid NOT NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  organization_id  uuid        NULL REFERENCES organizations(id),   -- denormalised from lessons for RLS
  is_primary       boolean     NOT NULL DEFAULT false,
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (lesson_id, topic_id)
);
CREATE UNIQUE INDEX ux_lt_primary ON lesson_topics (lesson_id) WHERE is_primary;
CREATE INDEX ix_lt_topic ON lesson_topics (topic_id);

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE lesson_assets (
  id                 uuid PRIMARY KEY,
  lesson_id          uuid        NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  organization_id    uuid        NULL REFERENCES organizations(id),
  asset_type         text        NOT NULL CHECK (asset_type IN ('video','pdf','image','attachment','captions')),
  provider           text        NOT NULL CHECK (provider IN ('vdocipher','s3')),
  provider_asset_id  text        NULL,                             -- VdoCipher video id
  s3_key             text        NULL,
  mime_type          text        NULL,
  size_bytes         bigint      NULL CHECK (size_bytes >= 0),
  duration_seconds   int         NULL,
  status             text        NOT NULL DEFAULT 'processing' CHECK (status IN ('uploading','processing','available','failed','retired')),
  scan_status        text        NOT NULL DEFAULT 'pending' CHECK (scan_status IN ('pending','clean','infected','not_required')),
  position           int         NOT NULL DEFAULT 0,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_la_provider CHECK ((provider = 'vdocipher' AND provider_asset_id IS NOT NULL) OR (provider = 's3' AND s3_key IS NOT NULL))
);
CREATE UNIQUE INDEX ux_la_vdo ON lesson_assets (lesson_id, provider_asset_id) WHERE provider = 'vdocipher';  -- v0.5 as migrated
CREATE INDEX ix_la_lesson ON lesson_assets (lesson_id);  -- v0.5 added in migration
CREATE INDEX ix_la_provider_asset ON lesson_assets (provider_asset_id) WHERE provider_asset_id IS NOT NULL;  -- v0.5 added in migration

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE resources (
  id               uuid PRIMARY KEY,
  organization_id  uuid        NULL REFERENCES organizations(id),
  course_id        uuid        NULL REFERENCES courses(id),
  lesson_id uuid NULL REFERENCES lessons(id) ON DELETE SET NULL,  -- v0.5 as migrated
  company_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch); company-hub resources
  title            text        NOT NULL,
  resource_type    text        NOT NULL CHECK (resource_type IN ('file','link','cheatsheet','interview_experience')),
  s3_key           text        NULL,
  url text NULL CHECK (url IS NULL OR url ~ '^https://'),  -- v0.5 as migrated
  is_public        boolean     NOT NULL DEFAULT false,
  created_by       uuid        NOT NULL REFERENCES users(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  access_level text NOT NULL DEFAULT 'entitled' CHECK (access_level IN ('public','signed_in','entitled')),  -- v0.5 added in migration
  CONSTRAINT ck_res_target CHECK (num_nonnulls(course_id, lesson_id, company_id) >= 1),
  CONSTRAINT ck_res_payload CHECK (s3_key IS NOT NULL OR url IS NOT NULL),
  CONSTRAINT ck_res_public CHECK (is_public = (access_level = 'public'))  -- v0.5 added in migration
);
CREATE INDEX ix_res_course ON resources (course_id) WHERE course_id IS NOT NULL;  -- v0.5 added in migration

-- RLS: U | Retention: R-LEARN | PII: P1
CREATE TABLE enrolments (
  id                 uuid PRIMARY KEY,
  user_id            uuid        NOT NULL REFERENCES users(id),
  course_id          uuid        NOT NULL REFERENCES courses(id),
  course_version_id  uuid        NOT NULL REFERENCES course_versions(id),   -- pinned; upgrade is explicit
  organization_id    uuid        NULL REFERENCES organizations(id),
  batch_id           uuid        NULL REFERENCES batches(id),
  source             text        NOT NULL CHECK (source IN ('entitlement','batch_sync','manual','free')),
  entitlement_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  status             text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','suspended','expired','withdrawn')),
  enrolled_at        timestamptz NOT NULL DEFAULT now(),
  completed_at       timestamptz NULL,
  expires_at         timestamptz NULL,
  progress_pct       numeric(5,2) NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
  last_activity_at   timestamptz NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, course_id),
  CONSTRAINT ck_enr_source CHECK (source <> 'entitlement' OR entitlement_id IS NOT NULL)
);
CREATE INDEX ix_enr_course ON enrolments (course_id, status);
CREATE INDEX ix_enr_batch ON enrolments (batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX ix_enr_user_activity ON enrolments (user_id, last_activity_at DESC);  -- v0.5 added in migration

-- RLS: U | Retention: R-LEARN | PII: P1
CREATE TABLE lesson_progress (
  enrolment_id      uuid        NOT NULL REFERENCES enrolments(id) ON DELETE CASCADE,
  lesson_key        uuid        NOT NULL,                          -- stable lesson id (CCP-11)
  user_id           uuid        NOT NULL REFERENCES users(id),
  organization_id   uuid        NULL REFERENCES organizations(id),
  status            text        NOT NULL DEFAULT 'not_started' CHECK (status IN ('not_started','in_progress','completed')),
  progress_pct      numeric(5,2) NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
  video_position_s  int         NULL,
  watched_seconds int NOT NULL DEFAULT 0 CHECK (watched_seconds >= 0),  -- v0.5 as migrated; unique seconds watched (merged intervals)
  first_opened_at   timestamptz NULL,
  completed_at      timestamptz NULL,
  updated_at        timestamptz NOT NULL DEFAULT now(),
  watched_intervals jsonb NOT NULL DEFAULT '[]',  -- v0.5 added in migration
  evidence jsonb NULL,  -- v0.5 added in migration
  PRIMARY KEY (enrolment_id, lesson_key),
  CONSTRAINT ck_lp_completed CHECK ((status = 'completed') = (completed_at IS NOT NULL))  -- v0.5 added in migration
);
CREATE INDEX ix_lp_user ON lesson_progress (user_id, updated_at DESC);

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE assignments (
  id                uuid PRIMARY KEY,
  organization_id   uuid        NULL REFERENCES organizations(id),
  course_id         uuid        NULL REFERENCES courses(id),
  batch_id          uuid        NULL REFERENCES batches(id),
  title             text        NOT NULL,
  instructions_md   text        NOT NULL,
  submission_type   text        NOT NULL CHECK (submission_type IN ('file','text','link','code')),
  max_score         numeric(7,2) NOT NULL CHECK (max_score > 0),
  rubric            jsonb       NULL,
  available_from    timestamptz NULL,
  due_at            timestamptz NULL,
  late_until        timestamptz NULL,
  max_attempts smallint NOT NULL DEFAULT 1 CHECK (max_attempts BETWEEN 1 AND 20),  -- v0.5 as migrated
  created_by        uuid        NOT NULL REFERENCES users(id),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  lesson_id uuid NULL,  -- v0.5 added in migration
  allowed_file_types text[] NOT NULL DEFAULT '{pdf,zip,docx,txt}',  -- v0.5 added in migration
  late_penalty_pct numeric(5,2) NOT NULL DEFAULT 0 CHECK (late_penalty_pct BETWEEN 0 AND 100),  -- v0.5 added in migration
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),  -- v0.5 added in migration
  grades_released_at timestamptz NULL,  -- v0.5 added in migration
  CONSTRAINT ck_asg_dates CHECK (late_until IS NULL OR due_at IS NULL OR late_until >= due_at),
  CONSTRAINT ck_asg_target CHECK (num_nonnulls(course_id, batch_id) >= 1)  -- v0.5 added in migration
);
CREATE INDEX ix_asg_batch ON assignments (batch_id) WHERE batch_id IS NOT NULL;  -- v0.5 added in migration
CREATE INDEX ix_asg_course ON assignments (course_id) WHERE course_id IS NOT NULL;  -- v0.5 added in migration

-- RLS: U | Retention: R-LEARN | PII: P2 (free text / files)
CREATE TABLE assignment_submissions (
  id               uuid PRIMARY KEY,
  assignment_id    uuid        NOT NULL REFERENCES assignments(id),
  user_id          uuid        NOT NULL REFERENCES users(id),
  organization_id  uuid        NULL REFERENCES organizations(id),
  attempt_no smallint NOT NULL DEFAULT 1 CHECK (attempt_no >= 1),  -- v0.5 as migrated
  body_text        text        NULL,
  link_url text NULL CHECK (link_url IS NULL OR link_url ~ '^https?://'),  -- v0.5 as migrated
  file_s3_keys     text[]      NOT NULL DEFAULT '{}',
  code_submission_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  status           text        NOT NULL DEFAULT 'submitted' CHECK (status IN ('draft','submitted','late','graded','returned')),
  submitted_at     timestamptz NULL,
  score numeric(7,2) NULL CHECK (score IS NULL OR score >= 0),  -- v0.5 as migrated
  feedback_md      text        NULL,
  graded_by        uuid        NULL REFERENCES users(id),
  graded_at        timestamptz NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  rubric_scores jsonb NULL,  -- v0.5 added in migration
  returned_reason text NULL,  -- v0.5 added in migration
  raw_score        numeric(7,2) NULL,   -- v0.6 learning_0002 (BE-08): grader's score before the late penalty; score = final (penalised)
  late_penalty_pct numeric(5,2) NULL,   -- v0.6 learning_0002: penalty applied (copied from the assignment at grading time)
  CONSTRAINT ck_asub_raw_score CHECK (raw_score IS NULL OR raw_score >= 0),  -- v0.6
  CONSTRAINT ck_asub_late_penalty CHECK (late_penalty_pct IS NULL OR (late_penalty_pct >= 0 AND late_penalty_pct <= 100)),  -- v0.6
  UNIQUE (assignment_id, user_id, attempt_no)
);
CREATE INDEX ix_as_assignment ON assignment_submissions (assignment_id, status);  -- v0.5 added in migration
CREATE INDEX ix_as_user ON assignment_submissions (user_id, created_at DESC);  -- v0.5 added in migration

-- RLS: U (public verification served by a SECURITY DEFINER lookup on public_code exposing only safe fields)
-- Retention: R-LEARN (+ revoked kept for verification integrity) | PII: P2
-- RLS (as migrated): U. Public verification is served by the API in a named system context selecting only safe fields (no SECURITY DEFINER function)
CREATE TABLE certificates (
  id                  uuid PRIMARY KEY,
  public_code         text        NOT NULL UNIQUE CHECK (public_code ~ '^[A-Z0-9]{10,16}$'),  -- /verify/{public_code}
  user_id             uuid        NOT NULL REFERENCES users(id),
  organization_id     uuid        NULL REFERENCES organizations(id),
  course_id           uuid        NOT NULL REFERENCES courses(id),
  course_version_id   uuid        NOT NULL REFERENCES course_versions(id),
  enrolment_id        uuid        NOT NULL REFERENCES enrolments(id),
  name_on_certificate text        NOT NULL,
  identity_verified   boolean     NOT NULL DEFAULT false,
  final_attempt_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  template_version    text        NOT NULL,
  pdf_s3_key          text        NULL,
  content_hash        bytea       NOT NULL CHECK (octet_length(content_hash) = 32),
  issued_at           timestamptz NOT NULL DEFAULT now(),
  revoked_at          timestamptz NULL,
  revoke_reason       text        NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  issue_source text NOT NULL DEFAULT 'rule' CHECK (issue_source IN ('rule','manual')),  -- v0.5 added in migration
  UNIQUE (enrolment_id),
  CONSTRAINT ck_cert_revoke CHECK ((revoked_at IS NULL) = (revoke_reason IS NULL))  -- v0.5 added in migration
);
CREATE INDEX ix_cert_user ON certificates (user_id, issued_at DESC);  -- v0.5 added in migration
```

---

## 8. Placement (`placement` module)

```sql
-- RLS: NONE (global taxonomy) | Retention: R-CONTENT | PII: P0
CREATE TABLE topics (
  id          uuid PRIMARY KEY,
  parent_id   uuid        NULL REFERENCES topics(id),
  kind        text        NOT NULL CHECK (kind IN ('subject','topic','subtopic')),
  slug citext NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),  -- v0.5 as migrated
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),  -- v0.5 as migrated
  path        text        NOT NULL UNIQUE,                     -- 'quant/percentages/successive-percentages'
  depth       smallint    NOT NULL CHECK (depth BETWEEN 0 AND 2),
  position    int         NOT NULL DEFAULT 0,
  is_active   boolean     NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (parent_id, slug),
  CONSTRAINT ck_topic_root CHECK ((kind = 'subject') = (parent_id IS NULL)),
  CONSTRAINT ck_topic_depth CHECK ((kind = 'subject' AND depth = 0) OR (kind = 'topic' AND depth = 1) OR (kind = 'subtopic' AND depth = 2))  -- v0.5 added in migration
);
CREATE INDEX ix_topics_path ON topics (path text_pattern_ops);          -- subtree: path LIKE 'quant/%'
CREATE UNIQUE INDEX ux_topics_root_slug ON topics (slug) WHERE parent_id IS NULL;  -- v0.5 added in migration

-- RLS: NONE | Retention: R-CONTENT | PII: P0
CREATE TABLE companies (
  id            uuid PRIMARY KEY,
  slug citext NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),  -- v0.5 as migrated
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),  -- v0.5 as migrated
  logo_s3_key   text        NULL,
  industry      text        NULL,
  hub_status    text        NOT NULL DEFAULT 'draft' CHECK (hub_status IN ('draft','published','archived')),
  description_md text       NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE company_paths (
  id               uuid PRIMARY KEY,
  company_id       uuid        NOT NULL REFERENCES companies(id),
  organization_id  uuid        NULL REFERENCES organizations(id),
  role_name        text        NOT NULL,                        -- 'Ninja', 'Digital', 'SDE-1'
  version_no       int         NOT NULL DEFAULT 1,
  pattern          jsonb       NOT NULL,                        -- [{section, topic_id, weight, minutes, question_count}]
  status           text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','retired')),
  published_at     timestamptz NULL,
  created_by       uuid        NOT NULL REFERENCES users(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (company_id, role_name, version_no)
);

-- (CCP-4) RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE company_path_steps (
  id                uuid PRIMARY KEY,
  company_path_id   uuid        NOT NULL REFERENCES company_paths(id) ON DELETE CASCADE,
  organization_id   uuid        NULL REFERENCES organizations(id),
  position          int         NOT NULL,
  step_type         text        NOT NULL CHECK (step_type IN ('lesson','practice_set','test','coding_set')),
  lesson_key        uuid        NULL,
  test_id           uuid        NULL REFERENCES tests(id),
  topic_id          uuid        NULL REFERENCES topics(id),
  title             text        NOT NULL,
  is_required       boolean     NOT NULL DEFAULT true,
  UNIQUE (company_path_id, position),
  CONSTRAINT ck_cps_ref CHECK (num_nonnulls(lesson_key, test_id, topic_id) = 1)
);

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE questions (
  id                    uuid PRIMARY KEY,
  organization_id       uuid        NULL REFERENCES organizations(id),   -- NULL = platform bank
  question_type         text        NOT NULL CHECK (question_type IN ('mcq_single','mcq_multi','numeric','fill_blank',
                                        'coding','descriptive')),
  primary_topic_id      uuid        NOT NULL REFERENCES topics(id),
  status                text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','retired')),
  current_version_id    uuid        NULL,                                -- FK below; latest published
  external_ref          text        NULL,
  created_by            uuid        NOT NULL REFERENCES users(id),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  deleted_at            timestamptz NULL,
  retired_reason        text        NULL CONSTRAINT ck_q_retired_reason CHECK (retired_reason IS NULL OR char_length(retired_reason) <= 500)  -- v0.6 placement_0004 (ADM-55)
);
CREATE INDEX ix_q_topic ON questions (primary_topic_id, status);

-- Immutable after publish (trigger blocks UPDATE of content columns when status='published'). RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE question_versions (
  id                 uuid PRIMARY KEY,
  question_id        uuid        NOT NULL REFERENCES questions(id),
  organization_id    uuid        NULL REFERENCES organizations(id),
  version_no         int         NOT NULL CHECK (version_no >= 1),
  stem               jsonb       NOT NULL,                       -- rich text (KaTeX, code blocks, images by s3 key)
  answer_key         jsonb       NULL,                           -- numeric {value, tolerance} / fill_blank {accepted:[..]} — NEVER in delivery DTOs
  explanation        jsonb       NULL,
  difficulty         smallint    NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
  item_rating        smallint    NOT NULL DEFAULT 1000,          -- adaptive practice (Elo)
  default_marks      numeric(6,2) NOT NULL DEFAULT 1 CHECK (default_marks > 0),
  default_negative   numeric(6,2) NOT NULL DEFAULT 0 CHECK (default_negative >= 0),
  expected_seconds   int         NULL,
  coding_problem_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  status             text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','in_review','published','retired')),
  content_hash       bytea       NOT NULL CHECK (octet_length(content_hash) = 32),
  authored_by        uuid        NOT NULL REFERENCES users(id),
  reviewed_by        uuid        NULL REFERENCES users(id),
  published_at       timestamptz NULL,
  edited_by          uuid[]      NOT NULL DEFAULT '{}',          -- v0.6 placement_0004 (ADM-46/48): in-place editors other than authored_by; refused review/publish (SoD)
  review_comment     text        NULL CONSTRAINT ck_qv_review_comment CHECK (review_comment IS NULL OR char_length(review_comment) <= 2000),  -- v0.6 placement_0004 (ADM-55)
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (question_id, version_no),
  CONSTRAINT ck_qv_review CHECK (status <> 'published' OR (reviewed_by IS NOT NULL AND published_at IS NOT NULL)),
  CONSTRAINT ck_qv_reviewer CHECK (reviewed_by IS NULL OR reviewed_by <> authored_by OR organization_id IS NOT NULL)
);
ALTER TABLE questions ADD CONSTRAINT fk_q_current FOREIGN KEY (current_version_id) REFERENCES question_versions(id);
CREATE INDEX ix_qv_pool ON question_versions (difficulty, status) INCLUDE (question_id) WHERE status = 'published';
CREATE INDEX ix_qv_question ON question_versions (question_id, version_no DESC);  -- v0.5 added in migration

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE question_options (
  id                   uuid PRIMARY KEY,
  question_version_id  uuid        NOT NULL REFERENCES question_versions(id) ON DELETE CASCADE,
  organization_id      uuid        NULL REFERENCES organizations(id),
  label                text        NOT NULL,                     -- 'A'
  body                 jsonb       NOT NULL,
  is_correct           boolean     NOT NULL DEFAULT false,       -- NEVER in delivery DTOs
  position             smallint    NOT NULL,
  feedback             jsonb       NULL,
  UNIQUE (question_version_id, position),
  UNIQUE (question_version_id, label)
);

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE question_tags (
  id               uuid PRIMARY KEY,
  question_id      uuid        NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  organization_id  uuid        NULL REFERENCES organizations(id),
  tag_type         text        NOT NULL CHECK (tag_type IN ('topic','company','skill','exam_pattern','source','custom')),
  topic_id         uuid        NULL REFERENCES topics(id),
  company_id       uuid        NULL REFERENCES companies(id),
  tag_value        text        NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_qt_payload CHECK (
    (tag_type = 'topic'   AND topic_id IS NOT NULL) OR
    (tag_type = 'company' AND company_id IS NOT NULL) OR
    (tag_type NOT IN ('topic','company') AND tag_value IS NOT NULL))
);
CREATE UNIQUE INDEX ux_qt ON question_tags (question_id, tag_type, coalesce(topic_id::text, company_id::text, tag_value));
CREATE INDEX ix_qt_topic ON question_tags (topic_id) WHERE topic_id IS NOT NULL;
CREATE INDEX ix_qt_company ON question_tags (company_id) WHERE company_id IS NOT NULL;

-- (CCP-4) RLS: U | Retention: R-LEARN | PII: P1
CREATE TABLE practice_sessions (
  id                  uuid PRIMARY KEY,
  user_id             uuid        NOT NULL REFERENCES users(id),
  organization_id     uuid        NULL REFERENCES organizations(id),
  mode                text        NOT NULL CHECK (mode IN ('adaptive','topic_set','company_step','revision')),
  topic_id            uuid        NULL REFERENCES topics(id),
  company_path_step_id uuid       NULL REFERENCES company_path_steps(id),
  status              text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','abandoned')),
  target_count        smallint    NULL,
  answered_count      smallint    NOT NULL DEFAULT 0,
  correct_count       smallint    NOT NULL DEFAULT 0,
  started_at          timestamptz NOT NULL DEFAULT now(),
  ended_at            timestamptz NULL,
  updated_at          timestamptz NOT NULL DEFAULT now(),
  served jsonb NOT NULL DEFAULT '[]'  -- v0.5 added in migration
);
CREATE INDEX ix_prs_user ON practice_sessions (user_id, started_at DESC);

-- (CCP-4) RLS: U | Retention: R-LEARN | PII: P1
CREATE TABLE practice_responses (
  id                   uuid PRIMARY KEY,
  practice_session_id  uuid        NOT NULL REFERENCES practice_sessions(id) ON DELETE CASCADE,
  user_id              uuid        NOT NULL REFERENCES users(id),
  organization_id      uuid        NULL REFERENCES organizations(id),
  question_version_id  uuid        NOT NULL REFERENCES question_versions(id),
  topic_id             uuid        NOT NULL REFERENCES topics(id),
  response             jsonb       NOT NULL,
  is_correct           boolean     NULL,                         -- NULL for descriptive
  attempt_no           smallint    NOT NULL DEFAULT 1 CHECK (attempt_no >= 1),   -- nth time this user answered this question (AN DM-5)
  served_at            timestamptz NOT NULL,                     -- server time the question was shown
  time_spent_ms        int         NOT NULL CHECK (time_spent_ms >= 0),
  hint_used            boolean     NOT NULL DEFAULT false,
  solution_viewed      boolean     NOT NULL DEFAULT false,       -- viewed before answering ⇒ excluded from mastery/item stats
  rating_before        smallint    NULL,
  rating_after         smallint    NULL,
  answered_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (practice_session_id, question_version_id),
  CONSTRAINT ck_pr_time CHECK (answered_at >= served_at)
);
CREATE INDEX ix_pr_user_q ON practice_responses (user_id, question_version_id, answered_at DESC);
CREATE INDEX ix_pr_user_topic ON practice_responses (user_id, topic_id, answered_at);  -- v0.5 added in migration
-- Mastery: see topic_mastery (§12, owned by analytics; AN CP-11). The former user_topic_mastery table is not created.

-- (CCP-4) RLS: U | Retention: 90 days after expiry | PII: P1
CREATE TABLE recommendations (
  id               uuid PRIMARY KEY,
  user_id          uuid        NOT NULL REFERENCES users(id),
  organization_id  uuid        NULL REFERENCES organizations(id),
  rule_key         text        NOT NULL CHECK (rule_key IN ('weak_topic','stale_topic','path_next_step','assigned_due','readiness_gap')),
  rule_version     smallint    NOT NULL DEFAULT 1,
  reason           text        NOT NULL,                         -- human-readable, includes numbers
  evidence         jsonb       NOT NULL DEFAULT '{}',
  target_type      text        NOT NULL CHECK (target_type IN ('lesson','practice_set','test','topic','company_path_step')),
  target_id        uuid        NOT NULL,
  priority         smallint    NOT NULL DEFAULT 50,
  status           text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','dismissed','completed','expired')),
  generated_at     timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL
);
CREATE INDEX ix_rec_user_active ON recommendations (user_id, priority DESC) WHERE status = 'active';
CREATE UNIQUE INDEX ux_rec_dedupe ON recommendations (user_id, rule_key, target_type, target_id) WHERE status = 'active';

-- (PRD CCP-02, P1) Mentor availability. External meeting link in v1 (OPD-08). RLS: TN (platform mentors NULL org) | Retention: R-LEARN | PII: P1
-- STATUS: migrated in mentoring_0001 (v0.6, audit fix wave 3 re-check 2026-11-03). Columns not re-diffed against the migration since v0.5; the migration wins (§17).
CREATE TABLE mentor_slots (
  id               uuid PRIMARY KEY,
  mentor_id        uuid        NOT NULL REFERENCES users(id),
  organization_id  uuid        NULL REFERENCES organizations(id),
  starts_at        timestamptz NOT NULL,
  duration_minutes smallint    NOT NULL CHECK (duration_minutes IN (30,45,60)),
  session_kind     text        NOT NULL CHECK (session_kind IN ('mock_interview','resume_review','career_guidance')),
  company_id       uuid        NULL REFERENCES companies(id),
  status           text        NOT NULL DEFAULT 'open' CHECK (status IN ('open','booked','cancelled','completed')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ms_open ON mentor_slots (starts_at) WHERE status = 'open';
CREATE UNIQUE INDEX ux_ms_mentor_time ON mentor_slots (mentor_id, starts_at) WHERE status <> 'cancelled';

-- (PRD CCP-02) Booking consumes entitlements.mentor_sessions_remaining; mentor no-show credits it back.
-- RLS: U (student) + mentor visibility via API | Retention: R-LEARN | PII: P1/P2
-- STATUS: migrated in mentoring_0001 (v0.6, audit fix wave 3 re-check 2026-11-03). Columns not re-diffed against the migration since v0.5; the migration wins (§17).
CREATE TABLE mentor_bookings (
  id                 uuid PRIMARY KEY,
  mentor_slot_id     uuid        NOT NULL REFERENCES mentor_slots(id),
  user_id            uuid        NOT NULL REFERENCES users(id),
  organization_id    uuid        NULL REFERENCES organizations(id),
  entitlement_id     uuid        NULL REFERENCES entitlements(id),   -- quota source (BR-ENT-03)
  meeting_url        text        NULL,                               -- external link (v1)
  status             text        NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','rescheduled','cancelled_by_student',
                                     'cancelled_by_mentor','completed','student_no_show','mentor_no_show')),
  quota_consumed     boolean     NOT NULL DEFAULT true,
  cancelled_at       timestamptz NULL,
  idempotency_key    text        NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, idempotency_key)
);
CREATE UNIQUE INDEX ux_mb_slot_live ON mentor_bookings (mentor_slot_id) WHERE status IN ('booked','rescheduled','completed');
CREATE INDEX ix_mb_user ON mentor_bookings (user_id, created_at DESC);

-- (PRD CCP-02) Rubric feedback, visible to the student within 48 h. RLS: U | Retention: R-LEARN | PII: P2 (free text)
-- STATUS: migrated in mentoring_0001 (v0.6, audit fix wave 3 re-check 2026-11-03). Columns not re-diffed against the migration since v0.5; the migration wins (§17).
CREATE TABLE interview_feedback (
  id                  uuid PRIMARY KEY,
  mentor_booking_id   uuid        NOT NULL UNIQUE REFERENCES mentor_bookings(id),
  user_id             uuid        NOT NULL REFERENCES users(id),
  organization_id     uuid        NULL REFERENCES organizations(id),
  mentor_id           uuid        NOT NULL REFERENCES users(id),
  scores              jsonb       NOT NULL,                          -- {communication, problem_solving, technical_depth, confidence}: 1–5
  comments            text        NULL CHECK (comments IS NULL OR char_length(comments) <= 5000),
  released_at         timestamptz NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- (PRD CCP-06, P1) Structured résumé, versioned. RLS: O (+ assigned mentor via API) | Retention: R-ACCT | PII: P2
-- STATUS: migrated in mentoring_0001 (v0.6, audit fix wave 3 re-check 2026-11-03). Columns not re-diffed against the migration since v0.5; the migration wins (§17).
CREATE TABLE resumes (
  id               uuid PRIMARY KEY,
  user_id          uuid        NOT NULL REFERENCES users(id),
  template_key     text        NOT NULL CHECK (template_key IN ('ats_classic','ats_modern')),
  version_no       int         NOT NULL DEFAULT 1 CHECK (version_no >= 1),
  content          jsonb       NOT NULL,                             -- education, skills, projects, internships, achievements, certifications
  checklist_score  smallint    NULL CHECK (checklist_score BETWEEN 0 AND 100),
  pdf_s3_key       text        NULL,
  is_current       boolean     NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, version_no)
);
CREATE UNIQUE INDEX ux_resume_current ON resumes (user_id) WHERE is_current;

-- (PRD CCP-06) Mentor review request (premium). RLS: O (+ reviewer via API) | Retention: R-ACCT | PII: P2
-- STATUS: migrated in mentoring_0001 (v0.6, audit fix wave 3 re-check 2026-11-03). Columns not re-diffed against the migration since v0.5; the migration wins (§17).
CREATE TABLE resume_reviews (
  id               uuid PRIMARY KEY,
  resume_id        uuid        NOT NULL REFERENCES resumes(id),
  user_id          uuid        NOT NULL REFERENCES users(id),
  reviewer_id      uuid        NULL REFERENCES users(id),
  entitlement_id   uuid        NULL REFERENCES entitlements(id),
  status           text        NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','in_review','completed','cancelled')),
  comments         jsonb       NOT NULL DEFAULT '[]',                -- [{section, comment}]
  requested_at     timestamptz NOT NULL DEFAULT now(),
  completed_at     timestamptz NULL,
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_rr_queue ON resume_reviews (status, requested_at) WHERE status IN ('requested','in_review');
```

Reserved (PRD CCP-03, Deferred-to-owner OPD-12, default P2; no DDL in the baseline): `placement_drives`, `drive_eligibility_rules`, `drive_shortlists`.

---

## 9. Assessments (`assessments` module)

```sql
-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE tests (
  id                  uuid PRIMARY KEY,
  organization_id     uuid        NULL REFERENCES organizations(id),
  test_kind           text        NOT NULL CHECK (test_kind IN ('practice_set','mock','company_mock','diagnostic','course_quiz','drive')),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 300),  -- v0.5 as migrated
  slug                citext      NULL,
  company_id          uuid        NULL REFERENCES companies(id),
  company_path_id     uuid        NULL REFERENCES company_paths(id),
  status              text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','closed','archived')),
  version             int         NOT NULL DEFAULT 1,           -- bumped on republish; attempts store it
  duration_seconds    int         NULL CHECK (duration_seconds > 0),   -- NULL = untimed practice
  grace_seconds       int         NOT NULL DEFAULT 30 CHECK (grace_seconds BETWEEN 0 AND 300),
  navigation_mode     text        NOT NULL DEFAULT 'free' CHECK (navigation_mode IN ('free','sequential','section_locked')),
  attempts_allowed    smallint    NULL CHECK (attempts_allowed > 0),   -- NULL = unlimited
  grading_method      text        NOT NULL DEFAULT 'highest' CHECK (grading_method IN ('highest','latest','first','average')),
  shuffle_questions   boolean     NOT NULL DEFAULT true,
  shuffle_options     boolean     NOT NULL DEFAULT true,
  review_policy       jsonb       NOT NULL,                      -- 4-phase matrix (system-architecture §8.6)
  integrity_settings jsonb NOT NULL DEFAULT jsonb_build_object('fullscreen', false, 'log_focus', true, 'log_paste', true),  -- v0.5 as migrated
  pass_percentage     numeric(5,2) NULL,
  is_free             boolean     NOT NULL DEFAULT false,
  available_from      timestamptz NULL,
  available_until     timestamptz NULL,
  settings_locked_at  timestamptz NULL,                          -- first attempt start
  published_at        timestamptz NULL,
  created_by          uuid        NOT NULL REFERENCES users(id),
  batch_id            uuid        NULL REFERENCES batches(id),   -- v0.6 assessments_0003 (ADM-49): owning batch; every trainer of that batch may edit; NULL = legacy creator-only rule
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_tests_window CHECK (available_until IS NULL OR available_from IS NULL OR available_until > available_from)
);
CREATE INDEX ix_tests_company ON tests (company_id) WHERE company_id IS NOT NULL;
CREATE INDEX ix_tests_batch ON tests (batch_id) WHERE batch_id IS NOT NULL;  -- v0.6 assessments_0003
CREATE INDEX ix_tests_org ON tests (organization_id, status);  -- v0.5 added in migration

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE test_sections (
  id                uuid PRIMARY KEY,
  test_id           uuid        NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
  organization_id   uuid        NULL REFERENCES organizations(id),
  title             text        NOT NULL,
  position          smallint    NOT NULL,
  duration_seconds  int         NULL CHECK (duration_seconds > 0),   -- sectional timer
  instructions_md   text        NULL,
  min_attempt_required smallint NULL,
  UNIQUE (test_id, position)
);

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE test_section_rules (
  id                   uuid PRIMARY KEY,
  test_section_id      uuid        NOT NULL REFERENCES test_sections(id) ON DELETE CASCADE,
  organization_id      uuid        NULL REFERENCES organizations(id),
  position             smallint    NOT NULL,
  rule_type            text        NOT NULL CHECK (rule_type IN ('fixed','random')),
  question_id          uuid        NULL REFERENCES questions(id),
  question_version_id  uuid        NULL REFERENCES question_versions(id),   -- pin a version (optional)
  topic_id             uuid        NULL REFERENCES topics(id),               -- subtree
  company_id           uuid        NULL REFERENCES companies(id),
  question_types       text[]      NULL,
  difficulty_min       smallint    NULL CHECK (difficulty_min BETWEEN 1 AND 5),
  difficulty_max       smallint    NULL CHECK (difficulty_max BETWEEN 1 AND 5),
  tag_filter           jsonb       NULL,
  draw_count           smallint    NOT NULL DEFAULT 1 CHECK (draw_count >= 1),
  marks_each numeric(6,2) NULL CHECK (marks_each > 0),  -- v0.5 as migrated; overrides version default
  negative_marks_each  numeric(6,2) NULL CHECK (negative_marks_each >= 0),
  UNIQUE (test_section_id, position),
  CONSTRAINT ck_tsr_type CHECK (
    (rule_type = 'fixed'  AND question_id IS NOT NULL AND draw_count = 1) OR
    (rule_type = 'random' AND question_id IS NULL AND topic_id IS NOT NULL)),
  CONSTRAINT ck_tsr_diff CHECK (difficulty_min IS NULL OR difficulty_max IS NULL OR difficulty_min <= difficulty_max)
);

-- (CCP-3) RLS: T (org-scoped) or TN for platform-wide drives | Retention: R-CONTENT | PII: P0
CREATE TABLE test_assignments (
  id                uuid PRIMARY KEY,
  test_id           uuid        NOT NULL REFERENCES tests(id),
  organization_id   uuid        NULL REFERENCES organizations(id),
  batch_id          uuid        NULL REFERENCES batches(id),
  course_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  available_from    timestamptz NOT NULL,
  available_until   timestamptz NOT NULL,
  attempts_allowed smallint NULL CHECK (attempts_allowed > 0),  -- v0.5 as migrated
  release_mode      text        NOT NULL DEFAULT 'immediate' CHECK (release_mode IN ('immediate','after_window','scheduled','manual')),  -- PRD CCP-09
  results_release_at timestamptz NULL,
  assigned_by       uuid        NOT NULL REFERENCES users(id),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_ta_target CHECK (num_nonnulls(batch_id, course_id) >= 1 OR organization_id IS NOT NULL),
  CONSTRAINT ck_ta_window CHECK (available_until > available_from),
  CONSTRAINT ck_ta_scheduled CHECK (release_mode <> 'scheduled' OR results_release_at IS NOT NULL)  -- v0.5 added in migration
);
CREATE INDEX ix_ta_batch ON test_assignments (batch_id, available_from) WHERE batch_id IS NOT NULL;
CREATE INDEX ix_ta_test ON test_assignments (test_id);  -- v0.5 added in migration

-- (CCP-3) RLS: T/U | Retention: R-LEARN | PII: P1
CREATE TABLE attempt_overrides (
  id                     uuid PRIMARY KEY,
  test_id                uuid        NOT NULL REFERENCES tests(id),
  test_assignment_id     uuid        NULL REFERENCES test_assignments(id),
  organization_id        uuid        NULL REFERENCES organizations(id),
  user_id                uuid        NULL REFERENCES users(id),
  batch_id               uuid        NULL REFERENCES batches(id),
  extra_time_seconds     int         NOT NULL DEFAULT 0 CHECK (extra_time_seconds >= 0),
  extra_attempts         smallint    NOT NULL DEFAULT 0 CHECK (extra_attempts >= 0),
  window_extension_seconds int       NOT NULL DEFAULT 0 CHECK (window_extension_seconds >= 0),
  reason text NOT NULL CHECK (char_length(reason) BETWEEN 3 AND 500),  -- v0.5 as migrated; 'accessibility', 'power cut during attempt'
  granted_by             uuid        NOT NULL REFERENCES users(id),
  created_at             timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_ao_target CHECK (num_nonnulls(user_id, batch_id) = 1)
);
CREATE INDEX ix_ao_user ON attempt_overrides (test_id, user_id) WHERE user_id IS NOT NULL;
CREATE INDEX ix_ao_batch ON attempt_overrides (test_id, batch_id) WHERE batch_id IS NOT NULL;  -- v0.5 added in migration

-- RLS: U | Retention: R-LEARN | PII: P1/P3 (ip)
CREATE TABLE test_attempts (
  id                   uuid PRIMARY KEY,
  test_id              uuid        NOT NULL REFERENCES tests(id),
  test_version         int         NOT NULL,
  test_assignment_id   uuid        NULL REFERENCES test_assignments(id),
  user_id              uuid        NOT NULL REFERENCES users(id),
  organization_id      uuid        NULL REFERENCES organizations(id),
  batch_id             uuid        NULL REFERENCES batches(id),
  attempt_no           smallint    NOT NULL CHECK (attempt_no >= 1),
  status               text        NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','submitted','auto_submitted',
                                       'grading','awaiting_manual','graded','invalidated','abandoned')),
  selection_seed       bytea       NOT NULL CHECK (octet_length(selection_seed) = 16),
  layout               jsonb       NOT NULL,                      -- frozen [{section_id,[{qv_id, option_order}]}]
  started_at           timestamptz NOT NULL DEFAULT now(),
  deadline_at          timestamptz NULL,                          -- NULL for untimed
  extra_time_seconds   int         NOT NULL DEFAULT 0,
  submitted_at         timestamptz NULL,
  submit_reason        text        NULL CHECK (submit_reason IN ('user','deadline','section_end','admin_force','session_end')),
  last_seen_at         timestamptz NOT NULL DEFAULT now(),
  current_section_id   uuid        NULL REFERENCES test_sections(id),
  -- Attempt–session binding (Brief v0.2 §1; SEC-DM-17, PRD CCP-01/SEC CCP-S3). Other sessions get 409 attempt_bound_elsewhere.
  bound_session_id     uuid        NULL REFERENCES auth_sessions(id),
  bound_device_id      uuid        NULL REFERENCES devices(id),
  rebind_count         smallint    NOT NULL DEFAULT 0 CHECK (rebind_count >= 0),   -- ≤ assessment.max_rebinds_per_attempt (2), service-enforced; incremented only when bound_device_id changes; same-device re-attach does not count
  start_ip             inet        NULL,
  idempotency_key      text        NOT NULL,
  integrity_status     text        NOT NULL DEFAULT 'none' CHECK (integrity_status IN ('none','review_recommended','cleared','invalidated')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (test_id, user_id, attempt_no),
  UNIQUE (user_id, idempotency_key),
  CONSTRAINT ck_att_submit CHECK ((status IN ('in_progress','abandoned')) OR submitted_at IS NOT NULL)
);
CREATE UNIQUE INDEX ux_att_one_open ON test_attempts (test_id, user_id) WHERE status = 'in_progress';
CREATE INDEX ix_att_deadline ON test_attempts (deadline_at) WHERE status = 'in_progress';      -- DB safety sweeper
CREATE INDEX ix_att_user ON test_attempts (user_id, started_at DESC);
CREATE INDEX ix_att_assignment ON test_attempts (test_assignment_id, status) WHERE test_assignment_id IS NOT NULL;
CREATE INDEX ix_att_bound_session ON test_attempts (bound_session_id) WHERE status = 'in_progress';  -- v0.5 added in migration
CREATE INDEX ix_att_test ON test_attempts (test_id, status);  -- v0.5 added in migration

-- (CCP-3) RLS: U | Retention: R-LEARN | PII: P1
CREATE TABLE attempt_sections (
  attempt_id        uuid        NOT NULL REFERENCES test_attempts(id) ON DELETE CASCADE,
  test_section_id   uuid        NOT NULL REFERENCES test_sections(id),
  user_id           uuid        NOT NULL,
  organization_id   uuid        NULL,
  position          smallint    NOT NULL,
  status            text        NOT NULL DEFAULT 'not_started' CHECK (status IN ('not_started','active','submitted','timed_out')),
  started_at        timestamptz NULL,
  deadline_at       timestamptz NULL,
  submitted_at      timestamptz NULL,
  PRIMARY KEY (attempt_id, test_section_id)
);

-- Latest answer state per question (history lives in attempt_events). RLS: U | Retention: R-LEARN | PII: P1
CREATE TABLE attempt_responses (
  id                   uuid PRIMARY KEY,
  attempt_id           uuid        NOT NULL REFERENCES test_attempts(id) ON DELETE CASCADE,
  user_id              uuid        NOT NULL,
  organization_id      uuid        NULL,
  test_section_id      uuid        NOT NULL REFERENCES test_sections(id),
  question_version_id  uuid        NOT NULL REFERENCES question_versions(id),
  response             jsonb       NULL,                          -- {"option_ids":[..]} | {"value":"12.5"} | {"code_submission_id":".."}
  client_seq           bigint      NOT NULL CHECK (client_seq >= 0),
  flagged              boolean     NOT NULL DEFAULT false,
  time_spent_ms        int         NOT NULL DEFAULT 0,
  first_answered_at    timestamptz NULL,
  saved_at             timestamptz NOT NULL DEFAULT now(),
  is_correct           boolean     NULL,                          -- set by scoring only
  marks_awarded        numeric(7,2) NULL,
  manual_grade_by      uuid        NULL REFERENCES users(id),
  UNIQUE (attempt_id, question_version_id)
);

-- Partitioned monthly on occurred_at; append-only. RLS: U | Retention: R-ASSESS-EVT | PII: P1/P3 (ip)
CREATE TABLE attempt_events (
  id                   uuid        NOT NULL,
  occurred_at          timestamptz NOT NULL,                      -- server receive time (client time in payload)
  attempt_id           uuid        NOT NULL,                      -- soft ref
  user_id              uuid        NOT NULL,
  organization_id      uuid        NULL,
  event_type           text        NOT NULL CHECK (event_type IN ('start','resume','answer_saved','answer_cleared','flag',
                          'section_enter','section_submit','navigate','focus_lost','focus_gained','fullscreen_exit','paste',
                          'disconnect','reconnect','rebind_requested','rebind','rebind_refused','session_revoked_security',
                          'timer_sync','submit','auto_submit','override_applied','regrade','invalidate',
                          'reattach_same_device')),     -- v0.4: same device_id re-login re-attaches without a rebind
  question_version_id  uuid        NULL,
  client_seq           bigint      NULL,
  payload              jsonb       NOT NULL DEFAULT '{}',
  auth_session_id      uuid        NULL,
  ip                   inet        NULL,
  PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at);
CREATE INDEX ix_ae_attempt ON attempt_events (attempt_id, occurred_at);

-- RLS: U | Retention: R-LEARN | PII: P1
CREATE TABLE attempt_results (
  attempt_id          uuid PRIMARY KEY REFERENCES test_attempts(id),
  user_id             uuid        NOT NULL REFERENCES users(id),
  organization_id     uuid        NULL REFERENCES organizations(id),
  test_id             uuid        NOT NULL REFERENCES tests(id),
  scoring_version     smallint    NOT NULL DEFAULT 1,
  score               numeric(8,2) NOT NULL,
  max_score           numeric(8,2) NOT NULL CHECK (max_score > 0),
  percentage          numeric(5,2) NOT NULL,
  correct_count       smallint    NOT NULL,
  incorrect_count     smallint    NOT NULL,
  unanswered_count    smallint    NOT NULL,
  time_taken_seconds  int         NOT NULL,
  section_scores      jsonb       NOT NULL,                       -- [{section_id, score, max, time_s}]
  topic_scores        jsonb       NOT NULL,                       -- [{topic_id, correct, total, avg_time_ms}]
  percentile          numeric(5,2) NULL,
  rank                int         NULL,
  rank_provisional    boolean     NOT NULL DEFAULT true,
  passed              boolean     NULL,
  graded_at           timestamptz NOT NULL DEFAULT now(),
  released_at         timestamptz NULL,
  updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ares_test_score ON attempt_results (test_id, score DESC);
```

---

## 10. Coding (`coding` module)

```sql
-- (CCP-6) RLS: NONE | Retention: R-CONTENT | PII: P0
CREATE TABLE judge_languages (
  id                    uuid PRIMARY KEY,
  language_key text NOT NULL UNIQUE CHECK (language_key ~ '^[a-z][a-z0-9_]{0,31}$'),  -- v0.5 as migrated; 'cpp17','java17','python3','c'
  display_name          text        NOT NULL,
  provider_language_id  int         NOT NULL,                    -- Judge0 language_id
  time_multiplier numeric(4,2) NOT NULL DEFAULT 1.0 CHECK (time_multiplier BETWEEN 0.5 AND 5),  -- v0.5 as migrated; Java/Python allowance
  memory_extra_kb int NOT NULL DEFAULT 0 CHECK (memory_extra_kb >= 0),  -- v0.5 as migrated
  max_processes smallint NOT NULL DEFAULT 64 CHECK (max_processes BETWEEN 1 AND 256),  -- v0.5 as migrated
  is_enabled            boolean     NOT NULL DEFAULT true,
  starter_template      text        NULL,
  updated_at            timestamptz NOT NULL DEFAULT now(),
  version_label text NULL  -- v0.5 added in migration
);

-- RLS: TN | Retention: R-CONTENT | PII: P0
CREATE TABLE coding_problems (
  id                uuid PRIMARY KEY,
  organization_id   uuid        NULL REFERENCES organizations(id),
  slug citext NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,79}$'),  -- v0.5 as migrated
  title text NOT NULL CHECK (char_length(title) BETWEEN 3 AND 200),  -- v0.5 as migrated
  version_no        int         NOT NULL DEFAULT 1,               -- bumped when cases/limits change
  statement_md      text        NOT NULL,
  input_format_md   text        NULL,
  output_format_md  text        NULL,
  constraints_md    text        NULL,
  difficulty        smallint    NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
  primary_topic_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  time_limit_ms     int         NOT NULL DEFAULT 2000 CHECK (time_limit_ms BETWEEN 100 AND 5000),
  wall_limit_ms     int         NOT NULL DEFAULT 5000 CHECK (wall_limit_ms BETWEEN 200 AND 10000),
  memory_limit_kb   int         NOT NULL DEFAULT 262144 CHECK (memory_limit_kb BETWEEN 16384 AND 524288),
  allowed_languages text[]      NOT NULL DEFAULT '{c,cpp17,java17,python3}',
  checker_type      text        NOT NULL DEFAULT 'exact' CHECK (checker_type IN ('exact','token','float_tolerance','custom')),
  checker_config    jsonb       NULL,
  scoring_mode      text        NOT NULL DEFAULT 'weighted_cases' CHECK (scoring_mode IN ('weighted_cases','all_or_nothing')),
  status            text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','in_review','published','retired')),
  created_by        uuid        NOT NULL REFERENCES users(id),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  is_free boolean NOT NULL DEFAULT false,  -- v0.5 added in migration
  published_by uuid NULL REFERENCES users(id),  -- v0.5 added in migration
  published_at timestamptz NULL,  -- v0.5 added in migration
  CONSTRAINT ck_cp_wall CHECK (wall_limit_ms >= time_limit_ms)
);
CREATE UNIQUE INDEX ux_cp_slug ON coding_problems (coalesce(organization_id, '00000000-0000-0000-0000-000000000000'::uuid), slug);
CREATE INDEX ix_cp_status ON coding_problems (status, difficulty);  -- v0.5 added in migration

-- Hidden case content lives encrypted in S3 (system-architecture §9.3). RLS: TN | Retention: R-CONTENT | PII: P0 (P4 for keys)
CREATE TABLE coding_test_cases (
  id                  uuid PRIMARY KEY,
  coding_problem_id   uuid        NOT NULL REFERENCES coding_problems(id) ON DELETE CASCADE,
  organization_id     uuid        NULL REFERENCES organizations(id),
  problem_version     int         NOT NULL,
  ordinal smallint NOT NULL CHECK (ordinal >= 1),  -- v0.5 as migrated
  is_sample           boolean     NOT NULL DEFAULT false,         -- shown in statement, used by Run
  is_hidden           boolean     NOT NULL DEFAULT true,
  weight              numeric(6,2) NOT NULL DEFAULT 1 CHECK (weight >= 0),
  sample_input        text        NULL,                            -- plaintext only for samples
  sample_output       text        NULL,
  input_s3_key        text        NULL,                            -- hidden: AES-GCM ciphertext
  expected_s3_key     text        NULL,
  wrapped_data_key    bytea       NULL,                            -- KMS-wrapped (key td-judge-testcases)
  input_sha256 bytea NULL CHECK (input_sha256 IS NULL OR octet_length(input_sha256) = 32),  -- v0.5 as migrated
  expected_sha256 bytea NULL CHECK (expected_sha256 IS NULL OR octet_length(expected_sha256) = 32),  -- v0.5 as migrated
  size_bytes          int         NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (coding_problem_id, problem_version, ordinal),
  CONSTRAINT ck_ctc_mode CHECK (is_sample <> is_hidden),
  CONSTRAINT ck_ctc_sample CHECK (NOT is_sample OR (sample_input IS NOT NULL AND sample_output IS NOT NULL)),
  CONSTRAINT ck_ctc_hidden CHECK (NOT is_hidden OR (input_s3_key IS NOT NULL AND expected_s3_key IS NOT NULL
                                  AND wrapped_data_key IS NOT NULL AND sample_input IS NULL AND sample_output IS NULL))
);

-- RLS: U | Retention: R-LEARN (source kept; practice runs purged after 90 days) | PII: P1 (code may be personal work product)
CREATE TABLE code_submissions (
  id                  uuid PRIMARY KEY,
  user_id             uuid        NOT NULL REFERENCES users(id),
  organization_id     uuid        NULL REFERENCES organizations(id),
  coding_problem_id   uuid        NOT NULL REFERENCES coding_problems(id),
  problem_version     int         NOT NULL,
  language_key        text        NOT NULL REFERENCES judge_languages(language_key),
  mode                text        NOT NULL CHECK (mode IN ('run','submit')),
  attempt_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch); inside an assessment
  practice_session_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  source_code         text        NOT NULL CHECK (octet_length(source_code) <= 65536),
  custom_input        text        NULL CHECK (custom_input IS NULL OR octet_length(custom_input) <= 65536),
  status              text        NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','judge_error','judge_timeout','rejected')),
  verdict             text        NULL CHECK (verdict IN ('AC','WA','TLE','MLE','RE','CE','PARTIAL','IE')),
  score               numeric(7,2) NULL,
  passed_cases        smallint    NULL,
  total_cases         smallint    NULL,
  max_time_ms         int         NULL,
  max_memory_kb       int         NULL,
  compile_output      text        NULL CHECK (compile_output IS NULL OR octet_length(compile_output) <= 16384),
  judge_provider text NOT NULL CHECK (judge_provider IN ('judge0_cloud','judge0_selfhosted','fake')),  -- v0.5 as migrated
  queue_name text NOT NULL CHECK (queue_name IN ('judge_assessment','judge_submit','judge_run')),  -- v0.5 as migrated
  idempotency_key     text        NOT NULL,
  similarity_flag     boolean     NOT NULL DEFAULT false,           -- cohort MOSS/JPlag pass (advisory)
  queued_at           timestamptz NOT NULL DEFAULT now(),
  started_at          timestamptz NULL,
  completed_at        timestamptz NULL,
  max_score numeric(7,2) NULL,  -- v0.5 added in migration
  normalized_sha256 bytea NULL CHECK (normalized_sha256 IS NULL OR octet_length(normalized_sha256) = 32),  -- v0.5 added in migration
  retry_count smallint NOT NULL DEFAULT 0,  -- v0.5 added in migration
  notice text NULL,  -- v0.5 added in migration
  UNIQUE (user_id, idempotency_key),
  CONSTRAINT ck_cs_custom_run CHECK (mode = 'run' OR custom_input IS NULL)  -- v0.5 added in migration
);
CREATE INDEX ix_cs_user_problem ON code_submissions (user_id, coding_problem_id, queued_at DESC);
CREATE INDEX ix_cs_attempt ON code_submissions (attempt_id) WHERE attempt_id IS NOT NULL;
CREATE INDEX ix_cs_pending ON code_submissions (queued_at) WHERE status IN ('queued','running');
CREATE INDEX ix_cs_similarity ON code_submissions (coding_problem_id, normalized_sha256) WHERE mode = 'submit';  -- v0.5 added in migration

-- RLS: U | Retention: as code_submissions | PII: P1
CREATE TABLE submission_results (
  id                  uuid PRIMARY KEY,
  code_submission_id  uuid        NOT NULL REFERENCES code_submissions(id) ON DELETE CASCADE,
  user_id             uuid        NOT NULL,
  organization_id     uuid        NULL,
  test_case_id        uuid        NULL REFERENCES coding_test_cases(id),   -- NULL for custom-input run
  ordinal             smallint    NOT NULL,
  is_hidden           boolean     NOT NULL,
  verdict             text        NOT NULL CHECK (verdict IN ('AC','WA','TLE','MLE','RE','CE','IE','SKIPPED')),
  time_ms             int         NULL,
  memory_kb           int         NULL,
  exit_code           smallint    NULL,
  stdout_excerpt text NULL CHECK (stdout_excerpt IS NULL OR octet_length(stdout_excerpt) <= 4096),  -- v0.5 as migrated; samples/custom runs only (≤ 4 KiB)
  judge_token         text        NULL,
  weight_awarded      numeric(6,2) NOT NULL DEFAULT 0,
  UNIQUE (code_submission_id, ordinal),
  CONSTRAINT ck_sr_hidden_output CHECK (NOT is_hidden OR stdout_excerpt IS NULL)
);
```

---

## 11. Commerce and entitlements (`commerce`, `entitlements` modules)

```sql
-- RLS: TN (org-specific products possible) | Retention: R-FIN | PII: P0
CREATE TABLE products (
  id               uuid PRIMARY KEY,
  organization_id  uuid        NULL REFERENCES organizations(id),
  sku citext NOT NULL UNIQUE CHECK (sku ~ '^[A-Za-z0-9][A-Za-z0-9-]{1,63}$'),  -- v0.5 as migrated
  name text NOT NULL CHECK (char_length(name) BETWEEN 2 AND 200),  -- v0.5 as migrated
  -- v0.3: PRD FR-COM-001 vocabulary (contract-reconciliation §7). extra_learner_seat reserved (Phase 3 buddy seat).
  product_kind     text        NOT NULL CHECK (product_kind IN ('free_resource','free_course','course','bundle',
                                   'subscription_plan','placement_package','mock_pack','institution_seat','extra_learner_seat')),
  description_md   text        NULL,
  sac_code         text        NOT NULL DEFAULT '9992',
  gst_rate         numeric(5,2) NOT NULL DEFAULT 18.00 CHECK (gst_rate BETWEEN 0 AND 28),
  refund_policy_key text       NOT NULL,                         -- same wording on marketing + Terms
  status           text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','retired')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- (CCP-5) RLS: TN | Retention: R-FIN | PII: P0
CREATE TABLE product_items (
  id               uuid PRIMARY KEY,
  product_id       uuid        NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  organization_id  uuid        NULL REFERENCES organizations(id),
  item_type        text        NOT NULL CHECK (item_type IN ('course','test','company_path','topic_practice','feature')),
  course_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  test_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  company_path_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  topic_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  feature_key text NULL CHECK (feature_key ~ '^[a-z][a-z0-9_]{1,62}$'),  -- v0.5 as migrated; 'mentor_sessions','all_courses','all_tests'
  quantity int NULL CHECK (quantity > 0),  -- v0.5 as migrated; e.g. 4 mentor sessions
  unit_price_paise bigint NULL CHECK (unit_price_paise >= 0),  -- v0.5 added in migration
  CONSTRAINT ck_pi_ref CHECK (num_nonnulls(course_id, test_id, company_path_id, topic_id, feature_key) = 1),
  CONSTRAINT ck_pi_type CHECK ( (item_type = 'course' AND course_id IS NOT NULL) OR (item_type = 'test' AND test_id IS NOT NULL) OR (item_type = 'company_path' AND company_path_id IS NOT NULL) OR (item_type = 'topic_practice' AND topic_id IS NOT NULL) OR (item_type = 'feature' AND feature_key IS NOT NULL))  -- v0.5 added in migration
);
CREATE UNIQUE INDEX ux_pi ON product_items (product_id, item_type,
  coalesce(course_id, test_id, company_path_id, topic_id)::text, coalesce(feature_key, ''));
CREATE INDEX ix_pi_course ON product_items (course_id) WHERE course_id IS NOT NULL;
CREATE INDEX ix_pi_test ON product_items (test_id) WHERE test_id IS NOT NULL;
CREATE UNIQUE INDEX ux_pi ON product_items (product_id, item_type, (coalesce(course_id, test_id, company_path_id, topic_id)::text), (coalesce(feature_key, '')));  -- v0.5 added in migration
CREATE INDEX ix_pi_path ON product_items (company_path_id) WHERE company_path_id IS NOT NULL;  -- v0.5 added in migration
CREATE INDEX ix_pi_topic ON product_items (topic_id) WHERE topic_id IS NOT NULL;  -- v0.5 added in migration
CREATE INDEX ix_pi_feature ON product_items (feature_key) WHERE feature_key IS NOT NULL;  -- v0.5 added in migration

-- RLS: TN | Retention: R-FIN | PII: P0
CREATE TABLE plans (
  id                    uuid PRIMARY KEY,
  product_id            uuid        NOT NULL REFERENCES products(id),
  organization_id       uuid        NULL REFERENCES organizations(id),
  code                  citext      NOT NULL UNIQUE,
  billing_type          text        NOT NULL CHECK (billing_type IN ('one_time','recurring')),
  interval_unit         text        NULL CHECK (interval_unit IN ('month','year')),
  interval_count        smallint    NULL CHECK (interval_count BETWEEN 1 AND 12),
  access_duration_days  int         NULL CHECK (access_duration_days > 0),
  trial_days            smallint    NOT NULL DEFAULT 0,
  gateway_plan_ids      jsonb       NOT NULL DEFAULT '{}',      -- {"razorpay":"plan_...","cashfree":"..."}
  status                text        NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','retired')),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_plan_shape CHECK (
    (billing_type = 'one_time'  AND access_duration_days IS NOT NULL AND interval_unit IS NULL) OR
    (billing_type = 'recurring' AND interval_unit IS NOT NULL AND interval_count IS NOT NULL))
);
CREATE INDEX ix_plans_product ON plans (product_id);  -- v0.5 added in migration

-- RLS: TN | Retention: R-FIN | PII: P0
CREATE TABLE prices (
  id                 uuid PRIMARY KEY,
  plan_id            uuid        NOT NULL REFERENCES plans(id),
  organization_id    uuid        NULL REFERENCES organizations(id),
  currency           char(3)     NOT NULL DEFAULT 'INR' CHECK (currency = 'INR'),
  amount_paise       bigint      NOT NULL CHECK (amount_paise > 0),
  tax_inclusive      boolean     NOT NULL DEFAULT true,
  is_recurring       boolean     NOT NULL,                       -- denormalised from plan for the CHECK
  valid_from         timestamptz NOT NULL DEFAULT now(),
  valid_until        timestamptz NULL,
  is_active          boolean     NOT NULL DEFAULT true,
  created_by         uuid        NOT NULL REFERENCES users(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_price_mandate CHECK (NOT is_recurring OR amount_paise <= 1500000),   -- ₹15,000 e-mandate no-AFA limit
  CONSTRAINT ck_price_window CHECK (valid_until IS NULL OR valid_until > valid_from)
);
CREATE INDEX ix_prices_plan_active ON prices (plan_id) WHERE is_active;
-- No overlapping active windows per plan:
ALTER TABLE prices ADD CONSTRAINT ex_price_overlap EXCLUDE USING gist
  (plan_id WITH =, tstzrange(valid_from, coalesce(valid_until, 'infinity')) WITH &&) WHERE (is_active);

-- RLS: TN | Retention: R-FIN | PII: P0
CREATE TABLE coupons (
  id                    uuid PRIMARY KEY,
  organization_id       uuid        NULL REFERENCES organizations(id),
  code citext NOT NULL UNIQUE CHECK (code ~ '^[A-Za-z0-9_-]{3,32}$'),  -- v0.5 as migrated
  discount_type         text        NOT NULL CHECK (discount_type IN ('percent','flat','free_access')),
  percent_off           numeric(5,2) NULL CHECK (percent_off > 0 AND percent_off <= 100),
  amount_off_paise      bigint      NULL CHECK (amount_off_paise > 0),
  applicable_product_ids uuid[]     NOT NULL DEFAULT '{}',        -- empty = all
  min_order_paise       bigint      NULL,
  max_redemptions int NULL CHECK (max_redemptions > 0),  -- v0.5 as migrated
  per_user_limit smallint NOT NULL DEFAULT 1 CHECK (per_user_limit >= 1),  -- v0.5 as migrated
  redeemed_count        int         NOT NULL DEFAULT 0,
  valid_from            timestamptz NOT NULL,
  valid_until           timestamptz NULL,
  first_time_only       boolean     NOT NULL DEFAULT false,
  status                text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','expired')),
  created_by            uuid        NOT NULL REFERENCES users(id),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_coupon_shape CHECK (
    (discount_type = 'percent' AND percent_off IS NOT NULL AND amount_off_paise IS NULL) OR
    (discount_type = 'flat' AND amount_off_paise IS NOT NULL AND percent_off IS NULL) OR
    (discount_type = 'free_access')),
  CONSTRAINT ck_coupon_cap CHECK (max_redemptions IS NULL OR redeemed_count <= max_redemptions)
);

-- RLS: O | Retention: R-FIN | PII: P1
CREATE TABLE coupon_redemptions (
  id                    uuid PRIMARY KEY,
  coupon_id             uuid        NOT NULL REFERENCES coupons(id),
  user_id               uuid        NOT NULL REFERENCES users(id),
  order_id              uuid        NOT NULL REFERENCES orders(id),
  discount_paise        bigint      NOT NULL CHECK (discount_paise >= 0),
  status                text        NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved','consumed','released')),
  reserved_until        timestamptz NOT NULL,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (coupon_id, order_id)
);
CREATE INDEX ix_cr_coupon_user ON coupon_redemptions (coupon_id, user_id) WHERE status IN ('reserved','consumed');

-- RLS: custom — USING (user_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) OR app.is_platform())
-- Retention: R-FIN | PII: P2/P3 (billing name, GSTIN)
CREATE TABLE orders (
  id                 uuid PRIMARY KEY,
  order_number       text        NOT NULL UNIQUE,                 -- 'TD-O-2026-00001234'
  user_id            uuid        NULL REFERENCES users(id),        -- NULL for B2B institution orders
  organization_id    uuid        NULL REFERENCES organizations(id),
  status             text        NOT NULL DEFAULT 'created' CHECK (status IN ('created','pending_payment','paid','failed',
                                    'expired','cancelled','refunded','partially_refunded')),
  currency           char(3)     NOT NULL DEFAULT 'INR',
  subtotal_paise     bigint      NOT NULL CHECK (subtotal_paise >= 0),
  discount_paise     bigint      NOT NULL DEFAULT 0 CHECK (discount_paise >= 0),
  tax_paise          bigint      NOT NULL CHECK (tax_paise >= 0),
  total_paise        bigint      NOT NULL CHECK (total_paise >= 0),
  gateway            text        NULL CHECK (gateway IN ('razorpay','cashfree','offline_po')),
  gateway_order_id   text        NULL,
  subscription_id    uuid        NULL REFERENCES subscriptions(id),
  idempotency_key    text        NOT NULL,
  billing_name       text        NULL,
  billing_gstin text NULL CHECK (billing_gstin ~ '^[0-9]{2}[A-Z0-9]{13}$'),  -- v0.5 as migrated
  place_of_supply    char(2)     NULL,                             -- GST state code
  expires_at         timestamptz NOT NULL,
  paid_at            timestamptz NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_order_total CHECK (total_paise = subtotal_paise - discount_paise + tax_paise),  -- subtotal is pre-tax (inclusive prices are split at order time)
  CONSTRAINT ck_order_owner CHECK (user_id IS NOT NULL OR organization_id IS NOT NULL),
  CONSTRAINT ck_order_paid CHECK (status NOT IN ('paid','refunded','partially_refunded') OR paid_at IS NOT NULL),
  refunded_paise     bigint      NOT NULL DEFAULT 0,             -- v0.6 commerce_0003 (COM-11/ADM-24): sum of approved/processing/processed refunds, reserved at approval under the order lock, released on provider failure
  CONSTRAINT ck_order_refunded CHECK (refunded_paise >= 0 AND refunded_paise <= total_paise)  -- v0.6 commerce_0003
);
CREATE UNIQUE INDEX ux_orders_gateway ON orders (gateway, gateway_order_id) WHERE gateway_order_id IS NOT NULL;
CREATE UNIQUE INDEX ux_orders_idem ON orders ((coalesce(user_id, organization_id)), idempotency_key);  -- v0.5 as migrated
CREATE INDEX ix_orders_pending ON orders (created_at) WHERE status = 'pending_payment';
CREATE INDEX ix_orders_user ON orders (user_id, created_at DESC);

-- RLS: as orders | Retention: R-FIN | PII: P0
CREATE TABLE order_items (
  id                uuid PRIMARY KEY,
  order_id          uuid        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  user_id           uuid        NULL,
  organization_id   uuid        NULL,
  product_id        uuid        NOT NULL REFERENCES products(id),
  plan_id           uuid        NOT NULL REFERENCES plans(id),
  price_id          uuid        NOT NULL REFERENCES prices(id),
  quantity          int         NOT NULL DEFAULT 1 CHECK (quantity >= 1),
  unit_amount_paise bigint      NOT NULL,
  discount_paise    bigint      NOT NULL DEFAULT 0,
  taxable_paise     bigint      NOT NULL,
  cgst_paise        bigint      NOT NULL DEFAULT 0,
  sgst_paise        bigint      NOT NULL DEFAULT 0,
  igst_paise        bigint      NOT NULL DEFAULT 0,
  total_paise       bigint      NOT NULL,
  gst_rate          numeric(5,2) NOT NULL,
  sac_code          text        NOT NULL,
  CONSTRAINT ck_oi_gst CHECK ((igst_paise = 0) OR (cgst_paise = 0 AND sgst_paise = 0))
);
CREATE INDEX ix_oi_order ON order_items (order_id);

-- RLS: as orders | Retention: R-FIN | PII: P3 (instrument metadata; never PAN/CVV)
CREATE TABLE payments (
  id                   uuid PRIMARY KEY,
  order_id             uuid        NULL REFERENCES orders(id),
  subscription_id      uuid        NULL REFERENCES subscriptions(id),
  user_id              uuid        NULL REFERENCES users(id),
  organization_id      uuid        NULL REFERENCES organizations(id),
  gateway              text        NOT NULL CHECK (gateway IN ('razorpay','cashfree','offline_po')),
  gateway_payment_id   text        NOT NULL,
  method               text        NULL CHECK (method IN ('upi','card','netbanking','wallet','emandate','bank_transfer','emi')),
  status               text        NOT NULL CHECK (status IN ('created','authorized','captured','failed','refunded','partially_refunded')),
  amount_paise         bigint      NOT NULL CHECK (amount_paise > 0),
  fee_paise            bigint      NULL,
  tax_on_fee_paise     bigint      NULL,
  card_last4           char(4)     NULL,
  card_network         text        NULL,
  card_issuer          text        NULL,
  vpa_masked           text        NULL,
  bank_code            text        NULL,
  error_code           text        NULL,
  error_description    text        NULL,
  authorized_at        timestamptz NULL,
  captured_at          timestamptz NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (gateway, gateway_payment_id),
  CONSTRAINT ck_pay_target CHECK (order_id IS NOT NULL OR subscription_id IS NOT NULL)
);
CREATE INDEX ix_pay_order ON payments (order_id);
CREATE INDEX ix_pay_sub ON payments (subscription_id) WHERE subscription_id IS NOT NULL;

-- RLS: NONE (system-only, platform finance) | Retention: R-FIN (payload PII scrubbed after 180 days) | PII: P3/P4
-- RLS (as migrated): platform-only policy p_platform (app.is_platform()); td_app DELETE/TRUNCATE revoked
CREATE TABLE payment_webhook_events (
  id                 uuid PRIMARY KEY,
  gateway            text        NOT NULL CHECK (gateway IN ('razorpay','cashfree')),
  event_id           text        NOT NULL,                        -- X-Razorpay-Event-Id
  event_type         text        NOT NULL,
  signature_valid    boolean     NOT NULL,
  payload            jsonb       NOT NULL,
  payload_sha256     bytea       NOT NULL CHECK (octet_length(payload_sha256) = 32),
  gateway_created_at timestamptz NULL,
  received_at        timestamptz NOT NULL DEFAULT now(),
  status             text        NOT NULL DEFAULT 'received' CHECK (status IN ('received','processing','processed','ignored','failed')),
  attempts           smallint    NOT NULL DEFAULT 0,
  next_attempt_at    timestamptz NULL,                           -- v0.6 commerce_0003 (COM-13): exponential backoff for 72 h after receipt, then 'failed'
  last_error         text        NULL,
  processed_at       timestamptz NULL,
  order_id           uuid        NULL REFERENCES orders(id),
  payment_id         uuid        NULL REFERENCES payments(id),
  subscription_id    uuid        NULL REFERENCES subscriptions(id),
  is_stale           boolean     NOT NULL DEFAULT false,         -- monitoring flag only (> 5 min old); stale events are processed via re-fetch, never rejected
  refetched_at       timestamptz NULL,                          -- v0.4 (CPR-SCH-13): provider re-fetch time
  refetch_status     text        NULL CHECK (refetch_status IN ('ok','failed','not_required')),   -- failed ⇒ retry with backoff, no state change
  UNIQUE (gateway, event_id)
);
CREATE INDEX ix_pwe_status ON payment_webhook_events (status, received_at) WHERE status IN ('received','processing','failed');

-- RLS: O | Retention: R-FIN | PII: P1
CREATE TABLE subscriptions (
  id                        uuid PRIMARY KEY,
  user_id                   uuid        NOT NULL REFERENCES users(id),
  plan_id                   uuid        NOT NULL REFERENCES plans(id),
  price_id                  uuid        NOT NULL REFERENCES prices(id),
  gateway                   text        NOT NULL CHECK (gateway IN ('razorpay','cashfree')),
  gateway_subscription_id   text        NOT NULL,
  status                    text        NOT NULL CHECK (status IN ('created','authenticated','active','pending','halted',
                                           'paused','cancelled','completed','expired')),
  mandate_max_amount_paise  bigint      NOT NULL CHECK (mandate_max_amount_paise <= 1500000),
  current_period_start      timestamptz NULL,
  current_period_end        timestamptz NULL,
  next_charge_at            timestamptz NULL,
  pre_debit_notified_at     timestamptz NULL,
  total_count               int         NULL,
  paid_count                int         NOT NULL DEFAULT 0,
  cancel_at_period_end      boolean     NOT NULL DEFAULT false,
  cancelled_at              timestamptz NULL,
  cancel_reason             text        NULL,
  grace_until               timestamptz NULL,
  billing_name              text        NULL,                    -- v0.6 commerce_0003 (COM-10): buyer billing details for every debit invoice
  billing_state_code        text        NULL CHECK (billing_state_code ~ '^[0-9]{2}$'),  -- v0.6 place of supply
  billing_gstin             text        NULL CHECK (billing_gstin ~ '^[0-9]{2}[A-Z0-9]{13}$'),  -- v0.6
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  UNIQUE (gateway, gateway_subscription_id)
);
CREATE INDEX ix_sub_user ON subscriptions (user_id);
CREATE INDEX ix_sub_next_charge ON subscriptions (next_charge_at) WHERE status = 'active';

-- RLS: as orders | Retention: R-FIN | PII: P1
CREATE TABLE refunds (
  id                 uuid PRIMARY KEY,
  payment_id         uuid        NOT NULL REFERENCES payments(id),
  order_id           uuid        NOT NULL REFERENCES orders(id),
  user_id            uuid        NULL REFERENCES users(id),
  organization_id    uuid        NULL REFERENCES organizations(id),
  gateway_refund_id  text        NULL,
  amount_paise       bigint      NOT NULL CHECK (amount_paise > 0),
  reason_code        text        NOT NULL CHECK (reason_code IN ('within_policy_window','content_issue','duplicate_payment',
                                   'service_failure','goodwill','chargeback','other','price_adjustment')),  -- v0.6 commerce_0003: + price_adjustment (finance-only, keeps access; COM-01)
  reason_note        text        NULL,
  consumption_pct    numeric(5,2) NULL,                          -- refund rule input (e.g. < 20 % consumed)
  status             text        NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','approved','rejected','processing','processed','failed')),
  requested_by       uuid        NOT NULL REFERENCES users(id),
  approved_by        uuid        NULL REFERENCES users(id),
  approval_request_id uuid NULL REFERENCES approval_requests(id),  -- v0.5 as migrated; v0.3: FK → approval_requests(id) (added in §13); Dual refunds
  processed_at       timestamptz NULL,
  submit_attempts    smallint    NOT NULL DEFAULT 0,             -- v0.6 commerce_0003 (COM-02): provider-submit retry bookkeeping
  next_submit_at     timestamptz NULL,                           -- v0.6
  last_error         text        NULL,                           -- v0.6
  idempotency_key    text        NOT NULL UNIQUE,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_refund_approver CHECK (approved_by IS NULL OR approved_by <> requested_by OR reason_code = 'within_policy_window'),
  -- v0.3: goodwill refunds are always Dual (role matrix §5). The > ₹25,000 Dual rule is a service rule driven by
  -- policy key commerce.refund.dual_approval_above_paise (default 2500000) and also sets approval_request_id.
  CONSTRAINT ck_refund_goodwill_dual CHECK (reason_code <> 'goodwill' OR status IN ('requested','rejected') OR approval_request_id IS NOT NULL)
);
CREATE UNIQUE INDEX ux_refund_gateway ON refunds (gateway_refund_id) WHERE gateway_refund_id IS NOT NULL;
CREATE INDEX ix_refund_order ON refunds (order_id);  -- v0.5 added in migration
CREATE INDEX ix_refund_unsubmitted ON refunds (next_submit_at) WHERE status = 'approved' AND gateway_refund_id IS NULL;  -- v0.6 commerce_0003
CREATE INDEX ix_refund_processing ON refunds (created_at) WHERE status = 'processing';  -- v0.6 commerce_0003

-- (CCP-5) RLS: NONE | Retention: R-FIN | PII: P0
-- RLS (as migrated): platform-only policy p_platform (app.is_platform())
CREATE TABLE invoice_sequences (
  series text NOT NULL CHECK (series IN ('TD','TDCN')),  -- v0.5 as migrated; 'TD' (tax invoice), 'TDCN' (credit note)
  fiscal_year text NOT NULL CHECK (fiscal_year ~ '^[0-9]{4}-[0-9]{2}$'),  -- v0.5 as migrated; '2026-27'
  next_value   bigint   NOT NULL DEFAULT 1 CHECK (next_value >= 1),
  PRIMARY KEY (series, fiscal_year)
);

-- Immutable after issue (corrections via credit note). RLS: as orders | Retention: R-FIN | PII: P2/P3
CREATE TABLE invoices (
  id                uuid PRIMARY KEY,
  invoice_number    text        NOT NULL UNIQUE CHECK (char_length(invoice_number) <= 16),  -- GST: ≤16 chars, e.g. 'TD/2627/000123'
  invoice_type      text        NOT NULL CHECK (invoice_type IN ('tax_invoice','credit_note')),
  order_id          uuid        NOT NULL REFERENCES orders(id),
  refund_id         uuid        NULL REFERENCES refunds(id),
  original_invoice_id uuid      NULL REFERENCES invoices(id),
  user_id           uuid        NULL REFERENCES users(id),
  organization_id   uuid        NULL REFERENCES organizations(id),
  seller_gstin      text        NOT NULL,
  buyer_name        text        NOT NULL,
  buyer_gstin       text        NULL,
  buyer_address     jsonb       NULL,
  place_of_supply   char(2)     NOT NULL,
  issue_date        date        NOT NULL,
  taxable_paise     bigint      NOT NULL,
  cgst_paise        bigint      NOT NULL DEFAULT 0,
  sgst_paise        bigint      NOT NULL DEFAULT 0,
  igst_paise        bigint      NOT NULL DEFAULT 0,
  total_paise       bigint      NOT NULL,
  irn               text        NULL,                            -- e-invoice IRN for B2B if applicable
  pdf_s3_key        text        NULL,
  status            text        NOT NULL DEFAULT 'issued' CHECK (status IN ('issued','cancelled')),
  created_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_inv_cn CHECK ((invoice_type = 'credit_note') = (original_invoice_id IS NOT NULL)),
  CONSTRAINT ck_inv_total CHECK (total_paise = taxable_paise + cgst_paise + sgst_paise + igst_paise)  -- v0.5 added in migration
);
CREATE INDEX ix_inv_order ON invoices (order_id);
CREATE UNIQUE INDEX ux_inv_tax_order ON invoices (order_id) WHERE invoice_type = 'tax_invoice' AND status = 'issued';  -- v0.5 added in migration
CREATE UNIQUE INDEX ux_inv_cn_refund ON invoices (refund_id) WHERE refund_id IS NOT NULL;  -- v0.5 added in migration

-- RLS: T | Retention: R-FIN | PII: P2 (contact)
CREATE TABLE institution_contracts (
  id                uuid PRIMARY KEY,
  organization_id   uuid        NOT NULL REFERENCES organizations(id),
  contract_number   text        NOT NULL UNIQUE,
  product_id        uuid        NOT NULL REFERENCES products(id),
  seat_count        int         NOT NULL CHECK (seat_count > 0),
  starts_on         date        NOT NULL,
  ends_on           date        NOT NULL,
  amount_paise      bigint      NOT NULL CHECK (amount_paise >= 0),
  po_number         text        NULL,
  order_id          uuid        NULL REFERENCES orders(id),       -- billing via offline_po order
  dpa_version       text        NOT NULL,                         -- data processing agreement
  dpa_signed_at     timestamptz NOT NULL,
  data_return_days  smallint    NOT NULL DEFAULT 30,
  status            text        NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','expired','terminated')),
  created_by        uuid        NOT NULL REFERENCES users(id),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  price_per_seat_paise bigint NULL CHECK (price_per_seat_paise >= 0),  -- v0.5 added in migration
  billing_schedule text NOT NULL DEFAULT 'upfront' CHECK (billing_schedule IN ('upfront','milestones')),  -- v0.5 added in migration
  grace_days smallint NOT NULL DEFAULT 7 CHECK (grace_days BETWEEN 0 AND 60),  -- v0.5 added in migration
  reassignment_allowance int NOT NULL CHECK (reassignment_allowance >= 0),  -- v0.5 added in migration
  reassignments_used int NOT NULL DEFAULT 0 CHECK (reassignments_used >= 0),  -- v0.5 added in migration
  seats_burned int NOT NULL DEFAULT 0 CHECK (seats_burned >= 0),  -- v0.5 added in migration
  version int NOT NULL DEFAULT 1,  -- v0.5 added in migration
  terminated_at timestamptz NULL,  -- v0.5 added in migration
  CONSTRAINT ck_ic_dates CHECK (ends_on > starts_on),
  CONSTRAINT ck_ic_reassign CHECK (reassignments_used <= reassignment_allowance),  -- v0.5 added in migration
  CONSTRAINT ck_ic_terminated CHECK ((status = 'terminated') = (terminated_at IS NOT NULL))  -- v0.5 added in migration
);
CREATE INDEX ix_ic_org ON institution_contracts (organization_id);  -- v0.5 added in migration

-- Source polymorphism with explicit FKs (exactly one source column set, matching source_type).
-- v0.2 (PRD CCP-05): PRD business vocabulary for source_type, `grace` status + grace_ends_at, consumable quotas.
-- Security never revokes entitlements; restrictions gate them (entitlements.check → ACCOUNT_RESTRICTED).
-- RLS: U | Retention: R-FIN (8 years; evidence of what was sold) | PII: P1
CREATE TABLE entitlements (
  id                        uuid PRIMARY KEY,
  user_id                   uuid        NOT NULL REFERENCES users(id),
  organization_id           uuid        NULL REFERENCES organizations(id),
  product_id                uuid        NULL REFERENCES products(id),
  course_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch); direct grant (free enrolment / admin) without product
  feature_key               text        NULL,
  source_type               text        NOT NULL CHECK (source_type IN ('free_enrolment','purchase','placement_package',
                                           'subscription','coupon_grant','institution_contract','admin_grant','trial')),
  order_item_id             uuid        NULL REFERENCES order_items(id),
  subscription_id           uuid        NULL REFERENCES subscriptions(id),
  institution_contract_id   uuid        NULL REFERENCES institution_contracts(id),
  coupon_redemption_id      uuid        NULL REFERENCES coupon_redemptions(id),
  granted_by                uuid        NULL REFERENCES users(id),       -- admin_grant (and staff-issued trials)
  grant_reason              text        NULL,
  status                    text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','grace','suspended','revoked','expired')),
  starts_at                 timestamptz NOT NULL DEFAULT now(),
  ends_at                   timestamptz NULL,                              -- NULL only for free_enrolment / admin_grant
  grace_ends_at             timestamptz NULL,                              -- BR-ENT-09 (5 d subscription), BR-ENT-17 (contract grace_days)
  mentor_sessions_remaining smallint    NULL CHECK (mentor_sessions_remaining >= 0),
  mocks_remaining           smallint    NULL CHECK (mocks_remaining >= 0),
  resume_reviews_remaining  smallint    NULL CHECK (resume_reviews_remaining >= 0),
  revoked_at                timestamptz NULL,
  revoked_by                uuid        NULL REFERENCES users(id),
  revoke_reason             text        NULL CHECK (revoke_reason IN ('refund','chargeback','contract_end','contract_terminated',
                                           'seat_unassigned','admin','fraud','superseded')),
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_ent_target CHECK (num_nonnulls(product_id, course_id, feature_key) >= 1),
  CONSTRAINT ck_ent_source CHECK (
    (source_type IN ('purchase','placement_package') AND order_item_id IS NOT NULL
                                          AND num_nonnulls(subscription_id, institution_contract_id, coupon_redemption_id) = 0) OR
    (source_type = 'subscription'         AND subscription_id IS NOT NULL
                                          AND num_nonnulls(order_item_id, institution_contract_id, coupon_redemption_id) = 0) OR
    (source_type = 'institution_contract' AND institution_contract_id IS NOT NULL AND organization_id IS NOT NULL
                                          AND num_nonnulls(order_item_id, subscription_id, coupon_redemption_id) = 0) OR
    (source_type = 'coupon_grant'         AND coupon_redemption_id IS NOT NULL
                                          AND num_nonnulls(order_item_id, subscription_id, institution_contract_id) = 0) OR
    (source_type = 'admin_grant'          AND granted_by IS NOT NULL
                                          AND num_nonnulls(order_item_id, subscription_id, institution_contract_id, coupon_redemption_id) = 0) OR
    (source_type IN ('free_enrolment','trial')
                                          AND num_nonnulls(order_item_id, subscription_id, institution_contract_id, coupon_redemption_id) = 0)),
  CONSTRAINT ck_ent_window CHECK (ends_at IS NULL OR ends_at > starts_at),
  CONSTRAINT ck_ent_open_end CHECK (ends_at IS NOT NULL OR source_type IN ('free_enrolment','admin_grant')),
  CONSTRAINT ck_ent_grace CHECK (status <> 'grace' OR grace_ends_at IS NOT NULL),
  CONSTRAINT ck_ent_revoked CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))
);
CREATE UNIQUE INDEX ux_ent_order_item ON entitlements (order_item_id) WHERE order_item_id IS NOT NULL;   -- idempotent fulfilment
CREATE UNIQUE INDEX ux_ent_sub ON entitlements (subscription_id) WHERE subscription_id IS NOT NULL;     -- one rolling entitlement per subscription
CREATE UNIQUE INDEX ux_ent_seat ON entitlements (institution_contract_id, user_id)
  WHERE institution_contract_id IS NOT NULL AND status IN ('active','grace','suspended');
CREATE INDEX ix_ent_user_active ON entitlements (user_id, ends_at) WHERE status IN ('active','grace');
CREATE INDEX ix_ent_contract_active ON entitlements (institution_contract_id) WHERE status IN ('active','grace');  -- seat count
CREATE INDEX ix_ent_expiry ON entitlements (ends_at) WHERE status = 'active' AND ends_at IS NOT NULL;
CREATE INDEX ix_ent_grace ON entitlements (grace_ends_at) WHERE status = 'grace';
CREATE UNIQUE INDEX ux_ent_seat ON entitlements (institution_contract_id, user_id) WHERE institution_contract_id IS NOT NULL AND status IN ('active','grace','suspended');  -- v0.5 added in migration
CREATE UNIQUE INDEX ux_ent_coupon ON entitlements (coupon_redemption_id) WHERE coupon_redemption_id IS NOT NULL;  -- v0.5 added in migration

-- (PRD CCP-05) Append-only entitlement history (grant, extend, grace, suspend, restore, revoke, quota use/credit).
-- RLS: U | Retention: R-FIN | PII: P1
CREATE TABLE entitlement_events (
  id                uuid PRIMARY KEY,
  entitlement_id    uuid        NOT NULL REFERENCES entitlements(id),
  user_id           uuid        NOT NULL REFERENCES users(id),
  organization_id   uuid        NULL REFERENCES organizations(id),
  event_type        text        NOT NULL CHECK (event_type IN ('granted','extended','entered_grace','restored','suspended',
                                    'expired','revoked','quota_consumed','quota_credited','seat_reassigned','fp_extension')),
  from_status       text        NULL,
  to_status         text        NULL,
  delta             jsonb       NOT NULL DEFAULT '{}',          -- e.g. ends_at old/new, quota deltas
  reason            text        NULL,
  actor_type        text        NOT NULL CHECK (actor_type IN ('user','system','gateway')),
  actor_user_id     uuid        NULL REFERENCES users(id),
  source_ref        uuid        NULL,                            -- order / payment / booking / case_decision id
  occurred_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ee_ent ON entitlement_events (entitlement_id, occurred_at);
CREATE INDEX ix_ee_user ON entitlement_events (user_id, occurred_at DESC);
```

---

## 12. Analytics (`analytics` module)

Confirmed by the Analytics Engineer (`analytics-event-schema.md` §1.5, §4.2–4.6, §6, §10 DM-1..12; reconciliation §2.4). Rules for every table here:

* **Identity is server-set.** `user_id`, `organization_id`, `auth_session_id`, `device_id`, `privacy_tier` come from the session, never from the client.
* **No PII** beyond opaque ids: no names, emails, phones, IPs, user agents, answer text or code. Exports/BI use `subject_key = HMAC-SHA256(k_analytics_vN, user_id)` (Brief v0.2 §1).
* **Entity columns are typed uuids without FKs** (partitioned and high-volume tables; content may be deleted independently).
* **RLS family `U`** on every table with `user_id`/`organization_id` (AN DM-10). D2C rows have `organization_id IS NULL`. Cohort tables (no `user_id`) use family `T` with a `NULL`-org platform row.
* **Minors** (`privacy_tier = 'minor'`): learning-purpose data only; no rows in `route_daily_aggregates` or `security_activity_feed_daily` (CHECKs below + ingest drops P-purpose events).
* **Small-cell floors** come from `policy_settings` keys `analytics.k_min.cohort` (10), `analytics.k_min.item` (10), `analytics.k_min.cross_org_display` (50), `analytics.k_min.percentile_reference` (20).

```sql
-- Partitioned monthly on event_ts (derived from UUIDv7 event_id; AN CP-1). Insert ON CONFLICT DO NOTHING = per-event idempotency.
-- RLS: U | Retention: R-AN-RAW (90 days) | PII: P1
CREATE TABLE analytics_events (
  event_id          uuid        NOT NULL,                          -- client UUIDv7 (or server for source='server'); unchanged on retry
  event_ts          timestamptz NOT NULL,                          -- = UUIDv7 ms timestamp of event_id; partition key
  event_type        text        NOT NULL,                          -- 'page.view', 'video.play', 'practice.answered', ...
  schema_version    smallint    NOT NULL,
  source            text        NOT NULL CHECK (source IN ('client','server')),
  purpose           text        NOT NULL CHECK (purpose IN ('learning','product')),   -- L / P purpose (consent A / H)
  user_id           uuid        NOT NULL,
  organization_id   uuid        NULL,                              -- org of the enrolment/entitlement used; NULL for D2C
  auth_session_id   uuid        NULL,                              -- auth_sessions.id (never the token or its hash)
  device_id         uuid        NULL,
  tab_id            uuid        NULL,
  page_instance_id  uuid        NULL,
  seq               int         NULL CHECK (seq >= 0),
  route             text        NULL,                              -- route template, never a raw URL
  surface           text        NULL,
  course_id         uuid        NULL,
  lesson_id         uuid        NULL,
  lesson_asset_id   uuid        NULL,
  topic_id          uuid        NULL,
  question_id       uuid        NULL,
  test_attempt_id   uuid        NULL,
  coding_problem_id uuid        NULL,
  occurred_at       timestamptz NOT NULL,                          -- client wall clock (audit only)
  received_at       timestamptz NOT NULL DEFAULT now(),
  effective_at      timestamptz NOT NULL,                          -- min(occurred_at + skew_ms, received_at); used for all aggregation
  skew_ms           integer     NOT NULL,
  privacy_tier      text        NOT NULL CHECK (privacy_tier IN ('adult','minor')),   -- snapshot at ingest
  ingest_flags      text[]      NOT NULL DEFAULT '{}' CHECK (ingest_flags <@ ARRAY['large_skew','clock_jump','late','seq_gap',
                                   'rate_capped','implausible_clamped']::text[]),
  measurement_version text      NOT NULL DEFAULT 'tm-1.0',
  payload           jsonb       NOT NULL DEFAULT '{}' CHECK (octet_length(payload::text) <= 4096),
  PRIMARY KEY (event_id, event_ts),
  CONSTRAINT ck_aev_minor_purpose CHECK (privacy_tier = 'adult' OR purpose = 'learning')
) PARTITION BY RANGE (event_ts);
CREATE INDEX ix_aev_user_time ON analytics_events (user_id, event_ts);
CREATE INDEX ix_aev_page_seq ON analytics_events (page_instance_id, seq);
CREATE INDEX brin_aev_received ON analytics_events USING brin (received_at);         -- builder watermark
CREATE INDEX ix_aev_user_eff ON analytics_events (user_id, effective_at);  -- v0.5 added in migration

-- Partitioned monthly on event_ts. Narrow typed columns, no JSONB (AN DM-1). RLS: U | Retention: R-AN-HB (35 days) | PII: P1
CREATE TABLE activity_heartbeats (
  event_id          uuid        NOT NULL,
  event_ts          timestamptz NOT NULL,
  user_id           uuid        NOT NULL,
  organization_id   uuid        NULL,
  auth_session_id   uuid        NULL,
  device_id         uuid        NULL,
  tab_id            uuid        NOT NULL,
  page_instance_id  uuid        NOT NULL,
  seq               int         NOT NULL CHECK (seq >= 0),
  effective_at      timestamptz NOT NULL,
  received_at       timestamptz NOT NULL DEFAULT now(),
  kind              text        NOT NULL CHECK (kind IN ('engaged','keepalive')),
  active_ms         int         NOT NULL CHECK (active_ms BETWEEN 0 AND 20000),
  state_bits        smallint    NOT NULL,                          -- bit0 visible, bit1 focused, bit2 input_recent, bit3 media_playing
  surface           text        NOT NULL,                          -- 'video','article','practice','test','coding','browse'
  course_id         uuid        NULL,
  lesson_id         uuid        NULL,
  lesson_asset_id   uuid        NULL,
  question_id       uuid        NULL,
  test_attempt_id   uuid        NULL,
  coding_problem_id uuid        NULL,
  media_position_s  numeric(9,2) NULL,
  media_rate        numeric(3,2) NULL CHECK (media_rate IS NULL OR media_rate BETWEEN 0.25 AND 2.0),
  played_ranges     int4range[] NULL,                              -- deciseconds
  edit_ops          int         NULL CHECK (edit_ops IS NULL OR edit_ops BETWEEN 0 AND 5000),
  scroll_depth_pct  smallint    NULL CHECK (scroll_depth_pct IS NULL OR scroll_depth_pct BETWEEN 0 AND 100),
  input_events      int         NULL CHECK (input_events IS NULL OR input_events BETWEEN 0 AND 1000),
  ingest_flags      text[]      NOT NULL DEFAULT '{}',
  sample_interval_ms int NULL CHECK (sample_interval_ms IS NULL OR sample_interval_ms BETWEEN 1000 AND 330000),  -- v0.5 added in migration
  route text NULL,  -- v0.5 added in migration
  privacy_tier text NOT NULL DEFAULT 'minor' CHECK (privacy_tier IN ('adult','minor')),  -- v0.5 added in migration
  topic_id uuid NULL,  -- v0.5 added in migration
  editor_focused boolean NULL,  -- v0.5 added in migration
  PRIMARY KEY (event_id, event_ts)
) PARTITION BY RANGE (event_ts);
CREATE INDEX ix_hb_user_time ON activity_heartbeats (user_id, event_ts);
CREATE INDEX ix_hb_page_seq ON activity_heartbeats (page_instance_id, seq);
CREATE INDEX ix_hb_user_device_eff ON activity_heartbeats (user_id, device_id, effective_at) WHERE kind = 'engaged';  -- engaged-bucket feed (SH-01, H3)
CREATE INDEX brin_hb_received ON activity_heartbeats USING brin (received_at);
CREATE INDEX ix_hb_user_eff ON activity_heartbeats (user_id, effective_at);  -- v0.5 added in migration

-- Partitioned monthly on started_at (AN DM-2). RLS: U | Retention: R-AN-INT (13 months) | PII: P1
CREATE TABLE engagement_intervals (
  id                uuid        NOT NULL,
  started_at        timestamptz NOT NULL,
  ended_at          timestamptz NULL,                              -- NULL while open
  user_id           uuid        NOT NULL,
  organization_id   uuid        NULL,
  auth_session_id   uuid        NULL,
  device_id         uuid        NULL,
  tab_id            uuid        NOT NULL,
  page_instance_id  uuid        NOT NULL,
  surface           text        NOT NULL,
  mode text NOT NULL CHECK (mode IN ('interactive','mixed','media')),  -- v0.5 as migrated; interactive / passive_media / reading ...
  course_id         uuid        NULL,
  lesson_id         uuid        NULL,
  lesson_asset_id   uuid        NULL,
  topic_id          uuid        NULL,
  question_id       uuid        NULL,
  test_attempt_id   uuid        NULL,
  coding_problem_id uuid        NULL,
  active_s numeric(10,3) NOT NULL DEFAULT 0 CHECK (active_s >= 0),  -- v0.5 as migrated
  heartbeat_count   int         NOT NULL DEFAULT 0,
  close_reason text NULL CHECK (close_reason IN ('idle','hidden','blur','pagehide','navigate','grace_timeout', 'session_ended','mode_change','gap')),  -- v0.5 as migrated
  flags             text[]      NOT NULL DEFAULT '{}' CHECK (flags <@ ARRAY['hidden_playback','clock_jump','seq_gap','late']::text[]),
  is_open           boolean     NOT NULL DEFAULT true,
  measurement_version text      NOT NULL,                          -- 'tm-1.0'
  last_sample_at timestamptz NOT NULL,  -- v0.5 added in migration
  provisional_end timestamptz NOT NULL,  -- v0.5 added in migration
  privacy_tier text NOT NULL CHECK (privacy_tier IN ('adult','minor')),  -- v0.5 added in migration
  built_at timestamptz NOT NULL DEFAULT now(),  -- v0.5 added in migration
  PRIMARY KEY (id, started_at),
  CONSTRAINT ck_ei_open CHECK (is_open = (ended_at IS NULL)),
  CONSTRAINT ck_ei_order CHECK (ended_at IS NULL OR ended_at >= started_at)
) PARTITION BY RANGE (started_at);
CREATE INDEX ix_ei_user_time ON engagement_intervals (user_id, started_at);
CREATE INDEX ix_ei_open ON engagement_intervals (page_instance_id) WHERE is_open;
CREATE INDEX ix_ei_page ON engagement_intervals (page_instance_id);  -- v0.5 added in migration

-- Grain: user × IST date × (entity_kind, entity_id) (AN DM-3). entity_kind '_total' uses entity_id = user_id.
-- RLS: U | Retention: R-AN-AGG | PII: P1
CREATE TABLE daily_learning_aggregates (
  user_id               uuid        NOT NULL,
  activity_date         date        NOT NULL,                       -- Asia/Kolkata calendar day (AN CP-9)
  entity_kind text NOT NULL CHECK (entity_kind IN ('_total','course','lesson','topic','test_attempt', 'coding_problem','organization','lesson_asset')),  -- v0.5 as migrated
  entity_id             uuid        NOT NULL,
  organization_id       uuid        NULL,
  course_id             uuid        NULL,
  topic_id              uuid        NULL,
  category_topic_id     uuid        NULL,                           -- root 'subject' node of topics
  m1_session_elapsed_s  int         NULL CHECK (entity_kind = '_total' OR m1_session_elapsed_s IS NULL),
  m2_active_s           int         NOT NULL DEFAULT 0,
  m3_video_playback_s   int         NOT NULL DEFAULT 0,
  m4_assessment_s       int         NOT NULL DEFAULT 0,
  m5_learning_s         int         NOT NULL DEFAULT 0,
  questions_attempted   int         NOT NULL DEFAULT 0,
  questions_correct     int         NOT NULL DEFAULT 0,
  first_attempt_correct int         NOT NULL DEFAULT 0,
  code_runs             int         NOT NULL DEFAULT 0,
  code_submissions      int         NOT NULL DEFAULT 0,
  code_accepted         int         NOT NULL DEFAULT 0,
  lessons_completed     int         NOT NULL DEFAULT 0,
  video_coverage_gain_s int         NOT NULL DEFAULT 0,
  implausible_day       boolean     NOT NULL DEFAULT false,         -- M2 > 16 h; excluded from cohorts/leaderboards
  privacy_tier          text        NOT NULL CHECK (privacy_tier IN ('adult','minor')),
  measurement_version   text        NOT NULL,
  is_frozen             boolean     NOT NULL DEFAULT false,         -- frozen at D+4
  computed_at           timestamptz NOT NULL DEFAULT now(),
  assessment_active_s int NOT NULL DEFAULT 0,  -- v0.5 added in migration
  PRIMARY KEY (user_id, activity_date, entity_kind, entity_id),
  CONSTRAINT ck_dla_order CHECK (m5_learning_s <= m2_active_s OR entity_kind <> '_total')  -- v0.5 added in migration
);
CREATE INDEX ix_dla_org_date ON daily_learning_aggregates (organization_id, activity_date) WHERE organization_id IS NOT NULL;
CREATE INDEX ix_dla_course_date ON daily_learning_aggregates (course_id, activity_date) WHERE course_id IS NOT NULL;
CREATE INDEX ix_dla_kind_date ON daily_learning_aggregates (entity_kind, activity_date);  -- v0.5 added in migration

-- (AN CP-2) A table, not a materialized view: RLS does not apply to MVs. RLS: U | Retention: R-AN-AGG | PII: P1
CREATE TABLE weekly_learning_aggregates (
  user_id              uuid        NOT NULL,
  iso_week_start       date        NOT NULL CHECK (extract(isodow FROM iso_week_start) = 1),   -- Monday, IST
  entity_kind text NOT NULL CHECK (entity_kind IN ('_total','course','topic','organization')),  -- v0.5 as migrated
  entity_id            uuid        NOT NULL,
  organization_id      uuid        NULL,
  m2_active_s          int         NOT NULL DEFAULT 0,
  m3_video_playback_s  int         NOT NULL DEFAULT 0,
  m4_assessment_s      int         NOT NULL DEFAULT 0,
  m5_learning_s        int         NOT NULL DEFAULT 0,
  active_days          smallint    NOT NULL DEFAULT 0 CHECK (active_days BETWEEN 0 AND 7),   -- days with M5 ≥ 10 min
  privacy_tier         text        NOT NULL CHECK (privacy_tier IN ('adult','minor')),
  measurement_version  text        NOT NULL,
  computed_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, iso_week_start, entity_kind, entity_id)
);
CREATE INDEX ix_wla_org_week ON weekly_learning_aggregates (organization_id, iso_week_start) WHERE organization_id IS NOT NULL;

-- (AN CP-2) Non-identifying cohort rollups; cells below analytics.k_min.cohort are stored with suppressed = true and nulls.
-- RLS: T (organization_id; NULL = platform-wide rows readable by platform roles and, for display, through k-checked API) | Retention: R-AN-COHORT | PII: P0
CREATE TABLE cohort_learning_aggregates (
  id                   uuid PRIMARY KEY,
  organization_id      uuid        NULL,                           -- NULL = platform-wide cohort
  batch_id             uuid        NULL,
  period_kind          text        NOT NULL CHECK (period_kind IN ('day','week')),
  period_start         date        NOT NULL,
  entity_kind          text        NOT NULL CHECK (entity_kind IN ('_total','course','topic','category','test')),
  entity_id            uuid        NULL,
  learners_enrolled    int         NULL,
  learners_active      int         NULL,                           -- M5 > 0
  m5_sum_s             bigint      NULL,
  m5_p50_s             int         NULL,
  m5_p90_s             int         NULL,
  completions          int         NULL,
  accuracy             numeric(5,4) NULL,
  score_deciles        numeric(7,2)[] NULL,                        -- test score distribution
  suppressed           boolean     NOT NULL DEFAULT false,         -- k-rule
  measurement_version  text        NOT NULL,
  computed_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (organization_id, batch_id, period_kind, period_start, entity_kind, entity_id),
  CONSTRAINT ck_cla_suppressed CHECK (NOT suppressed OR (learners_active IS NULL AND m5_sum_s IS NULL AND m5_p50_s IS NULL AND m5_p90_s IS NULL AND accuracy IS NULL))  -- v0.5 added in migration
);
CREATE INDEX ix_cla_org_period ON cohort_learning_aggregates (organization_id, period_start);

-- (AN CP-2) Product analytics; adults with analytics_product consent only. RLS: NONE (no user_id; platform/content roles via API) | Retention: R-AN-COHORT | PII: P0
CREATE TABLE route_daily_aggregates (
  route                text        NOT NULL,                       -- route template
  activity_date        date        NOT NULL,
  views                int         NOT NULL DEFAULT 0,
  unique_users_hll     bytea       NULL,                           -- HyperLogLog sketch
  unique_users_est     int         NULL,
  m2_p50_s             int         NULL,
  bounce_count         int         NOT NULL DEFAULT 0,
  buffering_events     int         NOT NULL DEFAULT 0,
  computed_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (route, activity_date)
);

-- (AN CP-2) Merged playback ranges per user × asset. RLS: U | Retention: R-AN-AGG | PII: P1
CREATE TABLE video_watch_coverage (
  user_id              uuid        NOT NULL,
  lesson_asset_id      uuid        NOT NULL,
  organization_id      uuid        NULL,
  covered_ranges       int4range[] NOT NULL DEFAULT '{}',          -- merged, deciseconds
  coverage_pct         numeric(5,2) NOT NULL DEFAULT 0 CHECK (coverage_pct BETWEEN 0 AND 100),
  duration_s int NULL CHECK (duration_s IS NULL OR duration_s > 0),  -- v0.5 as migrated; copied from lesson_assets.duration_seconds
  last_position_s      int         NULL,
  updated_at           timestamptz NOT NULL DEFAULT now(),
  lesson_id uuid NULL,  -- v0.5 added in migration
  covered_s numeric(10,1) NOT NULL DEFAULT 0,  -- v0.5 added in migration
  PRIMARY KEY (user_id, lesson_asset_id)
);

-- (AN CP-11; replaces architect user_topic_mastery and PRD mastery_scores) Single writer: analytics. Placement reads via service.
-- RLS: U | Retention: R-AN-AGG | PII: P1 (learning delivery only; never used for risk or marketing)
CREATE TABLE topic_mastery (
  user_id              uuid        NOT NULL REFERENCES users(id),
  topic_id uuid NOT NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  organization_id      uuid        NULL REFERENCES organizations(id),
  theta                numeric(6,3) NOT NULL DEFAULT 0,             -- Elo-style ability (analytics §6.2)
  n_eff                numeric(8,2) NOT NULL DEFAULT 0,             -- effective evidence count
  attempts             int         NOT NULL DEFAULT 0,
  correct              int         NOT NULL DEFAULT 0,
  weighted_accuracy    numeric(5,4) NOT NULL DEFAULT 0 CHECK (weighted_accuracy BETWEEN 0 AND 1),
  band text NOT NULL DEFAULT 'not_started' CHECK (band IN ('not_started','insufficient_data','weak', 'developing','proficient','strong')),  -- v0.5 as migrated
  avg_time_ms          int         NULL,
  last_practiced_at    timestamptz NULL,
  model_version        text        NOT NULL,                        -- 'mastery-1.0'
  updated_at           timestamptz NOT NULL DEFAULT now(),
  wa_num double precision NOT NULL DEFAULT 0,  -- v0.5 added in migration
  wa_den double precision NOT NULL DEFAULT 0,  -- v0.5 added in migration
  PRIMARY KEY (user_id, topic_id)
);
CREATE INDEX ix_tm_user_band ON topic_mastery (user_id, band);
CREATE INDEX ix_tm_topic ON topic_mastery (topic_id);  -- v0.5 added in migration

-- (AN CP-2) Item statistics per question version (first attempts only). RLS: NONE (aggregate; content roles see ≥ analytics.k_min.item) | Retention: R-AN-COHORT | PII: P0
CREATE TABLE question_item_stats (
  question_version_id uuid PRIMARY KEY,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  n_first              int         NOT NULL DEFAULT 0,
  p_value              numeric(5,4) NULL,
  median_time_s        int         NULL,
  skip_rate            numeric(5,4) NULL,
  option_dist          jsonb       NULL,
  point_biserial       numeric(5,4) NULL,
  difficulty_b         numeric(6,3) NULL,
  review_flag          boolean     NOT NULL DEFAULT false,
  computed_at          timestamptz NOT NULL DEFAULT now(),
  n_updates int NOT NULL DEFAULT 0  -- v0.5 added in migration
);

-- (AN CP-2, §6.5) Daily feed for security; adults with active security_monitoring consent only; read via
-- analytics.feeds.get_activity_summary(). RLS: O (platform/security only) | Retention: R-AN-FEED | PII: P1
CREATE TABLE security_activity_feed_daily (
  user_id                       uuid        NOT NULL,
  activity_date                 date        NOT NULL,              -- IST
  privacy_tier                  text        NOT NULL CHECK (privacy_tier = 'adult'),   -- minors: no rows, ever
  active_devices                smallint    NOT NULL DEFAULT 0,
  multi_device_overlap_s        int         NOT NULL DEFAULT 0,
  max_concurrent_active_page_instances smallint NOT NULL DEFAULT 0,
  active_hours_bitmap           int         NOT NULL DEFAULT 0 CHECK (active_hours_bitmap BETWEEN 0 AND 16777215),  -- 24 bits, hour-level only
  implausible_day               boolean     NOT NULL DEFAULT false,
  plausibility_violations       jsonb       NOT NULL DEFAULT '{}',   -- counts by code
  clock_jump_count              int         NOT NULL DEFAULT 0,
  large_skew_count              int         NOT NULL DEFAULT 0,
  feed_version                  text        NOT NULL,              -- 'feed-1.0'
  computed_at                   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, activity_date)
);

-- (AN CP-2) Ops: days needing recompute after late events. RLS: NONE (system) | Retention: deleted once recomputed | PII: P1
-- RLS (as migrated): O (user_id = app.user_id() OR platform)
CREATE TABLE analytics_dirty_days (
  user_id              uuid        NOT NULL,
  activity_date        date        NOT NULL,
  reason text NOT NULL CHECK (reason IN ('late_event','backfill','tm_version_change','erasure', 'interval_rebuild','server_event')),  -- v0.5 as migrated
  marked_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, activity_date)
);

-- (AN CP-2) Ops: rejection counters only, no payloads. RLS: NONE (system) | Retention: 90 days | PII: P0
CREATE TABLE analytics_ingest_rejections (
  hour_start           timestamptz NOT NULL,
  code                 text        NOT NULL CHECK (code IN ('unknown_event_type','unsupported_schema_version','server_only_event',
                          'purpose_not_permitted','event_too_old','event_in_future','invalid_payload','payload_too_large',
                          'entity_not_entitled','rate_capped','uuid_time_mismatch')),
  event_type           text        NOT NULL DEFAULT '_unknown',
  count                bigint      NOT NULL DEFAULT 0,
  PRIMARY KEY (hour_start, code, event_type)
);

-- (PRD CCP-11) Audited, expiring report exports (coordinator, trainer, finance, security Section H).
-- RLS: custom — USING (requested_by = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) OR app.is_platform())
-- Retention: rows 1 year (R-SEC); files deleted at expires_at (24 h) | PII: P1 (+ P2 inside the file when contains_pii)
-- STATUS: migrated in analytics_0002 (v0.6, 2026-11-03); RLS policy p_ej as above; trg_set_updated_at
CREATE TABLE export_jobs (
  id                   uuid PRIMARY KEY,
  requested_by         uuid        NOT NULL REFERENCES users(id),
  organization_id      uuid        NULL REFERENCES organizations(id),
  report_key           text        NOT NULL,                       -- 'coordinator.batch_progress', 'security.monthly_integrity', ...
  scope_type           text        NOT NULL CHECK (scope_type IN ('platform','organization','batch','course','self')),
  scope_id             uuid        NULL,
  filters              jsonb       NOT NULL DEFAULT '{}',
  format               text        NOT NULL DEFAULT 'csv' CHECK (format IN ('csv')),   -- v0.6 as migrated
  contains_pii         boolean     NOT NULL,
  row_count            int         NULL,
  status               text        NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','awaiting_approval','running',
                                       'ready','expired','failed','rejected')),
  approval_request_id  uuid        NULL REFERENCES approval_requests(id),   -- per-user security exports, > 10,000-row PII exports
  reason_code          text        NULL,
  reason               text        NULL,                           -- v0.6 as migrated
  file_s3_key          text        NULL,                           -- watermarked with requester + time
  file_sha256          bytea       NULL CHECK (file_sha256 IS NULL OR octet_length(file_sha256) = 32),
  watermark            text        NULL,                           -- v0.6 as migrated
  failure_code         text        NULL,                           -- v0.6 as migrated
  expires_at           timestamptz NULL,
  downloaded_at        timestamptz NULL,
  download_count       int         NOT NULL DEFAULT 0 CHECK (download_count BETWEEN 0 AND 5),  -- v0.6 as migrated
  completed_at         timestamptz NULL,                           -- v0.6 as migrated
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_ej_ready CHECK (status <> 'ready' OR (file_s3_key IS NOT NULL AND expires_at IS NOT NULL))
);
CREATE INDEX ix_ej_requester ON export_jobs (requested_by, created_at DESC);
CREATE INDEX ix_ej_status ON export_jobs (status, updated_at) WHERE status IN ('running','ready');  -- v0.6 as migrated
```

Service interfaces (not tables) consumed by `security` (Brief v0.2 §2): `analytics.feeds.get_engaged_buckets(user_id, from, to)` reads `activity_heartbeats` through `ix_hb_user_device_eff` and returns `(device_id, auth_session_id, bucket_5min, activity_kind)`; `analytics.feeds.get_activity_summary(...)` reads `security_activity_feed_daily`. Both return nothing for minors or users without an active `security_monitoring` consent.

---

## 13. Platform (`audit`, `admin`, `notifications`, `support`)

```sql
-- (CCP-2) Written in the business transaction; drained by the sealer. RLS: NONE (INSERT-only for td_app) | Retention: minutes | PII: P1/P2
CREATE TABLE audit_outbox (
  id               uuid PRIMARY KEY,
  occurred_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
  record           jsonb       NOT NULL                            -- same shape as audit_log business columns
);
CREATE INDEX ix_audit_outbox_time ON audit_outbox (occurred_at, id);

-- Append-only, hash-chained, partitioned monthly. UPDATE/DELETE revoked from all app roles; trigger raises on UPDATE.
-- RLS: platform-only read (security_reviewer/super_admin via app.is_platform()) | Retention: R-AUDIT | PII: P1/P2
CREATE TABLE audit_log (
  seq               bigint      NOT NULL,                         -- gap-free, assigned by sealer
  occurred_at       timestamptz NOT NULL,
  id                uuid        NOT NULL,                         -- = audit_outbox.id
  actor_type text NOT NULL,  -- v0.5 as migrated
  actor_user_id     uuid        NULL,
  actor_session_id  uuid        NULL,
  actor_roles       text[]      NOT NULL DEFAULT '{}',
  action            text        NOT NULL,                         -- 'rbac.grant.create','security.restriction.lift','case.decide',
                                                                  -- 'policy.change','pii.reveal','export.download', ...
  target_type       text        NOT NULL,
  target_id         uuid        NULL,
  organization_id   uuid        NULL,
  subject_user_id   uuid        NULL,                             -- whose data was affected
  reason_code       text        NULL,                             -- SEC-DM-18: 'case_review','appeal','takeover_investigation','qa_sample', ...
  reason            text        NULL,                             -- free text
  before_state      jsonb       NULL,                             -- minimised diff
  after_state       jsonb       NULL,
  request_id        text        NULL,
  ip                inet        NULL,
  prev_hash bytea NOT NULL,  -- v0.5 as migrated
  row_hash bytea NOT NULL,  -- v0.5 as migrated; sha256(prev_hash || canonical_json(row))
  -- v0.5: not in migration (replaced/removed): PRIMARY KEY (seq, occurred_at)
  CONSTRAINT ck_audit_log_actor_type CHECK (actor_type IN ('user','system','gateway','support_impersonation')),  -- v0.5 added in migration
  CONSTRAINT ck_audit_log_prev_hash_len CHECK (octet_length(prev_hash) = 32),  -- v0.5 added in migration
  CONSTRAINT ck_audit_log_row_hash_len CHECK (octet_length(row_hash) = 32),  -- v0.5 added in migration
  CONSTRAINT pk_audit_log PRIMARY KEY (seq, occurred_at)  -- v0.5 added in migration
) PARTITION BY RANGE (occurred_at);
CREATE INDEX ix_audit_target ON audit_log (target_type, target_id, occurred_at);
CREATE INDEX ix_audit_actor ON audit_log (actor_user_id, occurred_at);
CREATE INDEX ix_audit_subject ON audit_log (subject_user_id, occurred_at);
CREATE INDEX ix_audit_seq ON audit_log (seq);  -- v0.5 added in migration
-- Chain anchors: hourly {max_seq, row_hash} written to S3 Object Lock (compliance mode) — not a table.

-- (Owned by admin — CCP-7; columns per SEC-DM-15/19) Versioned; one active row per (key, scope).
-- Precedence: user exception > organization > plan > platform default (security §3.1). Bounds (min_value/max_value) and
-- `locked` live on the platform row and are copied to overrides; out-of-bound overrides are rejected by the service.
-- Key namespaces include sessions.*, devices.*, playback.*, assessment.*, risk.*, login.*, otp.*, unblock.*, org.*,
-- auth.step_up_window.*, analytics.tm.*, analytics.retention.*, analytics.k_min.*, commerce.*, coding.*.
-- v0.3 keys: commerce.subscription_grace_days (default 5, bounds 3–7), commerce.refund.dual_approval_above_paise (2500000),
-- coding.run_per_minute (10), coding.submit_per_minute (5), coding.max_inflight_submits (1),
-- org.notify_coordinator_on_restriction (default 'L4_status_only'). Proposals need policy.propose; execution policy.edit (Dual).
-- v0.4 namespaces (CPR-SCH-12): risk.hc.* (incl. 🔒 risk.hc.auto_restrict_enabled, default false), risk.separation.*,
-- risk.owner_verification.*, security.keys.* (security.keys.k_device.current_version, security.keys.k_login.current_version),
-- assessment.idle_hold_extra_minutes. risk.owner_verified_overlap_multiplier is retired (replaced by separation classes S0–S3).
-- RLS: NONE (platform config; org rows readable by that org and user rows by that user through the API) | Retention: R-CONTENT | PII: P0/P1
CREATE TABLE policy_settings (
  id               uuid PRIMARY KEY,
  setting_key      text        NOT NULL,                          -- 'devices.student.max_trusted', 'risk.threshold.L3', ...
  scope_type       text        NOT NULL CHECK (scope_type IN ('platform','plan','organization','user')),
  scope_id         uuid        NULL,                              -- plan id / organization id / user id; NULL for platform
  value            jsonb       NOT NULL,
  value_schema     text        NOT NULL,                          -- JSON-schema id validated by app
  min_value        jsonb       NULL,
  max_value        jsonb       NULL,
  org_overridable  boolean     NOT NULL DEFAULT false,
  plan_overridable boolean     NOT NULL DEFAULT false,
  locked           boolean     NOT NULL DEFAULT false,            -- 🔒: no override below platform; platform change needs dual approval
  version          int         NOT NULL CHECK (version >= 1),
  is_active        boolean     NOT NULL DEFAULT true,
  effective_from   timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NULL,                              -- required for user exceptions (≤ 180 days)
  case_decision_id uuid        NULL REFERENCES case_decisions(id),  -- required for user exceptions (security §5.5)
  change_reason    text        NOT NULL,
  changed_by       uuid        NOT NULL REFERENCES users(id),
  approved_by      uuid        NULL REFERENCES users(id),
  approval_request_id uuid     NULL REFERENCES approval_requests(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_ps_scope CHECK ((scope_type = 'platform') = (scope_id IS NULL)),
  CONSTRAINT ck_ps_user_exception CHECK (scope_type <> 'user'
      OR (expires_at IS NOT NULL AND case_decision_id IS NOT NULL AND expires_at <= effective_from + interval '180 days')),
  CONSTRAINT ck_ps_approval CHECK (approved_by IS NULL OR approved_by <> changed_by),
  UNIQUE (setting_key, scope_type, scope_id, version)
);
CREATE UNIQUE INDEX ux_ps_active ON policy_settings (setting_key, scope_type,
  coalesce(scope_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE is_active;
CREATE INDEX ix_ps_user_exceptions ON policy_settings (scope_id, expires_at) WHERE scope_type = 'user' AND is_active;
CREATE UNIQUE INDEX ux_ps_active ON policy_settings (setting_key, scope_type, coalesce(scope_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE is_active;  -- v0.5 added in migration

-- RLS: NONE | Retention: R-CONTENT | PII: P0
CREATE TABLE feature_flags (
  id               uuid PRIMARY KEY,
  flag_key         text        NOT NULL UNIQUE,                   -- 'payments.cashfree_enabled', 'platform.maintenance_mode' (v0.3)
  description      text        NOT NULL,
  is_enabled       boolean     NOT NULL DEFAULT false,
  rollout_percent  smallint    NOT NULL DEFAULT 0 CHECK (rollout_percent BETWEEN 0 AND 100),
  org_allowlist    uuid[]      NOT NULL DEFAULT '{}',
  user_allowlist   uuid[]      NOT NULL DEFAULT '{}',
  updated_by       uuid        NULL REFERENCES users(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- RLS: O | Retention: 180 days (in-app/delivery log); security notices R-SEC | PII: P2
CREATE TABLE notifications (
  id                 uuid PRIMARY KEY,
  user_id            uuid        NOT NULL REFERENCES users(id),
  organization_id    uuid        NULL REFERENCES organizations(id),
  template_key       text        NOT NULL,
  template_version   smallint    NOT NULL,
  category           text        NOT NULL CHECK (category IN ('security','transactional','learning','marketing','system')),
  channels           text[]      NOT NULL CHECK (channels <@ ARRAY['in_app','email','sms','push']::text[]),
  data               jsonb       NOT NULL DEFAULT '{}',          -- template variables (minimised)
  priority           text        NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','critical')),
  status             text        NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','partially_sent','failed','suppressed')),
  delivery           jsonb       NOT NULL DEFAULT '{}',           -- {"email":{"status":"delivered","provider_id":"..."},...}
  dedupe_key         text        NULL,
  read_at            timestamptz NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);  -- marketing consent and minor suppression enforced in the notifications service
CREATE UNIQUE INDEX ux_notif_dedupe ON notifications (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX ix_notif_inbox ON notifications (user_id, created_at DESC) WHERE 'in_app' = ANY (channels);

-- RLS: custom — USING (requester_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) OR app.is_platform())
-- Retention: 3 years after closure (consumer-law limitation) | PII: P2/P3
-- STATUS: migrated in support_0001 (v0.6, audit fix wave 3 re-check 2026-11-03). Columns not re-diffed against the migration since v0.5; the migration wins (§17).
CREATE TABLE support_tickets (
  id                 uuid PRIMARY KEY,
  ticket_number      text        NOT NULL UNIQUE,                 -- 'TD-T-2026-000123'
  requester_id       uuid        NOT NULL REFERENCES users(id),
  organization_id    uuid        NULL REFERENCES organizations(id),
  category           text        NOT NULL CHECK (category IN ('account_access','device_reset','billing','refund','content',
                                    'assessment','technical','grievance','privacy_request','other',
                                    'certificate','college_access','appeal')),  -- v0.6 support_0002 (FR-SUP-001); SLA queue index ix_st_due_id on (coalesce(resolution_due_at, '9999-01-01'), id)
  subject            text        NOT NULL,
  body               text        NOT NULL,
  status             text        NOT NULL DEFAULT 'open' CHECK (status IN ('open','pending_user','pending_internal','resolved','closed')),
  priority           text        NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
  assigned_to        uuid        NULL REFERENCES users(id),
  related_order_id   uuid        NULL REFERENCES orders(id),
  related_case_id    uuid        NULL REFERENCES security_cases(id),
  is_grievance       boolean     NOT NULL DEFAULT false,          -- DPDP / consumer grievance clock
  first_response_due_at timestamptz NULL,
  resolution_due_at  timestamptz NULL,
  first_responded_at timestamptz NULL,
  resolved_at        timestamptz NULL,
  privacy_request_id uuid        NULL REFERENCES privacy_requests(id),   -- category 'privacy_request'
  -- thread lives in support_ticket_messages (PRD CCP-07); the former messages JSONB column is removed
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_st_queue ON support_tickets (status, priority, resolution_due_at) WHERE status NOT IN ('resolved','closed');
CREATE INDEX ix_st_requester ON support_tickets (requester_id, created_at DESC);

-- (PRD CCP-07) Ticket thread. Append-only except redaction. RLS: same predicate as support_tickets (via ticket) | Retention: as ticket | PII: P2/P3
-- STATUS: migrated in support_0001 (v0.6, audit fix wave 3 re-check 2026-11-03). Columns not re-diffed against the migration since v0.5; the migration wins (§17).
CREATE TABLE support_ticket_messages (
  id                 uuid PRIMARY KEY,
  support_ticket_id  uuid        NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
  organization_id    uuid        NULL REFERENCES organizations(id),   -- denormalised for RLS
  author_id          uuid        NULL REFERENCES users(id),           -- NULL = system
  author_kind        text        NOT NULL CHECK (author_kind IN ('requester','agent','system')),
  visibility         text        NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','internal')),   -- internal notes (FR-SUP-004)
  body               text        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 10000),
  attachments        jsonb       NOT NULL DEFAULT '[]',
  redacted_at        timestamptz NULL,
  created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_stm_ticket ON support_ticket_messages (support_ticket_id, created_at);

-- (PRD CCP-08) Dual-control queue (FR-ADM-004, role matrix §5). Approver ≠ requester; 72 h expiry; payload hashed so the
-- approved action cannot be altered after approval. RLS: NONE (platform; API filters by approval.decide grants) | Retention: R-AUDIT | PII: P1
-- RLS (as migrated, rbac_0003): custom p_apr USING (requested_by = app.user_id() OR app.is_platform() OR organization_id = ANY (app.org_ids())) WITH CHECK (requested_by = app.user_id() OR app.is_platform()); created in rbac_0001
CREATE TABLE approval_requests (
  id                 uuid PRIMARY KEY,
  action_type        text        NOT NULL,                      -- 'rbac.grant.privileged','policy.change','risk.ruleset.activate',
                                                                -- 'refund.goodwill','export.bulk_pii','security.export.per_user',
                                                                -- v0.4: 'security.case.decision','security.restriction.bulk_lift',
                                                                -- 'risk.kill_switch.ratify', ...
  organization_id    uuid        NULL REFERENCES organizations(id),
  target_type        text        NOT NULL,
  target_id          uuid        NULL,
  payload            jsonb       NOT NULL,                      -- proposed change (minimised)
  payload_hash       bytea       NOT NULL CHECK (octet_length(payload_hash) = 32),
  requested_by       uuid        NOT NULL REFERENCES users(id),
  request_reason     text        NOT NULL,
  required_approver_role text    NOT NULL,                      -- role key from role matrix §5
  status             text        NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','expired','cancelled','executed')),
  decided_by         uuid        NULL REFERENCES users(id),
  decided_at         timestamptz NULL,
  decision_note      text        NULL,
  expires_at         timestamptz NOT NULL,                      -- created_at + 72 h
  executed_at        timestamptz NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_apr_distinct CHECK (decided_by IS NULL OR decided_by <> requested_by),   -- SoD-05
  CONSTRAINT ck_apr_decided CHECK ((status IN ('approved','rejected','executed')) = (decided_by IS NOT NULL))
);
CREATE INDEX ix_apr_pending ON approval_requests (action_type, expires_at) WHERE status = 'pending';
CREATE UNIQUE INDEX ux_apr_case_decision_pending ON approval_requests (target_id)
  WHERE action_type = 'security.case.decision' AND status = 'pending';            -- v0.4: one pending decision per case
CREATE UNIQUE INDEX ux_apr_case_decision_pending ON approval_requests (target_id) WHERE action_type = 'security.case.decision' AND status = 'pending';  -- v0.5 added in migration
-- v0.3: forward FK from commerce (refunds are defined in §11 before this table)
ALTER TABLE refunds ADD CONSTRAINT fk_refund_approval FOREIGN KEY (approval_request_id) REFERENCES approval_requests(id);
```

### 13.1 Privacy (`admin` module, privacy sub-package)

Owned by `admin` (Brief v0.2 §2); request workflow and retention schedule defined by the Security Specialist (`privacy-and-data-retention.md` §5, §7; SEC CCP-S2, PRIV CCP-P1, PRD CCP-07, ARCH CCP-13).

```sql
-- DPDP rights queue (ss.11–14): access/export, correction, erasure, grievance, nomination. RLS: O (requester) + platform | Retention: R-PRIV | PII: P2/P3
CREATE TABLE privacy_requests (
  id                   uuid PRIMARY KEY,
  request_ref text NOT NULL UNIQUE CHECK (request_ref ~ '^PRV-[0-9]{4}-[0-9A-HJKMNP-TV-Z]{6}$'),  -- v0.5 as migrated; 'PRV-YYMM-XXXXXX'
  user_id              uuid        NULL REFERENCES users(id),     -- data principal (NULL if unauthenticated grievance)
  requested_by         uuid        NULL REFERENCES users(id),     -- principal, guardian or nominee
  requester_relationship text      NOT NULL DEFAULT 'self' CHECK (requester_relationship IN ('self','guardian','nominee','college')),
  organization_id      uuid        NULL REFERENCES organizations(id),   -- B2B: routed to the college as fiduciary
  request_type         text        NOT NULL CHECK (request_type IN ('access_export','correction','erasure','grievance',
                                         'nomination','consent_withdrawal_help')),
  status               text        NOT NULL DEFAULT 'received' CHECK (status IN ('received','identity_verification','in_progress',
                                         'awaiting_requester','cooling_off','completed','rejected','withdrawn')),
  identity_verification_method text NULL CHECK (identity_verification_method IN ('session','otp','guardian_otp','manual')),
  identity_verified_at timestamptz NULL,
  received_at          timestamptz NOT NULL DEFAULT now(),
  due_at               timestamptz NOT NULL,                     -- statutory / policy due date (≤ 90 days; grievance ≤ 30 days)
  cooling_off_until    timestamptz NULL,                         -- erasure
  completed_at         timestamptz NULL,
  response_summary     text        NULL,
  export_job_id uuid NULL,  -- v0.5: soft reference, no FK yet (target table in another migration branch)
  assigned_to          uuid        NULL REFERENCES users(id),
  legal_hold           boolean     NOT NULL DEFAULT false,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  details text NULL CHECK (details IS NULL OR char_length(details) <= 4000),  -- v0.5 added in migration
  export_payload jsonb NULL,  -- v0.5 added in migration
  idempotency_key text NULL  -- v0.5 added in migration
);
CREATE INDEX ix_prq_queue ON privacy_requests (status, due_at) WHERE status NOT IN ('completed','rejected','withdrawn');
CREATE INDEX ix_prq_user ON privacy_requests (user_id, received_at DESC);

-- Retention registry driving deletion jobs; every module's privacy_provider registers here (AN DM-12). RLS: NONE | Retention: R-CONTENT | PII: P0
CREATE TABLE retention_policies (
  id                 uuid PRIMARY KEY,
  data_category      text        NOT NULL,                     -- privacy doc D1–D18
  table_name         text        NOT NULL,
  retention_class    text        NOT NULL,                     -- R-ACCT, R-SEC, R-AN-RAW, ...
  retention_interval interval    NULL,                         -- NULL = life of account / contract (rule in `basis`)
  basis              text        NOT NULL,                     -- legal / policy basis
  deletion_method    text        NOT NULL CHECK (deletion_method IN ('partition_drop','row_delete','anonymise','pseudonymise','s3_lifecycle')),
  legal_hold_aware   boolean     NOT NULL DEFAULT true,
  job_name           text        NOT NULL,                     -- 'purge_raw_analytics', ...
  owner_module       text        NOT NULL,
  is_active          boolean     NOT NULL DEFAULT true,
  updated_by         uuid        NULL REFERENCES users(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (table_name, data_category)
);

-- (PRIV CCP-P1) Re-applied after any backup restore before data is used: the restore job recomputes HMAC(k_erasure, id)
-- for restored users and re-runs privacy_provider.erase() on matches. Holds a keyed hash, never the user id.
-- RLS: NONE (system) | Retention: R-PRIV (35 days beyond oldest retained backup) | PII: P1
-- v0.6: migrated in admin_0003 (DB-01) with the as-migrated DDL below, which differs from the v0.4 contract:
--   RLS p_platform (ENABLE + FORCE; USING/WITH CHECK app.is_platform()); append-only (UPDATE/DELETE/TRUNCATE revoked from td_app);
--   subject_hash is SHA-256("erasure:<user_id>") (app.modules.admin.privacy.subject_hash), NOT a keyed HMAC(k_erasure, ...) — see §17.3;
--   scope is jsonb {modules: [...], sessions_revoked: n}; pending_modules lists required modules whose provider has not run;
--   no verified_at; table comment says retention R-AUDIT (>= oldest backup), PII P0 (hash only).
CREATE TABLE erasure_ledger (
  id                 uuid PRIMARY KEY,
  privacy_request_id uuid        NULL REFERENCES privacy_requests(id),
  subject_hash       bytea       NOT NULL CHECK (octet_length(subject_hash) = 32),
  erased_at          timestamptz NOT NULL DEFAULT now(),
  scope              jsonb       NOT NULL DEFAULT '{}'::jsonb,
  pending_modules    text[]      NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_erasure_ledger_subject ON erasure_ledger (subject_hash);
CREATE INDEX ix_erasure_ledger_request ON erasure_ledger (privacy_request_id);
```

Note on DDL order: the document groups tables by module; forward references (e.g. `account_restrictions → security_cases/case_decisions`, `lessons → tests`, `risk_rule_versions`/`policy_settings`/`export_jobs → approval_requests`, `support_tickets → privacy_requests`, `mentor_bookings → entitlements`) are resolved in the Alembic baseline by creating tables first and adding cross-module FKs in a final step.

---

## 14. RLS and classification summary

| Table | Family | Partitioned | Retention | PII |
|---|---|---|---|---|
| outbox_events, idempotency_keys | NONE / O | – | 7 d / 24 h–7 d | P1 |
| users, user_profiles, user_credentials, mfa_factors | O (+ org visibility fn for users/profiles) | – | R-ACCT | P2–P4 |
| verification_tokens, password_reset_tokens | **O (as migrated, identity_0003)**; hash lookup in a named system context | – | R-TOKEN | P4 |
| consents, guardian_consents | O | – | R-CONSENT | P3 |
| devices | NONE | – | R-DEV | P1/P3 |
| user_devices | O | – | R-DEV | P1/P2 |
| auth_sessions | O | – | R-SEC | P1–P4 |
| login_attempts | O | monthly | R-SEC | P3 |
| session_network_observations (v0.4) | O | monthly (`first_seen_at`) | R-SEC (395 d) | P3 |
| playback_sessions | O | monthly | R-PLAY | P1/P3 |
| security_signals, risk_evaluations | O | monthly | R-RISK | P3 |
| risk_rules, risk_rule_versions | NONE | – | R-CONTENT | P0 |
| account_restrictions, security_cases, unblock_requests, case_notes, case_decisions | O / app-gated | – | R-RISK | P3 |
| org_trusted_networks | T | – | R-ORG | P0/P1 |
| security_incidents | NONE (API-gated: security lead, DPO, super_admin) | – | R-PRIV | P2/P3 |
| organizations, org_memberships, batches, batch_members, institution_contracts | T | – | R-ORG / R-FIN | P0–P2 |
| org_invitations, bulk_import_jobs | T | – | R-ORG | P2 |
| roles, permissions, role_permissions | NONE | – | R-CONTENT | P0 |
| role_grants | custom (user or org) | – | R-AUDIT | P1 |
| courses, course_versions, course_modules, lessons, lesson_assets, lesson_topics, resources, assignments | TN | – | R-CONTENT | P0 |
| enrolments, lesson_progress, assignment_submissions, certificates | U | – | R-LEARN | P1–P2 |
| topics, companies, judge_languages | NONE | – | R-CONTENT | P0 |
| company_paths, company_path_steps, questions, question_versions, question_options, question_tags | TN | – | R-CONTENT | P0 |
| practice_sessions, practice_responses, recommendations | U | – | R-LEARN | P1 |
| mentor_slots (mentoring_0001) | TN | – | R-LEARN | P1 |
| mentor_bookings, interview_feedback (mentoring_0001) | U | – | R-LEARN | P1/P2 |
| resumes, resume_reviews (mentoring_0001) | O | – | R-ACCT | P2 |
| tests, test_sections, test_section_rules, test_assignments | TN | – | R-CONTENT | P0 |
| attempt_overrides, test_attempts, attempt_sections, attempt_responses, attempt_results | U | – | R-LEARN | P1/P3 |
| attempt_events | U | monthly | R-ASSESS-EVT | P1/P3 |
| coding_problems, coding_test_cases, coding_test_case_blobs (impl.) | TN | – | R-CONTENT | P0/P4 |
| code_submissions, submission_results | U | – | R-LEARN | P1 |
| products, product_items, plans, prices, coupons | TN | – | R-FIN | P0 |
| coupon_redemptions, subscriptions | O | – | R-FIN | P1 |
| orders, order_items, payments, refunds, invoices | custom (user or org) | – | R-FIN | P2/P3 |
| payment_webhook_events, invoice_sequences, reconciliation_runs (impl.) | **platform-only policy `p_platform` (as migrated)** | – | R-FIN | P3/P4 |
| entitlements, entitlement_events, seat_waitlist (impl.) | U | – | R-FIN | P1 |
| analytics_events | U | monthly (`event_ts`) | R-AN-RAW (90 d) | P1 |
| activity_heartbeats | U | monthly (`event_ts`) | R-AN-HB (35 d) | P1 |
| engagement_intervals | U | monthly | R-AN-INT (13 mo) | P1 |
| daily_learning_aggregates, weekly_learning_aggregates, video_watch_coverage, topic_mastery | U | – | R-AN-AGG | P1 |
| cohort_learning_aggregates | T (NULL org = platform) | – | R-AN-COHORT | P0 |
| route_daily_aggregates, question_item_stats | NONE (aggregates, k-rule) | – | R-AN-COHORT | P0 |
| security_activity_feed_daily | O (platform/security only) | – | R-AN-FEED (180 d) | P1 |
| analytics_dirty_days / analytics_ingest_rejections | **O (as migrated)** / NONE (system) | – | until recomputed / 90 d | P1/P0 |
| export_jobs (analytics_0002) | custom `p_ej` (requester or org or platform) | – | R-SEC (files 24 h) | P1 (+P2 in file) |
| audit_outbox | NONE (insert-only) | – | minutes | P1/P2 |
| audit_log | platform-only | monthly | R-AUDIT | P1/P2 |
| policy_settings, feature_flags | NONE | – | R-CONTENT | P0/P1 |
| approval_requests | **custom `p_apr` (as migrated, rbac_0003)**: requester, own org, or platform | – | R-AUDIT | P1 |
| notifications | O | – | 180 d | P2 |
| support_tickets, support_ticket_messages (support_0001) | custom | – | 3 y after closure | P2/P3 |
| privacy_requests | O | – | R-PRIV | P2/P3 |
| retention_policies | NONE | – | R-CONTENT | P0 |
| erasure_ledger (admin_0003) | `p_platform` (platform only), append-only | – | R-PRIV | P1 (stored as hash; table comment says P0) |
| security_user_state, security_notices (impl.) | O | – | R-RISK / R-SEC | P1/P3 |
| security_counters, security_bulk_lifts, security_report_exports (impl.) | NONE (API-gated) | – | 2 d / R-AUDIT / 30 d | P0–P3 |
| analytics_job_state, analytics_consumed_events (impl.) | NONE (ops) | – | – | P0 |

**Total: 121 tables** — the 82 Brief v0.1 tables, 14 architect CCP tables (`outbox_events`, `idempotency_keys`, `audit_outbox`, `test_assignments`, `attempt_overrides`, `attempt_sections`, `practice_sessions`, `practice_responses`, `recommendations`, `company_path_steps`, `product_items`, `invoice_sequences`, `judge_languages`, and the former `user_topic_mastery`, now `topic_mastery`), and 25 further tables from accepted v0.2 proposals (`org_trusted_networks`, `security_incidents`, `privacy_requests`, `retention_policies`, `erasure_ledger`, `approval_requests`, `org_invitations`, `bulk_import_jobs`, `lesson_topics`, `mentor_slots`, `mentor_bookings`, `interview_feedback`, `resumes`, `resume_reviews`, `entitlement_events`, `video_watch_coverage`, `weekly_learning_aggregates`, `cohort_learning_aggregates`, `route_daily_aggregates`, `question_item_stats`, `security_activity_feed_daily`, `analytics_dirty_days`, `analytics_ingest_rejections`, `export_jobs`, `support_ticket_messages`). All 121 appear in Brief v0.2 §4. Before v0.2 this document defined 96 tables. **v0.4: 122 tables** — `session_network_observations` added (CPR-SCH-04; Brief v0.4 §4). **v0.5 (Stage 10 sync): 132 tables documented** — 122 contract tables (113 migrated, 9 Planned — not yet migrated) + 10 implementation tables (§17.2); **123 tables migrated**. Partitioned tables are created with a `DEFAULT` partition only; `pg_partman` monthly premake/drops remain Planned (§17.6). **v0.6:** the 9 Planned tables are migrated and further tables were added by later revisions (§17.1); monthly partitions come from `maint.ensure_partitions` (§1.3). The table count has not been recounted.

---

## 15. Columns pending confirmation — resolved in v0.2

All items previously open here were resolved by the Integration Lead on 2026-11-03 using the Security Specialist's and Analytics Engineer's data-model requirements (`docs/contract-reconciliation.md` §2.5). Summary:

### 15.1 Security Specialist (resolved)

| Former question | Resolution (now in §3–§5, §13) |
|---|---|
| `risk_evaluations` score / level / action | `score numeric(5,2)` 0–100; `level_before/level_after` 0–4; action vocabulary from security §9; thresholds in `policy_settings` (`risk.threshold.*`) |
| First-class ruleset table? | `risk_rule_versions` rows with `rule_id IS NULL` are ruleset versions; one active per family (`ux_rrv_active_ruleset`) |
| `scoring_mode` for minors / shadow | Replaced by `mode` (`enforce`/`shadow`); minors have no sharing evaluations (`ck_sig_minor` + service rule); takeover handled deterministically |
| Rule DSL and approval | `definition` JSONB (`params`, `points`, `caps`, `multipliers`, `thresholds`); `approved_by <> proposed_by`; ≥ 14 days shadow |
| Signal catalogue and minor rule | `family` + `rule_key` (SH-01..12, SH-M1, TO-01..07, `cap.*`, abuse/integrity); `is_minor_at_time` CHECK |
| L4 lift trigger | `security_cases.is_high_risk` + unblock workflow §5 → `requires_second_approval`; `case_decisions.approved_by <> decided_by` |
| Case statuses and SLA | `open`, `under_review`, `awaiting_user`, `escalated`, `decided`, `closed`; `sla_first_response_due`, `sla_decision_due` from `unblock.sla.*` |
| Evidence handling | `unblock_requests.attachments` (≤ 2 files, ≤ 5 MB, AV-scanned; never Aadhaar/PAN); deleted 90 days after closure |
| `convert_to_paid_seat` | Dropped (buddy seat is a commerce product) |
| Geo granularity | `geo_country` + `geo_region` (state); no city; `network_type` from offline ASN/IP-type DB |
| Fingerprint columns | `devices.fp_hash`, `fp_epoch` (Phase 2, adults, consent E, off by default) |
| Step-up windows | `auth_sessions.last_step_up_at`; 5 / 10 / 15 min (Brief v0.2 §1) |
| Retention | Privacy doc authoritative; classes in §1.4 |
| `privacy_requests` | Defined in §13.1 |

### 15.2 Analytics Engineer (resolved)

| Former question | Resolution (now in §12) |
|---|---|
| `analytics_events` envelope | Stored envelope from analytics §1.5 (`event_type`, `event_ts`, `effective_at`, `skew_ms`, `privacy_tier`, `ingest_flags`, typed entity columns, `payload` ≤ 4 KiB); xAPI-style columns dropped |
| Client time clamping | `effective_at = min(occurred_at + skew_ms, received_at)`; reject beyond 72 h late window |
| Heartbeat inputs | `page.heartbeat` narrow columns (`kind`, `active_ms`, `state_bits`, media/editor/reading fields) |
| Interval method version | `measurement_version` text (`tm-1.0`) |
| Aggregate grain / pre-aggregates | `daily_learning_aggregates` by (`entity_kind`, `entity_id`); `weekly_learning_aggregates`, `cohort_learning_aggregates` added |
| Raw retention | Events 90 days, heartbeats 35 days (reconciliation §3.1) |
| Percentile tables | `attempt_results.percentile` (reference cohort ≥ 20); cohort distributions in `cohort_learning_aggregates`; item statistics in `question_item_stats` |

### 15.3 Still open (owner decisions, not schema blockers)

| Item | Default in this schema | Owner |
|---|---|---|
| Legal Q4: is any analytics data "traffic data" under Rules 6(e)/8(3)? | Not treated as logs; 90 d / 35 d raw retention | Counsel via Security Specialist |
| PO-03: `security_monitoring` required for adult paid plans | Required; withdrawal ⇒ deterministic-only (no `security_signals` of family `sharing`, no feed rows) | Product owner + counsel |
| PO-11: placement drives | Names reserved, no DDL (§8) | Product owner |

---

## 16. Contract change proposals

Schema-level proposals from all wave-1 authors were reconciled into Brief v0.2 (`docs/contract-reconciliation.md`). This document reflects every accepted decision. Reserved names without DDL: `placement_drives`, `drive_eligibility_rules`, `drive_shortlists` (PRD CCP-03, deferred to product owner, default P2). New schema changes go through `contract-reconciliation.md` (Integration Lead) before the Alembic baseline.

### 16.1 v0.4 security follow-ups (applied 2026-11-03, `docs/consistency-pass-requests.md` §2)

| Request | Applied in |
|---|---|
| CPR-SCH-01 | `devices.key_version`, `login_attempts.key_version`; versioned HMAC comments (§4) |
| CPR-SCH-02 | `user_devices.remember_token_hash`, `remember_issued_at`, `ck_ud_remember`, `ux_ud_remember`; owner-verification and fixed `remember_until` comments (§4) |
| CPR-SCH-03 | `auth_sessions.created_via` + `remember_device`; `end_reason` + `replaced_same_device`; `idle_hold_until`; `scope` is a record only (`pending_session_choice` already present since v0.3) (§4) |
| CPR-SCH-04 | New partitioned table `session_network_observations` (§4, §1.3, §14) |
| CPR-SCH-05 | `case_decisions.approval_request_id` + `ck_cd_approval_link`, final-decisions-only comment; `approval_requests` action types and `ux_apr_case_decision_pending` (§5, §13) |
| CPR-SCH-06 | `attempt_events.event_type` + `reattach_same_device`; `test_attempts.rebind_count` comment (§9) |
| CPR-SCH-07 | `security_cases.opened_reason` + `engine_hc_L3` (§5) |
| CPR-SCH-08 | `risk_evaluations.is_minor_at_time` + `ck_re_no_minor`; `trigger` + `verification`; `gates` comment (§5) |
| CPR-SCH-09 | `security_signals.rule_key` families and `AB-12`; separation-class `multipliers` example (§5) |
| CPR-SCH-10 | `risk_rule_versions.status_changed_at/by`, `status_change_reason`; `active → shadow` transition (§5) |
| CPR-SCH-11 | R-SEC purge at 395 days; R-AUDIT split 3 y / 8 y (§1.4) |
| CPR-SCH-12 | `policy_settings` namespaces `risk.hc.*`, `risk.separation.*`, `risk.owner_verification.*`, `security.keys.*`, `assessment.idle_hold_extra_minutes`; `risk.owner_verified_overlap_multiplier` retired (§13) |
| CPR-SCH-13 | `payment_webhook_events.refetched_at`, `refetch_status`; `is_stale` monitoring-only (§11) |
| CPR-SCH-14 | `users.is_synthetic` endorsed; excluded from SH/HC rules (§3) |

---

## 17. As-migrated reference (Stage 10 schema sync, v0.5 — 2026-11-03)

Source of truth: `apps/api/migrations/versions/*.py` (24 revisions at v0.5; 45 at v0.6 — see §17.1; one Alembic history with per-module branch labels, ADR-0009). This section was produced by executing every revision's `upgrade()` against a recording stub and diffing the emitted DDL with §2–§13; after the v0.5 edits the column, constraint and index lists of all 113 shared tables match the migrations exactly. Migration-side rationale lives in each revision's docstring, `apps/api/app/modules/analytics/README.md` and `apps/api/app/modules/commerce/models.py`.

### 17.1 Revision inventory

Regenerated 2026-11-03 (audit fix wave 3) from the headers of the 45 files in `apps/api/migrations/versions/` (`revision`, `down_revision`, `branch_labels`, `depends_on`, first docstring line). One Alembic history with per-module branch labels (ADR-0009); a revision without a branch label continues its predecessor's branch. "Depends on" lists `depends_on` only (the predecessor is implied).

| Revision (branch) | Depends on | Summary (docstring) |
|---|---|---|
| `core_base_0001` (core_base) | – | extensions, roles, schemas, RLS context functions, kernel tables (`outbox_events`, `idempotency_keys`) |
| `core_base_0002` | admin_0001, sessions_0002, security_0001, media_0001, assessments_0001, analytics_0001, audit_0001, identity_0001, notifications_0001 | `maint.*` partition maintenance and retention purge (DB-02, DB-04; §1.2, §1.3); seeds missing `retention_policies` rows (`auth_sessions`, `playback_sessions`, `attempt_events`, tokens, `outbox_events`, `idempotency_keys`, `notifications`) |
| `identity_0001` (identity) | core_base | users, profiles, credentials, MFA factors, verification/reset tokens, consents |
| `identity_0002` | orgs_0001 | org-visibility RLS on users/user_profiles; `consents.organization_id` FK |
| `identity_0003` | – | RLS on `verification_tokens` and `password_reset_tokens` (owner or platform) |
| `identity_0004` | – | verification token purpose `attempt_rebind` (Stage 10 backlog A-10) |
| `orgs_0001` (orgs) | core_base, identity_0001 | organizations, memberships, batches, batch members, roster imports, invitations |
| `rbac_0001` (rbac) | core_base, identity_0001, orgs_0001 | roles, permissions, role_permissions, role_grants, approval_requests |
| `rbac_0002` | – | seed roles, permissions and role_permissions from the role matrix catalogue |
| `rbac_0003` | – | RLS on `approval_requests` (requester, own org, or platform) |
| `sessions_0001` (sessions) | core_base, identity_0001, orgs_0001 | devices, user_devices, auth_sessions, login_attempts, session_network_observations |
| `sessions_0002` | – | ENABLE + FORCE RLS on the DEFAULT partitions |
| `media_0001` (media) | core_base, catalog_0001 | `playback_sessions` (partitioned monthly on `started_at`) |
| `security_0001` (security) | core_base, identity_0001, orgs_0001, rbac_0001 | signals, rules, evaluations, restrictions, cases, unblock requests, decisions, trusted networks, incidents, per-user engine state, exports and bulk lifts |
| `security_0002` | – | enforcement rows are read-only for their owner (DB-05): `p_o` → `p_o_read` + `p_o_write` on `account_restrictions`, `security_cases`, `unblock_requests`, `security_user_state`, `security_notices`; DELETE/TRUNCATE revoked on `account_restrictions`, `security_cases` |
| `catalog_0001` (catalog) | core_base, identity_0001, orgs_0001 | courses, course_versions, course_modules, lessons, lesson_topics, lesson_assets, resources |
| `catalog_0002` | – | FR-CAT-001 lesson types `pdf` and `practice_set` (`lessons_lesson_type_check`, `ck_lesson_ref`; §7) |
| `learning_0001` (learning) | core_base, identity_0001, orgs_0001, catalog_0001 | enrolments, lesson_progress, assignments, assignment_submissions, certificates |
| `learning_0002` | – | raw (pre-penalty) score on assignment submissions (BE-08): `raw_score`, `late_penalty_pct` |
| `placement_0001` (placement) | core_base, identity_0001, orgs_0001 | taxonomy, companies, company paths, question bank, practice, recommendations |
| `placement_0002` | assessments_0001 | `company_path_steps.test_id → tests(id)` |
| `placement_0003` | – | `question_reports` (PLC-33..35 reported-error queue) |
| `placement_0004` | – | question SoD editors + review comment + retire reason (ADM-46 / ADM-55): `question_versions.edited_by`, `review_comment`; `questions.retired_reason` |
| `assessments_0001` (assessments) | core_base, identity_0001, orgs_0001, sessions_0001, placement_0001 | tests, sections, draw rules, assignments, overrides, attempts, results |
| `assessments_0002` | – | attempt integrity review decisions (ASM-20): `attempt_integrity_decisions` |
| `assessments_0003` | – | owning batch on tests (ADM-49): `tests.batch_id`, `ix_tests_batch` |
| `coding_0001` (coding) | core_base, identity_0001, orgs_0001 | judge languages, problems, test cases (hidden = encrypted), submissions, results |
| `coding_0002` | – | editor drafts, reference solutions, validation runs, hidden-case content tokens (`coding_drafts`, `coding_reference_solutions`, `coding_problem_validations`, `coding_testcase_content_tokens`) |
| `coding_0003` | – | column-level `UPDATE (stdout_excerpt)` on `submission_results` for privacy erasure (DB-01) |
| `commerce_0001` (commerce) | core_base, identity_0001, orgs_0001, rbac_0001 | products, plans, prices, coupons, orders, payments, webhook events, subscriptions, refunds, invoices, institution contracts, reconciliation runs |
| `commerce_0002` | rbac_0001 | invoice PDFs, B2B contract invoices, GST register exports (`gst_exports`), plan change (`subscriptions.scheduled_*`, `pending_addon_paise`) |
| `commerce_0003` | – | money integrity, refund state machine, subscription billing state, webhook backoff (DB-07 CHECKs, `orders.refunded_paise`, refund `price_adjustment` + submit retry columns, `subscriptions.billing_*`, `payment_webhook_events.next_attempt_at`) |
| `entitlements_0001` (entitlements) | core_base, identity_0001, orgs_0001, commerce_0001 | entitlements, entitlement_events (append-only), seat_waitlist |
| `entitlements_0002` | – | `plan_changed` history event (COM-14) |
| `mentoring_0001` (mentoring) | core_base, identity_0001, orgs_0001, placement_0001, entitlements_0001 | mentor_slots, mentor_bookings, interview_feedback, mentor_notes, resumes, resume_reviews |
| `analytics_0001` (analytics) | core_base_0001, identity_0001, orgs_0001 | raw events, heartbeats, engagement intervals, aggregates, mastery, security feed |
| `analytics_0002` | rbac_0001 | `export_jobs` (ANL-13..15 audited, expiring report exports) |
| `audit_0001` (audit) | core_base | `audit_outbox` + append-only hash-chained `audit_log` |
| `admin_0001` (admin) | core_base, identity_0001, orgs_0001, rbac_0001, security_0001 | policy_settings, feature_flags, privacy_requests, retention_policies |
| `admin_0002` | rbac_0001 | `break_glass_sessions` (ADM-17..19) |
| `admin_0003` | – | `erasure_ledger` (CCP-P1; privacy §7 backups; audit DB-01) |
| `notifications_0001` (notifications) | core_base, identity_0001, orgs_0001 | in-app inbox and delivery log |
| `support_0001` (support) | core_base, identity_0001, orgs_0001, security_0001, commerce_0001, admin_0001 | support_tickets, support_ticket_messages, support_user_notes |
| `support_0002` | – | FR-SUP-001 categories (`certificate`, `college_access`, `appeal`) + SLA queue index `ix_st_due_id` |
| `support_0003` | core_base_0002 | **security-owned revision on the support branch:** `purge_closed_cases` retention (privacy D8, §7) — `maint.closed_case_attachments`, `maint.clear_closed_case_attachments`, `maint.purge_closed_cases`; `p_maint` policies on `account_restrictions`, `unblock_requests`, `support_tickets`; `retention_policies` job `purge_cases` renamed `purge_closed_cases` (D8) and D8 rows added for `security_cases`, `case_notes`, `case_decisions`, `account_restrictions` |

**Why `support_0003` is on the support branch (deliberate).** The purge needs `support_tickets` (support_0001) and `retention_policies`/`policy_settings` (admin_0001, a dependency of support_0001). As `security_0003` it needed cross-branch `depends_on` entries back to revisions that themselves depend on `security_0001`, which made Alembic's head bookkeeping fail nondeterministically on a fresh database (`KeyError: 'security_0001'`, hash-seed dependent). On the support branch its single `depends_on` is `core_base_0002`. Do not move it.

Tables created by these revisions whose DDL is not yet written out in §2–§13 (the migration is the reference): `break_glass_sessions` (admin_0002), `attempt_integrity_decisions` (assessments_0002), the four `coding_0002` tables, `gst_exports` (commerce_0002), `question_reports` (placement_0003), `mentor_notes` (mentoring_0001), `support_user_notes` (support_0001).

### 17.2 Tables added during implementation (not in Brief v0.4 §4)

To be ratified by the contract owner via `docs/contract-reconciliation.md`. DDL verbatim from the migrations.

```sql
-- coding_0001. Stand-in for S3 td-judge-private until S3/KMS credentials exist:
-- coding_test_cases.input_s3_key / expected_s3_key hold 'db:blob/<uuid>'. RLS: TN | PII: P0/P4
CREATE TABLE coding_test_case_blobs (
  id                  uuid PRIMARY KEY,
  coding_problem_id   uuid        NOT NULL REFERENCES coding_problems(id) ON DELETE CASCADE,
  organization_id     uuid        NULL REFERENCES organizations(id),
  ciphertext          bytea       NOT NULL CHECK (octet_length(ciphertext) BETWEEN 28 AND 8388636),  -- AES-256-GCM only
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ctcb_problem ON coding_test_case_blobs (coding_problem_id);

-- commerce_0001. Persisted daily gateway reconciliation reports (FR-COM-013). RLS: platform only | R-FIN | P0
CREATE TABLE reconciliation_runs (
  id           uuid PRIMARY KEY,
  gateway      text        NOT NULL,
  range_from   timestamptz NOT NULL,
  range_to     timestamptz NOT NULL,
  status       text        NOT NULL DEFAULT 'completed' CHECK (status IN ('running','completed','failed')),
  summary      jsonb       NOT NULL DEFAULT '{}',
  mismatches   jsonb       NOT NULL DEFAULT '[]',
  triggered_by text        NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- entitlements_0001. Institution seat waitlist (BR-ENT-16..18). RLS: U | R-ORG | P1
CREATE TABLE seat_waitlist (
  id                       uuid PRIMARY KEY,
  institution_contract_id  uuid        NOT NULL REFERENCES institution_contracts(id),
  organization_id          uuid        NOT NULL REFERENCES organizations(id),
  user_id                  uuid        NOT NULL REFERENCES users(id),
  status                   text        NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting','assigned','cancelled')),
  added_by                 uuid        NULL REFERENCES users(id),
  entitlement_id           uuid        NULL REFERENCES entitlements(id),
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_sw_waiting ON seat_waitlist (institution_contract_id, user_id) WHERE status = 'waiting';

-- security_0001. Per-user engine state (T-step-up / L2 bookkeeping). RLS: O | R-RISK | P3
CREATE TABLE security_user_state (
  user_id                   uuid PRIMARY KEY REFERENCES users(id),
  sharing_score             numeric(5,2) NOT NULL DEFAULT 0,
  takeover_score            numeric(5,2) NOT NULL DEFAULT 0,
  sharing_level             smallint    NOT NULL DEFAULT 0 CHECK (sharing_level BETWEEN 0 AND 4),
  l2_issued_at              timestamptz NULL,
  l2_passed_at              timestamptz NULL,
  step_up_required_since    timestamptz NULL,
  step_up_cleared_at        timestamptz NULL,
  last_evaluated_at         timestamptz NULL,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now()
);

-- security_0001. DB sliding-window counters for AB-* rules (hashed source keys only). RLS: NONE | 2 days | P1
CREATE TABLE security_counters (
  counter_key   text        NOT NULL,
  bucket_start  timestamptz NOT NULL,
  count         integer     NOT NULL DEFAULT 0,
  PRIMARY KEY (counter_key, bucket_start)
);

-- security_0001. Event refs for "This wasn't me" (SEC-46). RLS: O | R-SEC | P1
CREATE TABLE security_notices (
  id               uuid PRIMARY KEY,
  event_ref        text        NOT NULL UNIQUE CHECK (event_ref ~ '^ACC-[0-9]{4}-[0-9A-HJKMNP-TV-Z]{6}$'),
  user_id          uuid        NOT NULL REFERENCES users(id),
  kind             text        NOT NULL CHECK (kind IN ('replay','new_sign_in','new_country')),
  rule_key         text        NOT NULL,
  auth_session_id  uuid        NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  acknowledged_at  timestamptz NULL,
  disowned_at      timestamptz NULL
);
CREATE INDEX ix_sn_user ON security_notices (user_id, created_at DESC);

-- security_0001. Security report exports (SEC-32). RLS: NONE (requester only via API) | 30 days | P3
CREATE TABLE security_report_exports (
  id                  uuid PRIMARY KEY,
  report_key          text        NOT NULL,
  requested_by        uuid        NOT NULL REFERENCES users(id),
  filters             jsonb       NOT NULL DEFAULT '{}',
  include_per_user_rows boolean   NOT NULL DEFAULT false,
  contains_pii        boolean     NOT NULL DEFAULT false,
  reason_code         text        NULL,
  reason              text        NULL,
  status              text        NOT NULL CHECK (status IN ('awaiting_approval','running','completed','rejected','expired','failed')),
  approval_request_id uuid        NULL REFERENCES approval_requests(id),
  approved_by         uuid        NULL REFERENCES users(id),
  row_count           integer     NULL,
  content             text        NULL,
  watermark           text        NULL,
  download_expires_at timestamptz NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  completed_at        timestamptz NULL,
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- security_0001. Bulk restriction lifts (SEC-44/45, dual control). RLS: NONE (API) | R-AUDIT | P0
CREATE TABLE security_bulk_lifts (
  id                  uuid PRIMARY KEY,
  selector            jsonb       NOT NULL,
  reason              text        NOT NULL,
  extension_credit    boolean     NOT NULL DEFAULT true,
  requested_by        uuid        NOT NULL REFERENCES users(id),
  approval_request_id uuid        NULL REFERENCES approval_requests(id),
  matched_restriction_ids uuid[]  NOT NULL DEFAULT '{}',
  status              text        NOT NULL CHECK (status IN ('awaiting_approval','running','completed','rejected','expired')),
  progress            jsonb       NOT NULL DEFAULT '{}',
  created_at          timestamptz NOT NULL DEFAULT now(),
  completed_at        timestamptz NULL,
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- analytics_0001. Builder watermarks. RLS: NONE (ops) | P0
CREATE TABLE analytics_job_state (
  job                  text        PRIMARY KEY,
  watermark            timestamptz NULL,
  last_run_at          timestamptz NULL,
  last_duration_ms     int         NULL,
  last_result          jsonb       NOT NULL DEFAULT '{}'
);

-- analytics_0001. Idempotent outbox consumption (app.core.outbox handlers). RLS: NONE | P0
CREATE TABLE analytics_consumed_events (
  outbox_event_id      uuid        PRIMARY KEY,
  event_type           text        NOT NULL,
  consumed_at          timestamptz NOT NULL DEFAULT now()
);
```

### 17.3 Deviation register (backlog §B)

| Module | Deviation as migrated | Where documented |
|---|---|---|
| core | `idempotency_keys.user_id` is a soft reference (kernel precedes identity); inline CHECKs became named constraints; uniqueness is `UNIQUE NULLS NOT DISTINCT` so system callers (NULL user) are deduplicated too | §2.3 DDL |
| identity | `mfa_factors.totp_confirmed_at` (pending vs confirmed TOTP enrolment); `guardian_consents.verification_method` adds `guardian_otp_declaration` (privacy doc §4 branch J, counsel question P-6) | §3 DDL, identity_0001 docstring |
| sessions / media | `user_devices.user_label` ≤ 60 chars; `playback_sessions.tab_id` (MED-04, silent same-session tab takeover); no `organization_id` on playback (O family) | §4 DDL |
| security | `account_restrictions` + `hc_rule`, `ruleset_version`, `rule_keys`, `reverify_device_ids`, `lift_pending_at`, end reason `deescalated`; `security_cases` + `high_risk_reasons`, `hc_rule`, `sla_alerted_at`, `escalated_at`, `panel_views`, `version` (ETag); `unblock_requests` + `appeal_used`, `info_requested_at`, `rejected_by`, `timeline`, `version`; `case_decisions.false_positive_rule_keys`; `security_signals.suppressed_by_decision_id`, `ck_sig_cat` admits `HC-01`/`HC-02`; `risk_rule_versions` reason `shadow_start`, retired versions skip the approval check, uniqueness via `ux_rrv_rule_semver` on `(coalesce(rule_id, nil uuid), family, semver)` and one active version per rule (`ux_rrv_active_rule`); `org_trusted_networks.decision_note`; `security_incidents.version` and `incident_ref` format CHECK; five impl. tables (§17.2) | §5 DDL, security_0001 docstring |
| orgs | Unnamed UNIQUEs are named (`uq_batches_org_code`, `uq_org_memberships_org_user`, `uq_bulk_import_jobs_org_sha`); length/slug CHECKs on names and slugs | §6 DDL |
| catalog | `courses.is_free`, `course_kind` default `self_paced`; `course_versions` draft metadata (`level`, `language`, `category`, `tags`, `certificate_rule`, `completeness_plan`, `change_type`, `created_by`, `submitted_by`, `submitted_at`, `ck_cv_published`, `ux_cv_one_draft`); position uniques `DEFERRABLE INITIALLY DEFERRED`; `ux_la_vdo` is per lesson `(lesson_id, provider_asset_id)` because drafts clone asset rows; `resources.access_level` (`public`/`signed_in`/`entitled`) with `is_public` derived (`ck_res_public`) | §7 DDL, catalog_0001 docstring |
| learning | `lesson_progress.watched_intervals`, `evidence`, `ck_lp_completed`; `assignments` + `lesson_id`, `allowed_file_types`, `late_penalty_pct`, `status`, `grades_released_at`, `ck_asg_target`; `assignment_submissions` + `rubric_scores`, `returned_reason`; `certificates.issue_source` (`rule`/`manual`), `ck_cert_revoke`; public certificate verification uses a named system context, not a SECURITY DEFINER function | §7 DDL, learning_0001 docstring |
| placement | `practice_sessions.served` jsonb (served-but-unanswered questions with server `served_at`, PLC-20); `ck_topic_depth`, `ux_topics_root_slug`; mentoring and résumé tables not created (PLC-36..52) | §8 DDL, placement_0001 docstring |
| assessments | Extra CHECKs (`ck_ta_scheduled`, override reason length, `marks_each > 0`, `attempts_allowed > 0`); `tests.integrity_settings` default built with `jsonb_build_object`; extra indexes (`ix_att_test`, `ix_att_bound_session`, `ix_ao_batch`, `ix_ta_test`, `ix_tests_org`) | §9 DDL |
| coding | `coding_problems.is_free`, `published_by`, `published_at`; `code_submissions.judge_provider` allows `'fake'` (FakeJudgeAdapter, never production), + `normalized_sha256` (plagiarism hook, `ix_cs_similarity`), `retry_count` (one automatic retry after `judge_timeout`), `max_score`, `notice`, `queue_name` CHECK, `ck_cs_custom_run`; `judge_languages.version_label`; `coding_test_case_blobs` (§17.2) | §10 DDL, coding_0001 docstring |
| commerce | `product_items.unit_price_paise` (mentor-session refund rule, FR-COM-008), `ck_pi_type`; `institution_contracts` + `price_per_seat_paise`, `billing_schedule`, `grace_days`, `reassignment_allowance`, `reassignments_used`, `seats_burned`, `version`, `terminated_at`, `ck_ic_reassign`, `ck_ic_terminated`; `invoices.ck_inv_total`, `ux_inv_tax_order`, `ux_inv_cn_refund`; `refunds.approval_request_id` now has an FK; `reconciliation_runs` (§17.2) | §11 DDL, `app/modules/commerce/models.py` |
| entitlements | `seat_waitlist` (§17.2); `ux_ent_coupon` | §11 DDL |
| analytics | heartbeats + `sample_interval_ms`, `editor_focused`, `route`, `topic_id`, `privacy_tier`; intervals + `last_sample_at`, `provisional_end`, `privacy_tier`, `built_at`, close reasons `blur`/`mode_change`/`gap`, mode CHECK, `active_s numeric(10,3)`; daily kinds `organization`/`lesson_asset` + `assessment_active_s`, `ck_dla_order`; weekly kind `organization`; `cohort_learning_aggregates.ck_cla_suppressed`; `topic_mastery` decayed sums `wa_num`/`wa_den`, band `insufficient_data`; `video_watch_coverage.duration_s` nullable + `lesson_id`, `covered_s`; `question_item_stats.n_updates`; dirty-day reasons `interval_rebuild`/`server_event`; ops tables (§17.2) | §12 DDL, `app/modules/analytics/README.md` |
| audit | Inline CHECKs and PK became named constraints (`pk_audit_log`, `ck_audit_log_*`); `ix_audit_seq` | §13 DDL |
| admin | `privacy_requests` + `details`, `export_payload`, `idempotency_key`; `request_ref` format CHECK; `export_job_id` soft (no `export_jobs` yet); v0.6 `erasure_ledger` (admin_0003) differs from the contract: unkeyed `SHA-256("erasure:<user_id>")` subject hash instead of HMAC(k_erasure), `scope` jsonb, `pending_modules` instead of `modules_completed`, no `verified_at`, platform-only RLS | §13.1 DDL |

### 17.4 Foreign keys: soft references and late FKs

**Soft references (column exists, no FK yet — the target table lives in a branch that does not precede this one).** Tagged `-- v0.5: soft reference` in the DDL: `idempotency_keys.user_id`; `courses.primary_topic_id`, `lessons.test_id` / `coding_problem_id` / `assignment_id`, `lesson_topics.topic_id`, `resources.company_id`; `enrolments.entitlement_id`, `assignment_submissions.code_submission_id`, `certificates.final_attempt_id`; `question_versions.coding_problem_id`; `test_assignments.course_id`; `coding_problems.primary_topic_id`, `code_submissions.attempt_id` / `practice_session_id`; `product_items.course_id` / `test_id` / `company_path_id` / `topic_id`; `entitlements.course_id`; `topic_mastery.topic_id`, `question_item_stats.question_version_id`; `privacy_requests.export_job_id`. A later cross-branch revision (`depends_on` both modules) should add them (backlog §A1).

**FKs added by a later `ALTER TABLE`** (same semantics as the DDL above): `courses.current_version_id` (catalog_0001), `questions.current_version_id` (placement_0001), `risk_rules.active_version_id` and `account_restrictions.decision_id` (security_0001), `consents.organization_id` (identity_0002), `company_path_steps.test_id` (placement_0002).

### 17.5 RLS as migrated

Families are applied by `app.core.migration_helpers.enable_rls(table, family)`: `ENABLE` + `FORCE` and one policy `p_<family>` for roles `td_app, td_readonly`, with the predicates of §2.2. The RLS lint in `apps/api/tests/core/test_rls.py` requires ENABLE + FORCE on every table that carries `user_id` or `organization_id`, which caused these deviations from the per-table tags:

| Table | Documented | As migrated |
|---|---|---|
| `verification_tokens`, `password_reset_tokens` | NONE | O (identity_0003); pre-auth routes run in a named system context |
| `approval_requests` | NONE (API-gated) | custom `p_apr`: USING requester OR platform OR own org; WITH CHECK requester OR platform (rbac_0003) |
| `payment_webhook_events`, `invoice_sequences`, `reconciliation_runs` | NONE (system) | `p_platform`: USING / WITH CHECK `app.is_platform()` |
| `analytics_dirty_days` | NONE (system) | O |
| `users` | O on id + org visibility | `p_users` USING `id = app.user_id() OR app.is_platform() OR app.user_visible_in_orgs(id)`; WITH CHECK own row or platform (org visibility is read-only) |
| `user_profiles` | O + org visibility | same pattern on `user_id` |
| `guardian_consents` | O (child_user_id) | `p_gc` on `child_user_id` |
| `organizations` | T on id | `p_org` USING `id = ANY (app.org_ids()) OR app.is_platform()` |
| `role_grants` | custom | `p_rg` USING user OR org OR platform; WITH CHECK org OR platform |
| `audit_log` | platform-only read | `p_platform_read` (SELECT, `app.is_platform()`); `p_sealer_read` / `p_sealer_insert` for `td_audit_sealer` |
| `*_default` partitions | – | each DEFAULT partition has its own ENABLE + FORCE and the parent's family; app roles reach rows only through the parent |

Tables without RLS (reference data, or API-gated with no tenant column): `outbox_events`, `audit_outbox`, `devices`, `roles`, `permissions`, `role_permissions`, `topics`, `companies`, `judge_languages`, `risk_rules`, `risk_rule_versions`, `case_notes`, `case_decisions`, `security_incidents`, `security_counters`, `security_bulk_lifts`, `security_report_exports`, `policy_settings`, `feature_flags`, `retention_policies`, `route_daily_aggregates`, `question_item_stats`, `analytics_ingest_rejections`, `analytics_job_state`, `analytics_consumed_events`.

### 17.6 Partitioning

Partitioned by `RANGE` as documented: `login_attempts` (`attempted_at`), `session_network_observations` (`first_seen_at`), `playback_sessions` (`started_at`), `security_signals` (`occurred_at`), `risk_evaluations` (`evaluated_at`), `attempt_events` (`occurred_at`), `analytics_events` (`event_ts`), `activity_heartbeats` (`event_ts`), `engagement_intervals` (`started_at`), `audit_log` (`occurred_at`). Each parent is created with a `DEFAULT` partition only. **v0.6 (DB-04):** monthly children are created by `maint.ensure_partitions` through the daily `td.core.maint_partitions` job (current month + 3 ahead, hardened like the DEFAULT partition; DEFAULT rows of the month moved, except `audit_log`) and expired children dropped by `maint.drop_expired_partitions` in `td.core.maint_retention` (§1.2, §1.3). `pg_partman` is not used. The jobs run only where `DATABASE_MAINTENANCE_URL` is configured.

### 17.7 Grants, append-only tables, triggers, sequences

- Default privileges: DML to `td_app`, SELECT to `td_readonly`. Append-only (UPDATE/DELETE/TRUNCATE revoked from `td_app`): `consents`, `login_attempts`, `security_signals`, `risk_evaluations`, `case_notes`, `case_decisions`, `attempt_events`, `entitlement_events`. DELETE/TRUNCATE revoked: `invoices`, `payment_webhook_events`, `certificates`, `role_grants`, `approval_requests`, `policy_settings`. `submission_results`: UPDATE revoked (immutable once judged).
- Reference data written only by migrations or seeds (INSERT/UPDATE/DELETE revoked from `td_app`): `roles`, `permissions`, `role_permissions`, `judge_languages`, `risk_rules`.
- `audit_outbox` / `audit_log`: ALL revoked from every app role, then `td_app` gets INSERT on `audit_outbox` and SELECT on `audit_log`, `td_readonly` SELECT on `audit_log`, `td_audit_sealer` SELECT/DELETE on `audit_outbox` and SELECT/INSERT on `audit_log`; `audit_log` UPDATE/DELETE/TRUNCATE blocked by `app.audit_log_immutable()` triggers (also on `audit_log_default`).
- Triggers: `trg_set_updated_at` (`app.set_updated_at()`) on mutable tables; `trg_qv_immutable` / `trg_qo_immutable` on published question versions and options.
- Sequence `commerce_order_number_seq` (order numbers); exclusion constraint `ex_price_overlap` on `prices` (needs `btree_gist`).

### 17.8 Planned — not yet migrated

v0.6 (2026-11-03): all nine tables previously listed here are now migrated — `mentor_slots`, `mentor_bookings`, `interview_feedback`, `resumes`, `resume_reviews` (mentoring_0001), `support_tickets`, `support_ticket_messages` (support_0001), `export_jobs` (analytics_0002), `erasure_ledger` (admin_0003, as-migrated DDL in §13.1). Their `-- STATUS` lines say so. Reserved names `placement_drives`, `drive_eligibility_rules`, `drive_shortlists` still have no DDL.
