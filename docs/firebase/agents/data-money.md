# DATA-MONEY agent: commerce, admissions, notifications, support on Firestore

Date: 2026-11-12, rounds 1 and 2. Scope: `TD_STORE_COMMERCE` / `ADMISSIONS` / `NOTIFICATIONS` / `SUPPORT`.
Every switch still defaults to **`postgres`**. Nothing was deployed or flipped, and the VM was not touched.

Test policy (owner, round 2):
- Tests run on the Firebase emulator only, with `TD_TEST_NO_PG=1` and `TD_TEST_DB_NAME=money_test`.
- No Postgres is used and there are no matrix runs.
- Parity is checked later against the live VM.

## 1. Status

| Module | State | Tests (emulator) |
|---|---|---|
| **commerce** | <ul><li>Every statement is routed through the shared SQL-on-Firestore engine.</li><li>Routes, the webhook and the jobs work on a stack with **no Postgres** (`MemoryTx`).</li><li>Reads of other modules go through their `public.py` (identity, entitlements, learning).</li><li>`public.py` API added.</li><li>Index fragment.</li><li>The FK-drop migration is written and **not applied** (§5).</li></ul> | 26 (engine 12, money flows 8, HTTP 5, smoke 1) |
| **admissions** | <ul><li>Every statement is routed through the same engine (`store_specs.SPEC`, `datastore.py`).</li><li>The ledger trigger, partial uniques and append-only events are emulated.</li><li>Batch reads go through `orgs.public`.</li><li>The public course-status and plan routes work without Postgres.</li><li>`public_api.py` added (the name `public.py` was already taken by the website routes).</li></ul> | 8, plus 1 HTTP test in the commerce HTTP file |
| **notifications** | <ul><li>Done per P2b.</li><li>`public.py` added.</li><li>Its commerce reads now go through `commerce.public`.</li></ul> | Its tests need Postgres: skipped |
| **support** | <ul><li>Done per P2b.</li><li>`public.py` added (`dashboard_counts`).</li><li>Its order reads now go through `commerce.public`.</li></ul> | Its tests need Postgres: skipped |

**Commerce flip readiness.** Commerce is complete on my side. Flipping still needs:
- the migration in §5, run at flip time;
- the other modules' remaining direct reads, listed in §7;
- an approvals API for `ApprovalRequest`.

## 2. Shared engine: `app/core/firestore/sqlstore.py` (edited only by this agent)

A module declares a `SqlModuleSpec`:
- models;
- the RLS family of each table: `read_all`, `owner` or `platform`;
- unique keys, including partial ones;
- CHECKs;
- `updated_at` triggers;
- citext columns;
- no-delete and append-only tables;
- read-phase commit checks.

From the spec it gets a `SqlStore` with `execute / add / flush / refresh / get(with_for_update) / delete / begin_nested / next_counter`.

- **`postgres` switch.** Every call is passed to the session unchanged.
- **`firestore` switch.**
  - **Interpreter.** It covers the SQLAlchemy subset used: joins and outer joins, three-valued NULL logic, `IN`, `IS DISTINCT FROM`, citext, tuple keysets, ORDER BY with Postgres NULL order, aggregates with GROUP BY, `EXISTS`, `UPDATE … RETURNING`, `INSERT … ON CONFLICT DO NOTHING` and DELETE.
  - **Unit of work.** One per session: an identity map with read-your-writes and savepoints.
  - **Commit.** One Firestore transaction from SQLAlchemy `before_commit`:
    - optimistic version checks replace `FOR UPDATE`; a row that was locked but not changed is rewritten with `_lk` bumped, so two lockers can never both commit;
    - `uniq_<module>_*` reservations;
    - CHECKs and the module's commit reads;
    - gap-free counters.
  - **Lost races.** They return 409 `conflict`.
- **Stack without Postgres** (`runtime.postgres_enabled()` False), new in round 2:
  - `StoreDbSession` / `StorePrincipalDbSession` replace `DbSession` / `PrincipalDbSession` in the commerce and admissions routers. When Postgres exists they *are* `get_db` / `get_principal_db`.
  - Without Postgres they yield a `MemoryTx`:
    - the `app.*` RLS GUCs live in memory, so `system_context`, `as_system`, `tenant_context` and the RLS emulation are unchanged;
    - it commits the units of work at the end of a successful request and discards them on an error;
    - `emit_event`'s outbox insert is captured and written as `outbox_events` documents (the same documents as `core_store.emit_event_tx`) **in the same Firestore transaction** as the module rows;
    - any other SQL raises `PostgresDisabledError`.
  - `store_session()` does the same for jobs and the webhook (Postgres `session.begin()` when Postgres is available).
- **Specs:**
  - commerce: `commerce/store_specs.py` (money CHECKs, `ex_price_overlap`);
  - admissions: `admissions/store_specs.py` (`ck_afp_*`, `ck_areg_*`, `ck_apc_*`, the deferred ledger trigger `ledger_sum`, live-registration and UTR/proof uniques, append-only `admission_events`, platform-only RLS).
- **Data model:** one collection per table, with the same name (`lms_` prefix). The document id is the primary key, or `compose_id` for a composite key. The codec is: UUID→str, numeric→exact string, date→ISO, JSONB→canonical JSON string.
- **Backfill:** `SqlStore.register_backfill()` registers one mapping per table, using the same mapper the engine reads.

## 3. Platform findings (round 2)

- **`commerce.provider_webhook`** no longer opens a Postgres session: it uses `store_session()`, and so do the commerce jobs in `tasks.py`.
  - Tested over HTTP with no Postgres: a signed delivery is `accepted` and stored once, and a replay returns `duplicate`.
- **`/public/courses/status`** (admissions) works without Postgres. It runs on `StoreDbSession`, the course-status and plan rows are on Firestore, and batches come from `orgs.public.list_batches`.
  - Tested over HTTP, together with `/public/admissions/plans/{slug}`.

## 4. `public.py` (store-neutral cross-module APIs)

- **`commerce/public.py`:**
  - catalogue: `product_quotas`, `product_item_refs`, `product_ids_covering`, `product_names`, `catalogue`;
  - orders, invoices and subscriptions: `get_order`, `recent_orders`, `paid_orders_since`, `get_invoice`, `get_subscription`, `renewing_subscriptions`;
  - helpers: `get_document_store`, `gateway_status`, and `execute` (any select over commerce tables).
- **`notifications/public.py`:** `notify`, `send_email`, `send_sms`, the email/SMS adapters, `erase_user`, `register_commerce_consumers`.
- **`support/public.py`:** `dashboard_counts`.
- **`admissions/public_api.py`:** `course_statuses`, `registrations_for_user`. No other module reads admissions tables today.

## 5. FK-drop migration: written, NOT applied

`apps/api/migrations/flip/commerce_0005_drop_inbound_fks.py` (revision `commerce_0005`, down `commerce_0004`, depends on `entitlements_0003` and `support_0004`):
- It drops these FKs into commerce tables:
  - `entitlements` → `products`, `order_items`, `subscriptions`, `coupon_redemptions`;
  - `support_tickets.related_order_id` → `orders`.
- Downgrade re-adds them.
- It sits **outside `version_locations`**, so `alembic upgrade heads`, the tests and deploys never run it. A test checks this.
- At the commerce flip only:

```
git mv apps/api/migrations/flip/commerce_0005_drop_inbound_fks.py apps/api/migrations/versions/
cd apps/api && .venv/Scripts/python -m alembic upgrade heads
```

Admissions has no inbound FKs from other modules. Its outbound FKs (to users and batches) become irrelevant once its rows live in Firestore.

## 6. Commands and results (emulator 127.0.0.1:18080, no Postgres)

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=money_test .venv/Scripts/python -m pytest tests/commerce/firestore tests/admissions/firestore -q
  -> 34 passed (62.7 s)
TD_TEST_NO_PG=1 ... pytest tests/notifications tests/support tests/commerce tests/admissions --ignore=…/firestore -q
  -> 27 passed, 130 skipped (the Postgres tests skip by policy)
TD_TEST_NO_PG=1 ... pytest tests/firestore/test_store_boundary.py -q -> 5 passed
ruff check (my modules, tests, sqlstore) -> clean
mypy app/modules/{commerce,admissions,notifications,support} app/core/firestore/sqlstore.py
  -> clean, apart from 2 old errors in admissions/rules.py:110 and files.py:98 that predate this work
```

**HTTP tests** (`tests/commerce/firestore/test_http.py`) run through the real app with `postgres_enabled()` False. These modules are on Firestore: commerce, admissions, core, audit, orgs, entitlements, identity and learning. Only the principal is injected; the database dependencies are not overridden. They cover:
- the public catalogue, and a 404 for an unknown product;
- `/me/orders` scoped to the owner, order detail, and 404 for another user's order;
- order cancel committed at the end of the request, plus idempotent replay through core's Firestore idempotency;
- the webhook, accepted once and then reported as a duplicate;
- admissions course status and plan.

## 7. Gaps and requests to other agents

1. **Direct reads of my tables by other modules.** These should switch to `commerce.public`; each change is one line:
   - `entitlements/service.py`: `quotas_for_product` → `product_quotas`, and `covering_scope` → `product_ids_covering`;
   - `entitlements/router.py`: `_titles` → `product_names`, and `admin.catalogue` → `catalogue`;
   - `admin/accounts.py`: the dashboard's `Order` stats → `paid_orders_since`;
   - `app/wiring.py`: `_product_items` (raw SQL) → `product_item_refs`;
   - `app/seeds/commerce_demo.py`: call `sync_if_enabled(db, "commerce")`.
2. **Approvals.** Commerce still selects `ApprovalRequest` directly (`admin.pending_coupon_approvals`, `router._decide_approval`). This needs a store-neutral approvals API from the rbac/admin owner.
3. **Admissions enrolment and onboarding.** These still call identity (users, password), learning (enrolments) and orgs (batch members) through those modules' current code. They need those modules on Firestore, plus a pass that switches the remaining direct `select(User/Enrolment/BatchMember)` calls to their `public.py`. Registration, claims, verification and the status routes are covered.
4. **Known differences.**
   - A lost race returns 409 where Postgres would wait.
   - On a stack that has Postgres, Firestore commits just before Postgres.
   - Admissions `SET CONSTRAINTS ALL IMMEDIATE`: the ledger is checked at commit, so after the login email has been sent.
   - Lists without a filter scan the whole collection (fine for demo data).

Round-1 details (engine design and the money-flow proofs) are unchanged and are the basis of §2.

## 8. Round 3: no external side effect from a transaction that cannot commit

**The problem.** On Postgres, `deliver_login_email` runs `SET CONSTRAINTS ALL IMMEDIATE`, so the deferred ledger trigger fires **before** the email is sent. The row locks held by the transaction also mean the later commit cannot lose a race. On Firestore both of those checks ran only at commit, which happens after the email has gone out.

**The fix: an engine precheck.**
- `sqlstore.UnitOfWork.commit(dry_run=True)` and `sqlstore.precheck_all(session)` run every commit check in a read-only Firestore transaction and write nothing. The checks are:
  - the versions of locked or changed rows;
  - uniqueness reservations, and that new document ids are free;
  - CHECKs, RLS write rules and append-only tables;
  - the module's commit reads (the admissions ledger trigger, commerce `ex_price_overlap`);
  - counters.
- Each datastore exposes the precheck to its module:
  - `admissions.datastore.constraints_immediate(session)` keeps `SET CONSTRAINTS ALL IMMEDIATE` on Postgres and runs the precheck on Firestore;
  - `commerce.datastore.before_side_effect(session)` and `admissions.datastore.before_side_effect(session)` run the precheck on Firestore and do nothing on Postgres, where row locks already give the same guarantee.

**Why not move the email to after the commit?** The Postgres path sends it before the commit, and the HTTP response reports what the provider answered (`email.sent` / `reason`, `login_email_sent_at`). Sending it after the commit would change the API.

With the precheck, the Firestore order is the same as on Postgres:
1. check everything;
2. call the side effect;
3. commit.

The race window that remains is the time between the precheck and the commit (milliseconds). Postgres has no such window, because it holds the locks. A loser in that window gets 409, and only if a concurrent writer changed the same rows within those milliseconds.

**Every external side effect in commerce and admissions that runs before the commit, and what was done:**

| Where | Side effect | Change |
|---|---|---|
| `admissions/onboarding.deliver_login_email` | Login email (with a temporary password) | `ads.constraints_immediate` replaces the inline `SET CONSTRAINTS` |
| `admissions/service._store_claim` | Payment proof upload to the file store | `ads.before_side_effect` |
| `admissions/service.register` | Résumé upload to the file store | `ads.before_side_effect` |
| `commerce/service.create_order` | Razorpay `create_order` | `ds.before_side_effect` |
| `commerce/service.create_subscription` | Razorpay `create_subscription` | `ds.before_side_effect` |
| `commerce/service.cancel_subscription` | Razorpay `cancel_subscription` | `ds.before_side_effect` |
| `commerce/service.submit_refund` | Razorpay `create_refund` (money moves) | `ds.before_side_effect` |
| `commerce/billing.resume_subscription` | Razorpay `undo_scheduled_cancel` | `ds.before_side_effect` |
| `commerce/billing.change_plan` | Razorpay `add_subscription_addon` + `update_subscription_plan` | `ds.before_side_effect` (one check before both calls) |
| `commerce/billing.render_gst_export` | GST CSV to the file store | `ds.before_side_effect` |
| `commerce/documents.ensure_invoice_pdf` | Invoice PDF to the file store | `ds.before_side_effect` |

These need no change:
- **Already after the commit:**
  - `commerce/router.provider_webhook` → `enqueue_webhook_event`;
  - the admissions status emails (`admissions/notify.py`, an outbox handler);
  - the commerce emails (notifications consumers of outbox events).
- **Read-only:** gateway `fetch_*` calls.
- **Compensation on an error path:** `commerce/billing._compensate_addon`.
- **Outbox events on a stack without Postgres:** written in the same Firestore transaction as the rows (§2).

**Outside my scope (request to the audit owner).** With `TD_STORE_AUDIT=firestore`, `app.core.audit.audit()` writes through `enqueue_now`, in its own transaction, the moment it is called. On a request that later fails, the audit row stays; on Postgres it would roll back. A fix would take an after-commit hook: the engine already commits units of work at a single point (`commit_all`), so audit could queue its rows into the session and have them written there.

**Admissions user reads.** `staff_actor`, the login-email path, enrolment and the student page now read users and profiles through `identity.public`. `_reload_user` replaces `session.refresh(user)`: on Postgres it still calls `session.refresh(user)`; on Firestore it re-reads the user from the identity store.

**Tests (emulator, `TD_TEST_NO_PG=1`, `TD_TEST_DB_NAME=money_test`).**

`tests/admissions/firestore/test_http_side_effects.py` runs over HTTP through the real app with no Postgres. Only the staff principal and the email transport are injected.
- `test_login_email_is_sent_and_recorded`: returns 200, sends exactly one email and commits `login_email_sent_at`.
- `test_failed_ledger_check_sends_no_email`:
  - the request sets `verified_total_paise` with no verified claim behind it;
  - the response is a 500, as Postgres's `23514` would be;
  - **no email** was sent;
  - nothing was committed: no `login_email_sent_at`, no event.

`tests/commerce/firestore/test_money_flows.py::test_provider_refund_is_never_called_for_a_transaction_that_cannot_commit`: a concurrent change to the locked order makes the approval unable to commit. The result is 409, and the fake provider received **no** refund.

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=money_test .venv/Scripts/python -m pytest tests/commerce/firestore tests/admissions/firestore tests/firestore/test_store_boundary.py -q
  -> 42 passed (73.8 s)
ruff check / ruff format (my modules, sqlstore, tests) -> clean
mypy (commerce, admissions, notifications, support, sqlstore) -> clean, apart from the 2 older admissions errors
```
