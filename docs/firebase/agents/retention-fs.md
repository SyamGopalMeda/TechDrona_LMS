# Retention parity on Firestore (agent "retention-fs", 2026-11-13)

Goal: the Firebase stack deletes exactly what the VM's retention jobs delete, at equivalent timing,
and audits every run. The VM (Postgres, Celery, `TD_RUNTIME` ≠ firebase) is the spec and is unchanged.
Nothing was deployed.

## 1. Parity table

The VM's spec is `maint.run_retention` → `maint.purge_expired_rows` (migration `core_base_0002`)
and `maint.purge_closed_cases` (`support_0003`). The cutoff is `now() - min(active retention_interval)`.
The intervals below are the seeded defaults. Admins can change them in `retention_policies`.

| Table (policy) | VM deletes when | Firebase before | Firebase now |
|---|---|---|---|
| login_attempts (D7, 395 days) | `attempted_at < cutoff` | TTL `attempted_at + 395 d`. Same basis. Admin edits ignored. | Daily job, same predicate and live interval. TTL guard when the interval is longer than 395 days or uses months. |
| session_network_observations (D7, 395 days) | `coalesce(last_seen_at, first_seen_at) < cutoff` | TTL `first_seen_at + 395 d`. Equal in practice, because rows are insert-only with last = first. Admin edits ignored. | Job (`last_seen_at` is NOT NULL) + guard as above. |
| auth_sessions (D5, 395 days, "ended sessions") | `coalesce(ended_at, absolute_expires_at) < cutoff` | **Nothing.** No TTL, so sessions were kept forever. | Job. Sessions referenced by `test_attempts.bound_session_id` are kept, because the FK has no ON DELETE (see finding F1). |
| security_signals (D8, 180 days) | `occurred_at < cutoff` and the user has no case that is not closed or is on legal hold | TTL stamped with the interval in force at write time; `None` while held (`hold_evidence`/`release_evidence`). A longer interval, or a deactivated policy, let the TTL delete early. A shorter one did not apply to existing rows. | Job with the same held check (`security.public.evidence_holds`), plus a daily TTL guard. |
| risk_evaluations (D8, 180 days) | `evaluated_at < cutoff` and neither the user's cases nor the row's own `case_id` is open or held | As signals. `sync_evidence` checks only the user's cases, not the row's own `case_id`. | Job with both checks, plus the guard. |
| playback_sessions (D11, 180 days) | `started_at < cutoff` | TTL `started_at + 180 d`. Admin edits ignored. | Job + guard when the interval is longer than 180 days or uses months. |
| attempt_events (D15, 24 months) | `occurred_at < cutoff` | **Nothing.** The TTL policy is declared, but no writer stamps `expire_at`. | Job. |
| verification_tokens (TOKEN, 7 days) | `coalesce(consumed_at, expires_at) < cutoff` | TTL `expires_at + 7 d`. Consumed tokens were kept until `expires_at + 7 d` instead of `consumed_at + 7 d` (fewer deletions than the VM). | Job. The stamp is never early. Guard when the interval is longer than 7 days. |
| password_reset_tokens (TOKEN, 7 days) | as above | as above | as above |
| outbox_events (OPS, 7 days) | dispatched with `dispatched_at < cutoff`, or undispatched with `attempts >= 10` and `occurred_at < cutoff` | **Nothing.** Events were kept forever. | Job, same predicate (the 10 is fixed in the SQL, not `TD_OUTBOX_MAX_ATTEMPTS`). |
| idempotency_keys (OPS, 0 days) | `expires_at < cutoff` | TTL `expire_at = expires_at`. Admin edits ignored. | Job + guard when the interval is longer than 0 days. |
| notifications (D13, 1 year) | `created_at < cutoff` | TTL `created_at + 365 d`: one day early when the year spans 29 Feb. The dedupe marker has the same TTL. | Job; the dedupe marker is deleted with its notification. The guard always runs, because "1 year" is calendar months. It re-stamps the notification and its marker together. |
| security_cases, case_notes, case_decisions, account_restrictions, unblock_requests (D8; cases 1 year, unblock 365 days) | `purge_closed_cases` (weekly): 1 year after closure (3 years if disputed), not on legal hold, no open appeal, restriction, attachment or policy reference. Only the `security_cases` interval is read, on both stacks. | The Firestore implementation existed, but **raised `ValueError`** ("security_cases has no active retention policy"). A Firestore-only stack has no `retention_policies` documents, because there are no migrations. | Seeds the missing policy rows first, then runs the existing implementation. Audited per call as before. |
| (partitions) `core.maint_partitions` | premakes monthly partitions | Postgres-only. With no maintenance URL it logged `maintenance_skipped` as a warning. | Without Postgres: `partitions_noop` at **info** and returns `[]`; the task returns 0. Firestore has no partitions to premake, harden or move. |

Every run writes one audit record, with the same shape as the SQL entry point:
- action `maint.retention.purged`;
- actor role `system:maint.retention`;
- target `retention_policy`;
- `after_state = {table: {partitions_dropped: 0, rows_deleted: n}}`, listing only the tables that have an active policy.

It is written even when nothing is deleted.

## 2. What changed

| File | Change |
|---|---|
| `apps/api/app/core/retention_fs.py` (new) | The Firestore twin of `maint.run_retention`: 12 targets in SQL order, each with its predicate (basis time vs cutoff), keep rules, scans and TTL guard. |
| `apps/api/app/core/maintenance.py` | `run_retention`: no Firestore module (the VM) → the SQL path, byte-for-byte as before. Otherwise the SQL runs only if Postgres is enabled (hybrid), and then the Firestore job. `run_partition_maintenance`: a logged no-op without Postgres. |
| `apps/api/app/modules/admin/retention_defaults.py` (new) | The 17 `retention_policies` rows in their final post-migration state. |
| `apps/api/app/modules/admin/repo_firestore_privacy.py`, `admin/public.py` | New `ensure_retention_defaults` (Firestore: inserts missing `(table_name, data_category)` rows with deterministic ids, never changes existing rows; Postgres: no-op). New `active_retention_intervals`. |
| `apps/api/app/modules/security/public.py`, `security/repo_fs_engine.py` | `evidence_holds` / `held_subjects`: the two `NOT EXISTS` hold checks. |
| `apps/api/app/modules/security/repo_fs_controls.py` | `maintenance_runner` seeds the policy defaults before `purge_closed_cases`. This fixes the `ValueError`. |
| `apps/api/app/modules/assessments/public.py` | `attempt_bound_session_ids`: the `bound_session_id` FK check. |
| `firestore.indexes.json`, `apps/api/app/modules/{identity,media,sessions}/firestore.indexes.fragment.json` | `expire_at` gets an ASCENDING single-field index (it was `indexes: []`) on the 9 guarded TTL collections: login_attempts, session_network_observations, security_signals, risk_evaluations, playback_sessions, verification_tokens, password_reset_tokens, idempotency_keys, notifications. The TTL stays on. |
| `apps/api/tests/platform/test_retention_firestore.py` (new) | 12 tests, see §4. |
| `apps/api/tests/media/fs/test_playback_firestore.py` | The expected playback TTL override now includes the index. |

### How the job works

**Schedule.** Unchanged:
- `core.maint_retention` runs daily at 22:30 UTC on the `maintenance` queue;
- `lmsScheduler` hands it to `lmsTasksMaintenance`;
- `schedules.json` is untouched.

**Intervals.** They are read from `retention_policies` on every run, so an admin edit applies from the next run, as on the VM. Rules:
- The interval used is the minimum of the active intervals.
- Postgres calendar arithmetic applies: "1 year" and "24 months" are calendar periods.
- A table with no active row is skipped and left out of the summary.
- If a table has an active row with no interval, the run raises before deleting anything. On the VM this aborts the single transaction.

**Deletion.**
- Each table is scanned with one or two single-field range queries (`field < cutoff`, ordered by the field, pages of 100).
- Each page is filtered by the exact predicate and the keep rules.
- The rows are deleted in a transaction that re-reads them and re-checks the predicate.
- Deletions are capped at `batch * max_batches` per table (5000 × 200), as in the SQL.

**TTL guard.** It runs when a writer's fixed stamp could fire before the SQL predicate selects the row. That is the case when:
- the policy is longer than the writer's interval;
- the interval uses months;
- the policy is inactive;
- the table is security or notifications (always).

The guard reads the documents with `expire_at < now + 2 days` (the next run plus one missed run). It moves `expire_at` to the first instant the predicate is true, or to `None` while the row is kept. A stamp is only ever moved later, and only if it still has the value the query saw. That protects a `hold_evidence` that just cleared it.

If the `expire_at` index is not deployed yet, the guard logs `retention_ttl_guard_index_missing` at ERROR. The run still purges and audits.

**Timing vs the VM.**
- The VM deletes at the first 22:30 UTC run after a row becomes due. The Firebase job deletes at the same run.
- A TTL may delete the row earlier, between its due instant and that run (at most about a day). It never deletes before the predicate is true.
- TTL deletions are not counted in the audit summary, because Firestore does not report them. The job's own deletions are counted.

**Cost.**
- An empty run is about 16 scan queries, 3 guard queries (security ×2, notifications) and about 17 policy document reads, plus 1 audit write. That is roughly 36 billed reads a day.
- With data: about 2 reads and 1 delete per expired row (query plus transactional re-read).
- The guard reads each guarded document at most about twice near the end of its life.
- The guard writes only when a stamp must move.

## 3. Findings for the owner

| # | Finding | Action |
|---|---|---|
| F1 | **VM bug (not changed: VM rule).** `test_attempts.bound_session_id REFERENCES auth_sessions(id)` has no ON DELETE. When a due session is referenced by any attempt, `maint.purge_expired_rows('auth_sessions')` raises a foreign-key violation. That aborts the whole `maint.run_retention` transaction, so nothing is deleted from any table that day, or any later day. This starts about 395 days after the first test attempt on a session that later ended. Firebase keeps exactly those sessions and deletes the rest. | Owner: a migration (`ON DELETE SET NULL`, or a `NOT EXISTS` keep rule in the SQL predicate). Then decide whether Firebase should follow. |
| F2 | The `expire_at` indexes must be deployed: `firebase deploy --only firestore:indexes`. Until then the guard logs ERROR; rows are still purged correctly. | Coordinator, at the next index deploy. |
| F3 | There is no API to edit `retention_policies` on either stack: `GET /admin/retention-policies` only. Edits are direct row or document edits; both stacks read them on every run. | — |
| F4 | The seed re-creates a migration row that was deleted outright (there is no delete path). Deactivating a row (`is_active=false`) is honoured. | — |
| F5 | `notification_dedupe`, `security_counters`, `kv`, `analytics_*` and coding token TTLs are not `retention_policies` tables. They are Firestore-only stand-ins for Redis or unique indexes, so they are out of this scope. The exception is the notification dedupe marker, which now follows its notification. | — |

## 4. Tests and verification

New `tests/platform/test_retention_firestore.py`, run on the emulator with `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=retention_fs`:

1. `test_seed_defaults_match_the_migrations`: the 17 seeded rows equal the final state of `admin_0001`, `core_base_0002` and `support_0003`. The test parses the migration files.
2. `test_targets_mirror_run_retention_order`: the 12 targets match the SQL's table array.
3. `test_eligible_from_is_never_before_the_predicate`: covers 29 Feb, 31 Jan + 1 month, days, and 0 days.
4. `test_guarded_ttl_fields_are_indexed`: checks `firestore.indexes.json`.
5. `test_retention_deletes_exactly_the_sql_rows`: for every table, rows inside the window are kept and rows outside are deleted. It also covers:
   - auth sessions: ended recently but past their absolute expiry, still live, and FK-bound;
   - held evidence, both through the user and through the evaluation's own legal-hold case;
   - unheld and subject-less signals;
   - consumed and expired tokens;
   - outbox dead letters and pending events;
   - the notification with its dedupe marker.

   It also checks the exact per-table counts, the audit record (actor, target, `after_state`), and that held evidence is left with no TTL.
6. `test_admin_edited_intervals_and_ttl_guard`:
   - shortened `login_attempts` (30 days) deletes;
   - lengthened `notifications` (24 months) keeps the row, and the notification and marker TTLs are moved past the new due date;
   - deactivated `playback_sessions` keeps the row, removes its TTL, and is left out of the summary.
7. `test_active_policy_without_interval_fails_before_deleting`.
8. `test_empty_run_is_audited_and_cheap`: 12 zero rows, one audit per run, and the seed runs once.
9. `test_seed_never_overrides_existing_rows`: a backfilled 500-day row wins.
10. `test_purge_closed_cases_runs_on_an_unseeded_firestore`: the former `ValueError` path now purges the 400-day case and keeps the 30-day one.
11. `test_partitions_are_a_logged_noop_without_postgres`: the task returns 0 and logs exactly one info event, with no Postgres call.
12. `test_vm_keeps_the_sql_path`: with no Firestore modules, exactly one `maint.run_retention` SQL call and no Firestore retention; partitions still call SQL.

Verification results: see the final section, "Verification".

## Verification

- **New tests.** `tests/platform/test_retention_firestore.py`: 12 passed.
- **Full suite.** Run with `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=retention_fs`, one `tests/<dir>` at a time: **1010 passed, 0 failed**. That is the baseline 998 plus the 12 new tests.
  - Two emulator lock-contention tests failed once in the chunked run, while a Postgres run was loading the machine:
    - `tests/platform/test_kv_firestore.py::test_concurrent_incr_is_exact`
    - `tests/ai/fs/test_ai_usage_firestore.py::test_tutor_limit_concurrent_exactly_limit`
  - Neither touches retention, and both passed when rerun alone (2 passed).
- **Affected suites.** platform, security (including `fs/`), admin, media, notifications, core and assessments are all green within the run above.
- **`ruff check`.** Clean on every changed file. `ruff format` was applied to the changed files only.
- **`mypy` (unfiltered, `packages = ["app"]`, 434 files).** Only the 2 pre-existing errors: `admissions/rules.py:110` and `admissions/files.py:98`.
- **Postgres VM tests not run.** `tests/core/test_maintenance.py` and `tests/security/test_purge_closed_cases.py` need Postgres. On this machine they errored in fixture setup: the database could not be migrated, with or without these changes. They are not part of the 998 baseline.
  - The VM path is covered by `test_vm_keeps_the_sql_path`.
  - The SQL code path in `maintenance.py` is unchanged when no module is on Firestore.
