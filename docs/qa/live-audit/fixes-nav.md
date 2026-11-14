# Fixes: navigation, portal access and Admin information architecture (2026-11-14)

Source findings: `admin.md` (F1–F15, M1–M13), `staff-portals.md` (F5, F6, §4), `student-and-access.md` (F-5, F-6, F-7, F-10).
Scope: `apps/lms-spa/src` only. Every changed file under `src/` is also in `apps/lms-spa/spa-overrides/` with the same content (except `src/spa/**`, which is SPA-owned and not overwritten by `npm run sync`). **Update 2026-11-14:** src is the source of truth (sync retired 2026-11-14); edit `src/` only, `spa-overrides/` is gone.
Nothing is deleted: hidden pages keep their routes, titles and icons, and the pages that link to them still do.

Not deployed. To verify on live: rebuild (`prebuild` regenerates `src/spa/routes.gen.tsx`, which already contains the two new routes), deploy, and re-run `audit-admin`, `audit-staff` and `audit-student`.

## How the hiding works

- `lib/nav/portals.ts`
  - `NavItem.hidden`: the item stays in the registry but is not listed in the sidebar, the phone menu or Find a page.
  - `NavItem.requires: "payments"`: the item is listed only while `GET public/integrations` reports `payments: true`. While the status is unknown, the item stays hidden, so it doesn't flash in and out.
  - `visibleNav(items, { connected, only })` does the filtering.
- `components/shell/PortalShell.tsx` passes `visibleNav(def.nav, …)` to `PortalFrame` and `MobileTabBar`. It reads `useIntegrations()`, which is the same cached call the old dashboard Integrations card used, and the gate's grants.
- The raw `PORTALS[...].nav` arrays are unchanged in content. So `PortalNav` tests owned by others, and any code that looks up titles, still see every page.

## Changes

| Finding | Change | Files |
|---|---|---|
| admin M5 / M12 | The 8 gateway pages (Revenue, Orders, Refunds, Subscriptions, Invoices, Products & prices, Coupons, Reconciliation) are marked `requires: "payments"`. They come back automatically once Razorpay is connected. Admissions, Verify payments, Registrations and Fee plans stay. | `lib/nav/portals.ts`, `components/shell/PortalShell.tsx` |
| admin M4 | The Mentoring section (4 items) is hidden. | `lib/nav/portals.ts` |
| admin M7 | Corporate enquiries is hidden. | `lib/nav/portals.ts` |
| admin F10 / M6 | Security "Unblock reviews" (L3–L4) is hidden. The Security overview links to it, and Support › Unblock requests stays. `/security/approvals` and `/security/policies` were already out of the nav. | `lib/nav/portals.ts` |
| admin M6 | Security is reduced to Security overview, Incidents, Cases and Restrictions. Risk rules and Reports are hidden; the overview links to reports. | `lib/nav/portals.ts` |
| admin M3 / F10 | Question review is hidden. It duplicates Studio "Review queue", which the Admin can open. | `lib/nav/portals.ts` |
| admin M9 | Feature flags and Break-glass are hidden from the nav and linked from the new **Settings › System status** page ("Advanced tools"). The dashboard's "emergency-access session is active" alert still links to Break-glass. | `lib/nav/portals.ts`, `features/admin/components/Governance.tsx` (`SystemStatus`), `app/admin/system/page.tsx` (new route), `lib/nav/icons.ts` |
| admin M10 | `/admin/notifications` was already absent from the nav. It stays reachable by URL, as required (not deleted). | — |
| admin (result) | The listed Admin nav goes from 42 to **25 items in 9 sections** with no gateway: Overview 2, People 3, Colleges 1, Website 1, Learning 3, Payments 4, Support 2, Security 4, Settings 5. With the gateway connected, it is 33. | `lib/nav/portals.ts` |
| admin M1 / F4 | The dashboard "Active courses" tile and the "Courses" quick action now go to `/admin/courses`. On `/admin/courses`, the studio buttons now read "Open Content studio", and the empty state says content managers create courses. | `Governance.tsx`, `CourseCards.tsx` |
| admin M2 / F13 | The "Your Teacher Portal" card renders only when the Admin holds a batch `trainer` grant. Otherwise nothing is shown. The Batches quick action now says "add yourself to teach one". | `Governance.tsx` |
| admin F6 / M11 | The Integrations card moved off the dashboard to Settings › System status (`/admin/system`). | `Governance.tsx`, `app/admin/system/page.tsx` |
| admin M12 | The dashboard "Payments" KPI (gateway orders) is replaced by **"Payments to verify"**, from `admin/admissions/overview`: `pending_claims` plus the amount waiting, linking to `/finance/admissions/verify`. The "Sales, last 30 days" card is replaced by an **Admissions** card (Registered/enrolled, Verified fees). The gateway Sales card shows only while `payments` is connected. The quick action "Payments & revenue" became "Admissions & fees" → `/finance/admissions`. | `Governance.tsx` |
| admin F12 | The UI knows the auth mode through `useSimpleAuth()` (`GET public/integrations` → `simple_auth`). Under simple auth: Role grants says "Removing an Admin role needs a second admin to approve". The API still sends privileged *revokes* to dual control (`rbac/router.py:289`), but grants apply at once (`:208`). The grant dialog no longer says "another admin must approve" and shows "Grant" instead of "Request grant". The Approvals queue drops "Approving asks you to confirm again", because step-up is always fresh under simple auth (`sessions/resolver.py:107`). With simple auth off, the copy is unchanged. | `Governance.tsx`, `ApprovalsQueue.tsx` |
| admin F1 | **College Data Portal not deployed.** A new SPA-only route, `app/college-portal/[[...path]]/page.tsx`, shows "College Data Portal is being moved … available here again soon", with "Back to Admin" and "All modules" links. Hosting serves static portal files before the SPA fallback, so this page appears only while the portal is missing. If the page is reached by client routing, it reloads once as a document, so a deployed portal is never shadowed. `/admin/college-data` now probes `/college-portal/index.html`. When the probe returns 404/5xx, or returns the LMS app shell (`<div id="root">`, which is what Hosting's `** → /index.html` fallback serves with HTTP 200), the page shows the same message instead of a frame blocked by `frame-ancestors 'none'`. If the probe fails (network), the page behaves as before. All entry points are kept: sidebar, dashboard hero, quick action, Modules menu, `/modules` card (both go through `/continue` → document load), and "Open full screen". | `features/college-data/availability.tsx` (new), `features/college-data/CollegePortalFallback.tsx` (new), `features/college-data/CollegeDataPortal.tsx`, `app/college-portal/[[...path]]/page.tsx` (new), `src/spa/routes.gen.tsx` (regenerated) |
| admin F2 / student F-5 | **Admin in Studio.** `catalogue.py` gives `super_admin` only `course.archive`, `question.review` and `question.publish` among the studio permissions. So for an Admin without `content_manager`, `studioAccess()` returns `"admin"`. `StaffPortalGate` (`StudioScope`) then allows only `/studio/courses/**` and `/studio/review/**` and redirects every other `/studio` URL (dashboard, taxonomy, questions, banks, reported errors, coding, media, companies, template mocks) to `/studio/courses`. The Studio nav shows only Review queue, Courses and Account settings. The gate now shares the `me/grants` it already reads through `useStaffGrants()`. RBAC is unchanged. | `features/staff-portal/access.ts`, `features/staff-portal/StaffPortalGate.tsx`, `components/shell/PortalShell.tsx` |
| admin F3 | **Portal switcher.** The new `switcherPortals(portals, roleKeys)` lists the portals in `portals`, the portals whose role the caller holds (any scope), and, for an Admin, the Content studio. Trainer and Evaluator are listed only with that grant. So an Admin in Studio or Teacher always sees "Switch portal → Admin". The current-portal mark also works on the Admin sections (`/finance`, `/desk`…). | `components/shell/PortalSwitcher.tsx`, `features/staff-portal/access.ts` |
| student F-7 | Hidden from the student sidebar: Company paths, Mock interviews, Billing, My access, My paths and Free diagnostic. Their URLs, the dashboard and the Interview prep hub links still work. | `lib/nav/portals.ts` |
| student F-10 | Notifications (the header bell covers it) and Profile & settings (account menu → Settings) are hidden from the sidebar. | `lib/nav/portals.ts` |
| student F-6 | **Kept both** Explore courses and My registrations. The pages don't support a merge: `/app/courses` has only a header link to registrations and no tabs, and `/app/registrations` is not under `/app/courses`, so a merged item would never be highlighted. My registrations has real data (registration and payment status) for students who registered. | — |
| student (result) | The student sidebar has **15 items**: Dashboard; Learn 7 (My learning, My classes, Explore courses, My registrations, Assignments, Live activities, Certificates); Practice & tests 4; Placement 2 (Interview prep, Résumé builder); Account 1 (Support). The mobile tab bar targets (`/app`, `/app/learning`, `/app/practice`, `/app/tests`) are all still listed, and the More sheet gets the filtered list. | `lib/nav/portals.ts` |
| staff-portals §4 | The Evaluator Integrity dialog no longer offers "Invalidate the attempt" (`outcomesFor(evaluateOnly)`), because `attempt.invalidate` is trainer-only. The evaluator page passes `evaluateOnly`. The trainer dialog is unchanged. | `features/trainer/components/Integrity.tsx`, `app/evaluator/integrity/page.tsx` |
| staff-portals F5 | The Evaluator Tests empty state reads "Tests assigned to your batches appear here when students submit attempts." | `features/trainer/components/TestsList.tsx` |
| staff-portals F1 / student F-13 | Left as is: the API agent is fixing the evaluator batch 403. The UI call is unchanged. | — |
| staff-portals F6 | An "Account settings" (`/app/settings/profile`) item was added to the Admin (Settings section), Trainer, Evaluator and Studio navs, so Find a page → "settings" finds it. The palette *is* the nav data, so this item also shows in those sidebars. The PortalNav search algorithm is untouched (owned by another agent). | `lib/nav/portals.ts` |

## Decisions

1. **Gateway gating is dynamic.** It follows `public/integrations.payments`, not a static flag, so the pages reappear when Razorpay is connected. While the status is unknown or the call fails, the pages stay hidden. Their URLs keep working.
2. **Approvals stays in the nav.** Even under simple auth, privileged revokes, policy changes and MFA resets are still dual-controlled.
3. **Break-glass:** activation is retired, and the API answers 405. The history page is linked from System status and from the dashboard alert, so it does not need a sidebar slot.
4. **25 Admin items instead of about 22.** The extra items are "System status" (the new home for Integrations, Feature flags and Break-glass) and "Account settings" (required for Find a page). Above PortalNav's collapse threshold of 24, sections start collapsed except the current one.
5. **Website Admin Panel stays.** It is out of scope here (F5: SSO). Its label is unchanged, because nav labels must not contain parentheses (existing test).
6. **Admin studio scope** covers course detail pages (`/studio/courses/**`). Viewing works for Admin, and course *editing* actions are still authorised by the API (`course.edit` is Content-manager only).
7. **Student "My registrations" kept** (see F-6 above), so the student nav has 15 items, the top of the 13–15 target.
8. **College portal detection** checks the response *content*, not only the status. Hosting's SPA fallback returns HTTP 200, so a HEAD/404 check alone would never fire.

## Tests

Run individually with `npx vitest run <file> --pool=threads --no-file-parallelism`:

- `src/lib/nav/portals.test.ts`: 14 passed. New `visibleNav` tests: Admin count and sections, gateway on/off/unknown, registry keeps hidden pages, student 13–15 items with tab targets kept, staff settings entry, `only`.
- `src/features/staff-portal/staff-portal.test.tsx`: 26 passed. New: `studioAccess`, `adminStudioRedirect`, rendered Studio gate redirect and allow for Admin and Content manager, `switcherPortals`.
- `src/components/shell/PortalShell.test.tsx`: 7 passed. New: Admin nav without gateway, gateway appears when connected, Admin-in-Studio nav, Content manager full nav.
- `src/components/shell/shell.test.tsx` and `nav-shell.test.tsx`: passed, unchanged.
- `src/features/admin/components/admin.test.tsx`: passed. Dashboard: `/admin/courses` links, Payments to verify, Verified fees, no Sales card and no Integrations card without a gateway; Sales card with a gateway; System status; simple-auth Role grants and Approvals copy.
- `src/features/admin/components/teacher-portal.test.tsx`: 3 passed. The card is now absent without a trainer grant.
- `src/features/admin/components/course-cards.test.tsx`: passed.
- `src/features/trainer/components/evaluator-nav.test.tsx` (new): 2 passed. Integrity outcomes, evaluator empty-state copy.
- `src/features/trainer/components/trainer.test.tsx`: passed, unchanged.
- `src/features/college-data/availability.test.tsx` (new) and `CollegeDataPortal.test.tsx`: passed.
- `src/spa/spa.test.tsx`: passed. `PAGE_COUNT` is now 207 (+ `/admin/system`, + `/college-portal/*`). If another agent adds a page at the same time, bump it again.
- `src/features/__contract__/api-paths.test.ts`: passed. `tsc --noEmit`: clean.

## Left for the owner

- After deploy, re-test `/college-portal/index.html` and `/admin/college-data`: both should show "being moved". Once the college portal is on Hosting, both should show the real portal with no code change.
- `/admin/system` and `/college-portal/*` are new routes, so the build must run `prebuild` (it does: `gen-routes`).
- Not done here, and owned elsewhere or out of scope: admin F5 (website SSO), F7 (catalog CORS), F8 (staff-neutral profile fields), F9 (QA accounts as synthetic), F11 (hourly reconciliation while no gateway), F14 (session eviction), student F-2, F-3, F-4, F-8, F-9, F-11.
