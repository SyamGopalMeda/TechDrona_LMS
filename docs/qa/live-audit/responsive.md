# Responsive UI/UX audit: live LMS (all roles, all device sizes)

- **Site:** https://techdrona-lms-app.web.app (live). Audit only: no source changes and no deploys. Nothing was submitted; only menus, drawers and dialogs were opened.
- **Date:** 2026-11-14
- **Runner:** Playwright on Cloud Build (`qa/live-e2e`), spec `qa/live-e2e/tests/audit-responsive.spec.ts`, probe `qa/live-e2e/lib/probe.ts`.
- **Devices:**

  | Project | Viewport | Browser |
  |---|---|---|
  | desktop | 1440×900 | Chromium |
  | laptop | 1280×720 | Chromium |
  | tablet | iPad gen 7, 810×1080 | Chromium, touch |
  | tablet-landscape | 1080×810 | Chromium, touch |
  | phone-android | Pixel 7, 412×839 | Chromium |
  | phone-iphone | iPhone 13, 390×664 | WebKit |
  | phone-small | iPhone SE, 320×568 | WebKit |

  Playwright's "iPhone SE" is the first-generation model (320×568). It is narrower than the 375×667 asked for, so every result holds at 375 too.
- **Coverage:** 109 URLs × 7 devices, about 760 page visits, plus one navigation-behaviour test per role and device.

  | Role | Pages |
  |---|---|
  | student | 24 (sidebar nav plus account status) |
  | admin | 43 (/admin, /finance, /desk, /security, /mentor, Colleges Data, settings, /modules) |
  | trainer | 9 |
  | evaluator | 3 |
  | studio (content manager) | 11 |
  | public (signed out) | 11: /login, /signup, /forgot-password, /help, /legal/×4, /verify, /modules, /courses |

## Runs used for this report

| Build | Scope |
|---|---|
| `c013c66a-5e7e-4c7e-adba-9964117fc93d` | admin; desktop, laptop, tablet, tablet-landscape |
| `c451de1d-2ed2-41b5-be86-17d84b17477d` | admin; three phones |
| `c455beae-7084-434a-ae50-e4192e41412f` | student; all devices |
| `7bc01930-d514-4207-b9fe-8e9f377d2284` | content, trainer, evaluator, public; all devices |
| `415e92ff-202e-4b91-a127-d33d8d3c135b` | public on iPhone 13 and iPhone SE (rerun after a WebKit crash, see T2) |

Findings JSON is under `qa/live-e2e/runs/<build>/findings/responsive-*.json`. Screenshots are under `qa/live-e2e/runs/<build>/artifacts/shots/<device>/<role>/<page>.jpg`; only a sample was downloaded, and the full set is in `gs://td-qa-reports-f4fe3/runs/<build>/`.

Two earlier builds (`25c9811a…`, `cb282ef5…`, `baddafa8…`, `155c9928…`) were thrown away. Their QA sessions were evicted part-way through (see T1), and they used the first version of the probe, which reported false positives.

## Summary matrix

The matrix counts layout issues after removing known probe noise: the decorative "Ctrl K" hint, inline text links (WCAG 2.5.8 inline exception), and content under the tab bar at scroll 0, which scrolls clear. Each cell shows **issues (pages affected)**; "OK" means no issue.

| Page group | desktop | laptop | tablet | tablet-landscape | phone-android | phone-iphone | phone-small |
|---|---|---|---|---|---|---|---|
| student (24p) | 5 (1p) | 5 (1p) | 22 (4p) | 21 (4p) | 22 (4p) | 22 (4p) | 20 (4p) |
| admin /admin (17p) | 5 (1p) | 5 (1p) | 24 (4p) | 23 (4p) | 16 (3p) | 16 (3p) | 14 (3p) |
| admin /finance (12p) | OK | OK | OK | OK | OK | OK | OK |
| admin /desk (3p) | OK | OK | OK | OK | OK | OK | OK |
| admin /security (7p) | OK | OK | 1 (1p) | 1 (1p) | 1 (1p) | 1 (1p) | 1 (1p) |
| admin /mentor (4p) | OK | OK | 1 (1p) | 1 (1p) | 1 (1p) | 1 (1p) | 1 (1p) |
| trainer (9p) | OK | OK | 1 (1p) | 1 (1p) | OK | OK | OK |
| evaluator (3p) | OK | OK | OK | OK | OK | OK | OK |
| studio (11p) | OK | OK | OK | OK | OK | OK | OK |
| public, LMS pages (10p) | OK | OK | 18 (8p) | 18 (8p) | 18 (8p) | 18 (8p) | 18 (8p) |
| /courses (redirects to the company website) | 11 | 11 | 14 | 19 | 14 | 14 | 16 |

Almost every remaining issue is a **small tap target or small text**. The audit found no hard layout breaks:

- **Horizontal scroll and overflow:** none in the LMS, on any page or device. No element sticks out of the viewport.
- **Tables:** no table is wider than the screen. Data tables become stacked cards on phones (for example `c451de1d…/artifacts/shots/phone-small/admin/admin_users.jpg`).
- **Overlap and hidden content:** no overlapping controls, and no content is hidden under the sticky header or the student tab bar (`pb-24` clears it).
- **Mobile navigation** works for every role on every touch device:

  | Check | Result |
  |---|---|
  | Collapsed nav | The staff "Menu · page" bar and the student bottom tab bar with its "More" sheet replace the sidebar below 1024 px. |
  | Reachability | Every nav item is reachable on a phone, including all 41 admin items after expanding sections. |
  | Closing | The panels close after navigation (one intermittent exception, F7). |
  | Tab bar | Shown only to students. |
  | Header menus | The account menu, module switcher and portal switcher open on tap and fit at 320 px. |
  | Search | Ctrl K focuses "Find a page" on desktop. On touch, the same field is in the staff Menu panel and works. |

- **Shell consistency:** all five portals render the same shell, with the same 57 px top bar, the same navy sidebar with a "<Portal> portal" mint badge, the same main padding (32/32 desktop, 24 tablet, 16/24 phone) and the same heading scale. Public pages share the website header (79 px).

## Findings

Findings are grouped by root cause. Severity: **High** = blocks a task, **Medium** = visible on many pages or hurts touch use, **Low** = polish, **Info** = no action needed.

### F1 (Medium): the page title is larger on phones than on desktop (inverted heading scale)
- **Devices:** all phones (30 px) compared with tablet, laptop and desktop (28 px). Every non-dashboard page in every portal: student, admin, trainer, evaluator and studio, about 100 pages.
- **What:** the shared page header's `<h1>` uses `text-2xl` below 640 px and `sm:text-[1.75rem]` above. In this design-token set `text-2xl` resolves to 30 px, so phones get a bigger title than desktop. Long titles ("Certificates & documents", "Unblock requests") wrap to two or three lines at 320 px. The dashboard hero h1 (`Dashboard.tsx:48`) scales correctly: 25.6 px on phone, 32 px on desktop.
- **Evidence:** `facts.h1.size` in every `responsive-*-phone-*.json`, for example `c451de1d…/findings/responsive-admin-phone-small-finance_orders.json`. Screenshot: `c451de1d…/artifacts/shots/phone-small/admin/finance_orders.jpg`.
- **Component:** `apps/lms-spa/src/components/ui/Display.tsx:719`.
- **Fix:** `text-[1.5rem] leading-8 sm:text-[1.75rem] sm:leading-9`. Alternatively, give the token scale a phone size at or below the `sm` size.

### F2 (Medium): course-card titles are text-only links (17–19 px tall) and the card kicker uses 10.9 px text
- **Devices:** tablet, tablet-landscape and all phones.
- **Pages:** /app (dashboard course strip), /app/courses, /admin/courses. The website's /courses has the same pattern.
- **What:** the only link on each catalogue card is the title text. Its tap target is about 19 px tall: "Agentic AI" 74×19, "AWS and DevOps" 127×19 and so on, below the 24 px minimum. The "COURSE" kicker pill uses `text-[0.68rem]` (10.9 px). On desktop this is the only issue on these pages (5 per page in the matrix).
- **Evidence:** `c455beae…/artifacts/shots/tablet/student/app_courses.jpg`, `c455beae…/artifacts/shots/phone-small/student/app_courses.jpg`, `c013c66a…/artifacts/shots/tablet/admin/admin_courses.jpg`.
- **Components:**
  - `apps/lms-spa/src/features/site-catalog/components/SiteCourseCard.tsx:167` (title link)
  - `SiteCourseCard.tsx:144-145` (kicker)
  - `apps/lms-spa/src/features/site-catalog/components/SiteCourseStrip.tsx:53` (strip title link)
- **Fix:** make the whole card the target. Add `relative` to the card and give the title `<a>` `after:absolute after:inset-0 after:content-['']`, keeping the "Course details" button above it with `relative z-[1]`. If that is not wanted, use `inline-flex min-h-6 items-center` (better: `py-2 -my-2`) on the title link. Raise the kicker to `text-[0.75rem]`.

### F3 (Low): standalone text links and `<summary>` toggles are under 24 px tall on touch
- **Devices:** tablet, tablet-landscape and all phones.
- **What:** links that sit on their own line (not inside running text) render about 17–20 px tall:

  | Page | Links |
  |---|---|
  | /login | "Forgot password?" |
  | /forgot-password | "Back to log in" |
  | /app/account-status | "Check a review request", "Contact support", "Privacy requests" |
  | /app/progress | "How we measure time" (`<summary>`), "Start practising" |
  | /app/courses | "My registrations" |
  | /mentor | "Open queue" |
  | /college-portal | "Browse courses", "Help centre" |
  | /legal/* | "Related" lists: "Grievance officer", "Privacy settings (sign-in needed)", "Billing (sign-in needed)", "Device policy", and others |

  These make up the counts in the "public (LMS)" row and most of the student and admin tablet/phone counts.
- **Evidence:** `415e92ff…/artifacts/shots/phone-small/public/login.jpg`, `415e92ff…/artifacts/shots/phone-small/public/legal_privacy.jpg`, `c455beae…/artifacts/shots/phone-small/student/app_account_status.jpg`.
- **Components:**
  - `apps/lms-spa/src/features/public/components/ContentDoc.tsx:19` (`linkCls` for legal pages; the same pattern is in `HelpCentre.tsx:5` and `FreeResources.tsx:14`)
  - `apps/lms-spa/src/features/auth/components/LoginForm.tsx:120`
  - `apps/lms-spa/src/features/auth/components/PasswordRecovery.tsx:89`
  - `apps/lms-spa/src/features/unblock/components/AccountStatus.tsx:119`
  - `apps/lms-spa/src/features/progress/components/ProgressDashboard.tsx:24`
- **Fix:** add a shared utility for standalone links, such as `.td-link-block { display:inline-flex; align-items:center; min-height:24px }` (44 px for primary actions), and apply it where a link is its own list item or paragraph. For list links, `py-1` on the `<a>` is enough.

### F4 (Low): checkboxes are 20×20 px
- **Devices:** touch devices.
- **Pages:** /login ("Keep me signed in"), /signup (terms), /admin/ai (app toggles), /security/restrictions (filters).
- **What:** the shared `Checkbox` input is `h-5 w-5` (20 px). Its `<label htmlFor>` extends the clickable area, so this is mild, but the box itself is under 24 px.
- **Component:** `apps/lms-spa/src/components/ui/Checkbox.tsx:19`.
- **Fix:** use `h-6 w-6` on coarse pointers (`pointer-coarse:h-6 pointer-coarse:w-6`, or a media query), or wrap the input and label in one `<label>` with `min-h-touch` and padding.

### F5 (Low): the student "More" sheet has no "Find a page" search
- **Devices:** tablet (portrait) and all phones, student only.
- **What:** the staff Menu panel on phones includes the searchable "Find a page" field, the touch equivalent of Ctrl K. The student "More" sheet, with 19 items in four sections, does not, because `searchable` is not passed. The behaviour differs between portals, and students have the longest phone menu after admin.
- **Evidence:** `c455beae…/artifacts/shots/phone-small/student/nav-more-sheet.jpg`; `moreSheet.search=false` in `c455beae…/findings/responsive-nav-student-phone-*.json`.
- **Component:** `apps/lms-spa/src/components/shell/MobileTabBar.tsx:164`.
- **Fix:** `<PortalNav items={sheetItems} label={label} root={root} searchable />`. The input is already hidden on desktop, and Ctrl K only targets the visible copy.

### F6 (Low): small text in decorative and secondary places
- **Hint and section labels:**
  - The "Ctrl K" `<kbd>` hint in the desktop sidebar is 10 px (`PortalNav.tsx:227`). It is decorative and `aria-hidden`, but low-contrast `text-white/45` at 10 px is hard to read. Use `text-[11px]`.
  - Sidebar section labels are 11 px uppercase (`PortalNav.tsx:268`). This matches the website and is acceptable.
- **Catalogue kicker:** 10.9 px; see F2.

### F7 (Low, intermittent): staff "Menu" panel occasionally still open after navigating
- **Devices:** seen once in each audit pass: admin on tablet (pass 2) and admin on iPhone 13 (pass 1). The other 14 staff runs closed correctly.
- **What:** after tapping a nav link in the Menu panel, the new page loaded but `aria-expanded` was still `true` 400 ms later. The panel closes in a `useEffect` keyed on `pathname`. With lazy routes, the pathname can update after the new page has started rendering, so the panel can briefly cover the new page.
- **Evidence:** `staffMenu.closedAfterNav=false` in `c013c66a…/findings/responsive-nav-admin-tablet.json`. Panel screenshot: `c013c66a…/artifacts/shots/tablet/admin/nav-staff-menu.jpg`.
- **Component:** `apps/lms-spa/src/components/shell/PortalFrame.tsx:101` (`StaffMenu`).
- **Fix:** close on link activation as well as on the pathname change. For example, add `onClickCapture={(e) => { if ((e.target as Element).closest("a[href]")) setOpen(false); }}` on the panel container. Confirm by hand on an iPad.

### F8 (Info): tablet portrait (810 px) uses the phone layout
- **What:** below `lg` (1024 px), staff get the "Menu · page" bar and students get the bottom tab bar. On an 810 px iPad this works, and grids show two columns with cards about 350 px wide (`c013c66a…/artifacts/shots/tablet/admin/finance_admissions.jpg`), but there is plenty of room for a rail.
- **Odd card at the end of stat grids:** some stat grids leave a single card on the last row at two columns, for example the seven tiles on /finance/admissions.
- **Optional:** show the icon-only rail sidebar (`--td-layout-sidebar-collapsed`) from `md`. For the stat grids, use `md:grid-cols-3` or `auto-fit` so odd counts don't strand a single card. This is a design choice, not a defect.

### F9 (Medium, website, not the LMS): /courses on small phones
/courses is a Hosting redirect (`firebase.json:173`) to `https://techdrona-website.web.app/courses`, so these belong to the website repo:

| Problem | Device | Detail |
|---|---|---|
| Cookie banner overflows | 320 px | The "Accept cookies" button (`button.ck-btn`) extends past the right edge of the viewport. It is fixed-position, so it causes no page scroll, but the button is cut off. Fix: let the banner actions wrap (`flex-wrap: wrap`) and use `width: 100%` buttons under 360 px. |
| Stats tile text overflows | 320 px | The word "Certificate" in the stats tile spills out of its box. Fix: `overflow-wrap: anywhere` or a smaller `clamp()` font in the tile. |
| Small decorative text | all | The hero mock-up uses 9–10 px text (deliberately illegible art, so mark it `aria-hidden`). |
| Program-month items overflow | ≥1080 px | The program-month `<li>` items overflow their box horizontally. |
| Small footer links | phones | "Privacy Policy", "Cookie settings" and the footer course links are 17–20 px tall. |

Screenshot: `7bc01930…/artifacts/shots/phone-small/public/courses.jpg`.

## Test-harness notes (no app defect)

- **T1. Session-cap eviction.**
  - **Cause:** QA accounts are limited to 3 concurrent staff sessions and 2 student sessions (`apps/api/app/modules/admin/policy.py:51-58`). Running several builds at once for the same role, including other agents' audit specs, signed earlier runs out ("You were signed out. Please log in again.").
  - **Change to the spec:** it now signs in again inside the test when a role page bounces to /login (`relogged` field in the findings).
  - **Recommendation:** run at most one build per role at a time, or give each concurrent spec its own QA account.
- **T2. WebKit crash after a cross-origin redirect.** WebKit (`Assertion error`, MiniBrowser) died on the page after /courses, which redirects to the website. /courses now runs last in the public list.
- **T3. Full-page screenshots stretch `min-h-dvh` layouts.** Playwright enlarges the viewport for full-page capture, which leaves large blank gaps and draws the tab bar mid-page in screenshots. These are capture artefacts, not layout bugs. Judge the top of each shot.
- **T4. Probe improvements in `lib/probe.ts`.** `layoutReport()` is new; `layoutIssues()` stays compatible for older specs.
  - **New checks:**
    - tables without their own scroll container;
    - text clipped without an ellipsis;
    - text spilling out of its box;
    - fonts under 11 px;
    - overlapping controls (clipped to scroll containers);
    - content under the sticky header;
    - content that cannot scroll clear of the mobile tab bar;
    - fixed bars overlapping each other;
    - fixed layers (cookie banners, toasts) sticking out of the viewport.
  - **Noise removed:** small tap targets are now split into real targets and inline text links. The probe ignores the skip link, closed `<details>` content and the empty toast region.
- **T5. Device size.** The "phone-small" project is 320×568 (iPhone SE first generation). Add an `iPhone SE (3rd gen)`-sized project at 375×667 if that exact size must be tracked; nothing in this audit fails at 320, so it will pass there too.
