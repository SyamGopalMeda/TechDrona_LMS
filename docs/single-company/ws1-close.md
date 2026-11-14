# WS1 close-out (REMOVAL-PLAN §5 step 9) — DONE (2026-11-08, see §5)

| | |
|---|---|
| Status | **Blocked.** C: reached 0 bytes free during the run and `techdrona-postgres-1` stopped. Per the rules the container was not restarted and nothing was deleted to make room. |
| Date | 2026-11-07 |
| Dev DB | `techdrona` not touched. Scratch DBs used: `techdrona_ws1_dump`, `techdrona_final_sc`, `techdrona_ws1_seeds`. |

## 1. What changed

### Migration `orgs_0003_rehome_and_lock` (now in the graph)
- File: `apps/api/migrations/versions/orgs_0003_rehome_and_lock.py` (from `pending/orgs_0003.py.txt`).
- `depends_on` = the 17 other **real** branch heads: `rbac_0004, identity_0005, sessions_0003, commerce_0004, admin_0004, ai_0002, catalog_0003, paths_0002, engage_0002, learning_0003, mentoring_0001, analytics_0003, support_0004, security_0003, placement_0005, assessments_0004, coding_0003`.
- Not listed (no such revision was needed): `learning_0004`, `notifications_0002`, `placement_0006`, `assessments_0005`, `coding_0004`.
- **Second Alembic 1.20 pitfall found:** a revision listed in `depends_on` must be a real row of `alembic_version` at upgrade time. "Effective heads" that another revision already depends on (`entitlements_0003`, `media_0001`, `notifications_0001`, `audit_0001`, `core_base_0002`) are not stored there. Listing one makes the merge step fail with `KeyError: 'media_0001'` in `update_to_step`; this was reproduced on the dump. They still run first, because each is an ancestor of a listed head. The rule from ws1.md still applies: no other revision may list `orgs_0002`.
- New step 0: deletes `policy_settings` rows for the retired key `risk.trusted_network_multiplier`. FORCE RLS is lifted only for that statement.
- `alembic heads` now shows a single head: `orgs_0003`. Every other branch is an "effective head".

### Cleanup
- `orgs/models.py`: removed the DEPRECATED college column mapping (`data_role`, `gstin`, `billing_*`, `state_code`, `contact_*`, `settings`), as WS2 asked.
- `sessions/models.py`: removed the `Device.shared_organization_id` shim (WS5).
- `core/errors.py`: removed `seat_pool_exhausted` and `reassignment_allowance_exhausted`, plus the matching assertion in `tests/core/test_errors_request_id.py` (WS2).
- `admin/policy.py`: removed `risk.trusted_network_multiplier` (WS5/WS3). It was never seeded, and `orgs_0003` deletes any stored row.
- `tests/_review_scratch/`: already gone.
- `tests/ai/test_app_gating.py`: no longer sends `organization_id`. Nothing left to do.

### Seeds (D7), done by the seeds sub-agent
- Changed: `app/seeds/dev_users.py`, the new `app/seeds/company_demo.py`, `coding_demo.py` (now has a production guard), `commerce_demo.py` (`main` now calls `guard()`), `tests/seeds/test_dev_fixtures.py`.
- `company_demo` was added to the seed order in `scripts/seed-dev.sh`, `seed-dev.ps1` and `reset-dev-data.ps1`.
- **Accounts (emails only, dev domain):**
  - Admin: `admin@`, `admin2@`, and `security@`, `security2@`, `finance@` (kept because `E2E_REVIEWER_A/B` and `E2E_FINANCE` use them).
  - `trainer@`, `evaluator@`, `content@`.
  - Students: `student@`, `restricted.`, `reverify.`, `suspended.`, `minor.`, `asha.student@`, `ravi.student@`.
- **Batches:**
  - `DEMO-CSE-27`: the trainer and evaluator grants are on this batch.
  - `DEMO-FS-26`: Ravi.
- **Demo content:**
  - A platform question bank.
  - An article published to a batch.
  - A path with youtube-nocookie and Google Docs embeds, allocated to `DEMO-CSE-27`.
  - An engage quiz.
  - `demo-batch-weekly-test` assigned to the batch.
  - A structured assignment with a submission waiting for the evaluator.
  - The corporate enquiry `TD-E-DEMO-000001`.
- **Legacy purge:** `dev_users.purge_legacy` finds the old `coordinator@` and `support@` accounts. It revokes their grants, ends their sessions and memberships, and deactivates them. It is idempotent.
- **Results:**
  - `tests/seeds`: 16 passed.
  - Related seed tests: 21 passed.
  - `ruff` and `mypy app` (260 files) are clean.
  - The standalone end-to-end seed run did not complete, because Postgres stopped.

## 2. Dump restore (`techdrona_ws1_dump`)
- Restored with `pg_restore` inside the postgres container from `backups/techdrona-dev-before-college-removal-20261106.dump`.
- `alembic upgrade heads` succeeded once `depends_on` had been trimmed as described above.
- Afterwards:
  - `alembic_version` holds only `orgs_0003`.
  - Live organizations: **1** (the company org `techdrona`, type `internal`). `demo-college` was deleted.
  - Live organization-scope grants: **0**.
  - Live grants: `super_admin` P ×2, `content_manager` P ×1, `trainer` batch ×1. The coordinator, finance, support and security grants were revoked by `rbac_0004`.
  - All 7 memberships belong to the company org.
  - Batch `DEMO-CSE-27` is kept.
  - FORCE RLS is still on for the tables checked: `organizations`, `batches`, `org_memberships`, `courses`, `tests` and `role_grants`.
- D7 on dev: restore, migrate, then re-seed. The seed's legacy purge deactivates the removed demo accounts.

## 3. Full suite: baseline only, before the test conversions
- Command, on a fresh DB with `orgs_0003`:

  ```
  TD_TEST_DB_NAME=techdrona_final_sc TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest -q
  ```

- Result: **747 passed, 40 failed, 181 errors** in 12 min 58 s. The migration chain itself succeeded on the fresh DB.
- Dominant cause, about 970 log hits: `ck_org_single_company`. The tests that still create a second organization (`tests.identity.factory.make_org`, and org "B" in `tests/placement/world.py`) are now correctly refused by the singleton lock.
- Affected suites: engage, assessments, placement, sessions, mentoring, support, learning, authz matrix, rbac (`test_rbac.py`, `test_w2a_adm41.py`), coding, admin and integration.
- **Not done (blocked):**
  - Converting those tests to `company_org()` plus a second batch. Files: `tests/identity/factory.py`, `tests/placement/world.py`, `tests/rbac/test_rbac.py`, `tests/rbac/test_w2a_adm41.py`, `tests/analytics/*`, `tests/learning/*`, `tests/coding/*`, `tests/admin/*`.
  - The final full-suite run.
  - `ruff` and `mypy` over the whole tree.
  - The RLS family `U` review.
  - The WS6 request that `GET me/grants` return `/evaluator` in `portals` (`sessions/login.py` `PORTALS`).

---

## 4. Resume (2026-11-08) — first pass blocked (Docker down); completed in §5

| | |
|---|---|
| Status | **Blocked for DB work.** During this session the Docker Desktop engine went away (`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`); port 5432 is now answered by a different, native Windows Postgres (rejects the techdrona credentials). Per the rules Docker/containers were **not** started. Dev DB `techdrona` was only read (policy/grant listings). |

### 4.1 Test conversions (task 1) — code-reviewed
Already done by the paused agent (files dated 2026-11-07 17:44–19:24): `tests/identity/factory.py` (`company_org()`, no `make_org`), `tests/placement/world.py` (A and B are both the company org; isolation is cross-**batch**: `trainer_b`/`student_b` live in `batch_b`), `tests/analytics/conftest.py` (`make_org` returns `COMPANY_ORG_ID`), rbac, authz matrix, admin, learning, coding, engage, assessments, placement suites. Re-check now: no test inserts into `organizations` or builds `Organization(...)`; no synthetic foreign org ids. No further deletions in this pass (earlier deletions are listed in ws1.md / ws2–ws5.md).

### 4.2 Evaluator portal (task 2) — automated-tested (earlier run), code-reviewed
`sessions/login.py` `PORTALS["evaluator"] = "/evaluator"`, `LANDING_ORDER` includes evaluator; `GET /me/grants` builds `portals` from `PORTALS`. Covered by `tests/rbac/test_rbac.py::test_evaluator_portal_and_landing` (evaluator → `/evaluator`; evaluator+trainer → `["/evaluator", "/trainer"]`).

### 4.3 RLS family `U` review (task 3)
- **Finding:** 52 `p_u` policies on the dev DB (attempts, attempt events/responses/results/grades/overrides/integrity, assignment submissions/responses/regrades, code submissions, certificates, enrolments, lesson/path progress, practice, engage participants/responses, mentor bookings, interview feedback, question reports, recommendations, topic mastery, analytics events/heartbeats/intervals/aggregates incl. partitions). Predicate `user_id = me OR organization_id = ANY(app.org_ids()) OR platform`. With one company org every batch **student** has the company org in `app.org_ids()`, so at DB level any batch student could read every batch-mate's org-attributed rows. The app layer filters by user/batch (and engage participant reads run in `system_context`), so this was a defence-in-depth hole, same class as the `users` hole `identity_0005` closed.
- **Fix:** new migration `apps/api/migrations/versions/orgs_0004_u_family_staff_only.py` (revises `orgs_0003`; `alembic heads` = `orgs_0004` only). Adds `app.caller_is_org_staff()` (active `staff` membership in one of `app.org_ids()`, or a live non-student grant carrying that org — trainer/evaluator batch grants do), no row argument so it is evaluated once per statement, and `ALTER POLICY p_u` on every table/partition: org branch now also requires `app.caller_is_org_staff()`. Own rows and platform bypass unchanged; downgrade restores. `maint.ensure_partitions` copies the parent policy to new partitions. `app/core/migration_helpers.py` gains family `US` (the new predicate) for future tables; `U` is kept verbatim so historic migrations replay.
- **Test:** `tests/identity/test_u_family_rls.py` (every `p_u` has the staff guard in USING and WITH CHECK; a student cannot read or write a batch-mate's row; staff by grant and by membership can; a revoked grant loses access). Passing — see §5.

### 4.4 Seeds standalone (task 4) — see §5.3
Runner prepared (scratch, not in repo): migrates a template DB `techdrona_rd_seedtpl`, then for each seed creates `techdrona_rd_seed_<name>` from it, runs the seed alone, drops it, then runs the full chain twice on `techdrona_rd_seed_chain` (idempotency). Env override swaps only the database name of the `.env` URLs; it asserts the base DB is `techdrona` and never connects to it.

### 4.5 Full suite (task 5)
- Run 1 (fresh `techdrona_rd_backend`, before `orgs_0004` existed): reached **96 %** of ~970 tests with **3 failures** shown as `F` (at ~22 %, ~51 %, ~66 %), **0 errors**, before Docker went away; the process was then killed, so no summary/test ids were captured. Versus the baseline (747 passed / 40 failed / 181 errors) the second-org errors are gone.
- `ruff check .`: pass. `ruff format --check .`: 512 files formatted. `mypy app`: no issues in 260 files (re-run after the pause).
- **Still to do once Docker Desktop is up:** full suite on fresh `techdrona_rd_backend` (now including `orgs_0004` + the new test), identify and re-run the 3 failures alone, run the seed runner, then drop `techdrona_rd_*` (never `techdrona_test`).

## 5. Completion (2026-11-08, Docker back; project Postgres on port 15432)

### 5.1 Alembic fresh-DB bug found and fixed — automated-tested
- Run 2 (fresh `techdrona_rd_backend`) errored on every test: `alembic upgrade heads` failed with `KeyError: 'security_0001'` in `update_to_step`. It depends on the hash seed: seeds 8, 9 and 10 fail, others pass. It **predates `orgs_0004`**: removing `orgs_0004` still fails with seeds 8 and 9. It is the same class as the earlier `support_0003` pitfall (docs/audit/fixes/w3be.md).
- Cause: `core_base_0002` listed `security_0001` in `depends_on`. In some orders Alembic deleted `security_0001` from `alembic_version` before `security_0002` (down `security_0001`) ran.
- Fix: `apps/api/migrations/versions/core_base_0002_maint.py` now depends on `security_0002` instead, with a comment. Its DDL is unchanged. The dev DB is not affected: all these revisions are already applied there, and only `orgs_0004` is pending.
- Verified: a fresh migrate passes with `PYTHONHASHSEED` 1–16. Full suites also ran with seeds 8 and 9.

### 5.2 Full suite — automated-tested
| Run | Setup | Result |
|---|---|---|
| 3 | fresh DB, `PYTHONHASHSEED=8`, after 5.1 | **973 passed, 4 failed** (22 m 38 s) |
| 3a | the 4 failures alone | the same 4 failed (deterministic, not flaky) |
| 4 | fresh DB, `PYTHONHASHSEED=9`, after the fixes below | **977 passed, 0 failed** (18 m 44 s) |

The 4 failures and how each was handled:
1. **Real authz gap, fixed in code.** `assessments/test_attempts.py::test_trainer_scoping_and_cross_tenant_assignment`: batch B's trainer **could assign batch A's test** to their own batch (201). The old org boundary used to separate batches, but in a single company every test shares the org. Fix in `app/modules/assessments/studio.py::create_assignment`: an org-owned test may be assigned only by a caller for whom `can_read_test` holds; anyone else gets 404 (no disclosure). The test's 404 assertion is unchanged and now passes.
2. **Fixture now creates the DB grant.** `coding/test_w2a_access.py::test_batch_trainer_reads_own_batch_submissions_only`: the trainer existed only as a synthetic `Principal`, with no `role_grants` row. `orgs_0004` requires that a staff member really exists, so the test now creates the real batch grant. The 200/404 assertions are unchanged.
3. **Status code changed from 404 to 403; access is still denied.** In a single company the other batch's row is no longer hidden by RLS, so the batch-scope check answers instead. This is the same status that the existing `trainer_a2` and `submissions` assertions already expected.
   - `engage/test_engage.py::test_authz_student_admin_and_cross_batch`: trainer B on launch, control and presenter now gets 403.
   - `learning/test_learning.py::test_assignments_submission_grading_release_override`: trainer B on assignment PATCH now gets 403.
   - In the assessments test, trainer B on the studio test GET gets 403, and the test still never appears in B's list.
   - Student B opening batch A's test gets 403 `entitlement_required` with no test body.
   - No assertion was deleted.
- `ruff check .` passes. `ruff format --check .` reports 512 files already formatted. `mypy app` reports no issues in 260 files.

### 5.3 Seeds on empty scratch DBs — automated-tested
I migrated a template DB and then ran each seed alone on a fresh copy of it (env override: only the database name changes; `APP_ENV=dev`):
- `rbac_seed` and `commerce_demo` succeed standalone. `dev_users` also succeeds standalone; it prints the dev TOTP secrets, which are not reproduced here.
- `catalog_demo`, `placement_demo`, `coding_demo`, `security_demo`, `e2e_demo` and `company_demo` stop with a clear `RuntimeError: <email> not found - run python -m app.seeds.dev_users first`. This is their intended precondition.
- The full `seed-dev.sh` order ran twice on one DB, and every seed passed both times (idempotent).

### 5.4 Cleanup
- I dropped `techdrona_rd_backend` and `techdrona_rd_seedtpl`; the per-seed DBs were dropped by the runner. `techdrona` and `techdrona_test` were untouched.
- Earlier agents' scratch DBs remain, left for the coordinator: `techdrona_final_sc`, `techdrona_ws1_fix`, `techdrona_ws1_seedrun`.
- **`orgs_0004` is NOT applied to dev.** The coordinator applies it with `alembic upgrade heads`.
