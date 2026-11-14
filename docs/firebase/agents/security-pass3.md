# Security pass 3

Agent: DATA-MONEY (reassigned), 2026-11-12.
- Scope: `security/{controls,reports,api_engine,tasks,retention}.py` and the new `security/repo_fs_controls.py`.
- Policy: tests run on the emulator only (`TD_TEST_NO_PG=1`, `TD_TEST_DB_NAME=secp3_test`).
- `TD_STORE_SECURITY` stays `postgres` until passes 1 and 2 are also done.

## 1. Can the shared SQL engine carry security? Yes, with backward-compatible extensions

The pass-3 files keep their SQL. Statements over security tables run on `app/core/firestore/sqlstore.py`, through the `repo_fs_controls.STORE` spec. That spec works on **the same documents** as the other security repositories:
- the `admin.fs_rows` codec of `security.store_specs`;
- `compose_id` keys;
- the collections are not registered a second time.

Engine extensions. Commerce and admissions are unchanged, and their tests are still green (§4).

| Extension | Why |
|---|---|
| `SqlModuleSpec.encode / decode / doc_id_of / register_collections` | Lets the engine use a module's existing document encoding (`fs_rows`: hex bytea, JSON text, ISO dates; datetime parts in composite ids) |
| RLS family `open` | Tables whose Postgres RLS is `NONE`: the API checks permissions, so the engine adds no row check |
| `x IN / NOT IN (SELECT …)` with an uncorrelated subquery | Evaluated once per statement (`reports._h1`: "highest scores without a case") |
| `MemoryTx` routes statements, `get` and `add` on engine-owned tables to the engine | On the stack without Postgres, security SQL that has not been ported yet (for example `engine.ruleset` called by `controls.engine_state`) also runs on Firestore, on the same documents |
| `store_db` / `store_principal_db` are built on `get_db` / `get_principal_db` | Dependency overrides and the Postgres request transaction still apply. When those yield `NO_POSTGRES`, a `MemoryTx` is used instead |

What the engine already covered: GROUP BY with `count/sum/min/max/coalesce`, joins, keyset, `UPDATE`/`DELETE`, and `FOR UPDATE` as optimistic locks.

Not carried by the engine, rewritten to the owner module's `public.py` with the same outputs (the Python reproduces the SQL's GROUP BY, HAVING and DISTINCT):

| Call site | Was | Now |
|---|---|---|
| `reports._h2` | `user_devices` `COUNT(DISTINCT user_id) … HAVING` | `sessions.public.list_user_devices` + per-device sets |
| `reports._h10` | `auth_sessions` GROUP BY tier/client, plus a subquery distribution | `sessions.public.list_sessions(active_at=…)` + `Counter` |
| `reports._engine_health` | `login_attempts` count | `sessions.public.list_login_attempts` |
| `reports` H6 and `controls` (engine state, bulk lift) | `ApprovalRequest` selects | `rbac.public.find_approvals` |
| `tasks` (decay, approval expiry, kill-switch ratification, heartbeat) | `AuthSession`, `User`, `ApprovalRequest` | `sessions.public.list_sessions`, `identity.public.get_user`, `rbac.public.find_approvals` + `save_approval` |
| `retention` | `maint.*` SQL functions (`td_maintenance`) | `repo_fs_controls.maintenance_runner` (below) |

No counters or rollups were needed: every GROUP BY in my files is evaluated by the engine or reproduced in Python, so the outputs are identical.

## 2. What is routed

- **`controls.py`.** Every security statement goes through the engine:
  - engine state;
  - kill switch (rule, `risk_mode`, `hc_all`);
  - rule versions (propose, simulate, shadow start and report, activation and rollback through approvals);
  - bulk lifts (request, check, execute, reject);
  - report-export execution and rejection.
  - A row returned by another security repository (`engine.rule_version` on Firestore) is joined to the transaction with `repo_fs_controls.persist_row`, so the kill switch's change to the version commits together with the `risk_rules` update.
- **`reports.py`.** All 13 report runners; the cross-module reads go through public APIs (§1).
- **`api_engine.py`.** Every route uses `StorePrincipalDbSession`. The incident routes keep data-ops' Firestore branch.
- **`tasks.py`.** Jobs run in `store_session()`; cross-module reads go through public APIs.
- **`retention.py`.** `default_runner()` picks `maint.*` on Postgres and `repo_fs_controls.maintenance_runner` on Firestore, which reimplements the three `support_0003` functions with the same rows and audit actions:
  - `closed_case_attachments`;
  - `clear_closed_case_attachments`;
  - `purge_closed_cases`, covering the disputed-case three-year age, active-restriction, open-appeal, attachment and `policy_settings` checks, plus reference detaching. It uses the new `support.public.detach_security_refs`.

## 3. Tests (emulator, no Postgres)

`tests/security/fs/test_pass3_controls_reports_http.py` and `test_pass3_kill_switch_http.py` run over HTTP through the real app, using data-ops' `fs_http` harness. Expected numbers are computed from the fixtures.

| Test | Proves |
|---|---|
| `test_dashboard_group_bys_match_fixtures` | `/security/dashboard`: open cases by status, active restrictions by level and pending appeals all equal `Counter`s over the fixtures |
| `test_engine_health_report_counts` | Report ENG: `level_distribution` and `signal_volumes` (GROUP BY on restrictions and signals) equal the fixtures |
| `test_rules_and_versions_listing` | `/security/rules` and `/security/rule-versions` |
| `test_report_exports_list_is_the_requesters` | `/security/reports/exports` |
| `test_retention_purge_runner_on_firestore` | The purge removes only the old closed case without blockers, together with its note and its ended restriction; a case with an active restriction and a young case stay |
| `test_kill_switch_one_rule` | The active version goes to `shadow` (`kill_switch`) and `risk_rules.active_version_id` is set to NULL in one commit, through idempotency on Firestore |

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=secp3_test .venv/Scripts/python -m pytest tests/security/fs/test_pass3_controls_reports_http.py tests/security/fs/test_pass3_kill_switch_http.py -q
  -> 6 passed
```

The regression run over commerce, admissions, `security/fs` and the boundary lint is in §4.

## 4. Regression and gaps

- **Regression.** `tests/commerce/firestore`, `tests/admissions/firestore`, `tests/security/fs` and the boundary lint: see the final summary for the counts. One known failure, `tests/security/fs/test_unblock_review_http_firestore.py::test_learner_unblock_lifecycle`, comes from `repo_fs_cases.py` (pass 1, still in progress: `UnblockRequestRow` has no `case_ref`). It is not caused by this pass.
- **Not covered by an HTTP test yet:**
  - rule-version propose / shadow / activation;
  - bulk-lift execution;
  - creating a report export;
  - the per-user reports (H1–H6, H9, H12).

  They route through the same engine, but they also depend on `security.evidence.read` checks via `rbac`, on approvals (rbac on Firestore) and on pass-2 `engine.*` helpers. Tests can follow once passes 1 and 2 land.
- **`has_perm(session, …)` for `security.evidence.read`** goes to rbac's store. On the harness, `FakeAuth` grants are not visible to it, so per-user reports answer 403 there.
- **`DISPUTED_AGE`**: fixed in round 5 (§8).
- **Retention reads `policy_settings` directly** (by `case_decision_id`) from the admin collection, read-only. Request to the admin owner: a `public` helper for this.
- **Shared engine file.** `app/core/firestore/sqlstore.py` is edited only by this agent. Passes 1 and 2 can use `repo_fs_controls.STORE` or `persist_row` for rows they hand to pass-3 code.

## 5. Round 2: the remaining flows, golden numbers, jobs

New tests (emulator only, no Postgres, `TD_TEST_DB_NAME=secp3_test`):

**`test_pass3_flows_http.py` (over HTTP).**
- **H1, top suspicious accounts.** The rows equal the open cases. `highest_scores_without_case` equals the user states with a positive score and no open case, sorted by score descending.
- **Rule versions.** Propose (201), then the version is listed, then start-shadow (200), then the shadow report (200).
- **Bulk-lift dry run.** The golden result is `matched == 2`, with excluded counts `{l4: 1, human_applied: 1, high_risk: 0, takeover: 0, pending_decision: 0}`. Only active engine L3 restrictions count; L2 and ended restrictions are not considered.
- **Export request.** Requesting an export of an aggregate report returns 202, and the export then appears in the requester's list.
- The route permission checks inside these routes (`policies.has_perm`, an rbac lookup) are answered from the test's `FakeAuth` grants, the same as the route-level `perm(...)` dependencies.

**`test_pass3_tasks_firestore.py`.** `tasks.run_job` with `postgres_enabled()` False:
- `security.purge_counters` deletes counters older than 2 days and keeps the newer one;
- `security.sla_breach_alerts` runs.

## 6. Round 3: approval-executed actions are all-or-nothing (access undo journal)

This answers data-access.md §9.
- **The engine records before-images.** `sqlstore.UnitOfWork.commit` keeps the before-image of every document it writes (rows, `uniq_*` reservations, counters, outbox; a created document has none). `undo_callback()` restores them all in one transaction.
- **Journal hook.** `register_journal(current, on_rollback)` connects the engine to the journal; security and commerce register `identity.fs_journal`. Every engine commit that happens while a journal scope is open registers its undo there.
- **`sqlstore.journaled_executor(store, job)`** wraps approval executors and reject hooks:
  - Postgres: unchanged.
  - Firestore: the executor's writes commit **inside** the decision's journal. When the decision route passes `NO_POSTGRES`, the executor gets its own `MemoryTx` in platform scope.
- **Applied to:**
  - security `_activate` (rule activation and rollback), `_ratify` (kill-switch ratification), `_execute_bulk` / `_bulk_rejected`, `_execute_export` / `_export_rejected`;
  - commerce `billing_approvals._execute`, `_on_reject`, `_execute_commerce`, `_reject_commerce`.
- **Direct multi-write routes** (kill switch, bulk-lift request, export request) carry `Depends(request_journal, scope="function")`. The engine commits at the end of the request, inside that scope, and the approval request that rbac created is undone together with it.

Forced-failure tests:

| Test | Proves |
|---|---|
| `test_pass3_journal_firestore.py::test_executor_writes_roll_back_with_the_decision` | The export rejection is committed inside the journal; a later failure in the decision restores `pending_approval`. Without a failure the rejection stays. |
| `test_pass3_journal_firestore.py::test_kill_switch_failure_after_writes_leaves_nothing` | The audit raises after the version and rule writes and after rbac's approval request. Over HTTP the result is: the version is still `active`, the rule still points to it, and **no** `risk.kill_switch.ratify` request exists. |
| `tests/commerce/firestore/test_journal.py` | A GST-export rejection rolls back with the decision; without a failure it stays. |

Regression: see the final summary.

## 7. Round 4: pass-2 requests on pass-3 code (security-pass2.md)

- **Evidence after a bulk lift.** `controls._execute_bulk` collects the users whose cases it closed. It then calls `repo_fs_engine.release_evidence(users)` through the new `sqlstore.after_commit` hook, so the call runs **after** the cases are committed (`release_evidence` recomputes from the cases). On Postgres the follow-up is not registered; it would be a no-op there.
  - The per-restriction savepoint in that executor now uses the engine savepoint (`secx.begin_nested`), so a failing restriction also rolls back its writes on Firestore (BL-05).
- **`legal_hold`.** Nothing in the pass-3 files sets or clears it (retention only reads it), so no `hold_evidence` / `release_evidence` call is needed here.
- **Nightly jobs.** The whole `decay_recompute` run (derivations plus evaluations) and the `heartbeat_batch` call run inside `async with fx.detector_scope():`. This matches Postgres, where the job's transaction rolls back as a whole.
- **Tests:** `tests/security/fs/test_pass3_evidence_firestore.py`.
  - The bulk lift calls `release_evidence` once, with both users, and at that moment both cases already read `closed` from Firestore.
  - The nightly job enters and exits exactly one detector scope.

## 8. Round 5: exact `interval '3 years'`, other intervals, `policy_settings`

**`interval '3 years'`.** `repo_fs_controls.disputed_cutoff(now, interval)` reproduces `now() - GREATEST(v_interval, interval '3 years')` exactly:
- **Ranking.** `GREATEST` ranks intervals the way Postgres compares them: on 30-day months, so `3 years` counts as 1080 days. The policy interval wins only when it is strictly longer.
- **Subtracting 3 years.** `minus_years` works on the calendar. The year moves back and the month, day and time stay. A day that does not exist is clamped to the end of the month: `2028-02-29 − 3 years = 2025-02-28`, the same as `'2028-02-29'::timestamptz - interval '3 years'`. It is computed in UTC, the server's session time zone. No new dependency was added; it uses the standard library's `calendar`.
- **The comparison** stays strict, as in the SQL: `closed_at < cutoff`.

**Tests: `tests/security/fs/test_pass3_disputed_age.py`, 7 tests, all passing.**
- `minus_years` on five dates: two leap-day clamps (2028-02-29 and 2024-02-29), 2028-03-01, 2027-02-28 23:59:59 and 2027-03-01.
- The `GREATEST` ranking: 365 days, exactly 1080 days, and 1100 days.
- An end-to-end purge with now = 2028-02-29 12:00. Of three disputed cases:
  - one closed 1 s before the 2025-02-28 12:00 cut-off is purged;
  - the one closed exactly at the cut-off is kept;
  - the one closed on 2025-03-01 is kept. The old 3×365-day approximation (cut-off 2025-03-01 12:00) would have purged it.

**Other intervals translated from SQL.** None of the other translated intervals use months or years:
- `ATTACHMENT_AGE` is `interval '90 days'`, a day interval, so it is exact.
- The `tasks.py` and `reports.py` windows were already Python `timedelta`s in the original code. The engine evaluates them in the same way.

There is one remaining limitation, outside my files. The policy interval comes from admin's `retention_policies` as a Python `timedelta`. That is asyncpg's decoding on Postgres, and the `fs_rows` `seconds` kind on Firestore. A policy stored as `'1 year'` (months) is therefore subtracted as a day count, not a calendar year. The Postgres function subtracts the raw interval. The seeded `security_cases` policy is the reference for this. Request to admin/data-access: also expose the interval's months, or store the policy in days.

**`policy_settings` helper.** `admin.public` has no `policy_settings` lookup by `case_decision_id` yet. Retention still reads the admin `policy_settings` collection directly, read-only (`repo_fs_controls._policy_referenced_decisions`). When data-access adds the helper (for example `admin.public.policy_settings_for_decisions(session, ids)`), switching to it is a one-line change in that function. **Open request to data-access.**

## 9. Round 6: admin interval helpers, composite keys, atomic audit and outbox

### Retention on the admin helpers
- **Retention interval.** It now comes from `admin.public.retention_interval(session, "security_cases")`, a `PgInterval` that keeps months, days and microseconds, with Postgres `interval_cmp` ordering and `min()`.
- **Ordinary cases.** The cut-off is `admin.public.subtract_interval(now, interval)`: months first with the end-of-month clamp, then days, then time. A `'1 year'` policy is therefore a calendar year.
- **Disputed cases.** `disputed_cutoff(now, interval)` takes a `PgInterval`; a `timedelta` is coerced with `PgInterval.from_timedelta`.
  - `GREATEST` ranks the two intervals with `interval_cmp`, where a month counts as 30 days, so `'3 years'` (`PgInterval(months=36)`) ranks as 1080 days.
  - On a tie, Postgres's `GREATEST` keeps its **first** argument, which is `v_interval`; this was corrected in this round.
  - The winning interval is then subtracted with `subtract_interval`.
  - `minus_years` is now a thin wrapper over `subtract_interval`.
- **`policy_settings` references.** They come from `admin.public.policy_case_decision_ids(session, ids)`. Retention no longer reads admin's collection directly.
- **Tests (`test_pass3_disputed_age.py`):**
  - **`'1 year'` policy across a leap day.** Now = 2028-02-29 12:00, so the cut-off is 2027-02-28 12:00. A case closed one second before it is purged. The case closed exactly at the cut-off is kept, and so is the one closed on 2027-03-01. A 365-day cut-off would have purged that last one.
  - **`GREATEST` cases:**
    - a 1-year policy, where 3 years wins;
    - a `timedelta` that has to be coerced;
    - a tie at 1080 days, where the policy wins;
    - 1100 days, where the policy wins;
    - 4 years, which gives the calendar date 2024-02-29.
  - The 3-year leap-day purge test runs on a `PgInterval(months=12)` policy.

### Engine fix: composite primary keys
- **`SqlStore.get`** compared only the first primary-key column. That caused a duplicate row or a 409 on composite-key tables.
- **New `pk_conditions(model, ident)`** builds one equality for **every** key column:
  - a scalar for a single-column key;
  - a tuple in key order, or a `{column: value}` mapping, for a composite key;
  - anything else for a composite key, or the wrong number of values, raises `ValueError`.
- **Other identity paths** (the identity map, `doc_id`, unique keys, conflicts, `persist_row`) already used all key columns, or now do.
- **Audit of the specs that use the engine:**

| Spec | Composite-key tables |
|---|---|
| commerce | `invoice_sequences (series, fiscal_year)` |
| admissions | none |
| assessments | `attempt_sections (attempt_id, test_section_id)`, `attempt_events (id, occurred_at)`, `attempt_item_grades (attempt_id, question_version_id)`. The one composite `get` is in `evaluation.py:340`, `AttemptItemGrade` with a tuple, and is now correct |
| analytics | none |
| security | `security_signals (id, occurred_at)`, `risk_evaluations (id, evaluated_at)`, `security_counters (counter_key, bucket_start)` |

- **Test:** `tests/commerce/firestore/test_engine_keys_and_buffers.py::test_composite_key_get_update_delete`.
  - Three `invoice_sequences` rows share the leading key column.
  - `get` by tuple and by mapping returns the right row; an unknown key returns `None`; a scalar is refused.
  - An update through the identity map changes one row, with no duplicate and no 409.
  - Deleting one row leaves the other two.

### The engine writes the request's audit rows and outbox events atomically (platform request)
- **The rule.** When a request buffer scope is open (`app.core.request_commit.is_open()`), the first unit of work that commits in `commit_all` takes the buffered audit rows and outbox events (`audit.pending_docs()`, `outbox.pending_events()`).
  - It writes them **in the same Firestore transaction** as the business rows, using `audit.write_pending` and `outbox.write_pending_events`.
  - After the commit succeeds it calls `mark_written` / `mark_events_written`.
  - If the commit fails, nothing is written and the buffers stay, so the request's error path drops them.
  - The undo journal also covers these documents.
- **Outbox events captured by a `MemoryTx`** are now written with core's `event_doc`, with the payload as JSON text in `payload_json` (the layout core's relay reads).
- **Tests:**
  - `test_buffered_audit_and_event_commit_with_the_rows`: the audit row and the event exist after the engine commit, the buffers are empty, and the payload is JSON text.
  - `test_failed_commit_writes_no_audit_and_no_event`: a citext unique violation fails the commit, and neither the audit row nor the event exists.

### Round-6 regression: every suite on the engine (emulator, `TD_TEST_NO_PG=1`)

| Suite | Result |
|---|---|
| tests/commerce/firestore | 31 passed |
| tests/admissions/firestore | 10 passed |
| tests/assessments/fs | 8 passed |
| tests/placement/fs | 21 passed |
| tests/security/fs (pass 3 and the other passes) | 74 passed |
| tests/analytics/fs | 15 passed |
| **Total** | **159 passed, 0 failed** |
