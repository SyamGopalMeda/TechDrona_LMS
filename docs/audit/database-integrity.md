# Audit — Database schema and data integrity (area `database`, prefix `DB-`)

Auditor: database audit agent, 2026-11-03. Phase A (audit only — no source/migration/doc edits).

Method: fresh database `techdrona_audit_database` created and migrated via the pytest conftest (`TD_TEST_DB_NAME=techdrona_audit_database TD_TEST_RESET_DB=1`, `tests/core/test_ids_time_money.py`), then introspected with SQL as `td_owner` (and the bootstrap superuser only where `FORCE RLS` blocked the owner). Alembic driven through the API with the conftest URL pattern. Concurrency/grant probes: `apps/api/tests/_audit_scratch/database/test_db_probes.py` (committed engine, real pooled app engine). Helper scripts (SQL runner, Alembic runner, ORM-vs-DB diff) are in the auditor's scratchpad and are not part of the repo.

## Coverage inventory

| Feature/Req ID | Requirement source | Code location | Audit method | Result |
|---|---|---|---|---|
| `alembic upgrade heads` from empty | ADR-0009, conventions §4 | `apps/api/migrations/` | Fresh reset and migrate | Verified OK (34 revisions, 141 tables + 10 DEFAULT partitions) |
| Multiple heads / branches | conventions §4 | `alembic heads`, `alembic current` | Alembic API | Verified OK (20 branch heads, all applied, no unmerged problems) |
| Downgrade paths | ADR-0009 | every revision `downgrade()` | `downgrade base` then `upgrade heads`, twice, on own DB | Verified OK (left 1 table, `alembic_version`; re-upgrade restored 152 relations, 125 permissions, 9 roles) |
| ORM vs. migrated-schema drift (`alembic check`) | conventions §4 | `migrations/env.py`, `*/models.py` | `alembic check` + `compare_metadata` | Issue DB-08 |
| RLS ENABLE+FORCE on tenant tables | schema §2.2, §17.5 | `core/migration_helpers.enable_rls` | `pg_class`, `pg_policy` | Verified OK: every table with `user_id`/`organization_id` is covered except the documented NONE set. Issues DB-05, DB-04 |
| td_app not owner, no BYPASSRLS | schema §1.2 | roles | `pg_roles`, `pg_tables` | Verified OK (all 152 relations owned by `td_owner`; no td_* role has super/bypassrls) |
| Least-privilege grants (append-only, audit) | schema §17.7 | migrations | `information_schema.role_table_grants` + live probe | Verified OK (append-only sets, audit_log UPDATE/DELETE denied, sealer only INSERT/SELECT audit_log + SELECT/DELETE audit_outbox). Issue DB-04 (new partitions) |
| `maint.*` SECURITY DEFINER functions, `td_maintenance` | schema §1.2, §17.6 | core_base | `pg_proc` | Not built (schema `maint` is empty; td_maintenance has no privileges) — DB-02 |
| Money as integer paise ≥ 0 | schema §1.1 | commerce_0001 | `pg_constraint` | Issue DB-07 |
| Enum CHECKs | schema §1.1 | all | `pg_constraint` sample | Verified OK (text + CHECK used throughout) |
| Indexes on FK / hot paths (autosave, heartbeats, sessions, risk signals) | schema | migrations | `pg_indexes` | Hot paths Verified OK (`attempt_responses (attempt_id, question_version_id)`, `ix_hb_user_time`, `ux_as_token`, `ix_sig_user_time`, `ux_att_one_open`). Unindexed FKs: DB-10 |
| Partitioned tables | schema §1.3, §17.6 | 10 parents | `pg_inherits` | Issue DB-04 (DEFAULT only; blocks future partitions) |
| Soft cross-module references | schema §17.4 | migrations | catalog query | Issue DB-09 |
| Cascade rules that could delete user data | — | FKs | `pg_constraint confdeltype` + grep for deletes | Verified OK (31 CASCADE FKs; no app code deletes users, enrolments, test_attempts, code_submissions, coding_problems or orders) |
| Idempotency keys | API §1.8 | `app/core/idempotency.py` | Code read | Verified OK for semantics; no expiry purge — DB-02 |
| Outbox at-least-once + dedupe | schema §2.3 | `app/core/outbox.py`, analytics consumer | Code read | Verified OK (`FOR UPDATE SKIP LOCKED`, savepoint per event, handlers in the same transaction as `dispatched_at`; analytics dedupes on `analytics_consumed_events`). No purge — DB-02 |
| Webhook dedupe | COM WH-01 | `commerce/webhooks.py:115-139` | Code read + index | Verified OK (`UNIQUE (gateway, event_id)` + `ON CONFLICT DO NOTHING`; processing row-locked) |
| Race: coupon caps | FR-COM-007 | `commerce/pricing.py:134-150` | Code read | Verified OK (coupon row `FOR UPDATE` on order creation) |
| Race: seat pool | BR-ENT-15 | `entitlements/service.py:931-960` | Code read | Verified OK (`lock_contract` row lock + `ux_ent_seat`) |
| Race: attempt start / attempt counts | ASM | `assessments/attempts.py:392-455` | Concurrent probe | Issue DB-03 (integrity holds, but 500s) |
| Race: enrolment | LRN-03 | learning router | Concurrent probe | Issue DB-03 |
| Transaction boundaries | ADR-0003 | `core/db.py` | Code read (no `.commit()` in modules; one transaction per request) | Verified OK. RLS-context weakness: DB-06 |
| Retention / purge jobs (raw 90 d, HB 35 d, logs 395 d) | privacy §7, schema §1.3-1.4 | `analytics/jobs.py:1085-1167`, `analytics/params.py:89-95` | Code read + grant probe | Analytics part Verified OK (35 d / 90 d / 396 d / 730 d / 180 d). Everything else Not built — DB-02 |
| Erasure + `erasure_ledger` (DPDP s.12) | privacy §5, §7 | `admin/privacy.py:167-173`, `admin/router.py:624-629` | Code read + grep | Issue DB-01 |
| Seeds dev/test only | conventions | `app/seeds/*` | grep | Verified OK with a caveat (each demo seed guards on `is_production`; only `rbac_seed` is imported, by migration `rbac_0002`, which is intended reference data). Caveat in DB-11 |
| Schema doc §17 accuracy | schema §17 | docs | Table/revision diff | Issue DB-11 |

---

### DB-01: Privacy erasure deletes nothing; erasure ledger missing; request still marked "completed"
- Severity: High
- Status: Confirmed
- Component: `apps/api/app/modules/admin/privacy.py:167-173` (`execute_erasure`), `apps/api/app/modules/admin/router.py:624-634` (privacy complete endpoint); `apps/api/app/modules/analytics/jobs.py:1170` (`erase_user`, never called)
- Requirement: privacy-and-data-retention.md §5 (Erasure within 30 days of cooling-off), §7 job `account_erasure` ("call each module's `privacy_provider.delete()`"), CCP-P1 `erasure_ledger`; schema §17.8
- Repro: read code; `grep -rn "erase_user\|erasure_ledger" apps/api` (the only hits are the test, the definition and a docstring); DB: no `erasure_ledger` table among the 141 migrated tables.
- Expected / Actual: Expected the user's personal data to be erased or anonymised across modules (keeping only legal holds), with a ledger so backup restores re-apply deletions. Actual: `execute_erasure` revokes sessions and sets `users.status='deactivated'`, nothing else. Email, phone, profile (name, DOB), analytics rows, attempts and so on stay intact. The request is then set to `status="completed"`, `completed_at=now`.
- Evidence:
  ```
  async def execute_erasure(session, user_id):
      n = await ss.revoke_all_sessions(session, user_id, "account_deleted")
      await session.execute(update(User).where(User.id == user_id).values(status="deactivated"))
      return n
  grep: tests/analytics/test_pipeline.py:21,579 | analytics/jobs.py:1170 (def) | admin/privacy.py:7 "the ``erasure_ledger`` are Planned"
  ```
- Root cause: The privacy-provider fan-out and the ledger were deferred, but the endpoint still completes the request.
- Recommended fix: Add a `privacy_provider` registry (export/delete per module) and call it from `execute_erasure`, starting with `analytics.jobs.erase_user`, identity anonymisation (email/phone/name/DOB → tombstone) and the learning/assessment anonymisation. Add the `erasure_ledger` migration (subject_hash, erased_at, scope). Until then, do not mark erasure requests `completed` (keep them `in_progress` or `blocked`).
- Suggested owner paths: `apps/api/app/modules/admin/privacy.py`, `apps/api/app/modules/admin/router.py`, new `apps/api/migrations/versions/admin_0003_erasure_ledger.py`, each module's `privacy.py`/service

### DB-02: Retention purges missing for every class except analytics; DB roles make them impossible as designed
- Severity: High
- Status: Confirmed
- Component: `apps/api/migrations/versions/core_base_0001_kernel.py` (schema `maint` created empty); `retention_policies` seed rows; Celery registrations (`modules/*/tasks.py`)
- Requirement: privacy §7 jobs `purge_auth_logs` (395 d), `purge_security_signals` (180 d), `expire_devices`, `purge_closed_cases`, `account_erasure`; schema §1.2 (`td_maintenance` + `maint.drop_expired_partitions`), §1.4 R-TOKEN (7 d), R-PLAY (180 d), R-ASSESS-EVT (24 mo), outbox dispatched rows (7 d), idempotency keys (24 h / 7 d), notifications (180 d)
- Repro: SQL on the migrated DB, plus probe `test_probe_grants_and_rls`
- Expected / Actual: Expected a scheduled purge for each retention class. Actual: the only purge is `analytics.retention_purge` (analytics tables, correct periods). Nothing purges `login_attempts`, `session_network_observations`, ended `auth_sessions`, `security_signals`, `risk_evaluations`, `playback_sessions`, `attempt_events`, `verification_tokens`/`password_reset_tokens`, `outbox_events` (dispatched or dead-letter), `idempotency_keys` (only removed when the same key is reused), `notifications` or `devices`. `retention_policies` names jobs that do not exist (`purge_auth_logs`, `purge_risk`, `purge_cases`). Append-only grants also stop `td_app` from ever deleting these rows, and the designed `td_maintenance`/`maint.*` route does not exist.
- Evidence:
  ```
  maint functions: (none)          schema maint ACL: ['td_owner=UC/td_owner']
  td_maintenance table grants: (none)
  GRANT_PROBE login_attempts DELETE (retention) => ERR permission denied for table login_attempts
  GRANT_PROBE security_signals DELETE (retention) => ERR permission denied for table security_signals
  GRANT_PROBE attempt_events DELETE (retention) => ERR permission denied for table attempt_events
  retention_policies: login_attempts|395 days|partition_drop|purge_auth_logs ; security_signals|180 days|purge_risk ; unblock_requests|365 days|purge_cases
  grep "purge_auth_logs|purge_risk|purge_cases" apps/api/app -> no matches
  ```
- Root cause: `pg_partman` and the `maint` functions are "Planned" (schema §17.6), and no row-delete fallback was added for these tables.
- Recommended fix: Add migration `core_base_0002_maint` creating `maint.drop_expired_partitions(regclass)` / `maint.purge_expired_rows(regclass)` as SECURITY DEFINER (owner `td_owner`, `search_path` pinned, EXECUTE only for `td_maintenance`) that read `retention_policies`. Add the missing `retention_policies` rows and a maintenance Celery queue/job per privacy §7 that writes an audit summary. Add a nightly `DELETE` of expired `idempotency_keys`, dispatched `outbox_events` older than 7 days, and expired or consumed tokens older than 7 days.
- Suggested owner paths: `apps/api/migrations/versions/` (new core/admin revision), `apps/api/app/modules/admin/tasks.py`, `apps/api/app/modules/sessions/tasks.py`, `apps/api/app/modules/security/tasks.py`, `apps/api/app/worker.py`

### DB-03: Concurrent attempt start / enrolment raise an unhandled IntegrityError (HTTP 500)
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/assessments/attempts.py:392-455` (POST `/api/v1/attempts`); learning `POST /api/v1/me/enrolments` (`learning/router.py:153`); `app/core/errors.py:265-284` (DB errors become `internal_error` 500)
- Requirement: API §1 error model (409 conflict codes, never 5xx for client races); SCN-02 multi-tab
- Repro: `TD_TEST_DB_NAME=techdrona_audit_database .venv/Scripts/python -m pytest tests/_audit_scratch/database -k race -s`. The probe sends 6 concurrent starts (or enrolments) for the same student and test (or course), each with a different Idempotency-Key, which is what a double-click from two tabs does.
- Expected / Actual: Expected one 201, with the others getting `active_attempt_exists` / `already_enrolled` (409) or a replay. Actual: one 201, and the five others fail with an `IntegrityError` that reaches the outermost handler, so a real client gets 500. Data integrity holds: exactly 1 attempt row, thanks to `ux_att_one_open` / `test_attempts_test_id_user_id_attempt_no_key` / `enrolments_user_id_course_id_key`.
- Evidence:
  ```
  UNHANDLED ['IntegrityError', 'IntegrityError', 'IntegrityError', 'IntegrityError', 'IntegrityError']
  ATTEMPT_RACE Counter({201: 1})   ATTEMPT_ROWS 1
  E sqlalchemy.exc.IntegrityError: ... duplicate key value violates unique constraint "test_attempts_test_id_user_id_attempt_no_key"
  UNHANDLED [5 x IntegrityError]  ENROL_RACE Counter({201: 1})
  E ... duplicate key value violates unique constraint "enrolments_user_id_course_id_key"
  grep IntegrityError apps/api/app -> only modules/security/cases.py:330
  ```
- Root cause: The `FOR UPDATE` on the open attempt locks nothing when no row exists yet, so both requests compute `attempt_no = max+1`. The DB unique constraint is the only arbiter, and its violation is not translated.
- Recommended fix: Serialise per `(test_id, user_id)`, for example with `pg_advisory_xact_lock(hashtext(test_id||user_id))` before the open-attempt check, or catch `IntegrityError` on these inserts and map it to `active_attempt_exists` / `already_enrolled`. Optionally add a generic handler that maps `UniqueViolation` to 409 `conflict`. Apply the same pattern to other `count-then-insert` sites.
- Suggested owner paths: `apps/api/app/modules/assessments/attempts.py`, `apps/api/app/modules/learning/service.py`/`router.py`, `apps/api/app/core/errors.py`

### DB-04: Partitioning is DEFAULT-only; new partitions would bypass RLS and append-only grants, and are blocked once data lands in DEFAULT
- Severity: Medium (latent; becomes High as soon as monthly partitions are created)
- Status: Confirmed
- Component: the 10 partitioned parents (`login_attempts`, `session_network_observations`, `security_signals`, `risk_evaluations`, `attempt_events`, `analytics_events`, `activity_heartbeats`, `engagement_intervals`, `playback_sessions`, `audit_log`); default privileges in `core_base_0001`; `sessions_0002_partition_rls.py`
- Requirement: schema §1.3 (monthly partitions, partition-drop retention), §17.5-17.6, privacy §7.1
- Repro: as `td_owner` on the audit DB:
  1. `CREATE TABLE login_attempts_2026_12 PARTITION OF login_attempts FOR VALUES FROM ('2026-12-01') TO ('2027-01-01')`, then inspect `pg_class`.
  2. Insert one October row (it lands in DEFAULT), then create the October partition.
- Expected / Actual: Expected new child partitions to carry ENABLE+FORCE RLS and no direct `td_app` grants (as the `*_default` children do), and monthly partitions to be creatable. Actual: (1) the new child gets `td_app=arwd` from the schema default privileges, including UPDATE/DELETE on an append-only table, with RLS off. `td_app` could read or modify other users' rows by naming the child directly. (2) Creating a partition fails once DEFAULT holds rows for that range.
- Evidence:
  ```
  login_attempts_2026_12 | rls=False | force=False | ['td_owner=arwdDxt/td_owner', 'td_app=arwd/td_owner', 'td_readonly=r/td_owner']
  login_attempts_default | rls=True  | force=True  | ['td_owner=arwdDxt/td_owner']
  ERR CheckViolation updated partition constraint for default partition "login_attempts_default" would be violated by some row
  extensions: plpgsql, pgcrypto, citext, btree_gist   (no pg_partman)
  ```
- Root cause: Partition hardening (revoke and RLS) is applied by hand to `*_default` only. The ALTER DEFAULT PRIVILEGES grant applies to every future table, and no premake exists.
- Recommended fix: Before any partition maintenance ships, create partitions only through a `maint` function that revokes `td_app`/`td_readonly` privileges and enables and forces RLS on each new child (or uses `pg_partman` with a template table carrying no grants). Premake future months now, while DEFAULT is still small, and add a step that moves DEFAULT rows into their range.
- Suggested owner paths: `apps/api/migrations/versions/` (new maint revision), `apps/api/app/core/migration_helpers.py`

### DB-05: RLS family O lets a learner modify or delete their own enforcement records
- Severity: Medium
- Status: Confirmed
- Component: policies `p_o` on `account_restrictions`, `security_cases`, `unblock_requests`, `security_user_state`, `security_notices`, `privacy_requests`, `consents` (append-only, so safe), with `td_app` holding UPDATE/DELETE on all of them except `consents`
- Requirement: schema §2.2 ("RLS is the tenant boundary"); security-threat-model (defence in depth); risk-engine restrictions must not be self-liftable
- Repro: probe `test_probe_grants_and_rls`. As `td_app` with only `app.user_id = <learner>` set, update and then delete the learner's own active `account_restrictions` row.
- Expected / Actual: Expected the learner context to have at most SELECT on restriction, case and engine-state rows (writes only in a system/staff context). Actual: both statements succeed.
- Evidence:
  ```
  account_restrictions | p_o | * | USING (user_id = app.user_id() OR app.is_platform()) WITH CHECK (same)
  GRANT_PROBE learner UPDATE own account_restriction => OK rowcount=1
  GRANT_PROBE learner DELETE own account_restriction => OK rowcount=1
  ```
- Root cause: Family O is applied `FOR ALL` with an identical USING and WITH CHECK, so ownership grants write access.
- Recommended fix: For security-enforcement tables, split the policy: `FOR SELECT USING (user_id = app.user_id() OR app.is_platform())` and `FOR INSERT/UPDATE/DELETE ... USING/WITH CHECK (app.is_platform())`. Revoke DELETE from `td_app` on `account_restrictions`, `security_cases`, `privacy_requests` and `security_incidents` (R-RISK / R-PRIV retention).
- Suggested owner paths: new `apps/api/migrations/versions/security_0002_rls_readonly_owner.py`, `admin_0003`

### DB-06: `system_context()` inside request handlers switches the rest of the transaction to platform scope
- Severity: Medium
- Status: Confirmed (code); exploitability depends on later queries in each handler (cross-check with the security area)
- Component: `apps/api/app/core/db.py:160-164`; 47 calls in request handlers (`grep "await system_context(session" modules/*/router*.py modules/*/api_*.py`) in admin, identity, learning, notifications, orgs, security, support. Example: `identity/router.py:415` (`mobile_send_otp`).
- Requirement: ADR-0003 / schema §2.2 (RLS as the tenant boundary); `commerce/pricing.py:42` shows the intended `as_system` scoped pattern
- Expected / Actual: Expected platform scope only for the specific statement, with the principal's context restored afterwards. Actual: `set_config(..., true)` lasts for the whole transaction, so every query after the call (including later reads of user-controlled IDs) runs with `app.is_platform=on` and RLS no longer limits it.
- Evidence: `system_context` body sets `is_platform=True` with transaction-local GUCs and has no restore. 47 request-path call sites. `as_system` (commerce) restores the context but without `try/finally`.
- Recommended fix: Replace bare calls in request paths with an `async with as_system(session, job, principal)` context manager in `core/db.py` (`try/finally` restoring `tenant_context`), and lint against bare `system_context` in router modules.
- Suggested owner paths: `apps/api/app/core/db.py`, router modules listed above

### DB-07: Several money columns have no `>= 0` CHECK
- Severity: Medium
- Status: Confirmed
- Component: `commerce_0001` — `order_items.unit_amount_paise`, `taxable_paise`, `discount_paise`, `total_paise`; `payments.fee_paise`, `tax_on_fee_paise`; `coupons.min_order_paise`
- Requirement: schema §1.1 (money as bigint paise); audit brief (paise ≥ 0)
- Evidence: catalog query `has_check=False` for exactly these 7 columns. `orders` (`*_paise >= 0`, `ck_order_total`), `invoices` (`ck_inv_total`), `payments.amount_paise > 0` and `refunds.amount_paise > 0` are correct. `order_items` has GST-split checks but no non-negativity check and no `total = taxable + gst` consistency check.
- Recommended fix: Add `CHECK (x >= 0)` on the 7 columns plus `ck_oi_total CHECK (total_paise = taxable_paise + cgst_paise + sgst_paise + igst_paise)` (validate after checking existing rows).
- Suggested owner paths: new `apps/api/migrations/versions/commerce_0003_money_checks.py`

### DB-08: ORM metadata diverges from the migrated schema; `alembic check` cannot detect drift
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/migrations/env.py` (no `include_object`/`compare_*` filters), all `app/modules/*/models.py`
- Requirement: conventions §4 (migrations are the source of truth; models must match)
- Repro: `alembic check` against the freshly migrated DB; `compare_metadata(MigrationContext, import_all_models().metadata)`
- Evidence:
  ```
  alembic.util.exc.AutogenerateDiffsDetected: New upgrade operations detected: [('remove_index', ... login_attempts_default ...
  Counter({'remove_index': 254, 'remove_fk': 225, 'remove_table_comment': 140, 'remove_constraint': 63,
           'add_constraint': 24, 'modify_type': 22, 'remove_table': 10, 'remove_column': 5, 'add_fk': 4, 'modify_nullable': 2})
  remove_column: devices.fp_epoch, devices.fp_hash, mfa_factors.webauthn_transports/webauthn_uv_required/webauthn_aaguid
  modify_nullable policy_settings.min_value/max_value: DB NULL, ORM NOT NULL
  modify_type e.g. users.email CITEXT(DB) vs TEXT(ORM); mfa_factors.webauthn_sign_count BIGINT(DB) vs INTEGER(ORM)
  ```
- Root cause: The models are thin mappings (no FKs, indexes or comments, different names for unique constraints), so autogenerate shows hundreds of diffs and real drift is hidden. No CI check exists.
- Recommended fix: In `env.py`, add `include_object` that skips `*_default` partitions and indexes, and `compare_server_default=False`. Map the 5 missing columns, the `CITEXT` type and the nullability. Then add a CI test that asserts `compare_metadata` restricted to columns, types and nullability is empty.
- Suggested owner paths: `apps/api/migrations/env.py`, `apps/api/app/modules/sessions/models.py`, `identity/models.py`, `admin/models.py`, new `apps/api/tests/core/test_schema_drift.py`

### DB-09: Cross-module soft references without FKs (backlog A1 still open)
- Severity: Medium
- Status: Confirmed
- Component: columns with no FK (catalog query). Cross-branch references that should get a late FK (schema §17.4): `courses.primary_topic_id`, `lessons.test_id/coding_problem_id/assignment_id`, `lesson_topics.topic_id`, `resources.company_id`, `enrolments.entitlement_id`, `assignment_submissions.code_submission_id`, `certificates.final_attempt_id`, `question_versions.coding_problem_id`, `test_assignments.course_id`, `coding_problems.primary_topic_id`, `code_submissions.attempt_id/practice_session_id`, `product_items.course_id/test_id/company_path_id/topic_id`, `entitlements.course_id`, `topic_mastery.topic_id`, `privacy_requests.export_job_id`, `idempotency_keys.user_id`. Further undocumented ones: `gst_exports.requested_by/approved_by/approval_request_id`, `account_restrictions.evaluation_id`, `attempt_integrity_decisions.security_case_id`. Denormalised RLS keys with no FK or consistency trigger: `attempt_responses/attempt_sections/submission_results/order_items.user_id, organization_id`.
- Expected / Actual: Expected a later cross-branch revision adding the FKs (schema §17.4). None exists, so the 34 revisions add no FK to these columns.
- Orphan-risk assessment: Highest risk is `product_items.*_id` and `entitlements.course_id`, where a mistyped or retired ID silently grants nothing or grants access to the wrong content. Next is `lessons.test_id/coding_problem_id`, where a broken lesson link renders 404. The denormalised `user_id`/`organization_id` on child rows decide RLS visibility, so a mismatch with the parent would expose or hide rows. Partitioned-table references (`*_session_id`, `event_id`) are soft by design.
- Recommended fix: Add one `zz_cross_module_fks` revision that `depends_on` all heads and adds the listed FKs `NOT VALID`, then `VALIDATE`. For denormalised RLS keys, add BEFORE INSERT/UPDATE triggers copying `user_id`/`organization_id` from the parent.
- Suggested owner paths: new `apps/api/migrations/versions/integration_0001_cross_module_fks.py`

### DB-10: About 150 foreign-key columns have no supporting index, including some hot lookups
- Severity: Low
- Status: Confirmed
- Component: catalog query for FKs whose column is not the leading column of any index (users excluded)
- Evidence (selection): `coupon_redemptions.order_id` (fulfil/release by order), `refunds.payment_id`, `payment_webhook_events.order_id/payment_id`, `orders.subscription_id`, `attempt_responses.question_version_id` (item analysis), `mentor_notes.mentor_booking_id`, `submission_results.test_case_id`, `coding_testcase_content_tokens.test_case_id`, `seat_waitlist.entitlement_id`, and `organization_id` on RLS-filtered tables (`test_attempts`, `enrolments`, `lesson_progress`, `attempt_results`, `auth_sessions`, `orders`, `payments`, `invoices`) that coordinator and finance views filter by.
- Recommended fix: Add indexes (`CREATE INDEX CONCURRENTLY`) for the lookups above, and partial or composite `(organization_id, …)` indexes on the large U-family tables.
- Suggested owner paths: new per-module migration revisions

### DB-11: Schema documentation §17 is stale; seed guard is a denylist
- Severity: Low
- Status: Confirmed
- Component: `docs/database-schema.md` §14, §17.1, §17.5, §17.8; `app/core/config.py:22,36`
- Evidence:
  - §17 says "24 revisions … 123 tables migrated". Actual: 34 revision files and 141 tables (plus 10 DEFAULT partitions).
  - §17.8 lists `mentor_slots`, `mentor_bookings`, `interview_feedback`, `resumes`, `resume_reviews`, `support_tickets`, `support_ticket_messages` and `export_jobs` as not yet migrated, but all are migrated.
  - No DDL anywhere in the doc for `attempt_integrity_decisions`, `break_glass_sessions`, `coding_drafts`, `coding_problem_validations`, `coding_reference_solutions`, `coding_testcase_content_tokens`, `gst_exports`, `mentor_notes`, `question_reports` or `support_user_notes`.
  - §14 tags `case_notes`/`case_decisions` as "O / app-gated", but they have no RLS (§17.5 is right).
  - `gst_exports` is the only table using `trg_gst_exports_updated_at`, and `video_watch_coverage`/`topic_mastery` have no updated_at trigger. Both are harmless because the jobs set `updated_at = now()`.
  - Seeds refuse only `APP_ENV in {prod, production}`, and `APP_ENV` defaults to `local`. A production task launched without `APP_ENV` would accept demo seeds, including the known `DEV_PASSWORD`.
- Recommended fix: Regenerate §17 from the migrations and add the 10 tables. Make the seed guard an allowlist (`local`, `dev`, `test`) or require `APP_ENV` to be set explicitly in production settings.
- Suggested owner paths: `docs/database-schema.md`, `docs/database-erd.md`, `apps/api/app/seeds/*.py`, `apps/api/app/core/config.py`

---

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | – |
| High | 2 | DB-01, DB-02 |
| Medium | 7 | DB-03, DB-04, DB-05, DB-06, DB-07, DB-08, DB-09 |
| Low | 2 | DB-10, DB-11 |

Verified OK:
- Upgrade from empty, and downgrade to base plus re-upgrade (twice).
- Single history with 20 branch heads.
- Ownership, roles, BYPASSRLS.
- Append-only and audit grants (audit_log UPDATE/DELETE denied even in platform context; td_app cannot read audit_outbox).
- RLS on every tenant table.
- Hot-path indexes.
- Webhook dedupe; coupon and seat locking; outbox claim and dedupe; idempotency semantics.
- Analytics retention periods (35 d / 90 d / 13 mo / 24 mo).
- CASCADE rules (no code path deletes parent user data).

Not tested / limits:
- No load or EXPLAIN testing on production-sized data (DB-10 is based on the catalog).
- Audit hash-chain verification was left to the audit area.
- The outbox handler side effects (emails sent inside the savepoint before commit can repeat on retry) are Suspected and were not probed.
- `alembic downgrade` was run only on `techdrona_audit_database`.
- Probes leave committed rows in `techdrona_audit_database` only.
