# Platform agent report: running the LMS on Firebase (2026-11-12)

Scope: `functions-lms/`, the VM-only runtime pieces in `apps/api/app/core/`, `firebase.json` /
`.firebaserc`, `apps/api/tests/platform/`. Nothing was deployed. The VM, the website repo and
Firestore rules were not touched. No secret was read.

**Result:** the unchanged FastAPI app runs inside a Python Cloud Function behind a Python port
of the Next.js BFF. Redis, Celery, beat, outbox and idempotency each have a Firebase backend
behind a switch. The default of every switch is the current VM behaviour.

## 1. What was built

| Area | Files | What it does |
|---|---|---|
| Runtime switch | `app/core/runtime.py`, `app/core/config.py` (additive) | `TD_RUNTIME=vm` (default) or `firebase`. `TD_CACHE_BACKEND` and `TD_TASKS_BACKEND` follow it unless they are set explicitly. |
| API function | `functions-lms/main.py` | `lmsApi` is an HTTPS function in asia-south1 (python313, 1 GiB, 1 CPU, concurrency 40, 60 s timeout, min instances from the `LMS_API_MIN_INSTANCES` param, default 1). It runs `EdgeApp(create_app())` through `a2wsgi.ASGIMiddleware`. `run_wsgi` returns the WSGI response verbatim, because Flask would otherwise add `Content-Type: text/html` to a 204. |
| BFF parity | `functions-lms/lms_edge/` (`app.py`, `cookies.py`, `csrf.py`, `public.py`, `http.py`, `config.py`) | A line-by-line port of `lib/bff/proxy.ts`, `csrf.ts`, `cookies.ts`, `headers.ts`, `remember.ts` and `public-admissions.ts`. It keeps the same checks (Fetch Metadata, Origin, signed double-submit CSRF, body limits, JSON-only, beacon CSRF in the body), the same problem bodies, the same upstream allow-list headers (service token, `x-td-session`, `x-td-device`, canonical `__Host-` cookies, client IP, `x-forwarded-*`, new `x-request-id`/`traceparent`, `x-td-activity`) and the same cookie re-issue rules (an ended session is cleared, CSRF is re-minted on a session change). It calls the API in-process over ASGI, with no network hop. |
| `__session` packing | `lms_edge/cookies.py` | `TD_EDGE_COOKIE_PACKING=session` is the default in the function. Session, device, remember and the CSRF token are packed into one HttpOnly `__session` cookie: `v1.<b64url JSON {s,d,r,c: [value, expires_epoch]}>`. Each part keeps its own expiry, and the cookie's Max-Age is the longest remaining part. The readable `__Host-td_csrf` cookie is still issued with the same value and attributes, so browser JS is unchanged. The header is compared with the packed copy. `split` mode gives byte-identical Next.js cookies. |
| New BFF route (SPA) | `GET /api/v1/_bff/session` | Replaces what the Next page middleware did on a page load: the remember-device re-issue (AUTH-28) and `td_csrf` issue/refresh. Returns `200 {"session": bool, "refreshed": bool}`. Same-origin only. It sits in the `_bff/` namespace, which the API never serves. |
| Redis → Firestore | `app/core/firestore/kv.py`, `app/core/redis.py`, `app/core/ratelimit.py` | `FirestoreRedis` is a Redis-compatible facade over `lms_kv`: get/set(ex, px, nx, xx, keepttl)/incr/incrby/expire/ttl/delete/exists/mget/ping/pipeline. It returns bytes like Redis. With `TD_CACHE_BACKEND=firestore`, `get_cache_redis()` and `get_queue_redis()` return it, so the entitlement cache and the readiness probe work with no module change. `FirestoreRateLimitBackend` gives exact fixed-window counts (one transaction per hit, INCR + EXPIRE ttl+1 like Redis) and fails open like Redis. |
| Celery → Cloud Tasks | `app/core/cloudtasks.py`, `app/worker.py` | With `TD_TASKS_BACKEND=cloudtasks`, `install(celery_app)` replaces `send_task`, which also covers `apply_async`/`delay`. Sends go to the task-queue function for the Celery queue (`critical` → `lmsTasksCritical`, `default` → `lmsTasks`, `maintenance` → `lmsTasksMaintenance`, unknown → `lmsTasks`) through `firebase_admin.functions.task_queue`. `countdown`/`eta` become `schedule_delay_seconds`. `run_task` runs the registered task body (`Task.apply`, eager, raises so Cloud Tasks retries). |
| Beat → scheduled functions | `functions-lms/schedules.json`, `tools/gen_schedules.py`, `cloudtasks.cron_for/run_periodic` | One `scheduler_fn.on_schedule` function (`lmsJob*`, UTC) per beat entry: **31 entries, 26 app tasks** (not 27/10: the registry is larger than the brief's grep). Sub-minute entries run every minute and repeat inside the call: outbox relay 5 s, deadline sweeper 5 s, audit seal 2 s, all within a 50 s budget. Intervals without an exact cron equivalent raise an error instead of changing cadence. A test fails if `schedules.json` drifts from the registry. |
| Outbox + idempotency | `app/core/firestore/core_store.py`, hooks in `idempotency.py`, `worker.py`, `outbox.py` (docstring) | `emit_event_tx(tx, …)` writes the event in the caller's Firestore transaction. `relay_pending_firestore` claims a lease in a transaction (`lease_until`, the SKIP LOCKED equivalent), runs the existing handlers, then dispatches or dead-letters. It needs no composite index (`order_by("pending_at")`). The worker relay drains Postgres unless every module is on Firestore, and drains Firestore only when some module is on Firestore, so the default is unchanged. `idempotent()` uses the Firestore record (`lms_idempotency_keys`, id = sha256(user\|route\|key), TTL field `expire_at`) when `TD_STORE_CORE=firestore`. |
| Firestore credentials | `app/core/firestore/client.py`, `checks.py` (small edits) | With `TD_RUNTIME=firebase` and no key file, the Admin SDK uses Application Default Credentials (the function's service account), and the production gate accepts that. VM behaviour is unchanged. |
| Packaging | `functions-lms/tools/build.py`, `requirements.txt`, `secrets.txt`, `.env.example`, `.gitignore` | `build.py` regenerates `schedules.json`, copies `apps/api/app` → `functions-lms/app` (no tests, no `.env`, no caches) and checks `venv`. Requirements are pinned to the API venv versions plus `firebase-functions==0.6.0` and `a2wsgi==1.10.10`. Secrets are Secret Manager `SecretParam`s named in `secrets.txt` and mapped to the same env names as `server.env`. |
| `_REPO_ROOT` | `app/core/config.py` | Clamped, because `/workspace/app/core/config.py` in the bundle has only 4 parents (`parents[4]` would raise IndexError at import). The VM value is unchanged. |
| Hosting | `firebase.json`, `.firebaserc`, `functions-lms/tools/sync_hosting.py` | `hosting` is now a list. The old showcase config is unchanged as target `showcase` (mapped to site `billing-f4fe3`, the site a target-less deploy used). The new target `lms` has `public: apps/lms-spa/dist`, `/api/**` → `lmsApi` (asia-south1), SPA fallback `** → /index.html`, the Caddy marketing redirects to the website, Caddy's `Strict-Transport-Security` and `X-Robots-Tag: noindex, nofollow`, and the SPA agent's `hosting-headers.json` (static CSP and per-path rules). It adds `functions: [{source: functions-lms, codebase: lms, runtime: python313}]`. |
| Deploy (not run) | `functions-lms/deploy/deploy.sh`, `deploy/gcs-cors.json` | Checks the env and secrets, builds, builds the SPA, syncs headers and deploys `functions:lms,hosting:lms`. Supports `--dry-run`. |

## 2. Switches and defaults

| Switch | Default | Firebase function value |
|---|---|---|
| `TD_RUNTIME` | `vm` | `firebase` (`main.py` sets it with `setdefault`) |
| `TD_CACHE_BACKEND` | `""` → redis | firestore |
| `TD_TASKS_BACKEND` | `""` → celery | cloudtasks |
| `TD_CLOUD_TASKS_QUEUES` / `_LOCATION` | `critical=lmsTasksCritical,default=lmsTasks,maintenance=lmsTasksMaintenance` / `asia-south1` | same |
| `TD_STORE_CORE` | postgres | flip last (P6) |
| `TD_EDGE_COOKIE_PACKING` (edge only) | `session` | `session` |
| `TD_EDGE_TRUST_VIEWER_ADDRESS` (edge only) | false | false (Hosting passes a browser-supplied `CloudFront-Viewer-Address`) |

A VM redeployed from this code behaves the same: no setting changes value, Celery and beat start
exactly as before, and Redis is used as before.

## 3. Tests: commands and actual results

```
cd apps/api
TD_TEST_DB_NAME=platform_test .venv/Scripts/python -m pytest tests/platform -q      # 53 passed (17.7 s)
APP_ENV=test .venv/Scripts/python -m pytest --noconftest tests/firestore/test_store_boundary.py tests/firestore/test_backend_and_checks.py -q   # 15 passed
.venv/Scripts/python -m ruff check / ruff format --check <changed files>            # clean
.venv/Scripts/python -m mypy <changed app modules>                                   # no issues
functions-lms/venv/Scripts/python functions-lms/tools/smoke_local.py functions-lms   # see below
```

- `tests/platform` (Firestore emulator 127.0.0.1:18080, project `demo-platform-test`; Postgres
  not needed because the conftest overrides `migrated_database`):
  - runtime switches;
  - the Redis facade semantics (expiry, nx/xx, INCR keeps the TTL, exact concurrent INCR, pipeline);
  - rate-limit 429 and its headers;
  - the unchanged entitlements cache on the facade;
  - outbox emit, relay order, retry, dead letter, no handler, Postgres session scope and lease exclusion;
  - idempotency replay, reuse 409, stored 4xx, 5xx not stored, in-progress 409;
  - cron conversion and the `schedules.json` == registry check;
  - `send_task`/`apply_async`/`delay` routed to Cloud Tasks, `run_task`, the sub-minute repeat;
  - edge: CSRF byte-compatible with the TS algorithm, bootstrap and re-issue, double submit, Fetch
    Metadata and Origin, 413/415, beacon, upstream header rebuild, forged headers dropped, viewer
    header ignored, cookie packing and Max-Age, session rotation, CSRF rebinding, ended-session
    clearing, reserved paths, 405, split mode identical to Next, `_bff/session` remember refresh,
    the public admissions CORS and multipart → JSON path, and the edge in front of the **real**
    FastAPI app.
- Local function smoke (functions venv, Flask test client = the Request object Cloud Functions passes):
  - `/healthz` 200;
  - `/api/v1/health/live` 200 + `__session` + `td_csrf`;
  - `_bff/csrf` 204 with no Content-Type;
  - unknown, webhook and other paths 404 problem+json;
  - unsafe request without a token 403 `csrf_failed`;
  - public bridge from an evil origin 403.
- Firebase discovery (`firebase_functions.private.serving.functions_as_yaml`) produces **35
  endpoints**: 1 https, 3 taskQueue (retry and rate-limit config) and 31 schedule (UTC). Secrets
  and the min-instances param appear in the manifest.
- **Not run:** tests that need Postgres or Redis (`tests/core`, module suites). Run with
  `--noconftest`, some core tests failed only because Redis, Postgres and the conftest env were
  missing (connection timeouts, no service token). None of those failures was in code changed
  here. The full Firebase emulator suite (`firebase emulators:start --only functions`) was not
  started, because it would collide with the shared emulator hub/ports.

## 4. Unverified (must be checked on the first real deploy)

1. **Hosting cookie handling:**
   - that Firebase Hosting passes the function's `Set-Cookie` for `__Host-td_csrf` through;
   - that it forwards `__session` with the packed value (expected, but not live-tested);
   - that responses with `Set-Cookie` are not cached (expected; all API responses are `no-store` anyway).
2. **Client IP:** the X-Forwarded-For layout Hosting → Cloud Run. `TD_TRUSTED_PROXY_HOPS=1` is an
   assumption. Log `x-forwarded-for` once and set hops so `x-td-client-ip` is the browser IP.
   Rate limits and the security signals depend on it.
3. **Cloud Tasks enqueue:** the enqueue (`firebase_admin.functions.task_queue`) and the IAM it
   needs. The function service account needs `roles/cloudtasks.enqueuer` and
   `roles/run.invoker` on the task functions (Firebase usually grants these on deploy).
4. **Firestore over ADC:** that the function service account has `roles/datastore.user`.
5. **Cloud Storage presigned uploads and downloads:**
   - Downloads and boto3 `put_object` should work over GCS XML interop with HMAC keys:
     `S3_ENDPOINT_URL=https://storage.googleapis.com`, `AWS_REGION=auto`, path style.
   - **Presigned POST** (`media/storage.py presign_post`, `x-amz-*` policy fields) is the riskiest
     part. GCS documents POST policy V4 with `x-goog-*` fields. Acceptance of `x-amz-*` fields
     under HMAC interop is not verified. If GCS rejects it, the media module needs a GCS-flavoured
     policy (request below).
   - Buckets need CORS from `deploy/gcs-cors.json` (the LMS origin, GET/HEAD/POST/PUT,
     expose ETag), the same rule Caddy applied to the files host.
   - The SPA CSP `connect-src`/`form-action` must list `https://storage.googleapis.com`. It does
     when `S3_ENDPOINT_URL` is set while generating headers.
6. **Cold start** of the full API: about 100+ modules imported per instance, not measured. Keep
   min instances at 1 for `lmsApi`.
7. **Sub-minute jobs:** each holds an instance about 50 s per minute (3 jobs). The cost is not
   measured.

## 5. Blockers and open decisions

- **Postgres (decided 2026-11-12):** the owner chose to deploy the Firebase stack only when every
  module is on Firestore, with no Cloud SQL bridge. The platform side is ready for that (round 2,
  §8). What remains is the module work: each route still on its Postgres code path fails with
  `PostgresDisabledError` until its module agent finishes. The Postgres-only jobs
  (`core.maint_partitions`, `core.maint_retention`) still exist as scheduled functions. They fail
  harmlessly (logged) until they are retired per plan §3.6.
- **College Data Portal proxy** (`/college-portal/*`, `lib/college-portal/proxy.ts`) was **not
  ported**. It depends on the separate portal app (SQLite, `college-portal` container), which has
  no Firebase home yet (`col_*` move, single-project.md §4). On Firebase, `/college-portal/*`
  currently falls into the SPA fallback.
- **Webhooks:** built in round 2 as `lmsWebhooks` (§8). Hosting still returns 404 for
  `/api/v1/webhooks/*`, as the VM's BFF does. Providers call the function URL.
- **Coding judge** (owner decision 1): `TD_CODING_SEND_TASKS` stays off, and the polling judge
  worker has no Firebase equivalent.
- **Hosting site name** (owner decision 2): `.firebaserc` maps target `lms` to the placeholder
  site `techdrona-lms-app`. Create or rename the site, then update `.firebaserc` and the
  `REPLACE` values.

## 6. Requests to other agents

- **spa:**
  1. On app start, call `GET /api/v1/_bff/session`. It replaces the middleware portal gate and
     the remember-me re-issue. If `session` is false on a portal route, redirect to
     `/login?next=…`.
  2. Keep `/` → `/login` (signed out) or `/modules` (signed in) client-side (Caddy did it by cookie).
  3. Regenerate `hosting-headers.json` with the Firebase env (`S3_ENDPOINT_URL`, site origin),
     then run `functions-lms/tools/sync_hosting.py`. The current file has VM origins (sslip.io).
  4. `robots.txt` should be `Disallow: /` and `sitemap.xml` 404, as Caddy served on the LMS host.
- **data-content (media) and data-money (commerce documents):**
  1. Verify presigned POST against GCS interop. Add a GCS (`x-goog-*`) policy variant behind
     `S3_ENDPOINT_URL` if needed.
  2. `ServerSideEncryption` is already skipped when an endpoint is set (good for GCS).
- **data agents (all):**
  1. Modules on Firestore must emit events with `app.core.firestore.core_store.emit_event_tx(tx, …)`
     inside their transaction (not `emit_event(session)`).
  2. Handlers receive `session=None` once every module is on Firestore.
  3. Celery sends inside a Firestore transaction are refused (`forbid_in_transaction`); use
     `tx.after_commit`.
- **Owner/coordinator:** Firestore TTL policies (`gcloud firestore fields ttls update expire_at
  --collection-group=lms_kv --enable-ttl` and the same for `lms_idempotency_keys`). These can
  also be declared as `fieldOverrides` in `firestore.indexes.json`. That file is shared, so it
  was not edited here.

## 7. Deploy steps (for later; owner approval first; nothing here was run)

1. **Decide the Postgres question (§5).** Create the Hosting site:
   `firebase hosting:sites:create <lms-site> --project billing-f4fe3`. Set `.firebaserc` →
   `targets.billing-f4fe3.hosting.lms = ["<lms-site>"]`.
2. **Enable the APIs:** Cloud Functions, Cloud Run, Cloud Build, Artifact Registry, Cloud Tasks,
   Cloud Scheduler, Secret Manager, Eventarc.
3. **Secrets:** for each name in `functions-lms/secrets.txt`, run
   `firebase functions:secrets:set NAME --project billing-f4fe3` with the **same values as the
   VM's `server.env`**, so sessions, device cookies, TOTP and CSRF tokens stay valid.
4. **Environment:** `cp functions-lms/.env.example functions-lms/.env.billing-f4fe3`. Fill every
   `REPLACE` value: the same `APP_ENV` and testing switches as `server.env`, the site URL and the
   bucket names.
5. **Cloud Storage:**
   1. Create the buckets in **us-central1** (Cloud Storage free tier; asia-south1 has none):
      `BUCKET_PREFIX=<prefix> bash functions-lms/deploy/create-buckets.sh` (also applies CORS).
      Why and the trade-offs: `docs/firebase/agents/cost-media.md` §4 (cost-media agent, 2026-11-13).
   2. Create an HMAC key for a service account with `roles/storage.objectAdmin` on them; its
      id/secret go into the `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` secrets.
   3. Apply CORS: `gcloud storage buckets update gs://<bucket> --cors-file=functions-lms/deploy/gcs-cors.json`
      (edit the origin first).
   4. Copy objects from SeaweedFS with `aws s3 sync` (endpoint = SeaweedFS) → `gsutil`/`gcloud
      storage cp`, keeping the keys.
6. **IAM** for the functions' service account: `roles/datastore.user`,
   `roles/cloudtasks.enqueuer`, `roles/run.invoker`, `roles/secretmanager.secretAccessor`.
7. **Firestore TTL:** now declared in `firestore.indexes.json` `fieldOverrides` (§8 #6); deploy it with `firebase deploy --only firestore:indexes`.
8. **Deploy:**
   1. Dry run: `bash functions-lms/deploy/deploy.sh --dry-run`.
   2. Deploy: `bash functions-lms/deploy/deploy.sh`.
   3. Smoke the live site: `/api/v1/health/live`, `/api/v1/_bff/csrf` → 204 + cookies, then
      sign in through the SPA.
9. **Check the unverified items in §4** (cookies, client IP via logs, a task enqueue, an upload
   and a download), then walk through as each role (plan §6).
10. **Rollback:**
    - `firebase hosting:disable --site <lms-site>`, or deploy the previous release.
    - Functions: `firebase functions:delete <name> --codebase lms`.
    - The VM is untouched throughout.

## 8. Round 2 (2026-11-12): no Postgres at all, plus core helpers

Owner decision: the Firebase stack runs with no Postgres. It is deployed only when every
`TD_STORE_*` is `firestore`. Nothing was deployed.

| # | What | Files |
|---|---|---|
| 1 | **Boot without Postgres.** `runtime.postgres_enabled()` is False when `TD_RUNTIME=firebase` and every module is on Firestore, or when `DATABASE_URL` is empty. It is True on the VM, so nothing changes there. When it is False: `db.get_engine()` raises `PostgresDisabledError` and never builds an engine. `get_db` / `get_principal_db` (`DbSession`, `PrincipalDbSession`) yield `db.NO_POSTGRES`, which is falsy and raises `PostgresDisabledError` on any use (a clear error, never a connection attempt). `/health/ready` keeps the same shape and pings Firestore for `database`. The startup gate passes (ADC, no key file). The Celery registry boots with the Cloud Tasks transport, and the worker relay drains only the Firestore outbox. | `app/core/runtime.py`, `db.py`, `health.py` |
| 2 | **`TD_TEST_NO_PG=1`** in the root `tests/conftest.py`. It skips the migration and works without DB URLs. Every Postgres fixture (`app_engine`, `committed_engine`, `sealer_engine`, `owner_engine`, `db`) skips its test. Default (unset): identical to before. | `tests/conftest.py` |
| 3 | **Core `audit()` on Firestore.** It accepts the caller's `ScopedTransaction`. With `TD_STORE_AUDIT=firestore` the record goes to `audit.repo_firestore.enqueue(tx, …)` and commits or rolls back with the business write. A Postgres session or `None` falls back to `enqueue_now` (its own transaction; the Firestore sealer is the only sealer then). With `TD_STORE_AUDIT=postgres` (default) a Firestore transaction raises `TypeError`, because it cannot be atomic with `audit_outbox`. Postgres sessions behave as before. `repo_firestore.py` was not edited. | `app/core/audit.py` |
| 4 | **Shared row codecs** `app/core/firestore/rows.py`. The module copies use two families that store values differently, so both are kept verbatim: "json" (learning/engage/mentoring `fs_rows.py`: `encode/decode/doc_mapper/doc_of/orm_of`, bytes→hex, `$l` nesting) and "scaled" (placement/coding `fsmap.py`: `to_doc_value/from_doc_value/row_doc/orm_doc/orm_of_scaled/pk_id/register_table`, numeric quantized, bytes→base64). The copies are unchanged. A parity test compares every copy with the shared module. `admin/fs_rows.py` (`FsRow` class) is a third style and is not covered. | `app/core/firestore/rows.py`, `tests/platform/test_rows.py` |
| 5 | **Per-request locks** (`pg_advisory_xact_lock` replacement): `await request_locks.acquire(f"sess:{user_id}")` claims the lease `lms_locks/{key}` for the current request. It waits with jittered backoff (default 10 s, then `503 service_unavailable` + `Retry-After: 1`), is re-entrant, and has a 30 s lease TTL as a crash guard. `RequestContextMiddleware` opens a scope per HTTP request and releases every lock in its `finally`. There is no cost when no lock is taken (the VM path never imports Firestore). Outside requests, use `async with request_locks.scope():`. **sessions owner:** in `sessions.service.lock_user`, replace the Firestore early `return` with `await request_locks.acquire(f"sess:{user_id}")` to close the session-cap race. | `app/core/request_locks.py`, `app/core/middleware.py` |
| 6 | **TTL policies** in `firestore.indexes.json` `fieldOverrides` (`"ttl": true`, the format the CLI deploys): `lms_kv.expire_at`, `lms_idempotency_keys.expire_at`, `lms_attempt_events.expire_at` and `lms_coding_testcase_content_tokens.expires_at`. `lms_playback_sessions.expire_at` was already present. Nothing was removed: still 113 indexes, and field overrides went from 62 to 66. Note: the file was rewritten as standard 2-space JSON (content identical apart from the 4 additions). This replaces the manual `gcloud … ttls` step in §7. | `firestore.indexes.json` |
| 7 | **Webhooks function** `lmsWebhooks`: the `api-webhooks` service on Firebase. It is the same app with `TD_ROUTER_SET=webhooks` (`settings.model_copy`; only the commerce `webhook_router` and health routes) behind `lms_edge.webhooks.WebhookEdge`, with no BFF, cookies or CSRF. The raw body is passed byte for byte (HMAC). The client IP comes from X-Forwarded-For (the per-IP invalid-signature limit stays per provider IP). `Authorization`, `Cookie` and `X-TD-*` are dropped, so a webhook can never be service-authenticated. Other paths return 404. Settings: 512 MiB, public invoker. Providers call `https://asia-south1-<project>.cloudfunctions.net/lmsWebhooks/api/v1/webhooks/<provider>`. Hosting keeps returning 404 for `/api/v1/webhooks/*`, as the VM does. **commerce owner:** `provider_webhook` still opens `get_sessionmaker()` directly and must move to its Firestore repository. | `functions-lms/main.py`, `functions-lms/lms_edge/webhooks.py` |

The function environment for the no-Postgres stack is in `functions-lms/.env.example`: empty
`DATABASE_URL` and every `TD_STORE_*=firestore`. `DATABASE_URL` was removed from `secrets.txt`.

### Round 2 test results

```
cd apps/api
TD_TEST_NO_PG=1 TD_TEST_DB_NAME=platform_test .venv/Scripts/python -m pytest tests/platform tests/firestore -q
  -> 99 passed (57.8 s)   [tests/platform 73 + tests/firestore 28, no --noconftest needed]
ruff check app/core tests/platform tests/conftest.py app/worker.py   -> clean
mypy (changed core modules)                                          -> no issues
functions discovery                                                  -> 36 endpoints (lmsWebhooks included)
functions-lms/tools/smoke_local.py                                   -> unchanged results (see §3)
```

New tests:
- `test_no_postgres.py`:
  - app boot and gate, `/healthz`, `/health/live` and `/health/ready` (database = Firestore) with
    no engine built;
  - `NO_POSTGRES` sentinel;
  - Celery registry without Postgres;
  - defaults keep Postgres.
- `test_core_audit_firestore.py`: atomic commit and rollback; refusal on Postgres.
- `test_rows.py`: 5 parity checks across all copies.
- `test_request_locks.py`: serialisation, re-entrancy, 503 on timeout, release by the middleware.
- `test_webhooks_edge.py`: raw body, IP, header hygiene, 404s, and the real app with
  `TD_ROUTER_SET=webhooks`.

Observed with no Postgres, informational for the module agents: `GET /api/v1/public/courses/status`
(admissions) and `GET /api/v1/catalog/courses` still use the request session and answer
`PostgresDisabledError`. The admin maintenance-flag read in `MaintenanceMiddleware` fails open
(logged) until admin flags read Firestore.

## 9. Round 3 (2026-11-12): emulator run and no-Postgres core fixes

Test policy: no Docker and no Postgres. Everything was run on the Firestore emulator with
`TD_TEST_NO_PG=1`. Nothing was deployed.

### 9.1 Functions + Hosting emulator, actually run

| Item | Result |
|---|---|
| Script | `functions-lms/tools/emulate.ps1` (re-runnable; `-SeedOnly`, `-NoSeed`). It uses its own config `functions-lms/emulator/firebase.json`: Hosting 5000, Functions 5001, hub 14402, logging 14502, UI off, project `demo-platform-emu`. It reuses the shared Firestore emulator on 18080, so the running instance's ports are untouched. It writes `functions-lms/.env.local` (TD_RUNTIME=firebase, every `TD_STORE_*=firestore`, `TD_PUBLIC_BASE_URL=http://127.0.0.1:5000`, `APP_ENV=local`, `DATABASE_URL=`, `TD_SIMPLE_AUTH=true` as on the VM) and `.secret.local` (dummy dev-only secrets). Both files are gitignored. |
| Seed (no Postgres) | `functions-lms/tools/seed_emulator.py`. It writes the RBAC catalogue (5 roles, 117 permissions, 179 role-permission pairs) through the rbac backfill mappings. It creates `admin@dev.techdrona.local` (super_admin @ platform) and `student@dev.techdrona.local` through `identity.public.create_user`, `identity.service.record_consent` and `rbac.public.add_grant` on Firestore, with the VM seed's dev password. It is idempotent and refuses anything that is not a `demo-*` emulator project. |
| Loaded | 37 functions (incl. `lmsJobCodingProcessPending`). `lmsApi`, `lmsWebhooks` and the 3 task-queue functions are served. The 31 `lmsJob*` scheduled functions are "ignored because the pubsub emulator is not running", which is expected; their bodies are covered by `tests/platform/test_cloudtasks.py`. |
| Smoke | `functions-lms/tools/smoke_emulator.py`. It goes **through Hosting** (http://127.0.0.1:5000) and writes a full JSON report. |

Smoke results through Hosting:
- The SPA loads: `/` → 200 index.html; deep link `/app/learn/...` → 200 (SPA fallback).
- `GET /api/v1/health/ready` → 200 `{"database":"ok","redis_cache":"ok"}` (both checks are Firestore).
- `GET /api/v1/_bff/csrf` → 204 with the `__session` and `td_csrf` cookies.
- `GET /api/v1/_bff/session` → 200 `{"session":false}` when anonymous, and `{"session":true}` after login.
- **Login works with no Postgres:** `POST /api/v1/auth/login` (CSRF double submit) → 200 `authenticated`, for admin (tier privileged, redirect `/admin`) and for student (redirect `/app`).
- Every parameter-free `GET /api/v1/*` route (138, taken from the app's OpenAPI) was called as each user:

| User | 200 | 400 | 403 | 422 | 503 | 500 |
|---|---|---|---|---|---|---|
| admin | 123 | 6 | 8 | 1 | 0 | 0 |
| student | 57 | 4 | 76 | 1 | 0 | 0 |

Latest run, on a **fresh** emulator start (old instance stopped; 37 functions incl.
`lmsJobCodingProcessPending`; `TD_CODING_SEND_TASKS=1` loaded): **no route fails**. Earlier
runs showed `PostgresDisabledError` 503s on modules not yet ported: 13 routes for admin and 6 for
student, then 4 (admin module); those modules have since moved to Firestore.
- **400/422: the app's own answers** to missing required query parameters (`/catalog/search`, `/paths/link-options`, `/paths/batch-members`, `/me/ai/tutor-history`, `/admin/documents/prefill`, `/security/evaluations`, `/studio/resources`), not failures.
- **403:** permission answers (a student on staff routes).

**Two real bugs found by the emulator run, both fixed:**
1. **Hosting drops `Set-Cookie`** from a function response unless `Cache-Control` contains
   `private` (firebase-tools `hosting/proxy.js`; it mirrors the CDN rule). Every cookie-carrying
   edge answer was `no-store`, so no cookie ever reached the browser. The edge now sends
   `Cache-Control: private, no-store` whenever it sets cookies. Browser caching is unchanged,
   because `no-store` already applied. Responses without cookies are untouched. Test:
   `test_cookie_responses_are_private_for_hosting`.
2. **POSTs through Hosting hung:** the Hosting proxy sends chunked bodies, and a2wsgi blocked
   reading `wsgi.input`. `run_wsgi` now reads the body once through Flask
   (`get_data(cache=True)`) and passes the app a sized `wsgi.input`.

Two emulator facts were also handled:
- Firebase reserves the `FIREBASE_*` env prefix for functions. `Settings` now takes
  `FIREBASE_PROJECT_ID` from `GOOGLE_CLOUD_PROJECT`/`GCLOUD_PROJECT` on the Firebase runtime
  when it is unset.
- The emulator client prefers a `demo-*` `GCLOUD_PROJECT` over a real project id that came from
  the repo `.env`.

`FIREBASE_PROJECT_ID` was removed from `functions-lms/.env.example`.

### 9.2 Changes this round

| Item | What | Test |
|---|---|---|
| (1) SPA navigation marker | The edge forwards a browser `x-td-activity: navigation` on GET when the request is same-origin (Fetch-Metadata `same-origin`/`none`, or no Fetch-Metadata and no foreign Origin) and not a prefetch. The Next.js rule (`Sec-Fetch-Mode: navigate`) is kept. Anything else is dropped. | `test_spa_navigation_marker_is_forwarded_like_nextjs` (9 cases) |
| (2) `sync_hosting.py` | Owns `/api/**` and `/sitemap.xml` → `lmsApi` plus the SPA fallback. It keeps other rewrites and header rules from the existing `lms` entry and extra keys on the `**` rule. Running it on the current `firebase.json` changes nothing. | `test_sync_hosting.py` |
| R10 | `idempotent_firestore` treats `None`/`NO_POSTGRES` as "no savepoint". `db.no_session(s)` is the explicit check. | `test_idempotency_with_the_no_postgres_placeholder` |
| R12 | `RequestContextMiddleware` publishes the request's state dict. `app.core.request_context.current_principal()` and `current_rls_context()` (an `RlsContext` mirroring `tenant_context`'s GUCs; `ANONYMOUS` when nobody is signed in) give modules without a Postgres session the caller's view. This also works for principals resolved later or in threadpool dependencies. | `test_request_principal_context.py` |
| Contention (data-ops) | The store's transaction runner also retries a raw `Aborted` or "Transaction lock timeout" raised by a read inside the callback, with the same jittered backoff as before. When retries run out it raises `TransactionContentionError`, which is now also a `ProblemError`: `409 conflict` "Another request changed this at the same time…" + `Retry-After: 1` (the sqlstore wording), never a raw 500. | `test_store_contention.py` (incl. 4 concurrent read-modify-write → 1..4) |
| No-PG session helpers (data-access, data-learning) | With `None`/`NO_POSTGRES`, `set_rls_context`, `apply_db_role`, `tenant_context` and `system_context` are no-ops. `system_context` records the platform scope in a ContextVar and restores it on block exit. `rls_scope` answers platform inside `system_context` and in jobs, the principal's scope in a signed-in request, and nothing for an anonymous request. `emit_event(NO_POSTGRES, …)` goes to the Firestore outbox. | `test_no_pg_session_helpers.py` |
| Audit/outbox at the commit point (data-money, data-learning) | Without a Postgres session and without an explicit Firestore transaction, `audit()` (with `TD_STORE_AUDIT=firestore`) and `emit_event()` buffer per request (`app/core/request_commit.py`). Both are written in **one** Firestore transaction when the response starts with status < 500 and no error reached the error handlers. Otherwise they are dropped (the rollback equivalent). Every handler in `install_error_handlers` now calls `audit.mark_failed()`. A store-layer unit of work can write the buffers atomically with its own writes: `audit.pending_docs`/`write_pending`/`mark_written`, `outbox.pending_events`/`write_pending_events`/`mark_events_written`. Outside a request (jobs), writes happen at once. | HTTP tests: success commits both; raised 409 and crash drop both |
| A3 outbox parity | The Firestore relay builds `OutboxMessage` exactly like the Postgres relay: UUID ids, a fresh payload dict, UUID/None organization, a **plain tz-aware UTC datetime** (Firestore's `DatetimeWithNanoseconds` is converted), `attempt` = attempts+1. The order is `pending_at` then id, which equals Postgres `ORDER BY occurred_at, id`. Delivery is at-least-once (a failure is redelivered with attempt 2). The dead letter is the same: attempts ≥ max, `last_error` set, never re-picked. New events store the payload as `payload_json` (JSON text: exact JSONB round-trip, including nested arrays that Firestore maps reject). The relay also reads the `payload` map that sqlstore writes. Dead letters are re-checked against the *current* `TD_OUTBOX_MAX_ATTEMPTS` (no stored verdict), so raising it re-picks them exactly as on Postgres (`test_raising_max_attempts_repicks_dead_letters`). | `test_relay_message_matches_the_postgres_relay`, `test_relay_reads_map_payloads_written_by_the_sql_engine` |
| Buffer API (security pass 2, req. 8) | `app.core.request_commit`: `is_open()`, `checkpoint()` → token, `rollback_to(token)` (drops what was buffered after the token, like ROLLBACK TO SAVEPOINT) and `async with buffer_open():` for code outside a request. `buffer_open` commits the audit rows and outbox events on success and drops them on error. Nested inside a request scope it acts as a savepoint. The private `audit._pending` / `outbox._pending_events` still work. | `test_request_commit_api.py` |
| P1 outbox read API | **`app.core.outbox.read_events(session, *, since, event_types, limit=500, after=None) -> list[OutboxRecord]`**. It is store-neutral: it reads the Postgres `outbox_events` table when Postgres is in use and the Firestore outbox when any module is on Firestore, merges both and orders by `(occurred_at, id)`. `after` = keyset of the previous page's last record. Firestore paging is safe for ties on the same timestamp. `OutboxRecord` has id, event_type, aggregate_type, aggregate_id, payload, organization_id, occurred_at, dispatched_at. **analytics:** replace the direct SQL in `consumer.consume_outbox` with it and filter consumed ids on your side. | `test_outbox_read_api.py` |
| `TD_TEST_NO_PG` auto-skip | The root conftest records every asyncpg/psycopg connect attempt. With `TD_TEST_NO_PG=1`, a test that fails after one is reported **skipped** ("needs Postgres"). This covers own engines and Postgres-backed routes hit through `client`. `@pytest.mark.needs_pg` skips explicitly. Default: inactive. `tests/audit/test_audit_api.py::test_bad_cursor_and_missing_seq` is now skipped. | `tests/platform tests/firestore tests/audit`: 141 passed, 25 skipped |
| A4 backfill hash | `backfill.canonical` turns `bytes`/`bytearray`/`memoryview` into lowercase hex, so Postgres bytea and Firestore Bytes hash identically instead of raising `TypeError`. | `test_backfill_canonical.py` |
| Judge on Firebase (coordinator decision) | `TD_CODING_SEND_TASKS=1` in `functions-lms/.env.example` and in the emulator env. Each submission's `notify_enqueued` sends `coding.judge_submission`. Its `judge_*` queue maps to `lmsTasks` through the default route. A Firebase-only scheduled job `coding.process_pending` (every minute, `lmsJobCodingProcessPending`) is the backstop for the VM worker's polling (`cloudtasks.FIREBASE_ONLY_JOBS`). It is in `schedules.json` (now 32 scheduled functions) and not in the VM's beat. | `test_schedules_json_matches_the_beat_registry` (drift + sweep entry + VM beat unchanged) |
| Coding token TTL | The `lms_coding_testcase_content_tokens` TTL field moved from `expires_at` to `expire_at` (created + 30 days), keeping the 30-per-hour limit and the 30-day retention. | static JSON |

### 9.3 Regression run of every data agent's Firestore suite

Run in the foreground in three chunks (`TD_TEST_NO_PG=1`, unique `TD_TEST_DB_NAME` per chunk,
shared Firestore emulator 18080):

| Chunk | Suites | Result |
|---|---|---|
| A | `tests/platform`, `tests/firestore`, `identity/fs`, `{audit,admin,ai,security,hub}/fs`, `commerce/firestore`, `admissions/firestore` | **325 passed** |
| B | `tests/{catalog,entitlements,media,paths}`, the learning, engage and mentoring fs tests | **119 passed, 125 skipped** (Postgres-only tests, skipped by `TD_TEST_NO_PG`) |
| C | `placement/fs`, `assessments/fs`, `coding/fs` | **59 passed** |

**Total: 503 passed, 0 failed.** An earlier full run showed 6 failures. Each of the 6 passed when
run alone. They came from two runs sharing one emulator project, after a session restart left an
old run alive; the clean chunked runs above have none. After the chunks,
`test_request_commit_api.py` was added: 3 passed.

### 9.4 Requests from this round

- **data-money (sqlstore):**
  1. In `commit_all` / the unit-of-work transaction, write `audit.pending_docs()` and
     `outbox.pending_events()` inside the same Firestore transaction (`write_pending`,
     `write_pending_events`), then call `mark_written` / `mark_events_written` after commit. That
     makes them fully atomic with the business rows. Until then they commit at the end of the
     request.
  2. Consider writing `payload_json` instead of the `payload` map, because nested arrays would
     fail.
- **sessions:** call `request_locks.acquire(f"sess:{user_id}")` in `lock_user` (still open from
  round 2).
- **admin, analytics, coding, assessments (integrity):** the 503 routes in §9.1.

## 10. Round 4 (2026-11-12): Postgres text ordering on Firestore

### 10.1 The VM's collation

| Source | Finding |
|---|---|
| `infra/gcp-demo/docker-compose.yml` → `infra/docker/postgres/Dockerfile` | `FROM postgres:16-bookworm` (official image: `ENV LANG en_US.utf8`). There is no `POSTGRES_INITDB_ARGS` and `db-init/01-roles.sh` creates no database with a locale. |
| Migrations | No `COLLATE` anywhere. `citext` is used in 20 migration files. |
| **Result** | The cluster default is **libc `en_US.utf8`** (glibc 2.36, ISO 14651 tables). `text` sorts by it, and `citext` compares `lower()` values under it. Postgres breaks collation ties with a byte compare (`varstr_cmp`). Not checked on the VM itself (not touched); inferred from the image and the configuration. |

### 10.2 API: `app.core.firestore.collation`

| Function | Use |
|---|---|
| `sort_key(v)` | Postgres `ORDER BY` key of a text value. Non-strings keep their natural order. |
| `citext_key(v)` | `citext` / `ORDER BY lower(x)`. |
| `order_key(v, desc=False, nulls=None, citext=False)` | One key for `sorted(rows, key=..., reverse=desc)` with Postgres NULL placement (ASC = NULLS LAST, DESC = NULLS FIRST, or `nulls="first"/"last"`). |
| `sort_rows(rows, [(getter, desc), ...], nulls={i: "first"})` | Multi-column ORDER BY. |
| `compare(a, b)`, `mode()` | strcmp-style compare; `glibc` (exact) or `uca` (emulated). |

There are two implementations:
- **Exact:** on Linux with the `en_US.UTF-8` locale, `locale.strxfrm` plus the byte tie-break,
  which is Postgres itself.
- **Emulated** (Windows dev machines; Cloud Functions images may lack the locale): UCA via
  **`pyuca`** with *shifted* variable weighting. Spaces and punctuation are ignored on levels 1–3
  and break ties on level 4 in glibc's measured punctuation order. Lower case sorts before upper
  case, accents are compared forwards, and code point is the final tie-break.

PyICU was not used: it cannot be built on Windows, and Cloud Functions has no ICU headers.
`pyuca==1.2` (pure Python) was added to `apps/api/pyproject.toml` and
`functions-lms/requirements.txt`.

Verification: `tests/platform/data/collation_glibc_en_US.json` holds 12 lists sorted by glibc
2.41 `strcoll` + `strcmp` in a Linux shell: mixed case, accents and ligatures (é è ê ß æ å ø ł ñ
ç), punctuation, spaces (leading and trailing), digits and names, plus 6 × 300 random strings.
- The **emulation matches all 1,931 positions**.
- The exact mode also matches; this was run in the Linux shell.

Documented differences of the emulation: DUCET 10.0 vs glibc's newer ISO 14651 table. Symbols and
scripts added after Unicode 10 and some CJK compatibility forms may differ. Currency signs (`$ £ ¥
€ ₹`) are non-ignorable in both.

### 10.3 Where it is used now

- **`sqlstore` ORDER BY** (`Interpreter._sort`, comparator only; re-read just before editing).
  Text uses the collation, citext columns use `lower()`, NULLS LAST/FIRST is the default, and
  explicit `NULLS FIRST/LAST` is now honoured. Tests: `test_sql_engine_order_by_uses_the_collation`.
  The commerce and admissions Firestore suites still pass (182 passed with platform and firestore).
- **Core store layer:** none of its in-memory sorts are on text (outbox order is `(occurred_at,
  uuid)`, which equals Postgres uuid order).
- **Server-side Firestore ordering is different:** `ScopedStore.query(order_by=...)` orders
  strings by UTF-8 bytes, not by the collation. Repositories that sort lists by a text column for
  display must sort in memory with `collation.order_key` / `sort_rows`, or store a sort key.

**Module owners: switch your in-memory text sorts to `app.core.firestore.collation`**:
- security `FindRepo` / `SecSession`;
- learning `fs_store` (its register tests compared against SQLite's binary collation, which is
  not what Postgres does);
- identity and admin lists;
- any `sorted(..., key=lambda r: r["name"])` on text.

### 10.4 Also in this round

| Item | What | Test |
|---|---|---|
| `MemoryTx` = no session | `db.no_session(s)` is True for `None`, `NO_POSTGRES` **and the engine's `MemoryTx`**, so `outbox.read_events` never queries Postgres from a `MemoryTx` context, even with a `DATABASE_URL`. The analytics consumer test's `postgres_enabled` patch can go. `db.no_sql_session(s)` (None/`NO_POSTGRES` only) is what the RLS helpers, `system_context`, `emit_event` and the idempotency savepoint use, because `MemoryTx` emulates GUCs, savepoints and outbox inserts. | `test_memory_tx_counts_as_no_session` |

Tests: the collation tests (17) plus `tests/platform tests/firestore tests/commerce/firestore tests/admissions/firestore` → 182 passed (`TD_TEST_NO_PG=1`). ruff and mypy are clean.
