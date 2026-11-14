# Cleanup pass (round 7): cross-module access in the data-content scope

**Goal:** no module reads or writes another module's tables directly; it calls that module's
`public.py`, so every module can flip on its own.

**Agent:** data-content, 2026-11-12. No deploys. Every `TD_STORE_*` still defaults to `postgres`.
The Postgres behaviour is unchanged: every `public.py` used dispatches on the owner's store
switch and runs the same SQL on Postgres.

**Scope edited:**
- `commerce`, `admissions`, `notifications`, `support`, `catalog`, `entitlements`, `media`, `paths`, `analytics`, `coding`, `ai`, `audit`, `hub`;
- `app/wiring.py`;
- `app/seeds/**`.

## 1. Scan (before / after)

The scanner maps every table to the module whose `models.py` declares it. For every file in scope
it then lists (a) imports of another module's `models` and (b) SQL text naming another module's
table.

| Module / file | Before | After | Notes |
|---|---|---|---|
| wiring.py | 12 | **0** | |
| commerce | 4 | **0** | |
| support | 12 | **0** | |
| admissions | 10 | **0** | |
| notifications | 4 | **0** | |
| hub | 1 | **0** | |
| coding | 2 | **0** | |
| analytics | 22 | **1** | `hooks.py:143` is a docstring the scanner matches, not SQL. The `consumer.py` outbox read was fixed in round 8 (§7). |
| seeds | 37 | 37 | By design, see §3 |
| catalog, entitlements, media, paths, ai, audit | 0 | 0 | |
| **Total** | **104** | **38** | Outside the seeds: 67 → 1 (a docstring) |

## 2. What changed

### `wiring.py`
| Function | Now uses |
|---|---|
| `coding_problem_parents` (blocked the coding flip) | `coding.public.problem_primary_topic` + `placement.public.topic_with_root` |
| `test_parents` | `placement.public.company_paths_with_test` (+ `catalog.api`) |
| `_product_items` | `commerce.public.product_item_refs` |
| Usage provider | `learning.public.max_progress_by_course` / `has_certificate_for_courses`, `assessments.public.count_attempts` / `count_attempted_tests` |
| `video_coverage_lookup` | New `analytics.public.coverage_groups` |
| `final_test_lookup` | `assessments.public.best_result` |
| `on_false_positive_credit` | New `entitlements.public.event_exists` |
| `on_stream_cap_hit` | `security.public.report_event`, wrapped in `security.repo_fs_engine.detector_scope()`: a failed detector rolls back like a savepoint; no-op on Postgres |

### commerce
- The approval decision (`router._decide_approval`) now uses `rbac.public`: `get_approval(for_update=True)`, `expire_if_due`, and the `decision()` claim block with `mark_executed`.
- The pending coupon approvals lookup now uses `rbac.public.find_approvals`.
- `Entitlement` and `Certificate` types are imported from the `public.py` files.

### support
- **Account lookup:**
  - user and profile from `identity.public`;
  - the active restriction from `security.public.user_restrictions(active_only=True)`;
  - devices from `sessions.public.list_user_devices`;
  - sessions from `sessions.public.list_sessions`, sorted by `last_seen_at` DESC with NULLs first, limit 20, as Postgres orders them;
  - entitlements from `entitlements.public.user_entitlements`, by `starts_at` DESC, limit 20;
  - MFA count from `identity.public.active_factors`.
- **Other sites:**
  - token caps use `identity.public.verification_tokens_of` / `reset_tokens_of`;
  - the unblock link uses `security.public.get_unblock_request`;
  - the attempt link uses `assessments.public.get_attempt`;
  - priority uses `assessments.public.has_attempt_in_progress`;
  - requester cards use `identity.public.user_cards`;
  - enquiry admin recipients use `rbac.public.user_ids_with_role(platform)` + `identity.public.get_users` (active only).

### admissions
- **Accounts** (identity):
  - usernames and live-by-email lookups use `identity.public.get_users` / `users_by_emails`;
  - username checks use `username_taken`;
  - account creation uses `identity.public.create_user` / `save_profile`. A Firestore uniqueness error counts as a lost race, like `IntegrityError`.
- **Batch membership** (orgs): `orgs.public.batch_members` / `add_batch_member` / `get_batch_member` / `save_batch_member`.
- **Revocation:** `entitlements.public.get_entitlement(for_update=True)`, then `learning.public.withdraw_enrolment`.
- **Course links (R2):** `catalog.public.get_courses`.

### notifications, hub, coding
- **notifications:** user email from `identity.public.get_user`; finance admins from `rbac.public.live_grants`; batch announcements from `orgs.public.get_batch` / `batch_members` + `identity.public.get_users` (inner join kept).
- **hub:** the `User` type is imported from `identity.public`.
- **coding:** the batch reader uses `orgs.public.get_batch` / `batch_members`; the attempt org uses `assessments.public.attempt_org_of_user` on both stores.

### analytics (Postgres branches)
- Consents, user flags and topic roots always go through `identity.public` / `placement.public`.
- Batches, students, enrolments and lesson progress use `orgs.public` / `learning.public` / identity, via the `fs_reports` helpers, on both stores.
- Every `JOIN users ... NOT is_synthetic` became `NOT (user_id = ANY(:syn))`, with the synthetic ids from `identity.public.list_users(is_synthetic=True)`. This gives the same rows, since analytics rows always belong to an existing account.
- The cohort batch inputs are shared (`fs_jobs.batch_cohorts`).
- `exports.py` imports `ApprovalRequest` from `rbac.public`.

### Additions the coordinator asked for
- **`catalog.public`** (for data-learning) now exports `ensure_permission`, `system_lookup`, `get_version`, `lesson_out`, `version_tree`. All are store-neutral except `system_lookup`: it runs a caller-supplied SQL statement, so on Firestore callers should use `lesson_scope` / `course_org_lookup` instead.
- **Catalog TN view without Postgres (R12):** it now falls back to core's request context (`rls_scope`, then `current_principal()`) when no route bound a view, so other modules calling `catalog.public` get the right visibility.
- **`notifications.public`:**
  - `created_documents(user_id, notification_id, dedupe_key)` returns the `(collection, id)` pairs one `notify` created;
  - `delete_notification(session, user_id, notification_id, dedupe_key)` is a store-neutral undo.

  Security's `repo_fs_engine.notification_created` can switch to `created_documents` and stop importing notifications' collection names (request S1).
- **`entitlements.public.event_exists`** and **`analytics.public.coverage_groups`** (see `wiring.py` above).
- **(b) `notifications.assert_owner_or_platform`:** no change needed. Core's `rls_scope` already resolves the scope without a Postgres session, from the system-job context or `current_principal()`.
- **(c) `on_submission_judged`:** lives in `assessments/coding.py`, not `wiring.py` (out of scope, request A1).

## 3. Seeds

Seeds write demo rows into many modules' Postgres tables; that is their job, and these are the 37
remaining hits. New `app/seeds/sync.py` `sync_touched(session, *modules)` backfills each touched
module that is on Firestore (modules without a mapping are skipped). Every seed now calls it with
the modules it writes:
- `catalog_demo`, `coding_demo`, `commerce_demo`;
- `company_demo`: identity, orgs, learning, assessments, engage, paths, placement, support;
- `dev_users`, `e2e_demo`, `placement_demo`, `security_demo`.

`e2e_env` only reads. Seeding a stack with **no Postgres at all** would need the seeds rewritten
onto each module's `public.py` write APIs. That is not done here (see §5).

## 4. Remaining cross-module accesses outside my scope (by file)

From the same scanner, excluding seeds. Counts are hits (model imports + SQL naming another
module's table):

| Owner (agent) | Files (hits) |
|---|---|
| security (security agents) | `signals.py` 5, `engine.py` 3, `cases.py` 3, `unblock.py` 2, `timeline.py` 2, `restrictions.py` 2, `api_review.py` 2, `tasks.py` 1, `reports.py` 1, `repo_fs_controls.py` 1, `public.py` 1, `controls.py` 1, `api_student.py` 1 |
| assessments (data-assess) | `attempts.py` 7, `coding.py` 3, `studio.py` 2, `integrity.py` 2, `report.py` 1, `evaluation.py` 1 |
| placement (data-assess) | `mentoring.py` 4, `practice.py` 3, `bank.py` 2, `policies.py` 1 |
| rbac / orgs / identity / sessions / admin (data-access) | `rbac/service.py` 4, `rbac/catalogue.py` 1, `orgs/route_store.py` 4, `orgs/import_website_plans.py` 1, `identity/service.py` 1, `identity/router.py` 1, `identity/policy.py` 1, `sessions/resolver.py` 2, `sessions/service.py` 1, `sessions/router.py` 1, `sessions/login.py` 1, `admin/accounts.py` 2, `admin/router.py` 1, `admin/privacy.py` 1, `admin/courses_overview.py` 1, `admin/approvals.py` 1 |
| core (platform) | `migration_helpers.py` 1 |

## 5. Requests

| # | To | Request |
|---|---|---|
| A1 | data-assess | `assessments/coding.py` `on_submission_judged` (registered in `wiring.py`): run on core's `store_session()` / `MemoryTx` when there is no Postgres. |
| S1 | security | `repo_fs_engine.notification_created`: use `notifications.public.created_documents` and drop the `notifications.store_specs` import. |
| P1 | platform | **Done (round 8):** `app.core.outbox.read_events` is in use (§7). Follow-up: `app.core.db.no_session()` does not count a `MemoryTx` as session-less, so `read_events` takes its Postgres branch whenever `postgres_enabled()` is true, even inside a `MemoryTx`. That is correct on the final stack; consider counting `MemoryTx` too. |
| D1 | data-access | Re-export `role_permission_map` / `batch_org` in `rbac.public`: `catalog/router.py` studio listing still imports them from `rbac.service` (both are store-aware). |
| L1 | data-learning | Prefer `catalog.public.lesson_scope` / `course_org_lookup` over `system_lookup` on Firestore. |
| ALL | owners in §4 | Switch the listed files to the owners' `public.py`. |
| SEEDS | coordinator | Decide whether demo seeding on a no-Postgres stack is needed; if so, seeds must move to the modules' `public.py` write APIs. |

## 6. Tests

```
cd apps/api
export TD_TEST_NO_PG=1 TD_TEST_DB_NAME=cleanup_test TD_TEST_FIRESTORE_AUTOSTART=0
.venv/Scripts/python.exe -m pytest tests/commerce tests/admissions tests/notifications tests/support \
  tests/catalog tests/entitlements tests/media tests/paths tests/analytics tests/coding tests/hub \
  tests/seeds tests/ai tests/audit -q -p no:cacheprovider
#   -> 271 passed, 393 skipped (Postgres-backed), 1 failed (3 min 50 s)
```

The single failure is `tests/audit/test_audit_api.py::test_bad_cursor_and_missing_seq`. It connects to Postgres (`:15432`) through the app without a Postgres fixture, so `TD_TEST_NO_PG` does not skip it. It is environment-dependent; no audit code was changed in this pass.

ruff check / format are clean on every edited module, `wiring.py` and the seeds. mypy shows no new errors in the edited modules. Two errors remain in admissions files this pass did not touch: `rules.py:110` and `files.py:98`.

Not run (policy): the Postgres-backed suites. On Postgres the changed code paths call the owners' `public.py`, which run the same SQL. The behaviour differences are the documented reorderings, which give the same rows.


## 7. Round 8: `analytics.consumer.consume_outbox` without SQL on `outbox_events`

**Change:**
- New `consumer.unconsumed_events(session, since, limit)` reads through `app.core.outbox.read_events` (both stores, ordered `(occurred_at, id)`).
- It drops ids this module already consumed (`analytics_consumed_events`: one `ANY(:ids)` query on Postgres, documents on Firestore). It pages with `after=(occurred_at, id)` until `limit` unconsumed events are found or the outbox ends.
- This is the old `... AND NOT EXISTS (consumed) ORDER BY occurred_at, id LIMIT :n`: same rows, same order, same limit.
- Both the Postgres and the Firestore consumer paths use it. The direct Firestore outbox reader (`fs_raw.outbox_events_since`) was removed.

**Test** (`tests/analytics/fs/test_consumer_outbox_firestore.py`):
- The fixture has 5 handled events and 1 unhandled event in the Firestore outbox, with one handled event pre-consumed, on a `MemoryTx` with `postgres_enabled()` false (the final stack).
- With `limit=2`, three runs consume exactly the expected ids in `read_events` order, skipping the consumed one (keyset paging past it).
- The third run sees 0. The unhandled event is never read, and every handled id ends up consumed.

**Results:** `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=cleanup_test pytest tests/analytics` gives **57 passed, 46 skipped** (Postgres-only). ruff is clean.

## 8. Round 9: Postgres collation for Firestore-path text ordering

Applies to catalog, entitlements, media, paths, analytics, notifications, support and hub. On this
machine `app.core.firestore.collation.mode()` is `uca` (emulated en_US; glibc's locale is not
available on Windows).

### In-memory text ORDER BY: switched to the collation helper

| Site | SQL it replaces | Fix |
|---|---|---|
| `paths/adapters.batch_people` (allocate picker) | `ORDER BY full_name, email` | `collation.sort_rows`: collation plus NULLS LAST. This path now serves both stores, since it composes `orgs.public` and `identity.public`. |
| `analytics/fs_reports.ingest_health_rows` | `GROUP BY code ORDER BY code` | `sort_key(code)` |
| `analytics/feeds._fs_engaged_buckets` | `... ORDER BY bucket, device_id, auth_session_id, activity_kind` | `sort_key(activity_kind)`. The uuid columns keep the uuid order with NULLS LAST. |
| `analytics/fs_jobs._max_text_uuid` | `max(col::text)` | `max(..., key=sort_key)` |

Every other in-memory sort in these modules is on UUIDs (`str(uuid)` is fixed-width lowercase hex, so it orders like Postgres uuid), dates, timestamps or numbers. Unchanged.

### Firestore server-side `order_by`: no TEXT fields

Every `order_by` in these modules is on a timestamp or date (`created_at`, `updated_at`, `started_at`, `occurred_at`, `received_at`, `hour_start`, `activity_date`, `ends_at`, `grace_ends_at`, `resolved_at`) or a UUID (`id`, `topic_id`; the document id tie-break is a UUID too). Support's dynamic `tickets_of(order=...)` is only called with `created_at`. So no sort-key field is needed, and there is no backfill change.

### Engine modules (commerce, admissions)

`app/core/firestore/sqlstore.py` already applies `collation.order_key` (collation, citext via `lower()`, Postgres NULLS defaults) in its ORDER BY. Nothing was duplicated.

### Tests
- `tests/paths/fs/test_collation_paths.py`: mixed case, accents, an equal name decided by email, and NULLS LAST. The expected order is written out as `en_US.utf8` sorts it:
  `Ábel, apple(A@), apple(b@), Eclair, éclair, Zebra, NULL`.
- `tests/analytics/fs/test_collation_analytics.py`:
  - rejection codes: punctuation ignored at the first level and case at the tertiary level, `ab, a_z, rate, Rate, rated` (byte order would differ);
  - `max(uuid::text)`.
- Also: analytics' `postgres_enabled` test patch was dropped, because core `no_session()` now treats `MemoryTx` as having no Postgres.

### Results (`TD_TEST_NO_PG=1 TD_TEST_DB_NAME=cleanup_test`)
- `tests/catalog tests/entitlements tests/media tests/paths tests/analytics tests/notifications tests/support tests/hub` gives **132 passed, 191 skipped** (the skipped ones need Postgres).
- After dropping the patch, `tests/analytics tests/paths/fs` gives **64 passed, 46 skipped**.
- ruff is clean, and mypy shows no issues in the edited modules.
