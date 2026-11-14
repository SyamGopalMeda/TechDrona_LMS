# role-api-audit agent: role-based access control of `/api/v1` (2026-11-13)

**Scope.** Every route of the FastAPI app (`create_app()`, `TD_ROUTER_SET=all`) was audited for
each role:

- `student`
- `trainer@batch`
- `evaluator@batch`
- `content_manager`
- `super_admin`

The Firestore code paths were compared with the SQL/RLS paths throughout.

**Not changed.** No deploys. `apps/web` and `apps/lms-spa` are untouched. `functions-lms/app` was
re-synced with `functions-lms/tools/build.py`.

## 1. Matrix summary

The routes were enumerated from the live route table, and each guard was read from its
dependency tree:

- `require_permission(...)` sets `td_permission`.
- `authenticated_router` adds `require_active_principal`.

### Guard types (600 method+path pairs)

| Guard | Routes | Notes |
|---|---:|---|
| `public` | 31 | Login/signup/verify, public catalog, health, admissions `/public/*`, webhooks. |
| Static `require_permission(perm, scope)` | 222 | Platform scope unless a batch, course or org resolver is given. 18 of these also need step-up (a no-op under `TD_SIMPLE_AUTH`). |
| `require_active_principal` only, with the check inside the handler or service | 347 | 117 are `/me/*` (owner-filtered). 230 are staff or shared surfaces that check in the service: `check_permission`, `ensure_permission`, `can_author`, `_ensure_grade`, `can_test`, `staff_scope`, owner checks. |

Route tags across all 600 routes:

| Tag | Routes |
|---|---:|
| default | 475 |
| account_status | 62 |
| public | 31 |
| l3_readonly | 21 |
| login_continuation | 5 |
| mfa_enrolment | 4 |
| consent | 2 |

### Static-permission routes each role can hold

This uses the catalogue (`role_permission_pairs`) at the role's own grant scope.

| Role | Holdable static routes (of 222) |
|---|---:|
| student | 0 (self-ownership only) |
| evaluator (batch) | 9 |
| trainer (batch / course) | 38 |
| content_manager (platform) | 49 (no finance, admin or security permissions) |
| super_admin (platform) | 211 |

The 11 routes `super_admin` cannot hold follow the matrix by design:

- `course.edit` on 6 studio course routes.
- `taxonomy.manage` on `/studio/topics`.
- `company_path.manage` on `/studio/companies`.

These are content_manager or trainer only. An admin cannot self-grant them: the only self-grant
allowed is `trainer@batch`, which does not cover platform courses.

### Guard type by module

| Module | public | perm | in-handler |
|---|---:|---:|---:|
| admin | 0 | 21 | 12 |
| admissions | 5 | 24 | 4 |
| ai | 0 | 5 | 2 |
| analytics | 0 | 5 | 10 |
| assessments | 0 | 0 | 39 |
| audit | 0 | 3 | 0 |
| catalog | 4 | 6 | 10 |
| coding | 0 | 0 | 23 |
| commerce | 4 | 27 | 17 |
| core (health) | 3 | 0 | 0 |
| engage | 0 | 0 | 17 |
| entitlements | 0 | 2 | 5 |
| hub | 1 | 0 | 2 |
| identity | 10 | 0 | 20 |
| learning | 2 | 35 | 44 |
| media | 0 | 0 | 7 |
| mentoring | 0 | 0 | 24 |
| notifications | 0 | 1 | 3 |
| orgs | 0 | 20 | 3 |
| paths | 0 | 0 | 27 |
| placement | 1 | 5 | 40 |
| rbac | 0 | 3 | 5 |
| security | 0 | 51 | 16 |
| sessions | 0 | 4 | 8 |
| support | 1 | 10 | 9 |

### How each check was done

Each of the 347 in-handler routes was traced end to end, including:

- the Firestore branch: `repo_firestore*.py`, `fs_*.py`, `store.py` dispatch, `if fs()`, and the
  SQL-on-Firestore engine `core/firestore/sqlstore.py`, which evaluates the full `WHERE` and
  emulates RLS through `visible()`.

For every route, the audit checked whether:

- a student can reach staff data;
- a batch-A trainer or evaluator can reach batch-B objects;
- content_manager can reach admin, finance or security data;
- `/me/*` or an id in the path can leak another user's rows;
- the Firestore branch drops a filter that SQL or RLS applies.

No Firestore branch was found that drops a user or batch filter that the SQL path applies; the
paths below are equivalent on both stores. The leaks found were logic or scope bugs that exist on
both stores (section 2).

## 2. Findings

### Fixed (each has a failing-then-passing test in `apps/api/tests/parity/test_rbac_audit.py`)

| # | Sev | Where | Role | What leaked / was allowed | Fix |
|---|---|---|---|---|---|
| F1 | **High** | `apps/api/app/modules/admissions/student.py:107-120` (`_mine`) via `/me/admissions`, `/me/admissions/plans/{slug}`, `POST /me/admissions/registrations`, `POST /me/admissions/claims` | any signed-in account, including a fresh self-signup | Website registrations were matched by `user.email` without checking `email_verified_at`. Anyone who signed up with a website registrant's address could read that registration (reg no, fee, balance, claims with UTR and staff notes). `POST /claims` also set `reg.user_id` to the attacker, so approval enrolled the attacker's account. | New `_verified_email(user)`: match by email only once the address is verified (all four call sites). Linking by `user_id` is unchanged. Verified owners see exactly what they saw before. |
| F2 | Med | `apps/api/app/modules/paths/service.py` `archive_path` (DELETE `/paths/{id}`, router `:259`) | trainer@A | Archiving a company path revoked **every** active allocation, including batch B's. `DELETE /path-allocations/{id}` itself requires `path.allocate` on that batch (SEC-01). | `archive_path` now runs `managed_allocation` (the same rule as direct revoke) on each active allocation first. Admins and the owning batch's trainer are unaffected. |
| F3 | Low-Med | `paths/service.py` `publish_article`, `managed_article(change=True)`; router `:371/380/393/402` | trainer@A | A trainer could publish an article to any batch or person, and edit, unpublish or delete articles published to other batches. | New `require_audience_scope`: `path.manage` on every target batch (platform covers all) and `can_allocate_users` for people. It is checked on publish (new audience) and on patch, unpublish, delete and publish of an already published article (current audience). Drafts are unchanged. |
| F4 | Med | `apps/api/app/modules/learning/structured_api.py:107-150` (`_ensure_grade`); `learning/router.py` `_submission_for_staff` and `grading_queue` | trainer or evaluator @A | A grade grant on the assignment's batch A returned "all allocations". It therefore also covered an allocation of the same structured assignment to batch B (evaluation, review, finalize, AI grading, regrade resolve, extensions). The legacy `/assignment-submissions/{id}` (+files, grade-override) and `/assignments/{id}/submissions` routes had the same problem. | When the assignment scope is a batch, the grant covers only allocations to that batch or user-list allocations. Other allocations need the grant on their own batch (it is still `None` = all when every allocation is covered). The legacy routes apply the same gradable set to structured assignments (new `gradable_allocations`). |

### Needs a decision (not changed)

| # | Sev | Where | Role | Issue | Suggested fix |
|---|---|---|---|---|---|
| D1 | Med | `apps/api/app/modules/orgs/router.py:313` `POST /batches/{id}/members` (`batch.member.manage` B) | trainer@A | A trainer can add **any** active account (a student of batch B, or staff as `student`) to batch A. The cross-batch check only runs with `move_from_batch_id`. The added user then falls under A's scope: batch reports, attendance, path user-allocations, and mentor notes via `is_assigned`. The 422 is also an email-existence oracle. | For non-platform callers, allow only accounts with no other active batch membership or staff grant, or require `move_from_batch_id` with permission on the source batch. The matrix gives trainers `batch.member.manage`, so this is the owner's call. |
| D2 | Med | `apps/api/app/modules/admissions/service.py:1314-1318` `find_or_create_user` | attacker pre-registers | With F1 fixed, an attacker can no longer link a registration. But approval of a website registration still enrols an **existing unverified** same-email account (pre-hijack: the attacker knows its password). | Treat an unverified same-email account like Google's `_claim_unverified_account`: drop its password and sessions, then mark the email verified when the login email is sent. Alternatively, refuse with "verify the email first". |
| D3 | Low (info) | `apps/api/app/modules/rbac/catalogue.py:267` `mentor.notes.read` = `S - B - P` | trainer@batch | Trainers can read mentor notes of their batch's students (`GET /mentor/students/{id}/notes`). If "/mentor is admin-only" is the rule, the trainer cell should be `-`. `docs/single-company/ws4.md` keeps it on purpose. | Owner to confirm. Re-seed the rbac rows if it changes. |
| D4 | Low | `apps/api/app/modules/learning/router.py:1526-1541` (and `fs_enrol.enrolment_page`) `GET /enrolments` and `/progress` with `?batch_id=` | trainer or evaluator of the old batch | The scope uses `Enrolment.batch_id` stamped at enrolment. After a transfer, the old batch's staff keep reading the student's progress. | Intersect with the current active members of `batch_id`, or re-stamp on transfer. |
| D5 | Low | `apps/api/app/modules/support/router.py:1227-1255` `POST /support/users/{user_id}/notes` (`ticket.respond`) | content_manager | Can attach support notes to any user, outside their ticket lane. 404 versus 201 reveals whether a user exists. Notes are read back only with `user.read` (SA). | Require a ticket in the caller's lane (`staff_scope.sees`) unless the caller holds `user.read`. |
| D6 | Low | `support/router.py:811-812` `PATCH /support/tickets/{id}` `related_case_id` | content_manager | Accepts any security case id, with no owner check (integrity only; nothing reads the link). | Check `case.user_id == t.requester_id`, as `related_unblock_request_id` does. |
| D7 | Low | `apps/api/app/modules/media/router.py:343-361` `POST /media/downloads` | student | Resources of draft or archived courses are downloadable when `public`, `signed_in`, or free-entitled. It needs the uuid7 resource id, which is not listed anywhere. | 404 unless the course is published and not deleted. |
| D8 | Low (config) | `apps/api/app/modules/rbac/router.py:208` and `admin/accounts.py:511` | super_admin | Under `TD_SIMPLE_AUTH=true`, granting `super_admin` skips dual control. Step-up is a no-op too, so `POST /me/privacy-requests` (erasure) is guarded only by the session. | Already on the "undo before launch" list (testing-phase switches). |
| D9 | Low | `apps/api/app/modules/paths/service.py` `link_options` | trainer@batch | Lists the titles of all company assignments, tests and articles (titles and marks only). | Optional filter to the caller's batches. |
| D10 | Info | `identity/router.py:1921` `legal_name_locked: False`; `PATCH /me/profile` | student | `full_name` is always editable, including after a certificate is issued. `user.legal_name.change` is not enforced on HTTP. | Product decision. |
| D11 | Functional, not a leak (suspected) | `apps/api/app/modules/assessments/store_specs.py` (attempt tables, RLS family `owner`) and `core/firestore/sqlstore.py` `visible()` | trainer or evaluator @batch | On Firestore, the engine emulates only the owner and platform branches of the attempt RLS (the org-staff branch is not emulated). Batch staff may get 404 or empty results on attempt result/review/evaluation/grade/integrity routes, and on `/tests/{id}/attempts`, `/evaluation`, `/report` and `/integrity/flags`. This fails closed, so no data leaks. | Verify on the deployed system with a batch-scoped trainer. If confirmed, add the batch-staff branch to the attempts visibility rule. |

### Verified correct

| Area | Verified routes |
|---|---|
| admin | 12 |
| rbac | 5 |
| security | 16 |
| support | 9 |
| commerce | 18 |
| sessions | 8 |
| identity | about 24 |
| analytics | 16 |
| engage | 17 |
| mentoring | 23 |
| notifications | 4 |
| hub | 3 |
| ai | 7 |
| paths | 24 (of 27, before the fixes) |
| orgs | 21 (of 22) |
| assessments | 37 |
| learning | 44 |
| coding | 23 |
| placement | 40 |
| catalog | 10 |
| media | 6 (of 7) |
| entitlements | 5 |
| admissions `/admin/*` | 24 |

What these checks covered:

- **Approvals:** the list and detail show a row only to its requester or a possible approver. Maker ≠ checker, except a sole admin.
- **Grants:** `rbac.grant.manage` at platform scope is required. The only self-grant is `trainer@batch`. Trainers, evaluators and content_managers cannot grant.
- **Support:** lane-scoped queue and tickets. content_manager sees only content, assessment and certificate tickets.
- **Commerce, sessions, privacy, unblock requests:** all owner-filtered on both stores.
- **Coding:** hidden test cases and reference solutions need `coding_problem.manage` or `hidden.read`.
- **Studio questions:** answer keys are shown only to the author or reviewer, or with `answer_key.read`.
- **Users' entitlements:** `/users/{id}/entitlements` is platform only.

## 3. Tests (Firestore emulator 127.0.0.1:18080, `TD_TEST_NO_PG=1`, no `-n`)

The new suite `tests/parity/test_rbac_audit.py` runs the real `RbacPermissionChecker` over the
role catalogue, on the parity harness (every module on Firestore, `NO_POSTGRES` sessions). Its
4 tests **all failed on the old code and all pass now**:

- unverified-email admissions: the victim's registration was returned before the fix;
- trainer archive of a cross-batch path: 204 before, 403 now;
- article audience: publishing to batch B returned 200 before, 403 now;
- structured grading: the `_ensure_grade` unit test, where the grant returned "all allocations" before.

Regression runs after the fixes:

| Suite | Result |
|---|---|
| `tests/parity` (incl. the new file) | 16 passed |
| `tests/paths` | 8 passed, 14 skipped (Postgres) |
| `tests/admissions/firestore` | 10 passed |
| `tests/identity/fs` (rbac, orgs, sessions on Firestore) | 78 passed |
| `tests/learning` + `tests/core` | 165 passed, 129 skipped (Postgres) |
| `tests/rbac` + `tests/authz` | 2 passed, 63 skipped |
| `tests/firestore` | 39 passed, 1 failed |

Notes on these results:

- `tests/rbac` + `tests/authz`: the TS-AUTHZ matrix and the RBAC suites need Postgres (`db` fixture), so they skip under `TD_TEST_NO_PG=1`.
- `tests/firestore`: the 1 failure is `test_gate_production_refuses_missing_creds_and_emulator`, which fails only because the run exports `FIRESTORE_EMULATOR_HOST`. It is environment-related and not affected by these changes.

`ruff check` is clean on every changed file.

## 4. Files changed

- `apps/api/app/modules/admissions/student.py`: `_verified_email`; email matching only when verified.
- `apps/api/app/modules/paths/service.py`: `require_audience_scope`, `archive_path(..., request)` per-allocation check, `managed_article(change=)`, audience check in `publish_article`.
- `apps/api/app/modules/paths/router.py`: passes `request` to archive; `change=True` on article patch, delete, publish and unpublish.
- `apps/api/app/modules/learning/structured_api.py`: `_ensure_grade` allocation scoping; `gradable_allocations`.
- `apps/api/app/modules/learning/router.py`: structured gradable check in `_submission_for_staff` and `grading_queue`.
- `apps/api/tests/parity/test_rbac_audit.py`: new.
- `functions-lms/app/**`: re-copied by `functions-lms/tools/build.py`. That copy also picks up any other in-progress `apps/api/app` edits. The build reported `functions-lms/venv` missing or incomplete; reinstall it before the next deploy. **Not deployed.**
