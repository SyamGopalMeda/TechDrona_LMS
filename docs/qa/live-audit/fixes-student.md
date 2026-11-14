# Fixes: student portal dead ends, empty states and shared account pages

Follow-up to `student-and-access.md` (F-1 to F-4, F-8, F-9, F-11, F-16), `admin.md` (finding 8 / M13) and `staff-portals.md` (F4). Date: 2026-11-14. Not deployed.

All paths are under `apps/lms-spa/`. Every changed `src/` file has an identical copy at the same path under `spa-overrides/`, so `npm run sync` keeps it. `apps/web` is unchanged.

| Finding | Change | Files |
|---|---|---|
| **F-2** Mock interviews: "See plans" → `/app/billing`, which has no plans | The no-package state now says "Mock interviews aren't open for you yet. Mock interviews open when your batch's placement programme starts…". The Billing link is gone. Its action is now "Build your résumé meanwhile" → `/app/resume` | `src/features/mentor/student/Mentoring.tsx` |
| **F-3** "Browse free courses" with 0 free courses (My learning, dashboard "Continue learning") | New `NoCoursesEmptyState` picks its copy from the LMS catalogue (`GET catalog/courses`). The catalogue is fetched only while the empty state is on screen. Free courses → "Browse free courses". Only paid courses → "Explore courses". None, or the call fails → "See upcoming courses", with copy about Tech Drona's upcoming batches. All three link to `/app/courses` | `src/features/learning/components/BrowseCoursesCta.tsx` (new), `MyCourses.tsx`, `src/features/dashboard/components/StudentDashboard.tsx` |
| **F-4** Course strip and cards: waitlist promise, "Coming soon" shown twice, small tap targets, 10.9 px label | **Waitlist:** the website has a real waitlist form (`tech drona/src/pages/Course.jsx`, `#register`). It appears only when registration is coming soon, not when it is closed. So `siteCourseActions` adds `waitlist` only for `regStatus === "coming_soon"`. The button reads "Join the waitlist on our website" → `<courseUrl>#register`, opens in a new tab, and says so to screen readers. The strip description mentions a waitlist only when one exists; otherwise it reads "See what's running now and what's coming next." The website-group leads in `SITE_COURSE_GROUPS` no longer promise a waitlist for running or completed courses. **Duplicate label:** `notOpenLabel()` drops the disabled "Coming soon"/"Closed" label when the status pill already says it, or when a waitlist link replaces it. **Whole card is one link:** the title link is stretched (`::after` with `inset-0`) over the card. The other links sit above it (`z-[2]`). The banner's duplicate hidden link is now a `div`. On the strip, cards are at least 7.5rem tall and action links at least 44 px. **Website link:** still opens in a new tab. It shows an external icon and has the sr-only text "(opens the Tech Drona website in a new tab)". The button reads "Course details on our website ↗". **Label size:** the family/"COURSE" label and the kicker go from 0.68/0.7rem to `text-xs` (0.75rem) | `src/features/site-catalog/components/SiteCourseCard.tsx`, `SiteCourseStrip.tsx`, `src/features/site-catalog/lib/catalog.ts` |
| **F-1** (UI side) Cards while catalog.json is blocked by CORS | Courses built only from the live state (`minimal`) show "Syllabus, fees and batch dates are on the Tech Drona website." in place of the missing tagline. They still get the waitlist and details links. The console CORS error stays until the website sends `Access-Control-Allow-Origin` (website fix pending) | `SiteCourseCard.tsx` |
| **F-8** Practice: empty Subject list and a disabled Start button | When no subjects exist, an empty state replaces the form: "No practice sets yet. Practice sets will appear when your course content is published…" | `src/features/practice/components/PracticeHub.tsx` |
| **F-9** Coding: "No problems match these filters" when no problems exist | With no filter set and on the first page: "No coding problems yet". The filter wording stays when a filter or later page is in use | `src/features/coding/components/ProblemList.tsx` |
| **F-11** `/app/orders` renders blank | New index page that redirects to `/app/billing`, which lists orders. `scripts/gen-routes.mjs` was re-run, so `src/spa/routes.gen.tsx` has the index route; `prebuild` regenerates it anyway. The page-count test now expects 205 (204 web pages plus this SPA-only page) | `src/app/app/orders/page.tsx` (new), `src/spa/routes.gen.tsx` (generated), `src/spa/spa.test.tsx` |
| **admin.md 8 / M13** Profile form asks staff for graduation year and branch | New `useAccountScope()` reads `GET me/grants` silently, as the portal switcher does. An account is a student when the grants open the Student portal (`/app`, or a `student` role). Unknown grants or errors count as student, which is the old behaviour. Graduation year and branch show only to students, and staff saves send only `full_name`, so stored values are kept. Staff copy says "Ask an administrator…" instead of "Contact support". The form waits for the scope, so staff never see the student fields flash. The "Videos playing at once" limit on the shared Devices page shows only to students | `src/features/account/lib/account-scope.ts` (new), `src/features/account/components/ProfileSettings.tsx`, `SecurityActivity.tsx` |
| **staff-portals.md F4** Account status links point at dead student routes | For staff, "Go to my dashboard" becomes "Go to the <Portal> portal". It leads to the staff shell they came from (`lastShellPortal`), or to their home portal. Admin sections resolve to `/admin`. "Check a review request" and "Contact support" (`/app/support/new`) are hidden for staff and replaced by "Back to the <Portal> portal". The video limit row is hidden for staff. Students see no change. `RestrictedStatus` takes an optional `home` prop; its default keeps the public `/account/restricted` page unchanged | `src/features/unblock/components/AccountStatus.tsx`, `RestrictedStatus.tsx` |
| **F-16** Phone Settings: "Save changes" sits under the tab bar | The save button is in a sticky bar, `bottom-[calc(4.5rem+env(safe-area-inset-bottom))]` (the 4rem tab bar plus a gap; `lg:bottom-4`). For staff, who have no tab bar, it is `bottom-4` | `ProfileSettings.tsx` |
| Student-facing staff permissions | None needed (API only) | – |

## Tests

New or extended (all under `src/`, with override copies):
- `features/mentor/student/student.test.tsx`: honest copy; no "See plans" or Billing link; résumé action.
- `features/learning/components/learning.test.tsx`:
  - the CTA with free courses, with no courses, and with only paid courses;
  - the dashboard "Continue learning" without free courses.
- `features/practice/practice.test.tsx`: the empty-subjects state (no picker, no disabled button).
- `features/coding/coding.test.tsx`: "No coding problems yet" with no filter, and the filter wording once a filter is set.
- `features/site-catalog/site-catalog.test.tsx`:
  - the stretched title link and its new-tab text;
  - the label size;
  - the minimal-card tagline;
  - the waitlist link only for coming-soon courses;
  - one "Coming soon" or "Closed" per card;
  - the strip description with and without a waitlist.
- `app/app/orders/page.test.tsx`: the redirect to `/app/billing`.
- `features/account/components/account-scope.test.tsx`:
  - `accountScope` rules;
  - profile fields for student and staff, including the PATCH body;
  - the sticky save bar;
  - the fallback when the grants call fails;
  - the video limit row.
- `features/unblock/components/unblock.test.tsx`: AccountStatus for a student and for staff.

Run (targeted, `--pool=threads --no-file-parallelism`): 13 files, **122 of 122 pass**. This includes `account.test.tsx`, `account-extra.test.tsx`, `hubs.test.tsx`, `spa.test.tsx` and the API contract test. `PracticeSession` "FE-07/FE-16" in `practice.test.tsx` failed in 2 of 4 combined runs and passed alone. It is timing-sensitive (FE-24); the code it tests was not changed.

Not run: `tsc`, build, emulators, browser (RAM rules). Type-check before deploying.

## Left open

- **Website:** add `Access-Control-Allow-Origin` for `/catalog.json` (F-1). Until then the cards stay in the minimal form, and the console shows the CORS error.
- **Nav:** hiding Mock interviews, Company paths and similar items (F-7/F-10) is in `lib/nav/portals.ts`, which belongs to another agent. The dashboard's "Mock interviews" quick action is still there; it now lands on the honest empty state.
- **Remaining student wording on shared pages:** the "This wasn't me" confirmation (`SecuritySettings.tsx`, "Your courses, progress and purchases…") and the level 2/3 restriction copy ("videos and tests").
