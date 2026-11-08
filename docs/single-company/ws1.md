# WS1: Foundation (RBAC, orgs, identity, sessions, core, seeds)

| | |
|---|---|
| Status | Done for steps 1–4. Step 9 (`orgs_0003`) is written and smoke-tested but is **not** in the Alembic graph yet. |
| Date | 2026-11-07 |
| Plan | `REMOVAL-PLAN.md` §1.2, §2, §2.4, §3, §4, §5 (steps 1–4 and 9), §6 WS1, and the owner decisions in §8 (D2, D3, D5, D6, D7) |
| Dev DB | Not touched. All migrations were run only on the scratch databases `techdrona_ws1`, `techdrona_ws1b`, `techdrona_ws1c` and `techdrona_ws1d`. |

## 1. What changed

### Core
- New file `app/core/company.py`. It exports:
  - `COMPANY_ORG_ID = 01930000-0000-7000-8000-00000000c001`
  - `COMPANY_ORG_SLUG`, `COMPANY_ORG_NAME` and `COMPANY_ORG_TYPE`
  - the helper `is_company_org()`
- `principal.py`, `db.py` and `migration_helpers.py` are unchanged.
- `ScopeRef("organization", …)` still works as an internal step of the scope chain.

### RBAC
- **`catalogue.py`, the single-company matrix:**
  - Five roles: `student`, `evaluator`, `trainer`, `content_manager` and `super_admin` (now named "Admin").
  - Columns are STU EVL TRN CM SA.
  - `REMOVED_ROLES` lists the five deleted roles. Every permission they held was moved to `super_admin` (D2). Admin cells that were BG (break-glass only), A (approver only) or R (read-only) became P where a folded role held the permission.
  - Admin also gained `test.assign`, `test.results.release`, `test.override.grant`, `path.manage` and `path.allocate` (D3).
  - Evaluator holds the 11 permissions from §4.2 plus `test.results.release` (D3). It is granted at B, or at platform scope.
  - Removed permissions (`REMOVED_PERMISSIONS`, 14 in total): every `org.*` permission except `org.read` and `org.member.read`, plus `rbac.grant.org_staff`, `contract.*`, `seat.*`, `audit.read.org` and `security.network.verify` (D5).
  - `organization` is no longer a grant scope. The allowed grant scopes are `GRANT_SCOPE_TYPES = platform, batch, course`.
  - `DUAL_ROLES = {super_admin}`, so dual control is now "two different admins". `EXCLUSIVE_ROLE_PAIRS = ()`.
- **`service.py`:**
  - `resolve_grant_scope` rejects `organization`.
  - The production rule in `check_sod` that kept finance and security roles apart was removed.
- **`router.py`:**
  - Only Admin can grant or revoke roles (`rbac.grant.manage` at P). The coordinator's "org staff" grant path is gone.
  - The `organization_id` filter on `GET /rbac/grants` is gone.
  - `GrantIn.scope_type` no longer accepts `organization`.
- **`seeds/rbac_seed.sync`:** skips roles that the current `roles.role_key` CHECK does not allow. Without this, the applied revision `rbac_0002` would fail on a fresh database when it tries to insert `evaluator`.

### Orgs
- **Deleted:** `lifecycle.py` and `csv_import.py`.
- **`router.py`** now serves only batches:
  - `GET /batches`: Admin sees every batch; a trainer sees the batches they hold a grant on.
  - `POST /batches`: `batch.create` at P. New batches are stamped with `COMPANY_ORG_ID`.
  - `GET` and `PATCH /batches/{id}`, `/archive`, `/members` and `/members/{uid}` are unchanged.
  - Adding members accepts `user_ids` and/or `emails`, and any account that is not deactivated or deleted. It creates or reactivates the `org_memberships` row: `member_type` is `student`, or `staff` for trainer and mentor members, and `source` is `staff`. A staff membership is never downgraded to student.
  - When a student's last batch membership is removed, their membership becomes `left`.
  - Removed: `/orgs/**`, `/invitations/**`, `/me/orgs` and `PATCH /me/orgs/{id}`.
- **`service.py`:**
  - `get_learner_org_context`, `active_student_org_ids` and `batch_org_for_member` keep their signatures. Public learners still get `None`.
  - New: `ensure_org_membership` and `end_student_membership_if_no_batches`.
  - Removed: `invite_domains`, `invite_domain_allowed` and `org_requires_mfa`.
- **`models.py`:**
  - `BulkImportJob` and `OrgInvitation` were removed.
  - The college columns of `Organization` are still mapped, marked DEPRECATED. They are dropped in `orgs_0003`, because WS2's `billing.py` still reads them.

### Identity
- `/me` no longer returns `organizations`.
- The consent purpose `college_data_sharing` was removed.
- `SignupIn.invite_token` was removed, and so was `WEB_ROUTES["invite"]`.
- `policy.get_policy`: precedence is now user > platform.
  - The `org_id` argument is still accepted but ignored.
  - New default key: `auth.require_mfa_students = False`.

### Sessions
- `PORTALS` and `LANDING_ORDER`:
  - Evaluator lands on `/evaluator` (changed at close-out, see ws1-close.md).
  - Removed portals: `/college`, `/mentor`, `/desk`, `/security` and `/finance`.
- Lab devices were removed:
  - `LAB_IDLE` is gone.
  - `counts_toward_cap` is always true.
  - Remember-device no longer checks for lab devices.
- Student MFA now reads the platform key, through `resolver.students_require_mfa()`.

### Seeds
- **`dev_users`** creates everything in the company org and its batch `DEMO-CSE-27`:
  - Admin accounts: `admin`, `admin2`, and `security`, `security2` and `finance`, which are kept as extra Admin accounts because the security, commerce and E2E fixtures use those addresses.
  - `trainer` at batch scope, `evaluator` at batch scope, and `content`.
  - Five students.
  - Removed accounts: `coordinator` and `support`.
- **`e2e_demo`:** the trainer test is now the company org's `demo-batch-weekly-test`.
- **`e2e_env`:** `E2E_COORDINATOR_*` was replaced by `E2E_EVALUATOR_*`.

### Docs
- `docs/role-permission-matrix.md`:
  - §3 is regenerated from `catalogue.py`.
  - §9 (portals) is rewritten.
  - A header note says §3, §9 and the catalogue take precedence over older prose. WS6 rewrites the rest.

## 2. Migrations

| Revision | Depends on | Effect |
|---|---|---|
| `orgs_0002_company_org` | `orgs_0001` | Inserts the company org. The upsert is idempotent; a pre-existing `techdrona` slug is renamed `-legacy-…`. Drops `org_invitations` and `bulk_import_jobs`. |
| `rbac_0004_single_company` | `rbac_0003`, plus `orgs_0001` and `sessions_0001` | See the list below. |
| `identity_0005_single_company` | `identity_0004`, plus `orgs_0001` and `rbac_0001` | Rewrites `app.user_visible_in_orgs` (§2.4). Adds a `NOT VALID` purpose CHECK that rejects new `college_data_sharing` consents. `college_name_text` is kept (D6). |
| `sessions_0003_drop_lab_devices` | `sessions_0002` | Drops `devices.shared_*` and `ck_dev_shared`. |
| `orgs_0003_rehome_and_lock` | **Pending**: `docs/single-company/pending/orgs_0003.py.txt` | See below. |

**What `rbac_0004` does:**
- Widens the `role_key` CHECK. Removed role keys stay valid only for historic rows.
- Converts live trainer grants at organization scope into batch grants on that organization's non-archived batches.
- Revokes the grants of removed roles. The reason is `college_removal` for the coordinator and `role_consolidation` for the other four. Nobody is promoted to Admin automatically.
- Revokes every other live grant at organization scope.
- Adds `ck_rg_no_live_org_scope`.
- Revokes the sessions of every affected user and sets `sessions_valid_after`.
- Calls `sync()`, then deletes the permissions removed from the catalogue.
- Deletes removed role rows that no grant references. A referenced row is kept, renamed "… (removed)" and left with no allowed scopes.
- Expires pending `org.suspend` and `commerce.contract.terminate` approvals.
- Re-points pending approvals whose approver was a removed role to `super_admin`.

**What `orgs_0003` will do:**
- Resolves unique conflicts first. Memberships are de-duplicated; a duplicate batch code gets the suffix `-<oldslug>`.
- Sets `organization_id` to the company org in every table that has the column, except `audit_log`, `consents` and `outbox_events`. User triggers are disabled during the update.
- Deletes the other organizations. One that is still referenced is soft-deleted instead.
- Drops the college columns.
- Adds `ck_org_single_company` and `ux_organizations_singleton`.

**How the migrations run:**
- Data steps run as the table owner. Each step lifts FORCE RLS only on tables that have it, then restores it in the same transaction.
- Every `downgrade()` restores the schema only. Its docstring points to the backup dump for the data.

**Verified:**
- A fresh `alembic upgrade heads` passes, in every test run.
- `rbac_0004` was checked on legacy-shaped data in `techdrona_ws1d`: a coordinator, a finance admin, a trainer at organization scope, and pending approvals. The grants were converted and revoked, the sessions rotated, the role rows deleted or kept, and the approvals expired or re-pointed, all as expected.
- `orgs_0003` was applied to `techdrona_ws1c` with seeded college rows. Re-homing worked, the duplicate batch code was renamed, the old org was soft-deleted (a consent still references it), the columns were dropped, the singleton index was created and FORCE RLS was still on.

**Alembic pitfall (version 1.20):** no revision may list `orgs_0002` in `depends_on`; use `orgs_0001` instead. A cross-branch dependant makes Alembic drop `orgs_0002` from `alembic_version`, and the merge step `orgs_0003` then fails with `KeyError: 'orgs_0002'`. This was reproduced and fixed here. The dev database's `alembic_version` also lacks `orgs_0001` and `sessions_0002`. The single-parent upgrades still work in that case, because Alembic takes its create-branch path.

## 3. Shims and API for the other workstreams

- **`app.core.company.COMPANY_ORG_ID`.** Use it in place of any organization taken from a request.
- **`app.modules.rbac.catalogue`:**
  - `admin_roles()` returns `frozenset({"super_admin"})`. Use it as the approver set, the alert recipients and the full-IP roles.
  - `successor_role(old)` returns `"super_admin"` for every removed role.
  - `ADMIN_ROLE`, `REMOVED_ROLES` and `REMOVED_PERMISSIONS`.
- **`orgs.service`:** the signatures of `get_learner_org_context`, `batch_org_for_member` and `active_student_org_ids` are unchanged. New: `ensure_org_membership(session, org_id, user_id, member_type=, added_by=)`.
- **`sessions.models.Device.shared_organization_id`:** a read-only, always-NULL `column_property` shim, so WS5's lab branches keep working. Delete it once WS5 has removed them.
- **`identity.policy.get_policy(..., org_id=...)`:** still accepted and ignored. The resolver is now called with `org_id=None`.
- **Tests:**
  - `tests.identity.factory.company_org()` is new.
  - `make_org()` is DEPRECATED. A second organization stops working once `orgs_0003` runs.

## 4. References other workstreams must fix

Line numbers are from 2026-11-07. Wherever a removed role appears, replace it with `admin_roles()` or `"super_admin"`.

### WS2 (commerce and entitlements)
- **`commerce/billing_approvals.py:66-68`:** `frozenset({"finance_admin"})` becomes `admin_roles()`.
- **`commerce/router.py:583,675,871`:** `required_approver_role="finance_admin"` becomes `"super_admin"`.
- **`commerce/router.py:1050-1516`:** the routes use the deleted `contract.*` permissions. Delete them, as the plan says.
- **`commerce/billing.py:310-367`:** reads `org.gstin`, `state_code`, `billing_*` and `billing_address`. Delete this (it blocks `orgs_0003`).
- **`entitlements/router.py:320`:** `principal.has_role("security_reviewer")` becomes `super_admin`.
- **`entitlements/router.py:390-443`:** `seat.*` routes. Delete them.
- **`wiring.py`:** the `orgs.member_removed` event is no longer produced, because the org member-removal route is gone. Remove the COM-04 hook.

### WS3 (admin and AI)
- **`admin/accounts.py:47` `BREAK_GLASS_ROLE = "security_reviewer"`:** the role is gone, and Admin already holds every permission that was break-glass only. Retire break-glass, or elevate to `super_admin`.
- **`admin/accounts.py:50,573,631`:** use `admin_roles()`.
- **`admin/models.py:113` and `admin_0002`:** the `elevated_role` default is `'security_reviewer'`. Change it in a new `admin_*` migration.
- **`admin/policy.py:144-154`:** the role namespace map for `security_reviewer` and `finance_admin`.
- **Register the policy key** `_K("auth.require_mfa_students", False, "bool")`. Until then Admin cannot set it through the API; the identity default is false.
- **`ai/router.py:45` `WRITE = "org.settings.update"`:** the permission was deleted, so nobody can write until this changes. Suggestion: `feature_flag.manage` at P.
- **`/orgs/{org_id}/privacy-requests`** in `admin/router.py`: delete it, as the plan says.

### WS4 (learning delivery)
- **`notifications/consumers.py:183-221`:** `finance_admin_ids` needs to look up `super_admin` instead.
- **`tests/rbac/test_w2a_adm41.py`** (owned by WS1) uses `visibility: "org_only"` and an `organization_id` body field. Tell WS1 or the coordinator when you remove them; the test needs updating then.
- **Mentor duties** now belong to Admin, which holds `mentor.*` at P (D2).

### WS5 (assessment, practice and operations)
- **`audit/router.py:90-91`:** `_ROLE_FAMILIES` and `FULL_IP_ROLES` use the removed roles.
- **`security/api_engine.py:416,448`:** `security_reviewer`.
- **`security/api_engine.py:521,547,584,609`:** the trusted-network routes use the deleted `security.network.verify` and `org.settings.update` permissions. Delete them (D5).
- **`security/cases.py:346,373,690,782`:** the approver strings and `has_role("security_reviewer")` checks.
- **`security/controls.py:152,554,722,736,746`:** the approver sets.
- **`security/reports.py:7`:** a docstring mentions the removed role.
- **Lab-device code:** `security/signals.py:347-386,933,1063`, `unblock.py:140,460,824` and `timeline.py:272`. These use the `Device.shared_organization_id` shim, which is always NULL.
- **`support/service.py:61-68`:** `support_agent`, `finance_admin` and `security_reviewer` lanes.
- **`tests/placement/world.py`:** builds org B, which stops working once `orgs_0003` runs. The authz suites use it.

### WS6 (web, OpenAPI, docs, E2E and CI)
- **Portals:** Evaluator lands on `/evaluator` (close-out). `/me/grants` returns portals from `/app`, `/evaluator`, `/trainer`, `/studio` and `/admin` only.
- **`/me`:** no longer returns `organizations`.
- **Removed:** `/me/orgs`, `PATCH /me/orgs/{id}` and `/invitations/*`.
- **Signup:** `invite_token` is now rejected, because the schema forbids extra fields.
- **Batches API:** `GET` and `POST /batches`. The members body takes `emails` as well as `user_ids`.
- **RBAC API:** `GET /rbac/grants` has no `organization_id`, and `scope_type=organization` gives a 400 or 422.
- **E2E:** use `E2E_EVALUATOR_*` instead of `E2E_COORDINATOR_*`. The trainer test slug is now `demo-batch-weekly-test`; it is mentioned in `e2e/staff-portals.integration.spec.ts:74`.
- **`docs/role-permission-matrix.md`:** sections 2, 4–8 and 10 still contain multi-organisation prose.

### Tests of other workstreams that still use removed roles
Grep for these strings: `finance_admin`, `support_agent`, `security_reviewer`, `placement_mentor`, `college_coordinator`. Section 5 lists the results of running every other suite.

## 5. Test results (real runs)

All runs used scratch databases created from scratch (`TD_TEST_RESET_DB=1`), migrated with `alembic upgrade heads`.

- `ruff check .` passes.
- `ruff format --check .` passes; 496 files are already formatted. (The three `tests/_review_scratch` files were reformatted, and noqa comments were added for their pre-existing F811 errors.)
- `mypy app` passes: no issues in 257 source files.
- `rg college_coordinator apps/api/app` matches only `rbac/catalogue.py`, in `REMOVED_ROLES` and a docstring.

### 5.1 WS1 suites

The baseline before any change was 276 passed.

Command, from `apps/api`:

```
TD_TEST_DB_NAME=techdrona_ws1 TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/rbac tests/orgs tests/identity tests/sessions tests/authz tests/seeds tests/core -q
```

Result: **285 passed, 1 failed** in 8 min 32 s.

- **The failure:** `identity/test_phase_b_identity.py::test_sec05_duplicate_signup_matches_timing_and_cookies`. The duplicate-signup request took 1.94 s and the new-signup request 1.13 s, a gap of 0.81 s against the 0.5 s limit.
  - **Cause:** a cold-start cost on the first signup in the process. Profiling showed the first request costs about 6 s on its own and the second 0.45 s. The rate-limit check, `resolve_device` and the mail send were each 18 ms or less.
  - **Fix:** the test now sends an unmeasured warm-up signup first. The module re-run then gave **12 passed**.
- **Authz suites:** `tests/authz` alone gave **13 passed**: the 11-principal matrix, the every-route check and the object-level check.

**Deleted tests:**
- `tests/orgs/test_lifecycle.py`
- `tests/orgs/test_orgs.py`
- `tests/orgs/test_w2b_fixes.py`
- `tests/orgs/test_audit_fixes.py`

The batch tests and the BE-02 helper tests moved to `tests/orgs/test_batches.py`.

**New or converted tests:**
- **`tests/orgs/test_batches.py`:**
  - the college routes return 404 or 405;
  - Admin creates and lists batches;
  - non-admins are refused;
  - accounts are added by id or e-mail, and the membership follows the batch membership;
  - a trainer manages only their own batch;
  - batch lifecycle, moves and PATCH;
  - the shims.
- **`tests/identity/test_single_company_rls.py`** (§2.4 at the database level, as `td_app`):
  - a student cannot read another student in the same batch, or a public learner;
  - a student can read staff, whether staff by membership or by grant;
  - staff can read members;
  - a revoked grant stops counting as staff;
  - a new `college_data_sharing` consent is rejected.
- **`tests/rbac/test_rbac.py`:** 5-role seed parity, the matrix for each role, evaluator and Admin spot checks, cross-batch scope, Admin-only grants, refusal of `organization` scope and of removed roles, and dual control with two admins.
- **MFA:** the per-org MFA test became the platform `auth.require_mfa_students` test.
- **Sessions:** the support-agent tests became Admin tests. Admin's step-up window is 300 s, and the beyond-quota reset is audited.
- **`tests/seeds`:** a new single-company seed test.
- **Authz matrix:** the CRD column became EVL, and `other_coordinator` became `other_evaluator`.

### 5.2 Other workstreams' suites

These were run only to show what WS1 breaks. Command:

```
TD_TEST_DB_NAME=techdrona_ws1b ... pytest tests --ignore=<the 7 WS1 folders>
```

Result: **540 passed, 103 failed** in 24 min. No baseline was taken for these suites, so some failures may be older.

| Cause | Count |
|---|---|
| `NoResultFound`, from the test factory granting a removed role (no `roles` row) | 38 |
| `TypeError: 'shared_registered_by' is an invalid keyword argument for Device`, in the lab-device helpers of `tests/security/helpers.py` | 36 |
| 403 for removed roles or removed permissions | 14 |
| 422 | 5 |
| 404 | 2 |
| `ck_rg_no_live_org_scope` (a grant made at organization scope) | 2 |
| Other | 2 |

Failures by suite:

| Suite | Failures | Owner |
|---|---|---|
| security | 49 | WS5 |
| admin | 12 | WS3 |
| mentoring | 10 | WS4 |
| analytics | 7 | WS5 |
| assessments | 7 | WS5 |
| support | 7 | WS5 |
| engage | 2 | WS4 |
| notifications | 2 | WS4 |
| placement | 2 | WS5 |
| ai | 1 | WS3 |
| catalog | 1 | WS4 |
| learning | 1 | WS4 |
| media | 1 | WS4 |
| paths | 1 | WS4 |

Each owning workstream converts its tests: remove role → `super_admin`, lab devices → deleted, coordinator → Admin or Trainer.
