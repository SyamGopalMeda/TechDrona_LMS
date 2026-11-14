# Live re-verification of the audit fixes (2026-11-14)

- **Sites:** LMS https://techdrona-lms-app.web.app (SPA, functions and `/college-portal/**` just deployed); website https://techdrona-website.web.app.
- **How:** Playwright on Cloud Build only (`qa/live-e2e/run.sh`), live sites only. Navigation and reading only: no form was submitted. One extra read-only source was used: the `lmsscheduler` function log (admin 11).
- **Sources checked:** `admin.md`, `staff-portals.md`, `student-and-access.md`, `responsive.md`, `website.md` and the `fixes-*.md` notes.
- **Waves:** builds that used the same QA role never ran at the same time. One build had to be repeated for that reason (see the College portal note under section 1).

## Totals

| Result | Count |
|---|---|
| Verified on live | 50 |
| Partly verified (main fix works, a remainder is still open) | 5 |
| Still failing | 0 |
| Not verifiable on live | 4 |
| **New regressions or new findings** | **6** (1 medium, 5 low or info) |

## Builds

| Build | Spec / scope | Result |
|---|---|---|
| `9f298a7c-c2cc-461e-88ee-1520411356e8` | `audit-admin`; admin; desktop (adds College portal checks, `/admin/system` and every `/studio/*` URL) | 66/66 passed |
| `5beba1aa-4d7c-406f-b338-99a837e77fc5` | `audit-staff`; trainer, evaluator, content; desktop (adds the Integrity batch-filter check) | 3/3 passed |
| `73566b50-ce96-48af-bc60-bda1acff50c4` | `audit-website`; all 7 devices (adds the popup-vs-menu and cookie-bar checks) | 32 passed, 17 skipped by design |
| `e8c1d75a-20ba-49d3-922a-c667a3918891` | `audit-website --grep=hash`; no QA sign-in; desktop, phone-android (settled deep-link check) | passed |
| `f5ae6b2f-14f7-4265-aad1-268ff3183885` | `audit-responsive`; admin; all 7 devices | passed |
| `d9872b8a-3ad4-43ba-aa86-6762060fcb3e` | `audit-responsive`; content, trainer, evaluator, public; all 7 devices | passed |
| `7e6cba21-a7bb-43d2-afbc-83d7170f9c98` | `audit-responsive`; student; all 7 devices | passed |
| `30d8befa-8a90-4511-a457-e808e136f868` | `audit-student --grep-invert=post-login`; all roles; desktop, phone-android | 23 passed |
| `90154536-c9df-4671-8054-28810ff2a139` | `smoke`; all roles; all 7 devices | 35/35 passed |
| `6fe41f53-a7e6-41e6-88ea-da32d691a0dc` | `audit-student --grep=college`; student only; desktop (clean rerun, see the College portal note) | passed |

- **Findings JSON:** `qa/live-e2e/runs/<build>/findings/`.
- **Screenshots:** `gs://td-qa-reports-f4fe3/runs/<build>/artifacts/`. The ones cited below were also downloaded to `qa/live-e2e/runs/<build>/shots/`.

**Spec changes made for this check** (expectations and extra probes; no app code was changed):

| Spec | Change |
|---|---|
| `audit-admin.spec.ts` | Adds `/admin/system` and the remaining `/studio/*` URLs. New test "college portal (admin)": headers, `api/session`, `api/colleges`, the iframe content and CSP console errors. |
| `audit-staff.spec.ts` | Integrity Batch filter: the options it lists, and the calls made when one is chosen. More "Find a page" queries. |
| `audit-website.spec.ts` | Three new tests: "fix: lead popup waits for the open menu", "fix: cookie bar fits" and "fix: hash deep links settle on target". |
| `audit-student.spec.ts` | New test "college portal: student and signed out". |
| `audit-responsive.spec.ts` | Nav expectations are now the visible items: Admin 25, Student 15. Adds `/admin/system`. Reports `extra` and `count` for each menu. |

## 1. Per-finding status

### College Data Portal (`fixes-college-portal.md`, admin F1)

| Check | Status | Evidence |
|---|---|---|
| `/college-portal/index.html` for admin | **Verified** | 200 `text/html`. Headers: the portal CSP with `frame-ancestors 'self'`, `X-Frame-Options: SAMEORIGIN`, `Cache-Control: private, no-store`. `api/session`: `authenticated: true, role: editor, sso: true`. `api/colleges`: 200, 171 colleges. |
| `/admin/college-data` shows the portal in the frame, no CSP errors | **Verified** | The iframe holds `/college-portal/index.html`, titled "Home · Tech Drona Outreach Portal", with real content ("TARGET 400 …"). No CSP or `frame-ancestors` console error. Screenshot: `runs/9f298a7c…/shots/desktop-college-data-framed.png`. The map's district boundaries fail with 404 (N2). |
| "Open full screen" / sidebar / Modules entry | **Verified** | `/college-portal/index.html` as a document shows the portal for QA Admin (Editor) on desktop, laptop and tablet-landscape (responsive admin run). |
| Student gets 403 or a redirect | **Verified** | Build `6fe41f53`: the page returns 403 "Admins only. The College Data Portal is available to LMS admins only.", the API returns 403 `forbidden`, and `/admin/college-data` redirects to `/app`. |
| Signed out redirects to login | **Verified** | The page returns 303 to `/login?next=%2Fadmin%2Fcollege-data`. `api/colleges` returns 401 `auth_required`, and `/college-portal/` returns 308 to `index.html`. Seen in build `30d8befa` and by curl. |

> **College portal note:** in build `30d8befa` the student probe came back as signed out (303 to /login). That build's `api probes` and `entry flows` tests sign the student in again, and with the student cap of 2 that evicted the stored session. Even `/admin/college-data` went to `/login` there. The student-only rerun `6fe41f53` gives the real answer, 403.

### API fixes (`fixes-api.md`)

| # | Finding | Status | Evidence |
|---|---|---|---|
| F1 / F-13 | Evaluator 403 on `batches/{id}`; Integrity batch filter empty | **Verified** | Evaluator `batches/{id}` 200, `/members` 200, `batches?mine=true` 200, `GET batches` 200. On `/evaluator/integrity` the Batch filter lists "All batches" and "Generative AI". Choosing it makes `200 GET integrity/flags?batch_id=…`. No 4xx call and no console error. The trainer page behaves the same. |
| F1 (scope) | Content manager still refused | **Verified** | qa-content gets `batches` 403 (staff and API probes). |
| F3 | Content manager ticket permissions kept (decision) | n/a | `support/queue` is still 200 for content, as decided. |
| admin 9 | "Signed in now" counts QA sessions | **Partly verified** | "Signed in now" is now **2**; it was 16. "New registrations" still shows **4**: the QA users are not flagged `is_synthetic` (a data step, as the fix note says). |
| admin 11 | Hourly reconciliation rows with no gateway | **Verified** | `lmsscheduler` logged `commerce.reconciliation_skipped` at 08:00 UTC (13:30 IST). The newest row on `/finance/reconciliation` is 12:30 IST, from before the deploy. |
| admin 14 / F-12 | Session eviction now carries a specific `detail` | **Not verifiable** | It needs 3 fresh sign-ins of one account, which would evict the other QA sessions on live. The SPA still drops `reason`; that change is pending, as the fix note says. |
| F-15 | Trainer `mentor/students`, content `admin/certificates` 200 | n/a (review only) | Unchanged: trainer `mentor/students` 200, content `admin/certificates` 200. |

### Navigation and IA (`fixes-nav.md`)

| Finding | Status | Evidence |
|---|---|---|
| Admin nav 42 → **25 items in 9 sections** | **Verified** | All 7 devices list 25 items with nothing missing or extra. Sections: Overview 2, People 3, Colleges 1, Website 1, Learning 3, Payments 4, Support 2, Security 4, Settings 5. |
| M5/M12: 8 gateway pages hidden; URLs still work | **Verified** | They are not in the nav. All 8 URLs load ("Admin · Finance" shell, no 4xx). |
| M4 Mentoring, M7 Corporate enquiries, M3 Question review, M6 Risk rules / Reports / Unblock reviews: hidden | **Verified** | Not in the nav. Each URL still loads without an error. |
| M9: Feature flags and Break-glass moved to **System status** | **Verified** | `/admin/system` loads ("System status", 7 integrations, "Advanced tools" linking to Feature flags and Break-glass history). |
| F6/M11: Integrations card off the dashboard | **Verified** | The dashboard text has no Integrations card. |
| M1/F4: dashboard links go to `/admin/courses`; "Open Content studio" label | **Verified** | The dashboard links contain no `/studio/*` and no `/finance/orders`; "All courses" goes to `/admin/courses`. `/admin/courses` shows "Open Content studio" and "Authoring happens in the content studio". |
| M2/F13: Teacher Portal card only with a trainer grant | **Verified** | No "Teacher" card on the dashboard. |
| M12: "Payments to verify" KPI and Admissions card | **Verified** | "Payments to verify 0 / ₹0.00 waiting"; Admissions card with "Registered" and "Verified fees". No "Sales" card. |
| F12: simple-auth copy | **Verified** (page copy) | `/admin/roles`: "Removing an Admin role needs a second admin to approve". `/admin/approvals` no longer says "Approving asks you to confirm again". The grant dialog was not opened. |
| F2 / F-5: Admin in Studio limited to Courses and Review | **Verified** | `/studio`, `/studio/taxonomy`, `/questions`, `/reports/errors`, `/coding`, `/media`, `/companies`, `/question-banks` and `/tests` all redirect to `/studio/courses`. `/studio/review` loads. No 403 anywhere in the admin run. |
| F3: Portal switcher for Admin | **Verified, but see N1** | Header "Switch portal" lists "Content studio → /studio" and "Admin → /admin". It causes the 320 px header regression N1. |
| No 403 page reachable from the admin nav | **Verified** | All 25 nav targets and all 41 other admin URLs: 0 failed API calls and no error UI (desktop run, and the responsive run on 7 devices). |
| Student F-7/F-10: sidebar 15 items | **Verified** | Desktop sidebar: 15 items. The phone tab bar shows Home, Learn, Practice, Tests and More. The responsive run reaches all 15 on 7 devices, with nothing extra. |
| Staff §4: no "Invalidate" outcome for the evaluator | **Not verifiable** | The QA batch has no integrity flags, so the decision dialog cannot be opened. |
| Staff F5: Evaluator Tests empty state | **Verified** | "No tests yet. Tests assigned to your batches appear here when students submit attempts." |
| Staff F6: "Account settings" in the staff and admin navs | **Verified** | Trainer, evaluator, content and admin navs list "Account settings". "settings" finds it for each of them. |

### Student fixes (`fixes-student.md`)

| # | Status | Evidence |
|---|---|---|
| F-2 Mock interviews dead-end | **Verified** | "Mock interviews aren't open for you yet … Build your résumé meanwhile" → `/app/resume`. No Billing link. |
| F-3 "Browse free courses" with 0 courses | **Verified** | `/app/learning` and the dashboard show "See upcoming courses" → `/app/courses`, with the new copy. |
| F-4 waitlist copy, double "Coming soon", whole-card link, 12 px label | **Verified** (copy and links) | Strip: "Registrations open soon. Join the waitlist on our website to hear first." Each coming-soon card has "Join the waitlist on our website" (`#register`) and "Course details on our website". Title links say "(opens the Tech Drona website in a new tab)". The probe still measures the title `<a>` at 251×19, because it cannot see the stretched `::after` (false positive). |
| F-1 catalog.json CORS (UI side plus website header) | **Verified** | No CORS console error on `/app`, `/app/courses` (desktop and phone), `/admin/courses`, `/finance/admissions`, `/finance/admissions/plans` or LMS `/register`. The response sends `Access-Control-Allow-Origin: *`, and a fetch from the LMS origin returns 200 (10.5 KB). |
| F-8 Practice empty state | **Verified** | "No practice sets yet. Practice sets will appear when your course content is published…" No disabled Start button. |
| F-9 Coding empty state | **Verified** | "No coding problems yet". |
| F-11 `/app/orders` blank | **Verified** | It redirects to `/app/billing`. |
| admin 8 / M13: staff profile fields | **Verified** | The admin, trainer, evaluator and content profiles show only Full name, and say "Ask an administrator…". The student still sees Graduation year and Branch. |
| staff F4: account-status links for staff | **Verified** | "Go to the Admin portal", "Back to the Admin portal" (and the same for the Trainer, Evaluator and Content studio portals). No Contact support and no review-request link for staff. |
| F-16 phone Save bar | **Verified** (sticky) | The bar is sticky above the tab bar. It now overlaps a field at scroll 0 on iPhone and laptop (N4). |

### Responsive (`fixes-responsive.md`, `responsive.md`)

| # | Status | Evidence |
|---|---|---|
| F1: phone title 30 px → 24 px | **Verified** | Every `PageHeader` h1 is **24 px** on all 3 phones, for every role. Before, all admin and student pages were 30 px. The h1s still above 24 px are other components: dashboard heroes (25.6 px), auth pages (29.6 px), `/modules` and `/app/account-status` (30 px). |
| F3: standalone links ≥ 24 px | **Partly verified** | `/login`, `/forgot-password`, the legal pages and `/app/progress` are no longer flagged: the public LMS pages report 0 tap issues on all 7 devices; before, 18 issues on 8 pages. Still small, and listed as open in the fix note: `/app/account-status` "Check a review request", "Contact support" and "Privacy requests" (22 px), and `/mentor` "Open queue" (72×15). |
| F4 / staff F8: 24 px checkbox and radio on touch | **Verified** | No checkbox or radio is flagged on `/login`, `/signup` or `/trainer/engage/new` on touch devices. |
| F5: search in the student More sheet | **Verified** | `moreSheet.search = true` on tablet and the 3 phones. |
| F6 / admin 15: Ctrl K hint 11 px | **Verified** | No `font` issue for the hint on desktop or laptop. |
| F7: staff Menu closes on a tap | **Verified** | `closedAfterNav = true` in 16 of 16 runs (admin, trainer, evaluator and content × tablet and 3 phones). The student More sheet also closes. |
| Staff F6: "Find a page" ranking | **Partly verified** | "grade" and "grades" find Grading (trainer, evaluator); "tests" lists Tests first; "setting" lists Account settings first (admin). Still no keywords: "profile" finds nothing for staff (open in the fix note). The student "settings" query also lost its result (N3). |
| F2: course-card kicker 10.9 px | **Partly verified** | The kicker is no longer flagged. The fact labels "Program length", "Class schedule" and "Major projects" on `/app/courses` and `/admin/courses` are still 10.88 px. |

### Website (`fixes-website.md`, `website.md`)

| # | Status | Evidence |
|---|---|---|
| 1 catalog.json CORS | **Verified** | 200, `ACAO: *`, `Cache-Control: public, max-age=300`, 8 courses. The LMS-origin fetch works and the console stays clean. |
| 2 Popup over the open menu | **Verified** | Cookie bar pre-answered (popup due after 4 s), menu kept open for about 30 s on tablet, Pixel 7, iPhone 13 and iPhone SE. All 40 samples: popup **not** shown, menu on top, `.mp` z-index 265. After the menu closed, the popup opened, so it is deferred, not broken. |
| 3 Cookie bar at 320 px | **Verified** | iPhone SE: "Accept cookies" fully in view (x 160–306 of 320), no horizontal scroll; the bar covers 21 % of the screen (31 % before). Pixel 7 14 % (19 % before), iPhone 13 18 % (24 % before). The consent sentence is hidden at ≤ 420 px, as designed. |
| 4 Home.jsx null error | **Verified** (not reproduced) | The menu test navigating from `/` to `/about` logs no error on any of the 7 devices. |
| 5 Deep links off target | **Verified** | After a settled load, every target sits just under the header (78 px desktop, 68 px phone) at 0.5 s, 3 s and 6 s. The URLs were `/courses/*#register`, `/recruitment#hire`, `/procurement#quote` and `/projects#companion` (before: 838, 699 and 300 px off, and −157 px). The crawl's own number (`topAfterScroll`) is read before the page scrolls, so it is not valid for this check. |
| 6 Tap targets | **Verified** on touch | Course-card titles, footer "Privacy Policy" / "Cookie settings", the cookie-bar link and breadcrumbs are no longer flagged. The menu's "View all…" and email links are still 22 px on desktop and laptop only (the fix targets touch and ≤ 860 px, as intended). |
| 6 Labels under 12 px | **Partly verified** | `.pc-facts`, `.wk-url` and similar labels are no longer in the samples. `/training` on phones still has 33 elements under 12 px, such as 9.5 px spans "NextGen 2026" and "Cloud & Career", probably the honeycomb illustration the fix left on purpose. This needs a look. |
| 7 Slow `/solutions` and `/courses` | **Verified** | `/solutions` load is 1.2–3.5 s (8.6–10 s before). `/courses` is 0.5–2 s, with one tablet outlier of 9.9 s. |
| F9 `/courses` "Certificate" tile at 320 px | **Verified** | No text overflow on the iPhone SE. |
| 8 favicon / soft 404 | **Verified** | `/favicon.ico` returns 200 `image/x-icon`. Unknown URLs carry `robots: noindex` and no canonical. HTTP 200 stays, as decided. |
| 9 Forms validate on blur, 5 domain, 6 legal pages | n/a | Not in scope of the fixes (owner decisions). |

### Regression sweep (all roles)

| Check | Status |
|---|---|
| Every nav item of every role loads without 4xx/5xx or error UI | **Verified.** Admin 25 + 41 other URLs, trainer 10, evaluator 4, content 12, student 15 + 14 other URLs. The only failing request is the map GeoJSON 404 inside the College portal (N2). |
| No cross-portal jumps | **Verified.** The access matrix (5 roles × 27 URLs) shows every foreign URL redirecting to the role's home, with no foreign API call. Staff API probes match the role matrix; the student gets 403 on all 16. Account menu → Settings stays in each role's own shell. |
| Smoke, 5 roles × 7 devices | **35/35 passed.** |

## 2. New regressions and new findings

| # | Sev | What | Evidence | Likely file |
|---|---|---|---|---|
| **N1** | **Medium** | **Admin header breaks at 320 px.** The new "Switch portal" button (admin F3 fix) wraps to two lines and pushes "Modules" onto the logo (cut to "TECH DR"). The Modules panel then opens 55 px past the left edge, cutting off "Tech Drona LMS", "Colleges Management" and "All modules". This affects all 41 admin pages on the iPhone SE. At 375 px and up it is fine. The earlier run had no overlap and the panel fit. | Responsive build `f5ae6b2f`: `overlap: a.flex.shrink-0 ⟷ summary "Modules"` on 41/41 phone-small admin pages; `moduleSwitcher.panel = {l: -55, fits: false}`. Old run `c451de1d`: 0 overlaps, panel `l: 16`. Smoke `90154536` shows the same. Screenshots: `qa/live-e2e/runs/f5ae6b2f-14f7-4265-aad1-268ff3183885/shots/nav-moduleSwitcher.jpg`, `…/shots/admin_users.jpg`. | `apps/lms-spa/src/components/shell/PortalSwitcher.tsx` (the long label at every width; use an icon or a short label below `sm`) and `ModuleSwitcher.tsx:48` (the `absolute right-0` panel overflows once the button moves left). |
| **N2** | Low | **College portal map: district boundaries 404.** The map logs `[map] could not load district boundaries Error: District boundaries HTTP 404` (`js/map/map.js:65`) on every portal load. The page works without the district layer. | Admin build `9f298a7c` (frame, full screen) and responsive `f5ae6b2f` (desktop, laptop, tablet-landscape). | `apps/college-data/portal/.gcloudignore`: the pattern `data/` follows gitignore rules, so it also drops `public/data/ap_districts.geojson` from the Cloud Build upload, not only the root `data/` (DB and seed). Anchor it as `/data/`, rebuild the image, and redeploy Cloud Run. |
| N3 | Low | Student "Find a page → settings" now finds nothing. Before, it found "Profile & settings"; that item is now hidden, and "Account settings" was added only to the staff and admin navs. | `audit-student-pages-desktop.json` → `chrome.find.settings` = "No page matches". | `apps/lms-spa/src/lib/nav/portals.ts` (student nav) or the planned `keywords` support in `PortalNav.tsx`. |
| N4 | Low | Sticky "Save changes" bar on `/app/settings/profile` overlaps a form field at scroll 0 (iPhone 13; laptop for the student; iPhone for the admin). This side effect of F-16 is expected while scrolling, but at scroll 0 it covers a field that is on screen. | Responsive `7e6cba21` (`overlap: input#_r_a_ ⟷ button "Save changes"`) and `f5ae6b2f`. Screenshot: `qa/live-e2e/runs/7e6cba21-a7bb-43d2-afbc-83d7170f9c98/shots/app_settings_profile.jpg`. | `apps/lms-spa/src/features/account/components/ProfileSettings.tsx` (add bottom padding to the form equal to the bar's height). |
| N5 | Low | Tablet-landscape `/admin`: the new quick action "Admissions & fees" (and its description) overflows its 75 px text box. | Responsive `f5ae6b2f` and smoke `90154536` (`text-overflow … "Admissions & fees" text 91px in 75px box`). | `apps/lms-spa/src/features/admin/components/Governance.tsx` (quick-action grid; `min-w-0` / wrap). |
| N6 | Info | `/app/account-status` shows staff "Signed-in devices at once: 2", but the staff cap is 3 (only students have 2). | Staff run `5beba1aa` (account pages) and admin run `9f298a7c`. | `apps/lms-spa/src/features/unblock/components/AccountStatus.tsx` (show the staff policy value, or hide the row for staff). |

**Checked and not regressions:**
- The student tab-bar overlaps at scroll 0 were already there (41 before, 39 now), and the content scrolls clear.
- `batches/{id}/classes` 404 for staff is a wrong path in the spec's probe; the batch pages make no failing call.
- The iOS WebKit `Fetch API cannot load … access control checks` page errors and Firestore `RPC_ERROR` lines come from requests cancelled when the test navigates away.
- The probe's 1×1 "tap" items are the forms' hidden honeypot fields.

## 3. Not verifiable on live (why)

| Item | Why |
|---|---|
| admin 14 / F-12: `401 session_revoked` with the new `detail` | It needs 3 fresh sign-ins of one QA account, which would sign the other running checks out. Run it alone as `fixes-api.md` describes. The SPA change that would show the message is still pending. |
| Staff §4: no "Invalidate" outcome for the evaluator | There are no integrity flags in the QA batch, so the dialog cannot be opened. |
| Staff F2: attempt, result and review routes | There are still no tests or attempts in the QA batch. |
| admin F12: grant-dialog button text ("Grant" instead of "Request grant") | Opening the grant dialog was avoided to keep the run read-only. The page copy was verified. |

## 4. Still open (unchanged, known)

- "New registrations 4" counts the QA accounts until they are flagged `is_synthetic` (data step).
- Website Admin Panel opens the website sign-in (SSO not integrated; admin F5).
- Standalone small links on `/app/account-status` and `/mentor`; raw checkboxes in the studio and engage editors; "Find a page" keywords (see the "Still open" list in `fixes-responsive.md`).
- Course-card fact labels at 10.88 px (`features/site-catalog`).
