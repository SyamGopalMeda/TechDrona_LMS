# Data-analytics agent: analytics module (round 4, 2026-11-12)

The analytics module was reassigned from data-ops (see `data-ops.md`) to the data-content agent.
`TD_STORE_ANALYTICS` still defaults to `postgres`. Nothing was deployed. All tests here run on the
emulator only (`TD_TEST_NO_PG=1`, `TD_TEST_DB_NAME=analytics_test`).

## 1. Status (round 5)

**Every analytics endpoint and task now has a Firestore path.** An AST check finds no function in
`app/modules/analytics/` that runs SQL on the session without a Firestore dispatch, apart from the
backfill loader, which reads Postgres by design. `TD_STORE_ANALYTICS` still defaults to
`postgres`.

| Area | State on `TD_STORE_ANALYTICS=firestore` |
|---|---|
| Ingest, outbox consumer, interval builder, daily aggregation, mastery (round 4) | Done |
| **Weekly rollup** (`rollup_week`) | Done (`fs_jobs.rollup_week`): `sum`, `count FILTER (m5 >= 600)`, `bool_or(minor)`, `max(org::text)`, synthetic and unknown users excluded |
| **Cohort rollups** (`rollup_cohorts`, `_per_user`, `_upsert_cohort`) | Done. Batches and members come from `orgs.public`, synthetic flags from `identity.public`. The upsert finds a cell by its natural key, so backfilled cells keep their id. Percentiles and the k-floor are the shared Python. |
| **Video coverage** (`run_video_coverage`) | Done. Played ranges are read from batch documents and merged by the shared code. The `video.ended` duration fallback uses `asset_ids`. The upsert keeps `duration_s` and `lesson_id` coalesce. |
| **Security feed** (`run_security_feed`) | Done. Eligibility is shared; deletes and upserts by primary key. |
| **Retention purge / erasure** | Done. Batches past retention are dropped or trimmed (BE-24 server-time check), rollups are purged by date, and dirty days before the freeze. Erasure deletes the user's batches and every owned document. The batch TTL is the backstop. |
| **Reports** (`reports.py`: student metrics, learning-time series, streak, topic accuracy, batch / course / platform reports, ingest health) | Done (`fs_reports.py`). Each SQL statement has a twin returning tuples in the same column and row order, so the report code (k-cells, distributions, buckets, funnel) is shared. Enrolments and lesson progress come from `learning.public`. |
| **Exports** (`exports.py`, `export_store.py`) | Done. `export_jobs` runs on the shared SQL engine (`core/firestore/sqlstore.py`) through `analytics/datastore.py`, so the same statements run on Firestore. The `ApprovalRequest` join now uses `rbac.public.get_approvals` and `save_approval`. Approve/reject use `admin.approvals` as before. |
| **Evidence** (`video_coverage`, `lesson_time_evidence`, `watched_seconds_for_lesson`) | Done |
| **Feeds** | Done (data-ops' slice; engaged buckets read batches) |
| **Routes and tasks** | The analytics router uses core's `StorePrincipalDbSession`: the Postgres transaction when there is one, otherwise a `MemoryTx` committed at the end of the request. `run_job`, the export task and the sweep use `store_session()`. `hooks._default_org` uses `assessments.public.attempt_org_of_user`. |

## 2. Data model (Firestore, `lms_` prefix)

**`analytics_batches/{id}`** (new, owned by `user_id`, TTL `expire_at` = received + 90 days):

| Field | Content |
|---|---|
| `heartbeats` / `events` | The rows, each encoded exactly like a 1:1 backfill document (`HeartbeatRow` / `EventRow`). `played_ranges` (`int4range[]`) is stored as maps `{l, u, b, e}`, because Firestore has neither ranges nor nested arrays. |
| `event_ids` | Dedupe index. |
| `page_instance_ids`, `days` (IST), `session_ids`, `asset_ids`, `event_types` | Reader indexes. |
| `received_at` | Interval-builder watermark. |

Behaviour that replaces Postgres features:
- **Dedupe.** Postgres uses `ON CONFLICT (event_id, event_ts)`, and `event_ts` is derived from the uuid7 id. Here the user's batches are checked with `event_ids array-contains-any` (30 ids per query). A retried batch comes back all `duplicate`; this is tested.
- **Retention.** Heartbeats older than 35 days are dropped by the readers, as the Postgres purge does. The TTL removes the documents after 90 days.
- **Cost.** One write per client batch, not one per event; the test asserts `#docs = ceil(#events / 100)`. Every reader is bounded by user + page, user + IST days, user + sessions, or a receive watermark.
- **Backfill.** Postgres rows are grouped per user × IST receive day into batch documents (`store_specs.load_batches`).

**Other tables** keep data-ops' 1:1 documents (`store_specs`, primary key as id):
- `engagement_intervals`: mutable, rebuilt per page instance;
- `daily_learning_aggregates`, `topic_mastery`, `analytics_dirty_days`, `analytics_ingest_rejections`, `analytics_job_state`, `analytics_consumed_events`;
- the rollup collections (for the jobs still to port).

The 1:1 raw `analytics_events` / `activity_heartbeats` collections were removed. Their 1:1 index
was replaced in `firestore.indexes.fragment.json`, which also has the batch indexes, the TTL
override and large-field overrides.

## 3. How "identical to the SQL" is kept and proven

The jobs' SQL only **loads inputs and writes outputs**; the metrics are Python (`timemodel`). Each
SQL site therefore got an `if _fs()` branch that returns row objects with the **same attribute
names** as the SQL rows, with the same filters and ordering (Postgres NULL ordering reproduced
where it matters). The computation runs unchanged on both stores. The Postgres branches are the
original statements, extracted into `_page_rows_pg`, `_discover_pages_pg` and `_day_intervals_pg`
without edits.

Proof, in `tests/analytics/fs/test_pipeline_firestore.py`:
- **Example 1 (spec §3.13) golden values**, the same numbers `tests/analytics/test_pipeline.py` asserts on Postgres:
  - m2 = 2400 (union, not the per-tab sum), m3 = 1800, m5 = 2400, m1 = 2400, m4 = 0;
  - lesson, topic and course m2 = 1200 each;
  - 3/3 first-attempt-correct answers through the consumer;
  - topic mastery `insufficient_data` with 3 attempts.
- **Re-runs are idempotent**, and nothing stays dirty.
- **Counters computed from the fixture** (questions attempted, correct and first-attempt correct; code runs, submissions and accepted; lessons completed) equal the stored `_total`, topic and course rows.

## 4. Files

| File | Change |
|---|---|
| `app/modules/analytics/fs_raw.py` | **New.** Batch documents, readers, intervals, daily rows, dirty days, rejections, job state, consumed marks, core-outbox reader, mastery upsert, per-user deletes. |
| `app/modules/analytics/store_specs.py` | `batch_doc`, range codec, the batch collection, and the backfill loader replacing the raw 1:1 mappings. |
| `app/modules/analytics/service.py` | Ingest dispatch. `_attempt_ok` now uses `assessments.public.attempt_lifetime`. |
| `app/modules/analytics/jobs.py` | Job state, interval builder, day inputs (topic roots through `placement.public.topic_roots`), user-day writer, discovery. |
| `app/modules/analytics/consumer.py`, `mastery.py` | Dispatch. |
| `app/modules/analytics/feeds.py`, `repo_firestore.py` | Engaged buckets read from batches (the heartbeat reader was removed from the repository). |
| `app/modules/analytics/firestore.indexes.fragment.json` | See §2. |
| `tests/analytics/fs/test_pipeline_firestore.py` | **New.** |
| `tests/analytics/fs/test_analytics_data_path.py`, `test_analytics_reads_firestore.py` | Updated for the batch model. |
| `app/modules/media/adapters.py` | INV-12 now calls `security.public.set_unblock_attachment_scan` / `pending_unblock_attachment_keys`. |

## 5. Commands and real results

```
cd apps/api
export TD_TEST_NO_PG=1 TD_TEST_DB_NAME=analytics_test TD_TEST_FIRESTORE_AUTOSTART=0
.venv/Scripts/python.exe -m pytest tests/analytics tests/media tests/catalog/fs tests/paths/fs tests/entitlements/fs -q -p no:cacheprovider
#   -> 88 passed, 72 skipped (the skipped ones are the Postgres suites)
ruff check / ruff format --check (analytics, media, tests/analytics) -> clean
mypy app/modules/analytics app/modules/media -> no issues
```

Not run (policy): the Postgres analytics suites, and backfill → verify against a real database.

## 6. Round-4 plan (now done; kept for history)

1. **Rollup jobs:**
   - `rollup_week`;
   - cohort rollups (percentiles; `_per_user` reads daily rows);
   - `run_video_coverage`: `played_ranges` from batches by `asset_ids`, plus `video.ended` duration from events;
   - `run_security_feed`, using eligibility through `identity.public` / consent.

   Pattern: load the same rows from `fs_raw`, reuse the Python, and replace the upserts with transactions keyed by the primary-key document ids.
2. **`run_retention_purge` / `erase_user`.** Batch TTL already covers raw retention. For the rest: interval and rollup purges by date; erasure deletes the user's batches and all owned 1:1 documents (`fs_raw.delete_user_docs`).
3. **`reports.py`.** All 20 sites read rollups with GROUP BY. Port them as Python aggregation over the rollup documents of the window, then prove each report against fixture-computed expectations (H1–H12, k-anonymity cells).
4. **`exports.py` / `export_store.py`.** `export_jobs` is plain CRUD plus approvals (`rbac.public`) and the object store (unchanged). `evidence.py` and the rest of `feeds.py` are small reads of video coverage and daily rows.
5. HTTP tests for `/me/analytics/*`, `/analytics/*` and the export endpoints using the no-Postgres harness (`tests/paths/fs/http_harness.py`).

## 7. Requests to other agents

| # | To | Request |
|---|---|---|
| A1 | coordinator | Merge `app/modules/analytics/firestore.indexes.fragment.json`, which includes the `lms_analytics_batches.expire_at` TTL. |
| A2 | data-ops (security) | None needed. The INV-12 functions are in use. |
| A3 | platform | The relay path (`on_outbox_event`) depends on core's Firestore relay calling registered handlers with an `OutboxMessage` (`id`, `event_type`, `payload`, `occurred_at`, `organization_id`), as on Postgres. Please confirm. |


## 8. Round 5: tests and results

`tests/analytics/fs/test_reports_firestore.py` is new. It seeds fixture
`daily_learning_aggregates` rows (3 learners plus 1 synthetic, the current week, a course and a
topic). The test computes every expected value from those fixture rows using the SQL definitions,
and compares with the job output documents and the HTTP responses. Routes run on core's
`MemoryTx` (request sessions are `NO_POSTGRES`); other modules are stubbed at analytics' boundary.

- **Weekly rollup:** every `(user, kind, entity)` row equals the fixture's m2 / m5 sums and active-day count. Re-running is idempotent.
- **Cohort cells:** the platform cell has `learners_enrolled = 3` and is suppressed under the k-floor. Re-running does not duplicate cells (upsert by natural key).
- **HTTP `/me/analytics/learning-time` and `/summary`:** daily points, today / this-week sums, coding runs, lessons completed, and topic accuracy (answered, correct, ratio, learning seconds).
- **HTTP `/analytics/reports/platform`:** DAU, WAU, MAU and the 30-day total, computed with the fixture's DISTINCT / implausible / synthetic rules.
- **HTTP `/analytics/reports/courses/{id}`:** `learners_active` k-cell.
- **HTTP `/analytics/reports/batches/{id}`:** each learner's weekly m5.
- **HTTP `/analytics/ingest-health`:** works on Firestore.
- **Evidence:** coverage, watched seconds and lesson evidence.
- **Retention purge** runs on Firestore. **Erasure** removes every daily row and the coverage row of the user.
- **Exports over HTTP:** request (202), list, get, and another user gets 404.

```
cd apps/api
export TD_TEST_NO_PG=1 TD_TEST_DB_NAME=analytics_test TD_TEST_FIRESTORE_AUTOSTART=0
.venv/Scripts/python.exe -m pytest tests/analytics tests/media tests/catalog/fs tests/paths/fs tests/entitlements/fs -q -p no:cacheprovider
#   -> 93 passed, 72 skipped (the skipped ones are the Postgres suites)
ruff check / format: clean; mypy app/modules/analytics app/modules/media: no issues
```

Not covered over HTTP (service-level tests only):
- `POST /analytics/events` and `/events/beacon`, `GET /analytics/config`: ingest is covered through `ingest_batch` in `test_pipeline_firestore.py`;
- export download, approve and reject: approve and reject run in `admin.approvals`, which is data-ops' code;
- the `generate` and `sweep` task bodies.

Not run (policy): the Postgres suites, and backfill → verify against a real database.

### Round-5 requests

| # | To | Request |
|---|---|---|
| A1 | coordinator | Merge `app/modules/analytics/firestore.indexes.fragment.json` (batches TTL, batch, interval and daily indexes). |
| A3 | platform | (pending) Confirm the Firestore outbox relay passes `OutboxMessage` with the Postgres fields to registered handlers. |
| A4 | platform / data-money (owner of `sqlstore` and `backfill`) | `app.core.firestore.backfill.canonical()` has no `bytes` case. Verify hashing of an engine-mapped table with a binary value raises `TypeError` (seen with the shared `sample_row` helper on `export_jobs`). Suggest hex-encoding bytes in `canonical()`. |
| A5 | data-ops (admin) | `admin.approvals.decide` (used by export approve/reject) must run on a session-less stack. Analytics calls it unchanged. |

### Known differences

- **`export_jobs` RLS.** The engine family is "requester or platform"; the Postgres policy also lets the requester's organization read. Exports are read by the requester or a platform approver.
- **Approval expiry in the export sweep.** It now writes through `rbac.public.save_approval`, which on Firestore refuses to change an already-decided request (the Postgres path only ever changes pending ones, so the result is the same).
- **Report search order.** Ties within a `GROUP BY` result follow Python ordering where the SQL had no `ORDER BY`. The report code keys every result by id, so the output is unchanged.

## 9. Round 6: HTTP gaps closed

`tests/analytics/fs/test_http_ingest_exports.py` is new. It runs through the real FastAPI app with
request sessions set to `NO_POSTGRES` (routes run on core's `MemoryTx`). analytics, rbac, core
(idempotency) and audit are all on Firestore.

**Ingest and config**
- `POST /analytics/events`: a batch is accepted (`accepted = #events`). Retrying the identical batch gives `accepted 0, duplicate = #events`. Each batch is one `analytics_batches` document.
- `POST /analytics/events/beacon`: `sec-fetch-site: cross-site` gives 403 `csrf_failed`; same-origin gives 204 and stores a second batch document.
- `GET /analytics/config`: equals `config_payload(False, "adult")` (an adult with no product consent; identity `consents_of` stubbed).

**Exports, bulk-PII flow**
1. `POST /exports` creates an `awaiting_approval` job and an `admin.approvals` request (rbac on Firestore). The approval's audit is written to the Firestore audit store.
2. Download before ready gives 409.
3. `POST /exports/{id}/approve`, with an idempotency key on core Firestore, succeeds.
4. The **generate task body** (`tasks.run_export`) runs on the no-Postgres stack, and the job becomes `ready`.
5. Download returns JSON with a URL (fake export store), and a 302 redirect without `Accept: application/json`.
6. A second job is rejected through `POST /exports/{id}/reject` and becomes `rejected`.
7. The **sweep task body** (`tasks.run_exports_sweep`) runs and returns its counters.

**A5 answer:** `admin.approvals.decide` **works without Postgres**, for both approve and reject, when rbac, audit and core are on Firestore. Nothing failed on a Postgres access. Two things to know:
1. `admin.approvals.can_approve` calls `rbac.service.check_permission`, which resolves the approver's **stored** role grants and role permissions. This emulator test does not seed rbac, so that one call is stubbed to the test's grants. It is authorization data, not a no-Postgres failure. Without seeded grants the response is a correct 403 `permission_denied` (`report.export.approve`).
2. `rbac.service.create_approval_request` calls core `audit()` directly, so `TD_STORE_AUDIT` must be `firestore` on a no-Postgres stack. With audit on Postgres it raises `PostgresDisabledError` (`INSERT INTO audit_outbox`), which was observed before audit was switched to Firestore in the test.

**Results:** `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=analytics_test pytest tests/analytics tests/media tests/{catalog,paths,entitlements}/fs` gives **95 passed, 72 skipped** (the skipped ones need Postgres). ruff and format are clean.
