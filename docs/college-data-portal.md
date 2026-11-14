# College Data Portal inside the LMS

Status: integrated and deployed on 2026-11-10 (section 6). **2026-11-14: on the Firebase LMS the portal runs on Cloud Run `college-portal` behind `lmsApi` (Litestream to `gs://td-college-portal-db-f4fe3`); see `docs/qa/live-audit/fixes-college-portal.md`. Sections 1, 4 and 5 describe the VM setup.** The College Data Portal (college outreach: colleges, branches, contacts, calls,
targets, people, enrollments, follow-ups, exam windows, official-source data) used to be a separate app in its own
Firebase/GCP project `techdrona-colleges-data`. It is now part of this repository and of the LMS platform, and runs
in the LMS's GCP/Firebase project `billing-f4fe3` only.

## 1. How it fits

```
browser ── /admin/college-data ──▶ web (Next.js)   LMS admin page: sidebar item "College Data Portal"
   │                                                (Admin › College outreach), renders the portal in a
   │                                                same-origin frame + "Open full screen" link
   └────── /college-portal/* ─────▶ web route handler (src/app/college-portal/[[...path]]/route.ts,
                                     src/lib/college-portal/proxy.ts)
                                       1. LMS session cookie → GET /me/grants + /me on the api
                                          (Admin portal users only; fails closed; 60 s cache keyed on
                                          session + device cookie + user agent; writes and page loads
                                          always re-check and count as LMS activity)
                                       2. same-origin check on POST/PATCH/PUT/DELETE
                                       3. strips /college-portal, forwards an allow-list of headers
                                          + x-td-proxy-secret, x-td-proxy-user (admin name), x-td-proxy-role
                                     ──▶ college-portal (apps/college-data/portal, Node 24 + SQLite)
                                          proxy mode (PORTAL_PROXY_SECRET): refuses every request without
                                          the secret (except GET /api/health); signs the admin in (SSO);
                                          every change is audited under the admin's LMS name
```

- **Single sign-on.** Admins never see the portal's old passcode screen. The LMS session cookie never reaches the
  portal, and the portal's own cookies are dropped by the proxy. When the LMS session ends, the portal sends the top
  window to `/login?next=/admin/college-data`.
- **Who can open it:** anyone who can enter the Admin portal (`super_admin`); they get editor rights in the portal.
  Revoking admin access takes effect within 60 s for reads (auth cache) and immediately for writes; signing out
  takes effect immediately. Changes are audited as "Name (email)" of the LMS account.
- **Session.** Working in the portal keeps the LMS session alive (writes and page loads count as activity). If the
  LMS session still ends, the portal shows "Signed out of the LMS" with *Sign in (new tab)* / *Retry*, so an open
  form is not lost.
- **The sidebar link does a full page load** (`documentNav`), because only this page's own CSP allows the frame;
  reached by client-side routing (back/forward), the page reloads itself once.
- **Security headers.** LMS pages keep `frame-ancestors 'none'` and `X-Frame-Options: DENY`. Only
  `/admin/college-data` adds `'self'` to `frame-src`, and only `/college-portal/*` is frameable (`SAMEORIGIN`,
  `frame-ancestors 'self'`). The LMS middleware skips `/college-portal/` so the portal keeps its own CSP.
- **Standalone mode still works** for local use without the LMS (`./scripts/run-college-portal.ps1 -Standalone` or
  `npm start` in `apps/college-data/portal`); then the old passcode settings apply.

## 2. Firebase / GCP consolidation

The LMS project `billing-f4fe3` ("TechDrona Full LMS") is the only project the platform uses.

| Old (`techdrona-colleges-data`) | What it held | Now |
|---|---|---|
| Hosting `techdrona-colleges-data.web.app` | portal UI | served by the LMS web app at `/college-portal/` (LMS Hosting showcase redirects that path to `/demo`) |
| Cloud Run `techdrona-portal` (asia-south1) | portal API | `college-portal` service in the LMS VM stack (`infra/gcp-demo/docker-compose.yml`) |
| GCS `techdrona-colleges-data-db` (Litestream) | the SQLite DB = **all college data** | migrated (section 3); DB in the `college-portal-data` volume; `vm.sh portal-backup` |
| Firebase web config + Analytics `G-Z0LD0BGQYB` | page analytics | removed from the portal (`public/js/firebase.js` deleted); LMS Analytics covers `/admin/college-data` |
| Secret Manager `portal-passcode`, `portal-viewer-passcode` | portal sign-in | not used (SSO through the LMS) |
| Firestore `(default)` | — | checked 2026-11-10: **no collections** (portal never used it) |
| Firebase Auth | 1 account (owner, never signed in, no provider) | nothing to migrate; LMS accounts are used |

No Firestore rules, Storage rules or Auth settings existed for the portal, so none were migrated. The LMS
`firestore.rules` (deny all client access) is unchanged.

## 3. Data migration (done 2026-11-10)

Source: the live portal's Litestream replica, newest generation `cc144a8c9715fac1` (snapshot 2026-11-09 17:10 UTC,
no writes after it). It is a superset of the local `colleges_data-main/portal/data/techdrona.db`: the only
differences were a "Deploy check" follow-up created and deleted on 2026-11-09 and the official-source cache tables
(`live_*`).

| Table | Rows |
|---|---|
| colleges | 171 |
| branches | 812 |
| contacts | 437 |
| targets | 1 (programme target) |
| audit_log | 9 |
| people, enrollments, calls, follow-ups | 0 (none recorded yet) |

Files (`apps/college-data/portal/data/`, never committed: `*.db` is git-ignored):

- `techdrona.db`: the migrated DB (integrity_check ok).
- `techdrona.backup-2026-11-09-live-cloudrun-snapshot.db`: the raw restored replica.
- `techdrona.backup-2026-11-09-local-pre-integration.db`: the old local DB. Older `techdrona.backup-*` files came along.

The original folder `D:\company website\TECH DRONA LMS\colleges_data-main` was not modified; keep it until the
cutover is confirmed.

**Repeat the migration right before cutover** if anyone used the old portal after 2026-11-09 17:10 UTC:

```bash
gcloud storage ls -l -r gs://techdrona-colleges-data-db/db/ --project techdrona-colleges-data   # newest snapshot = newest generation
gcloud storage cp -r gs://techdrona-colleges-data-db/db ./replica --project techdrona-colleges-data
pip install lz4
python scripts/college-data/restore_litestream_snapshot.py ./replica/db/generations/<newest> ./techdrona.db
```

## 4. Run locally

```powershell
./scripts/dev-up.ps1; ./scripts/run-api.ps1    # LMS as usual
./scripts/run-college-portal.ps1               # portal in proxy mode on 127.0.0.1:4173 (TD_COLLEGE_PORTAL_SECRET from .env)
./scripts/run-web.ps1                          # then sign in as admin → Admin › College Data Portal
```

Env (root `.env`, `.env.example` section 19): `TD_COLLEGE_PORTAL_SECRET` (≥ 32 chars, same value for web and
portal; required in every environment, without it `/college-portal/*` answers 503) and `TD_COLLEGE_PORTAL_URL`
(default `http://127.0.0.1:4173` outside production). A wrong secret shows as 502 "misconfigured", never as a
sign-out.

## 5. Deploy (GCP demo VM, project `billing-f4fe3`)

1. Add `TD_COLLEGE_PORTAL_SECRET=<openssl rand -base64 48>` to `/opt/techdrona/server.env` (and the PC copy).
2. Redeploy the code as in `docs/deploy/gcp-demo.md` §5 (`vm.sh build` now also builds `college-portal`).
3. Upload and import the migrated DB **before** first use (otherwise the portal starts with an empty schema).
   Upload a consistent single file: if a local portal has used the DB since the migration (a `techdrona.db-wal`
   exists next to it), export it first, server stopped or not:
   `node -e "new (require('node:sqlite').DatabaseSync)('apps/college-data/portal/data/techdrona.db').exec(\"VACUUM INTO 'college.db'\")"`.
   `portal-import` checks integrity, refuses a damaged file and backs up the current DB first.
   ```bash
   gcloud compute scp apps/college-data/portal/data/techdrona.db td-lms-demo:college.db $Z --tunnel-through-iap
   $SSH 'sudo bash /opt/techdrona/src/infra/gcp-demo/vm.sh portal-import ~/college.db && rm ~/college.db'
   ```
4. `vm.sh up`, then check: admin sign-in → Admin › College Data Portal shows 171 colleges;
   `https://<host>/college-portal/api/colleges` without a session → 401.
5. Back up: `vm.sh portal-backup` (copy in `/opt/techdrona/backups/`). The VM has no service account, so there is
   no continuous off-site replication as Litestream did; take backups (or disk snapshots) regularly.

Firebase Hosting (`firebase deploy --only hosting --project billing-f4fe3`) only serves the static showcase; it
needs no change for the portal except the new `/college-portal` redirect in `firebase.json`.

## 6. Retire the old project (owner decision, after the cutover is verified)

**Status 2026-11-10 (owner-approved cutover):** live on the LMS VM (`https://35-244-50-26.sslip.io/admin/college-data`),
verified signed in (171 colleges, SSO, no CSP errors). The old portal was frozen (Cloud Run ingress `internal`) before
the final snapshot (generation `5be0f9e87e0766ec`, identical to the migrated DB), and its Hosting site was disabled
(both reversible: `--ingress all`, `firebase deploy`). **Kept until ~2026-12-10** as a backup: bucket
`techdrona-colleges-data-db`, the Cloud Run service (no traffic) and the two secrets. Then run the deletions below.

Not done automatically, because it is irreversible. Suggested order:

```bash
P=techdrona-colleges-data
gcloud run services update techdrona-portal --region asia-south1 --max-instances 0 --project $P  # or delete
firebase hosting:disable --project $P                       # techdrona-colleges-data.web.app stops serving
# keep gs://techdrona-colleges-data-db for 30 days as a backup, then:
gcloud storage rm -r gs://techdrona-colleges-data-db --project $P
gcloud secrets delete portal-passcode portal-viewer-passcode --project $P
# finally, optionally: gcloud projects delete $P
```

## 7. Security notes

- The portal shares the LMS origin, so an XSS bug in the portal would act with the admin's LMS session. Its strict
  CSP (`script-src 'self'` + hashes, no inline handlers) and escaped rendering keep this low; if the portal grows
  (third-party scripts, user-supplied HTML), move it to its own subdomain.
- The portal container has no published port and accepts nothing without the shared secret; it never sees LMS
  cookies or tokens.

## 8. Tests

- Portal: `npm run selftest` (standalone), `npm run test:live`, `npm run test:proxy` (proxy mode/SSO) in
  `apps/college-data/portal`.
- Web: `src/lib/college-portal/proxy.test.ts`, `src/features/college-data/CollegeDataPortal.test.tsx`, CSP and
  middleware tests; end to end: `apps/web/e2e/college-data-portal.integration.spec.ts`.
