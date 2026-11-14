# Data-access agent: identity, sessions, rbac, orgs on Firestore

Agent: data-access. Rounds 1 to 8 were all on 2026-11-12. From round 6 this agent also owns the **admin** module. Plan: `docs/firebase-migration-plan.md`. Store layer: `p0.md`. Pattern: `p2.md`.

Every `TD_STORE_*` switch still defaults to `postgres`. Nothing was deployed.

Test policy (owner decision): tests run on the Firebase emulator only, with `TD_TEST_NO_PG=1`. No Postgres runs are planned. Parity is checked later against the live VM.

## 1. Status (end of round 2)

| Module | Repository + data model | Routes on Firestore with **no Postgres** | `public.py` for other modules | Backfill/verify | Can flip? |
|---|---|---|---|---|---|
| identity | yes | **All** `identity/router.py` endpoints, plus `erasure.py` and `reencrypt_totp.py`. **Google sign-in has no HTTP test** (it needs a Firebase Auth token verifier). | yes | yes | Yes for its own routes, once the two platform fixes in §5 land. Other modules still read identity tables directly (§6). |
| sessions | yes | **All** `sessions/router.py` and `login.py` endpoints, and the resolver | yes | yes (+TTL) | Same as identity |
| rbac | yes | **All** `rbac/router.py` endpoints, including dual-control approve/reject | yes | yes | Same as identity |
| orgs | yes | **All** `orgs/router.py` and `classes.py` endpoints, plus the website plan importer | yes | yes | Same as identity |

**"Flippable" means:** with `TD_STORE_{IDENTITY,SESSIONS,RBAC,ORGS,AUDIT,CORE}=firestore` and an **empty `DATABASE_URL`**, every endpoint of these four modules runs without touching Postgres. In that setup the request session is `NO_POSTGRES`, and any Postgres use fails the test.

**Before a real flip**, the consumers in other modules (§6) must switch to the `public.py` APIs. Until they do, they would read empty Postgres tables. The owner has decided all modules move together.

## 2. How it works

- **Data model.** Unchanged from round 1. Every column of every table maps to a field of a Firestore document through `identity/fs_codec.py`. Uniqueness is kept by lookup documents:
  - `users_by_email|phone|username`
  - `user_devices_live`
  - `role_grants_live`
  - `approvals_case_pending`
  - `org_memberships_by_user`
  - `batches_by_code`
  - `batch_members_live`
  - `class_sessions_by_date`
  - attendance id = `session:user`
- **Request unit of work** (`identity/fs_uow.py`):
  - Rows a route loads on Firestore are tracked. At the end of a **successful** request, only the changed fields are written, through each module's saver (`<m>/uow_savers.py`), so the uniqueness lookups and the "ended session stays ended" rule still apply.
  - `fs_uow.add(session, obj)` replaces `session.add`.
  - When a request fails, the pending changes are discarded, as a Postgres rollback would.
  - Objects built inside a repository transaction are **not** tracked (fix by fork B). Without this, a stale internal copy could overwrite a newer write, for example the approval status.
  - Atomic operations stay inside the repository transactions: OTP checks, token claims, TOTP steps, recovery codes, grants, approval decisions, membership and class uniqueness.
- **No-Postgres helpers** (`identity/pgctx.py`): `sys_ctx` / `sys_scope` replace `system_context` / `as_system` and do nothing when the request has no Postgres session. The resolver does not build a Postgres session when `runtime.postgres_enabled()` is False.
- **`lock_user` on Firestore** now calls `app.core.request_locks.acquire(f"sess:{user_id}")`, as the platform agent requested. The lock is released when the request ends. `unlock_user` is kept as a no-op.
- **Expiry fields for TTL:**
  - `verification_tokens` and `password_reset_tokens`: `expire_at = expires_at + 7 days` (the R-TOKEN rule), set on insert, on OTP re-issue, and in the backfill.
  - `login_attempts` and `session_network_observations`: `expire_at = time + 395 days` (the R-SEC rule).
  - The TTL field overrides are in the index fragments.
- **`end_sessions_where`** stays SQL-only for Postgres. On Firestore, the store-neutral `sessions.public.end_sessions(user_id, except_ids=…, only_status=…)` and `SessionsRepo.end_sessions(where=…)` are used. None of the four modules calls the SQL form on Firestore.

## 3. `public.py` (for other modules; switch your consumers to these)

| Module | Functions |
|---|---|
| `identity.public` | `get_user(s)`, `get_profile(s)`, `user_cards`, `find_user`, `users_by_emails`, `username_taken`, `list_users`, `status_counts`, `search_users`, `update_user`, `create_user`, `save_user`, `save_profile`, `save_credential`, `get_credential`, `active_factors`, `add_factor`, `save_factor`, `revoke_factors`, `consents_of`, `latest_consent_action`, `has_verified_guardian_consent`, `verification_tokens_of`, `reset_tokens_of` |
| `sessions.public` | `get_session`, `list_sessions` (filters: user, status, active_at, created/last-seen windows, device, tier, client, end reason), `update_session`, `end_sessions`, `add_session`, `get_device`, `add_device`, `list_user_devices`, `add_user_device`, `clear_remember_tokens`, `get_login_attempt`, `list_login_attempts`, `list_observations`, `add_observation` |
| `rbac.public` | `roles`, `role_by_key`, `live_grants`, `user_ids_with_role`, `staff_user_ids`, `user_ids_with_permission`, `get_grant`, `revoke_user_grants`, `add_grant`, `permission_keys`, `role_permission_pairs`, `get_approval(for_update=)`, `find_approvals` (all approval filters used today), `save_approval` (single execution on Firestore) |
| `orgs.public` | `get_org`, `add_org`, `get_batch(es)`, `batch_names`, `list_batches`, `batch_status_counts`, `add_batch`, `get_batch_plan`, `batch_members`, `is_batch_member`, `get_batch_member`, `add_batch_member`, `save_batch_member`, `org_memberships`, `active_org_ids`, `end_memberships` |

Aggregates such as GROUP BY reports are computed by the caller from the returned lists.

## 4. Tests (emulator only, real run)

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=access_test TD_TEST_FIRESTORE_AUTOSTART=0 .venv/Scripts/python.exe -m pytest tests/identity/fs -q
```

**Result: 45 passed (95 s).** The suite is made of:
- 25 service/repository/backfill tests from round 1;
- 1 smoke test;
- `test_http_identity.py` (11);
- `test_http_sessions_rbac.py` (5);
- `test_http_orgs.py` (3).

The HTTP tests go through `create_app()` with an empty `DATABASE_URL`. The `http` fixture in `tests/identity/fs/conftest.py` sets this up, together with `fs_user` and `seed_catalogue`.

Coverage:
- **identity:** sign-up, email verification, login, back-off, MFA with TOTP and recovery codes, new-device OTP, session cap and session choice, logout, forgot/reset (single use), password change, step-up, consents, profile, TOTP enrol/confirm/delete, recovery codes, remember refresh, and the guardian flow. Erasure and TOTP re-encryption are tested at service level.
- **sessions and rbac:**
  - all `/me/sessions` and `/me/devices` endpoints, device policy and login history;
  - the admin sessions/devices endpoints;
  - roles and permissions; grants list, create (idempotent; a duplicate gets 409), and revoke;
  - dual control: self-approval gets 403; two concurrent approvals give exactly one execution; reject.
- **orgs:**
  - batches CRUD (a duplicate code gets 409);
  - members, including the membership lifecycle and re-adding a member;
  - plan, preview and schedule;
  - class generate (idempotent), duplicate date 409, delete blocked while attendance exists;
  - attendance as a batch-scoped trainer, the attendance summary, `/me/classes` and `/me/attendance`;
  - the importer (dry run, apply, re-run, update, code clash).

Checks: ruff check and format are clean on the touched files. mypy reports no errors in the four modules.

**Detached in HTTP tests (owned and tested by other agents):** the security restriction lookup and signal sink, the assessments attempt lookup, the catalog course-org lookup, and the admin policy resolver (documented defaults are used instead). `identity.router.notify` is replaced by a recorder (see §5).

**Use one `TD_TEST_DB_NAME` per parallel run.** Runs that share an emulator project wipe each other's data.

## 5. Gaps and requests

1. **notifications / platform:** `notifications.notify` on Firestore calls `core.db.rls_scope(session)`, which raises on `NO_POSTGRES`. Treat a falsy session as platform scope. Until then, the session-choice, password-reset, TOTP-confirm and other notice-sending routes fail with no Postgres. The tests stub `notify`.
2. **platform:** `core_store.idempotent_firestore` checks `session is not None`, but `NO_POSTGRES` is falsy, not `None`, so the check should be `if session`. The identity and rbac routers work around it by passing `session or None`.
3. ~~Approval executes after the claim~~: fixed in round 3 (§8).
4. **Untested over HTTP:** mobile OTP verification (covered at service level), the privileged revoke flow, and the beyond-quota device reset.
5. **Catalog lookups from orgs:** `PUT /plan` with a new `course_id` and the importer's slug lookup call catalog APIs. These depend on catalog's Firestore path; the tests stub the importer's lookup.
6. ~~Admin `/admin/approvals` on Postgres~~: ported in round 3 (§8).
7. **Formatting incident:** in round 2 I ran `ruff format` once on the whole `app/modules` tree by mistake. This could have re-wrapped lines (whitespace and quotes only, no code change) in other agents' files that were not formatted at that moment. The files touched in that window included `admin`, `assessments`, `coding`, `commerce`, `engage`, `hub`, `learning`, `mentoring`, `paths`, `placement` and `security` files. If another agent sees an unexpected "file changed" notice, this is the likely cause.

## 6. Consumers still to switch to `public.py` (other agents, next round)

These files import the access modules' models and must not run SQL or ORM on those tables when the switches are `firestore`:

- **identity models:**
  - admin: accounts, privacy
  - admissions: admin, onboarding, service
  - assessments: attempts
  - hub: router
  - learning: certificates, cert_admin
  - notifications: consumers, router
  - security: api_review, api_student, cases, engine, public, restrictions, signals, tasks, timeline, unblock
  - support: enquiries, router, service
  - seeds: catalog_demo, coding_demo, commerce_demo, company_demo, dev_users, e2e_demo, e2e_env, placement_demo, security_demo
- **sessions models:**
  - admin: accounts
  - assessments: attempts
  - security: api_review, cases, engine, reports, restrictions, signals, tasks, timeline, unblock
  - support: router
  - seeds: dev_users, security_demo
- **rbac models:**
  - admin: accounts, approvals, router
  - analytics: exports
  - commerce: admin, router
  - learning: structured
  - notifications: consumers
  - security: cases, controls, reports, tasks
  - support: enquiries
  - seeds: dev_users, e2e_demo
- **orgs models:**
  - admin: accounts, courses_overview
  - admissions: service
  - assessments: attempts, studio
  - coding: router
  - learning: certificates, router
  - notifications: router
  - placement: mentoring, policies
  - security: engine
  - seeds: company_demo, dev_users

Some of these may already have their own Firestore branch from their agent, or may import the models only for type hints. Each owner should check theirs.

## 7. Files (both rounds)

- **New:**
  - `identity/{fs_codec,fs_base,fs_uow,pgctx,public,uow_savers,store_specs,repo_firestore}.py`
  - `sessions/{public,uow_savers,store_specs,repo_firestore}.py`
  - `rbac/{public,uow_savers,store_specs,repo_firestore}.py`
  - `orgs/{public,uow_savers,route_store,store_specs,repo_firestore}.py`
  - four `firestore.indexes.fragment.json` (composite indexes, payload/plan exemptions, TTL overrides)
  - `tests/identity/fs/*`
  - `tests/identity/test_store_parity_access.py` (Postgres parity, superseded by the new test policy)
- **Ported:**
  - `identity/{service,router,erasure,reencrypt_totp}.py`
  - `sessions/{service,resolver,login,router}.py`
  - `rbac/{service,router}.py`
  - `orgs/{service,router,classes,import_website_plans}.py`
  - Postgres branches keep the original SQL. A backup of the original identity router is at `C:\Users\SYAM\AppData\Local\Temp\claude\099c798e4136fab9\88f7fa47-940f-41d2-9f5a-d10548d6f736\scratchpad\access_identity_router.orig.py`.
- **Backfill/verify:** `python -m app.core.firestore.backfill identity sessions rbac orgs [--verify-only] [--replace]`.

## 8. Round 3 (2026-11-12)

### Approval parity: claim plus compensation

New `rbac.public.decision(session, req, status=..., decided_by=..., note=..., sole_admin=...)` is an async context manager:

- **On Postgres** it sets the decision fields on the locked row. An exception rolls everything back, as before.
- **On Firestore** the `pending -> decided` claim is one transaction (`RbacRepo.decide_approval`). Only the first request wins; the others get 409.
- **If the block raises** (the privileged executor, a reject hook, audit), the claim is undone by `RbacRepo.restore_pending`. The request goes back to `pending` with `decided_by`, `decided_at`, `decision_note`, `executed_at` and `sole_admin_decision` cleared, which is what the Postgres rollback leaves. Then the error propagates.
- `rbac.public.mark_executed` and `rbac.public.expire_if_due` (ADM-23) complete the set.

Used by:
- the RBAC-07/08 routes (`rbac/router.py::_decide`);
- the admin queue (`admin/approvals.py::decide` and `cancel`).

**Remaining edge:** closed in round 4 (§9).

### `/admin/approvals` (list, get, approve, reject, cancel)

`admin/approvals.py` no longer has any SQL:

- `load_for_update` uses `rbac.public.get_approval(for_update=True)`.
- `expire_if_due` uses `rbac.public.expire_if_due`.
- `new_request` persists the module-clock times on Firestore.
- `decide` and `cancel` use `decision`. A cancellation keeps `decided_at` NULL, as before.

In `admin/router.py`, the list route uses `rbac.public.find_approvals(status=..., order="expires_asc")` and the get route uses `get_approval`. Only the two approvals routes were changed; the rest of admin was not touched.

### `rbac.public` additions

| Function | For | Notes |
|---|---|---|
| `revoke_grant(session, actor, grant_id, revoked_by, reason)` | data-ops (break-glass) | Full service semantics: audit, and the grantee's sessions rotate |
| `pending_approval_ids_by_target(action_type=, target_type=, target_ids=)` | commerce (coupon activation) | |
| `get_approvals(ids)` | analytics (export jobs) | Batched lookup by id |
| `get_approval(for_update=)`, `find_approvals`, `decision`, `mark_executed` | commerce's approve path | Replaces its `select(ApprovalRequest)...with_for_update()` |
| `role_permission_map`, `batch_org` | data-content | Re-exports |

### Google sign-in over HTTP with the Auth emulator

`identity/google.py` gains `EmulatorTokenVerifier`. It accepts the Auth emulator's unsigned (`alg: none`) ID tokens and applies the same aud/iss/exp/iat/required-claim checks.

`get_verifier()` uses it only when **both** of these hold:
- `FIREBASE_AUTH_EMULATOR_HOST` is set;
- `APP_ENV` is not `prod` or `production`.

Only then are `demo-*` projects allowed. In production the emulator mode is refused (logged): the demo project id then counts as unset and Google sign-in answers 503. The constructor also raises under production settings.

The real verifier still rejects emulator tokens (`bad_alg`).

**Router fix:** a Firestore sign-up now copies the stored server defaults (`restriction_level`, `locale`, ...) back onto the in-memory user, as Postgres `eager_defaults` does. Google sign-up crashed without this.

### Tests (emulator only)

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=access_r3 TD_TEST_FIRESTORE_AUTOSTART=0 .venv/Scripts/python.exe -m pytest tests/identity/fs -q
```

**Result: 53 passed (94 s).** The 8 new tests:

- `test_http_approvals.py` (4):
  - **Failure case.** An executor failure (unknown role, 422) on both `/rbac/approval-requests/{id}/approve` and `/admin/approvals/{id}/approve` leaves the request `pending` with no decision recorded. It can still be decided afterwards: a reject works once, and a second reject gets 409.
  - **Admin queue.** List and get (404 for an unknown id); two concurrent approves give one 200 and one 409, with exactly one grant created and the request `executed`; cancel by the requester (409 the second time, 403 for someone else).
  - **Expiry.** An expired request answers 409 and stays `expired`.
  - **Public API.** The commerce/analytics helpers, the re-exports, and break-glass `revoke_grant`.
- `test_http_google.py` (4), using tokens minted by the Auth emulator at 127.0.0.1:19099:
  - login of an existing student;
  - replay refused (401);
  - unverified email refused;
  - new-student sign-up (409 `google_signup_required`, then sign-up with consents);
  - the signed-token verifier rejects emulator tokens;
  - emulator mode refused in production.
  - These tests are skipped when the Auth emulator is down. They use addresses unique to each run, because the shared Auth emulator keeps accounts between runs.

Checks: ruff is clean on the touched files only (no tree-wide formatting this round). mypy reports no errors in identity/sessions/rbac/orgs or `admin/approvals.py`.

## 9. Round 4: an approved action is all-or-nothing

### Mechanism: the undo journal (`identity/fs_journal.py`)

`async with journal():` opens an undo scope. The four access repositories now build their store as `JournalingStore.system(job)`. Every document they write inside a scope records its **before-image** once (`None` if the write created the document). The before-image comes from:
- the transaction's own read, for `update_read`, `delete_read`, `update` and `delete`;
- a read just before the write, for a blind `put`.

Only committed attempts are kept. When the block raises, every touched document is restored in reverse order (created documents are deleted), then the error propagates. This covers the uniqueness lookup documents too, such as the live grant slot and the email reservation.

How other code joins:
- Other modules join by building their store with `JournalingStore.system(job)`, or by registering an undo callback with `on_rollback(cb)`.
- `request_journal` is a router dependency that makes a whole request one undo scope. It is meant for direct multi-write routes such as deactivate or break-glass.

### Applied to approvals

`rbac.public.decision(...)` now runs the following inside **one** journal:
1. the claim (`pending -> decided`);
2. the executor's writes (grant create or revoke, grantee session rotation, `users.sessions_valid_after`, remember tokens, ...);
3. `mark_executed`.

**Audit** is buffered to the request commit point by `core.audit` and dropped when the request fails. So a failure at any step, including the final `approval.executed` audit after the grant was written, leaves:
- no grant;
- the request `pending`, with no decision recorded;
- the grantee's sessions untouched;
- no audit row.

This is the result of one Postgres transaction. It applies to both decision routes (RBAC-07/08 and `/admin/approvals`) and to cancel. The round-3 `restore_pending` path was replaced by the journal; the repository method is still there but unused.

### Tests (emulator only)

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=access_r4b TD_TEST_FIRESTORE_AUTOSTART=0 .venv/Scripts/python.exe -m pytest tests/identity/fs -q
```

**Result: 58 passed (124 s).** The `request_journal` route test was added after that run; `test_fs_journal.py` on its own gives 4 passed. mypy and ruff are clean on the touched files.

**HTTP tests (`test_http_approvals.py`):**
- `test_failure_after_grant_write_undoes_everything`. The `approval.executed` audit is forced to raise after `create_grant` has written the grant, ended the grantee's sessions and moved `sessions_valid_after`. This is run on both `/rbac/approval-requests/{id}/approve` and `/admin/approvals/{id}/approve`. Each run asserts:
  - the request is `pending` with `decided_by` NULL;
  - there is no grant document at all;
  - the grantee's session is still `active`;
  - `sessions_valid_after` is unchanged;
  - the `lms_audit_outbox` content is identical to before.

  Without the failure, the same request then executes exactly once.
- `test_failure_after_revoke_write_restores_the_grant`: a privileged revoke followed by a failure leaves the grant live, the live-slot reservation restored (a duplicate grant is still refused with 409), and the request pending.

**Service-level tests (`test_fs_journal.py`, 4 tests):**
- the effects that MFA reset, deactivate and break-glass use through the public APIs (revoke factors, revoke all sessions, user status, grant revoke, plus an external `on_rollback` callback) are all undone on failure and all kept on success;
- created documents are deleted on rollback, and writes made outside a scope are not affected;
- `request_journal` on a route: a failing deactivate-style route leaves no change, a successful one keeps its changes.

### Other privileged actions (status)

| Action | Executor / route | State |
|---|---|---|
| `rbac.grant.privileged` / `rbac.revoke.privileged` | rbac (mine) | **All-or-nothing, HTTP-tested** |
| break-glass | `admin/accounts.py` (data-ops) | Its writes go through `rbac.public.add_grant` / `revoke_grant` and sessions, which are journaled. Data-ops must decide it inside `rbac.public.decision`, or add `Depends(request_journal, scope="function")` to its route. |
| `user.mfa.reset` | `admin/accounts.py::_execute_mfa_reset` (data-ops) | **Still SQL** (`update(MfaFactor)`). Data-ops must switch to `identity.public.revoke_factors`, after which it is covered automatically, because it runs inside the journal of `admin.approvals.decide`. |
| deactivate (ADM-04) | `admin/accounts.py` route (data-ops) | Must use `identity.public.update_user` and `sessions.public.end_sessions`, and add `request_journal` to the route. |
| `policy.change` | admin repository (data-ops) | Must build the admin store with `JournalingStore`, or register `on_rollback`. |
| commerce billing approvals, security `risk.kill_switch.ratify`, `security.restriction.bulk_lift`, exports | commerce, security | Their writes run inside the decision journal only if their stores use `JournalingStore` or they register `on_rollback`. This is a request to data-money and data-ops. |

## 10. Round 5: admin privileged actions are all-or-nothing on Firestore

Edited only `admin/accounts.py` (the deactivate, reactivate, MFA-reset and break-glass code) and `_execute_policy_change` in `admin/router.py`. The diffs are small and every Postgres branch is unchanged.

- **`_user`** reads through `identity.public.get_user`. A new `_set_user` helper sets columns on either store (`identity.public.update_user` on Firestore, a flush on Postgres).
- **Deactivate / reactivate (ADM-04):**
  - `Depends(request_journal)` makes the request one undo scope;
  - the status change goes through `_set_user`, and sessions end through `sessions.service.revoke_all_sessions` (store-neutral);
  - the `identity.user_deactivated` event is emitted with `emit_any` (identical on Postgres, the Firestore outbox otherwise), and the Firestore outbox row is journaled so a failed request removes it.
- **MFA reset (ADM-05):**
  - the request route counts active factors with `identity.public.active_factors` and finds a duplicate pending request with `rbac.public.find_approvals`;
  - the executor calls `identity.public.revoke_factors`;
  - it runs inside the decision journal of `admin.approvals.decide`, so factor revocation, session revocation, the decision and the audit row commit together or not at all.
- **Break-glass `end` / `review`:**
  - `Depends(request_journal)`;
  - `_bg_save` captures the break-glass document's before-image (`fs_journal.capture`) before the admin repository saves it;
  - the grant revoke goes through `rbac.public.revoke_grant` (journaled).
  - There is no activation route in this code base, and the expiry job (`expire_break_glass`) was not changed.
- **`policy.change` executor:** on Firestore it captures the policy head and the active row it replaces, and records the new version row as created. All three are inside the decision journal, so a failure after the write restores the previous active version.
- **`fs_journal.capture(collection, doc_id)`** is new: it records a before-image for a write made through a store outside the access modules.

**HTTP tests, no Postgres** (`tests/identity/fs/test_http_admin_actions.py`, 3 tests, with `TD_STORE_ADMIN=firestore` added):
- **Deactivate:** with a forced failure after the writes (the `admin.user.deactivated` audit raises), the user stays active, `sessions_valid_after` stays unchanged, the session stays active, and there is no audit row and no outbox event. Then deactivate succeeds: deactivated, 1 session revoked, the audit row and the outbox event are present.
- **Reactivate:** a forced failure leaves the user deactivated; reactivate then succeeds.
- **MFA reset:**
  - the request returns 202, and a second request while one is pending gets 409;
  - a different admin approves with a forced failure after the factor and session writes (the `admin.user.mfa_reset` audit raises): the factor is still active, the session is active, the approval is pending with no decision, and there is no audit row;
  - the approval then executes (1 factor removed, sessions revoked, audit rows present).
- **Break-glass end:** a forced failure leaves the session `active` and the elevated grant restored (not revoked), with no audit row. Then it ends and the grant is revoked.
- **Break-glass review:** a forced failure leaves `reviewed_at` NULL; then it succeeds.

The `policy.change` path has no HTTP test: the admin policy routes belong to data-ops.

**Full suite:** `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=access_r5b TD_TEST_FIRESTORE_AUTOSTART=0 .venv/Scripts/python.exe -m pytest tests/identity/fs -q` gives **62 passed (117 s)**. mypy and ruff are clean on the touched files.

## 11. Round 6: the admin module on Firestore with no Postgres

This builds on data-ops' flags, policy, privacy, retention and break-glass repositories (see `data-ops.md`). With `TD_STORE_ADMIN=firestore` (and the other modules on Firestore), every admin route and the admin job run with no Postgres.

| File | Change |
|---|---|
| `admin/accounts.py` | **Dashboard (ADM-01):** every tile comes from the owning module's public API:<br>- users, minors, new registrations and learners: `identity.public.status_counts` / `list_users`, with `rbac.public.staff_user_ids` to leave staff out;<br>- active sessions: `sessions.public.list_sessions(active_at=)`;<br>- courses: `catalog.public.course_status_counts`;<br>- batches: `orgs.public.batch_status_counts`;<br>- paid orders: `commerce.public.paid_orders_since`, through a read-only `MemoryTx` when there is no Postgres session;<br>- approvals the viewer can decide: `rbac.public.find_approvals`. |
| `admin/accounts.py` | **Users:** search (ADM-02) uses `identity.public.search_users` (same filters, keyset and order); user detail (ADM-03) uses the public profile, grant, factor, approval and session APIs. |
| `admin/accounts.py` | **Create user (ADM-06):** `identity.public.create_user` (email/phone uniqueness), `rbac.public.role_by_key`, and `emit_any`, with the outbox row journaled; runs under `request_journal`. Set-password is now also under `request_journal`. |
| `admin/accounts.py` | **Break-glass expiry job:** on Firestore each elevation is one unit: grant revoke, session rotation, row update, alert and a buffered audit row commit together or are all undone. `admin/tasks.py` uses `NO_POSTGRES` when Postgres is disabled. |
| `admin/accounts.py` | Postgres-only helpers are renamed `*_pg` (`_count_pg`). |
| `admin/courses_overview.py` | Reads `learning.public.courses_overview_stats` and `orgs.public.get_batches` / `list_batches`. The response is unchanged. |
| `admin/router.py` | The policy list uses `rbac.public.find_approvals` for pending changes. The `policy.change` executor is journaled (round 5). |
| `admin/policy.py` | Postgres-only `_next_version` is renamed `_next_version_pg`. It is only reached from the Postgres branch of `write_setting`. |

### Code scan (proof)

`tests/admin/fs/test_no_unguarded_sql.py` parses every `admin/*.py` with `ast` and fails if any function issues SQL without a Firestore branch in the same function.

- **What counts as SQL:** `session.execute/get/add/scalar(s)/delete/merge`, or SQLAlchemy `select/update/delete/insert/text`.
- **What counts as a Firestore branch:** a call to `uses_firestore` / `_fs` / `fs` / `postgres_enabled`, or an `if session` / `if not session` test.
- **Exempt:** functions named `*_pg`, provided every call site is itself guarded (the scan checks that too); `models.py`, `store_specs.py` and `fs_rows.py`.

**Result: clean.** Before this round it listed 10 functions.

### Tests (emulator only)

**HTTP tests:** `tests/admin/fs/test_admin_access_http.py`, 5 tests, every `TD_STORE_*=firestore`, empty `DATABASE_URL`.

- **Reads:** the dashboard (user and learner counts, active sessions, empty commerce); user search, including keyset paging and the `current` filter; user detail (grants, MFA, sessions); courses overview.
- **Create user:**
  - a forced failure after the writes leaves no user, profile or email reservation;
  - success creates the user with its `content_manager` grant;
  - a duplicate gets 422.
- **`policy.change` through dual control:**
  - version 1 executes;
  - a forced failure while approving version 2 leaves only version 1, still active, with the approval pending and no audit row;
  - the retry makes version 2 active and version 1 inactive.
- **Break-glass expiry job:**
  - a forced failure leaves the elevation active, its grant live, and no audit row;
  - the retry expires it, revokes the grant and writes the audit row;
  - a second run finds nothing.
- **Other routes:** admin set-password (password and must-change flag saved), and the flags, retention and approvals list routes.

**Result:** `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=access_r6 TD_TEST_FIRESTORE_AUTOSTART=0 .venv/Scripts/python.exe -m pytest tests/admin/fs -q` gives **21 passed**. That is data-ops' existing admin tests, the scan and the 5 new tests.

### Notes and requests

- **Commerce/platform:** `commerce.public` calls through the SQL engine need a real session object. With `NO_POSTGRES` the dashboard opens a read-only `MemoryTx` itself. It would be cleaner if `paid_orders_since` accepted a falsy session.
- **Seeds:** `admin` seed paths were not part of this round.

### Helpers added for other agents (round 6)

| Helper | For | What it does |
|---|---|---|
| `admin.public.active_policy_setting(session, key, scope_type="platform", scope_id=None)` | security pass 2/3 | The active `policy_settings` row of one key and scope, on either store; `None` if absent |
| `admin.public.active_policy_settings(session, keys, scope_type=..., scope_id=...)` | security | `{key: active row}` for several keys |
| `admin.public.policy_settings_for_case_decisions(session, decision_ids)` | security pass 3 | Every policy row whose `case_decision_id` is in the list |
| `admin.public.policy_case_decision_ids(session, decision_ids)` | security pass 3 | Which of the given ids are referenced (the `purge_closed_cases` NOT EXISTS check) |
| `admin.public.retention_interval(session, table)` | security pass 2 | The shortest active retention interval of a table, as a `PgInterval` |
| `PgInterval`, `add_interval`, `subtract_interval`, `interval_days` (`admin.public`, defined in `admin/intervals.py`) | security | Postgres interval arithmetic (see "Interval parity" below) |
| `identity.public.web_base_url()`, `identity.public.web_link(name, **params)` | data-learning | Re-exports of `identity.links` |
| `orgs.public.attendance_certificate_block(session, batch_id, user_id)` | data-learning | The attendance gate on either store. The Firestore side is tested in `tests/identity/fs/test_fs_public_extras.py` (no plan, below minimum, a cancelled class ignored, late counts as attended, never marked). The Postgres side is unchanged code; it is not run, per the test policy. |
| `identity.fs_journal.child()` | security pass 2 | A nested undo scope: it joins the open journal, or opens its own. The private `_current` still works. |

### Interval parity (`admin/intervals.py`)

Postgres keeps an interval as (months, days, microseconds). asyncpg turns it into a `timedelta` (a year becomes 365 days, a month 30 days), and Firestore had stored plain seconds.

- **Storage.** `retention_policies.retention_interval` is now stored on Firestore as `{months, days, microseconds}` (FsRow kind `interval`).
- **Backfill.** The retention backfill reads the components in SQL (`date_part`), so `'1 year'` is backfilled as 12 months, not 365 days.
- **Legacy rows.** Rows written earlier as plain seconds are still read (as days plus time).
- **`PgInterval` arithmetic:**
  - `ts - iv` / `ts + iv` follow Postgres: months first, clamped to the month end; then days; then time; in UTC.
  - `min()` and comparisons follow Postgres `interval_cmp` (a month counts as 30 days).
  - `interval_days()` gives the old asyncpg day count, so the retention list route answers exactly as before.
- **Tests:** `tests/admin/fs/test_intervals.py`, 13 tests: `'1 year'`, `'18 months'`, `'90 days'`, the leap-day boundaries (29 Feb minus 1 year is 28 Feb; 31 Aug minus 18 months is 29 Feb 2024), mixed components, ordering, legacy values, the backfill transform, the Firestore round trip through `retention_interval`, and the case-decision lookup.

**Request to security:** switch `repo_fs_engine.retention_interval` to `admin.public.retention_interval`. Its result works with `ts + iv` unchanged, but a `PgInterval` cannot be mixed with `timedelta` constants such as `RISK_RETENTION`; wrap those as `PgInterval.from_timedelta(...)`. Switch `repo_fs_controls._policy_referenced_decisions` to `admin.public.policy_case_decision_ids`.

### Final verification (round 6)

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=access_r6h TD_TEST_FIRESTORE_AUTOSTART=0 .venv/Scripts/python.exe -m pytest tests/admin/fs tests/identity/fs -q
```

**Result: 99 passed (149 s).**
- mypy: no errors in admin, identity, sessions, rbac or orgs.
- ruff: clean on those modules and both test directories.
- The SQL scan is clean.

## 12. Round 7: cross-module cleanup and helpers for other agents

### Cross-module scan (before / after)

The scan uses the method of `cleanup.md` §1. For each file it lists imports of another module's `models` and SQL string literals that name another module's table. The scanner is at `C:\Users\SYAM\AppData\Local\Temp\claude\099c798e4136fab9\88f7fa47-940f-41d2-9f5a-d10548d6f736\scratchpad\access_xmod_scan.py`.

| Module | Before | After |
|---|---|---|
| rbac | 5 | 1 (false positive: `catalogue.py:216` is the permission description string "Update batches") |
| orgs | 5 | 0 |
| identity | 3 | 0 |
| sessions | 5 | 0 |
| admin | 6 | 0 |
| **Total** | **24** | **1 (0 real)** |

Changes. Every Postgres branch now calls the owner's `public.py`, which runs equivalent SQL on Postgres:

- **rbac/service.py:**
  - `is_sole_admin` uses `rbac.public.live_grants` and `identity.public.get_users` instead of a SQL join on `users`.
  - `batch_org` and `org_exists` use `orgs.public`.
- **orgs/route_store.py:**
  - Member and student names come from `identity.public.get_profiles`. The Postgres ordering by name is applied in Python with the same rule: nulls last, then by user id.
  - `lookup_accounts` uses `identity.public.get_users` and `users_by_emails`.
- **orgs/import_website_plans.py:** `identity.public.find_user`.
- **identity:**
  - `service.mfa_failures_recent` uses `sessions.public.list_login_attempts`.
  - The `policy.get_policy` fallback (no admin resolver registered) uses `admin.public.active_policy_setting`, with the same user > platform precedence and the same validity window.
  - In the router, `remove_user_devices`, the session-choice target and the remember-me lookup use `sessions.public`.
- **sessions:**
  - `resolver.org_ids_for` uses `orgs.public.active_org_ids`.
  - Model types come from `identity.public`.
- **admin:**
  - `privacy.execute_erasure` uses `identity.public.update_user`.
  - Model types come from `identity.public`, `rbac.public` and `orgs.public`.

Model classes imported only for type hints now come from the owner's `public.py`, which re-exports them.

**Ordering caveat:** Postgres sorts names with the database collation, and the Python sort is by code point. These can differ for mixed-case or non-ASCII names. With the demo data they are the same.

**D1 confirmed:** `rbac.public.role_permission_map` and `rbac.public.batch_org` have been exported since round 3.

**`sessions.lock_user` confirmed:** on Firestore it calls `app.core.request_locks.acquire(f"sess:{user_id}")`. A new concurrency test covers it (see Tests below). When I replaced `lock_user` with a no-op, the test failed with two "authenticated" results. So it detects the race the lock prevents.

### New helpers

| Helper | For | What it does |
|---|---|---|
| `identity.public.otp_send_allowed(session, channel, destination)`, `identity.public.create_otp(session, *, purpose, channel, destination, user_id=, auth_session_id=, device_id=, ip=)`, `identity.public.check_otp(session, *, purpose, code, user_id=, auth_session_id=)` | assessments (rebind flow) | Store-neutral OTP send limit, issue and check |
| `identity.fs_journal.savepoint()` | security (detector sink) | A nested undo scope: if its block raises, its own writes are undone at once, even when the caller swallows the error. On success its entries join the outer journal, so an outer failure still undoes them. |
| `identity.fs_journal.child()` | security | Joins the open journal (round 6) |
| `sessions.public.ip_prefix(ip)` | security AB-04/05 | The /24 (IPv4) or /48 (IPv6) network of an address |
| `sessions.public.list_login_attempts_in_prefix(session, ip, *, since, until=None, outcomes=None)` | security AB-04/05 | Attempts from that network in the time window (see below) |
| `sessions.public.remove_user_devices(...)`, `sessions.public.user_device_by_remember(...)` | identity router | Store-neutral device removal and remember-me lookup |

How the network-prefix query works:
- **Firestore:** login attempts carry a new `ip_prefix` field. It is set on insert and by the backfill mapping. A composite index (`ip_prefix`, `attempted_at`) is in the sessions fragment.
- **Postgres:** it uses `ip <<= network`.
- **Same results:** the result equals filtering every attempt of the window by network (tested).
- **Older documents:** attempts written on Firestore before this change have no `ip_prefix`. Re-run the sessions backfill, or let them age out; they are not found by this query.

### Tests (emulator only)

New file `tests/identity/fs/test_fs_round7.py`, 6 tests, and 1 new test in `test_fs_public_extras.py`:
- **savepoint, failure inside a successful outer scope:** the savepoint's own writes are undone, the outer writes stay.
- **savepoint, success then outer failure:** the savepoint's writes are undone with the outer scope.
- **savepoint without an outer scope.**
- **`ip_prefix`.**
- **Prefix query equals a full scan,** for IPv4 and IPv6, with and without an outcome filter.
- **Two concurrent logins under the student session cap:** exactly one is authenticated, the other gets `session_cap_reached`, and 2 sessions are active.
- **The OTP exports** (in `test_fs_public_extras.py`).

### Final verification (round 7)

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=access_r7f TD_TEST_FIRESTORE_AUTOSTART=0 .venv/Scripts/python.exe -m pytest tests/identity/fs tests/admin/fs -q
```

**Result: 106 passed (143 s).**
- mypy: no errors in admin, identity, sessions, rbac or orgs.
- ruff check and format: clean.
- Admin SQL scan: clean.
- Cross-module scan: 1 hit, which is a false positive.

## 13. Round 8: name ordering parity

The VM database is the official `postgres:16-bookworm` image (`infra/docker/postgres/Dockerfile`, `infra/gcp-demo/docker-compose.yml`). Nothing in `db-init` overrides the locale, so the cluster uses the image default: **`en_US.utf8`, libc provider, glibc 2.36**. Text `ORDER BY` uses that collation, not code-point order.

### Postgres path: ORDER BY is back in SQL

| Where | Before (round 7) | Now |
|---|---|---|
| Batch student list (`orgs.route_store.students_named`) | Names fetched, then sorted in Python | `identity.public.users_ordered_by_full_name(session, user_ids)`. On Postgres it is one SQL query in the identity module: `VALUES (ids) LEFT JOIN user_profiles ORDER BY full_name NULLS LAST, id`. This is the same ordering, nulls rule and tie-breaker as the old join, with the database collation. |
| `orgs.public.list_batches` | Postgres rows re-sorted in Python | Every filter and the `ORDER BY (name, id)` / `(created_at, id)` / `(id)` run in SQL |
| `rbac.public.role_permission_pairs` | Postgres rows sorted in Python | `ORDER BY role_key, permission_key` in SQL |

On Postgres no access-module path re-sorts text in Python any more. The batch member list (`active_members_named`) orders by `added_at` in SQL; the names are only attached afterwards.

### Firestore path

Every Firestore text sort in these modules now uses `identity.textsort.text_key`:
- the student list;
- `list_batches` by name;
- the route store's batch lists by code and by name;
- `rbac` roles, permission keys and pairs;
- the purpose order of `current_consents`.

`text_key` delegates to the platform's shared `app.core.firestore.collation.sort_key`, so no PyICU/pyuca dependency was added here. **That module landed during this round, and it is used.** It gives:
- **exact** glibc `en_US.UTF-8` order where the process has that locale (Linux with the locale installed);
- an **emulation** elsewhere (pyuca with shifted weighting: spaces and punctuation break ties only at level 4; lower case before upper case; then a code-point tie-break).

The tie-breakers are the SQL's: NULLs last, then `user_id` / `id` in byte order, which is Postgres uuid order. (If the module were missing, `text_key` falls back to code-point order.)

### Remaining difference, precisely

- **Postgres path:** none. The ORDER BY runs in SQL, as before.
- **Firestore path:** the platform module states its own limits. Where the glibc locale is present the order is exact. Under the emulation, scripts and symbols added after Unicode 10, and some CJK compatibility forms, may order differently.
- Nothing in the access modules adds a difference of its own.

### Tests (emulator only)

`tests/identity/fs/test_fs_name_order.py`, **2 passed**:
- NULLs last, equal names ordered by `user_id`, empty input.
- Mixed case (`alice` / `Alice`), accents (`álice` / `Álice`), spaces and punctuation (`bob smith`, `o'neil` / `O'Neil`) and equal names: the order equals `sort_key` order, and accented and mixed-case names sort among their base letters.

**Full run:** `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=access_r8f TD_TEST_FIRESTORE_AUTOSTART=0 .venv/Scripts/python.exe -m pytest tests/identity/fs tests/admin/fs -q` gives **109 passed**.
- ruff check and format: clean.
- Admin SQL scan: clean.
- Cross-module scan: 1 hit, which is a known false positive.
- mypy: no errors in the five modules.

### Security SH-11 helper

`sessions.public.shared_devices_of_user(session, user_id, *, min_accounts, since)` returns the same rows as the `HAVING count(DISTINCT user_id) >= N` query in `security/signals.py`:
- the `device_id` of each `user_devices` row of the user;
- whose device was used (`last_used_at > since`) by at least N distinct accounts.

On Postgres it runs that exact SQL. On Firestore it makes one query per device of the user. It is tested against fixture-computed expectations: an old row, a never-used row, a below-threshold device, and the N=3 / N=4 boundaries.

## 14. Round 9: Firestore server-side text ordering

Firestore `order_by` on a text field orders by raw bytes; the VM database orders by its `en_US` collation. I checked every server-side `order_by` in identity, sessions, rbac, orgs and admin.

**Two user-visible lists ordered on a text field. Both are fixed:**

| List | Postgres | Firestore before | Firestore now |
|---|---|---|---|
| `GET /admin/feature-flags` (`AdminSettingsRepo.list_flags`) | `ORDER BY flag_key` | `order_by flag_key` (bytes) | Reads every flag, then sorts in memory with `collation.order_key(flag_key)` |
| `GET /admin/retention-policies` (`PrivacyRepo.retention_policies`, also behind `admin.public.retention_policies`) | `ORDER BY table_name` | `order_by table_name` (bytes) | Reads every row, then sorts with `collation.order_key(table_name)` (rows of one table stay in document-id order) |

Both are small, unpaginated platform tables, so sorting in memory is the right fit. No `sort_key` field was needed.

**Every other server-side `order_by` in the five modules is on a timestamp:** `created_at`, `attempted_at`, `received_at`, `completed_at`, `erased_at`, `started_at`.

**The admin user search** (`identity.public.search_users`) orders and keyset-paginates by user id, which is a UUID. The Firestore path sorts `uuid.UUID` values, and that equals Postgres uuid (byte) order, so no change was needed.

All text sorts done in memory in these modules already use the collation (round 8, `identity.textsort.text_key`).

**Test:** `tests/admin/fs/test_admin_access_http.py::test_flag_and_retention_lists_use_the_database_collation`.
- The flag keys are `coop_beta`, `co_op`, `Co_op_upper`, `coop`, `co-op`, `a_b`, `ab` and `aa_z`; the table names are `login_attempts`, `loginattempts`, `Login_x`, `a_b` and `ab`.
- Both lists come back over HTTP in `collation.sort_key` order.
- The test also asserts that this order differs from byte order for these keys.

**Full run (round 9):** `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=access_r9f TD_TEST_FIRESTORE_AUTOSTART=0 .venv/Scripts/python.exe -m pytest tests/identity/fs tests/admin/fs -q` gives **110 passed**. mypy shows no errors in admin, and no text `order_by` is left in the five modules.
