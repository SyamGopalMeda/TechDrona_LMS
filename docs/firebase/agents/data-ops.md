# Data-ops agent: audit, admin (rest), ai (rest), security, analytics, hub

Agent: data-ops, 2026-11-12. Builds on P0 (`p0.md`) and P2 (`p2.md`). Every `TD_STORE_*` still
defaults to **`postgres`**; nothing was flipped, deployed or pushed. Postgres/Docker was **not
running**, so only the Firestore side was executed (emulator 127.0.0.1:18080).

## 1. Status per module

| Module | State | Tests | Safe to flip? |
|---|---|---|---|
| **audit** (`TD_STORE_AUDIT`) | **Complete.** Firestore outbox, hash chain, head, sealer (dual-outbox transition), read API dispatch, backfill + verify of the chain | 10 emulator tests pass; 2 HTTP matrix tests written (need PG) | After the PG matrix run + the "Requests" item 1 below. Flip procedure in §4 |
| **admin** rest (`TD_STORE_ADMIN`, same switch as flags/policy) | **Complete:** privacy_requests, erasure_ledger, retention_policies, break_glass_sessions: repository, dispatch in `privacy.py` / `router.py` / `accounts.py`, backfill + verify | 10 emulator tests pass; existing `admin_backend` matrix tests now also backfill these tables (not run: PG down) | After the PG matrix run |
| **ai** rest (`TD_STORE_AI`, same switch as settings) | **Complete:** ai_usage ledger + month rollup, tutor quota (D10) with finalise guard, tutor history, erasure; backfill + verify | 10 emulator tests pass (incl. 6 concurrent reservations vs limit 3 -> exactly 3) | After the PG matrix run |
| **security** | **Data path only:** data model for all 15 tables, mappers, backfill + verify. No repository; the module still reads Postgres | 2 emulator tests pass (every table round-trips) | **No** |
| **analytics** | **Data path only:** all 16 tables, mappers, backfill + verify; cost notes. No repository | 2 emulator tests pass | **No** |
| **hub** | Nothing to move: hub has no tables. It reads `identity.User` (SQL) and `web_team` (already Firestore via `core/firestore/website.py`) | n/a | n/a (follows identity) |

## 2. Data model

### audit (plan §3.5)
- `audit_outbox/{uuid7}` — `{id, occurred_at, record_json}`; system family, append-only. `record` is JSON text (JSONB may hold nested arrays; int/float kept).
- `audit_log/{seq:012d}` — every `AuditLog` column; `prev_hash`/`row_hash` hex; `before_state_json`/`after_state_json`; `occurred_at` Timestamp + `occurred_at_s` (RFC 3339 µs, the exact hash input). Read needs `audit.read`; no principal write; append-only.
- `audit_meta/head` — `{seq, row_hash, last_pg_ids}`, written in the same transaction as the appended rows (gap-free `seq`).
- `locks/audit_sealer` lease (single writer); `chain.py` unchanged.
- Writers in a Firestore transaction: `app.modules.audit.repo_firestore.enqueue(tx, actor, action, ...)` (same record as `core.audit.audit()`).

### admin rest
- `privacy_requests/{id}` owned by `user_id` (RLS O; staff `privacy.request.process`); `request_ref` unique via `uniq_privacy_ref`; `export_payload` JSON text.
- `erasure_ledger/{id}` system, append-only, `subject_hash` hex.
- `retention_policies/{id}` shared (`audit.read`), read-only. Postgres stays the source for the `maint.*` SQL until P7; **re-run the backfill after any migration that changes this table.**
- `break_glass_sessions/{id}` shared (`breakglass.activate`). Routes keep their checks; row updates use an optimistic `updated_at` lock (409 `conflict` instead of waiting on `FOR UPDATE`).

### ai rest
- `ai_usage/{id}` system; `cost_estimate` exact NUMERIC text + `cost_micros` int; `month`, `day` (UTC).
- `ai_usage_months/{YYYY-MM}` rollup `{calls, tokens_in, tokens_out, cost_micros, by_feature, by_day}` updated in every reserve/finalise transaction: caps = 1 read; `/admin/ai-usage` = 1 read. It serialises reservations like the `ai.caps` advisory lock did.
- `ai_quota/{user}:{ctx}:{ctx_id}` `{ok, reserved: {usage_id: ts}}` — tutor limit (ok + reservations younger than `RESERVATION_TTL`).
- Finalise guard: the transaction changes a usage row only while `outcome == "reserved"`.
- `ai_tutor_turns/{thread}:{seq:012d}` owned (written only by the `ai.tutor_history` job), `ai_tutor_threads/{thread}` `{next}`. Erasure pseudonymises usage, deletes turns, threads and quota docs.

### security / analytics (data path)
1:1 collections named after the tables, PK as document id (composite -> `compose_id`, `None` -> `-`), ORM column names, kinds derived from the SQLAlchemy model (`admin/fs_rows.py: model_row/register_model`). Families from the RLS comments (see the module docstrings). Volume notes for the repository phase: `analytics_events`/`activity_heartbeats`/`engagement_intervals` must become per-batch documents with TTL (1 write per heartbeat is not affordable); `security_counters` belongs in the rate-limit store; `security_signals`/`risk_evaluations` need TTL `expire_at`. Reports (`security/reports.py`, `analytics/reports.py`) read rollups; their GROUP BYs need maintained counters or rollup jobs — not started.

## 3. Default behaviour unchanged
All new code runs only when `uses_firestore(<module>)` is true. `audit/sealer.seal_once` with every switch on Postgres runs exactly the old `seal_pending` (the Firestore outbox is drained only when `firestore_modules()` is non-empty). `privacy.create`, `load`, `list_own`, `queue` keep the same SQL as before (moved from the router into `privacy.py`). App import smoke test with defaults: OK, `firestore_modules() == ()`.

## 4. How to flip (after the PG matrix run)
```powershell
# audit: stop the sealer first (the chain copy must not race it)
cd apps/api; .venv/Scripts/python -m app.core.firestore.backfill audit admin ai   # backfill + verify, exit 1 on diff
# then TD_STORE_AUDIT=firestore / TD_STORE_ADMIN=firestore / TD_STORE_AI=firestore and restart api, worker, sealer
```
The Postgres `audit_outbox` is not backfilled (td_app has INSERT only): in Firestore mode the sealer keeps draining it into the Firestore chain. Rollback: switch back; Postgres still has the pre-flip rows (F1).

## 5. Files
New: `app/modules/audit/{store_specs,repo_firestore}.py`, `audit/firestore.indexes.fragment.json`; `app/modules/admin/{fs_rows,repo_firestore_privacy}.py`, `admin/firestore.indexes.fragment.json`; `app/modules/ai/{store_specs_usage,repo_firestore_usage}.py`, `ai/firestore.indexes.fragment.json`; `app/modules/security/store_specs.py`; `app/modules/analytics/store_specs.py`; tests `tests/{audit,admin,ai,security,analytics}/fs/*` (emulator-only harness `tests/audit/fs/support.py` overrides the root `migrated_database`), `tests/audit/test_audit_store_matrix.py`.
Changed: `audit/router.py`, `audit/sealer.py`, `admin/store_specs.py`, `admin/privacy.py`, `admin/router.py`, `admin/accounts.py`, `ai/store_specs.py` (imports the usage specs), `ai/store.py`, `ai/router.py`.

## 6. Commands and results (2026-11-12)
```
cd apps/api
TD_TEST_DB_NAME=ops_test TD_TEST_FIRESTORE_AUTOSTART=0 .venv/Scripts/python.exe -m pytest tests/audit/fs tests/admin/fs tests/ai/fs tests/security/fs tests/analytics/fs -q
-> 34 passed in 46.9s
ruff check / ruff format --check (all touched files) -> clean, 58 files formatted
mypy app/modules/{audit,admin,ai} + security/analytics store_specs -> no errors in these modules
  (mypy reports errors in other agents' in-progress files: core/firestore/core_store.py, identity, sessions, rbac, redis)
```
**Not run (Postgres down):** the existing `tests/audit`, `tests/admin`, `tests/ai` suites (both stores via the `admin_backend`/`ai_backend` matrix), `tests/audit/test_audit_store_matrix.py`, the backfill CLI against a real database, `tests/firestore/test_store_boundary.py` (my files import no google/firebase modules — checked by grep).

## 7. Known differences / gaps
1. Cross-store ordering (as P2b): Firestore writes commit before the Postgres audit/idempotency rows of the same request.
2. Privacy and break-glass races answer 409 `conflict` instead of blocking on `FOR UPDATE`.
3. Audit list with `from`/`to` or a family filter filters in memory while paging (exact results; cost grows with the skipped rows). `chain-status` reads the whole log each call (O(n) reads) — consider caching or the nightly verify.
4. Audit immutability on Firestore relies on the hash chain (no triggers/role); anchoring (`audit_anchors`) not built.
5. `uniq_privacy_ref` reservations are not backfilled (refs are random; collision with a backfilled ref is not detected).
6. Transition sealer cross-store re-delivery: guarded by `last_pg_ids` (FS chain) and "id among the newest chain rows" (PG chain); covers one failed delete, not an arbitrary backlog.
7. security and analytics: repositories, report GROUP BYs, the risk engine and ingest are not migrated.

## 8. Requests to other agents
1. **platform (`app/core/audit.py`)**: let `audit()` take a Firestore `ScopedTransaction` and call `app.modules.audit.repo_firestore.enqueue` (or move `build_record` into core and import it there). Until then, modules already on Firestore still write their audit row to the Postgres outbox (committed after the Firestore write).
2. **coordinator**: merge `app/modules/{audit,admin,ai}/firestore.indexes.fragment.json` into `firestore.indexes.json`; run the PG matrix (`tests/audit tests/admin tests/ai`) when Postgres is up.
3. **identity owner**: `hub/router.py` and `admin/privacy.build_export` read identity/sessions/security ORM models directly; they need public read APIs before those modules flip.

---

# Round 2 (2026-11-12): public APIs, security/analytics slices, no-Postgres stack

Owner decisions: no Cloud SQL bridge; every module ends on Firestore; tests run only on the
emulator (`TD_TEST_NO_PG=1`). Defaults are still `postgres` everywhere and nothing was deployed.

## R2.1 Status

| Item | State |
|---|---|
| `public.py` | **Done** for audit, admin, ai and security, plus analytics. They are store-neutral entry points for other modules. Other modules still import internals: `learning/cert_admin.py` imports `admin.repo_firestore`; the `ai.service` and `admin.approvals` imports are covered by re-exports. |
| audit | Complete. Core `audit()` (platform agent) now routes to `repo_firestore.enqueue` / `enqueue_now`, and this is tested inside a Firestore transaction, including the rollback case. The HTTP routes work with no Postgres. |
| admin rest | Complete. Privacy, break-glass, flags and retention routes work over HTTP with no Postgres. The maintenance-mode flag is read from Firestore when there is no Postgres session or engine (`flags.load` / `cached_flag_enabled`). |
| ai rest | Complete. The tutor flow (reserve, fake provider, finalise, history), usage, settings and apps work over HTTP with no Postgres. |
| **security** | **Slice 1 routed:** restrictions and per-user state, which includes the per-request `restriction_state` hook, apply/supersede/end, the user cache, and L3 session revocation through `sessions.public`. Also routed: the SEC-01 learner status route `/me/security/status`, and the admin/support/privacy read helpers in `security.public`. **Not routed:** signals and the risk engine, cases/notes/decisions, unblock requests (apart from reads), rules, incidents, reports, bulk lifts and the retention jobs (about 8k LOC). **Do not flip.** |
| **analytics** | **Slice 1 routed:** the read interfaces other modules call: `get_topic_mastery` (placement, mentoring), the security feeds and H11 learning activity, with eligibility through `identity.public`. **Not routed:** ingest, which should write one batch document plus per-day rollups (cost-safe design in `repo_firestore.py`), the rollup jobs, reports, exports and the consumer. **Do not flip.** |
| hub | Ported. `_user` now goes through `identity.public.get_user`, and the integrations status through `ai.public`. Tested over HTTP with no Postgres. |
| `privacy.build_export` | Ported to `identity.public`, `sessions.public` and `security.public`. The erasure path uses `identity.public.update_user` when identity is on Firestore. |

## R2.2 No-Postgres rules applied in my modules
- When the request session is `NO_POSTGRES` (falsy), `admin.fs_rows.pg_system(session, job)` skips the Postgres system context.
- `emit_any()` writes the Firestore outbox (`core_store.emit_event_firestore`) when there is no session.
- `idem_session()` passes `None` to `core.idempotency.idempotent`. This works around `core_store.idempotent_firestore` calling `session.begin_nested()` on `NO_POSTGRES` (see request 1).
- Security reaches identity and sessions only through `security/adapters.py`, which calls their `public.py`.

## R2.3 Tests (emulator only)
```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=ops_test TD_TEST_FIRESTORE_AUTOSTART=0 .venv/Scripts/python.exe -m pytest \
  tests/audit/fs tests/admin/fs tests/ai/fs tests/security/fs tests/analytics/fs tests/hub/fs -q
-> 53 passed in 50 s
ruff check / ruff format --check (my modules + tests): clean
mypy app/modules/{audit,admin,ai,security,analytics,hub}: no errors in these modules (other agents' files still report errors)
App import with default stores: OK, firestore_modules() == ()
```
The HTTP tests use the real FastAPI app. The request session is `NO_POSTGRES` (`tests/audit/fs/http_support.py`) and FakeAuth handles authentication. They cover:
- AUD-01..03;
- the full privacy lifecycle, the daily create limit, the maintenance-mode 503, flags, retention and break-glass review;
- the tutor flow, AI usage, settings and apps;
- `/me/modules` and `/public/integrations`;
- `/me/security/status`.

Unit tests on the emulator cover the security restriction invariants (concurrent applies leave one active row per family), L3 locks, takeover, step-up, and the analytics readers.

## R2.4 Requests to other agents
1. **platform:** `core_store.idempotent_firestore` checks `session is not None`, so it calls `begin_nested()` on `NO_POSTGRES`. It should test truthiness instead. My routes work around it with `idem_session()`. Also, the emulator sometimes raises `ABORTED: Transaction lock timeout` as a raw `AioRpcError`, which the `run_transaction` retry loop does not catch. I saw it with 4 concurrent restriction applies.
2. **rbac:** add `revoke_grant(session, grant_id, by)` to `rbac.public`. Break-glass `_revoke_grant` still uses `session.get(RoleGrant)`. It is only reached for legacy rows that have a grant, because activation is retired.
3. **support owner:** `support/router.py` still imports `security.models` (`UnblockRequest`, `AccountRestriction`). Switch to `security.public.get_unblock_request` / `user_restrictions(active_only=True)`.
4. **learning owner:** `cert_admin.py` should use `admin.public.patch_flag` instead of `AdminSettingsRepo` / `FeatureFlag`.
5. **coordinator:** merge the index fragments of audit, admin, ai, security and analytics.

## R2.5 What remains before security and analytics can flip
- **security:** the engine and signals (scoring, counters moved to the rate store), cases, decisions and approvals, unblock requests, rules and versions, incidents, notices, reports (19 GROUP BYs need counters or rollups), bulk lifts, retention/purge jobs, and the seeds.
- **analytics:** ingest writing batch documents plus per-day rollups in one transaction, the dirty-day jobs (`jobs.py`), mastery `apply_response`, the reports (H1–H12, k-anonymity), exports with approvals, the consumer, and erasure.

---

# Round 3 (2026-11-12): partial. Security and analytics are NOT fully routed

The coordinator asked for security (engine, signals, cases, notes, decisions, unblock writes,
rules, incidents, notices, bulk lifts, report exports) and analytics (ingest, rollup jobs,
reports, exports) to be fully routed, with identical outputs and HTTP tests for each. **That was
not achieved in this round.**

These parts are about 8k lines of SQL-heavy code in security and about 5k in analytics. They
contain dozens of GROUP BY reports and use approvals, sessions, identity and outbox together.
Porting them with "identical outputs" needs a dedicated pass per file. This round delivered:

| Item | State |
|---|---|
| **INV-12** (data-content request) | Done. `security.public.set_unblock_attachment_scan` and `pending_unblock_attachment_keys` work on both stores, with the same row-count and ordering semantics as the SQL. The Firestore path scans `unblock_requests`, which has low volume (appeals only). `media/adapters.py` can switch to them. |
| **Incidents** (SEC-40..42) | Routed: list, open (unique `incident_ref` via `uniq_incident_ref`) and update (`If-Match` version, timeline, closed_at). Tested over HTTP. |
| `fs_rows.model_row` | Row classes now carry the model's literal `server_default` values (`status='detected'`, `version=1`, `{}`/`[]`, booleans). New Firestore rows therefore match Postgres inserts. Defaults are deep-copied per row. |
| Still on Postgres in security | engine and signals, cases, notes and decisions, unblock writes (create, update, submit, reverify, attachments), rules and versions plus shadow and activation, notices, bulk lifts, report exports and `reports.py`, timeline, retention, `tasks.py` |
| Still on Postgres in analytics | ingest (`service.ingest_batch` / `_process_event`; the batch-document design is in `analytics/repo_firestore.py`), `jobs.py` rollups, `reports.py`, exports and the consumer, mastery `apply_response`, erasure |

**`TD_STORE_SECURITY` and `TD_STORE_ANALYTICS` must stay `postgres`.**

Tests: `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=ops_test ... pytest tests/{audit,admin,ai,security,analytics,hub}/fs -q` gives **55 passed** (58 s). ruff is clean; mypy shows 0 errors in my modules.

`idem_session()` stays until the platform agent's `core_store` truthiness fix lands.

Suggested split for the remaining work, one agent or pass each, each with HTTP tests:

1. **security cases, notes, decisions and unblock** (`cases.py`, `unblock.py`, `api_review.py`, `api_student.py` rest)
2. **security engine and signals** (`engine.py`, `signals.py`, `timeline.py`, counters moved to the `lms_kv` rate store)
3. **security rules, bulk lifts, report exports and `reports.py`** (`controls.py`, `api_engine.py` rest, `reports.py`)
4. **analytics ingest and rollups** (`service.py`, `jobs.py`, `consumer.py`, `mastery.apply_response`), written as batch documents plus per-user-day rollup documents
5. **analytics reports and exports** (`reports.py`, `exports.py`, `export_store.py`)

---

# Round 4 (2026-11-12): security passes 1–3. NOT completed

Analytics was handed over to the data-content agent; from this round I make no edits under `analytics/**`.

**Result: `TD_STORE_SECURITY=firestore` does NOT yet serve every security endpoint and task.
Keep it `postgres`.**

Measured scope of what remains, in database touch points (`session.execute/get/add`) per file:

| File | Touch points |
|---|---|
| unblock.py | 21 |
| cases.py | 19 |
| api_review.py | 22 |
| api_student.py | 9 |
| engine.py | 27 |
| signals.py | 33 |
| controls.py | 24 |
| reports.py | 24 |
| timeline.py | 16 |
| tasks.py | 14 |
| api_engine.py | 11 |

Across security there are 154 `select`s, 31 raw `text()` SQL statements, 12 GROUP BYs and 13 joins. About 45 of the touch points reach identity, sessions or rbac models directly. Each one needs a hand rewrite to a Firestore repository plus the owner module's `public.py` to keep the outputs identical. That did not fit in this round.

Done in round 4 (pass 1 groundwork):
- `repo_firestore.FindRepo.find(coll, row_cls, filters=, order=, limit=)`: a generic single-collection read for the remaining port. Filters run in Firestore; the SQL `ORDER BY ... LIMIT` is reproduced in memory.
- Cases: `cases.case_restriction` and `cases.student_projection` (via a shared `_student_view`, the same output on both stores) and `unblock.own_case_by_ref` are routed. The learner case view `GET /me/security/cases/{case_ref}` works with no Postgres. It shows student-visible notes only, the latest decision and the active restriction, and returns 404 for another user's case. It has an HTTP test.

Security on Firestore today:
- restrictions and user state, including the per-request hook;
- `/me/security/status` and `/me/security/cases/{ref}`;
- incidents;
- INV-12 attachment scan status;
- the read helpers in `security.public`.

Still to port:

| Pass | Status | What remains |
|---|---|---|
| 1 | open | unblock create, update, submit, attachments, reverify and withdraw; case assign, notes and decisions; review queues in `api_review.py`; disown |
| 2 | not started | `engine.py` (evaluation, open_case, notices), `signals.py` (ingest, counters via the `lms_kv` rate store, daily derivation), `timeline.py` |
| 3 | not started | `controls.py` (engine state, kill switch, rule versions with shadow and activation, bulk lifts, report exports), `reports.py` (the GROUP BYs need rollups or counters), `api_engine.py` (the rest), `tasks.py`, `retention.py` |

Tests: `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=ops_test pytest tests/{audit,admin,ai,security,hub}/fs -q` gives **51 passed** (47 s; the analytics tests now belong to data-content). ruff is clean.

Suggestion: run passes 1, 2 and 3 as three parallel agents. Their files are disjoint apart from `repo_firestore.py`, where each can add its own repository class.

---

# Round 5 (2026-11-12): security pass 1 (cases, notes, decisions, unblock, review queues, disown)

Parallel split: pass 2 (engine, signals, timeline) belongs to a new agent and pass 3 (controls, reports, api_engine rest, tasks, retention) to data-money. My new code is in `security/repo_fs_cases.py`. `FindRepo` stays in `security/repo_firestore.py`.

## R5.1 Approach: the pass-1 code is unchanged; its statements run on Firestore
`repo_fs_cases.py` adds `SecSession`, a stand-in for the request session. The decorator `@sec_route` puts it on every route in `api_student.py` (16 routes) and `api_review.py` (30 routes).
- **When it applies:** only with `TD_STORE_SECURITY=firestore`. On Postgres the decorator calls the endpoint unchanged.
- **Unit of work:** each request gets an identity map, so the same document is always the same object. When the endpoint returns, all new and changed rows are written in one transaction with an optimistic `updated_at` check (409 `conflict` instead of waiting on `FOR UPDATE`). An exception writes nothing, like the Postgres rollback.

How each kind of statement is handled:

| Statement | Handling |
|---|---|
| Security tables (single table) | `select`, `update`, `get` and `add` are evaluated against Firestore. Equality and `IS NULL` filters run in Firestore; all predicates are then re-checked in memory with SQL three-valued logic. Also handled: `ORDER BY` with Postgres NULLS LAST/FIRST semantics, `LIMIT`, `count`/`min`/`max`, and `IN (subquery)`. |
| Security joins | `select(A, B / B.col).join(B, B.id == A.fk)` |
| Security GROUP BY | `select(col, count()).group_by(col)` |
| `security_counters` | The `INSERT ... ON CONFLICT` upsert and the `SUM` read become per-bucket documents incremented in a transaction. |
| Other modules' tables | Through their `public.py`: User, UserProfile, UserCredential, Device, AuthSession, LoginAttempt, UserDevice (identity/sessions); ApprovalRequest, RoleGrant (rbac). `update(User)` becomes `identity.public.update_user`. |
| `core.outbox` inserts | Go to the Firestore outbox. |
| RLS GUC statements (`system_context`) | No-ops. GUC reads answer platform scope, which is what the Postgres code runs under. |
| Anything else (raw SQL, other shapes) | Raises `NotImplementedError` with a clear message, so a missed port fails loudly. |

`SecSession` is falsy, like `NO_POSTGRES`, so `pg_system`, `emit_any` and `idem_session` take their Firestore branch.

## R5.2 Tests (emulator, `TD_TEST_NO_PG=1`, through the FastAPI app)
- `test_sx_runner_firestore.py` checks the SQL semantics: IN/NOT IN, NULLS ordering, count, column projection, `update`, and the unit-of-work write.
- `test_unblock_review_http_firestore.py` has three flows:
  1. **Learner unblock:** form (with its rate counter), create draft, duplicate gives 409 `unblock_request_open`, list (join), by-reference (another user gets 404), submit, detail, withdraw. **Reviewer side of the same flow:** case queue with status counts (GROUP BY), case detail, review queue, support triage list (join plus active restrictions), internal note.
  2. **Reviewer case:** claim with `If-Match`, where a stale etag gets 412; unblock-request detail and request-info; restrictions and evaluations lists; manual case creation.
  3. **Decision:** explanation view, student note visible to the learner, claim, timeline view, decision `uphold`. The learner case view then shows the decision.

Combined run: `pytest tests/{audit,admin,ai,security,hub}/fs -q` gives **63 passed** (124 s). ruff is clean.
mypy shows no errors in my files. It reports errors in pass-2/pass-3 files that are still in progress (`engine.py`, `signals.py`, `repo_fs_engine.py`, `repo_fs_controls.py`); those belong to the other agents.

## R5.3 Pass-1 routes
**Covered by HTTP tests:** the 3 flows above.

**Wrapped but not yet exercised by a test:** the runner should handle their statements, but this is unverified.
- Case routes: assign, approval approve/send-back/withdraw.
- Restrictions: restriction create/lift, manual verification.
- Review queue: claim, escalate, send-back, attachment view.
- Support and PII: support forward, pii-reveals.
- Learner routes: disown, responses, appeal, reverify start/complete, attachment upload.
- Evaluation detail, concurrency, device graph.

A statement shape the runner does not cover raises `NotImplementedError`, so these will fail loudly rather than silently diverge. More HTTP coverage is the next step before flipping.

**Jobs:** security tasks (pass 3) and engine calls (pass 2) that run outside a route should wrap their session with `repo_fs_cases.wrap_session(session)` and flush with `await session.commit_fs()`. They may reuse the runner.

## R5.4 Notes for the pass-2 and pass-3 agents
- The runner is generic for every security table in `repo_fs_cases.MODELS`. You can decorate your routes with `@sec_route`, or wrap job sessions with `wrap_session(...)`, instead of hand-porting each statement. Add model shapes to `_foreign_select` only through the owning module's `public.py`.
- **Changing semantics:** GUC reads answer platform scope under `SecSession`. Keep RLS-sensitive checks (`notifications.assert_owner_or_platform`) in mind.
- **Test setup:** tests that touch orgs need `orgs` in `FS_MODULES`, because `orgs.public` receives the stand-in session.

---

# Round 6 (2026-11-12): HTTP tests for every remaining pass-1 route, break-glass, pass-2 requests

## R6.1 Pass-1 routes now covered (FastAPI app, Firestore, no Postgres)
`tests/security/fs/test_pass1_routes_http_firestore.py` has 5 tests:

| Test | Routes and checks |
|---|---|
| unblock review actions | review **claim** (If-Match); **request-info**; learner **responses**; **escalate**; support **forward** (case priority raised to high); review **send-back**. The escalating reviewer gets 403 SoD-06; a second reviewer gets 200 and state `under_review`. |
| assign and decision approvals | **assign**; decision proposal that needs a second approval (`contact_change`) gives 202. Then approval **withdraw**, approval **send-back** by a second reviewer, and approval **approve**. The learner's case view then shows `lift_conditions`. |
| restrictions | **create** L1, duplicate gives 409. **Lift** L1 gives `ended`. Lift L3 gives 409 `decision_required` with the case_ref. **pii-reveals** of a session IP. **Manual verification** of an expired L3 ends it. |
| attachments and reverify | learner attachment **upload** (presigned POST); a non-PDF/PNG/JPG file gives 415. Submit. The scan status is set clean through `security.public`, then the reviewer **attachment view** works. Decision `lift_false_positive` gives lift pending. **reverify start** by e-mail; wrong code gives 400 `otp_invalid`; the right code ends the restriction. |
| appeal and disown | decision `uphold`, then learner **appeal**; a second appeal gives 409. **disown** a notice: another user gets 404, the owner gets `protected`, a repeat gets 409. |

Fixes in the stand-in session (`repo_fs_cases.SecSession`) that these tests needed:
- **Other modules' rows written back.** Rows of other modules read through their `public.py` and then changed by security code are now saved through the owner's API when the request commits: ApprovalRequest via `rbac.public.save_approval`; User, UserProfile and UserCredential via `identity.public.save_*`; AuthSession via `sessions.public.update_session`; UserDevice via `sessions.public.add_user_device`. Without this, an approval withdraw/send-back was lost.
- **Savepoints.** `begin_nested()` now works both awaited and as an `async with` block; the decision proposal uses it.
- **Document ids.** The unit-of-work key now uses the backfill's id rule. Composite primary keys (signals, evaluations) were previously keyed by `id` only.

Test setup notes:
- Security's `has_perm` checks the real rbac catalogue, so these tests seed it with `tests.identity.fs.conftest.seed_catalogue`.
- Case fixtures carry realistic `priority`, `assignee_id` and `panel_views` values.

## R6.2 Break-glass: `rbac.public.revoke_grant`
With rbac on Firestore, `admin/accounts._revoke_grant` calls `rbac.public.revoke_grant`. That call includes the rbac service's audit and the grantee's session rotation. Ending a break-glass session uses the user as actor; the expiry job uses the system actor, and the revoke is recorded in the holder's name. The Postgres path is unchanged.

Test: `tests/admin/fs/test_break_glass_grant_firestore.py`. Ending a break-glass session over HTTP revokes the grant (`revoked_at` and `revoked_by` are set).

## R6.3 Requests from security pass 2 (evidence retention)
- `cases.finalize_decision` (when the case ends `closed`) and `unblock._restore_access` call `repo_fs_cases.evidence_released`. It first writes the unit of work, so the recompute reads the closed case, then calls `repo_fs_engine.release_evidence`.
- **Appeal re-opens a case:** `unblock.appeal` (decided case set to `escalated`) calls `evidence_held`.
- **Other case paths:** no other pass-1 path creates a case outside `engine.open_case`.
- **Signal suppression** (`update(SecuritySignal)...values(suppressed_by_decision_id=...)`) is written with the system job's raw write. Only `suppressed_by_decision_id` may change; any other field raises. All other stored fields, `expire_at` included, are kept.

Tests: `test_pass1_evidence_firestore.py`.
- **Suppression:** the suppressed field is set, `expire_at` and the other fields are unchanged, and changing another field is refused.
- **Close:** decision `close_no_action` closes the case, and the held signal gets an `expire_at` again.

On Postgres both helpers are no-ops.

## R6.4 Pass-2 requests 9 and 10: outbox buffering and the undo journal
- **(a) Outbox events.** `security/restrictions.py` now emits `account.restricted` and `restriction.lifted` through `core.outbox.emit_event` instead of `emit_any`. On the Firebase stack, events are buffered to the commit point (request, or detector scope) and dropped on failure, so they can never be relayed before a rollback. The stand-in session (`SecSession`) also routes `outbox_events` inserts from other security code through the same buffer. Before this change it wrote them immediately.
- **(b) Undo journal.** Restriction rows, family heads and user-state documents are written through `identity.fs_journal.JournalingStore`: `repo_firestore.system_repo`, and in `repo_fs_cases` the unit of work, the runner reads and the rate counters. Inside a `detector_scope` or request journal they are restored automatically on failure. The raw append-only patch of `security_signals` records its before-image in the journal too.
  - `repo_fs_engine.capture_restriction_family` and the other manual captures in pass 2's `detector_scope` are now redundant for these writes. They belong to pass 2, so I left them for that agent to remove.
- **Test:** `tests/security/fs/test_restriction_rollback_firestore.py` has two tests.
  - A detector that fails after an L3 `apply_restriction` and a state write leaves no restriction, no active head, no user-state document, no `account.restricted` outbox document, and the `users.restriction_level` cache unchanged.
  - A successful detector commits the restriction and exactly one event.

## R6.5 Ownership change
Admin now belongs to data-access. The break-glass edit in R6.2 was made before that handover. I have made no admin edits since.

## R6.6 Results
`TD_TEST_NO_PG=1 TD_TEST_DB_NAME=ops_test pytest tests/security/fs tests/audit/fs tests/ai/fs tests/hub/fs tests/admin/fs/test_break_glass_grant_firestore.py -q` gives **95 passed, 1 failed** (218 s).

**The failure is expected, and the fix belongs to pass 2.** `test_fs_engine_service.py::test_failed_detector_truncates_the_request_buffers` asserts the old `emit_any` behaviour, where `account.restricted` was written immediately in its own transaction. Its comment on line 669 still says so.

With request 9 that event is now buffered to the request commit, so `request_commit.commit()` returns **4** (2 audit rows and 2 events) instead of 3. The final outbox content asserted at line 670 is unchanged. The fix is to change `== 3` to `== 4` and update the comment. That file belongs to the pass-2 agent, so I did not edit it.

ruff is clean. mypy shows no errors in my files.

---

# Round 7 (2026-11-12): security cross-module cleanup (cleanup.md §4) and S1

**Scanner:** the same rule as `cleanup.md` §1. It flags (a) an import of another module's `models`, and (b) SQL text naming another module's table. Source: scratchpad `xmod_scan.py`.

| File | Before | After | What changed |
|---|---|---|---|
| api_review.py | 2 | **0** | profile via `identity.public.get_profile`; PII reveal via `sessions.public.get_login_attempt` / `get_session` |
| api_student.py | 1 | **0** | `identity.public.get_user` |
| cases.py | 3 | **0** | `identity.public.get_user`. Approvals via `rbac.public.find_approvals` / `get_approval(for_update=True)`, wrapped in `repo_fs_cases.track_foreign`, so changes made under the Firestore stand-in session are still written back. The conflict-of-interest shared-device count uses `sessions.public.list_user_devices` (reviewer's live devices that the subject also has). |
| unblock.py | 2 | **0** | users, devices and `must_change_password` via `identity.public` / `sessions.public` (`live_only` = `trust_status <> 'removed'`) |
| restrictions.py | 2 | **0** | Both paths now go through `security.adapters`, which uses identity/sessions `public.py`. This covers: users cache plus session scopes, step-up sessions, credential time, `must_change_password`, remember tokens, and L3 revocation via `sessions.public.end_sessions` (same SQL on Postgres as `end_sessions_where`). |
| public.py | 1 | **0** | `restricted_users_by_level` on Postgres: active restriction rows, then `identity.public` for user status (was a JOIN) |
| engine.py | 3 | **0** | users via `identity.public`; `primary_org` via `orgs.public.active_org_ids` (first by id); device verification times via `sessions.public.list_user_devices` |
| timeline.py | 2 | **0** | logins, sessions, observations, OTP tokens, devices and the device graph via `sessions.public` / `identity.public`, with SQL `BETWEEN` kept exactly (inclusive post-filter) |
| controls.py | 1 | **0** | `ApprovalRequest` type from `rbac.public` |
| reports.py | 1 | **0** | H4 network clusters via `sessions.public.list_observations`, aggregated in Python: distinct accounts per cluster, most first, top 100 |
| tasks.py | 1 | **0** | deferred L3 sessions ended via `sessions.public.end_sessions` |
| repo_fs_controls.py | 4 | 4 | **False positives:** the module docstring (line 1) and a docstring at line 398 |
| repo_fs_engine.py | 0 | 1 | **New pass-2 code:** the backfill-only `BACKFILL_EXPIRY_SQL` loader (line 731) reads `retention_policies` from Postgres. That is by design for a backfill. |
| signals.py | 5 | 5 | **Not done** (see below) |
| **Total** | **28** | **10** (5 real, all in signals.py) | |

**signals.py is still open.** It is the pass-2 detector file: about 20 Postgres-path statements on `login_attempts`, `auth_sessions`, `user_devices`, `devices`, `session_network_observations` and `verification_tokens`. They include the AB-04/05 raw SQL and the SH-11 `HAVING count(DISTINCT user_id)` across all accounts' devices, which has no `sessions.public` equivalent yet.
- **Request to pass 2:** switch these PG branches to the `fx`/`sessions.public` helpers they already use on Firestore.
- **Request to data-access:** a `sessions.public.devices_shared_by(min_accounts, since)` helper for SH-11.

**S1 (notifications internals):**
- `repo_fs_engine.notification_created` now uses `notifications.public.created_documents`. This is pass 2's `detector_scope` capture; the edit is minimal and the record order is unchanged.
- `engine.py` and `unblock.py` import `notify`, `send_sms` and `send_email` from `notifications.public`.
- No security file imports `notifications.service`, `store_specs` or `repo` any more.
- `delete_notification` is not needed: the journal deletes the created documents.
- Pass 2 has been told.

**Tests:** `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=ops_test pytest tests/security/fs -q` gives **73 passed** (170 s), run after all the edits. ruff is clean on every touched file. mypy shows no new errors; the remaining ones are pre-existing in pass-2 files (`engine.py` unused ignores, `repo_fs_engine.py`).

---

# Round 8 (2026-11-12): text collation (`app.core.firestore.collation`)

## R8.1 In-memory `ORDER BY`
| Site | Change |
|---|---|
| `security/repo_fs_cases._sort` | `collation.order_key` per column, with the column's NULL placement. This backs the pass-1 statement runner (`sx.*`), the `SecSession` stand-in (security tables, joins, and other modules' rows from their `public.py`), and every pass-1 route. Postgres defaults hold (ASC NULLS LAST, DESC NULLS FIRST), and `.nulls_first()` / `.nulls_last()` are honoured. |
| `security/repo_firestore.FindRepo.find` | `order_key` with Postgres NULL placement; ties broken by id |
| `security/reports._h4` (R7) | Equal counts are ordered by cluster in the VM collation (was `str()`) |
| `ai/store._fs_usage_summary` `by_feature` (SQL `ORDER BY feature`) | `sort_key`. `by_day` stays plain ISO-date order, because the SQL orders a date there, not text. |
| audit, hub | Nothing to change. The audit log orders by `seq`; hub has no ordered lists. |

The SQL `ORDER BY` on Postgres is unchanged. The other `sorted()` calls in these modules are not result orderings: constants, error-message key lists, and backfill loaders whose document order does not matter.

## R8.2 Firestore server-side `order_by` on text
I grepped every `order_by=` in security (my files and pass-2/3 files), audit, ai and hub. **No site orders on a text field.** All of them order on timestamps (`created_at`, `detected_at`, `occurred_at`, `bucket_start`) or integers (`seq`), where byte order equals Postgres order. No sort-key field is needed. The store's implicit `__name__` tie-break only orders ties, which Postgres leaves unspecified.

## R8.3 Tests
- `tests/security/fs/test_collation_order_firestore.py` covers the runner's ASC, DESC (NULLS FIRST), `.asc().nulls_first()` and `LIMIT` cases, plus `FindRepo.find` in both directions. The data has mixed case, accents, punctuation and spaces, and NULLs. Expected order: `a, A, b, co op, co-op, coop, e, é, Zeta, NULL`.
- `tests/ai/fs/test_ai_collation_firestore.py` checks the `by_feature` order: `eval, éval, grading, Grading, path_generation, Zeta`.

## R8.4 Fix found on the way
An import cycle: `security/store_specs` imports pass 2's `repo_fs_engine`, which imported `_all` from `repo_firestore`, which imports `store_specs`. Importing `repo_firestore` first raised `ImportError`. `repo_fs_engine._all` is now a small lazy wrapper; the change is minimal.

**Result:** `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=ops_test pytest tests/security/fs tests/audit/fs tests/ai/fs tests/hub/fs -q` gives **103 passed** (214 s). ruff is clean; mypy shows no errors in the touched files.
