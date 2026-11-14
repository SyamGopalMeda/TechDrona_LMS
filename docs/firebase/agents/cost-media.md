# cost-media agent: video, media and analytics ingest on free tiers (2026-11-13)

Scope: media module (uploads, video assets, playback tokens, heartbeats, downloads), video watch /
analytics ingestion, certificate and export file serving, storage config and bucket deploy steps,
Hosting cache headers of the `lms` target, the SPA player and `lib/analytics`.
Owner rule: **no feature or behaviour change, only cost.** No deploys and no cloud changes were
made: everything here is code, config and docs.

## 1. How video works today, end to end

| Step | What happens | Where |
|---|---|---|
| Upload | Studio asks MED-01 `POST /media/uploads/video`. The API calls VdoCipher `PUT /videos` and returns VdoCipher's direct-upload form. The browser uploads the file **straight to VdoCipher** (CSP `form-action` allows `vdo-ap-southeast.s3-accelerate.amazonaws.com`). No video byte passes through a Function, Firebase Hosting or Cloud Storage. | `media/router.py` `video_upload`, `media/providers.py` `VdoCipherProvider.create_upload` |
| Transcode | VdoCipher transcodes and DRM-packages the file. This repo has **no transcoder and no rendition settings**. Studio polls MED-03 (`/assets/{id}/status`, VdoCipher `GET /videos/{id}`) until the asset is `available`. | VdoCipher dashboard |
| Storage | The video lives at VdoCipher. Firestore only holds the `lesson_assets` row (`provider=vdocipher`, `provider_asset_id`). | catalog |
| Playback URL | MED-04 `POST /media/playback-tokens` checks entitlement, the stream cap (one Firestore transaction on `playback_users/{uid}`) and the 30-per-hour limit. It then asks VdoCipher for a 300 s OTP carrying the per-viewer moving watermark. The SPA embeds `player.vdocipher.com/v2/?otp=…&playbackInfo=…`. VdoCipher streams DRM-protected adaptive video from its CDN. | `media/service.py` `issue_playback` |
| Player | `VideoPlayer.tsx` with VdoCipher's `api.js` supplies play/pause/position. | `features/player` |
| Watch events | Two streams, both every 30 s while the page is open: (a) MED-05 heartbeat (`use-playback-session.ts`, policy `playback.heartbeat_seconds`, default 30 s) keeps the stream slot, re-checks the entitlement and credits watched seconds to `lesson_progress` (completion at 90 %). (b) The analytics tracker (`lib/analytics/tracker.ts`) records `page.heartbeat` every 15 s with `media.played_ranges` and flushes **one batch per 30 s** (plus on visibility/idle changes and page hide via `sendBeacon`) to ANL-01. The server stores **one `analytics_batches` document per batch**, not one per event. | `media/service.py` `heartbeat`, `analytics/service.py` `ingest_batch` |
| Coverage | Each MED-05 also reads the learner's analytics coverage for the lesson (`wiring.video_coverage_lookup` → `analytics.coverage_groups`). The scheduled `video_coverage` job (60 s, scheduler agent's scope) folds the batches' played ranges into `video_watch_coverage`. | `analytics/evidence.py`, `analytics/jobs.py` |
| Stop | MED-06 on unmount, or on `pagehide` via a keepalive fetch. | |

Other files (lesson PDFs, images and captions, resources, assignment submissions, support and unblock
attachments, certificates, documents, invoices and analytics exports) go to Cloud Storage through
the S3 API. Uploads are browser **presigned POSTs**. Downloads are **presigned GETs (≤ 5 min)** or a
302 to one (ANL-15). They never stream through a Function. Certificate and document PDFs are rendered
in the Function and `PUT` once to the certificates bucket. That is a small, one-time upload.

## 2. Cost per viewing hour (measured)

### 2.1 Probe

`functions-lms/tools/media_cost_probe.py` (new; no `firestore_cost_probe.py` existed to extend)
counts billable Firestore operations at the **google-cloud-firestore RPC level**. It patches
`FirestoreAsyncClient`, so documents returned by get, batchGet and runQuery count as reads, an empty
result counts as 1 read, and each Write in a Commit counts as a write or delete. It does this on the
emulator (`127.0.0.1:18080`, its own `demo-cost-media` project, wiped only there) while driving the
**real service code** on the all-Firestore stack (`TD_STORE_*=firestore`, `TD_CACHE_BACKEND=firestore`,
fake VdoCipher):

- one MED-04 per viewing;
- per 30 s, one MED-05 (with `touch_engaged`) and one ANL-01 batch, exactly what the SPA sends
  (two engaged heartbeats with played ranges) through `enforce_rate_limits` + `ingest_batch` +
  `after_ingest`;
- one MED-06 at the end.

A fake clock advances 30 s per step. The final progress is asserted: 3,600 s watched, lesson
completed.

```
apps/api/.venv/Scripts/python functions-lms/tools/media_cost_probe.py --minutes 60 [--free] [--session memory|nopg] [--watched N] [--json out.json]
```

Not included: per-request middleware (session resolve, CSRF, MED-05's own rate limit, idempotency)
and scheduler job hints. Those belong to the other agents' probes. Add them on top.

### 2.2 Firestore operations (purchased course, 60 min, 30 s interval)

| Request | Before: reads / writes | After: reads / writes |
|---|---|---|
| MED-04 token (once per viewing) | 25 / 5 | 25 / 5 |
| MED-05 heartbeat (steady) | 24 / 3 | **18** / 3 |
| ANL-01 batch at minute 1 | 19 / 6 | 17 / 7 |
| ANL-01 batch at minute 60 | **134** / 5 (121 = `analytics_batches`, grows every batch) | **12** / 6 (constant) |
| MED-06 stop | 3 / 2 | 3 / 2 |
| **Per viewing hour** | **≈ 11,730 reads / 966 writes** | **≈ 3,610 reads / 1,086 writes** |

Per-hour breakdown after the changes:

- **MED-05:** 2,167 reads and 365 writes. The writes are `playback_sessions`, `enrolments.last_activity_at` and `lesson_progress` (1 each per heartbeat). The reads are catalog (5), enrolment (3), progress (2), playback session (2), policy (2), coverage (1), cache (2) and the auth session (1).
- **ANL-01:** 1,445 reads and 721 writes. The writes are one batch document, one page summary and four rate-limit counters (`lms_kv`, ratelimit agent) per batch.

Watch-history effect (`--watched 50`, a learner who has watched 50 other videos): the MED-05 coverage
lookup used to read **every** coverage document of the learner on every heartbeat. That was
50 reads per heartbeat, about 6,000 reads per viewing hour, growing with the learner's history. It
is now 1.

Function invocations: **240 per viewing hour** (120 MED-05 + 120 ANL-01), plus 2 per viewing (MED-04/06)
and a few for visibility/idle flushes. The client already batches analytics (15 s samples, one request
per 30 s). The two streams are separate API contracts. Merging them would change the protocol, so they
were left as they are.

### 2.3 What that means on the free tiers (video viewing only, nothing else on the project)

| Quota (free) | Per viewing hour, after | Viewing hours that fit |
|---|---|---|
| Firestore reads, 50,000/day (shared with the website) | ≈ 3,610 (+ middleware) | ≈ **13 h/day** (was ≈ 4 h, and less for long sessions because of the O(n²) growth) |
| Firestore writes, 20,000/day | ≈ 1,086 (+ middleware: `touch_engaged` adds up to 240) | ≈ **15–18 h/day** |
| Function requests, 2 M/month | 240 | ≈ 8,300 h/month |
| Hosting transfer, 360 MB/day | ≈ 0.5 MB of API JSON | not a limit |
| Cloud Storage egress | **0**: video is not in Cloud Storage | not a limit |

On Blaze, beyond the free tier, Firestore costs roughly **$0.004 per viewing hour** after the changes,
down from about $0.009. That uses the list prices of about $0.06 per 100k reads and $0.18 per 100k
writes; asia-south1 is a little higher.

### 2.4 Video bytes

Video bytes are **not on Firebase at all**. VdoCipher stores, transcodes, DRM-protects and delivers
them under its own plan, so the "100 GB free egress" question does not apply to video today. The
bitrate ladder is set in VdoCipher, not in this code. Typical adaptive ladders use about
0.35–0.45 GB/h at 480p, 0.7–1.1 GB/h at 720p and 1.4–2.3 GB/h at 1080p. No quality setting was touched.

For comparison, the case if video were ever served from Cloud Storage or Hosting (not recommended:
see §5):

| Hosting option | Free allowance | Hours at ≈ 0.75 GB/h (720p) | Cost per extra hour |
|---|---|---|---|
| GCS us-central1 | 100 GB/month egress free | ≈ 130 h/month | ≈ $0.09 (at ≈ $0.12/GB to Asia) |
| Firebase Hosting | 360 MB/day ≈ 10.8 GB/month | ≈ 14 h/month | ≈ $0.11 (at $0.15/GB) |

## 3. Changes made (behaviour-neutral)

1. **Analytics ingest: per-page heartbeat summary** (`analytics/fs_raw.py`, `store_specs.py`,
   `service.py`, `fs_jobs.py`).
   - **Problem:** every ANL-01 batch read *every* earlier batch document of the page instance. Ingest needs the stored heartbeats' `effective_at`, `kind` and `event_id` for the engaged-sample rate cap and the BE-01 `credit_wall_s` clamp. In a viewing hour that is about 7,300 reads, and the count grows quadratically with the length of the session.
   - **Fix:** `analytics_page_heartbeats/{user}:{page}` holds exactly those fields (`effective_at|kind|event_id|received_at`, with the same 35-day reader cut). It is written **in the same transaction** as the batch document, so a reader sees both or neither, as before.
   - **Fallbacks to the old batch scan:** pages stored before the summaries existed are read from their batches once, and the summary is then seeded from them. A summary that would pass 6,000 entries (document size) is marked `overflow`, and readers scan the batches as before.
   - **Lifecycle:** the TTL `expire_at` is the same as the batches' (90 days), and privacy erasure (`fs_jobs.erase_user`) deletes the summaries.
   - **Indexes:** `firestore.indexes.json` and the analytics fragment add the TTL on `expire_at` and exempt `hbs` from indexing.
   - **Cost and result:** each batch now costs +1 write and 2 reads, instead of reading n documents. The ingest results are identical (tests below).
   - **Rollout caveat:** a page instance open *during* the deploy, if served by an old instance after a new one wrote its summary, could miss a sample in the summary. That window is minutes, and it only affects rate-cap and clamp decisions for that page.
2. **MED-05 coverage lookup** (`analytics/evidence.py` `coverage_groups`): it now queries
   `video_watch_coverage` by `lesson_id in [...]` (chunks of 30) instead of reading all of the
   learner's coverage documents and filtering in Python. The output is the same groups in the same
   order. It needs the equality+`in` shape that `_fs_coverage` already uses (no new composite index).
3. **MED-05 policy lookup** (`media/service.py` `stale_after_policy`): a heartbeat reads only
   `playback.stale_after_seconds`, the one policy it uses, instead of all four. The value is the same
   and so is the stale decision. This saves 6 reads per heartbeat once media gets a working session
   (see §6.1, now fixed).
4. **Buckets in a free-tier region**:
   - New `functions-lms/deploy/create-buckets.sh` (not run). It creates the four buckets in **us-central1** (STANDARD, uniform access, public-access prevention) and applies `gcs-cors.json`.
   - `platform.md` §7 step 5.1 now says us-central1, and `.env.example` points to the script.
   - No code change is needed: buckets are addressed by name.
   - No lifecycle rule was added, because the exports bucket also holds invoices and receipts (commerce documents).
5. **Hosting cache headers**: already right, so nothing changed. Hashed `/assets/**` are
   `public, max-age=31536000, immutable`, and everything else is `no-cache` (revalidated with 304s,
   which carry almost no bytes). Signed and private files (presigned GETs) get no long cache, by design.
6. Probe `functions-lms/tools/media_cost_probe.py` (§2.1).

No SPA file changed: the client already batches and coalesces. No VdoCipher, quality or protocol
setting changed.

### Tests

- `tests/analytics/fs/test_page_heartbeats_firestore.py` (emulator) covers five cases:
  1. **Identical results.** The same viewing (30 s batches, a retried batch, a too-close engaged sample, an over-claimed range, a keepalive, and a late sample between stored ones) is ingested by two learners: once through the summaries and once through the old batch scan. The per-event statuses, credited seconds, stored rows (kind, flags, clamped ranges), `video_watch_coverage` and daily aggregates (M2/M3/M5) are equal, and the batch scan runs only for the page's first heartbeat batch. A deliberately broken summary reader makes this test fail (mutation check).
  2. **Legacy page.** A page stored before summaries existed is seeded from its batches and gives identical results.
  3. **Size cap.** Over the cap, the summary is marked overflow and readers fall back to the batch scan, with identical results.
  4. **Erasure** removes the summaries.
  5. **`coverage_groups`** equals the full-scan result for 1, 3 and 35 lessons (more than one `in` chunk) and for an unknown lesson.
- `tests/media/fs/test_heartbeat_policy_cost.py`: `stale_after_policy` equals
  `playback_policy().stale_after_seconds`. A heartbeat looks up only that key and makes the same
  stale/not-stale decision (100 s versus 130 s of silence against a 120 s policy).
- With `TD_TEST_NO_PG=1`:
  - `tests/media tests/analytics tests/firestore`: **109 passed, 72 skipped** (the skips need Postgres).
  - `tests/admin tests/learning tests/integration tests/core tests/sessions`: **204 passed, 194 skipped**.
- Changed Python files (both rounds): `ruff check`, `ruff format --check` and unfiltered `mypy`
  are all clean.
- Round-2 regression tests: §6.1 and §6.2. Round-2 suite results: §8.

## 4. Storage region

### 4.1 Recommendation

Create the LMS buckets in **us-central1** with `create-buckets.sh`. Cloud Storage's always-free
usage applies only in us-central1, us-east1 and us-west1:

- 5 GB-months of Standard storage;
- 5k Class A and 50k Class B operations;
- 100 GB of egress per month.

asia-south1 has no free tier: every GB stored and every GB downloaded is billed from the first byte.

### 4.2 Latency

These buckets hold only documents, images, captions, submissions, certificates and exports. Video
is not stored there. From India, a download or upload starts about 200–250 ms later. The Functions
stay in asia-south1, and their small writes (certificate PDFs, exports) cross regions at a
negligible cost. A separate "free-region video bucket" is not needed, because video is not in
Cloud Storage.

### 4.3 Owner decisions

- **Data residency:** learner submissions, admission proofs and invoices would be stored in the USA.
  Confirm this is acceptable under your privacy notice and DPDP obligations.
- **Existing buckets:** if buckets were already created in asia-south1, the script's header has the
  steps: create the new buckets, `gcloud storage rsync`, switch the env names, verify, then delete the
  old ones.
- **Soft delete:** this is left at the GCS default (7 days, during which deleted objects still count
  as stored bytes). Setting it to 0 would save a little but removes recovery, so it is your call.

## 5. Honest video picture and alternatives (recommendations only)

- **Today:** video costs Firebase nothing in bandwidth. The variable cost is your **VdoCipher plan**,
  which is billed by bandwidth and storage, plus about 3.6k Firestore reads and 1.1k writes and
  240 Function requests per viewing hour, after the changes above. The Firestore part leaves room for
  about 13 viewing hours a day on the free tier, before the per-request middleware and the website's
  share of the same quota.
- **Do not move video to Cloud Storage or Hosting HLS.** It would lose DRM, the per-viewer moving
  watermark and OTP playback, which are product features. It would also cost about $0.09–0.11 per
  viewing hour after roughly 130 h (GCS) or 14 h (Hosting) a month.
- **Cheaper ways to keep every LMS feature.** These are options to evaluate, not implemented. Prices
  change, so verify them on a current quote.
  1. **Stay on VdoCipher and right-size the plan.** Check the ladder in the VdoCipher dashboard; capping at 720p roughly halves bytes against 1080p. That changes what learners see, so **it is your decision**.
  2. **Another DRM video service** behind the same `VideoProvider` interface (`media/providers.py`: upload credentials, status, OTP with watermark). Candidates to quote include Gumlet, Bunny Stream with DRM, and Mux. The must-haves are Widevine/FairPlay DRM, a per-viewer dynamic watermark, token playback, and a player JS API that reports play/pause/position (needed for MED-05 and `video.*` analytics). The LMS tracking (heartbeats, coverage, completion at 90 %, stream cap) stays unchanged, because it is provider-neutral.
  3. **Lower MED-05 frequency.** This is an existing admin policy, `playback.heartbeat_seconds` (15–60 s). At 60 s, MED-05 Firestore and Function cost halves (about −1,080 reads, −180 writes and −60 requests per viewing hour). The trade-offs are that a moved or revoked stream is noticed later and the progress resolution is coarser. **This changes behaviour, so it is your decision.** Before the §6.1 fix, this policy was silently ignored on Firebase.
  4. **Other knobs with behaviour impact** (not done; listed for completeness):
     - write `enrolments.last_activity_at` at most once per N minutes (−120 writes/h at N=1);
     - cache the catalog asset → lesson → version → course chain per instance for a few seconds (about −5 reads per heartbeat, but a deleted or unpublished course is noticed a few seconds later).

## 6. Parity bugs (round 2, at the coordinator's request)

### 6.1 Fixed: media routes got the `NO_POSTGRES` placeholder session

**Problem.** `media/router.py` used `app.core.db.PrincipalDbSession`. On the Firebase stack that
yields `NO_POSTGRES`. The entitlement check reaches `commerce.product_ids_covering`, which runs on
the SQL-on-Firestore engine and needs a `MemoryTx`.

- **MED-04/MED-05 answered 500** (`PostgresDisabledError`) for every paid lesson that is not a free
  preview. MED-07 downloads of `entitled` resources failed the same way.
- **Admin playback policies were silently ignored.** `_int_policy`'s `begin_nested` raised and the
  error was swallowed, so the defaults 1/300/30/90 always applied.
- The VM (Postgres session) does neither.

**Fix.** The media router now uses `StorePrincipalDbSession`, as analytics, commerce and
assessments do. On the VM it passes the Postgres session through unchanged; on Firebase it gives a
`MemoryTx`. This covers every media route (MED-01..07). `idempotent_firestore` already handles a
`MemoryTx` savepoint.

**Regression test:** `tests/media/fs/test_playback_paid_no_postgres.py`. It runs over HTTP with
`install_fake_db`, so the request session is `NO_POSTGRES`, as on Firebase. Media, catalog,
learning, entitlements, commerce, admin and analytics run for real on the emulator. It checks:

- A purchased paid lesson: token 201 with the **admin policy `heartbeat_seconds=45` honoured**,
  then heartbeat 200, then stop.
- The same lesson without an entitlement answers **403 `entitlement_required`, not 500**.
- MED-07 of an `entitled` resource returns a presigned URL to the owner and 403 to anyone else.
- With the old import, the first two tests fail.

### 6.2 Fixed: certificates and documents `begin_nested` on `NO_POSTGRES`

**Problem.** Three steps in `learning/certificates.py` and `documents.py` were wrapped in
`session.begin_nested()`:

- LRN-33 `issue_due`, which therefore **answered 500** on Firebase;
- `_notify_in_app`, whose error was swallowed, so **the in-app certificate notice was silently
  dropped**;
- `documents.on_enrolled`, the auto admission letter. `PostgresDisabledError` is not a
  `ProblemError`, so the error escaped that handler.

**Fix.** New helper `certificates.savepoint(session)`: on a SQL session (VM) it is the same
`begin_nested()`; on the no-Postgres placeholder it is no savepoint. The Firestore writes there are
their own transactions, the same rule as `core_store.idempotent_firestore` (R10).

**Test:** `tests/learning/fs/test_cert_no_postgres_savepoint.py`.

- `issue_due` issues and queues on `NO_POSTGRES`.
- The in-app notice is sent.
- SQL sessions still get the savepoint.
- Two of the three tests fail without the fix.

### 6.3 Same pattern elsewhere (reported, not fixed: other agents' scope)

**Verified.** **LRN-05 `GET /me/courses/{course_id}/lessons/{lesson_id}` answers 500 for a paid,
non-preview lesson on Firebase.** I reproduced it over HTTP with the same harness.
`learning/router.py` uses the core session, and `check_lesson_access` → `require_access` →
`entitlements.evaluate` → commerce engine fails. LRN-06 (completion) and LRN-10 (assignment submit)
share that path.

**Likely, by the same static path (not verified).** These modules call
`require_access` / `check_access` / `evaluate`, or commerce / assessments / admissions public
functions, from a router on the core session:

- `entitlements/router.py`, `hub/router.py`;
- `mentoring/service.py`, `paths/adapters.py`;
- `placement/bank.py`, `placement/practice.py`;
- `support/router.py`, `support/service.py`;
- `admin/accounts.py`, `admin/flags.py`;
- `notifications/consumers.py`.

**Other unguarded `begin_nested()` on request or job sessions:**

- `placement/practice.py` (368, 651);
- `orgs/route_store.py` (several);
- `security/cases.py` 356, `security/signals.py` 771;
- `commerce/service.py` 1179;
- `analytics/consumer.py` 457, the reconciler job (scheduler agent).

**Jobs on Postgres only.** `learning/tasks.py` (certificate send, batch-end issue, PDF backfill)
opens `get_sessionmaker()` directly, so it is Postgres-only (scheduler agent).

**Suggested central fix** (data-money/platform owners): when `SqlStore.execute` gets a
no-Postgres session, run a read-only statement on a throwaway `MemoryTx`. That fixes every
`entitlements.evaluate` caller at once. The alternative is to move these routers to
`StorePrincipalDbSession` one by one.

### 6.4 Not changed: free-course lesson events rejected (`entity_not_entitled`)

The VM behaves the same, so this is **pre-existing, not a migration bug**, and I left it as it is.

- `analytics.service._allowed` calls `check_access(...)` without `is_free` on both stores.
- `entitlements.evaluate` has no free-course rule of its own, so a learner on a free course with no
  entitlement gets `no_entitlement` on Postgres too.
- Effect: free courses record no learning-time or coverage analytics.
- Owner decision: if wanted, pass the course's `is_free`, as `learning.check_lesson_access` does.

### 6.5 Cross-agent cost notes (forwarded by the coordinator)

- The analytics ingest rate limiter does 4 reads and 4 writes on `lms_kv` per batch, about
  480 writes per viewing hour.
- `touch_engaged` adds a session write per credited request.

### 6.6 Test isolation note

The shared emulator project `demo-techdrona-test` is wiped by every agent's `clear_emulator`. The
emulator suites here intermittently lost their seed data mid-test until they ran with
`TD_TEST_DB_NAME=cost_media` (a private `demo-*` project). Use a per-agent `TD_TEST_DB_NAME` when
agents test in parallel.

## 7. Files

- New: `functions-lms/tools/media_cost_probe.py`, `functions-lms/deploy/create-buckets.sh`,
  `apps/api/tests/analytics/fs/test_page_heartbeats_firestore.py`,
  `apps/api/tests/media/fs/test_heartbeat_policy_cost.py`,
  `apps/api/tests/media/fs/test_playback_paid_no_postgres.py`,
  `apps/api/tests/learning/fs/test_cert_no_postgres_savepoint.py`, this document.
- Changed: `apps/api/app/modules/analytics/{fs_raw,store_specs,service,fs_jobs,evidence}.py`,
  `apps/api/app/modules/media/{service,router}.py`,
  `apps/api/app/modules/learning/{certificates,documents}.py`, `firestore.indexes.json`,
  `apps/api/app/modules/analytics/firestore.indexes.fragment.json`, `functions-lms/.env.example`,
  `docs/firebase/agents/platform.md` (§7 step 5.1).
- Deploy note: the new TTL (`lms_analytics_page_heartbeats.expire_at`) goes live with
  `firebase deploy --only firestore:indexes`, alongside the next functions deploy.

## 8. Round-2 verification

Command: `TD_TEST_DB_NAME=cost_media TD_TEST_NO_PG=1 pytest tests/media tests/analytics tests/firestore tests/learning tests/admin tests/integration tests/core tests/sessions tests/entitlements tests/catalog`.

- Result: **351 passed, 316 skipped, 1 failed**.
- The one failure is `tests/firestore/test_store_boundary.py::test_no_raw_firestore_outside_store_layer`. It is caused by `app/core/jobhints.py` and `scheduler.py`, the scheduler agent's in-progress files, which were not touched here.
- `ruff`, `ruff format --check` and unfiltered `mypy` are clean on every file changed in either round.
