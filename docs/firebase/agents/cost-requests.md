# Firestore cost of the student request path (2026-11-13)

Scope: the student request path. That covers `lms_edge` (BFF), core middleware, the session
resolver and principal, rbac, rate limits (`lms_kv`), idempotency, and the read paths of the
dashboard, hub, My learning, catalogue, course page, lesson and notifications. The analytics rate
limiter and `touch_engaged` were added at the coordinator's request.

Out of scope: scheduled jobs, Cloud Tasks, outbox and audit seal (scheduler agent), and media,
playback and analytics ingestion beyond the rate limit and the session touch (media agent).

The hard rule held: no feature or behaviour changed or was removed, only the cost. Nothing was
deployed and `apps/web` was not touched.

## How it was measured

`functions-lms/tools/request_cost_probe.py` is new. It builds on the scheduler agent's
`firestore_cost_probe.py`, which it imports and does not modify.

Billed operations are counted at the gRPC (GAPIC) level of `google-cloud-firestore`'s async
client, using these billing rules:

| RPC | Billed as |
|---|---|
| RunQuery | 1 read per returned document; a query with no results bills 1 read |
| RunAggregationQuery | 1 read per 1000 index entries started |
| BatchGet | 1 read per requested document |
| Commit | 1 write, or 1 delete, per write |

`--sites` adds the call site behind every operation, which is how the waste below was found.

The probe runs the whole Firebase request path in-process against the Firestore emulator
(127.0.0.1:18080, project `demo-costreq`):

- `lms_edge.EdgeApp` (packed `__session` cookie, CSRF double submit) in front of
  `app.main.create_app()`;
- every module on Firestore, `TD_CACHE_BACKEND=firestore`, and the live testing switch
  `TD_SIMPLE_AUTH=true`;
- Cloud Tasks enqueues counted but not sent.

Seed data:

- the role catalogue, plus admin and student from `seed_emulator.py`;
- a second admin, needed to publish because of separation of duties;
- a 3-lesson article course, authored and published through the studio API;
- the student also grants 3 optional consents, as a self-signup adult does.

**Per request:** each request is measured 3 times in one session. The "steady" figure is the third
call.

**Student-hour:** request by request, on a shifted clock, so session idle and last-seen
bookkeeping, reading-time checks and rate-limit windows all see the hour pass. The traffic is taken
from the SPA's own code (file:line references are in the probe docstring):

| Part of the hour | Requests |
|---|---|
| App open | `_bff/session`, hub `me/modules`, shell (`me`, `me/grants`, `me/enabled-apps`, bell), dashboard (`me/dashboard`, `me/tests`, `me/admissions`, `me/classes`, `public/courses/status`), `analytics/config` |
| NotificationBell | every 120 s while visible, and on every route change: 49 requests |
| Lessons | 12 article lessons of about 5 min each: `catalog/courses/{slug}`, `me/courses/{id}`, the lesson, a completion POST; every 4th lesson goes through the course page; `me/enabled-apps` is fetched again when the sidebar remounts |
| Other pages | My learning ×2, catalogue ×1, notifications page ×1 |
| Analytics | `POST analytics/events` every 30 s (2 heartbeats, tracker 15 s / 30 s): 119 requests |

Totals: 120 request-path requests plus 119 analytics requests.

**Before/after:** "before" is the same probe with the pre-change modules loaded in place of the
working tree (`--baseline DIR`, with a `manifest.json` of module → file).

```
cd apps/api
.venv/Scripts/python ../../functions-lms/tools/request_cost_probe.py --sites --json out.json
.venv/Scripts/python ../../functions-lms/tools/request_cost_probe.py --project demo-costreq-base --baseline <dir> --json base.json
```

## Results

### Per request (steady state, reads / writes)

| Request | Before | After |
|---|---|---|
| `_bff/csrf`, `_bff/session` (edge only) | 0 / 0 | 0 / 0 |
| POST auth/login (+ CSRF bootstrap, 4th sign-in) | 66 / 18 | 63 / 18 |
| GET me | 10 / 0 | 8 / 0 |
| GET me/grants | 8 / 0 | 8 / 0 |
| GET me/enabled-apps | 15 / 0 | 12 / 0 |
| GET me/notifications (bell unread poll) | 9 / 0 | 9 / 0 |
| GET me/modules (hub) | 9 / 0 | 8 / 0 |
| GET me/dashboard (enrolled) | 21 / 0 | 18 / 0 |
| GET me/tests | 17 / 0 | 14 / 0 |
| GET me/admissions | 17 / 1 | 12 / 1 |
| GET me/classes | 14 / 0 | 11 / 0 |
| GET analytics/config | 19 / 0 | 16 / 0 |
| GET /api/public/courses/status | 4 / 1 | 3 / 1 |
| GET catalog/courses?limit=50 | 1 / 0 | 1 / 0 |
| GET catalog/courses/{slug} | 9 / 0 | 7 / 0 |
| POST me/enrolments | 21 / 6 | 16 / 6 |
| GET me/enrolments?limit=100 | 16 / 0 | 13 / 0 |
| GET me/courses/{id} | 25 / 0 | 20 / 0 |
| GET me/courses/{id}/lessons/{id} | 22 / 1 | 19 / 1 |
| POST me/lessons/{key}/completion | 18 / 1 | 15 / 1 |
| GET me/notifications?limit=20 | 9 / 0 | 9 / 0 |
| POST auth/logout | 11 / 3 | 10 / 3 |
| POST analytics/events (2 heartbeats, hour average) | 18.0 / 4.6 | 11.8 / 2.5 |

### One student-hour of study

| | Reads | Writes |
|---|---|---|
| Request path, before | 1,710 | 46 |
| Request path, after | 1,509 | 48 * |
| Analytics POSTs, before | 2,137 | 545 |
| Analytics POSTs, after | 1,409 | 301 |
| **Total, before** | **3,847** | **591** |
| **Total, after** | **2,918 (−24 %)** | **349 (−41 %)** |

\* The two extra writes come from the scheduler agent's in-progress `jobhints` hook, which was
live in the working tree during the "after" run. They are not from this change.

The probe did not run playback (its fake video asset needs the media stack). During video, the
media heartbeat calls the same `touch_engaged`, and the analytics flushes are the same POSTs, so
the savings apply there too. That is the coordinator's "about 480 rate-limit writes per viewing
hour": it falls to about 240.

### How many students fit in the free tier

The free tier is 50k reads, 20k writes and 20k deletes a day, for the whole project. The website,
the college portal and the scheduled jobs share it.

| | Student-hours per day (reads bind) | One 1-hour study session + 1 sign-in |
|---|---|---|
| Before | 50,000 / 3,847 = 13.0 | about 12.8 students a day |
| After | 50,000 / 2,918 = 17.1 | about 16.8 students a day |
| Writes (after) | 20,000 / 349 = 57 | — |

These figures are the upper bound if this LMS had the whole quota. Reads are the binding limit.
Take off whatever the website, the college portal and the scheduler use. A student who only opens
the dashboard and one lesson, about 15 requests, costs about 180 reads, so about 270 such light
visits fit in a day.

Where the remaining reads go:

- **About 10 reads on every authenticated request.** The session resolver costs 7: session by
  token, device, user, restrictions, grants, org memberships and MFA factors. Most of these are
  "empty query = 1 read" lookups. The consent gate costs 3.
- **Volume.** 239 requests an hour, half of them analytics flushes.

See "Next levers" below.

## What changed and why it is behaviour-neutral

1. **Request-scoped read memo** (`app/core/firestore/request_memo.py`, hooks in `store.py` and
   `middleware.py`).
   - **What it does:** inside one HTTP request, a second read of the same document is served from
     the first read. This covers `users`, `user_profiles`, `auth_sessions`, `devices`, `courses`,
     `courses_by_slug`, `course_versions` and `lessons`. A query on `consents` is also
     memoised.
   - **Lifetime:** the memo is created by `RequestContextMiddleware` and dropped in its
     `finally`. Nothing is shared across requests, so there is no staleness for revocation,
     logout, restrictions or permissions.
   - **Exclusions and invalidation:**
     - Reads inside a transaction never use the memo.
     - Any write staged through the store (all transaction writes, `create`, `import_documents`,
       `delete_all`) forgets that document and every memoised query on its collection.
     - Taking a lease or request lock clears the whole memo, so lock-serialised code re-reads
       after it holds the lock.
     - Values are deep-copied in and out.
   - **The only difference:** a repeat read in the same request returns what the first read
     returned, not a commit that landed milliseconds in between. That is indistinguishable from
     the two reads running together.
   - **Saves:** 1–3 reads on `me`, `me/modules`, `me/admissions`, course pages and lessons.

2. **Consent gate reads only the 3 required purposes**
   (`sessions/hooks.py`, `identity/service.current_consents(…, purposes)`,
   `identity/repo_firestore`).
   - **What it does:** the per-request check used to read the user's whole consent ledger: all
     purposes, all history, growing with every toggle. It now queries
     `purpose in (terms, privacy_notice, core_service)`. The latest-row-per-purpose logic is
     unchanged, so the answer is identical. A withdrawal is seen on the next request.
   - **Safety net:** the query uses equality plus `in`, which needs no composite index. If the
     project still refuses it, the code falls back to the full read and logs it.
   - **Saves:** 3 reads per request for this seed (6 rows down to 3), more for users with a
     longer ledger.

3. **Rate-limit window counters without a read** (`firestore/kv.py`).
   - **What it does:** `app.core.ratelimit` keys (`rl:<key>:<window>:<index>`) are counted with a
     batch of server-side `Increment(1)` writes. The new count comes back in the commit response.
     This replaces a transaction that did one read plus one write per key.
   - **Why the counts are exact:** a window key is only used inside its own window, and its
     `expire_at` is the window end plus 1 s. So the old "expired → start from 0" branch could
     never apply to it.
   - **Other keys:** keys that are not windows, such as the Google ID-token replay guard, keep
     the old transaction, including expiry restart.
   - **Compatibility:** `peek` reads both the new field `n` and the old field `v`.
   - **Saves:** 1 read per rate-limited key.

4. **Colocated analytics counters** (`ratelimit.check_colocated`, `kv.incr_colocated`,
   `analytics/service.enforce_rate_limits`).
   - **What it does:** these counters now share one `lms_kv` document per user per minute, as
     separate fields:
     - session per minute (`anl:s`);
     - session burst, 10 s windows (`anl:sb`);
     - user per minute (`anl:u`).

     A session always belongs to its user, and 10 s windows nest in the epoch-aligned minute. The
     IP counter stays in its own document because it is shared across users.
   - **What stays the same:** the limits, the counts, the order in which counters are
     incremented, the first-exceeded 429, and fail-open on an outage. The Redis and memory
     backends fall back to separate `check` calls.
   - **Saves:** analytics POSTs go from 4 writes and 4 reads to 2 writes and 0 reads.

5. **`touch_engaged` skips writes that change nothing** (`sessions/resolver.py`).
   - **What it does:** the write is skipped only when the idle expiry cannot move (it is already
     capped at the absolute expiry, as under `TD_SIMPLE_AUTH`) **and** `last_seen_at` is less than
     60 s old.
   - **Why it is neutral:** 60 s is the granularity every other request already keeps
     `last_seen_at` at (`_touch` / `LAST_SEEN_WRITE_INTERVAL`, unchanged from the VM). Every
     consumer of `last_seen_at` therefore already sees values up to 60 s old: the devices and
     sessions list, the security timeline, support, and the `last_seen_after` filters.
   - **Normal auth:** with normal timeouts the idle expiry moves on every credit, so the session
     is written every time, exactly as before.

6. **Idempotency without reads on a new key** (`firestore/core_store.idempotent_firestore`).
   - **What it does:** a new key is claimed with one `create`, which fails if the document
     exists. A replay, a concurrent duplicate or an expired key goes through the old transaction
     unchanged. The finish is a field `update` with an exists precondition: the same document as
     the old read-then-overwrite, and a record that has disappeared stays absent.
   - **Saves:** 2 reads per idempotent POST.

7. **Ending a user's sessions reads only open sessions** (`sessions/repo_firestore.end_sessions`).
   - **What it does:** it now queries
     `status in (active, pending_mfa, pending_device_otp, pending_session_choice)`, which is
     every non-ended value the `auth_sessions` CHECK constraint allows. It no longer reads every
     session the user has ever had. The rows that match and get ended are the same.
   - **Safety net:** if the query is refused, it falls back to the full read.
   - **Saves:** sign-in, logout-everywhere and restrictions stop growing with history.

8. **Failed-login count per IP as an aggregation** (`sessions/repo_firestore.count_attempts`).
   - **What it does:** one `count()` (1 read per 1000 rows) replaces reading every attempt from
     the IP in the last 10 minutes. On a campus behind one NAT IP, the old way cost O(n²) reads
     during a login wave.
   - **Index:** added `lms_login_attempts (ip, outcome, attempted_at)` to
     `firestore.indexes.json` and the sessions fragment. Until that index is deployed, the
     refusal falls back to the old full read (logged), with the same number.
   - **Deploy note:** deploy the index first to get the saving. Nothing breaks without it.

9. **SPA: the order-status poll waits while the tab is hidden**
   (`apps/lms-spa/src/features/commerce/components/OrderStatus.tsx`).
   - **What it does:** a 4 s poll that falls due while the learner is in the payment app runs the
     moment the tab is visible again. The interval and the 15-minute limit are unchanged.
   - **Other polls checked:**
     - Already visible-only, with an immediate refresh on return: NotificationBell, engage
       `usePoll`, analytics tracker.
     - Left alone: playback heartbeat (media agent), the exam timers (the timer must keep its
       server sync), coding and assignment debounces.

**Not changed, on purpose:**

- **Session `last_seen` writes:** already at most once per 60 s, as on the VM.
- **Lesson-open `enrolment.last_activity_at` write:** the VM wrote it on every open, and it is
  exposed.
- **No principal, session, device, grant or restriction cache across requests:** the VM had no
  such cache, and adding one would delay revocation.

## Tests added

| Behaviour | Test |
|---|---|
| Memo: hit, copy-on-read, invalidation on every store write type, lease clears it, transactions bypass it, nothing outside or after a request, only listed collections, query memo plus collection invalidation, read rights re-checked, the middleware creates and drops it | `tests/firestore/test_request_memo.py` |
| Rate limits: no transaction on window keys, exact under concurrency, 429 and `exhausted` | `tests/platform/test_kv_firestore.py` |
| Rate limits: an old-format counter is still read by `peek`; non-window keys keep the expiry restart | `tests/platform/test_kv_firestore.py` |
| Rate limits: colocated answers equal separate checks, one commit per call; windows that do not nest are rejected | `tests/platform/test_kv_firestore.py` |
| Idempotency: a fresh key uses no transaction; replay and expired-key restart; a record removed meanwhile stays absent | `tests/platform/test_core_store.py` |
| Consent gate: same answer as the full ledger, reads only the required rows, a withdrawal is seen at once | `tests/identity/fs/test_fs_identity.py` |
| `end_sessions` reads open sessions only, including the fallback; IP failure count by aggregation, including the fallback; `touch_engaged` writes whenever the idle expiry moves and skips only no-op writes | `tests/identity/fs/test_fs_sessions.py` |
| SPA: order status waits while hidden and polls on return | `commerce.test.tsx` |

## Next levers (need an owner decision; not done)

1. **Version-checked principal cache.**
   - **Idea:** cache grants, restrictions, org memberships, MFA factors and consents per user,
     keyed by a version stamp. The stamp lives on the user document, which is read on every
     request anyway, and every write to those collections bumps it.
   - **Gain:** about 7 → 3 reads per request, about 1,600 fewer reads per student-hour, roughly
     2.3× the capacity.
   - **Risk:** any write that does not go through the store would not bump the stamp. That
     includes console edits, backfills and TTL deletes, and such a write would keep a revoked
     grant or a lifted restriction live. The VM had no such cache, so this needs explicit owner
     approval.
2. **Analytics flush cadence** (media/analytics agent). 119 POSTs an hour make up about half of
   all requests. Batching heartbeats into fewer flushes, for example every 60 s, would halve that
   share. It changes client timing, so it needs a product decision.
3. **Deploy the new `lms_login_attempts` index** so the NAT-safe login count takes effect.
