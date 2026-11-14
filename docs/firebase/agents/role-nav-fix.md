# Role / portal navigation fix (LMS SPA), 2026-11-13

## The reported bug

The owner has one role, `super_admin`, and `GET /me/grants` returns `portals: ["/admin"]`. They were in the Admin portal, opened the account menu and clicked **Settings**. They landed in the Student portal (Student sidebar and "Student" badge). From there the student sidebar led on to `/app/certificates`.

There were three causes:

1. `PortalShell` gives every staff portal the account link `Settings → /app/settings/profile`. Every `/app/*` page rendered inside the Student shell, so a staff member who opened Settings left their own portal.
2. The `/app` layout had no role gate. Staff portals use `StaffPortalGate`, but `/app` did not. A staff-only account could open any student page and got the student navigation.
3. `/continue` resumed any `/app/*` page for anyone. `features/hub/last-page.ts` `allowedFor()` returned `true` for every `/app` path. Once the owner had been on `/app/certificates`, the next sign-in without a deep link went `/continue` → `/app/certificates`, back into the Student portal. The module hub's LMS card and the Modules menu use the same path.

## The fix (SPA only; `apps/web` and `apps/api` were not changed)

- **Student portal gate** (`StudentPortalGate` in `features/staff-portal/StaffPortalGate.tsx`, with the decision logic in `decideStudentArea` in `features/staff-portal/access.ts`). `app/app/layout.tsx` now wraps `PortalShell` with it. It reads `me/grants` once when the portal mounts (memoised for 5 s, like `decisionFor`). It then decides on every path change:
  - **Unknown grants: Student shell, as before.** This covers no session (the shell then sends the visitor to sign-in), any API failure other than 401, and a reply without `portals`. A 401 sends the visitor to `/login?next=<page>`.
  - **The account opens the Student portal: Student shell, unchanged.** This uses `canEnterPortal(portals, "student", roleKeys)`. It covers a `student` grant, an account with no grants at all (the API answers `["/app"]`), and admin+student accounts.
  - **Shared account pages (`/app/settings/**` and `/app/account-status`) open for everyone.** For a staff member they render inside a staff shell. That is the shell of the staff portal they came from, if they may open it, so an admin using "Your Teacher Portal" stays in the Trainer shell. Otherwise it is the Student shell for an account that opens `/app`, and failing that the shell of their home portal. `PortalShell` records which portal's shell is on screen (`noteShellPortal`). One page component serves every portal, so no page logic is duplicated.
  - **Any other `/app` page sends a staff-only account to `homePortal(portals)`.** This mirrors `StaffPortalGate`, where a Student opening `/admin` lands on `/app`. An account that opens no portal sees `PortalForbidden`.
- **`allowedFor()`** (last-page memory, used by `/continue`): a student page is resumed only when `portals` includes `/app`. Shared account pages are resumed for everyone.
- **Students see exactly what they saw before:** same shell, same links, same pages. The only difference is one `GET me/grants` call when the Student portal mounts (the staff portals already make this call), and the first render waits for it.

### Files (each is also copied into `apps/lms-spa/spa-overrides/` so `npm run sync` keeps it)

| File | Change |
|---|---|
| `src/app/app/layout.tsx` | new override: `<StudentPortalGate>{(portal) => <PortalShell portal={portal}>…}</StudentPortalGate>` |
| `src/features/staff-portal/access.ts` | new override: `SHARED_ACCOUNT_PREFIXES`, `isSharedAccountPath`, `portalKeyForPrefix`, `decideStudentArea` (lines 55–105) |
| `src/features/staff-portal/StaffPortalGate.tsx` | existing override: `noteShellPortal`/`lastShellPortal`, `loadStudentGrants`, `StudentPortalGate`, `resetStudentGate` (lines 61–125) |
| `src/components/shell/PortalShell.tsx` | existing override: line 38 `useEffect(() => noteShellPortal(portal))`; the wrong comment ("me/grants always has /app") is corrected |
| `src/features/hub/last-page.ts` | new override: `allowedFor` lines 57–60 |
| tests | `features/staff-portal/staff-portal.test.tsx` (existing override, extended), `features/hub/last-page.test.ts` (new override, one assertion inverted and cases added), `components/shell/PortalShell.test.tsx` (new) |

Note: `spa-overrides/` now holds 10 source/test files. The comment in `scripts/sync-from-web.mjs` and the overrides row in `spa.md` still list the original 5; update them when convenient.

## Audit: every cross-portal navigation found

"Gate" means the link still points at `/app`, but `StudentPortalGate` now sends a staff-only account to its home portal (or keeps it in its staff shell for account pages). Students are unaffected.

| Where (apps/lms-spa/src) | From → to | Verdict | Fix |
|---|---|---|---|
| `components/shell/PortalShell.tsx:39-44` account menu "Settings" `/app/settings/profile` (staff portals) | any staff portal → Student shell | **BUG (reported)** | Gate renders the account pages inside the staff shell; the link itself is unchanged |
| `app/app/layout.tsx` (no role gate) | staff → every student page + student sidebar / Ctrl K list | **BUG (reported)** | `StudentPortalGate` |
| `features/hub/last-page.ts:57` `allowedFor` (`/continue`, module hub LMS card, ModuleSwitcher "LMS", post-login `STAFF_LANDING`) | staff → remembered `/app/*` page | **BUG** | `/app` resumed only for accounts that open `/app`; account pages for all |
| `app/modules/page.tsx:47` hub account menu "Settings" `/app/settings/profile` | hub → Student shell | **BUG** (same as row 1) | Gate (home-portal shell) |
| `lib/api/client.ts:177` `MFA_ENROL_FALLBACK = /app/settings/security/mfa` (403 `mfa_enrolment_required`, also `/continue` and `/modules`) | staff portal → Student shell | **BUG** (admins need MFA) | Gate (account page, staff shell) |
| `features/auth/lib/login-flow.ts:32` restriction level 3 → `/app/account-status` | sign-in → Student shell | **BUG** for staff | Gate (account page, staff shell) |
| `features/auth/lib/login-flow.ts:41,44` fallback `/app` when the API gives no redirect, or a `next=/app/...` | sign-in → Student portal | bug for staff only with a stale `next` | Gate |
| `features/notifications/lib/templates.ts:30-55` (account-status / security / devices links) | Student notifications only (bell and inbox are student-only) | intended | Shared pages work for all anyway |
| `app/not-found.tsx:25` "Go to dashboard" `/app` (signed in) | 404 → Student portal | bug for staff | Gate |
| `app/app/error.tsx:7` "Go to my dashboard" `/app` (error on a shared account page) | staff shell → `/app` | bug for staff | Gate |
| `components/shell/SiteHeader.tsx:225,284`, `app/(public)/page.tsx:55` "Go to dashboard" `/app` | public pages → Student portal | bug for staff | Gate |
| `features/auth/components/Verification.tsx:56,152` `/app` | email/device verification → Student portal | bug for staff | Gate |
| `features/unblock/components/RestrictedStatus.tsx:246` `/app` | `/account/restricted` → Student portal | bug for staff | Gate |
| `features/paths/components/ArticleReader.tsx:78,94` "Go to your dashboard" `/app`, breadcrumb "My paths" `/app/path/my` (non-editors on `/read/[id]`) | reader → Student portal | bug for staff readers | Gate (editors get the `/trainer` breadcrumb) |
| `features/unblock/components/AccountStatus.tsx:121` "contact support" `/app/support/new` (on the shared account-status page) | staff shell → student support page | **open, owner decision** | Gate sends staff to their home portal; see below |
| `features/unblock/components/AccountStatus.tsx:95,124`, `RestrictedStatus.tsx:224,250`, `SettingsNav.tsx`, `SecuritySettings.tsx:274,347`, `DevicesAndSessions.tsx:249` | links between the shared account pages | intended | stay in the same shell |
| `app/manifest.ts:9` PWA `start_url: /app` | installed app → Student portal | bug for staff | Gate |
| `components/shell/PortalSwitcher.tsx` (portals from `me/grants`) | any → portals the account can open | intended | — |
| `components/shell/ModuleSwitcher.tsx:22-26`, `app/modules/page.tsx` cards → `/continue` | hub ↔ modules | intended (made safe by the `allowedFor` fix) | — |
| `components/shell/PortalFrame.tsx:206` and the logo → portal root; `PortalNav.tsx` "Find a page" / Ctrl K | within the current portal's nav only | intended | — |
| `components/shell/MobileTabBar.tsx` `STUDENT_TABS` | Student shell only | intended | — |
| `components/shell/SegmentError.tsx` (each portal's `error.tsx` passes its own home) | own portal | intended | — |
| `features/admin/components/Governance.tsx:634` "Your Teacher Portal" `/trainer`; `Governance.tsx:720`, `CourseCards.tsx:107,240,283` → `/studio/courses` | Admin → Trainer / Studio | intended (admin may open both, `canEnterPortal`) | — |
| `features/trainer/shared/portal-base.ts`, `TestsList basePath`, `EvaluationView.tsx:202` (Edit link hidden for evaluators) | Trainer / Evaluator share screens | intended (already portal-aware) | — |
| `features/staff-portal/StaffPortalGate.tsx` → `homePortal()` | wrong portal → home | intended | — |
| `lib/api/client.ts:257-288` (401 → `/login?next=here`, restricted, change-password, accept-terms, session-choice) | auth pages, then back to `next` | intended; no 403 path redirects to `/app` | — |
| `app/continue/page.tsx` (`me/grants` → `ContinueRedirect`) and `last-page.ts pickContinueTarget` fallback | home portal | intended (fixed via `allowedFor`) | — |
| `spa/session.ts homeRedirect` (`/` → `/modules` or `/login`) | — | intended | — |
| Student feature components (dashboard, learning, tests, coding, practice, commerce, engage learner, paths learner, support, registration, catalog…) with `/app/*` links | used only on `/app` pages | intended (students) | Gate covers staff |

No staff-portal page (`app/admin|trainer|evaluator|studio|finance|desk|security|mentor`) or staff feature hard-codes an `/app/...` link. The only one is the account-menu Settings link above.

## Left for the owner to decide

1. **Support for staff.** "Contact support" on `/app/account-status` (and the help pages' "Open a support ticket") goes to `/app/support/new`. That is a student page, so a staff-only account is now sent to its home portal. If staff should be able to file tickets, add `/app/support` to `SHARED_ACCOUNT_PREFIXES` (one line).
2. **Dual-role users (admin + student)** keep full Student access. Settings opened from a staff portal now stays in that staff shell. Opened directly or from the Student portal, it uses the Student shell, as before.
3. The "Go to dashboard" links on public pages, 404 and verification pages still point at `/app`; the gate forwards staff to their home portal. Switching them to `/continue` would also resume students' last page, which changes student behaviour, so I left them.

## Tests

Run as `npx vitest run <files> --pool=threads --no-file-parallelism`, one run at a time:

- `src/features/staff-portal/staff-portal.test.tsx`: 19/19. That is 8 existing tests plus 11 new: `decideStudentArea` for owner, trainer, studio, evaluator, student, no-grants, admin+teacher and admin+student; and the rendered `StudentPortalGate`, where the owner's Settings opens the Admin shell, `/app/certificates` → `/admin`, the last-shell memory works, a student keeps the Student shell, a missing session skips the fetch, a 401 goes to sign-in and an API outage fails open.
- `src/features/hub/last-page.test.ts` and `ContinueRedirect.test.tsx`: pass. They include the owner case: a remembered `/app/certificates` → `/admin`.
- `src/components/shell/PortalShell.test.tsx` (new): 3/3.
- Wider regression run over `src/features/staff-portal/staff-portal.test.tsx`, `src/features/hub`, `src/components/shell`, `src/spa/spa.test.tsx` and `src/lib/nav`: **11 files, 83/83 tests passed.**
- `tsc --noEmit` could not run: the Node heap ran out of memory at about 500 MB on this PC. Types were checked by hand. Run `npm run typecheck` before the build.
- No build and no deploy were done.
