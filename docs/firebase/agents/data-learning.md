# Firebase migration: data-learning agent (learning, engage, mentoring)

> **Removed 2026-11-14** ([cleanup/feature-removal-plan.md](../../cleanup/feature-removal-plan.md)): mentoring (slots, bookings, sessions, feedback, mentor notes, résumé reviews, the `/mentor` console; the Résumé builder stays), company paths (the `companies` entity stays), corporate enquiries, `GET /catalog/search`, the public SPA pages Hosting redirects to the website, and the `/app/diagnostic`, `/admin/question-review`, `/admin/notifications`, `/app/bookmarks`, `/app/analytics` and `/security/policies` pages. Mentions below of those features are historical.

Agent: data-learning. Rounds 1, 2 and 3 all ran on 2026-11-12. This report covers the state
after round 7. Round 3 replaced last-writer-wins with transactions at every former `FOR UPDATE`
site and made every in-memory register match the SQL (section 7). Round 4 closed the last two race differences (section 8). Round 5 routed all cross-module access through public.py (section 9).

Every switch still defaults to **`postgres`**. Nothing is deployed and nothing is flipped. These
were not edited:
- `firestore.indexes.json`;
- the shared core;
- the Firestore rules;
- other modules.

**Test policy (owner decision).** Testing uses only the Firebase emulator, with
`TD_TEST_NO_PG=1` and no Docker or Postgres. Postgres matrix runs are skipped. Parity with
Postgres is checked later against the live VM.

## 1. Status

| Module | Code state | Tests (emulator, no Postgres) |
|---|---|---|
| **learning** `TD_STORE_LEARNING` | **Routed.** Every learning endpoint has a Firestore path: enrolments, progress, certificates, outbox, admin certificate register, legacy and structured assignments, regrades, issued documents, templates and settings, erasure. A store-neutral `public.py` exists for other modules | 35 service-level tests plus **4 HTTP tests** through the FastAPI app. All pass |
| **engage** `TD_STORE_ENGAGE` | Complete (round 1). Round 2 changes: batch membership, invite recipients and the nickname lookup now go through `orgs.public` / `identity.public`, and there is no `system_context` when no Postgres session exists. `public.py` added | 12 repository tests plus **2 HTTP tests**. All pass |
| **mentoring** `TD_STORE_MENTORING` | Complete (round 1). Round 2 changes listed below this table. `public.py` added | 13 repository tests plus **2 HTTP tests**. All pass |

Round 2 changes in mentoring:
- Quotas use the entitlements API (`usable_entitlements`, `consume_quota`, `credit_quota`).
- Companies and topics come from the `placement.bank` API.
- Certificates come from `learning.public`.
- Names, batches and batch students come from `orgs.public` / `identity.public`.
- `as_system` is a no-op without a Postgres session.

**Safe to flip?** On the code side, yes, for all three, once other modules stop reading these
tables directly (§5). Engage and mentoring have no such readers left. Learning still has
readers in admin, paths, analytics, commerce, admissions and `wiring.py`, which must switch to
`learning.public`.

The HTTP tests use a request session that **fails on any SQL statement**, so the routes they
cover are proven Postgres-free.

## 2. Round 2 work

### 2.1 `public.py`: the store-neutral API for other modules

**`app/modules/learning/public.py`.** Each function has a Postgres branch, which is the
caller's own query moved verbatim, and a Firestore branch.

| Function | Replaces the direct SQL/ORM in |
|---|---|
| `courses_overview_stats(session, now)`, returning `CoursesOverviewStats` | `admin/courses_overview.py` |
| `assignment_in_org`, `assignment_link_options`, `assignment_grades_released_at`, `graded_submissions` | `paths/service.py` (`_check_link`, `link_options`, `_assignment_done`) |
| `enrolments_of_users`, `lesson_progress_counts` | `analytics/reports.py` |
| `get_enrolment`, `student_lesson` | `analytics/hooks.py` |
| `certificates_for_refund(user, course_ids=, issued_since=)`, plus `revoke_certificate` | `commerce/service.py` `_revoke_certificates`. `revoke_certificate` / `revoke_certificates_for_entitlement` / `revoke_certificates_for_courses` keep their **signatures unchanged** |
| `lock_enrolment`, `create_enrolment`, `withdraw_enrolment(session, enrolment_id, entitlement_id)` | `admissions/service.py` (`enrol`, `revoke_access`) |
| `max_progress_by_course`, `has_certificate_for_courses`, `coding_access_grant`, `register_*` | `wiring.py` (usage provider and hooks) |
| `check_lesson_access`, `get_progress`, `record_video_heartbeat`, `STUDENT_VISIBLE` | `media/{router,service}.py` |
| `certificates_of_user` | `mentoring/service.py` (now switched) |

**`engage/public.py`.** No module outside engage reads engage tables. It exports
`create_activity`, `list_activities`, `activity_detail` and `my_runs`, all of which dispatch on
the switch.

**`mentoring/public.py`.** It exports what `placement/mentoring.py` uses: `booked_students`,
`names`, `student_summaries`, `feedback_history` and `read_notes`.

### 2.2 The learning unit of work: `learning/fs_store.py`

Learning was written in the SQLAlchemy style: load ORM rows, mutate them, `session.add`,
`await session.flush()`. `fs_store` (imported as `fss`) keeps that shape on both stores, so the
roughly 340 call sites ported mechanically.

| Postgres | Store-neutral |
|---|---|
| `session.get(M, pk)` | `fss.get(session, M, pk)` |
| `select(M)...` | `fss.find(session, M, filters=, order_by=, where=, limit=)` (Firestore) |
| `session.add(obj)` | `fss.add(session, obj)` |
| `await session.flush()` | `await fss.flush(session)` |
| `session.delete(obj)` | `fss.delete(session, obj)` |

How it works on Firestore:
- **Tracked rows.** Rows come back as transient ORM instances, with a snapshot of each. They are tracked in `session.info`; with no Postgres session (`None`, or core's falsy `NO_POSTGRES`), the current asyncio context holds them instead. An identity map applies within a real session.
- **What `flush` writes, in order:**
  1. **Creates.** Each create is one transaction covering the row plus its uniqueness key documents. Server defaults (`now()`, `'active'`, `0`, `'{}'`) are applied and written back to the object.
  2. **Deletes.** Each delete removes the row and its key documents.
  3. **Updates.** A field diff of every tracked row. When a key field changes, the key documents move with it (for example, a regrade leaving `open` releases `regrade_open`).
- **Conflicts.** A uniqueness conflict becomes the 409 that Postgres maps the constraint to (for example, "You are already enrolled in this course."). With `raise_unique=True`, `fss.UniqueConflict` is raised instead, for retry loops.

### 2.3 Learning routing, by area (each area has its own Firestore query helpers)

| Files | Helper | Notes |
|---|---|---|
| `service.py`, `router.py`, `privacy.py` | `fs_enrol.py` | Enrolments (self, batch, admissions); progress (video heartbeat, article completion); recompute; certificate eligibility, issue and revoke (including for an entitlement or courses); version migration and publish hook; dashboard; learner assignment lists; staff assignment register and grading; erasure. Batch reads branch on `uses_firestore("orgs")` and use `orgs.public` |
| `certificates.py`, `cert_admin.py` (`certpdf.py` has no SQL) | `fs_cert.py` | Outbox queue, approve, cancel and send. `FOR UPDATE SKIP LOCKED` becomes a sender **lease** (`learning.certificate_outbox_send`). Also: PDF backfill; due enrolments and batch-end issue; the admin register, search, summary and outbox page. Users and batches come through `identity.public` / `orgs.public` |
| `structured.py`, `structured_api.py` | `fs_assign.py` | Structure put and clone, allocations, extensions, workspace (start, autosave, submit), AI-grading queue, evaluation, review, finalize, release, regrade requests and resolve. The SQL filter builders (`allocated_to_learner_filter` and the others) are Postgres-only; Firestore evaluates the same predicates in memory. Graders use `rbac.service`. Org and batch membership use `orgs.public`; names use `identity.public` |
| `documents.py`, `doc_admin.py` (`docpdf.py` and `docdefs.py` have no SQL) | `fs_docs.py` | Issue with a unique `ref_no` (Postgres savepoint plus `IntegrityError`; Firestore `raise_unique`, giving the same 409), reissue and supersede, revoke (unsent emails cancelled), public verify and PDF check, templates, the settings singleton, the register and its counts, the enrolment letter |

A static audit (every function containing SQL also has a Firestore branch) leaves only these:
- the Postgres-only SQL filter builders;
- `structured.graders`' role join, which on Firestore goes through `rbac.service`;
- `cert_admin.put_settings`, the `FeatureFlag` row, which on Firestore uses the admin repository.

## 3. Data model (unchanged since round 1)

`fs_rows` codec: UUID → str, Decimal → exact str, bytes → hex, a nested array → `{"$l": [...]}`.
Each Postgres UNIQUE constraint or partial unique index becomes a key document.

| Module | Collections |
|---|---|
| learning | Each table is `<table>/{pk}`. Key collections: `enrolment_keys`, `certificate_codes`, `certificate_by_enrolment`, `certificate_outbox_keys`, `submission_keys`, `item_response_keys`, `regrade_open`, `issued_document_keys` |
| engage | `engage_activities` (plus `deleted`), `engage_questions`, `engage_runs`, `engage_join_codes`, `engage_run_keys`, `engage_participants/{run:user}`, `engage_seq/{run}`, `engage_responses/{participant:question}` |
| mentoring | `mentor_slots`, `mentor_slot_times`, `mentor_bookings` (plus the denormalised slot fields), `mentor_slot_live` (no double booking), `mentor_booking_idem`, `interview_feedback`, `interview_feedback_by_booking`, `mentor_notes`, `resumes`, `resume_versions`, `resume_reviews`, `resume_review_open` |

Indexes: `app/modules/{learning,engage,mentoring}/firestore.indexes.fragment.json` (11, 5 and 4
indexes) are for the coordinator to merge. Backfill and verify use the generic CLI:
`python -m app.core.firestore.backfill learning engage mentoring`.

## 4. Tests (2026-11-12, emulator only)

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=learning_test .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q \
  tests/learning/test_fs_*.py tests/learning/fs tests/engage/test_fs_repo.py tests/engage/fs \
  tests/mentoring/test_fs_repo.py tests/mentoring/fs
```

Result: **68 passed** in 61 s.

### HTTP tests

These go through the real FastAPI app. The harness is `tests/learning/fs/harness.py`, built on
`tests/paths/fs/http_harness.py`. The request session fails on any SQL statement or ORM `add`.
Audit and outbox are recorders. Catalog, entitlements, orgs, identity, rbac, ai, core and
notifications all run on Firestore.

**`tests/learning/fs/test_learning_http.py` (4 tests):**
- **Course flow.** A course is created and published through the catalog studio. Then: enrol (201, then 200 on repeat); open lessons; complete articles; progress reaches 100 %; the certificate is issued automatically; public verify works (404 for an unknown code); the dashboard loads; another learner sees nothing.
- **Legacy batch assignment.** Batch learner only (an outsider gets 404, a student creating one gets 403). Then: submit, then 409 on the attempt limit; trainer queue; grade (422 above the maximum); hidden until release, then the score and feedback are shown; grading after release gets 409.
- **Structured assignment.** Inline sections; allocation to a batch with company-staff evaluators; workspace start, autosave and submit (409 on a late edit); evaluation and review; finalize (total 9); unpublished, then publish with per-item marks; regrade request (409 on a second open one), resolve with reopen.
- **Documents and admin certificates.** The settings gate (409), then settings; issue (`TD-AL-…`, PDF, email sent); the register and its search (a learner gets 403); detail; public verify and the PDF hash check; the shared outbox queue; certificate summary and register; templates; revoke, after which verify shows "revoked".

**`tests/engage/fs/test_engage_http.py` (2 tests):**
- **Quiz flow:** create (a learner gets 403); listing; detail; launch; start; join preview and join (idempotent); live state with no answer-key leak; answers (409 on a second answer to the same question); presenter counts; reveal; publish refused on a live run; finalise (event recorded); leaderboard and my rank; my runs; rerun, giving run 2 with a new code; duplicate; delete.
- **Members-only batch activity:** a member joins; a non-member gets 403.

**`tests/mentoring/fs/test_mentoring_http.py` (2 tests):**
- **Slots and bookings:** slots are created (409 `slot_overlap`); a student sees open slots and the quota; books (the quota is consumed on Firestore entitlements); **a second student is refused with 409 `slot_unavailable`**. Then: reschedule (credit kept, and the old slot is bookable again); my bookings; mentor sessions and counts; cancel (credit restored); mentor slot list; delete a slot.
- **Résumés:** versions 1 and 2, with exactly one current; a review request (409 on a second); the mentor queue; feedback completes the review.

### Other checks

| Check | Result |
|---|---|
| `ruff check` / `ruff format --check` on the three modules and their tests | clean (89 files) |
| `mypy app/modules/{learning,engage,mentoring}` | no errors in these modules. The 4 remaining errors are in shared core (`core_store.py`, `redis.py`), which I did not touch |

**Not run.** Postgres-side suites and the round-1 Postgres matrix files (`test_*_firestore_matrix.py`), per the owner's decision. Postgres-path parity is to be checked against the live VM.

## 5. Requests to other agents

1. **Platform / core (blocks the final no-Postgres stack).** On `NO_POSTGRES`, these must become no-ops or run on Firestore. Today they execute SQL on the request session:
   - `system_context` / `as_system` / `tenant_context`;
   - `rls_scope`;
   - `emit_event` (`app/core/outbox.py`).

   Also, core idempotency (`core_store`) awaits `session.begin_nested()` on any non-`None` session, including `NO_POSTGRES`.

   Learning's request paths still call `system_context` and `emit_event`. The HTTP tests run them on a GUC-only session and a recorder. Engage and mentoring already skip them without a session.
2. **Owners of learning's direct readers.** Switch these to `app.modules.learning.public` (§2.1):
   - admin: `courses_overview`;
   - paths: `service.py` lines ~497, ~798 and ~1565;
   - analytics: `reports.py` (`_enrolments`, `_lesson_funnel`);
   - commerce: `_revoke_certificates` (use `certificates_for_refund`);
   - admissions: `revoke_access` (use `withdraw_enrolment`);
   - `wiring.py`: `LearningUsageProvider` (use `max_progress_by_course` / `has_certificate_for_courses`);
   - seeds: `company_demo.py` (learning, engage).

   This is the last blocker for flipping learning.
3. **Coordinator.**
   - Merge the three index fragments.
   - Promote `fs_rows.py` to `app/core/firestore/rows.py` (three copies today).
   - Optionally promote `learning/fs_store.py` as a generic unit of work.
4. **orgs.** Confirm that `orgs.service.attendance_certificate_block` is store-neutral (certificates and due enrolments call it).
5. **Documents (F4 notes).** `verify_pdf_check` uses `system_context`, and `on_enrolled` uses `session.begin_nested()`. Both are covered by request 1.

## 6. Known differences on Firestore (read before flipping)

**Cross-store ordering.** Audit, outbox and idempotency rows commit separately from Firestore
writes, so a failure after a Firestore commit leaves that write in place. This applies until P6
or until core moves:
- issue then supersede of documents are separate writes;
- the mentoring credit-back runs after the booking change.

**Locks.** Since round 3, every former `FOR UPDATE` site is a Firestore transaction, a lease or a uniqueness key; nothing there is last-writer-wins any more (section 7.1). The certificate sender still takes one sweep lease per run. Since round 3, each row also has its own lease, so concurrent sweeps no longer split the work but never send twice.

**In-memory filtering.** These load a collection and filter or sort in memory. Their results are proven equal to the SQL (section 7.2):
- learning: the certificate and document registers and searches (including email searches), the due list, the admin overview, learner assignment eligibility;
- engage: run aggregation;
- mentoring: mentor sessions.

The cost grows with the data. It is fine at company size. Shadow fields plus indexes would fix
it if the data grows.

**Race outcomes.** A few races return a different 409 code than Postgres:
- simultaneous slot bookings get `slot_unavailable`;
- engage join seq comes from a counter, which avoids a Postgres 500 risk.

**Ordering without a Postgres tie-breaker.** Since round 7, word-cloud ties sort by the database collation (section 11). Text samples are ordered by (`answered_at`, `id`).

**Decimal scores.** They are stored as exact strings. No current query orders by them.

## 7. Round 3: lock parity and register parity

### 7.1 Former `FOR UPDATE` and lock sites

New primitives in `learning/fs_store.py`:
- **`fss.locked(session, Model, ids, fn)` / `fss.locked_multi(...)`.** The rows are read inside one Firestore transaction. `fn` checks and mutates them; it must be pure, because it is re-run with fresh rows when a concurrent writer commits first. The field diffs and any moved uniqueness keys are written in the same transaction. This is the equivalent of a Postgres transaction waiting on the row lock.
- **`fss.lease(key)` / `fss.release(key, holder)`.** These replace a row lock held during external work (email or AI calls) and `SKIP LOCKED`.
- **`fss.copy_into`** and **`fss.evict`**.

Fix: in `send_one` the row was mutated on an untracked copy, so its status change was silently not saved. It is now mutated on the session's tracked instance.

| Site (Postgres) | Firestore now | Test |
|---|---|---|
| `certificates.approve` / `cancel` (`FOR UPDATE` on outbox rows) | `fss.locked`: transition checks run on fresh rows | `test_fs_concurrency_cert`: 4 concurrent cancels give 1 cancelled and 3 skipped; approve racing cancel serialises |
| `certificates.send_one` / `send_pending` (lock held while sending; `SKIP LOCKED`) | A per-row lease, then the status is re-read before sending | 4 concurrent sends deliver once; a later call re-reads "sent" |
| `service.revoke_certificate` and the bulk revokes (`FOR UPDATE ... WHERE revoked_at IS NULL`) | `fss.locked` check-and-revoke. The bulk revokes skip rows revoked in the meantime | 3 concurrent revokes: 1 wins and its reason is kept; two refunds racing revoke each certificate once |
| `service.on_course_published` / `migrate_version` and `recompute` (`FOR UPDATE` on enrolments) | Version switch plus re-open, and progress plus completion, each one transaction on the fresh row | `test_fs_concurrency_enrol`: 3 concurrent publish hooks migrate each enrolment once, with correct progress |
| `lock_enrolment` (advisory lock) plus insert (self-enrol, enrol-on-lesson) | The `enrolment_keys` key. The loser now returns the **winner's enrolment** (200), as Postgres does after the wait; before round 3 it returned 409 | 4 concurrent self-enrols: one enrolment, created once, one event |
| `router` learner submit (`FOR UPDATE` on own submissions) | Attempt number plus insert, retried on a `submission_keys` conflict | 4 concurrent submits with `max_attempts=2` get attempts 1 and 2, and 2 × `attempt_limit_reached` |
| `structured.upsert_response` (`FOR UPDATE`) | First save: a create-only insert (round 4). Later saves: a locked update, so the last writer wins with nothing else overwritten, as under the lock | Section 8 |
| `structured.run_queued_ai` (`FOR UPDATE OF responses` during AI calls) | A per-response lease plus a fresh "still queued" check | 3 concurrent handlers: AI is called once per item |
| `structured_api` regrade resolve (`with_for_update`) | `fss.locked_multi` over the request **and** its submission (status check plus reopen in one transaction) | 3 concurrent resolutions: 1 winner; the submission is reopened only by a "resolve" winner |
| `public.certificates_for_refund` (`with_for_update`) | Read only. The revoke step is locked (see above) | Covered by the revoke tests |
| mentoring `pdf_upload` / `pdf_complete` / `save_resume` (`FOR UPDATE` on the résumé) | `complete_pdf` is a transaction (check the pending key, then promote it). Upload and save were blind overwrites under the lock and stay atomic single-document writes | `tests/mentoring/test_fs_concurrency.py`: 4 concurrent completes give 1 success and 3 × `validation_failed` |
| mentoring book / reschedule / cancel / delete slot / feedback / no-show / review completion / résumé versions; engage launch / control / join | Already transactions (round 1) | `test_fs_repo.py` in each module: 6 bookers give 1 booking; 8 joins get seq 1–5 plus 3 "full"; 4 résumé saves get versions 1–4 |
| mentoring `create_slots` | Also fixed: two new slots at the same start in one request now give 409 `conflict`. Before, Firestore raised a 500 "insert then insert" | Found by the register fixture |

Both race differences that were left after round 3 are closed in round 4 (section 8).

### 7.2 Registers and searches equal the SQL

The tests are `tests/learning/test_fs_registers.py`, `tests/engage/test_fs_registers.py` and
`tests/mentoring/test_fs_registers.py`. Each one runs the **same SQL in SQLite** over the
fixture rows:
- `case_sensitive_like` is on;
- UUIDs are stored as lower-case text, so they sort as Postgres `uuid` does;
- `NULLS LAST` is supported.

Each test then compares ids, order, page boundaries and the more/next flags, page by page with
the route's cursor or offset, plus the totals. Fixtures include ties, NULLs, case variants and
`%` / `_` in search terms.

| Register / search | Covered |
|---|---|
| Admin certificate register | course, status, the search term over name, code, user email and full name, keyset pages, limits 4 and 50 |
| Certificate summary counts | total, revoked, without PDF, per course |
| Outbox approval queue | status, course (through the certificate or the document), kind, keyset pages |
| Due list | completed or batch ended, excluding certified and withdrawn, course filter, `completed_at DESC NULLS LAST, id DESC` with ties, limit |
| Documents register and status counts | type, status, course, search term (name, email, normalised ref), pages |
| My enrolments, my certificates (order with ties), staff enrolment page (keyset), staff assignment list, due-date ordering | as listed |
| engage activity list | type, escaped `ILIKE`, soft delete, `created_at DESC`, limit |
| mentoring open slots and my bookings | offset pages |
| mentoring mentor sessions | 4 views, order, offset pages, counts |
| mentoring résumé review queue | open and completed, scope sets, own reviews excluded, order, limit |
| mentoring mentor notes | org visibility, order |

Fix: the certificate and document register searches used plain substring matching. The SQL is
an **unescaped** `lower(col) LIKE '%term%'`, in which a user's `_` or `%` is a wildcard. The
searches now use `fss.like`, which implements Postgres `LIKE`: NULL never matches, and `%`, `_`
and backslash escapes behave as in Postgres. The engage title search escapes the term, as the
SQL does.

### 7.3 Results (round 3)

Command:

```
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=learning_test .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/learning/test_fs_*.py tests/learning/fs tests/engage/test_fs_*.py tests/engage/fs tests/mentoring/test_fs_*.py tests/mentoring/fs
```

Result: **89 passed** in 133 s. The previous 68 tests still pass; 21 are new (11 concurrency, 10
register).

| Check | Result |
|---|---|
| `ruff check` / `ruff format` | clean |
| `mypy` | no errors in learning, engage or mentoring. The remaining errors are in shared core files |

## 8. Round 4: the last two race differences

**1. Two concurrent first autosaves of the same item.**
- *Postgres:* both requests find no row, both `INSERT`, and the unique index fails the second with 409 `conflict` (generic detail).
- *Firestore:* `structured._upsert_response_fs` now inserts **create-only**. The `item_response_keys/{submission:item}` key is created in the row's transaction, so the second insert fails with the same 409 `conflict`. It no longer turns into an update of the first row.
- A save of an existing row is unchanged: a locked update where the last writer wins.

Tests in `test_fs_concurrency_assign.py`:
- `test_concurrent_first_autosaves_conflict_like_postgres`: 4 requests all read "no row" before any insert (held with a barrier). Result: exactly 1 `ok` and 3 `conflict`, and one row.
- `test_concurrent_later_autosaves_serialise`: all succeed, the last one wins.

**2. An admin cancel or approve landing while an email is being sent.**
- *Postgres:* the cancel waits on the row lock that the sender holds. It then sees `sent` and skips the row with `{"id": ..., "reason": "sent"}` (`cancelled: 0`).
- *Firestore:* `fss.locked(..., respect_leases=[f"outbox.{id}"])` reads the send-lease document inside the cancel or approve transaction.
  - While the lease is held, the transaction waits: it polls with backoff, up to the lease TTL plus 5 s. Then it acts on the row's final status, giving the same `reason: "sent"` skip.
  - The lease document is in the transaction's read set. So when a sender claims the lease concurrently, one of the two transactions retries; both cannot proceed.
  - When the cancel commits first, the sender re-reads `cancelled` after taking its lease and sends nothing.
- Result: a row reported "cancelled" can never end "sent".

Tests in `test_fs_concurrency_cert.py`:
- `test_cancel_waits_for_in_flight_send_like_postgres`: a cancel during a 0.5 s send returns `{"cancelled": 0, "skipped": [{"reason": "sent"}]}`, and the row is `sent` with no `cancelled_at`. An approve during a send also reports `reason: "sent"`.
- `test_cancel_before_send_wins_and_nothing_is_sent`: a cancel first, then a sender holding a stale "pending" read, sends nothing. Then 3 rounds of racing send and cancel: whenever the cancel reports success, the row is `cancelled`; otherwise it is `sent`, with the skip reason `sent`.

**Results (round 4).** The command from section 7.3 gives **92 passed** in 136 s. ruff check and format are clean. mypy shows no errors in learning, engage or mentoring; the remaining errors are in other modules' and core files.

## 9. Round 5: cross-module access through `public.py`

**Goal.** In learning, engage and mentoring there is no import of another module's `models`,
no SQL on another module's tables, and every cross-module call goes through that module's
`public.py`. When a needed function is missing from someone else's `public.py`, it is listed
in §9.3 rather than added there.

### 9.1 Scan, before and after

Scans run over `app/modules/{learning,engage,mentoring}`:
1. `from app.modules.<other>.models import`;
2. SQL text or `select(<OtherModel>)` touching another module's tables;
3. any `from app.modules.<other>... import` that is not that module's `public`.

| Scan | Before | After |
|---|---|---|
| 1. Imports of other modules' `models` | **11**. `identity.models` ×4 (cert_admin ×2, certificates); `orgs.models` ×5 (router ×4, certificates); `admin.models.FeatureFlag` (cert_admin); `rbac.models` (structured); `entitlements.models` (mentoring) | **0** |
| 2. SQL on other modules' tables | **9**. `select(User…)` ×2 (cert_admin); `select(FeatureFlag)` (cert_admin); `select(Batch…)` ×2 and `select(BatchMember…)` (router); `select(RoleGrant…)` join (structured graders); outer joins to `batches`/`users`/`user_profiles` (certificates due list and the router assignment list); `text("… FROM user_profiles")` (engage join); `Entitlement` predicates (mentoring `_usable`) | **0** |
| 3. Non-public cross-module imports | **~45** distinct lines in total (`ai.service`, `catalog.api`/`service`, `media.storage`, `coding.service`, `entitlements.service`, `notifications.service`/`adapters`, `commerce.documents`, `admin.flags`/`privacy`/`repo_firestore`, `analytics.mastery`, `ai.store`, `rbac.service`, `placement.bank`/`grading`/`policies`/`richtext`, `identity.links`, `orgs.service`) | **11** lines, all needing functions that are not in the owner's `public.py` (§9.3) |

### 9.2 What changed (behaviour is unchanged on both stores)

**learning**
- **`cert_admin`**
  - The auto-send setting uses **`admin.public.patch_flag`**, as data-ops asked. It invalidates the flag cache, and each store keeps its own "flag missing" detail.
  - E-mails come from `identity.public.get_users`.
  - The register search's people subquery is now `fs_cert.people_matching`: identity public, Postgres `LIKE` semantics, used on both stores.
- **`certificates`**
  - The due list is store-neutral. Learning's own enrolments and certificates are read in SQL on Postgres. Batches come from `orgs.public.get_batches` and users and profiles from `identity.public`. Order, filters and limit are as before; they are verified against the SQL by `test_fs_registers.py::test_due_list_order_filters_limit`.
  - Imports moved to `notifications.public` (`notify`, `EmailAttachment`, `OutboundEmail`, `get_email_adapter`), `commerce.public.get_document_store`, `admin.public.flag_enabled`, `media.public`, and `catalog.public`.
- **`router`**
  - Batch lookups (`_org_of_target`, batch enrol, the assignment-list batch names) use `orgs.public` (`get_batch`, `batch_members`, `batch_names`). They run in a system context, as the joins did.
  - Imports moved to `ai.public.require_app_enabled`, `catalog.public`, `media.public` and `coding.public`.
- **`structured`**
  - `graders` uses `orgs.public.org_memberships` plus **`rbac.public.user_ids_with_permission`**, which replaces the `RoleGrant`/`RolePermission`/`Permission` join.
  - The bank question lookup uses `placement.public.get_question`, with the soft-delete check that `bank.get_question` had.
  - Imports moved to `coding.public` and `ai.public`.
- **`structured_api`**: imports moved to `ai.public` (`require_app_enabled`, `grade_response`, `tutor_*`, `system_settings`) and `rbac.public.role_permission_map`.
- **`service`**: imports moved to `catalog.public`.
- **`privacy`**: imports moved to `admin.public.register_erasure_provider`.

**engage**
- The join nickname lookup uses `identity.public.get_profile`.
- Imports moved to `notifications.public.notify`, `ai.public.require_app_enabled`, `rbac.public.batch_org`, `placement.public.get_question` (with the soft-delete check), and `admin.public.register_erasure_provider`.

**mentoring**
- Imports moved to `entitlements.public` (`usable_entitlements`, `consume_quota`, `credit_quota`, `QUOTA_FEATURES`, `Actor`, `Entitlement`).
- The dead `_usable` SQL predicate was removed.
- Companies come from `placement.public.existing_company_ids`, and topic names from `placement.public.topic_names` (one call instead of a loop).
- Further imports moved to `analytics.public.get_topic_mastery`, `media.public`, `catalog.public` and `admin.public`.

**Tests.** Tests that stub AI now patch `app.modules.ai.public`, which is what the code calls.
This needed a one-line import change in `tests/learning/test_structured_assignments.py` (a
Postgres suite). That is the only edit to an existing test file.

### 9.3 Missing from other modules' `public.py` (requests; I did not edit those modules)

| Module | Needed in its `public.py` | Used by |
|---|---|---|
| placement | `load_bundles`, `versions_of`, `delivery`, `key_payload` (bank); `grading.is_correct`, `grading.normalise_response`; `policies.can_in_org`, `policies.has_permission`; `richtext.html_of` | learning `structured` (item bundles, keys, auto-marking); engage `bank_import` and `can_manage` |
| catalog | `ensure_permission`, `system_lookup`, `get_version`, `lesson_out`, `version_tree` (today in `catalog.service`) | learning `router`, `structured_api` |
| identity | `links.web_base_url` | learning `certificates`, `documents` (verify links in e-mails) |
| orgs | `service.attendance_certificate_block` (also confirm that it is store-neutral) | learning `certificates` (due list and issue gate) |

### 9.4 Results (round 5)

Command:

```
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=learning_test .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/learning/test_fs_*.py tests/learning/fs tests/engage/test_fs_*.py tests/engage/fs tests/mentoring/test_fs_*.py tests/mentoring/fs
```

Result: **92 passed** in 211 s. mypy shows no errors in learning, engage or mentoring; the 13 remaining errors are in other modules and core.

`ruff check` and `ruff format --check` are clean (96 files). `create_app()` imports and builds.

## 10. Round 6: the last `public.py` switches

The owners added the functions requested in section 9.3. Learning and engage now use them:

| Was | Now |
|---|---|
| `identity.links.web_base_url` (certificates, documents) | `identity.public.web_base_url` |
| `orgs.service.attendance_certificate_block` (certificates due list and issue gate) | `orgs.public.attendance_certificate_block` |
| `placement.bank` (`load_bundles`, `versions_of`, `delivery`, `key_payload`), `placement.grading` (`is_correct`, `normalise_response`), `placement.policies` (`can_in_org`, `has_permission`), `placement.richtext.html_of` (learning `structured`, engage `service`) | `placement.public` |
| `catalog.service` (`ensure_permission`, `get_version`, `lesson_out`, `version_tree`, `register_publish_hook`) in learning `router` and `structured_api` | `catalog.public` |
| `catalog.system_lookup` (5 sites: `router._assignment_scope`, `_submission_row`; `structured_api._sub_for_staff`, `_alloc_for_staff`, regrade resolve) | Not replaced by a catalog function: all 5 look up **learning's own** tables (`assignments`, `assignment_submissions`, `assignment_allocations`, `assignment_regrade_requests`). On Firestore they already read the row with `fss.get`. On Postgres they now call `fss.system_row`, a learning-owned helper: the same system-context lookup followed by an RLS restore, on learning's tables only. So no new catalog function is needed, and nothing calls `catalog.system_lookup` |

**Scan after round 6** (same three scans as section 9.1, over `app/modules/{learning,engage,mentoring}`):

| Scan | Result |
|---|---|
| Other modules' `models` imports | **0** |
| SQL on other modules' tables | **0** |
| Cross-module imports not through `public.py` | **0** |

No requests are left open.

**Results.**
- The suite command from section 9.4 gives **92 passed** in 128 s.
- `ruff check` and `ruff format` are clean.
- `create_app()` builds.

## 11. Round 7: Postgres text collation (en_US.utf8) on the Firestore paths

The shared helper is `app.core.firestore.collation`: `sort_key` and `order_key`, with Postgres
NULL placement.

### 11.1 Every `ORDER BY` in learning, engage and mentoring, by column type

All `order_by(...)` / `ORDER BY` clauses in the three modules' Postgres paths were listed
(about 50).

**Exactly one orders by a TEXT column:** engage word cloud, `ORDER BY 1, n DESC, t` (`t` = the term).
- *Fix:* `service_fs.aggregate` now sorts ties with `sort_key(term)`.
- *Before:* Python code-point order, which put every capital first.

**All the others order by non-text values**, which keep their natural order:
- UUID ids: Postgres `uuid` compares bytes, which equals lower-case-hex string order and Python `UUID` order;
- timestamps;
- integers (`position`, `run_no`, `attempt_no`, `version_no`);
- dates.

**Their NULL placement was re-checked against the Postgres defaults:**
- ASC = NULLS LAST: `submitted_at` in the grading queue and the evaluation; `due_at` with an explicit `NULLS LAST`.
- DESC = NULLS FIRST: `completed_at` in the review queue.
- Explicit `NULLS LAST` on DESC: `last_activity_at`, and `completed_at` in the due list.

All already matched.

**Python sorts on display text** (for example, mentoring names) run on both stores with the same
code, so they are not Postgres `ORDER BY`s and need no change.

### 11.2 Firestore server-side `order_by` on text fields

A grep of every `store.query` / `fss.find` `order_by` in the three modules gives these fields:

| Field | Count |
|---|---|
| `created_at` | 4 |
| `starts_at` | 2 |
| `run_no` | 2 |
| `joined_at` | 1 |
| `position` | 1 |
| `version_no` | 1 |

**None is a TEXT field.** The implicit `__name__` tie-break is the document id. For every
ordered or paginated list that id is the row's UUID (lower-case hex), and its byte order equals
Postgres `uuid` order.

Composite ids (`lesson_progress`, `document_templates`) never back an ordered list. The
template catalogue is read whole and keyed by `(kind, key)`, as its Postgres `select`, which
has no `ORDER BY`.

So **no sort-key field and no backfill change is needed**. No site needed the in-memory
`order_key` either, beyond the word-cloud fix above.

### 11.3 Tests

**New test:** `tests/engage/test_fs_repo.py::test_word_ties_follow_postgres_en_us_collation`. It
checks the word-cloud tie order against the glibc en_US orders that
`tests/platform/test_collation.py` checks against its glibc ground truth:
- `a < A < b < B`;
- `co op < co-op < coop < Co-op`;
- `resume < Resume < résumé`.

**The register parity tests (section 7.2) are unchanged and still valid.** Their SQLite reference
uses BINARY collation, but the `ORDER BY`s they compare are only on UUID text, timestamps and
dates. For all of these, BINARY order equals Postgres order. `LIKE` / `ILIKE` matching semantics
are unchanged, as instructed.

**Results.**
- The suite command from section 9.4 gives **93 passed** in 137 s.
- `ruff check` and `ruff format` are clean.
