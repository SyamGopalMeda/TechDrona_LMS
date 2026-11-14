# parity-nopg agent: Firebase "no Postgres session" parity bugs (2026-11-13)

Rule followed: **the VM (Postgres) behaviour is the spec.** On the VM nothing changes: every fix
below takes the exact old code path whenever a SQL session or a Postgres session factory exists.
No deploys. `apps/web` untouched. No tree-wide formatter (ruff format only on the files listed in §5).

## 1. What was wrong

On the Firebase stack (`TD_RUNTIME=firebase`, every `TD_STORE_<MODULE>=firestore`, no
`DATABASE_URL`) a router on `app.core.db.PrincipalDbSession` / `DbSession` gets the falsy
`NO_POSTGRES` placeholder. Any attribute use on it raises `PostgresDisabledError`. Three shapes of
the bug:

- **A. Reads of SQL-on-Firestore tables through `NO_POSTGRES`.** The tables are commerce,
  assessments, admissions, analytics exports and security controls. `SqlStore.execute` needs
  `session.info` and the RLS GUCs. The main entry point is
  `entitlements.evaluate → covering_scope → commerce.product_ids_covering`. That makes
  `require_access` / `check_access` answer 500 for every *paid, non-free* resource on any router
  using the core session.
- **B. `session.begin_nested()` on `NO_POSTGRES`.** It either raised, or was swallowed by an
  `except Exception`, which silently changed the behaviour.
- **C. Jobs that open `get_sessionmaker()` without checking for Postgres.**

## 2. Fixes

### 2.1 Central fix for A: read-only detached unit of work

**Change:** `app/core/firestore/sqlstore.py` (`SqlStore.execute`, `_detached_read`, `_detached_scope`)
and `app/core/db.py` (`current_platform_job`).

When `SqlStore.execute` (and so `SqlStore.get`) gets **no SQL session at all** (`NO_POSTGRES` /
`None`), the module is on Firestore and the statement is a plain `SELECT` without `FOR UPDATE`, the
statement now runs on a throwaway `UnitOfWork`. It runs under the caller's RLS scope, derived exactly
the way `db.rls_scope` derives it for a no-Postgres session:

- platform inside `system_context` and in jobs or scripts;
- otherwise the request principal's `tenant_context` (user, org ids, platform flag);
- the empty context for an anonymous request.

**Why it is behaviour-identical:**

- A no-SQL session can hold no pending SQL-engine writes, because every write on it raises. So the
  read sees exactly what the Postgres transaction would see.
- The RLS scope is the one Postgres would apply.
- Writes, `FOR UPDATE`, `flush`, `add` and savepoints on `NO_POSTGRES` still raise as before. They
  need a request or job `MemoryTx`, and none was found on a Firebase path (§3).
- On the VM, `session` is a real `AsyncSession`, so the branch is never taken.

This generalises what `assessments.public._sess` and `admin.accounts._read_session` already did by
hand. It fixes every `entitlements.evaluate` caller at once: routers, outbox consumers and jobs.

**Routes it fixes** (all verified over HTTP, §4):

- **Learning:** LRN-05 / LRN-06 / LRN-10 (paid lessons, completion, assignment submit), LRN-03
  (enrol into a paid course).
- **Entitlements:** ENT-01/02 for an entitled user, ENT-03 product names, ENT-06 grant of a product
  (`quotas_for_product`).
- **Mentoring:** booking with a package quota.
- **Support:** ticket priority (`has_attempt_in_progress`) and `related_order_id` / attempt checks.
- **Placement:** practice entitlement.
- **Admin and notifications:** the admin dashboard, and the notifications consumers
  (`get_invoice`, `get_subscription`, `renewing_subscriptions`).

### 2.2 Entitlement cache bump on a non-SQLAlchemy session

**Change:** `app/modules/entitlements/cache.py`, `bump_after_commit`.

**Bug:** ENT-06 manual grant answered **500**. `bump_after_commit` read `session.sync_session` on
`NO_POSTGRES`. On a `MemoryTx` it would also have failed: `event.listen` on a non-Session object.

**Fix:**

- On `NO_POSTGRES` / `None` the Firestore rows are already committed, so the version bump is
  scheduled at once.
- On a `MemoryTx` it runs after the units of work commit (`sqlstore.after_commit`). This is the
  equivalent of the SQLAlchemy `after_commit` hook.
- The SQLAlchemy path is unchanged.

The existing fs tests had stubbed `bump_after_commit`, so they never saw this.

### 2.3 Savepoints and job sessions

**New helpers in `app/core/db.py`:**

- **`savepoint(session)`:** `begin_nested()` on a SQL session (VM, unchanged; also a `MemoryTx`),
  and no savepoint on `NO_POSTGRES` / `None`. It generalises `learning.certificates.savepoint`.
- **`job_session(job)`:** with Postgres, `get_sessionmaker()` + `begin()` +
  `await system_context(...)`, exactly what the jobs did inline. Without Postgres (the same test as
  `get_db`), the `NO_POSTGRES` placeholder inside `system_context` (platform `rls_scope`).

**Sites changed:**

| Site | Bug on Firebase | Fix |
|---|---|---|
| `placement/practice.py` `analytics_mastery` | `begin_nested` raised and was swallowed. `/me/mastery`, `/me/recommendations` and the weak-topic lists **silently used the interim EWMA instead of the analytics mastery** (the CP-11 single writer). | `savepoint(session)` |
| `learning/tasks.py` `_send` / `_batch_end` / `_backfill` (certificate e-mail send, batch-end issue, PDF backfill) | `get_sessionmaker()` raised `PostgresDisabledError` | `job_session` (kept inside `learning/`, as agreed with the scheduler agent) |
| `media/tasks.py` `scan_sweep` | same | `job_session` |
| `notifications/tasks.py` `renewal_reminders` | same | `job_session` |
| `support/tasks.py` `auto_close` | same | `job_session` |
| `ai/service.py` `_settings_for_rate(None)` | went to `ledger_tx`, a Postgres-only separate transaction | reads `store.system_settings` when ai is on Firestore (it already reads Firestore) |

## 3. Every site in the brief's list, and the verdict

### 3.1 Suspected routers and services

| Site | Verdict |
|---|---|
| `learning/router.py` LRN-05/06/10 (+ LRN-03/04, assignments, LRN-20 certificate) | **Was broken (A).** Fixed by §2.1. HTTP-tested. |
| `entitlements/router.py` | **Was broken:** A, plus §2.2 (grant 500). Fixed. HTTP-tested (check, check-batch denial path, grants, `/me/entitlements`). |
| `hub/router.py` | Only `gateway_status()` (no session). OK. HTTP-tested (`/me/modules`, `/public/integrations`). |
| `mentoring/service.py` | Quota reads through `evaluate` (A). Fixed. HTTP-tested (slots, book, reschedule, cancel with credit restore). |
| `paths/adapters.py` | Assessments reads go through `assessments.public._sess` (already safe). Commerce through A. HTTP-tested (batch, path, allocate, open, complete, progress, link options, AI draft). |
| `placement/bank.py`, `placement/practice.py` | Assessments reads safe; entitlement through A; `analytics_mastery` fixed in §2.3. HTTP-tested. |
| `support/router.py`, `support/service.py` | Commerce and assessments reads through A or `_sess`. HTTP-tested (ticket create, staff view, patch, messages, SUP-11 user lookup). |
| `admin/accounts.py` | The dashboard used its own `_read_session`. HTTP-tested (dashboard, users, detail, deactivate, reactivate). |
| `admin/flags.py` | Already guarded (`uses_firestore` / `_postgres_enabled`). HTTP-tested (list, patch). |
| `notifications/consumers.py` | Commerce reads through A. The outbox relay runs in every harness flow. |

### 3.2 `begin_nested` sites

| Site | Verdict |
|---|---|
| `placement/practice.py:368` | Postgres branch only (`_fs()` returns earlier). OK. |
| `placement/practice.py:651` | **Was broken.** Fixed (§2.3). |
| `orgs/route_store.py` (4 sites) | Postgres branches only; the Firestore branches use `OrgsRepo`. OK. HTTP-tested (batch create, members). |
| `security/cases.py:356` | Runs on `SecSession` (`sec_route` wraps every security route on Firestore), which has its own `begin_nested`. OK. |
| `security/signals.py:771` | Already guarded (`if not session`). OK. |
| `commerce/service.py:1179` | Commerce routes use `StorePrincipalDbSession`, so the session is a `MemoryTx`, whose `begin_nested` works. OK. |
| `analytics/consumer.py:457` | Postgres branch only (`if _fs(): return ...`). OK. |
| `core/idempotency.py:177` | Postgres branch only; on Firebase `idempotent_firestore` guards with `no_sql_session`. |
| `learning/documents.py:655`, `learning/service.py:180` | Postgres branches only. |
| `media/service.py:64` | The media router is on `StorePrincipalDbSession` (cost-media round 2). |
| `core/outbox.py:247` | Postgres relay only. Not touched (scheduler agent's file). |

### 3.3 `get_sessionmaker()` sites

| Site | Verdict |
|---|---|
| `learning/tasks.py`, `media/tasks.py`, `notifications/tasks.py`, `support/tasks.py` | **Were broken.** Fixed (§2.3). |
| `admin/flags.py`, `admin/tasks.py`, `assessments/tasks.py`, `coding/worker.py`, `placement/tasks.py`, `sessions/service.py` | Already guarded. |
| commerce, analytics and security jobs | Use `sqlstore.store_session`. |
| `ai/store.py` `ledger_tx` | Reached only from Postgres branches, plus `_settings_for_rate(None)`, now fixed. |
| `app/worker.py`, `core/health.py`, backfill / import / seed scripts | Not request or job paths on Firebase, or the scheduler agent's files. Not touched. |

### 3.4 Raw `session.execute`

An AST scan of every module was done: every function that runs SQL without a store guard. It is
the admin scan `tests/admin/fs/test_no_unguarded_sql.py`, applied to all modules. It gives
**281 hits**.

Almost all are false positives:

- statement builders that run on the SQL engine (commerce, assessments, admissions, analytics
  exports, security controls);
- security code running on `SecSession`;
- Postgres-only helpers called only from guarded branches;
- guards under other names (`on_firestore`, `fss.fs`, `_fs`).

The HTTP harness is the check that counts: it runs the real flows with Postgres absent.

## 4. The parity harness: `apps/api/tests/parity/`

### 4.1 How it runs

- **The real FastAPI app over HTTP**, on the Firestore emulator.
- **Every module in `backend.MODULES` on Firestore,** and `TD_CACHE_BACKEND=firestore`.
- **No Postgres at all:** `DATABASE_URL=""`, so `get_engine()` raises as on Firebase, and the
  request sessions are `NO_POSTGRES` (`install_fake_db`).
- **Only external things are replaced:**
  - authentication: `FakeAuth`; staff principals hold the Admin role (`super_admin`), and every
    principal is also a real identity user in Firestore;
  - object storage: `MemoryDocumentStore`;
  - the role→permission lookup: `rbac.role_permission_map` returns `rbac.catalogue`, which is what
    the deployed collections are seeded from;
  - the payment gateway: `FakePaymentProvider`;
  - the coding judge: `FakeJudgeAdapter`.
- **Audit, outbox, idempotency, rate limits, entitlements, commerce and the rest all run for real.**
- **`World.call`** never accepts a 500 and asserts the VM status codes. The expected codes were read
  from the Postgres suites and are listed in each test's docstring.
- **`World.relay()`** dispatches the Firestore outbox exactly as `app.worker` does on Firebase
  (`relay_pending_firestore`, handlers get `session=None`). Any failing consumer fails the test,
  with its traceback.

### 4.2 Flows covered

| Test file | Flow |
|---|---|
| `test_learning_parity.py` | Admin authors, submits and publishes a **paid** course (studio), with SoD between two admins. ENT-01 denial, then a 403 on enrol. ENT-06 admin grant. LRN-03 201, then 200. LRN-04. LRN-05 paid (`entitlement`) and preview lessons. LRN-06 completion. Dashboard. A second learner gets LRN-05 403 `entitlement_required`. Assignment: LRN-14 create, LRN-10 submit (entitlement-checked; a non-entitled learner is refused), LRN-17 grade, LRN-18 release. LRN-20 manual certificate, then the outbox relay (PDF and queued e-mail), then LRN-11/12/13 and LRN-30/32/33/39. The certificate jobs. |
| `test_commerce_parity.py` | Finance product, plan and price (HTTP). Consent. COM-03 quote, COM-04 order. The gateway webhook `payment.captured`. Order `paid`, `/me/orders`, ENT-01 allowed. Enrol, then the paid lesson opens. Relay. |
| `test_assess_coding_parity.py` | Question author, review, publish. Paid test. ATT-01 403 without entitlement, then 201 after the `all_tests` grant. Autosave, submit, result, evaluation. Coding: problem, sample and hidden cases, reference, validate, publish. Submit 403, then 202 after the grant. Judge worker. Submission `completed`/`AC`. |
| `test_mentoring_parity.py` | Placement-package product with a `mentor_sessions` quota, granted by ENT-06 (quota from the product). Mentor slots, book (quota 2→1), reschedule, mentor sessions, cancel with `credit_restored`. |
| `test_paths_parity.py` | Batch and member (orgs). Path create, steps, link options (4 kinds), publish, allocate. Learner `/me/paths`, open, complete. Staff progress. AI draft (never 500). |
| `test_placement_parity.py` | Topic and questions. Practice 403, then 201 after the `all_practice` grant. Answer with an idempotent replay, state, complete, recommendations, practice review. **`/me/mastery` uses the analytics mastery** (regression for §2.3). Question report, then resolve. Notifications. |
| `test_ops_parity.py` | Support tickets (assessment and billing), queue, staff view, patch, messages both ways, SUP-11 user lookup. Admin dashboard, user search and detail, deactivate, reactivate, flags list and patch, courses overview. Hub modules and integrations. Notifications inbox, read-all, read. |
| `test_jobs_parity.py` | Every periodic or on-demand job runs with no Postgres session factory: support, media, notifications, learning (×3), admin break-glass, placement media sweep, assessments sweep, commerce (×5), analytics exports, security (×5). |

### 4.3 Proof that the fixes are needed

- **Central fix:** with `_detached_read` disabled, 6 of the 11 tests fail (learning ×2, commerce,
  mentoring, support, placement).
- **Practice mastery:** with `begin_nested` restored in `analytics_mastery`, the placement test fails.
- **Jobs:** `learning`, `media`, `notifications` and `support` `get_sessionmaker()` raise on the
  harness, where `DATABASE_URL` is empty.

### 4.4 How to run it

Run it with your own namespace, so parallel agents do not wipe each other's data:

```
cd apps/api; TD_TEST_DB_NAME=parity_nopg TD_TEST_NO_PG=1 .venv/Scripts/python -m pytest tests/parity
```

## 5. Files changed

**App code:**

- `app/core/db.py`: `current_platform_job`, `savepoint`, `job_session` (additive).
- `app/core/firestore/sqlstore.py`: the detached read in `SqlStore.execute`, plus the two helpers.
- `app/modules/entitlements/cache.py`: `bump_after_commit`.
- `app/modules/learning/tasks.py`, `app/modules/media/tasks.py`, `app/modules/notifications/tasks.py`,
  `app/modules/support/tasks.py`: `job_session`.
- `app/modules/placement/practice.py`: `analytics_mastery`.
- `app/modules/ai/service.py`: `_settings_for_rate`.

**Tests:** `tests/parity/` (new): `conftest.py`, `harness.py` and the 8 test files in §4.

**Files owned by other agents:** none of them were edited. That covers `store.py`, `kv.py`,
middleware, sessions, identity, rbac, `ratelimit`, `functions-lms/main.py`, `cloudtasks`, `jobs`,
`jobhints`, `scheduler`, `outbox` and `audit`.

## 6. Still open: not parity bugs, so the VM is unchanged

- **`practice.answered` → analytics mastery fails for new questions.** Placement emits `difficulty`
  as an int (1–5). `analytics.mastery._item_difficulty` calls `.lower()` on it when the item has no
  calibrated difficulty (`question_item_stats` row). The handler raises `AttributeError` **on the VM
  too**, so practice answers never update topic mastery until items are calibrated. The harness
  allowlists exactly this failure (`VM_KNOWN_FAILURES`). Fixing it changes VM behaviour, so it
  needs an owner or analytics decision.
- **Free-course lesson analytics are rejected.** This is the pre-existing VM behaviour reported in
  cost-media §6.4. Not changed.
- **Pre-existing mypy notes, not in my files:** `tests/conftest.py:119`,
  `tests/firestore/conftest.py:113` and `tests/coding/conftest.py:117` have unused `type: ignore`
  comments.
