# One Firebase project for all Tech Drona modules

Status: **in progress** (2026-11-11). Owner decisions of 2026-11-11: one Firebase project
(`billing-f4fe3`, "TechDrona Full LMS", Blaze) for everything; one Firestore database with
module prefixes; `syamgopalmeda@gmail.com` is the only owner; duplicated features are
consolidated in phases; the college data moves to Firestore.

## 1. Layout

| Module | Firestore collections | Who reads/writes | Code | Security |
|---|---|---|---|---|
| Company website + website Admin Panel | `web_*` (47 names, e.g. `web_records`, `web_fee_accounts`, `web_team`) | Browsers (Firebase JS SDK) | `tech drona` repo, prefix added in `src/lib/fsns.js` and `functions/ns.js` | `firestore.rules` **in the website repo**: the only rules file for the project |
| Tech Drona LMS | `lms_*` (only modules switched with `TD_STORE_<MODULE>=firestore`; none today) | FastAPI, Admin SDK | `apps/api/app/core/firestore/collections.py` `physical_name()` | Server-side `ScopedStore`; browsers denied (no rule matches `lms_*`) |
| Colleges Management | `col_*` (planned; data is still SQLite, §4) | College portal, Admin SDK | `apps/college-data/portal` | Browsers denied (no rule matches `col_*`) |

The LMS's main data stays in PostgreSQL on the VM (163 tables). Firestore holds only the modules
that have been moved (MIGRATION-PLAN.md).

Rules and indexes have one owner each, because a deploy replaces the whole set:
- **Rules:** website repo, `npm run deploy:rules`. This repo's `firebase.json` has no `rules` key
  (`tests/firestore/test_store_boundary.py` enforces it). The old deny-all file was removed. The
  website suite `tests/fees.security.test.mjs` "S1" proves that browsers, even the website owner,
  cannot read or write `lms_*`, `col_*` or unprefixed paths.
- **Indexes:** this repo (`firestore.indexes.json`, all `lms_*`). The website repo deploys no
  indexes (it needs none).

## 2. What was migrated (2026-11-11)

From project `techdrona` (Spark), read-only on the source:

| Item | Result |
|---|---|
| Firestore | 107 documents in 8 collections (audit 1, course_public 8, courses 8, notify_samples 45, records 3, settings 1, team 1, visits 40) → same IDs under `web_*`; re-read and compared field-by-field: **108/108 identical** (incl. the added owner entry). Copy refuses to overwrite (`exists: false`), so it is safe to re-run |
| Owner change | `web_team/syamgopalmeda@gmail.com` added as `owner`; `web_team/medasyamgopal@gmail.com` changed from `owner` to `staff`, everything else verbatim. The website rules' `ownerEmail()` is `syamgopalmeda@gmail.com` |
| Firebase Auth | 5 users (Google) imported with the same UIDs (`records/g_<uid>` leads stay linked): 5/5 match on uid, email, verified flag and provider |
| Cloud Storage | none used (files are Firestore chunks) |
| Cloud Functions | none deployed (code updated for `web_*`; deploy needs SMTP/Cashfree secrets) |
| Hosting | new site `techdrona-website` → https://techdrona-website.web.app (web app "TechDrona Company Website"); authorised domains added |

Backups (owner's PC, outside both repos): typed JSON dumps of the source Firestore and Auth export,
in the session scratchpad `export-techdrona/` (`firestore-techdrona-pre-migration.json`,
`auth-techdrona-pre-migration.json`). The source project itself is untouched and remains the
fallback until it is deleted.

## 3. Central login and module switching

- One sign-in page: the LMS `/login` (password + MFA + device and session rules).
- Staff land on `/modules` (`apps/web/src/app/modules/page.tsx`), which lists only the modules the
  user may open (`GET /api/v1/me/modules`, `app/modules/hub/router.py`) and forwards straight to
  the LMS portal when it is the only one. Every LMS staff header has a **Modules** menu
  (`components/shell/ModuleSwitcher.tsx`).
- Permissions per module, reusing each module's own role model:
  LMS = RBAC grants; Colleges Management = Admin role (same rule as the portal proxy);
  Company Website Admin = an active `web_team` entry (owner/staff/trainer/mentor).
- Website Admin without a second sign-in: `/sso/website` → `POST /api/v1/sso/website` (CSRF via the
  BFF) → a one-hour Firebase custom token for the caller's LMS-verified email, issued only to an
  active `web_team` member, passed in the URL fragment → the website calls
  `signInWithCustomToken` and drops the fragment. The website's own checks and rules still apply.
  Audited as `hub.sso.website`. The website login page offers "Sign in with your Tech Drona
  account" first and keeps its password form as a fallback.

**Needs (not done, owner approval required):** a service account for the API on the VM, with
`roles/datastore.user` and `roles/firebaseauth.admin`; its key at a root-only path on the VM,
mounted into `api`, and `FIREBASE_PROJECT_ID=billing-f4fe3` + `FIREBASE_SERVICE_ACCOUNT_FILE` in
`/opt/techdrona/server.env`. Without it the website module is simply hidden in the hub.

## 4. Still to do

1. Owner: enable the **Google** provider (Firebase console → Authentication → Sign-in method) in
   `billing-f4fe3`, then put the auto-created web client ID into the website's
   `VITE_GOOGLE_CLIENT_ID` (One Tap, Gmail sending).
2. Owner: approve the API service account (§3). Then deploy the LMS (hub, `lms_` prefix) and the
   website (SSO button). Deploy only the files of this change on top of the VM's current source:
   the PC working tree also holds other, undeployed LMS work.
3. Cut-over: redirect https://techdrona.web.app to https://techdrona-website.web.app, then run the
   copy once more for documents created in between (copy-if-absent; check `web_visits` /
   `web_records` counts).
4. Colleges Management → Firestore `col_*` (portal storage rewrite; needs the service account).
5. Phased feature consolidation (website mini-LMS → LMS), one feature at a time.
6. About 30 days after cut-over, with the owner's confirmation: delete the old projects
   `techdrona`, `techdrona-colleges` and (already scheduled) `techdrona-colleges-data`.

## 5. Rollback

- Website: `.env` comments hold the old `techdrona` config; rebuild and
  `firebase deploy --only hosting:website --project old-techdrona`. The old project's data was never
  modified.
- Rules: `firebase deploy --only firestore:rules` from the website repo (current) or restore the
  LMS deny-all file (kept in the session scratchpad as `lms-firestore.rules.removed`).
- The `web_*` copy can be deleted without touching anything else (no other module reads it).
