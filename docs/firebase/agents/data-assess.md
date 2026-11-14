# data-assess agent report: placement, assessments, coding

Agent: DATA-ASSESS. Round 1: 2026-11-12. Round 2: 2026-11-12, under the owner's test policy (Firebase emulator only, no Postgres, `TD_TEST_NO_PG=1`). Scope: the Postgres → Firestore move of `placement`, `assessments` and `coding`, behind `TD_STORE_<MODULE>=firestore`.

All three switches stay at their default, **`postgres`**. Nothing was deployed or flipped. Rules, secrets and the judge are unchanged; the judge stays the fake/demo provider.

## 1. Status (end of round 3)

| Module | Done | Not done | Safe to flip? |
|---|---|---|---|
| **placement** | **All files routed.** `bank.py` (round 1), `practice.py`, `banks.py`, `bulk_import.py`, `reports.py`, `mentoring.py` (topic names, plus orgs and identity reads through their `public` APIs when there is no Postgres), `qbank_router.py` (media), `privacy.py`, `tasks.py` (media scan sweep) and `policies.batch_org`. `router.py` had no inline SQL; its handlers go through the routed functions. **`public.py`**: store-neutral reads for other modules. **HTTP tests through the FastAPI app** pass with no Postgres. | Other modules still need to switch to `placement.public` (§6). Assessments and coding are not routed yet, and placement reads them (practice hold-back, coding questions). | **Not until assessments and coding are routed.** The owner flips everything together. Placement is ready on its own side. |
| **assessments** | **Round 3: the whole module is routed.** Every file (`attempts`, `studio`, `evaluation`, `exam`, `integrity`, `report`, `router`, `coding`, `tasks`, `privacy`) runs its SQLAlchemy code through `assessments/datastore.py` on the shared SQL-on-Firestore engine (`core/firestore/sqlstore.py`, `store_specs.SPEC`/`STORE`). Each request is one unit of work committed in **one Firestore transaction**, so start, autosave, submit, scoring and grading stay atomic. Other modules' data is read through their `public` APIs (§1.2). **HTTP tests through the FastAPI app** with no Postgres cover author → publish → override → attempt (idempotent start, one open attempt) → autosave → submit → manual grade → result, assignments with the attempt limit, manual release, review, integrity flags, decisions and invalidation, reports, evaluation, the studio list/get/patch/validate/archive, sequential sections, resume, rebind override, the deadline sweeper and erasure. | AI grading (`/evaluation/ai-grade`) and rebind OTP have no tests; they depend on the ai and identity modules. Coding-question attempts depend on the coding module (another agent): coding's `visibility()` fails on a `MemoryTx` (§6). | **Yes, for the assessments side, once the other modules it reads are on Firestore** (the owner flips everything together). Parity against the VM is still to be checked. |
| **coding** | Round 2 work (data model, chunked blobs, `public.py`, `repo_firestore.py`, routed service functions). **Reassigned to a new agent in round 3; not touched since.** | See that agent's report. | — |

### 1.2 Assessments routing (round 3)

- **Engine:** `store_specs.py` holds the module's `SqlModuleSpec`:
  - tables and RLS families: TN tables are `read_all`; U/US tables are `owner` (own rows or platform). The org-staff branch of US is not emulated (single company);
  - the uniques `UNIQUE (test_id, position)`, `(test_section_id, position)`, `(test_id, user_id, attempt_no)`, `(user_id, idempotency_key)`, the partial `ux_att_one_open` and `(attempt_id, question_version_id)`;
  - append-only `attempt_events` and `attempt_integrity_decisions`, and the `updated_at` triggers.
  - `attempt_events` uses `id` as its document id: the engine would otherwise compose its `(id, occurred_at)` primary key with a datetime, which fails. The backfill mappings are registered with the same id.
  - Round 2's hand-written `assessments/repo_firestore.py` and its heads/idempotency documents were **removed**: the engine's unique reservations replace them.
- **Requests:** the routes use `StorePrincipalDbSession`. That is the Postgres session on the VM (unchanged) and a `MemoryTx` without Postgres, committed at the end of a successful request.
- **Mechanical rewrite:** every `session.execute/add/get/flush/delete` in the module goes through `assessments/datastore.py`. With `TD_STORE_ASSESSMENTS=postgres` each call goes straight to the session, so the Postgres behaviour is unchanged.
- **Reads of other modules' tables** (Firestore only; the Postgres SQL stays in the `else` branch):
  - `datastore.get` sends placement, sessions, identity and coding models to those modules' public functions or repositories;
  - `xmod.py`: batch membership and device verification (orgs and sessions public), session hold, the start lock (`core.request_locks` replaces `pg_advisory_xact_lock`), and version settings via `placement.bank`;
  - studio: coding question and pool lookups via `placement.public`, membership via `orgs.public`;
  - evaluation and integrity: names via `identity.public.get_profiles`.
- **Rewritten Postgres-only SQL:**
  - the autosave `INSERT … ON CONFLICT DO UPDATE WHERE client_seq <` (same outcome on the unit of work);
  - the integrity `FLAGS_SQL` (CTEs, `FILTER`, `DISTINCT ON`, `date_trunc`): the same signals, decisions, filters and keyset order computed in Python; code-submission signals come from the coding repository;
  - the sweeper's `make_interval`;
  - the erasure `UPDATE`s.
- **System-context writes:** `lock_settings` updates a test inside `system_context`. The engine checks a write against the scope the row was *read* with, so `datastore.written_as_system` records the platform scope. Without that, the student's start was refused with 403.
- **`public.py`** now runs the original statements through the engine. With no usable session (`NO_POSTGRES`, another module's session object) it uses a private read-only `MemoryTx` with the caller's RLS scope. `fixed_versions_in_live_tests` (the placement practice hold-back) never opens Postgres; this fixes the coordinator's report about 3 failing placement tests.
- **placement:** `rls.no_postgres()` and `memory_gucs()` treat the engine's `MemoryTx` like `NO_POSTGRES`, and `visibility()` reads its in-memory GUCs. New `placement.public` lookups: `get_company`, `get_company_path`, `get_topic`, `coding_question_for_problem`, `coding_pool`.

### Running without Postgres (round 2 additions)

- **RLS context without Postgres:** `placement/rls.py` (coding has an identical copy, `coding/rls.py`).
  - `bind_principal`, an async router dependency added to every authenticated router of the three modules, records the request principal in a context variable.
  - `system_scope(session, job)` is `db.system_context` on Postgres. Without Postgres it marks the block as platform scope.
  - `visibility()` in the repositories reads the transaction GUCs when there is a Postgres session. Otherwise it uses that principal: user, org ids and `is_platform`. `org_staff` mirrors `app.caller_is_org_staff()`: a non-student organization or batch grant, or an active staff membership read through `orgs.public`.
- **Idempotency:** core `idempotent()` opens a Postgres savepoint whenever `session is not None`. `db.NO_POSTGRES` is not `None`, so routes now pass `_nopg(session)`, which is `None` without Postgres. This is a request to platform (§6).
- **Outbox:** the practice `practice.answered` event is written with `core_store.emit_event_tx` inside the answer's transaction. One answer gives one event, atomically.
- **Identity map:** Postgres returns the same ORM row on every `get`, but Firestore objects are transient. `router._transition` therefore re-reads the question after a workflow step, so its response shows the new status, the same as on Postgres.

## 2. Data model

Documents map one to one onto rows, and UUIDs stay document ids. Physical names are `lms_<table>`.

**Value mapping** (`placement/fsmap.py`, with `coding/fsmap.py` an identical copy):
- `numeric(p,s)` → a decimal string with the column's scale.
- `bytea` → base64.
- `uuid`, `uuid[]` and `inet` → strings.
- JSONB and timestamps are copied verbatim.

The repositories turn documents back into **transient ORM instances**, so every serializer (`topic_out`, `version_out`, `Bundle`, `delivery`, ...) is shared and the responses are identical.

### placement

| Collection (id) | Replaces |
|---|---|
| `topics/{id}`, `topics_by_path/{path_key}` | `topics.path` UNIQUE, `UNIQUE(parent_id, slug)`, `ux_topics_root_slug`. A subtree move rewrites the descendants' paths and their keys in one transaction |
| `companies/{id}`, `companies_by_slug/{slug}` | `companies.slug` UNIQUE |
| `company_paths/{id}`, `company_path_steps/{id}` | One transaction replaces the steps. `version_no` is max+1 for the company and role, read inside the transaction |
| `questions/{id}` | TN visibility filter in the repository |
| `question_versions/{id}` with **embedded `options`** | Triggers `placement_qv_immutable` and `placement_qo_immutable`: `assert_version_change` refuses frozen-field changes and published→draft. Options live in the version document, so they share the guard. Publish retires the old version, publishes the new one and sets the question pointer in one transaction |
| `question_tags/{qid:type:ref}` | `ux_qt` |
| `question_bank_items/{bank:question}`, `practice_responses/{session:qv}` | The UNIQUE pairs. A practice answer creates the response and bumps the counters atomically; a concurrent duplicate gets the stored response back |
| `question_reports_open/{user:question}`, `recommendations_active/{user:rule:type:target}` | The partial uniques `ux_qr_open_per_user` and `ux_rec_dedupe` (backfilled only for open and active rows) |
| `question_media`, `question_reports`, `question_banks`, `practice_sessions`, `recommendations` | One document per row. Learner rows are `owned` (`user_id`) |

### assessments

- **Org-scoped (TN):** `tests`, `test_sections`, `test_section_rules`, `test_assignments`.
- **Learner-owned (US):** `test_attempts`, `attempt_overrides`, `attempt_sections/{attempt:section}`, `attempt_responses/{attempt:qv}`, `attempt_results/{attempt}` and `attempt_item_grades/{attempt:qv}`.
- **Append-only:** `attempt_integrity_decisions`, and `attempt_events/{id}` with a TTL `expire_at` that replaces the partition drop.
- **`test_attempt_heads/{test:user}` = `{last_attempt_no, open_attempt_id}`.** It replaces three things:
  - `ux_att_one_open`;
  - `UNIQUE(test_id, user_id, attempt_no)`;
  - `pg_advisory_xact_lock(test:user)`.

  Attempt start, and later submit or finalize, must read and write it in the same transaction as the attempt rows.
- **`test_attempts_idem/{user:key}`** replaces the idempotency UNIQUE.

### coding

- Slug uniqueness: `coding_problems_by_slug/{org|platform:slug}`.
- Natural-key ids:
  - `coding_reference_solutions/{problem:lang}`;
  - `submission_results/{submission:ordinal}`;
  - `coding_drafts/{user:problem:lang}`;
  - `coding_testcase_content_tokens/{hex(token_hash)}`.
- Idempotency: `code_submissions_idem/{user:key}`.
- Encryption: `coding_test_case_blobs.ciphertext` and `wrapped_data_key` keep the same AES-GCM bytes, and `coding.crypto` still decrypts them (tested end to end).
- **Large blobs (round 2):** a Firestore document is at most 1 MiB, so ciphertext over 750 KB is split: the blob document keeps the metadata with `chunks = n` and an empty `ciphertext`, and `coding_test_case_blob_chunks/{blob_id:n}` hold the pieces. The repository writes them in one transaction and the backfill writes the same layout (a loader expands large rows). One commit is at most 10 MiB, so a blob is capped at 12 pieces (about 9 MB); anything larger is refused and would need Cloud Storage. The current data needs no Cloud Storage.
- The in-flight submit lock becomes a request lock (`core.request_locks`, `coding_submit:{user}`); not wired yet (the submit path is not routed).

**Indexes:** `app/modules/{placement,assessments,coding}/firestore.indexes.fragment.json` hold composite indexes plus index exemptions for large fields. **The coordinator merges them** into the root `firestore.indexes.json`. The placement indexes match the queries the repository runs; the assessments and coding ones are a first cut for the future repositories.


## 3. Files (rounds 1 and 2)

| File | |
|---|---|
| `placement/fsmap.py`, `coding/fsmap.py` | Row ↔ document mapper (copies; platform's `core/firestore/rows.py` now holds a shared version) |
| `placement/store_specs.py`, `assessments/store_specs.py`, `coding/store_specs.py` | Collections, key documents, backfill mappings (coding: blob chunks with a loader) |
| `placement/repo_firestore.py` | `PlacementRepo`. Round 2 added practice (`mark_served`, `complete_session`, `sessions_of`, `record_answer` with an in-transaction hook), recommendations (`ux_rec_dedupe` via `recommendations_active`), reports (`question_reports_open`), banks and items, media, erasure, bulk import (`create_questions_in_bank`), `company_by_slug`, `get_topics` and `path_ids_with_test` |
| `assessments/repo_firestore.py` | **new** `AssessmentsRepo` (reads and the atomic attempt flows) |
| `coding/repo_firestore.py` | `CodingBlobRepo` (chunking) and **new** `CodingRepo` |
| `placement/public.py`, `assessments/public.py`, `coding/public.py` | **new**. Store-neutral API for other modules |
| `placement/rls.py`, `coding/rls.py` | **new**. RLS context without Postgres |
| `placement/{bank,practice,banks,bulk_import,reports,mentoring,qbank_router,privacy,tasks,policies,router}.py` | Routed. The Postgres statements are unchanged inside `else` branches |
| `coding/service.py`, `coding/blobstore.py`, `coding/router.py`, `assessments/router.py` | Partly routed (above), plus `bind_principal` and `_nopg` |
| `*/firestore.indexes.fragment.json` | Composite indexes for every query the repositories run (round 2 added steps by test, media by scan status, bank items by bank, owned practice / recommendation / report / attempt / result / submission listings). The coordinator merges them |
| `tests/placement/fs/*`, `tests/assessments/fs/*`, `tests/coding/fs/*` | Emulator-only tests (below) |

## 4. Tests (emulator only, `TD_TEST_NO_PG=1`; Postgres was not used, as the owner decided)

**Round 3:**

```
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=assess_test .venv/Scripts/python -m pytest tests/placement/fs tests/assessments/fs -q
  -> 26 passed in 222 s (placement 19 incl. 3 HTTP + the practice tests; assessments 7 incl. 4 HTTP)
```

`tests/assessments/fs/test_assessments_http_firestore.py` has 4 HTTP tests, listed in §1. The round-2 assessments repository tests were removed with that repository. mypy and ruff report 0 errors in `app/modules/{assessments,placement}`. `tests/coding/fs` belongs to the new coding agent and was not run.

Round 2 (kept for reference):

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=assess_test .venv/Scripts/python -m pytest tests/placement/fs tests/assessments/fs tests/coding/fs -q
  -> 60 passed in 204 s (emulator 127.0.0.1:18080, no Postgres)
```

What the tests cover:
- **HTTP through the FastAPI app** (`test_placement_http_firestore.py`, 3 tests). The request session is `NO_POSTGRES`, and core, audit, identity, rbac, notifications, orgs, entitlements and the other modules run on Firestore. The flows:
  - studio topics, including a duplicate returning 409;
  - the question workflow with the SoD 403, search, a new version, retire, and the public subject tree;
  - companies and company paths;
  - a practice start, then an answer with an idempotent replay;
  - another learner gets 404 on someone else's practice set;
  - state, complete, mastery and recommendations;
  - learner reports: create, duplicate 409, queue and resolve;
  - question banks: create, add, list and list questions.
- **placement at service level:**
  - practice flows: concurrent duplicate answers give one response and one outbox event; reveal; complete; review; mastery;
  - weak-topic recommendations, including dedupe, dismiss, and no re-creation after dismissal;
  - company-step practice and readiness;
  - banks: lifecycle, stats, search and purge rules;
  - bulk import: all or nothing;
  - reports: one open per learner, the queue and resolve;
  - erasure and the media sweep;
  - round 1: taxonomy, workflow, immutability, pool and search, TN visibility, backfill → verify.
- **`public.py` of all three modules** on Firestore, with data seeded through the real backfill.
- **assessments atomicity:**
  - 5 concurrent starts give 1 attempt;
  - attempt numbers, the attempt limit and the idempotency key;
  - 3 concurrent submits give exactly 1 success; responses, result and head are written together, and autosave is refused afterwards;
  - a failing submit writes nothing.
- **coding:**
  - a 2 MB sealed case through `blobstore`, split into chunks and decrypted with the same key;
  - a backfill of a large row verifies clean;
  - the chunk cap;
  - submission idempotency under 4 concurrent creates;
  - the conditional update;
  - mapper round trips.

`ruff check` and `ruff format --check` are clean on my modules and tests. `mypy app/modules/{placement,assessments,coding}` reports 0 errors in these modules; the 12 remaining errors are in other agents' files. `create_app()` builds.

**Not run:** the Postgres suites, by owner decision; parity is checked later against the live VM. The placement HTTP tests are slow (about 60 s each on the emulator).

**Note:** during round 2 I once ran `ruff check --fix` on all of `app/modules` by mistake instead of only my three modules. Ruff only applies its safe fixes (import order, unused imports). `create_app()` still builds and every router imports. Other agents may see small import-only changes in their files.

## 5. Gaps and known differences (read before the flip)

1. **assessments:** the module's own code is not routed yet. The plan is to route `attempts.start/autosave/finalize/submit/score_attempt` onto `start_attempt`, `save_response` and `submit_attempt`, then studio and evaluation (manual grades, release, overrides, integrity decisions), then reports and tasks. These need HTTP tests like placement's.
2. **coding:** still to route: the submission path (`precheck_practice`, `create_submission` with the `coding_submit:{user}` request lock), history and view, the judge worker writes, authoring, and erasure.
3. **Firestore-path behaviour notes:**
   - Searches, pools, bank lists and the report queue filter in memory: same results, cost grows with the corpus.
   - ILIKE becomes a case-insensitive substring match.
   - A TN WITH CHECK violation returns 403 (Postgres gave 500).
   - Recommendations are written in chunks of 100 per transaction.
   - The media sweep needs no SKIP LOCKED: it runs as a single job.
   - Bulk import validates and builds every item first, then writes them in transactions of at most 350 writes (all or nothing for validation errors).
4. **Practice hold-back** (`_in_graded_tests`): on Firestore it uses `assessments.public.fixed_versions_in_live_tests`. That needs the assessments data on Firestore, so placement and assessments flip together.
5. **Cross-module readers** still query my tables directly (§6). They must switch to the `public.py` functions before the flip.

## 6. Requests to other agents and the coordinator

**Round 3 additions:**
- **coding agent:** `coding.repo_firestore.visibility()` unpacks 4 values from the GUC query. On the engine's `MemoryTx` it gets 3 (`app.caller_is_org_staff()` is not emulated), so any coding call made with an assessments request session fails. Read `session.guc` the way `placement.repo_firestore.visibility` does, or use `placement.rls.memory_gucs`. Until then, assessments reads coding through `repo(None)` (system view; callers check ownership). Coding-question attempts (`judge_for_attempt`, `submission_view`) need that fix.
- **platform:**
  - `sqlstore.model_doc_id` cannot compose a datetime primary-key part (`attempt_events`). Assessments overrides it in its spec.
  - `wiring.test_parents` (the entitlement resolver for tests) still runs Postgres SQL on `company_path_steps`: switch to `placement.public.company_paths_with_test`. The HTTP tests register the allow-all access checker after app creation because of this.
  - The outbox handler `assessments.coding.on_submission_judged` receives the relay's session. Under no Postgres it should be a `MemoryTx` (`store_session`).
- **data-money (notifications):** `assert_owner_or_platform` (unchanged request).


- **platform:**
  1. `core/firestore/core_store.idempotent_firestore` calls `session.begin_nested()` when `session is not None`. On the Firebase stack the session is `NO_POSTGRES`, so it should test `if session` (falsy). My routes work around it with `_nopg(session)`.
  2. A core "current principal" context (set by `require_active_principal`) would let every repository evaluate RLS without Postgres. Mine use `placement/rls.py` for now.
  3. Merge the index fragments (with the additions in §3).
  4. TTL policies on `lms_attempt_events.expire_at` and `lms_coding_testcase_content_tokens.expires_at`.
- **data-money (notifications):** `notifications.service.assert_owner_or_platform` calls `db.rls_scope(session)`, which fails on `NO_POSTGRES`. The report-resolution notification therefore cannot be sent without Postgres; the HTTP test stubs that check. It needs a principal-based check.
- **data-learning:**
  - `learning/structured.py`: switch to `placement.public.get_question` / `get_version` and `coding.public`.
  - `mentoring/service.py` and `service_fs.py`: switch to `placement.public.existing_company_ids` and `topic_names`.
  - `paths/service.py`: switch to `assessments.public.test_linkable`, `search_tests` and `attempt_scored_facts`.
- **data-ops:**
  - `analytics/jobs._category_of`: switch to `placement.public.topic_roots`.
  - `analytics/service` (attempt lifetime): switch to `assessments.public.attempt_lifetime`.
  - `analytics/hooks`: switch to `assessments.public.attempt_org_of_user`.
- **data-money (support):**
  - `support/router.py`: switch to `assessments.public.get_attempt`.
  - `support/service.derive_priority`: switch to `assessments.public.has_attempt_in_progress`.
- **coordinator / platform (`app/wiring.py`):**
  - `coding_problem_parents`: use `coding.public.problem_primary_topic` plus `placement.public.topic_with_root`.
  - `test_parents`: use `placement.public.company_paths_with_test`.
  - `mocks_started` / `_attempted_tests`: use `assessments.public.count_attempts` / `count_attempted_tests`.
  - `final_test_lookup`: use `assessments.public.best_result`.

## 7. Round 4 (2026-11-12)

Emulator only, with `TD_TEST_NO_PG=1`. All the new tests go through the FastAPI app with no Postgres.

**1. AI grading (ASM-26).** It now calls `ai.public` (`grade_response`, `AIError`) with the fake provider. Test `test_ai_grading_suggestion_then_human_grade`:
- a pending AI suggestion is stored on the essay;
- a re-run skips it;
- the evaluator's mark then finalises the item.

**2. Rebind with OTP (ATT-04/05).** Test `test_rebind_with_otp` uses a user created through `identity.public` and the in-memory email adapter:
- a second device at restriction level 2 is refused with `otp_required`;
- the OTP is sent;
- a wrong code is refused;
- the right code rebinds the attempt.

The OTP functions are `identity.service.create_otp`, `check_otp` and `otp_send_allowed`, which already work on Firestore. `identity.public` does not export them. **Request to the access agent:** add them to `identity.public`.

**3. Outbox handler `assessments.coding.on_submission_judged`.** It lives in my module. On the Firestore store, when the relay passes `None` or a session the engine cannot use, the handler runs in its own `store_session()` with system scope and commits on return. The Postgres path is unchanged. Test `test_outbox_handler_rescores_without_postgres`.

**4. Bug found and fixed.** The engine's `SqlStore.get` compares only the first primary-key column. `session.get(AttemptItemGrade, (attempt_id, qv))` therefore never found an existing grade row, created a duplicate, and the commit returned 409. `assessments.datastore.get` now selects on every primary-key column for composite keys. Before this fix, grading an item that already had an AI suggestion failed. **Request to platform:** fix `SqlStore.get` for composite keys.

**5. `placement.public` re-exports for data-learning.** These are all store-neutral:
- `load_bundles`, `versions_of`, `delivery`, `key_payload`, `Bundle` (from `bank`);
- `is_correct`, `normalise_response` (from `grading`);
- `can_in_org`, `has_permission` (from `policies`);
- `html_of` (from `richtext`).

**6. `bank.submit_review`.** It now reads the linked coding problem through `coding.public.get_problem`; a `not_found` counts as "missing", exactly as `session.get` returning `None` did. On Postgres that is the same `session.get` under the same RLS, so behaviour is unchanged. I removed the coding agent's stand-in fixture `placement_reads_coding_public`, at the coordinator's request. `tests/coding/fs/test_coding_attempt_http_firestore.py`: **1 passed**.

**Results:**
```
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=assess_test pytest tests/placement/fs tests/assessments/fs -q
  -> 29 passed in 238 s   (assessments: 7 HTTP tests + public API test)
pytest tests/coding/fs/test_coding_attempt_http_firestore.py -> 1 passed (fixture removed)
ruff check / ruff format --check (my modules and tests) -> clean
mypy app/modules/{assessments,placement} -> 0 errors in these modules
```

## 8. Round 5: cross-module cleanup (2026-11-12)

The scanner is the same method as `cleanup.md` §1: other modules' `models` imports, plus SQL text naming another module's table. The scanner script is in the session scratchpad (`xscan.py`).

| File | Before | After | How |
|---|---|---|---|
| assessments/attempts.py | 7 | **0** | Batch membership, device check, session hold and auth-session lookups go through `orgs.public` / `sessions.public` (via `xmod`) on both stores. Version settings come from `placement.bank.load_bundles`. The OTP flow uses `identity.public.create_otp` / `check_otp` / `otp_send_allowed` / `get_user` |
| assessments/studio.py | 2 | **0** | `placement.public.get_company`, `get_company_path`, `get_question`, `get_version`, `coding_question_for_problem` and `coding_pool`. The two coding lookups now hold the original Postgres SQL inside placement, their owner. Membership goes through `orgs.public.is_batch_member` / `org_memberships` |
| assessments/report.py | 1 | **0** | `xmod.version_topics` (`placement.bank.load_bundles`) |
| assessments/evaluation.py | 1 | **0** | `identity.public.get_profiles` |
| assessments/datastore.py | 3 (string match) | **0** | The foreign-model dispatch now keys on table names |
| assessments/integrity.py | 2 | **0** | Already cleared in round 3 |
| assessments/coding.py | 3 | **3** | Needs coding functions that do not exist yet (requests below) |
| placement/mentoring.py | 4 | **0** | `orgs.public.list_batches` / `batch_members` and `identity.public.get_users` / `get_profiles`, inside `rls.system_scope` (`system_context` on Postgres). The `status = 'active'` filter is kept exactly |
| placement/practice.py | 3 | **0** | Always `assessments.public.fixed_versions_in_live_tests`, with question ids from `bank.load_bundles` |
| placement/bank.py | 1 | **0** | New `assessments.public.test_exists` |
| placement/policies.py | 1 | **0** | `orgs.public.get_batch` |
| **Total** | **26** | **3** | |

On Postgres every replacement runs the same statement through the owning module (the same RLS context; the `system_context` blocks are kept).

**Requests to the coding agent:** add these to `coding.public`, so that `assessments/coding.py` (3 hits) and the code signals in `assessments/integrity._code_signals` can drop `coding.models` and `coding.repo_firestore`:
1. `get_submission(session, submission_id) -> CodeSubmission | None` (`session.get`).
2. `attempt_submissions(session, *, attempt_id, user_id, problem_id, mode="submit") -> list[CodeSubmission]`.
3. `submission_view` re-exported.
4. `attempt_code_signals(session, attempt_ids) -> {attempt_id: (max submits per problem per hour, similarity flags)}`.

**Results:**
```
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=assess_test pytest tests/placement/fs tests/assessments/fs tests/coding/fs/test_coding_attempt_http_firestore.py -q
  -> 30 passed in 226 s
ruff check (assessments, placement) -> clean;  mypy -> 0 errors in these modules;  create_app() builds
```
Postgres parity is still unverified (no Postgres, by owner decision). Every Postgres path now runs the owner module's statement, which needs checking against the VM.

## 9. Round 6: Postgres text ordering on Firestore paths (2026-11-12)

Every Firestore-path in-memory `ORDER BY <text>` in placement and coding now uses `app.core.firestore.collation`, which reproduces glibc `en_US.utf8` ordering plus the byte tie-break. None of the text columns concerned can be NULL, so the default NULL placement does not come into play. Python sorts that already run on **both** stores (e.g. the bank `subjects`, `tags` and readiness lists) were left as they are, so the two stores stay identical.

| Site | Postgres `ORDER BY` | Firestore fix |
|---|---|---|
| `placement/bank.subject_tree` | `depth, position, name` | `sort_key(name)` |
| `placement/repo_firestore.companies` (`list_companies`) | `companies.name` | `sort_key(name)` |
| `placement/repo_firestore.paths` | `company_paths.role_name` | `sort_key(role_name)` |
| `placement/repo_firestore.banks_of_question` (question detail `banks`) | `question_banks.name` | `sort_key(name)` |
| `placement/practice.my_company_path` | `role_name, version_no DESC` | `(sort_key(role_name), -version_no)` |
| `placement/banks._fs_list_banks` with `sort="name"` | `lower(name), id` | `(citext_key(name), id)` |
| `coding/service.enabled_languages` | `language_key` | `sort_key(language_key)` |
| `coding/repo_firestore.languages` | (feeds the above) | sorted in memory with `sort_key` |
| `coding/repo_firestore.ref_solutions` (`list_reference_solutions`) | `language_key` | sorted in memory with `sort_key` |

**Firestore server-side `order_by` on text fields** (these order by raw bytes):

| Site | Field | Decision |
|---|---|---|
| `coding/repo_firestore.languages` | `language_key` | The full set is fetched, then re-sorted in memory with `sort_key` (above). No sort-key field needed |
| `coding/repo_firestore.ref_solutions` | `language_key` | Same: full set (one problem), re-sorted in memory |
| `placement/repo_firestore.subtree` | `path` | A prefix **range scan** (`path >= p`, `< p + "/"`) used as a set (subtree ids, re-pathing, search filters). Byte order is required for the range; the result is never shown in order. No change |

No placement or coding Firestore list paginates on a text field: the cursors use ids, timestamps or positions. No stored sort-key field was therefore needed.

**Tests (new):**
- `tests/placement/fs/test_collation_order_firestore.py`: companies, subject-tree siblings and the bank list by name;
- `tests/coding/fs/test_coding_collation_firestore.py`: `enabled_languages` follows `sort_key` and differs from code-point order.

The corpus `Zeta, beta, Alpha, co-op, co op, coop, éclair, Echo` must come out as `Alpha, beta, co op, co-op, coop, Echo, éclair, Zeta`.

```
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=assess_test pytest tests/placement/fs tests/coding tests/assessments/fs -q
  -> 73 passed, 39 skipped (the Postgres-only coding suites skip under TD_TEST_NO_PG) in 268 s
ruff / ruff format: clean on the edited files; mypy: 0 errors in placement and the edited coding files
```
Assessments ordering comes from the sqlstore engine, which platform is updating.
