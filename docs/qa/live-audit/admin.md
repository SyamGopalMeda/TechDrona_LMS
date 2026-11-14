# Admin portal: live audit (2026-11-14)

- **Site:** https://techdrona-lms-app.web.app (live), signed in as the QA `super_admin` (platform scope).
- **How:** Playwright on Cloud Build. Navigation and reading only: no form was submitted. Tabs were clicked, and menus and switchers were opened.
- **Spec:** `qa/live-e2e/tests/audit-admin.spec.ts`. Re-run:
  ```
  bash qa/live-e2e/run.sh tests/audit-admin.spec.ts --roles=admin --projects=desktop --shots
  bash qa/live-e2e/run.sh tests/audit-admin.spec.ts --roles=admin --projects=tablet --shots
  ```
- **Runs:**
  - `7164df8f-1334-4ed9-83ba-204f73956bba`: desktop, complete. This is the source of every page status below.
  - `9fbdd251-ce2c-4337-86f7-05562d5740a4`: desktop and tablet. The session was evicted at about 06:14:40 UTC (see finding 14). Its tablet data covers only the pages before that time.
  - Findings JSON: `qa/live-e2e/runs/<id>/findings/`.
  - Screenshots: `gs://td-qa-reports-f4fe3/runs/<id>/artifacts/`. A few are downloaded to `qa/live-e2e/runs/<id>/shots/`.

**Context used for the "relevant or not" calls:**
- Tech Drona trains students in batches. The website takes admissions, and fees are paid by manual UPI and verified in the LMS.
- The dashboard Integrations card says 7 of 7 outside services are **not integrated**: email, SMS, online payments, AI, code runner, video hosting and website SSO.
- `TD_SIMPLE_AUTH` is permanent: no MFA, no step-up and no dual control for role grants.
- The LMS currently has 0 courses, 8 batches (website imports) and only QA or owner accounts.

---

## 1. Every Admin nav item and page

Status: **OK** means it loaded with no failed API call. **Issue** points to the numbered findings in section 2. **Misplaced** points to section 3.

| # | Sidebar section / label | URL | Purpose | Live status |
|---|---|---|---|---|
| 1 | Overview / Dashboard | `/admin` | KPIs, attention list, courses, quick actions, integrations | Loads. Issues: F1, F4, F6, F9. Misplaced: M1, M2 |
| 2 | Overview / Approvals | `/admin/approvals` | Dual-control queue (all types) | OK, empty. Duplicate: F10 |
| 3 | People / Users | `/admin/users` (+ `/admin/users/:id`) | Find and manage accounts | OK (10 rows; detail OK) |
| 4 | People / Role grants | `/admin/roles` | Grant or revoke roles | OK (9 grants). Copy issue: F12 |
| 5 | People / Privacy requests | `/admin/privacy-requests` | DPDP rights queue | OK, empty |
| 6 | Colleges / Colleges Data | `/college-portal/index.html` | College outreach app | **Broken: "Page not found"** (F1) |
| 7 | Website / Website Admin Panel | `https://techdrona-website.web.app/admin` | Website back office | Lands on the website **sign-in** ("Welcome back"); SSO not integrated (F5) |
| 8 | Learning / Courses | `/admin/courses` | Course overview + website catalogue | Loads. CORS console error (F7). "Content studio" button goes to another portal (F4) |
| 9 | Learning / Question review | `/admin/question-review` | Review questions sent by content managers | OK, empty. Misplaced: M3 |
| 10 | Learning / Batches | `/admin/batches` (+ detail) | Batches, members, trainers, plan, classes | OK (8 rows). All 3 detail tabs OK |
| 11 | Learning / Certificates & documents | `/admin/certificates` | Certificates, letters, templates | OK. All 8 tabs OK (0 issued) |
| 12 | Mentoring / Mentor sessions | `/mentor` | The admin's own mentor sessions | OK, empty. Misplaced: M4 |
| 13 | Mentoring / Mentees | `/mentor/students` | Students the admin mentors | OK, empty ("No students assigned yet"). M4 |
| 14 | Mentoring / Mentor availability | `/mentor/slots` | Publish bookable mock-interview slots | OK, empty. M4 |
| 15 | Mentoring / Résumé reviews | `/mentor/resume-reviews` | Review student résumés | OK, empty. M4 |
| 16 | Payments / Revenue | `/finance` | Gateway sales, refunds, reconciliation | Loads. The page itself says "Online payment gateway: not integrated yet … simulated and stay empty" (M5) |
| 17 | Payments / Admissions | `/finance/admissions` | Open or close course registration | Loads (8 courses, "No fee set"). CORS console error (F7) |
| 18 | Payments / Verify payments | `/finance/admissions/verify` | Verify UPI receipts and enrol | OK, empty |
| 19 | Payments / Registrations | `/finance/admissions/registrations` | Website registrations | OK, empty |
| 20 | Payments / Fee plans | `/finance/admissions/plans` | Fees, instalments, UPI details | Loads, no plans yet. CORS console error (F7) |
| 21 | Payments / Orders | `/finance/orders` | Gateway orders | OK, empty. M5 |
| 22 | Payments / Refunds | `/finance/refunds` | Gateway refunds | OK, empty. M5 |
| 23 | Payments / Subscriptions | `/finance/subscriptions` | UPI AutoPay subscriptions | OK, empty. M5 |
| 24 | Payments / Invoices | `/finance/invoices` | GST invoices, credit notes, GST export | OK, empty. M5 |
| 25 | Payments / Products & prices | `/finance/products` | Checkout product catalogue | OK, empty. M5 |
| 26 | Payments / Coupons | `/finance/coupons` | Checkout coupons | OK, empty. M5 |
| 27 | Payments / Reconciliation | `/finance/reconciliation` | Gateway settlement matching | Loads with 30 rows of hourly "Razorpay 0 orders · 0 payments" runs (F11). M5 |
| 28 | Support / Ticket queue | `/desk` | Learner support tickets | OK, empty |
| 29 | Support / Unblock requests | `/desk/unblock-requests` | L1/L2 unblock triage | OK, empty. Duplicate: F10, M6 |
| 30 | Support / Corporate enquiries | `/desk/enquiries` | Public `/enquiries` form submissions | OK, empty. `/enquiries` now redirects to the website contact page, so nothing feeds it (M7) |
| 31 | Security / Security overview | `/security` | Risk engine state | OK. Engine is "Watching only (shadow)" with auto restrictions off (M6) |
| 32 | Security / Cases | `/security/cases` | Suspicious-activity cases | OK, empty. M6 |
| 33 | Security / Incidents | `/security/incidents` | CERT-In / DPB breach log | OK, empty. Keep (legal) |
| 34 | Security / Restrictions | `/security/restrictions` | Account restrictions | OK, empty. M6 |
| 35 | Security / Unblock reviews | `/security/unblock-requests` | L3/L4 unblock appeals | OK, empty. Duplicate: F10, M6 |
| 36 | Security / Risk rules | `/security/rules` | Risk rule versions | OK, empty. M6 |
| 37 | Security / Reports | `/security/reports` (+ report) | Security reports | OK. Report detail OK (3 rows) |
| 38 | Settings / Audit log | `/admin/audit` | Tamper-evident audit log | OK (50 rows, chain verified) |
| 39 | Settings / Policies | `/admin/policies` | Policy settings (all namespaces) | OK. 6 tabs OK. Duplicate of `/security/policies` (F10) |
| 40 | Settings / AI & apps | `/admin/ai` | AI caps, authorized apps, usage | OK (3 tabs). Provider shows "Fake"; AI is not integrated (M8) |
| 41 | Settings / Feature flags | `/admin/feature-flags` | 4 flags | OK. M9 |
| 42 | Settings / Break-glass | `/admin/break-glass` | Emergency elevation history | OK, empty ("New ones can't be started"). M9 |

**Reachable but not in the nav**

| URL | Reached from | Live status |
|---|---|---|
| `/admin/college-data` | Old route, hub `last-page` | Shell loads, but the iframe is blocked: console `Framing 'https://techdrona-lms-app.web.app/' violates … "frame-ancestors 'none'"`. "Open full screen" goes to the 404 page (F1) |
| `/admin/notifications` | Direct URL only | Placeholder "Templates can't be edited here yet" (M10) |
| `/security/approvals` | Links on the security pages | OK; a filtered copy of `/admin/approvals` (F10) |
| `/security/policies` | Links on the security pages | OK; a filtered copy of `/admin/policies` (F10) |
| `/modules` | Modules menu > All modules | OK. Its Colleges card goes to the 404 page (F1) |
| `/app/settings/profile` | Account menu > Settings | OK, in the Admin shell. The URL is a student `/app` URL, and the form asks for "Graduation year" and "Branch" (F8) |
| `/app/account-status` | Direct URL | Opens in the Admin shell with student wording: "Videos playing at once", "Go to my dashboard" (F8) |
| `/app`, `/app/learning` | Direct URL | Redirect to `/admin` (correct) |
| `/studio`, `/studio/courses`, `/studio/review` | Dashboard "Active courses" tile, Quick action "Courses", `/admin/courses` buttons | Load, but in the **Content studio** portal (nav switches, no way back except the logo or the browser) (F4) |
| `/studio/taxonomy`, `/studio/questions`, `/studio/reports/errors`, `/studio/coding`, and the `/studio` dashboard widgets | Studio nav, once the admin is in Studio | **403** (F2) |
| `/trainer` | Dashboard "Your Teacher Portal" (disabled until self-assigned) | Loads the Trainer portal ("You haven't been assigned a batch yet") (M2) |

**Shell inventory (desktop)**

- **Sidebar:** 42 links in 10 sections: Overview 2, People 3, Colleges 1, Website 1, Learning 4, Mentoring 4, Payments 12, Support 3, Security 7, Settings 5.
- **Header:** Modules menu, account menu. The portal switcher is **not shown**, because `me/grants.portals` lists only `/admin` for this account.
- **Account menu:**
  - Settings → `/app/settings/profile`
  - Tech Drona website
  - Sign out
- **Modules menu:**
  - Tech Drona LMS → `/admin`
  - Colleges Management → `/college-portal/index.html` (404)
  - All modules → `/modules`
- **Find a page (Ctrl K):** Ctrl K focuses the box. It searches only the Admin nav. "learn", "practice", "student", "my" and "test" return no student pages. "unblock" returns 2 near-identical items: "Unblock requests" and "Unblock reviews".
- **Dashboard links:** Users ×5, `/finance/orders` ×3, `/finance` ×3, `/studio/courses` ×2, `/college-portal/index.html` ×2, `/admin/batches` ×3, `/admin/approvals` ×3, `/desk`, `/security`, `/security/cases`, `/admin/privacy-requests`, `/admin/certificates` ×2, `/admin/audit`.
- **Tablet (iPad):** the "Menu · Dashboard" sheet lists all 10 sections, collapsed. It works, but 42 items behind 10 accordions is a lot for a phone or tablet (M-summary).

---

## 2. Findings

Severity: **High** = broken for the admin; **Medium** = wrong or confusing, with a workaround; **Low** = polish.

1. **High: Colleges module is a dead link everywhere.**
   - **URLs:** `/college-portal/index.html` shows the SPA "Page not found". `/admin/college-data` iframe is blocked by `frame-ancestors 'none'` (console error).
   - **Entry points:** sidebar "Colleges Data", dashboard hero button, Quick action, Modules menu "Colleges Management", `/modules` card, `/admin/college-data` "Open full screen".
   - **Evidence:** `runs/7164df8f…/shots/desktop-college_portal_index_html.png`. `firebase.json` hosting target `lms` has no rewrite or static files for `/college-portal/**`, so the catch-all `** → /index.html` applies. Only headers are defined (`firebase.json:322-339`).
   - **Source:** `apps/lms-spa/src/lib/nav/portals.ts:71`; `features/admin/components/Governance.tsx:665, 718`; `features/college-data/CollegeDataPortal.tsx:7`; the hub module list (`apps/api/app/modules/hub`).
   - **Fix:** deploy the college portal on Firebase Hosting (static files under `dist/college-portal/` or a function rewrite), or hide the nav entry, dashboard buttons and Modules entry until it is deployed.

2. **High: Studio pages give 403 to the admin, yet the admin is sent there.**
   - **Failing calls on live:**
     - `/studio/taxonomy`: `403 GET studio/topics`
     - `/studio/questions`: `403 GET studio/questions?offset=0&limit=25`
     - `/studio/reports/errors`: `403 GET studio/question-reports?status=open|resolved`
     - `/studio/coding`: `403 GET studio/coding/problems?limit=100`
     - `/studio` dashboard: `403 GET studio/question-reports?status=open&limit=1` and `403 GET studio/questions?status=draft&limit=200`
   - **Shown to the admin:** "You don't have permission to do this", with a "New subject or topic" button still enabled. Screenshot: `runs/7164df8f…/shots/desktop-studio_taxonomy.png`.
   - **Cause:** `canEnterPortal` lets a super admin into every staff portal (`features/staff-portal/access.ts`), but the API grants admin only `question.review` and `question.publish`, not studio read.
   - **Fix:** either stop routing the admin into `/studio` (see F4), or block `/studio/*` for admin in `canEnterPortal` except `/studio/courses` and `/studio/review`. Alternatively, grant admin read-only studio permissions in RBAC (`apps/api/app/modules/rbac`). Hide create buttons when the list call returns 403.

3. **Medium: No portal switcher for the admin, although the admin is sent to Studio and Trainer.**
   - **Evidence:** the header has no "Switch portal" menu, because `GET me/grants` → `portals` holds only `/admin` (shell inventory, `findings/audit-admin-desktop-shell.json`). Yet dashboard links lead to `/studio/*` and `/trainer`. Once there, the sidebar is the Studio or Trainer nav, and the only way back is the logo (which goes to `/studio` or `/trainer`, not `/admin`) or the Modules menu "Tech Drona LMS".
   - **Source:** `components/shell/PortalSwitcher.tsx:25-35`, `components/shell/PortalShell.tsx:33-34`.
   - **Fix:** for an admin, list Admin, Studio and Teacher in the switcher (using `reachablePortals` with the admin rule from `canEnterPortal`), or always show a "Back to Admin" link in non-admin shells for admins.

4. **Medium: Admin links jump into the Content studio portal without saying so.**
   - **Links:**
     - Dashboard tile "Active courses" → `/studio/courses` (`Governance.tsx:688`)
     - Quick action "Courses: Author and publish courses" → `/studio/courses` (`Governance.tsx:720`)
     - `/admin/courses` "Content studio" button (`CourseCards.tsx:283`)
     - Empty-state "Open the content studio" (`CourseCards.tsx:240`)
     - Course card "Edit" (`studioCourseHref`, `CourseCards.tsx:107`)
   - **Effect:** the whole sidebar switches to Studio nav, the badge changes to "Content studio portal", and there is no Admin link back except the logo.
   - **Fix:** point the "Active courses" tile and the Quick action to `/admin/courses`. Label the remaining studio links "Open Content studio ↗". Better: keep the Admin shell (add a "Back to Admin" link) when an admin is in `/studio`.

5. **Medium: "Website Admin Panel" opens the website sign-in page.**
   - **Where:** `https://techdrona-website.web.app/admin` shows "Back office | Tech Drona / Welcome back" (a login form).
   - **Cause:** website SSO is "Not integrated yet" (dashboard Integrations card).
   - **Source:** `portals.ts:73`.
   - **Fix:** label it "Website admin ↗ (separate sign-in)" until SSO works, or route it through `/sso/website` once the service account exists.

6. **Medium: The dashboard shows an Integrations card listing 7 "Not integrated yet" services.**
   - **Problem:** this is engineering status, not daily admin work. It also includes items with no product use today (Code runner, Video hosting, AI features).
   - **Source:** `Governance.tsx` `IntegrationsCard` (around line 566), rendered at about line 729.
   - **Fix:** move it to Settings (a "System status" panel), or show it only while something the admin uses is affected (email, payments).

7. **Low: Console CORS error on 3 pages.**
   - **Error:** `Access to fetch at 'https://techdrona-website.web.app/catalog.json' … blocked by CORS policy`.
   - **Pages:** `/admin/courses`, `/finance/admissions`, `/finance/admissions/plans`. They fall back to live status, so the content still shows.
   - **Source:** `apps/lms-spa/src/features/site-catalog/lib/catalog.ts`.
   - **Fix:** add `Access-Control-Allow-Origin: https://techdrona-lms-app.web.app` (and the future `lms.<domain>`) to `catalog.json` in the website hosting headers, or proxy it through the LMS API.

8. **Medium: Account menu "Settings" goes to a student URL, and the profile form is student-shaped.**
   - **Where:** `/app/settings/profile` (in the Admin shell) asks staff for "Graduation year" and "Branch (CSE, ECE…)". `/app/account-status` says "Videos playing at once", "Go to my dashboard" (→ `/app`) and "Contact support" → `/app/support/new`. That support link is a student page, which redirects the admin back to `/admin`.
   - **Source:** `components/shell/PortalShell.tsx:39-44`; `features/staff-portal/access.ts` `SHARED_ACCOUNT_PREFIXES`.
   - **Fix:** use a neutral `/account/settings` route, or keep `/app/settings` but hide student-only fields (graduation year, branch, playback limits) for staff.

9. **Low: Dashboard "Students" and "New registrations" count QA accounts.**
   - **Values:** "New registrations 4 (Last 30 days)" and "Signed in now 16". The QA accounts are not marked synthetic, so they appear as real numbers.
   - **Source:** `apps/api/app/modules/admin/accounts.py:158-181`.
   - **Fix:** mark `qa-*@qa.techdrona.test` as `is_synthetic`.

10. **Medium: Duplicate entries and near-duplicate labels.**
    - **Approvals:** `/admin/approvals` (nav) and `/security/approvals` (a filtered copy, reached from security pages). With `TD_SIMPLE_AUTH`, role grants need no second admin. Both queues are empty, and most of the 15 approval types cannot occur.
    - **Policies:** `/admin/policies` (nav) and `/security/policies` (filtered copy).
    - **Unblock:** "Unblock requests" (Support, `/desk/unblock-requests`) and "Unblock reviews" (Security, `/security/unblock-requests`). Same people, different levels; Find a page shows both for "unblock".
    - **Question review:** `/admin/question-review` and Studio "Review queue" (`/studio/review`) show the same `studio/questions?version_status=awaiting_review` list.
    - **Source:** `portals.ts:66, 75, 96, 102, 106`.
    - **Fix:** one Unblock item (tabs for L1-L2 and L3-L4). Keep Approvals only while there is anything dual-controlled. Drop the `/security/approvals` and `/security/policies` copies or redirect them to the main pages with a filter.

11. **Low: Reconciliation runs every hour against a gateway that is not connected.**
    - **Evidence:** `/finance/reconciliation` lists 30 rows "Razorpay · 0 orders · 0 payments · Completed" (hourly), even though the page says the gateway is not integrated.
    - **Source:** `apps/api/app/modules/commerce/tasks.py` (scheduled reconciliation).
    - **Fix:** skip the scheduled run while the gateway is not configured.

12. **Low: Copy that contradicts simple-auth mode.**
    - `/admin/roles`: "Admin roles need a second admin to approve" (`Governance.tsx:153`).
    - `/admin/approvals`: "Approving asks you to confirm again".
    - With `TD_SIMPLE_AUTH=true` (permanent), grants are instant and there is no step-up.
    - **Fix:** make this copy depend on the auth mode.

13. **Low: Dashboard "Your Teacher Portal" card shows a disabled "Be a Teacher" button for every admin.**
    - **Source:** `Governance.tsx:611-645`. See M2.

14. **Medium (operational): Admin sessions are evicted when the same account signs in elsewhere.**
    - **Evidence:** in run `9fbdd251` every page after about 06:14:40 redirected to `/login?next=…` (`401 GET me/grants`). At the same time another agent's audit started and signed in the same QA admin (`gcloud builds list`: responsive-admin build `25c9811a` at 06:13:20).
    - **Cause:** `apps/api/app/modules/sessions/login.py:311-322` evicts the oldest session above `sessions.staff.max_concurrent`.
    - **Impact on real admins:** an admin signed in on a laptop and a phone can be logged out silently mid-task.
    - **Fix:** run QA admin builds one at a time, or give each runner its own admin account. For owners, raise `sessions.staff.max_concurrent` or show "You were signed out because you signed in on another device".

15. **Low (UI, desktop or tablet): small tap targets and sidebar overlap.**
    - **Tap targets:** tablet `layoutIssues` flags the "Go to Batches" text link (93×17) on the dashboard, course and user name links (about 19px tall) in tables, and the 10px "Ctrl K" hint.
    - **Overlap:** the desktop probe reports sidebar items overlapping the "Tech Drona website" and "Sign out" footer on long sections (Payments 12, Security 7). This is likely scroll-clipped. The responsive agent should confirm.
    - **Note:** the dashboard KPI cards hang below the navy hero, which looks intentional.

---

## 3. Irrelevant / misplaced items

The Admin portal does not show raw student pages (no "My learning", "Practice" or "Tests" in the nav or Find a page; `/app/*` learner URLs redirect to `/admin`). The clutter comes instead from **folded-in role portals** (mentor, gateway finance, risk engine) and **features with no backing integration or data**. Recommendations:

| # | Item (URL) | Why it is misplaced or irrelevant | Recommendation |
|---|---|---|---|
| M1 | Dashboard **Quick action "Courses: Author and publish courses"** and the **"Active courses" tile** → `/studio/courses` | Authoring is the Content studio's job; the admin gets 403s there (F2) | Point to `/admin/courses`; leave authoring links to Studio |
| M2 | Dashboard **"Your Teacher Portal" / "Be a Teacher"** card | Teaching is a Trainer job. It is always disabled for admins who don't teach, and takes prime dashboard space | Show it only when the admin holds a trainer grant (render nothing otherwise); or move it to the Portal switcher / account menu as "Teacher portal" |
| M3 | **Learning › Question review** (`/admin/question-review`) | Studio content workflow, the same list as Studio "Review queue". There are no questions (0 courses, Studio questions 403) | Hide from Admin nav while the question bank is unused; reviewing belongs to Studio |
| M4 | **Mentoring** section: Mentor sessions, Mentees, Mentor availability, Résumé reviews (`/mentor/*`) | These are a *placement mentor's* personal tools (publish slots, owe feedback, review résumés). They pair with the student pages "Mock interviews" and "Résumé builder". All empty; mentoring is not part of the batch-training workflow; the admin is not a mentor | Remove from the Admin nav. If mentoring is offered later, give it to trainers (Trainer portal "Mentoring" section) behind an app toggle |
| M5 | **Payments › Revenue, Orders, Refunds, Subscriptions, Invoices, Products & prices, Coupons, Reconciliation** (8 of 12 Payments items) | All are online-checkout (Razorpay) features. The pages themselves say the gateway is "not integrated yet … simulated and stay empty". Fees are collected by manual UPI under Admissions. Subscriptions (UPI AutoPay), Coupons and Products have no data and no use in the admissions flow | Collapse Payments to **Admissions, Verify payments, Registrations, Fee plans**. Hide the 8 gateway pages behind a "gateway connected" check (the `integrations` flag already exists) |
| M6 | **Security**: Cases, Restrictions, Unblock reviews, Risk rules, Reports, Security overview, plus **Support › Unblock requests** | Risk-engine tooling for an account-sharing detector that runs "Watching only (shadow)" with automatic restrictions **off**; account protection is off in this testing phase. All queues are empty. It also duplicates Unblock across two sections (F10) | Keep one **Account security** page (overview, with restrictions and unblock tabs). Hide Risk rules and Reports until the engine is switched on. Keep **Incidents** (legal CERT-In / DPB clock) under Settings |
| M7 | **Support › Corporate enquiries** (`/desk/enquiries`) | Fed by the LMS public `/enquiries` form, which now redirects to the website contact page (`firebase.json` lms redirects). Website enquiries are managed in the Website Admin, so this queue will stay empty | Remove from the nav, or relabel "Old LMS enquiries" until it is emptied |
| M8 | **Settings › AI & apps** (`/admin/ai`) | AI is "Not integrated yet", the provider shows "Fake", and the caps refer to learner tutor and AI drafts that do not exist. The "Authorized apps" tab (assignments, assessments, question banks, engage, paths) does toggle the *student and trainer* nav | Rename to "Apps" and keep only the Authorized apps tab; hide AI settings and Usage until a provider is configured |
| M9 | **Settings › Feature flags** and **Break-glass** | Engineering or ops tools: 4 flags (Cashfree, maintenance, fingerprint, certificate auto-send); break-glass "New ones can't be started" and the list is empty | Move "Certificate auto-send" into Certificates › Settings; hide Feature flags and Break-glass behind an "Advanced" group or remove them from the nav |
| M10 | `/admin/notifications` (not in the nav) | Placeholder page with no function | Delete the route |
| M11 | **Dashboard Integrations card** | System status, not daily admin work (F6) | Move to Settings |
| M12 | **Dashboard "Sales, last 30 days"**, **"Payments" KPI** → `/finance/orders` | Counts gateway orders, always 0 because admissions fees are not orders | Replace with Admissions numbers: pending verifications and verified fees in 30 days (`admin/admissions/overview`) |
| M13 | Account menu **Settings** → `/app/settings/profile` (student URL, student fields) | Staff profile shouldn't ask for graduation year or branch (F8) | Staff-neutral account page |

**Net effect if applied:** the sidebar goes from 42 items in 10 sections to about 22 items:
- **Overview:** Dashboard, Approvals (only if needed)
- **People:** Users, Role grants, Privacy requests
- **Learning:** Courses, Batches, Certificates & documents
- **Admissions:** Admissions, Verify payments, Registrations, Fee plans
- **Support:** Tickets, Unblock
- **Security:** Account security, Incidents
- **Settings:** Audit log, Policies, Apps
- **Links:** Colleges Data (once deployed), Website Admin
