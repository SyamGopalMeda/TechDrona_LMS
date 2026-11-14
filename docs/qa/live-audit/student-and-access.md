# Live audit: Student portal, entry flows and cross-role access

- **Site:** https://techdrona-lms-app.web.app (live). Audited on 2026-11-14 through the Cloud Build runner only (`qa/live-e2e`). Navigation and reading only; no data was created or changed.
- **Spec:** `qa/live-e2e/tests/audit-student.spec.ts`
- **Evidence:** clean run `77a9bd92-12a2-4672-98c7-e7e8a37bff30` (desktop and phone-android, all 5 roles), at `qa/live-e2e/runs/77a9bd92-…/findings/*.json` and `gs://td-qa-reports-f4fe3/runs/77a9bd92-…/`.
- **Post-login landing:** taken from run `5f3a1867-da66-4a57-8437-e0e57ea46c9f`. That run's other data is void, because its UI sign-ins revoked the stored sessions (see F-12).
- **Data state:** 0 LMS courses; 8 website courses, all "Coming soon"; the student has no enrolment.

## Summary

| Area | Result |
|---|---|
| Staff APIs called with the student session | **Pass.** 16 of 16 return `403 permission_denied` (API request and in-page `fetch`) |
| Student opening any staff portal (24 URLs) | **Pass.** Silently redirected to `/app`, Student shell |
| Staff-only roles opening `/app/*` | **Pass.** Redirected to their home portal; `/app/settings/**` and `/app/account-status` stay inside the role's own shell |
| Account menu → Settings (fixed 2026-11-13) | **Pass for every role** on desktop and phone |
| `/`, `/login`, `/continue`, `/modules` while signed in | **Pass.** Each role lands on its home; admin lands on `/modules` |
| Student pages | 23 of 23 nav pages render with a heading and an empty state. No 4xx/5xx API calls. The only console error is the known catalog.json CORS error |
| Main problems | Upsell and empty states lead to dead ends (Mock interviews → Billing; "Browse free courses" with 0 courses); too many nav items for an empty platform; course cards bounce to the website; admin can enter the Content studio, but its APIs refuse admin |

## 1. Student navigation

Desktop sidebar: 23 items, exactly as in `apps/lms-spa/src/lib/nav/portals.ts:119-143`. The `appKey` toggles (paths, assignments, engage) are all on. Mobile tab bar: Home · Learn · Practice · Tests · More. The More sheet lists the other 19 items.

| # | Section | Item → URL | Live result (empty account) | API errors | Verdict / recommendation |
|---|---|---|---|---|---|
| 1 | – | Dashboard `/app` | Stat tiles all 0. Cards: "Courses from Tech Drona" (3 "Coming soon" cards linking to the **website**), Due soon, Continue learning, Quick actions, Access & billing | CORS error on catalog.json (F-1) | Keep. Fix F-1, F-3 and F-4 |
| 2 | Learn | My learning `/app/learning` | "You haven't enrolled… **Browse free courses**" → `/app/courses`, which has **no** free courses | – | Keep. Fix the CTA (F-3) |
| 3 | Learn | My classes `/app/classes` | "No live classes. When you join a batch…" | – | Keep (admissions → batch classes) |
| 4 | Learn | Explore courses `/app/courses` | 8 website courses, all "Coming soon"; tiles show Open 0 · Running 0 · Upcoming 8 · Completed 0; every card links out to the website | CORS (F-1) | Keep. Merge with My registrations (F-6) |
| 5 | Learn | My registrations `/app/registrations` | "You haven't registered… Explore courses" | – | Fold into Explore courses as a tab, or show only when the student has a registration (F-6) |
| 6 | Learn | My paths `/app/path/my` | "No paths yet" → My learning | – | Hide until paths exist (F-7) |
| 7 | Learn | Assignments `/app/assignments` | "Nothing due right now" | – | Keep (batch work) |
| 8 | Learn | Live activities `/app/engage` | Join-code form plus "Nothing yet" | – | Keep; useful in class |
| 9 | Learn | Certificates `/app/certificates` | "No certificates yet" | – | Keep |
| 10 | Practice & tests | Practice `/app/practice` | Subject select is **empty**; the "Start 10-question set" button is disabled with no explanation | – | Add a "No practice subjects published yet" empty state (F-8) |
| 11 | Practice & tests | Tests `/app/tests` | "No tests open right now" → practice | – | Keep |
| 12 | Practice & tests | Coding `/app/coding` | "**No problems match these filters**", although no problems exist at all | – | Fix the empty-state wording (F-9) |
| 13 | Practice & tests | Progress `/app/progress` | All zeros and charts | – | Keep |
| 14 | Practice & tests | Free diagnostic `/app/diagnostic` | "No diagnostic test is open right now" | – | Hide until one is published, or move it under Tests (F-7) |
| 15 | Placement | Interview prep `/app/interview-prep` | A hub that duplicates items 16–18 and Tests | – | Make it the single Placement entry (F-7) |
| 16 | Placement | Mock interviews `/app/mentoring` | Upsell "come with a placement package… **See plans**" → `/app/billing`, which has no plans | – | **Dead end** (F-2). Hide until packages are on sale |
| 17 | Placement | Résumé builder `/app/resume` | "Start my résumé" | – | Keep (works without courses) |
| 18 | Placement | Company paths `/app/companies` | "Company paths are coming soon" | – | **Feature not built.** Remove from nav (F-7) |
| 19 | Account | Notifications `/app/notifications` | "No notifications yet" | – | Duplicates the header bell. Remove from the sidebar (F-10) |
| 20 | Account | Billing `/app/billing` | Orders/Subscriptions/Invoices/Refunds tabs, all empty → Explore courses | – | Nothing is sold through commerce yet (payments go through Admissions/UPI). Hide or merge with My access (F-7) |
| 21 | Account | My access `/app/access` | "Nothing here yet" | – | Merge with Billing as "Purchases & access" (F-7) |
| 22 | Account | Support `/app/support` | "No tickets yet", New ticket, "Browse help articles" → `/help` | – | Keep |
| 23 | Account | Profile & settings `/app/settings/profile` | Profile form; tabs Security, Devices, Privacy | – | Duplicates the account menu's "Settings". Keep one (F-10) |

Pages outside the nav, also probed:
- `/app/account-status`: "All clear" (account menu).
- `/app/path`: Learning path.
- `/app/bookmarks`: "aren't available yet".
- `/app/analytics`: redirects to `/app/progress`.
- `/app/onboarding`: "Get started", 3 steps, all empty.
- `/app/orders`: **blank page** (F-11).

**Shell chrome (student):**

| Element | Live |
|---|---|
| Header | Logo → `/app`; bell (`aria-label` "Notifications") → `/app/notifications`; account button "Account: QA Student". No portal switcher (student has one portal) |
| Account menu | Settings → `/app/settings/profile`; Account status → `/app/account-status`; Tech Drona website ↗ |
| Find a page | "course" → Explore courses; "bill" → Billing; "interview" → Interview prep and Mock interviews; "settings" → Profile & settings; "certificate" → Certificates; "admin", "pay" and "zzz" → "No page matches". No staff pages leak. "pay" finds nothing, although payments live under My registrations |
| Mobile tab bar | Home, Learn, Practice, Tests, More. More holds the other 19 items |
| Dashboard CTAs | All 16 internal links land on a real page in the Student shell. The 3 course cards go to `techdrona-website.web.app/courses/<slug>` (F-4) |

## 2. Entry flows per role

Desktop and phone-android gave the same results. "Badge" is the sidebar portal badge or top-bar pill.

| Flow | student | trainer | evaluator | content | admin |
|---|---|---|---|---|---|
| `/` signed out | `/login` | `/login` | `/login` | `/login` | `/login` |
| **Post-login landing** (sign-in form, clean browser) | `/app` | `/trainer` | `/evaluator` | `/studio` | `/modules` ("Where do you want to work?") |
| `/` signed in | `/app` | `/trainer` | `/evaluator` | `/studio` | `/modules` |
| `/login` signed in | `/app` | `/trainer` | `/evaluator` | `/studio` | `/modules` |
| `/continue` (no remembered page) | `/app` | `/trainer` | `/evaluator` | `/studio` | `/modules` |
| `/modules` | → `/app` (single module) | → `/trainer` | → `/evaluator` | → `/studio` | Hub: "Tech Drona LMS" (super admin) → `/continue?area=lms&fallback=/admin`; "Colleges Management" (editor) |
| Home shell | Student portal | Trainer portal | Evaluator portal | Content studio portal | Admin portal |
| Account menu | Settings, Account status, Website | Settings, Website | Settings, Website | Settings, Website | Tech Drona LMS, Colleges Management, All modules, Settings, Website |
| Account menu → **Settings** | `/app/settings/profile`, **Student** shell | `/app/settings/profile`, **Trainer** shell | **Evaluator** shell | **Content studio** shell | **Admin** shell |
| `/app/practice` right after Settings | `/app/practice` | → `/trainer` | → `/evaluator` | → `/studio` | → `/admin` |
| `/app`, `/app/learning`, `/app/courses` | stay | → `/trainer` | → `/evaluator` | → `/studio` | → `/admin` |
| `/app/account-status` | Student shell | Trainer shell | Evaluator shell | Content studio shell | Admin shell |

**Admin landing: `/modules` is right.** The admin account holds two modules: LMS (super_admin) and Colleges Management (editor). The hub is the only page that offers both (and the website admin, once website SSO is live). It also costs only one click, because the LMS card resumes the last LMS page through `/continue` and otherwise falls back to `/admin`. Single-module roles are forwarded straight to their portal, so nobody sees a one-card page. Keep `routeForLoginResult` → `/continue` → `/modules` (`features/auth/lib/login-flow.ts:37-40`).

Two small nits:
- Admin's `/continue` in a fresh browser lands on the hub, not `/admin`. This is by design, because `continueFallback` without an area is the hub.
- Admin's account menu should also list "Account status", as the student's does.

## 3. Cross-role access matrix

Each cell is the final URL and the shell shown, for the portal home and 2 deep pages (27 URLs per role, desktop).

| Portal (home · deep · deep) | student | trainer | evaluator | content | admin |
|---|---|---|---|---|---|
| `/app` · `/app/learning` · `/app/billing` | ✔ all three, Student | → `/trainer` | → `/evaluator` | → `/studio` | → `/admin` |
| `/admin` · `/admin/users` · `/admin/certificates` | → `/app` | → `/trainer` | → `/evaluator` | → `/studio` | ✔ Admin |
| `/finance` · `/finance/orders` · `/finance/admissions/registrations` | → `/app` | → `/trainer` | → `/evaluator` | → `/studio` | ✔ "Admin · Finance" |
| `/desk` · `/desk/unblock-requests` · `/desk/enquiries` | → `/app` | → `/trainer` | → `/evaluator` | → `/studio` | ✔ "Admin · Support" |
| `/security` · `/security/cases` · `/security/restrictions` | → `/app` | → `/trainer` | → `/evaluator` | → `/studio` | ✔ "Admin · Account security" |
| `/mentor` · `/mentor/students` · `/mentor/slots` | → `/app` | → `/trainer` | → `/evaluator` | → `/studio` | ✔ "Admin · Mentoring" |
| `/studio` · `/studio/questions` · `/studio/courses` | → `/app` | → `/trainer` | → `/evaluator` | ✔ Content studio | ✔ Content studio, but **`403 GET studio/questions`, `403 studio/question-reports`** (F-5) |
| `/trainer` · `/trainer/grading` · `/trainer/tests` | → `/app` | ✔ Trainer | → `/evaluator` | → `/studio` | ✔ Trainer |
| `/evaluator` · `/evaluator/tests` · `/evaluator/integrity` | → `/app` | → `/trainer` | ✔ Evaluator; integrity page gets **`403 GET batches/{id}`** (F-13) | → `/studio` | ✔ Evaluator |

Every redirect is silent. The user lands on their home page without a "you don't have access to that page" notice (see F-14).

## 4. Staff API probes (GET, browser context)

Each call was made twice: once with `context.request` (session cookies) and once with in-page `fetch(…, {credentials:"include"})`. Both always returned the same status.

| Endpoint | student | trainer | evaluator | content | admin (baseline) |
|---|---|---|---|---|---|
| `admin/users` | 403 | 403 | 403 | 403 | 200 |
| `admin/certificates` | 403 | 403 | 403 | **200** (0 rows) | 200 |
| `admin/dashboard` | 403 | 403 | 403 | 403 | 200 |
| `admin/admissions/registrations` | 403 | 403 | 403 | 403 | 200 |
| `admin/privacy-requests` | 403 | 403 | 403 | 403 | 200 |
| `admin/feature-flags` | 403 | 403 | 403 | 403 | 200 |
| `rbac/grants` | 403 | 403 | 403 | 403 | 200 |
| `audit/events` | 403 | 403 | 403 | 403 | 200 |
| `finance/orders` | 403 | 403 | 403 | 403 | 200 |
| `finance/reports/revenue` | 403 | 403 | 403 | 403 | 200 |
| `studio/questions` | 403 | 200 (spec: `question.create`, trainers author tests) | 403 | 200 | **403** (F-5) |
| `studio/courses` | 403 | 200 (0 rows) | 403 | 200 | 200 |
| `security/cases` | 403 | 403 | 403 | 403 | 200 |
| `support/queue` | 403 | 403 | 403 | 200 (spec SUP-07: content managers see content tickets) | 200 |
| `mentor/students` | 403 | **200** (0 rows) | 403 | 403 | 200 |
| `batches` | 403 | 200 (own batch) | 403 | 403 | 200 |

**No critical finding.** The student received 403 on all 16 endpoints, and the admin baseline proves those endpoints exist and return data. The bold 200s for staff roles return no rows today; they are listed in F-15 for a check against the role matrix.

## 5. catalog.json CORS: what it powers and how it degrades

- **What it powers:**
  - The dashboard card "Courses from Tech Drona" (`SiteCourseStrip`, `apps/lms-spa/src/app/app/page.tsx:10`).
  - `/app/courses` (`SiteCourseSections`).
  - The public `/register` pages and the admin course cards.
- **Code path:** `fetchSiteCatalog` (`features/site-catalog/lib/catalog.ts:352-384`) fetches three sources in parallel:
  1. `${SITE}/catalog.json`, for rich card data: kicker, tagline, theme colours, tech, facts, images and the featured flag.
  2. Firestore REST `web_course_public`, for the live state: title, status and dates.
  3. `/api/v1/public/courses/status`, for the LMS registration status.
- **Why it fails:** the code was written for a Next server, where `server-only` loaded it server-side. In the SPA it runs in the browser. On live, the website serves `catalog.json` with `200 application/json` and **no `Access-Control-Allow-Origin`**, so the browser blocks it.
- **How it degrades:** the error is caught (`.catch(() => null)` at `catalog.ts:361`), and the cards are built from sources 2 and 3 only (`minimalCourse`, `catalog.ts:219`). So the 8 courses still appear, but they lose:
  - their tagline, facts, tech chips and images;
  - their theme accent, so every card uses the default theme and the generic "Course" kicker;
  - their featured ordering.

  The page still works, but the cards look bare and the console shows an error on every dashboard and Explore-courses load.
- **Fix:**
  - **Preferred:** add `Access-Control-Allow-Origin: https://techdrona-lms-app.web.app` (and the future `lms.<domain>`) for `/catalog.json` in the **website's** Firebase Hosting `headers`.
  - **Alternative:** serve it through a same-origin LMS Hosting rewrite or API proxy (e.g. `/api/v1/public/site-catalog`), which also lets it be cached.

## 6. Findings

| # | Sev | Finding | Evidence | Likely source | Recommended fix |
|---|---|---|---|---|---|
| F-1 | Medium | catalog.json is blocked by CORS on every dashboard and Explore-courses load. Cards fall back to minimal data (see §5) | Console error on `/app` and `/app/courses`; `catalog.json` returns 200 with no ACAO header | `apps/lms-spa/src/features/site-catalog/lib/catalog.ts:359` (browser fetch in the SPA) | Add a CORS header on the website Hosting, or add a same-origin proxy |
| F-2 | Medium | **Dead-end upsell.** Mock interviews says "come with a placement package… See plans" → `/app/billing`, which has no plans, only empty Orders/Invoices tabs | `/app/mentoring` links | `features/mentor/student/Mentoring.tsx:19`; nav `lib/nav/portals.ts:136` | Hide Mock interviews (nav, dashboard Quick actions `StudentDashboard.tsx:197`, Interview prep hub) until a package is on sale, or link "See plans" to a real pricing page |
| F-3 | Medium | "Browse free courses" (My learning and the dashboard "Continue learning" card) opens Explore courses, which has 0 free or self-paced courses, only 8 "Coming soon" website courses | `/app/learning`, dashboard | `features/learning/components/MyCourses.tsx:25`, `features/dashboard/components/StudentDashboard.tsx:169` | With 0 LMS courses, change the copy to "See upcoming courses" or "Register for a batch"; or hide the CTA when the catalogue has no self-paced courses |
| F-4 | Medium | The dashboard course strip says "Explore upcoming courses and **join a waitlist**", but each card links out to the website (`target=_blank`) and nothing offers a waitlist. Cards also repeat "Coming soon" twice (pill and disabled label). On phone the course-title links are small tap targets (≈ 74×19 px) | Desktop screenshot of `/app`; phone layout check | `features/site-catalog/components/SiteCourseStrip.tsx:29`, `SiteCourseCard.tsx:65-72` | Fix the copy (no waitlist exists). Keep students in the LMS: link to `/app/courses#<slug>` or an in-app overview. Drop the duplicate label. Enlarge the tap area |
| F-5 | Medium | **Admin can open the Content studio, but its APIs refuse admin.** `/studio` and `/studio/questions` render with `403 GET studio/questions` and `403 studio/question-reports`, which shows as error states | Access matrix, admin row; API probe: admin `studio/questions` 403 | `features/staff-portal/access.ts:24` (super admin may enter every staff portal) vs API `question.create` (spec PLC-04) | Either give super_admin read access to `studio/questions` and `studio/question-reports`, or stop letting admin enter `/studio` (the Admin nav already has "Question review"). Make the UI gate and the API agree |
| F-6 | Low | Explore courses and My registrations are two nav items for one journey (browse → register → pay → verify). Explore courses already links to My registrations | Nav pages 4–5 | `lib/nav/portals.ts:124-125` | Keep one "Courses" item with tabs (Browse / My registrations), or show My registrations only once the student has one |
| F-7 | Low | 23 nav items for an account with nothing in it. Several have no backing data or module yet: Company paths ("coming soon"), My paths, Free diagnostic, Billing and My access (commerce unused; payments go through Admissions/UPI), Mock interviews | Nav pages 6, 14, 18, 20, 21, 16 | `lib/nav/portals.ts:119-143` | See §7. Hide items until their module has content (a feature flag, or the existing `appKey` mechanism), and merge duplicates. Target about 12 items |
| F-8 | Low | Practice shows an empty Subject dropdown and a disabled "Start" button with no explanation (Onboarding does say "No practice subjects published yet") | `/app/practice` | `features/practice/components/PracticeHub.tsx:44-95` (TopicPicker, `disabled={!subjectId}`) | When `subjects` is empty, show an EmptyState instead of the form |
| F-9 | Low | Coding says "No problems match these filters / Try a different difficulty or status" when no problems exist and no filter is set | `/app/coding` | `features/coding/components/ProblemList.tsx:85` | Use a separate empty state when no filters are applied: "No coding problems published yet" |
| F-10 | Low | Duplicate entry points: Notifications (sidebar plus header bell) and Profile & settings (sidebar plus account menu "Settings") | Shell chrome | `lib/nav/portals.ts:139,143` | Drop both from the sidebar; the header covers them on desktop and phone |
| F-11 | Low | `/app/orders` (no id) renders a blank page with no heading or text. No index route exists; only `/app/orders/:order_id` does | `mainLen 0` | `apps/lms-spa/src/spa/routes.gen.tsx:620-628` | Add an index redirect to `/app/billing`, or let it fall to not-found |
| F-12 | Info (QA tooling) | A new browser sign-in revokes the account's oldest sessions (account limit "Signed-in devices at once: 2"). Two UI sign-ins plus the global-setup session logged out every other test in run 5f3a1867, and they also break other audit builds that share the QA accounts | Run 5f3a1867: every probe returned 401, and pages bounced to `/login` mid-run | `qa/live-e2e/tests/audit-student.spec.ts` (post-login test) | The spec now has a separate `post-login` test, to run alone (`--grep post-login`, desktop) and never while other builds run. Page tests re-sign-in through the API when bounced (`visit()`) |
| F-13 | Low | The evaluator's Integrity flags page calls `GET batches/{id}`, which returns 403 (needs `org.member.read` @B) | Matrix, evaluator `/evaluator/integrity` | `features/trainer/components/Integrity.tsx` (shared with trainer); spec ORG-22 | Grant evaluators batch read for their batch, or skip the batch lookup in evaluator mode |
| F-14 | Low (UX) | Wrong-portal redirects are silent. A student opening a shared `/admin/...` link lands on the dashboard with no explanation | Matrix | `features/staff-portal/StaffPortalGate.tsx` (`ClientRedirect`) | Optional: a one-line toast or notice "That page is for staff; you're in the Student portal" |
| F-15 | Info | Staff APIs returning 200 to staff roles that should be checked against the role matrix (all return 0 rows today): content → `admin/certificates`; trainer → `mentor/students`. Trainer → `studio/questions` and content → `support/queue` are documented (PLC-04, SUP-07) | §4 | API routers for certificates and mentor | Confirm intent. If unintended, tighten before real data exists |
| F-16 | Info | Phone `/app/settings/profile`: "Save changes" sits under the fixed tab bar until the user scrolls. Main has `pb-24`, so it clears at the end of the scroll. This is a full-page-screenshot effect, not a blocker | Phone screenshot | `components/shell/PortalFrame.tsx` (`pb-24`) | None needed. Optionally scroll the focused form actions into view |

## 7. Irrelevant / misplaced items (student)

**Hide until the backing module has data:**
- **Company paths** (`/app/companies`): the page itself says "coming soon". Remove it from the nav and from the Interview prep hub.
- **Mock interviews** (`/app/mentoring`): sold only with a placement package that does not exist, and "See plans" is a dead end (F-2). Also remove it from the dashboard Quick actions and the Interview prep hub.
- **Billing** (`/app/billing`) and **My access** (`/app/access`): no commerce orders exist, and course payments go through Admissions (My registrations). Merge them into one "Purchases & access" page. Show it only when the student has an order or grant, or move it under Settings.
- **My paths** (`/app/path/my`): no learning paths exist. Hide it while there are none, through the existing `paths` `appKey`, or show it only when one is assigned.
- **Free diagnostic** (`/app/diagnostic`): no diagnostic test is published. Fold it into Tests, as a filter or tab.

**Duplicates:**
- **Explore courses** and **My registrations**: one "Courses" item with tabs (F-6).
- **Interview prep**: it is a hub over Mock interviews, Résumé, Company paths and Tests, so keep either the hub or its children in the nav, not both. Recommendation: keep "Interview prep" plus "Résumé builder".
- **Notifications** (the bell already covers it) and **Profile & settings** (the account menu already covers it): remove both from the sidebar (F-10).

**Links that leave the LMS:**
- Course cards on the dashboard and Explore courses → `techdrona-website.web.app/courses/<slug>` (opens in a new tab). Students should stay in the LMS (F-4).
- "Tech Drona website" in the account menu and sidebar footer is fine.

**Staff features:** none leak into the student UI. "Find a page" for "admin" finds nothing, and every staff URL redirects to `/app`.

**Suggested student nav (about 13 items):**
- Dashboard
- **Learn:** My learning, My classes, Courses (browse and registrations), Assignments, Live activities, Certificates
- **Practice & tests:** Practice, Tests (incl. diagnostic), Coding, Progress
- **Placement:** Interview prep, Résumé builder
- **Account:** Support

Restore the hidden items automatically when their module has content.
