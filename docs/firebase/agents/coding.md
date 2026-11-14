# coding agent report: rest of `app/modules/coding` on Firestore

Agent: CODING, 2026-11-12. Follows `data-assess.md` (round 2 built the data model, blobs,
`rls.py`, `public.py` and the service functions other modules call).

`TD_STORE_CODING` stays at its default, **`postgres`**. Nothing was deployed or flipped. Rules,
secrets, the judge provider and test-case encryption are unchanged. Every Postgres statement is
still there, now inside the `else` branch of a `uses_firestore("coding")` check.

## 1. What is routed now

| Area | Firestore path (`repo_firestore.CodingRepo`) | Replaces |
|---|---|---|
| Languages | `enabled_languages`, `language_or_422`, `_check_languages_exist` read `judge_languages` | SELECTs |
| Student catalogue | `GET /coding/problems` (published problems, `id > cursor`, my submit verdicts), `GET /coding/problems/{slug|id}`, sample cases | SELECTs |
| Submit path | `precheck_practice`: `_lock_user` uses `request_locks.acquire("coding_submit:{user}")`; `_recent_count`, `_inflight_count` and `_global_pending` use queries and counts; `create_submission` stores the submission and the `code_submissions_idem` key in one transaction (an existing key gives 409 `conflict`, the same as the UNIQUE violation); `queue_position` uses a count; the replay check `_idem_exists` reads the core idempotency record when `TD_STORE_CORE=firestore` | `pg_advisory_xact_lock`, counts, INSERT, `UNIQUE (user_id, idempotency_key)` |
| Views | `GET /coding/submissions/{id}` (`submission_view`: results + sample-case join), staff read, `_batch_reader` through `orgs.public.batch_members`/`get_batch`; `GET /me/coding/submissions` (id-desc keyset, done in memory) | `session.get`, joins |
| Judge worker | `claim` (guarded `queued→running`); `load_work`; `record` writes the results, the submission update and the `submission.judged` outbox event (`emit_event_tx`) in **one** transaction; `_release`; `pending_ids` (re-queues stale running rows, then sorts by priority and then `queued_at`); `judge_by_id` and `process_pending` run without sessions. The judge (fake/demo) is unchanged | UPDATE…RETURNING, `FOR UPDATE SKIP LOCKED` (the guarded claim makes double processing impossible) |
| Authoring | `create_problem` (`coding_problems_by_slug` key in the same transaction), `patch_problem`, `add_test_case`, version bump, `publish_problem`: `save_problem` writes the changed fields and the new or copied cases atomically and checks the stored `version_no` and the case ordinals inside the transaction (409 `conflict`, like `UNIQUE (problem, version, ordinal)`); `list_cases`; studio list and search (ILIKE becomes a case-insensitive substring match), published picker, case counts; `rotate_wrapped_keys` | INSERT/UPDATE + flush |
| Reference solutions / validation | upsert on `{problem:lang}`; `latest_validation` (`created_at desc, id desc`); 10/h count; validation insert. Hidden cases are still decrypted only in memory | `ON CONFLICT DO UPDATE` |
| Drafts | `save_draft`: create, or update with the 20/min window, in one transaction; `get_draft` reads by document id | `ON CONFLICT DO NOTHING` + `FOR UPDATE` |
| Hidden content (COD-17) | tokens `{hex(sha256)}` written together; 30/h count of distinct requests; `redeem_token` is single use in one transaction | UPDATE…RETURNING |
| Privacy | `erase_user`: same effect and counts (drafts deleted; source, input, compiler output and hash cleared; stdout cleared); idempotent | DELETE/UPDATE |

Encryption is unchanged: blobs still go through `blobstore` (chunked) and `crypto`.
`fill_defaults` applies the column defaults an INSERT would set (for example `retry_count=0`,
`similarity_flag=false`, `queued_at=now()`), so the stored documents match the rows.

## 2. Tests (emulator only, no Postgres)

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=coding_test .venv/Scripts/python.exe -m pytest tests/coding -q
  -> 36 passed, 39 skipped (the Postgres suites) in 43 s
```

New files:
- `tests/coding/fs/test_coding_http_firestore.py`: HTTP through the FastAPI app, with the request
  session set to `NO_POSTGRES`.
  - Authoring: author → cases → publish refused until validated → reference solution → validate
    → SoD 403 → publish.
  - Student flow: languages, problem list and detail, drafts (including the 404 for another
    user), run, submit with an idempotent replay and the in-flight 409.
  - Judging and results: `worker.process_pending` (priority order) → submission view (hidden
    cases show the verdict only) → history paging → outbox events → staff view.
  - Versioning: version bump with copied cases, and a stale validation.
  - COD-17: token bound to its user, single use, and two concurrent redeems give exactly one 200.
  - Erasure: the expected counts, and a repeat run changes nothing.
  - Concurrency: 3 concurrent submits give exactly one 202 (request lock).
- `tests/coding/fs/test_coding_concurrency_firestore.py` covers these races:
  - same slug: one wins;
  - concurrent case adds: never a duplicate ordinal;
  - concurrent version bumps: one wins;
  - draft window: no lost increments, and the 21st save is refused and writes nothing;
  - reference upserts: one document;
  - 4 concurrent claims: 1 wins;
  - duplicate result ordinals: refused;
  - idempotency key: repeat or 409;
  - stale running rows: re-queued;
  - release paths.
- `tests/coding/fs/support.py`: seeds the 4 migration languages.

`ruff check`, `ruff format --check` and `mypy app/modules/coding` are clean. `create_app()` builds.

## 3. Behaviour notes (Firestore path)

- Under heavy concurrency on one document (more than ~10 simultaneous writes to the same draft),
  the store answers `409 conflict` with `Retry-After: 1` (`TransactionContentionError`). Postgres
  would queue those writes on the row lock instead.
- If a hidden case's blob is written and the case write then fails, the blob is left behind
  without a case. It is never readable without a case row. On Postgres the request transaction
  rolls it back.
- `pending_ids` has no SKIP LOCKED. Two pollers may list the same id, but only one wins the
  claim.
- History, studio search and the catalogue are filtered and sorted in memory, so the results are
  the same but the cost grows with the data.

## 4. Round 2 (2026-11-12): the SQL engine's `MemoryTx` and attempts with coding questions

**The crash.** Assessments now runs on the shared SQL engine (`core/firestore/sqlstore.py`). Its
in-memory request session (`MemoryTx`) answers the `current_setting(...)` query with 3 values
and has no `app.caller_is_org_staff()`. `coding.repo_firestore.visibility()` expected 4 values,
so attempts with coding questions failed.

**Fixes (coding files only):**

- `coding/rls.py` is now a byte-for-byte copy of `placement/rls.py`. It adds
  `memory_gucs(session)` and `no_postgres(session)`.
- `visibility()` now handles all four session kinds:
  - `None`: system view;
  - falsy `NO_POSTGRES`: the request principal;
  - `MemoryTx`: its in-memory GUCs, with org-staff taken from the principal (same as placement);
  - Postgres: the 4-column query, unchanged.
- `coding/router.py`'s session dependency is now `sqlstore.StorePrincipalDbSession`, the same as
  assessments and analytics.
  - With Postgres it passes the request session through unchanged.
  - Without Postgres it yields a `MemoryTx` carrying the principal's RLS context.
  - This was needed because the coding route hands its session to the assessments attempt
    validator (`validate_coding_attempt`), which uses the SQL engine. With `NO_POSTGRES` that
    call failed with `PostgresDisabledError`.
- All coding Firestore paths work with either session.

**New tests:**

- `tests/coding/fs/test_coding_attempt_http_firestore.py` runs over HTTP with no Postgres:
  1. Author the coding problem and validate it.
  2. Create a `coding` question and publish a test.
  3. The learner, with no coding entitlement, starts an attempt and opens and drafts the problem
     through `attempt_id`.
  4. The learner submits; the submission goes to the `judge_assessment` queue.
  5. Another user who tries the same attempt id is refused.
  6. The worker runs the fake judge and returns PARTIAL (2 of 3 cases).
  7. The learner pins the submission by autosave and submits the attempt.
  8. The result shows **6 of 9** marks.
- `test_coding_rls_firestore.py`:
  - `visibility()` on `MemoryTx` (tenant and system context), on `NO_POSTGRES` and on `None`;
  - a check that the two `rls.py` copies are identical.

**Results:**

```
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=coding_test pytest tests/coding -q        -> 40 passed, 39 skipped
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=coding_test pytest tests/assessments/fs -q -> 8 passed
```

`ruff check`, `ruff format --check` and `mypy app/modules/coding` are clean.

## 5. Round 3 (2026-11-12): submission reads for assessments go through `coding.public`

**New in `coding.public`.** All four work on both stores and apply the caller's RLS: the Postgres
policies, or on Firestore `visibility(session)` (`None` = the system view).

| Function | What it does |
|---|---|
| `get_submission(session, id)` | Postgres: `session.get(CodeSubmission, id)` |
| `attempt_submissions(session, *, attempt_id, user_id, problem_id, mode="submit")` | Every status, oldest first |
| `submission_view` | Re-export from `service` |
| `attempt_code_signals(session, attempt_ids)` | The `cs` CTE of `assessments.integrity.FLAGS_SQL`. Per attempt: the most `submit` submissions on one problem within one clock hour of `queued_at`, and the number of similarity-flagged submissions. Attempts without submissions are left out (the caller treats them as 0). Postgres: `date_trunc('hour')` with GROUP BY. Firestore: `attempt_id in` (chunks of 30), grouped in memory |

**Assessments edits.** The assessments owner is idle, so the coordinator allowed me to edit these
two files, involved lines only. Both files keep their CRLF line endings.

- `assessments/coding.py`:
  - `check_pinned_submission` and `_on_submission_judged` now use `coding_public.get_submission`
    instead of `adb.get(..., CodeSubmission, ...)`.
  - `_scored_submission` now uses `attempt_submissions`. The pinned submission wins; otherwise
    the newest completed one wins (`completed_at DESC, id DESC`). This is one code path in place
    of the earlier Firestore/Postgres pair, with the same selection.
  - `coding_review` now imports `submission_view` from `coding.public`.
  - The now-unused `select` import is removed.
- `assessments/integrity.py`: `_code_signals` now calls `attempt_code_signals`, and the unused
  `cast` import is removed.

**Behaviour change on the Firestore path.** These reads now use the caller's visibility, which is
what Postgres RLS does. Before, they used the system view.
- `assessments/datastore._foreign_get`'s `code_submissions` branch (system view) is no longer
  used by these two files. It stays in place.
- The whole assessments suite passes with this change, but the assessments owner should confirm
  it when they return.

**Before/after scan** (diff ignoring CR: 48 lines in `coding.py`, 25 in `integrity.py`):

| File | `CodeSubmission` | `repo_firestore` / `coding_repo` | `coding.public` |
|---|---|---|---|
| `coding.py` | 13 → 0 | 2 → 0 | 0 → 7 |
| `integrity.py` | 0 → 0 | 2 → 0 | 0 → 3 |

- `coding.py`: its `coding.service` references go 4 → 3. The remaining three are
  docstring/comment mentions of `register_attempt_validator`.
- `integrity.py`: `code_submissions` stays only in `FLAGS_SQL` (the Postgres path) and the module
  docstring.

**New test.** `tests/coding/fs/test_coding_public_firestore.py` checks, on Firestore:
- the hour buckets: 3 submits in one hour plus 1 in the next give a burst of 3;
- runs and practice submissions are excluded;
- similarity flags are summed;
- attempts with no submissions are absent;
- `attempt_submissions` filters and orders correctly;
- `get_submission` returns `None` for a missing id.

**Results:**

```
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=coding_test pytest tests/coding tests/assessments/fs -q -> 48 passed, 39 skipped
```

ruff, format and mypy are clean on `app/modules/coding` and the two assessments files.

## 6. Requests

1. **platform (TTL):** the TTL policy on `lms_coding_testcase_content_tokens.expires_at` (the
   5-minute link expiry) can delete tokens before the 30/h counter window ends and well before
   the 30-day retention. My token documents now also carry `expire_at` = created + 30 days.
   Please move the TTL to `expire_at`.
2. **platform:** the `idempotent_firestore` `begin_nested` fix. The router still uses `_nopg`.
3. **coordinator / wiring (blocking for the flip):** `app/wiring.coding_problem_parents` still
   runs `session.execute` and fails with no Postgres when the real entitlements checker is used.
   It should use `coding.public.problem_primary_topic` + `placement.public.topic_with_root`.
   My HTTP tests use the coding `access` checker stub for this reason.
4. **coordinator:** merge the 12 new composite indexes from
   `app/modules/coding/firestore.indexes.fragment.json`.
5. **Deployment note (judge on Firebase):** with no VM poller, judging needs a trigger. The
   options are `TD_CODING_SEND_TASKS=1` (Cloud Tasks wake-up → `coding.judge_submission` →
   `judge_by_id`), or a scheduled `coding.process_pending`. Both run on Firestore now. The owner
   still has to decide on the real judge.
6. **placement (blocking for coding questions without Postgres):**
   `placement/bank.submit_review` reads the linked problem with
   `session.get(CodingProblem, ...)` and fails without Postgres. It should use
   `coding.public.get_problem`. The attempt test stands in for this change with a test-local
   copy of `submit_review` that differs only in that read (fixture
   `placement_reads_coding_public`).
7. `studio_published_problems` imports `placement.policies.can_in_org` directly; this is
   pre-existing code. It should use a placement `public` function.
