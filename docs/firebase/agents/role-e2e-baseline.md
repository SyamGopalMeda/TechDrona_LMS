# Role E2E baseline (browser-driven), 2026-11-13

A browser audit of every role in the LMS SPA. Playwright made real clicks on the sidebar, the account menu, the portal switcher, the logo, the breadcrumbs, the "Find a page" (Ctrl K) palette and the dashboard cards/CTAs. It also opened other portals' pages directly and probed staff APIs. The run was against the **local emulator stack** (Hosting :5000 + Functions :5001 from `functions-lms/tools/emulate.ps1`, shared Firestore emulator :18080). It served the **existing `apps/lms-spa/dist` build (13 Nov 2026 15:56)**, which was not rebuilt. Source fixes made after that build (for example `docs/firebase/agents/role-nav-fix.md`) are **not** part of this baseline. Re-run the audit after a rebuild to measure them.

Scratchpad (not in the repo): `C:\Users\SYAM\AppData\Local\Temp\claude\099c798e4136fab9\88f7fa47-940f-41d2-9f5a-d10548d6f736\scratchpad\` (below: `SCRATCH\`)

- `SCRATCH\role_crawl.cjs`: the reusable crawler. It reads the account list and base URL as parameters.
- `SCRATCH\role_accounts.json`: the account list (email, password, expected home, allowed portals, optional self-grant).
- `SCRATCH\role_resume.cjs`: repro of the owner's bug (account menu → Settings → student Certificates → `/continue` / sign in again).
- `SCRATCH\role_report.cjs`: turns `role_out\role_crawl_<key>.json` into the tables below.
- `SCRATCH\role_seed.py`, `SCRATCH\role_consent.py`, `SCRATCH\role_regrant.cjs`: emulator-only account setup (see "Accounts").
- Output: `SCRATCH\role_out\role_crawl_<key>.json` and `SCRATCH\role_out\shots\<key>-NNN.png` (one per flagged step), plus `SCRATCH\role_out\role_resume_<key>.json` and `shots\resume-<key>.png`.

## How to re-run

```powershell
# 1. stack (shared Firestore emulator on 18080 must be up); -NoSeed once the accounts exist
powershell -ExecutionPolicy Bypass -File functions-lms\tools\emulate.ps1 -NoSeed
# 2. crawl (one headless browser, one context at a time; ~45 min for all six accounts)
$PW = "d:\company website\TECH DRONA LMS\techdrona LMS\apps\web\node_modules\playwright"
cd C:\Users\SYAM\AppData\Local\Temp\claude\099c798e4136fab9\88f7fa47-940f-41d2-9f5a-d10548d6f736\scratchpad
node role_crawl.cjs $PW role_accounts.json --base=http://127.0.0.1:5000 > crawl.log      # all accounts
node role_crawl.cjs $PW --only=admin,trainer                                               # a subset
node role_crawl.cjs $PW --quick                                                            # first 6 nav items/portal
node role_resume.cjs $PW --key=admin                                                       # owner's bug repro
node role_report.cjs > role_tables.md                                                      # tables
```

Options:

- `--apiConcurrency=N` (default 2) throttles `/api` requests in the browser. The Functions emulator starts one ~180 MB Python worker per concurrent request, and with no throttle the PC ran out of memory and the emulator died (`FATAL ERROR: Zone Allocation failed`). Use `--apiConcurrency=0` against a real deployment.
- `--settle=ms` (default 2200) is the wait after each navigation.
- `--noise=<regex>` sets which console errors are ignored. The default ignores the website `catalog.json` CORS error, which is specific to the 127.0.0.1 origin.
- `--out=dir` sets the output directory.

Each line of the crawl log is `[role] kind item -> final URL (sidebar badge)`, followed by `!! flags`, `api:` (failed `/api/v1` calls with status 400 or higher) and `console:`.

Flags the crawler raises:

- **cross-portal**: the final URL's portal differs from the clicked item's portal (or, for the account menu, from the portal it was opened in).
- **shown portal not allowed for role**: the role landed in a portal it should not see.
- **shell mismatch**: the URL portal differs from the sidebar badge.
- **API 5xx**.
- **API 403/404 on allowed page**.
- **error text**: matches "not found", "permission", "unavailable", "try again" and similar in `<main>`. "AI & apps" is a known false positive, because its help text says "unavailable".
- **blank page**: `<main>` holds fewer than 25 characters. These were all a skeleton that was still loading under the throttle; check the screenshot.
- **console errors**.
- **forbidden portal content rendered**.
- **API probe 2xx**: a role that should not read staff data got a 2xx.

## Accounts (emulator only)

| key | account | grants | notes |
|---|---|---|---|
| student | student@dev.techdrona.local | (none; self-signup) | seeded by emulate.ps1 |
| trainer | audit-trainer@dev.techdrona.local | trainer@batch AUDIT-BATCH | created with must_change_password and no consents. First login: /change-password worked, then /accept-terms **failed** (D6). Consents were then recorded directly (`role_consent.py`) |
| evaluator | audit-evaluator@dev.techdrona.local | evaluator@batch AUDIT-BATCH | |
| content_manager | audit-content@dev.techdrona.local | content_manager@platform | |
| admin | admin@dev.techdrona.local | super_admin@platform | seeded by emulate.ps1 |
| admin_trainer | audit-admin2@dev.techdrona.local | super_admin@platform + **self-granted** trainer@batch (`POST rbac/grants`, 201) | the "Your Teacher Portal" case |

Batch `AUDIT-BATCH` (`01a1d5bb-e0c4-76fb-b95c-31bda5617995`) was created through `POST batches` as the admin. `POST admin/users` failed with 503 (D6), so the four audit users were written with the identity/rbac public APIs (`role_seed.py`, same path as `seed_emulator.py`).

The first seed gave the batch grants `organization_id = null`. With those grants the trainer dashboard said **"Not found"** (`GET batches/{id}` → 404, log `cross_tenant_denied permission=org.member.read`), and the evaluator Tests and Integrity pages said "You don't have permission". The grants were then revoked and re-made through the admin API (`role_regrant.cjs`, `POST rbac/grants` 201), and the tables below are from that state. `role_seed.py` now sets the batch org.

**Note for the live QA accounts:** `scratchpad\qa_accounts.py`, used on LIVE billing-f4fe3, also writes batch grants with `organization_id=None`. Its qa-trainer and qa-evaluator would hit the same false "Not found" / "no permission" pages. Re-grant them through the Role grants UI before testing them.

## Summary per role

| role | landing after sign-in | `/` · `/continue` · `/modules` | own sidebar (every item clicked) | other portals (goto home + deep pages) | staff API probes | sign-out |
|---|---|---|---|---|---|---|
| student | /app ✔ | /app ✔ | 23/23 OK in the Student shell | all 21 → /app ✔ (no staff content) | all 403/404 ✔ (`admin/approvals` 200 = own rows only, by design) | ✔ |
| trainer | /trainer ✔ | /trainer ✔ | 9/9 OK | all → /trainer ✔ | 403 ✔ (`batches`, `studio/questions`, `studio/courses` 200: own batch / trainer authoring, matrix) | ✔ |
| evaluator | /evaluator ✔ | /evaluator ✔ | 3/3 render; Integrity flags gets a silent 403 on `batches/{id}` (D7) | all → /evaluator ✔ | 403 ✔ | ✔ |
| content_manager | /studio ✔ | /studio ✔ | 11/11 OK | all → /studio ✔ | 403, **except `admin/certificates` 200** (D9) | ✔ |
| admin | **/modules** (module hub; D10) | /modules | 45/45 Admin nav items stay in the Admin shell; Colleges Data 404 on the emulator only (E1) | admin may open all portals; **Studio pages error** (D4) | 200 ✔ (studio/questions 403, D4) | ✔ |
| admin_trainer | /modules | `/continue` → **/app** (D2) | as admin. Switcher shows Admin + Trainer. Dashboard card "Your Teacher Portal" → /trainer ✔ and /trainer/batches/{id} ✔ | as admin; Studio taxonomy/companies/coding error (D4) | as admin | ✔ |

In every staff portal the account menu "Settings" leads into the **Student portal** (D1). This is the main defect.

## Defects

Severity: High = wrong portal or broken core flow; Medium = a page a role should use errors out; Low = UX or consistency; Env = specific to the emulator.

1. **D1 (High). The account menu "Settings" moves every staff role into the Student portal (the owner's bug; confirmed).**
   - Roles: admin, admin_trainer, content_manager, trainer, evaluator, from each of their portals (/admin, /studio, /trainer, /evaluator).
   - Steps: open the avatar menu, then click Settings.
   - Expected: settings inside the user's own portal shell.
   - Actual: `/app/settings/profile` with the **"Student portal"** badge and the full student sidebar (My learning, Certificates, Billing…). Clicking the student sidebar's **Certificates** then lands on `/app/certificates` in the Student portal, exactly as the owner reported.
   - Screenshots: `shots\admin-019.png`, `shots\admin-020.png`, `shots\content_manager-002/003.png`, `shots\evaluator-004/005.png`, `shots\trainer-002/003.png`, `shots\admin_trainer-009/010.png`.
   - Cause: `PortalShell` account links go to `/app/settings/profile` for staff.
2. **D2 (High). Once a staff member has visited a /app page, `/continue` and the next sign-in send them back into the Student portal.**
   - Steps (`role_resume.cjs`, admin and content_manager):
     1. Sign in.
     2. Account menu → Settings.
     3. Student sidebar → Certificates.
     4. Open `/continue` (or `/continue?area=lms`, which is what the website account icon, the module hub and the Modules menu use).
     5. Clear the session cookies without signing out (session expiry) and sign in again.
   - Expected: the user's own portal or the module hub.
   - Actual: `/app/certificates`, Student portal, every time. `td.last_page` holds `/app/certificates` and `allowedFor()` accepts `/app` for an account whose `me/grants` portals are only `["/admin"]` or `["/studio"]`. admin_trainer's `/continue` went to `/app` in the main crawl.
   - Screenshots: `shots\resume-admin.png`, `shots\resume-content_manager.png`; `role_out\role_resume_admin.json`.
3. **D3 (High). /app has no role gate. Staff-only accounts get the full Student portal.**
   - `me/grants` portals are `["/admin"]`, `["/studio"]`, `["/trainer"]` and `["/evaluator"]` (none include `/app`). Even so, admin, content_manager, trainer and evaluator can open `/app` and every student page.
   - Each of the 23 sidebar items, the dashboard CTAs and the palette rendered the student UI with the student nav. The student APIs answered with the caller's own (empty) data, so no other user's data was exposed.
   - Expected: a staff-only account is sent to its home portal, except for shared account pages (settings, account status).
   - Rows: `portal-home /app` and the following `/app` rows in the trainer, evaluator, content_manager and admin tables.
4. **D4 (Medium). The Admin can open the Content studio, but most Studio pages fail with "You don't have permission to do this".**
   - `StaffPortalGate` admits super_admin into every staff portal, and the Admin dashboard has a CTA to `/studio/courses`. However, `super_admin` lacks `question.*`, `taxonomy.manage` and similar permissions (the catalogue gives them to content_manager only).
   - Studio dashboard: 403 on `GET studio/questions?status=draft` and on `studio/question-reports` (the counts stay silently empty).
   - Pages that show the error box:
     - Reported errors (`studio/question-reports`)
     - Taxonomy (`studio/topics`)
     - Companies (`studio/companies`)
     - All questions (`studio/questions`)
     - Question banks (`studio/question-banks`)
     - Coding problems (`studio/coding/problems`)
   - admin_trainer: Taxonomy, Companies and Coding problems fail the same way. Its trainer@batch grant makes the questions pages work.
   - Expected: either hide Studio from the Admin (gate, CTA, and an admin-to-studio switcher if wanted) or give the Admin read access.
   - Screenshots: `shots\admin-003.png` … `shots\admin-015.png`, `shots\admin_trainer-003/004/005.png`.
5. **D5 (Low). The Admin has no portal switcher.**
   - `me/grants` for super_admin returns `portals: ["/admin"]`, so "Switch portal" is never shown.
   - The Admin can reach /studio, /trainer and /evaluator only by typing the URL or through the dashboard CTA (studio).
   - The gate and the switcher disagree on which portals the Admin has. Combined with D4, the Admin can wander into a portal that does not work for them.
   - admin_trainer does get the switcher (Admin, Trainer).
6. **D6 (High, backend; seen on the emulator; check on deployed). Writes that emit an outbox event fail with 503 in `lmsApi`.**
   - Failing calls:
     - `POST admin/users` (Admin → Users → Add user): every attempt returned 503.
     - `POST me/consents` (first-login **/accept-terms**): the user stays on /accept-terms with "Service unavailable". The trainer's first login could not finish.
   - Every sign-in also logs `request_commit_failed error=LookupError`.
   - Traceback: `fs_rows.emit_any → core_store.emit_event_firestore → store.run_transaction → jobhints.after_commit → kick → _enqueue → scheduler.entry_for` → `LookupError: unknown periodic job 'core.outbox_relay'`.
   - The periodic-job registry is filled by `app/worker.py` (`register_periodic`). The `lmsApi` function never imports it; only the task and scheduler functions import it via `celery_app()`. `jobhints.active()` is true because `TD_TASKS_BACKEND=cloudtasks` and there is no Postgres.
   - `functions-lms/app/core/jobhints.py` was modified today at 15:02. If that version is deployed, the live site has the same failure.
   - `POST batches` and `POST rbac/grants` still answered 201.
   - Log: `SCRATCH\role_emu.log` lines 281-494 and `SCRATCH\role_emu2.log`.
7. **D7 (Low). Evaluator → Integrity flags makes a silent 403.**
   - The page calls `GET batches/{batch_id}`, which answers 403 for an evaluator@batch (it needs `org.member.read`).
   - The page still renders. The batch name or filter is probably missing.
   - Trainers get 200 on the same call.
8. **D8 (Low, UX). "Find a page" ranks section matches above label matches.**
   - Student "tests" + Enter → **Practice** (section "Practice & tests"), not "Tests".
   - Studio "tests" → All questions.
   - Admin "settings" → Audit log (section "Settings").
   - Admin "tests" and Trainer/Evaluator "certificates"/"settings" → no match. There is no Settings entry in any staff palette, because Settings exists only as the /app account link.
   - The palette never offered a page from another portal (good).
9. **D9 (Info, needs a decision). A content manager can list every certificate through the API.**
   - `GET admin/certificates` → 200 for content_manager. The route needs `certificate.issue_manual`, which the role matrix grants to content_manager at platform scope.
   - The response holds learner names and verification data, and no Studio UI uses it.
   - Confirm this is intended or narrow it.
10. **D10 (Info). Admin sign-in lands on `/modules` (module hub), not `/admin`.**
    - This is by design: `STAFF_LANDING = /continue` falls back to the hub when the account has more than one module (LMS, Colleges, Website).
    - It differs from the expected "admin → /admin". Once D2 is fixed, the hub's LMS card goes to `/admin`.
11. **E1 (Env). Colleges Data (`/college-portal/index.html`) → 404 "Page not found" on the emulator.** `college-portal/` is deployed by the overlay and is not in `apps/lms-spa/dist`. Not a product bug.
12. **E2 (Env).** Ignored by default:
    - Console `Access to fetch at https://techdrona-website.web.app/catalog.json … blocked by CORS` on /app pages: the website allows only the production LMS origin.
    - Occasional `429 POST analytics/events`.
    - Student `/modules` "blank page": a skeleton still loading under the throttle; it lands on /app.

What passed:

- Login landing for student, trainer, evaluator and content_manager.
- Forbidden access for every role. Each `goto` into another portal's home or deep pages redirected to the role's own home portal, never rendered the other portal's content, and the staff API probes answered 403.
- No shell mismatch: the sidebar badge always matched the URL's portal. Admin sections /finance, /desk, /security and /mentor show the Admin nav with an "Admin · …" badge.
- Logo, breadcrumbs and the admin_trainer switcher entries.
- Sign-out from the account menu for every role (revisiting home → `/login?next=…`).
- admin_trainer self-grant (201), the "Your Teacher Portal" card → /trainer, and the Teacher-portal batch page.
- Forced /change-password worked.

## Per-role tables (final URL, portal shown, errors)

`portal shown` is the sidebar badge (`<title> portal`). The trainer and evaluator tables are from the re-run with the API-made grants. The earlier runs are kept as `role_out\role_crawl_trainer_firstlogin.json` (stuck on /accept-terms, D6) and `role_crawl_trainer_seedgrant.json` / `role_crawl_evaluator_seedgrant.json` (null-org grants).

### student (student@dev.techdrona.local, expected home /app)

- login: {"firstUrl":"/app"}
- me/grants: {"portals":["/app"],"roles":[]}
- switcher: {"root":"/app","entries":"not shown"}
- account-menu: {"root":"/app","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"/app/account-status","label":"Account status"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- api-probes: {"probes":[{"ep":"admin/users","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"rbac/grants","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"admin/feature-flags","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"finance/refunds","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"security/incidents","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"security/restrictions","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"admin/certificates","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"studio/questions","ok":["admin","studio"],"status":403,"code":"permission_denied"},{"ep":"studio/courses","ok":["admin","studio"],"status":403,"code":"permission_denied"},{"ep":"batches","ok":["admin","trainer","evaluator"],"status":403,"code":"permission_denied"}]}
- sign-out (account menu): landed /login; revisiting /app -> /login?next=%2Fapp

| # | kind | item | final URL | portal shown (sidebar badge) | API >=400 | console | flags |
|---|---|---|---|---|---|---|---|
| 1 | login | (after sign-in) | /app | Student portal |  |  |  |
| 2 | goto | / | /app | Student portal |  |  |  |
| 3 | goto | /continue | /app | Student portal |  |  |  |
| 4 | goto | /modules | /app | Student portal |  |  | blank page (student-001.png) |
| 5 | portal-home | /app | /app | Student portal |  |  |  |
| 6 | nav | Dashboard [/app] | /app | Student portal |  |  |  |
| 7 | nav | My learning [/app/learning] | /app/learning | Student portal |  |  |  |
| 8 | nav | My classes [/app/classes] | /app/classes | Student portal |  |  |  |
| 9 | nav | Explore courses [/app/courses] | /app/courses | Student portal |  |  |  |
| 10 | nav | My registrations [/app/registrations] | /app/registrations | Student portal |  |  |  |
| 11 | nav | My paths [/app/path/my] | /app/path/my | Student portal |  |  |  |
| 12 | nav | Assignments [/app/assignments] | /app/assignments | Student portal |  |  |  |
| 13 | nav | Live activities [/app/engage] | /app/engage | Student portal |  |  |  |
| 14 | nav | Certificates [/app/certificates] | /app/certificates | Student portal |  |  |  |
| 15 | nav | Practice [/app/practice] | /app/practice | Student portal |  |  |  |
| 16 | nav | Tests [/app/tests] | /app/tests | Student portal |  |  |  |
| 17 | nav | Coding [/app/coding] | /app/coding | Student portal |  |  |  |
| 18 | nav | Progress [/app/progress] | /app/progress | Student portal |  |  |  |
| 19 | nav | Free diagnostic [/app/diagnostic] | /app/diagnostic | Student portal |  |  |  |
| 20 | nav | Interview prep [/app/interview-prep] | /app/interview-prep | Student portal |  |  |  |
| 21 | nav | Mock interviews [/app/mentoring] | /app/mentoring | Student portal |  |  |  |
| 22 | nav | Résumé builder [/app/resume] | /app/resume | Student portal |  |  |  |
| 23 | nav | Company paths [/app/companies] | /app/companies | Student portal |  |  |  |
| 24 | nav | Notifications [/app/notifications] | /app/notifications | Student portal |  |  |  |
| 25 | nav | Billing [/app/billing] | /app/billing | Student portal |  |  |  |
| 26 | nav | My access [/app/access] | /app/access | Student portal |  |  |  |
| 27 | nav | Support [/app/support] | /app/support | Student portal |  |  |  |
| 28 | nav | Profile & settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 29 | cta | /app -> /app/learning | /app/learning | Student portal |  |  |  |
| 30 | cta | /app -> /app/assignments | /app/assignments | Student portal |  |  |  |
| 31 | cta | /app -> /app/tests | /app/tests | Student portal |  |  |  |
| 32 | cta | /app -> /app/certificates | /app/certificates | Student portal |  |  |  |
| 33 | cta | /app -> /app/courses | /app/courses | Student portal |  |  |  |
| 34 | cta | /app -> /app/courses/nextgen-career-accelerator-2026/register | /app/courses/nextgen-career-accelerator-2026/register | Student portal |  |  |  |
| 35 | cta | /app -> /app/practice | /app/practice | Student portal |  |  |  |
| 36 | cta | /app -> /app/diagnostic | /app/diagnostic | Student portal |  |  |  |
| 37 | cta | /app -> /app/mentoring | /app/mentoring | Student portal |  |  |  |
| 38 | cta | /app -> /app/resume | /app/resume | Student portal |  |  |  |
| 39 | cta | /app -> /app/notifications | /app/notifications | Student portal |  |  |  |
| 40 | cta | /app -> /app/support | /app/support | Student portal |  |  |  |
| 41 | cta | /app -> /app/billing | /app/billing | Student portal |  |  |  |
| 42 | cta | /app -> /app/access | /app/access | Student portal |  |  |  |
| 43 | palette | /app "certificates" | /app/certificates | Student portal |  |  |  |
| 44 | palette | /app "settings" | /app/settings/profile | Student portal |  |  |  |
| 45 | palette | /app "courses" | /app/courses | Student portal |  |  |  |
| 46 | palette | /app "tests" | /app/practice | Student portal |  |  |  |
| 47 | logo | sidebar logo from /app/learning | /app | Student portal |  |  |  |
| 48 | account-menu | /app -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 49 | account-menu | /app -> Account status [/app/account-status] | /app/account-status | Student portal |  |  |  |
| 50 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 51 | forbidden | /admin | /app | Student portal |  |  |  |
| 52 | forbidden | /admin/users | /app | Student portal |  |  |  |
| 53 | forbidden | /admin/roles | /app | Student portal |  |  |  |
| 54 | forbidden | /admin/certificates | /app | Student portal |  |  |  |
| 55 | forbidden | /finance/orders | /app | Student portal |  |  |  |
| 56 | forbidden | /desk | /app | Student portal |  |  |  |
| 57 | forbidden | /security/cases | /app | Student portal |  |  |  |
| 58 | forbidden | /mentor/students | /app | Student portal |  |  |  |
| 59 | forbidden | /studio | /app | Student portal |  |  |  |
| 60 | forbidden | /studio/questions | /app | Student portal |  |  |  |
| 61 | forbidden | /studio/courses | /app | Student portal |  |  |  |
| 62 | forbidden | /trainer | /app | Student portal |  |  |  |
| 63 | forbidden | /trainer/grading | /app | Student portal |  |  |  |
| 64 | forbidden | /trainer/tests | /app | Student portal |  |  |  |
| 65 | forbidden | /evaluator | /app | Student portal |  |  |  |
| 66 | forbidden | /evaluator/tests | /app | Student portal |  |  |  |
| 67 | forbidden | /evaluator/integrity | /app | Student portal |  |  |  |

### trainer (audit-trainer@dev.techdrona.local, expected home /trainer)

- login: {"firstUrl":"/login"}
- me/grants: {"portals":["/trainer"],"roles":["trainer@batch"]}
- switcher: {"root":"/trainer","entries":"not shown"}
- account-menu: {"root":"/trainer","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- switcher: {"root":"/app","entries":"not shown"}
- account-menu: {"root":"/app","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"/app/account-status","label":"Account status"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- api-probes: {"probes":[{"ep":"admin/users","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"rbac/grants","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"admin/feature-flags","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"finance/refunds","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"security/incidents","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"security/restrictions","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"admin/certificates","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"studio/questions","ok":["admin","studio"],"status":200,"code":null},{"ep":"studio/courses","ok":["admin","studio"],"status":200,"code":null},{"ep":"batches","ok":["admin","trainer","evaluator"],"status":200,"code":null}]}
- sign-out (account menu): landed /login; revisiting /trainer -> /login?next=%2Ftrainer

| # | kind | item | final URL | portal shown (sidebar badge) | API >=400 | console | flags |
|---|---|---|---|---|---|---|---|
| 1 | login | (after sign-in) | /trainer | Trainer portal | 401 POST auth/login |  |  |
| 2 | goto | / | /trainer | Trainer portal |  |  |  |
| 3 | goto | /continue | /trainer | Trainer portal |  |  |  |
| 4 | goto | /modules | /trainer | Trainer portal |  |  |  |
| 5 | portal-home | /trainer | /trainer | Trainer portal |  |  |  |
| 6 | nav | Dashboard [/trainer] | /trainer | Trainer portal |  |  |  |
| 7 | nav | Courses [/trainer/courses] | /trainer/courses | Trainer portal |  |  |  |
| 8 | nav | Learning paths [/trainer/paths] | /trainer/paths | Trainer portal |  |  |  |
| 9 | nav | Articles [/trainer/paths/articles] | /trainer/paths/articles | Trainer portal |  |  |  |
| 10 | nav | Engage [/trainer/engage] | /trainer/engage | Trainer portal |  |  |  |
| 11 | nav | Grading [/trainer/grading] | /trainer/grading | Trainer portal |  |  |  |
| 12 | nav | Assignments [/trainer/assignments] | /trainer/assignments | Trainer portal |  |  |  |
| 13 | nav | Tests [/trainer/tests] | /trainer/tests | Trainer portal |  |  |  |
| 14 | nav | Integrity flags [/trainer/integrity] | /trainer/integrity | Trainer portal |  |  |  |
| 15 | cta | /trainer -> /trainer/batches/01a1d5bb-e0c4-76fb-b95c-31bda5617995 | /trainer/batches/01a1d5bb-e0c4-76fb-b95c-31bda5617995 | Trainer portal |  |  |  |
| 16 | cta | /trainer -> /trainer/grading | /trainer/grading | Trainer portal |  |  |  |
| 17 | cta | /trainer -> /trainer/integrity | /trainer/integrity | Trainer portal |  |  |  |
| 18 | cta | /trainer -> /trainer/tests | /trainer/tests | Trainer portal |  |  |  |
| 19 | cta | /trainer -> /trainer/courses | /trainer/courses | Trainer portal |  |  |  |
| 20 | cta | /trainer -> /trainer/engage/new | /trainer/engage/new | Trainer portal |  |  |  |
| 21 | cta | /trainer -> /trainer/paths | /trainer/paths | Trainer portal |  |  |  |
| 22 | palette | /trainer "certificates" | /trainer | Trainer portal |  |  |  |
| 23 | palette | /trainer "settings" | /trainer | Trainer portal |  |  |  |
| 24 | palette | /trainer "courses" | /trainer/courses | Trainer portal |  |  |  |
| 25 | palette | /trainer "tests" | /trainer/tests | Trainer portal |  |  |  |
| 26 | logo | sidebar logo from /trainer/courses | /trainer | Trainer portal |  |  |  |
| 27 | breadcrumb | /trainer/paths/articles -> /trainer/paths | /trainer/paths | Trainer portal |  |  |  |
| 28 | account-menu | /trainer -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  | cross-portal: expected trainer got student (trainer-001.png) |
| 29 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 30 | portal-home | /app | /app | Student portal |  |  |  |
| 31 | nav | Dashboard [/app] | /app | Student portal |  |  |  |
| 32 | nav | My learning [/app/learning] | /app/learning | Student portal |  |  |  |
| 33 | nav | My classes [/app/classes] | /app/classes | Student portal |  |  |  |
| 34 | nav | Explore courses [/app/courses] | /app/courses | Student portal |  |  |  |
| 35 | nav | My registrations [/app/registrations] | /app/registrations | Student portal |  |  |  |
| 36 | nav | My paths [/app/path/my] | /app/path/my | Student portal |  |  |  |
| 37 | nav | Assignments [/app/assignments] | /app/assignments | Student portal |  |  |  |
| 38 | nav | Live activities [/app/engage] | /app/engage | Student portal |  |  |  |
| 39 | nav | Certificates [/app/certificates] | /app/certificates | Student portal |  |  |  |
| 40 | nav | Practice [/app/practice] | /app/practice | Student portal |  |  |  |
| 41 | nav | Tests [/app/tests] | /app/tests | Student portal |  |  |  |
| 42 | nav | Coding [/app/coding] | /app/coding | Student portal |  |  |  |
| 43 | nav | Progress [/app/progress] | /app/progress | Student portal |  |  |  |
| 44 | nav | Free diagnostic [/app/diagnostic] | /app/diagnostic | Student portal |  |  |  |
| 45 | nav | Interview prep [/app/interview-prep] | /app/interview-prep | Student portal |  |  |  |
| 46 | nav | Mock interviews [/app/mentoring] | /app/mentoring | Student portal |  |  |  |
| 47 | nav | Résumé builder [/app/resume] | /app/resume | Student portal |  |  |  |
| 48 | nav | Company paths [/app/companies] | /app/companies | Student portal |  |  |  |
| 49 | nav | Notifications [/app/notifications] | /app/notifications | Student portal |  |  |  |
| 50 | nav | Billing [/app/billing] | /app/billing | Student portal |  |  |  |
| 51 | nav | My access [/app/access] | /app/access | Student portal |  |  |  |
| 52 | nav | Support [/app/support] | /app/support | Student portal |  |  |  |
| 53 | nav | Profile & settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 54 | cta | /app -> /app/learning | /app/learning | Student portal |  |  |  |
| 55 | cta | /app -> /app/assignments | /app/assignments | Student portal |  |  |  |
| 56 | cta | /app -> /app/tests | /app/tests | Student portal |  |  |  |
| 57 | cta | /app -> /app/certificates | /app/certificates | Student portal |  |  |  |
| 58 | cta | /app -> /app/courses | /app/courses | Student portal |  |  |  |
| 59 | cta | /app -> /app/courses/nextgen-career-accelerator-2026/register | /app/courses/nextgen-career-accelerator-2026/register | Student portal |  |  |  |
| 60 | cta | /app -> /app/practice | /app/practice | Student portal |  |  |  |
| 61 | cta | /app -> /app/resume | /app/resume | Student portal |  |  |  |
| 62 | cta | /app -> /app/notifications | /app/notifications | Student portal |  |  |  |
| 63 | cta | /app -> /app/support | /app/support | Student portal |  |  |  |
| 64 | cta | /app -> /app/billing | /app/billing | Student portal |  |  |  |
| 65 | cta | /app -> /app/access | /app/access | Student portal |  |  |  |
| 66 | palette | /app "certificates" | /app/certificates | Student portal |  |  |  |
| 67 | palette | /app "settings" | /app/settings/profile | Student portal |  |  |  |
| 68 | palette | /app "courses" | /app/courses | Student portal |  |  |  |
| 69 | palette | /app "tests" | /app/practice | Student portal |  |  |  |
| 70 | logo | sidebar logo from /app/learning | /app | Student portal |  |  |  |
| 71 | account-menu | /app -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 72 | account-menu | /app -> Account status [/app/account-status] | /app/account-status | Student portal |  |  |  |
| 73 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 74 | owner-bug | /trainer account menu -> Settings | /app/settings/profile | Student portal |  |  | cross-portal: expected trainer got student (trainer-002.png) |
| 75 | owner-bug | then student sidebar -> Certificates | /app/certificates | Student portal |  |  | cross-portal: expected trainer got student (trainer-003.png) |
| 76 | forbidden | /admin | /trainer | Trainer portal |  |  |  |
| 77 | forbidden | /admin/users | /trainer | Trainer portal |  |  |  |
| 78 | forbidden | /admin/roles | /trainer | Trainer portal |  |  |  |
| 79 | forbidden | /admin/certificates | /trainer | Trainer portal |  |  |  |
| 80 | forbidden | /finance/orders | /trainer | Trainer portal |  |  |  |
| 81 | forbidden | /desk | /trainer | Trainer portal |  |  |  |
| 82 | forbidden | /security/cases | /trainer | Trainer portal |  |  |  |
| 83 | forbidden | /mentor/students | /trainer | Trainer portal |  |  |  |
| 84 | forbidden | /studio | /trainer | Trainer portal |  |  |  |
| 85 | forbidden | /studio/questions | /trainer | Trainer portal |  |  |  |
| 86 | forbidden | /studio/courses | /trainer | Trainer portal |  |  |  |
| 87 | forbidden | /evaluator | /trainer | Trainer portal |  |  |  |
| 88 | forbidden | /evaluator/tests | /trainer | Trainer portal |  |  |  |
| 89 | forbidden | /evaluator/integrity | /trainer | Trainer portal |  |  |  |

### evaluator (audit-evaluator@dev.techdrona.local, expected home /evaluator)

- login: {"firstUrl":"/evaluator"}
- me/grants: {"portals":["/evaluator"],"roles":["evaluator@batch"]}
- switcher: {"root":"/evaluator","entries":"not shown"}
- account-menu: {"root":"/evaluator","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- switcher: {"root":"/app","entries":"not shown"}
- account-menu: {"root":"/app","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"/app/account-status","label":"Account status"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- api-probes: {"probes":[{"ep":"admin/users","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"rbac/grants","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"admin/feature-flags","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"finance/refunds","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"security/incidents","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"security/restrictions","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"admin/certificates","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"studio/questions","ok":["admin","studio"],"status":403,"code":"permission_denied"},{"ep":"studio/courses","ok":["admin","studio"],"status":403,"code":"permission_denied"},{"ep":"batches","ok":["admin","trainer","evaluator"],"status":403,"code":"permission_denied"}]}
- sign-out (account menu): landed /login; revisiting /evaluator -> /login?next=%2Fevaluator

| # | kind | item | final URL | portal shown (sidebar badge) | API >=400 | console | flags |
|---|---|---|---|---|---|---|---|
| 1 | login | (after sign-in) | /evaluator | Evaluator portal |  |  |  |
| 2 | goto | / | /evaluator | Evaluator portal |  |  |  |
| 3 | goto | /continue | /evaluator | Evaluator portal |  |  |  |
| 4 | goto | /modules | /evaluator | Evaluator portal |  |  |  |
| 5 | portal-home | /evaluator | /evaluator | Evaluator portal |  |  |  |
| 6 | nav | Grading [/evaluator] | /evaluator | Evaluator portal |  |  |  |
| 7 | nav | Tests [/evaluator/tests] | /evaluator/tests | Evaluator portal |  |  |  |
| 8 | nav | Integrity flags [/evaluator/integrity] | /evaluator/integrity | Evaluator portal | 403 GET batches/01a1d5bb-e0c4-76fb-b95c-31bda5617995 |  | API 403/404 on allowed page (evaluator-001.png) |
| 9 | palette | /evaluator "certificates" | /evaluator | Evaluator portal |  |  |  |
| 10 | palette | /evaluator "settings" | /evaluator | Evaluator portal |  |  |  |
| 11 | palette | /evaluator "courses" | /evaluator | Evaluator portal |  |  |  |
| 12 | palette | /evaluator "tests" | /evaluator/tests | Evaluator portal |  |  |  |
| 13 | logo | sidebar logo from /evaluator/tests | /evaluator | Evaluator portal |  |  |  |
| 14 | account-menu | /evaluator -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  | cross-portal: expected evaluator got student (evaluator-002.png) |
| 15 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 16 | portal-home | /app | /app | Student portal |  |  |  |
| 17 | nav | Dashboard [/app] | /app | Student portal |  |  |  |
| 18 | nav | My learning [/app/learning] | /app/learning | Student portal |  |  |  |
| 19 | nav | My classes [/app/classes] | /app/classes | Student portal |  |  |  |
| 20 | nav | Explore courses [/app/courses] | /app/courses | Student portal |  |  |  |
| 21 | nav | My registrations [/app/registrations] | /app/registrations | Student portal |  |  |  |
| 22 | nav | My paths [/app/path/my] | /app/path/my | Student portal |  |  |  |
| 23 | nav | Assignments [/app/assignments] | /app/assignments | Student portal |  |  |  |
| 24 | nav | Live activities [/app/engage] | /app/engage | Student portal |  |  |  |
| 25 | nav | Certificates [/app/certificates] | /app/certificates | Student portal |  |  |  |
| 26 | nav | Practice [/app/practice] | /app/practice | Student portal |  |  |  |
| 27 | nav | Tests [/app/tests] | /app/tests | Student portal |  |  |  |
| 28 | nav | Coding [/app/coding] | /app/coding | Student portal |  |  |  |
| 29 | nav | Progress [/app/progress] | /app/progress | Student portal |  |  |  |
| 30 | nav | Free diagnostic [/app/diagnostic] | /app/diagnostic | Student portal |  |  |  |
| 31 | nav | Interview prep [/app/interview-prep] | /app/interview-prep | Student portal |  |  |  |
| 32 | nav | Mock interviews [/app/mentoring] | /app/mentoring | Student portal |  |  |  |
| 33 | nav | Résumé builder [/app/resume] | /app/resume | Student portal |  |  |  |
| 34 | nav | Company paths [/app/companies] | /app/companies | Student portal |  |  |  |
| 35 | nav | Notifications [/app/notifications] | /app/notifications | Student portal |  |  |  |
| 36 | nav | Billing [/app/billing] | /app/billing | Student portal |  |  |  |
| 37 | nav | My access [/app/access] | /app/access | Student portal |  |  |  |
| 38 | nav | Support [/app/support] | /app/support | Student portal |  |  |  |
| 39 | nav | Profile & settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 40 | cta | /app -> /app/learning | /app/learning | Student portal |  |  |  |
| 41 | cta | /app -> /app/assignments | /app/assignments | Student portal |  |  |  |
| 42 | cta | /app -> /app/tests | /app/tests | Student portal |  |  |  |
| 43 | cta | /app -> /app/certificates | /app/certificates | Student portal |  |  |  |
| 44 | cta | /app -> /app/courses | /app/courses | Student portal |  |  |  |
| 45 | cta | /app -> /app/courses/nextgen-career-accelerator-2026/register | /app/courses/nextgen-career-accelerator-2026/register | Student portal |  |  |  |
| 46 | cta | /app -> /app/practice | /app/practice | Student portal |  |  |  |
| 47 | cta | /app -> /app/diagnostic | /app/diagnostic | Student portal |  |  |  |
| 48 | cta | /app -> /app/mentoring | /app/mentoring | Student portal |  |  |  |
| 49 | cta | /app -> /app/resume | /app/resume | Student portal |  |  |  |
| 50 | cta | /app -> /app/notifications | /app/notifications | Student portal |  |  |  |
| 51 | cta | /app -> /app/support | /app/support | Student portal |  |  |  |
| 52 | cta | /app -> /app/billing | /app/billing | Student portal |  |  |  |
| 53 | cta | /app -> /app/access | /app/access | Student portal |  |  |  |
| 54 | palette | /app "certificates" | /app/certificates | Student portal |  |  |  |
| 55 | palette | /app "settings" | /app/settings/profile | Student portal |  |  |  |
| 56 | palette | /app "courses" | /app/courses | Student portal |  |  |  |
| 57 | palette | /app "tests" | /app/practice | Student portal |  |  |  |
| 58 | logo | sidebar logo from /app/learning | /app/learning | (none) |  |  | blank page (evaluator-003.png) |
| 59 | account-menu | /app -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 60 | account-menu | /app -> Account status [/app/account-status] | /app/account-status | Student portal |  |  |  |
| 61 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 62 | owner-bug | /evaluator account menu -> Settings | /app/settings/profile | Student portal |  |  | cross-portal: expected evaluator got student (evaluator-004.png) |
| 63 | owner-bug | then student sidebar -> Certificates | /app/certificates | Student portal |  |  | cross-portal: expected evaluator got student (evaluator-005.png) |
| 64 | forbidden | /admin | /evaluator | Evaluator portal |  |  |  |
| 65 | forbidden | /admin/users | /evaluator | Evaluator portal |  |  |  |
| 66 | forbidden | /admin/roles | /evaluator | Evaluator portal |  |  |  |
| 67 | forbidden | /admin/certificates | /evaluator | Evaluator portal |  |  |  |
| 68 | forbidden | /finance/orders | /evaluator | Evaluator portal |  |  |  |
| 69 | forbidden | /desk | /evaluator | Evaluator portal |  |  |  |
| 70 | forbidden | /security/cases | /evaluator | Evaluator portal |  |  |  |
| 71 | forbidden | /mentor/students | /evaluator | Evaluator portal |  |  |  |
| 72 | forbidden | /studio | /evaluator | Evaluator portal |  |  |  |
| 73 | forbidden | /studio/questions | /evaluator | Evaluator portal |  |  |  |
| 74 | forbidden | /studio/courses | /evaluator | Evaluator portal |  |  |  |
| 75 | forbidden | /trainer | /evaluator | Evaluator portal |  |  |  |
| 76 | forbidden | /trainer/grading | /evaluator | Evaluator portal |  |  |  |
| 77 | forbidden | /trainer/tests | /evaluator | Evaluator portal |  |  |  |

### content_manager (audit-content@dev.techdrona.local, expected home /studio)

- login: {"firstUrl":"/studio"}
- me/grants: {"portals":["/studio"],"roles":["content_manager@platform"]}
- switcher: {"root":"/studio","entries":"not shown"}
- account-menu: {"root":"/studio","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- switcher: {"root":"/app","entries":"not shown"}
- account-menu: {"root":"/app","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"/app/account-status","label":"Account status"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- api-probes: {"probes":[{"ep":"admin/users","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"rbac/grants","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"admin/feature-flags","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"finance/refunds","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"security/incidents","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"security/restrictions","ok":["admin"],"status":403,"code":"permission_denied"},{"ep":"admin/certificates","ok":["admin"],"status":200,"code":null},{"ep":"studio/questions","ok":["admin","studio"],"status":200,"code":null},{"ep":"studio/courses","ok":["admin","studio"],"status":200,"code":null},{"ep":"batches","ok":["admin","trainer","evaluator"],"status":403,"code":"permission_denied"}]}
- sign-out (account menu): landed /login; revisiting /studio -> /login?next=%2Fstudio

| # | kind | item | final URL | portal shown (sidebar badge) | API >=400 | console | flags |
|---|---|---|---|---|---|---|---|
| 1 | login | (after sign-in) | /studio | Content studio portal |  |  |  |
| 2 | goto | / | /studio | Content studio portal |  |  |  |
| 3 | goto | /continue | /studio | Content studio portal |  |  |  |
| 4 | goto | /modules | /studio | Content studio portal |  |  |  |
| 5 | portal-home | /studio | /studio | Content studio portal |  |  |  |
| 6 | nav | Dashboard [/studio] | /studio | Content studio portal |  |  |  |
| 7 | nav | Review queue [/studio/review] | /studio/review | Content studio portal |  |  |  |
| 8 | nav | Reported errors [/studio/reports/errors] | /studio/reports/errors | Content studio portal |  |  |  |
| 9 | nav | Courses [/studio/courses] | /studio/courses | Content studio portal |  |  |  |
| 10 | nav | Media [/studio/media] | /studio/media | Content studio portal |  |  |  |
| 11 | nav | Taxonomy [/studio/taxonomy] | /studio/taxonomy | Content studio portal |  |  |  |
| 12 | nav | Companies [/studio/companies] | /studio/companies | Content studio portal |  |  |  |
| 13 | nav | All questions [/studio/questions] | /studio/questions | Content studio portal |  |  |  |
| 14 | nav | Question banks [/studio/question-banks] | /studio/question-banks | Content studio portal |  |  |  |
| 15 | nav | Coding problems [/studio/coding] | /studio/coding | Content studio portal |  |  |  |
| 16 | nav | Template mocks [/studio/tests] | /studio/tests | Content studio portal |  |  |  |
| 17 | cta | /studio -> /studio/review | /studio/review | Content studio portal |  |  |  |
| 18 | cta | /studio -> /studio/questions | /studio/questions | Content studio portal |  |  |  |
| 19 | cta | /studio -> /studio/reports/errors | /studio/reports/errors | Content studio portal |  |  |  |
| 20 | cta | /studio -> /studio/courses | /studio/courses | Content studio portal |  |  |  |
| 21 | cta | /studio -> /studio/questions/new | /studio/questions/new | Content studio portal |  |  |  |
| 22 | cta | /studio -> /studio/coding | /studio/coding | Content studio portal |  |  |  |
| 23 | cta | /studio -> /studio/tests | /studio/tests | Content studio portal |  |  |  |
| 24 | cta | /studio -> /studio/media | /studio/media | Content studio portal |  |  |  |
| 25 | cta | /studio -> /studio/taxonomy | /studio/taxonomy | Content studio portal |  |  |  |
| 26 | palette | /studio "certificates" | /studio | Content studio portal |  |  |  |
| 27 | palette | /studio "settings" | /studio | Content studio portal |  |  |  |
| 28 | palette | /studio "courses" | /studio/courses | Content studio portal |  |  |  |
| 29 | palette | /studio "tests" | /studio/questions | Content studio portal |  |  |  |
| 30 | logo | sidebar logo from /studio/review | /studio | Content studio portal |  |  |  |
| 31 | account-menu | /studio -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  | cross-portal: expected studio got student (content_manager-001.png) |
| 32 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 33 | portal-home | /app | /app | Student portal |  |  |  |
| 34 | nav | Dashboard [/app] | /app | Student portal |  |  |  |
| 35 | nav | My learning [/app/learning] | /app/learning | Student portal |  |  |  |
| 36 | nav | My classes [/app/classes] | /app/classes | Student portal |  |  |  |
| 37 | nav | Explore courses [/app/courses] | /app/courses | Student portal |  |  |  |
| 38 | nav | My registrations [/app/registrations] | /app/registrations | Student portal |  |  |  |
| 39 | nav | My paths [/app/path/my] | /app/path/my | Student portal |  |  |  |
| 40 | nav | Assignments [/app/assignments] | /app/assignments | Student portal |  |  |  |
| 41 | nav | Live activities [/app/engage] | /app/engage | Student portal |  |  |  |
| 42 | nav | Certificates [/app/certificates] | /app/certificates | Student portal |  |  |  |
| 43 | nav | Practice [/app/practice] | /app/practice | Student portal |  |  |  |
| 44 | nav | Tests [/app/tests] | /app/tests | Student portal |  |  |  |
| 45 | nav | Coding [/app/coding] | /app/coding | Student portal |  |  |  |
| 46 | nav | Progress [/app/progress] | /app/progress | Student portal |  |  |  |
| 47 | nav | Free diagnostic [/app/diagnostic] | /app/diagnostic | Student portal |  |  |  |
| 48 | nav | Interview prep [/app/interview-prep] | /app/interview-prep | Student portal |  |  |  |
| 49 | nav | Mock interviews [/app/mentoring] | /app/mentoring | Student portal |  |  |  |
| 50 | nav | Résumé builder [/app/resume] | /app/resume | Student portal |  |  |  |
| 51 | nav | Company paths [/app/companies] | /app/companies | Student portal |  |  |  |
| 52 | nav | Notifications [/app/notifications] | /app/notifications | Student portal |  |  |  |
| 53 | nav | Billing [/app/billing] | /app/billing | Student portal |  |  |  |
| 54 | nav | My access [/app/access] | /app/access | Student portal |  |  |  |
| 55 | nav | Support [/app/support] | /app/support | Student portal |  |  |  |
| 56 | nav | Profile & settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 57 | cta | /app -> /app/learning | /app/learning | Student portal |  |  |  |
| 58 | cta | /app -> /app/assignments | /app/assignments | Student portal |  |  |  |
| 59 | cta | /app -> /app/tests | /app/tests | Student portal |  |  |  |
| 60 | cta | /app -> /app/certificates | /app/certificates | Student portal |  |  |  |
| 61 | cta | /app -> /app/courses | /app/courses | Student portal |  |  |  |
| 62 | cta | /app -> /app/diagnostic | /app/diagnostic | Student portal |  |  |  |
| 63 | cta | /app -> /app/mentoring | /app/mentoring | Student portal |  |  |  |
| 64 | cta | /app -> /app/resume | /app/resume | Student portal |  |  |  |
| 65 | cta | /app -> /app/notifications | /app/notifications | Student portal |  |  |  |
| 66 | cta | /app -> /app/support | /app/support | Student portal |  |  |  |
| 67 | cta | /app -> /app/billing | /app/billing | Student portal |  |  |  |
| 68 | palette | /app "certificates" | /app/certificates | Student portal |  |  |  |
| 69 | palette | /app "settings" | /app/settings/profile | Student portal |  |  |  |
| 70 | palette | /app "courses" | /app/courses | Student portal |  |  |  |
| 71 | palette | /app "tests" | /app/practice | Student portal |  |  |  |
| 72 | logo | sidebar logo from /app/learning | /app | Student portal |  |  |  |
| 73 | account-menu | /app -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 74 | account-menu | /app -> Account status [/app/account-status] | /app/account-status | Student portal |  |  |  |
| 75 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 76 | owner-bug | /studio account menu -> Settings | /app/settings/profile | Student portal |  |  | cross-portal: expected studio got student (content_manager-002.png) |
| 77 | owner-bug | then student sidebar -> Certificates | /app/certificates | Student portal |  |  | cross-portal: expected studio got student (content_manager-003.png) |
| 78 | forbidden | /admin | /studio | Content studio portal |  |  |  |
| 79 | forbidden | /admin/users | /studio | Content studio portal |  |  |  |
| 80 | forbidden | /admin/roles | /studio | Content studio portal |  |  |  |
| 81 | forbidden | /admin/certificates | /studio | Content studio portal |  |  |  |
| 82 | forbidden | /finance/orders | /studio | Content studio portal |  |  |  |
| 83 | forbidden | /desk | /studio | Content studio portal |  |  |  |
| 84 | forbidden | /security/cases | /studio | Content studio portal |  |  |  |
| 85 | forbidden | /mentor/students | /studio | Content studio portal |  |  |  |
| 86 | forbidden | /trainer | /studio | Content studio portal |  |  |  |
| 87 | forbidden | /trainer/grading | /studio | Content studio portal |  |  |  |
| 88 | forbidden | /trainer/tests | /studio | Content studio portal |  |  |  |
| 89 | forbidden | /evaluator | /studio | Content studio portal |  |  |  |
| 90 | forbidden | /evaluator/tests | /studio | Content studio portal |  |  |  |
| 91 | forbidden | /evaluator/integrity | /studio | Content studio portal |  |  |  |

### admin (admin@dev.techdrona.local, expected home /admin)

- login: {"firstUrl":"/modules"}
- me/grants: {"portals":["/admin"],"roles":["super_admin@platform"]}
- switcher: {"root":"/admin","entries":"not shown"}
- account-menu: {"root":"/admin","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- switcher: {"root":"/studio","entries":"not shown"}
- account-menu: {"root":"/studio","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- switcher: {"root":"/trainer","entries":"not shown"}
- account-menu: {"root":"/trainer","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- switcher: {"root":"/evaluator","entries":"not shown"}
- account-menu: {"root":"/evaluator","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- switcher: {"root":"/app","entries":"not shown"}
- account-menu: {"root":"/app","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"/app/account-status","label":"Account status"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- api-probes: {"probes":[{"ep":"admin/users","ok":["admin"],"status":200,"code":null},{"ep":"rbac/grants","ok":["admin"],"status":200,"code":null},{"ep":"admin/feature-flags","ok":["admin"],"status":200,"code":null},{"ep":"finance/refunds","ok":["admin"],"status":200,"code":null},{"ep":"security/incidents","ok":["admin"],"status":200,"code":null},{"ep":"security/restrictions","ok":["admin"],"status":200,"code":null},{"ep":"admin/certificates","ok":["admin"],"status":200,"code":null},{"ep":"studio/questions","ok":["admin","studio"],"status":403,"code":"permission_denied"},{"ep":"studio/courses","ok":["admin","studio"],"status":200,"code":null},{"ep":"batches","ok":["admin","trainer","evaluator"],"status":200,"code":null}]}
- sign-out (account menu): landed /login; revisiting /admin -> /login?next=%2Fadmin

| # | kind | item | final URL | portal shown (sidebar badge) | API >=400 | console | flags |
|---|---|---|---|---|---|---|---|
| 1 | login | (after sign-in) | /modules | (none) |  |  |  |
| 2 | goto | / | /modules | (none) |  |  |  |
| 3 | goto | /continue | /modules | (none) |  |  |  |
| 4 | goto | /modules | /modules | (none) |  |  |  |
| 5 | portal-home | /admin | /admin | Admin portal |  |  |  |
| 6 | nav | Dashboard [/admin] | /admin | Admin portal |  |  |  |
| 7 | nav | Approvals [/admin/approvals] | /admin/approvals | Admin portal |  |  |  |
| 8 | nav | Users [/admin/users] | /admin/users | Admin portal |  |  |  |
| 9 | nav | Role grants [/admin/roles] | /admin/roles | Admin portal |  |  |  |
| 10 | nav | Privacy requests [/admin/privacy-requests] | /admin/privacy-requests | Admin portal |  |  |  |
| 11 | nav | Colleges Data [/college-portal/index.html] | /college-portal/index.html | (none) |  |  |  |
| 12 | nav | Website Admin Panel (https://techdrona-website.web.app/admin) | - | - | - | - | external link |
| 13 | nav | Courses [/admin/courses] | /admin/courses | Admin portal |  |  |  |
| 14 | nav | Question review [/admin/question-review] | /admin/question-review | Admin portal |  |  |  |
| 15 | nav | Batches [/admin/batches] | /admin/batches | Admin portal |  |  |  |
| 16 | nav | Certificates & documents [/admin/certificates] | /admin/certificates | Admin portal |  |  |  |
| 17 | nav | Mentor sessions [/mentor] | /mentor | Admin · Mentoring portal |  |  |  |
| 18 | nav | Mentees [/mentor/students] | /mentor/students | Admin · Mentoring portal |  |  |  |
| 19 | nav | Mentor availability [/mentor/slots] | /mentor/slots | Admin · Mentoring portal |  |  |  |
| 20 | nav | Résumé reviews [/mentor/resume-reviews] | /mentor/resume-reviews | Admin · Mentoring portal |  |  |  |
| 21 | nav | Revenue [/finance] | /finance | Admin · Finance portal |  |  |  |
| 22 | nav | Admissions [/finance/admissions] | /finance/admissions | Admin · Finance portal |  |  |  |
| 23 | nav | Verify payments [/finance/admissions/verify] | /finance/admissions/verify | Admin · Finance portal |  |  |  |
| 24 | nav | Registrations [/finance/admissions/registrations] | /finance/admissions/registrations | Admin · Finance portal |  |  |  |
| 25 | nav | Fee plans [/finance/admissions/plans] | /finance/admissions/plans | Admin · Finance portal |  |  |  |
| 26 | nav | Orders [/finance/orders] | /finance/orders | Admin · Finance portal |  |  |  |
| 27 | nav | Refunds [/finance/refunds] | /finance/refunds | Admin · Finance portal |  |  |  |
| 28 | nav | Subscriptions [/finance/subscriptions] | /finance/subscriptions | Admin · Finance portal |  |  |  |
| 29 | nav | Invoices [/finance/invoices] | /finance/invoices | Admin · Finance portal |  |  |  |
| 30 | nav | Products & prices [/finance/products] | /finance/products | Admin · Finance portal |  |  |  |
| 31 | nav | Coupons [/finance/coupons] | /finance/coupons | Admin · Finance portal |  |  |  |
| 32 | nav | Reconciliation [/finance/reconciliation] | /finance/reconciliation | Admin · Finance portal |  |  |  |
| 33 | nav | Ticket queue [/desk] | /desk | Admin · Support portal |  |  |  |
| 34 | nav | Unblock requests [/desk/unblock-requests] | /desk/unblock-requests | Admin · Support portal |  |  |  |
| 35 | nav | Corporate enquiries [/desk/enquiries] | /desk/enquiries | Admin · Support portal |  |  |  |
| 36 | nav | Security overview [/security] | /security | Admin · Account security portal |  |  |  |
| 37 | nav | Cases [/security/cases] | /security/cases | Admin · Account security portal |  |  |  |
| 38 | nav | Incidents [/security/incidents] | /security/incidents | Admin · Account security portal |  |  |  |
| 39 | nav | Restrictions [/security/restrictions] | /security/restrictions | Admin · Account security portal |  |  |  |
| 40 | nav | Unblock reviews [/security/unblock-requests] | /security/unblock-requests | Admin · Account security portal |  |  |  |
| 41 | nav | Risk rules [/security/rules] | /security/rules | Admin · Account security portal |  |  |  |
| 42 | nav | Reports [/security/reports] | /security/reports | Admin · Account security portal |  |  |  |
| 43 | nav | Audit log [/admin/audit] | /admin/audit | Admin portal |  |  |  |
| 44 | nav | Policies [/admin/policies] | /admin/policies | Admin portal |  |  |  |
| 45 | nav | AI & apps [/admin/ai] | /admin/ai | Admin portal |  |  | error text (admin-001.png) |
| 46 | nav | Feature flags [/admin/feature-flags] | /admin/feature-flags | Admin portal |  |  |  |
| 47 | nav | Break-glass [/admin/break-glass] | /admin/break-glass | Admin portal |  |  |  |
| 48 | cta | /admin -> /admin/audit | /admin/audit | Admin portal |  |  |  |
| 49 | cta | /admin -> /college-portal/index.html | /college-portal/index.html | (none) |  |  |  |
| 50 | cta | /admin -> /admin/users?add=1 | /admin/users?add=1 | Admin portal |  |  |  |
| 51 | cta | /admin -> /admin/users?status=active | /admin/users?status=active | Admin portal |  |  |  |
| 52 | cta | /admin -> /admin/users | /admin/users | Admin portal |  |  |  |
| 53 | cta | /admin -> /finance/orders | /finance/orders | Admin · Finance portal |  |  |  |
| 54 | cta | /admin -> /studio/courses | /studio/courses | Content studio portal |  |  |  |
| 55 | cta | /admin -> /admin/batches | /admin/batches | Admin portal |  |  |  |
| 56 | cta | /admin -> /admin/approvals | /admin/approvals | Admin portal |  |  |  |
| 57 | cta | /admin -> /admin/courses | /admin/courses | Admin portal |  |  |  |
| 58 | cta | /admin -> /admin/certificates | /admin/certificates | Admin portal |  |  |  |
| 59 | cta | /admin -> /finance | /finance | Admin · Finance portal |  |  |  |
| 60 | cta | /admin -> /admin/users?status=pending_verification | /admin/users?status=pending_verification | Admin portal |  |  |  |
| 61 | cta | /admin -> /admin/users?status=deactivated | /admin/users?status=deactivated | Admin portal |  |  |  |
| 62 | cta | /admin -> /desk | /desk | Admin · Support portal |  |  |  |
| 63 | cta | /admin -> /admin/privacy-requests | /admin/privacy-requests | Admin portal |  |  |  |
| 64 | cta | /admin -> /security | /security | Admin · Account security portal |  |  |  |
| 65 | cta | /admin -> /security/cases | /security/cases | Admin · Account security portal |  |  |  |
| 66 | palette | /admin "certificates" | /admin/certificates | Admin portal |  |  |  |
| 67 | palette | /admin "settings" | /admin/audit | Admin portal |  |  |  |
| 68 | palette | /admin "courses" | /admin/courses | Admin portal |  |  |  |
| 69 | palette | /admin "tests" | /admin | Admin portal |  |  |  |
| 70 | logo | sidebar logo from /admin/approvals | /admin | Admin portal |  |  |  |
| 71 | account-menu | /admin -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  | cross-portal: expected admin got student (admin-002.png) |
| 72 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 73 | portal-home | /studio | /studio | Content studio portal | 403 GET studio/questions?status=draft&limit=200, 403 GET studio/question-reports?status=open&limit=1, 403 GET studio/questions?status=draft&limit=200, 403 GET studio/question-reports?status=open&limit=1 |  | API 403/404 on allowed page (admin-003.png) |
| 74 | nav | Dashboard [/studio] | /studio | Content studio portal |  |  |  |
| 75 | nav | Review queue [/studio/review] | /studio/review | Content studio portal |  |  |  |
| 76 | nav | Reported errors [/studio/reports/errors] | /studio/reports/errors | Content studio portal | 403 GET studio/question-reports?status=open&limit=25, 403 GET studio/question-reports?status=open&limit=25 |  | API 403/404 on allowed page; error text (admin-004.png) |
| 77 | nav | Courses [/studio/courses] | /studio/courses | Content studio portal |  |  |  |
| 78 | nav | Media [/studio/media] | /studio/media | Content studio portal |  |  |  |
| 79 | nav | Taxonomy [/studio/taxonomy] | /studio/taxonomy | Content studio portal | 403 GET studio/topics, 403 GET studio/topics |  | API 403/404 on allowed page; error text (admin-005.png) |
| 80 | nav | Companies [/studio/companies] | /studio/companies | Content studio portal | 403 GET studio/companies, 403 GET studio/companies |  | API 403/404 on allowed page; error text (admin-006.png) |
| 81 | nav | All questions [/studio/questions] | /studio/questions | Content studio portal | 403 GET studio/questions?offset=0&limit=25, 403 GET studio/questions?offset=0&limit=25 |  | API 403/404 on allowed page; error text (admin-007.png) |
| 82 | nav | Question banks [/studio/question-banks] | /studio/question-banks | Content studio portal | 403 GET studio/question-banks?sort=updated&limit=100, 403 GET studio/question-banks?sort=updated&limit=100 |  | API 403/404 on allowed page; error text (admin-008.png) |
| 83 | nav | Coding problems [/studio/coding] | /studio/coding | Content studio portal | 403 GET studio/coding/problems?limit=100, 403 GET studio/coding/problems?limit=100 |  | API 403/404 on allowed page; error text (admin-009.png) |
| 84 | nav | Template mocks [/studio/tests] | /studio/tests | Content studio portal |  |  |  |
| 85 | cta | /studio -> /studio/review | /studio/review | Content studio portal |  |  |  |
| 86 | cta | /studio -> /studio/questions | /studio/questions | Content studio portal | 403 GET studio/questions?offset=0&limit=25, 403 GET studio/questions?offset=0&limit=25 |  | API 403/404 on allowed page; error text (admin-010.png) |
| 87 | cta | /studio -> /studio/reports/errors | /studio/reports/errors | Content studio portal | 403 GET studio/question-reports?status=open&limit=25, 403 GET studio/question-reports?status=open&limit=25 |  | API 403/404 on allowed page; error text (admin-011.png) |
| 88 | cta | /studio -> /studio/courses | /studio/courses | Content studio portal |  |  |  |
| 89 | cta | /studio -> /studio/questions/new | /studio/questions/new | Content studio portal |  |  |  |
| 90 | cta | /studio -> /studio/coding | /studio/coding | Content studio portal | 403 GET studio/coding/problems?limit=100, 403 GET studio/coding/problems?limit=100 |  | API 403/404 on allowed page; error text (admin-012.png) |
| 91 | cta | /studio -> /studio/tests | /studio/tests | Content studio portal |  |  |  |
| 92 | cta | /studio -> /studio/media | /studio/media | Content studio portal |  |  |  |
| 93 | cta | /studio -> /studio/taxonomy | /studio/taxonomy | Content studio portal | 403 GET studio/topics, 403 GET studio/topics |  | API 403/404 on allowed page; error text (admin-013.png) |
| 94 | palette | /studio "certificates" | /studio | Content studio portal |  |  |  |
| 95 | palette | /studio "settings" | /studio | Content studio portal |  |  |  |
| 96 | palette | /studio "courses" | /studio/courses | Content studio portal |  |  |  |
| 97 | palette | /studio "tests" | /studio/questions | Content studio portal | 403 GET studio/questions?offset=0&limit=25, 403 GET studio/questions?offset=0&limit=25 |  | API 403/404 on allowed page; error text (admin-014.png) |
| 98 | logo | sidebar logo from /studio/review | /studio | Content studio portal | 403 GET studio/questions?status=draft&limit=200, 403 GET studio/question-reports?status=open&limit=1, 403 GET studio/questions?status=draft&limit=200, 403 GET studio/question-reports?status=open&limit=1 |  | API 403/404 on allowed page (admin-015.png) |
| 99 | account-menu | /studio -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  | cross-portal: expected studio got student (admin-016.png) |
| 100 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 101 | portal-home | /trainer | /trainer | Trainer portal |  |  |  |
| 102 | nav | Dashboard [/trainer] | /trainer | Trainer portal |  |  |  |
| 103 | nav | Courses [/trainer/courses] | /trainer/courses | Trainer portal |  |  |  |
| 104 | nav | Learning paths [/trainer/paths] | /trainer/paths | Trainer portal |  |  |  |
| 105 | nav | Articles [/trainer/paths/articles] | /trainer/paths/articles | Trainer portal |  |  |  |
| 106 | nav | Engage [/trainer/engage] | /trainer/engage | Trainer portal |  |  |  |
| 107 | nav | Grading [/trainer/grading] | /trainer/grading | Trainer portal |  |  |  |
| 108 | nav | Assignments [/trainer/assignments] | /trainer/assignments | Trainer portal |  |  |  |
| 109 | nav | Tests [/trainer/tests] | /trainer/tests | Trainer portal |  |  |  |
| 110 | nav | Integrity flags [/trainer/integrity] | /trainer/integrity | Trainer portal |  |  |  |
| 111 | palette | /trainer "certificates" | /trainer | Trainer portal |  |  |  |
| 112 | palette | /trainer "settings" | /trainer | Trainer portal |  |  |  |
| 113 | palette | /trainer "courses" | /trainer/courses | Trainer portal |  |  |  |
| 114 | palette | /trainer "tests" | /trainer/tests | Trainer portal |  |  |  |
| 115 | logo | sidebar logo from /trainer/courses | /trainer | Trainer portal |  |  |  |
| 116 | breadcrumb | /trainer/paths/articles -> /trainer/paths | /trainer/paths | Trainer portal |  |  |  |
| 117 | account-menu | /trainer -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  | cross-portal: expected trainer got student (admin-017.png) |
| 118 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 119 | portal-home | /evaluator | /evaluator | Evaluator portal |  |  |  |
| 120 | nav | Grading [/evaluator] | /evaluator | Evaluator portal |  |  |  |
| 121 | nav | Tests [/evaluator/tests] | /evaluator/tests | Evaluator portal |  |  |  |
| 122 | nav | Integrity flags [/evaluator/integrity] | /evaluator/integrity | Evaluator portal |  |  |  |
| 123 | palette | /evaluator "certificates" | /evaluator | Evaluator portal |  |  |  |
| 124 | palette | /evaluator "settings" | /evaluator | Evaluator portal |  |  |  |
| 125 | palette | /evaluator "courses" | /evaluator | Evaluator portal |  |  |  |
| 126 | palette | /evaluator "tests" | /evaluator/tests | Evaluator portal |  |  |  |
| 127 | logo | sidebar logo from /evaluator/tests | /evaluator | Evaluator portal |  |  |  |
| 128 | account-menu | /evaluator -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  | cross-portal: expected evaluator got student (admin-018.png) |
| 129 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 130 | portal-home | /app | /app | Student portal |  |  |  |
| 131 | nav | Dashboard [/app] | /app | Student portal |  |  |  |
| 132 | nav | My learning [/app/learning] | /app/learning | Student portal |  |  |  |
| 133 | nav | My classes [/app/classes] | /app/classes | Student portal |  |  |  |
| 134 | nav | Explore courses [/app/courses] | /app/courses | Student portal |  |  |  |
| 135 | nav | My registrations [/app/registrations] | /app/registrations | Student portal |  |  |  |
| 136 | nav | My paths [/app/path/my] | /app/path/my | Student portal |  |  |  |
| 137 | nav | Assignments [/app/assignments] | /app/assignments | Student portal |  |  |  |
| 138 | nav | Live activities [/app/engage] | /app/engage | Student portal |  |  |  |
| 139 | nav | Certificates [/app/certificates] | /app/certificates | Student portal |  |  |  |
| 140 | nav | Practice [/app/practice] | /app/practice | Student portal |  |  |  |
| 141 | nav | Tests [/app/tests] | /app/tests | Student portal |  |  |  |
| 142 | nav | Coding [/app/coding] | /app/coding | Student portal |  |  |  |
| 143 | nav | Progress [/app/progress] | /app/progress | Student portal |  |  |  |
| 144 | nav | Free diagnostic [/app/diagnostic] | /app/diagnostic | Student portal |  |  |  |
| 145 | nav | Interview prep [/app/interview-prep] | /app/interview-prep | Student portal |  |  |  |
| 146 | nav | Mock interviews [/app/mentoring] | /app/mentoring | Student portal |  |  |  |
| 147 | nav | Résumé builder [/app/resume] | /app/resume | Student portal |  |  |  |
| 148 | nav | Company paths [/app/companies] | /app/companies | Student portal |  |  |  |
| 149 | nav | Notifications [/app/notifications] | /app/notifications | Student portal |  |  |  |
| 150 | nav | Billing [/app/billing] | /app/billing | Student portal |  |  |  |
| 151 | nav | My access [/app/access] | /app/access | Student portal |  |  |  |
| 152 | nav | Support [/app/support] | /app/support | Student portal |  |  |  |
| 153 | nav | Profile & settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 154 | cta | /app -> /app/learning | /app/learning | Student portal |  |  |  |
| 155 | cta | /app -> /app/assignments | /app/assignments | Student portal |  |  |  |
| 156 | cta | /app -> /app/tests | /app/tests | Student portal |  |  |  |
| 157 | cta | /app -> /app/certificates | /app/certificates | Student portal |  |  |  |
| 158 | cta | /app -> /app/practice | /app/practice | Student portal |  |  |  |
| 159 | cta | /app -> /app/diagnostic | /app/diagnostic | Student portal |  |  |  |
| 160 | cta | /app -> /app/mentoring | /app/mentoring | Student portal |  |  |  |
| 161 | cta | /app -> /app/resume | /app/resume | Student portal |  |  |  |
| 162 | cta | /app -> /app/notifications | /app/notifications | Student portal |  |  |  |
| 163 | cta | /app -> /app/support | /app/support | Student portal |  |  |  |
| 164 | cta | /app -> /app/billing | /app/billing | Student portal |  |  |  |
| 165 | cta | /app -> /app/access | /app/access | Student portal |  |  |  |
| 166 | palette | /app "certificates" | /app/certificates | Student portal |  |  |  |
| 167 | palette | /app "settings" | /app/settings/profile | Student portal |  |  |  |
| 168 | palette | /app "courses" | /app/courses | Student portal |  |  |  |
| 169 | palette | /app "tests" | /app/practice | Student portal |  |  |  |
| 170 | logo | sidebar logo from /app/learning | /app | Student portal |  |  |  |
| 171 | account-menu | /app -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 172 | account-menu | /app -> Account status [/app/account-status] | /app/account-status | Student portal |  |  |  |
| 173 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 174 | owner-bug | /admin account menu -> Settings | /app/settings/profile | Student portal |  |  | cross-portal: expected admin got student (admin-019.png) |
| 175 | owner-bug | then student sidebar -> Certificates | /app/certificates | Student portal |  |  | cross-portal: expected admin got student (admin-020.png) |

### admin_trainer (audit-admin2@dev.techdrona.local, expected home /admin)

- login: {"firstUrl":"/modules"}
- selfGrant: {"status":201,"body":"{\"grant_id\":\"01a1d5e3-4aac-7543-a9d1-bf0d3fc73053\",\"session_effect\":\"grantee_sessions_rotated\"}"}
- me/grants: {"portals":["/admin","/trainer"],"roles":["trainer@batch","super_admin@platform"]}
- switcher: {"root":"/admin","entries":[{"href":"/admin","label":"Admin"},{"href":"/trainer","label":"Trainer"}]}
- account-menu: {"root":"/admin","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- switcher: {"root":"/studio","entries":[{"href":"/admin","label":"Admin"},{"href":"/trainer","label":"Trainer"}]}
- account-menu: {"root":"/studio","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- switcher: {"root":"/trainer","entries":[{"href":"/admin","label":"Admin"},{"href":"/trainer","label":"Trainer"}]}
- account-menu: {"root":"/trainer","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- switcher: {"root":"/evaluator","entries":[{"href":"/admin","label":"Admin"},{"href":"/trainer","label":"Trainer"}]}
- account-menu: {"root":"/evaluator","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- switcher: {"root":"/app","entries":[{"href":"/admin","label":"Admin"},{"href":"/trainer","label":"Trainer"}]}
- account-menu: {"root":"/app","links":[{"href":"/app/settings/profile","label":"Settings"},{"href":"/app/account-status","label":"Account status"},{"href":"https://techdrona-website.web.app","label":"Tech Drona website"}]}
- api-probes: {"probes":[{"ep":"admin/users","ok":["admin"],"status":200,"code":null},{"ep":"rbac/grants","ok":["admin"],"status":200,"code":null},{"ep":"admin/feature-flags","ok":["admin"],"status":200,"code":null},{"ep":"finance/refunds","ok":["admin"],"status":200,"code":null},{"ep":"security/incidents","ok":["admin"],"status":200,"code":null},{"ep":"security/restrictions","ok":["admin"],"status":200,"code":null},{"ep":"admin/certificates","ok":["admin"],"status":200,"code":null},{"ep":"studio/questions","ok":["admin","studio"],"status":200,"code":null},{"ep":"studio/courses","ok":["admin","studio"],"status":200,"code":null},{"ep":"batches","ok":["admin","trainer","evaluator"],"status":200,"code":null}]}
- sign-out (account menu): landed /login; revisiting /admin -> /login?next=%2Fadmin

| # | kind | item | final URL | portal shown (sidebar badge) | API >=400 | console | flags |
|---|---|---|---|---|---|---|---|
| 1 | login | (after sign-in) | /modules | (none) |  |  |  |
| 2 | goto | / | /modules | (none) |  |  |  |
| 3 | goto | /continue | /app | Student portal |  |  |  |
| 4 | goto | /modules | /modules | (none) |  |  |  |
| 5 | portal-home | /admin | /admin | Admin portal |  |  |  |
| 6 | nav | Dashboard [/admin] | /admin | Admin portal |  |  |  |
| 7 | nav | Approvals [/admin/approvals] | /admin/approvals | Admin portal |  |  |  |
| 8 | nav | Users [/admin/users] | /admin/users | Admin portal |  |  |  |
| 9 | nav | Role grants [/admin/roles] | /admin/roles | Admin portal |  |  |  |
| 10 | nav | Privacy requests [/admin/privacy-requests] | /admin/privacy-requests | Admin portal |  |  |  |
| 11 | nav | Colleges Data [/college-portal/index.html] | /college-portal/index.html | (none) |  |  |  |
| 12 | nav | Website Admin Panel (https://techdrona-website.web.app/admin) | - | - | - | - | external link |
| 13 | nav | Courses [/admin/courses] | /admin/courses | Admin portal |  |  |  |
| 14 | nav | Question review [/admin/question-review] | /admin/question-review | Admin portal |  |  |  |
| 15 | nav | Batches [/admin/batches] | /admin/batches | Admin portal |  |  |  |
| 16 | nav | Certificates & documents [/admin/certificates] | /admin/certificates | Admin portal |  |  |  |
| 17 | nav | Mentor sessions [/mentor] | /mentor | Admin · Mentoring portal |  |  |  |
| 18 | nav | Mentees [/mentor/students] | /mentor/students | Admin · Mentoring portal |  |  |  |
| 19 | nav | Mentor availability [/mentor/slots] | /mentor/slots | Admin · Mentoring portal |  |  |  |
| 20 | nav | Résumé reviews [/mentor/resume-reviews] | /mentor/resume-reviews | Admin · Mentoring portal |  |  |  |
| 21 | nav | Revenue [/finance] | /finance | Admin · Finance portal |  |  |  |
| 22 | nav | Admissions [/finance/admissions] | /finance/admissions | Admin · Finance portal |  |  |  |
| 23 | nav | Verify payments [/finance/admissions/verify] | /finance/admissions/verify | Admin · Finance portal |  |  |  |
| 24 | nav | Registrations [/finance/admissions/registrations] | /finance/admissions/registrations | Admin · Finance portal |  |  |  |
| 25 | nav | Fee plans [/finance/admissions/plans] | /finance/admissions/plans | Admin · Finance portal |  |  |  |
| 26 | nav | Orders [/finance/orders] | /finance/orders | Admin · Finance portal |  |  |  |
| 27 | nav | Refunds [/finance/refunds] | /finance/refunds | Admin · Finance portal |  |  |  |
| 28 | nav | Subscriptions [/finance/subscriptions] | /finance/subscriptions | Admin · Finance portal |  |  |  |
| 29 | nav | Invoices [/finance/invoices] | /finance/invoices | Admin · Finance portal |  |  |  |
| 30 | nav | Products & prices [/finance/products] | /finance/products | Admin · Finance portal |  |  |  |
| 31 | nav | Coupons [/finance/coupons] | /finance/coupons | Admin · Finance portal |  |  |  |
| 32 | nav | Reconciliation [/finance/reconciliation] | /finance/reconciliation | Admin · Finance portal |  |  |  |
| 33 | nav | Ticket queue [/desk] | /desk | Admin · Support portal |  |  |  |
| 34 | nav | Unblock requests [/desk/unblock-requests] | /desk/unblock-requests | Admin · Support portal |  |  |  |
| 35 | nav | Corporate enquiries [/desk/enquiries] | /desk/enquiries | Admin · Support portal |  |  |  |
| 36 | nav | Security overview [/security] | /security | Admin · Account security portal |  |  |  |
| 37 | nav | Cases [/security/cases] | /security/cases | Admin · Account security portal |  |  |  |
| 38 | nav | Incidents [/security/incidents] | /security/incidents | Admin · Account security portal |  |  |  |
| 39 | nav | Restrictions [/security/restrictions] | /security/restrictions | Admin · Account security portal |  |  |  |
| 40 | nav | Unblock reviews [/security/unblock-requests] | /security/unblock-requests | Admin · Account security portal |  |  |  |
| 41 | nav | Risk rules [/security/rules] | /security/rules | Admin · Account security portal |  |  |  |
| 42 | nav | Reports [/security/reports] | /security/reports | Admin · Account security portal |  |  |  |
| 43 | nav | Audit log [/admin/audit] | /admin/audit | Admin portal |  |  |  |
| 44 | nav | Policies [/admin/policies] | /admin/policies | Admin portal |  |  |  |
| 45 | nav | AI & apps [/admin/ai] | /admin/ai | Admin portal |  |  | error text (admin_trainer-001.png) |
| 46 | nav | Feature flags [/admin/feature-flags] | /admin/feature-flags | Admin portal |  |  |  |
| 47 | nav | Break-glass [/admin/break-glass] | /admin/break-glass | Admin portal |  |  |  |
| 48 | cta | /admin -> /admin/audit | /admin/audit | Admin portal |  |  |  |
| 49 | cta | /admin -> /college-portal/index.html | /college-portal/index.html | (none) |  |  |  |
| 50 | cta | /admin -> /admin/users?add=1 | /admin/users?add=1 | Admin portal |  |  |  |
| 51 | cta | /admin -> /admin/users?status=active | /admin/users?status=active | Admin portal |  |  |  |
| 52 | cta | /admin -> /admin/users | /admin/users | Admin portal |  |  |  |
| 53 | cta | /admin -> /finance/orders | /finance/orders | Admin · Finance portal |  |  |  |
| 54 | cta | /admin -> /studio/courses | /studio/courses | Content studio portal |  |  |  |
| 55 | cta | /admin -> /admin/batches | /admin/batches | Admin portal |  |  |  |
| 56 | cta | /admin -> /admin/approvals | /admin/approvals | Admin portal |  |  |  |
| 57 | cta | /admin -> /admin/courses | /admin/courses | Admin portal |  |  |  |
| 58 | cta | /admin -> /admin/certificates | /admin/certificates | Admin portal |  |  |  |
| 59 | cta | /admin -> /trainer | /trainer | Trainer portal |  |  |  |
| 60 | cta | /admin -> /finance | /finance | Admin · Finance portal |  |  |  |
| 61 | cta | /admin -> /admin/users?status=pending_verification | /admin/users?status=pending_verification | Admin portal |  |  |  |
| 62 | cta | /admin -> /admin/users?status=deactivated | /admin/users?status=deactivated | Admin portal |  |  |  |
| 63 | cta | /admin -> /desk | /desk | Admin · Support portal |  |  |  |
| 64 | cta | /admin -> /admin/privacy-requests | /admin/privacy-requests | Admin portal |  |  |  |
| 65 | cta | /admin -> /security | /security | Admin · Account security portal |  |  |  |
| 66 | cta | /admin -> /security/cases | /security/cases | Admin · Account security portal |  |  |  |
| 67 | palette | /admin "certificates" | /admin/certificates | Admin portal |  |  |  |
| 68 | palette | /admin "settings" | /admin/audit | Admin portal |  |  |  |
| 69 | palette | /admin "courses" | /admin/courses | Admin portal |  |  |  |
| 70 | palette | /admin "tests" | /admin | Admin portal |  |  |  |
| 71 | logo | sidebar logo from /admin/approvals | /admin | Admin portal |  |  |  |
| 72 | switcher | /admin -> Admin [/admin] | /admin | Admin portal |  |  |  |
| 73 | switcher | /admin -> Trainer [/trainer] | /trainer | Trainer portal |  |  |  |
| 74 | account-menu | /admin -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  | cross-portal: expected admin got student (admin_trainer-002.png) |
| 75 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 76 | portal-home | /studio | /studio | Content studio portal |  |  |  |
| 77 | nav | Dashboard [/studio] | /studio | Content studio portal |  |  |  |
| 78 | nav | Review queue [/studio/review] | /studio/review | Content studio portal |  |  |  |
| 79 | nav | Reported errors [/studio/reports/errors] | /studio/reports/errors | Content studio portal |  |  |  |
| 80 | nav | Courses [/studio/courses] | /studio/courses | Content studio portal |  |  |  |
| 81 | nav | Media [/studio/media] | /studio/media | Content studio portal |  |  |  |
| 82 | nav | Taxonomy [/studio/taxonomy] | /studio/taxonomy | Content studio portal | 403 GET studio/topics, 403 GET studio/topics |  | API 403/404 on allowed page; error text (admin_trainer-003.png) |
| 83 | nav | Companies [/studio/companies] | /studio/companies | Content studio portal | 403 GET studio/companies, 403 GET studio/companies |  | API 403/404 on allowed page; error text (admin_trainer-004.png) |
| 84 | nav | All questions [/studio/questions] | /studio/questions | Content studio portal |  |  |  |
| 85 | nav | Question banks [/studio/question-banks] | /studio/question-banks | Content studio portal |  |  |  |
| 86 | nav | Coding problems [/studio/coding] | /studio/coding | Content studio portal | 403 GET studio/coding/problems?limit=100, 403 GET studio/coding/problems?limit=100 |  | API 403/404 on allowed page; error text (admin_trainer-005.png) |
| 87 | nav | Template mocks [/studio/tests] | /studio/tests | Content studio portal |  |  |  |
| 88 | palette | /studio "certificates" | /studio | Content studio portal |  |  |  |
| 89 | palette | /studio "settings" | /studio | Content studio portal |  |  |  |
| 90 | palette | /studio "courses" | /studio/courses | Content studio portal |  |  |  |
| 91 | palette | /studio "tests" | /studio/questions | Content studio portal |  |  |  |
| 92 | logo | sidebar logo from /studio/review | /studio | Content studio portal |  |  |  |
| 93 | switcher | /studio -> Admin [/admin] | /admin | Admin portal |  |  |  |
| 94 | switcher | /studio -> Trainer [/trainer] | /trainer | Trainer portal |  |  |  |
| 95 | account-menu | /studio -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  | cross-portal: expected studio got student (admin_trainer-006.png) |
| 96 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 97 | portal-home | /trainer | /trainer | Trainer portal |  |  |  |
| 98 | nav | Dashboard [/trainer] | /trainer | Trainer portal |  |  |  |
| 99 | nav | Courses [/trainer/courses] | /trainer/courses | Trainer portal |  |  |  |
| 100 | nav | Learning paths [/trainer/paths] | /trainer/paths | Trainer portal |  |  |  |
| 101 | nav | Articles [/trainer/paths/articles] | /trainer/paths/articles | Trainer portal |  |  |  |
| 102 | nav | Engage [/trainer/engage] | /trainer/engage | Trainer portal |  |  |  |
| 103 | nav | Grading [/trainer/grading] | /trainer/grading | Trainer portal |  |  |  |
| 104 | nav | Assignments [/trainer/assignments] | /trainer/assignments | Trainer portal |  |  |  |
| 105 | nav | Tests [/trainer/tests] | /trainer/tests | Trainer portal |  |  |  |
| 106 | nav | Integrity flags [/trainer/integrity] | /trainer/integrity | Trainer portal |  |  |  |
| 107 | cta | /trainer -> /trainer/batches/01a1d5bb-e0c4-76fb-b95c-31bda5617995 | /trainer/batches/01a1d5bb-e0c4-76fb-b95c-31bda5617995 | Trainer portal |  |  |  |
| 108 | cta | /trainer -> /trainer/grading | /trainer/grading | Trainer portal |  |  |  |
| 109 | cta | /trainer -> /trainer/integrity | /trainer/integrity | Trainer portal |  |  |  |
| 110 | cta | /trainer -> /trainer/tests | /trainer/tests | Trainer portal |  |  |  |
| 111 | cta | /trainer -> /trainer/courses | /trainer/courses | Trainer portal |  |  |  |
| 112 | cta | /trainer -> /trainer/engage/new | /trainer/engage/new | Trainer portal |  |  |  |
| 113 | cta | /trainer -> /trainer/paths | /trainer/paths | Trainer portal |  |  |  |
| 114 | palette | /trainer "certificates" | /trainer | Trainer portal |  |  |  |
| 115 | palette | /trainer "settings" | /trainer | Trainer portal |  |  |  |
| 116 | palette | /trainer "courses" | /trainer/courses | Trainer portal |  |  |  |
| 117 | palette | /trainer "tests" | /trainer/tests | Trainer portal |  |  |  |
| 118 | logo | sidebar logo from /trainer/courses | /trainer | Trainer portal |  |  |  |
| 119 | switcher | /trainer -> Admin [/admin] | /admin | Admin portal |  |  |  |
| 120 | switcher | /trainer -> Trainer [/trainer] | /trainer | Trainer portal |  |  |  |
| 121 | account-menu | /trainer -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  | cross-portal: expected trainer got student (admin_trainer-007.png) |
| 122 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 123 | portal-home | /evaluator | /evaluator | Evaluator portal |  |  |  |
| 124 | nav | Grading [/evaluator] | /evaluator | Evaluator portal |  |  |  |
| 125 | nav | Tests [/evaluator/tests] | /evaluator/tests | Evaluator portal |  |  |  |
| 126 | nav | Integrity flags [/evaluator/integrity] | /evaluator/integrity | Evaluator portal |  |  |  |
| 127 | palette | /evaluator "certificates" | /evaluator | Evaluator portal |  |  |  |
| 128 | palette | /evaluator "settings" | /evaluator | Evaluator portal |  |  |  |
| 129 | palette | /evaluator "courses" | /evaluator | Evaluator portal |  |  |  |
| 130 | palette | /evaluator "tests" | /evaluator/tests | Evaluator portal |  |  |  |
| 131 | logo | sidebar logo from /evaluator/tests | /evaluator | Evaluator portal |  |  |  |
| 132 | switcher | /evaluator -> Admin [/admin] | /admin | Admin portal |  |  |  |
| 133 | switcher | /evaluator -> Trainer [/trainer] | /trainer | Trainer portal |  |  |  |
| 134 | account-menu | /evaluator -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  | cross-portal: expected evaluator got student (admin_trainer-008.png) |
| 135 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 136 | portal-home | /app | /app | Student portal |  |  |  |
| 137 | nav | Dashboard [/app] | /app | Student portal |  |  |  |
| 138 | nav | My learning [/app/learning] | /app/learning | Student portal |  |  |  |
| 139 | nav | My classes [/app/classes] | /app/classes | Student portal |  |  |  |
| 140 | nav | Explore courses [/app/courses] | /app/courses | Student portal |  |  |  |
| 141 | nav | My registrations [/app/registrations] | /app/registrations | Student portal |  |  |  |
| 142 | nav | My paths [/app/path/my] | /app/path/my | Student portal |  |  |  |
| 143 | nav | Assignments [/app/assignments] | /app/assignments | Student portal |  |  |  |
| 144 | nav | Live activities [/app/engage] | /app/engage | Student portal |  |  |  |
| 145 | nav | Certificates [/app/certificates] | /app/certificates | Student portal |  |  |  |
| 146 | nav | Practice [/app/practice] | /app/practice | Student portal |  |  |  |
| 147 | nav | Tests [/app/tests] | /app/tests | Student portal |  |  |  |
| 148 | nav | Coding [/app/coding] | /app/coding | Student portal |  |  |  |
| 149 | nav | Progress [/app/progress] | /app/progress | Student portal |  |  |  |
| 150 | nav | Free diagnostic [/app/diagnostic] | /app/diagnostic | Student portal |  |  |  |
| 151 | nav | Interview prep [/app/interview-prep] | /app/interview-prep | Student portal |  |  |  |
| 152 | nav | Mock interviews [/app/mentoring] | /app/mentoring | Student portal |  |  |  |
| 153 | nav | Résumé builder [/app/resume] | /app/resume | Student portal |  |  |  |
| 154 | nav | Company paths [/app/companies] | /app/companies | Student portal |  |  |  |
| 155 | nav | Notifications [/app/notifications] | /app/notifications | Student portal |  |  |  |
| 156 | nav | Billing [/app/billing] | /app/billing | Student portal |  |  |  |
| 157 | nav | My access [/app/access] | /app/access | Student portal |  |  |  |
| 158 | nav | Support [/app/support] | /app/support | Student portal |  |  |  |
| 159 | nav | Profile & settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 160 | palette | /app "certificates" | /app/certificates | Student portal |  |  |  |
| 161 | palette | /app "settings" | /app/settings/profile | Student portal |  |  |  |
| 162 | palette | /app "courses" | /app/courses | Student portal |  |  |  |
| 163 | palette | /app "tests" | /app/practice | Student portal |  |  |  |
| 164 | logo | sidebar logo from /app/learning | /app | Student portal |  |  |  |
| 165 | switcher | /app -> Admin [/admin] | /admin | Admin portal |  |  |  |
| 166 | switcher | /app -> Trainer [/trainer] | /trainer | Trainer portal |  |  |  |
| 167 | account-menu | /app -> Settings [/app/settings/profile] | /app/settings/profile | Student portal |  |  |  |
| 168 | account-menu | /app -> Account status [/app/account-status] | /app/account-status | Student portal |  |  |  |
| 169 | account-menu | Tech Drona website (https://techdrona-website.web.app) | - | - | - | - | external |
| 170 | owner-bug | /admin account menu -> Settings | /app/settings/profile | Student portal |  |  | cross-portal: expected admin got student (admin_trainer-009.png) |
| 171 | owner-bug | then student sidebar -> Certificates | /app/certificates | Student portal |  |  | cross-portal: expected admin got student (admin_trainer-010.png) |
