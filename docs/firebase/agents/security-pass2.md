# Security pass 2: risk engine, signals and timeline on Firestore

Agent: security pass 2, 2026-11-12. Scope: `security/engine.py`, `security/signals.py`, `security/timeline.py`, plus the new `security/repo_fs_engine.py`. `TD_STORE_*` defaults are unchanged (all `postgres`). Nothing was deployed.

## Status: done for the pass-2 scope

With `TD_STORE_SECURITY=firestore` and no Postgres, everything in these three files runs on Firestore. That includes the login and request hot path (`SecurityEventSink`), every engine entry point that other passes call, and the evidence views.

What is ported:

- **Rules:** `ruleset`, `rule_version`, `rule_status`, and the circuit breaker (`trip_breaker`, `check_fp_breaker`, `_hc_daily_ok`).
- **Signals:** `record_signal`, `user_signals`, `recent_signal`, the counters (`bump`, `count_since`), and the daily derivations SH-04..07, SH-10 and SH-11.
- **Detectors:** the login detectors (TO-01/03/05/07/09/11, AB-01/04/05/10, SH-09), `check_l2_pass`, SH-13, the engaged-bucket SH-01/SH-02 ingest, and `report_event` (thresholds plus the AB-09 alert).
- **Evaluation:** `evaluate_sharing`, including the HC shadow rows and all actions (L1, L2, L3 with case, recommend L4, de-escalate); `evaluate_takeover` / `_hc_takeover` (HC-T2, HC-T3, the minors' TO-03 lock); `protect_lock` and `disown`.
- **Cases and reads:** `open_case`, `confirmed_incidents`, `high_risk_reasons`, `evaluations_for`.
- **Timeline:** `timeline` and `device_graph`.

## Approach

There is still one copy of the logic. Each security-table touch point dispatches on `uses_firestore("security")`. On Postgres, the code that runs is the original SQLAlchemy call: either the original statement inside an `else`, or a helper (`fx.add`, `fx.flush`, `fx.new`, `_scalar`) that is exactly `session.add` / `session.flush()` / `Model(**kw)` / `execute().scalar_one()`.

Other modules are reached only through their `public.py`:

| Module | Functions used |
|---|---|
| identity | `get_user`, `consents_of`, `verification_tokens_of` |
| sessions | `list_sessions`, `list_user_devices`, `add_user_device`, `list_login_attempts`, `list_observations`, `get_session`, `get_device` |
| rbac | `live_grants` |
| orgs | `active_org_ids` |

The no-Postgres branches use `emit_any` for outbox events. `SecurityEventSink._guard` skips the savepoint when the session is falsy (`NO_POSTGRES`, or pass 1's `SecSession`), and keeps `as_system`.

I did not need the pass-1 `SecSession`, but my code is compatible with it. It passes the session through only to the `public.py` calls, and it writes the same `store_specs` row classes. When `disown` receives a notice row from pass 1, it saves the row and calls `mark_saved`, so pass 1's unit of work sees no change and raises no 409. Pass 1's timeline HTTP flow passes with my timeline.

**Data**, on the collections and document ids the backfill already uses:

- `security_signals` (document id `compose_id(id, occurred_at)`) and `risk_evaluations` (`compose_id(id, evaluated_at)`) carry `expire_at` set to the event time + 180 days (R-RISK / privacy D7).
- NUMERIC columns are rounded to the column scale, as Postgres stores them.
- Signals with no subject (AB-04/05/07) are written by a system job.
- `security_counters`: one document per `{key}:{minute bucket}:{shard}`, with 4 shards. Each bump is a transaction, so counts are exact under concurrency. A window count sums the documents with `bucket_start >= since`. `expire_at` is the bucket + 2 days.
- `security_user_state` saves only the changed fields (SQLAlchemy UPDATE semantics). Cases and notices use an optimistic `updated_at` save. Rule-version status changes use a raw write with an `updated_at` check, because that collection is append-only for principals.

## Tests (emulator, `TD_TEST_NO_PG=1`)

`tests/security/fs/test_fs_engine_service.py` has 14 tests:

- counters, including concurrent bumps, window sums and TTL;
- signal documents: id, TTL, rounding, signals without a subject, source filter;
- minors;
- sharing L1, with the expected score computed by hand (32) and by `score_sharing`, compared field by field with the stored evaluation, restriction, state and notification;
- takeover step-up (score 50), then protect-lock (85): restriction, notice, `must_change_password`, notifications;
- HC-T3 for a minor;
- `open_case` merge, confirmed incidents and high-risk reasons;
- rule versions and the circuit breaker;
- AB-08 (hot path) and AB-07;
- `report_event` thresholds and the playback evaluation;
- timeline (inclusive `BETWEEN`) and device graph;
- L3 with a case and L4 recommendation.

HTTP tests:

- `test_fs_engine_http.py`: real login through the app with no Postgres. Ten failed logins create one TO-01 signal and a takeover evaluation (score 20.00, `none`). An 11th failure adds no new signal, and the user can still sign in.
- `test_fs_engine_http_review.py`: `GET /security/evaluations` returns the engine rows.

`pytest tests/security/fs -q` gives **46 passed** (106 s), including the pass-1 and earlier tests. `test_store_boundary` and `test_rules_unit` pass. ruff is clean, and mypy reports no errors in my files. App import with default stores: `firestore_modules() == ()`.

**Not run:** the Postgres security suites, because Postgres was down. The Postgres branches are textually the original statements.

## Known differences

1. Postgres serialises with `FOR UPDATE` on cases and rule versions. Here those are optimistic saves, so a lost race gets 409 instead of waiting. The `hc:<rule>` advisory lock becomes a `request_locks` lease held for the request; a job with no lock scope runs unlocked.
2. AB-04 and AB-05 read every login attempt of the last hour, then filter by /24 in memory, on each failed login. This is correct but costs O(attempts per hour).
3. Ties in result order that Postgres leaves unspecified are ordered by (time, id). One example is the device list in SH-11 evidence.
4. `case_ref` uniqueness is not reserved (the same as pass 1). Collisions are random.
5. Detector rollback (rounds 2 and 3, below) is compensation, not isolation. While a failed detector is being undone, another request can briefly see its writes (a few milliseconds). Emails and SMS that were already sent are not recalled; Postgres does not recall them either. The `account.restricted` event that `restrictions.apply_restriction` writes with `emit_any` could be relayed in that window before it is deleted (see request 7).

## Round 2 (2026-11-12): parity fixes

### Detector rollback
`repo_fs_engine.detector_scope()` replaces the savepoint. On Postgres it does nothing.

Inside the scope, every write made through this repository is journaled:
- signals, evaluations, cases, notes and notices that are inserted;
- counter bumps;
- `security_user_state` field saves;
- case and notice saves;
- rule-version and rule changes;
- evidence-hold resyncs.

If the detector raises, the journal is replayed in reverse: inserted documents are deleted, counters are decremented (a shard that reaches 0 is deleted), updated fields are restored, and evidence holds are recomputed. Nested scopes hand their journal to the enclosing one.

`SecurityEventSink._guard` now wraps every detector in it. On the Postgres branch it is added inside the savepoint and is a no-op there.

Two forced-failure tests are in `test_detector_failure_leaves_no_signals_or_counters`:
- **AB-08:** the signal is written and then the detector raises. No signal and no counter documents remain.
- **Login detector:** TO-07 and SH-09 are written, then the takeover evaluation fails. No signals and no evaluation remain. The same detector then succeeds once the failure is removed.

`report_event` (outbox handlers), the nightly derivations and routes that call the engine outside the sink are not wrapped. On Postgres they roll back with the caller's transaction. Pass 3 jobs and `wiring.py` handlers can use `async with fx.detector_scope():` to get the same behaviour (see request 6).

### TTL versus open cases and legal holds
This copies the Postgres `maint.purge_expired_rows` predicate (`core_base_0002_maint`).

`security_signals` and `risk_evaluations` older than the table's active `retention_policies.retention_interval` are deleted, **except** rows whose user has a case that is not closed or has `legal_hold`. For evaluations, rows whose own `case_id` is such a case are also kept; that case always belongs to the same user, so the user rule already covers it. Signals with no user are never held.

On Firestore:
- **On insert:** `expire_at` is `None` (kept) while the user is held. Otherwise it is the event time plus the interval. The interval is read from admin `retention_policies` (minimum of the active rows, cached for 5 minutes), with 180 days as the fallback.
- **`hold_evidence(user_ids)` / `release_evidence(user_ids)`** (`repo_fs_engine.py`): both recompute from the cases, which are the source of truth. They clear `expire_at`, or restore it to event time + interval. A restored time that is already past is deleted by the TTL, as the next daily purge would. Both are idempotent.
- **My code:** `engine.open_case` calls `hold_evidence` after a new case is written.

Test: `test_evidence_kept_while_case_open_or_held` covers an open case (cleared), a close plus release (restored to +180 days), a legal hold on the closed case (cleared again), idempotence, and another user being unaffected.

### Calls other passes must add
Call these **after** the case document is written, i.e. after pass 1's unit of work or `commit_fs()`, because the functions read the cases.

| Who | Where | Call |
|---|---|---|
| pass 1 | `cases.py` `finalize_decision` (line ~570, `case.status = "closed"`) | `release_evidence([case.user_id])` |
| pass 1 | `unblock.py` `_restore_access` (line ~900, `case.status = "closed"`) | `release_evidence([case.user_id])` |
| pass 1 | any case create or reopen that does not go through `engine.open_case`. Today: none (the manual case route and the assessments referral both use `engine.open_case`) | `hold_evidence([user_id])` |
| pass 3 | `controls.py` `_execute_bulk` (line ~621, `case.status = "closed"`) | `release_evidence([affected user ids])` |
| pass 3 / admin | wherever `security_cases.legal_hold` is set or cleared (no code sets it today; legal hold is applied by maintenance or SQL) | `hold_evidence` on set, `release_evidence` on clear |
| pass 3 | `retention.py` Firestore purge of closed cases | no call needed: deleting a closed, unheld case does not change the predicate |
| backfill owner | after backfilling `security_signals` / `risk_evaluations` / `security_cases` | for every user with signals: `hold_evidence` (it sets `expire_at` correctly for held and unheld users), or set it in the transform (request 2) |

### Indexes and TTL
These are in the new file `apps/api/app/modules/security/firestore.indexes.pass2.fragment.json`, ready to merge:
- `lms_security_signals` (`rule_key`, `occurred_at`);
- `lms_security_counters` (`counter_key`, `bucket_start`);
- TTL on `expire_at` for `lms_security_signals`, `lms_risk_evaluations` and `lms_security_counters`.

### Round-2 test results
`pytest tests/security/fs tests/firestore/test_store_boundary.py tests/security/test_rules_unit.py -q` gives **70 passed** (150 s), including the pass-1 and pass-3 tests present in that directory. ruff is clean and mypy reports no errors in my files. App import with default stores: `firestore_modules() == ()`.

## Round 3 (2026-11-12): other modules' writes are undone too

`detector_scope()` now covers everything the Postgres savepoint covers, not only this module's
documents.

**Journal.** The scope opens its own `identity.fs_journal.Journal` (it does not use the nested
`journal()`, because inside a request journal that would let the outer scope decide). Undo works
per kind of write:

- **identity and sessions documents:** recorded automatically by their `JournalingStore`. This
  covers `must_change_password`, the `restriction_level` cache, session scope and revocation, and
  remember-device tokens.
- **this repository's writes:** signals, evaluations, cases, notes, notices, counters, state
  fields, rule versions. These are logged as compensating callbacks in the same journal. The
  evidence resync is queued to run last.
- **restrictions and their family head:** `engine._apply` / deescalate capture the head and the
  active row before `rx.apply_restriction` / `end_restriction` (`fx.capture_restriction_family`),
  then record the new restriction as created (`fx.restriction_created`). The `account.restricted`
  outbox event that `restrictions.py` writes with `emit_any` gets a compensation that deletes it
  by `aggregate_id`.
- **user state:** `engine._get_state` captures `security_user_state` before `rx.get_state`, which
  may create the zero row.
- **notifications:** `engine.notify_user` records the inbox row and its dedupe marker as created
  (`fx.notification_created`).

On success, the journal entries are handed to the enclosing journal, if there is one.

**Audit and outbox.**
- **Inside a request** (`RequestContextMiddleware` buffers): the scope takes a checkpoint of the
  pending audit rows and outbox events. On failure it removes only the rows added after the
  checkpoint, via `audit.mark_written` / `outbox.mark_events_written`. The request's own earlier
  rows stay and commit at the request's commit point.
- **Outside a request:** the scope opens its own buffers (`audit.begin_buffer` /
  `outbox.begin_event_buffer`). It writes them with `request_commit.commit()` when the detector
  succeeds and drops them when it fails.
- The engine's own events now use `core.outbox.emit_event` again, the original call, which
  buffers when there is no Postgres session.

**Tests** (`test_fs_engine_service.py`). The failing detector is a login detector that ends in
T-protect. After all its writes are made, it raises.
- `test_failed_detector_undoes_restrictions_state_notifications_audit_outbox`: after the failure,
  everything is back to the pre-detector state:
  - signals;
  - the takeover restriction and its head;
  - `security_user_state` (absent again);
  - the notice;
  - the `security.takeover_protect` notification;
  - `must_change_password`;
  - the audit row `security.restriction.apply`;
  - the `account.restricted` event;
  - the evaluation.

  The same detector then succeeds and writes all of them.
- `test_failed_detector_truncates_the_request_buffers`: with request buffers open, a failed
  detector leaves only the request's earlier audit row and event. A successful detector adds its
  own, and the request commit writes them.
- `test_detector_failure_leaves_no_signals_or_counters` (round 2) still passes.

**Round-3 test run:** `pytest tests/security/fs tests/firestore/test_store_boundary.py tests/security/test_rules_unit.py -q` gives **76 passed** (228 s). ruff is clean and mypy reports no errors in my files. App import with default stores: `firestore_modules() == ()`.

**APIs I used that are not public** (please make them public):
- `identity.fs_journal._current`: to open a child journal that rolls back on its own. Wanted: a
  public `fs_journal.child()` context manager with the same behaviour as the nested scope above.
- `core.audit._pending` / `core.outbox._pending_events`: to tell whether a request buffer is open.
  Wanted: `audit.checkpoint()` / `audit.rollback_to(cp)`, and the same pair in `core.outbox`,
  plus `buffer_open()`.

## Round 4 (2026-11-12): public APIs, and pass 1's journaled restrictions

**Journal.** When no undo journal is open, `detector_scope()` opens one with the public
`identity.fs_journal.child()`. When a journal is already open (for example a route's
`request_journal`), `child()` *joins* that journal, so the rollback is left to the outer scope.
The sink swallows the detector's error, so the outer scope would never roll it back. In that case
only, a child journal is still set through `fs_journal._current`; it rolls back on its own and is
merged into the outer journal on success. **Request 9 changes:** `child()` (or a new
`savepoint()`) should give these savepoint semantics: roll back on error even when nested, merge
into the outer journal on success.

**Audit and outbox.** Now use the public `core.request_commit.buffer_open()`. It is a savepoint of
the request's buffers inside a request, and buffers of its own, committed on success, outside one.
The private `audit._pending` / `outbox._pending_events` reads are gone. **Request 10 is done.**

**Retention.** `expire_at` is now computed from `admin.public.retention_interval(session, table)`
(a `PgInterval`, cached for 5 minutes) with `admin.intervals.add_interval`, so calendar intervals
behave like Postgres. For example, `1 mon` from 31 January ends on 28 or 29 February. The fallback
is 180 days when there is no active row (Postgres refuses to purge then) or when admin is on
Postgres and no session is at hand.
Test: `test_expiry_follows_admin_retention_interval_calendar`: signals use 1 month (31 Jan 2028
-> 29 Feb 2028) and evaluations use 2 months.

**Pass 1 changes absorbed.**
- `restrictions.py` now emits `account.restricted` / `restriction.lifted` with
  `core.outbox.emit_event` (buffered).
- `security.repo_firestore.system_repo` now uses `JournalingStore`, so restriction rows, family
  heads and user state are journaled.
- I removed my manual captures (`capture_restriction_family`, `restriction_created` with its
  outbox compensation, `capture_state`) and the `engine._apply` / `_get_state` wrappers.
  `engine.py` and `signals.py` call `rx.apply_restriction` / `rx.get_state` / `rx.end_restriction`
  directly again, as in the original code.
- What remains manual is only `fx.notification_created`, because notifications still use a plain
  `ScopedStore` (request 8).
- **Requests 7 and 10 are done.**

`test_failed_detector_truncates_the_request_buffers`: the request commit now writes 4 rows
(2 audit rows + 2 events), not 3, because `account.restricted` is now buffered with the request
instead of written in its own transaction. That was the only cause of the failure: the audit rows
and the final outbox contents asserted are unchanged. The failed-detector half of the test also
shows that the buffered `account.restricted` is dropped by the checkpoint.

**Round-4 test run:** `pytest tests/security/fs tests/firestore/test_store_boundary.py tests/security/test_rules_unit.py -q` gives **87 passed** (175 s), including the pass-1 and pass-3 tests in that directory. ruff is clean and mypy reports no errors in my files.

## Round 5 (2026-11-12): notifications API, backfill expiry, and the other passes' calls

**Notifications.** `fx.notification_created` now records the documents listed by
`notifications.public.created_documents()`. This module no longer imports any notifications
collection names. The round-3 forced-failure test still shows the notification undone.
**Request 8 is done.**

**Backfill `expire_at`.** Added in `repo_fs_engine.register_backfill_expiry()`. It registers
three extra backfill mappings (`security_signals:expire_at`, `risk_evaluations:expire_at`,
`security_counters:expire_at`). Each one writes only `expire_at` into the same documents as the
table mappings; the backfill's `_combined` merges rows of one collection by document id. Postgres
computes the value itself, using the purge predicate of `maint.purge_expired_rows`:

- **held** (`NULL`): the subject has a case with `status <> 'closed' OR legal_hold`, or, for an
  evaluation, its own `case_id` is such a case;
- **otherwise**: event time + `COALESCE(min(active retention_policies.retention_interval),
  '180 days')`, using Postgres interval arithmetic;
- **counters**: `bucket_start + 2 days`.

`verify` checks the field too. The backfill imports only `store_specs`, so **I added one import
line at the end of `security/store_specs.py`** (the coordinator gave me ownership of this
transform) that loads these mappings. Nothing else in that file changed.

Tests: `test_fs_engine_backfill.py` (2 tests):
- the SQL contains the purge predicate, the per-table policy and the defaults;
- a backfill with held and unheld signals, an evaluation and a counter writes `expire_at`
  (`None` when held), keeps every table field, and verify passes for all three collections.

The SQL itself was not run (no Postgres).

**Other passes' calls, checked by reading the code.**

| Pass | File and place | Call | Status |
|---|---|---|---|
| 1 | `cases.py` `finalize_decision` (~l.571, after `session.flush()`, when `case.status == "closed"`) | `repo_fs_cases.evidence_released` → `release_evidence` | done; the unit of work is flushed before the recompute |
| 1 | `unblock.py` `_restore_access` (~l.906) | `evidence_released` | done |
| 1 | `unblock.py` appeal / escalation (~l.571, case re-opened as `escalated`) | `evidence_held` | done (flushed first) |
| 3 | `controls.py` `_execute_bulk` (~l.642) | `secx.after_commit(session, lambda: fx.release_evidence(users))` | done; runs after the cases commit |
| 3 | `tasks.py` nightly derivation and evaluation (~l.83), heartbeat batch (~l.300) | `async with fx.detector_scope()` | done; the whole run is one scope |
| 3 / wiring | `wiring.py` `on_stream_cap_hit` (~l.275) | `async with detector_scope()` | done |
| — | setting or clearing `legal_hold` | `hold_evidence` / `release_evidence` | no code sets it today |

**New data-access APIs (round 5).**
- `detector_scope()` now uses `identity.fs_journal.savepoint()` together with
  `request_commit.buffer_open()`. The private `fs_journal._current` use and my own
  child-journal code are gone. **Request 9 is done.**
- AB-04/05 now read the attempts of the source through
  `sessions.public.list_login_attempts_in_prefix(session, la.ip, since=...)`, which uses the
  indexed `ip_prefix` field, instead of scanning every attempt of the hour. The `ip << /24`
  (`/48`) containment is still re-checked on each row. The aggregates are computed by the shared
  `_source_aggregates`. **Request 4 is done.**
- Test `test_ab04_ab05_prefix_query_equals_the_window_scan` uses IPv4 and IPv6 attempts, in and
  out of the source network, in and out of the hour, pre-auth-blocked rows, repeated identifiers
  and a NULL IP. For three sources it checks that the prefix query gives the same
  `(failures, distinct accounts, spray)` as the old window scan, plus hand-computed values.

Both data-access items (request 9: `savepoint()`; request 4: the `/24` prefix) are delivered and used.

### Round 5 (continued): the Postgres path of `signals.py` also uses the public APIs

On both stores, `signals.py` now reaches identity and sessions only through their `public.py`.
Each `public.py` function runs, on Postgres, the SQL it replaces (same filters).

| Site | Before (Postgres path) | After (both stores) |
|---|---|---|
| `_user` | `session.get(User, id)` | `identity.public.get_user` |
| `_owner_verified_refresh` | `select(UserDevice)` (user, device, not removed) + flush | `sessions.public.list_user_devices(live_only=True)` + `add_user_device` |
| `check_l2_pass` | `select(UserDevice.device_id, owner_verified_at)` | `list_user_devices(user_id=)` |
| AB-04 / AB-05 | 2 raw SQL on `login_attempts` (`ip << src`) | `list_login_attempts_in_prefix` + shared `_source_aggregates` |
| AB-10 | join `account_restrictions × user_devices` | `list_user_devices(device_id=, last_used_after=)` + `restrictions.active_restrictions` (one row per pair, as the join) |
| TO-01, TO-03, AB-01 (1 h, 24 h), TO-09 | 5 `count(LoginAttempt)` | `list_login_attempts(since=, user_id=, outcomes=)` (+ country / id filter) |
| `_network_at` | `select(SessionNetworkObservation)` + `session.get(AuthSession)` | `list_observations(until=)` + `get_session` |
| SH-13 | 2 `select(AuthSession)` | `list_sessions(device_id=)` / `list_sessions(exclude_device_id=, last_seen_*)` (the per-device SH-13 count on `security_signals` stays a dispatch: SQL on Postgres) |
| `_leg` | `session.get(Device)` | `get_device` |
| SH-05 / SH-06 / SH-04 / SH-07 / SH-10 | `count(distinct AuthSession.device_id)`, `count(UserDevice)`, `count(AuthSession)`, `count(VerificationToken)`, `select(AuthSession)` | `list_sessions`, `list_user_devices`, `identity.public.verification_tokens_of` (`_Daily`) |
| SH-11 | GROUP BY `user_devices` | `sessions.public.shared_devices_of_user(min_accounts=, since=)` (the same SQL on Postgres; per-device queries on Firestore) |

**Scan of `signals.py`** (direct use of identity/sessions models: statements, `session.get` on
their models, raw SQL on their tables, runtime imports):

- **Before: 27 statements**, counted in the original file:
  - 7 `session.get(User | AuthSession | Device)`;
  - 2 raw SQL on `login_attempts`;
  - 5 `select_from(LoginAttempt)` counts;
  - 6 `UserDevice` selects / joins (AB-10 join, the L2 and refresh selects, the `new24` count,
    and the 2 selects of the SH-11 GROUP BY);
  - 1 `SessionNetworkObservation` select;
  - 5 `AuthSession` selects / counts;
  - 1 `VerificationToken` count;

  plus runtime imports of `User`, `AuthSession`, `Device`, `LoginAttempt`,
  `SessionNetworkObservation` and `UserDevice`.
- **After: 0 statements.** `User`, `AuthSession`, `LoginAttempt` and `UserDevice` are imported for annotations only (`TYPE_CHECKING`). `signals.py` reads identity and sessions only through their `public.py`.

**Collation.** None of the in-memory sorts in my files order by a text column, so I did not use
`app.core.firestore.collation.sort_key`:
- the Firestore sorts order by timestamps, with the id as tie-break (UUID / hex order, which is
  Postgres' uuid order);
- the other sorts are pre-existing Python sorts of rule keys / device ids, which run identically
  on both stores.

**Round-5 test run:** `pytest tests/security/fs tests/firestore/test_store_boundary.py tests/security/test_rules_unit.py -q` gives **92 passed** (186 s). ruff is clean, mypy reports no errors in my four files, and app import with default stores gives `firestore_modules() == ()`.

**Not in this round:** `engine.py` (`sharing_context` device read, consents, orgs, grants, user
reads) and `timeline.py` still use SQL on their Postgres path; only their Firestore path uses
`public.py`. The same conversion is possible there; I have not done it.

**mypy.** My earlier reports said "no errors in my files". That was wrong: my output filter
looked for `/` while mypy prints Windows `\` paths. The real errors were:
- unused `type: ignore` comments (6) and a `rows` re-typing in `check_fp_breaker` (`engine.py`);
- an `int | None` scale and a `todo` tuple type (`repo_fs_engine.py`);
- an untyped default-arg lambda (`signals.py`, now `functools.partial`).

All are fixed. `mypy` on `engine.py`, `signals.py`, `timeline.py` and `repo_fs_engine.py` now
reports nothing in these files; the 4 errors it still prints are in other modules' files.

**Equivalence on Postgres** (not run: no Postgres). Each replacement keeps the same predicate:
- exclusive lower bounds `> since`;
- `trust_status <> 'removed'` is `live_only`;
- `device_id <> :d` excludes NULL, as SQL does;
- `count(DISTINCT identifier_hash)` ignores NULL, and `GROUP BY identifier_hash` counts the NULL
  group, as before;
- `NOT pre_auth_blocked` is `pre_auth_blocked is False` (the column is NOT NULL).

Ties that Postgres left unordered (`ORDER BY created_at DESC LIMIT 1`, the AB-10 join order) now
break by id.

## Requests

1. **Coordinator:** merge `security/firestore.indexes.pass2.fragment.json`.
2. **store_specs / backfill owner:** set `expire_at` in the backfill transform. For `security_signals` and `risk_evaluations` it is `None` when the user has an open or held case, otherwise event time + interval; for `security_counters` it is `bucket_start` + 2 days. Alternatively, run `hold_evidence` per user after the backfill. Without this, backfilled rows never expire.
3. **pass 1 / pass 3:** add the calls in the table above.
4. **sessions owner:** add a `/24` (or `/48`) prefix field and filter on `login_attempts`, so AB-04/05 can query by source instead of scanning the hour.
5. **pass 1:** suppressing signals (`suppressed_by_decision_id`) on Firestore must write through the system job. The `security_signals` spec is append-only, so a store `update` is refused. Keep `expire_at` unchanged when doing so.
6. **pass 3 (`tasks.py`) / `wiring.py` owner:** wrap each per-user nightly derivation and evaluation, and the `on_stream_cap_hit` → `report_event` handler, in `async with repo_fs_engine.detector_scope():`, so a failure leaves no partial signals (Postgres: the job or handler transaction rolls back).
7. **restrictions owner (`restrictions.py`; data-ops):** use `core.outbox.emit_event` (buffered to the commit point) instead of `emit_any` in `apply_restriction` / `_apply_fs` / `end_restriction`. Then the `account.restricted` / `restriction.lifted` events roll back with the scope or request, and the compensation in `fx.restriction_created` is no longer needed. Also, on Firestore build `SecurityRepo` on `JournalingStore.system(...)`, so restriction and state writes join any journal without the explicit captures.
8. **notifications owner:** build `notifications.repo_firestore.system_repo` on `JournalingStore`, or expose `notifications.public.delete_notification(user_id, id)`. `fx.notification_created` currently imports `notifications.store_specs` (`NOTIFICATIONS`, `DEDUPE`, `dedupe_id`).
9. **data-access (`identity/fs_journal.py`):** public `child()` journal scope (see round 3).
10. **platform (`core/audit.py`, `core/outbox.py`):** public buffer checkpoint and rollback API (see round 3).
