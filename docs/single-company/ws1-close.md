# WS1 close-out (REMOVAL-PLAN §5 step 9) — PARTIAL, blocked by disk space

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
