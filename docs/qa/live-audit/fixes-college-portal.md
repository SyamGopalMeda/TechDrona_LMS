# College Data Portal on the Firebase LMS (2026-11-14)

**Problem.** The LMS moved from the VM (Next.js BFF + FastAPI) to Firebase Hosting `techdrona-lms-app` (Vite SPA + Python
functions). The VM's Next route `/college-portal/*` (`apps/web/src/lib/college-portal/proxy.ts`) had no counterpart:
`firebase.json` had headers for `/college-portal/**` but no rewrite, so the SPA fallback served `index.html` and every
Colleges entry point (`/admin/college-data`, nav "Colleges Data") showed the SPA 404.

**Status.** The Cloud Run service and the `lmsApi` function are deployed and verified. The Hosting rewrite and headers
are prepared in `firebase.json`, but **Hosting is not deployed yet**: it goes out with the next SPA deploy.
The VM portal is unchanged and stays as the fallback.

## 1. Design

```
browser ── /college-portal/** ──▶ Firebase Hosting (techdrona-lms-app)
                                    rewrite ──▶ function lmsApi (asia-south1)
                                                 lms_edge/college_portal.py  (port of proxy.ts)
                                                  1. __session cookie → session/device (CookieJar)
                                                  2. in-process GET /api/v1/me/grants + /api/v1/me
                                                     admin only (/admin portal or super_admin grant);
                                                     60 s positive cache (session+device+UA); page loads
                                                     and writes always re-check and count as activity
                                                  3. same-origin check on POST/PATCH/PUT/DELETE
                                                  4. allow-listed headers + x-td-proxy-secret / -user / -role=editor
                                                     + Google ID token (Cloud Run IAM)
                                                ──▶ Cloud Run college-portal (asia-south1, min 0, max 1)
                                                     Node 24 server unchanged, proxy mode (PORTAL_PROXY_SECRET)
                                                     SQLite /data/techdrona.db ── Litestream (1 s) ──▶
                                                     gs://td-college-portal-db-f4fe3/db
```

Why a route in `lmsApi` and not a Hosting rewrite straight to Cloud Run (option b of the brief):

- Hosting forwards only the `__session` cookie, and the LMS packs session/device/CSRF into it (`TD_EDGE_COOKIE_PACKING=session`).
  The edge already unpacks it and calls the API in-process, so the access check needs no network hop, no
  new cookie and no change to the portal.
- The portal keeps its existing proxy-header contract (`x-td-proxy-secret`, `x-td-proxy-user`, `x-td-proxy-role`) and
  never sees an LMS cookie or token. No portal code changed.
- Behaviour copies proxy.ts: 303 to `/login?next=%2Fadmin%2Fcollege-data` for a page load, a 401 page with a
  *Sign in* link inside the frame, 401 JSON for API calls, 403 for non-admins, 503 when access cannot be verified (fail
  closed), 502 `portal_misconfigured` when the upstream refuses the secret or IAM, `Set-Cookie`/`Server` dropped, redirects kept under
  `/college-portal`, 1 MiB body limit.

The Cloud Run service is protected by **two** layers: IAM (`--no-allow-unauthenticated`; only the functions' service
account `534765702239-compute@` has `roles/run.invoker`) **and** the shared secret (the portal answers 401
`proxy_required` without it).

**Hosting headers replace function headers** (verified live: `/api/v1/_bff/csrf` returns Hosting's CSP and
`Cache-Control: no-cache`, not the function's own). The `/**` SPA CSP (`frame-ancestors 'none'`, no map tiles or Google Fonts)
would therefore break the portal and its frame. `firebase.json` adds, after the SPA rules:

| source | headers |
|---|---|
| `/college-portal`, `/college-portal/**` | `X-Frame-Options: SAMEORIGIN`, the portal's own proxy-mode CSP (`frame-ancestors 'self'`, OSM/Carto tiles, Google Fonts, `script-src 'self'`), `Cache-Control: private, no-store` |
| `/college-portal/{css,js,vendor,assets}/**` | `Cache-Control: private, no-cache` (revalidates; the portal answers 304) |

If `apps/college-data/portal/public/index.html` ever gets an inline `<script>`, add its `sha256` hash to
`COLLEGE_PORTAL_CSP` (the portal computes the hash itself, but Hosting's header wins).

## 2. Files changed

| File | Change |
|---|---|
| `functions-lms/lms_edge/college_portal.py` | **new**: the `/college-portal/*` handler |
| `functions-lms/lms_edge/app.py` | routes `/college-portal`, `/college-portal/*` to it (docstring updated) |
| `functions-lms/secrets.txt` | `TD_COLLEGE_PORTAL_SECRET` is now an active secret |
| `functions-lms/.env.billing-f4fe3`, `.env.example` | `TD_COLLEGE_PORTAL_URL=https://college-portal-q3b3zuhb4a-el.a.run.app` |
| `apps/api/tests/platform/test_college_portal_edge.py` | **new**: 9 tests (redirects, 401/403, secret/identity headers, header allow-list, cache, CSRF, bad paths, 503) |
| `apps/college-data/portal/deploy/` | **new**: `cloudrun.Dockerfile` (node:24-slim + Litestream 0.3.13), `entrypoint.sh`, `litestream.yml`, `fetch_seed.mjs`, `cloudbuild.yaml` |
| `apps/college-data/portal/.gcloudignore` | **new**: keeps `data/` (DB, seed JSON with contact details) out of the Cloud Build upload |
| `firebase.json` (lms target) | rewrites `/college-portal` + `/college-portal/**` → `lmsApi`; portal headers (above) |
| `functions-lms/tools/sync_hosting.py` | the two rewrites are managed rewrites (a re-sync keeps them) |
| `apps/lms-spa/src/spa/hosting-headers.ts`, `apps/lms-spa/hosting-headers.json` | the portal header rules (source of `firebase.json` headers). `sync_hosting.py` was re-run and reproduces `firebase.json` byte for byte |

The VM files (`apps/college-data/portal/Dockerfile`, `infra/gcp-demo/*`) are unchanged.

Tests: `pytest tests/platform/test_college_portal_edge.py tests/platform/test_edge.py tests/platform/test_webhooks_edge.py`
→ 28 passed (run from `apps/api` with dummy `DATABASE_*` env; the platform conftest needs no Postgres).

## 3. GCP resources created (project billing-f4fe3)

| Resource | Details |
|---|---|
| Secret `TD_COLLEGE_PORTAL_SECRET` | random 64 characters (never printed); accessors: `college-portal@`, `534765702239-compute@` |
| Bucket `gs://td-college-portal-db-f4fe3` | asia-south1, uniform access, public access prevention enforced, versioning on; `college-portal@` has `roles/storage.objectAdmin` on this bucket only |
| Service account `college-portal@billing-f4fe3.iam.gserviceaccount.com` | runtime identity of the Cloud Run service; no project-level roles |
| Artifact Registry `asia-south1-docker.pkg.dev/billing-f4fe3/college-portal` | image `college-portal:v202611140723` |
| Cloud Run `college-portal` (asia-south1) | revision `college-portal-00001-7sz`; min 0 / max 1 (SQLite has a single writer), no CPU throttling (Litestream syncs in the background), gen2, 512 MiB, `--no-allow-unauthenticated`; `run.invoker` → `534765702239-compute@` |
| Function `lmsApi` | redeployed alone (`functions:lms:lmsApi`) with the new edge route and the secret |

## 4. Data

- Source: the live VM portal, consistent snapshot with `vm.sh portal-backup` (`VACUUM INTO` inside the running
  container; the portal was not stopped or changed). Snapshot `/opt/techdrona/backups/college-portal-20261114T071344Z.db`
  stays on the VM.
- Copied read-only over IAP SSH, sha256 identical on both sides, `PRAGMA integrity_check` = ok. Row counts: colleges 171, branches
  812, contacts 437, targets 1, audit_log 9 (same as the 2026-11-10 migration: nobody has written on the VM since).
- Uploaded to `gs://td-college-portal-db-f4fe3/seed/techdrona.db` (Litestream seed; md5 verified) and
  `.../snapshots/vm-college-portal-20261114T071344Z.db` (kept as a backup). The local copy was deleted. No PII was printed.
- First start (logs): "no matching backups found" → seed restored (3,608,576 bytes) → Litestream generation
  `5021f950b7ab2cd9` written to `gs://td-college-portal-db-f4fe3/db`. From now on every start restores the newest replica; the
  seed is used only when no replica exists (`fetch_seed.mjs` fails rather than start empty).

**The two copies now diverge.** Cloud Run is the copy to use once Hosting is deployed. Changes made on the VM portal after
07:13 UTC 2026-11-14 are not in Cloud Run.

## 5. Commands (for repeat / redeploy)

```bash
P=billing-f4fe3
# image (Cloud Build; run in apps/college-data/portal)
gcloud builds submit --config deploy/cloudbuild.yaml --project $P --region asia-south1 \
  --substitutions _IMAGE=asia-south1-docker.pkg.dev/$P/college-portal/college-portal:<tag> .
# service
gcloud run deploy college-portal --image asia-south1-docker.pkg.dev/$P/college-portal/college-portal:<tag> \
  --region asia-south1 --project $P --service-account college-portal@$P.iam.gserviceaccount.com \
  --min-instances 0 --max-instances 1 --no-cpu-throttling --concurrency 80 --memory 512Mi --cpu 1 \
  --execution-environment gen2 --no-allow-unauthenticated --ingress all --port 8080 --timeout 60 \
  --set-env-vars LITESTREAM_BUCKET=td-college-portal-db-f4fe3 \
  --set-secrets PORTAL_PROXY_SECRET=TD_COLLEGE_PORTAL_SECRET:latest
gcloud run services add-iam-policy-binding college-portal --region asia-south1 --project $P \
  --member serviceAccount:534765702239-compute@developer.gserviceaccount.com --role roles/run.invoker
# function (only lmsApi)
firebase deploy --only functions:lms:lmsApi --project $P
# hosting (with the SPA; NOT done by this fix)
firebase deploy --only hosting:lms --project $P
```

Avoid writes while a new Cloud Run revision rolls out: for a few seconds two instances can run, and both write to the replica.

Backup / point-in-time restore: `litestream restore -o restored.db [-timestamp 2026-11-14T12:00:00Z] gcs://td-college-portal-db-f4fe3/db`
(7 days of WAL history, plus bucket versioning).

## 6. Verification (live, curl)

Through the function URL (`https://lmsapi-q3b3zuhb4a-el.a.run.app`, the same code Hosting will call), because
Hosting is not yet deployed:

| Check | Result |
|---|---|
| `GET /college-portal/index.html`, no session, `Sec-Fetch-Dest: document` | **303** → `/login?next=%2Fadmin%2Fcollege-data` |
| `GET /college-portal/api/colleges`, no session | **401** `auth_required` |
| `GET /college-portal/` | **308** → `/college-portal/index.html` |
| QA admin (`td-qa-creds`, login via `/api/v1/auth/login` on web.app) `GET /college-portal/index.html` | **200** text/html, "Tech Drona — Outreach Portal" |
| QA admin `GET /college-portal/api/session` | `authenticated: true, sso: true, role: editor` |
| QA admin `GET /college-portal/api/colleges` | 200, **171** colleges |
| QA admin `GET /college-portal/js/app.js` | 200 text/javascript |
| QA student `GET /college-portal/api/colleges` / page | **403** `forbidden` / 403 page |
| QA admin cross-site `POST /college-portal/api/calls` | **403** `cross_origin` (never reached the portal) |
| Cloud Run URL directly, no credentials | **403** (IAM) |
| Cloud Run URL with an owner ID token, no secret / wrong secret | **401** `proxy_required` |

No write tests were run against the real data.

**After the Hosting deploy**, run these:

```bash
W=https://techdrona-lms-app.web.app
curl -sI -H 'sec-fetch-dest: document' $W/college-portal/index.html   # 303 → /login?next=%2Fadmin%2Fcollege-data
curl -s  $W/college-portal/api/colleges                                # 401 auth_required
# signed in as admin (browser): /admin/college-data shows the portal framed, 171 colleges, no CSP errors in the console;
# response headers of /college-portal/index.html: the portal CSP with frame-ancestors 'self', X-Frame-Options SAMEORIGIN,
# Cache-Control private, no-store
```

## 7. Rollback

- Hosting: redeploy the previous `firebase.json` (remove the two `/college-portal` rewrites). `/college-portal/*` then falls back to the
  SPA 404 again. Or roll back the Hosting release in the console.
- Function: `lms_edge/college_portal.py` is only reached for `/college-portal*` paths. To disable it, unset
  `TD_COLLEGE_PORTAL_URL` (it then answers 503) or remove the `elif` in `lms_edge/app.py`, and redeploy `functions:lms:lmsApi`.
  Previous revision: `gcloud run services update-traffic lmsapi --to-revisions <prev>=100 --region asia-south1`.
- Cloud Run: `gcloud run services update college-portal --max-instances 0 ...` or delete the service. The data stays in the bucket.
- The VM portal is untouched and still reachable on the VM host (`/admin/college-data`).

## 8. Pending

**Caller (SPA deploy):** deploy Hosting together with the SPA: `firebase deploy --only hosting:lms --project billing-f4fe3`.
`firebase.json`, `hosting-headers.ts` and `hosting-headers.json` already contain the changes, so a `gen-static` + `sync_hosting.py`
run keeps them. Then run the checks in section 6.

**Note:** `firebase deploy --only functions:lms:lmsApi` packaged `functions-lms/app` as it was on disk. That included 5 API
files another agent had synced at 12:45 to 12:47 IST (`admin/accounts.py`, `commerce/tasks.py`, `orgs/router.py`,
`sessions/resolver.py`, `support/service.py`; each identical to `apps/api/app`). They are now live in `lmsApi`
(health 200, no ERROR logs). The other functions (`lmsTasks*`, `lmsScheduler`, `lmsWebhooks`) still run the previous
code.

**Owner:**
1. Approve the Cloud Run copy as the system of record, then retire the VM portal (`college-portal` service in
   `infra/gcp-demo/docker-compose.yml`). Until then, **don't edit data on the VM portal**: VM changes won't reach Cloud Run.
   If someone did edit on the VM, re-seed before first use: take a new `vm.sh portal-backup`, upload it as
   `gs://td-college-portal-db-f4fe3/seed/techdrona.db`, delete `gs://td-college-portal-db-f4fe3/db/`, and redeploy or restart the service.
2. Optional: the VM's own `TD_COLLEGE_PORTAL_SECRET` is a different value. It can be rotated or removed when the VM is retired.
3. Unchanged from 2026-11-10: delete the old `techdrona-colleges-data` resources after ~2026-12-10 (`docs/college-data-portal.md` §6).
